"""LE CONTRÔLE DE LA FAMILLE « GABARIT » — et il regarde le fichier POSÉ.

CE QUI A COÛTÉ CE GARDE
=======================

``mac/arac-pont.sh installer`` fabriquait ``pont.conf`` en faisant passer
``mac/pont.conf.example`` dans un ``sed`` à **trois** substitutions —
``ARAC_NODE_ID``, ``ARAC_SERVEUR_SSH``, ``ARAC_CLAUDE_CODE_DIR`` — et **aucune**
des quatre lignes portant le jeton ``<cerveau>``. Le fichier posé gardait donc,
littéralement :

    ARAC_TOKEN_FILE=$HOME/.arac/<cerveau>/jeton_ingest
    ARAC_DESKTOP_EXPORT=$HOME/.arac/<cerveau>/export-desktop/conversations.json
    ARAC_STATE_FILE=$HOME/.arac/<cerveau>/etat-pont.json
    ARAC_LOG_FILE=$HOME/.arac/<cerveau>/journal/arac-pont.log

``<cerveau>`` n'est pas un nom : c'est un **dossier littéral**, le même pour
tous les cerveaux d'un poste. Deux ponts correctement nommés partageaient donc
un seul jeton et un seul CURSEUR — c'est-à-dire très exactement ce que
``mac/arac-pont.sh`` décrit lui-même, en tête de fichier, comme « la seule
perte silencieuse et définitive du système ». Tout le cloisonnement du poste
était annulé par la commande même qui l'installe, et c'est la première commande
que tape celui qui a un Mac.

En shell, ce n'était même pas inerte : ``<cerveau>`` est une **redirection**.
``. pont.conf`` tentait d'ouvrir un fichier nommé ``cerveau`` — et, s'il en
existait un dans le répertoire courant, créait ``/jeton_ingest``.

LA FORME DU DÉFAUT, ET POURQUOI ELLE SE REPRODUIT
==================================================

Le gabarit était juste. La substitution était juste *sur ce qu'elle visait*. Le
fichier posé était faux. Le défaut ne vit dans aucun des deux fichiers : il vit
dans l'**écart entre deux listes** — les jetons que le gabarit porte, et ceux
que le rendeur substitue —, écart que personne ne mesurait parce que personne ne
relisait ce qui venait d'être écrit.

C'est une famille, ce dépôt en fabrique cinq sortes (unités systemd, fragment
sshd, fichiers de configuration, règles tmpfiles, plists launchd), et elle
vient d'en donner l'instance la plus coûteuse.

LES TROIS DIRECTIONS DE CE GARDE
=================================

1. **L'inventaire est fermé.** Tout fichier livré qui porte un jeton de gabarit
   est classé : rendu par un script (lequel), rendu à la main, ou parlant des
   jetons sans en porter. Un gabarit ajouté demain et non classé fait rougir —
   on ne peut pas l'oublier.

2. **Chaque rendeur substitue TOUS les jetons de son gabarit.** Statique, et
   c'est la direction qui aurait attrapé le défaut : ``<cerveau>`` était dans le
   gabarit, pas dans le ``sed``.

3. **Le fichier POSÉ ne porte aucun jeton.** Dynamique : on joue vraiment
   ``installer`` dans un faux foyer, avec DEUX cerveaux, et on relit ce qui a
   été écrit sur le disque. Puis ``ops/systemd/render.sh``. Et enfin on
   **trompe** le contrôle — on remet un ``<cerveau>`` dans une copie du
   gabarit — pour vérifier qu'il refuse : un contrôle qu'on n'a jamais vu
   rougir n'est pas un contrôle.

CE QU'IL NE COUVRE PAS — dit ici plutôt que découvert dans six mois
===================================================================

· **Les gabarits rendus à la main.** ``deploy/systemd/arac-pont-sans-mac.*``,
  ``deploy/nginx/ingest-tls.conf.exemple``, ``deploy/ssh/authorized_keys.modele``
  et les deux ``db/migrations/*.sql.template`` sont substitués par un humain qui
  suit une documentation. Il n'y a pas de fichier posé par le produit, donc rien
  à relire. Ce garde exige seulement qu'ils soient **déclarés** tels.
· **Une valeur VIDE** substituée à un jeton. ``@@PORT_API@@`` remplacé par rien
  ne laisse aucun jeton derrière lui : ce garde le trouve irréprochable. C'est
  la raison pour laquelle ``arac-pont.sh`` refuse séparément des ports vides
  (``ports_renseignes``) et un ``ssh`` introuvable — deux refus, pas un jeton.
· **Une valeur FAUSSE.** Substituer le port du voisin est une substitution
  parfaite. Aucun garde de forme ne le verra.

Hors-ligne : ce fichier ne lit que des fichiers, et n'exécute que des scripts
du dépôt dans un répertoire temporaire à lui, avec un ``HOME`` factice.
"""

from __future__ import annotations

import os
import pathlib
import plistlib
import re
import shutil
import subprocess

import pytest

from tests.corpus_du_depot import fichiers_du_depot

RACINE = pathlib.Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# LES TROIS FAMILLES DE JETONS, ET LEUR RÈGLE
# ---------------------------------------------------------------------------
#
# `@@NOM@@` et `__NOM__` ne sont jamais légitimes dans un fichier posé, où que
# ce soit — ni en valeur, ni en commentaire : personne n'écrit `@@FOYER@@` en
# prose. `<mot>`, lui, est de la prose quand il est en commentaire
# (« <adresse-de-votre-serveur> » est une consigne adressée à un humain) et un
# gabarit non substitué quand il est dans une ligne que lit un programme.
JETON_AROBASES = re.compile(r"@@[A-Za-z0-9_]+@@")
JETON_SOULIGNES = re.compile(r"__[A-Z][A-Z0-9_]+__")
JETON_CHEVRONS = re.compile(r"<[A-Za-z_][A-Za-z0-9_-]*>")

#: Le même contrôle que celui de `mac/arac-pont.sh` et de
#: `ops/systemd/render.sh`, écrit une seconde fois ici — en Python. Deux
#: écritures d'une même règle sont un risque de divergence ; c'est assumé, et
#: c'est `test_le_controle_du_shell_et_celui_d_ici_refusent_la_meme_chose` qui
#: les tient ensemble.


def jetons_du_fichier_pose(texte: str, *, chevrons: bool = True) -> list[str]:
    """Les lignes d'un fichier POSÉ qui portent encore un jeton de gabarit."""
    fautives: list[str] = []
    for n, ligne in enumerate(texte.splitlines(), 1):
        if JETON_AROBASES.search(ligne) or JETON_SOULIGNES.search(ligne):
            fautives.append(f"{n}: {ligne}")
            continue
        if not chevrons:
            continue
        nue = ligne.strip()
        if not nue or nue.startswith("#") or nue.startswith(";"):
            continue
        if JETON_CHEVRONS.search(ligne):
            fautives.append(f"{n}: {ligne}")
    return fautives


# ===========================================================================
# 1. L'INVENTAIRE EST FERMÉ
# ===========================================================================

#: Ce que fait chaque fichier du dépôt qui porte un jeton. Trois rôles, et le
#: rôle « gabarit rendu par un script » nomme SON rendeur — c'est ce nom qui
#: permet la direction 2.
RENDU_PAR_SCRIPT = {
    "mac/pont.conf.example": "mac/arac-pont.sh",
    "mac/com.arac.pont.sync.plist.modele": "mac/arac-pont.sh",
    "mac/com.arac.pont.tunnel.plist.modele": "mac/arac-pont.sh",
    "deploy/ssh/99-arac-pont.conf": "deploy/ssh/rendre-pont.sh",
    "ops/systemd/arac-backup-dirs.conf.template": "ops/systemd/render.sh",
    "ops/systemd/arac-backup-offsite.service.template": "ops/systemd/render.sh",
    "ops/systemd/arac-backup-watchdog.service.template": "ops/systemd/render.sh",
    "ops/systemd/arac-health.service.template": "ops/systemd/render.sh",
    "ops/systemd/arac-install-check.service.template": "ops/systemd/render.sh",
}

#: Substitués par un HUMAIN qui suit une documentation. Aucun code du produit
#: ne les pose : il n'y a donc pas de fichier posé à relire. La valeur ici est
#: la page qui explique le geste — sans elle, un gabarit à la main est un
#: gabarit abandonné.
RENDU_A_LA_MAIN = {
    "deploy/systemd/arac-pont-sans-mac.service.modele": "docs/PONT-MAC.md",
    "deploy/systemd/arac-pont-sans-mac.timer.modele": "docs/PONT-MAC.md",
    "deploy/nginx/ingest-tls.conf.exemple": "deploy/README.md",
    "deploy/ssh/authorized_keys.modele": "deploy/README.md",
    "db/migrations/04_roles.sql.template": "docs/SAUVEGARDE.md",
    "db/migrations/05_role_backup.sql.template": "docs/SAUVEGARDE.md",
    "db/migrations/06_grant_arac_backup_alembic_version.sql": "docs/SAUVEGARDE.md",
    "db/migrations/07_roles_least_privilege_v1_6d.sql": "docs/SAUVEGARDE.md",
    "db/migrations/07_roles_least_privilege_v1_6d_rollback.sql": "docs/SAUVEGARDE.md",
    "db/migrations/proposals/2026-06-03-create-arac-review-writer-role.sql":
        "db/migrations/proposals",
    "db/migrations/proposals/2026-06-03-grant-readonly-review-queue.sql":
        "db/migrations/proposals",
}

#: Ils PARLENT des jetons sans en porter un seul qui doive être substitué :
#: les rendeurs eux-mêmes (leur `sed` cite les jetons), et les gardes.
PARLE_DES_JETONS = {
    "mac/arac-pont.sh",
    "deploy/ssh/rendre-pont.sh",
    "ops/systemd/render.sh",
    "bootstrap/lib/services.sh",
    "tests/test_g1_aucun_nom_partage_entre_cerveaux.py",
    "tests/test_gabarits_le_fichier_pose_ne_porte_aucun_jeton.py",
    # Le JUMEAU de ce garde : il pose la même question à ce que le produit
    # IMPRIME, et cite donc les trois familles de jetons pour les chercher.
    "tests/test_gabarits_la_commande_imprimee_ne_porte_aucun_trou.py",
}


def _porteurs_de_jetons() -> dict[str, list[str]]:
    porteurs: dict[str, list[str]] = {}
    for rel in fichiers_du_depot():
        chemin = RACINE / rel
        if not chemin.is_file():
            continue
        try:
            texte = chemin.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        jetons = sorted(
            set(JETON_AROBASES.findall(texte)) | set(JETON_SOULIGNES.findall(texte))
        )
        if jetons:
            porteurs[rel] = jetons
    return porteurs


def test_tout_gabarit_livre_est_classe() -> None:
    """Un gabarit ajouté demain ne peut pas passer inaperçu.

    La liste qui grandit toute seule est celle des FICHIERS du dépôt ; les
    trois listes ci-dessus sont des classements. Un fichier qui porte un jeton
    et n'est dans aucun des trois fait rougir ce test, avec le geste.
    """
    connus = set(RENDU_PAR_SCRIPT) | set(RENDU_A_LA_MAIN) | PARLE_DES_JETONS
    inconnus = sorted(set(_porteurs_de_jetons()) - connus)
    assert not inconnus, (
        "Ces fichiers portent un jeton de gabarit et ne sont classés nulle part :\n"
        + "\n".join(f"  · {f}" for f in inconnus)
        + "\n\nClassez-les dans tests/test_gabarits_le_fichier_pose_ne_porte_"
        "aucun_jeton.py :\n"
        "  · RENDU_PAR_SCRIPT — un script du dépôt le substitue. Nommez-le : la\n"
        "    direction 2 vérifiera alors qu'il substitue TOUS ses jetons, et la\n"
        "    direction 3 relira le fichier posé.\n"
        "  · RENDU_A_LA_MAIN — un humain le substitue. Nommez la page qui\n"
        "    explique le geste.\n"
        "  · PARLE_DES_JETONS — il les cite sans en porter."
    )


def test_chaque_classement_designe_un_fichier_vivant() -> None:
    """Un classement qui ne désigne plus rien est un classement qui ment."""
    morts = [
        f
        for f in list(RENDU_PAR_SCRIPT) + list(RENDU_A_LA_MAIN) + sorted(PARLE_DES_JETONS)
        if not (RACINE / f).exists()
    ]
    assert not morts, (
        "Ces fichiers sont classés ici mais n'existent plus : " + ", ".join(morts)
    )


def test_chaque_gabarit_a_la_main_nomme_une_page_qui_existe() -> None:
    """Un gabarit rendu à la main sans mode d'emploi est un gabarit abandonné."""
    orphelins = {
        gab: page for gab, page in RENDU_A_LA_MAIN.items() if not (RACINE / page).exists()
    }
    assert not orphelins, f"Pages introuvables : {orphelins}"


# ===========================================================================
# 2. CHAQUE RENDEUR SUBSTITUE TOUS LES JETONS DE SON GABARIT
# ===========================================================================
#
# C'est la direction qui aurait attrapé le défaut : `<cerveau>` était dans
# `mac/pont.conf.example`, et pas dans le `sed` de `commande_installer`.

def _substitutions_du_rendeur(script: str) -> set[str]:
    """Les jetons que le `sed` d'un script remplace, lus dans le script.

    `-e "s|@@X@@|…|g"`, `-e "s#__X__#…#g"`, `-e "s|<x>|…|g"` : le délimiteur
    varie d'un script à l'autre, on le lit au lieu de le supposer.
    """
    texte = (RACINE / script).read_text(encoding="utf-8")
    trouves: set[str] = set()
    for m in re.finditer(r"""-e\s+["']s(.)(.+?)\1""", texte):
        gauche = m.group(2)
        trouves |= set(JETON_AROBASES.findall(gauche))
        trouves |= set(JETON_SOULIGNES.findall(gauche))
        trouves |= set(JETON_CHEVRONS.findall(gauche))
    return trouves


def _jetons_du_gabarit(gabarit: str) -> set[str]:
    """Ce qu'un gabarit EXIGE qu'on substitue.

    `@@X@@` et `__X__` où qu'ils soient. Les chevrons, eux, uniquement dans une
    ligne de VALEUR : en commentaire, `<adresse-de-votre-serveur>` est une
    consigne adressée à un humain, et la substituer demanderait de la deviner.
    """
    texte = (RACINE / gabarit).read_text(encoding="utf-8")
    jetons = set(JETON_AROBASES.findall(texte)) | set(JETON_SOULIGNES.findall(texte))
    if not texte.lstrip().startswith("<?xml"):
        for ligne in texte.splitlines():
            nue = ligne.strip()
            if not nue or nue.startswith(("#", ";", "--")):
                continue
            jetons |= set(JETON_CHEVRONS.findall(ligne))
    return jetons


@pytest.mark.parametrize("gabarit", sorted(RENDU_PAR_SCRIPT))
def test_le_rendeur_substitue_tous_les_jetons_de_son_gabarit(gabarit: str) -> None:
    script = RENDU_PAR_SCRIPT[gabarit]
    manquants = sorted(_jetons_du_gabarit(gabarit) - _substitutions_du_rendeur(script))
    assert not manquants, (
        f"{script} ne substitue pas ces jetons de {gabarit} :\n"
        + "\n".join(f"  · {j}" for j in manquants)
        + "\n\nC'est EXACTEMENT le défaut qui a coûté au pont du Mac tout son\n"
        "cloisonnement : le gabarit portait `<cerveau>`, le `sed` ne le voyait\n"
        "pas, et le fichier posé gardait un dossier littéral partagé par tous\n"
        "les cerveaux du poste."
    )


# ===========================================================================
# 3. LE FICHIER POSÉ — ON JOUE, PUIS ON RELIT LE DISQUE
# ===========================================================================

REPONSES = "{cerveau}\no\n{node}\n{ssh}\n\n{api}\n{cockpit}\n"


def _jouer_installer(depot_mac: pathlib.Path, foyer: pathlib.Path, **rep: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["HOME"] = str(foyer)
    env["ARAC_SANS_COULEUR"] = "1"
    env.pop("ARAC_CERVEAU", None)
    return subprocess.run(
        ["bash", str(depot_mac / "arac-pont.sh"), "installer"],
        input=REPONSES.format(**rep),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(foyer),
    )


@pytest.fixture(scope="module")
def deux_cerveaux(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """Un faux foyer Mac, deux cerveaux installés côte à côte, pour de vrai."""
    foyer = tmp_path_factory.mktemp("faux-foyer")
    mac = RACINE / "mac"
    a = _jouer_installer(mac, foyer, cerveau="kz_perso", node="poste-marc",
                         ssh="serveur-perso", api="8241", cockpit="8242")
    assert a.returncode == 0, a.stdout + a.stderr
    b = _jouer_installer(mac, foyer, cerveau="kz_projet", node="poste-marc",
                         ssh="serveur-projet", api="8341", cockpit="8342")
    assert b.returncode == 0, b.stdout + b.stderr
    return foyer


def test_installer_pose_un_dossier_par_cerveau(deux_cerveaux: pathlib.Path) -> None:
    """Et jamais dans le foyer commun — c'est ce qui armait le refus de deviner.

    Tant que `installer` ne demandait pas le nom du cerveau, il posait tout
    dans `~/.arac` NU. `cerveaux_connus()` n'énumère que les SOUS-dossiers :
    cette installation lui était invisible pour toujours, le compte retombait à
    zéro, et le second cerveau s'installait par-dessus le premier.
    """
    foyer = deux_cerveaux / ".arac"
    assert (foyer / "kz_perso" / "pont.conf").is_file()
    assert (foyer / "kz_projet" / "pont.conf").is_file()
    assert not (foyer / "pont.conf").exists(), (
        "Une configuration a été posée dans le foyer COMMUN ~/.arac : elle est "
        "invisible à l'énumération par cerveau, et le prochain cerveau du poste "
        "s'installera par-dessus."
    )


@pytest.mark.parametrize("cerveau", ["kz_perso", "kz_projet"])
def test_le_pont_conf_pose_ne_porte_aucun_jeton(
    deux_cerveaux: pathlib.Path, cerveau: str
) -> None:
    pose = deux_cerveaux / ".arac" / cerveau / "pont.conf"
    fautives = jetons_du_fichier_pose(pose.read_text(encoding="utf-8"))
    assert not fautives, (
        f"Le pont.conf posé pour « {cerveau} » porte encore le gabarit :\n"
        + "\n".join(f"  {f}" for f in fautives)
    )


def test_les_quatre_chemins_par_cerveau_sont_distincts(
    deux_cerveaux: pathlib.Path,
) -> None:
    """Le jeton, l'export, le CURSEUR, le journal — quatre, et deux fois deux.

    Le curseur est celui qui compte : partagé, le pont du second y marque
    « déjà envoyées » des conversations que le premier n'a jamais reçues, et
    elles ne repartent plus jamais.
    """
    cles = (
        "ARAC_TOKEN_FILE",
        "ARAC_DESKTOP_EXPORT",
        "ARAC_STATE_FILE",
        "ARAC_LOG_FILE",
    )
    valeurs: dict[str, dict[str, str]] = {}
    for cerveau in ("kz_perso", "kz_projet"):
        texte = (deux_cerveaux / ".arac" / cerveau / "pont.conf").read_text(
            encoding="utf-8"
        )
        valeurs[cerveau] = {
            cle: next(
                l.split("=", 1)[1]
                for l in texte.splitlines()
                if l.startswith(cle + "=")
            )
            for cle in cles
        }
    for cle in cles:
        a, b = valeurs["kz_perso"][cle], valeurs["kz_projet"][cle]
        assert a != b, f"{cle} est le MÊME chemin pour les deux cerveaux : {a}"
        assert "kz_perso" in a and "kz_projet" in b, (
            f"{cle} ne porte pas le nom de son cerveau : {a} / {b}"
        )


def test_les_deux_plists_launchd_sont_distincts_et_sans_jeton(
    deux_cerveaux: pathlib.Path,
) -> None:
    """`automatiser` pose les deux agents : on relit les quatre fichiers.

    Une étiquette launchd est UNIQUE par session macOS : deux plists de même
    Label, et le second `bootstrap` remplace l'agent du premier, dont la
    synchronisation cesse sans une erreur.
    """
    if not (shutil.which("autossh") or shutil.which("ssh")):
        pytest.skip(
            "ni autossh ni ssh sur cette machine : `automatiser` refuse de poser "
            "un agent de tunnel sans programme à lancer, et il a raison."
        )
    mac = RACINE / "mac"
    env = dict(os.environ)
    env["HOME"] = str(deux_cerveaux)
    env["ARAC_SANS_COULEUR"] = "1"
    for cerveau in ("kz_perso", "kz_projet"):
        # `automatiser` refuse tant que la première synchronisation n'a pas eu
        # lieu — c'est un refus délibéré, et il n'est pas l'objet d'ici.
        (deux_cerveaux / ".arac" / cerveau / "etat-pont.json").write_text("{}")
        env["ARAC_CERVEAU"] = cerveau
        subprocess.run(
            ["bash", str(mac / "arac-pont.sh"), "automatiser"],
            input="o\n", capture_output=True, text=True, env=env,
            cwd=str(deux_cerveaux),
        )

    agents = deux_cerveaux / "Library" / "LaunchAgents"
    poses = sorted(agents.glob("*.plist"))
    assert len(poses) == 4, f"Attendu quatre agents, trouvé : {[p.name for p in poses]}"

    etiquettes = []
    for p in poses:
        fautives = jetons_du_fichier_pose(p.read_text(encoding="utf-8"), chevrons=False)
        assert not fautives, f"{p.name} porte encore le gabarit :\n" + "\n".join(fautives)
        with p.open("rb") as fh:
            etiquettes.append(plistlib.load(fh)["Label"])
    assert len(set(etiquettes)) == 4, f"Étiquettes non distinctes : {etiquettes}"

    tunnels = {
        p.name: p.read_text(encoding="utf-8")
        for p in poses
        if p.name.endswith("tunnel.plist")
    }
    assert any("8241" in t for t in tunnels.values())
    assert any("8341" in t for t in tunnels.values())


def test_le_conf_pose_se_source_sans_erreur(deux_cerveaux: pathlib.Path) -> None:
    """`<cerveau>` n'est pas un chemin faux : c'est une REDIRECTION shell.

    `. pont.conf` sur le fichier d'avant rendait « cerveau: No such file or
    directory » quatre fois, ARAC_TOKEN_FILE valait `$HOME/.arac/`, et la
    commande imprimée pour déposer le jeton pointait un RÉPERTOIRE.
    """
    for cerveau in ("kz_perso", "kz_projet"):
        conf = deux_cerveaux / ".arac" / cerveau / "pont.conf"
        r = subprocess.run(
            ["bash", "-c", f'. "{conf}" && printf "%s\\n" "$ARAC_STATE_FILE"'],
            capture_output=True, text=True,
            env={**os.environ, "HOME": str(deux_cerveaux)},
        )
        assert r.returncode == 0, r.stderr
        assert r.stderr == "", f"Sourcer {conf} écrit sur stderr : {r.stderr}"
        assert r.stdout.strip().endswith(f"/.arac/{cerveau}/etat-pont.json"), r.stdout


def test_render_systemd_ne_pose_aucun_jeton(tmp_path: pathlib.Path) -> None:
    """Le second rendeur du dépôt, joué pour de vrai, dans un dossier à nous."""
    sortie = tmp_path / "unites"
    env = {
        **os.environ,
        "ARAC_UNIT_PREFIX": "arac-kzfaux",
        "ARAC_HOME": "/opt/faux-arac",
        "ARAC_ENV_FILE": "/etc/arac/kzfaux/arac.env",
        "ARAC_BACKUP_DIR": "/var/backups/kzfaux",
        "ARAC_BACKUP_STATE": "/var/lib/kzfaux",
        "ARAC_VAR_DIR": "/var/lib/kzfaux/var",
        "ARAC_SERVICE_USER": "arac_kzfaux",
        "ARAC_SERVICE_GROUP": "arac_kzfaux",
    }
    r = subprocess.run(
        ["bash", str(RACINE / "ops" / "systemd" / "render.sh"), str(sortie)],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
    )
    assert r.returncode == 0, r.stdout + r.stderr
    rendus = sorted(sortie.iterdir())
    assert rendus, "render.sh n'a rien rendu"
    for f in rendus:
        fautives = jetons_du_fichier_pose(f.read_text(encoding="utf-8"), chevrons=False)
        assert not fautives, f"{f.name} :\n" + "\n".join(fautives)


# ===========================================================================
# 4. LE CONTRÔLE REFUSE VRAIMENT — on le trompe, il doit rougir
# ===========================================================================


def test_installer_refuse_un_gabarit_qui_garde_un_jeton(
    tmp_path: pathlib.Path,
) -> None:
    """Un contrôle qu'on n'a jamais vu rougir n'est pas un contrôle.

    On remet dans une COPIE du gabarit la ligne exacte d'avant le correctif,
    sous une clé que le `sed` de `installer` ne vise pas. Le fichier doit être
    refusé, la commande doit sortir non nulle, et rien ne doit rester sur le
    disque : un pont.conf dont on vient de dire qu'il est faux n'a pas à être
    laissé en place « au cas où ».
    """
    faux_mac = tmp_path / "mac"
    faux_mac.mkdir()
    for nom in ("arac-pont.sh", "arac-sync.py", "pont.conf.example"):
        shutil.copy(RACINE / "mac" / nom, faux_mac / nom)
    gabarit = faux_mac / "pont.conf.example"
    gabarit.write_text(
        gabarit.read_text(encoding="utf-8")
        + "\nARAC_UN_CHEMIN_OUBLIE=$HOME/.arac/<un-jeton-oublie>/quelque-chose\n",
        encoding="utf-8",
    )

    foyer = tmp_path / "foyer"
    foyer.mkdir()
    r = _jouer_installer(faux_mac, foyer, cerveau="kz_temoin", node="poste",
                         ssh="hote", api="8241", cockpit="8242")

    assert r.returncode != 0, (
        "Le gabarit portait un jeton que le `sed` ne vise pas, et `installer` "
        "a rendu 0 :\n" + r.stdout
    )
    assert "<un-jeton-oublie>" in r.stdout, r.stdout
    assert not (foyer / ".arac" / "kz_temoin" / "pont.conf").exists(), (
        "Le fichier fautif a été laissé sur le disque."
    )


def test_le_controle_du_shell_et_celui_d_ici_refusent_la_meme_chose(
    tmp_path: pathlib.Path,
) -> None:
    """La règle est écrite deux fois — en bash et en Python. Elle doit tenir.

    On soumet les mêmes six lignes aux deux implémentations : celle de
    `mac/arac-pont.sh` (`jetons_non_resolus`) et celle de ce fichier. Deux
    écritures d'une même règle sont un risque de divergence ; ce test est le
    seul lien qui les tient ensemble.
    """
    echantillon = "\n".join(
        [
            "# un commentaire avec <adresse-de-votre-serveur> : de la prose",
            "ARAC_STATE_FILE=$HOME/.arac/<cerveau>/etat-pont.json",
            "ARAC_NODE_ID=poste-marc",
            "Environment=ARAC_HOME=__ARAC_HOME__",
            "    <string>@@FOYER@@/.arac</string>",
            "ARAC_PORT_API=8241",
        ]
    )
    attendu = {2, 4, 5}  # numéros de ligne fautifs

    assert {int(f.split(":")[0]) for f in jetons_du_fichier_pose(echantillon)} == attendu

    cible = tmp_path / "echantillon.conf"
    cible.write_text(echantillon, encoding="utf-8")
    foyer = tmp_path / "foyer-vide"
    foyer.mkdir()
    # `set -- aide` avant de sourcer : le répartiteur en fin de script lit `$1`,
    # et une commande inconnue s'y termine par `exit 2` — ce qui tuerait le
    # shell qui source. « aide » imprime et rend la main.
    r = subprocess.run(
        [
            "bash",
            "-c",
            'set -- aide; . "$SCRIPT" >/dev/null 2>&1; jetons_non_resolus "$CIBLE" || true',
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(foyer),
            "SCRIPT": str(RACINE / "mac" / "arac-pont.sh"),
            "CIBLE": str(cible),
        },
    )
    lignes_bash = {
        int(l.strip().split(":")[0]) for l in r.stdout.splitlines() if l.strip()
    }
    assert lignes_bash == attendu, (
        "Les deux écritures de la règle divergent.\n"
        f"  bash   : {sorted(lignes_bash)}\n"
        f"  python : {sorted(attendu)}\n"
        f"  (sortie brute : {r.stdout!r} / {r.stderr!r})"
    )
