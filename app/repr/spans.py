"""spans.py — extraction bi-format des TEXTES USER depuis
`memory_atoms.source_ref` (write-path fold v2).

Il n'existe pas de table d'empans en production : ce module reconstitue à la
volée, depuis `source_ref`, les textes utilisateur qui ont donné naissance à
un atome.

LEÇON MESURÉE : sur le cerveau de référence, **76 % de la provenance a été
perdue** — un changement de format de `source_ref` a coupé le lien entre
atome et conversation, sans erreur ni alerte. Les atomes concernés existent
toujours ; leur origine, non. D'où les deux ancrages historiques ci-dessous,
que ce module sait tous deux lire. Figez ce format tôt : c'est le seul fil
qui relie ce que le cerveau sait à ce qu'il a vu.

Deux ancrages historiques (spec fold-v2-scout §2) :
  - cortex (vivant)  : `{"message_ids": [int, ...]}` →
    `SELECT id, role, content FROM arac.raw_messages` (texte clair) ;
  - curator legacy (mort en écriture ; ne concerne que les atomes créés avant
    le changement de contrat de provenance — un cerveau neuf n'en a aucun) :
    `{"curator_raw_id": uuid, "message_indices": [int, ...]}` →
    `SELECT content_gz FROM arac.raw_conversations`, gunzip → NDJSON,
    bi-format transcript (a) Claude Code CLI `{"type":..., "message":
    {"role":..., "content": str|list[block]}}` et (b) desktop/simple
    `{"role":..., "content": str}`.

Structure : fonctions PURES (testables sans DB) + UNE fonction I/O fine par
format (SELECT paramétré, aucune autre logique). Atome sans ancrage → [].
Anomalies (conversation/messages manquants, lignes malformées) : comptées et
loguées structuré (jamais de texte ni de PII dans les logs), puis fallback
dégénérescence T_meta — c'est la `spanless_rule` de la recette, pas une
erreur avalée.
"""
from __future__ import annotations

import gzip
import json
import logging
import uuid as _uuid
from typing import Any

logger = logging.getLogger(__name__)

# Formats d'ancrage reconnus (valeur `format` de la provenance build).
FORMAT_CORTEX = "cortex"
FORMAT_CURATOR = "curator"
FORMAT_NONE = "none"

_RAW_MESSAGES_SQL = "SELECT id, role, content FROM arac.raw_messages WHERE id = ANY(%s)"
_RAW_CONVERSATION_SQL = "SELECT content_gz FROM arac.raw_conversations WHERE id = %s::uuid"


# ---------------------------------------------------------------------------
# Ports verbatim de harness/text_extract.py (fonctions pures)
# ---------------------------------------------------------------------------

def parse_source_ref(raw: str | dict | None) -> dict[str, Any]:
    """Parse tolérant de `source_ref` (texte JSON ou déjà dict) : retourne {}
    si absent/invalide plutôt que de lever — port verbatim
    (`text_extract.py:24-35`)."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def role_of(msg_obj: dict[str, Any]) -> str | None:
    """Rôle d'une ligne NDJSON : `message.role` (format CLI), sinon `role`
    top-level (format desktop/simple), sinon `type` (fallback CLI) — port
    verbatim (`text_extract.py:38-48`)."""
    message = msg_obj.get("message")
    if isinstance(message, dict) and message.get("role"):
        return str(message["role"])
    top_role = msg_obj.get("role")
    if top_role:
        return str(top_role)
    t = msg_obj.get("type")
    return str(t) if t else None


def extract_curator_text(msg_obj: dict[str, Any]) -> str:
    """Texte utile d'une ligne NDJSON, quel que soit le format source — port
    verbatim (`text_extract.py:51-78`) : `message.content` (CLI) prioritaire
    sinon `content` top-level (desktop) ; str tel quel ; liste de blocks →
    concat des blocks `type == 'text'` UNIQUEMENT (tool_use/tool_result
    exclus par construction) ; autre/absent → ''."""
    message = msg_obj.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if content is None:
        content = msg_obj.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


# ---------------------------------------------------------------------------
# Classification de l'ancrage (pure) — même logique que extract.py:282-297
# ---------------------------------------------------------------------------

def classify_source_ref(source_ref: str | dict | None) -> tuple[str, dict[str, Any]]:
    """Classe un `source_ref` en (format, ref) :
      - ('curator', {'curator_raw_id': str, 'message_indices': [int,...]})
      - ('cortex',  {'message_ids': [int,...]})
      - ('none',    {})  — atome sans ancrage exploitable (fallback T_meta).

    Priorités et coercions identiques à `harness/extract.py:282-297` :
    curator si `curator_raw_id` ET `message_indices` liste (indices non
    numériques ignorés comme au banc) ; sinon cortex si `message_ids` liste
    NON VIDE (ids coercés int — non-coerçable = erreur BRUYANTE, un ancrage
    cortex corrompu doit se voir) ; sinon none."""
    sref = parse_source_ref(source_ref)
    raw_id = sref.get("curator_raw_id")
    mids = sref.get("message_indices")
    message_ids = sref.get("message_ids")
    if raw_id and isinstance(mids, list):
        return FORMAT_CURATOR, {
            "curator_raw_id": str(raw_id),
            "message_indices": [int(i) for i in mids if isinstance(i, (int, float))],
        }
    if isinstance(message_ids, list) and message_ids:
        return FORMAT_CORTEX, {"message_ids": [int(m) for m in message_ids]}
    return FORMAT_NONE, {}


# ---------------------------------------------------------------------------
# Extraction PURE par format (aucune E/S)
# ---------------------------------------------------------------------------

def cortex_user_texts(
    msg_map: dict[int, tuple[str, str]], message_ids: list[int]
) -> list[str]:
    """Textes des tours `user` d'un ancrage cortex — reproduit
    `build_cortex_spans` (`extract.py:204-229`) + le filtre user du banc :
    parcours dans l'ORDRE FOURNI par `message_ids` (l'ordre listé par le LLM
    cortex, pas de tri chronologique), id manquant → skip compté, contenu
    strippé, vide → skip, rôle != 'user' → exclu."""
    out: list[str] = []
    missing = 0
    for mid in message_ids:
        hit = msg_map.get(mid)
        if hit is None:
            missing += 1
            continue
        role, content = hit
        content = (content or "").strip()
        if not content:
            continue
        if role == "user":
            out.append(content)
    if missing:
        logger.warning(json.dumps({
            "event": "repr.spans.cortex_message_ids_missing",
            "missing": missing, "requested": len(message_ids),
        }))
    return out


def curator_user_texts_from_ndjson(
    ndjson_text: str, message_indices: list[int]
) -> list[str]:
    """Textes des tours `user` d'un transcript NDJSON curator legacy —
    reproduit `build_curator_spans` (`extract.py:158-201`) + le filtre user
    du banc : lignes parsées une à une (ligne malformée → None, comptée),
    indices dédupliqués et TRIÉS (`sorted(set(indices))`, comme le banc),
    hors bornes/malformé → skip compté, rôle != 'user' → exclu, texte
    extrait bi-format (CLI blocks / desktop str) vide → skip."""
    lines: list[dict[str, Any] | None] = []
    malformed = 0
    for line in ndjson_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            lines.append(json.loads(line))
        except json.JSONDecodeError:
            malformed += 1
            lines.append(None)
    out: list[str] = []
    out_of_range = 0
    for idx in sorted(set(message_indices)):
        if idx < 0 or idx >= len(lines) or lines[idx] is None:
            out_of_range += 1
            continue
        obj = lines[idx]
        if role_of(obj) != "user":
            continue
        extracted = extract_curator_text(obj)
        if extracted:
            out.append(extracted)
    if malformed or out_of_range:
        logger.warning(json.dumps({
            "event": "repr.spans.curator_anomalies",
            "malformed_json_lines": malformed,
            "index_out_of_range": out_of_range,
            "indices_requested": len(set(message_indices)),
        }))
    return out


# ---------------------------------------------------------------------------
# I/O fines (une par format) — SELECT paramétré, logique déléguée aux pures
# ---------------------------------------------------------------------------

def fetch_cortex_user_texts(conn, message_ids: list[int]) -> list[str]:
    """Ancrage cortex : SELECT `arac.raw_messages` (texte clair, pas de
    gunzip) puis extraction pure. `conn` : psycopg sync (curseur tuple)."""
    ids = [int(m) for m in message_ids]
    with conn.cursor() as cur:
        cur.execute(_RAW_MESSAGES_SQL, (ids,))
        rows = cur.fetchall()
    msg_map = {int(r[0]): (r[1] or "", r[2] or "") for r in rows}
    return cortex_user_texts(msg_map, ids)


def fetch_curator_user_texts(
    conn, curator_raw_id: str, message_indices: list[int]
) -> list[str]:
    """Ancrage curator legacy : SELECT `content_gz`, gunzip, puis extraction
    pure. `curator_raw_id` validé UUID (bruyant — un ancrage corrompu doit
    se voir, jamais partir dans un SQL). Conversation absente ou blob NULL →
    [] (loggé) : la `spanless_rule` dégénère en T_meta, comme au banc
    (`raw_ids_missing` compté puis skip)."""
    _uuid.UUID(curator_raw_id)  # ValueError bruyante si non-UUID
    with conn.cursor() as cur:
        cur.execute(_RAW_CONVERSATION_SQL, (curator_raw_id,))
        row = cur.fetchone()
    if row is None or row[0] is None:
        logger.warning(json.dumps({
            "event": "repr.spans.curator_raw_id_missing",
            "curator_raw_id": curator_raw_id,
        }))
        return []
    ndjson_text = gzip.decompress(bytes(row[0])).decode("utf-8", errors="replace")
    return curator_user_texts_from_ndjson(
        ndjson_text, [int(i) for i in message_indices]
    )


def user_texts_for_source_ref(
    conn, source_ref: str | dict | None
) -> tuple[str, list[str]]:
    """Point d'entrée du builder : (format, textes user) pour un
    `source_ref` quelconque. Atome sans ancrage → ('none', [])."""
    fmt, ref = classify_source_ref(source_ref)
    if fmt == FORMAT_CORTEX:
        return fmt, fetch_cortex_user_texts(conn, ref["message_ids"])
    if fmt == FORMAT_CURATOR:
        return fmt, fetch_curator_user_texts(
            conn, ref["curator_raw_id"], ref["message_indices"]
        )
    return FORMAT_NONE, []
