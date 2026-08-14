"""Famille « mémoire » — l'état du savoir déjà constitué (READ-ONLY strict).

Cette famille répond à une seule question : **de quoi le cerveau se souvient-il,
et dans quel état ?** Elle ne mesure pas le débit (voir la famille
``croissance``) mais le stock : sa composition, sa confiance, sa fraîcheur, sa
répartition dans la carte des scopes, et son outillage de rappel.

Trois partis pris, tous vérifiables dans le SQL ci-dessous :

1. **``agent_message`` n'est pas du savoir.** C'est du TRANSPORT : des messages
   de bus entre nœuds, stockés dans la même table que les atomes parce que
   c'était commode. Toute métrique de savoir l'exclut explicitement
   (``kind <> 'agent_message'``), et une métrique dédiée l'isole pour qu'on
   puisse vérifier qu'il ne contamine rien.

2. **Une absence de donnée n'est pas un zéro.** Les métriques de couverture
   (vérification, horizon de validité, représentation dérivée) mesurent la part
   du savoir qui porte réellement l'information. Quand cette part vaut 0 %, la
   valeur ne dit pas « tout va bien », elle dit « cette information n'existe
   nulle part » — et la preuve le montre ligne par ligne. Les divisions passent
   toutes par ``nullif(..., 0)`` : un dénominateur vide produit ``NULL``, donc un
   état ``unavailable`` motivé, jamais un faux 0 %.

3. **L'arithmétique est en SQL.** Pourcentages, médianes et ratios sont calculés
   par PostgreSQL. Ni le BFF ni le navigateur ne touchent aux chiffres.
"""

from __future__ import annotations

from control_center.cc_v1.metric import Metric

__all__ = ["METRICS"]


# Les quatre natures qui portent l'essentiel du savoir opérationnel. Ce n'est
# pas un choix esthétique : ce sont les seules natures qui décrivent un fait
# réutilisable (un piège, une décision, un état, un motif). Le reste est du
# commentaire, de la référence ou de l'intention.
_STRUCTURANTS = "'gotcha', 'decision', 'state', 'pattern'"


METRICS: tuple[Metric, ...] = (

    # ------------------------------------------------------------ composition
    Metric(
        key="atoms_core_kinds_share",
        label="Part du savoir structurant",
        unit="%",
        definition=(
            "Part des souvenirs vivants qui décrivent un piège, une décision, "
            "un état ou un motif — les quatre natures réellement réutilisables."
        ),
        formula="100 x actifs(gotcha, decision, state, pattern) / actifs hors transport",
        domain="memoire",
        window="instant",
        sql=f"""
            SELECT round(
                       100.0 * count(*) FILTER (WHERE kind IN ({_STRUCTURANTS}))
                       / nullif(count(*), 0), 1) AS value
              FROM arac.memory_atoms
             WHERE status = 'active' AND kind <> 'agent_message'
        """,
        evidence_label="Chaque nature d'atome, son poids, et si elle est structurante",
        evidence_sql=f"""
            SELECT kind,
                   count(*) AS atomes,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS part_pct,
                   (kind IN ({_STRUCTURANTS})) AS structurant,
                   max(created_at) AS dernier
              FROM arac.memory_atoms
             WHERE status = 'active' AND kind <> 'agent_message'
             GROUP BY kind
             ORDER BY 2 DESC
        """,
    ),

    Metric(
        key="unvalidated_knowledge_share",
        label="Savoir non validé",
        unit="%",
        definition=(
            "Part des souvenirs vivants qui n'ont jamais été confirmés par un "
            "auditeur : ils reposent uniquement sur la parole de leur producteur."
        ),
        formula="100 x actifs(confidence = 'producer') / actifs hors transport",
        domain="memoire",
        window="instant",
        sql="""
            SELECT round(
                       100.0 * count(*) FILTER (WHERE confidence = 'producer')
                       / nullif(count(*), 0), 1) AS value
              FROM arac.memory_atoms
             WHERE status = 'active' AND kind <> 'agent_message'
        """,
        evidence_label="Le niveau de confiance déclaré, et le score obtenu",
        evidence_sql="""
            SELECT confidence,
                   count(*) AS atomes,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS part_pct,
                   count(*) FILTER (WHERE confidence_score IS NULL) AS sans_score_chiffre,
                   min(confidence_score) AS score_min,
                   max(confidence_score) AS score_max
              FROM arac.memory_atoms
             WHERE status = 'active' AND kind <> 'agent_message'
             GROUP BY confidence
             ORDER BY 2 DESC
        """,
    ),

    # -------------------------------------------------------------- fraîcheur
    Metric(
        key="atoms_median_age_days",
        label="Âge médian du savoir",
        unit="jours",
        definition=(
            "Âge de l'atome vivant du milieu : la moitié du savoir rappelable "
            "est plus ancienne que cette valeur."
        ),
        formula="mediane(maintenant - created_at) sur les actifs hors transport, en jours",
        domain="memoire",
        window="all",
        sql="""
            SELECT round(
                       percentile_cont(0.5) WITHIN GROUP (
                           ORDER BY extract(epoch FROM now() - created_at) / 86400.0
                       )::numeric, 1) AS value
              FROM arac.memory_atoms
             WHERE status = 'active' AND kind <> 'agent_message'
        """,
        evidence_label="La pyramide des âges du savoir vivant, par tranche",
        evidence_sql="""
            SELECT CASE
                     WHEN created_at >= now() - interval '7 days'  THEN 'moins de 7 jours'
                     WHEN created_at >= now() - interval '30 days' THEN 'de 7 a 30 jours'
                     WHEN created_at >= now() - interval '90 days' THEN 'de 30 a 90 jours'
                     ELSE 'plus de 90 jours'
                   END AS tranche_age,
                   count(*) AS atomes,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS part_pct,
                   min(created_at) AS plus_ancien,
                   max(created_at) AS plus_recent
              FROM arac.memory_atoms
             WHERE status = 'active' AND kind <> 'agent_message'
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),

    Metric(
        key="atoms_touched_30d_share",
        label="Savoir retouché sur 30 jours",
        unit="%",
        definition=(
            "Part des souvenirs vivants qui ont été relus, corrigés ou confirmés "
            "au cours des trente derniers jours."
        ),
        formula="100 x actifs(updated_at >= maintenant - 30 jours) / actifs hors transport",
        domain="memoire",
        window="30d",
        sql="""
            SELECT round(
                       100.0 * count(*) FILTER (WHERE updated_at >= now() - interval '30 days')
                       / nullif(count(*), 0), 1) AS value
              FROM arac.memory_atoms
             WHERE status = 'active' AND kind <> 'agent_message'
        """,
        evidence_label="La semaine de dernière retouche de chaque atome vivant",
        evidence_sql="""
            SELECT date_trunc('week', updated_at)::date AS semaine_derniere_retouche,
                   count(*) AS atomes,
                   count(*) FILTER (WHERE updated_at >= now() - interval '30 days')
                     AS dans_la_fenetre_30j,
                   count(DISTINCT scope) AS scopes_concernes
              FROM arac.memory_atoms
             WHERE status = 'active' AND kind <> 'agent_message'
             GROUP BY 1
             ORDER BY 1 DESC
             LIMIT 30
        """,
    ),

    Metric(
        key="verification_coverage",
        # Même correction que dans la famille « confiance » : la garde
        # mesure « aucun atome vivant n'en porte », pas « la totalité ».
        unavailable_reason=("mécanisme non alimenté : aucun atome vivant ne porte "
                            "de last_verified_at — aucun agent de ce dépôt ne "
                            "l'écrit"),
        unavailable_gesture="aucun geste connu — le mécanisme de re-vérification n'a jamais tourné",
        substitute="l'âge des atomes (atoms_median_age_days) et le taux de remplacement",
        label="Savoir vérifié au moins une fois",
        unit="%",
        definition=(
            "Part des souvenirs vivants qui portent une date de dernière "
            "vérification : sans elle, rien ne distingue un fait relu d'un fait oublié."
        ),
        formula="100 x actifs(last_verified_at renseigne) / actifs hors transport",
        domain="memoire",
        window="instant",
        sql="""
            SELECT CASE WHEN count(*) FILTER (WHERE last_verified_at IS NOT NULL) = 0
                   THEN NULL::numeric ELSE round(
                       100.0 * count(*) FILTER (WHERE last_verified_at IS NOT NULL)
                       / nullif(count(*), 0), 1) END AS value
              FROM arac.memory_atoms
             WHERE status = 'active' AND kind <> 'agent_message'
        """,
        evidence_label="Le savoir vivant selon qu'il porte ou non une trace de vérification",
        evidence_sql="""
            SELECT CASE
                     WHEN last_verified_at IS NULL THEN 'aucune trace de verification'
                     WHEN last_verified_at >= now() - interval '90 days'
                       THEN 'verifie dans les 90 jours'
                     ELSE 'verifie il y a plus de 90 jours'
                   END AS etat_verification,
                   count(*) AS atomes,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS part_pct,
                   max(last_verified_at) AS derniere_verification
              FROM arac.memory_atoms
             WHERE status = 'active' AND kind <> 'agent_message'
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),

    Metric(
        key="expiry_horizon_coverage",
        unavailable_reason=("mécanisme non alimenté : aucun atome vivant ne porte "
                            "de confirmed_until — le cerveau n'a aucune notion de "
                            "péremption"),
        unavailable_gesture="aucun geste connu — aucun horizon de validité n'est jamais posé",
        substitute="l'âge médian du savoir",
        label="Savoir doté d'une date de péremption",
        unit="%",
        definition=(
            "Part des souvenirs vivants qui déclarent jusqu'à quand ils sont "
            "réputés valides : sans horizon, un fait périmé reste rappelable indéfiniment."
        ),
        formula="100 x actifs(confirmed_until renseigne) / actifs hors transport",
        domain="memoire",
        window="instant",
        sql="""
            SELECT CASE WHEN count(*) FILTER (WHERE confirmed_until IS NOT NULL) = 0
                   THEN NULL::numeric ELSE round(
                       100.0 * count(*) FILTER (WHERE confirmed_until IS NOT NULL)
                       / nullif(count(*), 0), 1) END AS value
              FROM arac.memory_atoms
             WHERE status = 'active' AND kind <> 'agent_message'
        """,
        evidence_label="Le savoir vivant réparti entre sans horizon, périmé, et encore valide",
        evidence_sql="""
            SELECT CASE
                     WHEN confirmed_until IS NULL THEN 'sans horizon de validite'
                     WHEN confirmed_until < now() THEN 'horizon depasse'
                     ELSE 'encore sous garantie'
                   END AS etat_peremption,
                   count(*) AS atomes,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS part_pct,
                   min(confirmed_until) AS echeance_la_plus_proche
              FROM arac.memory_atoms
             WHERE status = 'active' AND kind <> 'agent_message'
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),

    # ------------------------------------------------------------ obsolescence
    Metric(
        key="supersession_rate",
        label="Taux de remplacement",
        unit="%",
        definition=(
            "Part du savoir produit qui a fini remplacé par une version plus "
            "récente : c'est le rythme auquel le cerveau se corrige lui-même."
        ),
        formula="100 x atomes(status = 'superseded') / atomes hors transport, tous statuts",
        domain="memoire",
        window="all",
        sql="""
            SELECT round(
                       100.0 * count(*) FILTER (WHERE status = 'superseded')
                       / nullif(count(*), 0), 2) AS value
              FROM arac.memory_atoms
             WHERE kind <> 'agent_message'
        """,
        evidence_label="Les atomes remplacés, du plus récent au plus ancien, avec leur remplaçant",
        evidence_sql="""
            SELECT a.scope,
                   a.kind,
                   a.key,
                   a.version,
                   a.updated_at AS remplace_le,
                   a.superseded_by AS remplace_par,
                   (r.id IS NOT NULL) AS remplacant_retrouve,
                   r.status AS statut_du_remplacant
              FROM arac.memory_atoms a
              LEFT JOIN arac.memory_atoms r ON r.id = a.superseded_by
             WHERE a.status = 'superseded'
             ORDER BY a.updated_at DESC
             LIMIT 200
        """,
    ),

    Metric(
        key="archived_knowledge",
        label="Savoir mis de côté",
        unit="atomes",
        definition=(
            "Atomes de savoir archivés hors messages de bus : ils existent encore "
            "mais ne sont plus rappelables."
        ),
        formula="count(atomes WHERE status = 'archived' AND kind <> 'agent_message')",
        domain="memoire",
        window="all",
        sql="""
            SELECT count(*) AS value
              FROM arac.memory_atoms
             WHERE status = 'archived' AND kind <> 'agent_message'
        """,
        evidence_label="Chaque atome de savoir archivé, avec sa date de mise à l'écart",
        evidence_sql="""
            SELECT scope, kind, key, confidence, created_at, updated_at AS archive_le
              FROM arac.memory_atoms
             WHERE status = 'archived' AND kind <> 'agent_message'
             ORDER BY updated_at DESC
             LIMIT 200
        """,
    ),

    Metric(
        key="bus_messages_total",
        label="Messages de bus (transport)",
        unit="atomes",
        definition=(
            "Messages échangés entre nœuds stockés dans la table des atomes : "
            "c'est du transport, jamais du savoir, et aucune métrique de savoir ne les compte."
        ),
        formula="count(atomes WHERE kind = 'agent_message')",
        domain="memoire",
        window="all",
        sql="""
            SELECT count(*) AS value
              FROM arac.memory_atoms
             WHERE kind = 'agent_message'
        """,
        evidence_label="Le transport par nœud émetteur et par statut, avec sa période d'activité",
        evidence_sql="""
            SELECT node_id,
                   status,
                   count(*) AS messages,
                   min(created_at) AS premier,
                   max(created_at) AS dernier
              FROM arac.memory_atoms
             WHERE kind = 'agent_message'
             GROUP BY node_id, status
             ORDER BY 3 DESC
             LIMIT 100
        """,
    ),

    # ----------------------------------------------------- carte du savoir
    Metric(
        key="populated_scopes",
        label="Territoires de savoir peuplés",
        unit="scopes",
        definition=(
            "Nombre de scopes distincts qui abritent au moins un souvenir vivant : "
            "c'est l'étendue réelle de la carte du savoir."
        ),
        formula="count(DISTINCT scope) sur les actifs hors transport",
        domain="memoire",
        window="instant",
        sql="""
            SELECT count(DISTINCT scope) AS value
              FROM arac.memory_atoms
             WHERE status = 'active' AND kind <> 'agent_message'
        """,
        evidence_label="Chaque territoire peuplé, et s'il est connu du registre des projets",
        evidence_sql="""
            SELECT a.scope,
                   count(*) AS atomes_actifs,
                   (a.scope NOT LIKE '%/%') AS racine_non_rappelable,
                   (p.scope IS NOT NULL) AS present_au_registre_projets,
                   max(p.member_count) AS effectif_declare_au_registre
              FROM arac.memory_atoms a
              LEFT JOIN arac.project_registry p ON p.scope = a.scope
             WHERE a.status = 'active' AND a.kind <> 'agent_message'
             GROUP BY a.scope, p.scope
             ORDER BY 2 DESC
        """,
    ),

    Metric(
        key="scope_density_median",
        label="Densité médiane par territoire",
        unit="atomes",
        definition=(
            "Nombre d'atomes vivants du territoire médian : la moitié des scopes "
            "en contient moins, l'autre moitié davantage."
        ),
        formula="mediane(count(actifs) GROUP BY scope)",
        domain="memoire",
        window="instant",
        sql="""
            WITH densite AS (
                SELECT scope, count(*) AS atomes
                  FROM arac.memory_atoms
                 WHERE status = 'active' AND kind <> 'agent_message'
                 GROUP BY scope
            )
            SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY atomes)::numeric, 1) AS value
              FROM densite
        """,
        evidence_label="La densité de chaque territoire, du plus dense au plus vide",
        evidence_sql="""
            SELECT scope,
                   count(*) AS atomes_actifs,
                   count(DISTINCT kind) AS natures_distinctes,
                   min(created_at) AS premier,
                   max(created_at) AS dernier
              FROM arac.memory_atoms
             WHERE status = 'active' AND kind <> 'agent_message'
             GROUP BY scope
             ORDER BY 2 DESC
        """,
    ),

    Metric(
        key="repr_coverage",
        label="Savoir doté d'une représentation dérivée",
        unit="%",
        definition=(
            "Part des souvenirs vivants qui possèdent une représentation "
            "construite : sans elle, un atome reste invisible au rappel sémantique."
        ),
        formula="100 x actifs ayant au moins une entree memory_atom_reprs / actifs hors transport",
        domain="memoire",
        window="instant",
        sql="""
            SELECT round(
                       100.0 * count(*) FILTER (
                           WHERE EXISTS (
                               SELECT 1 FROM arac.memory_atom_reprs r WHERE r.atom_id = a.id
                           )
                       ) / nullif(count(*), 0), 1) AS value
              FROM arac.memory_atoms a
             WHERE a.status = 'active' AND a.kind <> 'agent_message'
        """,
        evidence_label="Le savoir vivant par version de représentation, dont la part sans aucune",
        evidence_sql="""
            SELECT coalesce(r.repr_version, 'aucune representation construite') AS representation,
                   count(*) AS atomes,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS part_pct,
                   min(r.created_at) AS premiere_construction,
                   max(r.created_at) AS derniere_construction
              FROM arac.memory_atoms a
              LEFT JOIN arac.memory_atom_reprs r ON r.atom_id = a.id
             WHERE a.status = 'active' AND a.kind <> 'agent_message'
             GROUP BY 1
             ORDER BY 2 DESC
        """,
    ),
)
