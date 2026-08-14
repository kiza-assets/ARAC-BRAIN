"""Les unités engendrées peuvent-elles VRAIMENT exécuter leur binaire ?

CE QUE CE FICHIER GARDE, ET POURQUOI IL EXISTE
==============================================

L'étape 9 portait un garde remarquable — il nommait le répertoire fautif, disait
sous quelle identité il avait testé, montrait la trace qu'on verrait, et refusait
de trancher à la place de l'utilisateur. Il reposait pourtant sur un modèle
INCOMPLET de la panne : il ne connaissait que la traversabilité des répertoires.

Or les unités qu'il laisse écrire portent `ProtectHome=true`, qui ne lit aucune
permission : systemd monte un tmpfs VIDE par-dessus /home et /root pour le
service. Un dépôt cloné dans /root — le geste le plus naturel quand on ouvre un
shell root sur un serveur neuf — ou dans ~, emplacement explicitement béni par
la documentation, devient donc introuvable POUR LE SERVICE, alors même que le
garde vient de le déclarer atteignable. Pire : le remède n° 2 qu'il proposait
lui-même (`chmod o+x /root`) faisait PASSER le garde et fabriquait très
exactement la boucle 203/EXEC qu'il promettait d'empêcher.

Le remède n° 1, « recommandé », avait un autre défaut : `sudo mv $ARAC_HOME
/opt/<base>` casse l'environnement Python, dont tous les scripts de `.venv/bin`
portent un shebang ABSOLU vers l'ancien chemin. Un remède qui casse ce qu'il
répare est pire que le défaut.

Ce fichier borne les deux : la VALEUR de ProtectHome selon l'emplacement du
dépôt, et le CONTENU des deux remèdes. Il vérifie enfin que le garde éprouve la
panne comme systemd la vivra — en interceptant l'appel réel à `systemd-run`.

Ni base, ni réseau, ni root : on engendre les unités et on les lit.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[1]
_LIB = _RACINE / "bootstrap" / "lib"

#: Le décor minimal pour engendrer une unité : ce que l'étape 2 aurait calculé.
_PRELUDE = """
set -uo pipefail
ARAC_HOME={home}
ARAC_VENV={home}/.venv
ARAC_DB=cerveau_test
ARAC_SCHEMA=arac
ARAC_NODE_ID=poste-de-test
ARAC_ENV_FILE=/etc/arac/cerveau_test/arac.env
ARAC_SECRETS_COCKPIT=/etc/arac/cerveau_test/cockpit.env
ARAC_SERVICE_USER=arac
ARAC_AGENT_USER=aracagent
ARAC_AGENT_HOME=/var/lib/arac/cerveau_test
ARAC_LOG_DIR=/var/log/arac
ARAC_BACKUP_DIR=/var/backups/arac
ARAC_BACKUP_RETENTION=14
ARAC_API_PORT=8000
ARAC_COCKPIT_PORT=8100
ARAC_API_APP=app.main:app
ARAC_COCKPIT_APP=control_center.app:app
ARAC_CYCLE_MODULE=agents.cortex.cycle
ARAC_CYCLES="04:00 13:00 21:00"
ARAC_CYCLE_TZ=UTC
ARAC_UI_COULEUR=jamais
BRAIN_NOM=cerveau-de-test
BRAIN_OWNER=Alice
PREFIXE_UNITE=arac-cerveau_test
U_API=$PREFIXE_UNITE-api
U_COCKPIT=$PREFIXE_UNITE-cockpit
U_CYCLE=$PREFIXE_UNITE-cycle
U_BACKUP=$PREFIXE_UNITE-sauvegarde
SIMULATION=1
ACCORD_AUTOMATIQUE=0
BAVARD=0
source {lib}/ui.sh
source {lib}/core.sh
source {lib}/services.sh
"""


def _bash(script: str, home: str = "/opt/mon-cerveau", env: dict | None = None):
    plein = _PRELUDE.format(home=home, lib=_LIB) + script
    e = dict(os.environ)
    e.setdefault("ARAC_UI_COULEUR", "jamais")
    if env:
        e.update(env)
    return subprocess.run(
        ["bash", "-c", plein], capture_output=True, text=True, env=e, timeout=120
    )


# ---------------------------------------------------------------------------
# 1. ProtectHome : la valeur, et ce qu'elle vaut selon l'emplacement du dépôt
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("home,attendu", [
    ("/root/arac-oss", "read-only"),
    ("/root", "read-only"),
    ("/home/alice/arac", "read-only"),
    ("/opt/mon_cerveau", "true"),
    ("/srv/arac", "true"),
    ("/var/lib/arac-oss", "true"),
])
def test_protect_home_suit_lemplacement_du_depot(home, attendu):
    """Sous /home ou /root, `ProtectHome=true` rend le binaire INTROUVABLE."""
    r = _bash('_protect_home_valeur "$ARAC_HOME" "$ARAC_VENV"', home=home)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == attendu, (
        f"Pour un dépôt en {home}, ProtectHome vaut « {r.stdout.strip()} » "
        f"au lieu de « {attendu} ».\n"
        f"« true » masque /home ET /root derrière un tmpfs vide : le service "
        f"ne peut pas exécuter son binaire, et systemd rend 203/EXEC en boucle."
    )


@pytest.mark.parametrize("unite", ["_unite_api", "_unite_cockpit", "_unite_cycle"])
def test_les_unites_nempechent_pas_leur_propre_demarrage(unite):
    """Aucune unité ne porte `ProtectHome=true` quand le dépôt est sous /root."""
    r = _bash(unite, home="/root/arac-oss")
    assert r.returncode == 0, r.stderr
    lignes = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith("ProtectHome=")]
    assert lignes, f"{unite} n'écrit plus ProtectHome du tout — le durcissement a disparu."
    for l in lignes:
        assert l.split("=", 1)[1].lower() not in ("true", "yes", "on", "1"), (
            f"{unite} écrit « {l} » alors que le dépôt est sous /root.\n"
            f"L'unité s'interdit à elle-même d'atteindre son ExecStart."
        )


@pytest.mark.parametrize("unite", ["_unite_api", "_unite_cockpit", "_unite_cycle"])
def test_le_durcissement_nest_pas_relache_sans_raison(unite):
    """Hors de /home et /root, `ProtectHome=true` reste — on n'assouplit pas par confort."""
    r = _bash(unite, home="/opt/mon_cerveau")
    assert r.returncode == 0, r.stderr
    assert "ProtectHome=true" in r.stdout, (
        f"{unite} a relâché ProtectHome alors que rien ne l'y obligeait : "
        f"le durcissement doit céder à une contrainte, jamais à une habitude."
    )


# ---------------------------------------------------------------------------
# 2. Le garde éprouve-t-il la panne comme systemd la vivra ?
# ---------------------------------------------------------------------------

def _theatre(tmp_path) -> Path:
    """Un `id` de théâtre : les utilisateurs système existent, où qu'on soit.

    Sans lui, ce test ne mesurerait rien sur une machine où « arac » et
    « aracagent » n'ont jamais été créés — c'est-à-dire sur celle de qui clone.
    """
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    (b / "id").write_text("#!/bin/sh\necho 4242\nexit 0\n", encoding="utf-8")
    (b / "id").chmod(0o755)
    return b


def test_le_garde_execute_le_binaire_sous_les_proprietes_de_lunite(tmp_path):
    """La question n'est pas « ce chemin est-il traversable ? ».

    C'est « cette unité, TELLE QUE JE VAIS L'ÉCRIRE, pourra-t-elle exécuter ce
    binaire ? ». On intercepte `systemd-run` pour lire ce que le garde lui
    demande vraiment : sans `ProtectHome`, la mesure ne dit rien de l'unité.
    """
    faux = _theatre(tmp_path)
    trace = tmp_path / "appels.txt"
    (faux / "systemd-run").write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> {trace}\nexit 0\n', encoding="utf-8"
    )
    (faux / "systemd-run").chmod(0o755)

    r = _bash(
        '_controle_execution_sous_unite; echo "RC=$?"',
        home="/root/arac-oss",
        env={"PATH": f"{faux}:{os.environ['PATH']}"},
    )
    assert "RC=0" in r.stdout, r.stdout + r.stderr
    assert trace.exists(), (
        "Le garde n'a JAMAIS lancé systemd-run : il continue de déduire au lieu "
        "de mesurer, et son modèle de la panne reste incomplet."
    )
    appels = trace.read_text(encoding="utf-8")
    assert "ProtectHome" in appels, (
        "Le garde éprouve l'exécution sans poser ProtectHome : il mesure autre "
        "chose que l'unité qu'il s'apprête à écrire.\n" + appels
    )
    assert "ProtectSystem" in appels
    assert "--uid=" in appels, "le garde n'éprouve pas sous l'identité du service"
    assert "/.venv/bin/" in appels, "le garde n'exécute pas le binaire de l'unité"


def test_le_garde_signale_une_execution_refusee(tmp_path):
    """Un `systemd-run` qui échoue doit arrêter l'étape, pas la laisser poser."""
    faux = _theatre(tmp_path)
    (faux / "systemd-run").write_text("#!/bin/sh\nexit 203\n", encoding="utf-8")
    (faux / "systemd-run").chmod(0o755)

    r = _bash(
        '_controle_execution_sous_unite; echo "RC=$?"',
        home="/root/arac-oss",
        env={"PATH": f"{faux}:{os.environ['PATH']}"},
    )
    assert "RC=0" not in r.stdout, (
        "Une exécution refusée sous les propriétés de l'unité n'a PAS arrêté "
        "l'étape : les unités seraient posées et boucleraient en 203/EXEC."
    )
    assert "203" in r.stdout, "le code exact que systemd rendra n'est pas montré"


# ---------------------------------------------------------------------------
# 3. Le remède ne doit pas casser ce qu'il répare
# ---------------------------------------------------------------------------

def _impasse(tmp_path) -> str:
    """Le message rendu quand le dépôt n'est pas atteignable par les services."""
    prive = tmp_path / "prive"
    prive.mkdir(mode=0o700)
    depot = prive / "arac-oss"
    depot.mkdir()
    r = _bash('_controle_accessibilite_depot; echo "RC=$?"', home=str(depot))
    assert "RC=0" not in r.stdout, (
        "Un dépôt sous un répertoire 0700 a été déclaré atteignable :\n" + r.stdout
    )
    return r.stdout


def test_le_remede_du_deplacement_reconstruit_lenvironnement_python(tmp_path):
    """Un venv n'est pas déplaçable : ses scripts portent un shebang ABSOLU."""
    sortie = _impasse(tmp_path)
    assert "mv " in sortie, "le remède du déplacement a disparu"
    assert "venv" in sortie.lower(), (
        "Le remède propose de DÉPLACER le dépôt sans dire un mot de "
        "l'environnement Python.\n"
        "Après le `mv`, les scripts de .venv/bin pointent tous vers l'ancien "
        "chemin : pip, alembic et uvicorn rendent « required file not found » "
        "(code 127). Le remède casse l'installation qu'il prétend réparer.\n\n"
        + sortie
    )
    assert "--clear" in sortie or "recréer" in sortie.lower() or "reconstru" in sortie.lower(), (
        "Le remède mentionne le venv sans donner le geste qui le reconstruit.\n"
        + sortie
    )


def test_le_remede_de_louverture_du_chemin_ne_suffit_pas_seul(tmp_path):
    """`chmod o+x` ne dit rien de ProtectHome — le message doit le dire.

    C'est le piège exact : le remède n° 2 faisait PASSER le garde en laissant
    la panne entière. Un utilisateur qui l'applique croit avoir réparé.
    """
    sortie = _impasse(tmp_path)
    if "chmod o+x" not in sortie:
        pytest.skip("ce chemin n'offre pas le remède d'ouverture")
    assert "ProtectHome" in sortie, (
        "Le remède « ouvrir la traversée » est proposé sans dire que "
        "ProtectHome, lui, ne lit AUCUNE permission. L'utilisateur applique, "
        "le garde passe, et la boucle 203/EXEC reste entière.\n" + sortie
    )
