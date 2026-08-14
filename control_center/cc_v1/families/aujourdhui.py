"""Famille « aujourd'hui » — le DELTA du jour, pas l'état du cerveau.

Le reste du registre décrit un ÉTAT : combien d'atomes, quelle couverture, quelle
santé. Cette famille-ci décrit un MOUVEMENT : ce que le cerveau a appris, enrichi,
remplacé, absorbé, dépensé et raté **depuis une fenêtre glissante**. C'est la seule
famille dont la question n'est pas « où en est-on ? » mais « que s'est-il passé ? ».

## POURQUOI UNE FAMILLE PARAMÉTRÉE PAR SA FENÊTRE

Le registre exige un SQL **littéral** par métrique — c'est ce qui rend chaque chiffre
rejouable dans ``psql``. Mais la vue « Aujourd'hui » doit pouvoir basculer en 7 j et
30 j sans que la formule change : deux formules pour un même libellé, et le cockpit
recommence à mentir.

D'où le compromis retenu : chaque mesure est déclarée UNE fois sous forme de ``Spec``
portant un gabarit SQL dont la seule variable est l'intervalle. ``METRICS`` — ce que
lit le registre — est la projection de ces ``Spec`` sur la fenêtre canonique de 24 h,
donc du SQL littéral, contrôlable et rejouable. ``control_center/cc_v1/today.py``
projette les MÊMES ``Spec`` sur 7 j et 30 j. Une formule, trois fenêtres, aucune
duplication : si la définition de « atome enrichi » change, elle change partout.

## CE QUE CETTE FAMILLE REFUSE DE MESURER

Trois mesures sont attendues de cette vue et **n'existent pas en base** :

| Clé                    | Dépendance manquante                                    |
|------------------------|---------------------------------------------------------|
| ``today_links_created``| ``arac.atom_links`` — non lue par ce panneau          |
| ``today_contradictions``| aucun producteur : 0 atome ``kind='contradiction'``    |
| ``today_regressions``  | le score NRB n'est pas persisté en base (fichier JSON)  |

Elles sont déclarées quand même, et rendent ``NULL`` — donc ``unavailable`` avec sa
raison. **Jamais zéro.** « +0 contradiction aujourd'hui » se lirait comme une bonne
nouvelle alors que c'est une absence de mesure : c'est précisément l'erreur
d'affichage la plus coûteuse de ce produit, celle qui transforme une panne en
satisfecit. Leur preuve ne récite pas la panne, elle la **vérifie en base** au moment
où on l'ouvre (``to_regclass``, comptes réels), avec le geste qui la débloquerait et
le substitut retenu en attendant.

## CONVENTIONS

- ``agent_message`` est du TRANSPORT, jamais du savoir : il est exclu de tout compte
  d'atome. Un cerveau qui compterait ses accusés de réception comme des souvenirs
  se déclarerait en pleine forme le jour où il n'apprend plus rien.
- **Les preuves restent peuplées même quand le delta vaut 0.** Elles montrent
  l'historique récent avec une colonne ``dans_la_fenetre`` : une journée sans
  supersession doit pouvoir se distinguer d'un mécanisme de supersession mort.
  Une preuve vide ne prouve rien — surtout pas une absence.
- **La preuve dit sa propre troncature.** Une preuve ligne à ligne porte un
  ``LIMIT`` : sur 30 jours, ``today_atoms_created`` affirmait 383 quand la preuve
  n'exposait que 58 lignes marquées (``LIMIT 60``), sans qu'aucune colonne ne le
  signale — le lecteur qui comptait les lignes marquées, comme le libellé l'y
  invite, tombait sur un autre chiffre que la valeur. Ces preuves servent donc une
  colonne ``total_fenetre``, calculée par une fonction de fenêtrage — donc AVANT
  le ``LIMIT``, sur l'ensemble du résultat — qui vaut exactement la valeur servie.
  Elle est CONSTANTE sur toutes les lignes : on la lit, on ne l'additionne pas.
- Toute l'arithmétique est en SQL, division du coût par atome comprise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from control_center.cc_v1.projects import PROJECT_MATCH as _PROJECT_MATCH
from control_center.cc_v1.projects import projects_values_cte
from control_center.cc_v1.metric import Metric

__all__ = [
    "METRICS",
    "SPECS",
    "SPEC_BY_KEY",
    "WINDOWS",
    "WINDOW_LABELS",
    "DEFAULT_WINDOW",
    "DOMAIN",
    "Spec",
    "PROJECT_CTE",
]

DOMAIN = "aujourdhui"

#: Les fenêtres offertes, et l'intervalle PostgreSQL correspondant. Le client ne
#: choisit jamais un intervalle : il choisit une clé de ce dictionnaire. Une clé
#: inconnue ne construit aucun SQL.
WINDOWS: dict[str, str] = {
    "24h": "24 hours",
    "7d": "7 days",
    "30d": "30 days",
}

#: Le libellé français de la fenêtre, servi comme argument de gabarit narratif.
#: C'est du FORMATAGE (une durée en toutes lettres), pas un calcul.
WINDOW_LABELS: dict[str, str] = {
    "24h": "24 heures",
    "7d": "7 jours",
    "30d": "30 jours",
}

DEFAULT_WINDOW = "24h"


# ============================================================================
# Le type Spec — une mesure, trois fenêtres, une seule formule
# ============================================================================


@dataclass(frozen=True)
class Spec:
    """Une mesure de delta, déclarée indépendamment de sa fenêtre.

    ``sql_template`` et ``evidence_template`` ne comportent qu'UNE variable,
    ``{win}``, remplacée par un intervalle pris dans ``WINDOWS``. Aucune entrée
    utilisateur n'atteint le SQL : la clé de fenêtre est une clé de dictionnaire.

    ``direction`` est le SENS DE LECTURE de la mesure, servi au client pour qu'il
    sache dans quel sens une hausse est une bonne nouvelle — distinct de
    ``target``, qui est un seuil d'alerte. Une métrique peut avoir un sens de
    lecture sans mériter d'alerte.
    """

    key: str
    label: str
    unit: str
    definition: str
    formula: str
    evidence_label: str
    sql_template: str
    evidence_template: str
    direction: str = "up"
    target: dict[str, Any] | None = field(default=None)
    measurable: bool = True
    unavailable_reason: str = ""
    unavailable_gesture: str = ""
    unavailable_substitute: str = ""

    def sql(self, window: str = DEFAULT_WINDOW) -> str:
        return self.sql_template.format(win=WINDOWS[window])

    def evidence_sql(self, window: str = DEFAULT_WINDOW) -> str:
        return self.evidence_template.format(win=WINDOWS[window])

    def metric(self, window: str = DEFAULT_WINDOW) -> Metric:
        """Projette la ``Spec`` sur une fenêtre : une ``Metric`` du registre."""
        return Metric(
            key=self.key,
            label=self.label,
            unit=self.unit,
            definition=self.definition,
            formula=self.formula,
            sql=self.sql(window),
            evidence_sql=self.evidence_sql(window),
            evidence_label=self.evidence_label,
            domain=DOMAIN,
            window=window,
            target=self.target,
            # La Spec déclarait déjà ces trois champs sans les transmettre :
            # les mesures non mesurables héritaient donc du message générique
            # « valeur nulle retournée par la source », qui n'apprend rien.
            # Une indisponibilité doit dire CE QUI manque et CE QUI la débloquerait.
            unavailable_reason=self.unavailable_reason or None,
            unavailable_gesture=self.unavailable_gesture or None,
            substitute=self.unavailable_substitute or None,
        )


# ============================================================================
# Le prédicat des projets, en SQL littéral
# ============================================================================
#
# La règle vient de ``config/projects.toml`` et n'existe qu'à UN endroit :
# ``cc_v1/projects.py`` la traduit en SQL — ici comme dans ``entities`` et dans
# la famille ``projets``. Une métrique du registre doit porter un SQL LITTÉRAL,
# copiable dans psql : la règle est donc engendrée dans la chaîne, pas passée
# en paramètre.
#
# Le recouvrement entre projets est VOULU : un même atome peut faire progresser
# deux projets. L'interface ne résout jamais l'appartenance.

PROJECT_CTE = projects_values_cte("proj")

#: Le prédicat d'appartenance, appliqué aux alias ``a`` (memory_atoms) et ``p`` (proj).
PROJECT_MATCH = _PROJECT_MATCH

#: Ce qui n'est pas du savoir. Écrit une fois, appliqué partout.
NOT_TRANSPORT = "a.kind <> 'agent_message'"


# ============================================================================
# LES MESURES
# ============================================================================

SPECS: tuple[Spec, ...] = (

    # ------------------------------------------------------------ entrée brute
    Spec(
        key="today_conversations_received",
        label="Conversations reçues",
        unit="conversations",
        definition="Conversations détectées et enregistrées pendant la fenêtre.",
        formula="count(conversations WHERE created_at > now() - fenêtre)",
        direction="up",
        sql_template="""
            SELECT count(*) AS value
              FROM arac.conversations
             WHERE created_at > now() - interval '{win}'
        """,
        evidence_label=("Les dernières conversations détectées, celles de la fenêtre marquées ; "
                        "`total_fenetre` = la valeur servie, LIMIT compris"),
        # `total_fenetre` : compté par fenêtrage, donc AVANT le LIMIT (cf. en-tête).
        evidence_template="""
            SELECT conversation_uid,
                   title,
                   source_type,
                   node_id,
                   created_at,
                   (created_at > now() - interval '{win}') AS dans_la_fenetre,
                   count(*) FILTER (
                       WHERE created_at > now() - interval '{win}') OVER () AS total_fenetre
              FROM arac.conversations
             ORDER BY created_at DESC
             LIMIT 60
        """,
    ),
    Spec(
        key="today_conversations_curated",
        label="Conversations entièrement curées",
        unit="conversations",
        definition="Conversations dont le curseur de curation a rattrapé le dernier message pendant la fenêtre.",
        formula="count(conversations WHERE curated_at ∈ fenêtre ET curated_through_message_id >= max(raw_messages.id))",
        direction="up",
        sql_template="""
            SELECT count(*) AS value
              FROM arac.conversations c
             WHERE c.curated_at > now() - interval '{win}'
               AND c.exclusion_reason IS NULL
               AND c.last_curation_error IS NULL
               AND COALESCE(c.curated_through_message_id, 0) >= (
                     SELECT max(m.id) FROM arac.raw_messages m
                      WHERE m.conversation_id = c.id)
        """,
        evidence_label=("Les dernières curations, avec l'état réel du curseur ; "
                        "`total_fenetre` = la valeur servie, LIMIT compris"),
        evidence_template="""
            SELECT c.conversation_uid,
                   c.title,
                   c.source_type,
                   c.atoms_generated,
                   c.curated_at,
                   COALESCE(c.curated_through_message_id, 0) AS curseur,
                   s.dernier_message,
                   (COALESCE(c.curated_through_message_id, 0) >= s.dernier_message
                    AND c.exclusion_reason IS NULL
                    AND c.last_curation_error IS NULL)            AS entierement_curee,
                   /* Le marqueur porte le prédicat COMPLET de la valeur, pas seulement
                      la date : « entièrement curée » ET « dans la fenêtre ». Avec la
                      seule date, la preuve marquait 9 lignes pour une valeur de 6 —
                      les 3 conversations curées mais incomplètes ou exclues. La colonne
                      `entierement_curee` reste servie : elle dit pourquoi. */
                   (c.curated_at > now() - interval '{win}'
                    AND COALESCE(c.curated_through_message_id, 0) >= s.dernier_message
                    AND c.exclusion_reason IS NULL
                    AND c.last_curation_error IS NULL)            AS dans_la_fenetre,
                   count(*) FILTER (
                       WHERE c.curated_at > now() - interval '{win}'
                         AND COALESCE(c.curated_through_message_id, 0) >= s.dernier_message
                         AND c.exclusion_reason IS NULL
                         AND c.last_curation_error IS NULL) OVER () AS total_fenetre
              FROM arac.conversations c
              CROSS JOIN LATERAL (
                  SELECT max(m.id) AS dernier_message
                    FROM arac.raw_messages m
                   WHERE m.conversation_id = c.id
              ) s
             WHERE c.curated_at IS NOT NULL
             ORDER BY c.curated_at DESC
             LIMIT 60
        """,
    ),
    Spec(
        key="today_messages_absorbed",
        label="Messages absorbés",
        unit="messages",
        definition="Messages bruts entrés dans le cerveau pendant la fenêtre, curés ou non.",
        formula="count(raw_messages WHERE received_at > now() - fenêtre)",
        direction="up",
        sql_template="""
            SELECT count(*) AS value
              FROM arac.raw_messages
             WHERE received_at > now() - interval '{win}'
        """,
        evidence_label=("Les messages absorbés par jour, avec la part réellement "
                        "dans la fenêtre glissante (sa somme = la valeur servie)"),
        # POURQUOI `FILTER (WHERE received_at > now() - interval)` ET NON UN JOUR TRONQUÉ :
        # le marqueur comparait `date_trunc('day', received_at)` à `date_trunc('day',
        # now() - fenêtre)`, c'est-à-dire un JOUR UTC ENTIER, alors que la valeur, elle,
        # est comptée sur la fenêtre GLISSANTE. La preuve marquait 403 là où la valeur
        # affirmait 3813 : elle contredisait le chiffre qu'elle prétendait justifier.
        # Désormais `messages_dans_la_fenetre` porte le MÊME prédicat que sql_template :
        # la somme de la colonne sur les lignes servies REND la valeur affichée.
        # LIMIT 40 (et non 30) : une fenêtre de 30 jours glissants touche jusqu'à
        # 31 journées calendaires — à 30 lignes la somme pouvait en perdre une.
        evidence_template="""
            SELECT date_trunc('day', received_at)            AS jour,
                   count(*)                                  AS messages,
                   count(*) FILTER (
                       WHERE received_at > now() - interval '{win}')
                                                             AS messages_dans_la_fenetre,
                   count(DISTINCT conversation_id)           AS conversations,
                   count(*) FILTER (WHERE was_masked)        AS masques,
                   bool_or(received_at > now() - interval '{win}') AS dans_la_fenetre
              FROM arac.raw_messages
             GROUP BY 1
             ORDER BY 1 DESC
             LIMIT 40
        """,
    ),

    # --------------------------------------------------------------- le savoir
    Spec(
        key="today_atoms_created",
        label="Atomes créés",
        unit="atomes",
        definition="Souvenirs neufs écrits pendant la fenêtre, hors messages d'agent qui ne sont pas du savoir.",
        formula="count(memory_atoms WHERE created_at ∈ fenêtre ET kind <> 'agent_message')",
        direction="up",
        target={"warn": 1, "critical": 0, "direction": "up"},
        sql_template="""
            /* `status = 'active'` : même filtre que `view_new_24h`, qui répond à la
               MÊME question dans le panneau Atomes. Sans lui, un atome créé puis
               remplacé dans la fenêtre était compté ici et pas là — deux chiffres
               différents pour « ce que le cerveau a appris aujourd'hui ». */
            SELECT count(*) AS value
              FROM arac.memory_atoms a
             WHERE a.kind <> 'agent_message'
               AND a.status = 'active'
               AND a.created_at > now() - interval '{win}'
        """,
        evidence_label=("Les derniers souvenirs écrits, ceux que la valeur compte marqués ; "
                        "`total_fenetre` = la valeur servie, LIMIT compris"),
        # `a.status` EST SERVI et le marqueur porte `status = 'active'`, comme la valeur.
        # Avant : le marqueur ne testait que la date, donc la preuve marquait 48 lignes
        # là où la valeur en comptait 46 (fenêtre 7 j) — les 2 atomes créés puis remplacés
        # dans la fenêtre. Le lecteur voit maintenant POURQUOI une ligne n'est pas comptée.
        evidence_template="""
            SELECT a.id,
                   a.kind,
                   a.scope,
                   a.key,
                   a.status,
                   a.confidence_score,
                   a.created_at,
                   a.source_ref ->> 'conversation_uid'          AS conversation_uid,
                   (a.scope NOT LIKE '%/%')                     AS pose_sur_une_racine,
                   (a.status = 'active'
                    AND a.created_at > now() - interval '{win}') AS dans_la_fenetre,
                   count(*) FILTER (
                       WHERE a.status = 'active'
                         AND a.created_at > now() - interval '{win}') OVER () AS total_fenetre
              FROM arac.memory_atoms a
             WHERE a.kind <> 'agent_message'
             ORDER BY a.created_at DESC
             LIMIT 60
        """,
    ),
    Spec(
        key="today_atoms_enriched",
        label="Atomes enrichis",
        unit="atomes",
        definition="Atomes existants réécrits pendant la fenêtre sans être remplacés : le cerveau a affiné, pas ajouté.",
        formula="count(memory_atoms WHERE updated_at ∈ fenêtre ET updated_at > created_at ET superseded_by IS NULL)",
        direction="up",
        sql_template="""
            SELECT count(*) AS value
              FROM arac.memory_atoms a
             WHERE a.kind <> 'agent_message'
               AND a.superseded_by IS NULL
               AND a.updated_at > a.created_at
               AND a.updated_at > now() - interval '{win}'
               /* Né AVANT la fenêtre : sinon un atome créé puis retouché le même
                  jour était compté deux fois, en « créé » ET en « enrichi ».
                  Enrichir, c'est revenir sur un savoir déjà acquis. */
               AND a.created_at <= now() - interval '{win}'
        """,
        evidence_label=("Les derniers enrichissements, ceux de la fenêtre marqués ; "
                        "`total_fenetre` = la valeur servie, LIMIT compris"),
        evidence_template="""
            SELECT a.id,
                   a.kind,
                   a.scope,
                   a.key,
                   a.version,
                   a.status,
                   a.created_at,
                   a.updated_at,
                   /* `created_at <= now() - fenêtre` fait partie du prédicat de la
                      valeur (enrichir, c'est revenir sur un savoir DÉJÀ acquis) : sans
                      lui, un atome né ET retouché dans la fenêtre serait marqué ici sans
                      être compté là. Latent aujourd'hui (0 cas), latent par accident. */
                   (a.updated_at > now() - interval '{win}'
                    AND a.created_at <= now() - interval '{win}') AS dans_la_fenetre,
                   count(*) FILTER (
                       WHERE a.updated_at > now() - interval '{win}'
                         AND a.created_at <= now() - interval '{win}') OVER () AS total_fenetre
              FROM arac.memory_atoms a
             WHERE a.kind <> 'agent_message'
               AND a.superseded_by IS NULL
               AND a.updated_at > a.created_at
             ORDER BY a.updated_at DESC
             LIMIT 60
        """,
    ),
    Spec(
        key="today_atoms_superseded",
        label="Atomes remplacés",
        unit="atomes",
        definition="Atomes qu'une version plus récente a évincés pendant la fenêtre : le cerveau a changé d'avis.",
        formula="count(memory_atoms WHERE superseded_by IS NOT NULL ET updated_at ∈ fenêtre)",
        direction="up",
        sql_template="""
            SELECT count(*) AS value
              FROM arac.memory_atoms a
             WHERE a.superseded_by IS NOT NULL
               /* Le transport d'agent n'est pas du savoir : la convention du socle
                  l'exclut partout ailleurs dans cette famille. Latent aujourd'hui
                  (aucun agent_message remplacé), mais latent par accident. */
               AND a.kind <> 'agent_message'
               AND a.updated_at > now() - interval '{win}'
        """,
        evidence_label=("Les dernières supersessions, avec l'atome qui a pris la place ; "
                        "`total_fenetre` = la valeur servie, LIMIT compris"),
        evidence_template="""
            SELECT a.id                                       AS atome_evince,
                   a.kind,
                   a.scope,
                   a.key,
                   a.status,
                   a.superseded_by                            AS remplace_par,
                   a.created_at,
                   a.updated_at,
                   /* Le marqueur porte AUSSI `kind <> 'agent_message'`, comme la valeur :
                      sans lui, un message d'agent remplacé dans la fenêtre serait marqué
                      ici sans être compté là. Latent aujourd'hui (0 cas), latent par
                      accident — le même oubli s'est déjà payé ailleurs dans ce fichier. */
                   (a.updated_at > now() - interval '{win}'
                    AND a.kind <> 'agent_message')            AS dans_la_fenetre,
                   count(*) FILTER (
                       WHERE a.updated_at > now() - interval '{win}'
                         AND a.kind <> 'agent_message') OVER ()  AS total_fenetre
              FROM arac.memory_atoms a
             WHERE a.superseded_by IS NOT NULL
             ORDER BY a.updated_at DESC
             LIMIT 60
        """,
    ),

    # -------------------------------------------------------- territoire touché
    Spec(
        key="today_scopes_touched",
        label="Scopes touchés",
        unit="scopes",
        definition="Domaines de mémoire ayant reçu au moins un atome neuf ou enrichi pendant la fenêtre.",
        formula="count(DISTINCT scope) sur les atomes créés ou mis à jour dans la fenêtre",
        direction="up",
        sql_template="""
            SELECT count(DISTINCT a.scope) AS value
              FROM arac.memory_atoms a
             WHERE a.kind <> 'agent_message'
               /* Un scope dont le seul mouvement de la fenêtre est un archivage
                  n'a rien REÇU : la définition promet « un atome neuf ou enrichi ». */
               AND a.status = 'active'
               AND (a.created_at > now() - interval '{win}'
                    OR a.updated_at > now() - interval '{win}')
        """,
        evidence_label=("Chaque scope, ce qu'il a gagné dans la fenêtre et ce qu'il pèse : "
                        "le nombre de lignes marquées `dans_la_fenetre` = la valeur servie, "
                        "que `total_fenetre` porte aussi telle quelle (LIMIT compris)"),
        # POURQUOI `a.status = 'active'` DANS LES FILTER : la valeur ne compte que les
        # scopes ayant reçu un atome ACTIF (un archivage n'est pas une réception). La preuve,
        # elle, comptait tous statuts : un scope dont le seul mouvement était une
        # supersession apparaissait comme « touché » alors que la valeur l'excluait.
        # `dans_la_fenetre` transcrit maintenant, mot pour mot, le prédicat de sql_template :
        # compter les lignes vraies rend le chiffre affiché.
        evidence_template="""
            SELECT a.scope,
                   count(*) FILTER (
                       WHERE a.status = 'active'
                         AND a.created_at > now() - interval '{win}')      AS atomes_crees,
                   count(*) FILTER (
                       WHERE a.status = 'active'
                         AND a.updated_at > now() - interval '{win}'
                         AND a.updated_at > a.created_at)                  AS atomes_enrichis,
                   count(*) FILTER (WHERE a.status = 'active')             AS atomes_actifs,
                   (a.scope NOT LIKE '%/%')                                AS scope_racine,
                   (count(*) FILTER (
                       WHERE a.status = 'active'
                         AND (a.created_at > now() - interval '{win}'
                              OR a.updated_at > now() - interval '{win}')) > 0)
                                                                           AS dans_la_fenetre,
                   sum(CASE WHEN count(*) FILTER (
                                WHERE a.status = 'active'
                                  AND (a.created_at > now() - interval '{win}'
                                       OR a.updated_at > now() - interval '{win}')) > 0
                            THEN 1 ELSE 0 END) OVER ()                     AS total_fenetre
              FROM arac.memory_atoms a
             WHERE a.kind <> 'agent_message'
             GROUP BY a.scope
             ORDER BY 2 DESC, 3 DESC, 4 DESC
             LIMIT 60
        """,
    ),
    Spec(
        key="today_projects_progressed",
        label="Projets qui ont progressé",
        unit="projets",
        definition="Projets, parmi les huit, ayant gagné au moins un atome pendant la fenêtre.",
        formula="count(DISTINCT projet) où au moins un atome créé dans la fenêtre satisfait la règle du projet",
        direction="up",
        sql_template=f"""
            WITH {PROJECT_CTE},
            gagnants AS (
                SELECT p.id
                  FROM proj p
                  JOIN arac.memory_atoms a
                    ON {PROJECT_MATCH}
                 WHERE {NOT_TRANSPORT}
                   AND a.created_at > now() - interval '{{win}}'
                 GROUP BY p.id
            )
            SELECT count(*) AS value FROM gagnants
        """,
        evidence_label="Les huit projets et ce que la fenêtre leur a apporté",
        evidence_template=f"""
            WITH {PROJECT_CTE}
            SELECT p.id                                                  AS projet,
                   p.label,
                   count(a.id) FILTER (
                       WHERE a.created_at > now() - interval '{{win}}')   AS atomes_gagnes,
                   count(a.id) FILTER (
                       WHERE a.updated_at > now() - interval '{{win}}'
                         AND a.updated_at > a.created_at)                AS atomes_enrichis,
                   count(a.id) FILTER (WHERE a.status = 'active')        AS atomes_actifs,
                   max(a.created_at)                                     AS dernier_atome,
                   /* Le marqueur manquait : la preuve listait les huit projets sans dire
                      lesquels la valeur compte. Le NOMBRE de lignes vraies = la valeur. */
                   (count(a.id) FILTER (
                       WHERE a.created_at > now() - interval '{{win}}') > 0) AS dans_la_fenetre
              FROM proj p
              LEFT JOIN arac.memory_atoms a
                ON {PROJECT_MATCH}
               AND {NOT_TRANSPORT}
             GROUP BY p.id, p.label
             ORDER BY 3 DESC, 5 DESC
        """,
    ),

    # ------------------------------------------------------------- la machine
    Spec(
        key="today_cycles_run",
        label="Cycles exécutés",
        unit="cycles",
        definition="Cycles de digestion démarrés pendant la fenêtre, tous statuts confondus.",
        formula="count(run_receipts WHERE started_at > now() - fenêtre), détail = répartition par statut",
        direction="up",
        sql_template="""
            WITH c AS (
                SELECT status FROM arac.run_receipts
                 WHERE started_at > now() - interval '{win}'
            )
            SELECT (SELECT count(*) FROM c) AS value,
                   (SELECT string_agg(status || ' : ' || n::text, ' · ' ORDER BY n DESC)
                      FROM (SELECT status, count(*) AS n FROM c GROUP BY status) g) AS detail
        """,
        evidence_label=("Les derniers cycles, leur issue et ce qu'ils ont produit ; "
                        "`total_fenetre` = la valeur servie, LIMIT compris"),
        evidence_template="""
            SELECT r.id,
                   r.slot_key,
                   r.trigger,
                   r.model,
                   r.status,
                   r.stop_reason,
                   r.items,
                   r.atoms_created,
                   r.atoms_superseded,
                   r.atoms_quarantined,
                   r.est_input_tokens,
                   r.started_at,
                   (r.started_at > now() - interval '{win}') AS dans_la_fenetre,
                   count(*) FILTER (
                       WHERE r.started_at > now() - interval '{win}') OVER () AS total_fenetre
              FROM arac.run_receipts r
             ORDER BY r.started_at DESC
             LIMIT 60
        """,
    ),
    Spec(
        key="today_cycles_done",
        label="Cycles menés à terme",
        unit="cycles",
        definition="Cycles de la fenêtre dont l'issue est « done » : le seul statut qui produit du savoir.",
        formula="count(run_receipts WHERE started_at ∈ fenêtre ET status = 'done')",
        direction="up",
        sql_template="""
            SELECT count(*) AS value
              FROM arac.run_receipts
             WHERE started_at > now() - interval '{win}'
               AND status = 'done'
        """,
        evidence_label=("Les cycles menés à terme, et ceux qui ne l'ont pas été : la somme "
                        "de `dans_la_fenetre` (nulle hors du statut « done ») = la valeur"),
        # La colonne qui portait le nom `dans_la_fenetre` comptait les cycles de la fenêtre
        # TOUS STATUTS : sa somme donnait 6 quand la valeur en affirmait 1. Elle s'appelle
        # désormais `cycles_dans_la_fenetre` (information de contexte), et `dans_la_fenetre`
        # porte le prédicat COMPLET de la valeur — fenêtre ET statut « done ».
        evidence_template="""
            SELECT r.status,
                   count(*)                                              AS cycles,
                   count(*) FILTER (
                       WHERE r.started_at > now() - interval '{win}')     AS cycles_dans_la_fenetre,
                   count(*) FILTER (
                       WHERE r.started_at > now() - interval '{win}'
                         AND r.status = 'done')                          AS dans_la_fenetre,
                   COALESCE(sum(r.atoms_created), 0)                     AS atomes_produits,
                   COALESCE(sum(r.est_input_tokens), 0)                  AS jetons
              FROM arac.run_receipts r
             GROUP BY r.status
             ORDER BY 2 DESC
        """,
    ),
    Spec(
        key="today_cycles_quarantined",
        label="Cycles en quarantaine",
        unit="cycles",
        definition="Cycles de la fenêtre partis en quarantaine : ce qu'ils portaient n'a pas été retenu.",
        formula="count(run_receipts WHERE started_at ∈ fenêtre ET status = 'quarantined')",
        direction="down",
        # PAS de seuil absolu : 2 quarantaines sont beaucoup sur 24 h et peu sur
        # 30 j. Un seuil calibré pour la fenêtre canonique et appliqué tel quel
        # aux autres rendait la carte critique par construction dès qu'on
        # changeait d'échelle — une alerte qui ne dépend pas de la mesure n'est
        # pas une alerte. Le taux, lui, est comparable entre fenêtres : il est
        # porté par `cycle_quarantine_rate` (famille digestion), qui a le seuil.
        target=None,
        sql_template="""
            SELECT count(*) AS value
              FROM arac.run_receipts
             WHERE started_at > now() - interval '{win}'
               AND status = 'quarantined'
        """,
        evidence_label=("Les dernières quarantaines, avec leur motif d'arrêt ; "
                        "`total_fenetre` = la valeur servie, LIMIT compris"),
        evidence_template="""
            SELECT r.id,
                   r.slot_key,
                   r.trigger,
                   r.stop_reason,
                   r.items,
                   r.atoms_quarantined,
                   r.quarantine_attributed_uids,
                   r.est_input_tokens,
                   r.started_at,
                   (r.started_at > now() - interval '{win}') AS dans_la_fenetre,
                   count(*) FILTER (
                       WHERE r.started_at > now() - interval '{win}') OVER () AS total_fenetre
              FROM arac.run_receipts r
             WHERE r.status = 'quarantined'
             ORDER BY r.started_at DESC
             LIMIT 60
        """,
    ),
    Spec(
        key="today_candidates_dropped",
        label="Candidats écartés",
        unit="candidats",
        definition="Atomes proposés puis refusés à l'entrée pendant la fenêtre : du savoir présenté et non retenu.",
        formula="count(digestion_review_queue WHERE created_at > now() - fenêtre)",
        direction="down",
        sql_template="""
            SELECT count(*) AS value
              FROM arac.digestion_review_queue
             WHERE created_at > now() - interval '{win}'
        """,
        evidence_label="Les motifs de refus, dans la fenêtre et depuis toujours",
        evidence_template="""
            SELECT q.drop_reason                                          AS motif,
                   count(*) FILTER (
                       WHERE q.created_at > now() - interval '{win}')     AS dans_la_fenetre,
                   count(*)                                              AS total,
                   count(*) FILTER (WHERE q.status = 'pending')          AS encore_en_attente,
                   max(q.created_at)                                     AS dernier
              FROM arac.digestion_review_queue q
             GROUP BY q.drop_reason
             ORDER BY 2 DESC, 3 DESC
             LIMIT 40
        """,
    ),

    # ----------------------------------------------------------------- l'usage
    Spec(
        key="today_recall_served",
        label="Rappels servis",
        unit="rappels",
        definition=("Contextes servis à un consommateur pendant la fenêtre : le cerveau a été "
                    "interrogé. Un rappel = un request_id, quel que soit le nombre de moteurs "
                    "qui en ont écrit un reçu."),
        formula="count(DISTINCT context_receipts.request_id WHERE created_at > now() - fenêtre)",
        direction="up",
        # POURQUOI `DISTINCT request_id` : depuis FOLD V2, chaque rappel réel écrit
        # DEUX lignes dans arac.context_receipts — le moteur v1 (`ce-shadow-r3pur-v1`) puis
        # le moteur v2-fold, avec le MÊME request_id et les MÊMES served_ids
        # (app/routers/atoms.py appelle run_shadow_v2 après run_shadow). Compter les lignes
        # affichait donc le DOUBLE des rappels réels : 102 au lieu de 51 sur 24 h.
        # Le compte de request_id distincts reste juste si un moteur v3 apparaît.
        sql_template="""
            SELECT count(DISTINCT request_id) AS value
              FROM arac.context_receipts
             WHERE created_at > now() - interval '{win}'
        """,
        evidence_label=("Les rappels par jour (reçus dédoublonnés par request_id), "
                        "avec la part dans la fenêtre glissante et la bande confiante"),
        # DEUX CORRECTIONS ICI, cf. sql_template ci-dessus.
        # 1) `count(DISTINCT request_id)` : depuis FOLD V2 chaque rappel réel écrit
        #    DEUX lignes (moteur v1 puis v2-fold, même request_id, mêmes served_ids).
        #    Compter les lignes doublait le chiffre.
        # 2) Marqueur sur la fenêtre GLISSANTE et non sur le jour UTC tronqué : la
        #    colonne `rappels_dans_la_fenetre` porte exactement le prédicat de la
        #    valeur, donc sa somme sur les lignes servies REND la valeur affichée.
        evidence_template="""
            SELECT date_trunc('day', created_at)                          AS jour,
                   count(DISTINCT request_id)                            AS rappels,
                   count(DISTINCT request_id) FILTER (
                       WHERE created_at > now() - interval '{win}')      AS rappels_dans_la_fenetre,
                   count(*)                                              AS recus_ecrits,
                   count(DISTINCT request_id) FILTER (
                       WHERE final_band = 'high')                        AS bande_haute,
                   count(DISTINCT request_id) FILTER (
                       WHERE COALESCE(cardinality(served_ids), 0) = 0)   AS rappels_vides,
                   count(DISTINCT consumer)                              AS consommateurs,
                   bool_or(created_at > now() - interval '{win}')        AS dans_la_fenetre
              FROM arac.context_receipts
             GROUP BY 1
             ORDER BY 1 DESC
             LIMIT 40
        """,
    ),

    # ------------------------------------------------------------------ le coût
    Spec(
        key="today_tokens_spent",
        label="Jetons dépensés",
        unit="jetons",
        definition="Jetons d'entrée estimés consommés par les cycles démarrés pendant la fenêtre.",
        formula="sum(run_receipts.est_input_tokens WHERE started_at > now() - fenêtre)",
        direction="down",
        sql_template="""
            SELECT COALESCE(sum(est_input_tokens), 0) AS value
              FROM arac.run_receipts
             WHERE started_at > now() - interval '{win}'
        """,
        evidence_label=("Les jetons par cycle : la SOMME de `jetons_dans_la_fenetre` "
                        "rend la valeur servie, et `total_fenetre` la porte telle quelle"),
        # CE QUI ÉTAIT FAUX : la preuve ne portait qu'un marqueur BOOLÉEN. Or la valeur
        # n'est pas un compte de cycles mais une SOMME DE JETONS : compter les lignes
        # marquées, comme pour les autres mesures de la famille, rendait 6 quand la
        # valeur affirmait 487 179. La colonne `jetons_dans_la_fenetre` porte la
        # contribution RÉELLE de chaque ligne, et `total_fenetre` la somme complète —
        # calculée par fenêtrage, donc avant le LIMIT, qui tronquait déjà 60 des 134
        # cycles de la fenêtre 30 jours.
        evidence_template="""
            SELECT r.id,
                   r.slot_key,
                   r.status,
                   r.model,
                   r.est_input_tokens                                    AS jetons,
                   CASE WHEN r.started_at > now() - interval '{win}'
                        THEN COALESCE(r.est_input_tokens, 0) ELSE 0 END  AS jetons_dans_la_fenetre,
                   r.atoms_created                                       AS atomes,
                   r.items,
                   r.started_at,
                   (r.started_at > now() - interval '{win}')             AS dans_la_fenetre,
                   COALESCE(sum(r.est_input_tokens) FILTER (
                       WHERE r.started_at > now() - interval '{win}') OVER (), 0)
                                                                         AS total_fenetre
              FROM arac.run_receipts r
             ORDER BY r.started_at DESC
             LIMIT 60
        """,
    ),
    Spec(
        key="today_cost_per_atom",
        label="Coût par atome du jour",
        unit="jetons/atome",
        definition="Jetons dépensés dans la fenêtre rapportés aux atomes qu'elle a produits.",
        formula="sum(est_input_tokens) / count(atomes créés) — indéfini si aucun atome n'a été produit",
        direction="down",
        target={"warn": 80000, "critical": 200000, "direction": "down"},
        # Zéro atome ne fait pas un coût nul : il fait un coût INDÉFINI. La
        # division rend NULL, et cette raison-là est servie plutôt que la raison
        # générique du service — « 0 jeton par atome » serait un mensonge flatteur.
        unavailable_reason=("aucun atome n'a été produit dans la fenêtre : le coût par atome "
                            "est indéfini, ce n'est pas un coût nul"),
        unavailable_gesture="regarder pourquoi les cycles n'ont rien retenu (quarantaines, candidats écartés)",
        unavailable_substitute="les jetons dépensés (today_tokens_spent), qui restent mesurés",
        sql_template="""
            WITH j AS (
                SELECT COALESCE(sum(est_input_tokens), 0)::numeric AS jetons
                  FROM arac.run_receipts
                 WHERE started_at > now() - interval '{win}'
            ), t AS (
                /* `status = 'active'` : MÊME population que `today_atoms_created`, qui est
                   le chiffre annoncé dans le même bandeau (« créé N atome(s) de savoir »).
                   Sans ce filtre le dénominateur portait sur TOUS les statuts : le lecteur
                   qui posait la division tombait sur un autre nombre que celui qu'on venait
                   de lui donner (30 023 contre 29 280 servis, sur 30 jours), et le mot
                   « retenu » du gabarit revendique précisément la population active. */
                SELECT count(*)::numeric AS atomes
                  FROM arac.memory_atoms a
                 WHERE a.kind <> 'agent_message'
                   AND a.status = 'active'
                   AND a.created_at > now() - interval '{win}'
            )
            SELECT round(j.jetons / nullif(t.atomes, 0), 0) AS value,
                   j.jetons::text || ' jetons pour ' || t.atomes::text || ' atomes' AS detail
              FROM j, t
        """,
        evidence_label=("Le coût par atome jour par jour, avec les jetons et les atomes "
                        "réellement dans la fenêtre (leur quotient = la valeur servie)"),
        # DEUX CORRECTIONS.
        # 1) `a.status = 'active'` dans la CTE `at`, comme dans sql_template : la preuve
        #    journalière comptait une AUTRE population que la valeur.
        # 2) Colonnes `*_dans_la_fenetre` sur la fenêtre GLISSANTE. Le marqueur comparait
        #    des JOURS TRONQUÉS pendant que la valeur glissait : la seule ligne marquée
        #    rendait 60 897 jetons/atome quand la valeur affirmait 72 993. Désormais
        #    sum(jetons_dans_la_fenetre) / sum(atomes_dans_la_fenetre) = la valeur servie.
        evidence_template="""
            WITH cy AS (
                SELECT date_trunc('day', started_at)               AS jour,
                       COALESCE(sum(est_input_tokens), 0)::numeric AS jetons,
                       COALESCE(sum(est_input_tokens) FILTER (
                           WHERE started_at > now() - interval '{win}'), 0)::numeric
                                                                   AS jetons_dans_la_fenetre,
                       count(*)                                    AS cycles
                  FROM arac.run_receipts
                 GROUP BY 1
            ), at AS (
                SELECT date_trunc('day', a.created_at) AS jour,
                       count(*)::numeric               AS atomes,
                       count(*) FILTER (
                           WHERE a.created_at > now() - interval '{win}')::numeric
                                                       AS atomes_dans_la_fenetre
                  FROM arac.memory_atoms a
                 WHERE a.kind <> 'agent_message'
                   AND a.status = 'active'
                 GROUP BY 1
            )
            SELECT cy.jour,
                   cy.cycles,
                   cy.jetons,
                   cy.jetons_dans_la_fenetre,
                   COALESCE(at.atomes, 0)                                  AS atomes,
                   COALESCE(at.atomes_dans_la_fenetre, 0)                  AS atomes_dans_la_fenetre,
                   round(cy.jetons / nullif(at.atomes, 0), 0)              AS jetons_par_atome,
                   (cy.jetons_dans_la_fenetre > 0
                    OR COALESCE(at.atomes_dans_la_fenetre, 0) > 0)         AS dans_la_fenetre
              FROM cy
              LEFT JOIN at ON at.jour = cy.jour
             ORDER BY cy.jour DESC
             LIMIT 40
        """,
    ),

    # ========================================================================
    # LES TROIS ABSENCES — déclarées, jamais nulles, jamais zéro
    # ========================================================================
    #
    # Leur valeur est NULL : le service les traduit en `unavailable`. Leur preuve
    # ne récite pas la panne, elle la CONSTATE en base à l'instant où on l'ouvre.
    # Le jour où la dépendance arrivera, la preuve le dira d'elle-même.

    Spec(
        key="today_links_created",
        label="Liens créés",
        unit="liens",
        definition="Liens tissés entre atomes pendant la fenêtre — non mesurable : cette mesure n'est pas branchée sur la table des liens.",
        formula="indisponible : ce panneau ne compte pas les lignes de arac.atom_links",
        direction="up",
        measurable=False,
        # Repli seulement. La raison servie est CONSTATÉE par la requête
        # ci-dessous : le texte gravé affirmait qu'une migration n'était pas
        # appliquée, sans jamais l'avoir vérifié, et le disait encore une fois
        # qu'elle l'était.
        unavailable_reason="la création de liens n'est pas comptée par ce panneau",
        unavailable_gesture="branchez ce compte sur arac.atom_links",
        unavailable_substitute="voisinage sémantique (embedding) et vue « atomes jamais rappelés »",
        sql_template="""
            SELECT NULL::numeric AS value,
                   CASE WHEN to_regclass('arac.atom_links') IS NULL
                        THEN 'table arac.atom_links absente : rien à compter, et surtout pas zéro'
                        ELSE 'table arac.atom_links présente, mais ce panneau ne compte pas ses lignes'
                        END AS detail,
                   CASE WHEN to_regclass('arac.atom_links') IS NULL
                        THEN 'la table arac.atom_links est absente du schéma : aucun lien '
                             || 'n''est matérialisé'
                        ELSE 'la table arac.atom_links est déployée, mais ce panneau ne '
                             || 'compte pas encore ses lignes'
                        END AS reason,
                   CASE WHEN to_regclass('arac.atom_links') IS NULL
                        THEN 'appliquez les migrations en attente : alembic upgrade head'
                        ELSE 'branchez ce compte sur arac.atom_links'
                        END AS gesture
        """,
        evidence_label="L'état de la dépendance, constaté en base maintenant",
        evidence_template="""
            SELECT 'arac.atom_links'                                       AS dependance,
                   (to_regclass('arac.atom_links') IS NOT NULL)            AS deployee_maintenant,
                   to_regclass('arac.atom_links')::text                    AS resolue_en,
                   'voisinage sémantique (embedding) et vue « jamais rappelés »' AS substitut,
                   now()                                                   AS constate_a
             LIMIT 1
        """,
    ),
    Spec(
        key="today_contradictions",
        label="Contradictions détectées",
        unit="contradictions",
        definition="Contradictions relevées pendant la fenêtre — non mesurable : aucun mécanisme n'en produit.",
        formula="indisponible : aucun producteur n'écrit de contradiction (ni atome, ni ligne d'audit)",
        direction="down",
        measurable=False,
        # La raison énonce le MÉCANISME absent, jamais un compte : un compte écrit
        # ici serait celui de la base sur laquelle il a été relevé, donc faux chez
        # tout autre lecteur. La preuve ci-dessous compte les trois sources EN BASE.
        unavailable_reason=("aucun producteur de contradiction : rien n'écrit d'atome "
                            "kind='contradiction', ni de ligne dans audit_links / audit_feedback"),
        unavailable_gesture=("brancher un détecteur qui écrive soit un atome kind='contradiction', "
                             "soit une ligne dans arac.audit_links / arac.audit_feedback"),
        unavailable_substitute="la supersession (superseded_by) : le seul conflit réellement enregistré",
        sql_template="""
            SELECT NULL::numeric AS value,
                   'aucun mécanisme ne produit de contradiction : « 0 » se lirait comme une bonne nouvelle' AS detail
        """,
        evidence_label="Les trois sources possibles, comptées en base maintenant",
        evidence_template="""
            SELECT source,
                   lignes,
                   'aucun mécanisme n''alimente cette source' AS raison,
                   'brancher un détecteur de contradiction (atome kind=''contradiction'' ou ligne d''audit)' AS geste,
                   'la supersession (superseded_by), seul conflit réellement enregistré' AS substitut
              FROM (
                    SELECT 'arac.memory_atoms WHERE kind = ''contradiction''' AS source,
                           count(*) AS lignes
                      FROM arac.memory_atoms WHERE kind = 'contradiction'
                     UNION ALL
                    SELECT 'arac.audit_links', count(*) FROM arac.audit_links
                     UNION ALL
                    SELECT 'arac.audit_feedback', count(*) FROM arac.audit_feedback
              ) s
             GROUP BY source, lignes
             ORDER BY source
        """,
    ),
    Spec(
        key="today_regressions",
        label="Régressions de benchmark",
        unit="régressions",
        definition="Régressions du benchmark NRB sur la fenêtre — non mesurable : le score ne vit pas en base.",
        formula="indisponible : le score NRB est produit par un harnais externe et déposé dans un fichier JSON",
        direction="down",
        measurable=False,
        unavailable_reason=("le score du benchmark NRB n'est pas persisté en base : il est produit "
                            "par un harnais externe et déposé dans un fichier JSON"),
        # Le geste renvoyait à « chantier moteur B11 » : un identifiant
        # de registre privé, que le lecteur ne peut ni ouvrir ni deviner. Un
        # geste doit dire QUOI faire, pas où c'est écrit ailleurs.
        unavailable_gesture=("faites écrire le score de chaque passage du "
                             "benchmark dans arac.run_receipts : une régression "
                             "n'est observable que si le score vit en base"),
        unavailable_substitute=("la confiance observée sur les rappels réellement servis "
                                "(context_receipts.final_band)"),
        sql_template="""
            SELECT NULL::numeric AS value,
                   'le score NRB ne vit pas en base : aucune régression n''y est observable' AS detail
        """,
        evidence_label="Les tables candidates cherchées dans le schéma, et ce qu'on trouve à la place",
        evidence_template="""
            SELECT 'score du benchmark NRB'                                       AS dependance,
                   'non persisté en base : produit par un harnais externe, déposé en fichier JSON' AS raison,
                   'persister chaque passage du NRB en base (chantier moteur B11)' AS geste,
                   'confiance observée sur les rappels servis (context_receipts.final_band)' AS substitut,
                   (SELECT count(*) FROM information_schema.tables
                     WHERE table_schema = 'arac'
                       AND (table_name ILIKE '%benchmark%' OR table_name ILIKE '%nrb%')
                   )                                                              AS tables_candidates_trouvees,
                   /* count(DISTINCT request_id) et non count(*) : le substitut annoncé est
                      la confiance observée PAR RAPPEL. Depuis FOLD V2 chaque rappel
                      écrit deux reçus (moteur servi v1, moteur d'ombre v2-fold, même
                      request_id) : compter les lignes annonçait deux fois plus de mesures
                      disponibles que le substitut n'en porte réellement. */
                   (SELECT count(DISTINCT request_id) FROM arac.context_receipts) AS mesures_du_substitut
             LIMIT 1
        """,
    ),
)

SPEC_BY_KEY: dict[str, Spec] = {s.key: s for s in SPECS}

#: Ce que lit le registre : les mêmes mesures, projetées sur la fenêtre canonique
#: de 24 h. Du SQL littéral, contrôlable par ``tests/test_cc_v1_registry.py`` et
#: rejouable dans ``psql`` sans transformation.
METRICS: tuple[Metric, ...] = tuple(s.metric(DEFAULT_WINDOW) for s in SPECS)
