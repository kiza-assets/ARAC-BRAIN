#!/usr/bin/env bash
# ============================================================================
# EST-CE QUE CETTE INSTALLATION TIENT DEBOUT DANS LA DURÉE ?
#
#     sudo ops/install_check.sh                    tous les contrôles
#     sudo ops/install_check.sh --quiet            ne montre que ce qui ne va pas
#
# IL LUI FAUT root, ET IL LE DIT. Le coffre d'un cerveau posé par le bootstrap
# est en 0700 root : sans ce droit, ce contrôle ne lit ni les DSN ni la liste
# blanche d'ingestion. Il ne rend alors AUCUN verdict — il refuse, il nomme le
# coffre de VOTRE cerveau, et il donne le geste. Quand plusieurs cerveaux
# vivent sur la machine, désignez le vôtre :
#
#     sudo ARAC_ENV_FILE=/etc/arac/<votre-base>/arac.env ops/install_check.sh
#
# CODES DE SORTIE   0 saine · 1 des réserves · 2 quelque chose est cassé
#                   3 JE N'AI PAS PU MESURER (droits manquants) — ni bon, ni
#                     mauvais, et surtout pas un ordre de réparer. Même
#                     vocabulaire que scripts/ops/health_check.py (UNKNOWN=3).
#
# TROIS OUTILS RÉPONDENT À TROIS QUESTIONS DIFFÉRENTES — ET C'EST TOUT
# --------------------------------------------------------------------
#   ./bootstrap/checks/verify_install.sh   ce cerveau est-il BIEN POSÉ ?
#                                          (base, rôles, secrets, ports, code
#                                           contre schéma — l'état à l'instant)
#   sudo ops/install_check.sh (ce fichier) tient-il debout DANS LA DURÉE ?
#                                          (sauvegardes, restauration prouvée,
#                                           minuteurs, dérive)
#   scripts/ops/health_check.py            le cerveau lui-même VA-T-IL BIEN ?
#                                          (les 148 métriques du cockpit)
#
# ILS PEUVENT DONC DIRE DES CHOSES DIFFÉRENTES SANS QU'AUCUN NE MENTE. Ce qui
# serait un mensonge, c'est qu'ils se contredisent sur LA MÊME question. Ça
# s'est produit, et c'est ce qui a fait réécrire ce bloc : sur un cerveau
# installé la minute d'avant, parfaitement sain, `verify_install.sh` rendait
# « ✓ Ce cerveau fonctionne » pendant que ce fichier-ci rendait « Cette
# installation ne tient PAS debout » — et il ne POUVAIT structurellement pas
# dire autre chose, puisqu'il exigeait une restauration prouvée qu'aucune
# installation fraîche ne peut avoir. Un ami qui installe parfaitement
# apprenait en trois minutes que son cerveau ne tient pas debout. C'est le
# moment exact où l'on abandonne.
#
# LE QUATRIÈME ÉTAT, ET POURQUOI IL A FALLU L'AJOUTER
# ----------------------------------------------------
# `verify_install.sh` s'est donné cette doctrine en tête de fichier, et elle
# est juste :
#
#     ✓  j'ai mesuré, et c'est bon
#     ✗  j'ai mesuré, et c'est cassé
#     ⚠  JE N'AI PAS PU MESURER — je ne conclus donc rien
#
# Ce contrôle-ci n'en avait que trois, et il manquait le seul qui compte pour
# une installation neuve : « ce n'est pas encore vrai, et ce n'est pas encore
# FAUX non plus ». Une sauvegarde dont le minuteur est armé mais n'a pas
# encore sonné n'est pas une panne : c'est une promesse dont l'échéance n'est
# pas venue. Elle s'écrit donc `?`, elle dit CE QU'IL LUI MANQUE POUR SAVOIR
# et QUAND elle le saura — et elle ne fait pas basculer le verdict. Le jour où
# l'échéance passe sans que rien ne soit arrivé, la même ligne devient `✗`.
#
# « Je n'ai pas pu vérifier » n'est ni « c'est bon » ni « c'est cassé ». Un
# code de sortie, lui, est un ORDRE donné à une machine ; « pas encore » n'est
# pas un ordre de réparer. Les lignes `?` laissent donc le code à 0 — mais
# elles sont imprimées, comptées, et le verdict final les nomme.
#
# QUAND LE LANCER
#   — juste après l'installation, avant de croire qu'elle a marché ;
#   — après une migration, une mise à jour, un redémarrage de serveur ;
#   — quand quelque chose ne va pas et que vous ne savez pas par où commencer ;
#   — une fois par semaine, par une unité systemd, pour que la dérive se voie.
#
# CE QU'IL NE FAIT PAS
#   Il ne répare rien, il ne modifie rien, il n'écrit nulle part. Chaque ligne
#   rouge porte le geste qui la corrige — mais c'est vous qui le faites. Un
#   contrôle qui répare tout seul finit par cacher la panne qu'il répare.
#
#   Il ne dépense rien non plus : aucun appel à un service payant. Vous pouvez
#   le lancer cent fois.
# ============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$HERE/env.sh"

QUIET=0
[ "${1:-}" = "--quiet" ] && QUIET=1

OK=0; WARN=0; FAIL=0; INCONNU=0
SECTION=""

section() { SECTION="$1"; [ "$QUIET" -eq 0 ] && printf '\n%s\n%s\n' "$1" "$(printf '%.0s─' $(seq ${#1}))"; }
ok()   { OK=$((OK+1));   [ "$QUIET" -eq 0 ] && printf '  ✓ %s\n' "$1"; return 0; }
warn() { WARN=$((WARN+1)); printf '  ~ %s\n' "$1"; [ -n "${2:-}" ] && printf '      %s\n' "$2"; return 0; }
bad()  { FAIL=$((FAIL+1)); printf '  ✗ %s\n' "$1"; [ -n "${2:-}" ] && printf '      %s\n' "$2"; return 0; }

#: LE QUATRIÈME ÉTAT. « Je ne peux pas encore savoir » — et l'argument $2 doit
#: dire CE QUI MANQUE POUR SAVOIR, pas ce qu'il faut réparer. Un `?` qui ne
#: dit pas ce qui lui manque est un `✗` mal élevé.
inconnu() {
    INCONNU=$((INCONNU+1))
    printf '  ? %s\n' "$1"
    [ -n "${2:-}" ] && printf '      %s\n' "$2"
    return 0
}

# --- CE QUI M'APPARTIENT --------------------------------------------------
# Le préfixe d'unité de CE cerveau. Le bootstrap l'écrit dans le coffre
# (`ARAC_UNIT_PREFIX`) ; sinon on le dérive du nom de la base, exactement
# comme `bootstrap/lib/config.sh:153`. Sans lui, ce contrôle balaie « arac-* »
# — c'est-à-dire les minuteurs de TOUS les cerveaux de la machine, et un
# minuteur du voisin en échec faisait basculer le verdict de CETTE
# installation. Un nom d'unité ne dit pas à quel cerveau il mène, pas plus
# qu'un numéro de port.
if [ -n "${ARAC_UNIT_PREFIX:-}" ]; then
    MOTIF_UNITES="${ARAC_UNIT_PREFIX}-*"
elif [ -n "${_ARAC_NOM:-}" ]; then
    MOTIF_UNITES="arac-${_ARAC_NOM}-*"
else
    MOTIF_UNITES=""
fi

PY="$(arac_python)"


# ---------------------------------------------------------------------------
# AI-JE SEULEMENT LE DROIT DE MESURER ? — le refus, plutôt que le faux verdict
# ---------------------------------------------------------------------------
#
# CE QUI SE PASSAIT. La page de dépannage met trois commandes en tête ; la
# première porte `sudo`, la deuxième non. Or le coffre d'un cerveau posé par
# le bootstrap est `/etc/arac/<base>/arac.env`, dans un dossier en 0700 root.
# Depuis un compte ordinaire, `ops/env.sh` ne peut ni le lire ni même le
# lister : il retombe sur `$ARAC_HOME/.env`, qu'aucune installation faite par
# le bootstrap n'écrit, et TOUT ce qui suit s'effondre — pas de DSN, pas de
# liste blanche, sept croix. Résultat mesuré sur un cerveau installé la minute
# d'avant : `verify_install.sh` rendait « ✓ Ce cerveau fonctionne » pendant que
# ce fichier-ci rendait « Cette installation ne tient PAS debout », code 2.
#
# LE CHOIX. On ne peut pas « fonctionner sans root » : les secrets sont en
# 0700 root PARCE QUE c'est ce qui empêche le voisin de les lire, et ce n'est
# pas négociable. Reste la deuxième conduite : le DIRE, avec le geste. C'est
# ce que fait déjà `scripts/ops/health_check.py`, qui refuse de conclure et
# imprime le chemin RÉEL du coffre plutôt qu'un gabarit. Ce contrôle-ci
# connaissait pourtant le nom du cerveau (`_ARAC_NOM`, lu dans
# `config/brain.toml`) et tranchait quand même.
#
# LA CONDITION EST ÉTROITE, ET C'EST VOULU. On ne refuse que si le coffre est
# illisible ET que l'environnement ne porte pas déjà ce qu'il contient. Sous
# systemd, l'unité tourne sous un compte non privilégié mais reçoit le coffre
# par `EnvironmentFile=` : les DSN sont là, il n'y a rien à refuser, et le
# contrôle hebdomadaire continue de tourner comme avant.
#
# LE CODE DE SORTIE EST 3, ET PAS 2. « Je n'ai pas pu mesurer » n'est pas
# « c'est cassé ». C'est le même vocabulaire que `health_check.py`
# (EXIT_UNKNOWN = 3) et que le quatrième état `?` de ce fichier : un code de
# sortie est un ORDRE donné à une machine, et « je n'ai rien vu » n'est pas
# un ordre de réparer.
# ---------------------------------------------------------------------------
CODE_NON_MESURABLE=3

if [ ! -r "$ARAC_ENV_FILE" ] && [ -z "${DATABASE_URL_ADMIN:-}${ARAC_DB_URL_ADMIN:-}" ]; then
    if [ -n "${_ARAC_NOM:-}" ]; then
        COFFRE="$ARAC_ETC_DIR/$_ARAC_NOM/arac.env"
    else
        COFFRE="$ARAC_ETC_DIR/<le-nom-de-votre-base>/arac.env"
    fi
    printf '\n%s\n' "CE CONTRÔLE N'A PAS PU MESURER — et il ne rendra donc aucun verdict."
    printf '%s\n' "──────────────────────────────────────────────────────────"
    if [ "$(id -u)" -ne 0 ]; then
        if [ ! -d /etc/arac ]; then
            printf '%s\n' \
"Aucun coffre n'est visible : /etc/arac n'existe pas sur cette machine.
Deux lectures possibles, et ce compte ne peut pas les départager :
aucun cerveau n'a jamais été installé ici par le bootstrap, ou bien
l'installation vit ailleurs (\$ARAC_HOME/.env, installation manuelle)."
        elif [ ! -r "$COFFRE" ]; then
            printf '%s\n' \
"Le coffre de ce cerveau est « $COFFRE », et ce compte ne peut même pas
SAVOIR s'il existe : le dossier qui le contient ne lui est pas
traversable. C'est voulu — il est en 0700 root, et c'est très
exactement ce qui empêche le compte du voisin de lire vos clés."
        fi
        printf '\n%s\n' "LE GESTE :"
        printf '    %s\n' "sudo ARAC_ENV_FILE=$COFFRE ops/install_check.sh"
        printf '\n%s\n' \
"Sans lui, ce contrôle ne lirait ni vos DSN, ni votre liste blanche
d'ingestion : il ne mesurerait pas votre installation, il mesurerait sa
propre cécité — et il conclurait « ne tient PAS debout » sur un cerveau
parfaitement sain. Un verdict rendu sans avoir vu est pire que pas de
verdict du tout."
    else
        printf '%s\n' \
"Vous êtes root, et le fichier d'environnement « $ARAC_ENV_FILE » reste
illisible. Deux cas :
  · installation faite par le bootstrap → le coffre est ailleurs :
      sudo ARAC_ENV_FILE=$COFFRE ops/install_check.sh
  · installation manuelle → il n'a jamais été créé :
      cp '$ARAC_HOME/.env.example' '$ARAC_ENV_FILE' && chmod 600 '$ARAC_ENV_FILE'"
    fi
    # « L'UN D'EUX N'A BESOIN DE RIEN » — ET LES DEUX ÉTAIENT ÉCRITS SANS SUDO.
    #
    # Le lecteur à qui l'on vient de refuser un verdict cherche celui des deux
    # qu'il peut lancer tout de suite. Mesuré sur un cerveau sain, depuis un
    # compte ordinaire : `verify_install.sh` rend un rapport PARTIEL et un
    # code 0 — il dit ce qu'il ne peut pas voir et ne conclut rien à son
    # sujet ; `health_check.py` rend UNKNOWN et sort en 3, sans le moindre
    # bulletin, parce qu'il lit la base avec le rôle en lecture stricte, dont
    # le DSN vit dans le même coffre 0700 root que le nôtre. Les présenter
    # côte à côte sous « l'un d'eux n'a besoin de rien », c'est envoyer une
    # fois sur deux vers le mur qu'on vient de décrire.
    printf '\n%s\n' \
"Les deux autres contrôles répondent à d'autres questions. UN SEUL des deux
se passe de root, et il le dit quand il ne voit pas tout :
  ./bootstrap/checks/verify_install.sh          ce cerveau est-il BIEN POSÉ ?
      sans root : rapport PARTIEL, code 0 — les lignes qu'il n'a pas pu
      mesurer sont marquées « NON CONTRÔLÉ », jamais « absent ».
  sudo -E .venv/bin/python scripts/ops/health_check.py  le cerveau VA-T-IL BIEN ?
      root exigé, pour la MÊME raison que nous : il lit la base avec le
      rôle en lecture stricte, et ce DSN vit dans $COFFRE.
      Sans lui : « UNKNOWN », aucun bulletin, code 3."
    exit "$CODE_NON_MESURABLE"
fi


# ---------------------------------------------------------------------------
section "1. LE DÉPÔT ET SON ENVIRONNEMENT"
# ---------------------------------------------------------------------------

[ -d "$ARAC_HOME" ] \
    && ok "racine d'installation : $ARAC_HOME" \
    || bad "racine introuvable : $ARAC_HOME" "posez ARAC_HOME sur le dépôt cloné"

if [ -f "$ARAC_ENV_FILE" ]; then
    MODE="$(stat -c %a "$ARAC_ENV_FILE")"
    if [ "$MODE" = "600" ]; then
        ok "fichier d'environnement présent, mode 600"
    else
        bad "fichier d'environnement en mode $MODE (attendu 600)" \
            "chmod 600 '$ARAC_ENV_FILE' — il contient toutes vos clés d'API"
    fi
    # Un .env versionné est une fuite définitive : même supprimé, l'historique
    # de git le garde, et les clés doivent être révoquées.
    if git -C "$ARAC_HOME" ls-files --error-unmatch "$(basename "$ARAC_ENV_FILE")" >/dev/null 2>&1; then
        bad "le fichier d'environnement est SUIVI PAR GIT" \
            "révoquez toutes les clés qu'il contient, puis : git rm --cached .env"
    else
        ok "le fichier d'environnement n'est pas suivi par git"
    fi
else
    bad "aucun fichier d'environnement : $ARAC_ENV_FILE" \
        "Deux cas, ne les confondez pas :
      · installé par le bootstrap → le fichier vit dans /etc/arac/<base>/arac.env
        et n'est lisible que par root. Relancez en root, ou :
          sudo ARAC_ENV_FILE=/etc/arac/<base>/arac.env ops/install_check.sh
      · installation manuelle → créez-le :
          cp '$ARAC_HOME/.env.example' '$ARAC_ENV_FILE' && chmod 600 '$ARAC_ENV_FILE'"
fi

if [ -x "$PY" ]; then
    PYV="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)"
    ok "interpréteur de l'installation : $PY (Python $PYV)"
    "$PY" -c "import psycopg, fastapi, alembic" 2>/dev/null \
        && ok "dépendances essentielles importables (psycopg, fastapi, alembic)" \
        || bad "des dépendances manquent" "make venv"
else
    bad "interpréteur introuvable : $PY" "make venv, ou posez ARAC_PYTHON"
fi


# ---------------------------------------------------------------------------
section "2. L'IDENTITÉ ET LA TAXONOMIE — ce cerveau est-il le vôtre ?"
# ---------------------------------------------------------------------------

NODE_ID=""
if [ -x "$PY" ]; then
    NODE_ID="$("$PY" -c 'import arac_runtime as r; print(r.node_id())' 2>/dev/null)"
    if [ -n "$NODE_ID" ]; then
        ok "identité déclarée : node_id = $NODE_ID"
    else
        bad "ce cerveau n'a pas d'identité (config/brain.toml absent ou incomplet)" \
            "python3 bootstrap/wizard.py — le cerveau refuse toute conversation d'un nœud non déclaré"
    fi

    # La liste blanche d'ingestion. Elle est *fail-closed* — absente, l'API
    # refuse TOUT dépôt en 403 — et son absence ne se manifeste nulle part
    # ailleurs : les services tournent, le cockpit répond, la synchronisation
    # se déclare satisfaite, et la mémoire reste vide. C'est un contrôle
    # d'installation parce que c'est là qu'on le cherche, pas dans un journal.
    if [ -z "${ARAC_INGEST_ALLOWED_NODES:-}" ]; then
        bad "ARAC_INGEST_ALLOWED_NODES absente : l'ingestion refuse TOUT (403)" \
            "ajoutez votre node_id à '$ARAC_ENV_FILE', puis redémarrez l'API.
      Fail-closed volontaire : sans liste, un jeton valide ne suffit pas.
      C'est ce qui empêche un dépôt anonyme de devenir un faux souvenir."
    elif [ -n "$NODE_ID" ]; then
        case ",${ARAC_INGEST_ALLOWED_NODES}," in
            *",${NODE_ID},"*)
                ok "liste blanche d'ingestion : « $ARAC_INGEST_ALLOWED_NODES »" ;;
            *)
                bad "« $NODE_ID » n'est PAS dans ARAC_INGEST_ALLOWED_NODES" \
                    "liste actuelle : « $ARAC_INGEST_ALLOWED_NODES ».
      Tout ce que ce poste dépose repart en 403." ;;
        esac
    else
        warn "liste blanche posée, mais l'identité locale est inconnue" \
             "impossible de vérifier qu'elle couvre ce cerveau"
    fi

    if [ -f "$ARAC_HOME/config/scopes.toml" ]; then
        if "$PY" "$ARAC_HOME/bootstrap/generate_scopes.py" --check >/dev/null 2>&1; then
            ok "taxonomie : l'énumération et le seed sont à jour"
        else
            bad "la taxonomie générée diverge de config/scopes.toml" \
                "make scopes — sinon le code et la base ne parlent pas des mêmes scopes"
        fi
    else
        bad "config/scopes.toml absent" "python3 bootstrap/wizard.py"
    fi
fi


# ---------------------------------------------------------------------------
section "3. LA BASE — les rôles, et leurs pouvoirs séparés"
# ---------------------------------------------------------------------------

if ! command -v psql >/dev/null 2>&1; then
    warn "psql absent : les contrôles de base sont sautés" "apt install postgresql-client"
else
    for pair in "ADMIN:DATABASE_URL_ADMIN" "APP:DATABASE_URL_APP" \
                "AGENT:DATABASE_URL_AGENT" "READONLY:DATABASE_URL_READONLY" \
                "BACKUP:DATABASE_URL_BACKUP"; do
        label="${pair%%:*}"; var="${pair##*:}"
        dsn="${!var:-}"
        if [ -z "$dsn" ]; then
            if [ "$label" = "BACKUP" ]; then
                warn "rôle BACKUP non configuré ($var)" \
                     "la sauvegarde tournera sous le rôle ADMIN — elle marchera, mais un
      processus automatique non surveillé aura le pouvoir de détruire le schéma"
            else
                bad "$var n'est pas définie"
            fi
            continue
        fi
        if psql "$dsn" -qtAc "SELECT 1" >/dev/null 2>&1; then
            ok "rôle $label : connexion établie"
        else
            bad "rôle $label : connexion refusée ($(arac_dsn_redacted "$dsn"))" \
                "mot de passe, pg_hba.conf, ou rôle inexistant"
        fi
    done

    RO="${DATABASE_URL_READONLY:-}"
    if [ -n "$RO" ] && psql "$RO" -qtAc "SELECT 1" >/dev/null 2>&1; then
        # On ne fait pas CONFIANCE au rôle : on essaie d'écrire. Un cockpit qui
        # peut écrire n'est plus un cockpit, et cela ne se voit pas autrement.
        if psql "$RO" -qtAc "CREATE TABLE IF NOT EXISTS public._arac_probe(x int)" >/dev/null 2>&1; then
            bad "le rôle READONLY a réussi à créer une table" \
                "il n'est pas en lecture stricte — révisez ses GRANT immédiatement"
            psql "${DATABASE_URL_ADMIN:-$RO}" -qtAc "DROP TABLE IF EXISTS public._arac_probe" >/dev/null 2>&1
        else
            ok "le rôle READONLY ne peut PAS écrire (vérifié, pas supposé)"
        fi

        SCHEMA_OK="$(psql "$RO" -qtAc \
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='$ARAC_DB_SCHEMA' AND table_type='BASE TABLE'" 2>/dev/null)"
        [ "${SCHEMA_OK:-0}" -gt 0 ] \
            && ok "schéma « $ARAC_DB_SCHEMA » : ${SCHEMA_OK} tables" \
            || bad "schéma « $ARAC_DB_SCHEMA » vide ou absent" "appliquez les migrations"

        for ext in vector pg_trgm; do
            HAS="$(psql "$RO" -qtAc "SELECT count(*) FROM pg_extension WHERE extname='$ext'" 2>/dev/null)"
            [ "${HAS:-0}" = "1" ] \
                && ok "extension $ext installée" \
                || bad "extension $ext ABSENTE" \
                       "sans elle, ni embeddings ni restauration : CREATE EXTENSION $ext; (superutilisateur)"
        done

        DBREV="$(psql "$RO" -qtAc "SELECT version_num FROM $ARAC_DB_SCHEMA.alembic_version LIMIT 1" 2>/dev/null)"
        FILEREV="$(ls -1 "$ARAC_HOME/db/alembic/versions"/*.py 2>/dev/null | sed 's#.*/##; s/\.py$//' | sort | tail -1)"
        if [ -z "$DBREV" ]; then
            bad "aucune version de schéma en base" "les migrations n'ont jamais été appliquées"
        elif [ "$DBREV" = "$FILEREV" ]; then
            ok "migrations à jour ($DBREV)"
        else
            warn "la base est en $DBREV, le dépôt fournit jusqu'à $FILEREV" \
                 "appliquez les migrations manquantes avant de vous fier au cockpit"
        fi

        NSCOPES="$(psql "$RO" -qtAc "SELECT count(*) FROM $ARAC_DB_SCHEMA.scopes" 2>/dev/null)"
        [ "${NSCOPES:-0}" -gt 0 ] \
            && ok "taxonomie semée en base : ${NSCOPES} scopes" \
            || bad "aucun scope en base" \
"le remède porte le DSN de CE cerveau — une redirection nue viserait la
      grappe par défaut de la machine, c'est-à-dire la base d'un voisin :
        psql \"\$DATABASE_URL_ADMIN\" -f db/seeds/scopes.sql   (généré par make scopes)"

        if [ -n "$NODE_ID" ]; then
            HASNODE="$(psql "$RO" -qtAc "SELECT count(*) FROM $ARAC_DB_SCHEMA.nodes WHERE node_id='$NODE_ID'" 2>/dev/null)"
            [ "${HASNODE:-0}" = "1" ] \
                && ok "le nœud « $NODE_ID » est déclaré en base" \
                || bad "le nœud « $NODE_ID » n'existe pas en base" \
                       "toute conversation venant de ce poste sera REFUSÉE (db/seeds/01_nodes_and_config.sql)"
        fi
    fi
fi


# ---------------------------------------------------------------------------
section "4. LA SAUVEGARDE — ce qui reste quand le reste a disparu"
# ---------------------------------------------------------------------------

if [ -d "$ARAC_BACKUP_DIR" ]; then
    BMODE="$(stat -c %a "$ARAC_BACKUP_DIR")"
    ok "répertoire de sauvegarde : $ARAC_BACKUP_DIR (mode $BMODE)"
    [ "$BMODE" = "700" ] || warn "mode $BMODE : les dumps sont lisibles par d'autres" \
        "chmod 700 '$ARAC_BACKUP_DIR' — un dump contient l'intégralité du cerveau, en clair"
    DUMP="$(arac_newest "$ARAC_BACKUP_DIR" "$ARAC_BACKUP_PREFIX-*.dump")"
    [ -z "$DUMP" ] && DUMP="$(arac_newest "$ARAC_BACKUP_DIR" "$ARAC_BACKUP_PREFIX-*.dump.age")"
    if [ -n "$DUMP" ]; then
        AGE="$(arac_age_hours "$DUMP")"
        [ "$AGE" -le 48 ] \
            && ok "dernier dump il y a ${AGE} h" \
            || warn "dernier dump il y a ${AGE} h" "ops/backup.sh, puis vérifiez le timer"
    else
        # AUCUN DUMP : PANNE, OU ÉCHÉANCE NON VENUE ? Les deux se ressemblent
        # et ne demandent pas le même geste. On ne devine pas : on demande à
        # systemd si le minuteur de CE cerveau a déjà sonné. `LastTriggerUSec`
        # vaut `n/a` tant qu'il n'a jamais tiré.
        _T_SAUV=""
        [ -n "$MOTIF_UNITES" ] && command -v systemctl >/dev/null 2>&1 && \
            _T_SAUV="$(systemctl list-units --plain --no-legend --no-pager --type=timer \
                       "${MOTIF_UNITES%-\*}-sauvegarde.timer" 2>/dev/null | awk '{print $1}')"
        if [ -n "$_T_SAUV" ]; then
            _DERNIER="$(systemctl show -p LastTriggerUSec --value "$_T_SAUV" 2>/dev/null)"
            _PROCHAIN="$(systemctl show -p NextElapseUSecRealtime --value "$_T_SAUV" 2>/dev/null)"
            # `LastTriggerUSec` SURVIT À L'UNITÉ QUI L'A PRODUIT.
            #
            # systemd garde l'estampille d'un minuteur persistant dans
            # /var/lib/systemd/timers/stamp-<unité>.timer. Ni la suppression de
            # l'unité, ni `daemon-reload`, ni `reset-failed` ne l'effacent :
            # une unité HOMONYME créée plus tard hérite de la date d'une autre
            # installation. Sur un dépôt dont le bootstrap est explicitement
            # rejouable, réinstaller un cerveau du même nom suffisait à faire
            # dire à ce contrôle « le minuteur a déjà sonné et rien n'arrive »
            # — un ✗, code 2, pour un minuteur qui n'avait jamais tiré.
            #
            # On ne croit donc cette date que si elle est POSTÉRIEURE à
            # l'activation de l'unité présente. Sinon, elle ne parle pas de
            # cette installation, et un contrôle qui ne peut pas mesurer ne
            # tranche pas : il rend « ? ».
            _DEPUIS="$(systemctl show -p ActiveEnterTimestamp --value "$_T_SAUV" 2>/dev/null)"
            _ESTAMPILLE_ETRANGERE=0
            if [ -n "$_DERNIER" ] && [ "$_DERNIER" != "n/a" ] && [ -n "$_DEPUIS" ]; then
                _T_D="$(date -d "$_DERNIER" +%s 2>/dev/null || echo 0)"
                _T_A="$(date -d "$_DEPUIS"  +%s 2>/dev/null || echo 0)"
                [ "${_T_D:-0}" -gt 0 ] && [ "${_T_A:-0}" -gt 0 ] && [ "$_T_D" -lt "$_T_A" ] \
                    && _ESTAMPILLE_ETRANGERE=1
            fi
            if [ "$_ESTAMPILLE_ETRANGERE" = 1 ]; then
                inconnu "aucun dump — et l'estampille du minuteur est ANTÉRIEURE à cette installation" \
                    "CE QUI MANQUE POUR SAVOIR : un premier passage de $_T_SAUV pour CETTE
      installation. La date rendue par systemd ($_DERNIER) précède
      l'activation de l'unité présente ($_DEPUIS) : elle vient d'une unité
      homonyme antérieure, dont systemd garde l'estampille (stamp-$_T_SAUV).
      Pour ne pas attendre : sudo systemctl start ${_T_SAUV%.timer}.service"
            elif [ -z "$_DERNIER" ] || [ "$_DERNIER" = "n/a" ] || [ "$_DERNIER" = "0" ]; then
                inconnu "aucun dump — et le minuteur n'a pas encore sonné une seule fois" \
                    "CE QUI MANQUE POUR SAVOIR : un premier passage de $_T_SAUV${_PROCHAIN:+ (prochain : $_PROCHAIN)}.
      Une sauvegarde qui n'a pas encore eu lieu n'est pas une sauvegarde
      manquante. Pour ne pas attendre : sudo systemctl start ${_T_SAUV%.timer}.service"
            else
                bad "aucun dump, alors que $_T_SAUV a déjà sonné (dernier : $_DERNIER)" \
                    "le minuteur tire et rien n'arrive : journalctl -u ${_T_SAUV%.timer}.service -n 50 --no-pager"
            fi
        else
            bad "aucun dump, et aucun minuteur de sauvegarde pour ce cerveau" \
                "rien ne produira jamais de dump. ops/backup.sh une fois à la main, puis armez le minuteur"
        fi
        unset _T_SAUV _DERNIER _PROCHAIN _DEPUIS _ESTAMPILLE_ETRANGERE _T_D _T_A
    fi
else
    bad "répertoire de sauvegarde absent : $ARAC_BACKUP_DIR" \
        "sudo install -d -m 0700 -o \"\$(id -un)\" '$ARAC_BACKUP_DIR'"
fi

if [ -e "$ARAC_BACKUP_STATE/last_verify_ok" ]; then
    VAGE="$(arac_age_hours "$ARAC_BACKUP_STATE/last_verify_ok")"
    [ "$VAGE" -le 240 ] \
        && ok "dernière restauration PROUVÉE il y a ${VAGE} h" \
        || warn "dernière restauration prouvée il y a ${VAGE} h" "ops/restore_verify.sh"
else
    # ON DEMANDE À SYSTEMD AVANT DE PARLER DE SYSTEMD.
    #
    # CE QUE CE BLOC RÉPARE, ET IL SE DÉMENTAIT LUI-MÊME DOUZE LIGNES PLUS BAS.
    # Il servait, sur TOUTE installation neuve : « aucune restauration n'a
    # jamais été vérifiée / … Aucun minuteur ne le fait à votre place — c'est
    # un geste qu'on décide. » Puis la section 5 du même écran imprimait
    # « arac-<base>-restauration.timer », armé, avec sa prochaine échéance.
    #
    # C'était vrai quand le bootstrap n'armait que la sauvegarde. Il pose
    # désormais l'unité de restauration (bootstrap/lib/services.sh), qui lance
    # `ops/restore_verify.sh` chaque dimanche à 03:00 et pose ce témoin. Le
    # commentaire qui portait la décision décrivait un dépôt qui n'existe plus,
    # et personne ne l'avait relu parce que le TÉMOIN, lui, manquait vraiment.
    #
    # La leçon est générale, et c'est elle qu'on applique ici : un témoin
    # absent autorise à dire « je ne sais pas ». Il n'autorise pas à dire
    # POURQUOI il est absent. La raison, c'est systemd qui la détient.
    _T_REST=""
    [ -n "$MOTIF_UNITES" ] && command -v systemctl >/dev/null 2>&1 && \
        _T_REST="$(systemctl list-units --plain --no-legend --no-pager --type=timer \
                   "${MOTIF_UNITES%-\*}-restauration.timer" 2>/dev/null | awk '{print $1}')"
    if [ -n "$_T_REST" ]; then
        _R_PROCHAIN="$(systemctl show -p NextElapseUSecRealtime --value "$_T_REST" 2>/dev/null)"
        inconnu "aucune restauration n'a encore été vérifiée sur cette installation" \
            "CE QUI MANQUE POUR SAVOIR : un premier passage de $_T_REST${_R_PROCHAIN:+ (prochain : $_R_PROCHAIN)}.
      Ce minuteur est armé et lance ops/restore_verify.sh : il restaure un
      dump dans une base jetable, compte les lignes et pose le témoin qui
      éteint cette réserve. Vous n'avez rien à armer.
      Pour ne pas attendre dimanche :
          sudo systemctl start ${_T_REST%.timer}.service"
    else
        inconnu "aucune restauration n'a jamais été vérifiée" \
            "CE QUI MANQUE POUR SAVOIR : un passage de ops/restore_verify.sh, qui
      restaure un dump dans une base jetable et compte les lignes. Aucun
      minuteur de CE cerveau ne le fait — le bootstrap en pose un
      (« …-restauration.timer »), et il n'est pas là. Tant que ce passage
      n'a pas eu lieu, vos dumps sont une hypothèse : ni prouvée, ni réfutée."
    fi
    unset _T_REST _R_PROCHAIN
fi

if [ -n "${ARAC_BACKUP_RECIPIENTS:-}" ] && [ -r "${ARAC_BACKUP_RECIPIENTS}" ]; then
    ok "chiffrement au repos configuré ($(wc -l < "$ARAC_BACKUP_RECIPIENTS") destinataire(s))"
else
    warn "chiffrement au repos DÉSACTIVÉ" \
         "les dumps sont en clair sur le disque ; voir docs/SAUVEGARDE.md"
fi

if [ -n "${ARAC_OFFSITE_DEST:-}" ]; then
    LASTOK="$(arac_newest "$ARAC_BACKUP_STATE/receipts" '*.ok')"
    if [ -n "$LASTOK" ]; then
        ok "copie hors site : dernier accusé il y a $(arac_age_hours "$LASTOK") h"
    else
        warn "copie hors site configurée, mais aucun accusé de réception" "ops/backup_offsite.sh"
    fi
else
    warn "aucune copie hors site" \
         "vos sauvegardes disparaîtront avec le serveur qui les héberge"
fi

if command -v psql >/dev/null 2>&1 && MAINT="$(arac_maintenance_dsn 2>/dev/null)"; then
    TPL="${ARAC_RESTORE_TEMPLATE_DB:-${ARAC_BACKUP_PREFIX}_restore_template}"
    # CE CONTRÔLE EXIGEAIT `datistemplate`, ET IL AVAIT TORT.
    #
    # Un rôle non superutilisateur peut copier une base pour deux raisons :
    # elle est marquée `datistemplate` (et alors TOUT rôle du serveur ayant
    # CREATEDB peut la copier, y compris celui du cerveau voisin), ou bien il
    # la POSSÈDE. Le bootstrap pose désormais la seconde forme, plus étroite.
    # Exiger la première déclarait « absent » un gabarit présent et utilisable
    # — un faux manque, qui envoie rejouer un geste de superutilisateur dont
    # on n'a pas besoin.
    HAS_TPL="$(psql "$MAINT" -qtAc "SELECT count(*) FROM pg_database WHERE datname='$TPL'" 2>/dev/null)"
    [ "${HAS_TPL:-0}" = "1" ] \
        && ok "gabarit de restauration présent ($TPL)" \
        || warn "gabarit de restauration absent" \
                "ops/restore_verify.sh --prepare-template — sans lui, la vérification
      hebdomadaire réclame le superutilisateur pour créer l'extension pgvector"

    # L'AUTRE MOITIÉ DE LA MÊME PROMESSE, ET C'EST ELLE QUI MANQUAIT.
    #
    # Le gabarit ne sert à rien si le rôle ne peut pas le copier : copier une
    # base exige CREATEDB, gabarit ou pas. Le dépôt donnait le gabarit et pas
    # l'attribut ; `ops/restore_verify.sh` mourait sur « permission denied to
    # create database » sur toute installation, et la réserve « aucune
    # restauration n'a jamais été vérifiée » ne pouvait être levée par
    # personne. On mesure donc les DEUX, séparément, pour que le message dise
    # laquelle des deux manque.
    ROLE_MAINT="$(arac_dsn_user "$MAINT")"
    if [ -n "$ROLE_MAINT" ]; then
        CAN_CREATE="$(psql "$MAINT" -qtAc \
            "SELECT rolcreatedb FROM pg_roles WHERE rolname='$ROLE_MAINT'" 2>/dev/null)"
        if [ "$CAN_CREATE" = "t" ]; then
            ok "le rôle « $ROLE_MAINT » peut créer une base jetable (CREATEDB)"
        else
            warn "le rôle « $ROLE_MAINT » n'a pas CREATEDB : aucune restauration ne peut être vérifiée" \
                 "ops/restore_verify.sh --prepare-template (le SQL imprimé le donne), ou
      relancez le bootstrap : sudo ./bootstrap/bootstrap.sh --from base
      CREATEDB ne donne aucun droit sur une base existante, et la base
      vivante ne lui appartient pas : il ne peut pas la détruire."
        fi
    fi
fi


# ---------------------------------------------------------------------------
section "5. LES SERVICES — informatif, pas bloquant"
# ---------------------------------------------------------------------------
#
# Les noms d'unités dépendent de votre installation : ce contrôle rapporte ce
# qu'il voit, il n'exige rien. Une unité absente n'est pas une panne si vous
# avez choisi cron, un autre superviseur, ou rien du tout.
#
# CE MOTIF ÉTAIT « arac-* », ET IL RAMASSAIT LES VOISINS. Sur une machine à
# plusieurs cerveaux, il attrapait les minuteurs de tous et les unités
# globales de l'hôte. Le dégât n'était pas cosmétique : une unité d'un cerveau
# VOISIN dont le dernier passage avait échoué était comptée comme une panne
# ICI, et le verdict basculait sur « Cette installation ne tient PAS debout »
# pour une installation qui n'avait rien. C'est la faute du §0 du dépannage,
# montée d'un cran : un nom d'unité ne dit pas à quel cerveau il mène, pas
# plus qu'un numéro de port. On ne regarde donc que « $MOTIF_UNITES », dérivé
# de l'identité de CE cerveau — et ce qui appartient aux autres est listé à
# part, sans peser sur le verdict.

if command -v systemctl >/dev/null 2>&1 && [ -z "$MOTIF_UNITES" ]; then
    inconnu "impossible de savoir quelles unités sont les vôtres" \
        "CE QUI MANQUE POUR SAVOIR : ARAC_UNIT_PREFIX dans le coffre, ou le nom
      de la base (config/brain.toml). Sans l'un des deux, ce contrôle ne peut
      que balayer « arac-* » — donc les minuteurs des voisins. Il préfère se
      taire : un verdict fondé sur les unités de quelqu'un d'autre est faux."
elif command -v systemctl >/dev/null 2>&1; then
    # On regarde les MINUTEURS, pas les services. Un service déclenché par un
    # minuteur est « inactive » 23 h 59 par jour : c'est son état normal, et le
    # signaler apprend à ignorer ce contrôle. Ce qui compte, c'est : le minuteur
    # est-il armé, et son dernier passage a-t-il échoué ?
    TIMERS="$(systemctl list-units --plain --no-legend --no-pager --type=timer "$MOTIF_UNITES" 2>/dev/null | awk '{print $1}')"
    if [ -n "$TIMERS" ]; then
        while read -r t; do
            [ -z "$t" ] && continue
            st="$(systemctl is-active "$t" 2>/dev/null)"
            nxt="$(systemctl show -p NextElapseUSecRealtime --value "$t" 2>/dev/null)"
            if [ "$st" = "active" ]; then
                ok "minuteur $t armé${nxt:+ — prochain passage : $nxt}"
            else
                warn "minuteur $t : $st" "systemctl enable --now $t"
            fi
        done <<<"$TIMERS"
    else
        warn "aucun minuteur systemd « $MOTIF_UNITES »" \
             "rien n'est planifié pour CE cerveau : ni sauvegarde, ni vérification,
      ni surveillance. Voir ops/systemd/README.md"
    fi

    FAILED="$(systemctl list-units --plain --no-legend --no-pager --state=failed "$MOTIF_UNITES" 2>/dev/null | awk '{print $1}')"
    if [ -n "$FAILED" ]; then
        while read -r u; do
            [ -z "$u" ] && continue
            bad "$u : DERNIER PASSAGE EN ÉCHEC" "journalctl -u $u -n 50 --no-pager"
        done <<<"$FAILED"
    else
        ok "aucune unité « $MOTIF_UNITES » en échec"
    fi

    # LES AUTRES : nommés, jamais comptés. Les taire ferait croire qu'ils
    # n'existent pas ; les compter ferait échouer ce cerveau pour la panne
    # d'un autre. On les montre, et on dit à qui ils sont.
    AUTRES="$(systemctl list-units --plain --no-legend --no-pager --type=timer 'arac-*' 2>/dev/null \
              | awk '{print $1}' | grep -vxF -- "$(printf '%s' "$TIMERS")" 2>/dev/null)"
    if [ -n "$AUTRES" ] && [ "$QUIET" -eq 0 ]; then
        printf '  · autres minuteurs « arac-* » sur cette machine — PAS LES VÔTRES :\n'
        while read -r a; do
            [ -z "$a" ] && continue
            printf '      %s (%s)\n' "$a" "$(systemctl is-active "$a" 2>/dev/null)"
        done <<<"$AUTRES"
        printf '      Ils appartiennent à un autre cerveau, ou à la machine. Leur état\n'
        printf '      ne dit rien du vôtre, et ne pèse pas sur le verdict ci-dessous.\n'
    fi
else
    inconnu "systemd absent — planification non vérifiable" \
        "CE QUI MANQUE POUR SAVOIR : systemctl. Si vous avez choisi cron ou un
      autre superviseur, ce contrôle ne sait pas le lire — ce n'est pas une
      panne, c'est un angle mort assumé."
fi


section "6. LA CURATION — ce qui décide si ce cerveau APPREND"
# ---------------------------------------------------------------------------
#
# Ce contrôle mesure la DURÉE : « ce cerveau va-t-il encore bien dans six
# mois ? ». Or il existe une panne qui ne se voit sur AUCUNE autre ligne — ni
# service, ni minuteur, ni sauvegarde : le binaire de curation a disparu (une
# mise à jour npm, un nvm désinstallé, un PATH de service changé), et depuis,
# chaque cycle s'arrête sans produire un souvenir. Tout est vert, et le
# cerveau n'apprend plus. On le regarde donc ici, où l'on regarde la durée.
#
# On ne dépense rien : `claude auth status` ne parle à personne.

CLAUDE_BIN_LU=""
if [ -r "$ARAC_ENV_FILE" ]; then
    CLAUDE_BIN_LU="$(sed -n 's/^ARAC_CLAUDE_BIN=//p' "$ARAC_ENV_FILE" | tail -1)"
fi
[ -z "$CLAUDE_BIN_LU" ] && CLAUDE_BIN_LU="$(command -v claude 2>/dev/null || true)"
if [ -z "$CLAUDE_BIN_LU" ] || [ ! -x "$CLAUDE_BIN_LU" ]; then
    warn "binaire de curation ABSENT — ce cerveau ingère sans plus rien apprendre" \
         "La digestion n'appelle aucune API : elle lance « claude » sur ce serveur.
      sudo npm install -g @anthropic-ai/claude-code
      (ou nommez-le : ARAC_CLAUDE_BIN=<chemin> dans le coffre de ce cerveau)"
else
    ok "binaire de curation $CLAUDE_BIN_LU"
fi

# ---------------------------------------------------------------------------
printf '\n%s\n' "──────────────────────────────────────────────────────────"
# CETTE LIGNE EST CITÉE MOT POUR MOT PAR docs/INSTALLATION.md §7. Le quatrième
# état s'imprime donc SOUS elle, sur sa propre ligne : ajouter un compteur ici
# rendrait fausse une phrase juste, dans un fichier que cette manche n'a pas le
# droit d'ouvrir. Une correction qui périme la documentation de quelqu'un
# d'autre n'est pas une correction, c'est un déplacement de dette.
printf '%d contrôle(s) au vert, %d réserve(s), %d panne(s).\n' "$OK" "$WARN" "$FAIL"
printf 'Ce contrôle mesure la DURÉE (sauvegardes, restauration prouvée, minuteurs).\n'
printf '  ./bootstrap/checks/verify_install.sh   dit si ce cerveau est BIEN POSÉ\n'
printf '  .venv/bin/python scripts/ops/health_check.py   dit si le cerveau VA BIEN\n'
printf 'Les trois répondent à trois questions ; un désaccord entre eux sur des\n'
printf 'questions différentes n%s\n' "'est pas une contradiction."
if [ "$INCONNU" -gt 0 ]; then
    printf '\n%d point(s) ne sont PAS ENCORE vérifiables — ni bons, ni mauvais.\n' "$INCONNU"
    printf 'Les lignes « ? » ci-dessus ne sont ni bonnes ni mauvaises : ce contrôle ne PEUT\n'
    printf 'pas encore les trancher, et chacune dit ce qui lui manque pour savoir. Une\n'
    printf 'installation neuve en porte normalement deux — la première sauvegarde et\n'
    printf 'la première restauration prouvée. Elles ne font pas échouer ce contrôle.\n'
fi
if [ "$FAIL" -gt 0 ]; then
    printf '\nCette installation ne tient PAS debout. Chaque ligne ✗ porte son geste.\n'
    exit 2
elif [ "$WARN" -gt 0 ]; then
    printf '\nElle fonctionne, avec des réserves. Lisez les lignes ~ : ce sont des\n'
    printf 'promesses que vous croyez tenues et qui ne le sont pas encore.\n'
    exit 1
fi
printf '\nInstallation saine.\n'
exit 0
