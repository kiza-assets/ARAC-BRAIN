"""Écriture de `arac.digestion_review_queue` (migration 0028).

« Le disposant dispose, cette file explique. » Chaque candidat-atome ÉCARTÉ
par `agents/cortex/dispose.py` (jamais posté ou perdant un arbitrage) et
chaque message bloqué en amont (`agents/cortex/cycle.py`, pack surdimensionné)
atterrit ici — revue humaine différée plutôt que silence dans les logs.

Deux responsabilités :
  - `insert_review_row` : écriture BEST-EFFORT (jamais bloquante) d'une row.
  - `check_receipt_atom_invariant` (+ `count_atoms_for_run`) : invariant
    receipts <-> atomes (« ce que le reçu prétend avoir créé/supersédé
    correspond aux rows RÉELLEMENT écrites dans `memory_atoms` pour ce run »),
    la fonction de vérification est PURE (comptes déjà calculés en
    paramètres) pour être réutilisable telle quelle par le conservation-audit
    nocturne sans dépendre d'une connexion DB.

Doctrine BEST-EFFORT (décision documentée) : la revue humaine
est un CONFORT (traçabilité des décisions du disposant), jamais un chemin
bloquant — une file indisponible (table verrouillée, connexion coupée...) ne
doit JAMAIS faire échouer la digestion elle-même. `insert_review_row` avale
donc ses propres exceptions (log + retour silencieux) ; l'invariant, lui,
N'EST QU'UNE ALERTE (log + notification), jamais un rollback : la mémoire
posée reste posée, l'écart mérite un oeil humain mais pas un blocage.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from agents.lib.log_capture import mask_secrets
from app.journal import raison

logger = logging.getLogger("arac.cortex.review_queue")

# Masquage PII léger : adresses e-mail dans le candidat
# SANITISÉ avant écriture en review-queue. Regex simple volontairement (pas
# de RFC 5322 complet — suffisant pour éviter qu'une adresse traîne en clair
# dans une table de revue humaine). Le scrubber PII COMPLET (noms, tél.,
# adresses postales...) reste un chantier ROADMAP (gap systémique déjà
# : ce module ne fait QUE masquer secrets+emails, il ne
# prétend PAS anonymiser le contenu).
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _mask_emails(text: str) -> str:
    return _EMAIL_PATTERN.sub("[REDACTED:email]", text)

#: Scope de remplissage pour les rows qui ne portent PAS un candidat d'atome
#: (un message écarté avant la digestion, une omission constatée). La colonne
#: est NOT NULL, mais la notion de scope n'a aucun sens pour ces lignes-là.
#:
#: L'underscore initial est délibéré : la grammaire d'un scope est
#: `minuscules/chiffres/tirets`, donc cette valeur ne peut JAMAIS entrer en
#: collision avec un scope de votre taxonomie. Une ligne marquée ainsi se lit
#: « ceci n'est pas un savoir, c'est une observation du système ».
PLACEHOLDER_SCOPE = "_systeme"

# 5 valeurs fermées, IDENTIQUES au CHECK de la migration 0028 (cf docstring
# de la migration pour la sémantique de chacune).
DROP_REASONS = frozenset({
    "kept_lower_confidence", "policy_skip", "atom_quarantine",
    "coverage_omitted", "oversized_message",
})

# Troncature défensive de chaque valeur texte du candidat SANITISÉ — jamais
# un blob non borné dans une table de revue humaine (~2000 chars, cf SCOPE
# ; assez pour lire une `value`/`rationale` complète en pratique, sans
# ouvrir la porte à un débordement si un LLM dérive).
_MAX_STR_CHARS = 2000


def _log(event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, ensure_ascii=False, default=str))


def _sanitize(value: Any) -> Any:
    """Masque les secrets (`agents.lib.log_capture.mask_secrets`) puis tronque
    à `_MAX_STR_CHARS`, récursivement sur tout `str` d'une structure JSON
    (dict/list préservés tels quels). Ne retire PAS les champs (le candidat
    reste lisible pour la revue) — masque et borne seulement.
    """
    if isinstance(value, str):
        return _mask_emails(mask_secrets(value))[:_MAX_STR_CHARS]
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    return value


async def insert_review_row(
    conn,
    run_ref: str,
    conversation_uid: str,
    drop_reason: str,
    proposed_atom: dict[str, Any],
    incumbent_atom_id: str | None,
    scope: str,
    kind: str,
) -> None:
    """INSERT best-effort dans `arac.digestion_review_queue`.

    `proposed_atom` est SANITISÉ (`_sanitize`) avant sérialisation : jamais
    de secret en clair, jamais un champ texte non borné. Ce module n'inspecte
    JAMAIS de contenu de message brut — `proposed_atom` est TOUJOURS soit le
    payload d'atome déjà construit par `policy.finalize_atom` (candidat
    complet tel qu'il aurait été posté), soit un petit dict de métadonnées
    déterministe (ex. `{"reason": ..., "retry_count": ...}` pour une
    omission) — jamais un extrait de conversation.

    BEST-EFFORT (cf docstring module) : toute exception (table absente,
    connexion coupée, contrainte violée...) est LOGGÉE puis avalée — cette
    fonction ne lève JAMAIS. Le caller (`dispose.py`/`cycle.py`) continue
    donc sans savoir si l'écriture a réussi ; c'est le choix assumé, la
    digestion des atomes réels prime sur la traçabilité de ce qui est jeté.

    PAS DE COMMIT ICI (même discipline que `curator_lib_v2` : le caller
    committe, cette fonction ne fait que préparer l'INSERT dans la
    transaction en cours).

    SAVEPOINT (revue adversariale, constat 1/7/27) : `conn` est la
    connexion PARTAGÉE du disposant/cycle, déjà dans une transaction en
    cours (POST d'atomes, avance de curseur...). Sans savepoint, un INSERT
    échoué (table verrouillée, FK `incumbent_atom_id` invalide...) laisse
    psycopg3 en `InFailedSqlTransaction` : le `commit()` du caller devient
    un rollback SILENCIEUX (retry_count/backoff perdus) ou l'appel BDD
    suivant (ex. `mark_curation_failed`) lève à son tour -> crash payant
    (dispose_interrupted, re-spawn). `async with conn.cursor()` seul ne
    protège rien (ce n'est qu'un cursor, pas une transaction). `async with
    conn.transaction():` POSE un SAVEPOINT (une transaction est déjà
    ouverte sur `conn`) : en cas d'exception, psycopg3 fait un ROLLBACK TO
    SAVEPOINT — seul l'INSERT est annulé, le reste de la transaction du
    caller reste utilisable normalement.
    """
    if drop_reason not in DROP_REASONS:
        # Erreur de programmation de l'appelant (typo sur un literal
        # interne) : ce n'est PAS une panne d'infra -> on ne l'avale pas
        # silencieusement, elle doit remonter en test/dev.
        raise ValueError(f"drop_reason inconnu : {drop_reason!r}")

    sanitized = _sanitize(proposed_atom)
    try:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO arac.digestion_review_queue "
                    "(run_ref, conversation_uid, drop_reason, proposed_atom, "
                    " incumbent_atom_id, scope, kind) "
                    "VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)",
                    (run_ref, conversation_uid, drop_reason,
                     json.dumps(sanitized, ensure_ascii=False, default=str),
                     incumbent_atom_id, scope, kind),
                )
    except Exception as e:  # noqa: BLE001 — best-effort, cf docstring module
        _log("review_queue.insert_failed", run_ref=run_ref,
             conversation_uid=conversation_uid, drop_reason=drop_reason,
             error=raison(e))


async def count_atoms_for_run(conn, run_ref: str) -> int:
    """COUNT(*) `arac.memory_atoms` dont `source_ref->>'run_ref' = run_ref`.

    Lecture utilisée par `cycle.py` en fin de run pour nourrir
    `check_receipt_atom_invariant` : chaque `created`/`superseded` du
    disposant produit EXACTEMENT une nouvelle row `memory_atoms` attribuée à
    CE run (`confirm_unchanged` fait un PATCH en place, aucune nouvelle row).
    """
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT COUNT(*) FROM arac.memory_atoms "
            "WHERE source_ref->>'run_ref' = %s",
            (run_ref,),
        )
        row = await cur.fetchone()
    return int(row[0]) if row else 0


def check_receipt_atom_invariant(
    *, atoms_in_db: int, atoms_created: int, atoms_superseded: int,
) -> tuple[bool, int]:
    """Invariant receipts <-> atomes. Fonction PURE : comptes
    déjà calculés en paramètres, aucun accès DB — réutilisable telle quelle
    par le conservation-audit nocturne.

    `atoms_created`/`atoms_superseded` sont les compteurs du reçu du run
    (`DisposeTotals`) ; `atoms_in_db` = `count_atoms_for_run` (ou tout
    équivalent, ex. rejoué a posteriori par). Chaque `created` ET
    chaque `superseded` produit EXACTEMENT une row `memory_atoms` neuve
    attribuée au run -> l'attendu est leur somme (`confirmed`/`kept`/
    `quarantined` n'écrivent AUCUNE nouvelle row et sont donc absents de la
    somme).

    Retourne `(ok, ecart)` où `ecart = atoms_in_db - attendu` (0 si `ok` ;
    signé sinon, pour distinguer sur-comptage — ex. atomes écrits deux fois
    par une API buggée — de sous-comptage — ex. un POST répondu 201 sans
    écriture réelle).
    """
    expected = atoms_created + atoms_superseded
    ecart = atoms_in_db - expected
    return ecart == 0, ecart
