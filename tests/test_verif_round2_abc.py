"""Vérification SCEPTIQUE round 2 — reproduction ou réfutation des findings
F5..F9 déclarés par la re-attaque adversariale.

Aucune DB, aucun réseau. Harness minimal indépendant.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path("$ARAC_HOME")
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.cortex import contract, cycle, dispose  # noqa: E402
from agents.cortex.atoms_client import AtomsApiDown  # noqa: E402

UID_A = "6e2b6143-0e70-4388-a7ea-51944cdfbb0b"
UID_A_CORRUPT = "6e2143-0e70-4388-a7ea-51944cdfbb0b"   # cas réel run 64, dist 2
UID_B = "9f41c0aa-7d15-4a62-b3ce-2210ab77e901"
SLOT = "circadian_1300@2026-07-20"
SCOPES = frozenset({"outillage", "outillage/infrastructure"})


def pres(with_b=False, fully_presented=True):
    p = {UID_A: {"conversation_id": "cid-A", "max_id": 12,
                 "message_ids": {11, 12}, "empty_ids": set(),
                 "source_type": "claude_code",
                 "fully_presented": fully_presented}}
    if with_b:
        p[UID_B] = {"conversation_id": "cid-B", "max_id": 22,
                    "message_ids": {21, 22}, "empty_ids": set(),
                    "source_type": "mac", "fully_presented": True}
    return p


def atom(**over):
    base = {"kind": "gotcha", "scope": "outillage/infrastructure", "key": "verif-cle",
            "value": "Un fait durable assez long pour passer la politique.",
            "rationale": None, "confidence_score": 90, "tags": [],
            "supersede_key_hint": None, "message_ids": [11, 12]}
    base.update(over)
    return base


def doc(convs, *, run_ref=SLOT):
    return {"contract_version": "cortex-dispose/1", "run_ref": run_ref,
            "complete": True, "audit_summary": "v", "conversations": convs}


def conv(uid, atoms=(), **over):
    c = {"conversation_uid": uid, "atoms": list(atoms), "skips": []}
    c.update(over)
    return c


@pytest.fixture()
def flags(monkeypatch):
    def _set(**kw):
        for n in ("ARAC_CORTEX_RUNREF_LENIENT", "ARAC_CORTEX_EMPTY_DROP_TOLERANT",
                  "ARAC_CORTEX_UID_NEARMATCH", "ARAC_CORTEX_DEDUP_UID_STRICT",
                  "ARAC_DISPOSE_COVERAGE_V2"):
            monkeypatch.delenv(n, raising=False)
        for n, on in kw.items():
            monkeypatch.setenv(n, "1" if on else "0")
    _set()
    return _set


class Lib:
    def __init__(self):
        self.advances, self.failed, self.parked, self.excluded = [], [], [], []
        self._retry = {}
        self._streak = {}
        self.atoms_prior = 0

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
        self._streak[cid] = self._streak.get(cid, 0) + 1
        return self._streak[cid], self._streak[cid]

    async def get_atoms_generated(self, db, cid):
        return self.atoms_prior

    async def mark_conversation_excluded(self, db, cid, *, category, reason, by):
        self.excluded.append((cid, category, reason))
        return True


class RQ:
    async def insert_review_row(self, *a, **kw):
        pass


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
    lib, api = Lib(), Api()
    monkeypatch.setattr(dispose, "curator_lib_v2", lib)
    monkeypatch.setattr(dispose, "review_queue", RQ())

    async def _run(cleaned, presented):
        return await dispose.dispose_document(
            Db(), cleaned, presented, run_ref=SLOT, node_id="arac-curator",
            valid_scopes=SCOPES, api=api)
    _run.lib, _run.api = lib, api
    return _run


# ===================== F5 (a) — brûlage de curseur : FERMÉ ==================
async def test_F5a_repair_sans_preuve_ne_brule_plus_le_curseur(flags, disposer):
    """F5(a) FERMÉ (fix round-2, condition (4) preuve d'appartenance) : bloc à
    uid CORROMPU, ZÉRO atome, `no_new_knowledge=true`. Flag C ON -> réparation
    REFUSÉE (aucun id rendu cité) -> `unknown_conversation` FATAL, curseur
    INTOUCHÉ. ON == OFF sur ce scénario."""
    for on in (True, False):
        flags(**({"ARAC_CORTEX_UID_NEARMATCH": True} if on else {}))
        p = pres()
        with pytest.raises(contract.ContractError) as e:
            contract.validate_document(
                doc([conv(UID_A_CORRUPT, [], no_new_knowledge=True)]),
                expected_run_ref=SLOT, presented=p)
        assert e.value.errors == [f"unknown_conversation:{UID_A_CORRUPT}"]
        assert e.value.attributed_uids == frozenset()
    assert disposer.lib.advances == [] and disposer.api.posted == []


async def test_F5a_symetrie_retablie_avec_B(flags):
    """F5 asymétrie FERMÉE : B exige >= 1 id réellement rendu (`kept`) et C
    exige désormais >= 1 id réellement rendu CITÉ par le bloc. Aucun correctif
    de fidélité ne dispose d'une conversation sans preuve matérielle."""
    # B : atome dont TOUTE la provenance est vide -> FATAL même flag ON
    flags(ARAC_CORTEX_EMPTY_DROP_TOLERANT=True)
    p = pres()
    p[UID_A]["empty_ids"] = {8, 9}
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(UID_A, [atom(message_ids=[8, 9])])]),
            expected_run_ref=SLOT, presented=p)
    assert e.value.errors == [f"foreign_message_ids:{UID_A}"]

    # C : bloc SANS aucune preuve (0 atome) -> réparation REFUSÉE
    flags(ARAC_CORTEX_UID_NEARMATCH=True)
    with pytest.raises(contract.ContractError) as e2:
        contract.validate_document(
            doc([conv(UID_A_CORRUPT, [], no_new_knowledge=True)]),
            expected_run_ref=SLOT, presented=pres())
    assert e2.value.errors == [f"unknown_conversation:{UID_A_CORRUPT}"]

    # ... et un bloc AVEC preuve (>= 1 id rendu cité) est toujours réparé :
    # la fermeture est un resserrement, pas une désactivation de C.
    cleaned = contract.validate_document(
        doc([conv(UID_A_CORRUPT, [atom(message_ids=[11, 12])])]),
        expected_run_ref=SLOT, presented=pres())
    assert cleaned["_uid_nearmatch_count"] == 1


# ================ F5 (b) — punition de l'innocente : FERMÉ ==================
async def test_F5b_repair_atoms_vides_ne_punit_plus(flags, disposer):
    """F5(b) FERMÉ : même bloc SANS `no_new_knowledge` -> réparation refusée ->
    quarantaine NON attribuée, `mark_curation_failed` JAMAIS appelé. ON == OFF."""
    flags(ARAC_CORTEX_UID_NEARMATCH=True)
    p = pres()
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(UID_A_CORRUPT, [])]), expected_run_ref=SLOT, presented=p)
    assert e.value.attributed_uids == frozenset()
    assert disposer.lib.failed == [] and disposer.lib.advances == []


async def test_F5b_plus_aucun_park_possible(flags, disposer):
    """F5(b) suite FERMÉE : 3 runs de suite ne parkent plus rien — aucun bloc
    sans preuve n'atteint jamais le disposant."""
    flags(ARAC_CORTEX_UID_NEARMATCH=True)
    p = pres()
    for _ in range(3):
        with pytest.raises(contract.ContractError):
            contract.validate_document(
                doc([conv(UID_A_CORRUPT, [])]), expected_run_ref=SLOT,
                presented=p)
    assert disposer.lib.parked == [] and disposer.lib.failed == []


async def test_F5b_coverage_v2_ON_nexclut_plus_la_conversation(flags, disposer):
    """AGGRAVATION FERMÉE : avec `ARAC_DISPOSE_COVERAGE_V2` ON (armé en PROD),
    3 blocs sans preuve n'excluent plus la conversation réelle — ils
    n'atteignent plus le disposant du tout."""
    flags(ARAC_CORTEX_UID_NEARMATCH=True, ARAC_DISPOSE_COVERAGE_V2=True)
    p = pres()
    for _ in range(3):
        with pytest.raises(contract.ContractError):
            contract.validate_document(
                doc([conv(UID_A_CORRUPT, [])]), expected_run_ref=SLOT,
                presented=p)
    assert disposer.lib.excluded == [] and disposer.lib.advances == []


async def test_F5_ref_faux_positif_impossible_entre_deux_convs_reelles(flags):
    """RÉFUTATION PARTIELLE de F5 : la prémisse « conversation INNOCENTE »
    exige une réparation FAUSSE. Sur des uids RÉELS (distance >= 21 mesurée),
    une corruption <= 2 caractères de A ne peut jamais matcher B, et un uid
    à distance <= 2 de B ne peut jamais matcher A : le pire cas est
    l'ambiguïté, qui est FATALE."""
    from agents.cortex.contract import _edit_distance, _nearmatch_uid
    assert _edit_distance(UID_A, UID_B, cutoff=8) > 2
    # corruption de A -> ne matche QUE A
    rep, cands = _nearmatch_uid(UID_A_CORRUPT, [UID_A, UID_B])
    assert (rep, cands) == (UID_A, [UID_A])
    # uid inventé équidistant -> ambigu -> aucune réparation
    rep2, cands2 = _nearmatch_uid(UID_A[:-1] + "a", [UID_A, UID_A[:-2] + "ee"])
    assert rep2 is None and len(cands2) == 2


# ===================== F6 — flag D punit l'innocente ========================
async def test_F6_duplicate_uid_nest_plus_attribue(flags, disposer):
    """F6 FERMÉ — MIS À JOUR round 3 (finding N2) : le fix D est NEUTRALISÉ
    (quarantaine payante non attribuable qui ne faisait bouger aucun état).
    Plus de quarantaine du tout sur un doublon PUR : la propriété F6 « aucune
    punition d'une conversation productive » est tenue a fortiori."""
    flags(ARAC_CORTEX_DEDUP_UID_STRICT=True)
    p = pres()
    cleaned = contract.validate_document(
        doc([conv(UID_A, [atom()]), conv(UID_A, [atom()])]),
        expected_run_ref=SLOT, presented=p)
    assert len(cleaned["conversations"]) == 2

    punished = await cycle._punish_quarantine(
        None, [], [{"uid": UID_A, "conversation_id": "cid-A"}], slot_key=SLOT)
    assert punished == [] and disposer.lib.failed == []


async def test_F6_doublon_avec_vraie_violation_reste_attribue(flags):
    """F6, contre-épreuve : le décompte du doublon ne blanchit RIEN. Un bloc
    dupliqué qui porte EN PLUS une vraie violation (ids étrangers) reste
    attribué — le guard d'attribution n'est pas affaibli, il est précisé."""
    flags(ARAC_CORTEX_DEDUP_UID_STRICT=True)
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(UID_A, [atom()]),
                 conv(UID_A, [atom(message_ids=[999])])]),
            expected_run_ref=SLOT, presented=pres())
    # MIS À JOUR round 3 (N2, D neutralisé) : plus d'erreur de doublon, mais
    # le guard anti-poison est INTACT — la vraie violation reste fatale ET
    # attribuée.
    assert e.value.errors == [f"foreign_message_ids:{UID_A}"]
    assert e.value.attributed_uids == frozenset({UID_A})


async def test_F6_doctrine_C_coherente(flags):
    """F6 contraste RÉSOLU : uid réparé portant une violation -> non attribué ;
    uid dupliqué -> non attribué non plus. Même doctrine C1 dans le fichier."""
    flags(ARAC_CORTEX_UID_NEARMATCH=True)
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(UID_A_CORRUPT, [atom(message_ids=[11, 999])])]),
            expected_run_ref=SLOT, presented=pres())
    assert e.value.errors == [f"foreign_message_ids:{UID_A}"]
    assert e.value.attributed_uids == frozenset()   # réparé -> non puni


# ===================== F7 — flag non observé : FERMÉ ========================
def test_F7_coverage_v2_est_observe():
    """F7 FERMÉ : `ARAC_DISPOSE_COVERAGE_V2` (booléen, lu par dispose.py,
    ARMÉ EN PROD) est désormais dans `_OBSERVED_FLAGS` -> « armé sans effet »
    et « jamais armé » deviennent distinguables dans journald."""
    assert "ARAC_DISPOSE_COVERAGE_V2" in cycle._OBSERVED_FLAGS
    assert hasattr(dispose, "_coverage_v2_enabled")


# ===================== F8 — lecteur de `progress` ===========================
def test_F8_progress_a_bien_un_lecteur():
    """F8 : la justification C4 (« aucun lecteur existant de cette colonne »)
    est FACTUELLEMENT FAUSSE — le cockpit lit `progress`."""
    from control_center.sql import perception_queries as pq
    assert "progress" in pq.RUNS_OPEN_SQL
    # ... mais le lecteur filtre sur des statuts où `_fidelity` n'existe pas
    assert "'done'" not in pq.RUNS_OPEN_SQL
    assert "started" in pq.RUNS_OPEN_SQL


def test_F8_meta_cles_filtrees_explicitement():
    """F8 (2e volet) FERMÉ : `_coverage_signals` filtre EXPLICITEMENT les
    méta-clés réservées (préfixe `_`) et les entrées non-dict — le filtrage ne
    repose plus sur la coïncidence « ces valeurs ne portent pas les clés lues ».
    Contre-épreuve : même une méta-clé portant `parked`/`excluded`/`drained`
    (forme piège) reste inerte, et une valeur non-dict ne crash pas."""
    progress = {UID_A: {"parked": True},
                "_fidelity": {"parked": True, "excluded": True, "drained": True},
                "_note": "texte"}
    sigs = cycle._coverage_signals(progress, SLOT)
    assert [s[2] for s in sigs] == [[UID_A]]


# ===================== F9 — bornage incohérent ==============================
def test_F9_chemin_OFF_non_borne_est_le_comportement_de_main(flags):
    """F9 : le chemin OFF émet bien la valeur BRUTE non bornée... mais c'est
    EXACTEMENT le code de `main` (exigence dure « flags OFF = bit-identique »).
    Le borner casserait la bit-identité. RÉFUTÉ comme défaut du chantier."""
    flags()
    payload = "X" * 5000
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(doc([], run_ref=payload),
                                   expected_run_ref=SLOT, presented=pres())
    assert any(len(err) > 4000 for err in e.value.errors)   # non borné, = main

    # flag A ON : la valeur brute ne sort JAMAIS (tolérée -> sha8 ;
    # bien-formée-autre-run -> sha8)
    flags(ARAC_CORTEX_RUNREF_LENIENT=True)
    cleaned = contract.validate_document(doc([], run_ref=payload),
                                         expected_run_ref=SLOT, presented={})
    assert cleaned["run_ref"] == SLOT and "_runref_declared_sha8" in cleaned
    with pytest.raises(contract.ContractError) as e2:
        contract.validate_document(doc([], run_ref="circadian_0400@2026-07-19"),
                                   expected_run_ref=SLOT, presented=pres())
    assert e2.value.errors == [
        f"run_ref_mismatch:sha8={contract._sha8('circadian_0400@2026-07-19')}"]


async def test_F6_delta_exact_du_flag_D(flags, disposer):
    """F6, delta EXACT — MIS À JOUR round 3 (finding N2) : le flag D est
    NEUTRALISÉ, son delta est donc VIDE. Deux blocs porteurs d'atomes pour le
    même uid : flag armé ou non, le document est accepté et le disposant fait
    exactement la même chose (dette F1 préexistante, comportement de `main`).
    Rationnel du désarmement : armé, D produisait une quarantaine payante NON
    attribuable ne faisant bouger AUCUN état (trou de terminaison)."""
    flags()  # D OFF
    p = pres()
    cleaned = contract.validate_document(
        doc([conv(UID_A, [atom()]), conv(UID_A, [atom(key="autre-cle")])]),
        expected_run_ref=SLOT, presented=p)
    await disposer(cleaned, p)
    assert disposer.lib.advances == [("cid-A", 12, 1), ("cid-A", 12, 1)]
    assert disposer.lib.failed == []           # aucune punition flag OFF

    flags(ARAC_CORTEX_DEDUP_UID_STRICT=True)
    cleaned_on = contract.validate_document(
        doc([conv(UID_A, [atom()]), conv(UID_A, [atom(key="autre-cle")])]),
        expected_run_ref=SLOT, presented=pres())
    assert cleaned_on == cleaned                    # delta EXACT = zéro


# ============ NOUVEAU (round 2, vérification) — la justification de C ========
# Matériau PROD (SSH lecture seule, 2026-07-20) : `arac.run_receipts` id=64,
# bloc à uid corrompu `6e2143-…`. Ses 3 atomes citent 8 `message_ids`, dont
# 897983 qui N'EXISTE PAS dans `arac.raw_messages` (vérifié : count=0 ; les ids
# voisins réels sont 897990..898000). Il ne peut donc être dans AUCUN pack.
RUN64_ATOM_IDS = {
    "ville-test-2": [883558, 883560, 992534],
    "dice": [891603, 893844, 895263],
    "culture": [897983, 897991],        # 897983 = id INEXISTANT en prod
}
RUN64_REAL_IDS = {883558, 883560, 992534, 891603, 893844, 895263, 897991}


async def test_NEW_C_ne_sauve_PAS_le_run_64(flags, disposer):
    """RÉFUTATION de la justification centrale de FIX C (« aurait sauvé le
    run 64 »). Pack le PLUS FAVORABLE possible (tous les ids RÉELS cités
    présentés). Flag C ON : l'uid est bien réparé, puis `foreign_message_ids`
    s'applique NORMALEMENT sur la conv réparée et l'atome `culture` citant
    l'id INEXISTANT 897983 rend le document FATAL. Le run 64 reste
    QUARANTAINÉ, 0 atome — seule l'étiquette d'erreur change."""
    p = {UID_A: {"conversation_id": "cid-A", "max_id": max(RUN64_REAL_IDS),
                 "message_ids": set(RUN64_REAL_IDS), "empty_ids": set(),
                 "source_type": "claude_code", "fully_presented": True}}
    atoms = [atom(key=f"cle-{k}", message_ids=list(v))
             for k, v in RUN64_ATOM_IDS.items()]

    flags(ARAC_CORTEX_UID_NEARMATCH=True)
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(doc([conv(UID_A_CORRUPT, atoms)]),
                                   expected_run_ref=SLOT, presented=p)
    assert e.value.errors == [f"foreign_message_ids:{UID_A}"]
    assert e.value.attributed_uids == frozenset()   # réparé -> non attribué

    # B en renfort ne change RIEN : 897983 n'existe pas, donc n'est dans
    # aucun `empty_ids` possible.
    flags(ARAC_CORTEX_UID_NEARMATCH=True, ARAC_CORTEX_EMPTY_DROP_TOLERANT=True)
    with pytest.raises(contract.ContractError) as e2:
        contract.validate_document(doc([conv(UID_A_CORRUPT, atoms)]),
                                   expected_run_ref=SLOT, presented=p)
    assert e2.value.errors == [f"foreign_message_ids:{UID_A}"]

    # Flag OFF : l'erreur est AUTRE (l'atome fautif n'est même pas inspecté,
    # `pack_entry is None`) — c'est exactement ce que montre le reçu 64.
    flags()
    with pytest.raises(contract.ContractError) as e3:
        contract.validate_document(doc([conv(UID_A_CORRUPT, atoms)]),
                                   expected_run_ref=SLOT, presented=p)
    assert e3.value.errors == [f"unknown_conversation:{UID_A_CORRUPT}"]


async def test_NEW_C_seul_sauverait_le_run_64_SI_les_ids_etaient_reels(flags):
    """Contrôle : sans l'id inexistant, C sauve bien le run. Le blocage vient
    donc UNIQUEMENT du 5e mode (id de message halluciné), non couvert par
    A/B/C."""
    p = {UID_A: {"conversation_id": "cid-A", "max_id": max(RUN64_REAL_IDS),
                 "message_ids": set(RUN64_REAL_IDS), "empty_ids": set(),
                 "source_type": "claude_code", "fully_presented": True}}
    atoms = [atom(key=f"cle-{k}", message_ids=[i for i in v if i != 897983])
             for k, v in RUN64_ATOM_IDS.items()]
    flags(ARAC_CORTEX_UID_NEARMATCH=True)
    cleaned = contract.validate_document(doc([conv(UID_A_CORRUPT, atoms)]),
                                         expected_run_ref=SLOT, presented=p)
    assert cleaned["_uid_nearmatch_count"] == 1
    assert len(cleaned["conversations"][0]["atoms"]) == 3
