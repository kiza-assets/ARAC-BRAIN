"""Tests des collecteurs read-only du Control Center (V1.7B / T2).

Doctrine vérifiée : OBSERVE FIRST. DO NOT CONTROL. + READ ONLY.

Aucune DB réelle, aucun subprocess réel :
  - les connexions DB sont monkeypatchées par un faux connecteur (fake cursor) ;
  - subprocess.run est monkeypatché par un faux exécuteur scriptable ;
  - le système de fichiers est dirigé via monkeypatch des résolveurs de chemins.

Couvre : structures de retour nominales, résilience (source down → {error}/[]),
et GARANTIES STATIQUES (inspect.getsource) :
  - aucun INSERT/UPDATE/DELETE/TRUNCATE/DROP dans les 3 modules collectors ;
  - aucun verbe système mutateur hors de l'allowlist-de-refus défensive ;
  - _run_readonly refuse effectivement une commande mutatrice.
"""

from __future__ import annotations

import ast
import inspect
import io
import json
import re
import tokenize

import pytest

from control_center.collectors import db_metrics, reports_council, system_metrics


# ============================================================================
# Helper : code source SANS commentaires NI docstrings
# ============================================================================


def _executable_source(module) -> str:
    """Retourne le source d'un module privé de ses commentaires et docstrings.

    Les garanties statiques doivent porter sur le CODE EXÉCUTÉ, pas sur la prose
    explicative (qui mentionne légitimement « aucun INSERT/UPDATE/DELETE... »).
    On retire :
      - les commentaires (#...) via tokenize ;
      - les docstrings (module / classe / fonction) via analyse AST.
    """
    src = inspect.getsource(module)

    # 1) Repérer les segments de docstrings à blanchir (positions via AST).
    tree = ast.parse(src)
    doc_nodes = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                doc_nodes.append(body[0].value)

    lines = src.splitlines(keepends=True)
    # Blanchir les lignes couvertes par chaque docstring (offsets 1-based AST).
    for d in doc_nodes:
        for ln in range(d.lineno, (d.end_lineno or d.lineno) + 1):
            lines[ln - 1] = "\n"
    no_doc = "".join(lines)

    # 2) Retirer les commentaires via tokenize.
    out_tokens = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(no_doc).readline):
            if tok.type == tokenize.COMMENT:
                continue
            out_tokens.append(tok)
        return tokenize.untokenize(out_tokens)
    except tokenize.TokenError:
        # Fallback conservateur : retire au moins les commentaires ligne à ligne.
        return "\n".join(
            line.split("#", 1)[0] for line in no_doc.splitlines()
        )


# ============================================================================
# Faux objets DB (context managers compatibles psycopg)
# ============================================================================


class _FakeCursor:
    """Curseur factice : répond aux execute() selon un script ``responses``.

    ``responses`` est une liste de valeurs renvoyées tour à tour :
      - une list[tuple] → consommée par fetchall()
      - un tuple        → consommé par fetchone()
    L'ordre des execute() suit l'ordre d'implémentation des collecteurs.
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self._current = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._current = self._responses.pop(0) if self._responses else None

    def fetchall(self):
        return self._current or []

    def fetchone(self):
        return self._current


class _FakeConn:
    """Connexion factice : fabrique un _FakeCursor, trace close()."""

    def __init__(self, responses):
        self._responses = responses
        self.closed = False

    def cursor(self):
        return _FakeCursor(self._responses)

    def close(self):
        self.closed = True


def _patch_conn(monkeypatch, responses):
    """Monkeypatch _connect_readonly pour renvoyer un _FakeConn scripté."""
    conn = _FakeConn(responses)
    monkeypatch.setattr(db_metrics, "_connect_readonly", lambda: conn)
    return conn


def _patch_conn_down(monkeypatch):
    """Monkeypatch _connect_readonly pour simuler une DB injoignable."""

    def _boom():
        raise OSError("connection refused (simulated)")

    monkeypatch.setattr(db_metrics, "_connect_readonly", _boom)


# ============================================================================
# db_metrics — nominal
# ============================================================================


def test_memory_atoms_summary_nominal(monkeypatch):
    # ordre execute : by_kind(GROUP), by_scope(GROUP), by_status(GROUP), total
    _patch_conn(
        monkeypatch,
        [
            [("decision", 3), ("idea", 2)],          # by_kind
            [("outillage", 4), ("outillage/infrastructure", 1)],         # by_scope
            [("active", 4), ("archived", 1)],         # by_status
            (5,),                                      # total
        ],
    )
    out = db_metrics.memory_atoms_summary()
    assert out["total"] == 5
    assert out["by_kind"] == {"decision": 3, "idea": 2}
    assert out["by_scope"] == {"outillage": 4, "outillage/infrastructure": 1}
    assert out["by_status"] == {"active": 4, "archived": 1}
    assert "error" not in out


def test_raw_conversations_count_nominal(monkeypatch):
    _patch_conn(monkeypatch, [(230,)])
    assert db_metrics.raw_conversations_count() == 230


def test_ipq_summary_nominal(monkeypatch):
    _patch_conn(monkeypatch, [[("approved", 1), ("rejected", 4)]])
    out = db_metrics.ipq_summary()
    assert out["by_status"] == {"approved": 1, "rejected": 4}
    assert out["total"] == 5
    assert "error" not in out


def test_mrq_summary_nominal(monkeypatch):
    _patch_conn(monkeypatch, [[("reviewed", 11), ("pending_human_review", 2)]])
    out = db_metrics.mrq_summary()
    assert out["by_status"] == {"reviewed": 11, "pending_human_review": 2}
    assert out["total"] == 13
    assert "error" not in out


def test_db_connection_closed_after_use(monkeypatch):
    conn = _patch_conn(monkeypatch, [(0,)])
    db_metrics.raw_conversations_count()
    assert conn.closed is True


# ============================================================================
# db_metrics — résilience (DB down → {error})
# ============================================================================


def test_memory_atoms_summary_db_down(monkeypatch):
    _patch_conn_down(monkeypatch)
    out = db_metrics.memory_atoms_summary()
    assert out["error"] == "unavailable"
    assert out["total"] == 0
    assert out["by_kind"] == {} and out["by_scope"] == {} and out["by_status"] == {}


def test_raw_conversations_count_db_down(monkeypatch):
    _patch_conn_down(monkeypatch)
    out = db_metrics.raw_conversations_count()
    assert isinstance(out, dict) and out["error"] == "unavailable"


def test_ipq_summary_db_down(monkeypatch):
    _patch_conn_down(monkeypatch)
    out = db_metrics.ipq_summary()
    assert out["error"] == "unavailable" and out["total"] == 0 and out["by_status"] == {}


def test_mrq_summary_db_down(monkeypatch):
    _patch_conn_down(monkeypatch)
    out = db_metrics.mrq_summary()
    assert out["error"] == "unavailable" and out["total"] == 0 and out["by_status"] == {}


# ============================================================================
# system_metrics — allowlist _run_readonly (cœur sécurité)
# ============================================================================


def test_run_readonly_refuses_mutating_systemctl():
    # Exigence T2 explicite : systemctl restart doit être REFUSÉ.
    out = system_metrics._run_readonly(["systemctl", "restart", "arac-api"])
    assert out["ok"] is False
    assert "not_allowed" in out["error"]


@pytest.mark.parametrize(
    "cmd",
    [
        ["systemctl", "start", "x"],
        ["systemctl", "stop", "x"],
        ["systemctl", "restart", "x"],
        ["systemctl", "enable", "x"],
        ["systemctl", "disable", "x"],
        ["systemctl", "reload", "x"],
        ["systemctl", "mask", "x"],
        ["kill", "-9", "1234"],          # binaire hors allowlist
        ["rm", "-rf", "/"],              # binaire hors allowlist
        ["bash", "-c", "echo pwned"],    # binaire hors allowlist
        ["git", "push", "origin", "main"],   # git allowlist positive → refusé
        ["git", "commit", "-m", "x"],        # idem
        ["git", "reset", "--hard"],          # idem
        ["df", "kill"],                  # verbe mutateur en argument
        [],                              # commande vide
        ["systemctl"],                   # systemctl sans sous-commande
    ],
)
def test_run_readonly_refuses_disallowed(cmd):
    out = system_metrics._run_readonly(cmd)
    assert out["ok"] is False, f"devrait refuser : {cmd}"


def test_assert_readonly_raises_on_mutating():
    with pytest.raises(system_metrics.CommandNotAllowed):
        system_metrics._assert_readonly(["systemctl", "restart", "arac-api"])
    with pytest.raises(system_metrics.CommandNotAllowed):
        system_metrics._assert_readonly(["reboot"])


@pytest.mark.parametrize(
    "cmd",
    [
        ["git", "rev-parse", "HEAD"],
        ["git", "log", "-n", "5", "--oneline"],
        ["df", "-h", "/opt"],
        ["ss", "-ltn"],
        ["tmux", "ls"],
        ["systemctl", "is-active", "arac-api"],
        ["systemctl", "is-enabled", "arac-api"],
        ["systemctl", "is-failed", "arac-api"],
        ["systemctl", "list-units"],
        ["systemctl", "list-timers"],
    ],
)
def test_assert_readonly_accepts_allowed(cmd):
    # Ne doit PAS lever : ce sont des commandes de lecture légitimes.
    system_metrics._assert_readonly(cmd)


# ============================================================================
# Red-team V1.7B — sous-commandes RETIRÉES des allowlists (doivent être REFUSÉES)
# ============================================================================


@pytest.mark.parametrize(
    "cmd",
    [
        # systemctl show/cat retirés (exposent variables d'env et fichiers unit)
        ["systemctl", "show", "arac-api"],
        ["systemctl", "cat", "arac-api"],
        # git show/branch/status retirés (show expose contenu de fichiers repo)
        ["git", "show", "HEAD:secrets.txt"],
        ["git", "branch", "--all"],
        ["git", "status"],
    ],
)
def test_run_readonly_refuses_removed_subcommands(cmd):
    """Les sous-commandes retirées lors du durcissement V1.7B sont REFUSÉES.

    Garantit que le resserrement des allowlists systemctl et git (red-team MEDIUM)
    est effectivement appliqué : ces sous-commandes ne sont plus autorisées.
    """
    out = system_metrics._run_readonly(cmd)
    assert out["ok"] is False, f"devrait refuser après durcissement V1.7B : {cmd}"
    assert "not_allowed" in out["error"], f"motif de refus inattendu : {out}"


# ============================================================================
# system_metrics — collecteurs avec subprocess mocké
# ============================================================================


class _FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _fake_subprocess(monkeypatch, router):
    """Monkeypatch subprocess.run dans system_metrics via une fonction router.

    ``router(cmd_list) -> _FakeCompleted``. Aucun process réel n'est lancé.
    """

    def _run(cmd_list, capture_output, text, timeout, check):  # noqa: ARG001
        return router(cmd_list)

    monkeypatch.setattr(system_metrics.subprocess, "run", _run)


def test_git_version_nominal(monkeypatch):
    def router(cmd):
        if cmd[:2] == ["git", "rev-parse"] and "--abbrev-ref" in cmd:
            return _FakeCompleted(stdout="main")
        if cmd[:2] == ["git", "rev-parse"]:
            return _FakeCompleted(stdout="abc123def456")
        if cmd[:2] == ["git", "describe"]:
            return _FakeCompleted(stdout="v1.0.0-48-gabc123")
        if cmd[:2] == ["git", "log"]:
            return _FakeCompleted(stdout="abc123 commit one\ndef456 commit two")
        return _FakeCompleted(returncode=1)

    _fake_subprocess(monkeypatch, router)
    out = system_metrics.git_version()
    assert out["branch"] == "main"
    assert out["head_commit"] == "abc123def456"
    assert out["describe"] == "v1.0.0-48-gabc123"
    assert out["last_commits"] == ["abc123 commit one", "def456 commit two"]


def test_git_version_degraded(monkeypatch):
    # Git introuvable → FileNotFoundError → tous champs dégradés, pas d'exception.
    def router(cmd):
        raise FileNotFoundError("git not found")

    _fake_subprocess(monkeypatch, router)
    out = system_metrics.git_version()
    assert out["branch"] is None
    assert out["head_commit"] is None
    assert out["describe"] is None
    assert out["last_commits"] == []


def test_server_health_nominal(monkeypatch, tmp_path):
    # /proc/loadavg lu via open() — on patche builtins.open pour ce chemin.
    fake_loadavg = tmp_path / "loadavg"
    fake_loadavg.write_text("0.10 0.20 0.30 1/100 12345\n")
    real_open = open

    def fake_open(path, *a, **k):
        if path == "/proc/loadavg":
            return real_open(fake_loadavg, *a, **k)
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", fake_open)

    def router(cmd):
        if cmd[0] == "df":
            return _FakeCompleted(stdout="Filesystem Size Used\n/dev/sda 50G 20G")
        if cmd[0] == "systemctl":
            return _FakeCompleted(stdout="active")
        return _FakeCompleted(returncode=1)

    # De quel cerveau ce cockpit est-il le cockpit ? L'unité le pose ; sans
    # cette variable, server_health rend « unknown » plutôt que l'état d'une
    # unité qui appartient à quelqu'un d'autre.
    monkeypatch.setenv("ARAC_UNIT_API", "arac-zoe_brain-api")
    _fake_subprocess(monkeypatch, router)
    out = system_metrics.server_health()
    assert out["loadavg"] == {"1m": 0.10, "5m": 0.20, "15m": 0.30}
    assert "Filesystem" in out["disk"]
    assert out["arac_api_status"] == "active"


def test_server_health_sans_unite_declaree_ne_regarde_pas_le_voisin(monkeypatch):
    """Sans ARAC_UNIT_API : « unknown », jamais l'état de l'unité d'à côté.

    Cette fonction demandait l'état de « arac-api », écrit en dur. Sur cette
    machine, deux cockpits d'ESSAI rapportaient ainsi la santé de l'unité de
    PRODUCTION : des tuiles vertes qui ne parlaient pas du cerveau qu'on
    regardait. Un diagnostic qui ment en disant « tout va bien » est pire
    qu'une absence de diagnostic.
    """
    monkeypatch.delenv("ARAC_UNIT_API", raising=False)
    vues = []

    def router(cmd):
        vues.append(cmd)
        return _FakeCompleted(stdout="active")

    _fake_subprocess(monkeypatch, router)
    out = system_metrics.server_health()
    assert out["arac_api_status"] == "unknown"
    assert not [c for c in vues if c and c[0] == "systemctl"], (
        "sans unité déclarée, server_health ne doit interroger AUCUNE unité"
    )


def test_server_health_api_status_read_only_never_mutates(monkeypatch):
    # Garantit que server_health appelle systemctl is-active (lecture), capté
    # par l'allowlist : on enregistre les commandes vues.
    seen = []

    def router(cmd):
        seen.append(cmd)
        if cmd[0] == "systemctl":
            return _FakeCompleted(stdout="inactive")
        return _FakeCompleted(stdout="")

    monkeypatch.setenv("ARAC_UNIT_API", "arac-zoe_brain-api")
    _fake_subprocess(monkeypatch, router)
    system_metrics.server_health()
    systemctl_calls = [c for c in seen if c and c[0] == "systemctl"]
    assert systemctl_calls, "server_health doit interroger systemctl"
    for c in systemctl_calls:
        # Après durcissement V1.7B : 'show' retiré de l'allowlist.
        # server_health n'utilise que is-active (lecture d'état).
        assert c[1] in {"is-active", "is-enabled", "is-failed"} or c[1].startswith("list-")


def test_tmux_sessions_present_and_absent(monkeypatch):
    def router_present(cmd):
        return _FakeCompleted(stdout="arac: 1 windows\nv2: 2 windows")

    _fake_subprocess(monkeypatch, router_present)
    assert system_metrics.tmux_sessions() == ["arac: 1 windows", "v2: 2 windows"]

    def router_absent(cmd):
        raise FileNotFoundError("no tmux")

    _fake_subprocess(monkeypatch, router_absent)
    assert system_metrics.tmux_sessions() == []


def test_ssh_tunnel_status(monkeypatch):
    def router_up(cmd):
        return _FakeCompleted(
            stdout="State Recv-Q Send-Q Local\nLISTEN 0 128 127.0.0.1:2223"
        )

    _fake_subprocess(monkeypatch, router_up)
    out = system_metrics.ssh_tunnel_status()
    assert out["listener_2223"] is True
    assert isinstance(out["note"], str)

    def router_down(cmd):
        return _FakeCompleted(stdout="State Recv-Q Send-Q Local\nLISTEN 0 128 *:443")

    _fake_subprocess(monkeypatch, router_down)
    out = system_metrics.ssh_tunnel_status()
    assert out["listener_2223"] is False


# ============================================================================
# reports_council — fichiers repo mockés
# ============================================================================


def test_recent_reports_nominal(monkeypatch, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "A.md").write_text("# secret content should not be read")
    (docs / "B.md").write_text("# another")
    # mtime distincts pour un tri déterministe
    import os

    os.utime(docs / "A.md", (1000, 1000))
    os.utime(docs / "B.md", (2000, 2000))

    monkeypatch.setattr(reports_council, "_docs_dir", lambda: docs)
    out = reports_council.recent_reports(10)
    names = [r["name"] for r in out]
    assert names == ["B.md", "A.md"]  # plus récent d'abord
    # contenu jamais exposé : seulement name + modified
    assert set(out[0].keys()) == {"name", "modified"}


def test_recent_reports_missing_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(reports_council, "_docs_dir", lambda: tmp_path / "nope")
    assert reports_council.recent_reports() == []


def test_decisions_index_nominal(monkeypatch, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "DECISIONS.md").write_text(
        "# DECISIONS\n\n"
        "### D-101 — Première décision\n\nblabla\n\n"
        "### D-102 — Deuxième décision\n\n"
        "Une référence inline à D-101 ne doit PAS recompter.\n\n"
        "### D-145 — Dernière décision\n"
    )
    monkeypatch.setattr(reports_council, "_docs_dir", lambda: docs)
    out = reports_council.decisions_index()
    assert out["count"] == 3
    assert out["last_number"] == 145
    ids = [d["id"] for d in out["decisions"]]
    assert ids == ["D-101", "D-102", "D-145"]
    assert out["decisions"][0]["title"] == "Première décision"


def test_decisions_index_missing(monkeypatch, tmp_path):
    """Registre absent : la forme est identique, ET l'absence est DÉCLARÉE.

    POURQUOI ce test exige plus que des listes vides : `docs/DECISIONS.md`
    n'est engendré par aucun code de ce dépôt. Chez un cerveau neuf, la page
    « Décisions » est vide pour de bon. Un tableau vide muet se lit comme une
    panne du cockpit ; l'état déclaré (`state`/`reason`/`gesture`) est donc la
    partie utile de la réponse, pas un ornement — et il doit NOMMER le fichier
    attendu, sinon le lecteur ne peut pas le créer.
    """
    monkeypatch.setattr(reports_council, "_docs_dir", lambda: tmp_path / "nope")
    out = reports_council.decisions_index()
    assert out["decisions"] == []
    assert out["last_number"] is None
    assert out["count"] == 0
    assert out["state"] == "absent"
    assert out["path"] == "docs/DECISIONS.md"
    assert "DECISIONS.md" in (out["reason"] or "")
    assert "DECISIONS.md" in (out["gesture"] or "")


def test_council_recent_verdicts_nominal(monkeypatch, tmp_path):
    base = tmp_path / "council"
    base.mkdir()
    sess = {
        "session_id": "CS-abc",
        "candidate": {"candidate_id": "C-001", "body_redacted": "NE PAS LIRE"},
        "reviews": ["transcript secret — ne doit pas apparaître"],
        "president_decision": {
            "final_decision": "REJECT",
            "rationale_redacted": "raison — ne doit pas apparaître",
        },
        "receipt": {
            "session_id": "CS-abc",
            "candidate_id": "C-001",
            "final_decision": "REJECT",
            "created_at": "2026-06-13T15:08:26+00:00",
        },
    }
    (base / "session_CS-abc.json").write_text(json.dumps(sess))
    sess2 = dict(sess)
    sess2_receipt = dict(sess["receipt"])
    sess2_receipt["session_id"] = "CS-def"
    sess2_receipt["created_at"] = "2026-06-10T10:00:00+00:00"
    sess2["receipt"] = sess2_receipt
    sess2["session_id"] = "CS-def"
    (base / "session_CS-def.json").write_text(json.dumps(sess2))

    monkeypatch.setattr(reports_council, "_council_sessions_dir", lambda: base)
    out = reports_council.council_recent_verdicts(5)
    assert len(out) == 2
    # tri created_at desc → CS-abc d'abord
    assert out[0]["session_id"] == "CS-abc"
    # metadata only : exactement 4 clés, aucune fuite de transcript/rationale
    for item in out:
        assert set(item.keys()) == {
            "session_id",
            "candidate_id",
            "final_decision",
            "created_at",
        }
        blob = json.dumps(item)
        assert "transcript" not in blob and "NE PAS LIRE" not in blob
        assert "rationale" not in blob


def test_council_recent_verdicts_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(
        reports_council, "_council_sessions_dir", lambda: tmp_path / "nope"
    )
    assert reports_council.council_recent_verdicts() == []


def _timeline_git_router(branches_stdout: str):
    """Faux `git` : des tags toujours, des branches selon le motif interrogé."""

    def router(cmd):
        if cmd[:2] == ["git", "tag"]:
            return _FakeCompleted(stdout="v1.0.0\nv0.7.0")
        if cmd[:2] == ["git", "for-each-ref"]:
            return _FakeCompleted(stdout=branches_stdout)
        return _FakeCompleted(returncode=1)

    return router


def test_timeline_versions_sans_convention_declaree(monkeypatch):
    """Aucune convention posée : les tags remontent, les branches DISENT pourquoi non.

    POURQUOI ce cas est le cas nominal : les tags sont universels — tout dépôt
    Git en a ou n'en a pas. Une convention de nommage de branches, elle,
    appartient à celui qui l'a choisie. Le cockpit n'en suppose aucune ; sans
    déclaration il rend une liste vide ACCOMPAGNÉE de sa raison, plutôt qu'un
    panneau muet qui aurait appris au lecteur la convention d'un autre dépôt.
    """
    monkeypatch.delenv(reports_council.RELEASE_BRANCH_GLOB_ENV, raising=False)
    monkeypatch.setattr(
        system_metrics.subprocess,
        "run",
        lambda cmd, **k: _timeline_git_router("release/1.0\nrelease/1.1")(cmd),
    )
    out = reports_council.timeline_versions()
    assert out["tags"] == ["v1.0.0", "v0.7.0"]
    assert out["release_branches"] == []
    assert out["branch_glob"] is None
    assert reports_council.RELEASE_BRANCH_GLOB_ENV in (out["branch_reason"] or "")


def test_timeline_versions_avec_convention_declaree(monkeypatch):
    """Motif déclaré : le cockpit suit CE motif, et le rend pour qu'on le vérifie."""
    monkeypatch.setenv(
        reports_council.RELEASE_BRANCH_GLOB_ENV, "refs/heads/release/*"
    )
    vus: list[list[str]] = []

    def run(cmd, **k):
        vus.append(list(cmd))
        return _timeline_git_router("release/1.0\nrelease/1.1")(cmd)

    monkeypatch.setattr(system_metrics.subprocess, "run", run)
    out = reports_council.timeline_versions()
    assert out["tags"] == ["v1.0.0", "v0.7.0"]
    assert out["release_branches"] == ["release/1.0", "release/1.1"]
    assert out["branch_glob"] == "refs/heads/release/*"
    assert out["branch_reason"] is None
    # Le motif déclaré est bien celui passé à git : pas de motif gravé ailleurs.
    assert any("refs/heads/release/*" in c for c in vus)


# ============================================================================
# GARANTIES STATIQUES (inspect.getsource) — invariants doctrine READ-ONLY
# ============================================================================

_DML_PATTERN = re.compile(
    r"\b(INSERT\s+INTO|UPDATE\s+\w|DELETE\s+FROM|TRUNCATE|DROP\s+(TABLE|SCHEMA|DATABASE))\b",
    re.IGNORECASE,
)


@pytest.mark.parametrize("mod", [db_metrics, system_metrics, reports_council])
def test_no_dml_in_collector_sources(mod):
    """Aucun INSERT/UPDATE/DELETE/TRUNCATE/DROP dans le CODE des collecteurs.

    Scan effectué sur le source privé de docstrings/commentaires (la prose
    documente légitimement ces invariants en toutes lettres).
    """
    src = _executable_source(mod)
    matches = _DML_PATTERN.findall(src)
    assert not matches, f"DML interdit détecté dans {mod.__name__}: {matches}"


def test_db_metrics_only_selects():
    """db_metrics ne contient que des requêtes SELECT (lecture pure)."""
    src = _executable_source(db_metrics).upper()
    # Toute exécution SQL doit être un SELECT. On vérifie qu'aucun mot-clé
    # d'écriture SQL n'apparaît dans le CODE du module.
    for forbidden in ("INSERT", "UPDATE ", "DELETE", "TRUNCATE", "DROP ", "ALTER ", "CREATE "):
        assert forbidden not in src, f"mot-clé d'écriture interdit: {forbidden!r}"
    assert "SELECT" in src  # le module fait bien des lectures


def test_system_metrics_no_mutating_verb_outside_guard():
    """Aucun verbe système mutateur utilisé comme commande dans system_metrics.

    Les verbes mutateurs n'ont le droit d'apparaître QUE dans la définition de
    l'allowlist-de-refus (_MUTATING_VERBS / _SYSTEMCTL_READ_SUBCOMMANDS) — jamais
    dans une liste passée à subprocess. On vérifie qu'aucune commande littérale
    construite dans le module ne contient un verbe mutateur.
    """
    src = inspect.getsource(system_metrics)
    # Repère les listes littérales passées à _run_readonly([...]) et vérifie
    # qu'aucune ne contient un verbe mutateur.
    calls = re.findall(r"_run_readonly\(\s*\[([^\]]*)\]", src)
    mutating = {"start", "stop", "restart", "enable", "disable", "kill", "reload", "rm"}
    for call in calls:
        tokens = re.findall(r'"([^"]*)"|\'([^\']*)\'', call)
        flat = {a or b for a, b in tokens}
        leaked = flat & mutating
        assert not leaked, f"verbe mutateur dans un appel _run_readonly: {leaked}"


def test_reports_council_no_subprocess_mutation():
    """reports_council ne construit aucune commande système mutatrice."""
    src = inspect.getsource(reports_council)
    calls = re.findall(r"_run_readonly\(\s*\[([^\]]*)\]", src)
    mutating = {"start", "stop", "restart", "enable", "disable", "kill", "reload", "rm"}
    for call in calls:
        tokens = re.findall(r'"([^"]*)"|\'([^\']*)\'', call)
        flat = {a or b for a, b in tokens}
        assert not (flat & mutating), f"commande mutatrice: {flat & mutating}"


def test_allowlist_contents():
    """L'allowlist binaires est bien restreinte aux 5 binaires read-only attendus."""
    assert system_metrics._ALLOWED_BINARIES == frozenset(
        {"git", "df", "ss", "tmux", "systemctl"}
    )


# ============================================================================
# cockpit_tunnel_status — V1.7E (lecture /proc/net/tcp, sans subprocess)
# ============================================================================


def _fake_proc_content_with_listen(port_hex: str = "46B4") -> str:
    """Retourne un contenu /proc/net/tcp factice avec un LISTEN sur port_hex."""
    # Format réel : sl local_address rem_address st tx_queue rx_queue ...
    # L'IP loopback 127.0.0.1 en little-endian hex = 0100007F
    return (
        "  sl  local_address rem_address   st tx_queue rx_queue "
        "tr tm->when retrnsmt   uid  timeout inode\n"
        f"   0: 0100007F:{port_hex} 00000000:0000 0A 00000000:00000000 "
        "00:00000000 00000000     0        0 12345 1 0000000000000000 100 0 0 10 0\n"
    )


def _fake_proc_content_without_listen() -> str:
    """Retourne un contenu /proc/net/tcp factice SANS LISTEN sur 46B4."""
    return (
        "  sl  local_address rem_address   st tx_queue rx_queue "
        "tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 0100007F:0035 00000000:0000 0A 00000000:00000000 "
        "00:00000000 00000000   101        0 99999 1 0000000000000000 100 0 0 10 0\n"
    )


def test_cockpit_tunnel_status_up(tmp_path):
    """cockpit_tunnel_status → 'up' si un LISTEN sur le port 46B4 est présent."""
    tcp_file = tmp_path / "tcp"
    tcp_file.write_text(_fake_proc_content_with_listen("46B4"), encoding="ascii")
    result = system_metrics.cockpit_tunnel_status(_proc_paths=(str(tcp_file),))
    assert result == "up", (
        f"Attendu 'up' avec LISTEN sur 46B4, obtenu : {result!r}"
    )


def test_cockpit_tunnel_status_down_wrong_port(tmp_path):
    """cockpit_tunnel_status → 'down' si aucun LISTEN sur 46B4 (autre port en LISTEN)."""
    tcp_file = tmp_path / "tcp"
    tcp_file.write_text(_fake_proc_content_without_listen(), encoding="ascii")
    result = system_metrics.cockpit_tunnel_status(_proc_paths=(str(tcp_file),))
    assert result == "down", (
        f"Attendu 'down' sans LISTEN sur 46B4, obtenu : {result!r}"
    )


def test_cockpit_tunnel_status_down_no_files(tmp_path):
    """cockpit_tunnel_status → 'down' si les fichiers proc n'existent pas."""
    result = system_metrics.cockpit_tunnel_status(
        _proc_paths=(str(tmp_path / "nope_tcp"), str(tmp_path / "nope_tcp6"))
    )
    assert result == "down", (
        f"Attendu 'down' si fichiers proc absents, obtenu : {result!r}"
    )


def test_cockpit_tunnel_status_unknown_on_unreadable(tmp_path, monkeypatch):
    """cockpit_tunnel_status → 'unknown' si open() lève une exception inattendue."""
    # On simule un échec total (pas seulement OSError) en patchant open
    real_open = open

    def bad_open(path, *a, **k):
        raise RuntimeError("simulated unreadable proc")

    monkeypatch.setattr("builtins.open", bad_open)
    # On passe un chemin existant pour déclencher open() (pas un OSError)
    # mais bad_open lève RuntimeError → doit tomber dans le except Exception → "unknown"
    result = system_metrics.cockpit_tunnel_status(_proc_paths=("/proc/net/tcp",))
    assert result == "unknown", (
        f"Attendu 'unknown' sur exception inattendue, obtenu : {result!r}"
    )


def test_cockpit_tunnel_status_up_tcp6(tmp_path):
    """cockpit_tunnel_status → 'up' si le LISTEN sur 46B4 est dans tcp6 (pas tcp)."""
    tcp_file = tmp_path / "tcp"
    tcp6_file = tmp_path / "tcp6"
    # tcp sans le port 46B4
    tcp_file.write_text(_fake_proc_content_without_listen(), encoding="ascii")
    # tcp6 avec le port 46B4 — IPv6 loopback ::1 en little-endian = "00000000000000000000000001000000"
    tcp6_content = (
        "  sl  local_address                         remote_address"
        "                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        f"   0: 00000000000000000000000001000000:46B4 00000000000000000000000000000000:0000"
        " 0A 00000000:00000000 00:00000000 00000000     0        0 23456 1 0000000000000000 100 0 0 10 0\n"
    )
    tcp6_file.write_text(tcp6_content, encoding="ascii")
    result = system_metrics.cockpit_tunnel_status(
        _proc_paths=(str(tcp_file), str(tcp6_file))
    )
    assert result == "up", (
        f"Attendu 'up' avec LISTEN sur 46B4 dans tcp6, obtenu : {result!r}"
    )


def test_cockpit_tunnel_status_port_hex_constant():
    """Port 18100 doit correspondre à la constante '46B4' (majuscule)."""
    assert system_metrics._COCKPIT_TUNNEL_PORT_HEX == "46B4", (
        "La constante port hex doit être '46B4' (18100 en hex majuscule)"
    )
    assert int("46B4", 16) == 18100, "46B4 hex doit valoir 18100 décimal"


def test_cockpit_tunnel_status_no_subprocess():
    """cockpit_tunnel_status ne doit utiliser aucun subprocess (lecture /proc pure).

    Garantie statique : le source de cockpit_tunnel_status ne contient aucun
    appel à subprocess, _run_readonly, ou os.popen.
    """
    import ast as _ast
    import inspect as _inspect
    src = _inspect.getsource(system_metrics.cockpit_tunnel_status)
    tree = _ast.parse(src)
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            func = node.func
            # Cherche des appels à subprocess.*, _run_readonly, os.popen
            if isinstance(func, _ast.Attribute):
                if func.attr in ("run", "Popen", "call", "check_output", "popen"):
                    raise AssertionError(
                        f"cockpit_tunnel_status ne doit pas appeler subprocess.{func.attr}"
                    )
            elif isinstance(func, _ast.Name):
                if func.id in ("_run_readonly", "popen"):
                    raise AssertionError(
                        f"cockpit_tunnel_status ne doit pas appeler {func.id}()"
                    )
