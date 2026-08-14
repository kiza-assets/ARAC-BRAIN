"""Modèles Pydantic v2 pour `arac.sessions` + `arac.session_buffer` — Phase 2.4.

DDL de référence : `db/migrations/01_init.sql`, tables `arac.sessions` et
`arac.session_buffer`. DDL réel vérifié via
``\\d arac.sessions`` et ``\\d arac.session_buffer`` (Phase 2.4 mini-plan).

Modèles publics :
- `SessionOpen`              — POST /v1/sessions/open
- `SessionAppendEvent`       — POST /v1/sessions/{id}/append
- `SessionClose`             — POST /v1/sessions/{id}/close
- `SessionRead`              — GET /v1/sessions/{id} (sans buffer)
- `SessionReadWithBuffer`    — GET /v1/sessions/{id}?include_buffer=true
- `SessionBufferEntry`       — 1 entrée du buffer

Note design (Q.B Phase 2.4) : `SessionRead.atoms_created` est calculé live au
GET via SELECT FROM arac.memory_atoms WHERE session_id (pas le champ DDL
arac.sessions.atoms_created qui reste NULL Phase 2-3). Voir docstring
`app/routers/sessions.py` pour le détail.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.scope import Scope


# ============================================================================
# Enums spécifiques sessions (NON partagés avec atom.py — YAGNI Q.A Phase 2.4)
# ============================================================================


class ClosedBy(str, Enum):
    """Qui a clos la session ? (`sessions.closed_by` BDD CHECK)."""

    MANUAL = "manual"           # close manuelle via l'API (humain ou agent)
    AUTO_CRON = "auto_cron"     # close auto par le cron `stale_closer` (Phase 6)


class SessionState(str, Enum):
    """Enum virtuel — mappé sur `ended_at IS NULL` côté SQL.

    Pas de colonne `status` en DDL pour les sessions (contrairement à
    memory_atoms). Cet enum sert UNIQUEMENT au filtre query string du list
    endpoint : `?status=open` → `WHERE ended_at IS NULL`, `?status=closed`
    → `WHERE ended_at IS NOT NULL`.
    """

    OPEN = "open"
    CLOSED = "closed"


# ============================================================================
# Configuration Pydantic commune
# ============================================================================

_COMMON_CONFIG = ConfigDict(
    str_strip_whitespace=True,
    validate_assignment=True,
    extra="forbid",                      # rejette champs inconnus (anti-fabulation API)
    use_enum_values=False,
)


# ============================================================================
# Inputs
# ============================================================================


class SessionOpen(BaseModel):
    """POST /v1/sessions/open input.

    `topic` est optionnel (peut être renseigné plus tard via PATCH ou laissé
    None pour les sessions ad-hoc).
    """

    model_config = _COMMON_CONFIG

    node_id: str = Field(min_length=1)
    scope: Scope                                  # réutilise l'énumération fermée des scopes
    topic: str | None = Field(default=None, max_length=200)


class SessionAppendEvent(BaseModel):
    """POST /v1/sessions/{id}/append input.

    `event_type` est free-form côté DB (aucun CHECK SQL sur session_buffer).
    Convention applicative proposée Phase 2.4 (NON enforced ici, à durcir
    Phase 9+ si patterns d'usage divergent) :
      - `"message"`        : ligne de chat brute (humain ou agent)
      - `"atom_created"`   : référence à un atom_id créé pendant la session
      - `"recall"`         : trace d'un recall sémantique
      - `"note"`           : note interne de session
    """

    model_config = _COMMON_CONFIG

    event_type: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] | None = None


class SessionClose(BaseModel):
    """POST /v1/sessions/{id}/close input.

    `summary` est obligatoire — il sera embedded via `text-embedding-3-large`
    et stocké dans `sessions.summary_embedding` (halfvec(3072)) pour
    recherche sémantique future (`/v1/sessions/recall` Phase 4).
    """

    model_config = _COMMON_CONFIG

    summary: str = Field(min_length=1)
    accomplishments: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    closed_by: ClosedBy = ClosedBy.MANUAL


# ============================================================================
# Outputs
# ============================================================================


class SessionBufferEntry(BaseModel):
    """1 entrée du buffer events (output uniquement, pas de PK côté DB)."""

    model_config = _COMMON_CONFIG

    session_id: UUID
    event_type: str
    payload: dict[str, Any] | None
    created_at: datetime


class SessionRead(BaseModel):
    """Output : GET /v1/sessions/{id} (sans buffer par défaut).

    Champs exclus :
    - `summary_embedding` (halfvec, 24 KiB lourd payload — endpoint dédié
      `/embedding` possible Phase 4+ si besoin debug)

    `atoms_created` est calculé **live** via `SELECT id FROM memory_atoms
    WHERE session_id = %s` (pas le champ DDL `sessions.atoms_created` qui
    reste NULL Phase 2-3, à populer Phase 9+ par cron/trigger si besoin
    "frozen at close time").
    """

    model_config = _COMMON_CONFIG

    id: UUID
    node_id: str
    scope: Scope
    topic: str | None
    started_at: datetime
    ended_at: datetime | None         # None = open, set = closed
    summary: str | None
    accomplishments: list[str]
    blockers: list[str]
    next_steps: list[str]
    closed_by: ClosedBy | None
    atoms_created: list[UUID]         # calculé live, pas stocké


class SessionReadWithBuffer(SessionRead):
    """Output : GET /v1/sessions/{id}?include_buffer=true.

    Étend SessionRead avec le buffer events ordonné chronologiquement.
    """

    model_config = _COMMON_CONFIG

    buffer: list[SessionBufferEntry] = Field(default_factory=list)


# ============================================================================
# Sentinelles assert au chargement
# ============================================================================

assert len(ClosedBy) == 2, f"ClosedBy doit avoir 2 membres, trouvé {len(ClosedBy)}"
assert len(SessionState) == 2, f"SessionState doit avoir 2 membres, trouvé {len(SessionState)}"
