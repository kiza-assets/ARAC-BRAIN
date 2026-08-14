"""FIX C — `ARAC_CORTEX_UID_NEARMATCH` (chantier fidélité A+B+C).

HERMÉTIQUE : aucune DB, aucun réseau (packs `presented` construits à la main).

CE QUE C CORRIGE (mesure it.3, run 64 réel) : le LLM recopie un
`conversation_uid` RÉEL du pack en le CORROMPANT à la transcription
(`6e2143-0e70-4388-a7ea-51944cdfbb0b` pour
`6e2b6143-0e70-4388-a7ea-51944cdfbb0b`, 2 caractères perdus sur 36)
-> `unknown_conversation` -> QUARANTAINE DU RUN ENTIER, alors que le contenu
produit est bon et que la conversation visée est certaine.

SEUILS DÉRIVÉS DES DONNÉES (prod 2026-07-20, 244 uids réels de
`arac.conversations`) :
  - distance d'édition MIN entre deux uids réels distincts = 21 ;
  - suffixe commun MAX entre deux uids réels distincts     = 3 ;
  - cas run 64 : distance 2 / suffixe 31 (2e candidat du pack : 23 / 1) ;
  - mode « ids de messages » du run 52 (`unknown_conversation:150884`) :
    distance 30 / suffixe 1 -> reste FATAL (ce n'est pas une corruption).
=> seuils `distance <= 2` OU `suffixe >= 30` : marge de 19 caractères
   (resp. 27) avant qu'une paire d'uids RÉELS puisse être confondue.

CE QUE C NE RELÂCHE PAS :
  - match AMBIGU (>= 2 candidats du pack) -> FATAL, on ne devine jamais ;
  - uid totalement inconnu -> FATAL ;
  - après réparation, `foreign_message_ids` s'applique NORMALEMENT (un atome
    citant des ids d'une AUTRE conversation reste rejeté).

Flag OFF (défaut) : comportement bit-identique — prouvé ci-dessous.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.cortex import contract  # noqa: E402

RUN_REF = "slot"

# --- Données RÉELLES du run 64 (arac.run_receipts id=64, 2026-07-20 02:00Z) ---
REAL_UID = "6e2b6143-0e70-4388-a7ea-51944cdfbb0b"      # uid du pack
DECLARED_UID = "6e2143-0e70-4388-a7ea-51944cdfbb0b"    # uid écrit par le LLM
OTHER_UIDS = [                                          # les 3 autres du pack 64
    "72bc5ab6-ef5d-4d3d-b95f-9686b4208f47",
    "ece02aff-c792-4b09-ae66-58073da518e5",
    "785081ee-8660-4a43-ac60-3caeb132c2cb",
]


def _presented(uids=None):
    """Pack du run 64 : la conv réelle (ids 1..3) + les 3 voisines (ids 10..12)."""
    uids = uids if uids is not None else [REAL_UID, *OTHER_UIDS]
    out = {}
    for n, uid in enumerate(uids):
        base = 1 if n == 0 else 10 * (n + 1)
        out[uid] = {
            "max_id": base + 2,
            "message_ids": {base, base + 1, base + 2},
            "empty_ids": set(),
        }
    return out


def _doc(uid, ids=(1, 2)):
    return {
        "contract_version": contract.CONTRACT_VERSION, "run_ref": RUN_REF,
        "complete": True, "audit_summary": "t",
        "conversations": [{
            "conversation_uid": uid, "no_new_knowledge": False,
            "atoms": [{"scope": "outillage", "kind": "note", "key": "k-1",
                       "value": "v", "confidence_score": 90,
                       "message_ids": list(ids)}],
            "skips": [],
        }],
    }


def _validate(doc, presented=None):
    return contract.validate_document(
        doc, expected_run_ref=RUN_REF, presented=presented or _presented())


@pytest.fixture(autouse=True)
def _isole_les_autres_flags(monkeypatch):
    """C est testé SEUL : A et B restent désarmés."""
    monkeypatch.delenv("ARAC_CORTEX_RUNREF_LENIENT", raising=False)
    monkeypatch.delenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", raising=False)


# ===========================================================================
# Calibration : les seuils sont bien ceux dérivés des données
# ===========================================================================


def test_seuils_calibres_sur_le_cas_reel_run_64():
    d = contract._edit_distance(DECLARED_UID, REAL_UID, cutoff=10)
    assert d == 2, "signature mesurée du run 64"
    assert d <= contract._UID_MAX_EDIT_DISTANCE
    # Fix round-1 (F4) : la branche « suffixe commun » a été SUPPRIMÉE — le
    # cas cible passe par la seule branche distance.
    assert not hasattr(contract, "_UID_MIN_COMMON_SUFFIX")


def test_marge_vs_les_autres_uids_du_pack_reel():
    """Les 3 voisines du pack 64 sont HORS de portée (distance >= 21)."""
    for uid in OTHER_UIDS:
        assert contract._edit_distance(DECLARED_UID, uid, cutoff=20) > 20


def test_mode_run_52_ids_de_messages_hors_de_portee():
    """`unknown_conversation:150884` (run 52) n'est PAS une corruption d'uid."""
    for declared in ("150884", "151355", "151467"):
        assert contract._nearmatch_uid(declared, [REAL_UID, *OTHER_UIDS]) == (None, [])


# ===========================================================================
# FLAG OFF — bit-identique
# ===========================================================================


def test_off_cas_run_64_reste_fatal(monkeypatch):
    monkeypatch.delenv("ARAC_CORTEX_UID_NEARMATCH", raising=False)
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc(DECLARED_UID))
    assert exc.value.errors == [f"unknown_conversation:{DECLARED_UID}"]
    assert exc.value.attributed_uids == frozenset(), "uid absent du pack : jamais attribué"


@pytest.mark.parametrize("value", ["0", "off", "", "no", "faux"])
def test_off_valeurs_non_armantes(monkeypatch, value):
    monkeypatch.setenv("ARAC_CORTEX_UID_NEARMATCH", value)
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc(DECLARED_UID))
    assert exc.value.errors == [f"unknown_conversation:{DECLARED_UID}"]


def test_off_et_on_identiques_sur_un_document_sain(monkeypatch):
    """Aucune corruption -> document nettoyé BIT-IDENTIQUE dans les deux états."""
    monkeypatch.delenv("ARAC_CORTEX_UID_NEARMATCH", raising=False)
    off = _validate(_doc(REAL_UID))
    monkeypatch.setenv("ARAC_CORTEX_UID_NEARMATCH", "1")
    on = _validate(_doc(REAL_UID))
    assert off == on
    assert "_uid_nearmatch_count" not in off and "_uid_nearmatch_count" not in on


def test_off_aucune_cle_de_compteur(monkeypatch):
    monkeypatch.delenv("ARAC_CORTEX_UID_NEARMATCH", raising=False)
    cleaned = _validate(_doc(REAL_UID))
    assert not [k for k in cleaned if k.startswith("_uid_nearmatch")]


# ===========================================================================
# FLAG ON — propriétés
# ===========================================================================


def test_on_cas_run_64_repare(monkeypatch, caplog):
    monkeypatch.setenv("ARAC_CORTEX_UID_NEARMATCH", "1")
    with caplog.at_level("INFO", logger="arac.cortex.contract"):
        cleaned = _validate(_doc(DECLARED_UID))
    conv = cleaned["conversations"][0]
    assert conv["conversation_uid"] == REAL_UID, "uid réparé vers la conv RÉELLE"
    assert conv["atoms"][0]["message_ids"] == [1, 2], "provenance intacte"
    assert cleaned["_uid_nearmatch_count"] == 1
    assert cleaned["_uid_nearmatch_repairs"] == [
        {"declared": DECLARED_UID, "repaired": REAL_UID}]
    # la conv réparée n'est PLUS comptée omise (dispose.py:575 : presented[uid])
    assert REAL_UID not in cleaned["_omitted_uids"]
    assert set(cleaned["_omitted_uids"]) == set(OTHER_UIDS)
    assert "uid_nearmatch_repaired" in caplog.text


def test_on_uid_ambigu_reste_fatal(monkeypatch):
    """Deux uids du pack à distance <= 2 du déclaré -> AUCUNE réparation."""
    monkeypatch.setenv("ARAC_CORTEX_UID_NEARMATCH", "1")
    jumeau = REAL_UID[:-1] + "c"          # distance 1 du réel, 2 du déclaré ? -> non
    declared = REAL_UID[:-1] + "d"        # distance 1 de REAL_UID ET 1 de jumeau
    presented = _presented([REAL_UID, jumeau])
    repaired, candidates = contract._nearmatch_uid(declared, list(presented))
    assert repaired is None and len(candidates) == 2, "ambiguïté détectée"
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc(declared), presented)
    assert exc.value.errors == [f"unknown_conversation:{declared}"]
    assert exc.value.attributed_uids == frozenset()


def test_on_uid_totalement_inconnu_reste_fatal(monkeypatch):
    monkeypatch.setenv("ARAC_CORTEX_UID_NEARMATCH", "1")
    for declared in ("00000000-0000-0000-0000-000000000000",
                     "u-hallucinee", "150884", REAL_UID[:18]):
        with pytest.raises(contract.ContractError) as exc:
            _validate(_doc(declared))
        assert exc.value.errors == [f"unknown_conversation:{declared}"]


def test_on_suffixe_long_mais_prefixe_delirant_reste_fatal(monkeypatch):
    """Le critère « suffixe >= 30 » est borné en longueur : pas de fourre-tout."""
    monkeypatch.setenv("ARAC_CORTEX_UID_NEARMATCH", "1")
    # (a) hors forme uuid (trop long) -> rejeté par `_UID_SHAPE_RE`
    for declared in ("deadbeefdeadbeef" + REAL_UID[-31:],   # 47 chars
                     # (b) dans la forme mais delta de longueur 4 > 2
                     "deadbeefd" + REAL_UID[-31:],          # 40 chars
                     # (c) caractères non-uuid
                     "zzzz" + REAL_UID[-32:]):
        with pytest.raises(contract.ContractError) as exc:
            _validate(_doc(declared))
        assert exc.value.errors == [f"unknown_conversation:{declared}"], declared


# ===========================================================================
# Le filet anti-poison reste ENTIER après réparation
# ===========================================================================


def test_on_apres_reparation_ids_dune_autre_conv_toujours_rejetes(monkeypatch):
    """Citer les ids de la conversation voisine reste FATAL — et l'est
    désormais PLUS TÔT : fix round-2 (F5), un bloc dont AUCUN atome ne cite un
    id rendu de la conv cible n'a aucune preuve d'appartenance, la réparation
    est refusée avant même le guard (`unknown_conversation`). Le résultat reste
    FATAL et non attribué : le filet n'est pas affaibli, il est resserré."""
    monkeypatch.setenv("ARAC_CORTEX_UID_NEARMATCH", "1")
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc(DECLARED_UID, ids=(20, 21)))   # ids de OTHER_UIDS[0]
    assert exc.value.errors == [f"unknown_conversation:{DECLARED_UID}"]
    # ... et le poison n'est JAMAIS attribué à la conversation réparée
    # (fix round-1 F2) : flag OFF elle n'était punie par personne, ON non plus.
    assert exc.value.attributed_uids == frozenset()


def test_on_apres_reparation_id_hors_plage_toujours_rejete(monkeypatch):
    monkeypatch.setenv("ARAC_CORTEX_UID_NEARMATCH", "1")
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc(DECLARED_UID, ids=(1, 999_999)))
    assert exc.value.errors == [f"foreign_message_ids:{REAL_UID}"]


def test_on_reparation_nechappe_pas_aux_autres_gardes(monkeypatch):
    """La réparation ne blanchit rien d'autre : kind interdit reste fatal."""
    monkeypatch.setenv("ARAC_CORTEX_UID_NEARMATCH", "1")
    doc = _doc(DECLARED_UID)
    doc["conversations"][0]["atoms"][0]["kind"] = "mission"
    with pytest.raises(contract.ContractError) as exc:
        _validate(doc)
    assert exc.value.errors == ["conversations[0].atoms[0].kind_forbidden:'mission'"]
    assert exc.value.attributed_uids == frozenset()   # fix round-1 F2


def test_on_document_original_non_muté(monkeypatch):
    """La réparation copie la conversation : le doc d'entrée reste intact
    (le brut est journalisé en quarantaine tel qu'émis par le LLM)."""
    monkeypatch.setenv("ARAC_CORTEX_UID_NEARMATCH", "1")
    doc = _doc(DECLARED_UID)
    _validate(doc)
    assert doc["conversations"][0]["conversation_uid"] == DECLARED_UID
