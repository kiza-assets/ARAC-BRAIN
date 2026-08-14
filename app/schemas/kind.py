"""Enum des kinds ARAC — validation stricte côté API + miroir BDD CHECK.

20 kinds (15 Phase 2.7 + `agent_message` ajouté Phase B triade 2026-05-18
+ `mission_proposal` et `mission` ajoutés Phase D plumbing 2026-05-19
+ `delivery` ajouté Phase D.5 vague 2 2026-05-20
+ `imported_conversation_summary` ajouté V1.6B 2026-06-11) figés au DDL
`arac.memory_atoms.kind` CHECK constraint (stack v2 §2.4 + migrations
alembic 0002_agent_message_bus, 0003_mission_kinds,
0004_delivery_kind_immobilier_scopes puis 0011_imported_conversation_kind).
Toute modification requiert une migration Alembic ALTER TABLE ... DROP/ADD
CONSTRAINT, **avec migration des données existantes** si suppression d'un kind.

Note historique : `mood` initialement envisagé en vision §3.3 a été abandonné
stack v2 §2.4. Encodage alternatif documenté : `tag` sur atome `note`/`insight`,
ou champ JSONB dans `source_ref`.

Le kind est validé contre une énumération fermée, doublée d'un CHECK en
base : deux remparts, parce qu'un seul finit toujours par être contourné.
"""

from enum import Enum


class Kind(str, Enum):
    """20 kinds (16 producteurs + 4 auditeurs).

    Producteurs : atomes que l'utilisateur ou un agent producteur peut écrire.
    Auditeurs   : atomes que les agents autonomes ou validations interactives
                  écrivent pour annoter d'autres atomes (l'`audit_log` lie
                  l'audit à sa cible via `target_atom_id`).
    """

    # --- Producteurs hérités du prototype antérieur (6) ---
    # Source de vérité du prototype antérieur : la doctrine anti-dérive
    # §2.2 candidat Article 5 + §4.3 (6 buckets du prototype antérieur). Correction Phase 2.7 :
    # initialement commenté "7 producteurs" Phase 2.1 par présomption pré-vérification
    # empirique (kind.py commit fb891d3, 2026-05-10) — l'investigation live SSH du
    # 2026-05-11 a établi que le prototype antérieur exposait 6 kinds producteurs (sans `killed`).
    # Le kind dit ce que l'atome PRÉTEND être ; c'est lui qui fixe le seuil de
    # confiance exigé et la façon dont le rappel le pondère.
    DECISION = "decision"            # décision prise — rationale obligatoire (RATIONALE_REQUIRED_KINDS)
    PATTERN = "pattern"              # pattern réutilisable détecté
    GOTCHA = "gotcha"                # piège rencontré et résolu
    STATE = "state"                  # état courant d'un module/projet (snapshot)
    TODO = "todo"                    # tâche à faire
    NOTE = "note"                    # note libre sans catégorie plus précise

    # --- Producteurs extensions ARAC par rapport au prototype antérieur (6) ---
    KILLED = "killed"                # décision/atome explicitement abandonné — extension ARAC (recatégorisé Phase 2.7)
    IDEA = "idea"                    # idée brute à explorer
    INSIGHT = "insight"              # apprentissage profond, prise de conscience
    QUESTION = "question"            # question ouverte à creuser
    REFERENCE = "reference"          # URL/livre/podcast/contact externe gardé en contexte
    AGENT_MESSAGE = "agent_message"  # message inter-agent (triade Phase B+) — trigger PG NOTIFY si source_ref.to présent

    # --- Producteurs extension triade Phase D (3) ---
    MISSION_PROPOSAL = "mission_proposal"  # orchestrator propose une mission avant verdict auditeur — Phase D
    MISSION = "mission"                    # proposal validée par l'auditeur, dispatchable au developer — Phase D
    DELIVERY = "delivery"                  # livrable developer post-mission (PR, fichier, commit hash) — Phase D.5

    # --- Producteur import gouverné V1.6B (1) ---
    IMPORTED_CONVERSATION_SUMMARY = "imported_conversation_summary"  # résumé redacted d'une conversation importée (pipeline incoming → human approval), migration 0011 — V1.6B 2026-06-11

    # --- Auditeurs (4) — agents autonomes ou validations interactives ---
    ALERT = "alert"                  # signale un risque ou une anomalie
    VALIDATION = "validation"        # confirme la cohérence d'un atome existant
    CONTRADICTION = "contradiction"  # détecte contradiction entre 2 atomes
    SUGGESTION = "suggestion"        # propose amélioration / atome dérivé


# ----------------------------------------------------------------------------
# Sous-ensembles utiles pour la logique métier (single source of truth).
# Toute logique métier qui filtre par "type de kind" doit utiliser ces
# frozenset plutôt que ré-énumérer en local — cohérence garantie si la liste
# évolue.
# ----------------------------------------------------------------------------

PRODUCER_KINDS: frozenset[Kind] = frozenset({
    Kind.DECISION,
    Kind.PATTERN,
    Kind.GOTCHA,
    Kind.STATE,
    Kind.TODO,
    Kind.KILLED,
    Kind.NOTE,
    Kind.IDEA,
    Kind.INSIGHT,
    Kind.QUESTION,
    Kind.REFERENCE,
    Kind.AGENT_MESSAGE,
    Kind.MISSION_PROPOSAL,
    Kind.MISSION,
    Kind.DELIVERY,
    Kind.IMPORTED_CONVERSATION_SUMMARY,
})

AUDITOR_KINDS: frozenset[Kind] = frozenset({
    Kind.ALERT,
    Kind.VALIDATION,
    Kind.CONTRADICTION,
    Kind.SUGGESTION,
})

# Kinds qui REQUIÈRENT un `rationale` non vide à la création.
# Règle applicative (pas DDL — la BDD n'a pas de contrainte sur rationale
# par kind). Validation côté Pydantic / app logic dans atom.py.
# Stack v2 §2.4 : "rationale TEXT — pourquoi (obligatoire pour decision via app logic)".
RATIONALE_REQUIRED_KINDS: frozenset[Kind] = frozenset({
    Kind.DECISION,
})

# Ordre canonique des kinds pour tri ordinal et walk des buckets (Phase 4).
# Producteurs hérités du prototype antérieur les plus structurants en premier (decisions →
# patterns → gotchas → states), puis extensions ARAC dans l'ordre de poids
# cognitif décroissant (insights > references > questions > todos > notes >
# ideas > killed), puis kinds auditeurs en queue (alert > validation >
# contradiction > suggestion). Utilisé par :
#   - foundations() : tri ordinal des pierres-angulaires (CASE WHEN SQL)
#   - context_for() : ordre de walk des buckets pour stabilité de réponse
KIND_ORDER: list[Kind] = [
    # Producteurs hérités du prototype antérieur
    Kind.DECISION,
    Kind.PATTERN,
    Kind.GOTCHA,
    Kind.STATE,
    # Extensions ARAC (producteurs)
    Kind.INSIGHT,
    Kind.REFERENCE,
    Kind.QUESTION,
    Kind.TODO,
    Kind.NOTE,
    Kind.IDEA,
    Kind.KILLED,
    Kind.MISSION_PROPOSAL,  # triade Phase D — proposition orchestrator avant verdict auditeur (poids doctrinal modéré)
    Kind.MISSION,           # triade Phase D — proposal validée, dispatchable developer
    Kind.DELIVERY,          # triade Phase D.5 — livrable developer post-mission (artefact de bouclage)
    Kind.AGENT_MESSAGE,  # opérationnel triade — trié en queue producteurs (faible poids cognitif, éligible soft-delete 30j)
    Kind.IMPORTED_CONVERSATION_SUMMARY,  # import gouverné V1.6B — empreinte/résumé redacted, faible poids tant que non sémantisé (V1.6C)
    # Auditeurs
    Kind.ALERT,
    Kind.VALIDATION,
    Kind.CONTRADICTION,
    Kind.SUGGESTION,
]


# ----------------------------------------------------------------------------
# Sentinelles assert au chargement — garde-fous contre régression silencieuse
# ----------------------------------------------------------------------------

assert len(Kind) == 20, f"Kind enum doit avoir 20 membres, trouvé {len(Kind)}"
assert len(KIND_ORDER) == 20, f"KIND_ORDER doit couvrir 20 kinds, trouvé {len(KIND_ORDER)}"
assert set(KIND_ORDER) == set(Kind), \
    "KIND_ORDER doit couvrir l'intégralité des kinds (aucun manquant, aucun en doublon)"
assert len(PRODUCER_KINDS) == 16, f"PRODUCER_KINDS doit avoir 16 membres, trouvé {len(PRODUCER_KINDS)}"
assert len(AUDITOR_KINDS) == 4, f"AUDITOR_KINDS doit avoir 4 membres, trouvé {len(AUDITOR_KINDS)}"
assert PRODUCER_KINDS | AUDITOR_KINDS == set(Kind), \
    "PRODUCER_KINDS ∪ AUDITOR_KINDS doit couvrir l'intégralité de Kind"
assert PRODUCER_KINDS & AUDITOR_KINDS == frozenset(), \
    "PRODUCER_KINDS et AUDITOR_KINDS doivent être disjoints (un kind ne peut être les deux)"
assert RATIONALE_REQUIRED_KINDS <= PRODUCER_KINDS, \
    "RATIONALE_REQUIRED_KINDS doit être un sous-ensemble de PRODUCER_KINDS"
