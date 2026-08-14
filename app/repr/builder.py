"""builder.py — construction d'UNE représentation fold v2 par atome
(FOLD V2, write-path prod).

`build_repr(conn, embed_fn, atom_row)` :
  0. pré-check `memory_atom_reprs` — repr déjà présente → retour immédiat,
     ZÉRO appel OpenAI (l'idempotence ne re-paye jamais) ;
  1. extraction des textes user (bi-format, `app.repr.spans`) ;
  2. composition T_meta + surface user bornée 256 tok (`app.repr.recipe`) ;
  3. BudgetLedger.charge AVANT toute dépense (fail-closed porté du banc,
     `build_rm1_reprs.py:205-237` — refuse si le cumul projeté crève le
     plafond, l'API n'est jamais appelée après un refus) ;
  4. 2 embeddings max : emb(T_meta) + emb(surface) si surface non vide
     (sinon dégénérescence T_meta, 1 seul embedding) ;
  5. fold α=0.5 (formule exacte du banc) ;
  6. INSERT append-only `ON CONFLICT (atom_id, repr_version) DO NOTHING`
     (même idempotence que `build_rm1_reprs.py::insert_reprs:283-302`),
     build jsonb = provenance {format, n_spans, n_user_tokens, degenerate}
     — JAMAIS de texte ni de PII.

Erreurs BRUYANTES : toute exception (embed, DB, dims) remonte à l'appelant
(le batch WP-C catch par atome et continue) — rien n'est avalé ici.
`embed_fn` : callable SYNC `str -> list[float]` injectable (tests
hermétiques : fake déterministe ; prod : wrapper sync autour de
`app.services.embeddings.embed`).
`conn` : psycopg sync, curseur tuple — le commit appartient à l'APPELANT
(le batch commit par atome réussi ; `build_repr` ne commit pas, pour rester
composable en transaction de test).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from app.repr.recipe import (
    EMBED_DIMS,
    MANIFEST_SHA,
    REPR_VERSION,
    bound_user_surface,
    compose_t_meta,
    fold,
    ntok,
    vec_to_text,
)
from app.repr.spans import user_texts_for_source_ref

# Mêmes constantes de facturation que le banc (`build_rm1_reprs.py:79-80`).
PRICE_USD_PER_MTOK = 0.13   # text-embedding-3-large
BUDGET_USD = 0.15           # plafond DUR par défaut (hérité du banc)

_EXISTS_SQL = (
    "SELECT 1 FROM arac.memory_atom_reprs "
    "WHERE atom_id = %s::uuid AND repr_version = %s"
)
_INSERT_SQL = """
    INSERT INTO arac.memory_atom_reprs
        (atom_id, repr_version, embedding, manifest_sha, doc_sha256, build)
    VALUES (%s::uuid, %s, %s::halfvec(3072), %s, %s, %s::jsonb)
    ON CONFLICT (atom_id, repr_version) DO NOTHING
"""


class BudgetExceeded(RuntimeError):
    """Plafond de dépense crevé — levée AVANT tout appel API (fail-closed)."""


class BudgetLedger:
    """Port prod du BudgetLedger du banc (`build_rm1_reprs.py:205-237`) :
    compte les tokens cl100k qui SERAIENT envoyés à l'API et refuse d'appeler
    si le cumul projeté crève le plafond — AVANT la dépense, jamais après.

    Différence consignée vs le banc : pas d'`embedding_cache` en prod
    (artefact bench) → tout texte chargé est un « miss » facturé ; le
    pré-check d'existence de `build_repr` joue le rôle du cache (une repr
    déjà en base ne re-paye jamais)."""

    def __init__(self, budget_usd: float = BUDGET_USD,
                 price_usd_per_mtok: float = PRICE_USD_PER_MTOK):
        self.budget_usd = budget_usd
        self.price_usd_per_mtok = price_usd_per_mtok
        self.budget_tokens = int(budget_usd / price_usd_per_mtok * 1_000_000)
        self.sent_tokens = 0
        self.calls: list[dict[str, Any]] = []

    def charge(self, texts: Sequence[str], label: str) -> int:
        """Comptabilise `texts` (tokens cl100k). Lève `BudgetExceeded` si le
        cumul projeté dépasse le plafond — SANS rien comptabiliser (l'appel
        API ne doit alors jamais avoir lieu)."""
        tok = sum(ntok(t) for t in texts)
        if self.sent_tokens + tok > self.budget_tokens:
            raise BudgetExceeded(
                f"BUDGET DUR crevé: {label} demanderait {tok} tokens, cumul "
                f"{self.sent_tokens + tok} > {self.budget_tokens} "
                f"(${self.budget_usd})"
            )
        self.calls.append({"label": label, "texts": len(texts), "api_tokens": tok})
        self.sent_tokens += tok
        return tok

    @property
    def spent_usd(self) -> float:
        return round(self.sent_tokens * self.price_usd_per_mtok / 1e6, 6)


@dataclass(frozen=True)
class ReprBuildResult:
    """Résultat d'un `build_repr` — ids/compteurs UNIQUEMENT, jamais de
    texte (même doctrine que les reçus du Context Engine)."""

    atom_id: str
    repr_version: str
    status: str                 # 'inserted' | 'already_present' | 'conflict_skipped'
    source_format: str          # 'cortex' | 'curator' | 'none' ('' si already_present)
    n_spans: int
    n_user_tokens: int
    degenerate: bool
    embed_calls: int
    api_tokens: int

    @property
    def inserted(self) -> bool:
        return self.status == "inserted"


def _check_dims(vec: Sequence[float], label: str) -> Sequence[float]:
    if len(vec) != EMBED_DIMS:
        raise ValueError(
            f"embed_fn a renvoyé {len(vec)} dims pour {label}, "
            f"attendu {EMBED_DIMS} — refus d'insérer un vecteur invalide"
        )
    return vec


def build_repr(
    conn,
    embed_fn: Callable[[str], list[float]],
    atom_row: Mapping[str, Any],
    *,
    ledger: BudgetLedger | None = None,
) -> ReprBuildResult:
    """Construit et insère la repr `rm1-fold-a50` d'UN atome. Cf docstring
    module pour le contrat (idempotence, budget, commit à l'appelant).

    `atom_row` : mapping row `memory_atoms` avec au moins
    `id, value, scope, kind, key, tags, source_ref`.
    `ledger` : partagé par le batch (cumul multi-atomes) ; None = ledger
    frais (plafond par défaut) pour un geste unitaire."""
    atom_id = str(atom_row["id"])
    ledger = ledger if ledger is not None else BudgetLedger()

    # 0. Idempotence AVANT toute dépense : repr déjà en base → zéro embed.
    with conn.cursor() as cur:
        cur.execute(_EXISTS_SQL, (atom_id, REPR_VERSION))
        if cur.fetchone() is not None:
            return ReprBuildResult(
                atom_id=atom_id, repr_version=REPR_VERSION,
                status="already_present", source_format="", n_spans=0,
                n_user_tokens=0, degenerate=False, embed_calls=0, api_tokens=0,
            )

    # 1-2. Textes (spans bi-format) + composition recette.
    source_format, texts = user_texts_for_source_ref(conn, atom_row.get("source_ref"))
    t_meta = compose_t_meta(atom_row)
    surface = bound_user_surface(texts)
    degenerate = not surface
    to_embed = [t_meta] + ([surface] if surface else [])

    # 3. Budget fail-closed AVANT la dépense (lève BudgetExceeded → aucun
    #    appel embed_fn n'a lieu).
    api_tokens = ledger.charge(to_embed, f"build_repr:{atom_id}")

    # 4-5. 2 embeddings max, puis fold (dégénérescence T_meta si pas de
    #      surface — fold([]) retourne le vecteur T_meta tel quel).
    meta_vec = _check_dims(embed_fn(t_meta), "T_meta")
    user_vecs = [_check_dims(embed_fn(surface), "surface")] if surface else []
    vec = fold(meta_vec, user_vecs)

    # 6. INSERT append-only idempotent. Provenance SANS texte.
    build = {
        "format": source_format,
        "n_spans": len(texts),
        "n_user_tokens": ntok(surface) if surface else 0,
        "degenerate": degenerate,
    }
    with conn.cursor() as cur:
        cur.execute(
            _INSERT_SQL,
            (atom_id, REPR_VERSION, vec_to_text(vec), MANIFEST_SHA, None,
             json.dumps(build, ensure_ascii=False)),
        )
        inserted = cur.rowcount == 1

    return ReprBuildResult(
        atom_id=atom_id,
        repr_version=REPR_VERSION,
        status="inserted" if inserted else "conflict_skipped",
        source_format=source_format,
        n_spans=len(texts),
        n_user_tokens=build["n_user_tokens"],
        degenerate=degenerate,
        embed_calls=len(to_embed),
        api_tokens=api_tokens,
    )
