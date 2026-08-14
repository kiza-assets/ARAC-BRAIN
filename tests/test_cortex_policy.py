"""Tests de la politique de seuils `agents/cortex/policy.py`.

HERMÉTIQUES : aucune DB, aucun réseau. Couvre `check_atom` (seuils exacts
par kind, kind banni, scope inventé, rationale obligatoire pour decision,
value vide), `finalize_atom` (tags union+curator+cap 8, audit_source forcé
pour alert, source_ref construit par le code même si le LLM en fournissait
un, node_id imposé) et `normalize_value` (NFC, casefold, espaces multiples).
"""

from __future__ import annotations

import unicodedata

import pytest

from agents.cortex.policy import (
    THRESHOLDS,
    PolicyVerdict,
    check_atom,
    finalize_atom,
    normalize_value,
)


VALID_SCOPES = frozenset({"travail/strategie", "travail/finance"})


def _atom(**overrides) -> dict:
    atom = {
        "kind": "decision",
        "scope": "travail/strategie",
        "key": "cortex-dispose-v1",
        "value": "Le disposant remplace le curateur MCP outillé.",
        "rationale": "Le LLM sans outil ne peut plus corrompre la BDD.",
        "confidence_score": 90,
        "tags": ["curator"],
        "supersede_key_hint": None,
        "message_ids": [918001, 918050],
    }
    atom.update(overrides)
    return atom


# ============================================================================
# check_atom — seuils exacts par kind
# ============================================================================


@pytest.mark.parametrize("kind,threshold", sorted(THRESHOLDS.items()))
def test_seuil_exact_passe(kind, threshold):
    rationale = "justification" if kind == "decision" else None
    atom = _atom(kind=kind, confidence_score=threshold, rationale=rationale)
    verdict = check_atom(atom, valid_scopes=VALID_SCOPES)
    assert verdict == PolicyVerdict(ok=True, reason=None)


@pytest.mark.parametrize("kind,threshold", sorted(THRESHOLDS.items()))
def test_seuil_moins_un_echoue(kind, threshold):
    rationale = "justification" if kind == "decision" else None
    atom = _atom(kind=kind, confidence_score=threshold - 1, rationale=rationale)
    verdict = check_atom(atom, valid_scopes=VALID_SCOPES)
    assert verdict.ok is False
    assert verdict.reason == "below_threshold"


# ============================================================================
# check_atom — autres règles
# ============================================================================


def test_kind_banni():
    atom = _atom(kind="agent_message", confidence_score=99)
    verdict = check_atom(atom, valid_scopes=VALID_SCOPES)
    assert verdict == PolicyVerdict(ok=False, reason="kind_forbidden")


def test_scope_invente():
    atom = _atom(scope="scope-qui-n-existe-pas")
    verdict = check_atom(atom, valid_scopes=VALID_SCOPES)
    assert verdict == PolicyVerdict(ok=False, reason="scope_invalid")


def test_decision_sans_rationale():
    atom = _atom(kind="decision", confidence_score=90, rationale=None)
    verdict = check_atom(atom, valid_scopes=VALID_SCOPES)
    assert verdict == PolicyVerdict(ok=False, reason="rationale_required")


def test_decision_rationale_blanc_echoue_aussi():
    atom = _atom(kind="decision", confidence_score=90, rationale="   ")
    verdict = check_atom(atom, valid_scopes=VALID_SCOPES)
    assert verdict == PolicyVerdict(ok=False, reason="rationale_required")


def test_value_vide():
    atom = _atom(kind="note", confidence_score=90, value="   ")
    verdict = check_atom(atom, valid_scopes=VALID_SCOPES)
    assert verdict == PolicyVerdict(ok=False, reason="empty_value")


def test_premier_echec_fait_foi_kind_avant_scope():
    # kind banni ET scope invalide simultanément -> kind_forbidden gagne (ordre DESIGN §3)
    atom = _atom(kind="agent_message", scope="scope-invente")
    verdict = check_atom(atom, valid_scopes=VALID_SCOPES)
    assert verdict.reason == "kind_forbidden"


def test_atome_valide_note_seuil_50():
    atom = _atom(kind="note", confidence_score=50, rationale=None)
    assert check_atom(atom, valid_scopes=VALID_SCOPES).ok is True


# ============================================================================
# finalize_atom
# ============================================================================


def test_finalize_tags_union_curator_et_cap_8():
    atom = _atom(tags=["a", "b", "c", "d", "e", "f", "g", "h"])  # 8 tags LLM, sans curator
    payload = finalize_atom(
        atom, node_id="cortex-disposant", run_ref="circadian_2100@2026-07-03",
        conversation_uid="conv-1", source_type="claude_code",
    )
    assert len(payload["tags"]) == 8
    assert "curator" in payload["tags"]
    assert payload["tags"] == ["a", "b", "c", "d", "e", "f", "g", "curator"]


def test_finalize_tags_curator_deja_present_pas_de_doublon():
    atom = _atom(tags=["curator", "important"])
    payload = finalize_atom(
        atom, node_id="cortex-disposant", run_ref="circadian_2100@2026-07-03",
        conversation_uid="conv-1", source_type="claude_code",
    )
    assert payload["tags"].count("curator") == 1
    assert payload["tags"] == ["important", "curator"]


def test_finalize_alert_force_audit_source():
    atom = _atom(kind="alert", confidence_score=85, rationale=None)
    payload = finalize_atom(
        atom, node_id="cortex-disposant", run_ref="circadian_2100@2026-07-03",
        conversation_uid="conv-1", source_type="claude_code",
    )
    assert payload["audit_source"] == "autonomous_agent_suggest"


def test_finalize_non_alert_sans_audit_source():
    atom = _atom(kind="decision")
    payload = finalize_atom(
        atom, node_id="cortex-disposant", run_ref="circadian_2100@2026-07-03",
        conversation_uid="conv-1", source_type="claude_code",
    )
    assert "audit_source" not in payload


def test_finalize_source_ref_construit_par_le_code_meme_si_llm_en_fournissait_un():
    # Un atome (hypothétiquement pas encore nettoyé par contract.py) qui
    # porterait un source_ref/node_id/confidence du LLM ne doit JAMAIS
    # influencer le payload — finalize_atom ne les lit jamais.
    atom = _atom(
        node_id="llm-invente-un-faux-node",
        source_ref={"contract": "falsifie"},
        confidence="producer",
    )
    payload = finalize_atom(
        atom, node_id="cortex-disposant", run_ref="circadian_2100@2026-07-03",
        conversation_uid="conv-42", source_type="claude_code",
    )
    assert payload["node_id"] == "cortex-disposant"
    assert payload["source_ref"] == {
        "contract": "cortex-dispose/1",
        "run_ref": "circadian_2100@2026-07-03",
        "conversation_uid": "conv-42",
        "source_type": "claude_code",
        "message_ids": atom["message_ids"],
    }
    assert "confidence" not in payload


def test_finalize_node_id_impose():
    atom = _atom()
    payload = finalize_atom(
        atom, node_id="cortex-disposant", run_ref="circadian_2100@2026-07-03",
        conversation_uid="conv-1", source_type="claude_code",
    )
    assert payload["node_id"] == "cortex-disposant"


# ============================================================================
# normalize_value
# ============================================================================


def test_normalize_nfc_compose_vs_decompose():
    composed = "café"  # é = U+00E9 (précomposé)
    decomposed = "café"  # e + combining acute accent (décomposé)
    assert composed != decomposed  # bytes différents avant normalisation
    assert normalize_value(composed) == normalize_value(decomposed)


def test_normalize_casefold():
    assert normalize_value("DÉCISION Importante") == normalize_value("décision importante")


def test_normalize_espaces_multiples_et_tabs():
    assert normalize_value("un   texte\t\tavec des   espaces\n\nmultiples") == (
        "un texte avec des espaces multiples"
    )


def test_normalize_trim_bords():
    assert normalize_value("   entouré d'espaces   ") == "entouré d'espaces"


def test_finalize_alert_sets_consistent_confidence_tier():
    """422 mesuré au premier run réel (receipt #4) : l'API exige
    confidence=agent_suggest quand audit_source=autonomous_agent_suggest."""
    from agents.cortex.policy import finalize_atom

    atom = {"kind": "alert", "scope": "outillage", "key": "test-alerte",
            "value": "Un risque décrit sans le secret.", "rationale": None,
            "confidence_score": 85, "tags": [], "supersede_key_hint": None,
            "message_ids": [1]}
    payload = finalize_atom(atom, node_id="arac-curator", run_ref="slot",
                            conversation_uid="u", source_type="claude_code")
    assert payload["audit_source"] == "autonomous_agent_suggest"
    assert payload["confidence"] == "agent_suggest"
