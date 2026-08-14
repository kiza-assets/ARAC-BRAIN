"""LES PROMESSES QUE LE PRODUIT DOIT POUVOIR EXERCER LUI-MÊME.

Une promesse que personne ne peut exercer finit par n'être exercée par
personne — et elle reste vraie sur le papier pendant des mois. Ce fichier
n'exerce rien : il refuse mécaniquement que les trois promesses ci-dessous
redeviennent inexerçables.

Il est HERMÉTIQUE : ni base, ni réseau, ni service. Il lit des fichiers du
dépôt et, pour l'inventaire, il travaille dans un ``tmp_path``.

  1. La restauration vérifiée. `ops/restore_verify.sh` crée sa base jetable
     sous le rôle d'administration du cerveau. Ce rôle n'avait pas CREATEDB,
     et rien dans le dépôt ne le lui donnait : le script mourait sur
     « permission denied to create database » sur TOUTE installation posée par
     le bootstrap, et le chemin de secours documenté échouait pareil, sans
     imprimer le moindre geste. `ops/install_check.sh` portait donc en
     permanence « aucune restauration n'a jamais été vérifiée » — la seule
     promesse du dépôt que personne n'avait jamais pu vérifier.

  2. Le zéro d'une table gelée. La tuile « Conversations brutes » du tableau
     de bord comptait `arac.raw_conversations`, GELÉE depuis la migration
     0017. Elle affichait 0 le premier jour et 0 au bout de dix mille
     messages, pendant que /cc/v1/metrics servait la vérité. Un zéro faux est
     pire qu'une absence : il se mesure.

  3. Le gabarit jamais substitué. `mac/arac-sync.py --inventaire` testait
     littéralement « $HOME/.arac/<cerveau>/export-desktop » — un chemin qui
     n'existe jamais — et répondait « absent » sur un export bel et bien
     présent, que le pont venait d'envoyer avec succès.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]


def _lire(chemin: str) -> str:
    return (RACINE / chemin).read_text(encoding="utf-8")


def _code_seul(source: str) -> str:
    """La même source, sans ses lignes de commentaire shell.

    POURQUOI CETTE FONCTION EXISTE. Les gardes de ce fichier cherchent des
    INSTRUCTIONS. Les fichiers de ce dépôt expliquent longuement, dans leurs
    commentaires, le défaut qu'ils réparent — en citant la commande fautive.
    Un garde qui lit la source entière trouve donc son propre contre-exemple
    dans le récit de sa correction, et rougit sur un fichier corrigé. C'est le
    même piège que « compter les lignes “Pourquoi” » dans acceptance.sh : on
    regarde le CODE, pas la prose qui l'entoure.
    """
    return "\n".join(
        l for l in source.splitlines() if not l.lstrip().startswith("#")
    )


# ===========================================================================
# 1. LA RESTAURATION DOIT ÊTRE EXERÇABLE SUR UN CERVEAU POSÉ PAR LE BOOTSTRAP
# ===========================================================================


def test_le_bootstrap_donne_au_role_admin_de_quoi_creer_une_base_jetable():
    """Sans CREATEDB, aucune sauvegarde de ce dépôt ne peut être prouvée.

    Le rôle d'administration ne peut pas détruire la base vivante (elle
    appartient au superutilisateur) : c'est le privilège minimal qui rend le
    contrôle possible, et il doit être posé par l'installation, pas par un
    geste que personne ne fera.
    """
    src = _lire("bootstrap/lib/database.sh")
    assert re.search(r"ALTER ROLE \$R_ADMIN CREATEDB\s*;", src), (
        "bootstrap/lib/database.sh ne donne plus CREATEDB au rôle "
        "d'administration : ops/restore_verify.sh redevient inexécutable sur "
        "tout cerveau posé par le bootstrap."
    )


def test_le_bootstrap_pose_le_gabarit_de_restauration():
    """pgvector n'est pas « trusted » : sans gabarit, il faut le superutilisateur.

    Le gabarit doit être POSSÉDÉ par le rôle d'administration plutôt que marqué
    `datistemplate` : `datistemplate` le rendrait copiable par le rôle du
    cerveau VOISIN, et indestructible au premier essai de désinstallation.
    """
    src = _lire("bootstrap/lib/database.sh")
    assert "_gabarit_de_restauration" in src
    # LA GARANTIE, PAS SON ORTHOGRAPHE. Le `CREATE DATABASE` du gabarit
    # s'écrit désormais par `format('… %I OWNER %I …', :'tpl', :'admin')\gexec`
    # — l'identifiant est cité par le serveur au lieu de l'être à la main. Ce
    # qu'on garde, c'est que le gabarit soit créé AU NOM du rôle
    # d'administration de CE cerveau ; l'exiger à la lettre faisait rougir ce
    # test au premier durcissement du citage, alors que la promesse tenait.
    assert re.search(
        r'CREATE DATABASE[^\n]*OWNER[^\n]*(\$R_ADMIN|%I)', src
    ) and re.search(r"admin=\"\$R_ADMIN\"|OWNER \$R_ADMIN", src), (
        "le gabarit de restauration n'est plus créé au nom du rôle "
        "d'administration de ce cerveau."
    )
    assert "datistemplate = false" in src, (
        "le gabarit doit être explicitement démarqué : une base "
        "`datistemplate` refuse d'être détruite et s'ouvre au voisin."
    )


def test_restore_verify_ne_fait_deviner_aucun_nom_de_role():
    """Les deux branches d'échec doivent imprimer un geste, avec le VRAI rôle.

    La branche « gabarit présent » n'en portait AUCUN : elle imprimait
    « CREATE DATABASE ... TEMPLATE … a échoué. » et rien d'autre. Le lecteur
    qui avait fait ce qu'on lui disait se retrouvait devant un mur sans porte.
    """
    src = _lire("ops/restore_verify.sh")
    assert "_remede_createdb" in src
    # Les deux échecs de création de base appellent le même remède.
    assert src.count("$(_remede_createdb)") >= 2, (
        "une des deux branches de CREATE DATABASE n'imprime pas de geste."
    )
    # Et le remède nomme le rôle réel, lu dans le DSN — pas un gabarit.
    assert 'ROLE_ADMIN="$(arac_dsn_user "$MAINT_DSN")"' in src
    assert "arac_dsn_user" in _lire("ops/env.sh")


def test_install_check_mesure_les_deux_moities_de_la_promesse():
    """Le gabarit ne sert à rien si le rôle ne peut pas le copier.

    Le contrôle ne regardait que le gabarit — et exigeait `datistemplate`, ce
    qui déclarait « absent » un gabarit présent et utilisable.
    """
    src = _lire("ops/install_check.sh")
    assert "rolcreatedb" in src, (
        "ops/install_check.sh ne vérifie plus que le rôle peut créer une base "
        "jetable : la moitié de la promesse redevient invisible."
    )
    assert "AND datistemplate" not in src, (
        "la requête du gabarit exige de nouveau `datistemplate` : elle "
        "déclarera « absent » un gabarit présent et utilisable. La propriété "
        "suffit, et elle est plus étroite."
    )


def test_l_acceptation_joue_reellement_la_restauration():
    """`make acceptance` doit exercer la promesse, pas la citer."""
    src = _lire("tests/acceptance/acceptance.sh")
    assert "_preuve_restauration" in src
    assert "ops/restore_verify.sh" in src
    assert "aucune restauration n'a jamais été vérifiée" in src, (
        "l'acceptation ne vérifie plus que la réserve permanente TOMBE."
    )


def test_il_n_existe_qu_une_seule_sauvegarde_dans_ce_depot():
    """L'unité que le bootstrap arme doit APPELER `ops/backup.sh`, pas dumper elle-même.

    Le défaut, mesuré : l'`ExecStart` inlinait `pg_dump -Fc` sans `--schema`.
    Le dump portait alors deux entrées `COMMENT - EXTENSION`, et
    `COMMENT ON EXTENSION` exige d'être PROPRIÉTAIRE de l'extension. Or
    `ops/restore_verify.sh` restaure — délibérément — sous le rôle
    d'administration, qui n'est pas superutilisateur. Le SEUL dump qu'une
    installation par ce bootstrap produise était donc déclaré irrestaurable,
    avec le message « Le coffre est vide » — sur une sauvegarde parfaitement
    saine. Deux implémentations de la sauvegarde, un seul nom.
    """
    src = _code_seul(_lire("bootstrap/lib/services.sh"))
    debut = src.index("_unite_backup()")
    corps = src[debut : src.index("_unite_backup_timer()")]
    assert "ExecStart=$ARAC_HOME/ops/backup.sh" in corps, (
        "l'unité de sauvegarde ne passe plus par ops/backup.sh : le dépôt "
        "reprend deux sauvegardes différentes sous le même nom, et seule "
        "l'une des deux se restaure."
    )
    assert "pg_dump" not in corps, (
        "l'unité de sauvegarde dumpe de nouveau elle-même. Tout ce que "
        "`ops/backup.sh` apporte — planchers de sincérité, contrôle du "
        "sommaire, écriture en .partial, chiffrement, rotation APRÈS succès, "
        "registre des tailles — redisparaît en silence."
    )


def test_l_acceptation_fabrique_son_dump_avec_l_unite_et_pas_avec_l_autre_chemin():
    """Une assertion qui ne peut pas rencontrer son contre-exemple n'est pas une preuve.

    `_preuve_restauration` lançait `ops/backup.sh` puis `ops/restore_verify.sh`
    dos à dos : le vert tombait à chaque exécution, et l'installation que
    l'acceptation venait de faire n'empruntait jamais ce chemin.
    """
    src = _lire("tests/acceptance/acceptance.sh")
    debut = src.index("_preuve_restauration() {")
    corps = src[debut : src.index("_env_bootstrap()")]
    assert 'systemctl start "$PREFIXE_UNITE-sauvegarde.service"' in corps, (
        "l'acceptation ne fabrique plus son dump avec l'unité posée par le "
        "bootstrap : elle certifierait de nouveau la branche que le lecteur "
        "n'emprunte pas."
    )
    assert "ops/backup.sh" not in corps, (
        "l'acceptation contourne l'unité en appelant ops/backup.sh directement."
    )
    # L'étape doit être INSCRITE AU PROGRAMME, pas seulement définie quelque
    # part : une fonction que le déroulé n'appelle plus ne prouve rien. Le
    # déroulé est passé d'une suite d'appels `etape 8 "…"` à un tableau
    # `PROGRAMME`, pour que le dénominateur du rapport soit compté et non tapé.
    assert re.search(
        r'^\s*"[^"]+\|etape_8_prouver_sa_sauvegarde"\s*$', src, re.M
    ), (
        "l'étape d'acceptation qui joue le cycle complet de sauvegarde n'est "
        "plus inscrite dans PROGRAMME : la promesse redevient non prouvée."
    )


def test_le_bootstrap_arme_la_restauration_verifiee():
    """« Aucun minuteur ne le fait à votre place » était vrai, et c'était le défaut.

    `docs/SAUVEGARDE.md` ouvre sur « une sauvegarde qui n'a jamais été
    restaurée n'est pas une sauvegarde ». Tant que rien ne restaure, la phrase
    est un slogan et `ops/install_check.sh` porte à vie « vos dumps sont une
    hypothèse ».
    """
    services = _lire("bootstrap/lib/services.sh")
    config = _lire("bootstrap/lib/config.sh")
    assert 'U_RESTORE="${PREFIXE_UNITE}-restauration"' in config, (
        "l'unité de restauration vérifiée n'est plus nommée : elle porterait "
        "un nom commun à la machine, donc partagé entre cerveaux."
    )
    assert "ExecStart=$ARAC_HOME/ops/restore_verify.sh" in services
    assert '_poser_unite "$U_RESTORE.timer"' in services
    assert '"$U_RESTORE.timer"' in services.split("systemctl daemon-reload")[1], (
        "la minuterie de restauration est posée mais jamais armée."
    )
    # Code 2 = « restauré, preuve partielle » : ce n'est pas un échec, et une
    # unité rouge en permanence ne se lit plus.
    assert "SuccessExitStatus=2" in services

    # ET LA PHRASE, ELLE ? Ce test regardait le fichier qu'on venait de
    # corriger, jamais celui qui portait le défaut. `ops/install_check.sh`
    # continuait donc de servir, sur toute installation neuve, « Aucun minuteur
    # ne le fait à votre place — c'est un geste qu'on décide » DOUZE LIGNES
    # avant que la section 5 du même écran n'imprime le minuteur qui le fait.
    # Une assertion qui ne peut pas rencontrer son contre-exemple n'en est pas
    # une : celle-ci va lire la phrase là où l'utilisateur la lit.
    # On lit le CODE SEUL : le commentaire a le droit de citer la phrase
    # fautive pour raconter ce qu'il répare. C'est ce qu'elle IMPRIME qui ment.
    check = _code_seul(_lire("ops/install_check.sh"))
    assert "Aucun minuteur ne le fait à votre place" not in check, (
        "ops/install_check.sh redit « Aucun minuteur ne le fait à votre "
        "place » alors que le bootstrap arme « …-restauration.timer ». Deux "
        "organes du même produit se contrediraient sur la seule question que "
        "cette page existe pour trancher."
    )
    assert "-restauration.timer" in check, (
        "ops/install_check.sh ne demande plus à systemd si le minuteur de "
        "restauration de CE cerveau existe : il ne peut donc que supposer, et "
        "il supposait le contraire de ce qu'il montrait."
    )
    verif = _lire("bootstrap/checks/verify_install.sh")
    assert "-restauration.timer" in verif, (
        "la section 7 de verify_install.sh prescrit encore la restauration "
        "comme un geste « à jouer au moins une fois » sans savoir qu'une "
        "minuterie la joue déjà chaque semaine."
    )


def test_le_controle_lit_la_memoire_sous_les_roles_du_cerveau():
    """« Est-ce mon cerveau qui répond ? » ne se prouve pas avec `SELECT 1`.

    `docs/SAUVEGARDE.md` §7 clôt la bascule par `verify_install.sh` et justifie
    ce choix en propres termes. Or son seul contrôle par rôle était un
    `SELECT 1`, qui ne touche aucun objet du schéma, et tous ses comptages de
    contenu passaient par le SUPERUTILISATEUR, à qui aucun droit ne manque
    jamais. Mesuré : « ✓ Ce cerveau fonctionne », code 0, sur une base
    restaurée dont le schéma appartenait à `postgres`, dont aucun rôle ne
    pouvait lire un souvenir, et dont l'API rendait 500 sur toutes ses routes
    de données. Une preuve verte par construction, à l'endroit exact où la page
    du pire jour dit de la croire.
    """
    src = _lire("bootstrap/checks/verify_install.sh")
    assert 'sous_role "$cle" "SELECT 1"' not in src, (
        "le contrôle par rôle est redevenu un `SELECT 1` : il ne peut plus "
        "rougir sur la perte de droits, qui est LA panne d'après-restauration."
    )
    assert 'sous_role "$cle" "SELECT count(*) FROM $ARAC_SCHEMA.memory_atoms"' in src, (
        "aucune ligne de ce fichier ne lit une table du schéma sous le rôle de "
        "l'application."
    )
    assert "permission denied" in src, (
        "le contrôle ne distingue plus « pas le droit de lire » (la panne "
        "d'après-restauration) de « la table n'existe pas encore » (une "
        "installation à mi-chemin) : deux gestes opposés pour un seul verdict."
    )
    # L'identité de la base elle-même : le nom a suivi la bascule, la mémoire
    # peut ne pas l'avoir suivie.
    assert "controle_apres_bascule" in src, (
        "plus rien ne vérifie, après une bascule, que la base qui porte le nom "
        "du cerveau porte AUSSI son empreinte."
    )


def test_le_dump_dit_de_quel_cerveau_il_vient():
    """Un dump qui ne porte pas son identité se restaure quand même — ailleurs.

    `ops/restore_verify.sh` savait dire qu'un dump SE RESTAURE, jamais DE QUI
    il vient, et il concluait « PROUVÉ ». Sur une machine à plusieurs cerveaux,
    c'est une preuve verte rangée à côté d'une mémoire qui n'est pas la sienne.

    L'identité ne peut pas venir du nom du fichier — il se recopie, et le pire
    jour est celui où l'on choisit mal dans une liste de noms qui se
    ressemblent. Elle est donc GRAVÉE dans le commentaire du schéma par le
    bootstrap, et `pg_dump --schema` l'emporte à l'intérieur du dump.
    """
    db = _lire("bootstrap/lib/database.sh")
    assert "COMMENT ON SCHEMA %I IS %L" in db, (
        "le bootstrap ne grave plus l'empreinte dans le schéma : plus aucun "
        "dump ne dira de quel cerveau il vient."
    )
    assert "empreinte=" in db

    src = _lire("ops/restore_verify.sh")
    assert "PREUVE D" in src, "la preuve d'identité a disparu du verdict."
    assert "obj_description(to_regnamespace" in src, (
        "l'identité n'est plus lue DANS la base restaurée : la lire ailleurs "
        "reviendrait à faire confiance au nom du fichier."
    )
    assert "IDENTITE_KO" in src, (
        "un dump étranger ne fait plus échouer le verdict, ou l'échec ne se "
        "distingue plus d'un dump illisible — deux pannes, deux gestes."
    )


def test_la_preuve_ne_condamne_pas_le_dump_quand_le_cerveau_est_mort():
    """Le jour où ce contrôle sert le plus est celui où la base vivante est morte.

    §7 en fait sa PREMIÈRE étape (« choisir le dump, et le prouver AVANT de
    s'en servir »), et sa consigne d'échec est « prenez le dump précédent et
    recommencez ». Or la comparaison lisait `${L_ATOMS:-0}` : une mesure
    IMPOSSIBLE devenait une mesure à ZÉRO, tout dump paraissait « contenir plus
    d'atomes que la base vivante », et TOUS les dumps échouaient l'un après
    l'autre. Mesuré sur un cerveau réel au schéma détruit, avec un dump
    parfaitement bon.
    """
    src = _lire("ops/restore_verify.sh")
    assert "L_ATOMS=''" in src, (
        "la mesure du vivant n'est plus initialisée à « pas mesuré » : elle "
        "retombe sur zéro, et zéro est une mesure."
    )
    assert 'elif [ -z "$L_ATOMS" ]; then' in src, (
        "« la base vivante ne se laisse plus lire » n'est plus distingué de "
        "« la base vivante contient zéro atome » : le premier accuse le dump "
        "d'un défaut qui est celui du cerveau."
    )


def test_la_restauration_ne_detruit_que_ce_qu_elle_a_cree():
    """Le `trap` était armé AVANT toute création, et tiré sur toutes les sorties.

    Mesuré : `ARAC_RESTORE_DB=<base d'un voisin>` faisait partir
    `DROP DATABASE IF EXISTS "<base du voisin>"` contre le serveur, sur le
    chemin de sortie où le script sort PARCE QUE la cible n'est pas à lui. La
    base vivante du voisin tenait par la propriété PostgreSQL ; le gabarit de
    restauration, lui, appartient au rôle du cerveau — il était réellement
    détruit.
    """
    src = _code_seul(_lire("ops/restore_verify.sh"))
    assert "CREEE_PAR_MOI=0" in src, (
        "le drapeau qui distingue « base créée par moi » de « base trouvée "
        "là » a disparu : le nettoyage redevient une destruction aveugle."
    )
    assert src.count("CREEE_PAR_MOI=1") >= 2, (
        "une des deux branches de CREATE DATABASE ne marque pas la base "
        "comme créée par ce script."
    )
    # Le refus interroge le SERVEUR avant d'armer le piège.
    i_refus = src.index("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = '$TARGET'")
    i_trap = src.index("trap cleanup EXIT")
    assert i_refus < i_trap, (
        "le piège de nettoyage est de nouveau armé avant que l'existence de "
        "la cible ne soit vérifiée."
    )
    assert 'if [ "$CREEE_PAR_MOI" -ne 1 ]' in src


def test_aucune_base_de_restauration_n_est_ouverte_a_tous():
    """`CREATE DATABASE … TEMPLATE …` ne recopie pas les privilèges du gabarit.

    Les deux bases naissaient donc avec le CONNECT que PostgreSQL donne à
    PUBLIC. Mesuré : le rôle applicatif du cerveau voisin se connectait à la
    base de restauration — qui contient, le temps de la vérification,
    l'intégralité du cerveau — et y lisait le catalogue : noms de tables,
    colonnes, volumétrie.
    """
    verify = _lire("ops/restore_verify.sh")
    database = _lire("bootstrap/lib/database.sh")
    assert "REVOKE CONNECT ON DATABASE \\\"$TARGET\\\" FROM PUBLIC" in verify, (
        "la base jetable redevient connectable par toute la grappe."
    )
    # Même raison qu'au-dessus : `REVOKE CONNECT ON DATABASE %I FROM PUBLIC`
    # passé à `format()` vaut le littéral, et se cite mieux.
    assert re.search(
        r"REVOKE CONNECT ON DATABASE[^\n]*(\\\"\$tpl\\\"|%I)[^\n]*FROM PUBLIC", database
    ), (
        "le gabarit de restauration redevient connectable par toute la "
        "grappe — et lui est PERMANENT."
    )


def test_le_garde_de_cible_connait_plus_qu_un_nom():
    """Un garde qui ne connaît qu'un nom protège un nom, pas une classe."""
    guard = _lire("ops/restore_guard.sh")
    verify = _lire("ops/restore_verify.sh")
    assert 'for interdit in "$@"' in guard, (
        "arac_target_forbidden ne prend de nouveau qu'un seul nom interdit."
    )
    assert 'arac_target_forbidden "$TARGET" "$LIVE_DB" "$TEMPLATE_DB"' in verify, (
        "le gabarit de restauration n'est plus passé au garde : il redevient "
        "une cible acceptable, et sa destruction rend la preuve de "
        "sauvegarde impossible."
    )
    assert "le gabarit de restauration est refusé comme cible" in guard, (
        "le banc d'essai du garde n'éprouve plus le cas qui a réellement "
        "détruit une base."
    )


def test_la_desinstallation_a_un_controle_qui_sait_dire_pourquoi():
    """Un contrôle qui ne voit pas la cause de l'échec qu'il signale envoie
    chercher au mauvais endroit.

    Le contrôle de fin du §13 imprimait le nom du rôle survivant sans pouvoir
    dire ce qui le retenait : sa requête ne regardait que `datname='$BASE'`,
    donc jamais `<base>_restore_template`, qui est la cause.
    """
    src = _lire("ops/uninstall_check.sh")
    assert "pg_shdepend" in src, (
        "le contrôle ne demande plus au serveur ce qui retient un rôle."
    )
    # LE MOTIF DES BASES : TOUTE NAISSANCE DÉRIVÉE DU NOM DU CERVEAU.
    #
    # Il ne cherchait que `<base>_restore_%` — les deux naissances du bootstrap
    # et de `ops/restore_verify.sh`. `docs/SAUVEGARDE.md` §7 en fait naître deux
    # AUTRES, `<base>_restauree_<date>` et `<base>_avarie_<date>`, et demande
    # expressément de garder la seconde. Mesuré : après §7 puis §13, la
    # section 1 imprimait « ✓ aucune base » sur une grappe qui portait le
    # cerveau entier en clair, et les cinq DROP ROLE échouaient dessus.
    #
    # Une liste de suffixes oublierait le suivant. On exige donc le motif
    # général — et son garde-fou, sans lequel il serait pire que le défaut.
    assert "'${BASE}\\\\_%'" in src, (
        "le contrôle ne cherche plus TOUTES les bases dérivées du nom de ce "
        "cerveau : une liste de suffixes oublie toujours le prochain."
    )
    assert "arac_' || d.datname || '_admin" in src, (
        "le garde-fou du VOISIN a disparu. Avec le motif large et sans lui, "
        "`uninstall_check.sh bascule` imprimerait `dropdb bascule_deux` : la "
        "mémoire d'un autre cerveau, détruite par une ressemblance de nom."
    )
    for suffixe in ("_avarie_", "_restauree_", "_restore_template"):
        assert suffixe in src, (
            f"« <base>{suffixe} » n'est plus nommée : le contrôle la verrait "
            "sans savoir dire d'où elle vient, ni pourquoi elle est là."
        )
    # Un répertoire de drop-in ne se retire pas avec `rm -f`.
    assert 'if [ -d "$f" ]; then' in src, (
        "les drop-ins de systemd redeviennent des « fichiers » : la dernière "
        "commande imprimée échouerait sur « Is a directory » — et c'est un "
        "répertoire que l'en-tête de chaque unité invite à créer "
        "(« sudo systemctl edit … »)."
    )
    assert '"/var/lib/systemd/timers/stamp-$PREFIXE_UNITE-"' in src, (
        "les estampilles de minuteur ne sont plus regardées : une "
        "réinstallation homonyme repartirait avec l'horloge de la précédente."
    )
    assert "--gestes" in src and "dropdb" in src, (
        "le contrôle ne sait plus imprimer les gestes qui restent à faire."
    )
    # Il ne détruit rien lui-même : la destruction se lit avant de se faire.
    for verbe in ("dropdb -p", "DROP ROLE", "rm -rf"):
        assert verbe in src
    assert "GESTES_ARRET+=" in src, (
        "les gestes ne sont plus collectés mais exécutés : un outil qui sait "
        "détruire une mémoire est un outil dangereux à livrer."
    )
    # L'ORDRE DES GESTES EST LE GESTE. Le bloc s'ouvrait sur « les bases
    # d'abord, les rôles ensuite » et imprimait le dropdb AVANT l'arrêt des
    # services : copié tel quel, il rendait « database is being accessed by
    # other users », puis cinq DROP ROLE en échec. Mesuré.
    for famille in ("GESTES_ARRET", "GESTES_BASE", "GESTES_ROLE", "GESTES_FICHIER"):
        assert f'_bloc "' in src and famille in src, (
            f"la famille de gestes {famille} a disparu : l'ordre d'exécution "
            "redevient l'ordre d'affichage du rapport, qui ne passe pas."
        )
    positions = [src.index(f'_bloc "{n}.') for n in (1, 2, 3, 4)]
    assert positions == sorted(positions), (
        "les quatre temps du démontage ne sont plus imprimés dans l'ordre où "
        "ils passent : arrêter, les bases, les rôles, les fichiers."
    )


# ===========================================================================
# 2. AUCUNE TUILE NE COMPTE UNE TABLE QUE PLUS RIEN N'ÉCRIT
# ===========================================================================


def _tables_gelees() -> set[str]:
    """Les tables qu'une migration déclare gelées, lues dans les migrations."""
    gelees: set[str] = set()
    for mig in (RACINE / "db/alembic/versions").glob("*freeze*.py"):
        for nom in re.findall(r"arac\.([a-z_]+)", mig.read_text(encoding="utf-8")):
            gelees.add(nom)
    return gelees


def test_la_migration_declare_bien_raw_conversations_gelee():
    """Le garde ci-dessous n'a de sens que si la liste vient du dépôt."""
    assert "raw_conversations" in _tables_gelees()


def test_le_collecteur_de_la_table_gelee_dit_qu_elle_est_gelee():
    src = _lire("control_center/collectors/db_metrics.py")
    bloc = src.split("def raw_conversations_count")[1].split("def ", 1)[0]
    assert "GELÉE" in bloc, (
        "raw_conversations_count ne prévient plus que sa table est gelée : "
        "la prochaine tuile s'y branchera sans le savoir."
    )


def test_aucune_tuile_ne_montre_la_table_gelee_sans_la_nommer():
    """Un 0 sur une table gelée n'est pas un 0, c'est une absence."""
    src = _lire("control_center/app.py")
    for etiquette in re.findall(r'render_tile\(\s*"([^"]+)",\s*raw_total', src):
        assert "gelée" in etiquette.lower(), (
            f"la tuile « {etiquette} » compte la table gelée "
            "arac.raw_conversations sans le dire : elle affichera 0 pour "
            "toujours, y compris sur un cerveau qui absorbe tous les jours."
        )


def test_le_tableau_de_bord_compte_ce_que_l_ingestion_ecrit_vraiment():
    """L'ingestion V2 écrit `conversations` et `raw_messages` — c'est cela qu'on montre."""
    src = _lire("control_center/app.py")
    assert "db_metrics.conversations_count()" in src
    assert "db_metrics.raw_messages_count()" in src
    collectors = _lire("control_center/collectors/db_metrics.py")
    assert "def conversations_count" in collectors
    assert "def raw_messages_count" in collectors


# ===========================================================================
# 3. L'INVENTAIRE NE DIT « ABSENT » QUE DE CE QU'IL A REGARDÉ
# ===========================================================================


def _charger_pont():
    chemin = RACINE / "mac/arac-sync.py"
    spec = importlib.util.spec_from_file_location("arac_sync_pont", chemin)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_l_inventaire_trouve_un_export_reellement_depose(tmp_path, capsys):
    """Le cas exact du défaut : l'export est là, et la commande disait « absent »."""
    pont = _charger_pont()

    foyer = tmp_path / "arac" / "essai"
    (foyer / "export-desktop").mkdir(parents=True)
    (foyer / "export-desktop" / "conversations.json").write_text("[]", encoding="utf-8")
    projets = tmp_path / "claude" / "projects"
    projets.mkdir(parents=True)
    (projets / "une.jsonl").write_text("{}\n", encoding="utf-8")

    conf = tmp_path / "pont.conf"
    conf.write_text(
        "\n".join(
            [
                "ARAC_NODE_ID=poste-essai",
                "ARAC_INGEST_URL=http://127.0.0.1:1/v1/ingest/messages",
                f"ARAC_TOKEN_FILE={tmp_path}/jeton",
                f"ARAC_CLAUDE_CODE_DIR={projets}",
                f"ARAC_DESKTOP_EXPORT={foyer}/export-desktop/conversations.json",
                f"ARAC_STATE_FILE={tmp_path}/etat.json",
                f"ARAC_LOG_FILE={tmp_path}/journal/pont.log",
                "ARAC_MAX_CONVERSATIONS=0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    config = pont.Config(chemin_conf=str(conf))
    journal = pont.Journal(config.chemin("ARAC_LOG_FILE"))
    pont.inventaire(journal, config)
    ecran = capsys.readouterr().out

    bloc = ecran.split("export-desktop", 1)
    assert len(bloc) > 1, ecran
    ligne_export = bloc[1].split("$HOME/Library", 1)[0]
    assert "→ absent" not in ligne_export, (
        "l'inventaire déclare « absent » un export qui est là :\n" + ecran
    )
    assert str(foyer / "export-desktop") in ecran, (
        "l'inventaire n'imprime pas le chemin RÉELLEMENT regardé :\n" + ecran
    )


def test_aucun_candidat_ne_reste_un_gabarit_non_substitue():
    """Un chemin qui porte encore un chevron n'est pas « absent ».

    C'est la règle qu'`ops/install_check.sh` applique déjà : quand un contrôle
    ne peut pas mesurer, il ne tranche pas.
    """
    pont = _charger_pont()
    for brut, cle, _ in pont.CANDIDATS_MAC:
        if "<" in brut:
            assert cle, (
                f"« {brut} » porte un gabarit et aucune clé de configuration "
                "ne dit comment le résoudre : la ligne dira « absent » quoi "
                "qu'il arrive."
            )


def test_l_inventaire_signale_claude_config_dir(tmp_path, capsys, monkeypatch):
    """Claude Code range ses transcriptions ailleurs si CLAUDE_CONFIG_DIR est posée.

    Vérifié sur le CLI installé : la variable existe, et les transcriptions
    vivent dans `<config>/projects`. Le pont ne déplace rien tout seul — il le
    DIT, parce que c'est exactement la panne que `--inventaire` promet de
    détecter : « relancez-la le jour où le pont se tait ».
    """
    pont = _charger_pont()
    ailleurs = tmp_path / "ailleurs"
    (ailleurs / "projects").mkdir(parents=True)
    conf = tmp_path / "pont.conf"
    conf.write_text(
        "\n".join(
            [
                "ARAC_NODE_ID=poste-essai",
                "ARAC_INGEST_URL=http://127.0.0.1:1/v1/ingest/messages",
                f"ARAC_TOKEN_FILE={tmp_path}/jeton",
                f"ARAC_CLAUDE_CODE_DIR={tmp_path}/claude/projects",
                f"ARAC_DESKTOP_EXPORT={tmp_path}/export/conversations.json",
                f"ARAC_STATE_FILE={tmp_path}/etat.json",
                f"ARAC_LOG_FILE={tmp_path}/journal/pont.log",
                "ARAC_MAX_CONVERSATIONS=0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(ailleurs))
    config = pont.Config(chemin_conf=str(conf))
    journal = pont.Journal(config.chemin("ARAC_LOG_FILE"))
    pont.inventaire(journal, config)
    ecran = capsys.readouterr().out
    assert "CLAUDE_CONFIG_DIR" in ecran and str(ailleurs / "projects") in ecran, ecran


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

