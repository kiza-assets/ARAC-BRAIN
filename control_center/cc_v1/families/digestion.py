"""Famille « digestion » — l'entonnoir, et la comptabilité de ce qu'il perd.

La digestion est le seul endroit où une conversation devient du savoir. C'est
donc le seul endroit où du savoir peut se perdre sans que personne ne le voie.
Cette famille est construite autour d'une idée unique :

    Un entonnoir ne se juge pas à ce qui en sort, mais à ce qui disparaît
    entre deux maillons sans être compté.

D'où trois classes de métriques, dans cet ordre d'importance :

1. **L'entonnoir et ses taux de conversion** — détectées → absorbées → analysées
   → atomisées → retrouvées. Le maillon « reliée » (arêtes entre atomes) est
   structurellement INDISPONIBLE : cet étage ne compte pas les arêtes de
   ``arac.atom_links``. La métrique le DIT au lieu d'afficher un zéro, parce
   qu'un zéro affiché à la place d'une absence transforme une panne en résultat.

2. **Les équations de conservation** — un cycle déclare ``presented``,
   ``covered``, ``no_new_knowledge``, ``omitted``. Si la somme des trois derniers
   ne fait pas le premier, un passage a disparu du registre. Une deuxième
   équation, plus large, compare les passages réellement engagés (``items``) aux
   passages inscrits au registre de couverture. Une troisième confronte les
   compteurs de cycle à la file de revue. Les écarts ne sont pas cachés : ils
   ont leur propre métrique, avec leur propre seuil.

3. **Les pertes attribuables** — causes de quarantaine, cycles quarantinés sans
   fautif, taille des tranches perdues, ancienneté de la tête de file. Ce sont
   les endroits où l'on peut agir.

DEUX POINTS DE MÉTHODE, hérités du registre :

- Toute l'arithmétique est en SQL. Aucun ratio, aucun pourcentage, aucun
  percentile n'est calculé en Python ou dans le navigateur : les requêtes ci-
  dessous sont rejouables telles quelles depuis un terminal, donc opposables.
- ``agent_message`` est du TRANSPORT, jamais du savoir : aucun décompte
  d'atomes de cette famille ne l'inclut.

LECTURE SEULE : aucune instruction mutante, invariant vérifié à l'instanciation
par ``Metric.__post_init__`` et par ``tests/test_cc_v1_registry.py``.
"""

from __future__ import annotations

from control_center.cc_v1.metric import Metric

__all__ = ["METRICS"]


# ---------------------------------------------------------------------------
# Fragment partagé — le registre de comptabilité de la digestion.
#
# Cinq postes ont une double écriture : un compteur agrégé sur le cycle
# (``run_receipts``) et une ligne par objet dans la file de revue
# (``digestion_review_queue``). Les deux doivent dire la même chose. Les deux
# derniers postes sont là pour la lecture, pas pour l'écart : ils n'ont pas de
# contrepartie en file, et le SQL le déclare explicitement.
#
# Ce fragment est un littéral statique, sans aucune interpolation d'entrée : il
# est déclaré une seule fois pour que la valeur et sa preuve ne puissent pas
# diverger — un registre comptable dont les deux vues divergeraient ne prouverait
# plus rien.
# ---------------------------------------------------------------------------

_LEDGER_CTE = """
    WITH revue AS (
        SELECT drop_reason                        AS poste,
               count(*)                           AS lignes,
               min(created_at)                    AS premiere,
               max(created_at)                    AS derniere
          FROM arac.digestion_review_queue
         GROUP BY 1
    ), cycle(rang, poste, source_compteur, compteur, compte_dans_ecart) AS (
        SELECT 1, 'coverage_omitted',
               'run_receipts.coverage_omitted',
               coalesce(sum(coverage_omitted), 0), true
          FROM arac.run_receipts
        UNION ALL
        SELECT 2, 'policy_skip',
               'run_receipts.atoms_policy_skips',
               coalesce(sum(atoms_policy_skips), 0), true
          FROM arac.run_receipts
        UNION ALL
        SELECT 3, 'atom_quarantine',
               'run_receipts.atoms_quarantined',
               coalesce(sum(atoms_quarantined), 0), true
          FROM arac.run_receipts
        UNION ALL
        SELECT 4, 'kept_lower_confidence',
               'run_receipts.atoms_kept_lower_confidence',
               coalesce(sum(atoms_kept_lower_confidence), 0), true
          FROM arac.run_receipts
        UNION ALL
        SELECT 5, 'oversized_message',
               'run_receipts.messages_truncated',
               coalesce(sum(messages_truncated), 0), true
          FROM arac.run_receipts
        UNION ALL
        SELECT 6, 'oversized_message',
               'run_receipts.oversized_messages (longueur du tableau) — recompte',
               coalesce(sum(jsonb_array_length(
                   coalesce(oversized_messages, '[]'::jsonb))), 0), false
          FROM arac.run_receipts
        UNION ALL
        SELECT 7, 'conflit_409',
               'run_receipts.conflicts_409 — poste sans contrepartie en file',
               coalesce(sum(conflicts_409), 0), false
          FROM arac.run_receipts
    )
"""


METRICS: tuple[Metric, ...] = (

    # ======================================================== 1. L'ENTONNOIR
    Metric(
        key="digestion_funnel_conversion",
        label="Rendement de l'entonnoir",
        unit="%",
        definition="Part des conversations détectées qui ressortent de la digestion en ayant produit au moins un atome de savoir.",
        formula="conversations avec atoms_generated > 0 / conversations totales × 100",
        domain="digestion",
        window="all",
        target={"warn": 30, "critical": 15, "direction": "up"},
        sql="""
            SELECT round(100.0 * count(*) FILTER (WHERE coalesce(atoms_generated, 0) > 0)
                         / nullif(count(*), 0), 1) AS value
              FROM arac.conversations
        """,
        evidence_label="L'entonnoir maillon par maillon, avec le taux de conversion de chacun — et le maillon qu'on ne peut pas mesurer",
        evidence_sql="""
            WITH maillons(rang, maillon, unite, objets, mesurable, lecture) AS (
                VALUES
                  (1, 'détectées', 'conversations',
                      (SELECT count(*) FROM arac.conversations),
                      true,
                      'conversations connues du cerveau, toutes sources confondues'),
                  (2, 'absorbées', 'conversations',
                      (SELECT count(DISTINCT conversation_id) FROM arac.raw_messages),
                      true,
                      'conversations portant au moins un message brut en base'),
                  (3, 'analysées', 'conversations',
                      (SELECT count(*) FROM arac.conversations WHERE curated_at IS NOT NULL),
                      true,
                      'conversations passées par un cycle de curation abouti'),
                  (4, 'atomisées', 'conversations',
                      (SELECT count(*) FROM arac.conversations
                        WHERE coalesce(atoms_generated, 0) > 0),
                      true,
                      'conversations ayant produit au moins un atome'),
                  (5, 'reliées', 'arêtes',
                      NULL::bigint,
                      false,
                      /* La lecture DÉCOULE de l'état constaté : elle affirmait
                         « migration non appliquée » sans jamais regarder, et
                         continuait de l'affirmer une fois la table posée. */
                      CASE WHEN to_regclass('arac.atom_links') IS NULL
                           THEN 'INDISPONIBLE — table arac.atom_links absente du schéma : aucune arête entre atomes n''est matérialisée, donc rien à compter'
                           ELSE 'INDISPONIBLE — table arac.atom_links présente, mais cet étage ne compte pas encore ses arêtes'
                           END),
                  (6, 'retrouvées', 'atomes',
                      (SELECT count(*) FROM arac.memory_atoms a
                        WHERE a.status = 'active' AND a.kind <> 'agent_message'
                          AND EXISTS (SELECT 1 FROM arac.context_receipts cr
                                       WHERE a.id = ANY (cr.served_ids))),
                      true,
                      'atomes actifs déjà servis au moins une fois — changement d''unité assumé : aucun atome ne porte de lien résolvable vers sa conversation d''origine')
            )
            SELECT rang,
                   maillon,
                   unite,
                   objets,
                   CASE WHEN unite = lag(unite) OVER (ORDER BY rang)
                        THEN round(100.0 * objets
                                   / nullif(lag(objets) OVER (ORDER BY rang), 0), 1)
                   END                                        AS conversion_pct,
                   CASE WHEN unite = lag(unite) OVER (ORDER BY rang)
                        THEN lag(objets) OVER (ORDER BY rang) - objets
                   END                                        AS perte,
                   mesurable,
                   lecture
              FROM maillons
             ORDER BY rang
             LIMIT 6
        """,
    ),
    Metric(
        key="digestion_analysis_ratio",
        label="Conversion absorbées → analysées",
        unit="%",
        definition="Part des conversations absorbées que le curateur a réellement analysées jusqu'au bout.",
        formula="conversations avec curated_at / conversations avec au moins un message × 100",
        domain="digestion",
        window="all",
        target={"warn": 50, "critical": 25, "direction": "up"},
        sql="""
            SELECT round(100.0 * count(*) FILTER (WHERE c.curated_at IS NOT NULL)
                         / nullif(count(*) FILTER (
                               WHERE EXISTS (SELECT 1 FROM arac.raw_messages rm
                                              WHERE rm.conversation_id = c.id)), 0), 1) AS value
              FROM arac.conversations c
        """,
        evidence_label="Le maillon analysé source par source : ce qui est entré, ce qui a été lu, ce qui attend encore",
        evidence_sql="""
            SELECT c.source_type,
                   count(*)                                             AS absorbees,
                   count(*) FILTER (WHERE c.curated_at IS NOT NULL)     AS analysees,
                   round(100.0 * count(*) FILTER (WHERE c.curated_at IS NOT NULL)
                         / nullif(count(*), 0), 1)                      AS conversion_pct,
                   count(*) FILTER (WHERE c.curated_at IS NULL
                                      AND c.exclusion_reason IS NULL)   AS en_attente,
                   count(*) FILTER (WHERE c.exclusion_reason IS NOT NULL) AS exclues,
                   count(*) FILTER (WHERE c.last_curation_error IS NOT NULL) AS en_erreur,
                   min(c.created_at)                                    AS premiere_entree,
                   max(c.curated_at)                                    AS derniere_analyse
              FROM arac.conversations c
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="digestion_atomization_ratio",
        label="Conversion analysées → atomisées",
        unit="%",
        definition="Part des conversations analysées qui ont réellement produit au moins un atome de savoir.",
        formula="conversations avec atoms_generated > 0 / conversations avec curated_at × 100",
        domain="digestion",
        window="all",
        target={"warn": 40, "critical": 20, "direction": "up"},
        sql="""
            SELECT round(100.0 * count(*) FILTER (WHERE coalesce(atoms_generated, 0) > 0)
                         / nullif(count(*) FILTER (WHERE curated_at IS NOT NULL), 0), 1) AS value
              FROM arac.conversations
        """,
        evidence_label="Les conversations analysées, réparties par rendement en atomes",
        evidence_sql="""
            SELECT CASE
                     WHEN coalesce(atoms_generated, 0) = 0 THEN 'aucun atome'
                     WHEN atoms_generated BETWEEN 1 AND 2  THEN '1 à 2 atomes'
                     WHEN atoms_generated BETWEEN 3 AND 5  THEN '3 à 5 atomes'
                     WHEN atoms_generated BETWEEN 6 AND 10 THEN '6 à 10 atomes'
                     ELSE 'plus de 10 atomes'
                   END                                          AS tranche,
                   count(*)                                     AS conversations,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS part_pct,
                   coalesce(sum(atoms_generated), 0)            AS atomes,
                   min(curated_at)                              AS premiere,
                   max(curated_at)                              AS derniere
              FROM arac.conversations
             WHERE curated_at IS NOT NULL
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),

    # ============================================ 2. COUVERTURE D'UN PASSAGE
    Metric(
        key="digestion_coverage_ratio",
        label="Taux de couverture",
        unit="%",
        definition="Part des passages présentés au curateur dont le contenu a effectivement été couvert par une extraction.",
        formula="Σ coverage_covered / Σ coverage_presented × 100",
        domain="digestion",
        window="all",
        target={"warn": 60, "critical": 40, "direction": "up"},
        sql="""
            SELECT round(100.0 * coalesce(sum(coverage_covered), 0)
                         / nullif(coalesce(sum(coverage_presented), 0), 0), 1) AS value
              FROM arac.run_receipts
        """,
        evidence_label="L'équation de couverture par jour : présenté, couvert, sans savoir nouveau, omis",
        evidence_sql="""
            SELECT utc_day                                      AS jour,
                   count(*)                                     AS cycles,
                   coalesce(sum(coverage_presented), 0)         AS presente,
                   coalesce(sum(coverage_covered), 0)           AS couvert,
                   coalesce(sum(coverage_no_new_knowledge), 0)  AS sans_savoir_nouveau,
                   coalesce(sum(coverage_omitted), 0)           AS omis,
                   round(100.0 * coalesce(sum(coverage_covered), 0)
                         / nullif(coalesce(sum(coverage_presented), 0), 0), 1) AS couverture_pct,
                   coalesce(sum(atoms_created), 0)              AS atomes_produits
              FROM arac.run_receipts
             WHERE coverage_presented > 0
             GROUP BY 1
             ORDER BY 1 DESC
        """,
    ),
    Metric(
        key="digestion_no_new_knowledge_ratio",
        label="Part sans savoir nouveau",
        unit="%",
        definition="Part des passages présentés que le curateur a lus sans y trouver de savoir nouveau, ce qui est une lecture réussie et non une perte.",
        formula="Σ coverage_no_new_knowledge / Σ coverage_presented × 100",
        domain="digestion",
        window="all",
        sql="""
            SELECT round(100.0 * coalesce(sum(coverage_no_new_knowledge), 0)
                         / nullif(coalesce(sum(coverage_presented), 0), 0), 1) AS value
              FROM arac.run_receipts
        """,
        evidence_label="Les trois issues d'un passage présenté, avec leur part — deux sont des succès, une seule est une perte",
        evidence_sql="""
            SELECT 'couvert'                                    AS issue,
                   'le passage a produit du savoir'             AS lecture,
                   'succès'                                     AS nature,
                   coalesce(sum(coverage_covered), 0)           AS passages,
                   round(100.0 * coalesce(sum(coverage_covered), 0)
                         / nullif(coalesce(sum(coverage_presented), 0), 0), 1) AS part_pct
              FROM arac.run_receipts
            UNION ALL
            SELECT 'aucun savoir nouveau',
                   'le passage a été lu, il ne contenait rien de neuf',
                   'succès',
                   coalesce(sum(coverage_no_new_knowledge), 0),
                   round(100.0 * coalesce(sum(coverage_no_new_knowledge), 0)
                         / nullif(coalesce(sum(coverage_presented), 0), 0), 1)
              FROM arac.run_receipts
            UNION ALL
            SELECT 'omis',
                   'le passage n''a pas été traité — seule vraie perte des trois',
                   'perte',
                   coalesce(sum(coverage_omitted), 0),
                   round(100.0 * coalesce(sum(coverage_omitted), 0)
                         / nullif(coalesce(sum(coverage_presented), 0), 0), 1)
              FROM arac.run_receipts
             ORDER BY 4 DESC
             LIMIT 3
        """,
    ),
    Metric(
        key="digestion_omission_ratio",
        label="Taux d'omission",
        unit="%",
        definition="Part des passages présentés au curateur qu'il a laissés de côté sans les traiter.",
        formula="Σ coverage_omitted / Σ coverage_presented × 100",
        domain="digestion",
        window="all",
        target={"warn": 10, "critical": 25, "direction": "down"},
        sql="""
            SELECT round(100.0 * coalesce(sum(coverage_omitted), 0)
                         / nullif(coalesce(sum(coverage_presented), 0), 0), 1) AS value
              FROM arac.run_receipts
        """,
        evidence_label="Les cycles qui ont omis des passages, et les candidats correspondants restés en file de revue",
        evidence_sql="""
            SELECT r.id                                         AS run_id,
                   r.slot_key                                   AS creneau,
                   r.started_at,
                   r.status                                     AS issue,
                   r.coverage_presented                         AS presente,
                   r.coverage_omitted                           AS omis,
                   round(100.0 * r.coverage_omitted
                         / nullif(r.coverage_presented, 0), 1)  AS omission_pct,
                   r.stop_reason                                AS motif_arret,
                   (SELECT count(*) FROM arac.digestion_review_queue q
                     WHERE q.drop_reason = 'coverage_omitted'
                       AND q.run_ref = r.slot_key)              AS lignes_en_file
              FROM arac.run_receipts r
             WHERE coalesce(r.coverage_omitted, 0) > 0
             ORDER BY r.coverage_omitted DESC, r.started_at DESC
             LIMIT 100
        """,
    ),

    # ====================================== 3. ÉQUATIONS DE CONSERVATION
    Metric(
        key="digestion_coverage_conservation_gap",
        label="Écart de conservation d'un cycle",
        unit="passages",
        definition="Passages qui ne sont dans aucune des trois cases d'un cycle, alors que présenté doit toujours égaler couvert plus sans-savoir-nouveau plus omis.",
        formula="Σ |presented − (covered + no_new_knowledge + omitted)|",
        domain="digestion",
        window="all",
        target={"warn": 1, "critical": 10, "direction": "down"},
        sql="""
            SELECT coalesce(sum(abs(
                       coverage_presented
                       - (coalesce(coverage_covered, 0)
                          + coalesce(coverage_no_new_knowledge, 0)
                          + coalesce(coverage_omitted, 0)))), 0) AS value
              FROM arac.run_receipts
             WHERE coverage_presented IS NOT NULL
        """,
        evidence_label="L'équation vérifiée cycle par cycle, les écarts les plus gros d'abord",
        evidence_sql="""
            SELECT id                                           AS run_id,
                   started_at,
                   status                                       AS issue,
                   coverage_presented                           AS presente,
                   coverage_covered                             AS couvert,
                   coverage_no_new_knowledge                    AS sans_savoir_nouveau,
                   coverage_omitted                             AS omis,
                   coverage_presented
                     - (coalesce(coverage_covered, 0)
                        + coalesce(coverage_no_new_knowledge, 0)
                        + coalesce(coverage_omitted, 0))        AS ecart,
                   CASE WHEN coverage_presented
                             = coalesce(coverage_covered, 0)
                               + coalesce(coverage_no_new_knowledge, 0)
                               + coalesce(coverage_omitted, 0)
                        THEN 'équation vérifiée'
                        ELSE 'CONSERVATION ROMPUE' END          AS etat
              FROM arac.run_receipts
             WHERE coverage_presented IS NOT NULL
             ORDER BY abs(coverage_presented
                          - (coalesce(coverage_covered, 0)
                             + coalesce(coverage_no_new_knowledge, 0)
                             + coalesce(coverage_omitted, 0))) DESC,
                      started_at DESC
             LIMIT 200
        """,
    ),
    Metric(
        key="digestion_unledgered_passes",
        label="Passages jamais inscrits au registre",
        unit="passages",
        definition="Passages réellement engagés dans un cycle qui n'apparaissent dans aucune case du registre de couverture, donc dont le sort n'est comptabilisé nulle part.",
        formula="Σ items − Σ coverage_presented, sur tous les cycles",
        domain="digestion",
        window="all",
        target={"warn": 1, "critical": 50, "direction": "down"},
        sql="""
            SELECT coalesce(sum(items), 0) - coalesce(sum(coverage_presented), 0) AS value
              FROM arac.run_receipts
        """,
        evidence_label="Engagé contre inscrit, par issue de cycle : où la comptabilité s'arrête",
        evidence_sql="""
            SELECT status                                       AS issue,
                   count(*)                                     AS cycles,
                   count(*) FILTER (WHERE coalesce(items, 0)
                                          <> coalesce(coverage_presented, 0)) AS cycles_hors_registre,
                   coalesce(sum(items), 0)                      AS passages_engages,
                   coalesce(sum(coverage_presented), 0)         AS passages_inscrits,
                   coalesce(sum(items), 0)
                     - coalesce(sum(coverage_presented), 0)     AS passages_hors_registre,
                   coalesce(sum(atoms_created), 0)              AS atomes_produits,
                   CASE WHEN coalesce(sum(items), 0)
                             = coalesce(sum(coverage_presented), 0)
                        THEN 'comptabilité complète'
                        ELSE 'le registre de couverture ne couvre pas cette issue' END AS lecture
              FROM arac.run_receipts
             GROUP BY 1
             ORDER BY 6 DESC
        """,
    ),
    Metric(
        key="digestion_ledger_divergence",
        label="Postes comptables divergents",
        unit="postes",
        definition="Postes de la digestion dont le compteur agrégé du cycle contredit le nombre de lignes réellement déposées en file de revue.",
        formula="count(postes à double écriture WHERE compteur de cycle ≠ lignes en file)",
        domain="digestion",
        window="all",
        target={"warn": 1, "critical": 3, "direction": "down"},
        sql=_LEDGER_CTE + """
            SELECT count(*) AS value
              FROM cycle c
              LEFT JOIN revue r ON r.poste = c.poste
             WHERE c.compte_dans_ecart
               AND c.compteur <> coalesce(r.lignes, 0)
        """,
        evidence_label="Le registre à double écriture, poste par poste : compteur du cycle contre lignes en file",
        evidence_sql=_LEDGER_CTE + """
            SELECT c.poste,
                   c.source_compteur,
                   c.compteur                                   AS compteur_cycle,
                   coalesce(r.lignes, 0)                        AS lignes_en_file,
                   c.compteur - coalesce(r.lignes, 0)           AS ecart,
                   CASE WHEN NOT c.compte_dans_ecart THEN 'lecture seule — hors écart'
                        WHEN c.compteur = coalesce(r.lignes, 0) THEN 'conservé'
                        ELSE 'DIVERGENT' END                    AS etat,
                   r.premiere                                   AS premiere_ligne,
                   r.derniere                                   AS derniere_ligne
              FROM cycle c
              LEFT JOIN revue r ON r.poste = c.poste
             ORDER BY c.rang
             LIMIT 12
        """,
    ),

    # ======================================== 4. PERTES ATTRIBUABLES
    Metric(
        key="digestion_quarantine_cause_concentration",
        label="Concentration des causes de quarantaine",
        unit="%",
        definition="Part de la cause dominante dans l'ensemble des causes de quarantaine relevées, mesure de la réparabilité du problème.",
        formula="occurrences de la cause la plus fréquente / occurrences totales × 100",
        domain="digestion",
        window="all",
        sql="""
            WITH causes AS (
                SELECT split_part(e.value #>> '{}', ':', 1) AS cause,
                       count(*) AS occurrences
                  FROM arac.run_receipts r
                  CROSS JOIN LATERAL jsonb_array_elements(
                         coalesce(r.quarantine_errors, '[]'::jsonb)) AS e(value)
                 GROUP BY 1
            )
            SELECT round(100.0 * max(occurrences) / nullif(sum(occurrences), 0), 1) AS value,
                   (SELECT cause FROM causes ORDER BY occurrences DESC, cause LIMIT 1) AS detail
              FROM causes
        """,
        evidence_label="Les causes de quarantaine agrégées par préfixe, avec les cycles et les passages qu'elles ont coûté",
        evidence_sql="""
            WITH releves AS (
                SELECT r.id                                      AS run_id,
                       r.items                                   AS passages,
                       r.started_at,
                       split_part(e.value #>> '{}', ':', 1)      AS cause,
                       left(e.value #>> '{}', 120)               AS exemple
                  FROM arac.run_receipts r
                  CROSS JOIN LATERAL jsonb_array_elements(
                         coalesce(r.quarantine_errors, '[]'::jsonb)) AS e(value)
            ), cycles_par_cause AS (
                SELECT cause, run_id, min(passages) AS passages, min(started_at) AS started_at
                  FROM releves
                 GROUP BY 1, 2
            )
            SELECT o.cause,
                   o.occurrences,
                   round(100.0 * o.occurrences / sum(o.occurrences) OVER (), 1) AS part_pct,
                   c.cycles,
                   c.passages_des_cycles,
                   c.premiere,
                   c.derniere,
                   o.exemple
              FROM (
                SELECT cause, count(*) AS occurrences, min(exemple) AS exemple
                  FROM releves GROUP BY 1
              ) o
              JOIN (
                SELECT cause,
                       count(*)                    AS cycles,
                       coalesce(sum(passages), 0)  AS passages_des_cycles,
                       min(started_at)             AS premiere,
                       max(started_at)             AS derniere
                  FROM cycles_par_cause GROUP BY 1
              ) c ON c.cause = o.cause
             ORDER BY o.occurrences DESC, o.cause
             LIMIT 40
        """,
    ),
    Metric(
        key="digestion_quarantine_unattributed_cycles",
        label="Quarantaines sans fautif",
        unit="cycles",
        definition="Cycles mis en quarantaine sans qu'aucune conversation ne soit désignée coupable, dont les passages sont donc détruits sans cause identifiée.",
        formula="count(cycles quarantinés WHERE longueur(quarantine_attributed_uids) = 0)",
        domain="digestion",
        window="all",
        target={"warn": 1, "critical": 5, "direction": "down"},
        sql="""
            SELECT count(*) AS value
              FROM arac.run_receipts
             WHERE status = 'quarantined'
               AND jsonb_array_length(coalesce(quarantine_attributed_uids, '[]'::jsonb)) = 0
        """,
        evidence_label="Les quarantaines aveugles, avec le total des passages qu'elles ont détruits sans motif attribuable",
        evidence_sql="""
            SELECT id                                           AS run_id,
                   slot_key                                     AS creneau,
                   started_at,
                   items                                        AS passages_detruits,
                   sum(items) OVER ()                           AS passages_detruits_total,
                   count(*) OVER ()                             AS cycles_concernes,
                   coalesce(quarantine_errors, '[]'::jsonb)     AS erreurs_relevees,
                   jsonb_array_length(coalesce(quarantine_errors, '[]'::jsonb)) AS nb_erreurs,
                   stop_reason                                  AS motif_arret,
                   model                                        AS modele
              FROM arac.run_receipts
             WHERE status = 'quarantined'
               AND jsonb_array_length(coalesce(quarantine_attributed_uids, '[]'::jsonb)) = 0
             ORDER BY items DESC, started_at DESC
             LIMIT 100
        """,
    ),
    Metric(
        key="digestion_slice_size_ratio_failed",
        label="Surcharge des tranches perdues",
        unit="× la tranche réussie",
        definition="Rapport entre la taille moyenne d'une tranche de digestion qui échoue et celle d'une tranche qui aboutit.",
        formula="(Σ items / cycles) des issues perdues ÷ (Σ items / cycles) de l'issue done",
        domain="digestion",
        window="all",
        target={"warn": 1.5, "critical": 3, "direction": "down"},
        sql="""
            SELECT round(
                     (coalesce(sum(items) FILTER (
                          WHERE status IN ('quarantined', 'spawn_failed')), 0)::numeric
                      / nullif(count(*) FILTER (
                          WHERE status IN ('quarantined', 'spawn_failed')), 0))
                     / nullif(
                       coalesce(sum(items) FILTER (WHERE status = 'done'), 0)::numeric
                       / nullif(count(*) FILTER (WHERE status = 'done'), 0), 0), 2) AS value
              FROM arac.run_receipts
        """,
        evidence_label="La taille moyenne d'une tranche selon l'issue du cycle, et ce que cette tranche a produit",
        evidence_sql="""
            SELECT status                                       AS issue,
                   count(*)                                     AS cycles,
                   coalesce(sum(items), 0)                      AS passages,
                   round(avg(items), 2)                         AS tranche_moyenne,
                   round(percentile_cont(0.5) WITHIN GROUP (ORDER BY items)::numeric, 2) AS tranche_mediane,
                   max(items)                                   AS tranche_max,
                   coalesce(sum(atoms_created), 0)              AS atomes_produits,
                   round(coalesce(sum(atoms_created), 0)::numeric
                         / nullif(coalesce(sum(items), 0), 0), 2) AS atomes_par_passage
              FROM arac.run_receipts
             GROUP BY 1
             ORDER BY 4 DESC NULLS LAST
        """,
    ),

    # ========================================== 5. LA FILE ET SON ANCIENNETÉ
    Metric(
        key="digestion_queue_head_age_days",
        label="Ancienneté de la tête de file",
        unit="jours",
        definition="Âge du contenu le plus ancien qui attend encore d'être digéré, mesuré sur la date du message et non sur celle de son import.",
        formula="now() − min(date du premier message des conversations non entièrement curées)",
        domain="digestion",
        window="instant",
        target={"warn": 30, "critical": 90, "direction": "down"},
        sql="""
            SELECT round(extract(epoch FROM (now() - min(t.date_contenu))) / 86400, 1) AS value
              FROM (
                SELECT (SELECT min(rm.msg_created_at) FROM arac.raw_messages rm
                         WHERE rm.conversation_id = c.id) AS date_contenu
                  FROM arac.conversations c
                 WHERE c.curated_through_message_id IS NULL
                    OR c.curated_through_message_id < (
                           SELECT max(rm.id) FROM arac.raw_messages rm
                            WHERE rm.conversation_id = c.id)
              ) t
        """,
        evidence_label="La tête de file : le contenu le plus vieux qui attend, du plus ancien au plus récent",
        evidence_sql="""
            SELECT c.conversation_uid,
                   c.source_type,
                   left(coalesce(c.title, ''), 70)              AS titre,
                   (SELECT min(rm.msg_created_at) FROM arac.raw_messages rm
                     WHERE rm.conversation_id = c.id)           AS date_contenu,
                   round(extract(epoch FROM (now() - (
                       SELECT min(rm.msg_created_at) FROM arac.raw_messages rm
                        WHERE rm.conversation_id = c.id))) / 86400, 1) AS age_jours,
                   c.created_at                                 AS date_import,
                   (SELECT count(*) FROM arac.raw_messages rm
                     WHERE rm.conversation_id = c.id)           AS messages,
                   coalesce(c.curated_through_message_id, 0)    AS curseur,
                   c.retry_count                                AS tentatives
              FROM arac.conversations c
             WHERE c.curated_through_message_id IS NULL
                OR c.curated_through_message_id < (
                       SELECT max(rm.id) FROM arac.raw_messages rm
                        WHERE rm.conversation_id = c.id)
             ORDER BY date_contenu ASC NULLS LAST
             LIMIT 100
        """,
    ),
    Metric(
        key="digestion_residence_p95_days",
        label="Temps de séjour en file au p95",
        unit="jours",
        definition="Délai sous lequel 95 % des conversations sortent de la file de digestion, compté entre leur import et leur curation.",
        formula="percentile_cont(0,95) sur (curated_at − created_at), en jours",
        domain="digestion",
        window="all",
        target={"warn": 14, "critical": 30, "direction": "down"},
        sql="""
            SELECT round(percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY extract(epoch FROM (curated_at - created_at)) / 86400)::numeric, 2)
                   AS value
              FROM arac.conversations
             WHERE curated_at IS NOT NULL
               AND curated_at >= created_at
        """,
        evidence_label="La distribution du temps de séjour, p50 et p95, source par source",
        evidence_sql="""
            SELECT source_type,
                   count(*)                                     AS conversations_sorties,
                   round(percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY extract(epoch FROM (curated_at - created_at)) / 86400)::numeric, 2)
                                                                AS p50_jours,
                   round(percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY extract(epoch FROM (curated_at - created_at)) / 86400)::numeric, 2)
                                                                AS p95_jours,
                   round(min(extract(epoch FROM (curated_at - created_at)) / 86400)::numeric, 2)
                                                                AS min_jours,
                   round(max(extract(epoch FROM (curated_at - created_at)) / 86400)::numeric, 2)
                                                                AS max_jours,
                   coalesce(sum(atoms_generated), 0)            AS atomes_produits
              FROM arac.conversations
             WHERE curated_at IS NOT NULL
               AND curated_at >= created_at
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),
)
