"""Pydantic schemas pour /v1/audit_log (Phase 4.6).

Schémas en lecture seule pour l'endpoint `GET /v1/audit_log` qui expose les
entrées de la table `arac.audit_log` où `warning_code IS NOT NULL` — i.e. les
warnings anti-drift W-001..W-007 persistés Phase 4.6 par le router atoms (I2).

Style cohérent avec app/schemas/dashboard.py :
  - `model_config = ConfigDict(extra="forbid")` (strict)
  - Champs typés explicites (int / UUID | None / datetime / dict[str, Any])
  - Aucune validation business côté schema — read-only, on fait confiance à
    ce qui est en BDD.

Note sur `severity` / `message` / `warning_context` :
  - La colonne `warning_context` JSONB contient typiquement
    `{severity, message, context: {...}, remediation_hint?}`.
  - Pour l'exposition API on hisse `severity` et `message` au niveau racine de
    l'entry (commodité client), et on conserve le sous-objet `context` brut
    dans `warning_context` (dict). Si la structure ne correspond pas, on
    retombe sur `{}` (jamais d'erreur 500 dans le router).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditLogEntry(BaseModel):
    """Une ligne d'audit_log avec warning_code IS NOT NULL (Phase 4.6).

    `severity` et `message` sont extraits de `warning_context` côté router
    pour exposition à plat — utile pour le frontend dashboard analytics.
    `warning_context` conserve le sous-objet `context` brut (payload riche).
    """

    model_config = ConfigDict(extra="forbid")

    id: int
    node_id: str
    target_atom_id: UUID | None = None
    warning_code: str | None = None
    severity: str | None = None
    message: str | None = None
    warning_context: dict[str, Any] = Field(default_factory=dict)
    action: str | None = None
    created_at: datetime


class AuditLogResponse(BaseModel):
    """Réponse paginée /v1/audit_log."""

    model_config = ConfigDict(extra="forbid")

    entries: list[AuditLogEntry]
    total: int
    limit: int
    offset: int
