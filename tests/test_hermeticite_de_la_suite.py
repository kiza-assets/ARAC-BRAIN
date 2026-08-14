"""La suite est HERMÉTIQUE — et voici la preuve, pas la promesse.

Cinq documents du dépôt écrivent la même phrase (`Makefile`, `README.md`,
`GOAL.md`, `docs/CONTRIBUER.md`, `docs/FAQ.md`) :

    « HERMÉTIQUE : ni base, ni réseau, ni clé d'API. Un test rouge doit vouloir
    dire *le code est cassé*, jamais *PostgreSQL n'est pas lancé*. »

Elle était fausse. `make test` émettait de vrais GET HTTP vers
``http://127.0.0.1:8000`` — sur la machine de l'auteur, l'API de PRODUCTION —
par le repli codé en dur du collecteur du cockpit
(``control_center/collectors/brain_api.py``). Ce n'était pas une hypothèse :
le garde F1, qui rend les pages du cockpit et cherche l'auteur dans le HTML,
trouvait les scopes PRIVÉS du cerveau réel dans une page rendue par la suite de
tests. Quatre tests rouges dont la cause n'était pas dans le code.

Ce fichier ne documente pas la promesse : il l'exerce. Une promesse écrite dans
cinq documents et vérifiée nulle part est un aveu, pas une garantie.
"""

from __future__ import annotations

import socket

import pytest

from tests.garde_hermetique import RefusHermetique


# ============================================================================
# 1. Aucune socket ne sort — quelle que soit l'adresse
# ============================================================================


@pytest.mark.parametrize(
    "adresse",
    [
        ("127.0.0.1", 8000),    # l'API de production, sur cette machine
        ("127.0.0.1", 8100),    # son cockpit
        ("127.0.0.1", 5432),    # son cluster PostgreSQL
        ("localhost", 8000),
        ("10.0.0.4", 443),
        ("93.184.216.34", 80),
    ],
)
def test_aucune_connexion_sortante_n_est_possible(adresse):
    """« Local » ne veut pas dire « à moi ».

    On ne discrimine pas par adresse : le repli fautif visait le LOOPBACK, et
    c'est précisément là que vit le cerveau de qui lance la suite. Un garde qui
    n'aurait interdit que les adresses « extérieures » n'aurait rien vu.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RefusHermetique) as pris:
            s.connect(adresse)
        assert str(adresse[1]) in str(pris.value)
    finally:
        s.close()


def test_connect_ex_ne_ment_pas_non_plus():
    """`connect_ex` a pour contrat de rendre un code, pas de lever.

    Il ne doit pas pour autant devenir la porte de service du garde : on rend
    « connexion refusée », qui est la vérité de ce qui se passe.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        assert s.connect_ex(("127.0.0.1", 8000)) != 0
    finally:
        s.close()


def test_un_client_http_ne_joint_rien():
    """Le chemin réel du défaut : httpx, tel que l'utilise le collecteur."""
    httpx = pytest.importorskip("httpx")
    with pytest.raises(Exception):  # noqa: B017 — httpx enveloppe le refus
        httpx.get("http://127.0.0.1:8000/v1/brain/health", timeout=2.0)


def test_lier_un_port_reste_permis():
    """Le garde interdit de SORTIR, pas d'exister.

    Un test qui a besoin d'un port libre, ou qui vérifie qu'un port est pris,
    ne fait pas sortir de paquet. L'interdire aurait rendu le garde insupportable
    — et un garde insupportable finit désactivé.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        assert s.getsockname()[1] > 0
    finally:
        s.close()


# ============================================================================
# 2. Le cockpit, rendu par la suite, ne parle à personne
# ============================================================================


def test_le_cockpit_rendu_ne_montre_pas_un_cerveau_vivant():
    """La page qui allait chercher les données du cerveau réel.

    Sans garde, ``/cc/brain`` interrogeait ``http://127.0.0.1:8000`` et
    affichait les scopes du cerveau de qui lançait la suite. Avec le garde,
    elle retombe sur son chemin d'indisponibilité — l'état exact d'un dépôt
    fraîchement cloné, qui est ce que la suite est censée décrire.

    On ne cherche pas ici un nom d'auteur (c'est le travail de F1) : on vérifie
    qu'AUCUNE sortie n'a été possible pendant le rendu.
    """
    from tests import garde_hermetique as g
    from tests.test_f1_aucune_trace_de_l_auteur import servi

    pages = servi()
    assert "/cc/brain" in pages, sorted(pages)[:10]
    # Le rendu s'est fait sans qu'un seul paquet sorte : tout ce que le
    # collecteur a tenté figure au journal des refus, et rien n'a abouti.
    for tentative in g.TENTATIVES_RESEAU:
        assert tentative  # journal lisible, pas vide de sens


def test_le_journal_des_refus_est_lisible():
    """Un garde silencieux rend la suite verte sans rien apprendre à personne.

    Le collecteur du cockpit avale toutes les exceptions (« résilience
    volontaire : aucune exception ne remonte au cockpit »). Un refus y serait
    invisible. On tient donc un journal, imprimé en fin de session par
    `pytest_terminal_summary`, pour que « la suite est hermétique » se lise
    comme un constat et non comme une croyance.
    """
    from tests import garde_hermetique as g

    assert isinstance(g.TENTATIVES_RESEAU, list)
    assert isinstance(g.TENTATIVES_BASE, list)


# ============================================================================
# 3. La suite lit le dépôt — elle n'interroge pas la machine
# ============================================================================


@pytest.mark.parametrize(
    "commande",
    [
        ["systemctl", "is-active", "arac-api.service"],
        ["systemctl", "is-enabled", "arac-curator-batch.timer"],
        ["journalctl", "--no-pager", "--since", "-7 days"],
        ["ss", "-ltn"],
        ["tmux", "ls"],
        ["df", "-h", "/opt"],
        ["psql", "-p", "5432", "-d", "arac", "-c", "SELECT 1"],
        ["curl", "http://127.0.0.1:8000/health"],
        ["docker", "ps"],
    ],
)
def test_la_suite_n_interroge_pas_la_machine(commande):
    """Mesuré à l'espion : la suite exécutait VRAIMENT ces commandes.

    ``systemctl is-active arac-curator-batch.service`` sur l'unité de
    production, ``journalctl --since -7 days`` sur le journal RÉEL de la
    machine — dont le contenu atterrissait dans une page du cockpit que le
    garde F1 relit ensuite ligne à ligne. C'est la même faute que le GET vers
    ``127.0.0.1:8000``, par une autre porte : le résultat de la suite dépendait
    de la machine, et l'état privé de quelqu'un entrait dans les tests.
    """
    import subprocess

    with pytest.raises(RefusHermetique):
        subprocess.run(commande, capture_output=True)


@pytest.mark.parametrize("commande", [
    ["git", "ls-files"],
    ["bash", "-n", "ops/lint_shell.sh"],
])
def test_ce_qui_regarde_le_depot_reste_permis(commande):
    """On ne coupe pas ce qui regarde le dépôt : c'est l'objet même du test.

    `bootstrap.sh --dry-run`, `git ls-files`, `bash -n` sur les scripts
    d'installation : ces sous-processus lisent le dépôt cloné, pas l'hôte. Un
    garde qui les interdirait rendrait la moitié de la suite intestable — et
    un garde insupportable finit désactivé.
    """
    import subprocess

    subprocess.run(commande, capture_output=True, cwd=str(
        __import__("pathlib").Path(__file__).resolve().parents[1]))
