"""Compteur de tokens — proxy pour dimensionner le chunking curator (v0.6).

`count_tokens` utilise tiktoken `o200k_base`. NB IMPORTANT : tiktoken encode pour
les modèles OpenAI, PAS pour Claude. C'est donc un PROXY d'ordre de grandeur
(typiquement ±10-20 % des tokens Claude réels) ; le budget de chunking est en
conséquence volontairement conservateur (cf. la découpe en segments).

Robustesse : si tiktoken n'est pas chargeable (pas de réseau/cache sous le service
curator sandboxé au premier `get_encoding`), on retombe sur une estimation par
octets — calibrée sur les conversations ARAC (~2.8 octets/token o200k, on prend
/3 pour SUR-estimer, donc des chunks plus petits = côté sûr). Le comptage ne doit
jamais faire planter la curation.
"""

from __future__ import annotations

import functools
import logging

logger = logging.getLogger("arac.token_count")

_ENCODING_NAME = "o200k_base"
# Estimation de repli : octets / _BYTES_PER_TOKEN. 3 < 2.84 mesuré -> sur-estime
# légèrement le nombre de tokens (chunks un peu plus petits, marge de sécurité).
_BYTES_PER_TOKEN = 3


@functools.lru_cache(maxsize=1)
def _encoding():
    """Charge l'encodage tiktoken une seule fois. Peut lever (réseau/cache)."""
    import tiktoken

    return tiktoken.get_encoding(_ENCODING_NAME)


@functools.lru_cache(maxsize=1)
def _tiktoken_available() -> bool:
    try:
        _encoding().encode("ping")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(
            '{"event": "token_count.tiktoken_unavailable", "fallback": "bytes", '
            '"error": "%s"}',
            type(e).__name__,
        )
        return False


def count_tokens(text: str) -> int:
    """Nombre de tokens (tiktoken o200k) ou estimation par octets en repli."""
    if not text:
        return 0
    if _tiktoken_available():
        try:
            return len(_encoding().encode(text))
        except Exception:  # noqa: BLE001 — ne jamais planter sur le comptage
            pass
    return len(text.encode("utf-8")) // _BYTES_PER_TOKEN
