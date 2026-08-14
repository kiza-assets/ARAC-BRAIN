"""FIX round 3 — non-régression des 2 findings CONFIRMÉS de la revue
adversariale (N1, N2). Hermétique : aucune DB, aucun réseau.

N1 — `TypeError` non rattrapée sous FIX C armé (`atoms` non itérable) qui
     laissait un reçu ORPHELIN `spawning` (spawn payé perdu, bisection
     anti-poison désarmée, tuile cockpit polluée).
N2 — trou de TERMINAISON du FIX D (`ARAC_CORTEX_DEDUP_UID_STRICT`) :
     quarantaine payante non attribuable et sans aucun mouvement d'état.
     Fermé par NEUTRALISATION de D (cf docstring `_dedup_uid_strict_enabled`).
"""
from __future__ import annotations

import ast
import inspect
import sys
import textwrap
from pathlib import Path

import pytest

_REPO = Path("$ARAC_HOME")
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.cortex import contract, cycle  # noqa: E402

UID_A = "6e2b6143-0e70-4388-a7ea-51944cdfbb0b"
UID_A_CORRUPT = "6e2143-0e70-4388-a7ea-51944cdfbb0b"   # cas réel run 64, dist 2
SLOT = "circadian_1300@2026-07-20"

_ALL_FLAGS = ("ARAC_CORTEX_RUNREF_LENIENT", "ARAC_CORTEX_EMPTY_DROP_TOLERANT",
              "ARAC_CORTEX_UID_NEARMATCH", "ARAC_CORTEX_DEDUP_UID_STRICT")


@pytest.fixture()
def flags(monkeypatch):
    def _set(**kw):
        for n in _ALL_FLAGS:
            monkeypatch.delenv(n, raising=False)
        for n, on in kw.items():
            monkeypatch.setenv(n, "1" if on else "0")
    _set()
    return _set


def pres():
    return {UID_A: {"conversation_id": "cid-A", "max_id": 12,
                    "message_ids": {11, 12}, "empty_ids": set(),
                    "source_type": "claude_code", "fully_presented": True}}


def atom(**over):
    base = {"kind": "gotcha", "scope": "outillage/infrastructure", "key": "round3-cle",
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


# ===========================================================================
# N1 — `atoms` non itérable ne doit JAMAIS lever TypeError
# ===========================================================================
# int / bool / float sont TRUTHY et NON itérables : l'idiome
# `conv.get("atoms") or []` ne les rattrapait pas (None/{}/"" étaient falsy,
# str/dict/list itérables) — d'où le trou passé au travers du round 2.
_ATOMS_NON_ITERABLES = [5, True, 1.5, -1, 0.0001]
_ATOMS_AUTRES = [None, {}, "", "abc", {"a": 1}, [], [atom()]]


@pytest.mark.parametrize("bad", _ATOMS_NON_ITERABLES)
def test_N1_atoms_non_iterable_sous_flag_C_leve_ContractError(flags, bad):
    """Chemin EXACT du finding : FIX C armé, uid corrompu (donc la preuve
    d'appartenance est calculée), `atoms` non itérable. Avant le fix :
    `TypeError` remontée hors du `except ContractError` de `cycle.py:522`."""
    flags(ARAC_CORTEX_UID_NEARMATCH=True)
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(UID_A_CORRUPT, atoms=[]) | {"atoms": bad}]),
            expected_run_ref=SLOT, presented=pres())
    # Pas de preuve d'appartenance -> AUCUNE réparation -> FATAL comme `main`.
    assert f"unknown_conversation:{UID_A_CORRUPT}" in e.value.errors
    assert "conversations[0].atoms_not_list" in e.value.errors
    # uid halluciné du point de vue du contrat : jamais attribuable.
    assert e.value.attributed_uids == frozenset()


@pytest.mark.parametrize("bad", _ATOMS_NON_ITERABLES + _ATOMS_AUTRES)
def test_N1_aucune_exception_non_ContractError_toutes_formes(flags, bad):
    """Balayage complet des formes d'`atoms` : la SEULE exception possible
    reste `ContractError` (jamais TypeError/AttributeError), flag C armé."""
    flags(ARAC_CORTEX_UID_NEARMATCH=True)
    try:
        contract.validate_document(
            doc([conv(UID_A_CORRUPT) | {"atoms": bad}]),
            expected_run_ref=SLOT, presented=pres())
    except contract.ContractError:
        pass
    except Exception as exc:  # noqa: BLE001 — c'est précisément le finding
        pytest.fail(f"exception non-contractuelle: {type(exc).__name__}: {exc}")


@pytest.mark.parametrize("bad", _ATOMS_NON_ITERABLES)
def test_N1_bit_identique_flag_C_OFF(flags, bad):
    """Flags OFF : même entrée, mêmes erreurs, même attribution — le fix N1 ne
    touche à RIEN hors du chemin C (il ne s'exécute même pas)."""
    flags()
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(UID_A_CORRUPT) | {"atoms": bad}]),
            expected_run_ref=SLOT, presented=pres())
    assert e.value.errors == [f"unknown_conversation:{UID_A_CORRUPT}",
                              "conversations[0].atoms_not_list"]
    assert e.value.attributed_uids == frozenset()


def test_N1_ne_casse_pas_la_reparation_C_legitime(flags):
    """Contre-épreuve : le durcissement ne tue pas FIX C. Bloc à uid corrompu
    avec `atoms` = LISTE citant des ids réellement rendus -> réparé."""
    flags(ARAC_CORTEX_UID_NEARMATCH=True)
    cleaned = contract.validate_document(
        doc([conv(UID_A_CORRUPT, [atom()])]),
        expected_run_ref=SLOT, presented=pres())
    assert cleaned["conversations"][0]["conversation_uid"] == UID_A
    assert cleaned["_uid_nearmatch_count"] == 1


def test_N1_membership_proof_count_type_guard():
    """Unitaire : `_membership_proof_count` retourne 0 (pas d'exception) pour
    toute forme non-liste d'`atoms` — pas de preuve => pas de réparation."""
    entry = {"message_ids": {11, 12}, "empty_ids": set()}
    for bad in _ATOMS_NON_ITERABLES + [None, {}, "", "abc", {"a": 1}]:
        assert contract._membership_proof_count({"atoms": bad}, entry) == 0
    assert contract._membership_proof_count({"atoms": [atom()]}, entry) == 2


# ---------------------------------------------------------------------------
# N1 (chaîne de dommage) — plus jamais de reçu ORPHELIN `spawning`
# ---------------------------------------------------------------------------
def _validate_try_node():
    tree = ast.parse(textwrap.dedent(inspect.getsource(cycle.run_cycle)))
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and "contract.validate_document" in \
                ast.unparse(node.body):
            return node
    raise AssertionError("try/except autour de validate_document introuvable")


def test_N1_filet_crash_contrat_ferme_le_recu():
    """Défense en profondeur : toute exception NON contractuelle levée par le
    parseur/validateur (entrée 100 % LLM) ferme le reçu au lieu de le laisser
    ouvert au statut `spawning` (spawn payé perdu, bisection anti-poison
    désarmée 2 cycles, tuile cockpit « run(s) ouvert(s) » polluée)."""
    node = _validate_try_node()
    generic = [h for h in node.handlers
               if isinstance(h.type, ast.Name) and h.type.id == "Exception"]
    assert len(generic) == 1, "aucun filet générique autour du contrat"
    body = ast.unparse(generic[0])
    assert "ended=True" in body, "le reçu doit être CLÔTURÉ"
    assert "status='quarantined'" in body, \
        "statut terminal existant (CHECK migration 0019), aucune migration"
    assert isinstance(generic[0].body[-1], ast.Raise), \
        "le crash doit rester VISIBLE (re-levé), seul le reçu orphelin part"
    # aucune punition / aucune avance de curseur dans ce chemin
    assert "_punish_quarantine" not in body and "advance_cursor" not in body


def test_N1_filet_crash_ne_precede_pas_le_handler_contractuel():
    """Ordre des handlers : `ContractError` (quarantaine normale, attribuée)
    doit rester AVANT le filet générique, sinon toute quarantaine ordinaire
    deviendrait un crash et perdrait l'attribution du poison."""
    node = _validate_try_node()
    kinds = [ast.unparse(h.type) for h in node.handlers]
    assert kinds.index("contract.ContractError") < kinds.index("Exception")


# ===========================================================================
# N2 — FIX D neutralisé (trou de terminaison fermé par désactivation)
# ===========================================================================
def test_N2_flag_D_arme_est_inerte(flags):
    """Le flag est LU mais n'a plus d'effet : `_dedup_uid_strict_enabled()`
    retourne False dans les deux états."""
    flags()
    assert contract._dedup_uid_strict_enabled() is False
    flags(ARAC_CORTEX_DEDUP_UID_STRICT=True)
    assert contract._dedup_uid_strict_enabled() is False


def test_N2_doublon_uid_ne_quarantaine_plus(flags):
    """Doublon d'uid PUR, flag D armé : plus AUCUNE quarantaine non
    attribuable (donc plus de re-spawn payé sans mouvement d'état). Le
    document est accepté comme sur `main` — dette F1 au statu quo."""
    flags(ARAC_CORTEX_DEDUP_UID_STRICT=True)
    cleaned = contract.validate_document(
        doc([conv(UID_A, [atom()]), conv(UID_A, [atom(key="autre-cle")])]),
        expected_run_ref=SLOT, presented=pres())
    assert len(cleaned["conversations"]) == 2


def test_N2_bit_identique_flag_D_arme_ou_non(flags):
    """Preuve d'inertie : document nettoyé STRICTEMENT identique flag armé et
    flag absent (le flag ne peut plus rien changer, dans aucun sens)."""
    d = [conv(UID_A, [atom()]), conv(UID_A, [atom(key="autre-cle")])]
    flags()
    off = contract.validate_document(doc(d), expected_run_ref=SLOT,
                                     presented=pres())
    flags(ARAC_CORTEX_DEDUP_UID_STRICT=True)
    on = contract.validate_document(doc(d), expected_run_ref=SLOT,
                                    presented=pres())
    assert on == off


def test_N2_guard_anti_poison_intact_sur_bloc_duplique(flags):
    """Aucun guard affaibli : une VRAIE violation (ids étrangers) portée par
    un bloc dupliqué reste FATALE et ATTRIBUÉE, flag D armé."""
    flags(ARAC_CORTEX_DEDUP_UID_STRICT=True)
    with pytest.raises(contract.ContractError) as e:
        contract.validate_document(
            doc([conv(UID_A, [atom()]), conv(UID_A, [atom(message_ids=[999])])]),
            expected_run_ref=SLOT, presented=pres())
    assert e.value.errors == [f"foreign_message_ids:{UID_A}"]
    assert e.value.attributed_uids == frozenset({UID_A})
