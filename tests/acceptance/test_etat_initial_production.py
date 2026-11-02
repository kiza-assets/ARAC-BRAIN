"""L'ÉTAT INITIAL DE LA MACHINE — vierge, saine ou douteuse — décidé sans root.

Le test d'acceptation exigeait une production saine avant de commencer. Sur un
exécuteur GitHub nu (run 41543766719) il n'y en a aucune, et il s'arrêtait en
code 3 : « LA PRODUCTION N'EST PAS SAINE AVANT MÊME DE COMMENCER ». Le contrôle
sépare maintenant trois cas :

    (a) aucune production installée        → « vierge » : état initial valide
    (b) production présente et saine       → contrôles d'avant, inchangés
    (c) production présente mais douteuse  → STOP, comme avant

Ce fichier exerce le prédicat PUR ``etat_initial_production`` (a vs b/c) et
``souvenirs_n_ont_pas_baisse`` (le seuil n'est plus un chiffre personnel). Il
est HERMÉTIQUE : ``bash`` seul, ni base, ni réseau, ni root. La distinction b/c
(saine ou douteuse) se joue sur de vrais services : elle ne se prouve qu'en
exécutant ``acceptance.sh``, ce qu'on ne fait pas sur une machine de production.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parent
_GARDE = _DIR / "garde_isolement.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash absent — ces gardes sont du shell"
)


def _appeler(fonction: str, *args: str) -> subprocess.CompletedProcess[str]:
    # Les valeurs sont passées comme arguments positionnels, jamais interpolées.
    return subprocess.run(
        ["bash", "-c", f"set -u; source '{_GARDE}'; {fonction} \"$@\"", "_", *args],
        capture_output=True, text=True, timeout=30,
    )


def _etat(unites: str, ecoute: str, base: str, roles: str = "0") -> str:
    res = _appeler("etat_initial_production", unites, ecoute, base, roles)
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


def test_a_machine_vierge_est_un_etat_initial_valide():
    # Unités d'acceptation seules : exclues en amont, donc comptées 0.
    assert _etat("0", "0", "absente", "0") == "vierge"


@pytest.mark.parametrize(
    "unites,ecoute,base,roles",
    [
        ("2", "1", "presente", "5"),   # (b) production historique complète
        ("2", "0", "presente", "5"),   # (c) unités installées, API muette
        ("1", "0", "absente", "0"),    # (c) une seule unité : installation partielle
        ("2", "1", "inconnue", "5"),   # (c) base illisible
        ("0", "1", "absente", "0"),    # (c) un inconnu tient le 8000 ou le 8100
        ("0", "0", "presente", "0"),   # base de cerveau (ex. « perso ») sans unités
        ("0", "0", "absente", "5"),    # rôles arac_* sur le 5432
        ("5", "1", "presente", "5"),   # cerveau public « perso » installé : 5 unités arac-perso-*
        ("inconnu", "0", "absente", "0"),  # unités illisibles
        ("0", "0", "absente", "inconnu"),  # rôles illisibles
        ("0", "0", "inconnue", "0"),   # dans le doute, jamais « vierge »
    ],
)
def test_b_c_une_trace_de_cerveau_la_protege_comme_avant(unites, ecoute, base, roles):
    assert _etat(unites, ecoute, base, roles) == "presente"


@pytest.mark.parametrize(
    "args",
    [("", "", "", ""), ("x", "0", "absente", "0"), ("0", "oui", "absente", "0"),
     ("0", "0", "ABSENTE", "0"), ("0", "0", "absente", "")],
)
def test_une_valeur_inattendue_n_est_jamais_lue_comme_vierge(args):
    assert _etat(*args) == "presente"


def test_sans_argument_le_predicat_ne_conclut_pas_vierge():
    res = subprocess.run(
        ["bash", "-c", f"set -u; source '{_GARDE}'; etat_initial_production"],
        capture_output=True, text=True, timeout=30,
    )
    assert res.stdout.strip() == "presente"


def test_le_quatrieme_argument_est_obligatoire():
    # Trois valeurs « vierges » ne suffisent plus : les rôles doivent être lus.
    assert _appeler("etat_initial_production", "0", "0", "absente").stdout.strip() == "presente"


@pytest.mark.parametrize(
    "avant,apres,attendu",
    [("10", "10", 0), ("10", "11", 0), ("0", "0", 0), ("10", "9", 1),
     ("10", "", 1), ("", "10", 1), ("abc", "10", 1), ("10", "x", 1)],
)
def test_les_souvenirs_ne_doivent_pas_baisser(avant, apres, attendu):
    assert _appeler("souvenirs_n_ont_pas_baisse", avant, apres).returncode == attendu


def test_aucun_seuil_personnel_dans_le_test_d_acceptation():
    """Le chiffre d'un cerveau particulier (1914) ne doit plus décider."""
    for f in _DIR.glob("*.sh"):
        assert not re.search(r"\b1914\b", f.read_text(encoding="utf-8")), f.name
