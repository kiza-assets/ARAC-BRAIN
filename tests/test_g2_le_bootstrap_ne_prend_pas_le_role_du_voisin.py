"""G2 — LE COMPORTEMENT, pas seulement le texte.

G1 (`test_g1_aucun_nom_partage_entre_cerveaux.py`) balaie des fichiers : il
attrape un nom figé. Il ne peut rien dire de ce que le bootstrap FAIT. Or les
deux fautes qui ont détruit une production étaient des gestes, pas des noms :

  · exécuter `ALTER ROLE … PASSWORD` sur un rôle trouvé en place ;
  · attribuer un port sans avoir constaté qu'il était libre.

On exerce donc ici les fonctions elles-mêmes, en les sourçant. Aucune base,
aucun réseau, aucun privilège : on lit ce que le shell PRODUIT.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
LIB = RACINE / "bootstrap" / "lib"


def _bash(corps: str, env_sup: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Source les bibliothèques du bootstrap et exécute `corps`.

    `set -u` est posé comme dans le vrai bootstrap : une variable oubliée doit
    faire échouer ce test, pas produire un SQL à trou.
    """
    script = f"""
set -uo pipefail
ARAC_HOME={RACINE}
source "$ARAC_HOME/bootstrap/lib/ui.sh"
source "$ARAC_HOME/bootstrap/lib/core.sh"
source "$ARAC_HOME/bootstrap/lib/database.sh"
{corps}
"""
    import os

    env = dict(os.environ)
    env.setdefault("NO_COLOR", "1")
    env.update(env_sup or {})
    return subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, env=env, timeout=60
    )


def _decor_cerveau(db: str) -> str:
    """Les variables que l'étape 2 aurait posées pour ce cerveau."""
    return f"""
ARAC_DB={db}
ARAC_ETC=/etc/arac/{db}
ARAC_SCHEMA=arac
ARAC_ROLE_PREFIX=arac_{db}
R_ADMIN=${{ARAC_ROLE_PREFIX}}_admin
R_APP=${{ARAC_ROLE_PREFIX}}_app
R_AGENT=${{ARAC_ROLE_PREFIX}}_agent
R_READONLY=${{ARAC_ROLE_PREFIX}}_readonly
R_BACKUP=${{ARAC_ROLE_PREFIX}}_backup
"""


# ---------------------------------------------------------------------------
# 1. L'INSTRUCTION QUI A DÉTRUIT LA PRODUCTION
# ---------------------------------------------------------------------------

#: Toute instruction qui change le mot de passe d'un rôle. On la cherche dans
#: le SQL ENGENDRÉ, pas dans le source : c'est ce qui part vers PostgreSQL qui
#: compte, et lui seul. La prose qui l'enseigne, elle, doit rester — c'est la
#: mémoire de l'incident.
_ALTER_MDP = re.compile(r"^\s*ALTER\s+ROLE\b[^;]*\bPASSWORD\b", re.I | re.M)


def _sql_des_roles(db: str = "cerveau_a") -> str:
    r = _bash(_decor_cerveau(db) + "\n_sql_roles motdepasse1 motdepasse2 motdepasse3 motdepasse4")
    assert r.returncode == 0, f"_sql_roles a échoué :\n{r.stderr}"
    assert not r.stderr.strip(), (
        "_sql_roles a écrit sur la sortie d'erreur — le SQL est engendré par un "
        f"document en ligne NON protégé, une substitution s'y est glissée :\n{r.stderr}"
    )
    return r.stdout


def test_le_sql_engendre_ne_change_jamais_un_mot_de_passe() -> None:
    """Aucun `ALTER ROLE … PASSWORD` ne doit partir vers PostgreSQL.

    C'est l'instruction exacte de l'incident. Elle réussit toujours, ne dit
    rien, et n'échoue que chez le voisin — au redémarrage suivant de SES
    services, donc des heures plus tard, sans rien qui rattache la panne à
    l'installation qui l'a causée.
    """
    sql = _sql_des_roles()
    fautifs = _ALTER_MDP.findall(sql)
    assert not fautifs, (
        "Le SQL engendré par _sql_roles change un mot de passe de rôle :\n  "
        + "\n  ".join(fautifs)
        + "\n\nUn rôle est global au cluster. Celui qu'on trouve en place n'est "
          "pas forcément le nôtre — et s'il l'est, son mot de passe est déjà "
          "dans le coffre. Il n'existe donc aucun cas où cette instruction "
          "soit le bon geste. Créez, ou refusez."
    )


def test_le_sql_engendre_ne_cree_que_ce_qui_manque() -> None:
    """Chaque CREATE ROLE est gardé par un `IF NOT EXISTS`."""
    sql = _sql_des_roles()
    creations = len(re.findall(r"^\s*CREATE\s+ROLE\b", sql, re.I | re.M))
    gardes = len(re.findall(r"IF\s+NOT\s+EXISTS\s*\(SELECT 1 FROM pg_roles", sql, re.I))
    assert creations == gardes == 5, (
        f"{creations} CREATE ROLE pour {gardes} gardes « IF NOT EXISTS ». "
        "Chacun des cinq rôles doit être créé UNIQUEMENT s'il manque."
    )


def test_chaque_role_cree_porte_la_plaque_de_son_cerveau() -> None:
    """Un rôle sans plaque est un rôle dont personne ne pourra dire à qui il est.

    C'est la question que le bootstrap ne savait pas poser le jour de
    l'incident : il trouvait `arac_app`, ne pouvait rien en dire, et
    continuait.
    """
    sql = _sql_des_roles("cerveau_a")
    plaques = re.findall(r"COMMENT ON ROLE (\S+) IS '([^']*)'", sql)
    assert len(plaques) == 5, f"{len(plaques)} plaque(s) pour 5 rôles"
    for role, plaque in plaques:
        assert role.startswith("arac_cerveau_a_"), role
        assert "cerveau=cerveau_a" in plaque, plaque
        assert "secrets=/etc/arac/cerveau_a" in plaque, plaque


# ---------------------------------------------------------------------------
# 2. DEUX CERVEAUX N'ONT AUCUN NOM EN COMMUN
# ---------------------------------------------------------------------------


def test_deux_cerveaux_ont_des_jeux_de_roles_disjoints() -> None:
    """Le test que l'incident aurait dû avoir : A et B ne se touchent pas."""
    a = set(re.findall(r"CREATE ROLE (\S+)", _sql_des_roles("cerveau_a")))
    b = set(re.findall(r"CREATE ROLE (\S+)", _sql_des_roles("cerveau_b")))
    assert len(a) == len(b) == 5
    assert not (a & b), (
        f"Ces rôles sont communs aux deux cerveaux : {sorted(a & b)}\n"
        "Un rôle est global au cluster : un nom partagé, c'est un mot de passe "
        "que le second bootstrap écrase au premier passage."
    )


@pytest.mark.parametrize(
    "champ, gabarit",
    [
        ("ARAC_ETC", "/etc/arac/{db}"),
        ("ARAC_LOG_DIR", "/var/log/arac/{db}"),
        ("ARAC_BACKUP_DIR", "/var/backups/arac/{db}"),
        ("PREFIXE_UNITE", "arac-{db}"),
        ("ARAC_ROLE_PREFIX", "arac_{db}"),
    ],
)
def test_chaque_chemin_porte_le_nom_du_cerveau(champ: str, gabarit: str) -> None:
    """Aucun de ces six noms ne doit être commun à deux cerveaux.

    Le dossier de sauvegarde était commun : la rotation d'un cerveau
    supprimait les dumps de l'autre. Les unités l'étaient aussi : le second
    `systemctl enable` écrasait le premier, et un seul des deux tournait.
    """
    valeurs = {}
    for db in ("cerveau_a", "cerveau_b"):
        r = _bash(_decor_cerveau(db) + f"""
ARAC_LOG_DIR="${{ARAC_LOG_DIR:-/var/log/arac/$ARAC_DB}}"
ARAC_BACKUP_DIR="${{ARAC_BACKUP_DIR:-/var/backups/arac/$ARAC_DB}}"
PREFIXE_UNITE="arac-$ARAC_DB"
printf '%s' "${champ}"
""".replace("${champ}", "${" + champ + "}"))
        assert r.returncode == 0, r.stderr
        valeurs[db] = r.stdout.strip()
        assert valeurs[db] == gabarit.format(db=db), \
            f"{champ} = {valeurs[db]!r}, attendu {gabarit.format(db=db)!r}"
    assert valeurs["cerveau_a"] != valeurs["cerveau_b"], \
        f"{champ} est IDENTIQUE pour deux cerveaux : {valeurs['cerveau_a']!r}"


# ---------------------------------------------------------------------------
# 3. LES PORTS — constater avant d'attribuer
# ---------------------------------------------------------------------------
#
# CES DEUX TESTS INTERROGEAIENT LA MACHINE, ET C'ÉTAIT MESURABLE : ils lançaient
# `ss -ltnH sport = :8000` et `:8100` sur l'hôte, c'est-à-dire sur les ports de
# PRODUCTION, pendant un simple `make test`. La table des sockets d'une machine
# dit qui écoute, sous quel PID, pour tous les cerveaux qui y vivent.
#
# On ne renonce pas pour autant à la SEULE chose que ces deux tests éprouvent
# vraiment — que `port_libre` voit une socket RÉELLE plutôt que de supposer.
# On restreint la question : le test ouvre une socket, et pose devant `ss` un
# double qui n'accepte de parler à l'hôte QUE du port qu'il vient d'ouvrir.
# Pour tout autre numéro il répond « personne n'écoute », ce qui est la réponse
# que le test veut éprouver et ne révèle rien de la machine.


def _ss_borne_au_port(dossier: Path, port: int) -> Path:
    """Un `ss` qui ne sait répondre que sur UN port : celui du test.

    Le double délègue au vrai `ss` pour ce port-là — sinon on n'éprouverait
    plus que l'analyse d'une chaîne, alors que la faute d'origine était de
    n'avoir rien observé du tout. Pour tous les autres ports il rend une sortie
    vide, c'est-à-dire « libre ».
    """
    reel = shutil.which("ss", path=os.environ.get("ARAC_GARDE_PATH_HOTE", os.defpath))
    dossier.mkdir(parents=True, exist_ok=True)
    talon = dossier / "ss"
    talon.write_text(
        "#!/bin/sh\n"
        "# Double posé par test_g2 — voir le commentaire de section.\n"
        'case "$*" in\n'
        f'  *":{port}"*) exec {reel or "/bin/false"} "$@" ;;\n'
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    talon.chmod(0o755)
    return dossier


def test_un_port_tenu_n_est_jamais_declare_libre(tmp_path) -> None:
    """`port_libre` doit voir une socket réelle, ouverte à l'instant."""
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        theatre = _ss_borne_au_port(tmp_path / "bin", port)
        r = _bash(
            f'port_libre {port} && echo LIBRE || echo TENU',
            env_sup={"PATH": f"{theatre}:{os.environ['PATH']}"},
        )
        assert r.returncode == 0, r.stderr
        assert "TENU" in r.stdout, (
            f"port_libre({port}) a répondu « libre » alors qu'une socket écoute "
            "à cette seconde. C'est la supposition exacte qui a fait lier le "
            "port de l'API de production."
        )
    finally:
        s.close()


def test_l_attribution_saute_le_port_tenu(tmp_path) -> None:
    """`premier_port_libre` doit rendre un AUTRE numéro, et le dire au-dessus."""
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        theatre = _ss_borne_au_port(tmp_path / "bin", port)
        r = _bash(
            f'premier_port_libre {port} 20',
            env_sup={"PATH": f"{theatre}:{os.environ['PATH']}"},
        )
        assert r.returncode == 0, r.stderr
        retenu = r.stdout.strip()
        assert retenu.isdigit(), f"sortie inattendue : {r.stdout!r}"
        assert int(retenu) != port, "le port tenu a été attribué malgré tout"
        assert port < int(retenu) <= port + 20
    finally:
        s.close()


def test_sans_ss_on_refuse_plutot_que_de_supposer() -> None:
    """Ne pas savoir n'est pas une autorisation.

    `ss` absent, l'ancien code aurait conclu « libre ». C'est la conclusion la
    plus coûteuse possible : elle produit une unité qui ne pourra jamais ouvrir
    sa socket, sur le port d'un service qui, lui, marchait.
    """
    r = _bash("PATH=/nonexistent port_libre 8000; echo CODE=$?")
    assert "CODE=2" in r.stdout, (
        "Sans `ss`, `port_libre` doit rendre 2 (« je n'ai pas pu savoir »), "
        f"jamais 0 (« libre »). Sortie : {r.stdout!r}"
    )


# ---------------------------------------------------------------------------
# 4. LES MIGRATIONS DÉDUISENT LEURS RÔLES
# ---------------------------------------------------------------------------


def test_les_migrations_deduisent_les_roles_du_role_admin() -> None:
    sys.path.insert(0, str(RACINE))
    from db.alembic.roles import RolesArac, prefixe_depuis_role_admin

    assert prefixe_depuis_role_admin("arac_nadia_brain_admin") == "arac_nadia_brain"
    r = RolesArac("arac_nadia_brain")
    assert r.app == "arac_nadia_brain_app"
    assert r.backup == "arac_nadia_brain_backup"
    # Compatibilité : un cerveau posé AVANT ce nommage garde ses cinq noms.
    assert RolesArac(prefixe_depuis_role_admin("arac_admin")).app == "arac_app"


def test_une_migration_hors_contexte_refuse_plutot_que_de_deviner() -> None:
    """Pas de valeur de repli : ne pas savoir sous quel cerveau on tourne est
    une raison de s'arrêter, pas de choisir `arac` par défaut."""
    sys.path.insert(0, str(RACINE))
    from db.alembic.roles import PrefixeDeRoleInvalide, prefixe_depuis_role_admin

    with pytest.raises(PrefixeDeRoleInvalide):
        prefixe_depuis_role_admin("postgres")


def test_un_nom_de_cerveau_trop_long_est_refuse_avant_la_troncature() -> None:
    """PostgreSQL tronque à 63 octets SANS erreur : deux cerveaux aux noms
    longs et voisins partageraient alors un rôle, silencieusement."""
    sys.path.insert(0, str(RACINE))
    from db.alembic.roles import PrefixeDeRoleInvalide, valider_prefixe

    valider_prefixe("a" * 54)
    with pytest.raises(PrefixeDeRoleInvalide):
        valider_prefixe("a" * 55)


def test_un_nom_de_cerveau_ne_peut_pas_devenir_une_injection() -> None:
    sys.path.insert(0, str(RACINE))
    from db.alembic.roles import PrefixeDeRoleInvalide, valider_prefixe

    for mauvais in ('arac"; DROP ROLE x; --', "arac app", "ARAC", "1arac", ""):
        with pytest.raises(PrefixeDeRoleInvalide):
            valider_prefixe(mauvais)


def test_aucune_migration_ne_nomme_un_role_en_dur() -> None:
    """Un nom de rôle en dur dans une migration annule tout le bootstrap.

    La migration tourne sous le rôle d'administration du cerveau qu'elle
    migre ; ses `GRANT` doivent viser les frères de CE rôle, jamais ceux d'un
    autre cerveau qui porterait un nom générique.
    """
    import ast

    fautifs: list[str] = []
    for p in sorted((RACINE / "db" / "alembic" / "versions").glob("*.py")):
        arbre = ast.parse(p.read_text(encoding="utf-8"))
        docs = {
            id(n.body[0].value)
            for n in ast.walk(arbre)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef))
            and getattr(n, "body", None)
            and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
            and isinstance(n.body[0].value.value, str)
        }
        for n in ast.walk(arbre):
            if (
                isinstance(n, ast.Constant)
                and isinstance(n.value, str)
                and id(n) not in docs
                and re.search(r"\barac_(app|agent|readonly|admin|backup)\b", n.value)
            ):
                fautifs.append(f"{p.name}:{n.lineno}")
    assert not fautifs, (
        "Ces migrations nomment un rôle en toutes lettres :\n  "
        + "\n  ".join(fautifs)
        + "\n\nUtilisez `R = roles_arac()` puis f\"… TO {R.app}\"."
    )
