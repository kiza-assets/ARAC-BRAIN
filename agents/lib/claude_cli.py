"""Wrapper subprocess autour de `claude` CLI headless — Phase D.1 MVP + D.4 Bloc 9a.

Le developer agent (agents/developer/main.py) appelle `run_claude_subprocess()`
pour exécuter une mission dans le dépôt de l'installation (`ARAC_HOME`).

Garde-fous — chacun ferme une façon précise de perdre du travail ou des
données, et aucun n'est décoratif :
- Timeout dur (DEFAULT_TIMEOUT_SEC). Au-delà : kill processus + retour ok=False.
- --allowedTools whitelist explicite : Read/Edit/Write/Glob/Grep + commandes
  Bash git limitées (add, commit, status, diff, log, branch, checkout) +
  push *uniquement* sur `feature/*` (regex). Pas de reset, pas de force, pas
  de rm, pas de sudo, pas de network.
- --add-dir $ARAC_HOME : sandbox au dépôt de l'installation. L'agent ne voit
  rien d'autre du disque.
- --permission-mode acceptEdits : pas de prompt interactif sur Edit/Write.
  Les Bash hors whitelist sont refusés silencieusement.
- --output-format json : sortie structurée parsable par le caller.
- Pas de --dangerously-skip-permissions (le whitelist suffit, plus safe).

Phase D.4 Bloc 9a (capture intégrale) :
- Streaming chunk-par-chunk de stdout/stderr (4 KB) via `asyncio.gather`.
- Param `mission_logger: MissionLogger | None` propage chaque chunk dans le
  transcript JSONL si fourni.
- Suppression des troncatures `[:10_000]` sur le retour. Conservation d'un
  résumé court (`stdout_summary` / `stderr_summary` 500 chars) pour les atomes
  delivery legacy, tandis que `stdout` / `stderr` deviennent les buffers full.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any

import arac_runtime
from app.journal import raison  # noqa: E402

if TYPE_CHECKING:
    from agents.lib.log_capture import MissionLogger

logger = logging.getLogger("arac.claude_cli")

# ---------------------------------------------------------------------------
# LE VRAI PRÉREQUIS DE LA CURATION — ET IL N'EST PAS UNE CLÉ D'API.
#
# Ce module ne parle À AUCUNE API. Il lance un BINAIRE : le Claude Code CLI,
# en sous-processus, sous le compte d'agent du cerveau. Ce que la curation
# exige, c'est donc :
#   · le binaire `claude` présent sur LE SERVEUR (npm i -g @anthropic-ai/claude-code) ;
#   · une AUTHENTIFICATION lisible par le compte d'agent — soit une session
#     ouverte (abonnement Claude : `claude auth status` → authMethod claude.ai),
#     soit `ANTHROPIC_API_KEY` dans l'environnement du service (facturation à
#     l'appel). Le binaire lit l'une ou l'autre ; ARAC, lui, ne lit ni ne
#     transmet jamais cette clé : elle voyage par l'environnement hérité.
#
# LE CHEMIN ÉTAIT FIGÉ, ET C'EST CE QUI CASSAIT. `/usr/bin/claude` en dur
# suppose une installation npm globale sous préfixe /usr. Posé par nvm, par
# `npm -g` sous préfixe utilisateur, ou dans /usr/local/bin, le binaire existe
# et le spawn lève quand même FileNotFoundError — que le retry ci-dessous
# interprète comme « swap npm transitoire », d'où quatre tentatives, puis
# `spawn_failed`, curseurs intouchés, aucun atome, À CHAQUE CYCLE,
# indéfiniment : le cerveau ingère et n'apprend jamais.
#
# On résout donc à l'exécution, dans cet ordre : `ARAC_CLAUDE_BIN` (le chemin
# que VOUS nommez), puis le PATH du service, puis `/usr/bin/claude` en dernier
# recours — pour que le comportement historique reste celui d'une machine où
# le binaire est bien là.
# ---------------------------------------------------------------------------
CLAUDE_BIN = "/usr/bin/claude"          # dernier recours, et rien d'autre
CLAUDE_BIN_ENV = "ARAC_CLAUDE_BIN"      # la variable qui le déplace


def resolve_claude_bin() -> str:
    """Le chemin du binaire de curation, résolu MAINTENANT (jamais à l'import).

    À l'import, l'environnement du service n'est pas encore celui du run en
    test, et un chemin figé au chargement ne se laisse plus corriger.
    """
    import shutil

    explicite = os.environ.get(CLAUDE_BIN_ENV, "").strip()
    if explicite:
        return explicite
    trouve = shutil.which("claude")
    if trouve:
        return trouve
    return CLAUDE_BIN


def curation_disponible() -> tuple[bool, str, str]:
    """(disponible, chemin_résolu, ce_qu_il_faut_faire) — sans rien dépenser.

    Ne teste QUE la présence et l'exécutabilité du binaire : l'état
    d'authentification se lit par `claude auth status --json`, que le contrôle
    d'installation joue sous le HOME du compte d'agent (bootstrap/checks/
    verify_install.sh). Ici, on répond à la seule question qui décide si un
    cycle peut spawner.
    """
    chemin = resolve_claude_bin()
    if os.path.isfile(chemin) and os.access(chemin, os.X_OK):
        return True, chemin, ""
    return False, chemin, (
        f"Le binaire de curation est introuvable ou non exécutable : {chemin}. "
        "La curation ne passe par AUCUNE API : elle lance le Claude Code CLI "
        "sur ce serveur. Le geste : sudo npm install -g @anthropic-ai/claude-code "
        f"(puis, si le binaire n'atterrit pas dans le PATH du service, posez "
        f"{CLAUDE_BIN_ENV}=<chemin absolu> dans le fichier d'environnement du "
        "cerveau). Vérifier : sudo ./bootstrap/bootstrap.sh --check"
    )
DEFAULT_TIMEOUT_SEC = 600  # 10 min
DEFAULT_CWD = str(arac_runtime.home())
DEFAULT_MODEL = "claude-opus-4-8"  # Override possible via param model=.

# Taille des chunks streamés stdout/stderr. 4 KB = compromis latence/overhead
# (assez gros pour ne pas multiplier les réveils, assez petit pour que la
# capture reste bornée en mémoire sur une sortie longue).
_CHUNK_SIZE = 4096
# Taille des résumés courts conservés dans le dict de retour (pour atomes
# delivery legacy). Le full vit dans le transcript JSONL.
_SUMMARY_CHARS = 500

# v0.6 — retry sur spawn raté TRANSITOIRE. Un Claude Code tournant en
# ROOT sur le même serveur (la session opérateur elle-même) auto-update le
# binaire global partagé /usr/bin/claude. L'install est root:root : les agents
# `aracagent` ne PEUVENT PAS l'empêcher. Pendant le swap npm (~1-6 s), le symlink
# /usr/bin/claude pointe dans le vide → create_subprocess_exec lève
# FileNotFoundError (Errno 2). Observé le 2026-05-23 : 5 segments curator perdus
# en silence (2 updates dans la fenêtre 12:20 / 14:25). On retente UNIQUEMENT
# FileNotFoundError (binaire absent = transitoire ; AUCUN subprocess démarré donc
# AUCUN atome créé → retry strictement sûr, pas de doublon). Les autres OSError
# (ex E2BIG Errno 7) restent NON retentées : permanentes pour un prompt
# donné. Backoff cumulé ~7 s : couvre largement la fenêtre de swap. Tuple
# monkeypatchable (mis à (0, 0, 0) en tests pour rester rapides).
_SPAWN_MAX_ATTEMPTS = 4
_SPAWN_RETRY_BACKOFF_SEC: tuple[float, ...] = (1.0, 2.0, 4.0)

# Phase D.1.1 : le service arac-developer tourne sous systemd avec
# `ProtectHome=true`, ce qui rend le vrai HOME du compte de service
# inaccessible au subprocess. On déplace donc le HOME de l'outil sous
# `$ARAC_HOME/data/agent-home/` — chemin que l'unité systemd doit lister dans
# `ReadWritePaths=`, donc lisible/écrivable par le subprocess sandboxé. claude CLI y trouve .claude/.credentials.json
# (OAuth) + .claude.json (config). Refresh OAuth fait par claude lui-même
# au fil des invocations (rotation tokens persistée dans ce HOME).
#
# SHELL forcé à /bin/bash car le shell de aracagent dans /etc/passwd est
# /usr/sbin/nologin. claude CLI a besoin d'un shell réel pour ses Bash internes.
_AGENT_HOME = str(arac_runtime.data_dir() / "agent-home")
_AGENT_SHELL = "/bin/bash"

# Liste blanche des outils autorisés. Le préfixe MCP est ajouté à l'exécution
# par `allowed_tools()` : il dépend du cerveau, pas du dépôt.
# Format claude CLI : "Tool" ou "Bash(pattern)" ou "mcp__<server>__<tool>"
# (espace-séparé). Bash patterns suivent la syntaxe claude code (cf docs).
#
# Le préfixe `mcp__<cerveau>__*` autorise tous les outils MCP exposés par
# le serveur de l'utilisateur (healthz, foundations, recall, context_for,
# lineage, list_atoms, get_atom, list_sessions, get_session, create_atom,
# patch_atom, supersede_atom, delete_atom, open_session). Le MCP n'est
# activé que si env `ARAC_MCP_CONFIG` est défini (cf cmd build plus bas).
ALLOWED_TOOLS_BASE: tuple[str, ...] = (
    "Read",
    "Edit",
    "Write",
    "Glob",
    "Grep",
    "Bash(git add:*)",
    "Bash(git commit:*)",
    "Bash(git status)",
    "Bash(git status:*)",
    "Bash(git diff:*)",
    "Bash(git log:*)",
    "Bash(git branch:*)",
    "Bash(git checkout:*)",
    "Bash(git push origin feature/*)",
    "Bash(ls:*)",
    "Bash(cat:*)",
    "Bash(mkdir:*)",
    "Bash(pytest:*)",
)


def _mcp_tool_prefix() -> str:
    """Le préfixe des outils MCP de CE cerveau.

    Cette valeur n'est pas décorative : elle est passée à `claude --allowedTools`.
    Elle était figée sur le nom du serveur MCP de l'installation d'origine, si
    bien qu'un utilisateur dont le serveur porte un autre nom voyait TOUS ses
    outils MCP refusés — sans message expliquant pourquoi. Le nom vient donc
    désormais du cerveau de l'utilisateur, avec priorité à une variable d'env
    pour ceux qui nomment leur serveur MCP autrement.
    """
    import os

    explicite = os.environ.get("ARAC_MCP_SERVER_NAME", "").strip()
    if explicite:
        return f"mcp__{explicite}"
    try:
        from arac_runtime import brain_name
        return f"mcp__{brain_name()}"
    except Exception:
        # Sans configuration lisible, on n'emprunte le nom de personne.
        return "mcp__arac"


def allowed_tools() -> tuple[str, ...]:
    """La liste blanche effective, préfixe MCP de l'utilisateur compris."""
    return ALLOWED_TOOLS_BASE + (_mcp_tool_prefix(),)


async def _drain_stream(
    stream: asyncio.StreamReader,
    kind: str,
    mission_logger: "MissionLogger | None",
) -> bytes:
    """Lit `stream` chunk-par-chunk, émet event chunk via mission_logger si fourni.

    Retourne le buffer complet (non tronqué).
    """
    seq = 0
    parts: list[bytes] = []
    while True:
        chunk = await stream.read(_CHUNK_SIZE)
        if not chunk:
            break
        parts.append(chunk)
        if mission_logger is not None:
            try:
                text = chunk.decode("utf-8", errors="replace")
                mission_logger.write_event(
                    f"subprocess.{kind}_chunk",
                    seq=seq,
                    bytes=len(chunk),
                    text=text,
                )
            except Exception as e:  # noqa: BLE001
                # Capture ne doit JAMAIS planter la mission.
                logger.warning(json.dumps({
                    "event": "claude_cli.chunk_log_fail",
                    "kind": kind,
                    "raison": raison(e),
                }))
        seq += 1
    return b"".join(parts)


async def run_claude_subprocess(
    prompt: str,
    *,
    cwd: str = DEFAULT_CWD,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    model: str = DEFAULT_MODEL,
    mission_logger: "MissionLogger | None" = None,
    no_tools: bool = False,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """Exécute `claude -p` headless avec restrictions D.1 MVP + capture D.4.

    Retourne un dict :
      - ok (bool) : exit_code == 0 ET pas de timeout
      - exit_code (int) : code de retour (-1 si timeout/erreur subprocess)
      - stdout (str) : sortie stdout COMPLÈTE (capture intégrale, ex-tronqué 10k)
      - stderr (str) : sortie stderr COMPLÈTE (capture intégrale)
      - stdout_summary (str) : 500 premiers chars de stdout (pour atomes legacy)
      - stderr_summary (str) : 500 premiers chars de stderr (pour atomes legacy)
      - duration_sec (int) : durée totale en secondes
      - duration_ms (int) : durée totale en millisecondes (précision D.4)
      - timed_out (bool) : True si killed après timeout_sec
      - stdout_bytes (int) : taille brute stdout en bytes
      - stderr_bytes (int) : taille brute stderr en bytes
    """
    # Phase D.4 : si MCP activé (env ARAC_MCP_CONFIG), on retire --allowedTools.
    # Le combo --allowedTools + --mcp-config bug côté Claude CLI : les MCP tools
    # ne sont alors PAS reconnus même quand listés explicitement par préfixe
    # mcp__<cerveau>__*. Sans --allowedTools, claude voit tous les tools (built-in
    # + MCP). Trade-off accepté : sandbox systemd (ProtectHome/ProtectSystem) +
    # audit gate D.2 (regex secrets + paths + branche) + branche feature/*
    # restent les barrières effectives. Cible Phase E : revoir si --allowedTools
    # devient compatible MCP côté Claude CLI.
    # Cortex V3 : `no_tools=True` = AUCUN outil — ni MCP ni built-in.
    # « Le LLM propose du JSON strict, le code déterministe dispose » : le
    # subprocess ne peut rien écrire, rien lire, rien exécuter. Tue au passage
    # le trade-off --allowedTools×MCP ci-dessus (plus de MCP du tout).
    mcp_config = "" if no_tools else os.environ.get("ARAC_MCP_CONFIG", "").strip()

    # v0.5.1 — le prompt est fourni via STDIN, PAS en argv.
    # Une conversation curator entière dépasse MAX_ARG_STRLEN
    # (131072 octets, cap single-arg Linux = 32 * PAGE_SIZE 4096) et fait
    # échouer execve avec `OSError [Errno 7] Argument list too long`. C'est
    # ce qui a bloqué 8 bundles sur 10 lors d'un incident mesuré. `claude -p`
    # sans prompt positionnel lit le prompt depuis stdin (mode pipe documenté
    # `claude --help` : « -p/--print … useful for pipes »).
    cmd = [
        resolve_claude_bin(),
        "-p",
        "--model",
        model,
        "--output-format",
        "text",
        "--permission-mode",
        "acceptEdits",
    ]

    if system_prompt:
        # Cortex V3 : REMPLACE le system prompt par défaut (le subprocess n'est
        # plus « Claude Code » — leçon du receipt #2 : sans ça, le modèle
        # répond en conversation au lieu d'émettre le contrat JSON).
        cmd.extend(["--system-prompt", system_prompt])
    if no_tools:
        # Liste d'outils autorisés VIDE : tout tool_use est refusé par le CLI.
        cmd.extend(["--allowedTools", ""])
    elif mcp_config:
        cmd.extend(["--mcp-config", mcp_config, "--strict-mcp-config"])
    else:
        cmd.extend(["--allowedTools", *allowed_tools()])

    start = time.monotonic()
    timed_out = False

    # Force HOME et SHELL pour que claude CLI sous user aracagent
    # (shell=/usr/sbin/nologin) puisse exécuter Bash sans interactif.
    subprocess_env = os.environ.copy()
    subprocess_env["HOME"] = _AGENT_HOME
    subprocess_env["SHELL"] = _AGENT_SHELL

    logger.info(json.dumps({
        "event": "claude_cli.subprocess_starting",
        "cmd_preview": " ".join(cmd[:6]) + " ...",
        "cwd": cwd,
        "home": subprocess_env.get("HOME"),
        "shell": subprocess_env.get("SHELL"),
    }))

    # v0.6 — retry sur FileNotFoundError transitoire (swap npm du binaire
    # global par un claude root concurrent). cf constantes _SPAWN_* plus haut.
    proc = None
    spawn_err: OSError | None = None
    attempt = 0
    for attempt in range(1, _SPAWN_MAX_ATTEMPTS + 1):
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                env=subprocess_env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            break  # spawn réussi
        except FileNotFoundError as e:
            # Binaire absent = swap npm en cours (claude root auto-update).
            # Transitoire : on retente après un court backoff.
            spawn_err = e
            if attempt < _SPAWN_MAX_ATTEMPTS:
                idx = min(attempt - 1, len(_SPAWN_RETRY_BACKOFF_SEC) - 1)
                backoff = _SPAWN_RETRY_BACKOFF_SEC[idx]
                logger.warning(json.dumps({
                    "event": "claude_cli.spawn_retry",
                    "attempt": attempt,
                    "max_attempts": _SPAWN_MAX_ATTEMPTS,
                    "backoff_sec": backoff,
                    "raison": raison(e),
                }))
                if mission_logger is not None:
                    mission_logger.write_event(
                        "subprocess.spawn_retry",
                        attempt=attempt,
                        backoff_sec=backoff,
                        error=raison(e)[:200],
                    )
                await asyncio.sleep(backoff)
                continue
            # Dernière tentative épuisée → échec géré sous la boucle.
        except OSError as e:
            # v0.5.1 — autre OSError (ex E2BIG `[Errno 7] Argument list
            # too long`, désormais impossible car le prompt passe par stdin, mais
            # garde-fou) : PERMANENTE pour un prompt donné → PAS de retry.
            spawn_err = e
            break

    if proc is None:
        # Échec définitif : FileNotFoundError après _SPAWN_MAX_ATTEMPTS, ou OSError
        # non-retentable. On RETOURNE un dict ok=False au lieu de propager : le
        # caller (_curate_one) marque alors la row 'failed' via mark_curated, ce
        # qui évite l'orphelin status='processing' qui a piégé les 8 bundles le
        # l'incident E2BIG.
        e = spawn_err
        msg = f"claude CLI spawn échec: {type(e).__name__}: {e}"
        logger.error(json.dumps({
            "event": "claude_cli.spawn_fail",
            "error": type(e).__name__,
            "raison": raison(e),
            "attempts": attempt,
        }))
        if mission_logger is not None:
            mission_logger.write_event(
                "subprocess.spawn_fail",
                error=raison(e)[:200],
                attempts=attempt,
            )
        return {
            "ok": False,
            "exit_code": -1,
            "stdout": "",
            "stderr": msg,
            "stdout_summary": "",
            "stderr_summary": msg[:_SUMMARY_CHARS],
            "duration_sec": 0,
            "duration_ms": 0,
            "timed_out": False,
            "stdout_bytes": 0,
            "stderr_bytes": 0,
        }

    logger.info(json.dumps({
        "event": "claude_cli.subprocess_pid",
        "pid": proc.pid,
    }))

    if mission_logger is not None:
        mission_logger.write_event(
            "subprocess.spawn",
            pid=proc.pid,
            cmd_preview=" ".join(cmd[:6]) + " ...",
            cwd=cwd,
            model=model,
            timeout_sec=timeout_sec,
            mcp_enabled=bool(mcp_config),
        )

    # v0.5.1 — alimente le prompt via stdin puis EOF. `claude -p`
    # consomme l'intégralité de stdin comme prompt (mode pipe) AVANT d'émettre
    # quoi que ce soit sur stdout (l'appel LLM n'a lieu qu'après lecture
    # complète du prompt). Écrire+drain ici, avant de drainer stdout/stderr,
    # ne deadlocke donc pas ; drain() applique le backpressure pour les gros
    # prompts (conversations de plusieurs centaines de Ko). On ferme stdin
    # pour signaler l'EOF.
    if proc.stdin is not None:
        try:
            proc.stdin.write(prompt.encode("utf-8"))
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as e:
            logger.warning(json.dumps({
                "event": "claude_cli.stdin_write_fail",
                "error": type(e).__name__,
                "raison": raison(e),
            }))
        finally:
            try:
                proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass

    stdout_b = b""
    stderr_b = b""
    exit_code = -1

    try:
        # Streaming concurrent stdout + stderr + wait du process.
        assert proc.stdout is not None
        assert proc.stderr is not None
        stdout_task = asyncio.create_task(
            _drain_stream(proc.stdout, "stdout", mission_logger)
        )
        stderr_task = asyncio.create_task(
            _drain_stream(proc.stderr, "stderr", mission_logger)
        )
        # On wait globalement (drains + proc.wait) sous timeout.
        done, pending = await asyncio.wait(
            {stdout_task, stderr_task, asyncio.create_task(proc.wait())},
            timeout=timeout_sec,
            return_when=asyncio.ALL_COMPLETED,
        )
        if pending:
            # Timeout : on cancel les drains et kill le process.
            timed_out = True
            for t in pending:
                t.cancel()
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            # Récupère ce qui a déjà été drainé jusqu'au cancel.
            try:
                stdout_b = stdout_task.result() if stdout_task.done() else b""
            except (asyncio.CancelledError, Exception):
                stdout_b = b""
            try:
                stderr_b = stderr_task.result() if stderr_task.done() else b""
            except (asyncio.CancelledError, Exception):
                stderr_b = b""
            stderr_b = (stderr_b or b"") + f"\nTIMEOUT after {timeout_sec}s — process killed".encode()
            exit_code = -1
        else:
            stdout_b = stdout_task.result()
            stderr_b = stderr_task.result()
            exit_code = proc.returncode if proc.returncode is not None else -1
            logger.info(json.dumps({
                "event": "claude_cli.subprocess_exited",
                "exit_code": exit_code,
                "stdout_len": len(stdout_b),
                "stderr_len": len(stderr_b),
            }))
    except Exception as e:  # noqa: BLE001
        # Sécurité : on ne propage pas, on retourne un dict cohérent.
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        stderr_b = (stderr_b or b"") + f"\nsubprocess wrapper error: {type(e).__name__}: {e}".encode()
        exit_code = -1

    duration_sec = int(time.monotonic() - start)
    duration_ms = int((time.monotonic() - start) * 1000)
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")

    if mission_logger is not None:
        mission_logger.write_event(
            "subprocess.exit",
            exit_code=exit_code,
            duration_ms=duration_ms,
            timed_out=timed_out,
            stdout_total_bytes=len(stdout_b),
            stderr_total_bytes=len(stderr_b),
        )

    return {
        "ok": (not timed_out) and exit_code == 0,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_summary": stdout[:_SUMMARY_CHARS],
        "stderr_summary": stderr[:_SUMMARY_CHARS],
        "duration_sec": duration_sec,
        "duration_ms": duration_ms,
        "timed_out": timed_out,
        "stdout_bytes": len(stdout_b),
        "stderr_bytes": len(stderr_b),
    }
