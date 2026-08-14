"""Sensibilité d'un scope : ce que le cerveau a le droit de proposer tout seul.

CE QUE CE MODULE DÉCIDE
-----------------------
Rien n'est jamais appliqué automatiquement. L'invariant tient en une ligne, et
il n'a aucune exception :

    auto_apply_allowed est TOUJOURS False, pour tout scope, pour tout risque.

Ce module classe donc uniquement le niveau de RELECTURE humaine exigé avant
qu'une proposition ne devienne un souvenir :

    LOW     proposition automatique permise, relecture optionnelle ;
    MEDIUM  proposition permise, relecture humaine RECOMMANDÉE ;
    HIGH    proposition permise, relecture humaine TOUJOURS obligatoire,
            et contenu rédacté — il ne sort jamais en clair.

TOUT EST « HIGH » TANT QUE VOUS N'AVEZ RIEN DIT
-----------------------------------------------
Le dépôt ne contient AUCUNE table de risque : il ne connaît pas votre vie. Un
scope non classé est donc HIGH — le plus conservateur. Conséquence concrète :
sans configuration, chaque proposition demande votre relecture. C'est
volontairement inconfortable, et c'est le bon défaut. L'inverse — supposer
qu'un scope inconnu est anodin — se paie une seule fois, et cher.

Pour desserrer, écrivez ``config/sensitivity.toml`` :

    [scopes]
    "travail/finance"   = "medium"
    "outillage"         = "low"      # la racine : toutes ses feuilles héritent
    "perso"             = "high"

L'héritage se fait par racine : une feuille non citée prend le risque de sa
racine, et à défaut HIGH. Vous n'avez donc à déclarer que ce qui s'écarte du
défaut.

CONSEIL DE CLASSEMENT
---------------------
HIGH pour tout ce qui touche à la santé, à la famille, au juridique, au fiscal
et à l'argent. MEDIUM pour la stratégie et les décisions qui engagent. LOW pour
la technique et l'opérationnel courant.

Le doute se tranche vers le haut : une relecture de trop coûte trente secondes,
un souvenir sensible posé sans relecture coûte beaucoup plus longtemps.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

import arac_runtime


POLICY_VERSION = "sensitivity_policy@v1"

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"
VALID_RISKS = (RISK_LOW, RISK_MEDIUM, RISK_HIGH)

# Niveaux de revue dérivés du risque (mission §1.2).
REVIEW_NONE = "none"               # LOW : revue optionnelle
REVIEW_RECOMMENDED = "recommended"  # MEDIUM : revue recommandée avant apply
REVIEW_MANDATORY = "mandatory"      # HIGH : revue TOUJOURS obligatoire

# ---------------------------------------------------------------------------
# La table de risque : la vôtre, ou rien.
# ---------------------------------------------------------------------------


def _load_scope_risk() -> dict[str, str]:
    """Lit ``config/sensitivity.toml``. Absent ou illisible → table vide.

    Une table vide n'est pas une panne : elle signifie « tout est sensible »,
    ce qui est le comportement sûr. On ne lève donc pas — on se tait et on
    protège.
    """
    path = Path(
        os.environ.get("ARAC_SENSITIVITY_CONFIG")
        or arac_runtime.config_dir() / "sensitivity.toml"
    )
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    out: dict[str, str] = {}
    for scope, risk in (raw.get("scopes") or {}).items():
        risk = str(risk).strip().lower()
        if risk in VALID_RISKS:
            out[str(scope).strip().lower()] = risk
    return out


_SCOPE_RISK: dict[str, str] = _load_scope_risk()

# Rationale par défaut par risque (lisible API/cockpit).
_RISK_REASON: dict[str, str] = {
    RISK_LOW: "scope opérationnel/technique non sensible — proposition auto permise, "
              "apply jamais auto (revue optionnelle)",
    RISK_MEDIUM: "scope business/stratégie/projet — proposition permise, revue humaine "
                 "recommandée avant toute application",
    RISK_HIGH: "scope sensible, ou non classé (le défaut est le plus prudent) — "
               "contenu rédacté, relecture humaine TOUJOURS obligatoire, aucune "
               "application automatique. Pour desserrer : config/sensitivity.toml",
}

_DEFAULT_RISK = RISK_HIGH  # fail-safe : scope inconnu/non mappé → le plus conservateur

def _normalize(scope: str | None) -> str:
    """Lower + strip (fail-closed sur casse/espaces, comme is_sensitive_scope)."""
    return (scope or "").strip().lower()


def risk_of(scope: str | None) -> str:
    """Risque (low/medium/high) d'un scope. Inconnu → HIGH (fail-safe)."""
    s = _normalize(scope)
    if not s:
        return _DEFAULT_RISK
    if s in _SCOPE_RISK:
        return _SCOPE_RISK[s]
    # Fallback par racine (un sous-scope futur hérite du risque de sa racine si la
    # racine est connue ; sinon HIGH). Évite un trou si une feuille apparaît en DB
    # avant d'être ajoutée à la table (la DB peut contenir des scopes legacy).
    root = s.split("/")[0]
    return _SCOPE_RISK.get(root, _DEFAULT_RISK)


def review_level_of(risk: str) -> str:
    if risk == RISK_LOW:
        return REVIEW_NONE
    if risk == RISK_MEDIUM:
        return REVIEW_RECOMMENDED
    return REVIEW_MANDATORY


def classify_scope(scope: str | None) -> dict:
    """Politique de sensibilité d'un scope (PUR, aucune écriture).

    Retourne un dict stable, retournable par l'API et affichable dans le cockpit :
      - risk                 : low | medium | high
      - review_level         : none | recommended | mandatory
      - human_review_required: True dès medium (False uniquement en low)
      - auto_propose_allowed : True (proposer = lecture seule, toujours permis)
      - auto_apply_allowed   : **toujours False** (INVARIANT — jamais d'apply auto)
      - redact_content       : True en high (contenu non exposé en clair)
      - reason               : justification lisible
      - policy_version       : version de la politique
    """
    risk = risk_of(scope)
    level = review_level_of(risk)
    return {
        "scope": _normalize(scope) or None,
        "risk": risk,
        "review_level": level,
        # medium ET high exigent une revue avant apply ; seul low ne l'exige pas.
        "human_review_required": risk != RISK_LOW,
        # proposer est toujours une lecture seule → permis ; ce n'est PAS un apply.
        "auto_propose_allowed": True,
        # INVARIANT DUR mission §10 : aucune application automatique, jamais.
        "auto_apply_allowed": False,
        # le contenu sensible n'est jamais exposé en clair (rédaction).
        "redact_content": risk == RISK_HIGH,
        "reason": _RISK_REASON[risk],
        "policy_version": POLICY_VERSION,
    }


def all_scopes_policy() -> list[dict]:
    """Politique de TOUS les scopes mappés (tri stable). Pour API/cockpit/tests."""
    return [classify_scope(s) for s in sorted(_SCOPE_RISK)]


def scopes_at_risk(risk: str) -> list[str]:
    """Liste triée des scopes d'un niveau de risque donné."""
    if risk not in VALID_RISKS:
        raise ValueError(f"risque inconnu : {risk!r} (attendus {VALID_RISKS})")
    return sorted(s for s, r in _SCOPE_RISK.items() if r == risk)


def summary() -> dict:
    """Compteurs par niveau de risque (vue cockpit/brain-health)."""
    counts = {r: 0 for r in VALID_RISKS}
    for r in _SCOPE_RISK.values():
        counts[r] += 1
    return {
        "policy_version": POLICY_VERSION,
        "total_scopes": len(_SCOPE_RISK),
        "by_risk": counts,
        "high_risk_scopes": scopes_at_risk(RISK_HIGH),
        "medium_risk_scopes": scopes_at_risk(RISK_MEDIUM),
        "low_risk_scopes": scopes_at_risk(RISK_LOW),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(summary(), ensure_ascii=False, indent=2))
