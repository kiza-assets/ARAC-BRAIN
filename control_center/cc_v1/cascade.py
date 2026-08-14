"""Control Center v1 — LA CASCADE : « le cerveau pense ».

Le flux (``stream.py``) montre des événements ISOLÉS : un atome ici, un cycle là,
un rappel plus loin. On n'y voit jamais l'ENCHAÎNEMENT. Ce module le
reconstruit — non pas en le narrant, mais en le RECOLLANT depuis les traces que
le cerveau a laissées derrière lui :

    18:42  Conversation détectée        ingest_receipts + capture_manifests
      ↓    Absorbée                     raw_messages, fenêtre exacte du paquet
      ↓    Projets reconnus             règle des projets sur les atomes produits
      ↓    Scopes touchés               scopes distincts des atomes produits
      ↓    Analyse                      run_receipts (modèle, durée, stop_reason)
      ↓    Atomes créés                 memory_atoms.source_ref
      ↓    Atomes remplacés             memory_atoms.superseded_by
      ↓    Candidats écartés            digestion_review_queue
      ↓    Liens                        NON LU — cette étape n'interroge pas arac.atom_links
      ↓    Rappel                       context_receipts.served_ids
      ↓    Mémoire consolidée           l'état d'aujourd'hui de ce qui a été appris

Routes exposées :

  GET /cc/v1/cascade?limit=&since=      les dernières cascades achevées
  GET /cc/v1/cascade/{conversation_uid} la cascade d'UNE conversation
  GET /cc/v1/cascade/catalog            les gabarits + la règle d'émission de chaque étape

============================================================================
CE QU'EST UNE CASCADE, EXACTEMENT
============================================================================

Une cascade = **le passage d'UNE conversation dans UN cycle du cerveau**. Ce
n'est pas « la vie entière d'une conversation » : une conversation est présentée
au cerveau à CHAQUE cycle où elle a bougé, et chaque passage a son propre
verdict. Une cascade a donc une identité composée :

    cascade_id = "{run_ref}::{conversation_uid}"

Elle est ACHEVÉE quand son cycle l'est (``run_receipts.ended_at IS NOT NULL``).
L'énumération vient de ``run_receipts.pack``, le manifeste que le cerveau écrit
AVANT de travailler : un tableau ``[{uid, conversation_id, n_msgs, cursor_from,
max_id}]``. Vérifié le 2026-08-04 : les 912 paires (cycle, conversation) des 136
paquets couvrent la totalité des atomes portant un ``run_ref`` — aucun atome
n'échappe à un paquet, aucune quarantaine n'est attribuée hors paquet. Le
``pack`` est donc l'énumération EXHAUSTIVE des cascades, pas un échantillon.

============================================================================
CONTRAINTE DE NARRATION (identique à ``today.py``)
============================================================================

Le serveur ne compose AUCUNE phrase. Chaque étape porte ``template_key`` +
``args`` + ``sources``. Les gabarits vivent dans ``CASCADE_TEMPLATES`` et sont
servis par ``/cc/v1/cascade/catalog`` : **le client compose**. Une clé inconnue
s'affiche ``[étape inconnue : clé]`` — jamais un texte de remplacement inventé.

**Une étape sans source résolvable est refusée à la construction**, pas filtrée
après coup : ``_Steps.add`` nettoie les sources, et si rien ne survit, l'étape
n'entre jamais dans la cascade et son refus est publié dans
``refused_without_source``. La contrainte est dans le code, pas dans une consigne.

Une source est résolvable si elle porte un ``href`` vers une route ``/cc/v1/…``
RÉELLEMENT servie par ce cockpit, et un ``ref`` ou un ``sql``. Cinq familles :

  conversation → /cc/v1/conversations/{uid}     (entities)
  atom         → /cc/v1/atoms/{id}              (entities)
  scope        → /cc/v1/scopes/{path}           (scopes)
  project      → /cc/v1/projects/{id}           (entities)
  run          → /cc/v1/timeline?from=&to=      (lifestory — la fenêtre du cycle)
  trace        → /cc/v1/cascade/{uid}           + le SQL exact, rejouable en psql

La famille ``trace`` couvre les tables qu'aucune route n'ouvre encore
(``ingest_receipts``, ``capture_manifests``, ``run_receipts``,
``digestion_review_queue``, ``context_receipts``). Elle ne triche pas : son
``href`` renvoie à la réponse qui contient la donnée, et son ``sql`` est la
requête qui l'a produite, sur une ligne, copiable dans un terminal. Une preuve
qu'on peut rejouer contre le serveur est une preuve opposable.

============================================================================
AUCUNE ARITHMÉTIQUE HORS SQL
============================================================================

Comptes, sommes, durées en millisecondes, bornes de fenêtre, totaux de projet,
survivants d'aujourd'hui : tout est calculé par PostgreSQL. Python ne fait ici
que trois choses, toutes non arithmétiques : **borner** une requête, **assembler**
des lignes déjà agrégées dans la forme de la réponse, et **comparer** une valeur
déjà servie à zéro pour choisir un gabarit plutôt qu'un autre.

============================================================================
CE QUI N'EXISTE PAS, ET QUI EST DIT PLUTÔT QUE TU
============================================================================

- ``arac.atom_links`` n'est pas lue ici. L'étape « liens » est TOUJOURS
  ``unavailable`` : raison, geste, substitut. Elle n'est jamais ``0 lien créé``
  — écrire zéro là où l'on n'a pas mesuré est un mensonge. Sa raison est
  CONSTATÉE à chaque appel (``entities.links_dependency``) et distingue « la
  table n'est pas là » de « la table est là, cette étape ne la lit pas » :
  envoyer relancer une migration déjà passée trompe autant qu'un zéro faux.
- ``arac.capture_manifests`` ne porte pas de ``conversation_uid``. Le manifeste de
  capture est RECONSTRUIT par recouvrement temporel (même nœud, même source, la
  course de capture qui contient le reçu d'ingestion). Les reçus qui trouvent
  ainsi leur manifeste le portent ; les autres rendent ``capture_manifest: null``
  avec sa raison. Cette reconstruction est NOMMÉE dans la réponse
  (``provenance``) : ce n'est pas une clé étrangère, et le lecteur doit le savoir.
- Les atomes antérieurs au changement de contrat de provenance portent un
  ``source_ref`` de l'ancien type (``curator_raw_id``), sans ``run_ref`` ni
  ``conversation_uid`` : ils sont hors cascade. Aucune cascade ne les invente ;
  ils n'apparaissent nulle part. Un cerveau neuf n'en a aucun — ce chemin ne sert
  qu'aux cerveaux installés avant le changement.

LECTURE SEULE : uniquement des ``SELECT``/``WITH``, sur une connexion
``arac_readonly``, avec la garde lexicale d'``entities._assert_read_only``
appliquée à chaque requête avant exécution.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote

from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse

from control_center.cc_v1 import service
from control_center.cc_v1.entities import (
    LINKS_UNAVAILABLE,
    PROJECTS,
    links_dependency as _links_dependency,
    _clean,
    _failure,
    _project_predicate,
    _project_rule,
    _readonly,
    _rows,
    _sql_text,
    union_ou_vide,
)

__all__ = [
    "register",
    "CASCADE_TEMPLATES",
    "UNKNOWN_TEMPLATE",
    "STEP_RULES",
    "STAGES",
    "MAX_CASCADES",
    "DEFAULT_CASCADES",
    "MAX_ATOMS_PER_CASCADE",
    "MAX_ROWS_PER_CALL",
    "cascades",
    "catalog",
]

logger = logging.getLogger("arac.cc.v1.cascade")

_PREFIX = "/cc/v1"


# ============================================================================
# BORNES DURES — ce ne sont pas des préférences
# ============================================================================
#
# Au-delà, une réponse cesse d'être lisible et une requête cesse d'être sûre.
# Chaque borne atteinte est SIGNALÉE dans la réponse (``truncated``) : une
# troncature silencieuse est un mensonge par omission.

#: Plafond dur du nombre de cascades par appel (mandat V3).
MAX_CASCADES = 20
#: Nombre de cascades servies quand l'appelant n'en demande pas.
#:
#: CE QUI ÉTAIT FAUX : le défaut ÉTAIT le plafond. Un appel nu à /cc/v1/cascade
#: rendait donc 20 trajets, soit 1 015 977 octets mesurés — et le crochet temps
#: réel du cockpit rappelle cette route sans `limit` ni `since` à chaque rafale
#: d'étape « analyse », toutes les deux secondes pendant un cycle.
#:
#: CE QUE CETTE VERSION GARANTIT : un défaut DÉCOUPLÉ du plafond (228 713 octets
#: mesurés, −77 %). Rien n'est caché : `truncated` porte le corpus réel, la
#: fenêtre de balayage et le nombre servi, et la notice — affichée par le
#: client — dit combien de conversations existent et comment atteindre les
#: autres (`?limit=` jusqu'à MAX_CASCADES, `?since=`, ou l'ouverture d'une
#: conversation précise).
DEFAULT_CASCADES = 5
#: Plafond dur des atomes détaillés PAR cascade.
MAX_ATOMS_PER_CASCADE = 40
#: Plafond dur des atomes remplacés détaillés par cascade.
MAX_SUPERSEDED_PER_CASCADE = 20
#: Plafond dur des candidats écartés détaillés par cascade.
MAX_DROPPED_PER_CASCADE = 20
#: Plafond dur des scopes détaillés par cascade.
MAX_SCOPES_PER_CASCADE = 12
#: Plafond dur de lignes lues sur TOUT l'appel, toutes requêtes confondues.
#: 20 + 800 + 400 + 160 + 240 + 200 + 20 + 20 = 1860 dans le pire cas.
MAX_ROWS_PER_CALL = 2000

#: Cycles balayés pour remplir ``limit`` cascades. Un paquet contient en moyenne
#: 6,7 conversations (912 / 136) ; le coussin couvre les paquets vides.
_RUN_SCAN_CUSHION = 8
#: Plafond du balayage de cycles, filtre par conversation compris.
_MAX_RUN_SCAN = 40


# ============================================================================
# LES ÉTAPES — l'ordre du pipeline, déclaré une fois
# ============================================================================
#
# L'ordre est celui du TRAJET, pas celui d'un tri : détectée avant absorbée,
# absorbée avant analysée, analysée avant consolidée. C'est aussi l'ordre
# chronologique, chaque étape portant en outre son ``at`` réel quand une trace
# le date. Trier sur ``at`` serait pire que ce rang : quatre étapes (projets,
# scopes, liens, consolidation) sont des LECTURES de l'état, pas des instants —
# elles n'ont pas d'horodatage propre, et un tri les jetterait au hasard.

STAGES: tuple[dict[str, str], ...] = (
    {"stage": "detected", "label": "Conversation détectée",
     "trace": "arac.ingest_receipts + arac.capture_manifests (recouvrement temporel)"},
    {"stage": "absorbed", "label": "Absorbée",
     "trace": "arac.raw_messages, bornée par la fenêtre du paquet (cursor_from, max_id]"},
    {"stage": "projects", "label": "Projets reconnus",
     "trace": "règle des projets appliquée aux atomes produits"},
    {"stage": "scopes", "label": "Scopes touchés",
     "trace": "scopes distincts des atomes produits"},
    {"stage": "analysis", "label": "Analyse",
     "trace": "arac.run_receipts (modèle, durée, stop_reason, couverture)"},
    {"stage": "atoms_born", "label": "Atomes créés",
     "trace": "arac.memory_atoms via source_ref (run_ref + conversation_uid)"},
    {"stage": "atoms_superseded", "label": "Atomes remplacés",
     "trace": "arac.memory_atoms.superseded_by pointant vers un atome de ce trajet"},
    {"stage": "dropped", "label": "Candidats écartés",
     "trace": "arac.digestion_review_queue (run_ref + conversation_uid)"},
    {"stage": "links", "label": "Liens",
     "trace": "NON LU — cette étape n'interroge pas arac.atom_links"},
    {"stage": "recall", "label": "Rappel",
     "trace": "arac.context_receipts.served_ids croisé aux atomes du trajet"},
    {"stage": "consolidated", "label": "Mémoire consolidée",
     "trace": "état d'aujourd'hui des atomes nés de ce trajet"},
)

_STAGE_RANK: dict[str, int] = {s["stage"]: i + 1 for i, s in enumerate(STAGES)}
_STAGE_LABEL: dict[str, str] = {s["stage"]: s["label"] for s in STAGES}


# ============================================================================
# LES GABARITS — le seul endroit de ce fichier où des mots sont écrits
# ============================================================================
#
# Le serveur ne les remplit JAMAIS. Il désigne une clé et fournit ses arguments ;
# le client compose. Ajouter une étape, c'est ajouter un gabarit ICI et une règle
# dans STEP_RULES — jamais une concaténation ailleurs.

CASCADE_TEMPLATES: dict[str, str] = {

    # --- 1. détectée --------------------------------------------------------
    "detected":
        "Conversation détectée le {detected_at} : {receipts} remise(s) d'ingestion, "
        "{received} message(s) présentés par le capteur {node}.",
    "detected_with_capture":
        "Conversation détectée le {detected_at} par la course de capture #{manifest} "
        "du nœud {node} ({files_scanned} fichier(s) balayé(s)).",
    "detected_unavailable":
        "Aucune remise d'ingestion ne porte cette conversation : "
        "je ne sais pas dire quand je l'ai vue pour la première fois.",

    # --- 2. absorbée --------------------------------------------------------
    "absorbed":
        "Absorbée : {messages} message(s) lus, du {first_at} au {last_at}, "
        "sur {total} que compte la conversation.",
    "absorbed_empty":
        "Aucun message neuf à absorber dans cette fenêtre : "
        "le curseur était déjà au bout de la conversation.",

    # --- 3. projets reconnus ------------------------------------------------
    "projects_recognised":
        "Projet(s) reconnu(s) : {projects} — {count} territoire(s) touché(s) "
        "par ce que j'ai retenu.",
    "projects_none":
        "Aucun des projets ne reconnaît ce qui a été retenu : "
        "le savoir produit tombe hors de leurs règles.",
    "projects_skipped":
        "Aucun atome produit : il n'y a rien à rattacher à un projet.",
    "projects_unavailable":
        "Le cycle {run} n'a pas abouti ({status}) : aucun projet ne peut être "
        "reconnu, faute d'analyse — et non faute de territoire.",

    # --- 4. scopes touchés --------------------------------------------------
    "scopes_touched":
        "{count} domaine(s) touché(s) : {scopes}.",
    "scopes_root_debt":
        "{count} domaine(s) touché(s) : {scopes} — dont {roots} posé(s) sur une "
        "racine nue, où le rappel ne les verra jamais.",
    "scopes_skipped":
        "Aucun atome produit : aucun domaine n'a bougé.",
    "scopes_unavailable":
        "Le cycle {run} n'a pas abouti ({status}) : je ne sais pas quels domaines "
        "ce passage aurait touchés.",

    # --- 5. analyse ---------------------------------------------------------
    "analysis_done":
        "Analysée par {model} en {duration_ms} lors du cycle {run} ({trigger}) ; "
        "arrêt : {stop_reason}.",
    # `analysis_done_silent` a été RETIRÉ : « le cycle n'a laissé aucun motif
    # d'arrêt » était tout ce que cette vue savait dire d'un trajet abouti, alors
    # que le verdict de ce trajet dormait en base. Le cas qu'elle couvrait (cycle
    # abouti, pas de stop_reason) est désormais dit par le verdict lui-même, ou
    # par `analysis_no_verdict` quand il manque. Un gabarit qu'aucune branche ne
    # peut plus émettre est du bois mort : on ne le garde pas au catalogue.
    # LE VERDICT DE CE TRAJET. Les trois clés qui suivent disent ce que le cerveau
    # a pensé de CETTE conversation-ci, pas de son paquet : c'est la question
    # centrale qu'on pose à un cerveau, et elle dormait en base (run_receipts.progress).
    "analysis_covered":
        "Analysée par {model} en {duration_ms} lors du cycle {run} ({trigger}) : "
        "le cerveau a lu ce trajet et l'a jugé COUVERT.",
    "analysis_no_new_knowledge":
        "Analysée par {model} en {duration_ms} lors du cycle {run} ({trigger}) : "
        "lue de bout en bout, et jugée sans savoir nouveau.",
    "analysis_omitted":
        "Présentée au cycle {run} ({trigger}) et OMISE : le cerveau ne l'a pas "
        "traitée dans ce passage.",
    "analysis_no_verdict":
        "Analysée par {model} en {duration_ms} lors du cycle {run} ({trigger}) ; "
        "ce cycle n'a consigné aucun verdict pour ce trajet : je ne sais pas s'il "
        "a été couvert.",
    "analysis_quarantined":
        "Le cycle {run} est parti en quarantaine après {duration_ms} : "
        "ce que ce trajet portait n'a pas été retenu.",
    "analysis_failed":
        "Le cycle {run} n'a pas abouti ({status}) après {duration_ms} : "
        "la conversation avait été présentée, elle n'a pas été digérée.",

    # --- 6. atomes créés ----------------------------------------------------
    "atoms_born":
        "{count} nouvel(s) atome(s) de savoir : {kinds}.",
    "atoms_none":
        "Aucun atome créé : ce passage n'a rien appris de neuf.",
    "atoms_unavailable":
        "Le cycle {run} n'a pas abouti ({status}) : je ne sais pas ce que ce "
        "passage aurait retenu.",

    # --- 7. atomes remplacés ------------------------------------------------
    "atoms_superseded":
        "{count} atome(s) existant(s) remplacé(s) par ce trajet : j'ai changé d'avis.",
    "atoms_no_supersede":
        "Aucun atome existant n'a été remplacé : ce trajet n'a fait qu'ajouter.",

    # --- 8. candidats écartés -----------------------------------------------
    "candidates_dropped":
        "{count} candidat(s) écarté(s) avant d'entrer en mémoire ({reasons}).",
    "candidates_kept_all":
        "Aucun candidat écarté : tout ce qui a été proposé est entré.",
    # Rien proposé ET rien retenu n'est PAS « tout a été retenu ». Affirmer un
    # succès là où le trajet n'a rien produit était le mensonge le plus séduisant
    # de cette vue : il touchait 765 cascades sur 912.
    "candidates_none_proposed":
        "Rien à écarter : ce trajet n'a proposé aucun savoir.",
    # « n'a proposé aucun savoir » tombait aussi sur les cycles en quarantaine —
    # où la proposition EXISTE, en base, en octets — et sur les spawn_failed, où
    # le modèle n'a jamais été appelé. Deux étapes de la même cascade se
    # contredisaient alors frontalement. Ces deux clés-ci disent l'absence de
    # TRACE, jamais l'absence de PROPOSITION.
    "candidates_quarantined":
        "Ce trajet a bien proposé du savoir : la sortie du cycle {run} est partie "
        "en quarantaine ({errors}) et n'est jamais entrée en mémoire.",
    "candidates_unavailable":
        "Le cycle {run} n'a pas abouti ({status}) : ce qu'il a proposé n'a pas été "
        "enregistré ({reason}).",

    # --- 9. liens (jamais mesuré) -------------------------------------------
    "links_unavailable":
        "Je ne sais pas dire quels liens ce trajet a créés : {reason}.",

    # --- 10. rappel ---------------------------------------------------------
    "recall_served":
        "Ce savoir a déjà servi : {receipts} rappel(s) l'ont ressorti, "
        "{atoms} atome(s) concerné(s), le dernier le {last_at}.",
    "recall_never":
        "Aucun rappel n'a encore ressorti ce savoir : il dort depuis sa naissance.",
    "recall_skipped":
        "Aucun atome produit : il n'y a rien qui puisse être rappelé.",
    "recall_unavailable":
        "Le cycle {run} n'a pas abouti ({status}) : rien n'est né de ce trajet, "
        "donc rien n'a pu être rappelé — et rien ne dit ce qui l'aurait été.",

    # --- 11. consolidée -----------------------------------------------------
    "consolidated":
        "Mémoire consolidée : {alive} atome(s) de ce trajet sont encore vivants "
        "aujourd'hui sur {born} nés ici.",
    "consolidated_empty":
        "Rien à consolider : ce trajet n'a laissé aucun atome derrière lui.",
    "consolidated_unavailable":
        "Le cycle {run} n'a pas abouti ({status}) : ce trajet n'a rien laissé, et "
        "je ne sais pas ce qu'il aurait laissé.",
    "consolidated_all_gone":
        "Plus rien ne survit de ce trajet : les {born} atome(s) nés ici ont tous "
        "été remplacés ou retirés.",
}

#: Ce que le client affiche pour une clé absente du dictionnaire. Il n'invente
#: jamais de texte de remplacement : il montre le trou.
UNKNOWN_TEMPLATE = "[étape inconnue : {key}]"

#: La règle d'émission de CHAQUE étape, SERVIE au client : il doit pouvoir lire
#: pourquoi telle étape porte tel gabarit, sans ouvrir ce fichier.
STEP_RULES: dict[str, str] = {
    "detected": "au moins un reçu d'ingestion porte ce conversation_uid, sans manifeste de capture rattachable",
    "detected_with_capture": "au moins un reçu d'ingestion ET une course de capture du même nœud/source dont la fenêtre contient le reçu",
    "detected_unavailable": "aucun reçu d'ingestion ne porte ce conversation_uid : la trace de détection n'existe pas",
    "absorbed": "au moins un message dans la fenêtre du paquet (cursor_from, max_id]",
    "absorbed_empty": "fenêtre du paquet vide : aucun message neuf n'a été présenté au cerveau",
    "projects_recognised": "au moins un projet dont la règle attrape un atome produit ; ordre : atomes du projet décroissant (du plus large au plus spécifique)",
    "projects_none": "des atomes ont été produits mais aucune règle de projet ne les attrape",
    "projects_skipped": "cycle abouti ET aucun atome produit : l'étape n'a légitimement pas eu lieu",
    "projects_unavailable": "run_receipts.status <> 'done' : l'étape n'a pas eu lieu parce que l'ANALYSE n'a pas eu lieu",
    "scopes_touched": "au moins un scope distinct parmi les atomes produits, aucun sur une racine nue",
    "scopes_root_debt": "au moins un scope touché est une racine nue (sans « / »)",
    "scopes_skipped": "cycle abouti ET aucun atome produit : l'étape n'a légitimement pas eu lieu",
    "scopes_unavailable": "run_receipts.status <> 'done' : aucun domaine mesurable, faute d'analyse",
    "analysis_done": "run_receipts.status = 'done', aucun verdict consigné pour ce trajet ET stop_reason renseigné",
    "analysis_covered": "run_receipts.progress[uid].coverage = 'covered' — le verdict de CE trajet, pas les compteurs du cycle",
    "analysis_no_new_knowledge": "run_receipts.progress[uid].coverage = 'no_new_knowledge'",
    "analysis_omitted": "run_receipts.progress[uid].coverage = 'omitted'",
    "analysis_no_verdict": "run_receipts.status = 'done' mais progress[uid].coverage absent : le verdict de ce trajet n'existe pas en base",
    "analysis_quarantined": "run_receipts.status = 'quarantined'",
    "analysis_failed": "run_receipts.status hors 'done' et 'quarantined' (spawn_failed, dispose_interrupted, empty…)",
    "atoms_born": "au moins un atome porte ce run_ref ET ce conversation_uid dans source_ref",
    "atoms_none": "cycle abouti ET aucun atome ne porte ce couple : le passage n'a rien retenu",
    "atoms_unavailable": "run_receipts.status <> 'done' : le passage n'a pas été digéré, ce qu'il aurait retenu n'est pas mesurable",
    "atoms_superseded": "au moins un atome dont superseded_by pointe vers un atome de ce trajet",
    "atoms_no_supersede": "des atomes sont nés mais aucun n'a remplacé d'incumbent",
    "candidates_dropped": "au moins une ligne de digestion_review_queue pour ce run_ref ET ce conversation_uid",
    "candidates_kept_all": "cycle abouti, aucune ligne de rejet, et au moins un atome né ou remplacé par ce trajet",
    "candidates_none_proposed": "cycle abouti, aucune ligne de rejet ET aucun atome né ni remplacé par ce trajet",
    "candidates_quarantined": "run_receipts.status = 'quarantined' ET ce conversation_uid figure dans quarantine_attributed_uids : la proposition est PROUVÉE, seule sa persistance a manqué",
    "candidates_unavailable": "run_receipts.status <> 'done' sans quarantaine attribuée à ce trajet : ce qui a été proposé n'a laissé aucune trace lisible",
    "links_unavailable": "TOUJOURS — cette étape ne lit pas arac.atom_links ; elle n'est jamais mesurée, donc jamais nulle. Sa raison est constatée en base à chaque appel",
    "recall_served": "au moins un context_receipts.served_ids contient un atome de ce trajet",
    "recall_never": "des atomes sont nés mais aucun reçu de rappel ne les a servis",
    "recall_skipped": "cycle abouti ET aucun atome produit : l'étape n'a légitimement pas eu lieu",
    "recall_unavailable": "run_receipts.status <> 'done' : rien n'est né, donc rien n'a pu être rappelé — l'absence vient de l'analyse",
    "consolidated": "au moins un atome de ce trajet est encore 'active' aujourd'hui",
    "consolidated_empty": "cycle abouti ET aucun atome n'est né de ce trajet",
    "consolidated_unavailable": "run_receipts.status <> 'done' : rien à consolider parce que rien n'a été digéré",
    "consolidated_all_gone": "des atomes sont nés mais aucun n'est encore 'active'",
}


# ============================================================================
# SOURCES — cinq familles, toutes résolvables sur une route réellement servie
# ============================================================================


def _href_conversation(uid: str) -> str:
    return f"{_PREFIX}/conversations/{quote(str(uid), safe='')}"


def _src_conversation(uid: str, title: Any = None) -> dict[str, Any]:
    return {"kind": "conversation", "ref": uid, "label": title or uid,
            "href": _href_conversation(uid)}


def _src_atom(atom: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "atom", "ref": atom.get("id"), "label": atom.get("key"),
            "href": f"{_PREFIX}/atoms/{atom.get('id')}"}


def _src_scope(scope: Any) -> dict[str, Any]:
    return {"kind": "scope", "ref": scope, "label": scope,
            "href": f"{_PREFIX}/scopes/{quote(str(scope), safe='/')}"}


def _src_project(project_id: Any, label: Any) -> dict[str, Any]:
    return {"kind": "project", "ref": project_id, "label": label,
            "href": f"{_PREFIX}/projects/{quote(str(project_id), safe='')}"}


def _src_run(run_ref: Any, started_at: Any, ended_at: Any) -> dict[str, Any]:
    """La source « cycle » : la CHRONOLOGIE bornée à la fenêtre du cycle.

    ``run_receipts`` n'a pas de route propre ; ``/cc/v1/timeline`` en est la
    fenêtre ouvrable : de la phrase on atteint tout ce que le cerveau a fait
    pendant ce cycle-là, borne à borne.
    """
    href = f"{_PREFIX}/timeline?granularity=hour"
    if started_at:
        href += f"&from={quote(str(started_at), safe='')}"
    if ended_at:
        href += f"&to={quote(str(ended_at), safe='')}"
    return {"kind": "run", "ref": run_ref, "label": run_ref, "href": href}


def _src_trace(ref: str, uid: str, sql: str, label: str) -> dict[str, Any]:
    """La source « trace » : une table sans route, mais un SQL rejouable.

    L'``href`` renvoie à la réponse qui PORTE la donnée (cette cascade même) ; le
    ``sql`` est la requête exacte qui l'a produite, sur une ligne, copiable dans
    ``psql``. On peut donc contredire le cockpit de deux façons : en rappelant la
    route, ou en rejouant la requête. Un cockpit qui ne peut pas être contredit
    ne mérite pas d'être cru.
    """
    return {"kind": "trace", "ref": ref, "label": label,
            "href": f"{_PREFIX}/cascade/{quote(str(uid), safe='')}",
            "sql": sql}


def _resolvable(source: Any) -> bool:
    """Une source vaut si elle mène quelque part ET dit de quoi elle parle."""
    if not isinstance(source, dict):
        return False
    href = str(source.get("href") or "").strip()
    if not href.startswith(f"{_PREFIX}/"):
        return False
    return bool(str(source.get("ref") or "").strip() or str(source.get("sql") or "").strip())


# ============================================================================
# L'ACCUMULATEUR D'ÉTAPES — le point d'application de la contrainte
# ============================================================================


class _Steps:
    """Les étapes d'une cascade. Refuse à la CONSTRUCTION ce qui n'est pas sourcé.

    C'est ici, et nulle part ailleurs, que « une étape sans source résolvable est
    refusée » devient vrai : une étape non sourcée ne peut pas entrer, donc ne
    peut pas sortir. Son refus est publié — pas avalé.
    """

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.refused: list[dict[str, str]] = []

    def add(self, stage: str, template_key: str, args: dict[str, Any],
            sources: list[dict[str, Any]], *,
            state: str = "passed",
            at: Any = None,
            duration_ms: Any = None,
            measures: dict[str, Any] | None = None,
            targets: list[dict[str, Any]] | None = None) -> None:
        clean = [s for s in sources if _resolvable(s)]
        if not clean:
            self.refused.append({"stage": stage, "template_key": template_key,
                                 "reason": "aucune source résolvable"})
            logger.warning("cc_v1.cascade_step_without_source",
                           extra={"stage": stage, "template": template_key})
            return
        self.items.append({
            "rank": _STAGE_RANK.get(stage, 99),
            "stage": stage,
            "stage_label": _STAGE_LABEL.get(stage, stage),
            "at": at,
            "duration_ms": duration_ms,
            "template_key": template_key,
            "rule": STEP_RULES.get(template_key, ""),
            "args": args,
            "measures": measures or {},
            "state": state,
            "targets": targets or [],
            "sources": clean,
        })

    def ordered(self) -> list[dict[str, Any]]:
        """Le trajet, dans l'ordre du pipeline — qui est l'ordre chronologique."""
        return sorted(self.items, key=lambda s: s["rank"])


# ============================================================================
# LES REQUÊTES — toute l'agrégation, toutes les durées, tous les totaux
# ============================================================================

#: L'ossature : les cascades achevées, une ligne par (cycle, conversation).
#:
#: ``pack`` est le manifeste écrit par le cerveau AVANT de travailler. Sa fenêtre
#: ``(cursor_from, max_id]`` borne EXACTEMENT les messages présentés — c'est
#: pourquoi ``messages_absorbes`` colle à ``n_msgs`` sans qu'on ait à le croire
#: sur parole. Aucun balayage de ``raw_messages`` sans ``conversation_id``.
_Q_HEAD = """
WITH runs AS (
    SELECT r.slot_key,
           r.trigger,
           r.model,
           r.status,
           r.stop_reason,
           r.skip_reason,
           r.progress,
           r.quarantine_errors,
           octet_length(r.quarantine_output)                        AS quarantaine_octets,
           r.started_at,
           r.ended_at,
           r.items,
           r.spawns,
           r.est_input_tokens,
           r.atoms_created,
           r.atoms_superseded,
           r.atoms_confirmed,
           r.atoms_quarantined,
           r.conflicts_409,
           r.coverage_presented,
           r.coverage_covered,
           r.coverage_no_new_knowledge,
           r.coverage_omitted,
           r.pack,
           r.quarantine_attributed_uids,
           (extract(epoch FROM (r.ended_at - r.started_at)) * 1000)::bigint AS cycle_duree_ms
      FROM arac.run_receipts r
     WHERE r.ended_at IS NOT NULL
       AND jsonb_typeof(r.pack) = 'array'
       AND (%(since)s::timestamptz IS NULL OR r.started_at >= %(since)s::timestamptz)
       AND (%(uid)s::text IS NULL
            OR r.pack @> jsonb_build_array(jsonb_build_object('uid', %(uid)s::text)))
     ORDER BY r.started_at DESC
     LIMIT %(run_scan)s
), presentees AS (
    SELECT r.*,
           e.value ->> 'uid'                                  AS uid,
           nullif(e.value ->> 'conversation_id', '')::uuid    AS conversation_id,
           nullif(e.value ->> 'n_msgs', '')::int              AS paquet_messages,
           nullif(e.value ->> 'cursor_from', '')::bigint      AS curseur_depuis,
           nullif(e.value ->> 'max_id', '')::bigint           AS curseur_jusqua,
           e.ordinality                                       AS rang_paquet,
           jsonb_exists(coalesce(r.quarantine_attributed_uids, '[]'::jsonb),
                        e.value ->> 'uid')                    AS quarantaine_attribuee,
           /* LE VERDICT DE CE TRAJET, et non celui du cycle. run_receipts.progress
              est un objet {uid: {coverage: covered|no_new_knowledge|omitted}} : 268
              verdicts posés en base, jamais servis. Sans cette colonne, l'étape
              « analysée » ne pouvait offrir que les compteurs du CYCLE, identiques
              octet pour octet pour deux conversations du même paquet dont les
              verdicts sont opposés. */
           (r.progress -> (e.value ->> 'uid') ->> 'coverage')  AS verdict_de_ce_trajet
      FROM runs r,
           LATERAL jsonb_array_elements(r.pack) WITH ORDINALITY e(value, ordinality)
     WHERE (%(uid)s::text IS NULL OR e.value ->> 'uid' = %(uid)s::text)
)
SELECT p.slot_key                                             AS run_ref,
       p.uid,
       p.slot_key || '::' || p.uid                            AS cascade_id,
       p.trigger,
       p.model,
       p.status,
       p.stop_reason,
       p.started_at                                           AS cycle_debut,
       p.ended_at                                             AS cycle_fin,
       p.cycle_duree_ms,
       p.items                                                AS cycle_items,
       p.spawns                                               AS cycle_spawns,
       p.est_input_tokens                                     AS cycle_jetons_estimes,
       p.atoms_created                                        AS cycle_atomes_nes,
       p.atoms_superseded                                     AS cycle_atomes_remplaces,
       p.atoms_confirmed                                      AS cycle_atomes_confirmes,
       p.atoms_quarantined                                    AS cycle_atomes_quarantaine,
       p.conflicts_409                                        AS cycle_conflits,
       p.coverage_presented                                   AS cycle_couverture_presentee,
       p.coverage_covered                                     AS cycle_couverture_couverte,
       p.coverage_no_new_knowledge                            AS cycle_couverture_sans_nouveaute,
       p.coverage_omitted                                     AS cycle_couverture_omise,
       p.quarantaine_attribuee,
       p.verdict_de_ce_trajet,
       p.skip_reason,
       p.quarantine_errors                                    AS quarantaine_erreurs,
       p.quarantaine_octets,
       p.rang_paquet,
       p.paquet_messages,
       p.curseur_depuis,
       p.curseur_jusqua,
       p.conversation_id,
       c.title                                                AS titre,
       c.source_type,
       c.node_id                                              AS conversation_noeud,
       c.created_at                                           AS conversation_creee_le,
       c.curated_at                                           AS conversation_curee_le,
       c.exclusion_reason                                     AS conversation_exclusion,
       m.messages_absorbes,
       m.premier_message_le,
       m.dernier_message_le,
       (extract(epoch FROM (m.dernier_message_le - m.premier_message_le))
            * 1000)::bigint                                   AS absorption_duree_ms,
       t.messages_total
  FROM presentees p
  LEFT JOIN arac.conversations c
    ON c.conversation_uid = p.uid
  LEFT JOIN LATERAL (
       SELECT count(*)                  AS messages_absorbes,
              min(rm.msg_created_at)    AS premier_message_le,
              max(rm.msg_created_at)    AS dernier_message_le
         FROM arac.raw_messages rm
        WHERE rm.conversation_id = c.id
          AND rm.id > coalesce(p.curseur_depuis, 0)
          AND rm.id <= p.curseur_jusqua) m ON true
  LEFT JOIN LATERAL (
       SELECT count(*) AS messages_total
         FROM arac.raw_messages rm2
        WHERE rm2.conversation_id = c.id) t ON true
 ORDER BY p.started_at DESC, p.rang_paquet ASC
"""
# La borne LIMIT a été retirée de cette requête : la dédup par conversation se
# fait en Python APRÈS lecture (cf. `cascades()`), sinon un seul cycle en
# quarantaine dont le paquet porte 13 conversations occupe 13 des 20 cartes et
# l'écran phare devient structurellement incapable de montrer un trajet réussi.
# Le volume reste borné par `run_scan` en amont — la requête ne balaie jamais
# tous les cycles. Aucun commentaire `--` ici : la preuve est servie sur UNE
# ligne, un commentaire SQL y masquerait tout ce qui suit.

#: LE CORPUS ENTIER, et la fenêtre de balayage réellement appliquée.
#:
#: CE QUI ÉTAIT FAUX : la réponse annonçait « 51 conversations ont une cascade
#: achevée » — le compte de ce qui tenait dans la fenêtre de balayage
#: (``run_scan`` = 28 cycles, soit six jours), présenté comme le compte du corpus.
#: La base en porte 141, pour 955 passages : 90 conversations étaient hors de
#: portée sans que rien ne le dise, ni la fenêtre, ni son plancher de date.
#:
#: CE QUE CETTE REQUÊTE GARANTIT : le vrai total est LU, une fois, sans balayage
#: (955 lignes, index sur ``started_at``), à côté des bornes exactes du balayage.
#: Le lecteur voit donc trois nombres distincts et nommés : ce que porte le
#: corpus, ce que la fenêtre a atteint, ce qui est servi.
_Q_CORPUS = """
WITH balayes AS (
    SELECT r.id, r.started_at
      FROM arac.run_receipts r
     WHERE r.ended_at IS NOT NULL
       AND jsonb_typeof(r.pack) = 'array'
       AND (%(since)s::timestamptz IS NULL OR r.started_at >= %(since)s::timestamptz)
       AND (%(uid)s::text IS NULL
            OR r.pack @> jsonb_build_array(jsonb_build_object('uid', %(uid)s::text)))
     ORDER BY r.started_at DESC
     LIMIT %(run_scan)s
), corpus AS (
    SELECT count(DISTINCT e.value ->> 'uid')  AS conversations,
           count(*)                           AS passages,
           count(DISTINCT r.id)               AS cycles
      FROM arac.run_receipts r,
           LATERAL jsonb_array_elements(r.pack) e
     WHERE r.ended_at IS NOT NULL
       AND jsonb_typeof(r.pack) = 'array'
)
SELECT c.conversations                          AS corpus_conversations,
       c.passages                               AS corpus_passages,
       c.cycles                                 AS corpus_cycles,
       (SELECT count(*)          FROM balayes)  AS cycles_balayes,
       (SELECT min(b.started_at) FROM balayes b) AS balayage_depuis,
       (SELECT max(b.started_at) FROM balayes b) AS balayage_jusqua
  FROM corpus c
"""

#: Étape 1 — la DÉTECTION, et la colonne vertébrale temporelle de la cascade.
#:
#: ``capture_manifests`` ne porte AUCUN ``conversation_uid`` : le manifeste est
#: retrouvé par recouvrement (même nœud, même source, fenêtre de course
#: contenant le reçu). C'est une reconstruction, elle est nommée comme telle
#: dans la réponse. ``least()`` ignore les NULL : une trace manquante ne fait pas
#: disparaître le début de la cascade, elle laisse l'autre parler.
#:
#: LA CASCADE COMMENCE QUAND LE CERVEAU VOIT, PAS QUAND L'HUMAIN PARLE. Faire
#: partir ``cascade_debut`` du plus vieux MESSAGE donnait des trajets de 36
#: jours pour des conversations importées d'un mois de discussions : on mesurait
#: l'âge du dialogue, pas le trajet dans le cerveau. La borne basse est donc la
#: première remise d'ingestion (à défaut, la création de la ligne conversation).
#: L'écart entre le premier message et cette remise reste servi à part
#: (``latence_de_capture_ms``) : c'est une mesure utile, pas une durée de trajet.
_Q_DETECTED = """
WITH paires (run_ref, uid, cycle_debut, cycle_fin, premier_message_le, conversation_creee_le) AS (
    VALUES {pairs}
), detection AS (
    SELECT ir.conversation_uid                                    AS uid,
           count(*)                                               AS remises,
           min(ir.created_at)                                     AS premiere_remise_le,
           max(ir.created_at)                                     AS derniere_remise_le,
           sum(ir.received)                                       AS messages_presentes,
           sum(ir.inserted)                                       AS messages_inseres,
           sum(ir.duplicates)                                     AS messages_doublons,
           count(DISTINCT ir.node_id)                             AS noeuds,
           (array_agg(ir.node_id ORDER BY ir.created_at))[1]      AS premier_noeud,
           (array_agg(ir.source_type ORDER BY ir.created_at))[1]  AS premiere_source,
           (array_agg(ir.outcome ORDER BY ir.created_at))[1]      AS premier_verdict
      FROM arac.ingest_receipts ir
     WHERE ir.conversation_uid = ANY(%(uids)s::text[])
     GROUP BY ir.conversation_uid
)
SELECT p.run_ref,
       p.uid,
       d.remises,
       d.premiere_remise_le,
       d.derniere_remise_le,
       d.messages_presentes,
       d.messages_inseres,
       d.messages_doublons,
       d.noeuds,
       d.premier_noeud,
       d.premiere_source,
       d.premier_verdict,
       cm.id                                                      AS manifeste_id,
       cm.run_started_at                                          AS manifeste_debut,
       cm.run_ended_at                                            AS manifeste_fin,
       cm.files_scanned                                           AS manifeste_fichiers,
       cm.sessions                                                AS manifeste_sessions,
       cm.messages_emitted                                        AS manifeste_messages_emis,
       cm.batches_failed                                          AS manifeste_lots_echoues,
       least(d.premiere_remise_le, p.conversation_creee_le)       AS cascade_debut,
       p.cycle_fin                                                AS cascade_fin,
       (extract(epoch FROM (p.cycle_fin - least(d.premiere_remise_le,
                                                p.conversation_creee_le))) * 1000)::bigint
                                                                  AS cascade_duree_ms,
       (extract(epoch FROM (p.cycle_debut - d.premiere_remise_le)) * 1000)::bigint
                                                                  AS attente_avant_analyse_ms,
       p.premier_message_le                                       AS conversation_premier_message_le,
       (extract(epoch FROM (d.premiere_remise_le - p.premier_message_le)) * 1000)::bigint
                                                                  AS latence_de_capture_ms
  FROM paires p
  LEFT JOIN detection d
    ON d.uid = p.uid
  LEFT JOIN LATERAL (
       SELECT cmm.id, cmm.run_started_at, cmm.run_ended_at, cmm.files_scanned,
              cmm.sessions, cmm.messages_emitted, cmm.batches_failed
         FROM arac.capture_manifests cmm
        WHERE cmm.node_id = d.premier_noeud
          AND cmm.source_type = d.premiere_source
          AND cmm.run_started_at <= d.premiere_remise_le
          AND coalesce(cmm.run_ended_at, cmm.run_started_at) >= d.premiere_remise_le
        ORDER BY cmm.run_started_at DESC
        LIMIT 1) cm ON true
"""

#: Étape 6 — les atomes NÉS de ce trajet. ``row_number()`` borne à 40 PAR cascade
#: (et non globalement) : une cascade prolifique ne doit pas affamer la suivante.
_Q_ATOMS = """
WITH paires (run_ref, uid) AS (
    VALUES {pairs}
), nes AS (
    SELECT p.run_ref,
           p.uid,
           a.id,
           a.kind,
           a.scope,
           a.key,
           a.status,
           a.version,
           a.confidence_score,
           a.tags,
           a.created_at,
           a.updated_at,
           a.superseded_by,
           left(a.value, 240)                                  AS extrait,
           (a.scope NOT LIKE %(slash)s)                        AS sur_racine_nue,
           (a.updated_at > a.created_at + interval '1 second') AS retouche_sur_place,
           row_number() OVER (PARTITION BY p.run_ref, p.uid
                              ORDER BY a.created_at ASC, a.id ASC) AS rang
      FROM paires p
      JOIN arac.memory_atoms a
        ON a.source_ref ->> 'run_ref' = p.run_ref
       AND a.source_ref ->> 'conversation_uid' = p.uid
     WHERE a.kind <> 'agent_message'
)
SELECT * FROM nes WHERE rang <= %(per_cascade)s ORDER BY run_ref, uid, rang
"""

#: LES TOTAUX — les comptes VRAIS, hors de toute troncature d'affichage.
#:
#: C'est la requête qui empêche la cascade de mentir. Les listes servies aux
#: étapes 6, 7, 8 et 4 sont BORNÉES (40 atomes, 20 remplacements, 20 rejets,
#: 12 scopes) ; compter ces lignes-là en Python aurait annoncé « 40 atomes »
#: pour une cascade qui en a produit 63, « 20 rejets » pour 47, et aurait
#: dédupliqué les genres et les motifs sur un échantillon au lieu du tout.
#: Chaque compte, chaque distinct, chaque min/max vient donc d'ici — et les
#: étapes n'utilisent la longueur d'une liste que pour dire ce qu'elles
#: MONTRENT, jamais ce qui EXISTE.
#:
#: Le zéro rendu par ces ``count()`` est un zéro MESURÉ : les quatre tables
#: interrogées existent et ont été lues. Il n'a rien à voir avec l'absence de
#: ``atom_links``, qui n'est pas mesurable et ne rend jamais de chiffre.
_Q_TOTALS = """
WITH paires (run_ref, uid) AS (
    VALUES {pairs}
), nes AS (
    SELECT p.run_ref, p.uid, a.id, a.kind, a.scope, a.status,
           a.superseded_by, a.created_at
      FROM paires p
      JOIN arac.memory_atoms a
        ON a.source_ref ->> 'run_ref' = p.run_ref
       AND a.source_ref ->> 'conversation_uid' = p.uid
     WHERE a.kind <> 'agent_message'
), agg_nes AS (
    SELECT n.run_ref,
           n.uid,
           count(*)                                             AS atomes_nes,
           count(*) FILTER (WHERE n.status = 'active')           AS atomes_vivants,
           count(*) FILTER (WHERE n.superseded_by IS NOT NULL)   AS atomes_deja_remplaces,
           count(*) FILTER (WHERE n.scope NOT LIKE %(slash)s)    AS atomes_sur_racine_nue,
           count(DISTINCT n.scope)                               AS scopes_touches,
           count(DISTINCT n.kind)                                AS genres_touches,
           array_agg(DISTINCT n.kind)                            AS genres,
           min(n.created_at)                                     AS premier_atome_le,
           max(n.created_at)                                     AS dernier_atome_le,
           (extract(epoch FROM (max(n.created_at) - min(n.created_at))) * 1000)::bigint
                                                                 AS ecriture_duree_ms
      FROM nes n
     GROUP BY n.run_ref, n.uid
), agg_remplaces AS (
    SELECT n.run_ref,
           n.uid,
           count(*)                                              AS atomes_remplaces,
           min((extract(epoch FROM (n.created_at - ancien.created_at)) / 86400)::int)
                                                                 AS survie_jours_min,
           max((extract(epoch FROM (n.created_at - ancien.created_at)) / 86400)::int)
                                                                 AS survie_jours_max
      FROM nes n
      JOIN arac.memory_atoms ancien ON ancien.superseded_by = n.id
     GROUP BY n.run_ref, n.uid
), agg_ecartes AS (
    SELECT p.run_ref,
           p.uid,
           count(*)                                              AS candidats_ecartes,
           array_agg(DISTINCT q.drop_reason)                     AS motifs_ecart
      FROM paires p
      JOIN arac.digestion_review_queue q
        ON q.run_ref = p.run_ref
       AND q.conversation_uid = p.uid
     GROUP BY p.run_ref, p.uid
)
SELECT p.run_ref,
       p.uid,
       coalesce(a.atomes_nes, 0)              AS atomes_nes,
       coalesce(a.atomes_vivants, 0)          AS atomes_vivants,
       coalesce(a.atomes_deja_remplaces, 0)   AS atomes_deja_remplaces,
       coalesce(a.atomes_sur_racine_nue, 0)   AS atomes_sur_racine_nue,
       coalesce(a.scopes_touches, 0)          AS scopes_touches,
       coalesce(a.genres_touches, 0)          AS genres_touches,
       coalesce(a.genres, ARRAY[]::text[])    AS genres,
       a.premier_atome_le,
       a.dernier_atome_le,
       a.ecriture_duree_ms,
       coalesce(r.atomes_remplaces, 0)        AS atomes_remplaces,
       r.survie_jours_min,
       r.survie_jours_max,
       coalesce(e.candidats_ecartes, 0)       AS candidats_ecartes,
       coalesce(e.motifs_ecart, ARRAY[]::text[]) AS motifs_ecart
  FROM paires p
  LEFT JOIN agg_nes        a ON a.run_ref = p.run_ref AND a.uid = p.uid
  LEFT JOIN agg_remplaces  r ON r.run_ref = p.run_ref AND r.uid = p.uid
  LEFT JOIN agg_ecartes    e ON e.run_ref = p.run_ref AND e.uid = p.uid
"""

#: Étape 4 — les scopes distincts touchés, comptés en SQL, bornés par cascade.
_Q_SCOPES = """
WITH paires (run_ref, uid) AS (
    VALUES {pairs}
), touches AS (
    SELECT p.run_ref,
           p.uid,
           a.scope,
           count(*)                                       AS atomes,
           (a.scope NOT LIKE %(slash)s)                   AS racine_nue,
           count(*) OVER (PARTITION BY p.run_ref, p.uid)  AS scopes_total,
           count(*) FILTER (WHERE (a.scope NOT LIKE %(slash)s))
                    OVER (PARTITION BY p.run_ref, p.uid)  AS racines_total,
           row_number() OVER (PARTITION BY p.run_ref, p.uid
                              ORDER BY count(*) DESC, a.scope ASC) AS rang
      FROM paires p
      JOIN arac.memory_atoms a
        ON a.source_ref ->> 'run_ref' = p.run_ref
       AND a.source_ref ->> 'conversation_uid' = p.uid
     WHERE a.kind <> 'agent_message'
     GROUP BY p.run_ref, p.uid, a.scope
)
SELECT * FROM touches WHERE rang <= %(per_cascade)s ORDER BY run_ref, uid, rang
"""

#: Étape 7 — les atomes REMPLACÉS. ``supersedes`` est NULL sur la totalité de la
#: base (anomalie constatée et documentée dans ``lifestory``) : seule l'arête
#: ``superseded_by`` porte l'information, et c'est elle qu'on remonte.
_Q_SUPERSEDED = """
WITH paires (run_ref, uid) AS (
    VALUES {pairs}
), remplaces AS (
    SELECT p.run_ref,
           p.uid,
           ancien.id                                       AS ancien_id,
           ancien.kind,
           ancien.scope,
           ancien.key,
           ancien.version                                  AS ancienne_version,
           ancien.confidence_score                         AS ancienne_confiance,
           ancien.created_at                               AS ancien_ne_le,
           neuf.id                                         AS nouvel_id,
           neuf.key                                        AS nouvelle_key,
           neuf.confidence_score                           AS nouvelle_confiance,
           neuf.created_at                                 AS remplace_le,
           (extract(epoch FROM (neuf.created_at - ancien.created_at)) / 86400)::int
                                                           AS survie_jours,
           row_number() OVER (PARTITION BY p.run_ref, p.uid
                              ORDER BY neuf.created_at ASC) AS rang
      FROM paires p
      JOIN arac.memory_atoms neuf
        ON neuf.source_ref ->> 'run_ref' = p.run_ref
       AND neuf.source_ref ->> 'conversation_uid' = p.uid
      JOIN arac.memory_atoms ancien
        ON ancien.superseded_by = neuf.id
     WHERE neuf.kind <> 'agent_message'
)
SELECT * FROM remplaces WHERE rang <= %(per_cascade)s ORDER BY run_ref, uid, rang
"""

#: Étape 8 — les candidats ÉCARTÉS avant d'entrer en mémoire.
_Q_DROPPED = """
WITH paires (run_ref, uid) AS (
    VALUES {pairs}
), ecartes AS (
    SELECT p.run_ref,
           p.uid,
           q.id,
           q.drop_reason                                   AS motif,
           q.scope,
           q.kind,
           q.status                                        AS statut_revue,
           q.incumbent_atom_id                             AS atome_en_place,
           q.proposed_atom ->> 'key'                       AS clef_proposee,
           q.created_at,
           row_number() OVER (PARTITION BY p.run_ref, p.uid
                              ORDER BY q.created_at ASC, q.id ASC) AS rang
      FROM paires p
      JOIN arac.digestion_review_queue q
        ON q.run_ref = p.run_ref
       AND q.conversation_uid = p.uid
)
SELECT * FROM ecartes WHERE rang <= %(per_cascade)s ORDER BY run_ref, uid, rang
"""

#: Étape 10 — le RAPPEL. Un seul balayage de ``context_receipts`` : les
#: ``served_ids`` sont dépliés une fois et joints aux atomes du trajet, plutôt
#: qu'un ``&&`` par cascade qui rebalaierait la table vingt fois.
_Q_RECALL = """
WITH paires (run_ref, uid) AS (
    VALUES {pairs}
), nes AS (
    SELECT p.run_ref, p.uid, a.id
      FROM paires p
      JOIN arac.memory_atoms a
        ON a.source_ref ->> 'run_ref' = p.run_ref
       AND a.source_ref ->> 'conversation_uid' = p.uid
     WHERE a.kind <> 'agent_message'
), servis AS (
    SELECT cr.id AS receipt_id, cr.created_at, cr.consumer, cr.final_band, s.atome
      FROM arac.context_receipts cr,
           LATERAL unnest(cr.served_ids) s(atome)
)
SELECT n.run_ref,
       n.uid,
       count(DISTINCT s.receipt_id)                        AS rappels,
       count(DISTINCT n.id)                                AS atomes_rappeles,
       count(DISTINCT s.consumer)                          AS consommateurs,
       min(s.created_at)                                   AS premier_rappel_le,
       max(s.created_at)                                   AS dernier_rappel_le,
       count(DISTINCT s.receipt_id) FILTER (WHERE s.final_band = 'high') AS rappels_bande_haute,
       array_agg(DISTINCT n.id::text)                      AS atomes_rappeles_ids
  FROM nes n
  JOIN servis s ON s.atome = n.id
 GROUP BY n.run_ref, n.uid
"""

#: Étape 11 — la CONSOLIDATION : ce qui, de ce trajet, est encore vivant
#: AUJOURD'HUI. Distinct de ``_Q_TOTALS`` par l'intention : celui-ci mesure
#: la naissance, celui-là la survie, et l'âge du savoir se lit dans l'écart.
_Q_CONSOLIDATED = """
WITH paires (run_ref, uid) AS (
    VALUES {pairs}
)
SELECT p.run_ref,
       p.uid,
       count(a.id)                                                  AS nes,
       count(a.id) FILTER (WHERE a.status = 'active')               AS vivants,
       count(a.id) FILTER (WHERE a.status <> 'active')              AS retires,
       count(a.id) FILTER (WHERE a.superseded_by IS NOT NULL)       AS remplaces_depuis,
       count(a.id) FILTER (WHERE a.updated_at > a.created_at
                             + interval '1 second')                 AS retouches_depuis,
       count(a.id) FILTER (WHERE a.embedding IS NOT NULL)           AS indexables,
       avg(a.confidence_score) FILTER (WHERE a.status = 'active')   AS confiance_moyenne,
       (extract(epoch FROM (now() - max(a.created_at))) / 86400)::int AS age_jours
  FROM paires p
  LEFT JOIN arac.memory_atoms a
    ON a.source_ref ->> 'run_ref' = p.run_ref
   AND a.source_ref ->> 'conversation_uid' = p.uid
   AND a.kind <> 'agent_message'
 GROUP BY p.run_ref, p.uid
"""


def _projects_sql() -> tuple[str, dict[str, Any]]:
    """Étape 3 — les projets reconnus, une branche par projet, tout en SQL.

    Deux comptes par branche, et ils ne disent PAS la même chose :
      - ``atomes_du_trajet`` : ce que CE passage a apporté au projet ;
      - ``atomes_du_projet``  : ce que le projet pèse en tout, aujourd'hui.

    L'ordre servi est ``atomes_du_projet`` décroissant : « du plus large au plus
    spécifique », comme se lit toute arborescence de projets. Trier sur l'apport
    du trajet aurait donné un ordre qui change à chaque cascade — donc une branche
    qu'on ne peut pas apprendre à lire.

    Cet ordre ne connaît AUCUN nom de projet : le ``ORDER BY`` ci-dessous ne cite
    que ``atomes_du_projet``, ``atomes_du_trajet`` puis ``label`` comme dernier
    départage alphabétique. Vos projets se classent donc par ce qu'ils pèsent,
    quels qu'ils s'appellent — aucune hiérarchie n'est câblée ici.
    """
    blocks: list[str] = []
    params: dict[str, Any] = {}
    for p in PROJECTS:
        trajet_sql, trajet_params = _project_predicate(p, "c", f"t_{p['id']}")
        total_sql, total_params = _project_predicate(p, "a", f"g_{p['id']}")
        params |= trajet_params | total_params
        params[f"pid_{p['id']}"] = p["id"]
        params[f"plab_{p['id']}"] = p["label"]
        blocks.append(f"""
    SELECT c.run_ref,
           c.uid,
           %(pid_{p['id']})s::text  AS project_id,
           %(plab_{p['id']})s::text AS label,
           count(*)                 AS atomes_du_trajet,
           (SELECT count(*)
              FROM arac.memory_atoms a
             WHERE a.kind <> 'agent_message'
               AND a.status = 'active'
               AND {total_sql}) AS atomes_du_projet
      FROM cascade_atomes c
     WHERE {trajet_sql}
     GROUP BY c.run_ref, c.uid""")

    sql = """
WITH paires (run_ref, uid) AS (
    VALUES {pairs}
), cascade_atomes AS (
    SELECT p.run_ref, p.uid, a.id, a.scope, a.key, a.tags
      FROM paires p
      JOIN arac.memory_atoms a
        ON a.source_ref ->> 'run_ref' = p.run_ref
       AND a.source_ref ->> 'conversation_uid' = p.uid
     WHERE a.kind <> 'agent_message'
), reconnus AS (
""" + union_ou_vide(
        blocks,
        # Les six colonnes que `SELECT r.*` sert et que le `ORDER BY` ci-dessous
        # nomme : sans elles, un cerveau SANS projet déclaré ferait échouer la
        # cascade entière — l'étape 3 doit pouvoir dire « aucun projet », pas
        # emporter les onze autres.
        (("run_ref", "text"), ("uid", "text"), ("project_id", "text"),
         ("label", "text"), ("atomes_du_trajet", "bigint"),
         ("atomes_du_projet", "bigint")),
        separateur="\nUNION ALL",
    ) + """
)
SELECT r.*,
       count(*) OVER (PARTITION BY r.run_ref, r.uid) AS projets_total
  FROM reconnus r
 ORDER BY r.run_ref, r.uid, r.atomes_du_projet DESC, r.atomes_du_trajet DESC, r.label ASC
"""
    return sql, params


# ============================================================================
# EXÉCUTION — bornes, budget de lignes, et le SQL rendu au client
# ============================================================================


def _pairs_values(heads: list[dict[str, Any]], *,
                  spine: bool = False) -> tuple[str, dict[str, Any]]:
    """La liste ``VALUES`` des couples (cycle, conversation), en PARAMÈTRES.

    Rien de la base ni de l'appelant n'entre dans le corps du SQL : seuls des
    marqueurs ``%(nom)s`` numérotés. ``spine=True`` ajoute les quatre bornes
    temporelles dont la requête de détection a besoin pour calculer, EN SQL, le
    début et la durée de la cascade.
    """
    rows: list[str] = []
    params: dict[str, Any] = {}
    for i, h in enumerate(heads):
        params[f"rr{i}"] = h["run_ref"]
        params[f"cu{i}"] = h["uid"]
        if not spine:
            rows.append(f"(%(rr{i})s::text, %(cu{i})s::text)")
            continue
        params[f"cd{i}"] = h.get("cycle_debut")
        params[f"cf{i}"] = h.get("cycle_fin")
        params[f"pm{i}"] = h.get("premier_message_le")
        params[f"cc{i}"] = h.get("conversation_creee_le")
        rows.append(
            f"(%(rr{i})s::text, %(cu{i})s::text, %(cd{i})s::timestamptz, "
            f"%(cf{i})s::timestamptz, %(pm{i})s::timestamptz, %(cc{i})s::timestamptz)"
        )
    return ",\n    ".join(rows), params


def _index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Regroupe des lignes par couple (run_ref, uid). Aucun calcul."""
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault((r.get("run_ref"), r.get("uid")), []).append(r)
    return out


def _first(index: dict[tuple[str, str], list[dict[str, Any]]],
           key: tuple[str, str]) -> dict[str, Any]:
    rows = index.get(key) or []
    return rows[0] if rows else {}


def _since(value: Any) -> datetime | None:
    """Valide la borne basse. Une valeur illisible n'échoue pas : elle s'efface,
    et le fait est signalé dans ``notices`` — le cockpit ne se tait jamais."""
    raw = _clean(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _bounded(value: Any, default: int = DEFAULT_CASCADES) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(n, MAX_CASCADES))


# ============================================================================
# LA CONSTRUCTION D'UNE CASCADE — onze étapes, aucune phrase
# ============================================================================


def _step_detected(steps: _Steps, head: dict[str, Any], det: dict[str, Any],
                   sql: str) -> None:
    uid, title = head["uid"], head.get("titre")
    remises = det.get("remises")
    trace = _src_trace("ingest_receipts", uid, sql, "les remises d'ingestion de cette conversation")

    if not remises:
        steps.add("detected", "detected_unavailable", {},
                  [_src_conversation(uid, title), trace],
                  state="unavailable",
                  measures={"remises": None},
                  targets=[_src_conversation(uid, title)])
        return

    manifeste = det.get("manifeste_id")
    measures = {
        "remises": remises,
        "messages_presentes": det.get("messages_presentes"),
        "messages_inseres": det.get("messages_inseres"),
        "messages_doublons": det.get("messages_doublons"),
        "noeuds": det.get("noeuds"),
        "premier_verdict": det.get("premier_verdict"),
        "attente_avant_analyse_ms": det.get("attente_avant_analyse_ms"),
        "latence_de_capture_ms": det.get("latence_de_capture_ms"),
        "manifeste_id": manifeste,
        "manifeste_fichiers": det.get("manifeste_fichiers"),
        "manifeste_messages_emis": det.get("manifeste_messages_emis"),
        "manifeste_lots_echoues": det.get("manifeste_lots_echoues"),
        "provenance_manifeste": (
            "reconstruit par recouvrement temporel (nœud + source + fenêtre de course) — "
            "arac.capture_manifests ne porte pas de conversation_uid"
            if manifeste else
            "aucune course de capture ne recouvre la première remise"),
    }
    if manifeste:
        steps.add("detected", "detected_with_capture",
                  {"detected_at": det.get("premiere_remise_le"),
                   "manifest": manifeste,
                   "node": det.get("premier_noeud"),
                   "files_scanned": det.get("manifeste_fichiers")},
                  [_src_conversation(uid, title), trace],
                  at=det.get("premiere_remise_le"), measures=measures,
                  targets=[_src_conversation(uid, title)])
    else:
        steps.add("detected", "detected",
                  {"detected_at": det.get("premiere_remise_le"),
                   "receipts": remises,
                   "received": det.get("messages_presentes"),
                   "node": det.get("premier_noeud")},
                  [_src_conversation(uid, title), trace],
                  at=det.get("premiere_remise_le"), measures=measures,
                  targets=[_src_conversation(uid, title)])


def _cycle_abouti(head: dict[str, Any]) -> bool:
    """Le cycle qui portait ce trajet a-t-il vraiment travaillé jusqu'au bout ?

    Six étapes en aval (projets, scopes, atomes, candidats, rappel, consolidation)
    lisaient un compte à zéro et en concluaient « il n'y avait rien à faire ». Sur
    un cycle en quarantaine ou en échec de lancement, ce zéro ne dit rien de ce que
    le trajet portait : il dit seulement que l'ANALYSE n'a pas eu lieu. La question
    se pose donc une fois, ici, et les six étapes s'y réfèrent.
    """
    return head.get("status") == "done"


def _absence_du_cycle(head: dict[str, Any]) -> dict[str, Any]:
    """La raison, le geste et le substitut d'une étape vide FAUTE D'ANALYSE.

    Règle I2 du mandat : une donnée absente n'est jamais un zéro. Elle porte sa
    raison, le geste qui la débloquerait, et le substitut qu'on peut lire à la
    place. Le substitut est ici une VRAIE ligne de base — les octets mis de côté
    par la quarantaine, ou le motif d'arrêt du lancement — jamais une paraphrase.
    """
    statut = head.get("status")
    run = head.get("run_ref")
    if statut == "quarantined":
        octets = head.get("quarantaine_octets")
        erreurs = head.get("quarantaine_erreurs")
        return {
            "state": "unavailable",
            "reason": ("le cycle est parti en quarantaine : sa sortie n'a pas pu être "
                       "reprise, donc rien n'a été écrit en mémoire"),
            "gesture": (f"rejouer la sortie mise de côté : SELECT quarantine_output, "
                        f"quarantine_errors FROM arac.run_receipts "
                        f"WHERE slot_key = '{run}'"),
            "substitute": (f"{octets} octet(s) de sortie conservés en quarantaine"
                           if octets else
                           "aucune sortie n'a été conservée pour ce cycle"),
            "quarantaine_octets": octets,
            "quarantaine_erreurs": erreurs,
            "quarantaine_attribuee_a_ce_trajet": head.get("quarantaine_attribuee"),
        }
    if statut == "spawn_failed":
        return {
            "state": "unavailable",
            "reason": (f"le cycle n'a jamais été lancé ({head.get('stop_reason')}) : "
                       "le modèle n'a pas vu cette conversation"),
            "gesture": "relancer un cycle sur cette conversation quand le quota le permet",
            "substitute": f"motif d'arrêt du lancement : {head.get('stop_reason')}",
            "stop_reason": head.get("stop_reason"),
        }
    if statut == "skipped":
        return {
            "state": "unavailable",
            "reason": f"le cycle a été sauté ({head.get('skip_reason')}) : il n'a rien traité",
            "gesture": "relancer un cycle sur cette conversation",
            "substitute": f"motif du saut : {head.get('skip_reason')}",
            "skip_reason": head.get("skip_reason"),
        }
    return {
        "state": "unavailable",
        "reason": (f"le cycle s'est terminé sur l'état {statut} : ce trajet n'a pas "
                   "été digéré"),
        "gesture": "consulter arac.run_receipts pour ce slot_key",
        "substitute": f"motif d'arrêt : {head.get('stop_reason')}",
        "stop_reason": head.get("stop_reason"),
    }


def _step_absorbed(steps: _Steps, head: dict[str, Any], sql: str) -> None:
    uid, title = head["uid"], head.get("titre")
    absorbes = head.get("messages_absorbes")
    sources = [_src_conversation(uid, title),
               _src_trace("raw_messages", uid, sql,
                          "la fenêtre exacte du paquet, (cursor_from, max_id]")]
    measures = {
        "messages_absorbes": absorbes,
        "messages_annonces_par_le_paquet": head.get("paquet_messages"),
        "messages_total_conversation": head.get("messages_total"),
        "curseur_depuis": head.get("curseur_depuis"),
        "curseur_jusqua": head.get("curseur_jusqua"),
    }
    if not absorbes:
        steps.add("absorbed", "absorbed_empty", {}, sources,
                  state="skipped", measures=measures,
                  targets=[_src_conversation(uid, title)])
        return
    steps.add("absorbed", "absorbed",
              {"messages": absorbes,
               "first_at": head.get("premier_message_le"),
               "last_at": head.get("dernier_message_le"),
               "total": head.get("messages_total")},
              sources,
              at=head.get("premier_message_le"),
              duration_ms=head.get("absorption_duree_ms"),
              measures=measures,
              targets=[_src_conversation(uid, title)])


def _step_projects(steps: _Steps, head: dict[str, Any], projects: list[dict[str, Any]],
                   atoms: list[dict[str, Any]], sql: str) -> None:
    uid, title = head["uid"], head.get("titre")
    trace = _src_trace("projects_rule", uid, sql,
                       "la règle des projets appliquée aux atomes de ce trajet")
    if not atoms:
        if not _cycle_abouti(head):
            absence = _absence_du_cycle(head)
            steps.add("projects", "projects_unavailable",
                      {"run": head.get("run_ref"), "status": head.get("status")},
                      [_src_conversation(uid, title), trace],
                      state="unavailable",
                      measures={"projets": None} | absence, targets=[])
            return
        steps.add("projects", "projects_skipped", {},
                  [_src_conversation(uid, title), trace],
                  state="skipped", measures={"projets": 0},
                  targets=[])
        return
    if not projects:
        steps.add("projects", "projects_none", {},
                  [_src_conversation(uid, title), trace],
                  state="skipped",
                  measures={"projets": 0,
                            "scopes_hors_regle": sorted({a.get("scope") for a in atoms})},
                  targets=[])
        return
    by_id = {p["id"]: p for p in PROJECTS}
    targets = [_src_project(p.get("project_id"), p.get("label")) | {
        "atomes_du_trajet": p.get("atomes_du_trajet"),
        "atomes_du_projet": p.get("atomes_du_projet"),
        "rule": _project_rule(by_id[p["project_id"]]) if p.get("project_id") in by_id else None,
    } for p in projects]
    total = projects[0].get("projets_total")
    steps.add("projects", "projects_recognised",
              {"projects": " → ".join(str(p.get("label")) for p in projects),
               "count": total},
              [_src_conversation(uid, title), trace]
              + [_src_project(p.get("project_id"), p.get("label")) for p in projects],
              measures={"projets": total,
                        "ordre": ("atomes_du_projet décroissant — du plus large au plus "
                                  "spécifique ; la règle de chaque projet est servie "
                                  "dans sa cible"),
                        "recouvrement": ("un atome peut appartenir à plusieurs projets ; "
                                         "le recouvrement est voulu et jamais résolu")},
              targets=targets)


def _step_scopes(steps: _Steps, head: dict[str, Any], scopes: list[dict[str, Any]],
                 sql: str) -> None:
    uid, title = head["uid"], head.get("titre")
    trace = _src_trace("scopes_touched", uid, sql, "les scopes distincts des atomes produits")
    if not scopes:
        if not _cycle_abouti(head):
            absence = _absence_du_cycle(head)
            steps.add("scopes", "scopes_unavailable",
                      {"run": head.get("run_ref"), "status": head.get("status")},
                      [_src_conversation(uid, title), trace],
                      state="unavailable",
                      measures={"scopes": None} | absence, targets=[])
            return
        steps.add("scopes", "scopes_skipped", {},
                  [_src_conversation(uid, title), trace],
                  state="skipped", measures={"scopes": 0}, targets=[])
        return
    total = scopes[0].get("scopes_total")
    racines_total = scopes[0].get("racines_total")
    targets = [_src_scope(s.get("scope")) | {"atomes": s.get("atomes"),
                                             "racine_nue": s.get("racine_nue")}
               for s in scopes]
    args = {"count": total,
            "scopes": ", ".join(str(s.get("scope")) for s in scopes)}
    key = "scopes_touched"
    if racines_total:
        key = "scopes_root_debt"
        args["roots"] = racines_total
    steps.add("scopes", key, args,
              [_src_conversation(uid, title), trace]
              + [_src_scope(s.get("scope")) for s in scopes],
              measures={"scopes": total, "racines_nues": racines_total,
                        "detail_servi": len(scopes),
                        "detail_tronque": bool(total and total > len(scopes))},
              targets=targets)


def _step_analysis(steps: _Steps, head: dict[str, Any], sql: str) -> None:
    uid = head["uid"]
    status = head.get("status")
    run_ref = head.get("run_ref")
    src_run = _src_run(run_ref, head.get("cycle_debut"), head.get("cycle_fin"))
    sources = [src_run, _src_trace("run_receipts", uid, sql, "le reçu du cycle qui a traité ce trajet")]
    # LE VERDICT DE CE TRAJET, ENFIN SERVI.
    #
    # CE QUI ÉTAIT FAUX : ce bloc ne servait que les quatre compteurs de couverture
    # du CYCLE ENTIER — identiques octet pour octet pour toutes les conversations
    # d'un même paquet, y compris pour deux dont les verdicts sont OPPOSÉS : dans
    # un même cycle circadien, une conversation jugée `no_new_knowledge` et une
    # autre jugée `covered` recevaient les mêmes mesures à l'écran. Le maillon
    # « Compréhension », qui est la question centrale qu'on pose à un cerveau,
    # était le seul de la chaîne dont la preuve existait en base
    # (`run_receipts.progress`) et n'était pas rendue.
    #
    # CE QUE CETTE VERSION GARANTIT : `verdict_de_ce_trajet` porte le jugement de
    # CETTE conversation ; les compteurs du cycle sont renommés `cycle_couverture_*`
    # pour qu'aucun lecteur ne les prenne pour lui ; et l'absence de verdict se dit
    # `analysis_no_verdict` avec sa raison, son geste et son substitut — jamais
    # comme un verdict neutre.
    verdict = head.get("verdict_de_ce_trajet")
    measures = {
        "modele": head.get("model"),
        "declencheur": head.get("trigger"),
        "statut": status,
        "stop_reason": head.get("stop_reason"),
        "items_du_cycle": head.get("cycle_items"),
        "jetons_estimes_du_cycle": head.get("cycle_jetons_estimes"),
        "verdict_de_ce_trajet": verdict,
        "cycle_couverture_presentee": head.get("cycle_couverture_presentee"),
        "cycle_couverture_couverte": head.get("cycle_couverture_couverte"),
        "cycle_couverture_sans_nouveaute": head.get("cycle_couverture_sans_nouveaute"),
        "cycle_couverture_omise": head.get("cycle_couverture_omise"),
        "portee_des_compteurs_de_couverture": (
            "ces quatre compteurs décrivent le CYCLE entier, pas ce trajet ; "
            "le jugement de ce trajet est `verdict_de_ce_trajet`"),
        "quarantaine_attribuee_a_ce_trajet": head.get("quarantaine_attribuee"),
        "rang_dans_le_paquet": head.get("rang_paquet"),
    }
    targets = [src_run | {"kind": "run"}]
    if status == "done":
        args = {"model": head.get("model"), "duration_ms": head.get("cycle_duree_ms"),
                "run": run_ref, "trigger": head.get("trigger")}
        verdicts = {"covered": "analysis_covered",
                    "no_new_knowledge": "analysis_no_new_knowledge",
                    "omitted": "analysis_omitted"}
        if verdict in verdicts:
            key = verdicts[verdict]
        elif head.get("stop_reason"):
            # Pas de verdict, mais le cycle a dit pourquoi il s'est arrêté : c'est
            # cela qu'il faut lire en premier.
            key = "analysis_done"
            args["stop_reason"] = head.get("stop_reason")
        else:
            # L'étape a bien eu lieu — c'est le VERDICT qui manque. Marquer l'étape
            # `unavailable` dirait que l'analyse n'a pas eu lieu, ce qui est faux :
            # l'absence est nommée là où elle est, sur la donnée manquante.
            key = "analysis_no_verdict"
            measures["verdict_indisponible"] = (
                {"reason": "ce cycle n'a pas consigné de verdict pour ce trajet "
                           "(run_receipts.progress ne porte pas cet uid)",
                 "gesture": "le producteur doit renseigner run_receipts.progress[uid].coverage",
                 "substitute": "les compteurs de couverture du cycle (cycle_couverture_*), "
                               "qui décrivent le paquet et non ce trajet"}
                if verdict is None else
                {"reason": f"verdict {verdict!r} inconnu de ce module",
                 "gesture": "ajouter la clé de gabarit correspondante dans CASCADE_TEMPLATES",
                 "substitute": "les compteurs de couverture du cycle (cycle_couverture_*)"})
        steps.add("analysis", key, args,
                  sources, at=head.get("cycle_debut"),
                  duration_ms=head.get("cycle_duree_ms"),
                  measures=measures, targets=targets)
    elif status == "quarantined":
        steps.add("analysis", "analysis_quarantined",
                  {"run": run_ref, "duration_ms": head.get("cycle_duree_ms")},
                  sources, state="failed", at=head.get("cycle_debut"),
                  duration_ms=head.get("cycle_duree_ms"),
                  measures=measures, targets=targets)
    else:
        steps.add("analysis", "analysis_failed",
                  {"run": run_ref, "status": status,
                   "duration_ms": head.get("cycle_duree_ms")},
                  sources, state="failed", at=head.get("cycle_debut"),
                  duration_ms=head.get("cycle_duree_ms"),
                  measures=measures, targets=targets)


def _step_atoms(steps: _Steps, head: dict[str, Any], atoms: list[dict[str, Any]],
                totals: dict[str, Any], sql: str) -> None:
    uid, title = head["uid"], head.get("titre")
    trace = _src_trace("memory_atoms", uid, sql, "les atomes portant ce run_ref et ce conversation_uid")
    nes = totals.get("atomes_nes")
    measures = {
        "atomes_nes": nes,
        "atomes_vivants": totals.get("atomes_vivants"),
        "atomes_sur_racine_nue": totals.get("atomes_sur_racine_nue"),
        "scopes_touches": totals.get("scopes_touches"),
        "genres_touches": totals.get("genres_touches"),
        "premier_atome_le": totals.get("premier_atome_le"),
        "dernier_atome_le": totals.get("dernier_atome_le"),
        "detail_tronque": bool(nes and nes > len(atoms)),
        "detail_servi": len(atoms),
    }
    if not nes:
        # CE QUI ÉTAIT FAUX : `atoms_none` (« ce passage n'a rien appris de neuf »)
        # était émis sans jamais regarder le statut du cycle. Il tombait donc sur
        # 463 trajets issus de cycles en quarantaine — où la proposition du modèle
        # EXISTE, en octets, en base — et sur 195 trajets de cycles `spawn_failed`,
        # où le modèle n'a jamais été appelé. La même cascade disait alors, deux
        # étapes plus haut, que le cycle n'avait pas abouti.
        if not _cycle_abouti(head):
            absence = _absence_du_cycle(head)
            steps.add("atoms_born", "atoms_unavailable",
                      {"run": head.get("run_ref"), "status": head.get("status")},
                      [_src_conversation(uid, title), trace],
                      state="unavailable",
                      measures=measures | {"atomes_nes": None} | absence, targets=[])
            return
        steps.add("atoms_born", "atoms_none", {},
                  [_src_conversation(uid, title), trace],
                  state="skipped", measures=measures, targets=[])
        return
    steps.add("atoms_born", "atoms_born",
              {"count": nes, "kinds": ", ".join(totals.get("genres") or [])},
              [_src_conversation(uid, title), trace] + [_src_atom(a) for a in atoms],
              at=totals.get("premier_atome_le"),
              duration_ms=totals.get("ecriture_duree_ms"),
              measures=measures,
              targets=[_src_atom(a) | {"kind": "atom", "atom_kind": a.get("kind"),
                                       "scope": a.get("scope"), "status": a.get("status")}
                       for a in atoms])


def _step_superseded(steps: _Steps, head: dict[str, Any], rows: list[dict[str, Any]],
                     totals: dict[str, Any], sql: str) -> None:
    uid, title = head["uid"], head.get("titre")
    trace = _src_trace("superseded_by", uid, sql,
                       "les atomes dont superseded_by pointe vers un atome de ce trajet")
    if not totals.get("atomes_nes"):
        return
    total = totals.get("atomes_remplaces")
    if not total:
        steps.add("atoms_superseded", "atoms_no_supersede", {},
                  [_src_conversation(uid, title), trace],
                  state="skipped", measures={"remplaces": 0}, targets=[])
        return
    steps.add("atoms_superseded", "atoms_superseded",
              {"count": total},
              [_src_conversation(uid, title), trace]
              + [{"kind": "atom", "ref": r.get("ancien_id"), "label": r.get("key"),
                  "href": f"{_PREFIX}/atoms/{r.get('ancien_id')}"} for r in rows],
              at=rows[0].get("remplace_le") if rows else None,
              measures={"remplaces": total,
                        "survie_jours_min": totals.get("survie_jours_min"),
                        "survie_jours_max": totals.get("survie_jours_max"),
                        "detail_servi": len(rows),
                        "detail_tronque": bool(total > len(rows))},
              targets=[{"kind": "atom", "ref": r.get("ancien_id"), "label": r.get("key"),
                        "href": f"{_PREFIX}/atoms/{r.get('ancien_id')}",
                        "remplace_par": r.get("nouvel_id"),
                        "survie_jours": r.get("survie_jours")} for r in rows])


def _step_dropped(steps: _Steps, head: dict[str, Any], rows: list[dict[str, Any]],
                  totals: dict[str, Any], sql: str) -> None:
    uid, title = head["uid"], head.get("titre")
    trace = _src_trace("digestion_review_queue", uid, sql,
                       "les candidats écartés pour ce cycle et cette conversation")
    total = totals.get("candidats_ecartes")
    if not total:
        # CE QUI ÉTAIT FAUX, DEUX FOIS.
        #
        # 1) La clé de totaux lue était `atomes_crees`, qui n'existe NULLE PART :
        #    le SQL sert `atomes_nes`. `produits` valait donc toujours 0 côté
        #    atomes, et 107 trajets sur les 119 ayant produit du savoir affichaient
        #    « ce trajet n'a proposé aucun savoir » dans la MÊME cascade où l'étape
        #    précédente disait « 3 nouvel(s) atome(s) de savoir ». Le gabarit
        #    `candidates_kept_all` était de fait mort (12 émissions possibles sur 119).
        #
        # 2) Aucune branche ne regardait le statut du cycle. Sur un cycle en
        #    quarantaine, 9 757 octets de savoir proposé peuvent dormir dans
        #    run_receipts.quarantine_output, rejetés quatre fois pour cette
        #    conversation précise — et la cascade affirmait qu'il n'avait « rien
        #    proposé ». 71 paires (cycle, conversation) sont dans ce cas.
        #
        # CE QUE CETTE VERSION GARANTIT : « rien proposé » ne se dit que d'un cycle
        # ABOUTI dont ce trajet n'a effectivement rien tiré ; partout ailleurs,
        # c'est la trace qui manque, et elle est nommée comme telle.
        if head.get("status") == "quarantined" and head.get("quarantaine_attribuee"):
            absence = _absence_du_cycle(head)
            steps.add("dropped", "candidates_quarantined",
                      {"run": head.get("run_ref"),
                       "errors": absence.get("quarantaine_erreurs")},
                      [_src_conversation(uid, title), trace],
                      state="unavailable",
                      measures={"ecartes": None, "produits": None} | absence, targets=[])
            return
        if not _cycle_abouti(head):
            absence = _absence_du_cycle(head)
            steps.add("dropped", "candidates_unavailable",
                      {"run": head.get("run_ref"), "status": head.get("status"),
                       "reason": absence.get("reason")},
                      [_src_conversation(uid, title), trace],
                      state="unavailable",
                      measures={"ecartes": None, "produits": None} | absence, targets=[])
            return
        # Distinguer « rien écarté parce que tout est entré » de « rien écarté
        # parce que rien n'a été proposé ». La seconde reste le cas fréquent, et
        # ce n'est pas une bonne nouvelle.
        produits = (totals.get("atomes_nes") or 0) + (totals.get("atomes_remplaces") or 0)
        cle = "candidates_kept_all" if produits else "candidates_none_proposed"
        steps.add("dropped", cle, {},
                  [_src_conversation(uid, title), trace],
                  state="skipped",
                  measures={"ecartes": 0, "produits": produits}, targets=[])
        return
    motifs = totals.get("motifs_ecart") or []
    steps.add("dropped", "candidates_dropped",
              {"count": total, "reasons": ", ".join(motifs)},
              [_src_conversation(uid, title), trace]
              + [_src_scope(r.get("scope")) for r in rows if r.get("scope")],
              at=rows[0].get("created_at") if rows else None,
              measures={"ecartes": total, "motifs": motifs,
                        "detail_servi": len(rows),
                        "detail_tronque": bool(total > len(rows))},
              targets=[{"kind": "scope", "ref": r.get("scope"), "label": r.get("scope"),
                        "href": f"{_PREFIX}/scopes/{quote(str(r.get('scope') or ''), safe='/')}",
                        "clef_proposee": r.get("clef_proposee"),
                        "genre_propose": r.get("kind"),
                        "motif": r.get("motif"), "statut_revue": r.get("statut_revue")}
                       for r in rows])


def _step_links(steps: _Steps, head: dict[str, Any],
                links_dep: dict[str, str] | None = None) -> None:
    """L'étape qui n'a JAMAIS de chiffre. Elle a une raison, un geste, un substitut.

    Écrire « 0 lien créé » serait le mensonge le plus facile de ce fichier : la
    mesure n'existe pas. Une absence de mesure n'est pas une mesure nulle, et
    cette étape est là précisément pour le dire à chaque cascade.

    POURQUOI la raison est passée en argument
    -----------------------------------------
    Elle disait, sans condition, que la table des liens n'existait pas — l'état
    d'une base précise, gravé dans le code et resservi à tout le monde. La raison
    vient donc maintenant d'un CONSTAT (``entities.links_dependency``), fait une
    seule fois par appel et partagé par toutes les cascades du lot : sonder une
    fois par cascade ouvrirait autant de connexions que de conversations
    affichées, pour une réponse identique.

    Sans constat fourni, on retombe sur le texte qui n'affirme rien.
    """
    dep = dict(links_dep or LINKS_UNAVAILABLE)
    uid, title = head["uid"], head.get("titre")
    steps.add("links", "links_unavailable",
              {"reason": dep["reason"]},
              [_src_conversation(uid, title),
               # Le libellé ne dit plus « la table absente » : la trace est la
               # REQUÊTE qui tranche, pas sa conclusion supposée. Elle est
               # rejouable telle quelle en psql, comme toutes les autres.
               {"kind": "trace", "ref": "arac.atom_links",
                "label": "l'état constaté de la table",
                "href": f"{_PREFIX}/status",
                "sql": "SELECT to_regclass('arac.atom_links') AS table_presente"}],
              state="unavailable",
              measures={"liens": None} | dep,
              targets=[])


def _step_recall(steps: _Steps, head: dict[str, Any], recall: dict[str, Any],
                 atoms: list[dict[str, Any]], totals: dict[str, Any], sql: str) -> None:
    uid, title = head["uid"], head.get("titre")
    trace = _src_trace("context_receipts", uid, sql,
                       "les reçus de rappel ayant servi un atome de ce trajet")
    if not totals.get("atomes_nes"):
        if not _cycle_abouti(head):
            absence = _absence_du_cycle(head)
            steps.add("recall", "recall_unavailable",
                      {"run": head.get("run_ref"), "status": head.get("status")},
                      [_src_conversation(uid, title), trace],
                      state="unavailable",
                      measures={"rappels": None} | absence, targets=[])
            return
        steps.add("recall", "recall_skipped", {},
                  [_src_conversation(uid, title), trace],
                  state="skipped", measures={"rappels": 0}, targets=[])
        return
    if not recall.get("rappels"):
        steps.add("recall", "recall_never", {},
                  [_src_conversation(uid, title), trace],
                  state="skipped", measures={"rappels": 0}, targets=[])
        return
    # Ne montrer QUE les atomes réellement ressortis. Lister ici tous les atomes
    # du trajet donnait à lire « 42 rappels » au-dessus de deux atomes dont un
    # seul avait jamais été servi : la cible démentait la mesure.
    servis = set(recall.get("atomes_rappeles_ids") or [])
    rappeles = [a for a in atoms if str(a.get("id")) in servis]
    steps.add("recall", "recall_served",
              {"receipts": recall.get("rappels"),
               "atoms": recall.get("atomes_rappeles"),
               "last_at": recall.get("dernier_rappel_le")},
              [_src_conversation(uid, title), trace] + [_src_atom(a) for a in rappeles],
              at=recall.get("premier_rappel_le"),
              measures={"rappels": recall.get("rappels"),
                        "atomes_rappeles": recall.get("atomes_rappeles"),
                        "consommateurs": recall.get("consommateurs"),
                        "rappels_bande_haute": recall.get("rappels_bande_haute"),
                        "premier_rappel_le": recall.get("premier_rappel_le"),
                        "dernier_rappel_le": recall.get("dernier_rappel_le"),
                        "detail_servi": len(rappeles),
                        "detail_tronque": bool(recall.get("atomes_rappeles") and
                                               recall["atomes_rappeles"] > len(rappeles))},
              targets=[_src_atom(a) for a in rappeles])


def _step_consolidated(steps: _Steps, head: dict[str, Any], cons: dict[str, Any],
                       atoms: list[dict[str, Any]], sql: str) -> None:
    uid, title = head["uid"], head.get("titre")
    trace = _src_trace("consolidation", uid, sql,
                       "l'état d'aujourd'hui des atomes nés de ce trajet")
    nes, vivants = cons.get("nes"), cons.get("vivants")
    measures = {
        "nes": nes, "vivants": vivants,
        "retires": cons.get("retires"),
        "remplaces_depuis": cons.get("remplaces_depuis"),
        "retouches_depuis": cons.get("retouches_depuis"),
        "indexables": cons.get("indexables"),
        "confiance_moyenne": cons.get("confiance_moyenne"),
        "age_jours": cons.get("age_jours"),
    }
    if not nes:
        if not _cycle_abouti(head):
            absence = _absence_du_cycle(head)
            steps.add("consolidated", "consolidated_unavailable",
                      {"run": head.get("run_ref"), "status": head.get("status")},
                      [_src_conversation(uid, title), trace],
                      state="unavailable",
                      measures=measures | {"nes": None, "vivants": None} | absence,
                      targets=[])
            return
        steps.add("consolidated", "consolidated_empty", {},
                  [_src_conversation(uid, title), trace],
                  state="skipped", measures=measures, targets=[])
        return
    if not vivants:
        steps.add("consolidated", "consolidated_all_gone", {"born": nes},
                  [_src_conversation(uid, title), trace] + [_src_atom(a) for a in atoms],
                  state="failed", measures=measures,
                  targets=[_src_atom(a) for a in atoms])
        return
    steps.add("consolidated", "consolidated", {"alive": vivants, "born": nes},
              [_src_conversation(uid, title), trace] + [_src_atom(a) for a in atoms],
              measures=measures,
              targets=[_src_atom(a) | {"status": a.get("status")} for a in atoms])


# ============================================================================
# API PUBLIQUE
# ============================================================================


def cascades(limit: int = DEFAULT_CASCADES, since: Any = None,
             uid: str | None = None) -> dict[str, Any]:
    """Les cascades achevées, la plus récente d'abord. Ne lève jamais.

    ``uid`` restreint à UNE conversation : même forme, mêmes étapes, mêmes
    gabarits. Il n'existe qu'une construction de cascade — deux implémentations
    de la même étape finiraient par se contredire, et la page cesserait d'être
    opposable.
    """
    n = _bounded(limit)
    want_uid = _clean(uid)
    since_dt = _since(since)
    notices: list[str] = []
    if since is not None and _clean(since) and since_dt is None:
        notices.append("borne « since » illisible : ignorée (ISO 8601 attendu)")

    run_scan = min(n + _RUN_SCAN_CUSHION, _MAX_RUN_SCAN)
    head_params = {"since": since_dt, "uid": want_uid, "run_scan": run_scan, "limit": n}
    executed: dict[str, str] = {}
    rows_read = 0

    try:
        with _readonly() as conn:
            heads_all = _rows(conn, _Q_HEAD, head_params, where="cascade.head")
            executed["head"] = _sql_text(conn, _Q_HEAD, head_params)
            rows_read += len(heads_all)

            corpus = (_rows(conn, _Q_CORPUS, head_params, where="cascade.corpus")
                      or [{}])[0]
            executed["corpus"] = _sql_text(conn, _Q_CORPUS, head_params)
            rows_read += 1

            # --- Dédup par conversation, puis borne ---------------------------
            # La requête rend TOUS les passages ; on ne garde que le plus récent
            # de chaque conversation avant de couper. Sans cela, un seul cycle
            # en quarantaine dont le paquet portait 13 conversations occupait
            # 13 des 20 cartes, et l'écran phare ne pouvait STRUCTURELLEMENT
            # pas montrer un trajet réussi. Six cartes sur vingt étaient en
            # outre le même sujet répété, sans que rien ne le dise.
            vus: set = set()
            distincts: list = []
            for h in heads_all:
                if h["uid"] in vus:
                    continue
                vus.add(h["uid"])
                distincts.append(h)
            total_distinct = len(distincts)
            heads = distincts[:n] if not want_uid else heads_all[:n]
            # « total_conversations » nommait un SOUS-total : ce que la fenêtre de
            # balayage avait atteint, pas ce que la base contient. Les clés portent
            # désormais leur portée dans leur nom, et le corpus est servi à côté.
            tronque = {
                "applied": (not want_uid) and total_distinct > len(heads),
                "shown": len(heads),
                "conversations_dans_la_fenetre": total_distinct,
                "passages_dans_la_fenetre": len(heads_all),
                "fenetre_de_balayage": {
                    "cycles_demandes": run_scan,
                    "cycles_balayes": corpus.get("cycles_balayes"),
                    "depuis": corpus.get("balayage_depuis"),
                    "jusqua": corpus.get("balayage_jusqua"),
                    "plafond": _MAX_RUN_SCAN,
                    "note": ("le balayage part des cycles les plus récents ; "
                             "une conversation dont le dernier passage est "
                             "antérieur à `depuis` est hors de portée de cet appel"),
                },
                "corpus": {
                    "conversations": corpus.get("corpus_conversations"),
                    "passages": corpus.get("corpus_passages"),
                    "cycles": corpus.get("corpus_cycles"),
                    "note": ("tout ce que la base porte, hors fenêtre de balayage — "
                             "compté par une requête bornée, pas par le balayage"),
                },
                "note": ("une conversation n'apparaît qu'une fois, "
                         "à son passage le plus récent"),
            }
            if tronque["applied"]:
                depuis = corpus.get("balayage_depuis")
                notices.append(
                    f"{corpus.get('corpus_conversations')} conversations ont une "
                    f"cascade achevée ; le balayage porte sur les "
                    f"{corpus.get('cycles_balayes')} derniers cycles "
                    f"(depuis {str(depuis)[:10]}), soit {total_distinct} d'entre "
                    f"elles, dont les {len(heads)} plus récentes sont servies. "
                    "Affinez avec ?since= ou ouvrez une conversation précise."
                )

            if not heads:
                return {
                    "items": [], "count": 0, "state": "ok",
                    "limit": n, "since": since_dt.isoformat() if since_dt else None,
                    "conversation_uid": want_uid,
                    "reason": ("aucune cascade achevée ne correspond"
                               if not want_uid else
                               "cette conversation n'a jamais été présentée à un cycle achevé"),
                    "templates": CASCADE_TEMPLATES,
                    "unknown_template": UNKNOWN_TEMPLATE,
                    "rules": STEP_RULES,
                    "stages": list(STAGES),
                    "notices": notices,
                    "rows_read": rows_read,
                    "evidence": {"kind": "sql", "sql": executed["head"], "blocks": executed},
                    "computed_at": service._now(),
                }

            spine_pairs, spine_params = _pairs_values(heads, spine=True)
            flat_pairs, flat_params = _pairs_values(heads)
            uids = [h["uid"] for h in heads]

            q_detected = _Q_DETECTED.format(pairs=spine_pairs)
            p_detected = spine_params | {"uids": uids}
            detected = _rows(conn, q_detected, p_detected, where="cascade.detected")
            executed["detected"] = _sql_text(conn, q_detected, p_detected)
            rows_read += len(detected)

            q_atoms = _Q_ATOMS.format(pairs=flat_pairs)
            p_atoms = flat_params | {"slash": "%/%", "per_cascade": MAX_ATOMS_PER_CASCADE}
            atoms = _rows(conn, q_atoms, p_atoms, where="cascade.atoms")
            executed["atoms"] = _sql_text(conn, q_atoms, p_atoms)
            rows_read += len(atoms)

            q_totals = _Q_TOTALS.format(pairs=flat_pairs)
            p_totals = flat_params | {"slash": "%/%"}
            totals = _rows(conn, q_totals, p_totals, where="cascade.totals")
            executed["totals"] = _sql_text(conn, q_totals, p_totals)
            rows_read += len(totals)

            q_scopes = _Q_SCOPES.format(pairs=flat_pairs)
            p_scopes = flat_params | {"slash": "%/%", "per_cascade": MAX_SCOPES_PER_CASCADE}
            scopes = _rows(conn, q_scopes, p_scopes, where="cascade.scopes")
            executed["scopes"] = _sql_text(conn, q_scopes, p_scopes)
            rows_read += len(scopes)

            proj_sql, proj_params = _projects_sql()
            q_projects = proj_sql.format(pairs=flat_pairs)
            p_projects = flat_params | proj_params
            projects = _rows(conn, q_projects, p_projects, where="cascade.projects")
            executed["projects"] = _sql_text(conn, q_projects, p_projects)
            rows_read += len(projects)

            q_sup = _Q_SUPERSEDED.format(pairs=flat_pairs)
            p_sup = flat_params | {"per_cascade": MAX_SUPERSEDED_PER_CASCADE}
            superseded = _rows(conn, q_sup, p_sup, where="cascade.superseded")
            executed["superseded"] = _sql_text(conn, q_sup, p_sup)
            rows_read += len(superseded)

            q_drop = _Q_DROPPED.format(pairs=flat_pairs)
            p_drop = flat_params | {"per_cascade": MAX_DROPPED_PER_CASCADE}
            dropped = _rows(conn, q_drop, p_drop, where="cascade.dropped")
            executed["dropped"] = _sql_text(conn, q_drop, p_drop)
            rows_read += len(dropped)

            q_recall = _Q_RECALL.format(pairs=flat_pairs)
            recall = _rows(conn, q_recall, flat_params, where="cascade.recall")
            executed["recall"] = _sql_text(conn, q_recall, flat_params)
            rows_read += len(recall)

            q_cons = _Q_CONSOLIDATED.format(pairs=flat_pairs)
            consolidated = _rows(conn, q_cons, flat_params, where="cascade.consolidated")
            executed["consolidated"] = _sql_text(conn, q_cons, flat_params)
            rows_read += len(consolidated)

    except Exception as exc:  # noqa: BLE001 — résilience volontaire (I2)
        failure = _failure("cascade", exc)
        return failure | {"items": [], "count": 0, "limit": n,
                          "conversation_uid": want_uid,
                          "templates": CASCADE_TEMPLATES,
                          "unknown_template": UNKNOWN_TEMPLATE,
                          "rules": STEP_RULES,
                          "stages": list(STAGES),
                          "notices": notices,
                          "evidence": {"kind": "sql",
                                       "sql": ";\n\n".join(executed.values()),
                                       "blocks": executed}}

    by_detected = _index(detected)
    by_atoms = _index(atoms)
    by_totals = _index(totals)
    by_scopes = _index(scopes)
    by_projects = _index(projects)
    by_superseded = _index(superseded)
    by_dropped = _index(dropped)
    by_recall = _index(recall)
    by_consolidated = _index(consolidated)

    items: list[dict[str, Any]] = []
    refused_all: list[dict[str, str]] = []

    # UN seul constat de la couche de liens pour tout le lot : la réponse est la
    # même pour toutes les cascades servies, et la sonder par cascade ouvrirait
    # une connexion par conversation affichée.
    links_dep = _links_dependency()

    for head in heads:
        key = (head["run_ref"], head["uid"])
        det = _first(by_detected, key)
        tot = _first(by_totals, key)
        cons = _first(by_consolidated, key)
        rec = _first(by_recall, key)
        cascade_atoms = by_atoms.get(key) or []
        cascade_scopes = by_scopes.get(key) or []
        cascade_projects = by_projects.get(key) or []
        cascade_superseded = by_superseded.get(key) or []
        cascade_dropped = by_dropped.get(key) or []

        steps = _Steps()
        _step_detected(steps, head, det, executed["detected"])
        _step_absorbed(steps, head, executed["head"])
        _step_projects(steps, head, cascade_projects, cascade_atoms, executed["projects"])
        _step_scopes(steps, head, cascade_scopes, executed["scopes"])
        _step_analysis(steps, head, executed["head"])
        _step_atoms(steps, head, cascade_atoms, tot, executed["atoms"])
        _step_superseded(steps, head, cascade_superseded, tot, executed["superseded"])
        _step_dropped(steps, head, cascade_dropped, tot, executed["dropped"])
        _step_links(steps, head, links_dep)
        _step_recall(steps, head, rec, cascade_atoms, tot, executed["recall"])
        _step_consolidated(steps, head, cons, cascade_atoms, executed["consolidated"])
        refused_all.extend(steps.refused)

        outcome_state = "learned"
        if head.get("status") != "done":
            outcome_state = "failed"
        elif not tot.get("atomes_nes"):
            outcome_state = "no_new_knowledge"

        items.append({
            "cascade_id": head["cascade_id"],
            "started_at": det.get("cascade_debut") or head.get("cycle_debut"),
            "ended_at": det.get("cascade_fin") or head.get("cycle_fin"),
            "duration_ms": det.get("cascade_duree_ms"),
            "subject": {
                "kind": "conversation",
                "uid": head["uid"],
                "title": head.get("titre"),
                "source_type": head.get("source_type"),
                "messages": head.get("messages_total"),
                "node_id": head.get("conversation_noeud"),
                "created_at": head.get("conversation_creee_le"),
                "curated_at": head.get("conversation_curee_le"),
                "exclusion_reason": head.get("conversation_exclusion"),
                "href": _href_conversation(head["uid"]),
            },
            "run": {
                "ref": head.get("run_ref"),
                "trigger": head.get("trigger"),
                "model": head.get("model"),
                "status": head.get("status"),
                "stop_reason": head.get("stop_reason"),
                "started_at": head.get("cycle_debut"),
                "ended_at": head.get("cycle_fin"),
                "duration_ms": head.get("cycle_duree_ms"),
                "rank_in_pack": head.get("rang_paquet"),
                "items": head.get("cycle_items"),
            },
            "steps": steps.ordered(),
            "outcome": {
                "atoms_created": tot.get("atomes_nes"),
                "atoms_superseded": tot.get("atomes_remplaces"),
                "dropped": tot.get("candidats_ecartes"),
                "quarantined": head.get("quarantaine_attribuee"),
                "alive_today": cons.get("vivants"),
                "state": outcome_state,
            },
            # Le MÊME constat que l'étape « liens » de cette cascade : deux
            # blocs de la même charge utile ne peuvent pas dire deux choses
            # différentes de la même table. Celui-ci servait le repli.
            "links": dict(links_dep) | {
                "impact": ["étape « liens » de la cascade",
                           "densité du trajet",
                           "atomes orphelins de ce trajet"],
                "substitute": ("voisinage sémantique (embedding <=>) via "
                               "/cc/v1/atoms/{id}/story — aucune de ces arêtes "
                               "n'est un lien déclaré par le cerveau"),
            },
            "truncated": {
                "atoms": bool(tot.get("atomes_nes") and
                              tot["atomes_nes"] > len(cascade_atoms)),
                "atoms_limit": MAX_ATOMS_PER_CASCADE,
                "scopes_limit": MAX_SCOPES_PER_CASCADE,
                "superseded_limit": MAX_SUPERSEDED_PER_CASCADE,
                "dropped_limit": MAX_DROPPED_PER_CASCADE,
            },
            "refused_without_source": steps.refused,
        })

    if rows_read > MAX_ROWS_PER_CALL:
        notices.append(f"budget de lignes dépassé : {rows_read} > {MAX_ROWS_PER_CALL}")

    # --- Chaque SQL de trace est NOMMÉ, pas seulement recopié ----------------
    #
    # CE QUI ÉTAIT (ET RESTE PARTIELLEMENT) FAUX : les sources de type « trace »
    # recopient la requête complète à chaque étape de chaque cascade. Mesuré sur
    # ?limit=20 : 202 occurrences pour 11 chaînes distinctes, 684 334 octets de
    # champ `sql` pour 67 476 octets de contenu réel — et ces 11 chaînes sont
    # DÉJÀ servies, octet pour octet, dans `evidence.blocks` du même document.
    #
    # CE QUE CETTE VERSION GARANTIT : chaque trace porte `sql_ref`, le nom du
    # bloc de `evidence.blocks` qui contient sa requête — posé SI ET SEULEMENT
    # SI le texte servi y est identique octet pour octet. Le champ `sql` reste
    # servi tant que le client le lit (`app.js:stepSourceNodes` marquerait la
    # source « indisponible » sans lui, ce qui serait un mensonge : elle est
    # disponible). Le jour où le client lit `sql_ref`, la déduplication est
    # d'une ligne ici — et la garde du smoke prouve qu'elle ne perdra rien.
    bloc_par_texte = {texte: nom for nom, texte in executed.items()}
    for item in items:
        for etape in item["steps"]:
            for source in etape.get("sources") or []:
                nom = bloc_par_texte.get(source.get("sql"))
                if nom:
                    source["sql_ref"] = nom

    return {
        "items": items,
        "truncated": tronque,
        "count": len(items),
        "state": "ok",
        "limit": n,
        "since": since_dt.isoformat() if since_dt else None,
        "conversation_uid": want_uid,
        "templates": CASCADE_TEMPLATES,
        "unknown_template": UNKNOWN_TEMPLATE,
        "rules": STEP_RULES,
        "stages": list(STAGES),
        "doctrine": ("le serveur ne compose aucune phrase : il désigne un gabarit et "
                     "fournit ses arguments et ses sources ; une étape sans source "
                     "résolvable est refusée à la construction, jamais filtrée après ; "
                     "une source de trace porte `sql_ref`, le nom de son bloc dans "
                     "`evidence.blocks` — son champ `sql` en est la copie littérale, "
                     "servie pour les clients qui ne résolvent pas encore la référence"),
        "notices": notices,
        "refused_without_source": refused_all,
        "rows_read": rows_read,
        "rows_budget": MAX_ROWS_PER_CALL,
        "evidence": {"kind": "sql", "sql": ";\n\n".join(executed.values()),
                     "blocks": executed},
        "computed_at": service._now(),
    }


def catalog() -> dict[str, Any]:
    """Les gabarits et la règle d'émission de chaque étape, SANS exécution.

    Cette route répond même base éteinte : elle documente le contrat de narration
    et ne le calcule pas. C'est aussi ce qui permet à l'interface de vérifier
    qu'elle connaît toutes les clés que le serveur peut lui envoyer.
    """
    return {
        "templates": CASCADE_TEMPLATES,
        "unknown_template": UNKNOWN_TEMPLATE,
        "rules": STEP_RULES,
        "stages": [s | {"rank": _STAGE_RANK[s["stage"]]} for s in STAGES],
        "template_count": len(CASCADE_TEMPLATES),
        "stage_count": len(STAGES),
        "states": {
            "passed": "l'étape a eu lieu et sa trace existe",
            "failed": "l'étape a eu lieu et s'est mal terminée",
            "skipped": "l'étape n'a légitimement pas eu lieu (rien à faire)",
            "unavailable": "la trace nécessaire n'existe pas en base — jamais un zéro",
        },
        # Le serveur ne met pas en forme : il NOMME. Le suffixe de l'argument dit
        # au client comment le rendre. C'est la frontière exacte entre ce qui est
        # interdit ici (l'agrégation) et ce qui lui est permis là-bas (le
        # formatage) : « 248898 » et « 4 min 9 s » sont la même donnée.
        "arg_formats": {
            "_ms": "durée en millisecondes — à rendre en durée lisible",
            "_at": "horodatage ISO 8601 UTC — à rendre en date, absolue ou relative",
            "count / receipts / atoms / messages / born / alive / roots":
                "entier — à rendre avec un séparateur de milliers",
            "projects / scopes / kinds / reasons":
                "liste déjà jointe par le serveur, dans l'ordre servi ; l'ordre EST "
                "l'information et ne doit pas être retrié",
        },
        "source_kinds": {
            "conversation": f"{_PREFIX}/conversations/{{uid}}",
            "atom": f"{_PREFIX}/atoms/{{id}}",
            "scope": f"{_PREFIX}/scopes/{{path}}",
            "project": f"{_PREFIX}/projects/{{id}}",
            "run": f"{_PREFIX}/timeline?from=&to=&granularity=hour",
            "trace": f"{_PREFIX}/cascade/{{uid}} + le SQL exact, rejouable en psql",
        },
        "identity": ("cascade_id = run_ref + '::' + conversation_uid — une cascade est "
                     "le passage d'UNE conversation dans UN cycle, pas la vie entière "
                     "d'une conversation"),
        # L'exhaustivité était annoncée avec une DATE : « vérifié exhaustif le
        # 2026-08-04 ». C'était le constat fait sur une base, un jour, servi
        # ensuite à tout le monde comme une propriété du système. Ce catalogue
        # ne peut pas vérifier cela — il répond base éteinte. Il énonce donc la
        # règle, et nomme la requête qui permet à chacun de la vérifier chez
        # lui : une garantie qu'on peut rejouer vaut mieux qu'une date.
        "enumeration": ("run_receipts.pack, le manifeste écrit par le cerveau avant de "
                        "travailler ; pour vérifier qu'aucun atome portant un run_ref "
                        "n'échappe à un paquet sur VOTRE base : SELECT count(*) FROM "
                        "arac.memory_atoms a WHERE a.source_ref ? 'run_ref' AND NOT EXISTS "
                        "(SELECT 1 FROM arac.run_receipts r WHERE r.pack ? "
                        "(a.source_ref->>'conversation_uid'))"),
        "doctrine": ("le serveur ne compose aucune phrase ; une étape sans source "
                     "résolvable est refusée à la construction ; une mesure absente "
                     "n'est jamais un zéro"),
        "limits": {
            "cascades_per_call": MAX_CASCADES,
            "atoms_per_cascade": MAX_ATOMS_PER_CASCADE,
            "scopes_per_cascade": MAX_SCOPES_PER_CASCADE,
            "superseded_per_cascade": MAX_SUPERSEDED_PER_CASCADE,
            "dropped_per_cascade": MAX_DROPPED_PER_CASCADE,
            "rows_per_call": MAX_ROWS_PER_CALL,
        },
        "known_absences": {
            # Ce catalogue répond base ÉTEINTE : il ne peut rien affirmer de
            # l'état d'une base, et il ne doit pas essayer. Il servait le repli
            # de la sonde — « le schéma n'a pas été interrogé » — ce qui est
            # vrai ici mais se lit comme un diagnostic d'installation. Ce que
            # ce catalogue sait, et qui reste vrai sur toute base, c'est que la
            # narration ne LIT pas cette table. L'état constaté, lui, se demande
            # à /status, qui a une connexion pour le regarder.
            "atom_links": {
                "state": "unavailable",
                "reason": ("l'étape « liens » de la cascade n'interroge pas "
                           "arac.atom_links : ce catalogue décrit ce que la "
                           "narration ne lit pas, jamais l'état d'une base"),
                "gesture": f"pour l'état constaté de la table : {_PREFIX}/status",
                "substitute": "voisinage sémantique + vue « jamais rappelés »",
            },
            "capture_manifests.conversation_uid": {
                "state": "unavailable",
                "reason": "arac.capture_manifests ne porte pas de conversation_uid",
                "gesture": "ajouter la colonne, ou publier le manifeste dans le reçu d'ingestion",
                "substitute": ("recouvrement temporel : même nœud, même source, course de "
                               "capture contenant le reçu d'ingestion"),
            },
            "legacy_source_ref": {
                "state": "unavailable",
                "reason": ("les atomes antérieurs au 2026-07-03 portent un source_ref de "
                           "l'ancien contrat (curator_raw_id) sans run_ref ni conversation_uid"),
                "gesture": "rétro-attribuer curator_raw_id à une conversation",
                "substitute": "aucun — ces atomes n'apparaissent dans aucune cascade",
            },
        },
        "computed_at": service._now(),
    }


# ============================================================================
# Enregistrement
# ============================================================================


def register(
    a: FastAPI,
    session_api: Callable[..., Any],
    audit_read_log: Callable[[str, str], Any],
) -> None:
    """Enregistre ``/cc/v1/cascade``, ``/cc/v1/cascade/catalog`` et
    ``/cc/v1/cascade/{conversation_uid}``.

    ``catalog`` est déclarée AVANT la route paramétrée : FastAPI apparie dans
    l'ordre de déclaration, et une route ``{conversation_uid}` posée d'abord
    avalerait le mot « catalog » comme s'il était un identifiant.

    GET uniquement, garde de session sur chaque route, journal de lecture sur
    chaque accès, handlers synchrones (threadpool) — doctrine identique au socle.
    """

    @a.get(f"{_PREFIX}/cascade")
    def cc_v1_cascade(
        principal: dict = Depends(session_api),
        limit: int = Query(default=DEFAULT_CASCADES, ge=1, le=MAX_CASCADES),
        since: str | None = Query(default=None, max_length=64),
    ) -> JSONResponse:
        """Les dernières cascades achevées : le trajet d'une conversation, étape par étape.

        Aucune phrase n'est composée ici. Le client assemble
        ``templates[template_key].format(**args)`` et retombe sur
        ``unknown_template`` si la clé lui est inconnue.
        """
        audit_read_log(f"{_PREFIX}/cascade", principal.get("sub", "?"))
        return JSONResponse(cascades(limit=limit, since=since))

    @a.get(f"{_PREFIX}/cascade/catalog")
    def cc_v1_cascade_catalog(principal: dict = Depends(session_api)) -> JSONResponse:
        """Les gabarits et la règle d'émission de chaque étape, sans exécution.

        Répond même si la base est éteinte : c'est le CONTRAT de narration, pas
        son résultat.
        """
        audit_read_log(f"{_PREFIX}/cascade/catalog", principal.get("sub", "?"))
        return JSONResponse(catalog())

    @a.get(f"{_PREFIX}/cascade/{{conversation_uid}}")
    def cc_v1_cascade_one(
        conversation_uid: str,
        principal: dict = Depends(session_api),
        limit: int = Query(default=MAX_CASCADES, ge=1, le=MAX_CASCADES),
        since: str | None = Query(default=None, max_length=64),
    ) -> JSONResponse:
        """Toutes les cascades d'UNE conversation, la plus récente d'abord.

        Même forme, mêmes étapes, mêmes gabarits que la liste : une conversation
        traverse le cerveau à chaque cycle où elle a bougé, et chaque passage a
        son propre verdict. Un uid inconnu ne lève pas : il rend une liste vide
        avec sa raison.
        """
        audit_read_log(f"{_PREFIX}/cascade/{conversation_uid}", principal.get("sub", "?"))
        return JSONResponse(cascades(limit=limit, since=since, uid=conversation_uid))
