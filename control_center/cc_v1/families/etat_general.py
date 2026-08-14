"""Famille « état général » — les constantes vitales et l'Indice de Santé Cérébrale.

C'est l'objet central de la spécification (§4.2) : le chiffre que ce cockpit existe
pour afficher. Il manquait — l'écran d'accueil affichait un substitut sous le libellé
« indice de santé », ce qu'une vérification adversariale a relevé comme bloquant.

## LE PRINCIPE DE COMPOSITION

L'indice agrège cinq constantes vitales pondérées, chacune normalisée sur 0–100 :

| # | Constante      | Poids | Mesure |
|---|----------------|------:|--------|
| V1 | Rappel        |  35 % | part des rappels servis en bande confiante |
| V2 | Fraîcheur     |  25 % | latence détection → premier atome |
| V3 | Digestion     |  20 % | débit face à la file |
| V4 | Intégrité     |  10 % | **minimum** des trois taux de perte |
| V5 | Connectivité  |  10 % | densité de liens — **non branchée** sur `arac.atom_links` |

**Renormalisation** : l'indice ne se calcule que sur les constantes disponibles,
les poids restants étant renormalisés. Une constante indisponible n'est comptée ni 0
(l'indice s'effondrerait faussement) ni 100 (il mentirait par optimisme). Le dénominateur
effectif est publié à côté de la valeur, pour que l'interface puisse dire
« 4 constantes sur 5 ».

## UN ÉCART ASSUMÉ AVEC LA SPÉCIFICATION

La spec définit V1 comme le score du benchmark NRB (14/20 → 70). **Ce score ne vit pas
en base** : il est produit par un harnais externe et déposé dans un fichier JSON. Le
registre, lui, ne lit que PostgreSQL — c'est ce qui rend chaque chiffre rejouable en psql.

Plutôt que d'introduire une source de vérité hors base, V1 mesure ici la **confiance
réellement observée sur les rappels servis** (`context_receipts`). C'est une mesure, pas
une estimation : elle dit ce que le cerveau a effectivement produit, pas ce qu'un jeu de
20 questions figées en dit. Elle est plus sévère, et plus vraie.

Pour rétablir la définition de la spec, il faudrait persister le résultat du NRB en base
(chantier moteur B11). L'indice le signale lui-même via `vital_recall.definition`.

## AUCUNE ARITHMÉTIQUE HORS SQL

Y compris la moyenne pondérée et sa renormalisation : tout est calculé par PostgreSQL,
donc rejouable à l'identique depuis un terminal. C'est le prix de l'opposabilité.
"""

from __future__ import annotations

from control_center.cc_v1.metric import Metric

__all__ = ["METRICS"]


# ---------------------------------------------------------------------------
# Fragments SQL partagés — chaque constante vitale, normalisée sur 0–100.
# Ils sont recopiés dans chaque métrique plutôt que composés dynamiquement :
# une requête littérale est une requête qu'on peut copier-coller dans psql.
# ---------------------------------------------------------------------------

#
# UN RAPPEL, UNE LIGNE. Depuis FOLD V2, chaque rappel réel écrit DEUX reçus
# — le moteur SERVI puis le moteur d'ombre v2-fold, même request_id, mêmes
# served_ids. Compter les lignes mélangeait donc deux populations aux bandes
# différentes et produisait une constante qu'AUCUN moteur n'a mesurée : 4,0 servi,
# quand le chemin servi vaut 5,6 et l'ombre 2,4. On retient le premier reçu écrit
# (le chemin servi) : c'est ce que l'appelant a réellement reçu, et cela reste
# juste si un moteur v3 en écrit un troisième.
# Commentaire de BLOC : ce SQL est servi aplati sur une ligne (règle 9).
_V1 = """
    SELECT round(100.0 * count(*) FILTER (WHERE cr.final_band IN ('high', 'medium'))
                 / nullif(count(*), 0), 1) AS v
      FROM arac.context_receipts cr
     WHERE NOT EXISTS (
           /* un rappel = un request_id ; le premier recu ecrit est le chemin servi */
           SELECT 1 FROM arac.context_receipts p
            WHERE p.request_id = cr.request_id AND p.id < cr.id)
"""

# Latence détection → premier atome, en jours, sur les conversations atomisées
# des 90 derniers jours. 0 j -> 100 ; 10 j -> 0 (pénalité de 10 points par jour).
#
# AGRÉGER PUIS JOINDRE, ET NON JOINDRE PUIS AGRÉGER (corrigé 2026-08-05).
# La forme précédente joignait conversations × raw_messages × memory_atoms AVANT
# de regrouper : le produit matérialisait 1 119 805 lignes par worker, soit
# 3 359 415 lignes produites pour 63 groupes conservés. Coût mesuré : 383 ms,
# et payé DEUX FOIS par appel à /cc/v1/metrics puisque `brain_health_index`
# interpole ce même fragment. La forme ci-dessous ne balaye raw_messages qu'une
# fois : 34 ms, valeur RIGOUREUSEMENT identique (74,0 avant comme après).
_V2 = """
    WITH prem_msg AS (
        SELECT m.conversation_id, min(m.received_at) AS premier
          FROM arac.raw_messages m
         GROUP BY m.conversation_id
    ), prem_atom AS (
        SELECT a.source_ref ->> 'conversation_uid' AS uid, min(a.created_at) AS premier
          FROM arac.memory_atoms a
         WHERE a.status = 'active' AND a.created_at > now() - interval '90 days'
         GROUP BY 1
    ), lat AS (
        SELECT extract(epoch FROM (pa.premier - pm.premier)) / 86400.0 AS days
          FROM arac.conversations c
          JOIN prem_msg  pm ON pm.conversation_id = c.id
          JOIN prem_atom pa ON pa.uid = c.conversation_uid
         WHERE pa.premier >= pm.premier
    )
    SELECT round(greatest(0, 100 - 10 * percentile_cont(0.5)
                 WITHIN GROUP (ORDER BY days))::numeric, 1) AS v
      FROM lat
"""

# Débit face à la file : 100 × débit / (débit + file/30).
# Un débit qui absorberait la file en 30 jours donne 50.
_V3 = """
    WITH f AS (
        SELECT count(*)::numeric AS n
          FROM arac.conversations c
         WHERE c.curated_through_message_id IS NULL
            OR c.curated_through_message_id < (
                   SELECT max(rm.id) FROM arac.raw_messages rm
                    WHERE rm.conversation_id = c.id)
    ), d AS (
        SELECT count(*)::numeric / 7 AS r FROM arac.conversations
         WHERE curated_at > now() - interval '7 days'
    )
    SELECT round(100 * d.r / nullif(d.r + f.n / 30, 0), 1) AS v FROM f, d
"""

# Intégrité = MINIMUM des trois sous-scores. Une propriété conjonctive :
# si UN canal perd de l'information, l'intégrité est compromise. La moyenne
# diluait le pire indicateur — c'est le défaut corrigé le 2026-08-03.
_V4 = """
    WITH t AS (
        SELECT
          (SELECT count(*) FILTER (WHERE status = 'quarantined')::numeric
                  / nullif(count(*), 0) FROM arac.run_receipts)              AS quarantaine,
          (SELECT count(*) FILTER (WHERE outcome <> 'accepted')::numeric
                  / nullif(count(*), 0) FROM arac.ingest_receipts)           AS refus,
          (SELECT count(*)::numeric
                  / nullif((SELECT count(*) FROM arac.raw_messages), 0)
             FROM arac.raw_message_revisions)                                AS divergence
    )
    SELECT round(least(
             100 * greatest(0, 1 - coalesce(quarantaine, 0) / (2 * 0.25)),
             100 * greatest(0, 1 - coalesce(refus, 0)       / (2 * 0.20)),
             100 * greatest(0, 1 - coalesce(divergence, 0)  / (2 * 0.05))
           )::numeric, 1) AS v
      FROM t
"""


METRICS: tuple[Metric, ...] = (

    Metric(
        key="vital_recall",
        label="V1 — Rappel",
        unit="/100",
        definition=("Part des rappels servis dans une bande de confiance haute ou moyenne, "
                    "mesurée sur le chemin SERVI : le moteur d'ombre n'entre pas dans le compte."),
        formula="rappels en bande high|medium / rappels × 100 (un rappel = un request_id)",
        domain="etat-general",
        window="all",
        target={"warn": 60, "critical": 40, "direction": "up"},
        sql=_V1.replace(" AS v", " AS value"),
        evidence_label=("La distribution des bandes de confiance par moteur : la constante se "
                        "lit sur les lignes `sert = true`, l'ombre est montrée à côté"),
        evidence_sql="""
            SELECT (NOT EXISTS (SELECT 1 FROM arac.context_receipts p
                                 WHERE p.request_id = cr.request_id AND p.id < cr.id))
                                                       AS sert,
                   cr.engine_version                   AS moteur,
                   cr.final_band,
                   count(*)                            AS recus,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS part_pct,
                   (cr.final_band IN ('high', 'medium')) AS compte_comme_confiant
              FROM arac.context_receipts cr
             GROUP BY 1, 2, 3
             ORDER BY 1 DESC, 4 DESC
        """,
    ),

    Metric(
        key="vital_freshness",
        label="V2 — Fraîcheur",
        unit="/100",
        definition="Vitesse à laquelle le cerveau transforme ce qu'il reçoit en savoir.",
        formula="100 − 10 × médiane(jours entre réception et premier atome), plancher 0",
        domain="etat-general",
        window="90d",
        target={"warn": 60, "critical": 40, "direction": "up"},
        sql=_V2.replace(" AS v", " AS value"),
        evidence_label="Les latences observées, conversation par conversation",
        evidence_sql="""
            SELECT c.conversation_uid,
                   min(m.received_at)                                   AS recue_le,
                   min(a.created_at)                                    AS premier_atome_le,
                   round((extract(epoch FROM (min(a.created_at) - min(m.received_at)))
                          / 86400.0)::numeric, 2)                       AS latence_jours
              FROM arac.conversations c
              JOIN arac.raw_messages m ON m.conversation_id = c.id
              JOIN arac.memory_atoms a
                ON a.source_ref ->> 'conversation_uid' = c.conversation_uid
               AND a.status = 'active'
             WHERE a.created_at > now() - interval '90 days'
             GROUP BY c.conversation_uid
            HAVING min(a.created_at) >= min(m.received_at)
             ORDER BY latence_jours DESC
             LIMIT 200
        """,
    ),

    Metric(
        key="vital_digestion",
        label="V3 — Digestion",
        unit="/100",
        definition="Capacité du débit courant à absorber la file en attente.",
        formula="100 × débit / (débit + file/30)",
        domain="etat-general",
        window="7d",
        target={"warn": 60, "critical": 40, "direction": "up"},
        sql=_V3.replace(" AS v", " AS value"),
        evidence_label="Les deux termes du rapport : la file et le débit qui la résorbe",
        evidence_sql="""
            WITH f AS (
                SELECT count(*) AS n FROM arac.conversations c
                 WHERE c.curated_through_message_id IS NULL
                    OR c.curated_through_message_id < (
                           SELECT max(rm.id) FROM arac.raw_messages rm
                            WHERE rm.conversation_id = c.id)
            ), d AS (
                SELECT count(*) AS cures FROM arac.conversations
                 WHERE curated_at > now() - interval '7 days'
            )
            SELECT 'file en attente' AS terme, f.n::text AS valeur FROM f
            UNION ALL SELECT 'curées sur 7 jours', d.cures::text FROM d
            UNION ALL SELECT 'débit quotidien', round(d.cures::numeric / 7, 2)::text FROM d
            LIMIT 3
        """,
    ),

    Metric(
        key="vital_integrity",
        label="V4 — Intégrité",
        unit="/100",
        definition="Résistance du système à la perte d'information, mesurée sur son maillon le plus faible.",
        formula="min(quarantaine, refus d'ingestion, divergence de hash) normalisés — R-26",
        domain="etat-general",
        window="all",
        target={"warn": 60, "critical": 40, "direction": "up"},
        sql=_V4.replace(" AS v", " AS value"),
        evidence_label="Les trois canaux de perte, et lequel commande la constante",
        evidence_sql="""
            WITH t AS (
                SELECT
                  (SELECT count(*) FILTER (WHERE status = 'quarantined')::numeric
                          / nullif(count(*), 0) FROM arac.run_receipts)      AS quarantaine,
                  (SELECT count(*) FILTER (WHERE outcome <> 'accepted')::numeric
                          / nullif(count(*), 0) FROM arac.ingest_receipts)   AS refus,
                  (SELECT count(*)::numeric
                          / nullif((SELECT count(*) FROM arac.raw_messages), 0)
                     FROM arac.raw_message_revisions)                        AS divergence
            )
            SELECT 'quarantaine des cycles' AS canal,
                   round(100 * coalesce(quarantaine, 0), 2)                  AS taux_pct,
                   round(100 * greatest(0, 1 - coalesce(quarantaine, 0) / 0.50)::numeric, 1) AS score
              FROM t
            UNION ALL
            SELECT 'refus d''ingestion', round(100 * coalesce(refus, 0), 2),
                   round(100 * greatest(0, 1 - coalesce(refus, 0) / 0.40)::numeric, 1) FROM t
            UNION ALL
            SELECT 'divergence de hash', round(100 * coalesce(divergence, 0), 2),
                   round(100 * greatest(0, 1 - coalesce(divergence, 0) / 0.10)::numeric, 1) FROM t
            ORDER BY 3 ASC
            LIMIT 3
        """,
    ),

    Metric(
        key="vital_connectivity",
        # Repli seulement : la raison servie est celle que la requête CONSTATE
        # (colonnes `reason`/`gesture` ci-dessous). Ce texte-ci ne sert que si la
        # requête elle-même n'a pas pu s'exécuter — il ne doit donc affirmer
        # l'état d'aucune table.
        unavailable_reason="la connectivité explicite n'a pas pu être constatée",
        unavailable_gesture="vérifiez que le cockpit peut interroger le schéma",
        substitute='voisinage sémantique et vue « jamais rappelés »',
        label="V5 — Connectivité",
        unit="/100",
        definition="Densité des liens explicites entre atomes — cette constante n'est pas encore branchée sur arac.atom_links.",
        formula="100 × (1 − part d'atomes orphelins) — requiert arac.atom_links",
        domain="etat-general",
        window="instant",
        # POURQUOI CETTE REQUÊTE CONSTATE AU LIEU D'AFFIRMER
        # --------------------------------------------------
        # La valeur reste NULL dans les deux cas, et c'est correct : ni 0
        # (l'indice s'effondrerait faussement), ni 100 (il mentirait). Mais les
        # deux absences ne sont pas la même, et le cockpit doit les distinguer.
        #
        # CE QUE CETTE BRANCHE-CI DISAIT, ET POURQUOI C'ÉTAIT FAUX
        # -------------------------------------------------------
        # Quand la table EST là — c'est-à-dire chez tous ceux qui ont suivi
        # l'installation — le geste servi était :
        #
        #     « alimentez arac.atom_links : aucun agent n'y écrit de lien
        #       aujourd'hui »
        #
        # Le dépôt livre pourtant ce producteur, et il tourne :
        # `app/services/atom_links.py` dérive les arêtes CERTAINES
        # (`supersedes`, `same_thread`) et les arêtes sémantiques, et
        # `agents/cortex/cycle.py` appelle `recompute()` à chaque tour — AVANT
        # le garde-dépense, donc même quand l'IA payante est coupée. Vérifié
        # sur une base neuve : 0 lien avant l'appel, 2 après, sans un centime
        # d'IA. Le lecteur qui appliquait ce geste partait chercher un agent
        # d'écriture qui tournait déjà trois fois par jour.
        #
        # Ce qui manque n'a jamais été le producteur : c'est le BRANCHEMENT de
        # cette constante sur le contenu de la table. C'est ce que la branche
        # dit maintenant, et cela reste vrai le jour où quelqu'un la branchera —
        # ce jour-là, la métrique rend un nombre et cette phrase n'est plus
        # servie du tout.
        #
        # La mesure elle-même ne peut pas figurer ici : PostgreSQL analyse la
        # requête entière avant de l'exécuter, donc un `FROM arac.atom_links`
        # ferait échouer la requête quand la table manque, y compris dans la
        # branche qui ne l'atteint jamais. Mesurer la connectivité demandera une
        # requête montée APRÈS le constat de présence — pas un CASE. C'est
        # exactement ce que fait `entities.links_dependency()`, en deux
        # aller-retours, pour les panneaux de navigation.
        sql="""
            SELECT NULL::numeric AS value,
                   CASE WHEN to_regclass('arac.atom_links') IS NULL
                        THEN 'table arac.atom_links absente du schéma : la couche '
                             || 'de liens explicites n''est pas déployée sur cette base'
                        ELSE 'table arac.atom_links présente : cette constante n''est '
                             || 'pas branchée sur son contenu — c''est la mesure qui '
                             || 'manque ici, pas les liens'
                        END AS reason,
                   CASE WHEN to_regclass('arac.atom_links') IS NULL
                        THEN 'appliquez les migrations en attente : alembic upgrade head'
                        ELSE 'branchez cette constante sur le contenu de la table : '
                             || 'part des atomes actifs portant au moins une arête'
                        END AS gesture
        """,
        evidence_label="L'état constaté de la dépendance, et le substitut retenu",
        # La preuve ne cite plus de nom de migration : elle montre ce que le
        # catalogue dit MAINTENANT, et laisse le lecteur rejouer la ligne.
        evidence_sql="""
            SELECT 'arac.atom_links'                            AS dependance,
                   (to_regclass('arac.atom_links') IS NOT NULL) AS deployee,
                   to_regclass('arac.atom_links')::text         AS resolue_en,
                   'le cycle du cortex recalcule cette table à chaque tour ; '
                   || 'ce qui manque ici est la mesure de densité'          AS ce_qui_manque,
                   'voisinage sémantique + vue « jamais rappelés »'         AS substitut
             LIMIT 1
        """,
    ),

    Metric(
        key="brain_health_index",
        label="Indice de santé cérébrale",
        unit="/100",
        definition="Synthèse pondérée des constantes vitales, renormalisée sur celles qui sont mesurables.",
        formula="Σ(constante × poids) / Σ(poids des constantes disponibles) — R-12",
        domain="etat-general",
        window="instant",
        target={"warn": 70, "critical": 55, "direction": "up"},
        sql=f"""
            WITH v AS (
                SELECT ({_V1}) AS v1, ({_V2}) AS v2, ({_V3}) AS v3, ({_V4}) AS v4,
                       NULL::numeric AS v5
            ), p AS (
                SELECT v1, v2, v3, v4, v5,
                       (CASE WHEN v1 IS NULL THEN 0 ELSE 35 END
                      + CASE WHEN v2 IS NULL THEN 0 ELSE 25 END
                      + CASE WHEN v3 IS NULL THEN 0 ELSE 20 END
                      + CASE WHEN v4 IS NULL THEN 0 ELSE 10 END
                      + CASE WHEN v5 IS NULL THEN 0 ELSE 10 END)::numeric AS poids
                  FROM v
            )
            SELECT round((coalesce(v1, 0) * 35 + coalesce(v2, 0) * 25
                        + coalesce(v3, 0) * 20 + coalesce(v4, 0) * 10
                        + coalesce(v5, 0) * 10) / nullif(poids, 0), 0) AS value
              FROM p
        """,
        evidence_label="Les cinq constantes, leur poids, et le dénominateur effectif",
        evidence_sql=f"""
            WITH v AS (
                SELECT ({_V1}) AS v1, ({_V2}) AS v2, ({_V3}) AS v3, ({_V4}) AS v4,
                       NULL::numeric AS v5
            )
            SELECT 'V1 — Rappel' AS constante, v1 AS valeur, 35 AS poids,
                   (v1 IS NOT NULL) AS comptee FROM v
            UNION ALL SELECT 'V2 — Fraîcheur',    v2, 25, (v2 IS NOT NULL) FROM v
            UNION ALL SELECT 'V3 — Digestion',    v3, 20, (v3 IS NOT NULL) FROM v
            UNION ALL SELECT 'V4 — Intégrité',    v4, 10, (v4 IS NOT NULL) FROM v
            UNION ALL SELECT 'V5 — Connectivité', v5, 10, (v5 IS NOT NULL) FROM v
             LIMIT 5
        """,
    ),
)
