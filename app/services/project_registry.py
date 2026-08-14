"""Registre de projet (couche de liens) + routeur de reprise — P-V6-013..017.

`arac.project_registry` = cache dérivé : un centroïde par leaf-scope (moyenne des embeddings
des atomes actifs du scope). Recalculé au tick cortex AVANT le spend gate (frais même IA OFF).

Routeur de reprise : embed(query) -> plus proche centroïde de scope (pgvector) -> recall dense
RESTREINT à ce scope. REJET OPEN-SET : si le plus proche centroïde est trop loin, on NE route
PAS (fail-open = recall normal), pour ne pas router à tort une reprise hors-set.

Déterministe, zéro LLM sur le read-path (embedding text-embedding-3-large = pas un LLM).
"""
from __future__ import annotations
from typing import Any

from psycopg.rows import dict_row

# Distance cosine (pgvector <=>) au-delà de laquelle on refuse de router (fail-open).
# Calibré (validate_registry, transaction annulée) : in-set paraphrasé jusqu'à ~0.64,
# hors-set >= ~0.76 -> fenêtre ~0.70. Le fail-open (recall nu) couvre les cas limites.
REJECT_DISTANCE = 0.70

_RECOMPUTE_SQL = """
INSERT INTO arac.project_registry (scope, centroid, member_count, updated_at)
SELECT scope,
       avg(embedding::vector(3072))::halfvec(3072),
       count(*),
       now()
FROM arac.memory_atoms
WHERE status = 'active' AND embedding IS NOT NULL
GROUP BY scope
HAVING count(*) >= 3
ON CONFLICT (scope) DO UPDATE
    SET centroid = EXCLUDED.centroid,
        member_count = EXCLUDED.member_count,
        updated_at = now()
"""

_DELETE_STALE_SQL = """
DELETE FROM arac.project_registry pr
WHERE NOT EXISTS (
    SELECT 1 FROM arac.memory_atoms m
    WHERE m.status = 'active' AND m.embedding IS NOT NULL AND m.scope = pr.scope
    GROUP BY m.scope HAVING count(*) >= 3
)
"""

_NEAREST_SQL = """
SELECT scope, member_count, (centroid <=> %(qv)s::halfvec(3072))::float8 AS dist
FROM arac.project_registry
ORDER BY centroid <=> %(qv)s::halfvec(3072)
LIMIT 2
"""

# Recall dense (miroir de /v1/atoms/recall) ; %(scope)s NULL => pas de restriction (fail-open).
_RECALL_SQL = """
SELECT id, kind, scope, key, value,
       (embedding <=> %(qv)s::halfvec(3072))::float8 AS distance
FROM arac.memory_atoms
WHERE status = 'active' AND embedding IS NOT NULL
  AND (%(scope)s::text IS NULL OR scope = %(scope)s)
ORDER BY embedding <=> %(qv)s::halfvec(3072)
LIMIT %(k)s
"""


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _atom(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(row["id"]), "kind": row["kind"], "scope": row["scope"],
            "key": row["key"], "value": row["value"], "distance": float(row["distance"])}


async def recompute(conn) -> dict[str, int]:
    """Recalcule le registre (UPSERT + suppression des scopes disparus). Idempotent, 0 coût IA."""
    async with conn.cursor() as cur:
        await cur.execute(_RECOMPUTE_SQL)
        upserted = cur.rowcount
        await cur.execute(_DELETE_STALE_SQL)
        deleted = cur.rowcount
        await cur.execute("SELECT count(*) AS n, coalesce(sum(member_count), 0) AS m FROM arac.project_registry")
        row = await cur.fetchone()
    return {"scopes": int(row[0]), "members_total": int(row[1]),
            "upserted": int(upserted or 0), "deleted": int(deleted or 0)}


async def _plain_recall(cur, qv: str, k: int, reason: str) -> dict[str, Any]:
    await cur.execute(_RECALL_SQL, {"qv": qv, "scope": None, "k": k})
    atoms = await cur.fetchall()
    return {"routed_scope": None, "rejected": True, "reason": reason,
            "candidates": [], "atoms": [_atom(a) for a in atoms]}


async def route(conn, query_vec: list[float], *, k: int = 8,
                reject_distance: float = REJECT_DISTANCE, enabled: bool = True) -> dict[str, Any]:
    """Route une requête de reprise. Retourne le scope routé (ou None si rejeté open-set),
    les candidats top-2, et les atomes (scopés si confiant, sinon recall nu = fail-open).

    `enabled` (kill-switch ARAC_PROJECT_ROUTER_ENABLED) : si False, retombe sur le recall nu
    = comportement inchangé (arm/disarm réversible sans redéploiement)."""
    qv = _vec_literal(query_vec)
    async with conn.cursor(row_factory=dict_row) as cur:
        if not enabled:
            return await _plain_recall(cur, qv, k, "router_disabled")
        # Fail-open si le registre n'existe pas encore (avant migration) ou toute erreur :
        # on ne casse JAMAIS une reprise, on retombe sur le recall nu.
        try:
            await cur.execute(_NEAREST_SQL, {"qv": qv})
            cands = await cur.fetchall()
        except Exception:
            await conn.rollback()
            return await _plain_recall(cur, qv, k, "registry_unavailable")

        candidates = [{"scope": c["scope"], "member_count": int(c["member_count"]),
                       "distance": float(c["dist"])} for c in cands]
        if not candidates or candidates[0]["distance"] > reject_distance:
            return await _plain_recall(cur, qv, k, "open_set_reject")

        top = candidates[0]["scope"]
        scopes = [top]
        if len(candidates) > 1 and (candidates[1]["distance"] - candidates[0]["distance"]) < 0.03:
            scopes.append(candidates[1]["scope"])  # expansion top-2 si quasi-égalité
        atoms: list[dict[str, Any]] = []
        for sc in scopes:
            await cur.execute(_RECALL_SQL, {"qv": qv, "scope": sc, "k": k})
            atoms.extend(_atom(a) for a in await cur.fetchall())
        atoms.sort(key=lambda a: a["distance"])
        return {"routed_scope": top, "rejected": False, "reason": None,
                "candidates": candidates, "expanded_scopes": scopes, "atoms": atoms[:k]}
