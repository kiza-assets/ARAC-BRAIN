"""Tests contrat POST /v1/ingest/messages — Ingestion V2 (LOT 1).

HERMÉTIQUES : SANS DB réelle, SANS .env, SANS docker. Prouve le comportement
pur (caps, validation pydantic, calcul de hash, sémantique de réponse) en
appelant directement les fonctions PURES extraites de app/routers/ingest_v2.py
— même stratégie que tests/test_curator_backoff.py (fakes/fonctions
injectées plutôt qu'un client HTTP + DB réelle).

Source canonique du contrat : §« Contrat POST
/v1/ingest/messages » + app/schemas/ingest_v2.py.

Couverture :
  - payload valide → modèle pydantic construit.
  - caps durs (400) : batch >2000 messages, message >512 KB (avec le
    `message_uuid` fautif, ou son index si absent).
  - validation pydantic (422) : source_type invalide, role invalide,
    conversation_uid vide, champ inconnu (top-level ET par-message).
  - `compute_content_hash` : déterministe, change si le contenu change,
    reflète le contenu SANITIZED (pas le secret brut) — preuve que sanitize
    est appliqué AVANT le hash.
  - `compute_dedup_key` : fallback `'h:'+hash` quand message_uuid absent,
    sinon message_uuid tel quel.
  - `response_status_code` : 202 si inserted>0, 200 sinon.
  - `_parse_batch_json` : JSON invalide / racine non-objet → 400.

Extension — chaîne de preuve `ingest_receipts`, cf
app/services/ingest_receipts.py) :
  - `resolve_request_id` / `compute_body_sha256` / résolution des headers
    optionnels `X-ARAC-Origin-Kind` / `X-ARAC-Hops`.
  - Compteurs peuplés via le contexte pydantic (`nul_stripped`,
    `created_at_nullified`) — `_build_batch_model(payload, counts)`.
  - `mask_secrets_with_hits` (app/services/sanitize.py) : scrub_hits par
    catégorie.
  - `_OUTCOME_BY_STATUS` : mapping code HTTP -> `outcome` CHECK.
  - `write_accepted_receipt` / `write_refusal_receipt` : forme SQL +
    garantie « ne lève jamais » (refusal, best-effort).
  - Tests DB docker (SKIP proprement si `DATABASE_URL_ADMIN_TEST`/
    `DATABASE_URL_APP_TEST` absentes, cf tests/conftest.py) : atomicité
    (rollback simulé), écriture autonome, grant `arac_app` sans UPDATE.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.routers.ingest_v2 import (
    _OUTCOME_BY_STATUS,
    _build_batch_model,
    _enforce_batch_caps,
    _parse_batch_json,
    _resolve_hops,
    _resolve_origin_kind,
    _resolve_reconcile,
    compute_body_sha256,
    compute_content_hash,
    compute_dedup_key,
    resolve_request_id,
    response_status_code,
)
from app.schemas.ingest_v2 import MAX_MESSAGE_BYTES, MAX_MESSAGES_PER_BATCH, IngestV2MessageIn
from app.services.ingest_receipts import (
    _prepare_refusal_detail,
    write_accepted_receipt,
    write_refusal_receipt,
)
from app.services.sanitize import mask_recursive, mask_secrets_with_hits


# ============================================================================
# Helpers
# ============================================================================


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    """Payload de référence, conforme au contrat design (2 messages)."""
    payload: dict[str, Any] = {
        "source_type": "claude_code",
        "conversation_uid": "conv-abc-123",
        "title": "Conversation de test",
        "messages": [
            {
                "message_uuid": "m1",
                "parent_uuid": None,
                "role": "user",
                "content": "Bonjour",
                "created_at": "2026-07-02T10:00:00Z",
            },
            {
                "message_uuid": "m2",
                "parent_uuid": "m1",
                "role": "assistant",
                "content": "Salut !",
                "created_at": "2026-07-02T10:00:01Z",
            },
        ],
    }
    payload.update(overrides)
    return payload


# ============================================================================
# Payload valide
# ============================================================================


def test_valid_payload_builds_model():
    payload = _valid_payload()
    _enforce_batch_caps(payload)  # ne lève pas
    batch = _build_batch_model(payload)
    assert batch.source_type == "claude_code"
    assert batch.conversation_uid == "conv-abc-123"
    assert len(batch.messages) == 2
    assert batch.messages[0].role == "user"
    assert batch.messages[1].parent_uuid == "m1"


def test_message_without_uuid_builds_valid_model():
    """message_uuid optionnel (DB autorise NULL, cf docstring schema)."""
    payload = _valid_payload(messages=[{"role": "user", "content": "sans uuid"}])
    batch = _build_batch_model(payload)
    assert batch.messages[0].message_uuid is None


# ============================================================================
# Caps durs (400)
# ============================================================================


def test_batch_over_2000_messages_raises_400():
    payload = _valid_payload(
        messages=[{"role": "user", "content": "x"} for _ in range(MAX_MESSAGES_PER_BATCH + 1)]
    )
    with pytest.raises(HTTPException) as exc_info:
        _enforce_batch_caps(payload)
    assert exc_info.value.status_code == 400
    assert "Too many messages" in exc_info.value.detail


def test_batch_at_exactly_2000_messages_does_not_raise():
    payload = _valid_payload(
        messages=[{"role": "user", "content": "x"} for _ in range(MAX_MESSAGES_PER_BATCH)]
    )
    _enforce_batch_caps(payload)  # ne lève pas (limite inclusive)


def test_oversized_message_raises_400_with_faulty_uuid():
    big_content = "x" * (MAX_MESSAGE_BYTES + 100)
    payload = _valid_payload(
        messages=[
            {"message_uuid": "small-1", "role": "user", "content": "ok"},
            {"message_uuid": "fault-uuid-42", "role": "assistant", "content": big_content},
        ]
    )
    with pytest.raises(HTTPException) as exc_info:
        _enforce_batch_caps(payload)
    assert exc_info.value.status_code == 400
    assert "fault-uuid-42" in exc_info.value.detail


def test_oversized_message_without_uuid_reports_index():
    big_content = "y" * (MAX_MESSAGE_BYTES + 1)
    payload = _valid_payload(messages=[{"role": "user", "content": big_content}])
    with pytest.raises(HTTPException) as exc_info:
        _enforce_batch_caps(payload)
    assert exc_info.value.status_code == 400
    assert "index:0" in exc_info.value.detail


# ============================================================================
# Validation pydantic (422)
# ============================================================================


def test_invalid_source_type_raises_422():
    payload = _valid_payload(source_type="Claude-Code!!")
    with pytest.raises(HTTPException) as exc_info:
        _build_batch_model(payload)
    assert exc_info.value.status_code == 422


def test_invalid_role_raises_422():
    payload = _valid_payload(
        messages=[{"message_uuid": "m1", "role": "system", "content": "..."}]
    )
    with pytest.raises(HTTPException) as exc_info:
        _build_batch_model(payload)
    assert exc_info.value.status_code == 422


def test_blank_conversation_uid_raises_422():
    payload = _valid_payload(conversation_uid="   ")
    with pytest.raises(HTTPException) as exc_info:
        _build_batch_model(payload)
    assert exc_info.value.status_code == 422


def test_unknown_top_level_field_raises_422():
    payload = _valid_payload(unexpected_field="nope")
    with pytest.raises(HTTPException) as exc_info:
        _build_batch_model(payload)
    assert exc_info.value.status_code == 422


def test_unknown_message_field_raises_422():
    payload = _valid_payload(messages=[{"role": "user", "content": "hi", "bogus": True}])
    with pytest.raises(HTTPException) as exc_info:
        _build_batch_model(payload)
    assert exc_info.value.status_code == 422


# ============================================================================
# content_hash (déterministe, sanitize appliqué avant)
# ============================================================================


def test_content_hash_is_deterministic():
    h1 = compute_content_hash("user", "bonjour", "2026-07-02T10:00:00Z")
    h2 = compute_content_hash("user", "bonjour", "2026-07-02T10:00:00Z")
    assert h1 == h2
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)


def test_content_hash_changes_with_content():
    h1 = compute_content_hash("user", "bonjour", None)
    h2 = compute_content_hash("user", "bonsoir", None)
    assert h1 != h2


def test_content_hash_changes_with_created_at():
    h1 = compute_content_hash("user", "bonjour", "2026-07-02T10:00:00Z")
    h2 = compute_content_hash("user", "bonjour", "2026-07-02T10:00:01Z")
    assert h1 != h2


def test_hash_reflects_sanitized_content_not_raw_secret():
    """Preuve pipeline : mask_recursive AVANT compute_content_hash (router)."""
    raw_secret_content = "voici ma cle sk-ant-abcdef1234567890"
    sanitized = mask_recursive(raw_secret_content)
    assert "sk-ant-" not in sanitized

    hash_on_sanitized = compute_content_hash("user", sanitized, None)
    hash_on_raw = compute_content_hash("user", raw_secret_content, None)
    assert hash_on_sanitized != hash_on_raw

    # Recalcul idempotent : le hash stocké DOIT être celui du sanitized,
    # jamais celui du secret brut.
    assert hash_on_sanitized == compute_content_hash("user", mask_recursive(raw_secret_content), None)


# ============================================================================
# dedup_key (fallback hash quand message_uuid absent)
# ============================================================================


def test_dedup_key_fallback_when_uuid_absent():
    content_hash = compute_content_hash("user", "bonjour", None)
    key = compute_dedup_key(None, content_hash)
    assert key == f"h:{content_hash}"


def test_dedup_key_uses_message_uuid_when_present():
    content_hash = compute_content_hash("user", "bonjour", None)
    key = compute_dedup_key("msg-uuid-1", content_hash)
    assert key == "msg-uuid-1"


# ============================================================================
# Sémantique de réponse (202 vs 200)
# ============================================================================


def test_response_status_202_when_inserted():
    assert response_status_code(1) == 202
    assert response_status_code(5) == 202


def test_response_status_200_when_no_insert():
    assert response_status_code(0) == 200


# ============================================================================
# Parsing JSON (body décompressé — pas du NDJSON, cf V1)
# ============================================================================


def test_parse_batch_json_invalid_json_raises_400():
    with pytest.raises(HTTPException) as exc_info:
        _parse_batch_json(b"{not valid json")
    assert exc_info.value.status_code == 400


def test_parse_batch_json_non_object_root_raises_400():
    with pytest.raises(HTTPException) as exc_info:
        _parse_batch_json(b"[1, 2, 3]")
    assert exc_info.value.status_code == 400


def test_parse_batch_json_valid_object_roundtrips():
    parsed = _parse_batch_json(b'{"source_type": "claude_code", "conversation_uid": "x", "messages": []}')
    assert parsed["source_type"] == "claude_code"
    assert parsed["messages"] == []


# ---------------------------------------------------------------------------
# Validators défensifs (revue adversariale 2026-07-03 : S6, M2)
# ---------------------------------------------------------------------------


def test_blank_message_uuid_normalized_to_none():
    """S6 : uuid vide/blanc -> None, sinon dedup_key='' partagé par des
    messages distincts -> le second serait silencieusement avalé."""
    from app.schemas.ingest_v2 import IngestV2MessageIn

    for raw in ("", "   ", "\t"):
        m = IngestV2MessageIn(message_uuid=raw, role="user", content="x")
        assert m.message_uuid is None
    m = IngestV2MessageIn(message_uuid=" abc ", role="user", content="x")
    assert m.message_uuid == "abc"


def test_unparseable_created_at_normalized_to_none_valid_kept_verbatim():
    """M2 : timestamp non parsable -> None (jamais 500 + rollback batch) ;
    timestamp VALIDE renvoyé NON reformaté (stabilité du content_hash)."""
    from app.schemas.ingest_v2 import IngestV2MessageIn

    bad = IngestV2MessageIn(role="user", content="x", created_at="pas-une-date")
    assert bad.created_at is None
    kept = "2026-07-03T17:01:43.123Z"
    good = IngestV2MessageIn(role="user", content="x", created_at=kept)
    assert good.created_at == kept


def test_gzip_bomb_rejected_413_before_full_materialization():
    """C3 : un gzip très répétitif (bombe) doit être coupé PENDANT la
    décompression streaming (413), jamais matérialisé en entier."""
    import gzip as _gzip

    from app.routers.ingest import _decompress_if_gzip

    bomb = _gzip.compress(b"A" * (8 * 1024 * 1024))  # 8 MB -> ~8 KB gzip
    with pytest.raises(HTTPException) as exc_info:
        _decompress_if_gzip(bomb, max_decompressed=1024 * 1024)
    assert exc_info.value.status_code == 413
    # Un body légitime sous le plafond passe inchangé.
    ok = _gzip.compress(b'{"k": 1}')
    assert _decompress_if_gzip(ok, max_decompressed=1024 * 1024) == b'{"k": 1}'


# ============================================================================
# chaîne de preuve ingest_receipts (HERMÉTIQUE, sans DB)
# ============================================================================

# ---------------------------------------------------------------------------
# request_id / body_sha256 / headers optionnels (origin_kind, hops)
# ---------------------------------------------------------------------------


def test_resolve_request_id_echoes_valid_header():
    valid = "8f14e45f-ceea-467e-bd3e-98f37e5b5c1a"
    assert resolve_request_id(valid) == valid


def test_resolve_request_id_generates_when_header_absent():
    generated = resolve_request_id(None)
    # doit être un uuid valide (round-trip sans lever).
    assert str(uuid.UUID(generated)) == generated


def test_resolve_request_id_generates_when_header_invalid():
    generated = resolve_request_id("pas-un-uuid")
    assert generated != "pas-un-uuid"
    assert str(uuid.UUID(generated)) == generated


def test_compute_body_sha256_matches_hashlib_and_is_deterministic():
    import hashlib

    body = b'{"source_type": "claude_code", "conversation_uid": "x", "messages": []}'
    assert compute_body_sha256(body) == hashlib.sha256(body).hexdigest()
    assert compute_body_sha256(body) == compute_body_sha256(body)
    assert compute_body_sha256(body) != compute_body_sha256(body + b" ")


def test_resolve_origin_kind_from_header_or_none():
    req_with = SimpleNamespace(headers={"X-ARAC-Origin-Kind": "jsonl_export"})
    assert _resolve_origin_kind(req_with) == "jsonl_export"
    req_blank = SimpleNamespace(headers={"X-ARAC-Origin-Kind": "   "})
    assert _resolve_origin_kind(req_blank) is None
    req_absent = SimpleNamespace(headers={})
    assert _resolve_origin_kind(req_absent) is None


def test_resolve_hops_valid_invalid_or_absent():
    assert _resolve_hops(SimpleNamespace(headers={"X-ARAC-Hops": "2"})) == 2
    assert _resolve_hops(SimpleNamespace(headers={"X-ARAC-Hops": "0"})) == 0
    assert _resolve_hops(SimpleNamespace(headers={"X-ARAC-Hops": "-1"})) is None
    assert _resolve_hops(SimpleNamespace(headers={"X-ARAC-Hops": "bogus"})) is None
    assert _resolve_hops(SimpleNamespace(headers={})) is None


def test_resolve_reconcile_accepts_1_and_true_case_insensitive():
    """Findings 3/8/16/30 (revue adversariale) : header `X-ARAC-Reconcile`
    coordination FIX-C — nom EXACT, valeurs '1'/'true' insensibles à la
    casse -> True, tout le reste (absent, '0', 'false', 'yes') -> False,
    jamais 400/422 (même doctrine best-effort que `_resolve_origin_kind`/
    `_resolve_hops`)."""
    assert _resolve_reconcile(SimpleNamespace(headers={"X-ARAC-Reconcile": "1"})) is True
    assert _resolve_reconcile(SimpleNamespace(headers={"X-ARAC-Reconcile": "true"})) is True
    assert _resolve_reconcile(SimpleNamespace(headers={"X-ARAC-Reconcile": "TRUE"})) is True
    assert _resolve_reconcile(SimpleNamespace(headers={"X-ARAC-Reconcile": " True "})) is True
    assert _resolve_reconcile(SimpleNamespace(headers={"X-ARAC-Reconcile": "0"})) is False
    assert _resolve_reconcile(SimpleNamespace(headers={"X-ARAC-Reconcile": "false"})) is False
    assert _resolve_reconcile(SimpleNamespace(headers={"X-ARAC-Reconcile": "yes"})) is False
    assert _resolve_reconcile(SimpleNamespace(headers={})) is False


# ---------------------------------------------------------------------------
# NUL-strip + compteurs (contexte pydantic) — jamais 422, jamais 500
# ---------------------------------------------------------------------------


def test_nul_bytes_stripped_and_counted_via_build_batch_model():
    counts = {"nul_stripped": 0, "created_at_nullified": 0}
    payload = _valid_payload(
        messages=[{"message_uuid": "m1", "role": "user", "content": "avant\x00après"}]
    )
    batch = _build_batch_model(payload, counts)
    assert batch.messages[0].content == "avantaprès"
    assert counts["nul_stripped"] == 1
    assert counts["created_at_nullified"] == 0


def test_nul_strip_without_counts_dict_still_strips_but_does_not_count():
    """counts=None (défaut) : les tests unitaires directs du modèle ne
    crashent pas — le strip a lieu, seul le comptage est absent."""
    payload = _valid_payload(messages=[{"role": "user", "content": "a\x00b\x00c"}])
    batch = _build_batch_model(payload)  # pas de counts
    assert batch.messages[0].content == "abc"


def test_nul_strip_hash_idempotent_on_replay():
    """Le hash est calculé sur le contenu STRIPPÉ — rejouer le même batch
    (avec ou sans NUL) donne le même hash, preuve d'idempotence."""
    counts = {"nul_stripped": 0, "created_at_nullified": 0}
    payload = _valid_payload(messages=[{"role": "user", "content": "x\x00y"}])
    batch = _build_batch_model(payload, counts)
    h1 = compute_content_hash(batch.messages[0].role, batch.messages[0].content, None)
    # Rejeu : le client renvoie le contenu déjà strippé (cas réel : le même
    # contenu source, réingéré).
    replay_payload = _valid_payload(messages=[{"role": "user", "content": "xy"}])
    replay_batch = _build_batch_model(replay_payload)
    h2 = compute_content_hash(replay_batch.messages[0].role, replay_batch.messages[0].content, None)
    assert h1 == h2


def test_created_at_nullified_counted_only_when_unparseable():
    """Un created_at déjà absent/blanc côté client n'est PAS compté (rien
    n'a été « guéri ») ; seule la nullification PAR ÉCHEC DE PARSE l'est."""
    counts = {"nul_stripped": 0, "created_at_nullified": 0}
    payload = _valid_payload(
        messages=[
            {"role": "user", "content": "a", "created_at": "pas-une-date"},
            {"role": "user", "content": "b", "created_at": None},
            {"role": "user", "content": "c"},
        ]
    )
    batch = _build_batch_model(payload, counts)
    assert batch.messages[0].created_at is None
    assert batch.messages[1].created_at is None
    assert batch.messages[2].created_at is None
    assert counts["created_at_nullified"] == 1


# ---------------------------------------------------------------------------
# mask_secrets_with_hits — scrub_hits par catégorie (ingest_receipts)
# ---------------------------------------------------------------------------


def test_mask_secrets_with_hits_reports_category_and_masks():
    masked, hits = mask_secrets_with_hits("voici ma cle sk-ant-abcdef1234567890")
    assert "sk-ant-" not in masked
    assert hits == {"anthropic-key": 1}


def test_mask_secrets_with_hits_no_hits_on_clean_text():
    masked, hits = mask_secrets_with_hits("bonjour, rien à cacher ici")
    assert masked == "bonjour, rien à cacher ici"
    assert hits == {}


def test_mask_secrets_with_hits_aggregates_multiple_categories():
    text = "token=ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 et password=hunter2hunter2"
    masked, hits = mask_secrets_with_hits(text)
    assert hits.get("token") == 1
    assert hits.get("password") == 1
    assert "hunter2hunter2" not in masked


# ---------------------------------------------------------------------------
# _OUTCOME_BY_STATUS — mapping code HTTP -> outcome CHECK (migration 0021)
# ---------------------------------------------------------------------------


def test_outcome_by_status_covers_required_codes():
    assert _OUTCOME_BY_STATUS == {
        400: "refused_400",
        403: "refused_403",
        413: "refused_413",
        422: "refused_422",
        409: "refused_409",
        429: "rate_limited_429",
    }
    # 403 (whitelist/mismatch, réutilisé du router legacy) a désormais sa
    # propre entrée (correctif : migration 0021 corrigée avant
    # application prod pour inclure `refused_403` dans le CHECK outcome).
    assert 403 in _OUTCOME_BY_STATUS


# ---------------------------------------------------------------------------
# Régression statique : title COALESCE (premier conservé) + was_masked câblé
# ---------------------------------------------------------------------------


def _router_source() -> str:
    import inspect

    import app.routers.ingest_v2 as ingest_v2_mod

    return inspect.getsource(ingest_v2_mod)


def test_title_upsert_keeps_first_title_not_the_latest():
    """Bug d'écrasement corrigé : le PREMIER titre est
    conservé, EXCLUDED pris seulement si l'existant est NULL."""
    src = _router_source()
    assert "title = COALESCE(arac.conversations.title, EXCLUDED.title)" in src
    assert "title = COALESCE(EXCLUDED.title, arac.conversations.title)" not in src


def test_was_masked_column_wired_into_raw_messages_insert():
    src = _router_source()
    assert "content_hash, msg_created_at, node_id, was_masked)" in src
    assert "was_masked" in src


# ---------------------------------------------------------------------------
# write_accepted_receipt / write_refusal_receipt — forme SQL + garanties
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Cursor factice : capture (sql, params) sans toucher à une vraie DB."""

    def __init__(self, sink: list[tuple[str, tuple]]):
        self._sink = sink

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def execute(self, sql: str, params: tuple = ()):
        self._sink.append((sql, params))


class _FakeConnection:
    """Connexion factice (pool app) : `cursor()` retourne un `_FakeCursor`
    partageant le même sink — utilisé pour `write_accepted_receipt` (pas de
    connexion autonome, cf app/services/ingest_receipts.py)."""

    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []

    def cursor(self):
        return _FakeCursor(self.executed)


async def test_write_accepted_receipt_inserts_outcome_accepted_in_provided_conn():
    conn = _FakeConnection()
    await write_accepted_receipt(
        conn,
        request_id="8f14e45f-ceea-467e-bd3e-98f37e5b5c1a",
        node_id="test-node",
        source_type="claude_code",
        conversation_uid="conv-1",
        http_status=202,
        received=2,
        inserted=2,
        duplicates=0,
        sensor_version="ingest_v2/d063",
    )
    assert len(conn.executed) == 1
    sql, params = conn.executed[0]
    assert "INSERT INTO arac.ingest_receipts" in sql
    assert "'accepted'" in sql  # outcome fixé en dur (pas un paramètre)
    assert params[0] == "8f14e45f-ceea-467e-bd3e-98f37e5b5c1a"
    assert params[1] == "test-node"


async def test_write_accepted_receipt_reconcile_column_wired(monkeypatch):
    """Findings 3/8/16/30 (revue adversariale, MAJEUR) : `reconcile` (colonne
    existante migration 0021, jamais posée avant ce correctif) doit désormais
    apparaître dans la liste de colonnes de l'INSERT ET porter la valeur
    passée — défaut `False` si non fourni (rétrocompatible)."""
    conn_default = _FakeConnection()
    await write_accepted_receipt(
        conn_default,
        request_id="8f14e45f-ceea-467e-bd3e-98f37e5b5c1a",
        node_id="test-node",
        source_type="claude_code",
        conversation_uid="conv-1",
        http_status=202,
        received=1,
        inserted=1,
        duplicates=0,
    )
    sql, params = conn_default.executed[0]
    assert "reconcile" in sql
    # index 14 : `outcome` (colonne 5 du SQL) est fixé en dur ('accepted',
    # jamais un %s) donc absent de `params` — décalage de 1 vs la liste de
    # colonnes du SQL, cf `body_sha256, reconcile,` juste avant `scrub_hits`.
    assert params[14] is False

    conn_true = _FakeConnection()
    await write_accepted_receipt(
        conn_true,
        request_id="8f14e45f-ceea-467e-bd3e-98f37e5b5c1a",
        node_id="test-node",
        source_type="claude_code",
        conversation_uid="conv-1",
        http_status=200,
        received=0,
        inserted=0,
        duplicates=0,
        reconcile=True,
    )
    _, params2 = conn_true.executed[0]
    assert params2[14] is True


def test_prepare_refusal_detail_masks_email_alongside_secrets():
    """Finding 15 (revue adversariale, MINEUR) : `_prepare_refusal_detail`
    doit masquer les e-mails EN PLUS des secrets (13 regex) — jusqu'ici
    seuls les secrets étaient masqués, une adresse restait en clair dans
    `ingest_receipts.refusal_detail` (aligné sur `_mask_emails` de
    `agents/cortex/review_queue.py`)."""
    detail = "conversation_uid invalide pour alice@example.com et sk-ant-abcdef1234567890"
    masked = _prepare_refusal_detail(detail)
    assert "alice@example.com" not in masked
    assert "[REDACTED:email]" in masked
    assert "sk-ant-" not in masked
    assert "[REDACTED:anthropic-key]" in masked


async def test_write_refusal_receipt_never_raises_when_connect_fails(monkeypatch):
    """Best-effort : un échec de connexion à l'écriture du reçu de refus ne
    doit JAMAIS remonter (masquerait l'erreur d'origine 400/413/422/409/429/500)."""
    import psycopg

    from app.services import ingest_receipts as ir_mod

    async def _boom(*args, **kwargs):
        raise OSError("DB indisponible")

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _boom)

    # Ne lève PAS, même si la connexion échoue.
    await write_refusal_receipt(
        dsn="postgres://fake:fake@localhost:5433/fake",
        request_id="8f14e45f-ceea-467e-bd3e-98f37e5b5c1a",
        outcome="refused_400",
        http_status=400,
        refusal_detail="Invalid Content-Length",
    )
    assert ir_mod is not None  # import utilisé (sanity, pas de warning lint)


async def test_write_refusal_receipt_never_raises_without_dsn(monkeypatch):
    """Sans DSN (ni param ni DATABASE_URL_APP env) : skip loggé, jamais de crash."""
    monkeypatch.delenv("DATABASE_URL_APP", raising=False)
    await write_refusal_receipt(
        dsn=None,
        request_id="8f14e45f-ceea-467e-bd3e-98f37e5b5c1a",
        outcome="refused_422",
        http_status=422,
        refusal_detail="quelque chose",
    )


async def test_write_refusal_receipt_masks_and_truncates_detail(monkeypatch):
    """refusal_detail : masqué (mask_recursive) ET tronqué à ~500 caractères
    avant d'atteindre `ingest_receipts` — jamais de brut non scrubé."""
    import psycopg

    sink: list[tuple[str, tuple]] = []

    class _Cur(_FakeCursor):
        pass

    class _Conn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        def cursor(self):
            return _Cur(sink)

    async def _fake_connect(*args, **kwargs):
        return _Conn()

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", _fake_connect)

    secret = "sk-ant-abcdef1234567890"
    long_detail = f"faux secret dans un champ invalide: {secret} " + ("x" * 600)
    await write_refusal_receipt(
        dsn="postgres://fake:fake@localhost:5433/fake",
        request_id="8f14e45f-ceea-467e-bd3e-98f37e5b5c1a",
        outcome="refused_422",
        http_status=422,
        refusal_detail=long_detail,
    )
    assert len(sink) == 1
    _, params = sink[0]
    stored_detail = params[12]  # ordre des colonnes de l'INSERT, cf ingest_receipts.py
    assert secret not in stored_detail
    assert len(stored_detail) <= 500


# ---------------------------------------------------------------------------
# Finding 14 (revue adversariale, SÉRIEUX sécurité) : le detail d'un refus ne
# doit PAS fuiter non masqué dans le log `ingest_v2.denied` — régression vs
# origin/main (la même chaîne était déjà masquée côté base, cf
# `ingest_receipts.refusal_detail` ci-dessus, mais PAS côté journald).
# ---------------------------------------------------------------------------


async def test_denied_log_masks_secret_in_detail_hermetic_400_path(monkeypatch, caplog):
    """400 cap taille message (`_enforce_batch_caps`, hermétique — AUCUNE DB
    requise, la vérification a lieu avant toute requête SQL) : un
    `message_uuid` ressemblant à un secret, embarqué dans le `detail` HTTP
    400, ne doit JAMAIS apparaître en clair dans `extra['detail']` du log
    `ingest_v2.denied` — même masquage que la row `ingest_receipts` (cf
    `_prepare_refusal_detail`)."""
    import json as _json
    import logging as _logging

    import app.routers.ingest_v2 as ingest_v2_mod

    monkeypatch.setenv("ARAC_INGEST_ALLOWED_NODES", "test-node")
    secret = "sk-ant-abcdef1234567890abcdef1234567890abcdef"
    oversized = "x" * (MAX_MESSAGE_BYTES + 10)
    body = _json.dumps(
        {
            "source_type": "claude_code",
            "conversation_uid": "conv-mask-test",
            "messages": [{"message_uuid": secret, "role": "user", "content": oversized}],
        }
    ).encode("utf-8")
    request = _fake_request(headers={"X-ARAC-Node-Id": "test-node"}, body=body)
    response = _fake_response()

    with caplog.at_level(_logging.WARNING, logger="arac.api.ingest_v2"):
        with pytest.raises(HTTPException) as exc_info:
            await ingest_v2_mod.ingest_messages(request=request, response=response, db=None)
    assert exc_info.value.status_code == 400

    denied_records = [r for r in caplog.records if r.message == "ingest_v2.denied"]
    assert len(denied_records) == 1
    logged_detail = denied_records[0].detail
    assert secret not in logged_detail
    assert "[REDACTED:anthropic-key]" in logged_detail


async def test_denied_log_masks_error_in_500_path(monkeypatch, caplog):
    """500 générique (`except Exception`) : un message d'erreur contenant un
    secret ne doit pas fuiter dans `extra['error']` du log `ingest_v2.denied`."""
    import json as _json
    import logging as _logging

    import app.routers.ingest_v2 as ingest_v2_mod

    monkeypatch.setenv("ARAC_INGEST_ALLOWED_NODES", "test-node")
    secret = "sk-ant-abcdef1234567890abcdef1234567890abcdef"

    def _boom_resolve_node_id(request):
        raise RuntimeError(f"panne inattendue, contexte: {secret}")

    monkeypatch.setattr(ingest_v2_mod, "_resolve_node_id", _boom_resolve_node_id)

    body = _json.dumps(
        {"source_type": "claude_code", "conversation_uid": "conv-mask-500", "messages": []}
    ).encode("utf-8")
    request = _fake_request(headers={"X-ARAC-Node-Id": "test-node"}, body=body)
    response = _fake_response()

    with caplog.at_level(_logging.WARNING, logger="arac.api.ingest_v2"):
        with pytest.raises(HTTPException) as exc_info:
            await ingest_v2_mod.ingest_messages(request=request, response=response, db=None)
    assert exc_info.value.status_code == 500

    denied_records = [r for r in caplog.records if r.message == "ingest_v2.denied"]
    assert len(denied_records) == 1
    logged_error = denied_records[0].error
    assert secret not in logged_error
    # La coupe est PLUS HAUTE qu'au correctif finding 14 : le message n'est
    # plus masqué, il n'est plus écrit du tout. `app.journal.raison()` rend la
    # classe de l'exception, le diagnostic PostgreSQL quand il existe, et
    # l'empreinte du message — parce que masquer les treize formes de secret
    # CONNUES laissait passer « DETAIL:  Failing row contains (…) », qui n'en
    # est aucune, et qui porte le souvenir entier (mesuré sur un cerveau vivant).
    assert logged_error.startswith("RuntimeError")
    assert "sha8:" in logged_error
    assert "panne inattendue" not in logged_error


# ============================================================================
# tests DB docker (SKIP proprement si Docker absent, cf
# tests/conftest.py `db_admin`/`db_session` — DATABASE_URL_ADMIN_TEST /
# DATABASE_URL_APP_TEST). Non exécutés sur cette machine (Docker absent) ;
# structurés pour tourner via `make test-db`.
# ============================================================================


def _fake_request(*, headers: dict[str, str], body: bytes) -> SimpleNamespace:
    async def _body() -> bytes:
        return body

    return SimpleNamespace(headers=headers, body=_body, state=SimpleNamespace())


def _fake_response() -> SimpleNamespace:
    return SimpleNamespace(headers={}, status_code=200)


async def test_live_accepted_receipt_atomic_rollback_removes_both(db_session, monkeypatch):
    """Rollback forcé (échec du reçu) DANS la transaction -> ni messages, ni
    conversation, ni reçu ne persistent (atomicité, cf app/routers/ingest_v2.py)."""
    import json as _json

    import app.routers.ingest_v2 as ingest_v2_mod

    monkeypatch.setenv("ARAC_INGEST_ALLOWED_NODES", "test-node")

    async def _boom_write_accepted(*args, **kwargs):
        raise RuntimeError("panne simulée post-INSERT (test atomicité)")

    monkeypatch.setattr(ingest_v2_mod, "write_accepted_receipt", _boom_write_accepted)

    conv_uid = f"test-atomic-{uuid.uuid4()}"
    body = _json.dumps(
        {
            "source_type": "claude_code",
            "conversation_uid": conv_uid,
            "messages": [{"role": "user", "content": "bonjour"}],
        }
    ).encode("utf-8")
    request = _fake_request(
        headers={"X-ARAC-Node-Id": "test-node"},
        body=body,
    )
    response = _fake_response()

    with pytest.raises(HTTPException) as exc_info:
        await ingest_v2_mod.ingest_messages(request=request, response=response, db=db_session)
    assert exc_info.value.status_code == 500

    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT count(*) FROM arac.conversations WHERE conversation_uid = %s",
            (conv_uid,),
        )
        (n_conv,) = await cur.fetchone()
        await cur.execute(
            "SELECT count(*) FROM arac.raw_messages rm "
            "JOIN arac.conversations c ON c.id = rm.conversation_id "
            "WHERE c.conversation_uid = %s",
            (conv_uid,),
        )
        (n_msg,) = await cur.fetchone()
    assert n_conv == 0
    assert n_msg == 0


async def test_live_reconcile_header_sets_ingest_receipts_reconcile_column(
    db_session, monkeypatch
):
    """Findings 3/8/16/30 (revue adversariale, MAJEUR) bout-en-bout : le
    header `X-ARAC-Reconcile: 1` doit peupler `ingest_receipts.reconcile =
    true` sur le reçu `accepted` — colonne existante (migration 0021) mais
    JAMAIS posée avant ce correctif (`reconcile_audit.collect_reconcile`
    trouvait donc toujours `RECONCILE_MISSING`). Un batch SANS le header
    reste à `false` (non-régression du comportement par défaut)."""
    import json as _json

    import app.routers.ingest_v2 as ingest_v2_mod

    monkeypatch.setenv("ARAC_INGEST_ALLOWED_NODES", "test-node")

    async def _post(conv_uid: str, *, reconcile_header: str | None):
        headers = {"X-ARAC-Node-Id": "test-node"}
        if reconcile_header is not None:
            headers["X-ARAC-Reconcile"] = reconcile_header
        body = _json.dumps(
            {
                "source_type": "claude_code",
                "conversation_uid": conv_uid,
                "messages": [{"role": "user", "content": "bonjour"}],
            }
        ).encode("utf-8")
        request = _fake_request(headers=headers, body=body)
        response = _fake_response()
        return await ingest_v2_mod.ingest_messages(request=request, response=response, db=db_session)

    conv_with = f"test-reconcile-hdr-{uuid.uuid4()}"
    await _post(conv_with, reconcile_header="1")
    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT reconcile FROM arac.ingest_receipts "
            "WHERE conversation_uid = %s AND outcome = 'accepted'",
            (conv_with,),
        )
        (reconcile_flag,) = await cur.fetchone()
    assert reconcile_flag is True

    conv_without = f"test-no-reconcile-hdr-{uuid.uuid4()}"
    await _post(conv_without, reconcile_header=None)
    async with db_session.cursor() as cur:
        await cur.execute(
            "SELECT reconcile FROM arac.ingest_receipts "
            "WHERE conversation_uid = %s AND outcome = 'accepted'",
            (conv_without,),
        )
        (reconcile_flag_absent,) = await cur.fetchone()
    assert reconcile_flag_absent is False


async def test_live_refusal_receipt_written_via_autonomous_connection(db_admin):
    """`write_refusal_receipt` écrit bien une row `outcome=refused_400` via
    sa propre connexion (indépendante de toute transaction applicative)."""
    import os

    dsn = os.environ.get("DATABASE_URL_APP_TEST")
    if not dsn:
        pytest.skip("DATABASE_URL_APP_TEST absente")

    req_id = str(uuid.uuid4())
    try:
        await write_refusal_receipt(
            dsn=dsn,
            request_id=req_id,
            outcome="refused_400",
            http_status=400,
            refusal_detail="Invalid Content-Length",
            node_id="test-node",
        )
        async with db_admin.cursor() as cur:
            await cur.execute(
                "SELECT outcome, http_status, node_id FROM arac.ingest_receipts "
                "WHERE request_id = %s",
                (req_id,),
            )
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == "refused_400"
        assert row[1] == 400
        assert row[2] == "test-node"
    finally:
        async with db_admin.cursor() as cur:
            await cur.execute(
                "DELETE FROM arac.ingest_receipts WHERE request_id = %s", (req_id,)
            )


async def test_live_arac_app_cannot_update_ingest_receipts(db_session):
    """Grant (migration 0021) : `arac_app` a SELECT/INSERT mais jamais
    UPDATE/DELETE sur `ingest_receipts` (immuabilité du reçu)."""
    import psycopg

    with pytest.raises(psycopg.Error):
        async with db_session.cursor() as cur:
            await cur.execute(
                "UPDATE arac.ingest_receipts SET outcome = 'accepted' WHERE false"
            )
