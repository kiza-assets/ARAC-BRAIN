"""Tests PURS du gate de promotion curator I9 (Phase E.3, fail-closed shadow-first)."""

from __future__ import annotations

from agents.curator import gate as g


def _good_candidate(**over):
    c = {
        "kind": "decision",
        "scope": "outillage",
        "key": "use-postgres-16",
        "value": "On garde PostgreSQL 16 nu + pgvector.",
        "confidence_score": 80,
        "source_ref": {"source_path": "conv/2026-06-21.json", "type": "conversation",
                       "date": "2026-06-21T10:00:00Z"},
        "node_id": "arac-curator",
    }
    c.update(over)
    return c


# --- gate_mode --------------------------------------------------------------
def test_gate_mode_defaults_off():
    assert g.gate_mode({}) is g.GateMode.OFF


def test_gate_mode_parses_known():
    assert g.gate_mode({"ARAC_CURATOR_GATE_MODE": "shadow"}) is g.GateMode.SHADOW
    assert g.gate_mode({"ARAC_CURATOR_GATE_MODE": "ENFORCE"}) is g.GateMode.ENFORCE
    assert g.gate_mode({"ARAC_CURATOR_GATE_MODE": "off"}) is g.GateMode.OFF


def test_gate_mode_unknown_is_off_failsafe():
    assert g.gate_mode({"ARAC_CURATOR_GATE_MODE": "enfroce_typo"}) is g.GateMode.OFF


# --- field detection --------------------------------------------------------
def test_has_source_via_source_ref_and_path():
    assert g.has_source(_good_candidate())
    assert g.has_source({"source_path": "x.json"})
    assert not g.has_source({"source_ref": {}})
    assert not g.has_source({"source_ref": {"unrelated": "x"}})
    assert not g.has_source({})


def test_has_date_via_field_or_source_subkey():
    assert g.has_date({"observed_at": "2026-06-21"})
    assert g.has_date({"source_ref": {"date": "2026-06-21"}})
    assert not g.has_date({"source_ref": {"source_path": "x"}})
    assert not g.has_date({})


def test_has_confidence_int_but_not_bool():
    assert g.has_confidence({"confidence_score": 0})
    assert g.has_confidence({"confidence": "producer"})
    assert not g.has_confidence({"confidence_score": True})  # bool n'est pas une confidence
    assert not g.has_confidence({})


def test_has_provenance():
    assert g.has_provenance({"node_id": "arac-curator"})
    assert not g.has_provenance({"node_id": ""})
    assert not g.has_provenance({})


def test_missing_mandatory_lists_all_gaps():
    assert g.missing_mandatory({}) == ["source", "date", "confidence", "provenance"]
    assert g.missing_mandatory(_good_candidate()) == []


# --- evaluate (verdict réel, priorité) --------------------------------------
def test_promote_when_clean():
    out, reasons = g.evaluate(_good_candidate())
    assert out is g.GateOutcome.PROMOTE
    assert reasons == []


def test_truncated_source_blocks_first():
    # même un candidat complet est BLOCKED si la source est tronquée.
    out, reasons = g.evaluate(_good_candidate(), source_truncated=True)
    assert out is g.GateOutcome.BLOCKED
    assert "source_truncated" in reasons


def test_missing_fields_block():
    out, reasons = g.evaluate({"kind": "decision", "scope": "outillage", "key": "x"})
    assert out is g.GateOutcome.BLOCKED
    assert "missing_source" in reasons and "missing_provenance" in reasons


def test_llm_unavailable_pending_review():
    out, reasons = g.evaluate(_good_candidate(), llm_available=False)
    assert out is g.GateOutcome.PENDING_REVIEW
    assert "llm_unavailable" in reasons


def test_contradiction_disputed():
    out, reasons = g.evaluate(_good_candidate(), contradiction=True)
    assert out is g.GateOutcome.DISPUTED
    assert "contradiction_detected" in reasons


def test_missing_outranks_llm_and_contradiction():
    # champs manquants = BLOCKED, même si LLM down + contradiction.
    out, _ = g.evaluate({"key": "x"}, llm_available=False, contradiction=True)
    assert out is g.GateOutcome.BLOCKED


def test_truncation_outranks_missing_fields():
    out, reasons = g.evaluate({"key": "x"}, source_truncated=True)
    assert out is g.GateOutcome.BLOCKED
    assert reasons == ["source_truncated"]


# --- apply_gate (modes) -----------------------------------------------------
def test_off_mode_is_inert():
    r = g.apply_gate(_good_candidate(source_truncated=False), source_truncated=True,
                     mode=g.GateMode.OFF)
    assert r.effective_outcome is g.GateOutcome.PROMOTE
    assert r.gate_outcome is g.GateOutcome.PROMOTE
    assert r.blocks_promotion is False


def test_shadow_mode_computes_but_does_not_block():
    r = g.apply_gate(_good_candidate(), source_truncated=True, mode=g.GateMode.SHADOW)
    assert r.gate_outcome is g.GateOutcome.BLOCKED        # verdict réel mesuré
    assert r.effective_outcome is g.GateOutcome.PROMOTE   # mais ne bloque PAS
    assert r.blocks_promotion is False
    assert "source_truncated" in r.reasons


def test_enforce_mode_blocks():
    r = g.apply_gate(_good_candidate(), source_truncated=True, mode=g.GateMode.ENFORCE)
    assert r.gate_outcome is g.GateOutcome.BLOCKED
    assert r.effective_outcome is g.GateOutcome.BLOCKED
    assert r.blocks_promotion is True


def test_enforce_clean_promotes():
    r = g.apply_gate(_good_candidate(), mode=g.GateMode.ENFORCE)
    assert r.effective_outcome is g.GateOutcome.PROMOTE
    assert r.blocks_promotion is False


# --- audit record -----------------------------------------------------------
def test_audit_record_has_verdict_and_no_value_leak():
    r = g.apply_gate(_good_candidate(), contradiction=True, mode=g.GateMode.ENFORCE)
    rec = g.build_audit_record(_good_candidate(), r)
    assert rec["event"] == "curator.i9_gate"
    assert rec["gate_outcome"] == "disputed"
    assert rec["effective_outcome"] == "disputed"
    assert rec["blocks_promotion"] is True
    # JAMAIS la value de l'atome ni la source brute dans l'audit.
    blob = str(rec)
    assert "PostgreSQL 16" not in blob
    assert "conv/2026-06-21.json" not in blob
