"""Le garde du journal : un contrôle STATIQUE de ce qu'un `ExecStart` peut imprimer.

CE QU'IL EXISTE POUR EMPÊCHER
-----------------------------
Le journal systemd appartient à la machine, pas au cerveau : lisible par `root`
et par tout compte du groupe `systemd-journal`, conservé des semaines, et que
la désinstallation ne sait pas purger unité par unité. La règle du dépôt est
écrite depuis longtemps — `dedup_thresholds.key_sha8` (« aucune clé ne doit
être écrite en clair dans un artefact durable »), `dispose._sanitize_error_body`
(« la revue humaine passe par la DB, JAMAIS via journald »),
`cycle._errors_pour_journal` (fermé par défaut) — mais rien ne la faisait
respecter. Elle a donc été appliquée là où quelqu'un y a pensé, et oubliée
partout ailleurs : huit sites inventoriés, cinq fermés, trois laissés
ouverts pendant que la désinstallation imprimait « VERDICT : PROPRE » en
code 0.

Un garde de RUNTIME ne suffit pas : `app/journal.FiltreMemoire` ferme le canal
des traces d'exception, mais il ne peut pas deviner qu'une chaîne de
caractères est le domaine de quelqu'un. Un garde qui CHERCHE UN TÉMOIN dans un
journal ne suffit pas non plus — c'est exactement ce qui a échoué : le §13.10
cherchait la chaîne d'une ancienne fuite, sur un chemin que l'acceptation
n'emprunte jamais faute de clé payante, et rendait « ✓ » à chaque passage.

Ce garde-ci ne cherche pas un témoin : il lit le CODE, et il refuse la forme.

CE QU'IL LIT, ET POURQUOI CE PÉRIMÈTRE
--------------------------------------
Les entrées ne sont pas écrites en dur : elles sont extraites de
`bootstrap/lib/services.sh`, c'est-à-dire des `ExecStart=` que le produit
installe réellement. Si demain une quatrième unité démarre un quatrième
module, elle entre dans le périmètre sans que personne n'ait à y penser.

La fermeture, elle, est FERMÉE PAR DÉFAUT : on part des modules d'entrée, on
suit les imports de première partie, PUIS on ajoute tout fichier `.py` du
paquet qui contient un module atteint. Cette dernière règle n'est pas de la
paresse, c'est la leçon de la manche précédente : `control_center/cc_v1/
scopes.py` et `lifestory.py` — deux des trois sites restants — ne sont
atteignables que par `importlib.import_module` depuis le registre, et une
fermeture d'imports statique ne les aurait JAMAIS vus. Un juge qui n'emprunte
pas le vrai chemin ne voit pas ce qui s'y passe.

LES CINQ RÈGLES
---------------
G1  Le filet est posé. Chaque module d'entrée d'un `ExecStart` appelle
    `installer_garde_journal()`. C'est lui qui rend `exc_info` acceptable :
    la permission de journaliser une trace s'ACHÈTE en posant le filtre qui
    l'assainit.
G2  Aucune exception en clair. Un objet exception ne peut entrer dans une ligne
    de journal que par un réducteur : `type(e).__name__`,
    `diagnostic_exception(e)`, `raison(e)`. Le message d'une erreur PostgreSQL
    porte « DETAIL:  Failing row contains (…) » — mesuré, le souvenir en clair.
G3  Aucun champ de mémoire en clair. Les noms du vocabulaire de la mémoire
    (`scope`, `key`, `value`, `title`, `rationale`, `preview`, `text`, `query`,
    `combos`, `payload`, `atom`) doivent traverser un réducteur.
G4  Aucun gabarit qui NOMME un champ de mémoire suivi d'un trou : `scope=%s`,
    `key={}`, `value=%r` — la forme même de la fuite des trois sites restants.
G5  Dans le TEXTE d'un message, FERMÉ PAR DÉFAUT : toute valeur interpolée est
    refusée sauf preuve — un réducteur, un nom qui porte son contrat
    (`_sha8`, `_count`, `_id`…), une constante de module en majuscules, ou une
    entrée du VOCABULAIRE_MACHINE, où chaque mot dit d'où il vient.

    G5 EST NÉ D'UNE FUITE QUE G3 NE POUVAIT PAS VOIR, et qu'aucune relecture
    n'aurait trouvée : le cockpit journalisait `where=scope:perso/sante`, parce
    que ses appelants COMPOSENT ce `where` avec la valeur regardée
    (`_failure(f"scope:{resolved}", exc)`). Le mot « where » n'est dans aucun
    vocabulaire de la mémoire — et il n'y a aucune raison qu'il y soit. C'est
    en RÉVOQUANT un SELECT sur un cerveau vivant, pour provoquer une vraie
    panne, qu'on l'a vu sortir. G3 nomme ce qu'on sait ; G5 refuse ce qu'on ne
    sait pas nommer.

    Les deux listes ne sont pas du même côté : celle de G3 (la mémoire) oublie
    vers la FUITE, celle de G5 (la machine) oublie vers la FAUSSE ALERTE. On
    tient donc la seconde longue et la première courte.

Ce module est une bibliothèque : le test qui le fait mordre est
`tests/acceptance/test_le_journal_ne_retient_aucun_souvenir.py`.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path


PAQUETS_PREMIERE_PARTIE = ("app", "agents", "control_center")

# ---------------------------------------------------------------------------
# Le vocabulaire de la mémoire — FERMÉ, et court exprès.
# ---------------------------------------------------------------------------
# Une liste longue donne l'illusion de la couverture ; celle-ci ne prétend pas
# couvrir, elle nomme les champs que le SCHÉMA appelle ainsi (`arac.memory_atoms`
# : scope, key, value, rationale) plus ceux que les avertissements et le cockpit
# fabriquent à partir d'eux. Ce qui n'est pas dans cette liste est couvert par
# G2 (les exceptions) et par le filtre de runtime.
VOCABULAIRE_MEMOIRE = frozenset({
    "scope", "scopes", "key", "keys", "value", "values",
    "title", "titre", "rationale", "preview", "combos",
    "text", "texte", "content", "contenu", "payload", "atom",
    "query", "excerpt", "extrait", "souvenir",
})

# Ce qui rend une valeur publiable. Chacun se justifie : une empreinte ne se
# renverse pas, une longueur est un nombre, un type est un nom de classe écrit
# dans le source, `reduire` est fermé par défaut.
REDUCTEURS = frozenset({
    "sha8", "key_sha8", "empreinte", "reduire", "len", "type", "bool", "int",
    "float", "sorted", "set", "id", "mask_secrets", "mask_recursive",
    "assainir_texte", "diagnostic_exception", "trace_assainie",
    "_sanitize_error_body", "_errors_pour_journal", "is_ceremony_key", "raison",
    "_where_pour_journal",
})

# Un suffixe qui DIT que la valeur est déjà réduite. On ne fait pas confiance
# au nom seul : il faut que l'expression passe aussi par un réducteur, sauf
# pour ces suffixes-là, qui sont le contrat de nommage du dépôt.
SUFFIXES_SURS = ("_sha8", "_len", "_count", "_chars", "_hash", "_id", "_ids", "_n",
                 "_ms", "_sec", "_bytes", "_octets")

# ---------------------------------------------------------------------------
# Le vocabulaire de la MACHINE — l'autre côté, et le côté SÛR d'une liste.
# ---------------------------------------------------------------------------
# G5 est fermé par défaut : dans le TEXTE d'un message, toute valeur interpolée
# est refusée sauf preuve du contraire. Cette liste porte les preuves. Elle est
# du BON côté : l'oublier fait crier le garde à tort (on s'en aperçoit tout de
# suite), jamais fuir en silence. C'est l'inverse d'une liste d'interdits, qui
# oublie précisément ce que personne n'avait imaginé.
#
# Chaque entrée dit d'où elle vient, et pourquoi elle ne peut porter aucun mot
# de personne.
VOCABULAIRE_MACHINE = frozenset({
    # Valeurs de configuration lues dans l'environnement du service, et leurs
    # défauts, écrits dans le source (`agents/cortex/pack.py`).
    "raw", "val", "effective", "max_msgs", "max_tokens", "cap", "slots",
    "estimations", "budget", "limite",
    # Noms de classes et de modules — écrits dans le source.
    "__name__", "__qualname__", "__module__",
    # État interne d'une machine à états : phases, modes, compteurs d'échec.
    "phase", "mode", "state", "etat", "attempt", "failures", "_failures",
    "substitute", "collisions", "reste", "restant",
    # Canaux PostgreSQL et jetons d'abonné : littéraux du source pour les
    # premiers, tirage `secrets` pour les seconds.
    "channel", "channels", "_notifies", "join", "sorted",
    # Un identifiant d'événement de crochet interne (`register_hook`) : un
    # littéral du source, jamais une donnée.
    "event", "token", "backend_pid",
    # LE REFUS D'UN CYCLE, ET SON GESTE. Ajoutés le jour où un refus de
    # préflight a cessé d'être muet — « je n'ai pas pu » n'est ni « c'est
    # bon » ni « c'est cassé », et le journal est le SEUL endroit où le
    # lecteur d'un `systemctl start` verra la phrase.
    #   · `remede` / `remede_claude` : composés par `spend_guard.remede_pour`
    #     et `claude_cli.curation_disponible` à partir de littéraux du source,
    #     d'un chemin de coffre et d'un chemin de binaire. Aucune de leurs
    #     pièces ne vient de la mémoire — ni atome, ni conversation, ni requête.
    #   · `slot_key` : « circadian_2100@2026-08-10 », une heure déclarée et une
    #     date. Déjà journalisé comme champ structuré partout ailleurs.
    #   · `chemin_du_coffre` : /etc/arac/<base>/arac.env, déduit de
    #     l'environnement du service.
    "remede", "remede_claude", "slot_key", "chemin_du_coffre",
})

NIVEAUX = frozenset({
    "debug", "info", "warning", "warn", "error", "exception", "critical",
    "fatal", "log",
})
_JOURNALISEUR = re.compile(r"^(_{0,2}logger|_{0,2}log|LOG|logging|_journal)$", re.I)
_FONCTIONS_JOURNAL = frozenset({"_log", "_emit_warnings_log", "_journal"})

# G4 : un gabarit qui nomme un champ de mémoire juste avant un trou.
_GABARIT_FUITANT = re.compile(
    r"\b(" + "|".join(sorted(VOCABULAIRE_MEMOIRE)) + r")\s*[=:]\s*[%{]"
)

_NOMS_EXCEPTION = frozenset({"e", "exc", "err", "error", "ex", "exception"})


@dataclass(frozen=True)
class Violation:
    fichier: str
    ligne: int
    regle: str
    motif: str
    extrait: str


# ---------------------------------------------------------------------------
# Le périmètre : ce qu'un ExecStart peut atteindre
# ---------------------------------------------------------------------------

def entrees_execstart(racine: Path) -> tuple[str, ...]:
    """Les modules Python que les `ExecStart=` du produit démarrent.

    Lus dans `bootstrap/lib/services.sh` — le fichier qui écrit les unités —
    et non recopiés ici : un garde qui recopie ce qu'il surveille surveille sa
    copie.
    """
    services = racine / "bootstrap" / "lib" / "services.sh"
    if not services.exists():
        return ()
    texte = services.read_text(encoding="utf-8", errors="replace")
    trouves = re.findall(
        r'ARAC_\w+(?:_APP|_MODULE)="\$\{ARAC_\w+:-([\w.]+)(?::\w+)?\}"', texte
    )
    return tuple(sorted(set(trouves)))


def _chemin(racine: Path, module: str) -> Path | None:
    p = racine / (module.replace(".", "/") + ".py")
    if p.exists():
        return p
    p = racine / module.replace(".", "/") / "__init__.py"
    return p if p.exists() else None


def fermeture(racine: Path) -> tuple[Path, ...]:
    """Tous les fichiers qu'un `ExecStart` peut atteindre. FERMÉ PAR DÉFAUT.

    Deux temps : la fermeture d'import statique, puis l'élargissement au PAQUET
    de chaque module atteint. Le second temps est celui qui compte — c'est lui
    qui rattrape les modules chargés par `importlib.import_module`, et c'est
    exactement là que vivaient deux des trois fuites restantes.
    """
    vus: set[str] = set()
    pile = list(entrees_execstart(racine))
    while pile:
        nom = pile.pop()
        if nom in vus:
            continue
        chemin = _chemin(racine, nom)
        if chemin is None:
            continue
        vus.add(nom)
        try:
            arbre = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                for alias in noeud.names:
                    if alias.name.split(".")[0] in PAQUETS_PREMIERE_PARTIE:
                        pile.append(alias.name)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module and not noeud.level:
                if noeud.module.split(".")[0] in PAQUETS_PREMIERE_PARTIE:
                    pile.append(noeud.module)
                    for alias in noeud.names:
                        pile.append(f"{noeud.module}.{alias.name}")

    fichiers: set[Path] = set()
    for nom in vus:
        chemin = _chemin(racine, nom)
        if chemin is None:
            continue
        fichiers.add(chemin)
        # Élargissement au paquet : tout `.py` sous le répertoire du module.
        dossier = chemin.parent
        for autre in dossier.rglob("*.py"):
            if "__pycache__" not in autre.parts:
                fichiers.add(autre)
    return tuple(sorted(fichiers))


# ---------------------------------------------------------------------------
# La lecture d'un appel de journalisation
# ---------------------------------------------------------------------------

def _nom_appele(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _est_reducteur(noeud: ast.expr) -> bool:
    return isinstance(noeud, ast.Call) and _nom_appele(noeud.func) in REDUCTEURS


def _noms_non_reduits(noeud: ast.expr) -> set[str]:
    """Les identifiants que l'expression rend EN CLAIR.

    On descend l'arbre, mais on ÉLAGUE tout sous-arbre dont la racine est un
    réducteur : `type(exc).__name__` ne rend pas `exc`, `sha8(payload["key"])`
    ne rend pas `key`. Sans cet élagage, le garde crierait sur les endroits qui
    font déjà ce qu'il faut — et un garde qui crie à tort finit désarmé.
    """
    sortie: set[str] = set()

    def descendre(n: ast.AST) -> None:
        if isinstance(n, ast.expr) and _est_reducteur(n):
            return
        if isinstance(n, ast.Name):
            sortie.add(n.id)
            return
        if isinstance(n, ast.Attribute):
            # Ce qui SORT d'un `payload.topic`, c'est `topic` — pas `payload`.
            # Sans cette précision le garde criait sur `payload.k`, qui est un
            # entier, et un garde qui crie à tort finit désarmé.
            sortie.add(n.attr)
            if not isinstance(n.value, ast.Name):
                descendre(n.value)
            return
        if isinstance(n, ast.Subscript):
            cle = n.slice
            if isinstance(cle, ast.Constant) and isinstance(cle.value, str):
                sortie.add(cle.value)
                if not isinstance(n.value, ast.Name):
                    descendre(n.value)
                return
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            sortie.add("§" + n.value)
            return
        for enfant in ast.iter_child_nodes(n):
            descendre(enfant)

    descendre(noeud)
    return sortie


def _sur_par_le_nom(nom: str) -> bool:
    return nom.endswith(SUFFIXES_SURS)


def _appel_de_journal(noeud: ast.AST) -> str | None:
    if not isinstance(noeud, ast.Call):
        return None
    func = noeud.func
    if isinstance(func, ast.Attribute) and func.attr in NIVEAUX:
        base = func.value
        nom = base.id if isinstance(base, ast.Name) else _nom_appele(base)
        if _JOURNALISEUR.match(nom or ""):
            return func.attr
    if isinstance(func, ast.Name) and func.id in _FONCTIONS_JOURNAL:
        return func.id
    return None


def _arguments_journalises(noeud: ast.Call) -> list[tuple[str | None, ast.expr]]:
    """(nom du champ, expression) pour tout ce que l'appel fait sortir.

    `extra={...}` est OUVERT : ses clés littérales sont les noms de champs, et
    c'est précisément dans un `extra` que dormaient `preview`, `scope` et
    `existing_combos`.
    """
    sortie: list[tuple[str | None, ast.expr]] = []
    for arg in noeud.args:
        sortie.append((None, arg))
    for mot in noeud.keywords:
        if mot.arg == "extra" and isinstance(mot.value, ast.Dict):
            for cle, val in zip(mot.value.keys, mot.value.values):
                nom = cle.value if isinstance(cle, ast.Constant) else None
                sortie.append((nom if isinstance(nom, str) else None, val))
        elif mot.arg in ("exc_info", "stack_info", "stacklevel"):
            continue
        else:
            sortie.append((mot.arg, mot.value))
    return sortie


def _nom_simple(noeud: ast.expr) -> str | None:
    """Le nom de l'expression si c'en est un ; None si elle ne rend rien."""
    if isinstance(noeud, ast.Name):
        return noeud.id
    if isinstance(noeud, ast.Attribute):
        return noeud.attr
    if isinstance(noeud, ast.Subscript):
        cle = noeud.slice
        if isinstance(cle, ast.Constant) and isinstance(cle.value, str):
            return cle.value
        return _nom_simple(noeud.value)
    if isinstance(noeud, ast.Constant):
        return None  # un littéral du source ne vient d'aucune donnée
    if isinstance(noeud, ast.Call):
        nom_appele = _nom_appele(noeud.func)
        # `x.get("backend_pid")` rend `backend_pid`, pas `get` : c'est le CHAMP
        # qui sort, et c'est lui qu'il faut juger.
        if nom_appele == "get" and noeud.args:
            premier = noeud.args[0]
            if isinstance(premier, ast.Constant) and isinstance(premier.value, str):
                return premier.value
        return nom_appele or "<appel>"
    if isinstance(noeud, ast.BinOp):
        return (_nom_simple(noeud.left) or _nom_simple(noeud.right))
    if isinstance(noeud, (ast.BoolOp, ast.IfExp, ast.Compare)):
        for enfant in ast.iter_child_nodes(noeud):
            if isinstance(enfant, ast.expr):
                nom = _nom_simple(enfant)
                if nom:
                    return nom
        return None
    return "<expression>"


def _interpolations(noeud: ast.expr) -> list[ast.expr]:
    """Les valeurs qu'un gabarit de message fait entrer dans le TEXTE.

    Trois formes, et seulement trois, parce que ce sont les trois que ce dépôt
    emploie : la f-string, le `%` de `logging` (les arguments qui suivent le
    gabarit sont traités par l'appelant), et `.format(...)`.
    """
    sortie: list[ast.expr] = []
    if isinstance(noeud, ast.JoinedStr):
        for morceau in noeud.values:
            if isinstance(morceau, ast.FormattedValue):
                sortie.append(morceau.value)
    elif isinstance(noeud, ast.BinOp) and isinstance(noeud.op, ast.Mod):
        droite = noeud.right
        if isinstance(droite, ast.Tuple):
            sortie.extend(droite.elts)
        else:
            sortie.append(droite)
    elif (isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Attribute)
          and noeud.func.attr == "format"):
        sortie.extend(noeud.args)
    return sortie


def _args_pourcent(appel: ast.Call, expr: ast.expr) -> list[ast.expr]:
    """Le `%` DIFFÉRÉ de `logging` : `logger.warning("a=%s", a)`.

    `logging` formate lui-même, plus tard : les arguments qui suivent le
    gabarit entrent dans le TEXTE aussi sûrement qu'une f-string, et c'est la
    forme qu'employaient les trois sites de `cc_v1`.
    """
    if not appel.args or appel.args[0] is not expr:
        return []
    gabarit = appel.args[0]
    if not (isinstance(gabarit, ast.Constant) and isinstance(gabarit.value, str)):
        return []
    if "%" not in gabarit.value:
        return []
    return list(appel.args[1:])


def _cibles_except(arbre: ast.AST) -> set[str]:
    """Les noms liés par un `except ... as X` — les objets exception du module."""
    noms = set(_NOMS_EXCEPTION)
    for n in ast.walk(arbre):
        if isinstance(n, ast.ExceptHandler) and n.name:
            noms.add(n.name)
    return noms


# ---------------------------------------------------------------------------
# L'inventaire
# ---------------------------------------------------------------------------

def inventaire(racine: Path) -> list[Violation]:
    """Toutes les violations des règles G1 à G4, dans le périmètre `ExecStart`."""
    violations: list[Violation] = []

    # --- G1 : le filet est posé sur chaque entrée -------------------------
    for module in entrees_execstart(racine):
        chemin = _chemin(racine, module)
        if chemin is None:
            continue
        source = chemin.read_text(encoding="utf-8", errors="replace")
        if "installer_garde_journal" not in source:
            violations.append(Violation(
                fichier=str(chemin.relative_to(racine)), ligne=1, regle="G1",
                motif=(f"le module d'entrée « {module} » d'un ExecStart n'appelle "
                       "pas installer_garde_journal() : rien n'assainit les traces "
                       "que ce processus enverra dans journald"),
                extrait=f"ExecStart → {module}",
            ))

    # --- G2/G3/G4 : ce que chaque appel de journal peut imprimer ----------
    for chemin in fermeture(racine):
        source = chemin.read_text(encoding="utf-8", errors="replace")
        try:
            arbre = ast.parse(source)
        except SyntaxError:
            continue
        lignes = source.splitlines()
        exceptions = _cibles_except(arbre)
        for noeud in ast.walk(arbre):
            niveau = _appel_de_journal(noeud)
            if niveau is None:
                continue
            extrait = (lignes[noeud.lineno - 1].strip()[:120]
                       if noeud.lineno <= len(lignes) else "")
            rel = str(chemin.relative_to(racine))
            for champ, expr in _arguments_journalises(noeud):
                noms = _noms_non_reduits(expr)
                # G4 — le gabarit nomme un champ de mémoire devant un trou
                for nom in noms:
                    if nom.startswith("§") and _GABARIT_FUITANT.search(nom[1:]):
                        violations.append(Violation(
                            rel, noeud.lineno, "G4",
                            f"gabarit « {_GABARIT_FUITANT.search(nom[1:]).group(0)} »",
                            extrait))
                        break
                # G5 — une valeur INTERPOLÉE dans le TEXTE du message
                #
                # G3 refuse ce que le vocabulaire de la mémoire nomme ; G5
                # refuse ce qu'on n'a pas su nommer. Il est né d'une fuite que
                # G3 ne pouvait pas voir : `_failure(f"scope:{resolved}", exc)`
                # rangeait le domaine dans un champ appelé `where`, mot qui
                # n'est dans aucun vocabulaire — et le journal du cockpit
                # rendait « where=scope:perso/sante » à chaque panne, mesuré.
                #
                # Le texte d'un message part TOUJOURS dans le journal, quel que
                # soit le formateur ; `extra=` non. C'est donc là, et là
                # seulement, qu'on est fermé par défaut : une interpolation doit
                # se DÉMONTRER inoffensive — un réducteur, ou un nom qui porte
                # son contrat (`_sha8`, `_count`, `_id`, `_len`…).
                if champ is None:
                    for expr_interpolee in _interpolations(expr) + _args_pourcent(noeud, expr):
                        if _est_reducteur(expr_interpolee):
                            continue
                        nom = _nom_simple(expr_interpolee)
                        if nom is None or _sur_par_le_nom(nom):
                            continue
                        if nom.lower().strip("_") in VOCABULAIRE_MACHINE \
                                or nom in VOCABULAIRE_MACHINE:
                            continue
                        # Une CONSTANTE de module (tout en majuscules) est
                        # écrite dans le source : elle ne vient d'aucune donnée,
                        # et cela se lit sans liste.
                        if nom.isupper() and nom.isidentifier():
                            continue
                        violations.append(Violation(
                            rel, noeud.lineno, "G5",
                            f"valeur interpolée en clair dans le message : « {nom} »",
                            extrait))

                # G2 — une exception en clair
                fuite_exc = sorted(n for n in noms if n in exceptions)
                if fuite_exc:
                    violations.append(Violation(
                        rel, noeud.lineno, "G2",
                        f"exception en clair : {', '.join(fuite_exc)}", extrait))
                # G3 — un champ de mémoire en clair
                candidats = {champ} if champ else set()
                candidats |= {n for n in noms if not n.startswith("§")}
                fuite_mem = sorted(
                    n for n in candidats
                    if n and n.lower().strip("_") in VOCABULAIRE_MEMOIRE
                    and not _sur_par_le_nom(n)
                )
                if fuite_mem:
                    violations.append(Violation(
                        rel, noeud.lineno, "G3",
                        f"mémoire en clair : {', '.join(fuite_mem)}", extrait))
    return violations
