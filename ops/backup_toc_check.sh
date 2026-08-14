#!/usr/bin/env bash
# ============================================================================
# LE SOMMAIRE D'UN DUMP — vérifier qu'il contient bien ce qu'on croit
#
#     pg_restore --list mon.dump | ops/backup_toc_check.sh
#
# Sortie : la liste des tables MANQUANTES, une par ligne. Code 0 si aucune.
#
# CE QUE CE FICHIER ENSEIGNE
# --------------------------
# Un dump qui s'ouvre n'est pas un dump complet. `pg_restore --list` réussit
# parfaitement sur un dump pris AVANT une migration : le fichier est lisible,
# bien formé, et il lui manque une table entière. Restauré tel quel, il rend un
# cerveau amputé — et personne ne s'en aperçoit avant d'en avoir besoin.
#
# Le contrôle porte donc sur le SOMMAIRE (le « table of contents » que pg_dump
# écrit en tête du fichier), pas sur la lisibilité. C'est la seule vérification
# de sauvegarde qu'on puisse faire sans PostgreSQL, sans base et sans réseau —
# donc la seule qu'on puisse tester à volonté. Elle est ici séparée du reste
# pour cette raison, et elle porte son propre banc d'essai :
#
#     ops/backup_toc_check.sh selftest
#
# LE PIÈGE QU'ELLE ÉVITE (leçon coûteuse, gardée du cerveau de référence)
# ----------------------------------------------------------------------
# Chercher « nodes » dans le sommaire par simple sous-chaîne est satisfait par
# la ligne de `nodes_heartbeat_history`. Un dump amputé de `arac.nodes` passait
# donc le contrôle tant qu'une table au nom plus long existait. Le motif ci-
# dessous ancre la fin du nom sur une espace ou une fin de ligne : `pg_restore
# --list` écrit le propriétaire juste après le nom, ou rien, jamais collé.
#
# `set -e` n'est armé que si ce fichier est EXÉCUTÉ : `source` ne crée pas de
# sous-shell, et un fichier de fonctions qui arme des options les impose à tout
# le script qui le source. Voir la note détaillée dans ops/restore_guard.sh.
# ============================================================================
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    set -euo pipefail
fi


# ----------------------------------------------------------------------------
# Ce qu'un dump doit contenir pour mériter le nom de sauvegarde
# ----------------------------------------------------------------------------
#
# Ce n'est pas « toutes les tables » : la liste des tables change à chaque
# migration, et un contrôle qui les exige toutes est rouge en permanence. Ce
# sont les tables SANS LESQUELLES on ne peut pas reconstruire un cerveau :
#
#   memory_atoms      le savoir lui-même — ce qu'on a payé pour extraire
#   memory_atom_reprs les représentations qui le rendent rappelable
#   conversations     le substrat : d'où vient chaque atome
#   raw_messages      le contenu réel des conversations
#   nodes             qui a le droit d'écrire dans ce cerveau
#   scopes            la taxonomie — sans elle, les atomes n'ont plus d'adresse
#   run_receipts      l'histoire de la digestion : ce qui a marché, ce qui a raté
#   ingest_receipts   l'histoire de ce qui est entré, accepté comme refusé
#   context_receipts  l'histoire des rappels servis
#   alembic_version   la version de schéma. Sans elle, on restaure des données
#                     sans savoir quel code sait les lire.
#
# À adapter à VOTRE installation via ARAC_BACKUP_REQUIRED_TABLES (noms séparés
# par des espaces). Retirer une table de cette liste est une décision : vous
# déclarez pouvoir vivre sans elle après un désastre.
_DEFAULT_REQUIRED=(
    memory_atoms
    memory_atom_reprs
    conversations
    raw_messages
    nodes
    scopes
    run_receipts
    ingest_receipts
    context_receipts
    alembic_version
)

arac_required_tables() {
    if [ -n "${ARAC_BACKUP_REQUIRED_TABLES:-}" ]; then
        # shellcheck disable=SC2086
        printf '%s\n' $ARAC_BACKUP_REQUIRED_TABLES
    else
        printf '%s\n' "${_DEFAULT_REQUIRED[@]}"
    fi
}


# arac_toc_missing_tables [schéma] [table...] — lit le sommaire sur stdin.
#
# Imprime les tables demandées ABSENTES, une par ligne. Retourne 0 si aucune.
# Fonction pure : ni base, ni réseau, ni fichier. C'est ce qui la rend testable.
arac_toc_missing_tables() {
    local schema="${1:-${ARAC_DB_SCHEMA:-arac}}"
    shift || true
    local toc tables=() missing=() t
    toc="$(cat -)"
    if [ "$#" -gt 0 ]; then
        tables=("$@")
    else
        mapfile -t tables < <(arac_required_tables)
    fi
    for t in "${tables[@]}"; do
        # « TABLE DATA <schéma> <table> <propriétaire> » — le nom de table est
        # ancré à droite pour ne pas être satisfait par un nom plus long.
        grep -qE "TABLE DATA ${schema} ${t}([[:space:]]|\$)" <<<"$toc" || missing+=("$t")
    done
    if [ "${#missing[@]}" -gt 0 ]; then
        printf '%s\n' "${missing[@]}"
        return 1
    fi
    return 0
}


# ----------------------------------------------------------------------------
# Banc d'essai — aucune base, aucun fichier, aucun réseau
# ----------------------------------------------------------------------------
_selftest() {
    local fail=0 out
    _assert() {  # _assert <intitulé> <attendu> <obtenu>
        if [ "$2" = "$3" ]; then
            printf '  ok   %s\n' "$1"
        else
            printf '  FAIL %s : attendu [%s], obtenu [%s]\n' "$1" "$2" "$3"
            fail=1
        fi
    }

    # Le propriétaire est un nom NEUTRE, et volontairement : ce sommaire est
    # une pièce d'essai, pas une installation. Y écrire le nom d'un rôle réel
    # ferait croire qu'un rôle s'appelle ainsi partout — c'est cette croyance,
    # sur `arac_app`, qui a coûté une production. Le contrôle ne lit d'ailleurs
    # que le schéma et la table : le propriétaire ne l'intéresse pas.
    local toc_complet
    toc_complet=$(cat <<'EOF'
;
; Archive created at 2026-01-01 04:00:00 UTC
;
215; 1259 16400 TABLE arac memory_atoms unproprietaire
3401; 0 16400 TABLE DATA arac memory_atoms unproprietaire
3402; 0 16401 TABLE DATA arac memory_atom_reprs unproprietaire
3403; 0 16402 TABLE DATA arac conversations unproprietaire
3404; 0 16403 TABLE DATA arac raw_messages unproprietaire
3405; 0 16404 TABLE DATA arac nodes unproprietaire
3406; 0 16405 TABLE DATA arac nodes_heartbeat_history unproprietaire
3407; 0 16406 TABLE DATA arac scopes unproprietaire
3408; 0 16407 TABLE DATA arac run_receipts unproprietaire
3409; 0 16408 TABLE DATA arac ingest_receipts unproprietaire
3410; 0 16409 TABLE DATA arac context_receipts unproprietaire
3411; 0 16410 TABLE DATA arac alembic_version unproprietaire
EOF
)
    out=$(arac_toc_missing_tables <<<"$toc_complet" || true)
    _assert "un sommaire complet ne manque de rien" "" "$out"

    # Le piège du préfixe : `nodes` retiré, `nodes_heartbeat_history` restant.
    local toc_ampute
    toc_ampute=$(grep -v 'TABLE DATA arac nodes unproprietaire' <<<"$toc_complet")
    out=$(arac_toc_missing_tables <<<"$toc_ampute" || true)
    _assert "une table absente est vue même si un nom plus long la contient" "nodes" "$out"

    # Le cas réel : dump pris avant la migration qui crée context_receipts.
    local toc_pre_migration
    toc_pre_migration=$(grep -v 'context_receipts' <<<"$toc_complet")
    out=$(arac_toc_missing_tables <<<"$toc_pre_migration" || true)
    _assert "un dump antérieur à une migration est déclaré incomplet" \
        "context_receipts" "$out"

    # Code de sortie : 1 quand il manque quelque chose, 0 sinon.
    if arac_toc_missing_tables <<<"$toc_complet" >/dev/null; then
        printf '  ok   code de sortie 0 sur un dump complet\n'
    else
        printf '  FAIL code de sortie non nul sur un dump complet\n'; fail=1
    fi
    if arac_toc_missing_tables <<<"$toc_ampute" >/dev/null; then
        printf '  FAIL code de sortie 0 sur un dump amputé\n'; fail=1
    else
        printf '  ok   code de sortie 1 sur un dump amputé\n'
    fi

    # Un autre schéma : le contrôle suit le paramètre, il ne suppose pas « arac ».
    out=$(arac_toc_missing_tables "cerveau" memory_atoms <<<"$toc_complet" || true)
    _assert "le schéma n'est pas supposé, il est passé" "memory_atoms" "$out"

    if [ "$fail" -eq 0 ]; then
        printf 'backup_toc_check : tout passe.\n'
    else
        printf 'backup_toc_check : ÉCHEC.\n'
    fi
    return "$fail"
}


# ----------------------------------------------------------------------------
# Exécution directe : CLI (sommaire sur stdin) ou banc d'essai.
# Sourcé : rien ne se passe, seules les fonctions sont définies.
# ----------------------------------------------------------------------------
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    case "${1:-}" in
        selftest) _selftest ;;
        *)        arac_toc_missing_tables "${ARAC_DB_SCHEMA:-arac}" "$@" ;;
    esac
fi
