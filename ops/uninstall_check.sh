#!/usr/bin/env bash
# ============================================================================
# CE QUI RESTE D'UN CERVEAU DÉSINSTALLÉ — et POURQUOI ça reste
#
#     ops/uninstall_check.sh <base>                     # que reste-t-il ?
#     ops/uninstall_check.sh <base> --port 5486         # sur CETTE grappe
#     ops/uninstall_check.sh <base> --empreinte <uuid>  # CE cerveau-là
#     ops/uninstall_check.sh <base> --fouiller <dir>    # + ce répertoire
#     ops/uninstall_check.sh <base> --gestes            # + les commandes exactes
#
# CODES DE SORTIE
#   0  il ne reste RIEN de ce cerveau aux endroits regardés — ils sont nommés
#   1  il reste quelque chose — chaque reste est nommé, avec sa cause
#   2  le contrôle n'a pas pu tout voir (pas de superutilisateur système,
#      grappe injoignable, archive chiffrée illisible)
#
# CE SCRIPT NE DÉTRUIT RIEN. Il lit, il nomme, et avec `--gestes` il IMPRIME
# les commandes. La destruction reste un geste qu'on lit avant de le faire.
#
# IL FONCTIONNE SANS LE COFFRE, et c'est le point : il tourne APRÈS la
# désinstallation, donc après que `/etc/arac/<base>/` a été effacé.
# ============================================================================
#
# POURQUOI CE FICHIER EXISTE
# --------------------------
# La page de désinstallation portait un contrôle de fin qui disait : « chacune
# de ces lignes doit ne RIEN rendre ». Il rendait le nom d'un rôle survivant —
# et rien d'autre. Il ne pouvait pas rendre la CAUSE, parce que sa requête ne
# regardait qu'une seule base : celle du cerveau.
#
# ET IL A DIT « PROPRE » SUR UNE MACHINE QUI PORTAIT QUATRE COPIES COMPLÈTES,
# LISIBLES, DE LA MÉMOIRE. C'est le constat qui a produit la version que vous
# lisez, et il faut l'écrire en entier parce qu'il touche à la promesse la plus
# intime du produit — pouvoir partir. Mesuré, le §13 suivi mot pour mot :
#
#   · son étape 2 écrit `$HOME/adieu-<base>-<date>.dump` (mode 644) ;
#   · son étape 7, branche (a), DÉPLACE les dumps dans `$HOME/dumps-<base>-
#     conserves` ;
#   · une vérification de restauration interrompue laisse une base jetable
#     dont le nom ne dérive de rien (`ARAC_RESTORE_DB` la nomme librement) ;
#   · et le contrôle ne cherchait des dumps qu'à UN endroit, sur le seul motif
#     de leur NOM. Il imprimait « ✓ ni coffre, ni journaux, ni état, ni dumps »,
#     comptait zéro reste, et sortait en 0.
#
# LE CRITÈRE DE FORME — ce qui a changé, et c'est tout ce fichier
# ---------------------------------------------------------------
# Cinq fois ce contrôle a buté sur une ÉNUMÉRATION : la liste des noms de bases
# dérivées, la liste des suffixes de dumps, la liste des répertoires. Une liste
# oublie toujours, et ce qu'elle oublie est précisément ce que personne n'avait
# imaginé.
#
# La question n'est pas « ce nom ressemble-t-il au mien ? ». C'est :
#
#     CET OBJET CONTIENT-IL LA MÉMOIRE DE CE CERVEAU-CI ?
#
# Et le dépôt savait déjà y répondre — il ne l'avait simplement jamais demandé
# ici. Le bootstrap grave une EMPREINTE d'installation, « choisie par
# personne », à deux endroits qui voyagent avec la mémoire :
#
#   · `COMMENT ON SCHEMA arac IS 'ARAC cerveau=… empreinte=… poste=…'`,
#     que `pg_dump --schema` emporte À L'INTÉRIEUR du fichier de dump ;
#   · `COMMENT ON ROLE … IS 'arac:cerveau=…;empreinte=…;secrets=…'`,
#     global à la grappe, donc absent des dumps — et c'est pour cela qu'il ne
#     pouvait pas servir aux fichiers.
#
# On interroge donc l'OBJET, jamais son nom :
#
#   · une BASE, quel que soit son nom, sur n'importe quelle grappe : on s'y
#     connecte et on lit le commentaire de ses schémas. C'est ainsi qu'une base
#     appelée « copie_de_secours » est reconnue pour ce qu'elle est — le
#     cerveau entier — et qu'un cerveau VOISIN portant EXACTEMENT le même nom
#     que le nôtre, sur une autre grappe, est reconnu pour ce qu'il est : celui
#     de quelqu'un d'autre, qu'on ne touche pas ;
#   · un FICHIER : on lit ses premiers octets. `PGDMP` est la signature d'une
#     archive `pg_dump`, `toc.dat` celle d'une archive tar, `-- PostgreSQL
#     database dump` celle d'un dump en clair. Alors — et alors seulement — on
#     demande à `pg_restore --schema-only` ce que ce fichier déclare. Aucun nom
#     de fichier n'entre dans ce jugement, aucune extension, aucun répertoire.
#
# C'est le même geste que le garde des exécutables, qui lit la table des
# symboles dynamiques de l'ELF au lieu d'énumérer `sh`, `perl`, `awk`… : on
# demande à la chose ce qu'elle est.
#
# CE QUE LE CRITÈRE DE FORME NE PEUT PAS FAIRE — et il faut le dire, sinon
# « PROPRE » redevient un mensonge :
#
#   1. UNE ARCHIVE CHIFFRÉE (`*.age`) ne se lit pas sans la clé privée, qui par
#      construction ne vit pas ici. Pour celles-là, et pour elles seules, il
#      reste le NOM — et la réserve est imprimée avec le constat.
#   2. UN DUMP D'AVANT L'EMPREINTE ne porte pas de plaque. Le repli par le nom
#      demeure donc, en SECOND filet, jamais en premier, et toujours annoncé.
#   3. ON NE BALAIE PAS LA MACHINE ENTIÈRE. Les racines fouillées sont bornées,
#      et elles sont IMPRIMÉES avec le verdict : « PROPRE » ne veut jamais dire
#      plus que « rien aux endroits que voici ». `--fouiller` en ajoute.
#
# L'ordre des sections est le raisonnement : la mémoire d'abord (bases,
# fichiers), les serrures ensuite (rôles), le décor en dernier (unités,
# estampilles, dossiers, comptes).
# ============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPOT="$(cd "$HERE/.." && pwd)"

#: La racine des coffres — la MÊME variable que `ops/env.sh`, et pour la même
#: raison : « où vivent les coffres ? » n'a qu'une réponse dans ce dépôt, et
#: deux conventions voisines pour la même question est la classe de défaut que
#: ce dépôt passe des manches à éliminer. Ce script-ci ne source pas `env.sh`
#: (il doit pouvoir tourner APRÈS la désinstallation, quand il n'y a plus de
#: coffre à charger) : il pose donc le même défaut, explicitement.
ARAC_ETC_DIR="${ARAC_ETC_DIR:-/etc/arac}"

BASE=''
PORT=''
GESTES=0
EMPREINTE=''
declare -a FOUILLES=()

while [ $# -gt 0 ]; do
    case "$1" in
        --port)        PORT="${2:-}"; shift 2 ;;
        --port=*)      PORT="${1#--port=}"; shift ;;
        --empreinte)   EMPREINTE="${2:-}"; shift 2 ;;
        --empreinte=*) EMPREINTE="${1#--empreinte=}"; shift ;;
        --fouiller)    FOUILLES+=("${2:-}"); shift 2 ;;
        --fouiller=*)  FOUILLES+=("${1#--fouiller=}"); shift ;;
        --gestes)      GESTES=1; shift ;;
        -h|--help)
            sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        -*)            printf 'option inconnue : %s\n' "$1" >&2; exit 64 ;;
        *)             BASE="$1"; shift ;;
    esac
done

if [ -z "$BASE" ]; then
    cat >&2 <<'USAGE'
Il manque le nom de la base — c'est-à-dire le nom du cerveau, tel que le
bootstrap l'a dérivé du nom que vous lui aviez donné.

    ops/uninstall_check.sh <base> [--port <port>] [--empreinte <uuid>]
                                  [--fouiller <dir>] [--gestes]

On ne le devine pas : sur une machine qui a porté plusieurs cerveaux, deviner
« celui qu'on vient de retirer » revient à désigner celui du voisin. Si vous
ne vous souvenez plus du nom, les restes le portent :

    ls /etc/arac/                      # les coffres encore présents
    systemctl list-units --all 'arac-*'
    sudo -u postgres psql -p <port> -tAc \
      "SELECT rolname FROM pg_roles WHERE rolname LIKE 'arac\_%'"
USAGE
    exit 64
fi

case "$BASE" in
    *[!a-z0-9_]*|'')
        printf 'Nom de base refusé : « %s » — seuls [a-z0-9_] sont attendus.\n' "$BASE" >&2
        exit 64 ;;
esac

case "$EMPREINTE" in
    ''|*[!a-zA-Z0-9]*)
        [ -n "$EMPREINTE" ] && {
            printf 'Empreinte refusée : « %s » — seuls [a-zA-Z0-9] sont attendus.\n' "$EMPREINTE" >&2
            exit 64
        } ;;
esac

#: LE PRÉFIXE DES UNITÉS DE CE CERVEAU, composé UNE FOIS.
#:
#: Il ne s'écrit nulle part ailleurs, et surtout jamais collé à un chemin :
#: « /var/lib/systemd/timers/stamp-arac-$BASE- » ferait apparaître dans ce
#: fichier le littéral « stamp-arac- », c'est-à-dire une racine que deux
#: cerveaux se partagent. Le garde G1 refuse cette forme, et il a raison : ce
#: qui ressemble à un chemin commun finit par en être un.
PREFIXE_UNITE="arac-$BASE"

RESTES=0
PARTIEL=0
#: L'EMPREINTE QU'ON A LUE DANS LES OBJETS, quand l'appelant n'en a donné
#: aucune. Le rapport la connaît — il l'imprime déjà, objet par objet
#: (« relancez avec « --empreinte <celle-ci> » si vous la reconnaissez »). Elle
#: est retenue ici pour que la COMMANDE DE SUITE imprimée en pied de page la
#: porte : une invitation à relancer qui perd l'argument qui tranche rend une
#: liste de gestes amputée, et c'est ce qui a coûté une copie complète de
#: mémoire oubliée sur un serveur qu'on croyait rendu.
EMPREINTE_VUE=''
#: Levé quand ce contrôle n'a pas pu ATTESTER de quel cerveau il parle. Ce
#: n'est pas la même chose que « il n'a pas pu voir » : la fouille a bien eu
#: lieu, par la forme, partout. Ce qui manque est de quoi trancher entre deux
#: homonymes — et cette réserve voyage jusqu'au verdict plutôt que de le rendre
#: illisible en le transformant en « je ne sais pas ».
RESERVE_IDENTITE=0
#: Levé quand ce contrôle a vu, quelque part, la mémoire d'un AUTRE cerveau
#: portant le nom qu'on cherche. Il change le verdict : on ne prescrit rien.
HOMONYME=0
#: Nombre de gestes retenus faute de certitude — imprimé avec sa raison.
RETENUS=0
#: Restes pour lesquels il n'existe AUCUN geste borné à ce cerveau — le journal
#: système en est un : systemd ne sait pas effacer les entrées d'une seule
#: unité. Sans ce compteur, la branche « aucun geste imprimé » accuserait ce
#: fichier d'un défaut (« il a nommé un reste sans savoir quoi en dire ») là où
#: c'est le système qui n'offre rien. Accuser le mauvais coupable envoie
#: chercher au mauvais endroit.
SANS_GESTE=0

#: LES GESTES SONT RANGÉS PAR FAMILLE, ET LA FAMILLE DÉCIDE DE L'ORDRE.
#:
#: L'ordre réel a quatre temps, et chacun débloque le suivant :
#:   1. ARRÊTER  — tant qu'un service parle à la base, elle ne se détruit pas ;
#:   2. les BASES — tant qu'un rôle possède une base, il ne se détruit pas ;
#:   3. les RÔLES — ils sont globaux à la grappe, c'est le geste à lire deux fois ;
#:   4. les FICHIERS — unités, estampilles, coffre, dossiers, comptes, copies.
declare -a GESTES_ARRET=() GESTES_BASE=() GESTES_ROLE=() GESTES_FICHIER=()

titre()  { printf '\n%s\n' "$1"; printf '%s\n' "$(printf '─%.0s' $(seq 1 ${#1}))"; }
reste()  { printf '  ✗ %s\n' "$1"; RESTES=$(( RESTES + 1 )); }
cause()  { printf '      ↳ %s\n' "$1"; }
propre() { printf '  ✓ %s\n' "$1"; }
autre()  { printf '  · %s\n' "$1"; }
aveugle(){ printf '  ? %s\n' "$1"; PARTIEL=1; }
#: UN GESTE PORTE LA QUALITÉ DE SA PREUVE, et c'est elle qui décide s'il
#: s'imprime. « C » : l'objet a été reconnu à l'EMPREINTE gravée dedans — il
#: n'y a pas d'homonyme possible, le geste est sûr, quelle que soit la grappe.
#: « N » : reconnu sur son NOM SEUL — plaque absente, archive chiffrée,
#: empreinte inconnue. Celui-là ne s'imprime que si rien, sur cette machine,
#: ne rend un nom ambigu. C'est toute la différence entre le critère de forme
#: et l'énumération : le premier autorise à agir, le second oblige à se taire.
geste()  { # <famille> <commande> [nom]
    local q='C'; [ "${3:-}" = nom ] && q='N'
    case "$1" in
        arret)   GESTES_ARRET+=("$q"$'\t'"$2") ;;
        base)    GESTES_BASE+=("$q"$'\t'"$2") ;;
        role)    GESTES_ROLE+=("$q"$'\t'"$2") ;;
        *)       GESTES_FICHIER+=("$q"$'\t'"$2") ;;
    esac
}

#: D'OÙ VIENT UNE BASE — l'EXPLICATION, jamais l'identification.
#:
#: La distinction est tout le sujet de ce fichier. C'est la PLAQUE qui dit
#: « ceci est votre mémoire » ; le nom, lui, ne sert plus qu'à raconter au
#: lecteur par quel chemin du produit cette base est née. Une base reconnue à
#: son empreinte est un reste même si son nom ne dit rien — mais quand le nom
#: parle, on traduit, parce qu'« une base de plus » n'aide personne à décider.
_origine_de_la_base() { # <datname> → une phrase, ou vide
    case "$1" in
        "$BASE")                   printf "c'est la base vivante elle-même : l'étape 4 du §13 ne l'a pas détruite, ou a visé une autre grappe." ;;
        "${BASE}_restore_template") printf "posée par l'étape 4 du BOOTSTRAP, pas par vous — c'est le gabarit de la restauration vérifiée." ;;
        "${BASE}"_restore_*)       printf "base jetable d'une vérification de sauvegarde interrompue, ou conservée par « --keep »." ;;
        "${BASE}"_avarie_*)        printf "c'est votre cerveau d'AVANT la bascule, renommé par docs/SAUVEGARDE.md §7 étape 5, qui demande de le garder « jusqu'à ce que la nouvelle ait fait ses preuves »." ;;
        "${BASE}"_restauree_*)     printf "née à l'étape 3 du §7 et jamais basculée — une restauration interrompue en chemin." ;;
        "${BASE}_test")            printf "le rituel manuel imprimé par bootstrap/checks/verify_install.sh." ;;
        *)                         printf "son nom ne dit pas d'où elle vient — ce contrôle ne sait pas QUI l'a créée, seulement qu'elle porte votre mémoire." ;;
    esac
}

#: UN CHAMP D'UNE PLAQUE, quelle que soit sa ponctuation.
#:
#: Les deux plaques du produit ne se séparent pas de la même façon — celle des
#: rôles par « ; », celle du schéma par des espaces — et c'est normal : l'une
#: vit dans un commentaire lu par `\du+`, l'autre dans un commentaire qui doit
#: traverser un `pg_dump`. Les lire avec deux fonctions différentes, c'est
#: préparer le jour où l'une des deux sera oubliée.
_champ_de() { # <plaque> <champ> → la valeur, ou vide
    local t=" ${1//;/ }"
    t=" ${t//:/ }"
    case "$t" in
        *" $2="*) local r="${t#*" $2="}"; printf '%s' "${r%% *}" ;;
        *)        printf '' ;;
    esac
}

printf 'CE QUI RESTE DU CERVEAU « %s » SUR CETTE MACHINE\n' "$BASE"


# ----------------------------------------------------------------------------
# 0. Les grappes à interroger, et l'empreinte de ce cerveau
# ----------------------------------------------------------------------------
#
# Un rôle PostgreSQL est GLOBAL à sa grappe, et une machine qui héberge
# plusieurs cerveaux en porte souvent plusieurs. Si l'on ne nous donne pas de
# port, on interroge TOUTES les grappes de la machine plutôt que la grappe par
# défaut : chercher au mauvais endroit et n'y rien trouver, c'est conclure
# « c'est propre » sur une machine qui ne l'est pas.
#
# MAIS DÉTECTER PARTOUT N'EST PAS PRESCRIRE PARTOUT — et c'est le CRITÈRE DE
# FORME qui fait la différence. Ce script composait, à partir d'un seul mot tapé
# par un humain, un `dropdb` et cinq `DROP ROLE` portant le port d'une grappe
# que personne n'avait désignée. Sur une machine à plusieurs grappes, sans
# `--port`, il imprimait la séquence complète qui efface une mémoire — sous un
# titre qui dit « LES GESTES, DANS L'ORDRE OÙ ILS PASSENT ».
#
# Désormais : un objet reconnu à son EMPREINTE se prescrit sans réserve, où
# qu'il soit — une empreinte ne se partage pas, la grappe n'y change rien. Un
# objet reconnu sur son NOM SEUL ne se prescrit que si aucun homonyme n'a été
# vu et si l'on a désigné sa grappe. La forme autorise à agir ; le nom oblige
# à se taire.

PORTS=()
if [ -n "$PORT" ]; then
    PORTS=("$PORT")
elif command -v pg_lsclusters >/dev/null 2>&1; then
    mapfile -t PORTS < <(pg_lsclusters --no-header 2>/dev/null | awk '{print $3}')
fi


SUPER_OK=0
if [ "$(id -u)" = "0" ] || sudo -n true 2>/dev/null; then
    SUPER_OK=1
fi

psql_super() { # <port> <sql>
    sudo -u postgres psql -p "$1" -X -tAc "$2" 2>/dev/null
}
psql_dans() { # <port> <base> <sql>
    sudo -u postgres psql -p "$1" -d "$2" -X -tAc "$3" 2>/dev/null
}

# L'EMPREINTE — d'où elle vient, et ce qu'on fait quand elle manque.
#
# Ce contrôle tourne APRÈS l'effacement du coffre : c'est son point. Il faut
# donc pouvoir la lui donner (`--empreinte`), et savoir la retrouver seul.
# Cinq sources, de la plus explicite à la plus déduite ; celle qui répond la
# première gagne, et on DIT laquelle a répondu.
EMPREINTE_SOURCE=''
#: L'empreinte est-elle ATTESTÉE, ou seulement DÉDUITE ?
#:
#: La distinction n'est pas académique, et elle a été mesurée sur ce banc.
#: Quand plus rien de ce cerveau ne subsiste et qu'un HOMONYME vit encore sur
#: une autre grappe, la déduction « une seule empreinte porte ce nom, donc
#: c'est la vôtre » désigne CELLE DU VOISIN — et le contrôle prescrivait alors
#: de détruire sa mémoire. La déduction est un raisonnement qui part du NOM :
#: elle ne peut donc pas rendre une certitude que le nom n'a pas. Tout ce qui
#: en découle est marqué « reconnu sur son nom », et se tait quand un nom
#: devient ambigu.
EMPREINTE_SURE=1
if [ -n "$EMPREINTE" ]; then
    EMPREINTE_SOURCE='donnée par vous (--empreinte)'
elif [ -n "${ARAC_INSTALL_UUID:-}" ]; then
    EMPREINTE="$ARAC_INSTALL_UUID"
    EMPREINTE_SOURCE="lue dans l'environnement (ARAC_INSTALL_UUID)"
elif [ -r "$ARAC_ETC_DIR/$BASE/arac.env" ]; then
    EMPREINTE="$(sed -n 's/^ARAC_INSTALL_UUID=//p' "$ARAC_ETC_DIR/$BASE/arac.env" | tr -d '"'"'"' \r')"
    [ -n "$EMPREINTE" ] && EMPREINTE_SOURCE="lue dans le coffre — qui est lui-même un reste"
fi
if [ -z "$EMPREINTE" ] && [ -r "$DEPOT/config/brain.toml" ]; then
    _nom_toml="$(sed -n 's/^ *name *= *"\([^"]*\)".*/\1/p' "$DEPOT/config/brain.toml" | head -1)"
    _nom_toml="$(printf '%s' "$_nom_toml" | tr -c 'a-zA-Z0-9' '_' | sed 's/_*$//')"
    if [ "${_nom_toml,,}" = "$BASE" ]; then
        EMPREINTE="$(sed -n 's/^ *uuid *= *"\([^"]*\)".*/\1/p' "$DEPOT/config/brain.toml" | head -1)"
        [ -n "$EMPREINTE" ] && EMPREINTE_SOURCE="lue dans la description restée dans ce clone (config/brain.toml)"
    fi
fi

# LA DÉDUCTION, EN DERNIER RECOURS — et elle sait dire qu'elle ne peut pas.
#
# Toutes les plaques qui déclarent « cerveau=<BASE> » sont rassemblées. Si
# elles portent UNE seule empreinte, c'est celle de ce cerveau et on le dit. Si
# elles en portent PLUSIEURS, deux installations du même nom cohabitent : c'est
# exactement le cas qu'on ne sait pas trancher tout seul, et le prétendre
# coûterait la mémoire de l'une des deux.
if [ -z "$EMPREINTE" ] && [ "$SUPER_OK" -eq 1 ]; then
    _vues=''
    for p in "${PORTS[@]:-}"; do
        [ -z "$p" ] && continue
        _vues="$_vues$(psql_super "$p" \
            "SELECT coalesce(shobj_description(oid,'pg_authid'),'')
               FROM pg_roles
              WHERE coalesce(shobj_description(oid,'pg_authid'),'') LIKE 'arac:%'")
"
    done
    _emps=''
    while IFS= read -r _pl; do
        [ -z "$_pl" ] && continue
        [ "$(_champ_de "$_pl" cerveau)" = "$BASE" ] || continue
        _e="$(_champ_de "$_pl" empreinte)"
        [ -n "$_e" ] && _emps="$_emps$_e
"
    done <<< "$_vues"
    _uniq="$(printf '%s' "$_emps" | sort -u | grep -c . || true)"
    if [ "${_uniq:-0}" = "1" ]; then
        EMPREINTE="$(printf '%s' "$_emps" | sort -u | grep . | head -1)"
        EMPREINTE_SURE=0
        EMPREINTE_SOURCE="DÉDUITE du nom : une seule empreinte porte « $BASE » sur cette machine"
    elif [ "${_uniq:-0}" -gt 1 ]; then
        HOMONYME=1
        EMPREINTE_SOURCE="INDÉCIDABLE : $_uniq installations différentes portent le nom « $BASE »"
    fi
fi

titre "0. De quel cerveau parle-t-on ?"
Q=''
if [ -n "$EMPREINTE" ] && [ "$EMPREINTE_SURE" -eq 1 ]; then
    propre "empreinte « $EMPREINTE » — $EMPREINTE_SOURCE"
    cause "c'est elle qui tranche, pas le nom. Un objet qui porte le nom « $BASE » et une AUTRE empreinte appartient à quelqu'un d'autre : ce contrôle le dira, et n'imprimera aucun geste pour lui."
elif [ -n "$EMPREINTE" ]; then
    Q=nom
    RESERVE_IDENTITE=1
    autre "empreinte « $EMPREINTE » — $EMPREINTE_SOURCE"
    cause "ATTESTÉE PAR PERSONNE : elle a été retrouvée EN PARTANT DU NOM, donc elle n'en sait pas plus que lui. Si vous venez d'effacer votre cerveau et qu'un homonyme vit encore ici, cette empreinte est LA SIENNE. Tout ce qui suit porte cette réserve, et les gestes destructeurs se taisent dès qu'un nom devient ambigu."
    cause "pour lever la réserve : « --empreinte <votre uuid> » — elle est dans votre coffre (ARAC_INSTALL_UUID) et dans config/brain.toml."
elif [ "$HOMONYME" -eq 1 ]; then
    Q=nom
    RESERVE_IDENTITE=1
    autre "$EMPREINTE_SOURCE"
    cause "relancez avec « --empreinte <uuid> » — elle est écrite dans votre coffre (ARAC_INSTALL_UUID) et dans config/brain.toml. Sans elle, aucun geste destructeur ne sera imprimé."
else
    Q=nom
    RESERVE_IDENTITE=1
    autre "empreinte inconnue — ni --empreinte, ni environnement, ni coffre, ni description, et aucune plaque à déduire"
    cause "ce contrôle retombe alors sur le NOM SEUL, qui ne prouve rien : deux personnes appellent leur cerveau « perso ». Il a tout de même OUVERT chaque base et chaque archive des endroits listés en fin de rapport — ce qui manque n'est pas la fouille, c'est de quoi distinguer deux homonymes."
fi


# ----------------------------------------------------------------------------
# 1. Les bases — « cette base contient-elle MA mémoire ? »
# ----------------------------------------------------------------------------
#
# ON NE DRESSE PLUS LA LISTE DES NOMS. On ouvre chaque base de chaque grappe et
# on lui demande ce qu'elle porte. Ce qui a été mesuré avec l'ancienne version,
# sur un cerveau réel désinstallé selon le §13 : la section imprimait
# « ✓ aucune base “<base>” ni dérivée » pendant qu'une base nommée
# « copie_de_secours » — née d'une vérification de restauration conservée par
# `--keep`, dont `ARAC_RESTORE_DB` choisit librement le nom — portait les neuf
# souvenirs, en clair. La section 2 la nommait même, comme la raison pour
# laquelle un rôle refusait de mourir, sans jamais dire ce qu'elle contenait.
#
# Le repli par le nom SUBSISTE, en second filet : une base dérivée dont le
# schéma a été détruit ne porte plus de plaque, et elle reste un reste.

titre "1. Bases PostgreSQL — ce qui porte de la mémoire"
BASES_VUES=0
if [ "${#PORTS[@]}" -eq 0 ]; then
    aveugle "aucune grappe PostgreSQL trouvée (ni --port, ni pg_lsclusters)"
elif [ "$SUPER_OK" -eq 0 ]; then
    aveugle "sans sudo, les bases et les rôles ne sont pas lisibles — relancez avec sudo"
else
    for p in "${PORTS[@]}"; do
        # Le quatrième champ est LE GARDE-FOU DU VOISIN DONT LE NOM COMMENCE
        # COMME LE NÔTRE : « bascule » ne possède pas « bascule_deux » parce que
        # leurs noms se ressemblent. Un cerveau installé porte ses cinq rôles
        # « arac_<base>_* » — si celui d'administration existe pour CE nom-là, la
        # base appartient à quelqu'un d'autre. Ce garde ne sert plus quand la
        # plaque répond ; il sert quand elle manque, c'est-à-dire sur les
        # installations d'avant l'empreinte, qui sont exactement celles qu'on ne
        # peut identifier que par leur nom.
        LISTE="$(psql_super "$p" \
            "SELECT d.datname
                 || '|' || pg_get_userbyid(d.datdba)
                 || '|' || pg_size_pretty(pg_database_size(d.datname))
                 || '|' || (EXISTS (SELECT 1 FROM pg_roles r
                                     WHERE r.rolname = 'arac_' || d.datname || '_admin'))::text
               FROM pg_database d
              WHERE d.datallowconn
              ORDER BY 1")"
        if [ -z "$LISTE" ]; then
            aveugle "grappe $p injoignable, ou aucune base lisible"
            continue
        fi
        while IFS='|' read -r d proprio taille est_un_cerveau; do
            [ -z "$d" ] && continue
            # LE CRITÈRE DE FORME. On demande à la base, pas à son nom. TOUT
            # schéma est interrogé, pas seulement celui qui s'appelle « arac » :
            # une copie où le schéma aurait été renommé porte la même plaque au
            # même endroit, et c'est la plaque qui décide.
            PLAQUE="$(psql_dans "$p" "$d" \
                "SELECT coalesce(obj_description(oid,'pg_namespace'),'')
                   FROM pg_namespace
                  WHERE coalesce(obj_description(oid,'pg_namespace'),'') LIKE 'ARAC cerveau=%'
                  ORDER BY nspname LIMIT 1")"
            EMP_D="$(_champ_de "$PLAQUE" empreinte)"
            CERV_D="$(_champ_de "$PLAQUE" cerveau)"

            _derive=0
            case "$d" in "$BASE"|"$BASE"_*) _derive=1 ;; esac

            if [ -n "$EMP_D" ] && [ -n "$EMPREINTE" ] && [ "$EMP_D" = "$EMPREINTE" ]; then
                BASES_VUES=1
                reste "base « $d » sur la grappe $p ($taille, propriétaire : $proprio) — ELLE PORTE VOTRE MÉMOIRE"
                cause "reconnue non pas à son nom mais à l'empreinte gravée dans le commentaire de son schéma : « $PLAQUE ». C'est une copie complète et lisible de ce cerveau."
                cause "$(_origine_de_la_base "$d")"
                if [ "$d" = postgres ] || [ "$d" = template1 ]; then
                    cause "et c'est une base SYSTÈME : on ne la détruit pas, on lui retire le schéma."
                    geste base \
                        "sudo -u postgres psql -p $p -d '$d' -c \"DROP SCHEMA arac CASCADE\"   # relisez d'abord : c'est une base SYSTÈME" "$Q"
                else
                    geste base "sudo -u postgres dropdb -p $p --if-exists '$d'" "$Q"
                fi
                continue
            fi

            if [ -n "$EMP_D" ] && [ -n "$EMPREINTE" ] && [ "$EMP_D" != "$EMPREINTE" ]; then
                # LE VOISIN. Qu'il porte notre nom ou non, sa mémoire n'est pas
                # la nôtre. Le cas où il porte EXACTEMENT notre nom est celui
                # que ce script ne savait pas voir : il ne connaissait que le
                # voisin dont le nom COMMENCE comme le nôtre.
                if [ "$_derive" -eq 1 ]; then
                    HOMONYME=1
                    autre "base « $d » sur la grappe $p — ce n'est PAS votre mémoire, malgré son nom"
                    cause "elle porte l'empreinte $EMP_D (cerveau « ${CERV_D:-?} »), la vôtre est $EMPREINTE. Un nom se partage, une empreinte non. AUCUN geste n'est imprimé pour elle, et si vous en composiez un vous-même, il coûterait la mémoire de quelqu'un d'autre."
                else
                    autre "base « $d » sur la grappe $p — cerveau « ${CERV_D:-?} », empreinte $EMP_D : ce n'est pas le vôtre"
                fi
                continue
            fi

            if [ -n "$EMP_D" ] && [ -z "$EMPREINTE" ]; then
                if [ "$CERV_D" = "$BASE" ]; then
                    BASES_VUES=1
                    EMPREINTE_VUE="${EMPREINTE_VUE:-$EMP_D}"
                    reste "base « $d » sur la grappe $p ($taille) — elle se déclare du cerveau « $CERV_D »"
                    cause "empreinte trouvée dans la base : $EMP_D. Ce contrôle ne connaît pas la vôtre et ne peut donc PAS confirmer que c'est bien celle-ci. Relancez avec « --empreinte $EMP_D » si vous la reconnaissez."
                    geste base "sudo -u postgres dropdb -p $p --if-exists '$d'   # RELISEZ : reconnue sur son nom, pas sur son empreinte" nom
                else
                    autre "base « $d » sur la grappe $p — cerveau « ${CERV_D:-?} » : ce n'est pas celui que vous cherchez"
                fi
                continue
            fi

            # PAS DE PLAQUE. Le second filet, et il est annoncé comme tel.
            [ "$_derive" -eq 0 ] && continue
            # LE VOISIN DONT LE NOM COMMENCE COMME LE NÔTRE, sans plaque pour le
            # dire. On ne le compte pas comme un reste, et surtout on n'imprime
            # pas son dropdb.
            if [ "$d" != "$BASE" ] && [ "$est_un_cerveau" = "true" ]; then
                autre "base « $d » sur la grappe $p — ce n'est pas un reste : c'est le cerveau d'un AUTRE"
                cause "elle ne porte aucune plaque, mais elle porte ses propres rôles « arac_${d}_* ». Aucun geste n'est imprimé pour elle : y toucher coûterait la mémoire du voisin."
                continue
            fi
            BASES_VUES=1
            case "$proprio" in
                arac_"$BASE"_*) RETENU=" Tant qu'elle existe, DROP ROLE $proprio est refusé." ;;
                *)              RETENU="" ;;
            esac
            reste "base « $d » sur la grappe $p ($taille, propriétaire : $proprio)"
            cause "SANS PLAQUE : reconnue sur son NOM SEUL, qui ne prouve rien. Elle est soit antérieure à l'empreinte, soit amputée de son schéma. Regardez ce qu'elle contient avant de la détruire.$RETENU"
            geste base "sudo -u postgres dropdb -p $p --if-exists '$d'   # RELISEZ : reconnue sur son nom, pas sur son empreinte" nom
        done <<< "$LISTE"

        # LE SECOND FILET — LES BASES QU'ON N'A PAS PU OUVRIR.
        #
        # La boucle ci-dessus s'appuie sur `datallowconn` : une base fermée aux
        # connexions ne peut pas être interrogée sur son contenu, donc le
        # critère de forme ne l'atteint pas. C'est le trou exact que laisse
        # « demander à l'objet ce qu'il est » — et une liste de noms, si
        # faillible soit-elle, le couvre. On garde donc les deux : la forme
        # d'abord, le nom en second, et chacun dit ce qu'il vaut.
        FERMEES="$(psql_super "$p" \
            "SELECT d.datname
                 || '|' || pg_get_userbyid(d.datdba)
                 || '|' || pg_size_pretty(pg_database_size(d.datname))
               FROM pg_database d
              WHERE (d.datname = '$BASE' OR d.datname LIKE '${BASE}\\_%')
                AND NOT d.datallowconn
              ORDER BY 1")"
        while IFS='|' read -r d proprio taille; do
            [ -z "$d" ] && continue
            BASES_VUES=1
            reste "base « $d » sur la grappe $p ($taille, propriétaire : $proprio) — FERMÉE aux connexions"
            cause "son nom dérive de celui de ce cerveau, mais « datallowconn = false » interdit de l'ouvrir : ce contrôle n'a PAS pu lire son empreinte. Rouvrez-la pour regarder ce qu'elle contient avant d'en décider — ALTER DATABASE \"$d\" ALLOW_CONNECTIONS true."
            geste base "sudo -u postgres dropdb -p $p --if-exists '$d'   # RELISEZ : reconnue sur son nom, son contenu n'a pas pu être lu" nom
        done <<< "$FERMEES"
    done
    [ "$BASES_VUES" -eq 0 ] && propre "aucune base ne porte la mémoire de ce cerveau sur ${#PORTS[@]} grappe(s) interrogée(s)"
fi


# ----------------------------------------------------------------------------
# 2. Les copies de la mémoire HORS base — dumps, où qu'ils soient
# ----------------------------------------------------------------------------
#
# C'EST LA SECTION QUI MANQUAIT, ET SON ABSENCE FAISAIT MENTIR LE VERDICT.
# L'ancienne version regardait UN répertoire, `/var/backups/arac/<base>`, et
# concluait « ni coffre, ni journaux, ni état, ni dumps ». Or le §13 pose
# lui-même deux copies ailleurs : le dump d'adieu de son étape 2, dans le foyer
# de qui désinstalle et en mode 644 ; et le dossier de dumps que sa branche (a)
# DÉPLACE dans ce même foyer. Aucune des deux ne s'appelle comme le répertoire
# qu'on regardait, et toutes les deux se restaurent — mesuré, souvenir par
# souvenir.
#
# On ne cherche donc plus des NOMS dans un répertoire : on cherche des
# ARCHIVES POSTGRESQL dans un ensemble borné de racines, et on demande à
# chacune de quel cerveau elle vient.

_genre_archive() { # <fichier> → custom | tar | plain | age | (vide)
    local tete=''
    # LES PREMIERS OCTETS SE LISENT SANS SORTIR DU SHELL, et ce n'est pas une
    # coquetterie. Ce contrôle ouvre plusieurs milliers de fichiers : un
    # `head | tr` par fichier, c'est deux processus par fichier, et le rapport
    # mettait une minute à sortir. Un rapport lent est un rapport qu'on
    # n'attend plus. `read -n` lit sans fork, ignore les octets nuls sans
    # broncher, et n'avale que ce qu'on lui demande.
    IFS= read -r -n 24 tete < "$1" 2>/dev/null
    case "$tete" in
        PGDMP*)                   printf 'custom'; return 0 ;;
        toc.dat*)                 printf 'tar';    return 0 ;;
        age-encryption.org/v1*)   printf 'age';    return 0 ;;
    esac
    case "$tete" in
        --*|SET*|\\connect*)
            # Un dump « plain » commence par l'en-tête que pg_dump écrit
            # lui-même. On lit ce début DANS UNE VARIABLE avant de l'interroger :
            # un tube dont le dernier maillon est un filtre rend le code de ce
            # filtre seul, et cette forme-là a déjà rendu des verdicts faux
            # ailleurs dans ce dépôt.
            local debut
            debut="$(head -c 4096 "$1" 2>/dev/null | LC_ALL=C tr -d '\0')"
            grep -q 'PostgreSQL database dump' <<<"$debut" && printf 'plain' ;;
    esac
    return 0
}

_plaque_du_fichier() { # <fichier> <genre> → la ligne COMMENT ON SCHEMA, ou vide
    case "$2" in
        custom|tar) pg_restore -f - --schema-only "$1" 2>/dev/null \
                        | grep -m1 -a "COMMENT ON SCHEMA" ;;
        plain)      grep -m1 -a "COMMENT ON SCHEMA" "$1" 2>/dev/null ;;
        *)          printf '' ;;
    esac
}

# LES RACINES FOUILLÉES. Elles sont bornées, et elles seront IMPRIMÉES avec le
# verdict : c'est ce qui empêche « PROPRE » de vouloir dire plus que ce qui a
# été regardé. Chacune est un endroit que le PRODUIT écrit ou nomme lui-même —
# le répertoire de sauvegarde (en ENTIER, pas seulement notre sous-dossier :
# une copie de notre mémoire posée chez le voisin resterait invisible sinon),
# le foyer de qui désinstalle, les deux répertoires temporaires que
# docs/SAUVEGARDE.md met en garde de ne pas utiliser, et ce clone.
declare -a RACINES=()
_ajouter_racine() { # <chemin>
    local r="$1" x
    [ -n "$r" ] || return 0
    [ -d "$r" ] || return 0
    for x in "${RACINES[@]:-}"; do [ "$x" = "$r" ] && return 0; done
    RACINES+=("$r")
}
_ajouter_racine "/var/backups/arac/"
_ajouter_racine "/var/tmp/"
_ajouter_racine "/tmp/"
_ajouter_racine "$DEPOT"
if [ -n "${SUDO_USER:-}" ]; then
    _foyer="$(getent passwd "$SUDO_USER" 2>/dev/null | cut -d: -f6)"
    _ajouter_racine "$_foyer"
fi
_ajouter_racine "${HOME:-}"
for _f in "${FOUILLES[@]:-}"; do
    [ -z "$_f" ] && continue
    if [ -d "$_f" ]; then _ajouter_racine "$_f"
    else aveugle "--fouiller « $_f » : ce n'est pas un répertoire, il n'a pas été fouillé"
    fi
done

titre "2. Copies de la mémoire hors base (dumps)"
COPIES=0
CHIFFREES_AUTRES=0
if ! command -v pg_restore >/dev/null 2>&1; then
    aveugle "pg_restore absent : le contenu des archives n'a pas pu être lu, seul leur nom l'a été"
fi
for r in "${RACINES[@]:-}"; do
    [ -z "$r" ] && continue
    while IFS= read -r f; do
        [ -z "$f" ] && continue
        [ -r "$f" ] || { aveugle "archive illisible par ce contrôle : « $f »"; continue; }
        genre="$(_genre_archive "$f")"
        [ -z "$genre" ] && continue

        if [ "$genre" = age ]; then
            # LA LIMITE DU CRITÈRE DE FORME, DITE PLUTÔT QUE TUE. Une archive
            # chiffrée ne se lit pas ici : la clé privée ne vit pas sur ce
            # serveur, et c'est tout l'intérêt. Il ne reste que le nom.
            case "$(basename "$f")" in
                *"$BASE"*)
                    COPIES=1
                    reste "archive CHIFFRÉE « $f » ($(stat -c %s "$f" 2>/dev/null) octets, mode $(stat -c %a "$f" 2>/dev/null))"
                    cause "elle porte le nom de ce cerveau. RÉSERVE : chiffrée, son contenu n'est pas lisible ici — c'est le seul cas où ce contrôle juge sur un nom. Si vous détenez la clé, ouvrez-la avant de conclure."
                    geste fichier "sudo rm -f '$f'      # RELISEZ : chiffrée, reconnue sur son nom seul" nom ;;
                *) CHIFFREES_AUTRES=$(( CHIFFREES_AUTRES + 1 )) ;;
            esac
            continue
        fi

        plaque="$(_plaque_du_fichier "$f" "$genre")"
        emp_f="$(_champ_de "$plaque" empreinte)"
        cerv_f="$(_champ_de "$plaque" cerveau)"

        if [ -n "$emp_f" ] && [ -n "$EMPREINTE" ] && [ "$emp_f" = "$EMPREINTE" ]; then
            COPIES=1
            reste "copie complète de la mémoire : « $f » ($(stat -c %s "$f" 2>/dev/null) octets, mode $(stat -c %a "$f" 2>/dev/null))"
            cause "reconnue à l'empreinte qui voyage DANS le fichier, pas à son nom : « $plaque »."
            cause "un dump se restaure : tant qu'il est là, votre mémoire est là. Si vous voulez le garder, sortez-le de cette machine — la garder ici, c'est laisser le cerveau entier sur un serveur dont vous venez de retirer tout ce qui le protégeait."
            geste fichier "sudo rm -f '$f'      # ou SORTEZ-LA de cette machine, puis effacez-la" "$Q"
        elif [ -n "$emp_f" ] && [ -n "$EMPREINTE" ]; then
            [ "$cerv_f" = "$BASE" ] && {
                HOMONYME=1
                autre "archive « $f » — cerveau « $cerv_f » mais empreinte $emp_f : ce n'est PAS votre mémoire, malgré son nom"
            }
        elif [ -n "$emp_f" ] && [ -z "$EMPREINTE" ] && [ "$cerv_f" = "$BASE" ]; then
            COPIES=1
            EMPREINTE_VUE="${EMPREINTE_VUE:-$emp_f}"
            reste "copie complète de la mémoire : « $f » — elle se déclare du cerveau « $cerv_f »"
            cause "empreinte dans le fichier : $emp_f. Ce contrôle ne connaît pas la vôtre — relancez avec « --empreinte $emp_f » si vous la reconnaissez."
            cause "un dump se restaure : tant qu'il est là, votre mémoire est là."
            # LE GESTE QUI MANQUAIT, ET CE QU'IL A COÛTÉ. Cette branche — la
            # plus courante de toutes, celle du lecteur qui suit le §13 sans
            # avoir sous la main l'empreinte de son installation — NOMMAIT une
            # copie complète de la mémoire et n'imprimait AUCUN geste pour elle.
            # Le rapport se fermait alors sur « LES GESTES, DANS L'ORDRE OÙ ILS
            # PASSENT », ses dix lignes de commentaires, et rien : le lecteur
            # recopiait ce qu'on lui donnait, et il lui restait son cerveau
            # entier sur un serveur qu'il croyait rendu propre.
            #
            # Il est marqué « nom » et pas « C », et ce n'est pas une prudence
            # de façade : le fichier déclare bien UNE empreinte, mais ce
            # contrôle n'en connaît aucune à quoi la comparer. Ce qui le
            # rattache à vous n'est donc que le NOM écrit dedans — un homonyme
            # le porterait aussi. Comme tout geste « nom », il se retire tout
            # seul si un homonyme a été vu sur cette machine, et le pourquoi
            # s'imprime alors à sa place.
            geste fichier "sudo rm -f '$f'      # ou SORTEZ-LA de cette machine, puis effacez-la — RELISEZ : reconnue au nom qu'elle déclare, pas à votre empreinte" nom
        elif [ -z "$plaque" ]; then
            # Archive PostgreSQL sans plaque : antérieure à l'empreinte, ou
            # prise sur une autre base. On ne la nomme que si son NOM parle de
            # ce cerveau — sinon ce serait accuser les fichiers du voisin.
            case "$(basename "$f")" in
                *"$BASE"*)
                    COPIES=1
                    reste "archive PostgreSQL SANS empreinte « $f »"
                    cause "elle porte le nom de ce cerveau mais ne déclare aucune empreinte : elle est antérieure à cette version, ou elle vient d'ailleurs. Reconnue sur son NOM SEUL — regardez-la avant de la détruire : pg_restore --list '$f'"
                    geste fichier "sudo rm -f '$f'      # RELISEZ : reconnue sur son nom, pas sur son empreinte" nom ;;
            esac
        fi
    done < <(find "$r" -maxdepth 3 -type f -size +1k ! -type l 2>/dev/null)
done
if [ "$COPIES" -eq 0 ]; then
    propre "aucune archive ne porte la mémoire de ce cerveau dans les ${#RACINES[@]} racine(s) fouillée(s)"
fi
if [ "$CHIFFREES_AUTRES" -gt 0 ]; then
    autre "$CHIFFREES_AUTRES archive(s) chiffrée(s) vues et NON ouvertes : leur nom ne parle pas de ce cerveau, et sans la clé privée ce contrôle ne peut pas en dire plus"
fi


# ----------------------------------------------------------------------------
# 3. Les rôles — la plaque d'abord, le nom ensuite
# ----------------------------------------------------------------------------
#
# C'est ici que le contrôle de la page échouait à faire son métier : il
# imprimait le nom du rôle survivant sans jamais dire pourquoi il survit.
# PostgreSQL, lui, le sait — `pg_shdepend` et `pg_database.datdba` le disent.
#
# ET IL LES RECONNAISSAIT SUR LEUR NOM. Le bootstrap grave pourtant une plaque
# sur chaque rôle, il la relit avant de rouvrir un coffre, et il REFUSE
# l'installation quand un rôle porte le bon nom et la mauvaise empreinte
# (bootstrap/lib/database.sh). Ce script ne l'ouvrait jamais — et composait
# cinq `DROP ROLE` pour un homonyme.
#
# Les candidats ne viennent plus d'un seul motif de nom : toute plaque qui
# déclare « cerveau=<BASE> » désigne un rôle de ce cerveau, même si son nom ne
# dérive de rien — `ARAC_ROLE_PREFIX` se pose dans l'environnement.

titre "3. Rôles PostgreSQL (globaux à la grappe)"
ROLES_VUS=0
if [ "$SUPER_OK" -eq 1 ] && [ "${#PORTS[@]}" -gt 0 ]; then
    for p in "${PORTS[@]}"; do
        ROLES="$(psql_super "$p" \
            "SELECT rolname || '|' || rolcanlogin || '|' || rolcreatedb
                 || '|' || replace(coalesce(shobj_description(oid,'pg_authid'),''), '|', ' ')
               FROM pg_roles
              WHERE rolname LIKE 'arac\\_${BASE}\\_%'
                 OR coalesce(shobj_description(oid,'pg_authid'),'') LIKE 'arac:%'
              ORDER BY 1")"
        [ -z "$ROLES" ] && continue
        while IFS='|' read -r r peut_se_connecter peut_creer plaque; do
            [ -z "$r" ] && continue
            emp_r="$(_champ_de "$plaque" empreinte)"
            cerv_r="$(_champ_de "$plaque" cerveau)"
            _derive_r=0
            case "$r" in arac_"$BASE"_*) _derive_r=1 ;; esac

            # Ni le nom ni la plaque ne parlent de nous : ce rôle est celui d'un
            # autre cerveau, et il n'a rien à faire dans ce rapport.
            [ "$_derive_r" -eq 0 ] && [ "$cerv_r" != "$BASE" ] && continue

            if [ -n "$emp_r" ] && [ -n "$EMPREINTE" ] && [ "$emp_r" != "$EMPREINTE" ]; then
                HOMONYME=1
                autre "rôle « $r » sur la grappe $p — ce rôle porte le nom que vous cherchez et l'empreinte d'une AUTRE installation ($emp_r)"
                cause "ce n'est pas votre cerveau. Aucun geste n'est imprimé pour lui : un DROP ROLE ici coûterait au voisin l'accès à sa propre mémoire, et son mot de passe est dans un coffre qui n'est pas le vôtre."
                continue
            fi

            ROLES_VUS=1
            RESTES=$(( RESTES + 1 ))
            printf '  ✗ rôle « %s » sur la grappe %s' "$r" "$p"
            [ "$peut_se_connecter" = "t" ] && printf ' — PEUT SE CONNECTER'
            [ "$peut_creer" = "t" ]        && printf ', PEUT CRÉER DES BASES'
            printf '\n'

            if [ -z "$emp_r" ]; then
                cause "AUCUNE PLAQUE, ou plaque sans empreinte : reconnu sur son NOM SEUL. C'est le régime dégradé — vérifiez qu'aucun autre cerveau ne vit sur cette machine avant de le détruire (ls -d /etc/arac/*/)."
            elif [ -z "$EMPREINTE" ]; then
                EMPREINTE_VUE="${EMPREINTE_VUE:-$emp_r}"
                cause "il déclare l'empreinte $emp_r (cerveau « ${cerv_r:-?} ») et ce contrôle ne connaît pas la vôtre : relancez avec « --empreinte $emp_r » si vous la reconnaissez."
            else
                cause "plaque vérifiée : empreinte $emp_r — c'est bien un rôle de CETTE installation."
            fi

            # POURQUOI CE RÔLE NE PART PAS. Trois raisons possibles, et le
            # serveur les connaît toutes les trois.
            POSSEDE="$(psql_super "$p" \
                "SELECT string_agg(datname, ', ' ORDER BY datname)
                   FROM pg_database WHERE pg_get_userbyid(datdba) = '$r'")"
            if [ -n "$POSSEDE" ]; then
                cause "il POSSÈDE encore : $POSSEDE — PostgreSQL refusera DROP ROLE tant que ces bases existent (la section 1 dit ce que chacune contient)"
            fi
            DEPS="$(psql_super "$p" \
                "SELECT string_agg(DISTINCT d.datname, ', ')
                   FROM pg_shdepend s
                   JOIN pg_database d ON d.oid = s.dbid
                  WHERE s.refobjid = (SELECT oid FROM pg_roles WHERE rolname = '$r')")"
            if [ -n "$DEPS" ]; then
                cause "des objets lui appartiennent encore dans : $DEPS (REASSIGN OWNED / DROP OWNED, base par base)"
            fi
            if [ -z "$POSSEDE" ] && [ -z "$DEPS" ]; then
                cause "rien ne le retient : DROP ROLE passera. Il a simplement été oublié."
            fi
            if [ "$peut_se_connecter" = "t" ]; then
                cause "son mot de passe vivait dans $ARAC_ETC_DIR/$BASE/ : si ce coffre est effacé, plus personne ne peut ni s'en servir ni le changer"
            fi
            if [ -n "$emp_r" ] && [ -n "$EMPREINTE" ] && [ "$emp_r" = "$EMPREINTE" ]; then
                geste role "sudo -u postgres psql -p $p -c \"DROP ROLE IF EXISTS $r\"" "$Q"
            else
                geste role "sudo -u postgres psql -p $p -c \"DROP ROLE IF EXISTS $r\"   # RELISEZ : reconnu sur son nom, pas sur son empreinte" nom
            fi
        done <<< "$ROLES"
    done
fi
if [ "$SUPER_OK" -eq 0 ]; then
    aveugle "non lus (sudo requis)"
elif [ "$ROLES_VUS" -eq 0 ]; then
    propre "aucun rôle de ce cerveau"
fi


# ----------------------------------------------------------------------------
# 4. Les unités systemd
# ----------------------------------------------------------------------------

titre "4. Unités systemd"
UNITES_VUES=0
if command -v systemctl >/dev/null 2>&1; then
    while read -r u _; do
        [ -z "$u" ] && continue
        case "$u" in ●) continue ;; esac
        UNITES_VUES=1
        reste "unité « $u » encore connue de systemd"
        geste arret "sudo systemctl disable --now '$u'"
    done < <(systemctl list-units --all --no-legend "$PREFIXE_UNITE-*" 2>/dev/null | awk '{print $1}')
    # Un fichier d'unité peut survivre sans être « chargé ».
    #
    # ET IL N'Y A PAS QUE DES FICHIERS. Chaque unité posée par le bootstrap
    # porte, dans son propre en-tête, l'invitation à créer un RÉPERTOIRE :
    #
    #     # Pour la modifier durablement, utilisez un drop-in :
    #     #   sudo systemctl edit arac-<base>-...
    #
    # `systemctl edit` fabrique « arac-<base>-api.service.d/override.conf ».
    # Ce contrôle le voyait — et imprimait `sudo rm -f` dessus, qui rend
    # « cannot remove : Is a directory » et ne retire rien. La toute dernière
    # commande de la désinstallation échouait donc sur l'objet que le produit
    # lui-même invite à créer. Mesuré. Le bootstrap laisse aussi des copies
    # « <unité>.avant-<horodatage> » quand il remplace une unité : elles sont
    # ramassées par le même motif, et pour elles `rm -f` suffit.
    for f in /etc/systemd/system/"$PREFIXE_UNITE"-*; do
        [ -e "$f" ] || continue
        UNITES_VUES=1
        if [ -d "$f" ]; then
            reste "répertoire de réglages « $f » (drop-in)"
            cause "posé par « sudo systemctl edit », que l'en-tête de chaque unité de ce cerveau recommande. Il contient VOS surcharges : lisez-les avant de les perdre."
            geste fichier "sudo rm -rf '$f'"
        else
            reste "fichier d'unité « $f »"
            geste fichier "sudo rm -f '$f'"
        fi
    done
    # LA LIGNE tmpfiles.d QUE ops/systemd/ FAIT POSER. Elle vit dans un
    # répertoire commun à la machine, elle RECRÉE le répertoire de sauvegarde à
    # chaque démarrage, et elle survit à tout le reste : un cerveau désinstallé
    # dont la ligne demeure fait réapparaître son dossier de dumps, vide, à
    # chaque redémarrage — et le §13 ne la nomme nulle part.
    for f in /etc/tmpfiles.d/"$PREFIXE_UNITE"-*.conf; do
        [ -e "$f" ] || continue
        UNITES_VUES=1
        reste "fragment tmpfiles.d « $f »"
        cause "il recrée les répertoires de sauvegarde de ce cerveau à chaque démarrage."
        geste fichier "sudo rm -f '$f'"
    done
    [ "$UNITES_VUES" -eq 1 ] && geste fichier "sudo systemctl daemon-reload"
    [ "$UNITES_VUES" -eq 0 ] && propre "aucune unité « $PREFIXE_UNITE-* », aucun drop-in, aucun fragment tmpfiles.d"
else
    aveugle "systemctl absent"
fi


# ----------------------------------------------------------------------------
# 5. Les estampilles de minuteur
# ----------------------------------------------------------------------------
#
# systemd écrit `stamp-<unité>.timer` pour se rappeler du dernier
# déclenchement (`Persistent=true`). Elles survivent à la suppression des
# unités : une réinstallation homonyme repart alors avec l'horloge du cerveau
# précédent, et une machine qui a vu passer dix cerveaux d'essai accumule dix
# fichiers que plus rien ne nomme.

titre "5. Estampilles de minuteur"
ESTAMPILLES=0
# LE MOTIF PORTE LE NOM DE CE CERVEAU, EN UN SEUL MORCEAU, ET C'EST DÉLIBÉRÉ.
# Écrire le répertoire d'un côté et le nom de l'autre — un `find` avec son
# `-name`, ou un glob qui finit par « *.timer » — laisse dans ce fichier soit
# un chemin commun à la machine, soit un nom d'unité que deux cerveaux se
# partagent. Le garde G1 refuse les deux, et il a raison : un fichier d'ops
# qui contient un nom non suffixé finit par agir dessus.
shopt -s nullglob
for f in "/var/lib/systemd/timers/stamp-$PREFIXE_UNITE-"*; do
    ESTAMPILLES=1
    reste "estampille « $f »"
    geste fichier "sudo rm -f '$f'"
done
shopt -u nullglob
[ "$ESTAMPILLES" -eq 0 ] && propre "aucune estampille « stamp-$PREFIXE_UNITE-… »"


# ----------------------------------------------------------------------------
# 6. Le coffre, les dossiers, les comptes, la description
# ----------------------------------------------------------------------------

titre "6. Coffre, dossiers, comptes et description"
FICHIERS=0
for d in "$ARAC_ETC_DIR/$BASE" \
         "/var/log/arac/$BASE" \
         "/var/lib/arac/$BASE" "/var/lib/arac/$BASE-service" "/var/lib/arac/$BASE-etat" \
         "/var/backups/arac/$BASE"; do
    [ -e "$d" ] || continue
    FICHIERS=1
    if [ "$d" = "/var/backups/arac/$BASE" ]; then
        reste "dossier de sauvegarde « $d »"
        cause "la section 2 dit, fichier par fichier, ce qu'il contient VRAIMENT — c'est elle qui juge, pas ce nom de dossier."
    else
        reste "dossier « $d »"
    fi
    geste fichier "sudo rm -rf '$d'"
done
[ "$FICHIERS" -eq 0 ] && propre "ni coffre, ni journaux, ni état, ni dossier de sauvegarde"

COMPTES=0
while IFS=: read -r nom _; do
    case "$nom" in
        *"$BASE"*)
            COMPTES=1
            reste "compte système « $nom »"
            geste fichier "sudo userdel '$nom'" ;;
    esac
done < /etc/passwd
[ "$COMPTES" -eq 0 ] && propre "aucun compte système portant « $BASE »"

# LA DESCRIPTION DU CERVEAU, RESTÉE DANS LE CLONE. Le §13 ne parle jamais du
# dépôt : il retire la base, les rôles, le coffre, les unités — et laisse dans
# `config/` le nom du propriétaire, l'empreinte de l'installation, l'identifiant
# du poste, et la TAXONOMIE, c'est-à-dire la forme de la mémoire de quelqu'un.
# Ce n'est pas la mémoire elle-même, et c'est pour cela que ce constat vient en
# dernier — mais « il ne reste RIEN de ce cerveau » ne peut pas se dire pendant
# que le fichier qui le décrit est encore lisible.
# ---------------------------------------------------------------------------
# CE CONTRÔLE DISAIT « ABSENTS » DE DEUX FICHIERS QU'IL N'AVAIT JAMAIS REGARDÉS,
# ET L'ORDRE DU §13 GARANTISSAIT QU'IL NE POUVAIT PAS LES REGARDER.
#
# Toute la détection — brain.toml, scopes.toml, la taxonomie ENGENDRÉE, l'état
# du bootstrap — était imbriquée dans un unique `if [ -r brain.toml ]`. Or le
# §13 fait effacer `config/brain.toml` à l'étape 7 et lance ce contrôle à
# l'étape 9 : la branche entière était sautée, `DESCRIPTION` restait à 0, et la
# ligne verte affirmait « ni la taxonomie engendrée (app/schemas/
# scope_generated.py, db/seeds/scopes.sql) » pendant que les deux fichiers
# étaient là, avec la taxonomie en clair, entière. Le contrôle qui prononce le
# départ mentait donc au mot près, STRUCTURELLEMENT : sa conclusion dépendait de
# ce que la procédure venait de détruire.
#
# LA CORRECTION EST DE SÉPARER DEUX QUESTIONS QUI ÉTAIENT CONFONDUES :
#   1. CE FICHIER EST-IL LÀ ?      — chacun est regardé pour lui-même, toujours.
#   2. EST-IL À CE CERVEAU-CI ?    — c'est le RATTACHEMENT, et il peut manquer.
#
# Le rattachement a trois issues, et la troisième est celle qui manquait :
#   · ce clone décrit CE cerveau      → on nomme, on prescrit ;
#   · ce clone décrit un AUTRE cerveau → on ne prescrit RIEN. Prescrire un
#     « rm » sur la taxonomie du voisin est très exactement l'accident que tout
#     ce fichier existe pour empêcher ;
#   · ce clone ne décrit plus personne → les fichiers sont ORPHELINS. On les
#     nomme, on prescrit (leur chemin est sans ambiguïté), et on DIT que le
#     rattachement ne peut plus être attesté. « Je n'ai pas pu vérifier » n'est
#     ni « c'est bon » ni « c'est cassé » : c'est une troisième chose, et elle
#     s'imprime.
#
# Le rattachement se lit sur DEUX objets, pas un : `config/brain.toml`, que
# l'étape 7 efface, et `.bootstrap-state.json`, qu'elle n'efface pas et qui
# porte le même nom de cerveau. Le second survit précisément à l'étape qui
# aveuglait le contrôle.
# ---------------------------------------------------------------------------
DESCRIPTION=0
#: 1 = ce clone décrit ce cerveau-ci · 0 = plus personne · 2 = un AUTRE cerveau
RATTACHE=0
RATTACHE_PAR=''
RATTACHE_AUTRE=''

_nom_normalise() { printf '%s' "$1" | tr -c 'a-zA-Z0-9' '_' | sed 's/_*$//'; }

if [ -r "$DEPOT/config/brain.toml" ]; then
    _n="$(sed -n 's/^ *name *= *"\([^"]*\)".*/\1/p' "$DEPOT/config/brain.toml" | head -1)"
    _n="$(_nom_normalise "$_n")"
    if [ "${_n,,}" = "$BASE" ]; then
        RATTACHE=1; RATTACHE_PAR="config/brain.toml nomme ce cerveau"
    elif [ -n "$_n" ]; then
        RATTACHE=2; RATTACHE_AUTRE="${_n,,}"
    fi
fi
#: L'OBJET QUI SURVIT À L'ÉTAPE 7. `.bootstrap-state.json` porte « nom » —
#: le même nom de cerveau que brain.toml — et le §13 ne l'efface pas. On
#: l'interroge donc quand brain.toml ne peut plus répondre : c'est le même
#: geste que partout ailleurs dans ce fichier, demander à l'objet ce qu'il est.
if [ "$RATTACHE" -eq 0 ] && [ -r "$DEPOT/.bootstrap-state.json" ]; then
    _n="$(sed -n 's/.*"nom"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$DEPOT/.bootstrap-state.json" | head -1)"
    _n="$(_nom_normalise "$_n")"
    if [ "${_n,,}" = "$BASE" ]; then
        RATTACHE=1; RATTACHE_PAR=".bootstrap-state.json nomme ce cerveau"
    elif [ -n "$_n" ]; then
        RATTACHE=2; RATTACHE_AUTRE="${_n,,}"
    fi
fi
#: Dernier indice, et il tient dans un NOM DE FICHIER : l'avancement d'une
#: installation porte la base dans son nom. Plus faible que les deux précédents
#: (un nom, pas une lecture), donc jamais employé pour contredire un objet qui
#: a parlé — seulement pour rattacher quand plus rien ne parle.
if [ "$RATTACHE" -eq 0 ] && [ -e "$DEPOT/.bootstrap-install.$BASE.state" ]; then
    RATTACHE=1; RATTACHE_PAR=".bootstrap-install.$BASE.state porte le nom de ce cerveau"
fi

#: Ce que chaque fichier du clone porte, dit une fois, ici.
_pourquoi_ce_fichier() { # <chemin>
    case "$1" in
        */config/brain.toml)  printf "elle porte le nom du propriétaire, l'empreinte de l'installation et l'identifiant du poste." ;;
        */config/scopes.toml) printf "c'est la TAXONOMIE, la forme de la mémoire, domaine par domaine." ;;
        */scope_generated.py|*/db/seeds/scopes.sql)
            printf "engendré depuis config/scopes.toml au point de contrôle 3 du §3 ; il porte les domaines en clair. Ni empreinte ni souvenir — mais c'est la forme de la mémoire de quelqu'un, et git ne le suit pas : effacer la source ne l'efface pas." ;;
        */.bootstrap-state.json)
            printf "les réponses de l'entretien : le nom du propriétaire, l'empreinte, le poste et la taxonomie entière." ;;
        *) printf "avancement du bootstrap de ce cerveau." ;;
    esac
}

#: On regarde les SIX fichiers, un par un, quoi qu'il arrive. Ce qui change
#: selon le rattachement, c'est ce qu'on en DIT et ce qu'on ose prescrire.
for _f in "$DEPOT/config/brain.toml" \
          "$DEPOT/config/scopes.toml" \
          "$DEPOT/app/schemas/scope_generated.py" \
          "$DEPOT/db/seeds/scopes.sql" \
          "$DEPOT/.bootstrap-install.$BASE.state" \
          "$DEPOT/.bootstrap-state.json"; do
    [ -e "$_f" ] || continue
    DESCRIPTION=1
    case "$RATTACHE" in
        1)
            reste "dans ce clone : « $_f »"
            cause "$(_pourquoi_ce_fichier "$_f")"
            geste fichier "rm -f '$_f'"
            ;;
        2)
            autre "dans ce clone : « $_f » — mais ce clone décrit « $RATTACHE_AUTRE », pas « $BASE »"
            cause "ce n'est PAS un reste de votre cerveau, et ce contrôle ne prescrit rien dessus : le « rm » composé ici effacerait la description du cerveau de quelqu'un d'autre."
            DESCRIPTION=2
            ;;
        *)
            reste "dans ce clone, ORPHELIN : « $_f »"
            cause "$(_pourquoi_ce_fichier "$_f")"
            cause "RATTACHEMENT NON ATTESTÉ : ni « config/brain.toml » ni « .bootstrap-state.json » ne nomme plus de cerveau dans ce clone — l'étape 7 du §13 efface le premier. Ce fichier est là, et ce contrôle ne peut plus dire DE QUI il est. Il ne conclut donc ni « c'est à vous » ni « ce n'est pas à vous » : il le nomme, et vous laissez juger. Le geste ci-dessous vise un chemin sans ambiguïté, dans le clone où vous êtes."
            geste fichier "rm -f '$_f'"
            ;;
    esac
done

# UN « ✓ » QUI N'ÉNUMÈRE PAS CE QU'IL A REGARDÉ EST LA FORME DE SILENCE QUE CE
# DÉPÔT CONDAMNE AILLEURS — et un « ✓ » qui énumère ce qu'il n'a PAS regardé
# est pire : c'est celui-ci qui a dit « ni la taxonomie engendrée » sans jamais
# ouvrir les yeux dessus. La phrase ne nomme donc que des fichiers dont
# l'absence vient d'être constatée, un par un, à l'instant.
[ "$DESCRIPTION" -eq 0 ] && propre "ce clone ne décrit plus ce cerveau : ni brain.toml, ni scopes.toml, ni la taxonomie engendrée (app/schemas/scope_generated.py, db/seeds/scopes.sql), ni l'avancement (.bootstrap-install.$BASE.state, .bootstrap-state.json) — les six regardés un par un"
[ "$DESCRIPTION" -eq 2 ] && propre "aucun fichier de CE cerveau dans ce clone : il décrit « $RATTACHE_AUTRE »"


# ----------------------------------------------------------------------------
# 7. Le journal système — l'endroit où personne ne pense à chercher sa mémoire
# ----------------------------------------------------------------------------
#
# CE CONTRÔLE NE REGARDAIT PAS LÀ. `grep -c journalctl ops/uninstall_check.sh`
# rendait 0, et dans tout le §13 le mot « journal » ne désignait que
# `/var/log/arac/<base>/`. Pendant ce temps, `arac-<base>-restauration.service`
# — armé par le bootstrap, déclenché chaque dimanche par sa minuterie, et que
# `docs/SAUVEGARDE.md` §7 étape 6 fait lancer à la main — imprimait la CLÉ et le
# DOMAINE de trois souvenirs dans journald. Un §13 joué mot pour mot, un
# « VERDICT : PROPRE » en code 0, et la mémoire encore lisible par tout compte
# du groupe « systemd-journal », pendant des semaines. La source est tarie
# (`ops/restore_verify.sh` n'écrit plus que des empreintes) ; ce qu'un journal a
# déjà avalé, lui, ne se rattrape pas — d'où cette section.
#
# CE QUE SYSTEMD SAIT FAIRE, ET CE QU'IL NE SAIT PAS.
# Il ne sait PAS effacer les entrées d'une seule unité : `--vacuum-size`,
# `--vacuum-time` et `--vacuum-files` travaillent sur des FICHIERS de journal,
# et un fichier de journal porte tout ce que la machine a écrit pendant sa
# période — donc aussi le cerveau du voisin, et le reste des services. Il n'y a
# donc rien à prescrire ici qui soit à la fois efficace et borné à ce cerveau,
# et ce contrôle ne prescrira pas un geste qui déborde sur autrui. Ce qu'il
# peut faire, il le fait : REGARDER, COMPTER, NOMMER, et dire la vérité sur ce
# qui reste.
#
# C'est la raison pour laquelle la vraie correction est en amont : ce que le
# produit écrit dans journald doit pouvoir Y RESTER — des comptes, des
# empreintes, des identifiants d'unités. Une donnée qu'on n'écrit pas est une
# donnée qu'on n'a pas à effacer.

titre "7. Le journal système"
JOURNAL_VU=0
if ! command -v journalctl >/dev/null 2>&1; then
    aveugle "journalctl absent : ce contrôle ne peut pas dire ce que le journal garde de ce cerveau"
elif ! journalctl -n 0 --quiet >/dev/null 2>&1; then
    aveugle "journal illisible depuis ce compte (il faut root, ou le groupe « systemd-journal ») — ce contrôle ne peut pas dire ce que le journal garde de ce cerveau"
else
    #: Le motif porte le nom de ce cerveau EN UN SEUL MORCEAU — même raison
    #: qu'aux estampilles : « arac-*-restauration » nommerait les unités de
    #: toute la machine, et ce fichier n'écrit jamais un nom que deux cerveaux
    #: se partagent.
    #: `--quiet` retire les lignes d'information de journalctl lui-même
    #: (« -- Journal begins at … »), qui feraient compter une ligne là où le
    #: journal est vide — un « il reste quelque chose » sur du vent.
    _J_LIGNES="$(journalctl --quiet -u "$PREFIXE_UNITE-*" --no-pager -o cat 2>/dev/null | wc -l)"
    _J_DEPUIS="$(journalctl --quiet -u "$PREFIXE_UNITE-*" --no-pager -o short-iso 2>/dev/null | grep -m1 '^[0-9]' | cut -d' ' -f1)"
    if [ "${_J_LIGNES:-0}" -eq 0 ]; then
        propre "le journal ne garde aucune ligne des unités « $PREFIXE_UNITE-* »"
    else
        JOURNAL_VU=1
        autre "le journal garde ${_J_LIGNES} ligne(s) des unités « $PREFIXE_UNITE-* »${_J_DEPUIS:+, depuis le $_J_DEPUIS}"
        #: LE RÉGLAGE EST NOMMÉ, SON FICHIER NON — et c'est G1 qui l'exige.
        #: Écrire ici le chemin de la configuration de journald ferait entrer
        #: dans un fichier d'ops un chemin de la MACHINE, que tous les cerveaux
        #: se partagent : la forme exacte que ce dépôt refuse partout ailleurs.
        #: « SystemMaxUse » et « MaxRetentionSec » se trouvent par
        #: « man journald.conf », qui dit aussi où ils se posent.
        cause "systemd ne sait pas effacer les entrées d'UNE unité : « journalctl --vacuum-* » travaille sur des fichiers de journal, et ces fichiers portent aussi le journal des autres services et, sur une machine à plusieurs cerveaux, celui du voisin. Ces lignes partiront avec la rotation du journal, à la date que fixent « SystemMaxUse » et « MaxRetentionSec » (voir « man journald.conf »)."
        #: LA SIGNATURE DE LA FUITE CONNUE. Jusqu'à cette version,
        #: `ops/restore_verify.sh` imprimait « échantillon d'atomes réellement
        #: relus : » puis, ligne par ligne, la clé et le domaine de trois
        #: souvenirs. Un cerveau installé avant la correction a donc, dans le
        #: journal, de la mémoire en clair — et c'est la seule chose qui, ici,
        #: se cherche à coup sûr : on connaît le texte exact qu'on a écrit.
        #:
        #: ON RETIENT AVANT DE CHERCHER, ET CE N'EST PAS UN DÉTAIL DE STYLE.
        #: Une recherche silencieuse placée au bout d'un tuyau sort au premier
        #: succès et casse la conduite sous son producteur : le code de retour
        #: dépend alors de qui meurt le premier, donc de la taille du journal et
        #: de l'ordonnanceur. Un contrôle qui prononce un départ ne se joue pas
        #: aux dés. On retient la sortie, puis on cherche dedans — c'est la
        #: forme que `tests/test_le_juge_ne_tire_pas_au_sort.py` exige.
        _J_RESTAURATION="$(journalctl --quiet -u "$PREFIXE_UNITE-restauration.service" --no-pager -o cat 2>/dev/null)"
        if grep -qF "échantillon d'atomes réellement relus :" <<<"$_J_RESTAURATION"; then
            reste "le journal porte des CLÉS et des DOMAINES de vos souvenirs, en clair"
            SANS_GESTE=$(( SANS_GESTE + 1 ))
            cause "écrits par « ops/restore_verify.sh » d'AVANT cette version, sous l'unité « $PREFIXE_UNITE-restauration.service ». Pour les relire : journalctl -u $PREFIXE_UNITE-restauration.service --no-pager | grep -A4 'échantillon d.atomes'"
            cause "AUCUN GESTE N'EST PRESCRIT, et ce n'est pas une négligence : il n'en existe aucun qui efface ces lignes sans emporter le journal des autres services de cette machine. Si ce serveur ne porte que ce cerveau et que vous le rendez, la seule purge complète est « sudo journalctl --rotate && sudo journalctl --vacuum-time=1s » — elle vide le journal de TOUTE la machine, elle ne se limite pas à ARAC, et c'est à vous de décider, pas à ce contrôle."
        else
            propre "aucune clé, aucun domaine de souvenir dans le journal de ces unités (la signature de la fuite d'avant cette version est absente)"
        fi
    fi
fi


# ----------------------------------------------------------------------------
# 8. Le verdict, ses BORNES, et les gestes
# ----------------------------------------------------------------------------

printf '\n'
printf 'CE QUI A ÉTÉ REGARDÉ — un verdict ne vaut jamais plus que son périmètre\n'
if [ "${#PORTS[@]}" -gt 0 ]; then
    printf '  grappes  : %s\n' "$(printf '%s ' "${PORTS[@]}")"
else
    printf '  grappes  : aucune\n'
fi
printf '  racines  : %s\n' "$(printf '%s ' "${RACINES[@]:-aucune}")"
printf '  journal  : les unités « %s-* », dans le journal système\n' "$PREFIXE_UNITE"
printf '  critère  : l%sempreinte gravée dans l%sobjet (schéma, plaque de rôle, en-tête de dump), pas le nom.\n' "'" "'"
printf '             Pour ajouter un endroit : --fouiller <dir>. Les archives chiffrées ne se lisent pas ici.\n'
printf '\n'

if [ "$RESTES" -eq 0 ]; then
    if [ "$PARTIEL" -eq 1 ]; then
        printf 'VERDICT : RIEN DE VISIBLE — mais ce contrôle n%s pas tout vu (lignes « ? »).\n' "'a"
        exit 2
    fi
    if [ "$RESERVE_IDENTITE" -eq 1 ]; then
        printf 'VERDICT : PROPRE — rien de ce cerveau aux endroits ci-dessus, dumps compris.\n'
        printf '          RÉSERVE : l%sempreinte de cette installation n%sa pas pu être attestée. Chaque base\n' "'" "'"
        printf '          et chaque archive ont bien été OUVERTES et interrogées ; c%sest la distinction entre\n' "'"
        printf '          deux cerveaux HOMONYMES qui manque. Pour la lever : --empreinte <votre uuid>.\n'
    else
        printf 'VERDICT : PROPRE — rien de ce cerveau aux endroits ci-dessus, dumps compris.\n'
    fi
    exit 0
fi

printf 'VERDICT : %d RESTE(S). Une désinstallation qui ne se vérifie pas n%s pas une.\n' \
    "$RESTES" "'en est"

if [ "$GESTES" -eq 1 ]; then
    # CE QU'ON S'AUTORISE À PRESCRIRE, ET SUR QUELLE PREUVE.
    #
    # Un geste marqué « C » vise un objet reconnu à l'EMPREINTE gravée dedans :
    # aucun homonyme ne peut s'y glisser, il s'imprime toujours. Un geste
    # marqué « N » vise un objet reconnu sur son NOM. Celui-là se tait dans
    # deux cas, et deux seulement :
    #   · un homonyme a été vu sur cette machine — un nom ne prouve alors plus
    #     rien, et c'est l'accident que tout ce fichier existe pour empêcher ;
    #   · la grappe n'a pas été désignée alors que la machine en porte
    #     plusieurs : un « dropdb » ne se prescrit pas au hasard des serveurs.
    SUR_NOM_OK=1
    RAISON_RETENUE=''
    if [ "$HOMONYME" -eq 1 ]; then
        SUR_NOM_OK=0
        RAISON_RETENUE="homonyme"
    elif [ -z "$PORT" ] && [ "${#PORTS[@]}" -gt 1 ]; then
        SUR_NOM_OK=0
        RAISON_RETENUE="grappe"
    fi

    # ON COMPTE AVANT D'ANNONCER, ET C'EST TOUTE LA CORRECTION.
    #
    # L'en-tête « LES GESTES, DANS L'ORDRE OÙ ILS PASSENT » et ses dix lignes
    # sur l'ordre des quatre temps s'imprimaient dès qu'on demandait `--gestes`,
    # AVANT de savoir s'il y aurait un seul geste à mettre dessous. Mesuré : un
    # verdict rouge qui NOMME une copie complète de la mémoire, l'en-tête, les
    # commentaires — et pas une commande. Le lecteur qui suit ce qu'on lui donne
    # repart avec son cerveau entier sur le serveur qu'il vient de rendre.
    #
    # Une liste vide n'est pas une liste : c'est une question sans réponse. On
    # compte donc d'abord, et s'il n'y a rien à écrire on écrit POURQUOI.
    A_IMPRIMER=0
    A_RETENIR=0
    for _g in "${GESTES_ARRET[@]:-}" "${GESTES_BASE[@]:-}" \
              "${GESTES_ROLE[@]:-}" "${GESTES_FICHIER[@]:-}"; do
        [ -z "$_g" ] && continue
        case "$_g" in
            C*) A_IMPRIMER=$(( A_IMPRIMER + 1 )) ;;
            N*) if [ "$SUR_NOM_OK" -eq 1 ]; then A_IMPRIMER=$(( A_IMPRIMER + 1 ))
                else A_RETENIR=$(( A_RETENIR + 1 )); fi ;;
        esac
    done
fi

if [ "$GESTES" -eq 1 ] && [ "$A_IMPRIMER" -eq 0 ]; then
    printf '\nAUCUN GESTE N%sEST IMPRIMÉ — ET VOICI POURQUOI.\n' "'"
    printf '%s\n' '─────────────────────────────────────────'
    if [ "$A_RETENIR" -gt 0 ] && [ "$RAISON_RETENUE" = homonyme ]; then
        printf '%s\n' \
"# Les $RESTES reste(s) ci-dessus n'ont PAS été reconnus à votre empreinte —
# seulement au nom « $BASE » — et ce contrôle a vu sur cette machine la mémoire
# d'un AUTRE cerveau portant ce même nom. Un « dropdb » ou un « rm » composé à
# partir d'un nom ne saurait pas distinguer les deux : c'est très exactement
# l'accident que ce fichier existe pour empêcher, et il se tait plutôt que de
# le provoquer.
#
# Donnez-lui de quoi trancher :
#     ops/uninstall_check.sh $BASE${PORT:+ --port $PORT} --empreinte <votre uuid> --gestes
# Elle est écrite dans votre coffre (ARAC_INSTALL_UUID) et dans
# config/brain.toml. Sans elle, aucune machine ne peut trancher à votre place."
    elif [ "$A_RETENIR" -gt 0 ]; then
        printf '%s\n' \
"# Les $RESTES reste(s) ci-dessus ont été reconnus à leur NOM, pas à votre
# empreinte, et cette machine porte plusieurs grappes PostgreSQL dont aucune
# n'a été désignée. Un « dropdb » ne se prescrit pas au hasard des serveurs :
# les rôles y sont globaux, et deux grappes portent souvent deux cerveaux.
# La DÉTECTION, elle, a bien eu lieu partout — c'est ce que vous venez de lire.
#
# Relancez en désignant la vôtre :
#     ops/uninstall_check.sh $BASE --port <le port de VOTRE grappe> --gestes
# Il est écrit dans votre coffre : ARAC_DB_PORT."
    elif [ "$SANS_GESTE" -gt 0 ] && [ "$SANS_GESTE" -eq "$RESTES" ]; then
        # NI UNE PRUDENCE, NI UN DÉFAUT : LE SYSTÈME N'OFFRE RIEN.
        # Le seul reste de cette famille est le journal système, et la raison
        # est imprimée avec lui, à sa ligne. Répéter ici « c'est un DÉFAUT de
        # ops/uninstall_check.sh » enverrait chercher un bug dans ce fichier au
        # lieu de lire la contrainte réelle — accuser le mauvais coupable coûte
        # plus cher que se taire.
        printf '%s\n' \
"# Le ou les $RESTES reste(s) ci-dessus n'ont AUCUN geste qui soit borné à ce
# cerveau — la raison est imprimée avec chacun d'eux, à sa ligne. Ce n'est ni
# une prudence de ce contrôle ni un défaut : c'est ce que le système ne sait
# pas faire. Ne composez pas la commande vous-même : celles qui existent
# emportent le journal des autres services de cette machine."
    else
        # CE CAS-LÀ EST UN DÉFAUT DE CE FICHIER, ET IL SE DÉNONCE LUI-MÊME.
        # Chaque reste nommé plus haut doit porter son geste ; s'il n'y en a
        # aucun et que rien n'a été retenu, ce n'est pas le lecteur qui a mal
        # fait, c'est ce contrôle qui a nommé un reste sans savoir quoi en dire.
        # Le taire, c'est rendre un rapport rouge sans issue — c'est ce qui est
        # arrivé à la copie de mémoire de la section 2, pendant deux versions.
        printf '%s\n' \
"# $RESTES reste(s) ont été nommés ci-dessus et ce contrôle n'a su prescrire
# AUCUN geste pour eux. Ce n'est pas une prudence : c'est un DÉFAUT de
# ops/uninstall_check.sh, qui doit servir un geste pour chaque reste qu'il
# nomme. Ne composez pas la commande vous-même à partir du nom : c'est le
# geste par lequel on détruit la mémoire d'un voisin. Signalez ce rapport."
    fi
    printf '\n'
    printf '%s\n' "# puis, pour vérifier :  ops/uninstall_check.sh $BASE${PORT:+ --port $PORT}${EMPREINTE:+ --empreinte $EMPREINTE}"
elif [ "$GESTES" -eq 1 ]; then
    printf '\nLES GESTES, DANS L%s ORDRE OÙ ILS PASSENT\n' "'"
    printf '%s\n' '─────────────────────────────────────────'
    printf '%s\n' \
"# Cet ordre n'est pas décoratif, et il a QUATRE temps — chacun débloque le
# suivant. On ARRÊTE d'abord : tant qu'un service de ce cerveau parle à sa
# base, « dropdb » rend « database is being accessed by other users ». Les
# bases ensuite : tant qu'un rôle en possède une, « DROP ROLE » est refusé.
# Les rôles après. Les fichiers en dernier — retirer l'unité avant de l'avoir
# arrêtée laisse un service vivant que plus rien ne nomme.
#
# LISEZ-LES AVANT DE LES PASSER : les rôles sont globaux à la grappe, et sur
# une machine à plusieurs cerveaux une erreur de nom coûte la mémoire du
# voisin. Ce script ne les exécute pas à votre place, et c'est délibéré."
    printf '\n'
    # La qualité de chaque geste (« C » ou « N ») et ce qu'elle autorise sont
    # décidées plus haut, AVANT l'en-tête : c'est ce comptage préalable qui
    # permet de ne pas annoncer une liste qui serait vide.
    #
    # `printf '%s\n' "${TAB[@]}"` sur un tableau VIDE imprime une ligne vide —
    # une commande fantôme au milieu d'un bloc qu'on copie sans réfléchir.
    _bloc() { # <titre> <commandes qualifiées...>
        local titre="$1" g; shift
        local -a lignes=()
        for g in "$@"; do
            case "$g" in
                C*) lignes+=("${g#*$'\t'}") ;;
                N*) if [ "$SUR_NOM_OK" -eq 1 ]; then lignes+=("${g#*$'\t'}")
                    else RETENUS=$(( RETENUS + 1 )); fi ;;
            esac
        done
        [ "${#lignes[@]}" -eq 0 ] && return 0
        printf '# %s\n' "$titre"
        printf '%s\n' "${lignes[@]}"
        printf '\n'
    }
    _bloc "1. ARRÊTER — sinon la base ne se détruit pas" "${GESTES_ARRET[@]}"
    _bloc "2. LES BASES — sinon les rôles ne se détruisent pas" "${GESTES_BASE[@]}"
    _bloc "3. LES RÔLES — globaux à la grappe : relisez chaque nom" "${GESTES_ROLE[@]}"
    _bloc "4. LES FICHIERS, LES COPIES, LE COFFRE, LES COMPTES" "${GESTES_FICHIER[@]}"

    if [ "$RETENUS" -gt 0 ]; then
        if [ "$RAISON_RETENUE" = homonyme ]; then
            printf '%s\n\n' \
"# $RETENUS GESTE(S) RETENU(S), ET VOICI POURQUOI.
#
# Ce contrôle a vu, sur cette machine, la mémoire d'un AUTRE cerveau portant le
# nom « $BASE ». Les objets que voici n'ont PAS été reconnus à votre empreinte —
# seulement à leur nom — et un « dropdb » composé à partir d'un nom ne saurait
# pas distinguer les deux. C'est très exactement l'accident que ce fichier
# existe pour empêcher.
#
# Ce qui a été reconnu à VOTRE empreinte, lui, est imprimé ci-dessus : une
# empreinte ne se partage pas.
#
# Pour le reste, donnez-lui la vôtre :
#     ops/uninstall_check.sh $BASE --port <le vôtre> --empreinte <votre uuid> --gestes
# Elle est écrite dans votre coffre (ARAC_INSTALL_UUID) et dans
# config/brain.toml. Sans elle, aucune machine ne peut trancher à votre place."
        else
            printf '%s\n\n' \
"# $RETENUS GESTE(S) RETENU(S), ET VOICI POURQUOI.
#
# Cette machine porte plusieurs grappes PostgreSQL et vous n'en avez désigné
# aucune. Les objets concernés n'ont pas été reconnus à votre empreinte, mais à
# leur nom : un « dropdb » ne se prescrit pas au hasard des serveurs, où les
# rôles sont globaux et où deux grappes portent souvent deux cerveaux. La
# DÉTECTION, elle, a bien eu lieu partout — c'est ce que vous venez de lire.
#
# Relancez en désignant la vôtre :
#     ops/uninstall_check.sh $BASE --port <le port de VOTRE grappe> --gestes
# Il est écrit dans votre coffre : ARAC_DB_PORT."
        fi
    fi
    printf '%s\n' "# puis, pour vérifier :  ops/uninstall_check.sh $BASE${PORT:+ --port $PORT}${EMPREINTE:+ --empreinte $EMPREINTE}"
else
    # UN OUTIL QUI SE CITE LUI-MÊME DOIT SE CITER ENTIER.
    #
    # Cette ligne recopiait la base et le port de l'invocation en cours et
    # LAISSAIT TOMBER `--empreinte` — alors que l'empreinte est ce que ce
    # rapport déclare décisif deux écrans plus haut : « c'est elle qui tranche,
    # pas le nom ». Sans elle, la commande proposée retombe sur le nom seul et
    # rend une liste de gestes amputée. Mesuré : avec l'empreinte, quatre
    # gestes dont l'adieu ; sans, un seul.
    printf '\nPour les commandes exactes, dans le bon ordre :\n'
    printf '    ops/uninstall_check.sh %s%s%s --gestes\n' \
        "$BASE" "${PORT:+ --port $PORT}" "${EMPREINTE:+ --empreinte $EMPREINTE}"
    # ET QUAND L'APPELANT N'A PAS D'EMPREINTE MAIS QUE LES OBJETS EN PORTENT
    # UNE. On l'imprime à part, jamais dans la commande : la reconnaître est un
    # acte de l'opérateur, pas une déduction de ce script. La glisser dans la
    # ligne qu'on copie ferait passer une reconnaissance PAR LE NOM pour une
    # certitude par l'empreinte — et c'est ainsi qu'on détruit un homonyme.
    if [ -z "$EMPREINTE" ] && [ -n "$EMPREINTE_VUE" ]; then
        printf '\n'
        printf 'Les objets ci-dessus déclarent l%sempreinte %s. SI vous la reconnaissez pour\n' "'" "$EMPREINTE_VUE"
        printf 'la vôtre — elle est dans votre coffre (ARAC_INSTALL_UUID) et dans\n'
        printf 'config/brain.toml — ajoutez « --empreinte %s » : les gestes cessent\n' "$EMPREINTE_VUE"
        printf 'alors de reposer sur un nom, et aucun homonyme ne peut plus s%sy glisser.\n' "'"
    fi
fi
exit 1
