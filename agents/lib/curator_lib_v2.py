"""Helpers BDD pour l'agent curator — Ingestion V2 par-message.

Pendant v2 de `agents/lib/curator_lib.py` (v1, RETIRÉ du dépôt lors du chantier « Perception V4 » —
historique via `git log -- agents/lib/curator_lib.py`) : opère sur
`arac.conversations` / `arac.raw_messages` (migration 0015) au lieu de
`arac.raw_conversations` (v1, GELÉE — rollback trivial).

Différences structurelles avec v1 :
  - curseur = watermark d'ID GLOBAL (`raw_messages.id`), pas de status
    pending/processing/failed par ligne -> pas de lock/claim (le curateur
    est mono-instance PAR CONSTRUCTION, cf design § Arbitrage 4) ;
  - `find_superseding_snapshot` n'existe pas en v2 (inutile par construction,
    confirmé par les deux avis d'architecture) ;
  - l'avance du curseur doit se faire DANS LA MÊME TRANSACTION que le POST
    des atomes -> `advance_cursor` et `mark_curation_failed` NE COMMITENT
    PAS : c'est au caller (agents/cortex/dispose.py) de committer.

Aucun import de l'API ARAC ici (pas de plumbing HTTP) : ce module reste
purement BDD, testable off-line (CLI, tests hermétiques).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import psycopg

# Chantier « Perception V4 » : backoff linéaire extrait dans un module dédié (une seule
# source de vérité pour la cadence de retry ; ARAC_CURATOR_RETRY_BACKOFF_STEP_MIN/
# MAX_STEPS) — `curator_lib.py` v1 (raw_conversations, gelé) a été retiré.
from agents.lib.curator_backoff import _BACKOFF_MAX_STEPS, _BACKOFF_STEP_MIN, _trunc_error

logger = logging.getLogger("arac.curator.lib.v2")

# --- Fenêtres du gate curateur v2, paramétrables par env ---------------------------------------------------------
_QUIET_HOURS = float(os.environ.get("ARAC_CURATOR_QUIET_HOURS", "2"))
_MIN_NEW_MSGS = max(1, int(os.environ.get("ARAC_CURATOR_MIN_NEW_MSGS", "3")))
_AGE_CAP_HOURS = float(os.environ.get("ARAC_CURATOR_AGE_CAP_HOURS", "24"))


def _gate_params(limit: int | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "quiet_hours": _QUIET_HOURS,
        "min_new_msgs": _MIN_NEW_MSGS,
        "age_cap_hours": _AGE_CAP_HOURS,
    }
    if limit is not None:
        params["limit"] = limit
    return params


# ---------------------------------------------------------------------------
# Gate curateur v2 (WHERE pure, zéro dérive) — SELECT candidats
# ---------------------------------------------------------------------------


async def select_eligible_conversations(
    db: psycopg.AsyncConnection,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """SELECT (read-only) des conversations éligibles à la curation — gate v2.

    SQL EXACT du gate curateur v2 : agrège
    directement `raw_messages` sur `conversations` (watermark d'ID global,
    zéro dérive possible). Éligible si :
      - acked = false ET retry_count < 5 ET backoff écoulé (next_retry_at) ;
      - ET exclusion_category IS NULL (une conversation
        EXCLUE-TRACÉE — reçu d'exclusion motivée posé via les colonnes 0023 —
        sort du backlog actionnable ET du pack ; c'est la définition du
        drain traçé, miroir watchdog `_ACTIONABLE_BACKLOG_SQL` synchrone) ;
      - ET au moins 1 message non curé (id > curated_through_message_id) ;
      - ET ( (calme depuis >= ARAC_CURATOR_QUIET_HOURS ET
              >= ARAC_CURATOR_MIN_NEW_MSGS nouveaux messages)
            OU (le plus vieux message non curé date de plus de
                ARAC_CURATOR_AGE_CAP_HOURS -- plafond d'âge anti-famine) ).

    Ordonné par le plus vieux message NON CURÉ d'abord (les conversations
    négligées le plus longtemps passent en premier). `has_atoms`/lock/claim
    n'existent pas en v2 : le curateur est mono-instance par construction.

    Anti-famine : les timestamps client (`msg_created_at`) sont NULLABLES —
    un client qui n'en envoie pas rendrait sa conversation inéligible POUR
    TOUJOURS (max/min sur NULL = NULL = jamais vrai). D'où
    COALESCE(msg_created_at, received_at) : `received_at` est NOT NULL côté
    serveur, la garantie de rappel ne dépend jamais du client.

    Anti-spawn-à-vide (revue adversariale, S2) : au moins UN nouveau
    message NON VIDE est exigé — les messages tool-only (uuid conservé,
    content='') comptent pour l'ordre mais ne justifient jamais, seuls,
    une dépense LLM.
    """
    sql = (
        "SELECT c.id, c.conversation_uid, c.source_type, c.node_id, "
        "       c.curated_through_message_id AS cursor "
        "FROM arac.conversations c "
        "JOIN arac.raw_messages m ON m.conversation_id = c.id "
        "WHERE c.acked = false AND c.retry_count < 5 "
        "  AND c.exclusion_category IS NULL "
        "  AND (c.next_retry_at IS NULL OR c.next_retry_at <= now()) "
        "GROUP BY c.id "
        "HAVING count(*) FILTER (WHERE m.id > c.curated_through_message_id) >= 1 "
        "   AND count(*) FILTER (WHERE m.id > c.curated_through_message_id "
        "                        AND btrim(m.content) <> '') >= 1 "
        "   AND ( "
        "        (now() - max(COALESCE(m.msg_created_at, m.received_at)) "
        "               >= interval '1 hour' * %(quiet_hours)s "
        "         AND count(*) FILTER (WHERE m.id > c.curated_through_message_id) "
        "               >= %(min_new_msgs)s) "
        "        OR min(COALESCE(m.msg_created_at, m.received_at)) "
        "             FILTER (WHERE m.id > c.curated_through_message_id) "
        "             <= now() - interval '1 hour' * %(age_cap_hours)s "
        "   ) "
        "ORDER BY min(COALESCE(m.msg_created_at, m.received_at)) "
        "  FILTER (WHERE m.id > c.curated_through_message_id) "
        "  ASC NULLS LAST "
        "LIMIT %(limit)s"
    )
    async with db.cursor() as cur:
        await cur.execute(sql, _gate_params(limit))
        rows = await cur.fetchall()
    return [
        {
            "id": str(r[0]),
            "conversation_uid": r[1],
            "source_type": r[2],
            "node_id": r[3],
            "cursor": r[4],
        }
        for r in rows
    ]


async def count_uncurated(db: psycopg.AsyncConnection) -> int:
    """COUNT (read-only, cheap) des conversations RÉELLEMENT éligibles.

    Même prédicat que `select_eligible_conversations` (gate curateur v2) :
    sert de pending-gate du batch -> si 0, aucun `claude` n'est spawné.
    """
    sql = (
        "SELECT COUNT(*) FROM ( "
        "  SELECT c.id "
        "  FROM arac.conversations c "
        "  JOIN arac.raw_messages m ON m.conversation_id = c.id "
        "  WHERE c.acked = false AND c.retry_count < 5 "
        "    AND c.exclusion_category IS NULL "
        "    AND (c.next_retry_at IS NULL OR c.next_retry_at <= now()) "
        "  GROUP BY c.id "
        "  HAVING count(*) FILTER (WHERE m.id > c.curated_through_message_id) >= 1 "
        "     AND count(*) FILTER (WHERE m.id > c.curated_through_message_id "
        "                          AND btrim(m.content) <> '') >= 1 "
        "     AND ( "
        "          (now() - max(COALESCE(m.msg_created_at, m.received_at)) "
        "                 >= interval '1 hour' * %(quiet_hours)s "
        "           AND count(*) FILTER (WHERE m.id > c.curated_through_message_id) "
        "                 >= %(min_new_msgs)s) "
        "          OR min(COALESCE(m.msg_created_at, m.received_at)) "
        "               FILTER (WHERE m.id > c.curated_through_message_id) "
        "               <= now() - interval '1 hour' * %(age_cap_hours)s "
        "     ) "
        ") sub"
    )
    async with db.cursor() as cur:
        await cur.execute(sql, _gate_params())
        row = await cur.fetchone()
    return int(row[0]) if row else 0


# ---------------------------------------------------------------------------
# SELECT messages non curés d'une conversation
# ---------------------------------------------------------------------------


async def fetch_uncurated_messages(
    db: psycopg.AsyncConnection,
    conversation_id: str,
    cursor: int,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """SELECT (read-only) des messages bruts non encore curés d'une conversation.

    Retourne {id, message_uuid, role, content, msg_created_at}, ORDER BY id
    ASC (ordre d'arrivée serveur = watermark). `limit` optionnel (absent par
    défaut -> lit tout le delta ; le chunking en aval découpe déjà par budget
    de tokens, cf agents/curator/chunking.py).
    """
    sql = (
        "SELECT id, message_uuid, role, content, msg_created_at "
        "FROM arac.raw_messages "
        "WHERE conversation_id = %s AND id > %s "
        "ORDER BY id"
    )
    params: list[Any] = [conversation_id, cursor]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    async with db.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()
    return [
        {
            "id": r[0],
            "message_uuid": r[1],
            "role": r[2],
            "content": r[3],
            "msg_created_at": r[4],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# UPDATE succès : avance du curseur (même tx que le POST des atomes)
# ---------------------------------------------------------------------------


async def advance_cursor(
    db: psycopg.AsyncConnection,
    conversation_id: str,
    new_cursor: int,
    *,
    atoms_generated: int,
) -> None:
    """UPDATE `conversations.curated_through_message_id` (GREATEST) + métriques succès.

    IMPORTANT — PAS DE COMMIT ICI : cette fonction fait partie de la même
    transaction que le POST des atomes côté appelant (arbitrage :
    "avance du curseur dans la même tx que le POST des
    atomes" -> crash-safe sans colonnes de bail/lease). Le caller
    (agents/cortex/dispose.py) DOIT committer explicitement après l'appel,
    et seulement en cas de succès complet de la curation.
    """
    async with db.cursor() as cur:
        await cur.execute(
            "UPDATE arac.conversations SET "
            "  curated_through_message_id = GREATEST(curated_through_message_id, %s), "
            "  curated_at = now(), "
            "  atoms_generated = atoms_generated + %s, "
            "  retry_count = 0, next_retry_at = NULL, last_curation_error = NULL, "
            "  updated_at = now() "
            "WHERE id = %s",
            (new_cursor, atoms_generated, conversation_id),
        )


async def record_atoms_generated(
    db: psycopg.AsyncConnection,
    conversation_id: str,
    n: int,
) -> None:
    """UPDATE métrique `atoms_generated` SEULE — sans toucher curseur, retry,
    curated_at (contrairement à `advance_cursor`).

    Utilisé sur le chemin d'échec PARTIEL (revue adversariale C1) : des chunks
    du préfixe ont réussi et créé des atomes, mais la conversation part en
    retry pour le reste — appeler `advance_cursor` ici remettrait retry_count
    à 0 et rendrait le cap `retry_count < 5` inatteignable (retries infinis).

    PAS DE COMMIT ICI (même discipline que les autres writers du module)."""
    async with db.cursor() as cur:
        await cur.execute(
            "UPDATE arac.conversations SET "
            "  atoms_generated = atoms_generated + %s, "
            "  updated_at = now() "
            "WHERE id = %s",
            (n, conversation_id),
        )


# ---------------------------------------------------------------------------
# UPDATE échec : retry borné + backoff linéaire, curseur INTOUCHÉ
# ---------------------------------------------------------------------------


async def mark_curation_failed(
    db: psycopg.AsyncConnection,
    conversation_id: str,
    *,
    error: str | None,
) -> int:
    """UPDATE de conversation en échec de curation : curseur INTOUCHÉ.

    `retry_count` est incrémenté et `next_retry_at` planifié en backoff
    LINÉAIRE, formule partagée avec l'ex-`curator_lib.mark_curated(status='failed')`
    v1 (retiré) via `_BACKOFF_STEP_MIN`/`_BACKOFF_MAX_STEPS` de
    `agents/lib/curator_backoff.py` — une seule source de vérité pour la
    cadence de retry.

    `error` est un motif INTERNE (jamais du contenu de conversation ni un
    stdout brut de subprocess), tronqué par `_trunc_error`.

    PAS DE COMMIT ICI (même discipline que `advance_cursor` : le caller
    committe après l'appel).

    Retourne le `retry_count` APRÈS incrément (oracle de
    couverture) : `agents/cortex/dispose.py` réutilise ce compteur EXISTANT
    (pas de colonne dédiée) pour détecter des omissions CONSÉCUTIVES d'une
    même conversation — un succès (`advance_cursor`) le remet à 0, donc sa
    valeur mesure bien une série ininterrompue d'échecs à avancer.
    """
    err = _trunc_error(error)
    async with db.cursor() as cur:
        await cur.execute(
            "UPDATE arac.conversations SET "
            "  retry_count = retry_count + 1, "
            "  last_curation_error = %s, "
            "  next_retry_at = now() + make_interval("
            "      mins => %s * LEAST(retry_count + 1, %s)), "
            "  updated_at = now() "
            "WHERE id = %s "
            "RETURNING retry_count",
            (err, _BACKOFF_STEP_MIN, _BACKOFF_MAX_STEPS, conversation_id),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0


async def park_conversation(
    db: psycopg.AsyncConnection,
    conversation_id: str,
    *,
    error: str,
) -> None:
    """PARK immédiat d'une conversation : force `retry_count`
    au plafond du gate (`select_eligible_conversations` exige
    `retry_count < 5`) sans attendre 5 échecs naturels — réservé aux
    situations où continuer à re-présenter ferait plus de mal que de bien
    (3 omissions CONSÉCUTIVES : le LLM ignore silencieusement la même
    conversation à répétition, cf `agents/cortex/dispose.py`).

    `GREATEST` : idempotent, ne fait jamais REDESCENDRE un retry_count déjà
    au-delà du plafond. PAS DE COMMIT ICI (même discipline que le reste du
    module — le caller committe).
    """
    err = _trunc_error(error)
    async with db.cursor() as cur:
        await cur.execute(
            "UPDATE arac.conversations SET "
            "  retry_count = GREATEST(retry_count, 5), "
            "  last_curation_error = %s, "
            "  updated_at = now() "
            "WHERE id = %s",
            (err, conversation_id),
        )


async def defer_conversation(
    db: psycopg.AsyncConnection,
    conversation_id: str,
    *,
    error: str,
) -> int:
    """BACKOFF SANS ESCALADE vers le park (cas « tranche
    TRONQUÉE ») : une conversation-géant dont la tranche présentée était
    TRONQUÉE par le budget pack et que le LLM a omise — l'omission ne prouve
    RIEN (il n'a jamais vu la conversation entière), elle ne doit donc JAMAIS
    compter vers le seuil de park (`OMISSION_PARK_THRESHOLD`) ni épuiser le
    cap du gate (`retry_count < 5`).

    Même formule de backoff linéaire que `mark_curation_failed`
    (`curator_backoff`, source unique de cadence), mais `retry_count` est
    PLAFONNÉ à 4 : la conversation recule (next_retry_at) sans jamais sortir
    du gate par épuisement — le vrai résolveur des géants 0-atome est le
    value-gate (agents/cortex/value_gate.py), pas le park.

    PAS DE COMMIT ICI (même discipline que le reste du module). Retourne le
    `retry_count` APRÈS l'update (plafonné)."""
    err = _trunc_error(error)
    async with db.cursor() as cur:
        await cur.execute(
            "UPDATE arac.conversations SET "
            "  retry_count = LEAST(retry_count + 1, 4), "
            "  last_curation_error = %s, "
            "  next_retry_at = now() + make_interval("
            "      mins => %s * LEAST(retry_count + 1, %s)), "
            "  updated_at = now() "
            "WHERE id = %s "
            "RETURNING retry_count",
            (err, _BACKOFF_STEP_MIN, _BACKOFF_MAX_STEPS, conversation_id),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0


# Marqueur du compteur de présentations COMPLÈTES omises (fix round-1,
# finding « conflation retry_count ») : `retry_count` est UN compteur partagé
# à TROIS sémantiques (mark_curation_failed = échec/punition quarantaine,
# defer_conversation = tranche tronquée, advance_cursor = reset) — il ne peut
# donc JAMAIS prouver « >= 3 présentations COMPLÈTES sans atome » (garde-fou
# cas 1). Le compteur dédié vit dans `last_curation_error` (colonne
# EXISTANTE, AUCUNE migration) sous ce marqueur parseable : tout autre writer
# du champ (defer, punition, park) l'écrase -> la série repart à 1
# (CONSERVATEUR : jamais moins de 3 présentations complètes réelles avant un
# drain) ; tout succès (`advance_cursor`) le remet à NULL (série cassée).
_FULL_OMISSION_MARKER = "full_omission_streak="


async def mark_full_omission(
    db: psycopg.AsyncConnection,
    conversation_id: str,
    *,
    error: str,
) -> tuple[int, int]:
    """UPDATE d'une omission sur tranche PLEINEMENT présentée (
    fix round-1) : incrémente le compteur DÉDIÉ de présentations complètes
    consécutives sans atome (marqueur `_FULL_OMISSION_MARKER` dans
    `last_curation_error`), JAMAIS le `retry_count` partagé comme preuve.

    `retry_count` est tout de même incrémenté mais PLAFONNÉ à 4 (comme
    `defer_conversation`) : la conversation recule en backoff sans jamais
    sortir du gate par épuisement (`retry_count < 5`) — sous couverture v2 la
    décision terminale est STREAK-based (drain traçé), plus jamais un park
    par accumulation de compteur conflaté.

    Un seul UPDATE atomique : le streak précédent est parsé côté SQL depuis
    `last_curation_error` (0 si marqueur absent — donc les retry_count prod
    PRÉ-FLIP ne comptent JAMAIS : au flip ON, toute conversation repart à
    streak=1, jamais une exclusion sur l'histoire d'un autre compteur).

    PAS DE COMMIT ICI (même discipline que le reste du module). Retourne
    `(retry_count, full_omission_streak)` APRÈS l'update."""
    err = _trunc_error(error)
    async with db.cursor() as cur:
        await cur.execute(
            "UPDATE arac.conversations SET "
            "  retry_count = LEAST(retry_count + 1, 4), "
            "  last_curation_error = %(marker)s || "
            "    (COALESCE(substring(last_curation_error "
            "         from %(regex)s)::int, 0) + 1)::text || ';' || %(err)s, "
            "  next_retry_at = now() + make_interval("
            "      mins => %(step)s * LEAST(retry_count + 1, %(max_steps)s)), "
            "  updated_at = now() "
            "WHERE id = %(cid)s "
            "RETURNING retry_count, "
            "  substring(last_curation_error from %(regex)s)::int",
            {
                "marker": _FULL_OMISSION_MARKER,
                "regex": _FULL_OMISSION_MARKER + r"(\d+)",
                "err": err,
                "step": _BACKOFF_STEP_MIN,
                "max_steps": _BACKOFF_MAX_STEPS,
                "cid": conversation_id,
            },
        )
        row = await cur.fetchone()
    if not row:
        return 0, 0
    return int(row[0]), int(row[1] or 0)


async def get_atoms_generated(
    db: psycopg.AsyncConnection,
    conversation_id: str,
) -> int:
    """SELECT (read-only) du compteur `atoms_generated` d'une conversation —
    garde DURE du drain-exclusion (fix round-1, aligné value-gate :
    ne JAMAIS exclure une conversation qui a déjà produit des atomes)."""
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT atoms_generated FROM arac.conversations WHERE id = %s",
            (conversation_id,),
        )
        row = await cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


async def mark_conversation_excluded(
    db: psycopg.AsyncConnection,
    conversation_id: str,
    *,
    category: str,
    reason: str,
    by: str,
) -> bool:
    """Reçu d'EXCLUSION MOTIVÉE — drain TRACÉ, jamais silencieux :
    pose les 4 colonnes 0023 (`exclusion_category`/`exclusion_reason`/
    `excluded_at`/`excluded_by`). Une conversation ainsi marquée sort du gate
    actionnable (`exclusion_category IS NULL` dans le prédicat) et de ses
    miroirs watchdog/conservation — SANS acked (le trigger d'audit d'ack ne
    concerne pas ce chemin), SANS DELETE (contenu conservé dans raw_messages,
    invariant C-0→C-9), RÉVERSIBLE (colonnes re-clearables, cf
    scripts/ops/exclude_conversation.py --reinclude).

    FIRST-WRITER-WINS (fix round-1, finding « motif mutable sans journal ») :
    le trigger 0029 ne journalise les mutations de motif que sous
    `acked=true` — ce writer MACHINE opère `acked=false`, une ré-écriture
    passerait donc SANS trace. D'où `AND exclusion_category IS NULL` : un
    motif déjà consigné n'est JAMAIS écrasé par ce chemin (aligné D36
    « l'exclusion consignée est définitive par défaut ») ; la requalification
    reste possible via l'outil opérateur (`exclude_conversation.py
    --force-motive-change`, journalisé).

    ⚠️ `category` DOIT appartenir à la taxonomie FERMÉE de la CHECK 0023
    (`conversations_exclusion_category_check`) : 'anthropic_temporary_purged',
    'duplicate_source', 'no_curable_content', 'operator_manual', 'test' —
    toute autre valeur fait échouer l'UPDATE (et la transaction du caller).
    `reason` : motif MÉCANIQUE, jamais de PII (règle V0.107). `by` : label de
    COMPOSANT, jamais une identité personnelle.

    PAS DE COMMIT ICI (le caller committe, même tx que l'avance du curseur).
    Retourne True si le reçu a été posé, False si un motif existait déjà
    (le caller LOGGE le skip — jamais un silence)."""
    async with db.cursor() as cur:
        await cur.execute(
            "UPDATE arac.conversations SET "
            "  exclusion_category = %s, "
            "  exclusion_reason = %s, "
            "  excluded_at = now(), "
            "  excluded_by = %s, "
            "  updated_at = now() "
            "WHERE id = %s AND exclusion_category IS NULL "
            "RETURNING id",
            (category, _trunc_error(reason), by, conversation_id),
        )
        row = await cur.fetchone()
    return row is not None
