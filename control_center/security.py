"""ARAC — Control Center : couche de sécurité (stdlib uniquement).

Doctrine : OBSERVE FIRST. DO NOT CONTROL.
Ce module implémente la LOGIQUE d'authentification du Control Center.
Il ne contient aucun endpoint POST de login — ceux-ci sont différés à la
phase de durcissement (V1.7C+) pour permettre une validation indépendante
de la logique crypto avant câblage HTTP.

Garanties hardcodées :
  - 0 dépendance externe (stdlib uniquement : hmac, hashlib, base64, json,
    os, struct, time, secrets, pathlib).
  - 0 secret ou mot de passe en clair.
  - 0 import de provider HTTP (requests, httpx, aiohttp, openai, etc.).
  - 0 écriture en base de données.

Contenu :
  1. TOTP RFC 6238 (HMAC-SHA1, step=30s, 6 digits) — totp_now / totp_verify
  2. Hachage mot de passe — hash_password / verify_password (pbkdf2_sha256)
  3. Session signée HMAC-SHA256 — sign_session / verify_session
  4. Dépendance FastAPI — require_session (gate READ-ONLY, aucune écriture)
  5. Log d'audit des consultations — audit_read_log (append-only, sans PII)

Note fail2ban (phase durcissement) :
  Les échecs d'authentification (TOTP invalide, mot de passe erroné, session
  rejetée) DOIVENT être loggués dans un fichier dédié que fail2ban peut
  surveiller. Pattern suggéré : « CC_AUTH_FAIL » dans /var/log/arac/<cerveau>/
  cc_auth_fail.log. La configuration fail2ban sera ajoutée en V1.7C.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import os
import pathlib
import secrets
import struct
import time
from typing import Any

from fastapi import HTTPException, Request

from control_center.config import (
    CC_SESSION_SECRET_ENV,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    local_trusted_tunnel_enabled,
)


# ============================================================================
# 1. TOTP RFC 6238 (HMAC-SHA1, step=30s, 6 digits)
# ============================================================================


def _hotp(key_bytes: bytes, counter: int, digits: int = 6) -> str:
    """HOTP RFC 4226 : un code HMAC-SHA1 pour un counter donné.

    Args:
        key_bytes: clé secrète en bytes (décodée depuis base32).
        counter:   valeur du compteur (entier non signé 64 bits big-endian).
        digits:    nombre de chiffres du code (généralement 6).

    Returns:
        Code OTP zéro-paddé sur ``digits`` caractères.
    """
    msg = struct.pack(">Q", counter)
    h = hmac.new(key_bytes, msg, hashlib.sha1).digest()
    # Dynamic truncation RFC 4226 §5.3
    offset = h[-1] & 0x0F
    truncated = struct.unpack(">I", h[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10**digits)).zfill(digits)


def totp_now(
    secret_b32: str,
    t: float | None = None,
    step: int = 30,
    digits: int = 6,
) -> str:
    """Génère le code TOTP courant pour un secret base32 (RFC 6238, HMAC-SHA1).

    Args:
        secret_b32: secret TOTP encodé en base32 (insensible à la casse,
                    les espaces sont ignorés).
        t:          timestamp Unix (float). Par défaut : time.time().
        step:       durée d'une fenêtre TOTP en secondes (défaut : 30).
        digits:     nombre de chiffres du code (défaut : 6).

    Returns:
        Code TOTP à ``digits`` chiffres, zéro-paddé.

    Raises:
        binascii.Error: si ``secret_b32`` n'est pas un base32 valide.
    """
    if t is None:
        t = time.time()
    key_bytes = base64.b32decode(secret_b32.upper().replace(" ", ""))
    counter = int(t) // step
    return _hotp(key_bytes, counter, digits)


def totp_verify(
    secret_b32: str,
    code: str,
    t: float | None = None,
    step: int = 30,
    digits: int = 6,
    window: int = 1,
) -> bool:
    """Vérifie un code TOTP en autorisant une fenêtre de ± ``window`` steps.

    La comparaison est constante (secrets.compare_digest) pour éviter les
    attaques de timing.

    Args:
        secret_b32: secret TOTP base32.
        code:       code soumis par l'utilisateur (string, peut contenir
                    des espaces).
        t:          timestamp de référence (défaut : time.time()).
        step:       durée d'une fenêtre en secondes (défaut : 30).
        digits:     nombre de chiffres attendu (défaut : 6).
        window:     nombre de fenêtres de tolérance de chaque côté (défaut : 1,
                    soit ± 30 secondes autour du step courant).

    Returns:
        True si le code correspond à l'un des steps dans la fenêtre.
    """
    if t is None:
        t = time.time()
    key_bytes = base64.b32decode(secret_b32.upper().replace(" ", ""))
    current_counter = int(t) // step
    code_clean = code.replace(" ", "").zfill(digits)
    for offset in range(-window, window + 1):
        expected = _hotp(key_bytes, current_counter + offset, digits)
        if secrets.compare_digest(expected, code_clean):
            return True
    return False


# ============================================================================
# 2. Hachage mot de passe (pbkdf2_sha256)
# ============================================================================

_PBKDF2_ITERATIONS: int = 260_000
"""Nombre d'itérations PBKDF2-HMAC-SHA256.

260 000 est au-dessus du minimum OWASP 2024 (210 000) et cohérent avec
le coût acceptable sur une petite instance Hetzner pour un seul admin.
La valeur est encodée dans le hash stocké → elle peut être augmentée lors
d'une rotation de mot de passe sans casser les anciens hashes.
"""

_HASH_FORMAT: str = "pbkdf2_sha256${iterations}${salt_hex}${hash_hex}"
"""Format du hash stocké — documenté ici, construit dans hash_password()."""


def hash_password(pw: str, salt: bytes | None = None) -> str:
    """Hache un mot de passe avec PBKDF2-HMAC-SHA256.

    Format de sortie : ``pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>``

    Exemples :
        stored = hash_password("mot_de_passe_fort")
        # → "pbkdf2_sha256$260000$a1b2c3...$d4e5f6..."

    Le résultat est destiné à être stocké dans la variable d'env
    CC_ADMIN_PASSWORD_HASH (jamais en clair dans le code ou le dépôt).

    Args:
        pw:   mot de passe en clair (string). JAMAIS loggué, jamais stocké.
        salt: sel en bytes (16 bytes recommandés). Par défaut : généré
              aléatoirement via os.urandom(16).

    Returns:
        Chaîne formatée ``pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>``.
    """
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        pw.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    """Vérifie un mot de passe contre un hash pbkdf2_sha256 stocké.

    La comparaison finale est constante (hmac.compare_digest) pour éviter
    les attaques de timing sur le digest hex.

    Args:
        pw:     mot de passe à vérifier (string en clair).
        stored: hash au format ``pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>``.

    Returns:
        True si le mot de passe correspond, False sinon (y compris si le
        format du hash stocké est invalide).
    """
    try:
        parts = stored.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected_hex = parts[3]
    except (ValueError, IndexError):
        return False

    dk = hashlib.pbkdf2_hmac(
        "sha256",
        pw.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(dk.hex(), expected_hex)


# ============================================================================
# 3. Session signée HMAC-SHA256
# ============================================================================


def sign_session(payload: dict[str, Any], secret: str) -> str:
    """Crée un token de session signé HMAC-SHA256.

    Format : ``<b64url_payload>.<hex_signature>``

    - payload : dict JSON sérialisable. Le champ ``iat`` (issued-at, Unix
      timestamp int) est ajouté automatiquement s'il est absent.
    - Pas de PII dans le payload : stocker uniquement des identifiants
      (ex : ``{"sub": "admin", "iat": 1718000000}``).

    Args:
        payload: données à embarquer dans le token (sans PII).
        secret:  clé HMAC (valeur de CC_SESSION_SECRET).

    Returns:
        Token ``<b64url_payload>.<hex_signature>``.
    """
    if "iat" not in payload:
        payload = {**payload, "iat": int(time.time())}
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    b64_payload = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    sig = hmac.new(secret.encode("utf-8"), b64_payload.encode(), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{sig}"


def verify_session(
    token: str,
    secret: str,
    ttl: int = SESSION_TTL_SECONDS,
) -> dict[str, Any] | None:
    """Vérifie et décode un token de session.

    Vérifie dans l'ordre :
      1. Format correct (deux parties séparées par un point).
      2. Signature HMAC-SHA256 (comparaison constante).
      3. Présence du champ ``iat``.
      4. Expiration : ``now - iat <= ttl``.

    Args:
        token:  token au format ``<b64url_payload>.<hex_signature>``.
        secret: clé HMAC (valeur de CC_SESSION_SECRET).
        ttl:    durée de vie maximale en secondes (défaut : SESSION_TTL_SECONDS).

    Returns:
        dict du payload si le token est valide et non expiré.
        None sinon (token invalide, signature trafiquée, expiré, secret vide).
    """
    # Garde fail-closed : un secret vide signerait et vérifierait contre lui-même.
    # On échoue fermé ici indépendamment du garde d'env de require_session, afin
    # qu'un futur appelant direct (POST /cc/login V1.7C, script, test) ne puisse
    # pas accepter silencieusement des sessions forgées avec secret=''.
    if not secret:
        return None

    try:
        b64_payload, provided_sig = token.rsplit(".", 1)
    except ValueError:
        return None

    # Vérification signature (constante)
    expected_sig = hmac.new(
        secret.encode("utf-8"), b64_payload.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_sig, provided_sig):
        return None

    # Décodage payload
    try:
        # Repadding base64url
        padding = 4 - len(b64_payload) % 4
        padded = b64_payload + ("=" * (padding % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, binascii.Error, json.JSONDecodeError):
        # Fail-closed uniquement sur les erreurs de token malformé attendues.
        # On ne capture pas Exception nu pour laisser remonter les vrais bugs.
        return None

    # Vérification expiration
    iat = payload.get("iat")
    if not isinstance(iat, (int, float)):
        return None
    if time.time() - float(iat) > ttl:
        return None

    return payload


# ============================================================================
# 4. Dépendance FastAPI — require_session
# ============================================================================


# Headers qu'un reverse-proxy ajoute mais qu'une connexion directe (navigateur via
# tunnel SSH) n'envoie jamais. Leur présence signale une requête NON directe → on
# refuse le bypass de confiance loopback (défense en profondeur).
_FORWARDING_HEADERS: tuple[str, ...] = (
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-forwarded-port",
    "x-real-ip",
    "forwarded",
)


def _request_has_forwarding_headers(request: Request) -> bool:
    """True si la requête porte un header de reverse-proxy/forwarding.

    Un navigateur en connexion DIRECTE (tunnel SSH -L vers 127.0.0.1) n'envoie aucun
    de ces headers. Leur présence => requête relayée par un proxy => le bypass de
    confiance loopback est REFUSÉ (l'auth normale login/TOTP s'applique). C'est une
    décision de REFUS basée sur un header (fail-secure) — jamais un OCTROI basé sur
    un header.
    """
    return any(h in request.headers for h in _FORWARDING_HEADERS)


def is_loopback(host: str | None) -> bool:
    """True si host est une adresse loopback (127.0.0.0/8 ou ::1).

    Robuste par construction : host None/vide/malformé => False (jamais de
    bypass sur une entrée douteuse — fail-secure). Utilise ipaddress pour
    couvrir tout le bloc loopback, pas seulement la chaîne "127.0.0.1".
    """
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


async def require_session(
    request: Request,
    html: bool = False,
) -> dict[str, Any]:
    """Dépendance FastAPI : vérifie la session Control Center (READ-ONLY gate).

    Lit le cookie ``cc_session``, vérifie la signature et l'expiration via
    ``verify_session()``. La clé est lue depuis l'env ``CC_SESSION_SECRET``
    au moment de l'appel (jamais en cache module-level pour éviter que le
    secret soit figé avant rotation).

    Ce gate est un mécanisme de LECTURE : il protège l'accès aux données
    observées, il n'écrit rien.

    Note : l'endpoint POST /cc/login (qui crée la session) est différé à la
    phase de durcissement V1.7C. Jusqu'à cette phase, require_session peut
    être utilisé dans les tests unitaires en fournissant un cookie valide
    généré via sign_session().

    Args:
        request: objet FastAPI Request (injecté automatiquement).
        html:    si True, redirige vers /cc/login au lieu de lever 401.
                 (Réservé phase V1.7C — actuellement toujours 401.)

    Returns:
        dict du payload de session (champs : ``sub``, ``iat``, etc.).

    Raises:
        HTTPException(401): si le cookie est absent, invalide ou expiré.
    """
    # ------------------------------------------------------------------
    # V1.7D — LOCAL TRUSTED TUNNEL (bypass d'auth pour le tunnel SSH de confiance)
    #
    # Le bypass n'est accordé QUE si TOUTES ces conditions tiennent :
    #   1. le flag LOCAL_TRUSTED_TUNNEL est activé ;
    #   2. le pair TCP est loopback (127.0.0.0/8 ou ::1) ;
    #   3. AUCUN header de forwarding n'est présent (connexion DIRECTE, pas proxifiée).
    #
    # Frontière de confiance : le service est lancé avec uvicorn --no-proxy-headers
    # (cf. arac-control-center.service), donc request.client.host est le PAIR TCP RÉEL
    # et N'EST PAS dérivé d'un X-Forwarded-For. (Le défaut uvicorn proxy_headers=True
    # laisserait un pair de confiance réécrire client via XFF — d'où --no-proxy-headers.)
    # La condition 3 ajoute une défense en profondeur : même si un reverse-proxy était
    # un jour placé devant le service, ses requêtes (porteuses de X-Forwarded-*) ne
    # bypasseraient pas — l'auth login/TOTP resterait exigée pour tout accès externe.
    #
    # ATTENTION mainteneur : ce bypass fait confiance à un accès loopback DIRECT (tunnel
    # SSH = clé authentifiée). Si un reverse-proxy est ajouté pour exposer le service à
    # l'extérieur, DÉSACTIVER LOCAL_TRUSTED_TUNNEL. Accès accordé = strictement READ-ONLY.
    # ------------------------------------------------------------------
    if local_trusted_tunnel_enabled():
        client_host = request.client.host if request.client else None
        if is_loopback(client_host) and not _request_has_forwarding_headers(request):
            return {"sub": "admin", "auth": "local_trusted_tunnel"}

    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie_value:
        raise HTTPException(
            status_code=401,
            detail="Session Control Center absente ou expirée. Authentifiez-vous.",
        )

    secret = os.environ.get(CC_SESSION_SECRET_ENV, "")
    if not secret:
        # Configuration manquante — refuse l'accès plutôt que de le laisser passer
        raise HTTPException(
            status_code=503,
            detail=f"Variable d'env {CC_SESSION_SECRET_ENV!r} non configurée.",
        )

    payload = verify_session(cookie_value, secret)
    if payload is None:
        raise HTTPException(
            status_code=401,
            detail="Session invalide ou expirée. Ré-authentifiez-vous.",
        )

    return payload


# ============================================================================
# 5. Log d'audit des consultations (append-only, sans PII)
# ============================================================================

# Le nom du cerveau vient de la configuration de l'utilisateur, jamais du dépôt
# dont ce code est issu. Écrire « /var/log/arac/<cerveau>/ » ici plaçait les journaux
# de TOUS les cerveaux dans un dossier portant le nom de l'installation d'origine
# — et rendait fausse la promesse d'`arac_runtime` : aucun chemin absolu en dur.
def _cc_log_dir() -> str:
    """Le dossier de journaux de CE cerveau.

    La source d'autorité est ARAC_LOG_DIR, que l'unité du cockpit engendrée
    par le bootstrap pose et qui porte la valeur EXACTE que le bootstrap a
    créée sur le disque. Un seul calcul, une seule vérité.

    À défaut seulement, on reconstruit le nom à partir de ARAC_BRAIN_NAME en
    reproduisant l'assainissement du bootstrap — voir le corps de la fonction
    pour ce que coûtait la divergence.

    Volontairement PAS d'import de `arac_runtime` ni de `re` : ce module est
    la couche d'authentification, et sa valeur tient à sa surface minimale —
    un test le vérifie ligne à ligne.
    """
    declare = (os.environ.get("ARAC_LOG_DIR") or "").strip()
    if declare:
        return declare.rstrip("/")

    # SANS ARAC_LOG_DIR, ON ASSAINIT COMME LE BOOTSTRAP ASSAINIT.
    #
    # Ce module lisait ARAC_BRAIN_NAME BRUT et écrivait « /var/log/arac/<nom> ».
    # Le bootstrap, lui, crée « /var/log/arac/$ARAC_DB », où ARAC_DB est le nom
    # ASSAINI (bootstrap/lib/config.sh) : tout ce qui n'est pas [a-zA-Z0-9]
    # devient « _ », puis le tout passe en minuscules. Deux calculs, deux
    # vérités — et elles divergent dès qu'un nom porte une majuscule ou un
    # tiret, ce qui est le cas le plus courant qui soit (« Zoe-Brain »).
    #
    # Le cockpit écrivait alors son journal d'audit dans /var/log/arac/Zoe-Brain
    # quand le seul dossier qu'il a le droit d'écrire est /var/log/arac/zoe_brain.
    # Sous ProtectSystem=strict, l'écriture échoue et le journal d'accès bascule
    # silencieusement sur /tmp : la trace des consultations d'une mémoire privée
    # se met à vivre dans un dossier lisible et volatile, sans que rien ne le dise.
    nom = (os.environ.get("ARAC_BRAIN_NAME") or "").strip()
    # Reproduction EXACTE de `tr -c 'a-zA-Z0-9' '_' | sed 's/_*$//'` puis
    # minuscules, sans importer `re` : ce module tient sa valeur de sa surface
    # minimale, et un test la vérifie ligne à ligne.
    assaini = "".join(
        c if (c.isascii() and c.isalnum()) else "_" for c in nom
    ).rstrip("_").lower()
    if not assaini:
        # Cockpit sans identité déclarée : on n'invente pas un dossier sous
        # la racine commune. Celle-ci n'appartient à personne, donc à tout le
        # monde — deux cockpits anonymes y mêleraient leurs traces d'accès au
        # moment précis où l'on cherche QUI a consulté quelle mémoire. On
        # descend directement sur le repli volatile, qui est déjà le
        # comportement quand le dossier propre n'est pas inscriptible.
        return _CC_LOG_FALLBACK_DIR
    return f"/var/log/arac/{assaini}"


_CC_LOG_FALLBACK_DIR: str = "/tmp/arac_cc"
_CC_LOG_FALLBACK: str = "/tmp/arac_cc/access.log"

_CC_LOG_PRIMARY: str = f"{_cc_log_dir()}/cc_access.log"

_CC_AUTH_FAIL_LOG_PRIMARY: str = f"{_cc_log_dir()}/cc_auth_fail.log"
_CC_AUTH_FAIL_LOG_FALLBACK: str = "/tmp/arac_cc/cc_auth_fail.log"


def _ensure_log_file(path: str) -> bool:
    """Tente de créer le fichier de log avec permissions 0600.

    Returns:
        True si le fichier est prêt (créé ou déjà existant et writable).
        False si la création échoue.
    """
    p = pathlib.Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.touch(mode=0o600)
        else:
            # Vérifier que les permissions sont 0600 (restrictif)
            current_mode = p.stat().st_mode & 0o777
            if current_mode != 0o600:
                p.chmod(0o600)
        return os.access(path, os.W_OK)
    except OSError:
        return False


def _get_log_path() -> str:
    """Retourne le chemin du fichier de log d'accès CC.

    Priorité : /var/log/arac/<cerveau>/cc_access.log si writable,
    sinon /tmp/arac_cc/access.log (fallback).
    """
    if _ensure_log_file(_CC_LOG_PRIMARY):
        return _CC_LOG_PRIMARY
    _ensure_log_file(_CC_LOG_FALLBACK)
    return _CC_LOG_FALLBACK


def auth_fail_log(client_ip: str, reason: str) -> None:
    """Logue un échec d'authentification Control Center (pour fail2ban).

    Ce log est distinct du log d'accès (cc_access.log). Il est destiné à être
    surveillé par fail2ban pour bannir les IPs après N tentatives échouées.

    Format stable et parsable :
        <ISO8601> CC_AUTH_FAIL client_ip=<ip> reason=<reason>

    Garanties :
      - JAMAIS de secret, mot de passe, ni code TOTP dans ce log.
      - Sanitize \\n\\r dans client_ip et reason (anti log-injection).
      - Append-only, permissions 0600 (lecture seule root).
      - Fallback /tmp/arac_cc/cc_auth_fail.log si /var/log/arac/<cerveau>/ non writable.
      - Non-fatal : un échec d'écriture ne bloque pas le rejet de la requête.

    Note fail2ban : configurer un filtre sur le pattern ``CC_AUTH_FAIL`` et
    banir après 5 tentatives en 10 minutes (cf. docs/RUNBOOK.md section
    « fail2ban Control Center »).

    Args:
        client_ip: adresse IP du client (request.client.host). Sanitizée.
        reason:    raison de l'échec : "bad_password", "bad_totp",
                   "not_provisioned". JAMAIS la valeur du secret.
    """
    # Sanitize anti-injection de log : \n ou \r forgeraient de fausses lignes
    client_ip = str(client_ip).replace("\n", " ").replace("\r", " ")[:64]
    reason = str(reason).replace("\n", " ").replace("\r", " ")[:64]
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    line = f"{ts} CC_AUTH_FAIL client_ip={client_ip} reason={reason}\n"

    # Choix du fichier de log (primary → fallback)
    if _ensure_log_file(_CC_AUTH_FAIL_LOG_PRIMARY):
        log_path = _CC_AUTH_FAIL_LOG_PRIMARY
    else:
        _ensure_log_file(_CC_AUTH_FAIL_LOG_FALLBACK)
        log_path = _CC_AUTH_FAIL_LOG_FALLBACK

    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        # Non-fatal : l'échec de log ne doit pas masquer le rejet de la requête.
        pass


def audit_read_log(request_path: str, principal: str) -> None:
    """Logue une consultation Control Center (append-only, sans données sensibles).

    Ce log documente qui a consulté quelle page et quand. Il n'enregistre
    jamais de données sensibles (pas de payload d'atome, pas de secret,
    pas de PII au-delà du principal/identifiant de session).

    Note fail2ban (phase durcissement V1.7C) :
        Les échecs d'authentification seront loggués séparément dans
        cc_auth_fail.log avec le tag CC_AUTH_FAIL pour permettre à fail2ban
        de bannir les IPs après N tentatives échouées.

    Format de ligne :
        ISO8601 | CC_ACCESS | <principal> | <request_path>

    Le fichier est en mode 0600 (lecture seule root). La rotation log est
    à gérer via logrotate (cf. docs/RUNBOOK.md section « Rotation logs CC »).

    Args:
        request_path: chemin HTTP consulté (ex : "/cc/atoms", "/cc/health").
                      JAMAIS les query params s'ils contiennent des données.
        principal:    identifiant du consultant (ex : "admin", node_id CC).
                      JAMAIS un mot de passe, token, ou valeur sensible.
    """
    # Anti-injection de ligne de log : un principal contenant \n ou \r forgerait
    # une fausse entrée CC_ACCESS. Sanitize avant écriture (red-team V1.7B).
    principal = str(principal).replace("\n", " ").replace("\r", " ")[:128]
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    line = f"{ts} | CC_ACCESS | {principal} | {request_path}\n"

    log_path = _get_log_path()
    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        # Non-fatal : le log d'accès ne doit pas bloquer la consultation.
        # En production, surveiller les erreurs OSError via les logs systemd.
        pass
