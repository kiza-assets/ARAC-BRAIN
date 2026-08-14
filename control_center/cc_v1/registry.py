"""Control Center v1 — registre des métriques (READ-ONLY strict).

PRINCIPE CARDINAL DU COCKPIT :

    « Le Control Center n'affiche jamais de données calculées par le frontend.
      Le cerveau produit les métriques. Chaque chiffre affiché doit provenir
      directement du moteur, et pouvoir être tracé jusqu'à sa source. »

Ce module transforme ce principe en **contrainte de type** plutôt qu'en consigne :

    Une métrique qui ne déclare pas sa preuve NE PEUT PAS être instanciée.

``Metric.__post_init__`` refuse toute métrique dont ``evidence_sql`` est vide. Il
n'existe donc aucun chemin par lequel un chiffre décoratif — un chiffre sans
lignes sources — puisse atteindre l'interface. L'invariant est vérifié
statiquement par ``tests/test_cc_v1_registry.py``.

DEUXIÈME INVARIANT — l'arithmétique appartient au moteur :

    Le BFF ne calcule pas. Il transporte.

Chaque métrique porte UNE requête SQL qui produit sa valeur finale, division et
pourcentage compris. Ni ce module ni le navigateur ne font d'arithmétique sur les
données du cerveau. C'est PostgreSQL qui calcule, parce que c'est là que sont les
données — et parce qu'un calcul fait en SQL est un calcul qu'on peut rejouer à
l'identique depuis un terminal, donc prouver.

SÛRETÉ SQL : tout le SQL de ce module est **statique et littéral**. Aucune
interpolation, aucun paramètre utilisateur n'entre dans une requête. La seule
entrée externe est une clé de métrique, qui sert de clé de dictionnaire dans le
registre — une clé inconnue lève un ``KeyError``, elle ne construit jamais de SQL.
La surface d'injection est nulle par construction.

LECTURE SEULE : aucune instruction autre que ``SELECT``/``WITH`` n'apparaît ici,
invariant lui aussi vérifié par test (``inspect.getsource``), en cohérence avec
``control_center/collectors/db_metrics.py``.
"""

from __future__ import annotations

# Ni `re`, ni `dataclass`, ni `Any` ici : ils appartenaient au type `Metric`,
# qui vit maintenant dans `metric.py`. Ce module ne fait plus que déclarer des
# métriques et les servir.

__all__ = [
    "Metric",
    "REGISTRY",
    "by_key",
    "by_domain",
    "keys",
    "FORBIDDEN_SQL",
]


# ============================================================================
# Le type Metric — la contrainte structurelle
# ============================================================================
#
# Il vit dans `metric.py`, et pas ici : ce module importe les familles, les
# familles ont besoin du type. Le garder ici faisait un cycle qui, selon l'ordre
# d'import, escamotait dix-huit métriques en silence (cf. l'entête de
# `metric.py`). Réexporté pour que rien de ce qui l'importait d'ici ne change.
from control_center.cc_v1.metric import FORBIDDEN_SQL, Metric, _assert_read_only  # noqa: E402,F401


# ============================================================================
# LE REGISTRE
# ============================================================================
#
# Chaque entrée est un contrat : une valeur, sa formule, et les lignes qui la
# produisent. Ajouter une métrique sans preuve est impossible ; c'est le point.
#
# Convention des requêtes de valeur : UNE ligne, colonne ``value`` (numérique ou
# texte). Une colonne ``detail`` facultative fournit un complément affichable.
# Deux colonnes facultatives de plus, ``reason`` et ``gesture``, ne servent que
# lorsque ``value`` est NULL : elles laissent la REQUÊTE dire pourquoi la mesure
# n'a pas pu être faite, au lieu du code. Une métrique dont l'indisponibilité
# dépend de l'état réel de la base (une table pas encore migrée, une colonne
# jamais alimentée) doit s'en servir — un texte gravé dans ce fichier affirme
# l'état d'une base qu'il n'a pas regardée, et continue de l'affirmer après
# qu'elle a changé. Elles priment sur ``unavailable_reason`` / ``gesture``, qui
# restent le repli.
# Convention des requêtes de preuve : N lignes bornées par un LIMIT explicite.

CORE: tuple[Metric, ...] = (

    # ---------------------------------------------------------------- mémoire
    Metric(
        key="atoms_active",
        label="Souvenirs vivants",
        unit="atomes",
        definition="Atomes rappelables : seuls les atomes actifs remontent dans un contexte servi.",
        formula="count(memory_atoms WHERE status='active')",
        domain="memoire",
        sql="SELECT count(*) AS value FROM arac.memory_atoms WHERE status = 'active'",
        evidence_label="Les atomes actifs les plus récents",
        evidence_sql="""
            SELECT id, kind, scope, key, confidence_score, created_at
              FROM arac.memory_atoms
             WHERE status = 'active'
             ORDER BY created_at DESC
             LIMIT 200
        """,
    ),
    Metric(
        key="atoms_by_status",
        label="Atomes par statut",
        unit="atomes",
        definition="Répartition de tous les atomes par statut : un seul statut est rappelable.",
        formula="count(*) GROUP BY status",
        domain="memoire",
        sql="SELECT count(*) AS value FROM arac.memory_atoms",
        evidence_label="Le compte par statut, et sa rappelabilité",
        evidence_sql="""
            SELECT status,
                   count(*) AS atomes,
                   (status = 'active') AS rappelable
              FROM arac.memory_atoms
             GROUP BY status
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="root_level_debt",
        label="Dette root-level",
        unit="atomes",
        definition="Atomes posés sur un scope racine : ils sont invisibles au rappel.",
        formula="count(actifs WHERE scope ne contient pas '/')",
        domain="memoire",
        window="instant",
        target={"warn": 118, "critical": 140, "direction": "down"},
        sql="""
            SELECT count(*) AS value
              FROM arac.memory_atoms
             WHERE status = 'active' AND scope NOT LIKE '%/%'
        """,
        evidence_label="La dette par racine, et les atomes concernés",
        evidence_sql="""
            SELECT scope,
                   count(*) AS atomes,
                   min(created_at) AS plus_ancien,
                   max(created_at) AS plus_recent
              FROM arac.memory_atoms
             WHERE status = 'active' AND scope NOT LIKE '%/%'
             GROUP BY scope
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="dormant_knowledge",
        label="Savoir jamais rappelé",
        unit="atomes",
        definition="Atomes actifs qui ne sont jamais remontés dans un contexte servi.",
        formula="actifs absents de tous les context_receipts.served_ids",
        domain="memoire",
        window="all",
        sql="""
            WITH servis AS (
                SELECT DISTINCT unnest(served_ids)::uuid AS id FROM arac.context_receipts
            )
            SELECT count(*) AS value
              FROM arac.memory_atoms a
             WHERE a.status = 'active'
               AND NOT EXISTS (SELECT 1 FROM servis s WHERE s.id = a.id)
        """,
        evidence_label="Les atomes dormants, par scope puis par ancienneté",
        evidence_sql="""
            WITH servis AS (
                SELECT DISTINCT unnest(served_ids)::uuid AS id FROM arac.context_receipts
            )
            SELECT a.scope, a.kind, a.key, a.confidence_score, a.created_at
              FROM arac.memory_atoms a
             WHERE a.status = 'active'
               AND NOT EXISTS (SELECT 1 FROM servis s WHERE s.id = a.id)
             ORDER BY a.scope, a.created_at DESC
             LIMIT 200
        """,
    ),

    # --------------------------------------------------------- conversations
    Metric(
        key="conversations_total",
        label="Conversations canoniques",
        unit="conversations",
        definition="Conversations connues du cerveau, toutes sources confondues.",
        formula="count(conversations)",
        domain="conversations",
        sql="SELECT count(*) AS value FROM arac.conversations",
        evidence_label="La répartition par source",
        evidence_sql="""
            SELECT source_type,
                   count(*) AS conversations,
                   count(*) FILTER (WHERE curated_at IS NOT NULL) AS curees
              FROM arac.conversations
             GROUP BY source_type
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="raw_messages_total",
        label="Messages absorbés",
        unit="messages",
        definition="Messages bruts en base, idempotents par dedup_key.",
        formula="count(raw_messages)",
        domain="conversations",
        sql="SELECT count(*) AS value FROM arac.raw_messages",
        evidence_label="Le volume par source et par nœud",
        evidence_sql="""
            SELECT node_id,
                   count(*) AS messages,
                   count(*) FILTER (WHERE was_masked) AS masques,
                   min(received_at) AS premier,
                   max(received_at) AS dernier
              FROM arac.raw_messages
             GROUP BY node_id
             ORDER BY 2 DESC
             LIMIT 50
        """,
    ),
    Metric(
        key="curation_backlog",
        label="File de curation",
        unit="conversations",
        definition="Conversations reçues dont le curateur n'a pas encore lu tous les messages.",
        formula="count(conversations WHERE curseur < dernier message)",
        domain="digestion",
        target={"warn": 20, "critical": 50, "direction": "down"},
        sql="""
            SELECT count(*) AS value
              FROM arac.conversations c
             WHERE c.curated_through_message_id IS NULL
                OR c.curated_through_message_id < (
                       SELECT max(rm.id) FROM arac.raw_messages rm
                        WHERE rm.conversation_id = c.id)
        """,
        evidence_label="La file, dans l'ordre réel de traitement (contenu le plus ancien d'abord)",
        evidence_sql="""
            SELECT c.conversation_uid,
                   c.source_type,
                   c.title,
                   coalesce(c.curated_through_message_id, 0) AS curseur,
                   (SELECT count(*) FROM arac.raw_messages rm
                     WHERE rm.conversation_id = c.id) AS messages,
                   (SELECT min(rm.msg_created_at) FROM arac.raw_messages rm
                     WHERE rm.conversation_id = c.id) AS date_contenu,
                   c.last_curation_error,
                   c.retry_count
              FROM arac.conversations c
             WHERE c.curated_through_message_id IS NULL
                OR c.curated_through_message_id < (
                       SELECT max(rm.id) FROM arac.raw_messages rm
                        WHERE rm.conversation_id = c.id)
             ORDER BY date_contenu ASC NULLS LAST
             LIMIT 200
        """,
    ),

    # -------------------------------------------------------------- digestion
    Metric(
        key="cycles_total",
        label="Cycles de digestion",
        unit="cycles",
        definition="Cycles de curation enregistrés depuis l'origine.",
        formula="count(run_receipts)",
        domain="digestion",
        window="all",
        sql="SELECT count(*) AS value FROM arac.run_receipts",
        evidence_label="Les cycles par issue, avec leur charge et leur production",
        evidence_sql="""
            SELECT status,
                   count(*)                          AS cycles,
                   coalesce(sum(items), 0)           AS passages,
                   round(avg(items), 2)              AS passages_moyens,
                   coalesce(sum(atoms_created), 0)   AS atomes_produits
              FROM arac.run_receipts
             GROUP BY status
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="cycle_quarantine_rate",
        label="Cycles en quarantaine",
        unit="%",
        definition="Part des cycles de digestion qui finissent en quarantaine.",
        formula="cycles quarantinés / cycles totaux × 100",
        domain="digestion",
        window="all",
        target={"warn": 10, "critical": 25, "direction": "down"},
        sql="""
            SELECT round(
                     100.0 * count(*) FILTER (WHERE status = 'quarantined')
                     / nullif(count(*), 0), 1) AS value
              FROM arac.run_receipts
        """,
        evidence_label="Les cycles mis en quarantaine, du plus récent au plus ancien",
        evidence_sql="""
            SELECT id, slot_key, trigger, model, started_at, ended_at,
                   items                                              AS passages,
                   jsonb_array_length(coalesce(quarantine_attributed_uids, '[]'::jsonb))
                                                                      AS conversations_fautives,
                   atoms_created                                      AS atomes_produits,
                   stop_reason, quarantine_sha256
              FROM arac.run_receipts
             WHERE status = 'quarantined'
             ORDER BY started_at DESC
             LIMIT 200
        """,
    ),
    Metric(
        key="quarantine_passes",
        label="Passages emportés par une quarantaine",
        unit="passages",
        definition="Passages de conversation traités dans un cycle qui a fini en quarantaine.",
        formula="Σ items sur les cycles quarantinés",
        domain="digestion",
        window="all",
        sql="""
            SELECT coalesce(sum(items), 0) AS value
              FROM arac.run_receipts WHERE status = 'quarantined'
        """,
        evidence_label="Cycle par cycle : ce qui a été traité puis jeté",
        evidence_sql="""
            SELECT id, slot_key, started_at,
                   items AS passages_traites,
                   jsonb_array_length(coalesce(quarantine_attributed_uids, '[]'::jsonb))
                         AS dont_fautifs,
                   items - jsonb_array_length(coalesce(quarantine_attributed_uids, '[]'::jsonb))
                         AS sains_jetes,
                   atoms_created AS atomes_produits,
                   quarantine_errors
              FROM arac.run_receipts
             WHERE status = 'quarantined'
             ORDER BY items DESC
             LIMIT 200
        """,
    ),
    Metric(
        key="quarantine_culprits",
        label="Conversations réellement fautives",
        unit="conversations",
        definition="Conversations auxquelles une quarantaine est explicitement attribuée.",
        formula="Σ longueur(quarantine_attributed_uids) sur les cycles quarantinés",
        domain="digestion",
        window="all",
        sql="""
            SELECT coalesce(sum(jsonb_array_length(
                     coalesce(quarantine_attributed_uids, '[]'::jsonb))), 0) AS value
              FROM arac.run_receipts WHERE status = 'quarantined'
        """,
        evidence_label="Les conversations mises en cause, cycle par cycle",
        evidence_sql="""
            SELECT r.id AS run_id, r.slot_key, r.started_at,
                   u.value #>> '{}' AS conversation_uid,
                   r.stop_reason
              FROM arac.run_receipts r
              CROSS JOIN LATERAL jsonb_array_elements(
                     coalesce(r.quarantine_attributed_uids, '[]'::jsonb)) AS u(value)
             WHERE r.status = 'quarantined'
             ORDER BY r.started_at DESC
             LIMIT 200
        """,
    ),
    Metric(
        key="quarantine_collateral",
        label="Conversations saines jetées",
        unit="passages",
        definition="Passages sains détruits parce qu'ils partageaient un cycle avec une conversation fautive.",
        formula="Σ items − Σ conversations fautives, sur les cycles quarantinés",
        domain="digestion",
        window="all",
        target={"warn": 50, "critical": 200, "direction": "down"},
        sql="""
            SELECT coalesce(sum(items), 0)
                 - coalesce(sum(jsonb_array_length(
                     coalesce(quarantine_attributed_uids, '[]'::jsonb))), 0) AS value
              FROM arac.run_receipts WHERE status = 'quarantined'
        """,
        evidence_label="Le détail des dégâts collatéraux, du plus lourd au plus léger",
        evidence_sql="""
            SELECT id AS run_id, slot_key, started_at, model,
                   items AS passages,
                   jsonb_array_length(coalesce(quarantine_attributed_uids, '[]'::jsonb)) AS fautifs,
                   items - jsonb_array_length(coalesce(quarantine_attributed_uids, '[]'::jsonb))
                         AS sains_jetes,
                   stop_reason
              FROM arac.run_receipts
             WHERE status = 'quarantined'
             ORDER BY sains_jetes DESC
             LIMIT 200
        """,
    ),
    Metric(
        key="quarantine_blast_radius",
        label="Rayon de souffle de la quarantaine",
        unit="conversations saines / fautive",
        definition="Nombre de conversations saines détruites pour chaque conversation réellement fautive.",
        formula="(Σ items − Σ fautives) / Σ fautives, sur les cycles quarantinés",
        domain="digestion",
        window="all",
        target={"warn": 1, "critical": 3, "direction": "down"},
        sql="""
            SELECT round(
                     (coalesce(sum(items), 0)
                      - coalesce(sum(jsonb_array_length(
                          coalesce(quarantine_attributed_uids, '[]'::jsonb))), 0))::numeric
                     / nullif(coalesce(sum(jsonb_array_length(
                          coalesce(quarantine_attributed_uids, '[]'::jsonb))), 0), 0), 2) AS value
              FROM arac.run_receipts WHERE status = 'quarantined'
        """,
        evidence_label="Le rayon de souffle par cycle : combien de saines pour une fautive",
        evidence_sql="""
            SELECT id AS run_id, started_at,
                   items AS passages,
                   jsonb_array_length(coalesce(quarantine_attributed_uids, '[]'::jsonb)) AS fautifs,
                   round((items - jsonb_array_length(coalesce(quarantine_attributed_uids, '[]'::jsonb)))::numeric
                         / nullif(jsonb_array_length(coalesce(quarantine_attributed_uids, '[]'::jsonb)), 0), 2)
                         AS rayon
              FROM arac.run_receipts
             WHERE status = 'quarantined'
             ORDER BY rayon DESC NULLS LAST
             LIMIT 200
        """,
    ),
    Metric(
        key="digestion_yield",
        label="Rendement de digestion",
        unit="%",
        definition="Part des passages de conversation qui aboutissent réellement à un cycle productif.",
        formula="items(cycles terminés) / items(tous cycles) × 100",
        domain="digestion",
        window="all",
        target={"warn": 70, "critical": 50, "direction": "up"},
        sql="""
            SELECT round(
                     100.0 * coalesce(sum(items) FILTER (WHERE status = 'done'), 0)
                     / nullif(coalesce(sum(items), 0), 0), 1) AS value
              FROM arac.run_receipts
        """,
        evidence_label="Où passent les passages : productifs contre perdus, par issue",
        evidence_sql="""
            SELECT status,
                   coalesce(sum(items), 0)         AS passages,
                   round(100.0 * coalesce(sum(items), 0)
                         / nullif((SELECT sum(items) FROM arac.run_receipts), 0), 1) AS part_pct,
                   coalesce(sum(atoms_created), 0) AS atomes_produits,
                   count(*)                        AS cycles
              FROM arac.run_receipts
             GROUP BY status
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="digestion_throughput_7d",
        label="Débit de digestion",
        unit="conversations / jour",
        definition="Conversations entièrement curées par jour, moyenne sur les 7 derniers jours.",
        formula="count(conversations curées sur 7 j) / 7",
        domain="digestion",
        window="7d",
        target={"warn": 3, "critical": 1, "direction": "up"},
        sql="""
            SELECT round(count(*)::numeric / 7, 2) AS value
              FROM arac.conversations
             WHERE curated_at > now() - interval '7 days'
        """,
        evidence_label="Les conversations curées jour par jour sur 30 jours",
        evidence_sql="""
            SELECT curated_at::date AS jour,
                   count(*)         AS conversations_curees,
                   coalesce(sum(atoms_generated), 0) AS atomes_generes
              FROM arac.conversations
             WHERE curated_at > now() - interval '30 days'
             GROUP BY 1
             ORDER BY 1 DESC
        """,
    ),
    Metric(
        key="backlog_eta_days",
        label="Résorption de la file",
        unit="jours",
        definition="Temps nécessaire pour absorber la file de curation au débit mesuré des 7 derniers jours.",
        formula="file de curation / débit quotidien",
        domain="digestion",
        window="7d",
        target={"warn": 7, "critical": 21, "direction": "down"},
        sql="""
            WITH file AS (
                SELECT count(*)::numeric AS n
                  FROM arac.conversations c
                 WHERE c.curated_through_message_id IS NULL
                    OR c.curated_through_message_id < (
                           SELECT max(rm.id) FROM arac.raw_messages rm
                            WHERE rm.conversation_id = c.id)
            ), debit AS (
                SELECT count(*)::numeric / 7 AS d
                  FROM arac.conversations
                 WHERE curated_at > now() - interval '7 days'
            )
            SELECT round(file.n / nullif(debit.d, 0), 1) AS value
              FROM file, debit
        """,
        evidence_label="Les deux termes du calcul : la file et le débit qui la résorbe",
        evidence_sql="""
            WITH file AS (
                SELECT count(*) AS n
                  FROM arac.conversations c
                 WHERE c.curated_through_message_id IS NULL
                    OR c.curated_through_message_id < (
                           SELECT max(rm.id) FROM arac.raw_messages rm
                            WHERE rm.conversation_id = c.id)
            ), debit AS (
                SELECT count(*) AS cures_7j FROM arac.conversations
                 WHERE curated_at > now() - interval '7 days'
            )
            SELECT 'file de curation' AS terme, file.n::text AS valeur,
                   'conversations non entièrement lues' AS lecture FROM file
            UNION ALL
            SELECT 'curées sur 7 jours', debit.cures_7j::text,
                   'base du débit quotidien' FROM debit
            UNION ALL
            SELECT 'débit quotidien', round(debit.cures_7j::numeric / 7, 2)::text,
                   'curées / 7' FROM debit
            LIMIT 3
        """,
    ),

    # ----------------------------------------------------------------- rappel
    Metric(
        key="recall_receipts_total",
        label="Reçus de rappel",
        unit="reçus",
        definition="Rappels servis et tracés depuis l'origine.",
        formula="count(context_receipts)",
        domain="rappel",
        window="all",
        sql="SELECT count(*) AS value FROM arac.context_receipts",
        evidence_label="Les derniers rappels servis, avec leur bande et leur motif d'arrêt",
        evidence_sql="""
            SELECT created_at, consumer, engine_version, calibration_version,
                   scope_filter, k_requested,
                   coalesce(array_length(served_ids, 1), 0) AS servis,
                   round(top1_distance_final::numeric, 3)   AS distance_top1,
                   raw_band, final_band, stop_reason,
                   round(shadow_latency_ms::numeric, 0)     AS latence_ms
              FROM arac.context_receipts
             ORDER BY created_at DESC
             LIMIT 200
        """,
    ),
    Metric(
        key="recall_low_band_ratio",
        label="Rappels en confiance basse",
        unit="%",
        definition="Part des rappels servis dans une bande de confiance basse ou nulle.",
        formula="reçus dont final_band ∈ {low, none} / total × 100",
        domain="rappel",
        window="all",
        target={"warn": 60, "critical": 80, "direction": "down"},
        sql="""
            SELECT round(
                     100.0 * count(*) FILTER (WHERE final_band IN ('low', 'none'))
                     / nullif(count(*), 0), 1) AS value
              FROM arac.context_receipts
        """,
        evidence_label="La distribution complète des bandes, brute puis finale",
        evidence_sql="""
            SELECT raw_band, final_band, count(*) AS recus,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS part_pct,
                   round(avg(top1_distance_final)::numeric, 3) AS distance_moyenne
              FROM arac.context_receipts
             GROUP BY raw_band, final_band
             ORDER BY 3 DESC
        """,
    ),
    Metric(
        key="recall_budget_stop_ratio",
        label="Rappels arrêtés sur le budget",
        unit="%",
        definition="Part des rappels qui s'arrêtent parce que le budget de contexte est atteint, non parce que le corpus est épuisé.",
        formula="reçus dont stop_reason='budget' / total × 100",
        domain="rappel",
        window="all",
        sql="""
            SELECT round(100.0 * count(*) FILTER (WHERE stop_reason = 'budget')
                         / nullif(count(*), 0), 1) AS value
              FROM arac.context_receipts
        """,
        evidence_label="Les motifs d'arrêt, par fréquence",
        evidence_sql="""
            SELECT stop_reason, count(*) AS recus,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS part_pct,
                   round(avg(k_requested)::numeric, 1) AS k_demande_moyen
              FROM arac.context_receipts
             GROUP BY stop_reason
             ORDER BY 2 DESC
        """,
    ),

    # -------------------------------------------------------------- vitalité
    Metric(
        key="nodes_total",
        label="Nœuds déclarés",
        unit="nœuds",
        definition="Machines et agents connus du cerveau.",
        formula="count(nodes)",
        domain="observabilite",
        sql="SELECT count(*) AS value FROM arac.nodes",
        evidence_label="Les nœuds, leur dernier pouls, et leur silence évalué contre leur propre seuil",
        evidence_sql="""
            SELECT n.node_id,
                   n.role,
                   n.active,
                   n.last_heartbeat,
                   round(extract(epoch FROM (now() - n.last_heartbeat)) / 60)::bigint
                        AS silence_minutes,
                   n.silent_warn_minutes,
                   n.silent_critical_minutes,
                   CASE
                     WHEN n.last_heartbeat IS NULL THEN 'jamais vu'
                     WHEN n.silent_critical_minutes IS NOT NULL
                          AND now() - n.last_heartbeat
                              > make_interval(mins => n.silent_critical_minutes) THEN 'critique'
                     WHEN n.silent_warn_minutes IS NOT NULL
                          AND now() - n.last_heartbeat
                              > make_interval(mins => n.silent_warn_minutes) THEN 'silencieux'
                     ELSE 'vivant'
                   END AS etat,
                   (SELECT count(*) FROM arac.nodes_heartbeat_history h
                     WHERE h.node_id = n.node_id) AS pouls_enregistres
              FROM arac.nodes n
             ORDER BY n.last_heartbeat DESC NULLS LAST
             LIMIT 100
        """,
    ),
    Metric(
        key="audit_calls_total",
        label="Appels d'outils audités",
        unit="appels",
        definition="Appels d'outils tracés par les agents depuis l'origine.",
        formula="count(audit_log)",
        domain="audits",
        window="all",
        sql="SELECT count(*) AS value FROM arac.audit_log",
        evidence_label="Les derniers appels, avec leur issue et leur coût",
        evidence_sql="""
            SELECT created_at, node_id, action, tool_name, success,
                   tokens_used, latency_ms, warning_code, error_message
              FROM arac.audit_log
             ORDER BY created_at DESC
             LIMIT 200
        """,
    ),
    Metric(
        key="ingest_receipts_total",
        label="Reçus d'ingestion",
        unit="reçus",
        definition="Tentatives d'ingestion tracées, acceptées comme refusées.",
        formula="count(ingest_receipts)",
        domain="pipeline",
        window="all",
        sql="SELECT count(*) AS value FROM arac.ingest_receipts",
        evidence_label="Les issues d'ingestion, par fréquence",
        evidence_sql="""
            SELECT outcome, count(*) AS recus,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS part_pct
              FROM arac.ingest_receipts
             GROUP BY outcome
             ORDER BY 2 DESC
        """,
    ),
    Metric(
        key="drop_reasons_total",
        label="Candidats écartés",
        unit="candidats",
        definition="Atomes proposés puis écartés pendant la digestion, avec leur motif.",
        formula="count(digestion_review_queue)",
        domain="digestion",
        window="all",
        sql="SELECT count(*) AS value FROM arac.digestion_review_queue",
        evidence_label="Les motifs d'écartement, par fréquence",
        evidence_sql="""
            SELECT drop_reason, count(*) AS candidats,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS part_pct,
                   min(created_at) AS premier, max(created_at) AS dernier
              FROM arac.digestion_review_queue
             GROUP BY drop_reason
             ORDER BY 2 DESC
        """,
    ),
)


# ============================================================================
# Familles — extension du registre sans conflit d'édition
# ============================================================================
#
# Le registre de base (CORE) couvre les constantes vitales. Les familles
# thématiques vivent dans ``control_center/cc_v1/families/<nom>.py`` et
# exportent chacune ``METRICS: tuple[Metric, ...]``.
#
# Pourquoi ce découpage : il permet d'étendre le cockpit métrique par métrique
# sans jamais rouvrir ce fichier — donc sans conflit quand plusieurs chantiers
# avancent en parallèle. L'invariant G1 s'applique identiquement aux familles :
# le type ``Metric`` refuse toujours une métrique sans preuve, d'où qu'elle vienne.
#
# Le chargement est TOLÉRANT : une famille absente ou cassée ne fait pas tomber
# le cockpit, elle est simplement absente du registre et journalisée. Le socle
# doit survivre à une extension défaillante.

FAMILY_MODULES: tuple[str, ...] = (
    "etat_general",
    "aujourdhui",
    "confiance",
    "vues",
    "memoire",
    "croissance",
    "pipeline",
    "digestion",
    "rappel",
    "projets",
)
"""Familles chargées, dans l'ordre. Une famille absente est ignorée sans erreur."""

LOAD_ERRORS: dict[str, str] = {}
"""Familles dont le chargement a échoué : {nom: type d'erreur}. Exposé par l'API
pour que l'interface puisse dire ce qui manque, plutôt que de l'ignorer."""


def _load_families() -> tuple[Metric, ...]:
    """Charge les familles déclarées. Ne lève jamais."""
    import importlib

    out: list[Metric] = []
    for name in FAMILY_MODULES:
        try:
            mod = importlib.import_module(f"control_center.cc_v1.families.{name}")
        except ModuleNotFoundError:
            continue  # famille pas encore écrite — cas nominal
        except Exception as exc:  # noqa: BLE001 — une famille cassée n'abat pas le socle
            LOAD_ERRORS[name] = f"{type(exc).__name__}: {exc}"
            continue
        metrics = getattr(mod, "METRICS", ())
        if not isinstance(metrics, (list, tuple)):
            LOAD_ERRORS[name] = "METRICS n'est pas une séquence"
            continue
        for m in metrics:
            if isinstance(m, Metric):
                out.append(m)
            else:
                LOAD_ERRORS[name] = "METRICS contient un objet qui n'est pas une Metric"
    return tuple(out)


def _dedupe(metrics: tuple[Metric, ...]) -> tuple[Metric, ...]:
    """Première déclaration gagne : CORE ne peut pas être écrasé par une famille."""
    seen: set[str] = set()
    out: list[Metric] = []
    for m in metrics:
        if m.key in seen:
            LOAD_ERRORS[m.key] = "clé dupliquée — la déclaration la plus ancienne est conservée"
            continue
        seen.add(m.key)
        out.append(m)
    return tuple(out)


REGISTRY: tuple[Metric, ...] = _dedupe(CORE + _load_families())


# ============================================================================
# Accès
# ============================================================================

_BY_KEY: dict[str, Metric] = {m.key: m for m in REGISTRY}

if len(_BY_KEY) != len(REGISTRY):  # pragma: no cover — garde de chargement
    raise ValueError("Clés de métriques dupliquées dans le registre.")


def by_key(key: str) -> Metric:
    """Retourne la métrique de clé ``key``. Lève ``KeyError`` si inconnue.

    C'est le SEUL point d'entrée depuis une requête HTTP : une clé inconnue lève,
    elle ne construit jamais de SQL. Aucune surface d'injection.
    """
    return _BY_KEY[key]


def keys() -> tuple[str, ...]:
    """Toutes les clés du registre, dans l'ordre de déclaration."""
    return tuple(m.key for m in REGISTRY)


def by_domain(domain: str) -> tuple[Metric, ...]:
    """Les métriques appartenant à un domaine d'interface."""
    return tuple(m for m in REGISTRY if m.domain == domain)
