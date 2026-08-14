"""Value-gate — scorer DÉTERMINISTE de densité mémoire,
mode SHADOW LOG-ONLY exclusivement.

Le backlog figé de ~2 581 kt (backfill self-capture 07-07) ne draine pas par
densité : 13 des 15 plus grosses conversations pending ont `atoms_generated=0`
APRÈS engagement LLM (curseur avancé, budget dépensé, rien appris). Ce module
identifie ces conversations LOW_VALUE par une règle STRUCTURELLE et
DÉTERMINISTE (jamais un embedding/similarité — doctrine de coût), sur
métadonnées DB existantes uniquement :

    LOW_VALUE ssi (atoms_generated = 0)                    — jamais un atome
             ET (curated_through_message_id > engaged_min) — preuve d'au moins
                                                             UN engagement LLM
                                                             sans atome (les
                                                             jamais-engagées ne
                                                             sont JAMAIS
                                                             candidates)
             ET (uncured_ktok >= uncured_ktok_min)         — le résidu justifie
                                                             d'éviter la dépense
             ET (node_id ∈ operator_nodes)                 — sessions OPÉRATEUR
                                                             (self-capture),
                                                             jamais « la
                                                             source » en bloc

Le garde `atoms_generated = 0` est CODÉ EN DUR (: ne JAMAIS
archiver une conversation qui a déjà produit — 4dfafcdc/6 atomes et
8e352c9c/1 atome doivent rester hors liste, vérifiable en shadow).

SHADOW (ce module, livré) : `shadow_scan` LIT, score, LOGGE chaque candidat
would-be-excluded (`value_gate.shadow_exclude` : uid, chiffres) + un résumé
par cycle (`value_gate.shadow_summary`) — AUCUNE ÉCRITURE de décision, aucune
colonne touchée. Vous relisez ce journal AVANT tout armement.

ENFORCE (NON IMPLÉMENTÉ ICI, À DESSEIN) : l'écriture du
reçu d'exclusion (`exclusion_category`/... , cf
`curator_lib_v2.mark_conversation_excluded`) et l'avance du curseur sont un
choix de POLITIQUE MÉMOIRE — elles n'entrent dans ce module qu'avec le GO.

Seuils par env (défauts =, tunables en soak) :
  ARAC_VALUE_GATE_UNCURED_KTOK_MIN   (défaut 100)
  ARAC_VALUE_GATE_ENGAGED_CURSOR_MIN (défaut 1 — curseur strictement > 0)
  ARAC_VALUE_GATE_OPERATOR_NODES     (CSV ; défaut : "<votre-node>-server")

Le nœud OPÉRATEUR est celui qui produit les conversations du serveur
lui-même — celles où le cerveau se regarde travailler. Elles sont volumineuses
et faiblement porteuses de savoir durable, d'où ce garde-fou. Le défaut est
dérivé de VOTRE node_id, jamais écrit en dur : un identifiant de machine en
dur dans un moteur est un moteur qui ne tourne que sur une machine.

Estimation tokens : proxy déterministe chars/4 (aucun appel tiktoken sur des
mégaoctets de backlog à chaque cycle — l'ordre de grandeur suffit pour un
seuil à 100 kt, et le proxy est stable/reproductible d'un cycle à l'autre).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("arac.cortex.value_gate")

DEFAULT_UNCURED_KTOK_MIN = 100.0
DEFAULT_ENGAGED_CURSOR_MIN = 1
def _default_operator_nodes() -> frozenset[str]:
    """Le pendant serveur de votre poste source (cf migration 0020).

    Si l'identité du cerveau n'est pas encore connue (dépôt fraîchement
    cloné, test unitaire), on rend un ensemble VIDE : aucun nœud n'est
    opérateur, donc le gate ne propose l'exclusion de rien. Se taire est le
    bon défaut — proposer d'exclure au hasard ne l'est pas.
    """
    try:
        import arac_runtime

        return frozenset({f"{arac_runtime.node_id()}-server"})
    except Exception:
        return frozenset()


DEFAULT_OPERATOR_NODES = _default_operator_nodes()

# Proxy tokens déterministe (cf docstring module).
_CHARS_PER_TOKEN = 4.0

# Candidats pending, prédicat MINIMAL (jamais le gate complet : le value-gate
# regarde le backlog ENTIER, y compris les conversations en backoff — un géant
# déféré par le pas 2 reste un candidat au drain). `exclusion_category IS
# NULL` : les déjà-exclues (drain pas 2 / futur enforce) sortent d'office.
_CANDIDATES_SQL = (
    "SELECT c.id::text, c.conversation_uid, c.node_id, c.source_type, "
    "       c.atoms_generated, c.curated_through_message_id, "
    "       COALESCE(sum(length(m.content)) "
    "                FILTER (WHERE m.id > c.curated_through_message_id), 0) "
    "         AS uncured_chars "
    "FROM arac.conversations c "
    "JOIN arac.raw_messages m ON m.conversation_id = c.id "
    "WHERE c.acked = false AND c.exclusion_category IS NULL "
    "GROUP BY c.id "
    "HAVING count(*) FILTER (WHERE m.id > c.curated_through_message_id) >= 1"
)


def _log(event: str, **kw: Any) -> None:
    logger.info(json.dumps({"event": event, **kw}, ensure_ascii=False, default=str))


def thresholds_from_env() -> dict[str, Any]:
    """Seuils du scorer, défauts = (fail-safe : une valeur env
    illisible retombe sur le défaut, jamais un crash du cycle)."""
    def _f(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, "") or default)
        except ValueError:
            return default

    nodes_raw = os.environ.get("ARAC_VALUE_GATE_OPERATOR_NODES", "")
    nodes = frozenset(n.strip() for n in nodes_raw.split(",") if n.strip()) \
        or DEFAULT_OPERATOR_NODES
    return {
        "uncured_ktok_min": _f("ARAC_VALUE_GATE_UNCURED_KTOK_MIN",
                               DEFAULT_UNCURED_KTOK_MIN),
        "engaged_cursor_min": int(_f("ARAC_VALUE_GATE_ENGAGED_CURSOR_MIN",
                                     DEFAULT_ENGAGED_CURSOR_MIN)),
        "operator_nodes": nodes,
    }


def score_row(
    row: dict[str, Any],
    *,
    uncured_ktok_min: float = DEFAULT_UNCURED_KTOK_MIN,
    engaged_cursor_min: int = DEFAULT_ENGAGED_CURSOR_MIN,
    operator_nodes: frozenset[str] = DEFAULT_OPERATOR_NODES,
) -> dict[str, Any] | None:
    """Scoring PUR d'une conversation pending (row : conversation_uid,
    node_id, atoms_generated, cursor, uncured_chars). Retourne le détail
    chiffré du candidat LOW_VALUE, ou None si la conversation est protégée.

    Les 4 critères de, TOUS requis (conjonction stricte —
    fail-toward-keep : au moindre doute la conversation reste curable) :
    atoms_generated=0 (dur), engagement prouvé (curseur), masse résiduelle,
    node opérateur."""
    atoms = int(row.get("atoms_generated") or 0)
    if atoms != 0:
        return None  # GARDE DURE : a déjà produit -> jamais candidate.
    cursor = int(row.get("cursor") or 0)
    if cursor < max(1, engaged_cursor_min):
        return None  # jamais engagée par le LLM -> pas de preuve de stérilité.
    if str(row.get("node_id") or "") not in operator_nodes:
        return None  # jamais « la source » en bloc : nodes opérateur seulement.
    uncured_ktok = float(row.get("uncured_chars") or 0) / _CHARS_PER_TOKEN / 1000.0
    if uncured_ktok < uncured_ktok_min:
        return None
    return {
        "uid": row.get("conversation_uid"),
        "node_id": row.get("node_id"),
        "source_type": row.get("source_type"),
        "atoms_generated": atoms,
        "cursor": cursor,
        "uncured_ktok": round(uncured_ktok, 1),
        "score": "low_value_operator_session",
    }


async def shadow_scan(db, *, thresholds: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """SCAN SHADOW du backlog pending (LECTURE SEULE STRICTE) : score chaque
    conversation, LOGGE chaque candidat would-be-excluded avec ses chiffres
    (`value_gate.shadow_exclude`) + un résumé (`value_gate.shadow_summary`).

    AUCUNE ÉCRITURE, AUCUNE DÉCISION : la liste retournée/loggée est la
    matière de VOTRE revue, avant tout armement. Les uid de
    conversation sont des identifiants techniques (uuid), jamais une PII —
    les clés d'atomes, elles, restent sha8 partout (V0.107) mais aucun
    contenu ni clé ne transite par ce module."""
    th = thresholds or thresholds_from_env()
    async with db.cursor() as cur:
        await cur.execute(_CANDIDATES_SQL)
        rows = await cur.fetchall()
    candidates: list[dict[str, Any]] = []
    for r in rows:
        cand = score_row(
            {
                "id": r[0], "conversation_uid": r[1], "node_id": r[2],
                "source_type": r[3], "atoms_generated": r[4],
                "cursor": r[5], "uncured_chars": r[6],
            },
            uncured_ktok_min=th["uncured_ktok_min"],
            engaged_cursor_min=th["engaged_cursor_min"],
            operator_nodes=th["operator_nodes"],
        )
        if cand is not None:
            candidates.append(cand)
            _log("value_gate.shadow_exclude", **cand)
    _log("value_gate.shadow_summary",
         scanned=len(rows), would_be_excluded=len(candidates),
         uncured_ktok_min=th["uncured_ktok_min"],
         engaged_cursor_min=th["engaged_cursor_min"],
         operator_nodes=sorted(th["operator_nodes"]))
    return candidates
