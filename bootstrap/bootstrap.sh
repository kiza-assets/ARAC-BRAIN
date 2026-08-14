#!/usr/bin/env bash
# ===========================================================================
# bootstrap.sh — donner corps au cerveau décrit par l'entretien.
#
# L'entretien (bootstrap/wizard.py) produit une DESCRIPTION : votre nom, celui
# de votre cerveau, le poste d'où viennent vos conversations, et la forme de
# votre mémoire. Il n'installe rien.
#
# Ce script incarne cette description. Il fait onze choses, dans cet ordre, et
# chacune dit POURQUOI elle existe, CE QU'ELLE CONSTRUIT et CE QUE CELA
# CHANGERA dans le comportement de votre cerveau :
#
#    1. constater les prérequis        6. semer votre taxonomie
#    2. lire la description            7. engendrer les secrets
#    3. la base et ses rôles           8. les clés externes et leur coût
#    4. pgvector                       9. installer les services
#    5. les migrations                10. vérifier, et rendre un rapport
#                                     11. dire la suite
#
# Quatre promesses :
#   · IDEMPOTENT — relançable sans dégât ; aucune base n'est jamais écrasée
#     sans qu'on ait dit ce qu'elle contient et obtenu un accord explicite.
#   · REPRENABLE — une étape échoue, on répare, on relance : il reprend là.
#   · SIMULABLE  — `--dry-run` montre tout et n'écrit rien. La base n'est
#     alors ouverte qu'en lecture.
#   · RÉPARABLE  — chaque échec dit ce qui a échoué, pourquoi, et le geste
#     exact pour repartir.
#
# Usage :  ./bootstrap/bootstrap.sh --help
# ===========================================================================

set -euo pipefail

# --- Où sommes-nous ? (aucun chemin en dur, jamais) ------------------------
_ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARAC_HOME="${ARAC_HOME:-$(cd "$_ICI/.." && pwd)}"
export ARAC_HOME
ARAC_PG_SUPERUSER="${ARAC_PG_SUPERUSER:-postgres}"

# Les colonnes et les traits de séparation comptent des CARACTÈRES, pas des
# octets : sans locale UTF-8, « Conséquence » vaudrait treize et tout se
# décalerait. On répare silencieusement si la machine le permet.
if [[ "${LC_ALL:-${LANG:-}}" != *[Uu][Tt][Ff]* ]] && locale -a 2>/dev/null | grep -qix 'C.utf8'; then
    export LC_ALL=C.UTF-8
fi

# --- Les bibliothèques ------------------------------------------------------
for _lib in ui core prereqs config database secrets services verify; do
    # shellcheck source=/dev/null
    source "$_ICI/lib/$_lib.sh"
done
unset _lib

analyser_options "$@"
detecter_sudo
etat_charger

# --- Modes courts -----------------------------------------------------------
case "$MODE" in
    etapes)
        printf '\n'
        for e in "${ETAPES[@]}"; do printf '  %-12s %s\n' "$e" "${TITRE_ETAPE[$e]}"; done
        printf '  %-12s %s\n' "(épilogue)" "La suite : brancher le Mac"
        printf '\n'
        exit 0 ;;
    check)
        banniere
        etape_prereqs && exit 0 || exit 1 ;;
    verify)
        # Le contrôle a besoin des chemins calculés par l'étape 2 : on la
        # laisse tourner (elle ne fait que lire), puis on saute au contrôle.
        SEULEMENT="controle" ;;
esac

# ===========================================================================
# Déroulé
# ===========================================================================

banniere

if ! reel; then
    dire "$(_c 35 '[simulation]') Rien ne sera écrit, créé, ni démarré."
    note "La base n'est ouverte qu'en LECTURE, pour pouvoir vous dire ce
qu'elle contient déjà. Relancez sans --dry-run pour agir."
    vide
fi

if [[ -n "$SEULEMENT" ]]; then
    note "Étape unique demandée : $SEULEMENT"
elif [[ -n "$DEPUIS" ]]; then
    note "Reprise demandée à partir de : $DEPUIS"
fi

# L'étape 2 calcule tous les chemins : elle est indispensable à toutes les
# autres, y compris quand on n'en demande qu'une seule.
_a_faire() { # etape
    local e="$1"
    [[ -n "$SEULEMENT" ]] && { [[ "$e" == "$SEULEMENT" ]] && return 0 || return 1; }
    if [[ -n "$DEPUIS" ]]; then
        local vu=0 x
        for x in "${ETAPES[@]}"; do
            [[ "$x" == "$DEPUIS" ]] && vu=1
            [[ "$x" == "$e" ]] && { (( vu )) && return 0 || return 1; }
        done
        return 1
    fi
    return 0
}

INCOMPLETES=()
FAITES=()
IGNOREES=()

# --- Une étape sautée est une leçon perdue : on le dit UNE FOIS, en tête -----
#
# Le fichier d'avancement fait sauter les étapes déjà accomplies. C'est ce qui
# rend le bootstrap reprenable, et c'est juste. Mais le dire seulement en marge
# de chaque ligne rendait le total invisible : sept étapes sur onze pouvaient
# disparaître sans que rien n'annonce l'ampleur du saut.
#
# L'avancement n'est connu qu'APRÈS l'étape 2 (c'est elle qui déduit le nom de
# la base, donc le fichier à lire). Cette annonce se joue donc au premier pas
# concerné, pas avant.
# CE QU'ON COMPTE ICI, ET POURQUOI CE N'EST PAS `etape_faite`.
#
# `ETAPES_FAITES` grossit pendant la course : l'étape 2, accomplie il y a trois
# lignes sous les yeux de l'utilisateur, y entre aussitôt. Compter là-dedans
# faisait dire au bootstrap, à la PREMIÈRE installation d'un clone neuf :
#
#     ⚠ 1 étape(s) sur 10 ont déjà été accomplies ici.
#       config
#       … effacez le fichier d'avancement — il vient de quelqu'un d'autre :
#         rm /opt/…/.bootstrap-install.lew17a.state
#
# — un avertissement faux, au premier lancement, qui prescrit d'effacer son
# propre avancement. En simulation c'était pire : rien n'est jamais écrit en
# simulation, donc le fichier NOMMÉ dans la phrase n'existait pas.
#
# On ne compte donc que ce que le fichier portait AVANT ce lancement.
_SAUTS_ANNONCES=0
annoncer_sauts() {
    (( _SAUTS_ANNONCES )) && return 0
    _SAUTS_ANNONCES=1
    local deja=() e
    for e in "${ETAPES[@]}"; do etape_heritee "$e" && deja+=("$e"); done
    (( ${#deja[@]} == 0 )) && return 0
    vide
    if reel; then
        alerte "$(_c 1 "${#deja[@]} étape(s) sur ${#ETAPES[@]} avaient déjà été accomplies avant ce lancement.")"
        note "  ${deja[*]}
  Elles ne seront ni rejouées ni réexpliquées. Pour tout reprendre depuis
  le début :  $(geste_bootstrap "--rejouer")"
        # LE FICHIER PORTE LE NOM DU CERVEAU, ET IL EST IGNORÉ PAR GIT : un
        # clone frais ne peut PAS l'apporter. S'il est là, ou bien vous avez
        # déjà installé « $ARAC_DB » depuis ce dossier, ou bien ce dossier a
        # été COPIÉ (pas cloné) depuis une machine où il l'était. On dit les
        # deux cas, et on ne prescrit le `rm` que dans le second.
        note "  Ce fichier s'appelle « $(basename "$ETAT_FICHIER") » : il ne concerne que le
  cerveau « $ARAC_DB », et git ne le transporte pas. Si vous n'avez jamais
  installé ce cerveau-là depuis ce dossier — un dossier COPIÉ, pas cloné —
  alors il est étranger, et c'est le seul cas où il faut l'effacer :
    rm $ETAT_FICHIER"
    else
        note "  ${#deja[@]} étape(s) sur ${#ETAPES[@]} étaient déjà marquées accomplies dans
  $ETAT_FICHIER
  avant ce lancement. La simulation les déroule quand même : elle
  n'accomplit rien, elle explique — et une étape sautée serait une leçon
  perdue. (Une simulation n'écrit jamais dans ce fichier.)"
    fi
    vide
}

for etape in "${ETAPES[@]}"; do

    # prereqs et config ne font que constater : elles tournent toujours, car
    # tout le reste dépend des chemins qu'elles calculent.
    if [[ "$etape" != "prereqs" && "$etape" != "config" ]]; then
        _a_faire "$etape" || { IGNOREES+=("$etape"); continue; }
        annoncer_sauts
        # `reel` est dans la condition, et c'est le point : une SIMULATION
        # n'accomplit rien, donc n'a rien à sauter. Sauter une étape en
        # simulation n'économise que son en-tête — c'est-à-dire la seule chose
        # qu'elle produise. `--dry-run` cessait ainsi d'être la démonstration
        # que chaque étape annonce ses trois raisons : un fichier d'avancement
        # oublié le faisait tomber de onze en-têtes à quatre.
        if reel && etape_faite "$etape" && (( ! REJOUER )) && [[ -z "$SEULEMENT" && -z "$DEPUIS" ]]; then
            note "· ${TITRE_ETAPE[$etape]} — déjà accomplie lors d'un passage précédent."
            note "  (pour la rejouer : --from $etape, ou --rejouer pour tout reprendre)"
            IGNOREES+=("$etape")
            continue
        fi
    fi

    rc=0
    "etape_$etape" || rc=$?

    case "$rc" in
        0) FAITES+=("$etape"); etape_marquer "$etape" ;;
        8) INCOMPLETES+=("$etape") ;;
        *) exit "$rc" ;;
    esac

    if [[ "$etape" == "$SEULEMENT" ]]; then break; fi
done

# ===========================================================================
# Bilan
# ===========================================================================

sous_titre "Bilan"

if (( ${#FAITES[@]} )); then
    if reel; then
        bien "Accomplies : ${FAITES[*]}"
    else
        bien "Seraient accomplies : ${FAITES[*]}"
    fi
fi
if (( ${#IGNOREES[@]} )); then
    note "Ignorées   : ${IGNOREES[*]}"
fi
if (( ${#INCOMPLETES[@]} )); then
    vide
    alerte "$(_c 1 "Incomplètes : ${INCOMPLETES[*]}")"
    note "Ces étapes n'ont pas pu aboutir — leur message explique pourquoi et
ce qui manque. Elles seront reprises telles quelles au prochain
lancement ; rien de ce qui a été fait n'est perdu."
fi

# L'épilogue est du texte : il s'affiche aussi en simulation, parce que c'est
# souvent là qu'on comprend à quoi tout cela sert.
if [[ -z "$SEULEMENT" ]] && (( ${#INCOMPLETES[@]} == 0 )); then
    epilogue
elif [[ -z "$SEULEMENT" ]]; then
    vide
    dire "La suite (brancher le Mac, première synchronisation) s'affichera quand"
    dire "les étapes incomplètes auront abouti."
    vide
fi

if ! reel; then
    dire "$(_c 35 '[simulation]') Aucun changement n'a été appliqué."
    dire "Pour agir :"
    cmd "$(geste_bootstrap)"
    vide
    exit 0
fi

(( ${#INCOMPLETES[@]} )) && exit 9
exit 0
