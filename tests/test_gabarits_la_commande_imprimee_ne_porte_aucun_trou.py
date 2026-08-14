"""LE JUMEAU DU CONTRÔLE DES GABARITS — et il regarde ce que le produit IMPRIME.

CE QUI A COÛTÉ CE GARDE
=======================

``mac/arac-pont.sh premiere-synchro`` réussit, annonce « ✓ Vos conversations
sont arrivées », et imprime, comme dernier geste à recopier :

    sudo systemctl start <prefixe>-cycle.service
    journalctl -u <prefixe>-cycle.service -f

``<prefixe>`` n'est pas un nom : c'est un **trou**. Recopiée telle quelle, la
commande rend « Unit <prefixe>-cycle.service not found ». Recopiée « en
comprenant », elle devient une devinette sur le nom d'une unité — et sur une
machine à deux cerveaux, une devinette désigne le voisin.

Le nom était pourtant connu à cette ligne : quatre lignes plus bas, le même
écran interpolait correctement ``$ARAC_PORT_COCKPIT``. Et c'est la **dernière**
chose que le pont dit, à la minute exacte où les conversations viennent
d'arriver — le moment où l'on a le plus confiance en ce qu'on lit, et donc
celui où l'on recopie sans relire.

POURQUOI AUCUN GARDE NE L'A VU — les deux raisons, écrites une fois pour toutes
==============================================================================

1. ``tests/test_gabarits_le_fichier_pose_ne_porte_aucun_jeton.py`` relit les
   fichiers **POSÉS**. Un texte imprimé n'est pas un fichier : il ne reste rien
   sur le disque à relire. Ce garde-là n'avait pas tort, il n'avait pas de
   prise.
2. G1 (``test_g1_aucun_nom_partage_entre_cerveaux``) tient au contraire un
   ``<trou>`` pour **DÉRIVÉ** — ``est_derive()`` rend ``True`` dès qu'un
   littéral commence par un chevron. Il a raison sur SA question : un trou ne
   fige aucun nom que deux cerveaux se disputeraient. Il ne pose simplement pas
   celle-ci.

La question d'ici est la troisième, et personne ne la posait :

    **une commande donnée à recopier est-elle recopiable ?**

CE QUE CE GARDE MESURE — exactement, ni plus
============================================

``cmd`` est, dans les deux voix du produit (``mac/arac-pont.sh:148`` et
``bootstrap/lib/ui.sh:72``), la fonction dont le métier est d'imprimer **un
geste à recopier**. C'est la seule dont le texte est destiné au presse-papier
plutôt qu'à la lecture. Trois directions :

1. **L'inventaire des trous est fermé.** Tout ``<jeton>`` qu'un ``cmd`` imprime
   est classé dans ``TROUS_ASSUMES``, avec le motif qui dit pourquoi le produit
   ne PEUT pas connaître cette valeur (l'adresse du serveur de l'utilisateur,
   le numéro qu'il vient de choisir…). Un trou neuf fait rougir : son auteur
   doit trancher — substituer, ou déclarer que c'est à l'humain de remplir. Il
   n'y a pas de troisième réponse, et c'est le point. ``@@X@@`` et ``__X__``,
   eux, ne sont jamais légitimes : ce sont les jetons des gabarits.
2. **Les écrans sont JOUÉS, et relus.** Statique, un garde ne voit pas le
   défaut symétrique : une interpolation **vide**. ``127.0.0.1:$ARAC_PORT_API``
   est irréprochable dans le source et imprime ``127.0.0.1:`` tant qu'aucun
   ``pont.conf`` n'existe — ce que `aide`, le tout premier écran, faisait. On
   joue donc les écrans dans un faux foyer et on relit ce qui sort.
3. **Le garde rougit pour de vrai.** On remet ``<prefixe>`` dans une copie du
   script, et le contrôle doit le refuser en le nommant. Un contrôle qu'on n'a
   jamais vu rougir n'est pas un contrôle.

CE QU'IL NE COUVRE PAS — dit ici plutôt que découvert dans six mois
===================================================================

· **La prose.** ``note`` et ``dire`` s'adressent à un lecteur :
  « <adresse-de-votre-serveur> » y est une consigne, pas un défaut. Seul
  ``cmd`` est tenu, parce que seul son texte est fait pour être recopié sans
  être relu.
· **Une valeur FAUSSE.** Substituer le port du voisin est une substitution
  parfaite. Aucun garde de forme ne le verra ; c'est ce que ``make acceptance``
  éprouve sur un cerveau réel.
· **Les écrans qu'on ne peut pas jouer sans serveur.** La direction 2 ne
  couvre que ce qui est atteignable hors ligne. C'est pour cette raison que le
  dernier écran du pont a été extrait en fonction (``ecran_apres_le_trajet``) :
  il est désormais jouable sans tunnel, sans API et sans envoyer une seule
  conversation.
· **Le Markdown.** ``docs/`` prescrit ses gestes en prose ; c'est le domaine
  de G4 et de ``test_la_doc_dit_vrai``.

Hors-ligne : ce fichier ne lit que des fichiers, et n'exécute que ``bash`` sur
des scripts du dépôt, dans un répertoire temporaire à lui, avec un ``HOME``
factice.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess

import pytest

from tests.test_g1_aucun_nom_partage_entre_cerveaux import _fichiers_balayes
from tests.test_g3_toute_commande_imprimee_porte_son_port import _est_du_shell

RACINE = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "mac" / "arac-pont.sh"

# ---------------------------------------------------------------------------
# LES JETONS, ET LEUR RÈGLE DANS UNE COMMANDE À RECOPIER
# ---------------------------------------------------------------------------
JETON_AROBASES = re.compile(r"@@[A-Za-z0-9_]+@@")
JETON_SOULIGNES = re.compile(r"__[A-Z][A-Z0-9_]+__")
#: Un trou porte parfois un espace — « <le numéro> », « <l'autre> ». Le motif
#: ne s'arrête donc qu'au chevron fermant, et jamais à la fin de la ligne.
JETON_CHEVRONS = re.compile(r"<[A-Za-z_][^<>\n]{0,60}>")

#: L'appel à `cmd`, y compris en continuation (`|| cmd "…"`), et le début de
#: sa chaîne. Une commande imprimée peut traverser plusieurs lignes : on suit
#: la chaîne jusqu'à sa fermeture, comme le fait G4 pour ses écrans.
_APPEL_CMD = re.compile(r"""^\s*(?:(?:\|\||&&|;)\s*)?cmd\s+(["'])""")


def _commandes_imprimees(p: pathlib.Path) -> list[tuple[int, str]]:
    """Les textes qu'un script fait recopier : un par appel à `cmd`.

    On rend la ligne PHYSIQUE de l'appel pour que le constat porte un numéro
    qu'on peut ouvrir, et le texte complet de la chaîne — un `cmd` qui court
    sur trois lignes est une seule commande aux yeux de qui la recopie.
    """
    lignes = p.read_text(encoding="utf-8", errors="replace").splitlines()
    trouves: list[tuple[int, str]] = []
    i = 0
    while i < len(lignes):
        m = _APPEL_CMD.match(lignes[i])
        if not m:
            i += 1
            continue
        guillemet = m.group(1)
        debut = i + 1
        reste = lignes[i][m.end():]
        morceaux: list[str] = []
        while True:
            fin = reste.find(guillemet)
            if fin >= 0:
                morceaux.append(reste[:fin])
                break
            morceaux.append(reste)
            i += 1
            if i >= len(lignes):
                break
            reste = lignes[i]
        trouves.append((debut, "\n".join(morceaux)))
        i += 1
    return trouves


def _fichiers_qui_parlent() -> list[pathlib.Path]:
    """Tout le shell du dépôt — le même corpus que G1, moins ses exemptions.

    On importe le corpus de G1 plutôt que d'en écrire un second : deux corpus
    qui se ressemblent finissent par diverger, et le jour où ils divergent,
    personne ne sait lequel des deux ment.
    """
    return [p for p in _fichiers_balayes() if _est_du_shell(p)]


# ===========================================================================
# 1. L'INVENTAIRE DES TROUS EST FERMÉ
# ===========================================================================

#: Les seuls trous légitimes dans une commande à recopier : ceux dont la valeur
#: N'EXISTE PAS encore dans le produit au moment où il imprime. La clé est le
#: jeton, la valeur dit pourquoi personne ne peut le substituer. Tout le reste
#: — c'est-à-dire toute valeur que le script tient déjà dans une variable —
#: doit être interpolé.
TROUS_ASSUMES: dict[str, str] = {
    "<votre-base>": (
        "Le repli de `${ARAC_CERVEAU:-<votre-base>}`, et il n'est atteint que "
        "sur un poste installé dans le foyer COMMUN ~/.arac, c'est-à-dire "
        "avant le cloisonnement par cerveau : là, le pont ne connaît aucun nom "
        "de base et n'a rien à substituer. Dire « je ne sais pas » vaut mieux "
        "que nommer : sur une machine à deux cerveaux, un nom deviné est celui "
        "du voisin."
    ),
    "<le-compte-du-tunnel>": (
        "Le compte Unix que l'utilisateur a créé sur SON serveur pour le "
        "tunnel. Le pont ne l'a jamais vu — il vit de l'autre côté, et c'est "
        "précisément la ligne de ~/.ssh/config que l'on demande à l'utilisateur "
        "d'écrire."
    ),
    "<adresse-de-votre-serveur>": (
        "L'adresse du serveur de l'utilisateur. Aucune installation du poste ne "
        "la contient tant qu'il n'a pas rempli ~/.ssh/config ; c'est le geste "
        "même qu'on lui prescrit."
    ),
    "<utilisateur>": (
        "Le compte SSH du lecteur sur son propre serveur, dans la commande de "
        "tunnel imprimée par la fin de l'installation. Le bootstrap tourne SUR "
        "le serveur : il ne sait pas sous quel nom on s'y connecte depuis "
        "l'extérieur."
    ),
    "<votre-serveur>": (
        "L'hôte que le lecteur atteindra depuis son poste. Le bootstrap connaît "
        "des adresses de boucle locale, jamais celle par laquelle on vient de "
        "l'extérieur — la deviner reviendrait à imprimer une adresse fausse."
    ),
    "<le numéro>": (
        "Le port d'API que l'utilisateur vient de choisir, dans l'écran qui lui "
        "demande justement de l'écrire dans pont.conf. La valeur n'existe nulle "
        "part côté poste : c'est ce que l'écran sert à obtenir."
    ),
    "<l'autre>": (
        "Le port de cockpit, dans le même écran et pour la même raison que "
        "« <le numéro> » : ces deux nombres n'ont AUCUN défaut, délibérément, "
        "parce qu'un défaut plausible désignerait le premier cerveau d'une "
        "machine qui en porte deux."
    ),
    "<nom>": (
        "Le nom que l'administrateur donnera à la grappe PostgreSQL qu'il "
        "s'apprête à créer avec `pg_createcluster`. Elle n'existe pas encore : "
        "il n'y a rien à substituer, et proposer un nom serait proposer de "
        "réutiliser celui d'une grappe existante."
    ),
    "<port>": (
        "Le port de cette même grappe à créer. Le bootstrap refuse justement de "
        "choisir un numéro de port à la place de l'administrateur — c'est ce "
        "qui empêche d'en lier un déjà pris par le cerveau voisin."
    ),
    "<dépôt>": (
        "L'adresse du dépôt Git que le lecteur veut cloner. Ce dépôt n'a pas "
        "d'adresse canonique tant qu'il n'est pas publié, et l'inventer serait "
        "imprimer une URL qui ne répond pas."
    ),
}


def _trous(texte: str) -> list[str]:
    return sorted(set(JETON_CHEVRONS.findall(texte)))


def _inventaire() -> dict[str, list[str]]:
    """{jeton: [fichier:ligne, …]} pour tout ce que `cmd` imprime."""
    vus: dict[str, list[str]] = {}
    for p in _fichiers_qui_parlent():
        rel = str(p.relative_to(RACINE))
        for numero, texte in _commandes_imprimees(p):
            for jeton in _trous(texte):
                vus.setdefault(jeton, []).append(f"{rel}:{numero}")
    return vus


def test_aucune_commande_a_recopier_ne_porte_un_jeton_de_gabarit() -> None:
    """`@@X@@` et `__X__` ne sont jamais de la prose : ce sont des gabarits."""
    fautifs: list[str] = []
    for p in _fichiers_qui_parlent():
        rel = str(p.relative_to(RACINE))
        for numero, texte in _commandes_imprimees(p):
            for jeton in JETON_AROBASES.findall(texte) + JETON_SOULIGNES.findall(texte):
                fautifs.append(f"{rel}:{numero} → {jeton}")
    assert not fautifs, (
        "Une commande donnée à recopier porte un jeton de GABARIT :\n"
        + "\n".join(f"  · {f}" for f in fautifs)
        + "\n\nUn gabarit non substitué dans un fichier posé est un chemin "
        "littéral ;\ndans une commande imprimée, c'est une commande qui ne peut "
        "pas s'exécuter."
    )


def test_tout_trou_dans_une_commande_a_recopier_est_assume() -> None:
    """Un trou neuf oblige à trancher : substituer, ou déclarer pourquoi non.

    C'est la direction qui aurait attrapé `<prefixe>` : le nom du cerveau était
    dans `$ARAC_CERVEAU` à cette ligne même, et personne n'aurait pu écrire un
    motif honnête expliquant que le produit ne le connaissait pas.
    """
    inconnus = {
        jeton: lieux
        for jeton, lieux in _inventaire().items()
        if jeton not in TROUS_ASSUMES
    }
    assert not inconnus, (
        "Ces commandes sont données à RECOPIER et portent un trou que rien ne "
        "justifie :\n"
        + "\n".join(f"  · {j}  ({', '.join(l)})" for j, l in sorted(inconnus.items()))
        + "\n\nDeux réponses, et pas de troisième :\n"
        "  · le produit connaît la valeur à cette ligne → INTERPOLEZ-LA. C'était\n"
        "    le cas de `<prefixe>` : `$ARAC_CERVEAU` était renseigné, et quatre\n"
        "    lignes plus bas le même écran interpolait `$ARAC_PORT_COCKPIT`.\n"
        "  · le produit ne peut PAS la connaître (l'adresse du serveur du\n"
        "    lecteur, un numéro qu'il vient de choisir) → classez le jeton dans\n"
        "    TROUS_ASSUMES avec le motif. Et si vous ne savez pas l'écrire, la\n"
        "    réponse est la première."
    )


def test_chaque_trou_assume_couvre_encore_une_commande() -> None:
    """Un trou classé qui ne désigne plus rien est une permission gratuite.

    C'est ainsi qu'une liste d'exceptions grossit jusqu'à couvrir le prochain
    défaut sans que personne ne l'ait décidé.
    """
    vivants = set(_inventaire())
    morts = sorted(set(TROUS_ASSUMES) - vivants)
    assert not morts, (
        "Ces trous sont déclarés assumés et plus aucune commande ne les "
        "imprime : " + ", ".join(morts) + ". Retirez-les de TROUS_ASSUMES."
    )


@pytest.mark.parametrize("jeton", sorted(TROUS_ASSUMES))
def test_chaque_trou_assume_porte_un_motif_ecrit(jeton: str) -> None:
    """« On a décidé » sans le pourquoi est indistinguable d'un oubli."""
    motif = TROUS_ASSUMES[jeton].strip()
    assert len(motif) > 80, (
        f"Le motif de {jeton} tient en {len(motif)} caractères. Un classement "
        "sans motif n'est pas un contrat, c'est une liste d'exceptions."
    )


# ===========================================================================
# 2. LES ÉCRANS SONT JOUÉS, ET RELUS
# ===========================================================================
#
# Statique, un garde ne voit pas le défaut symétrique du trou : la valeur
# VIDE. `127.0.0.1:$ARAC_PORT_API` est irréprochable dans le source et imprime
# `127.0.0.1:` tant qu'aucun `pont.conf` n'existe.

#: Ce qu'une interpolation vide laisse derrière elle, et qu'aucune lecture du
#: source ne montre. Chaque motif porte son nom, pour que le constat dise ce
#: qui manquait plutôt que « motif n° 2 ».
VALEURS_VIDES: tuple[tuple[str, str], ...] = (
    (
        r"(?:\d{1,3}(?:\.\d{1,3}){3}|localhost):(?![0-9])",
        "une adresse dont le PORT est vide — l'interpolation n'a rien rendu",
    ),
    (
        r"\bport\b\s{2,}",
        "le mot « port » suivi de rien : le numéro annoncé n'existait pas",
    ),
    (
        r"(?:^|\s)-[\w.]+\.(?:service|timer)\b",
        "un nom d'unité qui commence par un tiret : son préfixe était vide",
    ),
    (
        r"«\s*»",
        "une citation vide : on cite une valeur qu'on n'a pas",
    ),
)

REPONSES_INSTALLER = "{cerveau}\no\n{node}\n{ssh}\n\n{api}\n{cockpit}\n"


def _jouer(commande: list[str], foyer: pathlib.Path, **env_sup: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["HOME"] = str(foyer)
    env["ARAC_SANS_COULEUR"] = "1"
    env.pop("ARAC_CERVEAU", None)
    env.update(env_sup)
    return subprocess.run(
        commande, capture_output=True, text=True, env=env, cwd=str(foyer),
        input="",
    )


#: CE QUI DISTINGUE, DANS UNE SORTIE, UN GESTE À RECOPIER DU RESTE.
#
# Les deux voix du produit impriment leurs commandes avec la MÊME indentation
# de six espaces — `mac/arac-pont.sh:148` et `bootstrap/lib/ui.sh:72` —, et
# rien d'autre n'est indenté ainsi. C'est le seul marqueur que la sortie
# conserve, et `test_les_deux_voix_indentent_leurs_gestes_pareil` interdit
# qu'il dérive sans qu'on le sache.
_LIGNE_DE_COMMANDE = re.compile(r"^ {6}\S")


def _relire(sortie: str, quoi: str) -> None:
    """Le seul endroit qui juge un écran JOUÉ, et il juge deux choses.

    · UN TROU (`<jeton>`) — seulement dans une ligne de commande. Ailleurs,
      c'est de la prose adressée à un humain : l'inventaire du pont affiche
      « $HOME/.arac/<cerveau>/export-desktop » comme LIBELLÉ générique, puis
      la ligne suivante donne le chemin réellement regardé. Accuser cela
      apprendrait à ignorer le garde.
    · UNE VALEUR VIDE — partout. « port  fermé » est de la prose, et c'est
      quand même un numéro qui manque au milieu d'une phrase qui en annonce un.
    """
    fautives: list[str] = []
    for n, ligne in enumerate(sortie.splitlines(), 1):
        if _LIGNE_DE_COMMANDE.match(ligne):
            for jeton in JETON_AROBASES.findall(ligne) + JETON_SOULIGNES.findall(ligne):
                fautives.append(f"{n}: jeton de gabarit {jeton} — {ligne.strip()}")
            for jeton in JETON_CHEVRONS.findall(ligne):
                if jeton not in TROUS_ASSUMES:
                    fautives.append(f"{n}: trou non assumé {jeton} — {ligne.strip()}")
        for motif, pourquoi in VALEURS_VIDES:
            if re.search(motif, ligne):
                fautives.append(f"{n}: {pourquoi} — {ligne.strip()!r}")
    assert not fautives, (
        f"L'écran « {quoi} », JOUÉ, porte un trou :\n"
        + "\n".join(f"  {f}" for f in fautives)
        + "\n\nCe n'est pas ce que dit le source : c'est ce que lit celui qui "
        "vient\nde taper la commande."
    )


def test_le_premier_ecran_ne_porte_aucun_trou(tmp_path: pathlib.Path) -> None:
    """`./arac-pont.sh` sans argument, sur une machine qui n'a rien.

    C'est la toute première chose que voit celui qui vient d'obtenir ce
    script. Le schéma annonçait « tunnel SSH  (127.0.0.1: sur cette machine) »
    — une adresse sans port, faute de `pont.conf`.
    """
    foyer = tmp_path / "foyer"
    foyer.mkdir()
    r = _jouer(["bash", str(RACINE / "mac" / "arac-pont.sh"), "aide"], foyer)
    assert r.returncode == 0, r.stdout + r.stderr
    _relire(r.stdout, "arac-pont.sh aide, foyer vide")


def test_le_diagnostic_sur_un_poste_nu_ne_porte_aucun_trou(
    tmp_path: pathlib.Path,
) -> None:
    """`etat` est ce qu'on tape quand plus rien n'arrive. Sans conf, il
    annonçait « port  fermé — le tunnel est tombé » : le maillon 4 accusé
    d'une panne qui appartient au maillon 2, et un numéro absent au milieu
    d'une phrase qui prétend en citer un.
    """
    foyer = tmp_path / "foyer"
    foyer.mkdir()
    r = _jouer(["bash", str(RACINE / "mac" / "arac-pont.sh"), "etat"], foyer)
    _relire(r.stdout, "arac-pont.sh etat, aucune configuration")


@pytest.fixture(scope="module")
def foyer_installe(tmp_path_factory: pytest.TempPathFactory) -> tuple[pathlib.Path, str]:
    """Un faux foyer Mac, avec un cerveau réellement installé par le produit.

    Rend le foyer ET la sortie de `installer` : cet écran est la première
    liste de gestes du parcours, et il ne se rejoue pas — la seconde fois,
    `installer` propose des valeurs qu'il vient d'écrire.
    """
    foyer = tmp_path_factory.mktemp("foyer-imprime")
    env = dict(os.environ)
    env["HOME"] = str(foyer)
    env["ARAC_SANS_COULEUR"] = "1"
    env.pop("ARAC_CERVEAU", None)
    r = subprocess.run(
        ["bash", str(RACINE / "mac" / "arac-pont.sh"), "installer"],
        input=REPONSES_INSTALLER.format(
            cerveau="kz_temoin", node="poste-temoin", ssh="serveur-temoin",
            api="8241", cockpit="8242",
        ),
        capture_output=True, text=True, env=env, cwd=str(foyer),
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return foyer, r.stdout


def test_l_ecran_d_installation_ne_porte_aucun_trou(
    foyer_installe: tuple[pathlib.Path, str],
) -> None:
    """La première liste de gestes du parcours — celle qu'on suit en entier."""
    _relire(foyer_installe[1], "arac-pont.sh installer")


#: LES ÉCRANS QU'ON PEUT JOUER SANS RIEN TOUCHER À LA MACHINE.
#
# `tunnel ouvrir` lancerait un vrai `ssh`, et `etat` sur une configuration
# RENSEIGNÉE sonde 127.0.0.1 : « local » ne veut pas dire « à moi », le cerveau
# de quelqu'un vit sur la boucle locale. On ne joue donc que ce qui refuse ou
# rend compte AVANT toute sonde — ce qui est précisément l'endroit où le
# produit parle le plus.
ECRANS_HORS_LIGNE = (
    ("aide", ["aide"], ""),
    ("journal", ["journal"], ""),
    ("automatiser (refus : pas de première synchro)", ["automatiser"], "o\n"),
    ("desinstaller (refus : on répond non)", ["desinstaller"], "n\n"),
)


@pytest.mark.parametrize(
    "quoi,args,entree", ECRANS_HORS_LIGNE, ids=[e[0].split()[0] for e in ECRANS_HORS_LIGNE]
)
def test_les_ecrans_hors_ligne_ne_portent_aucun_trou(
    foyer_installe: tuple[pathlib.Path, str], quoi: str, args: list[str], entree: str,
) -> None:
    """Le reste de la voix du pont, sur un cerveau réellement installé."""
    foyer, _ = foyer_installe
    env = dict(os.environ)
    env["HOME"] = str(foyer)
    env["ARAC_SANS_COULEUR"] = "1"
    env["ARAC_CERVEAU"] = "kz_temoin"
    r = subprocess.run(
        ["bash", str(RACINE / "mac" / "arac-pont.sh"), *args],
        input=entree, capture_output=True, text=True, env=env, cwd=str(foyer),
    )
    _relire(r.stdout, f"arac-pont.sh {quoi}")


def _ecran_final(foyer: pathlib.Path, cerveau: str | None) -> str:
    """Le dernier écran du pont, imprimé sans tunnel ni serveur.

    `ecran_apres_le_trajet` a été extrait en fonction pour exactement ceci :
    l'écran qui portait le trou est le plus difficile à atteindre du produit —
    il exige une API vivante, un tunnel ouvert et un envoi accepté. Un garde
    qui ne peut pas jouer un écran ne le surveille pas.
    """
    env = dict(os.environ)
    env["HOME"] = str(foyer)
    env["ARAC_SANS_COULEUR"] = "1"
    env.pop("ARAC_CERVEAU", None)
    if cerveau:
        env["ARAC_CERVEAU"] = cerveau
    r = subprocess.run(
        [
            "bash", "-c",
            'set -- aide; . "$SCRIPT" >/dev/null 2>&1; '
            "charger_conf; ecran_apres_le_trajet",
            "arac-pont.sh",
        ],
        capture_output=True, text=True, env={**env, "SCRIPT": str(SCRIPT)},
        cwd=str(foyer),
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def test_le_dernier_ecran_nomme_l_unite_du_cerveau(
    foyer_installe: pathlib.Path,
) -> None:
    """Le constat, rejoué : le geste imprimé doit être recopiable tel quel.

    `bootstrap/lib/config.sh:167` pose `PREFIXE_UNITE="arac-${ARAC_DB}"`, et
    `ARAC_DB` est ce que `installer` demande sous le nom « cerveau ». L'unité
    de digestion s'appelle donc `arac-<cerveau>-cycle.service`, et le pont a
    tout ce qu'il faut pour l'écrire.
    """
    sortie = _ecran_final(foyer_installe[0], "kz_temoin")
    _relire(sortie, "premiere-synchro, dernier écran, cerveau connu")
    assert "sudo systemctl start arac-kz_temoin-cycle.service" in sortie, sortie
    assert "journalctl -u arac-kz_temoin-cycle.service -f" in sortie, sortie
    assert "<prefixe>" not in sortie, sortie
    # Le port du cockpit vient du pont.conf posé par `installer` : la ligne
    # d'à côté prouve que l'écran interpole bien ce qu'il connaît.
    assert "open http://127.0.0.1:8242" in sortie, sortie


def test_le_dernier_ecran_dit_qu_il_ne_sait_pas_plutot_que_de_nommer(
    tmp_path: pathlib.Path,
) -> None:
    """Le foyer COMMUN — un poste installé avant le cloisonnement par cerveau.

    Là, le pont ne connaît AUCUN nom de base. La correction n'est pas d'en
    inventer un : c'est de dire qu'on ne sait pas, et de donner la commande
    qui va le demander au serveur.
    """
    foyer = tmp_path / "foyer-commun"
    (foyer / ".arac").mkdir(parents=True)
    (foyer / ".arac" / "pont.conf").write_text(
        "ARAC_NODE_ID=poste-ancien\nARAC_PORT_COCKPIT=8242\n", encoding="utf-8"
    )
    sortie = _ecran_final(foyer, None)
    _relire(sortie, "premiere-synchro, dernier écran, foyer commun")
    gestes = [l for l in sortie.splitlines() if _LIGNE_DE_COMMANDE.match(l)]
    nommees = [l for l in gestes if ".service" in l or ".timer" in l]
    assert not nommees, (
        "Un geste à recopier nomme une unité alors qu'aucun nom de cerveau "
        "n'est connu — sur une machine à deux cerveaux, une unité devinée est "
        "celle du voisin :\n" + "\n".join(nommees)
    )
    assert any("ls /etc/arac/" in l for l in gestes), (
        "L'écran ne donne aucun geste pour ALLER CHERCHER le nom : dire « je "
        "ne sais pas » sans dire où regarder laisse le lecteur deviner.\n"
        + sortie
    )


def test_la_premiere_synchro_refuse_des_ports_vides(
    tmp_path: pathlib.Path,
) -> None:
    """Sans numéro, la sonde du tunnel n'accuse pas le bon maillon.

    `port_ouvert 127.0.0.1 ""` échoue toujours : l'écran annonçait « port
    fermé — rien ne peut partir » sur une configuration à laquelle il manquait
    seulement deux nombres.
    """
    foyer = tmp_path / "foyer"
    dossier = foyer / ".arac" / "kz_sans_ports"
    dossier.mkdir(parents=True)
    (dossier / "pont.conf").write_text(
        "ARAC_NODE_ID=poste\nARAC_PORT_API=\nARAC_PORT_COCKPIT=\n", encoding="utf-8"
    )
    shutil.copy(RACINE / "mac" / "arac-sync.py", dossier / "arac-sync.py")
    r = _jouer(
        ["bash", str(RACINE / "mac" / "arac-pont.sh"), "premiere-synchro"],
        foyer, ARAC_CERVEAU="kz_sans_ports",
    )
    assert r.returncode == 4, f"code {r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "sont vides dans" in r.stdout, r.stdout
    assert "rien ne peut partir" not in r.stdout, (
        "Le tunnel est accusé d'une panne qui appartient à la configuration :\n"
        + r.stdout
    )
    _relire(r.stdout, "premiere-synchro, ports vides")


# ===========================================================================
# 3. LE GARDE ROUGIT POUR DE VRAI
# ===========================================================================


def test_le_garde_voit_le_trou_qu_on_lui_remet(tmp_path: pathlib.Path) -> None:
    """On remet le défaut exact, et le contrôle doit le nommer.

    On ne trompe pas le corpus complet — il est lu depuis le dépôt — mais la
    fonction qui juge, sur une copie du script portant la ligne d'avant le
    correctif. C'est elle qui décide ; c'est donc elle qu'il faut voir rougir.
    """
    copie = tmp_path / "arac-pont.sh"
    copie.write_text(
        (RACINE / "mac" / "arac-pont.sh").read_text(encoding="utf-8")
        + '\ncmd "sudo systemctl start <prefixe>-cycle.service"\n',
        encoding="utf-8",
    )
    trouves = {
        j for _, texte in _commandes_imprimees(copie) for j in _trous(texte)
    }
    assert "<prefixe>" in trouves, (
        "L'extracteur n'a pas vu le trou qu'on vient de remettre : "
        f"{sorted(trouves)}"
    )
    assert "<prefixe>" not in TROUS_ASSUMES, (
        "`<prefixe>` a été classé comme assumé. Il ne l'est pas : le nom du "
        "cerveau est dans $ARAC_CERVEAU à cette ligne même."
    )


def test_le_garde_voit_une_valeur_vide() -> None:
    """La direction 2, éprouvée sur les écrans exacts d'avant le correctif."""
    for ligne, quoi in (
        ("     tunnel SSH  (127.0.0.1: sur cette machine)", "adresse sans port"),
        ("  × port  fermé — le tunnel est tombé", "port vide"),
        ("      sudo systemctl start -cycle.service", "préfixe vide"),
    ):
        assert any(re.search(m, ligne) for m, _ in VALEURS_VIDES), (
            f"La direction 2 ne voit pas « {quoi} » : {ligne!r}"
        )


def test_les_deux_voix_indentent_leurs_gestes_pareil() -> None:
    """Le marqueur que la direction 2 lit dans la sortie ne doit pas dériver.

    Le produit a DEUX `cmd` — celui du pont Mac et celui du bootstrap — écrits
    séparément. S'ils cessaient d'indenter pareil, la direction 2 se mettrait à
    lire du texte au lieu de commandes, ou l'inverse, et resterait verte.
    """
    for fichier, motif in (
        ("mac/arac-pont.sh", r"^cmd\(\)\s*\{\s*printf '( +)%s"),
        ("bootstrap/lib/ui.sh", r"^cmd\(\)\s*\{.*printf '( +)%s"),
    ):
        texte = (RACINE / fichier).read_text(encoding="utf-8")
        m = re.search(motif, texte, re.MULTILINE)
        assert m, f"{fichier} ne définit plus `cmd` sous une forme lisible ici"
        assert len(m.group(1)) == 6, (
            f"{fichier} indente ses gestes de {len(m.group(1))} espaces ; la "
            "direction 2 en attend 6. Mettez les deux d'accord, et ce test avec."
        )


def test_le_garde_se_tait_sur_un_ecran_juste() -> None:
    """Et il ne crie pas au loup sur ce qui est correct : un garde qui accuse
    la solution apprend à ses lecteurs à l'ignorer."""
    for ligne in (
        "      sudo systemctl start arac-kz_temoin-cycle.service",
        "      open http://127.0.0.1:8242",
        "  ✓ port 8241 ouvert (API atteignable)",
        "     tunnel etat        les ports sont-ils là ?",
        "  ✓ poste déclaré : « poste-marc »",
    ):
        assert not any(re.search(m, ligne) for m, _ in VALEURS_VIDES), (
            f"Le garde accuse une ligne correcte : {ligne!r}"
        )
