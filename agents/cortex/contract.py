"""Contrat de sortie `cortex-dispose/1`.

Le LLM du disposant n'a AUCUN outil et n'écrit RIEN : il émet UN objet JSON
sur stdout. Ce module est le SEUL endroit qui parse cette sortie et la
valide STRICTEMENT avant qu'un octet n'atteigne l'API atomes — sortie
invalide ⇒ quarantaine du run entier (jamais de salvage partiel, §2).

Deux fonctions pures, hermétiques (aucun accès réseau/DB) :
  - `extract_json_object` : extraction de l'objet JSON depuis le texte brut
    (fenced ```json, ou premier objet `{}` équilibré) ;
  - `validate_document`   : validation de forme du contrat + retrait des
    champs contrôlés par le code + retour du document nettoyé.

La politique HYBRID (seuils de confiance, scopes valides, construction du
payload POST) est hors périmètre de ce module : voir `agents/cortex/policy.py`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger("arac.cortex.contract")


def _env_flag(name: str) -> bool:
    """Flag env PUR, lu à CHAQUE appel (armement au déploiement systemd)."""
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _runref_lenient_enabled() -> bool:
    """FIX A — `run_ref` échoé par le LLM : mismatch non-fatal si armé."""
    return _env_flag("ARAC_CORTEX_RUNREF_LENIENT")


def _empty_drop_tolerant_enabled() -> bool:
    """FIX B — tolérance des ids COUVERTS-mais-VIDES (dropés par
    `ARAC_PACK_DROP_EMPTY`) cités par un atome de LA MÊME conversation."""
    return _env_flag("ARAC_CORTEX_EMPTY_DROP_TOLERANT")


def _uid_nearmatch_enabled() -> bool:
    """FIX C — réparation d'un `conversation_uid` corrompu à la transcription."""
    return _env_flag("ARAC_CORTEX_UID_NEARMATCH")


def _dedup_uid_strict_enabled() -> bool:
    """FIX D (dette PRÉEXISTANTE, fix round-1 finding F1) — un même
    `conversation_uid` répété DEUX FOIS dans le document devient FATAL.

    Sur `main`, ce cas est accepté et fait boucler `dispose.py:573-575` deux
    fois sur la MÊME conversation (double avance de curseur, ou avance suivie
    d'un `mark_curation_failed`). Le trou est antérieur au chantier A+B+C
    (reproduit tous flags OFF) : il est donc corrigé sous SON PROPRE flag,
    défaut OFF, pour préserver l'exigence « flags OFF = bit-identique ».

    FIX D NEUTRALISÉ (fix round-3, finding N2) — cette fonction retourne
    TOUJOURS `False`, MÊME flag armé. Raison mesurée : armé, D transforme un
    doublon d'uid PUR (aucune autre violation) en quarantaine FATALE **non
    attribuable** (F6) ; `cycle.py:531` ne punit alors personne, `retry_count`
    n'avance pas, les curseurs restent intouchés (`cycle.py:554`) -> RIEN ne
    bouge dans l'état DB, le pack suivant est identique, le run est re-spawné
    (payé) à l'identique. L'amortisseur `_bisected_max_conversations`
    (`cycle.py:176-222`) n'est pas convergent mais OSCILLANT (6→6→3→6→6→3… :
    la bisection change la signature de pack et se désarme elle-même,
    `cycle.py:217-218`). La boucle ne termine jamais ; elle n'est bornée qu'en
    DÉPENSE par `max_spawns_per_day` (`agents/lib/spend_guard.py`).
    C'est un trou de TERMINAISON.

    Non fermable proprement dans le périmètre de ce chantier : (i) le fermer
    en RÉ-ATTRIBUANT le doublon rouvre F6 (punition d'une conversation
    productive) ; (ii) le fermer en salvant l'un des deux blocs viole la
    doctrine « quarantaine du run entier, jamais de salvage partiel » ;
    (iii) le fermer par park/backoff exige de modifier la bisection, qui est
    du chemin PRINCIPAL non flaggé (= changement prod sans preuve mesurée).
    D est par ailleurs HORS mandat A+B+C et hors périmètre de déploiement
    recommandé (reco = A+B). Règle appliquée : « faille non fermable
    proprement -> on désactive le fix ». La dette F1 (double dispose) revient
    donc au comportement de `main` : statu quo, aucune régression.
    Ré-armement futur : supprimer ce court-circuit ET borner d'abord la
    répétition côté `cycle.py` (compteur de quarantaines consécutives non
    attribuables à signature de pack constante -> park/backoff), JAMAIS en
    ré-attribuant.
    """
    if _env_flag("ARAC_CORTEX_DEDUP_UID_STRICT"):
        _log("cortex.contract.dedup_uid_strict_neutralized",
             reason="round3_finding_N2_termination_hole")
    return False


def _log(event: str, **kw: Any) -> None:
    logger.info(json.dumps({"event": event, **kw}, ensure_ascii=False, default=str))


def _sha8(value: object) -> str:
    """Empreinte courte d'une valeur venue du LLM — JAMAIS la valeur en clair.

    Invariant PII (V0.107, mémoire `feedback-arac-audit-ref-no-pii`) : rien de
    ce qu'écrit le LLM ne part en clair et non borné dans journald (fix
    round-1, finding R4 : un `run_ref` halluciné de 4 000 caractères portant un
    patronyme partait intégralement dans les logs persistants)."""
    return hashlib.sha256(str(value).encode("utf-8", "replace")).hexdigest()[:8]

# ----------------------------------------------------------------------------
# Constantes du contrat
# ----------------------------------------------------------------------------

CONTRACT_VERSION = "cortex-dispose/1"
MAX_STDOUT_BYTES = 1_048_576
MAX_ATOMS_PER_RUN = 200

# Les 12 kinds producteurs autorisés en sortie du disposant (DESIGN §2) —
# sous-ensemble volontaire des 16 kinds producteurs de app/schemas/kind.py
# (agent_message, mission_proposal, mission, delivery,
# imported_conversation_summary sont hors périmètre de la curation) ; `alert`
# (kind auditeur) est ajouté car son audit_source est forcé côté code
# (cf policy.finalize_atom).
ALLOWED_KINDS = frozenset({
    "decision", "pattern", "gotcha", "state", "todo", "note",
    "idea", "insight", "question", "reference", "killed", "alert",
})

# Champs contrôlés PAR LE CODE, jamais acceptés du LLM (DESIGN §2 + §3) —
# retirés silencieusement d'un atome, mais comptés dans `_stripped_fields_count`
# du document nettoyé retourné par `validate_document`.
FORBIDDEN_ATOM_FIELDS = frozenset({"node_id", "confidence", "audit_source", "source_ref"})

_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,126}[a-z0-9]$")
_VALUE_MAX_LEN = 6000
_MAX_TAGS = 8

_ATOM_KNOWN_FIELDS = frozenset({
    "kind", "scope", "key", "value", "rationale", "confidence_score",
    "tags", "supersede_key_hint", "message_ids",
})
_DOC_ALLOWED_FIELDS = frozenset({
    "contract_version", "run_ref", "complete", "conversations", "audit_summary",
})
# `no_new_knowledge` (oracle de couverture) : attestation
# explicite du LLM qu'une conversation présentée n'a RIEN produit de durable
# (décision terminale motivée, distincte d'un simple `"atoms": []` silencieux
# — cf `agents/cortex/dispose.py` pour la sémantique covered/no_new_knowledge/omitted).
_CONVERSATION_ALLOWED_FIELDS = frozenset({
    "conversation_uid", "atoms", "skips", "no_new_knowledge",
})

_FENCE_RE = re.compile(r"```json\s*(.*?)```", re.DOTALL)

# ----------------------------------------------------------------------------
# FIX A — grammaire d'un `run_ref` SERVEUR (`cycle.resolve_slot`)
# ----------------------------------------------------------------------------
# Fix round-1 (finding F3, chemin de REJEU) : rendre le mismatch non-fatal
# rendait aussi acceptable un document produit pour un AUTRE run RÉEL (même
# grammaire, autre créneau) — matériau vérifié présent en prod : 12 messages
# bruts sur 3 conversations contiennent une sortie `cortex-dispose/1` avec un
# `slot_key` d'un run passé, sur des conversations non exclues et non curées,
# donc RÉ-PRÉSENTABLES dans un pack futur. Le LLM pourrait recopier ce
# document ; ses `message_ids` seraient alors ⊆ du nouveau pack et le curseur
# avancerait sur des messages JAMAIS lus.
# D'où la lénience GRAMMATICALE : on ne tolère QUE ce qui ne peut pas être le
# slot_key d'un run (invention libre du LLM — cas run 59 :
# `manual_digest_2026-07-19` pour `circadian_0400@2026-07-19`). Un `run_ref`
# BIEN FORMÉ mais différent de l'attendu reste FATAL, flag ON compris.
_SLOT_KEY_RE = re.compile(
    r"^(?:circadian_\d{4}|manual)@\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2})?$"
)

# ----------------------------------------------------------------------------
# FIX C — `ARAC_CORTEX_UID_NEARMATCH`
# ----------------------------------------------------------------------------
# Seuils DÉRIVÉS DES DONNÉES (population mesurée : 244 `conversation_uid` réels
# de `arac.conversations`, prod 2026-07-20) :
#   - distance d'édition MINIMALE entre deux uids réels DISTINCTS   = 21
#   - cas réel run 64 (déclaré `6e2143-…` vs pack `6e2b6143-…`)     = 2
#     (2e meilleur candidat du même pack : 23)
#   - mode « ids de messages » du run 52 (`unknown_conversation:150884` …)
#     = 30 -> reste FATAL, ce n'est PAS une corruption de transcription.
# D'où le seuil UNIQUE ci-dessous : marge 2 vs 21. Toute paire d'uids réels est
# donc hors de portée l'un de l'autre par construction ; seule une corruption
# de transcription peut matcher.
#
# Fix round-2 (finding V1, BLOQUANT) — LA JUSTIFICATION EMPIRIQUE DE C EST
# FALSIFIÉE. Vérification prod (SSH lecture seule, reçu `arac.run_receipts`
# id=64) : le bloc à uid corrompu porte AUSSI un `message_id` 897983 qui
# N'EXISTE PAS dans `arac.raw_messages` (count=0 ; voisins réels
# 897990..898000). Le run 64 cumule donc DEUX modes : (i) uid corrompu, que C
# répare, et (ii) id de message HALLUCINÉ, qu'aucun des fix A/B/C ne couvre et
# qui reste FATAL par le garde `foreign_message_ids` (volontairement conservé).
# Conséquence : C ne sauve PAS le run 64 — il change seulement l'étiquette de
# quarantaine (`unknown_conversation` -> `foreign_message_ids`, non attribuée
# dans les deux cas). GAIN MESURÉ DE C = 0 RUN À CE JOUR. Le flag reste
# implémenté (durci) mais la recommandation de déploiement est NO-GO : A+B
# seuls ont un gain prouvé (runs 59, 61, 63). Cf `tests/test_verif_round2_abc.py
# ::test_NEW_C_ne_sauve_PAS_le_run_64`.
#
# Fix round-1 (finding F4) : la branche « suffixe commun >= 30 » a été
# SUPPRIMÉE. Elle réparait à distance d'édition 5 (`deadbe43-0e70-…` vers
# `6e2b6143-0e70-…`, préfixe entièrement différent) alors que le cas cible
# (run 64) passe par la branche distance (2) — elle était donc inutile au cas
# réel et strictement élargissante. Un guard ne s'affaiblit jamais : on le
# resserre au seul mode mesuré.
_UID_MAX_EDIT_DISTANCE = 2
_UID_MAX_LEN_DELTA = 2          # borne de longueur (pré-filtre)
_UID_SHAPE_RE = re.compile(r"^[0-9a-fA-F-]{30,40}$")  # forme uuid-esque exigée


def _edit_distance(a: str, b: str, *, cutoff: int) -> int:
    """Distance de Levenshtein bornée (retourne `cutoff + 1` si dépassée)."""
    if abs(len(a) - len(b)) > cutoff:
        return cutoff + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ca != cb),
            ))
        previous = current
        if min(previous) > cutoff:
            return cutoff + 1
    return previous[-1]


def _nearmatch_uid(declared: str, candidates: "list[str]") -> "tuple[str | None, list[str]]":
    """Cherche l'uid RÉEL du pack dont `declared` est une corruption.

    Retourne `(uid réparé | None, tous les candidats retenus)`. Le match doit
    être UNIQUE : si >= 2 uids du pack passent le seuil, aucune réparation
    (l'appelant reste FATAL) — on ne devine JAMAIS entre deux conversations.
    Branche UNIQUE : distance d'édition <= `_UID_MAX_EDIT_DISTANCE`.
    """
    if not _UID_SHAPE_RE.match(declared):
        return None, []
    matches: list[str] = []
    for uid in candidates:
        if abs(len(uid) - len(declared)) > _UID_MAX_LEN_DELTA:
            continue
        if (_edit_distance(declared, uid, cutoff=_UID_MAX_EDIT_DISTANCE)
                <= _UID_MAX_EDIT_DISTANCE):
            matches.append(uid)
    if len(matches) == 1:
        return matches[0], matches
    return None, matches


def _membership_proof_count(conv: object, pack_entry: dict) -> int:
    """Nombre d'ids de messages RÉELLEMENT RENDUS de `pack_entry` cités par les
    atomes du bloc `conv` (fix round-2, finding F5 — preuve d'appartenance).

    Compte UNIQUEMENT les ids présents dans `message_ids` (= ids rendus au LLM).
    Les `empty_ids` (FIX B) ne sont JAMAIS une preuve : citer un id vide ne
    prouve pas qu'on a lu la conversation, le message n'a rien montré.
    """
    if not isinstance(conv, dict):
        return 0
    rendered = pack_entry.get("message_ids") or frozenset()
    n = 0
    # Fix round-3 (finding N1) : `atoms` vient BRUT du LLM et n'est validé
    # (`atoms_not_list`) que PLUS BAS dans `validate_document` — cette fonction
    # est appelée AVANT. L'idiome `conv.get("atoms") or []` ne rattrapait que
    # les valeurs FALSY : `"atoms": 5` / `true` / `1.5` sont truthy et NON
    # itérables -> `TypeError` non rattrapée, qui remontait hors du
    # `except ContractError` de `cycle.py:522` et laissait un reçu ORPHELIN au
    # statut `spawning` (spawn payé perdu, bisection anti-poison désarmée 2
    # cycles, tuile cockpit polluée). Un type non-liste = AUCUNE preuve
    # d'appartenance -> 0 -> pas de réparation C -> retour exact au
    # comportement FATAL de `main`. Strictement RESSERRANT.
    atoms = conv.get("atoms")
    if not isinstance(atoms, list):
        return 0
    for atom in atoms:
        if not isinstance(atom, dict):
            continue
        mids = atom.get("message_ids")
        if not isinstance(mids, list):
            continue
        n += sum(1 for m in mids
                 if isinstance(m, int) and not isinstance(m, bool) and m in rendered)
    return n


def _best_uid_distance(declared: object, candidates: "list[str]") -> int | None:
    """Meilleure distance d'édition observée (near-miss C8) — bornée, sert
    UNIQUEMENT au log de calibration ; aucune influence sur la validation."""
    if not isinstance(declared, str) or not candidates:
        return None
    cutoff = _UID_MAX_EDIT_DISTANCE + 6
    best = min(_edit_distance(declared, uid, cutoff=cutoff) for uid in candidates)
    return best if best <= cutoff else None


class ContractError(Exception):
    """Levée quand la sortie du LLM viole le contrat `cortex-dispose/1`.

    `errors` accumule TOUTES les violations détectées (jamais un seul
    message au premier échec) — le disposant journalise la liste complète
    en quarantaine DB (DESIGN §2 : « quarantaine du run entier », jamais de
    salvage partiel).

    `attributed_uids` (attribution du poison) : sous-ensemble
    des `conversation_uid` RÉELLEMENT présentes dans le pack (`presented`)
    dont on peut prouver qu'elles sont la SOURCE d'au moins une violation
    (erreur positionnelle `conversations[i].*` ou `foreign_message_ids:<uid>`
    résolue via l'ordre du document — cf `validate_document`). Vide pour les
    erreurs de forme globales (JSON illisible/tronqué, version/run_ref/
    complete invalides…) : ces erreurs-là ne punissent PERSONNE (cycle.py).
    Un uid qui n'existe PAS dans `presented` (halluciné) n'est JAMAIS ajouté
    ici — l'erreur `unknown_conversation:<uid>` reste non-attribuable.
    """

    def __init__(
        self,
        errors: list[str],
        *,
        attributed_uids: "frozenset[str] | set[str] | None" = None,
    ):
        self.errors = list(errors)
        self.attributed_uids: frozenset[str] = frozenset(attributed_uids or ())
        super().__init__("; ".join(self.errors))


# ----------------------------------------------------------------------------
# Extraction JSON
# ----------------------------------------------------------------------------


def extract_json_object(stdout: str) -> dict:
    """Extrait l'unique objet JSON de la sortie stdout du spawn `claude -p`.

    Stratégie (DESIGN §2) :
      (a) un bloc fencé ```json ... ``` existe -> on parse SON contenu ;
      (b) sinon, on scanne le texte pour le PREMIER objet `{...}` équilibré
          (comptage d'accolades qui ignore celles situées dans des strings
          JSON, échappements `\\"` compris).

    Lève `ContractError` si : stdout vide ; > MAX_STDOUT_BYTES ; aucun objet
    trouvé ; JSON invalide ou tronqué (accolade non fermée) ; plusieurs
    objets top-level NUS hors bloc fencé (ambiguïté refusée, jamais devinée) ;
    clés dupliquées à N'IMPORTE QUEL niveau d'imbrication.
    """
    if not stdout:
        raise ContractError(["stdout_empty"])

    n_bytes = len(stdout.encode("utf-8"))
    if n_bytes > MAX_STDOUT_BYTES:
        raise ContractError([f"stdout_too_large:{n_bytes}"])

    fence_match = _FENCE_RE.search(stdout)
    if fence_match is not None:
        candidate = fence_match.group(1)
    else:
        objects = _find_balanced_objects(stdout)
        if not objects:
            raise ContractError(["no_json_object_found"])
        if len(objects) > 1:
            raise ContractError(["multiple_top_level_objects"])
        candidate = objects[0]

    parsed = _parse_no_duplicate_keys(candidate)
    if not isinstance(parsed, dict):
        raise ContractError(["top_level_not_object"])
    return parsed


def _find_balanced_objects(text: str) -> list[str]:
    """Scanne `text` et retourne CHAQUE objet `{...}` top-level équilibré.

    Un objet non balancé (accolade ouvrante jamais refermée avant la fin du
    texte) est une troncature -> `ContractError` immédiate plutôt qu'un objet
    ignoré silencieusement.
    """
    objects: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "{":
            end = _scan_balanced(text, i)
            if end is None:
                raise ContractError(["truncated_json"])
            objects.append(text[i:end])
            i = end
        else:
            i += 1
    return objects


def _scan_balanced(text: str, start: int) -> int | None:
    """Retourne l'index juste après la `}` qui referme l'objet ouvert en
    `start`, ou None si jamais refermé. Ignore les accolades à l'intérieur de
    strings JSON (échappements `\\` pris en compte)."""
    depth = 0
    in_string = False
    escape = False
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return None


def _no_duplicate_keys_hook(pairs: list[tuple[str, Any]]) -> dict:
    """`object_pairs_hook` de `json.loads` — détecte les clés dupliquées à
    N'IMPORTE QUEL niveau (appelé par le décodeur pour chaque objet imbriqué)."""
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise ContractError([f"duplicate_key:{key}"])
        seen[key] = value
    return seen


def _parse_no_duplicate_keys(candidate: str) -> Any:
    try:
        return json.loads(candidate, object_pairs_hook=_no_duplicate_keys_hook)
    except ContractError:
        raise
    except json.JSONDecodeError as exc:
        raise ContractError([f"invalid_json:{exc}"]) from exc


# ----------------------------------------------------------------------------
# Validation du document
# ----------------------------------------------------------------------------


def validate_document(
    doc: dict,
    *,
    expected_run_ref: str,
    presented: dict[str, dict],
) -> dict:
    """Valide STRICTEMENT un document `cortex-dispose/1` et retourne sa
    version nettoyée (champs contrôlés par le code retirés).

    `presented` décrit le pack RÉELLEMENT offert au LLM par conversation :
    `{conversation_uid: {"max_id": int, "message_ids": set[int],
    "empty_ids": set[int]}}` — sert à rejeter les `conversation_uid`
    hallucinés et les `message_ids` hors tranche (red-team DESIGN §7).
    `empty_ids` (FIX B, pack.py) = ids COUVERTS par le curseur mais non rendus
    car VIDES ; clé optionnelle, lue UNIQUEMENT sous
    `ARAC_CORTEX_EMPTY_DROP_TOLERANT` (absente -> aucune tolérance).

    Accumule TOUTES les violations puis lève `ContractError` en bloc si la
    liste n'est pas vide (jamais de fail-fast partiel — le disposant a
    besoin de l'exhaustivité pour la quarantaine). Quand au moins une
    violation est imputable à une conversation RÉELLE du pack (erreur
    positionnelle `conversations[i].*` ou `foreign_message_ids:<uid>`),
    `ContractError.attributed_uids` la porte — permet au
    disposant de punir CETTE conversation seule plutôt que tout le pack.

    Retire silencieusement `FORBIDDEN_ATOM_FIELDS` de chaque atome — jamais
    acceptés du LLM — et compte leur nombre total dans
    `_stripped_fields_count` du document retourné. Tout AUTRE champ inconnu
    (top-level, conversation, ou atome) est une ERREUR, pas un strip.

    `no_new_knowledge` (oracle de couverture) : champ conversation
    optionnel, simplement type-validé ici (bool) — PAS d'erreur de contrat si
    une conversation présentée a `"atoms": []` sans `no_new_knowledge` ; ce
    cas est une omission COMPTÉE (pas rejetée), traitée par le disposant
    (`agents/cortex/dispose.py`). De même, une conversation présentée mais
    ABSENTE du document n'est pas une erreur de contrat : son uid apparaît
    dans `_omitted_uids` du document nettoyé.

    `ARAC_CORTEX_UID_NEARMATCH` (FIX C) : un `conversation_uid` absent du pack
    mais qui est une CORRUPTION DE TRANSCRIPTION d'un uid RÉEL du pack (match
    unique, seuils dérivés des données — cf `_nearmatch_uid`) est réparé,
    loggué et compté (`_uid_nearmatch_count`/`_uid_nearmatch_repairs`). Le
    garde `foreign_message_ids` s'applique ensuite NORMALEMENT sur la
    conversation réparée. Flag OFF (défaut) = `unknown_conversation:<uid>`.
    Un uid réparé n'est JAMAIS attribué (pas de punition d'une conversation
    innocente), une réparation qui créerait un DOUBLON de conversation dans
    le document est refusée (fix round-1, findings F1/F2), et une réparation
    SANS PREUVE D'APPARTENANCE (aucun atome du bloc ne cite un id RÉELLEMENT
    RENDU de la conversation cible) est refusée (fix round-2, finding F5 —
    sinon un bloc vide dispose TERMINALEMENT d'une conversation réelle).
    ⚠ Gain mesuré de C à ce jour : ZÉRO run sauvé (finding V1, cf bloc de
    constantes ci-dessus) — flag à laisser OFF.

    `ARAC_CORTEX_DEDUP_UID_STRICT` (FIX D, dette préexistante) : un même
    `conversation_uid` répété deux fois dans le document devient
    `duplicate_conversation_uid:<uid>` (FATAL, NON attribué à lui seul — fix
    round-2, finding F6). Flag OFF (défaut) = comportement de `main` (le
    doublon passe et fait boucler le disposant deux fois sur la même
    conversation).
    """
    if not isinstance(doc, dict):
        raise ContractError(["document_not_object"])

    errors: list[str] = []
    attributed_uids: set[str] = set()
    lenient_runref: tuple[Any, ...] = ()  # FIX A : (valeur déclarée,) si tolérée

    unknown_top = set(doc) - _DOC_ALLOWED_FIELDS
    errors.extend(f"unknown_top_level_field:{field}" for field in sorted(unknown_top))

    if doc.get("contract_version") != CONTRACT_VERSION:
        errors.append(f"contract_version_mismatch:{doc.get('contract_version')!r}")
    if doc.get("run_ref") != expected_run_ref:
        # FIX A — `ARAC_CORTEX_RUNREF_LENIENT` : le `run_ref` échoé par
        # le LLM n'a AUCUN consommateur aval (le `run_ref` gravé dans
        # `source_ref` des atomes, la review_queue et les reçus viennent TOUS
        # du `slot_key` SERVEUR — cycle.py:505 → dispose.py/policy.py:116/
        # review_queue.py). Ce n'est donc pas un garde de sécurité mais un
        # champ de cohérence mort : sous flag, le mismatch devient NON-FATAL
        # (loggué + compté), l'atome passe. Flag OFF (défaut) = fatal, à
        # l'octet près. Le slot_key serveur reste la seule source de vérité.
        # Fix round-1 (F3 + R4) : (i) lénience GRAMMATICALE — un `run_ref`
        # bien formé (grammaire slot_key serveur) mais différent reste FATAL,
        # c'est le chemin de REJEU d'un document d'un AUTRE run ; (ii) la
        # valeur déclarée n'est JAMAIS logguée en clair (sha8 + longueur).
        declared_runref = doc.get("run_ref")
        wellformed = bool(isinstance(declared_runref, str)
                          and _SLOT_KEY_RE.match(declared_runref))
        if _runref_lenient_enabled() and not wellformed:
            lenient_runref = (declared_runref,)
            _log("cortex.contract.runref_lenient",
                 run_ref=expected_run_ref,
                 declared_sha8=_sha8(declared_runref),
                 declared_len=len(declared_runref) if isinstance(declared_runref, str) else None,
                 declared_type=type(declared_runref).__name__)
        else:
            if _runref_lenient_enabled():
                # Near-miss A (C8) : flag armé, tolérance REFUSÉE.
                _log("cortex.contract.runref_lenient_refused",
                     run_ref=expected_run_ref, reason="wellformed_other_run",
                     declared_sha8=_sha8(declared_runref),
                     declared_len=len(str(declared_runref)))
                # Sous flag, l'erreur ne porte que l'empreinte (la valeur brute
                # remonte sinon dans journald via cycle.py `cortex.quarantined`).
                errors.append(f"run_ref_mismatch:sha8={_sha8(declared_runref)}")
            else:
                errors.append(f"run_ref_mismatch:{doc.get('run_ref')!r}")
    if doc.get("complete") is not True:
        errors.append(f"complete_not_true:{doc.get('complete')!r}")

    conversations = doc.get("conversations")
    if not isinstance(conversations, list):
        errors.append("conversations_not_list")
        conversations = []

    cleaned_conversations: list[dict] = []
    stripped_fields_count = 0
    total_atoms = 0
    # FIX B : ids VIDES tolérés (et retirés des provenances), pour compteur et
    # observabilité. Toujours 0 flag OFF.
    empty_tolerated_ids: list[int] = []
    # FIX C : réparations d'uid effectuées. Toujours vide flag OFF.
    uid_nearmatch_repairs: list[dict[str, str]] = []
    # Fix round-1 (F2) : uids OBTENUS PAR RÉPARATION — JAMAIS attribués (donc
    # jamais punis). Toujours vide flag OFF.
    repaired_uids: set[str] = set()
    # Fix round-1 (F1, chemin C) : uids DÉCLARÉS tels quels par le LLM +
    # cibles déjà réparées — une réparation ne doit jamais CRÉER un doublon
    # de conversation dans le document (dispose.py:573-575 boucle sans dédup).
    declared_uids: set[str] = {
        c["conversation_uid"] for c in conversations
        if isinstance(c, dict) and isinstance(c.get("conversation_uid"), str)
    }
    seen_uids: set[str] = set()

    for i, conv in enumerate(conversations):
        prefix = f"conversations[{i}]"
        if not isinstance(conv, dict):
            errors.append(f"{prefix}.not_object")
            continue

        errors_before_conv = len(errors)
        # Fix round-2 (F6) : erreurs NON attribuables émises pour ce bloc
        # (doublon d'uid) — décomptées de l'attribution ci-dessous.
        dup_only_errors = 0

        unknown_conv_fields = set(conv) - _CONVERSATION_ALLOWED_FIELDS
        errors.extend(
            f"{prefix}.unknown_field:{field}" for field in sorted(unknown_conv_fields)
        )

        uid = conv.get("conversation_uid")
        pack_entry = presented.get(uid) if isinstance(uid, str) else None
        if pack_entry is None and isinstance(uid, str) and _uid_nearmatch_enabled():
            # FIX C — `ARAC_CORTEX_UID_NEARMATCH` : le LLM a recopié un
            # uid RÉEL du pack en le corrompant (run 64 : `6e2143-…` pour
            # `6e2b6143-…`, 2 caractères perdus sur 36). Sous flag, et
            # SEULEMENT sous flag, on répare — sous conditions strictes
            # (seuils dérivés des données, cf `_nearmatch_uid`) :
            #   (1) le match doit être UNIQUE dans le pack (>= 2 candidats ->
            #       aucune réparation, l'erreur FATALE d'origine est émise) ;
            #   (2) seuil très serré (distance d'édition <= 2) avec une marge
            #       mesurée de 19 caractères sur la population réelle -> deux
            #       conversations réelles ne peuvent JAMAIS être confondues ;
            #   (3) la cible ne doit pas DÉJÀ être présente dans le document
            #       (fix round-1 F1 : sinon la réparation crée une CONVERSATION
            #       EN DOUBLE et `dispose.py:573-575`, qui ne dédoublonne pas,
            #       avance deux fois le curseur / punit une conv qui vient de
            #       réussir) ;
            #   (4) PREUVE D'APPARTENANCE (fix round-2, finding F5) : le bloc
            #       doit citer >= 1 id de message RÉELLEMENT RENDU de la
            #       conversation cible. Sans cette condition, un bloc SANS
            #       aucune preuve (0 atome, `no_new_knowledge=true`, ou
            #       `atoms: []`) devenait une disposition TERMINALE sur une
            #       conversation réelle : curseur avancé sans qu'un octet
            #       n'ait été lu (`dispose.py:585`), ou omission punie
            #       (`dispose.py:411-413`, park à 3), voire drain+exclusion
            #       low_yield sous `ARAC_DISPOSE_COVERAGE_V2` (armé en prod,
            #       `dispose.py:447-490`). La condition rétablit la symétrie
            #       avec FIX B, qui exige déjà >= 1 id rendu (`kept`) : aucun
            #       correctif de fidélité ne dispose d'une conversation sans
            #       preuve matérielle qu'elle a été lue. Strictement
            #       RESSERRANTE (jamais un guard affaibli) et sans perte sur
            #       le matériau réel : le bloc du run 64 cite 7 ids réels ;
            #   (5) la réparation est logguée et comptée.
            # Après réparation, `pack_entry` est celui de la conversation
            # RÉELLE : le garde `foreign_message_ids` s'applique NORMALEMENT
            # (filet anti-poison intact — un atome citant des ids d'une autre
            # conversation reste rejeté). En revanche l'uid réparé n'est
            # JAMAIS ajouté à `attributed_uids` (fix round-1 F2) : sinon un
            # bloc corrompu portant du poison ferait PUNIR (mark_curation_failed
            # via pack_meta, cycle.py `_punish_quarantine`) une conversation
            # réelle qui, flag OFF, n'était punie par personne.
            repaired, candidates = _nearmatch_uid(uid, list(presented))
            if repaired is not None and repaired in (declared_uids | repaired_uids):
                _log("cortex.contract.uid_nearmatch_refused",
                     run_ref=expected_run_ref, reason="target_already_in_document",
                     declared=uid, target=repaired)
                repaired = None
            if repaired is not None:
                # Condition (4) — preuve d'appartenance (fix round-2, F5).
                n_proof = _membership_proof_count(conv, presented[repaired])
                if n_proof == 0:
                    _log("cortex.contract.uid_nearmatch_refused",
                         run_ref=expected_run_ref, reason="no_membership_proof",
                         declared=uid, target=repaired,
                         n_atoms=len(conv.get("atoms") or [])
                         if isinstance(conv.get("atoms"), list) else None,
                         no_new_knowledge=conv.get("no_new_knowledge"))
                    repaired = None
            if repaired is not None:
                _log("cortex.contract.uid_nearmatch_repaired",
                     run_ref=expected_run_ref, declared=uid, repaired=repaired,
                     distance=_edit_distance(uid, repaired,
                                             cutoff=_UID_MAX_EDIT_DISTANCE))
                uid_nearmatch_repairs.append({"declared": uid, "repaired": repaired})
                repaired_uids.add(repaired)
                conv = dict(conv)
                conv["conversation_uid"] = repaired
                uid = repaired
                pack_entry = presented[repaired]
            elif len(candidates) > 1:
                # Ambiguïté : on ne devine JAMAIS entre deux conversations.
                _log("cortex.contract.uid_nearmatch_ambiguous",
                     run_ref=expected_run_ref,
                     declared=uid, candidates=sorted(candidates))
        if pack_entry is None:
            # uid halluciné/absent du pack : jamais attribuable (cf ContractError).
            # Near-miss C (C8) : de QUELLE distance était-on du meilleur uid du
            # pack ? Seule donnée qui permette de recalibrer le seuil (ou de
            # constater que C ne sert à rien) pendant le soak. La valeur brute
            # n'est logguée que si elle a la FORME d'un uid (sinon sha8+len :
            # le champ peut porter n'importe quel texte du LLM).
            shape_ok = bool(isinstance(uid, str) and _UID_SHAPE_RE.match(uid))
            _log("cortex.contract.unknown_conversation",
                 run_ref=expected_run_ref,
                 declared=uid if shape_ok else None,
                 declared_sha8=_sha8(uid), declared_len=len(str(uid)),
                 shape_ok=shape_ok,
                 best_distance=_best_uid_distance(uid, list(presented)),
                 nearmatch_armed=_uid_nearmatch_enabled())
            errors.append(f"unknown_conversation:{uid}")
        elif uid in seen_uids:
            # Dette PRÉEXISTANTE (fix round-1 F1, reproduite tous flags OFF) :
            # le LLM répète la MÊME conversation deux fois -> double passage
            # dans `dispose_document`. Sous flag `ARAC_CORTEX_DEDUP_UID_STRICT`
            # (défaut OFF = comportement de `main`), c'est FATAL et attribué à
            # la conversation fautive.
            if _dedup_uid_strict_enabled():
                errors.append(f"duplicate_conversation_uid:{uid}")
                # Fix round-2 (finding F6) : FATAL, mais JAMAIS attribué à
                # lui seul. Le doublon est un artefact du LLM (il a recopié
                # son propre bloc), pas une preuve que CETTE conversation a
                # produit du poison — elle a même pu produire des atomes
                # valides dans les DEUX blocs. L'attribuer transformait une
                # quarantaine non punitive (comportement de `main`) en
                # `mark_curation_failed` d'une conversation productive
                # (retry_count++, exclusion à 3) : doctrine C1, on ne punit
                # que ce dont la conversation est prouvée SOURCE. Si le même
                # bloc porte par ailleurs une VRAIE violation (foreign ids,
                # atome malformé…), l'attribution normale s'applique.
                dup_only_errors += 1
            else:
                _log("cortex.contract.duplicate_conversation_uid",
                     run_ref=expected_run_ref, declared=uid, enforced=False)
        if isinstance(uid, str):
            seen_uids.add(uid)

        no_new_knowledge = conv.get("no_new_knowledge")
        if no_new_knowledge is not None and not isinstance(no_new_knowledge, bool):
            errors.append(f"{prefix}.no_new_knowledge_invalid:{no_new_knowledge!r}")

        atoms = conv.get("atoms")
        if not isinstance(atoms, list):
            errors.append(f"{prefix}.atoms_not_list")
            atoms = []

        skips = conv.get("skips", [])
        if not isinstance(skips, list):
            errors.append(f"{prefix}.skips_not_list")
        else:
            for k, skip in enumerate(skips):
                if not isinstance(skip, dict):
                    errors.append(f"{prefix}.skips[{k}].not_object")

        cleaned_atoms: list[dict] = []
        for j, atom in enumerate(atoms):
            total_atoms += 1
            cleaned_atom, atom_errors, n_stripped, tolerated_empty = _validate_atom(
                atom,
                prefix=f"{prefix}.atoms[{j}]",
                pack_entry=pack_entry,
                conv_uid=uid,
                run_ref=expected_run_ref,
            )
            errors.extend(atom_errors)
            stripped_fields_count += n_stripped
            empty_tolerated_ids.extend(tolerated_empty)
            if cleaned_atom is not None:
                cleaned_atoms.append(cleaned_atom)

        # Attribution du poison : cette conversation est la
        # SOURCE d'au moins une violation ET c'est une conversation RÉELLE du
        # pack (pack_entry non None) -> imputable, sinon (uid halluciné) on
        # ne punit jamais une conversation qui n'existe pas.
        # Fix round-1 (F2) : un uid RÉPARÉ (FIX C) n'est jamais attribué — la
        # conversation réelle n'a pas écrit ce bloc, c'est le LLM qui a
        # corrompu son identifiant ; la punir serait transformer une
        # quarantaine NON attribuable (comportement flag OFF) en punition
        # d'une conversation innocente (retry_count++, exclusion à 3).
        # Fix round-2 (F6) : les erreurs purement structurelles du document
        # (doublon d'uid) ne comptent pas dans l'attribution.
        if (pack_entry is not None and uid not in repaired_uids
                and len(errors) - dup_only_errors > errors_before_conv):
            attributed_uids.add(uid)

        cleaned_conv = {k: v for k, v in conv.items() if k in _CONVERSATION_ALLOWED_FIELDS}
        cleaned_conv["atoms"] = cleaned_atoms
        cleaned_conversations.append(cleaned_conv)

    if total_atoms > MAX_ATOMS_PER_RUN:
        errors.append(f"atoms_total_exceeds_cap:{total_atoms}")

    if errors:
        raise ContractError(errors, attributed_uids=attributed_uids)

    cleaned_doc = {k: v for k, v in doc.items() if k in _DOC_ALLOWED_FIELDS}
    cleaned_doc["conversations"] = cleaned_conversations
    cleaned_doc["_stripped_fields_count"] = stripped_fields_count
    if empty_tolerated_ids:
        # FIX B : compteur de tolérance (clé ABSENTE quand rien n'a été toléré
        # -> document nettoyé bit-identique flag OFF).
        cleaned_doc["_empty_ids_tolerated_count"] = len(empty_tolerated_ids)
        cleaned_doc["_empty_ids_tolerated"] = sorted(set(empty_tolerated_ids))
    if uid_nearmatch_repairs:
        # FIX C : compteur de réparation (clés ABSENTES quand rien n'a été
        # réparé -> document nettoyé bit-identique flag OFF).
        cleaned_doc["_uid_nearmatch_count"] = len(uid_nearmatch_repairs)
        cleaned_doc["_uid_nearmatch_repairs"] = uid_nearmatch_repairs
    if lenient_runref:
        # FIX A : le slot_key SERVEUR reste la source de vérité — on écrase le
        # `run_ref` halluciné dans le document nettoyé (aucun aval ne peut donc
        # hériter d'une valeur fausse) et on compte la tolérance.
        # Fix round-1 (R4) : `_runref_declared` (valeur BRUTE, non bornée,
        # potentiellement porteuse de PII, et sans AUCUN lecteur) est
        # SUPPRIMÉ — seule l'empreinte survit.
        cleaned_doc["run_ref"] = expected_run_ref
        cleaned_doc["_runref_lenient_count"] = 1
        cleaned_doc["_runref_declared_sha8"] = _sha8(lenient_runref[0])
    # Conversations PRÉSENTÉES mais jamais mentionnées par le LLM (omission
    # totale, pas une erreur de contrat) : le disposant les
    # traite comme `coverage_omitted` (curseur figé, re-présentation naturelle).
    doc_uids = {c["conversation_uid"] for c in cleaned_conversations}
    cleaned_doc["_omitted_uids"] = sorted(uid for uid in presented if uid not in doc_uids)
    return cleaned_doc


def _validate_atom(
    atom: object,
    *,
    prefix: str,
    pack_entry: dict | None,
    conv_uid: object,
    run_ref: str = "",
) -> tuple[dict | None, list[str], int, list[int]]:
    """Valide un atome individuel.

    Retourne (atome nettoyé|None, erreurs, n_champs_retirés, ids_vides_tolérés)
    — le 4e élément (FIX B) est TOUJOURS vide flag OFF."""
    if not isinstance(atom, dict):
        return None, [f"{prefix}.not_object"], 0, []

    n_stripped = len(FORBIDDEN_ATOM_FIELDS & set(atom))

    errors: list[str] = []
    unknown = set(atom) - _ATOM_KNOWN_FIELDS - FORBIDDEN_ATOM_FIELDS
    errors.extend(f"{prefix}.unknown_field:{field}" for field in sorted(unknown))

    kind = atom.get("kind")
    if kind not in ALLOWED_KINDS:
        errors.append(f"{prefix}.kind_forbidden:{kind!r}")

    scope = atom.get("scope")
    if not isinstance(scope, str) or not scope.strip():
        errors.append(f"{prefix}.scope_invalid:{scope!r}")

    key = atom.get("key")
    if not isinstance(key, str) or not _KEY_PATTERN.match(key):
        errors.append(f"{prefix}.key_invalid:{key!r}")

    value = atom.get("value")
    if not isinstance(value, str) or not value or len(value) > _VALUE_MAX_LEN:
        errors.append(f"{prefix}.value_invalid")

    rationale = atom.get("rationale")
    if rationale is not None and not isinstance(rationale, str):
        errors.append(f"{prefix}.rationale_invalid")

    confidence_score = atom.get("confidence_score")
    if (
        not isinstance(confidence_score, int)
        or isinstance(confidence_score, bool)
        or not (0 <= confidence_score <= 100)
    ):
        errors.append(f"{prefix}.confidence_score_invalid:{confidence_score!r}")

    tags = atom.get("tags", [])
    if (
        not isinstance(tags, list)
        or len(tags) > _MAX_TAGS
        or not all(isinstance(t, str) for t in tags)
    ):
        errors.append(f"{prefix}.tags_invalid")

    supersede_key_hint = atom.get("supersede_key_hint")
    if supersede_key_hint is not None and not isinstance(supersede_key_hint, str):
        errors.append(f"{prefix}.supersede_key_hint_invalid")

    message_ids = atom.get("message_ids")
    valid_message_ids = (
        isinstance(message_ids, list)
        and len(message_ids) > 0
        and all(isinstance(m, int) and not isinstance(m, bool) for m in message_ids)
    )
    tolerated_empty: list[int] = []
    if not valid_message_ids:
        errors.append(f"{prefix}.message_ids_invalid")
    elif pack_entry is not None:
        allowed_ids = pack_entry.get("message_ids") or set()
        outside = [m for m in message_ids if m not in allowed_ids]
        if outside:
            # FIX B — `ARAC_CORTEX_EMPTY_DROP_TOLERANT`. Les ids cités
            # hors `message_ids` (= hors ids RENDUS) sont fatals PAR DÉFAUT.
            # Sous flag, et SEULEMENT sous flag, on tolère le cas de fidélité
            # mesuré (runs 61+63) : le LLM cite un id de LA MÊME conversation,
            # DANS la plage couverte, absent du rendu UNIQUEMENT parce que le
            # message était VIDE (dropé par `ARAC_PACK_DROP_EMPTY`,
            # pack.py:412-420 -> `presented[uid]["empty_ids"]`).
            # TROIS conditions cumulatives, aucune n'est relâchée :
            #   (1) TOUS les ids hors-rendu sont dans `empty_ids` de CETTE
            #       conversation (`pack_entry` est celui de l'uid déclaré) —
            #       un id d'une AUTRE conv ou HORS-PLAGE n'y est jamais, donc
            #       reste FATAL ;
            #   (2) il reste >= 1 id RÉELLEMENT RENDU : un atome dont toute la
            #       provenance est vide ne prouve rien -> FATAL ;
            #   (3) les ids tolérés sont RETIRÉS de la provenance de l'atome
            #       (`message_ids` nettoyés ci-dessous) : ils ne seront JAMAIS
            #       cités comme source dans `source_ref` (policy.py:119) ni
            #       relus par `app/repr/spans.py`.
            empty_ids = pack_entry.get("empty_ids") or frozenset()
            kept = [m for m in message_ids if m in allowed_ids]
            all_empty = all(m in empty_ids for m in outside)
            if _empty_drop_tolerant_enabled() and all_empty and kept:
                tolerated_empty = outside
                message_ids = kept
                _log("cortex.contract.empty_drop_tolerated",
                     run_ref=run_ref,
                     conversation_uid=conv_uid, atom_path=prefix,
                     tolerated_ids=sorted(set(outside)),
                     kept_ids=len(kept))
            else:
                # Near-miss B (fix round-1, C8) : le SEUL matériau qui permette
                # de savoir, pendant le soak, si B a servi / aurait servi et
                # pourquoi il a refusé. Émis flag ON comme flag OFF (log pur,
                # aucune incidence sur la validation).
                max_id = pack_entry.get("max_id")
                _log("cortex.contract.foreign_message_ids",
                     run_ref=run_ref, conversation_uid=conv_uid, atom_path=prefix,
                     n_outside=len(outside), n_kept=len(kept),
                     n_outside_empty=sum(1 for m in outside if m in empty_ids),
                     n_outside_beyond_max=sum(
                         1 for m in outside
                         if isinstance(max_id, int) and m > max_id),
                     reason=("flag_off" if not _empty_drop_tolerant_enabled()
                             else "not_all_empty" if not all_empty
                             else "no_rendered_id_left"),
                     empty_drop_armed=_empty_drop_tolerant_enabled())
                errors.append(f"foreign_message_ids:{conv_uid}")

    if errors:
        return None, errors, n_stripped, []

    cleaned = {
        "kind": kind,
        "scope": scope,
        "key": key,
        "value": value,
        "rationale": rationale,
        "confidence_score": confidence_score,
        "tags": list(tags),
        "supersede_key_hint": supersede_key_hint,
        # FIX B : provenance NETTOYÉE — les ids vides tolérés en sont retirés
        # (`message_ids` a été réduit aux ids réellement rendus plus haut).
        "message_ids": list(message_ids),
    }
    return cleaned, [], n_stripped, tolerated_empty
