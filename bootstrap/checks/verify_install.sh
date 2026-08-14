#!/usr/bin/env bash
# ===========================================================================
# verify_install.sh — ce cerveau est-il sain ?
#
# Écrit pour vivre SEUL. On le lance après l'installation, mais surtout des
# mois plus tard, sans rien réinstaller, pour répondre à une seule question.
#
# Il ne répare rien, ne modifie rien, n'écrit rien. Il regarde, il compte, et
# il dit. Deux de ses contrôles ne servent qu'à vous épargner les erreurs qui
# ont coûté le plus cher au cerveau de référence :
#
#   · les souvenirs posés sur une racine, donc invisibles au rappel (9 % du
#     total sur le cerveau de référence — le piège n°1) ;
#   · les souvenirs qui ont perdu leur provenance, donc invérifiables (76 %).
#
# CE CONTRÔLE REFUSE PLUTÔT QUE DE DEVINER — et c'est le point.
#
# Il a longtemps fait pire que rien : quand `config/brain.toml` manquait, il
# retombait sur des valeurs par défaut (base « arac », secrets dans
# /etc/arac/arac) et rendait un verdict complet — sur une installation qui
# n'existait pas. Un outil de vérification qui se trompe de sujet est plus
# dangereux qu'un outil absent : l'absent envoie chercher, le menteur rassure.
#
# Il s'arrête donc net, sans rien contrôler, tant qu'il ne sait pas DE QUEL
# cerveau on parle. Un verdict qu'on ne peut pas fonder ne se rend pas.
#
# LA MÊME RÈGLE VAUT CONTRÔLE PAR CONTRÔLE — c'est la doctrine de ce fichier :
#
#     ✓  j'ai mesuré, et c'est bon
#     ✗  j'ai mesuré, et c'est cassé
#     ⚠  JE N'AI PAS PU MESURER — je ne conclus donc rien
#
# Le troisième état n'est pas une commodité, c'est le seul qui empêche l'outil
# de mentir. La plupart des commandes d'ici (`psql`, `lire_var`, `ss`) rendent
# une chaîne VIDE aussi bien quand la réponse est « non » que quand elles n'ont
# pas pu s'exécuter. Lire ce vide comme un résultat, c'est annoncer une panne
# qui n'existe pas — ou, pire, annoncer que tout va bien sans avoir regardé.
# Chaque contrôle ci-dessous sépare donc explicitement les deux, et le code de
# sortie de la commande est TOUJOURS capturé, jamais deviné depuis sa sortie.
#
# Sortie : 0 si tout est sain (des avertissements restent possibles),
#          1 si au moins un contrôle a échoué,
#          2 si le contrôle n'a PAS PU se faire — rien n'a été jugé.
#
# Usage :  ./bootstrap/checks/verify_install.sh [--simulation]
# ===========================================================================

set -uo pipefail

_ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARAC_HOME="${ARAC_HOME:-$(cd "$_ICI/../.." && pwd)}"

# shellcheck source=/dev/null
source "$_ICI/../lib/ui.sh"
# shellcheck source=/dev/null
source "$_ICI/../lib/core.sh"

SIMULATION_SEULE=0
[[ "${1:-}" == "--simulation" ]] && SIMULATION_SEULE=1

ARAC_PG_SUPERUSER="${ARAC_PG_SUPERUSER:-postgres}"
ARAC_SCHEMA="${ARAC_SCHEMA:-arac}"
# NI HÔTE NI PORT PAR DÉFAUT ICI — voir `decouvrir`. Ils étaient posés à
# 127.0.0.1:5432 avant même d'avoir ouvert le fichier d'environnement du
# cerveau, ce qui rendait la lecture qui suit incapable de les corriger
# (`${X:-…}` ne remplace que le vide). Un cerveau installé sur un cluster
# dédié — le geste que ce dépôt recommande — était donc contrôlé contre le
# cluster 5432, c'est-à-dire contre celui du voisin.
# ARAC_ROLE_PREFIX, ARAC_API_PORT et ARAC_COCKPIT_PORT n'ont PAS de valeur par
# défaut ici, et c'est le correctif. Ce contrôle en avait — les mêmes pour tous
# les cerveaux : il inspectait donc `arac_app` et le port 8000 quel que soit le
# cerveau examiné, c'est-à-dire, sur une machine qui en porte deux, ceux du
# voisin. Un contrôle qui se trompe de cerveau est pire qu'un contrôle absent :
# il rend un verdict, et on le croit. Ces trois valeurs sont lues dans le
# fichier d'environnement du cerveau, ou déduites de son nom (voir decouvrir).

OK=0; AVERTS=0; ECHECS=0

ok()     { printf '  %s %s %s\n' "$(_c 32 '✓')" "$(pad "$1" 40)" "$(_c 2 "${2-}")"; OK=$((OK+1)); }
avert()  { printf '  %s %s %s\n' "$(_c 33 '⚠')" "$(pad "$1" 40)" "${2-}"; AVERTS=$((AVERTS+1)); }
rate()   { printf '  %s %s %s\n' "$(_c 31 '✗')" "$(pad "$1" 40)" "${2-}"; ECHECS=$((ECHECS+1)); }
remede() { printf '      %s\n' "$(_c 36 "$1")"; }

# ---------------------------------------------------------------------------
# Découverte de la configuration
# ---------------------------------------------------------------------------

#: Rend la main seulement si l'on sait de quel cerveau on parle. Sinon on
#: sort en 2 : « je n'ai rien pu juger », qui n'est pas « tout va mal » et
#: n'est surtout pas « tout va bien ».
exiger_description() {
    local brain="$ARAC_HOME/config/brain.toml"
    local raison=""

    if [[ ! -e "$brain" ]]; then
        raison="Le fichier $brain n'existe pas."
    elif [[ ! -r "$brain" ]]; then
        raison="Le fichier $brain existe mais n'est pas lisible par $(id -un)."
    else
        local sortie
        if ! sortie="$(python3 -c "$_PY_LIRE_BRAIN" "$brain" 2>&1)"; then
            raison="Le fichier $brain est illisible comme TOML :
$sortie"
        else
            eval "$sortie"
            [[ -z "${BRAIN_NOM:-}" ]]   && raison="brain.name manque dans $brain."
            [[ -z "${BRAIN_OWNER:-}" ]] && raison="brain.owner manque dans $brain."
            [[ -z "${BRAIN_NODE:-}" ]]  && raison="source.node_id manque dans $brain."
        fi
    fi

    [[ -z "$raison" ]] && return 0

    vide
    mal "$(_c 1 'Ce contrôle ne peut pas se faire.')"
    vide
    _triade "Pourquoi" "$raison"
    vide
    note "Ce script déduit TOUT de ce fichier : le nom de la base, le dossier des
secrets, le préfixe des unités systemd. Sans lui, il ne saurait pas quel
cerveau examiner — il examinerait un cerveau générique, nommé « arac »,
dont les secrets vivraient dans /etc/arac/arac, et il vous rendrait un
verdict sur cette fiction. C'est exactement ce qu'il faisait avant, et
c'est pire que ne rien dire : un « ✓ tout va bien » sur une installation
qui n'existe pas envoie chercher la panne partout ailleurs."
    vide
    dire "$(_c 1 'Le geste, selon votre situation :')"
    vide
    dire "  · rien n'est encore installé — commencez par l'entretien :"
    cmd "python3 bootstrap/wizard.py"
    vide
    dire "  · le cerveau est installé AILLEURS que dans le dépôt courant :"
    cmd "ARAC_HOME=/chemin/vers/l/installation $0"
    vide
    dire "  · le fichier existe mais appartient à root :"
    cmd "sudo $0"
    vide
    dire "  · vous vouliez seulement voir CE QUI serait contrôlé, sans"
    dire "    installation :"
    cmd "$0 --simulation"
    vide
    exit 2
}

decouvrir() {
    exiger_description
    ARAC_DB="${ARAC_DB:-$(printf '%s' "$BRAIN_NOM" | tr -c 'a-zA-Z0-9' '_' | sed 's/_*$//')}"
    ARAC_DB="${ARAC_DB,,}"
    ARAC_ETC="${ARAC_ETC:-/etc/arac/$ARAC_DB}"
    ARAC_ENV_FILE="${ARAC_ENV_FILE:-$ARAC_ETC/arac.env}"
    ARAC_SECRETS_ROLES="${ARAC_SECRETS_ROLES:-$ARAC_ETC/roles.env}"
    ARAC_SECRETS_COCKPIT="${ARAC_SECRETS_COCKPIT:-$ARAC_ETC/cockpit.env}"
    # ARAC_BACKUP_DIR et ARAC_LOG_DIR ne sont PLUS déduits ici : le bootstrap
    # les écrit dans le fichier d'environnement, et ce qu'il a retenu l'emporte
    # sur ce qu'on recalculerait. La déduction reste, en repli, plus bas.

    # CE QUE LE CERVEAU A RETENU L'EMPORTE SUR CE QU'ON RECALCULERAIT.
    #
    # Les ports ne se déduisent d'aucun nom : ils ont été ATTRIBUÉS, après
    # constat de disponibilité, et écrits dans le fichier d'environnement de ce
    # cerveau. Les recalculer ici reviendrait à contrôler une installation
    # imaginaire — celle qui aurait eu les numéros par défaut.
    if [[ -r "$ARAC_ENV_FILE" ]]; then
        [[ -z "${ARAC_API_PORT:-}" ]]     && ARAC_API_PORT="$(lire_var "$ARAC_ENV_FILE" ARAC_API_PORT || true)"
        [[ -z "${ARAC_COCKPIT_PORT:-}" ]] && ARAC_COCKPIT_PORT="$(lire_var "$ARAC_ENV_FILE" ARAC_COCKPIT_PORT || true)"
        [[ -z "${ARAC_ROLE_PREFIX:-}" ]]  && ARAC_ROLE_PREFIX="$(lire_var "$ARAC_ENV_FILE" ARAC_ROLE_PREFIX || true)"
        [[ -z "${ARAC_UNITE_PREFIXE:-}" ]] && ARAC_UNITE_PREFIXE="$(lire_var "$ARAC_ENV_FILE" ARAC_UNIT_PREFIX || true)"
        [[ -z "${ARAC_LOG_DIR:-}" ]]      && ARAC_LOG_DIR="$(lire_var "$ARAC_ENV_FILE" ARAC_LOG_DIR || true)"
        [[ -z "${ARAC_BACKUP_DIR:-}" ]]   && ARAC_BACKUP_DIR="$(lire_var "$ARAC_ENV_FILE" ARAC_BACKUP_DIR || true)"

        # LE SERVEUR AUSSI EST UNE VALEUR RETENUE, PAS UNE CONSTANTE.
        #
        # `ARAC_DB_PORT` n'était lu nulle part ici, et il était posé à 5432 en
        # tête de fichier. L'étape 6 de la documentation — « lancez
        # verify_install.sh » — interrogeait donc TOUJOURS le cluster 5432,
        # quel que soit le cluster où le cerveau avait été installé. Mesuré :
        # 22 sains / 1 échec (« base introuvable ») sur une installation
        # parfaitement saine, et 39 sains / 0 échec avec ARAC_DB_PORT posé à
        # la main. Ici l'écart était fail-closed ; sur une machine portant une
        # base homonyme sur 5432, il aurait rendu un verdict sur celle du
        # voisin.
        #
        # Le bootstrap écrit désormais l'hôte et le port. Pour les
        # installations d'avant, on les relit dans le DSN d'administration :
        # c'est la même valeur, écrite depuis toujours.
        [[ -z "${ARAC_DB_PORT:-}" ]] && ARAC_DB_PORT="$(lire_var "$ARAC_ENV_FILE" ARAC_DB_PORT || true)"
        [[ -z "${ARAC_DB_HOTE:-}" ]] && ARAC_DB_HOTE="$(lire_var "$ARAC_ENV_FILE" ARAC_DB_HOTE || true)"
        if [[ -z "${ARAC_DB_PORT:-}" || -z "${ARAC_DB_HOTE:-}" ]]; then
            local _dsn
            _dsn="$(lire_var "$ARAC_ENV_FILE" ARAC_DB_URL_ADMIN || true)"
            if [[ -n "$_dsn" ]]; then
                local _hp
                # La redirection AVANT le `<<`, l'opérateur APRÈS la parenthèse fermante :
# tout ce qui suit le délimiteur ouvrant est relu après le `PY` final, donc
# collé au `)`. Le lint du dépôt attrape cette forme, et il a raison.
_hp="$(python3 - "$_dsn" 2>/dev/null <<'PY'
import sys, urllib.parse
u = urllib.parse.urlparse(sys.argv[1])
print((u.hostname or "") + " " + (str(u.port) if u.port else ""))
PY
)" || _hp=""
                [[ -z "${ARAC_DB_HOTE:-}" ]] && ARAC_DB_HOTE="${_hp%% *}"
                [[ -z "${ARAC_DB_PORT:-}" ]] && ARAC_DB_PORT="${_hp##* }"
            fi
        fi
    fi
    # À défaut — installation encore incomplète — on redéduit du nom du cerveau,
    # jamais d'une constante partagée.
    ARAC_ROLE_PREFIX="${ARAC_ROLE_PREFIX:-arac_$ARAC_DB}"
    ARAC_UNITE_PREFIXE="${ARAC_UNITE_PREFIXE:-arac-$ARAC_DB}"
    ARAC_LOG_DIR="${ARAC_LOG_DIR:-/var/log/arac/$ARAC_DB}"
    ARAC_BACKUP_DIR="${ARAC_BACKUP_DIR:-/var/backups/arac/$ARAC_DB}"
    # Un port INCONNU reste inconnu : `_port` le rapportera « non mesuré »
    # plutôt que de contrôler un numéro par défaut qui n'est celui de personne.
    ARAC_API_PORT="${ARAC_API_PORT:-}"
    ARAC_COCKPIT_PORT="${ARAC_COCKPIT_PORT:-}"
    # Le serveur, lui, ne peut pas rester inconnu : sans lui, `psql_super` ne
    # sait pas à qui parler. On retombe donc sur le cluster par défaut de la
    # machine — mais on le DIT, au lieu de le supposer en silence.
    if [[ -z "${ARAC_DB_PORT:-}" ]]; then
        ARAC_DB_PORT=5432
        PORT_DB_SUPPOSE=1
    else
        PORT_DB_SUPPOSE=0
    fi
    ARAC_DB_HOTE="${ARAC_DB_HOTE:-127.0.0.1}"

    # LA MÊME FONCTION QUE L'INSTALLATION, ET C'EST TOUT L'INTÉRÊT.
    # Ces quatre noms étaient refabriqués ici, en deux lignes jumelles de
    # celles de `lib/config.sh` — et le cinquième, `R_BACKUP`, n'y était
    # jamais arrivé. Un contrôle qui recopie la règle qu'il contrôle ne
    # contrôle plus rien le jour où sa copie vieillit.
    poser_noms_de_roles "$ARAC_ROLE_PREFIX"
}

q() { psql_super -d "$ARAC_DB" -tAc "$1" 2>/dev/null || true; }
qq() { psql_super -d postgres -tAc "$1" 2>/dev/null || true; }

# ---------------------------------------------------------------------------
# 0. Le contrat des variables — le seul contrôle qui ne demande RIEN
# ---------------------------------------------------------------------------
#
# Il ne touche ni la base, ni le réseau, ni les secrets : il compare deux
# fichiers du dépôt. Il tourne donc AVANT d'exiger une installation, et il
# tourne aussi en simulation — c'est même là qu'il sert le plus, puisqu'il
# répond à une question qu'on se pose avant d'installer : « le fichier que je
# m'apprête à recopier dit-il la vérité ? »
#
# Ce qu'il attrape : une variable documentée que rien ne lit (on la recopie,
# elle ne fait rien, aucune erreur n'apparaît), et une variable lue par le
# code que personne n'a déclarée (on ne la pose pas, et un jour elle manque).

controle_contrat_variables() {
    sous_titre "0. Le contrat des variables d'environnement"
    local audit="$ARAC_HOME/bootstrap/checks/audit_env.py"
    if [[ ! -r "$audit" ]]; then
        avert "contrat des variables" "audit_env.py introuvable — non contrôlé"
        return 0
    fi
    local sortie rc=0
    sortie="$(python3 "$audit" 2>&1)" || rc=$?
    case "$rc" in
        0) ok "contrat des variables" ".env.example et le code disent la même chose" ;;
        1) rate "contrat des variables" "le fichier canonique s'écarte du code"
           printf '%s\n' "$sortie" | sed 's/^/    /'
           remede "python3 bootstrap/checks/audit_env.py" ;;
        *) avert "contrat des variables" "le contrôle n'a pas pu se faire"
           printf '%s\n' "$sortie" | sed 's/^/    /' ;;
    esac
}

# ---------------------------------------------------------------------------
# 1. La description
# ---------------------------------------------------------------------------

controle_description() {
    sous_titre "1. La description du cerveau"
    # L'identité est déjà GARANTIE ici : `exiger_description` a arrêté le
    # script si elle manquait. On l'affiche pour que le lecteur sache sur
    # quoi porte tout ce qui suit.
    ok "identité déclarée" "« $BRAIN_NOM », de $BRAIN_OWNER, depuis $BRAIN_NODE"
    if [[ -r "$ARAC_HOME/config/scopes.toml" ]]; then
        local rc=0 sortie
        sortie="$(cd "$ARAC_HOME" && python3 bootstrap/generate_scopes.py \
                  --config config/scopes.toml --check 2>&1)" || rc=$?
        case "$rc" in
            0) ok "taxonomie à jour" "$(printf '%s' "$sortie" | tr -s ' \n' ' ' | sed 's/^ //')" ;;
            1) avert "taxonomie divergente" "le code généré ne reflète plus config/scopes.toml"
               remede "sudo ./bootstrap/bootstrap.sh --scopes-only" ;;
            *) rate "taxonomie invalide" "le générateur la refuse"
               remede "python3 bootstrap/generate_scopes.py --config config/scopes.toml --check" ;;
        esac
    else
        rate "taxonomie déclarée" "config/scopes.toml absent"
        remede "python3 bootstrap/wizard.py"
    fi
}

# ---------------------------------------------------------------------------
# 2. La base
# ---------------------------------------------------------------------------

#: Le canal superutilisateur répond-il ? Sonde préalable, et non luxe.
#:
#: `q` et `qq` écrasent l'erreur (`2>/dev/null || true`) : « la base n'existe
#: pas », « PostgreSQL est arrêté » et « je n'ai pas le droit de devenir
#: postgres » rendent tous les trois la MÊME chaîne vide. Sans cette sonde, le
#: contrôle 2 lit ce vide comme « base introuvable » et propose de la recréer —
#: un remède destructeur pour un serveur simplement arrêté.
#:
#: Rend 0 si le canal répond ; sinon 1, en écrivant la raison sur stdout.
sonde_super() {
    local sortie rc=0
    sortie="$(psql_super -d postgres -tAc "SELECT 1" 2>&1)" || rc=$?
    if (( rc == 0 )) && [[ "$sortie" == 1 ]]; then
        return 0
    fi
    _premiere_ligne "$sortie"
    return 1
}

controle_base() {
    sous_titre "2. La base et son schéma"

    # DIRE CONTRE QUEL SERVEUR ON VA CONCLURE, AVANT DE CONCLURE.
    #
    # Tout ce bloc s'adresse à UN cluster. Lequel n'était écrit nulle part :
    # ce contrôle a rendu « base introuvable » sur une installation saine,
    # simplement parce qu'il interrogeait 5432 pendant que le cerveau vivait
    # sur 5460. Un verdict qui ne nomme pas son objet n'est pas un verdict.
    if (( ${PORT_DB_SUPPOSE:-0} )); then
        avert "serveur PostgreSQL" "$ARAC_DB_HOTE:$ARAC_DB_PORT — SUPPOSÉ, non lu"
        note "     Ni ARAC_DB_PORT ni ARAC_DB_URL_ADMIN n'ont pu être lus dans
     $ARAC_ENV_FILE. Le cluster par défaut de la machine est donc
     interrogé faute de mieux. S'il porte une base homonyme, tout ce
     qui suit parlerait du cerveau de quelqu'un d'autre."
        remede "sudo $0        # le coffre est en 0600, root"
    else
        ok "serveur PostgreSQL" "$ARAC_DB_HOTE:$ARAC_DB_PORT"
    fi

    local diag
    if ! diag="$(sonde_super)"; then
        avert "accès superutilisateur" "NON VÉRIFIÉ — ${diag:-psql injoignable}"
        note "     Tout ce bloc interroge le catalogue en tant que
     « $ARAC_PG_SUPERUSER ». Tant que ce canal ne répond pas, on ne peut
     dire NI que la base existe, NI qu'elle manque. Rien n'est donc jugé
     ici — et surtout aucune reconstruction n'est proposée."
        remede "sudo -u $ARAC_PG_SUPERUSER psql -p $ARAC_DB_PORT -c 'select 1'"
        return 1
    fi

    if [[ "$(qq "SELECT 1 FROM pg_database WHERE datname='$ARAC_DB'")" != 1 ]]; then
        rate "base « $ARAC_DB »" "introuvable"
        remede "sudo ./bootstrap/bootstrap.sh --from base"
        return 1
    fi
    ok "base « $ARAC_DB »" "$(qq "SELECT pg_size_pretty(pg_database_size('$ARAC_DB'))")"

    local vect
    vect="$(q "SELECT extversion FROM pg_extension WHERE extname='vector'")"
    if [[ -n "$vect" ]]; then
        ok "pgvector actif" "v$vect — le rappel par similarité est possible"
    else
        rate "pgvector actif" "absent : aucun rappel par similarité"
        remede "sudo ./bootstrap/bootstrap.sh --from vecteurs"
    fi

    local tables
    tables="$(q "SELECT count(*) FROM information_schema.tables WHERE table_schema='$ARAC_SCHEMA'")"
    # Un `count(*)` rend TOUJOURS un nombre quand il s'exécute. Une chaîne vide
    # ne veut donc pas dire « zéro table » : elle veut dire « la requête n'a pas
    # abouti ». Les deux menaient au même verdict — « les migrations n'ont pas
    # tourné » — dont l'un des deux était faux.
    if [[ -z "$tables" ]]; then
        avert "tables du schéma $ARAC_SCHEMA" "NON VÉRIFIÉ — la requête n'a rien rendu"
        return 1
    fi
    if [[ "$tables" -gt 0 ]]; then
        ok "tables du schéma $ARAC_SCHEMA" "${tables}"
    else
        rate "tables du schéma $ARAC_SCHEMA" "aucune : les migrations n'ont pas tourné"
        remede "sudo ./bootstrap/bootstrap.sh --from migrations"
        return 1
    fi

    local rev
    rev="$(q "SELECT version_num FROM $ARAC_SCHEMA.alembic_version LIMIT 1")"
    if [[ -n "$rev" ]]; then
        ok "révision du schéma" "$rev"
    else
        avert "révision du schéma" "table alembic_version vide ou absente"
    fi

    controle_apres_bascule
    return 0
}

# ---------------------------------------------------------------------------
# 2 bis. CE QUE LA PAGE DE LA RESTAURATION ATTEND DE CE CONTRÔLE
# ---------------------------------------------------------------------------
#
# `docs/SAUVEGARDE.md` §7 clôt la bascule par ce script, et justifie ce choix
# en propres termes : « Après une bascule, la question n'est pas “quelque chose
# répond-il ?” mais “est-ce mon cerveau qui répond ?” ». Il n'y répondait pas :
# il remontait la socket jusqu'au PID et lisait `ARAC_DB` dans son
# environnement — c'est-à-dire un NOM DE BASE, qu'une bascule vient justement
# de déplacer d'une base à l'autre. Le nom avait suivi ; la mémoire, non.
#
# Trois choses se regardent ici, et chacune peut rougir :
#   · la base porte-t-elle l'EMPREINTE de cette installation ? Elle est gravée
#     dans le commentaire du schéma, elle voyage dans le dump, et deux cerveaux
#     ne peuvent pas porter la même ;
#   · le schéma appartient-il au rôle qui fait tourner les migrations ? Après
#     un `pg_restore --no-owner`, il appartient à qui a restauré ;
#   · reste-t-il, sur cette grappe, des bases dérivées du nom de ce cerveau ?
#     Une bascule en laisse deux, et chacune est une COPIE COMPLÈTE de la
#     mémoire — qu'on garde exprès, mais qu'on doit savoir qu'on garde.
controle_apres_bascule() {
    local marque empreinte_base empreinte_coffre proprio autres

    # L'empreinte attendue vit dans le coffre, en 0600 : sans root, on ne la
    # lit pas — et on ne conclut donc pas. Un contrôle qui ne peut pas voir
    # doit se taire, pas deviner.
    empreinte_coffre="$(lire_var "$ARAC_ENV_FILE" ARAC_INSTALL_UUID 2>/dev/null || true)"

    marque="$(q "SELECT coalesce(obj_description(to_regnamespace('$ARAC_SCHEMA'),'pg_namespace'),'')")"
    empreinte_base="$(printf '%s' "$marque" | sed -n 's/.*\bempreinte=\([^ ]*\).*/\1/p')"
    if [[ -z "$empreinte_base" ]]; then
        avert "empreinte de la base" "NON GRAVÉE — cette base ne dit pas de quelle installation elle vient"
        note "     Elle a été posée avant que le bootstrap ne grave l'empreinte, ou
     elle sort d'une restauration antérieure. Tant qu'elle manque, ni ce
     contrôle ni ops/restore_verify.sh ne peuvent distinguer VOTRE mémoire
     de celle d'un cerveau voisin."
        remede "sudo ./bootstrap/bootstrap.sh --only migrations"
    elif [[ -n "$empreinte_coffre" && "$empreinte_base" != "$empreinte_coffre" ]]; then
        rate "empreinte de la base" "CE N'EST PAS LE CERVEAU DE CETTE INSTALLATION"
        note "     dans la base   : $empreinte_base
     attendue       : $empreinte_coffre   ($ARAC_ENV_FILE)
     La base « $ARAC_DB » répond, et ce n'est pas la vôtre. C'est très
     exactement ce qu'une bascule mal ciblée fabrique : le nom a suivi,
     la mémoire non. N'écrivez rien tant que ce n'est pas tranché."
        remede "sudo -u $ARAC_PG_SUPERUSER psql -p $ARAC_DB_PORT -Atc \"SELECT datname FROM pg_database WHERE datname LIKE '${ARAC_DB}%'\""
    else
        ok "empreinte de la base" "$empreinte_base — c'est bien la mémoire de cette installation"
    fi

    proprio="$(q "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='$ARAC_SCHEMA'")"
    if [[ -z "$proprio" ]]; then
        avert "propriétaire du schéma $ARAC_SCHEMA" "NON LU"
    elif [[ "$proprio" == "$R_ADMIN" ]]; then
        ok "propriétaire du schéma $ARAC_SCHEMA" "$proprio — les migrations pourront le faire évoluer"
    else
        rate "propriétaire du schéma $ARAC_SCHEMA" "« $proprio », et non « $R_ADMIN »"
        note "     C'est la signature d'un « pg_restore --no-owner » qu'on n'a pas
     refermé : la prochaine migration échouera sur « must be owner »."
        remede "sudo ./bootstrap/bootstrap.sh --only migrations"
    fi

    # LES COPIES QUE LA BASCULE LAISSE DERRIÈRE ELLE.
    # On ne les traite pas comme des restes à supprimer — §7 dit de garder
    # l'avariée « jusqu'à ce que la nouvelle ait fait ses preuves ». On les
    # NOMME, parce qu'un disque qui porte deux fois la même mémoire est une
    # chose qu'on doit décider de garder, pas découvrir six mois plus tard.
    autres="$(qq "SELECT string_agg(datname || ' (' || pg_size_pretty(pg_database_size(datname)) || ')', ', ' ORDER BY datname)
                    FROM pg_database
                   WHERE datname <> '$ARAC_DB'
                     AND datname LIKE '${ARAC_DB}\\_%'
                     -- le gabarit de restauration est VIDE et voulu : il est
                     -- déjà rapporté, comme un acquis, par ops/install_check.sh
                     AND datname <> '${ARAC_DB}_restore_template'
                     -- et surtout : une base qui est le cerveau de QUELQU'UN
                     -- D'AUTRE n'est pas un reste du nôtre. « bascule » ne
                     -- possède pas « bascule_deux » parce que son nom commence
                     -- pareil. On le demande au serveur : un cerveau installé
                     -- a ses cinq rôles.
                     AND NOT EXISTS (SELECT 1 FROM pg_roles
                                      WHERE rolname = 'arac_' || datname || '_admin')")"
    if [[ -n "$autres" ]]; then
        avert "copies de la mémoire sur cette grappe" "$autres"
        note "     Ces bases dérivent du nom de ce cerveau et n'appartiennent à aucun
     autre cerveau installé. Chacune porte une COPIE COMPLÈTE de la
     mémoire — dont « ${ARAC_DB}_avarie_… », que docs/SAUVEGARDE.md §7
     demande expressément de garder le temps que la bascule fasse ses
     preuves. Ce n'est pas une panne ; c'est une chose à savoir."
        remede "ops/uninstall_check.sh $ARAC_DB --port $ARAC_DB_PORT --gestes"
    fi
}

# ---------------------------------------------------------------------------
# 3. Les rôles — et la lecture seule réellement éprouvée
# ---------------------------------------------------------------------------

_PY_DSN="$(cat <<'PY'
import shlex, sys
from urllib.parse import urlsplit, unquote
u = urlsplit(sys.stdin.read().strip())
vide = ""
print("PGUSER=" + shlex.quote(unquote(u.username or vide)))
print("PGPASSWORD=" + shlex.quote(unquote(u.password or vide)))
print("PGHOST=" + shlex.quote(u.hostname or "127.0.0.1"))
print("PGPORT=" + shlex.quote(str(u.port or 5432)))
print("PGDATABASE=" + shlex.quote((u.path or "/").lstrip("/")))
PY
)"

#: Exécute une requête sous un rôle donné, SANS que le mot de passe passe par
#: argv : il ne transite que par l'environnement du processus fils.
#:
#: Rend sur la sortie standard ce que psql a dit, et un code qui DIT ce qui
#: s'est passé — parce que le texte seul ne permet pas de le savoir :
#:
#:   0  connecté, requête aboutie
#:   1  connecté, mais le MOTEUR a refusé la requête (erreur SQL)
#:   2  la CONNEXION a échoué (mot de passe, hôte, pg_hba)
#:   3  rien n'a même pu être TENTÉ (secret illisible, DSN illisible, psql absent)
#:
#: 2 et 3 se ressemblent et ne veulent pas dire la même chose : pour le
#: contrôle « ce rôle se connecte-t-il ? », 2 est un verdict (non) et 3 n'en
#: est pas un. C'est à l'appelant de trancher, et il ne peut le faire que si
#: on lui rend l'information — d'où quatre codes plutôt qu'un booléen.
#:
#: POURQUOI `eval "$env"` PUIS `export` NOMMÉMENT, et non `eval "export $env"` :
#: `export` ne s'applique qu'au PREMIER mot qui le suit. `export A=1\nB=2` posait
#: donc PGUSER seul, et laissait PGPASSWORD/PGHOST/PGPORT/PGDATABASE en simples
#: variables locales, invisibles à psql. psql retombait alors sur la socket
#: locale en authentification peer, échouait sur les quatre rôles, et le script
#: annonçait « connexion refusée » ×4 puis « la garantie de lecture seule est
#: rompue » sur une installation parfaitement saine.
sous_role() { # cle_du_dsn requete
    local dsn env rc=0
    command -v psql >/dev/null 2>&1 || return 3
    dsn="$(lire_var "$ARAC_ENV_FILE" "$1" 2>/dev/null)" || return 3
    [[ -n "$dsn" ]] || return 3
    env="$(printf '%s' "$dsn" | python3 -c "$_PY_DSN")" || return 3
    unset dsn
    (
        eval "$env"
        export PGUSER PGPASSWORD PGHOST PGPORT PGDATABASE
        psql -tAc "$2" 2>&1
    ) || rc=$?
    case "$rc" in
        0|1|2) return "$rc" ;;
        *)     return 3 ;;   # psql introuvable, tué, code inattendu : non mesuré
    esac
}

#: La première ligne d'un message d'erreur, sans le bruit. Ni DSN ni mot de
#: passe n'y figurent : psql nomme l'hôte, le port et le rôle, jamais le secret.
_premiere_ligne() { printf '%s' "${1%%$'\n'*}"; }

controle_roles() {
    sous_titre "3. Les rôles"
    # LES RÔLES SONT GLOBAUX AU SERVEUR — LEUR SEULE PRÉSENCE NE PROUVE RIEN.
    #
    # Sur une machine qui a déjà hébergé un cerveau, `arac_admin` et ses trois
    # confrères existent AVANT qu'on ait rien installé : quatre ✓ verts pour
    # une base qui n'a jamais reçu le moindre GRANT. On mesure donc le lien du
    # rôle à CETTE base — `GRANT CONNECT ON DATABASE` posé par l'étape 3, après
    # un `REVOKE … FROM PUBLIC` qui rend la réponse significative.
    local r connecte
    for r in "$R_ADMIN" "$R_APP" "$R_AGENT" "$R_READONLY"; do
        if [[ "$(qq "SELECT 1 FROM pg_roles WHERE rolname='$r'")" != 1 ]]; then
            rate "rôle $r" "absent"
            remede "sudo ./bootstrap/bootstrap.sh --from base"
            continue
        fi
        connecte="$(qq "SELECT has_database_privilege('$r','$ARAC_DB','CONNECT')")"
        case "$connecte" in
            t) ok "rôle $r" "présent, et admis sur « $ARAC_DB »" ;;
            f) rate "rôle $r" "existe sur ce serveur, mais PAS sur la base « $ARAC_DB »"
               note "     Les rôles sont globaux au serveur PostgreSQL. Celui-ci vient
     d'ailleurs — d'un autre cerveau, ou d'un essai précédent — et n'a
     jamais reçu de droit sur cette base-ci."
               remede "sudo ./bootstrap/bootstrap.sh --from base" ;;
            *) avert "rôle $r" "présent — son droit sur « $ARAC_DB » n'a PAS pu être mesuré" ;;
        esac
    done

    if [[ ! -r "$ARAC_ENV_FILE" ]]; then
        avert "connexions par rôle" "$ARAC_ENV_FILE illisible (relancez en root)"
        remede "sudo ./bootstrap/checks/verify_install.sh"
        return
    fi

    # LA LISTE DES DSN À RELIRE EST CELLE QUI LES A ÉCRITS.
    # Elle était recopiée ici, en toutes lettres, avec ses quatre noms de
    # rôle : un DSN de plus posé par l'étape 3 n'aurait jamais été relu par ce
    # contrôle, et le rapport aurait conclu « ✓ » sans l'avoir regardé.
    local cle nom sortie rc _l _v_db _v_role _reste
    for _l in "${DSN_PAR_ROLE[@]}"; do
        read -r cle _v_db _v_role _reste <<< "$_l"
        nom="${!_v_role}"
        # `SELECT 1` NE TOUCHE AUCUN OBJET DU SCHÉMA, ET C'ÉTAIT TOUT LE DÉFAUT.
        #
        # Ce contrôle rendait « connexion acceptée » ×4, puis « ✓ Ce cerveau
        # fonctionne », code 0, sur un cerveau où AUCUN rôle ne pouvait lire un
        # seul souvenir — schéma restauré appartenant à `postgres`, API en 500
        # sur toutes ses routes de données. Mesuré, sur la base même que
        # `docs/SAUVEGARDE.md` §7 fabrique. Tous les comptages de contenu de ce
        # fichier passent par `q()`, c'est-à-dire par le SUPERUTILISATEUR, à qui
        # aucun droit ne manque jamais : la méthode ne POUVAIT pas rougir sur la
        # panne la plus probable d'après-restauration, la perte des droits.
        #
        # Et c'est exactement là que la page envoie chercher sa preuve :
        # « Après une bascule, la question n'est pas “quelque chose répond-il ?”
        # mais “est-ce mon cerveau qui répond ?” ». On lit donc, sous CHAQUE
        # rôle, une vraie table du schéma — celle qui porte les souvenirs.
        rc=0; sortie="$(sous_role "$cle" "SELECT count(*) FROM $ARAC_SCHEMA.memory_atoms")" || rc=$?
        case "$rc" in
            0) if [[ "$sortie" =~ ^[0-9]+$ ]]; then
                   ok "lecture $nom" "$sortie souvenir(s) lus SOUS CE RÔLE, dans $ARAC_SCHEMA.memory_atoms"
               else
                   avert "lecture $nom" "NON VÉRIFIÉE — réponse inattendue : $(_premiere_ligne "$sortie")"
               fi ;;
            1) # Connecté, mais le moteur a refusé la lecture. Deux causes très
               # différentes, et une seule est une panne de ce cerveau.
               if [[ "$sortie" == *"permission denied"* || "$sortie" == *"droit"* ]]; then
                   rate "lecture $nom" "connecté, mais PAS le droit de lire $ARAC_SCHEMA.memory_atoms"
                   printf '      %s\n' "$(_c 2 "$(_premiere_ligne "$sortie")")"
                   note "     C'est la panne d'après-restauration : un
     « pg_restore --no-owner --no-privileges » rend la base à qui l'a
     restaurée, pas aux rôles du cerveau. Le cerveau répond, et ne se
     souvient de rien."
                   remede "sudo ./bootstrap/bootstrap.sh --only migrations"
               else
                   # Table absente : le schéma n'a pas encore été migré. Ce
                   # n'est pas un défaut de droits, et le dire ainsi enverrait
                   # chercher au mauvais endroit.
                   avert "lecture $nom" "connectée, mais $ARAC_SCHEMA.memory_atoms est hors d'atteinte — $(_premiere_ligne "$sortie")"
                   remede "sudo ./bootstrap/bootstrap.sh --from migrations"
               fi ;;
            2) rate "connexion $nom" "refusée — mot de passe désynchronisé ?"
               printf '      %s\n' "$(_c 2 "$(_premiere_ligne "$sortie")")"
               remede "sudo rm $ARAC_SECRETS_ROLES && sudo ./bootstrap/bootstrap.sh --from base" ;;
            *) # On n'a RIEN pu tenter : $cle absente du fichier, DSN illisible,
               # psql introuvable. Ce n'est pas « refusée », c'est « pas su ».
               avert "connexion $nom" "NON VÉRIFIÉE — $cle illisible dans $ARAC_ENV_FILE, ou psql absent"
               remede "sudo grep -c '^$cle=' $ARAC_ENV_FILE" ;;
        esac
    done

    # -----------------------------------------------------------------------
    # La promesse structurante : le cockpit ne PEUT PAS écrire.
    #
    # C'est le contrôle le plus délicat du fichier, parce que le succès de
    # l'écriture est la SEULE issue qui doive alarmer — et c'est la seule qui
    # ne produit aucun message. Chercher un motif d'erreur dans le texte, comme
    # on le faisait, revient à conclure « l'écriture a réussi » dès que psql
    # s'est tu : connexion impossible, secret illisible, retour anticipé. Un
    # inconnu voyait alors « la garantie est rompue » sur une base où elle
    # tenait, appliquait le remède (déjà en place), relançait, revoyait le même
    # verdict — et apprenait à ne plus croire le vérificateur.
    #
    # On se fie donc au code de sortie de psql, pas à ses mots : seul rc=0
    # signifie que le CREATE TABLE est réellement passé.
    # -----------------------------------------------------------------------
    rc=0
    sortie="$(sous_role ARAC_DB_URL_READONLY "CREATE TEMP TABLE _arac_sonde(i int)")" || rc=$?
    case "$rc" in
        0) rate "lecture seule du cockpit" "une écriture a RÉUSSI : la garantie est rompue"
           remede "sudo -u $ARAC_PG_SUPERUSER psql -p $ARAC_DB_PORT -c \"ALTER ROLE $R_READONLY SET default_transaction_read_only = on\"" ;;
        1) if [[ "$sortie" == *"read-only"* || "$sortie" == *"lecture seule"* ]]; then
               ok "lecture seule du cockpit" "écriture refusée par le moteur, comme prévu"
           else
               # Refusée, mais pas par la lecture seule (droits manquants sur le
               # schéma, par exemple). L'écriture n'est pas passée : ce n'est pas
               # un échec. Mais ce n'est pas la garantie attendue : on le dit.
               avert "lecture seule du cockpit" "écriture refusée, mais pas par la lecture seule"
               printf '      %s\n' "$(_c 2 "$(_premiere_ligne "$sortie")")"
           fi ;;
        2) avert "lecture seule du cockpit" "NON VÉRIFIÉE — connexion au rôle $R_READONLY impossible"
           note "     Rien n'est jugé ici : tant qu'on ne se connecte pas, on ne
     sait pas si l'écriture serait refusée. Corrigez d'abord la
     connexion ci-dessus, puis relancez ce contrôle." ;;
        *) avert "lecture seule du cockpit" "NON VÉRIFIÉE — ARAC_DB_URL_READONLY illisible, ou psql absent" ;;
    esac
}

# ---------------------------------------------------------------------------
# 4. La taxonomie et l'état du savoir
# ---------------------------------------------------------------------------

controle_savoir() {
    sous_titre "4. La taxonomie et ce qu'elle porte"
    local n
    n="$(q "SELECT count(*) FROM $ARAC_SCHEMA.scopes")"
    if [[ -z "$n" ]]; then
        avert "domaines semés" "NON VÉRIFIÉ — $ARAC_SCHEMA.scopes illisible"
        return
    fi
    if [[ "$n" -gt 0 ]]; then
        ok "domaines semés" "$n ($(q "SELECT count(*) FROM $ARAC_SCHEMA.scopes WHERE depth=0") racines, $(q "SELECT count(*) FROM $ARAC_SCHEMA.scopes WHERE depth>0") feuilles)"
    else
        rate "domaines semés" "aucun : le cerveau ne peut rien ranger"
        remede "sudo ./bootstrap/bootstrap.sh --scopes-only"
        return
    fi

    local atomes
    atomes="$(q "SELECT count(*) FROM $ARAC_SCHEMA.memory_atoms WHERE status='active'")"
    [[ -z "$atomes" ]] && { avert "souvenirs" "table memory_atoms illisible"; return; }
    ok "souvenirs actifs" "$atomes"
    [[ "${atomes:-0}" -eq 0 ]] && {
        note "     Un cerveau neuf est vide. C'est normal : lancez une
     synchronisation, puis un cycle."
        return; }

    # --- Le piège n°1 : les souvenirs posés sur une racine ---------------
    local orphelins pct
    orphelins="$(q "SELECT count(*) FROM $ARAC_SCHEMA.memory_atoms a
        JOIN $ARAC_SCHEMA.scopes s ON s.path = a.scope
        WHERE a.status='active' AND s.depth = 0")"
    # Le sens le plus dangereux du défaut : `${orphelins:-0}` transformait une
    # requête qui n'a pas abouti en « aucun », c'est-à-dire en ✓. Un contrôle
    # qui n'a rien mesuré n'a surtout pas le droit de rassurer.
    if [[ -z "$orphelins" ]]; then
        avert "souvenirs invisibles au rappel" "NON VÉRIFIÉ — la requête n'a rien rendu"
    elif [[ "$orphelins" -eq 0 ]]; then
        ok "souvenirs invisibles au rappel" "aucun"
    else
        pct=$(( orphelins * 100 / atomes ))
        avert "souvenirs posés sur une racine" "$orphelins ($pct %) — INVISIBLES au rappel"
        note "     Une racine est un conteneur, pas un rangement. Ces souvenirs
     existent en base et ne remonteront jamais. Sur le cerveau de
     référence, observé huit mois, c'était près d'un souvenir actif sur
     onze — le compte du jour, lui, est celui que cette ligne vient de
     mesurer sur VOTRE base.
     Déplacez-les vers une feuille :"
        q "SELECT '       ' || a.scope || '  →  ' || count(*) || ' souvenir(s)'
           FROM $ARAC_SCHEMA.memory_atoms a JOIN $ARAC_SCHEMA.scopes s ON s.path=a.scope
           WHERE a.status='active' AND s.depth=0 GROUP BY a.scope ORDER BY 1"
    fi

    # --- La provenance ----------------------------------------------------
    local sans
    sans="$(q "SELECT count(*) FROM $ARAC_SCHEMA.memory_atoms
        WHERE status='active' AND (source_ref IS NULL OR source_ref = '')")"
    if [[ -n "$sans" ]]; then
        if [[ "$sans" -eq 0 ]]; then
            ok "provenance conservée" "100 % des souvenirs savent d'où ils viennent"
        else
            pct=$(( sans * 100 / atomes ))
            avert "souvenirs sans provenance" "$sans ($pct %)"
            note "     Un souvenir sans provenance n'est pas vérifiable. Sur le
     cerveau de référence, 76 % de la provenance a été perdue après un
     changement de format du champ source_ref. Si ce pourcentage
     augmente, cherchez une migration récente, pas un bogue d'aujourd'hui."
        fi
    fi
}

# ---------------------------------------------------------------------------
# 5. Les secrets
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# UN JETON NE DÉSIGNE QU'UN POSTE
# ---------------------------------------------------------------------------
#
# `app/auth.py` construit une table « jeton → poste » en balayant TOUT ce qui
# commence par `ARAC_NODE_TOKEN_`. Deux noms portant la même valeur, et il
# lève au démarrage : l'API ne démarre pas, elle boucle en restart, après une
# installation qui s'est déclarée réussie. Le message de journald ne nomme ni
# le fichier fautif, ni le geste.
#
# Ce contrôle-ci le nomme, avant la panne. Et il ne cherche pas des NOMS
# connus — il ne saurait pas lesquels, puisque le suffixe est le node_id de
# qui l'a écrit : il regarde la FORME du défaut, deux clés pour une valeur.
# C'est la seule façon d'attraper celui qu'on n'a pas prévu.
_controle_alias_de_jeton() {
    [[ -r "$ARAC_ENV_FILE" ]] || { avert "alias de jeton" "NON VÉRIFIÉS — $ARAC_ENV_FILE illisible"; return; }
    local sortie rc=0
    sortie="$(python3 - "$ARAC_ENV_FILE" <<'PY'
import pathlib, sys
from collections import defaultdict

PREFIXE = "ARAC_NODE_TOKEN_"
par_valeur = defaultdict(list)
for ligne in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if ligne.lstrip().startswith("#") or "=" not in ligne:
        continue
    cle, _, valeur = ligne.partition("=")
    cle = cle.strip()
    if cle.startswith(PREFIXE) and valeur.strip():
        par_valeur[valeur].append(cle)

doublons = [noms for noms in par_valeur.values() if len(noms) > 1]
print(f"NOMBRE={sum(len(n) for n in par_valeur.values())}")
for noms in doublons:
    print("DOUBLON=" + " ".join(sorted(noms)))
raise SystemExit(1 if doublons else 0)
PY
)" || rc=$?

    local combien
    combien="$(printf '%s\n' "$sortie" | sed -n 's/^NOMBRE=//p')"
    if (( rc == 0 )); then
        ok "alias de jeton" "${combien:-0} poste(s), un jeton chacun"
        return
    fi
    if (( rc != 1 )); then
        avert "alias de jeton" "le contrôle n'a pas pu se faire"
        return
    fi

    local ligne
    while IFS= read -r ligne; do
        [[ "$ligne" == DOUBLON=* ]] || continue
        rate "alias de jeton" "un seul jeton pour : ${ligne#DOUBLON=}"
    done <<< "$sortie"
    note "     Le nom d'un alias porte l'identité du poste : c'est ce qui permet
     d'en révoquer un sans toucher aux autres. Deux noms pour une même
     valeur, et cette identité ne veut plus rien dire — le poste retiré
     ouvre encore sous le nom du poste gardé.
     app/auth.py refuse de démarrer dans ce cas, volontairement : mieux
     vaut une API arrêtée qu'une API qui ne sait plus qui écrit chez elle.
     La cause habituelle est un changement de node_id : l'ancien alias
     n'était pas déposé. Le bootstrap le dépose désormais."
    remede "sudo ./bootstrap/bootstrap.sh --only secrets"
}

# ---------------------------------------------------------------------------
# LA PORTE DE LA BOUCLE LOCALE — et pourquoi ce contrôle FRAPPE au lieu de LIRE
# ---------------------------------------------------------------------------
#
# La version précédente de ce contrôle lisait `ARAC_API_TRUST_LOOPBACK` dans le
# fichier d'environnement, comptait les cerveaux de la machine, et rendait un
# avertissement quand il y en avait plusieurs. Elle avait raison sur le fond et
# tort sur la méthode, pour deux raisons qui se cumulaient :
#
#   · elle lisait une INTENTION, pas un ÉTAT. Le fichier peut dire « fermé »
#     pendant que l'API tourne encore avec l'ancienne valeur, faute de
#     redémarrage. C'est même le cas le plus probable juste après une
#     modification à la main — c'est-à-dire exactement le moment où on lance
#     ce contrôle ;
#   · elle refusait de trancher (« les deux postures restent légitimes ») tout
#     en écrivant, huit lignes plus bas, que la posture ouverte « n'est plus la
#     bonne sur cette machine-ci ». Le même code jugeait et s'abstenait.
#
# Les deux défauts disparaissent en frappant à la porte : on envoie une
# requête SANS jeton sur une route qui lit la mémoire, et on regarde ce que
# l'API répond VRAIMENT, maintenant. 401 : la porte est fermée. 200 : elle est
# ouverte, et aucune lecture de fichier ne peut prétendre le contraire.
#
# Cette requête est sans effet : c'est un GET de recherche, et elle est refusée
# avant d'atteindre la base quand la porte est fermée.
_controle_porte_boucle_locale() {
    local valeur motif code url
    valeur="$(lire_var "$ARAC_ENV_FILE" ARAC_API_TRUST_LOOPBACK 2>/dev/null || true)"
    motif="$(lire_var "$ARAC_ENV_FILE" ARAC_API_TRUST_LOOPBACK_RAISON 2>/dev/null || true)"

    # --- 1. Ce que le coffre DIT ------------------------------------------
    case "$(printf '%s' "${valeur:-0}" | tr 'A-Z' 'a-z')" in
        1|true|yes|oui|on)
            if [[ -n "$motif" ]]; then
                # Pas de ✓. Un desserrage assumé reste un desserrage : le
                # rendre vert, c'est le faire disparaître du rapport.
                avert "boucle locale DESSERRÉE" "sur décision écrite"
                note "     Motif déclaré : « $motif »"
                note "     Sur cette installation, tout compte local lit et écrit la
     mémoire de ce cerveau sans présenter de jeton. C'est un choix, il
     est daté, il est relisible — et il reste dangereux dès qu'un
     second compte a un shell ici. Pour revenir au défaut :"
                remede "sudo sed -i '/^ARAC_API_TRUST_LOOPBACK/d' $ARAC_ENV_FILE && sudo systemctl restart $ARAC_UNITE_PREFIXE-api.service"
            else
                rate "desserrage SANS motif" "ARAC_API_TRUST_LOOPBACK=$valeur, ARAC_API_TRUST_LOOPBACK_RAISON absente"
                note "     Le desserrage n'est PAS appliqué : le jeton reste exigé. Ce
     n'est pas une formalité — un défaut implicite est précisément ce
     qui a laissé cette porte ouverte pendant deux versions, parce
     qu'une intention que personne n'a écrite est une intention que
     personne ne peut relire.
     Écrivez la raison, ou retirez la variable."
                remede "sudo sh -c 'echo ARAC_API_TRUST_LOOPBACK_RAISON=\"\$(date -I) — <votre motif>\" >> $ARAC_ENV_FILE'"
            fi ;;
        *)
            ok "jeton porteur" "exigé PARTOUT, boucle locale comprise (défaut)" ;;
    esac

    # --- 2. Ce que l'API RÉPOND -------------------------------------------
    if [[ -z "${ARAC_API_PORT:-}" ]]; then
        avert "porte de la boucle locale" "NON MESURÉE — port de l'API inconnu"
        return
    fi
    url="http://127.0.0.1:$ARAC_API_PORT/v1/dashboard/search?q=arac-verif-porte"
    code="$(_code_http_sans_jeton "$url")"
    case "$code" in
        401)
            ok "porte de la boucle locale" "MESURÉE : un appel sans jeton rend 401" ;;
        000)
            avert "porte de la boucle locale" "NON MESURÉE — l'API ne répond pas sur $ARAC_API_PORT"
            note "     Le contrôle ne conclut pas : une API arrêtée n'est pas une
     porte fermée, c'est une porte qu'on n'a pas essayée."
            remede "sudo systemctl start $ARAC_UNITE_PREFIXE-api.service" ;;
        200|202)
            rate "porte de la boucle locale" "OUVERTE : un appel sans jeton a rendu $code"
            note "     N'importe quel compte de cette machine — y compris le compte de
     service d'un AUTRE cerveau, y compris « nobody » — lit la mémoire
     de celui-ci et peut y écrire de faux souvenirs, sans présenter le
     moindre secret. Aucune permission de fichier ne ferme ce chemin,
     parce qu'il ne passe par aucun fichier.
     Si le coffre dit pourtant « fermé », c'est que l'API tourne encore
     avec l'ancienne valeur : elle ne relit son environnement qu'au
     démarrage."
            remede "sudo systemctl restart $ARAC_UNITE_PREFIXE-api.service" ;;
        *)
            avert "porte de la boucle locale" "réponse inattendue sans jeton : $code"
            note "     Ni 401 (fermée) ni 200 (ouverte). Regardez le corps de la
     réponse avant de conclure :"
            remede "curl -i '$url'" ;;
    esac
}

#: Le code HTTP d'un GET SANS le moindre en-tête d'autorisation. 000 = pas de
#: réponse. `curl` d'abord, `python3` en repli : ce contrôle doit fonctionner
#: sur une machine où curl n'a pas été installé, sinon il se tait précisément
#: là où l'installation est la plus incomplète.
_code_http_sans_jeton() { # url
    if command -v curl >/dev/null 2>&1; then
        curl -s -o /dev/null -m 5 -w '%{http_code}' "$1" 2>/dev/null || printf '000'
        return
    fi
    python3 - "$1" <<'PY' 2>/dev/null || printf '000'
import sys, urllib.error, urllib.request
try:
    with urllib.request.urlopen(sys.argv[1], timeout=5) as r:
        print(r.status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception:
    print("000")
PY
}

controle_secrets() {
    sous_titre "5. Les secrets"
    local f mode
    if [[ ! -e "$ARAC_ETC" ]]; then
        rate "coffre $ARAC_ETC" "absent"
        remede "sudo ./bootstrap/bootstrap.sh --from secrets"
        return
    fi
    mode="$(stat -c %a "$ARAC_ETC")"
    if [[ "$mode" == 700 ]]; then ok "coffre $ARAC_ETC" "0700"
    else rate "coffre $ARAC_ETC" "$mode au lieu de 0700"; remede "sudo chmod 0700 $ARAC_ETC"; fi

    # « ABSENT » EST UNE MESURE. ICI, ON N'AVAIT PAS MESURÉ.
    #
    # `[[ ! -e "$f" ]]` sur un fichier logé dans un répertoire 0700 root rend
    # FAUX pour un compte ordinaire — non parce que le fichier manque, mais
    # parce que le répertoire n'est pas traversable (EACCES). Le contrôle
    # écrivait donc, sur une installation COMPLÈTE faite la minute d'avant :
    #     ⚠ arac.env absent · ⚠ roles.env absent · ⚠ cockpit.env absent
    #     ⚠ contenu des secrets illisible sans root — contrôle partiel
    # quatre lignes qui se contredisent, deux lignes après avoir déclaré
    # « ✓ coffre /etc/arac/<base> 0700 ». Or l'écran de fin du bootstrap
    # prescrit ce script SANS sudo, et `docs/INSTALLATION.md` assume le mode
    # partiel : un mode partiel a le droit de ne pas voir, il n'a pas le droit
    # d'accuser. C'est le faux diagnostic que `ops/install_check.sh` a été
    # corrigé pour empêcher — corrigé sur un script, jamais cherché sur son
    # jumeau, alors que c'est le jumeau qu'on recommande.
    if [[ ! -r "$ARAC_ETC" || ! -x "$ARAC_ETC" ]]; then
        avert "contenu du coffre" "NON CONTRÔLÉ — $ARAC_ETC illisible par $(id -un)"
        note "     Ce n'est pas une panne, et ce n'est pas une absence : c'est le
     mode partiel. Le coffre est en 0700 root — c'est exactement ce qui
     empêche le compte d'un autre cerveau de le lire. Sans root, ce
     contrôle ne peut ni voir les trois fichiers, ni lire la liste
     blanche d'ingestion. Il ne conclut donc rien à leur sujet.
     Ce qui a été contrôlé plus haut reste vrai."
        remede "sudo $0"
        return
    fi

    for f in "$ARAC_ENV_FILE" "$ARAC_SECRETS_ROLES" "$ARAC_SECRETS_COCKPIT"; do
        if [[ ! -e "$f" ]]; then avert "$(basename "$f")" "absent"; continue; fi
        mode="$(stat -c %a "$f")"
        if [[ "$mode" == 600 ]]; then ok "$(basename "$f")" "0600"
        else rate "$(basename "$f")" "$mode au lieu de 0600"; remede "sudo chmod 0600 $f"; fi
    done

    if [[ ! -r "$ARAC_ENV_FILE" ]]; then
        avert "contenu des secrets" "illisible sans root — contrôle partiel"
        remede "sudo $0"
        return
    fi
    # La liste blanche : fail-closed, donc son absence ne se voit nulle part
    # ailleurs. L'API démarre, le cockpit répond, la synchronisation dit
    # qu'elle a envoyé — et chaque dépôt repart en 403. On la contrôle ici
    # parce que c'est le seul endroit qui la regarde AVANT que ça arrive.
    local liste
    liste="$(lire_var "$ARAC_ENV_FILE" ARAC_INGEST_ALLOWED_NODES 2>/dev/null || true)"
    if [[ -z "$liste" ]]; then
        rate "ARAC_INGEST_ALLOWED_NODES" "absente ou vide : l'ingestion refuse TOUT en 403"
        note "     Fail-closed volontaire : sans liste, aucun poste n'entre, même
     avec un jeton valide. C'est ce qui empêche un dépôt anonyme de
     devenir un faux souvenir définitif — mais tant qu'elle est vide,
     votre propre poste est refusé lui aussi."
        remede "sudo ./bootstrap/bootstrap.sh --only secrets"
    else
        case ",${liste}," in
            *",${BRAIN_NODE},"*)
                ok "ARAC_INGEST_ALLOWED_NODES" "« $liste » — dont ce cerveau" ;;
            *)
                rate "ARAC_INGEST_ALLOWED_NODES" "« $liste » n'inclut PAS « $BRAIN_NODE »"
                note "     Le poste déclaré à l'entretien est celui qui envoie. S'il
     n'est pas dans cette liste, tout ce qu'il dépose repart en 403."
                remede "sudo ./bootstrap/bootstrap.sh --only secrets" ;;
        esac
    fi

    # -----------------------------------------------------------------------
    # Le jeton porteur — et la variable que l'API lit VRAIMENT
    #
    # Ce contrôle disait : « ARAC_API_BEARER_TOKEN absent : l'API refusera
    # toute écriture. » C'était faux deux fois, et l'une des deux erreurs
    # vient d'être réparée dans le moteur :
    #   · app/auth.py ne lit PAS cette variable. Il balaie l'environnement à la
    #     recherche du préfixe ARAC_NODE_TOKEN_ ; un ARAC_API_BEARER_TOKEN seul
    #     n'ouvre rien côté SERVEUR. Il reste indispensable côté CLIENT :
    #     c'est le nom que `app/api_token.py` regarde en premier pour le pont,
    #     le cycle, le cockpit et les agents. Les deux noms doivent donc être
    #     présents ET égaux — c'est ce que vérifie la suite.
    #   · « l'API refusera toute écriture » est redevenu VRAI. Ce n'était plus
    #     le cas tant que la boucle locale était exemptée par défaut ; elle ne
    #     l'est plus (cf le contrôle « porte de la boucle locale », plus bas,
    #     qui ne se contente pas de lire la variable : il frappe à la porte).
    # -----------------------------------------------------------------------
    local cle valeur jeton_api jeton_noeud slug
    jeton_api="$(lire_var "$ARAC_ENV_FILE" ARAC_API_BEARER_TOKEN 2>/dev/null || true)"
    if [[ -n "$jeton_api" ]]; then
        ok "ARAC_API_BEARER_TOKEN" "présent"
    else
        rate "ARAC_API_BEARER_TOKEN" "absent ou VIDE : les appelants LOCAUX n'ont plus de jeton"
        note "     Ce n'est plus une simple ligne à recopier sur le Mac. Depuis que
     le jeton est exigé de toute requête, c'est sous ce nom-là que le
     cycle, le cockpit et les agents vont chercher le leur
     (app/api_token.py). Sans elle, le cockpit affiche « indisponible »
     et le cycle n'écrit plus rien — sans qu'aucun service ne tombe."
        remede "sudo ./bootstrap/bootstrap.sh --only secrets"
    fi

    # node_id → nom de variable : MAJUSCULES, tirets et points en soulignés.
    # C'est la convention de app/auth.py:_env_slug_to_node_id, à l'envers.
    slug="ARAC_NODE_TOKEN_$(printf '%s' "$BRAIN_NODE" | tr 'a-z.-' 'A-Z__')"
    jeton_noeud="$(lire_var "$ARAC_ENV_FILE" "$slug" 2>/dev/null || true)"
    if [[ -z "$jeton_noeud" ]]; then
        rate "$slug" "absent : ce poste n'a AUCUN jeton reconnu par l'API"
        note "     Ce défaut ne se voyait pas tant que la boucle locale était
     exemptée : tout marchait, et rien n'était authentifié. Maintenant,
     il se voit tout de suite — TOUT repart en 401, y compris votre
     propre pont. C'est le bon sens de la panne : bruyante et immédiate,
     plutôt que silencieuse et durable."
        remede "sudo ./bootstrap/bootstrap.sh --only secrets"
        note "     Ou à la main, une ligne à ajouter dans $ARAC_ENV_FILE :
       $slug=\$(openssl rand -hex 32)
     puis : sudo systemctl restart $ARAC_UNITE_PREFIXE-api.service"
    elif [[ "${#jeton_noeud}" -lt 32 ]]; then
        # app/auth.py LÈVE au démarrage sous 32 caractères : l'API ne démarre
        # pas du tout. Mieux vaut l'apprendre ici que dans journalctl.
        rate "$slug" "${#jeton_noeud} caractères : l'API refusera de DÉMARRER (< 32)"
        remede "openssl rand -hex 32"
    elif [[ -n "$jeton_api" && "$jeton_api" != "$jeton_noeud" ]]; then
        # Le piège de la rotation : on régénère l'un, le moteur lit l'autre.
        rate "$slug" "diverge de ARAC_API_BEARER_TOKEN : un jeton révoqué ouvre encore"
        remede "sudo ./bootstrap/bootstrap.sh --only secrets"
    else
        ok "$slug" "${#jeton_noeud} caractères — le poste « $BRAIN_NODE » est reconnu"
    fi
    unset jeton_api jeton_noeud

    _controle_alias_de_jeton

    _controle_porte_boucle_locale

    if [[ ! -r "$ARAC_SECRETS_COCKPIT" ]]; then
        # Ni « absent » ni « présent » : pas lu. Le rater ici enverrait
        # régénérer des secrets parfaitement valables.
        avert "secrets du cockpit" "NON VÉRIFIÉS — $ARAC_SECRETS_COCKPIT illisible"
        remede "sudo ./bootstrap/checks/verify_install.sh"
    else
        for cle in ARAC_CC_SESSION_SECRET ARAC_CC_ADMIN_PASSWORD_HASH ARAC_CC_TOTP_SECRET; do
            valeur="$(lire_var "$ARAC_SECRETS_COCKPIT" "$cle" 2>/dev/null || true)"
            if [[ -n "$valeur" ]]; then
                ok "$cle" "présent"
            else
                rate "$cle" "absent ou VIDE : le cockpit refusera la connexion"
                remede "sudo ./bootstrap/bootstrap.sh --only secrets"
            fi
            unset valeur
        done
        # LE NOM SOUS LEQUEL LE COCKPIT LES LIT, ET PAS SEULEMENT SOUS LEQUEL
        # LE BOOTSTRAP LES ÉCRIT.
        #
        # Les trois lignes ci-dessus ne prouvaient rien de ce qui compte : le
        # cockpit ne lit pas `ARAC_CC_*`, il lit `CC_*`. Les secrets pouvaient
        # être là, corrects, complets — et `POST /cc/login` répondre 503
        # « Login non provisionné ». Ce contrôle-là est le seul qui parle du
        # cockpit ; les précédents parlent du coffre.
        local source cible
        for cle in "ARAC_CC_SESSION_SECRET:CC_SESSION_SECRET" \
                   "ARAC_CC_ADMIN_PASSWORD_HASH:CC_ADMIN_PASSWORD_HASH" \
                   "ARAC_CC_TOTP_SECRET:CC_TOTP_SECRET"; do
            source="${cle%%:*}"; cible="${cle##*:}"
            local v_src v_cib
            v_src="$(lire_var "$ARAC_SECRETS_COCKPIT" "$source" 2>/dev/null || true)"
            v_cib="$(lire_var "$ARAC_SECRETS_COCKPIT" "$cible" 2>/dev/null || true)"
            [[ -z "$v_src" ]] && { unset v_src v_cib; continue; }   # déjà signalé au-dessus
            if [[ -z "$v_cib" ]]; then
                rate "$cible" "non traduit : le cockpit répondra 503 « Login non provisionné »"
                note "     Le secret existe sous le nom du bootstrap ($source) et le
     cockpit lit l'autre. C'était la dernière intervention humaine du
     parcours ; le pont de vocabulaire la fait maintenant."
                remede "sudo ./bootstrap/bootstrap.sh --only secrets"
            elif [[ "$v_cib" != "$v_src" ]]; then
                rate "$cible" "diverge de $source — deux valeurs pour un secret"
                remede "sudo ./bootstrap/bootstrap.sh --only secrets"
            else
                ok "$cible" "traduit pour le cockpit"
            fi
            unset v_src v_cib
        done
        unset source cible
    fi

    # --- L'EMPREINTE DE CETTE INSTALLATION ---------------------------------
    #
    # Elle n'est pas un secret : c'est ce qui distingue ce cerveau d'un autre
    # qui porterait le même nom. Absente, le bootstrap retombe sur le nom —
    # c'est-à-dire sur le comportement qui faisait d'un homonyme un héritier.
    local emp
    emp="$(lire_var "$ARAC_ENV_FILE" ARAC_INSTALL_UUID 2>/dev/null || true)"
    if [[ -z "$emp" ]]; then
        avert "ARAC_INSTALL_UUID" "absente : ce cerveau n'est identifié que par son NOM"
        note "     Un nom se choisit, et « perso », « test », un prénom, sont les
     noms que tout le monde choisit. Tant que cette ligne manque, une
     seconde installation portant le même nom serait reçue comme une
     réinstallation de celle-ci."
        remede "sudo ./bootstrap/bootstrap.sh --from config"
    else
        ok "ARAC_INSTALL_UUID" "$emp"
    fi
    unset emp

    local degrade
    degrade="$(lire_var "$ARAC_ENV_FILE" ARAC_MODE_DEGRADE 2>/dev/null || true)"
    if [[ -z "$degrade" ]]; then
        ok "clés externes" "embeddings et curation configurés"
    else
        avert "mode dégradé déclaré" "$degrade"
        note "     Le cerveau tourne, mais amputé. Voir l'étape 8 :"
        remede "sudo ./bootstrap/bootstrap.sh --only cles"
    fi
}

# ---------------------------------------------------------------------------
# 6. Les services
# ---------------------------------------------------------------------------

controle_services() {
    sous_titre "6. Les services"
    if ! command -v systemctl >/dev/null 2>&1; then
        avert "systemd" "systemctl introuvable — contrôle impossible"
        return
    fi
    local u
    for u in "$ARAC_UNITE_PREFIXE-api.service" "$ARAC_UNITE_PREFIXE-cockpit.service"; do
        if ! systemctl list-unit-files "$u" >/dev/null 2>&1 \
           || [[ -z "$(systemctl list-unit-files --no-legend "$u" 2>/dev/null)" ]]; then
            rate "$u" "non installé"
            remede "sudo ./bootstrap/bootstrap.sh --from services"
            continue
        fi
        if systemctl is-active --quiet "$u"; then
            ok "$u" "actif"
        else
            rate "$u" "$(systemctl is-active "$u" 2>/dev/null)"
            remede "journalctl -u $u -n 40 --no-pager"
        fi
    done
    for u in "$ARAC_UNITE_PREFIXE-cycle.timer" "$ARAC_UNITE_PREFIXE-sauvegarde.timer"; do
        if systemctl is-active --quiet "$u"; then
            ok "$u" "armée — prochaine : $(systemctl show -p NextElapseUSecRealtime --value "$u" 2>/dev/null)"
        else
            avert "$u" "non armée"
            remede "sudo systemctl enable --now $u"
        fi
    done

    # Les ports : loopback uniquement, c'est la promesse. On ne les contrôle
    # que si NOTRE service tourne — un autre programme peut très bien occuper
    # le même numéro, et le lui reprocher n'aurait aucun sens.
    _port "API" "$ARAC_API_PORT" "$ARAC_UNITE_PREFIXE-api.service"
    _port "cockpit" "$ARAC_COCKPIT_PORT" "$ARAC_UNITE_PREFIXE-cockpit.service"
}

#: UN NUMÉRO DE PORT APPARTIENT À LA MACHINE, PAS À CE CERVEAU.
#:
#: 8000 et 8100 sont les valeurs par défaut de TOUS les cerveaux. Ce contrôle
#: demandait « quelqu'un écoute-t-il sur ce port ? », ce qui ne dit rien de
#: l'installation examinée — et se trompait dans le sens le plus coûteux : les
#: unités sont en `Type=simple`, donc systemd les déclare `active` dès le fork,
#: AVANT que le programme ait tenté d'ouvrir sa socket. Un cockpit qui redémarre
#: en boucle sur « address already in use » recevait ainsi un ✓, le port étant
#: bel et bien tenu — par le cerveau du voisin.
#:
#: On rattache donc la socket à son propriétaire (`socket_appartient_a`, dans
#: core.sh), et l'impossibilité de le savoir reste un « non mesuré ».
_port() { # nom port unite
    local nom="$1" port="$2" unite="$3" ligne="" etat rc=0
    if [[ -z "$port" ]]; then
        # DEUX SILENCES QUI SE RESSEMBLENT ET N'ONT PAS LE MÊME SENS.
        #
        # Le port est vide parce qu'on n'a rien lu dans le coffre. Deux causes :
        # le coffre ne PORTE pas ce port (installation interrompue avant
        # l'étape 2), ou le coffre est ILLISIBLE (0700 root, compte ordinaire).
        # Le message n'en connaissait qu'une et l'affirmait : « Leur absence dit
        # que l'installation n'est pas allée jusque-là ». Sur une installation
        # complète, contrôlée sans sudo — ce que l'écran de fin du bootstrap
        # recommande —, il accusait donc une installation parfaite, quatre
        # lignes après avoir déclaré les deux services « actifs ».
        if [[ ! -r "$ARAC_ENV_FILE" ]]; then
            avert "$nom — port" "NON CONTRÔLÉ : le coffre est illisible par $(id -un)"
            note "     Le port de ce cerveau est écrit dans $ARAC_ENV_FILE, en
     0700 root. Ce que vous voyez ici ne dit RIEN de l'installation :
     ni qu'elle est complète, ni qu'elle ne l'est pas."
            remede "sudo $0"
            return
        fi
        avert "$nom — port" "NON CONTRÔLÉ : aucun port retenu pour ce cerveau"
        note "     Les ports sont attribués à l'étape 2 et écrits dans
     $ARAC_ENV_FILE, qui est lisible et ne le porte pas. Cette absence-là
     dit que l'installation n'est pas allée jusque-là — pas qu'un service
     est en panne."
        remede "sudo ./bootstrap/bootstrap.sh --from secrets"
        return
    fi
    # « arrêté » était une supposition : `is-active` est faux aussi pour
    # `activating`, `failed`, `reloading`. On rapporte l'état RÉEL — c'est lui
    # qui oriente la recherche.
    etat="$(systemctl is-active "$unite" 2>/dev/null)"
    if [[ "$etat" != active ]]; then
        avert "$nom sur le port $port" "NON CONTRÔLÉ : $unite est ${etat:-introuvable}"
        return
    fi
    command -v ss >/dev/null 2>&1 || { avert "$nom sur le port $port" "NON CONTRÔLÉ : ss introuvable"; return; }
    # `-p` : sans le propriétaire de la socket, on ne peut pas distinguer
    # « notre service écoute » de « quelqu'un d'autre tient ce numéro ».
    ligne="$(ss -ltnHp "sport = :$port" 2>/dev/null | head -1)" || rc=$?
    # ss qui échoue rend, lui aussi, une ligne vide. La confondre avec
    # « personne n'écoute » ferait chercher une panne dans le service.
    if (( rc != 0 )); then
        avert "$nom sur le port $port" "NON CONTRÔLÉ : ss a échoué (code $rc)"
        return
    fi
    if [[ -z "$ligne" ]]; then
        rate "$nom sur le port $port" "le service tourne mais personne n'écoute"
        remede "journalctl -u $unite -n 40 --no-pager"
        return
    fi

    socket_appartient_a "$ligne" "$unite"
    case "$?" in
        1) rate "$nom sur le port $port" "tenu par un AUTRE processus que $unite"
           printf '      %s\n' "$(_c 2 "$ligne")"
           note "     Ce numéro appartient à la machine, pas à ce cerveau. Tant
     qu'un autre le tient, $unite ne pourra jamais ouvrir sa socket :
     il redémarrera en boucle sur « address already in use », et son
     état « active » ne veut rien dire (Type=simple : actif dès le fork,
     avant toute tentative d'écoute).
     Donnez d'autres numéros à CE cerveau, ou libérez celui-ci :"
           remede "sudo ./bootstrap/bootstrap.sh --from config   # constate, puis réattribue un port libre"
           return ;;
        2) avert "$nom sur le port $port" "NON CONTRÔLÉ : ss ne montre pas le propriétaire de la socket"
           note "     Sans lui, on ne sait pas si c'est CE cerveau qui écoute ou un
     autre programme sur le même numéro. Relancez en root :"
           remede "sudo ./bootstrap/checks/verify_install.sh"
           return ;;
    esac

    if [[ "$ligne" == *"0.0.0.0:$port "* || "$ligne" == *"[::]:$port "* ]]; then
        rate "$nom sur le port $port" "écoute sur TOUTES les interfaces"
        note "     Le cerveau se joint par un tunnel SSH, jamais directement.
     Corrigez --host dans $unite, puis rechargez systemd."
    else
        ok "$nom sur le port $port" "boucle locale uniquement"
    fi

    _identite_derriere_le_port "$nom" "$port" "$ligne"
}

#: UN 200 NE PROUVE RIEN. IL FAUT SAVOIR QUI RÉPOND.
#:
#: Le jour de l'incident, l'API de production redémarrait pour la 35e fois sur
#: « address already in use » — et `curl /healthz` rendait 200. Le contrôle de
#: santé était donc VERT sur un service mort : il interrogeait un numéro de
#: port, et un numéro de port ne dit pas à quel cerveau il mène. C'est la pire
#: forme de panne, celle qui se présente comme une santé et que le premier
#: réflexe du diagnostic confirme.
#:
#: On ne demande donc pas au service de se nommer — une réponse HTTP est
#: exactement ce dont on doute. On remonte la socket jusqu'à son processus,
#: puis on lit l'environnement que systemd lui a posé en PID 1 : `ARAC_DB` y
#: nomme le cerveau, et cette valeur-là ne peut pas être servie par un
#: imposteur, seulement PORTÉE par lui — auquel cas c'est bien lui qu'on
#: identifie, et c'est ce qu'on veut savoir.
_identite_derriere_le_port() { # nom port ligne_ss
    local nom="$1" port="$2" ligne="$3" pid attendu="$ARAC_DB" vu=""
    pid="$(pids_socket "$ligne" | head -1)"
    if [[ -z "$pid" ]]; then
        avert "identité derrière le port $port" "NON CONTRÔLÉE : pas de PID sur la socket"
        return
    fi
    if [[ ! -r "/proc/$pid/environ" ]]; then
        avert "identité derrière le port $port" \
              "NON CONTRÔLÉE : /proc/$pid/environ illisible (relancez en root)"
        return
    fi
    vu="$(tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null \
          | sed -n 's/^ARAC_DB=//p' | head -1)"
    if [[ -z "$vu" ]]; then
        # ⚠ ET NON ✗ — et la nuance est le fruit d'une fausse alerte.
        #
        # À ce point, `_port` a DÉJÀ rattaché la socket à notre unité par son
        # cgroup : le processus qui écoute est bien le nôtre. S'il ne porte
        # pas ARAC_DB, c'est que son fichier d'environnement est antérieur à
        # ce nommage — pas qu'un imposteur tient le port. Décerner un ✗ ici
        # ferait crier au loup sur une installation saine, et un contrôle qui
        # crie au loup finit par n'être plus lu : c'est ainsi qu'on rate le
        # jour où il a raison.
        avert "identité derrière le port $port" \
              "NON CONTRÔLÉE : le processus n'expose pas ARAC_DB"
        note "     La socket appartient bien à $unite (vérifié ci-dessus par son
     cgroup) — ce n'est donc pas un port usurpé. Mais son environnement
     ne nomme pas le cerveau, ce qui empêche de le CONFIRMER par un
     second chemin. C'est le cas des installations antérieures à ce
     contrôle. Une réinstallation écrit ARAC_DB dans le fichier
     d'environnement et rend la confirmation possible :"
        remede "sudo ./bootstrap/bootstrap.sh --from base"
        return
    fi
    if [[ "$vu" != "$attendu" ]]; then
        rate "identité derrière le port $port" \
             "répond pour le cerveau « $vu », pas « $attendu »"
        note "     Le port est tenu par un AUTRE cerveau de cette machine. Tout ce
     qui interroge ce numéro — contrôle de santé, cockpit, tunnel SSH —
     parle depuis le début à « $vu » en croyant parler à « $attendu ».
     C'est ainsi qu'une production a été déclarée saine pendant qu'elle
     redémarrait en boucle."
        remede "sudo ./bootstrap/bootstrap.sh --from config   # réattribue un port libre"
        return
    fi
    ok "identité derrière le port $port" "c'est bien le $nom de « $attendu »"
}

# ---------------------------------------------------------------------------
# 7. Les sauvegardes
# ---------------------------------------------------------------------------

#: LE DOSSIER DE SAUVEGARDE EST PARTAGÉ — LE CONTRÔLE, NON.
#:
#: `/var/backups/arac` est le défaut de TOUS les cerveaux. Ce contrôle comptait
#: les `*.dump` sans distinguer le leur : un cerveau qui n'a JAMAIS été
#: sauvegardé recevait « ✓ dernière sauvegarde il y a 5 h — 4 au total » grâce
#: aux dumps d'un essai précédent, et se voyait proposer, comme geste de
#: restauration, de charger la mémoire de CET AUTRE cerveau dans sa base de
#: test. Le faux vert portait sur le filet de sécurité lui-même.
#:
# ===========================================================================
# 7. LA CURATION — LE SEUL CONTRÔLE QUI DIT SI CE CERVEAU APPRENDRA
#
# CE CONTRÔLE MANQUAIT, ET SON ABSENCE A COÛTÉ UNE INSTALLATION ENTIÈRE.
# Tout le reste pouvait être vert — base saine, quatre rôles, services actifs,
# 39 pages de cockpit — et le cerveau ne produisait AUCUN souvenir, sans qu'un
# seul écran ne le dise. La cause n'était ni une clé, ni un service : la
# digestion lance le binaire `claude` en sous-processus, sous le compte
# d'agent, avec SON dossier personnel — et ni le binaire, ni son
# authentification, ni les deux interrupteurs de dépense n'étaient regardés.
#
# Quatre questions, dans l'ordre où elles arrêtent un cycle :
#   1. le binaire existe-t-il, et à quel chemin ?
#   2. le compte d'agent peut-il l'exécuter ?
#   3. a-t-il de quoi s'authentifier — session d'abonnement, ou clé d'API — et
#      cela vu DEPUIS le dossier personnel de ce compte, pas depuis le vôtre ?
#   4. les deux interrupteurs de dépense sont-ils ouverts ?
#
# Aucune de ces questions ne dépense un centime : `claude auth status` ne parle
# à personne, et l'état des interrupteurs se lit dans un fichier et une table.
# ===========================================================================
controle_curation() {
    sous_titre "7. La curation — ce qui transforme vos conversations en souvenirs"

    local agent home_agent chemin
    agent="$(lire_var "$ARAC_ENV_FILE" ARAC_AGENT_USER 2>/dev/null || true)"
    home_agent="$(lire_var "$ARAC_ENV_FILE" ARAC_AGENT_HOME 2>/dev/null || true)"
    [[ -z "$home_agent" ]] && home_agent="/var/lib/arac/$ARAC_DB"
    chemin="$(lire_var "$ARAC_ENV_FILE" ARAC_CLAUDE_BIN 2>/dev/null || true)"
    [[ -z "$chemin" ]] && chemin="$(command -v claude 2>/dev/null || true)"

    if [[ -z "$chemin" || ! -x "$chemin" ]]; then
        avert "binaire de curation" "ABSENT — ce cerveau ingérera sans jamais apprendre"
        note "     La digestion n'appelle AUCUNE API : elle lance \`claude\` (Claude
     Code CLI) en sous-processus sur ce serveur. Sans lui, chaque cycle
     s'arrête sans produire un souvenir, et aucune clé d'API n'y change
     rien. Le reste du cerveau — ingestion, rappel, cockpit — fonctionne."
        remede "sudo npm install -g @anthropic-ai/claude-code"
        remede "puis, si le binaire n'est pas dans le PATH du service : ajoutez ARAC_CLAUDE_BIN=<chemin> à $ARAC_ENV_FILE"
        return
    fi
    ok "binaire de curation" "$chemin — $("$chemin" --version 2>/dev/null | head -1)"

    # LE COMPTE QUI COMPTE EST CELUI QUI LANCERA. Un binaire exécutable par
    # root et pas par le compte d'agent produit exactement le symptôme que ce
    # contrôle existe pour éviter : tout est vert, rien n'est digéré.
    if [[ -n "$agent" ]] && id "$agent" >/dev/null 2>&1; then
        if sudo -n -u "$agent" test -x "$chemin" 2>/dev/null; then
            ok "exécutable par $agent" "le compte qui lance les cycles"
        else
            avert "exécutable par $agent" "NON MESURÉ (sudo non disponible sans mot de passe)"
        fi
    fi

    # L'AUTHENTIFICATION, LUE LÀ OÙ LE BINAIRE LA LIRA — c'est-à-dire sous
    # $HOME/.claude du COMPTE D'AGENT, que `claude_cli.py` fixe à
    # <ARAC_AGENT_HOME>/data/agent-home. Une session ouverte dans /root n'y est
    # PAS : c'est la cause exacte du « Not logged in » qu'un cycle rend sans
    # autre explication.
    local maison_outil etat methode
    maison_outil="$home_agent/data/agent-home"
    etat=""
    if [[ -n "$agent" ]] && id "$agent" >/dev/null 2>&1; then
        etat="$(sudo -n -u "$agent" -H env HOME="$maison_outil" \
                 "$chemin" auth status --json 2>/dev/null || true)"
    fi
    [[ -z "$etat" ]] && etat="$(HOME="$maison_outil" "$chemin" auth status --json 2>/dev/null || true)"
    methode="$(printf '%s' "$etat" | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get("authMethod","") or "")
except Exception:
    print("")' 2>/dev/null || true)"

    case "$methode" in
        claude.ai)
            ok "authentification" "session d'abonnement, dans $maison_outil" ;;
        api_key)
            ok "authentification" "clé ANTHROPIC_API_KEY lue par le binaire — facturée à l'appel" ;;
        *)
            avert "authentification" "AUCUNE dans $maison_outil — le cycle récoltera « Not logged in »"
            note "     Le binaire est là, mais il n'a rien pour parler à Anthropic
     DEPUIS LE COMPTE QUI LANCE LES CYCLES. Votre propre session (celle
     de root, ou la vôtre) n'est pas lue : le cycle force HOME sur le
     dossier ci-dessus. Une seule des deux façons suffit."
            remede "sudo -u ${agent:-<compte-agent>} -H env HOME=$maison_outil $chemin auth login"
            remede "ou : ajoutez ARAC_CURATION_API_KEY à $ARAC_ENV_FILE puis sudo ./bootstrap/bootstrap.sh --only cles" ;;
    esac

    # LES DEUX INTERRUPTEURS DE DÉPENSE. Ils sont FERMÉS sur une installation
    # neuve, et c'est voulu — mais un utilisateur qui l'ignore attend des
    # souvenirs qui ne viendront jamais. On les nomme tous les deux, avec leur
    # geste, plutôt que de laisser un cycle refuser en silence.
    local interrupteur1 interrupteur2
    interrupteur1="$(lire_var "$ARAC_ENV_FILE" ARAC_ALLOW_PAID_AI 2>/dev/null || true)"
    case "${interrupteur1,,}" in
        1|true|yes|on) ok "interrupteur 1/2 (service)" "ARAC_ALLOW_PAID_AI=$interrupteur1" ;;
        *)  avert "interrupteur 1/2 (service)" "FERMÉ (ARAC_ALLOW_PAID_AI=${interrupteur1:-absent}) — aucun cycle ne dépensera"
            remede "sudo sed -i 's/^ARAC_ALLOW_PAID_AI=.*/ARAC_ALLOW_PAID_AI=1/' $ARAC_ENV_FILE" ;;
    esac
    interrupteur2="$(q "SELECT value FROM arac.arac_config WHERE key = 'paid_ai_enabled'")"
    case "$interrupteur2" in
        true|t|1) ok "interrupteur 2/2 (cerveau)" "arac_config.paid_ai_enabled = true" ;;
        *)  avert "interrupteur 2/2 (cerveau)" "FERMÉ (paid_ai_enabled=${interrupteur2:-absent}) — armement humain jamais fait"
            note "     C'est le second interrupteur, et c'est celui que personne ne
     trouve : il vit EN BASE, pas dans un fichier. Tant qu'il est fermé,
     le cycle refuse sur \`master_switch_config_off\` — un code qui ne
     dit rien à qui ne l'a jamais lu."
            remede "cd $ARAC_HOME && sudo .venv/bin/python -m agents.lib.paid_ai_control arm --confirm --coffre $ARAC_ENV_FILE" ;;
    esac
}

#: Le préfixe `${ARAC_DB}-` n'est pas une convention d'ici : c'est le nom que
#: l'unité de sauvegarde engendrée à l'étape 9 donne à ses fichiers
#: (bootstrap/lib/services.sh, _unite_backup).
controle_sauvegardes() {
    sous_titre "8. Les sauvegardes"
    if [[ ! -d "$ARAC_BACKUP_DIR" ]]; then
        # MÊME PIÈGE QUE LE §5 : ce chemin peut être une DÉDUCTION.
        # Quand le coffre n'a pas pu être lu, `decouvrir()` retombe sur
        # /var/backups/arac/<base> — qui n'est pas forcément celui que
        # l'installation a retenu. Dire « absent » d'un dossier qu'on a deviné,
        # c'est mesurer une installation imaginaire.
        if [[ ! -r "$ARAC_ENV_FILE" ]]; then
            avert "dossier de sauvegarde" "NON CONTRÔLÉ : le coffre est illisible par $(id -un)"
            note "     $ARAC_BACKUP_DIR est une DÉDUCTION, pas ce que cette
     installation a retenu : ARAC_BACKUP_DIR est écrit dans le coffre."
            remede "sudo $0"
            return
        fi
        avert "dossier $ARAC_BACKUP_DIR" "absent"
        remede "sudo ./bootstrap/bootstrap.sh --from services"
        return
    fi
    # TROISIÈME FOIS DANS CE SCRIPT, ET LA DERNIÈRE : « ABSENT » EST UNE MESURE.
    #
    # `test -d` réussit sur un dossier en 0700 root tant que son PARENT est
    # traversable — mais `find` à l'intérieur échoue en EACCES et rend zéro
    # ligne. Le compte ordinaire lisait donc « ⚠ sauvegardes : aucune encore »
    # sur un cerveau qui en portait deux, mesurées à la minute d'avant. C'est
    # exactement le faux diagnostic corrigé au §5 (les trois secrets) et au §6
    # (les deux ports) — même script, même famille, trois blocs plus bas.
    # Le mode partiel a le droit de ne pas voir ; il n'a pas le droit d'accuser.
    if [[ ! -r "$ARAC_BACKUP_DIR" || ! -x "$ARAC_BACKUP_DIR" ]]; then
        avert "sauvegardes" "NON CONTRÔLÉES — $ARAC_BACKUP_DIR illisible par $(id -un)"
        note "     Le dossier existe et son contenu n'est pas lisible par ce
     compte : il est en 0700 root, et c'est voulu — un dump est une copie
     intégrale de la mémoire. Ce contrôle ne dit donc RIEN ici : ni qu'il
     y a des sauvegardes, ni qu'il n'y en a pas."
        remede "sudo $0"
        return
    fi
    local dernier age n autres
    n="$(find "$ARAC_BACKUP_DIR" -maxdepth 1 -name "${ARAC_DB}-*.dump" 2>/dev/null | wc -l)"
    dernier="$(find "$ARAC_BACKUP_DIR" -maxdepth 1 -name "${ARAC_DB}-*.dump" -printf '%T@ %p\n' 2>/dev/null \
               | sort -rn | head -1 | cut -d' ' -f2-)"
    if [[ -z "$dernier" ]]; then
        autres="$(find "$ARAC_BACKUP_DIR" -maxdepth 1 -name '*.dump' 2>/dev/null | wc -l)"
        if [[ "${autres:-0}" -gt 0 ]]; then
            avert "sauvegardes de « $ARAC_DB »" "AUCUNE — ${autres} dump(s) du dossier appartiennent à un autre cerveau"
            note "     $ARAC_BACKUP_DIR est partagé par tous les cerveaux de cette
     machine. Ceux qui s'y trouvent ne protègent pas celui-ci : les
     restaurer chargerait la mémoire de quelqu'un d'autre."
        else
            avert "sauvegardes" "aucune encore — la première tombera à la prochaine minuterie"
        fi
        remede "sudo systemctl start $ARAC_UNITE_PREFIXE-sauvegarde.service"
        return
    fi
    age=$(( ( $(date +%s) - $(stat -c %Y "$dernier") ) / 3600 ))
    if (( age <= 12 )); then
        ok "dernière sauvegarde" "il y a ${age} h — $n au total"
    else
        avert "dernière sauvegarde" "il y a ${age} h : la minuterie ne tourne plus ?"
        remede "systemctl status $ARAC_UNITE_PREFIXE-sauvegarde.timer"
    fi
    # CE BLOC PRESCRIVAIT UN RITUEL DE SUPERUTILISATEUR QUI PROUVE MOINS QUE
    # L'OUTIL DU DÉPÔT.
    #
    # Il donnait createdb / pg_restore / dropdb sous « $ARAC_PG_SUPERUSER »,
    # puis concluait « une sauvegarde jamais restaurée n'est pas une
    # sauvegarde ». Trois reproches, et le troisième est le vrai :
    #   1. il réclame le superutilisateur, alors que l'étape 3 donne CREATEDB
    #      au rôle d'administration et l'étape 4 pose le gabarit — précisément
    #      pour que cette vérification n'en ait plus jamais besoin ;
    #   2. il ne prouve que « pg_restore n'a pas crié » : il ne compte aucune
    #      ligne, ne compare rien au cerveau vivant, et ne verrait donc ni un
    #      dump amputé d'une table, ni un dump vieux de trois semaines ;
    #   3. il ne lève RIEN. La réserve permanente d'`ops/install_check.sh`
    #      (« aucune restauration n'a jamais été vérifiée ») et l'alarme
    #      d'`ops/watchdog.sh` (« vos dumps sont une hypothèse ») ne tombent
    #      que sur l'estampille qu'écrit `ops/restore_verify.sh`. Le lecteur
    #      qui suivait ces trois lignes à la lettre voyait sa réserve rester
    #      allumée, et n'avait aucun moyen de savoir pourquoi.
    #
    # On prescrit donc le geste qui prouve ET qui lève. Le rituel manuel reste
    # nommé, parce qu'il est le seul recours sur une installation antérieure au
    # gabarit — et il garde sa leçon sur le « -p », qui reste vraie.
    local _port="${ARAC_DB_PORT:-<LE PORT DE VOTRE SERVEUR>}"
    # LA MÊME LEÇON QU'AU §4 D'ops/install_check.sh : ce bloc disait « à jouer
    # au moins une fois pour de vrai », c'est-à-dire « personne ne le fait »,
    # alors que le bootstrap arme « …-restauration.timer » le dimanche à 03:00.
    # On demande donc à systemd avant de prescrire un geste manuel — et si
    # l'unité est là, on le dit AVANT de donner la commande, pour que le
    # lecteur sache qu'il choisit de ne pas attendre, plutôt que de réparer.
    local _t_rest="" _rappel="Restauration — à jouer au moins une fois pour de vrai :"
    if [[ -n "${ARAC_UNITE_PREFIXE:-}" ]] && command -v systemctl >/dev/null 2>&1; then
        _t_rest="$(systemctl list-units --plain --no-legend --no-pager --type=timer \
                   "$ARAC_UNITE_PREFIXE-restauration.timer" 2>/dev/null | awk '{print $1}')"
    fi
    [[ -n "$_t_rest" ]] && _rappel="Restauration — $_t_rest la joue chaque semaine. Pour ne pas attendre :"
    note "     $_rappel
       sudo ARAC_ENV_FILE=${ARAC_ENV_FILE:-/etc/arac/${ARAC_DB:-<votre-base>}/arac.env} ops/restore_verify.sh
     Elle restaure ce dump dans une base JETABLE, compte ce qui en sort,
     le compare au cerveau vivant, détruit la base et écrit l'estampille
     qui éteint « aucune restauration n'a jamais été vérifiée » dans
     ops/install_check.sh. Elle ne demande AUCUN privilège de
     superutilisateur : le rôle d'administration a CREATEDB depuis
     l'étape 3, et copie le gabarit posé à l'étape 4.
     Sur une installation POSÉE AVANT le gabarit, le rituel manuel reste
     le recours — sous $ARAC_PG_SUPERUSER, et jamais sans « -p » :
       sudo -u $ARAC_PG_SUPERUSER createdb -p $_port ${ARAC_DB}_test
       sudo -u $ARAC_PG_SUPERUSER pg_restore -p $_port -d ${ARAC_DB}_test $dernier
       sudo -u $ARAC_PG_SUPERUSER dropdb -p $_port ${ARAC_DB}_test
     Le « -p » désigne la grappe de CE cerveau. Sans lui, les trois commandes
     s'adressent à la grappe par défaut de la machine : la base de
     vérification y serait créée, et le dropdb final y détruirait ce qui
     porte ce nom — c'est-à-dire, sur un poste à deux serveurs, chez le voisin.
     Il prouve que pg_restore n'a pas crié ; il ne compte rien, ne compare
     rien, et ne lève pas la réserve. Une sauvegarde jamais restaurée n'est
     pas une sauvegarde — et une restauration jamais comptée n'est pas une
     preuve."
}

# ---------------------------------------------------------------------------
# 8. Le code et le schéma disent-ils la même chose ?
# ---------------------------------------------------------------------------
#
# Une table absente ne fait AUCUN bruit. `arac.memory_review_queue` a été lue
# par deux consommateurs de production sans qu'aucune migration ne la crée : les
# deux dégradent proprement (SAVEPOINT, try/except), donc la panne était
# silencieuse et permanente. Aucun contrôle ne croisait ce que le code nomme et
# ce que le schéma porte ; celui-ci le fait, sur la base RÉELLE — le seul
# schéma qui fasse foi sur une machine.
#
# La même comparaison tourne aussi hors installation, contre les migrations du
# dépôt, dans `make test`. Les deux ne disent pas la même chose : celle-ci
# attrape en plus la base qui a DÉRIVÉ de ses migrations.

controle_schema_refs() {
    sous_titre "9. Le code et le schéma"
    local audit="$ARAC_HOME/bootstrap/checks/audit_schema_refs.py"
    if [[ ! -r "$audit" ]]; then
        avert "références au schéma" "audit_schema_refs.py introuvable — non contrôlé"
        return 0
    fi
    local objets rc=0 sortie
    objets="$(q "SELECT c.relname FROM pg_class c
                 JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = '$ARAC_SCHEMA'
                UNION
                SELECT p.proname FROM pg_proc p
                 JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = '$ARAC_SCHEMA'")"
    if [[ -z "$objets" ]]; then
        avert "références au schéma" "NON CONTRÔLÉ — le catalogue n'a rien rendu"
        return 0
    fi
    sortie="$(printf '%s\n' "$objets" | python3 "$audit" --objets - --silencieux 2>&1)" || rc=$?
    case "$rc" in
        0) ok "références au schéma" "tout ce que le code nomme existe dans « $ARAC_DB »" ;;
        1) rate "références au schéma" "le code lit des objets que cette base n'a pas"
           printf '%s\n' "$sortie" | sed 's/^/    /'
           note "     Ces lecteurs-là dégradent en SILENCE : ils ne remonteront
     jamais rien, et rien ne le dira. C'est une migration qui manque,
     pas un correctif à passer à la main." ;;
        *) avert "références au schéma" "le contrôle n'a pas pu se faire"
           printf '%s\n' "$sortie" | sed 's/^/    /' ;;
    esac
}

# ===========================================================================

main() {
    # Quand le bootstrap nous appelle, la bannière a déjà été affichée.
    [[ -z "${ARAC_SANS_BANNIERE:-}" ]] && banniere
    if (( SIMULATION_SEULE )); then
        titre "Contrôle a posteriori — ce qui serait vérifié"
        vide
        note "0. le contrat des variables : .env.example contre le code
   (le seul qui n'exige aucune installation — il tourne ci-dessous)
1. la description : brain.toml, scopes.toml, taxonomie à jour
2. la base : existence, pgvector, tables, révision du schéma
3. les rôles, et une TENTATIVE D'ÉCRITURE avec le rôle du cockpit
   (elle doit échouer : c'est la garantie qu'on vérifie, pas la promesse)
4. la taxonomie semée, les souvenirs invisibles, la provenance conservée
5. les secrets et leurs permissions, le mode dégradé éventuel
6. les services actifs, et que le port est tenu par CE cerveau
7. la CURATION : le binaire qu'elle lance (elle n'appelle aucune API), son
   authentification vue depuis le compte d'agent, et les deux interrupteurs
   de dépense — c'est ce contrôle qui dit si ce cerveau APPRENDRA
8. les sauvegardes DE CE CERVEAU : la dernière, son âge, sa restauration
9. le croisement code <-> schéma : tout ce que le code nomme existe-t-il ?"
        vide
        note "En simulation, rien de tout cela n'existe encore — sauf le point 0,
qui ne regarde que des fichiers du dépôt. Il est donc joué pour de vrai."
        vide
        controle_contrat_variables
        vide
        return $(( ECHECS > 0 ))
    fi

    decouvrir
    titre "Contrôle du cerveau « $BRAIN_NOM » — base « $ARAC_DB »"

    controle_contrat_variables
    controle_description
    if controle_base; then
        controle_roles
        controle_savoir
        controle_schema_refs
    else
        avert "contrôles suivants" "sautés : la base n'est pas exploitable"
    fi
    controle_secrets
    controle_services
    controle_curation
    controle_sauvegardes

    sous_titre "Verdict"
    printf '  %s %d    %s %d    %s %d\n' \
        "$(_c 32 'sains')" "$OK" "$(_c 33 'à surveiller')" "$AVERTS" "$(_c 31 'en échec')" "$ECHECS"
    vide
    if (( ECHECS > 0 )); then
        mal "$(_c 1 'Ce cerveau n'\''est pas sain.')"
        note "Chaque échec ci-dessus est suivi du geste exact qui le corrige.
Reprenez-les dans l'ordre, puis relancez ce contrôle."
        vide
        return 1
    fi
    if (( AVERTS > 0 )); then
        bien "$(_c 1 'Ce cerveau fonctionne.')"
        note "Les points « à surveiller » ne l'empêchent pas de vivre, mais ils
disent ce qu'il ne sait pas encore faire, ou plus faire."
        vide
        return 0
    fi
    bien "$(_c 1 'Ce cerveau est sain.')"
    vide
    return 0
}

# `main` ne s'exécute que si ce fichier est LANCÉ. Sourcé — ce que fait la
# suite de tests pour éprouver un contrôle isolément — il se contente de
# définir. Un contrôle qu'on ne peut pas éprouver seul n'est jamais éprouvé :
# c'est ainsi qu'un faux vert survit des mois.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
