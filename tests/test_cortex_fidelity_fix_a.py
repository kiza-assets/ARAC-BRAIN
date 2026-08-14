"""FIX A (chantier fidélité V5) — `ARAC_CORTEX_RUNREF_LENIENT`.

Le `run_ref` échoé par le LLM dans son document n'a AUCUN consommateur aval :
le `run_ref` gravé dans `source_ref` des atomes (`agents/cortex/policy.py:116`),
celui de la `digestion_review_queue` (`agents/cortex/review_queue.py:139`) et
celui des reçus viennent TOUS du `slot_key` SERVEUR passé par
`agents/cortex/cycle.py:505`. Ce n'est donc pas un garde de sécurité mais un
champ de cohérence : sous flag, son mismatch devient non-fatal.

Propriétés testées :
  - flag ABSENT / OFF  -> comportement bit-identique (mismatch FATAL) ;
  - flag ON            -> document accepté, log émis, compteur exposé,
                          `run_ref` du document nettoyé FORCÉ au slot serveur ;
  - flag ON            -> aucune autre violation n'est amnistiée.
"""

import copy
import json

import pytest

from agents.cortex.contract import ContractError, _sha8, validate_document

from tests.test_cortex_contract import RUN_REF, _atom, _doc, _presented

FLAG = "ARAC_CORTEX_RUNREF_LENIENT"
_PRESENTED = {"conv-1": [1, 2, 3]}
BAD_REF = "manual@2026-07-03T00:00:00"


def _validate(doc):
    return validate_document(doc, expected_run_ref=RUN_REF,
                             presented=_presented(**_PRESENTED))


# ---------------------------------------------------------------- OFF (défaut)


@pytest.mark.parametrize("value", [None, "", "0", "false", "off", "no", "nope"])
def test_off_run_ref_mismatch_reste_fatal(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(FLAG, raising=False)
    else:
        monkeypatch.setenv(FLAG, value)
    with pytest.raises(ContractError) as exc:
        _validate(_doc(run_ref=BAD_REF))
    assert f"run_ref_mismatch:{BAD_REF!r}" in exc.value.errors


def test_off_document_sain_bit_identique(monkeypatch):
    """Flag OFF : sortie strictement identique à la référence (aucun champ ajouté)."""
    monkeypatch.delenv(FLAG, raising=False)
    doc = _doc()
    reference = copy.deepcopy(_validate(doc))
    monkeypatch.setenv(FLAG, "0")
    assert _validate(_doc()) == reference
    assert "_runref_lenient_count" not in reference
    assert "_runref_declared_sha8" not in reference
    assert "_runref_declared" not in reference  # R4 : la valeur BRUTE a disparu


def test_on_document_sain_bit_identique_a_off(monkeypatch):
    """Flag ON mais run_ref CORRECT : sortie inchangée (le fix ne touche rien)."""
    monkeypatch.delenv(FLAG, raising=False)
    reference = copy.deepcopy(_validate(_doc()))
    monkeypatch.setenv(FLAG, "1")
    assert _validate(_doc()) == reference


# ------------------------------------------------------------------------ ON


def test_on_mismatch_accepte_et_slot_serveur_fait_foi(monkeypatch):
    monkeypatch.setenv(FLAG, "1")
    cleaned = _validate(_doc(run_ref=BAD_REF))
    # le slot_key SERVEUR reste la source de vérité, jamais les dires du LLM
    assert cleaned["run_ref"] == RUN_REF
    # R4 (fix round-1) : empreinte SEULEMENT, jamais la valeur brute du LLM
    assert cleaned["_runref_declared_sha8"] == _sha8(BAD_REF)
    assert "_runref_declared" not in cleaned
    assert cleaned["_runref_lenient_count"] == 1
    # l'atome passe intact
    assert cleaned["conversations"][0]["atoms"] == [_atom()]


def test_on_run_ref_absent_ou_non_string_tolere_et_compte(monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    doc = _doc()
    doc.pop("run_ref")
    cleaned = _validate(doc)
    assert cleaned["run_ref"] == RUN_REF
    assert cleaned["_runref_lenient_count"] == 1
    assert cleaned["_runref_declared_sha8"] == _sha8(None)

    cleaned = _validate(_doc(run_ref=42))
    assert cleaned["run_ref"] == RUN_REF
    assert cleaned["_runref_declared_sha8"] == _sha8(42)


def test_on_emet_un_log_json(monkeypatch, caplog):
    monkeypatch.setenv(FLAG, "on")
    with caplog.at_level("INFO", logger="arac.cortex.contract"):
        _validate(_doc(run_ref=BAD_REF))
    events = [json.loads(r.message) for r in caplog.records]
    matching = [e for e in events if e.get("event") == "cortex.contract.runref_lenient"]
    assert matching == [{"event": "cortex.contract.runref_lenient",
                         "run_ref": RUN_REF,
                         "declared_sha8": _sha8(BAD_REF),
                         "declared_len": len(BAD_REF),
                         "declared_type": "str"}]


def test_on_namnistie_aucune_autre_violation(monkeypatch):
    """Le flag ne relâche QUE run_ref : version, complete, uid inconnu,
    message_ids étrangers restent FATALS."""
    monkeypatch.setenv(FLAG, "1")

    with pytest.raises(ContractError) as exc:
        _validate(_doc(run_ref=BAD_REF, contract_version="cortex-dispose/0",
                       complete=False))
    joined = " ".join(exc.value.errors)
    assert "contract_version" in joined and "complete" in joined
    assert "run_ref_mismatch" not in joined

    with pytest.raises(ContractError) as exc:
        _validate(_doc(run_ref=BAD_REF, conversations=[
            {"conversation_uid": "conv-hallucinee", "atoms": [_atom()], "skips": []}]))
    assert any(e.startswith("unknown_conversation:") for e in exc.value.errors)

    with pytest.raises(ContractError) as exc:
        _validate(_doc(run_ref=BAD_REF, conversations=[
            {"conversation_uid": "conv-1",
             "atoms": [_atom(message_ids=[1, 999])], "skips": []}]))
    assert "foreign_message_ids:conv-1" in exc.value.errors
