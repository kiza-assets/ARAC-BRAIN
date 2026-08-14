"""Famille « confiance » — OÙ LE CERVEAU DOUTE (READ-ONLY strict).

Les autres familles répondent à « qu'est-ce que le cerveau sait ? ». Celle-ci
répond à la seule question qui compte quand on doit AGIR sur ce savoir :

    « À quel endroit précis est-ce que je ne peux pas lui faire confiance ? »

Un cockpit qui n'affiche que des compteurs en hausse rend le doute invisible.
Or le doute est la partie utile : c'est lui qui indique où relire, où arbitrer,
où le cerveau va se tromper si personne n'intervient. Cette famille cartographie
donc les zones d'ombre — par score, par territoire, par projet, par nature.

QUATRE PARTIS PRIS, tous vérifiables dans le SQL ci-dessous.

1. **Un doute a une adresse.** Aucune métrique ne se contente d'un pourcentage
   global : chaque preuve nomme le scope, le projet ou l'atome concerné, pour
   qu'on puisse ouvrir la fiche et corriger. Un chiffre qu'on ne peut pas suivre
   jusqu'à un objet ne produit aucune action.

2. **Une absence de mesure n'est jamais une bonne note.** Deux métriques de
   cette famille rendent délibérément ``NULL`` — donc ``unavailable`` motivé —
   parce que le mécanisme qu'elles mesurent n'est alimenté par aucun agent :
   ``last_verified_at`` et ``confirmed_until`` sont NULL sur la totalité du
   corpus. Afficher « 0 % vérifié » laisserait croire à une mesure ; afficher
   « mécanisme non alimenté » dit la vérité. La bascule est faite EN SQL, sur
   l'état réel de la colonne : le jour où un agent alimentera le champ, la
   métrique se mettra à mesurer toute seule, sans qu'on rouvre ce fichier.

3. **Un zéro mesuré reste un zéro affiché.** ``decisions_without_rationale``
   vaut réellement 0 : les 340 décisions vivantes portent toutes leur
   justification. Ce n'est pas une absence de mesure, c'est une bonne nouvelle
   vérifiable — et la preuve montre les 15 autres natures où le rationnel manque
   massivement, pour qu'on ne confonde pas les deux situations.

4. **L'arithmétique est en SQL.** Médianes, déciles, moyennes par territoire,
   distances sémantiques : PostgreSQL calcule, le BFF transporte, le navigateur
   affiche. Chaque requête est rejouable telle quelle dans ``psql``.

RAPPELS DU SOCLE, appliqués sans exception ici :

- ``agent_message`` est du TRANSPORT entre nœuds, jamais du savoir : exclu partout.
- Seul ``status = 'active'`` est rappelable : c'est le seul corpus qu'on juge.
- Un atome posé sur un scope RACINE (sans « / ») est invisible au rappel. Il
  compte dans le savoir et ne compte pas dans ce que le cerveau retrouvera.

CE QUI N'EST PAS ICI, ET POURQUOI. Les contradictions entre atomes seraient la
mesure de doute la plus précieuse. Elles sont absentes de cette famille parce
qu'aucun mécanisme n'en produit : 0 atome ``kind = 'contradiction'``,
``arac.atom_links`` non lue par cette famille, ``audit_links``
et ``audit_feedback`` vides. Une métrique « contradictions » afficherait 0, et ce
0 se lirait comme « aucun conflit détecté » alors qu'il signifie « aucune
détection n'existe ». Le substitut honnête est ``semantic_duplicates`` : deux
atomes quasi identiques SANS lignée commune sont le seul indice de conflit que
la base sait produire aujourd'hui.

LECTURE SEULE : aucune instruction mutante, invariant vérifié à l'instanciation
par ``Metric.__post_init__`` et par ``tests/test_cc_v1_registry.py``.
"""

from __future__ import annotations

from control_center.cc_v1.families.projets import _PROJETS_CTE
from control_center.cc_v1.metric import Metric

__all__ = ["METRICS", "FRAGILE_BELOW", "DUPLICATE_DISTANCE"]


#: Sous ce score, un atome est dit **fragile** : le producteur lui-même n'y
#: croyait qu'à moitié. Le seuil vaut 70 parce que c'est le décrochage réel de la
#: distribution observée (médiane 90, premier décile 75) : en dessous, on quitte
#: la masse du corpus.
FRAGILE_BELOW = 70

#: Distance cosinus en dessous de laquelle deux atomes disent probablement la
#: même chose. 0.10 est volontairement SERRÉ : on cherche les doublons francs,
#: pas la parenté thématique. Le voisinage large est déjà servi par la fiche
#: d'atome (``/cc/v1/atoms/{id}``), avec sa propre distance affichée.
DUPLICATE_DISTANCE = 0.10

#: Les quatre natures qui portent un fait réutilisable. Un territoire qui n'en
#: possède pas au moins deux n'est pas un territoire de savoir : c'est un tiroir.
#: Même définition que la famille ``memoire`` — elle est normative (SPEC §7).
_STRUCTURANTS = "'gotcha', 'decision', 'state', 'pattern'"

#: Le corpus jugeable, écrit une seule fois. Toute métrique de cette famille en
#: dérive : si le filtre changeait ici sans changer là, deux métriques de doute
#: se contrediraient — et une mesure de confiance qui se contredit ne vaut rien.
_VIVANT = "status = 'active' AND kind <> 'agent_message'"

#: Le même filtre, qualifié par un alias, pour les requêtes à plusieurs tables.
#: Il existe parce qu'un filtre à moitié qualifié (``a.status = … AND kind = …``)
#: devient AMBIGU dès qu'une seconde table entre dans la requête : PostgreSQL
#: refuse, ou pire, résout sur la mauvaise table. Une seule définition, deux
#: rendus — jamais deux définitions.
_VIVANT_A = "a.status = 'active' AND a.kind <> 'agent_message'"


METRICS: tuple[Metric, ...] = (

    # ========================================================================
    # 1. LA DISTRIBUTION — de quoi le cerveau est-il sûr, globalement ?
    # ========================================================================

    Metric(
        key="confidence_median",
        label="Confiance médiane",
        unit="/100",
        definition=(
            "Score de confiance de l'atome vivant du milieu : la moitié du savoir "
            "rappelable est jugée moins sûre que cette valeur."
        ),
        formula="mediane(confidence_score) sur les actifs notés, hors transport",
        domain="confiance",
        window="instant",
        target={"warn": 80, "critical": 70, "direction": "up"},
        sql=f"""
            SELECT round(
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY confidence_score)::numeric,
                       0) AS value
              FROM arac.memory_atoms
             WHERE {_VIVANT} AND confidence_score IS NOT NULL
        """,
        evidence_label="La distribution complète, par tranche de score, avec les déciles",
        evidence_sql=f"""
            SELECT CASE
                     WHEN confidence_score IS NULL THEN 'sans score'
                     WHEN confidence_score < 60  THEN 'moins de 60'
                     WHEN confidence_score < 70  THEN '60 a 69'
                     WHEN confidence_score < 80  THEN '70 a 79'
                     WHEN confidence_score < 90  THEN '80 a 89'
                     ELSE '90 et plus'
                   END                                                       AS tranche,
                   count(*)                                                  AS atomes,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1)        AS part_pct,
                   min(confidence_score)                                     AS score_min,
                   max(confidence_score)                                     AS score_max,
                   count(DISTINCT scope)                                     AS territoires
              FROM arac.memory_atoms
             WHERE {_VIVANT}
             GROUP BY 1
             ORDER BY min(coalesce(confidence_score, -1))
        """,
    ),

    Metric(
        key="fragile_atoms_total",
        label="Atomes fragiles",
        unit="atomes",
        definition=(
            f"Souvenirs vivants dont le score de confiance est inferieur a "
            f"{FRAGILE_BELOW} : le cerveau les servira malgre son propre doute."
        ),
        formula=f"count(actifs WHERE confidence_score < {FRAGILE_BELOW})",
        domain="confiance",
        window="instant",
        target={"warn": 100, "critical": 200, "direction": "down"},
        sql=f"""
            SELECT count(*) AS value
              FROM arac.memory_atoms
             WHERE {_VIVANT} AND confidence_score < {FRAGILE_BELOW}
        """,
        evidence_label="Les atomes fragiles, du moins sûr au moins récent",
        evidence_sql=f"""
            SELECT id, scope, kind, key, confidence_score, confidence,
                   (rationale IS NOT NULL AND btrim(rationale) <> '') AS justifie,
                   created_at, updated_at
              FROM arac.memory_atoms
             WHERE {_VIVANT} AND confidence_score < {FRAGILE_BELOW}
             ORDER BY confidence_score ASC, created_at DESC
             LIMIT 200
        """,
    ),

    Metric(
        key="fragile_knowledge_share",
        label="Part fragile du corpus",
        unit="%",
        definition=(
            f"Part du savoir NOTE dont la confiance est inferieure a "
            f"{FRAGILE_BELOW} : le poids reel du doute dans ce qui est rappelable."
        ),
        formula=(
            f"100 x actifs(confidence_score < {FRAGILE_BELOW}) / actifs portant un score"
        ),
        domain="confiance",
        window="instant",
        target={"warn": 10, "critical": 20, "direction": "down"},
        sql=f"""
            SELECT round(
                       100.0 * count(*) FILTER (WHERE confidence_score < {FRAGILE_BELOW})
                       / nullif(count(*) FILTER (WHERE confidence_score IS NOT NULL), 0),
                       1) AS value,
                   /* Le dénominateur est SERVI : le compte (107) porte sur les
                      atomes vivants, la part (7 %) sur les seuls atomes NOTÉS.
                      Sans ce detail, appliquer 7 % au total donnait 120, pas 107.
                      Commentaire de BLOC : ce SQL est servi aplati sur une ligne
                      (règle 9), un commentaire de ligne masquerait la suite. */
                   count(*) FILTER (WHERE confidence_score IS NOT NULL)::text
                     || ' atomes notés sur ' || count(*)::text || ' vivants' AS detail
              FROM arac.memory_atoms
             WHERE {_VIVANT}
        """,
        evidence_label="La part fragile territoire par territoire, la plus lourde d'abord",
        evidence_sql=f"""
            SELECT scope,
                   count(*)                                              AS atomes,
                   count(confidence_score)                               AS notes,
                   count(*) FILTER (WHERE confidence_score < {FRAGILE_BELOW}) AS fragiles,
                   round(100.0 * count(*) FILTER (WHERE confidence_score < {FRAGILE_BELOW})
                         / nullif(count(confidence_score), 0), 1)        AS part_fragile_pct,
                   round(avg(confidence_score)::numeric, 1)              AS confiance_moyenne
              FROM arac.memory_atoms
             WHERE {_VIVANT}
             GROUP BY scope
             ORDER BY 5 DESC NULLS LAST, 4 DESC
        """,
    ),

    Metric(
        key="atoms_without_confidence_score",
        label="Savoir sans score chiffré",
        unit="%",
        definition=(
            "Part des souvenirs vivants qui ne portent aucun score de confiance : "
            "on ne sait ni s'en méfier ni s'y fier."
        ),
        formula="100 x actifs(confidence_score IS NULL) / actifs hors transport",
        domain="confiance",
        window="instant",
        target={"warn": 10, "critical": 25, "direction": "down"},
        sql=f"""
            SELECT round(
                       100.0 * count(*) FILTER (WHERE confidence_score IS NULL)
                       / nullif(count(*), 0), 1) AS value
              FROM arac.memory_atoms
             WHERE {_VIVANT}
        """,
        evidence_label="Qui produit du savoir non noté : par nature d'atome et par nœud",
        evidence_sql=f"""
            SELECT kind, node_id,
                   count(*)                                              AS atomes,
                   count(*) FILTER (WHERE confidence_score IS NULL)       AS sans_score,
                   round(100.0 * count(*) FILTER (WHERE confidence_score IS NULL)
                         / nullif(count(*), 0), 1)                        AS part_pct,
                   max(created_at) FILTER (WHERE confidence_score IS NULL) AS dernier_sans_score
              FROM arac.memory_atoms
             WHERE {_VIVANT}
             GROUP BY kind, node_id
            HAVING count(*) FILTER (WHERE confidence_score IS NULL) > 0
             ORDER BY 4 DESC
        """,
    ),

    # ========================================================================
    # 2. LE DOUTE A UNE ADRESSE — territoires et projets
    # ========================================================================

    Metric(
        key="least_confident_scope",
        label="Territoire le moins sûr",
        unit="/100",
        definition=(
            "Confiance moyenne du territoire le plus faible parmi ceux qui "
            "comptent au moins cinq atomes notés ; son nom est servi en détail."
        ),
        formula="min(avg(confidence_score) par scope) sur les scopes ayant >= 5 atomes notés",
        domain="confiance",
        window="instant",
        target={"warn": 80, "critical": 70, "direction": "up"},
        sql=f"""
            WITH par_scope AS (
                SELECT scope,
                       round(avg(confidence_score)::numeric, 1) AS moyenne,
                       count(*) AS notes
                  FROM arac.memory_atoms
                 WHERE {_VIVANT} AND confidence_score IS NOT NULL
                 GROUP BY scope
                HAVING count(*) >= 5
            )
            SELECT moyenne AS value, scope AS detail
              FROM par_scope
             ORDER BY moyenne ASC, scope ASC
             LIMIT 1
        """,
        evidence_label="Le classement des territoires par confiance moyenne, le plus fragile en tête",
        evidence_sql=f"""
            SELECT scope,
                   count(*)                                              AS atomes,
                   count(confidence_score)                               AS notes,
                   round(avg(confidence_score)::numeric, 1)              AS confiance_moyenne,
                   min(confidence_score)                                 AS minimum,
                   round((percentile_cont(0.25) WITHIN GROUP (ORDER BY confidence_score))::numeric, 0)
                                                                          AS premier_quartile,
                   count(*) FILTER (WHERE confidence_score < {FRAGILE_BELOW}) AS fragiles,
                   (count(confidence_score) >= 5)                         AS retenu_pour_le_classement
              FROM arac.memory_atoms
             WHERE {_VIVANT}
             GROUP BY scope
             ORDER BY 4 ASC NULLS LAST, 2 DESC
        """,
    ),

    Metric(
        key="incomplete_scopes_total",
        label="Territoires indigents",
        unit="scopes",
        definition=(
            "Territoires peuplés mais trop maigres pour être utiles : moins de "
            "cinq atomes, ou moins de deux natures structurantes sur quatre."
        ),
        formula=(
            "count(scopes WHERE atomes < 5 OR natures structurantes distinctes < 2), "
            "structurantes = gotcha, decision, state, pattern"
        ),
        domain="confiance",
        window="instant",
        target={"warn": 8, "critical": 15, "direction": "down"},
        sql=f"""
            WITH par_scope AS (
                SELECT scope,
                       count(*) AS atomes,
                       count(DISTINCT kind) FILTER (WHERE kind IN ({_STRUCTURANTS}))
                           AS natures_structurantes
                  FROM arac.memory_atoms
                 WHERE {_VIVANT}
                 GROUP BY scope
            )
            SELECT count(*) AS value
              FROM par_scope
             WHERE atomes < 5 OR natures_structurantes < 2
        """,
        evidence_label="Chaque territoire indigent, ce qu'il contient et ce qui lui manque",
        evidence_sql=f"""
            SELECT scope,
                   count(*)                                                   AS atomes,
                   count(DISTINCT kind) FILTER (WHERE kind IN ({_STRUCTURANTS}))
                                                                              AS natures_structurantes,
                   count(DISTINCT kind)                                       AS natures_total,
                   string_agg(DISTINCT kind, ', ' ORDER BY kind)              AS natures_presentes,
                   round(avg(confidence_score)::numeric, 1)                   AS confiance_moyenne,
                   (scope NOT LIKE '%/%')                                     AS scope_racine,
                   max(created_at)                                            AS dernier_atome
              FROM arac.memory_atoms
             WHERE {_VIVANT}
             GROUP BY scope
            HAVING count(*) < 5
                OR count(DISTINCT kind) FILTER (WHERE kind IN ({_STRUCTURANTS})) < 2
             ORDER BY 2 ASC, 1
        """,
    ),

    Metric(
        key="least_confident_project",
        label="Projet le moins sûr",
        unit="/100",
        definition=(
            "Confiance moyenne du projet le plus faible parmi les vues de projet "
            "transverses ; son nom est servi en détail."
        ),
        formula="min(avg(confidence_score) par projet) sur les projets ayant >= 5 atomes notés",
        domain="confiance",
        window="instant",
        target={"warn": 85, "critical": 75, "direction": "up"},
        sql=_PROJETS_CTE + """
            SELECT round(avg(m.confidence_score)::numeric, 1) AS value,
                   m.projet                                   AS detail
              FROM membres m
             GROUP BY m.projet
            HAVING count(m.confidence_score) >= 5
             ORDER BY 1 ASC, 2 ASC
             LIMIT 1
        """,
        evidence_label="Les projets, leur confiance moyenne et leur part fragile",
        evidence_sql=_PROJETS_CTE + f"""
            SELECT m.projet,
                   count(*)                                              AS atomes,
                   count(m.confidence_score)                             AS notes,
                   round(avg(m.confidence_score)::numeric, 1)            AS confiance_moyenne,
                   min(m.confidence_score)                               AS minimum,
                   count(*) FILTER (WHERE m.confidence_score < {FRAGILE_BELOW}) AS fragiles,
                   count(*) FILTER (WHERE m.confidence_score IS NULL)    AS sans_score,
                   count(DISTINCT m.scope)                               AS territoires
              FROM membres m
             GROUP BY m.projet
             ORDER BY 4 ASC NULLS FIRST
        """,
    ),

    Metric(
        key="never_recalled_scopes_total",
        label="Territoires jamais rappelés",
        unit="scopes",
        definition=(
            "Territoires peuplés dont AUCUN atome n'est jamais remonté dans un "
            "contexte servi : du savoir écrit que le cerveau n'a jamais relu."
        ),
        formula="count(scopes WHERE aucun atome actif présent dans context_receipts.served_ids)",
        domain="confiance",
        window="all",
        target={"warn": 3, "critical": 8, "direction": "down"},
        sql=f"""
            WITH servis AS (
                SELECT DISTINCT s AS atom_id
                  FROM arac.context_receipts cr
                  CROSS JOIN LATERAL unnest(cr.served_ids) s
            ),
            par_scope AS (
                SELECT a.scope,
                       count(*) AS atomes,
                       count(*) FILTER (WHERE sv.atom_id IS NULL) AS dormants
                  FROM arac.memory_atoms a
                  LEFT JOIN servis sv ON sv.atom_id = a.id
                 WHERE {_VIVANT_A}
                 GROUP BY a.scope
            )
            SELECT count(*) AS value
              FROM par_scope
             WHERE dormants = atomes
        """,
        evidence_label="La part dormante de chaque territoire, du plus muet au plus rappelé",
        evidence_sql=f"""
            WITH servis AS (
                SELECT DISTINCT s AS atom_id
                  FROM arac.context_receipts cr
                  CROSS JOIN LATERAL unnest(cr.served_ids) s
            )
            SELECT a.scope,
                   count(*)                                              AS atomes,
                   count(*) FILTER (WHERE sv.atom_id IS NULL)            AS dormants,
                   round(100.0 * count(*) FILTER (WHERE sv.atom_id IS NULL)
                         / nullif(count(*), 0), 1)                       AS part_dormante_pct,
                   (count(*) FILTER (WHERE sv.atom_id IS NULL) = count(*)) AS jamais_rappele,
                   (a.scope NOT LIKE '%/%')                              AS scope_racine,
                   round(avg(a.confidence_score)::numeric, 1)            AS confiance_moyenne
              FROM arac.memory_atoms a
              LEFT JOIN servis sv ON sv.atom_id = a.id
             WHERE {_VIVANT_A}
             GROUP BY a.scope
             ORDER BY 4 DESC, 2 DESC
        """,
    ),

    Metric(
        key="root_level_invisible_share",
        label="Savoir invisible au rappel",
        unit="%",
        definition=(
            "Part des souvenirs vivants posés sur un scope RACINE : ils existent "
            "en base et ne remontent jamais dans un contexte servi."
        ),
        formula="100 x actifs(scope sans '/') / actifs hors transport",
        domain="confiance",
        window="instant",
        target={"warn": 5, "critical": 10, "direction": "down"},
        sql=f"""
            SELECT round(
                       100.0 * count(*) FILTER (WHERE scope NOT LIKE '%/%')
                       / nullif(count(*), 0), 1) AS value
              FROM arac.memory_atoms
             WHERE {_VIVANT}
        """,
        evidence_label="Chaque racine, le savoir qu'elle séquestre, et depuis quand",
        evidence_sql=f"""
            SELECT scope                                                 AS racine,
                   count(*)                                              AS atomes_invisibles,
                   count(DISTINCT kind)                                  AS natures,
                   round(avg(confidence_score)::numeric, 1)              AS confiance_moyenne,
                   min(created_at)                                       AS plus_ancien,
                   max(created_at)                                       AS plus_recent,
                   count(DISTINCT source_ref->>'conversation_uid')       AS conversations_sources
              FROM arac.memory_atoms
             WHERE {_VIVANT} AND scope NOT LIKE '%/%'
             GROUP BY scope
             ORDER BY 2 DESC
        """,
    ),

    # ========================================================================
    # 3. LA QUALITÉ DU DOSSIER — audit, justification, doublons
    # ========================================================================

    Metric(
        key="unaudited_knowledge_share",
        label="Savoir jamais audité",
        unit="%",
        definition=(
            "Part des souvenirs vivants qui ne portent aucune trace d'audit : "
            "personne, humain ni agent, n'a jamais relu ce que le producteur a écrit."
        ),
        formula="100 x actifs(audit_source IS NULL ou vide) / actifs hors transport",
        domain="confiance",
        window="instant",
        target={"warn": 50, "critical": 90, "direction": "down"},
        sql=f"""
            SELECT round(
                       100.0 * count(*) FILTER (
                           WHERE audit_source IS NULL OR btrim(audit_source) = '')
                       / nullif(count(*), 0), 1) AS value
              FROM arac.memory_atoms
             WHERE {_VIVANT}
        """,
        evidence_label="Les sources d'audit réellement présentes, et le niveau de confiance associé",
        evidence_sql=f"""
            SELECT coalesce(nullif(btrim(audit_source), ''), 'aucun audit') AS source_audit,
                   confidence                                            AS niveau_declare,
                   count(*)                                              AS atomes,
                   round(100.0 * count(*) / sum(count(*)) OVER (), 1)    AS part_pct,
                   round(avg(confidence_score)::numeric, 1)              AS score_moyen,
                   max(created_at)                                       AS dernier
              FROM arac.memory_atoms
             WHERE {_VIVANT}
             GROUP BY 1, 2
             ORDER BY 3 DESC
        """,
    ),

    Metric(
        key="decisions_without_rationale",
        label="Décisions sans justification",
        unit="atomes",
        definition=(
            "Décisions vivantes qui ne disent pas POURQUOI elles ont été prises : "
            "une décision sans rationnel ne peut être ni rejouée ni contestée."
        ),
        formula="count(actifs WHERE kind = 'decision' AND rationale vide ou absent)",
        domain="confiance",
        window="instant",
        target={"warn": 1, "critical": 10, "direction": "down"},
        sql=f"""
            SELECT count(*) AS value
              FROM arac.memory_atoms
             WHERE {_VIVANT}
               AND kind = 'decision'
               AND (rationale IS NULL OR btrim(rationale) = '')
        """,
        evidence_label="La couverture du rationnel par nature d'atome, et celle qui l'exige",
        evidence_sql=f"""
            SELECT kind                                                  AS nature,
                   (kind = 'decision')                                   AS rationnel_exige,
                   count(*)                                              AS atomes,
                   count(*) FILTER (WHERE rationale IS NULL OR btrim(rationale) = '')
                                                                          AS sans_rationnel,
                   round(100.0 * count(*) FILTER (
                             WHERE rationale IS NOT NULL AND btrim(rationale) <> '')
                         / nullif(count(*), 0), 1)                        AS couverture_pct,
                   round(avg(confidence_score)::numeric, 1)              AS confiance_moyenne
              FROM arac.memory_atoms
             WHERE {_VIVANT}
             GROUP BY kind
             ORDER BY 2 DESC, 4 DESC
        """,
    ),

    Metric(
        key="semantic_duplicates",
        label="Doublons potentiels",
        unit="atomes",
        definition=(
            f"Souvenirs vivants dont le plus proche voisin sémantique est a moins "
            f"de {DUPLICATE_DISTANCE} de distance SANS partager de lignee : deux "
            f"versions d'un meme fait que rien ne relie."
        ),
        formula=(
            f"count(actifs dont la distance cosinus au plus proche voisin non apparente "
            f"< {DUPLICATE_DISTANCE}), lignee = supersedes / superseded_by"
        ),
        domain="confiance",
        window="instant",
        target={"warn": 60, "critical": 150, "direction": "down"},
        sql=f"""
            SELECT count(*) AS value
              FROM arac.memory_atoms a
              CROSS JOIN LATERAL (
                  SELECT (a.embedding <=> b.embedding) AS distance
                    FROM arac.memory_atoms b
                   WHERE b.id <> a.id
                     AND b.status = 'active'
                     AND b.kind <> 'agent_message'
                     AND b.id IS DISTINCT FROM a.supersedes
                     AND b.id IS DISTINCT FROM a.superseded_by
                     AND b.supersedes IS DISTINCT FROM a.id
                     AND b.superseded_by IS DISTINCT FROM a.id
                   ORDER BY b.embedding <=> a.embedding
                   LIMIT 1
              ) voisin
             WHERE {_VIVANT_A}
               AND a.embedding IS NOT NULL
               AND voisin.distance < {DUPLICATE_DISTANCE}
        """,
        evidence_label="Chaque paire quasi identique, sa distance, et si elle traverse deux territoires",
        evidence_sql=f"""
            SELECT round(voisin.distance::numeric, 4)                    AS distance,
                   a.id                                                  AS atome_id,
                   a.scope                                               AS atome_scope,
                   a.kind                                                AS atome_nature,
                   a.key                                                 AS atome_cle,
                   voisin.jumeau_id,
                   voisin.jumeau_scope,
                   voisin.jumeau_cle,
                   (a.scope <> voisin.jumeau_scope)                      AS territoires_differents,
                   a.confidence_score                                    AS score_atome,
                   voisin.jumeau_score
              FROM arac.memory_atoms a
              CROSS JOIN LATERAL (
                  SELECT (a.embedding <=> b.embedding) AS distance,
                         b.id AS jumeau_id, b.scope AS jumeau_scope, b.key AS jumeau_cle,
                         b.confidence_score AS jumeau_score
                    FROM arac.memory_atoms b
                   WHERE b.id <> a.id
                     AND b.status = 'active'
                     AND b.kind <> 'agent_message'
                     AND b.id IS DISTINCT FROM a.supersedes
                     AND b.id IS DISTINCT FROM a.superseded_by
                     AND b.supersedes IS DISTINCT FROM a.id
                     AND b.superseded_by IS DISTINCT FROM a.id
                   ORDER BY b.embedding <=> a.embedding
                   LIMIT 1
              ) voisin
             WHERE {_VIVANT_A}
               AND a.embedding IS NOT NULL
               AND voisin.distance < {DUPLICATE_DISTANCE}
             ORDER BY 1 ASC
             LIMIT 200
        """,
    ),

    # ========================================================================
    # 4. LES DEUX ABSENCES ASSUMÉES — mécanismes non alimentés
    # ========================================================================
    #
    # Ces deux métriques rendent NULL, donc `unavailable` avec sa raison. Ni 0
    # (« rien n'est vérifié » se lirait comme une mesure), ni 100 (mensonge).
    # La bascule est faite EN SQL sur l'état réel de la colonne : le jour où un
    # agent alimentera le champ, elles se mettront à mesurer sans qu'on rouvre
    # ce fichier. Une absence qui se répare toute seule vaut mieux qu'une
    # constante en dur qu'il faudra penser à retirer.

    Metric(
        key="confidence_verification_coverage",
        # POURQUOI pas de compte ici : `unavailable_reason` est du TEXTE servi à
        # l'écran, pas une mesure. Un chiffre écrit ici serait celui du cerveau
        # sur lequel il a été relevé — donc faux chez tout autre lecteur. Le
        # compte réel, lui, existe déjà : le `detail` du SQL ci-dessous le
        # calcule (`|| total ||`) sur la base qu'on interroge. La raison énonce
        # le MÉCANISME, le SQL énonce la mesure.
        # « NULL sur la totalité des atomes » n'est servi que lorsque le
        # compte des atomes vérifiés vaut zéro — c'est donc constaté. Mais la
        # formule reste bancale sur un cerveau NEUF, où il n'y a aucun atome :
        # « la totalité » de rien. On dit ce que la garde a réellement mesuré.
        unavailable_reason=("mécanisme non alimenté : aucun agent n'écrit "
                            "last_verified_at, et aucun atome vivant n'en porte"),
        unavailable_gesture="aucun geste connu — aucune re-vérification n'a jamais été enregistrée",
        substitute="l'âge des atomes et leur taux de remplacement",
        label="Couverture de vérification",
        unit="%",
        definition=(
            "Part du savoir vivant relu depuis sa création — non mesurable tant "
            "qu'aucun agent n'écrit last_verified_at."
        ),
        formula="100 x actifs(last_verified_at IS NOT NULL) / actifs — NULL si la colonne n'est jamais alimentée",
        domain="confiance",
        window="instant",
        sql=f"""
            WITH t AS (
                SELECT count(*) AS total,
                       count(*) FILTER (WHERE last_verified_at IS NOT NULL) AS verifies
                  FROM arac.memory_atoms
                 WHERE {_VIVANT}
            )
            SELECT CASE WHEN verifies = 0 THEN NULL::numeric
                        ELSE round(100.0 * verifies / nullif(total, 0), 1) END AS value,
                   CASE WHEN verifies = 0
                        THEN 'mecanisme non alimente : last_verified_at est NULL sur les '
                             || total || ' atomes vivants'
                        ELSE NULL END AS detail
              FROM t
        """,
        evidence_label="L'état réel de la colonne, le geste qui la remplirait, et le substitut",
        evidence_sql=f"""
            SELECT 'arac.memory_atoms.last_verified_at'                  AS colonne,
                   count(*)                                              AS atomes_vivants,
                   count(last_verified_at)                               AS atomes_renseignes,
                   'aucun agent n''ecrit cette colonne'                  AS raison,
                   'alimenter last_verified_at a la curation et a l''audit' AS geste,
                   'audit_source + confidence_score comme substituts partiels' AS substitut
              FROM arac.memory_atoms
             WHERE {_VIVANT}
             LIMIT 1
        """,
    ),

    Metric(
        key="confidence_expiry_horizon",
        # Même règle qu'au-dessus : la raison dit le mécanisme absent, jamais un
        # compte relevé ailleurs. Le compte vivant est produit par le `detail` du SQL.
        unavailable_reason=("mécanisme non alimenté : aucun agent n'écrit "
                            "confirmed_until, et aucun atome vivant n'en porte"),
        unavailable_gesture="aucun geste connu — le cerveau n'a aucune notion de péremption",
        substitute="l'âge médian du savoir",
        label="Horizon de péremption",
        unit="%",
        definition=(
            "Part du savoir vivant qui déclare jusqu'à quand il reste valide — "
            "non mesurable tant qu'aucun agent n'écrit confirmed_until."
        ),
        formula="100 x actifs(confirmed_until IS NOT NULL) / actifs — NULL si la colonne n'est jamais alimentée",
        domain="confiance",
        window="instant",
        sql=f"""
            WITH t AS (
                SELECT count(*) AS total,
                       count(*) FILTER (WHERE confirmed_until IS NOT NULL) AS avec_horizon
                  FROM arac.memory_atoms
                 WHERE {_VIVANT}
            )
            SELECT CASE WHEN avec_horizon = 0 THEN NULL::numeric
                        ELSE round(100.0 * avec_horizon / nullif(total, 0), 1) END AS value,
                   CASE WHEN avec_horizon = 0
                        THEN 'mecanisme non alimente : confirmed_until est NULL sur les '
                             || total || ' atomes vivants'
                        ELSE NULL END AS detail
              FROM t
        """,
        evidence_label="L'état réel de la colonne, le geste qui la remplirait, et le substitut",
        evidence_sql=f"""
            SELECT 'arac.memory_atoms.confirmed_until'                   AS colonne,
                   count(*)                                              AS atomes_vivants,
                   count(confirmed_until)                                AS atomes_renseignes,
                   'aucun agent n''ecrit cette colonne'                  AS raison,
                   'poser un horizon de validite a la curation'          AS geste,
                   'age median du savoir (memoire) comme substitut partiel' AS substitut
              FROM arac.memory_atoms
             WHERE {_VIVANT}
             LIMIT 1
        """,
    ),
)
