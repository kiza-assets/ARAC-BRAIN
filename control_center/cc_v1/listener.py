"""Control Center v1 — L'OREILLE : écoute LISTEN, repli sur le suivi de base.

╔══════════════════════════════════════════════════════════════════════════════╗
║ CE QUE CE MODULE EST — et ce qu'il n'est pas                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

``stream.py`` SUIT la base : il interroge neuf tables une fois par seconde et
pousse les nouveautés en SSE. C'est honnête, c'est borné, et c'est du sondage
côté serveur. Ce module vise l'inverse : que le moteur PARLE, et que le
cockpit se contente d'écouter.

Ce module ouvre l'oreille. Il ne fabrique pas la voix.

    Une connexion PostgreSQL en lecture seule, un ``LISTEN`` sur deux canaux,
    un fil de fond partagé, une reconnexion à backoff. Rien d'autre.

╔══════════════════════════════════════════════════════════════════════════════╗
║ AUJOURD'HUI, PERSONNE NE PARLE — et c'est le comportement CORRECT             ║
╚══════════════════════════════════════════════════════════════════════════════╝

Le moteur ARAC n'émet aucune notification. Ce n'est pas un oubli : la migration
``0016_drop_notify_triggers`` a SUPPRIMÉ les deux déclencheurs de base qui en
émettaient, au nom d'une règle que ce dépôt tient partout — **rien ne réveille
rien**. Un déclencheur qui publie fait travailler la transaction qui écrit :
l'écriture paie pour un lecteur dont elle ignore l'existence. Le silence de ce
module est donc la conséquence d'un choix, pas d'une panne.

Conséquence directe et assumée :

    Cet écouteur restera muet tant que le moteur n'aura pas été modifié.
    ``notifies_received`` restera à 0. ``mode`` restera ``db-tailing``.
    ``engine_publishes`` restera ``false``.

Ce module ne simule AUCUN événement, ne fabrique aucun battement, ne « teste »
pas le canal en s'envoyant un message à lui-même. Un écouteur qui s'auto-parle
prouve seulement qu'il sait parler — il ne prouve rien sur le moteur.

Le mode d'emploi du branchement moteur tient en trois lignes, et il est ICI
plutôt que dans un document séparé — un renvoi survit mal à un déplacement de
fichier, et un lecteur envoyé vers un document absent conclut que son
installation est incomplète :

    OÙ    : ``NOTIFY`` sur l'un des canaux déclarés dans ``CHANNELS``
            ci-dessous — ``arac_events`` pour les transitions de cycle,
            ``arac_atom`` pour la naissance d'un atome.
    QUOI  : une charge utile JSON d'au plus 8 ko (limite de ``pg_notify``),
            portant au minimum ``event`` et l'identifiant de l'objet.
    D'OÙ  : les deux endroits où ces faits naissent déjà —
            ``RunReceiptLedger.create_receipt`` / ``.mark``
            (``agents/lib/spend_guard.py``) pour les cycles, et
            ``app/routers/atoms.py`` pour les atomes.

Ce module rendra le branchement effectif sans qu'une ligne du cockpit change.

╔══════════════════════════════════════════════════════════════════════════════╗
║ LE BASCULEMENT EST OBSERVÉ, JAMAIS DÉCLARÉ                                    ║
╚══════════════════════════════════════════════════════════════════════════════╝

``mode`` n'est pas une option de configuration : c'est un CONSTAT.

    notifies_received == 0  ->  mode = "db-tailing"     (le moteur se tait)
    notifies_received  > 0  ->  mode = "listen-notify"  (le moteur a parlé)

Le basculement se produit à la PREMIÈRE notification réellement reçue, et il est
irréversible pour la durée du processus : un moteur qui a parlé une fois a
prouvé qu'il sait parler. Personne ne peut forcer ``listen-notify`` par un
réglage — il n'y a pas de réglage. La seule façon de faire basculer ce module
est de faire publier le moteur.

Et même après le basculement, **le suivi de base reste actif**. Rien ne prouve
qu'un moteur qui publie UNE transition les publie TOUTES ; retirer le suiveur
exige une preuve de couverture, pas un espoir. ``fallback.retired`` reste donc
``false`` jusqu'à cette preuve, et ``fallback.retire_condition`` dit laquelle.

╔══════════════════════════════════════════════════════════════════════════════╗
║ CE QUE J'AI REFUSÉ DE FAIRE — la retenue est préférable à la démonstration     ║
╚══════════════════════════════════════════════════════════════════════════════╝

La route ``/cc/v1/listener/selftest`` NE publie rien. Elle refuse, et elle dit
pourquoi. Trois raisons qui suffisent chacune :

  1. DOCTRINE. Publier une notification dépose une entrée dans une file
     partagée du serveur, visible par TOUTES les autres sessions abonnées.
     C'est un effet qui sort de ma session : au sens du mandat, c'est une
     écriture. Le mandat dit « si tu as le moindre doute, ne l'implémente pas ».
     Je n'ai même pas de doute.

  2. POSTGRESQL. Le serveur refuserait de toute façon : la commande est barrée
     par ``PreventCommandIfReadOnly`` dans ``standard_ProcessUtility``. Notre
     connexion porte ``default_transaction_read_only=on`` (vérifiable dans la
     preuve servie ci-dessous, champ ``read_only``). Implémenter la route
     n'aurait donc produit qu'une erreur déguisée en fonctionnalité.

  3. VÉRITÉ DU COCKPIT. Une notification émise par le cockpit lui-même ferait
     basculer ``mode`` en ``listen-notify`` et ``engine_publishes`` en ``true``
     — sur un moteur toujours muet. Le cockpit se serait menti à lui-même, puis
     l'aurait affiché. C'est exactement l'échec que ce chantier combat.

À la place, ``selftest`` sert une preuve qui, elle, est en lecture seule :
``SELECT pg_listening_channels()`` exécuté sur la connexion de l'écouteur
lui-même. Le SERVEUR répond quels canaux CETTE session a souscrits. Cela prouve
que l'abonnement existe côté PostgreSQL — pas seulement dans une variable
Python. Et cela ne prouve PAS qu'une notification serait délivrée : seule une
publication réelle du moteur le prouvera. La route dit les deux.

Pour qui veut la preuve complète, ``selftest`` fournit la commande à taper
**hors du cockpit**, avec un rôle qui a le droit d'écrire — un geste humain,
tracé, hors de ce processus.

╔══════════════════════════════════════════════════════════════════════════════╗
║ LECTURE SEULE — la liste fermée de tout ce que ce module exécute              ║
╚══════════════════════════════════════════════════════════════════════════════╝

Ce module n'exécute que ceci, et rien d'autre ne peut lui être ajouté sans que
la garde d'import ``_assert_read_only`` le refuse :

  - ``LISTEN <canal>``            commande de SESSION : n'écrit aucune ligne,
                                  ne verrouille rien, n'est pas barrée en
                                  transaction read-only ;
  - ``SELECT pg_backend_pid() … pg_listening_channels()``  la preuve d'abonnement.

Les noms de canaux sont des constantes du module, validées par ``_CHANNEL_RE``
et passées par ``psycopg.sql.Identifier`` — aucune chaîne extérieure n'atteint
jamais le moteur SQL. ``executed_sql()`` rend cette liste au vérificateur.

AUCUNE ARITHMÉTIQUE SUR LES DONNÉES DU CERVEAU. Ce module ne lit pas une seule
ligne du cerveau : il compte des notifications QU'IL VIENT DE RECEVOIR — même
exception, et même justification, que ``measures.count`` dans ``stream.py``.

╔══════════════════════════════════════════════════════════════════════════════╗
║ API INTERNE — ce que ``stream.py`` pourra utiliser sans être réécrit          ║
╚══════════════════════════════════════════════════════════════════════════════╝

Ce module ne touche pas à ``stream.py``. Il lui offre une surface, et attend.

  ``ensure_started()``      démarre le fil de fond (idempotent, ne lève jamais)
  ``consume_wake()``        nombre de notifications reçues depuis le dernier
                            appel, puis remise à zéro — LE point d'intégration
  ``drain(limit)``          les notifications reçues, dans l'ordre, puis vidage
  ``subscribe(cb)``         rappel appelé pour chaque notification reçue
  ``unsubscribe(token)``    désabonnement
  ``transport()``           l'enveloppe ``transport`` à servir, mode réel inclus
  ``listener_state()``      l'état complet servi par la route

Le branchement de ``stream.Tailer`` tient en quatre lignes, à insérer dans
``Tailer._run`` juste avant ``await asyncio.sleep(self._interval_s())`` :

    from control_center.cc_v1 import listener
    listener.ensure_started()
    if listener.consume_wake():
        continue          # le moteur a parlé : passage immédiat, pas d'attente

Effet : tant que le moteur se tait, le suiveur garde sa cadence d'une seconde ;
dès qu'il parle, la latence tombe au temps d'un passage. Le suiveur reste la
SOURCE (il relit les lignes, donc la preuve reste une ligne de la base) ;
la notification n'est qu'une SONNETTE. C'est délibéré : si la charge utile
devenait la source, un événement du cockpit aurait pour preuve un message au
lieu d'une ligne, et la chaîne de preuve serait rompue.

Le câblage effectif de ces quatre lignes vous appartient : ce module ne
modifie pas ``stream.py``.

Routes exposées :

  GET /cc/v1/listener/state     mode réel, canaux, compteurs, repli, pourquoi
  GET /cc/v1/listener/selftest  le refus motivé + la preuve d'abonnement lisible
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import Depends, FastAPI, Query

from app.journal import raison
from fastapi.responses import JSONResponse

__all__ = [
    "register",
    "CHANNELS",
    "Listener",
    "get_listener",
    "ensure_started",
    "stop",
    "consume_wake",
    "drain",
    "subscribe",
    "unsubscribe",
    "request_reconnect",
    "transport",
    "listener_state",
    "selftest",
    "executed_sql",
]

#: LE MESSAGE EST AUTOPORTEUR, ``extra=`` NE L'EST PAS (corrigé 2026-08-05).
#:
#: Aucun formateur n'est configuré pour ce service — ni ``basicConfig``, ni
#: ``dictConfig``, ni ``log_config`` : uvicorn applique son format par défaut,
#: ``%(message)s``. Tout ce qui était rangé dans ``extra=`` n'était donc JAMAIS
#: rendu. Une panne de l'oreille se lisait « cc_v1.listener.unavailable » et rien
#: d'autre : sans phase, sans type d'exception, sans compteur d'échecs, sans
#: trace — indiagnosticable, précisément là où l'oreille est le seul organe qui
#: dit au cockpit que la base parle encore.
#:
#: Le contexte passe désormais par les ARGUMENTS du message ; ``extra=`` reste
#: rempli pour le jour où un formateur structuré sera posé, mais il n'est plus la
#: seule copie de l'information. ``exc_info=True`` sur toute branche qui capture
#: une exception : sans trace, « OperationalError » ne dit pas OÙ.
#:
#: GARDE-FOU : on journalise des canaux, des phases, des jetons d'abonnement et
#: des types d'exception — JAMAIS la charge utile d'une notification, jamais la
#: valeur d'un atome, jamais un titre de conversation.
logger = logging.getLogger("arac.cc.v1.listener")

_PREFIX = "/cc/v1"


# ============================================================================
# Les canaux — documentés, fermés, validés
# ============================================================================

CHANNELS: tuple[str, ...] = ("arac_events", "arac_atom")
"""Les deux canaux que le cockpit écoute.

``arac_events`` — LES TRANSITIONS DU CYCLE. Un message par transition d'état
d'un passage de curation (démarré, vide, engendré, échoué, en quarantaine,
terminé), plus les faits de pipeline (capture, import, curation d'une
conversation, rappel servi, refus d'ingestion). Volume attendu : quelques
dizaines de messages par jour, concentrés sur trois créneaux.

``arac_atom`` — LA MÉMOIRE QUI BOUGE. Un message par atome créé, remplacé ou
écarté. Volume attendu : des rafales de quelques dizaines de messages en
quelques secondes, trois fois par jour.

DEUX canaux et non un seul, pour une raison de fond : une rafale d'atomes ne
doit jamais retarder l'annonce d'une transition de cycle, et un consommateur
qui ne s'intéresse qu'aux cycles ne doit pas avoir à filtrer des milliers de
messages. Un abonné choisit son canal ; c'est le seul filtre gratuit que
PostgreSQL offre.

Ces noms sont un CONTRAT proposé au moteur, pas un fait observé : rien ne
publie dessus aujourd'hui. Le mode d'emploi du branchement est en tête de ce
module ; il n'y en a pas d'autre ailleurs.
"""

_CHANNEL_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
"""Un nom de canal est un identifiant SQL minuscule. Validé à l'import : aucun
nom ne peut atteindre le moteur SQL sans avoir passé ce filtre, en plus du
passage obligatoire par ``psycopg.sql.Identifier``."""

for _ch in CHANNELS:
    if not _CHANNEL_RE.match(_ch):
        raise ValueError(f"nom de canal invalide : {_ch!r}")


# ============================================================================
# Réglages — bornes dures, jamais dépassées
# ============================================================================

WINDOW_S = 1.0
"""Durée d'une fenêtre d'écoute bloquante. Ce n'est PAS un intervalle de
sondage : le fil dort dans ``libpq`` et se réveille sur le paquet réseau. La
fenêtre n'existe que pour rendre l'arrêt du fil et le rafraîchissement de la
preuve possibles sans tuer la connexion."""

RING_CAPACITY = 200
"""Anneau des notifications reçues. Borné : un cockpit ne grossit pas sans fin."""

PAYLOAD_MAX_CHARS = 8000
"""Plafond de charge utile conservée. PostgreSQL borne déjà à 8000 octets ; on
tronque à la même hauteur pour ne jamais dépendre de cette borne serveur."""

BACKOFF_STEPS_S: tuple[float, ...] = (1.0, 2.0, 5.0, 15.0, 30.0)
"""Attente croissante quand la base est injoignable. L'écouteur ne meurt jamais."""

PROOF_EVERY_WINDOWS = 30
"""Rafraîchissement de la preuve d'abonnement, en fenêtres. Une reconnexion
silencieuse ne doit pas laisser une preuve périmée passer pour fraîche."""

JOIN_TIMEOUT_S = 5.0
"""Délai d'attente à l'arrêt du fil, avant de le laisser mourir seul."""

AUTOSTART_ENV = "ARAC_CC_LISTENER_AUTOSTART"
"""Mettre à ``0`` pour empêcher le démarrage automatique au boot du cockpit
(utile pour un diagnostic à froid). Par défaut : l'oreille s'ouvre avec l'app.
Ce réglage ne pilote QUE le démarrage du fil — il ne peut pas influencer
``mode``, qui reste un constat."""


# ============================================================================
# Garde lecture seule — la liste fermée de ce que ce module exécute
# ============================================================================

FORBIDDEN_SQL: tuple[str, ...] = (
    "insert", "update", "delete", "truncate", "drop", "alter", "create",
    "grant", "revoke", "copy", "vacuum", "refresh", "call", "do",
    # Spécifique à ce module : la commande de publication est barrée AU MÊME
    # TITRE qu'un DELETE. C'est la traduction en code du refus documenté plus
    # haut — pour que le refus survive à un contributeur pressé.
    "notify", "unlisten", "pg_notify",
)

_WORD = re.compile(r"[a-z_]+")


def _assert_read_only(sql: str, where: str) -> None:
    """Refuse toute instruction mutante. Appliquée à l'import sur TOUT le SQL.

    Raises:
        ValueError: si un mot-clé interdit apparaît dans la requête.
    """
    words = set(_WORD.findall(sql.lower()))
    bad = sorted(words & set(FORBIDDEN_SQL))
    if bad:
        raise ValueError(f"{where} : instruction mutante {bad}")


_SQL_LISTEN_TEMPLATE = "LISTEN {channel}"
"""Le seul gabarit de commande de session. ``{channel}`` est substitué par
``psycopg.sql.Identifier``, jamais par formatage de chaîne."""

_SQL_PROOF = """
SELECT pg_backend_pid()                                   AS backend_pid,
       current_user                                       AS role,
       current_setting('default_transaction_read_only')   AS read_only,
       coalesce(array_agg(c ORDER BY c), ARRAY[]::text[]) AS channels
FROM pg_listening_channels() AS c
"""
"""LA PREUVE, en lecture seule : le SERVEUR dit quels canaux cette session a
souscrits, sous quel rôle, et si la session est bien en lecture seule."""

_EXECUTED_SQL: dict[str, str] = {
    "listen": _SQL_LISTEN_TEMPLATE.replace("{channel}", "<identifiant validé>"),
    "proof": _SQL_PROOF,
}
"""Tout ce que ce module peut exécuter. Deux entrées. Le vérificateur les relit."""

for _name, _sql in _EXECUTED_SQL.items():
    _assert_read_only(_sql, f"listener._EXECUTED_SQL[{_name}]")


def executed_sql() -> dict[str, str]:
    """La liste fermée du SQL exécutable par ce module — pour le vérificateur."""
    return dict(_EXECUTED_SQL)


# ============================================================================
# Petits outils
# ============================================================================


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt is not None else None


def _autostart_wanted() -> bool:
    return (os.environ.get(AUTOSTART_ENV, "1").strip().lower()
            not in ("0", "false", "no", "off"))


# ============================================================================
# L'écouteur
# ============================================================================


class Listener:
    """L'oreille du cockpit : une connexion, deux ``LISTEN``, un fil de fond.

    UN SEUL écouteur pour tout le processus. Un FIL, pas une tâche asyncio :
    ``stream.Tailer`` a déjà payé le prix d'une tâche liée à une boucle
    d'événements (une boucle qui meurt pendant un passage laisse un thread
    survivant sur la même connexion — mort en segmentation fault, pas en
    exception). Un fil démon, propriétaire exclusif de sa connexion, n'a pas ce
    problème : il survit au montage et démontage de l'application, ne bloque
    aucune boucle, et s'arrête sur un drapeau.

    L'écouteur ne partage JAMAIS sa connexion avec le suiveur : ``psycopg``
    interdit d'exécuter une requête pendant la consommation des notifications.
    Deux organes, deux connexions.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._reconnect_flag = threading.Event()

        # -- ce qui est REÇU (jamais inventé) ---------------------------------
        self._ring: deque[dict[str, Any]] = deque(maxlen=RING_CAPACITY)
        self._notifies = 0
        self._by_channel: dict[str, int] = {c: 0 for c in CHANNELS}
        self._first_notify_at: datetime | None = None
        self._last_notify_at: datetime | None = None
        self._wake_pending = 0

        # -- ce qui est OBSERVÉ de la connexion -------------------------------
        self._connected = False
        self._since: datetime | None = None
        self._connected_at: datetime | None = None
        self._connect_attempts = 0
        self._reconnects = 0
        self._failures = 0
        self._last_error: str | None = None
        self._windows = 0
        self._proof: dict[str, Any] = {
            "state": "unavailable",
            "reason": "l'écouteur n'a pas encore ouvert de connexion",
        }

        # -- abonnés internes (stream.py, un jour) ----------------------------
        self._subs: dict[int, Callable[[dict[str, Any]], None]] = {}
        self._sub_seq = 0

    # -- état ---------------------------------------------------------------

    @property
    def running(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    @property
    def mode(self) -> str:
        """Le transport RÉEL. Un constat, pas un réglage.

        Tant qu'aucune notification n'a été reçue, le cockpit est servi par le
        suivi de base et le dit. La première notification reçue fait basculer,
        définitivement pour ce processus.
        """
        return "listen-notify" if self._notifies > 0 else "db-tailing"

    @property
    def engine_publishes(self) -> bool:
        """``True`` seulement si le moteur a RÉELLEMENT parlé au moins une fois."""
        return self._notifies > 0

    def _why(self) -> str:
        if self._notifies > 0:
            return (
                f"le moteur a publié {self._notifies} notification(s) sur "
                f"{', '.join(CHANNELS)} ; le cockpit est réveillé par le moteur, "
                "et non plus seulement par son propre suivi de base"
            )
        if not self.running:
            return (
                "l'écouteur n'est pas démarré : aucune notification ne peut être "
                "reçue. Le cockpit reste servi par le suivi de base."
            )
        if not self._connected:
            return (
                "l'écouteur est démarré mais n'a pas de connexion à la base "
                f"({self._last_error or 'cause inconnue'}) ; il retente avec un "
                "délai croissant. Le cockpit reste servi par le suivi de base."
            )
        return (
            "l'écouteur est abonné et n'a reçu aucune notification : le moteur "
            "ne publie pas. La migration 0016_drop_notify_triggers a supprimé "
            "les deux déclencheurs de base qui publiaient, parce qu'un "
            "déclencheur fait payer l'écriture pour un lecteur dont elle ignore "
            "l'existence. Le silence est donc un choix, pas une panne — et "
            "c'est le comportement correct."
        )

    # -- cycle de vie -------------------------------------------------------

    def start(self) -> None:
        """Démarre le fil de fond si besoin. Idempotent. Ne lève jamais."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_flag.clear()
            self._since = self._since or _now_dt()
            t = threading.Thread(target=self._run, name="cc_v1_listener",
                                 daemon=True)
            self._thread = t
        try:
            t.start()
            logger.info("cc_v1.listener.started channels=%s",
                        ",".join(CHANNELS),
                        extra={"channels": ",".join(CHANNELS)})
        except Exception as exc:  # noqa: BLE001 — un cockpit ne meurt pas d'une oreille
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("cc_v1.listener.start_failed raison=%s",
                           raison(exc),
                           extra={"error": type(exc).__name__}, exc_info=True)

    def stop(self, timeout: float = JOIN_TIMEOUT_S) -> None:
        """Demande l'arrêt du fil et attend, sans jamais lever."""
        self._stop_flag.set()
        t = self._thread
        if t is not None and t.is_alive():
            try:
                t.join(timeout=timeout)
            except Exception:  # noqa: BLE001
                pass
        self._thread = None
        self._connected = False

    def request_reconnect(self) -> bool:
        """Demande au fil de rompre sa connexion et de la rouvrir.

        La rupture est RÉELLE : le fil ferme sa connexion, la déclare perdue,
        attend son backoff et rouvre — exactement le chemin d'une panne de base.
        Seule la CAUSE est provoquée ; ni l'état, ni le compteur, ni la preuve ne
        sont truqués. C'est ce qui permet au contrôle de recette d'affirmer que
        la reprise fonctionne, au lieu de l'espérer.

        Retourne ``False`` si le fil ne tourne pas : il n'y a alors rien à rompre.
        """
        if not self.running:
            return False
        self._reconnect_flag.set()
        return True

    # -- la boucle d'écoute -------------------------------------------------

    def _run(self) -> None:
        """Écoute, encaisse les pannes, se reconnecte. Ne meurt que sur demande."""
        while not self._stop_flag.is_set():
            conn = None
            try:
                conn = self._open()
            except Exception as exc:  # noqa: BLE001 — résilience volontaire
                self._on_failure(exc, phase="connect")
                self._sleep_backoff()
                continue

            try:
                self._consume(conn)
            except Exception as exc:  # noqa: BLE001
                self._on_failure(exc, phase="listen")
                self._sleep_backoff()
            finally:
                self._connected = False
                self._close(conn)

        logger.info("cc_v1.listener.stopped notifies=%s",
                    self._notifies,
                    extra={"notifies": self._notifies})

    def _open(self) -> Any:
        """Ouvre la connexion en lecture seule et souscrit aux canaux.

        ``LISTEN`` est une commande de SESSION : elle inscrit cette connexion
        dans la table des abonnés du serveur. Elle n'insère aucune ligne, ne
        prend aucun verrou, et n'est pas barrée en transaction read-only — la
        preuve servie par ``selftest`` le montre, champ ``read_only = on``.
        """
        from psycopg import sql as _sql

        from control_center.cc_v1 import service

        self._connect_attempts += 1
        if self._connected_at is not None:
            self._reconnects += 1

        conn = service._connect_readonly()
        with conn.cursor() as cur:
            for ch in CHANNELS:
                cur.execute(_sql.SQL(_SQL_LISTEN_TEMPLATE).format(
                    channel=_sql.Identifier(ch)))
        # La preuve est rafraîchie AVANT d'annoncer la connexion : sans cet
        # ordre, il existe une fenêtre où l'état dit « abonné » en servant
        # encore la preuve de la panne précédente. Un cockpit ne se déclare pas
        # prêt avant d'avoir de quoi le prouver.
        self._refresh_proof(conn)
        self._connected_at = _now_dt()
        self._failures = 0
        self._last_error = None
        self._connected = True
        logger.info("cc_v1.listener.subscribed channels=%s backend_pid=%s",
                    ",".join(CHANNELS), self._proof.get("backend_pid"),
                    extra={"channels": ",".join(CHANNELS),
                           "backend_pid": self._proof.get("backend_pid")})
        return conn

    def _consume(self, conn: Any) -> None:
        """Consomme les notifications par fenêtres, jusqu'à l'arrêt demandé.

        Le fil dort dans ``libpq`` pendant la fenêtre : il ne sonde rien, il
        attend un paquet. La fenêtre borne seulement le temps de réaction à une
        demande d'arrêt et cadence le rafraîchissement de la preuve.
        """
        while not self._stop_flag.is_set():
            gen = conn.notifies(timeout=WINDOW_S)
            try:
                for n in gen:
                    self._record(n)
                    if self._stop_flag.is_set():
                        break
            finally:
                gen.close()

            self._windows += 1
            if self._windows % PROOF_EVERY_WINDOWS == 0:
                self._refresh_proof(conn)

            # Rupture demandée : on sort par le MÊME chemin qu'une panne réelle
            # (déclaration, backoff, réouverture). Le drapeau est lu ENTRE deux
            # fenêtres, jamais pendant : fermer une connexion ``libpq`` depuis un
            # autre fil pendant une lecture bloquante tue le processus en
            # segmentation fault — c'est la leçon déjà payée par ``stream.Tailer``.
            if self._reconnect_flag.is_set():
                self._reconnect_flag.clear()
                raise ConnectionResetError("rupture demandée : vérification de la reprise")

    def _record(self, n: Any) -> None:
        """Enregistre une notification REÇUE. Ne l'interprète pas, ne la calcule pas.

        La charge utile est conservée telle quelle (tronquée) ET, si elle est un
        objet JSON, décodée pour l'inspection. Aucune décision du cockpit ne
        repose sur ce contenu : la notification est une SONNETTE, la preuve
        reste la ligne de la base que le suiveur relira.
        """
        import json as _json

        received = _now_dt()
        channel = getattr(n, "channel", "?")
        raw = getattr(n, "payload", "") or ""
        truncated = len(raw) > PAYLOAD_MAX_CHARS
        kept = raw[:PAYLOAD_MAX_CHARS]

        decoded: Any = None
        parse_error: str | None = None
        if kept.strip():
            try:
                decoded = _json.loads(kept)
            except Exception as exc:  # noqa: BLE001 — une charge libre reste lisible
                parse_error = f"{type(exc).__name__}: {exc}"

        rec = {
            "channel": channel,
            "sender_pid": getattr(n, "pid", None),
            "received_at": _iso(received),
            "payload_raw": kept,
            "payload_truncated": truncated,
            "payload_json": decoded,
            "payload_parse_error": parse_error,
        }

        self._ring.append(rec)
        self._notifies += 1
        self._wake_pending += 1
        self._by_channel[channel] = self._by_channel.get(channel, 0) + 1
        if self._first_notify_at is None:
            self._first_notify_at = received
            logger.info("cc_v1.listener.transport_switched mode=%s channel=%s",
                        "listen-notify", channel,
                        extra={"mode": "listen-notify", "channel": channel})
        self._last_notify_at = received

        for token, cb in list(self._subs.items()):
            try:
                cb(dict(rec))
            except Exception as exc:  # noqa: BLE001 — un abonné fautif ne coupe pas l'oreille
                logger.warning("cc_v1.listener.subscriber_failed token=%s raison=%s",
                               token, raison(exc),
                               extra={"token": token, "error": type(exc).__name__},
                               exc_info=True)

    def _refresh_proof(self, conn: Any) -> None:
        """Demande au SERVEUR quels canaux cette session écoute réellement."""
        try:
            with conn.cursor() as cur:
                cur.execute(_SQL_PROOF)
                cols = [d.name for d in (cur.description or [])]
                row = cur.fetchone()
        except Exception as exc:  # noqa: BLE001
            self._proof = {"state": "unavailable",
                           "reason": f"preuve illisible ({type(exc).__name__})",
                           "checked_at": _iso(_now_dt())}
            return

        data = dict(zip(cols, row)) if row else {}
        self._proof = {
            "state": "ok",
            "backend_pid": data.get("backend_pid"),
            "role": data.get("role"),
            "read_only": data.get("read_only"),
            "channels_registered_by_server": list(data.get("channels") or []),
            "checked_at": _iso(_now_dt()),
        }

    def _on_failure(self, exc: Exception, phase: str) -> None:
        self._connected = False
        self._failures += 1
        self._last_error = f"{type(exc).__name__}: {exc}"
        self._proof = {
            "state": "unavailable",
            "reason": f"connexion perdue ({type(exc).__name__})",
            "checked_at": _iso(_now_dt()),
        }
        logger.warning("cc_v1.listener.unavailable phase=%s failures=%s raison=%s",
                       phase, self._failures, raison(exc),
                       extra={"phase": phase, "error": type(exc).__name__,
                              "failures": self._failures}, exc_info=True)

    def _backoff_s(self) -> float:
        if not self._failures:
            return BACKOFF_STEPS_S[0]
        return BACKOFF_STEPS_S[min(self._failures - 1, len(BACKOFF_STEPS_S) - 1)]

    def _sleep_backoff(self) -> None:
        # ``Event.wait`` plutôt qu'un sommeil : une demande d'arrêt pendant un
        # backoff de 30 s ne doit pas se faire attendre 30 s.
        self._stop_flag.wait(self._backoff_s())

    @staticmethod
    def _close(conn: Any) -> None:
        if conn is None:
            return
        try:
            conn.close()
        except Exception:  # noqa: BLE001 — fermer ne masque jamais l'erreur utile
            pass

    # -- API interne pour stream.py -----------------------------------------

    def consume_wake(self) -> int:
        """Notifications reçues depuis le dernier appel, puis remise à zéro.

        LE point d'intégration : un suiveur qui obtient un nombre non nul sait
        que quelque chose a bougé et peut faire un passage immédiat au lieu
        d'attendre sa cadence. Zéro veut dire « rien n'a bougé », jamais
        « je ne sais pas » — l'écouteur non démarré rend zéro ET ``state()``
        dit qu'il n'écoute pas.
        """
        n, self._wake_pending = self._wake_pending, 0
        return n

    def drain(self, limit: int = RING_CAPACITY) -> list[dict[str, Any]]:
        """Les notifications reçues, dans l'ordre d'arrivée, puis retirées."""
        out: list[dict[str, Any]] = []
        limit = max(1, min(int(limit), RING_CAPACITY))
        while self._ring and len(out) < limit:
            out.append(self._ring.popleft())
        return out

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Les dernières notifications reçues, SANS les retirer (pour l'affichage)."""
        limit = max(1, min(int(limit), RING_CAPACITY))
        return list(self._ring)[-limit:]

    def subscribe(self, cb: Callable[[dict[str, Any]], None]) -> int:
        """Branche un rappel sur chaque notification reçue. Rend un jeton."""
        self._sub_seq += 1
        self._subs[self._sub_seq] = cb
        return self._sub_seq

    def unsubscribe(self, token: int) -> bool:
        return self._subs.pop(token, None) is not None

    # -- l'état servi -------------------------------------------------------

    def fallback(self) -> dict[str, Any]:
        """Le repli : ce qui sert le cockpit tant que le moteur ne parle pas.

        ``active`` reste ``true`` même après le basculement. Un moteur qui a
        publié UNE transition n'a pas prouvé qu'il les publie TOUTES ; débrancher
        le suiveur sur cette foi ferait disparaître des faits sans que personne
        ne le voie. La condition de retrait est écrite, elle n'est pas remplie.
        """
        try:
            from control_center.cc_v1 import stream
            interval_ms: int | None = stream.TAIL_INTERVAL_MS
            sources = list(stream._SOURCE_TABLES)
            tailer_running: bool | None = stream.get_tailer().running
        except Exception as exc:  # noqa: BLE001 — l'absence se dit
            interval_ms, sources, tailer_running = None, [], None
            logger.warning("cc_v1.listener.stream_unreadable raison=%s",
                           raison(exc),
                           extra={"error": type(exc).__name__}, exc_info=True)

        return {
            "mode": "db-tailing",
            "active": True,
            "retired": False,
            "module": "control_center.cc_v1.stream",
            "interval_ms": interval_ms,
            "tailer_running": tailer_running,
            "sources": sources,
            "why_active": (
                "le suivi par filigranes est la SOURCE des événements : il relit "
                "les lignes, donc chaque événement du cockpit garde une ligne de "
                "la base pour preuve. Une notification n'est qu'une sonnette."
            ),
            "retire_condition": (
                "retirer le suiveur exigerait la preuve que le moteur publie "
                "TOUTES les transitions des 9 tables suivies — une preuve de "
                "couverture, pas une intention. Tant qu'elle n'existe pas, "
                "débrancher le suiveur ferait disparaître des faits en silence."
            ),
            "gesture_when_engine_publishes": (
                "brancher listener.consume_wake() dans Tailer._run (4 lignes, "
                "décrites dans le docstring de ce module) : la latence tombe au "
                "temps d'un passage, la chaîne de preuve reste intacte."
            ),
        }

    def state(self) -> dict[str, Any]:
        """L'état RÉEL de l'oreille. Ne lève jamais."""
        return {
            # -- le contrat demandé -----------------------------------------
            "mode": self.mode,
            "channels": list(CHANNELS),
            "notifies_received": self._notifies,
            "last_notify_at": _iso(self._last_notify_at),
            "since": _iso(self._since),
            "fallback": self.fallback(),
            "engine_publishes": self.engine_publishes,
            "why": self._why(),
            # -- ce qui rend l'état vérifiable ------------------------------
            "state": "ok" if self._connected else "unavailable",
            "reason": None if self._connected else (
                self._last_error or (
                    "l'écouteur n'est pas démarré" if not self.running
                    else "connexion en cours d'établissement")),
            "gesture": None if self._connected else (
                "vérifier DATABASE_URL_READONLY et que PostgreSQL répond : "
                "psql \"$DATABASE_URL_READONLY\" -At -c 'SELECT 1'"),
            "substitute": None if self._connected else (
                "le suivi de base (db-tailing) sert le cockpit sans interruption"),
            "listening": self._connected,
            "running": self.running,
            "thread": (self._thread.name if self._thread is not None else None),
            "first_notify_at": _iso(self._first_notify_at),
            "notifies_by_channel": dict(self._by_channel),
            "wake_pending": self._wake_pending,
            "connection": {
                "connected": self._connected,
                "connected_at": _iso(self._connected_at),
                "attempts": self._connect_attempts,
                "reconnects": self._reconnects,
                "consecutive_failures": self._failures,
                "last_error": self._last_error,
                "backoff_next_s": self._backoff_s(),
                "backoff_steps_s": list(BACKOFF_STEPS_S),
                "window_s": WINDOW_S,
                "windows_elapsed": self._windows,
                "note": ("le fil dort dans libpq pendant la fenêtre ; il n'y a "
                         "aucun sondage. La fenêtre borne le temps de réaction "
                         "à une demande d'arrêt."),
            },
            "subscription_proof": dict(self._proof),
            "subscribers_internal": len(self._subs),
            "recent": self.recent(),
            "recent_note": (
                "vide aujourd'hui, et c'est CORRECT : rien ne publie. Ce module "
                "ne fabrique aucun événement pour paraître vivant."
            ),
            "switch_rule": {
                "db-tailing": "notifies_received == 0 — le moteur se tait",
                "listen-notify": "notifies_received > 0 — le moteur a parlé",
                "irreversible": True,
                "configurable": False,
                "note": ("mode est un CONSTAT, pas un réglage : il n'existe aucune "
                         "variable qui puisse le forcer. La seule façon de faire "
                         "basculer ce module est de faire publier le moteur."),
            },
            "engine_wiring": {
                "state": "unavailable",
                "reason": ("le moteur ne publie sur aucun canal : la migration "
                           "0016_drop_notify_triggers a supprimé les deux "
                           "déclencheurs de base qui le faisaient"),
                "gesture": ("émettre NOTIFY sur l'un des canaux ci-dessus, avec "
                            "une charge utile JSON d'au plus 8 ko, depuis les "
                            "deux endroits où ces faits naissent déjà : "
                            "RunReceiptLedger.create_receipt/mark "
                            "(agents/lib/spend_guard.py) pour les cycles, et "
                            "app/routers/atoms.py pour les atomes"),
                "substitute": "db-tailing, actif et déclaré",
            },
            "computed_at": _iso(_now_dt()),
        }

    def transport(self) -> dict[str, Any]:
        """L'enveloppe ``transport`` que ``stream.py`` pourra servir telle quelle.

        Même forme que ``stream.TRANSPORT``, mais avec le mode RÉEL observé par
        l'oreille au lieu du mode écrit en dur. ``stream.py`` n'est pas modifié :
        cette fonction existe pour le jour où il le sera.
        """
        try:
            from control_center.cc_v1 import stream
            base: dict[str, Any] = dict(stream.TRANSPORT)
        except Exception:  # noqa: BLE001
            base = {}
        live = self.mode
        base |= {
            "mode": live,
            "interval_ms": 0 if live == "listen-notify" else base.get("interval_ms"),
            "engine_publishes": self.engine_publishes,
            "why": self._why(),
            "channels": list(CHANNELS),
            "notifies_received": self._notifies,
            "listener": {"running": self.running, "listening": self._connected,
                         "since": _iso(self._since)},
            "fallback": self.fallback(),
        }
        return base


# ============================================================================
# L'écouteur partagé
# ============================================================================

_LISTENER: Listener | None = None
_LISTENER_LOCK = threading.Lock()


def get_listener() -> Listener:
    """L'oreille unique du processus : un fil, une connexion, tous les abonnés."""
    global _LISTENER
    with _LISTENER_LOCK:
        if _LISTENER is None:
            _LISTENER = Listener()
        return _LISTENER


def ensure_started() -> Listener:
    """Démarre l'écouteur si besoin. Idempotent, ne lève jamais."""
    lis = get_listener()
    if not lis.running:
        lis.start()
    return lis


def stop(timeout: float = JOIN_TIMEOUT_S) -> None:
    """Arrête l'écouteur partagé."""
    get_listener().stop(timeout=timeout)


def consume_wake() -> int:
    """Raccourci : notifications reçues depuis le dernier appel (puis remise à zéro)."""
    return get_listener().consume_wake()


def drain(limit: int = RING_CAPACITY) -> list[dict[str, Any]]:
    """Raccourci : les notifications reçues, puis retirées de l'anneau."""
    return get_listener().drain(limit)


def subscribe(cb: Callable[[dict[str, Any]], None]) -> int:
    """Raccourci : branche un rappel sur chaque notification reçue."""
    return get_listener().subscribe(cb)


def unsubscribe(token: int) -> bool:
    """Raccourci : débranche un rappel."""
    return get_listener().unsubscribe(token)


def request_reconnect() -> bool:
    """Raccourci : rompt la connexion et fait rouvrir le fil (chemin de panne réel)."""
    return get_listener().request_reconnect()


def transport() -> dict[str, Any]:
    """Raccourci : l'enveloppe ``transport`` avec le mode réel."""
    return get_listener().transport()


def listener_state() -> dict[str, Any]:
    """La charge utile de ``GET /cc/v1/listener/state``."""
    return get_listener().state()


# ============================================================================
# Le refus — documenté, motivé, servi
# ============================================================================

REFUSAL: dict[str, Any] = {
    "state": "unavailable",
    "reason": "NOTIFY est une écriture ; hors périmètre lecture seule",
    "what_was_asked": (
        "exécuter une publication sur la connexion de l'écouteur pour prouver "
        "que le canal fonctionne"
    ),
    "what_was_done": "rien — la commande n'existe nulle part dans ce module",
    "grounds": [
        {
            "kind": "doctrine",
            "statement": (
                "publier dépose une entrée dans une file partagée du serveur, "
                "visible par toutes les autres sessions abonnées. C'est un effet "
                "qui sort de ma session : au sens du mandat, une écriture."
            ),
        },
        {
            "kind": "postgresql",
            "statement": (
                "la commande est barrée par PreventCommandIfReadOnly dans "
                "standard_ProcessUtility. La connexion de l'écouteur porte "
                "default_transaction_read_only=on — voir subscription_proof."
                "read_only. L'implémenter n'aurait produit qu'une erreur "
                "déguisée en fonctionnalité."
            ),
        },
        {
            "kind": "verite_du_cockpit",
            "statement": (
                "une notification émise par le cockpit ferait basculer mode en "
                "listen-notify et engine_publishes en true sur un moteur muet. "
                "Le cockpit se serait menti, puis l'aurait affiché."
            ),
        },
    ],
    "enforcement": (
        "le mot-clé de publication figure dans listener.FORBIDDEN_SQL, au même "
        "titre que DELETE : la garde d'import refuserait tout ajout ultérieur"
    ),
    "principle": "la retenue est préférable à la démonstration",
}


def selftest() -> dict[str, Any]:
    """La charge utile de ``GET /cc/v1/listener/selftest`` : un refus + une preuve.

    Le refus est complet et motivé. La preuve qui l'accompagne est en lecture
    seule : c'est le SERVEUR qui déclare les canaux souscrits par la session de
    l'écouteur. Elle prouve que l'abonnement existe côté PostgreSQL. Elle ne
    prouve pas qu'une notification serait délivrée — et la réponse le dit.
    """
    lis = get_listener()
    proof = dict(lis._proof)
    expected = set(CHANNELS)
    got = set(proof.get("channels_registered_by_server") or [])

    payload: dict[str, Any] = dict(REFUSAL)
    payload["read_only_proof"] = {
        "state": proof.get("state", "unavailable"),
        "reason": proof.get("reason"),
        "sql": " ".join(_SQL_PROOF.split()),
        "backend_pid": proof.get("backend_pid"),
        "role": proof.get("role"),
        "read_only": proof.get("read_only"),
        "channels_expected": sorted(expected),
        "channels_registered_by_server": sorted(got),
        "channels_missing": sorted(expected - got),
        "subscription_confirmed": bool(got) and expected <= got,
        "checked_at": proof.get("checked_at"),
        "what_it_proves": (
            "PostgreSQL confirme que la session de l'écouteur est inscrite sur "
            "ces canaux, sous ce rôle, en transaction read-only. L'abonnement "
            "existe côté serveur, pas seulement dans une variable Python."
        ),
        "what_it_does_not_prove": (
            "qu'une notification serait effectivement délivrée. Seule une "
            "publication réelle du moteur le prouvera — et c'est exactement ce "
            "que notifies_received comptera."
        ),
    }
    payload["how_to_prove_it_for_real"] = {
        "who": "un humain, avec un rôle qui a le droit d'écrire — pas le cockpit",
        "where": "un terminal, hors de ce processus",
        "command": (
            "psql \"$DATABASE_URL_APP\" -c \"NOTIFY arac_events, "
            "'{\\\"v\\\":1,\\\"type\\\":\\\"cycle.started\\\",\\\"ts\\\":\\\"…\\\","
            "\\\"ref\\\":{\\\"table\\\":\\\"arac.run_receipts\\\",\\\"id\\\":0}}'\""
        ),
        "then": (
            "GET /cc/v1/listener/state doit montrer notifies_received=1, "
            "mode=listen-notify, engine_publishes=true, et la charge utile "
            "décodée dans recent[0].payload_json"
        ),
        "caution": (
            "ce geste prouve le CANAL, pas le moteur. engine_publishes deviendra "
            "true alors que le moteur n'a rien publié : la valeur dit « quelque "
            "chose a parlé sur ce canal », et c'est tout ce qu'elle peut dire. "
            "Redémarrer le cockpit remet le constat à zéro."
        ),
    }
    payload["state_href"] = f"{_PREFIX}/listener/state"
    payload["channels"] = list(CHANNELS)
    payload["computed_at"] = _iso(_now_dt())
    return payload


# ============================================================================
# Enregistrement des routes
# ============================================================================


def register(
    a: FastAPI,
    session_api: Callable[..., Any],
    audit_read_log: Callable[[str, str], Any],
) -> None:
    """Enregistre les routes de l'écouteur et ouvre l'oreille avec l'application.

    Doctrine identique au socle : ``@a.get`` uniquement, garde de session sur
    chaque route, journal de lecture sur chaque accès.

    L'écouteur démarre au démarrage de l'application (et non à la première
    connexion d'un client) : une oreille qui ne s'ouvre qu'au moment où l'on
    regarde n'entend pas ce qui s'est dit avant. Si l'application est déjà
    démarrée quand ce module est enregistré, le crochet ne se déclenchera pas —
    les routes démarrent alors l'écouteur paresseusement, ce qui reste correct.

    Args:
        a: l'instance FastAPI du Control Center.
        session_api: la dépendance de session en mode API (401 JSON si absente).
        audit_read_log: le journal de lecture du socle (chemin, principal).
    """

    @a.get(f"{_PREFIX}/listener/state")
    def cc_v1_listener_state(principal: dict = Depends(session_api)) -> JSONResponse:
        """L'ÉTAT RÉEL de l'oreille : mode observé, canaux, compteurs, repli.

        ``mode`` n'est pas un réglage : ``db-tailing`` tant qu'aucune
        notification n'a été reçue, ``listen-notify`` dès la première. Un
        compteur à zéro devant un moteur qui ne publie pas est le comportement
        CORRECT — ce module ne fabrique rien pour paraître vivant.
        """
        audit_read_log(f"{_PREFIX}/listener/state", principal.get("sub", "?"))
        ensure_started()
        return JSONResponse(listener_state())

    @a.get(f"{_PREFIX}/listener/selftest")
    def cc_v1_listener_selftest(
        principal: dict = Depends(session_api),
        limit: int = Query(default=20, ge=1, le=RING_CAPACITY),
    ) -> JSONResponse:
        """LE REFUS, motivé — et la preuve d'abonnement qui, elle, est lisible.

        Publier pour se prouver qu'on sait publier serait une écriture, un
        mensonge d'architecture, et de toute façon un refus du serveur. Cette
        route ne publie pas. Elle sert le refus, ses trois fondements, la preuve
        d'abonnement rendue par PostgreSQL, et la commande à taper hors du
        cockpit pour qui veut la preuve complète.
        """
        audit_read_log(f"{_PREFIX}/listener/selftest", principal.get("sub", "?"))
        ensure_started()
        payload = selftest()
        payload["recent"] = get_listener().recent(limit)
        return JSONResponse(payload)

    # -- l'oreille s'ouvre avec l'application, et se ferme avec elle ---------
    if _autostart_wanted():
        _add_event_handler(a, "startup", _on_startup)
    _add_event_handler(a, "shutdown", _on_shutdown)


def _add_event_handler(a: FastAPI, event: str, fn: Callable[[], None]) -> bool:
    """Branche un crochet de cycle de vie, quelle que soit la version du socle.

    ``add_event_handler`` a migré de l'application vers son routeur selon les
    versions de Starlette (absent de l'application en 1.0). On essaie les trois
    chemins connus, puis on renonce en le DISANT : un crochet manquant ne prive
    de rien — les routes démarrent l'écouteur paresseusement — mais un cockpit
    ne tait pas ce qu'il n'a pas pu faire.
    """
    router = getattr(a, "router", None)
    for target in (router, a):
        fn_add = getattr(target, "add_event_handler", None)
        if callable(fn_add):
            try:
                fn_add(event, fn)
                return True
            except Exception:  # noqa: BLE001 — on tente le chemin suivant
                pass
    bucket = getattr(router, f"on_{event}", None)
    if isinstance(bucket, list):
        bucket.append(fn)
        return True
    logger.warning("cc_v1.listener.hook_unavailable event=%s substitute=%s",
                   event, "démarrage paresseux à la première route",
                   extra={"event": event,
                          "substitute": "démarrage paresseux à la première route"})
    return False


def _on_startup() -> None:
    """Ouvre l'oreille. Ne lève jamais : un cockpit ne meurt pas d'un silence."""
    try:
        ensure_started()
    except Exception as exc:  # noqa: BLE001
        logger.warning("cc_v1.listener.autostart_failed raison=%s",
                       raison(exc),
                       extra={"error": type(exc).__name__}, exc_info=True)


def _on_shutdown() -> None:
    """Referme l'oreille et rend la connexion. Ne lève jamais."""
    try:
        stop()
    except Exception as exc:  # noqa: BLE001
        logger.warning("cc_v1.listener.shutdown_failed raison=%s",
                       raison(exc),
                       extra={"error": type(exc).__name__}, exc_info=True)
