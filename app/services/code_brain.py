"""Cerveau code — indexeur structurel PUR (Phase G).

Indexation DÉTERMINISTE du code Python via `ast` (AUCUN appel OpenAI, AUCUN
embedding ici — coût LLM nul par construction, cf budgets mission §G/§J). Extrait
fichiers / symboles / routes / tests / imports et construit un graphe d'impact.
Indexation INCRÉMENTALE par hash de fichier + commit HEAD : si HEAD inchangé et
aucun fichier modifié, AUCUN re-scan. Une erreur de parser est ISOLÉE (le fichier
fautif porte `parse_error`, l'index global reste utilisable). Un fichier
NON indexé répond par une INCERTITUDE explicite, jamais par une invention.

Le schéma physique vit dans la migration 0014 (tables `code_*`). Ce module porte
la logique pure (parsing + graphe + requêtes), réutilisable par un cron d'index
et par le routeur de contexte (Phase H).
"""

from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from typing import Iterable, Mapping

_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}


def file_hash(content: str) -> str:
    """sha256 du contenu (clé d'incrémentalité : même hash -> pas de re-parse)."""
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def module_name_for(path: str) -> str:
    """Nom de module Python déduit du chemin repo-relatif.
    `agents/curator/main.py` -> `agents.curator.main` ; `pkg/__init__.py` -> `pkg`."""
    p = path[:-3] if path.endswith(".py") else path
    parts = [seg for seg in p.split("/") if seg]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


@dataclass
class Symbol:
    name: str
    kind: str          # function | class | method
    lineno: int


@dataclass
class Route:
    method: str
    path: str
    handler: str       # nom de la fonction handler


@dataclass
class FileRecord:
    path: str
    sha256: str
    module: str
    last_commit: str | None = None
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)      # modules importés (noms)
    routes: list[Route] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)         # noms des fonctions test_*
    referenced_names: set[str] = field(default_factory=set)  # noms cités (pour tests->symbole)
    parse_error: str | None = None

    @property
    def is_test_file(self) -> bool:
        base = self.path.rsplit("/", 1)[-1]
        return base.startswith("test_") or self.path.startswith("tests/")


@dataclass
class CodeIndex:
    head: str | None = None
    files: dict[str, FileRecord] = field(default_factory=dict)

    def is_indexed(self, path: str) -> bool:
        return path in self.files


# --- Parsing (déterministe, ast) --------------------------------------------
def parse_python_source(path: str, source: str, last_commit: str | None = None) -> FileRecord:
    """Parse un fichier Python. En cas de SyntaxError, renvoie un FileRecord avec
    `parse_error` posé (jamais d'exception propagée : isolation du fichier fautif)."""
    rec = FileRecord(path=path, sha256=file_hash(source), module=module_name_for(path),
                     last_commit=last_commit)
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        rec.parse_error = f"{type(exc).__name__}: {exc.msg} (line {exc.lineno})"
        return rec

    for node in tree.body:
        _collect_top_level(node, rec)
    # Noms référencés (pour relier un test à un symbole).
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            rec.referenced_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            rec.referenced_names.add(node.attr)
    return rec


def _collect_top_level(node: ast.stmt, rec: FileRecord) -> None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        rec.symbols.append(Symbol(node.name, "function", node.lineno))
        if node.name.startswith("test_"):
            rec.tests.append(node.name)
        _collect_routes(node, rec)
    elif isinstance(node, ast.ClassDef):
        rec.symbols.append(Symbol(node.name, "class", node.lineno))
        for sub in node.body:
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                rec.symbols.append(Symbol(f"{node.name}.{sub.name}", "method", sub.lineno))
    elif isinstance(node, ast.Import):
        for alias in node.names:
            rec.imports.append(alias.name)
    elif isinstance(node, ast.ImportFrom):
        if node.level == 0 and node.module:
            base = node.module                      # import absolu
        elif node.level >= 1:
            base = _resolve_relative(rec, node.level, node.module)  # import relatif
        else:
            base = None
        if base:
            rec.imports.append(base)
            # `from base import c` peut importer le SOUS-MODULE base.c : on enregistre
            # aussi base.<name> (sinon on rate la dépendance sur un sous-module).
            for alias in node.names:
                rec.imports.append(f"{base}.{alias.name}")


def _resolve_relative(rec: "FileRecord", level: int, module: str | None) -> str | None:
    """Résout un import relatif (`from . import x`, `from ..lib import y`) en nom
    de module ABSOLU, en s'appuyant sur le module du fichier. Gère le cas package
    (__init__.py) vs module régulier. None si la résolution sort de la racine."""
    parts = rec.module.split(".") if rec.module else []
    is_pkg = rec.path.endswith("__init__.py")
    drop = level - (1 if is_pkg else 0)
    if drop < 0 or drop > len(parts):
        return None
    anchor = parts[: len(parts) - drop]
    if not anchor and not module:
        return None
    base = ".".join(anchor)
    if module:
        base = f"{base}.{module}" if base else module
    return base or None


def _collect_routes(func: ast.FunctionDef | ast.AsyncFunctionDef, rec: FileRecord) -> None:
    """Détecte `@router.get("/x")` / `@app.post("/y")` (FastAPI)."""
    for dec in func.decorator_list:
        if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
            continue
        method = dec.func.attr.lower()
        if method not in _HTTP_METHODS:
            continue
        if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
            rec.routes.append(Route(method=method, path=dec.args[0].value, handler=func.name))


# --- Indexation incrémentale ------------------------------------------------
@dataclass
class IndexStats:
    head: str | None
    total: int = 0
    reindexed: int = 0
    reused: int = 0
    parse_errors: int = 0
    head_unchanged: bool = False
    rescanned: bool = True


def index_files(
    files: Mapping[str, str],
    head: str | None,
    prev: CodeIndex | None = None,
    *,
    last_commits: Mapping[str, str] | None = None,
) -> tuple[CodeIndex, IndexStats]:
    """Construit/rafraîchit l'index. INCRÉMENTAL :
      - HEAD identique au précédent ET mêmes fichiers/hash -> AUCUN re-parse.
      - sinon, ne re-parse QUE les fichiers dont le hash a changé.
    """
    prev = prev or CodeIndex()
    last_commits = last_commits or {}
    stats = IndexStats(head=head, total=len(files))

    # Court-circuit : HEAD inchangé + ensemble de hash identique -> réutilise tel quel.
    if prev.head is not None and prev.head == head:
        same = (set(prev.files) == set(files) and
                all(prev.files[p].sha256 == file_hash(c) for p, c in files.items()))
        if same:
            stats.head_unchanged = True
            stats.rescanned = False
            stats.reused = len(prev.files)
            return prev, stats

    new_index = CodeIndex(head=head, files={})
    for path, content in files.items():
        h = file_hash(content)
        old = prev.files.get(path)
        if old is not None and old.sha256 == h:
            new_index.files[path] = old           # réutilise (hash inchangé)
            stats.reused += 1
            continue
        rec = parse_python_source(path, content, last_commit=last_commits.get(path))
        new_index.files[path] = rec
        stats.reindexed += 1
        if rec.parse_error:
            stats.parse_errors += 1
    return new_index, stats


# --- Requêtes (avec incertitude explicite) ----------------------------------
def symbol_to_files(index: CodeIndex, name: str) -> list[str]:
    """Fichiers définissant le symbole `name` (function/class ; ou `Class.method`)."""
    out = []
    for path, rec in index.files.items():
        if any(s.name == name for s in rec.symbols):
            out.append(path)
    return sorted(out)


def symbol_to_tests(index: CodeIndex, name: str) -> list[str]:
    """Fichiers de test qui RÉFÉRENCENT le symbole `name`."""
    short = name.split(".")[-1]
    out = []
    for path, rec in index.files.items():
        if rec.is_test_file and (name in rec.referenced_names or short in rec.referenced_names):
            out.append(path)
    return sorted(out)


def route_to_handler(index: CodeIndex, method: str, path: str) -> dict | None:
    """Handler d'une route (method, path) -> {file, handler} ou None (incertitude)."""
    method = method.lower()
    for fpath, rec in index.files.items():
        for r in rec.routes:
            if r.method == method and r.path == path:
                return {"file": fpath, "handler": r.handler, "method": method, "path": path}
    return None


def file_dependents(index: CodeIndex, path: str) -> list[str]:
    """Fichiers qui IMPORTENT le module défini par `path` (dépendants directs)."""
    target = index.files[path].module if path in index.files else module_name_for(path)
    out = []
    for p, rec in index.files.items():
        if p == path:
            continue
        # dépend de `target` si un import vaut exactement target, ou est un
        # sous-module/symbole de target (target.<…>).
        if any(imp == target or imp.startswith(target + ".") for imp in rec.imports):
            out.append(p)
    return sorted(set(out))


def impacted_by(index: CodeIndex, path: str) -> list[str]:
    """Fermeture transitive des DÉPENDANTS de `path` (graphe d'impact).
    Le fichier `path` lui-même est EXCLU du résultat (même en présence d'un cycle
    d'imports A->B->A) : on renvoie ce qui est impacté PAR `path`, pas `path`."""
    seen: set[str] = set()
    stack = [path]
    while stack:
        cur = stack.pop()
        for dep in file_dependents(index, cur):
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    seen.discard(path)            # jamais s'inclure soi-même (cohérence sur cycle)
    return sorted(seen)


def resolve(index: CodeIndex, path: str) -> dict:
    """Réponse SOURCÉE pour un fichier, avec incertitude explicite si non indexé."""
    if not index.is_indexed(path):
        return {"path": path, "indexed": False, "uncertain": True,
                "reason": "file_not_indexed"}
    rec = index.files[path]
    return {
        "path": path, "indexed": True, "uncertain": bool(rec.parse_error),
        "module": rec.module, "sha256": rec.sha256, "parse_error": rec.parse_error,
        "symbols": [s.name for s in rec.symbols],
        "routes": [{"method": r.method, "path": r.path, "handler": r.handler} for r in rec.routes],
        "dependents": file_dependents(index, path),
    }


# --- Lien code <-> décision métier (optionnel) ------------------------------
def decisions_to_revalidate(
    changed_files: Iterable[str],
    atom_code_links: Mapping[str, list[str]],
) -> list[str]:
    """atom_code_links: {atom_id: [fichiers/symboles dont dépend la décision]}.
    Retourne les atom_id à REVALIDER car un fichier lié a changé (alerte, pas
    invalidation auto)."""
    changed = set(changed_files)
    flagged = []
    for atom_id, deps in atom_code_links.items():
        if any(d in changed for d in deps):
            flagged.append(atom_id)
    return sorted(flagged)
