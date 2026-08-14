"""RED TEAM du chantier fidélité A+B+C — mandat : EMPOISONNER la mémoire.

Chaque test encode une ATTAQUE concrète (flags ON) et prouve soit qu'elle
RÉUSSIT (= faille à corriger), soit qu'elle ÉCHOUE (= garantie prouvée).
Hermétique : zéro réseau, zéro DB, zéro spawn.

Nomenclature :
  ATK-x-N  : scénario d'attaque
  GAR-x-N  : garantie (l'attaque est prouvée impossible)
"""

from __future__ import annotations

import itertools
import sys
import uuid
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.cortex import contract, dispose, policy  # noqa: E402
from agents.cortex.atoms_client import AtomsApiDown  # noqa: E402

# --- univers de test ---------------------------------------------------------
UID_A = "6e2b6143-0e70-4388-a7ea-51944cdfbb0b"   # cas réel run 64
UID_B = "9f41c0aa-7d15-4a62-b3ce-2210ab77e901"   # autre conv du pack
UID_ABSENT = "1c9d55e2-4b80-49f7-8a10-77cc3ee1d442"  # réelle en DB, HORS pack

SLOT_NOW = "circadian_1300@2026-07-20"
SLOT_OLD = "circadian_0400@2026-07-20"           # slot_key COHÉRENT d'un AUTRE run

SCOPES = frozenset({"outillage", "outillage/infrastructure", "travail/operations"})


def presented(*, a_rendered=(11, 12), a_empty=(), a_max=12,
              b_rendered=(21, 22), b_empty=(), b_max=22, with_b=True):
    p = {UID_A: {"conversation_id": "cid-A", "max_id": a_max,
                 "message_ids": set(a_rendered), "empty_ids": set(a_empty),
                 "source_type": "claude_code", "fully_presented": True}}
    if with_b:
        p[UID_B] = {"conversation_id": "cid-B", "max_id": b_max,
                    "message_ids": set(b_rendered), "empty_ids": set(b_empty),
                    "source_type": "mac", "fully_presented": True}
    return p


def atom(**over):
    base = {"kind": "gotcha", "scope": "outillage/infrastructure", "key": "red-team-cle",
            "value": "Un fait durable assez long pour passer la politique.",
            "rationale": None, "confidence_score": 90, "tags": [],
            "supersede_key_hint": None, "message_ids": [11, 12]}
    base.update(over)
    return base


def doc(convs, *, run_ref=SLOT_NOW):
    return {"contract_version": "cortex-dispose/1", "run_ref": run_ref,
            "complete": True, "audit_summary": "rt",
            "conversations": convs}


def conv(uid, atoms=(), **over):
    c = {"conversation_uid": uid, "atoms": list(atoms), "skips": []}
    c.update(over)
    return c


@pytest.fixture()
def flags(monkeypatch):
    """Arme/désarme les 3 flags — env PUR, relu à chaque appel."""
    def _set(a=False, b=False, c=False):
        for name, on in (("ARAC_CORTEX_RUNREF_LENIENT", a),
                         ("ARAC_CORTEX_EMPTY_DROP_TOLERANT", b),
                         ("ARAC_CORTEX_UID_NEARMATCH", c)):
            monkeypatch.setenv(name, "1" if on else "0")
    _set()
    return _set


# --- fakes disposant (miroir hermétique de curator_lib_v2 / review_queue) -----
class FakeCursorLib:
    def __init__(self):
        self.advances = []
        self.mark_failed_calls = []
        self.parked = []
        self.excluded = []
        self._retry: dict[str, int] = {}

    async def advance_cursor(self, db, cid, new_cursor, *, atoms_generated):
        self.advances.append((cid, new_cursor, atoms_generated))
        self._retry[cid] = 0

    async def mark_curation_failed(self, db, cid, *, error):
        self.mark_failed_calls.append((cid, error))
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
        self.excluded.append((cid, category, reason))
        return True


class FakeReviewQueue:
    def __init__(self):
        self.calls = []

    async def insert_review_row(self, conn, run_ref, uid, drop_reason,
                                proposed_atom, incumbent_id, scope, kind):
        self.calls.append((uid, drop_reason))


class FakeApi:
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


class FakeDb:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


@pytest.fixture()
def disposer(monkeypatch):
    lib, rq, api = FakeCursorLib(), FakeReviewQueue(), FakeApi()
    monkeypatch.setattr(dispose, "curator_lib_v2", lib)
    monkeypatch.setattr(dispose, "review_queue", rq)

    async def _run(cleaned_doc, pres):
        db = FakeDb()
        totals, progress = await dispose.dispose_document(
            db, cleaned_doc, pres, run_ref=SLOT_NOW, node_id="arac-curator",
            valid_scopes=SCOPES, api=api)
        return totals, progress

    _run.lib, _run.rq, _run.api = lib, rq, api
    return _run


# =============================================================================
# ATTAQUES SUR A — ARAC_CORTEX_RUNREF_LENIENT
# =============================================================================

def test_gar_a1_replay_dune_reponse_dun_AUTRE_run_reste_fatal(flags):
    """GAR-A-1 (ex ATK-A-1, FERMÉE au fix round-1) — REJEU. Le corpus curé
    CONTIENT des packs cortex antérieurs et leurs réponses JSON (self-capture,
    cf pack.py:340-346 ; matériau vérifié en prod le 2026-07-20 : 12 messages
    sur 3 conversations non curées portent un slot_key passé). Si le LLM
    recopie la réponse d'un run PRÉCÉDENT, `run_ref` est le SEUL champ qui
    distingue « réponse à CE prompt » de « réponse recopiée ».
    La lénience est désormais GRAMMATICALE : un `run_ref` BIEN FORMÉ (grammaire
    slot_key serveur) et différent de l'attendu reste FATAL, flag ON compris."""
    pres = presented(a_rendered=(11, 12, 13, 14, 15), a_max=15, with_b=False)
    stale = doc([conv(UID_A, [atom(message_ids=[11, 12])])], run_ref=SLOT_OLD)

    flags(a=False)
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(dict(stale), expected_run_ref=SLOT_NOW,
                                   presented=pres)
    assert any(x.startswith("run_ref_mismatch") for x in e.value.errors)

    flags(a=True)  # ATTAQUE FERMÉE : toujours fatal
    with pytest.raises(contract.ContractError) as on:
        contract.validate_document(dict(stale), expected_run_ref=SLOT_NOW,
                                   presented=pres)
    assert any(x.startswith("run_ref_mismatch") for x in on.value.errors)


async def test_gar_a1b_le_rejeu_ne_peut_plus_avancer_le_curseur(flags, disposer):
    """GAR-A-1b — conséquence : le document de rejeu n'atteint plus JAMAIS le
    disposant, donc plus aucune avance de curseur sur des messages non lus."""
    flags(a=True)
    pres = presented(a_rendered=(11, 12, 13, 14, 15), a_max=15, with_b=False)
    with pytest.raises(contract.ContractError):
        contract.validate_document(
            doc([conv(UID_A, [atom(message_ids=[11, 12])])], run_ref=SLOT_OLD),
            expected_run_ref=SLOT_NOW, presented=pres)
    assert disposer.lib.advances == []


def test_gar_a2_le_runref_serveur_ecrase_toujours_le_declare(flags):
    """GAR-A-2 — aucune valeur hallucinée ne peut fuir en aval : le document
    nettoyé porte le slot_key SERVEUR, et seule l'EMPREINTE de la valeur
    déclarée est conservée (fix round-1 R4 : la valeur brute, non bornée et
    potentiellement porteuse de PII, ne survit ni dans le document ni dans
    journald). Le stdout BRUT reste archivé dans le reçu AVANT tout parsing
    (cycle.py:460-462) : A ne détruit aucune trace forensique."""
    flags(a=True)
    declared = "digest_du_2026-07-19"          # NON conforme à la grammaire
    cleaned = contract.validate_document(
        doc([conv(UID_A, [atom()])], run_ref=declared),
        expected_run_ref=SLOT_NOW, presented=presented(with_b=False))
    assert cleaned["run_ref"] == SLOT_NOW
    assert "_runref_declared" not in cleaned
    assert cleaned["_runref_declared_sha8"] == contract._sha8(declared)
    assert cleaned["_runref_lenient_count"] == 1


def test_gar_a3_lenience_distingue_bruit_et_autre_slot_valide(flags):
    """GAR-A-3 (ex ATK-A-3) — la lénience n'est PLUS totale : un `run_ref`
    absent/inventé (bénin, cas run 59 `manual_digest_2026-07-19`) est toléré,
    un slot_key COHÉRENT d'un autre run (preuve de rejeu) reste FATAL."""
    flags(a=True)
    for declared in (None, "", "run-42", "manual_digest_2026-07-19"):
        cleaned = contract.validate_document(
            doc([conv(UID_A, [atom()])], run_ref=declared),
            expected_run_ref=SLOT_NOW, presented=presented(with_b=False))
        assert cleaned["_runref_lenient_count"] == 1
    for declared in (SLOT_OLD, "circadian_2100@2026-07-19",
                     "manual@2026-07-19T04:00"):
        with pytest.raises(contract.ContractError) as e:
            contract.validate_document(
                doc([conv(UID_A, [atom()])], run_ref=declared),
                expected_run_ref=SLOT_NOW, presented=presented(with_b=False))
        assert any(x.startswith("run_ref_mismatch") for x in e.value.errors)
        # la valeur brute ne part JAMAIS dans l'erreur sous flag (R4)
        assert all(declared not in x for x in e.value.errors)


# =============================================================================
# ATTAQUES SUR B — ARAC_CORTEX_EMPTY_DROP_TOLERANT
# =============================================================================

def test_gar_b1_cheval_de_troie_la_provenance_reste_un_sous_ensemble_du_rendu(
        flags):
    """GAR-B-1 — cheval de Troie : l'atome cite 1 id rendu + 3 ids VIDES.
    Après tolérance, la provenance gravée dans `source_ref` (policy.py:119) ne
    contient QUE l'id réellement rendu : jamais un id vide n'est cité comme
    source. La provenance est donc HONNÊTE (sous-ensemble strict du rendu)."""
    flags(b=True)
    pres = presented(a_rendered=(11, 12), a_empty=(90, 91, 92), a_max=92,
                     with_b=False)
    cleaned = contract.validate_document(
        doc([conv(UID_A, [atom(message_ids=[11, 90, 91, 92])])]),
        expected_run_ref=SLOT_NOW, presented=pres)
    a = cleaned["conversations"][0]["atoms"][0]
    assert a["message_ids"] == [11]
    payload = policy.finalize_atom(a, node_id="n", run_ref=SLOT_NOW,
                                   conversation_uid=UID_A, source_type="x")
    assert payload["source_ref"]["message_ids"] == [11]
    assert cleaned["_empty_ids_tolerated"] == [90, 91, 92]


def test_gar_b2_id_vide_dune_AUTRE_conversation_reste_fatal(flags):
    """GAR-B-2 — le filet anti-poison inter-conversations tient : conv A cite un
    id VIDE de conv B -> `empty_ids` consulté est celui de A -> FATAL."""
    flags(b=True)
    pres = presented(a_rendered=(11, 12), a_empty=(90,), a_max=90,
                     b_rendered=(21, 22), b_empty=(95,), b_max=95)
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(UID_A, [atom(message_ids=[11, 95])])]),
            expected_run_ref=SLOT_NOW, presented=pres)
    assert f"foreign_message_ids:{UID_A}" in e.value.errors


def test_gar_b3_provenance_100pct_vide_reste_fatale(flags):
    """GAR-B-3 — un atome dont TOUTE la provenance est vide ne prouve rien."""
    flags(b=True)
    pres = presented(a_rendered=(11, 12), a_empty=(90, 91), a_max=91,
                     with_b=False)
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(UID_A, [atom(message_ids=[90, 91])])]),
            expected_run_ref=SLOT_NOW, presented=pres)
    assert f"foreign_message_ids:{UID_A}" in e.value.errors


def test_gar_b4_id_hors_plage_reste_fatal_meme_melange_a_des_vides(flags):
    """GAR-B-4 — tolérance TOUT-OU-RIEN : un seul id hors-plage (jamais couvert)
    dans le lot et l'atome entier redevient FATAL."""
    flags(b=True)
    pres = presented(a_rendered=(11, 12), a_empty=(90,), a_max=90,
                     with_b=False)
    with pytest.raises(contract.ContractError):
        contract.validate_document(
            doc([conv(UID_A, [atom(message_ids=[11, 90, 999999])])]),
            expected_run_ref=SLOT_NOW, presented=pres)


def test_gar_b5_sans_drop_empty_le_flag_est_inerte(flags):
    """GAR-B-5 — `empty_ids` vide (ARAC_PACK_DROP_EMPTY OFF côté pack) =>
    B est structurellement inopérant, aucun passe-droit."""
    flags(b=True)
    pres = presented(a_rendered=(11, 12), a_empty=(), a_max=12, with_b=False)
    with pytest.raises(contract.ContractError):
        contract.validate_document(
            doc([conv(UID_A, [atom(message_ids=[11, 13])])]),
            expected_run_ref=SLOT_NOW, presented=pres)


def test_atk_b6_le_detecteur_dextrapolation_did_est_neutralise(flags):
    """ATK-B-6 — B supprime un DÉTECTEUR. Citer un id jamais montré est le mode
    « extrapolation d'id au bord de tranche » documenté (pack.py:340-342). Si
    les ids extrapolés tombent par chance sur des vides, l'atome passe — alors
    que le signal « ce LLM invente des ids » (donc potentiellement AUSSI ceux
    qu'il garde) est avéré. Ici 2 ids réels + 4 ids extrapolés consécutifs."""
    flags(b=True)
    pres = presented(a_rendered=(11, 12), a_empty=(13, 14, 15, 16), a_max=16,
                     with_b=False)
    cleaned = contract.validate_document(
        doc([conv(UID_A, [atom(message_ids=[11, 12, 13, 14, 15, 16])])]),
        expected_run_ref=SLOT_NOW, presented=pres)
    assert cleaned["conversations"][0]["atoms"][0]["message_ids"] == [11, 12]
    # ... et le compteur de tolérance n'est lu par AUCUN consommateur aval
    # (grep : `_empty_ids_tolerated*` n'existe que dans contract.py + tests) :
    # le signal n'atterrit ni dans run_receipts ni dans digestion_review_queue.
    assert cleaned["_empty_ids_tolerated_count"] == 4


# =============================================================================
# ATTAQUES SUR C — ARAC_CORTEX_UID_NEARMATCH
# =============================================================================

def test_gar_c1_jumeau_fantome_ne_cree_plus_de_doublon(flags):
    """GAR-C-1 (ex ATK-C-1, FERMÉE) — JUMEAU FANTÔME. Le LLM émet la conv
    RÉELLE (avec atomes) PUIS une entrée dont l'uid est une corruption de la
    MÊME conv (mode « uid répété DEBUT+FIN », runs 11/38/51/52). La réparation
    est désormais REFUSÉE quand sa cible est DÉJÀ présente dans le document
    (`dispose.py:573` ne déduplique pas) : on retombe sur le comportement flag
    OFF — `unknown_conversation`, quarantaine, AUCUNE punition."""
    pres = presented(with_b=False)
    d = doc([conv(UID_A, [atom()]),
             conv("6e2143-0e70-4388-a7ea-51944cdfbb0b", [])])  # -2 caractères

    for armed in (False, True):
        flags(c=armed)
        with pytest.raises(contract.ContractError) as e:
            contract.validate_document(dict(d), expected_run_ref=SLOT_NOW,
                                       presented=pres)
        assert any(x.startswith("unknown_conversation") for x in e.value.errors)
        assert e.value.attributed_uids == frozenset()  # personne n'est puni


async def test_gar_c1b_le_jumeau_fantome_ne_punit_plus_une_conv_SAINE(
        flags, disposer):
    """GAR-C-1b — conséquence MESURÉE : le document n'atteint plus le
    disposant, donc ni double avance de curseur ni `mark_curation_failed` sur
    une conversation qui vient de RÉUSSIR (attaque fermée)."""
    flags(c=True)
    pres = presented(with_b=False)
    with pytest.raises(contract.ContractError):
        contract.validate_document(
            doc([conv(UID_A, [atom()]),
                 conv("6e2143-0e70-4388-a7ea-51944cdfbb0b", [])]),
            expected_run_ref=SLOT_NOW, presented=pres)
    assert disposer.lib.advances == []
    assert disposer.lib.mark_failed_calls == []


async def test_atk_c1c_jumeau_fantome_no_new_knowledge_FERMEE(
        flags, disposer):
    """ATK-C-1c — FERMÉE au round 2 (finding F5). Le jumeau fantôme atteste
    `no_new_knowledge` alors que la conv réelle est ABSENTE du document : sans
    aucun id rendu cité, la réparation est REFUSÉE (preuve d'appartenance) et
    le curseur n'avance PAS. ON == OFF sur ce scénario."""
    pres = presented(with_b=False)
    for armed in (False, True):
        flags(c=armed)
        with pytest.raises(contract.ContractError) as e:
            contract.validate_document(
                doc([conv("6e2143-0e70-4388-a7ea-51944cdfbb0b", [],
                          no_new_knowledge=True)]),
                expected_run_ref=SLOT_NOW, presented=pres)
        assert e.value.errors == [
            "unknown_conversation:6e2143-0e70-4388-a7ea-51944cdfbb0b"]
    assert disposer.lib.advances == []


def test_gar_c2_attribution_jamais_deplacee_sur_une_conv_innocente(flags):
    """GAR-C-2 (ex ATK-C-2, FERMÉE) — ATTRIBUTION. Une conv fantôme portant un
    atome invalide est, flag OFF, une erreur NON ATTRIBUABLE (personne n'est
    puni, cycle.py:492). Un uid RÉPARÉ n'entre plus dans `attributed_uids` :
    ON == OFF sur l'attribution, la conversation réelle n'est jamais punie
    pour un bloc dont le LLM a corrompu l'identifiant."""
    pres = presented(with_b=False)
    bad = doc([conv("6e2143-0e70-4388-a7ea-51944cdfbb0b",
                    [atom(kind="banane")])])

    for armed in (False, True):
        flags(c=armed)
        with pytest.raises(contract.ContractError) as e:
            contract.validate_document(dict(bad), expected_run_ref=SLOT_NOW,
                                       presented=pres)
        assert e.value.attributed_uids == frozenset(), armed


def test_gar_c3_branche_suffixe_supprimee(flags):
    """GAR-C-3 (ex ATK-C-3, FERMÉE) — la seconde porte (`suffixe commun >= 30`)
    laissait les 6 PREMIERS caractères d'un uuid totalement libres (réparation
    à distance d'édition 5, 2,5x le seuil documenté) alors que le cas cible
    (run 64) passe par la branche distance (2). Elle est SUPPRIMÉE."""
    flags(c=True)
    forged = "deadbe" + UID_A[6:]          # 6 caractères arbitraires en tête
    assert contract._edit_distance(forged, UID_A, cutoff=9) == 5
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(forged, [atom()])]),
            expected_run_ref=SLOT_NOW, presented=presented(with_b=False))
    assert e.value.errors == [f"unknown_conversation:{forged}"]
    assert not hasattr(contract, "_UID_MIN_COMMON_SUFFIX")


def test_gar_c4_deux_uuid_reels_ne_peuvent_jamais_se_confondre():
    """GAR-C-4 — mesure indépendante (population synthétique uuid4, même loi que
    les 245 uids réels vérifiés en prod le 2026-07-20 : distance min >= 9,
    suffixe commun max = 3) : aucune paire d'uids réels ne passe les seuils
    (2 / 30). Une réparation ne peut donc JAMAIS repointer vers la mauvaise
    conversation réelle par simple proximité."""
    pop = [str(uuid.uuid4()) for _ in range(400)]
    for a, b in itertools.combinations(pop, 2):
        assert contract._edit_distance(a, b, cutoff=2) > 2


def test_gar_c5_famille_duids_ambigus_reste_fatale(flags):
    """GAR-C-5 — si un générateur d'uid FUTUR produisait des uids d'une même
    famille (suffixe partagé), l'exigence d'UNICITÉ tient : >= 2 candidats ->
    aucune réparation, l'erreur fatale d'origine est émise."""
    flags(c=True)
    fam1 = "aaaaaa11-0e70-4388-a7ea-51944cdfbb0b"
    fam2 = "bbbbbb22-0e70-4388-a7ea-51944cdfbb0b"
    pres = {u: {"conversation_id": u, "max_id": 12, "message_ids": {11, 12},
                "empty_ids": set(), "source_type": "x", "fully_presented": True}
            for u in (fam1, fam2)}
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv("cccccc33-0e70-4388-a7ea-51944cdfbb0b", [atom()])]),
            expected_run_ref=SLOT_NOW, presented=pres)
    assert any(x.startswith("unknown_conversation") for x in e.value.errors)
    assert e.value.attributed_uids == frozenset()


def test_gar_c6_apres_reparation_le_filet_anti_poison_reste_arme(flags):
    """GAR-C-6 — scénario « uid lu ailleurs » : le LLM cite un uid vu DANS le
    contenu d'une conversation self-capture (pack antérieur) et des ids de CE
    pack-là. Même si la réparation aboutissait, les ids ne sont pas ceux de la
    conv réparée -> FATAL. L'anti-poison prime. Fix round-2 (F5) : le rejet
    intervient encore plus tôt — aucun id rendu de la conv cible n'étant cité,
    la réparation elle-même est refusée (`unknown_conversation`)."""
    flags(c=True)
    pres = presented()
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv("6e2143-0e70-4388-a7ea-51944cdfbb0b",
                      [atom(message_ids=[21, 22])])]),  # ids de la conv B !
            expected_run_ref=SLOT_NOW, presented=pres)
    assert e.value.errors == [
        "unknown_conversation:6e2143-0e70-4388-a7ea-51944cdfbb0b"]
    assert e.value.attributed_uids == frozenset()


def test_gar_c7_uid_dune_conversation_hors_pack_reste_fatal(flags):
    """GAR-C-7 — un uid RÉEL mais absent de CE pack (conversation d'un autre
    run, citée verbatim) ne matche rien : FATAL, ON comme OFF."""
    flags(c=True)
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(UID_ABSENT, [atom()])]),
            expected_run_ref=SLOT_NOW, presented=presented(with_b=False))
    assert f"unknown_conversation:{UID_ABSENT}" in e.value.errors


def test_gar_c8_ids_de_messages_pris_pour_un_uid_restent_fatals(flags):
    """GAR-C-8 — mode run 52 (`unknown_conversation:150884`) : un id de message
    à la place d'un uid ne passe pas la garde de forme."""
    flags(c=True)
    for junk in ("150884", "conversation-3", "-" * 36, UID_A[:20]):
        with pytest.raises(contract.ContractError):
            contract.validate_document(
                doc([conv(junk, [atom()])]),
                expected_run_ref=SLOT_NOW, presented=presented(with_b=False))


# =============================================================================
# COMBINAISON A+B+C
# =============================================================================

async def test_gar_abc_blanchiment_dun_document_dun_AUTRE_run_ferme(
        flags, disposer):
    """GAR-ABC (ex ATK-ABC, FERMÉE) — BLANCHIMENT. Un document produit pour un
    AUTRE pack franchissait TROIS détecteurs indépendants d'un coup : run_ref
    (A), uid (C), ids (B). La première barrière tient désormais : un `run_ref`
    bien formé d'un autre run reste FATAL, donc le document n'atteint jamais le
    disposant — aucun atome posté, aucun curseur avancé."""
    pres = presented(a_rendered=(11, 12, 13, 14, 15), a_empty=(16, 17),
                     a_max=17, with_b=False)
    stale = doc([conv("6e2143-0e70-4388-a7ea-51944cdfbb0b",
                      [atom(message_ids=[11, 16, 17])])], run_ref=SLOT_OLD)

    flags(a=False, b=False, c=False)
    with pytest.raises(contract.ContractError) as off:
        contract.validate_document(dict(stale), expected_run_ref=SLOT_NOW,
                                   presented=pres)
    # NB : le garde `foreign_message_ids` n'est même pas atteint flag OFF
    # (pack_entry None), d'où 2 erreurs et non 3.
    assert off.value.errors == [
        f"run_ref_mismatch:{SLOT_OLD!r}",
        "unknown_conversation:6e2143-0e70-4388-a7ea-51944cdfbb0b"]

    flags(a=True, b=True, c=True)
    with pytest.raises(contract.ContractError) as on:
        contract.validate_document(dict(stale), expected_run_ref=SLOT_NOW,
                                   presented=pres)
    assert any(x.startswith("run_ref_mismatch") for x in on.value.errors)
    assert disposer.api.posted == [] and disposer.lib.advances == []


def test_gar_off_bit_identique_sur_toutes_les_attaques(flags):
    """GAR-OFF — filet de sécurité du chantier : flags OFF, CHAQUE document
    d'attaque ci-dessus est rejeté exactement comme avant le chantier fidélité."""
    flags(a=False, b=False, c=False)
    pres = presented(a_rendered=(11, 12), a_empty=(90, 91), a_max=91)
    attaques = [
        doc([conv(UID_A, [atom()])], run_ref=SLOT_OLD),
        doc([conv(UID_A, [atom(message_ids=[11, 90])])]),
        doc([conv("6e2143-0e70-4388-a7ea-51944cdfbb0b", [atom()])]),
        doc([conv("deadbe" + UID_A[6:], [atom()])]),
        doc([conv("6e2143-0e70-4388-a7ea-51944cdfbb0b",
                  [atom(message_ids=[11, 90])])], run_ref=SLOT_OLD),
    ]
    for d in attaques:
        with pytest.raises(contract.ContractError):
            contract.validate_document(d, expected_run_ref=SLOT_NOW,
                                       presented=pres)
