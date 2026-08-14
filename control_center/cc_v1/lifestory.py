"""Control Center v1 — LA VIE DU CERVEAU : histoire, graphe, chronologie.

Le cockpit V1 affichait des ÉTATS. Ce module raconte une VIE. Trois routes, trois
questions qu'aucun compteur ne sait poser :

  ``/cc/v1/atoms/{id}/story``      D'où vient ce souvenir, qui l'a corrigé, qui
                                   s'en sert, et depuis quand ? — l'histoire
                                   complète d'un atome en UN seul appel.
  ``/cc/v1/projects/{id}/graph``   À quoi ce projet ressemble-t-il quand on le
                                   regarde comme un tissu plutôt qu'une liste ?
  ``/cc/v1/timeline``              Que s'est-il passé entre telle heure et telle
                                   heure ? — la chronologie REJOUABLE.

Ces routes sont ADDITIVES. ``entities.py`` sert déjà ``/cc/v1/atoms/{id}`` et
``/cc/v1/projects/{id}`` ; rien ici ne les modifie ni ne les redéclare. Les règles
de projet et les fonctions d'exécution sont **importées** d'``entities`` plutôt
que recopiées : une règle qui divergerait entre la fiche et le graphe ferait
mentir l'un des deux écrans.

DOCTRINE — identique au socle, sans exception
---------------------------------------------
- ``@a.get`` uniquement ; garde de session ; journal de lecture ; handlers
  synchrones (FastAPI les exécute en threadpool).
- **Toute l'arithmétique est en SQL** : distances ``<=>``, cumuls, différences de
  version, rangs, budgets de troncature. Python ne fait que borner une requête et
  transporter des lignes.
- **Toute réponse porte son ``evidence``** : le SQL réellement exécuté, paramètres
  substitués (``ClientCursor.mogrify``), sur une ligne, donc rejouable dans
  ``psql``. Un cockpit qui ne peut pas être contredit ne mérite pas d'être cru.
- **Une absence n'est jamais un zéro** : ``state='unavailable'`` + la raison.

CE QUI N'EXISTE PAS, ET QUI EST DIT PLUTÔT QUE TU
-------------------------------------------------
``arac.atom_links`` n'est pas lue par ce module. Il n'y a donc
**aucun lien explicite entre atomes** dans cette base. Conséquence assumée et
affichée dans les trois réponses :

  - le bloc ``links`` est TOUJOURS ``unavailable``, avec son geste et son substitut ;
  - les arêtes ``semantic`` du graphe viennent de la **proximité vectorielle**
    (``embedding <=>``) et les arêtes ``contains`` de l'**appartenance de scope ou
    de tag**. Aucune n'est un lien déclaré par le cerveau. Le graphe le dit dans
    sa propre charge utile (``edges_provenance``) : présenter une proximité
    cosinus comme un lien de sens serait fabriquer de la connaissance.

Deux autres frontières, rappelées ici parce qu'elles mordent sur ces routes :
``last_verified_at`` et ``confirmed_until`` sont NULL sur la totalité des atomes
(mécanisme non alimenté) : aucun événement « vérifié » n'apparaît dans la
chronologie, et c'est une absence, pas un calme. ``arac.scopes`` est inaccessible
au rôle read-only : les scopes sont déduits de ``memory_atoms.scope``.

LECTURE SEULE : uniquement des ``SELECT``/``WITH``, sur une connexion
``arac_readonly`` en ``default_transaction_read_only=on``, avec la garde lexicale
d'``entities._assert_read_only`` appliquée à chaque requête avant exécution.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse

from app.journal import raison, reduire, sha8
from control_center.cc_v1 import service
from control_center.cc_v1.entities import (
    PROJECTS,
    UN_RECU_PAR_RAPPEL,
    _clean,
    _failure,
    _one,
    _project_predicate,
    _project_rule,
    _readonly,
    _rows,
    _sql_text,
    _unavailable,
    union_ou_vide,
    links_dependency,
)

__all__ = [
    "register",
    "atom_story",
    "project_graph",
    "timeline",
    "MAX_GRAPH_NODES",
    "MAX_TIMELINE_EVENTS",
    "GRANULARITIES",
    "EVENT_TYPES",
]

logger = logging.getLogger("arac.cc.v1.lifestory")

_PREFIX = "/cc/v1"

#: Motif ``LIKE`` du séparateur de scope, passé en PARAMÈTRE. psycopg réserve
#: ``%`` au marquage des paramètres : un ``LIKE '%/%'`` littéral dans une requête
#: paramétrée casserait la liaison.
_SLASH = "%/%"

# ---------------------------------------------------------------------------
# Bornes dures. Elles ne sont pas des préférences : au-delà, une réponse cesse
# d'être lisible et une requête cesse d'être sûre. Chaque borne atteinte est
# SIGNALÉE dans la réponse — une troncature silencieuse est un mensonge.
# ---------------------------------------------------------------------------

#: Plafond dur du graphe de projet (mandat V2).
MAX_GRAPH_NODES = 400
#: Plafond dur des arêtes : 400 nœuds × 4 voisins sémantiques + l'ossature.
#: Si cette borne mord, elle emporte les arêtes SÉMANTIQUES en premier (les plus
#: lointaines d'abord) et jamais l'ossature ``contains``/``lineage`` : un graphe
#: tronqué doit rester un graphe connexe, pas une poussière de nœuds orphelins.
MAX_GRAPH_EDGES = 3000
#: Voisins sémantiques retenus PAR atome. Au-delà, le graphe devient une pelote.
GRAPH_NEIGHBOURS = 4
#: Distance cosinus au-delà de laquelle deux atomes ne se ressemblent plus assez
#: pour qu'une arête soit honnête. Constante déclarée, comme ``DUPLICATE_DISTANCE``
#: (0.10) dans la famille ``confiance`` — mais dix fois plus permissive, parce
#: qu'ici on cherche un VOISINAGE de sujet, pas un doublon.
GRAPH_MAX_DISTANCE = 0.35
#: Jours de croissance émis par le graphe. Les cumuls, eux, portent sur TOUTE
#: l'histoire du projet : on tronque l'affichage, jamais le calcul.
GRAPH_GROWTH_DAYS = 180

#: Plafond dur de la chronologie (mandat V2).
MAX_TIMELINE_EVENTS = 2000
#: Plafond des seaux : au-delà, la courbe n'est plus lisible et la requête coûte.
MAX_TIMELINE_BUCKETS = 750
#: Plage par défaut : 48 h — « rejouer hier » sans avoir à formuler une borne.
DEFAULT_TIMELINE_HOURS = 48
#: Plage maximale acceptée, granularité horaire comprise.
MAX_TIMELINE_DAYS = 400

#: Bornes de PLAUSIBILITÉ d'un instant servi par la chronologie.
#:
#: POURQUOI ELLES EXISTENT : ``datetime.fromisoformat('0001-01-01')`` RÉUSSIT, puis
#: ``fin - timedelta(hours=48)`` sous-déborde ``datetime.min`` et lève ``OverflowError``
#: — que ``_parse_instant`` n'attrapait pas, puisque l'erreur ne venait pas de la
#: lecture mais de la soustraction qui suit. ``/cc/v1/timeline?to=0001-01-01`` rendait
#: donc un HTTP 500 nu, en contradiction directe avec le contrat gravé dans la
#: docstring de ``timeline`` (« Ne lève jamais »), et l'écran Chronologie
#: (``app.js:2972`` passe ``q.to`` brut) n'affichait que « réponse HTTP 500 ».
#:
#: Une borne hors de ces limites n'est plus une erreur : c'est une ``notice``.
#: 1970 : aucune donnée du cerveau n'est antérieure à l'epoch. 2200 : au-delà, la
#: borne n'est pas une intention, c'est une faute de frappe ou une sonde.
INSTANT_MIN = datetime(1970, 1, 1, tzinfo=timezone.utc)
INSTANT_MAX = datetime(2200, 1, 1, tzinfo=timezone.utc)

#: Bornes des listes secondaires d'une histoire d'atome.
_STORY_CHAIN_LIMIT = 60
_STORY_QUERIES_LIMIT = 40
_STORY_SCOPES_LIMIT = 25
_STORY_TIMELINE_LIMIT = 200
_STORY_NEIGHBOURS = 8

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

#: UN RAPPEL, UN ÉVÉNEMENT. Le prédicat vit dans ``entities`` — écrit UNE fois,
#: partagé par la chronologie, la fiche d'atome, le graphe de projet et la fiche
#: de scope. Deux copies finiraient par diverger, et le cockpit compterait les
#: rappels de deux façons selon l'écran ouvert.
#:
#: Sans lui, TOUT ce module racontait la mémoire deux fois plus interrogée qu'elle
#: ne l'a été : 208 événements « rappel » pour 104 rappels réels sur 48 h, 424
#: « fois servi » pour 212 rappels sur l'atome le plus sollicité, et deux entrées
#: identiques dans la liste des requêtes d'une fiche d'atome — deux événements pour
#: un seul sujet, ce qui viole l'identité d'événement que cette vue promet.
_PREMIER_RECU = UN_RECU_PAR_RAPPEL

#: Ce que les trois routes de ce module disent de la couche de liens.
#:
#: POURQUOI CE N'EST PLUS UNE CONSTANTE
#: ------------------------------------
#: C'en était une, figée à l'import : ``dict(LINKS_UNAVAILABLE) | {…}``. Elle a
#: donc continué d'annoncer « le schéma n'a pas été interrogé » le jour où
#: ``LINKS_UNAVAILABLE`` a changé de sens — sur trois pages qui venaient
#: précisément d'interroger le schéma. Un texte d'indisponibilité calculé une
#: fois pour toutes est un texte qui ne peut pas suivre l'état qu'il décrit.
#:
#: La sonde est tirée sur la connexion déjà ouverte par la route : elle ne coûte
#: pas de connexion supplémentaire, et elle rend ce qu'elle a vu.
def _links(conn: Any) -> dict[str, Any]:
    return dict(links_dependency(conn)) | {
        "substitute": ("proximité vectorielle (embedding <=>) et appartenance de scope ou de tag — "
                       "aucune de ces arêtes n'est un lien déclaré par le cerveau"),
        "impact": ["arêtes explicites du graphe de projet",
                   "vue « orphelins du graphe »",
                   "degré de liaison d'un atome"],
    }


# ============================================================================
# L'HISTOIRE D'UN ATOME — /cc/v1/atoms/{id}/story
# ============================================================================
#
# ANOMALIE STRUCTURELLE, traitée ici :
# aucun chemin d'écriture n'alimente ``memory_atoms.supersedes`` : la colonne
# est donc NULL sur la totalité des atomes, quel que soit le cerveau. SEUL
# ``superseded_by`` est alimenté. Une remontée de lignée qui suivrait
# ``supersedes`` (l'arête « vers l'ancêtre ») ne trouverait donc JAMAIS
# d'ancêtre — elle afficherait « version initiale » pour toutes les versions 2
# et 3, ce qui est faux.
#
# La récursion ci-dessous suit donc les DEUX arêtes dans les deux sens :
#     parent → enfant  ssi  parent.superseded_by = enfant.id
#                       OU  enfant.supersedes    = parent.id
# Elle reste juste le jour où ``supersedes`` sera alimenté, et elle est juste
# aujourd'hui où il ne l'est pas.

_CHAIN_CTE = """
WITH RECURSIVE ancetres AS (
    SELECT a.id, a.supersedes, 0 AS hop
      FROM arac.memory_atoms a
     WHERE a.id = %(id)s::uuid
    UNION ALL
    SELECT p.id, p.supersedes, an.hop - 1
      FROM arac.memory_atoms p
      JOIN ancetres an ON (p.id = an.supersedes OR p.superseded_by = an.id)
     WHERE an.hop > -20
), descendances AS (
    SELECT a.id, a.superseded_by, 0 AS hop
      FROM arac.memory_atoms a
     WHERE a.id = %(id)s::uuid
    UNION ALL
    SELECT n.id, n.superseded_by, de.hop + 1
      FROM arac.memory_atoms n
      JOIN descendances de ON (n.id = de.superseded_by OR n.supersedes = de.id)
     WHERE de.hop < 20
), chaine AS (
    SELECT id, min(hop) AS hop
      FROM (SELECT id, hop FROM ancetres
            UNION ALL
            SELECT id, hop FROM descendances) t
     GROUP BY id
)"""


_STORY_IDENTITY = f"""
WITH usage AS (
    SELECT count(*)            AS served_count,
           min(cr.created_at)  AS first_served_at,
           max(cr.created_at)  AS last_served_at
      FROM arac.context_receipts cr
     WHERE cr.served_ids @> ARRAY[%(id)s::uuid]
       {_PREMIER_RECU}
)
SELECT a.id, a.kind, a.scope, a.key, a.status, a.version,
       a.confidence, a.confidence_score, a.tags, a.audit_source,
       a.node_id, a.session_id, a.created_at, a.updated_at, a.observed_at,
       a.last_verified_at, a.confirmed_until, a.supersedes, a.superseded_by,
       a.value, a.rationale, a.source_ref,
       length(a.value)                                   AS value_length,
       (a.embedding IS NOT NULL)                         AS has_embedding,
       (a.scope NOT LIKE %(slash)s)                      AS is_root_scoped,
       (a.updated_at > a.created_at + interval '1 second') AS retouche_sur_place,
       a.source_ref->>'conversation_uid'                 AS conversation_uid,
       a.source_ref->>'run_ref'                          AS run_id,
       c.title                                           AS conversation_title,
       c.source_type                                     AS conversation_source_type,
       c.curated_at                                      AS conversation_curated_at,
       c.atoms_generated                                 AS conversation_atoms_generated,
       r.id                                              AS cycle_id,
       r.slot_key                                        AS cycle_slot_key,
       r.trigger                                         AS cycle_trigger,
       r.status                                          AS cycle_status,
       r.model                                           AS cycle_model,
       r.started_at                                      AS cycle_started_at,
       r.ended_at                                        AS cycle_ended_at,
       r.items                                           AS cycle_items,
       r.atoms_created                                   AS cycle_atoms_created,
       r.atoms_superseded                                AS cycle_atoms_superseded,
       r.atoms_quarantined                               AS cycle_atoms_quarantined,
       r.est_input_tokens                                AS cycle_est_input_tokens,
       u.served_count, u.first_served_at, u.last_served_at,
       (u.served_count = 0)                              AS never_served,
       a.source_ref->>'curator_raw_id'                   AS legacy_raw_id,
       rc.node_id                                        AS legacy_node_id,
       rc.source_path                                    AS legacy_source_path,
       rc.message_count                                  AS legacy_message_count,
       rc.status                                         AS legacy_status,
       rc.received_at                                    AS legacy_received_at,
       lg.n_match                                        AS legacy_conversation_matches,
       cl.conversation_uid                               AS legacy_conversation_uid,
       cl.title                                          AS legacy_conversation_title
  FROM arac.memory_atoms a
  CROSS JOIN usage u
  LEFT JOIN arac.conversations c
         ON c.conversation_uid = a.source_ref->>'conversation_uid'
  /* PROVENANCE LEGACY. 1 097 atomes actifs portent un `curator_raw_id` sans
     `conversation_uid` : la fiche servait alors six `null` NUS pour leur naissance,
     contraire à la règle I2 (une absence se dit avec sa raison, son geste et son
     substitut) — et le substitut EXISTE, la capture brute est en base pour 1 093
     d'entre eux. Le pont est déterministe : curator_raw_id -> raw_conversations
     -> source_path contient le conversation_uid. Mesuré : 849 des 1 097 se
     résolvent SANS AMBIGUÏTÉ (0 cas à plusieurs correspondances).
     `n_match` est SERVI : un rattachement reconstruit ne doit jamais être présenté
     comme un rattachement déclaré, et une correspondance multiple doit se voir.
     `strpos` plutôt que LIKE : aucun signe pourcent dans une requête paramétrée
     (psycopg le lirait comme un marqueur), donc une preuve rejouable telle quelle. */
  LEFT JOIN arac.raw_conversations rc
         ON rc.id::text = a.source_ref->>'curator_raw_id'
  LEFT JOIN LATERAL (
        SELECT count(*)::int             AS n_match,
               min(c2.conversation_uid)  AS uid
          FROM arac.conversations c2
         WHERE a.source_ref->>'conversation_uid' IS NULL
           AND strpos(rc.source_path, c2.conversation_uid) > 0
  ) lg ON true
  LEFT JOIN arac.conversations cl
         ON lg.n_match = 1 AND cl.conversation_uid = lg.uid
  LEFT JOIN LATERAL (
        SELECT rr.id, rr.slot_key, rr.trigger, rr.status, rr.model, rr.started_at,
               rr.ended_at, rr.items, rr.atoms_created, rr.atoms_superseded,
               rr.atoms_quarantined, rr.est_input_tokens
          FROM arac.run_receipts rr
         WHERE rr.slot_key = a.source_ref->>'run_ref'
         ORDER BY rr.started_at DESC
         LIMIT 1
  ) r ON true
 WHERE a.id = %(id)s::uuid
 LIMIT 1"""


#: La chaîne de versions, du plus ancien ancêtre au plus jeune descendant, avec
#: la DIFFÉRENCE d'une version à l'autre calculée en SQL (``lag``). Aucun de ces
#: écarts n'est recalculé côté client : l'écran affiche la phrase telle quelle.
_STORY_CHAIN = _CHAIN_CTE + """
, detail AS (
    SELECT c.hop, a.id, a.version, a.status, a.kind, a.scope, a.key,
           a.confidence_score, a.created_at, a.updated_at,
           length(a.value)                                  AS taille,
           (coalesce(btrim(a.rationale), '') <> '')          AS porte_un_rationnel,
           a.source_ref->>'conversation_uid'                AS conversation_uid,
           a.source_ref->>'run_ref'                         AS run_id
      FROM chaine c
      JOIN arac.memory_atoms a ON a.id = c.id
), avec_precedent AS (
    SELECT d.*,
           lag(d.id)               OVER w AS id_avant,
           lag(d.taille)           OVER w AS taille_avant,
           lag(d.scope)            OVER w AS scope_avant,
           lag(d.kind)             OVER w AS kind_avant,
           lag(d.confidence_score) OVER w AS score_avant
      FROM detail d
    WINDOW w AS (ORDER BY d.hop, d.created_at)
)
SELECT hop, id, version, status, kind, scope, key, confidence_score,
       created_at, updated_at, taille, porte_un_rationnel,
       conversation_uid, run_id,
       (id = %(id)s::uuid) AS est_cet_atome,
       concat_ws(' · ',
           CASE WHEN id_avant IS NULL THEN 'version initiale'
                ELSE 'succede a ' || left(id_avant::text, 8) END,
           CASE WHEN taille_avant IS NULL THEN taille || ' caracteres'
                WHEN taille > taille_avant THEN '+' || (taille - taille_avant) || ' caracteres'
                WHEN taille < taille_avant THEN (taille - taille_avant) || ' caracteres'
                ELSE 'longueur inchangee' END,
           CASE WHEN scope_avant IS NOT NULL AND scope_avant <> scope
                THEN 'deplace de ' || scope_avant || ' vers ' || scope END,
           CASE WHEN kind_avant IS NOT NULL AND kind_avant <> kind
                THEN 'nature ' || kind_avant || ' vers ' || kind END,
           CASE WHEN score_avant IS NOT NULL AND score_avant <> confidence_score
                THEN 'confiance ' || score_avant || ' vers ' || confidence_score END
       ) AS diff_summary,
       '/cc/v1/atoms/' || id::text || '/story' AS href
  FROM avec_precedent
 ORDER BY hop, created_at
 LIMIT %(chain_limit)s"""


#: Les scopes qui ONT RÉELLEMENT SERVI cet atome. Ce n'est pas le scope où il est
#: rangé (une seule valeur, déjà dans l'identité) : c'est le filtre de scope des
#: requêtes qui l'ont fait remonter — donc les territoires qui en DÉPENDENT.
_STORY_SCOPES = f"""
SELECT coalesce(cr.scope_filter, '(aucun filtre de scope)') AS scope,
       count(*)             AS rappels,
       min(cr.created_at)   AS premier_rappel,
       max(cr.created_at)   AS dernier_rappel,
       count(DISTINCT cr.consumer) AS consommateurs,
       (cr.scope_filter IS NOT NULL) AS filtre_explicite
  FROM arac.context_receipts cr
 WHERE cr.served_ids @> ARRAY[%(id)s::uuid]
   {_PREMIER_RECU}
 GROUP BY coalesce(cr.scope_filter, '(aucun filtre de scope)'), (cr.scope_filter IS NOT NULL)
 ORDER BY 2 DESC
 LIMIT %(scopes_limit)s"""


_STORY_QUERIES = f"""
SELECT cr.created_at                                    AS at,
       cr.consumer,
       cr.final_band,
       cr.raw_band,
       cr.stop_reason,
       cr.scope_filter,
       cr.k_requested,
       cr.budget_k,
       cr.top1_distance_final,
       array_position(cr.served_ids, %(id)s::uuid)      AS rank,
       cardinality(cr.served_ids)                       AS servis_dans_ce_contexte
  FROM arac.context_receipts cr
 WHERE cr.served_ids @> ARRAY[%(id)s::uuid]
   {_PREMIER_RECU}
 ORDER BY cr.created_at DESC
 LIMIT %(queries_limit)s"""


_STORY_NEIGHBOURS_SQL = """
WITH moi AS (SELECT embedding FROM arac.memory_atoms WHERE id = %(id)s::uuid LIMIT 1)
SELECT a.id,
       a.key,
       a.scope,
       a.kind,
       a.status,
       round((a.embedding <=> (SELECT embedding FROM moi))::numeric, 4) AS distance,
       '/cc/v1/atoms/' || a.id::text || '/story' AS href
  FROM arac.memory_atoms a
 WHERE a.id <> %(id)s::uuid
   AND a.status = 'active'
   AND a.kind <> 'agent_message'
   AND a.embedding IS NOT NULL
   AND (SELECT embedding FROM moi) IS NOT NULL
 ORDER BY a.embedding <=> (SELECT embedding FROM moi)
 LIMIT %(neighbours)s"""


#: LA CHRONOLOGIE DE L'ATOME — naissance, retouches, remplacements, rappels —
#: assemblée et ordonnée EN SQL. Le navigateur reçoit une liste déjà datée,
#: déjà libellée, déjà munie de son lien : il n'a rien à déduire (G2).
_STORY_TIMELINE = _CHAIN_CTE + f"""
, evenements AS (
    SELECT a.created_at AS at,
           'naissance'  AS type,
           concat_ws(' ', 'Ne dans le cycle',
                     coalesce(a.source_ref->>'run_ref', '(cycle inconnu)'),
                     'a partir de',
                     coalesce(c.title, a.source_ref->>'conversation_uid',
                              '(source non tracee)')) AS label,
           CASE WHEN a.source_ref->>'conversation_uid' IS NOT NULL
                THEN '/cc/v1/conversations/' || (a.source_ref->>'conversation_uid')
                ELSE '/cc/v1/atoms/' || a.id::text END AS href
      FROM arac.memory_atoms a
      LEFT JOIN arac.conversations c
             ON c.conversation_uid = a.source_ref->>'conversation_uid'
     WHERE a.id = %(id)s::uuid

    UNION ALL

    SELECT a.updated_at,
           'retouche',
           'Contenu retouche sur place, sans nouvelle version',
           '/cc/v1/atoms/' || a.id::text
      FROM arac.memory_atoms a
     WHERE a.id = %(id)s::uuid
       AND a.updated_at > a.created_at + interval '1 second'
       AND a.superseded_by IS NULL

    UNION ALL

    SELECT a.updated_at,
           'remplacement',
           'Remplace par ' || left(a.superseded_by::text, 8),
           '/cc/v1/atoms/' || a.superseded_by::text || '/story'
      FROM arac.memory_atoms a
     WHERE a.id = %(id)s::uuid
       AND a.superseded_by IS NOT NULL

    UNION ALL

    SELECT v.created_at,
           CASE WHEN ch.hop < 0 THEN 'version_anterieure' ELSE 'version_posterieure' END,
           'Version ' || v.version || ' de la meme cle (' || v.status || ')',
           '/cc/v1/atoms/' || v.id::text || '/story'
      FROM chaine ch
      JOIN arac.memory_atoms v ON v.id = ch.id
     WHERE ch.hop <> 0

    UNION ALL

    SELECT cr.created_at,
           'rappel',
           concat_ws(' ', 'Servi a', cr.consumer, 'au rang',
                     array_position(cr.served_ids, %(id)s::uuid)::text,
                     '(bande ' || coalesce(cr.final_band, 'inconnue') || ')'),
           '/cc/v1/atoms/' || %(id)s::text
      FROM arac.context_receipts cr
     WHERE cr.served_ids @> ARRAY[%(id)s::uuid]
       {_PREMIER_RECU}
)
SELECT at, type, label, href
  FROM evenements
 WHERE at IS NOT NULL
 ORDER BY at
 LIMIT %(timeline_limit)s"""


def _projects_sql() -> tuple[str, dict[str, Any]]:
    """Les projets dont CET atome fait partie, selon les règles de projet déclarées.

    La règle est celle d'``entities.PROJECTS`` — importée, jamais recopiée : le
    graphe, la fiche projet et l'histoire d'un atome doivent répondre la même
    chose ou l'un des trois ment.
    """
    blocks: list[str] = []
    params: dict[str, Any] = {}
    for p in PROJECTS:
        pred, prm = _project_predicate(p, "a", f"pr_{p['id']}")
        params |= prm
        params[f"plab_{p['id']}"] = p["label"]
        params[f"pid_{p['id']}"] = p["id"]
        blocks.append(
            f"SELECT %(pid_{p['id']})s AS id, %(plab_{p['id']})s AS label,"
            f"       '/cc/v1/projects/' || %(pid_{p['id']})s AS href,"
            f"       '/cc/v1/projects/' || %(pid_{p['id']})s || '/graph' AS graph_href"
            f"  FROM arac.memory_atoms a WHERE a.id = %(id)s::uuid AND {pred}"
        )
    sql = union_ou_vide(
        blocks,
        (("id", "text"), ("label", "text"), ("href", "text"), ("graph_href", "text")),
    ) + "\nLIMIT 8"
    return sql, params


def _birth_conversation(row: dict[str, Any]) -> dict[str, Any]:
    """La conversation d'origine d'un atome — ou l'absence, DITE (règle I2).

    Trois cas, jamais un ``null`` nu :

    1. ``source_ref.conversation_uid`` est présent : rattachement DÉCLARÉ, servi
       tel quel avec ``voie = 'source_ref'``.
    2. Provenance legacy (``curator_raw_id`` seul) résolue sans ambiguïté par
       ``raw_conversations.source_path`` : rattachement RECONSTRUIT, servi avec
       ``voie = 'legacy_source_path'`` et ``declare = false``. Un lien reconstruit
       n'est jamais présenté comme un lien déclaré — c'est le point du champ.
    3. Rien de résoluble : ``unavailable`` avec sa raison, le geste qui la lèverait
       et le SUBSTITUT réellement disponible (la capture brute : nœud, chemin,
       nombre de messages, statut). Avant, ce cas servait six ``null`` nus alors
       que la ligne ``raw_conversations`` était là, en base, pour 1 093 des 1 097
       atomes concernés.
    """
    uid = row.get("conversation_uid")
    if uid:
        return {
            "state": "ok",
            "voie": "source_ref",
            "declare": True,
            "conversation_uid": uid,
            "title": row.get("conversation_title"),
            "href": f"/cc/v1/conversations/{uid}",
        }

    raw_id = row.get("legacy_raw_id")
    substitut = {
        "raw_id": raw_id,
        "node_id": row.get("legacy_node_id"),
        "source_path": row.get("legacy_source_path"),
        "message_count": row.get("legacy_message_count"),
        "status": row.get("legacy_status"),
        "received_at": row.get("legacy_received_at"),
    } if row.get("legacy_source_path") else None

    n_match = row.get("legacy_conversation_matches") or 0
    if n_match == 1 and row.get("legacy_conversation_uid"):
        legacy_uid = row["legacy_conversation_uid"]
        return {
            "state": "ok",
            "voie": "legacy_source_path",
            "declare": False,
            "conversation_uid": legacy_uid,
            "title": row.get("legacy_conversation_title"),
            "href": f"/cc/v1/conversations/{legacy_uid}",
            "note": ("rattachement RECONSTRUIT, non déclaré : cet atome ne porte qu'un "
                     "curator_raw_id ; la capture brute correspondante cite ce "
                     "conversation_uid dans son source_path, et une seule conversation "
                     "y correspond"),
            "substitute": substitut,
        }

    if n_match > 1:
        raison = (f"la capture brute de cet atome cite {n_match} conversations : "
                  "le rattachement serait un choix, pas une lecture")
    elif raw_id:
        raison = ("cet atome porte une provenance legacy (curator_raw_id) sans "
                  "conversation_uid, et sa capture brute ne cite aucune conversation connue")
    else:
        raison = ("cet atome ne déclare aucune provenance de conversation : ni "
                  "conversation_uid, ni curator_raw_id")

    return {
        "state": "unavailable",
        "voie": None,
        "declare": False,
        "reason": raison,
        "gesture": ("résoudre curator_raw_id contre arac.raw_conversations, puis "
                    "arac.conversations par le conversation_uid cité dans source_path"),
        "substitute": substitut or ("aucune capture brute non plus : la provenance de cet "
                                    "atome est perdue"),
    }


def atom_story(atom_id: str) -> dict[str, Any]:
    """L'histoire COMPLÈTE d'un atome, en un seul appel.

    Naissance (conversation, cycle, nœud), enrichissements version par version
    avec leur différence, lignée remontée dans les deux sens, scopes et projets
    qui en dépendent, usage réel, voisinage sémantique, chronologie ordonnée.

    Ne lève jamais : un identifiant inconnu rend ``state='unavailable'`` avec sa
    raison ET la requête qui n'a rien trouvé.
    """
    atom_id = _clean(atom_id) or ""
    if not atom_id:
        return _unavailable("identifiant d'atome vide")
    if not _UUID_RE.fullmatch(atom_id):
        return _unavailable(
            f"{atom_id!r} n'est pas un identifiant d'atome (uuid attendu)", id=atom_id)

    projects_sql, project_params = _projects_sql()
    params: dict[str, Any] = {
        "id": atom_id,
        "slash": _SLASH,
        "chain_limit": _STORY_CHAIN_LIMIT,
        "queries_limit": _STORY_QUERIES_LIMIT,
        "scopes_limit": _STORY_SCOPES_LIMIT,
        "timeline_limit": _STORY_TIMELINE_LIMIT,
        "neighbours": _STORY_NEIGHBOURS,
    }
    started = time.perf_counter()
    try:
        with _readonly() as conn:
            row = _one(conn, _STORY_IDENTITY, params, where="story.identity")
            if row is None:
                return _unavailable(
                    f"aucun atome ne porte l'identifiant {atom_id}",
                    id=atom_id,
                    evidence={"kind": "sql",
                              "sql": _sql_text(conn, _STORY_IDENTITY, params),
                              "label": "la requête qui n'a rien trouvé"},
                )
            chain = _rows(conn, _STORY_CHAIN, params, where="story.chain")
            scopes = _rows(conn, _STORY_SCOPES, params, where="story.scopes")
            queries = _rows(conn, _STORY_QUERIES, params, where="story.queries")
            events = _rows(conn, _STORY_TIMELINE, params, where="story.timeline")
            projects = _rows(conn, projects_sql, params | project_params,
                             where="story.projects")
            queries_evidence = [
                _sql_text(conn, _STORY_IDENTITY, params),
                _sql_text(conn, _STORY_CHAIN, params),
                _sql_text(conn, _STORY_SCOPES, params),
                _sql_text(conn, _STORY_QUERIES, params),
                _sql_text(conn, _STORY_TIMELINE, params),
                _sql_text(conn, projects_sql, params | project_params),
            ]
            identity_evidence = queries_evidence[0]
            try:
                neighbours = _rows(conn, _STORY_NEIGHBOURS_SQL, params,
                                   where="story.neighbours")
                neighbours_state: dict[str, Any] = {"state": "ok", "reason": None}
                queries_evidence.append(_sql_text(conn, _STORY_NEIGHBOURS_SQL, params))
            except Exception as exc:  # noqa: BLE001 — organe optionnel : il se dit, il n'abat pas la fiche
                # Message autoporteur : `extra=` n'est rendu par aucun formateur
                # de ce service (cf. entities._failure).
                logger.warning("cc_v1.story_neighbours_failed atom_id=%s raison=%s",
                               atom_id, raison(exc),
                               extra={"atom_id": atom_id, "error": type(exc).__name__},
                               exc_info=True)
                neighbours = []
                neighbours_state = {
                    "state": "unavailable",
                    "reason": f"voisinage sémantique indisponible ({raison(exc)})",
                }
            # La sonde des liens vit ICI, dans le bloc où la connexion existe.
            links = _links(conn)
    except Exception as exc:  # noqa: BLE001
        return _failure(f"story:{atom_id}", exc)

    if not row.get("has_embedding") and neighbours_state["state"] == "ok" and not neighbours:
        neighbours_state = {"state": "unavailable",
                            "reason": "cet atome n'a pas de plongement : aucun voisin calculable"}

    # Découpage de la chaîne — un tri de listes déjà ordonnées par le SQL, pas un
    # calcul : Python ne dérive aucune valeur, il range ce que PostgreSQL a rendu.
    ancestors = [r for r in chain if (r.get("hop") or 0) < 0]
    descendants = [r for r in chain if (r.get("hop") or 0) > 0]

    identity_keys = ("id", "kind", "scope", "key", "status", "version", "confidence",
                     "confidence_score", "tags", "audit_source", "node_id", "session_id",
                     "created_at", "updated_at", "observed_at", "value_length",
                     "has_embedding", "is_root_scoped", "retouche_sur_place")

    return {
        "state": "ok",
        "identity": {k: row.get(k) for k in identity_keys} | {
            "href": f"/cc/v1/atoms/{atom_id}",
            "scope_href": f"/cc/v1/atoms?scope={row.get('scope')}",
        },
        "content": {"value": row.get("value"), "rationale": row.get("rationale")},
        "birth": {
            "at": row.get("created_at"),
            "conversation_uid": row.get("conversation_uid"),
            "conversation_title": row.get("conversation_title"),
            "conversation_source_type": row.get("conversation_source_type"),
            "conversation_curated_at": row.get("conversation_curated_at"),
            "conversation_atoms_generated": row.get("conversation_atoms_generated"),
            "conversation_href": (f"/cc/v1/conversations/{row.get('conversation_uid')}"
                                  if row.get("conversation_uid") else None),
            "conversation": _birth_conversation(row),
            "run_id": row.get("run_id"),
            "node_id": row.get("node_id"),
            "session_id": row.get("session_id"),
            "audit_source": row.get("audit_source"),
            "source_ref": row.get("source_ref"),
            "cycle": {
                "id": row.get("cycle_id"),
                "slot_key": row.get("cycle_slot_key"),
                "trigger": row.get("cycle_trigger"),
                "status": row.get("cycle_status"),
                "model": row.get("cycle_model"),
                "started_at": row.get("cycle_started_at"),
                "ended_at": row.get("cycle_ended_at"),
                "items": row.get("cycle_items"),
                "atoms_created": row.get("cycle_atoms_created"),
                "atoms_superseded": row.get("cycle_atoms_superseded"),
                "atoms_quarantined": row.get("cycle_atoms_quarantined"),
                "est_input_tokens": row.get("cycle_est_input_tokens"),
            } if row.get("cycle_id") is not None else {
                "state": "unavailable",
                "reason": ("aucun reçu de cycle ne porte ce run_ref : "
                           + (f"source_ref.run_ref = {row.get('run_id')!r}"
                              if row.get("run_id")
                              else "cet atome ne déclare aucun run_ref (provenance antérieure "
                                   "au contrat cortex-dispose/1)")),
                "substitute": "la conversation d'origine, si elle est tracée",
            },
        },
        # Les enrichissements SONT la chaîne de versions : chaque maillon porte sa
        # différence avec le précédent, calculée en SQL.
        "enrichments": [
            {"version": r.get("version"), "at": r.get("created_at"),
             "id": r.get("id"), "status": r.get("status"),
             "conversation_uid": r.get("conversation_uid"), "run_id": r.get("run_id"),
             "diff_summary": r.get("diff_summary"), "hop": r.get("hop"),
             "est_cet_atome": r.get("est_cet_atome"), "href": r.get("href")}
            for r in chain
        ],
        "enrichments_note": (
            "un « enrichissement » est une VERSION de la même clé ; la retouche sur "
            "place (updated_at > created_at) est signalée à part dans identity"),
        "lineage": {
            "ancestors": ancestors,
            "descendants": descendants,
            "supersedes": row.get("supersedes"),
            "superseded_by": row.get("superseded_by"),
            "depth": len(chain),
            # La note affirmait « NULL sur la totalité des atomes » : le
            # compte d'une base, gravé. Ce qui est vrai partout, et vérifiable
            # sans connexion, c'est qu'aucune écriture du dépôt ne renseigne
            # cette colonne — les deux INSERT de app/routers/atoms.py ne la
            # citent pas. La remontée par l'arête inverse reste donc la seule
            # qui trouve un ancêtre, et le restera tant que ce sera vrai.
            "note": ("aucune écriture de ce dépôt ne renseigne "
                     "memory_atoms.supersedes : la lignée est remontée par l'arête "
                     "inverse (superseded_by), sans quoi aucun ancêtre ne serait "
                     "jamais trouvé"),
        },
        "scopes_using": scopes,
        "projects_depending": [p | {"rule": _project_rule(_by_project_id(p.get("id")))}
                               for p in projects if _by_project_id(p.get("id"))],
        "usage": {
            "served_count": row.get("served_count"),
            "first_served_at": row.get("first_served_at"),
            "last_served_at": row.get("last_served_at"),
            "never_served": row.get("never_served"),
            "queries": queries,
            "queries_truncated": len(queries) >= _STORY_QUERIES_LIMIT,
        },
        "neighbours": neighbours,
        "neighbours_state": neighbours_state | {
            "operator": "pgvector <=> (distance cosinus)",
            "limit": _STORY_NEIGHBOURS,
            "note": "un voisin n'est pas un lien : c'est une ressemblance calculée",
        },
        "links": links,
        "verification": {
            "state": "unavailable",
            "reason": ("aucun agent de ce dépôt n'écrit last_verified_at ni "
                       "confirmed_until : le mécanisme de vérification n'existe "
                       "pas encore côté moteur"),
            "gesture": "brancher un vérificateur qui écrive last_verified_at / confirmed_until",
            "substitute": "la date du dernier rappel (usage.last_served_at)",
        },
        "timeline": events,
        "timeline_truncated": len(events) >= _STORY_TIMELINE_LIMIT,
        "evidence": {
            "kind": "sql",
            "sql": identity_evidence,
            "label": "cet atome, sa naissance et son usage, tels que la base les décrit",
            "queries": queries_evidence,
        },
        "computed_at": service._now(),
        "duration_ms": service._ms(started),
    }


def _by_project_id(pid: Any) -> dict[str, Any] | None:
    for p in PROJECTS:
        if p["id"] == pid:
            return p
    return None


# ============================================================================
# LE GRAPHE D'UN PROJET — /cc/v1/projects/{id}/graph
# ============================================================================
#
# Un projet vu comme un TISSU : le projet, ses scopes, ses thèmes (les tags
# partagés) et ses atomes, reliés par trois natures d'arête — et trois seulement,
# parce que ce sont les trois seules que la base sait justifier :
#
#   contains  appartenance : projet → scope, scope → atome, thème → atome.
#             Factuelle, non discutable.
#   lineage   supersession : atome → atome. Le seul lien que le cerveau
#             enregistre RÉELLEMENT entre deux atomes.
#   semantic  proximité vectorielle (embedding <=>), bornée aux GRAPH_NEIGHBOURS
#             plus proches voisins de chaque atome et à GRAPH_MAX_DISTANCE.
#             CE N'EST PAS UN LIEN : c'est une ressemblance. La réponse le dit.
#
# Les membres incluent les atomes ``superseded`` — sans eux, aucune arête
# ``lineage`` n'existerait (un remplacé n'est plus actif) et le graphe
# raconterait un projet sans mémoire de ses corrections.

_GRAPH_MEMBERS = """
WITH membres AS (
    SELECT a.id, a.kind, a.scope, a.key, a.tags, a.status,
           a.confidence_score, a.created_at, a.updated_at, a.superseded_by,
           a.embedding
      FROM arac.memory_atoms a
     WHERE a.status IN ('active', 'superseded')
       AND a.kind <> 'agent_message'
       AND {predicate}
), rappels AS (
    SELECT s.id, count(*) AS rappels, max(cr.created_at) AS dernier_rappel
      FROM arac.context_receipts cr, unnest(cr.served_ids) AS s(id)
     WHERE s.id IN (SELECT id FROM membres)
       """ + _PREMIER_RECU + """
     GROUP BY s.id
), retenus AS (
    SELECT m.*, coalesce(r.rappels, 0) AS rappels, r.dernier_rappel,
           row_number() OVER (ORDER BY coalesce(r.rappels, 0) DESC, m.created_at DESC) AS rang
      FROM membres m
      LEFT JOIN rappels r ON r.id = m.id
), scopes AS (
    SELECT scope, count(*) AS poids, min(created_at) AS premier, max(created_at) AS dernier
      FROM retenus GROUP BY scope
), themes AS (
    SELECT t AS theme, count(*) AS poids, min(r.created_at) AS premier, max(r.created_at) AS dernier
      FROM retenus r, unnest(coalesce(r.tags, '{{}}'::text[])) AS t
     GROUP BY t
    HAVING count(*) >= 2
     ORDER BY count(*) DESC, t
     LIMIT %(themes_max)s
), budget AS (
    SELECT greatest(%(nodes_max)s
                    - 1
                    - (SELECT count(*) FROM scopes)
                    - (SELECT count(*) FROM themes), 1) AS atomes_max
), atomes AS (
    SELECT * FROM retenus WHERE rang <= (SELECT atomes_max FROM budget)
)"""


_GRAPH_NODES = _GRAPH_MEMBERS + """
SELECT 'project:' || %(pid)s                        AS id,
       'project'                                    AS kind,
       %(plabel)s                                   AS label,
       (SELECT count(*) FROM retenus)               AS weight,
       (SELECT min(created_at) FROM retenus)        AS first_at,
       (SELECT max(created_at) FROM retenus)        AS last_at,
       NULL::text                                   AS scope,
       NULL::text                                   AS atom_kind,
       NULL::text                                   AS status,
       '/cc/v1/projects/' || %(pid)s                AS href
UNION ALL
SELECT 'scope:' || scope, 'scope', scope, poids, premier, dernier,
       scope, NULL, NULL, '/cc/v1/atoms?scope=' || scope
  FROM scopes
UNION ALL
SELECT 'theme:' || theme, 'theme', theme, poids, premier, dernier,
       NULL, NULL, NULL, '/cc/v1/atoms?q=' || theme
  FROM themes
UNION ALL
SELECT 'atom:' || id::text, 'atom', key, rappels, created_at, updated_at,
       scope, kind, status, '/cc/v1/atoms/' || id::text || '/story'
  FROM atomes
 ORDER BY 2, 4 DESC, 3
 LIMIT %(nodes_hard_max)s"""


_GRAPH_EDGES = _GRAPH_MEMBERS + """
, paires AS (
    SELECT x.id AS gauche, y.id AS droite,
           (x.embedding <=> y.embedding) AS d,
           row_number() OVER (PARTITION BY x.id
                              ORDER BY x.embedding <=> y.embedding) AS rg
      FROM atomes x
      JOIN atomes y ON x.id <> y.id
     WHERE x.embedding IS NOT NULL AND y.embedding IS NOT NULL
), semantiques AS (
    SELECT DISTINCT ON (least(gauche, droite), greatest(gauche, droite))
           'atom:' || least(gauche, droite)::text   AS source,
           'atom:' || greatest(gauche, droite)::text AS target,
           round(d::numeric, 4)                      AS distance
      FROM paires
     WHERE rg <= %(voisins)s AND d <= %(distance_max)s
     ORDER BY least(gauche, droite), greatest(gauche, droite), d
)
SELECT source, target, kind, weight, distance
  FROM (
        SELECT 'project:' || %(pid)s AS source, 'scope:' || scope AS target,
               'contains' AS kind, poids AS weight, NULL::numeric AS distance,
               1 AS priorite
          FROM scopes
        UNION ALL
        SELECT 'scope:' || a.scope, 'atom:' || a.id::text, 'contains', 1, NULL, 1
          FROM atomes a
        UNION ALL
        SELECT 'theme:' || t, 'atom:' || a.id::text, 'contains', 1, NULL, 2
          FROM atomes a, unnest(coalesce(a.tags, '{{}}'::text[])) AS t
         WHERE t IN (SELECT theme FROM themes)
        UNION ALL
        SELECT 'atom:' || a.id::text, 'atom:' || a.superseded_by::text, 'lineage', 1, NULL, 1
          FROM atomes a
         WHERE a.superseded_by IN (SELECT id FROM atomes)
        UNION ALL
        SELECT source, target, 'semantic', 1, distance, 3
          FROM semantiques
  ) t
 ORDER BY priorite, distance NULLS FIRST, source, target
 LIMIT %(edges_max)s"""


#: La croissance du projet, CUMULATIVE sur toute son histoire, émise sur la
#: dernière fenêtre seulement. On tronque l'affichage, jamais le calcul : un
#: cumul calculé sur une fenêtre glissante mentirait sur la taille du projet.
_GRAPH_GROWTH = _GRAPH_MEMBERS + """
, bornes AS (
    SELECT date_trunc('day', min(created_at)) AS debut,
           date_trunc('day', now())           AS fin
      FROM retenus
), grille AS (
    SELECT generate_series((SELECT debut FROM bornes),
                           (SELECT fin FROM bornes),
                           interval '1 day')::date AS jour
     WHERE (SELECT debut FROM bornes) IS NOT NULL
)
SELECT g.jour,
       (SELECT count(*) FROM retenus r WHERE r.created_at::date <= g.jour) AS atomes,
       (SELECT count(DISTINCT r.scope) FROM retenus r WHERE r.created_at::date <= g.jour)
       + (SELECT count(*) FROM retenus r WHERE r.created_at::date <= g.jour)
       + 1                                                                 AS noeuds
  FROM grille g
 WHERE g.jour > (SELECT fin FROM bornes)::date - %(growth_days)s
 ORDER BY g.jour
 LIMIT %(growth_days)s"""


_GRAPH_TOTALS = _GRAPH_MEMBERS + """
SELECT (SELECT count(*) FROM retenus)                          AS membres,
       (SELECT count(*) FROM retenus WHERE status = 'active')  AS membres_actifs,
       (SELECT count(*) FROM scopes)                           AS scopes,
       (SELECT count(*) FROM themes)                           AS themes,
       (SELECT count(*) FROM atomes)                           AS atomes_retenus,
       (SELECT atomes_max FROM budget)                         AS budget_atomes,
       1 + (SELECT count(*) FROM scopes) + (SELECT count(*) FROM themes)
         + (SELECT count(*) FROM retenus)                      AS noeuds_theoriques,
       (SELECT count(*) FROM retenus WHERE embedding IS NULL)  AS sans_plongement,
       (SELECT min(created_at) FROM retenus)                   AS premier_atome,
       (SELECT max(created_at) FROM retenus)                   AS dernier_atome
 LIMIT 1"""


def project_graph(project_id: str, max_nodes: int = MAX_GRAPH_NODES) -> dict[str, Any]:
    """Le projet comme graphe vivant : nœuds, arêtes, croissance, troncature.

    Ne lève jamais : un projet inconnu rend ``state='unavailable'`` avec la liste
    des identifiants valides.
    """
    pid = _clean(project_id) or ""
    project = _by_project_id(pid)
    if project is None:
        return _unavailable(
            f"aucun projet ne porte l'identifiant {pid!r}",
            id=pid,
            known=[p["id"] for p in PROJECTS],
            hint="les projets sont des VUES déclarées côté serveur, pas des dossiers",
        )

    nodes_max = max(8, min(int(max_nodes or MAX_GRAPH_NODES), MAX_GRAPH_NODES))
    predicate, pred_params = _project_predicate(project, "a", "g")
    params: dict[str, Any] = pred_params | {
        "pid": project["id"],
        "plabel": project["label"],
        "nodes_max": nodes_max,
        "nodes_hard_max": nodes_max,
        "themes_max": 20,
        "voisins": GRAPH_NEIGHBOURS,
        "distance_max": GRAPH_MAX_DISTANCE,
        "edges_max": MAX_GRAPH_EDGES,
        "growth_days": GRAPH_GROWTH_DAYS,
    }
    nodes_sql = _GRAPH_NODES.format(predicate=predicate)
    edges_sql = _GRAPH_EDGES.format(predicate=predicate)
    growth_sql = _GRAPH_GROWTH.format(predicate=predicate)
    totals_sql = _GRAPH_TOTALS.format(predicate=predicate)

    started = time.perf_counter()
    try:
        with _readonly() as conn:
            totals = _one(conn, totals_sql, params, where="graph.totals") or {}
            nodes = _rows(conn, nodes_sql, params, where="graph.nodes")
            growth = _rows(conn, growth_sql, params, where="graph.growth")
            evidence_sql = _sql_text(conn, nodes_sql, params)
            queries_evidence = [
                evidence_sql,
                _sql_text(conn, totals_sql, params),
                _sql_text(conn, growth_sql, params),
            ]
            try:
                edges = _rows(conn, edges_sql, params, where="graph.edges")
                edges_state: dict[str, Any] = {"state": "ok", "reason": None}
                queries_evidence.append(_sql_text(conn, edges_sql, params))
            except Exception as exc:  # noqa: BLE001 — pgvector est un organe optionnel
                # Message autoporteur : `extra=` n'est rendu par aucun formateur
                # de ce service (cf. entities._failure).
                # Le nom d'un projet est écrit par le propriétaire dans
                # `config/projects.toml` : c'est un pan de sa vie, comme un
                # domaine. Empreinte, donc — cf. app/journal.py.
                logger.warning("cc_v1.graph_edges_failed project_sha8=%s raison=%s",
                               sha8(pid), raison(exc),
                               extra={"project_sha8": sha8(pid),
                                      "error": type(exc).__name__},
                               exc_info=True)
                edges = []
                edges_state = {
                    "state": "unavailable",
                    "reason": f"arêtes indisponibles ({raison(exc)})",
                }
            # Idem : le constat se fait sur la connexion du graphe.
            links = _links(conn)
    except Exception as exc:  # noqa: BLE001
        return _failure(f"graph:{pid}", exc)

    shown = len(nodes)
    total = totals.get("noeuds_theoriques")
    return {
        "state": "ok",
        "project": {"id": project["id"], "label": project["label"],
                    "href": f"/cc/v1/projects/{project['id']}",
                    "rule": _project_rule(project)},
        "nodes": nodes,
        "edges": edges,
        "edges_state": edges_state,
        "edges_provenance": {
            "contains": "appartenance de scope ou de tag — factuelle",
            "lineage": ("supersession (memory_atoms.superseded_by) — le SEUL lien que le "
                        "cerveau enregistre réellement entre deux atomes"),
            "semantic": (f"proximité vectorielle : les {GRAPH_NEIGHBOURS} plus proches voisins "
                         f"de chaque atome, distance cosinus <= {GRAPH_MAX_DISTANCE}"),
            # L'avertissement porte sur CE graphe, pas sur l'état d'une base :
            # ce graphe-ci est construit par ressemblance, quoi que contienne
            # arac.atom_links. Affirmer en plus que la table n'existe pas
            # ajoutait une affirmation jamais vérifiée à un avertissement juste.
            "avertissement": ("aucune arête de ce graphe n'est un lien DÉCLARÉ : il est "
                              "construit par proximité vectorielle, pas lu depuis "
                              "arac.atom_links. Une proximité cosinus est une "
                              "ressemblance, pas une relation de sens."),
            "operator": "pgvector <=> (distance cosinus)",
        },
        "growth": growth,
        "growth_window_days": GRAPH_GROWTH_DAYS,
        "growth_note": ("cumuls calculés sur TOUTE l'histoire du projet et sur TOUS ses "
                        "membres — pas seulement sur les nœuds retenus après troncature — "
                        f"puis émis sur la dernière fenêtre de {GRAPH_GROWTH_DAYS} jours. "
                        "La dernière valeur de `noeuds` peut donc dépasser len(nodes) : "
                        "l'une mesure le projet, l'autre ce qu'on en dessine."),
        "truncated": {
            "applied": bool(total is not None and shown < total),
            "shown": shown,
            "total": total,
            "limit": nodes_max,
            "kept": ("les atomes les plus rappelés d'abord, puis les plus récents ; "
                     "le projet, ses scopes et ses thèmes sont toujours conservés"),
            "edges_shown": len(edges),
            "edges_limit": MAX_GRAPH_EDGES,
            "edges_applied": len(edges) >= MAX_GRAPH_EDGES,
            "edges_kept": ("l'ossature d'abord (contains, lineage), les arêtes sémantiques "
                           "ensuite, de la plus proche à la plus lointaine"),
        },
        "totals": totals,
        "links": links,
        "evidence": {"kind": "sql", "sql": evidence_sql,
                     "label": "les nœuds du graphe, tels que la base les produit",
                     "queries": queries_evidence},
        "computed_at": service._now(),
        "duration_ms": service._ms(started),
    }


# ============================================================================
# LA CHRONOLOGIE REJOUABLE — /cc/v1/timeline
# ============================================================================
#
# « Rejouer hier » : bornes libres, granularité réglable, événements ordonnés du
# plus ancien au plus récent — l'ordre d'un rejeu, pas celui d'un fil d'actualité.
#
# Les MESSAGES ne produisent pas d'événement : 2 969 messages sont entrés dans
# les 48 dernières heures ; ils noieraient les 9 atomes nés dans le même temps.
# Ils sont comptés dans les seaux, où leur volume est l'information utile, et
# absents des événements, où leur nombre serait du bruit. Cette asymétrie est
# déclarée dans la réponse (``events_note``) plutôt que subie.

#: Granularités offertes. Le client ne devine ni le nom du pas ni son intervalle :
#: ils sont servis. Aucune valeur de l'utilisateur n'entre dans le SQL — la clé
#: sert d'index dans ce dictionnaire, et c'est TOUT.
GRANULARITIES: dict[str, dict[str, str]] = {
    "hour": {"trunc": "hour", "step": "1 hour", "label": "heure par heure"},
    "day": {"trunc": "day", "step": "1 day", "label": "jour par jour"},
    "week": {"trunc": "week", "step": "1 week", "label": "semaine par semaine"},
}

_BUCKETS_SQL = """
WITH grille AS (
    SELECT generate_series(
               date_trunc(%(grain)s, %(debut)s::timestamptz),
               greatest(
                   date_trunc(%(grain)s, %(fin)s::timestamptz - interval '1 microsecond'),
                   date_trunc(%(grain)s, %(debut)s::timestamptz)),
               %(pas)s::interval) AS at
), atomes AS (
    SELECT date_trunc(%(grain)s, created_at) AS at, count(*) AS n
      FROM arac.memory_atoms
     WHERE kind <> 'agent_message'
       AND created_at >= %(debut)s::timestamptz AND created_at < %(fin)s::timestamptz
     GROUP BY 1
), remplaces AS (
    SELECT date_trunc(%(grain)s, updated_at) AS at, count(*) AS n
      FROM arac.memory_atoms
     WHERE status = 'superseded'
       AND updated_at >= %(debut)s::timestamptz AND updated_at < %(fin)s::timestamptz
     GROUP BY 1
), absorbees AS (
    SELECT date_trunc(%(grain)s, created_at) AS at, count(*) AS n
      FROM arac.conversations
     WHERE created_at >= %(debut)s::timestamptz AND created_at < %(fin)s::timestamptz
     GROUP BY 1
), curees AS (
    SELECT date_trunc(%(grain)s, curated_at) AS at, count(*) AS n
      FROM arac.conversations
     WHERE curated_at >= %(debut)s::timestamptz AND curated_at < %(fin)s::timestamptz
     GROUP BY 1
), cycles AS (
    SELECT date_trunc(%(grain)s, started_at) AS at,
           count(*) AS n,
           count(*) FILTER (WHERE status = 'quarantined') AS quarantaine
      FROM arac.run_receipts
     WHERE started_at >= %(debut)s::timestamptz AND started_at < %(fin)s::timestamptz
     GROUP BY 1
), rappels AS (
    SELECT date_trunc(%(grain)s, cr.created_at) AS at, count(*) AS n
      FROM arac.context_receipts cr
     WHERE cr.created_at >= %(debut)s::timestamptz AND cr.created_at < %(fin)s::timestamptz
       """ + _PREMIER_RECU + """
     GROUP BY 1
), messages AS (
    SELECT date_trunc(%(grain)s, received_at) AS at, count(*) AS n
      FROM arac.raw_messages
     WHERE received_at >= %(debut)s::timestamptz AND received_at < %(fin)s::timestamptz
     GROUP BY 1
)
SELECT g.at,
       coalesce(a.n, 0)   AS atoms_created,
       coalesce(rp.n, 0)  AS atoms_superseded,
       coalesce(ab.n, 0)  AS conversations_absorbed,
       coalesce(cu.n, 0)  AS conversations_curated,
       coalesce(cy.n, 0)  AS cycles,
       coalesce(cy.quarantaine, 0) AS cycles_quarantined,
       coalesce(rc.n, 0)  AS recalls,
       coalesce(ms.n, 0)  AS messages
  FROM grille g
  LEFT JOIN atomes     a  ON a.at  = g.at
  LEFT JOIN remplaces  rp ON rp.at = g.at
  LEFT JOIN absorbees  ab ON ab.at = g.at
  LEFT JOIN curees     cu ON cu.at = g.at
  LEFT JOIN cycles     cy ON cy.at = g.at
  LEFT JOIN rappels    rc ON rc.at = g.at
  LEFT JOIN messages   ms ON ms.at = g.at
 ORDER BY g.at
 LIMIT %(buckets_max)s"""


#: Les branches d'événements. Chaque clé est un TYPE offert au client ; le
#: paramètre ``types`` n'est jamais interpolé — il sert d'index dans ce
#: dictionnaire, exactement comme une clé de métrique dans le registre.
EVENT_TYPES: tuple[str, ...] = (
    "atome_cree", "atome_remplace", "conversation_absorbee",
    "conversation_curee", "cycle", "rappel",
)

_EVENT_SQL: dict[str, str] = {
    "atome_cree": """
    SELECT a.created_at AS at,
           'atome_cree' AS type,
           'atom'       AS subject_kind,
           a.id::text   AS subject_id,
           a.key        AS subject_label,
           jsonb_build_object(
               'kind', a.kind, 'scope', a.scope, 'version', a.version,
               'confidence_score', a.confidence_score,
               'taille', length(a.value),
               'invisible_au_rappel', (a.scope NOT LIKE %(slash)s),
               'run_ref', a.source_ref->>'run_ref',
               'conversation_uid', a.source_ref->>'conversation_uid') AS measures,
           '/cc/v1/atoms/' || a.id::text || '/story' AS href
      FROM arac.memory_atoms a
     WHERE a.kind <> 'agent_message'
       AND a.created_at >= %(debut)s::timestamptz AND a.created_at < %(fin)s::timestamptz""",

    "atome_remplace": """
    SELECT a.updated_at, 'atome_remplace', 'atom', a.id::text, a.key,
           jsonb_build_object(
               'kind', a.kind, 'scope', a.scope, 'version', a.version,
               'successeur', a.superseded_by::text,
               'age_jours', round(extract(epoch FROM a.updated_at - a.created_at)
                                  / 86400.0, 1)) ,
           '/cc/v1/atoms/' || a.id::text || '/story'
      FROM arac.memory_atoms a
     WHERE a.status = 'superseded'
       AND a.updated_at >= %(debut)s::timestamptz AND a.updated_at < %(fin)s::timestamptz""",

    "conversation_absorbee": """
    SELECT c.created_at, 'conversation_absorbee', 'conversation', c.conversation_uid,
           coalesce(c.title, c.conversation_uid),
           jsonb_build_object(
               'source_type', c.source_type, 'node_id', c.node_id,
               'messages', (SELECT count(*) FROM arac.raw_messages rm
                             WHERE rm.conversation_id = c.id)),
           '/cc/v1/conversations/' || c.conversation_uid
      FROM arac.conversations c
     WHERE c.created_at >= %(debut)s::timestamptz AND c.created_at < %(fin)s::timestamptz""",

    "conversation_curee": """
    SELECT c.curated_at, 'conversation_curee', 'conversation', c.conversation_uid,
           coalesce(c.title, c.conversation_uid),
           jsonb_build_object(
               'source_type', c.source_type,
               'atoms_generated', c.atoms_generated,
               'curated_through_message_id', c.curated_through_message_id,
               'erreur', c.last_curation_error),
           '/cc/v1/conversations/' || c.conversation_uid
      FROM arac.conversations c
     WHERE c.curated_at >= %(debut)s::timestamptz AND c.curated_at < %(fin)s::timestamptz""",

    "cycle": """
    SELECT r.started_at, 'cycle', 'cycle', r.slot_key, r.slot_key,
           jsonb_build_object(
               'trigger', r.trigger, 'status', r.status, 'model', r.model,
               'items', r.items, 'atoms_created', r.atoms_created,
               'atoms_superseded', r.atoms_superseded,
               'atoms_quarantined', r.atoms_quarantined,
               'stop_reason', r.stop_reason,
               'est_input_tokens', r.est_input_tokens,
               'duree_s', round(extract(epoch FROM r.ended_at - r.started_at))),
           '/cc/v1/metrics/cycles_total'
      FROM arac.run_receipts r
     WHERE r.started_at >= %(debut)s::timestamptz AND r.started_at < %(fin)s::timestamptz""",

    "rappel": """
    SELECT cr.created_at, 'rappel', 'recall', cr.request_id::text,
           coalesce(cr.scope_filter, '(aucun filtre de scope)'),
           jsonb_build_object(
               'consumer', cr.consumer, 'final_band', cr.final_band,
               'raw_band', cr.raw_band, 'stop_reason', cr.stop_reason,
               'k_requested', cr.k_requested, 'budget_k', cr.budget_k,
               'servis', cardinality(cr.served_ids),
               'top1_distance_final', cr.top1_distance_final),
           '/cc/v1/metrics/recall_receipts_total'
      FROM arac.context_receipts cr
     WHERE cr.created_at >= %(debut)s::timestamptz AND cr.created_at < %(fin)s::timestamptz
       /* UN ÉVÉNEMENT PAR RAPPEL. Depuis FOLD V2, chaque rappel réel écrit DEUX
          reçus (moteur servi v1, puis moteur d'ombre v2-fold) avec le MÊME request_id,
          le MÊME horodatage et les MÊMES served_ids. La chronologie émettait donc deux
          événements portant le MÊME subject_id : 208 événements 'rappel' pour 104
          rappels réels sur 48 h, soit une mémoire montrée deux fois plus interrogée
          qu'elle ne l'a été, et l'identité d'événement violée (deux événements, un
          sujet). On retient le PREMIER reçu écrit — le chemin SERVI, « vérité de
          référence » selon le commentaire de colonne — ce qui reste juste si un
          moteur v3 en écrit un troisième. */
       AND NOT EXISTS (SELECT 1 FROM arac.context_receipts p
                        WHERE p.request_id = cr.request_id AND p.id < cr.id)""",
}


def _parse_instant(raw: Any, default: datetime) -> tuple[datetime, str | None]:
    """Lit une borne ISO 8601. Rend la borne et, le cas échéant, ce qui a cloché.

    Ce n'est pas de l'arithmétique sur les données du cerveau : c'est la
    validation d'une entrée HTTP avant qu'elle ne devienne un paramètre lié.
    """
    s = _clean(raw)
    if not s:
        return default, None
    txt = s[:-1] + "+00:00" if s.endswith("Z") else s
    try:
        parsed = datetime.fromisoformat(txt)
    # OverflowError / OSError : certaines formes ISO valides débordent la conversion
    # avant même d'être lues. Elles ne doivent pas plus casser la route qu'une chaîne
    # illisible — le contrat de `timeline` est « ne lève jamais ».
    except (ValueError, OverflowError, OSError):
        return default, f"borne {s!r} illisible (ISO 8601 attendu) — valeur par défaut appliquée"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    # Le vrai piège n'est pas la lecture, c'est L'ARITHMÉTIQUE QUI SUIT : '0001-01-01'
    # se lit très bien, et c'est `fin - 48 h` qui lève OverflowError trois lignes plus
    # loin. La borne de plausibilité est donc posée ICI, une fois, pour toutes les
    # soustractions en aval : au retour de cette fonction, un instant est toujours
    # assez loin de datetime.min/max pour supporter MAX_TIMELINE_DAYS de recul.
    if not (INSTANT_MIN <= parsed <= INSTANT_MAX):
        return default, (f"borne {s!r} hors de la plage servie "
                         f"({INSTANT_MIN.date().isoformat()} – {INSTANT_MAX.date().isoformat()}) "
                         f"— valeur par défaut appliquée")
    return parsed, None


def timeline(from_: Any = None, to: Any = None, granularity: str = "hour",
             types: Any = None) -> dict[str, Any]:
    """La chronologie rejouable du cerveau, entre deux bornes libres.

    Ne lève jamais. Une borne illisible, une granularité inconnue ou un type
    d'événement inconnu ne font pas échouer la requête : ils sont remplacés par
    leur valeur par défaut et SIGNALÉS dans ``notices``. Une chronologie qui
    refuse de répondre n'aide personne à rejouer sa journée.
    """
    notices: list[str] = []

    grain_key = (_clean(granularity) or "hour").lower()
    if grain_key not in GRANULARITIES:
        notices.append(f"granularité {grain_key!r} inconnue — 'hour' appliquée "
                       f"(offertes : {', '.join(GRANULARITIES)})")
        grain_key = "hour"
    grain = GRANULARITIES[grain_key]

    now = datetime.now(timezone.utc)
    fin, why = _parse_instant(to, now)
    if why:
        notices.append(why)
    # INVARIANT : `fin` est ici dans [INSTANT_MIN, INSTANT_MAX] — _parse_instant le
    # garantit, défaut compris (`now`). C'est ce qui rend sûres les TROIS soustractions
    # qui suivent (l. suivante, puis le repli `debut >= fin`, puis le plafond
    # MAX_TIMELINE_DAYS) : aucune ne peut plus sous-déborder datetime.min. C'est
    # exactement ce qui manquait quand `?to=0001-01-01` rendait un HTTP 500.
    debut, why = _parse_instant(from_, fin - timedelta(hours=DEFAULT_TIMELINE_HOURS))
    if why:
        notices.append(why)
    if debut >= fin:
        notices.append(f"borne de début postérieure à la fin — plage ramenée à "
                       f"{DEFAULT_TIMELINE_HOURS} h avant la fin")
        debut = fin - timedelta(hours=DEFAULT_TIMELINE_HOURS)
    if (fin - debut) > timedelta(days=MAX_TIMELINE_DAYS):
        notices.append(f"plage réduite au maximum autorisé de {MAX_TIMELINE_DAYS} jours")
        debut = fin - timedelta(days=MAX_TIMELINE_DAYS)

    asked = [t for t in re.split(r"[,\s]+", _clean(types) or "") if t]
    unknown = [t for t in asked if t not in EVENT_TYPES]
    if unknown:
        notices.append(f"types d'événement inconnus ignorés : {', '.join(sorted(set(unknown)))} "
                       f"(offerts : {', '.join(EVENT_TYPES)})")
    kept = tuple(t for t in EVENT_TYPES if t in asked) or EVENT_TYPES

    params: dict[str, Any] = {
        "grain": grain["trunc"],
        "pas": grain["step"],
        "debut": debut.isoformat(),
        "fin": fin.isoformat(),
        "slash": _SLASH,
        "buckets_max": MAX_TIMELINE_BUCKETS,
        "events_max": MAX_TIMELINE_EVENTS,
    }
    events_sql = ("SELECT at, type, subject_kind, subject_id, subject_label, measures, href\n"
                  "  FROM (\n"
                  + "\n    UNION ALL\n".join(_EVENT_SQL[t] for t in kept)
                  + "\n  ) e\n ORDER BY at, type, subject_id\n LIMIT %(events_max)s")

    started = time.perf_counter()
    try:
        with _readonly() as conn:
            buckets = _rows(conn, _BUCKETS_SQL, params, where="timeline.buckets")
            events = _rows(conn, events_sql, params, where="timeline.events")
            buckets_evidence = _sql_text(conn, _BUCKETS_SQL, params)
            events_evidence = _sql_text(conn, events_sql, params)
            # Idem : la chronologie annonce ce qu'elle ne filme pas, après
            # avoir regardé si la source existe.
            links = _links(conn)
    except Exception as exc:  # noqa: BLE001
        return _failure("timeline", exc)

    buckets_truncated = len(buckets) >= MAX_TIMELINE_BUCKETS
    if buckets_truncated:
        notices.append(f"seaux tronqués à {MAX_TIMELINE_BUCKETS} : élargis la granularité "
                       f"(granularity=day ou week) pour couvrir toute la plage")
    events_truncated = len(events) >= MAX_TIMELINE_EVENTS
    if events_truncated:
        notices.append(f"événements tronqués à {MAX_TIMELINE_EVENTS} : la plage contient plus "
                       f"d'événements que la borne dure — resserre from/to ou filtre types")

    return {
        "state": "ok",
        "range": {"from": debut.isoformat(), "to": fin.isoformat(),
                  "granularity": grain_key, "granularity_label": grain["label"],
                  "step": grain["step"], "duration_hours": (fin - debut).total_seconds() / 3600.0},
        "buckets": buckets,
        "buckets_truncated": {"applied": buckets_truncated, "shown": len(buckets),
                              "limit": MAX_TIMELINE_BUCKETS},
        "events": events,
        "events_truncated": {"applied": events_truncated, "shown": len(events),
                             "limit": MAX_TIMELINE_EVENTS},
        "types": {"selected": list(kept), "available": list(EVENT_TYPES)},
        "events_note": ("les messages bruts ne produisent pas d'événement : ils sont comptés "
                        "dans les seaux (où leur volume informe) et tus dans les événements "
                        "(où leur nombre noierait tout le reste)"),
        "granularities": {k: v["label"] for k, v in GRANULARITIES.items()},
        "notices": notices,
        "links": links,
        "evidence": {"kind": "sql", "sql": buckets_evidence,
                     "label": "les seaux de la plage demandée, tels que la base les compte",
                     "queries": [buckets_evidence, events_evidence]},
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
    """Enregistre les trois routes de « la vie du cerveau » sur l'application.

    Args:
        a: l'instance FastAPI du Control Center.
        session_api: la dépendance de session en mode API (401 JSON si absente).
        audit_read_log: le journal de lecture du socle (chemin, principal).
    """

    @a.get(f"{_PREFIX}/atoms/{{atom_id}}/story")
    def cc_v1_atom_story(atom_id: str,
                         principal: dict = Depends(session_api)) -> JSONResponse:
        """L'histoire complète d'un atome : naissance, corrections, usages, voisins.

        Un seul appel. Un identifiant inconnu ne lève pas : il rend
        ``state='unavailable'`` avec sa raison et la requête qui n'a rien trouvé.
        """
        audit_read_log(f"{_PREFIX}/atoms/{atom_id}/story", principal.get("sub", "?"))
        return JSONResponse(atom_story(atom_id))

    @a.get(f"{_PREFIX}/projects/{{project_id}}/graph")
    def cc_v1_project_graph(
        project_id: str,
        principal: dict = Depends(session_api),
        max_nodes: int = Query(default=MAX_GRAPH_NODES, ge=8, le=MAX_GRAPH_NODES),
    ) -> JSONResponse:
        """Le projet comme graphe : scopes, thèmes, atomes, et ce qui les rapproche.

        Aucune arête n'est un lien déclaré : ce graphe est construit par
        proximité vectorielle, il ne lit pas ``arac.atom_links``. La réponse
        porte la provenance de chaque nature d'arête plutôt que de laisser croire
        à un graphe de sens.
        """
        audit_read_log(f"{_PREFIX}/projects/{project_id}/graph", principal.get("sub", "?"))
        return JSONResponse(project_graph(project_id, max_nodes=max_nodes))

    @a.get(f"{_PREFIX}/timeline")
    def cc_v1_timeline(
        principal: dict = Depends(session_api),
        from_: str | None = Query(default=None, alias="from", max_length=64),
        to: str | None = Query(default=None, max_length=64),
        granularity: str = Query(default="hour", max_length=16),
        types: str | None = Query(default=None, max_length=200),
    ) -> JSONResponse:
        """La chronologie rejouable : seaux comptés et événements datés, ordonnés.

        Bornes libres (ISO 8601), granularité ``hour``/``day``/``week``, types
        filtrables. Une entrée invalide n'échoue pas : elle est remplacée par sa
        valeur par défaut et signalée dans ``notices``.
        """
        audit_read_log(f"{_PREFIX}/timeline", principal.get("sub", "?"))
        return JSONResponse(timeline(from_=from_, to=to, granularity=granularity, types=types))
