"""FIX B — `ARAC_CORTEX_EMPTY_DROP_TOLERANT` (chantier fidélité A+B+C).

HERMÉTIQUE : aucune DB, aucun réseau (fakes partagés `tests/test_stab_wave2`).

CE QUE B CORRIGE (mesure it.3, runs 61+63) : sous `ARAC_PACK_DROP_EMPTY`, les
messages VIDES ne sont pas rendus au LLM mais restent COUVERTS par le curseur.
Le LLM, qui voit la numérotation `[id=N]` trouée, cite parfois un de ces ids
vides -> `foreign_message_ids` -> QUARANTAINE DU RUN ENTIER pour une citation
qui n'apporte ni ne prouve rien (le message est vide par définition).

CE QUE B NE RELÂCHE PAS (le filet anti-poison reste entier) :
  - un id d'une AUTRE conversation reste FATAL ;
  - un id HORS de la plage couverte (halluciné/extrapolé) reste FATAL ;
  - un atome dont TOUTE la provenance est vide reste FATAL (>= 1 id
    réellement RENDU exigé) ;
  - les ids vides tolérés sont RETIRÉS de la provenance de l'atome : ils ne
    peuvent JAMAIS être gravés dans `source_ref.message_ids` (policy.py:119).

Flag OFF (défaut) : comportement bit-identique — prouvé ci-dessous par
comparaison du document nettoyé ET du couple (erreurs, uids attribués).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.cortex import contract  # noqa: E402
from agents.cortex import pack as pack_mod  # noqa: E402
from tests.test_stab_wave2 import FakeCuratorLib, _conv, _msg  # noqa: E402

RUN_REF = "slot"


@pytest.fixture()
def curator_lib(monkeypatch):
    fake = FakeCuratorLib([], {})
    monkeypatch.setattr(pack_mod, "curator_lib_v2", fake)

    async def _fake_known(db, uids):
        return "(aucun)"

    monkeypatch.setattr(pack_mod, "_known_atoms_block", _fake_known)
    return fake


async def _build(curator_lib):
    """Pack RÉEL (pas un fixture à la main) : u-1 = [1 plein, 2 VIDE,
    3 plein], u-2 = [10 plein] — l'autre conversation du même pack."""
    curator_lib.conversations = [_conv("c1", "u-1"), _conv("c2", "u-2")]
    curator_lib.messages_by_conv = {
        "c1": [_msg(1, "vrai contenu"), _msg(2, ""), _msg(3, "autre contenu")],
        "c2": [_msg(10, "conversation voisine")],
    }
    return await pack_mod.build_pack(object(), budget_tokens=10_000, count_fn=len)


def _doc(ids, uid="u-1"):
    return {
        "contract_version": contract.CONTRACT_VERSION, "run_ref": RUN_REF,
        "complete": True, "audit_summary": "t",
        "conversations": [{
            "conversation_uid": uid, "no_new_knowledge": False,
            "atoms": [{"scope": "outillage", "kind": "note", "key": "k-1",
                       "value": "v", "confidence_score": 90,
                       "message_ids": ids}],
            "skips": [],
        }],
    }


def _validate(doc, presented):
    return contract.validate_document(
        doc, expected_run_ref=RUN_REF, presented=presented)


# ===========================================================================
# Le pack expose bien les 3 populations d'ids (couvert / rendu / vide)
# ===========================================================================


async def test_pack_expose_empty_ids_disjoints_des_rendus(curator_lib, monkeypatch):
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    presented = (await _build(curator_lib))["presented"]
    assert presented["u-1"]["message_ids"] == {1, 3}, "ids RENDUS seulement"
    assert presented["u-1"]["empty_ids"] == {2}, "id couvert-mais-vide"
    assert presented["u-1"]["max_id"] == 3, "plage couverte inchangée"
    assert not (presented["u-1"]["message_ids"] & presented["u-1"]["empty_ids"])
    assert presented["u-2"]["empty_ids"] == set(), "aucun vide dans u-2"


async def test_pack_sans_drop_empty_aucun_empty_id(curator_lib, monkeypatch):
    """DROP_EMPTY OFF : rien n'est dropé -> `empty_ids` vide (B inopérant)."""
    monkeypatch.delenv("ARAC_PACK_DROP_EMPTY", raising=False)
    presented = (await _build(curator_lib))["presented"]
    assert presented["u-1"]["message_ids"] == {1, 2, 3}
    assert presented["u-1"]["empty_ids"] == set()


# ===========================================================================
# FLAG OFF — bit-identique
# ===========================================================================


async def test_off_id_vide_reste_fatal(curator_lib, monkeypatch):
    """OFF (défaut, variable ABSENTE) : citer l'id vide 2 = quarantaine
    attribuée, exactement comme avant B (test_stab_fix_round1 F7)."""
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    monkeypatch.delenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", raising=False)
    presented = (await _build(curator_lib))["presented"]
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc([1, 2, 3]), presented)
    assert exc.value.errors == ["foreign_message_ids:u-1"]
    assert exc.value.attributed_uids == frozenset({"u-1"})


@pytest.mark.parametrize("value", ["0", "off", "", "no", "faux"])
async def test_off_valeurs_non_armantes(curator_lib, monkeypatch, value):
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    monkeypatch.setenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", value)
    presented = (await _build(curator_lib))["presented"]
    with pytest.raises(contract.ContractError):
        _validate(_doc([1, 2]), presented)


async def test_off_document_sain_bit_identique(curator_lib, monkeypatch):
    """OFF : un document SAIN produit exactement le même nettoyé qu'avant B —
    aucune clé `_empty_ids_tolerated*`, provenance intacte."""
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    monkeypatch.delenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", raising=False)
    presented = (await _build(curator_lib))["presented"]
    doc = _validate(_doc([1, 3]), presented)
    assert doc["conversations"][0]["atoms"][0]["message_ids"] == [1, 3]
    assert "_empty_ids_tolerated_count" not in doc
    assert "_empty_ids_tolerated" not in doc


async def test_on_document_sain_bit_identique_a_off(curator_lib, monkeypatch):
    """ON mais RIEN à tolérer : sortie strictement identique à OFF (le fix
    est un pur sur-ensemble, il ne modifie aucun chemin sain)."""
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    presented = (await _build(curator_lib))["presented"]
    monkeypatch.delenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", raising=False)
    off = _validate(_doc([1, 3]), presented)
    monkeypatch.setenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", "1")
    on = _validate(_doc([1, 3]), presented)
    assert on == off


# ===========================================================================
# FLAG ON — propriétés
# ===========================================================================


async def test_on_id_vide_same_conv_passe_et_sort_de_la_provenance(
        curator_lib, monkeypatch):
    """EXIGENCE 1+3 : l'atome PASSE, et l'id vide 2 n'est PLUS cité comme
    source (il ne peut donc jamais atterrir dans `source_ref.message_ids`)."""
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    monkeypatch.setenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", "1")
    presented = (await _build(curator_lib))["presented"]
    doc = _validate(_doc([1, 2, 3]), presented)
    atom = doc["conversations"][0]["atoms"][0]
    assert atom["message_ids"] == [1, 3], "id vide RETIRÉ de la provenance"
    assert doc["_empty_ids_tolerated_count"] == 1
    assert doc["_empty_ids_tolerated"] == [2]


async def test_on_ordre_et_doublons_des_ids_rendus_preserves(
        curator_lib, monkeypatch):
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    monkeypatch.setenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", "1")
    presented = (await _build(curator_lib))["presented"]
    doc = _validate(_doc([3, 2, 1, 3]), presented)
    assert doc["conversations"][0]["atoms"][0]["message_ids"] == [3, 1, 3]


async def test_on_atome_uniquement_vide_reste_rejete(curator_lib, monkeypatch):
    """EXIGENCE 2 : >= 1 id RÉELLEMENT RENDU exigé — un atome dont toute la
    provenance est vide ne prouve rien, il reste FATAL même flag ON."""
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    monkeypatch.setenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", "1")
    presented = (await _build(curator_lib))["presented"]
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc([2]), presented)
    assert "foreign_message_ids:u-1" in exc.value.errors
    assert exc.value.attributed_uids == frozenset({"u-1"})


async def test_on_id_autre_conversation_reste_fatal(curator_lib, monkeypatch):
    """Anti-poison INTACT : l'id 10 existe (conv u-2 du MÊME pack) mais est
    cité sous u-1 -> attribution croisée = FATAL, flag ON compris."""
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    monkeypatch.setenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", "1")
    presented = (await _build(curator_lib))["presented"]
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc([1, 10]), presented)
    assert "foreign_message_ids:u-1" in exc.value.errors


async def test_on_id_vide_dune_autre_conv_reste_fatal(curator_lib, monkeypatch):
    """Le vide de u-2 n'est PAS un passe-droit pour u-1 : `empty_ids` est lu
    sur le `pack_entry` de LA conversation déclarée, jamais globalement."""
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    monkeypatch.setenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", "1")
    curator_lib.conversations = [_conv("c1", "u-1"), _conv("c2", "u-2")]
    curator_lib.messages_by_conv = {
        "c1": [_msg(1, "plein"), _msg(2, "")],
        "c2": [_msg(10, "plein"), _msg(11, "")],
    }
    built = await pack_mod.build_pack(object(), budget_tokens=10_000, count_fn=len)
    presented = built["presented"]
    assert presented["u-2"]["empty_ids"] == {11}
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc([1, 11]), presented)
    assert "foreign_message_ids:u-1" in exc.value.errors


@pytest.mark.parametrize("bad_id", [4, 99, 0, -1])
async def test_on_id_hors_plage_reste_fatal(curator_lib, monkeypatch, bad_id):
    """EXIGENCE : hors [cursor_from, max_id] (extrapolation `max_id+1`,
    hallucination) -> FATAL. Ces ids ne sont dans AUCUNE des deux listes."""
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    monkeypatch.setenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", "1")
    presented = (await _build(curator_lib))["presented"]
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc([1, bad_id]), presented)
    assert "foreign_message_ids:u-1" in exc.value.errors


async def test_on_melange_vide_tolerable_et_hors_plage_reste_fatal(
        curator_lib, monkeypatch):
    """Tolérance TOUT-OU-RIEN : un seul id non tolérable suffit à garder le
    rejet — jamais de salvage partiel de la provenance."""
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "1")
    monkeypatch.setenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", "1")
    presented = (await _build(curator_lib))["presented"]
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc([1, 2, 42]), presented)
    assert "foreign_message_ids:u-1" in exc.value.errors


async def test_on_sans_cle_empty_ids_aucune_tolerance(monkeypatch):
    """Fail-toward-strict : `presented` d'une version antérieure (clé
    `empty_ids` ABSENTE, reprise mid-déploiement) -> FATAL comme avant."""
    monkeypatch.setenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", "1")
    presented = {"u-1": {"max_id": 3, "message_ids": {1, 3}}}
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc([1, 2]), presented)
    assert "foreign_message_ids:u-1" in exc.value.errors


async def test_on_uid_inconnu_toujours_rejete(monkeypatch):
    """B ne touche pas au guard `unknown_conversation` (périmètre du fix C) :
    un uid absent du pack n'a pas de `pack_entry`, donc pas de tolérance."""
    monkeypatch.setenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", "1")
    presented = {"u-1": {"max_id": 3, "message_ids": {1, 3}, "empty_ids": {2}}}
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc([1, 2], uid="u-hallucinee"), presented)
    assert "unknown_conversation:u-hallucinee" in exc.value.errors
