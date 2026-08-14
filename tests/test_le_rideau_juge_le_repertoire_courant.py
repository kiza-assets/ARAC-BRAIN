"""LE RIDEAU JUGE LE RÉPERTOIRE COURANT — le dernier terme de la résolution.

CE QUE CE GARDE EMPÊCHE, EN UNE PHRASE
======================================
`cat arac.env`, lancé depuis le dossier d'un cerveau voisin, rend son coffre —
c'est-à-dire son jeton porteur et le mot de passe de sa base — sans qu'aucun
chemin de ce coffre n'apparaisse dans la commande.

LA CLASSE, ET POURQUOI C'EN EST LA DERNIÈRE INSTANCE
====================================================
Trois manches de suite, le même motif : **un jugement porte sur le TEXTE d'un
chemin là où le noyau juge sur sa RÉSOLUTION.** `/proc/self/root/<coffre>` est,
pour `abspath`, un chemin de `/proc` ; pour le noyau, c'est le coffre. La
correction précédente a écrit la bonne phrase — « ne juge pas un chemin sur son
texte quand le noyau juge sur sa résolution » — et l'a appliquée aux ARGUMENTS.
Elle a laissé dehors le troisième terme de la résolution du noyau : le
RÉPERTOIRE COURANT.

Deux moitiés du même trou :

· `_chemins_d_un_argument` ne retenait un chemin relatif que s'il était ÉCRIT
  comme tel (`./x`, `../x`), avec cette justification : « sans cela, tout mot
  serait un chemin possible et le garde crierait au loup ». Le noyau, lui,
  résout CHAQUE relatif contre le répertoire courant, que le mot porte un point
  ou non ;
· le répertoire courant lui-même n'était jugé par personne — ni le `cwd=` passé
  à `Popen`, ni celui qu'un `os.chdir` (`monkeypatch.chdir`) déplace. `ls`,
  SANS UN SEUL ARGUMENT, listait le dossier d'un voisin.

LA MESURE, AVANT ET APRÈS, RÉGIME DE REPLI
==========================================
Faux voisin à moi, hors du dépôt, portant `ARAC_API_BEARER_TOKEN=SENTINELLE-…`
et un `adieu.dump`. Rideau de Python seul (`ARAC_SANS_SECONDE_BARRIERE=1`) :

    forme                                  avant            après
    cat arac.env      (cwd=voisin)         le coffre LU     RefusDeFichier
    ls                (cwd=voisin)         le dossier LISTÉ RefusDeFichier
    sh -c 'cat arac.env'                   le coffre LU     RefusDeFichier
    shell=True 'cat arac.env'              le coffre LU     RefusDeFichier
    os.chdir puis ls                       le dossier LISTÉ RefusDeFichier
    os.chdir puis cat arac.env             le coffre LU     RefusDeFichier
    rm adieu.dump     (cwd=voisin)         le dump DÉTRUIT  RefusDeFichier
    cat ./arac.env    (témoin)             RefusDeFichier   RefusDeFichier

Le témoin est ce qui dit tout : le MÊME fichier, écrit autrement, était refusé.
En régime nominal, Landlock refusait déjà les sept ; la faille ne vivait que
dans le repli — que ce dépôt documente comme supporté, et pour lequel il écrit
lui-même « la suite ne tient alors que par la porte de Python ».

LA RÉPONSE À « CRIER AU LOUP » N'EST PAS UNE EXCEPTION, C'EST UN MEILLEUR
CRITÈRE
=======================================================================
On retient le mot nu quand il EXISTE là où le noyau irait le chercher. `grep
motif` ne désigne rien et ne réveille personne ; `grep motif arac.env`, depuis
le dossier d'un voisin, désigne un fichier réel. L'existence est MESURÉE, et
par `realpath` — jamais par `normpath` : c'est ce qui fait du critère une
résolution et non un texte, et c'est ce qui ferme aussi le détour par un lien.

CE QUE CES TESTS NE FONT PAS, ET POURQUOI
=========================================
Aucun d'eux ne pose de fichier hors du périmètre pour se donner un voisin à
lire : le rideau refuserait de l'écrire, et il aurait raison. Les cas de
sous-processus visent donc un dossier qui N'EXISTE PAS sous `/etc/arac` — si
le garde régressait, `Popen` échouerait sur le `cwd` au lieu d'atteindre quoi
que ce soit de réel, et le test rougirait sans rien avoir touché. La mesure
sur un vrai faux voisin est celle du tableau ci-dessus, jouée à la main.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import tests.garde_hermetique as g
from tests.garde_hermetique import RefusHermetique

RACINE = Path(__file__).resolve().parents[1]

#: Un dossier de cerveau qui n'existe sur AUCUNE machine — le nom porte le pid
#: pour qu'il ne puisse pas exister par hasard. Il est sous `/etc/arac`, donc
#: retranché de toute racine : c'est le périmètre qu'on éprouve, pas son
#: contenu, et il n'y a rien à contenir.
VOISIN = f"/etc/arac/voisin-imaginaire-{os.getpid()}"


# ---------------------------------------------------------------------------
# LE MOT NU
# ---------------------------------------------------------------------------

def test_le_mot_nu_est_un_chemin_quand_il_designe_quelque_chose():
    """`arac.env` et `./arac.env` désignent le même fichier : même verdict.

    On l'éprouve sur `/etc` et `shadow`, qui existent sur toute machine Linux
    et qu'aucune exception du rideau ne recouvre — sans jamais l'ouvrir : ces
    deux fonctions sont pures, elles ne lisent que l'existence.
    """
    nu = list(g._chemins_d_un_argument("shadow", cwd="/etc"))
    point = list(g._chemins_d_un_argument("./shadow", cwd="/etc"))
    assert nu == point == ["/etc/shadow"], (
        "Le mot nu et le mot pointé doivent rendre le MÊME chemin : le noyau "
        f"ne fait pas la différence. Nu={nu} pointé={point}")
    assert g._donnee_toleree("/etc/shadow") is False


def test_un_mot_qui_ne_designe_rien_ne_reveille_personne():
    """LE GARDE NE CRIE PAS AU LOUP, et c'est la moitié qui compte.

    C'est l'objection qui a tenu ce trou ouvert : si tout mot est un chemin,
    `grep motif` devient un refus. Le critère d'EXISTENCE y répond sans
    exception : un mot qui ne tombe sur rien n'est pas un chemin.
    """
    assert list(g._chemins_d_un_argument("status", cwd=str(RACINE))) == []
    assert list(g._chemins_d_un_argument("motif-qui-nexiste-pas", cwd="/etc")) == []
    assert list(g._chemins_d_un_argument("--porcelain", cwd="/etc")) == []
    assert list(g._chemins_d_un_argument("-n", cwd="/etc")) == []


def test_le_mot_nu_du_depot_passe_toujours():
    """Ce qui est DANS le dépôt reste servi sans un mot — la contre-épreuve."""
    vu = list(g._chemins_d_un_argument("README.md", cwd=str(RACINE)))
    assert vu == [str(RACINE / "README.md")]
    assert g._donnee_toleree(vu[0]) is True


# ---------------------------------------------------------------------------
# LE RÉPERTOIRE COURANT
# ---------------------------------------------------------------------------

def test_le_repertoire_courant_est_juge_meme_sans_argument():
    """`ls`, sans un seul argument, listait le dossier d'un voisin."""
    with pytest.raises(RefusHermetique):
        subprocess.run(["ls"], cwd=VOISIN, capture_output=True)


def test_le_mot_nu_resolu_contre_un_cwd_hors_perimetre_est_refuse():
    with pytest.raises(RefusHermetique):
        subprocess.run(["cat", "arac.env"], cwd=VOISIN, capture_output=True)


def test_le_geste_destructeur_l_est_aussi():
    """`rm adieu.dump` a détruit un dump, mesuré. Il ne le peut plus."""
    with pytest.raises(RefusHermetique):
        subprocess.run(["rm", "adieu.dump"], cwd=VOISIN, capture_output=True)


def test_le_corps_de_shell_passe_par_le_meme_juge():
    """La branche `shell=True` retournait AVANT tout contrôle de chemin."""
    with pytest.raises(RefusHermetique):
        subprocess.run("cat arac.env", shell=True, cwd=VOISIN, capture_output=True)
    with pytest.raises(RefusHermetique):
        subprocess.run(["sh", "-c", "cat arac.env"], cwd=VOISIN, capture_output=True)


def test_os_chdir_deplace_le_repertoire_courant_et_le_garde_le_voit(monkeypatch):
    """SANS AUCUN `cwd=`. `os.chdir` n'est enveloppé par aucun garde.

    Le répertoire courant du processus est le troisième terme de la résolution
    du noyau : le juger seulement quand il arrive par `cwd=` laissait la moitié
    du trou, celle qui ne s'écrit nulle part dans la commande.
    """
    monkeypatch.chdir("/etc")
    with pytest.raises(RefusHermetique):
        subprocess.run(["cat", "shadow"], capture_output=True)
    with pytest.raises(RefusHermetique):
        subprocess.run(["ls"], capture_output=True)


def test_le_refus_dit_ce_qu_il_a_vu_plutot_que_de_dire_non():
    """Un refus qui n'enseigne pas se contourne, puis se désactive."""
    with pytest.raises(RefusHermetique) as capture:
        subprocess.run(["ls"], cwd=VOISIN, capture_output=True)
    dit = str(capture.value)
    assert "répertoire" in dit.lower()
    assert VOISIN in dit
    assert "tmp_path" in dit


# ---------------------------------------------------------------------------
# CE QUI DOIT PASSER PASSE ENCORE — la moitié qui décide qu'un garde survit
# ---------------------------------------------------------------------------

def test_le_travail_ordinaire_n_est_pas_gene(tmp_path):
    """Un garde qui gêne se fait débrancher : c'est ainsi qu'on en perd un.

    Les six formes ci-dessous sont celles que la suite joue par centaines. Si
    l'une d'elles rougissait, le critère serait mauvais — et il faudrait un
    meilleur critère, pas une exception.
    """
    (tmp_path / "arac.env").write_text("temoin\n", encoding="utf-8")
    assert subprocess.run(["ls"], cwd=str(tmp_path),
                          capture_output=True).returncode == 0
    assert subprocess.run(["cat", "arac.env"], cwd=str(tmp_path),
                          capture_output=True).returncode == 0
    assert subprocess.run(["cat", "README.md"], cwd=str(RACINE),
                          capture_output=True).returncode == 0
    assert subprocess.run(["ls"], capture_output=True).returncode == 0
    # `git` PART du dépôt, et c'est tout ce qu'on lui demande ici : le code de
    # sortie ne nous regarde pas — ce dépôt se teste aussi SANS `.git`, où
    # `git status` rend 128 sans que rien ne soit cassé. Ce qu'on mesure est
    # que le garde ne l'a pas REFUSÉ.
    subprocess.run(["git", "status", "--short"], cwd=str(RACINE),
                   capture_output=True)
    # Un motif qui n'est pas un chemin, dans l'outil où l'objection était née.
    subprocess.run(["grep", "-c", "motif-absent", "README.md"],
                   cwd=str(RACINE), capture_output=True)


def test_la_raison_ecrite_ne_redevient_pas_fausse():
    """LE GARDE DE LA PHRASE — c'est elle qui a tenu le trou ouvert.

    « sans cela, tout mot serait un chemin possible et le garde crierait au
    loup » : la phrase était exacte sur le risque et fausse sur la conclusion.
    Tant qu'elle est écrite, personne ne relit la ligne qu'elle couvre.
    """
    source = (RACINE / "tests" / "garde_hermetique.py").read_text(encoding="utf-8")
    assert "crierait au loup à chaque argument" not in source, (
        "La justification qui a tenu ce trou ouvert est revenue dans "
        "`_chemins_d_un_argument`. Le mot nu se juge sur son EXISTENCE, pas "
        "sur son orthographe.")
    assert "os.path.normpath(os.path.join" not in source, (
        "`normpath` est du calcul de TEXTE : il replie les `..` sans jamais "
        "demander au disque et ne suit aucun lien. La résolution d'un chemin "
        "relatif se demande à `realpath`, comme le noyau.")
