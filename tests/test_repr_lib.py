"""test_repr_lib.py — tests unitaires HERMÉTIQUES de la lib pure `app/repr/`
(write-path fold v2, / WP-B).

Zéro DB, zéro réseau, zéro OpenAI : embed_fn fake déterministe (dérivé
sha256 du texte), FakeConn scriptée par fragment de SQL, fixtures NDJSON des
DEUX formats de transcript curator (CLI blocks / desktop simple).

Ce qui est prouvé ici :
  - recette : composition T_meta verbatim, deslug, borne 256 tok cl100k
    (tête), fold = formule exacte du banc, dégénérescence T_meta (aucun span
    user / alpha>=1), MANIFEST_SHA stable et recalculable ;
  - spans : classification bi-format de source_ref, extraction user pure
    (ordre cortex fourni, indices curator sorted(set), lignes malformées /
    hors bornes skippées, blocks tool_* exclus), I/O fines (SQL attendu,
    gunzip, UUID bruyant, conversation manquante → []) ;
  - builder : 2 embeddings max, INSERT ON CONFLICT DO NOTHING (rowcount 0 →
    conflict_skipped), pré-check d'existence → ZÉRO appel embed, budget
    fail-closed qui refuse AVANT tout appel API, provenance build jsonb sans
    texte, dims invalides bruyantes.
"""
from __future__ import annotations

import gzip
import hashlib
import json

import numpy as np
import pytest

from app.repr import builder as builder_mod
from app.repr import recipe, spans
from app.repr.builder import (
    BudgetExceeded,
    BudgetLedger,
    ReprBuildResult,
    build_repr,
)

# ============================================================================
# Outillage hermétique
# ============================================================================


def det_embed_factory():
    """embed_fn fake déterministe : texte -> vecteur 3072 dérivé du sha256
    (deux textes différents => vecteurs différents, même texte => mêmes
    octets). Compte les appels et mémorise les textes reçus."""
    calls: list[str] = []

    def embed_fn(text: str) -> list[float]:
        calls.append(text)
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        return rng.standard_normal(recipe.EMBED_DIMS).tolist()

    embed_fn.calls = calls
    return embed_fn


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows: list = []
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, params))
        for fragment, rows, rowcount in self._conn.routes:
            if fragment in sql:
                self._rows = list(rows)
                self.rowcount = rowcount
                return
        raise AssertionError(f"SQL non scripté dans FakeConn: {sql[:120]!r}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    """Connexion psycopg sync factice : routes = [(fragment_sql, rows,
    rowcount)], premier fragment inclus dans le SQL exécuté gagne."""

    def __init__(self, routes):
        self.routes = routes
        self.executed: list[tuple[str, tuple | None]] = []
        self.commits = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1


ATOM_ID = "3d0e8a3c-9f2b-4c11-8a5e-2b7f01234567"
RAW_ID = "b6a1f0d2-3c4e-4f5a-9b8c-7d6e5f403210"


def atom_row(source_ref, **over):
    row = {
        "id": ATOM_ID,
        "value": "Le serveur ARAC tourne sur Hetzner CPX21.",
        "scope": "outillage/infrastructure",
        "kind": "fact",
        "key": "serveur-hetzner_cpx21",
        "tags": ["infra", "hetzner"],
        "source_ref": source_ref,
    }
    row.update(over)
    return row


def cortex_conn(msg_rows, *, exists=False, insert_rowcount=1):
    return FakeConn([
        ("FROM arac.memory_atom_reprs", [(1,)] if exists else [], -1),
        ("FROM arac.raw_messages", msg_rows, -1),
        ("INSERT INTO arac.memory_atom_reprs", [], insert_rowcount),
    ])


# Transcript NDJSON curator : les DEUX formats + lignes pièges.
NDJSON_LINES = [
    # 0 — format CLI, user, content list de blocks (tool_result exclu)
    json.dumps({"type": "user", "message": {"role": "user", "content": [
        {"type": "text", "text": "Question CLI ligne zéro."},
        {"type": "tool_result", "content": "JAMAIS extrait"},
    ]}}),
    # 1 — format CLI, assistant (exclu du fold)
    json.dumps({"type": "assistant", "message": {"role": "assistant",
                                                  "content": "Réponse assistant."}}),
    # 2 — format desktop, user, content str
    json.dumps({"role": "user", "content": "  Question desktop ligne deux.  ",
                "created_at": "2026-01-01"}),
    # 3 — ligne malformée (JSON invalide)
    "{pas du json",
    # 4 — format desktop, user mais contenu vide
    json.dumps({"role": "user", "content": "   "}),
    # 5 — format CLI, user, content str
    json.dumps({"type": "user", "message": {"role": "user",
                                             "content": "Question CLI ligne cinq."}}),
]
NDJSON_TEXT = "\n".join(NDJSON_LINES)
NDJSON_GZ = gzip.compress(NDJSON_TEXT.encode("utf-8"))


# ============================================================================
# recipe.py — recette gelée
# ============================================================================


def test_recipe_champion_params_verbatim():
    assert recipe.REPR_VERSION == "rm1-fold-a50"
    assert recipe.ALPHA == 0.5
    assert recipe.USER_SURFACE_CAP_TOK == 256
    assert recipe.EMBED_DIMS == 3072
    assert recipe.EMBED_MODEL == "text-embedding-3-large"
    assert recipe.RECIPE["recipe_version"] == "rm1-fold-a50-prod-v1"


def test_manifest_sha_stable_et_recalculable():
    expected = hashlib.sha256(
        json.dumps(recipe.RECIPE, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert recipe.MANIFEST_SHA == expected
    assert len(recipe.MANIFEST_SHA) == 64


def test_deslug_verbatim():
    assert recipe.deslug("outillage/infrastructure-v2") == "outillage infrastructure v2"
    assert recipe.deslug(None) == ""
    assert recipe.deslug("") == ""


def test_compose_t_meta_verbatim_avec_tags():
    out = recipe.compose_t_meta(atom_row(None))
    assert out == (
        "Le serveur ARAC tourne sur Hetzner CPX21."
        "\n\n[scope] outillage infrastructure"
        "\n[kind] fact"
        "\n[cle] serveur hetzner cpx21"
        "\n[tags] infra hetzner"
    )


def test_compose_t_meta_sans_tags_ni_kind():
    out = recipe.compose_t_meta(atom_row(None, tags=None, kind=None))
    assert out.endswith("\n[cle] serveur hetzner cpx21")
    assert "[tags]" not in out
    assert "\n[kind] \n" in out  # kind None -> chaîne vide, section présente


def test_bound_user_surface_vide():
    assert recipe.bound_user_surface([]) == ""
    assert recipe.bound_user_surface(["", "   ", "\n"]) == ""


def test_bound_user_surface_ordre_et_join():
    out = recipe.bound_user_surface(["premier", "", "second"])
    assert out == "premier\n\nsecond"


def test_bound_user_surface_cap_256_tokens_tete():
    long_text = " ".join(f"mot{i}" for i in range(2000))
    out = recipe.bound_user_surface([long_text])
    assert recipe.ntok(out) <= 256
    assert out.startswith("mot0 mot1")  # cap en TÊTE, jamais la queue
    court = "texte court sous la borne"
    assert recipe.bound_user_surface([court]) == court


def test_head_cap_tokens_texte_court_inchange():
    assert recipe.head_cap_tokens("bonjour", 256) == "bonjour"


def test_fold_formule_exacte_du_banc():
    rng = np.random.default_rng(42)
    meta = rng.standard_normal(8)
    u1 = rng.standard_normal(8)
    u2 = rng.standard_normal(8)

    def _nrm(v):
        n = float(np.linalg.norm(v))
        return v / n if n > 0 else v

    surf = _nrm(np.mean([_nrm(u1), _nrm(u2)], axis=0))
    expected = _nrm(0.5 * _nrm(meta) + 0.5 * surf)
    got = recipe.fold(meta, [u1, u2], alpha=0.5)
    assert np.allclose(got, expected, atol=0, rtol=0)
    assert abs(float(np.linalg.norm(got)) - 1.0) < 1e-12


def test_fold_degenerescence_sans_user_vec_retourne_meta_brut():
    meta = [3.0, 4.0, 0.0]  # norme 5 — PAS re-normalisé en dégénérescence
    got = recipe.fold(meta, [])
    assert np.array_equal(got, np.array(meta, dtype=np.float64))


def test_fold_alpha_1_degenere_meme_avec_user_vecs():
    meta = [1.0, 2.0, 3.0]
    got = recipe.fold(meta, [[9.0, 9.0, 9.0]], alpha=1.0)
    assert np.array_equal(got, np.array(meta, dtype=np.float64))


def test_vec_to_text_parse_roundtrip():
    v = np.array([0.5, -1.25, 3.0])
    assert np.array_equal(recipe.parse_vec(recipe.vec_to_text(v)), v)


# ============================================================================
# spans.py — classification + extraction pure
# ============================================================================


def test_classify_cortex():
    fmt, ref = spans.classify_source_ref(
        {"contract": "cortex-dispose/1", "message_ids": [7, 3, 9]})
    assert fmt == "cortex"
    assert ref["message_ids"] == [7, 3, 9]


def test_classify_curator_prioritaire_et_coercions():
    fmt, ref = spans.classify_source_ref(
        {"curator_raw_id": RAW_ID, "message_indices": [2, 0, "x", 5.0]})
    assert fmt == "curator"
    assert ref["curator_raw_id"] == RAW_ID
    assert ref["message_indices"] == [2, 0, 5]  # non-numérique ignoré (comme le banc)


def test_classify_none():
    for sref in (None, {}, "", "pas du json", {"autre": 1},
                 {"message_ids": []}, {"message_ids": "3"},
                 json.dumps({"foo": "bar"})):
        assert spans.classify_source_ref(sref) == ("none", {})


def test_classify_source_ref_json_texte():
    fmt, ref = spans.classify_source_ref(json.dumps({"message_ids": [11]}))
    assert (fmt, ref["message_ids"]) == ("cortex", [11])


def test_classify_cortex_id_non_coercable_bruyant():
    with pytest.raises((ValueError, TypeError)):
        spans.classify_source_ref({"message_ids": ["abc"]})


def test_role_of_bi_format():
    assert spans.role_of({"message": {"role": "user"}, "type": "x"}) == "user"
    assert spans.role_of({"role": "assistant"}) == "assistant"
    assert spans.role_of({"type": "user"}) == "user"
    assert spans.role_of({}) is None


def test_extract_curator_text_cli_blocks_text_uniquement():
    obj = json.loads(NDJSON_LINES[0])
    assert spans.extract_curator_text(obj) == "Question CLI ligne zéro."


def test_extract_curator_text_desktop_str():
    obj = json.loads(NDJSON_LINES[2])
    assert spans.extract_curator_text(obj) == "Question desktop ligne deux."


def test_cortex_user_texts_ordre_fourni_et_filtres():
    msg_map = {
        1: ("user", "  premier tour user  "),
        2: ("assistant", "réponse"),
        3: ("user", "   "),          # vide après strip -> skip
        4: ("user", "second tour user"),
    }
    # ordre fourni 4 avant 1 (ordre du LLM cortex, pas de tri) ; 99 manquant
    out = spans.cortex_user_texts(msg_map, [4, 99, 2, 1, 3])
    assert out == ["second tour user", "premier tour user"]


def test_curator_user_texts_from_ndjson_bi_format():
    # indices désordonnés + doublon + hors bornes + malformé + assistant + vide
    out = spans.curator_user_texts_from_ndjson(
        NDJSON_TEXT, [5, 0, 2, 2, 1, 3, 4, 42, -1])
    # sorted(set(indices)) -> ordre 0, 2, 5 pour les user non vides
    assert out == [
        "Question CLI ligne zéro.",
        "Question desktop ligne deux.",
        "Question CLI ligne cinq.",
    ]


def test_fetch_cortex_user_texts_sql_et_extraction():
    conn = FakeConn([
        ("FROM arac.raw_messages", [(3, "user", "salut"), (5, "assistant", "re")], -1),
    ])
    out = spans.fetch_cortex_user_texts(conn, [5, 3])
    assert out == ["salut"]
    sql, params = conn.executed[0]
    assert "arac.raw_messages" in sql and "ANY" in sql
    assert params == ([5, 3],)


def test_fetch_curator_user_texts_gunzip():
    conn = FakeConn([("FROM arac.raw_conversations", [(NDJSON_GZ,)], -1)])
    out = spans.fetch_curator_user_texts(conn, RAW_ID, [0, 2])
    assert out == ["Question CLI ligne zéro.", "Question desktop ligne deux."]
    sql, params = conn.executed[0]
    assert "content_gz" in sql and params == (RAW_ID,)


def test_fetch_curator_conversation_absente_fallback_vide():
    conn = FakeConn([("FROM arac.raw_conversations", [], -1)])
    assert spans.fetch_curator_user_texts(conn, RAW_ID, [0]) == []


def test_fetch_curator_uuid_invalide_bruyant():
    conn = FakeConn([])
    with pytest.raises(ValueError):
        spans.fetch_curator_user_texts(conn, "pas-un-uuid", [0])
    assert conn.executed == []  # jamais parti en SQL


def test_user_texts_for_source_ref_sans_ancrage():
    conn = FakeConn([])  # aucune requête ne doit partir
    assert spans.user_texts_for_source_ref(conn, {"autre": True}) == ("none", [])
    assert conn.executed == []


# ============================================================================
# builder.py — BudgetLedger fail-closed
# ============================================================================


def test_budget_ledger_cumul_et_refus_avant_depense():
    ledger = BudgetLedger(budget_usd=0.13 * 100 / 1_000_000)  # plafond ~100 tokens
    assert 0 < ledger.budget_tokens <= 100  # int() tronque l'arrondi flottant
    ledger.charge(["a b c"], "ok")
    before = ledger.sent_tokens
    gros = " ".join(f"mot{i}" for i in range(500))
    with pytest.raises(BudgetExceeded):
        ledger.charge([gros], "trop")
    # le refus ne comptabilise RIEN (fail-closed, pas de demi-dépense)
    assert ledger.sent_tokens == before
    assert [c["label"] for c in ledger.calls] == ["ok"]


def test_budget_ledger_spent_usd():
    ledger = BudgetLedger()
    ledger.charge(["quelques mots à compter"], "x")
    assert ledger.spent_usd == round(ledger.sent_tokens * 0.13 / 1e6, 6)


# ============================================================================
# builder.py — build_repr
# ============================================================================


def test_build_repr_nominal_cortex_2_embeddings_et_fold():
    embed_fn = det_embed_factory()
    conn = cortex_conn([(3, "user", "quelle est la config du serveur ?"),
                        (4, "assistant", "CPX21.")])
    row = atom_row({"message_ids": [3, 4]})
    res = build_repr(conn, embed_fn, row)

    assert isinstance(res, ReprBuildResult)
    assert res.status == "inserted" and res.inserted
    assert res.source_format == "cortex"
    assert res.n_spans == 1 and not res.degenerate
    assert res.embed_calls == 2 and len(embed_fn.calls) == 2
    assert res.n_user_tokens == recipe.ntok("quelle est la config du serveur ?")

    t_meta = recipe.compose_t_meta(row)
    assert embed_fn.calls == [t_meta, "quelle est la config du serveur ?"]

    sql, params = conn.executed[-1]
    assert "ON CONFLICT (atom_id, repr_version) DO NOTHING" in sql
    assert params[0] == ATOM_ID
    assert params[1] == "rm1-fold-a50"
    assert params[3] == recipe.MANIFEST_SHA
    assert params[4] is None  # doc_sha256 None (fidèle aux lignes fold du banc)

    # vecteur inséré == fold exact des deux embeddings
    expected = recipe.fold(embed_fn(t_meta),
                           [embed_fn("quelle est la config du serveur ?")])
    assert np.allclose(recipe.parse_vec(params[2]), expected, atol=0, rtol=0)
    assert abs(float(np.linalg.norm(recipe.parse_vec(params[2]))) - 1.0) < 1e-9


def test_build_repr_provenance_sans_texte():
    embed_fn = det_embed_factory()
    conn = cortex_conn([(3, "user", "texte user secret")])
    res = build_repr(conn, embed_fn, atom_row({"message_ids": [3]}))
    build = json.loads(conn.executed[-1][1][5])
    assert set(build) == {"format", "n_spans", "n_user_tokens", "degenerate"}
    assert build == {"format": "cortex", "n_spans": 1,
                     "n_user_tokens": recipe.ntok("texte user secret"),
                     "degenerate": False}
    assert "secret" not in conn.executed[-1][1][5]
    assert res.n_spans == 1


def test_build_repr_degenerescence_sans_ancrage_egale_emb_t_meta():
    embed_fn = det_embed_factory()
    conn = FakeConn([
        ("FROM arac.memory_atom_reprs", [], -1),
        ("INSERT INTO arac.memory_atom_reprs", [], 1),
    ])
    row = atom_row(None)
    res = build_repr(conn, embed_fn, row)

    assert res.degenerate and res.source_format == "none"
    assert res.embed_calls == 1 and len(embed_fn.calls) == 1
    assert res.n_spans == 0 and res.n_user_tokens == 0
    # repr == emb(T_meta) VERBATIM (plancher méta, jamais re-normalisé)
    inserted_vec = recipe.parse_vec(conn.executed[-1][1][2])
    meta_vec = np.array(embed_fn(recipe.compose_t_meta(row)), dtype=np.float64)
    assert np.array_equal(inserted_vec, meta_vec)
    build = json.loads(conn.executed[-1][1][5])
    assert build["degenerate"] is True and build["format"] == "none"


def test_build_repr_degenerescence_spans_non_user():
    embed_fn = det_embed_factory()
    conn = cortex_conn([(3, "assistant", "que de l'assistant")])
    res = build_repr(conn, embed_fn, atom_row({"message_ids": [3]}))
    assert res.degenerate and res.source_format == "cortex"
    assert res.embed_calls == 1 and res.n_spans == 0


def test_build_repr_format_curator_legacy():
    embed_fn = det_embed_factory()
    conn = FakeConn([
        ("FROM arac.memory_atom_reprs", [], -1),
        ("FROM arac.raw_conversations", [(NDJSON_GZ,)], -1),
        ("INSERT INTO arac.memory_atom_reprs", [], 1),
    ])
    res = build_repr(conn, embed_fn, atom_row(
        {"curator_raw_id": RAW_ID, "message_indices": [0, 1, 2]}))
    assert res.source_format == "curator"
    assert res.n_spans == 2 and not res.degenerate  # lignes 0 et 2 user, 1 assistant
    surface = recipe.bound_user_surface(
        ["Question CLI ligne zéro.", "Question desktop ligne deux."])
    assert embed_fn.calls[1] == surface


def test_build_repr_deja_presente_zero_embed_zero_insert():
    embed_fn = det_embed_factory()
    conn = cortex_conn([], exists=True)
    res = build_repr(conn, embed_fn, atom_row({"message_ids": [3]}))
    assert res.status == "already_present" and not res.inserted
    assert res.embed_calls == 0 and embed_fn.calls == []
    assert len(conn.executed) == 1  # le seul SELECT d'existence, rien d'autre


def test_build_repr_on_conflict_rowcount_zero():
    embed_fn = det_embed_factory()
    conn = cortex_conn([(3, "user", "bonjour")], insert_rowcount=0)
    res = build_repr(conn, embed_fn, atom_row({"message_ids": [3]}))
    assert res.status == "conflict_skipped" and not res.inserted


def test_build_repr_budget_refuse_avant_tout_appel_api():
    embed_fn = det_embed_factory()
    conn = cortex_conn([(3, "user", "bonjour")])
    ledger = BudgetLedger(budget_usd=0.13 * 1 / 1_000_000)  # plafond 1 token
    with pytest.raises(BudgetExceeded):
        build_repr(conn, embed_fn, atom_row({"message_ids": [3]}), ledger=ledger)
    assert embed_fn.calls == []  # AUCUN appel API après le refus
    assert not any("INSERT INTO arac.memory_atom_reprs" in sql
                   for sql, _ in conn.executed)  # aucune écriture non plus
    assert ledger.sent_tokens == 0


def test_build_repr_ledger_partage_cumule():
    embed_fn = det_embed_factory()
    ledger = BudgetLedger()
    conn1 = cortex_conn([(3, "user", "bonjour")])
    conn2 = cortex_conn([(3, "user", "bonsoir")])
    r1 = build_repr(conn1, embed_fn, atom_row({"message_ids": [3]}), ledger=ledger)
    r2 = build_repr(conn2, embed_fn, atom_row({"message_ids": [3]}), ledger=ledger)
    assert ledger.sent_tokens == r1.api_tokens + r2.api_tokens > 0
    assert len(ledger.calls) == 2


def test_build_repr_dims_invalides_bruyant():
    def bad_embed(text):
        return [0.1, 0.2, 0.3]  # 3 dims au lieu de 3072

    conn = cortex_conn([(3, "user", "bonjour")])
    with pytest.raises(ValueError, match="3072"):
        build_repr(conn, bad_embed, atom_row({"message_ids": [3]}))
    assert not any("INSERT INTO arac.memory_atom_reprs" in sql
                   for sql, _ in conn.executed)


def test_build_repr_ne_commit_jamais():
    """Le commit appartient à l'appelant (batch WP-C) — contrat documenté."""
    embed_fn = det_embed_factory()
    conn = cortex_conn([(3, "user", "bonjour")])
    build_repr(conn, embed_fn, atom_row({"message_ids": [3]}))
    assert conn.commits == 0


# ============================================================================
# __init__.py — garde anti-boot
# ============================================================================


def test_init_n_importe_aucun_sous_module():
    import importlib
    import sys

    for mod in ("app.repr", "app.repr.recipe", "app.repr.spans", "app.repr.builder"):
        sys.modules.pop(mod, None)
    importlib.import_module("app.repr")
    assert "app.repr.recipe" not in sys.modules
    assert "app.repr.spans" not in sys.modules
    assert "app.repr.builder" not in sys.modules
