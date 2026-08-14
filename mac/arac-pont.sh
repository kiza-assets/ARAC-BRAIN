#!/usr/bin/env bash
# ============================================================================
# arac-pont.sh — installer, ouvrir et diagnostiquer le pont entre votre
#                machine et votre cerveau.
#
# Le pont est le maillon que personne ne comprend spontanément, et celui qui
# casse le plus souvent. Ce script existe pour qu'il soit VISIBLE : chaque
# commande dit ce qu'elle va faire avant de le faire, et `etat` répond à la
# seule question qui compte quand plus rien n'arrive — « lequel des maillons
# est cassé ? ».
#
# Il n'installe rien à votre insu, ne modifie aucun fichier système, et ne
# demande jamais les droits d'administrateur.
#
#   arac-pont.sh installer          prépare ~/.arac et pose la configuration
#   arac-pont.sh cle-ssh            fabrique la clé du tunnel
#   arac-pont.sh tunnel ouvrir      ouvre le tunnel (au premier plan)
#   arac-pont.sh etat               le diagnostic, maillon par maillon
#   arac-pont.sh premiere-synchro   le trajet complet, raconté
#   arac-pont.sh automatiser        confie tunnel + synchro à launchd
#   arac-pont.sh journal            regarde passer les événements
#   arac-pont.sh desinstaller       retire launchd, ne touche pas aux données
#
# Compatible avec le bash 3.2 livré par macOS (aucune syntaxe de bash 4+).
# ============================================================================

set -uo pipefail

VERSION="1.0"
ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# ---------------------------------------------------------------------------
# DE QUEL CERVEAU CE PONT EST-IL LE PONT ?
#
# Tout ce qui suit — dossier d'état, configuration, jeton, journal, étiquettes
# launchd, fichiers de log — portait un nom FIXE. Un même Mac pilote pourtant
# très naturellement deux cerveaux (le personnel et celui d'un projet), et
# rien ne les séparait :
#
#   · une étiquette launchd est UNIQUE par session macOS : le second
#     `launchctl bootstrap` remplaçait l'agent du premier, dont la
#     synchronisation cessait sans une erreur ;
#   · ~/.arac/etat-pont.json est le CURSEUR : partagé, le pont du second y
#     marquait « déjà envoyées » des conversations que le premier n'avait
#     jamais reçues. Elles ne repartaient plus jamais. C'est la seule perte
#     silencieuse et définitive du système.
#
# Le cerveau se choisit par $ARAC_CERVEAU, par --cerveau, ou — s'il n'y en a
# qu'un de configuré — tout seul. Plusieurs, et rien pour trancher : on refuse
# en les nommant, plutôt que de choisir dans quelle mémoire déposer des
# conversations privées.
# ---------------------------------------------------------------------------
FOYER_ARAC="$HOME/.arac"
ARAC_CERVEAU="${ARAC_CERVEAU:-}"
# CE QU'ON A DEMANDÉ, PAS CE QU'ON A DÉDUIT. `resoudre_cerveau` écrase
# `ARAC_CERVEAU` avec « l'unique » quand il n'y en a qu'un — et `installer`,
# qui sert justement à en ajouter un SECOND, proposerait alors le nom du
# premier comme valeur par défaut. On garde donc la demande explicite à part.
ARAC_CERVEAU_DEMANDE="$ARAC_CERVEAU"

assainir_cerveau() {
    printf '%s' "$1" | tr -c 'a-zA-Z0-9' '_' | sed 's/^_*//; s/_*$//' | tr 'A-Z' 'a-z'
}

cerveaux_connus() {
    [ -d "$FOYER_ARAC" ] || return 0
    for d in "$FOYER_ARAC"/*/; do
        [ -f "$d/pont.conf" ] || continue
        basename "$d"
    done
}

# UN FOYER COMMUN HABITÉ EST UN CERVEAU, MÊME S'IL N'A PAS DE NOM.
#
# `cerveaux_connus` n'énumère que les SOUS-DOSSIERS : un cerveau n'existait à
# ses yeux qu'APRÈS avoir été correctement installé. Or `installer` ne
# demandait pas le nom du cerveau, et posait donc sa configuration dans
# `~/.arac` NU. Chez celui qui avait suivi la première commande du mode
# d'emploi, l'énumération rendait zéro : le refus de deviner ne s'armait
# jamais, `ARAC_DIR` retombait encore sur le foyer commun, et le SECOND
# cerveau s'installait par-dessus le premier — même curseur, même jeton,
# même étiquette launchd — sans un message.
#
# `installer` nomme désormais toujours (voir `commande_installer`). Reste le
# poste installé AVANT ce correctif : son `~/.arac/pont.conf` existe et
# fonctionne, on ne le casse pas. On le COMPTE, ce qui suffit à armer le
# refus dès qu'un second cerveau apparaît à côté de lui.
foyer_commun_habite() { [ -f "$FOYER_ARAC/pont.conf" ]; }

# Les quatre chemins qui DOIVENT être propres à un cerveau — le jeton,
# l'export, le CURSEUR et le journal. Ils se recalculent dès que le cerveau
# change, c'est-à-dire quand `installer` vient d'en apprendre le nom.
defauts_du_cerveau() {
    ARAC_TOKEN_FILE="$ARAC_DIR/jeton_ingest"
    ARAC_DESKTOP_EXPORT="$ARAC_DIR/export-desktop/conversations.json"
    ARAC_STATE_FILE="$ARAC_DIR/etat-pont.json"
    ARAC_LOG_FILE="$ARAC_DIR/journal/arac-pont.log"
}

resoudre_cerveau() {
    if [ -n "$ARAC_CERVEAU" ]; then
        ARAC_CERVEAU="$(assainir_cerveau "$ARAC_CERVEAU")"
    else
        set -- $(cerveaux_connus)
        commun=0; foyer_commun_habite && commun=1
        total=$(( $# + commun ))
        if [ "$total" -gt 1 ]; then
            mal "Ce poste pilote plusieurs cerveaux ; lequel ?"
            [ "$#" -gt 0 ] && note "  $*"
            [ "$commun" -eq 1 ] && note "  ~/.arac  (le foyer COMMUN, posé avant le cloisonnement par cerveau)"
            note "Précisez :  ARAC_CERVEAU=<nom> $0 <commande>"
            note "Sans cela, le pont devrait choisir DANS QUELLE MÉMOIRE déposer"
            note "vos conversations. Il refuse de choisir à votre place."
            exit 2
        elif [ "$#" -eq 1 ]; then
            ARAC_CERVEAU="$1"
        else
            # Zéro cerveau (`installer` va en créer un, et il demandera son
            # nom), ou le seul foyer commun d'une installation antérieure au
            # cloisonnement — qu'on laisse fonctionner tel quel.
            ARAC_CERVEAU=""
        fi
    fi
    ARAC_DIR="$FOYER_ARAC${ARAC_CERVEAU:+/$ARAC_CERVEAU}"
    CONF="$ARAC_DIR/pont.conf"
    ETIQUETTE_SYNC="com.arac.${ARAC_CERVEAU:-sans-cerveau}.pont.sync"
    ETIQUETTE_TUNNEL="com.arac.${ARAC_CERVEAU:-sans-cerveau}.pont.tunnel"
    JOURNAL_TUNNEL="$HOME/Library/Logs/arac-pont-${ARAC_CERVEAU:-sans-cerveau}-tunnel.log"
}

AGENTS="$HOME/Library/LaunchAgents"

# ---------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------
if [ -t 1 ] && [ -z "${ARAC_SANS_COULEUR:-}" ]; then
    G=$'\033[1m'; N=$'\033[0m'; V=$'\033[32m'; R=$'\033[31m'; J=$'\033[33m'; F=$'\033[2m'
else
    G=""; N=""; V=""; R=""; J=""; F=""
fi

dire()   { printf '%s\n' "$*"; }
vide()   { printf '\n'; }
titre()  { vide; printf '%s%s%s\n' "$G" "$*" "$N"; printf '%s\n' "  ────────────────────────────────────────────────────────────────────"; }
bien()   { printf '  %s✓%s %s\n' "$V" "$N" "$*"; }
mal()    { printf '  %s×%s %s\n' "$R" "$N" "$*"; }
tiede()  { printf '  %s!%s %s\n' "$J" "$N" "$*"; }
note()   { printf '  %s%s%s\n' "$F" "$*" "$N"; }
cmd()    { printf '      %s\n' "$*"; }

# Le cerveau se résout AVANT les valeurs par défaut : elles en dépendent
# toutes. C'est aussi ce qui fait échouer tôt, et en le disant, un poste qui
# pilote deux cerveaux sans préciser lequel.
resoudre_cerveau

# ---------------------------------------------------------------------------
# Configuration : lue si elle existe, valeurs par défaut sinon
# ---------------------------------------------------------------------------
ARAC_NODE_ID=""
ARAC_INGEST_URL=""
ARAC_CLAUDE_CODE_DIR="$HOME/.claude/projects"
defauts_du_cerveau
ARAC_MAX_CONVERSATIONS="0"
ARAC_SERVEUR_SSH=""
# Aucun défaut : « 8000 » était plausible, donc dangereux — sur une machine à
# deux cerveaux il désigne le PREMIER. Voir mac/arac-sync.py, même raison.
ARAC_PORT_API=""
ARAC_PORT_COCKPIT=""

charger_conf() {
    if [ -r "$CONF" ]; then
        # shellcheck disable=SC1090
        . "$CONF"
    fi
}

python_du_systeme() {
    if command -v python3 >/dev/null 2>&1; then
        command -v python3
    elif [ -x /usr/bin/python3 ]; then
        printf '/usr/bin/python3\n'
    else
        printf ''
    fi
}

port_ouvert() { # hôte port
    # bash 3.2 : /dev/tcp fonctionne, et évite de dépendre de nc, dont les
    # options diffèrent entre macOS et Linux.
    (exec 3<>"/dev/tcp/$1/$2") >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# CE QU'ON RELIT, C'EST LE FICHIER POSÉ — JAMAIS LE GABARIT
#
# Un gabarit n'est pas un fichier : c'est la PROMESSE d'un fichier. La seule
# façon de savoir si elle a été tenue est de relire ce qu'on vient d'écrire.
#
# `installer` a posé, jusqu'à cette manche, un pont.conf qui gardait
# LITTÉRALEMENT `$HOME/.arac/<cerveau>/etat-pont.json` : son `sed` substituait
# trois clés et aucune des quatre lignes portant le jeton `<cerveau>`. Le
# gabarit était juste ; la substitution était juste sur ce qu'elle visait ; et
# le fichier posé était faux. Personne ne le relisait. Tout le cloisonnement
# du poste — un foyer par cerveau, un jeton par cerveau, un CURSEUR par
# cerveau — était annulé par la commande même qui l'installe.
#
# En shell, ce n'est même pas un chemin inerte : `<cerveau>` est une
# REDIRECTION. `. pont.conf` tente d'ouvrir un fichier nommé « cerveau », et
# s'il en existe un dans le répertoire courant, il CRÉE `/jeton_ingest`.
#
# TROIS FAMILLES DE JETONS, UNE RÈGLE PAR FAMILLE :
#   @@NOM@@   jamais légitime dans un fichier posé, nulle part (launchd, sshd,
#             nginx, systemd « sans Mac ») ;
#   __NOM__   idem (gabarits systemd de ops/systemd/) ;
#   <mot>     jamais légitime dans une ligne de VALEUR. En commentaire, c'est
#             de la prose adressée à un humain — « <adresse-de-votre-serveur> »
#             est une consigne, pas un défaut. Dans une ligne lue par un
#             programme, c'est un gabarit qui n'a pas été substitué.
#
# `avec_chevrons=0` pour un fichier XML : un plist est fait de <string>.
# ---------------------------------------------------------------------------
jetons_non_resolus() { # fichier [avec_chevrons=1] → imprime les lignes fautives
    awk -v chevrons="${2:-1}" '
        /@@[A-Za-z0-9_]+@@/ || /__[A-Z][A-Z0-9_]+__/ { printf "  %d: %s\n", FNR, $0; n++; next }
        chevrons == 0                                { next }
        /^[[:space:]]*([#;]|$)/                      { next }
        /<[A-Za-z_][A-Za-z0-9_-]*>/                  { printf "  %d: %s\n", FNR, $0; n++ }
        END { exit (n ? 1 : 0) }
    ' "$1"
}

# Le contrôle lui-même : il refuse, il nomme, et il ne laisse pas derrière lui
# un fichier dont on vient de dire qu'il est faux.
controle_fichier_pose() { # fichier [avec_chevrons]
    fautives="$(jetons_non_resolus "$1" "${2:-1}")" && return 0
    mal "Le fichier posé porte encore des jetons de gabarit : $1"
    printf '%s\n' "$fautives"
    note "Ce fichier n'aurait pas fait ce qu'il annonce : un jeton non"
    note "substitué désigne un chemin LITTÉRAL, le même pour tous les"
    note "cerveaux de ce poste. Il est retiré plutôt que laissé en place."
    rm -f "$1"
    return 1
}

# LES DEUX NUMÉROS SANS LESQUELS RIEN N'A DE SENS.
#
# Vides, ils ne produisent pas une erreur : ils produisent une commande
# absurde — `ssh -L :127.0.0.1: hôte`, un plist qui ouvre un tunnel vers
# nulle part, un `etat` qui annonce « port fermé » d'un port qui n'existe
# pas. On refuse avant, et en disant où les lire.
ports_renseignes() {
    [ -n "$ARAC_PORT_API" ] && [ -n "$ARAC_PORT_COCKPIT" ] && return 0
    mal "ARAC_PORT_API et/ou ARAC_PORT_COCKPIT sont vides dans $CONF"
    # LA PHRASE NE CITE PLUS DE NUMÉRO, ET C'EST LE FOND, PAS LA FORME.
    #
    # Elle citait le port historique pour enseigner de NE PAS le recopier. Deux
    # conséquences, et les deux mauvaises : le garde G1, qui lit les chaînes
    # IMPRIMÉES comme du code — c'est délibéré, c'est ce qui lui permet
    # d'attraper les commandes qu'on fait recopier — retenait ce littéral et
    # rendait `make test` rouge ; et un lecteur pressé retient le nombre qu'il
    # a sous les yeux, pas la mise en garde qui l'accompagne. On nomme la
    # règle sans donner d'exemple à recopier : le seul numéro juste est celui
    # que la commande ci-dessous va chercher SUR SON serveur.
    note "Ils n'ont aucun défaut, et c'est voulu : un numéro plausible désigne"
    note "le PREMIER cerveau d'une machine qui en porte deux. Lisez CEUX DE"
    note "VOTRE cerveau sur son serveur, puis écrivez-les dans $CONF :"
    cmd "sudo grep -E '^ARAC_(API|COCKPIT)_PORT=' /etc/arac/${ARAC_CERVEAU:-<votre-base>}/arac.env"
    return 2
}

# ===========================================================================
# installer
# ===========================================================================
commande_installer() {
    titre "Préparer le pont sur cette machine"
    vide
    dire "  Un pont appartient à UN cerveau. Son dossier, sa configuration, son"
    dire "  jeton, son CURSEUR de synchronisation, son journal et ses étiquettes"
    dire "  launchd porteront son nom — c'est ce qui permet à ce poste d'en"
    dire "  piloter deux sans qu'ils se marchent dessus."
    vide

    # -----------------------------------------------------------------------
    # LE NOM, D'ABORD : TOUT EN DÉCOULE.
    #
    # Cette question n'existait pas. `installer` posait donc sa configuration
    # dans `~/.arac` NU, et le gabarit y arrivait avec ses quatre `<cerveau>`
    # intacts. Deux ponts correctement nommés partageaient un seul curseur et
    # un seul jeton — c'est-à-dire exactement ce que ce script décrit, vingt
    # lignes plus haut, comme « la seule perte silencieuse et définitive du
    # système ».
    # -----------------------------------------------------------------------
    dire "  0. Le nom de ce cerveau."
    note "Celui de sa base sur le serveur, celui du dossier /etc/arac/<base>/."
    note "Vérification côté serveur :  ls /etc/arac/"
    if [ -n "$ARAC_CERVEAU_DEMANDE" ]; then
        printf '     cerveau [%s] : ' "$ARAC_CERVEAU_DEMANDE"
    else
        printf '     cerveau : '
    fi
    read -r rep_cerveau
    [ -z "$rep_cerveau" ] && rep_cerveau="$ARAC_CERVEAU_DEMANDE"
    nom_cerveau="$(assainir_cerveau "$rep_cerveau")"
    if [ -z "$nom_cerveau" ]; then
        vide
        mal "Sans nom, ce pont s'installerait dans le foyer COMMUN — ~/.arac —"
        note "et le prochain cerveau de ce poste s'installerait par-dessus :"
        note "même curseur, même jeton, même étiquette launchd. Rien n'a été"
        note "fait. Reprenez avec le nom de la base de votre cerveau."
        return 2
    fi
    if [ "$nom_cerveau" != "$rep_cerveau" ]; then
        note "Retenu : « $nom_cerveau » — mêmes règles que le serveur pour"
        note "nommer sa base (lettres, chiffres, souligné, minuscules)."
    fi
    ARAC_CERVEAU="$nom_cerveau"
    resoudre_cerveau
    defauts_du_cerveau
    vide

    dire "  Voici ce que je vais faire, et rien d'autre :"
    vide
    dire "   1. créer $ARAC_DIR (0700) et ses sous-dossiers"
    dire "   2. y copier arac-sync.py depuis $ICI"
    dire "   3. y écrire pont.conf à partir de vos réponses"
    dire "   4. relire le fichier posé, et refuser s'il reste un jeton de gabarit"
    dire "   5. vous dire ce qu'il reste à faire — sans le faire à votre place"
    vide
    dire "  Je ne touche à aucun fichier système, je ne demande pas sudo, et"
    dire "  je n'envoie strictement rien : l'envoi a sa propre commande, et"
    dire "  elle vous montrera d'abord ce qui part."
    vide
    printf '  Continuer ? [o/N] '
    read -r reponse
    case "$reponse" in
        o|O|oui|OUI) ;;
        *) vide; dire "  Rien n'a été fait."; return 0 ;;
    esac

    mkdir -p "$ARAC_DIR" "$ARAC_DIR/journal" "$ARAC_DIR/export-desktop"
    chmod 700 "$ARAC_DIR"
    bien "$ARAC_DIR prêt"

    if [ -f "$ICI/arac-sync.py" ]; then
        cp "$ICI/arac-sync.py" "$ARAC_DIR/arac-sync.py"
        chmod 755 "$ARAC_DIR/arac-sync.py"
        bien "arac-sync.py copié dans $ARAC_DIR"
        note "copié, pas lié : une mise à jour du dépôt ne changera pas votre"
        note "pont sans que vous l'ayez décidé. Relancez « installer » pour"
        note "prendre une nouvelle version."
    else
        mal "arac-sync.py introuvable à côté de ce script ($ICI)"
        return 3
    fi

    if [ -f "$CONF" ]; then
        vide
        tiede "$CONF existe déjà — je n'y touche pas."
        note "Éditez-le à la main, ou renommez-le pour repartir de zéro."
        # UN pont.conf POSÉ PAR UNE VERSION ANTÉRIEURE PORTE ENCORE LE GABARIT.
        # On ne le réécrit pas — il est peut-être annoté, il est à son
        # propriétaire — mais on ne se tait pas non plus : ses quatre chemins
        # désignent un dossier LITTÉRAL nommé « <cerveau> », partagé.
        if ! fautives="$(jetons_non_resolus "$CONF")"; then
            vide
            mal "Et il porte encore des jetons de gabarit non substitués :"
            printf '%s\n' "$fautives"
            note "Ce fichier a été posé par une version de « installer » qui ne"
            note "substituait pas ces lignes. Elles ne désignent pas un cerveau :"
            note "elles désignent un dossier littéral, le même pour tous."
            note "Le geste : renommez-le et relancez cette commande."
            cmd "mv $CONF $CONF.avant-cloisonnement"
            cmd "$0 installer"
            return 3
        fi
    else
        vide
        titre "Cinq questions"
        vide
        dire "  1. L'identifiant de ce poste."
        note "Votre cerveau refuse les conversations d'un poste inconnu. Cette"
        note "valeur doit être EXACTEMENT celle de source.node_id dans le"
        note "config/brain.toml de votre serveur. Recopiez-la, ne la retapez pas."
        printf '     node_id : '
        read -r rep_node
        vide
        dire "  2. Le nom d'hôte SSH de votre serveur, tel qu'il est dans ~/.ssh/config."
        note "Pas une adresse IP nue : un alias, avec une clé, pour que le tunnel"
        note "se rouvre tout seul sans jamais rien vous demander."
        printf '     hôte SSH [mon-cerveau] : '
        read -r rep_ssh
        [ -z "$rep_ssh" ] && rep_ssh="mon-cerveau"
        vide
        dire "  3. Le dossier des sessions Claude Code à surveiller."
        note "Par défaut tout ; restreignez à un sous-dossier si vous ne voulez"
        note "envoyer que certains projets. Le pont ne lit jamais au-dessus."
        printf "     dossier [%s] : " "$ARAC_CLAUDE_CODE_DIR"
        read -r rep_dir
        [ -z "$rep_dir" ] && rep_dir="\$HOME/.claude/projects"
        vide
        # LES DEUX NUMÉROS, ICI, PARCE QU'ILS NE SE DEVINENT PAS.
        #
        # Ils n'ont volontairement aucun défaut — « 8000 » désigne le PREMIER
        # cerveau d'une machine qui en porte deux. Mais ne pas les demander
        # laissait un pont.conf à deux trous, et rien pour dire lesquels :
        # `tunnel ouvrir` construisait alors `-L :127.0.0.1:`, et `etat`
        # annonçait « port fermé » d'un port qui n'existe pas.
        dire "  4. et 5. Les deux ports de VOTRE cerveau, sur son serveur :"
        # `cmd`, PAS `note` : c'est un geste à recopier, et le dire ainsi le
        # met sous le garde qui relit ce que le produit imprime
        # (tests/test_gabarits_la_commande_imprimee_ne_porte_aucun_trou.py).
        # Une commande déguisée en prose échappe à tout, y compris à l'œil.
        cmd "sudo grep -E '^ARAC_(API|COCKPIT)_PORT=' /etc/arac/$ARAC_CERVEAU/arac.env"
        note "Aucun défaut, et c'est voulu : un numéro plausible vous brancherait"
        note "sur le cerveau du voisin, avec un jeton valide et un HTTP 200."
        note "Vous pouvez laisser vide et les écrire plus tard dans pont.conf."
        printf '     port de l'"'"'API : '
        read -r rep_api
        printf '     port du cockpit : '
        read -r rep_cockpit

        if [ -f "$ICI/pont.conf.example" ]; then
            # LES QUATRE LIGNES QUI PORTENT `<cerveau>` SONT SUBSTITUÉES ICI,
            # ET C'EST LE CORRECTIF. Elles ne l'étaient pas : le fichier posé
            # gardait le gabarit littéral, et `<cerveau>` n'est pas un nom —
            # c'est un DOSSIER, le même pour tous les cerveaux du poste.
            #
            # `<votre-cerveau>` et `<votre-base>` désignent la même chose que
            # `<cerveau>` : le nom qu'on vient d'apprendre. On les substitue
            # aussi — un commentaire qui dit « <votre-base> » à quelqu'un qui
            # a déjà répondu à la question lui fait chercher une réponse qu'il
            # a donnée. Ce qui reste — « <adresse-de-votre-serveur> » — est une
            # consigne adressée à un humain, et le contrôle plus bas le sait.
            sed -e "s|<cerveau>|$ARAC_CERVEAU|g" \
                -e "s|<votre-cerveau>|$ARAC_CERVEAU|g" \
                -e "s|<votre-base>|$ARAC_CERVEAU|g" \
                -e "s|^ARAC_NODE_ID=.*|ARAC_NODE_ID=$rep_node|" \
                -e "s|^ARAC_SERVEUR_SSH=.*|ARAC_SERVEUR_SSH=$rep_ssh|" \
                -e "s|^ARAC_CLAUDE_CODE_DIR=.*|ARAC_CLAUDE_CODE_DIR=$rep_dir|" \
                -e "s|^ARAC_PORT_API=.*|ARAC_PORT_API=$rep_api|" \
                -e "s|^ARAC_PORT_COCKPIT=.*|ARAC_PORT_COCKPIT=$rep_cockpit|" \
                "$ICI/pont.conf.example" > "$CONF"
        else
            {
                printf 'ARAC_NODE_ID=%s\n' "$rep_node"
                printf 'ARAC_SERVEUR_SSH=%s\n' "$rep_ssh"
                printf 'ARAC_CLAUDE_CODE_DIR=%s\n' "$rep_dir"
                printf 'ARAC_PORT_API=%s\n' "$rep_api"
                printf 'ARAC_PORT_COCKPIT=%s\n' "$rep_cockpit"
                printf 'ARAC_TOKEN_FILE=%s\n' "$ARAC_TOKEN_FILE"
                printf 'ARAC_DESKTOP_EXPORT=%s\n' "$ARAC_DESKTOP_EXPORT"
                printf 'ARAC_STATE_FILE=%s\n' "$ARAC_STATE_FILE"
                printf 'ARAC_LOG_FILE=%s\n' "$ARAC_LOG_FILE"
            } > "$CONF"
        fi
        chmod 600 "$CONF"

        # ON RELIT CE QU'ON VIENT D'ÉCRIRE. Pas le gabarit : le fichier posé.
        controle_fichier_pose "$CONF" || return 3

        vide
        bien "$CONF écrit"
        note "Il ne contient aucun secret ; le jeton vit à part, en 0600."
        note "Les quatre chemins qui doivent être propres à ce cerveau :"
        grep -E '^ARAC_(TOKEN_FILE|DESKTOP_EXPORT|STATE_FILE|LOG_FILE)=' "$CONF" \
            | sed 's/^/      /'
    fi

    charger_conf
    vide
    titre "Ce qu'il reste à faire, dans cet ordre"
    vide
    etape=1
    if [ -z "$ARAC_PORT_API" ] || [ -z "$ARAC_PORT_COCKPIT" ]; then
        dire "  $etape. Les deux numéros de ports, laissés vides — sans eux le tunnel"
        dire "     ne s'ouvre pas. Sur le serveur :"
        cmd "sudo grep -E '^ARAC_(API|COCKPIT)_PORT=' /etc/arac/$ARAC_CERVEAU/arac.env"
        dire "     puis, dans $CONF :"
        cmd "ARAC_PORT_API=<le numéro>    ARAC_PORT_COCKPIT=<l'autre>"
        vide
        etape=$((etape + 1))
    fi
    dire "  $etape. La clé du tunnel, si vous n'en avez pas :"
    cmd "$0 cle-ssh"
    vide
    etape=$((etape + 1))
    dire "  $etape. Le jeton d'ingestion, à lire sur le serveur (root) :"
    cmd "sudo grep '^ARAC_API_BEARER_TOKEN=' /etc/arac/$ARAC_CERVEAU/arac.env"
    dire "     puis à déposer ici :"
    cmd "umask 077 && cat > $ARAC_TOKEN_FILE   # collez, puis Ctrl-D"
    vide
    etape=$((etape + 1))
    dire "  $etape. Le trajet complet, raconté, sans rien envoyer sans votre accord :"
    cmd "ARAC_CERVEAU=$ARAC_CERVEAU $0 premiere-synchro"
    note "Le sélecteur n'est nécessaire que si ce poste pilote plusieurs"
    note "cerveaux — mais il est toujours juste, et il ne devine rien."
    vide
    return 0
}

# ===========================================================================
# cle-ssh
# ===========================================================================
commande_cle_ssh() {
    charger_conf
    # LA CLÉ AUSSI PORTE LE NOM DU CERVEAU.
    #
    # Tout le foyer Mac a été cloisonné — `~/.arac/<cerveau>/`, étiquettes
    # `com.arac.<cerveau>.pont.*`, journaux `arac-pont-<cerveau>-*.log` — sauf
    # ceci : `$HOME/.ssh/id_ed25519_arac`, un nom unique pour toute la session
    # macOS. Au second cerveau, cette fonction ne refusait pas : elle disait
    # « la clé existe déjà », puis imprimait la ligne authorized_keys en
    # associant la clé publique du PREMIER cerveau aux ports du SECOND. Une
    # seule clé privée finissait autorisée sur les deux. La promesse du
    # dispositif — « une clé, et cette clé n'ouvre que deux ports » — devenait
    # « une clé, quatre ports, deux cerveaux » : copier ou compromettre la clé
    # d'un pont donnait l'accès au tunnel de l'autre, et rien ne le signalait.
    #
    # La ligne d'en dessous mettait déjà le cerveau dans le COMMENTAIRE de la
    # clé (`-C "arac-pont-$ARAC_CERVEAU-…"`) : le nom du fichier est le seul
    # endroit qui ne l'avait pas suivi.
    cle="$HOME/.ssh/id_ed25519_arac_$ARAC_CERVEAU"
    cle_commune="$HOME/.ssh/id_ed25519_arac"

    titre "La clé du tunnel"
    dire "  Une clé DÉDIÉE au pont, distincte de votre clé d'administration."
    dire "  Pourquoi : sur le serveur, cette clé sera bridée — elle n'ouvrira"
    dire "  RIEN d'autre que les deux ports du cerveau. Pas de shell, pas de"
    dire "  transfert de fichiers, pas d'agent. Si le Mac est volé, le voleur"
    dire "  hérite d'un tuyau vers deux ports, pas d'un serveur."
    vide

    if [ -f "$cle" ]; then
        tiede "La clé de ce cerveau existe déjà : $cle"
    elif [ -f "$cle_commune" ]; then
        # UNE CLÉ SANS SUFFIXE : installation antérieure au cloisonnement.
        # On ne la réutilise pas en silence — c'est exactement le geste qui
        # faisait qu'une clé ouvrait deux cerveaux. On dit ce qu'on a trouvé,
        # ce qu'on attendait, et le geste.
        tiede "Une clé COMMUNE existe : $cle_commune"
        note "Elle date d'avant le cloisonnement par cerveau. Ce script ne la"
        note "réutilisera pas : si un second cerveau était installé sur ce"
        note "poste, la même clé privée ouvrirait les tunnels des DEUX."
        note ""
        note "Deux gestes possibles, à vous :"
        note "  · l'adopter pour CE cerveau, et pour lui seul :"
        note "      mv $cle_commune $cle"
        note "      mv $cle_commune.pub $cle.pub"
        note "  · en fabriquer une neuve pour ce cerveau, et laisser l'autre"
        note "    où elle est :"
        note "      ssh-keygen -t ed25519 -a 100 -f $cle -N ''"
        note ""
        note "Dans les deux cas, la ligne authorized_keys du serveur doit être"
        note "reposée : relancez cette commande ensuite."
        return 0
    else
        mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"
        ssh-keygen -t ed25519 -a 100 -f "$cle" -C "arac-pont-$ARAC_CERVEAU-$(hostname -s 2>/dev/null || echo poste)" -N ""
        bien "clé créée : $cle"
        note "Sans phrase de passe : un tunnel doit se rouvrir seul après un"
        note "redémarrage, sans personne pour taper quoi que ce soit. C'est un"
        note "arbitrage assumé — la clé est bridée côté serveur, c'est là que"
        note "se joue la sécurité."
    fi

    vide
    titre "À poser sur le serveur, une seule fois"
    vide
    dire "  Dans le ~/.ssh/authorized_keys du compte qui portera le tunnel,"
    dire "  collez CETTE ligne — la partie avant la clé est ce qui la bride :"
    vide
    # UNE LIGNE authorized_keys À TROU EST UNE PORTE OUVERTE.
    #
    # Avec des ports vides, ce printf rendait
    # `permitopen="127.0.0.1:",permitopen="127.0.0.1:"` — une ligne que sshd
    # accepte et qui n'autorise RIEN, ou qu'on « corrige » en retirant les
    # permitopen, c'est-à-dire en donnant à cette clé la redirection vers
    # n'importe quel port du serveur. On ne l'imprime pas.
    if [ -f "$cle.pub" ]; then
        if ports_renseignes; then
            printf '  restrict,port-forwarding,permitopen="127.0.0.1:%s",permitopen="127.0.0.1:%s" %s\n' \
                "$ARAC_PORT_API" "$ARAC_PORT_COCKPIT" "$(cat "$cle.pub")"
        else
            note "La ligne n'est PAS imprimée : elle porterait deux trous là où"
            note "vont les deux ports. Renseignez-les, puis relancez « $0 cle-ssh »."
            note "La clé, elle, est faite : ce qui manque est la ligne à poser."
            return 2
        fi
    fi
    vide
    note "restrict          : tout est interdit par défaut (shell, agent, X11, tty)"
    note "port-forwarding   : sauf la redirection de ports…"
    note "permitopen=…      : …et uniquement vers ces deux ports, en boucle locale."
    vide
    dire "  Puis, dans votre ~/.ssh/config sur cette machine :"
    vide
    cmd "Host ${ARAC_SERVEUR_SSH:-mon-cerveau}"
    cmd "    HostName        <adresse-de-votre-serveur>"
    cmd "    User            <le-compte-du-tunnel>"
    cmd "    IdentityFile    $cle"
    cmd "    IdentitiesOnly  yes"
    cmd "    ServerAliveInterval 30"
    cmd "    ServerAliveCountMax 3"
    vide
    dire "  Vérifiez ensuite que la clé n'ouvre bien QUE ce qu'elle doit :"
    cmd "ssh ${ARAC_SERVEUR_SSH:-mon-cerveau} echo bonjour    # doit ÉCHOUER"
    cmd "$0 tunnel ouvrir                                     # doit MARCHER"
    vide
    return 0
}

# ===========================================================================
# tunnel
# ===========================================================================
commande_tunnel() {
    charger_conf
    action="${1:-ouvrir}"

    if [ -z "$ARAC_SERVEUR_SSH" ]; then
        mal "ARAC_SERVEUR_SSH n'est pas renseigné dans $CONF"
        note "Le tunnel a besoin d'un nom d'hôte SSH. Voir « $0 cle-ssh »."
        return 2
    fi
    ports_renseignes || return 2

    case "$action" in
        ouvrir)
            titre "Ouverture du tunnel (au premier plan)"
            dire "  Deux ports remontent depuis le serveur vers cette machine :"
            vide
            dire "    127.0.0.1:$ARAC_PORT_API      → l'API — par où vos conversations montent"
            dire "    127.0.0.1:$ARAC_PORT_COCKPIT      → le cockpit — par où vous regardez"
            vide
            note "Rien n'est exposé à l'Internet, dans aucun sens : SSH ouvre les"
            note "ports SUR CETTE MACHINE, en boucle locale, et rien d'autre."
            vide
            dire "  Ctrl-C ferme le tunnel. Pour qu'il se rouvre tout seul à chaque"
            dire "  démarrage : $0 automatiser"
            vide
            exec ssh -N \
                -o ExitOnForwardFailure=yes \
                -o ServerAliveInterval=30 \
                -o ServerAliveCountMax=3 \
                -L "$ARAC_PORT_API:127.0.0.1:$ARAC_PORT_API" \
                -L "$ARAC_PORT_COCKPIT:127.0.0.1:$ARAC_PORT_COCKPIT" \
                "$ARAC_SERVEUR_SSH"
            ;;
        etat)
            titre "État du tunnel"
            if port_ouvert 127.0.0.1 "$ARAC_PORT_API"; then
                bien "port $ARAC_PORT_API (API) ouvert sur cette machine"
            else
                mal "port $ARAC_PORT_API (API) fermé — le tunnel n'est pas là"
            fi
            if port_ouvert 127.0.0.1 "$ARAC_PORT_COCKPIT"; then
                bien "port $ARAC_PORT_COCKPIT (cockpit) ouvert"
            else
                mal "port $ARAC_PORT_COCKPIT (cockpit) fermé"
            fi
            vide
            note "Qui tient ces ports :"
            cmd "lsof -nP -iTCP:$ARAC_PORT_API -sTCP:LISTEN"
            vide
            ;;
        fermer)
            titre "Fermeture du tunnel automatique"
            launchctl bootout "gui/$(id -u)/$ETIQUETTE_TUNNEL" 2>/dev/null \
                || launchctl unload -w "$AGENTS/$ETIQUETTE_TUNNEL.plist" 2>/dev/null
            bien "agent $ETIQUETTE_TUNNEL déchargé (s'il tournait)"
            note "Un tunnel ouvert au premier plan se ferme avec Ctrl-C."
            ;;
        *)
            mal "Action inconnue : $action  (ouvrir | etat | fermer)"
            return 2
            ;;
    esac
    return 0
}

# ===========================================================================
# etat — le diagnostic, maillon par maillon
# ===========================================================================
commande_etat() {
    charger_conf
    py="$(python_du_systeme)"
    probleme=0

    titre "La chaîne, maillon par maillon"
    vide
    dire "  Le pont est une file d'attente de dépendances. Le premier maillon"
    dire "  cassé explique tous les suivants : lisez de haut en bas, et"
    dire "  arrêtez-vous au premier ×."
    vide

    dire "  1. Cette machine"
    if [ -n "$py" ]; then bien "python3 : $py ($("$py" -V 2>&1))"
    else mal "python3 introuvable — installez les Command Line Tools : xcode-select --install"; probleme=1; fi
    if [ -d "$ARAC_DIR" ]; then bien "$ARAC_DIR présent"
    else mal "$ARAC_DIR absent — lancez « $0 installer »"; probleme=1; fi
    if [ -f "$ARAC_DIR/arac-sync.py" ]; then bien "arac-sync.py installé"
    else mal "arac-sync.py absent de $ARAC_DIR"; probleme=1; fi
    vide

    dire "  2. Configuration"
    if [ -r "$CONF" ]; then bien "$CONF lisible"
    else mal "$CONF absent"; probleme=1; fi
    if [ -n "$ARAC_NODE_ID" ]; then bien "poste déclaré : « $ARAC_NODE_ID »"
    else mal "ARAC_NODE_ID vide — le serveur refusera tout (403)"; probleme=1; fi
    if [ -f "$ARAC_TOKEN_FILE" ]; then
        perms="$(ls -l "$ARAC_TOKEN_FILE" | cut -c1-10)"
        case "$perms" in
            -rw-------) bien "jeton présent, permissions correctes" ;;
            *) tiede "jeton présent mais lisible par d'autres ($perms) — chmod 600 $ARAC_TOKEN_FILE" ;;
        esac
    else
        mal "jeton absent : $ARAC_TOKEN_FILE"; probleme=1
    fi
    vide

    dire "  3. Sources de conversations"
    if [ -d "$ARAC_CLAUDE_CODE_DIR" ]; then
        n="$(find "$ARAC_CLAUDE_CODE_DIR" -name '*.jsonl' 2>/dev/null | wc -l | tr -d ' ')"
        if [ "$n" -gt 0 ]; then bien "Claude Code : $n fichier(s) de session"
        else tiede "Claude Code : dossier présent, aucune session"; fi
    else
        tiede "Claude Code : $ARAC_CLAUDE_CODE_DIR absent"
    fi
    if [ -f "$ARAC_DESKTOP_EXPORT" ]; then
        bien "export claude.ai : présent ($(ls -lh "$ARAC_DESKTOP_EXPORT" | awk '{print $5}'))"
    else
        tiede "export claude.ai : absent (facultatif — voir docs/PONT-MAC.md)"
    fi
    vide

    dire "  4. Le tunnel"
    # LE DIAGNOSTIC NE REFUSE PAS : IL CONSTATE. MAIS IL NE SONDE PAS DU VIDE.
    #
    # `etat` est fait pour répondre à « lequel des maillons est cassé ? » : il
    # ne peut pas s'arrêter au premier trou comme les autres commandes. Sans
    # numéro, il sondait quand même et annonçait « port  fermé — le tunnel est
    # tombé » : le maillon 4 accusé d'une panne qui appartient au maillon 2,
    # avec deux remèdes (« tunnel ouvrir », « automatiser ») qui n'y peuvent
    # rien. Il nomme désormais la vraie cause, puis passe au maillon suivant.
    if [ -z "$ARAC_PORT_API" ] || [ -z "$ARAC_PORT_COCKPIT" ]; then
        ports_renseignes
        probleme=1
    else
        if port_ouvert 127.0.0.1 "$ARAC_PORT_API"; then
            bien "port $ARAC_PORT_API ouvert (API atteignable)"
        else
            mal "port $ARAC_PORT_API fermé — le tunnel est tombé ou n'a jamais été ouvert"
            note "  → $0 tunnel ouvrir     (au premier plan, pour voir l'erreur)"
            note "  → $0 automatiser       (pour qu'il se rouvre tout seul)"
            probleme=1
        fi
        if port_ouvert 127.0.0.1 "$ARAC_PORT_COCKPIT"; then
            bien "port $ARAC_PORT_COCKPIT ouvert (cockpit : http://127.0.0.1:$ARAC_PORT_COCKPIT)"
        else
            tiede "port $ARAC_PORT_COCKPIT fermé — pas de cockpit tant que le tunnel dort"
        fi
    fi
    vide

    dire "  5. Automatisation (launchd)"
    for etiquette in "$ETIQUETTE_TUNNEL" "$ETIQUETTE_SYNC"; do
        if launchctl list 2>/dev/null | grep -q "$etiquette"; then
            bien "$etiquette chargé"
        else
            tiede "$etiquette non chargé — « $0 automatiser » pour le confier à launchd"
        fi
    done
    vide

    dire "  6. Dernier passage"
    if [ -f "$ARAC_STATE_FILE" ] && [ -n "$py" ]; then
        "$py" - "$ARAC_STATE_FILE" <<'PYEOF'
import json, sys
try:
    e = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception as err:
    print(f"  ! état illisible ({err}) — le supprimer est sans danger : le serveur déduplique.")
    raise SystemExit(0)
convs = e.get("conversations", {})
completes = sum(1 for v in convs.values() if isinstance(v, dict) and v.get("complete"))
msgs = sum(int(v.get("messages_acquittes", 0)) for v in convs.values() if isinstance(v, dict))
print(f"  ✓ première synchronisation : {e.get('premiere_synchro') or 'jamais'}")
print(f"  ✓ dernier passage          : {e.get('derniere_synchro') or 'jamais'}")
print(f"  ✓ conversations suivies    : {len(convs)} ({completes} complètes)")
print(f"  ✓ messages acquittés       : {msgs}")
PYEOF
    else
        tiede "aucun état : la première synchronisation n'a pas encore eu lieu"
        note "  → $0 premiere-synchro"
    fi
    vide

    if [ "$probleme" -eq 0 ]; then
        titre "Verdict"
        bien "Le pont est debout."
        note "Rien n'est envoyé tant que vous ne le demandez pas ; launchd s'en"
        note "charge une fois « $0 automatiser » exécuté."
    else
        titre "Verdict"
        mal "Au moins un maillon est cassé — corrigez le premier × ci-dessus."
        note "Les pannes courantes et leur diagnostic : docs/PONT-MAC.md"
    fi
    vide
    return "$probleme"
}

# ===========================================================================
# premiere-synchro — le trajet complet, raconté
# ===========================================================================

# LE PRÉFIXE DES UNITÉS DU SERVEUR — DÉDUIT, OU RIEN.
#
# `bootstrap/lib/config.sh:167` pose `PREFIXE_UNITE="arac-${ARAC_DB}"`, et
# `ARAC_DB` est précisément ce que `installer` demande sous le nom « cerveau »
# (« celui de sa base sur le serveur, celui du dossier /etc/arac/<base>/ »).
# Les quatre unités en descendent : `-api`, `-cockpit`, `-cycle`,
# `-sauvegarde`.
#
# Sans nom de cerveau — le foyer COMMUN d'un poste installé avant le
# cloisonnement —, il n'y a rien à déduire. On rend 1, et l'appelant DIT qu'il
# ne sait pas au lieu de nommer : c'est la règle de tout ce dépôt, et c'est
# celle qu'un trou imprimé viole en silence.
prefixe_unite() {
    [ -n "$ARAC_CERVEAU" ] || return 1
    printf 'arac-%s' "$ARAC_CERVEAU"
}

# ---------------------------------------------------------------------------
# LE DERNIER ÉCRAN DU PONT — ET POURQUOI IL EST UNE FONCTION
#
# C'est la dernière chose que le pont dit, à la minute exacte où les
# conversations viennent d'arriver : le moment où l'on a le plus confiance en
# ce qu'on lit, et donc celui où l'on recopie sans relire.
#
# Il imprimait `sudo systemctl start <prefixe>-cycle.service`. `<prefixe>`
# n'est pas un nom, c'est un TROU — et le nom était connu à cette ligne :
# quatre lignes plus bas, le même écran interpolait correctement
# `$ARAC_PORT_COCKPIT`. Recopiée telle quelle, la commande rend « Unit
# <prefixe>-cycle.service not found » ; recopiée « en comprenant », elle
# devient une devinette sur le nom d'une unité — et sur une machine à deux
# cerveaux, une devinette désigne le voisin.
#
# Les gardes du dépôt ne pouvaient pas le voir, et pour deux raisons qu'il
# vaut mieux écrire que redécouvrir :
#   · le contrôle des gabarits ne relit que les fichiers POSÉS. Un texte
#     imprimé n'est pas un fichier : il ne reste rien sur le disque à relire.
#   · G1 tient au contraire un `<trou>` pour DÉRIVÉ (`est_derive`), et il a
#     raison sur SA question — un trou ne fige aucun nom que deux cerveaux se
#     disputeraient. Il ne pose simplement pas celle-ci.
#
# C'est une FONCTION pour qu'un test puisse l'imprimer sans installer de
# serveur, sans ouvrir de tunnel et sans envoyer une seule conversation :
# `tests/test_gabarits_la_commande_imprimee_ne_porte_aucun_trou.py` la joue
# avec un cerveau, puis sans, et relit les deux écrans.
# ---------------------------------------------------------------------------
ecran_apres_le_trajet() {
    titre "Et maintenant ?"
    bien "Vos conversations sont arrivées."
    vide
    dire "  Elles ne sont pas encore de la MÉMOIRE : ce sont des messages"
    dire "  bruts, en attente de digestion. Le serveur les transforme par"
    dire "  cycles (trois fois par jour par défaut), pas en continu."
    dire "  Entre deux cycles, un cerveau au repos est un cerveau normal."
    vide
    dire "  Pour digérer sans attendre, sur le serveur :"
    if prefixe="$(prefixe_unite)"; then
        cmd "sudo systemctl start $prefixe-cycle.service"
        cmd "journalctl -u $prefixe-cycle.service -f"
    else
        note "Ce pont est installé dans le foyer COMMUN ~/.arac : il ne connaît"
        note "pas le nom de votre cerveau, donc pas celui de son unité. Plutôt"
        note "que de la deviner — sur une machine à deux cerveaux, une unité"
        note "devinée est celle du voisin —, demandez le nom au serveur : c'est"
        note "celui du dossier, et l'unité s'appelle arac-<base>-cycle.service."
        cmd "ls /etc/arac/"
    fi
    vide
    dire "  Pour regarder, depuis cette machine, tant que le tunnel est ouvert :"
    if [ -n "$ARAC_PORT_COCKPIT" ]; then
        cmd "open http://127.0.0.1:$ARAC_PORT_COCKPIT"
    else
        note "Le port du cockpit n'est pas renseigné dans $CONF — sans lui,"
        note "l'adresse à ouvrir serait une adresse sans port. Où le lire :"
        cmd "sudo grep -E '^ARAC_COCKPIT_PORT=' /etc/arac/${ARAC_CERVEAU:-<votre-base>}/arac.env"
    fi
    vide
    dire "  Pour que tout cela se fasse sans vous, désormais :"
    cmd "$0 automatiser"
    vide
    note "Un ordre de grandeur, mesuré sur le cerveau de référence :"
    note "environ 87 000 jetons par cycle, environ 31 500 par atome"
    note "produit. Ce sont des appels facturés à votre fournisseur"
    note "d'embeddings et de curation. Un gros historique coûte."
}

commande_premiere_synchro() {
    charger_conf
    py="$(python_du_systeme)"
    sync="$ARAC_DIR/arac-sync.py"
    [ -f "$sync" ] || sync="$ICI/arac-sync.py"

    titre "Première synchronisation — le trajet complet"
    vide
    dire "  Ce que nous allons parcourir, dans l'ordre :"
    vide
    dire "    vos conversations sur ce disque"
    dire "        │   1. inventaire — où elles sont, combien il y en a"
    dire "        ▼"
    dire "    le tunnel SSH"
    dire "        │   2. vérification — est-il ouvert ?"
    dire "        ▼"
    dire "    l'annonce"
    dire "        │   3. ce qui partirait, nommément — rien n'est envoyé"
    dire "        ▼"
    dire "    l'envoi"
    dire "        │   4. votre accord explicite, puis le trajet réel"
    dire "        ▼"
    dire "    le rapport"
    dire "            5. trouvées, envoyées, acceptées, refusées — et pourquoi"
    vide

    if [ -z "$py" ]; then
        mal "python3 introuvable. xcode-select --install"
        return 3
    fi
    if [ ! -f "$sync" ]; then
        mal "arac-sync.py introuvable. Lancez « $0 installer »."
        return 3
    fi

    titre "1. Inventaire — ce que cette machine contient"
    "$py" "$sync" --inventaire || true

    titre "2. Le tunnel"
    # SANS NUMÉRO, LA SONDE NE DIT PAS CE QU'ELLE A L'AIR DE DIRE.
    #
    # `port_ouvert 127.0.0.1 ""` tente d'ouvrir `/dev/tcp/127.0.0.1/`, échoue,
    # et l'écran annonçait « port  fermé — rien ne peut partir » : un tunnel
    # accusé à la place d'une configuration incomplète, et un numéro absent au
    # milieu d'une phrase qui prétend en citer un. `ports_renseignes` dit la
    # vraie cause, et où lire le bon numéro.
    ports_renseignes || return 4
    if port_ouvert 127.0.0.1 "$ARAC_PORT_API"; then
        bien "port $ARAC_PORT_API ouvert : l'API est atteignable"
    else
        mal "port $ARAC_PORT_API fermé — rien ne peut partir."
        vide
        dire "  Ouvrez le tunnel dans un autre terminal, puis relancez :"
        cmd "$0 tunnel ouvrir"
        vide
        note "Si l'ouverture échoue : la clé n'est pas autorisée sur le serveur,"
        note "ou son compte n'a pas le droit de rediriger ces ports. Voir"
        note "« $0 cle-ssh » et deploy/ssh/README.md."
        return 5
    fi

    titre "3. L'annonce — ce qui partirait"
    "$py" "$sync" --annonce
    code=$?
    if [ "$code" -eq 0 ]; then
        vide
        bien "Rien à envoyer : tout ce qui est ici est déjà dans votre cerveau."
        return 0
    fi
    if [ "$code" -ne 10 ]; then
        vide
        mal "L'annonce s'est mal passée (code $code). Rien n'a été envoyé."
        return "$code"
    fi

    titre "4. Votre accord"
    vide
    dire "  Relisez la liste ci-dessus. Ce sont vos conversations : elles vont"
    dire "  quitter cette machine, chiffrées par le tunnel, pour votre serveur"
    dire "  — le vôtre, celui dont vous avez les clés."
    vide
    dire "  Ce qui NE part pas : les blocs d'outillage sans texte, les fichiers"
    dire "  de votre disque, et tout ce qui ressemble à un secret (clés, jetons,"
    dire "  mots de passe) — remplacé par un marqueur avant l'envoi."
    vide
    printf '  Envoyer ? [o/N] '
    read -r reponse
    case "$reponse" in
        o|O|oui|OUI) ;;
        *) vide; dire "  Rien n'est parti."; return 0 ;;
    esac

    titre "5. Le trajet"
    "$py" "$sync" --jenvoie
    code=$?

    vide
    case "$code" in
        0)  ecran_apres_le_trajet ;;
        4) mal "Le serveur a refusé ce poste. Le diagnostic est ci-dessus." ;;
        5|7) mal "Rien n'est passé. Vérifiez le tunnel : $0 tunnel etat" ;;
        6) tiede "Synchronisation partielle — les échecs sont listés ci-dessus." ;;
    esac
    vide
    return "$code"
}

# ===========================================================================
# automatiser
# ===========================================================================
commande_automatiser() {
    charger_conf
    py="$(python_du_systeme)"

    titre "Confier le pont à launchd"
    vide
    dire "  Deux agents vont être installés dans $AGENTS :"
    vide
    dire "    $ETIQUETTE_TUNNEL"
    dire "        garde le tunnel ouvert en permanence, le rouvre après une"
    dire "        veille, une coupure réseau ou un redémarrage."
    vide
    dire "    $ETIQUETTE_SYNC"
    dire "        lance la synchronisation toutes les heures."
    vide
    dire "  Ce sont des agents UTILISATEUR : ils tournent sous votre compte,"
    dire "  uniquement quand vous êtes connecté, et n'ont aucun privilège."
    vide

    if [ ! -f "$ARAC_STATE_FILE" ]; then
        mal "La première synchronisation n'a pas encore eu lieu."
        note "Refus délibéré : automatiser AVANT d'avoir vu ce qui part, ce"
        note "serait envoyer une vie entière sans l'avoir regardée passer."
        vide
        cmd "$0 premiere-synchro"
        vide
        return 4
    fi

    # Les deux plists figent ces numéros. Vides, ils poseraient deux agents
    # que launchd relancerait indéfiniment sans qu'aucun n'ouvre quoi que ce soit.
    ports_renseignes || return 4

    autossh=""
    for chemin in /opt/homebrew/bin/autossh /usr/local/bin/autossh; do
        [ -x "$chemin" ] && autossh="$chemin" && break
    done
    if [ -z "$autossh" ]; then
        tiede "autossh n'est pas installé."
        note "Sans lui, launchd relance ssh à chaque coupure, mais avec un délai"
        note "et sans détecter un tunnel « vivant mais muet » (session zombie"
        note "après une veille). autossh sonde et reconnecte proprement."
        vide
        cmd "brew install autossh"
        vide
        printf '  Continuer quand même avec ssh nu ? [o/N] '
        read -r rep
        case "$rep" in o|O|oui|OUI) autossh="$(command -v ssh)"; ssh_nu=1 ;; *) return 4 ;; esac
        # Le repli a besoin d'un ssh, et `command -v` rend la chaîne VIDE
        # quand il n'y en a pas : le plist recevrait un `@@AUTOSSH@@` remplacé
        # par rien, c'est-à-dire un agent sans programme. Le contrôle des
        # jetons ne le verrait pas — il n'y a plus de jeton.
        if [ -z "$autossh" ]; then
            mal "Ni autossh ni ssh sur cette machine."
            note "Un agent de tunnel sans programme à lancer n'est pas un agent."
            return 4
        fi
    fi

    mkdir -p "$AGENTS" "$ARAC_DIR/journal"

    for modele in com.arac.pont.tunnel com.arac.pont.sync; do
        src="$ICI/$modele.plist.modele"
        # Le gabarit garde son nom générique dans le dépôt ; l'agent INSTALLÉ
        # porte celui du cerveau, sans quoi le second écraserait le premier.
        etiquette="com.arac.$ARAC_CERVEAU.${modele#com.arac.}"
        dst="$AGENTS/$etiquette.plist"
        if [ ! -f "$src" ]; then
            mal "Gabarit introuvable : $src"
            return 3
        fi
        sed -e "s|@@FOYER@@|$HOME|g" \
            -e "s|@@CERVEAU@@|$ARAC_CERVEAU|g" \
            -e "s|@@ETIQUETTE@@|$etiquette|g" \
            -e "s|@@PYTHON@@|$py|g" \
            -e "s|@@AUTOSSH@@|$autossh|g" \
            -e "s|@@SERVEUR@@|$ARAC_SERVEUR_SSH|g" \
            -e "s|@@PORT_API@@|$ARAC_PORT_API|g" \
            -e "s|@@PORT_COCKPIT@@|$ARAC_PORT_COCKPIT|g" \
            "$src" > "$dst"
        # LE FICHIER POSÉ, PAS LE GABARIT — même règle qu'à `installer`. Un
        # plist reste du XML valide avec un `@@FOYER@@` en travers d'un chemin :
        # `plutil -lint` dit « OK », launchd charge l'agent, et l'agent lance
        # un script qui n'existe pas. Les chevrons ne sont pas regardés ici :
        # un plist est fait de <string>.
        controle_fichier_pose "$dst" 0 || return 3
        # `-M 0` est une option d'autossh, PAS de ssh : pour ssh, « -M 0 »
        # signifie « mode maître, et l'hôte s'appelle 0 ». Le tunnel ne
        # s'ouvrirait jamais, avec un message incompréhensible. On retire
        # donc la paire quand on retombe sur ssh nu.
        if [ "${ssh_nu:-0}" = "1" ] && [ "$modele" = "com.arac.pont.tunnel" ]; then
            "$py" - "$dst" <<'PYEOF'
import re, sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
s = re.sub(r"\s*<string>-M</string>\s*<string>0</string>", "", s, count=1)
open(p, "w", encoding="utf-8").write(s)
PYEOF
            note "option autossh « -M 0 » retirée : ce plist appelle ssh nu."
        fi
        bien "$dst écrit"
    done

    vide
    dire "  Chargement :"
    for etiquette in "$ETIQUETTE_TUNNEL" "$ETIQUETTE_SYNC"; do
        launchctl bootout "gui/$(id -u)/$etiquette" 2>/dev/null
        if launchctl bootstrap "gui/$(id -u)" "$AGENTS/$etiquette.plist" 2>/dev/null \
           || launchctl load -w "$AGENTS/$etiquette.plist" 2>/dev/null; then
            bien "$etiquette chargé"
        else
            mal "$etiquette n'a pas pu être chargé"
            note "Vérifiez le XML :  plutil -lint $AGENTS/$etiquette.plist"
        fi
    done

    vide
    note "Le tunnel démarre tout de suite. La synchronisation, elle, attend sa"
    note "première heure : elle n'est PAS lancée au chargement, pour qu'un"
    note "rechargement d'agent ne déclenche pas d'envoi surprise."
    vide
    dire "  Vérifier :"
    cmd "$0 etat"
    cmd "$0 journal"
    vide
    return 0
}

# ===========================================================================
# journal / desinstaller
# ===========================================================================
commande_journal() {
    charger_conf
    titre "Journal du pont"
    note "$ARAC_LOG_FILE — une ligne JSON par événement."
    vide
    if [ -f "$ARAC_LOG_FILE" ]; then
        if command -v jq >/dev/null 2>&1; then
            tail -n 40 "$ARAC_LOG_FILE" | jq -c .
        else
            tail -n 40 "$ARAC_LOG_FILE"
        fi
    else
        tiede "aucun journal : le pont n'a jamais tourné"
    fi
    vide
    note "Suivre en direct :  tail -f $ARAC_LOG_FILE"
    note "Ne garder que les fins de passage :"
    note "  jq -c 'select(.evenement==\"fin\")' $ARAC_LOG_FILE"
    vide
    if [ -f "$JOURNAL_TUNNEL" ]; then
        titre "Journal du tunnel"
        tail -n 20 "$JOURNAL_TUNNEL"
        vide
    fi
    return 0
}

commande_desinstaller() {
    titre "Retirer l'automatisation"
    dire "  Les agents launchd sont déchargés et supprimés."
    dire "  Vos conversations, votre configuration, votre état et vos journaux"
    dire "  restent intacts — et rien n'est retiré du serveur."
    vide
    printf '  Continuer ? [o/N] '
    read -r rep
    case "$rep" in o|O|oui|OUI) ;; *) dire "  Rien n'a été fait."; return 0 ;; esac
    for etiquette in "$ETIQUETTE_TUNNEL" "$ETIQUETTE_SYNC"; do
        launchctl bootout "gui/$(id -u)/$etiquette" 2>/dev/null \
            || launchctl unload -w "$AGENTS/$etiquette.plist" 2>/dev/null
        rm -f "$AGENTS/$etiquette.plist"
        bien "$etiquette retiré"
    done
    vide
    note "Pour tout effacer côté machine : rm -rf $ARAC_DIR"
    vide
    return 0
}

# ===========================================================================
# aide
# ===========================================================================
aide() {
    charger_conf
    # `aide` EST LE PREMIER ÉCRAN, ET IL S'AFFICHE AVANT TOUTE CONFIGURATION.
    #
    # C'est ce qu'imprime `./arac-pont.sh` sans argument : sur une machine qui
    # n'a pas encore de `pont.conf`, `$ARAC_PORT_API` est vide, et le schéma
    # annonçait « tunnel SSH  (127.0.0.1: sur cette machine) » — une adresse
    # sans port, c'est-à-dire un trou, dans la toute première chose que lit
    # celui qui vient d'obtenir ce script. Le schéma ne cite un numéro que
    # lorsqu'il en connaît un ; sinon il dit ce qui est vrai sans lui.
    if [ -n "$ARAC_PORT_API" ]; then
        ligne_tunnel="tunnel SSH  (127.0.0.1:$ARAC_PORT_API sur cette machine)"
    else
        ligne_tunnel="tunnel SSH  (en boucle locale ; son port sera dans pont.conf)"
    fi
    cat <<AIDE

  arac-pont.sh $VERSION — le pont entre cette machine et votre cerveau

  Le pont, en une image :

     vos conversations locales
        │  arac-sync.py les lit, les prépare, masque les secrets
        ▼
     $ligne_tunnel
        │  chiffré, sortant, vers votre serveur — rien n'est exposé
        ▼
     API du cerveau, en boucle locale sur le serveur
        │  vérifie le poste, refuse l'inconnu, écrit le brut
        ▼
     digestion par cycles → atomes → mémoire → cockpit

  COMMANDES

     installer          prépare ~/.arac, pose la configuration
     cle-ssh            fabrique la clé du tunnel, bridée côté serveur
     tunnel ouvrir      ouvre le tunnel au premier plan
     tunnel etat        les ports sont-ils là ?
     tunnel fermer      décharge l'agent launchd du tunnel
     etat               diagnostic complet, maillon par maillon
     premiere-synchro   le trajet complet, raconté, avec votre accord
     automatiser        confie tunnel + synchro à launchd
     journal            les derniers événements
     desinstaller       retire launchd, ne touche à aucune donnée

  DANS QUEL ORDRE, LA PREMIÈRE FOIS

     1. installer          2. cle-ssh (+ pose sur le serveur)
     3. le jeton           4. premiere-synchro     5. automatiser

  Tout est expliqué en détail dans docs/PONT-MAC.md — y compris les pannes
  courantes, et ce qui reste possible si vous n'avez pas de Mac.

AIDE
}

# ===========================================================================
case "${1:-aide}" in
    installer)         shift; commande_installer "$@" ;;
    cle-ssh|cle)       shift; commande_cle_ssh "$@" ;;
    tunnel)            shift; commande_tunnel "$@" ;;
    etat)              shift; commande_etat "$@" ;;
    premiere-synchro)  shift; commande_premiere_synchro "$@" ;;
    automatiser)       shift; commande_automatiser "$@" ;;
    journal)           shift; commande_journal "$@" ;;
    desinstaller)      shift; commande_desinstaller "$@" ;;
    aide|-h|--help)    aide ;;
    *)                 printf '  Commande inconnue : %s\n' "$1"; aide; exit 2 ;;
esac
