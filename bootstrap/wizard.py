#!/usr/bin/env python3
"""wizard.py — l'entretien qui donne naissance à un cerveau.

Ce n'est pas un formulaire de configuration. C'est le moment où quelqu'un
décide de la forme de sa propre mémoire, et où ARAC cesse d'être le cerveau
de son auteur pour devenir le sien.

Trois principes tiennent tout ce fichier.

**Rien n'est écrit sans être compris.** Chaque question dit pourquoi elle est
posée et ce que la réponse engage. Une taxonomie choisie au hasard produit un
cerveau qui range mal, et personne ne s'en aperçoit avant six mois.

**Rien n'est décidé à la place de l'utilisateur.** L'assistant propose des
domaines courants, jamais les domaines de quelqu'un d'autre. Les exemples sont
génériques et le disent : le cerveau de référence avait fini avec le nom d'une
boutique, d'un village et d'une compagne, et c'est très bien — mais c'était le
sien.

**Rien n'est irréversible sans avertissement.** L'assistant montre ce qu'il
s'apprête à écrire avant de l'écrire, et ne touche jamais à une base existante
sans dire ce qu'elle contient déjà.

Usage :
    python3 bootstrap/wizard.py                  entretien complet
    python3 bootstrap/wizard.py --resume         reprend un entretien interrompu
    python3 bootstrap/wizard.py --check          constate les prérequis, puis sort

Il n'existe PAS de mode non interactif, et cette ligne remplace celle qui en
documentait un : `--non-interactif --profil profils/exemple.toml` n'a jamais
existé ici — ni les deux options, ni le répertoire. Une invocation documentée
qui rend « unrecognized arguments » coûte à celui qui la recopie exactement ce
qu'un mode d'emploi est censé lui épargner.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import uuid as _uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parent.parent
ETAT = RACINE / ".bootstrap-state.json"

# ---------------------------------------------------------------------------
# Présentation — un terminal lisible, sans dépendance
# ---------------------------------------------------------------------------

_COULEUR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, texte: str) -> str:
    return f"\033[{code}m{texte}\033[0m" if _COULEUR else texte


def titre(t: str) -> None:
    print()
    print(_c("1", "  " + t))
    print(_c("2", "  " + "─" * (len(t) + 2)))


def dire(t: str = "", indent: int = 2) -> None:
    print(" " * indent + t)


def note(t: str) -> None:
    for ligne in t.split("\n"):
        print(_c("2", "  " + ligne))


def alerte(t: str) -> None:
    print(_c("33", "  ⚠  " + t))


def bien(t: str) -> None:
    print(_c("32", "  ✓  " + t))


def mal(t: str) -> None:
    print(_c("31", "  ✗  " + t))


# ---------------------------------------------------------------------------
# Saisie
# ---------------------------------------------------------------------------


def demander(question: str, defaut: str | None = None, valider=None) -> str:
    """Pose une question jusqu'à obtenir une réponse acceptable."""
    suffixe = f" [{defaut}]" if defaut else ""
    while True:
        try:
            rep = input(_c("36", f"  {question}{suffixe} ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            note("Entretien interrompu. Rien n'a été écrit.")
            note("Reprenez quand vous voulez : python3 bootstrap/wizard.py --resume")
            raise SystemExit(130)
        if not rep and defaut is not None:
            rep = defaut
        if not rep:
            mal("Une réponse est nécessaire.")
            continue
        if valider:
            souci = valider(rep)
            if souci:
                mal(souci)
                continue
        return rep


def oui_non(question: str, defaut: bool = True) -> bool:
    d = "O/n" if defaut else "o/N"
    while True:
        rep = demander(f"{question} ({d})", "o" if defaut else "n").lower()
        if rep in ("o", "oui", "y", "yes"):
            return True
        if rep in ("n", "non", "no"):
            return False
        mal("Répondez par o (oui) ou n (non).")


def slug(texte: str) -> str:
    sans_accent = "".join(
        c for c in unicodedata.normalize("NFD", texte) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9]+", "-", sans_accent.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)


def _cle_valide(v: str) -> str | None:
    if not re.match(r"^[a-z][a-z0-9-]*$", slug(v) or ""):
        return "Ce nom ne peut pas devenir un identifiant. Essayez des lettres simples."
    return None


# ---------------------------------------------------------------------------
# Ce que l'assistant construit
# ---------------------------------------------------------------------------


@dataclass
class Cerveau:
    proprietaire: str = ""
    nom: str = ""
    node_id: str = ""
    #: L'empreinte de CETTE installation. Voir `empreinte_installation`.
    uuid: str = ""
    racines: list[dict] = field(default_factory=list)
    feuilles: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"proprietaire": self.proprietaire, "nom": self.nom, "node_id": self.node_id,
                "uuid": self.uuid, "racines": self.racines, "feuilles": self.feuilles}


#: Domaines PROPOSÉS — jamais imposés, et volontairement génériques.
#: Ce ne sont pas les domaines de l'auteur : ce sont les catégories qui
#: reviennent le plus souvent quand on demande à quelqu'un de découper sa vie.
SUGGESTIONS: tuple[tuple[str, str, str, tuple[tuple[str, str], ...]], ...] = (
    ("travail", "TRAVAIL", "Votre activité professionnelle principale.",
     (("strategie", "Stratégie"), ("operations", "Opérations"), ("finance", "Finance"))),
    ("entreprise", "ENTREPRISE", "Une société que vous dirigez ou dans laquelle vous êtes engagé.",
     (("produits", "Produits"), ("clients", "Clients"), ("finance", "Finance"))),
    ("projets", "PROJETS", "Les chantiers qui ont un début et une fin.",
     (("en-cours", "En cours"), ("archives", "Archivés"))),
    ("perso", "PERSONNEL", "Votre vie privée : lieux, personnes, administratif.",
     (("logement", "Logement"), ("administratif", "Administratif"), ("sante", "Santé"))),
    ("famille", "FAMILLE", "Les personnes qui comptent et ce qui les concerne.",
     (("proches", "Proches"), ("organisation", "Organisation"))),
    ("finance", "FINANCE", "Patrimoine, investissements, fiscalité.",
     (("patrimoine", "Patrimoine"), ("fiscalite", "Fiscalité"))),
    ("sante", "SANTÉ", "Suivi médical, praticiens, décisions.",
     (("suivi", "Suivi"), ("praticiens", "Praticiens"))),
    ("etudes", "ÉTUDES", "Ce que vous apprenez formellement.",
     (("cours", "Cours"), ("travaux", "Travaux"))),
    ("loisirs", "LOISIRS", "Ce que vous faites pour le plaisir.",
     (("pratiques", "Pratiques"), ("envies", "Envies"))),
    ("outillage", "OUTILLAGE", "Vos outils, votre infrastructure, vos automatisations.",
     (("infrastructure", "Infrastructure"), ("automatisations", "Automatisations"),
      ("assistants", "Assistants"))),
    ("savoir", "SAVOIR", "Lectures, idées, apprentissages transverses.",
     (("apprentissages", "Apprentissages"), ("references", "Références"), ("idees", "Idées"))),
)


# ---------------------------------------------------------------------------
# Les étapes de l'entretien
# ---------------------------------------------------------------------------


def accueil() -> None:
    print()
    print(_c("1", "  ARAC — création de votre cerveau"))
    print()
    note("Vous n'installez pas un logiciel de notes.")
    note("Vous créez une mémoire qui va lire vos conversations, en extraire ce")
    note("qui compte, et vous le rendre quand vous en aurez besoin — sans que")
    note("vous ayez à ranger quoi que ce soit.")
    print()
    note("Cet entretien dure environ cinq minutes. Il décide de deux choses :")
    note("  · le nom et l'identité de votre cerveau ;")
    note("  · la forme de sa mémoire — les domaines dans lesquels il rangera.")
    print()
    note("La seconde est la plus importante. Prenez le temps.")
    note("Rien n'est écrit avant la dernière étape, et tout vous sera montré.")
    print()


def identite(c: Cerveau) -> None:
    titre("1 / 4 — À qui appartient ce cerveau ?")
    note("Votre prénom sert à deux choses : le cockpit vous salue, et le cerveau")
    note("sait distinguer ce que VOUS avez dit de ce qu'un agent a produit.")
    print()
    c.proprietaire = demander("Votre prénom ?")

    print()
    note("Le nom du cerveau apparaît dans le cockpit et identifie sa base de")
    note("données. Beaucoup gardent « arac » ; certains le baptisent.")
    print()
    defaut = slug(c.proprietaire) + "-brain"
    c.nom = slug(demander("Le nom de votre cerveau ?", defaut, _cle_valide))

    print()
    note("Enfin, un identifiant pour la machine depuis laquelle vous parlerez à")
    note("Claude — votre Mac, en général. Le cerveau s'en sert pour savoir d'où")
    note("vient chaque conversation, et pour refuser celles d'une source inconnue.")
    print()
    # Le défaut ne dérive PAS du nom de la machine qui pose la question.
    # Cet entretien tourne sur le SERVEUR ; ce qu'on nomme ici, c'est le POSTE.
    # Le nom d'hôte du serveur n'est donc jamais la bonne réponse — et sur la
    # machine où ce framework a été écrit, il valait le nom du cerveau
    # d'origine, qui se retrouvait recopié dans le config/brain.toml de tout
    # le monde, puis affiché par `make doctor`. Un défaut faux ET fuyant.
    c.node_id = slug(demander("Identifiant de votre poste ?",
                              f"{slug(c.proprietaire)}-poste", _cle_valide))
    print()
    bien(f"Le cerveau de {c.proprietaire}, nommé « {c.nom} », alimenté depuis « {c.node_id} ».")


def _leçon_taxonomie() -> None:
    note("Un mot sur ce qui va suivre, parce que c'est la décision structurante.")
    print()
    note("Votre cerveau range chaque savoir dans un DOMAINE. Ces domaines ont")
    note("deux niveaux : des RACINES — les grands mondes de votre vie — et des")
    note("FEUILLES — les rangements réels.")
    print()
    note("  travail/              ← racine : un conteneur")
    note("  travail/strategie     ← feuille : c'est ICI que les souvenirs vivent")
    print()
    alerte("Un souvenir posé sur une RACINE devient orphelin. Il reste en base, et")
    note("     une question qui lui ressemble peut encore le faire remonter par")
    note("     similarité pure — mais il est exclu de tout ce que votre cerveau")
    note("     construit au-dessus du rangement : pas d'état courant, pas de place")
    note("     dans la vue des scopes, pas de comptage dans la couverture. Et une")
    note("     recherche qui précise un domaine ne le trouvera jamais, l'égalité de")
    note("     scope étant stricte : demander « travail/finance » ne rend pas un")
    note("     souvenir rangé sur « travail ».")
    print()
    note("Sur le cerveau de référence, près d'un souvenir actif sur onze est tombé")
    note("dans ce piège et n'en est jamais ressorti de lui-même. Le compte du jour et")
    note("la requête qui le donne sont dans docs/COMMENT-IL-CREE-SES-SCOPES.md, § 3 —")
    note("un seul endroit, pour qu'aucune copie ne puisse diverger.")
    print()
    note("C'est pour cela que l'assistant vous fera toujours choisir des feuilles.")
    print()
    note("Cinq à huit racines suffisent presque toujours. Une feuille qui n'atteint")
    note("pas dix souvenirs en six mois n'aurait pas dû exister ; une feuille qui")
    note("dépasse deux cent cinquante gagnerait à être scindée. Vous pourrez")
    note("ajuster plus tard — mais déplacer des souvenirs coûte, alors autant")
    note("réfléchir maintenant.")
    print()


def taxonomie(c: Cerveau) -> None:
    titre("2 / 4 — Quels grands domaines composent votre vie ?")
    _leçon_taxonomie()

    dire("Domaines couramment retenus :")
    print()
    for i, (cle, label, desc, _) in enumerate(SUGGESTIONS, 1):
        dire(f"{i:>2}. {_c('1', label):<24} {_c('2', desc)}")
    print()
    note("Indiquez les numéros qui vous parlent, séparés par des espaces.")
    note("Vous pourrez en ajouter d'autres, à vous, juste après.")
    print()

    choisis: list[tuple] = []
    while not choisis:
        rep = demander("Vos domaines ?", "1 4 10 11")
        for tok in re.split(r"[\s,]+", rep):
            if tok.isdigit() and 1 <= int(tok) <= len(SUGGESTIONS):
                s = SUGGESTIONS[int(tok) - 1]
                if s not in choisis:
                    choisis.append(s)
        if not choisis:
            mal("Aucun numéro reconnu. Exemple : 1 4 10")

    print()
    while oui_non("Ajouter un domaine qui n'est pas dans la liste ?", defaut=False):
        nom = demander("  Son nom (ex. « Immobilier », « Musique ») ?", valider=_cle_valide)
        desc = demander("  En une phrase, à quoi sert ce domaine ?")
        choisis.append((slug(nom), nom.upper(), desc, ()))
        bien(f"Domaine ajouté : {nom.upper()}")
        print()

    for cle, label, desc, feuilles_sug in choisis:
        c.racines.append({"key": cle, "label": label, "description": desc})

    titre("3 / 4 — Dans chaque domaine, quels rangements ?")
    note("Pour chaque domaine, choisissez ses feuilles — les rangements réels.")
    note("Des propositions vous sont faites ; gardez, retirez, ajoutez.")
    print()

    for cle, label, desc, feuilles_sug in choisis:
        dire(_c("1", f"── {label}"))
        note(f"   {desc}")
        print()
        retenues: list[tuple[str, str]] = []
        if feuilles_sug:
            for i, (fk, fl) in enumerate(feuilles_sug, 1):
                dire(f"   {i}. {fl}")
            print()
            rep = demander(f"   Rangements pour {label} ?",
                           " ".join(str(i) for i in range(1, len(feuilles_sug) + 1)))
            for tok in re.split(r"[\s,]+", rep):
                if tok.isdigit() and 1 <= int(tok) <= len(feuilles_sug):
                    retenues.append(feuilles_sug[int(tok) - 1])
        while oui_non(f"   Ajouter un rangement à {label} ?", defaut=not retenues):
            n = demander("     Son nom ?", valider=_cle_valide)
            retenues.append((slug(n), n.capitalize()))
        if not retenues:
            alerte(f"   {label} n'a aucun rangement : rien ne pourra y être retenu.")
            n = demander(f"     Donnez-lui au moins un rangement", "general", _cle_valide)
            retenues.append((slug(n), n.capitalize()))
        for fk, fl in retenues:
            c.feuilles.append({"root": cle, "key": fk, "label": fl,
                               "description": f"{fl} — {desc}"})
        bien(f"   {label} : {len(retenues)} rangement(s)")
        print()


def recapitulatif(c: Cerveau) -> bool:
    titre("4 / 4 — Voici le cerveau que je m'apprête à créer")
    dire(f"Propriétaire : {_c('1', c.proprietaire)}")
    dire(f"Nom          : {_c('1', c.nom)}")
    dire(f"Poste source : {_c('1', c.node_id)}")
    print()
    dire(f"Taxonomie    : {len(c.racines)} domaines, {len(c.feuilles)} rangements")
    print()
    for r in c.racines:
        dire(f"  {_c('1', r['label'])}")
        for f in c.feuilles:
            if f["root"] == r["key"]:
                dire(f"     {r['key']}/{f['key']}", indent=4)
    print()
    note("Ces chemins sont ceux que votre cerveau utilisera pour toujours ranger")
    note("ce qu'il apprend. Les modifier plus tard est possible, mais suppose de")
    note("déplacer les souvenirs déjà rangés.")
    print()
    return oui_non("Créer ce cerveau ?", defaut=True)


# ---------------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------------


def ecrire(c: Cerveau) -> list[Path] :
    ecrits: list[Path] = []
    conf = RACINE / "config"
    conf.mkdir(exist_ok=True)

    scopes = conf / "scopes.toml"
    lignes = [
        "# Taxonomie générée par l'assistant d'installation.",
        f"# Cerveau : {c.nom} — propriétaire : {c.proprietaire}",
        "#",
        "# Ce fichier est LA source de vérité de la forme de votre mémoire.",
        "# Après modification :  ./bootstrap/bootstrap.sh --scopes-only",
        "#",
        "# Rappel : les souvenirs vivent sur les FEUILLES. Une racine est un",
        "# conteneur, pas un rangement. Un souvenir posé dessus devient orphelin :",
        "# la similarité pure peut encore le faire remonter, mais il sort de l'état",
        "# courant, de la vue des scopes et de la couverture — et une recherche qui",
        "# précise un domaine ne le trouvera jamais, l'égalité de scope étant",
        "# stricte.",
        "",
        "[taxonomy]",
        "max_depth = 2",
        'label_language = "fr"',
        "",
    ]
    for r in c.racines:
        lignes += ["[[root]]", f'key = "{r["key"]}"', f'label = "{r["label"]}"',
                   f'description = "{r["description"]}"', ""]
    for f in c.feuilles:
        lignes += ["[[leaf]]", f'root = "{f["root"]}"', f'key = "{f["key"]}"',
                   f'label = "{f["label"]}"', f'description = "{f["description"]}"', ""]
    scopes.write_text("\n".join(lignes), encoding="utf-8")
    ecrits.append(scopes)

    identite_f = conf / "brain.toml"
    empreinte = empreinte_installation(identite_f, c.uuid)
    c.uuid = empreinte
    identite_f.write_text("\n".join([
        "# Identité de ce cerveau. Écrit par l'assistant d'installation.",
        "",
        "[brain]",
        f'owner = "{c.proprietaire}"',
        f'name = "{c.nom}"',
        "# L'EMPREINTE DE CETTE INSTALLATION — à ne pas modifier, à ne pas recopier.",
        "#",
        "# Le nom d'un cerveau n'est pas une identité : « perso », « test », le",
        "# prénom de son propriétaire, sont les noms que tout le monde choisit.",
        "# Deux personnes qui choisissent le même sur la même machine dérivent",
        "# alors LES MÊMES noms de base, de rôles, d'unités et de coffre — et la",
        "# seconde installation est reçue comme une réinstallation de la",
        "# première, dont elle reprend les secrets.",
        "#",
        "# Cette valeur, elle, n'a été choisie par personne. C'est elle que le",
        "# bootstrap grave sur les rôles PostgreSQL et qu'il vérifie avant de",
        "# rouvrir un coffre existant. La perdre n'efface rien : elle est aussi",
        "# écrite dans le fichier d'environnement de ce cerveau, et le refus",
        "# vous dira où la relire.",
        f'uuid = "{empreinte}"',
        "",
        "[source]",
        "# Le poste depuis lequel les conversations arrivent. Le cerveau refuse",
        "# les conversations d'un identifiant non déclaré ici — c'est ce qui",
        "# l'empêche d'avaler n'importe quoi.",
        f'node_id = "{c.node_id}"',
        "",
    ]), encoding="utf-8")
    ecrits.append(identite_f)
    return ecrits


#: L'empreinte se lit AVANT de s'engendrer.
#:
#: Rejouer l'entretien sur une installation existante ne doit pas produire une
#: nouvelle empreinte : ce serait s'exclure soi-même de son propre cerveau, au
#: geste même que la documentation recommande quand on s'est trompé de
#: taxonomie. L'ordre est donc : ce que porte déjà le fichier, puis ce que
#: porte l'état de l'entretien en cours, puis — et seulement alors — du neuf.
_MOTIF_UUID = re.compile(r'^\s*uuid\s*=\s*"([A-Za-z0-9][A-Za-z0-9_.-]{7,63})"\s*$', re.M)


def empreinte_installation(identite_f: Path, en_cours: str = "") -> str:
    if identite_f.exists():
        m = _MOTIF_UUID.search(identite_f.read_text(encoding="utf-8", errors="replace"))
        if m:
            return m.group(1)
    return en_cours or _uuid.uuid4().hex


def sauver_etat(c: Cerveau) -> None:
    ETAT.write_text(json.dumps(c.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def charger_etat() -> Cerveau | None:
    if not ETAT.exists():
        return None
    try:
        d = json.loads(ETAT.read_text(encoding="utf-8"))
        return Cerveau(**d)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Prérequis — dits avant d'être exigés
# ---------------------------------------------------------------------------


def prerequis() -> list[tuple[str, bool, str]]:
    """Ce qu'il faut, et si c'est là. N'installe rien : constate et explique."""
    res: list[tuple[str, bool, str]] = []
    v = sys.version_info
    res.append(("Python ≥ 3.11", v >= (3, 11),
                f"trouvé {v.major}.{v.minor} — ARAC utilise tomllib, apparu en 3.11"))
    for outil, pourquoi in (
        ("psql", "parler à PostgreSQL, et rejouer vous-même les preuves du cockpit"),
        ("git", "récupérer et mettre à jour le framework"),
        ("ssh", "relier votre Mac au serveur (le pont qui apporte les conversations)"),
    ):
        res.append((outil, shutil.which(outil) is not None, pourquoi))
    return res


def afficher_prerequis() -> bool:
    titre("Avant de commencer — ce dont votre cerveau a besoin")
    tout = True
    for nom, present, pourquoi in prerequis():
        (bien if present else mal)(f"{nom:<16} {_c('2', pourquoi)}")
        tout = tout and present
    print()
    if not tout:
        alerte("Il manque au moins un prérequis.")
        note("L'entretien peut continuer — rien ne sera installé maintenant —")
        note("mais l'installation elle-même échouera tant qu'ils ne sont pas là.")
        note("Voir docs/INSTALLATION.md, section « Prérequis ».")
        print()
    return tout


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# LA SEULE CHOSE QUE CET ÉCRAN NE DISAIT PAS, ET C'EST CELLE QUI NE SE RATTRAPE PAS
# ---------------------------------------------------------------------------
#
# Cet écran est le dernier avant le geste, et le seul que personne ne saute.
# Il imprimait `sudo ./bootstrap/bootstrap.sh` nu, et le mot « port » n'existait
# nulle part dans ce fichier — sur une machine qui porte déjà un cerveau, cette
# ligne s'adresse à la grappe du voisin.
#
# `docs/INSTALLATION.md` §12.f l'écrit : `ARAC_DB_PORT` est la SEULE chose qui
# transmette ce choix, et le bootstrap REFUSE (code 6) d'en changer une fois le
# port retenu dans le coffre. Déplacer un cerveau d'une grappe à une autre est
# une migration de données, jamais un réglage.
#
# ET ON NE LE DIT PAS TOUT LE TEMPS. Un bon conseil au mauvais moment ne vaut
# pas mieux qu'un mauvais conseil : sur une machine vierge, l'avertissement
# complet ferait croire à une difficulté qui n'existe pas. On regarde donc si
# un cerveau est déjà là — par les NOMS de `/etc/arac/`, jamais par le contenu
# d'un coffre : chaque dossier y est en 0700 et n'appartient qu'à son cerveau.

_RACINE_COFFRES = Path("/etc/arac")


def _cerveaux_deja_sur_cette_machine() -> list[str]:
    """Les noms des cerveaux déjà installés ici. Jamais leur contenu."""
    try:
        return sorted(d.name for d in _RACINE_COFFRES.iterdir() if d.is_dir())
    except OSError:
        return []


def _dire_la_grappe() -> None:
    voisins = _cerveaux_deja_sur_cette_machine()
    if not voisins:
        note("Si un jour cette machine porte un SECOND cerveau, donnez-lui sa propre")
        note("grappe PostgreSQL au moment de l'installer : c'est le seul instant où le")
        note("choix est gratuit (docs/INSTALLATION.md §12.f).")
        print()
        return
    # LE NOMBRE, PAS LES NOMS. Le nom d'un cerveau appartient à son
    # propriétaire ; cet écran s'adresse à quelqu'un d'autre. Le compte suffit
    # à motiver le conseil, et `_annoncer_cluster` nommera, lui, ceux qui
    # partagent VRAIMENT la grappe visée — là, c'est un renseignement dû.
    alerte(f"CETTE MACHINE PORTE DÉJÀ {len(voisins)} CERVEAU(X) ARAC.")
    note("La ligne ci-dessus, telle quelle, installera le vôtre sur la grappe")
    note("PostgreSQL par DÉFAUT de la machine — celle où vivent déjà ces cerveaux-là.")
    note("Ce n'est plus destructeur, mais c'est le DERNIER moment où le choix est")
    note("gratuit : une fois le port retenu dans le coffre, le bootstrap REFUSE")
    note("(code 6) d'en changer, et l'y déplacer serait une migration de données.")
    print()
    dire("Pour lui donner la sienne :")
    dire(_c("36", "   sudo pg_createcluster 16 <nom> --port <port> --start"))
    dire(_c("36", "   sudo ARAC_DB_PORT=<port> ./bootstrap/bootstrap.sh"))
    print()
    note("ARAC_DB_PORT est la SEULE chose qui transmette ce choix : omise, elle vaut")
    note("la grappe par défaut. Le raisonnement complet est au §12.f de")
    note("docs/INSTALLATION.md.")
    print()


def main() -> int:
    p = argparse.ArgumentParser(description="Assistant de création d'un cerveau ARAC.")
    p.add_argument("--resume", action="store_true", help="reprend un entretien interrompu")
    p.add_argument("--check", action="store_true", help="vérifie les prérequis et sort")
    args = p.parse_args()

    if args.check:
        return 0 if afficher_prerequis() else 1

    accueil()
    afficher_prerequis()

    c = charger_etat() if args.resume else None
    if c:
        bien(f"Entretien repris : cerveau « {c.nom} » de {c.proprietaire}.")
    else:
        c = Cerveau()
        identite(c)
        sauver_etat(c)
        taxonomie(c)
        sauver_etat(c)

    if not recapitulatif(c):
        print()
        note("Rien n'a été créé. Votre entretien est conservé :")
        note("  python3 bootstrap/wizard.py --resume")
        return 1

    ecrits = ecrire(c)
    print()
    bien("Votre cerveau est décrit. Fichiers écrits :")
    for f in ecrits:
        dire(f"   {f.relative_to(RACINE)}", indent=2)
    print()
    titre("La suite")
    note("L'entretien ne crée que la DESCRIPTION de votre cerveau. Rien n'a encore")
    note("été installé, aucune base n'a été touchée.")
    print()
    dire("Pour lui donner corps, dans cet ordre :")
    dire(_c("36", "   ./bootstrap/bootstrap.sh --dry-run     # voir sans rien faire"))
    dire(_c("36", "   sudo ./bootstrap/bootstrap.sh          # agir"))
    print()
    _dire_la_grappe()
    note("La simulation d'abord : elle déroule les onze étapes, dit pourquoi chacune")
    note("existe et ce qu'elle changera, et n'écrit rien. L'installation demande")
    note("root — créer une base, écrire dans /etc, poser des unités systemd.")
    print()
    note("Cette commande vous montrera, avant d'agir, ce qu'elle s'apprête à faire :")
    note("créer la base et ses rôles, appliquer les migrations, générer vos secrets,")
    note("semer votre taxonomie, puis vérifier que tout répond.")
    print()
    note("Pour comprendre ce que vous installez avant de le lancer :")
    dire("   docs/CONCEPTS.md    ce qu'est un souvenir, un domaine, une preuve")
    dire("   docs/ARCHITECTURE.md  comment une conversation devient une connaissance")
    print()
    ETAT.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
