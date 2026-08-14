"""Famille « croissance » — le cerveau grossit-il, et à quelle vitesse (READ-ONLY strict).

La famille ``memoire`` décrit le stock. Celle-ci décrit le **débit** : ce que le
cerveau a gagné, ce qu'il a perdu, et à quel rythme.

Le parti pris central est le suivant :

    **La croissance brute ment par omission.**

Compter les atomes créés flatte toujours : elle ignore ceux que la même période
a remplacés ou archivés. La métrique de référence de cette famille est donc la
croissance **nette** — ``créés − remplacés − archivés`` —, la croissance brute
n'étant servie qu'à côté d'elle, pour qu'on puisse voir l'écart.

Trois autres règles, lisibles dans le SQL :

1. **``agent_message`` est exclu partout.** Ces atomes sont du transport entre
   nœuds, pas du savoir ; les compter gonflerait la croissance d'un bruit qui
   n'apprend rien à personne.

2. **Un jour sans atome n'est pas un jour manquant.** Toutes les séries
   temporelles sont bâties sur un ``generate_series`` puis jointes en ``LEFT
   JOIN`` : un jour à zéro apparaît explicitement avec sa valeur zéro. C'est la
   seule façon de distinguer « le cerveau n'a rien appris ce jour-là » de « on
   n'a pas la donnée » — confondre les deux est exactement l'erreur que la
   règle I2 interdit.

3. **Les séries vivent dans la preuve, la valeur résume.** Une métrique retourne
   un scalaire ; sa preuve retourne la courbe complète, jour par jour ou semaine
   par semaine, rejouable depuis un terminal.
"""

from __future__ import annotations

from control_center.cc_v1.metric import Metric

__all__ = ["METRICS"]


METRICS: tuple[Metric, ...] = (

    # -------------------------------------------------- la métrique de référence
    Metric(
        key="atoms_net_growth_30d",
        label="Croissance nette du savoir",
        unit="atomes",
        definition=(
            "Ce que le cerveau a réellement gagné en trente jours : les atomes "
            "créés, moins ceux que la même période a remplacés ou archivés."
        ),
        formula="crees(30j) - remplaces(30j) - archives(30j), hors transport",
        domain="croissance",
        window="30d",
        # Franchir zéro par le bas signifie que le cerveau se vide plus vite
        # qu'il n'apprend. Ce n'est pas un seuil choisi, c'est un changement de
        # signe : au-dessous, la croissance nette est une décroissance.
        target={"warn": 0, "direction": "up"},
        sql="""
            SELECT count(*) FILTER (WHERE created_at >= now() - interval '30 days')
                 - count(*) FILTER (WHERE status = 'superseded'
                                      AND updated_at >= now() - interval '30 days')
                 - count(*) FILTER (WHERE status = 'archived'
                                      AND updated_at >= now() - interval '30 days')
                   AS value
              FROM arac.memory_atoms
             WHERE kind <> 'agent_message'
        """,
        evidence_label="Les trois mouvements qui composent le solde des trente derniers jours",
        evidence_sql="""
            SELECT m.mouvement,
                   m.signe,
                   count(a.id) AS atomes,
                   min(a.created_at) AS premier_atome_concerne,
                   max(a.created_at) AS dernier_atome_concerne
              FROM (VALUES ('atomes crees', 1),
                           ('atomes remplaces', -1),
                           ('atomes archives', -1)) AS m(mouvement, signe)
              LEFT JOIN arac.memory_atoms a
                     ON a.kind <> 'agent_message'
                    AND ((m.mouvement = 'atomes crees'
                          AND a.created_at >= now() - interval '30 days')
                      OR (m.mouvement = 'atomes remplaces'
                          AND a.status = 'superseded'
                          AND a.updated_at >= now() - interval '30 days')
                      OR (m.mouvement = 'atomes archives'
                          AND a.status = 'archived'
                          AND a.updated_at >= now() - interval '30 days'))
             GROUP BY m.mouvement, m.signe
             ORDER BY 2 DESC, 3 DESC
        """,
    ),

    Metric(
        key="atoms_gross_growth_30d",
        label="Croissance brute du savoir",
        unit="atomes",
        definition=(
            "Atomes de savoir créés au cours des trente derniers jours, sans "
            "déduire ceux que la même période a remplacés ou archivés."
        ),
        formula="count(atomes crees dans les 30 derniers jours), hors transport",
        domain="croissance",
        window="30d",
        sql="""
            SELECT count(*) AS value
              FROM arac.memory_atoms
             WHERE kind <> 'agent_message'
               AND created_at >= now() - interval '30 days'
        """,
        evidence_label="Ce que le cerveau a appris en trente jours, par nature d'atome",
        evidence_sql="""
            SELECT kind,
                   count(*) AS atomes_crees,
                   count(DISTINCT scope) AS territoires_touches,
                   count(*) FILTER (WHERE status <> 'active') AS deja_retires_du_rappel,
                   max(created_at) AS dernier
              FROM arac.memory_atoms
             WHERE kind <> 'agent_message'
               AND created_at >= now() - interval '30 days'
             GROUP BY kind
             ORDER BY 2 DESC
        """,
    ),

    Metric(
        key="net_growth_retention_30d",
        label="Rétention de la croissance",
        unit="%",
        definition=(
            "Part de ce que le cerveau a appris en trente jours qui lui reste "
            "après déduction des remplacements et des archivages de la période."
        ),
        formula="100 x (crees - remplaces - archives) / crees, sur 30 jours, hors transport",
        domain="croissance",
        window="30d",
        sql="""
            SELECT round(
                       100.0 * (count(*) FILTER (WHERE created_at >= now() - interval '30 days')
                              - count(*) FILTER (WHERE status = 'superseded'
                                                   AND updated_at >= now() - interval '30 days')
                              - count(*) FILTER (WHERE status = 'archived'
                                                   AND updated_at >= now() - interval '30 days'))
                       / nullif(count(*) FILTER (WHERE created_at >= now() - interval '30 days'), 0),
                       1) AS value
              FROM arac.memory_atoms
             WHERE kind <> 'agent_message'
        """,
        evidence_label="Le devenir de chaque promotion hebdomadaire d'atomes, semaine par semaine",
        evidence_sql="""
            SELECT date_trunc('week', created_at)::date AS semaine_de_naissance,
                   count(*) AS atomes_crees,
                   count(*) FILTER (WHERE status = 'active') AS encore_vivants,
                   count(*) FILTER (WHERE status = 'superseded') AS depuis_remplaces,
                   count(*) FILTER (WHERE status = 'archived') AS depuis_archives,
                   round(100.0 * count(*) FILTER (WHERE status = 'active')
                         / nullif(count(*), 0), 1) AS survie_pct
              FROM arac.memory_atoms
             WHERE kind <> 'agent_message'
             GROUP BY 1
             ORDER BY 1 DESC
             LIMIT 30
        """,
    ),

    # ------------------------------------------------------------ débit récent
    # DEUX POPULATIONS, UN SEUL LIBELLÉ (corrigé 2026-08-05, hors constats fournis).
    # Cette famille compte des CRÉATIONS, tous statuts confondus — c'est son parti pris
    # (« la croissance brute ment par omission », d'où la métrique nette à côté). Mais
    # l'écran « Aujourd'hui » répond à la MÊME question en ne comptant que la population
    # ACTIVE : mesuré le 2026-08-05, 46 ici contre 44 là sur 7 jours, sans qu'aucun des
    # deux libellés ne dise laquelle des deux populations il compte. Deux cartes du même
    # cockpit, deux chiffres, aucune explication : c'est exactement ce que la règle du
    # « chiffre opposable » interdit.
    # Le chiffre ne change pas — il est juste pour ce qu'il mesure —, mais il DIT
    # désormais ce qu'il mesure, et sa preuve porte la colonne qui reconstruit l'autre.
    Metric(
        key="atoms_created_24h",
        label="Savoir appris en 24 heures",
        unit="atomes",
        definition=(
            "Atomes de savoir créés depuis vingt-quatre heures, tous statuts confondus "
            "— y compris ceux qu'une version plus récente a déjà remplacés ; l'écran "
            "« Aujourd'hui » compte, lui, les seuls atomes encore actifs. Une valeur de "
            "zéro signifie une journée sans apprentissage, pas une donnée manquante."
        ),
        formula="count(atomes crees depuis 24 heures, tous statuts), hors transport",
        domain="croissance",
        window="24h",
        sql="""
            SELECT count(*) AS value
              FROM arac.memory_atoms
             WHERE kind <> 'agent_message'
               AND created_at >= now() - interval '24 hours'
        """,
        evidence_label=("Les sept derniers jours, jour par jour, jours vides compris, "
                        "avec la part encore active qui explique l'écart avec « Aujourd'hui »"),
        evidence_sql="""
            SELECT j.jour::date AS jour,
                   count(a.id) AS atomes_crees,
                   count(a.id) FILTER (WHERE a.status = 'active') AS encore_actifs,
                   count(a.id) FILTER (WHERE a.status <> 'active') AS deja_remplaces_ou_archives,
                   (count(a.id) = 0) AS journee_muette,
                   count(DISTINCT a.scope) AS territoires_touches
              FROM (SELECT generate_series(date_trunc('day', now()) - interval '6 days',
                                           date_trunc('day', now()),
                                           interval '1 day') AS jour) j
              LEFT JOIN arac.memory_atoms a
                     ON a.kind <> 'agent_message'
                    AND a.created_at >= j.jour
                    AND a.created_at < j.jour + interval '1 day'
             GROUP BY j.jour
             ORDER BY 1 DESC
        """,
    ),

    Metric(
        key="atoms_created_7d",
        label="Savoir appris en 7 jours",
        unit="atomes",
        # Même correction que `atoms_created_24h` : le libellé dit maintenant QUELLE
        # population il compte. 46 ici (tous statuts) contre 44 sur l'écran
        # « Aujourd'hui » (actifs) le 2026-08-05 ; l'écart est exactement la colonne
        # `deja_remplaces_ou_archives` de la preuve, qui le rend vérifiable en un
        # coup d'œil au lieu de le laisser passer pour une contradiction.
        definition=(
            "Atomes de savoir créés au cours des sept derniers jours, tous statuts "
            "confondus — y compris ceux qu'une version plus récente a déjà remplacés ; "
            "l'écran « Aujourd'hui » compte, lui, les seuls atomes encore actifs."
        ),
        formula="count(atomes crees depuis 7 jours, tous statuts), hors transport",
        domain="croissance",
        window="7d",
        sql="""
            SELECT count(*) AS value
              FROM arac.memory_atoms
             WHERE kind <> 'agent_message'
               AND created_at >= now() - interval '7 days'
        """,
        evidence_label=("Ce qui a été appris cette semaine, par territoire et par nature, "
                        "avec la part encore active qui explique l'écart avec « Aujourd'hui »"),
        evidence_sql="""
            SELECT scope,
                   kind,
                   count(*) AS atomes_crees,
                   count(*) FILTER (WHERE status = 'active') AS encore_actifs,
                   count(*) FILTER (WHERE status <> 'active') AS deja_remplaces_ou_archives,
                   min(created_at) AS premier,
                   max(created_at) AS dernier
              FROM arac.memory_atoms
             WHERE kind <> 'agent_message'
               AND created_at >= now() - interval '7 days'
             GROUP BY scope, kind
             ORDER BY 3 DESC
             LIMIT 200
        """,
    ),

    Metric(
        key="atoms_weekly_rate_12w",
        label="Rythme hebdomadaire moyen",
        unit="atomes par semaine",
        definition=(
            "Nombre moyen d'atomes de savoir appris par semaine sur les douze "
            "dernières semaines, semaine en cours incluse."
        ),
        formula="count(atomes crees depuis le debut de la 12e semaine glissante) / 12",
        domain="croissance",
        window="90d",
        sql="""
            SELECT round(count(*)::numeric / 12.0, 1) AS value
              FROM arac.memory_atoms
             WHERE kind <> 'agent_message'
               AND created_at >= date_trunc('week', now()) - interval '11 weeks'
        """,
        evidence_label="La série hebdomadaire des douze dernières semaines, semaines vides comprises",
        evidence_sql="""
            SELECT s.semaine::date AS semaine,
                   count(a.id) AS atomes_crees,
                   (count(a.id) = 0) AS semaine_muette,
                   count(DISTINCT a.scope) AS territoires_touches,
                   count(DISTINCT a.kind) AS natures_distinctes
              FROM (SELECT generate_series(date_trunc('week', now()) - interval '11 weeks',
                                           date_trunc('week', now()),
                                           interval '1 week') AS semaine) s
              LEFT JOIN arac.memory_atoms a
                     ON a.kind <> 'agent_message'
                    AND a.created_at >= s.semaine
                    AND a.created_at < s.semaine + interval '1 week'
             GROUP BY s.semaine
             ORDER BY 1
        """,
    ),

    Metric(
        key="atoms_growth_momentum_7d",
        label="Élan du savoir",
        unit="%",
        definition=(
            "Écart entre ce que le cerveau a appris ces sept derniers jours et "
            "ce qu'il avait appris les sept jours précédents."
        ),
        formula="100 x (crees derniers 7j - crees 7j precedents) / crees 7j precedents",
        domain="croissance",
        window="7d",
        # Zéro n'est pas un seuil arbitraire : c'est le changement de signe. En
        # dessous, le cerveau apprend moins vite que la semaine d'avant.
        target={"warn": 0, "direction": "up"},
        sql="""
            SELECT round(
                       100.0 * (count(*) FILTER (WHERE created_at >= now() - interval '7 days')
                              - count(*) FILTER (WHERE created_at >= now() - interval '14 days'
                                                   AND created_at < now() - interval '7 days'))
                       / nullif(count(*) FILTER (WHERE created_at >= now() - interval '14 days'
                                                   AND created_at < now() - interval '7 days'), 0),
                       1) AS value
              FROM arac.memory_atoms
             WHERE kind <> 'agent_message'
        """,
        evidence_label="Les deux semaines comparées, avec leur volume et leur étendue",
        evidence_sql="""
            SELECT f.fenetre,
                   count(a.id) AS atomes_crees,
                   count(DISTINCT a.scope) AS territoires_touches,
                   min(a.created_at) AS premier,
                   max(a.created_at) AS dernier
              FROM (VALUES ('7 derniers jours'), ('7 jours precedents')) AS f(fenetre)
              LEFT JOIN arac.memory_atoms a
                     ON a.kind <> 'agent_message'
                    AND ((f.fenetre = '7 derniers jours'
                          AND a.created_at >= now() - interval '7 days')
                      OR (f.fenetre = '7 jours precedents'
                          AND a.created_at >= now() - interval '14 days'
                          AND a.created_at < now() - interval '7 days'))
             GROUP BY f.fenetre
             ORDER BY 1
        """,
    ),

    # ---------------------------------------------------------- silences
    Metric(
        key="atoms_silent_days_30d",
        label="Journées sans aucun apprentissage",
        unit="jours",
        definition=(
            "Nombre de journées, parmi les trente dernières, où le cerveau n'a "
            "produit aucun atome de savoir."
        ),
        formula="count(jours de la fenetre 30j dont le total d'atomes crees vaut 0)",
        domain="croissance",
        window="30d",
        sql="""
            WITH jours AS (
                SELECT generate_series(date_trunc('day', now()) - interval '29 days',
                                       date_trunc('day', now()),
                                       interval '1 day') AS jour
            ),
            serie AS (
                SELECT j.jour, count(a.id) AS atomes
                  FROM jours j
                  LEFT JOIN arac.memory_atoms a
                         ON a.kind <> 'agent_message'
                        AND a.created_at >= j.jour
                        AND a.created_at < j.jour + interval '1 day'
                 GROUP BY j.jour
            )
            SELECT count(*) FILTER (WHERE atomes = 0) AS value
              FROM serie
        """,
        evidence_label="La série quotidienne des trente derniers jours, chaque journée muette marquée",
        evidence_sql="""
            SELECT j.jour::date AS jour,
                   count(a.id) AS atomes_crees,
                   (count(a.id) = 0) AS journee_muette,
                   count(DISTINCT a.scope) AS territoires_touches,
                   max(a.created_at) AS dernier_atome_du_jour
              FROM (SELECT generate_series(date_trunc('day', now()) - interval '29 days',
                                           date_trunc('day', now()),
                                           interval '1 day') AS jour) j
              LEFT JOIN arac.memory_atoms a
                     ON a.kind <> 'agent_message'
                    AND a.created_at >= j.jour
                    AND a.created_at < j.jour + interval '1 day'
             GROUP BY j.jour
             ORDER BY 1 DESC
        """,
    ),

    Metric(
        key="last_atom_age_hours",
        label="Âge du dernier savoir appris",
        unit="heures",
        definition=(
            "Temps écoulé depuis la création du dernier atome de savoir, quel "
            "que soit son territoire."
        ),
        formula="(maintenant - max(created_at)) en heures, hors transport",
        domain="croissance",
        window="instant",
        # Seuils calés sur la cadence observée de la digestion : un cycle par
        # jour (run_receipts couvre 32 jours sur 32). Depasser 24 h signifie
        # donc qu'un cycle complet n'a rien produit ; 72 h, que trois cycles
        # consecutifs n'ont rien produit.
        target={"warn": 24, "critical": 72, "direction": "down"},
        sql="""
            SELECT round((extract(epoch FROM now() - max(created_at)) / 3600.0)::numeric, 1)
                     AS value
              FROM arac.memory_atoms
             WHERE kind <> 'agent_message'
        """,
        evidence_label="Les derniers atomes appris, du plus récent au plus ancien",
        evidence_sql="""
            SELECT created_at,
                   round((extract(epoch FROM now() - created_at) / 3600.0)::numeric, 1)
                     AS age_heures,
                   scope,
                   kind,
                   key,
                   status
              FROM arac.memory_atoms
             WHERE kind <> 'agent_message'
             ORDER BY created_at DESC
             LIMIT 50
        """,
    ),

    # ------------------------------------------------- croissance de la matière
    Metric(
        key="conversations_created_30d",
        label="Conversations absorbées sur 30 jours",
        unit="conversations",
        definition=(
            "Conversations entrées dans le cerveau au cours des trente derniers "
            "jours, toutes sources confondues."
        ),
        formula="count(conversations WHERE created_at >= maintenant - 30 jours)",
        domain="croissance",
        window="30d",
        sql="""
            SELECT count(*) AS value
              FROM arac.conversations
             WHERE created_at >= now() - interval '30 days'
        """,
        evidence_label="Les conversations absorbées semaine par semaine, par source et par état de curation",
        evidence_sql="""
            SELECT date_trunc('week', created_at)::date AS semaine,
                   source_type,
                   count(*) AS conversations,
                   count(*) FILTER (WHERE curated_at IS NOT NULL) AS deja_curees,
                   count(*) FILTER (WHERE excluded_at IS NOT NULL) AS exclues
              FROM arac.conversations
             WHERE created_at >= now() - interval '30 days'
             GROUP BY 1, 2
             ORDER BY 1 DESC, 3 DESC
        """,
    ),

    Metric(
        key="raw_messages_received_30d",
        label="Messages reçus sur 30 jours",
        unit="messages",
        definition=(
            "Messages bruts entrés dans le cerveau au cours des trente derniers "
            "jours : c'est la matière première de la digestion."
        ),
        formula="count(raw_messages WHERE received_at >= maintenant - 30 jours)",
        domain="croissance",
        window="30d",
        sql="""
            SELECT count(*) AS value
              FROM arac.raw_messages
             WHERE received_at >= now() - interval '30 days'
        """,
        evidence_label="La série quotidienne des messages reçus, journées vides comprises",
        evidence_sql="""
            SELECT j.jour::date AS jour,
                   count(m.id) AS messages_recus,
                   (count(m.id) = 0) AS journee_muette,
                   count(DISTINCT m.conversation_id) AS conversations_alimentees,
                   count(m.id) FILTER (WHERE m.was_masked) AS messages_masques
              FROM (SELECT generate_series(date_trunc('day', now()) - interval '29 days',
                                           date_trunc('day', now()),
                                           interval '1 day') AS jour) j
              LEFT JOIN arac.raw_messages m
                     ON m.received_at >= j.jour
                    AND m.received_at < j.jour + interval '1 day'
             GROUP BY j.jour
             ORDER BY 1 DESC
        """,
    ),

    Metric(
        key="scopes_opened_30d",
        label="Territoires ouverts sur 30 jours",
        unit="scopes",
        definition=(
            "Nombre de territoires de savoir dont le tout premier atome date des "
            "trente derniers jours : c'est l'élargissement de la carte."
        ),
        formula="count(scopes dont min(created_at) >= maintenant - 30 jours), hors transport",
        domain="croissance",
        window="30d",
        sql="""
            WITH ouverture AS (
                SELECT scope, min(created_at) AS premier_atome
                  FROM arac.memory_atoms
                 WHERE kind <> 'agent_message'
                 GROUP BY scope
            )
            SELECT count(*) AS value
              FROM ouverture
             WHERE premier_atome >= now() - interval '30 days'
        """,
        evidence_label="Chaque territoire par date d'ouverture, du plus récent au plus ancien",
        evidence_sql="""
            SELECT scope,
                   min(created_at) AS ouvert_le,
                   (min(created_at) >= now() - interval '30 days') AS ouvert_dans_la_fenetre,
                   count(*) AS atomes_depuis,
                   count(*) FILTER (WHERE status = 'active') AS encore_vivants,
                   max(created_at) AS dernier_atome
              FROM arac.memory_atoms
             WHERE kind <> 'agent_message'
             GROUP BY scope
             ORDER BY 2 DESC
        """,
    ),
)
