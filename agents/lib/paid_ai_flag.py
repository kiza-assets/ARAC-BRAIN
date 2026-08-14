"""Master-switch DB « IA payante armée » — clé `arac_config.paid_ai_enabled`.

Deuxième frein (avec l'env `ARAC_ALLOW_PAID_AI` et le kill-switch fichier) :
un flag DB que l'opérateur arme/désarme à la main (jour le jour) sans toucher
aux unités systemd. FAIL-CLOSED : clé absente / illisible / non-`true` => False.

`value` de arac_config est jsonb : on stocke un booléen JSON strict (`true`/`false`).
Lecture (agent/curateur, DSN SELECT) et écriture (opérateur, DSN admin) séparées.
"""

from __future__ import annotations

from typing import Any

_KEY = "paid_ai_enabled"

_SELECT_SQL = "SELECT value FROM arac.arac_config WHERE key = %s"
_UPSERT_SQL = (
    "INSERT INTO arac.arac_config (key, value, description, updated_at, updated_by) "
    "VALUES (%s, %s::jsonb, %s, NOW(), %s) "
    "ON CONFLICT (key) DO UPDATE SET "
    "  value = EXCLUDED.value, updated_at = NOW(), updated_by = EXCLUDED.updated_by"
)
_DESC = "Master-switch IA payante du curateur (sobriété). true => curation autorisée sous budget."


def _coerce_enabled(value: Any) -> bool:
    """N'accepte QUE le booléen JSON true (fail-closed sur tout le reste)."""
    return value is True


# --- Async (curateur batch, psycopg.AsyncConnection) -----------------------


async def read_paid_ai_enabled_async(conn) -> bool:
    async with conn.cursor() as cur:
        await cur.execute(_SELECT_SQL, (_KEY,))
        row = await cur.fetchone()
    if not row:
        return False
    return _coerce_enabled(row[0])


# --- Sync (CLIs opérateur, psycopg.Connection) -----------------------------


def read_paid_ai_enabled(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute(_SELECT_SQL, (_KEY,))
        row = cur.fetchone()
    if not row:
        return False
    return _coerce_enabled(row[0])


def set_paid_ai_enabled(conn, enabled: bool, *, updated_by: str) -> None:
    """UPSERT du flag (opérateur, DSN admin). `enabled` -> booléen JSON strict."""
    json_bool = "true" if enabled else "false"
    with conn.cursor() as cur:
        cur.execute(_UPSERT_SQL, (_KEY, json_bool, _DESC, updated_by))
    conn.commit()
