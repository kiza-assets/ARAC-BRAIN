#!/usr/bin/env python3
"""Anti-Drift Warning Catalog — détection des dérives de l'« état courant » (v1, PUR).

Moteur PUR (aucune DB, aucun réseau, aucune écriture, aucune mutation d'atome) qui
**agrège les signaux** déjà produits par d'autres moteurs read-only (scope_discovery,
current_state_overview, le store de propositions, les évals retrieval) et en dérive un
**catalogue d'avertissements anti-dérive** déterministe et explicable.

Son but : repérer tôt les dérives silencieuses du « cerveau vivant » avant qu'elles ne
polluent le recall — états manquants, états dirty, doublons d'état (contradictions),
propositions expirées ou peu confiantes, dette root-level, provenance douteuse, échecs
d'ingestion, régression de l'éval retrieval.

GARANTIES (non négociables, cf raison d'être du projet) :
  - PUR : `evaluate()` ne fait AUCUN I/O. Le CLI ne lit que des fichiers JSON fournis
    explicitement (`--discovery-json` / `--overview-json`), jamais la DB ni le réseau.
  - AUCUNE écriture, AUCUNE mutation d'atome. On ne propose ici que des *actions* (texte).
  - N'expose JAMAIS la `value` d'un atome : uniquement scopes, ids, compteurs, métadonnées.
  - Déterministe : pour une même entrée, exactement la même sortie (tri stable).
  - Robuste : tolère les clés manquantes, les entrées `None`, un `now` naïf.

Chaque avertissement (`warning`) a EXACTEMENT ces clés :
  code, severity, scope, description, sources, suggested_action, auto_fix_available, category.

`auto_fix_available=True` ne signifie JAMAIS « écriture automatique » : il signale qu'une
remédiation **dry-run** (proposition de réconciliation) est disponible en aval. L'apply
réel reste un geste humain.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# ----------------------------------------------------------------- sévérités
SEV_INFO = "info"
SEV_WARN = "warn"
SEV_CRITICAL = "critical"

# Rang de tri (plus haut = plus grave en tête).
_SEV_RANK = {SEV_CRITICAL: 0, SEV_WARN: 1, SEV_INFO: 2}

# ----------------------------------------------------------------- codes (enum stable)
W_STATE_001 = "W-STATE-001"   # feuille à proposer SANS état courant (coverage)
W_STATE_002 = "W-STATE-002"   # état courant dirty (freshness)
W_STATE_003 = "W-STATE-003"   # état présent mais sources sans provenance (provenance)
W_STATE_004 = "W-STATE-004"   # doublon d'état courant = contradiction (contradiction)
W_STATE_005 = "W-STATE-005"   # proposition expirée (lifecycle)
W_STATE_006 = "W-STATE-006"   # proposition à faible confiance (confidence)
W_STATE_007 = "W-STATE-007"   # dette root-level (root-debt)
W_STATE_008 = "W-STATE-008"   # feuille à proposer SANS proposition existante (coverage)
W_STATE_009 = "W-STATE-009"   # conversations d'ingestion en échec (ingestion)
W_STATE_010 = "W-STATE-010"   # régression de l'éval retrieval (retrieval)

ENGINE_VERSION = "anti_drift@v1"


# ----------------------------------------------------------------- utils PURS
def _parse_dt(v) -> datetime | None:
    """Parse souple en datetime tz-aware (UTC par défaut). None si illisible."""
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


def _norm_now(now: datetime | None) -> datetime:
    """Normalise `now` en UTC tz-aware (robustesse : naïf -> UTC)."""
    now = now or datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _num(v) -> float | None:
    """Convertit en float si possible, sinon None (défense en profondeur)."""
    if isinstance(v, bool):  # bool est un int en Python : on l'exclut explicitement
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _warn(*, code: str, severity: str, scope: str | None, description: str,
          sources: list[str], suggested_action: str, auto_fix_available: bool,
          category: str) -> dict:
    """Fabrique un warning au schéma EXACT (8 clés). `sources` est copié + dédoublonné
    en préservant l'ordre (jamais de `value` : uniquement scopes/ids/compteurs)."""
    seen: set[str] = set()
    clean_sources: list[str] = []
    for s in sources or []:
        s = str(s)
        if s not in seen:
            seen.add(s)
            clean_sources.append(s)
    return {
        "code": code,
        "severity": severity,
        "scope": scope,
        "description": description,
        "sources": clean_sources,
        "suggested_action": suggested_action,
        "auto_fix_available": bool(auto_fix_available),
        "category": category,
    }


# ----------------------------------------------------------------- règles (PURES)
def _rules_from_scopes(scopes: list[dict], proposals_by_scope: dict[str, list[dict]] | None,
                       *, root_debt: list[dict], root_debt_threshold: int) -> list[dict]:
    """Règles dérivées des scopes de discovery (W-STATE 001/002/003/004/008) + root-debt (007)."""
    out: list[dict] = []
    for sc in scopes:
        if not isinstance(sc, dict):
            continue
        scope = sc.get("scope")
        is_leaf = bool(sc.get("is_leaf"))
        elig = sc.get("eligibility") or {}
        needs = bool(elig.get("needs_proposal"))
        has_state = bool(sc.get("has_current_state"))
        current_state_count = int(sc.get("current_state_count") or 0)
        n_no_prov = int(sc.get("n_active_without_provenance") or 0)

        # W-STATE-004 : doublon d'état courant = contradiction (critical, jamais auto-fix)
        if current_state_count > 1:
            out.append(_warn(
                code=W_STATE_004, severity=SEV_CRITICAL, scope=scope,
                description=(f"{current_state_count} états courants actifs sur `{scope}` "
                            "(doublon = contradiction, recall non déterministe)."),
                sources=[scope],
                suggested_action=("trancher manuellement : superseder les doublons pour "
                                  "ne garder qu'un seul state:current (revue humaine requise)."),
                auto_fix_available=False, category="contradiction"))

        # W-STATE-002 : état courant dirty (sources plus récentes que l'état)
        if sc.get("state_dirty"):
            lag = sc.get("state_lag_days")
            out.append(_warn(
                code=W_STATE_002, severity=SEV_WARN, scope=scope,
                description=(f"État courant de `{scope}` en retard de {lag} j sur des "
                            "sources plus récentes (state dirty)."),
                sources=[scope],
                suggested_action="réconcilier (supersede proposé).",
                auto_fix_available=True, category="freshness"))

        # W-STATE-003 : état présent mais des actifs sans provenance (risque de citation)
        if has_state and n_no_prov > 0:
            out.append(_warn(
                code=W_STATE_003, severity=SEV_WARN, scope=scope,
                description=(f"`{scope}` a un état courant et {n_no_prov} atome(s) actif(s) "
                            "sans provenance : l'état courant peut citer des sources sans "
                            "provenance (risque, non confirmé ici)."),
                sources=[scope],
                suggested_action=("auditer la provenance des atomes-sources du scope avant "
                                  "de se fier à l'état courant (revue humaine)."),
                auto_fix_available=False, category="provenance"))

        # Règles « feuille à proposer » (W-STATE-001 / W-STATE-008)
        if is_leaf and needs:
            # W-STATE-001 : feuille à proposer SANS état courant
            if not has_state:
                out.append(_warn(
                    code=W_STATE_001, severity=SEV_WARN, scope=scope,
                    description=(f"Feuille `{scope}` éligible à un état courant mais SANS "
                                "state:current (couverture manquante)."),
                    sources=[scope],
                    suggested_action=("générer une proposition state:current "
                                      "(reconciler --discover, dry-run)."),
                    auto_fix_available=True, category="coverage"))
            # W-STATE-008 : feuille à proposer pour laquelle AUCUNE proposition n'existe
            if proposals_by_scope is not None and not proposals_by_scope.get(scope):
                out.append(_warn(
                    code=W_STATE_008, severity=SEV_WARN, scope=scope,
                    description=(f"Feuille `{scope}` éligible (needs_proposal) mais aucune "
                                "proposition en file (gap de couverture)."),
                    sources=[scope],
                    suggested_action=("générer une proposition state:current pour ce scope "
                                      "(reconciler --discover, dry-run)."),
                    auto_fix_available=True, category="coverage"))

    # W-STATE-007 : dette root-level (atomes posés sur une racine nue)
    for d in root_debt or []:
        if not isinstance(d, dict):
            continue
        active = int(d.get("active_count") or 0)
        if active >= root_debt_threshold:
            scope = d.get("scope")
            out.append(_warn(
                code=W_STATE_007, severity=SEV_WARN, scope=scope,
                description=(f"Racine nue `{scope}` porte {active} atomes actifs "
                            "(dette root-level, devraient vivre sous une feuille)."),
                sources=[scope],
                suggested_action=("proposer un re-rooting de ces atomes vers des scopes "
                                  "feuilles (proposition uniquement, apply humain)."),
                auto_fix_available=False, category="root-debt"))
    return out


def _rules_from_proposals(proposals: list[dict], *, now: datetime,
                          low_confidence_threshold: int) -> list[dict]:
    """Règles dérivées des propositions en file (W-STATE-005 expirées, W-STATE-006 confiance)."""
    out: list[dict] = []
    for p in proposals or []:
        if not isinstance(p, dict):
            continue
        scope = p.get("scope")
        pid = p.get("id") or p.get("proposal_id")
        src = [str(x) for x in (scope, pid) if x is not None] or [str(scope)]

        # W-STATE-005 : proposition expirée (status==expired OU expires_at < now)
        status = (p.get("status") or "").strip().lower()
        expires_at = _parse_dt(p.get("expires_at"))
        is_expired = (status == "expired") or (expires_at is not None and expires_at < now)
        if is_expired:
            out.append(_warn(
                code=W_STATE_005, severity=SEV_WARN, scope=scope,
                description=(f"Proposition expirée sur `{scope}` "
                            f"(status={status or 'n/a'}, expires_at={p.get('expires_at')})."),
                sources=src,
                suggested_action=("clore ou régénérer la proposition expirée "
                                  "(reconciler --discover, dry-run)."),
                auto_fix_available=False, category="lifecycle"))

        # W-STATE-006 : proposition à faible confiance
        conf = _num(p.get("confidence_score"))
        if conf is not None and conf < low_confidence_threshold:
            out.append(_warn(
                code=W_STATE_006, severity=SEV_INFO, scope=scope,
                description=(f"Proposition à faible confiance sur `{scope}` "
                            f"(confidence_score={conf:g} < {low_confidence_threshold})."),
                sources=src,
                suggested_action=("revoir manuellement avant apply : enrichir les sources "
                                  "ou écarter la proposition (revue humaine)."),
                auto_fix_available=False, category="confidence"))
    return out


def _rule_failed_conversations(failed_conversations: int) -> list[dict]:
    """W-STATE-009 : échec(s) d'ingestion de conversations (un seul warning global)."""
    n = int(failed_conversations or 0)
    if n <= 0:
        return []
    return [_warn(
        code=W_STATE_009, severity=SEV_WARN, scope=None,
        description=(f"{n} conversation(s) d'ingestion en échec : des sources potentielles "
                    "n'ont pas rejoint le cerveau (dérive par sous-alimentation)."),
        sources=["ingestion"],
        suggested_action=("inspecter le pipeline d'ingestion (logs, ARAC_INGEST_ALLOWED_NODES, "
                          "token curator) et relancer les conversations échouées."),
        auto_fix_available=False, category="ingestion")]


def _extract_recall_pair(eval_result: dict) -> tuple[float, float | None] | None:
    """Extrait (recall_courant, baseline|None) d'un `eval_result` au schéma souple.

    Accepte les clés `recall_at_5` / `recall@5` (et `recall`) pour le courant, et
    `baseline_recall_at_5` / `baseline` (et `baseline_recall`) pour la baseline.
    Retourne None si le schéma n'est pas reconnu (skip silencieux)."""
    if not isinstance(eval_result, dict):
        return None
    cur = None
    for k in ("recall_at_5", "recall@5", "recall"):
        cur = _num(eval_result.get(k))
        if cur is not None:
            break
    if cur is None:
        return None
    base = None
    for k in ("baseline_recall_at_5", "baseline_recall", "baseline"):
        base = _num(eval_result.get(k))
        if base is not None:
            break
    return (cur, base)


def _rule_eval_regression(eval_result: dict | None,
                          eval_min_recall: float | None) -> list[dict]:
    """W-STATE-010 : recall courant sous la baseline OU sous `eval_min_recall` (critical)."""
    if eval_result is None:
        return []
    pair = _extract_recall_pair(eval_result)
    if pair is None:                         # schéma non reconnu -> skip silencieux
        return []
    cur, base = pair
    floor = _num(eval_min_recall)
    # IMPORTANT : cur, base et floor doivent partager la MÊME échelle (ratio 0-1).
    # Aucune normalisation automatique : passer --eval-min-recall en 0-1, pas en %.
    below_baseline = base is not None and cur < base
    below_floor = floor is not None and cur < floor
    if not (below_baseline or below_floor):
        return []
    bits = []
    if below_baseline:
        bits.append(f"baseline {base:g}")
    if below_floor:
        bits.append(f"seuil {floor:g}")
    return [_warn(
        code=W_STATE_010, severity=SEV_CRITICAL, scope=None,
        description=(f"Régression retrieval : recall courant {cur:g} sous "
                    f"{' et '.join(bits)} (le cerveau retrouve moins bien)."),
        sources=["eval/retrieval"],
        suggested_action=("investiguer la régression d'embeddings/recherche (changement "
                          "récent, atomes pollués) avant tout nouvel apply."),
        auto_fix_available=False, category="retrieval")]


# ----------------------------------------------------------------- orchestrateur PUR
def evaluate(discovery: dict, overview: dict, *,
             proposals: list[dict] | None = None,
             eval_result: dict | None = None,
             eval_min_recall: float | None = None,
             failed_conversations: int = 0,
             now: datetime | None = None,
             root_debt_threshold: int = 20,
             low_confidence_threshold: int = 50) -> dict:
    """Fonction PURE. Agrège les signaux et retourne le catalogue d'avertissements.

    `discovery` : rapport de `scope_discovery.discover()`.
    `overview`  : rapport de `current_state_overview.analyze()` (réservé : la dérivation
                  primaire se fait via `discovery`, plus riche ; `overview` est accepté
                  pour la robustesse et un usage futur, jamais source de `value`).
    Le tri final est déterministe : (rang de sévérité, code, scope ou "").
    """
    now = _norm_now(now)
    discovery = discovery or {}
    overview = overview or {}  # accepté pour robustesse (non source de contenu sensible)
    props = list(proposals or [])

    scopes = discovery.get("scopes") or []
    root_debt = discovery.get("root_level_debt") or []

    # Index propositions par scope (pour W-STATE-008). None si `proposals` non fourni.
    proposals_by_scope: dict[str, list[dict]] | None
    if proposals is None:
        proposals_by_scope = None
    else:
        proposals_by_scope = {}
        for p in props:
            if isinstance(p, dict):
                proposals_by_scope.setdefault(p.get("scope"), []).append(p)

    warnings: list[dict] = []
    warnings += _rules_from_scopes(
        scopes, proposals_by_scope,
        root_debt=root_debt, root_debt_threshold=root_debt_threshold)
    warnings += _rules_from_proposals(
        props, now=now, low_confidence_threshold=low_confidence_threshold)
    warnings += _rule_failed_conversations(failed_conversations)
    warnings += _rule_eval_regression(eval_result, eval_min_recall)

    # Tri déterministe : critical > warn > info, puis code, puis scope ("" pour global).
    warnings.sort(key=lambda w: (_SEV_RANK.get(w["severity"], 99),
                                 w["code"], w["scope"] or ""))

    by_severity: dict[str, int] = {}
    by_code: dict[str, int] = {}
    for w in warnings:
        by_severity[w["severity"]] = by_severity.get(w["severity"], 0) + 1
        by_code[w["code"]] = by_code.get(w["code"], 0) + 1

    return {
        "report": "anti_drift",
        "engine_version": ENGINE_VERSION,
        "generated_at": now.isoformat(),
        "warnings": warnings,
        "summary": {
            "total": len(warnings),
            "by_severity": dict(sorted(by_severity.items())),
            "by_code": dict(sorted(by_code.items())),
        },
    }


# ----------------------------------------------------------------- rendu
def to_markdown(report: dict) -> str:
    """Rendu Markdown du catalogue (jamais de `value` d'atome)."""
    report = report or {}
    s = report.get("summary", {})
    warnings = report.get("warnings", [])
    L = [
        "# ARAC — Anti-Drift Warning Catalog (read-only)",
        f"_généré : {report.get('generated_at')} · moteur {report.get('engine_version')}_",
        "",
        f"- avertissements : **{s.get('total', 0)}** · "
        f"par sévérité : {s.get('by_severity', {})}",
        f"- par code : {s.get('by_code', {})}",
        "",
    ]
    if not warnings:
        L.append("Aucune dérive détectée.")
        return "\n".join(L)
    cur_sev = None
    for w in warnings:
        if w["severity"] != cur_sev:
            cur_sev = w["severity"]
            L += ["", f"## {cur_sev.upper()}"]
        scope = w["scope"] or "(global)"
        L.append(f"- `{w['code']}` [{w['category']}] `{scope}` : {w['description']}")
        L.append(f"  - action : {w['suggested_action']} "
                 f"(auto_fix={w['auto_fix_available']}, sources={w['sources']})")
    return "\n".join(L)


def _read_json(path: str | None):
    """Lecture seule d'un fichier JSON (None si chemin absent)."""
    if not path:
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Anti-Drift Warning Catalog — read-only, pur (aucune DB/réseau).")
    p.add_argument("--discovery-json", help="Fichier JSON (rapport scope_discovery).")
    p.add_argument("--overview-json", help="Fichier JSON (rapport current_state_overview).")
    p.add_argument("--proposals-json", help="Fichier JSON (liste de propositions).")
    p.add_argument("--eval-json", help="Fichier JSON (résultat d'éval retrieval).")
    p.add_argument("--eval-min-recall", type=float, default=None,
                   help="Plancher de recall ; MÊME ÉCHELLE que le champ recall de l'eval JSON "
                        "(ratio 0-1, pas un pourcentage). Ex : 0.6, pas 60.")
    p.add_argument("--failed-conversations", type=int, default=0)
    p.add_argument("--root-debt-threshold", type=int, default=20)
    p.add_argument("--low-confidence-threshold", type=int, default=50)
    p.add_argument("--now", help="ISO timestamp (déterminisme tests).")
    p.add_argument("--markdown", action="store_true")
    args = p.parse_args(argv)

    now = _parse_dt(args.now) or datetime.now(timezone.utc)
    try:
        discovery = _read_json(args.discovery_json) or {}
        overview = _read_json(args.overview_json) or {}
        proposals = _read_json(args.proposals_json)  # None si absent (W-STATE-008 inactif)
        eval_result = _read_json(args.eval_json)
    except (OSError, json.JSONDecodeError) as e:
        print(f"input error: {type(e).__name__}: {str(e)[:80]}", file=sys.stderr)
        return 3

    report = evaluate(
        discovery, overview, proposals=proposals, eval_result=eval_result,
        eval_min_recall=args.eval_min_recall,
        failed_conversations=args.failed_conversations, now=now,
        root_debt_threshold=args.root_debt_threshold,
        low_confidence_threshold=args.low_confidence_threshold)

    if args.markdown:
        print(to_markdown(report))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    # Code de sortie : 2 si au moins un critical, 1 si au moins un warn, 0 sinon.
    sev = report["summary"]["by_severity"]
    if sev.get(SEV_CRITICAL):
        return 2
    if sev.get(SEV_WARN):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
