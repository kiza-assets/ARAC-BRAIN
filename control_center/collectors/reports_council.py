"""Control Center — collecteurs fichiers repo : documents, décisions, Council.

Doctrine : OBSERVE FIRST. DO NOT CONTROL. + READ ONLY.

Lectures pures du système de fichiers du repo (aucune écriture, aucun
subprocess mutateur). Trois sources :

  - ``docs/*.md``                 → liste des documents récents (nom + mtime,
                                     JAMAIS le contenu).
  - ``docs/DECISIONS.md``         → index des décisions ``D-NNN`` (numéro +
                                     titre, dernier numéro).
  - sessions Council dry-run      → metadata des verdicts (session_id,
                                     candidate_id, final_decision, created_at).
                                     AUCUN contenu de review / transcript /
                                     rationale n'est extrait.

CES TROIS SOURCES SONT LES VÔTRES, ET DEUX D'ENTRE ELLES N'EXISTENT PAS ENCORE
------------------------------------------------------------------------------
``docs/DECISIONS.md`` et le répertoire des sessions Council ne sont produits par
aucun code de ce dépôt : ce sont des artefacts que VOUS écrivez, si vous décidez
de tenir un registre de décisions ou de faire délibérer des agents. Le cockpit
les lit s'ils sont là.

Chaque collecteur rend donc, en plus de ses données, un **état déclaré** :
``state``, ``reason`` et ``gesture``. Une page qui ne peut rien afficher doit
DIRE qu'elle attend un fichier et lequel — un tableau vide sans explication
laisse croire à une panne, ou pire, à un cerveau qui n'a rien à raconter.

Les chemins (``DOCS_DIR``, ``COUNCIL_SESSIONS_DIR``, ``REPO_ROOT``) proviennent
de ``control_center.config`` quand disponible ; sinon fallback défensif local
dérivé de l'emplacement de ce module et des conventions repo.

Pour la timeline, ``timeline_versions`` lit les tags et branches via Git en
LECTURE seule (for-each-ref / tag) à travers l'allowlist de ``system_metrics``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from control_center.collectors.system_metrics import _run_readonly

# Regex d'extraction des décisions : "### D-024 — intitulé de la décision"
# Tolère "D-024 —", "D-024 -", "D-024 :" comme séparateurs titre.
_DECISION_RE = re.compile(r"D-(\d+)\s*[—:\-]?\s*(.*)")


# ============================================================================
# Résolution de chemins — délègue à config, fallback local défensif
# ============================================================================


def _repo_root() -> Path:
    """REPO_ROOT depuis config si dispo, sinon dérivé de l'emplacement module."""
    try:
        from control_center import config

        root = getattr(config, "REPO_ROOT", None)
        if root:
            return Path(root)
    except Exception:
        pass
    # control_center/collectors/reports_council.py → remonter de 2 dossiers.
    return Path(__file__).resolve().parent.parent.parent


def _docs_dir() -> Path:
    """DOCS_DIR depuis config si dispo, sinon ``<repo>/docs``."""
    try:
        from control_center import config

        d = getattr(config, "DOCS_DIR", None)
        if d:
            return Path(d)
    except Exception:
        pass
    return _repo_root() / "docs"


def _council_sessions_dir() -> Path:
    """COUNCIL_SESSIONS_DIR depuis config si dispo, sinon /tmp/arac_council/dryrun."""
    try:
        from control_center import config

        d = getattr(config, "COUNCIL_SESSIONS_DIR", None)
        if d:
            return Path(d)
    except Exception:
        pass
    return Path("/tmp/arac_council/dryrun")


# ============================================================================
# API publique
# ============================================================================


def recent_reports(n: int = 10) -> list[dict[str, Any]]:
    """Les ``n`` rapports ``docs/*.md`` les plus récents (par mtime).

    Retourne une liste de ``{"name": <str>, "modified": <iso str>}`` — NOM et
    date seulement, JAMAIS le contenu du fichier. Triée du plus récent au plus
    ancien. Répertoire absent / illisible → ``[]`` (jamais d'exception).
    """
    docs = _docs_dir()
    try:
        files = [p for p in docs.glob("*.md") if p.is_file()]
    except Exception:
        return []

    try:
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for p in files[: max(0, n)]:
        try:
            from datetime import datetime, timezone

            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            out.append({"name": p.name, "modified": mtime.isoformat()})
        except Exception:
            out.append({"name": p.name, "modified": None})
    return out


def decisions_index() -> dict[str, Any]:
    """Index des décisions ``D-NNN`` extrait de ``docs/DECISIONS.md``.

    Parse les en-têtes Markdown contenant ``D-NNN`` (numéro + titre). Retourne ::

        {
            "decisions": [{"number": int, "id": "D-024", "title": <str>}, ...],
            "last_number": int | None,
            "count": int,
        }

    Fichier absent / illisible → même forme, ``state="absent"`` et une ``reason``
    qui NOMME le fichier attendu. Aucun contenu de corps de décision n'est
    extrait, seulement numéro et titre de l'en-tête.

    POURQUOI l'état est déclaré : ``docs/DECISIONS.md`` n'est engendré par aucun
    code de ce dépôt. Un cerveau neuf n'en a donc pas, et la page « Décisions »
    est légitimement vide. Rendre un tableau vide sans un mot laisserait croire à
    une panne du cockpit ; l'état dit ce qui manque et ce qui le remplirait.
    """
    path = _docs_dir() / "DECISIONS.md"
    rel = "docs/DECISIONS.md"
    empty = {
        "decisions": [], "last_number": None, "count": 0,
        "state": "absent",
        "path": rel,
        "reason": (f"aucun registre de décisions dans ce dépôt : {rel} n'existe pas "
                   "ou n'est pas lisible"),
        "gesture": (f"écrivez {rel} — un titre Markdown par décision, de la forme "
                    "« ### D-001 — ce que vous avez tranché ». Le cockpit l'indexera "
                    "sans autre réglage."),
    }
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return empty

    decisions: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in text.splitlines():
        line = raw.strip()
        # On ne traite que les en-têtes Markdown (### D-024 — ...) pour éviter
        # de capter des références « D-024 » en plein texte.
        if not line.startswith("#"):
            continue
        header = line.lstrip("#").strip()
        m = _DECISION_RE.match(header)
        if not m:
            continue
        num = int(m.group(1))
        if num in seen:
            continue
        seen.add(num)
        decisions.append(
            {
                "number": num,
                "id": f"D-{m.group(1)}",
                "title": m.group(2).strip(),
            }
        )

    decisions.sort(key=lambda d: d["number"])
    last_number = decisions[-1]["number"] if decisions else None
    if not decisions:
        # Le fichier EXISTE mais ne porte aucun en-tête « D-NNN » : ce n'est pas
        # la même absence, et le geste n'est pas le même non plus.
        return dict(empty, state="vide", reason=(
            f"{rel} existe mais ne contient aucun en-tête « D-NNN »"),
            gesture=("ajoutez des titres de la forme « ### D-001 — … » : "
                     "seuls les en-têtes Markdown sont indexés, jamais le corps"))
    return {
        "decisions": decisions,
        "last_number": last_number,
        "count": len(decisions),
        "state": "ok",
        "path": rel,
        "reason": None,
        "gesture": None,
    }


def council_recent_verdicts(n: int = 5) -> list[dict[str, Any]]:
    """Metadata des ``n`` derniers verdicts Council dry-run.

    Lit récursivement ``COUNCIL_SESSIONS_DIR/**/session_*.json``. Pour chaque
    session, extrait UNIQUEMENT la metadata ::

        {"session_id": <str>, "candidate_id": <str>,
         "final_decision": <str>, "created_at": <str>}

    AUCUN contenu de review / transcript / rationale / argument n'est lu. Tri
    par ``created_at`` décroissant (plus récent d'abord) ; fallback sur mtime
    fichier si ``created_at`` absent. Répertoire absent → ``[]``.
    """
    base = _council_sessions_dir()
    try:
        paths = list(base.glob("**/session_*.json"))
    except Exception:
        return []
    if not paths:
        return []

    items: list[dict[str, Any]] = []
    for p in paths:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue

        receipt = data.get("receipt") or {}
        decision = data.get("president_decision") or {}

        session_id = data.get("session_id") or receipt.get("session_id")
        candidate_id = receipt.get("candidate_id")
        if candidate_id is None:
            cand = data.get("candidate") or {}
            candidate_id = cand.get("candidate_id")
        final_decision = receipt.get("final_decision") or decision.get(
            "final_decision"
        )
        created_at = receipt.get("created_at")

        # mtime de secours pour le tri si created_at manquant.
        try:
            mtime = p.stat().st_mtime
        except Exception:
            mtime = 0.0

        items.append(
            {
                "session_id": session_id,
                "candidate_id": candidate_id,
                "final_decision": final_decision,
                "created_at": created_at,
                "_sort_key": created_at or "",
                "_mtime": mtime,
            }
        )

    # Tri : created_at desc (chaîne ISO triable), puis mtime desc en secours.
    items.sort(key=lambda d: (d["_sort_key"], d["_mtime"]), reverse=True)

    cleaned: list[dict[str, Any]] = []
    for it in items[: max(0, n)]:
        cleaned.append(
            {
                "session_id": it["session_id"],
                "candidate_id": it["candidate_id"],
                "final_decision": it["final_decision"],
                "created_at": it["created_at"],
            }
        )
    return cleaned


def council_index(n: int = 5) -> dict[str, Any]:
    """Les verdicts Council **et l'état de leur source**.

    Forme ::

        {"verdicts": [...], "count": int, "state": "ok"|"absent"|"vide",
         "path": <str>, "reason": <str|None>, "gesture": <str|None>}

    POURQUOI cette fonction double ``council_recent_verdicts`` : cette dernière
    rend une liste, et une liste vide ne sait pas dire POURQUOI elle est vide.
    Or le répertoire des sessions Council n'est produit par aucun code de ce
    dépôt — un cerveau neuf n'en a pas, et sa page Council est vide pour de bon.
    Une page définitivement vide doit nommer ce qui la remplirait, sans quoi elle
    se lit comme une panne.

    ``council_recent_verdicts`` reste la seule porte d'entrée des DONNÉES, avec
    sa garantie « metadata seulement » : cette fonction ne fait qu'y ajouter
    l'état de la source.
    """
    base = _council_sessions_dir()
    verdicts = council_recent_verdicts(n)
    if verdicts:
        return {"verdicts": verdicts, "count": len(verdicts), "state": "ok",
                "path": str(base), "reason": None, "gesture": None}
    try:
        exists = base.is_dir()
    except Exception:
        exists = False
    if not exists:
        return {
            "verdicts": [], "count": 0, "state": "absent", "path": str(base),
            "reason": (f"aucune session Council : le répertoire {base} n'existe pas. "
                       "Rien dans ce dépôt ne l'écrit — la délibération d'agents est "
                       "un usage que vous branchez, pas un service livré."),
            "gesture": (f"faites écrire des fichiers {base}/**/session_*.json par votre "
                        "propre délibération, ou pointez ARAC_COUNCIL_SESSIONS_DIR sur "
                        "le répertoire où elle les dépose."),
        }
    return {
        "verdicts": [], "count": 0, "state": "vide", "path": str(base),
        "reason": (f"le répertoire {base} existe mais ne contient aucun "
                   "fichier session_*.json lisible"),
        "gesture": "aucun geste côté cockpit : c'est la délibération qui n'a rien déposé.",
    }


#: La convention de nommage des branches que la timeline met en avant.
#:
#: POURQUOI c'est une variable et non un motif gravé : le cockpit citait
#: une convention de nommage propre à un dépôt particulier. Chez qui nomme
#: ses branches autrement, ce panneau restait vide sans jamais dire pourquoi —
#: et il apprenait au lecteur une convention qui n'était pas la sienne. Rien
#: n'est déclaré par défaut : le cockpit ne suppose aucune convention.
RELEASE_BRANCH_GLOB_ENV: str = "ARAC_COCKPIT_RELEASE_BRANCHES"


def release_branch_glob() -> str | None:
    """Le motif de branches déclaré, ou ``None`` si aucun ne l'est."""
    return (os.environ.get(RELEASE_BRANCH_GLOB_ENV) or "").strip() or None


def timeline_versions() -> dict[str, Any]:
    """Tags Git + branches de la convention DÉCLARÉE (lecture seule).

    Forme nominale ::

        {"tags": [<str>, ...], "release_branches": [<str>, ...],
         "branch_glob": <str|None>, "branch_reason": <str|None>}

    Les tags sont universels : tout dépôt Git en a, ou n'en a pas, et le cockpit
    le constate. Les branches, elles, dépendent d'une convention de nommage : le
    cockpit n'en invente aucune et ne lit que celle que déclare
    ``ARAC_COCKPIT_RELEASE_BRANCHES`` (ex. ``refs/heads/release/*``). Sans
    déclaration, la liste est vide et ``branch_reason`` dit pourquoi.

    Utilise ``git tag`` et ``git for-each-ref`` via l'allowlist read-only de
    ``system_metrics``. Tout échec dégrade le champ concerné en ``[]`` sans
    lever.
    """
    tags: list[str] = []
    tag_r = _run_readonly(["git", "tag", "--sort=-creatordate"])
    if tag_r.get("ok") and tag_r.get("stdout"):
        tags = [ln.strip() for ln in tag_r["stdout"].splitlines() if ln.strip()]

    glob = release_branch_glob()
    if not glob:
        return {
            "tags": tags,
            "release_branches": [],
            "branch_glob": None,
            "branch_reason": (
                "aucune convention de branches déclarée : le cockpit n'en suppose "
                f"aucune. Posez {RELEASE_BRANCH_GLOB_ENV} (ex. « refs/heads/release/* ») "
                "pour que ce panneau suive les vôtres."
            ),
        }

    branches: list[str] = []
    ref_r = _run_readonly(
        ["git", "for-each-ref", "--format=%(refname:short)", glob]
    )
    if ref_r.get("ok") and ref_r.get("stdout"):
        branches = [
            ln.strip() for ln in ref_r["stdout"].splitlines() if ln.strip()
        ]

    return {"tags": tags, "release_branches": branches,
            "branch_glob": glob, "branch_reason": None}
