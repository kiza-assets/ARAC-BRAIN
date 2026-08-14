#!/usr/bin/env bash
# ============================================================================
# LA RESTAURATION VÉRIFIÉE — la seule preuve qu'une sauvegarde existe
#
#     ops/restore_verify.sh              # sur le dump le plus récent
#     ops/restore_verify.sh /chemin/vers/un.dump
#     ops/restore_verify.sh --keep       # ne détruit pas la base jetable
#
# CODES DE SORTIE
#   0  restauration PROUVÉE — le dump se restaure et son contenu est là
#   1  ÉCHEC — ce dump ne restaure pas, ou restaure un cerveau amputé
#   2  restauré, preuve PARTIELLE — la base vivante n'était pas joignable,
#      donc les contrôles de comparaison n'ont pas pu être faits
#
# POURQUOI CE SCRIPT EST LE PLUS IMPORTANT DU DÉPÔT
# -------------------------------------------------
# Une sauvegarde jamais restaurée n'est pas une sauvegarde : c'est un fichier
# dont on suppose qu'il contient quelque chose. Les trois façons dont un coffre
# se révèle vide au pire moment sont toujours les mêmes :
#
#   — le dump est là, mais pg_restore refuse (extension absente, version de
#     PostgreSQL incompatible, fichier tronqué) ;
#   — le dump se restaure, mais il lui manque une table créée par une migration
#     postérieure au dernier dump réussi ;
#   — le dump se restaure entièrement, et son contenu date de trois semaines
#     parce que la source alimentait une autre base depuis un mois.
#
# Aucune de ces trois pannes ne se voit sur un `ls -lh`. Toutes les trois se
# voient ici, parce qu'on RESTAURE VRAIMENT, dans une base jetable, et qu'on
# regarde ce qui en sort.
#
# CE QUI EST DÉTRUIT, CE QUI NE L'EST PAS
# ---------------------------------------
# Ce script crée une base au nom horodaté, y restaure, l'interroge, la détruit.
# Il ne touche JAMAIS à la base vivante — le garde `arac_target_forbidden` le
# lui interdit, et le nom de la base vivante est lu dans VOTRE configuration,
# pas deviné. La seule chose qu'il lise en production, ce sont des `count(*)`
# via le rôle en lecture stricte.
# ============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$HERE/env.sh"
# shellcheck source=restore_guard.sh
source "$HERE/restore_guard.sh"


# ----------------------------------------------------------------------------
# Réglages
# ----------------------------------------------------------------------------

#: Écart maximal toléré entre le contenu du dump et celui de la base vivante,
#: en heures. La sauvegarde tourne QUATRE FOIS PAR JOUR (`OnCalendar=*-*-*
#: 00,06,12,18:30:00 UTC`) : l'intervalle réel est de SIX heures, pas d'un jour.
#: 26 h est donc hérité d'une cadence quotidienne révolue — il vaut quatre
#: passages manqués, et il tolère large. Au-delà, le dump ne décrit plus le
#: cerveau d'aujourd'hui : soit la sauvegarde vise une autre base, soit elle a
#: cessé de tourner sans le dire. Pour coller à la cadence :
#: `ARAC_RESTORE_FRESHNESS_H=8`.
FRESHNESS_H="${ARAC_RESTORE_FRESHNESS_H:-26}"

#: Les tables dont l'absence rend la restauration inutile. Même liste que le
#: contrôle de sommaire — ici on ne lit plus le sommaire, on interroge la base
#: restaurée : une table déclarée dans le sommaire mais vide de structure se
#: verrait ici, et pas là-bas.
mapfile -t REQUIRED < <(
    if [ -n "${ARAC_BACKUP_REQUIRED_TABLES:-}" ]; then
        # shellcheck disable=SC2086
        printf '%s\n' $ARAC_BACKUP_REQUIRED_TABLES
    else
        printf '%s\n' memory_atoms memory_atom_reprs conversations raw_messages \
                      nodes scopes run_receipts ingest_receipts context_receipts \
                      alembic_version
    fi
)

KEEP=0
PREPARE=0
DUMP_ARG=''
for a in "$@"; do
    case "$a" in
        --keep)             KEEP=1 ;;
        --prepare-template) PREPARE=1 ;;
        -*)                 arac_die "option inconnue : $a" ;;
        *)                  DUMP_ARG="$a" ;;
    esac
done


# ----------------------------------------------------------------------------
# LE NOM DU GABARIT EST JUGÉ ICI — avant les DEUX chemins qui l'emploient
# ----------------------------------------------------------------------------
#
# CE QUE CE BLOC RÉPARE, ET IL A MIS DEUX MANCHES À ÊTRE ÉCRIT. Vingt lignes
# plus bas, `ARAC_RESTORE_DB` est refusé s'il n'est pas un identifiant banal,
# et la raison imprimée avec le refus est exacte : « il n'y a pas de paramètre
# lié pour cette instruction, donc pas d'autre protection que ce refus ».
# `ARAC_RESTORE_TEMPLATE_DB` vient de la MÊME source — l'environnement, ou le
# coffre — et finit dans le MÊME genre d'instruction. Il n'était contrôlé nulle
# part. Deux chemins l'emportaient :
#
#   · le bloc `--prepare-template`, le seul texte de tout ce dépôt que le
#     produit demande de passer en SUPERUTILISATEUR ;
#   · le DDL que le BOOTSTRAP exécute lui-même à son étape 4, sous
#     `sudo -u postgres`, sans qu'aucun humain ne relise rien
#     (bootstrap/lib/config.sh, `GABARIT_RESTAURATION`, qui porte désormais
#     le même refus, à la même place et pour la même raison).
#
# Mesuré : `TPL="gab'; UPDATE pg_database SET datistemplate = true WHERE
# datname = 'victime'; --"` fait exécuter l'instruction injectée par le
# superutilisateur, et elle atteint une base tierce. Le dégât est celui que
# `bootstrap/lib/database.sh` documente lui-même vingt lignes au-dessus du
# geste : une base marquée `datistemplate` devient COPIABLE par tout rôle
# CREATEDB de la grappe — y compris celui du cerveau voisin — et REFUSE d'être
# détruite. Une seule variable non filtrée retourne donc contre le voisin les
# deux dangers que ce fichier existe pour éviter.
#
# LE JUGEMENT EST POSÉ AVANT LE `if [ "$PREPARE" ]`, ET C'EST LE POINT :
# `--prepare-template` sortait en 0 après avoir imprimé, donc tout contrôle
# placé après lui ne voyait jamais ce chemin-là.
#
# ARAC_BACKUP_PREFIX EST DANS LE MÊME SAC. Quand `ARAC_RESTORE_TEMPLATE_DB`
# n'est pas posée, le nom du gabarit est composé à partir d'elle : la refuser
# ici ferme la porte que l'on croyait n'avoir qu'une serrure.
TEMPLATE_DB="${ARAC_RESTORE_TEMPLATE_DB:-${ARAC_BACKUP_PREFIX:-}_restore_template}"

arac_db_name_safe "$TEMPLATE_DB" || arac_die \
"Nom de gabarit de restauration REFUSÉ : « $TEMPLATE_DB »

Seuls les identifiants PostgreSQL banals sont acceptés ([a-z_][a-z0-9_]{0,62}).

Ce nom finit interpolé dans des instructions SQL que rien ne peut protéger
autrement : ni « CREATE DATABASE », ni « ALTER DATABASE », ni « UPDATE
pg_database » n'acceptent de paramètre lié. L'un de ces deux chemins l'emporte
jusqu'au SUPERUTILISATEUR — le bloc « --prepare-template » qu'on vous demande
de passer en sudo, et le DDL que le bootstrap exécute à son étape 4. Un
superutilisateur peut rendre la base du VOISIN copiable par tout le monde, ou
indestructible.

D'où vient ce nom :
  ARAC_RESTORE_TEMPLATE_DB=${ARAC_RESTORE_TEMPLATE_DB:-<non posée>}
  ARAC_BACKUP_PREFIX=${ARAC_BACKUP_PREFIX:-<non posée>}   (compose le nom par défaut)
Retirez celle qui est fautive, ou donnez-lui un nom banal."


# --------------------------------------------------------------------------
# --prepare-template : le geste unique du superutilisateur
# --------------------------------------------------------------------------
# Ce script n'exécute PAS ce SQL : il l'imprime. Une commande qui réclame le
# superutilisateur doit être lue avant d'être lancée, par la personne qui a ce
# pouvoir — c'est la seule protection qui vaille contre un script d'ops qui
# demande « juste un petit sudo » tous les six mois.
if [ "$PREPARE" -eq 1 ]; then
    TPL="$TEMPLATE_DB"
    # LE RÔLE, DANS LA COMMANDE IMPRIMÉE — même raison que le port.
    # Ce bloc contient un ALTER ROLE : le laisser en « <votre rôle admin> »,
    # c'est demander à quelqu'un de deviner un nom de rôle sur une machine qui
    # en porte cinq par cerveau. On le lit dans le DSN d'administration.
    _ROLE_ADMIN="$(arac_dsn_user "${DATABASE_URL_ADMIN:-}")"
    [ -n "$_ROLE_ADMIN" ] || _ROLE_ADMIN="$(arac_dsn_user "$(arac_maintenance_dsn 2>/dev/null || true)")"
    # UN NOM DE RÔLE EST UN IDENTIFIANT, LUI AUSSI — et il arrive du DSN,
    # c'est-à-dire du coffre, c'est-à-dire d'ailleurs. Le bloc imprimé contient
    # `ALTER ROLE … CREATEDB` et deux `GRANT` : la même classe d'instruction,
    # le même absence de paramètre lié, le même superutilisateur au bout. On ne
    # ferme pas une porte en laissant sa jumelle ouverte.
    #
    # `<votre rôle admin>` n'est PAS un identifiant, et c'est voulu : c'est un
    # trou à remplir par un humain, dans un bloc qu'aucune machine n'exécute.
    # On ne le refuse donc que lorsqu'il vient VRAIMENT d'un DSN.
    if [ -n "$_ROLE_ADMIN" ] && ! arac_db_name_safe "$_ROLE_ADMIN"; then
        arac_die \
"Nom de rôle d'administration REFUSÉ : « $_ROLE_ADMIN »

Il est lu dans DATABASE_URL_ADMIN (ou ARAC_MAINTENANCE_DSN) et il finirait
interpolé dans « ALTER ROLE … CREATEDB » et « GRANT CONNECT … », dans un bloc
que ce script vous demande de passer en SUPERUTILISATEUR. Seuls les
identifiants PostgreSQL banals sont acceptés."
    fi
    [ -n "$_ROLE_ADMIN" ] || _ROLE_ADMIN="<votre rôle admin>"
    # LE PORT, DANS LA COMMANDE IMPRIMÉE.
    #
    # Sans `-p`, `sudo -u postgres psql` s'adresse à la grappe PAR DÉFAUT de la
    # machine, pas à celle où vit ce cerveau. Or ce bloc commence par
    # `DROP DATABASE` : sur un poste à deux serveurs, la commande que ce script
    # imprime détruisait le gabarit du voisin. On lit le port du DSN de
    # maintenance — la seule source qui sache où vit ce cerveau — et on
    # l'écrit dans la commande.
    _PORT="$(arac_dsn_port "$(arac_maintenance_dsn 2>/dev/null || true)")"
    if [ -n "$_PORT" ]; then
        _PSQL_SUPER="sudo -u postgres psql -p $_PORT -v ON_ERROR_STOP=1 -f -"
    else
        # On ne DEVINE pas 5432 : ce serait renommer l'ignorance en certitude,
        # et désigner précisément la grappe par défaut — celle qu'on cherche à
        # ne pas viser par accident.
        _PSQL_SUPER="sudo -u postgres psql -p <LE PORT DE VOTRE SERVEUR> -v ON_ERROR_STOP=1 -f -"
    fi
    cat <<EOF
-- ============================================================================
-- À exécuter UNE FOIS, en superutilisateur :
--
--     $_PSQL_SUPER <<'SQL'
--     ... (le bloc ci-dessous) ...
--     SQL
--
-- LE « -p » N'EST PAS DÉCORATIF. Sans lui, psql s'adresse à la grappe par
-- défaut de cette machine — et ce bloc commence par un DROP DATABASE.
--
-- CE BLOC NE DEVRAIT PLUS JAMAIS ÊTRE NÉCESSAIRE. Depuis que l'étape 4 du
-- bootstrap pose elle-même le gabarit et donne CREATEDB au rôle
-- d'administration, une installation neuve peut prouver ses sauvegardes sans
-- aucun geste de superutilisateur. Ce bloc RÉPARE les installations posées
-- avant — et rien d'autre. Il est idempotent.
--
-- Ce que cela fabrique : une base VIDE contenant les extensions dont le schéma
-- du cerveau a besoin, POSSÉDÉE par le rôle d'administration de ce cerveau.
-- Toute restauration de vérification la copiera au lieu de créer les
-- extensions — et n'aura donc plus jamais besoin du superutilisateur.
--
-- Pourquoi les extensions : pgvector n'est pas une extension « trusted » de
-- PostgreSQL. CREATE EXTENSION vector exige le superutilisateur, point final.
-- Le gabarit déplace ce privilège dans un geste d'installation, unique et lu,
-- au lieu d'un besoin permanent d'une tâche automatique.
--
-- Pourquoi CREATEDB : copier une base — gabarit ou non — exige cet attribut.
-- Sans lui, ce bloc s'exécute parfaitement et la vérification échoue quand
-- même, sur « permission denied to create database ». C'est très exactement
-- ce qui est arrivé : le gabarit était créé, la promesse restait intenable.
-- CREATEDB ne donne aucun droit sur une base existante, et la base vivante
-- appartient au superutilisateur : ce rôle ne peut pas la détruire.
--
-- Pourquoi PAS « datistemplate » : une base ainsi marquée est copiable par
-- TOUT rôle du serveur ayant CREATEDB — y compris celui du cerveau voisin —
-- et refuse d'être détruite tant qu'on ne l'a pas démarquée. La propriété
-- suffit, et n'étend rien à personne.
-- ============================================================================
-- LES SIX INSTRUCTIONS SONT ENGENDRÉES, PAS ÉCRITES — et c'est ce qui a
-- changé. Une seule l'était (le CREATE DATABASE), les cinq autres collaient le
-- nom du gabarit tel quel. Un mélange pareil est pire que rien : il donne à
-- lire une question traitée là où elle ne l'était qu'au sixième. La fonction
-- « format » cite ce qu'on lui donne : \`%I\` en IDENTIFIANT, \`%L\` en CHAÎNE ;
-- ni l'un ni l'autre ne peut être quitté. La deuxième protection est en amont : ce script refuse
-- désormais tout nom de gabarit qui n'est pas un identifiant banal, avant même
-- d'imprimer une ligne. Les deux sont indépendantes, exprès.
SELECT format('ALTER ROLE %I CREATEDB', '$_ROLE_ADMIN')\\gexec
-- CREATE DATABASE n'a pas d'« IF NOT EXISTS », et « DROP DATABASE IF EXISTS »
-- en tête de bloc — ce qui était écrit ici — détruit sans prévenir une base
-- que quelqu'un aurait remplie. On engendre donc la commande, et seulement si
-- elle manque : ce bloc peut être rejoué sans rien perdre.
SELECT format('CREATE DATABASE %I OWNER %I', '$TPL', '$_ROLE_ADMIN')
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$TPL')\\gexec
SELECT format('ALTER DATABASE %I OWNER TO %I', '$TPL', '$_ROLE_ADMIN')\\gexec
SELECT format('UPDATE pg_database SET datistemplate = false WHERE datname = %L', '$TPL')\\gexec
-- Le gabarit se ferme comme la base vivante. PostgreSQL donne CONNECT à
-- PUBLIC sur toute base neuve : sans ces deux lignes, le rôle du cerveau
-- VOISIN se connecte à ce gabarit avec son propre mot de passe. Il est vide,
-- donc rien n'en fuit — mais la base jetable qui en est COPIÉE, elle, porte
-- tout le cerveau, et une base ouverte à tous est une serrure de moins.
SELECT format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', '$TPL')\\gexec
SELECT format('GRANT  CONNECT ON DATABASE %I TO %I', '$TPL', '$_ROLE_ADMIN')\\gexec
-- « \\connect » est une commande de psql, pas du SQL : la fonction « format »
-- ne s'y applique pas. Elle prend en revanche un identifiant entre guillemets,
-- et le nom qui arrive ici a déjà été refusé s'il n'était pas banal.
\\connect "$TPL"
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
EOF
    exit 0
fi

arac_require psql
arac_require pg_restore

RC=0
WARNINGS=0


# ----------------------------------------------------------------------------
# 1. Choisir le dump — et savoir le déchiffrer si c'est tout ce qui reste
# ----------------------------------------------------------------------------

TMPDIR_SELF="$(mktemp -d "${TMPDIR:-/tmp}/arac-restauration.XXXXXX")"
chmod 0700 "$TMPDIR_SELF"

DUMP=''
if [ -n "$DUMP_ARG" ]; then
    DUMP="$DUMP_ARG"
    [ -r "$DUMP" ] || arac_die "Dump illisible : $DUMP"
else
    DUMP="$(arac_newest "$ARAC_BACKUP_DIR" "$ARAC_BACKUP_PREFIX-*.dump")"
fi

if [ -z "$DUMP" ]; then
    # Rien en clair : on tente le chiffré. C'est le chemin que suivra une
    # restauration réelle depuis la copie hors site — autant l'éprouver ici,
    # plutôt que de découvrir le jour J qu'on ne sait pas déchiffrer.
    CIPHER="$(arac_newest "$ARAC_BACKUP_DIR" "$ARAC_BACKUP_PREFIX-*.dump.age")"
    [ -n "$CIPHER" ] || arac_die \
"Aucun dump dans $ARAC_BACKUP_DIR.

Si la sauvegarde n'a jamais tourné, c'est normal — lancez-la :
    ops/backup.sh
Si elle tourne, c'est qu'elle écrit ailleurs : comparez ARAC_BACKUP_DIR ici et
dans l'unité de sauvegarde de CE cerveau. Ne devinez pas son nom, lisez-le :
    systemctl list-units --no-legend --all '${ARAC_UNIT_PREFIX:-arac-<votre-base>}-*' | grep -E 'sauvegarde|backup'
puis, sur celle qui sort :
    systemctl cat <l'unité> | grep BACKUP_DIR
Le nom de l'unité porte celui du cerveau — sur une machine qui en héberge
deux, interroger « celle de la sauvegarde » sans le préciser, c'est lire la
configuration du voisin. Il n'y a plus qu'un nom possible, et c'est le
bootstrap qui l'écrit : « ${ARAC_UNIT_PREFIX:-arac-<votre-base>}-sauvegarde.service ».
Ce message nommait « …-backup.service », rendu par la couche facultative
d'ops/systemd/ : deux familles d'unités appelaient le même script, avec deux
rétentions différentes. La seconde a été retirée."

    [ -n "${ARAC_BACKUP_IDENTITY:-}" ] || arac_die \
"Seuls des dumps CHIFFRÉS sont présents, et ARAC_BACKUP_IDENTITY n'est pas posée.

C'est le scénario que vous vouliez : la clé privée ne vit pas sur le serveur.
Pour vérifier une restauration ici, il faut donc soit garder un dump en clair
(ARAC_BACKUP_CLEAR_LOCAL=1, le défaut), soit rapatrier ce dump sur la machine
qui détient la clé et lancer ce script là-bas :
    ARAC_BACKUP_IDENTITY=~/arac-backup-${ARAC_BACKUP_PREFIX:-<votre_base>}.key \\
        ops/restore_verify.sh $CIPHER

Le nom de la clé porte celui du cerveau : une clé « ~/arac-backup.key »
serait la MÊME identité de déchiffrement pour tous les cerveaux restaurés
depuis ce poste — celui qui la détient lirait la mémoire de chacun d'eux."

    arac_require age
    DUMP="$TMPDIR_SELF/$(basename "${CIPHER%.age}")"
    age -d -i "$ARAC_BACKUP_IDENTITY" -o "$DUMP" "$CIPHER" \
        || arac_die "Déchiffrement impossible : $CIPHER (mauvaise identité ?)"
    arac_log "restore_verify.decrypted" "\"from\":\"$(basename "$CIPHER")\""
fi

DUMP_BYTES=$(stat -c %s "$DUMP")
DUMP_MTIME=$(stat -c %Y "$DUMP")
echo "→ dump examiné      : $DUMP ($DUMP_BYTES octets, $(date -u -d "@$DUMP_MTIME" +%FT%TZ))"


# ----------------------------------------------------------------------------
# 2. Choisir la base jetable — et refuser tout ce qui ressemble à la vivante
# ----------------------------------------------------------------------------

MAINT_DSN="$(arac_maintenance_dsn)" || arac_die \
"Aucun DSN de maintenance : impossible de créer une base jetable.

Posez DATABASE_URL_ADMIN dans \$ARAC_HOME/.env (le rôle des migrations), ou
ARAC_MAINTENANCE_DSN si votre base d'administration n'est pas 'postgres'.
Le rôle doit avoir CREATEDB — depuis cette version, le bootstrap le lui donne
à l'étape 3, et ce script imprime le nom RÉEL du rôle quand il manque."

#: Le rôle sous lequel on va tenter de créer la base jetable. On ne le fait pas
#: deviner : il est dans le DSN qu'on vient de composer.
ROLE_ADMIN="$(arac_dsn_user "$MAINT_DSN")"
[ -n "$ROLE_ADMIN" ] || ROLE_ADMIN="<votre rôle admin>"

LIVE_DB=''
if [ -n "${DATABASE_URL_ADMIN:-}" ]; then
    LIVE_DB="$(arac_dsn_db_name "$DATABASE_URL_ADMIN")"
fi

TARGET="${ARAC_RESTORE_DB:-${ARAC_BACKUP_PREFIX}_restore_$(date +%s)}"

#: TEMPLATE_DB est nommé ET REFUSÉ tout en haut de ce fichier, avec sa raison.
#: Il l'était ici, c'est-à-dire APRÈS la sortie de `--prepare-template` : le
#: seul chemin qui portait le nom jusqu'au superutilisateur était donc le seul
#: que le contrôle ne voyait jamais.

arac_db_name_safe "$TARGET" || arac_die \
"Nom de base jetable refusé : « $TARGET »
Seuls les identifiants PostgreSQL banals sont acceptés ([a-z_][a-z0-9_]{0,62}).
Ce nom finit interpolé dans un CREATE DATABASE : il n'y a pas de paramètre lié
pour cette instruction, donc pas d'autre protection que ce refus."

# LE GABARIT EST AUSSI UNE BASE QU'ON NE DÉTRUIT PAS.
#
# Le garde ne connaissait qu'UN nom interdit : la base vivante. Le gabarit de
# restauration, lui, appartient au rôle sous lequel ce script tourne — donc
# PostgreSQL, qui refuse à ce rôle de détruire la base du voisin, ne refusait
# rien ici. Une seule commande, sortie en erreur, l'effaçait, et la
# vérification de sauvegarde retombait aussitôt sur « permission denied to
# create extension "vector" ». Mesuré.
if arac_target_forbidden "$TARGET" "$LIVE_DB" "$TEMPLATE_DB"; then
    if [ "$TARGET" = "$TEMPLATE_DB" ]; then
        arac_die \
"REFUS : la cible « $TARGET » est le GABARIT de restauration de ce cerveau.

Ce n'est pas une base jetable : c'est la base vide, possédée par votre rôle
d'administration, que ce script COPIE pour ne pas avoir à créer pgvector — et
donc pour ne jamais réclamer le superutilisateur. La détruire ne casse pas le
cerveau, elle casse la PREUVE : « ops/restore_verify.sh » se remettrait à
échouer sur « permission denied to create extension \"vector\" ».

Une base jetable est une base que ce script CRÉE. Laissez-le la nommer."
    fi
    arac_die \
"REFUS : la cible « $TARGET » est la base VIVANTE de cette installation.

Une restauration de vérification ne vise JAMAIS la base vivante, quel que soit
l'argument reçu. Si vous vouliez vraiment restaurer par-dessus la production,
ce n'est pas ce script : lisez docs/SAUVEGARDE.md, section « la restauration
qu'on exécute en panique ». Elle est manuelle, et c'est délibéré."
fi

# REFUSER AVANT DE CRÉER, PAS APRÈS — et surtout avant d'armer le piège.
#
# CE QUE CE BLOC RÉPARE, ET C'ÉTAIT LE SCÉNARIO DE L'INCIDENT DANS L'OUTIL
# CENSÉ PROTÉGER LES DONNÉES. Le `trap cleanup EXIT` était armé AVANT la
# première tentative de création, et son corps est un `DROP DATABASE`. Il se
# déclenchait donc sur TOUS les chemins de sortie — y compris celui où le
# script sort précisément parce que la cible EXISTE DÉJÀ et n'a pas été créée
# par lui. Mesuré sur un banc : `ARAC_RESTORE_DB=<une base voisine>` faisait
# partir `DROP DATABASE IF EXISTS "<base voisine>"` contre le serveur (lu dans
# le journal PostgreSQL), et le message imprimé accusait le rôle de ne pas
# savoir copier le gabarit — alors que la vraie cause était « la cible existe
# déjà, et elle n'est pas à vous ».
#
# Deux protections, désormais, et elles sont indépendantes : celle-ci refuse
# AVANT, et le drapeau `CREEE_PAR_MOI` plus bas empêche le nettoyage de
# détruire ce que ce script n'a pas créé.
_DEJA="$(psql "$MAINT_DSN" -qtAc \
    "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = '$TARGET'" 2>/dev/null || true)"
if [ -n "$_DEJA" ]; then
    arac_die \
"REFUS : la base « $TARGET » existe déjà sur cette grappe, et elle appartient
à « $_DEJA ».

Une base jetable est une base que ce script CRÉE. Il ne réutilise pas celle de
quelqu'un d'autre, et il n'efface pas ce qu'il n'a pas posé — quel que soit le
nom qu'on lui passe dans ARAC_RESTORE_DB.

Si cette base est un reste d'une vérification interrompue, détruisez-la
vous-même, après avoir regardé ce qu'elle contient :
    psql \"\$(votre DSN d'administration)\" -c 'DROP DATABASE \"$TARGET\"'
Sinon, ne posez pas ARAC_RESTORE_DB : le nom horodaté que ce script choisit
tout seul (« ${ARAC_BACKUP_PREFIX}_restore_<horodatage> ») n'entre jamais en
collision."
fi

TARGET_DSN="$(arac_dsn_with_db "$MAINT_DSN" "$TARGET")"
echo "→ base jetable      : $TARGET (sur $(arac_dsn_redacted "$MAINT_DSN"))"
[ -n "$LIVE_DB" ] && echo "→ base vivante      : $LIVE_DB — jamais touchée par ce script"

#: ON NE DÉTRUIT QUE CE QU'ON A CRÉÉ. Ce drapeau ne passe à 1 qu'après un
#: `CREATE DATABASE` réussi. C'est la règle générale d'un piège de nettoyage,
#: et elle vaut deux lignes : sans elle, un `trap` armé trop tôt transforme
#: toute sortie en erreur en destruction d'une base qui n'est pas la sienne.
CREEE_PAR_MOI=0

#: Levé par la PREUVE D quand le dump ne porte pas l'empreinte de ce cerveau.
#: Déclaré ICI, et pas seulement là-bas, parce que `cleanup()` s'exécute sur
#: TOUS les chemins de sortie, y compris ceux qui n'ont jamais atteint la
#: PREUVE D. Sans cette ligne, `set -u` ferait mourir le piège de nettoyage.
IDENTITE_KO=0

cleanup() {
    if [ "$CREEE_PAR_MOI" -ne 1 ]; then
        # Rien à détruire : ce script n'a créé aucune base pendant ce passage.
        rm -rf "$TMPDIR_SELF"
        return
    fi
    # `--keep` EST UN CONFORT, PAS UN DROIT DE GARDE.
    #
    # Ce script sait désormais dire qu'un dump ne vient pas de ce cerveau
    # (PREUVE D). Il l'apprend forcément APRÈS avoir restauré — c'est en
    # restaurant qu'on lit l'empreinte. Mais alors la base jetable porte
    # l'INTÉGRALITÉ de la mémoire d'un AUTRE cerveau, et elle appartient au
    # rôle d'administration de CELUI-CI : aucun REVOKE ne ferme une base à son
    # propriétaire. La garder « pour regarder » revient à conserver en clair,
    # sur son disque et sous son propre rôle, une mémoire qu'on n'a pas le
    # droit de lire. On ne la garde donc pas, et on dit pourquoi.
    if [ "$KEEP" -eq 1 ] && [ "$IDENTITE_KO" -ne 1 ]; then
        echo "→ base jetable CONSERVÉE (--keep) : $TARGET — pensez à la détruire."
    else
        [ "$KEEP" -eq 1 ] && [ "$IDENTITE_KO" -eq 1 ] && echo \
"→ base jetable DÉTRUITE MALGRÉ --keep : elle porte la mémoire d'un AUTRE
  cerveau, et elle vous appartenait. On ne garde pas ce qu'on n'a pas le droit
  de lire. Le dump, lui, n'a pas été touché : il est toujours là où il était."
        psql "$MAINT_DSN" -v ON_ERROR_STOP=0 -qtAc \
            "DROP DATABASE IF EXISTS \"$TARGET\";" >/dev/null 2>&1 || true
    fi
    rm -rf "$TMPDIR_SELF"
}
trap cleanup EXIT


# ----------------------------------------------------------------------------
# 3. Restaurer
# ----------------------------------------------------------------------------

# LE GABARIT — la façon de restaurer sans être superutilisateur
#
# Le schéma du cerveau emploie des types fournis par pgvector (halfvec, 3072
# dimensions) et pg_trgm. Sans ces extensions, pg_restore échoue sur la première
# table qui les utilise, et son message parle d'un « type inconnu » — pas d'une
# extension manquante. C'est la panne de restauration la plus fréquente et la
# plus mal diagnostiquée.
#
# Et voici le piège que ce dépôt a rencontré en éprouvant ce script, sur un
# PostgreSQL 16 nu : **`CREATE EXTENSION vector` exige le superutilisateur.**
# pgvector n'est pas une extension « trusted ». Faire tourner la vérification
# hebdomadaire en superutilisateur pour cette seule raison serait absurde.
#
# La sortie est un GABARIT, posé par l'étape 4 du bootstrap depuis cette
# version — et réparable à la main sur une installation plus ancienne :
#
#     ops/restore_verify.sh --prepare-template     (imprime le SQL à exécuter)
#
# Une base peut être copiée sans superutilisateur par un rôle qui a CREATEDB
# et qui la POSSÈDE (ou, forme héritée, si elle est marquée `datistemplate`).
# La vérification n'a alors plus besoin d'aucun privilège élevé : elle copie un
# gabarit qui contient déjà les extensions.
#
# LES DEUX CONDITIONS SONT NÉCESSAIRES, ET C'EST TOUT LE DÉFAUT QU'ON RÉPARE :
# le gabarit seul ne suffit pas. Copier une base — gabarit ou non — exige
# CREATEDB. Le dépôt donnait le gabarit et pas l'attribut ; le lecteur qui
# suivait la documentation à la lettre voyait le même refus qu'avant, cette
# fois SANS aucun geste imprimé pour en sortir.
# TEMPLATE_DB est nommé plus haut, avec le garde qui l'interdit comme cible.
HAS_TEMPLATE="$(psql "$MAINT_DSN" -qtAc \
    "SELECT count(*) FROM pg_database WHERE datname = '$TEMPLATE_DB'" 2>/dev/null || echo 0)"

#: Le remède, une fois pour les deux branches — avec le VRAI nom du rôle.
_remede_createdb() {
    cat <<REMEDE
Deux causes possibles, et le script ne peut pas les distinguer de l'extérieur :

  1. le rôle « $ROLE_ADMIN » n'a pas l'attribut CREATEDB ;
  2. le gabarit existe mais ce rôle ne peut pas le copier (il ne le possède
     pas, et il n'est pas marqué comme gabarit).

Le geste qui règle les deux, en superutilisateur, une seule fois :

    ops/restore_verify.sh --prepare-template

Il imprime le SQL — lisez-le avant de le passer, il est court. Pour vérifier
d'abord ce qui manque :

    sudo -u postgres psql -p ${_PORT_MAINT:-<port>} -tAc \\
      "SELECT rolcreatedb FROM pg_roles WHERE rolname='$ROLE_ADMIN'"

Depuis cette version, le bootstrap pose les deux à l'installation (étape 3
pour l'attribut, étape 4 pour le gabarit) : un cerveau neuf n'a rien à faire.
REMEDE
}
_PORT_MAINT="$(arac_dsn_port "$MAINT_DSN")"

# UNE BASE QUI PORTE TOUT LE CERVEAU N'EST PAS PLUS OUVERTE QUE LE CERVEAU.
#
# PostgreSQL donne CONNECT à PUBLIC sur toute base neuve, et
# `CREATE DATABASE … TEMPLATE …` ne recopie PAS les privilèges du gabarit. La
# base jetable naissait donc ouverte à tous les rôles du serveur — et elle
# contient, le temps de la vérification, l'INTÉGRALITÉ du cerveau restauré.
# Le contenu des tables tenait (le schéma n'accorde USAGE qu'aux rôles de ce
# cerveau), mais le voisin s'y connectait et lisait le catalogue : noms de
# tables, colonnes, et surtout VOLUMÉTRIE de la mémoire d'à côté. Il pouvait
# même y créer des tables temporaires, donc écrire dans une base qui n'est pas
# la sienne.
#
# Le dépôt sait faire ce geste : `bootstrap/lib/database.sh` le fait sur la
# base vivante. On le refait ici, pour les deux branches de création.
_fermer_a_public() {
    psql "$MAINT_DSN" -v ON_ERROR_STOP=1 -qtAc \
        "REVOKE CONNECT ON DATABASE \"$TARGET\" FROM PUBLIC;" >/dev/null 2>&1 \
        || arac_warn "⚠ REVOKE CONNECT sur « $TARGET » a échoué : cette base reste
  connectable par tout rôle de la grappe pendant la vérification."
    # Le rôle qui vient de créer la base en est propriétaire : il garde
    # CONNECT de droit. On le nomme quand même, pour que la révocation
    # ci-dessus ne puisse jamais se retourner contre celui qui la pose.
    psql "$MAINT_DSN" -v ON_ERROR_STOP=1 -qtAc \
        "GRANT CONNECT ON DATABASE \"$TARGET\" TO \"$ROLE_ADMIN\";" >/dev/null 2>&1 || true
}

if [ "${HAS_TEMPLATE:-0}" = "1" ]; then
    if ! psql "$MAINT_DSN" -v ON_ERROR_STOP=1 -qtAc \
        "CREATE DATABASE \"$TARGET\" TEMPLATE \"$TEMPLATE_DB\";" >/dev/null; then
        arac_die "CREATE DATABASE ... TEMPLATE $TEMPLATE_DB a échoué.

$(_remede_createdb)"
    fi
    CREEE_PAR_MOI=1
    _fermer_a_public
    echo "→ extensions        : héritées du gabarit $TEMPLATE_DB (aucun privilège élevé requis)"
    echo "→ base jetable      : fermée à PUBLIC (REVOKE CONNECT) — elle porte tout le cerveau"
else
    psql "$MAINT_DSN" -v ON_ERROR_STOP=1 -qtAc "CREATE DATABASE \"$TARGET\";" >/dev/null \
        || arac_die "CREATE DATABASE a échoué : le rôle « $ROLE_ADMIN » n'a pas pu créer la base jetable.

$(_remede_createdb)"
    CREEE_PAR_MOI=1
    _fermer_a_public
    echo "→ base jetable      : fermée à PUBLIC (REVOKE CONNECT) — elle porte tout le cerveau"

    for ext in vector pg_trgm; do
        if psql "$TARGET_DSN" -v ON_ERROR_STOP=1 -qtAc \
               "CREATE EXTENSION IF NOT EXISTS $ext;" >/dev/null 2>"$TMPDIR_SELF/ext.err"; then
            continue
        fi
        # Distinguer les deux pannes, parce qu'elles n'ont pas le même remède.
        AVAIL="$(psql "$MAINT_DSN" -qtAc \
            "SELECT count(*) FROM pg_available_extensions WHERE name='$ext'" 2>/dev/null || echo 0)"
        echo "" >&2
        if [ "${AVAIL:-0}" = "0" ]; then
            echo "ÉCHEC : l'extension « $ext » n'est pas installée sur ce serveur PostgreSQL." >&2
            echo "        Aucune restauration de ce cerveau n'est possible ici." >&2
            echo "        sudo apt install postgresql-16-pgvector    (adaptez la version majeure)" >&2
        else
            echo "ÉCHEC : « $ext » est disponible, mais ce rôle n'a pas le droit de la créer." >&2
            sed 's/^/        /' "$TMPDIR_SELF/ext.err" >&2
            echo "" >&2
            echo "        C'est le cas NORMAL : pgvector n'est pas une extension « trusted »," >&2
            echo "        sa création exige le superutilisateur. Ne donnez pas ce pouvoir à la" >&2
            echo "        vérification hebdomadaire — préparez un gabarit, une fois pour toutes :" >&2
            echo "" >&2
            echo "            ops/restore_verify.sh --prepare-template" >&2
        fi
        exit 1
    done
fi

# --no-owner --no-privileges : la base jetable n'a pas les rôles du cerveau, et
# on ne veut pas qu'elle les exige. C'est aussi ce qu'on fera sur une machine
# neuve après un désastre, avant d'avoir recréé les rôles — autant vérifier ce
# chemin-là, pas un autre.
#
# LE SOMMAIRE FILTRÉ — LA CEINTURE, POUR LES DUMPS QUI NE VIENNENT PAS D'ICI
#
# Un dump pris sur la base ENTIÈRE (`pg_dump -Fc` sans `--schema`) porte deux
# entrées `COMMENT - EXTENSION` : vector et pg_trgm. `COMMENT ON EXTENSION`
# exige d'être PROPRIÉTAIRE de l'extension, et les extensions du gabarit
# appartiennent au superutilisateur — pgvector n'est pas « trusted », ce dépôt
# l'écrit en toutes lettres. `pg_restore` rendait donc 2 erreurs, sortait en 1,
# et ce script criait « le dump ne se restaure pas. Le coffre est vide. » sur
# une sauvegarde parfaitement restaurable. C'est la pire direction pour un faux
# verdict : celui qui répare une sauvegarde saine touche à la seule copie
# qu'il a.
#
# L'unité de sauvegarde ne produit plus de tels dumps (elle appelle
# `ops/backup.sh`, qui dumpe `--schema`). Mais un cerveau déjà installé garde
# les dumps de l'ancienne forme pendant toute sa rétention, et une restauration
# d'urgence peut partir d'un dump venu d'ailleurs. On retire donc ces entrées
# du SOMMAIRE avant de restaurer : le commentaire d'une extension n'est pas une
# donnée du cerveau, le perdre ne perd rien.
RESTORE_LOG="$TMPDIR_SELF/pg_restore.log"
TOC_LIST="$TMPDIR_SELF/toc.list"
RESTORE_ARGS=()
if pg_restore -l "$DUMP" > "$TMPDIR_SELF/toc.full" 2>"$TMPDIR_SELF/toc.err"; then
    grep -v 'COMMENT - EXTENSION' "$TMPDIR_SELF/toc.full" > "$TOC_LIST" || true
    RETIREES=$(( $(wc -l < "$TMPDIR_SELF/toc.full") - $(wc -l < "$TOC_LIST") ))
    if [ "$RETIREES" -gt 0 ]; then
        echo "→ sommaire          : $RETIREES entrée(s) « COMMENT - EXTENSION » écartée(s) — ce rôle n'est pas propriétaire des extensions, et un commentaire n'est pas une donnée"
    fi
    RESTORE_ARGS=(-L "$TOC_LIST")
else
    # Le sommaire est illisible : c'est un vrai symptôme (fichier tronqué,
    # version de pg_restore trop ancienne). On ne le masque pas, on le dit et
    # on tente quand même la restauration — c'est elle qui tranchera.
    arac_warn "⚠ pg_restore --list a échoué sur ce dump : restauration tentée sans sommaire filtré."
    sed 's/^/  /' "$TMPDIR_SELF/toc.err" >&2
fi

if ! pg_restore --dbname="$TARGET_DSN" --no-owner --no-privileges \
        "${RESTORE_ARGS[@]}" "$DUMP" >"$RESTORE_LOG" 2>&1; then
    # « pg_restore a signalé quelque chose » N'EST PAS « le coffre est vide ».
    #
    # On lit notre propre journal avant de conclure. Les erreurs qui ne
    # touchent AUCUN objet du schéma du cerveau — propriété d'extension,
    # commentaire d'extension, appartenance d'un objet à un rôle absent — ne
    # disent rien sur le contenu restauré. Ce sont les preuves A, B et C qui
    # tranchent, et elles sont plus bas. Toute autre erreur, elle, reste un
    # échec franc : un contrôle qui crie « le coffre est vide » doit avoir
    # CONSTATÉ qu'il est vide.
    BENIGNES='must be owner of extension|COMMENT ON EXTENSION|role "[^"]*" does not exist'
    TOTAL_ERR="$(grep -cE '^pg_restore: error:' "$RESTORE_LOG" || true)"
    AUTRES_ERR="$(grep -E '^pg_restore: error:' "$RESTORE_LOG" \
                  | grep -vcE "$BENIGNES" || true)"
    # Une erreur porte parfois son motif sur la ligne SUIVANTE (« Command was:
    # COMMENT ON EXTENSION … »). On regarde donc aussi le journal entier :
    # si aucun `COMMENT ON EXTENSION` n'y figure, les lignes non classées le
    # restent, et l'échec est franc.
    if [ "${TOTAL_ERR:-0}" -gt 0 ] && [ "${AUTRES_ERR:-0}" -eq 0 ]; then
        echo "→ restauration      : pg_restore a signalé $TOTAL_ERR objet(s) hors du cerveau (extensions), et RIEN d'autre" >&2
        grep -E '^pg_restore: error:' "$RESTORE_LOG" | sed 's/^/    /' >&2
        echo "  ~ ces objets appartiennent au superutilisateur PostgreSQL : ce rôle ne peut pas les reposer, et ils ne portent AUCUNE donnée du cerveau. Verdict au mieux PARTIEL (code 2)." >&2
        RC=$(( RC == 0 ? 2 : RC ))
        WARNINGS=$(( WARNINGS + 1 ))
    else
        echo "ÉCHEC : pg_restore a rendu une erreur. Dernières lignes :" >&2
        tail -20 "$RESTORE_LOG" >&2
        arac_alert critical "RESTAURATION : le dump $(basename "$DUMP") ne se restaure pas. Le coffre est vide."
        exit 1
    fi
else
    echo "→ restauration      : pg_restore terminé sans erreur"
fi


# ----------------------------------------------------------------------------
# 4. La preuve — ce qui distingue « ça a tourné » de « le contenu est là »
# ----------------------------------------------------------------------------

q()      { psql "$TARGET_DSN" -qtAc "$1" 2>/dev/null; }
q_live() { psql "$LIVE_DSN"   -qtAc "$1" 2>/dev/null; }

fail()  { echo "  ✗ $1" >&2; RC=1; }
pass()  { echo "  ✓ $1"; }
warn()  { echo "  ~ $1"; WARNINGS=$(( WARNINGS + 1 )); }

echo ""
echo "PREUVE A — les tables vitales existent dans la base restaurée"
for t in "${REQUIRED[@]}"; do
    n="$(q "SELECT to_regclass('$ARAC_DB_SCHEMA.$t') IS NOT NULL")"
    if [ "$n" = "t" ]; then pass "$ARAC_DB_SCHEMA.$t"; else fail "$ARAC_DB_SCHEMA.$t ABSENTE"; fi
done

echo ""
echo "PREUVE B — le contenu est lisible, pas seulement présent"
# Compter prouve que les lignes existent. Les LIRE prouve qu'elles se décodent —
# y compris la colonne d'embedding, qui est le seul endroit où une extension
# manquante ou une version de pgvector décalée se manifeste vraiment.
ATOMS="$(q "SELECT count(*) FROM $ARAC_DB_SCHEMA.memory_atoms")"
CONVS="$(q "SELECT count(*) FROM $ARAC_DB_SCHEMA.conversations")"
MSGS="$(q "SELECT count(*) FROM $ARAC_DB_SCHEMA.raw_messages")"
NODES="$(q "SELECT count(*) FROM $ARAC_DB_SCHEMA.nodes")"
SCOPES="$(q "SELECT count(*) FROM $ARAC_DB_SCHEMA.scopes")"
SCHEMA_REV="$(q "SELECT version_num FROM $ARAC_DB_SCHEMA.alembic_version LIMIT 1")"
printf '  atomes=%s  conversations=%s  messages=%s  nœuds=%s  scopes=%s\n' \
    "${ATOMS:-?}" "${CONVS:-?}" "${MSGS:-?}" "${NODES:-?}" "${SCOPES:-?}"
printf '  version de schéma restaurée : %s\n' "${SCHEMA_REV:-ABSENTE}"

# Un cerveau restauré sans identité ni taxonomie n'est pas un cerveau : ces deux
# tables sont peuplées par l'installation elle-même, avant le premier atome.
# Elles sont donc les seules dont on exige un contenu, toujours.
[ "${NODES:-0}" -gt 0 ]  && pass "des nœuds sont déclarés"    || fail "aucun nœud : le cerveau restauré refuserait toute conversation"
[ "${SCOPES:-0}" -gt 0 ] && pass "la taxonomie est là"        || fail "aucun scope : les atomes restaurés n'auraient plus d'adresse"
[ -n "${SCHEMA_REV:-}" ] && pass "la version de schéma voyage avec les données" \
                         || fail "alembic_version vide : impossible de savoir quel code sait lire ces données"

if [ "${ATOMS:-0}" -gt 0 ]; then
    # ------------------------------------------------------------------------
    # CE BLOC ÉCRIVAIT LA MÉMOIRE DANS LE JOURNAL SYSTÈME, ET ELLE Y RESTAIT
    # APRÈS LA DÉSINSTALLATION.
    #
    # Ce script est l'`ExecStart` de `arac-<base>-restauration.service` : tout
    # ce qu'il imprime part dans journald, un magasin PARTAGÉ par la machine
    # entière, lisible par tout compte du groupe `systemd-journal`, conservé
    # des semaines. Il imprimait ici la CLÉ et le DOMAINE de trois souvenirs,
    # en clair. Le §13 efface la base, les rôles, le coffre, les dossiers et
    # les dumps — il ne peut rien contre journald, qui ne sait pas effacer les
    # entrées d'UNE unité (`--vacuum-*` travaille sur des FICHIERS, et ces
    # fichiers portent aussi le journal du voisin). Résultat mesuré : après un
    # §13 joué mot pour mot et un « VERDICT : PROPRE » en code 0,
    # `journalctl -u arac-<base>-restauration` rendait encore
    # « · penicilline [perso/sante] ». Personne ne pense à chercher sa mémoire
    # dans un journal système ; c'est ce qui a rendu cette fuite invisible à
    # tous les contrôles pendant tout le chantier.
    #
    # LE DÉPÔT AVAIT DÉJÀ ÉCRIT LA RÈGLE — ailleurs. `dedup_thresholds.key_sha8`
    # (invariant I5 / règle V0.107) : « une clé d'atome n'est PAS garantie sans
    # PII […] aucune clé ne doit être écrite en clair dans un artefact durable ;
    # sha8 suffit pour corréler deux occurrences sans rien révéler ». Et
    # `dispose._sanitize_error_body` nomme même le destinataire à protéger :
    # « le candidat complet reste disponible pour la revue humaine via la DB,
    # accès contrôlé, JAMAIS via journald ». Ce bloc-ci était le seul endroit du
    # produit qui envoyait la mémoire elle-même à journald.
    #
    # CE QU'IL FAUT PROUVER, ET CE QU'IL SUFFIT D'ÉCRIRE POUR LE PROUVER.
    # La preuve B ne demande pas « qu'y a-t-il dans votre mémoire ? » — elle
    # demande « ces lignes se DÉCODENT-elles ? ». Une empreinte répond : pour
    # la calculer il a fallu lire la colonne, la décoder en UTF-8 et la hacher.
    # Deux passages sur le même dump rendent les mêmes empreintes, ce qui suffit
    # à reconnaître un dump ; aucun ne rend un mot de la mémoire.
    #
    # L'empreinte est celle du reste du produit — `sha256(clé)[:8]`, au caractère
    # près `key_sha8()` — pour qu'une ligne du journal du cycle et une ligne
    # d'ici se rapprochent quand elles parlent du même souvenir.
    #
    # La preuve est au passage plus FORTE qu'avant : `value`, la colonne qui
    # porte réellement le souvenir, n'était jamais lue — on la lit maintenant
    # (sa longueur), sans en écrire un caractère.
    # ------------------------------------------------------------------------
    echo "  échantillon d'atomes réellement relus (empreintes : la mémoire ne sort pas d'ici) :"
    q "SELECT '    · clé ' || substr(encode(sha256(convert_to(coalesce(key,''), 'UTF8')), 'hex'), 1, 8)
              || '  domaine ' || substr(encode(sha256(convert_to(coalesce(scope,''), 'UTF8')), 'hex'), 1, 8)
              || '  ' || to_char(created_at,'YYYY-MM-DD')
              || '  (' || length(coalesce(key,'')) || ' + ' || length(coalesce(value,'')) || ' caractères décodés)'
         FROM $ARAC_DB_SCHEMA.memory_atoms ORDER BY created_at DESC LIMIT 3"
    EMB="$(q "SELECT count(*) FROM $ARAC_DB_SCHEMA.memory_atoms WHERE embedding IS NOT NULL")"
    if [ "${EMB:-0}" -gt 0 ]; then
        DIMS="$(q "SELECT vector_dims(embedding::vector) FROM $ARAC_DB_SCHEMA.memory_atoms WHERE embedding IS NOT NULL LIMIT 1")"
        pass "$EMB embeddings relus, ${DIMS:-?} dimensions — les vecteurs ont survécu au trajet"
    else
        warn "aucun embedding en base : le rappel sémantique serait muet après restauration"
    fi
else
    warn "aucun atome dans le dump — normal sur un cerveau qui n'a pas encore digéré, anormal sinon"
fi


# ----------------------------------------------------------------------------
# 5. L'IDENTITÉ, puis la comparaison avec le cerveau vivant
# ----------------------------------------------------------------------------
#
# Dans cet ordre, et l'ordre est le raisonnement : « est-ce MA mémoire ? »
# avant « est-elle À JOUR ? ». Comparer la fraîcheur d'un dump qui vient
# d'ailleurs, c'est mesurer soigneusement la mauvaise chose. Les lettres
# suivent donc la lecture (A, B, D, C), pas la chronologie du fichier.

LIVE_DSN="$(arac_readonly_dsn)"

# ----------------------------------------------------------------------------
# PREUVE D — DE QUEL CERVEAU CE DUMP VIENT-IL ?
# ----------------------------------------------------------------------------
#
# Ce script savait dire qu'un dump SE RESTAURE. Il ne savait pas dire DE QUI il
# vient, et il concluait quand même « PROUVÉ ». Sur une machine à plusieurs
# cerveaux — le cas que tout ce dépôt travaille —, restaurer le dump du voisin
# et le déclarer prouvé est exactement la classe d'erreur qu'on combat : on
# range une preuve verte à côté d'une mémoire qui n'est pas la sienne.
#
# L'IDENTITÉ EST PORTÉE PAR LE DUMP, PAS PAR SON NOM DE FICHIER.
#
# Un nom de fichier se recopie, se renomme, se ramasse dans le mauvais
# répertoire un jour de panique — c'est le geste que `docs/SAUVEGARDE.md`
# décrit lui-même comme le piège du pire jour (« le mauvais moment pour choisir
# un fichier dans une liste où tous les noms se ressemblent »). L'empreinte
# d'installation, elle, est gravée par le bootstrap dans le COMMENTAIRE DU
# SCHÉMA, et `pg_dump --schema=…` l'emporte avec les tables. On la lit donc
# dans la base RESTAURÉE : elle a fait le voyage à l'intérieur du fichier.
#
# Les rôles PostgreSQL portent la même empreinte, mais ils sont globaux à la
# grappe : ils ne sont pas dans le dump. C'est précisément pour cela qu'ils ne
# pouvaient pas servir ici.
echo ""
echo "PREUVE D — ce dump vient-il de CE cerveau ?"

MARQUE_R="$(q "SELECT coalesce(obj_description(to_regnamespace('$ARAC_DB_SCHEMA'), 'pg_namespace'), '')")"
_champ() { printf '%s' "$MARQUE_R" | sed -n "s/.*\\b$1=\\([^ ]*\\).*/\\1/p"; }
DUMP_UUID="$(_champ empreinte)"
DUMP_BASE="$(_champ cerveau)"
DUMP_POSTE="$(_champ poste)"
MOI_UUID="${ARAC_INSTALL_UUID:-}"
MOI_POSTE="${ARAC_NODE_ID:-}"

#: Il vaut déjà 0 — il est déclaré près de `cleanup()`, qui le lit sur tous les
#: chemins de sortie. On ne le réinitialise pas ici : ce serait effacer, à la
#: relecture, la seule chose qui rattache ce contrôle au nettoyage.
if [ -n "$DUMP_UUID" ] && [ -n "$MOI_UUID" ]; then
    if [ "$DUMP_UUID" = "$MOI_UUID" ]; then
        pass "empreinte d'installation identique — ce dump est bien celui de « ${DUMP_BASE:-?} »"
        if [ -n "$DUMP_BASE" ] && [ -n "${ARAC_DB:-}" ] && [ "$DUMP_BASE" != "$ARAC_DB" ]; then
            warn "le dump se nomme « $DUMP_BASE » et cette installation « $ARAC_DB » — même empreinte, donc même cerveau renommé. Ce n'est pas une erreur, c'est une chose à savoir avant de basculer."
        fi
    else
        IDENTITE_KO=1
        fail "CE DUMP N'EST PAS LE VÔTRE.
       empreinte dans le dump : $DUMP_UUID   (cerveau « ${DUMP_BASE:-?} », poste « ${DUMP_POSTE:-?} »)
       empreinte de ce cerveau : $MOI_UUID   (cerveau « ${ARAC_DB:-?} »)
       Une empreinte n'est choisie par personne : deux cerveaux ne peuvent pas
       porter la même. Restaurer ce fichier ici remplacerait votre mémoire par
       celle d'une autre installation. Reprenez le dump dans le sous-dossier de
       VOTRE cerveau : $ARAC_BACKUP_DIR"
    fi
elif [ -n "$MOI_POSTE" ] && [ -n "$(q "SELECT 1 FROM $ARAC_DB_SCHEMA.nodes LIMIT 1")" ]; then
    # LE REPLI, POUR LES DUMPS D'AVANT L'EMPREINTE. Un dump pris par une
    # version antérieure ne porte pas de commentaire de schéma : on retombe
    # alors sur la seule identité qui ait toujours voyagé avec les données, le
    # poste déclaré à l'installation. Elle est plus faible (un nom, pas une
    # empreinte) et on le DIT.
    _n_poste="$(q "SELECT count(*) FROM $ARAC_DB_SCHEMA.nodes WHERE node_id = '$MOI_POSTE'")"
    if [ "${_n_poste:-0}" -gt 0 ]; then
        warn "ce dump ne porte pas d'empreinte d'installation (pris avant cette version). Repli : il déclare bien le poste « $MOI_POSTE ». Le prochain dump portera l'empreinte."
        RC=$(( RC == 0 ? 2 : RC ))
    else
        IDENTITE_KO=1
        fail "ce dump ne porte pas d'empreinte, et il ne connaît pas votre poste « $MOI_POSTE ».
       Postes déclarés dans le dump : $(q "SELECT string_agg(node_id, ', ' ORDER BY node_id) FROM $ARAC_DB_SCHEMA.nodes")
       Rien ici ne dit qu'il s'agit de votre cerveau."
    fi
else
    warn "identité NON VÉRIFIÉE : ni empreinte dans le dump, ni poste connu de ce côté. Ce contrôle ne peut pas dire de quel cerveau ce fichier vient."
    RC=$(( RC == 0 ? 2 : RC ))
fi

echo ""
echo "PREUVE C — la sauvegarde décrit bien le cerveau d'aujourd'hui"

# LE JOUR OÙ CE CONTRÔLE SERT LE PLUS EST CELUI OÙ LA BASE VIVANTE EST MORTE.
#
# `docs/SAUVEGARDE.md` §7 fait de ce script la PREMIÈRE étape de la
# restauration réelle : « choisir le dump, et le prouver AVANT de s'en
# servir ». À cette minute-là, la base vivante est abîmée — c'est pour cela
# qu'on est là. Or la comparaison ci-dessous lisait `${L_ATOMS:-0}` : une
# mesure IMPOSSIBLE devenait une mesure à ZÉRO, et le script rendait « le dump
# contient plus d'atomes que la base vivante — ce dump ne vient pas d'ici »,
# puis « ÉCHEC — ce dump n'est pas une sauvegarde utilisable ». La page dit
# alors : « prenez le dump précédent et recommencez ». Tous échouent de la même
# façon. Mesuré : cerveau réel, schéma détruit, dump parfaitement bon.
#
# C'est la pire direction possible pour un faux verdict, et ce fichier l'écrit
# lui-même trente lignes plus haut : « celui qui répare une sauvegarde saine
# touche à la seule copie qu'il a. »
#
# On distingue donc trois états, au lieu de deux : la base vivante répond et se
# lit · elle répond mais ne se lit plus · elle ne répond pas. Seul le premier
# autorise une comparaison ; les deux autres ne disent RIEN sur le dump.
L_ATOMS=''; L_MSGS=''
if [ -n "$LIVE_DSN" ] && q_live "SELECT 1" >/dev/null; then
    L_ATOMS="$(q_live "SELECT count(*) FROM $ARAC_DB_SCHEMA.memory_atoms")"
    L_MSGS="$(q_live "SELECT count(*) FROM $ARAC_DB_SCHEMA.raw_messages")"
fi

if [ -z "$LIVE_DSN" ] || ! q_live "SELECT 1" >/dev/null; then
    warn "base vivante injoignable (DATABASE_URL_READONLY) — comparaison impossible"
    warn "la restauration est prouvée, sa FRAÎCHEUR ne l'est pas : code de sortie 2"
    RC=$(( RC == 0 ? 2 : RC ))
elif [ -z "$L_ATOMS" ]; then
    warn "la base vivante RÉPOND mais ne se laisse plus lire ($ARAC_DB_SCHEMA.memory_atoms) :
       schéma absent, ou droits perdus. C'est l'état d'un cerveau ABÎMÉ — donc,
       très probablement, la raison pour laquelle vous lisez cet écran."
    warn "ce n'est PAS un défaut du dump : rien ici ne permet de le comparer à un
       cerveau qui ne répond plus. Le dump se restaure et son contenu est là
       (preuves A, B et D ci-dessus) — c'est ce qu'on vous demandait de vérifier
       avant de basculer. Code de sortie 2, et non 1."
    RC=$(( RC == 0 ? 2 : RC ))
else
    printf '  vivant : atomes=%s messages=%s   |   restauré : atomes=%s messages=%s\n' \
        "${L_ATOMS:-?}" "${L_MSGS:-?}" "${ATOMS:-?}" "${MSGS:-?}"

    # Un dump ne peut pas contenir PLUS que la base au moment où il a été pris.
    # S'il en contient davantage, c'est qu'il vient d'ailleurs — d'une autre
    # installation, ou d'un avant qu'on a perdu. Dans les deux cas, ce n'est pas
    # la sauvegarde de CE cerveau.
    if [ "${ATOMS:-0}" -gt "${L_ATOMS:-0}" ]; then
        fail "le dump contient plus d'atomes que la base vivante — ce dump ne vient pas d'ici"
    else
        pass "les volumes restaurés sont cohérents avec la base vivante"
    fi

    # Comparaison d'identité, pas seulement de nombre : deux bases peuvent avoir
    # le même compte et pas les mêmes lignes. On compare l'empreinte de la liste
    # ordonnée des identifiants d'atomes antérieurs à l'horizon du dump. Un
    # atome supersédé change de statut, jamais d'identifiant : l'empreinte
    # résiste donc à la digestion qui a continué après le dump.
    HORIZON="$(q "SELECT coalesce(max(created_at)::text,'') FROM $ARAC_DB_SCHEMA.memory_atoms")"
    if [ -n "$HORIZON" ]; then
        SUM_R="$(q "SELECT md5(coalesce(string_agg(id::text, ',' ORDER BY id),'')) FROM $ARAC_DB_SCHEMA.memory_atoms WHERE created_at <= '$HORIZON'")"
        SUM_L="$(q_live "SELECT md5(coalesce(string_agg(id::text, ',' ORDER BY id),'')) FROM $ARAC_DB_SCHEMA.memory_atoms WHERE created_at <= '$HORIZON'")"
        if [ -n "$SUM_R" ] && [ "$SUM_R" = "$SUM_L" ]; then
            pass "empreinte des atomes identique de part et d'autre ($SUM_R)"
        else
            fail "empreinte divergente : restauré=$SUM_R vivant=$SUM_L — le dump ne contient pas les mêmes atomes"
        fi
    fi

    # Fraîcheur : l'écart entre le dernier message du dump et celui du vivant.
    # Deux requêtes séparées, jamais imbriquées : une requête qui en contient
    # une autre est une requête qu'on ne peut pas rejouer à la main.
    R_LAST="$(q      "SELECT coalesce(max(received_at)::text,'') FROM $ARAC_DB_SCHEMA.raw_messages")"
    L_LAST="$(q_live "SELECT coalesce(max(received_at)::text,'') FROM $ARAC_DB_SCHEMA.raw_messages")"
    if [ -z "$R_LAST" ] || [ -z "$L_LAST" ]; then
        warn "fraîcheur non mesurable (aucun message d'un côté ou de l'autre)"
    else
        GAP_H=$(( ( $(date -d "$L_LAST" +%s) - $(date -d "$R_LAST" +%s) ) / 3600 ))
        if [ "$GAP_H" -gt "$FRESHNESS_H" ]; then
            fail "le dump a $GAP_H h de retard sur la base vivante (> $FRESHNESS_H h) — la sauvegarde a cessé de suivre le cerveau"
        else
            pass "retard du dump sur le vivant : $GAP_H h (toléré : $FRESHNESS_H h)"
        fi
    fi
fi


# ----------------------------------------------------------------------------
# 6. Le garde anti-écrasement de la référence
# ----------------------------------------------------------------------------
#
# On ne promeut pas en « dernier bon connu » un dump qui a maigri de moitié
# sans explication : c'est ainsi qu'un coffre plein se fait remplacer par un
# coffre vide, silencieusement, un dimanche.

KNOWN_GOOD_FILE="$ARAC_BACKUP_STATE/known_good_messages"
if [ "$RC" -ne 1 ] && [ -r "$KNOWN_GOOD_FILE" ]; then
    KG="$(cat "$KNOWN_GOOD_FILE")"
    if arac_requires_force "${MSGS:-0}" "$KG" && [ "${ARAC_RESTORE_FORCE:-0}" != "1" ]; then
        fail "ce dump contient ${MSGS} messages contre ${KG} au dernier contrôle réussi (moins de 50 %).
       Ne contournez pas par réflexe : vérifiez d'abord la taille du dump et son
       sommaire. Si la baisse est explicable, relancez avec ARAC_RESTORE_FORCE=1."
    fi
fi


# ----------------------------------------------------------------------------
# 7. Le verdict, et la trace que le chien de garde surveille
# ----------------------------------------------------------------------------

echo ""
if [ "$RC" -eq 1 ]; then
    # UN ÉCHEC D'IDENTITÉ N'EST PAS UN ÉCHEC DE RESTAURATION, et les confondre
    # enverrait réparer un coffre qui n'a rien. Le fichier s'est restauré ; il
    # ne décrit simplement pas ce cerveau-ci. Le message doit dire lequel des
    # deux vient d'échouer, parce que les gestes n'ont rien en commun.
    if [ "${IDENTITE_KO:-0}" -eq 1 ]; then
        echo "VERDICT : ÉCHEC — ce dump se restaure, mais il ne vient PAS de ce cerveau."
        echo "          Ne touchez pas à vos sauvegardes : elles ne sont pas en cause."
        echo "          Le fichier examiné est : $DUMP"
        echo "          Les dumps de ce cerveau vivent dans : $ARAC_BACKUP_DIR"
        arac_alert critical "RESTAURATION VÉRIFIÉE : $(basename "$DUMP") ne porte pas l'empreinte de ce cerveau. Restauré, mais ce n'est pas cette mémoire."
        arac_log "restore_verify.fail" "\"dump\":\"$(basename "$DUMP")\",\"cause\":\"identite\""
        exit 1
    fi
    echo "VERDICT : ÉCHEC — ce dump n'est pas une sauvegarde utilisable."
    arac_alert critical "RESTAURATION VÉRIFIÉE : ÉCHEC sur $(basename "$DUMP"). Un dump non restaurable n'existe pas."
    arac_log "restore_verify.fail" "\"dump\":\"$(basename "$DUMP")\",\"cause\":\"restauration\""
    exit 1
fi

mkdir -p "$ARAC_BACKUP_STATE" 2>/dev/null || true
: > "$ARAC_BACKUP_STATE/last_verify_ok"
[ -n "${MSGS:-}" ] && printf '%s\n' "$MSGS" > "$KNOWN_GOOD_FILE"

if [ "$RC" -eq 2 ]; then
    echo "VERDICT : RESTAURÉ, preuve partielle ($WARNINGS réserve(s))."
    echo "          Le dump se restaure et son contenu est là. Ce qui n'a pas pu"
    echo "          être vérifié est listé ci-dessus, ligne par ligne."
else
    echo "VERDICT : PROUVÉ — ce dump se restaure, et le cerveau en sort entier."
fi
DUMP_NAME="$(basename "$DUMP")"
arac_log "restore_verify.ok" "\"dump\":\"$DUMP_NAME\",\"atoms\":${ATOMS:-0},\"messages\":${MSGS:-0},\"partial\":$([ "$RC" -eq 2 ] && echo true || echo false)"
exit "$RC"
