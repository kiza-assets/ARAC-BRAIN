"""Tests de `agents/cortex/review_queue.py`.

Deux volets :
  - hermétique (aucune DB réelle) : un fake `conn`/cursor capture les
    INSERT. Couvre une row attendue par disposition (`insert_review_row`),
    colonnes correctes ; sanitisation du `proposed_atom` (masquage secret +
    troncature ~2000 chars) ; queue indisponible (exception à l'INSERT) ->
    best-effort, PAS de crash ; invariant receipts <-> atomes, fonction PURE
    (égalité/écart) ; migration de l'INSERT ad-hoc
    `cycle._record_oversized_messages` vers ce module.
  - DB réelle (cluster jetable, SKIP proprement si `DATABASE_URL_APP_TEST`
    absente, cf tests/conftest.py) : revue adversariale, finding 1/7/27 —
    l'INSERT best-effort doit être isolé par SAVEPOINT sur la connexion
    PARTAGÉE du disposant, sinon un échec d'INSERT laisse la transaction
    ABORTED et fait perdre l'écriture DÉJÀ CONSENTIE (retry_count) du caller.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import psycopg
import pytest

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from agents.cortex import cycle, review_queue  # noqa: E402
from agents.lib import curator_lib_v2  # noqa: E402


# ============================================================================
# Fakes — conn/cursor hermétiques (aucune vraie DB)
# ============================================================================


class _FakeCursor:
    def __init__(self, conn: "_FakeConn"):
        self._conn = conn

    async def __aenter__(self) -> "_FakeCursor":
        return self

    async def __aexit__(self, *a) -> bool:
        return False

    async def execute(self, sql, params=None):
        self._conn.executed.append((sql, params))
        if self._conn.raise_on_execute is not None:
            raise self._conn.raise_on_execute

    async def fetchone(self):
        return self._conn.fetch_result


class _FakeTransaction:
    """Miroir hermétique de `psycopg.AsyncConnection.transaction()` (savepoint) :
    ne fait RIEN de spécial (pas de vraie DB) mais NE SUPPRIME AUCUNE exception
    — même comportement que le vrai savepoint psycopg3 (rollback TO SAVEPOINT
    puis re-lève), laissant le `try/except` de `insert_review_row` l'avaler."""

    async def __aenter__(self) -> "_FakeTransaction":
        return self

    async def __aexit__(self, *a) -> bool:
        return False


class _FakeConn:
    """`raise_on_execute` simule une queue indisponible (table absente,
    connexion coupée...) ; `fetch_result` simule la row d'un SELECT COUNT/agrégat."""

    def __init__(self, *, raise_on_execute: Exception | None = None, fetch_result=None):
        self.executed: list[tuple] = []
        self.raise_on_execute = raise_on_execute
        self.fetch_result = fetch_result

    def cursor(self):
        return _FakeCursor(self)

    def transaction(self):
        return _FakeTransaction()


def _last_params(conn: _FakeConn) -> tuple:
    assert len(conn.executed) == 1, "exactement 1 INSERT attendu"
    return conn.executed[0][1]


# ============================================================================
# 1 row par disposition, colonnes correctes
# ============================================================================


async def test_kept_lower_confidence_row_has_incumbent_atom_id():
    conn = _FakeConn()
    await review_queue.insert_review_row(
        conn, "slot-1", "conv-1", "kept_lower_confidence",
        {"scope": "outillage", "kind": "gotcha", "key": "k", "value": "v"},
        "inc-uuid-1", "outillage", "gotcha")
    run_ref, uid, reason, atom_json, incumbent_id, scope, kind = _last_params(conn)
    assert (run_ref, uid, reason) == ("slot-1", "conv-1", "kept_lower_confidence")
    assert incumbent_id == "inc-uuid-1"
    assert (scope, kind) == ("outillage", "gotcha")
    assert json.loads(atom_json) == {"scope": "outillage", "kind": "gotcha", "key": "k", "value": "v"}


async def test_policy_skip_row_has_no_incumbent():
    conn = _FakeConn()
    await review_queue.insert_review_row(
        conn, "slot-1", "conv-2", "policy_skip",
        {"kind": "agent_message", "value": "x"}, None, "outillage", "agent_message")
    *_rest, incumbent_id, scope, kind = _last_params(conn)
    assert incumbent_id is None
    assert (scope, kind) == ("outillage", "agent_message")


async def test_atom_quarantine_row():
    conn = _FakeConn()
    await review_queue.insert_review_row(
        conn, "slot-1", "conv-3", "atom_quarantine",
        {"kind": "gotcha", "key": "k", "value": "v"}, None, "outillage/infrastructure", "gotcha")
    run_ref, uid, reason, _atom, incumbent_id, scope, kind = _last_params(conn)
    assert reason == "atom_quarantine"
    assert incumbent_id is None
    assert (scope, kind) == ("outillage/infrastructure", "gotcha")


async def test_coverage_omitted_row_uses_metadata_placeholder():
    conn = _FakeConn()
    await review_queue.insert_review_row(
        conn, "slot-1", "conv-4", "coverage_omitted",
        {"reason": "cortex_omission:atoms_empty", "retry_count": 2},
        None, "_systeme", "coverage_omitted")
    params = _last_params(conn)
    assert json.loads(params[3]) == {"reason": "cortex_omission:atoms_empty", "retry_count": 2}
    assert params[4] is None
    assert (params[5], params[6]) == ("_systeme", "coverage_omitted")


async def test_oversized_message_row():
    conn = _FakeConn()
    await review_queue.insert_review_row(
        conn, "slot-1", "conv-5", "oversized_message",
        {"message_id": 42, "chars": 400_000, "est_tokens": 100_000},
        None, "_systeme", "oversized_message")
    params = conn.executed[0][1]
    assert json.loads(params[3]) == {"message_id": 42, "chars": 400_000, "est_tokens": 100_000}


# ============================================================================
# Sanitisation : masquage secret + troncature ~2000 chars, récursif
# ============================================================================


async def test_secret_in_value_is_masked_before_write():
    conn = _FakeConn()
    leaking = "voici la clé sk-ant-abcdefghijklmnopqrstuvwxyz0123456789"
    await review_queue.insert_review_row(
        conn, "slot-1", "conv-6", "policy_skip",
        {"value": leaking}, None, "outillage", "gotcha")
    stored = json.loads(conn.executed[0][1][3])
    assert "sk-ant-" not in stored["value"], "le secret brut ne doit JAMAIS atteindre la row"
    assert "[REDACTED:anthropic-key]" in stored["value"]


async def test_secret_masking_is_recursive_through_nested_structures():
    conn = _FakeConn()
    payload = {"rationale": "cf token=abcdefghijklmnopqrstuvwx1234", "tags": ["ok", "postgres://user:pass@host/db"]}
    await review_queue.insert_review_row(
        conn, "slot-1", "conv-7", "atom_quarantine", payload, None, "outillage", "gotcha")
    stored = json.loads(conn.executed[0][1][3])
    assert "abcdefghijklmnopqrstuvwx1234" not in stored["rationale"]
    assert "user:pass" not in stored["tags"][1]


async def test_long_text_value_is_truncated_to_2000_chars():
    conn = _FakeConn()
    await review_queue.insert_review_row(
        conn, "slot-1", "conv-8", "policy_skip",
        {"value": "a" * 5000}, None, "outillage", "gotcha")
    stored = json.loads(conn.executed[0][1][3])
    assert len(stored["value"]) == 2000


async def test_email_in_value_is_masked_before_write():
    """PII légère : une adresse e-mail dans un champ texte est
    masquée, en plus du masquage secrets — le scrubber PII COMPLET reste un
    chantier roadmap (gap systémique), ce module ne masque
    QUE secrets+emails."""
    conn = _FakeConn()
    await review_queue.insert_review_row(
        conn, "slot-1", "conv-6b", "policy_skip",
        {"value": "contact alice.exemple@example.com pour suite"},
        None, "outillage", "gotcha")
    stored = json.loads(conn.executed[0][1][3])
    assert "alice.exemple@example.com" not in stored["value"]
    assert "[REDACTED:email]" in stored["value"]


async def test_email_masking_is_recursive_through_nested_structures():
    conn = _FakeConn()
    payload = {"rationale": "voir contact@example.com", "tags": ["ok", "autre@exemple.fr"]}
    await review_queue.insert_review_row(
        conn, "slot-1", "conv-6c", "atom_quarantine", payload, None, "outillage", "gotcha")
    stored = json.loads(conn.executed[0][1][3])
    assert "contact@example.com" not in stored["rationale"]
    assert "autre@exemple.fr" not in stored["tags"][1]


async def test_raw_message_content_never_forwarded_as_is_message_ids_preserved():
    """Le candidat ne contient jamais le texte brut du message — seuls des
    identifiants/entiers (message_ids) transitent, jamais tronqués/masqués
    puisqu'ils ne sont pas des `str`."""
    conn = _FakeConn()
    await review_queue.insert_review_row(
        conn, "slot-1", "conv-9", "policy_skip",
        {"value": "fait résumé", "message_ids": [11, 12, 13]},
        None, "outillage", "gotcha")
    stored = json.loads(conn.executed[0][1][3])
    assert stored["message_ids"] == [11, 12, 13]


# ============================================================================
# Queue indisponible -> best-effort, jamais de crash (BREAK)
# ============================================================================


async def test_insert_failure_is_swallowed_never_crashes_the_run():
    conn = _FakeConn(raise_on_execute=RuntimeError("relation does not exist"))
    # Ne doit lever AUCUNE exception : la review est un confort, la digestion prime.
    await review_queue.insert_review_row(
        conn, "slot-1", "conv-10", "policy_skip",
        {"value": "x"}, None, "outillage", "gotcha")


async def test_unknown_drop_reason_is_a_programming_error_not_swallowed():
    """Un `drop_reason` hors des 5 valeurs fermées est une ERREUR DE CODE
    (typo interne), pas une panne d'infra -> ValueError, pas avalé."""
    conn = _FakeConn()
    with pytest.raises(ValueError):
        await review_queue.insert_review_row(
            conn, "slot-1", "conv-11", "n_importe_quoi",
            {"value": "x"}, None, "outillage", "gotcha")
    assert not conn.executed, "aucune tentative d'INSERT sur un drop_reason invalide"


# ============================================================================
# count_atoms_for_run (lecture) + invariant PUR
# ============================================================================


async def test_count_atoms_for_run_reads_the_count():
    conn = _FakeConn(fetch_result=(7,))
    n = await review_queue.count_atoms_for_run(conn, "slot-1")
    assert n == 7
    sql, params = conn.executed[0]
    assert "memory_atoms" in sql and "run_ref" in sql
    assert params == ("slot-1",)


async def test_count_atoms_for_run_no_row_returns_zero():
    conn = _FakeConn(fetch_result=None)
    assert await review_queue.count_atoms_for_run(conn, "slot-1") == 0


def test_invariant_ok_when_counts_match():
    ok, ecart = review_queue.check_receipt_atom_invariant(
        atoms_in_db=3, atoms_created=2, atoms_superseded=1)
    assert (ok, ecart) == (True, 0)


def test_invariant_catches_api_that_lies_about_writing():
    """BREAK : une fake API atoms qui répond 201 sans RIEN écrire (comptes
    divergents) -> l'invariant CRIE (ok=False, écart signé négatif)."""
    ok, ecart = review_queue.check_receipt_atom_invariant(
        atoms_in_db=0, atoms_created=1, atoms_superseded=0)
    assert ok is False
    assert ecart == -1


def test_invariant_catches_overcount():
    ok, ecart = review_queue.check_receipt_atom_invariant(
        atoms_in_db=5, atoms_created=2, atoms_superseded=1)
    assert ok is False
    assert ecart == 2


def test_invariant_confirmed_and_kept_never_enter_the_expected_sum():
    """`atoms_confirmed`/`atoms_kept_lower_confidence`/`atoms_quarantined`
    n'écrivent AUCUNE nouvelle row -> absents (à raison) du calcul."""
    ok, ecart = review_queue.check_receipt_atom_invariant(
        atoms_in_db=1, atoms_created=1, atoms_superseded=0)
    assert (ok, ecart) == (True, 0)


# ============================================================================
# Migration de l'INSERT ad-hoc cycle._record_oversized_messages
# ============================================================================


async def test_record_oversized_messages_now_goes_through_review_queue(monkeypatch):
    calls: list[dict] = []

    async def _fake_insert(conn, run_ref, conversation_uid, drop_reason,
                           proposed_atom, incumbent_atom_id, scope, kind):
        calls.append({
            "run_ref": run_ref, "conversation_uid": conversation_uid,
            "drop_reason": drop_reason, "proposed_atom": proposed_atom,
            "incumbent_atom_id": incumbent_atom_id, "scope": scope, "kind": kind,
        })

    monkeypatch.setattr(cycle.review_queue, "insert_review_row", _fake_insert)
    monkeypatch.setattr(cycle, "_alert", lambda *_a, **_k: None)

    oversized = [{"uid": "conv-x", "message_id": 99, "chars": 400_000, "est_tokens": 100_000}]
    await cycle._record_oversized_messages(object(), oversized, slot_key="slot-42")

    assert len(calls) == 1
    call = calls[0]
    assert call["run_ref"] == "slot-42"
    assert call["conversation_uid"] == "conv-x"
    assert call["drop_reason"] == "oversized_message"
    assert call["scope"] == "_systeme" and call["kind"] == "oversized_message"
    assert call["proposed_atom"] == {"message_id": 99, "chars": 400_000, "est_tokens": 100_000}


# ============================================================================
# DB réelle (cluster jetable) — SAVEPOINT autour de l'INSERT best-effort
# (revue adversariale, constat 1/7/27)
# ============================================================================
#
# `insert_review_row` tourne sur la connexion PARTAGÉE du disposant/cycle
# (déjà dans une transaction en cours : POST d'atomes, avance de curseur...).
# Avant le fix, un INSERT échoué (ici : FK `incumbent_atom_id` invalide, un
# uuid qui n'existe pas dans `arac.memory_atoms`) laissait `conn` en
# `InFailedSqlTransaction` -> l'écriture SUIVANTE sur la MÊME connexion
# (`curator_lib_v2.mark_curation_failed`, retry_count/backoff) échouait à
# son tour, ou pire, un `commit()` naïf devenait un rollback silencieux qui
# perdait cette écriture pourtant déjà consentie. Séquence REJOUÉE ici =
# EXACTEMENT celle de `agents/cortex/dispose.py` (`insert_review_row` PUIS
# `mark_curation_failed` PUIS `commit()` sur le même `conn`).


def _agent_dsn_or_skip() -> str:
    """DSN du rôle `arac_agent` (celui du cortex en prod, cf `cycle.py` :
    « le cortex EST l'agent (receipts RW, curseur UPDATE, brut SELECT) »).

    Aucune fixture conftest dédiée à ce rôle (aucun autre test n'en avait eu
    besoin) -> dérivé de `DATABASE_URL_APP_TEST` (même cluster/DB jetable,
    seul le rôle change) ; `DATABASE_URL_AGENT_TEST` explicite prend le pas
    s'il est défini.
    """
    explicit = os.environ.get("DATABASE_URL_AGENT_TEST")
    if explicit:
        return explicit
    app_dsn = os.environ.get("DATABASE_URL_APP_TEST")
    if not app_dsn:
        pytest.skip("DB test not available (DATABASE_URL_APP_TEST absente)")
    return app_dsn.replace("arac_app", "arac_agent", 1)


async def test_insert_review_row_failure_does_not_abort_the_shared_transaction(db_admin):
    """BREAK (avant fix) / ACCEPTANCE (après fix) — cluster jetable réel.

    Séquence : `insert_review_row` avec un `incumbent_atom_id` bidon (FK
    `arac.memory_atoms` invalide) sur `conn` PUIS `mark_curation_failed` PUIS
    `commit()` sur ce MÊME `conn` (exactement l'enchaînement de
    `agents/cortex/dispose.py`). Sans SAVEPOINT autour de l'INSERT,
    `mark_curation_failed` lève `InFailedSqlTransaction` (transaction
    partagée déjà avortée par l'INSERT raté) -> ce test échoue AVANT le fix.
    Après le fix, `mark_curation_failed` + `commit()` réussissent normalement
    et le `retry_count` incrémenté est bien relu après reconnexion.
    """
    dsn = _agent_dsn_or_skip()
    conv_uid = f"test-fixA-finding1-{uuid.uuid4()}"

    async with db_admin.cursor() as cur:
        await cur.execute(
            "INSERT INTO arac.conversations (source_type, conversation_uid, node_id) "
            "VALUES ('claude_code', %s, 'claude-code-serveur') RETURNING id",
            (conv_uid,),
        )
        (conv_id,) = await cur.fetchone()

    try:
        async with await psycopg.AsyncConnection.connect(dsn) as conn:
            bogus_incumbent = str(uuid.uuid4())  # n'existe PAS dans memory_atoms -> FK violée
            # Best-effort garanti : ne lève JAMAIS, même en cas d'échec réel de l'INSERT.
            await review_queue.insert_review_row(
                conn, "test-slot-fixA", conv_uid, "atom_quarantine",
                {"scope": "outillage", "kind": "gotcha", "key": "k", "value": "v"},
                bogus_incumbent, "outillage", "gotcha",
            )

            # AVANT LE FIX : lève `InFailedSqlTransaction` ici (transaction
            # partagée avortée par l'INSERT FK-invalide ci-dessus).
            new_retry = await curator_lib_v2.mark_curation_failed(
                conn, str(conv_id), error="test_fixA_finding1")
            assert new_retry == 1

            # AVANT LE FIX : ce commit devient un rollback silencieux (rien à
            # committer, la transaction est déjà morte).
            await conn.commit()

        # Reconnexion neuve : le retry_count DOIT avoir persisté.
        async with db_admin.cursor() as cur:
            await cur.execute(
                "SELECT retry_count, last_curation_error FROM arac.conversations WHERE id = %s",
                (conv_id,),
            )
            retry_count, last_error = await cur.fetchone()
        assert retry_count == 1, (
            "retry_count PERDU : le commit du caller a été silencieusement "
            "transformé en rollback par l'INSERT best-effort non isolé"
        )
        assert last_error == "test_fixA_finding1"

        # La row de revue, elle, n'a PAS été écrite (FK violée -> rollback TO
        # SAVEPOINT de l'INSERT SEUL) — le savepoint isole l'échec, il ne le
        # cache pas : `digestion_review_queue` reste cohérente (jamais de
        # `incumbent_atom_id` pointant dans le vide).
        async with db_admin.cursor() as cur:
            await cur.execute(
                "SELECT count(*) FROM arac.digestion_review_queue WHERE conversation_uid = %s",
                (conv_uid,),
            )
            (n_review_rows,) = await cur.fetchone()
        assert n_review_rows == 0
    finally:
        async with db_admin.cursor() as cur:
            await cur.execute("DELETE FROM arac.conversations WHERE id = %s", (conv_id,))
