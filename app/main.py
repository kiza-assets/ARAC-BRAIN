"""ARAC — FastAPI application entry point (Phase 2.3+).

Composants :
- Lifespan : init/close pool DB + close client OpenAI + chargement tokens Phase 3
- Logging structuré JSON (`pythonjsonlogger.json.JsonFormatter`) sur stdout,
  capturé par systemd journalctl en prod
- Middleware request_id + access log (events `request.received` / `request.completed`)
- Middleware Bearer (app/auth.py) : le jeton porteur est exigé de TOUTE
  requête, `127.0.0.1` compris ; seul `/healthz` est public. Le desserrage de
  la boucle locale exige DEUX variables écrites (`ARAC_API_TRUST_LOOPBACK` +
  `_RAISON`) — la règle exacte, et pourquoi elle a changé, sont dans app/auth.py
- Endpoint `/healthz` (public — exempté de jeton, c'est une sonde)
- Routers : atoms (Phase 2.3) + sessions (Phase 2.4)

Pas de CORS : aucun appelant de ce dépôt ne joint l'API depuis un navigateur —
ce sont des processus (le pont, le cycle, le cockpit, les agents), et chacun
porte son jeton via app/api_token.py. L'API n'écoute par ailleurs que sur la
boucle locale, mais ce n'est PAS ce qui la protège : la boucle locale est un
couloir partagé par tous les comptes de la machine, et c'est le jeton qui fait
la porte. Le seul reverse proxy livré est un exemple, non installé par le
bootstrap : deploy/nginx/ingest-tls.conf.exemple.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from pythonjsonlogger.json import JsonFormatter

from app import auth, constitution, db, errors, journal
from app.context import request_id_var
from app.routers.atoms import router as atoms_router
from app.routers.audit_log import router as audit_log_router
from app.routers.brain import router as brain_router  # Brain API read-only (V0.60, déployée)
from app.routers.dashboard import router as dashboard_router
from app.routers.heartbeat import router as heartbeat_router
from app.routers.ingest import router as ingest_router
from app.routers.ingest_v2 import router as ingest_v2_router
from app.routers.missions import router as missions_router
from app.routers.sessions import router as sessions_router
from app.services import embeddings


# ============================================================================
# Logging setup
# ============================================================================


def setup_logging(level: str = "INFO") -> None:
    """Configure les loggers `arac.*` avec JsonFormatter sur stdout.

    Idempotent : appel multiple ne duplique pas les handlers (utile en tests
    qui peuvent réinitialiser plusieurs fois).
    """
    handler = logging.StreamHandler()
    formatter = JsonFormatter(
        "{asctime} {name} {levelname} {message}",
        style="{",
        rename_fields={
            "asctime": "timestamp",
            "name": "logger",
            "levelname": "level",
        },
    )
    handler.setFormatter(formatter)

    arac_logger = logging.getLogger("arac")
    if not any(isinstance(h, logging.StreamHandler) for h in arac_logger.handlers):
        arac_logger.addHandler(handler)
    arac_logger.setLevel(level)
    arac_logger.propagate = False  # éviter double-log via root

    # LE GARDE DU JOURNAL. Ce que ce processus écrit part dans journald, qui
    # appartient à la MACHINE et non au cerveau (cf app/journal.py). Le filtre
    # est posé sur TOUS les journaliseurs du processus, uvicorn compris : la
    # trace d'un 500 sortait mesurément trois fois, dont deux par le
    # journaliseur d'uvicorn, que relire `app/` n'aurait jamais corrigé.
    journal.installer_garde_journal()


_logger = logging.getLogger("arac.api")


# ============================================================================
# Lifespan
# ============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup : logging + pool DB + tokens Phase 3. Shutdown : pool + client OpenAI."""
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
    await db.init_pool()
    # Force le chargement des tokens au démarrage — erreur de config détectée
    # à l'init plutôt qu'à la première requête authentifiée.
    auth.get_tokens()
    _logger.info("api.startup", extra={"event": "ready"})
    try:
        yield
    finally:
        await db.close_pool()
        await embeddings.close_client()
        _logger.info("api.shutdown", extra={"event": "stopped"})


# ============================================================================
# App
# ============================================================================

app = FastAPI(
    title="ARAC API",
    version="0.2.3",
    description="Couche cognitive personnelle. Phase 2 — API REST.",
    lifespan=lifespan,
)

# Les erreurs ATTENDUES ne doivent jamais ressembler à un plantage. En premier
# lieu le mode dégradé sans clé d'embeddings, que le bootstrap recommande pour
# découvrir le système sans dépenser : il rendait une 500 en texte brut sur le
# tout premier geste d'un nouvel utilisateur. Cf app/errors.py.
errors.enregistrer_handlers(app)


# ============================================================================
# La constitution — l'empreinte de ce sous quoi ce cerveau opère
# ============================================================================
#
# Le texte lui-même vit dans `app/constitution.py` (ou dans
# `config/constitution.md`, s'il a été personnalisé). Ce qui est exposé ici est
# son EMPREINTE : elle change dès qu'un caractère change, et elle est servie
# par /healthz.
#
# À quoi ça sert concrètement : six mois plus tard, devant un atome qui
# surprend, on peut savoir sous quelles règles il a été écrit. Une doctrine
# qu'on ne peut pas dater n'est pas une doctrine, c'est un souvenir.

ARAC_CONSTITUTION_SHA256 = constitution.sha256()
ARAC_CONSTITUTION_CHARS = constitution.char_count()


# ============================================================================
# Middlewares (ordre Starlette : le DERNIER enregistré est l'OUTERMOST)
#
# Stack final (de l'extérieur vers l'intérieur) :
#   request_id_and_logging  ← outermost : log toutes les requêtes (y compris
#                             les 401 d'auth ci-dessous)
#   bearer_auth             ← innermost : auth Phase 3 Conception A
#
# Conséquence : les requêtes refusées par bearer_auth sont quand même tracées
# avec request.received / request.completed status=401, ce qui donne un audit
# log complet (en plus des events auth.missing_bearer / auth.invalid_bearer
# émis par le middleware Bearer lui-même).
# ============================================================================


@app.middleware("http")
async def bearer_auth(request: Request, call_next):
    """Wrapper FastAPI pour app.auth.bearer_middleware (Phase 3)."""
    return await auth.bearer_middleware(request, call_next)


@app.middleware("http")
async def request_id_and_logging(request: Request, call_next):
    """Génère / propage X-Request-ID + log `request.received` / `.completed`.

    Le request_id est exposé via ContextVar `request_id_var` aux services
    (embed(), futurs audit_writer, etc.) pour propagation logs sans paramètre.
    """
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request_id_var.set(rid)

    start = time.perf_counter()
    _logger.info(
        "request.received",
        extra={
            "request_id": rid,
            "method": request.method,
            "path": request.url.path,
        },
    )

    try:
        response = await call_next(request)
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        # `_logger.exception` écrivait ici la trace ENTIÈRE, message compris.
        # MESURÉ sur un cerveau vivant : un `POST /v1/atoms` qui heurte une
        # contrainte NOT NULL fait rendre à PostgreSQL
        # « DETAIL:  Failing row contains (…, perso/sante, temoin-…, <LE
        # SOUVENIR EN CLAIR>, …) », et cette ligne partait telle quelle dans le
        # journal de la machine — le texte du souvenir, sa clé et son domaine,
        # dans un magasin partagé que la désinstallation ne sait pas purger.
        #
        # On garde tout ce qui dépanne : la trace complète (fichiers, lignes,
        # fonctions), la classe de l'exception, et le DIAGNOSTIC PostgreSQL
        # (sqlstate, contrainte, table, colonne) qui vient du schéma et dit
        # quoi corriger. On retire la seule chose qui puisse porter un
        # souvenir : le message. Il reste corrélable par son empreinte, et la
        # ligne fautive reste lisible en base, sous les rôles du cerveau.
        #
        # Le filtre posé par `setup_logging` en ferait autant tout seul ; on
        # l'écrit ici aussi parce qu'un lecteur de ce fichier doit voir la
        # règle à l'endroit où elle s'applique, et parce que deux barrières
        # valent mieux qu'une sur le seul chemin qui a déjà fui.
        _logger.error(
            "request.failed",
            extra={
                "request_id": rid,
                "latency_ms": latency_ms,
                "method": request.method,
                "path": request.url.path,
                "exception": journal.diagnostic_exception(exc),
                "trace": journal.trace_assainie(
                    (type(exc), exc, exc.__traceback__)
                ),
            },
        )
        raise

    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    _logger.info(
        "request.completed",
        extra={
            "request_id": rid,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "latency_ms": latency_ms,
        },
    )
    response.headers["X-Request-ID"] = rid
    return response


# ============================================================================
# Healthz (public — exempté de jeton : c'est une sonde de monitoring)
# ============================================================================


@app.get("/healthz")
async def healthz():
    """Healthcheck — exempté du middleware Bearer Phase 3 (cf app/auth.py _PUBLIC_PATHS).

    Public même derrière un reverse proxy, pour qu'une sonde de disponibilité
    externe n'ait pas besoin qu'on lui distribue un jeton.
    """
    db_health = await db.healthcheck()
    return {
        "ok": db_health["ok"],
        "db": db_health,
        "embeddings": {"client_initialized": embeddings._client is not None},
    }


@app.get("/v1/constitution/hash")
async def constitution_hash():
    """SHA-256 du texte ARAC_CONSTITUTION actif.

    Debug : permet à un client MCP de vérifier que la version reçue au
    handshake (champ `instructions`) est bien la dernière. Si le hash
    diffère, redémarrer le client pour réinitialiser la session MCP et
    recharger `instructions`.
    """
    return {
        "sha256": ARAC_CONSTITUTION_SHA256,
        "chars": ARAC_CONSTITUTION_CHARS,
    }


# ============================================================================
# Routers
# ============================================================================

app.include_router(atoms_router, prefix="/v1/atoms", tags=["atoms"])
app.include_router(sessions_router, prefix="/v1/sessions", tags=["sessions"])
app.include_router(heartbeat_router, prefix="/v1", tags=["heartbeat"])
app.include_router(dashboard_router, prefix="/v1/dashboard", tags=["dashboard"])
app.include_router(audit_log_router, prefix="/v1/audit_log", tags=["audit_log"])
app.include_router(missions_router, prefix="/v1/missions", tags=["missions"])
app.include_router(ingest_router, prefix="/v1/ingest", tags=["ingest"])
# Ingestion V2 par-message : coexiste avec
# le legacy ci-dessus (routes distinctes sous le même prefix /v1/ingest).
app.include_router(ingest_v2_router, prefix="/v1/ingest", tags=["ingest"])
# Brain API read-only (V0.60) : 7 GET sous /v1/brain, write_allowed=False, rédaction des valeurs sensibles.
# Activée 2026-06-23 après gauntlet (compat + fuzz + 3× suite).
app.include_router(brain_router, prefix="/v1/brain", tags=["brain"])


# ============================================================================
# Static files (Phase D.5 dashboard) — sert /static/* depuis ./static/
#
# Le mount sert les assets référencés par dashboard.html (link href, script
# src…). L'endpoint GET /v1/dashboard/ rend le HTML lui-même par HTMLResponse
# (cf routers/dashboard.py) ; il n'a pas besoin de ce mount pour répondre.
#
# CE MODULE NE CRÉE PLUS CE RÉPERTOIRE, ET C'EST LE FOND DU SUJET.
#
# Il faisait, à l'IMPORT, `_STATIC_DIR.mkdir(parents=True, exist_ok=True)`.
# Trois faits se rejoignaient pour rendre le produit inutilisable par qui le
# clone :
#
#   1. `static/` est VIDE dans le dépôt, et git ne transporte pas les
#      répertoires vides : aucun clone ne le porte ;
#   2. l'unité `*-api.service` monte tout le disque en lecture seule
#      (`ProtectSystem=strict`, cf bootstrap/lib/services.sh) et n'ouvre en
#      écriture que le dossier de journaux et le StateDirectory — le dépôt,
#      lui, est du CODE, et n'a aucune raison d'être inscriptible ;
#   3. donc l'import échouait sur `OSError: [Errno 30] Read-only file system`,
#      en boucle de redémarrage, avant la moindre ligne applicative.
#
# Le premier cerveau de l'épreuve ne démarrait que parce qu'on y avait lancé
# `make test`, qui créait ce répertoire par EFFET DE BORD. Un produit qui ne
# démarre qu'après le passage de sa propre suite de tests n'est pas livrable.
#
# La règle, désormais mécanisée par
# `tests/test_l_import_n_ecrit_rien_sur_le_disque.py` :
#
#     UN MODULE D'APPLICATION NE FABRIQUE RIEN SUR LE DISQUE À L'IMPORT.
#
# Il n'y est pas seul : au moment de l'import, on ne sait ni sous quelle
# identité on tourne, ni ce qui est monté en écriture, ni si l'on est dans un
# service, un test, une migration ou un `--help`. Ce qui doit exister est créé
# par CELUI QUI INSTALLE (le bootstrap, `StateDirectory=`, `ReadWritePaths=`),
# jamais par celui qui est importé.
#
# `check_dir=False` dit exactement cela à Starlette : monte la route, ne va pas
# voir sur le disque. Si le répertoire est absent, `/static/*` rend 404 — la
# réponse juste pour un asset qui n'a pas été livré — et l'API démarre.
# ============================================================================

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount(
    "/static",
    StaticFiles(directory=str(_STATIC_DIR), check_dir=False),
    name="static",
)
