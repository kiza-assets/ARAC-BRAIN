"""Tests `raw_message_revisions` — divergence de hash / correctifs coordination.

Deux volets, cf app/routers/ingest_v2.py + app/services/raw_message_revisions.py :

  - Détection PURE (`check_hash_divergence`) : testable sans DB, mêmes cas
    que la doctrine de la migration 0022 — un `dedup_key` absent de la map
    n'est JAMAIS une divergence (message nouveau), une ré-émission
    identique n'en est pas une non plus (seul un hash DIFFÉRENT sur un
    `dedup_key` déjà connu l'est).
  - `write_hash_divergence_revision` (app/services/raw_message_revisions.py) :
    forme SQL + masquage défensif (`mask_recursive`), testé hermétiquement
    (Fake connection/cursor, même stratégie que
    tests/test_ingest_v2_contract.py pour `write_accepted_receipt`).
  - Tests DB docker (SKIP proprement si `DATABASE_URL_ADMIN_TEST`/
    `DATABASE_URL_APP_TEST` absentes, cf tests/conftest.py) : bout-en-bout
    via `ingest_messages`, pour les cas ACCEPTANCE/BREAK du chantier (re-
    émission modifiée/identique, uuid NULL, N duplicates -> 1 seul SELECT
    de pré-fetch, 50 éditions -> 50 révisions/0 mutation, batch mixte,
    secret masqué, refus 403 -> reçu `refused_403`).

Correctifs de coordination (vague 2) inclus ici :
  - correctif 1 : `refused_403` doit être présent dans le CHECK outcome de
    la migration 0021 (test statique) — et le routeur doit désormais écrire
    un reçu sur un refus 403 (whitelist node).
"""

from __future__ import annotations

import inspect
import logging
import os
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.routers.ingest_v2 import (
    _OUTCOME_BY_STATUS,
    check_hash_divergence,
    compute_content_hash,
    compute_dedup_key,
)
from app.services.raw_message_revisions import write_hash_divergence_revision
from app.services.sanitize import mask_recursive

_MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "db", "alembic", "versions")


# ============================================================================
# Helpers (mêmes patterns que tests/test_ingest_v2_contract.py)
# ============================================================================


def _fake_request(*, headers: dict[str, str], body: bytes) -> SimpleNamespace:
    async def _body() -> bytes:
        return body

    return SimpleNamespace(headers=headers, body=_body, state=SimpleNamespace())


def _fake_response() -> SimpleNamespace:
    return SimpleNamespace(headers={}, status_code=200)


def _router_source() -> str:
    import app.routers.ingest_v2 as ingest_v2_mod

    return inspect.getsource(ingest_v2_mod)


def _payload(conv_uid: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source_type": "claude_code",
        "conversation_uid": conv_uid,
        "messages": messages,
    }


# ============================================================================
# check_hash_divergence — logique PURE (aucune DB)
# ============================================================================


def test_new_dedup_key_absent_from_map_is_never_a_divergence():
    """Un `dedup_key` absent de la map pré-fetchée = message nouveau, jamais
    une divergence (cf docstring migration 0022 + acceptance uuid NULL)."""
    assert check_hash_divergence({}, "m1", "hash-incoming") is None


def test_identical_resubmission_is_not_a_divergence():
    existing = {"m1": (42, "same-hash")}
    assert check_hash_divergence(existing, "m1", "same-hash") is None


def test_diverging_hash_on_known_dedup_key_is_detected():
    existing = {"m1": (42, "old-hash")}
    result = check_hash_divergence(existing, "m1", "new-hash")
    assert result == (42, "old-hash")


def test_uuid_null_content_changed_produces_new_dedup_key_not_a_divergence():
    """Acceptance : uuid NULL + contenu changé -> `dedup_key='h:'||hash`
    DIFFÉRENT -> nouveau message, PAS une fausse divergence."""
    existing_hash = compute_content_hash("user", "contenu original", None)
    existing_key = compute_dedup_key(None, existing_hash)
    existing = {existing_key: (7, existing_hash)}

    incoming_hash = compute_content_hash("user", "contenu modifié", None)
    incoming_key = compute_dedup_key(None, incoming_hash)

    assert incoming_key != existing_key
    assert check_hash_divergence(existing, incoming_key, incoming_hash) is None


def test_fifty_edits_all_diverge_against_the_same_original_never_mutated():
    """BREAK : éditer le même message 50x -> 50 divergences détectées, TOUTES
    contre le hash ORIGINAL (jamais réécrit — 0 mutation, cf `existing` non
    modifié par `check_hash_divergence`, fonction pure sans effet de bord)."""
    original_hash = "0" * 64
    existing = {"stable": (1, original_hash)}
    detections = []
    for i in range(50):
        incoming_hash = f"{i + 1:064d}"  # jamais "0"*64 (l'original), toujours divergent
        detections.append(check_hash_divergence(existing, "stable", incoming_hash))
    assert len(detections) == 50
    assert all(d == (1, original_hash) for d in detections)
    # La map "existing" (mirror de raw_messages) n'a jamais été mutée.
    assert existing == {"stable": (1, original_hash)}


# ============================================================================
# write_hash_divergence_revision — forme SQL + masquage défensif (hermétique)
# ============================================================================


class _FakeCursor:
    def __init__(self, sink: list[tuple[str, tuple]]):
        self._sink = sink

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def execute(self, sql: str, params: tuple = ()):
        self._sink.append((sql, params))


class _FakeConnection:
    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []

    def cursor(self):
        return _FakeCursor(self.executed)


async def test_write_hash_divergence_revision_inserts_reason_hash_divergence():
    conn = _FakeConnection()
    await write_hash_divergence_revision(
        conn,
        raw_message_id=42,
        conversation_id="11111111-1111-1111-1111-111111111111",
        dedup_key="m1",
        existing_content_hash="a" * 64,
        incoming_content_hash="b" * 64,
        incoming_content_masked="contenu propre",
        request_id="8f14e45f-ceea-467e-bd3e-98f37e5b5c1a",
    )
    assert len(conn.executed) == 1
    sql, params = conn.executed[0]
    assert "INSERT INTO arac.raw_message_revisions" in sql
    assert "'hash_divergence'" in sql  # reason fixé en dur (pas un paramètre)
    assert params[0] == 42
    assert params[6] == "8f14e45f-ceea-467e-bd3e-98f37e5b5c1a"
    assert params[7] == "ingest_v2"  # actor par défaut


async def test_write_hash_divergence_revision_masks_secret_via_mask_recursive():
    """BREAK : un contenu édité contenant un secret -> `incoming_content_masked`
    passé par `mask_recursive` avant écriture (défense en profondeur)."""
    conn = _FakeConnection()
    secret_content = "voici ma cle sk-ant-abcdef1234567890"
    await write_hash_divergence_revision(
        conn,
        raw_message_id=1,
        conversation_id="11111111-1111-1111-1111-111111111111",
        dedup_key="m1",
        existing_content_hash="a" * 64,
        incoming_content_hash="b" * 64,
        incoming_content_masked=secret_content,
        request_id=str(uuid.uuid4()),
    )
    _, params = conn.executed[0]
    stored_masked = params[5]
    assert "sk-ant-" not in stored_masked
    assert stored_masked == mask_recursive(secret_content)


# ============================================================================
# _OUTCOME_BY_STATUS — correctif 1 : refused_403 désormais câblé
# ============================================================================


def test_outcome_by_status_now_covers_403():
    assert _OUTCOME_BY_STATUS[403] == "refused_403"


def test_0021_migration_contains_refused_403_in_check():
    """Test statique (correctif 1) : la migration 0021 (pas encore appliquée
    en prod) doit contenir `refused_403` dans le CHECK `outcome`."""
    path = os.path.join(_MIGRATIONS_DIR, "0021_d063_ingest_receipts.py")
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "'refused_403'" in content


def test_router_no_deviation_comment_left_for_403():
    """La déviation documentée (403 sans reçu) doit avoir disparu du routeur
    après le correctif — sinon la doc mentirait sur le comportement réel."""
    src = _router_source()
    assert "n'a PAS d'entrée `refused_403`" not in src


# ============================================================================
# Pré-fetch — 1 SEUL SELECT par batch (jamais 1 par message)
# ============================================================================


def test_prefetch_select_appears_once_before_message_loop():
    src = _router_source()
    needle = "SELECT dedup_key, id, content_hash FROM arac.raw_messages"
    assert src.count(needle) == 1
    assert src.index(needle) < src.index("for m in batch.messages:")


# ============================================================================
# Tests DB docker (SKIP proprement si Docker absent, cf tests/conftest.py
# `db_admin`/`db_session`). Non exécutés sur cette machine (Docker absent) ;
# structurés pour tourner via `make test-db`.
# ============================================================================


async def test_live_reemit_modified_content_creates_one_revision_and_increments_receipt(
    db_session, monkeypatch
):
    """Acceptance : réémettre un message sous uuid stable avec content
    modifié -> 1 row `raw_message_revisions`, `hash_divergences=1` au reçu,
    `raw_messages` INCHANGÉ (aucun UPDATE)."""
    import json as _json

    import app.routers.ingest_v2 as ingest_v2_mod

    monkeypatch.setenv("ARAC_INGEST_ALLOWED_NODES", "test-node")
    conv_uid = f"test-divergence-{uuid.uuid4()}"

    async def _post(content: str):
        body = _json.dumps(
            _payload(conv_uid, [{"message_uuid": "stable-1", "role": "user", "content": content}])
        ).encode("utf-8")
        request = _fake_request(headers={"X-ARAC-Node-Id": "test-node"}, body=body)
        response = _fake_response()
        return await ingest_v2_mod.ingest_messages(request=request, response=response, db=db_session)

    out1 = await _post("version initiale")
    assert out1.inserted == 1
    assert out1.duplicates == 0

    out2 = await _post("version modifiée")
    assert out2.inserted == 0
    assert out2.duplicates == 1

    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT content, count(*) FROM arac.raw_messages rm "
            "JOIN arac.conversations c ON c.id = rm.conversation_id "
            "WHERE c.conversation_uid = %s GROUP BY content",
            (conv_uid,),
        )
        rows = await cur.fetchall()
    assert rows == [("version initiale", 1)]  # raw_messages INCHANGÉ

    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT reason, existing_content_hash, incoming_content_hash, actor "
            "FROM arac.raw_message_revisions rmr "
            "JOIN arac.conversations c ON c.id = rmr.conversation_id "
            "WHERE c.conversation_uid = %s",
            (conv_uid,),
        )
        revisions = await cur.fetchall()
    assert len(revisions) == 1
    reason, existing_hash, incoming_hash, actor = revisions[0]
    assert reason == "hash_divergence"
    assert existing_hash != incoming_hash
    assert actor == "ingest_v2"

    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT hash_divergences FROM arac.ingest_receipts "
            "WHERE conversation_uid = %s ORDER BY id DESC LIMIT 1",
            (conv_uid,),
        )
        (hash_divergences,) = await cur.fetchone()
    assert hash_divergences == 1


async def test_live_reemit_identical_content_creates_no_revision(db_session, monkeypatch):
    """Acceptance : réémettre à l'identique -> 0 révision, duplicates incrémenté."""
    import json as _json

    import app.routers.ingest_v2 as ingest_v2_mod

    monkeypatch.setenv("ARAC_INGEST_ALLOWED_NODES", "test-node")
    conv_uid = f"test-identical-{uuid.uuid4()}"

    async def _post():
        body = _json.dumps(
            _payload(conv_uid, [{"message_uuid": "stable-1", "role": "user", "content": "même contenu"}])
        ).encode("utf-8")
        request = _fake_request(headers={"X-ARAC-Node-Id": "test-node"}, body=body)
        response = _fake_response()
        return await ingest_v2_mod.ingest_messages(request=request, response=response, db=db_session)

    out1 = await _post()
    assert out1.inserted == 1
    out2 = await _post()
    assert out2.inserted == 0
    assert out2.duplicates == 1

    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT count(*) FROM arac.raw_message_revisions rmr "
            "JOIN arac.conversations c ON c.id = rmr.conversation_id "
            "WHERE c.conversation_uid = %s",
            (conv_uid,),
        )
        (n_rev,) = await cur.fetchone()
    assert n_rev == 0

    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT hash_divergences FROM arac.ingest_receipts "
            "WHERE conversation_uid = %s ORDER BY id DESC LIMIT 1",
            (conv_uid,),
        )
        (hash_divergences,) = await cur.fetchone()
    assert hash_divergences == 0


async def test_live_uuid_null_content_changed_is_new_message_not_a_false_divergence(
    db_session, monkeypatch
):
    """Acceptance : uuid NULL + contenu changé -> nouveau `dedup_key`
    (`'h:'||hash`) -> nouveau message inséré, PAS une divergence."""
    import json as _json

    import app.routers.ingest_v2 as ingest_v2_mod

    monkeypatch.setenv("ARAC_INGEST_ALLOWED_NODES", "test-node")
    conv_uid = f"test-uuid-null-{uuid.uuid4()}"

    async def _post(content: str):
        body = _json.dumps(
            _payload(conv_uid, [{"role": "user", "content": content}])  # pas de message_uuid
        ).encode("utf-8")
        request = _fake_request(headers={"X-ARAC-Node-Id": "test-node"}, body=body)
        response = _fake_response()
        return await ingest_v2_mod.ingest_messages(request=request, response=response, db=db_session)

    out1 = await _post("premier contenu")
    assert out1.inserted == 1
    out2 = await _post("deuxieme contenu")
    assert out2.inserted == 1  # nouveau message (dedup_key différent)
    assert out2.duplicates == 0

    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT count(*) FROM arac.raw_message_revisions rmr "
            "JOIN arac.conversations c ON c.id = rmr.conversation_id "
            "WHERE c.conversation_uid = %s",
            (conv_uid,),
        )
        (n_rev,) = await cur.fetchone()
    assert n_rev == 0


async def test_live_n_duplicates_trigger_exactly_one_prefetch_select(db_session, monkeypatch):
    """Acceptance : N duplicates dans le MÊME batch -> 1 SEUL SELECT de
    pré-fetch (jamais 1 par message)."""
    import json as _json

    import psycopg

    import app.routers.ingest_v2 as ingest_v2_mod

    monkeypatch.setenv("ARAC_INGEST_ALLOWED_NODES", "test-node")
    conv_uid = f"test-prefetch-{uuid.uuid4()}"
    needle = "SELECT dedup_key, id, content_hash FROM arac.raw_messages"

    async def _post(messages):
        body = _json.dumps(_payload(conv_uid, messages)).encode("utf-8")
        request = _fake_request(headers={"X-ARAC-Node-Id": "test-node"}, body=body)
        response = _fake_response()
        return await ingest_v2_mod.ingest_messages(request=request, response=response, db=db_session)

    # 1er POST : insère m1 (référence pour les duplicates du 2e POST).
    await _post([{"message_uuid": "m1", "role": "user", "content": "v1"}])

    calls: list[str] = []
    original_execute = psycopg.AsyncCursor.execute

    async def _counting_execute(self, query, params=None, **kwargs):
        sql = query if isinstance(query, str) else None
        if sql and needle in sql:
            calls.append(sql)
        return await original_execute(self, query, params, **kwargs)

    monkeypatch.setattr(psycopg.AsyncCursor, "execute", _counting_execute)

    # 2e POST : 5 duplicates de m1 dans le MÊME batch.
    out = await _post([{"message_uuid": "m1", "role": "user", "content": "v1"}] * 5)

    assert out.duplicates == 5
    assert len(calls) == 1


async def test_live_fifty_edits_yield_fifty_revisions_and_zero_mutation(db_session, monkeypatch):
    """BREAK : éditer le même message 50x -> 50 révisions, 0 mutation de
    `raw_messages` (contenu original inchangé, toujours 1 seule row)."""
    import json as _json

    import app.routers.ingest_v2 as ingest_v2_mod

    monkeypatch.setenv("ARAC_INGEST_ALLOWED_NODES", "test-node")
    conv_uid = f"test-50edits-{uuid.uuid4()}"

    async def _post(content: str):
        body = _json.dumps(
            _payload(conv_uid, [{"message_uuid": "stable", "role": "user", "content": content}])
        ).encode("utf-8")
        request = _fake_request(headers={"X-ARAC-Node-Id": "test-node"}, body=body)
        response = _fake_response()
        return await ingest_v2_mod.ingest_messages(request=request, response=response, db=db_session)

    out0 = await _post("version originale")
    assert out0.inserted == 1

    for i in range(50):
        out = await _post(f"edition numero {i}")
        assert out.inserted == 0
        assert out.duplicates == 1

    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT content, count(*) FROM arac.raw_messages rm "
            "JOIN arac.conversations c ON c.id = rm.conversation_id "
            "WHERE c.conversation_uid = %s GROUP BY content",
            (conv_uid,),
        )
        rows = await cur.fetchall()
    assert rows == [("version originale", 1)]  # 0 mutation

    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT count(*) FROM arac.raw_message_revisions rmr "
            "JOIN arac.conversations c ON c.id = rmr.conversation_id "
            "WHERE c.conversation_uid = %s",
            (conv_uid,),
        )
        (n_rev,) = await cur.fetchone()
    assert n_rev == 50


async def test_live_mixed_batch_counts_new_duplicate_and_divergent_exactly(db_session, monkeypatch):
    """BREAK : batch mixte (nouveau + duplicate identique + duplicate
    divergent) dans UN SEUL POST -> compteurs EXACTS."""
    import json as _json

    import app.routers.ingest_v2 as ingest_v2_mod

    monkeypatch.setenv("ARAC_INGEST_ALLOWED_NODES", "test-node")
    conv_uid = f"test-mixed-{uuid.uuid4()}"

    async def _post(messages):
        body = _json.dumps(_payload(conv_uid, messages)).encode("utf-8")
        request = _fake_request(headers={"X-ARAC-Node-Id": "test-node"}, body=body)
        response = _fake_response()
        return await ingest_v2_mod.ingest_messages(request=request, response=response, db=db_session)

    out1 = await _post(
        [
            {"message_uuid": "a", "role": "user", "content": "A1"},
            {"message_uuid": "b", "role": "user", "content": "B1"},
        ]
    )
    assert out1.inserted == 2
    assert out1.duplicates == 0

    out2 = await _post(
        [
            {"message_uuid": "a", "role": "user", "content": "A1"},  # identique
            {"message_uuid": "b", "role": "user", "content": "B2"},  # divergent
            {"message_uuid": "c", "role": "user", "content": "C1"},  # nouveau
        ]
    )
    assert out2.inserted == 1
    assert out2.duplicates == 2

    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT hash_divergences FROM arac.ingest_receipts "
            "WHERE conversation_uid = %s ORDER BY id DESC LIMIT 1",
            (conv_uid,),
        )
        (hash_divergences,) = await cur.fetchone()
    assert hash_divergences == 1

    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT count(*) FROM arac.raw_message_revisions rmr "
            "JOIN arac.conversations c ON c.id = rmr.conversation_id "
            "WHERE c.conversation_uid = %s",
            (conv_uid,),
        )
        (n_rev,) = await cur.fetchone()
    assert n_rev == 1


async def test_live_intra_batch_same_dedup_key_divergent_content_creates_one_revision(
    db_session, monkeypatch
):
    """Correctif findings 6/11/32 (revue adversariale, MINEUR) : DEUX
    messages du MÊME batch (même POST), même `message_uuid`, contenu
    DIFFÉRENT. Le pré-fetch `existing_by_dedup_key` a lieu AVANT la boucle
    (conversation neuve -> map vide) : sans mise à jour de la map APRÈS le
    1er INSERT réussi, `check_hash_divergence` ne voit ni l'un ni l'autre
    pour le 2e message -> absorbé par `ON CONFLICT DO NOTHING` SANS row
    `raw_message_revisions` (viole INV-5, divergence silencieuse).
    Après correctif : 1 row `raw_messages` (le 1er gagne, jamais muté),
    1 row `raw_message_revisions` (`hash_divergence`), `hash_divergences=1`
    au reçu."""
    import json as _json

    import app.routers.ingest_v2 as ingest_v2_mod

    monkeypatch.setenv("ARAC_INGEST_ALLOWED_NODES", "test-node")
    conv_uid = f"test-intra-batch-{uuid.uuid4()}"

    body = _json.dumps(
        _payload(
            conv_uid,
            [
                {"message_uuid": "dup-1", "role": "user", "content": "version A"},
                {"message_uuid": "dup-1", "role": "user", "content": "version B"},
            ],
        )
    ).encode("utf-8")
    request = _fake_request(headers={"X-ARAC-Node-Id": "test-node"}, body=body)
    response = _fake_response()
    out = await ingest_v2_mod.ingest_messages(request=request, response=response, db=db_session)

    assert out.inserted == 1
    assert out.duplicates == 1

    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT content, count(*) FROM arac.raw_messages rm "
            "JOIN arac.conversations c ON c.id = rm.conversation_id "
            "WHERE c.conversation_uid = %s GROUP BY content",
            (conv_uid,),
        )
        rows = await cur.fetchall()
    assert rows == [("version A", 1)]  # 1er gagne, jamais muté

    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT reason, count(*) FROM arac.raw_message_revisions rmr "
            "JOIN arac.conversations c ON c.id = rmr.conversation_id "
            "WHERE c.conversation_uid = %s GROUP BY reason",
            (conv_uid,),
        )
        revisions = await cur.fetchall()
    assert revisions == [("hash_divergence", 1)]

    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT hash_divergences FROM arac.ingest_receipts "
            "WHERE conversation_uid = %s ORDER BY id DESC LIMIT 1",
            (conv_uid,),
        )
        (hash_divergences,) = await cur.fetchone()
    assert hash_divergences == 1


async def test_live_403_writes_refused_403_receipt_and_denied_event(db_admin, monkeypatch, caplog):
    """Acceptance correctif 1 : refus 403 (node non whitelisté) -> reçu
    `outcome='refused_403'` écrit + event `ingest_v2.denied` loggé."""
    import app.routers.ingest_v2 as ingest_v2_mod

    dsn = os.environ.get("DATABASE_URL_APP_TEST")
    if not dsn:
        pytest.skip("DATABASE_URL_APP_TEST absente")
    monkeypatch.setenv("DATABASE_URL_APP", dsn)
    monkeypatch.setenv("ARAC_INGEST_ALLOWED_NODES", "test-node")  # "rogue-node" absent

    req_id = str(uuid.uuid4())
    request = _fake_request(
        headers={"X-ARAC-Node-Id": "rogue-node", "X-ARAC-Request-Id": req_id},
        body=b'{"source_type": "claude_code", "conversation_uid": "x", "messages": []}',
    )
    response = _fake_response()

    try:
        caplog.set_level(logging.WARNING, logger="arac.api.ingest_v2")
        with pytest.raises(HTTPException) as exc_info:
            # `db` jamais touché avant le 403 (raise dans `_resolve_node_id`,
            # avant toute requête SQL) — None suffit ici.
            await ingest_v2_mod.ingest_messages(request=request, response=response, db=None)
        assert exc_info.value.status_code == 403

        denied = [r for r in caplog.records if r.getMessage() == "ingest_v2.denied"]
        assert any(getattr(r, "status_code", None) == 403 for r in denied)

        async with db_admin.cursor() as cur:
            await cur.execute(
                "SELECT outcome, http_status FROM arac.ingest_receipts WHERE request_id = %s",
                (req_id,),
            )
            row = await cur.fetchone()
        assert row == ("refused_403", 403)
    finally:
        async with db_admin.cursor() as cur:
            await cur.execute("DELETE FROM arac.ingest_receipts WHERE request_id = %s", (req_id,))
