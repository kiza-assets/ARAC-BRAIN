"""receipts.py — dataclasses du reçu de contexte (shadow R3-pur).

ZÉRO texte, ZÉRO PII par CONSTRUCTION : le reçu ne porte que des ids
(uuid/str), des nombres, des bandes, des raisons d'arrêt et le SHA-256 de la
requête — JAMAIS `query`, `value`, `key` ni aucun libellé humain (règle
audit-ref V0.107 +). `scope_filter`/`kind_filter` sont les
filtres DEMANDÉS par l'appelant (chemins de taxonomie machine, ex.
"outillage/infrastructure" — pas des PII).

La validation `__post_init__` est receipt-grade : un reçu incohérent
(arrays désalignés, sha invalide, bande inconnue) lève AVANT toute écriture
DB — le moteur shadow attrape, logge ERROR et compte (bruyant, jamais fatal
au recall servi).

Ce module reste PUR (aucune E/S) : l'INSERT lui-même vit dans
`app/services/context_shadow.py` (connexion du handler + SAVEPOINT
best-effort, cf pattern `agents/cortex/review_queue.py`).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field

#: Doit rester aligné sur le CHECK de `arac.context_receipts` (migration
#: 0030) : les 4 stop_reason de `policy.decide` + "no_embedding" (posé par
#: le moteur shadow quand l'embedding requête manque, avant tout kNN).
RECEIPT_STOP_REASONS = frozenset(
    {"budget", "exhausted", "no_confident_context", "no_embedding", "corpus_exhausted"})
RECEIPT_BANDS = frozenset({"high", "medium", "low", "none"})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

#: Même pattern que `RecallRequest.consumer` (app/schemas/atom.py) —
#: revalidé ICI (barrière d'écriture) car le consumer d'un reçu peut venir
#: d'ailleurs que du payload pydantic (ex. défaut env
#: ARAC_SHADOW_CE_CONSUMER_DEFAULT) : un libellé humain (PII) dans une table
#: append-only serait ineffaçable (V0.107).
_CONSUMER_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


def query_sha256(query_text: str) -> str:
    """Empreinte SHA-256 hex de la requête — la SEULE trace de la requête
    autorisée dans un reçu (jamais le texte)."""
    return hashlib.sha256(query_text.encode("utf-8")).hexdigest()


@dataclass
class ContextReceipt:
    """Une row de `arac.context_receipts` (append-only). Aligné sur le DDL
    de la migration 0030 — `id`/`created_at` sont générés par la DB et
    n'apparaissent pas ici."""

    consumer: str                       # profil consommateur ('unknown' par défaut)
    engine_version: str                 # ex. "ce-shadow-r3pur-v1"
    calibration_version: str            # ex. "r3-calib-v1-20260708"
    query_sha256: str                   # hex 64 — JAMAIS le texte
    k_requested: int                    # RecallRequest.k (1..100)
    budget_k: int                       # min(profil, k) effectif
    served_ids: list[str]               # ce que PROD a servi (vérité du chemin servi)
    shadow_ids: list[str]               # ce que le shadow aurait servi ([] si abstention)
    shadow_distances: list[float]       # distances FINALES post-modificateurs, alignées shadow_ids
    stop_reason: str
    shadow_latency_ms: float
    request_id: str | None = None
    scope_filter: str | None = None     # filtre scope demandé (path machine, pas une PII)
    kind_filter: str | None = None
    top1_distance_raw: float | None = None
    top1_distance_final: float | None = None
    raw_band: str | None = None         # bande AVANT override profil
    final_band: str | None = None       # bande FINALE déclarée
    scope_prefix_gain: int = 0          # nb d'ids shadow atteints GRÂCE au fix préfixe
    shadow_error: str | None = None     # PROSPECTIF — toujours NULL aujourd'hui : reçu et kNN vivent dans le
                                        # même savepoint, une erreur annule le reçu entier (les échecs shadow ne
                                        # sont tracés que par log ERROR + COUNTERS, volatils). La colonne est
                                        # réservée à un futur reçu d'erreur persistant ; contrat si armée : TYPE
                                        # d'erreur seul, jamais un message avec du texte requête.

    def __post_init__(self) -> None:
        if not _CONSUMER_SLUG_RE.match(self.consumer):
            raise ValueError(
                "consumer doit être un slug machine (pattern RecallRequest.consumer) "
                "— jamais un libellé humain (V0.107, table append-only)")
        if not _SHA256_RE.match(self.query_sha256):
            raise ValueError("query_sha256 doit être un hex SHA-256 (64 minuscules) — jamais le texte")
        if self.stop_reason not in RECEIPT_STOP_REASONS:
            raise ValueError(f"stop_reason inconnu: {self.stop_reason!r}")
        for band_field in ("raw_band", "final_band"):
            v = getattr(self, band_field)
            if v is not None and v not in RECEIPT_BANDS:
                raise ValueError(f"{band_field} inconnu: {v!r}")
        if len(self.shadow_ids) != len(self.shadow_distances):
            raise ValueError("shadow_ids et shadow_distances doivent être alignés")
        if not 1 <= self.k_requested <= 100:
            raise ValueError(f"k_requested hors bornes 1..100: {self.k_requested}")
        if self.budget_k < 1:
            raise ValueError(f"budget_k doit être >= 1: {self.budget_k}")
        if self.scope_prefix_gain < 0 or self.scope_prefix_gain > len(self.shadow_ids):
            raise ValueError("scope_prefix_gain doit être dans [0, len(shadow_ids)]")

    def to_dict(self) -> dict:
        """Sérialisation plate (JSON-safe) — clés = colonnes de
        `arac.context_receipts`, mêmes noms, même ordre que INSERT_COLUMNS."""
        d = asdict(self)
        return {col: d[col] for col in INSERT_COLUMNS}

    def to_params(self) -> tuple:
        """Tuple positionnel aligné sur INSERT_COLUMNS, prêt pour un
        `cursor.execute(INSERT_SQL_TEMPLATE, receipt.to_params())`."""
        d = asdict(self)
        return tuple(d[col] for col in INSERT_COLUMNS)


#: Ordre canonique des colonnes pour l'INSERT (id/created_at générés DB).
INSERT_COLUMNS: tuple[str, ...] = (
    "request_id", "consumer", "engine_version", "calibration_version",
    "query_sha256", "scope_filter", "kind_filter", "k_requested", "budget_k",
    "served_ids", "shadow_ids", "shadow_distances", "top1_distance_raw",
    "top1_distance_final", "raw_band", "final_band", "stop_reason",
    "scope_prefix_gain", "shadow_latency_ms", "shadow_error",
)
