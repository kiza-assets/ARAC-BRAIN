"""Router ingest V2 — ingestion par-message.

Endpoint d ingestion par-message, une conversation par batch, avec curseur
de curation par watermark GLOBAL (`raw_messages.id`). Coexiste avec le
legacy `/v1/ingest/conversations` (app/routers/ingest.py) — AUCUNE table ni
route legacy modifiée par ce module.

Endpoints :
  - POST /v1/ingest/messages  → ingestion d une conversation (upsert) + N
    messages (idempotents par `dedup_key`).

Sécurité (couches superposées, RÉUTILISÉES intégralement du legacy — cf
app/routers/ingest.py) :
  1. Middleware Bearer Phase 3 (app/auth.py:bearer_middleware).
  2. Whitelist node_id via env ARAC_INGEST_ALLOWED_NODES (comma-separated) —
     `_resolve_node_id` importé tel quel du router legacy.
  3. Cohérence header X-ARAC-Node-Id vs request.state.auth_node_id.

Doctrine ARAC (anti-fabulation + defense-in-depth) :
  - Validation Pydantic v2 stricte (extra="forbid"), cf app/schemas/ingest_v2.py.
  - Caps durs HORS pydantic (400, pas 422) : body 10 MB (réutilise
    `_get_max_size`), ≤2000 messages/batch, ≤512 KB/message (avec le
    `message_uuid` fautif dans le detail).
  - `content_hash` calculé SERVEUR, APRÈS sanitize (`mask_secrets_with_hits`
    — app/services/sanitize.py, variante de `mask_recursive` qui remonte
    aussi le compte de hits par catégorie pour `ingest_receipts.scrub_hits`) :
    sha256(role \\n content \\n created_at).
  - Idempotence : `dedup_key` généré côté DB (COALESCE(message_uuid,
    'h:'||content_hash)) — `ON CONFLICT (conversation_id, dedup_key) DO NOTHING`.
  - Rate-limit : COUNT raw_messages du node sur 1h ≥ cap → 429 (garde simple
    messages/h — pas de garde batches/h séparée en V2 Lot 1).
  - Curseur de curation `curated_through_message_id` : jamais touché par cet
    endpoint (propriété exclusive du curateur v2, avancé dans la même tx que
    le POST des atomes — cf design §« Gate curateur v2 »). Lu ici en
    lecture-seule pour la réponse (`new_uncurated`).

Chaîne de preuve `ingest_receipts` (cf app/services/ingest_receipts.py) :
  - `request_id` (header `X-ARAC-Request-Id` ou généré serveur) échoué dans
    le corps ET le header de réponse, quelle que soit l'issue (accepté ou
    refusé).
  - Reçu `outcome='accepted'` écrit ATOMIQUEMENT dans la même transaction
    que l'upsert conversation + INSERT messages (rollback de l'un = rollback
    de tout, y compris le reçu).
  - Tout refus (400/403/413/422/409/429) et toute erreur inattendue (500)
    écrit un reçu en connexion AUTONOME (best-effort, ne masque jamais
    l'erreur d'origine) + un `logger.warning(event="ingest_v2.denied")`
    structuré.

Chaîne de preuve `raw_message_revisions` (cf
app/services/raw_message_revisions.py) :
  - 1 SELECT de pré-fetch PAR BATCH (`dedup_key -> (id, content_hash)`) sur
    la conversation, avant la boucle d'INSERT — jamais un SELECT par message.
  - Sur un duplicate (`ON CONFLICT DO NOTHING` sans `RETURNING`), le hash
    entrant est comparé au hash déjà en base pour ce `dedup_key`
    (`check_hash_divergence`, fonction PURE) : divergence -> row append-only
    dans `arac.raw_message_revisions` (`reason='hash_divergence'`) + incrément
    `ingest_receipts.hash_divergences` — AUCUN UPDATE de `arac.raw_messages`,
    jamais.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg import AsyncConnection

from app.db import get_db
from app.journal import raison
from app.routers.ingest import _decompress_if_gzip, _get_max_size, _resolve_node_id
from app.schemas.ingest_v2 import (
    MAX_MESSAGE_BYTES,
    MAX_MESSAGES_PER_BATCH,
    CaptureManifestIn,
    CaptureManifestOut,
    IngestV2BatchIn,
    IngestV2Out,
)
from app.services.ingest_receipts import (
    _prepare_refusal_detail,
    write_accepted_receipt,
    write_refusal_receipt,
)
from app.services.raw_message_revisions import write_hash_divergence_revision
from app.services.sanitize import mask_secrets_with_hits


router = APIRouter()
_logger = logging.getLogger("arac.api.ingest_v2")


# ============================================================================
# Constantes
# ============================================================================

_DEFAULT_MSG_RATE_LIMIT_PER_HOUR = 20000
_ENV_MSG_RATE_LIMIT = "ARAC_INGEST_V2_MSG_RATE_LIMIT_PER_HOUR"

_HEADER_REQUEST_ID = "X-ARAC-Request-Id"
_HEADER_ORIGIN_KIND = "X-ARAC-Origin-Kind"
_HEADER_HOPS = "X-ARAC-Hops"
# Header émis par les exporteurs en mode `--reconcile` (FIX-C, coordination
# de nom EXACT avec ce lot serveur, cf revue adversariale findings 3/8/16/30)
# — valeur '1' ou 'true' (insensible à la casse) -> `ingest_receipts.reconcile`.
_HEADER_RECONCILE = "X-ARAC-Reconcile"

# Version du routeur, consignée dans `ingest_receipts.sensor_version` — permet au futur reconcile_audit de distinguer les reçus émis
# avant/après une évolution du contrat.
_SENSOR_VERSION = "ingest_v2/d063"

# outcome CHECK (migration 0021) atteignable depuis les raises de CE routeur.
# 403 (whitelist/mismatch node, cf `_resolve_node_id` réutilisé du legacy) a
# désormais sa propre entrée `refused_403` (correctif : absente
# du CHECK initial de la migration 0021, corrigée avant application prod —
# cf docstring migration). Le log `ingest_v2.denied` reste émis pour TOUT
# refus, couvert ou non par cette map (cf handler générique).
_OUTCOME_BY_STATUS: dict[int, str] = {
    400: "refused_400",
    403: "refused_403",
    413: "refused_413",
    422: "refused_422",
    409: "refused_409",
    429: "rate_limited_429",
}


# ============================================================================
# Helpers config
# ============================================================================


def _get_msg_rate_limit() -> int:
    """Lit ARAC_INGEST_V2_MSG_RATE_LIMIT_PER_HOUR (defaults 20000).

    Même pattern que `_get_rate_limit` du router legacy (app/routers/ingest.py),
    re-clé sur les MESSAGES (pas les batches) — cf design §Contrat.
    """
    raw = os.environ.get(_ENV_MSG_RATE_LIMIT)
    if not raw:
        return _DEFAULT_MSG_RATE_LIMIT_PER_HOUR
    try:
        v = int(raw)
        return v if v > 0 else _DEFAULT_MSG_RATE_LIMIT_PER_HOUR
    except ValueError:
        return _DEFAULT_MSG_RATE_LIMIT_PER_HOUR


# ============================================================================
# Helpers body / validation (fonctions PURES — testables sans DB)
# ============================================================================


def _parse_batch_json(decompressed: bytes) -> dict[str, Any]:
    """Parse le body décompressé comme UN objet JSON (pas du NDJSON, cf V1).

    Lève 400 si UTF-8 invalide, JSON malformé, ou racine non-objet.
    """
    try:
        text = decompressed.decode("utf-8")
    except UnicodeDecodeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid UTF-8 after decompress: {e}",
        )
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e.msg}")
    if not isinstance(obj, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")
    return obj


def _enforce_batch_caps(payload: dict[str, Any]) -> None:
    """Caps durs AVANT validation pydantic — lèvent 400 (pas 422).

    - ≤2000 messages par batch (`MAX_MESSAGES_PER_BATCH`).
    - ≤512 KB par message, JSON sérialisé (`MAX_MESSAGE_BYTES`) — le detail
      inclut le `message_uuid` fautif (ou son index si absent), pour que
      l exporteur puisse découper au bon endroit (cf design).
    """
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be a list")
    if len(messages) > MAX_MESSAGES_PER_BATCH:
        raise HTTPException(
            status_code=400,
            detail=f"Too many messages: {len(messages)} > {MAX_MESSAGES_PER_BATCH}",
        )
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            raise HTTPException(status_code=400, detail=f"messages[{i}] not an object")
        size = len(json.dumps(m, ensure_ascii=False).encode("utf-8"))
        if size > MAX_MESSAGE_BYTES:
            fault_uuid = m.get("message_uuid") or f"index:{i}"
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Message too large: {size} > {MAX_MESSAGE_BYTES} bytes "
                    f"(message_uuid={fault_uuid})"
                ),
            )


def _build_batch_model(
    payload: dict[str, Any], counts: dict[str, int] | None = None
) -> IngestV2BatchIn:
    """Construit + valide le modèle pydantic. ValueError (incl. ValidationError) → 422.

    `counts` (optionnel) : dict mutable partagé via le contexte
    pydantic, peuplé par les field_validators du schema (`nul_stripped`,
    `created_at_nullified` — cf app/schemas/ingest_v2.py) et relu par le
    routeur après coup pour `ingest_receipts`. `None` (défaut) = pas de
    comptage (tests unitaires qui construisent le modèle directement).
    """
    try:
        context = {"counts": counts} if counts is not None else None
        return IngestV2BatchIn.model_validate(payload, context=context)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


def compute_content_hash(role: str, content: str, created_at: str | None) -> str:
    """sha256(role \\n content \\n created_at) — calculé SERVEUR, APRÈS sanitize.

    Mirror exact du CHECK DB `content_hash ~ '^[0-9a-f]{64}$'` (migration 0015).
    """
    basis = f"{role}\n{content}\n{created_at or ''}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def compute_dedup_key(message_uuid: str | None, content_hash: str) -> str:
    """Mirror pur-Python de la colonne générée DB `dedup_key`.

    `COALESCE(message_uuid, 'h:'||content_hash)` — utilisé par les tests
    hermétiques ; la valeur RÉELLE est calculée côté DB (colonne GENERATED),
    jamais envoyée dans l INSERT.
    """
    return message_uuid if message_uuid else f"h:{content_hash}"


def check_hash_divergence(
    existing_by_dedup_key: dict[str, tuple[int, str]],
    dedup_key: str,
    incoming_content_hash: str,
) -> tuple[int, str] | None:
    """Détecte une divergence de hash sur un `dedup_key` déjà en base.

    `existing_by_dedup_key` : map pré-fetchée UNE SEULE FOIS par batch
    (`dedup_key -> (raw_message_id, content_hash)`, cf boucle d insertion du
    routeur — 1 SELECT, jamais 1 par message). Retourne
    `(raw_message_id, existing_content_hash)` si ce `dedup_key` existe déjà
    avec un `content_hash` DIFFÉRENT de celui du message entrant (édition
    côté client, corruption, ou collision) — `None` sinon (message nouveau,
    ou ré-émission strictement identique).

    Un `dedup_key` ABSENT de la map n est JAMAIS une divergence : pour un
    message sans `message_uuid`, un contenu modifié produit un
    `content_hash` (donc un `dedup_key='h:'+hash`) DIFFÉRENT — c est un
    nouveau message, pas une divergence (cf docstring migration
    `0022_d063_raw_message_revisions.py`).
    """
    existing = existing_by_dedup_key.get(dedup_key)
    if existing is None:
        return None
    existing_id, existing_hash = existing
    if existing_hash == incoming_content_hash:
        return None
    return existing_id, existing_hash


def response_status_code(inserted: int) -> int:
    """202 si au moins un message inséré, 200 sinon (no-op / full dedup)."""
    return 202 if inserted > 0 else 200


def resolve_request_id(header_value: str | None) -> str:
    """Header `X-ARAC-Request-Id` (uuid) si valide, sinon généré serveur.

    Retourne toujours une string uuid normalisée (`str(UUID(...))`) — jamais
    422 : un `request_id` malformé ne doit jamais bloquer l'ingestion, il est
    simplement remplacé.
    """
    if header_value:
        try:
            return str(uuid.UUID(header_value.strip()))
        except ValueError:
            pass
    return str(uuid.uuid4())


def compute_body_sha256(decompressed: bytes) -> str:
    """sha256 du corps DÉCOMPRESSÉ — `ingest_receipts.body_sha256`."""
    return hashlib.sha256(decompressed).hexdigest()


def _resolve_origin_kind(request: Request) -> str | None:
    """Header `X-ARAC-Origin-Kind` (ex. 'jsonl_export'/'api_live'), fourni par
    le client — NULL si absent (champ CE best-effort)."""
    v = request.headers.get(_HEADER_ORIGIN_KIND, "").strip()
    return v or None


def _resolve_hops(request: Request) -> int | None:
    """Header `X-ARAC-Hops` (entier ≥0), fourni par le client — NULL si
    absent ou invalide (champ CE best-effort, jamais 400/422)."""
    raw = request.headers.get(_HEADER_HOPS, "").strip()
    if not raw:
        return None
    try:
        v = int(raw)
    except ValueError:
        return None
    return v if v >= 0 else None


def _resolve_reconcile(request: Request) -> bool:
    """Header `X-ARAC-Reconcile` ('1'/'true', insensible à la casse) — signale
    un batch émis par une passe `--reconcile` côté exporteur (revue
    adversariale findings 3/8/16/30). Best-effort comme les autres headers CE
    de ce module : toute valeur absente ou non reconnue -> `False`, jamais
    400/422. Consommé par `ingest_receipts.reconcile` (cf
    `scripts/ops/reconcile_audit.py:collect_reconcile`)."""
    v = request.headers.get(_HEADER_RECONCILE, "").strip().lower()
    return v in ("1", "true")


# ============================================================================
# POST /v1/ingest/messages
# ============================================================================


@router.post("/messages", response_model=IngestV2Out)
async def ingest_messages(
    request: Request,
    response: Response,
    db: AsyncConnection = Depends(get_db),
) -> IngestV2Out:
    """Ingère une conversation (upsert) + ses messages (idempotents).

    Transaction unique : upsert `arac.conversations` puis INSERT par message
    `ON CONFLICT (conversation_id, dedup_key) DO NOTHING`, puis le reçu
    `ingest_receipts` (outcome='accepted') — cf en-tête module. Le curseur
    `curated_through_message_id` n est JAMAIS avancé ici (propriété du
    curateur v2, cf design §« Gate curateur v2 »).

    TOUT refus (400/413/422/409/429) ou erreur inattendue (500) est capturé
    par le bloc try/except ci-dessous : log structuré `ingest_v2.denied` +
    reçu de refus en connexion autonome (best-effort) — un seul point de
    câblage pour tous les points de `raise` de cette fonction (et ceux
    réutilisés du router legacy, ex. `_resolve_node_id`).
    """
    request_id = resolve_request_id(request.headers.get(_HEADER_REQUEST_ID))
    response.headers[_HEADER_REQUEST_ID] = request_id
    origin_kind = _resolve_origin_kind(request)
    hops = _resolve_hops(request)
    reconcile = _resolve_reconcile(request)

    # Connus progressivement — utilisés par le reçu (accepté OU refusé),
    # donc déclarés en amont du try pour rester lisibles quel que soit le
    # point d'échec.
    node_id: str | None = None
    source_type: str | None = None
    conversation_uid: str | None = None
    body_sha256: str | None = None
    received = 0
    field_counts: dict[str, int] = {"nul_stripped": 0, "created_at_nullified": 0}
    empty_messages = 0
    masked_messages = 0
    scrub_hits: dict[str, int] = {}

    try:
        max_size = _get_max_size()

        # 1. Content-Length pré-check (économise lecture body si trop gros)
        cl_raw = request.headers.get("Content-Length")
        if cl_raw is not None:
            try:
                cl = int(cl_raw)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid Content-Length")
            if cl > max_size:
                raise HTTPException(
                    status_code=413,
                    detail=f"Batch too large: {cl} > {max_size} bytes",
                )

        # 2. Lecture body
        raw_body = await request.body()
        if len(raw_body) > max_size:
            raise HTTPException(
                status_code=413,
                detail=f"Batch too large after read: {len(raw_body)} > {max_size}",
            )

        # 3. Auth / whitelist (RÉUTILISÉ du router legacy)
        node_id = _resolve_node_id(request)

        # 4. Décompression (si gzip, RÉUTILISÉ) + parse JSON (UN objet, pas NDJSON)
        decompressed = _decompress_if_gzip(raw_body)
        body_sha256 = compute_body_sha256(decompressed)
        payload = _parse_batch_json(decompressed)

        # 5. Caps durs (400, avant pydantic)
        _enforce_batch_caps(payload)

        # 6. Validation pydantic stricte (422) — nul_stripped / created_at_nullified
        #    comptés via le contexte pydantic (cf app/schemas/ingest_v2.py).
        batch = _build_batch_model(payload, field_counts)
        source_type = batch.source_type
        conversation_uid = batch.conversation_uid
        received = len(batch.messages)

        # 7. Rate-limit (messages/h/node)
        rate_limit = _get_msg_rate_limit()
        async with db.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM arac.raw_messages "
                "WHERE node_id = %s AND received_at > now() - interval '1 hour'",
                (node_id,),
            )
            row = await cur.fetchone()
            count = row[0] if row else 0
        if count >= rate_limit:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {count}/{rate_limit} msgs/h for node {node_id}",
            )

        # 8. Transaction : upsert conversation + INSERT messages idempotents
        #    + reçu ingest_receipts (outcome='accepted') DANS LA MÊME TX.
        inserted = 0
        duplicates = 0
        hash_divergences = 0
        async with db.transaction(), db.cursor() as cur:
            # Garde d'appartenance (revue adversariale 2026-07-03, S5) : le DO
            # UPDATE ne matche que si la conversation appartient déjà au node
            # appelant — sinon RETURNING ne rend rien -> 409. Empêche un node
            # whitelisté B de s'approprier / polluer une conversation du node A.
            await cur.execute(
                """
                INSERT INTO arac.conversations (source_type, conversation_uid, node_id, title)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (source_type, conversation_uid) DO UPDATE
                    SET updated_at = now(),
                        title = COALESCE(arac.conversations.title, EXCLUDED.title)
                    WHERE arac.conversations.node_id = EXCLUDED.node_id
                RETURNING id, curated_through_message_id
                """,
                (batch.source_type, batch.conversation_uid, node_id, batch.title),
            )
            conv_row = await cur.fetchone()
            if conv_row is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Conversation ({batch.source_type}, {batch.conversation_uid}) "
                        f"appartient à un autre node que {node_id}"
                    ),
                )
            conversation_id, curated_through_message_id = conv_row

            # Pré-fetch UNE SEULE FOIS par batch : map
            # dedup_key -> (raw_message_id, content_hash) de TOUTE la
            # conversation — jamais 1 SELECT par message. Alimente
            # `check_hash_divergence` sur chaque duplicate rencontré ci-dessous.
            await cur.execute(
                "SELECT dedup_key, id, content_hash FROM arac.raw_messages "
                "WHERE conversation_id = %s",
                (conversation_id,),
            )
            existing_rows = await cur.fetchall()
            existing_by_dedup_key: dict[str, tuple[int, str]] = {
                row[0]: (row[1], row[2]) for row in existing_rows
            }

            for m in batch.messages:
                # Sanitize AVANT hash (défense en profondeur, cf app/services/sanitize.py)
                # + comptage scrub_hits/masked_messages/empty_messages.
                sanitized_content, hits = mask_secrets_with_hits(m.content)
                was_masked = sanitized_content != m.content
                if was_masked:
                    masked_messages += 1
                    for category, n in hits.items():
                        scrub_hits[category] = scrub_hits.get(category, 0) + n
                if not m.content.strip():
                    empty_messages += 1
                content_hash = compute_content_hash(m.role, sanitized_content, m.created_at)
                dedup_key = compute_dedup_key(m.message_uuid, content_hash)
                await cur.execute(
                    """
                    INSERT INTO arac.raw_messages
                        (conversation_id, message_uuid, parent_uuid, role, content,
                         content_hash, msg_created_at, node_id, was_masked)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (conversation_id, dedup_key) DO NOTHING
                    RETURNING id
                    """,
                    (
                        conversation_id,
                        m.message_uuid,
                        m.parent_uuid,
                        m.role,
                        sanitized_content,
                        content_hash,
                        m.created_at,
                        node_id,
                        was_masked,
                    ),
                )
                inserted_row = await cur.fetchone()
                if inserted_row is not None:
                    inserted += 1
                    # Correctif findings 6/11/32 (revue adversariale) : la
                    # map de pré-fetch date d'AVANT la boucle — si 2 messages
                    # du même batch partagent un `dedup_key` à contenu
                    # divergent, le 2e doit voir le 1er (fraîchement inséré)
                    # comme "existant", sinon il est absorbé par ON CONFLICT
                    # DO NOTHING sans row `raw_message_revisions` (viole
                    # INV-5 : divergence intra-batch non détectée).
                    existing_by_dedup_key[dedup_key] = (inserted_row[0], content_hash)
                else:
                    duplicates += 1
                    # Divergence de hash : le dedup_key existait
                    # déjà avec un content_hash DIFFÉRENT — jamais un UPDATE
                    # de raw_messages, on consigne l'écart en append-only.
                    divergence = check_hash_divergence(
                        existing_by_dedup_key, dedup_key, content_hash
                    )
                    if divergence is not None:
                        existing_message_id, existing_content_hash = divergence
                        hash_divergences += 1
                        await write_hash_divergence_revision(
                            db,
                            raw_message_id=existing_message_id,
                            conversation_id=conversation_id,
                            dedup_key=dedup_key,
                            existing_content_hash=existing_content_hash,
                            incoming_content_hash=content_hash,
                            incoming_content_masked=sanitized_content,
                            request_id=request_id,
                        )

            await cur.execute(
                """
                SELECT COUNT(*), COUNT(*) FILTER (WHERE id > %s)
                FROM arac.raw_messages
                WHERE conversation_id = %s
                """,
                (curated_through_message_id, conversation_id),
            )
            counts_row = await cur.fetchone()
            msg_count, new_uncurated = counts_row

            http_status = response_status_code(inserted)
            await write_accepted_receipt(
                db,
                request_id=request_id,
                node_id=node_id,
                source_type=batch.source_type,
                conversation_uid=batch.conversation_uid,
                http_status=http_status,
                received=received,
                inserted=inserted,
                duplicates=duplicates,
                hash_divergences=hash_divergences,
                empty_messages=empty_messages,
                created_at_nullified=field_counts["created_at_nullified"],
                masked_messages=masked_messages,
                nul_stripped=field_counts["nul_stripped"],
                body_sha256=body_sha256,
                reconcile=reconcile,
                scrub_hits=scrub_hits or None,
                sensor_version=_SENSOR_VERSION,
                origin_kind=origin_kind,
                hops=hops,
            )

    except HTTPException as exc:
        # Correctif finding 14 (revue adversariale, sécurité) : le detail
        # loggé en journald doit être masqué comme celui écrit en base
        # (`ingest_receipts.refusal_detail`, cf `_prepare_refusal_detail`)
        # — un secret/e-mail refusé ne doit fuiter NI en base NI en logs.
        masked_detail = _prepare_refusal_detail(str(exc.detail))
        _logger.warning(
            "ingest_v2.denied",
            extra={
                "event": "ingest_v2.denied",
                "status_code": exc.status_code,
                "request_id": request_id,
                "node_id": node_id,
                "detail": masked_detail,
            },
        )
        outcome = _OUTCOME_BY_STATUS.get(exc.status_code)
        if outcome is not None:
            await write_refusal_receipt(
                request_id=request_id,
                outcome=outcome,
                http_status=exc.status_code,
                refusal_detail=str(exc.detail),
                node_id=node_id,
                source_type=source_type,
                conversation_uid=conversation_uid,
                received=received,
                empty_messages=empty_messages,
                created_at_nullified=field_counts["created_at_nullified"],
                masked_messages=masked_messages,
                nul_stripped=field_counts["nul_stripped"],
                body_sha256=body_sha256,
                scrub_hits=scrub_hits or None,
                sensor_version=_SENSOR_VERSION,
                origin_kind=origin_kind,
                hops=hops,
            )
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
            headers={**(exc.headers or {}), _HEADER_REQUEST_ID: request_id},
        ) from exc
    except Exception as exc:
        # Correctif finding 14 (idem HTTPException ci-dessus) : le message
        # d'erreur brut peut contenir un fragment de payload (ex. un secret
        # dans un ValueError de parsing) — masqué avant journald.
        #
        # DEPUIS, LA COUPE EST PLUS HAUTE. Le masquage retirait les treize
        # formes de secret CONNUES et laissait passer tout le reste : un
        # `NotNullViolation` de PostgreSQL porte « DETAIL:  Failing row
        # contains (…, perso/sante, <LE SOUVENIR>, …) », que ces treize regex
        # ne reconnaissent pas — mesuré. `raison()` ne garde que la classe et
        # le diagnostic du schéma ; le masquage reste appliqué par-dessus,
        # défense en profondeur, au cas où un nom de contrainte porterait un
        # secret.
        masked_error = _prepare_refusal_detail(raison(exc))
        _logger.warning(
            "ingest_v2.denied",
            extra={
                "event": "ingest_v2.denied",
                "status_code": 500,
                "request_id": request_id,
                "node_id": node_id,
                "error": masked_error,
            },
        )
        await write_refusal_receipt(
            request_id=request_id,
            outcome="error_500",
            http_status=500,
            refusal_detail=raison(exc),
            node_id=node_id,
            source_type=source_type,
            conversation_uid=conversation_uid,
            received=received,
            empty_messages=empty_messages,
            created_at_nullified=field_counts["created_at_nullified"],
            masked_messages=masked_messages,
            nul_stripped=field_counts["nul_stripped"],
            body_sha256=body_sha256,
            scrub_hits=scrub_hits or None,
            sensor_version=_SENSOR_VERSION,
            origin_kind=origin_kind,
            hops=hops,
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error",
            headers={_HEADER_REQUEST_ID: request_id},
        ) from exc

    _logger.info(
        "ingest_v2.accepted",
        extra={
            "event": "ready",
            "conversation_id": str(conversation_id),
            "node_id": node_id,
            "request_id": request_id,
            "received": received,
            "inserted": inserted,
            "duplicates": duplicates,
        },
    )

    response.status_code = http_status
    return IngestV2Out(
        request_id=uuid.UUID(request_id),
        conversation_id=conversation_id,
        received=received,
        inserted=inserted,
        duplicates=duplicates,
        msg_count=msg_count,
        curated_through_message_id=curated_through_message_id,
        new_uncurated=new_uncurated,
    )


# ============================================================================
# POST /v1/ingest/capture-manifest
# ============================================================================


def _capture_manifest_insert_params(
    node_id: str, payload: CaptureManifestIn
) -> tuple[Any, ...]:
    """Construit les paramètres positionnels de l'INSERT `capture_manifests`
    (fonction PURE, testable sans DB — cf tests/test_capture_manifest.py).

    `messages_filtered` sérialisé en JSON ICI (colonne jsonb) — le dict
    pydantic est déjà `dict[str, int]` (extra="forbid" + non-négativité
    validés par le schema, cf app/schemas/ingest_v2.py)."""
    return (
        node_id,
        payload.source_type,
        payload.run_started_at,
        payload.run_ended_at,
        payload.files_scanned,
        payload.sessions,
        payload.messages_read,
        payload.messages_emitted,
        json.dumps(payload.messages_filtered),
        payload.batches_ok,
        payload.batches_failed,
        payload.ack_mismatches,
        payload.state_sha256,
        payload.archive_bytes,
    )


@router.post("/capture-manifest", response_model=CaptureManifestOut)
async def ingest_capture_manifest(
    request: Request,
    payload: CaptureManifestIn,
    db: AsyncConnection = Depends(get_db),
) -> CaptureManifestOut:
    """Enregistre UN manifeste de run de scan de capture.

    Même auth/résolution de node que POST /messages (`_resolve_node_id`,
    RÉUTILISÉ du router legacy) — le `node_id` n'est JAMAIS accepté du corps
    (cf docstring `app/schemas/ingest_v2.py:CaptureManifestIn`).

    Un manifeste est un fait clos : simple INSERT (autocommit psycopg3,
    cf app/db.py), jamais réédité (REVOKE UPDATE/DELETE en base, migration
    0026). Best-effort côté appelant : un 422 (payload invalide) ou un 5xx
    ici ne doit JAMAIS bloquer la capture texte elle-même (cf
    le scanner de capture du poste source et le pont Mac de `mac/`)
    — cette route reste néanmoins stricte niveau schéma (extra="forbid"),
    l'assouplissement est une responsabilité du CLIENT, pas du serveur.
    """
    node_id = _resolve_node_id(request)

    try:
        async with db.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO arac.capture_manifests
                    (node_id, source_type, run_started_at, run_ended_at,
                     files_scanned, sessions, messages_read, messages_emitted,
                     messages_filtered, batches_ok, batches_failed,
                     ack_mismatches, state_sha256, archive_bytes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                _capture_manifest_insert_params(node_id, payload),
            )
            row = await cur.fetchone()
    except HTTPException:
        raise
    except Exception as exc:
        # Correctif finding 14 (revue adversariale, sécurité) : même
        # masquage que les deux sites de `ingest_messages` ci-dessus.
        masked_error = _prepare_refusal_detail(raison(exc))
        _logger.warning(
            "ingest_v2.capture_manifest_failed",
            extra={
                "event": "ingest_v2.capture_manifest_failed",
                "node_id": node_id,
                "source_type": payload.source_type,
                "error": masked_error,
            },
        )
        raise HTTPException(status_code=500, detail="Internal error") from exc

    manifest_id = row[0] if row else None
    _logger.info(
        "ingest_v2.capture_manifest_accepted",
        extra={
            "event": "ready",
            "node_id": node_id,
            "manifest_id": manifest_id,
            "source_type": payload.source_type,
            "messages_read": payload.messages_read,
            "messages_emitted": payload.messages_emitted,
        },
    )
    return CaptureManifestOut(id=manifest_id)
