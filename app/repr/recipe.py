"""recipe.py — RECETTE prod GELÉE du fold v2 (`rm1-fold-a50`), FOLD V2.

RECETTE GELÉE, issue d'un banc de calibration mené hors dépôt : champion
`repr:rm1-fold-a50`, α=0.5, borne user 256 jetons cl100k.

POURQUOI GELÉE : une représentation est un vecteur payé. Changer la recette
sans recalculer l'existant crée deux populations incomparables dans le même
index — le rappel dégrade sans qu'aucun test n'échoue. `MANIFEST_SHA` existe
pour rendre ce glissement détectable : il est écrit à côté de chaque vecteur.

Fonctions PURES : aucune E/S, aucun appel réseau/DB/LLM. L'extraction des
textes user appartient à `app.repr.spans`, l'orchestration + INSERT à
`app.repr.builder`.

DÉVIATION CONSIGNÉE vs le banc (décision d'architecte, 2 embeddings max par
atome) : le banc embeddait CHAQUE span user séparément (cap per-piece 256
tok) puis mean-poolait les pièces ; en prod la surface user est UN SEUL
document borné (concat des textes user non vides, cap 256 tok cl100k tête —
la composition exacte de `bounded_doc` lignes 177-182) embeddé une fois.
`fold()` reste la formule EXACTE du banc (mean sur la liste des vecteurs
user, ici un singleton) : normalize(α·n(E_meta) + (1−α)·n(mean(n(pièces)))).

MANIFEST_SHA = sha256(RECIPE canonicalisée), même convention que le banc
(`build_rm1_reprs.py:127-129`) — DISTINCT du manifest_sha bench (contexte
différent : source `raw_messages`/`raw_conversations` direct, surface
single-embed, pas de LOO/multi-variantes).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

import numpy as np

# ---------------------------------------------------------------------------
# RECETTE GELÉE — paramètres copiés VERBATIM du champion rm1-fold-a50
# ---------------------------------------------------------------------------

#: Clé `repr_version` écrite dans `arac.memory_atom_reprs` (champion gelé,
#: `rm1_calibration.json:"champion":"repr:rm1-fold-a50"`).
REPR_VERSION = "rm1-fold-a50"

EMBED_MODEL = "text-embedding-3-large"  # = app/services/embeddings.py _MODEL
EMBED_DIMS = 3072                       # = app/services/embeddings.py _DIMENSIONS
BILLING_ENCODING = "cl100k_base"        # tokenizer de facturation embeddings v3

ALPHA = 0.5                             # champion_params.alpha
USER_SURFACE_CAP_TOK = 256              # champion_params.user_piece_cap_tok

RECIPE: dict[str, Any] = {
    "recipe_version": "rm1-fold-a50-prod-v1",
    "program": "fold v2 write-path prod",
    "repr_version": REPR_VERSION,
    "champion_source": {
        "calibration": "rm1_calibration.json version=rm1-calib-v1-20260708",
        "champion": "repr:rm1-fold-a50",
        "bench_build_manifest_sha":
            "48db6ae2c9575aa96a29397e904e58dc29d7ddef3d38a5113fb626ceb745c125",
    },
    "embed_model": EMBED_MODEL,
    "embed_dims": EMBED_DIMS,
    "billing_encoding": BILLING_ENCODING,
    "alpha": ALPHA,
    "user_surface_cap_tok": USER_SURFACE_CAP_TOK,
    "t_meta": "value + '\\n\\n[scope] ' + deslug(scope) + '\\n[kind] ' + kind"
              " + '\\n[cle] ' + deslug(key) + ('\\n[tags] ' + ' '.join(tags) si tags)",
    "deslug": "remplace '/', '-', '_' par espace",
    "user_surface": "head_cap_tokens(concat('\\n\\n', textes user btrim non vides,"
                    " ordre source_ref), 256)",
    "fold": "normalize(alpha*n(E_meta) + (1-alpha)*normalize(mean(n(pieces user))))",
    "spanless_rule": "atome sans texte user (aucun ancrage, spans vides ou"
                     " non-user) -> vecteur T_meta brut (plancher méta,"
                     " degenerate_to_meta)",
    "span_sources": "cortex: source_ref.message_ids -> arac.raw_messages ;"
                    " curator legacy: source_ref.curator_raw_id+message_indices ->"
                    " gunzip(arac.raw_conversations.content_gz) NDJSON bi-format"
                    " (CLI/desktop, port harness/text_extract.py)",
    "deviations_consignees": [
        "surface user = UN SEUL embedding du doc borné 256 tok (concat puis cap"
        " tête, composition bounded_doc du banc) au lieu du mean-pool per-piece"
        " (cap 256/pièce) du champion — décision architecte : 2 embeddings max"
        " par atome ; fold() reste la formule exacte du banc (mean sur la liste"
        " des vecteurs user, ici singleton)",
        "requête embarquée inchangée : embed v1 brut — le fold ne touche QUE la"
        " représentation des atomes, jamais celle des requêtes",
    ],
}

MANIFEST_SHA = hashlib.sha256(
    json.dumps(RECIPE, sort_keys=True, ensure_ascii=False).encode("utf-8")
).hexdigest()


# ---------------------------------------------------------------------------
# Tokenizer (lazy — jamais chargé au boot, même modèle que le banc)
# ---------------------------------------------------------------------------

_enc = None


def _encoding():
    global _enc
    if _enc is None:
        import tiktoken

        _enc = tiktoken.get_encoding(BILLING_ENCODING)
    return _enc


def ntok(text: str) -> int:
    """Nombre de tokens cl100k (tokenizer de facturation) — port verbatim."""
    return len(_encoding().encode(text, disallowed_special=()))


def head_cap_tokens(text: str, cap: int) -> str:
    """Cap en TÊTE à `cap` tokens cl100k — port verbatim
    (`build_rm1_reprs.py:152-156`)."""
    ids = _encoding().encode(text, disallowed_special=())
    if len(ids) <= cap:
        return text
    return _encoding().decode_bytes(ids[:cap]).decode("utf-8", errors="ignore")


def deslug(x: str | None) -> str:
    """Port verbatim (`build_rm1_reprs.py:159-160`)."""
    return (x or "").replace("/", " ").replace("-", " ").replace("_", " ")


# ---------------------------------------------------------------------------
# Composition des textes
# ---------------------------------------------------------------------------

def compose_t_meta(atom: Mapping[str, Any]) -> str:
    """T_meta = value + métadonnées lisibles — port verbatim de `t_meta`
    (`build_rm1_reprs.py:163-169`). `atom` : mapping avec au moins
    `value, scope, kind, key, tags` (row `memory_atoms`)."""
    tags = " ".join(atom.get("tags") or [])
    out = (atom["value"] + "\n\n[scope] " + deslug(atom.get("scope"))
           + "\n[kind] " + (atom.get("kind") or "") + "\n[cle] " + deslug(atom.get("key")))
    if tags:
        out += "\n[tags] " + tags
    return out


def bound_user_surface(texts: Sequence[str]) -> str:
    """Surface user bornée : concat '\\n\\n' des textes user non vides (ordre
    fourni = ordre source_ref), cap USER_SURFACE_CAP_TOK tokens cl100k en
    tête — reproduit la section source-user de `bounded_doc`
    (`build_rm1_reprs.py:172-183`) : filtre `text.strip()` non vide, join
    des textes TELS QUELS (l'extraction spans strippe déjà), cap tête.

    Retourne '' si aucun texte user exploitable (→ dégénérescence T_meta,
    cf `fold`)."""
    parts = [t for t in texts if t and t.strip()]
    if not parts:
        return ""
    return head_cap_tokens("\n\n".join(parts), USER_SURFACE_CAP_TOK)


# ---------------------------------------------------------------------------
# Vecteurs — mêmes fonctions de normalisation que le banc
# ---------------------------------------------------------------------------

def _nrm(v: np.ndarray) -> np.ndarray:
    """Port verbatim (`build_rm1_reprs.py:196-198`)."""
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def vec_to_text(v: np.ndarray | Sequence[float]) -> str:
    """Sérialisation halfvec-compatible — port verbatim
    (`build_rm1_reprs.py:201-202`)."""
    return "[" + ",".join(repr(float(x)) for x in v) + "]"


def parse_vec(emb_text: str) -> np.ndarray:
    """Port verbatim (`build_rm1_reprs.py:192-193`) — utile aux tests et aux
    audits de reproductibilité."""
    return np.array([float(x) for x in emb_text.strip("[]").split(",")], dtype=np.float64)


def fold(
    meta_vec: np.ndarray | Sequence[float],
    user_vecs: Sequence[np.ndarray | Sequence[float]],
    alpha: float = ALPHA,
) -> np.ndarray:
    """Fold champion — reproduit EXACTEMENT `fold_vec`
    (`build_rm1_reprs.py:466-471`) :

      - dégénérescence (`build_rm1_reprs.py:466-468`) : aucun vecteur user OU
        alpha >= 1.0 → retourne le vecteur T_meta TEL QUEL (le banc insérait
        `meta_emb_text`, l'embedding brut du cache, PAS re-normalisé) ;
      - sinon : surf = normalize(mean(normalize(chaque pièce user))) ;
        résultat = normalize(alpha·normalize(meta) + (1−alpha)·surf).

    Calculs en float64 (comme le banc, qui re-lisait le cache en float64)."""
    m = np.asarray(meta_vec, dtype=np.float64)
    us = [np.asarray(u, dtype=np.float64) for u in user_vecs]
    if not us or alpha >= 1.0:
        return m  # degenerate_to_meta — T_meta brut, non re-normalisé
    surf = _nrm(np.mean([_nrm(u) for u in us], axis=0))
    return _nrm(alpha * _nrm(m) + (1.0 - alpha) * surf)
