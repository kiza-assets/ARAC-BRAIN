#!/usr/bin/env python3
"""Scope Discovery Engine — découverte + scoring des scopes (v1, PUR, lecture seule).

Moteur générique qui remplace la liste hardcodée de 8 feuilles du reconciler. Il
**découvre les scopes réellement présents** en base (lecture seule), calcule pour
chacun un faisceau de métriques, classe sa sensibilité (via `sensitivity_policy`),
et décide s'il est **éligible** à porter/maintenir un `state:current` — avec une
**raison claire et unique** par scope.

GARANTIES :
  - LECTURE SEULE : aucune écriture DB/atome, aucun POST, aucun LLM, aucun Telegram.
    L'accès DB se fait sous `SET TRANSACTION READ ONLY` via DATABASE_URL_READONLY.
  - N'expose JAMAIS la `value` d'un atome (compteurs/métadonnées uniquement).
  - `discover()` est PURE (testable sans DB).
  - Ne décide jamais d'écrire : il dit seulement *quels scopes mériteraient une
    proposition* — la proposition (dry-run) et l'apply (humain) restent en aval.

Raisons d'éligibilité (une primaire, dérivée des données) :
  - root_level        : racine nue (un scope sans « / ») → pas d'etat courant,
                        et surtout : invisible au rappel ;
  - archived_only     : aucun atome actif (que de l'archivé/superseded) ;
  - insufficient_data : < `min_active` atomes actifs ;
  - conflict          : >1 `state:current` actif (doublon = incohérence) ;
  - dirty             : un `state:current` existe mais des sources sont plus récentes ;
  - already_current   : un `state:current` frais existe (rien à faire) ;
  - too_stale         : assez d'atomes mais tous anciens (> stale_days) ;
  - eligible          : assez d'atomes actifs récents, pas encore d'état courant.

La sensibilité (low/medium/high) est portée SÉPARÉMENT (champ `risk`/`review_level`) :
elle ne bloque jamais la *proposition* (lecture seule), seulement l'*apply* (humain).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import arac_runtime

from app.brain import sensitivity_policy as sens  # noqa: E402 — pur, aucune DB

STATE_KIND = "state"
CURRENT_KEY = "current"

# Mapping kinds → familles (mêmes conventions que le reconciler).
_DECISION_KINDS = frozenset({"decision"})
_RISK_KINDS = frozenset({"alert", "gotcha"})
_TASK_KINDS = frozenset({"todo"})
_QUESTION_KINDS = frozenset({"question"})

DEFAULT_MIN_ACTIVE = 5
DEFAULT_STALE_DAYS = 120
DEFAULT_FRESH_DAYS = 30

# Raisons (enum stable).
R_ROOT_LEVEL = "root_level"
R_ARCHIVED_ONLY = "archived_only"
R_INSUFFICIENT = "insufficient_data"
R_CONFLICT = "conflict"
R_DIRTY = "dirty"
R_ALREADY = "already_current"
R_TOO_STALE = "too_stale"
R_ELIGIBLE = "eligible"


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
    return _parse_dt(a.get("updated_at")) or _parse_dt(a.get("created_at"))


def _status(a: dict) -> str:
    """Statut normalisé (strip+lower) — fail-closed, cohérent avec memory_policy."""
    return (a.get("status") or "active").strip().lower()


def _count_statuses(atoms: list[dict]) -> dict[str, int]:
    """Compteur {statut: n} trié (lecture seule, métadonnées uniquement)."""
    out: dict[str, int] = {}
    for a in atoms:
        st = _status(a)
        out[st] = out.get(st, 0) + 1
    return dict(sorted(out.items()))


def _has_provenance(a: dict) -> bool:
    """True si l'atome porte une provenance (source_ref / source_atom_ids non vide)."""
    sr = a.get("source_ref")
    if isinstance(sr, str):
        return bool(sr.strip())
    if isinstance(sr, dict):
        return bool(sr.get("source_atom_ids") or sr.get("source_md") or sr)
    return bool(sr)


# ----------------------------------------------------------------- cœur PUR
def _readiness_score(*, reason: str, active: int,
                     min_active: int, n_decisions: int, n_tasks: int,
                     n_risks: int, fresh: bool, too_stale: bool) -> int:
    """Score 0..100 « prêt pour un état courant » — déterministe, explicable."""
    if reason in (R_ROOT_LEVEL, R_ARCHIVED_ONLY):
        return 0
    if reason == R_INSUFFICIENT:
        return min(30, round(active / max(1, min_active) * 30))
    score = 40
    score += min(30, (active // 5) * 5)          # volume (5 pts / tranche de 5)
    if n_decisions:
        score += 10
    if n_tasks or n_risks:
        score += 5
    if fresh:
        score += 15
    if too_stale:
        score -= 25
    return max(0, min(100, score))


def _analyze_one(scope: str, atoms: list[dict], now: datetime, *,
                 min_active: int, stale_days: int, fresh_days: int) -> dict:
    """Construit le rapport d'UN scope depuis SES atomes (tous statuts)."""
    active = [a for a in atoms if _status(a) == "active"]
    superseded = [a for a in atoms if _status(a) == "superseded"]
    archived = [a for a in atoms if _status(a) == "archived"]
    # Résidu : tout statut hors des 3 buckets connus (draft / low_confidence_archive
    # autorisés par memory_atoms_status_check, ou statut legacy). Calculé par
    # complémentaire pour garantir active+superseded+archived+other == total_count.
    other = [a for a in atoms
             if _status(a) not in ("active", "superseded", "archived")]

    kinds: dict[str, int] = {}
    n_decisions = n_risks = n_tasks = n_questions = 0
    n_no_provenance = 0
    state_current_count = 0
    state_current_at: datetime | None = None
    newest_source_at: datetime | None = None
    oldest_source_at: datetime | None = None
    stale_active = 0
    stale_cut = now.timestamp() - stale_days * 86400

    for a in active:
        k = a.get("kind") or "(none)"
        kinds[k] = kinds.get(k, 0) + 1
        if k in _DECISION_KINDS:
            n_decisions += 1
        if k in _RISK_KINDS:
            n_risks += 1
        if k in _TASK_KINDS:
            n_tasks += 1
        if k in _QUESTION_KINDS:
            n_questions += 1
        if not _has_provenance(a):
            n_no_provenance += 1
        ts = _ts(a)
        is_state_current = (k == STATE_KIND and a.get("key") == CURRENT_KEY)
        if is_state_current:
            state_current_count += 1
            if ts and (state_current_at is None or ts > state_current_at):
                state_current_at = ts
        else:  # atome-source (anti-auto-citation : l'état lui-même exclu)
            if ts:
                if newest_source_at is None or ts > newest_source_at:
                    newest_source_at = ts
                if oldest_source_at is None or ts < oldest_source_at:
                    oldest_source_at = ts
            if ts and ts.timestamp() < stale_cut:
                stale_active += 1

    active_count = len(active)
    is_leaf = "/" in (scope or "")
    has_state = state_current_count >= 1
    state_dirty = bool(state_current_at and newest_source_at
                       and newest_source_at > state_current_at)
    state_lag_days = (round((newest_source_at - state_current_at).total_seconds()
                            / 86400.0, 1) if state_dirty else None)
    freshness_days = (round((now - newest_source_at).total_seconds() / 86400.0, 1)
                      if newest_source_at else None)
    # `fresh` borne basse à 0 : un atome daté dans le futur (skew d'horloge / donnée
    # corrompue) ne doit pas être compté comme « frais » (freshness_days < 0).
    fresh = freshness_days is not None and 0 <= freshness_days <= fresh_days
    too_stale = (freshness_days is not None and freshness_days > stale_days)

    # --- machine à états de l'éligibilité (raison unique, ordre de priorité) ---
    if not is_leaf:
        reason, eligible, needs_proposal = R_ROOT_LEVEL, False, False
    elif active_count == 0:
        # aucun atome actif (archivé OU superseded) — étiquette historique
        # 'archived_only' (large : voir superseded_count/archived_count pour lever
        # l'ambiguïté ; rename de la valeur = contrat API, GO requis).
        reason, eligible, needs_proposal = R_ARCHIVED_ONLY, False, False
    elif active_count < min_active:
        reason, eligible, needs_proposal = R_INSUFFICIENT, False, False
    elif state_current_count > 1:
        reason, eligible, needs_proposal = R_CONFLICT, True, True
    elif has_state and state_dirty:
        reason, eligible, needs_proposal = R_DIRTY, True, True
    elif has_state:
        reason, eligible, needs_proposal = R_ALREADY, True, False
    elif too_stale:
        reason, eligible, needs_proposal = R_TOO_STALE, True, True
    else:
        reason, eligible, needs_proposal = R_ELIGIBLE, True, True

    pol = sens.classify_scope(scope)
    score = _readiness_score(
        reason=reason, active=active_count, min_active=min_active,
        n_decisions=n_decisions, n_tasks=n_tasks, n_risks=n_risks,
        fresh=fresh, too_stale=too_stale)

    return {
        "scope": scope,
        "is_leaf": is_leaf,
        "is_root_level": not is_leaf,
        "risk": pol["risk"],
        "review_level": pol["review_level"],
        "redact_content": pol["redact_content"],
        "active_count": active_count,
        "superseded_count": len(superseded),
        "archived_count": len(archived),
        "other_status_count": len(other),
        "other_statuses": _count_statuses(other),
        "total_count": len(atoms),
        "kinds": dict(sorted(kinds.items())),
        "n_decisions": n_decisions,
        "n_risks": n_risks,
        "n_tasks": n_tasks,
        "n_questions": n_questions,
        "n_active_without_provenance": n_no_provenance,
        "has_current_state": has_state,
        "current_state_count": state_current_count,
        "state_current_at": state_current_at.isoformat() if state_current_at else None,
        "newest_source_at": newest_source_at.isoformat() if newest_source_at else None,
        "oldest_source_at": oldest_source_at.isoformat() if oldest_source_at else None,
        "freshness_days": freshness_days,
        "state_dirty": state_dirty,
        "state_lag_days": state_lag_days,
        "stale_active_count": stale_active,
        "eligibility": {
            "eligible": eligible,
            "needs_proposal": needs_proposal,
            "reason": reason,
            "score": score,
        },
    }


def discover(atoms: list[dict], now: datetime | None = None, *,
             min_active: int = DEFAULT_MIN_ACTIVE,
             stale_days: int = DEFAULT_STALE_DAYS,
             fresh_days: int = DEFAULT_FRESH_DAYS) -> dict:
    """Fonction PURE. `atoms` = tous statuts confondus. Retourne le rapport complet."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:                       # robustesse : `now` naïf -> UTC
        now = now.replace(tzinfo=timezone.utc)
    by_scope: dict[str, list[dict]] = {}
    for a in (atoms or []):
        if not isinstance(a, dict):              # défense en profondeur (rows DB = dicts)
            continue
        sc = a.get("scope") or "(none)"
        by_scope.setdefault(sc, []).append(a)

    reports = [
        _analyze_one(sc, sc_atoms, now, min_active=min_active,
                     stale_days=stale_days, fresh_days=fresh_days)
        for sc, sc_atoms in sorted(by_scope.items())
    ]

    leaves = [r for r in reports if r["is_leaf"]]
    roots = [r for r in reports if r["is_root_level"]]
    eligible = [r for r in leaves if r["eligibility"]["eligible"]]
    needs = [r for r in leaves if r["eligibility"]["needs_proposal"]]

    by_reason: dict[str, int] = {}
    for r in reports:
        by_reason[r["eligibility"]["reason"]] = (
            by_reason.get(r["eligibility"]["reason"], 0) + 1)

    return {
        "report": "scope_discovery",
        "engine_version": "scope_discovery@v1",
        "dry_run": True,
        "write_allowed": False,
        "generated_at": now.isoformat(),
        "params": {"min_active": min_active, "stale_days": stale_days,
                   "fresh_days": fresh_days},
        "summary": {
            "scopes_total": len(reports),
            "leaf_scopes": len(leaves),
            "root_level_scopes": len(roots),
            "eligible_scopes": len(eligible),
            # numérateur de couverture : feuilles ÉLIGIBLES ayant déjà un état
            # courant (source unique consommée par brain.py + brain_health_report ;
            # évite le double-comptage dirty/conflict des anciens dénominateurs).
            "eligible_with_current_state": sum(1 for r in eligible
                                               if r["has_current_state"]),
            "needs_proposal_scopes": len(needs),
            "with_current_state": sum(1 for r in leaves if r["has_current_state"]),
            "with_other_status": sum(1 for r in reports if r["other_status_count"]),
            "dirty_states": sum(1 for r in leaves if r["state_dirty"]),
            "conflict_states": sum(1 for r in leaves
                                   if r["eligibility"]["reason"] == R_CONFLICT),
            "by_reason": dict(sorted(by_reason.items())),
        },
        "scopes": reports,
        "root_level_debt": sorted(
            ({"scope": r["scope"], "active_count": r["active_count"]} for r in roots
             if r["active_count"] > 0),
            key=lambda x: -x["active_count"]),
    }


def eligible_leaf_scopes(report: dict, *, needs_proposal_only: bool = True) -> list[str]:
    """Liste triée des feuilles éligibles (par défaut : celles qui méritent une
    proposition). Utilisée par le reconciler générique pour piloter `--discover`."""
    out = []
    for r in report.get("scopes", []):
        if not r.get("is_leaf"):
            continue
        elig = r.get("eligibility", {})
        if needs_proposal_only:
            if elig.get("needs_proposal"):
                out.append(r["scope"])
        elif elig.get("eligible"):
            out.append(r["scope"])
    return sorted(out)


# ----------------------------------------------------------------- DB I/O
_ALL_ATOMS_SQL = (
    "SELECT id::text, kind, scope, key, status, source_ref, "
    "created_at::text, updated_at::text "
    "FROM arac.memory_atoms ORDER BY scope, created_at, id"
)


def fetch_all_atoms(dsn: str) -> list[dict]:
    """Lecture seule de TOUS les atomes (tous statuts) — SET TRANSACTION READ ONLY."""
    import psycopg  # type: ignore[import]
    from psycopg.rows import dict_row
    with psycopg.connect(dsn, connect_timeout=8, row_factory=dict_row) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        return conn.execute(_ALL_ATOMS_SQL).fetchall()


# ----------------------------------------------------------------- rendu
def to_markdown(r: dict) -> str:
    s = r["summary"]
    L = [
        "# ARAC — Scope Discovery (read-only)",
        f"_généré : {r['generated_at']} · min_active={r['params']['min_active']} "
        f"stale>{r['params']['stale_days']}j_", "",
        f"- scopes : **{s['scopes_total']}** (feuilles **{s['leaf_scopes']}**, "
        f"racines nues **{s['root_level_scopes']}**)",
        f"- éligibles : **{s['eligible_scopes']}** · à proposer : "
        f"**{s['needs_proposal_scopes']}** · avec état : **{s['with_current_state']}** · "
        f"dirty : **{s['dirty_states']}** · conflits : **{s['conflict_states']}**",
        f"- raisons : {s['by_reason']}", "",
        "## Feuilles à proposer (needs_proposal)",
    ]
    for sc in r["scopes"]:
        if sc["is_leaf"] and sc["eligibility"]["needs_proposal"]:
            e = sc["eligibility"]
            L.append(f"- `{sc['scope']}` [{sc['risk']}] : {sc['active_count']} actifs · "
                     f"{e['reason']} · score {e['score']} · fraîcheur "
                     f"{sc['freshness_days']}j")
    if r["root_level_debt"]:
        L += ["", "## Dette root-level (atomes à re-rooter)"]
        L += [f"- `{d['scope']}` : {d['active_count']} atomes" for d in r["root_level_debt"]]
    return "\n".join(L)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Scope Discovery Engine — read-only.")
    p.add_argument("--markdown", action="store_true")
    p.add_argument("--min-active", type=int, default=DEFAULT_MIN_ACTIVE)
    p.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS)
    p.add_argument("--fresh-days", type=int, default=DEFAULT_FRESH_DAYS)
    p.add_argument("--fixture", help="JSON (liste d'atomes) pour tests/offline")
    p.add_argument("--now", help="ISO timestamp (déterminisme tests)")
    p.add_argument("--eligible-only", action="store_true",
                   help="N'imprime que la liste des feuilles à proposer (une par ligne).")
    args = p.parse_args(argv)

    now = _parse_dt(args.now) or datetime.now(timezone.utc)
    if args.fixture:
        data = json.loads(open(args.fixture, encoding="utf-8").read())
        atoms = data.get("atoms", data) if isinstance(data, dict) else data
    else:
        dsn = os.environ.get("DATABASE_URL_READONLY") or os.environ.get("DATABASE_URL")
        if not dsn:
            print("DATABASE_URL_READONLY/DATABASE_URL absent", file=sys.stderr)
            return 3
        try:
            atoms = fetch_all_atoms(dsn)
        except Exception as e:  # noqa: BLE001
            print(f"DB error: {type(e).__name__}: {str(e)[:80]}", file=sys.stderr)
            return 3

    report = discover(atoms, now, min_active=args.min_active,
                      stale_days=args.stale_days, fresh_days=args.fresh_days)
    if args.eligible_only:
        for sc in eligible_leaf_scopes(report):
            print(sc)
    elif args.markdown:
        print(to_markdown(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
