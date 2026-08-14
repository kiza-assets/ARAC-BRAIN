"""Control Center v1 — LES SCOPES COMME OBJETS DE PREMIER NIVEAU.

Un scope n'est pas une étiquette. C'est le TERRITOIRE dans lequel le cerveau
range ce qu'il apprend, et c'est lui qui décide de ce qu'il retrouvera :

    « Un atome posé sur une RACINE (un scope sans « / ») est invisible au
      rappel. Il est écrit, il est actif, et il ne remontera jamais. »

Tant qu'un scope reste une chaîne de caractères dans une liste, cette dette est
invisible. Ce module en fait un objet qu'on ouvre : son poids, sa confiance, sa
part dormante, ses conversations sources, ses projets, sa chronologie, ses
voisins sémantiques — et, quand il est en dette, le nombre exact d'atomes qu'il
séquestre hors de portée du rappel.

    « Est-ce que ça m'aide à comprendre ce que le cerveau apprend, retient,
      oublie ou ne comprend pas ? » — c'est la seule question posée à chaque
    bloc servi ici. Un scope qui grossit sans jamais être rappelé est du savoir
    OUBLIÉ ; un scope à faible confiance est du savoir que le cerveau NE
    COMPREND PAS ; une racine peuplée est du savoir qu'il n'a jamais RETENU.

ROUTES — additives, sans collision avec l'existant :

  GET /cc/v1/scopes/tree      l'arborescence enrichie : un scope = une ligne vivante
  GET /cc/v1/scopes/{path}    le détail d'un territoire (chemin encodé accepté)

``entities.py`` sert déjà ``GET /cc/v1/scopes`` (la liste plate). Ce module ne
la redéclare pas et ne la modifie pas : il l'APPROFONDIT. ``register()`` vérifie
l'absence de collision au démarrage et refuse de s'enregistrer deux fois plutôt
que de laisser FastAPI conserver silencieusement la première déclaration.

ORDRE D'ENREGISTREMENT — non négociable : ``/tree`` est déclaré AVANT
``/{path:path}``. Le second motif capture les barres obliques (un scope
s'écrit ``racine/feuille``), donc il capturerait aussi le mot ``tree`` s'il
venait en premier. FastAPI résout dans l'ordre de déclaration ; l'ordre EST le
contrat.

DOCTRINE, identique au socle (``routes.py``, ``entities.py``) :
  - ``@a.get`` uniquement, aucun verbe mutant, aucune écriture ;
  - garde de session et journal de lecture sur chaque route ;
  - handlers synchrones : FastAPI les exécute en threadpool ;
  - **toute l'arithmétique est en SQL** — pourcentages, cumuls, moyennes,
    distances ``<=>``, séries de jours. Python transporte des lignes ;
  - **toute réponse porte son ``evidence``** : le SQL réellement exécuté,
    paramètres substitués, sur une ligne, rejouable dans ``psql`` ;
  - **une absence n'est jamais un zéro** : un scope sans centroïde rend
    ``neighbours: []`` AVEC sa raison, jamais une liste vide muette.

RÉUTILISATION PLUTÔT QUE RECOPIE. Les helpers d'exécution (connexion, curseur
client, preuve rejouable, dégradation motivée) et les règles de projet
vivent dans ``entities.py``. Ils sont IMPORTÉS, pas recopiés : une règle de
projet qui existerait en deux exemplaires finirait par diverger, et deux écrans
du même cockpit afficheraient deux vérités. Le partage rend la contradiction
impossible par construction.

POURQUOI LES RÈGLES DE PROJET VIENNENT D'``entities`` ET NON DE LA FAMILLE
``projets`` : les deux existent et diffèrent volontairement sur un point — la
famille de métriques EXCLUT les racines nues d'un projet, la navigation les
INCLUT (les atomes posés sur une racine appartiennent bel et bien au projet, et
les cacher fabriquerait un trou dans la fiche). Ce module est une route de
navigation : il suit la sémantique de navigation, et le dit ici pour qu'on ne
prenne pas l'écart pour un bug.

LECTURE SEULE : aucune instruction mutante. Le gabarit de chaque requête passe
par ``entities._assert_read_only`` avant exécution, troisième couche après le
rôle ``arac_readonly`` et ``default_transaction_read_only=on``.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable
from urllib.parse import unquote

from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse

from app.journal import raison, reduire, sha8
from control_center.cc_v1 import entities, service

__all__ = ["register", "scopes_tree", "scope_detail", "ROUTES"]

logger = logging.getLogger("arac.cc.v1.scopes")

_PREFIX = "/cc/v1"

#: Les deux routes de ce module, déclarées ici pour que la garde de collision et
#: la documentation lisent la MÊME liste que l'enregistrement. Une garde qui
#: contrôle autre chose que ce qu'on enregistre ne garde rien.
ROUTES: tuple[str, ...] = (
    f"{_PREFIX}/scopes/tree",
    f"{_PREFIX}/scopes/{{path:path}}",
)

#: Motif ``LIKE`` du séparateur de scope, passé en PARAMÈTRE et jamais écrit
#: dans le corps du SQL : psycopg réserve ``%`` au marquage des paramètres.
_SLASH = entities._SLASH

#: Bornes des listes d'une fiche. Une fiche reste une fiche : au-delà, on n'a
#: plus un objet qu'on lit, on a un export qu'on ne lit pas.
_LIST_LIMIT = 50
_FRAGILE_LIMIT = 20
_HISTORY_LIMIT = 40
_NEIGHBOURS = 8

#: Plafond PAR TYPE d'événement dans la chronologie. Sans lui, un territoire très
#: rappelé noie ses créations d'atomes sous des centaines de « rappel servi » —
#: et la chronologie, qui doit raconter ce que le cerveau a APPRIS, ne raconte
#: plus que ce qu'il a relu. Le rang de chaque événement dans son propre type est
#: servi avec lui : la troncature est visible, jamais silencieuse.
_HISTORY_PER_TYPE = 12

#: Profondeur de la courbe d'évolution, en jours. 90 jours couvrent un trimestre
#: — assez pour voir une reprise ou un abandon, assez court pour rester lisible.
_EVOLUTION_DAYS = 90

#: Sous ce score, un atome est fragile. Même seuil que la famille de métriques
#: ``confiance`` : deux seuils différents feraient dire à la fiche et à la
#: métrique deux choses contradictoires sur le même atome.
_FRAGILE_BELOW = 70

#: Le corpus jugé, qualifié par l'alias ``a``. ``agent_message`` est du
#: TRANSPORT entre nœuds, jamais du savoir : il n'appartient à aucun territoire.
_SAVOIR_A = "a.kind <> 'agent_message'"

#: L'ÉTAT d'un territoire, dérivé EN SQL et servi tel quel. Il n'est calculé ni
#: par le BFF ni par le navigateur : l'interface peint ce que la base affirme.
#: L'ordre des branches est normatif — la dette prime sur tout le reste, parce
#: qu'un territoire invisible au rappel n'a pas d'autre problème digne d'être
#: affiché en premier.
_ETAT_CASE = f"""
        CASE
            WHEN g.path NOT LIKE %(slash)s                    THEN 'dette'
            WHEN g.atoms_active = 0                           THEN 'vide'
            WHEN g.dormant = g.atoms_active                   THEN 'jamais_rappele'
            WHEN g.confidence_avg < {_FRAGILE_BELOW} + 10     THEN 'fragile'
            WHEN g.growth_30d > 0                             THEN 'actif'
            ELSE 'stable'
        END
"""

#: Les tranches de confiance, écrites UNE fois : l'arbre, la fiche et la famille
#: ``confiance`` doivent découper la même population aux mêmes endroits.
_TRANCHE_CASE = """
        CASE
            WHEN a.confidence_score IS NULL THEN 'sans score'
            WHEN a.confidence_score < 60    THEN 'moins de 60'
            WHEN a.confidence_score < 70    THEN '60 a 69'
            WHEN a.confidence_score < 80    THEN '70 a 79'
            WHEN a.confidence_score < 90    THEN '80 a 89'
            ELSE '90 et plus'
        END
"""


# ============================================================================
# Les projets, traduits en SQL — source unique : cc_v1/projects.py
# ============================================================================


def _projects_for_scope_sql() -> tuple[str, dict[str, Any]]:
    """Les projets qui touchent UN scope donné (paramètre ``%(path)s``).

    Un projet est une VUE, pas un dossier : son appartenance se décide atome par
    atome (scopes ET mots-clés). Un scope peut donc appartenir à plusieurs
    projets, ou à aucun, et le compte par projet ne s'additionne pas.
    """
    blocks: list[str] = []
    params: dict[str, Any] = {}
    for rank, p in enumerate(entities.PROJECTS, start=1):
        pred, prm = entities._project_predicate(p, "a", f"p_{p['id']}")
        params |= prm
        params[f"lab_{p['id']}"] = p["label"]
        blocks.append(
            f"SELECT {rank} AS rang, '{p['id']}'::text AS id,"
            f" %(lab_{p['id']})s::text AS label,"
            f" (SELECT count(*) FROM arac.memory_atoms a"
            f"   WHERE a.scope = %(path)s AND a.status = 'active'"
            f"     AND {_SAVOIR_A} AND {pred}) AS atomes"
        )
    # `ORDER BY t.rang` lit une colonne de cette sous-requête : la relation de
    # repli (aucun projet déclaré) doit la projeter aussi, sinon l'absence de
    # projet ferait échouer la fiche de scope pour une AUTRE raison.
    sql = (
        "SELECT t.id, t.label, t.atomes,\n"
        "       '/cc/v1/projects/' || t.id AS href\n"
        "  FROM (\n" + entities.union_ou_vide(
            blocks,
            (("rang", "int"), ("id", "text"), ("label", "text"), ("atomes", "bigint")),
        ) + "\n) t\n"
        " WHERE t.atomes > 0\n"
        " ORDER BY t.atomes DESC, t.rang\n"
        " LIMIT 8"
    )
    return sql, params


def _projects_per_scope_fragment() -> tuple[str, dict[str, Any]]:
    """Le même calcul, corrélé à la colonne ``g.path`` de l'arbre.

    Rendu comme un sous-select scalaire produisant un tableau JSON de libellés :
    l'arbre reste UNE requête, donc UNE preuve rejouable, plutôt que 38 allers-
    retours dont personne ne pourrait vérifier la cohérence.
    """
    blocks: list[str] = []
    params: dict[str, Any] = {}
    for rank, p in enumerate(entities.PROJECTS, start=1):
        pred, prm = entities._project_predicate(p, "m", f"g_{p['id']}")
        params |= prm
        params[f"glab_{p['id']}"] = p["label"]
        blocks.append(
            f"SELECT {rank} AS rang, %(glab_{p['id']})s::text AS label"
            f"  WHERE EXISTS (SELECT 1 FROM arac.memory_atoms m"
            f"                 WHERE m.scope = g.path AND m.status = 'active'"
            f"                   AND m.kind <> 'agent_message' AND {pred})"
        )
    frag = (
        "(SELECT coalesce(jsonb_agg(x.label ORDER BY x.rang), '[]'::jsonb) FROM (\n"
        + entities.union_ou_vide(blocks, (("rang", "int"), ("label", "text")))
        + "\n) x)"
    )
    return frag, params


# ============================================================================
# GET /cc/v1/scopes/tree — l'arborescence enrichie
# ============================================================================


def scopes_tree(limit: int = entities.MAX_LIMIT) -> dict[str, Any]:
    """L'arbre des territoires : une ligne par scope, vivante et cliquable.

    Chaque ligne porte ce qui permet de DÉCIDER : ce que le territoire pèse, ce
    qu'il oublie (part dormante), ce dont il doute (confiance), ce qu'il produit
    (croissance à 30 jours), ce qu'il sert (rappels à 30 jours) — et s'il est en
    dette, donc invisible au rappel.
    """
    limit = entities._bounded(limit, entities.MAX_LIMIT)
    proj_frag, proj_params = _projects_per_scope_fragment()

    sql = f"""
WITH servis AS (
    SELECT DISTINCT s AS atom_id
      FROM arac.context_receipts cr
      CROSS JOIN LATERAL unnest(cr.served_ids) s
),
servis_30d AS (
    /* `passages` compte des RAPPELS, pas des lignes de reçu : depuis FOLD V2
       chaque rappel en écrit deux (moteur servi + moteur d'ombre, mêmes served_ids).
       Sans le dédoublonnage, `recall_served_30d` affichait le double pour chaque
       territoire. Cf. entities.UN_RECU_PAR_RAPPEL. */
    SELECT s AS atom_id, count(*) AS passages
      FROM arac.context_receipts cr
      CROSS JOIN LATERAL unnest(cr.served_ids) s
     WHERE cr.created_at >= now() - interval '30 days'
       {entities.UN_RECU_PAR_RAPPEL}
     GROUP BY 1
),
agg AS (
    SELECT a.scope                                                        AS path,
           count(*) FILTER (WHERE a.status = 'active')                    AS atoms_active,
           count(*)                                                       AS atoms_total,
           count(*) FILTER (WHERE a.status = 'active' AND sv.atom_id IS NULL)
                                                                          AS dormant,
           round(avg(a.confidence_score) FILTER (WHERE a.status = 'active')::numeric, 1)
                                                                          AS confidence_avg,
           round((percentile_cont(0.25) WITHIN GROUP (ORDER BY a.confidence_score)
                  FILTER (WHERE a.status = 'active'))::numeric, 0)        AS confidence_p25,
           count(*) FILTER (WHERE a.status = 'active'
                              AND a.confidence_score < {_FRAGILE_BELOW})  AS low_confidence_count,
           count(DISTINCT a.source_ref->>'conversation_uid')
               FILTER (WHERE a.status = 'active')                         AS conversations,
           /* LE DÉNOMINATEUR DE `conversations`, SANS QUOI LE CHIFFRE MENT PAR OMISSION.
              Poser « 251 atomes actifs » à côté de « 3 conversations » se lit comme
              « 3 conversations ont produit 251 atomes ». C'est faux partout où la
              provenance a été perdue — et sur le cerveau de référence, 76 pour cent
              du corpus était dans ce cas : un changement de format de source_ref
              avait coupé le lien atome-conversation, sans erreur ni alerte.
              La limite était donc tue exactement là où elle mord le plus.
              Arithmétique en SQL, pas au client. */
           /* `source_ref->>'conversation_uid' IS NULL` ET NON `NOT (source_ref ? …)` :
              56 atomes actifs n'ont AUCUN source_ref, et sur eux l'opérateur `?`
              rend NULL — donc ni vrai ni faux, donc EXCLU du FILTER. Le compte des
              atomes sans origine oubliait ainsi les plus orphelins de tous :
              `arac/strategie` annonçait 118 introuvables au lieu de 153. L'erreur
              allait dans le sens FLATTEUR, celui qui fait paraître la dette de
              provenance plus petite qu'elle n'est. L'écriture ci-dessous est
              insensible au NULL, comme celle qu'emploie déjà la fiche de projet. */
           count(*) FILTER (WHERE a.status = 'active'
                              AND a.source_ref->>'conversation_uid' IS NULL)
                                                                          AS atomes_sans_conversation,
           count(*) FILTER (WHERE a.status = 'active'
                              AND a.source_ref->>'conversation_uid' IS NULL
                              AND a.source_ref->>'curator_raw_id' IS NOT NULL)
                                                                          AS atomes_provenance_legacy,
           max(a.created_at) FILTER (WHERE a.status = 'active')           AS last_atom_at,
           min(a.created_at) FILTER (WHERE a.status = 'active')           AS first_atom_at,
           count(*) FILTER (WHERE a.status = 'active'
                              AND a.created_at >= now() - interval '30 days')
                                                                          AS growth_30d,
           coalesce(sum(s30.passages) FILTER (WHERE a.status = 'active'), 0)
                                                                          AS recall_served_30d
      FROM arac.memory_atoms a
      LEFT JOIN servis sv ON sv.atom_id = a.id
      LEFT JOIN servis_30d s30 ON s30.atom_id = a.id
     WHERE {_SAVOIR_A}
     GROUP BY a.scope
)
SELECT g.path,
       split_part(g.path, '/', 1)                                         AS root,
       CASE WHEN g.path LIKE %(slash)s
            THEN regexp_replace(g.path, '^.*/', '') END                   AS leaf,
       (g.path NOT LIKE %(slash)s)                                        AS is_root_scope,
       (length(g.path) - length(replace(g.path, '/', '')) + 1)            AS depth,
       g.atoms_active, g.atoms_total, g.dormant,
       round(100.0 * g.dormant / nullif(g.atoms_active, 0), 1)            AS dormant_pct,
       g.confidence_avg, g.confidence_p25, g.low_confidence_count,
       g.conversations, g.atomes_sans_conversation, g.atomes_provenance_legacy,
       {proj_frag}                                                        AS projects,
       g.last_atom_at, g.first_atom_at, g.growth_30d,
       (SELECT coalesce(jsonb_object_agg(k.kind, k.n), '{{}}'::jsonb)
          FROM (SELECT m.kind, count(*) AS n
                  FROM arac.memory_atoms m
                 WHERE m.scope = g.path AND m.status = 'active'
                   AND m.kind <> 'agent_message'
                 GROUP BY m.kind) k)                                      AS kinds,
       g.recall_served_30d,
       (g.path NOT LIKE %(slash)s)                                        AS debt,
       (pr.scope IS NOT NULL)                                             AS centroid_known,
       pr.member_count                                                    AS registry_member_count,
       pr.updated_at                                                      AS registry_updated_at,
       {_ETAT_CASE}                                                       AS state,
       '/cc/v1/scopes/' || g.path                                         AS href
  FROM agg g
  LEFT JOIN arac.project_registry pr ON pr.scope = g.path
 ORDER BY g.atoms_active DESC, g.path
 LIMIT %(limit)s"""

    totals_sql = f"""
WITH servis AS (
    SELECT DISTINCT s AS atom_id
      FROM arac.context_receipts cr
      CROSS JOIN LATERAL unnest(cr.served_ids) s
),
base AS (
    SELECT a.scope, a.status, a.confidence_score, a.created_at,
           (sv.atom_id IS NULL) AS dormant
      FROM arac.memory_atoms a
      LEFT JOIN servis sv ON sv.atom_id = a.id
     WHERE {_SAVOIR_A}
)
SELECT count(DISTINCT scope)                                              AS scopes,
       count(DISTINCT scope) FILTER (WHERE scope NOT LIKE %(slash)s)      AS root_scopes,
       count(DISTINCT split_part(scope, '/', 1))                          AS racines,
       count(*) FILTER (WHERE status = 'active')                          AS atoms_active,
       count(*)                                                           AS atoms_total,
       count(*) FILTER (WHERE status = 'active' AND scope NOT LIKE %(slash)s)
                                                                          AS root_level_debt,
       count(*) FILTER (WHERE status = 'active' AND dormant)              AS dormant,
       round(100.0 * count(*) FILTER (WHERE status = 'active' AND dormant)
             / nullif(count(*) FILTER (WHERE status = 'active'), 0), 1)   AS dormant_pct,
       round(avg(confidence_score) FILTER (WHERE status = 'active')::numeric, 1)
                                                                          AS confidence_avg,
       count(*) FILTER (WHERE status = 'active' AND confidence_score IS NULL)
                                                                          AS sans_score,
       count(*) FILTER (WHERE status = 'active'
                          AND created_at >= now() - interval '30 days')   AS growth_30d,
       (SELECT count(*) FROM arac.project_registry)                       AS scopes_with_centroid,
       (SELECT count(*) FROM (
            SELECT DISTINCT b2.scope FROM base b2 WHERE b2.status = 'active') s
         WHERE NOT EXISTS (SELECT 1 FROM arac.project_registry pr
                            WHERE pr.scope = s.scope))                    AS scopes_without_centroid,
       (SELECT count(*) FROM (
            SELECT b3.scope
              FROM base b3
             WHERE b3.status = 'active'
             GROUP BY b3.scope
            HAVING count(*) FILTER (WHERE b3.dormant) = count(*)) d)      AS scopes_never_recalled
  FROM base"""

    params: dict[str, Any] = {"slash": _SLASH, "limit": limit} | proj_params
    started = time.perf_counter()
    try:
        with entities._readonly() as conn:
            items = entities._rows(conn, sql, params, where="scopes.tree")
            totals = entities._one(conn, totals_sql, params, where="scopes.tree.totals") or {}
            evidence_sql = entities._sql_text(conn, sql, params)
            totals_evidence = entities._sql_text(conn, totals_sql, params)
    except Exception as exc:  # noqa: BLE001 — une panne se dit, elle ne se déguise pas
        return entities._failure("scopes.tree", exc) | {"items": [], "totals": {}}

    return {
        "state": "ok",
        "items": items,
        "count": len(items),
        "limit": limit,
        "totals": totals,
        "legend": {
            "state": {
                "dette": "scope racine : ses atomes sont invisibles au rappel",
                "vide": "aucun atome actif",
                "jamais_rappele": "aucun de ses atomes n'a jamais été servi",
                "fragile": f"confiance moyenne sous {_FRAGILE_BELOW + 10}",
                "actif": "au moins un atome créé ces 30 derniers jours",
                "stable": "peuplé, rappelé, sans mouvement récent",
            },
            "note": ("les projets d'une ligne ne s'additionnent pas : un atome peut "
                     "appartenir à plusieurs projets, le recouvrement est voulu"),
        },
        "evidence": {
            "kind": "sql",
            "sql": evidence_sql,
            "label": "l'arbre des territoires, tel que la base le décrit",
            "queries": [evidence_sql, totals_evidence],
        },
        "computed_at": service._now(),
        "duration_ms": service._ms(started),
    }


# ============================================================================
# GET /cc/v1/scopes/{path} — le détail d'un territoire
# ============================================================================


_HEADER_SQL = f"""
WITH servis AS (
    SELECT DISTINCT s AS atom_id
      FROM arac.context_receipts cr
      CROSS JOIN LATERAL unnest(cr.served_ids) s
),
g AS (
    SELECT %(path)s::text                                                 AS path,
           count(*) FILTER (WHERE a.status = 'active')                    AS atoms_active,
           count(*)                                                       AS atoms_total,
           count(*) FILTER (WHERE a.status = 'archived')                  AS atoms_archived,
           count(*) FILTER (WHERE a.superseded_by IS NOT NULL)            AS atoms_superseded,
           count(*) FILTER (WHERE a.status = 'active' AND sv.atom_id IS NULL)
                                                                          AS dormant,
           round(avg(a.confidence_score) FILTER (WHERE a.status = 'active')::numeric, 1)
                                                                          AS confidence_avg,
           round((percentile_cont(0.5) WITHIN GROUP (ORDER BY a.confidence_score)
                  FILTER (WHERE a.status = 'active'))::numeric, 0)        AS confidence_median,
           round((percentile_cont(0.25) WITHIN GROUP (ORDER BY a.confidence_score)
                  FILTER (WHERE a.status = 'active'))::numeric, 0)        AS confidence_p25,
           min(a.confidence_score) FILTER (WHERE a.status = 'active')     AS confidence_min,
           max(a.confidence_score) FILTER (WHERE a.status = 'active')     AS confidence_max,
           count(*) FILTER (WHERE a.status = 'active'
                              AND a.confidence_score < {_FRAGILE_BELOW})  AS low_confidence_count,
           count(*) FILTER (WHERE a.status = 'active'
                              AND a.confidence_score IS NULL)             AS sans_score,
           count(DISTINCT a.source_ref->>'conversation_uid')
               FILTER (WHERE a.status = 'active')                         AS conversations,
           /* Cf. la même correction sur la liste : le compte de conversations n'a de
              sens qu'accompagné du nombre d'atomes qui ne remontent à AUCUNE
              conversation. Sans lui, la fiche laissait déduire une origine à des
              atomes qui n'en ont pas de tracée. */
           /* `source_ref->>'conversation_uid' IS NULL` ET NON `NOT (source_ref ? …)` :
              56 atomes actifs n'ont AUCUN source_ref, et sur eux l'opérateur `?`
              rend NULL — donc ni vrai ni faux, donc EXCLU du FILTER. Le compte des
              atomes sans origine oubliait ainsi les plus orphelins de tous :
              `arac/strategie` annonçait 118 introuvables au lieu de 153. L'erreur
              allait dans le sens FLATTEUR, celui qui fait paraître la dette de
              provenance plus petite qu'elle n'est. L'écriture ci-dessous est
              insensible au NULL, comme celle qu'emploie déjà la fiche de projet. */
           count(*) FILTER (WHERE a.status = 'active'
                              AND a.source_ref->>'conversation_uid' IS NULL)
                                                                          AS atomes_sans_conversation,
           count(*) FILTER (WHERE a.status = 'active'
                              AND a.source_ref->>'conversation_uid' IS NULL
                              AND a.source_ref->>'curator_raw_id' IS NOT NULL)
                                                                          AS atomes_provenance_legacy,
           count(DISTINCT a.node_id) FILTER (WHERE a.status = 'active')   AS nodes,
           min(a.created_at) FILTER (WHERE a.status = 'active')           AS first_atom_at,
           max(a.created_at) FILTER (WHERE a.status = 'active')           AS last_atom_at,
           count(*) FILTER (WHERE a.status = 'active'
                              AND a.created_at >= now() - interval '30 days')
                                                                          AS growth_30d,
           count(*) FILTER (WHERE a.status = 'active'
                              AND a.created_at >= now() - interval '7 days')
                                                                          AS growth_7d,
           count(*) FILTER (WHERE a.status = 'active'
                              AND a.rationale IS NOT NULL
                              AND btrim(a.rationale) <> '')               AS avec_rationnel,
           count(*) FILTER (WHERE a.status = 'active'
                              AND a.audit_source IS NOT NULL
                              AND btrim(a.audit_source) <> '')            AS audites,
           count(DISTINCT a.kind) FILTER (WHERE a.status = 'active')      AS natures
      FROM arac.memory_atoms a
      LEFT JOIN servis sv ON sv.atom_id = a.id
     WHERE a.scope = %(path)s AND {_SAVOIR_A}
)
SELECT g.path,
       split_part(g.path, '/', 1)                                         AS root,
       CASE WHEN g.path LIKE %(slash)s
            THEN regexp_replace(g.path, '^.*/', '') END                   AS leaf,
       (g.path NOT LIKE %(slash)s)                                        AS is_root_scope,
       (length(g.path) - length(replace(g.path, '/', '')) + 1)            AS depth,
       g.atoms_active, g.atoms_total, g.atoms_archived, g.atoms_superseded,
       g.dormant,
       round(100.0 * g.dormant / nullif(g.atoms_active, 0), 1)            AS dormant_pct,
       g.confidence_avg, g.confidence_median, g.confidence_p25,
       g.confidence_min, g.confidence_max, g.low_confidence_count, g.sans_score,
       g.conversations, g.atomes_sans_conversation, g.atomes_provenance_legacy,
       g.nodes, g.natures,
       g.first_atom_at, g.last_atom_at, g.growth_30d, g.growth_7d,
       g.avec_rationnel, g.audites,
       round(100.0 * g.avec_rationnel / nullif(g.atoms_active, 0), 1)     AS rationnel_pct,
       round(100.0 * g.audites / nullif(g.atoms_active, 0), 1)            AS audit_pct,
       (pr.scope IS NOT NULL)                                             AS centroid_known,
       pr.member_count                                                    AS registry_member_count,
       pr.updated_at                                                      AS registry_updated_at,
       {_ETAT_CASE}                                                       AS state
  FROM g
  LEFT JOIN arac.project_registry pr ON pr.scope = g.path"""


_COVERAGE_SQL = f"""
SELECT a.kind                                                             AS nature,
       (a.kind IN ('gotcha', 'decision', 'state', 'pattern'))             AS structurante,
       count(*)                                                           AS atomes,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1)                 AS part_pct,
       round(avg(a.confidence_score)::numeric, 1)                         AS confiance_moyenne,
       count(*) FILTER (WHERE a.rationale IS NOT NULL
                          AND btrim(a.rationale) <> '')                   AS avec_rationnel,
       min(a.created_at)                                                  AS premier,
       max(a.created_at)                                                  AS dernier
  FROM arac.memory_atoms a
 WHERE a.scope = %(path)s AND a.status = 'active' AND {_SAVOIR_A}
 GROUP BY a.kind
 ORDER BY 3 DESC"""


_TAGS_SQL = f"""
SELECT t.tag,
       count(*)                                                           AS atomes,
       round(avg(a.confidence_score)::numeric, 1)                         AS confiance_moyenne,
       max(a.created_at)                                                  AS dernier
  FROM arac.memory_atoms a
  CROSS JOIN LATERAL unnest(coalesce(a.tags, '{{}}'::text[])) AS t(tag)
 WHERE a.scope = %(path)s AND a.status = 'active' AND {_SAVOIR_A}
 GROUP BY t.tag
 ORDER BY 2 DESC, 1
 LIMIT 25"""


_EVOLUTION_SQL = f"""
WITH bornes AS (
    SELECT date_trunc('day', now() - make_interval(days => %(days)s - 1))  AS debut,
           date_trunc('day', now())                                        AS fin
),
jours AS (
    SELECT generate_series((SELECT debut FROM bornes),
                           (SELECT fin FROM bornes),
                           interval '1 day')::date                         AS jour
),
crees AS (
    SELECT date_trunc('day', a.created_at)::date                           AS jour,
           count(*)                                                        AS n
      FROM arac.memory_atoms a
     WHERE a.scope = %(path)s AND a.status = 'active' AND {_SAVOIR_A}
       AND a.created_at >= (SELECT debut FROM bornes)
     GROUP BY 1
),
anterieur AS (
    SELECT count(*) AS n
      FROM arac.memory_atoms a
     WHERE a.scope = %(path)s AND a.status = 'active' AND {_SAVOIR_A}
       AND a.created_at < (SELECT debut FROM bornes)
)
SELECT j.jour,
       coalesce(c.n, 0)                                                    AS atomes_crees,
       (SELECT n FROM anterieur)
         + sum(coalesce(c.n, 0)) OVER (ORDER BY j.jour)                    AS cumul
  FROM jours j
  LEFT JOIN crees c ON c.jour = j.jour
 ORDER BY j.jour"""


_DISTRIBUTION_SQL = f"""
SELECT {_TRANCHE_CASE}                                                    AS tranche,
       count(*)                                                           AS atomes,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1)                 AS part_pct,
       min(a.confidence_score)                                            AS score_min,
       max(a.confidence_score)                                            AS score_max
  FROM arac.memory_atoms a
 WHERE a.scope = %(path)s AND a.status = 'active' AND {_SAVOIR_A}
 GROUP BY 1
 ORDER BY min(coalesce(a.confidence_score, -1))"""


_FRAGILE_SQL = f"""
SELECT a.id, a.kind, a.key, a.confidence_score, a.confidence, a.audit_source,
       (a.rationale IS NOT NULL AND btrim(a.rationale) <> '')             AS justifie,
       a.created_at,
       left(a.value, 160)                                                 AS extrait,
       '/cc/v1/atoms/' || a.id                                            AS href
  FROM arac.memory_atoms a
 WHERE a.scope = %(path)s AND a.status = 'active' AND {_SAVOIR_A}
   AND (a.confidence_score IS NULL OR a.confidence_score < {_FRAGILE_BELOW})
 ORDER BY a.confidence_score ASC NULLS FIRST, a.created_at DESC
 LIMIT %(fragile_limit)s"""


_CONVERSATIONS_SQL = f"""
SELECT c.conversation_uid                                                 AS uid,
       c.title, c.source_type, c.curated_at, c.node_id,
       count(a.id)                                                        AS atomes,
       round(avg(a.confidence_score)::numeric, 1)                         AS confiance_moyenne,
       min(a.created_at)                                                  AS premier_atome,
       max(a.created_at)                                                  AS dernier_atome,
       '/cc/v1/conversations/' || c.conversation_uid                      AS href
  FROM arac.memory_atoms a
  JOIN arac.conversations c
    ON c.conversation_uid = a.source_ref->>'conversation_uid'
 WHERE a.scope = %(path)s AND a.status = 'active' AND {_SAVOIR_A}
 GROUP BY c.conversation_uid, c.title, c.source_type, c.curated_at, c.node_id
 ORDER BY 6 DESC, 9 DESC
 LIMIT %(list_limit)s"""


_RECALL_SQL = f"""
WITH atomes AS (
    SELECT a.id
      FROM arac.memory_atoms a
     WHERE a.scope = %(path)s AND a.status = 'active' AND {_SAVOIR_A}
),
hits AS (
    /* Un rappel, une ligne : `served` et `served_30d` comptaient des reçus, donc
       le double des rappels réels. Cf. entities.UN_RECU_PAR_RAPPEL. */
    SELECT cr.id AS receipt_id, cr.created_at, cr.consumer,
           coalesce(cr.final_band, 'inconnue') AS band,
           s AS atom_id
      FROM arac.context_receipts cr
      CROSS JOIN LATERAL unnest(cr.served_ids) s
      JOIN atomes t ON t.id = s
     WHERE true
       {entities.UN_RECU_PAR_RAPPEL}
)
SELECT count(DISTINCT h.receipt_id)                                       AS served,
       count(DISTINCT h.atom_id)                                          AS distinct_atoms,
       (SELECT count(*) FROM atomes)                                      AS atoms_active,
       (SELECT count(*) FROM atomes) - count(DISTINCT h.atom_id)          AS never_served,
       count(DISTINCT h.receipt_id) FILTER (
           WHERE h.created_at >= now() - interval '30 days')              AS served_30d,
       max(h.created_at)                                                  AS last_served_at,
       (SELECT coalesce(jsonb_object_agg(b.band, b.n), '{{}}'::jsonb)
          FROM (SELECT h2.band, count(DISTINCT h2.receipt_id) AS n
                  FROM hits h2 GROUP BY h2.band) b)                       AS bands,
       (SELECT coalesce(jsonb_object_agg(k.consumer, k.n), '{{}}'::jsonb)
          FROM (SELECT h3.consumer, count(DISTINCT h3.receipt_id) AS n
                  FROM hits h3 GROUP BY h3.consumer) k)                   AS consumers
  FROM hits h"""


_HISTORY_SQL = f"""
WITH atomes AS (
    SELECT a.id, a.kind, a.key, a.created_at, a.updated_at,
           a.superseded_by, a.status,
           a.source_ref->>'conversation_uid' AS uid
      FROM arac.memory_atoms a
     WHERE a.scope = %(path)s AND {_SAVOIR_A}
),
evenements AS (
    SELECT a.created_at                                                    AS at,
           'atome_cree'                                                    AS type,
           'Nouvel atome · ' || a.kind || ' · ' || left(a.key, 70)         AS label,
           '/cc/v1/atoms/' || a.id                                         AS href
      FROM atomes a
    UNION ALL
    SELECT a.updated_at, 'atome_remplace',
           'Version remplacée · ' || a.kind || ' · ' || left(a.key, 70),
           '/cc/v1/atoms/' || a.id
      FROM atomes a
     WHERE a.superseded_by IS NOT NULL
    UNION ALL
    SELECT c.curated_at, 'conversation_curee',
           'Conversation analysée · ' || coalesce(left(c.title, 70), c.conversation_uid),
           '/cc/v1/conversations/' || c.conversation_uid
      FROM arac.conversations c
     WHERE c.curated_at IS NOT NULL
       AND EXISTS (SELECT 1 FROM atomes a WHERE a.uid = c.conversation_uid)
    UNION ALL
    SELECT cr.created_at, 'rappel_servi',
           'Rappel servi · ' || cr.consumer || ' · bande '
             || coalesce(cr.final_band, 'inconnue'),
           NULL
      FROM arac.context_receipts cr
     WHERE EXISTS (SELECT 1 FROM atomes a
                    WHERE cr.served_ids @> ARRAY[a.id])
       /* Un rappel, UN événement : sans ce prédicat la chronologie du territoire
          affichait deux lignes identiques par rappel (moteur servi + moteur
          d'ombre), et le plafond par type se remplissait deux fois plus vite —
          les créations d'atomes disparaissaient sous des doublons.
          Cf. entities.UN_RECU_PAR_RAPPEL. */
       {entities.UN_RECU_PAR_RAPPEL}
),
rangs AS (
    SELECT e.at, e.type, e.label, e.href,
           row_number() OVER (PARTITION BY e.type ORDER BY e.at DESC) AS rang
      FROM evenements e
     WHERE e.at IS NOT NULL
)
SELECT r.at, r.type, r.label, r.href, r.rang
  FROM rangs r
 WHERE r.rang <= %(per_type)s
 ORDER BY r.at DESC
 LIMIT %(history_limit)s"""


_NEIGHBOURS_SQL = """
WITH moi AS (
    SELECT centroid FROM arac.project_registry WHERE scope = %(path)s LIMIT 1
)
SELECT pr.scope                                                           AS path,
       round((pr.centroid <=> (SELECT centroid FROM moi))::numeric, 4)    AS distance,
       pr.member_count,
       pr.updated_at,
       '/cc/v1/scopes/' || pr.scope                                       AS href
  FROM arac.project_registry pr
 WHERE pr.scope <> %(path)s
   AND (SELECT centroid FROM moi) IS NOT NULL
 ORDER BY pr.centroid <=> (SELECT centroid FROM moi)
 LIMIT %(neighbours)s"""


#: L'absence assumée du voisinage : un scope sans centroïde n'a pas « aucun
#: voisin », il a un voisinage NON CALCULABLE. Six scopes peuplés sont dans ce
#: cas. Rendre `[]` sans le dire ferait croire à un territoire isolé.
_NO_CENTROID: dict[str, Any] = {
    "state": "unavailable",
    "reason": ("ce territoire n'a pas de centroïde dans arac.project_registry : "
               "aucune distance sémantique n'est calculable"),
    "gesture": "recalculer le registre de projets (recompute du cortex) pour ce scope",
    "substitute": "voisinage atome par atome depuis /cc/v1/atoms/{id}",
    "operator": "pgvector <=> (distance cosinus) sur project_registry.centroid",
}


def _provenance_block(header: dict[str, Any]) -> dict[str, Any]:
    """Ce que le compte de conversations NE dit pas : les atomes sans origine.

    La phrase vit dans ``entities.provenance_block`` — écrite UNE fois, servie
    par la fiche de scope ET par la fiche de projet. Deux formulations
    divergeraient, et le cockpit servirait deux vérités sur la même absence.

    Le bloc est servi même quand tout est traçable : une absence d'absence est une
    information, et un bloc qui n'apparaît qu'en cas de problème apprend au lecteur
    à ne plus le chercher.
    """
    return entities.provenance_block(header.get("atoms_active"),
                                     header.get("atomes_sans_conversation"),
                                     header.get("atomes_provenance_legacy"))


def scope_detail(path: str) -> dict[str, Any]:
    """Un territoire, ouvert : ce qu'il contient, ce qu'il doute, ce qu'il oublie.

    Le chemin est accepté encodé (``travail%2Ffinance``) comme décodé : le
    décodage se fait ici et une seule fois, et la valeur ne touche JAMAIS le
    corps d'une requête — elle est liée en paramètre. Surface d'injection nulle.
    """
    raw = entities._clean(path) or ""
    # Un proxy peut décoder ou non `%2F` : on décode systématiquement, ce qui
    # rend les deux formes équivalentes. Un scope ne contient jamais de `%`,
    # donc ce décodage ne peut pas détruire un chemin légitime.
    resolved = entities._clean(unquote(raw)) or ""
    if not resolved:
        return entities._unavailable("chemin de scope vide")
    if len(resolved) > 200:
        return entities._unavailable("chemin de scope trop long (200 caractères au plus)",
                                     path=resolved[:200])

    proj_sql, proj_params = _projects_for_scope_sql()
    params: dict[str, Any] = {
        "path": resolved,
        "slash": _SLASH,
        "days": _EVOLUTION_DAYS,
        "fragile_limit": _FRAGILE_LIMIT,
        "list_limit": _LIST_LIMIT,
        "history_limit": _HISTORY_LIMIT,
        "per_type": _HISTORY_PER_TYPE,
        "neighbours": _NEIGHBOURS,
    } | proj_params

    started = time.perf_counter()
    try:
        with entities._readonly() as conn:
            header = entities._one(conn, _HEADER_SQL, params, where="scope.header") or {}
            if not header or (header.get("atoms_total") or 0) == 0:
                # Un scope inconnu du savoir peut exister au registre de projets :
                # on ne conclut à l'absence qu'après avoir regardé les deux.
                if not header.get("centroid_known"):
                    return entities._unavailable(
                        f"aucun atome ne porte le scope {resolved!r}, "
                        "et aucun centroïde ne le connaît",
                        path=resolved,
                        evidence={"kind": "sql",
                                  "sql": entities._sql_text(conn, _HEADER_SQL, params),
                                  "label": "la requête qui n'a rien trouvé"},
                    )

            coverage = entities._rows(conn, _COVERAGE_SQL, params, where="scope.coverage")
            tags = entities._rows(conn, _TAGS_SQL, params, where="scope.tags")
            evolution = entities._rows(conn, _EVOLUTION_SQL, params, where="scope.evolution")
            distribution = entities._rows(conn, _DISTRIBUTION_SQL, params,
                                          where="scope.distribution")
            fragile = entities._rows(conn, _FRAGILE_SQL, params, where="scope.fragile")
            conversations = entities._rows(conn, _CONVERSATIONS_SQL, params,
                                           where="scope.conversations")
            projects = entities._rows(conn, proj_sql, params, where="scope.projects")
            recall = entities._one(conn, _RECALL_SQL, params, where="scope.recall") or {}
            history = entities._rows(conn, _HISTORY_SQL, params, where="scope.history")

            queries = [entities._sql_text(conn, s, params) for s in (
                _HEADER_SQL, _COVERAGE_SQL, _TAGS_SQL, _EVOLUTION_SQL, _DISTRIBUTION_SQL,
                _FRAGILE_SQL, _CONVERSATIONS_SQL, proj_sql, _RECALL_SQL, _HISTORY_SQL,
            )]

            # Le voisinage dépend d'un centroïde ET de pgvector. Il manque à six
            # territoires peuplés : on le DIT, on ne rend pas une liste muette.
            if header.get("centroid_known"):
                try:
                    neighbours = entities._rows(conn, _NEIGHBOURS_SQL, params,
                                                where="scope.neighbours")
                    neighbours_state: dict[str, Any] = {
                        "state": "ok", "reason": None,
                        "operator": "pgvector <=> (distance cosinus) sur project_registry.centroid",
                    }
                    queries.append(entities._sql_text(conn, _NEIGHBOURS_SQL, params))
                except Exception as exc:  # noqa: BLE001 — organe optionnel
                    # Message autoporteur : `extra=` n'est rendu par aucun formateur
                    # de ce service (cf. entities._failure).
                    #
                    # LE DOMAINE NE SORT PLUS EN CLAIR, et ce n'est pas un excès de
                    # prudence : la liste des domaines est la taxonomie que le
                    # propriétaire a ÉCRITE LUI-MÊME pendant l'entretien
                    # d'installation, pour nommer les pans de sa vie. Le journal
                    # systemd appartient à la machine et la désinstallation ne sait
                    # pas le purger ; `ops/uninstall_check.sh` disait déjà d'un
                    # domaine que « c'est la forme de la mémoire de quelqu'un »
                    # pendant que cette ligne-ci l'imprimait. L'empreinte est
                    # stable : corréler quarante incidents sur le même domaine
                    # reste possible, le lire ne l'est plus. La raison de
                    # l'exception passe par `journal.raison` — son message porte,
                    # pour une erreur PostgreSQL, la ligne fautive entière.
                    logger.warning("cc_v1.scope_neighbours_failed scope_sha8=%s raison=%s",
                                   sha8(resolved), raison(exc),
                                   extra={"scope_sha8": sha8(resolved),
                                          "error": type(exc).__name__},
                                   exc_info=True)
                    neighbours = []
                    neighbours_state = {
                        "state": "unavailable",
                        "reason": (f"voisinage sémantique indisponible "
                                   f"({raison(exc)})"),
                    }
            else:
                neighbours = []
                neighbours_state = dict(_NO_CENTROID)
    except Exception as exc:  # noqa: BLE001
        return entities._failure(f"scope:{resolved}", exc) | {"path": resolved}

    is_root = bool(header.get("is_root_scope"))
    invisibles = header.get("atoms_active") if is_root else 0

    return {
        "state": "ok",
        "path": resolved,
        "header": header,
        "coverage": {
            "kinds": coverage,
            "tags": tags,
            "structurantes": "gotcha, decision, state, pattern",
            "note": ("agent_message est du transport entre nœuds, jamais du savoir : "
                     "il n'est compté nulle part ici"),
        },
        "evolution": evolution,
        "evolution_window_days": _EVOLUTION_DAYS,
        "confidence": {
            "distribution": distribution,
            "fragile": fragile,
            "fragile_below": _FRAGILE_BELOW,
            "note": (f"« fragile » = score sous {_FRAGILE_BELOW} OU absence de score ; "
                     "un atome sans score n'est pas un atome sûr, c'est un atome non jugé"),
        },
        "conversations": conversations,
        # RÈGLE I2 : le compte de conversations ne doit jamais être servi seul.
        # « 251 atomes actifs » et « 3 conversations » côte à côte se lisent comme
        # « 3 conversations ont produit 251 atomes » — faux dès qu'une partie du
        # corpus a perdu sa provenance (76 pour cent sur le cerveau de référence).
        # L'absence est donc dite, chiffrée en SQL, avec son geste et son substitut.
        "provenance": _provenance_block(header),
        "projects": projects,
        "recall": recall,
        "debt": {
            "is_root_scope": is_root,
            "atoms_invisible_au_rappel": invisibles,
            "raison": (
                f"ce scope est une RACINE : ses {invisibles} atomes actifs sont "
                "invisibles au rappel, ils ne remontent jamais dans un contexte "
                "servi."
                if is_root else
                "ce scope porte au moins un niveau de profondeur : ses atomes sont "
                "candidats au rappel."
            ),
            "gesture": ("déplacer ces atomes sous une feuille « racine/sujet »"
                        if is_root else None),
        },
        "history": history,
        "history_note": (
            f"chronologie plafonnée à {_HISTORY_PER_TYPE} événements par type puis "
            f"{_HISTORY_LIMIT} au total ; le champ « rang » donne la position de "
            "chaque événement dans son propre type, pour que la troncature se voie"
        ),
        "neighbours": neighbours,
        "neighbours_state": neighbours_state,
        "evidence": {
            "kind": "sql",
            "sql": queries[0],
            "label": f"le territoire {resolved}, tel que la base le décrit",
            "queries": queries,
        },
        "computed_at": service._now(),
        "duration_ms": service._ms(started),
    }


# ============================================================================
# Enregistrement — GET uniquement, session + journal, garde de collision
# ============================================================================


def _already_registered(a: FastAPI) -> list[str]:
    """Les routes de ce module déjà déclarées ailleurs sur l'application.

    FastAPI n'interdit pas deux déclarations du même chemin : il garde
    SILENCIEUSEMENT la première et ignore la seconde. Un doublon ne casserait
    donc rien de visible — il ferait juste servir un autre code que celui qu'on
    lit. On préfère le voir et le journaliser.
    """
    existing = {getattr(r, "path", None) for r in getattr(a, "routes", [])}
    return [p for p in ROUTES if p in existing]


def register(
    a: FastAPI,
    session_api: Callable[..., Any],
    audit_read_log: Callable[[str, str], Any],
) -> None:
    """Enregistre ``/cc/v1/scopes/tree`` et ``/cc/v1/scopes/{path}``.

    Args:
        a: l'instance FastAPI du Control Center.
        session_api: la dépendance de session en mode API (401 JSON si absente).
        audit_read_log: le journal de lecture du socle (chemin, principal).

    N'écrase jamais une route existante : en cas de collision, elle est
    journalisée et l'enregistrement est abandonné. ``entities.py`` conserve
    ``GET /cc/v1/scopes`` (la liste plate) ; ce module ne la touche pas.
    """
    collisions = _already_registered(a)
    if collisions:
        logger.error("cc_v1.scopes_route_collision paths=%s", collisions,
                     extra={"paths": collisions})
        raise RuntimeError(
            "cc_v1.scopes : collision de routes, enregistrement abandonné : "
            f"{collisions}. Ces chemins sont déjà déclarés ailleurs."
        )

    # ------------------------------------------------------------------------
    # ORDRE NORMATIF : /tree AVANT /{path:path}. Le second motif capture les
    # barres obliques (un scope s'écrit « racine/feuille ») et avalerait donc
    # « tree » s'il était déclaré en premier. FastAPI résout dans l'ordre de
    # déclaration : ici, l'ordre des deux blocs EST le contrat.
    # ------------------------------------------------------------------------

    @a.get(ROUTES[0])
    def cc_v1_scopes_tree(
        principal: dict = Depends(session_api),
        limit: int = Query(default=entities.MAX_LIMIT, ge=1, le=entities.MAX_LIMIT),
    ) -> JSONResponse:
        """L'arborescence enrichie : poids, doute, oubli, dette, voisinage projet.

        Complète ``GET /cc/v1/scopes`` (liste plate) sans la remplacer : chaque
        ligne porte de quoi décider — ce que le territoire pèse, ce qu'il oublie,
        ce dont il doute — et un ``href`` vers sa fiche.
        """
        audit_read_log(ROUTES[0], principal.get("sub", "?"))
        return JSONResponse(scopes_tree(limit=limit))

    @a.get(ROUTES[1])
    def cc_v1_scope_detail(path: str, principal: dict = Depends(session_api)) -> JSONResponse:
        """Un territoire ouvert : couverture, évolution, confiance, rappel, dette.

        Un chemin inconnu ne lève pas : il rend ``state='unavailable'`` avec sa
        raison ET la requête qui n'a rien trouvé.
        """
        audit_read_log(f"{_PREFIX}/scopes/{path}", principal.get("sub", "?"))
        return JSONResponse(scope_detail(path))
