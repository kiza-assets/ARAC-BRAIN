"""Vérification SCEPTIQUE indépendante des attaques/findings round 1.

Chaque test REPRODUIT (confirme) ou RÉFUTE une allégation. Harness propre,
écrit sans réutiliser les fixtures de la red team.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

_REPO = Path("$ARAC_HOME")
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.cortex import contract, dispose, policy  # noqa: E402
from agents.cortex.atoms_client import AtomsApiDown  # noqa: E402

UID_A = "6e2b6143-0e70-4388-a7ea-51944cdfbb0b"
UID_A_CORRUPT = "6e2143-0e70-4388-a7ea-51944cdfbb0b"   # cas réel run 64 (dist 2)
UID_B = "9f41c0aa-7d15-4a62-b3ce-2210ab77e901"
SLOT_NOW = "circadian_1300@2026-07-20"
SLOT_OLD = "circadian_0400@2026-07-20"
SCOPES = frozenset({"outillage", "outillage/infrastructure", "travail/operations"})


def pres(*, a_rendered=(11, 12), a_empty=(), a_max=12, with_b=False,
         b_rendered=(21, 22), b_empty=(), b_max=22):
    p = {UID_A: {"conversation_id": "cid-A", "max_id": a_max,
                 "message_ids": set(a_rendered), "empty_ids": set(a_empty),
                 "source_type": "claude_code", "fully_presented": True}}
    if with_b:
        p[UID_B] = {"conversation_id": "cid-B", "max_id": b_max,
                    "message_ids": set(b_rendered), "empty_ids": set(b_empty),
                    "source_type": "mac", "fully_presented": True}
    return p


def atom(**over):
    base = {"kind": "gotcha", "scope": "outillage/infrastructure", "key": "verif-cle",
            "value": "Un fait durable assez long pour passer la politique.",
            "rationale": None, "confidence_score": 90, "tags": [],
            "supersede_key_hint": None, "message_ids": [11, 12]}
    base.update(over)
    return base


def doc(convs, *, run_ref=SLOT_NOW):
    return {"contract_version": "cortex-dispose/1", "run_ref": run_ref,
            "complete": True, "audit_summary": "v", "conversations": convs}


def conv(uid, atoms=(), **over):
    c = {"conversation_uid": uid, "atoms": list(atoms), "skips": []}
    c.update(over)
    return c


@pytest.fixture()
def flags(monkeypatch):
    def _set(a=False, b=False, c=False):
        for n, on in (("ARAC_CORTEX_RUNREF_LENIENT", a),
                      ("ARAC_CORTEX_EMPTY_DROP_TOLERANT", b),
                      ("ARAC_CORTEX_UID_NEARMATCH", c)):
            monkeypatch.setenv(n, "1" if on else "0")
    _set()
    return _set


class Lib:
    def __init__(self):
        self.advances, self.failed, self.parked = [], [], []
        self._retry = {}

    async def advance_cursor(self, db, cid, new_cursor, *, atoms_generated):
        self.advances.append((cid, new_cursor, atoms_generated))
        self._retry[cid] = 0

    async def mark_curation_failed(self, db, cid, *, error):
        self.failed.append((cid, error))
        self._retry[cid] = self._retry.get(cid, 0) + 1
        return self._retry[cid]

    async def park_conversation(self, db, cid, *, error):
        self.parked.append((cid, error))

    async def defer_conversation(self, db, cid, *, error):
        return 1

    async def mark_full_omission(self, db, cid, *, error):
        self._retry[cid] = self._retry.get(cid, 0) + 1
        return self._retry[cid], self._retry[cid]

    async def get_atoms_generated(self, db, cid):
        return 0

    async def mark_conversation_excluded(self, db, cid, *, category, reason, by):
        return True


class RQ:
    def __init__(self):
        self.calls = []

    async def insert_review_row(self, *a, **kw):
        self.calls.append(a[2:4])


class Api:
    AtomsApiDown = AtomsApiDown

    def __init__(self):
        self.posted = []

    def post_atom(self, payload):
        self.posted.append(payload)
        return 201, {"id": "a"}

    def get_by_key(self, scope, key):
        return None

    def recall(self, q, *, scope=None, k=3, consumer=None):
        return []

    def confirm_unchanged(self, inc):
        return 200, inc

    def supersede(self, *a, **kw):
        return 201, {"id": "v2"}


class Db:
    async def commit(self):
        pass


@pytest.fixture()
def disposer(monkeypatch):
    lib, rq, api = Lib(), RQ(), Api()
    monkeypatch.setattr(dispose, "curator_lib_v2", lib)
    monkeypatch.setattr(dispose, "review_queue", rq)

    async def _run(cleaned, presented):
        return await dispose.dispose_document(
            Db(), cleaned, presented, run_ref=SLOT_NOW, node_id="arac-curator",
            valid_scopes=SCOPES, api=api)
    _run.lib, _run.rq, _run.api = lib, rq, api
    return _run


# ============================ F1 ============================================
async def test_VF1_dup_via_reparation_C(flags, disposer):
    """F1 CORRIGÉ : conv réelle + jumeau corrompu(atoms=[]) -> la réparation
    est REFUSÉE (cible déjà dans le document), on retombe sur le comportement
    flag OFF : quarantaine `unknown_conversation`, aucune punition, aucun
    curseur touché."""
    flags(c=True)
    p = pres()
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(UID_A, [atom()]), conv(UID_A_CORRUPT, [])]),
            expected_run_ref=SLOT_NOW, presented=p)
    assert e.value.errors == [f"unknown_conversation:{UID_A_CORRUPT}"]
    assert e.value.attributed_uids == frozenset()
    assert disposer.lib.advances == [] and disposer.lib.failed == []


async def test_VF1_ref_le_doublon_existe_DEJA_flags_OFF(flags, disposer):
    """RÉFUTATION PARTIELLE de F1 : le doublon d'uid est un trou PRÉEXISTANT.
    Sans aucun flag, le LLM qui répète le MÊME uid deux fois obtient
    exactement le même effet (coverage_presented=2, punition d'une conv
    réussie). C n'ouvre pas un chemin nouveau : il ajoute une 2e façon
    d'atteindre un état déjà atteignable sur main."""
    flags()  # tout OFF
    p = pres()
    cleaned = contract.validate_document(
        doc([conv(UID_A, [atom()]), conv(UID_A, [])]),
        expected_run_ref=SLOT_NOW, presented=p)
    totals, _ = await disposer(cleaned, p)
    assert disposer.lib.advances == [("cid-A", 12, 1)]
    assert disposer.lib.failed == [("cid-A", "cortex_omission:atoms_empty")]
    assert totals["coverage_presented"] == 2


async def test_VF1_dup_no_new_knowledge_ne_repare_plus(flags, disposer):
    """F1 variante — FERMÉE au round 2 (finding F5). Un bloc SEUL à uid
    corrompu attestant `no_new_knowledge` n'apporte AUCUNE preuve d'avoir lu
    la conversation : la réparation est désormais REFUSÉE (condition (4)
    preuve d'appartenance) et le curseur n'est plus brûlé.
    Ce test figeait le comportement PRÉ-fix (avance du curseur) ; il fige
    maintenant sa fermeture."""
    flags(c=True)
    p = pres()
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(UID_A_CORRUPT, [], no_new_knowledge=True)]),
            expected_run_ref=SLOT_NOW, presented=p)
    assert e.value.errors == [f"unknown_conversation:{UID_A_CORRUPT}"]
    assert e.value.attributed_uids == frozenset()
    assert disposer.lib.advances == []


async def test_VF1_dup_atomes_postes_deux_fois(flags, disposer):
    """F1 CORRIGÉ (variante revue #3) : deux blocs PORTEURS d'atomes pour le
    même uid via réparation -> refusé, plus aucun double POST ni double
    avance de curseur."""
    flags(c=True)
    p = pres()
    with pytest.raises(contract.ContractError):
        contract.validate_document(
            doc([conv(UID_A, [atom(key="k1")]),
                 conv(UID_A_CORRUPT, [atom(key="k2")])]),
            expected_run_ref=SLOT_NOW, presented=p)
    assert disposer.api.posted == [] and disposer.lib.advances == []


async def test_VF1_dette_preexistante_dedup_strict_ferme_le_doublon(
        flags, disposer, monkeypatch):
    """F1 (dette PRÉEXISTANTE) — MIS À JOUR round 3 (finding N2) : le fix D
    (`ARAC_CORTEX_DEDUP_UID_STRICT`) est NEUTRALISÉ (armé, il produisait une
    quarantaine payante NON attribuable qui ne faisait bouger aucun état :
    curseurs intouchés, retry_count inchangé, pack suivant identique -> boucle
    non terminante, seulement bornée par max_spawns_per_day). La dette F1
    revient donc au comportement de `main` : doublon ACCEPTÉ, flag armé ou
    non — statu quo, aucune régression, et plus aucun trou de terminaison."""
    flags()
    monkeypatch.setenv("ARAC_CORTEX_DEDUP_UID_STRICT", "1")
    p = pres()
    cleaned = contract.validate_document(
        doc([conv(UID_A, [atom()]), conv(UID_A, [])]),
        expected_run_ref=SLOT_NOW, presented=p)
    assert len(cleaned["conversations"]) == 2
    assert contract._dedup_uid_strict_enabled() is False
    assert disposer.lib.advances == [] and disposer.lib.failed == []


# ============================ F2 ============================================
def test_VF2_attribution_transferee_sur_conv_reparee(flags):
    """F2 : atome INVALIDE porté par le bloc à uid corrompu.
    OFF -> unknown_conversation, attributed vide (aucune punition).
    ON  -> attribué à UID_A : _punish_quarantine marque la conv réelle."""
    p = pres()
    bad = doc([conv(UID_A_CORRUPT, [atom(kind="pas_un_kind")])])
    flags()
    with pytest.raises(contract.ContractError) as e_off:
        contract.validate_document(dict(bad), expected_run_ref=SLOT_NOW,
                                   presented=p)
    assert e_off.value.attributed_uids == frozenset()
    assert any(x.startswith("unknown_conversation") for x in e_off.value.errors)

    flags(c=True)
    with pytest.raises(contract.ContractError) as e_on:
        contract.validate_document(dict(bad), expected_run_ref=SLOT_NOW,
                                   presented=p)
    # F2 CORRIGÉ : un uid RÉPARÉ n'est jamais attribué -> ON == OFF.
    assert e_on.value.attributed_uids == frozenset()


# ============================ F3 ============================================
async def test_VF3_rejeu_slotkey_valide_accepte_et_avance_curseur(flags, disposer):
    """F3 : document d'un AUTRE run (slot_key grammaticalement valide),
    ids sous-ensemble du nouveau pack -> accepté ON, curseur poussé au max
    présenté (13-15 jamais lus)."""
    p = pres(a_rendered=(11, 12, 13, 14, 15), a_max=15)
    stale = doc([conv(UID_A, [atom(message_ids=[11, 12])])], run_ref=SLOT_OLD)
    flags()
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(dict(stale), expected_run_ref=SLOT_NOW,
                                   presented=p)
    assert any(x.startswith("run_ref_mismatch") for x in e.value.errors)
    flags(a=True)
    # F3 CORRIGÉ : lénience GRAMMATICALE -> un slot_key bien formé d'un AUTRE
    # run reste fatal, le rejeu n'atteint jamais le disposant.
    with pytest.raises(contract.ContractError) as e_on:
        contract.validate_document(dict(stale), expected_run_ref=SLOT_NOW,
                                   presented=p)
    assert any(x.startswith("run_ref_mismatch") for x in e_on.value.errors)
    assert disposer.lib.advances == []


def test_VF3_aucune_distinction_bruit_vs_slotkey(flags):
    """F3 CORRIGÉ : bruit/invention tolérés, slot_key d'un autre run FATAL."""
    flags(a=True)
    for declared in (None, "", "tronq", "manual_digest_2026-07-19"):
        c = contract.validate_document(
            doc([conv(UID_A, [atom()])], run_ref=declared),
            expected_run_ref=SLOT_NOW, presented=pres())
        assert c["_runref_lenient_count"] == 1
    for declared in (SLOT_OLD, "circadian_2100@2026-07-19",
                     "manual@2026-07-19T04:00"):
        with pytest.raises(contract.ContractError):
            contract.validate_document(
                doc([conv(UID_A, [atom()])], run_ref=declared),
                expected_run_ref=SLOT_NOW, presented=pres())


# ============================ F4 ============================================
def test_VF4_branche_suffixe_repare_a_distance_5(flags):
    """F4 CORRIGÉ : la branche suffixe est SUPPRIMÉE — une distance d'édition
    de 5 (les 6 premiers caractères libres) n'est plus réparée."""
    flags(c=True)
    fake = "deadbe43-0e70-4388-a7ea-51944cdfbb0b"
    assert contract._edit_distance(fake, UID_A, cutoff=10) == 5
    assert not hasattr(contract, "_common_suffix_len")
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(fake, [atom()])]), expected_run_ref=SLOT_NOW,
            presented=pres())
    assert e.value.errors == [f"unknown_conversation:{fake}"]


def test_VF4_cas_run64_passe_par_la_branche_distance(flags):
    """La branche suffixe n'est PAS nécessaire au cas réel run 64."""
    assert contract._edit_distance(UID_A_CORRUPT, UID_A, cutoff=2) == 2


# ============================ F5 ============================================
def test_VF5_extrapolation_sur_ids_vides_toleree(flags):
    """F5 : ids jamais montrés (extrapolation de bord) tolérés s'ils tombent
    sur des vides. Mais provenance nettoyée -> impact limité."""
    flags(b=True)
    p = pres(a_rendered=(11, 12), a_empty=(13, 14), a_max=14)
    cleaned = contract.validate_document(
        doc([conv(UID_A, [atom(message_ids=[11, 13, 14])])]),
        expected_run_ref=SLOT_NOW, presented=p)
    a = cleaned["conversations"][0]["atoms"][0]
    assert a["message_ids"] == [11]
    payload = policy.finalize_atom(a, node_id="n", run_ref=SLOT_NOW,
                                   conversation_uid=UID_A, source_type="x")
    assert payload["source_ref"]["message_ids"] == [11]


# ============================ R4 (PII log) ==================================
def test_VR4_runref_brut_non_borne_dans_les_logs(flags, caplog):
    """R4 : la valeur run_ref déclarée est logguée et stockée BRUTE, sans
    borne de taille ni validation de forme."""
    flags(a=True)
    poison = "compte-rendu de la conv de Jean-Michel Dupont chez ACME " + "x" * 4000
    with caplog.at_level(logging.INFO, logger="arac.cortex.contract"):
        cleaned = contract.validate_document(
            doc([conv(UID_A, [atom()])], run_ref=poison),
            expected_run_ref=SLOT_NOW, presented=pres())
    # R4 CORRIGÉ : ni la valeur brute dans journald, ni dans le document.
    assert "Jean-Michel Dupont" not in caplog.text
    assert len(caplog.text) < 1000
    assert "_runref_declared" not in cleaned
    assert cleaned["_runref_declared_sha8"] == contract._sha8(poison)


# ============================ R5 (near-miss) ================================
def test_VR5_aucun_log_de_near_miss(flags, caplog):
    """R5 CORRIGÉ : B refusé (ids non vides) et C sans candidat émettent
    chacun leur log de near-miss (matériau de calibration du soak)."""
    flags(b=True, c=True)
    with caplog.at_level(logging.INFO, logger="arac.cortex.contract"):
        with pytest.raises(contract.ContractError):
            contract.validate_document(
                doc([conv(UID_A, [atom(message_ids=[11, 999])])]),
                expected_run_ref=SLOT_NOW, presented=pres(a_empty=(90,), a_max=90))
        with pytest.raises(contract.ContractError):
            contract.validate_document(
                doc([conv("11111111-2222-3333-4444-555555555555", [atom()])]),
                expected_run_ref=SLOT_NOW, presented=pres())
    events = [json.loads(r.message) for r in caplog.records]
    kinds = {e["event"] for e in events}
    assert "cortex.contract.foreign_message_ids" in kinds
    assert "cortex.contract.unknown_conversation" in kinds
    b = next(e for e in events
             if e["event"] == "cortex.contract.foreign_message_ids")
    assert (b["reason"], b["n_outside"], b["n_outside_empty"],
            b["empty_drop_armed"]) == ("not_all_empty", 1, 0, True)
    c = next(e for e in events
             if e["event"] == "cortex.contract.unknown_conversation")
    assert c["nearmatch_armed"] is True and c["run_ref"] == SLOT_NOW
    assert c["best_distance"] is None      # aucun candidat : hors de portée


def test_VF5_ref_extrapolation_de_BORD_reste_fatale(flags):
    """RÉFUTATION F5 (1re moitié) : le mode « extrapolation au bord de tranche »
    (runs 12/20 = ids AU-DELÀ de max_id) reste FATAL sous B, car
    empty_ids ⊆ covered_ids ⊆ [cursor_from, max_id] par construction
    (pack.py:427). B ne peut tolérer QUE des trous INTERNES."""
    flags(b=True)
    p = pres(a_rendered=(11, 12), a_empty=(13,), a_max=13)
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(UID_A, [atom(message_ids=[11, 14])])]),
            expected_run_ref=SLOT_NOW, presented=p)
    assert f"foreign_message_ids:{UID_A}" in e.value.errors


def test_VF2_pack_meta_uid_est_bien_la_cle_de_punition():
    """F2 aval : _punish_quarantine indexe pack_meta par 'uid' (pack.py:475)
    = conversation_uid RÉEL -> un uid RÉPARÉ est bien punissable."""
    import inspect
    from agents.cortex import cycle
    src = inspect.getsource(cycle._punish_quarantine)
    assert 'by_uid = {m["uid"]: m for m in pack_meta}' in src
    assert "mark_curation_failed" in src
