"""Tests hermétiques PERF-LOOP itération 1 — composition de pack.

Deux flags env purs, défaut OFF = bit-identique (zéro DB réelle) :

  - `ARAC_PACK_MAX_CONVS` : plafond de conversations ADMISES par pack.
    Données (enquête quarantaines 2026-07-17) : 0 quarantaine foreign sur
    les packs distincts à 3-5 convs (20 runs) vs 1/2 à 6 convs et 1/1 (2/2
    tirs) à 8 convs ; gain attendu ≈ +87 kt/j (fourchette +31/+174).
    Propriétés testées : cap sur les ADMISES (une reportée ne consomme pas
    de slot), fairness round-robin conservée (le cap prend les N
    premières de l'ordre interleavé), budget non pré-partitionné (la
    dernière admise draine le restant).
  - `ARAC_PACK_STRICT_BOUNDARIES` : durcissement du MARQUAGE des frontières
    (rendu SEUL — guard contract.py et contrat de sortie INTOUCHÉS). Cible
    les 3 mécanismes des 6 quarantaines foreign (523 449 in_tok / 14,6 j) :
    fence DEBUT/FIN avec uid des deux côtés, avis de troncature au bord de
    tranche, format insaisissable par du contenu self-capture (`## ...`).

Fakes partagés avec tests/test_stab_wave2.py (mêmes sémantiques que
test_cortex_pack.py, 1 char = 1 « token »).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.cortex import pack as pack_mod  # noqa: E402
from tests.test_stab_wave2 import (  # noqa: E402
    FakeCuratorLib, _char_count, _conv, _msg,
)


@pytest.fixture(autouse=True)
def _clean_pack_env(monkeypatch):
    """Aucun flag pack ambiant ne doit fuiter dans ces tests (les défauts
    OFF/bit-identiques sont précisément ce qu'on prouve)."""
    for var in ("ARAC_PACK_MAX_CONVS", "ARAC_PACK_STRICT_BOUNDARIES",
                "ARAC_PACK_SOURCE_FAIR", "ARAC_PACK_DROP_EMPTY",
                "ARAC_PACK_TOKEN_BUDGET", "ARAC_PACK_FAIR_WINDOW",
                "ARAC_PACK_FILL_FLOOR"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def curator_lib(monkeypatch):
    fake = FakeCuratorLib([], {})
    monkeypatch.setattr(pack_mod, "curator_lib_v2", fake)

    async def _fake_known_atoms(db, uids):
        return "(aucun)"

    monkeypatch.setattr(pack_mod, "_known_atoms_block", _fake_known_atoms)
    return fake


def _install(curator_lib, conversations, messages_by_conv):
    curator_lib.conversations = conversations
    curator_lib.messages_by_conv = messages_by_conv


async def _build(budget_tokens, **kw):
    return await pack_mod.build_pack(
        object(), budget_tokens=budget_tokens, count_fn=_char_count, **kw)


def _prefix_len(msg_id, role="user"):
    return len(f"[id={msg_id}] {role}: ")


def _header_len(uid, source_type="claude_code"):
    return len(f"## conversation {uid} (source={source_type})")


def _msg_for_cost(msg_id, target_cost, *, role="user"):
    n = target_cost - _prefix_len(msg_id, role)
    assert n >= 0
    return _msg(msg_id, "x" * n, role=role)


def _strict_scaffold_len(uid, last_delta_id, source_type="claude_code"):
    """Coût (char-count) du scaffold strict tel que `build_pack` le réserve :
    header fencé + footer + avis de troncature au dernier id du delta."""
    header = f"<<<DEBUT CONVERSATION uid={uid} source={source_type}>>>"
    footer = (f"<<<FIN CONVERSATION uid={uid} — ids citables : UNIQUEMENT "
              "les ids [id=N] affichés ci-dessus, dans CETTE conversation>>>")
    return (len(header) + len(footer)
            + len(pack_mod._strict_trunc_notice(last_delta_id)))


# ===========================================================================
# _pack_max_convs — lecture env fail-safe
# ===========================================================================


def test_max_convs_no_env_is_zero_unlimited(monkeypatch):
    assert pack_mod._pack_max_convs() == 0


def test_max_convs_env_applied(monkeypatch):
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "4")
    assert pack_mod._pack_max_convs() == 4


def test_max_convs_env_invalid_falls_back_unlimited(monkeypatch, caplog):
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "quatre")
    with caplog.at_level("WARNING", logger="arac.cortex.pack"):
        assert pack_mod._pack_max_convs() == 0
    assert any("ARAC_PACK_MAX_CONVS" in r.message for r in caplog.records)


def test_max_convs_env_negative_falls_back_unlimited(monkeypatch, caplog):
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "-3")
    with caplog.at_level("WARNING", logger="arac.cortex.pack"):
        assert pack_mod._pack_max_convs() == 0
    assert any("ARAC_PACK_MAX_CONVS" in r.message for r in caplog.records)


def test_recommended_value_is_in_3_4_bracket():
    """La valeur recommandée par les données de l'enquête (0 foreign observé
    à 3-5 convs, 4 = plus grand volume à 0 foreign) reste dans la fourchette
    3-4 du programme — garde-fou contre une dérive silencieuse du défaut."""
    assert pack_mod.RECOMMENDED_PACK_MAX_CONVS in (3, 4)


# ===========================================================================
# Flags OFF — bit-identiques (le pack historique, à l'octet près)
# ===========================================================================


async def test_flags_off_block_and_meta_bit_identical(curator_lib):
    """Sans env : rendu au format historique EXACT (`## conversation …`,
    sections jointes par \\n\\n), aucune fence, aucun avis, est_tokens =
    somme headers + messages rendus (comptage historique)."""
    _install(curator_lib,
             [_conv("c1", "conv-1"), _conv("c2", "conv-2")],
             {"c1": [_msg(1, "alpha"), _msg(2, "beta")],
              "c2": [_msg(5, "gamma")]})
    built = await _build(10_000)

    expected_block = (
        "## conversation conv-1 (source=claude_code)\n"
        "[id=1] user: alpha\n"
        "[id=2] user: beta"
        "\n\n"
        "## conversation conv-2 (source=claude_code)\n"
        "[id=5] user: gamma"
    )
    assert built["conversations_block"] == expected_block
    assert [p["uid"] for p in built["pack_meta"]] == ["conv-1", "conv-2"]
    expected_est = (_header_len("conv-1") + len("[id=1] user: alpha")
                    + len("[id=2] user: beta")
                    + _header_len("conv-2") + len("[id=5] user: gamma"))
    assert built["est_tokens"] == expected_est


async def test_max_convs_zero_explicit_is_unlimited(curator_lib, monkeypatch):
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "0")
    convs = [_conv(f"c{i}", f"conv-{i}") for i in range(6)]
    msgs = {f"c{i}": [_msg(1, f"petit {i}")] for i in range(6)}
    _install(curator_lib, convs, msgs)
    built = await _build(10_000)
    assert len(built["pack_meta"]) == 6


# ===========================================================================
# ARAC_PACK_MAX_CONVS ON — propriétés
# ===========================================================================


async def test_max_convs_caps_admitted_conversations(curator_lib, monkeypatch):
    """8 candidates, cap 4 -> exactement les 4 PREMIÈRES de l'ordre des
    candidates entrent au pack (mécanisme des runs 51/52 : 8 tranches/pack,
    2/2 quarantaines — le cap coupe la surface de contamination croisée)."""
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "4")
    convs = [_conv(f"c{i}", f"conv-{i}") for i in range(8)]
    msgs = {f"c{i}": [_msg(1, f"contenu {i}")] for i in range(8)}
    _install(curator_lib, convs, msgs)
    built = await _build(10_000)

    assert [p["uid"] for p in built["pack_meta"]] == [
        "conv-0", "conv-1", "conv-2", "conv-3"]
    for i in range(4, 8):
        assert f"conv-{i}" not in built["presented"], \
            "au-delà du cap : curseur intouché, backlog re-servi au cycle suivant"
    assert "conv-4" not in built["conversations_block"]


async def test_max_convs_fairness_round_robin_conserved(curator_lib, monkeypatch):
    """+ cap : l'interleave par source s'applique AVANT le cap, qui
    prend les N premières de l'ordre interleavé -> 2 convs de CHAQUE source
    avec cap 4 (jamais 4 d'une seule source : fairness intacte)."""
    monkeypatch.setenv("ARAC_PACK_SOURCE_FAIR", "1")
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "4")
    convs = ([_conv(f"m{i}", f"mac-{i}", node_id="mac-1") for i in range(3)]
             + [_conv(f"s{i}", f"spawn-{i}", node_id="spawn-1") for i in range(3)])
    msgs = {c["id"]: [_msg(1, f"contenu {c['id']}")] for c in convs}
    _install(curator_lib, convs, msgs)
    built = await _build(10_000)

    uids = [p["uid"] for p in built["pack_meta"]]
    assert uids == ["mac-0", "spawn-0", "mac-1", "spawn-1"]


async def test_max_convs_reported_conv_does_not_consume_slot(
        curator_lib, monkeypatch):
    """Le cap compte les ADMISES, pas les examinées : une conversation
    REPORTÉE (tête > restant, <= plein) laisse son slot ET son budget à la
    candidate suivante — propriété « budget rempli » du programme."""
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "2")
    header_a = _header_len("conv-a")
    header_b = _header_len("conv-b")
    cost_a = 200
    budget = header_a + cost_a + header_b + 50
    msg_a = _msg_for_cost(1, cost_a)
    msg_b = _msg_for_cost(1, 70)   # > 50 restant, <= budget plein -> report
    msg_c = _msg_for_cost(1, 40)   # tient dans le restant
    _install(curator_lib,
             [_conv("cA", "conv-a"), _conv("cB", "conv-b"), _conv("cC", "conv-c")],
             {"cA": [msg_a], "cB": [msg_b], "cC": [msg_c]})
    built = await _build(budget)

    assert [p["uid"] for p in built["pack_meta"]] == ["conv-a", "conv-c"]
    assert built["messages_reported"] == 1
    assert "conv-b" not in built["presented"]


async def test_max_convs_last_admitted_drains_remaining_budget(
        curator_lib, monkeypatch):
    """cap 1 : le budget n'est PAS pré-partitionné — l'unique admise étend
    sa tranche aussi loin que le budget le permet (3 messages), la 2e
    candidate reste intégralement au backlog."""
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "1")
    _install(curator_lib,
             [_conv("c1", "conv-1"), _conv("c2", "conv-2")],
             {"c1": [_msg(1, "aaa"), _msg(2, "bbb"), _msg(3, "ccc")],
              "c2": [_msg(9, "ddd")]})
    built = await _build(10_000)

    assert [p["uid"] for p in built["pack_meta"]] == ["conv-1"]
    assert built["presented"]["conv-1"]["message_ids"] == {1, 2, 3}
    assert built["presented"]["conv-1"]["fully_presented"] is True
    assert "conv-2" not in built["presented"]


async def test_max_convs_read_each_build_no_reimport(curator_lib, monkeypatch):
    """Env pur : le cap est lu à CHAQUE build (armement/désarmement au
    déploiement systemd sans redéploiement de code)."""
    convs = [_conv(f"c{i}", f"conv-{i}") for i in range(5)]
    msgs = {f"c{i}": [_msg(1, f"contenu {i}")] for i in range(5)}
    _install(curator_lib, convs, msgs)

    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "2")
    built = await _build(10_000)
    assert len(built["pack_meta"]) == 2

    monkeypatch.delenv("ARAC_PACK_MAX_CONVS")
    built = await _build(10_000)
    assert len(built["pack_meta"]) == 5


# ===========================================================================
# ARAC_PACK_STRICT_BOUNDARIES ON — propriétés du rendu
# ===========================================================================


async def test_strict_fences_carry_uid_both_sides_no_legacy_header(
        curator_lib, monkeypatch):
    """Mécanismes (a)/(c) : uid répété DEBUT+FIN, fence `<<<…>>>` distincte
    du format `## conversation` que le contenu self-capture peut contenir."""
    monkeypatch.setenv("ARAC_PACK_STRICT_BOUNDARIES", "1")
    _install(curator_lib, [_conv("c1", "conv-1"), _conv("c2", "conv-2")],
             {"c1": [_msg(1, "alpha")], "c2": [_msg(5, "gamma")]})
    built = await _build(10_000)

    block = built["conversations_block"]
    for uid in ("conv-1", "conv-2"):
        assert f"<<<DEBUT CONVERSATION uid={uid} source=claude_code>>>" in block
        assert f"<<<FIN CONVERSATION uid={uid} — ids citables : " \
               "UNIQUEMENT les ids [id=N] affichés ci-dessus, " \
               "dans CETTE conversation>>>" in block
    assert "## conversation" not in block
    # L'ordre DEBUT -> message -> FIN tient par conversation.
    assert block.index("uid=conv-1 source") < block.index("[id=1]") \
        < block.index("FIN CONVERSATION uid=conv-1")


async def test_strict_trunc_notice_only_when_budget_cuts(curator_lib, monkeypatch):
    """Mécanisme (b) (runs 12/20 : citation de max_id+1 sur tranche coupée
    sans marquage) : avis de troncature ssi la tranche est coupée au budget,
    au DERNIER id couvert ; jamais d'avis sur une tranche complète."""
    monkeypatch.setenv("ARAC_PACK_STRICT_BOUNDARIES", "1")
    uid, cid = "conv-cut", "cC"
    scaffold = _strict_scaffold_len(uid, 2)
    budget = scaffold + 60 + 10  # le 1er message (60) passe, pas le 2e
    _install(curator_lib, [_conv(cid, uid)],
             {cid: [_msg_for_cost(1, 60), _msg_for_cost(2, 60)]})
    built = await _build(budget)

    assert built["presented"][uid]["fully_presented"] is False
    assert pack_mod._strict_trunc_notice(1) in built["conversations_block"]
    assert built["presented"][uid]["message_ids"] == {1}

    # Tranche complète (budget large) : AUCUN avis.
    built2 = await _build(10_000)
    assert built2["presented"][uid]["fully_presented"] is True
    assert "TRANCHE COUPÉE" not in built2["conversations_block"]


async def test_strict_guard_inputs_identical_on_off(curator_lib, monkeypatch):
    """Le durcissement est du RENDU SEUL : `presented` (les entrées du guard
    foreign_message_ids, INTOUCHÉ) et `pack_meta` sont identiques ON/OFF."""
    convs = [_conv("c1", "conv-1"), _conv("c2", "conv-2")]
    msgs = {"c1": [_msg(1, "alpha"), _msg(2, "beta")], "c2": [_msg(5, "gamma")]}
    _install(curator_lib, convs, msgs)

    monkeypatch.delenv("ARAC_PACK_STRICT_BOUNDARIES", raising=False)
    off = await _build(10_000)
    monkeypatch.setenv("ARAC_PACK_STRICT_BOUNDARIES", "1")
    on = await _build(10_000)

    assert on["pack_meta"] == off["pack_meta"]
    assert on["presented"] == off["presented"]
    assert on["messages_reported"] == off["messages_reported"]
    assert on["oversized_messages"] == off["oversized_messages"]


async def test_strict_budget_never_overshot_reserve_is_conservative(
        curator_lib, monkeypatch):
    """Le scaffold (fence+footer+avis) est décompté DANS le budget, réserve
    d'avis bornée par le dernier id du delta -> le rendu réel (avis au
    dernier id COUVERT, <= en chiffres) ne dépasse jamais le budget."""
    monkeypatch.setenv("ARAC_PACK_STRICT_BOUNDARIES", "1")
    uid, cid = "conv-b", "cB"
    _install(curator_lib, [_conv(cid, uid)],
             {cid: [_msg_for_cost(i, 50) for i in range(1, 30)]})
    budget = 600
    built = await _build(budget)

    assert built["pack_meta"], "au moins une tranche admise"
    assert built["est_tokens"] <= budget
    # Le bloc réellement rendu (hors \n de jointure, non comptés — même
    # convention que le comptage historique) tient sous le budget.
    rendered_no_newlines = built["conversations_block"].replace("\n", "")
    assert len(rendered_no_newlines) <= budget


async def test_strict_head_in_scaffold_window_is_oversized_not_livelock(
        curator_lib, monkeypatch):
    """Fail-closed : un message de tête de coût dans ]plein−scaffold, plein]
    ne tiendra JAMAIS avec le scaffold -> oversized (alerte + review-queue),
    jamais un report perpétuel (livelock). OFF : sémantique historique
    (report) bit-identique."""
    uid, cid = "conv-w", "cW"
    budget = 800
    scaffold = _strict_scaffold_len(uid, 1)
    cost = budget - 5  # > budget - scaffold (scaffold >> 5), <= budget
    assert budget - scaffold < cost <= budget
    _install(curator_lib, [_conv(cid, uid)], {cid: [_msg_for_cost(1, cost)]})

    monkeypatch.setenv("ARAC_PACK_STRICT_BOUNDARIES", "1")
    on = await _build(budget)
    assert on["pack_meta"] == []
    assert on["messages_reported"] == 0
    assert [o["uid"] for o in on["oversized_messages"]] == [uid]

    monkeypatch.delenv("ARAC_PACK_STRICT_BOUNDARIES")
    off = await _build(budget)
    assert off["messages_reported"] == 1
    assert off["oversized_messages"] == []


async def test_strict_empty_pack_placeholder_unchanged(curator_lib, monkeypatch):
    monkeypatch.setenv("ARAC_PACK_STRICT_BOUNDARIES", "1")
    _install(curator_lib, [], {})
    built = await _build(10_000)
    assert built["conversations_block"] == "(aucune)"
    assert built["pack_meta"] == []


# ===========================================================================
# Combiné — cap + fences ensemble (la configuration de déploiement visée)
# ===========================================================================


async def test_combined_cap_and_strict_boundaries(curator_lib, monkeypatch):
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "2")
    monkeypatch.setenv("ARAC_PACK_STRICT_BOUNDARIES", "1")
    convs = [_conv(f"c{i}", f"conv-{i}") for i in range(4)]
    msgs = {f"c{i}": [_msg(1, f"contenu {i}")] for i in range(4)}
    _install(curator_lib, convs, msgs)
    built = await _build(10_000)

    assert [p["uid"] for p in built["pack_meta"]] == ["conv-0", "conv-1"]
    block = built["conversations_block"]
    assert block.count("<<<DEBUT CONVERSATION") == 2
    assert block.count("<<<FIN CONVERSATION") == 2
    assert "conv-2" not in block and "conv-3" not in block


# ===========================================================================
# ARAC_PACK_FILL_FLOOR — géant de secours
# ===========================================================================


def _run53_like_pool():
    """Reproduit la topologie du run 53 (diagnostic) : 4 petites convs de
    tête (oldest-content) qui se DRAINENT COURT, puis un géant au rang 5 et
    des mediums aux rangs 6-8. Char-count = « token » (1 char = 1 token).
    Le géant a le plus GROS delta rendable disponible."""
    convs = ([_conv(f"c{i}", f"conv-{i}") for i in range(4)]        # têtes
             + [_conv("cG", "conv-giant")]                          # rang 5
             + [_conv(f"c{i}", f"conv-{i}") for i in range(5, 8)])  # rangs 6-8
    msgs = {f"c{i}": [_msg_for_cost(1, 50)] for i in range(4)}      # têtes courtes
    msgs["cG"] = [_msg_for_cost(mid, 100) for mid in range(1, 21)]  # 20×100 = géant
    for i in range(5, 8):
        msgs[f"c{i}"] = [_msg_for_cost(1, 100), _msg_for_cost(2, 100)]  # mediums
    return convs, msgs


# --- lecture env fail-safe (miroir de _pack_max_convs) ---------------------


def test_fill_floor_no_env_is_zero_off(monkeypatch):
    assert pack_mod._pack_fill_floor() == 0


def test_fill_floor_env_applied(monkeypatch):
    monkeypatch.setenv("ARAC_PACK_FILL_FLOOR", "40000")
    assert pack_mod._pack_fill_floor() == 40_000


def test_fill_floor_env_invalid_falls_back_off(monkeypatch, caplog):
    monkeypatch.setenv("ARAC_PACK_FILL_FLOOR", "quarante")
    with caplog.at_level("WARNING", logger="arac.cortex.pack"):
        assert pack_mod._pack_fill_floor() == 0
    assert any("ARAC_PACK_FILL_FLOOR" in r.message for r in caplog.records)


def test_fill_floor_env_negative_falls_back_off(monkeypatch, caplog):
    monkeypatch.setenv("ARAC_PACK_FILL_FLOOR", "-40000")
    with caplog.at_level("WARNING", logger="arac.cortex.pack"):
        assert pack_mod._pack_fill_floor() == 0
    assert any("ARAC_PACK_FILL_FLOOR" in r.message for r in caplog.records)


def test_recommended_fill_floor_is_40k():
    """Garde-fou : la valeur recommandée par la simulation (milieu robuste de
    la fenêtre bimodale [1,5 ; 68,7] kt) reste 40 000."""
    assert pack_mod.RECOMMENDED_PACK_FILL_FLOOR == 40_000


# --- OFF strict : bit-identique it.1 (le cas décisif du diagnostic) --------


async def test_fill_floor_off_abandons_budget_like_it1(curator_lib, monkeypatch):
    """SANS ARAC_PACK_FILL_FLOOR : cap=4 s'arrête aux 4 têtes qui drainent
    court, le géant du rang 5 n'est JAMAIS admis, du budget est abandonné —
    c'est EXACTEMENT le bug diagnostiqué (comportement it.1 inchangé)."""
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "4")
    convs, msgs = _run53_like_pool()
    _install(curator_lib, convs, msgs)
    built = await _build(1000)

    assert [p["uid"] for p in built["pack_meta"]] == [
        "conv-0", "conv-1", "conv-2", "conv-3"]
    assert "conv-giant" not in built["presented"]
    # Budget massivement abandonné (têtes ~50 chacune).
    assert built["est_tokens"] < 500


# --- ON : le secours admet UN géant, borne 5 convs -------------------------


async def test_fill_floor_rescue_admits_one_giant_five_convs(
        curator_lib, monkeypatch):
    """H-C : cap=4 draine court -> le secours admet UNE conv = le plus gros
    delta dispo (le géant du rang 5). Résultat : 5 convs distinctes, budget
    massivement mieux rempli, budget JAMAIS dépassé."""
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "4")
    monkeypatch.setenv("ARAC_PACK_FILL_FLOOR", "400")
    convs, msgs = _run53_like_pool()
    _install(curator_lib, convs, msgs)

    monkeypatch.delenv("ARAC_PACK_FILL_FLOOR", raising=False)
    off = await _build(1000)  # OFF : les 4 têtes seules, budget abandonné.
    monkeypatch.setenv("ARAC_PACK_FILL_FLOOR", "400")
    built = await _build(1000)

    uids = [p["uid"] for p in built["pack_meta"]]
    # Ordre des 4 premières INCHANGÉ (fairness/interleave préservé).
    assert uids[:4] == ["conv-0", "conv-1", "conv-2", "conv-3"]
    # Exactement UNE conv de secours = le géant (plus gros delta).
    assert uids[4] == "conv-giant"
    assert len(uids) == 5                       # borne cap+1
    # Le secours a bel et bien rempli davantage de budget (>400 récupérés).
    assert built["est_tokens"] > off["est_tokens"] + 400
    # Budget jamais dépassé.
    assert built["est_tokens"] <= 1000


async def test_fill_floor_rescue_never_exceeds_budget(curator_lib, monkeypatch):
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "4")
    monkeypatch.setenv("ARAC_PACK_FILL_FLOOR", "400")
    convs, msgs = _run53_like_pool()
    _install(curator_lib, convs, msgs)
    built = await _build(1000)
    assert built["est_tokens"] <= 1000
    # La tranche de secours est BORNÉE au restant (géant = 2000 de delta pour
    # ~600 de restant) -> partielle, jamais tout le géant d'un coup.
    assert built["presented"]["conv-giant"]["fully_presented"] is False


async def test_fill_floor_picks_biggest_delta_not_first_available(
        curator_lib, monkeypatch):
    """« plus gros delta dispo » : un medium au rang 5 et un géant au rang 6
    -> le secours choisit le GÉANT (plus gros delta), pas le premier venu."""
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "4")
    monkeypatch.setenv("ARAC_PACK_FILL_FLOOR", "400")
    convs = ([_conv(f"c{i}", f"conv-{i}") for i in range(4)]
             + [_conv("cM", "conv-medium"), _conv("cG", "conv-giant")])
    msgs = {f"c{i}": [_msg_for_cost(1, 50)] for i in range(4)}
    msgs["cM"] = [_msg_for_cost(1, 100)]                       # delta 100
    msgs["cG"] = [_msg_for_cost(mid, 100) for mid in range(1, 6)]  # delta 500
    _install(curator_lib, convs, msgs)
    built = await _build(1000)

    uids = [p["uid"] for p in built["pack_meta"]]
    assert uids[4] == "conv-giant"
    assert "conv-medium" not in built["presented"]
    assert len(uids) == 5


async def test_fill_floor_at_most_one_rescue_even_with_many_giants(
        curator_lib, monkeypatch):
    """Le secours = UNE conv, une tranche. Même avec plusieurs géants
    disponibles, on n'en admet JAMAIS plus d'un (borne 5 convs, zone sûre)."""
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "4")
    monkeypatch.setenv("ARAC_PACK_FILL_FLOOR", "400")
    convs = ([_conv(f"c{i}", f"conv-{i}") for i in range(4)]
             + [_conv(f"g{i}", f"conv-giant-{i}") for i in range(3)])
    msgs = {f"c{i}": [_msg_for_cost(1, 50)] for i in range(4)}
    for i in range(3):
        msgs[f"g{i}"] = [_msg_for_cost(mid, 100) for mid in range(1, 21)]
    _install(curator_lib, convs, msgs)
    built = await _build(1000)

    assert len(built["pack_meta"]) == 5
    n_giants = sum(1 for p in built["pack_meta"]
                   if p["uid"].startswith("conv-giant"))
    assert n_giants == 1


# --- no-op quand le pack est déjà plein (branche basse du bimodal) ---------


async def test_fill_floor_no_op_when_pack_already_full(curator_lib, monkeypatch):
    """`remaining` post-cap < seuil (les 4 têtes ont déjà rempli le pack) ->
    le secours ne déclenche PAS : bit-identique it.1 (branche ~0-1,5 kt du
    bimodal, cf pool courant live)."""
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "4")
    monkeypatch.setenv("ARAC_PACK_FILL_FLOOR", "400")
    convs = ([_conv(f"c{i}", f"conv-{i}") for i in range(4)]
             + [_conv("cG", "conv-giant")])
    # 4 têtes de 200 remplissent ~972/1000 -> restant ~28 < 400.
    msgs = {f"c{i}": [_msg_for_cost(1, 200)] for i in range(4)}
    msgs["cG"] = [_msg_for_cost(mid, 100) for mid in range(1, 21)]
    _install(curator_lib, convs, msgs)
    built = await _build(1000)

    assert len(built["pack_meta"]) == 4
    assert "conv-giant" not in built["presented"]


# --- anti-famine : le secours AJOUTE, ne retire jamais ---------------------


async def test_fill_floor_never_removes_admitted_conv(curator_lib, monkeypatch):
    """Anti-famine : les 4 têtes admises restent à LEUR place, avec les MÊMES
    entrées `presented` (guard). Le secours est un SUR-ENSEMBLE strict de it.1
    -> ON contient OFF, plus le géant. Rien n'est retiré."""
    monkeypatch.setenv("ARAC_PACK_MAX_CONVS", "4")
    convs, msgs = _run53_like_pool()
    _install(curator_lib, convs, msgs)

    monkeypatch.delenv("ARAC_PACK_FILL_FLOOR", raising=False)
    off = await _build(1000)
    monkeypatch.setenv("ARAC_PACK_FILL_FLOOR", "400")
    on = await _build(1000)

    # Les 4 têtes de OFF sont dans ON, à la même place, entrées identiques.
    assert on["pack_meta"][:4] == off["pack_meta"]
    for uid in ("conv-0", "conv-1", "conv-2", "conv-3"):
        assert on["presented"][uid] == off["presented"][uid]
    # Le pack ON n'est que OFF + le géant.
    assert set(on["presented"]) == set(off["presented"]) | {"conv-giant"}


# --- rescue exige un CAP : sans plafond, la boucle draine déjà tout --------


async def test_fill_floor_requires_cap_no_op_without_max_convs(
        curator_lib, monkeypatch):
    """Sans `ARAC_PACK_MAX_CONVS`, la boucle mono-passe atteint déjà les
    géants (aucun budget abandonné par le cap) -> le secours ne s'active pas
    (garde `max_convs`), aucune duplication, aucun crash."""
    monkeypatch.delenv("ARAC_PACK_MAX_CONVS", raising=False)
    monkeypatch.setenv("ARAC_PACK_FILL_FLOOR", "400")
    convs, msgs = _run53_like_pool()
    _install(curator_lib, convs, msgs)
    built = await _build(1000)

    # Sans cap : la boucle admet dans l'ordre jusqu'au budget (le géant du
    # rang 5 est atteint naturellement), et chaque uid apparaît AU PLUS une
    # fois (pas de double admission par le secours).
    uids = [p["uid"] for p in built["pack_meta"]]
    assert len(uids) == len(set(uids))
    assert built["est_tokens"] <= 1000
