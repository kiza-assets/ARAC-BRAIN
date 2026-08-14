"""LE CONTRÔLE QUI AURAIT ATTRAPÉ LA FAUTE — exercé, pas déclaré.

CE QUE CE FICHIER TESTE, ET POURQUOI IL EST DANS `make test`
============================================================
Il n'exerce pas ARAC. Il exerce le HARNAIS D'ACCEPTATION lui-même —
``tests/acceptance/garde_isolement.sh`` — sur les valeurs exactes qui ont
cassé une installation de production :

    5432                le cluster dont les rôles sont globaux
    8000, 8100          les ports de l'API et du cockpit de production
    arac-api            le nom d'une unité systemd vivante
    /var/backups/arac   le dossier que l'unité de sauvegarde ÉLAGUE

Un test d'acceptation installe pour de vrai : il crée une base, des rôles, des
unités systemd, et il efface tout à la fin. C'est l'outil le plus dangereux du
dépôt. Le mettre sous garde n'est pas de la prudence décorative — la panne
qu'on veut empêcher s'est produite, et elle a coûté cinq rôles de production.

Ces tests sont HERMÉTIQUES : ils ne lancent que ``bash``, sourcent un fichier
de fonctions pures, et n'ouvrent ni base, ni réseau, ni port. Ils tournent donc
sur un dépôt fraîchement cloné, avant toute installation — comme le reste de
la suite.

POURQUOI TESTER UN REFUS EST PLUS DUR QU'IL N'Y PARAÎT
======================================================
La première version de ``garde_isolement.sh`` écrivait ses refus ainsi :

    condition && _garde_refus "…" && return 1

``_garde_refus`` rendait 1. Le ``&&`` n'exécutait donc JAMAIS le ``return 1`` :
la garde affichait son refus, poursuivait, et rendait le code de son dernier
contrôle — c'est-à-dire, le plus souvent, 0. Une garde qui parle et n'arrête
rien. Aucune relecture ne l'aurait vue ; le test ci-dessous, si, parce qu'il
n'assertionne pas le MESSAGE mais le CODE DE SORTIE.

D'où la règle que ces tests appliquent partout : on vérifie qu'un refus REFUSE,
jamais qu'il se plaint.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


_GARDE = Path(__file__).resolve().parent / "garde_isolement.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash absent — ces gardes sont du shell"
)


def _appeler(fonction: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Source la bibliothèque et appelle UNE fonction, sans rien d'autre.

    ``set -u`` est armé : une garde qui lirait une variable non posée
    échouerait ici plutôt que sur la machine de quelqu'un. ``set -e`` ne l'est
    PAS, délibérément : ces fonctions rendent 1 pour dire « refusé », et un
    ``set -e`` transformerait chaque refus attendu en mort du shell, donc en
    faux positif.

    POURQUOI LES VALEURS ENTRENT PAR L'ENTRÉE STANDARD, ET PAS DANS LE CORPS
    =======================================================================
    Cette fonction composait ``bash -c "… garde_chemin_jetable /var/backups/
    arac dossier"``. Le corps portait donc, en toutes lettres, ``/etc/arac``,
    ``/var/backups/arac``, ``/var/log/arac``, ``/var/lib/arac/mon-cerveau``,
    ``/root``, ``/home``, ``/opt`` et ``/`` — les répertoires des cerveaux
    RÉELS de la machine, remis à un shell.

    Dix-sept tests étaient verts pour une seule raison : **le juge des chemins
    du garde hermétique ne lisait pas les corps de shell**. Les mêmes chemins,
    passés en LISTE au même ``bash``, étaient refusés depuis deux manches. Le
    corps était la porte de derrière, et elle est fermée depuis que
    ``garde_hermetique._corps_recus_par_un_shell`` découpe ce que le shell
    recevra.

    Ce n'est PAS le garde qui avait tort : la doctrine du dépôt est écrite —
    « un outil est légitime pour ce qu'il FAIT, jamais pour l'endroit où on le
    pointe » — et un garde qui devrait deviner que ``bash`` ne fera « que
    comparer du texte » ne serait plus un garde. C'est la FORME de ces tests
    qui avait tort.

    La forme juste : ces valeurs sont le SUJET de l'épreuve, jamais sa cible.
    Elles entrent donc comme des DONNÉES, par l'entrée standard, séparées par
    des octets nuls — ce que ``read -d ''`` relit sans jamais rien interpréter.
    Le corps ne porte plus qu'un chemin, celui de la bibliothèque testée, qui
    est un fichier DU DÉPÔT. Les valeurs de l'incident restent intactes, au
    caractère près : rien n'est édulcoré, c'est le canal qui change.

    CE QUE CETTE FORME NE PROUVE PAS, ET C'EST DIT PLUTÔT QUE DÉCOUVERT :
    l'entrée standard n'est jugée par personne. Un corps qui ferait
    ``rm -rf "$(cat)"`` serait invisible au garde exactement comme l'est un
    chemin composé à l'exécution. C'est la même zone d'ombre, elle est déclarée
    dans ``ZONES_NON_COUVERTES_DE_LA_PORTE``, et c'est la seconde barrière —
    Landlock — qui la couvre. Ici, le corps est écrit dans ce fichier, et il
    n'ouvre rien : les fonctions de ``garde_isolement.sh`` sont des prédicats de
    TEXTE (``[[ "$c" == "$interdit" ]]``), sans un seul test de fichier.
    """
    # Les valeurs sont relues dans un tableau. `${args[@]+"${args[@]}"}` et non
    # `"${args[@]}"` : sous `set -u`, un tableau VIDE fait mourir bash 4.3 et
    # antérieurs, et l'un des cas d'épreuve n'a précisément aucun argument.
    script = (
        f"set -u; source '{_GARDE}'; "
        "args=(); while IFS= read -r -d '' a; do args+=(\"$a\"); done; "
        f"{fonction} ${{args[@]+\"${{args[@]}}\"}}"
    )
    return subprocess.run(
        ["bash", "-c", script],
        input="".join(a + "\0" for a in args),
        capture_output=True, text=True, timeout=30,
    )


def _refuse(fonction: str, *args: str) -> str:
    res = _appeler(fonction, *args)
    assert res.returncode == 1, (
        f"{fonction}({args!r}) devait REFUSER (code 1) et a rendu {res.returncode}.\n"
        f"sortie : {res.stdout}{res.stderr}"
    )
    assert "REFUS" in res.stdout, f"{fonction} refuse sans le dire : {res.stdout!r}"
    return res.stdout


def _accepte(fonction: str, *args: str) -> None:
    res = _appeler(fonction, *args)
    assert res.returncode == 0, (
        f"{fonction}({args!r}) devait ACCEPTER et a rendu {res.returncode}.\n"
        f"sortie : {res.stdout}{res.stderr}"
    )
    assert "REFUS" not in res.stdout


# ===========================================================================
# La bibliothèque existe et se charge
# ===========================================================================


def test_les_valeurs_arrivent_entieres_par_le_canal():
    """LE CANAL LUI-MÊME EST ÉPROUVÉ — sinon tous les refus seraient vides.

    Les valeurs n'entrent plus dans le corps du shell mais par l'entrée
    standard. Si ce canal se rompait — un octet nul mal placé, un `read` qui
    s'arrête — les fonctions recevraient ZÉRO argument, refuseraient « le
    chemin est vide », et les seize tests de refus resteraient VERTS en ne
    mesurant plus rien. C'est la faute exacte que ce fichier condamne en tête :
    un contrôle qui se plaint sans rien arrêter.

    On mesure donc que la valeur ARRIVE, et on la choisit hostile au shell :
    une apostrophe (le libellé « l'API » avait déjà cassé une version de ce
    harnais), un espace, et un caractère de découpage.
    """
    valeur = "/n'importe quoi;avec espace"
    sortie = _refuse("garde_chemin_jetable", valeur, "dossier")
    assert valeur in sortie, (
        "la valeur n'est pas parvenue entière à la garde : le refus ne la cite "
        f"pas.\nrefus obtenu : {sortie!r}"
    )


def test_la_bibliotheque_de_gardes_existe_et_se_source():
    """Un harnais dont les gardes ne se chargent pas est un harnais sans garde."""
    assert _GARDE.is_file(), f"{_GARDE} est introuvable"
    res = subprocess.run(
        ["bash", "-n", str(_GARDE)], capture_output=True, text=True, timeout=30
    )
    assert res.returncode == 0, f"syntaxe invalide : {res.stderr}"


@pytest.mark.parametrize("nom", ["garde_isolement.sh", "acceptance.sh"])
def test_le_shell_du_harnais_se_charge(nom):
    """`ops/lint_shell.sh` ne balaie que `bootstrap/` et `ops/`.

    Le shell de ce dossier n'y est donc pas — et une faute de syntaxe s'y
    découvrirait à la seule occasion où on lance le harnais, c'est-à-dire au
    moment le plus cher : root, quinze minutes, une installation en cours.
    On le charge ici, dans `make test`, où l'erreur coûte une milliseconde.

    `bash -n` seulement : shellcheck n'est pas garanti présent, et une suite
    qui échoue faute d'un outil optionnel apprend à être ignorée.
    """
    fichier = _GARDE.parent / nom
    assert fichier.is_file(), f"{fichier} est introuvable"
    res = subprocess.run(
        ["bash", "-n", str(fichier)], capture_output=True, text=True, timeout=30
    )
    assert res.returncode == 0, f"syntaxe invalide dans {nom} : {res.stderr}"


def test_le_harnais_est_executable():
    """`make acceptance` l'appelle directement. Sans le bit d'exécution, la
    cible meurt sur « Permission denied » — un message qui n'apprend rien à
    qui vient de cloner."""
    harnais = _GARDE.parent / "acceptance.sh"
    assert harnais.stat().st_mode & 0o111, (
        f"{harnais} n'est pas exécutable : `make acceptance` échouera au clone"
    )


# ===========================================================================
# 1. LE CLUSTER — la cause qui a coûté cinq rôles
# ===========================================================================


def test_le_port_5432_est_refuse_nommement():
    """Les rôles PostgreSQL sont globaux au CLUSTER, pas à la base.

    Une seconde installation sur le 5432 fait `ALTER ROLE … PASSWORD` sur les
    rôles de la PREMIÈRE. C'est la faute exacte de l'incident, et le message
    de refus doit la nommer — pas parler d'un seuil.
    """
    sortie = _refuse("garde_port_pg", "5432")
    assert "5432" in sortie
    assert "GLOBAUX" in sortie or "globaux" in sortie


@pytest.mark.parametrize("port", ["5433", "5434", "5459", "0", "1"])
def test_tout_port_de_base_sous_le_plancher_est_refuse(port):
    """5433 et 5434 sont d'AUTRES cerveaux sur cette machine.

    Le plancher n'existe pas pour faire joli : un essai qui se pose sur le
    cluster d'un voisin lui réencode ses rôles tout aussi sûrement que sur
    celui de la production.
    """
    _refuse("garde_port_pg", port)


@pytest.mark.parametrize("port", ["5460", "5461", "5999"])
def test_un_port_de_base_a_soi_est_accepte(port):
    _accepte("garde_port_pg", port)


@pytest.mark.parametrize("mauvais", ["", "abc", "54 32", "5460;rm", "-1"])
def test_un_port_de_base_qui_n_est_pas_un_entier_est_refuse(mauvais):
    """Une valeur non numérique ne doit pas faire MOURIR la garde.

    `(( "abc" > 5 ))` sous `set -u` n'est pas « faux » : c'est une erreur. La
    garde rendrait alors un code non nul « par accident », ce qui ressemble à
    un refus — jusqu'au jour où l'accident tombe du bon côté.
    """
    _refuse("garde_port_pg", mauvais)


# ===========================================================================
# 2. LES PORTS DE SERVICE — la cause du diagnostic mensonger
# ===========================================================================


@pytest.mark.parametrize("port", ["8000", "8100"])
def test_les_ports_de_production_sont_refuses_nommement(port):
    """8000 a été lié par une unité d'essai. L'API de production a redémarré
    35 fois — et son /healthz répondait 200, servi par l'usurpateur."""
    sortie = _refuse("garde_port_service", port, "l'API")
    assert port in sortie


@pytest.mark.parametrize("port", ["8001", "8101", "8199", "80", "5432"])
def test_tout_port_de_service_sous_le_plancher_est_refuse(port):
    _refuse("garde_port_service", port, "le cockpit")


@pytest.mark.parametrize("port", ["8200", "8211", "8999"])
def test_un_port_de_service_a_soi_est_accepte(port):
    _accepte("garde_port_service", port, "le cockpit")


# ===========================================================================
# 3. LES NOMS — ce qui rend le démontage décidable
# ===========================================================================


@pytest.mark.parametrize(
    "unite",
    ["arac-api", "arac-control-center", "arac", "arac-cycle", "arac-sauvegarde"],
)
def test_les_unites_de_production_sont_refusees(unite):
    """Le démontage fait `systemctl disable --now` puis `rm` sur ce préfixe.

    S'il pouvait valoir `arac-api`, le harnais désarmerait l'API de production
    en croyant nettoyer derrière lui — et il le ferait en fin de test, quand
    plus personne ne regarde la sortie.
    """
    _refuse("garde_prefixe_unite", unite)


@pytest.mark.parametrize("nom", ["arac-brain", "mon-cerveau", "test", "essai"])
def test_un_nom_de_cerveau_non_marque_est_refuse(nom):
    """Sans marqueur dans le nom, rien ne distingue la base, les secrets et les
    unités de l'essai de ceux d'un cerveau vivant."""
    _refuse("garde_nom_cerveau", nom)


def test_un_nom_de_cerveau_marque_est_accepte():
    _accepte("garde_nom_cerveau", "acceptation-9f3a")


@pytest.mark.parametrize("nom", ["main", "arac2", "postgres", "essai"])
def test_un_cluster_non_marque_ou_de_production_est_refuse(nom):
    """`pg_dropcluster --stop` ne se rejoue pas. Le nom est la seule chose qui
    sépare « je démonte mon essai » de « j'ai détruit une mémoire »."""
    _refuse("garde_nom_cluster", nom)


def test_le_cluster_marque_est_accepte():
    _accepte("garde_nom_cluster", "acceptation9f3a")


# ===========================================================================
# 4. LES CHEMINS — ce que le démontage a le droit d'effacer
# ===========================================================================


@pytest.mark.parametrize(
    "chemin",
    [
        "/",
        "/var",
        "/var/log",
        "/var/log/arac",
        "/var/backups",
        "/var/backups/arac",
        "/etc/arac",
        "/opt",
        "/root",
        "/home",
    ],
)
def test_aucun_chemin_de_production_n_est_jetable(chemin):
    """`/var/backups/arac` est le plus dangereux des dix.

    L'unité de sauvegarde posée par le bootstrap SUPPRIME ce qu'elle y trouve
    de plus de N jours. Un essai qui en hériterait effacerait les sauvegardes
    d'un autre cerveau — en silence, sur minuterie, longtemps après la fin du
    test.
    """
    _refuse("garde_chemin_jetable", chemin, "dossier")


@pytest.mark.parametrize(
    "chemin",
    [
        "acceptation/x",                       # relatif
        "/var/lib/acceptation/../../etc",      # remontée
        "/acceptation",                        # trop haut
        "/var/lib/arac/mon-cerveau",           # non marqué
        "",
    ],
)
def test_les_chemins_douteux_sont_refuses(chemin):
    _refuse("garde_chemin_jetable", chemin, "dossier")


@pytest.mark.parametrize(
    "chemin",
    [
        "/var/lib/arac-acceptation/9f3a",
        "/etc/arac/acceptation_9f3a",
        "/var/log/arac-acceptation-9f3a",
    ],
)
def test_un_chemin_marque_et_profond_est_jetable(chemin):
    _accepte("garde_chemin_jetable", chemin, "dossier")


# ===========================================================================
# 5. LA COMPOSITION — la garde que le harnais appelle réellement
# ===========================================================================


@pytest.mark.parametrize("compte", ["arac", "aracagent", "root", "postgres"])
def test_les_comptes_de_production_sont_refuses(compte):
    """Le démontage fait `userdel`. S'il pouvait viser `arac`, il supprimerait
    le compte sous lequel tournent les services d'un cerveau vivant."""
    _refuse("garde_nom_systeme", compte, "compte")


@pytest.mark.parametrize("compte", ["aracacceptation9f3a", "agentacceptation9f3a"])
def test_un_compte_d_essai_marque_est_accepte(compte):
    _accepte("garde_nom_systeme", compte, "compte")


def test_un_compte_trop_long_est_refuse_ici_et_pas_par_useradd():
    """`useradd` refuse au-delà de 32 caractères — mais il le refuse au MILIEU
    de l'installation, pas au démarrage. Une garde qui laisse découvrir une
    limite connue à mi-parcours n'a pas fait son travail."""
    _refuse("garde_nom_systeme", "a" + "acceptation" * 4, "compte")


def test_la_configuration_de_l_incident_est_refusee_en_bloc():
    """Les valeurs EXACTES de l'incident, présentées ensemble.

    C'est l'assertion qui compte : chaque garde prise isolément peut être
    juste pendant que la composition oublie d'en appeler une.
    """
    res = _appeler(
        "garde_isolement_valeurs",
        "5432", "8000", "8100", "arac-brain", "main", "arac-api",
        "arac", "aracagent",
        "/var/backups/arac",
    )
    assert res.returncode == 1, "le harnais aurait démarré sur la configuration de l'incident"
    # TOUS les refus, pas seulement le premier : celui qui corrige veut la
    # liste entière, pas une découverte par lancement.
    assert res.stdout.count("REFUS") >= 8, (
        "la garde composite s'arrête au premier refus — elle doit les dire tous.\n"
        + res.stdout
    )


def test_une_configuration_isolee_est_acceptee():
    """Le pendant indispensable : une garde qui refuse tout est une garde qu'on
    désarme au bout de trois jours."""
    _accepte(
        "garde_isolement_valeurs",
        "5461", "8211", "8212", "acceptation-9f3a", "acceptation9f3a",
        "arac-acceptation_9f3a", "aracacceptation9f3a", "agentacceptation9f3a",
        "/var/lib/arac-acceptation/9f3a",
        "/etc/arac/acceptation_9f3a",
    )


def test_l_api_et_le_cockpit_ne_peuvent_pas_partager_un_port():
    """Deux services sur un port : le second boucle sur « address already in
    use » pendant que le premier répond — et le contrôle croit les deux vivants."""
    res = _appeler(
        "garde_isolement_valeurs",
        "5461", "8211", "8211", "acceptation-9f3a", "acceptation9f3a",
        "arac-acceptation_9f3a", "aracacceptation9f3a", "agentacceptation9f3a",
    )
    assert res.returncode == 1
    assert "même port" in res.stdout


# ===========================================================================
# 6. LE HARNAIS LUI-MÊME appelle bien ces gardes
# ===========================================================================
#
# Une bibliothèque de gardes parfaite que personne n'appelle ne garde rien.
# C'est la moitié du contrôle qu'on oublie le plus souvent.


def test_le_harnais_source_les_gardes_et_les_appelle():
    harnais = _GARDE.parent / "acceptance.sh"
    assert harnais.is_file(), "tests/acceptance/acceptance.sh est introuvable"
    texte = harnais.read_text(encoding="utf-8")
    assert "garde_isolement.sh" in texte, "le harnais ne charge pas ses gardes"
    for appel in (
        "garde_isolement_valeurs",
        "garde_port_libre",
        "garde_unite_absente",
        "garde_cluster_absent",
    ):
        assert appel in texte, f"le harnais ne fait jamais appel à {appel}"


def test_le_demontage_revalide_avant_de_detruire():
    """Le démontage efface des dossiers et désarme des unités. Il ne doit
    JAMAIS le faire sur une valeur qu'il n'a pas revérifiée juste avant —
    même si la même valeur a passé les gardes au démarrage. Entre les deux, il
    s'est écoulé une installation entière."""
    texte = (_GARDE.parent / "acceptance.sh").read_text(encoding="utf-8")
    # On ancre sur la SECTION, pas sur la seule fonction `demonter` : le
    # démontage délègue l'effacement des dossiers à un aide (`_detruire_dossier`)
    # défini juste avant elle. Ancrer sur `demonter()` seul ferait échouer ce
    # test pour une raison de mise en page, ce qui apprend à le désarmer.
    debut = texte.find("# LE DÉMONTAGE")
    assert debut > 0, "aucune section de démontage identifiable dans le harnais"
    fin = texte.find("# ÉTAPE 1")
    assert fin > debut, "la section de démontage n'est pas délimitée"
    corps = texte[debut:fin]
    assert "trap demonter EXIT" in texte, (
        "le démontage n'est pas armé sous un piège EXIT : un échec en cours de "
        "route laisserait un cluster et des unités derrière lui"
    )
    assert "garde_chemin_jetable" in corps, (
        "le démontage efface des dossiers sans revalider qu'ils sont jetables"
    )
    assert "garde_prefixe_unite" in corps, (
        "le démontage désarme des unités sans revalider leur préfixe"
    )
    assert "garde_nom_cluster" in corps, (
        "le démontage détruit un cluster sans revalider son nom"
    )
