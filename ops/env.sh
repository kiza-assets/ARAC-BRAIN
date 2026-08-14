# shellcheck shell=bash
# ============================================================================
# LE SOCLE DES SCRIPTS D'EXPLOITATION — à sourcer, jamais à exécuter
#
#     source "$(dirname "$0")/env.sh"
#
# Il répond aux quatre questions que TOUS les scripts d'ops se posent, et
# qu'aucun ne doit résoudre à sa façon :
#
#     1. Où est installé ce cerveau ?          →  ARAC_HOME
#     2. Comment je parle à sa base ?          →  arac_dsn_*
#     3. Où je pose mes dumps et mon état ?    →  ARAC_BACKUP_DIR / _STATE
#     4. Comment je préviens quelqu'un ?       →  arac_alert
#
# POURQUOI CE FICHIER EXISTE
# --------------------------
# Le cerveau de référence avait son chemin d'installation écrit en dur dans
# plus de trois cents fichiers. Les scripts d'exploitation étaient les pires :
# ils mélangeaient le chemin, le nom de la base, le nom de l'utilisateur système
# et le canal d'alerte de leur auteur. Ils marchaient sur une machine, la
# sienne, et nulle part ailleurs.
#
# Ici, RIEN n'est écrit en dur. Chaque valeur a une variable, chaque variable a
# un défaut explicable, et le défaut est celui d'une installation neuve. Si vous
# lisez une chaîne commençant par « / » ailleurs que dans ce fichier, c'est une
# régression.
#
# CE FICHIER NE FAIT RIEN TOUT SEUL
# ---------------------------------
# Il ne se connecte à rien, ne crée rien, n'écrit rien. Le sourcer est sans
# effet observable — c'est ce qui permet de le tester (`bash -n`, `selftest`)
# sans base et sans risque.
# ============================================================================

# Sourcé, jamais exécuté : refuser l'exécution directe évite le « pourquoi ce
# script ne fait rien ? » de quelqu'un qui l'aurait lancé par curiosité.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    echo "env.sh se source, il ne s'exécute pas : source ops/env.sh" >&2
    exit 64
fi


# ----------------------------------------------------------------------------
# 1. La racine, et le fichier d'environnement
# ----------------------------------------------------------------------------
#
# Même règle que `arac_runtime.py`, et c'est délibéré : les scripts bash et le
# code Python doivent trouver la MÊME installation, sinon un dump sauvegarde une
# base que l'API n'utilise pas. Ordre : ARAC_HOME, sinon le dépôt qui contient
# ce fichier (ops/ est un niveau sous la racine).

ARAC_OPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export ARAC_HOME="${ARAC_HOME:-$(cd "$ARAC_OPS_DIR/.." && pwd)}"

#: Le fichier de secrets et de réglages, mode 0600, jamais versionné.
#
# DEUX EMPLACEMENTS EXISTENT, et les confondre coûte une soirée :
#
#   · installation manuelle : `$ARAC_HOME/.env` ;
#   · installation par le bootstrap : `/etc/arac/<base>/arac.env`, qui est ce
#     que pointent les `EnvironmentFile=` des unités systemd.
#
# Sous systemd, la question ne se pose pas : l'unité a déjà chargé le bon
# fichier, et les valeurs sont dans l'environnement. Elle se pose quand on
# lance un script d'ops À LA MAIN — et jusqu'ici, la réponse était mauvaise :
# on cherchait `$ARAC_HOME/.env`, on ne le trouvait pas, et les contrôles
# déclaraient toute la base injoignable. Un diagnostic accablant, entièrement
# faux, sur une installation parfaitement saine.
#
# ============================================================================
# LA RÈGLE QUI DÉCIDE DU COFFRE — ET POURQUOI ELLE PARLE
# ============================================================================
#
# CE QU'ON A CHOISI, ET CONTRE QUOI.
#
# Deux conduites étaient possibles quand la machine porte plusieurs cerveaux.
#
#   (1) REFUSER dès l'ambiguïté. C'est ce que sept pages ont longtemps promis.
#       C'est sûr, et c'est invivable pour qui a deux cerveaux et sait lequel
#       il vise : chaque geste d'exploitation, quatre fois par jour, exige
#       alors une variable recopiée à la main. Pire, ce refus-là n'a JAMAIS
#       existé pour de bon : le socle refusait le DSN, puis `arac_db_nom`
#       dérivait du MÊME `config/brain.toml` le dossier de dumps, le préfixe
#       de rotation et l'étiquette du journal. On disait « je ne choisis pas »
#       en choisissant tout le reste. Un refus à moitié tenu ne protège rien.
#
#   (2) CHOISIR EN SILENCE. C'est ce que le code faisait depuis. C'est
#       exactement le mécanisme qui a détruit la mémoire de l'auteur : un
#       outil qui agit sur un cerveau que personne n'a nommé, et qui ne le
#       dit pas. Un dump, une rotation, une restauration ne se rattrapent pas.
#
# On tranche pour une troisième conduite, et c'est la seule qui tienne les
# deux bouts : CHOISIR, MAIS À VOIX HAUTE — et refuser quand le choix n'est
# pas évident.
#
#   rang 1  ARAC_ENV_FILE posé            → on obéit, en silence.
#                                           C'est une DÉSIGNATION.
#   rang 2  $ARAC_HOME/.env lisible       → on le prend, en silence.
#                                           Un dépôt n'a qu'un `.env`.
#   rang 3  un seul coffre sur la machine → on le prend, en silence, SI ce
#                                           dépôt ne décrit pas quelqu'un
#                                           d'autre. Aucun choix n'est
#                                           possible : il n'y a qu'un candidat.
#   rang 4  plusieurs coffres, et CE dépôt en décrit un qui existe
#                                         → on le prend, ET ON LE DIT :
#                                           quel cerveau, quel coffre, sur
#                                           quelle preuve, combien de candidats
#                                           il y avait, et la ligne exacte pour
#                                           en désigner un autre.
#   rang 5  tout le reste                 → ARRÊT AVANT TOUT GESTE, code 1,
#                                           avec la raison exacte et la liste
#                                           des coffres, prêts à recopier.
#
# La règle tient en une phrase : ON N'AGIT JAMAIS SUR UN CERVEAU QUE PERSONNE
# N'A NOMMÉ — ou bien vous le nommez (rang 1), ou bien l'outil le nomme tout
# haut avant d'agir (rang 4).
#
# CE QUE ÇA NE BRUITE PAS. Les unités systemd posent elles-mêmes
# `Environment=ARAC_ENV_FILE=…` : sous systemd on est au rang 1, et rien n'est
# imprimé. L'annonce ne s'adresse donc qu'à un humain qui tape la commande à
# la main — précisément celui qui peut se tromper de cerveau.

#: La racine des coffres posés par le bootstrap. Elle est une VARIABLE pour
#: une raison, et elle est bonne : sans elle, la règle ci-dessus ne serait
#: éprouvable que sur une machine portant de vrais cerveaux, c'est-à-dire
#: jamais dans `make test`, qui est hermétique. `tests/test_ops_env_nomme_le_
#: cerveau_qu_il_sert.py` lui donne un faux /etc à elle et mesure les cinq
#: rangs. Une garde qu'on ne peut pas éprouver disparaît sans qu'on l'apprenne :
#: c'est très exactement ce qui vient d'arriver à celle-ci.
ARAC_ETC_DIR="${ARAC_ETC_DIR:-/etc/arac}"

if [ -z "${ARAC_ENV_FILE:-}" ]; then
    if [ -r "$ARAC_HOME/.env" ]; then
        ARAC_ENV_FILE="$ARAC_HOME/.env"          # rang 2
    else
        # `head -3` tronquait la LISTE avant même qu'on ait pu la montrer :
        # sur une machine à quatre cerveaux, le refus en nommait trois. On
        # compte tout, et on nomme tout — un refus qui cache une partie de ce
        # qu'il a vu oblige à refaire à la main le travail qu'il vient de faire.
        _arac_coffres=$(ls -1 "$ARAC_ETC_DIR"/*/arac.env 2>/dev/null)
        _arac_combien=$(printf '%s\n' "$_arac_coffres" | grep -c . || true)

        # CE DÉPÔT DÉCRIT UN CERVEAU : CE N'EST PAS UNE DEVINETTE.
        #
        # `config/brain.toml` porte le nom du cerveau que ce dossier a installé.
        # Le coffre qui lui correspond n'est donc pas « choisi à la place de
        # l'opérateur » — c'est le sien, nommé par lui, à l'entretien. Ce qui
        # manquait n'était pas le rattachement : c'était de le DIRE.
        _arac_nom_clone=""
        if [ -r "$ARAC_HOME/config/brain.toml" ]; then
            # La redirection AVANT le `<<`, l'opérateur APRÈS la parenthèse
            # fermante : tout ce qui suit le délimiteur ouvrant est relu après
            # le `PY` final. Le lint du dépôt attrape cette forme, et il a raison.
            _arac_nom_clone=$(python3 - "$ARAC_HOME/config/brain.toml" 2>/dev/null <<'PY'
import pathlib, re, sys, tomllib
d = tomllib.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(re.sub(r"_+$", "", re.sub(r"[^a-zA-Z0-9]", "_",
                                d.get("brain", {}).get("name", ""))).lower())
PY
) || _arac_nom_clone=""
        fi
        _arac_coffre_du_clone=""
        if [ -n "$_arac_nom_clone" ] && [ -e "$ARAC_ETC_DIR/$_arac_nom_clone/arac.env" ]; then
            _arac_coffre_du_clone="$ARAC_ETC_DIR/$_arac_nom_clone/arac.env"
        fi

        # arac_refus_de_designation <raison> — l'arrêt du rang 5.
        #
        # IL S'ARRÊTE POUR DE BON. L'ancien refus posait un `$ARAC_HOME/.env`
        # inexistant et laissait le script continuer : on découvrait le
        # problème trois écrans plus loin, sous un « Aucun DSN de sauvegarde »
        # qui n'avait plus rien à voir avec la vraie cause. `exit 1` depuis un
        # fichier sourcé arrête le script appelant — c'est ce que « s'arrêter
        # avant d'agir » veut dire, et c'est le seul endroit du dépôt où la
        # question se pose une fois pour toutes les commandes d'`ops/`.
        arac_refus_de_designation() {
            printf '%s\n' "ARRÊT AVANT TOUT GESTE — $1" >&2
            printf '%s\n' \
"Aucun cerveau n'est choisi à votre place : nommez celui que vous visez.
Ceux que cette machine porte, tels quels :" >&2
            printf '%s\n' "$_arac_coffres" | while IFS= read -r _c; do
                [ -n "$_c" ] && printf '    ARAC_ENV_FILE=%s\n' "$_c" >&2
            done
            printf '%s\n' \
"Puis relancez, la variable devant la commande :
    sudo ARAC_ENV_FILE=… <votre commande>" >&2
            exit 1
        }

        case "$_arac_combien" in
            0)  # Aucun coffre : l'installation est manuelle, ou absente. Les
                # scripts diront ce qui manque — il n'y a ici rien à choisir.
                ARAC_ENV_FILE="$ARAC_HOME/.env" ;;
            1)  # UN SEUL COFFRE N'EST PAS FORCÉMENT LE VÔTRE, et c'était le
                # dernier choix silencieux qui restait. Un dépôt qui décrit
                # « perso » sur une machine dont l'unique cerveau s'appelle
                # « travail » se faisait servir « travail », sans un mot :
                # un dump, une rotation, une restauration sur le cerveau d'à
                # côté. Il n'y a pas d'ambiguïté ici, il y a un DÉSACCORD.
                if [ -n "$_arac_nom_clone" ] && [ -z "$_arac_coffre_du_clone" ]; then
                    arac_refus_de_designation \
"ce dépôt décrit le cerveau « $_arac_nom_clone », et « $_arac_nom_clone » n'a pas de coffre
sur cette machine. Le seul cerveau installé ici en est un autre."
                fi
                ARAC_ENV_FILE="$_arac_coffres" ;;
            *)
                if [ -n "$_arac_coffre_du_clone" ]; then
                    ARAC_ENV_FILE="$_arac_coffre_du_clone"
                    # RANG 4 — LE CHOIX, DIT TOUT HAUT, AVANT LE PREMIER GESTE.
                    #
                    # Sur stderr, jamais sur stdout : ces scripts rendent du
                    # JSON qu'on relit à la machine, et une phrase française au
                    # milieu casserait `jq`.
                    printf '%s\n' \
"ops/ sert le cerveau « $_arac_nom_clone » — ce dépôt le décrit, il n'a pas été deviné.
    coffre      $ARAC_ENV_FILE
    preuve      $ARAC_HOME/config/brain.toml nomme « $_arac_nom_clone »
    candidats   $_arac_combien coffres sous $ARAC_ETC_DIR
Pour en servir un AUTRE, nommez-le — c'est la seule façon de ne pas dépendre
du dossier d'où vous tapez :
    sudo ARAC_ENV_FILE=$ARAC_ETC_DIR/<base>/arac.env <votre commande>" >&2
                elif [ -n "$_arac_nom_clone" ]; then
                    arac_refus_de_designation \
"ce dépôt décrit le cerveau « $_arac_nom_clone », et « $_arac_nom_clone » n'a pas de coffre
sur cette machine, où $_arac_combien autres cerveaux sont installés."
                else
                    arac_refus_de_designation \
"$_arac_combien cerveaux sont installés sous $ARAC_ETC_DIR, et ce dépôt n'en décrit
aucun (config/brain.toml absent ou illisible)."
                fi ;;
        esac
        unset _arac_nom_clone
        unset _arac_coffre_du_clone
        unset _arac_coffres
        unset _arac_combien
        unset -f arac_refus_de_designation
    fi
fi


# arac_load_env <fichier> — charge un fichier d'environnement SANS l'exécuter.
#
# La méthode habituelle (`set -a; . .env`) livre un shell complet à un fichier
# de configuration : une ligne malencontreuse y devient une commande. Ici on ne
# lit que des affectations `CLE=valeur`, on retire les guillemets englobants, et
# on n'interprète RIEN d'autre.
#
# L'environnement du processus l'emporte toujours sur le fichier : une unité
# systemd qui pose `ARAC_BACKUP_DIR=` doit gagner contre le `.env`, sinon on ne
# peut plus faire tourner deux installations sur une machine.
arac_load_env() {
    local f="${1:-$ARAC_ENV_FILE}" line key val
    [ -r "$f" ] || return 0
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line#"${line%%[![:space:]]*}"}"          # trim à gauche
        case "$line" in ''|'#'*) continue ;; esac
        case "$line" in 'export '*) line="${line#export }" ;; esac
        case "$line" in *=*) : ;; *) continue ;; esac
        key="${line%%=*}"
        val="${line#*=}"
        case "$key" in ''|*[!A-Za-z0-9_]*) continue ;; esac
        case "$val" in
            '"'*'"') val="${val%\"}"; val="${val#\"}" ;;
            "'"*"'") val="${val%\'}"; val="${val#\'}" ;;
        esac
        [ -n "${!key+x}" ] || export "$key=$val"
    done < "$f"
}

arac_load_env "$ARAC_ENV_FILE"


# ----------------------------------------------------------------------------
# 2. Où atterrissent les dumps, et où vit l'état de la sauvegarde
# ----------------------------------------------------------------------------
#
# ARAC_BACKUP_DIR est HORS de la racine par défaut, et c'est le point : une
# sauvegarde qui vit dans le dossier qu'elle sauvegarde ne sauvegarde rien. Le
# jour où `/opt/arac` disparaît, `/var/backups/arac` est encore là.
#
# ARAC_BACKUP_STATE porte la mémoire de l'exploitation : reçus de copie hors
# site, horodatage de la dernière restauration vérifiée, historique de taille.
# Cet état n'est PAS jetable — sans lui, le chien de garde ne peut plus dire
# depuis quand plus rien ne marche.

# CHAQUE CERVEAU A SON DOSSIER, ET C'EST UN CORRECTIF, PAS UN RANGEMENT.
#
# Ces trois valeurs étaient communes à TOUS les cerveaux d'une machine. La
# conséquence n'était pas cosmétique : la rotation de `backup.sh` supprime les
# dumps de plus de N jours qui portent le préfixe — un préfixe partagé, dans un
# dossier partagé, c'est un cerveau qui efface les sauvegardes de l'autre. Et
# le chien de garde, lisant l'état commun, se taisait pour un cerveau parce que
# l'AUTRE avait tourné : le silence valait alors preuve de santé.
#
# Le nom de la base est le nom du cerveau. `arac_db_nom` le trouve — dans
# l'environnement chargé plus haut, sinon dans config/brain.toml.
arac_db_nom() {
    if [ -n "${ARAC_DB:-}" ]; then printf '%s' "$ARAC_DB"; return 0; fi
    if [ -r "$ARAC_HOME/config/brain.toml" ]; then
        python3 - "$ARAC_HOME/config/brain.toml" 2>/dev/null <<'PY' && return 0
import pathlib, re, sys, tomllib
d = tomllib.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
nom = d.get("brain", {}).get("name", "")
print(re.sub(r"_+$", "", re.sub(r"[^a-zA-Z0-9]", "_", nom)).lower())
PY
    fi
    return 1
}

_ARAC_NOM="$(arac_db_nom || true)"

if [ -n "$_ARAC_NOM" ]; then
    ARAC_BACKUP_DIR="${ARAC_BACKUP_DIR:-/var/backups/arac/$_ARAC_NOM}"
    ARAC_BACKUP_STATE="${ARAC_BACKUP_STATE:-/var/lib/arac/$_ARAC_NOM/backup}"
    #: Préfixe des fichiers de dump. Sert aussi de motif de ROTATION : ne le
    #: changez pas après coup sans renommer l'existant, sinon les anciens dumps
    #: ne sont plus vus — ni par la rotation, ni par la restauration.
    ARAC_BACKUP_PREFIX="${ARAC_BACKUP_PREFIX:-$_ARAC_NOM}"

    # --- LES DESTINATAIRES `age` VIVENT DANS LE COFFRE DE CE CERVEAU --------
    #
    # La documentation faisait déposer les clés publiques à un chemin commun à
    # la machine, avec une redirection qui TRONQUE :
    #
    #     echo 'age1...' > /etc/arac/backup-recipients.txt
    #
    # Deux dégâts, et le second est le pire. Le premier : `/etc/arac/` est la
    # racine commune, elle n'appartient à personne — le second cerveau écrase
    # le fichier du premier, et les sauvegardes du premier partent chiffrées
    # pour quelqu'un d'autre, c'est-à-dire illisibles pour lui. Le second : un
    # `>` sur un fichier qui contenait DÉJÀ une clé la remplace. Le jour de la
    # restauration, la clé privée qu'on a gardée précieusement ne déchiffre
    # rien, et il n'existe aucun recours.
    #
    # Le fichier vit donc dans `/etc/arac/<base>/`, à côté des autres secrets
    # de ce cerveau, en 0600 root comme eux. Et il n'est pris en compte que
    # s'il EXISTE : un chemin par défaut qui n'existe pas ferait échouer la
    # sauvegarde (`arac_die` sur « fichier de destinataires illisible ») là où
    # l'absence de chiffrement doit rester un avertissement.
    _arac_destinataires="$ARAC_ETC_DIR/$_ARAC_NOM/backup-recipients.txt"
    if [ -z "${ARAC_BACKUP_RECIPIENTS:-}" ] && [ -r "$_arac_destinataires" ]; then
        ARAC_BACKUP_RECIPIENTS="$_arac_destinataires"
    fi
    ARAC_BACKUP_RECIPIENTS="${ARAC_BACKUP_RECIPIENTS:-}"
    #: Le chemin ATTENDU, que les scripts citent dans leurs messages. Il vaut
    #: mieux nommer l'endroit une fois ici que le réécrire dans trois messages.
    ARAC_BACKUP_RECIPIENTS_ATTENDU="$_arac_destinataires"
    unset _arac_destinataires
else
    # Sans identité, on ne devine pas un chemin : on laisse les scripts dire
    # ce qui manque. Poser un dossier commun « en attendant » est précisément
    # ce qui a mêlé deux cerveaux.
    ARAC_BACKUP_DIR="${ARAC_BACKUP_DIR:-}"
    ARAC_BACKUP_STATE="${ARAC_BACKUP_STATE:-}"
    ARAC_BACKUP_PREFIX="${ARAC_BACKUP_PREFIX:-}"
    ARAC_BACKUP_RECIPIENTS="${ARAC_BACKUP_RECIPIENTS:-}"
    ARAC_BACKUP_RECIPIENTS_ATTENDU=""
fi

#: Le schéma PostgreSQL du cerveau. Un seul, et c'est lui qu'on dumpe.
#: Il vit DANS la base : deux cerveaux ne peuvent pas se le disputer.
ARAC_DB_SCHEMA="${ARAC_DB_SCHEMA:-arac}"


# ----------------------------------------------------------------------------
# 3. Les DSN — et pourquoi la sauvegarde a son propre rôle
# ----------------------------------------------------------------------------
#
# `pg_dump` a besoin de SELECT sur toutes les tables et de USAGE sur toutes les
# séquences. C'est exactement le rôle `arac_backup`
# (db/migrations/05_role_backup.sql.template) : il lit tout, il n'écrit rien,
# il ne peut pas migrer.
#
# Se rabattre sur le rôle ADMIN fonctionne — et dégrade la sûreté : la
# sauvegarde tourne alors sous le seul rôle capable de détruire le schéma, à
# heure fixe, sans surveillance. Le script le dit à voix haute plutôt que de le
# taire.

#: Le DSN de lecture intégrale, pour pg_dump.
arac_backup_dsn() {
    if [ -n "${ARAC_BACKUP_DSN:-}" ]; then
        printf '%s' "$ARAC_BACKUP_DSN"; return 0
    fi
    if [ -n "${DATABASE_URL_BACKUP:-}" ]; then
        printf '%s' "$DATABASE_URL_BACKUP"; return 0
    fi
    if [ -n "${DATABASE_URL_ADMIN:-}" ]; then
        printf '%s' "$DATABASE_URL_ADMIN"; return 0
    fi
    return 1
}

#: Vrai si la sauvegarde tourne sous le rôle DDL faute de mieux.
arac_backup_dsn_is_admin() {
    [ -z "${ARAC_BACKUP_DSN:-}" ] && [ -z "${DATABASE_URL_BACKUP:-}" ] \
        && [ -n "${DATABASE_URL_ADMIN:-}" ]
}

#: Le DSN de lecture stricte, pour tout ce qui observe sans toucher.
arac_readonly_dsn() {
    printf '%s' "${ARAC_READONLY_DSN:-${DATABASE_URL_READONLY:-}}"
}

#: Le DSN de maintenance : celui qui peut CREATE DATABASE / DROP DATABASE pour
#: fabriquer une base jetable. Par défaut, le rôle admin pointé sur la base
#: `postgres` — on ne se connecte JAMAIS à la base qu'on s'apprête à recréer.
arac_maintenance_dsn() {
    if [ -n "${ARAC_MAINTENANCE_DSN:-}" ]; then
        printf '%s' "$ARAC_MAINTENANCE_DSN"; return 0
    fi
    [ -n "${DATABASE_URL_ADMIN:-}" ] || return 1
    arac_dsn_with_db "$DATABASE_URL_ADMIN" "${ARAC_MAINTENANCE_DB:-postgres}"
}


# arac_dsn_with_db <dsn> <base> — le même DSN, une autre base.
#
# Fonction PURE : pas de réseau, pas de fichier. Elle remplace le dernier
# segment du chemin de l'URL en préservant la chaîne de paramètres. C'est ce qui
# permet à un script de créer `arac_restore_2026...` sur le même serveur que la
# base vivante, avec les mêmes identifiants, sans jamais recomposer un DSN à la
# main dans un coin.
arac_dsn_with_db() {
    local dsn="$1" db="$2" head query=''
    head="${dsn%%\?*}"
    [ "$dsn" != "$head" ] && query="?${dsn#*\?}"
    printf '%s/%s%s' "${head%/*}" "$db" "$query"
}

# arac_dsn_db_name <dsn> — le nom de la base d'un DSN. Pure elle aussi.
# Sert au garde-fou : la cible d'une restauration de test ne doit JAMAIS être
# la base vivante, et « vivante » se déduit du DSN, pas d'un nom deviné.
arac_dsn_db_name() {
    local dsn="$1" head
    head="${dsn%%\?*}"
    printf '%s' "${head##*/}"
}

# arac_dsn_user <dsn> — le RÔLE PostgreSQL de ce DSN, ou rien.
#
# POURQUOI CETTE FONCTION EXISTE
#
# `ops/restore_verify.sh` imprimait, quand la création de la base jetable
# échouait : « ALTER ROLE <votre rôle admin> CREATEDB; ». Le script CONNAÎT ce
# rôle — il est dans le DSN avec lequel il vient d'essayer. Faire deviner à
# quelqu'un une valeur qu'on a sous la main, c'est, sur une machine à deux
# cerveaux, l'inviter à aller la chercher dans le coffre du voisin. Même
# leçon que `arac_dsn_port` : ce qu'on sait, on l'écrit.
arac_dsn_user() {
    printf '%s' "${1:-}" | python3 -c 'import sys, urllib.parse
try:
    print(urllib.parse.urlparse(sys.stdin.read().strip()).username or "")
except Exception:
    print("")' 2>/dev/null || true
}

# arac_dsn_port <dsn> — le PORT du serveur désigné par ce DSN, ou rien.
#
# POURQUOI CETTE FONCTION EXISTE, ET CE QU'ELLE RÉPARE
#
# Les scripts, eux, parlent au serveur par un DSN : hôte et port y sont écrits,
# ils ne se trompent pas de grappe. Les commandes que ce dépôt IMPRIME pour
# être recopiées à la main — celles qui réclament le superutilisateur, donc
# celles qu'on ne peut pas exécuter à la place de l'utilisateur — n'ont pas de
# DSN :
#
#     sudo -u postgres psql -v ON_ERROR_STOP=1 -f -
#
# `psql` sans `-p` s'adresse à la grappe PAR DÉFAUT de la machine. Sur un poste
# qui en porte deux — ce que ce framework rend normal, et même recommandé —
# celui qui suit un message affiché par SON cerveau exécute la commande sur
# celui du VOISIN. Le `DROP DATABASE` du gabarit de restauration est dans ce
# lot. Un `-p` explicite n'est donc pas de la précision de style : c'est la
# seule chose, dans la commande, qui nomme la grappe.
arac_dsn_port() {
    printf '%s' "${1:-}" | python3 -c 'import sys, urllib.parse
try:
    print(urllib.parse.urlparse(sys.stdin.read().strip()).port or "")
except Exception:
    print("")' 2>/dev/null || true
}

# arac_dsn_redacted <dsn> — le même DSN, mot de passe effacé.
# À utiliser dans TOUT message, TOUT log, TOUTE alerte. Un DSN complet dans
# journald est un secret publié : journald se lit, se copie, s'exporte.
arac_dsn_redacted() {
    local dsn="$1"
    printf '%s' "$dsn" | sed -E 's#(://[^:/@]+):[^@]*@#\1:***@#'
}


# ----------------------------------------------------------------------------
# 4. Dire les choses — journal et alerte
# ----------------------------------------------------------------------------
#
# Sortie JSON sur stdout : ces scripts tournent sous systemd, et journald garde
# une ligne JSON aussi bien qu'une phrase, mais une ligne JSON se relit six mois
# plus tard avec `journalctl -o cat | jq`.

#: Horodatage UTC, format ISO. Toujours UTC : un incident se raconte dans un
#: seul fuseau, sinon on passe la nuit à recoller des heures locales.
arac_now() { date -u +%FT%TZ; }

arac_log() {  # arac_log <evenement> [<json partiel sans accolades>]
    printf '{"at":"%s","event":"%s"%s}\n' "$(arac_now)" "$1" "${2:+,$2}"
}

arac_warn() { printf '%s\n' "$*" >&2; }

arac_die() { printf '%s\n' "$*" >&2; exit 1; }


# arac_alert <niveau> <message> — prévenir un humain.
#
# LE CANAL N'EST PAS DÉCIDÉ ICI, et c'est volontaire. Le cerveau de référence
# écrivait « envoie sur Telegram » au milieu de ses scripts de sauvegarde : le
# jour où l'on veut un courriel, une sonde Prometheus ou un ntfy, il faut
# rouvrir six fichiers.
#
# Ici, une seule variable :
#
#     ARAC_ALERT_CMD="/usr/local/bin/mon-alerteur"
#
# Elle reçoit le niveau en $1 (« warn » ou « critical ») et le message en $2.
# Si elle n'est pas posée, l'alerte part dans le journal système, où elle est
# visible mais silencieuse — c'est un défaut honnête, pas une garantie :
#
#     ⚠ Sans ARAC_ALERT_CMD, PERSONNE n'est réveillé. Le chien de garde aboie
#       dans un journal que personne ne lit. Posez-la avant de compter dessus.
arac_alert() {
    local level="$1" msg="$2"
    arac_log "alert" "\"level\":\"$level\",\"message\":$(arac_json_string "$msg")"
    if [ -n "${ARAC_ALERT_CMD:-}" ]; then
        "$ARAC_ALERT_CMD" "$level" "$msg" || arac_warn "ARAC_ALERT_CMD a échoué (rc=$?)"
    else
        # L'ÉTIQUETTE PORTE LE NOM DU CERVEAU, comme les huit unités systemd.
        #
        # Elle valait « arac-ops », globale à toute la machine. Deux cerveaux
        # dont la sauvegarde échoue mêlaient donc leurs lignes sous le même
        # tag — au moment précis où l'on ouvre le journal pour savoir LEQUEL
        # des deux a cassé. Le dépôt applique déjà le bon remède à ses unités
        # (`SyslogIdentifier=arac-<base>-…`) ; il le manquait au seul endroit
        # qui n'est pas une unité. `ARAC_UNIT_PREFIX` est dans le coffre que
        # ce fichier vient de sourcer : le nom est là, il suffisait de s'en
        # servir.
        logger -t "${ARAC_UNIT_PREFIX:-arac}-ops" \
            -p "user.$([ "$level" = critical ] && echo err || echo warning)" \
            -- "$msg" 2>/dev/null || arac_warn "[$level] $msg"
    fi
}

# arac_json_string <texte> — échappe un texte pour l'insérer dans du JSON.
# Suffisant pour nos messages (guillemets, antislash, retours à la ligne).
arac_json_string() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    s="${s//$'\n'/\\n}"
    s="${s//$'\t'/\\t}"
    printf '"%s"' "$s"
}


# ----------------------------------------------------------------------------
# 5. Petits outils communs
# ----------------------------------------------------------------------------

#: Âge d'un fichier en heures. 99999 s'il n'existe pas — un fichier absent est
#: infiniment vieux, jamais « récent par défaut ». Le sens du défaut décide de
#: qui se fait réveiller.
arac_age_hours() {
    local f="$1" now mtime
    [ -e "$f" ] || { printf '99999'; return; }
    now=$(date +%s); mtime=$(stat -c %Y "$f")
    printf '%s' $(( (now - mtime) / 3600 ))
}

#: Le fichier le plus récent d'un motif, ou rien.
arac_newest() {
    local dir="$1" pattern="$2" f newest='' newest_t=0 t
    shopt -s nullglob
    for f in "$dir"/$pattern; do
        t=$(stat -c %Y "$f" 2>/dev/null || echo 0)
        [ "$t" -gt "$newest_t" ] && { newest="$f"; newest_t="$t"; }
    done
    shopt -u nullglob
    printf '%s' "$newest"
}

#: L'interpréteur de l'installation — celui qui a les dépendances.
arac_python() { printf '%s' "${ARAC_PYTHON:-$ARAC_HOME/.venv/bin/python}"; }

#: Exige un binaire, avec le paquet à installer dans le message. Un « command
#: not found » à 4 h du matin ne dit pas quoi faire ; celui-ci, si.
arac_require() {
    local bin="$1" hint="${2:-}"
    command -v "$bin" >/dev/null 2>&1 && return 0
    arac_die "Commande absente : $bin${hint:+ — $hint}"
}
