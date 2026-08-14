"""ARAC — ce qui a le droit d'entrer dans le journal systemd, et ce qui n'en a pas.

POURQUOI CE FICHIER EXISTE
--------------------------
Le journal systemd n'appartient pas au cerveau : il appartient à la MACHINE.
Il est lisible par `root` et par tout compte du groupe `systemd-journal`, il
est conservé des semaines, et la désinstallation ne sait pas le purger unité
par unité — `journalctl --vacuum-*` travaille sur des FICHIERS, et ces
fichiers portent aussi le journal du voisin. La base, elle, est protégée par
des rôles et un coffre en `0700`, et elle part avec le cerveau le jour où il
part. Le journal, non.

Le dépôt écrivait déjà cette règle, trois fois, en toutes lettres :

  - `agents/cortex/dedup_thresholds.key_sha8` — « aucune clé ne doit être
    écrite en clair dans un artefact durable ; sha8 suffit pour corréler deux
    occurrences sans rien révéler » (invariant I5 / règle V0.107) ;
  - `agents/cortex/dispose._sanitize_error_body` — « le candidat complet reste
    disponible pour la revue humaine via la DB, JAMAIS via journald » ;
  - `agents/cortex/cycle._errors_pour_journal` — fermé par défaut : tout ce qui
    suit le premier « : » est haché, SAUF deux formes dont on peut DÉMONTRER
    qu'elles ne portent rien.

Elle n'était appliquée qu'aux endroits où quelqu'un y avait pensé. Ce module
la rend disponible à TOUT le dépôt, et `tests/acceptance/test_le_journal_ne_
retient_aucun_souvenir.py` la rend obligatoire : un contrôle statique refuse
désormais tout appel de journalisation, dans les modules qu'un `ExecStart`
peut atteindre, capable d'imprimer une clé, un domaine, un titre ou un
fragment de souvenir.

UN DOMAINE EST-IL UN SECRET ? OUI.
----------------------------------
La question mérite mieux qu'un réflexe, parce que le domaine est l'axe de
triage naturel d'un exploitant : sans lui, une ligne d'incident perd son
« où ». Elle se tranche pourtant sans hésiter, et voici l'argument.

Un domaine n'est pas un identifiant technique attribué par le produit : c'est
une phrase que le propriétaire du cerveau a ÉCRITE LUI-MÊME pendant
l'entretien d'installation, pour nommer un pan de sa vie. `perso/sante`,
`travail/strategie`, `perso/famille` — la liste des domaines EST le plan de
l'existence de quelqu'un. Elle dit qu'il a une santé qui mérite une case, un
divorce en cours, une entreprise qui prépare quelque chose. Le contenu du
souvenir dit ce qu'il pense ; la taxonomie dit ce qui l'occupe. Le second se
lit plus vite que le premier, et se déduit sans effort d'un simple `grep` sur
un journal partagé.

Le dépôt le disait déjà d'un côté (`ops/uninstall_check.sh` : « il porte les
domaines en clair… c'est la forme de la mémoire de quelqu'un ») et le niait de
l'autre (`dispose.py`, `cc_v1/*.py` : `scope=` en clair). Deux conventions
voisines pour la même question, c'est une convention de moins. Elle est
tranchée ici, une fois : **un domaine ne sort jamais en clair d'un processus
que systemd journalise.**

CE QUE ÇA COÛTE, ET CE QUE ÇA NE COÛTE PAS. L'empreinte est stable : le même
domaine rend toujours la même empreinte, donc « ces quarante incidents portent
tous `d0d5c4a2` » reste lisible, et corréler deux lignes reste possible. Ce
qui se perd, c'est de LIRE le domaine dans le journal — et cela se retrouve en
une requête, du côté où c'est légitime : la base, sous les rôles du cerveau.

LA RÈGLE, EN TROIS LIGNES
-------------------------
1. Fermé par défaut. Une chaîne de caractères qui vient des données est réduite
   à `sha8:<empreinte>/<n caractères>`. On n'entretient pas la liste de ce qui
   serait sensible : une liste oublie, et ce qu'elle oublie est précisément ce
   que personne n'avait imaginé.
2. Ce qui reste en clair doit se DÉMONTRER inoffensif : un nombre, un booléen,
   une empreinte déjà calculée, un UUID engendré par la machine, un littéral
   écrit dans le source.
3. La substance va en base — `arac.audit_log`, `run_receipts`,
   `digestion_review_queue` — jamais dans journald.
"""

from __future__ import annotations

import hashlib
import logging
import re
import traceback
import uuid as _uuid
from typing import Any


# ============================================================================
# 1. L'empreinte
# ============================================================================

_EMPREINTE_HEX = 8


def sha8(valeur: object) -> str:
    """Empreinte sha8 (8 hexadécimaux de sha256) de n'importe quelle valeur.

    Identique, au caractère près, à `agents.cortex.dedup_thresholds.key_sha8`
    (même algorithme, même troncature) : deux occurrences de la même valeur
    rendent la même empreinte, quel que soit le module qui l'écrit. C'est ce
    qui permet de corréler une ligne du cycle et une ligne de l'API sans que
    l'une ni l'autre ne porte la valeur.
    """
    return hashlib.sha256(str(valeur).encode("utf-8")).hexdigest()[:_EMPREINTE_HEX]


def empreinte(valeur: object) -> str:
    """`sha8:<empreinte>/<n>` — l'empreinte ET la longueur du texte d'origine.

    La longueur est rendue parce qu'elle diagnostique sans rien révéler : « le
    rationale fait 85 caractères » est exactement l'information que W-003
    cherche à transmettre, et 85 ne se retourne pas en texte.
    """
    texte = "" if valeur is None else str(valeur)
    return f"sha8:{sha8(texte)}/{len(texte)}"


# Une valeur qui est DÉJÀ une empreinte ne doit pas être hachée une seconde
# fois : un second hachage la rendrait incomparable avec la première.
_DEJA_EMPREINTE = re.compile(r"^(sha8:)?[0-9a-f]{8}(/\d+)?$")
_EMPREINTE_LONGUE = re.compile(r"^[0-9a-f]{32,64}$")


def _est_uuid(texte: str) -> bool:
    """True si `texte` est un UUID — engendré par la machine, jamais saisi.

    Un identifiant d'atome, de session ou de requête est un tirage aléatoire :
    il ne porte aucun mot de personne, et c'est précisément lui qui permet de
    retrouver la ligne complète en base. Il reste donc en clair.
    """
    try:
        _uuid.UUID(texte)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _demontrable_inoffensif(texte: str) -> bool:
    """Les seules formes de chaîne qu'on laisse passer en clair.

    Chacune se DÉMONTRE, elle ne se décrète pas : un nombre est un compte ou un
    plafond ; une empreinte a déjà été calculée en amont ; un UUID vient du
    tirage aléatoire de la machine ; une chaîne vide ne dit rien.
    """
    if not texte:
        return True
    if texte.isdigit():
        return True
    if _DEJA_EMPREINTE.match(texte) or _EMPREINTE_LONGUE.match(texte):
        return True
    if _est_uuid(texte):
        return True
    return False


def reduire(valeur: Any, _profondeur: int = 0) -> Any:
    """Réduit une structure à ce qui peut rester dans le journal. FERMÉ PAR DÉFAUT.

    Les nombres, booléens et `None` passent : ils ne portent pas de mots. Les
    chaînes sont remplacées par leur empreinte, SAUF celles dont
    `_demontrable_inoffensif` établit qu'elles ne portent rien. Les
    dictionnaires gardent leurs CLÉS — ce sont des noms de champs, écrits dans
    le source, pas des données — et réduisent leurs valeurs.

    On ne tient volontairement AUCUNE liste de champs sensibles : c'est ce
    genre de liste qui a laissé passer `preview`, `existing_combos` et
    `scope` pendant huit versions.
    """
    if _profondeur > 6:
        return "…"
    if valeur is None or isinstance(valeur, (bool, int, float)):
        return valeur
    if isinstance(valeur, dict):
        return {
            str(cle): reduire(val, _profondeur + 1)
            for cle, val in list(valeur.items())[:40]
        }
    if isinstance(valeur, (list, tuple, set)):
        return [reduire(val, _profondeur + 1) for val in list(valeur)[:40]]
    texte = str(valeur)
    if _demontrable_inoffensif(texte):
        return texte
    return empreinte(texte)


# ============================================================================
# 2. Les exceptions — garder le TYPE et le LIEU, jamais la valeur
# ============================================================================
#
# `dispose._sanitize_error_body` avait déjà nommé le bon niveau pour un corps
# d'erreur d'API : « on ne conserve que `type` + `loc`, jamais des valeurs ».
# Une exception PostgreSQL demande exactement la même coupe, et elle est plus
# généreuse qu'il n'y paraît : psycopg porte, à côté du message, un DIAGNOSTIC
# structuré (sqlstate, contrainte, table, colonne) qui vient du SCHÉMA — donc
# du dépôt, pas de la mémoire. C'est lui qui dit quoi corriger.
#
# MESURÉ, et c'est ce qui a rendu ce module obligatoire : sur un cerveau vivant,
# un `POST /v1/atoms` qui heurte une contrainte NOT NULL fait rendre à
# PostgreSQL
#     NotNullViolation: null value in column "rationale" of relation "memory_atoms"
#     DETAIL:  Failing row contains (…, perso/sante, temoin-…, <LE SOUVENIR>, …)
# et cette ligne partait TROIS FOIS dans journald : une fois dans le champ
# `exc_info` de `main.request.failed`, deux fois de plus dans la trace que
# uvicorn réimprime pour son compte.

_CHAMPS_DIAG = (
    "sqlstate",
    "constraint_name",
    "table_name",
    "column_name",
    "schema_name",
    "datatype_name",
)


def diagnostic_exception(exc: BaseException) -> dict[str, Any]:
    """Ce qu'on garde d'une exception : son type, son diagnostic, une empreinte.

    Le message n'y est pas — il est remplacé par son empreinte, qui suffit à
    dire « c'est la même erreur qu'il y a dix minutes » sans dire laquelle.
    Pour une erreur psycopg, le diagnostic PostgreSQL est ajouté : ces champs
    viennent du schéma (nom de contrainte, de table, de colonne, code SQLSTATE)
    et non des données, ce qui se vérifie en lisant `db/alembic/versions/`.
    """
    sortie: dict[str, Any] = {
        "type": type(exc).__name__,
        "module": type(exc).__module__,
        "message_sha8": empreinte(str(exc)),
    }
    diag = getattr(exc, "diag", None)
    if diag is not None:
        for champ in _CHAMPS_DIAG:
            val = getattr(diag, champ, None)
            if val:
                sortie[champ] = str(val)
    return sortie


def raison(exc: BaseException) -> str:
    """Ce qu'on écrit d'une exception dans une ligne de journal, en un mot.

    C'est la forme courte de `diagnostic_exception`, destinée aux `error=…` qui
    peuplent le dépôt. Elle remplace `f"{type(e).__name__}: {e}"`, qui gardait
    le message ENTIER — et le message est justement l'endroit où PostgreSQL
    range la ligne fautive.

    CE QU'ON PERD, ET CE QU'ON NE PERD PAS. On perd la phrase anglaise de la
    bibliothèque. On ne perd presque rien du diagnostic : pour une panne de
    réseau ou de format, la CLASSE est la raison (`ConnectTimeout`,
    `JSONDecodeError`, `ModuleNotFoundError`) ; pour une erreur PostgreSQL —
    la seule qui puisse porter un souvenir — on rend en plus le SQLSTATE, la
    contrainte, la table et la colonne, qui sortent du schéma et disent quoi
    corriger bien mieux que la prose. Et l'empreinte reste : deux lignes qui
    portent la même empreinte portent la même erreur.

    Exemple mesuré, avant / après :
        NotNullViolation: null value in column "rationale" of relation
        "memory_atoms" DETAIL:  Failing row contains (…, perso/sante,
        temoin-…, <LE SOUVENIR>, …)
        →  NotNullViolation[23502 memory_atoms.rationale] sha8:1f0c9a2b/412
    """
    diag = getattr(exc, "diag", None)
    details: list[str] = []
    if diag is not None:
        etat = getattr(diag, "sqlstate", None)
        if etat:
            details.append(str(etat))
        table = getattr(diag, "table_name", None)
        colonne = getattr(diag, "column_name", None)
        if table and colonne:
            details.append(f"{table}.{colonne}")
        elif table:
            details.append(str(table))
        contrainte = getattr(diag, "constraint_name", None)
        if contrainte:
            details.append(str(contrainte))
    tete = type(exc).__name__
    if details:
        tete += "[" + " ".join(details) + "]"
    return f"{tete} {empreinte(str(exc))}"


def _empreinter_traceback(te: traceback.TracebackException, vus: set[int]) -> None:
    """Remplace, en place et récursivement, le MESSAGE de chaque exception.

    Les CADRES de la trace (fichier, ligne, fonction) sont conservés tels
    quels : ce sont des coordonnées de code, elles vivent déjà dans le dépôt et
    n'ont jamais porté un mot de personne. Seule la dernière ligne de chaque
    bloc — `Type: message` — est réécrite. Les chaînes `__cause__` /
    `__context__` et les groupes d'exceptions sont suivis, parce que c'est
    exactement par là que la trace mesurée faisait sortir le souvenir trois
    fois.
    """
    if id(te) in vus:
        return
    vus.add(id(te))
    try:
        te._str = empreinte(getattr(te, "_str", ""))  # noqa: SLF001
    except Exception:  # noqa: BLE001 — le journal ne doit JAMAIS lever
        pass
    # Les notes (`__notes__`, PEP 678) sont du texte libre attaché par
    # l'appelant : rien ne garantit qu'il ne porte pas une valeur.
    if getattr(te, "__notes__", None):
        try:
            te.__notes__ = [empreinte(n) for n in te.__notes__]
        except Exception:  # noqa: BLE001
            te.__notes__ = None
    for enfant in (getattr(te, "__cause__", None), getattr(te, "__context__", None)):
        if enfant is not None:
            _empreinter_traceback(enfant, vus)
    for enfant in getattr(te, "exceptions", None) or ():
        _empreinter_traceback(enfant, vus)


def trace_assainie(exc_info: Any) -> str:
    """La trace COMPLÈTE — cadres compris — dont les messages sont empreintés.

    Retirer la trace serait pire que la fuite : c'est le seul canal de
    dépannage de l'API, et un incident sans trace se paie en heures. On garde
    donc tout ce qui aide (où, dans quel ordre, quelle classe d'erreur) et on
    retire la seule chose qui puisse porter un souvenir.
    """
    if not exc_info or exc_info is True:
        return ""
    if isinstance(exc_info, BaseException):
        exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
    try:
        te = traceback.TracebackException(*exc_info)
    except Exception:  # noqa: BLE001
        return "<trace illisible — assainie>"
    _empreinter_traceback(te, set())
    try:
        texte = "".join(te.format())
    except Exception:  # noqa: BLE001
        return "<trace illisible — assainie>"
    diag = diagnostic_exception(exc_info[1]) if exc_info[1] is not None else {}
    extra = " ".join(f"{k}={v}" for k, v in diag.items() if k not in ("type", "module"))
    return texte + (f"\ndiagnostic : {extra}\n" if extra else "")


# ============================================================================
# 3. Le filet — un filtre posé sur TOUS les journaux du processus
# ============================================================================
#
# Les corrections site par site ferment les fuites qu'on a trouvées. Ce filtre
# ferme celles qu'on n'a pas trouvées, et surtout celles qu'on n'écrit pas
# nous-mêmes : la trace mesurée sortait aussi par le journaliseur d'uvicorn,
# qui n'appartient pas à ce dépôt et qu'aucune relecture de `app/` n'aurait
# corrigé.

# Les formes par lesquelles PostgreSQL rend une ligne de mémoire dans un
# message d'erreur. Ce n'est pas la défense principale — la défense principale
# est l'empreinte des messages d'exception ci-dessus — c'est la ceinture qui
# accompagne les bretelles, pour le cas où un message serait recopié à la main
# dans une chaîne de caractères ordinaire.
_FORMES_PG: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"DETAIL:\s*Failing row contains \((?:[^()]|\([^()]*\))*\)\.?"),
        "DETAIL: Failing row contains (…) [assaini]",
    ),
    (
        re.compile(r"Key \(([^)]*)\)=\((?:[^()]|\([^()]*\))*\)"),
        r"Key (\1)=(…) [assaini]",
    ),
    (
        re.compile(r"DETAIL:\s*Key \(([^)]*)\)=\((?:[^()]|\([^()]*\))*\)"),
        r"DETAIL: Key (\1)=(…) [assaini]",
    ),
)


def assainir_texte(texte: str) -> str:
    """Retire d'un texte libre les formes par lesquelles PostgreSQL rend une ligne.

    Idempotent : `[assaini]` ne réapparaît dans aucun motif.
    """
    if not texte:
        return texte
    if "Failing row contains" not in texte and "Key (" not in texte:
        return texte
    for motif, remplacement in _FORMES_PG:
        texte = motif.sub(remplacement, texte)
    return texte


class FiltreMemoire(logging.Filter):
    """Le garde posé sur la sortie : aucune trace, aucun message ne part entier.

    Il fait DEUX choses, et rien d'autre :
      1. il remplace la trace d'exception par sa version empreintée
         (`trace_assainie`) — c'est ce qui ferme le canal mesuré ;
      2. il assainit le texte du message des formes `Failing row contains` /
         `Key (…)=(…)`, au cas où quelqu'un aurait recopié un message d'erreur
         dans une chaîne à la main.

    Il ne juge PAS le contenu métier des lignes : ce travail-là appartient au
    contrôle statique (`tests/acceptance/test_le_journal_ne_retient_aucun_
    souvenir.py`), qui refuse à la compilation ce qu'un filtre ne saurait
    reconnaître à l'exécution. Un filtre qui prétendrait deviner qu'une chaîne
    est un domaine se tromperait dans les deux sens.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            if record.exc_info:
                record.exc_text = trace_assainie(record.exc_info)
                record.exc_info = None
            elif getattr(record, "exc_text", None):
                record.exc_text = assainir_texte(record.exc_text)
            if isinstance(record.msg, str) and (
                "Failing row contains" in record.msg or "Key (" in record.msg
            ):
                record.msg = assainir_texte(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: assainir_texte(v) if isinstance(v, str) else v
                        for k, v in record.args.items()
                    }
                elif isinstance(record.args, tuple):
                    record.args = tuple(
                        assainir_texte(a) if isinstance(a, str) else a
                        for a in record.args
                    )
        except Exception:  # noqa: BLE001 — journaliser ne doit jamais lever
            record.exc_info = None
            record.exc_text = "<trace retirée — le garde du journal a échoué>"
        return True


_FILTRE = FiltreMemoire()


_FABRIQUE_POSEE = False


def installer_garde_journal() -> int:
    """Assainit CHAQUE ligne du processus, à la source : la FABRIQUE de lignes.

    POURQUOI PAS UN FILTRE POSÉ SUR LES JOURNALISEURS. C'est ce qu'on avait
    écrit d'abord, et c'était FAUX — mesuré sur le cockpit du banc : la ligne
    `cc_v1.entities_failed` sortait avec sa trace ENTIÈRE, message compris,
    alors que le filtre était bien posé au démarrage. Trois raisons, toutes
    mécaniques, et chacune suffit :

      · un filtre posé sur un journaliseur ne voit QUE les lignes émises sur
        lui — pas celles qu'il reçoit par propagation ;
      · un filtre posé sur un collecteur ne voit que ce qui atteint CE
        collecteur — et quand aucun n'est configuré, Python sert la ligne par
        `logging.lastResort`, qui n'appartient à personne ;
      · surtout, on ne peut poser un filtre que sur ce qui EXISTE DÉJÀ. Les
        journaliseurs de `control_center/cc_v1/*` naissent au chargement
        paresseux des familles, longtemps après le démarrage. Un garde qui
        énumère à un instant donné garde cet instant.

    LA FABRIQUE, ELLE, EST UNIQUE ET ANTÉRIEURE À TOUT. `logging` construit
    chaque `LogRecord` par `logging.getLogRecordFactory()`. En l'enveloppant,
    on tient toutes les lignes — celles d'ARAC, celles d'uvicorn, celles d'une
    bibliothèque qu'on n'a pas lue, celles d'un module qui n'existe pas encore
    — et on les tient AVANT qu'un seul collecteur ne les voie.

    Le filtre reste posé en plus, sur ce qui existe : deux barrières valent
    mieux qu'une sur le seul chemin qui a déjà fui.

    Idempotent. Retourne le nombre de points d'ancrage posés, ce qui rend le
    geste MESURABLE plutôt que promis.
    """
    global _FABRIQUE_POSEE
    poses = 0

    if not _FABRIQUE_POSEE:
        fabrique_precedente = logging.getLogRecordFactory()

        def fabrique_assainie(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = fabrique_precedente(*args, **kwargs)
            _FILTRE.filter(record)
            return record

        fabrique_assainie.arac_garde_journal = True  # type: ignore[attr-defined]
        logging.setLogRecordFactory(fabrique_assainie)
        _FABRIQUE_POSEE = True
        poses += 1

    cibles: list[logging.Logger] = [logging.getLogger()]
    for nom in list(logging.root.manager.loggerDict):
        objet = logging.root.manager.loggerDict.get(nom)
        if isinstance(objet, logging.Logger):
            cibles.append(objet)
    for journaliseur in cibles:
        if _FILTRE not in journaliseur.filters:
            journaliseur.addFilter(_FILTRE)
            poses += 1
        for collecteur in list(journaliseur.handlers):
            if _FILTRE not in collecteur.filters:
                collecteur.addFilter(_FILTRE)
                poses += 1
    if _FILTRE not in logging.lastResort.filters:
        # Le collecteur de dernier recours : celui qui a servi la trace du
        # cockpit, parce qu'aucun autre n'était configuré.
        logging.lastResort.addFilter(_FILTRE)
        poses += 1
    return poses
