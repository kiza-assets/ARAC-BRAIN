"""Non-régression des correctifs ROUND 2 du chantier fidélité A+B+C.

Un test (au moins) par faille confirmée par la vérification sceptique round 2 :

  - V1 (BLOQUANT)  : la justification empirique de FIX C est FALSIFIÉE — le
                     run 64 cumule un uid corrompu ET un `message_id`
                     HALLUCINÉ (897983, absent de `arac.raw_messages`). Aucun
                     fix ne couvre ce 2e mode ; C ne sauve pas ce run. Ce
                     fichier fige que le garde anti-poison ne cède JAMAIS,
                     quelle que soit la combinaison de flags.
  - F5 (MOYEN)     : réparation C SANS preuve d'appartenance -> disposition
                     terminale (curseur brûlé / punition / exclusion). FERMÉE
                     par la condition (4) : >= 1 id RÉELLEMENT RENDU de la
                     conversation cible doit être cité par le bloc.
  - F6 (MOYEN)     : `duplicate_conversation_uid` FATAL *et attribué*.
                     FERMÉ : le doublon seul n'attribue plus rien.
  - F7 (MOYEN)     : `ARAC_DISPOSE_COVERAGE_V2` (armé en PROD) absent des
                     flags observés. FERMÉ.
  - F8 (FAIBLE)    : prémisse fausse (« aucun lecteur de `progress` ») + forme
                     persistée polymorphe. FERMÉ : filtrage explicite des
                     méta-clés réservées.

Plus une preuve de BIT-IDENTITÉ flags OFF : le module `contract.py` de la
branche est comparé, sur un corpus de documents, au `contract.py` de `main`
(extrait par `git show`) — mêmes erreurs, mêmes attributions, mêmes documents
nettoyés. Aucune DB, aucun réseau.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.cortex import contract, cycle, dispose  # noqa: E402

UID_A = "6e2b6143-0e70-4388-a7ea-51944cdfbb0b"
UID_A_CORRUPT = "6e2143-0e70-4388-a7ea-51944cdfbb0b"     # cas réel run 64
UID_B = "9f41c0aa-7d15-4a62-b3ce-2210ab77e901"
SLOT = "circadian_1300@2026-07-20"

_ALL_FLAGS = (
    "ARAC_CORTEX_RUNREF_LENIENT", "ARAC_CORTEX_EMPTY_DROP_TOLERANT",
    "ARAC_CORTEX_UID_NEARMATCH", "ARAC_CORTEX_DEDUP_UID_STRICT",
    "ARAC_DISPOSE_COVERAGE_V2",
)


@pytest.fixture()
def flags(monkeypatch):
    def _set(**kw):
        for n in _ALL_FLAGS:
            monkeypatch.delenv(n, raising=False)
        for n, on in kw.items():
            monkeypatch.setenv(n, "1" if on else "0")
    _set()
    return _set


def presented(*, empty_ids=frozenset(), with_b=False):
    p = {UID_A: {"conversation_id": "cid-A", "max_id": 12,
                 "message_ids": {11, 12}, "empty_ids": set(empty_ids),
                 "source_type": "claude_code", "fully_presented": True}}
    if with_b:
        p[UID_B] = {"conversation_id": "cid-B", "max_id": 22,
                    "message_ids": {21, 22}, "empty_ids": set(),
                    "source_type": "mac", "fully_presented": True}
    return p


def atom(**over):
    base = {"kind": "gotcha", "scope": "outillage/infrastructure", "key": "r2-cle",
            "value": "Un fait durable, assez long pour être plausible.",
            "rationale": None, "confidence_score": 90, "tags": [],
            "supersede_key_hint": None, "message_ids": [11, 12]}
    base.update(over)
    return base


def conv(uid, atoms=(), **over):
    c = {"conversation_uid": uid, "atoms": list(atoms), "skips": []}
    c.update(over)
    return c


def doc(convs, *, run_ref=SLOT):
    return {"contract_version": "cortex-dispose/1", "run_ref": run_ref,
            "complete": True, "audit_summary": "v", "conversations": convs}


# ===========================================================================
# V1 — le garde anti-poison ne cède sous AUCUNE combinaison de flags
# ===========================================================================
def test_V1_id_halluciné_reste_fatal_tous_flags_armes(flags):
    """V1 : le mode réellement bloquant du run 64 est un `message_id` qui
    N'EXISTE PAS (897983). Aucun fix ne le couvre — et surtout, aucun ne doit
    l'ouvrir : A+B+C+D tous ARMÉS, le document reste FATAL et non attribué."""
    flags(**{n: True for n in _ALL_FLAGS})
    p = presented(empty_ids={9, 10})
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(UID_A_CORRUPT, [atom(message_ids=[11, 12, 897983])])]),
            expected_run_ref=SLOT, presented=p)
    assert e.value.errors == [f"foreign_message_ids:{UID_A}"]
    assert e.value.attributed_uids == frozenset()


def test_V1_la_falsification_est_ecrite_dans_le_code(flags):
    """V1 : la justification « C aurait sauvé le run 64 » ne doit plus figurer
    seule dans le module — la falsification (id halluciné 897983, gain mesuré
    ZÉRO) y est consignée pour que la décision de déploiement soit informée."""
    src = (_REPO / "agents" / "cortex" / "contract.py").read_text()
    assert "897983" in src
    assert "GAIN MESURÉ DE C = 0" in src


# ===========================================================================
# F5 — preuve d'appartenance exigée avant toute réparation d'uid
# ===========================================================================
@pytest.mark.parametrize("bloc,motif", [
    (conv(UID_A_CORRUPT, [], no_new_knowledge=True), "0 atome + attestation"),
    (conv(UID_A_CORRUPT, []), "0 atome nu"),
    (conv(UID_A_CORRUPT, [atom(message_ids=[21, 22])]), "ids d'une autre conv"),
    (conv(UID_A_CORRUPT, [atom(message_ids=[9, 10])]), "ids VIDES seulement"),
    (conv(UID_A_CORRUPT, [atom(message_ids=[999999])]), "id inexistant"),
])
def test_F5_reparation_refusee_sans_preuve(flags, bloc, motif):
    """F5 : sans >= 1 id RÉELLEMENT RENDU de la conv cible cité par le bloc,
    la réparation est refusée -> `unknown_conversation` FATAL, non attribué,
    donc AUCUNE disposition terminale sur la conversation réelle."""
    flags(ARAC_CORTEX_UID_NEARMATCH=True, ARAC_CORTEX_EMPTY_DROP_TOLERANT=True)
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([bloc]), expected_run_ref=SLOT,
            presented=presented(empty_ids={9, 10}, with_b=True))
    assert e.value.errors == [f"unknown_conversation:{UID_A_CORRUPT}"], motif
    assert e.value.attributed_uids == frozenset(), motif


def test_F5_reparation_acceptee_avec_preuve(flags):
    """F5, contre-épreuve : C n'est pas désactivé — un bloc citant >= 1 id
    rendu de la conv cible est toujours réparé (cas du bloc RÉEL du run 64,
    qui porte 7 ids réels de la bonne conversation)."""
    flags(ARAC_CORTEX_UID_NEARMATCH=True)
    cleaned = contract.validate_document(
        doc([conv(UID_A_CORRUPT, [atom(message_ids=[11, 12])])]),
        expected_run_ref=SLOT, presented=presented())
    assert cleaned["_uid_nearmatch_count"] == 1
    assert cleaned["conversations"][0]["conversation_uid"] == UID_A


def test_F5_un_id_vide_ne_vaut_jamais_preuve(flags):
    """F5 : la preuve exige un id RENDU. Un id COUVERT-mais-VIDE (FIX B) ne
    prouve rien — le message n'a rien montré au LLM. Même flag B armé."""
    flags(ARAC_CORTEX_UID_NEARMATCH=True, ARAC_CORTEX_EMPTY_DROP_TOLERANT=True)
    assert contract._membership_proof_count(
        conv(UID_A_CORRUPT, [atom(message_ids=[9, 10])]),
        presented(empty_ids={9, 10})[UID_A]) == 0
    assert contract._membership_proof_count(
        conv(UID_A_CORRUPT, [atom(message_ids=[9, 11])]),
        presented(empty_ids={9, 10})[UID_A]) == 1


def test_F5_symetrie_B_et_C(flags):
    """F5 : l'asymétrie relevée est fermée — B exige `kept` (>= 1 id rendu
    conservé), C exige >= 1 id rendu cité. Même invariant : jamais de
    disposition terminale sans preuve matérielle de lecture."""
    flags(ARAC_CORTEX_EMPTY_DROP_TOLERANT=True, ARAC_CORTEX_UID_NEARMATCH=True)
    p = presented(empty_ids={9, 10})
    with pytest.raises(contract.ContractError):        # B sans `kept`
        contract.validate_document(
            doc([conv(UID_A, [atom(message_ids=[9, 10])])]),
            expected_run_ref=SLOT, presented=p)
    with pytest.raises(contract.ContractError):        # C sans preuve
        contract.validate_document(
            doc([conv(UID_A_CORRUPT, [atom(message_ids=[9, 10])])]),
            expected_run_ref=SLOT, presented=p)


async def test_F5_le_disposant_nest_jamais_atteint(flags, monkeypatch):
    """F5, bout en bout : un bloc sans preuve ne franchit pas le contrat, donc
    `dispose_document` n'est jamais appelé -> ni `advance_cursor`, ni
    `mark_curation_failed`, ni `mark_conversation_excluded` (les trois chemins
    de dommage identifiés), y compris `ARAC_DISPOSE_COVERAGE_V2` armé."""
    calls: list[str] = []

    class _Lib:
        def __getattr__(self, name):
            async def _f(*a, **kw):
                calls.append(name)
                return 0
            return _f

    monkeypatch.setattr(dispose, "curator_lib_v2", _Lib())
    flags(ARAC_CORTEX_UID_NEARMATCH=True, ARAC_DISPOSE_COVERAGE_V2=True)
    for _ in range(3):
        with pytest.raises(contract.ContractError):
            contract.validate_document(
                doc([conv(UID_A_CORRUPT, [], no_new_knowledge=True)]),
                expected_run_ref=SLOT, presented=presented())
    assert calls == []


# ===========================================================================
# F6 — un doublon d'uid ne punit plus personne
# ===========================================================================
def test_F6_doublon_seul_non_attribue(flags):
    """MIS À JOUR round 3 (finding N2) : FIX D est NEUTRALISÉ (trou de
    terminaison — quarantaine payante sans mouvement d'état). Le doublon d'uid
    PUR n'est donc plus fatal du tout, flag armé ou non : la propriété F6
    « ne punit personne » est tenue *a fortiori* (aucune quarantaine)."""
    flags(ARAC_CORTEX_DEDUP_UID_STRICT=True)
    cleaned = contract.validate_document(
        doc([conv(UID_A, [atom()]), conv(UID_A, [atom(key="autre-cle")])]),
        expected_run_ref=SLOT, presented=presented())
    assert len(cleaned["conversations"]) == 2


def test_F6_doublon_plus_vraie_violation_reste_attribue(flags):
    """Contre-épreuve : le décompte ne blanchit rien. Une violation RÉELLE
    dans un bloc dupliqué reste attribuée (guard resserré, pas affaibli)."""
    flags(ARAC_CORTEX_DEDUP_UID_STRICT=True)
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(UID_A, [atom()]),
                 conv(UID_A, [atom(kind="mission")])]),
            expected_run_ref=SLOT, presented=presented())
    assert e.value.attributed_uids == frozenset({UID_A})


def test_F6_doublon_multiple_reste_non_attribue(flags):
    """Trois blocs pour le même uid — MIS À JOUR round 3 (N2, D neutralisé) :
    aucune erreur, aucune attribution, aucune punition possible."""
    flags(ARAC_CORTEX_DEDUP_UID_STRICT=True)
    cleaned = contract.validate_document(
        doc([conv(UID_A, [atom()]), conv(UID_A, [atom(key="k2")]),
             conv(UID_A, [atom(key="k3")])]),
        expected_run_ref=SLOT, presented=presented())
    assert len(cleaned["conversations"]) == 3


# ===========================================================================
# F7 / F8 — observabilité
# ===========================================================================
def test_F7_coverage_v2_observe_et_reporte(flags):
    flags(ARAC_DISPOSE_COVERAGE_V2=True)
    assert "ARAC_DISPOSE_COVERAGE_V2" in cycle._OBSERVED_FLAGS
    armed = cycle._flags_armed()
    assert armed["ARAC_DISPOSE_COVERAGE_V2"] is True
    flags()
    assert cycle._flags_armed()["ARAC_DISPOSE_COVERAGE_V2"] is False


def test_F8_meta_cles_reservees_filtrees():
    """F8 : `progress` reste une map uid -> entrée pour ses lecteurs ; les
    méta-clés réservées (`_fidelity`…) sont filtrées EXPLICITEMENT, y compris
    si elles portent par accident les clés lues, et les valeurs non-dict ne
    font plus crasher le dérivateur de signaux."""
    progress = {UID_A: {"excluded": True},
                "_fidelity": {"parked": True, "excluded": True},
                "_autre": None}
    sigs = cycle._coverage_signals(progress, SLOT)
    assert [(s[0], s[2]) for s in sigs] == [("cortex.omission_excluded", [UID_A])]


def test_F8_premisse_corrigee_dans_le_code():
    """F8 : la justification fausse (« aucun lecteur existant de cette
    colonne ») est retirée et le lecteur réel est cité."""
    src = (_REPO / "agents" / "cortex" / "cycle.py").read_text()
    assert "aucun lecteur existant de cette colonne" not in src
    assert "perception_queries.py:122" in src
    from control_center.sql import perception_queries as pq
    assert "progress" in pq.RUNS_OPEN_SQL


# ===========================================================================
# BIT-IDENTITÉ flags OFF — comparaison directe au `contract.py` de `main`
# ===========================================================================
def _load_main_contract(tmp_path):
    """La version du contrat sur `main`, pour prouver « flags OFF = bit-identique ».

    Ce gate n'a de sens QUE dans un dépôt qui a déjà une branche `main` avec
    de l'historique. Dans un clone frais — ou dans un dépôt qui n'a pas encore
    de premier commit — il n'y a rien à comparer : on SAUTE, on ne fabrique
    pas un succès. Un test vert qui n'a rien vérifié est pire qu'un test
    absent : il rassure.
    """
    proc = subprocess.run(
        ["git", "-C", str(_REPO), "show", "main:agents/cortex/contract.py"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(
            "pas de `main:agents/cortex/contract.py` a comparer "
            "(depot sans historique) — le gate de bit-identite ne s'applique pas ici"
        )
    src = proc.stdout
    path = tmp_path / "contract_main.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("contract_main", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_CORPUS = [
    ("nominal", doc([conv(UID_A, [atom()])]), presented()),
    ("uid_corrompu", doc([conv(UID_A_CORRUPT, [atom()])]), presented()),
    ("uid_corrompu_vide", doc([conv(UID_A_CORRUPT, [], no_new_knowledge=True)]),
     presented()),
    ("ids_etrangers", doc([conv(UID_A, [atom(message_ids=[21, 22])])]),
     presented(with_b=True)),
    ("ids_vides", doc([conv(UID_A, [atom(message_ids=[9, 11])])]),
     presented(empty_ids={9, 10})),
    ("doublon", doc([conv(UID_A, [atom()]), conv(UID_A, [atom(key="k2")])]),
     presented()),
    ("runref_invente", doc([conv(UID_A, [atom()])], run_ref="digest_manuel"),
     presented()),
    ("runref_autre_run", doc([conv(UID_A, [atom()])],
                             run_ref="circadian_0400@2026-07-19"), presented()),
    ("atome_invalide", doc([conv(UID_A, [atom(kind="mission")])]), presented()),
    ("omission_totale", doc([]), presented(with_b=True)),
]


@pytest.mark.parametrize("nom,document,pres", _CORPUS,
                         ids=[c[0] for c in _CORPUS])
def test_OFF_bit_identique_vs_main(flags, tmp_path, nom, document, pres):
    """Exigence dure : flags OFF = comportement de `main` à
    l'octet près. Comparaison DIRECTE des deux implémentations sur le même
    document (erreurs, attributions, document nettoyé)."""
    flags()
    main = _load_main_contract(tmp_path)

    def _run(mod):
        try:
            return ("ok", mod.validate_document(
                dict(document), expected_run_ref=SLOT, presented=dict(pres)))
        except mod.ContractError as exc:
            return ("err", list(exc.errors), sorted(exc.attributed_uids))

    assert _run(contract) == _run(main), nom
