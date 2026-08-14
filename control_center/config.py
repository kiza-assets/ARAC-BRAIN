"""ARAC — Control Center : configuration (READ-ONLY, env-driven).

Règle fondamentale : AUCUNE valeur de secret en dur ici.
Ce fichier documente les NOMS des variables d'environnement attendues ;
les valeurs sont lues depuis l'environnement au runtime.

Variables d'environnement requises au runtime :

  DATABASE_URL_READONLY   DSN psycopg3 pour le rôle arac_readonly (SELECT-only).
                          Forme : un DSN postgresql vers la base arac via le rôle
                          arac_readonly ; mot de passe fourni par l'env, JAMAIS en clair
                          ici ni dans le code. (DSN complet hors de ce dépôt.)

  CC_SESSION_SECRET       Clé HMAC-SHA256 pour signer les sessions Control Center.
                          Générer via : openssl rand -hex 32
                          Longueur recommandée : ≥ 64 chars hex (32 bytes).

  CC_ADMIN_PASSWORD_HASH  Hash pbkdf2_sha256 du mot de passe administrateur.
                          Format : pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>
                          Générer via security.hash_password("mon_mot_de_passe").
                          JAMAIS stocker le mot de passe en clair.

  CC_TOTP_SECRET          Secret TOTP base32 (RFC 6238) pour le 2FA admin.
                          Générer via : python -c "import base64, os;
                            print(base64.b32encode(os.urandom(20)).decode())"
                          À scanner dans une app TOTP (Google Authenticator, etc.).
"""

from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg

# ============================================================================
# Noms des variables d'environnement — JAMAIS les valeurs ici
# ============================================================================

READONLY_DSN_ENV: str = "DATABASE_URL_READONLY"
"""Nom de la variable d'env portant le DSN PostgreSQL read-only (rôle arac_readonly)."""

CC_SESSION_SECRET_ENV: str = "CC_SESSION_SECRET"
"""Nom de la variable d'env portant la clé HMAC de signature des sessions CC."""

CC_ADMIN_PASSWORD_HASH_ENV: str = "CC_ADMIN_PASSWORD_HASH"
"""Nom de la variable d'env portant le hash pbkdf2_sha256 du mot de passe admin CC."""

CC_TOTP_SECRET_ENV: str = "CC_TOTP_SECRET"
"""Nom de la variable d'env portant le secret TOTP base32 (RFC 6238) pour le 2FA."""

LOCAL_TRUSTED_TUNNEL_ENV: str = "LOCAL_TRUSTED_TUNNEL"
"""Nom du feature flag V1.7D : si activé, les requêtes loopback (tunnel SSH de
confiance) bypassent l'auth (login/password/TOTP). Défaut : désactivé (fail-secure)."""


def local_trusted_tunnel_enabled() -> bool:
    """True si LOCAL_TRUSTED_TUNNEL est activé.

    Valeurs vraies (casse ignorée) : true, 1, yes, on. Tout le reste (absent,
    vide, "false", "0", "no"...) => False. Lu à CHAQUE appel (jamais en cache
    module-level — cf. leçon V1.7C1 : un cache figerait l'état avant restart).
    Défaut fail-secure : en l'absence de la variable, le bypass est DÉSACTIVÉ.
    """
    raw = os.environ.get(LOCAL_TRUSTED_TUNNEL_ENV, "").strip().lower()
    return raw in {"true", "1", "yes", "on"}


# ============================================================================
# Constantes de session
# ============================================================================

SESSION_TTL_SECONDS: int = 1800
"""Durée de vie d'une session Control Center en secondes (30 minutes)."""

SESSION_COOKIE_NAME: str = "cc_session"
"""Nom du cookie de session HTTP Control Center."""


# ============================================================================
# Chemins
# ============================================================================

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
"""Racine du dépôt ARAC (deux niveaux au-dessus de control_center/)."""

DOCS_DIR: Path = REPO_ROOT / "docs"
"""Répertoire docs/ du dépôt (RUNBOOK, ARCHITECTURE, CHANGELOG, DECISIONS)."""

COUNCIL_SESSIONS_DIR: str = "/tmp/arac_council"
"""Répertoire temporaire des sessions du Council (lecture seule depuis le CC)."""


# ============================================================================
# Le fuseau du cerveau
# ============================================================================

CYCLE_TZ_ENV: str = "ARAC_CYCLE_TZ"
"""Nom de la variable d'env portant le fuseau des cycles (posée par le bootstrap)."""

CYCLE_TZ_FALLBACK: str = "UTC"
"""Le repli quand rien n'est déclaré : UTC, le seul fuseau qui n'appartient à personne."""


def cycle_tz() -> str:
    """Le fuseau dans lequel se découpe une « journée » du cerveau.

    POURQUOI CETTE FONCTION EXISTE
    ------------------------------
    Les créneaux circadiens (04:00, 13:00, 21:00…) sont des heures LOCALES du
    serveur, pas des heures UTC. Le cockpit doit donc découper ses journées et
    calculer le prochain cycle sur la même horloge que le moteur — sinon il
    affirme des créneaux faux.

    Un fuseau écrit en dur dans le code serait celui de la machine sur laquelle
    ce code a été écrit : servi tel quel, il décale les journées de tous les
    autres. La source est donc ``ARAC_CYCLE_TZ``, la variable que le bootstrap
    pose depuis le fuseau du système (``bootstrap/lib/config.sh``) et qui pilote
    déjà les minuteries systemd des cycles. Cockpit et moteur lisent la même.

    Le repli est UTC, et il est EXPLICITE : quand rien n'est déclaré, le cockpit
    préfère un fuseau neutre — visiblement neutre — à un fuseau plausible qui
    serait faux sans le dire. Une valeur illisible (fuseau inconnu de la base
    tzdata) retombe sur le même repli plutôt que de faire tomber la page.

    Returns:
        Un nom de fuseau IANA valide (ex. ``"Europe/Berlin"``, ``"UTC"``),
        toujours utilisable tel quel par ``ZoneInfo`` et par ``AT TIME ZONE``.
    """
    declared = (os.environ.get(CYCLE_TZ_ENV) or "").strip()
    if not declared:
        return CYCLE_TZ_FALLBACK
    try:
        ZoneInfo(declared)
    except Exception:  # noqa: BLE001 — un fuseau inconnu n'est pas une panne de page
        return CYCLE_TZ_FALLBACK
    return declared


# ============================================================================
# Fonctions de configuration
# ============================================================================


def get_readonly_dsn() -> str | None:
    """Retourne le DSN read-only depuis l'environnement, ou None si absent.

    La valeur est lue depuis la variable d'env DATABASE_URL_READONLY.
    Ne lève pas d'exception si la variable est absente — l'appelant décide
    quoi faire (levée d'erreur, dégradation gracieuse, etc.).

    Returns:
        str: le DSN postgresql:// si DATABASE_URL_READONLY est définie.
        None: si la variable est absente ou vide.
    """
    return os.environ.get(READONLY_DSN_ENV) or None


def db_connect_readonly() -> psycopg.Connection:
    """Ouvre et retourne une connexion psycopg3 synchrone en lecture seule.

    Garanties défensives (double couche) :
      1. Le DSN pointe sur le rôle arac_readonly (droits SELECT uniquement
         au niveau PostgreSQL).
      2. La session est forcée en read-only via l'option de connexion
         ``default_transaction_read_only=on`` — même si le rôle était
         accidentellement promu, aucun DML ne passerait.

    autocommit=True : la connexion ne démarre pas de transaction implicite,
    ce qui est cohérent avec les lectures séquentielles du dashboard.
    Pour des lectures longues consistantes, l'appelant peut ouvrir une
    transaction explicite en READ ONLY.

    Raises:
        RuntimeError: si DATABASE_URL_READONLY n'est pas définie.
        psycopg.OperationalError: si la connexion échoue (BDD down, auth…).

    Returns:
        psycopg.Connection: connexion synchrone à utiliser dans un bloc
        ``with db_connect_readonly() as conn:`` (fermeture automatique).
    """
    dsn = get_readonly_dsn()
    if not dsn:
        raise RuntimeError(
            f"Variable d'environnement {READONLY_DSN_ENV!r} non définie. "
            "Vérifier $ARAC_HOME/.env (mode 0600) et le service "
            "systemd du Control Center (EnvironmentFile=)."
        )
    return psycopg.connect(
        dsn,
        autocommit=True,
        options="-c default_transaction_read_only=on",
    )
