"""VÉRIFICATION FINALE du périmètre de déploiement RÉDUIT : **A + B seuls**.

Contexte : le fix C (`ARAC_CORTEX_UID_NEARMATCH`) est ABANDONNÉ — gain mesuré
ZÉRO au rejeu prod (il ne sauve pas le run 64, qui cumule un second mode
`message_id` halluciné) et il était la source des 3 failles du red team (F1
jumeau fantôme, F2 transfert d'attribution, N1 TypeError). Le périmètre
proposé a donc CHANGÉ après les 3 rounds de revue : il mérite sa
propre vérification, c'est l'objet de ce fichier.

HERMÉTIQUE : aucune DB, aucun réseau.

Quatre volets :
  1. ISOLATION DE C — flag C absent, la logique de DÉCISION de C n'est jamais
     atteinte, et A/B ne dépendent d'AUCUN artefact de C.
  2. RE-ATTAQUE de A et B armés ENSEMBLE (les rounds précédents les avaient
     surtout attaqués séparément).
  3. F3-bis — faille RÉSIDUELLE de A, OUVERTE, enregistrée en `xfail(strict)`.
  4. Sémantique des compteurs de tolérance (ils portent le signal de rollback).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.cortex import contract  # noqa: E402

RUN_REF = "circadian_0400@2026-07-20"
UID = "11111111-2222-3333-4444-555555555555"
OTHER = "99999999-8888-7777-6666-555555555555"


@pytest.fixture()
def armed_ab(monkeypatch):
    """Périmètre EXACT proposé au déploiement : A ON, B ON, C OFF, D OFF."""
    monkeypatch.setenv("ARAC_CORTEX_RUNREF_LENIENT", "1")
    monkeypatch.setenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", "1")
    monkeypatch.delenv("ARAC_CORTEX_UID_NEARMATCH", raising=False)
    monkeypatch.delenv("ARAC_CORTEX_DEDUP_UID_STRICT", raising=False)


def _presented():
    """Pack à DEUX conversations : la cible (1,3 rendus / 2,4 vides, plage
    jusqu'à 10) et une voisine — le matériau des attaques inter-conversation."""
    return {
        UID: {"conversation_id": "c1", "max_id": 10,
              "message_ids": {1, 3}, "empty_ids": {2, 4}},
        OTHER: {"conversation_id": "c2", "max_id": 60,
                "message_ids": {50}, "empty_ids": {51}},
    }


def _doc(ids, *, uid=UID, run_ref=RUN_REF, extra_convs=()):
    conv = {"conversation_uid": uid, "no_new_knowledge": False, "skips": [],
            "atoms": [{"scope": "outillage", "kind": "note", "key": "demo-key",
                       "value": "v", "confidence_score": 90,
                       "message_ids": list(ids)}]}
    return {"contract_version": contract.CONTRACT_VERSION, "run_ref": run_ref,
            "complete": True, "audit_summary": "t",
            "conversations": [conv, *extra_convs]}


def _validate(doc, presented=None, run_ref=RUN_REF):
    return contract.validate_document(
        doc, expected_run_ref=run_ref, presented=presented or _presented())


# ===========================================================================
# 1. ISOLATION DE C — le code de C est-il strictement inerte, flag C OFF ?
# ===========================================================================


def test_isolation_C_logique_de_decision_jamais_appelee(armed_ab, monkeypatch):
    """A+B armés, C OFF : `_nearmatch_uid` et `_membership_proof_count` — les
    DEUX seules fonctions qui portent la DÉCISION de C — ne sont jamais
    appelées, y compris sur le cas qui les déclencherait (uid corrompu).

    C'est la preuve d'inertie qui autorise à laisser le code de C en place
    (flag OFF) plutôt qu'à le découpler : un découplage serait un changement
    de code NON revu, donc plus risqué que l'inertie prouvée."""
    def _boom(*a, **k):  # pragma: no cover - doit ne jamais être atteint
        raise AssertionError("logique de FIX C atteinte alors que le flag est OFF")

    monkeypatch.setattr(contract, "_nearmatch_uid", _boom)
    monkeypatch.setattr(contract, "_membership_proof_count", _boom)

    # uid à distance d'édition 1 d'un uid RÉEL du pack = le cas de C.
    corrompu = UID.replace("11111111", "1111111")
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc([1, 3], uid=corrompu))
    assert f"unknown_conversation:{corrompu}" in exc.value.errors
    # ... et rien n'est attribué : pas de punition d'une conversation réelle.
    assert exc.value.attributed_uids == frozenset()


def test_isolation_C_aucun_artefact_de_C_dans_le_document_nettoye(armed_ab):
    """A et B produisent leurs compteurs SANS jamais produire ceux de C."""
    doc = _validate(_doc([1, 2], run_ref="digest maison"))
    assert doc["_runref_lenient_count"] == 1          # A a agi
    assert doc["_empty_ids_tolerated_count"] == 1     # B a agi
    assert "_uid_nearmatch_count" not in doc          # C n'a rien produit
    assert "_uid_nearmatch_repairs" not in doc


def test_isolation_C_les_structures_de_C_restent_vides(armed_ab, monkeypatch):
    """Les structures introduites par C et lues sur le chemin PRINCIPAL
    (`repaired_uids` dans le test d'attribution, `dup_only_errors`) restent
    neutres : une violation réelle est attribuée EXACTEMENT comme sur `main`."""
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc([1, 50]))  # id de la conversation VOISINE -> fatal
    assert exc.value.errors == [f"foreign_message_ids:{UID}"]
    assert exc.value.attributed_uids == frozenset({UID}), (
        "l'attribution doit rester celle de `main` — `repaired_uids` vide")


def test_isolation_D_neutralise_meme_flag_arme(monkeypatch):
    """FIX D est court-circuité (round-3, finding N2) : même flag ARMÉ, un
    doublon d'uid reste ACCEPTÉ (comportement de `main`). Vérifié ici parce
    que D est le seul fix dont la neutralisation repose sur un `return False`
    et non sur l'absence de flag."""
    monkeypatch.setenv("ARAC_CORTEX_DEDUP_UID_STRICT", "1")
    assert contract._dedup_uid_strict_enabled() is False
    dup = {"conversation_uid": UID, "no_new_knowledge": True, "skips": [], "atoms": []}
    doc = _validate(_doc([1, 3], extra_convs=(dup,)))
    assert len(doc["conversations"]) == 2, "le doublon passe, comme sur `main`"


# ===========================================================================
# 2. RE-ATTAQUE de A ET B ARMÉS ENSEMBLE
# ===========================================================================


@pytest.mark.parametrize("ids,motif", [
    ([1, 50], "id d'une AUTRE conversation du pack"),
    ([1, 51], "id VIDE d'une AUTRE conversation du pack"),
    ([1, 99], "id au-delà de max_id (halluciné)"),
    ([1, 0], "id sous cursor_from (déjà curé)"),
    ([2, 4], "provenance ENTIÈREMENT vide (aucun id rendu)"),
    ([2], "un seul id, vide"),
])
def test_B_les_gardes_durs_tiennent_avec_A_arme(armed_ab, ids, motif):
    """Cheval de Troie par ids vides : les 3 conditions cumulatives de B ne
    sont relâchées par AUCUNE interaction avec A."""
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc(ids))
    assert any(e.startswith("foreign_message_ids") for e in exc.value.errors), motif


def test_B_provenance_persistee_est_un_SOUS_ENSEMBLE_des_ids_rendus(armed_ab):
    """Invariant de non-régression le plus important de B : ce qui est GRAVÉ
    en provenance ne peut jamais désigner un message que le LLM n'a pas vu."""
    doc = _validate(_doc([1, 2, 3, 4]))
    prov = doc["conversations"][0]["atoms"][0]["message_ids"]
    assert set(prov) <= _presented()[UID]["message_ids"]
    assert set(prov) & _presented()[UID]["empty_ids"] == set()


def test_B_inerte_si_le_pack_n_expose_pas_empty_ids(armed_ab):
    """`ARAC_PACK_DROP_EMPTY` OFF -> `presented` sans `empty_ids` : B ne peut
    RIEN tolérer (il n'a pas de matière). Défense contre un déploiement
    partiel où l'un des deux flags serait armé sans l'autre."""
    pres = {UID: {"conversation_id": "c1", "max_id": 10, "message_ids": {1, 3}}}
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc([1, 2]), presented=pres)
    assert exc.value.errors == [f"foreign_message_ids:{UID}"]


def test_A_un_autre_slot_key_BIEN_FORME_reste_fatal(armed_ab):
    """F3 (rejeu inter-run), volet FERMÉ : un document portant le `run_ref`
    d'un AUTRE run réel reste rejeté, flag A armé."""
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc([1, 3], run_ref="circadian_2100@2026-07-19"))
    assert any(e.startswith("run_ref_mismatch:sha8=") for e in exc.value.errors)


def test_A_ne_fuit_jamais_la_valeur_brute_du_LLM(armed_ab):
    """R4 : ni le document nettoyé ni le message d'erreur ne portent la valeur
    déclarée en clair (elle peut contenir une PII — V0.107)."""
    poison = "digest de Jean-Michel Dupont " + "x" * 4000
    doc = _validate(_doc([1, 3], run_ref=poison))
    assert doc["run_ref"] == RUN_REF, "le slot_key SERVEUR écrase l'halluciné"
    assert poison not in repr(doc)
    assert len(doc["_runref_declared_sha8"]) == 8

    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc([1, 3], run_ref="circadian_2100@2026-07-19"))
    assert "circadian_2100@2026-07-19" not in repr(exc.value.errors)


@pytest.mark.parametrize("atoms", [5, True, 1.5, "x", {"a": 1}])
def test_N1_type_inattendu_sur_atoms_leve_ContractError_pas_TypeError(armed_ab, atoms):
    """N1 (round-3) re-vérifié sur le périmètre A+B : `atoms` d'un type
    arbitraire produit une `ContractError` — jamais une exception nue qui
    laisserait un reçu ORPHELIN au statut `spawning` (spawn payé perdu)."""
    doc = _doc([1, 3])
    doc["conversations"][0]["atoms"] = atoms
    with pytest.raises(contract.ContractError):
        _validate(doc)


@pytest.mark.parametrize("bad", [5, "x", {"a": 1}, None])
def test_document_malforme_ne_crashe_jamais(armed_ab, bad):
    """Le validateur travaille sur du JSON 100 % contrôlé par le LLM."""
    doc = _doc([1, 3])
    doc["conversations"] = bad
    with pytest.raises(contract.ContractError):
        _validate(doc)


# ===========================================================================
# 3. F3-bis — FAILLE RÉSIDUELLE DE A, OUVERTE (enregistrée, non bloquante)
# ===========================================================================


@pytest.mark.xfail(strict=True, reason=(
    "F3-bis OUVERT (vérification finale 2026-07-20) — la lénience GRAMMATICALE "
    "de A ne ferme le rejeu inter-run QUE pour un `run_ref` BIEN FORMÉ. Un "
    "document d'un run PASSÉ dont le `run_ref` est absent/null/vide/non "
    "grammatical est ACCEPTÉ comme réponse du run courant. Reproduit sur "
    "matériau prod : le bloc `ece02aff` du run 63 rejoué contre le pack du run "
    "67 (même conversation, curseur inchangé 53743, tranche étendue "
    "54776->56099) est ACCEPTÉ sous A seul -> curseur avancé sur 1323 messages "
    "jamais lus + 5 autres conversations du pack comptées `coverage_omitted` "
    "(streak d'exclusion low_yield sous ARAC_DISPOSE_COVERAGE_V2, ARMÉ en "
    "prod). Sur `main`, ces 5 formes sont TOUTES fatales. Ce test passera au "
    "vert le jour où A sera resserré ; il doit rester rouge d'ici là."))
@pytest.mark.parametrize("run_ref", [None, "", "   ", "digest du 19 juillet", 0])
def test_F3bis_un_run_ref_non_grammatical_devrait_rester_fatal(armed_ab, run_ref):
    with pytest.raises(contract.ContractError) as exc:
        _validate(_doc([1, 3], run_ref=run_ref))
    assert any("run_ref" in e for e in exc.value.errors)


def test_F3bis_caracterisation_surface_reellement_ouverte_par_A(armed_ab):
    """Caractérisation FACTUELLE de la surface de A (à graver dans le dossier
    de décision) : le mode MESURÉ est une chaîne inventée (run 59,
    `manual_digest_2026-07-19`) ; A tolère en réalité TOUT ce qui n'est pas un
    slot_key bien formé, y compris l'ABSENCE du champ."""
    ouvert = []
    for label, mut in (
        ("champ absent", lambda d: d.pop("run_ref")),
        ("null", lambda d: d.__setitem__("run_ref", None)),
        ("chaîne vide", lambda d: d.__setitem__("run_ref", "")),
        ("entier", lambda d: d.__setitem__("run_ref", 0)),
        ("liste", lambda d: d.__setitem__("run_ref", [])),
        ("chaîne inventée (mode MESURÉ)", lambda d: d.__setitem__("run_ref", "x")),
    ):
        d = _doc([1, 3])
        mut(d)
        try:
            _validate(d)
            ouvert.append(label)
        except contract.ContractError:
            pass
    assert ouvert == ["champ absent", "null", "chaîne vide", "entier", "liste",
                      "chaîne inventée (mode MESURÉ)"], (
        "si cette liste RÉTRÉCIT, A a été resserré : mettre à jour le dossier "
        "de décision et retirer le xfail de `test_F3bis_...`")


# ===========================================================================
# 4. COMPTEURS DE TOLÉRANCE — ils portent le SIGNAL DE ROLLBACK
# ===========================================================================


def test_compteur_B_compte_les_occurrences_pas_les_ids_distincts(armed_ab):
    """DÉFAUT D'OBSERVABILITÉ mesuré : `_empty_ids_tolerated_count` compte les
    OCCURRENCES (ids répétés inclus) alors que `_empty_ids_tolerated` liste les
    DISTINCTS. Le seuil de rollback « B s'active sur > X % des atomes » se lit
    sur le compteur : il est donc GONFLABLE par un LLM qui répète un id. Le
    dossier de décision doit imposer la lecture de `len(_empty_ids_tolerated)`,
    PAS de `_empty_ids_tolerated_count`."""
    doc = _validate(_doc([1, 2, 2, 2, 2]))
    assert doc["_empty_ids_tolerated_count"] == 4      # occurrences
    assert doc["_empty_ids_tolerated"] == [2]          # distincts
    assert doc["conversations"][0]["atoms"][0]["message_ids"] == [1]


def test_compteurs_absents_quand_rien_n_est_tolere(armed_ab):
    """Flags ARMÉS mais document SAIN : aucune clé `_*` de fidélité -> le reçu
    prod reste bit-identique tant que les tolérances ne servent pas."""
    doc = _validate(_doc([1, 3]))
    for k in ("_runref_lenient_count", "_runref_declared_sha8",
              "_empty_ids_tolerated_count", "_empty_ids_tolerated",
              "_uid_nearmatch_count", "_uid_nearmatch_repairs"):
        assert k not in doc


def test_un_seul_id_rendu_suffit_a_tolerer_N_vides(armed_ab):
    """Caractérisation : la condition « >= 1 id rendu » est une preuve FAIBLE —
    un atome peut citer 1 rendu et N vides. Borné et sans conséquence sur la
    provenance gravée (réduite au seul id rendu), mais à connaître."""
    doc = _validate(_doc([1, 2, 4]))
    assert doc["_empty_ids_tolerated_count"] == 2
    assert doc["conversations"][0]["atoms"][0]["message_ids"] == [1]
