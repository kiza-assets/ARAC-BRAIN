"""Pool psycopg3 async pour FastAPI ARAC.

Choix de conception :
  - psycopg3 direct (pas d'ORM applicatif). DSN lu depuis
    `DATABASE_URL_APP` (rôle applicatif, pas admin) en `postgresql://`
    natif (pas de préfixe `+psycopg` qui est SA-only — cf note de correction
    post-2.0).
  - Pool min=2, max=10 (conforme limite Phase 2.0).
  - Adapter `halfvec(3072)` via `pgvector.psycopg.register_vector_async`
    enregistré sur chaque nouvelle connexion du pool.

Cycle de vie :
  - `init_pool()`  : lifespan startup FastAPI (main.py 2.3)
  - `close_pool()` : lifespan shutdown
  - `get_db()`     : FastAPI dependency injection
  - `healthcheck()`: appelé par /healthz

Note transactionnelle : par défaut psycopg3 est en autocommit. Pour des
opérations atomiques (ex: AtomSupersede en 2.3), utiliser explicitement
`async with conn.transaction(): ...` côté router/service.
"""

import os
import time
from typing import Any, AsyncIterator

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

# ============================================================================
# Constantes
# ============================================================================

_POOL_MIN_SIZE = 2
_POOL_MAX_SIZE = 10
_POOL_OPEN_TIMEOUT_SEC = 5.0       # délai max pour acquérir une connexion du pool
_HEALTHCHECK_TIMEOUT_SEC = 2.0     # plus court : SLA /healthz < 200 ms

# ============================================================================
# Pool global (module-level)
# ============================================================================

_POOL: AsyncConnectionPool | None = None


# ============================================================================
# Helpers privés
# ============================================================================


async def _configure_connection(conn: AsyncConnection) -> None:
    """Callback exécuté sur chaque nouvelle connexion du pool.

    Enregistre les adapters pgvector (vector, halfvec, sparsevec) pour que
    psycopg3 sérialise / désérialise list[float] ↔ types PG automatiquement.

    Format Python en lecture (pgvector >= 0.4) : objet `pgvector.HalfVector`
    avec API `.dimensions`, `.to_list()`, `.to_numpy()` (numpy ndarray dtype
    `>f2` = float16 big-endian, format natif halfvec — 6 KB pour 3072 dim).

    Format Python en écriture : `list[float]` ou `numpy.ndarray` accepté
    indifféremment par les paramètres `%s::halfvec(3072)`.

    Sérialisation JSON FastAPI (debug Phase 9+) : `.to_list()` au moment du
    dump pour obtenir une `list[float]` JSON-friendly.
    """
    from pgvector.psycopg import register_vector_async
    await register_vector_async(conn)


# ============================================================================
# API publique
# ============================================================================


async def init_pool() -> None:
    """Initialise le pool. Lit `DATABASE_URL_APP` depuis l'environnement.

    Idempotent : no-op si le pool est déjà ouvert (utile pour tests qui
    réinitialisent). Lève `RuntimeError` si la variable d'env est absente.

    `open(wait=True)` attend que `min_size=2` connexions soient prêtes avant
    de retourner — garantit qu'au premier appel à `/healthz` on n'attend pas
    une connexion à chaud.
    """
    global _POOL
    if _POOL is not None:
        return  # déjà ouvert

    dsn = os.environ.get("DATABASE_URL_APP")
    if not dsn:
        # Le chemin cité doit être celui que le bootstrap POSE réellement :
        # /etc/arac/<votre-base>/arac.env. Il a longtemps désigné
        # « $ARAC_HOME/.env », qu'aucune installation n'écrit — un lecteur en
        # panne y cherchait un fichier qui n'existait nulle part.
        raise RuntimeError(
            "DATABASE_URL_APP non définie — l'API ne sait pas à quelle base "
            "parler.\n"
            "Elle est lue depuis le fichier d'environnement de "
            "l'installation (/etc/arac/<votre-base>/arac.env, mode 0600 root), "
            "lui-même injecté par la directive `EnvironmentFile=` de l'unité "
            "systemd. Modèle commenté : .env.example.\n"
            "Vérifier : sudo grep -c '^DATABASE_URL_APP=' "
            "/etc/arac/<votre-base>/arac.env"
        )

    _POOL = AsyncConnectionPool(
        conninfo=dsn,
        min_size=_POOL_MIN_SIZE,
        max_size=_POOL_MAX_SIZE,
        timeout=_POOL_OPEN_TIMEOUT_SEC,
        configure=_configure_connection,
        open=False,                    # ne pas ouvrir au constructeur (deprecated psycopg_pool)
    )
    await _POOL.open(wait=True)


async def close_pool() -> None:
    """Ferme le pool gracieusement (attend la fin des connexions actives).

    Idempotent. Reset la variable globale pour permettre une réinitialisation
    propre (utile en tests).
    """
    global _POOL
    if _POOL is None:
        return
    await _POOL.close()
    _POOL = None


async def get_db() -> AsyncIterator[AsyncConnection]:
    """FastAPI dependency : yield une connexion du pool, retour auto.

    Usage typique dans un router :

        from fastapi import Depends
        from psycopg import AsyncConnection

        @router.post("/atoms")
        async def create_atom(payload: AtomCreate,
                              db: AsyncConnection = Depends(get_db)):
            async with db.cursor() as cur:
                await cur.execute("INSERT ...")

    Le pool gère le check-out / check-in automatique via le `async with`.
    Pour des opérations multi-statements atomiques :

        async with db.transaction():
            await cur.execute("UPDATE ...")
            await cur.execute("INSERT ...")
    """
    if _POOL is None:
        raise RuntimeError(
            "Pool non initialisé. Appeler `init_pool()` au lifespan startup."
        )
    async with _POOL.connection() as conn:
        yield conn


async def healthcheck() -> dict[str, Any]:
    """Vérifie que la DB répond. Format consommable par /healthz.

    Retour nominal :
        {
            "ok": True,
            "latency_ms": 12.34,
            "pg_version": "PostgreSQL 16.13",
            "pool": {"min": 2, "max": 10, "size": 2, "available": 2,
                     "requests_waiting": 0}
        }

    Retour erreur :
        {"ok": False, "error": "<type>: <msg>"}

    Timeout 2s côté pool — empêche /healthz de bloquer la requête.
    """
    if _POOL is None:
        return {"ok": False, "error": "pool not initialized"}

    start = time.perf_counter()
    try:
        async with _POOL.connection(timeout=_HEALTHCHECK_TIMEOUT_SEC) as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT version()")
                row = await cur.fetchone()
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        pg_version_full = row[0] if row else "unknown"
        # "PostgreSQL 16.13 on x86_64-..." → "PostgreSQL 16.13"
        pg_version = " ".join(pg_version_full.split()[:2])

        stats = _POOL.get_stats()
        return {
            "ok": True,
            "latency_ms": latency_ms,
            "pg_version": pg_version,
            "pool": {
                "min": _POOL.min_size,
                "max": _POOL.max_size,
                "size": stats.get("pool_size"),
                "available": stats.get("pool_available"),
                "requests_waiting": stats.get("requests_waiting"),
            },
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
