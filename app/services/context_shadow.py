"""context_shadow.py — moteur SHADOW + SERVE du Context Engine R3-pur
simplifié (V5 « Cerveau Cognitif »), `ENGINE_VERSION =
"ce-shadow-r3pur-v1"`.

Deux modes, un seul pipeline de décision (lib pure `app/context/`) :

  - **SHADOW** : appelé APRÈS que la réponse servie de `recall` est
    construite. Exécute le kNN shadow top-100 (greffe scope-préfixe
    embarquée), applique la décision R3-pur (`app.context.policy.decide`) et
    écrit un reçu `arac.context_receipts` — SANS JAMAIS toucher la réponse
    servie (bit-identique par construction : elle est figée avant l'appel).
  - **SERVE (GO-gaté)** : pour les consommateurs à profil
    abstention-valeur (`cortex_dedup`, `canari`), quand le flag de serve
    correspondant est armé, la décision R3-pur GOUVERNE la réponse servie.
    CONTRAT (gravé, revue adversariale) : **profils abstention-valeur
    = comportement prod préservé par construction (distance brute, scope
    strict, ordre dense) + métacognition additive (bandes, abstention,
    receipts)**. Concrètement :
      * la décision R3 (modificateurs, bandes) ne choisit QUE servir/abstenir
        et la taille de coupe (`budget_k`) — jamais QUOI servir ni dans quel
        ordre : ce qui est servi = top `budget_k` du rang kNN dense BRUT,
        identique à prod ;
      * la `distance` servie = distance cosine BRUTE — les contrats
        consommateurs (`agents/cortex/dispose.SEMANTIC_DISTANCE_MAX=0.08`,
        le canari de rappel, epsilon 0.15) sont calibrés sur la
        distance brute, jamais la post-modificateurs ; la distance FINALE
        reste consignée dans le reçu (`top1_distance_final`,
        `shadow_distances`) — la métacognition continue de l'utiliser en
        interne (bandes/abstention inchangées) ;
      * le pool candidats du serve filtre le scope en ÉGALITÉ STRICTE
        (sémantique prod, `app/routers/atoms.py::recall`) — la greffe
        scope-préfixe est « en lecture SHADOW UNIQUEMENT » :
        `run_shadow()` seul, jamais `serve_r3()` ;
      * abstention franche = liste vide (réponse de 1er rang).
    **Activation = GO humain** — défaut OFF, et toute erreur retombe
    sur le chemin dense prod (fallback bruyant, jamais un 500).

INVARIANTS (contrat, à ne jamais affaiblir) :
  1. Une erreur du moteur ne fait JAMAIS échouer le recall servi — mais elle
     est BRUYANTE : `logger.error` + compteur `COUNTERS`, jamais silencieuse.
  2. Flags par défaut OFF, lus dans `os.environ` À CHAQUE requête (même
     idiome que `app/routers/ingest_v2.py` — toggle sans redémarrage).
  3. ZÉRO texte / ZÉRO PII dans les reçus : ids + `query_sha256` uniquement
     (règle V0.107). Les logs d'erreur ne portent que le TYPE d'exception.
  4. Zéro appel LLM/OpenAI : l'embedding requête est RÉUTILISÉ tel quel
     depuis le handler (`query_embedding` déjà calculé par `embed()`).
  5. Append-only : INSERT seul sur `arac.context_receipts` (grants 0030).

PIÈGES connus (§pièges) :
  - **Transaction/pool** : `get_db` yield une connexion poolée non-autocommit ;
    un statement shadow échoué la mettrait en `InFailedSqlTransaction` et
    casserait le commit du check-in pool. TOUT le travail DB du moteur est
    donc enveloppé dans `async with conn.transaction():` — psycopg3 pose un
    SAVEPOINT si une transaction est déjà ouverte (pattern V4
    `agents/cortex/review_queue.py`) : en cas d'échec, ROLLBACK TO SAVEPOINT
    seul, la transaction du handler reste saine.
  - **Import calibration LAZY** : `app.context.calibration` charge le JSON
    gelé à l'import — cet import vit DANS le try du moteur, jamais au niveau
    module, pour qu'une calibration corrompue ne puisse pas empêcher le boot
    de l'API (elle rend le shadow bruyamment inopérant, c'est tout).
  - **`%%` dans le LIKE** : cf `app/context/shadow_scope.SCOPE_PREFIX_CLAUSE`.
  - **k appelant vs budget** : `decide` applique
    `budget_k = min(profile.budget_k, k)` — jamais plus que le k demandé.
  - **Latence** : le kNN shadow est un 2e parcours inline (au volume actuel
    ~1,5k atomes le planner choisit souvent un Seq Scan exact, ~15 ms
    CPU-bound ; sur l'index HNSW, quelques ms) + 1 INSERT, mesuré dans
    `shadow_latency_ms`. Ne PAS déporter dans une task avec la connexion du
    handler (use-after-checkin).
  - **`hnsw.ef_search` NE SUFFIT PAS au contrat top-100** : le défaut
    pgvector (40) tronquerait le pool à ≤40, mais même `ef_search = 100 ==
    LIMIT 100` reste troué — l'index HNSW émet exactement `ef_search`
    tuples et les filtres de la requête (status='active', scope, kind)
    s'appliquent APRÈS la sortie du graphe : pool silencieusement < 100 dès
    que le planner prend l'index (prouvé pgvector 0.8.2 : 0/100 sous index
    avec 300 voisins plus proches hors-filtre). Le garant est
    `SET LOCAL hnsw.iterative_scan = strict_order` (pgvector ≥ 0.8) : le
    parcours du graphe CONTINUE jusqu'à satisfaire le LIMIT, en ordre de
    distance exact. Les deux SET sont posés dans le savepoint AVANT chaque
    kNN ; iterative_scan est best-effort (GUC absent → sondé une fois par
    process, WARNING, repli ef_search seul = comportement pré-fix). Sur un
    Seq Scan exact, les SET sont sans effet.

FLAGS (env pur, défaut OFF) :
  - `ARAC_SHADOW_CE_ENABLED=1`         — maître (shadow-only).
  - `ARAC_SHADOW_CE_V2_ENABLED=1`      — FOLD V2 : shadow-v2 sur la
    représentation foldée `arac.memory_atom_reprs` (repr_version
    `rm1-fold-a50`), INDÉPENDANT du flag v1 (activer l'un sans l'autre).
    Exécuté APRÈS le v1 quand les deux sont armés : deux reçus au même
    `query_sha256` = comparaison vivante par requête. JAMAIS de serve v2
    dans ce chantier (les bandes v1 ne sont pas transposables — consigné,
    cf spec fold-v2 §6.2 point 4 : les bandes v1 appliquées aux distances
    v2 ne sont qu'un PROXY d'observation).
  - `ARAC_SHADOW_CE_CONSUMER_DEFAULT`  — consommateur par défaut quand le
    payload ne déclare rien (défaut `unknown`). Sert UNIQUEMENT à ventiler
    les reçus shadow : il ne participe JAMAIS au gating serve (cf ci-dessous)
    et doit être un slug machine (même pattern que `RecallRequest.consumer`),
    sinon il est ignoré bruyamment (fallback `unknown`) — jamais de libellé
    humain persisté dans un reçu (V0.107).
  - `ARAC_CE_SERVE_CORTEX_DEDUP=1`     — sert `consumer=cortex_dedup`
    par la décision R3-pur. **Activation = GO humain.**
  - `ARAC_CE_SERVE_CANARI=1`           — sert `consumer=canari` par la
    décision R3-pur (profil canari_strict, require_high_band).
    **Activation = GO humain.**

INTERACTION serve × défaut env (garde-fou périmètre de GO) : le gating serve
(`serve_enabled_for`) ne regarde QUE le consommateur DÉCLARÉ dans le payload
(`RecallRequest.consumer`), jamais le consommateur résolu via
`ARAC_SHADOW_CE_CONSUMER_DEFAULT`. Poser
`ARAC_SHADOW_CE_CONSUMER_DEFAULT=cortex_dedup` pendant que
`ARAC_CE_SERVE_CORTEX_DEDUP=1` ne bascule donc PAS le trafic /recall anonyme
(MCP, cockpit, session interactive) sur le chemin servi R3 — le GO
d'armement reste borné aux appelants qui se déclarent explicitement.

Attribution du consommateur (gap G1 du terrain) : personne ne threadait de
consommateur → champ EXPLICITE `RecallRequest.consumer` (défaut `unknown`),
posé par `agents/cortex/atoms_client.recall(consumer="cortex_dedup")` et
le canari de rappel (`"consumer": "canari"`). Le
mapping consommateur → profil est `_CONSUMER_TO_PROFILE` ; tout nom inconnu
retombe sur `session_interactive` (tracé dans les composants de décision).
Convention reçus : en mode shadow anonyme (`unknown`), `consumer='shadow'`
dans le reçu ; sinon le nom déclaré, tel quel.
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg import errors as pg_errors
from psycopg.rows import dict_row

from app.context import request_id_var
from app.context.receipts import INSERT_COLUMNS, ContextReceipt, query_sha256
from app.context.shadow_scope import (
    SCOPE_PREFIX_CLAUSE,
    is_prefix_gain,
    scope_prefix_params,
)

ENGINE_VERSION = "ce-shadow-r3pur-v1"

#: FOLD V2 — même politique R3-pur, pool kNN sur la représentation
#: foldée `arac.memory_atom_reprs`. La valeur distingue les reçus v1/v2 en
#: SQL (`WHERE engine_version LIKE 'ce-shadow-r3pur-v2%'`) — aucune colonne
#: ajoutée au schéma 0030.
ENGINE_VERSION_V2 = "ce-shadow-r3pur-v2-fold-a50"

#: Clé `repr_version` du champion gelé — DOIT rester égale à
#: `app.repr.recipe.REPR_VERSION` (test croisé
#: tests/test_context_shadow_v2_integration.py) ; dupliquée ici pour ne pas
#: importer `app.repr.recipe` (numpy/tiktoken) sur le chemin requête.
REPR_VERSION_V2 = "rm1-fold-a50"

# --------------------------------------------------------------------- flags (défaut OFF, lus à CHAQUE requête — toggle sans redémarrage)
FLAG_SHADOW_ENABLED = "ARAC_SHADOW_CE_ENABLED"
#: FOLD V2 — shadow-v2, indépendant du v1 (défaut OFF). AUCUN flag
#: serve-v2 dans ce chantier (décision d'architecte gravée).
FLAG_SHADOW_V2_ENABLED = "ARAC_SHADOW_CE_V2_ENABLED"
FLAG_CONSUMER_DEFAULT = "ARAC_SHADOW_CE_CONSUMER_DEFAULT"
#: GO-gatés : **activation = GO humain**, jamais armés par un agent.
FLAG_SERVE_CORTEX_DEDUP = "ARAC_CE_SERVE_CORTEX_DEDUP"
FLAG_SERVE_CANARI = "ARAC_CE_SERVE_CANARI"

_SERVE_FLAG_BY_CONSUMER: dict[str, str] = {
    "cortex_dedup": FLAG_SERVE_CORTEX_DEDUP,
    "canari": FLAG_SERVE_CANARI,
}

#: Nom de consommateur (fil G1) → nom de profil `CONSUMER_PROFILES`.
#: Tout nom absent est passé tel quel à `decide`, qui retombe sur
#: `session_interactive` en traçant le nom demandé (jamais perdu).
_CONSUMER_TO_PROFILE: dict[str, str] = {
    "cortex_dedup": "cortex_dedup",
    "canari": "canari_strict",
}

#: Compteurs santé module-level (exposables plus tard via /healthz) —
#: la face « jamais silencieux » de best-effort.
COUNTERS: dict[str, int] = {
    "shadow_error": 0,     # run_shadow a échoué (aucun reçu écrit)
    "serve_fallback": 0,   # serve_r3 a échoué → réponse dense prod servie
    "shadow_v2_error": 0,  # run_shadow_v2 a échoué — JAMAIS partagé avec v1
}

_logger = logging.getLogger("arac.services.context_shadow")

_SHADOW_POOL_LIMIT = 100  # top-100 fixe (pool de calibration du banc R3)

#: `hnsw.ef_search` posé (SET LOCAL, portée transaction/savepoint) avant
#: chaque kNN shadow : le défaut pgvector (40) < LIMIT 100 tronquerait
#: SILENCIEUSEMENT le pool à ≤40 candidats dès que le planner choisit l'index
#: HNSW `ix_memory_atoms_embedding` — décisions hors calibration sans aucun
#: signal. ⚠ ef_search seul ne GARANTIT PAS le contrat top-100 : l'index
#: émet exactement `ef_search` tuples AVANT les filtres de la requête
#: (status/scope/kind) → pool < 100 possible en silence. La garantie vient
#: de `hnsw.iterative_scan` (cf `_pin_iterative_scan` + piège docstring
#: module). Sur un Seq Scan exact, les SET sont sans effet.
_SHADOW_EF_SEARCH = max(_SHADOW_POOL_LIMIT, 100)
_SET_EF_SEARCH_SQL = f"SET LOCAL hnsw.ef_search = {_SHADOW_EF_SEARCH}"

#: Le GARANT du contrat top-100 (pgvector ≥ 0.8) : strict_order poursuit le
#: parcours du graphe jusqu'à satisfaire le LIMIT malgré les filtres
#: post-graphe, en ordre de distance EXACT — jamais relaxed_order ici :
#: l'ordre kNN dense brut est un contrat (serve abstention-valeur + rang
#: des reçus).
_SET_ITERATIVE_SCAN_SQL = "SET LOCAL hnsw.iterative_scan = strict_order"

#: Sonde « le GUC hnsw.iterative_scan existe-t-il ? » — None = pas encore
#: sondé ; False = pgvector < 0.8 (WARNING une fois, repli ef_search seul,
#: comportement pré-fix) ; True = posé à chaque kNN. Reset par les tests
#: via monkeypatch.setattr.
_ITERATIVE_SCAN_SUPPORTED: bool | None = None

# kNN top-100 — colonnes receipt-grade UNIQUEMENT (jamais `value`/`key` :
# zéro texte manipulé), classement dense INCHANGÉ. Squelette PARTAGÉ
# shadow/serve ; SEULE la clause scope diffère :
#   - SHADOW : greffe scope-préfixe — « en lecture SHADOW UNIQUEMENT » ;
#   - SERVE  : égalité STRICTE, sémantique PROD (même clause que
#     app/routers/atoms.py::recall) — le serve ne promeut JAMAIS la greffe
#     en douce.
_KNN_SQL_TEMPLATE = """
    SELECT id, scope, kind, confidence_score, confirmed_until,
           embedding <=> %s::halfvec(3072) AS distance
    FROM arac.memory_atoms
    WHERE status = 'active'
      AND embedding IS NOT NULL
      AND {scope_clause}
      AND (%s::text IS NULL OR kind = %s)
      AND (%s::timestamptz IS NULL OR created_at >= %s)
    ORDER BY embedding <=> %s::halfvec(3072)
    LIMIT {limit}
"""

#: Clause scope PROD (égalité stricte) — copie de la clause servie de
#: `app/routers/atoms.py::recall` ; 2 placeholders, le MÊME scope deux fois.
_SCOPE_STRICT_CLAUSE = "(%s::text IS NULL OR scope = %s)"

_SHADOW_KNN_SQL = _KNN_SQL_TEMPLATE.format(
    scope_clause=SCOPE_PREFIX_CLAUSE, limit=_SHADOW_POOL_LIMIT)
_SERVE_KNN_SQL = _KNN_SQL_TEMPLATE.format(
    scope_clause=_SCOPE_STRICT_CLAUSE, limit=_SHADOW_POOL_LIMIT)

# kNN shadow-v2 (FOLD V2) — distance sur la repr FOLDÉE
# (`memory_atom_reprs`, champion rm1-fold-a50), JOIN `memory_atoms` pour les
# colonnes de décision (scope/kind/confidence_score/confirmed_until) avec le
# MÊME re-filtre status='active' que _FULL_ROWS_SQL (un atome supersédé entre
# l'écriture de sa repr et ce kNN n'entre jamais dans un reçu comme candidat
# vivant). Clause scope = MÊME sémantique que shadow_scope.SCOPE_PREFIX_CLAUSE
# (greffe, lecture shadow uniquement), qualifiée `a.` — `created_at`
# existe dans les DEUX tables (ambiguïté SQL sinon). Mêmes paramètres
# `scope_prefix_params`. `%%` = `%` littéral (placeholders psycopg3 actifs).
_SCOPE_PREFIX_CLAUSE_V2 = (
    "(%s::text IS NULL OR a.scope = %s OR a.scope LIKE %s || '/%%')"
)
_SHADOW_V2_KNN_SQL = f"""
    SELECT a.id, a.scope, a.kind, a.confidence_score, a.confirmed_until,
           r.embedding <=> %s::halfvec(3072) AS distance
    FROM arac.memory_atom_reprs AS r
    JOIN arac.memory_atoms AS a ON a.id = r.atom_id
    WHERE r.repr_version = %s
      AND a.status = 'active'
      AND {_SCOPE_PREFIX_CLAUSE_V2}
      AND (%s::text IS NULL OR a.kind = %s)
      AND (%s::timestamptz IS NULL OR a.created_at >= %s)
    ORDER BY r.embedding <=> %s::halfvec(3072)
    LIMIT {_SHADOW_POOL_LIMIT}
"""

#: Sonde « la table repr a-t-elle au moins UNE ligne pour cette version ? » —
#: exécutée SEULEMENT quand le pool v2 revient vide, pour distinguer
#: « backfill pas encore passé » (no-op bruyant une fois par process) d'une
#: vraie abstention (reçu normal).
_V2_HAS_REPRS_SQL = (
    "SELECT 1 FROM arac.memory_atom_reprs WHERE repr_version = %s LIMIT 1"
)

# Hydratation des atomes servis (mode SERVE seulement) — mêmes colonnes que
# le SELECT de recall(), la `distance` servie étant la distance cosine BRUTE
# du rang kNN (contrat abstention-valeur — jamais la post-modificateurs).
# `status='active'` RE-FILTRÉ ici : sous READ COMMITTED chaque statement voit
# un snapshot frais — un atome supersédé ENTRE le kNN et l'hydratation serait
# sinon servi dans un 200, ce que le chemin dense prod (mono-statement) ne
# peut jamais faire.
_FULL_ROWS_SQL = """
    SELECT id, kind, scope, key, value, desc_hash, tags, status,
           superseded_by, confidence, audit_source, confidence_score,
           source_ref, rationale, node_id, session_id, version,
           created_at, updated_at
    FROM arac.memory_atoms
    WHERE id = ANY(%s::uuid[])
      AND status = 'active'
"""

_INSERT_RECEIPT_SQL = (
    "INSERT INTO arac.context_receipts ("
    + ", ".join(INSERT_COLUMNS)
    + ") VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, "
    "%s::uuid[], %s::uuid[], %s::real[], %s, %s, %s, %s, %s, %s, %s, %s)"
)


# ============================================================================
# Flags & résolution consommateur
# ============================================================================


def shadow_enabled() -> bool:
    """Flag maître — défaut OFF (absent = OFF), lu à chaque requête."""
    return os.environ.get(FLAG_SHADOW_ENABLED) == "1"


def shadow_v2_enabled() -> bool:
    """Flag maître FOLD V2 — défaut OFF, lu à chaque requête,
    INDÉPENDANT de `shadow_enabled` (l'un sans l'autre possible)."""
    return os.environ.get(FLAG_SHADOW_V2_ENABLED) == "1"


#: Même pattern que `RecallRequest.consumer` (app/schemas/atom.py) — la
#: barrière pydantic ne couvre que le chemin payload ; le défaut env doit
#: passer la MÊME validation avant de finir dans un reçu append-only (V0.107 :
#: jamais de libellé humain persisté).
_CONSUMER_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


def resolve_consumer(payload_consumer: str | None) -> str:
    """Consommateur effectif : le champ payload s'il est déclaré, sinon
    `ARAC_SHADOW_CE_CONSUMER_DEFAULT` (défaut `unknown`).

    Le défaut env n'est PAS validé par pydantic (contrairement au champ
    payload) : s'il n'est pas un slug machine, il est IGNORÉ bruyamment
    (warning + fallback `unknown`) — un reçu est append-only, un libellé
    humain (PII) y serait ineffaçable."""
    consumer = (payload_consumer or "").strip() or "unknown"
    if consumer == "unknown":
        env_default = os.environ.get(FLAG_CONSUMER_DEFAULT, "unknown").strip() or "unknown"
        if _CONSUMER_SLUG_RE.match(env_default):
            consumer = env_default
        elif env_default != "unknown":
            _logger.warning(
                "context_shadow.consumer_default_invalid",
                extra={
                    "event": "context_shadow.consumer_default_invalid",
                    # Jamais la valeur elle-même (potentiellement une PII) —
                    # seulement le fait qu'elle est invalide.
                    "flag": FLAG_CONSUMER_DEFAULT,
                },
            )
    return consumer


def serve_enabled_for(payload_consumer: str | None) -> bool:
    """True ssi le consommateur DÉCLARÉ dans le payload est GO-gaté servi
    par la décision R3-pur.

    Prend le champ `RecallRequest.consumer` BRUT (jamais le consommateur
    résolu) : `ARAC_SHADOW_CE_CONSUMER_DEFAULT` ne participe JAMAIS au gating
    serve — sinon poser ce défaut à `cortex_dedup` basculerait TOUT le trafic
    /recall anonyme sur le chemin servi, au-delà du périmètre du GO (cf
    docstring module, INTERACTION serve × défaut env).

    Seuls `cortex_dedup` et `canari` ont un flag de serve ; défaut OFF.
    **Armer ces flags = GO humain** — le shadow n'est jamais promu en
    douce."""
    declared = (payload_consumer or "").strip()
    flag = _SERVE_FLAG_BY_CONSUMER.get(declared)
    return flag is not None and os.environ.get(flag) == "1"


def health_counters() -> dict[str, int]:
    """Copie des compteurs santé (lecture cockpit/tests)."""
    return dict(COUNTERS)


# ============================================================================
# Organes internes (DB + décision)
# ============================================================================


def _request_id_or_none() -> str | None:
    """`X-Request-ID` du middleware si c'est un uuid valide, sinon None (la
    colonne est `uuid` ; un header client arbitraire ne doit pas faire
    échouer l'INSERT du reçu)."""
    rid = request_id_var.get()
    if not rid:
        return None
    try:
        return str(uuid.UUID(rid))
    except (ValueError, AttributeError, TypeError):
        return None


async def _pin_iterative_scan(conn: AsyncConnection, cur) -> None:
    """Pose `SET LOCAL hnsw.iterative_scan = strict_order` — LE garant du
    contrat top-100 (cf piège docstring module : ef_search seul laisse les
    filtres post-graphe réduire le pool sous le LIMIT en silence).

    Le SET vit dans un SAVEPOINT dédié (`conn.transaction()` imbriqué) : si
    le GUC n'existe pas (pgvector < 0.8, `UndefinedObject`), l'échec ne
    poisonne PAS la transaction de l'appelant — sondé UNE fois par process,
    WARNING bruyant, puis repli permanent sur ef_search seul (comportement
    pré-fix, jamais une erreur par requête). SET LOCAL dans un savepoint
    relâché survit jusqu'à la fin de la transaction englobante — la portée
    reste celle du handler, zéro fuite de session."""
    global _ITERATIVE_SCAN_SUPPORTED
    if _ITERATIVE_SCAN_SUPPORTED is False:
        return
    try:
        async with conn.transaction():  # SAVEPOINT dédié au SET
            await cur.execute(_SET_ITERATIVE_SCAN_SQL)
        _ITERATIVE_SCAN_SUPPORTED = True
    except (pg_errors.UndefinedObject, pg_errors.InvalidName):
        # 42704 (GUC inconnu, préfixe non réservé) OU 42602 (pgvector < 0.8
        # chargé : préfixe `hnsw` RÉSERVÉ → « invalid configuration
        # parameter name ») — les deux visages du même fait : pas
        # d'iterative_scan sur ce backend.
        _ITERATIVE_SCAN_SUPPORTED = False
        _logger.warning(
            "context_shadow.iterative_scan_unavailable",
            extra={
                "event": "context_shadow.iterative_scan_unavailable",
                "detail": "pgvector < 0.8 — contrat top-100 non garanti "
                          "sous index HNSW filtré (repli ef_search seul)",
            },
        )


async def _knn_pool(
    conn: AsyncConnection,
    sql: str,
    params: tuple,
) -> tuple[list[Any], dict[str, str | None]]:
    """Exécute un kNN top-100 (shadow OU serve, le SQL vient de l'appelant)
    → (candidats `policy.Candidate` en ORDRE kNN dense brut, map id→scope
    pour la mesure `scope_prefix_gain`). Import policy LAZY (cf docstring
    module).

    L'appelant DOIT avoir ouvert `conn.transaction()` (savepoint) : les
    `SET LOCAL` posés ici (`hnsw.ef_search` + `hnsw.iterative_scan`,
    cf `_pin_iterative_scan` pour la répartition des rôles) tiennent le
    contrat top-100 si le planner choisit l'index HNSW, et leur portée
    meurt avec la transaction du handler."""
    from app.context.policy import Candidate

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(_SET_EF_SEARCH_SQL)
        await _pin_iterative_scan(conn, cur)
        await cur.execute(sql, params)
        rows = await cur.fetchall()

    candidates = [
        Candidate(
            atom_id=str(r["id"]),
            distance=float(r["distance"]),
            scope=r["scope"],
            kind=r["kind"],
            confidence_score=r["confidence_score"],
            confirmed_until=r["confirmed_until"],
        )
        for r in rows
    ]
    scope_by_id = {str(r["id"]): r["scope"] for r in rows}
    return candidates, scope_by_id


async def _shadow_candidates(
    conn: AsyncConnection,
    query_embedding: list[float],
    scope: str | None,
    kind: str | None,
    since: datetime | None,
) -> tuple[list[Any], dict[str, str | None]]:
    """Pool SHADOW (run_shadow SEUL) — scope avec greffe scope-préfixe
    (« en lecture SHADOW UNIQUEMENT »)."""
    params = (
        query_embedding,
        *scope_prefix_params(scope),
        kind, kind,
        since, since,
        query_embedding,
    )
    return await _knn_pool(conn, _SHADOW_KNN_SQL, params)


async def _shadow_v2_candidates(
    conn: AsyncConnection,
    query_embedding: list[float],
    scope: str | None,
    kind: str | None,
    since: datetime | None,
) -> tuple[list[Any], dict[str, str | None]]:
    """Pool SHADOW-V2 (run_shadow_v2 SEUL) — kNN sur la repr foldée
    `memory_atom_reprs` (repr_version rm1-fold-a50), JOIN `memory_atoms`
    re-filtré status='active'. Même greffe scope-préfixe que le shadow
    v1 (lecture shadow uniquement), même garde ef_search (`_knn_pool`) : le
    nouvel index HNSW `ix_memory_atom_reprs_embedding` a exactement le même
    risque de troncature silencieuse à 40."""
    params = (
        query_embedding,
        REPR_VERSION_V2,
        *scope_prefix_params(scope),
        kind, kind,
        since, since,
        query_embedding,
    )
    return await _knn_pool(conn, _SHADOW_V2_KNN_SQL, params)


async def _serve_candidates(
    conn: AsyncConnection,
    query_embedding: list[float],
    scope: str | None,
    kind: str | None,
    since: datetime | None,
) -> tuple[list[Any], dict[str, str | None]]:
    """Pool SERVE (serve_r3 SEUL) — scope en égalité STRICTE, sémantique PROD
    (même clause que `app/routers/atoms.py::recall`) : le mode servi ne voit
    JAMAIS un atome que le chemin dense prod n'aurait pas vu."""
    params = (
        query_embedding,
        scope, scope,
        kind, kind,
        since, since,
        query_embedding,
    )
    return await _knn_pool(conn, _SERVE_KNN_SQL, params)


def _decide(candidates: list[Any], k: int, consumer: str):
    """Décision R3-pur (lib pure) — import calibration LAZY."""
    from app.context.calibration import CALIBRATION
    from app.context.policy import decide

    profile_name = _CONSUMER_TO_PROFILE.get(consumer, consumer)
    return decide(candidates, CALIBRATION, k=k, consumer_profile=profile_name)


def _build_receipt(
    *,
    receipt_consumer: str,
    query_text: str,
    scope: str | None,
    kind: str | None,
    k: int,
    decision: Any,
    scope_by_id: dict[str, str | None],
    served_ids: list[str],
    latency_ms: float,
    engine_version: str = ENGINE_VERSION,
) -> ContextReceipt:
    """ContextReceipt (validé receipt-grade par `__post_init__`) depuis une
    décision — ids + nombres uniquement, jamais de texte. `engine_version`
    ventile v1/v2 dans la même table 0030."""
    shadow_ids = [s.atom_id for s in decision.selected]
    shadow_distances = [float(s.distance) for s in decision.selected]
    comp = decision.score_components
    gain = sum(1 for sid in shadow_ids if is_prefix_gain(scope_by_id.get(sid), scope))
    return ContextReceipt(
        request_id=_request_id_or_none(),
        consumer=receipt_consumer,
        engine_version=engine_version,
        calibration_version=comp.get("calibration_version", "unknown"),
        query_sha256=query_sha256(query_text),
        scope_filter=scope,
        kind_filter=kind,
        k_requested=k,
        budget_k=decision.budget_k,
        served_ids=served_ids,
        shadow_ids=shadow_ids,
        shadow_distances=shadow_distances,
        top1_distance_raw=comp.get("top1_distance_raw"),
        top1_distance_final=comp.get("top1_distance_final"),
        raw_band=decision.raw_band,
        final_band=decision.band_top1,
        stop_reason=decision.stop_reason,
        scope_prefix_gain=gain,
        shadow_latency_ms=latency_ms,
        shadow_error=None,
    )


async def _insert_receipt(conn: AsyncConnection, receipt: ContextReceipt) -> None:
    """INSERT append-only du reçu — l'appelant enveloppe déjà dans le
    SAVEPOINT (`conn.transaction()`) ; ici, juste l'exécution."""
    async with conn.cursor() as cur:
        await cur.execute(_INSERT_RECEIPT_SQL, receipt.to_params())


def _receipt_consumer_for_shadow(consumer: str) -> str:
    """Convention : les runs shadow ANONYMES (`unknown`) sont
    marqués `consumer='shadow'` dans le reçu ; un consommateur déclaré
    (cortex_dedup/canari/...) reste attribué à son nom (la ventilation par
    profil est la matière de la compétition mesurée)."""
    return "shadow" if consumer == "unknown" else consumer


# ============================================================================
# SHADOW — mesurer, ne jamais toucher la réponse servie
# ============================================================================


async def run_shadow(
    conn: AsyncConnection,
    *,
    query_embedding: list[float] | None,
    query_text: str,
    scope: str | None,
    kind: str | None,
    since: datetime | None,
    k: int,
    consumer: str,
    served_ids: list[str],
) -> None:
    """Exécute le shadow R3-pur et écrit un reçu. NE LÈVE JAMAIS.

    Appelé par `recall()` APRÈS construction de la réponse servie
    (`served_ids` = vérité du chemin servi). Tout le travail DB (kNN +
    INSERT) est sous SAVEPOINT : un échec laisse la transaction du handler
    saine et se solde par `logger.error` + `COUNTERS["shadow_error"] += 1`
    (bruyant, jamais fatal, jamais silencieux)."""
    started = time.perf_counter()
    try:
        async with conn.transaction():  # SAVEPOINT (pattern V4 review_queue)
            if not query_embedding:
                # Défensif : l'embedding manque (le chemin servi aurait déjà
                # 500 avant nous, mais le reçu d'abstention est receipt-grade).
                receipt = _no_embedding_receipt(
                    consumer=consumer, query_text=query_text, scope=scope,
                    kind=kind, k=k,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    served_ids=served_ids,
                )
            else:
                candidates, scope_by_id = await _shadow_candidates(
                    conn, query_embedding, scope, kind, since)
                decision = _decide(candidates, k, consumer)
                receipt = _build_receipt(
                    receipt_consumer=_receipt_consumer_for_shadow(consumer),
                    query_text=query_text, scope=scope, kind=kind, k=k,
                    decision=decision, scope_by_id=scope_by_id,
                    served_ids=served_ids,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                )
            await _insert_receipt(conn, receipt)
    except Exception as exc:  # noqa: BLE001 — invariant : jamais fatal au recall
        COUNTERS["shadow_error"] += 1
        _logger.error(
            "context_shadow.failed",
            extra={
                "event": "context_shadow.failed",
                "consumer": consumer,
                "request_id": request_id_var.get(),
                "error": type(exc).__name__,
                "shadow_error_count": COUNTERS["shadow_error"],
            },
        )


def _no_embedding_receipt(
    *, consumer: str, query_text: str, scope: str | None, kind: str | None,
    k: int, latency_ms: float, served_ids: list[str],
    engine_version: str = ENGINE_VERSION,
) -> ContextReceipt:
    """Reçu d'abstention `no_embedding` (posé par le moteur AVANT tout kNN,
    cf CHECK de la migration 0030). Import calibration LAZY pour le budget."""
    from app.context.calibration import CALIBRATION, DEFAULT_CONSUMER_PROFILE

    profile_name = _CONSUMER_TO_PROFILE.get(consumer, consumer)
    profile = CALIBRATION.consumer_profiles.get(
        profile_name, CALIBRATION.consumer_profiles[DEFAULT_CONSUMER_PROFILE])
    return ContextReceipt(
        request_id=_request_id_or_none(),
        consumer=_receipt_consumer_for_shadow(consumer),
        engine_version=engine_version,
        calibration_version=CALIBRATION.version,
        query_sha256=query_sha256(query_text),
        scope_filter=scope,
        kind_filter=kind,
        k_requested=k,
        budget_k=min(profile.budget_k, k),
        served_ids=served_ids,
        shadow_ids=[],
        shadow_distances=[],
        top1_distance_raw=None,
        top1_distance_final=None,
        raw_band=None,
        final_band=None,
        stop_reason="no_embedding",
        scope_prefix_gain=0,
        shadow_latency_ms=latency_ms,
        shadow_error=None,
    )


# ============================================================================
# FOLD V2 — SHADOW-V2 : même politique R3-pur, pool sur la repr foldée
# ============================================================================

#: Throttle du no-op « aucune repr en base » : WARNING UNE fois par process
#: (le backfill n'est pas encore passé / la migration n'est pas appliquée),
#: jamais une erreur par requête. Reset par les tests via monkeypatch.
_V2_NOOP_WARNED = False


def _warn_v2_noop_once(reason: str) -> None:
    """No-op BRUYANT une seule fois par process — `reason` est un slug
    machine ('empty' | 'undefined_table'), jamais une valeur libre."""
    global _V2_NOOP_WARNED
    if _V2_NOOP_WARNED:
        return
    _V2_NOOP_WARNED = True
    _logger.warning(
        "context_shadow_v2.no_reprs",
        extra={
            "event": "context_shadow_v2.no_reprs",
            "repr_version": REPR_VERSION_V2,
            "reason": reason,
        },
    )


async def _v2_has_reprs(conn: AsyncConnection) -> bool:
    async with conn.cursor() as cur:
        await cur.execute(_V2_HAS_REPRS_SQL, (REPR_VERSION_V2,))
        return await cur.fetchone() is not None


async def run_shadow_v2(
    conn: AsyncConnection,
    *,
    query_embedding: list[float] | None,
    query_text: str,
    scope: str | None,
    kind: str | None,
    since: datetime | None,
    k: int,
    consumer: str,
    served_ids: list[str],
) -> None:
    """Shadow-v2 (FOLD V2) : kNN sur `arac.memory_atom_reprs`
    (champion `rm1-fold-a50`), décision R3-pur, reçu
    `engine_version=ENGINE_VERSION_V2`. NE LÈVE JAMAIS.

    Appelé par `recall()` APRÈS `run_shadow` v1 quand
    `ARAC_SHADOW_CE_V2_ENABLED=1` (indépendant du v1) : les deux reçus
    partagent le même `query_sha256` — comparaison vivante par requête.

    PROXY ASSUMÉ ET CONSIGNÉ (spec fold-v2 §6.2 point 4) : la décision
    réutilise la politique et la calibration V1 (`app/context/policy` +
    `r3_calibration.json`) — les bandes/seuils sont calibrés sur des
    distances v1, PAS sur la géométrie foldée v2. Ils ne servent ici que de
    PROXY d'observation ; le reçu le mentionne par construction :
    `engine_version='ce-shadow-r3pur-v2-fold-a50'` +
    `calibration_version=<calib v1>` dans la MÊME row = « distances v2 lues
    avec des bandes v1 ». Toute lecture servie v2 exigera une calibration
    propre (hors chantier, aucun flag serve-v2 n'existe).

    Requête embarquée INCHANGÉE : `query_embedding` = embed v1 brut réutilisé
    (le fold ne touche QUE la représentation des atomes — invariant #4).

    Table repr vide ou absente → NO-OP bruyant une fois par process
    (`context_shadow_v2.no_reprs`, WARNING throttlé), aucun reçu, jamais une
    erreur par requête. Toute autre erreur : `logger.error` +
    `COUNTERS["shadow_v2_error"]` (compteur SÉPARÉ du v1), jamais fatal."""
    started = time.perf_counter()
    try:
        async with conn.transaction():  # SAVEPOINT (même pattern que v1)
            if not query_embedding:
                receipt = _no_embedding_receipt(
                    consumer=consumer, query_text=query_text, scope=scope,
                    kind=kind, k=k,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    served_ids=served_ids,
                    engine_version=ENGINE_VERSION_V2,
                )
            else:
                candidates, scope_by_id = await _shadow_v2_candidates(
                    conn, query_embedding, scope, kind, since)
                if not candidates and not await _v2_has_reprs(conn):
                    # Backfill pas encore passé : rien à observer, pas de
                    # reçu (un reçu d'abstention serait un mensonge — le
                    # moteur n'a pas abstenu, il n'a pas de corpus).
                    _warn_v2_noop_once("empty")
                    return
                decision = _decide(candidates, k, consumer)
                receipt = _build_receipt(
                    receipt_consumer=_receipt_consumer_for_shadow(consumer),
                    query_text=query_text, scope=scope, kind=kind, k=k,
                    decision=decision, scope_by_id=scope_by_id,
                    served_ids=served_ids,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    engine_version=ENGINE_VERSION_V2,
                )
            await _insert_receipt(conn, receipt)
    except pg_errors.UndefinedTable:
        # Migration 0031 pas appliquée sur cette base : no-op bruyant une
        # fois par process (le SAVEPOINT a déjà rollback — la transaction du
        # handler reste saine), jamais une erreur par requête.
        _warn_v2_noop_once("undefined_table")
    except Exception as exc:  # noqa: BLE001 — invariant : jamais fatal au recall
        COUNTERS["shadow_v2_error"] += 1
        _logger.error(
            "context_shadow_v2.failed",
            extra={
                "event": "context_shadow_v2.failed",
                "consumer": consumer,
                "request_id": request_id_var.get(),
                "error": type(exc).__name__,
                "shadow_v2_error_count": COUNTERS["shadow_v2_error"],
            },
        )


# ============================================================================
# SERVE GO-gaté — la décision R3-pur devient la réponse
# ============================================================================


async def serve_r3(
    conn: AsyncConnection,
    *,
    query_embedding: list[float] | None,
    query_text: str,
    scope: str | None,
    kind: str | None,
    since: datetime | None,
    k: int,
    consumer: str,
) -> list[dict[str, Any]] | None:
    """Sert le consommateur par la décision R3-pur (GO humain).

    CONTRAT abstention-valeur (cf docstring module, section SERVE) : le
    comportement prod est préservé PAR CONSTRUCTION — la décision R3
    (modificateurs, bandes) ne choisit QUE servir/abstenir et la taille de
    coupe (`budget_k`), jamais QUOI servir ni dans quel ordre. Ce qui est
    servi = top `budget_k` du rang kNN dense BRUT sur un pool à scope STRICT
    prod (`_serve_candidates`), avec `distance` = distance cosine BRUTE
    (les contrats consommateurs — dispose 0.08, canari epsilon 0.15 — sont
    calibrés dessus). La métacognition (distances finales, bandes) reste
    consignée dans le reçu : `shadow_ids`/`shadow_distances` = la sélection
    R3 post-modificateurs, `top1_distance_raw` ET `top1_distance_final`
    (les DEUX distances), `raw_band`/`final_band`.

    Retourne les rows À SERVIR (dicts prêts pour
    `_row_to_atom_read_with_distance` ; `[]` = abstention franche
    `no_confident_context`) — ou **None si le moteur a échoué** :
    l'appelant sert alors la réponse dense prod (fallback bruyant :
    `logger.error` + `COUNTERS["serve_fallback"]`, jamais un 500).

    Le reçu est écrit dans le MÊME savepoint que la décision : s'il ne peut
    pas être posé, on ne sert PAS une décision non auditée — fallback dense."""
    started = time.perf_counter()
    try:
        async with conn.transaction():  # SAVEPOINT (pattern V4 review_queue)
            if not query_embedding:
                raise RuntimeError("query_embedding absent (no_embedding)")
            candidates, scope_by_id = await _serve_candidates(
                conn, query_embedding, scope, kind, since)
            decision = _decide(candidates, k, consumer)

            rows: list[dict[str, Any]] = []
            if not decision.abstained and candidates:
                # Servi = top budget_k du rang kNN dense BRUT : les
                # modificateurs ne réordonnent JAMAIS ce qui est servi à ces
                # profils, et la distance servie est la BRUTE (contrats
                # dispose 0.08 / canari 0.15). La décision n'a fourni que
                # l'abstention et budget_k.
                to_serve = candidates[: decision.budget_k]
                wanted = [c.atom_id for c in to_serve]
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(_FULL_ROWS_SQL, (wanted,))
                    fetched = {str(r["id"]): r for r in await cur.fetchall()}
                for cand in to_serve:
                    row = fetched.get(cand.atom_id)
                    if row is None:
                        # Course READ COMMITTED : atome disparu OU supersédé
                        # entre les 2 SELECT (_FULL_ROWS_SQL re-filtre
                        # status='active') — jamais servi dans un 200.
                        continue
                    rows.append({**row, "distance": float(cand.distance)})

            receipt = _build_receipt(
                receipt_consumer=consumer,
                query_text=query_text, scope=scope, kind=kind, k=k,
                decision=decision, scope_by_id=scope_by_id,
                served_ids=[str(r["id"]) for r in rows],
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )
            await _insert_receipt(conn, receipt)
        return rows
    except Exception as exc:  # noqa: BLE001 — invariant : jamais fatal au recall
        COUNTERS["serve_fallback"] += 1
        _logger.error(
            "context_serve.failed",
            extra={
                "event": "context_serve.failed",
                "consumer": consumer,
                "request_id": request_id_var.get(),
                "error": type(exc).__name__,
                "serve_fallback_count": COUNTERS["serve_fallback"],
            },
        )
        return None
