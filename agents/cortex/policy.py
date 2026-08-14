"""Politique de seuils du disposant `cortex-dispose/1`.

Source de vérité ENFORCÉE côté code (pas le prompt) : le LLM PROPOSE un
atome déjà nettoyé par `agents/cortex/contract.py`, ce module DISPOSE —
seuils de confiance par kind, scope valide, rationale obligatoire pour
`decision`, puis construction du payload POST /v1/atoms où les champs
sensibles (`node_id`, `source_ref`, `audit_source`) ne sont JAMAIS repris du
LLM. Module pur, hermétique (aucun accès réseau/DB).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from agents.cortex.contract import ALLOWED_KINDS

# Seuils de confiance ENFORCÉS par kind (DESIGN §3 : "les seuils du prompt
# actuel, désormais ENFORCED"). Un atome sous son seuil est un policy_skip
# compté, jamais un 422/atome perdu.
THRESHOLDS: dict[str, int] = {
    "decision": 85,
    "gotcha": 85,
    "killed": 85,
    "alert": 80,
    "pattern": 75,
    "state": 75,
    "todo": 75,
    "note": 50,
    "idea": 50,
    "insight": 50,
    "question": 50,
    "reference": 50,
}

assert frozenset(THRESHOLDS) == ALLOWED_KINDS, (
    "THRESHOLDS doit couvrir EXACTEMENT les 12 kinds producteurs de "
    "contract.ALLOWED_KINDS — un kind ajouté/retiré d'un côté sans l'autre "
    "est une dérive de contrat silencieuse."
)

_MAX_TAGS = 8
_CURATOR_TAG = "curator"
_ALERT_KIND = "alert"
_DECISION_KIND = "decision"


@dataclass
class PolicyVerdict:
    """Verdict de `check_atom` — le premier échec rencontré fait foi (fail-fast)."""

    ok: bool
    reason: str | None = None


def check_atom(atom: dict, *, valid_scopes: frozenset[str]) -> PolicyVerdict:
    """Applique la politique HYBRID à un atome déjà validé par contract.py.

    Ordre des vérifications = ordre du premier échec retourné (DESIGN §3) :
    kind connu -> scope valide -> seuil de confiance -> rationale
    (obligatoire pour `decision`) -> value non vide après strip.
    """
    kind = atom.get("kind")
    if kind not in THRESHOLDS:
        return PolicyVerdict(ok=False, reason="kind_forbidden")

    if atom.get("scope") not in valid_scopes:
        return PolicyVerdict(ok=False, reason="scope_invalid")

    if atom.get("confidence_score", -1) < THRESHOLDS[kind]:
        return PolicyVerdict(ok=False, reason="below_threshold")

    if kind == _DECISION_KIND and not (atom.get("rationale") or "").strip():
        return PolicyVerdict(ok=False, reason="rationale_required")

    if not (atom.get("value") or "").strip():
        return PolicyVerdict(ok=False, reason="empty_value")

    return PolicyVerdict(ok=True)


def finalize_atom(
    atom: dict,
    *,
    node_id: str,
    run_ref: str,
    conversation_uid: str,
    source_type: str,
) -> dict:
    """Construit le payload POST /v1/atoms — champs sensibles CONTRÔLÉS PAR
    LE CODE, jamais repris du LLM (`node_id`, `confidence`, `audit_source`,
    `source_ref` : cette fonction ne les LIT jamais dans `atom`, elle les
    construit à neuf ci-dessous, même si un LLM malicieux les y avait remis).

    `tags` = union(tags fournis, {"curator"}) plafonnée à 8, "curator"
    TOUJOURS présent (réservé une place plutôt qu'ajouté-puis-tronqué, pour
    ne jamais le perdre par troncature).
    """
    llm_tags = [t for t in (atom.get("tags") or []) if t != _CURATOR_TAG]
    deduped_llm_tags = list(dict.fromkeys(llm_tags))
    tags = deduped_llm_tags[: _MAX_TAGS - 1] + [_CURATOR_TAG]

    payload: dict[str, Any] = {
        "scope": atom["scope"],
        "kind": atom["kind"],
        "key": atom["key"],
        "value": atom["value"],
        "rationale": atom.get("rationale"),
        "confidence_score": atom["confidence_score"],
        "tags": tags,
        "node_id": node_id,
        "source_ref": {
            "contract": "cortex-dispose/1",
            "run_ref": run_ref,
            "conversation_uid": conversation_uid,
            "source_type": source_type,
            "message_ids": atom["message_ids"],
        },
    }
    if atom["kind"] == _ALERT_KIND:
        payload["audit_source"] = "autonomous_agent_suggest"
        # L'API impose la cohérence tier/audit_source (validator
        # _confidence_consistency d'AtomCreate) : alert => agent_suggest.
        # Sans ce tier, POST -> 422 (mesuré au premier run réel, receipt #4).
        payload["confidence"] = "agent_suggest"
    return payload


_WHITESPACE_RE = re.compile(r"\s+")


def normalize_value(v: str) -> str:
    """Normalise une valeur pour la comparaison 409 (DESIGN §4 étape 3) :
    NFC unicode -> casefold -> espaces (espaces/tabs/retours multiples)
    collapsés à un seul espace, bords trimés."""
    nfc = unicodedata.normalize("NFC", v)
    folded = nfc.casefold()
    return _WHITESPACE_RE.sub(" ", folded).strip()
