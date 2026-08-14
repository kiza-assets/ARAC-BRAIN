"""Routeur de contexte — `task_context_builder` (Phase H).

Chemin STANDARD de préparation du contexte agent. Le cerveau peut être immense ;
le contexte rendu doit être PETIT, EXACT, RÉCENT, SOURCÉ, BORNÉ, UTILE.

Propriétés (déterministes, donc REPRODUCTIBLES) :
  - mémoires métier et code SÉPARÉES ;
  - budgets de tokens STRICTS (global 2k / projet 4k / mémoire 8k par défaut) ;
  - max 3 passes de retrieval ;
  - PROVENANCE de chaque élément injecté ;
  - exclusion AUTOMATIQUE + TRACÉE du bruit (superseded, autre projet, doublons,
    logs/diffs/lockfiles/builds/caches, détails inutiles) ;
  - détection de contradiction + incertitudes explicites ;
  - aucun appel réseau/LLM ici (pur) : ordonnancement et budget déterministes.

Sortie = dict au schéma mission :
  {task_summary, project_context, business_memory, code_memory, contradictions,
   uncertainties, excluded_memory, token_budget, provenance, freshness_report,
   warnings}
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from app.services import business_memory as bm
from app.services import code_brain as cb


# --- Budgets ----------------------------------------------------------------
@dataclass
class TokenBudget:
    global_max: int = 2000
    project_max: int = 4000
    memory_max: int = 8000
    tool_output_max: int = 2000
    max_passes: int = 3
    max_results: int = 40


def estimate_tokens(text: str, counter: Callable[[str], int] | None = None) -> int:
    """Estimation déterministe (~4 chars/token) sauf si un compteur réel est injecté."""
    if counter is not None:
        return counter(text)
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def _truncate_to_tokens(
    text: str, max_tokens: int, counter: Callable[[str], int] | None = None,
) -> tuple[str, bool]:
    """Tronque `text` pour que estimate_tokens(résultat) <= max_tokens. Renvoie
    (texte_tronqué, a_été_tronqué). Robuste même avec un compteur réel (on ne
    se contente pas d'une borne en CHARS : on rétrécit jusqu'à passer le budget)."""
    if estimate_tokens(text, counter) <= max_tokens:
        return text, False
    # borne haute en chars puis rétrécissement (compteur réel = tokens/char variable)
    cut = min(len(text), max_tokens * 4)
    out = text[:cut]
    while out and estimate_tokens(out, counter) > max_tokens:
        out = out[: max(0, int(len(out) * 0.8)) - 1]
    return out, True


# Motifs de BRUIT exclus du contexte code (lockfiles, builds, caches, binaires…).
_NOISE_PATH_RE = re.compile(
    r"(?:^|/)(?:\.git|\.venv|venv|__pycache__|node_modules|\.pytest_cache|build|dist|"
    r"\.mypy_cache)(?:/|$)"
    r"|\.(?:lock|min\.js|map|pyc|so|bin|png|jpg|jpeg|gif|pdf|zip|gz)$"
    r"|(?:^|/)(?:package-lock\.json|poetry\.lock|yarn\.lock|requirements\.lock\.txt)$",
    re.IGNORECASE,
)


def _tokenize_query(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_]+", (text or "").lower()) if len(w) > 2}


def _keyword_hits(atom: "bm.BrainAtom", terms: set[str]) -> int:
    hay = f"{atom.key} {atom.value}".lower()
    return sum(1 for t in terms if t in hay)


# Marqueurs d'une tâche de REPRISE/élargissement (justifie le pass 2 « tout le
# projet actif » même sans mot-clé qui matche un atome précis).
_RESUME_MARKERS = {"reprend", "reprendre", "resume", "handoff", "continue", "continuer",
                   "etat", "état", "status", "point", "overview", "panorama"}


# --- Scoring (hybride : mots-clés + fraîcheur + confiance) -------------------
def _relevance(atom: bm.BrainAtom, terms: set[str], now: datetime) -> float:
    hay = f"{atom.key} {atom.value}".lower()
    hits = sum(1 for t in terms if t in hay)
    kw = hits / max(1, len(terms)) if terms else 0.0
    conf = (atom.confidence_score or 50) / 100.0
    fresh = 0.0 if bm.is_stale(atom, now) else 1.0
    # pondération : pertinence mots-clés dominante, puis confiance, puis fraîcheur.
    return round(2.0 * kw + 0.5 * conf + 0.3 * fresh, 6)


def _atom_provenance(atom: bm.BrainAtom) -> dict[str, Any]:
    src = atom.source_ref or {}
    return {
        "id": atom.id, "type": "business_atom", "kind": atom.kind,
        "scope": atom.scope, "node_id": atom.node_id,
        "source": (src.get("source_path") or src.get("uri") or src.get("type")
                   if isinstance(src, Mapping) else None),
        "observed_at": atom.observed_at.isoformat() if atom.observed_at else None,
    }


# --- Construction du contexte -----------------------------------------------
def build_task_context(
    request: Mapping[str, Any],
    *,
    atoms: Iterable[bm.BrainAtom] = (),
    code_index: cb.CodeIndex | None = None,
    now: datetime | None = None,
    budget: TokenBudget | None = None,
    counter: Callable[[str], int] | None = None,
) -> dict[str, Any]:
    """Construit le contexte borné. DÉTERMINISTE à `now` fixé -> reproductible.

    `now` défaut = horloge réelle UTC (la fraîcheur doit être évaluée contre le
    temps courant en prod ; les tests passent un `now` fixe pour la reproductibilité).
    """
    now = now or datetime.now(timezone.utc)
    budget = budget or TokenBudget()
    task = str(request.get("task", "")).strip()
    project = request.get("project")
    need_business = request.get("need_business", True)
    need_code = request.get("need_code", bool(request.get("repo")) or code_index is not None)
    terms = _tokenize_query(task)

    atoms = list(atoms)
    excluded: list[dict[str, Any]] = []
    warnings: list[str] = []

    # ---------- Mémoire MÉTIER ----------
    business: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    uncertainties: list[dict[str, Any]] = []

    if need_business:
        candidates, passes, relevant, active = _retrieve_business(
            atoms, project, terms, now, budget, excluded,
        )
        # contradictions sur TOUT l'ensemble ACTIF du projet (pas seulement les
        # atomes pertinents au mot-clé) : sinon un atome en conflit écarté par la
        # passe de pertinence ne serait jamais comparé -> contradiction MASQUÉE.
        for a, b in bm.find_contradictions(active):
            contradictions.append({"a": a, "b": b, "reason": "active_conflict"})
        # incertitudes : décisions sans source (jamais présentées comme vérité).
        for at in relevant:
            if at.kind in bm.DURABLE_KINDS and not _has_source(at):
                uncertainties.append({"id": at.id, "reason": "missing_source"})
        if not candidates:
            warnings.append("ambiguous_or_no_business_match")

        # Coupe budget mémoire (greedy par score décroissant, déterministe).
        used = 0
        for at in candidates:
            cost = estimate_tokens(at.value, counter) + 8
            if used + cost > budget.memory_max or len(business) >= budget.max_results:
                excluded.append({"id": at.id, "reason": "memory_budget", "tokens": cost})
                continue
            used += cost
            business.append({"id": at.id, "kind": at.kind, "key": at.key,
                             "value": at.value, "scope": at.scope,
                             "status": at.status, "confidence_score": at.confidence_score})
            provenance.append(_atom_provenance(at))
        business_tokens = used
    else:
        business_tokens = 0
        passes = 0

    # ---------- Mémoire CODE ----------
    code_memory: dict[str, Any] = {}
    code_tokens = 0
    if need_code and code_index is not None:
        code_memory, code_tokens, code_prov = _retrieve_code(
            task, terms, code_index, budget, excluded, counter,
        )
        provenance.extend(code_prov)
        if not code_memory.get("files") and not code_memory.get("symbols"):
            warnings.append("no_code_match")

    # ---------- Contexte projet (borné) ----------
    project_context, proj_truncated = _project_context(atoms, project, budget, counter)
    proj_tokens = estimate_tokens(str(project_context), counter)
    if proj_truncated:
        warnings.append("project_context_truncated")

    # ---------- Fraîcheur ----------
    selected_ids = {b["id"] for b in business}
    selected_atoms = [a for a in atoms if a.id in selected_ids]
    freshness = bm.freshness_report(selected_atoms, now) if selected_atoms else {"fresh": [], "stale": []}
    if freshness["stale"]:
        warnings.append("stale_memory_selected")

    if contradictions:
        warnings.append("contradictions_present")

    task_summary, summary_truncated = _truncate_to_tokens(task, budget.global_max, counter)
    if summary_truncated:
        warnings.append("task_summary_truncated")

    return {
        "task_summary": task_summary,
        "project_context": project_context,
        "business_memory": business,
        "code_memory": code_memory,
        "contradictions": contradictions,
        "uncertainties": uncertainties,
        "excluded_memory": excluded,
        "token_budget": {
            "global_max": budget.global_max,
            "project_max": budget.project_max,
            "memory_max": budget.memory_max,
            "business_tokens": business_tokens,
            "code_tokens": code_tokens,
            "project_tokens": proj_tokens,
            "retrieval_passes": passes,
            "max_passes": budget.max_passes,
            "within_budget": business_tokens <= budget.memory_max,
        },
        "provenance": provenance,
        "freshness_report": freshness,
        "warnings": warnings,
    }


# Clés reconnues comme marqueurs de SOURCE/PROVENANCE. Inclut le schéma générique
# ET le schéma réel des atomes prod ARAC (source_ref = curator_raw_id +
# message_indices + extracted_by + ingest_node) — calibré sur données prod (shadow
# Phase 2 : sans ces clés, les atomes prod sourcés étaient faussement « incertains »).
_SOURCE_KEYS = ("source_path", "path", "type", "uri", "id", "ref",
                "curator_raw_id", "extracted_by", "ingest_node", "conversation_id")


def _has_source(atom: bm.BrainAtom) -> bool:
    s = atom.source_ref
    if not isinstance(s, Mapping) or not s:
        return False
    return any(str(s.get(k) or "").strip() for k in _SOURCE_KEYS)


def _retrieve_business(atoms, project, terms, now, budget, excluded):
    """Jusqu'à `max_passes` passes. Trace les exclusions (autre projet / superseded
    / doublon). Retourne (candidats diversifiés+triés, nb_passes, pertinents_avant_
    diversité) — ce dernier sert à la détection de contradictions/incertitudes."""
    # Filtrage déterministe + traçage des exclusions structurelles.
    active: list[bm.BrainAtom] = []
    seen_dupe: set[str] = set()
    for a in atoms:
        if project is not None and a.project_of() != project:
            excluded.append({"id": a.id, "reason": "other_project", "project": a.project_of()})
            continue
        if a.status != bm.BrainStatus.ACTIVE.value:
            excluded.append({"id": a.id, "reason": f"status_{a.status}"})
            continue
        key = a.dedupe_key or bm.compute_dedupe_key(a.scope, a.kind, a.key)
        h = a.semantic_hash or bm.compute_semantic_hash(a.value)
        sig = (key, h)
        if sig in seen_dupe:
            excluded.append({"id": a.id, "reason": "duplicate"})
            continue
        seen_dupe.add(sig)
        active.append(a)

    is_resume = bool(terms & _RESUME_MARKERS)
    passes = 0
    selected: list[bm.BrainAtom] = []
    # Pass 1 (précis) : au moins un mot-clé de la tâche présent dans l'atome.
    passes += 1
    if terms:
        selected = [a for a in active if _keyword_hits(a, terms) >= 1]
    # Pass 2 (élargir) : tâche de REPRISE ou requête vide + projet ciblé -> projet actif.
    if not selected and project is not None and (not terms or is_resume) and passes < budget.max_passes:
        passes += 1
        selected = list(active)
    # Pass 3 (dernier recours) : préfixe de mot-clé (typo). Reste vide si vraiment
    # hors-sujet -> incertitude assumée (pas d'invention).
    if not selected and terms and passes < budget.max_passes:
        passes += 1
        selected = [a for a in active
                    if any(w.startswith(t[:4]) for t in terms if len(t) >= 4
                           for w in f"{a.key} {a.value}".lower().split())]

    # Tri déterministe : score desc, puis id asc (stable, reproductible).
    selected.sort(key=lambda a: (-_relevance(a, terms, now), a.id))
    # Diversité : 1 atome max par (scope,key) — évite la redondance.
    out, seen_key = [], set()
    for a in selected:
        k = (a.scope, a.key)
        if k in seen_key:
            excluded.append({"id": a.id, "reason": "diversity_dup_key"})
            continue
        seen_key.add(k)
        out.append(a)
    return out, passes, selected, active


def _retrieve_code(task, terms, index, budget, excluded, counter):
    """Code pertinent : symboles cités -> fichiers + tests + routes. Exclut le bruit."""
    files: list[dict[str, Any]] = []
    symbols: list[str] = []
    tests: set[str] = set()
    provenance: list[dict[str, Any]] = []
    tokens = 0
    seen_files: set[str] = set()

    # Budget tokens du code : borne DURE (comme la mémoire métier), pas seulement
    # un cap de résultats. Au-delà, on trace l'exclusion (jamais silencieux).
    code_budget = budget.memory_max
    # symboles dont le nom apparaît dans la tâche.
    for path, rec in index.files.items():
        if _NOISE_PATH_RE.search(path):
            excluded.append({"path": path, "reason": "noise_path"})
            continue
        for s in rec.symbols:
            short = s.name.split(".")[-1].lower()
            if short in terms and path not in seen_files:
                cost = estimate_tokens(path + " " + s.name, counter) + 8
                if tokens + cost > code_budget or len(files) >= budget.max_results:
                    excluded.append({"path": path, "reason": "code_budget", "tokens": cost})
                    seen_files.add(path)   # ne pas re-tenter ce fichier
                    break
                seen_files.add(path)
                symbols.append(s.name)
                for t in cb.symbol_to_tests(index, s.name):
                    tests.add(t)
                files.append({"path": path, "symbol": s.name, "module": rec.module})
                provenance.append({"type": "code_file", "path": path, "symbol": s.name,
                                   "sha256": rec.sha256})
                tokens += cost
                break
        if len(files) >= budget.max_results or tokens >= code_budget:
            break

    # routes citées par chemin.
    routes = []
    for path, rec in index.files.items():
        for r in rec.routes:
            if r.path.lower() in task.lower():
                routes.append({"method": r.method, "path": r.path, "handler": r.handler,
                               "file": path})

    return ({"files": files, "symbols": symbols, "tests": sorted(tests), "routes": routes},
            tokens, provenance)


def _project_context(atoms, project, budget, counter, max_kinds: int = 20):
    """Mini-résumé projet BORNÉ : compte d'atomes actifs par kind (pas de contenu).
    Renvoie (contexte, truncated). Si plus de `max_kinds` kinds OU si le rendu
    dépasse project_max, on tronque RÉELLEMENT (top kinds par compte) et on le
    signale — pas de warning fantôme."""
    if project is None:
        return {}, False
    counts: dict[str, int] = {}
    for a in atoms:
        if a.project_of() == project and a.status == bm.BrainStatus.ACTIVE.value:
            counts[a.kind] = counts.get(a.kind, 0) + 1
    truncated = False
    if len(counts) > max_kinds:
        top = dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:max_kinds])
        counts, truncated = top, True
    ctx = {"project": project, "active_atoms_by_kind": counts}
    # garde-fou budget : si même tronqué le rendu dépasse, on réduit encore.
    while counts and estimate_tokens(str(ctx), counter) > budget.project_max:
        counts.pop(min(counts, key=counts.get), None)
        ctx = {"project": project, "active_atoms_by_kind": counts}
        truncated = True
    return ctx, truncated


# --- Adaptateur recall (API) -> BrainAtom -> contexte borné -----------------
_DT_FIELDS = ("created_at", "updated_at", "observed_at", "last_verified_at", "confirmed_until")


def _parse_dt(v: Any) -> "datetime | None":
    """Parse une date ISO (string) en datetime aware, sinon passe-through/None."""
    if v is None or isinstance(v, datetime):
        return v
    if isinstance(v, str) and v.strip():
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def atoms_from_recall(api_atoms: Iterable[Mapping[str, Any]]) -> list["bm.BrainAtom"]:
    """Convertit des atomes au format API (/v1/atoms/recall) en BrainAtom.

    Tolère les champs absents (ex. colonnes 0013 non encore en BDD) et parse les
    dates ISO. `project` est dérivé du scope par BrainAtom.project_of().
    """
    out: list[bm.BrainAtom] = []
    for a in api_atoms:
        if not isinstance(a, Mapping):
            continue
        d = dict(a)
        for f in _DT_FIELDS:
            if f in d:
                d[f] = _parse_dt(d[f])
        # ids/enum -> str
        for f in ("id", "superseded_by", "supersedes", "kind", "scope", "status", "node_id"):
            if d.get(f) is not None:
                d[f] = str(d[f])
        if not d.get("id"):
            continue
        out.append(bm.BrainAtom.from_dict(d))
    return out


def route_recall(
    query: str,
    api_atoms: Iterable[Mapping[str, Any]],
    *,
    project: str | None = None,
    budget: TokenBudget | None = None,
    now: datetime | None = None,
    counter: Callable[[str], int] | None = None,
) -> dict[str, Any]:
    """Chemin standard : prend une sortie recall (atomes API) et renvoie un
    CONTEXTE BORNÉ (schéma `build_task_context`) — dédup, exclusions tracées,
    contradictions, provenance, budget. need_code=False (recall = mémoire métier).
    """
    atoms = atoms_from_recall(api_atoms)
    return build_task_context(
        {"task": query, "project": project, "need_business": True, "need_code": False},
        atoms=atoms, now=now, budget=budget, counter=counter,
    )
