"""Gate de promotion curator I9 — fail-closed, shadow-first (Phase E.3).

Complète `agents/curator/policy.py` (anti-bruit + seuils de confidence). Là où
policy.py décide « cet atome est-il du SIGNAL ? », ce gate décide « cet atome
est-il SÛR À PROMOUVOIR en mémoire active ? » — au sens INTÉGRITÉ/PROVENANCE :

  - source / date / confidence / provenance OBLIGATOIRES (sinon BLOCKED) ;
  - source TRONQUÉE -> BLOCKED (on ne promeut pas une vérité sur un extrait) ;
  - LLM (vérificateur) INDISPONIBLE -> PENDING_REVIEW (repris plus tard, pas
    promu à l'aveugle) ;
  - CONTRADICTION détectée -> DISPUTED (visible, jamais promue silencieusement) ;
  - sinon -> PROMOTE.

Garde-fous mission :
  - FAIL-CLOSED : tout doute déclasse (jamais un atome douteux promu en silence).
  - FEATURE FLAG `ARAC_CURATOR_GATE_MODE` : off | shadow | enforce (défaut off).
  - SHADOW : le gate calcule le verdict RÉEL et le journalise, mais NE BLOQUE PAS
    (effective_outcome = promote) — pour mesurer l'impact AVANT activation.
  - AUDIT : chaque décision produit un enregistrement structuré (build_audit_record).
  - REPRISE : PENDING_REVIEW/BLOCKED sont des états repris (pas une perte).

Module PUR (aucune I/O, aucune DB, aucun appel LLM) -> unit-testable. Le wiring
réel (interception des candidats avant create_atom) est OFF par défaut : aucun
changement de comportement tant que l'opérateur n'a pas posé le flag.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

GATE_MODE_ENV = "ARAC_CURATOR_GATE_MODE"


class GateMode(str, Enum):
    OFF = "off"          # gate inerte (défaut) — aucun changement de comportement
    SHADOW = "shadow"    # calcule + journalise, mais ne bloque pas
    ENFORCE = "enforce"  # applique réellement le verdict


class GateOutcome(str, Enum):
    PROMOTE = "promote"                # OK pour mémoire active
    BLOCKED = "blocked"                # intégrité/provenance insuffisante
    PENDING_REVIEW = "pending_review"  # vérif impossible (LLM down) — à reprendre
    DISPUTED = "disputed"              # contradiction — visible, non promue


# Champs tolérés pour chaque obligation (l'atome peut venir de plusieurs chemins).
_SOURCE_KEYS = ("source_ref", "source", "source_path")
_DATE_KEYS = ("observed_at", "source_date", "ingested_at", "received_at", "created_at")
_SOURCE_DATE_SUBKEYS = ("date", "observed_at", "timestamp", "received_at")
_CONF_KEYS = ("confidence_score", "confidence")
_PROVENANCE_KEYS = ("node_id", "provenance", "ingest_node")


def gate_mode(env: Mapping[str, str] = os.environ) -> GateMode:
    """Lit ARAC_CURATOR_GATE_MODE. Valeur inconnue -> OFF (fail-safe : on ne se
    met pas à enforcer par accident sur une faute de frappe)."""
    raw = str(env.get(GATE_MODE_ENV, "off")).strip().lower()
    try:
        return GateMode(raw)
    except ValueError:
        return GateMode.OFF


def _nonempty(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (dict, list, tuple, set)):
        return len(v) > 0
    return True


def has_source(c: Mapping[str, Any]) -> bool:
    for k in _SOURCE_KEYS:
        v = c.get(k)
        if isinstance(v, Mapping):
            # source_ref doit porter un identifiant de source (path/type/uri/id)
            if any(_nonempty(v.get(sk)) for sk in ("source_path", "path", "type", "uri", "id", "ref")):
                return True
        elif _nonempty(v):
            return True
    return False


def has_date(c: Mapping[str, Any]) -> bool:
    for k in _DATE_KEYS:
        if _nonempty(c.get(k)):
            return True
    src = c.get("source_ref")
    if isinstance(src, Mapping):
        for sk in _SOURCE_DATE_SUBKEYS:
            if _nonempty(src.get(sk)):
                return True
    return False


def has_confidence(c: Mapping[str, Any]) -> bool:
    v = c.get("confidence_score")
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    return _nonempty(c.get("confidence"))


def has_provenance(c: Mapping[str, Any]) -> bool:
    for k in _PROVENANCE_KEYS:
        if _nonempty(c.get(k)):
            return True
    return False


def missing_mandatory(c: Mapping[str, Any]) -> list[str]:
    missing = []
    if not has_source(c):
        missing.append("source")
    if not has_date(c):
        missing.append("date")
    if not has_confidence(c):
        missing.append("confidence")
    if not has_provenance(c):
        missing.append("provenance")
    return missing


def evaluate(
    candidate: Mapping[str, Any],
    *,
    llm_available: bool = True,
    contradiction: bool = False,
    source_truncated: bool = False,
) -> tuple[GateOutcome, list[str]]:
    """Verdict RÉEL (indépendant du mode). Priorité fail-closed :
    source tronquée > métadonnées manquantes > LLM down > contradiction > promote.
    """
    reasons: list[str] = []

    if source_truncated:
        reasons.append("source_truncated")
        return GateOutcome.BLOCKED, reasons

    missing = missing_mandatory(candidate)
    if missing:
        reasons.extend(f"missing_{m}" for m in missing)
        return GateOutcome.BLOCKED, reasons

    if not llm_available:
        reasons.append("llm_unavailable")
        return GateOutcome.PENDING_REVIEW, reasons

    if contradiction:
        reasons.append("contradiction_detected")
        return GateOutcome.DISPUTED, reasons

    return GateOutcome.PROMOTE, reasons


@dataclass
class GateResult:
    gate_outcome: GateOutcome        # ce que le gate a décidé (verdict réel)
    effective_outcome: GateOutcome   # ce que le caller DOIT appliquer (selon mode)
    mode: GateMode
    reasons: list[str] = field(default_factory=list)

    @property
    def blocks_promotion(self) -> bool:
        return self.effective_outcome != GateOutcome.PROMOTE


def apply_gate(
    candidate: Mapping[str, Any],
    *,
    llm_available: bool = True,
    contradiction: bool = False,
    source_truncated: bool = False,
    mode: GateMode | None = None,
) -> GateResult:
    """Calcule le verdict et l'applique SELON LE MODE.

    OFF     -> inerte : effective = PROMOTE (aucun changement de comportement).
    SHADOW  -> effective = PROMOTE, mais gate_outcome = verdict réel (journalisé).
    ENFORCE -> effective = gate_outcome.
    """
    if mode is None:
        mode = gate_mode()

    if mode is GateMode.OFF:
        return GateResult(GateOutcome.PROMOTE, GateOutcome.PROMOTE, mode, ["gate_off"])

    outcome, reasons = evaluate(
        candidate, llm_available=llm_available,
        contradiction=contradiction, source_truncated=source_truncated,
    )

    if mode is GateMode.SHADOW:
        # On NE bloque PAS : on mesure. effective reste PROMOTE.
        return GateResult(outcome, GateOutcome.PROMOTE, mode, reasons)

    # ENFORCE
    return GateResult(outcome, outcome, mode, reasons)


def build_audit_record(candidate: Mapping[str, Any], result: GateResult) -> dict[str, Any]:
    """Enregistrement structuré pour le log d'audit (jamais de contenu sensible :
    on ne logge ni la `value` de l'atome, ni la source brute — uniquement des
    métadonnées + le verdict)."""
    kind = candidate.get("kind")
    scope = candidate.get("scope")
    return {
        "event": "curator.i9_gate",
        "kind": str(getattr(kind, "value", kind)),
        "scope": str(getattr(scope, "value", scope)),
        "key": candidate.get("key"),
        "mode": result.mode.value,
        "gate_outcome": result.gate_outcome.value,
        "effective_outcome": result.effective_outcome.value,
        "blocks_promotion": result.blocks_promotion,
        "reasons": result.reasons,
    }
