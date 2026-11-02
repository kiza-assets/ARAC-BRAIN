"""Construction du PACK cortex — un lot multi-conversations ≤ budget.

Le pack est la matière d'UN spawn : les conversations éligibles (gate v2,
INCHANGÉ) y entrent chacune pour AU PLUS UNE tranche `[cursor+1 .. max_id]`
bornée par le budget de tokens restant. Une conversation-monstre avance donc
d'une tranche par cycle circadien — le plafond d'âge du gate garantit qu'elle
revient, jamais qu'elle explose le budget.

`presented` (retourné) est LA source de vérité de l'avance des curseurs :
le disposant n'avance jamais au-delà de ce qui a été montré — quoi que
prétende le LLM.

Sémantique de troncature CONSERVATRICE (remplace l'ancienne
troncature-marquée) — un message de tête (premier message non curé d'une
conversation) qui ne tient pas dans le budget restant du cycle a deux issues,
JAMAIS une troncature :
  - il tient dans le budget PLEIN (`budget_tokens`) : REPORT — le message
    n'est pas inclus, la conversation sort du pack CE cycle (tranche vide),
    curseur inchangé -> elle repasse en tête au prochain cycle avec un budget
    frais (compteur `messages_reported`) ;
  - il ne tient même pas dans le budget PLEIN : BLOCAGE fail-closed — la
    conversation est exclue, curseur gelé, le détail atterrit dans
    `oversized_messages` (le caller poste l'alerte + la review-queue).
`messages_truncated` reste à 0 pour toujours (INV-7 : aucun id présenté à
moitié n'entre jamais dans `presented[uid].max_id`).

VOIE DE FRAÎCHEUR (env `ARAC_PACK_RECENCY_SLOTS`, défaut 0 = OFF =
comportement bit-identique) : N places du pack réservées aux conversations
RÉCENTES **de l'utilisateur** ; toutes les autres places gardent l'ordre actuel
(oldest-content-first du gate + round-robin par source).
Réordonnancement PUR de la liste de candidats — gate SQL, prédicat,
curseurs, budget et caps INTOUCHÉS. Trois garanties, chacune démontrée dans
`_apply_recency_lane` : anti-famine par clamp `N <= places - 1`, budget par
garde de taille (`ARAC_PACK_RECENCY_MAX_MSGS`), pertinence par garde de
provenance (`ARAC_PACK_RECENCY_SOURCES`).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

from agents.lib import curator_lib_v2
from agents.lib.token_count import count_tokens
from app.journal import raison

logger = logging.getLogger("arac.cortex.pack")

# Budget INPUT du pack (tokens estimés, tiktoken) — sous le budget/run existant.
DEFAULT_PACK_TOKEN_BUDGET = 80_000
# Borne DURE du budget pack surchargé par env.
# Le spend_guard REFUSE le spawn si est_input > max_tokens_per_run (150 000,
# cycle.py `before_spawn`) -> un pack trop gros = slot BRÛLÉ (la fragilité
# rang 4 du drain-diagnostic), jamais un dépassement. La borne sûre doit donc
# garantir pack + OVERHEAD_MAX ≤ 150k, où l'overhead = system prompt +
# gabarit user + bloc known-atoms (les headers de conversation sont déjà
# décomptés DANS le budget pack). Overhead CHIFFRÉ (tiktoken, 2026-07-16) :
#   - mesuré prod (receipts 13 j)          : ~4 500 tok (in_tok 84,5k @ pack 80k)
#   - pire-cas réaliste (120 atomes pleins): ~9 700 tok
#   - pire-cas adversarial (texte à haute densité token, 120×140) : ~14 861 tok
# 135_000 = 150_000 − 15_000 (≥ pire-cas adversarial). Aucune valeur d'env,
# si grande soit-elle, ne peut dépasser ce plafond.
PACK_TOKEN_BUDGET_HARD_CAP = 135_000
# Nombre max de conversations examinées par cycle (le gate ordonne par famine).
DEFAULT_MAX_CONVERSATIONS = 20
# Atomes ALREADY-KNOWN injectés (lecture seule) : cap dur du bloc.
KNOWN_ATOMS_CAP = 120
KNOWN_VALUE_TRUNC = 140
# perf-loop — plafond du NOMBRE de conversations ADMISES par pack
# (env `ARAC_PACK_MAX_CONVS`, défaut 0 = illimité = bit-identique).
# DONNÉES (enquête quarantaines 2026-07-17, run_receipts 1-52) : par pack
# DISTINCT, 0 quarantaine foreign sur les packs à 3-5 convs (20 runs), contre
# 1/2 packs à 6 convs et 1/1 pack à 8 convs (2/2 tirs, runs 51+52) ; ère 95k
# (packs 8 convs) : 2 sorties LLM / 4 = 50 % quarantainées. Le mécanisme
# dominant (attribution croisée intra-pack) croît avec le nombre de tranches
# thématiquement voisines dans le même prompt. VALEUR RECOMMANDÉE AU
# DÉPLOIEMENT : 4 (plus grand nombre observé à 0 foreign avec volume — 4
# runs à 4 convs, 2 à 5 ; 3-4 = fourchette de l'enquête).
# GAIN ATTENDU CHIFFRÉ : quarantaines multi-conv -> ~0 ≈ récupération d'un
# slot/j ≈ +87 kt/j de digestion (fourchette +31 kt/j moyenne historique
# 14,6 j -> +174 kt/j les jours à pack toxique persistant, cf run 51/52 :
# 203 462 in_tok = 40,7 % du budget jour brûlés le 07-17).
RECOMMENDED_PACK_MAX_CONVS = 4
# perf-loop it.2 — SECOURS « géant de secours » (H-C). Seuil de
# `remaining` (tokens) au-delà duquel, APRÈS que `ARAC_PACK_MAX_CONVS` a rompu
# la boucle d'admission MONO-PASSE, on admet UNE conversation de secours = le
# plus gros delta non curé encore DISPONIBLE (rang >= cap+1, jamais examiné par
# la boucle). Env `ARAC_PACK_FILL_FLOOR`, défaut 0 = OFF = bit-identique it.1.
# DIAGNOSTIC (simulation par rejeu déterministe des run_receipts, 0 dépense
# LLM, 2026-07-17) : la boucle pack.py:304 est mono-passe ; le cap=4 s'arrête
# aux 4 convs de tête (oldest-content) et, quand elles se drainent court,
# ABANDONNE le budget restant sans jamais atteindre les géants aux rangs >=5.
# Run 53 (run_receipts id=53) : 4 têtes drainent 25,8 kt -> le cap rompt la
# boucle -> 68,7 kt de budget abandonnés, géants 41,8/22,9/22,0 kt jamais
# atteints.
# GAIN CHIFFRÉ (H-C @ seuil 40 kt, simulé fidèle — écart proxy/réel 4,9 % sur
# le run 53 décisif, ~1,5 % moyen sur 8 runs comparables) :
#   - run 53 : 25,8 -> 67,4 kt packés (+41,6 kt/slot) = 2,6x le contenu digéré
#     À COÛT LLM IDENTIQUE (1 spawn, même slot, budget/run 95k inchangé) ;
#   - moyenne 10 runs 44-53 : remplissage 67,7 -> 80,2 kt/slot (+12,5 / +18 %) ;
#   - famine >24h : BAISSE (run 53 : 4 -> 3), jamais ne monte — H-C est un
#     SUR-ENSEMBLE de it.1 : il AJOUTE, ne RETIRE jamais une conv de sa place
#     (anti-famine + équité entre sources préservées par construction) ;
#   - pool courant live (19 convs) : cap=4 remplit déjà 88,6 kt (reste 5,8 kt
#     < 40k) -> H-C NO-OP bit-identique (le seuil ne déclenche pas).
# SEUIL 40 kt : le `remaining` post-cap est BIMODAL — soit ~0-1,5 kt (pack
# déjà plein, aucun seuil ne déclenche = no-op), soit 68,7 kt (drained-short,
# 30/40/50k déclenchent identiquement). 40k = milieu robuste de la fenêtre
# [1,5 ; 68,7]. VALEUR RECOMMANDÉE AU DÉPLOIEMENT : 40 000. Le secours ajoute
# AU PLUS 1 conv (1 tranche) -> convs distinctes <= cap+1 (= 5 au cap=4
# recommandé, zone prouvée-sûre : 0 quarantaine foreign observée à <=5 convs,
# table contingence it.1). Guard foreign_message_ids (contract.py:427)
# INTOUCHÉ : H-C n'agit que sur l'ADMISSION, le rendu reste identique.
RECOMMENDED_PACK_FILL_FLOOR = 40_000
# VOIE DE FRAÎCHEUR — nombre de places du pack RÉSERVÉES au contenu
# le plus RÉCENT (env `ARAC_PACK_RECENCY_SLOTS`, défaut 0 = OFF = pack
# bit-identique). Le gate sert la file du contenu le plus ANCIEN au plus
# récent (`ORDER BY min(COALESCE(msg_created_at, received_at))`, anti-famine)
# + round-robin par source : c'est le bon ordre pour RATTRAPER un
# backlog, et le pire pour ABSORBER ce que l'utilisateur vient de dire.
# MESURE PROD (2026-07-26) : 101 conversations en attente (93 desktop_chat,
# 8 claude_code) ; les 4 conversations du jour occupent les rangs 87, 89, 90
# et 91 de la file desktop ; débit observé ~4 conversations/jour (1 à 7 sur
# 6 jours) -> ~3 SEMAINES avant que le cerveau n'absorbe la matière du jour.
# Pour un cerveau censé « reprendre un projet sans réexplication », absorber
# en DERNIER ce qui vient d'être discuté est un défaut de conception, pas un
# détail d'ordonnancement.
# La voie de fraîcheur est un RÉORDONNANCEMENT PUR de la liste de candidats
# (même nature que `_interleave_by_source` : gate SQL, prédicat, curseurs,
# caps et budget INTOUCHÉS) — cf `_apply_recency_lane` pour la preuve que
# l'anti-famine survit.
# VALEUR RECOMMANDÉE AU DÉPLOIEMENT : 1. Le pack n'admet que quelques
# conversations par cycle (`ARAC_PACK_MAX_CONVS` recommandé à 4) : 1 place
# suffit à rendre le cerveau réactif (le contenu du jour entre au cycle
# suivant, soit <= 8 h) tout en laissant 3 places au rattrapage historique
# (~-25 % de débit de rattrapage, ~4 -> ~3 conversations/jour). 2 double la
# réactivité les jours à forte activité et coûte une place de plus.
RECOMMENDED_PACK_RECENCY_SLOTS = 1
# correctif round-1 (défaut RÉEL du premier armement, mesuré en prod
# 2026-07-26 AVANT le premier cycle) : la fraîcheur SEULE est un mauvais
# critère. Le classement par date servait en rang 1 une conversation
# `claude_code` de 24 752 messages non curés — le transcript d'une session
# d'agent. Trois défauts d'un coup :
#   (a) BUDGET : elle absorbe tout le budget tokens du cycle (risque n°1 de la
#       revue initiale, réalisé dès le premier tir) ;
#   (b) DOCTRINE : c'est du trafic MACHINE, pas votre connaissance —
#       `agent_message` n'est pas de la mémoire durable ;
#   (c) PRODUIT : les conversations réellement visées restaient bloquées.
# LE PRINCIPE QUI TRANCHE : une conversation récente ne mérite pas seulement
# d'être digérée plus vite — elle mérite d'être PRIORITAIRE, parce qu'elle
# correspond à ce que vous avez actuellement en tête. Or un transcript d'agent
# n'est dans la tête de personne. La fraîcheur est donc pondérée par la
# PROVENANCE (humaine) et BORNÉE en TAILLE. Les deux gardes filtrent le vivier
# AVANT le choix des N plus récentes ; une conversation écartée n'est jamais
# pénalisée : elle reste servie par la voie historique, à sa place.
# Garde de TAILLE (env `ARAC_PACK_RECENCY_MAX_MSGS`) : delta non curé au-delà
# du seuil -> inéligible à la voie. 200 messages = ~2 ordres de grandeur
# au-dessus d'une conversation de travail humaine mesurée (2 à 29 messages sur
# les 8 conversations de tête du corpus de calibration) et ~2 ordres de
# grandeur SOUS le transcript d'agent (24 752) : le seuil sépare les deux
# populations avec une marge énorme, il n'a pas besoin d'être fin.
# 0 = garde désactivée (toutes tailles éligibles).
DEFAULT_RECENCY_MAX_MSGS = 200
# Garde de PROVENANCE (env `ARAC_PACK_RECENCY_SOURCES`, liste séparée par des
# virgules) : seuls ces `source_type` peuvent occuper une place fraîche.
# Défaut `desktop_chat` = les conversations que vous tenez VOUS-MÊME (93 des
# 101 en attente sur le corpus de calibration). `claude_code`/self-capture
# restent servis par la
# voie historique — jamais exclus du cerveau, seulement de la PRIORITÉ.
# Valeur explicitement VIDE (`ARAC_PACK_RECENCY_SOURCES=`) = aucune
# restriction de source (échappatoire documentée, pas le défaut).
DEFAULT_RECENCY_SOURCES = ("desktop_chat",)
# Garde de VOLUME (env `ARAC_PACK_RECENCY_MAX_TOKENS`, correctif round-2) :
# tokens estimés du delta non curé au-delà desquels une conversation n'est pas
# promue. Elle s'AJOUTE à la garde en messages, elle ne la remplace pas : la
# garde en messages ferme « beaucoup de messages » (transcript d'agent), celle
# en tokens ferme « peu de messages, énormes » (logs collés) — le seul cas que
# le compte de messages laissait passer. C'est la grandeur que le budget
# dépense réellement, donc la garde qui ferme VRAIMENT le risque « la place
# fraîche mange le cycle ».
# VALEUR 20 000, justification par les budgets réels :
#   - budget pack par défaut 80 000 -> la place fraîche est plafonnée à 25 % ;
#   - budget pack déployé 95 000    -> 21 % ;
#   - plafond dur 135 000           -> 15 % ;
#   - plafond spend_guard/run 150 000 (`ARAC_MAX_TOKENS_PER_RUN`) -> 13 %.
# Dans TOUS les cas >= 3/4 du budget du cycle restent au rattrapage historique
# — la place fraîche ne peut jamais, à elle seule, emporter l'essentiel du
# cycle. Marge produit : les conversations visées mesurent 2 à 29 messages
# ; 20 000 tokens = ~5 000 tokens par message
# sur une conversation de 4 messages, ~1 250 sur une de 16 — deux ordres de
# grandeur au-dessus d'un échange de travail normal. Le seuil ne mord donc que
# sur du contenu anormalement volumineux, ce qui est exactement son objet.
# 0 = garde désactivée.
DEFAULT_RECENCY_MAX_TOKENS = 20_000
# Nombre MAXIMUM d'estimations de volume par cycle (la garde en tokens exige
# de lire le delta ; les gardes bon marché ne le demandent jamais). Le
# balayage étant paresseux et ordonné, le cas nominal en consomme UNE
# (N=1, première du vivier admise). Ce plafond ne mord que sur un vivier
# pathologique — où renoncer (voie inerte) est la bonne réponse.
RECENCY_TOKEN_SCAN_MAX_CONVS = 8
# Fenêtre de candidats élargie pour l'équité par source (fix round-1) :
# le round-robin appliqué APRÈS `LIMIT max_conversations` est l'IDENTITÉ sur
# une fenêtre mono-source (prouvé par exécution) — la famine mac persiste
# tant que >= 20 conversations d'une AUTRE source dominent l'ordre
# oldest-content du gate.
# Flag ON, le SELECT (gate SQL INCHANGÉ, seul le paramètre LIMIT varie) lit
# une fenêtre plus large, l'interleave s'applique, puis la liste est TRONQUÉE
# à `max_conversations` (bisection anti-poison respectée). 200 couvre
# largement l'état mesuré (28 conversations en attente d'un côté, 208 de
# l'autre).
DEFAULT_FAIR_WINDOW = 200


def _env_flag(name: str) -> bool:
    """Flag d'armement par ENV PUR (pattern shadow projet) : lu à
    CHAQUE appel (jamais figé à l'import) -> armement/désarmement au
    déploiement systemd sans redéploiement de code. Défaut OFF."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _fair_window() -> int:
    """Taille de la fenêtre de candidats lue quand `ARAC_PACK_SOURCE_FAIR`
    est armé (env `ARAC_PACK_FAIR_WINDOW`, défaut `DEFAULT_FAIR_WINDOW`) —
    fail-safe : valeur illisible -> défaut, jamais un crash de cycle."""
    try:
        val = int(os.environ.get("ARAC_PACK_FAIR_WINDOW", "") or DEFAULT_FAIR_WINDOW)
    except ValueError:
        return DEFAULT_FAIR_WINDOW
    return max(1, val)


def _pack_token_budget() -> int:
    """Budget tokens du pack, surchargeable par ENV PUR (
    `ARAC_PACK_TOKEN_BUDGET`) — miroir du pattern `_fair_window` : lu à
    CHAQUE build (jamais figé à l'import) -> re-calibrage au déploiement
    systemd sans redéploiement de code. Défaut = `DEFAULT_PACK_TOKEN_BUDGET`
    (80 000, comportement bit-identique sans env).

    Fail-safe : valeur illisible ou <= 0 -> défaut + WARNING, jamais un
    crash de cycle. Borne dure : `min(env, PACK_TOKEN_BUDGET_HARD_CAP)` —
    le cap spend_guard 150k/run reste infranchissable avec marge (cf
    commentaire de la constante)."""
    raw = os.environ.get("ARAC_PACK_TOKEN_BUDGET", "").strip()
    if not raw:
        return DEFAULT_PACK_TOKEN_BUDGET
    try:
        val = int(raw)
    except ValueError:
        logger.warning(
            "ARAC_PACK_TOKEN_BUDGET invalide (%r) — fallback défaut %d",
            raw, DEFAULT_PACK_TOKEN_BUDGET)
        return DEFAULT_PACK_TOKEN_BUDGET
    if val <= 0:
        logger.warning(
            "ARAC_PACK_TOKEN_BUDGET <= 0 (%d) — fallback défaut %d",
            val, DEFAULT_PACK_TOKEN_BUDGET)
        return DEFAULT_PACK_TOKEN_BUDGET
    # Clamp dur : env > plafond -> plafond (marge sous le cap spend_guard).
    return min(val, PACK_TOKEN_BUDGET_HARD_CAP)


def _pack_max_convs() -> int:
    """Plafond de conversations ADMISES par pack (env `ARAC_PACK_MAX_CONVS`,
    build (jamais figé à l'import), miroir du pattern
    `_pack_token_budget`. 0 (défaut) = illimité = comportement bit-identique.
    Fail-safe : valeur illisible ou négative -> 0 + WARNING, jamais un crash
    de cycle."""
    raw = os.environ.get("ARAC_PACK_MAX_CONVS", "").strip()
    if not raw:
        return 0
    try:
        val = int(raw)
    except ValueError:
        logger.warning(
            "ARAC_PACK_MAX_CONVS invalide (%r) — fallback 0 (illimité)", raw)
        return 0
    if val < 0:
        logger.warning(
            "ARAC_PACK_MAX_CONVS négatif (%d) — fallback 0 (illimité)", val)
        return 0
    return val


def _pack_fill_floor() -> int:
    """Seuil de `remaining` (tokens) déclenchant le géant de secours
    (env `ARAC_PACK_FILL_FLOOR`) — lu à CHAQUE build (jamais figé à l'import),
    miroir du pattern `_pack_max_convs`. 0 (défaut) = OFF = aucun secours =
    comportement bit-identique it.1. Fail-safe : valeur illisible ou négative
    -> 0 + WARNING, jamais un crash de cycle."""
    raw = os.environ.get("ARAC_PACK_FILL_FLOOR", "").strip()
    if not raw:
        return 0
    try:
        val = int(raw)
    except ValueError:
        logger.warning(
            "ARAC_PACK_FILL_FLOOR invalide (%r) — fallback 0 (OFF)", raw)
        return 0
    if val < 0:
        logger.warning(
            "ARAC_PACK_FILL_FLOOR négatif (%d) — fallback 0 (OFF)", val)
        return 0
    return val


def _pack_recency_slots() -> int:
    """Places du pack réservées au contenu le plus RÉCENT (env
    `ARAC_PACK_RECENCY_SLOTS`) — lu à CHAQUE build (jamais figé à
    l'import), miroir du pattern `_pack_max_convs`. 0 (défaut) = voie de
    fraîcheur ÉTEINTE = comportement bit-identique (aucune requête
    supplémentaire, aucun réordonnancement). Fail-safe : valeur illisible ou
    négative -> 0 + WARNING, jamais un crash de cycle."""
    raw = os.environ.get("ARAC_PACK_RECENCY_SLOTS", "").strip()
    if not raw:
        return 0
    try:
        val = int(raw)
    except ValueError:
        logger.warning(
            "ARAC_PACK_RECENCY_SLOTS invalide (%r) — fallback 0 (OFF)", raw)
        return 0
    if val < 0:
        logger.warning(
            "ARAC_PACK_RECENCY_SLOTS négatif (%d) — fallback 0 (OFF)", val)
        return 0
    return val


def _pack_recency_max_msgs() -> int:
    """Garde de TAILLE de la voie de fraîcheur (env
    `ARAC_PACK_RECENCY_MAX_MSGS`, correctif round-1): nombre MAXIMUM de
    messages non curés qu'une conversation peut avoir pour prétendre à une
    place fraîche. Défaut `DEFAULT_RECENCY_MAX_MSGS` (200) — le défaut est
    PROTECTEUR, pas neutre : la voie n'est jamais armée sans garde.
    0 = garde désactivée. Fail-safe : valeur illisible ou négative -> défaut
    + WARNING (on ne dégrade JAMAIS vers « aucune garde »)."""
    raw = os.environ.get("ARAC_PACK_RECENCY_MAX_MSGS", "").strip()
    if not raw:
        return DEFAULT_RECENCY_MAX_MSGS
    try:
        val = int(raw)
    except ValueError:
        logger.warning(
            "ARAC_PACK_RECENCY_MAX_MSGS invalide (%r) — fallback défaut %d",
            raw, DEFAULT_RECENCY_MAX_MSGS)
        return DEFAULT_RECENCY_MAX_MSGS
    if val < 0:
        logger.warning(
            "ARAC_PACK_RECENCY_MAX_MSGS négatif (%d) — fallback défaut %d",
            val, DEFAULT_RECENCY_MAX_MSGS)
        return DEFAULT_RECENCY_MAX_MSGS
    return val


def _pack_recency_max_tokens() -> int:
    """Garde de VOLUME de la voie de fraîcheur (env
    `ARAC_PACK_RECENCY_MAX_TOKENS`, correctif round-2): tokens estimés
    maximum du delta non curé pour prétendre à une place fraîche. Défaut
    `DEFAULT_RECENCY_MAX_TOKENS` (20 000) — PROTECTEUR sans qu'aucune variable
    ne soit posée en prod. 0 = garde désactivée. Fail-safe ORIENTÉ : valeur
    illisible ou négative -> défaut + WARNING, JAMAIS « aucune garde »."""
    raw = os.environ.get("ARAC_PACK_RECENCY_MAX_TOKENS", "").strip()
    if not raw:
        return DEFAULT_RECENCY_MAX_TOKENS
    try:
        val = int(raw)
    except ValueError:
        logger.warning(
            "ARAC_PACK_RECENCY_MAX_TOKENS invalide (%r) — fallback défaut %d",
            raw, DEFAULT_RECENCY_MAX_TOKENS)
        return DEFAULT_RECENCY_MAX_TOKENS
    if val < 0:
        logger.warning(
            "ARAC_PACK_RECENCY_MAX_TOKENS négatif (%d) — fallback défaut %d",
            val, DEFAULT_RECENCY_MAX_TOKENS)
        return DEFAULT_RECENCY_MAX_TOKENS
    return val


def _pack_recency_sources() -> frozenset[str]:
    """Garde de PROVENANCE de la voie de fraîcheur (env
    `ARAC_PACK_RECENCY_SOURCES`, correctif round-1): `source_type`
    admis à occuper une place fraîche. Défaut `DEFAULT_RECENCY_SOURCES`
    (`desktop_chat`).

    Variable ABSENTE -> défaut protecteur. Variable PRÉSENTE mais vide (ou ne
    contenant que des séparateurs) -> ensemble VIDE = aucune restriction de
    source : c'est l'échappatoire explicite, elle exige un geste délibéré
    d'exploitation (on ne peut pas y tomber par accident, contrairement à un
    défaut lu comme chaîne vide)."""
    raw = os.environ.get("ARAC_PACK_RECENCY_SOURCES")
    if raw is None:
        return frozenset(DEFAULT_RECENCY_SOURCES)
    return frozenset(part.strip().lower() for part in raw.split(",")
                     if part.strip())


def _strict_trunc_notice(last_id: int) -> str:
    """avis de troncature rendu SOUS `ARAC_PACK_STRICT_BOUNDARIES`
    quand la tranche est coupée au budget en plein flux. Cible le mécanisme
    (b) de l'enquête quarantaines : extrapolation d'id au bord de tranche
    (runs 12 et 20 — citation de `max_id+1` sur un géant tronqué sans
    marquage : 28456 halluciné, 66260 existant mais non rendu). Rendu pur,
    le guard contract.py reste INTOUCHÉ."""
    return (f"[TRANCHE COUPÉE AU BUDGET après id={last_id} : la suite de cette "
            "conversation existe mais N'EST PAS affichée — ne cite JAMAIS un id "
            "non affiché ci-dessus]")


def _is_empty_like_gate(content: Any) -> bool:
    """Prédicat « message vide » ALIGNÉ MOT-POUR-MOT sur le gate SQL
    (`btrim(m.content) <> ''` — fix round-1, finding livelock whitespace) :
    `btrim(text)` PostgreSQL ne retire QUE les espaces (0x20), là où
    `str.strip()` Python retire TOUT whitespace (\\n, \\t, nbsp…). Un delta
    « non vide » au sens SQL mais whitespace-only au sens Python rendait la
    conversation éligible à CHAQUE cycle sans JAMAIS être présentée
    (tranche=[], ni omission ni receipt : épinglage perpétuel d'un slot,
    curseur figé à vie). Le même prédicat des deux côtés ferme le livelock :
    tout message que le gate compte comme non-vide EST rendu."""
    return str(content or "").strip(" ") == ""


def _interleave_by_source(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """round-robin PAR SOURCE, gate SQL INCHANGÉ.

    Le tri anti-famine du gate (`ORDER BY min(COALESCE(msg_created_at,
    received_at))`) + un backfill massif de contenu ancien (cohorte
    d'une seule source) = head-of-line blocking : cette source monopolise la
    tête du pack et affame toutes les autres (208 conversations en attente,
    toutes retry_count=0 — victimes pures d'ordonnancement).

    Réordonnancement PUR de la liste `candidates` (≤ max_conversations
    éléments, aucune écriture, prédicat du gate intouché) :
      - groupes par (source_type, node_id), dans l'ordre de PREMIÈRE
        apparition dans l'ordre du gate (la source la plus affamée ouvre
        le bal) ;
      - interleave round-robin : 1 conversation de chaque source par tour ;
      - INTRA-source, l'ordre du gate est CONSERVÉ (oldest-content-first)
        -> l'aging anti-famine du gate continue de s'appliquer à
        l'intérieur de chaque source, aucune famine intra-source.

    Future-proof : cape mécaniquement la part d'une source par cycle — un
    futur backfill (desktop) ne peut plus re-monopoliser la tête.
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    order: list[tuple[str, str]] = []
    for conv in candidates:
        key = (str(conv.get("source_type")), str(conv.get("node_id")))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(conv)
    out: list[dict[str, Any]] = []
    round_idx = 0
    while len(out) < len(candidates):
        for key in order:
            grp = groups[key]
            if round_idx < len(grp):
                out.append(grp[round_idx])
        round_idx += 1
    return out


async def _recency_by_conversation(db, conv_ids: list[str]) -> dict[str, Any]:
    """Date du message NON CURÉ le PLUS RÉCENT **et TAILLE du delta**, par
    conversation -> `{conversation_id: {"newest": ts, "n_msgs": int}}`.

    Lecture seule stricte, UNE requête, appelée UNIQUEMENT quand la voie de
    fraîcheur est armée -> flag OFF, ce chemin n'existe pas (zéro requête
    supplémentaire, zéro nouveau mode de panne).

    L'expression de date est le MIROIR EXACT de celle du gate
    (`COALESCE(m.msg_created_at, m.received_at)` sur le delta non curé,
    `m.id > c.curated_through_message_id`) : le gate en prend le `min`
    (ancienneté du delta = anti-famine), la voie de fraîcheur en prend le
    `max` (nouveauté du delta). Aucun prédicat d'éligibilité n'est ré-écrit
    ici — les conversations passées en argument SORTENT DÉJÀ du gate, donc
    aucune duplication de prédicat, donc aucune dérive possible avec lui.

    `n_msgs` (= `count(*)` sur le MÊME delta, donc gratuit : la ligne est
    déjà agrégée) alimente la garde de taille — c'est la mesure exacte de ce
    que la conversation coûterait au budget si elle occupait la place
    fraîche.

    Le filtre du delta est porté par le JOIN (et non par un `FILTER (WHERE …)`
    comme dans le gate) : strictement équivalent sur `max`, mais range-scan
    sur `idx_rawmsg_conv_id (conversation_id, id)` au lieu d'un parcours de
    tous les messages de la conversation — une conversation-monstre déjà
    curée à 99 % ne coûte plus rien. Le `c.id::text = ANY(...)` renonce
    volontairement à l'index PK sur `conversations` (table de quelques
    milliers de lignes, parcourue AU PLUS 3 fois par jour) au profit de la
    robustesse : aucune valeur d'`id` ne peut faire échouer un cast.
    """
    if not conv_ids:
        return {}
    sql = (
        "SELECT c.id::text, "
        "       max(COALESCE(m.msg_created_at, m.received_at)), "
        "       count(*) "
        "FROM arac.conversations c "
        "JOIN arac.raw_messages m "
        "  ON m.conversation_id = c.id "
        " AND m.id > c.curated_through_message_id "
        "WHERE c.id::text = ANY(%s) "
        "GROUP BY c.id"
    )
    async with db.cursor() as cur:
        await cur.execute(sql, (list(conv_ids),))
        rows = await cur.fetchall()
    return {str(r[0]): {"newest": r[1], "n_msgs": int(r[2])}
            for r in rows if r[1] is not None}


def _recency_eligible(
    conv: dict[str, Any],
    stats: dict[str, Any] | None,
    *,
    max_msgs: int,
    sources: frozenset[str],
) -> bool:
    """Prédicat d'ADMISSION à la voie de fraîcheur (correctif round-1),
    appliqué AVANT tout classement par date. Trois conditions, toutes
    fail-closed (le doute exclut de la voie, jamais du cerveau) :

      - date CONNUE : sans `newest`, on ne sait pas dater -> pas de promotion ;
      - PROVENANCE : `source_type` dans `sources` (défaut `desktop_chat` = ce
        que l'utilisateur dit LUI-MÊME). `sources` vide = aucune restriction ;
      - TAILLE : delta non curé <= `max_msgs` (défaut 200). C'est la garde qui
        interdit qu'une place fraîche soit un gouffre à budget — cas mesuré :
        transcript d'agent à 24 752 messages non curés.

    Une conversation écartée n'est ni pénalisée ni exclue : elle reste dans la
    file du gate, à son rang, servie par la voie historique.
    """
    if not stats or stats.get("newest") is None:
        return False
    if sources and str(conv.get("source_type", "")).lower() not in sources:
        return False
    if max_msgs and int(stats.get("n_msgs") or 0) > max_msgs:
        return False
    return True


def _recency_pool(
    window: list[dict[str, Any]],
    recency: dict[str, Any],
    *,
    max_msgs: int,
    sources: frozenset[str],
) -> list[dict[str, Any]]:
    """VIVIER de la voie de fraîcheur: les conversations de `window`
    admises par les gardes BON MARCHÉ (date connue, provenance, taille en
    messages — toutes lisibles dans l'agrégat déjà calculé, aucun accès aux
    contenus), triées de la PLUS RÉCENTE à la plus ancienne.

    C'est exactement l'ordre dans lequel la voie servira les conversations,
    un cycle après l'autre. Fonction PURE (aucune I/O) : c'est elle qu'on
    rejoue pour simuler une file réelle sans toucher à la base.

    `reverse=True` conserve la stabilité du tri (l'ordre relatif des ex aequo
    n'est PAS inversé, cf. doc CPython) -> à date identique, l'ordre du gate
    (oldest-content-first) départage.
    """
    pool = [c for c in window
            if _recency_eligible(c, recency.get(c["id"]),
                                 max_msgs=max_msgs, sources=sources)]
    pool.sort(key=lambda c: recency[c["id"]]["newest"], reverse=True)
    return pool


async def _pick_recency_head(
    db,
    pool: list[dict[str, Any]],
    slots: int,
    *,
    max_tokens: int,
    max_msgs: int,
    count_fn: Callable[[str], int],
    drop_empty: bool,
) -> list[dict[str, Any]]:
    """correctif round-2 — sélection des `slots` conversations promues,
    avec la garde de VOLUME (`ARAC_PACK_RECENCY_MAX_TOKENS`).

    POURQUOI UNE TROISIÈME GARDE : la garde en messages ferme le cas mesuré
    (transcript d'agent, 24 752 messages) mais pas « peu de messages, énormes »
    — 10 messages de logs collés passent à 200 et peuvent encore absorber
    l'essentiel du budget du cycle. Le volume en TOKENS est la grandeur que le
    budget dépense réellement : c'est donc sur elle que porte la garde finale.

    MÊME COMPTEUR QUE LE BUDGET, PAS UNE SECONDE ESTIMATION : `_delta_tokens`
    est LA fonction que `build_pack` utilise déjà pour choisir le géant de
    secours, et elle appelle le `count_fn` du pack (tiktoken en prod)
    sur le rendu EXACT `_render_message`. Aucune heuristique parallèle (pas de
    `length(content)/4` en SQL) ne peut donc dériver du décompte réel.

    COÛT DE CALCUL BORNÉ, par trois mécanismes :
      1. la garde en tokens ne s'applique QU'AUX candidates déjà retenues par
         les gardes bon marché (date + provenance + messages) — en prod, 6
         conversations sur 101 ;
      2. le balayage est PARESSEUX et ORDONNÉ : on estime la plus récente,
         puis la suivante seulement si la précédente a été écartée, et on
         S'ARRÊTE dès que `slots` conversations sont retenues (N=1 -> une
         seule estimation dans le cas nominal) ;
      3. il est plafonné à `RECENCY_TOKEN_SCAN_MAX_CONVS` estimations par
         cycle : au-delà, la voie renonce (tête partielle ou vide = voie
         inerte), ce qui est la bonne réponse pour un vivier pathologique.
    De plus, chaque delta lu est borné : la garde en messages garantit
    <= `max_msgs` lignes. Quand elle est DÉSACTIVÉE (`max_msgs == 0`), le
    `limit` du fetch borne quand même la lecture, et une conversation dont le
    delta dépasse cette borne est écartée FAIL-CLOSED (on refuse de promouvoir
    ce qu'on n'a pas pu mesurer entièrement) — jamais un scan de 24 752 lignes.

    `max_tokens == 0` -> garde désactivée : aucun fetch, aucune estimation
    (la tête est simplement les `slots` premières du vivier).
    """
    if not max_tokens:
        return pool[:slots]
    # Borne de lecture : la garde en messages quand elle est armée, sinon son
    # défaut protecteur (la garde en tokens ne lit jamais plus que ce que la
    # garde en messages autoriserait).
    scan_cap = max_msgs if max_msgs else DEFAULT_RECENCY_MAX_MSGS
    head: list[dict[str, Any]] = []
    estimations = 0
    for conv in pool:
        if len(head) >= slots:
            break
        if estimations >= RECENCY_TOKEN_SCAN_MAX_CONVS:
            logger.warning(
                "voie de fraîcheur : %d estimations sans succès — balayage "
                "arrêté (vivier pathologique), voie inerte ce cycle",
                estimations)
            break
        rows = await curator_lib_v2.fetch_uncurated_messages(
            db, conv["id"], conv["cursor"], limit=scan_cap + 1)
        estimations += 1
        if len(rows) > scan_cap:
            # Delta plus long que ce qu'on accepte de mesurer -> non promue
            # (fail-closed). N'arrive QUE si la garde en messages est
            # désactivée : sinon `_recency_eligible` l'a déjà écartée.
            continue
        if _delta_tokens(rows, count_fn=count_fn, drop_empty=drop_empty) > max_tokens:
            continue
        head.append(conv)
    return head


def _merge_recency_head(
    candidates: list[dict[str, Any]],
    head: list[dict[str, Any]],
    max_conversations: int,
) -> list[dict[str, Any]]:
    """fusion PURE tête fraîche + file normale:

      - `head` vide (aucune éligible / toutes écartées par les gardes) -> la
        liste retournée est EXACTEMENT `candidates` : voie inerte ce cycle,
        jamais une erreur, jamais un blocage ;
      - la queue est `candidates` PRIVÉE des promues : l'ordre normal
        (oldest-content-first + round-robin) y est conservé À
        L'IDENTIQUE, et aucune conversation ne peut être servie deux fois
        (dédup par `id`, une seule liste retournée) ;
      - troncature à `max_conversations` : le nombre de conversations
        EXAMINÉES par cycle ne change pas (les caps `ARAC_PACK_MAX_CONVS` /
        budget / `ARAC_PACK_FILL_FLOOR` en aval voient la même taille de
        liste qu'aujourd'hui).
    """
    head_ids = {c["id"] for c in head}
    tail = [c for c in candidates if c["id"] not in head_ids]
    return (head + tail)[:max_conversations]


async def _apply_recency_lane(
    db,
    candidates: list[dict[str, Any]],
    window: list[dict[str, Any]],
    *,
    slots: int,
    max_conversations: int,
    max_convs: int,
    count_fn: Callable[[str], int],
    drop_empty: bool,
) -> list[dict[str, Any]]:
    """enveloppe FAIL-SAFE de la voie de fraîcheur: quoi qu'il
    arrive, elle rend une liste de candidats exploitable (au pire celle
    d'aujourd'hui, à l'identique). Jamais un crash de cycle pour un
    réordonnancement.

    POURQUOI L'ANTI-FAMINE SURVIT (c'est la raison d'être du tri du gate —
    trois arguments, du plus fort au plus faible) :

      1. Les places NON réservées gardent l'ordre EXACT d'aujourd'hui
         (oldest-content-first du gate + round-robin par source). La
         voie de fraîcheur ne RÉORDONNE PAS la file historique : elle lui
         retire au plus `slots` places de tête, sans jamais permuter deux de
         ses membres.
      2. `slots` est une CONSTANTE strictement inférieure au nombre de places
         du pack (clamp `min(slots, cap - 1)` ci-dessous, où `cap` est le
         plafond réel de conversations admises). Chaque cycle draine donc AU
         MOINS UNE conversation de la file historique : le débit de
         rattrapage reste strictement positif, donc toute conversation en
         attente finit par être servie — progrès GARANTI, pas seulement
         probable. Sans ce clamp, un flux continu de contenu frais pourrait
         occuper 100 % des places : c'est le seul scénario de famine que
         la voie introduit, et il est fermé par construction.
      3. La voie est AUTO-LIMITÉE et l'éviction est SANS PERTE : une
         conversation promue est curée, son curseur avance, elle quitte le
         pending (ou son delta rétrécit) — elle ne peut pas squatter la place
         fraîche. Une conversation évincée de la tête, elle, ne perd RIEN :
         curseur intouché, toujours éligible, et son rang au gate ne peut que
         REMONTER (le `min` de son delta est figé tant qu'elle n'est pas
         curée, alors que tout nouvel arrivant est plus jeune qu'elle).

    TROIS GARDES sur le VIVIER, appliquées AVANT le choix des N plus récentes,
    de la moins chère à la plus chère (les deux premières lisent l'agrégat
    déjà calculé, la troisième seule touche aux contenus — cf
    `_recency_eligible` puis `_pick_recency_head`) :
      - TAILLE (`ARAC_PACK_RECENCY_MAX_MSGS`, défaut 200 messages non curés) :
        ferme le risque « la place fraîche est un gouffre à budget ». Le
        clamp anti-famine ci-dessus protège les PLACES ; il ne protégeait PAS
        le BUDGET — une seule conversation-monstre en tête pouvait laisser les
        places historiques repartir vides. La garde de taille ferme ce trou en
        amont : une conversation-monstre n'entre jamais par la voie fraîche
        (elle reste servie normalement, tranche par tranche, par la voie
        historique + le secours).
      - PROVENANCE (`ARAC_PACK_RECENCY_SOURCES`, défaut `desktop_chat`) : la
        priorité va à ce que l'utilisateur a dit LUI-MÊME. « Récent » n'est pas
        le critère produit : le critère est « présent dans son esprit » — un
        transcript de session d'agent est récent sans être une pensée de
        personne, et l'ingérer en priorité pollue le cerveau
        (`agent_message` != mémoire durable).
      - VOLUME (`ARAC_PACK_RECENCY_MAX_TOKENS`, défaut 20 000 tokens estimés,
        correctif round-2) : ferme le cas que le compte de messages laissait
        passer — « peu de messages, énormes » (logs collés). Mesuré avec LE
        compteur du budget (`_delta_tokens` -> `count_fn` sur le rendu exact),
        jamais une seconde estimation. Plafonne la place fraîche à 25 % du
        budget pack par défaut, 21 % du budget déployé, 13 % du plafond
        spend_guard : >= 3/4 du cycle restent au rattrapage dans tous les cas.
    Vivier vide après gardes -> voie INERTE ce cycle (ordre du gate rendu tel
    quel), jamais une erreur.

    Deux propriétés de sûreté héritées, à ne pas confondre avec un
    contournement :
      - la voie NE CONTOURNE PAS le gate : une conversation promue a déjà
        satisfait le prédicat d'éligibilité (calme 2 h + 3 messages, ou
        plafond d'âge) -> jamais de curation d'une conversation encore en
        cours d'écriture ;
      - la voie n'est PAS l'équité par source : la tête est choisie sur la
        seule fraîcheur (la source la plus active gagne, c'est le but) ; le
        round-robin continue de gouverner toutes les autres places.

    Coût chiffré du réglage recommandé (cap 4, slots 1) : 3 places/cycle pour
    le rattrapage au lieu de 4 (~4 -> ~3 conversations/jour) contre un délai
    d'absorption du contenu du jour qui tombe de ~3 semaines à ~1 cycle.
    """
    # Plafond RÉEL de conversations admises par pack : `ARAC_PACK_MAX_CONVS`
    # s'il est armé, sinon la taille de la fenêtre examinée (elle-même
    # éventuellement réduite par la bisection anti-poison).
    cap = max_convs if max_convs else max_conversations
    effective = min(slots, cap - 1)
    if effective <= 0:
        # cap == 1 (bisection anti-poison en cours, ou cap volontairement
        # minimal) : réserver une place au frais reviendrait à réserver TOUTE
        # la place -> la file historique n'avancerait plus. On préfère la
        # garantie de progrès : voie inerte ce cycle.
        logger.warning(
            "ARAC_PACK_RECENCY_SLOTS=%d ignoré ce cycle (cap=%d) — au moins "
            "une place reste au rattrapage historique (anti-famine)",
            slots, cap)
        return candidates
    # Gardes (défauts PROTECTEURS: la voie n'est jamais armée sans
    # elles) — filtrent le vivier AVANT tout classement par date.
    max_msgs = _pack_recency_max_msgs()
    sources = _pack_recency_sources()
    max_tokens = _pack_recency_max_tokens()
    try:
        recency = await _recency_by_conversation(db, [c["id"] for c in window])
        pool = _recency_pool(window, recency, max_msgs=max_msgs, sources=sources)
        head = await _pick_recency_head(
            db, pool, effective, max_tokens=max_tokens, max_msgs=max_msgs,
            count_fn=count_fn, drop_empty=drop_empty)
    except TypeError as exc:  # dates non comparables (naïf vs aware)
        # Un échec de TRI n'avorte aucune transaction : pas de rollback.
        logger.warning(
            "voie de fraîcheur : dates incomparables (%s) — ordre du gate "
            "conservé", raison(exc))
        return candidates
    except Exception as exc:  # noqa: BLE001 — réordonnancement, jamais bloquant
        # Une requête en échec laisse la transaction psycopg AVORTÉE : sans
        # rollback, le PROCHAIN SELECT du pack crasserait le cycle entier
        # (mode de panne déjà rencontré sur le shadow value-gate, fix
        # round-1). Rollback GARDÉ, et sans danger ici : à ce point du cycle
        # rien n'a encore été écrit sur cette connexion (build_pack est une
        # construction en lectures seules, le premier commit est postérieur).
        logger.warning(
            "voie de fraîcheur : lecture échouée (%s) — ordre du gate "
            "conservé", type(exc).__name__)
        try:
            await db.rollback()
        except Exception as rexc:  # noqa: BLE001 — cf. ci-dessus (fail-closed)
            logger.warning(
                "voie de fraîcheur : rollback impossible (%s)",
                type(rexc).__name__)
        return candidates
    reordered = _merge_recency_head(candidates, head, max_conversations)
    # Observabilité (finding C5 : « flag armé » et « flag sans effet » doivent
    # être distinguables dans journald) — y compris « armé mais AUCUNE
    # éligible » (vivier vide) et « éligibles mais toutes trop volumineuses »
    # (pool > 0, tete = 0), qui sont des états normaux et non des pannes.
    # Compteurs et types de source UNIQUEMENT : aucun uid, aucun titre, aucun
    # contenu (PII-free, V0.107).
    head_before = {c["id"] for c in candidates[:effective]}
    promoted = [c for c in reordered[:effective]
                if c["id"] not in head_before]
    logger.info(
        "pack.recency_lane slots=%d fenetre=%d vivier=%d tete=%d promues=%d "
        "max_msgs=%d max_tokens=%d sources=%s types=%s",
        effective, len(window), len(pool), len(head), len(promoted),
        max_msgs, max_tokens, sorted(sources) or ["*"],
        sorted({str(c.get("source_type")) for c in head}))
    return reordered


def _render_message(m: dict[str, Any]) -> str:
    return f"[id={m['id']}] {m['role']}: {m['content']}"


def _delta_tokens(
    rows: list[dict[str, Any]],
    *,
    count_fn: Callable[[str], int],
    drop_empty: bool,
) -> int:
    """Taille (tokens) du CONTENU RENDABLE d'un delta, hors scaffold.

    UNE SEULE implémentation, partagée par les deux consommateurs qui doivent
    parler de la même grandeur que le budget du pack :
      - le choix du géant de secours (« plus gros delta dispo ») ;
      - la garde de volume de la voie de fraîcheur
        (`ARAC_PACK_RECENCY_MAX_TOKENS`).
    Elle applique le `count_fn` du pack (tiktoken en prod) au rendu EXACT
    `_render_message` — c'est-à-dire à la chaîne qui sera réellement facturée
    — et respecte `drop_empty` (un delta 100 % vide pèse 0). Toute estimation
    parallèle (ex. `length(content)/4` en SQL) est proscrite : elle dériverait
    du décompte réel. Pure (aucune écriture, aucun effet de bord)."""
    total = 0
    for m in rows:
        if drop_empty and _is_empty_like_gate(m["content"]):
            continue
        total += count_fn(_render_message(m))
    return total


async def build_pack(
    db,
    *,
    budget_tokens: int | None = None,
    max_conversations: int = DEFAULT_MAX_CONVERSATIONS,
    count_fn: Callable[[str], int] = count_tokens,
) -> dict[str, Any]:
    """Construit le pack du cycle.

    Retourne {"pack_meta": [...], "presented": {uid: {...}}, "conversations_block": str,
              "known_atoms_block": str, "est_tokens": int, "messages_reported": int,
              "messages_truncated": int (toujours 0), "oversized_messages": [...]} —
    pack vide si `pack_meta` est [] (le cycle sort en `empty`).

    `oversized_messages` : liste de {"uid", "message_id", "chars", "est_tokens"}
    pour chaque message de tête bloqué (> budget PLEIN, cf docstring module).
    Le caller (cycle.py) porte les effets de bord (alerte, review-queue) —
    ce module reste une construction pure (lectures seules).

    `budget_tokens=None` (le cas cycle.py) -> budget résolu par
    `_pack_token_budget()` (env `ARAC_PACK_TOKEN_BUDGET`, défaut 80k,
    clamp dur 135k) ; un budget explicite du caller garde la main.
    """
    if budget_tokens is None:
        budget_tokens = _pack_token_budget()
    # (flag OFF par défaut): équité par source APRÈS le
    # gate SQL (inchangé) — cf `_interleave_by_source`. Fix round-1 : la
    # fenêtre de candidats est ÉLARGIE (`_fair_window`, le LIMIT est un
    # paramètre du gate, jamais son prédicat) AVANT l'interleave, puis
    # tronquée à `max_conversations` — sans quoi l'interleave sur une fenêtre
    # mono-source est l'identité et la famine persiste (une source affamée à
    # un rang > max_conversations n'entrait jamais dans la fenêtre).
    source_fair = _env_flag("ARAC_PACK_SOURCE_FAIR")
    # voie de fraîcheur (défaut 0 = OFF = tout ce bloc est inerte).
    recency_slots = _pack_recency_slots()
    fetch_limit = max(max_conversations, _fair_window()) if source_fair \
        else max_conversations
    if recency_slots:
        # Les conversations les plus RÉCENTES sont, par construction du tri
        # du gate (oldest-content-first), les DERNIÈRES de la file : à
        # `LIMIT max_conversations` (20) sur 101 pending, elles ne sont
        # JAMAIS lues (rangs 87-91 mesurés). La fenêtre LUE est donc élargie
        # — le LIMIT est un PARAMÈTRE du gate, jamais son prédicat (même
        # mécanique que le fix round-1 de) — et bornée par le MÊME
        # réglage explicite `ARAC_PACK_FAIR_WINDOW` (défaut 200, ~2× le
        # backlog mesuré). Borne assumée : au-delà de la fenêtre, la voie
        # dégrade proprement (« la plus récente DE LA FENÊTRE »), jamais en
        # erreur.
        fetch_limit = max(fetch_limit, _fair_window())
    window = await curator_lib_v2.select_eligible_conversations(
        db, limit=fetch_limit)
    if source_fair:
        candidates = _interleave_by_source(window)[:max_conversations]
    else:
        # Voie de fraîcheur OFF : `window` compte DÉJÀ au plus
        # `max_conversations` lignes (LIMIT du gate) -> cette troncature est
        # l'IDENTITÉ (comportement historique bit-identique). Elle ne mord
        # QUE si la fenêtre a été élargie ci-dessus, et rend alors à la voie
        # normale EXACTEMENT ce qu'elle voyait avant : les
        # `max_conversations` premières de l'ordre du gate.
        candidates = window[:max_conversations]
    # pas 1 (flag OFF par défaut): exclure les messages VIDES
    # (btrim='') du RENDU. 81 % des messages du backlog sont vides (tool-use
    # self-capture) ; chacun coûte ~12-18 tokens de préfixe `[id=X] role: `
    # pour 0 contenu -> ~15 % de capacité pack MESURÉE gaspillée (re-mesure
    # deep-reasoner). Les exclure ne perd RIEN (btrim vide = rien à
    # digérer) ; leurs ids restent dans la plage couverte (curseur passe la
    # queue de vides). Le gate exige déjà >=1 message non vide -> jamais de
    # boucle infinie sur une queue 100 % vide.
    drop_empty = _env_flag("ARAC_PACK_DROP_EMPTY")
    # perf-loop (flags OFF par défaut, cf commentaires des constantes):
    #   - max_convs : plafond de conversations ADMISES (pack_meta), PAS de
    #     candidats examinés — une conversation reportée/oversized/vide ne
    #     consomme jamais un slot du plafond, le budget coule vers la
    #     candidate suivante (propriété « budget rempli »). Le round-robin
    # en amont choisit LESQUELLES (fairness intacte: le cap prend
    #     les N premières de l'ordre interleavé).
    #     Gain attendu : quarantaines multi-conv (50 % des sorties ère 95k,
    #     runs 51/52) -> ~0, soit ≈ +87 kt/j de digestion (fourchette
    #     +31/+174, enquête 2026-07-17).
    #   - strict_boundaries : durcissement du MARQUAGE des frontières de
    #     conversation (rendu SEUL — ni guard ni contrat). Cible les 3
    #     mécanismes mesurés des 6 quarantaines foreign (523 449 in_tok
    #     brûlés en 14,6 j ≈ 31,4 kt/j) : (a) attribution croisée
    #     intra-pack (runs 11/38/51/52) -> uid répété DEBUT+FIN, (b)
    #     extrapolation d'id au bord de tranche (runs 12/20) -> avis de
    #     troncature explicite, (c) éclatement uid/ids (run 52) -> fence
    #     `<<<...>>>` insaisissable par le format `## ...` que le contenu
    #     self-capture peut contenir littéralement (frontières spoofables,
    #     pack.py rendait `## conversation` alors que les convs de
    #     self-capture contiennent des packs cortex antérieurs).
    max_convs = _pack_max_convs()
    strict_boundaries = _env_flag("ARAC_PACK_STRICT_BOUNDARIES")
    # perf-loop it.2 (flag OFF par défaut, cf commentaire de
    # `RECOMMENDED_PACK_FILL_FLOOR`) : seuil de `remaining` déclenchant le
    # géant de secours (H-C). 0 = OFF = bit-identique it.1.
    fill_floor = _pack_fill_floor()
    # VOIE DE FRAÎCHEUR — appliquée ICI, après lecture de TOUS les
    # caps (le clamp anti-famine a besoin de `max_convs`) et AVANT toute
    # lecture de messages : c'est un pur réordonnancement de la liste de
    # candidats, exactement comme `_interleave_by_source`. `recency_slots`
    # == 0 -> `candidates` n'est même pas touché (bit-identique).
    if recency_slots:
        candidates = await _apply_recency_lane(
            db, candidates, window, slots=recency_slots,
            max_conversations=max_conversations, max_convs=max_convs,
            count_fn=count_fn, drop_empty=drop_empty)

    pack_meta: list[dict[str, Any]] = []
    presented: dict[str, dict[str, Any]] = {}
    sections: list[str] = []
    remaining = budget_tokens
    messages_reported = 0
    oversized_messages: list[dict[str, Any]] = []
    # ids des conversations DÉJÀ examinées par la boucle principale
    # (fetch effectué) — le secours ne considère QUE les candidates jamais
    # atteintes (rang >= cap+1), les vrais géants du diagnostic.
    seen_conv_ids: set[Any] = set()

    def _admit_tranche(conv: dict[str, Any], rows: list[dict[str, Any]]) -> str:
        """Admet AU PLUS UNE tranche `[cursor+1 .. budget]` de `conv`
        (`rows` = delta non curé DÉJÀ fetché). Mute l'état du pack en cours de
        construction (`pack_meta`/`presented`/`sections` + `remaining`/
        `messages_reported`/`oversized_messages`). Logique EXTRAITE mot-pour-
        mot de la boucle d'admission historique it.1, partagée avec le secours
        Flag OFF par défaut : le seul appelant est la boucle principale, et la
        sémantique reste bit-identique.
        Retourne :
          - "stop"     : le scaffold seul dépasse le restant ET le pack n'est
                         pas vide -> l'appelant DOIT rompre sa boucle ;
          - "skip"     : rien admis (report / oversized / tranche vide) ->
                         l'appelant passe à la candidate suivante ;
          - "admitted" : une tranche non vide a été ajoutée au pack.
        """
        nonlocal remaining, messages_reported
        if strict_boundaries:
            # fence explicite DEBUT/FIN portant l'uid des DEUX côtés
            # + réserve conservatrice pour l'avis de troncature (bornée par
            # le dernier id du delta : le dernier id rendu lui est <=, donc
            # jamais plus de chiffres — le budget ne peut pas être dépassé,
            # au pire quelques tokens de marge inutilisée).
            header = (f"<<<DEBUT CONVERSATION uid={conv['conversation_uid']} "
                      f"source={conv['source_type']}>>>")
            footer = (f"<<<FIN CONVERSATION uid={conv['conversation_uid']} — "
                      "ids citables : UNIQUEMENT les ids [id=N] affichés "
                      "ci-dessus, dans CETTE conversation>>>")
            used = (count_fn(header) + count_fn(footer)
                    + count_fn(_strict_trunc_notice(int(rows[-1]["id"]))))
        else:
            header = (f"## conversation {conv['conversation_uid']} "
                      f"(source={conv['source_type']})")
            used = count_fn(header)
        if used > remaining and pack_meta:
            return "stop"
        tranche: list[str] = []
        # Fix round-1 (anti-poison, finding 7) : DEUX listes distinctes —
        # `covered_ids` (plage contiguë couverte par le curseur, vides dropés
        # INCLUS) vs `rendered_ids` (ids réellement MONTRÉS au LLM). Seuls
        # les seconds entrent dans `presented[uid]["message_ids"]` : un atome
        # citant un id dropé (jamais présenté) est un id ÉTRANGER pour
        # `contract.py` (foreign_message_ids -> quarantaine attribuée), plus
        # jamais un passe-droit du contrôle anti-poison.
        covered_ids: list[int] = []
        rendered_ids: list[int] = []
        # FIX B — TROISIÈME liste : les ids COUVERTS-mais-JAMAIS-RENDUS
        # pour l'unique raison qu'ils étaient VIDES (dropés par DROP_EMPTY
        # ci-dessous). Strictement `covered_ids - rendered_ids`, donc toujours
        # de CETTE conversation et toujours DANS la plage [cursor_from, max_id]
        # (ils entrent dans `covered_ids`, qui définit `max_id`). Exposés au
        # guard `foreign_message_ids` (contract.py) qui, sous son PROPRE flag
        # `ARAC_CORTEX_EMPTY_DROP_TOLERANT`, tolère qu'un atome les cite (et
        # les retire alors de sa provenance). Clé ADDITIVE et INERTE : aucun
        # consommateur ne la lit flag OFF, `presented[uid]["message_ids"]`
        # (l'entrée du guard) reste strictement les ids RENDUS.
        empty_ids: list[int] = []
        oversized_here: dict[str, Any] | None = None
        for m in rows:
            if drop_empty and _is_empty_like_gate(m["content"]):
                # Message VIDE AU SENS DU GATE SQL (btrim, cf
                # `_is_empty_like_gate`) : jamais rendu (0 token), mais son
                # id ENTRE dans la plage couverte contiguë -> le curseur
                # passera la queue de vides. INV-7 respecté : « présenter »
                # un contenu vide intégralement, c'est ne rien présenter.
                covered_ids.append(int(m["id"]))
                empty_ids.append(int(m["id"]))
                continue
            rendered = _render_message(m)
            cost = count_fn(rendered)
            if cost > remaining - used:
                if not tranche:
                    # Message de tête qui ne tient pas dans le RESTANT.
                    # strict: le seuil report-vs-blocage décompte le
                    # scaffold (fence+footer+réserve, déjà dans `used`,
                    # tranche vide) — sans quoi un message de coût dans
                    # ]plein−scaffold, plein] serait reporté à CHAQUE cycle
                    # sans jamais tenir (livelock fail-open). OFF : seuil
                    # historique inchangé (bit-identique).
                    full_fit = (budget_tokens - used) if strict_boundaries \
                        else budget_tokens
                    if cost <= full_fit:
                        # Tient dans le budget PLEIN : REPORT (jamais tronqué,
                        # jamais inclus à moitié) — la conversation sort du
                        # pack ce cycle, curseur inchangé, elle repassera
                        # seule/en tête au prochain cycle (budget frais).
                        messages_reported += 1
                    else:
                        # Ne tient même pas dans le budget PLEIN : BLOCAGE
                        # fail-closed — curseur gelé, remonté au caller.
                        oversized_here = {
                            "uid": conv["conversation_uid"],
                            "message_id": int(m["id"]),
                            "chars": len(str(m["content"])),
                            "est_tokens": cost,
                        }
                break
            tranche.append(rendered)
            covered_ids.append(int(m["id"]))
            rendered_ids.append(int(m["id"]))
            used += cost

        if oversized_here is not None:
            oversized_messages.append(oversized_here)
            return "skip"
        if not tranche:
            return "skip"
        remaining -= used
        uid = conv["conversation_uid"]
        pack_meta.append({
            "conversation_id": conv["id"],
            "uid": uid,
            "cursor_from": int(conv["cursor"]),
            "max_id": max(covered_ids),
            "n_msgs": len(covered_ids),
        })
        presented[uid] = {
            "conversation_id": conv["id"],
            "max_id": max(covered_ids),
            # Ids réellement MONTRÉS au LLM (fix round-1, finding 7) — les
            # vides dropés n'y entrent JAMAIS (couverts par max_id, mais
            # citables par personne : contract.py les rejette en foreign).
            "message_ids": set(rendered_ids),
            # FIX B — ids couverts, DANS la plage, mais non rendus CAR VIDES.
            # Disjoint de `message_ids` par construction. Vide quand
            # `ARAC_PACK_DROP_EMPTY` est OFF (aucun drop -> aucune tolérance
            # possible : B est inopérant sans DROP_EMPTY).
            "empty_ids": set(empty_ids),
            "source_type": conv["source_type"],
            # la tranche couvre-t-elle TOUT le delta
            # non curé de la conversation ? True ssi le dernier id COUVERT
            # est le dernier id du delta (pas de coupure budget, pas de
            # report, pas d'oversized — ces deux derniers cas sortent la
            # conversation du pack plus haut). Le disposant en a besoin
            # pour distinguer « omise alors que PLEINEMENT présentée »
            # (low-yield, drain traçé) de « omise car tranche TRONQUÉE »
            # (géant > budget : l'omission ne prouve rien -> backoff,
            # jamais park).
            "fully_presented": covered_ids[-1] == int(rows[-1]["id"]),
        }
        if strict_boundaries:
            # assemblage fencé — avis de troncature si la tranche est
            # coupée au budget en plein flux (même prédicat que
            # `fully_presented`), puis footer répétant l'uid. Rendu SEUL :
            # `presented`/`pack_meta` (les entrées du guard) sont identiques
            # flag ON/OFF.
            body = [header] + tranche
            if covered_ids[-1] != int(rows[-1]["id"]):
                body.append(_strict_trunc_notice(covered_ids[-1]))
            body.append(footer)
            sections.append("\n".join(body))
        else:
            sections.append(header + "\n" + "\n".join(tranche))
        return "admitted"

    def _renderable_delta_tokens(rows: list[dict[str, Any]]) -> int:
        """Critère de sélection du géant de secours (« plus gros delta
        dispo »). Délègue à `_delta_tokens` (module) — MÊME grandeur, même
        compteur que la garde de volume et que le budget du pack."""
        return _delta_tokens(rows, count_fn=count_fn, drop_empty=drop_empty)

    for conv in candidates:
        if remaining <= 0:
            break
        if max_convs and len(pack_meta) >= max_convs:
            # plafond ATTEINT sur les conversations ADMISES — les
            # candidates suivantes restent au backlog, curseur intouché, le
            # gate anti-famine les re-sélectionne au prochain cycle.:
            # le secours (post-boucle) pourra en admettre UNE si beaucoup de
            # budget reste abandonné (drained-short) — jamais plus.
            break
        rows = await curator_lib_v2.fetch_uncurated_messages(
            db, conv["id"], conv["cursor"])
        seen_conv_ids.add(conv["id"])
        if not rows:
            continue
        if _admit_tranche(conv, rows) == "stop":
            break

    # perf-loop it.2 — SECOURS « géant de secours » (H-C), flag OFF par
    # défaut (fill_floor == 0 -> ce bloc est mort, bit-identique it.1). Ne se
    # déclenche QUE quand le CAP a rompu la boucle mono-passe (len(pack_meta)
    # >= max_convs) ET qu'un budget substantiel (>= fill_floor) a été abandonné
    # (cas drained-short : 4 têtes courtes -> 68,7 kt perdus, run 53). Admet AU
    # PLUS UNE conversation supplémentaire = le PLUS GROS delta encore
    # disponible (rang >= cap+1, jamais examiné). SUR-ENSEMBLE strict de it.1 :
    # AUCUNE conv admise n'est retirée (anti-famine + fairness préservées),
    # convs distinctes <= max_convs + 1. Le rendu (entrées du guard
    # foreign_message_ids, contract.py:427) passe par le MÊME `_admit_tranche`
    # -> guard INTOUCHÉ.
    if (fill_floor and max_convs and len(pack_meta) >= max_convs
            and remaining >= fill_floor):
        rescue_pool: list[tuple[dict[str, Any], list[dict[str, Any]], int]] = []
        for conv in candidates:
            if conv["id"] in seen_conv_ids:
                continue
            rows = await curator_lib_v2.fetch_uncurated_messages(
                db, conv["id"], conv["cursor"])
            seen_conv_ids.add(conv["id"])
            if not rows:
                continue
            rescue_pool.append((conv, rows, _renderable_delta_tokens(rows)))
        # « plus gros delta dispo » d'abord (tri stable : à delta égal, l'ordre
        # du gate/interleave est conservé). On tente d'admettre le premier
        # qui produit une tranche puis on ARRÊTE : le secours est UNE conv, une
        # tranche. Un candidat non admis (oversized / report) est légitimement
        # tracé (rang >= cap+1 jamais vu jusqu'ici) et on passe au suivant.
        rescue_pool.sort(key=lambda t: t[2], reverse=True)
        for conv, rows, _delta in rescue_pool:
            if _admit_tranche(conv, rows) == "admitted":
                break

    known_block = await _known_atoms_block(db, [p["uid"] for p in pack_meta])
    return {
        "pack_meta": pack_meta,
        "presented": presented,
        "conversations_block": "\n\n".join(sections) if sections else "(aucune)",
        "known_atoms_block": known_block,
        "est_tokens": budget_tokens - remaining,
        "messages_reported": messages_reported,
        "messages_truncated": 0,
        "oversized_messages": oversized_messages,
    }


async def _known_atoms_block(db, uids: list[str]) -> str:
    """Atomes actifs LIÉS aux conversations du pack (lignée `source_ref`) —
    la matière du `supersede_key_hint`. Déterministe (pas de « scopes du
    pack » : ils n'existent qu'après curation). Le backstop sémantique du
    disposant couvre les doublons inter-conversations."""
    if not uids:
        return "(aucun)"
    sql = (
        "SELECT scope, kind, key, left(value, %s) "
        "FROM arac.memory_atoms "
        "WHERE status = 'active' "
        "  AND (source_ref->>'conversation_uid' = ANY(%s) "
        "       OR source_ref->>'curator_raw_id' = ANY(%s)) "
        "ORDER BY updated_at DESC LIMIT %s"
    )
    async with db.cursor() as cur:
        await cur.execute(sql, (KNOWN_VALUE_TRUNC, uids, uids, KNOWN_ATOMS_CAP))
        rows = await cur.fetchall()
    if not rows:
        return "(aucun)"
    return "\n".join(f"- [{r[0]}] {r[1]} `{r[2]}` : {r[3]}" for r in rows)
