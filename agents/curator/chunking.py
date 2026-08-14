"""Découpe d'une conversation en segments curables — v0.6.

Une conversation dont le prompt curator dépasse le contexte effectif du modèle
(observé : >= ~137 msgs -> 'Prompt is too long') est découpée en SEGMENTS de
messages dont le prompt complet reste sous un budget de tokens conservateur.

Règles :
- on ne coupe JAMAIS un message en deux (granularité = message) ;
- packing glouton : on remplit un segment jusqu'à ce que l'ajout du message
  suivant ferait dépasser le budget, puis on ouvre un nouveau segment ;
- un message seul plus gros que le budget occupe son propre segment (il pourra
  encore échouer en aval -> géré gracieusement par le curator, pas ici) ;
- une conversation qui tient déjà sous le budget renvoie 1 seul segment
  (comportement v0.5.1 inchangé, passthrough).
"""

from __future__ import annotations

import json
from typing import Any, Callable

# Surcoût de séparation JSON par message (virgule, retours, indentation NDJSON).
# Petit, conservateur (on sur-compte un peu).
_PER_MESSAGE_SEPARATOR_TOKENS = 4


def split_messages_into_chunks(
    messages: list[dict[str, Any]],
    *,
    overhead_tokens: int,
    budget_tokens: int,
    count_fn: Callable[[str], int],
) -> list[list[dict[str, Any]]]:
    """Découpe `messages` en segments tels que
    `overhead_tokens + tokens(segment) <= budget_tokens`.

    Args:
      overhead_tokens : coût fixe du prompt hors messages (template + scopes).
      budget_tokens   : budget total cible par prompt (cf ARAC_CURATOR_CHUNK_TOKEN_BUDGET).
      count_fn        : fonction de comptage de tokens (token_count.count_tokens).

    Returns: liste de segments (chaque segment = liste de messages). Toujours au
      moins 1 segment si `messages` est non vide ; [] si `messages` est vide.
    """
    if not messages:
        return []

    # Budget réellement disponible pour les messages d'un segment.
    msg_budget = max(1, budget_tokens - overhead_tokens)

    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_tokens = 0

    for msg in messages:
        mt = count_fn(json.dumps(msg, ensure_ascii=False)) + _PER_MESSAGE_SEPARATOR_TOKENS
        # Si le segment courant n'est pas vide et que l'ajout dépasse, on ferme.
        if current and current_tokens + mt > msg_budget:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(msg)
        current_tokens += mt

    if current:
        chunks.append(current)

    return chunks
