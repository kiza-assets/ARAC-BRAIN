"""Tests — schemas/atom_council/semantic_enrichment_result.schema.json (V1.6G2).

Contrat de sortie du PREMIER appel semantique reel (provider=claude). Valide en
fail-closed : schema parse + draft 2020-12 + $id + additionalProperties false partout
(y compris objets imbriques) + required == properties ; un exemple synthetique SAFE
valide ; rejets cibles. Aucun contenu reel, aucune donnee de payload, aucun secret.
"""
import json
import os

from jsonschema import Draft202012Validator

SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "schemas", "atom_council",
    "semantic_enrichment_result.schema.json",
)


def _load():
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _safe_example():
    """Exemple SYNTHETIQUE SAFE — aucune donnee reelle, bornes courtes anti-transcript."""
    return {
        "result_id": "SER-test00000001",
        "candidate_id": "C-test00000001",
        "source_file_id_redacted": "F-synthetic01",
        "provider": "claude",
        "model": "fable-5-max",
        "chunks_consumed": [
            {"chunk_id": "chunk-0000", "sha256_redacted_10hex": "abc123def0"},
            {"chunk_id": "chunk-0001", "sha256_redacted_10hex": "0fedcba321"},
            {"chunk_id": "chunk-0002", "sha256_redacted_10hex": "1122334455"},
        ],
        "facts": [
            "Fait synthetique explicitement present dans le payload redacted.",
            "Second fait synthetique, sans donnee sensible.",
        ],
        "inferences": [
            {
                "statement": "Inference synthetique prudente, sans verbatim.",
                "basis_redacted": "Base : recoupement de deux faits redacted.",
                "confidence": 0.5,
            }
        ],
        "uncertainties": ["Point d'incertitude synthetique a clarifier."],
        "contradictions": [],
        "proposed_title_redacted": "Titre synthetique propose (redacted)",
        "proposed_body_redacted": (
            "Empreinte structuree synthetique, bornee, sans transcript ni secret : "
            "gouvernance, conseil, dry-run, redaction en precondition."
        ),
        "proposed_scope": "outillage/assistants",
        "proposed_kind": "decision",
        "memory_worthiness": {
            "merits_atom": False,
            "rationale_redacted": "Exemple synthetique : ne merite pas d'atome, test seulement.",
            "confidence": 0.4,
        },
        "overall_confidence": 0.45,
        "no_raw_confirmed": True,
        "no_secret_confirmed": True,
        "created_at": "2026-06-13T00:00:00+00:00",
    }


# ---------------------------------------------------- structure / conformite CANON

def test_schema_parses_and_is_draft_2020_12():
    s = _load()
    assert s["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(s)


def test_schema_id_is_correct():
    s = _load()
    assert s["$id"] == (
        "https://arac.local/schemas/atom_council/semantic_enrichment_result.schema.json"
    )


def test_required_equals_properties():
    s = _load()
    assert set(s["required"]) == set(s["properties"].keys())


def test_additional_properties_false_everywhere():
    """additionalProperties: false a la racine ET dans tous les objets imbriques."""
    s = _load()
    assert s["additionalProperties"] is False
    # objets imbriques : chunks_consumed.items, inferences.items, memory_worthiness
    chunk_item = s["properties"]["chunks_consumed"]["items"]
    assert chunk_item["additionalProperties"] is False
    assert set(chunk_item["required"]) == set(chunk_item["properties"].keys())
    inf_item = s["properties"]["inferences"]["items"]
    assert inf_item["additionalProperties"] is False
    assert set(inf_item["required"]) == set(inf_item["properties"].keys())
    mw = s["properties"]["memory_worthiness"]
    assert mw["additionalProperties"] is False
    assert set(mw["required"]) == set(mw["properties"].keys())


# ---------------------------------------------------- validation positive

def test_safe_example_validates():
    errors = list(Draft202012Validator(_load()).iter_errors(_safe_example()))
    assert errors == [], f"l'exemple synthetique SAFE doit etre valide : {errors}"


# ---------------------------------------------------- rejets cibles (fail-closed)

def test_unknown_field_is_refused():
    poisoned = dict(_safe_example(), champ_inconnu="x")
    assert list(Draft202012Validator(_load()).iter_errors(poisoned))


def test_proposed_body_over_600_is_refused():
    over = dict(_safe_example(), proposed_body_redacted="a" * 601)
    assert list(Draft202012Validator(_load()).iter_errors(over))


def test_confidence_over_one_is_refused():
    bad = dict(_safe_example(), overall_confidence=1.5)
    assert list(Draft202012Validator(_load()).iter_errors(bad))


def test_provider_out_of_enum_is_refused():
    bad = dict(_safe_example(), provider="openai")
    assert list(Draft202012Validator(_load()).iter_errors(bad))


def test_inference_without_basis_is_refused():
    inst = _safe_example()
    inst["inferences"] = [{"statement": "Sans base.", "confidence": 0.3}]
    assert list(Draft202012Validator(_load()).iter_errors(inst))
