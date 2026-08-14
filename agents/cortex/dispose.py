"""Le DISPOSANT — applique déterministement un document `cortex-dispose/1`.

« Le LLM propose, le code dispose » : ce module possède TOUTES les écritures.
Pour chaque conversation du document (déjà validé par `contract.py`) :
politique HYBRID (code) → dédup sémantique backstop → POST → résolution 409
OBLIGATOIRE → avance du curseur APRÈS durabilité des atomes, commit PAR
conversation (l'unité atomique de reprise).

Sémantique d'échec :
  - `AtomsApiDown` remonte au caller (cycle) → status `dispose_interrupted`,
    curseur de la conversation en cours NON avancé, reprise idempotente au
    prochain cycle (les re-POST tombent en 409 → confirmed).
  - un atome individuellement invalide vis-à-vis de l'API (422 imprévu =
    dérive de contrat) est quarantiné (compté + détail en `progress`), les
    autres continuent.

Oracle de couverture — décision TERMINALE motivée exigée par
conversation PRÉSENTÉE, jamais un silence :
  - `atoms` non-vide            -> COVERED : dispose + avance le curseur.
  - `atoms` vide + `no_new_knowledge=true` -> attestation explicite : avance
    le curseur quand même (rien à écrire, mais décision motivée).
  - `atoms` vide nu, OU la conversation est absente du document -> OMISSION :
    curseur FIGÉ (jamais avancé), `retry_count` incrémenté via le compteur
    EXISTANT (`curator_lib_v2.mark_curation_failed`, remis à 0 par tout
    succès `advance_cursor`) -> re-présentation naturelle au prochain cycle.
    3 omissions CONSÉCUTIVES de la même conversation -> PARK immédiat
    (`curator_lib_v2.park_conversation`, force `retry_count>=5`, hors gate)
    + `progress[uid]["parked"] = True` pour que le caller (cycle.py) alerte.
    (flag `ARAC_DISPOSE_COVERAGE_V2` OFF par défaut) : le
    park est remplacé par une branche de COUVERTURE — drain traçé (exclusion
    motivée + curseur au max présenté) si la tranche était PLEINEMENT
    présentée, backoff sans park si elle était TRONQUÉE ; cf constantes
    LOW_YIELD_* et docstring de `_dispose_omitted`.
Les 4 compteurs `coverage_*` (mappés sur les colonnes `run_receipts` 0027)
vérifient l'invariant arithmétique presented == covered + no_new_knowledge +
omitted.

Revue humaine : chaque disposition qui n'aboutit PAS à une
mémoire durable (kept_lower_confidence, atom_quarantine, policy_skip,
coverage_omitted) alimente `arac.digestion_review_queue` via
`agents/cortex/review_queue.py` — best-effort (une file indisponible ne
casse jamais la digestion, cf docstring de ce module).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from agents.cortex import atoms_client as default_api
from agents.cortex import policy
from agents.cortex import review_queue
# Importé par valeur, PAS via `review_queue.…` : les tests remplacent le
# module par un double, et le placeholder doit rester le vrai.
from agents.cortex.review_queue import PLACEHOLDER_SCOPE
from agents.cortex.dedup_thresholds import get_threshold, is_ceremony_key, key_sha8
from app.journal import sha8
from agents.lib import curator_lib_v2

logger = logging.getLogger("arac.cortex.dispose")

# Backstop sémantique — seuil ROUTÉ par espace de représentation
# (agents/cortex/dedup_thresholds.py). Le chemin SERVI est l'espace
# v1 (embeddings bruts memory_atoms, design §3 : cosine >= 0.92 <=>
# distance <= 0.08) — valeur et comportement INCHANGÉS. La constante v2
# (0.0124, espace rm1-fold-a50) est livrée INERTE et ne s'arme qu'avec I3
# (recall dédup classé dans l'espace fold) au GO prod. Le carve-out
# cérémonie (CEREMONY_RE) ne s'applique qu'à l'espace FOLD : AUCUN
# carve-out actif sur le chemin v1 servi aujourd'hui — `is_ceremony_key`
# n'est utilisé ici que pour l'OBSERVABILITÉ (log d'armement B
# `dispose.semantic_dup`), jamais dans la décision.
SEMANTIC_DISTANCE_MAX = get_threshold("v1")
RESOLVE_RACE_RETRIES = 3

# Oracle de couverture : nombre d'omissions CONSÉCUTIVES (même
# conversation, compteur `retry_count` remis à 0 par tout succès) au-delà
# duquel on PARK plutôt que de continuer à re-présenter en pure perte.
OMISSION_PARK_THRESHOLD = 3

# --- — couverture v2 des omissions, flag OFF par défaut --
# Constat : le poison (foreign_ids) passe par le chemin
# QUARANTAINE (cycle.py), JAMAIS par `_dispose_omitted` — le park sur 3
# omissions ne se déclenche donc TOUJOURS que sur du low-yield ou une tranche
# tronquée, jamais sur du poison. Flag ON, la 3e omission branche sur la
# COUVERTURE de la tranche (`presented[uid]["fully_presented"]`, threadée par
# pack.py) :
#   - tranche PLEINEMENT présentée >= 3× sans atome -> DRAIN TRACÉ : curseur
#     avancé au max PRÉSENTÉ + reçu d'exclusion motivée (colonnes 0023),
#     jamais park (fin de la fuite DEAD_LETTER silencieuse + du re-gaspillage
#     budget dépensé) ;
#   - tranche TRONQUÉE (géant > budget pack) -> l'omission ne compte JAMAIS
#     vers le seuil : backoff plafonné (`defer_conversation`), jamais park.
# Flag OFF : comportement bit-identique à l'origine (park à la 3e omission).
#
# Fix round-1 (revue sceptique) — DEUX gardes-fous du cas 1 :
#   1. le seuil « >= 3 présentations COMPLÈTES » est compté par un compteur
#      DÉDIÉ (`curator_lib_v2.mark_full_omission`, marqueur dans
#      last_curation_error — AUCUNE migration), JAMAIS par `retry_count`
#      (compteur partagé à trois sémantiques : defers tronqués, punitions
#      quarantaine, échecs — le conflater excluait après UNE seule
#      présentation complète, avec un motif factuellement faux) ;
#   2. garde DURE `atoms_generated == 0` (même règle que le value-gate) :
#      une conversation qui a DÉJÀ produit des atomes n'est JAMAIS exclue —
#      au seuil, son delta présenté est drainé (curseur avancé) mais elle
#      RESTE dans le gate pour son contenu futur.
#
# `exclusion_category` : la CHECK 0023 est une taxonomie FERMÉE (5 valeurs) —
# le libellé décisionnel « low_yield_omission » la violerait (AUCUNE migration,
# règle). On mappe sur 'no_curable_content' (sémantique la plus proche :
# 3 présentations COMPLÈTES attestent qu'il n'y a rien à curer) ; le motif
# mécanique précis `low_yield_omission:...` vit dans `exclusion_reason`.
LOW_YIELD_EXCLUSION_CATEGORY = "no_curable_content"
LOW_YIELD_EXCLUSION_BY = "cortex-dispose"  # composant, jamais une PII (V0.107)


def _coverage_v2_enabled() -> bool:
    """Flag env PUR, lu à chaque appel (armement au déploiement systemd)."""
    return os.environ.get(
        "ARAC_DISPOSE_COVERAGE_V2", "").strip().lower() in ("1", "true", "yes", "on")


def _log(event: str, **kw: Any) -> None:
    import json as _json

    logger.info(_json.dumps({"event": event, **kw}, ensure_ascii=False, default=str))


def _sanitize_error_body(body: Any) -> Any:
    """Résumé de diagnostic d'un corps d'erreur API SANS jamais rejouer une
    valeur soumise (invariant I5 / règle V0.107).

    Sur un 422 FastAPI/pydantic-v2 PAR DÉFAUT (aucun handler
    `RequestValidationError` custom dans app/), chaque entrée de
    `body["detail"]` porte un champ `input` qui ÉCHO la valeur soumise —
    donc potentiellement la `value` de l'atome (texte de conversation).
    On ne conserve que `type` + `loc` (noms de champs, jamais des valeurs),
    suffisants pour diagnostiquer la dérive de contrat. Tout autre corps
    est réduit à sa FORME (fail-toward-silence) : le candidat complet reste
    disponible pour la revue humaine via `digestion_review_queue` (DB,
    accès contrôlé), jamais via journald.
    """
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, list):
        out = []
        for err in detail[:8]:
            if isinstance(err, dict):
                loc = err.get("loc")
                out.append({
                    "type": err.get("type"),
                    "loc": [str(part) for part in loc][:6]
                    if isinstance(loc, (list, tuple)) else None,
                })
            else:
                out.append({"type": type(err).__name__})
        return out
    return {"body_type": type(body).__name__}


class DisposeTotals(dict):
    """Compteurs du run (mappés 1:1 sur les colonnes de run_receipts)."""

    KEYS = ("atoms_created", "atoms_superseded", "atoms_confirmed",
            "atoms_kept_lower_confidence", "atoms_policy_skips",
            "atoms_quarantined", "conflicts_409",
            # Oracle de couverture (colonnes 0027) : invariant
            # coverage_presented == coverage_covered + coverage_no_new_knowledge
            # + coverage_omitted, vérifié par les tests (jamais en prod, coûteux).
            "coverage_presented", "coverage_covered",
            "coverage_no_new_knowledge", "coverage_omitted")

    def __init__(self) -> None:
        super().__init__({k: 0 for k in self.KEYS})

    def bump(self, key: str, n: int = 1) -> None:
        self[key] += n


def _incumbent_id(incumbent: dict[str, Any] | None) -> str | None:
    """Stringifie `incumbent["id"]` (uuid côté API) pour la review-queue,
    ou `None` si pas d'incumbent — jamais de KeyError sur un dict partiel."""
    if not incumbent:
        return None
    val = incumbent.get("id")
    return str(val) if val is not None else None


async def _resolve_against(db, incumbent: dict[str, Any], payload: dict[str, Any],
                           totals: DisposeTotals, api, *, run_ref: str,
                           conversation_uid: str) -> str:
    """Résolution OBLIGATOIRE contre un incumbent actif (design §4).

    Retourne la disposition : 'confirmed' | 'superseded' | 'kept' | 'quarantined'.
    Chaque issue `kept`/`quarantined` alimente `arac.digestion_review_queue`
    (best-effort — cf `review_queue.insert_review_row`).
    """
    if incumbent.get("kind") != payload["kind"]:
        totals.bump("atoms_quarantined")
        # Clé JAMAIS en clair : une clé-slug peut porter une PII (prénom
        # opérateur) — sha8 seulement (invariant I5 / V0.107), comme le log
        # d'armement B `dispose.semantic_dup` situé sur le même chemin.
        #
        # NI LE DOMAINE. L'invariant était appliqué à MOITIÉ ici : la clé
        # hachée, le `scope` en clair, sur les quatre lignes de ce fichier.
        # Un domaine n'est pas un identifiant technique — c'est une phrase que
        # le propriétaire a écrite lui-même pour nommer un pan de sa vie, et la
        # liste des domaines est le plan de son existence. `ops/uninstall_check
        # .sh` le disait déjà (« c'est la forme de la mémoire de quelqu'un »)
        # pendant que ces lignes l'imprimaient. L'argument complet, et la
        # décision, sont dans `app/journal.py`.
        _log("dispose.identity_kind_mismatch", scope_sha8=sha8(payload["scope"]),
             key_sha8=key_sha8(payload["key"]),
             incumbent_kind=incumbent.get("kind"),
             candidate_kind=payload["kind"])
        await review_queue.insert_review_row(
            db, run_ref, conversation_uid, "atom_quarantine", payload,
            _incumbent_id(incumbent), payload["scope"], payload["kind"])
        return "quarantined"

    if policy.normalize_value(incumbent.get("value") or "") == \
       policy.normalize_value(payload["value"]):
        api.confirm_unchanged(incumbent)
        totals.bump("atoms_confirmed")
        return "confirmed"

    inc_score = incumbent.get("confidence_score")
    if payload["confidence_score"] >= (inc_score if inc_score is not None else 0):
        for attempt in range(RESOLVE_RACE_RETRIES):
            status, _body = api.supersede(
                str(incumbent["id"]),
                new_value=payload["value"],
                new_rationale=payload.get("rationale"),
                new_confidence_score=payload["confidence_score"],
                new_node_id=payload["node_id"],
                new_source_ref=payload["source_ref"],
            )
            if status in (200, 201):
                totals.bump("atoms_superseded")
                return "superseded"
            if status == 409:
                # course : l'incumbent a changé sous nos pieds — re-fetch.
                fresh = api.get_by_key(payload["scope"], incumbent["key"])
                if fresh is None:
                    break  # slot libéré — le caller re-POSTera au prochain cycle
                incumbent = fresh
                if policy.normalize_value(incumbent.get("value") or "") == \
                   policy.normalize_value(payload["value"]):
                    api.confirm_unchanged(incumbent)
                    totals.bump("atoms_confirmed")
                    return "confirmed"
                continue
            break  # 4xx inattendu -> quarantaine d'atome
        totals.bump("atoms_quarantined")
        # sha8 seulement — même invariant I5 que ci-dessus.
        _log("dispose.supersede_unresolved", scope_sha8=sha8(payload["scope"]),
             key_sha8=key_sha8(payload["key"]))
        await review_queue.insert_review_row(
            db, run_ref, conversation_uid, "atom_quarantine", payload,
            _incumbent_id(incumbent), payload["scope"], payload["kind"])
        return "quarantined"

    # Candidat plus faible que l'incumbent : keep + compteur AUDITÉ (la
    # fossilisation résiduelle se voit dans les receipts, cf design §4.5).
    totals.bump("atoms_kept_lower_confidence")
    await review_queue.insert_review_row(
        db, run_ref, conversation_uid, "kept_lower_confidence", payload,
        _incumbent_id(incumbent), payload["scope"], payload["kind"])
    return "kept"


async def _dispose_atom(db, atom: dict[str, Any], payload: dict[str, Any],
                        totals: DisposeTotals, api, *, run_ref: str,
                        conversation_uid: str) -> str:
    """Un atome validé politique -> disposition terminale. Chaque quarantaine
    alimente `arac.digestion_review_queue` (best-effort)."""
    # 1. Hint explicite du LLM : mise à jour d'un fait connu (ALREADY-KNOWN).
    hint = atom.get("supersede_key_hint")
    if hint and hint != payload["key"]:
        incumbent = api.get_by_key(payload["scope"], str(hint))
        if incumbent is not None:
            return await _resolve_against(
                db, incumbent, payload, totals, api,
                run_ref=run_ref, conversation_uid=conversation_uid)
        # hint pointant dans le vide -> POST normal.

    # 2. Backstop sémantique : un quasi-doublon sous une AUTRE clé se résout
    #    contre l'incumbent au lieu de créer un doublon (>= 0.92, même kind).
    try:
        hits = api.recall(payload["value"], scope=payload["scope"], k=3,
                          consumer="cortex_dedup")  # : profil CE déclaré
    except default_api.AtomsApiDown:
        raise
    for h in hits or []:
        if (h.get("kind") == payload["kind"]
                and h.get("key") != payload["key"]
                and float(h.get("distance", 1.0)) <= SEMANTIC_DISTANCE_MAX):
            incumbent = api.get_by_key(h["scope"], h["key"])
            if incumbent is not None:
                # Log d'armement B : CHAQUE tir du backstop est
                # tracé avec les flags cérémonie — observabilité PURE
                # (aucun changement de décision), fait grossir le set
                # positifs/négatifs pour rendre AC2 évaluable au soak.
                # try/finally : le tir est loggé même si la résolution est
                # interrompue (AtomsApiDown → action="interrupted").
                # Clés JAMAIS en clair : une clé-slug PEUT porter une PII
                # (prénom opérateur — vérifié dans le corpus réel), donc
                # sha8 seulement (invariant I5 / règle V0.107, helper
                # `dedup_thresholds.key_sha8`). Les flags cérémonie sont
                # calculés sur la clé BRUTE avant hachage.
                action = "interrupted"
                try:
                    action = await _resolve_against(
                        db, incumbent, payload, totals, api,
                        run_ref=run_ref, conversation_uid=conversation_uid)
                finally:
                    _log("dispose.semantic_dup", space="v1",
                         distance=h.get("distance"),
                         key_candidate_sha8=key_sha8(payload["key"]),
                         key_incumbent_sha8=key_sha8(h["key"]),
                         ceremony_candidate=is_ceremony_key(payload["key"]),
                         ceremony_incumbent=is_ceremony_key(h.get("key")),
                         scope_sha8=sha8(payload["scope"]), action=action)
                return action

    # 3. POST — la dédup exacte (desc_hash) et l'unicité (scope,key) font foi.
    status, _body = api.post_atom(payload)
    if status in (200, 201):
        totals.bump("atoms_created")
        return "created"
    if status == 409:
        totals.bump("conflicts_409")
        incumbent = api.get_by_key(payload["scope"], payload["key"])
        if incumbent is None:
            # 409 sans incumbent actif (course rarissime) : un seul re-POST.
            status2, _ = api.post_atom(payload)
            if status2 in (200, 201):
                totals.bump("atoms_created")
                return "created"
            totals.bump("atoms_quarantined")
            await review_queue.insert_review_row(
                db, run_ref, conversation_uid, "atom_quarantine", payload,
                None, payload["scope"], payload["kind"])
            return "quarantined"
        return await _resolve_against(
            db, incumbent, payload, totals, api,
            run_ref=run_ref, conversation_uid=conversation_uid)
    # 422/4xx : dérive de contrat malgré policy_check -> quarantaine d'atome.
    # Clé en sha8 + corps ASSAINI (invariant I5 / V0.107) : le 422
    # pydantic-v2 par défaut écho la valeur soumise dans `detail[i].input`
    # (texte de conversation potentiel) — cf `_sanitize_error_body`.
    totals.bump("atoms_quarantined")
    _log("dispose.api_contract_drift", status=status,
         scope_sha8=sha8(payload["scope"]),
         key_sha8=key_sha8(payload["key"]), detail=_sanitize_error_body(_body))
    await review_queue.insert_review_row(
        db, run_ref, conversation_uid, "atom_quarantine", payload,
        None, payload["scope"], payload["kind"])
    return "quarantined"


async def _dispose_covered(
    db, conv: dict[str, Any], uid: str, meta: dict[str, Any], atoms: list[Any],
    totals: DisposeTotals, api, *, run_ref: str, node_id: str, valid_scopes: frozenset[str],
) -> dict[str, Any]:
    """Conversation COVERED (atoms non-vide) : dispose chaque atome puis
    avance le curseur au max PRÉSENTÉ. Retourne l'entrée `progress[uid]`.

    Chaque `policy_skip` alimente `arac.digestion_review_queue` (best-effort) — l'atome brut du LLM (pas encore `finalize_atom`,
    puisque rejeté AVANT construction du payload POST)."""
    dispositions: list[dict[str, Any]] = []
    for atom in atoms:
        verdict = policy.check_atom(atom, valid_scopes=valid_scopes)
        if not verdict.ok:
            totals.bump("atoms_policy_skips")
            dispositions.append({"key": atom.get("key"),
                                 "disposition": f"policy_skip:{verdict.reason}"})
            await review_queue.insert_review_row(
                db, run_ref, uid, "policy_skip", atom, None,
                atom.get("scope") or "unknown", atom.get("kind") or "unknown")
            continue
        payload = policy.finalize_atom(
            atom, node_id=node_id, run_ref=run_ref,
            conversation_uid=uid, source_type=meta.get("source_type", ""))
        outcome = await _dispose_atom(
            db, atom, payload, totals, api,
            run_ref=run_ref, conversation_uid=uid)
        dispositions.append({"key": payload["key"], "disposition": outcome})

    # Tous les atomes de la conversation ont une disposition TERMINALE
    # -> avance du curseur au max PRÉSENTÉ (jamais les dires du LLM),
    # commit = l'unité atomique de reprise.
    created_here = sum(1 for d in dispositions
                       if d["disposition"] in ("created", "superseded"))
    await curator_lib_v2.advance_cursor(
        db, meta["conversation_id"], int(meta["max_id"]),
        atoms_generated=created_here)
    await db.commit()
    totals.bump("coverage_covered")
    _log("dispose.conversation_done", conversation_uid=uid,
         n_atoms=len(dispositions), cursor=meta["max_id"], coverage="covered")
    return {"dispositions": dispositions, "cursor": int(meta["max_id"]),
            "coverage": "covered"}


async def _dispose_no_new_knowledge(
    db, uid: str, meta: dict[str, Any], totals: DisposeTotals,
) -> dict[str, Any]:
    """Attestation explicite `no_new_knowledge=true` : décision terminale
    motivée, RIEN à écrire, mais le curseur avance quand même."""
    await curator_lib_v2.advance_cursor(
        db, meta["conversation_id"], int(meta["max_id"]), atoms_generated=0)
    await db.commit()
    totals.bump("coverage_no_new_knowledge")
    _log("dispose.conversation_done", conversation_uid=uid, n_atoms=0,
         cursor=meta["max_id"], coverage="no_new_knowledge")
    return {"dispositions": [], "cursor": int(meta["max_id"]),
            "coverage": "no_new_knowledge"}


async def _dispose_omitted(
    db, uid: str, meta: dict[str, Any], totals: DisposeTotals, *, reason: str,
    run_ref: str,
) -> dict[str, Any]:
    """OMISSION (atoms=[] nu, ou conversation absente du document) : curseur
    FIGÉ, `retry_count` incrémenté (compteur EXISTANT, remis à 0 par tout
    succès) -> 3 omissions CONSÉCUTIVES = PARK immédiat.

    Alimente `arac.digestion_review_queue` (`coverage_omitted`,
    best-effort) — `proposed_atom` n'est PAS un candidat d'atome ici (la
    conversation n'a jamais atteint la digestion) mais un petit dict de
    métadonnées déterministe (motif + retry_count), placeholders
    `scope=PLACEHOLDER_SCOPE`/`kind="coverage_omitted"` (même pattern que
    `oversized_message`, cf `review_queue.insert_review_row`).

    (`ARAC_DISPOSE_COVERAGE_V2` — OFF par défaut, cf
    constantes du module) : flag ON, la décision au seuil dépend de la
    COUVERTURE de la tranche (`meta["fully_presented"]`) — drain traçé
    (exclusion motivée + curseur avancé au max PRÉSENTÉ) si pleinement
    présentée, backoff sans park si tronquée. Flag OFF : bit-identique au comportement d'origine
    (park à la 3e omission consécutive)."""
    coverage_v2 = _coverage_v2_enabled()
    fully_presented = bool(meta.get("fully_presented"))

    if coverage_v2 and not fully_presented:
        # Cas 2 — tranche TRONQUÉE (géant > budget pack) : l'omission ne
        # prouve rien, elle ne compte JAMAIS vers le seuil de park. Backoff
        # plafonné (retry_count <= 4, reste DANS le gate), JAMAIS park.
        new_retry = await curator_lib_v2.defer_conversation(
            db, meta["conversation_id"], error=f"{reason}:truncated_slice")
        totals.bump("coverage_omitted")
        await review_queue.insert_review_row(
            db, run_ref, uid, "coverage_omitted",
            {"reason": reason, "retry_count": new_retry,
             "slice": "truncated", "deferred": True},
            None, PLACEHOLDER_SCOPE, "coverage_omitted")
        await db.commit()
        _log("dispose.conversation_omitted", conversation_uid=uid,
             retry_count=new_retry, parked=False, deferred=True,
             fully_presented=False, reason=reason)
        return {"dispositions": [], "cursor": None, "coverage": "omitted",
                "retry_count": new_retry, "deferred": True}

    if coverage_v2:
        # Cas 1 — tranche PLEINEMENT présentée et omise. Fix round-1 : le
        # seuil est compté par le compteur DÉDIÉ de présentations complètes
        # consécutives (`mark_full_omission`), JAMAIS par `retry_count`
        # (conflaté par defers tronqués/punitions quarantaine — et gonflé
        # PRÉ-FLIP en prod : au flip ON toute conversation repart à
        # streak=1, jamais une exclusion héritée d'un autre compteur).
        new_retry, streak = await curator_lib_v2.mark_full_omission(
            db, meta["conversation_id"], error=reason)
        totals.bump("coverage_omitted")
        threshold_hit = streak >= OMISSION_PARK_THRESHOLD
        excluded = False
        drained = False
        if threshold_hit:
            # >= 3 présentations COMPLÈTES consécutives sans atome : DRAIN
            # TRACÉ (jamais silencieux, jamais park). Curseur avancé au max
            # PRÉSENTÉ (garde-fou : jamais au-delà de ce que le LLM a
            # réellement vu). Garde DURE atoms_generated (LUE AVANT
            # advance_cursor, même tx) : une conversation qui a déjà
            # produit n'est JAMAIS exclue — drain du delta présenté
            # seulement, elle RESTE dans le gate pour son contenu futur.
            atoms_prior = await curator_lib_v2.get_atoms_generated(
                db, meta["conversation_id"])
            await curator_lib_v2.advance_cursor(
                db, meta["conversation_id"], int(meta["max_id"]),
                atoms_generated=0)
            drained = True
            if atoms_prior == 0:
                # Reçu d'exclusion motivée (0023, réversible, contenu
                # conservé raw_messages). First-writer-wins : un motif déjà
                # consigné n'est jamais écrasé (retour False -> loggé).
                applied = await curator_lib_v2.mark_conversation_excluded(
                    db, meta["conversation_id"],
                    category=LOW_YIELD_EXCLUSION_CATEGORY,
                    reason=(f"low_yield_omission:{streak}_full_presentations_"
                            f"no_atoms:run={run_ref}"),
                    by=LOW_YIELD_EXCLUSION_BY)
                excluded = bool(applied)
                if not applied:
                    _log("dispose.exclusion_skipped_existing_motive",
                         conversation_uid=uid)
            else:
                _log("dispose.drain_without_exclusion", conversation_uid=uid,
                     atoms_generated=atoms_prior, full_omission_streak=streak)
        await review_queue.insert_review_row(
            db, run_ref, uid, "coverage_omitted",
            {"reason": reason, "retry_count": new_retry,
             "full_omission_streak": streak,
             **({"excluded": True,
                 "exclusion_category": LOW_YIELD_EXCLUSION_CATEGORY}
                if excluded else {}),
             **({"drained": True} if drained else {})},
            None, PLACEHOLDER_SCOPE, "coverage_omitted")
        await db.commit()
        _log("dispose.conversation_omitted", conversation_uid=uid,
             retry_count=new_retry, full_omission_streak=streak,
             parked=False, excluded=excluded, drained=drained, reason=reason)
        entry: dict[str, Any] = {"dispositions": [], "cursor": None,
                                 "coverage": "omitted",
                                 "retry_count": new_retry,
                                 "full_omission_streak": streak}
        if drained:
            entry["cursor"] = int(meta["max_id"])
            entry["drained"] = True
        if excluded:
            entry["excluded"] = True
        return entry

    # Flag OFF : bit-identique au comportement d'origine (compteur retry_count partagé,
    # park à la 3e omission consécutive).
    new_retry = await curator_lib_v2.mark_curation_failed(
        db, meta["conversation_id"], error=reason)
    totals.bump("coverage_omitted")
    parked = False
    if new_retry >= OMISSION_PARK_THRESHOLD:
        parked = True
        await curator_lib_v2.park_conversation(
            db, meta["conversation_id"],
            error=f"cortex_omission_park:{new_retry}_consecutive")
    await review_queue.insert_review_row(
        db, run_ref, uid, "coverage_omitted",
        {"reason": reason, "retry_count": new_retry},
        None, PLACEHOLDER_SCOPE, "coverage_omitted")
    await db.commit()
    _log("dispose.conversation_omitted", conversation_uid=uid,
         retry_count=new_retry, parked=parked, excluded=False,
         reason=reason)
    entry = {"dispositions": [], "cursor": None,
             "coverage": "omitted", "retry_count": new_retry}
    if parked:
        entry["parked"] = True
    return entry


async def dispose_document(
    db,
    doc: dict[str, Any],
    presented: dict[str, dict[str, Any]],
    *,
    run_ref: str,
    node_id: str = "arac-curator",
    valid_scopes: frozenset[str],
    api=default_api,
) -> tuple[DisposeTotals, dict[str, Any]]:
    """Applique le document. Retourne (totals, progress_par_conversation).

    `presented[uid]` = {"conversation_id", "max_id", "source_type", ...}
    (construit par pack.py, source de vérité de l'avance de curseur — jamais
    les dires du LLM).

    Oracle de couverture (cf docstring module) : pour CHAQUE
    conversation présentée, disposition TERMINALE — covered / no_new_knowledge
    / omitted — jamais un silence non comptabilisé. Un `progress[uid]` avec
    `"parked": True` signale au caller (cycle.py) qu'une alerte est due
    (3 omissions consécutives).

    Lève `AtomsApiDown` si l'API tombe : le caller marque
    `dispose_interrupted` ; les conversations déjà committées sont acquises.
    """
    totals = DisposeTotals()
    progress: dict[str, Any] = {}
    seen_uids: set[str] = set()

    for conv in doc.get("conversations", []):
        uid = conv["conversation_uid"]
        meta = presented[uid]  # garanti par contract.validate_document
        seen_uids.add(uid)
        totals.bump("coverage_presented")

        atoms = conv.get("atoms") or []
        if atoms:
            progress[uid] = await _dispose_covered(
                db, conv, uid, meta, atoms, totals, api,
                run_ref=run_ref, node_id=node_id, valid_scopes=valid_scopes)
        elif conv.get("no_new_knowledge") is True:
            progress[uid] = await _dispose_no_new_knowledge(db, uid, meta, totals)
        else:
            progress[uid] = await _dispose_omitted(
                db, uid, meta, totals, reason="cortex_omission:atoms_empty",
                run_ref=run_ref)

    # Conversations PRÉSENTÉES mais jamais MENTIONNÉES par le LLM (omission
    # TOTALE, cf contract.validate_document._omitted_uids) : même traitement.
    omitted_missing = doc.get("_omitted_uids")
    if omitted_missing is None:
        omitted_missing = sorted(uid for uid in presented if uid not in seen_uids)
    for uid in omitted_missing:
        if uid in seen_uids:
            continue
        meta = presented[uid]
        totals.bump("coverage_presented")
        progress[uid] = await _dispose_omitted(
            db, uid, meta, totals, reason="cortex_omission:absent_from_doc",
            run_ref=run_ref)

    return totals, progress
