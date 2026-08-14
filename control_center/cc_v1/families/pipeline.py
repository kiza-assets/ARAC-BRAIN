"""Famille « pipeline » — les huit étages, de la capture au rappel.

Le pipeline d'ARAC est une chaîne : capture → import → analyse → atomes →
graphes → index → benchmark → rappel. Une chaîne se juge à son maillon le plus
faible, jamais à son total : ces métriques mesurent donc des **passages** et des
**pertes** étage par étage, pas un volume global rassurant.

Trois principes appliqués ici, hérités du registre (cf ``registry`` §invariants) :

1. Toute l'arithmétique est en SQL. Les divisions, pourcentages et percentiles
   sont calculés par PostgreSQL, là où sont les données — donc rejouables depuis
   un terminal, donc opposables.
2. Toute métrique porte ses lignes sources. Aucune n'est décorative.
3. Une dépendance absente n'est pas une erreur à masquer : l'étage « graphes »
   n'est pas installé quand ``arac.atom_links`` est absente du schéma. La
   métrique correspondante le DIT — après l'avoir constaté — avec la preuve,
   au lieu de tomber en panne ou d'inventer un zéro trompeur.

LECTURE SEULE : aucune instruction mutante, invariant vérifié à l'instanciation
par ``Metric.__post_init__`` et par ``tests/test_cc_v1_registry.py``.
"""

from __future__ import annotations

from control_center.cc_v1.metric import Metric

__all__ = ["METRICS"]


METRICS: tuple[Metric, ...] = (

    # ======================================================== étage 1 : capture
    Metric(
        key="capture_throughput_7d",
        label="Débit de capture",
        unit="passages / jour",
        definition="Passages du capteur enregistrés par jour, moyenne sur les 7 derniers jours.",
        formula="count(capture_manifests sur 7 j) / 7",
        domain="pipeline",
        window="7d",
        sql="""
            SELECT round(count(*)::numeric / 7, 1) AS value
              FROM arac.capture_manifests
             WHERE created_at > now() - interval '7 days'
        """,
        evidence_label="Les passages de capture jour par jour, avec ce qu'ils ont lu et émis",
        evidence_sql="""
            SELECT created_at::date               AS jour,
                   count(*)                       AS passages,
                   sum(files_scanned)             AS fichiers_scannes,
                   sum(sessions)                  AS sessions,
                   sum(messages_read)             AS messages_lus,
                   sum(messages_emitted)          AS messages_emis,
                   sum(batches_ok)                AS lots_ok,
                   sum(batches_failed)            AS lots_echoues,
                   sum(ack_mismatches)            AS acquittements_manquants
              FROM arac.capture_manifests
             GROUP BY 1
             ORDER BY 1 DESC
             LIMIT 21
        """,
    ),
    Metric(
        key="capture_emission_ratio",
        label="Rendement de capture",
        unit="%",
        definition="Part des messages lus par le capteur qui sont réellement émis vers le cerveau.",
        formula="Σ messages_emitted / Σ messages_read × 100",
        domain="pipeline",
        window="all",
        sql="""
            SELECT round(100.0 * sum(messages_emitted)
                         / nullif(sum(messages_read), 0), 2) AS value
              FROM arac.capture_manifests
        """,
        evidence_label="Lu contre émis, par source et par nœud captureur",
        evidence_sql="""
            SELECT source_type,
                   node_id,
                   count(*)              AS passages,
                   sum(messages_read)    AS messages_lus,
                   sum(messages_emitted) AS messages_emis,
                   round(100.0 * sum(messages_emitted)
                         / nullif(sum(messages_read), 0), 2) AS rendement_pct,
                   sum(batches_ok)       AS lots_ok,
                   sum(batches_failed)   AS lots_echoues,
                   min(run_started_at)   AS premier_passage,
                   max(run_started_at)   AS dernier_passage
              FROM arac.capture_manifests
             GROUP BY 1, 2
             ORDER BY 4 DESC
        """,
    ),

    # ========================================================= étage 2 : import
    Metric(
        key="ingest_refusal_ratio",
        label="Refus à l'ingestion",
        unit="%",
        definition="Part des tentatives d'ingestion que le cerveau a refusées au lieu de les accepter.",
        formula="reçus dont outcome ∉ {accepted, duplicate_noop} / total × 100",
        domain="pipeline",
        window="all",
        sql="""
            SELECT round(100.0 * count(*) FILTER (
                             WHERE outcome NOT IN ('accepted', 'duplicate_noop'))
                         / nullif(count(*), 0), 2) AS value
              FROM arac.ingest_receipts
        """,
        evidence_label="Les issues d'ingestion, avec le détail de ce qui est entré et de ce qui a été rejeté",
        evidence_sql="""
            SELECT outcome                       AS issue,
                   count(*)                      AS recus,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS part_pct,
                   sum(received)                 AS messages_presentes,
                   sum(inserted)                 AS messages_retenus,
                   sum(duplicates)               AS doublons,
                   sum(hash_divergences)         AS divergences_de_hash,
                   sum(empty_messages)           AS messages_vides,
                   min(created_at)               AS premier,
                   max(created_at)               AS dernier
              FROM arac.ingest_receipts
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="ingest_hash_divergences",
        label="Divergences de hash",
        unit="révisions",
        definition="Messages déjà stockés dont une réémission portait un contenu différent : le passé a bougé.",
        formula="count(raw_message_revisions WHERE reason='hash_divergence')",
        domain="pipeline",
        window="all",
        sql="""
            SELECT count(*) AS value
              FROM arac.raw_message_revisions
             WHERE reason = 'hash_divergence'
        """,
        evidence_label="Les révisions de contenu, par motif et par auteur de la révision",
        evidence_sql="""
            SELECT reason                        AS motif,
                   actor                         AS auteur,
                   count(*)                      AS revisions,
                   count(DISTINCT raw_message_id) AS messages_touches,
                   count(DISTINCT conversation_id) AS conversations_touchees,
                   min(created_at)               AS premiere,
                   max(created_at)               AS derniere
              FROM arac.raw_message_revisions
             GROUP BY 1, 2
             ORDER BY 3 DESC
        """,
    ),
    Metric(
        key="pipeline_messages_absorbed_24h",
        label="Messages absorbés (24 h)",
        unit="messages",
        definition="Messages bruts réellement entrés en base au cours des dernières 24 heures.",
        formula="count(raw_messages WHERE received_at > now() - 24 h)",
        domain="pipeline",
        window="24h",
        sql="""
            SELECT count(*) AS value
              FROM arac.raw_messages
             WHERE received_at > now() - interval '24 hours'
        """,
        evidence_label="Les dernières heures d'absorption, heure par heure",
        evidence_sql="""
            SELECT date_trunc('hour', received_at) AS heure,
                   count(*)                        AS messages,
                   count(DISTINCT conversation_id) AS conversations,
                   count(*) FILTER (WHERE role = 'user')      AS messages_utilisateur,
                   count(*) FILTER (WHERE role = 'assistant') AS messages_assistant,
                   count(*) FILTER (WHERE was_masked)         AS messages_masques
              FROM arac.raw_messages
             GROUP BY 1
             ORDER BY 1 DESC
             LIMIT 48
        """,
    ),
    Metric(
        key="pipeline_absorption_rate_7d",
        label="Débit d'absorption",
        unit="messages / jour",
        definition="Messages bruts entrés en base par jour, moyenne sur les 7 derniers jours.",
        formula="count(raw_messages sur 7 j) / 7",
        domain="pipeline",
        window="7d",
        sql="""
            SELECT round(count(*)::numeric / 7, 1) AS value
              FROM arac.raw_messages
             WHERE received_at > now() - interval '7 days'
        """,
        evidence_label="L'absorption jour par jour, avec les conversations concernées",
        evidence_sql="""
            SELECT received_at::date              AS jour,
                   count(*)                       AS messages,
                   count(DISTINCT conversation_id) AS conversations,
                   min(received_at)               AS premier_message,
                   max(received_at)               AS dernier_message
              FROM arac.raw_messages
             GROUP BY 1
             ORDER BY 1 DESC
             LIMIT 30
        """,
    ),

    # ======================================================== étage 3 : analyse
    Metric(
        key="pipeline_conversations_excluded",
        label="Conversations exclues",
        unit="conversations",
        definition="Conversations écartées de la digestion et qui n'entreront jamais dans le savoir.",
        formula="count(conversations WHERE exclusion_reason IS NOT NULL)",
        domain="pipeline",
        window="all",
        sql="""
            SELECT count(*) AS value
              FROM arac.conversations
             WHERE exclusion_reason IS NOT NULL
        """,
        evidence_label="Les motifs d'exclusion, comparés au reste du corpus",
        evidence_sql="""
            SELECT coalesce(exclusion_category, 'aucune exclusion') AS categorie,
                   count(*)                                        AS conversations,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS part_pct,
                   min(excluded_at)                                AS premiere_exclusion,
                   max(excluded_at)                                AS derniere_exclusion,
                   min(left(exclusion_reason, 140))                AS motif_exemple
              FROM arac.conversations
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="pipeline_retries_pending",
        label="Reprises de curation programmées",
        unit="conversations",
        definition="Conversations dont une nouvelle tentative de curation est planifiée dans le futur.",
        formula="count(conversations WHERE next_retry_at > now())",
        domain="pipeline",
        window="instant",
        sql="""
            SELECT count(*) AS value
              FROM arac.conversations
             WHERE next_retry_at > now()
        """,
        evidence_label="Toutes les reprises inscrites : celles à venir et celles dont l'échéance est passée",
        evidence_sql="""
            SELECT conversation_uid,
                   source_type,
                   retry_count                                   AS tentatives,
                   next_retry_at                                 AS echeance,
                   CASE WHEN next_retry_at > now() THEN 'programmée'
                        ELSE 'échéance dépassée' END              AS etat,
                   round(extract(epoch FROM (now() - next_retry_at)) / 3600, 1)
                                                                 AS heures_de_retard,
                   left(coalesce(last_curation_error, ''), 90)   AS derniere_erreur
              FROM arac.conversations
             WHERE next_retry_at IS NOT NULL
             ORDER BY next_retry_at DESC
             LIMIT 100
        """,
    ),
    Metric(
        key="pipeline_curation_errors",
        label="Conversations en erreur de curation",
        unit="conversations",
        definition="Conversations portant une erreur de curation non résolue à ce jour.",
        formula="count(conversations WHERE last_curation_error IS NOT NULL)",
        domain="pipeline",
        window="instant",
        sql="""
            SELECT count(*) AS value
              FROM arac.conversations
             WHERE last_curation_error IS NOT NULL
        """,
        evidence_label="Les familles d'erreur de curation, et le nombre de tentatives qu'elles ont coûté",
        evidence_sql="""
            SELECT CASE WHEN last_curation_error IS NULL THEN 'aucune erreur'
                        ELSE split_part(last_curation_error, ':', 1) END AS famille_erreur,
                   count(*)                     AS conversations,
                   sum(retry_count)             AS tentatives_cumulees,
                   count(*) FILTER (WHERE next_retry_at IS NOT NULL) AS reprises_inscrites,
                   max(updated_at)              AS dernier_signal
              FROM arac.conversations
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),

    # ================================================ étage 4 : atomes — le coût
    Metric(
        key="pipeline_tokens_per_cycle",
        label="Tokens par cycle",
        unit="tokens / cycle",
        definition="Tokens d'entrée estimés que consomme en moyenne un cycle de digestion, quelle qu'en soit l'issue.",
        formula="Σ est_input_tokens / count(cycles)",
        domain="pipeline",
        window="all",
        sql="""
            SELECT round(sum(est_input_tokens)::numeric / nullif(count(*), 0), 0) AS value
              FROM arac.run_receipts
        """,
        evidence_label="La consommation jour par jour, et ce qu'elle a produit",
        evidence_sql="""
            SELECT utc_day                        AS jour,
                   count(*)                       AS cycles,
                   sum(est_input_tokens)          AS tokens,
                   round(sum(est_input_tokens)::numeric / nullif(count(*), 0), 0)
                                                  AS tokens_par_cycle,
                   sum(items)                     AS passages,
                   sum(atoms_created)             AS atomes_produits
              FROM arac.run_receipts
             GROUP BY 1
             ORDER BY 1 DESC
             LIMIT 40
        """,
    ),
    Metric(
        key="pipeline_tokens_per_atom",
        label="Coût par atome produit",
        unit="tokens / atome",
        definition="Tokens d'entrée estimés dépensés pour produire un atome de savoir, toutes issues de cycle confondues.",
        formula="Σ est_input_tokens / Σ atoms_created",
        domain="pipeline",
        window="all",
        sql="""
            SELECT round(sum(est_input_tokens)::numeric
                         / nullif(sum(atoms_created), 0), 1) AS value
              FROM arac.run_receipts
        """,
        evidence_label="Où part la dépense : tokens et atomes produits, par issue de cycle",
        evidence_sql="""
            SELECT status                         AS issue,
                   count(*)                       AS cycles,
                   sum(est_input_tokens)          AS tokens,
                   round(100.0 * sum(est_input_tokens)
                         / nullif(sum(sum(est_input_tokens)) OVER (), 0), 1) AS part_tokens_pct,
                   sum(atoms_created)             AS atomes_produits,
                   round(sum(est_input_tokens)::numeric
                         / nullif(sum(atoms_created), 0), 1) AS tokens_par_atome
              FROM arac.run_receipts
             GROUP BY 1
             ORDER BY 3 DESC
        """,
    ),

    # ============================================ étage 4 : atomes — la latence
    Metric(
        key="pipeline_cycle_duration_p50",
        label="Durée médiane d'un cycle",
        unit="secondes",
        definition="Durée médiane d'un cycle de digestion mené jusqu'à sa fin, quelle qu'en soit l'issue.",
        formula="percentile_cont(0,5) sur (ended_at − started_at)",
        domain="pipeline",
        window="all",
        sql="""
            SELECT round(percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY extract(epoch FROM (ended_at - started_at)))::numeric, 1) AS value
              FROM arac.run_receipts
             WHERE started_at IS NOT NULL AND ended_at IS NOT NULL
        """,
        evidence_label="La distribution des durées par issue de cycle",
        evidence_sql="""
            SELECT status                         AS issue,
                   count(*)                       AS cycles,
                   round(percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY extract(epoch FROM (ended_at - started_at)))::numeric, 1) AS p50_s,
                   round(percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY extract(epoch FROM (ended_at - started_at)))::numeric, 1) AS p95_s,
                   round(min(extract(epoch FROM (ended_at - started_at)))::numeric, 1) AS min_s,
                   round(max(extract(epoch FROM (ended_at - started_at)))::numeric, 1) AS max_s
              FROM arac.run_receipts
             WHERE started_at IS NOT NULL AND ended_at IS NOT NULL
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="pipeline_cycle_duration_p95",
        label="Durée d'un cycle au p95",
        unit="secondes",
        definition="Durée sous laquelle se terminent 95 % des cycles de digestion : la queue de distribution, pas la moyenne.",
        formula="percentile_cont(0,95) sur (ended_at − started_at)",
        domain="pipeline",
        window="all",
        sql="""
            SELECT round(percentile_cont(0.95) WITHIN GROUP (
                       ORDER BY extract(epoch FROM (ended_at - started_at)))::numeric, 1) AS value
              FROM arac.run_receipts
             WHERE started_at IS NOT NULL AND ended_at IS NOT NULL
        """,
        evidence_label="Les cycles les plus longs, avec leur issue et leur production",
        evidence_sql="""
            SELECT started_at,
                   slot_key                       AS creneau,
                   status                         AS issue,
                   round(extract(epoch FROM (ended_at - started_at))::numeric, 1) AS duree_s,
                   items                          AS passages,
                   atoms_created                  AS atomes_produits,
                   est_input_tokens               AS tokens,
                   stop_reason                    AS motif_arret
              FROM arac.run_receipts
             WHERE started_at IS NOT NULL AND ended_at IS NOT NULL
             ORDER BY (ended_at - started_at) DESC
             LIMIT 100
        """,
    ),

    # ======================================================== étage 5 : graphes
    Metric(
        key="pipeline_graph_stage_installed",
        # 0 en vert disait « aucun lien n'existe » comme si c'était une mesure
        # satisfaisante, pendant que /cc/v1/status déclarait la MÊME dépendance
        # indisponible. Deux organes du cockpit disaient le contraire.
        # La VALEUR de cette métrique constate déjà (to_regclass ci-dessous) :
        # elle ne rend NULL que si la table est absente. Sa raison ne peut donc
        # être servie que dans ce cas-là — mais elle nommait un numéro de
        # migration, ce qui suppose une histoire de migrations particulière.
        # « Les migrations en attente » se vérifie partout.
        unavailable_reason="l'étage graphes n'est pas branché : la table arac.atom_links est absente du schéma",
        unavailable_gesture="appliquez les migrations en attente : alembic upgrade head",
        substitute="le voisinage sémantique (embedding) et la vue « jamais rappelés »",
        label="Étage graphes installé",
        unit="tables",
        definition="Présence effective de la table de liens que l'étage graphes alimente : à zéro, aucun lien entre atomes n'existe.",
        formula="count(pg_class WHERE schéma='arac' ET relation='atom_links')",
        domain="pipeline",
        window="instant",
        sql="""
            SELECT CASE WHEN to_regclass('arac.atom_links') IS NULL
                        THEN NULL::bigint ELSE 1::bigint END AS value
        """,
        evidence_label="L'état de la dépendance, et les arêtes qui attendent d'être matérialisées",
        evidence_sql="""
            SELECT 'arac.atom_links — cible de l''étage graphes' AS objet,
                   CASE WHEN to_regclass('arac.atom_links') IS NULL
                        THEN 'absente' ELSE 'présente' END       AS etat,
                   /* La lecture DÉCOULE de l'état constaté sur la ligne d'à côté.
                      Elle affirmait « migration non appliquée » quel que soit cet
                      état : la preuve se contredisait elle-même dès que la table
                      était là.
                      COMMENTAIRE DE BLOC ET JAMAIS « -- » : cette requête est
                      PUBLIÉE aplatie sur une ligne par /cc/v1/evidence. Les six
                      commentaires de ligne qui étaient ici la tronquaient à 156
                      caractères sur 1332 — le lecteur recopiait un SELECT qui
                      s'arrêtait sur une virgule. Une preuve qu'on ne peut pas
                      rejouer n'est pas une preuve. */
                   CASE WHEN to_regclass('arac.atom_links') IS NULL
                        THEN 'table absente : aucun lien entre atomes n''est matérialisé'
                        ELSE 'table présente : les liens matérialisés y sont lisibles'
                        END                                       AS lecture
            UNION ALL
            /* « mesurables mais NON STOCKÉES » : c'était faux. Le producteur
               existe et il stocke — app/services/atom_links.py dérive ces
               arêtes de superseded_by et les écrit dans arac.atom_links à
               chaque tour du cortex. Cette ligne ne dit plus ce qu'elle n'a
               pas regardé : elle compte les atomes d'où l'arête se dérive, et
               laisse la ligne du dessus dire l'état constaté de la table. */
            SELECT 'arêtes « supersedes » dérivables',
                   count(*)::text,
                   'atomes portant superseded_by : autant d''arêtes certaines que l''étage graphes dérive'
              FROM arac.memory_atoms
             WHERE superseded_by IS NOT NULL
            UNION ALL
            SELECT 'arac.audit_links — file d''audit, usage distinct',
                   count(*)::text,
                   'table de liens présente, mais destinée à l''acquittement humain'
              FROM arac.audit_links
            LIMIT 3
        """,
    ),
)
