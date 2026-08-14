"""dedup_thresholds.py — seuils du backstop dédup sémantique PAR ESPACE de
représentation (chantier FOLD V2).

Module PUR : zéro I/O, zéro DB, zéro import lourd — importable partout
(dispose, outils de replay, tests) sans effet de bord.

Doctrine : le seuil 0.08 historique n'a AUCUN sens dans l'espace foldé (transport de
quantile formellement invalide, Kendall τ-a=0.628 — AC5) ; chaque espace de
représentation porte SON seuil, dérivé dans SON espace. Le routage par
`get_threshold(space)` rend tout futur espace impossible à brancher sans
décision explicite (KeyError bruyant, jamais un défaut silencieux).

LIVRAISON VERSION-GATÉE INERTE : aujourd'hui le chemin servi (dispose.py)
route `get_threshold("v1")` = 0.08 INCHANGÉ. La constante v2 (0.0124) et le
carve-out cérémonie ne s'ARMENT qu'avec I3 (recall dédup classé dans
l'espace fold `rm1-fold-a50`) au GO prod — les brancher sur un recall qui
range encore les vecteurs v1 serait un non-sens destructeur (invariant I3
de la décision).
"""

from __future__ import annotations

import hashlib
import re

#: Seuil de distance (cosine BRUTE) du backstop sémantique, par espace.
DEDUP_THRESHOLD_BY_SPACE: dict[str, float] = {
    # v1 — embeddings bruts `memory_atoms.embedding` (text-embedding-3-large).
    # Provenance : design §3 historique — « cosine >= 0.92 <=>
    # distance <= 0.08 ». C'est la valeur SERVIE aujourd'hui (dispose.py).
    "v1": 0.08,
    # rm1-fold-a50 — représentation foldée `arac.memory_atom_reprs`
    # (champion). Provenance :, coupe max-marge FP=0 — milieu de
    # [0, min_d2(N−)] = [0, 0.0248] après carve-out cérémonie → τ2 = 0.0124.
    # Calibration (sha256
    # b1e8e0fe8a71a1edf503c9f64519e83b317c5b65e097ff5f63218bb8b595c38a).
    # OBLIGATOIREMENT couplé au carve-out CEREMONY_RE (invariant I2 : sans
    # lui, 0.0124 supersède 2 verdict-alert DISTINCTS). INERTE tant que I3
    # (recall dédup dans l'espace fold) n'est pas armé au GO prod.
    "rm1-fold-a50": 0.0124,
}

#: Carve-out cérémonie (invariant I2) — clés d'enregistrements de
#: cérémonie triade (mission/verdict/delivery + identifiants hex) : des
#: événements DISTINCTS à texte quasi identique, qui occupent la bande de
#: distance quasi-nulle de l'espace fold. Dans la boucle backstop de
#: l'espace FOLD (et de lui SEUL — jamais sur le chemin v1 servi), tout hit
#: où le candidat OU l'incumbent matche est IGNORÉ (continue) :
#: fail-toward-CREATE, le POST fait coexister plutôt que superséder.
#: Fragilité consignée (décision §carveout) : seules 4 racines couvertes —
#: une nouvelle racine cérémonie (ex. mission-d2) échappe au carve-out,
#: monitorée par le log d'armement B (dispose.semantic_dup).
CEREMONY_RE = re.compile(
    r"^(mission-d1|verdict-validation|verdict-alert|delivery-mission)"
    r"(-[0-9a-f]{6,12})+$"
)


def is_ceremony_key(key: object) -> bool:
    """True si `key` est une clé de cérémonie triade (match CEREMONY_RE).

    Tolère un non-str (contrat violé en amont) en retournant False plutôt
    que de lever — cette fonction est appelée depuis des chemins
    d'observabilité (log d'armement B) qui ne doivent JAMAIS faire crasher
    une disposition. Côté décision (espace fold), un non-str ne peut de
    toute façon pas franchir le prédicat `key !=` du backstop.
    """
    return isinstance(key, str) and CEREMONY_RE.match(key) is not None


def key_sha8(key: object) -> str:
    """Empreinte sha8 (8 hex de sha256) d'une clé d'atome, pour TOUT
    log/receipt/artefact (invariant I5 de + règle V0.107).

    Une clé d'atome n'est PAS garantie sans PII : le corpus réel contient
    des clés-slugs portant le prénom de l'opérateur (vérifié arac_test et
    arac_bench, 11 clés actives). « Slug » ≠ « anonyme » — aucune clé ne
    doit donc être écrite en clair dans un artefact durable ; sha8 suffit
    pour corréler deux occurrences (même clé → même empreinte) sans rien
    révéler. Tolère un non-str (mêmes chemins d'observabilité que
    `is_ceremony_key`) en hachant sa repr str."""
    return hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:8]


def get_threshold(space: str) -> float:
    """Seuil du backstop pour `space` — KeyError BRUYANT sur espace inconnu
    (jamais de défaut silencieux : un nouvel espace de représentation exige
    sa propre dérivation de seuil."""
    try:
        return DEDUP_THRESHOLD_BY_SPACE[space]
    except KeyError:
        raise KeyError(
            f"espace de représentation inconnu pour le backstop dédup : "
            f"{space!r} (connus : {sorted(DEDUP_THRESHOLD_BY_SPACE)}) — "
            f"tout nouvel espace exige sa propre dérivation de seuil"
        ) from None
