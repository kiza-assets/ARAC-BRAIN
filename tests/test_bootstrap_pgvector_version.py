"""pgvector >= 0.7.0 est exigé tôt, avec le remède PGDG.

Constat (CI d'acceptation) : sur Ubuntu 24.04 nu, `postgresql-16-pgvector`
livre 0.6.0. L'étape 4 l'acceptait (elle ne regardait que la présence), puis
les migrations échouaient sur `type "halfvec" does not exist`.

Ces tests sont hermétiques : ni base, ni réseau, ni root. `pg_lire` et
`pg_lire_base` sont remplacés par des fonctions qui rendent une version fixe.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[1]
_LIB = _RACINE / "bootstrap" / "lib"


def _bash(corps: str) -> subprocess.CompletedProcess:
    script = (
        "set -uo pipefail\n"
        "ARAC_UI_COULEUR=jamais\n"
        "ARAC_DB=base_test\nARAC_PG_SUPERUSER=postgres\nARAC_DB_PORT=5433\n"
        f'source "{_LIB}/ui.sh"\n'
        f'source "{_LIB}/core.sh"\n'
        f'source "{_LIB}/database.sh"\n'
        f"{corps}\n"
    )
    e = dict(os.environ)
    e["ARAC_UI_COULEUR"] = "jamais"
    return subprocess.run(["bash", "-c", script], capture_output=True,
                          text=True, env=e, timeout=120)


def _rc(version: str, minimum: str = "0.7.0") -> int:
    r = _bash(f'version_au_moins "{version}" "{minimum}"; echo "RC=$?"')
    assert "RC=" in r.stdout, r.stdout + r.stderr
    return int(r.stdout.rsplit("RC=", 1)[1].split()[0])


def test_le_minimum_est_defini_une_fois() -> None:
    r = _bash('echo "MIN=$ARAC_PGVECTOR_MIN"')
    assert "MIN=0.7.0" in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize("version,attendu", [
    ("0.6.0", 1),    # Ubuntu 24.04 : refusé
    ("0.6.9", 1),
    ("0.7.0", 0),    # le seuil lui-même
    ("0.8.2", 0),    # PGDG
    ("0.10.0", 0),   # numérique, pas lexical
    ("1.0", 0),
    ("0.7", 0),
])
def test_comparaison_de_versions(version: str, attendu: int) -> None:
    assert _rc(version) == attendu


@pytest.mark.parametrize("illisible", ["", "abc", "0.7.0-beta", "v0.8.2", "0", "0.7.0.1"])
def test_vide_ou_illisible_est_refuse(illisible: str) -> None:
    assert _rc(illisible) == 1


def _etape_4(dispo: str, installe: str = "") -> subprocess.CompletedProcess:
    # On court-circuite l'en-tête et le root : seule la garde est éprouvée.
    return _bash(
        "etape_entete() { :; }\n"
        "exiger_root() { :; }\n"
        f'pg_lire() {{ echo "{dispo}"; }}\n'
        f'pg_lire_base() {{ echo "{installe}"; }}\n'
        "SIMULATION=1\n"
        "etape_vecteurs; echo \"RC=$?\"\n"
    )


def test_ubuntu_0_6_0_est_refuse_avec_le_remede_pgdg() -> None:
    r = _etape_4("0.6.0")
    sortie = r.stdout + r.stderr
    assert r.returncode == 7, sortie
    assert "trop ancien" in sortie
    assert "apt.postgresql.org.sh" in sortie
    assert "postgresql-common" in sortie
    assert "postgresql-16-pgvector" in sortie


def test_extension_deja_creee_en_version_ancienne_est_refusee() -> None:
    r = _etape_4("0.8.2", installe="0.6.0")
    sortie = r.stdout + r.stderr
    assert r.returncode == 7, sortie
    assert "ALTER EXTENSION vector UPDATE" in sortie
    assert "-p 5433" in sortie, "la commande imprimée doit porter son port"


def test_pgvector_absent_donne_aussi_le_remede_pgdg() -> None:
    r = _etape_4("")
    assert r.returncode == 7, r.stdout + r.stderr
    assert "apt.postgresql.org.sh" in r.stdout + r.stderr


def test_pgvector_recent_passe_la_garde() -> None:
    r = _etape_4("0.8.2", installe="0.8.2")
    sortie = r.stdout + r.stderr
    # La garde est franchie : on atteint le plan (« disponible : v… »).
    # La suite de l'étape (gabarit) exige un environnement complet : hors sujet.
    assert "disponible : v0.8.2" in sortie, sortie
    assert "trop ancien" not in sortie
