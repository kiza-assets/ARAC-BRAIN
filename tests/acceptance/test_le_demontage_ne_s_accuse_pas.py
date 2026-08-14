"""Le démontage doit demander À QUI est la socket avant de s'en accuser.

CE QUE CE FICHIER GARDE
=======================

`make acceptance` a rendu ceci, sur une exécution où l'installation avait
échoué à l'étape 3 — donc où aucun service n'avait jamais démarré, donc où le
harnais n'avait jamais lié le moindre port :

    ✗ le port 8211 est encore tenu
    ✗ le port 8231 est encore tenu
    ✗ LA MACHINE N'EST PAS REVENUE À SON ÉTAT INITIAL

Constaté dans la seconde qui suivait : les deux ports étaient tenus par des
uvicorn tiers, arrivés entre le constat de liberté et le moment du bind, et
déjà partis. Le harnais s'imputait les sockets d'un inconnu.

C'est la faute même que ce chantier combat — un verdict rendu sur un NUMÉRO,
sans demander qui répond derrière — dans l'outil qui juge tous les autres. Le
dépôt sait pourtant faire : `bootstrap/checks/verify_install.sh` remonte
socket → PID → cgroup → environnement pour NOMMER le cerveau derrière une
socket. Le harnais ne s'en servait pas sur lui-même.

CE QU'ON ÉPROUVE ICI, ET AVEC QUOI
==================================

`proprietaire_du_port` décide à partir de trois preuves dérivées : le cgroup
nomme une unité de CE cerveau, l'environnement porte `ARAC_DB=<ce cerveau>`, ou
le processus descend du harnais. On l'exerce sur de VRAIS processus — le seul
matériau qui vaille pour un contrôle qui lit `/proc` — sans jamais interroger
un service : les processus sont ceux que le test vient lui-même de lancer.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
HARNAIS = RACINE / "tests" / "acceptance" / "acceptance.sh"


def _decider(pid: str, arac_db: str = "cerveau_du_harnais") -> str:
    """Appelle `proprietaire_du_port` en isolant la fonction de tout le reste.

    On extrait la fonction du harnais plutôt que de sourcer le fichier entier :
    `acceptance.sh` refuse de démarrer hors des conditions qu'il exige, et
    c'est très bien ainsi.
    """
    texte = HARNAIS.read_text(encoding="utf-8")
    debut = texte.index("proprietaire_du_port() {")
    fin = texte.index("\n}\n", debut) + 3
    fonction = texte[debut:fin]
    script = (
        "set -u\n"
        f"ARAC_DB={arac_db}\n"
        f"PREFIXE_UNITE=arac-{arac_db}\n"
        f"{fonction}\n"
        f"proprietaire_du_port {pid}\n"
    )
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_un_processus_etranger_n_est_pas_un_reste_du_harnais():
    """LA RÉGRESSION. Un tiers qui tient le port ne doit pas être imputé.

    On prend le processus pytest lui-même : il ne descend pas d'un harnais
    d'acceptation, son cgroup ne nomme aucune unité de ce cerveau, et son
    environnement ne porte pas cet `ARAC_DB`. Verdict attendu : « tiers ».
    """
    assert _decider(str(os.getpid())) == "tiers", (
        "Le harnais s'attribue une socket qui n'est pas la sienne. C'est ce qui "
        "a fait déclarer « LA MACHINE N'EST PAS REVENUE À SON ÉTAT INITIAL » "
        "après une exécution qui n'avait jamais lié un seul port."
    )


def test_un_processus_qui_porte_notre_cerveau_est_a_nous():
    """L'autre moitié : le contrôle doit rester capable d'accuser à raison.

    Un garde qui ne dit jamais « c'est à moi » est aussi inutile qu'un garde
    qui le dit toujours. On lance un processus qui porte `ARAC_DB` du cerveau
    d'essai — ce que systemd pose dans l'environnement des unités — et on exige
    « nous ».
    """
    fils = subprocess.Popen(
        [sys.executable, "-c", "import sys, time; sys.stdout.write('pret\\n'); "
                               "sys.stdout.flush(); time.sleep(30)"],
        env={**os.environ, "ARAC_DB": "cerveau_du_harnais"},
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert fils.stdout is not None
        fils.stdout.readline()  # le fils a démarré : son /proc est en place
        assert _decider(str(fils.pid)) == "nous", (
            "Le harnais ne reconnaît plus SA propre socket : un vrai reste "
            "passerait alors pour un tiers, et le démontage se déclarerait "
            "propre en laissant un service debout."
        )
    finally:
        fils.kill()
        fils.wait(timeout=10)


@pytest.mark.parametrize("pid", ["", "0", "999999999", "pas-un-nombre", "-1"])
def test_ne_pas_savoir_n_est_ni_une_accusation_ni_une_absolution(pid):
    """Fail-closed : sans PID lisible, on rend « inconnu », jamais « tiers ».

    Rendre « tiers » quand on ne sait pas reviendrait à s'absoudre par défaut —
    c'est-à-dire à déclarer la machine propre parce qu'on n'a pas pu regarder.
    L'appelant, lui, compte « inconnu » comme un reste ET dit que c'est une
    impossibilité de mesurer, pas une preuve.
    """
    assert _decider(pid) == "inconnu"


def test_le_harnais_dit_qu_un_tiers_n_est_pas_un_reste():
    """Le message compte autant que le verdict.

    Un utilisateur qui lit « le port est encore tenu » part chercher une fuite.
    Il doit lire, à la place, à qui est ce port — et que ce n'est pas un reste
    de son exécution.
    """
    texte = HARNAIS.read_text(encoding="utf-8")
    assert "proprietaire_du_port" in texte
    assert "n'est PAS \\\nun reste de cette exécution" in texte or (
        "un reste de cette exécution" in texte), (
        "le harnais doit dire explicitement qu'un port tenu par un tiers n'est "
        "pas un reste de son démontage"
    )
    assert "je ne peux pas dire par qui" in texte, (
        "le cas « je n'ai pas pu savoir » doit se distinguer, à l'écran, du cas "
        "« c'est à moi » — sinon on rend un verdict sur une mesure absente."
    )
