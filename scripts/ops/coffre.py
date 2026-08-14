#!/usr/bin/env python3
"""OÙ VIT LE COFFRE — un seul organe, pour tous les outils qui le cherchent.

CE QUE CE FICHIER EXISTE POUR EMPÊCHER, ET C'EST MESURÉ
=======================================================
`docs/EXPLOITATION.md` §1 annonce « les cinq commandes … vous pouvez les lancer
cent fois, y compris pendant un incident ». La TROISIÈME ne pouvait pas se
lancer une seule fois sur un cerveau posé par le bootstrap :

    $ .venv/bin/python scripts/ops/alerts.py
    UNKNOWN : DATABASE_URL_READONLY n'est pas définie.        (code 3)

    $ sudo ARAC_ENV_FILE=/etc/arac/lew17a/arac.env \\
          .venv/bin/python scripts/ops/alerts.py
    UNKNOWN : DATABASE_URL_READONLY n'est pas définie.        (code 3)

La seconde forme est celle que TOUT le reste d'`ops/` enseigne — `ops/env.sh`,
`ops/install_check.sh`, `scripts/ops/health_check.py` — et elle ne servait à
rien ici : `alerts.py` ne lisait que `DATABASE_URL_READONLY` dans son
environnement. Ni `ARAC_ENV_FILE`, ni `ARAC_DB`, ni `config/brain.toml`. Or ce
DSN vit dans `/etc/arac/<base>/arac.env`, en `0600 root`. L'organe n'était pas
cassé : il n'était pas joignable par le chemin que la page prescrit. Le DSN
donné à la main, il rendait ses quatre alarmes sans broncher.

Sa voisine de liste, `health_check.py`, avait appris ce chemin une manche plus
tôt, et son propre commentaire nommait la maladie : « Deux outils voisins, deux
conventions : c'est exactement la classe de défaut que ce dépôt passe des
manches à éliminer. » La recopier une troisième fois l'aurait rouverte. Elle
vit donc ici, une seule fois, et les deux sondes l'importent.

CE QUE CET ORGANE NE FAIT PAS
=============================
Il ne DEVINE jamais le cerveau. `/etc/arac/` est la racine partagée de la
machine : elle n'appartient à personne. Sans nom de base — ni `ARAC_ENV_FILE`,
ni `ARAC_DB`, ni `config/brain.toml` lisible — il rend la chaîne vide, et
l'appelant le DIT au lieu de choisir à la place de quelqu'un.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: La racine du dépôt : ce fichier est dans `scripts/ops/`.
_REPO = Path(__file__).resolve().parents[2]


def defaut_env_file() -> str:
    """Le coffre de CE cerveau, dérivé comme `ops/env.sh` le dérive.

    Ordre : ce qu'on nous impose (`ARAC_ENV_FILE`), le nom de la base
    (`ARAC_DB`), puis la description issue de l'entretien
    (`config/brain.toml`). Rend "" quand rien ne permet de conclure.
    """
    if os.environ.get("ARAC_ENV_FILE"):
        return os.environ["ARAC_ENV_FILE"]
    nom = (os.environ.get("ARAC_DB") or "").strip()
    if not nom:
        try:
            import tomllib
            brain = _REPO / "config" / "brain.toml"
            d = tomllib.loads(brain.read_text(encoding="utf-8"))
            nom = re.sub(r"_+$", "", re.sub(r"[^a-zA-Z0-9]", "_",
                                            d.get("brain", {}).get("name", ""))).lower()
        except Exception:  # noqa: BLE001 — l'absence n'est pas une panne
            nom = ""
    return f"/etc/arac/{nom}/arac.env" if nom else ""


def charger_le_coffre(chemin: str) -> int:
    """Injecte les variables du coffre qui ne sont PAS déjà posées.

    L'environnement du processus l'emporte : sous systemd, `EnvironmentFile=`
    a déjà tout fourni, et un fichier lu ici ne doit pas contredire ce que
    l'unité a décidé. Rend le nombre de variables ajoutées.
    """
    ajoutees = 0
    try:
        with open(chemin, encoding="utf-8") as f:
            for ligne in f:
                ligne = ligne.strip()
                if not ligne or ligne.startswith("#") or "=" not in ligne:
                    continue
                cle, _, val = ligne.partition("=")
                cle = cle.strip()
                if cle.startswith("export "):
                    cle = cle[len("export "):].strip()
                if not cle or cle in os.environ:
                    continue
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                    val = val[1:-1]
                os.environ[cle] = val
                ajoutees += 1
    except OSError:
        return 0
    return ajoutees


def pourquoi_pas_lisible(chemin: str, variable: str = "DATABASE_URL_READONLY") -> str:
    """La PHRASE qui distingue « absent » de « je n'ai pas le droit de voir ».

    `/etc/arac/<base>/` est en 0700 root : depuis un compte ordinaire,
    `os.path.exists` rend False pour un fichier qui EXISTE. Dire « ce cerveau
    n'a peut-être jamais été installé » à quelqu'un dont l'installation marche
    très bien, c'est l'envoyer réinstaller.
    """
    ou = chemin or "/etc/arac/<votre-base>/arac.env"
    if not chemin:
        return ("Ce script n'a même pas pu DÉDUIRE où est votre coffre : ni "
                "ARAC_ENV_FILE, ni ARAC_DB, ni config/brain.toml lisible.")
    if not os.path.exists(chemin) and not os.access(os.path.dirname(chemin) or ".", os.X_OK):
        return (f"Ce compte ne peut même pas SAVOIR si « {ou} » existe : le "
                "dossier qui le contient ne lui est pas traversable — c'est "
                "voulu, il est en 0700 root.")
    if not os.path.exists(chemin):
        return (f"Le coffre attendu « {ou} » n'existe pas. Ce cerveau n'a "
                "peut-être jamais été installé par le bootstrap.")
    if not os.access(chemin, os.R_OK):
        return (f"Le coffre « {ou} » existe mais n'est pas lisible par ce "
                "compte — c'est voulu : il est en 0600 root.")
    return f"Le coffre « {ou} » a été lu, et il ne porte pas {variable}."


def geste_qui_marche(script: str, chemin: str) -> str:
    """La commande EXACTE qui fait tourner `script` sur CE cerveau.

    Jamais `<votre-base>` : un gabarit littéral dans un geste qu'on recopie en
    panne coûte exactement ce qu'un mode d'emploi est censé épargner. Quand le
    coffre n'a pas pu être déduit, on le dit — on ne fabrique pas un chemin.
    """
    if chemin:
        return f"sudo ARAC_ENV_FILE={chemin} .venv/bin/python {script}"
    return (f"sudo ARAC_ENV_FILE=/etc/arac/<base>/arac.env .venv/bin/python {script}\n"
            "      (« <base> » : le nom de votre cerveau — `ls /etc/arac/` le liste)")


def resoudre(variable: str = "DATABASE_URL_READONLY") -> tuple[bool, str]:
    """Pose `variable` depuis le coffre si elle manque.

    Rend (trouvée, chemin_du_coffre). Ne lève jamais, n'écrit rien sur la
    sortie : c'est l'appelant qui décide de ce qu'il en dit.
    """
    chemin = defaut_env_file()
    if not os.environ.get(variable) and chemin:
        charger_le_coffre(chemin)
    return bool(os.environ.get(variable)), chemin
