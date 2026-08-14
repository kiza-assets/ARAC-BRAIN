"""Chantier « Perception V4 » — primitives de backoff extraites vers `agents/lib/curator_backoff.py`.

Preuve que l'extraction (ex `agents/lib/curator_lib.py` v1, retiré) n'a rien cassé :
`curator_lib_v2.mark_curation_failed` doit continuer à planifier le backoff LINÉAIRE
avec les MÊMES constantes (`_BACKOFF_STEP_MIN`/`_BACKOFF_MAX_STEPS`) et la même
troncature (`_trunc_error`), désormais importées depuis `curator_backoff` plutôt que
depuis l'ancien module complet. AUCUNE DB, aucun .env (conftest fail-closed).
"""

from __future__ import annotations

from agents.lib import curator_backoff as cb
from agents.lib import curator_lib_v2 as cl2


# === curator_backoff — primitives pures =====================================

def test_trunc_error_passthrough_under_limit():
    assert cb._trunc_error("chunks_failed:[2,3]") == "chunks_failed:[2,3]"


def test_trunc_error_truncates_over_limit():
    assert cb._trunc_error("x" * 10, limit=3) == "xxx"


def test_trunc_error_none_stays_none():
    assert cb._trunc_error(None) is None


def test_backoff_constants_are_positive_defaults():
    # Défauts doctrine (30 min x jusqu'à 5 essais -> 30/60/90/120/150 min).
    assert cb._BACKOFF_STEP_MIN == 30
    assert cb._BACKOFF_MAX_STEPS == 5


# === curator_lib_v2.mark_curation_failed — repointage réel ==================

class _FakeCursor:
    def __init__(self, fetch_row=None):
        self.executed: list[tuple] = []
        self._row = fetch_row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, sql, params=None):
        self.executed.append((sql, params))

    async def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, fetch_row=None):
        self.cur = _FakeCursor(fetch_row)
        self.commits = 0

    def cursor(self, *a, **k):
        return self.cur

    async def commit(self):
        self.commits += 1


async def test_mark_curation_failed_uses_extracted_backoff_primitives():
    db = _FakeConn(fetch_row=(3,))
    retry_count = await cl2.mark_curation_failed(db, "conv-1", error="chunks_failed:[2]")

    assert retry_count == 3
    sql, params = db.cur.executed[0]
    assert "retry_count = retry_count + 1" in sql
    assert "next_retry_at = now() + make_interval" in sql
    # Les constantes de curator_backoff (PAS des valeurs en dur) alimentent le SQL.
    assert params == ("chunks_failed:[2]", cb._BACKOFF_STEP_MIN, cb._BACKOFF_MAX_STEPS, "conv-1")
    # mark_curation_failed NE COMMITE PAS (discipline transactionnelle du caller).
    assert db.commits == 0


async def test_mark_curation_failed_truncates_error_via_curator_backoff():
    db = _FakeConn(fetch_row=(1,))
    long_error = "e" * 5000
    await cl2.mark_curation_failed(db, "conv-2", error=long_error)
    _, params = db.cur.executed[0]
    assert params[0] == cb._trunc_error(long_error)
    assert len(params[0]) == 2000


async def test_mark_curation_failed_no_row_returns_zero():
    db = _FakeConn(fetch_row=None)
    retry_count = await cl2.mark_curation_failed(db, "conv-3", error=None)
    assert retry_count == 0
