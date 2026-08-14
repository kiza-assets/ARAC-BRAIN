#!/usr/bin/env python3
"""Brain Health Report — snapshot consolidé READ-ONLY du « cerveau vivant » (v1).

Agrège en UN rapport JSON+Markdown stable tous les signaux read-only déjà produits :
  - comptage des atomes (actif/archivé/superseded, par kind) ;
  - découverte des scopes (`scope_discovery`) + sensibilité (`sensitivity_policy`) ;
  - état courant / dirty / manquant / doublons (`current_state_overview`) ;
  - propositions en file + cycle de vie (`proposal_lifecycle`) ;
  - avertissements anti-dérive (`anti_drift`, W-STATE-001..010) ;
  - état des conversations d'ingestion (curated/pending/failed) ;
  - baseline retrieval (lecture du fichier d'éval versionné) ;
  - un `health_score` composite 0..100 et des `headline_signals` lisibles.

GARANTIES :
  - LECTURE SEULE : aucune écriture DB/atome, aucun POST, aucun LLM, aucun Telegram.
    Les accès DB sont des SELECT sous `SET TRANSACTION READ ONLY`.
  - N'expose JAMAIS la `value` d'un atome (compteurs/métadonnées uniquement).
  - `build_report()` est PUR (testable sans DB).

Usage :
  sudo -E .venv/bin/python scripts/ops/brain_health_report.py [--markdown]
       [--proposal-dir var/current_state_proposals_night]
  python scripts/ops/brain_health_report.py --fixture atoms.json   # offline
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import arac_runtime

from app.brain import scope_discovery as sd            # noqa: E402 — pur
from app.brain import current_state_overview as cso    # noqa: E402 — pur
from app.brain import anti_drift as ad                 # noqa: E402 — pur
from app.brain import sensitivity_policy as sens       # noqa: E402 — pur
from app.brain import proposal_lifecycle as lifecycle  # noqa: E402 — pur

ENGINE_VERSION = "brain_health_report@v2"
SCHEMA_VERSION = 2          # contrat machine-readable stable (cockpit/Telegram/agents)
DEFAULT_BASELINE = str(arac_runtime.path("tests", "evals", "baseline.json"))

# Sévérité globale ordonnée : ok < warn < critical < fail (fail = panne ops).
_SEV_ORDER = {"ok": 0, "info": 0, "warn": 1, "warning": 1, "critical": 2, "fail": 3}


def _max_sev(a: str, b: str) -> str:
    return a if _SEV_ORDER.get(a, 0) >= _SEV_ORDER.get(b, 0) else b


def _norm_sev(s: str) -> str:
    """Normalise les vocabulaires (anti_drift: info/warn/critical ; doctor: OK/WARN/FAIL)."""
    s = (s or "").strip().lower()
    return {"ok": "ok", "info": "ok", "warning": "warn", "warn": "warn",
            "critical": "critical", "fail": "fail"}.get(s, "warn")


# ----------------------------------------------------------------- utils
def _norm_now(now: datetime | None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _pct(num: int, den: int) -> float:
    return round(100.0 * num / den, 1) if den else 0.0


# ----------------------------------------------------------------- cœur PUR
def _atom_counts(atoms: list[dict]) -> dict:
    by_status: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for a in atoms:
        if not isinstance(a, dict):
            continue
        st = (a.get("status") or "active").strip().lower()
        by_status[st] = by_status.get(st, 0) + 1
        if st == "active":
            k = a.get("kind") or "(none)"
            by_kind[k] = by_kind.get(k, 0) + 1
    return {
        "total": sum(by_status.values()),
        "active": by_status.get("active", 0),
        "archived": by_status.get("archived", 0),
        "superseded": by_status.get("superseded", 0),
        "by_status": dict(sorted(by_status.items())),
        "by_kind": dict(sorted(by_kind.items(), key=lambda x: -x[1])),
    }


def _health_score(*, overview_summary: dict, discovery_summary: dict,
                  conversations: dict, anti_drift_summary: dict) -> int:
    """Score composite 0..100, déterministe et explicable.

    Part de 100 et retranche des pénalités bornées pour chaque signal de dérive."""
    score = 100
    elig_total = discovery_summary.get("eligible_scopes", 0)
    with_state = discovery_summary.get("eligible_with_current_state", 0)
    # couverture : pénalité proportionnelle au déficit de couverture des feuilles
    # ÉLIGIBLES (dénominateur = feuilles éligibles distinctes, sans double-comptage
    # des feuilles dirty/conflict qui sont à la fois "avec état" et "à proposer").
    if elig_total:
        coverage = with_state / elig_total
        score -= round((1 - coverage) * 40)        # jusqu'à -40
    score -= min(15, overview_summary.get("dirty_states", 0) * 5)        # dirty
    score -= min(20, overview_summary.get("duplicate_states", 0) * 10)   # doublons (lourd)
    score -= min(10, int(conversations.get("failed", 0) or 0) * 5)       # ingestion
    sev = anti_drift_summary.get("by_severity", {})
    score -= min(15, sev.get("critical", 0) * 5)                          # critiques
    return max(0, min(100, score))


def _content_severity(drift_summary: dict) -> str:
    """Sévérité du CONTENU (cerveau), dérivée de l'anti-dérive. PUR."""
    bysev = {(_norm_sev(k)): v for k, v in (drift_summary.get("by_severity") or {}).items()}
    if bysev.get("critical"):
        return "critical"
    if bysev.get("warn"):
        return "warn"
    return "ok"


def _build_signals(drift: dict) -> list[dict]:
    """Signaux machine-readable à CODE STABLE, dérivés du catalogue anti-dérive
    (W-STATE-001..010). PUR. Format figé pour cockpit/Telegram/agents."""
    out: list[dict] = []
    for w in (drift.get("warnings") or []):
        out.append({
            "code": w.get("code"),
            "severity": _norm_sev(w.get("severity")),
            "area": w.get("category") or "current_state",
            "scope": w.get("scope"),
            "message": w.get("description"),
            "action": w.get("suggested_action"),
        })
    return out


def _build_recommendations(signals: list[dict]) -> list[dict]:
    """Actions recommandées dédupliquées, priorisées par sévérité. PUR."""
    rank = {"fail": 0, "critical": 1, "warn": 2, "ok": 3}
    seen: set[str] = set()
    recs: list[dict] = []
    for s in sorted(signals, key=lambda x: rank.get(x.get("severity"), 9)):
        act = s.get("action")
        if not act or act in seen:
            continue
        seen.add(act)
        recs.append({"priority": s.get("severity"), "action": act,
                     "code": s.get("code"), "scope": s.get("scope")})
    return recs


def build_report(*, atoms: list[dict], conversations: dict | None = None,
                 proposals: list[dict] | None = None, baseline: dict | None = None,
                 current_eval: dict | None = None, now: datetime | None = None,
                 min_active: int = 5, stale_days: int = 120) -> dict:
    """Construit le rapport consolidé. PUR (toutes les données déjà chargées)."""
    now = _norm_now(now)
    atoms = atoms or []
    conversations = conversations or {}
    proposals = proposals or []

    discovery = sd.discover(atoms, now, min_active=min_active, stale_days=stale_days)
    overview = cso.analyze(atoms, now, stale_days=stale_days,
                           min_atoms_for_state=min_active)
    failed_conv = int(conversations.get("failed", 0) or 0)
    drift = ad.evaluate(discovery, overview, proposals=proposals,
                        eval_result=current_eval, failed_conversations=failed_conv,
                        now=now)
    lc_summary = lifecycle.summarize_lifecycle(proposals, now)

    disc_sum = discovery["summary"]
    ov_sum = overview["summary"]
    # Dénominateur de couverture = feuilles ÉLIGIBLES distinctes (une feuille
    # dirty/conflict ne doit PAS être comptée deux fois).
    eligible_total = disc_sum["eligible_scopes"]

    health = _health_score(overview_summary=ov_sum, discovery_summary=disc_sum,
                           conversations=conversations, anti_drift_summary=drift["summary"])

    # signaux à code stable + sévérité globale (contenu) + recommandations
    signals = _build_signals(drift)
    content_severity = _content_severity(drift["summary"])
    recommendations = _build_recommendations(signals)

    # signaux phares (lisibles, ordonnés par gravité)
    headline: list[str] = []
    if ov_sum.get("duplicate_states"):
        headline.append(f"{ov_sum['duplicate_states']} doublon(s) d'état courant "
                        "(contradiction — revue humaine).")
    if disc_sum.get("dirty_states"):
        headline.append(f"{disc_sum['dirty_states']} état(s) courant(s) dirty à réconcilier.")
    if disc_sum.get("needs_proposal_scopes"):
        headline.append(f"{disc_sum['needs_proposal_scopes']} feuille(s) éligible(s) sans "
                        "état courant (couverture à construire).")
    if failed_conv:
        headline.append(f"{failed_conv} conversation(s) d'ingestion en échec.")
    if drift["summary"].get("by_severity", {}).get("critical"):
        headline.append(f"{drift['summary']['by_severity']['critical']} avertissement(s) "
                        "anti-dérive CRITIQUES.")

    return {
        "report": "brain_health",
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": now.isoformat(),
        "dry_run": True,
        "write_allowed": False,
        # sévérité globale : ici = contenu seul ; main(--with-ops) la combine avec l'ops.
        "severity": content_severity,
        "health_score": health,
        "headline_signals": headline,
        "signals": signals,
        "recommendations": recommendations,
        "atoms": _atom_counts(atoms),
        "scopes": {
            "total": disc_sum["scopes_total"],
            "leaf": disc_sum["leaf_scopes"],
            "root_level": disc_sum["root_level_scopes"],
            "eligible_needs_proposal": disc_sum["needs_proposal_scopes"],
            "by_reason": disc_sum["by_reason"],
            "root_level_debt": discovery["root_level_debt"],
        },
        "current_state": {
            # couverture leaf-only et cohérente : with_current_state (numérateur) et
            # eligible_leaf_total (dénominateur) portent sur les MÊMES feuilles
            # éligibles → coverage_pct = with_current_state / eligible_leaf_total.
            "with_current_state": disc_sum["eligible_with_current_state"],
            "missing": ov_sum["scopes_missing_state"],
            "dirty": ov_sum["dirty_states"],
            "duplicate": ov_sum["duplicate_states"],
            # contradictions = états courants en doublon (incohérence à arbitrer).
            "contradictions": ov_sum["duplicate_states"],
            # stale = feuilles assez fournies mais toutes anciennes (> stale_days).
            "stale": disc_sum["by_reason"].get("too_stale", 0),
            "eligible_leaf_total": eligible_total,
            "coverage_pct": _pct(disc_sum["eligible_with_current_state"], eligible_total),
        },
        "conversations": {
            "total": int(conversations.get("total",
                         sum(v for v in conversations.values() if isinstance(v, int)))),
            "curated": int(conversations.get("curated", 0) or 0),
            "pending": int(conversations.get("pending", 0) or 0),
            "failed": failed_conv,
        },
        "proposals": {
            "total": lc_summary["total"],
            "by_state": lc_summary["by_state"],
            "expired_due": lc_summary["expired_due"],
            "awaiting_human_review": lc_summary["awaiting_human_review"],
        },
        "sensitivity": sens.summary(),
        "anti_drift": {
            "total": drift["summary"]["total"],
            "by_severity": drift["summary"]["by_severity"],
            "by_code": drift["summary"]["by_code"],
            "top": drift["warnings"][:10],
        },
        "eval": {
            "baseline": baseline or None,
            "current": current_eval or None,
        },
    }


# ----------------------------------------------------------------- DB I/O (read-only)
_CONV_SQL = "SELECT status, count(*) AS n FROM arac.raw_conversations GROUP BY status"


def fetch_conversations(dsn: str) -> dict:
    """Compte des conversations par statut (lecture seule). {} si la table manque."""
    import psycopg
    from psycopg.rows import dict_row
    out: dict[str, int] = {}
    try:
        with psycopg.connect(dsn, connect_timeout=8, row_factory=dict_row) as c:
            c.execute("SET TRANSACTION READ ONLY")
            for row in c.execute(_CONV_SQL).fetchall():
                out[(row["status"] or "?").strip().lower()] = int(row["n"])
    except Exception:  # noqa: BLE001 — table absente / erreur : on dégrade proprement
        return {}
    out["total"] = sum(out.values())
    return out


def load_proposals(proposal_dir: str | None) -> list[dict]:
    """Charge les propositions stockées (lecture seule, confinée). [] si absent."""
    if not proposal_dir or not os.path.isdir(proposal_dir):
        return []
    try:
        import current_state_proposal_store as store
        return store.list_proposals(proposal_dir)
    except Exception:  # noqa: BLE001
        return []


def load_baseline(path: str | None) -> dict | None:
    if not path or not os.path.isfile(path):
        return None
    try:
        return json.loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError):
        return None


# --------------------------------------------------- couche OPS (doctor, read-only)
def run_doctor_ops(timeout: int = 60) -> dict:
    """Exécute `arac-doctor.sh --json` (read-only) et renvoie sa sortie enrichie
    d'un agrégat `by_level`. {error:...} en cas d'échec (jamais d'exception remontée).

    Réservé au CLI/cron : l'API web (process arac user) ne shell-out PAS vers le doctor.
    """
    import subprocess
    doctor = str(arac_runtime.path("scripts", "ops", "arac-doctor.sh"))
    if not os.path.isfile(doctor):
        return {"error": "arac-doctor.sh introuvable", "overall": "unknown", "checks": []}
    try:
        proc = subprocess.run(["bash", doctor, "--json"], capture_output=True,
                              text=True, timeout=timeout)
        data = json.loads(proc.stdout or "{}")
    except Exception as e:  # noqa: BLE001 — dégradation propre
        return {"error": f"{type(e).__name__}: {str(e)[:80]}", "overall": "unknown",
                "checks": []}
    by_level: dict[str, int] = {}
    for c in data.get("checks", []):
        by_level[c.get("level", "?")] = by_level.get(c.get("level", "?"), 0) + 1
    data["by_level"] = by_level
    return data


def ops_severity(ops: dict) -> str:
    """Sévérité de la couche OPS dérivée de `overall` du doctor (OK/WARN/FAIL)."""
    if ops.get("error"):
        return "warn"           # doctor injoignable = signal d'attention, pas une panne
    return _norm_sev(ops.get("overall", "warn"))


# ----------------------------------------------------------------- rendu
def to_markdown(r: dict) -> str:
    a, sc, cs = r["atoms"], r["scopes"], r["current_state"]
    cv, pr, dr = r["conversations"], r["proposals"], r["anti_drift"]
    sev = r.get("severity", "ok").upper()
    L = [
        "# ARAC — Brain Health Report (read-only)",
        f"_généré : {r['generated_at']} · moteur {r['engine_version']} · "
        f"schéma v{r.get('schema_version', '?')}_", "",
        f"## Sévérité globale : **{sev}** · Score de santé : **{r['health_score']}/100**",
    ]
    if r["headline_signals"]:
        L += ["", "### Signaux phares"]
        L += [f"- {s}" for s in r["headline_signals"]]
    L += [
        "", "## Atomes",
        f"- actifs **{a['active']}** · archivés {a['archived']} · superseded {a['superseded']} "
        f"· total {a['total']}",
        f"- top kinds : {dict(list(a['by_kind'].items())[:8])}",
        "", "## Scopes & état courant",
        f"- scopes {sc['total']} (feuilles {sc['leaf']}, racines nues {sc['root_level']})",
        f"- couverture état courant : **{cs['coverage_pct']}%** "
        f"({cs['with_current_state']}/{cs['eligible_leaf_total']} feuilles éligibles)",
        f"- dirty **{cs['dirty']}** · doublons **{cs['duplicate']}** · "
        f"feuilles à proposer **{sc['eligible_needs_proposal']}**",
        f"- sensibilité : {r['sensitivity']['by_risk']}",
        "", "## Propositions (cycle de vie)",
        f"- total {pr['total']} · par état {pr['by_state']}",
        f"- en attente de revue humaine : {len(pr['awaiting_human_review'])} · "
        f"expirées dues : {len(pr['expired_due'])}",
        "", "## Conversations d'ingestion",
        f"- curated {cv['curated']} · pending {cv['pending']} · **failed {cv['failed']}** "
        f"· total {cv['total']}",
        "", "## Anti-dérive",
        f"- avertissements **{dr['total']}** · sévérité {dr['by_severity']}",
        f"- par code : {dr['by_code']}",
    ]
    L += [
        f"- contradictions **{cs.get('contradictions', 0)}** · stale **{cs.get('stale', 0)}** "
        f"· manquants **{cs['missing']}**",
    ]
    if r["scopes"]["root_level_debt"]:
        L += ["", "## Dette root-level"]
        L += [f"- `{d['scope']}` : {d['active_count']} atomes"
              for d in r["scopes"]["root_level_debt"]]
    bl = (r["eval"] or {}).get("baseline") or {}
    if bl:
        L += ["", "## Retrieval (baseline)", f"- {json.dumps(bl, ensure_ascii=False)[:300]}"]
    if r.get("recommendations"):
        L += ["", "## Actions recommandées"]
        L += [f"- [{rec['priority']}] {rec['action']}"
              + (f" (`{rec['scope']}`)" if rec.get("scope") else "")
              for rec in r["recommendations"][:10]]
    ops = r.get("ops")
    if ops:
        L += ["", "## Ops (arac-doctor)",
              f"- overall : **{ops.get('overall', '?')}** · par niveau : {ops.get('by_level', {})}"]
        if ops.get("error"):
            L += [f"- ⚠️ doctor : {ops['error']}"]
        else:
            L += [f"- [{c['level']}] {c['check']} : {c['detail']}"
                  for c in ops.get("checks", []) if c.get("level") != "OK"]
    return "\n".join(L)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Brain Health Report — read-only.")
    p.add_argument("--json", action="store_true", help="Sortie JSON (défaut si ni --markdown ni --quiet).")
    p.add_argument("--markdown", action="store_true")
    p.add_argument("--fixture", help="JSON (liste d'atomes) pour tests/offline")
    p.add_argument("--proposal-dir",
                   default=str(arac_runtime.var_dir() / "current_state_proposals_night"))
    p.add_argument("--baseline", default=DEFAULT_BASELINE)
    p.add_argument("--min-active", type=int, default=5)
    p.add_argument("--stale-days", type=int, default=120)
    p.add_argument("--now", help="ISO timestamp (déterminisme tests)")
    p.add_argument("--with-ops", action="store_true",
                   help="Inclut la couche OPS via arac-doctor.sh --json (CLI/cron only).")
    p.add_argument("--quiet", action="store_true",
                   help="Sortie minimale : sévérité + score + signaux phares (JSON 1 ligne).")
    p.add_argument("--strict", action="store_true",
                   help="Code de sortie strict : 0 ssi severity=ok (warn=1, critical/fail=2).")
    args = p.parse_args(argv)

    now = ad._parse_dt(args.now) or datetime.now(timezone.utc)
    conversations: dict = {}
    if args.fixture:
        data = json.loads(open(args.fixture, encoding="utf-8").read())
        atoms = data.get("atoms", data) if isinstance(data, dict) else data
    else:
        dsn = os.environ.get("DATABASE_URL_READONLY") or os.environ.get("DATABASE_URL")
        if not dsn:
            print("DATABASE_URL_READONLY/DATABASE_URL absent", file=sys.stderr)
            return 3
        try:
            atoms = sd.fetch_all_atoms(dsn)
        except Exception as e:  # noqa: BLE001
            print(f"DB error: {type(e).__name__}: {str(e)[:80]}", file=sys.stderr)
            return 3
        conversations = fetch_conversations(dsn)

    report = build_report(
        atoms=atoms, conversations=conversations,
        proposals=load_proposals(args.proposal_dir),
        baseline=load_baseline(args.baseline), now=now,
        min_active=args.min_active, stale_days=args.stale_days)

    # Couche OPS optionnelle : combine la sévérité contenu avec celle du doctor.
    if args.with_ops:
        ops = run_doctor_ops()
        report["ops"] = ops
        report["severity"] = _max_sev(report["severity"], ops_severity(ops))

    if args.quiet:
        print(json.dumps({
            "report": "brain_health", "schema_version": report["schema_version"],
            "generated_at": report["generated_at"], "severity": report["severity"],
            "health_score": report["health_score"],
            "headline_signals": report["headline_signals"],
        }, ensure_ascii=False, default=str))
    elif args.markdown:
        print(to_markdown(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))

    sev = report["severity"]
    if args.strict:
        return {"ok": 0, "warn": 1, "critical": 2, "fail": 2}.get(sev, 1)
    # défaut (non strict) : 2 si panne (critical/fail) ; sinon 1 si signal d'attention
    # (score < 70 OU doublon d'état courant) ; 0 sinon. Rétro-compatible.
    if sev in ("critical", "fail"):
        return 2
    flagged = report["health_score"] < 70 or report["current_state"]["duplicate"] > 0
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())
