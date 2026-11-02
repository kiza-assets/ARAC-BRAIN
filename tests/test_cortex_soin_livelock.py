"""Tests du soin du livelock de digestion : bisection relâchée après un reçu
`empty`, parking des conversations dont un message dépasse le budget,
dédoublonnage de la review-queue, saut des artefacts d'outillage, jeton du bot
absent des journaux. Hermétique : aucun réseau, aucune base."""
from __future__ import annotations

import logging

from agents.cortex import cycle
from agents.lib import curator_lib_v2
from app.perception import ingest_watchdog as w


def _pm(uid: str, cursor_from: int, max_id: int) -> dict:
    return {"conversation_id": f"id-{uid}", "uid": uid,
            "cursor_from": cursor_from, "max_id": max_id, "n_msgs": 1}


class _Cur:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        self.last = sql

    async def fetchall(self):
        return self.conn.rows

    @property
    def rowcount(self):
        return self.conn.rowcount

    async def fetchone(self):
        if "left(content" in self.last:
            return self.conn.head_row
        if "status = 'empty'" in self.last:
            return self.conn.empty_row
        if "digestion_review_queue" in self.last:
            return self.conn.pending_row
        return None


class _Conn:
    def __init__(self, rows=None, empty_row=None, pending_row=None,
                 head_row=None, rowcount=0):
        self.rows, self.empty_row, self.pending_row = rows or [], empty_row, pending_row
        self.head_row, self.rowcount = head_row, rowcount
        self.executed: list[tuple] = []

    def cursor(self, *a, **k):
        return _Cur(self)


PACK = [_pm(f"c{i}", 1, 10) for i in range(8)]


# --- Bisection relâchée ------------------------------------------------------


async def test_bisection_relachee_si_empty_posterieur():
    conn = _Conn(rows=[(20, "quarantined", PACK, None), (19, "quarantined", PACK, None)],
                 empty_row=(25,))
    assert await cycle._bisected_max_conversations(conn, default=20) == 20
    sql, params = conn.executed[-1]
    assert "status = 'empty'" in sql and params[0] == 20


async def test_bisection_inchangee_sans_empty_posterieur():
    conn = _Conn(rows=[(20, "quarantined", PACK, None), (19, "quarantined", PACK, None)])
    assert await cycle._bisected_max_conversations(conn, default=20) == 4


async def test_bisection_ne_compte_que_les_recus_terminaux():
    conn = _Conn(rows=[(20, "quarantined", PACK, None), (19, "quarantined", PACK, None)])
    await cycle._bisected_max_conversations(conn, default=20)
    first_sql = conn.executed[0][0]
    assert "status IN ('done', 'quarantined', 'spawn_failed')" in first_sql


async def test_bisection_sequence_q_q_empty_puis_q_seul():
    q = [(20, "quarantined", PACK, None), (19, "quarantined", PACK, None)]
    assert await cycle._bisected_max_conversations(
        _Conn(rows=q, empty_row=(21,)), default=20) == 20
    # Une seule quarantaine (le terminal précédent est `done`) : pas de bisection.
    seul = [(22, "quarantined", PACK, None), (18, "done", PACK, None)]
    assert await cycle._bisected_max_conversations(_Conn(rows=seul), default=20) == 20


# --- Parking et dédoublonnage ------------------------------------------------

OVERSIZED = [
    {"uid": "conv-a", "message_id": 101, "chars": 497019, "est_tokens": 119000},
    {"uid": "conv-b", "message_id": 202, "chars": 400000, "est_tokens": 100000},
]


async def test_park_oversized_conversation_sql():
    conn = _Conn()
    await curator_lib_v2.park_oversized_conversation(conn, "conv-a", 101)
    sql, params = conn.executed[0]
    assert "next_retry_at = now() + make_interval(days => %s)" in sql
    assert "WHERE conversation_uid = %s" in sql
    assert "cursor" not in sql and "retry_count" not in sql and "acked" not in sql
    assert params == (7, "oversized_message:101", "conv-a")


async def test_oversized_parking_pour_chaque_element_et_insert(monkeypatch):
    inserted, parked = [], []

    async def fake_insert(conn, run_ref, uid, *a):
        inserted.append(uid)

    async def fake_park(conn, uid, mid, **k):
        parked.append((uid, mid))

    monkeypatch.setattr(cycle.review_queue, "insert_review_row", fake_insert)
    monkeypatch.setattr(cycle.curator_lib_v2, "park_oversized_conversation", fake_park)
    text = await cycle._record_oversized_messages(_Conn(), OVERSIZED, slot_key="s@k")
    assert parked == [("conv-a", 101), ("conv-b", 202)]
    assert inserted == ["conv-a", "conv-b"]
    assert "2 message(s) surdimensionné(s)" in text


async def test_oversized_deuxieme_passage_zero_insert(monkeypatch):
    inserted, parked = [], []

    async def fake_insert(*a):
        inserted.append(a)

    async def fake_park(conn, uid, mid, **k):
        parked.append((uid, mid))

    monkeypatch.setattr(cycle.review_queue, "insert_review_row", fake_insert)
    monkeypatch.setattr(cycle.curator_lib_v2, "park_oversized_conversation", fake_park)
    conn = _Conn(pending_row=(1,))
    await cycle._record_oversized_messages(conn, OVERSIZED, slot_key="s@k")
    assert inserted == []
    assert len(parked) == 2  # parking posé dans tous les cas


# --- Saut automatique des artefacts d'outillage --------------------------------

SKILL_HEAD = "Base directory for this skill: /some/where SECRET-BODY"
ONE = OVERSIZED[:1]


def _capture(monkeypatch):
    parked, logs = [], []

    async def fake_insert(*a):
        pass

    async def fake_park(conn, uid, mid, **k):
        parked.append((uid, mid))
        return 1

    monkeypatch.setattr(cycle.review_queue, "insert_review_row", fake_insert)
    monkeypatch.setattr(cycle.curator_lib_v2, "park_oversized_conversation", fake_park)
    monkeypatch.setattr(cycle, "_log", lambda event, **f: logs.append((event, f)))
    return parked, logs


async def test_prefixe_reconnu_en_tete_saute_sans_parking(monkeypatch):
    parked, logs = _capture(monkeypatch)
    conn = _Conn(head_row=("  " + SKILL_HEAD,), rowcount=1)
    await cycle._record_oversized_messages(conn, ONE, slot_key="s@k")
    assert parked == []
    upd = [x for x in conn.executed if "UPDATE arac.conversations" in x[0]]
    assert len(upd) == 1
    sql = upd[0][0]
    assert "curated_through_message_id < %(mid)s" in sql
    assert "next_retry_at = NULL" in sql
    assert "NOT EXISTS" in sql and "c.conversation_uid = %(uid)s" in sql
    assert upd[0][1]["mid"] == 101 and upd[0][1]["uid"] == "conv-a"
    drop = [x for x in conn.executed if "reviewed_dropped" in x[0]]
    assert len(drop) == 1
    assert drop[0][1] == ("conv-a", "101")
    assert logs[-1][0] == "cortex.oversized_tool_artifact_skipped"


async def test_prefixe_reconnu_mais_pas_en_tete_parque(monkeypatch):
    parked, logs = _capture(monkeypatch)
    conn = _Conn(head_row=(SKILL_HEAD,), rowcount=0)
    await cycle._record_oversized_messages(conn, ONE, slot_key="s@k")
    assert parked == [("conv-a", 101)]
    assert [e for e, _ in logs] == ["cortex.oversized_tool_artifact_not_head_or_gap"]
    assert not [x for x in conn.executed if "reviewed_dropped" in x[0]]


async def test_prefixe_inconnu_parque(monkeypatch):
    parked, logs = _capture(monkeypatch)
    conn = _Conn(head_row=("Un message géant quelconque",), rowcount=1)
    await cycle._record_oversized_messages(conn, ONE, slot_key="s@k")
    assert parked == [("conv-a", 101)]
    assert not [x for x in conn.executed if "UPDATE arac.conversations" in x[0]]
    assert logs == []


async def test_env_surcharge_les_prefixes(monkeypatch):
    assert cycle._tool_artifact_prefixes() == cycle.TOOL_ARTIFACT_PREFIXES
    monkeypatch.setenv("ARAC_OVERSIZED_SKIP_PREFIXES", "Foo-prefix-long:|Bar-prefix-long:")
    assert cycle._tool_artifact_prefixes() == ("Foo-prefix-long:", "Bar-prefix-long:")
    parked, _ = _capture(monkeypatch)
    # Le préfixe par défaut n'est plus reconnu, le préfixe surchargé l'est.
    await cycle._record_oversized_messages(
        _Conn(head_row=(SKILL_HEAD,), rowcount=1), ONE, slot_key="s@k")
    assert parked == [("conv-a", 101)]
    parked.clear()
    await cycle._record_oversized_messages(
        _Conn(head_row=("Bar-prefix-long: xyz",), rowcount=1), ONE, slot_key="s@k")
    assert parked == []
    monkeypatch.setenv("ARAC_OVERSIZED_SKIP_PREFIXES", "")
    assert cycle._tool_artifact_prefixes() == cycle.TOOL_ARTIFACT_PREFIXES


async def test_prefixe_env_trop_court_refuse(monkeypatch):
    _, logs = _capture(monkeypatch)
    monkeypatch.setenv("ARAC_OVERSIZED_SKIP_PREFIXES", "Base|short")
    assert cycle._tool_artifact_prefixes() == cycle.TOOL_ARTIFACT_PREFIXES
    refused = [f for e, f in logs if e == "cortex.oversized_skip_prefix_refused"]
    assert [f["length"] for f in refused] == [4, 5]
    assert all(set(f) == {"length"} for f in refused)


async def test_prefixe_env_trop_long_refuse(monkeypatch):
    _, logs = _capture(monkeypatch)
    long_p = "x" * 121
    monkeypatch.setenv("ARAC_OVERSIZED_SKIP_PREFIXES", long_p + "|" + "y" * 120)
    assert cycle._tool_artifact_prefixes() == ("y" * 120,)
    refused = [f for e, f in logs if e == "cortex.oversized_skip_prefix_too_long"]
    assert refused == [{"length": 121}]
    assert "x" * 20 not in repr(logs)


async def test_alerte_parking_seulement_si_ligne_touchee(monkeypatch):
    _capture(monkeypatch)
    for rows, attendu, absent in ((1, "parqué 7 j", "non appliqué"),
                                  (0, "parking non appliqué", "parqué 7 j")):
        async def fake_park(conn, uid, mid, _r=rows, **k):
            return _r
        monkeypatch.setattr(cycle.curator_lib_v2, "park_oversized_conversation", fake_park)
        text = await cycle._record_oversized_messages(_Conn(), ONE, slot_key="s@k")
        assert attendu in text and absent not in text


async def test_park_oversized_conversation_retourne_rowcount():
    conn = _Conn(rowcount=1)
    assert await curator_lib_v2.park_oversized_conversation(conn, "conv-a", 101) == 1


async def test_select_tete_limite_au_role_user(monkeypatch):
    _capture(monkeypatch)
    conn = _Conn(head_row=None)
    await cycle._record_oversized_messages(conn, ONE, slot_key="s@k")
    sel = [x[0] for x in conn.executed if "left(content" in x[0]]
    assert sel and "role = 'user'" in sel[0]


async def test_journal_sans_contenu_ni_prefixe_brut(monkeypatch):
    parked, logs = _capture(monkeypatch)
    for rc in (1, 0):
        conn = _Conn(head_row=(SKILL_HEAD,), rowcount=rc)
        text = await cycle._record_oversized_messages(conn, ONE, slot_key="s@k")
        assert "SECRET-BODY" not in text
    assert logs
    for _, fields in logs:
        blob = repr(fields)
        assert "SECRET-BODY" not in blob
        assert cycle.TOOL_ARTIFACT_PREFIXES[0] not in blob
        assert len(fields["prefix_sha"]) == 12


# --- Jeton du bot hors des journaux ------------------------------------------


def test_quiet_httpx_logs_releve_le_seuil():
    for n in ("httpx", "httpcore"):
        logging.getLogger(n).setLevel(logging.INFO)
    w._quiet_httpx_logs()
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING


def test_send_telegram_releve_le_seuil_avant_l_envoi(monkeypatch):
    for n in ("httpx", "httpcore"):
        logging.getLogger(n).setLevel(logging.INFO)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "1")
    monkeypatch.setattr(w, "_post_with_retry", lambda *a, **k: (True, "ok"))
    assert w.send_telegram("t")[0] is True
    assert logging.getLogger("httpx").level >= logging.WARNING
