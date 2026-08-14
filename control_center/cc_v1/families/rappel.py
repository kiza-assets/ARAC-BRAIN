"""Famille « rappel » — ce que le cerveau retrouve quand on l'interroge.

Le rappel est le seul étage que l'utilisateur voit vraiment : tout ce que la
chaîne a capturé, importé, analysé et indexé ne vaut que s'il ressort au bon
moment. Ces métriques mesurent donc la QUALITÉ du retour (distance top-1, bande
de confiance, remplissage de la demande) et son COÛT (latence), jamais le seul
volume — un compteur de rappels ne dit rien de leur pertinence.

Chaque reçu de ``arac.context_receipts`` est une trace complète : ce qui a été
demandé, ce qui a été servi, ce que le moteur d'ombre aurait servi, et pourquoi
il s'est arrêté. Toute l'arithmétique — percentiles, parts, ratios — est faite
par PostgreSQL : le BFF transporte, il ne calcule pas.

Attention aux tableaux ``uuid[]`` : ``array_length(x, 1)`` vaut NULL sur un
tableau vide, jamais 0. Toutes les requêtes de ce module passent par
``coalesce(array_length(x, 1), 0)`` — sans quoi un rappel qui ne sert RIEN
disparaîtrait des sommes au lieu d'y compter pour zéro.

UN RAPPEL N'EST PAS UNE LIGNE DE ``context_receipts``
-----------------------------------------------------
Depuis FOLD V2, **chaque rappel réel écrit DEUX reçus** : le moteur servi
(``ce-shadow-r3pur-v1``) puis le moteur d'ombre v2-fold, avec le MÊME
``request_id`` et les MÊMES ``served_ids`` (``app/routers/atoms.py`` appelle
``run_shadow_v2`` juste après ``run_shadow``, « deux reçus au même query_sha256 =
comparaison vivante v1/v2 par requête »). Mesuré le 2026-08-05 : 3 340 lignes
pour 1 709 rappels, dont 1 631 paires aux ``served_ids`` identiques.

Deux conséquences, corrigées ici :

1. **Compter les lignes doublait tous les volumes** — 102 rappels affichés sur
   24 h pour 51 réels, 89,1/j de cadence pour ~45.
2. **Mélanger les deux moteurs fabriquait une distribution qui n'existe nulle
   part** : médiane servie 0,4221 quand v1 mesure 0,4378 et v2 0,4147. La spec
   est explicite — appliquer les bandes v1 aux distances v2 n'est « qu'un
   PROXY d'observation ». Un chiffre qu'aucun moteur n'a produit n'est pas une
   mesure, c'est une moyenne d'apples et d'oranges.

Toutes les mesures qui parlent de RAPPELS passent donc par ``_UN_RECU_PAR_RAPPEL``
ci-dessous, qui retient **le premier reçu écrit** pour chaque ``request_id``.
Pourquoi le premier plutôt qu'un filtre sur ``engine_version`` : c'est le chemin
SERVI (le commentaire de colonne dit « prod, bit-identique — vérité de
référence »), c'est vérifié en base (le premier reçu de chaque request_id est un
v1 pour les 1 709 rappels), et cela reste juste le jour où un moteur v3 écrira un
troisième reçu — là où un ``NOT LIKE '%-v2-%'`` devrait être réécrit.

Seule ``recall_engine_versions_active`` regarde délibérément TOUS les reçus :
c'est la métrique qui compte les moteurs, elle serait absurde dédoublonnée.

LECTURE SEULE : aucune instruction mutante, invariant vérifié à l'instanciation.
"""

from __future__ import annotations

from control_center.cc_v1.metric import Metric

__all__ = ["METRICS"]


#: Un reçu par rappel : le PREMIER écrit pour chaque ``request_id``.
#: Commentaire de BLOC et non de ligne — ce SQL est servi aplati sur une ligne
#: (règle 9 : un ``--`` masquerait tout ce qui suit et rendrait la preuve muette).
_UN_RECU_PAR_RAPPEL = """
            /* Un rappel = un request_id. Depuis FOLD V2 chaque rappel écrit
               deux reçus (moteur servi v1, puis moteur d'ombre v2-fold) : compter
               les lignes doublait le chiffre, les mélanger fabriquait une
               distribution qu'aucun moteur n'a produite. On retient le premier
               reçu écrit, c'est-à-dire le chemin SERVI. */
            premier_recu AS (
                SELECT min(id) AS id
                  FROM arac.context_receipts
                 GROUP BY request_id
            )"""


METRICS: tuple[Metric, ...] = (

    # ============================================ qualité : distance au top-1
    Metric(
        key="recall_top1_median",
        label="Distance top-1 médiane",
        unit="distance",
        definition=("Distance médiane, après calibration, entre la question posée et le meilleur "
                    "atome retrouvé — sur le chemin SERVI, à l'exclusion du moteur d'ombre."),
        formula="percentile_cont(0,5) sur top1_distance_final du reçu servi de chaque rappel",
        domain="rappel",
        window="all",
        sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT round(percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY cr.top1_distance_final)::numeric, 4) AS value
              FROM arac.context_receipts cr
              JOIN premier_recu p ON p.id = cr.id
             WHERE cr.top1_distance_final IS NOT NULL
        """,
        evidence_label=("Distance brute contre distance finale, moteur par moteur : la valeur "
                        "servie est le `finale_p50` de la ligne `sert = true`"),
        # La ventilation par moteur EST la preuve : elle montre que la médiane servie
        # (0,4378) est celle du chemin servi, et que le moteur d'ombre en mesure une
        # autre (0,4147). Le chiffre autrefois affiché — 0,4221 — n'existait sur
        # AUCUNE de ces lignes : il était la médiane d'un mélange des deux populations.
        evidence_sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT (p.id IS NOT NULL)             AS sert,
                   cr.engine_version              AS moteur,
                   cr.calibration_version         AS calibration,
                   count(*)                       AS recus,
                   round(percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY cr.top1_distance_raw)::numeric, 4)   AS brute_p50,
                   round(percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY cr.top1_distance_raw)::numeric, 4)   AS brute_p95,
                   round(percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY cr.top1_distance_final)::numeric, 4) AS finale_p50,
                   round(percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY cr.top1_distance_final)::numeric, 4) AS finale_p95,
                   min(cr.created_at)             AS premier,
                   max(cr.created_at)             AS dernier
              FROM arac.context_receipts cr
              LEFT JOIN premier_recu p ON p.id = cr.id
             GROUP BY 1, 2, 3
             ORDER BY 1 DESC, 4 DESC
        """,
    ),
    Metric(
        key="recall_top1_p95",
        label="Distance top-1 au p95",
        unit="distance",
        definition=("Distance sous laquelle se situent 95 % des meilleurs atomes retrouvés : la "
                    "queue de distribution, celle qui déçoit — sur le chemin SERVI seulement."),
        formula="percentile_cont(0,95) sur top1_distance_final du reçu servi de chaque rappel",
        domain="rappel",
        window="all",
        sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT round(percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY cr.top1_distance_final)::numeric, 4) AS value
              FROM arac.context_receipts cr
              JOIN premier_recu p ON p.id = cr.id
             WHERE cr.top1_distance_final IS NOT NULL
        """,
        evidence_label=("Les distances par bande de confiance, moteur servi et moteur d'ombre "
                        "côte à côte — la valeur se lit sur les lignes `sert = true`"),
        evidence_sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT (p.id IS NOT NULL)              AS sert,
                   cr.engine_version               AS moteur,
                   coalesce(cr.final_band, 'non renseignée') AS bande_finale,
                   count(*)                        AS recus,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS part_pct,
                   round(percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY cr.top1_distance_raw)::numeric, 4)   AS brute_p50,
                   round(percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY cr.top1_distance_final)::numeric, 4) AS finale_p50,
                   round(percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY cr.top1_distance_final)::numeric, 4) AS finale_p95,
                   round(avg(coalesce(array_length(cr.served_ids, 1), 0))::numeric, 2)
                                                   AS atomes_servis_moyen
              FROM arac.context_receipts cr
              LEFT JOIN premier_recu p ON p.id = cr.id
             GROUP BY 1, 2, 3
             ORDER BY 1 DESC, 4 DESC
        """,
    ),

    # ==================================================== coût : latence servie
    Metric(
        key="recall_latency_p50",
        label="Latence de rappel médiane",
        unit="ms",
        definition=("Temps médian mis par le moteur SERVI pour produire un rappel : la latence "
                    "du moteur d'ombre n'est pas subie par l'appelant."),
        formula="percentile_cont(0,5) sur shadow_latency_ms du reçu servi de chaque rappel",
        domain="rappel",
        window="all",
        sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT round(percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY cr.shadow_latency_ms)::numeric, 1) AS value
              FROM arac.context_receipts cr
              JOIN premier_recu p ON p.id = cr.id
             WHERE cr.shadow_latency_ms IS NOT NULL
        """,
        evidence_label=("La latence par consommateur et par moteur : la valeur se lit sur les "
                        "lignes `sert = true`, les autres sont le coût de l'ombre"),
        evidence_sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT (p.id IS NOT NULL)             AS sert,
                   cr.consumer                    AS consommateur,
                   cr.engine_version              AS moteur,
                   count(*)                       AS recus,
                   round(percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY cr.shadow_latency_ms)::numeric, 1)  AS p50_ms,
                   round(percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY cr.shadow_latency_ms)::numeric, 1)  AS p95_ms,
                   round(max(cr.shadow_latency_ms)::numeric, 1)     AS max_ms,
                   count(*) FILTER (WHERE cr.shadow_error IS NOT NULL) AS erreurs
              FROM arac.context_receipts cr
              LEFT JOIN premier_recu p ON p.id = cr.id
             GROUP BY 1, 2, 3
             ORDER BY 1 DESC, 4 DESC
        """,
    ),
    Metric(
        key="recall_latency_p95",
        label="Latence de rappel au p95",
        unit="ms",
        definition=("Temps sous lequel 95 % des rappels SERVIS sont produits : la lenteur "
                    "réellement subie aux pires moments, hors moteur d'ombre."),
        formula="percentile_cont(0,95) sur shadow_latency_ms du reçu servi de chaque rappel",
        domain="rappel",
        window="all",
        sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT round(percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY cr.shadow_latency_ms)::numeric, 1) AS value
              FROM arac.context_receipts cr
              JOIN premier_recu p ON p.id = cr.id
             WHERE cr.shadow_latency_ms IS NOT NULL
        """,
        evidence_label="Les rappels servis les plus lents, avec ce qu'ils ont coûté et rapporté",
        evidence_sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT cr.created_at,
                   cr.consumer                    AS consommateur,
                   cr.engine_version              AS moteur,
                   round(cr.shadow_latency_ms::numeric, 1) AS latence_ms,
                   cr.k_requested                 AS k_demande,
                   coalesce(array_length(cr.served_ids, 1), 0) AS atomes_servis,
                   round(cr.top1_distance_final::numeric, 4)   AS distance_finale,
                   cr.final_band                  AS bande_finale,
                   cr.stop_reason                 AS motif_arret
              FROM arac.context_receipts cr
              JOIN premier_recu p ON p.id = cr.id
             WHERE cr.shadow_latency_ms IS NOT NULL
             ORDER BY cr.shadow_latency_ms DESC
             LIMIT 100
        """,
    ),

    # ======================================================= volume et cadence
    Metric(
        key="recall_served_24h",
        label="Rappels servis (24 h)",
        unit="rappels",
        definition=("Rappels produits et tracés au cours des dernières 24 heures. Un rappel = "
                    "un request_id, pas une ligne de reçu : depuis chaque rappel en "
                    "écrit deux (moteur servi + moteur d'ombre)."),
        formula="count(DISTINCT context_receipts.request_id WHERE created_at > now() - 24 h)",
        domain="rappel",
        window="24h",
        sql="""
            SELECT count(DISTINCT request_id) AS value
              FROM arac.context_receipts
             WHERE created_at > now() - interval '24 hours'
        """,
        evidence_label="Les dernières heures de rappel, heure par heure (reçus dédoublonnés)",
        evidence_sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT date_trunc('hour', cr.created_at) AS heure,
                   count(*)                       AS rappels,
                   count(DISTINCT cr.consumer)    AS consommateurs,
                   round(avg(coalesce(array_length(cr.served_ids, 1), 0))::numeric, 2)
                                                  AS atomes_servis_moyen,
                   round(percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY cr.top1_distance_final)::numeric, 4) AS distance_p50
              FROM arac.context_receipts cr
              JOIN premier_recu p ON p.id = cr.id
             GROUP BY 1
             ORDER BY 1 DESC
             LIMIT 48
        """,
    ),
    Metric(
        key="recall_served_7d",
        label="Cadence de rappel",
        unit="rappels / jour",
        definition=("Rappels produits par jour, moyenne sur les 7 derniers jours. Un rappel = "
                    "un request_id, pas une ligne de reçu."),
        formula="count(DISTINCT context_receipts.request_id sur 7 j) / 7",
        domain="rappel",
        window="7d",
        sql="""
            SELECT round(count(DISTINCT request_id)::numeric / 7, 1) AS value
              FROM arac.context_receipts
             WHERE created_at > now() - interval '7 days'
        """,
        evidence_label="Les rappels jour par jour (dédoublonnés), avec leur qualité du même jour",
        evidence_sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT cr.created_at::date            AS jour,
                   count(*)                       AS rappels,
                   count(DISTINCT cr.consumer)    AS consommateurs,
                   sum(coalesce(array_length(cr.served_ids, 1), 0)) AS atomes_servis,
                   count(*) FILTER (WHERE cr.final_band IN ('low', 'none')) AS confiance_basse,
                   round(percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY cr.shadow_latency_ms)::numeric, 1)  AS latence_p95_ms
              FROM arac.context_receipts cr
              JOIN premier_recu p ON p.id = cr.id
             GROUP BY 1
             ORDER BY 1 DESC
             LIMIT 30
        """,
    ),

    # ================================================ couverture du corpus
    Metric(
        key="recall_atoms_served_distinct",
        label="Atomes déjà servis",
        unit="atomes",
        definition="Atomes distincts qui sont remontés au moins une fois dans un contexte servi.",
        formula="count(DISTINCT unnest(context_receipts.served_ids))",
        # PAS de dédoublonnage par request_id : le DISTINCT porte déjà sur l'ATOME, et
        # les deux reçus d'un même rappel ont des `served_ids` identiques (vérifié :
        # 1 631 paires sur 1 631). Le compte est donc insensible au doublon d'écriture.
        # La PREUVE, elle, l'était : sa colonne `fois_servi` comptait les reçus, donc
        # affichait le double de la réalité. Elle compte désormais les RAPPELS et se
        # nomme `fois_servi_rappels` — un nom qui dit son unité.
        domain="rappel",
        window="all",
        sql="""
            WITH servis AS (
                SELECT DISTINCT unnest(served_ids)::uuid AS id FROM arac.context_receipts
            )
            SELECT count(*) AS value FROM servis
        """,
        evidence_label="Les atomes les plus servis, avec leur statut actuel",
        evidence_sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL},
            servis AS (
                SELECT unnest(cr.served_ids)::uuid AS id
                  FROM arac.context_receipts cr
                  JOIN premier_recu p ON p.id = cr.id
            )
            SELECT a.scope, a.kind, a.key, a.status,
                   count(*)                       AS fois_servi_rappels,
                   a.confidence_score             AS confiance,
                   a.created_at
              FROM servis s
              JOIN arac.memory_atoms a ON a.id = s.id
             GROUP BY a.id, a.scope, a.kind, a.key, a.status, a.confidence_score, a.created_at
             ORDER BY 5 DESC
             LIMIT 200
        """,
    ),
    Metric(
        key="recall_k_fill_ratio",
        label="Remplissage de la demande",
        unit="%",
        definition=("Part des atomes demandés qui sont effectivement servis par le moteur de "
                    "rappel, un reçu par rappel."),
        formula="Σ taille(served_ids) / Σ k_requested × 100, sur le reçu servi de chaque rappel",
        domain="rappel",
        window="all",
        # Sans le dédoublonnage, les 1 631 rappels ayant deux reçus pesaient DEUX FOIS
        # plus que les 78 qui n'en ont qu'un : une moyenne pondérée par un artefact
        # d'écriture, pas par l'usage.
        sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT round(100.0 * sum(coalesce(array_length(cr.served_ids, 1), 0))
                         / nullif(sum(cr.k_requested), 0), 1) AS value
              FROM arac.context_receipts cr
              JOIN premier_recu p ON p.id = cr.id
        """,
        evidence_label="Demandé, budgété, servi : les trois nombres, pour chaque taille de demande",
        evidence_sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT cr.k_requested                 AS k_demande,
                   count(*)                       AS rappels,
                   round(avg(cr.budget_k)::numeric, 2) AS budget_moyen,
                   round(avg(coalesce(array_length(cr.served_ids, 1), 0))::numeric, 2)
                                                  AS servis_moyen,
                   round(100.0 * sum(coalesce(array_length(cr.served_ids, 1), 0))
                         / nullif(sum(cr.k_requested), 0), 1) AS remplissage_pct,
                   round(avg(coalesce(array_length(cr.shadow_ids, 1), 0))::numeric, 2)
                                                  AS candidats_ombre_moyen
              FROM arac.context_receipts cr
              JOIN premier_recu p ON p.id = cr.id
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="recall_empty_ratio",
        label="Rappels vides",
        unit="%",
        definition=("Part des rappels qui ne servent aucun atome : la question est posée, le "
                    "cerveau ne répond rien. Un rappel = un request_id."),
        formula="rappels dont taille(served_ids)=0 / rappels × 100",
        domain="rappel",
        window="all",
        sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT round(100.0 * count(*) FILTER (
                             WHERE coalesce(array_length(cr.served_ids, 1), 0) = 0)
                         / nullif(count(*), 0), 3) AS value
              FROM arac.context_receipts cr
              JOIN premier_recu p ON p.id = cr.id
        """,
        evidence_label="La distribution du nombre d'atomes servis, du rappel vide au rappel plein",
        evidence_sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT coalesce(array_length(cr.served_ids, 1), 0) AS atomes_servis,
                   count(*)                       AS rappels,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 3) AS part_pct,
                   round(avg(cr.k_requested)::numeric, 2) AS k_demande_moyen,
                   min(cr.created_at)             AS premier,
                   max(cr.created_at)             AS dernier
              FROM arac.context_receipts cr
              JOIN premier_recu p ON p.id = cr.id
             GROUP BY 1
             ORDER BY 1
        """,
    ),

    # ============================================== réglage et provenance
    Metric(
        key="recall_scope_prefix_gain_ratio",
        label="Rappels aidés par le préfixe de scope",
        unit="%",
        definition=("Part des rappels où le filtrage par préfixe de scope a ramené au moins un "
                    "atome de plus, mesurée sur le moteur servi."),
        formula="rappels dont scope_prefix_gain > 0 / rappels × 100",
        domain="rappel",
        window="all",
        # `scope_prefix_gain` DIFFÈRE entre les deux reçus d'un même rappel sur 8 paires :
        # mélanger les moteurs ne faisait pas que doubler le dénominateur, il changeait
        # le numérateur. La mesure porte sur le chemin servi, celui que l'appelant a reçu.
        sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT round(100.0 * count(*) FILTER (WHERE cr.scope_prefix_gain > 0)
                         / nullif(count(*), 0), 2) AS value
              FROM arac.context_receipts cr
              JOIN premier_recu p ON p.id = cr.id
        """,
        evidence_label="Le gain apporté par le préfixe de scope, valeur par valeur",
        evidence_sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT cr.scope_prefix_gain           AS gain,
                   count(*)                       AS rappels,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS part_pct,
                   count(*) FILTER (WHERE cr.scope_filter IS NOT NULL) AS avec_filtre_de_scope,
                   round(avg(coalesce(array_length(cr.served_ids, 1), 0))::numeric, 2)
                                                  AS servis_moyen,
                   max(cr.created_at)             AS dernier
              FROM arac.context_receipts cr
              JOIN premier_recu p ON p.id = cr.id
             GROUP BY 1
             ORDER BY 1
        """,
    ),
    Metric(
        key="recall_engine_versions_active",
        label="Versions de rappel en usage",
        unit="versions",
        definition="Couples moteur × calibration ayant servi au moins un rappel sur les 30 derniers jours.",
        formula="count(DISTINCT (engine_version, calibration_version) sur 30 j)",
        # SEULE métrique de la famille à regarder TOUS les reçus, délibérément : c'est
        # elle qui compte les moteurs. La dédoublonner par request_id ne rendrait plus
        # jamais que le moteur servi et masquerait l'existence même du moteur d'ombre.
        domain="rappel",
        window="30d",
        sql="""
            SELECT count(*) AS value
              FROM (
                    SELECT DISTINCT engine_version, calibration_version
                      FROM arac.context_receipts
                     WHERE created_at > now() - interval '30 days'
                   ) versions
        """,
        evidence_label="Toutes les versions vues, leur volume, leur période et leur activité récente",
        evidence_sql="""
            SELECT engine_version                 AS moteur,
                   calibration_version            AS calibration,
                   count(*)                       AS recus,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS part_pct,
                   min(created_at)                AS premier,
                   max(created_at)                AS dernier,
                   count(*) FILTER (WHERE created_at > now() - interval '30 days')
                                                  AS recus_30j
              FROM arac.context_receipts
             GROUP BY 1, 2
             ORDER BY 3 DESC
        """,
    ),
    Metric(
        key="recall_top_consumer_share",
        label="Poids du consommateur dominant",
        unit="%",
        definition=("Part des rappels attribuable au consommateur le plus actif : elle dit si "
                    "le rappel sert un seul usage ou plusieurs."),
        formula="max(rappels par consumer) / total des rappels × 100",
        domain="rappel",
        window="all",
        sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT round(100.0 * max(rappels) / nullif(sum(rappels), 0), 1) AS value
              FROM (
                    SELECT cr.consumer, count(*) AS rappels
                      FROM arac.context_receipts cr
                      JOIN premier_recu p ON p.id = cr.id
                     GROUP BY cr.consumer
                   ) par_consommateur
        """,
        evidence_label="Les consommateurs de rappel, par volume, avec la qualité qu'ils obtiennent",
        evidence_sql=f"""
            WITH{_UN_RECU_PAR_RAPPEL}
            SELECT cr.consumer                    AS consommateur,
                   count(*)                       AS rappels,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS part_pct,
                   sum(coalesce(array_length(cr.served_ids, 1), 0)) AS atomes_servis,
                   round(percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY cr.top1_distance_final)::numeric, 4) AS distance_p50,
                   count(*) FILTER (WHERE cr.final_band IN ('low', 'none')) AS confiance_basse,
                   max(cr.created_at)             AS dernier
              FROM arac.context_receipts cr
              JOIN premier_recu p ON p.id = cr.id
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),
)
