"""Module utility de capture intégrale des transcripts de missions agents ARAC.

Un JSONL par mission, append-only, secrets masqués AVANT écriture. C'est ce
qui rend une décision d'agent rejouable des mois plus tard : sans transcript,
un agent qui se trompe est un mystère définitif.

Responsabilités :
- `MissionLogger(mission_id, base_dir)` : ouvre un fichier JSONL append-only par
  mission, masque les 13 patterns secrets connus AVANT écriture, sérialise un
  JSON-ligne par event.
- Permissions : fichier 0640, dir parent 0750 (root:aracagent attendu côté
  filesystem, fixé par installation hors-code).
- `close()` : écrit un event `_close`, gzip optionnel si fichier > 10 MB.

Doctrine : capture intégrale (PAS de troncature des champs texte). Toute valeur
texte est masquée systématiquement par `mask_secrets()` avant écriture, sans
whitelist de champs — defense-in-depth zéro-leak.

Trace amont : atome fccf15ce (kind=state, décision user 2026-05-22 retention 90j).
"""

from __future__ import annotations

import datetime as _dt
import gzip
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

import arac_runtime
from app.journal import raison  # noqa: E402

logger = logging.getLogger("arac.log_capture")

DEFAULT_BASE_DIR = str(arac_runtime.agent_logs_dir())
_GZIP_THRESHOLD_BYTES = 10 * 1024 * 1024  # 10 MB

# Les 13 regex de masquage (cf spec Bloc 9a). Ordre IMPORTANT : les patterns
# les plus spécifiques d'abord (sk-ant- avant sk-, AKIA avant generic).
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-ant-[a-zA-Z0-9_\-]+"), "[REDACTED:anthropic-key]"),
    (re.compile(r"sk-[a-zA-Z0-9]{40,}"), "[REDACTED:openai-key]"),
    (re.compile(r"ghp_[a-zA-Z0-9]{30,}"), "[REDACTED:github-pat]"),
    (re.compile(r"gho_[a-zA-Z0-9]{30,}"), "[REDACTED:github-oauth]"),
    (re.compile(r"glpat-[a-zA-Z0-9_\-]+"), "[REDACTED:gitlab-pat]"),
    (re.compile(r"xoxb-[a-zA-Z0-9-]+"), "[REDACTED:slack-bot]"),
    (re.compile(r"(AKIA|ASIA)[A-Z0-9]{16}"), "[REDACTED:aws-key]"),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
        ),
        "[REDACTED:private-key]",
    ),
    (
        re.compile(
            r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}"
        ),
        "[REDACTED:jwt]",
    ),
    (re.compile(r"(?i)password\s*[=:]\s*\S+"), "password=[REDACTED]"),
    (re.compile(r"(?i)bearer\s+[a-zA-Z0-9\-._~+/]{20,}"), "bearer [REDACTED]"),
    (re.compile(r"postgres://[^@]+@"), "postgres://[REDACTED]@"),
    (
        re.compile(r"(?i)token\s*[=:]\s*[A-Za-z0-9_\-]{20,}"),
        "token=[REDACTED]",
    ),
)


def mask_secrets(text: str) -> str:
    """Applique les 13 regex de masquage. Retourne le texte masqué.

    Idempotent : `mask_secrets(mask_secrets(x)) == mask_secrets(x)` car les
    patterns `[REDACTED:*]` ne matchent aucune des regex.
    """
    if not isinstance(text, str) or not text:
        return text
    out = text
    for pat, repl in _SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


def _mask_recursive(value: Any) -> Any:
    """Applique mask_secrets récursivement sur tous les str d'une structure JSON.

    Préserve les clés (les noms de champs ne sont jamais des secrets en
    pratique ; un nom comme `password` reste tel quel, c'est sa valeur qu'on
    masque).
    """
    if isinstance(value, str):
        return mask_secrets(value)
    if isinstance(value, dict):
        return {k: _mask_recursive(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask_recursive(v) for v in value]
    return value


class MissionLogger:
    """Logger transcript intégral par mission (JSONL append-only).

    Usage :
        logger = MissionLogger(mission_id)
        logger.write_event("mission.start", prompt="...")
        logger.write_event("subprocess.exit", exit_code=0, duration_ms=1234)
        logger.close()
    """

    def __init__(self, mission_id: str, base_dir: str = DEFAULT_BASE_DIR):
        self.mission_id = mission_id
        self.base_dir = Path(base_dir)
        # Dir parent : on s'assure qu'il existe avec 0750. Si déjà existant
        # avec des perms différentes, on ne touche pas (idempotent).
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            # chmod best-effort, ne lève pas si pas owner (cas tests user).
            try:
                os.chmod(self.base_dir, 0o750)
            except (OSError, PermissionError):
                pass
        except Exception as e:  # noqa: BLE001
            logger.warning(json.dumps({
                "event": "log_capture.mkdir_warn",
                "base_dir": str(self.base_dir),
                "raison": raison(e),
            }))

        self.path = self.base_dir / f"{mission_id}.jsonl"
        self._closed = False
        self._bytes_written = 0

        # Crée le fichier s'il n'existe pas, fixe perms 0640.
        try:
            # Open en append : ne tronque pas un fichier existant (cas auditor
            # qui rouvre un transcript en mode append).
            with open(self.path, "a", encoding="utf-8"):
                pass
            try:
                os.chmod(self.path, 0o640)
            except (OSError, PermissionError):
                pass
        except Exception as e:  # noqa: BLE001
            logger.warning(json.dumps({
                "event": "log_capture.touch_warn",
                "path": str(self.path),
                "raison": raison(e),
            }))

    def write_event(self, event_type: str, **fields: Any) -> None:
        """Sérialise une ligne JSON et l'append au fichier.

        Tous les champs `str` (récursivement dict/list) sont masqués via
        `mask_secrets()` AVANT écriture. Les champs `ts`, `mission_id`,
        `event_type` sont injectés automatiquement.
        """
        if self._closed:
            logger.warning(json.dumps({
                "event": "log_capture.write_after_close",
                "mission_id": self.mission_id,
                "event_type": event_type,
            }))
            return

        record: dict[str, Any] = {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "mission_id": self.mission_id,
            "event_type": event_type,
        }
        # Masque tous les fields fournis (récursif)
        record.update(_mask_recursive(fields))

        try:
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line)
            self._bytes_written += len(line.encode("utf-8"))
        except Exception as e:  # noqa: BLE001
            # Ne JAMAIS faire planter le caller — la capture est un mécanisme
            # auxiliaire. On log dans journald via logger root.
            logger.error(json.dumps({
                "event": "log_capture.write_fail",
                "mission_id": self.mission_id,
                "event_type": event_type,
                "raison": raison(e),
            }))

    def close(self, gzip_if_oversized: bool = True) -> None:
        """Finalise le transcript. Écrit un event `_close`, gzip si > 10 MB.

        Idempotent : appel multiples no-op après le premier.
        """
        if self._closed:
            return
        self.write_event("_close", bytes_written=self._bytes_written)
        self._closed = True

        if not gzip_if_oversized:
            return
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size <= _GZIP_THRESHOLD_BYTES:
            return
        gz_path = self.path.with_suffix(".jsonl.gz")
        try:
            with open(self.path, "rb") as src, gzip.open(gz_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            os.remove(self.path)
            try:
                os.chmod(gz_path, 0o640)
            except (OSError, PermissionError):
                pass
            logger.info(json.dumps({
                "event": "log_capture.gzipped",
                "mission_id": self.mission_id,
                "size_before": size,
            }))
        except Exception as e:  # noqa: BLE001
            logger.warning(json.dumps({
                "event": "log_capture.gzip_fail",
                "mission_id": self.mission_id,
                "raison": raison(e),
            }))

    @property
    def bytes_written(self) -> int:
        return self._bytes_written

    def __enter__(self) -> "MissionLogger":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()
