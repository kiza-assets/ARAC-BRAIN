"""ARAC — Control Center : application FastAPI READ-ONLY.

Doctrine : OBSERVE FIRST. DO NOT CONTROL. + READ ONLY.

Ce module expose une application FastAPI dédiée au tableau de bord de
supervision du cerveau. Il est STRICTEMENT en lecture : zéro route POST,
PUT, PATCH, DELETE dans ce fichier ou dans ses dépendances directes.

Garanties structurelles (V1.7C) :
  - app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None) — OpenAPI désactivée.
  - Une seule route non-GET : POST /cc/login (handshake d'auth — pose un cookie
    de session, AUCUNE écriture cerveau ni DB). Toutes les autres routes sont GET.
  - Aucun handler n'écrit en base de données, ne modifie de fichier, ni ne
    déclenche d'action système.
  - Tout contenu dynamique HTML passe par control_center.templates (html.escape).
  - Les collecteurs (db_metrics, system_metrics, reports_council) sont les
    SEULES sources de données — tous en lecture seule.
  - require_session(html=True) → redirect 302 vers /cc/login si pas de session
    valide (mode HTML) ; require_session(html=False) → 401 JSON (mode API).
  - audit_read_log() est appelé sur chaque route protégée (traçabilité lecture).

Cette app N'EST PAS montée dans app/main.py (isolation — activation phase
ultérieure, sur décision explicite de l'opérateur). Aucun fichier systemd
n'est créé ici.

Usage (développement / tests) :
    from control_center.app import create_app
    app = create_app()

Usage serveur (future phase activation) :
    uvicorn control_center.app:app --host 127.0.0.1 --port 8200
"""

from __future__ import annotations

import html
import os
import time
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.journal import installer_garde_journal
from control_center.collectors import brain_api, db_metrics, reports_council, sobriety, system_metrics
from control_center.config import (
    CC_ADMIN_PASSWORD_HASH_ENV,
    CC_SESSION_SECRET_ENV,
    CC_TOTP_SECRET_ENV,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    local_trusted_tunnel_enabled,
)
from control_center.security import (
    audit_read_log,
    auth_fail_log,
    require_session,
    sign_session,
    totp_verify,
    verify_password,
)
from control_center.templates import (
    render_absence,
    render_limite,
    render_page,
    render_refresh_link,
    render_table,
    render_tile,
)
from control_center.perception_routes import register_perception_routes

# ============================================================================
# Factory d'application (pattern utilisé par les tests)
# ============================================================================


def _unite_cockpit() -> str:
    """Le nom de l'unité systemd de CE cockpit.

    Il était écrit en dur — « arac-control-center » — dans l'auto-description
    de /healthz et, plus grave, dans le conseil rendu à l'écran quand les
    identifiants ne sont pas provisionnés : « sudo systemctl restart
    arac-control-center ». Un conseil est du code qui s'exécute dans les mains
    d'un humain : sur une machine à deux cerveaux, celui qui le suit redémarre
    le cockpit du VOISIN, et constate que son propre problème persiste.

    Le bootstrap pose ARAC_UNIT_COCKPIT dans l'unité. À défaut, on rend un
    libellé qui ne se fait pas passer pour une commande.
    """
    return (os.environ.get("ARAC_UNIT_COCKPIT") or "").strip() or "<votre-unité-cockpit>"


def _unite_api() -> str:
    """Le nom de l'unité systemd de l'API de CE cerveau (voir `_unite_cockpit`)."""
    return (os.environ.get("ARAC_UNIT_API") or "").strip() or "API"


def create_app() -> FastAPI:
    """Crée et retourne l'app FastAPI Control Center (READ-ONLY).

    Pattern factory : permet aux tests d'instancier une app fraîche sans
    importer le module-level ``app`` (évite les effets de bord de module).
    La configuration est identique à l'instance module-level.

    Returns:
        FastAPI app configurée en lecture seule, docs désactivées.
    """
    _app = FastAPI(
        title="ARAC Control Center",
        description="Tableau de bord READ-ONLY — OBSERVE FIRST. DO NOT CONTROL.",
        version="1.7C",
        docs_url=None,      # Pas d'OpenAPI interactive exposée
        redoc_url=None,     # Pas de ReDoc exposé
        openapi_url=None,   # /openapi.json désactivé (red-team V1.7B) — expose le
                            # schéma de l'API sans auth ; bloquer ici plutôt qu'au
                            # niveau nginx pour une défense en profondeur.
    )
    # LE GARDE DU JOURNAL, posé avant la première route. Le cockpit lit la
    # mémoire : ses erreurs portent des domaines, des clés et des titres, et
    # `journalctl -u arac-<base>-cockpit.service` les rendait en clair. Le
    # filtre assainit les traces de TOUS les journaliseurs du processus,
    # uvicorn compris — cf. app/journal.py.
    installer_garde_journal()
    _register_routes(_app)
    return _app


def _register_routes(a: FastAPI) -> None:  # noqa: C901 — complexité inhérente au routing
    """Enregistre toutes les routes sur l'instance FastAPI fournie.

    Règle absolue : @a.get partout — seule exception POST : la route /cc/login (auth).
    Cette fonction est la source unique de vérité pour toutes les routes CC.
    """

    # ------------------------------------------------------------------
    # Route racine : redirect vers /cc/ (tunnel SSH → ouvre le cockpit directement)
    # ------------------------------------------------------------------

    @a.get("/", include_in_schema=False)
    async def root_redirect() -> Any:
        """Racine → cockpit. En mode tunnel : ouvre /cc/ directement ; en mode
        sécurisé : /cc/ redirige lui-même vers /cc/login. GET pur, lecture seule."""
        return RedirectResponse(url="/cc/", status_code=307)

    # ------------------------------------------------------------------
    # Route publique : liveness (sans auth)
    # ------------------------------------------------------------------

    @a.get("/cc/healthz", include_in_schema=False)
    async def healthz() -> JSONResponse:
        """Liveness probe — READ-ONLY, sans authentification.

        Utilisé par le monitoring externe pour vérifier que le process est
        vivant. Ne retourne aucune donnée sensible.

        Le champ "provisioned" indique (par booléen de PRÉSENCE uniquement,
        JAMAIS de valeur) si chacune des 3 variables d'env requises est définie.
        Permet de diagnostiquer un login 503 sans se logger ni redémarrer.

        Returns:
            {
              "status": "ok",
              "service": <le nom de l'unité de CE cockpit>,
              "mode": "read-only",
              "provisioned": {
                "session_secret": bool,
                "admin_password_hash": bool,
                "totp_secret": bool
              }
            }
        """
        return JSONResponse(
            {
                "status": "ok",
                "service": _unite_cockpit(),
                "mode": "read-only",
                "provisioned": {
                    "session_secret": bool(os.environ.get(CC_SESSION_SECRET_ENV, "")),
                    "admin_password_hash": bool(os.environ.get(CC_ADMIN_PASSWORD_HASH_ENV, "")),
                    "totp_secret": bool(os.environ.get(CC_TOTP_SECRET_ENV, "")),
                },
                "local_trusted_tunnel": local_trusted_tunnel_enabled(),
                "cockpit_tunnel": system_metrics.cockpit_tunnel_status(),
            }
        )

    # ------------------------------------------------------------------
    # Page de connexion (sans auth — affichage observe-first)
    # ------------------------------------------------------------------

    @a.get("/cc/login", include_in_schema=False)
    async def login_page(request: Request) -> Any:  # noqa: ARG001
        """Page de connexion Control Center — formulaire d'authentification (V1.7C).

        Affiche le formulaire HTML POST /cc/login avec champs password + totp_code.
        C'est le SEUL formulaire mutateur de toute l'app CC — sa seule mutation
        est l'établissement d'une session (cookie), aucune écriture DB/cerveau.

        Auth : mot de passe (pbkdf2_sha256) + TOTP RFC 6238 (HMAC-SHA1, step=30s).
        """
        body = """
<div class="login-box">
  <h1>Connexion Control Center</h1>
  <form method="post" action="/cc/login" autocomplete="off">
    <div class="login-field">
      <label for="password">Mot de passe administrateur</label>
      <input type="password" id="password" name="password" placeholder="&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;"
             autocomplete="current-password" required>
    </div>
    <div class="login-field">
      <label for="totp_code">Code TOTP (6 chiffres)</label>
      <input type="text" id="totp_code" name="totp_code" placeholder="000000"
             maxlength="6" inputmode="numeric" pattern="[0-9]{6}" autocomplete="one-time-code" required>
    </div>
    <button type="submit" style="margin-top:16px; padding:8px 24px; background:#238636;
            color:#fff; border:none; border-radius:6px; cursor:pointer; font-size:14px;">
      Connexion
    </button>
  </form>
  <p style="margin-top:20px; font-size:12px; color:#8b949e;">
    Auth : <strong>mot de passe</strong> (pbkdf2_sha256 / 260&nbsp;000 it&eacute;r.) +
    <strong>TOTP RFC&nbsp;6238</strong> (HMAC-SHA1, step=30s, fen&ecirc;tre &plusmn;1).<br>
    Session sign&eacute;e HMAC-SHA256, TTL 30&nbsp;min, cookie HttpOnly Secure SameSite=Strict.<br>
    Protection brute-force : fail2ban surveille cc_auth_fail.log.
  </p>
</div>
"""
        return render_page("Connexion", body)

    @a.post("/cc/login", include_in_schema=False)
    async def login_post(request: Request) -> Any:
        """POST /cc/login — handshake d'authentification Control Center.

        SEULE route non-GET de toute l'app CC. Sa seule mutation est l'établissement
        d'une session (cookie httponly). AUCUNE écriture DB ni écriture cerveau.

        Flux :
          1. Lit le formulaire (password, totp_code).
          2. FAIL-CLOSED : si l'un des 3 env (CC_SESSION_SECRET, CC_ADMIN_PASSWORD_HASH,
             CC_TOTP_SECRET) manque → 503 + auth_fail_log reason=not_provisioned.
          3. Vérifie password (verify_password) ET totp (totp_verify). Les deux
             helpers utilisent des comparaisons constantes (hmac.compare_digest /
             secrets.compare_digest) — résistants aux attaques de timing.
          4. SUCCÈS → sign_session({"sub": "admin", "iat": ...}, secret) ;
             cookie SESSION_COOKIE_NAME posé (httponly, secure, samesite=strict,
             path=/cc, max_age=SESSION_TTL_SECONDS) ; redirect 303 /cc/.
          5. ÉCHEC → 401 + auth_fail_log(client_ip, reason) pour fail2ban.
             Le 'sub' est TOUJOURS "admin" (valeur serveur, jamais l'input user).

        Sécurité :
          - Les secrets ne sont JAMAIS loggués (ni en clair, ni hashés partiellement).
          - password et totp_code ne sont JAMAIS écrits dans les logs.
          - Le client_ip est sanitizé avant écriture dans cc_auth_fail.log.
          - Rate-limit : fail2ban est la défense principale (cf. RUNBOOK.md).
            Un rate-limit mémoire par IP peut être ajouté en Phase 2 si nécessaire.
        """
        # Lecture du formulaire
        form = await request.form()
        password: str = form.get("password", "")
        totp_code: str = form.get("totp_code", "")

        client_ip: str = (request.client.host if request.client else "unknown")

        # Récupération des secrets depuis l'env (jamais loggués, jamais rendus)
        cc_session_secret = os.environ.get(CC_SESSION_SECRET_ENV, "")
        cc_password_hash = os.environ.get(CC_ADMIN_PASSWORD_HASH_ENV, "")
        cc_totp_secret = os.environ.get(CC_TOTP_SECRET_ENV, "")

        # FAIL-CLOSED : si l'un des 3 env manque → 503 (login non provisionné)
        # Note sécurité : NOT émettre de ligne CC_AUTH_FAIL ici — ce cas est un
        # état de configuration serveur, pas une attaque d'identifiants. Émettre
        # CC_AUTH_FAIL déclencherait fail2ban sur 127.0.0.1 (loopback du tunnel SSH)
        # et couperait la session de l'admin légitime (finding red-team 2.F1).
        # On logue dans cc_access.log avec un tag distinct (non monitoré par fail2ban).
        if not cc_session_secret or not cc_password_hash or not cc_totp_secret:
            audit_read_log("/cc/login[POST]", f"CC_LOGIN_UNPROVISIONED client_ip={client_ip}")
            missing = []
            if not cc_session_secret:
                missing.append(CC_SESSION_SECRET_ENV)
            if not cc_password_hash:
                missing.append(CC_ADMIN_PASSWORD_HASH_ENV)
            if not cc_totp_secret:
                missing.append(CC_TOTP_SECRET_ENV)
            return JSONResponse(
                status_code=503,
                content={
                    # CE MESSAGE A PRESCRIT UN GESTE QUI N'EXISTE PAS. Il
                    # renvoyait à `scripts/control_center/provision_admin.py` :
                    # ce fichier n'est nulle part dans le dépôt. Quelqu'un qui
                    # ne peut pas se connecter à son cockpit lisait donc, au
                    # pire moment, le nom d'un script introuvable — et il
                    # n'accuse pas le message, il s'accuse lui-même. Les trois
                    # secrets sont posés par l'étape 7 du bootstrap
                    # (`bootstrap/lib/secrets.sh`), qui imprime déjà ce geste.
                    "error": (
                        "Login non provisionné : le cockpit n'a pas les trois secrets "
                        "qu'il exige. Ils sont engendrés par l'étape 7 du bootstrap, "
                        "qui les écrit dans le coffre de ce cerveau : "
                        "sudo ./bootstrap/bootstrap.sh --only secrets. "
                        "Puis REDÉMARRE le service pour recharger l'EnvironmentFile : "
                        "sudo systemctl restart " + _unite_cockpit() + ". "
                        "(systemd lit EnvironmentFile une seule fois au démarrage.)"
                    ),
                    "missing": missing,
                },
            )

        # Vérification mot de passe
        pw_ok = verify_password(password, cc_password_hash)

        # Vérification TOTP (indépendante du mot de passe — les deux doivent passer)
        totp_ok = totp_verify(cc_totp_secret, totp_code)

        if not pw_ok:
            auth_fail_log(client_ip, "bad_password")
            return JSONResponse(
                status_code=401,
                content={"error": "Authentification échouée."},
            )

        if not totp_ok:
            auth_fail_log(client_ip, "bad_totp")
            return JSONResponse(
                status_code=401,
                content={"error": "Authentification échouée."},
            )

        # SUCCÈS — création de la session
        # 'sub' est TOUJOURS la valeur serveur "admin" (jamais l'input user)
        # pour éviter toute injection de log ou usurpation de principal.
        payload = {"sub": "admin", "iat": int(time.time())}
        token = sign_session(payload, cc_session_secret)

        response = RedirectResponse(url="/cc/", status_code=303)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            httponly=True,
            secure=True,
            samesite="strict",
            max_age=SESSION_TTL_SECONDS,
            path="/cc",
        )
        return response

    @a.get("/cc/logout", include_in_schema=False)
    async def logout(request: Request) -> Any:  # noqa: ARG001
        """GET /cc/logout — efface le cookie de session et redirige vers /cc/login.

        C'est un GET (pas de mutation serveur) : la "mutation" est côté client
        uniquement (delete_cookie dans la réponse HTTP). Aucune écriture DB.
        """
        response = RedirectResponse(url="/cc/login", status_code=303)
        response.delete_cookie(
            key=SESSION_COOKIE_NAME,
            path="/cc",
        )
        return response

    # ------------------------------------------------------------------
    # Dashboard overview (protégé session HTML)
    # ------------------------------------------------------------------

    @a.get("/cc/", include_in_schema=False)
    async def overview(request: Request, principal: dict = Depends(_session_html)) -> Any:
        """Dashboard principal — 11 tuiles de supervision.

        Affiche une vue consolidée de l'état du cerveau :
          1. Version Git + dernier commit
          2. Total atomes mémoire
          3. Conversations et messages bruts (ingestion V2)
          4. IPQ (Incoming Proposal Queue) — total
          5. MRQ (Memory Review Queue) — total
          6. Derniers verdicts Council (5 max)
          7. Derniers rapports (5 max)
          8. Derniers commits (3 max)
          9. Santé serveur (loadavg, disque)
         10. Sessions tmux actives
         11. Timeline (nb tags, nb branches de version suivies)

        Toutes les données viennent des collecteurs READ-ONLY.
        audit_read_log() tracé avant le rendu.
        """
        audit_read_log("/cc/", principal.get("sub", "?"))

        # Collecte parallèle — chaque collecteur est résilient (retourne {"error":...})
        atoms = db_metrics.memory_atoms_summary()
        # LA TUILE LISAIT UNE TABLE GELÉE, ET DISAIT DONC 0 POUR TOUJOURS.
        #
        # « Conversations brutes » comptait `arac.raw_conversations`, la file
        # d'ingestion V1, GELÉE depuis la migration 0017 : aucune ligne servie
        # de ce dépôt n'y écrit plus (`app/routers/ingest.py` : « GELÉE » ; la
        # route V1 rend 410). L'ingestion V2 écrit dans `arac.conversations` et
        # `arac.raw_messages`. Sur un cerveau neuf, la tuile affichait donc 0 le
        # jour de la première synchronisation — pendant que le pont annonçait
        # « messages insérés 16 » et que /cc/v1/metrics servait
        # `raw_messages_total = 16`. Le cockpit se contredisait d'une page à
        # l'autre, et c'est exactement le défaut que la tuile des branches de
        # version, dix lignes plus bas, porte déjà en commentaire : un zéro faux
        # est pire qu'une absence, il se mesure.
        conv = db_metrics.conversations_count()
        msgs = db_metrics.raw_messages_count()
        # La table gelée reste lisible — elle porte la LIGNÉE des atomes d'avant
        # la bascule — mais elle n'est montrée que lorsqu'elle a quelque chose à
        # dire, et sous un nom qui dit ce qu'elle est.
        raw_conv = db_metrics.raw_conversations_count()
        ipq = db_metrics.ipq_summary()
        mrq = db_metrics.mrq_summary()
        git = system_metrics.git_version()
        health = system_metrics.server_health()
        tmux = system_metrics.tmux_sessions()
        council = reports_council.council_index(n=5)
        verdicts = council.get("verdicts", [])
        reports = reports_council.recent_reports(n=5)
        timeline = reports_council.timeline_versions()

        # Tuiles
        git_val = git.get("describe") or git.get("head_commit") or "n/a"
        git_commit = (git.get("head_commit") or "")[:12] or "n/a"

        atoms_total = atoms.get("total", 0) if "error" not in atoms else "n/a"
        conv_total = conv if isinstance(conv, int) else "n/a"
        msgs_total = msgs if isinstance(msgs, int) else "n/a"
        raw_total = raw_conv if isinstance(raw_conv, int) else "n/a"
        ipq_total = ipq.get("total", 0) if "error" not in ipq else "n/a"
        mrq_total = mrq.get("total", 0) if "error" not in mrq else "n/a"

        loadavg = health.get("loadavg") or {}
        load_str = (
            f"{loadavg.get('1m', '?')} / {loadavg.get('5m', '?')} / {loadavg.get('15m', '?')}"
            if loadavg else "n/a"
        )
        arac_api_status = health.get("arac_api_status", "unknown")

        tmux_count = len(tmux)
        tags_count = len(timeline.get("tags", []))
        # POURQUOI cette tuile a changé de nom ET de clé : elle comptait des
        # les branches d'une convention de nommage propre à un dépôt particulier.
        # Le collecteur ne suppose plus aucune convention et ne suit que celle
        # que vous déclarez (ARAC_COCKPIT_RELEASE_BRANCHES) sous la clé
        # `release_branches` ; lire l'ancienne clé affichait donc 0 en
        # permanence, y compris chez qui avait déclaré la sienne — un zéro faux
        # est pire qu'une absence, il se mesure.
        release_count = len(timeline.get("release_branches", []))

        tiles_html = '<div class="tiles">'
        tiles_html += render_tile("Version Git", git_val, small=True)
        tiles_html += render_tile("Dernier commit", git_commit, small=True)
        tiles_html += render_tile("Atomes mémoire", atoms_total)
        tiles_html += render_tile("Conversations", conv_total)
        tiles_html += render_tile("Messages absorbés", msgs_total)
        # Zéro sur une table gelée n'est pas un zéro : c'est une absence. On ne
        # l'affiche donc que s'il y a une lignée à montrer, et on la nomme.
        if not isinstance(raw_total, int) or raw_total > 0:
            tiles_html += render_tile(
                "Conversations brutes (héritage V1, gelée)", raw_total, small=True
            )
        tiles_html += render_tile("IPQ total", ipq_total)
        tiles_html += render_tile("MRQ total", mrq_total)
        tiles_html += render_tile("tmux sessions", tmux_count)
        tiles_html += render_tile("Load avg (1m/5m/15m)", load_str, small=True)
        tiles_html += render_tile(_unite_api() + " status", arac_api_status, small=True)
        tiles_html += render_tile("Tags Git", tags_count)
        tiles_html += render_tile("Branches de version suivies", release_count)
        tiles_html += "</div>"

        # Tables secondaires
        verdicts_rows = [
            [v.get("session_id") or "—", v.get("candidate_id") or "—",
             v.get("final_decision") or "—", v.get("created_at") or "—"]
            for v in verdicts
        ]
        verdicts_html = "<h2>Derniers verdicts Council</h2>"
        # Même absence déclarée que sur /cc/council : sur le tableau de bord,
        # un panneau vide et muet donne l'impression d'un cerveau qui n'a rien
        # à raconter, alors que rien dans ce dépôt n'écrit ces sessions.
        verdicts_html += render_absence(council.get("reason"), council.get("gesture"))
        verdicts_html += render_table(
            ["Session", "Candidat", "Décision", "Date"], verdicts_rows
        )

        reports_rows = [[r.get("name") or "—", r.get("modified") or "—"] for r in reports]
        reports_html = "<h2>Derniers rapports</h2>"
        reports_html += render_table(["Fichier", "Modifié"], reports_rows)

        commits_rows = [[c] for c in git.get("last_commits", [])[:3]]
        commits_html = "<h2>Derniers commits</h2>"
        commits_html += render_table(["Commit"], commits_rows)

        refresh = render_refresh_link("/cc/")
        body = refresh + tiles_html + verdicts_html + reports_html + commits_html

        return render_page("Overview — Dashboard", body)

    # ------------------------------------------------------------------
    # Pages HTML détaillées (toutes protégées session HTML)
    # ------------------------------------------------------------------

    @a.get("/cc/memory", include_in_schema=False)
    async def memory_page(request: Request, principal: dict = Depends(_session_html)) -> Any:
        """Page détaillée : atomes mémoire (by_kind, by_scope, by_status)."""
        audit_read_log("/cc/memory", principal.get("sub", "?"))
        data = db_metrics.memory_atoms_summary()
        refresh = render_refresh_link("/cc/memory")

        if "error" in data:
            body = refresh + '<p class="unavailable">Base de données indisponible.</p>'
            return render_page("Mémoire — Atomes", body)

        # Total
        total_html = '<div class="tiles">' + render_tile("Total atomes", data["total"]) + "</div>"

        # by_kind
        kind_rows = sorted(data.get("by_kind", {}).items(), key=lambda x: -x[1])
        kind_html = "<h2>Par kind</h2>" + render_table(["Kind", "Nombre"], kind_rows)

        # by_scope
        scope_rows = sorted(data.get("by_scope", {}).items(), key=lambda x: -x[1])
        scope_html = "<h2>Par scope</h2>" + render_table(["Scope", "Nombre"], scope_rows)

        # by_status
        status_rows = sorted(data.get("by_status", {}).items(), key=lambda x: -x[1])
        status_html = "<h2>Par status</h2>" + render_table(["Status", "Nombre"], status_rows)

        body = refresh + total_html + kind_html + scope_html + status_html
        return render_page("Mémoire — Atomes", body)

    @a.get("/cc/queues", include_in_schema=False)
    async def queues_page(request: Request, principal: dict = Depends(_session_html)) -> Any:
        """Page détaillée : files IPQ + MRQ."""
        audit_read_log("/cc/queues", principal.get("sub", "?"))
        ipq = db_metrics.ipq_summary()
        mrq = db_metrics.mrq_summary()
        refresh = render_refresh_link("/cc/queues")

        # IPQ
        if "error" in ipq:
            ipq_html = "<h2>IPQ (Incoming Proposal Queue)</h2><p class=\"unavailable\">Indisponible.</p>"
        else:
            ipq_rows = sorted(ipq.get("by_status", {}).items(), key=lambda x: -x[1])
            ipq_html = (
                "<h2>IPQ (Incoming Proposal Queue)</h2>"
                + '<div class="tiles">' + render_tile("Total IPQ", ipq.get("total", 0)) + "</div>"
                + render_table(["Status", "Nombre"], ipq_rows)
            )

        # MRQ
        if "error" in mrq:
            mrq_html = "<h2>MRQ (Memory Review Queue)</h2><p class=\"unavailable\">Indisponible.</p>"
        else:
            mrq_rows = sorted(mrq.get("by_status", {}).items(), key=lambda x: -x[1])
            mrq_html = (
                "<h2>MRQ (Memory Review Queue)</h2>"
                + '<div class="tiles">' + render_tile("Total MRQ", mrq.get("total", 0)) + "</div>"
                + render_table(["Status", "Nombre"], mrq_rows)
            )

        body = refresh + ipq_html + mrq_html
        return render_page("Files — IPQ & MRQ", body)

    @a.get("/cc/council", include_in_schema=False)
    async def council_page(request: Request, principal: dict = Depends(_session_html)) -> Any:
        """Page détaillée : verdicts d'une délibération d'agents — si vous en avez une.

        Même règle que la page « Décisions » : le répertoire de sessions lu ici
        n'est écrit par aucun service de ce dépôt. Faire délibérer des agents est
        un usage qu'on branche, pas une pièce livrée — donc cette page est vide
        chez qui ne l'a pas branché.

        On passe par ``council_index`` et non par ``council_recent_verdicts`` :
        la seconde rend une liste, et une liste vide ne sait pas dire POURQUOI
        elle est vide. La première ajoute l'état de la source (répertoire absent
        / présent mais sans session) et le chemin exact consulté, sans changer
        la garantie « metadata seulement » qui reste dans le collecteur.
        """
        audit_read_log("/cc/council", principal.get("sub", "?"))
        data = reports_council.council_index(n=5)
        verdicts = data.get("verdicts", [])
        refresh = render_refresh_link("/cc/council")

        rows = [
            [v.get("session_id") or "—", v.get("candidate_id") or "—",
             v.get("final_decision") or "—", v.get("created_at") or "—"]
            for v in verdicts
        ]
        body = (
            refresh
            + '<div class="tiles">' + render_tile("Verdicts récents", len(verdicts)) + "</div>"
            + render_absence(data.get("reason"), data.get("gesture"))
            + render_table(["Session ID", "Candidat", "Décision", "Date"], rows)
        )
        return render_page("Council — Verdicts", body)

    @a.get("/cc/sobriety", include_in_schema=False)
    async def sobriety_page(request: Request, principal: dict = Depends(_session_html)) -> Any:
        """Page SOBRIÉTÉ : coût IA du cerveau (backlog, IA payante armée, Claude actif)."""
        audit_read_log("/cc/sobriety", principal.get("sub", "?"))
        s = sobriety.sobriety_summary()
        refresh = render_refresh_link("/cc/sobriety")

        bl = s.get("backlog") or {}
        claude = s.get("claude_running") or {}
        svc = s.get("curator_service") or {}
        armed = "🟢 OUI" if s.get("paid_ai_armed") else "🔴 NON"
        curator_claude = claude.get("curator_active")
        claude_txt = ("⚠️ OUI" if curator_claude is True
                      else ("non" if curator_claude is False else "?"))
        tiles = (
            render_tile("IA payante armée", armed)
            + render_tile("Claude curateur actif", claude_txt)
            + render_tile("env ARAC_ALLOW_PAID_AI", "on" if s.get("env_allow") else "off", small=True)
            + render_tile("flag paid_ai_enabled", s.get("paid_ai_enabled"), small=True)
            + render_tile("Conversations en attente (actionable)", bl.get("actionable"))
            + render_tile("pending / processing / failed",
                          f"{bl.get('pending')} / {bl.get('processing')} / {bl.get('failed')}")
            + render_tile("Curées aujourd'hui", bl.get("curated_today"))
            + render_tile("Dernière conversation reçue", bl.get("last_received"), small=True)
            + render_tile("Curator service / timer",
                          f"{svc.get('service_active')} / {svc.get('timer_active')}", small=True)
            + render_tile("Process claude (total)", claude.get("total"), small=True)
        )
        note = ("<p><em>Ingestion = toujours ON &amp; gratuite. La curation payante ne "
                "tourne que si « IA payante armée » = OUI, sous budget journalier borné. "
                "STOP immédiat : <code>arac-kill-paid-ai</code>.</em></p>")
        body = refresh + '<div class="tiles">' + tiles + "</div>" + note
        if s.get("db_error"):
            body += "<p>⚠️ DB indisponible — métriques backlog partielles.</p>"
        return render_page("Sobriété — IA payante", body)

    @a.get("/cc/reports", include_in_schema=False)
    async def reports_page(request: Request, principal: dict = Depends(_session_html)) -> Any:
        """Page détaillée : rapports docs/*.md (nom + mtime, jamais contenu)."""
        audit_read_log("/cc/reports", principal.get("sub", "?"))
        reports = reports_council.recent_reports(n=10)
        refresh = render_refresh_link("/cc/reports")

        rows = [[r.get("name") or "—", r.get("modified") or "—"] for r in reports]
        body = (
            refresh
            + '<div class="tiles">' + render_tile("Rapports docs/", len(reports)) + "</div>"
            + "<h2>Fichiers docs/*.md récents</h2>"
            + render_table(["Fichier", "Modifié (UTC)"], rows)
        )
        return render_page("Rapports", body)

    @a.get("/cc/decisions", include_in_schema=False)
    async def decisions_page(request: Request, principal: dict = Depends(_session_html)) -> Any:
        """Page détaillée : index des décisions D-NNN d'un registre que VOUS tenez.

        POURQUOI cette page peut être vide, et pourquoi elle le dit
        ------------------------------------------------------------
        Le fichier qu'elle indexe (``docs/DECISIONS.md``) n'est engendré par
        aucun code de ce dépôt : c'est un journal que le propriétaire du cerveau
        décide, ou non, de tenir. Un cerveau neuf n'en a pas, et cette page est
        alors vide pour de bon.

        Elle rendait auparavant un tableau vide, sans un mot. Chez un inconnu,
        cela se lit comme une panne — ou pire, comme un cockpit qui aurait perdu
        des données. L'état déclaré par le collecteur (``state``/``reason``/
        ``gesture``) est donc affiché : le lecteur apprend que le fichier
        n'existe pas, comment l'écrire, et que le cockpit l'indexera ensuite.
        """
        audit_read_log("/cc/decisions", principal.get("sub", "?"))
        data = reports_council.decisions_index()
        refresh = render_refresh_link("/cc/decisions")

        tiles_html = (
            '<div class="tiles">'
            + render_tile("Décisions totales", data.get("count", 0))
            + render_tile("Dernière D-", data.get("last_number") or "—")
            + "</div>"
        )
        rows = [
            [d.get("id") or "—", d.get("title") or "—"]
            for d in data.get("decisions", [])
        ]
        body = (
            refresh
            + tiles_html
            + "<h2>Index des décisions</h2>"
            + render_absence(data.get("reason"), data.get("gesture"))
            + render_table(["ID", "Titre"], rows)
        )
        return render_page("Décisions", body)

    @a.get("/cc/commits", include_in_schema=False)
    async def commits_page(request: Request, principal: dict = Depends(_session_html)) -> Any:
        """Page détaillée : derniers commits Git (5)."""
        audit_read_log("/cc/commits", principal.get("sub", "?"))
        git = system_metrics.git_version()
        refresh = render_refresh_link("/cc/commits")

        tiles_html = (
            '<div class="tiles">'
            + render_tile("Branche", git.get("branch") or "n/a", small=True)
            + render_tile("HEAD", (git.get("head_commit") or "n/a")[:16], small=True)
            + render_tile("Describe", git.get("describe") or "n/a", small=True)
            + "</div>"
        )
        rows = [[c] for c in git.get("last_commits", [])]
        body = (
            refresh
            + tiles_html
            + "<h2>Derniers commits (git log -5 --oneline)</h2>"
            + render_table(["Commit"], rows)
        )
        return render_page("Commits Git", body)

    @a.get("/cc/system", include_in_schema=False)
    async def system_page(request: Request, principal: dict = Depends(_session_html)) -> Any:
        """Page détaillée : santé serveur (loadavg, disque, arac-api, tunnels SSH + cockpit)."""
        audit_read_log("/cc/system", principal.get("sub", "?"))
        health = system_metrics.server_health()
        tunnel = system_metrics.ssh_tunnel_status()
        cockpit_status = system_metrics.cockpit_tunnel_status()
        refresh = render_refresh_link("/cc/system")

        loadavg = health.get("loadavg") or {}
        load_1m = loadavg.get("1m", "n/a")
        load_5m = loadavg.get("5m", "n/a")
        load_15m = loadavg.get("15m", "n/a")

        # Indicateur cockpit tunnel (point de couleur vert/rouge/gris + texte)
        _cockpit_dot = {
            "up":      '<span style="color:#3fb950;">&#9679;</span>',  # vert
            "down":    '<span style="color:#f85149;">&#9679;</span>',  # rouge
            "unknown": '<span style="color:#8b949e;">&#9679;</span>',  # gris
        }.get(cockpit_status, '<span style="color:#8b949e;">&#9679;</span>')
        _cockpit_label = {
            "up":      "UP",
            "down":    "DOWN",
            "unknown": "INCONNU",
        }.get(cockpit_status, "INCONNU")

        tiles_html = (
            '<div class="tiles">'
            + render_tile("Load avg 1m", load_1m)
            + render_tile("Load avg 5m", load_5m)
            + render_tile("Load avg 15m", load_15m)
            + render_tile(_unite_api(), health.get("arac_api_status", "unknown"), small=True)
            + render_tile("Tunnel SSH :2223", "oui" if tunnel.get("listener_2223") else "non")
            + "</div>"
        )

        disk_raw = health.get("disk") or "n/a"
        disk_html = (
            "<h2>Disque /opt (df -h)</h2>"
            f"<pre style='background:#161b22; padding:12px; border-radius:6px; "
            f"font-size:12px; overflow-x:auto;'>{html.escape(disk_raw)}</pre>"
        )
        tunnel_note = html.escape(tunnel.get("note", ""))
        tunnel_html = f"<h2>Tunnel SSH</h2><p>{tunnel_note}</p>"

        # Section tunnel cockpit V1.7E (reverse-forward :18100)
        cockpit_html = (
            "<h2>Tunnel cockpit (V1.7E)</h2>"
            f"<p>{_cockpit_dot} {html.escape(_cockpit_label)}"
            f" <small style='color:#8b949e;'>— marqueur reverse-forward :18100</small></p>"
        )

        body = refresh + tiles_html + disk_html + tunnel_html + cockpit_html
        return render_page("Santé Système", body)

    @a.get("/cc/tmux", include_in_schema=False)
    async def tmux_page(request: Request, principal: dict = Depends(_session_html)) -> Any:
        """Page détaillée : sessions tmux actives (lecture seule, tmux ls)."""
        audit_read_log("/cc/tmux", principal.get("sub", "?"))
        sessions = system_metrics.tmux_sessions()
        refresh = render_refresh_link("/cc/tmux")

        tiles_html = (
            '<div class="tiles">'
            + render_tile("Sessions tmux", len(sessions))
            + "</div>"
        )
        rows = [[s] for s in sessions]
        body = (
            refresh
            + tiles_html
            + "<h2>Sessions actives (tmux ls)</h2>"
            + render_table(["Session"], rows)
        )
        return render_page("Tmux Sessions", body)

    @a.get("/cc/timeline", include_in_schema=False)
    async def timeline_page(request: Request, principal: dict = Depends(_session_html)) -> Any:
        """Page détaillée : tags Git + branches de version de VOTRE convention.

        POURQUOI ce panneau ne cite plus aucune convention
        -------------------------------------------------
        Il affichait un motif de branches en dur et lisait la clé qui allait
        avec : la convention de nommage d'un dépôt particulier, gravée dans le
        cockpit de tout le monde. Chez qui nomme ses branches autrement, le
        panneau restait vide sans jamais dire pourquoi — et il apprenait au
        lecteur une convention qui n'était pas la sienne.

        Le collecteur ne suppose plus rien : il ne suit que le motif déclaré
        dans ``ARAC_COCKPIT_RELEASE_BRANCHES``, publie ses résultats sous
        ``release_branches`` et, à défaut de motif, une ``branch_reason``. Les
        tags, eux, sont universels : tout dépôt Git en a, ou n'en a pas.
        """
        audit_read_log("/cc/timeline", principal.get("sub", "?"))
        data = reports_council.timeline_versions()
        refresh = render_refresh_link("/cc/timeline")

        tags = data.get("tags", [])
        branches = data.get("release_branches", [])
        glob = data.get("branch_glob")

        tiles_html = (
            '<div class="tiles">'
            + render_tile("Tags Git", len(tags))
            + render_tile("Branches de version suivies", len(branches))
            + "</div>"
        )
        tags_html = "<h2>Tags Git (récents d'abord)</h2>" + render_table(["Tag"], [[t] for t in tags])
        titre_branches = (
            f"<h2>Branches suivies — {html.escape(str(glob))}</h2>" if glob
            else "<h2>Branches de version</h2>"
        )
        branches_html = (
            titre_branches
            # Sans motif déclaré, la liste est vide POUR UNE RAISON : le
            # collecteur la nomme, et la page la sert plutôt qu'un tableau muet.
            + render_absence(data.get("branch_reason"))
            + render_table(["Branche"], [[b] for b in branches])
        )

        body = refresh + tiles_html + tags_html + branches_html
        return render_page("Timeline", body)

    @a.get("/cc/brain", include_in_schema=False)
    async def brain_page(request: Request, principal: dict = Depends(_session_html)) -> Any:
        """Cockpit cerveau V1 — 4 sections READ-ONLY sur l'API `/v1/brain/*`.

        Brain Health · Current State · Proposals · Memory Quality.
        Données 100% live (aucune donnée fictive) ; chaque section dégrade gracieusement
        si l'API est indisponible. write_allowed=False côté API ; aucune valeur sensible affichée.
        """
        audit_read_log("/cc/brain", principal.get("sub", "?"))
        refresh = render_refresh_link("/cc/brain")

        def _unavail(title: str) -> str:
            return f"<h2>{html.escape(title)}</h2><p class=\"unavailable\">API Brain indisponible.</p>"

        # --- Section 1 : Brain Health ------------------------------------
        health = brain_api.brain_health()
        if "error" in health:
            health_html = _unavail("Brain Health")
        else:
            signals = health.get("headline_signals") or []
            recos = health.get("recommendations") or []
            health_tiles = (
                '<div class="tiles">'
                + render_tile("Health score", f"{health.get('health_score', '—')}/100")
                + render_tile("Sévérité", health.get("severity", "—"), small=True)
                + render_tile("write_allowed", str(health.get("write_allowed", "—")), small=True)
                + render_tile("Généré", health.get("generated_at", "—"), small=True)
                + "</div>"
            )
            signals_html = "<h3>Signaux</h3>" + render_table(
                ["Signal"], [[s] for s in signals[:8]]
            )
            recos_html = "<h3>Recommandations</h3>" + render_table(
                ["Priorité", "Code", "Scope", "Action"],
                [[r.get("priority", "—"), r.get("code", "—"), r.get("scope", "—"), r.get("action", "—")]
                 for r in recos[:10] if isinstance(r, dict)],
            )
            health_html = "<h2>Brain Health</h2>" + health_tiles + signals_html + recos_html

        # --- Section 2 : Current State -----------------------------------
        cs = brain_api.current_state()
        if "error" in cs:
            cs_html = _unavail("Current State")
        else:
            scopes = cs.get("scopes") or []
            cs_tiles = (
                '<div class="tiles">'
                + render_tile("Couverture", f"{cs.get('coverage_pct', '—')}%")
                + render_tile("Feuilles éligibles", cs.get("eligible_leaf_total", "—"))
                + render_tile("Avec état courant", cs.get("with_current_state", "—"))
                + "</div>"
            )
            def _fresh(v: Any) -> Any:
                return round(v, 1) if isinstance(v, (int, float)) else "—"

            cs_rows = [
                [s.get("scope") or "—", s.get("risk") or "—",
                 "oui" if s.get("has_current_state") else "non",
                 "oui" if s.get("state_dirty") else "non",
                 s.get("active_count") if s.get("active_count") is not None else "—",
                 _fresh(s.get("freshness_days"))]
                for s in scopes[:30] if isinstance(s, dict)
            ]
            cs_table = render_table(
                ["Scope", "Risque", "État courant", "Dirty", "Atomes", "Fraîcheur (j)"], cs_rows
            )
            cs_html = "<h2>Current State</h2>" + cs_tiles + cs_table

        # --- Section 3 : Proposals ---------------------------------------
        props = brain_api.proposals()
        if "error" in props:
            props_html = _unavail("Proposals")
        else:
            plist = props.get("proposals") or []
            props_tiles = (
                '<div class="tiles">'
                + render_tile("Propositions", props.get("count", 0))
                + "</div>"
            )
            props_rows = [
                [p.get("proposal_id") or p.get("id") or "—",
                 p.get("scope") or "—",
                 # schéma réel = ProposalSummaryItem : lifecycle_state / status (jamais 'lifecycle' dict)
                 p.get("lifecycle_state") or p.get("status") or "—",
                 # schéma réel = confidence_score (numérique) ou confidence_level (texte)
                 p.get("confidence_score") if p.get("confidence_score") is not None
                 else (p.get("confidence_level") or "—")]
                for p in plist[:25] if isinstance(p, dict)
            ]
            props_table = render_table(
                ["ID", "Scope", "Statut", "Confiance"], props_rows
            )
            # POURQUOI CETTE PAGE DIT OÙ LE GESTE SE FAIT
            # -------------------------------------------
            # C'est la seule chose du cockpit qui ressemble à une file
            # d'attente : un identifiant, un statut, une confiance, et rien
            # pour agir. Un lecteur à qui la documentation a promis « ouvrez
            # votre cockpit chaque semaine et tranchez quelques propositions »
            # arrive ici, cherche le bouton, et conclut que quelque chose est
            # cassé chez lui.
            #
            # Rien n'est cassé : le cockpit n'a AUCUNE route d'écriture — sa
            # seule méthode mutatrice est POST /cc/login, qui pose un cookie.
            # Et l'API ne permet pas davantage la promotion promise :
            # `confidence` est absent de `AtomUpdate` (PATCH /v1/atoms/{id}) et
            # la supersédure RECOPIE la confiance de l'atome remplacé
            # (`old["confidence"]`, app/routers/atoms.py). Un atome naît avec
            # sa confiance et meurt avec elle.
            #
            # La page n'a donc pas à faire semblant. Elle nomme ce qu'elle est
            # — une lecture — et l'endroit où le geste existe réellement.
            props_note = render_limite(
                "le cockpit lit ces propositions, il ne les tranche pas : il "
                "n'a aucune route d'écriture, et la confiance d'un atome ne "
                "peut pas être modifiée après sa naissance",
                "en conversation avec Claude, qui écrit par l'API : "
                "POST /v1/atoms pour un atome validé, "
                "POST /v1/atoms/{id}/supersede pour remplacer un atome dépassé",
            )
            props_html = "<h2>Proposals</h2>" + props_tiles + props_note + props_table

        # --- Section 4 : Memory Quality ----------------------------------
        mq = brain_api.memory_quality()
        ad = mq.get("anti_drift") or {}
        sens = mq.get("sensitivity") or {}
        if "error" in ad and "error" in sens:
            mq_html = _unavail("Memory Quality")
        else:
            by_risk = sens.get("by_risk") or {}
            mq_tiles = (
                '<div class="tiles">'
                + render_tile("Scopes (total)", sens.get("total_scopes", "—"))
                + render_tile("Risque high", by_risk.get("high", "—"))
                + render_tile("Risque medium", by_risk.get("medium", "—"))
                + render_tile("Risque low", by_risk.get("low", "—"))
                + "</div>"
            )
            warnings = ad.get("warnings") or []
            warn_rows = [
                [w.get("code", "—"), w.get("severity", "—"), w.get("scope", "—"),
                 w.get("description", "—")]
                for w in warnings[:20] if isinstance(w, dict)
            ]
            warn_table = "<h3>Avertissements anti-dérive</h3>" + render_table(
                ["Code", "Sévérité", "Scope", "Description"], warn_rows
            )
            mq_html = "<h2>Memory Quality</h2>" + mq_tiles + warn_table

        body = refresh + health_html + cs_html + props_html + mq_html
        return render_page("Brain — Cerveau", body)

    # ------------------------------------------------------------------
    # Cockpit PERCEPTION (V5 vague 1) — 13 routes GET, même protection
    # session + audit_read_log(route, principal) que l'existant.
    # ------------------------------------------------------------------

    register_perception_routes(a, _session_html)

    # ------------------------------------------------------------------
    # Routes API JSON read-only (protégées session, retournent 401)
    # ------------------------------------------------------------------

    @a.get("/cc/api/overview")
    async def api_overview(principal: dict = Depends(_session_api)) -> JSONResponse:
        """Vue JSON consolidée : atoms, queues, git, health, timeline.

        READ-ONLY. Toutes les données viennent des collecteurs.
        Aucune écriture DB ni action système.
        """
        audit_read_log("/cc/api/overview", principal.get("sub", "?"))
        return JSONResponse({
            "atoms": db_metrics.memory_atoms_summary(),
            # `raw_conversations` reste servie — c'est la LIGNÉE V1, gelée — et
            # les deux clés qui bougent réellement l'accompagnent désormais.
            # Une vue « consolidée » qui ne porte que le compteur mort décrit un
            # cerveau qui n'a rien absorbé, quel que soit ce qu'il a absorbé.
            "conversations": db_metrics.conversations_count(),
            "raw_messages": db_metrics.raw_messages_count(),
            "raw_conversations": db_metrics.raw_conversations_count(),
            "ipq": db_metrics.ipq_summary(),
            "mrq": db_metrics.mrq_summary(),
            "git": system_metrics.git_version(),
            "health": system_metrics.server_health(),
            "tunnel": system_metrics.ssh_tunnel_status(),
            "timeline": reports_council.timeline_versions(),
        })

    @a.get("/cc/api/memory")
    async def api_memory(principal: dict = Depends(_session_api)) -> JSONResponse:
        """Résumé JSON des atomes mémoire (by_kind, by_scope, by_status).

        READ-ONLY. Collecteur db_metrics.memory_atoms_summary() uniquement.
        """
        audit_read_log("/cc/api/memory", principal.get("sub", "?"))
        return JSONResponse(db_metrics.memory_atoms_summary())

    @a.get("/cc/api/queues")
    async def api_queues(principal: dict = Depends(_session_api)) -> JSONResponse:
        """Résumé JSON des files IPQ + MRQ.

        READ-ONLY. Collecteurs db_metrics.ipq_summary() + mrq_summary().
        """
        audit_read_log("/cc/api/queues", principal.get("sub", "?"))
        return JSONResponse({
            "ipq": db_metrics.ipq_summary(),
            "mrq": db_metrics.mrq_summary(),
        })

    @a.get("/cc/api/council")
    async def api_council(principal: dict = Depends(_session_api)) -> JSONResponse:
        """Metadata JSON des 5 derniers verdicts Council + décisions index.

        READ-ONLY. Collecteurs reports_council uniquement.
        Aucun contenu de review / transcript / rationale extrait.
        """
        audit_read_log("/cc/api/council", principal.get("sub", "?"))
        # `council_index` plutôt que la liste nue : un client JSON doit pouvoir
        # distinguer « aucune délibération n'a eu lieu » de « la source n'existe
        # pas », exactement comme le lecteur de la page HTML. La clé `verdicts`
        # garde la même forme et la même garantie « metadata seulement ».
        return JSONResponse({
            "council": reports_council.council_index(n=5),
            "verdicts": reports_council.council_recent_verdicts(n=5),
            "decisions": reports_council.decisions_index(),
        })

    @a.get("/cc/api/system")
    async def api_system(principal: dict = Depends(_session_api)) -> JSONResponse:
        """Santé système JSON : git, health, tunnel, tmux, timeline.

        READ-ONLY. Collecteurs system_metrics + reports_council uniquement.
        """
        audit_read_log("/cc/api/system", principal.get("sub", "?"))
        return JSONResponse({
            "git": system_metrics.git_version(),
            "health": system_metrics.server_health(),
            "tunnel": system_metrics.ssh_tunnel_status(),
            "tmux": system_metrics.tmux_sessions(),
            "timeline": reports_council.timeline_versions(),
        })

    # ------------------------------------------------------------------
    # BFF du cockpit vivant — routes /cc/v1/* (ADDITIF, READ-ONLY, GET only)
    # ------------------------------------------------------------------
    #
    # L'enregistrement est délégué à control_center/cc_v1/routes.py, qui
    # applique la même doctrine que ce module (@a.get uniquement, garde de
    # session, journal de lecture). Cette fonction reste la source unique de
    # vérité du routage : c'est ici qu'on voit que /cc/v1/* existe.
    #
    # Principe cardinal du cockpit : chaque métrique servie porte une preuve
    # résolvable — une métrique sans preuve ne peut pas être instanciée.

    from control_center.cc_v1 import routes as cc_v1_routes

    cc_v1_routes.register(a, session_api=_session_api, audit_read_log=audit_read_log)


# ============================================================================
# Dépendances FastAPI interne (wrappers require_session)
# ============================================================================
#
# require_session(html=True)  → renvoie 302 /cc/login si pas de session
# require_session(html=False) → renvoie 401 JSON si pas de session
#
# Ces wrappers permettent d'utiliser Depends() proprement dans les handlers.


async def _session_html(request: Request) -> dict:
    """Dépendance FastAPI : session requise, mode HTML (redirect → /cc/login)."""
    try:
        return await require_session(request, html=False)
    except Exception:
        # Redirect vers /cc/login pour les pages HTML
        from fastapi import HTTPException
        raise HTTPException(
            status_code=302,
            headers={"Location": "/cc/login"},
            detail="Session requise",
        )


async def _session_api(request: Request) -> dict:
    """Dépendance FastAPI : session requise, mode API (retourne 401 JSON)."""
    return await require_session(request, html=False)


# ============================================================================
# Instance module-level (pour uvicorn direct)
# ============================================================================
#
# NOTE : Cette app N'EST PAS montée dans app/main.py.
#         Isolation totale — activation en phase ultérieure, sur décision
#         explicite de l'opérateur.
#         Aucun fichier systemd n'est créé par ce module.

app: FastAPI = create_app()
