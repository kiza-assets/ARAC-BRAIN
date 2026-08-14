"""GATE round-1 du chantier fidélité A+B+C — un test de NON-RÉGRESSION par
faille confirmée par la vérification sceptique (C1..C8).

Les failles C1/C2/C3/C6/C7/C8-partiel sont couvertes par les fichiers
`test_verif_round1_abc.py` (assertions retournées vers le comportement
corrigé) et `test_redteam_fidelity_abc.py` (attaques désormais FERMÉES).
Ce fichier ferme le reste :

  - C4 : les compteurs de fidélité ont un CONSOMMATEUR (reçu + log de run) ;
  - C5 : chaque run logge l'ÉTAT des flags (« armé sans effet » démontrable) ;
  - C8 : near-miss du fix A (tolérance refusée) — le pendant B/C est dans
         `test_verif_round1_abc.py::test_VR5_aucun_log_de_near_miss`.

Hermétique : zéro réseau, zéro DB, zéro spawn.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.cortex import contract, cycle  # noqa: E402

UID_A = "6e2b6143-0e70-4388-a7ea-51944cdfbb0b"
SLOT_NOW = "circadian_1300@2026-07-20"

_FIDELITY_FLAGS = ("ARAC_CORTEX_RUNREF_LENIENT",
                   "ARAC_CORTEX_EMPTY_DROP_TOLERANT",
                   "ARAC_CORTEX_UID_NEARMATCH",
                   "ARAC_CORTEX_DEDUP_UID_STRICT")


@pytest.fixture(autouse=True)
def _flags_off(monkeypatch):
    for name in _FIDELITY_FLAGS:
        monkeypatch.delenv(name, raising=False)


def _pres(*, rendered=(11, 12), empty=(), max_id=12):
    return {UID_A: {"conversation_id": "cid-A", "max_id": max_id,
                    "message_ids": set(rendered), "empty_ids": set(empty),
                    "source_type": "claude_code", "fully_presented": True}}


def _atom(**over):
    base = {"kind": "gotcha", "scope": "outillage/infrastructure", "key": "gate-round1",
            "value": "Un fait durable assez long pour passer la politique.",
            "rationale": None, "confidence_score": 90, "tags": [],
            "supersede_key_hint": None, "message_ids": [11, 12]}
    base.update(over)
    return base


def _doc(*, run_ref=SLOT_NOW, atoms=None, uid=UID_A):
    return {"contract_version": "cortex-dispose/1", "run_ref": run_ref,
            "complete": True,
            "conversations": [{"conversation_uid": uid,
                               "atoms": list(atoms if atoms is not None
                                             else [_atom()]),
                               "skips": []}]}


# ===========================================================================
# C4 — les compteurs de fidélité ont un consommateur
# ===========================================================================

def test_C4_les_compteurs_sont_extraits_pour_le_recu(monkeypatch):
    """Les compteurs produits par A/B/C sont ramassés par `cycle` pour être
    gravés dans le reçu (`progress._fidelity`) et loggués avec le slot_key."""
    monkeypatch.setenv("ARAC_CORTEX_EMPTY_DROP_TOLERANT", "1")
    monkeypatch.setenv("ARAC_CORTEX_RUNREF_LENIENT", "1")
    cleaned = contract.validate_document(
        _doc(run_ref="digest-inventé",
             atoms=[_atom(message_ids=[11, 13])]),
        expected_run_ref=SLOT_NOW,
        presented=_pres(rendered=(11, 12), empty=(13,), max_id=13))

    fidelity = cycle._fidelity_counters(cleaned)
    assert fidelity["_runref_lenient_count"] == 1
    assert fidelity["_empty_ids_tolerated_count"] == 1
    assert fidelity["_empty_ids_tolerated"] == [13]
    assert fidelity["_runref_declared_sha8"] == contract._sha8("digest-inventé")
    # sérialisable tel quel dans la colonne jsonb `progress`
    assert json.loads(json.dumps({"_fidelity": fidelity}))["_fidelity"] == fidelity


def test_C4_aucun_compteur_quand_aucun_correctif_nagit():
    """Cas nominal / tous flags OFF : dict VIDE -> reçu bit-identique (aucune
    clé `_fidelity` ajoutée par `run_cycle`)."""
    cleaned = contract.validate_document(
        _doc(), expected_run_ref=SLOT_NOW, presented=_pres())
    assert cycle._fidelity_counters(cleaned) == {}


def test_C4_aucun_compteur_emis_par_le_contrat_nest_orphelin():
    """Couplage contrat -> reçu : TOUTE clé de fidélité que `contract.py`
    peut écrire dans le document nettoyé doit être ramassée par
    `cycle._FIDELITY_KEYS`. Sans quoi un futur compteur redeviendrait
    invisible depuis la DB (c'était exactement la faille C4)."""
    source = Path(contract.__file__).read_text(encoding="utf-8")
    emitted = set(re.findall(r'cleaned_doc\["(_[a-z0-9_]+)"\]', source))
    # champs de contrat pré-existants, hors périmètre fidélité
    emitted -= {"_stripped_fields_count", "_omitted_uids"}
    assert emitted, "aucune clé détectée : le motif d'extraction a dérivé"
    assert emitted <= set(cycle._FIDELITY_KEYS), emitted - set(cycle._FIDELITY_KEYS)


# ===========================================================================
# C5 — log d'armement des flags
# ===========================================================================

def test_C5_letat_des_flags_est_observable(monkeypatch):
    """« Flag ON mais cas jamais rencontré » et « flag jamais armé » doivent
    être DISTINGUABLES dans journald."""
    for name in cycle._OBSERVED_FLAGS:
        monkeypatch.delenv(name, raising=False)
    assert set(cycle._flags_armed().values()) == {False}

    monkeypatch.setenv("ARAC_CORTEX_UID_NEARMATCH", "1")
    monkeypatch.setenv("ARAC_PACK_DROP_EMPTY", "true")
    armed = cycle._flags_armed()
    assert armed["ARAC_CORTEX_UID_NEARMATCH"] is True
    assert armed["ARAC_PACK_DROP_EMPTY"] is True
    assert armed["ARAC_CORTEX_RUNREF_LENIENT"] is False


def test_C5_les_trois_flags_du_chantier_sont_observes():
    for name in _FIDELITY_FLAGS:
        assert name in cycle._OBSERVED_FLAGS, name


def test_C5_le_log_darmement_est_joignable_a_un_run(monkeypatch, caplog):
    """Le log porte le `slot_key` : un flag armé sans effet reste démontrable
    run par run."""
    monkeypatch.setenv("ARAC_CORTEX_UID_NEARMATCH", "1")
    with caplog.at_level(logging.INFO, logger="arac.cortex.cycle"):
        cycle._log("cortex.flags_armed", slot_key=SLOT_NOW,
                   **cycle._flags_armed())
    event = json.loads(caplog.records[-1].message)
    assert event["event"] == "cortex.flags_armed"
    assert event["slot_key"] == SLOT_NOW
    assert event["ARAC_CORTEX_UID_NEARMATCH"] is True


def test_C5_le_cycle_emet_larmement_avant_toute_branche():
    """Preuve par la source : l'émission est placée juste après le preflight,
    donc AVANT tout `return` (skip budget, slot dupliqué, pack vide…)."""
    src = Path(cycle.__file__).read_text(encoding="utf-8")
    i_flags = src.index('_log("cortex.flags_armed"')
    i_preflight = src.index('_log("cortex.preflight"')
    i_first_return = src.index("            return 0", i_preflight)
    assert i_preflight < i_flags < i_first_return


# ===========================================================================
# C8 — near-miss du fix A (le pendant B/C est dans test_verif_round1_abc.py)
# ===========================================================================

def test_C8_near_miss_A_est_loggue_sans_valeur_brute(monkeypatch, caplog):
    monkeypatch.setenv("ARAC_CORTEX_RUNREF_LENIENT", "1")
    declared = "circadian_0400@2026-07-20"      # slot_key d'un AUTRE run
    with caplog.at_level(logging.INFO, logger="arac.cortex.contract"):
        with pytest.raises(contract.ContractError) as e:
            contract.validate_document(_doc(run_ref=declared),
                                       expected_run_ref=SLOT_NOW,
                                       presented=_pres())
    events = [json.loads(r.message) for r in caplog.records]
    refused = [x for x in events
               if x["event"] == "cortex.contract.runref_lenient_refused"]
    assert len(refused) == 1
    assert refused[0]["reason"] == "wellformed_other_run"
    assert refused[0]["run_ref"] == SLOT_NOW
    assert refused[0]["declared_sha8"] == contract._sha8(declared)
    assert declared not in caplog.text            # jamais la valeur brute
    assert all(declared not in x for x in e.value.errors)
