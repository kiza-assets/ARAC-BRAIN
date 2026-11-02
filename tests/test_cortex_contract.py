"""Tests contrat `cortex-dispose/1`.

HERMÉTIQUES : aucune DB, aucun réseau, aucun subprocess — `agents/cortex/contract.py`
est un module pur. Couvre l'extraction JSON (fenced/nu/tronqué/ambiguïté/clés
dupliquées/taille) et la validation de forme du document (version, run_ref,
complete, conversation_uid hallucinée, message_ids hors tranche, kind banni,
key/value/confidence hors bornes, cap d'atomes, champs contrôlés par le code
retirés, champ inconnu rejeté, document sain retourné nettoyé).
"""

from __future__ import annotations

import json

import pytest

from agents.cortex.contract import (
    CONTRACT_VERSION,
    MAX_ATOMS_PER_RUN,
    MAX_STDOUT_BYTES,
    ContractError,
    extract_json_object,
    normalize_atom_key,
    validate_document,
)


# ============================================================================
# Helpers
# ============================================================================


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
        "message_ids": [1, 2, 3],
    }
    atom.update(overrides)
    return atom


def _presented(**uids) -> dict[str, dict]:
    """`uids` : conversation_uid -> set d'ids de messages présentés."""
    return {
        uid: {"max_id": max(ids) if ids else 0, "message_ids": set(ids)}
        for uid, ids in uids.items()
    }


def _doc(**overrides) -> dict:
    doc = {
        "contract_version": CONTRACT_VERSION,
        "run_ref": "circadian_2100@2026-07-03",
        "complete": True,
        "conversations": [
            {
                "conversation_uid": "conv-1",
                "atoms": [_atom()],
                "skips": [],
            }
        ],
        "audit_summary": "1 décision extraite.",
    }
    doc.update(overrides)
    return doc


RUN_REF = "circadian_2100@2026-07-03"


# ============================================================================
# extract_json_object
# ============================================================================


def test_extract_json_nu_valide():
    stdout = json.dumps({"a": 1, "b": [1, 2, 3]})
    assert extract_json_object(stdout) == {"a": 1, "b": [1, 2, 3]}


def test_extract_json_fence_avec_prose_autour():
    stdout = (
        "Voici mon analyse.\n\n```json\n"
        + json.dumps({"a": 1})
        + "\n```\n\nFin de la réponse."
    )
    assert extract_json_object(stdout) == {"a": 1}


def test_extract_objet_equilibre_dans_du_texte():
    stdout = "Prose avant " + json.dumps({"a": {"b": 1}}) + " prose après."
    assert extract_json_object(stdout) == {"a": {"b": 1}}


def test_extract_accolades_dans_des_strings():
    payload = {"value": "un texte { avec } des accolades \"internes\" et \\{ échappées"}
    stdout = "avant " + json.dumps(payload) + " après"
    assert extract_json_object(stdout) == payload


def test_extract_stdout_vide():
    with pytest.raises(ContractError):
        extract_json_object("")


def test_extract_tronque_accolade_non_fermee():
    stdout = '{"a": 1, "b": {"c": 2'
    with pytest.raises(ContractError):
        extract_json_object(stdout)


def test_extract_deux_objets_top_level_nus():
    stdout = json.dumps({"a": 1}) + " " + json.dumps({"b": 2})
    with pytest.raises(ContractError):
        extract_json_object(stdout)


def test_extract_cles_dupliquees_top_level():
    stdout = '{"a": 1, "a": 2}'
    with pytest.raises(ContractError):
        extract_json_object(stdout)


def test_extract_cles_dupliquees_imbriquees():
    stdout = '{"a": {"b": 1, "b": 2}}'
    with pytest.raises(ContractError):
        extract_json_object(stdout)


def test_extract_plus_1_mib():
    stdout = json.dumps({"a": "x" * (MAX_STDOUT_BYTES + 10)})
    with pytest.raises(ContractError):
        extract_json_object(stdout)


def test_extract_json_invalide():
    with pytest.raises(ContractError):
        extract_json_object("{not valid json")


# ============================================================================
# validate_document — versions / run_ref / complete / structure
# ============================================================================


def test_validate_version_inconnue():
    doc = _doc(contract_version="cortex-dispose/0")
    with pytest.raises(ContractError) as exc:
        validate_document(doc, expected_run_ref=RUN_REF, presented=_presented(**{"conv-1": [1, 2, 3]}))
    assert any("contract_version" in e for e in exc.value.errors)


def test_validate_run_ref_falsifie():
    doc = _doc(run_ref="manual@2026-07-03T00:00:00")
    with pytest.raises(ContractError) as exc:
        validate_document(doc, expected_run_ref=RUN_REF, presented=_presented(**{"conv-1": [1, 2, 3]}))
    assert any("run_ref" in e for e in exc.value.errors)


def test_validate_complete_false():
    doc = _doc(complete=False)
    with pytest.raises(ContractError) as exc:
        validate_document(doc, expected_run_ref=RUN_REF, presented=_presented(**{"conv-1": [1, 2, 3]}))
    assert any("complete" in e for e in exc.value.errors)


def test_validate_conversation_uid_hors_pack():
    doc = _doc()
    with pytest.raises(ContractError) as exc:
        validate_document(doc, expected_run_ref=RUN_REF, presented=_presented(**{"autre-conv": [1, 2, 3]}))
    assert any("unknown_conversation:conv-1" in e for e in exc.value.errors)


def test_validate_message_ids_etrangers():
    doc = _doc(conversations=[
        {"conversation_uid": "conv-1", "atoms": [_atom(message_ids=[999])], "skips": []}
    ])
    with pytest.raises(ContractError) as exc:
        validate_document(doc, expected_run_ref=RUN_REF, presented=_presented(**{"conv-1": [1, 2, 3]}))
    assert any("foreign_message_ids:conv-1" in e for e in exc.value.errors)


# ============================================================================
# validate_document — atomes individuels
# ============================================================================


def test_validate_kind_banni_agent_message():
    doc = _doc(conversations=[
        {"conversation_uid": "conv-1", "atoms": [_atom(kind="agent_message")], "skips": []}
    ])
    with pytest.raises(ContractError) as exc:
        validate_document(doc, expected_run_ref=RUN_REF, presented=_presented(**{"conv-1": [1, 2, 3]}))
    assert any("kind_forbidden" in e for e in exc.value.errors)


@pytest.mark.parametrize("bad_key", ["a", "!!!", ""])
def test_validate_key_invalide(bad_key):
    doc = _doc(conversations=[
        {"conversation_uid": "conv-1", "atoms": [_atom(key=bad_key)], "skips": []}
    ])
    with pytest.raises(ContractError) as exc:
        validate_document(doc, expected_run_ref=RUN_REF, presented=_presented(**{"conv-1": [1, 2, 3]}))
    assert any("key_invalid" in e for e in exc.value.errors)


@pytest.mark.parametrize("raw,expected", [
    ("snapshot-catalogue-sessionStorage-stale", "snapshot-catalogue-sessionstorage-stale"),
    ("rideau-hermétique-juge-résolution-et-texte", "rideau-hermetique-juge-resolution-et-texte"),
    ("docs-annonçaient-fuite-journal", "docs-annoncaient-fuite-journal"),
    ("a__b  c", "a-b-c"),
    ("-commence-par-tiret", "commence-par-tiret"),
    ("finit-par-tiret-", "finit-par-tiret"),
    ("", ""),
    ("éàç", "eac"),
    ("!!!", ""),
])
def test_normalize_atom_key(raw, expected):
    assert normalize_atom_key(raw) == expected


def test_normalize_atom_key_tronque_sans_tiret_final():
    out = normalize_atom_key("a" * 127 + "-bbb")
    assert len(out) <= 128 and not out.endswith("-") and out == "a" * 127
    assert len(normalize_atom_key("x" * 300)) == 128


def test_validate_key_accentuee_normalisee_avec_warning(caplog):
    doc = _doc(conversations=[
        {"conversation_uid": "conv-1", "atoms": [_atom(key="docs-annonçaient-Fuite")], "skips": []}
    ])
    with caplog.at_level("INFO"):
        cleaned = validate_document(doc, expected_run_ref=RUN_REF, presented=_presented(**{"conv-1": [1, 2, 3]}))
    assert cleaned["conversations"][0]["atoms"][0]["key"] == "docs-annoncaient-fuite"
    # La clé brute (venue du LLM) ne part jamais en clair dans le journal.
    assert any("key_normalized" in r.getMessage() and "raw_sha8" in r.getMessage()
               and "docs-annonçaient-Fuite" not in r.getMessage()
               for r in caplog.records)


def test_validate_value_trop_longue():
    doc = _doc(conversations=[
        {"conversation_uid": "conv-1", "atoms": [_atom(value="x" * 6001)], "skips": []}
    ])
    with pytest.raises(ContractError) as exc:
        validate_document(doc, expected_run_ref=RUN_REF, presented=_presented(**{"conv-1": [1, 2, 3]}))
    assert any("value_invalid" in e for e in exc.value.errors)


@pytest.mark.parametrize("bad_score", [-1, 101, 1000])
def test_validate_confidence_hors_bornes(bad_score):
    doc = _doc(conversations=[
        {"conversation_uid": "conv-1", "atoms": [_atom(confidence_score=bad_score)], "skips": []}
    ])
    with pytest.raises(ContractError) as exc:
        validate_document(doc, expected_run_ref=RUN_REF, presented=_presented(**{"conv-1": [1, 2, 3]}))
    assert any("confidence_score_invalid" in e for e in exc.value.errors)


def test_validate_plus_de_200_atomes():
    atoms = [_atom(key=f"cle-{i}", message_ids=[1]) for i in range(MAX_ATOMS_PER_RUN + 1)]
    doc = _doc(conversations=[{"conversation_uid": "conv-1", "atoms": atoms, "skips": []}])
    with pytest.raises(ContractError) as exc:
        validate_document(doc, expected_run_ref=RUN_REF, presented=_presented(**{"conv-1": [1, 2, 3]}))
    assert any("atoms_total_exceeds_cap" in e for e in exc.value.errors)


def test_validate_champ_inconnu_erreur():
    doc = _doc(conversations=[
        {"conversation_uid": "conv-1", "atoms": [_atom(unexpected_field="x")], "skips": []}
    ])
    with pytest.raises(ContractError) as exc:
        validate_document(doc, expected_run_ref=RUN_REF, presented=_presented(**{"conv-1": [1, 2, 3]}))
    assert any("unknown_field:unexpected_field" in e for e in exc.value.errors)


def test_validate_champs_interdits_retires_avec_compteur():
    doc = _doc(conversations=[
        {
            "conversation_uid": "conv-1",
            "atoms": [
                # LES QUATRE CHAMPS INTERDITS, ET PAS DEUX. Ce cas n'en posait
                # que deux (`node_id`, `source_ref`) et vérifiait pourtant
                # l'absence des quatre : les deux dernières assertions étaient
                # VRAIES PAR CONSTRUCTION — retirer `confidence` et
                # `audit_source` de FORBIDDEN_ATOM_FIELDS laissait ce test vert.
                _atom(node_id="mac-mini-01", source_ref={"fake": True},
                      confidence="auditor_validated",
                      audit_source="interactive_human_validated"),
            ],
            "skips": [],
        }
    ])
    cleaned = validate_document(doc, expected_run_ref=RUN_REF, presented=_presented(**{"conv-1": [1, 2, 3]}))
    assert cleaned["_stripped_fields_count"] == 4
    atom = cleaned["conversations"][0]["atoms"][0]
    # Le témoin : ce que le contrat GARDE. Sans lui, on ne saurait pas si
    # l'instrument voit quoi que ce soit dans cette collection.
    assert "key" in atom and "value" in atom
    assert "node_id" not in atom
    assert "source_ref" not in atom
    assert "confidence" not in atom
    assert "audit_source" not in atom


def test_validate_document_sain_retour_nettoye():
    doc = _doc()
    cleaned = validate_document(doc, expected_run_ref=RUN_REF, presented=_presented(**{"conv-1": [1, 2, 3]}))
    assert cleaned["_stripped_fields_count"] == 0
    assert cleaned["contract_version"] == CONTRACT_VERSION
    assert cleaned["run_ref"] == RUN_REF
    assert cleaned["complete"] is True
    assert cleaned["audit_summary"] == doc["audit_summary"]
    assert cleaned["conversations"] == [
        {
            "conversation_uid": "conv-1",
            "skips": [],
            "atoms": [_atom()],
        }
    ]
