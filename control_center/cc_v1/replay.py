"""Control Center v1 — LE REJEU : rejouer une journée du cerveau, image par image.

``/cc/v1/timeline`` sait déjà DIRE ce qui s'est passé entre deux bornes : des seaux
comptés et des événements datés. Il ne sait pas le REJOUER. Entre une liste et un
film il manque trois choses, et ce sont exactement les trois que ce module sert :

  1. des **images ordonnées** (``frames``) — un instantané par palier de temps,
     et non un événement par ligne ;
  2. une **cadence** (``frame_ms``, ``offset_ms``) — le client déclenche ses images
     sur son horloge à lui, sans jamais soustraire deux horodatages du cerveau ;
  3. des **cumuls déjà faits** (``cumulative``) — le compteur qui monte à l'écran
     est lu, pas accumulé côté client.

Routes exposées :

  GET /cc/v1/replay?day=AAAA-MM-JJ[&speed=&max_frames=]   une journée, en images
  GET /cc/v1/replay?from=&to=[&speed=&max_frames=]        une plage libre
  GET /cc/v1/replay/days?limit=30                         les journées rejouables

============================================================================
POURQUOI LES CUMULS SONT EN SQL, ET PAS DANS LE CLIENT
============================================================================

Un compteur qui monte est la chose la plus facile à faire mentir d'un cockpit :
il suffit qu'une image soit sautée, rejouée deux fois, ou reçue dans le désordre
pour que le total affiché à la fin du film ne soit celui d'aucune journée réelle.
Ce module refuse cette classe de bug par construction :

    sum(...) OVER (ORDER BY seau ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)

Chaque image porte le cumul EXACT à son instant, calculé par PostgreSQL sur la
totalité de la plage. Le client peut sauter des images, revenir en arrière, ou
poser le film sur pause : le chiffre affiché reste celui que la base soutient.
``totals`` est calculé par une requête SÉPARÉE et agrégée — donc le dernier cumul
et les totaux sont deux chemins indépendants vers le même nombre. S'ils divergent,
le contrôle de recette le voit (``scripts/ops/cc_v1_replay_smoke.py``).

Le cumul de ``scopes_touched`` mérite un mot : PostgreSQL n'accepte pas
``count(DISTINCT …) OVER (…)``. Le distinct cumulé est donc obtenu autrement, et
toujours en SQL : on date la PREMIÈRE apparition de chaque scope (``min(seau)``),
puis on somme ces premières apparitions dans la fenêtre glissante. Le résultat est
exact — et le total, calculé à part par un ``count(DISTINCT scope)``, le vérifie.

============================================================================
POURQUOI LE PAS DE TEMPS EST CHOISI PAR LA BASE
============================================================================

Une journée à 300 000 messages ne doit pas produire 300 000 images. Le pas de
temps n'est donc pas une constante : c'est le plus FIN des paliers de
``STEP_LADDER`` qui tient sous ``max_frames``, et il est élu **en SQL** — la base
compte, pour chaque palier candidat, combien de seaux distincts il produirait, et
retient le premier qui passe. Le pas retenu est servi (``step``), avec son libellé
et l'échelle complète : le client n'a rien à deviner, et le lecteur voit à quelle
maille il regarde. Si même le palier le plus grossier déborde, la réponse est
tronquée et le DIT (``truncated``) — jamais silencieusement.

Symétriquement : **aucune image n'est fabriquée pour meubler**. Un seau sans
événement n'existe pas. Une journée sans le moindre événement rend
``frames: []`` et ``empty: {is_empty: true, reason: …}`` — un film vide se dit,
il ne se remplit pas d'images noires qu'on prendrait pour un chargement.

============================================================================
DOCTRINE ANTI-FABULATION (identique à ``today.py``)
============================================================================

Le serveur ne compose AUCUNE phrase. Chaque événement porte
``{template_key, args, sources[]}`` ; les gabarits vivent dans
``REPLAY_TEMPLATES``, servi avec la réponse ; le client compose. Un gabarit inconnu
s'affiche ``[phrase inconnue : clé]`` — jamais un texte inventé pour boucher le
trou. Et **une phrase sans source est refusée** : ``_check_sources`` écarte tout
événement dont la liste ``sources`` est vide, en le comptant dans
``rejected_events``. De l'image on atteint la phrase, de la phrase le chiffre, du
chiffre la ligne.

LECTURE SEULE : uniquement des ``SELECT``/``WITH``, sur une connexion
``arac_readonly`` en ``default_transaction_read_only=on``, avec la garde lexicale
d'``entities._assert_read_only`` appliquée à chaque requête avant exécution.
Aucune valeur venue du client n'entre dans le corps d'une requête : bornes, pas,
plafonds et fuseau sont des PARAMÈTRES liés.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse

from control_center import config
from control_center.cc_v1 import service
from control_center.cc_v1.entities import (
    _clean,
    _failure,
    _one,
    _readonly,
    _rows,
    _sql_text,
)

__all__ = [
    "register",
    "replay",
    "replay_days",
    "REPLAY_TEMPLATES",
    "UNKNOWN_TEMPLATE",
    "EVENT_TYPES",
    "STEP_LADDER",
    "MAX_FRAMES",
    "SPEEDS",
    "CUMULATIVE_KEYS",
]

logger = logging.getLogger("arac.cc.v1.replay")

_PREFIX = "/cc/v1"

#: Motif ``LIKE`` du séparateur de scope, passé en PARAMÈTRE. psycopg réserve
#: ``%`` au marquage des paramètres : un ``LIKE '%/%'`` littéral casserait la
#: liaison de la requête.
_SLASH = "%/%"

#: Le fuseau DÉCLARÉ de ce cerveau. Une « journée » se découpe sur l'horloge de
#: son propriétaire, pas sur UTC : les créneaux circadiens observés dans les
#: reçus (04:00, 13:00, 21:00…) sont des heures locales du serveur. Le fuseau est
#: SERVI dans la réponse — un client qui afficherait un événement à 02:00 alors
#: que la base dit 00:00 UTC doit pouvoir le comprendre.
#:
#: POURQUOI une fonction et non une constante gravée : un fuseau écrit en dur ici
#: serait celui de la machine où ce fichier a été écrit, et découperait les
#: journées de tous les autres au mauvais endroit. La source est ``ARAC_CYCLE_TZ``
#: — la même que celle qui arme les minuteries des cycles — avec UTC pour repli
#: explicite. Lue à chaque appel : changer le fuseau ne demande pas de redémarrage.


def replay_tz() -> str:
    """Le nom du fuseau servi et utilisé pour découper les journées."""
    return config.cycle_tz()


def _tz() -> ZoneInfo:
    """Le fuseau courant, prêt pour l'arithmétique de dates."""
    return ZoneInfo(replay_tz())


# ---------------------------------------------------------------------------
# Bornes dures. Aucune n'est une préférence : au-delà, un film cesse d'être
# regardable et une requête cesse d'être sûre. Toute borne qui MORD est signalée
# dans la réponse — une troncature silencieuse est un mensonge.
# ---------------------------------------------------------------------------

#: Plafond dur du nombre d'images (mandat V3).
MAX_FRAMES = 600
#: Plancher : en dessous, on ne rejoue plus rien, on résume.
MIN_FRAMES = 5
#: Événements NARRATIFS détaillés par image. Au-delà, l'image devient une liste
#: et cesse d'être une image. Le compte réel est servi par image (``events_total``).
MAX_EVENTS_PER_FRAME = 12
#: Plage maximale acceptée pour ``from``/``to``. Au-delà, ce n'est plus un rejeu
#: de journée : c'est une chronologie, et ``/cc/v1/timeline`` la sert déjà.
MAX_RANGE_DAYS = 31
#: Journées listables par ``/cc/v1/replay/days``.
MAX_DAYS = 90
DEFAULT_DAYS = 30

#: L'échelle des paliers de temps, en secondes, du plus fin au plus grossier.
#: La base élit le premier qui tient sous ``max_frames`` (cf. le CTE ``essais``).
STEP_LADDER: tuple[int, ...] = (60, 120, 300, 600, 900, 1800, 3600, 7200, 14400, 21600)

#: Le libellé de chaque palier — servi, jamais recomposé côté client.
STEP_LABELS: dict[int, str] = {
    60: "minute par minute",
    120: "par 2 minutes",
    300: "par 5 minutes",
    600: "par 10 minutes",
    900: "par quart d'heure",
    1800: "par demi-heure",
    3600: "heure par heure",
    7200: "par 2 heures",
    14400: "par 4 heures",
    21600: "par 6 heures",
}

#: Durée d'affichage d'une image à vitesse 1. Ce n'est pas une donnée du cerveau :
#: c'est la cadence de projection, comme les 24 images/seconde d'un film.
BASE_FRAME_MS = 900

#: Vitesses offertes. Le paramètre ``speed`` sert d'INDEX dans ce tuple : une
#: valeur hors liste est ramenée à la plus proche offerte et signalée.
SPEEDS: tuple[float, ...] = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
DEFAULT_SPEED = 1.0

#: Les compteurs qu'une image porte, cumulés ET en delta. L'ordre est celui de
#: l'affichage ; il est servi (``counter_order``) pour que le client n'invente pas
#: le sien et que deux écrans ne classent pas les mêmes chiffres différemment.
#
# ``cycles_ended`` mérite sa place, et pas seulement pour le confort : sans lui,
# une image ne portant QUE la fin d'un cycle (le 4 août 2026 : quatre images sur
# trente-trois) affichait dix compteurs à zéro tout en montrant un événement. Une
# image sans le moindre delta est indiscernable d'une image fabriquée — donc
# chaque nature d'événement doit avoir son compteur, sans exception.
CUMULATIVE_KEYS: tuple[str, ...] = (
    "atoms",
    "atoms_superseded",
    "conversations_absorbed",
    "conversations_curated",
    "cycles",
    "cycles_ended",
    "cycles_quarantined",
    "candidates_dropped",
    "recalls",
    "messages",
    "scopes_touched",
)

#: Le libellé de chaque compteur — servi, jamais écrit dans le frontend.
COUNTER_LABELS: dict[str, str] = {
    "atoms": "atomes créés",
    "atoms_superseded": "atomes remplacés",
    "conversations_absorbed": "conversations absorbées",
    "conversations_curated": "conversations curées",
    # « cycles lancés » était faux : ce compteur suit les reçus de cycle
    # ENREGISTRÉS, dont 24 (7 sautés, 17 en échec de lancement) n'ont jamais
    # fait tourner le modèle.
    "cycles": "cycles enregistrés",
    "cycles_ended": "cycles terminés",
    "cycles_quarantined": "cycles en quarantaine",
    "candidates_dropped": "candidats écartés",
    "recalls": "rappels servis",
    "messages": "messages entrés",
    "scopes_touched": "domaines touchés",
}

#: Les natures d'événement qu'une image peut porter. ``messages_pouls`` et
#: ``rappels_pouls`` sont des DIGESTES : 3 459 messages en 22 minutes le 4 août
#: 2026 produiraient 3 459 événements et noieraient les 9 atomes nés le même jour.
#: Leur volume est l'information ; leur détail est du bruit. Cette asymétrie est
#: déclarée dans la réponse (``events_note``) plutôt que subie.
EVENT_TYPES: tuple[str, ...] = (
    "atome_cree",
    "atome_remplace",
    "conversation_absorbee",
    "conversation_curee",
    "cycle_demarre",
    "cycle_saute",
    "cycle_lancement_echoue",
    "cycle_termine",
    "candidat_ecarte",
    "messages_pouls",
    "rappels_pouls",
)

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Noms français, pour le seul ``day_label``. Formater une date est permis ;
#: agréger ne l'est pas. Aucun chiffre du cerveau ne passe par ici.
_FR_JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_FR_MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
            "août", "septembre", "octobre", "novembre", "décembre")


# ============================================================================
# LES GABARITS — le seul endroit de ce fichier où des mots sont écrits
# ============================================================================
#
# Le serveur ne les remplit JAMAIS. Il désigne une clé et fournit ses arguments ;
# le client compose. Ajouter une phrase, c'est ajouter un gabarit ICI et un
# ``template_key`` dans le SQL de la branche concernée — jamais une concaténation
# ailleurs. Le choix ENTRE deux gabarits (racine ou non, cycle abouti ou non) est
# un CASE SQL sur une valeur mesurée : c'est une sélection, pas une rédaction.

REPLAY_TEMPLATES: dict[str, str] = {
    # --- le savoir ----------------------------------------------------------
    "atome_cree":
        "{time} — nouvel atome {kind} dans {scope} : « {key} ».",
    "atome_cree_racine":
        "{time} — atome {kind} posé sur la racine {scope} : « {key} » — "
        "le rappel ne l'y verra jamais.",
    "atome_remplace":
        "{time} — l'atome « {key} » ({scope}) est remplacé après {age_jours} jour(s) : "
        "le cerveau a changé d'avis.",

    # --- l'ingestion --------------------------------------------------------
    "conversation_absorbee":
        "{time} — conversation absorbée : « {title} », {messages} message(s).",
    # 102 des 365 conversations n'ont pas de titre. Servir leur UID dans `title`
    # présentait un identifiant comme un nom : le lecteur ne pouvait plus
    # distinguer une conversation nommée d'une conversation anonyme.
    "conversation_absorbee_sans_titre":
        "{time} — conversation absorbée, sans titre enregistré ({uid}) : "
        "{messages} message(s).",
    "conversation_curee":
        "{time} — conversation curée : « {title} » → {atoms_generated} atome(s) retenu(s).",
    "conversation_curee_sterile":
        "{time} — conversation curée sans rien retenir : « {title} ».",
    "conversation_curee_en_echec":
        "{time} — la curation de « {title} » a échoué : {erreur}.",
    "conversation_curee_sans_titre":
        "{time} — conversation curée, sans titre enregistré ({uid}) → "
        "{atoms_generated} atome(s) retenu(s).",

    # --- la machine ---------------------------------------------------------
    "cycle_demarre":
        "{time} — le cycle {slot} démarre ({trigger}) sur {items} candidat(s).",
    # `cycle_demarre` était émis pour TOUS les reçus, y compris les `skipped`
    # (jamais lancés, ended_at NULL : aucun événement de fin ne viendra) et les
    # `spawn_failed` (le lancement a échoué). Le film racontait un démarrage qui
    # n'avait pas eu lieu, puis se contredisait trois minutes plus tard. Ces deux
    # clés disent ce qui s'est réellement produit à cet instant-là.
    "cycle_saute":
        "{time} — le cycle {slot} n'a pas été lancé ({skip_reason}).",
    "cycle_saute_sans_motif":
        "{time} — le cycle {slot} n'a pas été lancé ; aucun motif n'a été enregistré.",
    "cycle_lancement_echoue":
        "{time} — le lancement du cycle {slot} a échoué ({stop_reason}) : "
        "le modèle n'a jamais été appelé.",
    "cycle_lancement_echoue_sans_motif":
        "{time} — le lancement du cycle {slot} a échoué ; aucun motif d'arrêt "
        "n'a été enregistré.",
    "cycle_termine_done":
        "{time} — cycle {slot} abouti en {duree_s} s : {atoms_created} atome(s) créé(s), "
        "{atoms_superseded} remplacé(s).",
    "cycle_termine_quarantine":
        "{time} — cycle {slot} parti en quarantaine après {duree_s} s : "
        "ce qu'il portait n'a pas été retenu.",
    "cycle_termine_spawn_failed":
        "{time} — cycle {slot} n'a même pas démarré ({stop_reason}).",
    "cycle_termine_spawn_failed_sans_motif":
        "{time} — cycle {slot} n'a même pas démarré ; aucun motif d'arrêt "
        "n'a été enregistré.",
    "cycle_termine_autre":
        "{time} — cycle {slot} terminé avec l'état {status} après {duree_s} s.",
    "candidat_ecarte":
        "{time} — candidat écarté avant d'entrer en mémoire ({drop_reason}) dans {scope}.",
    "candidat_ecarte_sans_motif":
        "{time} — candidat écarté avant d'entrer en mémoire dans {scope} ; "
        "le motif n'a pas été enregistré.",
    "candidat_ecarte_sans_scope":
        "{time} — candidat écarté avant d'entrer en mémoire ({drop_reason}) ; "
        "aucun domaine ne lui avait été attribué.",

    # --- les digestes : le volume, pas le détail ----------------------------
    "messages_pouls":
        "{time} — {messages} message(s) entrent.",
    "rappels_pouls":
        "{time} — {recalls} rappel(s) servi(s).",

    # --- la journée elle-même (route /replay/days) --------------------------
    # CE QUI ÉTAIT FAUX : « … 5 cycle(s). » comptait les cycles PROGRAMMÉS. Le
    # 2026-08-04, 5 reçus pour 4 lancements réels (1 spawn_failed) ; le
    # 2026-08-05, 6 pour 4. La phrase créditait la machine d'un travail qui n'a
    # jamais eu lieu — la même erreur que `cycle_demarre` émis sur un cycle
    # `spawn_failed`, corrigée là et oubliée ici, alors que `jour_machine_seule`
    # (son gabarit frère) distingue déjà les deux comptes.
    # CE QUE CETTE VERSION GARANTIT : les deux nombres sont dits, et celui qui
    # porte le travail est celui des cycles RÉELLEMENT lancés.
    "jour_actif":
        "Le {day_label} : {atoms} atome(s), {conversations_absorbed} conversation(s) "
        "absorbée(s), {cycles_lances} cycle(s) lancé(s) sur {cycles} programmé(s).",
    "jour_machine_seule":
        "Le {day_label} : {cycles_lances} cycle(s) réellement lancé(s) sur {cycles} "
        "programmé(s), pour zéro atome — la machine a tourné sans rien retenir.",
    "jour_sans_lancement":
        "Le {day_label} : {cycles} cycle(s) programmé(s) et aucun n'a été lancé — "
        "le modèle n'a pas tourné de la journée.",
    "jour_sans_machine":
        "Le {day_label} : {events} événement(s), mais aucun cycle n'a été lancé.",
    "jour_vide":
        "Le {day_label} : aucun événement — rien n'est arrivé au cerveau ce jour-là.",
    # « rien n'est arrivé ce jour-là » était affirmé AU PASSÉ pour des journées qui
    # n'ont pas encore eu lieu (2026-12-25) et pour des journées antérieures au
    # premier fait enregistré (2026-01-01, le cerveau n'observant que depuis le
    # 2026-05-12). Une absence de trace hors de la vie du cerveau n'est pas un
    # constat sur le cerveau : ces deux clés le disent, plutôt que de le taire.
    "jour_a_venir":
        "Le {day_label} n'a pas encore eu lieu : il n'y a rien à rejouer.",
    "jour_avant_le_cerveau":
        "Le {day_label} est antérieur au premier fait enregistré ({premier_fait}) : "
        "le cerveau n'observait pas encore.",

    # --- ce que le rejeu ne sait pas montrer --------------------------------
    "mesure_indisponible":
        "Le rejeu ne peut pas montrer {measure} : {reason}.",
}

#: Ce que le client affiche pour une clé absente du dictionnaire. Il n'invente
#: jamais de texte de remplacement : il montre le trou.
UNKNOWN_TEMPLATE = "[phrase inconnue : {key}]"

#: Ce que le rejeu ne montrera pas, et pourquoi. Servi TEL QUEL dans la réponse :
#: le film doit pouvoir dire ce qu'il ne filme pas.
BLIND_SPOTS: tuple[dict[str, str], ...] = (
    {
        # POURQUOI le texte a changé : il affirmait que la table des liens
        # n'existait pas. Le rejeu ne l'a jamais vérifié — il servait l'état
        # d'une base sur laquelle il a été écrit. Ce qu'il SAIT, en revanche,
        # c'est que ses propres sources (les reçus de cycle) ne portent aucun
        # événement de création de lien. C'est cela qu'il déclare : une limite
        # de son film, pas un diagnostic de la base d'autrui.
        "measure": "la création d'un lien entre deux atomes",
        "state": "unavailable",
        "reason": ("aucun événement de création de lien n'est journalisé dans les "
                   "reçus de cycle : le rejeu n'a rien à filmer, même quand des "
                   "liens sont calculés"),
        "gesture": ("faites journaliser le recalcul des liens dans le reçu de "
                    "cycle pour qu'il devienne rejouable"),
        "substitute": "le voisinage sémantique du graphe de projet",
    },
    {
        "measure": "l'apparition d'une contradiction",
        "state": "unavailable",
        # « (0 atome de kind 'contradiction') » était un COMPTE : celui
        # d'une base, un jour. Le rejeu ne l'a jamais mesuré, et il ne peut
        # pas — c'est un texte figé. Ce qu'il peut affirmer, parce que c'est
        # vérifiable dans le dépôt et vrai chez tout le monde, c'est qu'aucun
        # code d'ici n'écrit d'atome de ce genre.
        "reason": "aucun code de ce dépôt n'écrit d'atome de kind "
                  "'contradiction' : il n'y a donc rien à filmer",
        "gesture": "aucun — le mécanisme n'existe pas encore côté moteur",
        "substitute": "les remplacements d'atomes, qui disent un changement d'avis",
    },
    {
        "measure": "la vérification d'un souvenir",
        "state": "unavailable",
        # Même correction : « NULL sur la totalité des atomes » décrivait
        # une base. La phrase porte désormais sur le dépôt, qui est ce que le
        # rejeu peut réellement connaître.
        "reason": "aucun agent de ce dépôt n'écrit last_verified_at ni "
                  "confirmed_until : la vérification d'un souvenir n'est "
                  "jamais un événement",
        "gesture": "aucun — le mécanisme n'existe pas encore côté moteur",
        "substitute": "les rappels servis, qui disent qu'un souvenir a été utilisé",
    },
)


# ============================================================================
# LES BRANCHES D'ÉVÉNEMENT — une par nature, toutes de même signature
# ============================================================================
#
# Chaque branche produit exactement neuf colonnes, dans cet ordre :
#     at, type, template_key, subject_kind, subject_id, subject_label, href,
#     args (jsonb), sources (jsonb)
# Les noms de colonnes viennent de la PREMIÈRE branche : les suivantes ne les
# répètent pas, c'est le contrat d'un UNION ALL.
#
# ``sources`` n'est jamais vide : chaque événement porte au moins un chemin
# résolvable vers la donnée qui le soutient. C'est ce qui rend une phrase
# opposable — et ``_check_sources`` écarte celles qui ne le seraient pas.
#
# Tout libellé passe par ``nullif(btrim(…), '')`` avant son ``coalesce`` de repli.
# Ce n'est pas de la coquetterie : 25 conversations de cette base portent un titre
# VIDE (chaîne de longueur nulle, pas NULL). Un simple ``coalesce`` les laissait
# passer, et le rejeu affichait « conversation curée : «  » » — une phrase sans
# sujet lisible, donc une phrase qui ne mène nulle part.

_EVENT_SQL: dict[str, str] = {
    "atome_cree": """
    SELECT a.created_at                                             AS at,
           'atome_cree'::text                                       AS type,
           CASE WHEN a.scope NOT LIKE %(slash)s THEN 'atome_cree_racine'::text
                ELSE 'atome_cree'::text END                         AS template_key,
           'atom'::text                                             AS subject_kind,
           a.id::text                                               AS subject_id,
           coalesce(nullif(btrim(a.key), ''), a.id::text)           AS subject_label,
           '/cc/v1/atoms/' || a.id::text || '/story'                AS href,
           jsonb_build_object(
               'time',   to_char(a.created_at AT TIME ZONE %(tz)s, 'HH24:MI'),
               'kind',   a.kind,
               'scope',  a.scope,
               'key',    coalesce(nullif(btrim(a.key), ''), a.id::text),
               'confidence_score', a.confidence_score,
               'taille', length(a.value),
               'invisible_au_rappel', (a.scope NOT LIKE %(slash)s))  AS args,
           jsonb_build_array(
               jsonb_build_object(
                   'kind',  'atom',
                   'label', coalesce(nullif(btrim(a.key), ''), a.id::text),
                   'href',  '/cc/v1/atoms/' || a.id::text || '/story'))
           || CASE WHEN a.source_ref ->> 'conversation_uid' IS NOT NULL
                   THEN jsonb_build_array(jsonb_build_object(
                            'kind',  'conversation',
                            'label', a.source_ref ->> 'conversation_uid',
                            'href',  '/cc/v1/conversations/'
                                     || (a.source_ref ->> 'conversation_uid')))
                   ELSE '[]'::jsonb END                              AS sources
      FROM arac.memory_atoms a, bornes b
     WHERE a.kind <> 'agent_message'
       AND a.created_at >= b.debut AND a.created_at < b.fin""",

    "atome_remplace": """
    SELECT a.updated_at,
           'atome_remplace'::text,
           'atome_remplace'::text,
           'atom'::text,
           a.id::text,
           coalesce(nullif(btrim(a.key), ''), a.id::text),
           '/cc/v1/atoms/' || a.id::text || '/story',
           jsonb_build_object(
               'time',      to_char(a.updated_at AT TIME ZONE %(tz)s, 'HH24:MI'),
               'kind',      a.kind,
               'scope',     a.scope,
               'key',       coalesce(nullif(btrim(a.key), ''), a.id::text),
               'version',   a.version,
               'successeur', a.superseded_by::text,
               'age_jours', round(extract(epoch FROM a.updated_at - a.created_at)
                                  / 86400.0, 1)),
           jsonb_build_array(
               jsonb_build_object(
                   'kind',  'atom',
                   'label', coalesce(nullif(btrim(a.key), ''), a.id::text),
                   'href',  '/cc/v1/atoms/' || a.id::text || '/story'))
      FROM arac.memory_atoms a, bornes b
     WHERE a.status = 'superseded'
       AND a.updated_at >= b.debut AND a.updated_at < b.fin""",

    "conversation_absorbee": """
    SELECT c.created_at,
           'conversation_absorbee'::text,
           CASE WHEN nullif(btrim(c.title), '') IS NULL
                     THEN 'conversation_absorbee_sans_titre'::text
                ELSE 'conversation_absorbee'::text END,
           'conversation'::text,
           c.conversation_uid,
           /* L'ÉTIQUETTE d'une source peut retomber sur l'UID : il faut bien
              nommer le lien. L'ARGUMENT d'une phrase, non — « conversation
              absorbée : « 0a1b2c3d-… » » présente un identifiant comme un titre,
              et le lecteur ne peut plus distinguer une conversation nommée d'une
              conversation anonyme. Une conversation sans titre est dans ce cas. */
           coalesce(nullif(btrim(c.title), ''), c.conversation_uid),
           '/cc/v1/conversations/' || c.conversation_uid,
           jsonb_build_object(
               'time',        to_char(c.created_at AT TIME ZONE %(tz)s, 'HH24:MI'),
               'title',       nullif(btrim(c.title), ''),
               'uid',         c.conversation_uid,
               'source_type', c.source_type,
               'messages',    (SELECT count(*) FROM arac.raw_messages rm
                                WHERE rm.conversation_id = c.id)),
           jsonb_build_array(
               jsonb_build_object(
                   'kind',  'conversation',
                   'label', coalesce(nullif(btrim(c.title), ''), c.conversation_uid),
                   'href',  '/cc/v1/conversations/' || c.conversation_uid))
      FROM arac.conversations c, bornes b
     WHERE c.created_at >= b.debut AND c.created_at < b.fin""",

    "conversation_curee": """
    SELECT c.curated_at,
           'conversation_curee'::text,
           CASE WHEN c.last_curation_error IS NOT NULL
                     THEN 'conversation_curee_en_echec'::text
                WHEN coalesce(c.atoms_generated, 0) = 0
                     THEN 'conversation_curee_sterile'::text
                WHEN nullif(btrim(c.title), '') IS NULL
                     THEN 'conversation_curee_sans_titre'::text
                ELSE 'conversation_curee'::text END,
           'conversation'::text,
           c.conversation_uid,
           coalesce(nullif(btrim(c.title), ''), c.conversation_uid),
           '/cc/v1/conversations/' || c.conversation_uid,
           jsonb_build_object(
               'time',            to_char(c.curated_at AT TIME ZONE %(tz)s, 'HH24:MI'),
               'title',           nullif(btrim(c.title), ''),
               'uid',             c.conversation_uid,
               'atoms_generated', c.atoms_generated,
               'erreur',          c.last_curation_error,
               'curated_through_message_id', c.curated_through_message_id),
           jsonb_build_array(
               jsonb_build_object(
                   'kind',  'conversation',
                   'label', coalesce(nullif(btrim(c.title), ''), c.conversation_uid),
                   'href',  '/cc/v1/conversations/' || c.conversation_uid))
      FROM arac.conversations c, bornes b
     WHERE c.curated_at >= b.debut AND c.curated_at < b.fin""",

    #: Les cycles RÉELLEMENT lancés. `skipped` et `spawn_failed` sont exclus ici
    #: et racontés par leurs propres blocs : un cycle qui n'a jamais tourné ne
    #: « démarre » pas, et le dire produisait une contradiction interne au film.
    "cycle_demarre": """
    SELECT r.started_at,
           'cycle_demarre'::text,
           'cycle_demarre'::text,
           'cycle'::text,
           r.id::text,
           coalesce(nullif(btrim(r.slot_key), ''), r.id::text),
           '/cc/v1/evidence/cycles_total',
           jsonb_build_object(
               'time',    to_char(r.started_at AT TIME ZONE %(tz)s, 'HH24:MI'),
               'slot',    coalesce(nullif(btrim(r.slot_key), ''), r.id::text),
               'trigger', r.trigger,
               'model',   r.model,
               'items',   r.items,
               'status',  r.status,
               'est_input_tokens', r.est_input_tokens),
           jsonb_build_array(
               jsonb_build_object(
                   'kind',  'metric',
                   'label', 'la répartition des cycles par issue (agrégat, pas la ligne de ce cycle)',
                   'href',  '/cc/v1/evidence/cycles_total'))
      FROM arac.run_receipts r, bornes b
     WHERE r.started_at >= b.debut AND r.started_at < b.fin
       AND r.status NOT IN ('skipped', 'spawn_failed')""",

    "cycle_saute": """
    SELECT r.started_at,
           'cycle_saute'::text,
           CASE WHEN nullif(btrim(r.skip_reason), '') IS NULL
                     THEN 'cycle_saute_sans_motif'::text
                ELSE 'cycle_saute'::text END,
           'cycle'::text,
           r.id::text,
           coalesce(nullif(btrim(r.slot_key), ''), r.id::text),
           '/cc/v1/evidence/cycles_total',
           jsonb_build_object(
               'time',        to_char(r.started_at AT TIME ZONE %(tz)s, 'HH24:MI'),
               'slot',        coalesce(nullif(btrim(r.slot_key), ''), r.id::text),
               'trigger',     r.trigger,
               'status',      r.status,
               'skip_reason', nullif(btrim(r.skip_reason), ''),
               'items',       r.items),
           jsonb_build_array(
               jsonb_build_object(
                   'kind',  'metric',
                   'label', 'la répartition des cycles par issue (agrégat, pas la ligne de ce cycle)',
                   'href',  '/cc/v1/evidence/cycles_total'))
      FROM arac.run_receipts r, bornes b
     WHERE r.started_at >= b.debut AND r.started_at < b.fin
       AND r.status = 'skipped'""",

    "cycle_lancement_echoue": """
    SELECT r.started_at,
           'cycle_lancement_echoue'::text,
           CASE WHEN nullif(btrim(r.stop_reason), '') IS NULL
                     THEN 'cycle_lancement_echoue_sans_motif'::text
                ELSE 'cycle_lancement_echoue'::text END,
           'cycle'::text,
           r.id::text,
           coalesce(nullif(btrim(r.slot_key), ''), r.id::text),
           '/cc/v1/evidence/cycles_total',
           jsonb_build_object(
               'time',        to_char(r.started_at AT TIME ZONE %(tz)s, 'HH24:MI'),
               'slot',        coalesce(nullif(btrim(r.slot_key), ''), r.id::text),
               'trigger',     r.trigger,
               'status',      r.status,
               'stop_reason', nullif(btrim(r.stop_reason), ''),
               'items',       r.items,
               'spawns',      r.spawns),
           jsonb_build_array(
               jsonb_build_object(
                   'kind',  'metric',
                   'label', 'la répartition des cycles par issue (agrégat, pas la ligne de ce cycle)',
                   'href',  '/cc/v1/evidence/cycles_total'))
      FROM arac.run_receipts r, bornes b
     WHERE r.started_at >= b.debut AND r.started_at < b.fin
       AND r.status = 'spawn_failed'""",

    "cycle_termine": """
    SELECT r.ended_at,
           'cycle_termine'::text,
           CASE
                WHEN r.status = 'done'         THEN 'cycle_termine_done'::text
                WHEN r.status = 'quarantined'  THEN 'cycle_termine_quarantine'::text
                WHEN r.status = 'spawn_failed'
                     AND nullif(btrim(r.stop_reason), '') IS NULL
                     THEN 'cycle_termine_spawn_failed_sans_motif'::text
                WHEN r.status = 'spawn_failed' THEN 'cycle_termine_spawn_failed'::text
                ELSE 'cycle_termine_autre'::text END,
           'cycle'::text,
           r.id::text,
           coalesce(nullif(btrim(r.slot_key), ''), r.id::text),
           '/cc/v1/evidence/cycles_total',
           jsonb_build_object(
               'time',   to_char(r.ended_at AT TIME ZONE %(tz)s, 'HH24:MI'),
               'slot',   coalesce(nullif(btrim(r.slot_key), ''), r.id::text),
               'status', r.status,
               /* NULL, et non « non renseignée » : 130 des 148 reçus n'ont pas de
                  stop_reason, et une prose de substitution servie dans un ARGUMENT
                  devient indiscernable d'une donnée. Le gabarit jumeau
                  `..._sans_motif` dit l'absence ; le client rend déjà null par «—». */
               'stop_reason', nullif(btrim(r.stop_reason), ''),
               'atoms_created',    r.atoms_created,
               'atoms_superseded', r.atoms_superseded,
               'atoms_quarantined', r.atoms_quarantined,
               'duree_s', round(extract(epoch FROM r.ended_at - r.started_at))),
           jsonb_build_array(
               jsonb_build_object(
                   'kind',  'metric',
                   'label', 'la répartition des cycles par issue (agrégat, pas la ligne de ce cycle)',
                   'href',  '/cc/v1/evidence/cycles_total'))
      FROM arac.run_receipts r, bornes b
     WHERE r.ended_at IS NOT NULL
       AND r.ended_at >= b.debut AND r.ended_at < b.fin""",

    "candidat_ecarte": """
    SELECT q.created_at,
           'candidat_ecarte'::text,
           /* Le choix du gabarit est un CASE sur une valeur MESURÉE — c'est une
              sélection, pas une rédaction. Ce qui était interdit, c'était de
              remplir le trou avec de la prose (« motif non renseigné », « sans
              scope », agrammatical de surcroît dans « … dans sans scope »). */
           CASE WHEN nullif(btrim(q.drop_reason), '') IS NULL
                     THEN 'candidat_ecarte_sans_motif'::text
                WHEN nullif(btrim(q.scope), '') IS NULL
                     THEN 'candidat_ecarte_sans_scope'::text
                ELSE 'candidat_ecarte'::text END,
           'candidate'::text,
           q.id::text,
           coalesce(nullif(btrim(q.drop_reason), ''), q.id::text),
           '/cc/v1/evidence/drop_reasons_total',
           jsonb_build_object(
               'time',        to_char(q.created_at AT TIME ZONE %(tz)s, 'HH24:MI'),
               'drop_reason', nullif(btrim(q.drop_reason), ''),
               'scope',       nullif(btrim(q.scope), ''),
               'kind',        q.kind,
               'run_ref',     q.run_ref,
               'conversation_uid', q.conversation_uid),
           jsonb_build_array(
               jsonb_build_object(
                   'kind',  'metric',
                   'label', 'la répartition des motifs d''écartement (agrégat, pas la ligne de ce candidat)',
                   'href',  '/cc/v1/evidence/drop_reasons_total'))
      FROM arac.digestion_review_queue q, bornes b
     WHERE q.created_at >= b.debut AND q.created_at < b.fin""",
}


# ============================================================================
# LA REQUÊTE DES IMAGES — tout le film en un aller-retour
# ============================================================================
#
# Lecture de haut en bas : les bornes, les événements narratifs, le pouls
# (messages et rappels, pré-agrégés à la minute pour qu'un jour à 300 000
# messages ne fasse pas 300 000 lignes), l'élection du pas, les seaux, les
# deltas, les cumuls glissants, puis les images.

_FRAMES_SQL_HEAD = """
WITH bornes AS (
    SELECT %(debut)s::timestamptz AS debut,
           %(fin)s::timestamptz   AS fin
), narratif AS (
"""

_FRAMES_SQL_TAIL = """
), pouls AS (
    SELECT date_trunc('minute', m.received_at) AS at,
           'message'::text                     AS type,
           count(*)                            AS n
      FROM arac.raw_messages m, bornes b
     WHERE m.received_at >= b.debut AND m.received_at < b.fin
     GROUP BY 1
    UNION ALL
    SELECT date_trunc('minute', cr.created_at),
           'rappel'::text,
           count(*)
      FROM arac.context_receipts cr, bornes b
     WHERE cr.created_at >= b.debut AND cr.created_at < b.fin
     GROUP BY 1
), instants AS (
    SELECT at FROM narratif
    UNION ALL
    SELECT at FROM pouls
), echelle AS (
    SELECT unnest(%(ladder)s::int[]) AS pas_s
), essais AS (
    SELECT e.pas_s,
           (SELECT count(DISTINCT floor(extract(epoch FROM i.at) / e.pas_s))
              FROM instants i) AS nb_seaux
      FROM echelle e
), pas AS (
    SELECT coalesce(
               (SELECT min(pas_s) FROM essais WHERE nb_seaux <= %(max_frames)s),
               (SELECT max(pas_s) FROM echelle)) AS pas_s
), seau_narratif AS (
    SELECT n.*,
           to_timestamp(floor(extract(epoch FROM n.at) / p.pas_s) * p.pas_s) AS seau
      FROM narratif n CROSS JOIN pas p
), seau_pouls AS (
    SELECT o.*,
           to_timestamp(floor(extract(epoch FROM o.at) / p.pas_s) * p.pas_s) AS seau
      FROM pouls o CROSS JOIN pas p
), scopes_premiere_fois AS (
    SELECT t.scope, min(t.seau) AS seau
      FROM (SELECT sn.args ->> 'scope' AS scope, sn.seau
              FROM seau_narratif sn
             WHERE sn.type = 'atome_cree') t
     WHERE t.scope IS NOT NULL
     GROUP BY t.scope
), scopes_par_seau AS (
    SELECT seau, count(*) AS n FROM scopes_premiere_fois GROUP BY seau
), delta_narratif AS (
    SELECT seau,
           count(*) FILTER (WHERE type = 'atome_cree')            AS atoms,
           count(*) FILTER (WHERE type = 'atome_remplace')        AS atoms_superseded,
           count(*) FILTER (WHERE type = 'conversation_absorbee') AS conversations_absorbed,
           count(*) FILTER (WHERE type = 'conversation_curee')    AS conversations_curated,
           /* `cycles` compte les reçus de cycle ENREGISTRÉS dans le seau, ce que
              `_TOTALS_SQL` compte aussi (un reçu = un started_at). Depuis que
              `cycle_demarre` exclut les cycles jamais lancés, il faut y réunir
              leurs deux blocs frères, sans quoi le dernier cumul cesserait
              d'égaler `totals` — l'invariant que la recette vérifie. */
           count(*) FILTER (WHERE type IN ('cycle_demarre', 'cycle_saute',
                                           'cycle_lancement_echoue'))
                                                                 AS cycles,
           count(*) FILTER (WHERE type = 'cycle_termine')         AS cycles_ended,
           count(*) FILTER (WHERE type = 'cycle_demarre'
                              AND args ->> 'status' = 'quarantined') AS cycles_quarantined,
           count(*) FILTER (WHERE type = 'candidat_ecarte')       AS candidates_dropped
      FROM seau_narratif
     GROUP BY seau
), delta_pouls AS (
    SELECT seau,
           coalesce(sum(n) FILTER (WHERE type = 'rappel'), 0)  AS recalls,
           coalesce(sum(n) FILTER (WHERE type = 'message'), 0) AS messages
      FROM seau_pouls
     GROUP BY seau
), cles AS (
    SELECT seau FROM seau_narratif
    UNION
    SELECT seau FROM seau_pouls
), base AS (
    SELECT k.seau,
           coalesce(dn.atoms, 0)                  AS atoms,
           coalesce(dn.atoms_superseded, 0)       AS atoms_superseded,
           coalesce(dn.conversations_absorbed, 0) AS conversations_absorbed,
           coalesce(dn.conversations_curated, 0)  AS conversations_curated,
           coalesce(dn.cycles, 0)                 AS cycles,
           coalesce(dn.cycles_ended, 0)           AS cycles_ended,
           coalesce(dn.cycles_quarantined, 0)     AS cycles_quarantined,
           coalesce(dn.candidates_dropped, 0)     AS candidates_dropped,
           coalesce(dp.recalls, 0)                AS recalls,
           coalesce(dp.messages, 0)               AS messages,
           coalesce(sp.n, 0)                      AS scopes_touched
      FROM cles k
      LEFT JOIN delta_narratif  dn ON dn.seau = k.seau
      LEFT JOIN delta_pouls     dp ON dp.seau = k.seau
      LEFT JOIN scopes_par_seau sp ON sp.seau = k.seau
), cadre AS (
    SELECT b.*,
           row_number() OVER (ORDER BY b.seau)                       AS seq,
           count(*)     OVER ()                                      AS frames_total,
           ((row_number() OVER (ORDER BY b.seau)) - 1)
               * %(frame_ms)s::bigint                                AS offset_ms,
           (extract(epoch FROM b.seau - (SELECT debut FROM bornes))
               * 1000)::bigint                                       AS wall_offset_ms,
           sum(b.atoms)                  OVER w AS cum_atoms,
           sum(b.atoms_superseded)       OVER w AS cum_atoms_superseded,
           sum(b.conversations_absorbed) OVER w AS cum_conversations_absorbed,
           sum(b.conversations_curated)  OVER w AS cum_conversations_curated,
           sum(b.cycles)                 OVER w AS cum_cycles,
           sum(b.cycles_ended)           OVER w AS cum_cycles_ended,
           sum(b.cycles_quarantined)     OVER w AS cum_cycles_quarantined,
           sum(b.candidates_dropped)     OVER w AS cum_candidates_dropped,
           sum(b.recalls)                OVER w AS cum_recalls,
           sum(b.messages)               OVER w AS cum_messages,
           sum(b.scopes_touched)         OVER w AS cum_scopes_touched
      FROM base b
    WINDOW w AS (ORDER BY b.seau ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
), classe AS (
    SELECT sn.*,
           row_number() OVER (PARTITION BY sn.seau
                              ORDER BY sn.at, sn.type, sn.subject_id) AS rang
      FROM seau_narratif sn
), evenements AS (
    SELECT seau,
           count(*) AS total,
           coalesce(
               jsonb_agg(
                   jsonb_build_object(
                       'type',         type,
                       'at',           at,
                       'template_key', template_key,
                       'args',         args,
                       'subject', jsonb_build_object(
                           'kind',  subject_kind,
                           'id',    subject_id,
                           'label', subject_label,
                           'href',  href),
                       'sources',      sources)
                   ORDER BY rang)
                   FILTER (WHERE rang <= %(per_frame)s),
               '[]'::jsonb) AS liste
      FROM classe
     GROUP BY seau
)
SELECT c.seq,
       c.seau                                          AS at,
       to_char(c.seau AT TIME ZONE %(tz)s, 'HH24:MI')  AS at_label,
       c.offset_ms,
       c.wall_offset_ms,
       c.frames_total,
       coalesce(e.total, 0)                            AS events_total,
       (coalesce(e.total, 0) > %(per_frame)s)          AS events_truncated,
       coalesce(e.liste, '[]'::jsonb)
       || CASE WHEN c.messages > 0 THEN jsonb_build_array(jsonb_build_object(
              'type', 'messages_pouls',
              'at',   c.seau,
              'template_key', 'messages_pouls',
              'args', jsonb_build_object(
                  'time', to_char(c.seau AT TIME ZONE %(tz)s, 'HH24:MI'),
                  'messages', c.messages),
              'subject', jsonb_build_object(
                  'kind', 'pulse', 'id', 'messages',
                  'label', 'messages entrés',
                  'href', '/cc/v1/timeline?from='
                          || to_char(c.seau AT TIME ZONE 'UTC',
                                     'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                          || '&to='
                          || to_char((c.seau + make_interval(secs => p.pas_s))
                                     AT TIME ZONE 'UTC',
                                     'YYYY-MM-DD"T"HH24:MI:SS"Z"')),
              'sources', jsonb_build_array(jsonb_build_object(
                  'kind', 'timeline',
                  'label', 'la chronologie de ce palier',
                  'href', '/cc/v1/timeline?from='
                          || to_char(c.seau AT TIME ZONE 'UTC',
                                     'YYYY-MM-DD"T"HH24:MI:SS"Z"')
                          || '&to='
                          || to_char((c.seau + make_interval(secs => p.pas_s))
                                     AT TIME ZONE 'UTC',
                                     'YYYY-MM-DD"T"HH24:MI:SS"Z"')))))
          ELSE '[]'::jsonb END
       || CASE WHEN c.recalls > 0 THEN jsonb_build_array(jsonb_build_object(
              'type', 'rappels_pouls',
              'at',   c.seau,
              'template_key', 'rappels_pouls',
              'args', jsonb_build_object(
                  'time', to_char(c.seau AT TIME ZONE %(tz)s, 'HH24:MI'),
                  'recalls', c.recalls),
              'subject', jsonb_build_object(
                  'kind', 'pulse', 'id', 'recalls',
                  'label', 'rappels servis',
                  'href', '/cc/v1/evidence/recall_receipts_total'),
              'sources', jsonb_build_array(jsonb_build_object(
                  'kind', 'metric',
                  'label', 'les reçus de rappel, ligne à ligne',
                  'href', '/cc/v1/evidence/recall_receipts_total'))))
          ELSE '[]'::jsonb END                         AS events,
       jsonb_build_object(
           'atoms',                  c.cum_atoms,
           'atoms_superseded',       c.cum_atoms_superseded,
           'conversations_absorbed', c.cum_conversations_absorbed,
           'conversations_curated',  c.cum_conversations_curated,
           'cycles',                 c.cum_cycles,
           'cycles_ended',           c.cum_cycles_ended,
           'cycles_quarantined',     c.cum_cycles_quarantined,
           'candidates_dropped',     c.cum_candidates_dropped,
           'recalls',                c.cum_recalls,
           'messages',               c.cum_messages,
           'scopes_touched',         c.cum_scopes_touched)  AS cumulative,
       jsonb_build_object(
           'atoms',                  c.atoms,
           'atoms_superseded',       c.atoms_superseded,
           'conversations_absorbed', c.conversations_absorbed,
           'conversations_curated',  c.conversations_curated,
           'cycles',                 c.cycles,
           'cycles_ended',           c.cycles_ended,
           'cycles_quarantined',     c.cycles_quarantined,
           'candidates_dropped',     c.candidates_dropped,
           'recalls',                c.recalls,
           'messages',               c.messages,
           'scopes_touched',         c.scopes_touched)      AS deltas,
       p.pas_s                                              AS step_seconds
  FROM cadre c
  CROSS JOIN pas p
  LEFT JOIN evenements e ON e.seau = c.seau
 ORDER BY c.seq
 LIMIT %(max_frames)s"""


#: LE PLANCHER DE LA VIE DU CERVEAU, et l'instant présent — lus en SQL, comme le
#: reste. Sans ces deux bornes, ``jour_vide`` affirmait « rien n'est arrivé au
#: cerveau ce jour-là » d'une journée à venir comme d'une journée où le cerveau
#: n'existait pas. L'agrégation (``least`` sur quatre ``min``) est faite par la
#: base : Python ne fait que comparer trois instants déjà servis.
_PLANCHER_SQL = """
SELECT least((SELECT min(r.started_at)  FROM arac.run_receipts r),
             (SELECT min(c.created_at)  FROM arac.conversations c),
             (SELECT min(a.created_at)  FROM arac.memory_atoms a),
             (SELECT min(m.received_at) FROM arac.raw_messages m)) AS plancher,
       now()                                                       AS maintenant"""


#: Les totaux, calculés PAR UNE AUTRE ROUTE ARITHMÉTIQUE que les cumuls. C'est
#: volontaire : deux chemins indépendants vers le même nombre, donc un contrôle
#: mutuel. Le dernier cumul DOIT égaler ces totaux — la recette le vérifie.
_TOTALS_SQL = """
SELECT
    (SELECT count(*) FROM arac.memory_atoms a
      WHERE a.kind <> 'agent_message'
        AND a.created_at >= %(debut)s::timestamptz
        AND a.created_at <  %(fin)s::timestamptz)                    AS atoms,
    (SELECT count(*) FROM arac.memory_atoms a
      WHERE a.status = 'superseded'
        AND a.updated_at >= %(debut)s::timestamptz
        AND a.updated_at <  %(fin)s::timestamptz)                    AS atoms_superseded,
    (SELECT count(*) FROM arac.conversations c
      WHERE c.created_at >= %(debut)s::timestamptz
        AND c.created_at <  %(fin)s::timestamptz)                    AS conversations_absorbed,
    (SELECT count(*) FROM arac.conversations c
      WHERE c.curated_at >= %(debut)s::timestamptz
        AND c.curated_at <  %(fin)s::timestamptz)                    AS conversations_curated,
    (SELECT count(*) FROM arac.run_receipts r
      WHERE r.started_at >= %(debut)s::timestamptz
        AND r.started_at <  %(fin)s::timestamptz)                    AS cycles,
    (SELECT count(*) FROM arac.run_receipts r
      WHERE r.ended_at IS NOT NULL
        AND r.ended_at >= %(debut)s::timestamptz
        AND r.ended_at <  %(fin)s::timestamptz)                      AS cycles_ended,
    (SELECT count(*) FROM arac.run_receipts r
      WHERE r.status = 'quarantined'
        AND r.started_at >= %(debut)s::timestamptz
        AND r.started_at <  %(fin)s::timestamptz)                    AS cycles_quarantined,
    (SELECT count(*) FROM arac.digestion_review_queue q
      WHERE q.created_at >= %(debut)s::timestamptz
        AND q.created_at <  %(fin)s::timestamptz)                    AS candidates_dropped,
    (SELECT count(*) FROM arac.context_receipts cr
      WHERE cr.created_at >= %(debut)s::timestamptz
        AND cr.created_at <  %(fin)s::timestamptz)                   AS recalls,
    (SELECT count(*) FROM arac.raw_messages m
      WHERE m.received_at >= %(debut)s::timestamptz
        AND m.received_at <  %(fin)s::timestamptz)                   AS messages,
    (SELECT count(DISTINCT a.scope) FROM arac.memory_atoms a
      WHERE a.kind <> 'agent_message'
        AND a.created_at >= %(debut)s::timestamptz
        AND a.created_at <  %(fin)s::timestamptz)                    AS scopes_touched"""


# ============================================================================
# LA LISTE DES JOURNÉES REJOUABLES — /cc/v1/replay/days
# ============================================================================
#
# Une journée SANS événement doit APPARAÎTRE dans la liste, marquée vide. C'est
# le point dur de cette route : le 2026-08-03 a vu six cycles tourner pour zéro
# atome. Une liste qui n'afficherait que les journées « intéressantes » ferait
# disparaître exactement ce qu'il faut voir. La grille des jours est donc
# produite par ``generate_series`` et les compteurs y sont JOINTS À GAUCHE : le
# jour existe d'abord, ses chiffres ensuite.

_DAYS_SQL = """
WITH grille AS (
    SELECT d::date AS jour
      FROM generate_series(%(premier)s::date, %(dernier)s::date, interval '1 day') d
), atomes AS (
    SELECT (a.created_at AT TIME ZONE %(tz)s)::date AS jour,
           count(*)                                 AS n,
           count(DISTINCT a.scope)                  AS scopes
      FROM arac.memory_atoms a
     WHERE a.kind <> 'agent_message'
       AND a.created_at >= %(debut)s::timestamptz AND a.created_at < %(fin)s::timestamptz
     GROUP BY 1
), remplaces AS (
    SELECT (a.updated_at AT TIME ZONE %(tz)s)::date AS jour, count(*) AS n
      FROM arac.memory_atoms a
     WHERE a.status = 'superseded'
       AND a.updated_at >= %(debut)s::timestamptz AND a.updated_at < %(fin)s::timestamptz
     GROUP BY 1
), absorbees AS (
    SELECT (c.created_at AT TIME ZONE %(tz)s)::date AS jour, count(*) AS n
      FROM arac.conversations c
     WHERE c.created_at >= %(debut)s::timestamptz AND c.created_at < %(fin)s::timestamptz
     GROUP BY 1
), curees AS (
    SELECT (c.curated_at AT TIME ZONE %(tz)s)::date AS jour, count(*) AS n
      FROM arac.conversations c
     WHERE c.curated_at >= %(debut)s::timestamptz AND c.curated_at < %(fin)s::timestamptz
     GROUP BY 1
), cycles AS (
    SELECT (r.started_at AT TIME ZONE %(tz)s)::date AS jour,
           count(*)                                          AS n,
           count(*) FILTER (WHERE r.status = 'quarantined')   AS quarantaine,
           count(*) FILTER (WHERE r.status = 'done')          AS aboutis,
           /* Les cycles qui ont RÉELLEMENT fait tourner le modèle. « 6 cycle(s)
              pour zéro atome — la machine a tourné sans rien retenir » était faux
              le 2026-08-03 : sur ces six, deux n'avaient jamais été lancés
              (skipped) et deux avaient échoué au lancement (spawn_failed). La
              machine n'avait pas « tourné sans rien retenir » : elle n'avait pas
              tourné. */
           count(*) FILTER (WHERE r.status NOT IN ('skipped', 'spawn_failed'))
                                                              AS lances
      FROM arac.run_receipts r
     WHERE r.started_at >= %(debut)s::timestamptz AND r.started_at < %(fin)s::timestamptz
     GROUP BY 1
), cycles_finis AS (
    SELECT (r.ended_at AT TIME ZONE %(tz)s)::date AS jour, count(*) AS n
      FROM arac.run_receipts r
     WHERE r.ended_at IS NOT NULL
       AND r.ended_at >= %(debut)s::timestamptz AND r.ended_at < %(fin)s::timestamptz
     GROUP BY 1
), ecartes AS (
    SELECT (q.created_at AT TIME ZONE %(tz)s)::date AS jour, count(*) AS n
      FROM arac.digestion_review_queue q
     WHERE q.created_at >= %(debut)s::timestamptz AND q.created_at < %(fin)s::timestamptz
     GROUP BY 1
), rappels AS (
    SELECT (cr.created_at AT TIME ZONE %(tz)s)::date AS jour, count(*) AS n
      FROM arac.context_receipts cr
     WHERE cr.created_at >= %(debut)s::timestamptz AND cr.created_at < %(fin)s::timestamptz
     GROUP BY 1
), messages AS (
    SELECT (m.received_at AT TIME ZONE %(tz)s)::date AS jour, count(*) AS n
      FROM arac.raw_messages m
     WHERE m.received_at >= %(debut)s::timestamptz AND m.received_at < %(fin)s::timestamptz
     GROUP BY 1
), assemblage AS (
    SELECT g.jour,
           coalesce(at.n, 0)          AS atoms,
           coalesce(at.scopes, 0)     AS scopes_touched,
           coalesce(rm.n, 0)          AS atoms_superseded,
           coalesce(ab.n, 0)          AS conversations_absorbed,
           coalesce(cu.n, 0)          AS conversations_curated,
           coalesce(cy.n, 0)          AS cycles,
           coalesce(cf.n, 0)          AS cycles_ended,
           coalesce(cy.quarantaine, 0) AS cycles_quarantined,
           coalesce(cy.aboutis, 0)    AS cycles_done,
           coalesce(cy.lances, 0)     AS cycles_lances,
           coalesce(ec.n, 0)          AS candidates_dropped,
           coalesce(rp.n, 0)          AS recalls,
           coalesce(ms.n, 0)          AS messages
      FROM grille g
      LEFT JOIN atomes    at ON at.jour = g.jour
      LEFT JOIN remplaces rm ON rm.jour = g.jour
      LEFT JOIN absorbees ab ON ab.jour = g.jour
      LEFT JOIN curees    cu ON cu.jour = g.jour
      LEFT JOIN cycles       cy ON cy.jour = g.jour
      LEFT JOIN cycles_finis cf ON cf.jour = g.jour
      LEFT JOIN ecartes   ec ON ec.jour = g.jour
      LEFT JOIN rappels   rp ON rp.jour = g.jour
      LEFT JOIN messages  ms ON ms.jour = g.jour
)
SELECT a.jour::text AS day,
       a.atoms, a.atoms_superseded, a.conversations_absorbed, a.conversations_curated,
       a.cycles, a.cycles_ended, a.cycles_quarantined, a.cycles_done, a.cycles_lances,
       a.candidates_dropped,
       a.recalls, a.messages, a.scopes_touched,
       (a.atoms + a.atoms_superseded + a.conversations_absorbed
        + a.conversations_curated + a.cycles + a.cycles_ended
        + a.candidates_dropped + a.recalls + a.messages)
                                                        AS events,
       (a.atoms + a.atoms_superseded + a.conversations_absorbed
        + a.conversations_curated + a.cycles + a.cycles_ended
        + a.candidates_dropped + a.recalls + a.messages) = 0
                                                        AS is_empty,
       CASE
           WHEN (a.atoms + a.atoms_superseded + a.conversations_absorbed
                 + a.conversations_curated + a.cycles + a.cycles_ended
                 + a.candidates_dropped + a.recalls + a.messages) = 0
                                                        THEN 'jour_vide'
           WHEN a.cycles > 0 AND a.cycles_lances = 0    THEN 'jour_sans_lancement'
           WHEN a.cycles > 0 AND a.atoms = 0            THEN 'jour_machine_seule'
           WHEN a.cycles = 0                            THEN 'jour_sans_machine'
           ELSE 'jour_actif'
       END                                              AS template_key,
       '/cc/v1/replay?day=' || a.jour::text             AS href
  FROM assemblage a
 ORDER BY a.jour DESC"""


# ============================================================================
# Validation des entrées — aucune ne devient jamais un fragment de SQL
# ============================================================================


def _fr_day_label(d: date) -> str:
    """« mardi 4 août 2026 ». Du formatage, pas du calcul : aucun chiffre du
    cerveau ne passe par cette fonction."""
    return f"{_FR_JOURS[d.weekday()]} {d.day} {_FR_MOIS[d.month - 1]} {d.year}"


# ---------------------------------------------------------------------------
# LES BORNES DU CALENDRIER — pourquoi elles existent
# ---------------------------------------------------------------------------
#
# CE QUI ÉTAIT FAUX : `?day=9999-12-31` et `?to=0001-01-01` rendaient une 500
# « Internal Server Error », alors que la docstring de `replay()` promet
# explicitement « Ne lève jamais ». Deux OverflowError, tous deux dans de
# l'arithmétique de dates faite AVANT toute validation :
#   - `fin = debut + timedelta(days=1)` déborde `datetime.max` au 31 décembre 9999 ;
#   - `_parse_instant(from_, fin - timedelta(days=1))` : l'expression par défaut
#     est évaluée AVANT l'appel, et sous-déborde `datetime.min` sous le 2 janvier 1.
# Les deux sont atteignables depuis l'écran (#/rejeu?day=…), qui n'affichait alors
# qu'un code HTTP nu, sans dire quel paramètre avait fauté.
#
# CE QUE CES BORNES GARANTISSENT : toute date ISO 8601 légale entre en fonction et
# en ressort — ramenée dans le calendrier rejouable, et SIGNALÉE dans `notices`.
# Deux jours de marge de chaque côté couvrent les ±1 jour et le décalage de fuseau
# que la suite du corps applique.
# Le jour n'a besoin que d'un jour de marge (``fin = debut + 1 jour``) : la borne
# haute reste donc 9999-12-30, qui répondait déjà 200 avant ce correctif. Seul
# 9999-12-31, qui déborde vraiment, est refusé — et il est refusé en 200 motivé.
_JOUR_MIN = date(1, 1, 2)
_JOUR_MAX = date(9999, 12, 30)
# Ces deux bornes ne datent rien : elles bornent le CALENDRIER. Elles sont donc
# ancrées en UTC et non dans le fuseau du cerveau — un garde-fou qui bougerait
# avec la configuration ne garderait plus rien.
_INSTANT_MIN = datetime(1, 1, 3, tzinfo=timezone.utc)
_INSTANT_MAX = datetime(9999, 12, 29, tzinfo=timezone.utc)


def _parse_day(raw: Any) -> tuple[date | None, str | None]:
    """Lit un ``AAAA-MM-JJ``. Rend la date et, le cas échéant, ce qui a cloché."""
    s = _clean(raw)
    if not s:
        return None, None
    if not _DAY_RE.match(s):
        return None, f"jour {s!r} illisible (AAAA-MM-JJ attendu) — jour du jour appliqué"
    try:
        jour = date.fromisoformat(s)
    except ValueError:
        return None, f"jour {s!r} inexistant au calendrier — jour du jour appliqué"
    if not (_JOUR_MIN <= jour <= _JOUR_MAX):
        return None, (f"jour {s!r} hors des bornes calendaires du rejeu "
                      f"({_JOUR_MIN.isoformat()} → {_JOUR_MAX.isoformat()}) — "
                      "jour du jour appliqué")
    return jour, None


def _utc_z(moment: datetime) -> str:
    """« 2026-08-03T22:00:00Z ». Une borne SANS ambiguïté de fuseau.

    Toute borne servie à un autre module doit porter son fuseau : celui qui la
    relira n'a pas à deviner lequel on avait en tête. Du formatage, pas du calcul.
    """
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_dt(raw: Any) -> datetime | None:
    """Relit un instant SERVI par la base (ISO 8601 UTC) en ``datetime``.

    ``service._jsonable`` rend les horodatages en ISO ; les comparer suppose de
    les relire. C'est une conversion de type, pas un calcul : aucune valeur n'est
    additionnée, soustraite ni agrégée ici.
    """
    if isinstance(raw, datetime):
        return raw
    s = _clean(raw)
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        return None


def _borner_instant(moment: datetime) -> tuple[datetime, str | None]:
    """Ramène une borne dans le calendrier rejouable. Ne lève jamais.

    Comparer deux dates et en choisir une n'est pas de l'arithmétique sur les
    données du cerveau : c'est la validation d'une entrée HTTP, au même titre que
    ``_pick_speed``. Aucun chiffre mesuré ne passe par ici.
    """
    if moment < _INSTANT_MIN:
        return _INSTANT_MIN, (f"borne {moment.isoformat()!r} antérieure au calendrier "
                              f"rejouable — ramenée à {_INSTANT_MIN.isoformat()}")
    if moment > _INSTANT_MAX:
        return _INSTANT_MAX, (f"borne {moment.isoformat()!r} postérieure au calendrier "
                              f"rejouable — ramenée à {_INSTANT_MAX.isoformat()}")
    return moment, None


def _parse_instant(raw: Any, default: datetime) -> tuple[datetime, str | None]:
    """Lit une borne ISO 8601. Validation d'une entrée HTTP, pas un calcul."""
    s = _clean(raw)
    if not s:
        return default, None
    txt = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        parsed = datetime.fromisoformat(txt)
    except ValueError:
        return default, f"borne {s!r} illisible (ISO 8601 attendu) — valeur par défaut appliquée"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_tz())
    return _borner_instant(parsed)


def _pick_speed(raw: Any) -> tuple[float, str | None]:
    """Ramène la vitesse demandée à l'une des vitesses OFFERTES.

    Ce n'est pas de l'arithmétique sur les données du cerveau : c'est le choix
    d'une cadence de projection, comme les 24 images/seconde d'un film.
    """
    s = _clean(raw)
    if s is None:
        return DEFAULT_SPEED, None
    try:
        asked = float(s)
    except ValueError:
        return DEFAULT_SPEED, (f"vitesse {s!r} illisible — {DEFAULT_SPEED}× appliquée "
                               f"(offertes : {', '.join(str(v) for v in SPEEDS)})")
    if asked in SPEEDS:
        return asked, None
    nearest = min(SPEEDS, key=lambda v: (abs(v - asked), v))
    return nearest, (f"vitesse {asked}× non offerte — {nearest}× appliquée "
                     f"(offertes : {', '.join(str(v) for v in SPEEDS)})")


def _bounded_frames(raw: Any) -> tuple[int, str | None]:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return MAX_FRAMES, None
    if n < MIN_FRAMES:
        return MIN_FRAMES, f"max_frames ramené au plancher de {MIN_FRAMES} images"
    if n > MAX_FRAMES:
        return MAX_FRAMES, f"max_frames ramené au plafond dur de {MAX_FRAMES} images"
    return n, None


def _check_sources(frames: list[dict[str, Any]]) -> int:
    """Écarte tout événement dont la liste ``sources`` est vide.

    Troisième garde-fou de la doctrine anti-fabulation : une phrase sans source
    n'est pas une phrase, c'est une affirmation. Le SQL construit toujours au
    moins une source — cette fonction est le filet qui vérifie que c'est vrai, et
    le compte des rejets est SERVI dans la réponse plutôt que tu.
    """
    rejected = 0
    for f in frames:
        gardes: list[dict[str, Any]] = []
        for ev in f.get("events") or []:
            src = ev.get("sources")
            if isinstance(src, list) and src and all(
                    isinstance(s, dict) and s.get("href") for s in src):
                gardes.append(ev)
            else:
                rejected += 1
        f["events"] = gardes
    if rejected:
        # Un rejet est une ANOMALIE : le SQL construit toujours une source, donc
        # si ce filet attrape quelque chose, une branche d'événement a régressé.
        # Il est compté dans la réponse ET journalisé — un filet silencieux ne
        # protège que celui qui l'a posé.
        logger.warning("cc_v1.replay_event_without_source", extra={"rejected": rejected})
    return rejected


# ============================================================================
# LE REJEU — /cc/v1/replay
# ============================================================================


def replay(day: Any = None, from_: Any = None, to: Any = None,
           speed: Any = None, max_frames: Any = None) -> dict[str, Any]:
    """Rejoue une journée (ou une plage) du cerveau, image par image.

    Ne lève jamais. Un jour illisible, une vitesse non offerte, une plage trop
    large : chacun est remplacé par sa valeur par défaut et SIGNALÉ dans
    ``notices``. Un rejeu qui refuse de répondre n'aide personne à regarder sa
    journée.
    """
    notices: list[str] = []

    vitesse, why = _pick_speed(speed)
    if why:
        notices.append(why)
    frame_ms = int(round(BASE_FRAME_MS / vitesse))

    plafond, why = _bounded_frames(max_frames)
    if why:
        notices.append(why)

    jour, why = _parse_day(day)
    if why:
        notices.append(why)

    maintenant = datetime.now(_tz())
    if jour is not None or (from_ is None and to is None):
        cible = jour or maintenant.date()
        debut = datetime(cible.year, cible.month, cible.day, tzinfo=_tz())
        fin = debut + timedelta(days=1)
        day_iso: str | None = cible.isoformat()
        day_label = _fr_day_label(cible)
    else:
        fin, why = _parse_instant(to, maintenant)
        if why:
            notices.append(why)
        # `fin` est déjà bornée par `_parse_instant` : la soustraction ci-dessous,
        # évaluée AVANT l'appel, ne peut donc plus sous-déborder `datetime.min`.
        # C'est le second des deux OverflowError qui rendaient une 500 nue.
        debut, why = _parse_instant(from_, fin - timedelta(days=1))
        if why:
            notices.append(why)
        if debut >= fin:
            notices.append("borne de début postérieure à la fin — plage ramenée à 24 h")
            debut = fin - timedelta(days=1)
        if (fin - debut) > timedelta(days=MAX_RANGE_DAYS):
            notices.append(f"plage réduite au maximum de {MAX_RANGE_DAYS} jours — "
                           f"au-delà, c'est /cc/v1/timeline qu'il faut interroger")
            debut = fin - timedelta(days=MAX_RANGE_DAYS)
        day_iso = None
        day_label = (f"{_fr_day_label(debut.astimezone(_tz()).date())} "
                     f"→ {_fr_day_label(fin.astimezone(_tz()).date())}")

    params: dict[str, Any] = {
        "debut": debut.isoformat(),
        "fin": fin.isoformat(),
        "tz": replay_tz(),
        "slash": _SLASH,
        "ladder": list(STEP_LADDER),
        "max_frames": plafond,
        "per_frame": MAX_EVENTS_PER_FRAME,
        "frame_ms": frame_ms,
    }
    frames_sql = (_FRAMES_SQL_HEAD
                  + "\n    UNION ALL\n".join(_EVENT_SQL[t] for t in _EVENT_SQL)
                  + _FRAMES_SQL_TAIL)

    started = time.perf_counter()
    try:
        with _readonly() as conn:
            frames = _rows(conn, frames_sql, params, where="replay.frames")
            totaux = _one(conn, _TOTALS_SQL, params, where="replay.totals") or {}
            vie = _one(conn, _PLANCHER_SQL, {}, where="replay.plancher") or {}
            preuve_frames = _sql_text(conn, frames_sql, params)
            preuve_totaux = _sql_text(conn, _TOTALS_SQL, params)
    except Exception as exc:  # noqa: BLE001 — une panne se dit, elle ne se déguise pas
        return _failure("replay", exc)

    rejected = _check_sources(frames)
    if rejected:
        notices.append(f"{rejected} événement(s) écarté(s) faute de source résolvable — "
                       "une phrase sans preuve n'est pas servie")

    frames_total = int(frames[0]["frames_total"]) if frames else 0
    step_seconds = int(frames[0]["step_seconds"]) if frames else STEP_LADDER[0]
    tronque = frames_total > len(frames)
    if tronque:
        notices.append(f"rejeu tronqué à {len(frames)} images sur {frames_total} : "
                       f"resserre la plage ou augmente max_frames "
                       f"(plafond dur : {MAX_FRAMES})")

    # Les images ne portent pas leurs colonnes de service : elles sont remontées
    # dans l'enveloppe, où elles décrivent le film et non l'image.
    for f in frames:
        f.pop("frames_total", None)
        f.pop("step_seconds", None)

    est_vide = not frames
    empty = None
    if est_vide:
        # TROIS ABSENCES, PAS UNE. `est_vide = not frames` était la seule condition :
        # le rejeu affirmait au passé « rien n'est arrivé au cerveau ce jour-là »
        # aussi bien pour le 25 décembre 2026 (qui n'a pas eu lieu) que pour le
        # 1er janvier 2026 (le premier fait enregistré date du 2026-05-12). Les deux
        # bornes sont lues en SQL ; Python ne fait ici que comparer trois instants.
        plancher = _as_dt(vie.get("plancher"))
        present = _as_dt(vie.get("maintenant")) or maintenant
        if debut > present:
            empty = {
                "is_empty": None,
                "state": "unavailable",
                "reason": "cette journée n'a pas encore eu lieu",
                "template_key": "jour_a_venir",
                "args": {"day_label": day_label},
                "gesture": "choisis une journée déjà écoulée : /cc/v1/replay/days les liste",
                "substitute": f"instant présent en base : {present.isoformat()}",
            }
        elif plancher is not None and fin <= plancher:
            empty = {
                "is_empty": None,
                "state": "unavailable",
                "reason": (f"cette journée est antérieure au premier fait enregistré "
                           f"({plancher.date().isoformat()})"),
                "template_key": "jour_avant_le_cerveau",
                "args": {"day_label": day_label,
                         "premier_fait": plancher.date().isoformat()},
                "gesture": "choisis une journée postérieure au premier fait enregistré",
                "substitute": f"premier fait enregistré : {plancher.isoformat()}",
            }
        else:
            empty = {
                "is_empty": True,
                "state": "ok",
                "reason": ("aucun événement ce jour-là" if day_iso
                           else "aucun événement sur cette plage"),
                "template_key": "jour_vide",
                "args": {"day_label": day_label},
                "gesture": "essaie une autre journée : /cc/v1/replay/days les liste toutes",
            }
        empty["premier_fait_enregistre"] = plancher.isoformat() if plancher else None

    duree_s = (fin - debut).total_seconds()
    return {
        "state": "ok",
        "range": {
            "from": debut.isoformat(),
            "to": fin.isoformat(),
            "day": day_iso,
            "day_label": day_label,
            "timezone": replay_tz(),
            "duration_hours": duree_s / 3600.0,
        },
        # La cadence de projection. ``frame_ms`` est la durée d'affichage d'une
        # image ; ``offset_ms`` (porté par chaque image) est l'instant de
        # déclenchement sur l'horloge du CLIENT. Rejouer, c'est poser un timer —
        # aucune soustraction d'horodatage du cerveau n'est demandée au client.
        "frame_ms": frame_ms,
        "speed": {"applied": vitesse, "available": list(SPEEDS), "base_frame_ms": BASE_FRAME_MS},
        "step": {
            "seconds": step_seconds,
            "label": STEP_LABELS.get(step_seconds, f"par {step_seconds} secondes"),
            "elected_by": ("le plus fin palier de l'échelle qui tient sous max_frames, "
                           "élu en SQL"),
            "ladder": [{"seconds": s, "label": STEP_LABELS[s]} for s in STEP_LADDER],
        },
        "frames": frames,
        "totals": {k: totaux.get(k) for k in CUMULATIVE_KEYS},
        "counter_order": list(CUMULATIVE_KEYS),
        "counter_labels": dict(COUNTER_LABELS),
        "templates": dict(REPLAY_TEMPLATES),
        "unknown_template": UNKNOWN_TEMPLATE,
        "event_types": list(EVENT_TYPES),
        "truncated": {
            "applied": tronque,
            "shown": len(frames),
            "total": frames_total,
            "limit": plafond,
            "hard_limit": MAX_FRAMES,
            "events_per_frame": MAX_EVENTS_PER_FRAME,
        },
        "empty": empty,
        "rejected_events": rejected,
        "events_note": ("les messages bruts et les rappels ne produisent pas d'événement "
                        "individuel : ils sont agrégés en un digeste par image "
                        "(messages_pouls, rappels_pouls), où leur volume informe — "
                        "leur détail noierait les atomes"),
        "cumulative_note": ("les cumuls sont calculés en SQL par fenêtre glissante "
                            "(sum() OVER … ROWS UNBOUNDED PRECEDING) ; le client les LIT. "
                            "totals est calculé par une requête séparée : le dernier cumul "
                            "doit l'égaler, et c'est vérifiable"),
        "blind_spots": [dict(b) for b in BLIND_SPOTS],
        "notices": notices,
        "links": {
            "days": "/cc/v1/replay/days",
            "timeline": "/cc/v1/timeline",
            "today": "/cc/v1/today",
        },
        "evidence": {
            "kind": "sql",
            "sql": preuve_frames,
            "label": "les images de la plage demandée, telles que la base les compose",
            "queries": [preuve_frames, preuve_totaux],
        },
        "computed_at": service._now(),
        "duration_ms": service._ms(started),
    }


# ============================================================================
# LES JOURNÉES REJOUABLES — /cc/v1/replay/days
# ============================================================================


def replay_days(limit: Any = DEFAULT_DAYS) -> dict[str, Any]:
    """Les journées rejouables, de la plus récente à la plus ancienne.

    Une journée SANS événement y figure, marquée ``is_empty``. C'est le point :
    « le cerveau n'a rien fait le 3 août » est une information, et une liste qui
    la masquerait mentirait par omission.
    """
    notices: list[str] = []
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = DEFAULT_DAYS
    if n < 1:
        n, _ = 1, notices.append("limit ramené à 1 journée")
    if n > MAX_DAYS:
        n = MAX_DAYS
        notices.append(f"limit ramené au plafond de {MAX_DAYS} journées")

    aujourdhui = datetime.now(_tz()).date()
    premier = aujourdhui - timedelta(days=n - 1)
    debut = datetime(premier.year, premier.month, premier.day, tzinfo=_tz())
    fin = datetime(aujourdhui.year, aujourdhui.month, aujourdhui.day, tzinfo=_tz()) \
        + timedelta(days=1)

    params: dict[str, Any] = {
        "premier": premier.isoformat(),
        "dernier": aujourdhui.isoformat(),
        "debut": debut.isoformat(),
        "fin": fin.isoformat(),
        "tz": replay_tz(),
    }

    started = time.perf_counter()
    try:
        with _readonly() as conn:
            jours = _rows(conn, _DAYS_SQL, params, where="replay.days")
            preuve = _sql_text(conn, _DAYS_SQL, params)
    except Exception as exc:  # noqa: BLE001
        return _failure("replay.days", exc)

    # Chaque journée porte sa PHRASE sous forme de clé + arguments + sources.
    # Le serveur ne compose rien : il désigne, il documente, il prouve.
    for j in jours:
        d = date.fromisoformat(j["day"])
        j["day_label"] = _fr_day_label(d)
        j["args"] = {
            "day_label": j["day_label"],
            "day": j["day"],
            "atoms": j["atoms"],
            "conversations_absorbed": j["conversations_absorbed"],
            "cycles": j["cycles"],
            "cycles_done": j["cycles_done"],
            "cycles_lances": j["cycles_lances"],
            "cycles_quarantined": j["cycles_quarantined"],
            "events": j["events"],
        }
        # CE QUI ÉTAIT FAUX : ce lien portait un ISO NAÏF (« 2026-08-04T00:00:00 »)
        # construit à partir d'un jour calendaire LOCAL, alors que
        # `lifestory._parse_instant` force toute borne sans fuseau à UTC. Dès que
        # le fuseau du cerveau n'est pas UTC, la même « journée » ne porte donc
        # pas les mêmes chiffres selon l'écran — le décalage vaut exactement le
        # décalage du fuseau, et il grandit avec lui.
        #
        # CE QUE CETTE VERSION GARANTIT : les bornes partent du fuseau du rejeu
        # (celui-là même qui a découpé la journée dans `_DAYS_SQL`, `AT TIME ZONE
        # %(tz)s`) et sont sérialisées en UTC explicite — le même geste que le SQL
        # des images fait déjà (`to_char(… AT TIME ZONE 'UTC', …"Z"')`).
        debut_jour = datetime(d.year, d.month, d.day, tzinfo=_tz())
        fin_jour = debut_jour + timedelta(days=1)
        j["sources"] = [
            {"kind": "replay", "label": f"rejouer le {j['day_label']}", "href": j["href"]},
            {"kind": "timeline",
             "label": "la chronologie de cette journée",
             "href": (f"/cc/v1/timeline"
                      f"?from={_utc_z(debut_jour)}&to={_utc_z(fin_jour)}"
                      f"&granularity=hour")},
        ]

    vides = [j["day"] for j in jours if j["is_empty"]]
    machine_seule = [j["day"] for j in jours if j["template_key"] == "jour_machine_seule"]

    return {
        "state": "ok",
        "range": {"from": premier.isoformat(), "to": aujourdhui.isoformat(),
                  "timezone": replay_tz(), "days": len(jours)},
        "days": jours,
        "count": len(jours),
        "limit": n,
        "templates": dict(REPLAY_TEMPLATES),
        "unknown_template": UNKNOWN_TEMPLATE,
        "counter_labels": dict(COUNTER_LABELS),
        # Les deux formes de journée qu'il ne faut PAS masquer, comptées et
        # nommées : ce sont elles qui disent la santé du cerveau.
        "empty_days": {"count": len(vides), "days": vides,
                       "note": "journées sans le moindre événement — rejouables, et vides"},
        "machine_only_days": {
            "count": len(machine_seule), "days": machine_seule,
            "note": "journées où des cycles ont tourné pour zéro atome : "
                    "la machine a travaillé sans rien retenir"},
        "notices": notices,
        "links": {"replay": "/cc/v1/replay?day=", "timeline": "/cc/v1/timeline"},
        "evidence": {
            "kind": "sql",
            "sql": preuve,
            "label": "les journées et leur volume, tels que la base les compte",
        },
        "computed_at": service._now(),
        "duration_ms": service._ms(started),
    }


# ============================================================================
# Enregistrement des routes — GET uniquement, session + journal de lecture
# ============================================================================


def register(
    a: FastAPI,
    session_api: Callable[..., Any],
    audit_read_log: Callable[[str, str], Any],
) -> None:
    """Enregistre les deux routes du rejeu sur l'application.

    Args:
        a: l'instance FastAPI du Control Center.
        session_api: la dépendance de session en mode API (401 JSON si absente).
        audit_read_log: le journal de lecture du socle (chemin, principal).
    """

    @a.get(f"{_PREFIX}/replay/days")
    def cc_v1_replay_days(
        principal: dict = Depends(session_api),
        limit: int = Query(default=DEFAULT_DAYS, ge=1, le=MAX_DAYS),
    ) -> JSONResponse:
        """Les journées rejouables et leur volume — journées vides comprises.

        Déclarée AVANT ``/replay`` : sans cela, rien ne garantit l'ordre de
        résolution si un jour ``/replay/{quelque chose}`` était ajouté.
        """
        audit_read_log(f"{_PREFIX}/replay/days", principal.get("sub", "?"))
        return JSONResponse(replay_days(limit=limit))

    @a.get(f"{_PREFIX}/replay")
    def cc_v1_replay(
        principal: dict = Depends(session_api),
        day: str | None = Query(default=None, max_length=32),
        from_: str | None = Query(default=None, alias="from", max_length=64),
        to: str | None = Query(default=None, max_length=64),
        speed: str | None = Query(default=None, max_length=16),
        max_frames: int = Query(default=MAX_FRAMES, ge=MIN_FRAMES, le=MAX_FRAMES),
    ) -> JSONResponse:
        """Une journée du cerveau, rejouable image par image.

        ``day=AAAA-MM-JJ`` (dans le fuseau déclaré du cerveau, servi en
        ``range.timezone``) ou ``from``/``to`` en ISO 8601.
        Chaque image porte son ``offset_ms`` de déclenchement et ses cumuls déjà
        faits : le client projette, il ne calcule pas. Une journée vide rend
        ``frames: []`` et le DIT dans ``empty``.
        """
        audit_read_log(f"{_PREFIX}/replay", principal.get("sub", "?"))
        return JSONResponse(replay(day=day, from_=from_, to=to,
                                   speed=speed, max_frames=max_frames))
