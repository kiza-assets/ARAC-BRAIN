#!/usr/bin/env bash
# ============================================================================
# LES GARDE-FOUS DE LA RESTAURATION — quatre fonctions pures, un banc d'essai
#
#     ops/restore_guard.sh selftest
#
# Aucune base, aucun réseau, aucun fichier. Ce sont des fonctions qui décident,
# pas des scripts qui agissent — et c'est pour cela qu'on peut les éprouver
# entièrement, ce qui est rarement vrai du code de sauvegarde.
#
# POURQUOI DES GARDES SÉPARÉS
# ---------------------------
# Une restauration est l'unique opération de tout ce dépôt qui DÉTRUIT. Elle
# écrase, et ce qu'elle écrase ne revient pas. Les trois façons de se tromper
# sont connues :
#
#   1. viser la mauvaise base           → on restaure PAR-DESSUS le cerveau vivant
#   2. promouvoir un dump tronqué       → on remplace un cerveau entier par un moignon
#   3. injecter un nom de base tordu    → on exécute du SQL qu'on n'a pas écrit
#
# Chacune a sa fonction ci-dessous, et chacune a ses cas de test. Le reste des
# scripts s'y adosse ; aucun ne re-décide dans son coin.
#
# NOTE — pourquoi `set -e` n'est posé QUE si ce fichier est exécuté :
# `source` ne crée pas de sous-shell. Un fichier de fonctions qui pose
# `set -euo pipefail` au premier plan impose donc ses options à TOUT le script
# qui le source, souvent des dizaines de lignes plus loin, sans que personne ne
# fasse le lien. Ce dépôt s'est fait avoir une fois pendant son écriture : le
# chien de garde s'arrêtait en silence sur un `ls` sans résultat, parce que ce
# fichier-ci avait armé `-e` chez lui. Les options d'un script lui appartiennent.
# ============================================================================
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    set -euo pipefail
fi


# ----------------------------------------------------------------------------
# 1. La cible n'est jamais la base vivante
# ----------------------------------------------------------------------------
#
# arac_target_forbidden <cible> [<base_interdite>...] → code 0 si INTERDIT.
#
# La base vivante n'est pas devinée : elle est extraite du DSN de l'installation
# (`arac_dsn_db_name`). Un framework ne peut pas écrire « arac » en dur — chez
# vous, la base s'appellera peut-être `cerveau` ou `memoire_prod`. Le garde
# protège la VÔTRE parce qu'il la lit dans VOTRE configuration.
#
# IL PREND DÉSORMAIS PLUSIEURS NOMS, ET C'EST UNE CORRECTION MESURÉE.
# Il n'en connaissait qu'un : la base vivante. Le GABARIT de restauration
# (`<prefixe>_restore_template`) passait donc le refus — et lui, contrairement
# à la base vivante, appartient au rôle sous lequel la vérification tourne :
# PostgreSQL ne refusait rien. Une seule commande sortie en erreur l'effaçait,
# et la vérification de sauvegarde retombait aussitôt sur « permission denied
# to create extension "vector" ». Un garde qui ne connaît qu'un nom protège
# un nom, pas une classe.
#
# CE GARDE NE SUFFIT PAS, ET C'EST VOULU : il décide sur des NOMS, sans
# serveur. La question qui compte vraiment — « cette base existe-t-elle déjà,
# et à qui appartient-elle ? » — se pose au serveur, dans
# `ops/restore_verify.sh`, avant toute création et avant d'armer le moindre
# piège de nettoyage. Les deux sont indépendants exprès.
#
# Ce garde vaut pour la restauration de TEST, celle qui tourne toute seule
# chaque semaine. La restauration réelle après désastre, elle, ne s'automatise
# pas : cf docs/SAUVEGARDE.md, section « la restauration qu'on exécute en
# panique ».
arac_target_forbidden() {
    local target="${1:-}" interdit
    [ -n "$target" ] || return 0        # une cible vide est interdite
    shift || true
    for interdit in "$@"; do
        [ -n "$interdit" ] && [ "$target" = "$interdit" ] && return 0
    done
    return 1
}


# ----------------------------------------------------------------------------
# 2. Le nom de base est un identifiant, pas une phrase
# ----------------------------------------------------------------------------
#
# arac_db_name_safe <nom> → code 0 si acceptable.
#
# `CREATE DATABASE` n'accepte pas de paramètre lié : le nom est forcément
# interpolé dans du SQL. Tout ce qui n'est pas un identifiant PostgreSQL banal
# est donc refusé AVANT d'approcher une connexion. Sans ce filtre, un nom de
# base venu d'une variable d'environnement — donc d'un fichier, donc d'ailleurs —
# est une injection SQL exécutée en tant que rôle administrateur.
#
# 63 caractères : la limite réelle de PostgreSQL (NAMEDATALEN - 1). Au-delà,
# le nom est tronqué SILENCIEUSEMENT, et deux bases jetables différentes
# peuvent devenir la même.
arac_db_name_safe() {
    local name="${1:-}"
    [[ "$name" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]
}


# ----------------------------------------------------------------------------
# 3. Un dump qui a maigri est suspect jusqu'à preuve du contraire
# ----------------------------------------------------------------------------
#
# arac_requires_force <entrant> <référence> [seuil_pct] → code 0 si un forçage
# explicite est requis.
#
# Le cas réel : le dump du jour contient deux fois moins de messages que le
# dernier dump vérifié. Deux explications, très inégales :
#   — la digestion a purgé quelque chose de volumineux (rare, explicable) ;
#   — le dump est tronqué, ou pris sur une base à moitié restaurée (fréquent).
#
# Dans le doute, le script REFUSE de promouvoir ce dump comme référence et
# demande `ARAC_RESTORE_FORCE=1`. Le seuil par défaut est 50 % : il n'est pas
# tiré d'une convention, il vient de ce qu'un cerveau ne perd jamais la moitié
# de son substrat en une journée sans qu'un humain le sache déjà.
arac_requires_force() {
    local incoming="${1:-0}" reference="${2:-0}" pct="${3:-50}"
    case "$incoming$reference" in *[!0-9]*) return 1 ;; esac
    [ "$reference" -le 0 ] && return 1          # pas de référence : rien à comparer
    [ $(( incoming * 100 )) -lt $(( reference * pct )) ]
}


# ----------------------------------------------------------------------------
# 4. La médiane, pour se calibrer sur soi-même
# ----------------------------------------------------------------------------
#
# arac_median — lit des entiers sur stdin, imprime la médiane. Vide → rien.
#
# Elle sert aux seuils qui n'ont PAS de bonne valeur universelle : la taille
# d'un dump, la croissance quotidienne d'une base. Personne ne peut vous dire
# quelle taille doit faire votre cerveau. En revanche, votre cerveau d'hier
# peut le dire — et la médiane, contrairement à la moyenne, ne se laisse pas
# emporter par un seul jour anormal.
arac_median() {
    local -a v=()
    mapfile -t v < <(grep -E '^-?[0-9]+$' || true)
    local n="${#v[@]}"
    [ "$n" -eq 0 ] && return 1
    mapfile -t v < <(printf '%s\n' "${v[@]}" | sort -n)
    if [ $(( n % 2 )) -eq 1 ]; then
        printf '%s' "${v[$(( n / 2 ))]}"
    else
        printf '%s' $(( ( ${v[$(( n / 2 - 1 ))]} + ${v[$(( n / 2 ))]} ) / 2 ))
    fi
}


# ----------------------------------------------------------------------------
# Banc d'essai
# ----------------------------------------------------------------------------
_selftest() {
    local fail=0
    _ok()   { printf '  ok   %s\n' "$1"; }
    _bad()  { printf '  FAIL %s\n' "$1"; fail=1; }
    _true() { if eval "$2"; then _ok "$1"; else _bad "$1"; fi; }
    _false(){ if eval "$2"; then _bad "$1"; else _ok "$1"; fi; }

    # --- cible interdite
    _true  "la base vivante est refusée comme cible de test" \
           'arac_target_forbidden cerveau cerveau'
    _false "une base jetable est acceptée" \
           'arac_target_forbidden arac_restore_1234 cerveau'
    _true  "une cible vide est refusée" \
           'arac_target_forbidden "" cerveau'
    _false "sans base vivante connue, seule la cible vide est refusée" \
           'arac_target_forbidden arac_restore_1234 ""'
    # Le gabarit : deuxième nom interdit. Il a réellement été détruit par un
    # nettoyage qui ne le connaissait pas.
    _true  "le gabarit de restauration est refusé comme cible" \
           'arac_target_forbidden cerveau_restore_template cerveau cerveau_restore_template'
    _false "une base jetable passe même quand deux noms sont interdits" \
           'arac_target_forbidden cerveau_restore_1234 cerveau cerveau_restore_template'
    _true  "la base vivante reste refusée quand le gabarit est aussi donné" \
           'arac_target_forbidden cerveau cerveau cerveau_restore_template'
    _false "un nom vide dans la liste d'interdits n'interdit rien" \
           'arac_target_forbidden cerveau_restore_1234 "" ""'

    # --- nom de base
    _true  "un identifiant banal passe"        'arac_db_name_safe arac_restore_1754500000'
    _false "un nom avec un espace est refusé"  'arac_db_name_safe "arac restore"'
    _false "une injection est refusée"         'arac_db_name_safe "x; DROP DATABASE arac"" --"'
    _false "un nom vide est refusé"            'arac_db_name_safe ""'
    _false "un nom de 64 caractères est refusé" \
           'arac_db_name_safe "$(printf "a%.0s" $(seq 64))"'
    _true  "un nom de 63 caractères passe" \
           'arac_db_name_safe "$(printf "a%.0s" $(seq 63))"'
    _false "une majuscule est refusée (elle serait repliée en silence)" \
           'arac_db_name_safe "Arac_Restore"'

    # --- forçage
    _true  "moitié moins que la référence exige un forçage" 'arac_requires_force 400 1000'
    _false "juste au seuil, pas de forçage"                 'arac_requires_force 500 1000'
    _false "au-dessus du seuil, pas de forçage"             'arac_requires_force 900 1000'
    _false "sans référence, rien à comparer"                'arac_requires_force 400 0'
    _true  "le seuil est réglable"                          'arac_requires_force 800 1000 90'
    _false "une valeur non numérique ne déclenche rien"      'arac_requires_force abc 1000'

    # --- médiane
    local m
    m=$(printf '5\n1\n3\n' | arac_median); [ "$m" = 3 ] \
        && _ok "médiane impaire" || _bad "médiane impaire (obtenu $m)"
    m=$(printf '10\n2\n4\n8\n' | arac_median); [ "$m" = 6 ] \
        && _ok "médiane paire" || _bad "médiane paire (obtenu $m)"
    m=$(printf '100\n1\n1\n1\n1\n' | arac_median); [ "$m" = 1 ] \
        && _ok "un jour anormal n'emporte pas la médiane" \
        || _bad "un jour anormal n'emporte pas la médiane (obtenu $m)"
    printf '' | arac_median >/dev/null 2>&1 \
        && _bad "une entrée vide devrait échouer" \
        || _ok "une entrée vide échoue au lieu d'inventer un chiffre"

    if [ "$fail" -eq 0 ]; then
        printf 'restore_guard : tout passe.\n'
    else
        printf 'restore_guard : ÉCHEC.\n'
    fi
    return "$fail"
}


if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    case "${1:-selftest}" in
        selftest)         _selftest ;;
        target-forbidden) shift; arac_target_forbidden "$@" ;;
        db-name-safe)     arac_db_name_safe "${2:-}" ;;
        requires-force)   arac_requires_force "${2:-}" "${3:-}" "${4:-50}" ;;
        median)           arac_median ;;
        *) echo "usage: restore_guard.sh {selftest|target-forbidden|db-name-safe|requires-force|median}" >&2; exit 64 ;;
    esac
fi
