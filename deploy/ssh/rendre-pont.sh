#!/usr/bin/env bash
# ============================================================================
# rendre-pont.sh — le fragment sshd de CE cerveau, sous un nom qui est le sien
# ============================================================================
#
# POURQUOI CE SCRIPT EXISTE
# -------------------------
# Le gabarit `99-arac-pont.conf` a un contenu intégralement propre à un
# cerveau — `Match User <compte>` et `PermitOpen 127.0.0.1:<api>
# 127.0.0.1:<cockpit>` — et le mode d'emploi le faisait déposer sous un nom
# FIXE, dans un répertoire commun à la machine :
#
#     sudo cp 99-arac-pont.conf /etc/ssh/sshd_config.d/
#
# Sans `-n`, sans contrôle d'existence, sans nom dérivé. Le second cerveau
# installé remplaçait donc le fichier du premier. Deux cas, tous deux muets :
#
#   · comptes de tunnel identiques → le `PermitOpen` du premier disparaît, son
#     tunnel meurt sur un « administratively prohibited » ;
#   · comptes différents → le bloc `Match` du premier disparaît ENTIÈREMENT :
#     plus de `ForceCommand /usr/sbin/nologin`, plus de `PermitTTY no`, plus de
#     `PermitOpen`, plus de `ClientAliveInterval`. Son compte de tunnel retombe
#     sur la configuration globale du serveur. Le durcissement décrit comme
#     « la totalité de la surface exposée du système » est retiré en silence
#     par l'installation du voisin.
#
# Ce script ne recopie plus : il REND. Il lit les valeurs dans le fichier
# d'environnement du cerveau — les seules qui font foi, puisque ce sont celles
# que l'installation s'est vu attribuer — et il écrit un fichier dont le nom
# porte le cerveau. Il REFUSE d'écraser un fichier qui existe déjà : un
# fragment sshd appartient à quelqu'un, et l'écraser sans demander est le
# geste qu'on corrige.
#
# USAGE
#     ./deploy/ssh/rendre-pont.sh                   # rend sur la sortie standard
#     ./deploy/ssh/rendre-pont.sh --poser           # écrit dans /etc/ssh/sshd_config.d/
#     ARAC_ENV_FILE=/etc/arac/<base>/arac.env ./deploy/ssh/rendre-pont.sh
#
# APRÈS `--poser`, ET JAMAIS AVANT :
#     sudo sshd -t                  # TESTER la syntaxe. Toujours.
#     sudo systemctl reload ssh
# en gardant une session SSH ouverte, et en testant la reconnexion depuis un
# SECOND terminal avant de fermer le premier.
# ============================================================================

set -uo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GABARIT="$ICI/99-arac-pont.conf"
POSER=0
[[ "${1:-}" == "--poser" ]] && POSER=1

mal()  { printf '  \033[31m×\033[0m %s\n' "$1" >&2; }
bien() { printf '  \033[32m✓\033[0m %s\n' "$1" >&2; }
note() { printf '    %s\n' "$1" >&2; }

lire() { # fichier cle
    [[ -r "$1" ]] || return 1
    sed -n "s/^${2}=//p" "$1" | head -n1
}

# --- De quel cerveau parle-t-on ? -------------------------------------------
#
# Aucune valeur par défaut, et c'est le point : « /etc/arac/arac/arac.env » ou
# « le premier trouvé » seraient deux façons de choisir un cerveau à la place
# de qui lance la commande.
ARAC_ENV_FILE="${ARAC_ENV_FILE:-}"
if [[ -z "$ARAC_ENV_FILE" ]]; then
    mapfile -t candidats < <(ls -1d /etc/arac/*/arac.env 2>/dev/null || true)
    if (( ${#candidats[@]} == 1 )); then
        ARAC_ENV_FILE="${candidats[0]}"
    elif (( ${#candidats[@]} == 0 )); then
        mal "Aucun cerveau installé sous /etc/arac."
        note "Ce fragment se rend depuis les valeurs RETENUES par une"
        note "installation — ports attribués, nom du cerveau. Sans elles, il"
        note "n'y a rien à rendre, et recopier des numéros au hasard ouvrirait"
        note "un tunnel vers on ne sait quoi."
        exit 2
    else
        mal "Cette machine porte plusieurs cerveaux ; lequel ?"
        for c in "${candidats[@]}"; do note "$c"; done
        note "Précisez :  ARAC_ENV_FILE=<l'un d'eux> $0"
        exit 2
    fi
fi

if [[ ! -r "$ARAC_ENV_FILE" ]]; then
    mal "Illisible : $ARAC_ENV_FILE"
    note "Il est en 0600, root. Relancez avec sudo."
    exit 2
fi

BASE="$(lire "$ARAC_ENV_FILE" ARAC_DB || true)"
PORT_API="$(lire "$ARAC_ENV_FILE" ARAC_API_PORT || true)"
PORT_COCKPIT="$(lire "$ARAC_ENV_FILE" ARAC_COCKPIT_PORT || true)"

manquant=0
for couple in "ARAC_DB:$BASE" "ARAC_API_PORT:$PORT_API" "ARAC_COCKPIT_PORT:$PORT_COCKPIT"; do
    [[ -n "${couple#*:}" ]] && continue
    mal "${couple%%:*} absente de $ARAC_ENV_FILE"
    manquant=1
done
(( manquant )) && { note "Rien n'a été rendu : un fragment sshd à trou est une porte ouverte."; exit 2; }

# --- LE COMPTE DU TUNNEL PORTE LUI AUSSI LE NOM DU CERVEAU ------------------
#
# Le mode d'emploi faisait créer un compte nommé « pont ». Deux cerveaux, deux
# `Match User pont` dans deux fichiers : sshd applique le PREMIER bloc qui
# correspond, et le second n'a plus aucun effet. Un compte par cerveau, et la
# question ne se pose plus.
COMPTE_PONT="${ARAC_COMPTE_PONT:-pont-$BASE}"

DESTINATION="/etc/ssh/sshd_config.d/99-arac-$BASE-pont.conf"

# LE GABARIT DOIT ÊTRE LÀ, ET LE RENDU DOIT AVOIR UN CORPS.
#
# Constaté en éprouvant ce script : gabarit illisible, `sed` échoue, `rendu`
# vaut la chaîne vide — et le contrôle des marques `@@` la trouve
# irréprochable, puisqu'une chaîne vide n'en contient aucune. On déposait
# alors un fragment sshd VIDE, en annonçant « Posé ». Un durcissement qui
# n'existe pas mais qu'on croit posé est pire que pas de durcissement du tout.
if [[ ! -r "$GABARIT" ]]; then
    mal "Gabarit introuvable ou illisible : $GABARIT"
    note "Ce script rend le fichier livré à côté de lui. S'il a été déplacé,"
    note "rendez-le depuis le dépôt : ./deploy/ssh/rendre-pont.sh"
    exit 2
fi

rendu="$(sed \
    -e "s|@@COMPTE_PONT@@|$COMPTE_PONT|g" \
    -e "s|@@PORT_API@@|$PORT_API|g" \
    -e "s|@@PORT_COCKPIT@@|$PORT_COCKPIT|g" \
    -e "s|@@BASE@@|$BASE|g" \
    "$GABARIT")"

if ! printf '%s' "$rendu" | grep -q '^Match User '; then
    mal "Le rendu ne contient pas le bloc « Match User » du gabarit."
    note "Rien n'a été écrit : un fragment sshd amputé de son Match retire le"
    note "durcissement au lieu de le poser."
    exit 2
fi

if [[ "$rendu" == *"@@"* ]]; then
    mal "Le gabarit contient encore des marques non remplacées :"
    printf '%s\n' "$rendu" | grep -n '@@' | sed 's/^/      /' >&2
    exit 2
fi

if (( ! POSER )); then
    printf '%s\n' "$rendu"
    note ""
    note "Ceci n'a rien écrit. Pour poser le fichier :"
    note "    sudo ARAC_ENV_FILE=$ARAC_ENV_FILE $0 --poser"
    note "Destination : $DESTINATION"
    note "Compte du tunnel : $COMPTE_PONT  (créez-le s'il n'existe pas :"
    note "    sudo adduser --disabled-password --gecos '' $COMPTE_PONT)"
    exit 0
fi

# --- LE REFUS D'ÉCRASER -----------------------------------------------------
if [[ -e "$DESTINATION" ]]; then
    mal "Ce fichier existe déjà : $DESTINATION"
    note "Il appartient à une installation — peut-être la vôtre, peut-être"
    note "celle d'un autre cerveau de cette machine. L'écraser retirerait en"
    note "silence le durcissement qu'il porte : ForceCommand, PermitTTY no,"
    note "PermitOpen, ClientAliveInterval."
    note ""
    note "Regardez-le, puis décidez :"
    note "    sudo diff -u $DESTINATION - <<< \"\$(ARAC_ENV_FILE=$ARAC_ENV_FILE $0)\""
    note "    sudo rm $DESTINATION   # seulement si vous savez à qui il est"
    exit 3
fi

umask 022
printf '%s\n' "$rendu" > "$DESTINATION" || { mal "Écriture refusée : $DESTINATION (root ?)"; exit 2; }
chmod 0644 "$DESTINATION"
chown root:root "$DESTINATION" 2>/dev/null || true
bien "Posé : $DESTINATION"
note "Compte du tunnel : $COMPTE_PONT — ports 127.0.0.1:$PORT_API et 127.0.0.1:$PORT_COCKPIT"
note ""
note "MAINTENANT, ET DANS CET ORDRE, EN GARDANT UNE SESSION SSH OUVERTE :"
note "    sudo sshd -t"
note "    sudo systemctl reload ssh"
note "puis testez la reconnexion depuis un SECOND terminal avant de fermer"
note "le premier. Une erreur de syntaxe ici referme la seule porte."
exit 0
