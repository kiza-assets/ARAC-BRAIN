"""shadow_scope.py — fix scope-préfixe (greffe), SHADOW UNIQUEMENT.

Le chemin recall SERVI filtre le scope en ÉGALITÉ STRICTE
(`app/routers/atoms.py`, clause `scope = %s`) : demander une RACINE n'atteint
JAMAIS ses feuilles. Mesure au banc : sur une racine donnée, 34 atomes
atteignables au lieu de 567 — un facteur 16,7. La greffe corrige la clause en
`scope = s OR scope LIKE s||'/%'` — dans le kNN SHADOW SEULEMENT : la clause
servie reste bit-identique tant que le fix n'est pas promu (décision humaine).

Pourquoi en shadow d'abord : changer le filtre de rappel change ce que le
cerveau répond. On mesure l'écart avant de le servir, jamais l'inverse.

Ce module fournit les DEUX faces du même fix, jamais deux vérités :
  - la face SQL (`SCOPE_PREFIX_CLAUSE` + `scope_prefix_params`) pour le kNN
    shadow ;
  - la face Python (`scope_matches`) pour la mesure
    `scope_prefix_gain` des reçus (combien d'ids le shadow a atteints GRÂCE
    au préfixe, c.-à-d. hors égalité stricte).

Piège psycopg (§pièges n°4) : avec des paramètres `%s`
(placeholders client-side psycopg3), tout `%` LITTÉRAL du SQL doit être
DOUBLÉ (`%%`) — d'où `'/%%'` dans la clause. Le serveur reçoit bien `'/%'`.
"""
from __future__ import annotations

#: Clause WHERE du filtre scope shadow — 3 placeholders, tous le MÊME scope
#: (cf `scope_prefix_params`). NULL = pas de filtre (comme la clause servie).
#: `%%` = un `%` littéral pour psycopg3 (placeholders %s actifs).
SCOPE_PREFIX_CLAUSE = "(%s::text IS NULL OR scope = %s OR scope LIKE %s || '/%%')"


def scope_prefix_params(scope: str | None) -> tuple[str | None, str | None, str | None]:
    """Les 3 paramètres de SCOPE_PREFIX_CLAUSE (le même scope, trois fois)."""
    return (scope, scope, scope)


def scope_matches(candidate_scope: str | None, ref_scope: str | None) -> bool:
    """Fix scope-préfixe en LECTURE, transposé en Python — MÊME sémantique
    que la clause SQL, dans UN SEUL sens (candidat SOUS ref, jamais
    l'inverse) : "travail/finance" matche ref "travail" ; "travail" ne matche
    pas ref "travail/finance" ; "travailleur" ne matche pas "travail" — la
    frontière est le '/', pas le préfixe de chaîne."""
    if not candidate_scope or not ref_scope:
        return False
    return candidate_scope == ref_scope or candidate_scope.startswith(ref_scope + "/")


def is_prefix_gain(candidate_scope: str | None, ref_scope: str | None) -> bool:
    """True ssi le candidat n'est atteignable QUE grâce au fix préfixe :
    il matche le scope demandé par préfixe mais PAS par égalité stricte
    (la clause prod l'aurait exclu). Somme sur les shadow_ids ->
    `context_receipts.scope_prefix_gain`."""
    return (
        candidate_scope is not None
        and ref_scope is not None
        and candidate_scope != ref_scope
        and scope_matches(candidate_scope, ref_scope)
    )
