#!/usr/bin/env python3
"""
current_state_overview.py — vue READ-ONLY de l'« état actuel » du cerveau ARAC.

Dérive, à partir des `memory_atoms` actifs (LECTURE SEULE), un tableau de bord
de l'état courant par scope, et détecte les signaux du « cerveau vivant » :

  • coverage   : quels scopes feuilles possèdent un atome `kind=state,key=current` actif ;
  • missing    : scopes ayant assez d'atomes mais SANS état courant ;
  • dirty      : l'état courant existe mais est PLUS ANCIEN que des atomes-source
                 plus récents du même scope → à réconcilier (signal clé) ;
  • duplicate  : >1 état courant actif pour un même scope (incohérence) ;
  • stale_atoms: atomes actifs anciens (> N jours) — information potentiellement obsolète.

GARANTIES :
  - LECTURE SEULE : aucune écriture DB/atome, aucun POST, aucun appel LLM, aucun Telegram.
  - N'expose JAMAIS la `value` d'un atome (métadonnées et compteurs uniquement).
  - La logique d'analyse `analyze()` est PURE (testable sans DB).

Sortie : JSON (défaut) ou Markdown. Codes de sortie : 0 = rien à signaler,
1 = au moins un signal (dirty/missing/duplicate) à examiner.

Usage :
  sudo -E .venv/bin/python -m app.brain.current_state_overview [--markdown] [--stale-days 120] [--min-atoms 5]
  python -m app.brain.current_state_overview --fixture atoms.json      # tests/hors-ligne
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

STATE_KIND = "state"
CURRENT_KEY = "current"


# ----------------------------------------------------------------- utils
def _parse_dt(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    s = str(v).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _ts(a: dict) -> datetime | None:
    # privilégie updated_at, retombe sur created_at
    return _parse_dt(a.get("updated_at")) or _parse_dt(a.get("created_at"))


# ----------------------------------------------------------------- coeur PUR
def analyze(atoms: list[dict], now: datetime, stale_days: int = 120,
            min_atoms_for_state: int = 5) -> dict:
    """Fonction PURE. `atoms` = liste de dicts {scope,kind,key,status,created_at,updated_at,...}.
    Ne lit aucune `value`. Retourne un rapport structuré (aucune donnée sensible)."""
    active = [a for a in atoms if a.get("status") == "active"]

    scopes: dict[str, dict] = {}
    for a in active:
        sc = a.get("scope") or "(none)"
        s = scopes.setdefault(sc, {
            "scope": sc, "active_atoms": 0, "state_current_count": 0,
            "state_current_at": None, "newest_source_at": None, "kinds": {},
        })
        s["active_atoms"] += 1
        k = a.get("kind") or "(none)"
        s["kinds"][k] = s["kinds"].get(k, 0) + 1
        ts = _ts(a)
        is_state_current = (a.get("kind") == STATE_KIND and a.get("key") == CURRENT_KEY)
        if is_state_current:
            s["state_current_count"] += 1
            if ts and (s["state_current_at"] is None or ts > _parse_dt(s["state_current_at"])):
                s["state_current_at"] = ts.isoformat()
        else:
            # atome-source (tout sauf l'état courant lui-même : anti-auto-citation)
            if ts and (s["newest_source_at"] is None or ts > _parse_dt(s["newest_source_at"])):
                s["newest_source_at"] = ts.isoformat()

    coverage, missing, dirty, duplicate = [], [], [], []
    for sc, s in sorted(scopes.items()):
        has_state = s["state_current_count"] >= 1
        if s["state_current_count"] > 1:
            duplicate.append({"scope": sc, "count": s["state_current_count"]})
        if has_state:
            coverage.append({
                "scope": sc, "state_current_at": s["state_current_at"],
                "newest_source_at": s["newest_source_at"], "active_atoms": s["active_atoms"],
            })
            cur = _parse_dt(s["state_current_at"])
            src = _parse_dt(s["newest_source_at"])
            if cur and src and src > cur:
                dirty.append({
                    "scope": sc,
                    "state_current_at": s["state_current_at"],
                    "newest_source_at": s["newest_source_at"],
                    "lag_days": round((src - cur).total_seconds() / 86400.0, 1),
                })
        elif s["active_atoms"] >= min_atoms_for_state:
            missing.append({"scope": sc, "active_atoms": s["active_atoms"]})

    # atomes obsolètes (anciens) — compteur par scope, jamais de value
    stale_cut = now.timestamp() - stale_days * 86400
    stale_by_scope: dict[str, int] = {}
    for a in active:
        ts = _ts(a)
        if ts and ts.timestamp() < stale_cut:
            sc = a.get("scope") or "(none)"
            stale_by_scope[sc] = stale_by_scope.get(sc, 0) + 1
    stale_atoms = sorted(
        ({"scope": k, "count": v} for k, v in stale_by_scope.items()),
        key=lambda x: -x["count"],
    )

    report = {
        "generated_at": now.isoformat(),
        "params": {"stale_days": stale_days, "min_atoms_for_state": min_atoms_for_state},
        "summary": {
            "active_atoms": len(active),
            "scopes_total": len(scopes),
            "scopes_with_current_state": len(coverage),
            "scopes_missing_state": len(missing),
            "dirty_states": len(dirty),
            "duplicate_states": len(duplicate),
            "stale_atom_total": sum(x["count"] for x in stale_atoms),
        },
        "dirty": sorted(dirty, key=lambda x: -x["lag_days"]),
        "missing": sorted(missing, key=lambda x: -x["active_atoms"]),
        "duplicate": duplicate,
        "coverage": coverage,
        "stale_atoms": stale_atoms[:25],
    }
    return report


# ----------------------------------------------------------------- DB I/O
def fetch_atoms(dsn: str) -> list[dict]:
    import psycopg
    from psycopg.rows import dict_row
    cols = "scope, kind, key, status, created_at, updated_at"
    with psycopg.connect(dsn, connect_timeout=8, row_factory=dict_row) as c:
        c.execute("SET TRANSACTION READ ONLY")
        # #23 : filtrer côté SQL pour éviter le transit des 149 lignes non-actives.
        # Le filtre applicatif (analyze() l.63) reste en place pour le contrat --fixture.
        return c.execute(
            f"SELECT {cols} FROM arac.memory_atoms WHERE status = 'active'"
        ).fetchall()


# ----------------------------------------------------------------- rendu
def to_markdown(r: dict) -> str:
    s = r["summary"]
    L = [
        "# ARAC — Current State Overview (read-only)",
        f"_généré : {r['generated_at']} · stale>{r['params']['stale_days']}j_",
        "",
        f"- atomes actifs : **{s['active_atoms']}** · scopes : **{s['scopes_total']}**",
        f"- avec état courant : **{s['scopes_with_current_state']}** · "
        f"manquant : **{s['scopes_missing_state']}** · "
        f"dirty (à réconcilier) : **{s['dirty_states']}** · "
        f"doublons : **{s['duplicate_states']}** · atomes obsolètes : **{s['stale_atom_total']}**",
        "",
    ]
    if r["dirty"]:
        L += ["## 🔁 États courants DIRTY (sources plus récentes que l'état)"]
        L += [f"- `{d['scope']}` : retard **{d['lag_days']} j** (état {d['state_current_at']} < source {d['newest_source_at']})" for d in r["dirty"]]
        L += [""]
    if r["missing"]:
        L += ["## ➕ Scopes SANS état courant (assez d'atomes)"]
        L += [f"- `{m['scope']}` : {m['active_atoms']} atomes actifs" for m in r["missing"]]
        L += [""]
    if r["duplicate"]:
        L += ["## ⚠️ DOUBLONS d'état courant (incohérence)"]
        L += [f"- `{d['scope']}` : {d['count']} états courants actifs" for d in r["duplicate"]]
        L += [""]
    if r["stale_atoms"]:
        L += ["## 🕸️ Atomes obsolètes (top scopes)"]
        L += [f"- `{x['scope']}` : {x['count']}" for x in r["stale_atoms"][:10]]
        L += [""]
    return "\n".join(L)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Vue read-only de l'état actuel du cerveau ARAC.")
    p.add_argument("--markdown", action="store_true")
    p.add_argument("--stale-days", type=int, default=120)
    p.add_argument("--min-atoms", type=int, default=5)
    p.add_argument("--fixture", help="JSON file (liste d'atomes) pour tests/offline")
    p.add_argument("--now", help="ISO timestamp (déterminisme tests)")
    args = p.parse_args(argv)

    # #21 : distinguer --now absent (utiliser heure réelle) de --now fourni mais invalide
    # (lever une erreur explicite pour préserver le déterminisme attendu des tests).
    if args.now is not None:
        now = _parse_dt(args.now)
        if now is None:
            print(f"--now invalide (ISO attendu) : {args.now!r}", file=sys.stderr)
            return 3
    else:
        now = datetime.now(timezone.utc)

    if args.fixture:
        # #22 : utiliser un gestionnaire de contexte pour fermer le descripteur proprement
        with open(args.fixture, encoding="utf-8") as f:
            atoms = json.load(f)
    else:
        dsn = os.environ.get("DATABASE_URL_READONLY") or os.environ.get("DATABASE_URL")
        if not dsn:
            print("DATABASE_URL_READONLY/DATABASE_URL absent", file=sys.stderr)
            return 3
        try:
            atoms = fetch_atoms(dsn)
        except Exception as e:  # noqa: BLE001
            print(f"DB error: {type(e).__name__}: {str(e)[:80]}", file=sys.stderr)
            return 3

    report = analyze(atoms, now, stale_days=args.stale_days, min_atoms_for_state=args.min_atoms)
    print(to_markdown(report) if args.markdown else json.dumps(report, ensure_ascii=False, indent=2, default=str))
    sig = report["summary"]
    flagged = sig["dirty_states"] or sig["scopes_missing_state"] or sig["duplicate_states"]
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
