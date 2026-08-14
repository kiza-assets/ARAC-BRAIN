"""Router Brain — endpoints READ-ONLY du « cerveau vivant » (v1, lecture seule).

Expose en lecture seule les moteurs du cerveau vivant (état courant, propositions,
santé, anti-dérive, sensibilité) construits dans `scripts/brain` + `scripts/memory`
+ `scripts/ops`. **Tous les endpoints sont GET.** Aucun verbe mutant, aucun POST de
production, aucune écriture mémoire/DB — uniquement des SELECT et des lectures de
fichiers de propositions confinés (gitignorés).

Auth : hérite du middleware Bearer global (app/auth.py) — le jeton porteur est exigé de
TOUTE requête, `127.0.0.1` compris ; seul `/healthz` est public. Le desserrage de la
boucle locale exige DEUX variables écrites (`ARAC_API_TRUST_LOOPBACK` + `_RAISON`). Ce
router N'AJOUTE aucune route mutante ni aucun contournement.

Provenance : chaque réponse porte `engine_version` / `generated_at`. Les contenus
sensibles ne sont jamais exposés en clair (rédaction héritée des moteurs).

Testabilité : les fournisseurs de données (`provide_atoms`, `provide_conversations`)
sont des dépendances FastAPI surchargeables (`app.dependency_overrides`) — les tests
HTTP n'ont donc besoin d'AUCUNE base de données.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from pydantic import BaseModel

from app.db import get_db

import arac_runtime

# Les moteurs de jugement. Tous PURS : aucun n'ouvre de connexion, aucun
# n'écrit. Cette route les orchestre, elle ne raisonne pas elle-même.
from app.brain import anti_drift as ad
from app.brain import brain_health_report as bhr
from app.brain import current_state_overview as cso
from app.brain import current_state_proposal_store as store
from app.brain import scope_discovery as sd
from app.brain import sensitivity_policy as sens

router = APIRouter()

DEFAULT_PROPOSAL_DIR = str(arac_runtime.var_dir() / "current_state_proposals_night")
BASELINE_PATH = str(arac_runtime.path("tests", "evals", "baseline.json"))

_ALL_ATOMS_SQL = (
    "SELECT id::text, kind, scope, key, status, source_ref, "
    "created_at::text, updated_at::text FROM arac.memory_atoms"
)
_CONV_SQL = "SELECT status, count(*) AS n FROM arac.raw_conversations GROUP BY status"


# ===========================================================================
# Fournisseurs de données (lecture seule, surchargeables en test)
# ===========================================================================
async def provide_atoms(db: Annotated[AsyncConnection, Depends(get_db)]) -> list[dict]:
    """SELECT read-only de tous les atomes (métadonnées ; jamais la `value`)."""
    async with db.cursor(row_factory=dict_row) as cur:
        await cur.execute(_ALL_ATOMS_SQL)
        return await cur.fetchall()


async def provide_conversations(db: Annotated[AsyncConnection, Depends(get_db)]) -> dict:
    """Compte des conversations par statut (lecture seule). {} si indisponible."""
    out: dict[str, int] = {}
    try:
        async with db.cursor(row_factory=dict_row) as cur:
            await cur.execute(_CONV_SQL)
            for r in await cur.fetchall():
                out[(r["status"] or "?").strip().lower()] = int(r["n"])
    except Exception:  # noqa: BLE001 — dégradation propre si la table manque
        return {}
    out["total"] = sum(out.values())
    return out


def get_proposal_dir() -> str:
    """Répertoire confiné des propositions (env ARAC_PROPOSAL_DIR, sinon défaut)."""
    return os.environ.get("ARAC_PROPOSAL_DIR", DEFAULT_PROPOSAL_DIR)


def _load_baseline() -> dict | None:
    try:
        return json.loads(open(BASELINE_PATH, encoding="utf-8").read())
    except (OSError, ValueError):
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ===========================================================================
# Schémas de réponse (Pydantic strict)
# ===========================================================================
class ScopeStateItem(BaseModel):
    model_config = {"extra": "forbid"}
    scope: str
    risk: str
    review_level: str
    active_count: int
    has_current_state: bool
    state_dirty: bool
    eligible: bool
    needs_proposal: bool
    reason: str
    score: int
    freshness_days: float | None = None


class CurrentStateResponse(BaseModel):
    model_config = {"extra": "forbid"}
    engine_version: str
    generated_at: str
    write_allowed: bool
    coverage_pct: float
    eligible_leaf_total: int
    with_current_state: int
    summary: dict[str, Any]
    scopes: list[ScopeStateItem]


class ProposalSummaryItem(BaseModel):
    model_config = {"extra": "forbid"}
    proposal_id: str | None = None
    scope: str | None = None
    status: str | None = None
    lifecycle_state: str | None = None
    confidence_score: int | None = None
    human_review_required: bool | None = None
    risk: str | None = None
    write_allowed: bool = False


class ProposalListResponse(BaseModel):
    model_config = {"extra": "forbid"}
    count: int
    proposal_dir: str
    # signale honnêtement si la surface fichier existe. Un count=0
    # avec proposal_dir_exists=false signifie « surface non initialisée », PAS
    # « 0 proposition » — évite la fausse assurance (les files DB peuvent être non vides).
    proposal_dir_exists: bool
    proposals: list[ProposalSummaryItem]


# ===========================================================================
# Endpoints (tous GET, lecture seule)
# ===========================================================================
@router.get("/health")
async def brain_health(
    atoms: Annotated[list[dict], Depends(provide_atoms)],
    conversations: Annotated[dict, Depends(provide_conversations)],
) -> dict:
    """GET /v1/brain/health — snapshot consolidé de santé du cerveau (read-only)."""
    return bhr.build_report(
        atoms=atoms, conversations=conversations,
        proposals=store.list_proposals(get_proposal_dir()),
        baseline=_load_baseline(), now=_now())


@router.get("/current-state", response_model=CurrentStateResponse)
async def current_state(
    atoms: Annotated[list[dict], Depends(provide_atoms)],
    risk: Annotated[str | None, Query(pattern="^(low|medium|high)$")] = None,
    needs_proposal: bool | None = None,
) -> CurrentStateResponse:
    """GET /v1/brain/current-state — couverture de l'état courant par scope feuille."""
    report = sd.discover(atoms, _now())
    s = report["summary"]
    # couverture mesurée sur les feuilles ÉLIGIBLES uniquement (source unique
    # `scope_discovery` : pas de double-comptage des feuilles dirty/conflict).
    eligible_total = s["eligible_scopes"]
    with_state = s["eligible_with_current_state"]
    items: list[ScopeStateItem] = []
    for sc in report["scopes"]:
        if not sc["is_leaf"]:
            continue
        if risk and sc["risk"] != risk:
            continue
        e = sc["eligibility"]
        if needs_proposal is not None and bool(e["needs_proposal"]) != needs_proposal:
            continue
        items.append(ScopeStateItem(
            scope=sc["scope"], risk=sc["risk"], review_level=sc["review_level"],
            active_count=sc["active_count"], has_current_state=sc["has_current_state"],
            state_dirty=sc["state_dirty"], eligible=e["eligible"],
            needs_proposal=e["needs_proposal"], reason=e["reason"], score=e["score"],
            freshness_days=sc["freshness_days"]))
    return CurrentStateResponse(
        engine_version=report["engine_version"], generated_at=report["generated_at"],
        write_allowed=False,
        coverage_pct=round(100.0 * with_state / eligible_total, 1)
        if eligible_total else 0.0,
        eligible_leaf_total=eligible_total, with_current_state=with_state,
        summary=s, scopes=items)


@router.get("/current-state/{scope:path}")
async def current_state_scope(
    scope: str,
    atoms: Annotated[list[dict], Depends(provide_atoms)],
) -> dict:
    """GET /v1/brain/current-state/{scope} — rapport de découverte d'UN scope."""
    report = sd.discover(atoms, _now())
    for sc in report["scopes"]:
        if sc["scope"] == scope:
            return {"engine_version": report["engine_version"],
                    "generated_at": report["generated_at"],
                    "write_allowed": False, "scope": sc}
    raise HTTPException(status_code=404, detail=f"scope inconnu : {scope}")


@router.get("/anti-drift")
async def anti_drift_catalog(
    atoms: Annotated[list[dict], Depends(provide_atoms)],
    conversations: Annotated[dict, Depends(provide_conversations)],
) -> dict:
    """GET /v1/brain/anti-drift — catalogue d'avertissements W-STATE (read-only)."""
    discovery = sd.discover(atoms, _now())
    overview = cso.analyze(atoms, _now())
    return ad.evaluate(
        discovery, overview, proposals=store.list_proposals(get_proposal_dir()),
        failed_conversations=int(conversations.get("failed", 0) or 0), now=_now())


@router.get("/sensitivity")
async def sensitivity_summary() -> dict:
    """GET /v1/brain/sensitivity — taxonomie de risque par scope (read-only)."""
    return sens.summary()


@router.get("/proposals", response_model=ProposalListResponse)
async def list_proposals(
    scope: str | None = None,
    status: str | None = None,
    risk: Annotated[str | None, Query(pattern="^(low|medium|high)$")] = None,
    needs_review: bool | None = None,
) -> ProposalListResponse:
    """GET /v1/brain/proposals — file de propositions.

    Filtres : `?scope=`, `?status=` (status OU lifecycle_state), `?risk=`
    (sensibilité low|medium|high), `?needs_review=` (revue humaine requise)."""
    pdir = get_proposal_dir()
    filtered = store.filter_proposals(
        store.list_proposals(pdir), scope=scope, status=status,
        risk=risk, needs_review=needs_review)
    items = [ProposalSummaryItem(
        proposal_id=p.get("proposal_id"), scope=p.get("scope"),
        status=p.get("status"), lifecycle_state=p.get("lifecycle_state"),
        confidence_score=p.get("confidence_score"),
        human_review_required=p.get("human_review_required"),
        risk=p.get("risk") or (p.get("sensitivity") or {}).get("risk"),
        write_allowed=False) for p in filtered]
    return ProposalListResponse(
        count=len(items), proposal_dir=pdir,
        proposal_dir_exists=os.path.isdir(pdir), proposals=items)


# Charset slug inoffensif (aucun caractère de traversal/dangereux). Un id qui passe
# ce filtre mais est rejeté par la validation stricte du store est une ressource
# INTROUVABLE (404, cohérence REST), pas une menace. La défense
# path-traversal du store reste inchangée et fait toujours foi.
_SAFE_PROPOSAL_LOOKUP_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str) -> dict:
    """GET /v1/brain/proposals/{id} — proposition rédactée (secrets/sensible masqués)."""
    pdir = get_proposal_dir()
    try:
        proposal = store.read_proposal(pdir, proposal_id)
    except store.ProposalSecurityError:
        # id au charset slug inoffensif mais rejeté par la validation stricte =
        # ressource introuvable (404). Un id réellement dangereux reste un 400.
        if _SAFE_PROPOSAL_LOOKUP_RE.match(proposal_id or ""):
            raise HTTPException(status_code=404, detail="proposition introuvable")
        raise HTTPException(status_code=400, detail="proposal_id invalide")
    except store.ProposalError:
        raise HTTPException(status_code=404, detail="proposition introuvable")
    # export_json = rédaction (secrets masqués, scope sensible non exposé).
    return json.loads(store.export_json(proposal))
