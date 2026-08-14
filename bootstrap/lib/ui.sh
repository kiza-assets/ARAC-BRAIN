# shellcheck shell=bash
# ---------------------------------------------------------------------------
# ui.sh — la voix du bootstrap.
#
# Une installation qui se contente d'afficher « OK » n'apprend rien à personne.
# Chaque étape d'ARAC doit dire trois choses, et ce fichier rend cette règle
# mécanique plutôt que morale : la fonction `etape_entete` REFUSE de s'afficher
# si l'une des trois manque.
#
#   POURQUOI     — la raison d'être de l'étape ;
#   CONSTRUIT    — ce qu'elle laisse derrière elle, concrètement ;
#   CONSÉQUENCE  — ce que cela changera dans le comportement du cerveau.
#
# Aucune dépendance : ni tput, ni couleurs exotiques. Un terminal, c'est tout.
# ---------------------------------------------------------------------------

ARAC_UI_COULEUR="${ARAC_UI_COULEUR:-auto}"

_ui_couleurs_actives() {
    case "$ARAC_UI_COULEUR" in
        jamais) return 1 ;;
        toujours) return 0 ;;
    esac
    [[ -t 1 && -z "${NO_COLOR:-}" ]]
}

_c() { # code texte
    if _ui_couleurs_actives; then printf '\033[%sm%s\033[0m' "$1" "$2"; else printf '%s' "$2"; fi
}

#: Un trait de N caractères. `tr` travaille sur des octets et découperait
#: « ─ » en trois : on répète le caractère à la main.
_trait() { # longueur
    local i; for (( i = 0; i < ${1:-1}; i++ )); do printf '─'; done
}

#: printf '%-20s' compte des OCTETS. Sur « Conséquence » ou « prérequis », les
#: colonnes se décalent. `pad` compte des CARACTÈRES.
pad() { # texte largeur
    local t="$1" n="$2" reste
    printf '%s' "$t"
    reste=$(( n - ${#t} ))
    (( reste > 0 )) && printf '%*s' "$reste" ''
    return 0
}

banniere() {
    printf '\n'
    printf '  %s\n' "$(_c 1 "ARAC — installation de votre cerveau")"
    printf '  %s\n' "$(_c 2 "$(_trait 38)")"
    printf '\n'
}

titre() { printf '\n  %s\n' "$(_c 1 "$1")"; }

sous_titre() {
    printf '\n  %s\n' "$(_c 1 "$1")"
    printf '  %s\n' "$(_c 2 "$(_trait "${#1}")")"
}

dire()   { printf '  %s\n' "${1-}"; }
note()   { local l; while IFS= read -r l; do printf '  %s\n' "$(_c 2 "$l")"; done <<< "${1-}"; }
bien()   { printf '  %s %s\n' "$(_c 32 '✓')" "${1-}"; }
mal()    { printf '  %s %s\n' "$(_c 31 '✗')" "${1-}"; }
alerte() { printf '  %s %s\n' "$(_c 33 '⚠')" "${1-}"; }
action() { printf '  %s %s\n' "$(_c 36 '→')" "${1-}"; }
plan()   { printf '  %s %s\n' "$(_c 35 '⟂')" "${1-}"; }
# Un geste à recopier. Indente CHAQUE ligne : plusieurs appels passent une
# suite de commandes, et seule la première se retrouvait alignée — le reste
# collait à la marge, donnant à lire un bloc bancal là, précisément, où
# l'utilisateur doit avoir confiance dans ce qu'il recopie.
cmd()    { while IFS= read -r _l; do printf '      %s\n' "$(_c 36 "$_l")"; done <<<"${1-}"; }
vide()   { printf '\n'; }

# --- L'en-tête d'étape : la règle F3 rendue mécanique -----------------------

etape_entete() { # numero total titre pourquoi construit consequence
    local numero="$1" total="$2" titre="$3" pourquoi="$4" construit="$5" consequence="$6"
    if [[ -z "$pourquoi" || -z "$construit" || -z "$consequence" ]]; then
        printf '  BOGUE INTERNE : l'\''étape « %s » n'\''annonce pas ses trois raisons.\n' "$titre" >&2
        exit 70
    fi
    local ligne="ÉTAPE ${numero} / ${total} — ${titre}"
    printf '\n'
    printf '  %s\n' "$(_c 1 "$ligne")"
    printf '  %s\n' "$(_c 2 "$(_trait "${#ligne}")")"
    _triade "Pourquoi" "$pourquoi"
    _triade "Construit" "$construit"
    _triade "Conséquence" "$consequence"
    printf '\n'
}

_triade() { # etiquette texte
    local etiquette="$1" texte="$2" premiere=1 ligne
    while IFS= read -r ligne; do
        if (( premiere )); then
            printf '  %s %s\n' "$(_c 2 "$(pad "$etiquette" 13)")" "$ligne"
            premiere=0
        else
            printf '  %s %s\n' "$(pad '' 13)" "$ligne"
        fi
    done <<< "$texte"
}

# --- Une leçon : un fait mesuré sur le cerveau de référence -----------------
#
# Ces chiffres sont des mesures, pas des menaces. On les cite pour que le
# prochain cerveau ne refasse pas la même erreur.

lecon() { # fait lecon
    printf '  %s %s\n' "$(_c 33 '◆')" "$(_c 1 "$1")"
    local l
    while IFS= read -r l; do printf '    %s\n' "$(_c 2 "$l")"; done <<< "$2"
}

# --- Un échec qui répare ----------------------------------------------------

echec() { # quoi pourquoi geste
    printf '\n'
    mal "$(_c 1 "ÉCHEC : $1")"
    vide
    _triade "Pourquoi" "${2:-cause inconnue}"
    vide
    dire "$(_c 1 'Le geste exact pour réparer :')"
    local l
    while IFS= read -r l; do cmd "$l"; done <<< "${3:-—}"
    vide
    return 0
}
