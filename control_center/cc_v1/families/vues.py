"""Famille « atomes » — LES COMPTEURS DES VUES (priorité 4 du cockpit V2).

Une vue n'est pas un filtre d'affichage : c'est une **question posée au savoir**.

    « Qu'est-ce que le cerveau vient d'apprendre ? »        → nouveaux (24 h)
    « Qu'est-ce qu'il a corrigé ? »                          → enrichis / fusionnés
    « Qu'est-ce qu'il retient sans jamais s'en servir ? »    → jamais rappelés
    « Sur quoi s'appuie-t-il vraiment ? »                    → porteurs
    « Qu'est-ce qu'il range sans que ça serve un projet ? »  → orphelins de projet
    « Qu'est-ce qu'il a rangé là où il ne le retrouvera pas ? » → dette root-level
    « Qu'est-ce qu'il affirme sans dire pourquoi ? »         → sans justification
    « Qu'est-ce qui ne doit jamais être perdu ? »            → pierres angulaires

Chaque métrique de cette famille compte les atomes de SA coupe, et sert en preuve
les **premiers éléments de la coupe** — pas un agrégat. C'est la différence entre
un compteur et une vue : la preuve d'une vue doit être la liste que la vue ouvre,
sinon le chiffre et l'écran racontent deux histoires.

CE QUI N'EST PAS MESURABLE — ET QUI EST DÉCLARÉ QUAND MÊME
----------------------------------------------------------
Deux vues attendues du cockpit n'ont pas de source en base :

``view_graph_orphans``  « atomes orphelins » au sens du GRAPHE (aucun lien entrant
                        ni sortant). ``arac.atom_links`` n'est pas lue par
                        cette vue ; sa raison est constatée en base.
``view_contradictory``  « atomes contradictoires ». Aucun mécanisme n'en produit :
                        rien n'écrit d'atome ``kind = 'contradiction'``, ni de
                        ligne dans ``audit_links`` / ``audit_feedback``.

Elles rendent ``NULL`` — donc ``unavailable`` avec leur raison, leur geste de
déblocage et leur substitut. **Jamais zéro.** « 0 atome contradictoire » se lirait
comme une bonne nouvelle alors que c'est une absence de détection : c'est
exactement la faute d'affichage à ne pas commettre sur ce produit. Leur preuve ne
récite pas la panne, elle la **constate en base** au moment où on l'ouvre
(``to_regclass``, comptes réels).

COHÉRENCE AVEC LE RESTE DU REGISTRE
-----------------------------------
Trois vues recouvrent une métrique déjà servie ailleurs. Elles réutilisent le
MÊME SQL — jamais une variante — pour qu'aucun écran ne puisse contredire un
autre :

``view_project_orphans``  partage le CTE des projets avec ``projects_uncovered_atoms``
                          (548 atomes le 2026-08-04) ;
``view_never_recalled``   même coupe que ``dormant_knowledge`` (759) ;
``view_root_debt``        même coupe que ``root_level_debt``, à ceci près qu'elle
                          exclut ``agent_message`` — la vue ouvre du SAVOIR, pas
                          du transport. L'écart entre les deux chiffres est donc
                          exactement le nombre de messages d'agents posés sur une
                          racine ; il vaut 0 le 2026-08-04 (157 = 157), et la
                          preuve porte la colonne qui permet de le vérifier
                          plutôt que de le croire.

CONVENTIONS DU SOCLE, appliquées sans exception
-----------------------------------------------
- ``agent_message`` est du TRANSPORT entre nœuds, jamais du savoir : exclu partout.
- Seul ``status = 'active'`` est rappelable ; les vues « fusionnés » et
  « enrichis » sont les seules à regarder au-delà, parce que leur objet EST la
  trace d'un remplacement.
- Un atome posé sur un scope RACINE (sans « / ») est invisible au rappel.
- Toute l'arithmétique est en SQL. Aucune requête n'est paramétrée : elles sont
  rejouables telles quelles dans ``psql``, motifs ``LIKE '%/%'`` compris.

LECTURE SEULE : aucune instruction mutante, invariant vérifié à l'instanciation
par ``Metric.__post_init__`` et par ``tests/test_cc_v1_registry.py``.
"""

from __future__ import annotations

from control_center.cc_v1.families.projets import _PROJETS_CTE
from control_center.cc_v1.metric import Metric

__all__ = ["METRICS", "DOMAIN", "VIEWS", "RATIONALE_REQUIRED", "CORNERSTONE_TAG"]

#: Domaine d'interface propriétaire de cette famille (SPEC §7).
DOMAIN = "atomes"

#: Le corpus rappelable, écrit une seule fois. Toute vue qui parle du savoir
#: vivant en dérive : si le filtre changeait ici sans changer là, deux vues du
#: même écran se contrediraient.
_VIVANT = "a.status = 'active' AND a.kind <> 'agent_message'"

#: Les natures qui **affirment un jugement** : elles devraient dire POURQUOI.
#: Une décision, un piège, un motif, une intuition, une validation ou un abandon
#: sans rationnel ne peut être ni rejoué, ni contesté, ni transmis.
#: Constat du 2026-08-04 : seule ``decision`` porte réellement son rationnel
#: (340/340). Les cinq autres en sont dépourvues à plus de 95 %. La preuve montre
#: la couverture NATURE PAR NATURE, pour qu'on lise le mécanisme et pas un total.
RATIONALE_REQUIRED = "'decision', 'gotcha', 'pattern', 'insight', 'validation', 'killed'"

#: Le tag qui marque un savoir que le cerveau ne doit jamais perdre. Il est POSÉ
#: À LA MAIN : sa rareté est le signal. 12 atomes le portent le 2026-08-04.
CORNERSTONE_TAG = "pierre-angulaire"

#: UN RAPPEL, UNE LIGNE — le prédicat de dédoublonnage des reçus.
#:
#: CE QUI ÉTAIT FAUX (mesuré le 2026-08-05, hors constats fournis) : cinq lectures
#: de cette famille comptaient les LIGNES de ``arac.context_receipts`` pour dire
#: combien de fois un atome a été rappelé. Depuis FOLD V2 chaque rappel réel
#: en écrit DEUX — le moteur SERVI (``ce-shadow-r3pur-v1``) puis le moteur d'ombre
#: v2-fold, même ``request_id``, mêmes ``served_ids``. Tout compte d'usage était
#: donc doublé : la fiche d'un atome (``entities.py``, déjà corrigée) annonçait 111
#: rappels là où la preuve de ces vues en affichait 222 pour le MÊME atome — deux
#: écrans du même cockpit, deux vérités.
#:
#: L'effet ne se limitait pas à l'affichage : ``view_load_bearing`` servait 85
#: atomes porteurs au lieu de 87, parce que le doublement n'est PAS uniforme
#: (1 631 rappels sur 1 709 ont un jumeau v2, 78 n'en ont pas) et déplace donc le
#: classement au seuil des 50 %.
#:
#: CE QUE CETTE VERSION GARANTIT : on retient le PREMIER reçu écrit de chaque
#: ``request_id``, c'est-à-dire le chemin SERVI (« prod, bit-identique — vérité de
#: référence », commentaire de colonne en base). Le prédicat reste juste le jour où
#: un moteur v3 écrira un troisième reçu, là où un filtre sur ``engine_version``
#: devrait être réécrit.
#:
#: Commentaire de BLOC : ce SQL est servi aplati sur UNE ligne (règle 9 — un ``--``
#: y masquerait tout ce qui suit). Aucun ``%`` : rien ici n'est paramétré.
_PREMIER_RECU = (
    "/* un rappel = un request_id ; le premier reçu écrit est le chemin servi */\n"
    "                       NOT EXISTS (SELECT 1 FROM arac.context_receipts p\n"
    "                                    WHERE p.request_id = cr.request_id AND p.id < cr.id)")

#: À coller dans un WHERE qui existe déjà…
_UN_RECU_PAR_RAPPEL = f"\n                   AND {_PREMIER_RECU}"

#: …et à coller quand la lecture n'a pas encore de WHERE.
_UN_RECU_PAR_RAPPEL_SEUL = f"\n                 WHERE {_PREMIER_RECU}"

#: Les vues déclarées, dans l'ordre d'affichage attendu. Servi tel quel par
#: l'interface : la liste des vues est une donnée du serveur, pas du navigateur.
VIEWS: tuple[tuple[str, str, str], ...] = (
    ("view_new_24h", "Nouveaux", "/cc/v1/atoms?view=recent"),
    ("view_enriched", "Enrichis", "/cc/v1/atoms?view=enriched"),
    ("view_merged", "Fusionnés", "/cc/v1/atoms?status=superseded"),
    ("view_never_recalled", "Jamais rappelés", "/cc/v1/atoms?view=dormant"),
    ("view_recalled_7d", "Récemment rappelés", "/cc/v1/atoms?view=recalled"),
    ("view_load_bearing", "Les plus utilisés", "/cc/v1/atoms?view=served"),
    ("view_project_orphans", "Orphelins de projet", "/cc/v1/atoms?view=unprojected"),
    ("view_root_debt", "Dette root-level", "/cc/v1/atoms?view=root"),
    ("view_missing_rationale", "Sans justification", "/cc/v1/atoms?view=no-rationale"),
    ("view_cornerstone", "Pierres angulaires", "/cc/v1/atoms?view=cornerstone"),
    ("view_graph_orphans", "Orphelins du graphe", None),
    ("view_contradictory", "Contradictoires", None),
)


METRICS: tuple[Metric, ...] = (

    # ======================================================== CE QUI VIENT D'ARRIVER
    Metric(
        key="view_new_24h",
        label="Nouveaux",
        unit="atomes",
        definition=(
            "Souvenirs nés dans les dernières 24 heures : ce que le cerveau vient "
            "d'apprendre, et rien d'autre."
        ),
        formula="count(actifs, hors agent_message, WHERE created_at > now() - 24h)",
        domain=DOMAIN,
        window="24h",
        sql=f"""
            SELECT count(*) AS value
              FROM arac.memory_atoms a
             WHERE {_VIVANT}
               AND a.created_at > now() - interval '24 hours'
        """,
        evidence_label="Les atomes nés dans les 24 dernières heures, du plus récent au plus ancien",
        evidence_sql=f"""
            SELECT a.id,
                   a.kind,
                   a.scope,
                   a.key,
                   a.confidence_score,
                   a.created_at,
                   a.source_ref->>'conversation_uid' AS conversation_uid,
                   a.source_ref->>'run_ref'          AS cycle,
                   (a.scope NOT LIKE '%/%')          AS invisible_au_rappel,
                   '/cc/v1/atoms/' || a.id::text || '/story' AS histoire
              FROM arac.memory_atoms a
             WHERE {_VIVANT}
               AND a.created_at > now() - interval '24 hours'
             ORDER BY a.created_at DESC
             LIMIT 200
        """,
    ),

    # ============================================================ CE QUI A ÉTÉ REVU
    Metric(
        key="view_enriched",
        label="Enrichis",
        unit="atomes",
        definition=(
            "Souvenirs vivants retouchés depuis leur naissance : version supérieure "
            "à 1, ou contenu modifié après création."
        ),
        formula="count(actifs WHERE version > 1 OU updated_at > created_at + 1s)",
        domain=DOMAIN,
        window="all",
        sql=f"""
            SELECT count(*) AS value
              FROM arac.memory_atoms a
             WHERE {_VIVANT}
               AND (a.version > 1 OR a.updated_at > a.created_at + interval '1 second')
        """,
        evidence_label="Les atomes retouchés, du plus récemment modifié au plus ancien",
        evidence_sql=f"""
            SELECT a.id,
                   a.kind,
                   a.scope,
                   a.key,
                   a.version,
                   a.created_at,
                   a.updated_at,
                   (a.updated_at > a.created_at + interval '1 second') AS retouche_sur_place,
                   (a.version > 1)                                     AS nouvelle_version,
                   a.supersedes,
                   '/cc/v1/atoms/' || a.id::text || '/story' AS histoire
              FROM arac.memory_atoms a
             WHERE {_VIVANT}
               AND (a.version > 1 OR a.updated_at > a.created_at + interval '1 second')
             ORDER BY a.updated_at DESC
             LIMIT 200
        """,
    ),
    Metric(
        key="view_merged",
        label="Fusionnés",
        unit="atomes",
        definition=(
            "Souvenirs remplacés par une version plus juste : la seule trace de "
            "conflit que le cerveau enregistre réellement."
        ),
        formula="count(memory_atoms WHERE status = 'superseded')",
        domain=DOMAIN,
        window="all",
        sql="""
            SELECT count(*) AS value
              FROM arac.memory_atoms a
             WHERE a.status = 'superseded'
        """,
        evidence_label="Les atomes remplacés, avec le successeur qui les a supplantés",
        evidence_sql="""
            SELECT a.id,
                   a.kind,
                   a.scope,
                   a.key,
                   a.version,
                   a.created_at                          AS ne_le,
                   a.updated_at                          AS remplace_le,
                   a.superseded_by                       AS successeur,
                   s.version                             AS version_successeur,
                   s.status                              AS statut_successeur,
                   (length(s.value) - length(a.value))   AS delta_caracteres,
                   '/cc/v1/atoms/' || a.id::text || '/story' AS histoire
              FROM arac.memory_atoms a
              LEFT JOIN arac.memory_atoms s ON s.id = a.superseded_by
             WHERE a.status = 'superseded'
             ORDER BY a.updated_at DESC
             LIMIT 200
        """,
    ),

    # =================================================== CE QUI SERT — ET CE QUI DORT
    Metric(
        key="view_never_recalled",
        label="Jamais rappelés",
        unit="atomes",
        definition=(
            "Souvenirs vivants qu'aucun contexte servi n'a jamais remontés : du "
            "savoir retenu que le cerveau n'a jamais utilisé."
        ),
        formula="count(actifs absents de tous les context_receipts.served_ids)",
        domain=DOMAIN,
        window="all",
        target={"warn": 600, "critical": 900, "direction": "down"},
        sql=f"""
            WITH servis AS (
                SELECT DISTINCT unnest(served_ids)::uuid AS id FROM arac.context_receipts
            )
            SELECT count(*) AS value
              FROM arac.memory_atoms a
             WHERE {_VIVANT}
               AND NOT EXISTS (SELECT 1 FROM servis s WHERE s.id = a.id)
        """,
        evidence_label="Les atomes dormants, du plus ancien au plus récent",
        evidence_sql=f"""
            WITH servis AS (
                SELECT DISTINCT unnest(served_ids)::uuid AS id FROM arac.context_receipts
            )
            SELECT a.id,
                   a.kind,
                   a.scope,
                   a.key,
                   a.confidence_score,
                   a.created_at,
                   (now() - a.created_at)            AS dort_depuis,
                   (a.scope NOT LIKE '%/%')          AS invisible_au_rappel,
                   (a.embedding IS NULL)             AS sans_plongement,
                   '/cc/v1/atoms/' || a.id::text || '/story' AS histoire
              FROM arac.memory_atoms a
             WHERE {_VIVANT}
               AND NOT EXISTS (SELECT 1 FROM servis s WHERE s.id = a.id)
             ORDER BY a.created_at
             LIMIT 200
        """,
    ),
    Metric(
        key="view_recalled_7d",
        label="Récemment rappelés",
        unit="atomes",
        definition=(
            "Souvenirs vivants remontés dans au moins un contexte servi ces sept "
            "derniers jours : le savoir que le cerveau a réellement mobilisé."
        ),
        formula="count(DISTINCT actifs présents dans served_ids des reçus de 7 jours)",
        domain=DOMAIN,
        window="7d",
        sql=f"""
            WITH servis AS (
                SELECT DISTINCT unnest(served_ids)::uuid AS id
                  FROM arac.context_receipts
                 WHERE created_at > now() - interval '7 days'
            )
            SELECT count(*) AS value
              FROM arac.memory_atoms a
             WHERE {_VIVANT}
               AND EXISTS (SELECT 1 FROM servis s WHERE s.id = a.id)
        """,
        evidence_label="Les atomes mobilisés cette semaine, du plus sollicité au moins sollicité",
        evidence_sql=f"""
            WITH rappels AS (
                SELECT s.id, count(*) AS rappels_7j, max(cr.created_at) AS dernier_rappel
                  FROM arac.context_receipts cr, unnest(cr.served_ids) AS s(id)
                 WHERE cr.created_at > now() - interval '7 days'{_UN_RECU_PAR_RAPPEL}
                 GROUP BY s.id
            )
            SELECT a.id,
                   a.kind,
                   a.scope,
                   a.key,
                   r.rappels_7j,
                   r.dernier_rappel,
                   a.confidence_score,
                   '/cc/v1/atoms/' || a.id::text || '/story' AS histoire
              FROM arac.memory_atoms a
              JOIN rappels r ON r.id = a.id
             WHERE {_VIVANT}
             ORDER BY r.rappels_7j DESC, r.dernier_rappel DESC
             LIMIT 200
        """,
    ),
    Metric(
        key="view_load_bearing",
        label="Les plus utilisés",
        unit="atomes",
        definition=(
            "Le plus petit groupe d'atomes vivants qui porte à lui seul la moitié "
            "des rappels servis sur du savoir encore vivant."
        ),
        # La formule ne cite plus de volume chiffré : les deux nombres qui y étaient
        # gravés (26 147 / 26 160) étaient des CONSTANTES d'un jour, et de surcroît
        # des comptes de LIGNES de reçus, donc le double des rappels réels. Le
        # volume qui fait foi est celui que la preuve calcule, colonne
        # `volume_total`, à l'instant où on l'ouvre.
        formula=(
            "atomes vivants classés par rappels décroissants, comptés jusqu'à ce que "
            "leur cumul atteigne 50 % du volume de rappels PORTANT SUR EUX, "
            "et non du volume total tous atomes confondus"
        ),
        domain=DOMAIN,
        window="all",
        sql=f"""
            WITH rappels AS (
                SELECT s.id, count(*) AS rappels
                  FROM arac.context_receipts cr, unnest(cr.served_ids) AS s(id){_UN_RECU_PAR_RAPPEL_SEUL}
                 GROUP BY s.id
            ), vivants AS (
                SELECT a.id, r.rappels
                  FROM arac.memory_atoms a
                  JOIN rappels r ON r.id = a.id
                 WHERE {_VIVANT}
            ), classement AS (
                SELECT id,
                       rappels,
                       sum(rappels) OVER (ORDER BY rappels DESC, id) AS cumul,
                       sum(rappels) OVER ()                          AS volume_total
                  FROM vivants
            )
            SELECT count(*) AS value
              FROM classement
             WHERE cumul - rappels < volume_total / 2.0
        """,
        evidence_label="Les atomes porteurs, avec leur part cumulée du volume de rappel",
        evidence_sql=f"""
            WITH rappels AS (
                SELECT s.id, count(*) AS rappels, max(cr.created_at) AS dernier_rappel
                  FROM arac.context_receipts cr, unnest(cr.served_ids) AS s(id){_UN_RECU_PAR_RAPPEL_SEUL}
                 GROUP BY s.id
            ), vivants AS (
                SELECT a.id, a.kind, a.scope, a.key, a.confidence_score,
                       r.rappels, r.dernier_rappel
                  FROM arac.memory_atoms a
                  JOIN rappels r ON r.id = a.id
                 WHERE {_VIVANT}
            ), classement AS (
                SELECT v.*,
                       row_number() OVER (ORDER BY rappels DESC, id)  AS rang,
                       sum(rappels) OVER (ORDER BY rappels DESC, id)  AS cumul,
                       sum(rappels) OVER ()                           AS volume_total
                  FROM vivants v
            )
            SELECT rang,
                   id,
                   kind,
                   scope,
                   key,
                   rappels,
                   dernier_rappel,
                   confidence_score,
                   round(100.0 * cumul / volume_total, 1) AS part_cumulee_pct,
                   '/cc/v1/atoms/' || id::text || '/story' AS histoire
              FROM classement
             WHERE cumul - rappels < volume_total / 2.0
             ORDER BY rang
             LIMIT 200
        """,
    ),

    # ================================================ CE QUI EST MAL RANGÉ OU ISOLÉ
    Metric(
        key="view_project_orphans",
        label="Orphelins de projet",
        unit="atomes",
        definition=(
            "Souvenirs vivants qu'aucune règle de projet ne réclame : du "
            "savoir rangé qu'aucune intention ne vient chercher."
        ),
        formula="savoir vivant MOINS l'union des huit vues de projet (mêmes règles que projets_uncovered_atoms)",
        domain=DOMAIN,
        window="instant",
        target={"warn": 400, "critical": 600, "direction": "down"},
        sql=_PROJETS_CTE + """
            SELECT count(*) AS value
              FROM savoir s
             WHERE NOT EXISTS (SELECT 1 FROM membres m WHERE m.id = s.id)
        """,
        evidence_label="Les atomes qu'aucun projet ne réclame, groupés par scope puis listés",
        evidence_sql=_PROJETS_CTE + """
            SELECT s.id,
                   s.kind,
                   s.scope,
                   s.key,
                   s.confidence_score,
                   s.created_at,
                   (s.scope NOT LIKE '%/%') AS invisible_au_rappel,
                   '/cc/v1/atoms/' || s.id::text || '/story' AS histoire
              FROM savoir s
             WHERE NOT EXISTS (SELECT 1 FROM membres m WHERE m.id = s.id)
             ORDER BY s.scope, s.created_at DESC
             LIMIT 200
        """,
    ),
    Metric(
        key="view_root_debt",
        label="Dette root-level",
        unit="atomes",
        definition=(
            "Savoir vivant posé sur un scope RACINE, sans « / » : il existe en base "
            "et reste invisible au rappel."
        ),
        formula="count(actifs, hors agent_message, WHERE scope ne contient pas '/')",
        domain=DOMAIN,
        window="instant",
        target={"warn": 118, "critical": 140, "direction": "down"},
        sql=f"""
            SELECT count(*) AS value
              FROM arac.memory_atoms a
             WHERE {_VIVANT}
               AND a.scope NOT LIKE '%/%'
        """,
        evidence_label="Les atomes invisibles au rappel, du plus rappelable au plus perdu",
        evidence_sql=f"""
            WITH rappels AS (
                SELECT s.id, count(*) AS rappels
                  FROM arac.context_receipts cr, unnest(cr.served_ids) AS s(id){_UN_RECU_PAR_RAPPEL_SEUL}
                 GROUP BY s.id
            )
            SELECT a.id,
                   a.kind,
                   a.scope                                AS racine,
                   a.key,
                   a.confidence_score,
                   a.created_at,
                   coalesce(r.rappels, 0)                 AS rappels,
                   (a.kind = 'agent_message')             AS transport_et_non_savoir,
                   '/cc/v1/atoms/' || a.id::text || '/story' AS histoire
              FROM arac.memory_atoms a
              LEFT JOIN rappels r ON r.id = a.id
             WHERE a.status = 'active'
               AND a.scope NOT LIKE '%/%'
             ORDER BY a.kind = 'agent_message', coalesce(r.rappels, 0) DESC, a.created_at DESC
             LIMIT 200
        """,
    ),
    Metric(
        key="view_missing_rationale",
        label="Sans justification",
        unit="atomes",
        definition=(
            "Souvenirs vivants qui AFFIRMENT un jugement sans dire pourquoi : ils ne "
            "peuvent être ni rejoués, ni contestés, ni transmis."
        ),
        formula=(
            "count(actifs WHERE kind ∈ {decision, gotcha, pattern, insight, validation, killed} "
            "ET rationale vide ou absent)"
        ),
        domain=DOMAIN,
        window="instant",
        target={"warn": 300, "critical": 600, "direction": "down"},
        sql=f"""
            SELECT count(*) AS value
              FROM arac.memory_atoms a
             WHERE {_VIVANT}
               AND a.kind IN ({RATIONALE_REQUIRED})
               AND coalesce(btrim(a.rationale), '') = ''
        """,
        evidence_label=(
            "La couverture du rationnel NATURE PAR NATURE, puis les atomes concernés"
        ),
        evidence_sql=f"""
            SELECT a.kind,
                   count(*)                                                      AS atomes,
                   count(*) FILTER (WHERE coalesce(btrim(a.rationale), '') = '') AS sans_justification,
                   round(100.0 * count(*) FILTER (WHERE coalesce(btrim(a.rationale), '') <> '')
                         / nullif(count(*), 0), 1)                               AS couverture_pct,
                   (a.kind IN ({RATIONALE_REQUIRED}))                            AS nature_qui_lexige,
                   min(a.created_at)                                             AS plus_ancien,
                   max(a.created_at)                                             AS plus_recent
              FROM arac.memory_atoms a
             WHERE {_VIVANT}
             GROUP BY a.kind
             ORDER BY (a.kind IN ({RATIONALE_REQUIRED})) DESC,
                      count(*) FILTER (WHERE coalesce(btrim(a.rationale), '') = '') DESC
        """,
    ),
    Metric(
        key="view_cornerstone",
        label="Pierres angulaires",
        unit="atomes",
        definition=(
            "Souvenirs vivants marqués « pierre-angulaire » : le savoir que vous "
            "avez désigné comme irremplaçable."
        ),
        formula="count(actifs WHERE 'pierre-angulaire' ∈ tags)",
        domain=DOMAIN,
        window="instant",
        sql=f"""
            SELECT count(*) AS value
              FROM arac.memory_atoms a
             WHERE {_VIVANT}
               AND a.tags && ARRAY['{CORNERSTONE_TAG}']
        """,
        evidence_label="Les pierres angulaires, et l'usage réel que le cerveau en fait",
        evidence_sql=f"""
            WITH rappels AS (
                SELECT s.id, count(*) AS rappels, max(cr.created_at) AS dernier_rappel
                  FROM arac.context_receipts cr, unnest(cr.served_ids) AS s(id){_UN_RECU_PAR_RAPPEL_SEUL}
                 GROUP BY s.id
            )
            SELECT a.id,
                   a.kind,
                   a.scope,
                   a.key,
                   a.confidence_score,
                   a.created_at,
                   coalesce(r.rappels, 0)   AS rappels,
                   r.dernier_rappel,
                   (r.id IS NULL)           AS jamais_rappelee,
                   (a.scope NOT LIKE '%/%') AS invisible_au_rappel,
                   '/cc/v1/atoms/' || a.id::text || '/story' AS histoire
              FROM arac.memory_atoms a
              LEFT JOIN rappels r ON r.id = a.id
             WHERE {_VIVANT}
               AND a.tags && ARRAY['{CORNERSTONE_TAG}']
             ORDER BY coalesce(r.rappels, 0) DESC, a.created_at DESC
             LIMIT 200
        """,
    ),

    # ============================== LES DEUX VUES QUI N'ONT PAS DE SOURCE — ET LE DISENT
    Metric(
        key="view_graph_orphans",
        label="Orphelins du graphe",
        unit="atomes",
        definition=(
            "Atomes sans aucun lien entrant ni sortant — non mesurable : cette vue "
            "ne lit pas la table des liens."
        ),
        formula="indisponible : cette vue ne lit pas arac.atom_links",
        domain=DOMAIN,
        window="instant",
        # Repli seulement : la raison servie est celle que la requête CONSTATE.
        unavailable_reason="aucun degré de liaison n'est calculé par cette vue",
        unavailable_gesture="branchez cette vue sur arac.atom_links",
        substitute=(
            "la vue « jamais rappelés » (view_never_recalled) et le voisinage sémantique "
            "servi par /cc/v1/atoms/{id}/story"
        ),
        sql="""
            SELECT NULL::numeric AS value,
                   CASE WHEN to_regclass('arac.atom_links') IS NULL
                        THEN 'table arac.atom_links absente : aucun degré à compter, et surtout pas zéro'
                        ELSE 'table arac.atom_links présente : cette vue ne lit pas encore ses degrés'
                        END AS detail,
                   CASE WHEN to_regclass('arac.atom_links') IS NULL
                        THEN 'la table arac.atom_links est absente du schéma : aucun degré '
                             || 'de liaison n''est calculable'
                        ELSE 'la table arac.atom_links est déployée, mais cette vue ne lit '
                             || 'pas encore ses degrés'
                        END AS reason,
                   CASE WHEN to_regclass('arac.atom_links') IS NULL
                        THEN 'appliquez les migrations en attente : alembic upgrade head'
                        ELSE 'branchez cette vue sur arac.atom_links'
                        END AS gesture
        """,
        evidence_label="L'état de la dépendance, constaté en base à l'instant où on l'ouvre",
        evidence_sql="""
            SELECT 'arac.atom_links'                                                  AS dependance,
                   (to_regclass('arac.atom_links') IS NOT NULL)                       AS deployee_maintenant,
                   to_regclass('arac.atom_links')::text                               AS resolue_en,
                   'vue jamais rappeles + voisinage semantique'                       AS substitut,
                   (SELECT count(*) FROM arac.memory_atoms
                     WHERE status = 'active' AND kind <> 'agent_message')             AS atomes_concernes,
                   now()                                                              AS constate_a
             LIMIT 1
        """,
    ),
    Metric(
        key="view_contradictory",
        label="Contradictoires",
        unit="atomes",
        definition=(
            "Atomes en contradiction les uns avec les autres — non mesurable : aucun "
            "mécanisme n'en produit."
        ),
        formula="indisponible : aucun producteur n'écrit de contradiction (ni atome, ni ligne d'audit)",
        domain=DOMAIN,
        window="instant",
        # La raison énonce le MÉCANISME absent, jamais un compte. Un « 0 atome »
        # écrit ici est le compte de la base sur laquelle il a été relevé : servi
        # à un autre lecteur, il annonce le corpus de quelqu'un d'autre. Le compte
        # réel est produit par la preuve, qui interroge les trois sources en base.
        unavailable_reason=(
            "aucun producteur de contradiction : rien n'écrit d'atome "
            "kind='contradiction', ni de ligne dans arac.audit_links / arac.audit_feedback"
        ),
        unavailable_gesture=(
            "brancher un detecteur qui ecrive soit un atome kind='contradiction', "
            "soit une ligne dans arac.audit_links / arac.audit_feedback"
        ),
        substitute=(
            "la vue « fusionnés » (view_merged) : la supersession est le seul conflit "
            "que la base enregistre réellement"
        ),
        sql="""
            SELECT NULL::numeric AS value,
                   'aucun mecanisme ne produit de contradiction : un zero se lirait comme une bonne nouvelle' AS detail
        """,
        evidence_label="Les trois sources possibles d'une contradiction, comptées en base maintenant",
        evidence_sql="""
            SELECT source,
                   lignes,
                   (lignes = 0)                                              AS source_vide,
                   'aucun mecanisme n''alimente cette source'                 AS raison,
                   'brancher un detecteur de contradiction'                   AS geste,
                   'la supersession (view_merged), seul conflit enregistre'   AS substitut
              FROM (
                    SELECT 'arac.memory_atoms kind=contradiction' AS source,
                           count(*) AS lignes
                      FROM arac.memory_atoms WHERE kind = 'contradiction'
                     UNION ALL
                    SELECT 'arac.audit_links',    count(*) FROM arac.audit_links
                     UNION ALL
                    SELECT 'arac.audit_feedback', count(*) FROM arac.audit_feedback
              ) s
             GROUP BY source, lignes
             ORDER BY source
        """,
    ),
)
