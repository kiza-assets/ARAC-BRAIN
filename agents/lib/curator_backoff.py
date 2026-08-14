"""Primitives de backoff/troncature partagées par le curateur — chantier « Perception V4 ».

Extrait de `agents/lib/curator_lib.py` (v1, retiré) au moment de la suppression
du code mort v1 : `curator_lib_v2.py` est la SEULE consommatrice vivante de ces
primitives (cf grep/AST), d'où leur isolement dans un module dédié plutôt
que de traîner tout `curator_lib.py` (qui, lui, n'opère que sur l'ancienne
table `arac.raw_conversations`, gelée depuis l'ingestion V2).

Aucun import de l'API ARAC ni de psycopg ici : module pur, testable off-line.
"""

from __future__ import annotations

import os

# --- F2 : retry borné + backoff linéaire (anti-boucle) ----------------------
# Backoff LINÉAIRE : next_retry_at = NOW() + step * min(essai, max_steps).
# Défaut step=30 min, max_steps=5 -> 30/60/90/120/150 min.
_BACKOFF_STEP_MIN = max(1, int(os.environ.get("ARAC_CURATOR_RETRY_BACKOFF_STEP_MIN", "30")))
_BACKOFF_MAX_STEPS = max(1, int(os.environ.get("ARAC_CURATOR_RETRY_BACKOFF_MAX_STEPS", "5")))


def _trunc_error(msg: str | None, limit: int = 2000) -> str | None:
    """Tronque un motif d'erreur INTERNE pour la colonne last_error.

    IMPORTANT : `last_error` ne doit JAMAIS recevoir du contenu de conversation
    ni un stdout brut de subprocess (risque de fuite de secret). Uniquement des
    raisons STRUCTURÉES internes ('chunks_failed:[2,3]', 'decompress_fail:ValueError',
    'superseded_by_newer_snapshot:<id>', 'zero_atoms:...'). La troncature est une
    ceinture supplémentaire.
    """
    if msg is None:
        return None
    return msg[:limit]
