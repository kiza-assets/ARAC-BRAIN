"""Famille « projets » — le savoir vu par intention, pas par rangement.

Un scope dit OÙ un atome est rangé. Un projet dit À QUOI il sert. Les deux ne
coïncident pas, et c'est volontaire :

    un chantier de rénovation traverse ``perso/logement`` ET ``travail/finance``.

Un projet est donc une **vue** — une règle de sélection appliquée au savoir
vivant — et non un dossier. Trois conséquences structurelles, qui expliquent
toute la forme de ce module :

1. **Un atome peut appartenir à plusieurs projets.** Les décomptes par projet ne
   s'additionnent donc PAS en un total : un projet transverse est presque
   entièrement inclus dans deux autres. Chaque fois qu'un total est produit,
   il l'est en ``count(DISTINCT id)``, jamais en somme de colonnes — une somme
   de colonnes compterait deux fois le même atome et mentirait.

2. **Un projet peut être vide.** La règle existe indépendamment du savoir : la
   preuve part donc des règles déclarées et leur rattache le savoir par jointure
   externe, pour qu'un projet sans atome apparaisse comme vide plutôt que de
   disparaître silencieusement de l'interface.

3. **Du savoir peut n'appartenir à aucun projet.** C'est la mesure la plus utile
   de la famille : un scope peuplé que nulle règle ne cite est du savoir qu'aucune
   intention ne réclame. Il a sa métrique et sa preuve.

LES RÈGLES SONT LES VÔTRES : elles viennent de ``config/projects.toml`` (modèle
commenté : ``config/projects.example.toml``). Le dépôt n'en propose aucune.
Sans ce fichier, la famille rend « aucun projet déclaré » — jamais un chiffre
inventé.

Elles sont traduites en SQL UNE SEULE FOIS, par ``cc_v1/projects.py``, et toutes
les métriques en dérivent. Une règle qui changerait à un endroit et pas à l'autre
produirait une valeur et une preuve contradictoires : le partage du fragment rend
cette contradiction impossible par construction.

RAPPELS DU SOCLE :

- ``agent_message`` est du TRANSPORT, jamais du savoir : il est exclu partout.
- Seul le statut ``active`` est rappelable : tout ce module ne parle que de lui.
- Les motifs (mots-clés) s'appliquent à ``key`` ET à ``tags``, sans distinction
  de casse.
- Toute l'arithmétique est en SQL. Les requêtes ci-dessous sont rejouables telles
  quelles depuis un terminal.

LECTURE SEULE : aucune instruction mutante, invariant vérifié à l'instanciation
par ``Metric.__post_init__`` et par ``tests/test_cc_v1_registry.py``.
"""

from __future__ import annotations

from control_center.cc_v1.projects import projects_table_cte
from control_center.cc_v1.metric import Metric

__all__ = ["METRICS"]


# ---------------------------------------------------------------------------
# LES RÈGLES DE PROJET, traduites en SQL littéral.
#
# ``scopes``  : motifs LIKE. Sans joker, égalité stricte ; avec ``%``, toute une
#               branche (``travail/%``). Un préfixe déclaré engendre les DEUX :
#               la branche ET la racine nue, parce qu'un atome posé sur une
#               racine est invisible au rappel et qu'une dette qu'on ne compte
#               pas ne se résorbe jamais.
# ``motifs``  : expression régulière, insensible à la casse, appliquée à ``key``
#               et à chaque ``tag``. NULL = aucun filtre.
#
# Le fragment est engendré par ``cc_v1/projects.py``, qui valide et échappe
# chaque valeur avant de la laisser entrer dans une chaîne SQL.
# ---------------------------------------------------------------------------

#
# COMMENTAIRE DE BLOC, JAMAIS `--` (règle 9) : ce fragment est interpolé dans
# 27 métriques dont le SQL est SERVI APLATI SUR UNE LIGNE (service.py:247-248,
# `" ".join(sql.split())`). Un `--` en tête avalait alors la requête ENTIÈRE :
# copiée dans psql, elle ne rendait RIEN (rc=0, zéro ligne) au lieu du chiffre
# affiché. `/* … */` survit à l'aplatissement — la preuve redevient opposable.

_PROJETS_CTE = projects_table_cte() + """
    , savoir AS (
        SELECT a.id, a.kind, a.scope, a.key, a.tags,
               a.confidence_score, a.created_at, a.updated_at
          FROM arac.memory_atoms a
         WHERE a.status = 'active'
           AND a.kind <> 'agent_message'
    ), membres AS (
        SELECT p.rang, p.projet, s.id, s.kind, s.scope, s.key,
               s.confidence_score, s.created_at
          FROM savoir s
          JOIN projets p
            ON s.scope LIKE ANY (p.scopes)
           AND (p.motifs IS NULL
                OR s.key ~* p.motifs
                OR EXISTS (SELECT 1
                             FROM unnest(coalesce(s.tags, '{}'::text[])) AS t
                            WHERE t ~* p.motifs))
    )
"""


METRICS: tuple[Metric, ...] = (

    # ============================================== 1. LE PAYSAGE DES PROJETS
    Metric(
        key="projects_active_total",
        label="Projets vivants",
        unit="projets",
        definition="Projets déclarés dont la règle de sélection ramène au moins un atome de savoir vivant.",
        formula="count(DISTINCT projet parmi les règles déclarées WHERE atomes actifs > 0)",
        domain="projets",
        window="instant",
        target={"warn": 7, "critical": 5, "direction": "up"},
        sql=_PROJETS_CTE + """
            SELECT count(DISTINCT projet) AS value FROM membres
        """,
        evidence_label="Les huit règles déclarées, ce qu'elles ramènent, et leur état — une règle vide apparaît quand même",
        evidence_sql=_PROJETS_CTE + """
            SELECT p.projet,
                   array_to_string(p.scopes, ' · ')             AS regle_scopes,
                   coalesce(p.motifs, '(aucun filtre)')         AS regle_motifs,
                   count(m.id)                                  AS atomes,
                   count(DISTINCT m.scope)                      AS scopes_traverses,
                   count(DISTINCT m.kind)                       AS natures,
                   max(m.created_at)                            AS dernier_atome,
                   CASE WHEN count(m.id) = 0 THEN 'règle vide — aucun savoir ne la satisfait'
                        WHEN max(m.created_at) < now() - interval '30 days' THEN 'en veille'
                        ELSE 'vivant' END                       AS etat
              FROM projets p
              LEFT JOIN membres m ON m.projet = p.projet
             GROUP BY p.rang, p.projet, p.scopes, p.motifs
             ORDER BY p.rang
        """,
    ),
    Metric(
        key="projects_atoms_covered",
        label="Savoir rattaché à un projet",
        unit="atomes",
        definition="Atomes de savoir vivants qu'au moins une règle de projet ramène.",
        formula="count(DISTINCT id) sur les atomes actifs satisfaisant au moins une règle",
        domain="projets",
        window="instant",
        sql=_PROJETS_CTE + """
            SELECT count(DISTINCT id) AS value FROM membres
        """,
        evidence_label="Le savoir projet par projet — les colonnes ne s'additionnent pas : un atome peut compter dans plusieurs projets",
        evidence_sql=_PROJETS_CTE + """
            SELECT m.projet,
                   count(*)                                     AS atomes,
                   round(100.0 * count(*)
                         / nullif((SELECT count(*) FROM savoir), 0), 1) AS part_du_savoir_pct,
                   count(DISTINCT m.scope)                      AS scopes_traverses,
                   round(avg(m.confidence_score), 1)            AS confiance_moyenne,
                   min(m.created_at)                            AS premier_atome,
                   max(m.created_at)                            AS dernier_atome,
                   count(*) FILTER (WHERE m.created_at > now() - interval '30 days') AS atomes_30j
              FROM membres m
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="projects_coverage_ratio",
        label="Couverture du savoir par les projets",
        unit="%",
        definition="Part du savoir vivant qu'au moins une règle de projet réclame.",
        formula="atomes rattachés à au moins un projet / atomes actifs hors agent_message × 100",
        domain="projets",
        window="instant",
        target={"warn": 70, "critical": 50, "direction": "up"},
        sql=_PROJETS_CTE + """
            SELECT round(100.0 * (SELECT count(DISTINCT id) FROM membres)
                         / nullif((SELECT count(*) FROM savoir), 0), 1) AS value
        """,
        evidence_label="Scope par scope : combien de projets le voient, et lesquels",
        evidence_sql=_PROJETS_CTE + """
            SELECT s.scope,
                   count(*)                                     AS atomes,
                   count(DISTINCT m.projet)                      AS projets_qui_le_voient,
                   coalesce(string_agg(DISTINCT m.projet, ' · ' ORDER BY m.projet),
                            '— aucun projet —')                 AS projets,
                   count(*) FILTER (WHERE m.projet IS NULL)      AS atomes_non_vus,
                   (s.scope NOT LIKE '%/%')                      AS scope_racine
              FROM savoir s
              LEFT JOIN membres m ON m.id = s.id
             GROUP BY s.scope
             ORDER BY 2 DESC
        """,
    ),

    # ================================================= 2. ACTIVITÉ ET VEILLE
    Metric(
        key="projects_busiest_30d",
        label="Projet le plus actif",
        unit="atomes / 30 jours",
        definition="Nombre d'atomes produits sur trente jours par le projet le plus actif, dont le nom est porté par le détail.",
        formula="max(atomes créés depuis 30 jours) par projet",
        domain="projets",
        window="30d",
        sql=_PROJETS_CTE + """
            , activite AS (
                SELECT projet,
                       count(*) FILTER (WHERE created_at > now() - interval '30 days') AS atomes_30j
                  FROM membres
                 GROUP BY 1
            )
            SELECT max(atomes_30j) AS value,
                   (SELECT projet FROM activite
                     ORDER BY atomes_30j DESC, projet LIMIT 1) AS detail
              FROM activite
        """,
        evidence_label="Le rythme de chaque projet sur trois fenêtres, du plus actif au plus calme",
        evidence_sql=_PROJETS_CTE + """
            SELECT m.projet,
                   count(*) FILTER (WHERE m.created_at > now() - interval '7 days')  AS atomes_7j,
                   count(*) FILTER (WHERE m.created_at > now() - interval '30 days') AS atomes_30j,
                   count(*) FILTER (WHERE m.created_at > now() - interval '90 days') AS atomes_90j,
                   count(*)                                     AS atomes_total,
                   round(100.0 * count(*) FILTER (WHERE m.created_at > now() - interval '30 days')
                         / nullif(count(*), 0), 1)              AS part_recente_pct,
                   max(m.created_at)                            AS dernier_atome,
                   round(extract(epoch FROM (now() - max(m.created_at))) / 86400, 1) AS jours_depuis
              FROM membres m
             GROUP BY 1
             ORDER BY 3 DESC, 5 DESC
        """,
    ),
    Metric(
        key="projects_idle_total",
        label="Projets en veille",
        unit="projets",
        definition="Projets vivants dont aucun atome n'a été produit depuis plus de trente jours.",
        formula="count(projets WHERE max(created_at) < now() − 30 jours)",
        domain="projets",
        window="30d",
        target={"warn": 2, "critical": 4, "direction": "down"},
        sql=_PROJETS_CTE + """
            SELECT count(*) AS value
              FROM (
                SELECT projet FROM membres
                 GROUP BY 1
                HAVING max(created_at) < now() - interval '30 days'
              ) v
        """,
        evidence_label="Le silence de chaque projet, du plus long au plus court",
        evidence_sql=_PROJETS_CTE + """
            SELECT m.projet,
                   max(m.created_at)                            AS dernier_atome,
                   round(extract(epoch FROM (now() - max(m.created_at))) / 86400, 1) AS jours_de_silence,
                   CASE WHEN max(m.created_at) < now() - interval '90 days' THEN 'abandonné ?'
                        WHEN max(m.created_at) < now() - interval '30 days' THEN 'en veille'
                        ELSE 'actif' END                        AS etat,
                   count(*)                                     AS atomes,
                   count(*) FILTER (WHERE m.kind = 'todo')      AS taches_ouvertes,
                   count(*) FILTER (WHERE m.kind = 'question')  AS questions_ouvertes,
                   count(DISTINCT m.scope)                      AS scopes_traverses
              FROM membres m
             GROUP BY 1
             ORDER BY 3 DESC
        """,
    ),

    # ============================================ 3. NATURE DU SAVOIR PROJET
    Metric(
        key="projects_decisions_total",
        label="Décisions rattachées à un projet",
        unit="décisions",
        definition="Atomes de nature décision qu'au moins une règle de projet réclame.",
        formula="count(DISTINCT id) sur les membres de projet WHERE kind = 'decision'",
        domain="projets",
        window="instant",
        sql=_PROJETS_CTE + """
            SELECT count(DISTINCT id) FILTER (WHERE kind = 'decision') AS value
              FROM membres
        """,
        evidence_label="Les décisions par projet, avec leur densité et la plus récente d'entre elles",
        evidence_sql=_PROJETS_CTE + """
            SELECT m.projet,
                   count(*) FILTER (WHERE m.kind = 'decision')  AS decisions,
                   count(*)                                     AS atomes,
                   round(100.0 * count(*) FILTER (WHERE m.kind = 'decision')
                         / nullif(count(*), 0), 1)              AS densite_pct,
                   max(m.created_at) FILTER (WHERE m.kind = 'decision') AS derniere_decision,
                   round(avg(m.confidence_score) FILTER (WHERE m.kind = 'decision'), 1)
                                                                AS confiance_moyenne,
                   min(m.key) FILTER (WHERE m.kind = 'decision') AS exemple
              FROM membres m
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="projects_gotchas_total",
        label="Pièges rattachés à un projet",
        unit="pièges",
        definition="Atomes de nature piège, c'est-à-dire les erreurs déjà payées, qu'au moins une règle de projet réclame.",
        formula="count(DISTINCT id) sur les membres de projet WHERE kind = 'gotcha'",
        domain="projets",
        window="instant",
        sql=_PROJETS_CTE + """
            SELECT count(DISTINCT id) FILTER (WHERE kind = 'gotcha') AS value
              FROM membres
        """,
        evidence_label="Les pièges par projet, et le rapport entre pièges appris et décisions prises",
        evidence_sql=_PROJETS_CTE + """
            SELECT m.projet,
                   count(*) FILTER (WHERE m.kind = 'gotcha')    AS pieges,
                   count(*) FILTER (WHERE m.kind = 'decision')  AS decisions,
                   round(count(*) FILTER (WHERE m.kind = 'gotcha')::numeric
                         / nullif(count(*) FILTER (WHERE m.kind = 'decision'), 0), 2)
                                                                AS pieges_par_decision,
                   round(100.0 * count(*) FILTER (WHERE m.kind = 'gotcha')
                         / nullif(count(*), 0), 1)              AS densite_pct,
                   max(m.created_at) FILTER (WHERE m.kind = 'gotcha') AS dernier_piege,
                   min(m.key) FILTER (WHERE m.kind = 'gotcha')  AS exemple
              FROM membres m
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="projects_dormant_ratio",
        label="Part dormante du savoir projet",
        unit="%",
        definition="Part du savoir rattaché à un projet qui n'est jamais remonté dans un contexte servi.",
        formula="membres de projet jamais servis / membres de projet × 100",
        domain="projets",
        window="all",
        target={"warn": 40, "critical": 60, "direction": "down"},
        sql=_PROJETS_CTE + """
            , servis AS (
                SELECT DISTINCT unnest(served_ids)::uuid AS id FROM arac.context_receipts
            ), dormance AS (
                SELECT m.projet, m.id, (sv.id IS NULL) AS dormant
                  FROM membres m
                  LEFT JOIN servis sv ON sv.id = m.id
            )
            SELECT round(100.0 * count(DISTINCT id) FILTER (WHERE dormant)
                         / nullif(count(DISTINCT id), 0), 1) AS value
              FROM dormance
        """,
        evidence_label="La dormance projet par projet : ce qui a servi au moins une fois, et ce qui n'a jamais servi",
        evidence_sql=_PROJETS_CTE + """
            , servis AS (
                SELECT DISTINCT unnest(served_ids)::uuid AS id FROM arac.context_receipts
            ), dormance AS (
                SELECT m.projet, m.id, m.kind, m.created_at, (sv.id IS NULL) AS dormant
                  FROM membres m
                  LEFT JOIN servis sv ON sv.id = m.id
            )
            SELECT projet,
                   count(*)                                     AS atomes,
                   count(*) FILTER (WHERE dormant)              AS jamais_servis,
                   count(*) FILTER (WHERE NOT dormant)          AS deja_servis,
                   round(100.0 * count(*) FILTER (WHERE dormant)
                         / nullif(count(*), 0), 1)              AS dormance_pct,
                   count(*) FILTER (WHERE dormant AND kind = 'decision') AS decisions_dormantes,
                   count(*) FILTER (WHERE dormant AND kind = 'gotcha')   AS pieges_dormants,
                   max(created_at) FILTER (WHERE dormant)       AS dernier_atome_dormant
              FROM dormance
             GROUP BY 1
             ORDER BY 5 DESC
        """,
    ),

    # ====================================== 4. CE QUE LES PROJETS NE VOIENT PAS
    Metric(
        key="projects_orphan_scopes",
        label="Scopes orphelins",
        unit="scopes",
        definition="Scopes peuplés de savoir vivant qu'aucune règle de projet ne cite.",
        formula="count(scopes avec atomes actifs) − count(scopes cités par au moins une règle)",
        domain="projets",
        window="instant",
        target={"warn": 5, "critical": 10, "direction": "down"},
        sql=_PROJETS_CTE + """
            , peuples AS (
                SELECT scope FROM savoir GROUP BY 1
            )
            SELECT count(*) AS value
              FROM peuples pe
             WHERE NOT EXISTS (
                   SELECT 1 FROM projets p WHERE pe.scope LIKE ANY (p.scopes))
        """,
        evidence_label="Les scopes que nulle règle ne réclame, du plus peuplé au plus vide",
        evidence_sql=_PROJETS_CTE + """
            SELECT s.scope,
                   count(*)                                     AS atomes,
                   round(100.0 * count(*)
                         / nullif((SELECT count(*) FROM savoir), 0), 1) AS part_du_savoir_pct,
                   (s.scope NOT LIKE '%/%')                     AS scope_racine,
                   CASE WHEN s.scope NOT LIKE '%/%'
                        THEN 'racine nue — déjà invisible au rappel, et réclamée par aucun projet'
                        ELSE 'feuille rappelable, mais réclamée par aucun projet' END AS lecture,
                   count(*) FILTER (WHERE s.kind = 'decision')  AS decisions,
                   count(*) FILTER (WHERE s.kind = 'gotcha')    AS pieges,
                   min(s.created_at)                            AS premier_atome,
                   max(s.created_at)                            AS dernier_atome
              FROM savoir s
             WHERE NOT EXISTS (
                   SELECT 1 FROM projets p WHERE s.scope LIKE ANY (p.scopes))
             GROUP BY s.scope
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="projects_uncovered_atoms",
        label="Savoir qu'aucun projet ne réclame",
        unit="atomes",
        definition="Atomes de savoir vivants que pas une seule des huit règles de projet ne ramène.",
        formula="atomes actifs hors agent_message − atomes rattachés à au moins un projet",
        domain="projets",
        window="instant",
        target={"warn": 200, "critical": 500, "direction": "down"},
        sql=_PROJETS_CTE + """
            SELECT count(*) AS value
              FROM savoir s
             WHERE NOT EXISTS (SELECT 1 FROM membres m WHERE m.id = s.id)
        """,
        evidence_label="Le savoir hors projet, par scope et par motif — écarté par la règle, ou jamais cité par aucune",
        evidence_sql=_PROJETS_CTE + """
            SELECT s.scope,
                   count(*)                                     AS atomes_hors_projet,
                   CASE WHEN EXISTS (SELECT 1 FROM projets p
                                      WHERE s.scope LIKE ANY (p.scopes))
                        THEN 'scope cité par une règle, atomes écartés par ses mots-clés'
                        ELSE 'scope cité par aucune règle de projet' END AS motif,
                   (s.scope NOT LIKE '%/%')                     AS scope_racine,
                   count(*) FILTER (WHERE s.kind = 'decision')  AS decisions_perdues,
                   count(*) FILTER (WHERE s.kind = 'gotcha')    AS pieges_perdus,
                   round(avg(s.confidence_score), 1)            AS confiance_moyenne,
                   max(s.created_at)                            AS dernier_atome
              FROM savoir s
             WHERE NOT EXISTS (SELECT 1 FROM membres m WHERE m.id = s.id)
             GROUP BY s.scope, 3, 4
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="projects_shared_atoms",
        label="Savoir partagé entre projets",
        unit="atomes",
        definition="Atomes vivants que plusieurs règles de projet réclament simultanément, preuve qu'un projet est une vue et non un rangement.",
        formula="count(atomes WHERE nombre de projets satisfaits > 1)",
        domain="projets",
        window="instant",
        sql=_PROJETS_CTE + """
            SELECT count(*) AS value
              FROM (
                SELECT id FROM membres GROUP BY id HAVING count(DISTINCT projet) > 1
              ) v
        """,
        evidence_label="Les combinaisons de projets qui se partagent le même savoir, de la plus fréquente à la plus rare",
        evidence_sql=_PROJETS_CTE + """
            , appartenance AS (
                SELECT id,
                       min(scope)                               AS scope,
                       count(DISTINCT projet)                   AS nb_projets,
                       string_agg(DISTINCT projet, ' + ' ORDER BY projet) AS combinaison
                  FROM membres
                 GROUP BY id
            )
            SELECT combinaison,
                   nb_projets,
                   count(*)                                     AS atomes,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS part_pct,
                   count(DISTINCT scope)                        AS scopes_concernes,
                   string_agg(DISTINCT scope, ' · ' ORDER BY scope) AS scopes
              FROM appartenance
             GROUP BY 1, 2
             ORDER BY 2 DESC, 3 DESC
        """,
    ),
)
