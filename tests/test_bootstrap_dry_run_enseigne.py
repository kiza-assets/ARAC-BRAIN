"""`--dry-run` doit DÉROULER les onze étapes — c'est la preuve exécutable de F3.

CE QUE CE FICHIER GARDE, ET POURQUOI IL EXISTE
==============================================

F3 dit : « chaque étape dit pourquoi elle existe, ce qu'elle construit, et ce que
cela changera ». `ui.sh` rend la règle mécanique — `etape_entete` REFUSE de
s'afficher si l'une des trois manque. Mais une règle mécanique ne prouve rien
si l'en-tête n'est jamais atteint.

Et il a cessé de l'être. Un fichier d'avancement laissé par un passage réel
(`.bootstrap-install.<base>.state`) fait sauter les étapes « déjà accomplies » —
y compris en SIMULATION, où rien n'est fait, rien n'est écrit, et où sauter une
étape ne fait donc économiser que sa LEÇON. `--dry-run` est passé de onze
en-têtes à quatre. La commande que `GOAL.md` cite comme preuve du bootstrap qui
enseigne ne montrait plus ce qu'elle est censée montrer.

Deux tests, et le second est celui qui aurait attrapé la faute :
  1. une simulation vierge déroule les dix étapes, chacune avec sa triade ;
  2. une simulation lancée avec un avancement ANTÉRIEUR en déroule tout autant.
     La simulation n'accomplit rien : elle n'a rien à sauter.

Ni base, ni réseau — MAINTENANT. Cette phrase était fausse : la simulation
interrogeait le cluster PostgreSQL de la machine (`sudo -u postgres psql -p
5432`), l'inventaire des unités du voisin et les ports 8000/8100. Elle tourne
désormais devant un décor de machine NEUVE (voir `_THEATRE` plus bas), et son
verdict ne dépend plus de l'hôte qui la fait tourner.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[1]
_BOOTSTRAP = _RACINE / "bootstrap" / "bootstrap.sh"

#: Ce qu'une simulation doit dérouler. Lu dans `core.sh` plutôt que recopié :
#: ajouter une étape sans l'enseigner doit rendre ce test rouge tout seul.
_ETAPES_RE = re.compile(r"^ETAPES=\((.*)\)\s*$", re.MULTILINE)
_TITRE_RE = re.compile(r"^\s*\[(\w+)\]=\"([^\"]+)\"", re.MULTILINE)
_ENTETE_RE = re.compile(r"^\s+ÉTAPE\s+(\d+)\s*/\s*(\d+)\s+—\s+(.+?)\s*$", re.MULTILINE)


def _core() -> str:
    return (_RACINE / "bootstrap" / "lib" / "core.sh").read_text(encoding="utf-8")


def _etapes() -> list[str]:
    m = _ETAPES_RE.search(_core())
    assert m, "ETAPES=(…) introuvable dans core.sh"
    return m.group(1).split()


def _titres() -> dict[str, str]:
    return dict(_TITRE_RE.findall(_core()))


@pytest.fixture(scope="module")
def maison(tmp_path_factory) -> Path:
    """Un ARAC_HOME d'emprunt : le dépôt par liens, une description à nous.

    Aucune écriture dans le dépôt, aucune dépendance à une installation. Les
    répertoires lourds sont liés, pas copiés ; seul `config/` est à nous, parce
    que c'est lui qui porte l'identité du cerveau simulé.
    """
    d = tmp_path_factory.mktemp("arac_home")
    for nom in ("app", "agents", "control_center", "db", "bootstrap", "scripts",
                "ops", "alembic.ini", "requirements.txt", "arac_runtime.py",
                ".env.example", "schemas", "static"):
        src = _RACINE / nom
        if src.exists():
            (d / nom).symlink_to(src)

    (d / "config").mkdir()
    shutil.copy(_RACINE / "config" / "scopes.example.toml", d / "config" / "scopes.toml")
    (d / "config" / "brain.toml").write_text(
        "\n".join([
            "# Description d'essai, écrite par la suite de tests.",
            "",
            "[brain]",
            'owner = "Alice"',
            'name = "cerveau-de-test"',
            "",
            "[source]",
            'node_id = "poste-de-test"',
            "",
        ]),
        encoding="utf-8",
    )
    return d


# ---------------------------------------------------------------------------
# LA MACHINE NEUVE — un décor, parce que la simulation en interrogeait une VRAIE
# ---------------------------------------------------------------------------
#
# Ce fichier affirmait, en tête : « Ni base, ni réseau : `--dry-run` n'ouvre la
# base qu'en lecture ». C'était faux, et mesurable. Un mouchard posé devant
# chaque binaire du PATH pendant `make test` a relevé, venant de CE test :
#
#   sudo -u postgres psql -p 5432 -d postgres -tAc "SELECT 1"
#   sudo -u postgres psql -p 5432 -d postgres -tAc "SELECT default_version
#        FROM pg_available_extensions WHERE name='vector'"
#   sudo -u postgres psql -p 5432 -d postgres -tAc "SELECT 1 FROM pg_database
#        WHERE datname='cerveau_de_test'"
#   systemctl list-unit-files --no-legend arac-*-api.service arac-*-cockpit.service
#   ss -ltnH sport = :8000     ss -ltnH sport = :8100
#
# — c'est-à-dire le cluster de PRODUCTION (5432, dont les rôles sont GLOBAUX),
# l'inventaire des unités du VOISIN, et les deux ports de production. Une
# simulation qui interroge la machine n'est pas une simulation : son verdict
# dépend de l'endroit où elle tourne, et sur la machine de l'auteur elle
# répondait « pgvector est là » parce que SON cerveau l'y avait installé.
#
# On lui donne donc la machine qu'elle prétend décrire : une machine NEUVE, où
# PostgreSQL tourne, où pgvector est disponible, où aucun cerveau n'existe
# encore et où aucun port n'est tenu. Le décor est déterministe ; le test cesse
# de dépendre de son hôte.
#
# Si la simulation se met un jour à interroger une ressource que ce décor ne
# joue pas, le PATH de refus l'arrête et ce test devient ROUGE — c'est-à-dire
# qu'un nouvel accès à la machine se voit le jour où il apparaît, sans que
# personne ait eu à l'ajouter à une liste.

_THEATRE = {
    # `sudo` ne donne aucun privilège ici : il retire ses propres options et
    # relance la commande par le PATH — donc par les doubles ci-dessous.
    "sudo": """#!/bin/sh
while [ $# -gt 0 ]; do
  case "$1" in
    -n|-H|-E|-k) shift ;;
    -u) shift 2 ;;
    --) shift; break ;;
    -*) shift ;;
    *) break ;;
  esac
done
[ $# -gt 0 ] || exit 0
exec "$@"
""",
    # Un PostgreSQL 16 vivant, avec pgvector disponible et aucun cerveau posé.
    "psql": """#!/bin/sh
q=$*
case "$q" in
  *--version*)                     echo "psql (PostgreSQL) 16.13"; exit 0 ;;
  *pg_available_extensions*)       echo "0.7.0"; exit 0 ;;
  *pg_database*)                   exit 0 ;;
  *pg_roles*)                      exit 0 ;;
  *server_version*)                echo "16.13"; exit 0 ;;
  *"SELECT 1"*)                    echo "1"; exit 0 ;;
esac
exit 0
""",
    # Aucune unité arac sur cette machine, et rien d'actif.
    "systemctl": """#!/bin/sh
case "$*" in
  *is-active*)  echo inactive; exit 3 ;;
  *is-enabled*) echo disabled; exit 1 ;;
esac
exit 0
""",
    "systemd-run": "#!/bin/sh\nexit 0\n",
    # Aucun port tenu.
    "ss": "#!/bin/sh\nexit 0\n",
    # UTC, et non le fuseau de qui que ce soit : F1 refuse un fuseau gravé, et
    # il a raison jusque dans un décor de test.
    "timedatectl": '#!/bin/sh\necho "UTC"\nexit 0\n',
    "pg_isready": "#!/bin/sh\necho accepting connections\nexit 0\n",
    "pg_lsclusters": "#!/bin/sh\necho '16 main 5432 online postgres'\nexit 0\n",
    "getent": "#!/bin/sh\nexit 2\n",
}


def _machine_neuve(dossier: Path) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    for nom, corps in _THEATRE.items():
        (dossier / nom).write_text(corps, encoding="utf-8")
        (dossier / nom).chmod(0o755)
    return dossier


def _simuler(maison: Path, etat: Path, theatre: Path) -> str:
    env = dict(os.environ)
    env.update({
        "ARAC_HOME": str(maison),
        "ARAC_ETAT": str(etat),
        "ARAC_UI_COULEUR": "jamais",
        "NO_COLOR": "1",
        "LC_ALL": env.get("LC_ALL", "C.UTF-8"),
        "PATH": f"{theatre}:{env.get('PATH', '')}",
    })
    r = subprocess.run(
        ["bash", str(_BOOTSTRAP), "--dry-run"],
        capture_output=True, text=True, env=env, cwd=str(maison), timeout=300,
    )
    assert r.returncode == 0, (
        f"--dry-run a rendu {r.returncode} : une simulation n'échoue pas.\n"
        + r.stdout[-4000:] + r.stderr[-2000:]
    )
    return r.stdout


def _entetes(sortie: str) -> list[str]:
    return [m.group(3) for m in _ENTETE_RE.finditer(sortie)]


def test_la_simulation_deroule_toutes_les_etapes(maison, tmp_path):
    """Chaque étape déclarée annonce ses trois raisons, en simulation aussi."""
    sortie = _simuler(maison, tmp_path / "vierge.state",
                      _machine_neuve(tmp_path / "bin"))
    vus = _entetes(sortie)
    titres = _titres()
    attendus = [titres[e] for e in _etapes()]

    manquants = [t for t in attendus if t not in vus]
    assert not manquants, (
        "Ces étapes n'ont PAS annoncé leurs trois raisons pendant la "
        "simulation :\n  " + "\n  ".join(manquants)
        + f"\n\n{len(vus)} en-tête(s) déroulé(s) pour {len(attendus)} étape(s)."
    )
    assert len(vus) >= len(attendus), (
        f"{len(vus)} en-tête(s) pour {len(attendus)} étapes : le bootstrap "
        f"n'enseigne plus tout ce qu'il fait."
    )
    # Les trois raisons, pas seulement le titre : `ui.sh` refuse d'afficher un
    # en-tête incomplet, mais rien ne prouvait qu'on les atteignait tous.
    for etiquette in ("Pourquoi", "Construit", "Conséquence"):
        assert sortie.count(etiquette) >= len(attendus), (
            f"« {etiquette} » n'apparaît que {sortie.count(etiquette)} fois "
            f"pour {len(attendus)} étapes."
        )


def test_un_avancement_anterieur_ne_fait_pas_taire_la_simulation(maison, tmp_path):
    """Une simulation n'accomplit rien : elle n'a donc rien à sauter.

    C'est LA régression. Un `.bootstrap-install.<base>.state` oublié dans un
    dépôt — le sien, ou celui qu'on vient de cloner — suffisait à faire tomber
    la démonstration de F3 de onze en-têtes à quatre, sans qu'aucune ligne de
    pédagogie ait été touchée.
    """
    etat = tmp_path / "deja-fait.state"
    etat.write_text(" ".join(_etapes()) + "\n", encoding="utf-8")

    sortie = _simuler(maison, etat, _machine_neuve(tmp_path / "bin"))
    vus = _entetes(sortie)
    titres = _titres()
    attendus = [titres[e] for e in _etapes()]

    manquants = [t for t in attendus if t not in vus]
    assert not manquants, (
        "Un avancement antérieur a fait TAIRE ces étapes en simulation :\n  "
        + "\n  ".join(manquants)
        + "\n\nUne simulation n'écrit rien : sauter une étape n'y économise "
          "que sa leçon."
    )
