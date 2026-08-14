#!/usr/bin/env bash
# ===========================================================================
# acceptance.sh — LE CRITÈRE DE RÉUSSITE DU FRAMEWORK, RENDU EXÉCUTABLE.
#
#     Le framework est prêt quand un utilisateur extérieur peut, SANS
#     INTERVENTION : cloner le dépôt · suivre la documentation · installer
#     ARAC · créer son cerveau · synchroniser ses premières conversations ·
#     VOIR SON CERVEAU APPRENDRE · utiliser son cockpit.
#
# Neuf étapes, neuf verdicts, neuf preuves. Ce script installe RÉELLEMENT un
# cerveau, du clone au cockpit, le DÉSINSTALLE en jouant le §13 à la lettre,
# puis démonte son propre banc — y compris quand il échoue.
#
# La neuvième est venue tard, et pour une raison : les huit premières prouvaient
# qu'on peut ARRIVER. Aucune ne prouvait qu'on peut PARTIR — ni qu'après le
# départ il ne reste, nulle part sur la machine, une copie de la mémoire.
#
# ---------------------------------------------------------------------------
# LES QUATRE VERDICTS, ET POURQUOI IL EN FAUT QUATRE
# ---------------------------------------------------------------------------
#
#   PROUVÉ       l'étape a été exercée, et ce qu'elle affirme est mesuré.
#   PARTIEL      exercée, mais une partie de ce qu'elle affirme n'a pas pu
#                l'être — et cette partie est NOMMÉE.
#   NON TESTÉ    pas exercée du tout. Ce n'est pas un échec : c'est une
#                absence de preuve, et elle se dit.
#   ÉCHEC        exercée, et le résultat contredit ce qui est promis.
#
# Un test qui ne connaîtrait que « réussi » et « échoué » serait obligé de
# mentir dans les deux sens : appeler « réussi » ce qu'il n'a pas vérifié, ou
# « échoué » ce qu'il n'a pas pu vérifier. Les étapes 5 et 6 vivent
# précisément dans cet entre-deux — le pont Mac n'existe pas sur un serveur,
# les embeddings coûtent de l'argent — et c'est là que se joue l'honnêteté de
# ce fichier.
#
# ---------------------------------------------------------------------------
# « SANS INTERVENTION » EST UN CRITÈRE, PAS UNE COMMODITÉ
# ---------------------------------------------------------------------------
#
# Chaque fois que ce harnais doit poser un geste que le bootstrap aurait dû
# poser lui-même, il l'enregistre dans le registre des INTERVENTIONS et le
# rapporte en tête. Une seule intervention suffit à ce que le framework ne
# soit PAS prêt, quel que soit l'état des neuf étapes : l'utilisateur, lui,
# n'aura pas ce script pour l'aider.
#
# ---------------------------------------------------------------------------
# CE QUI PROTÈGE LA MACHINE — à lire avant de toucher à ce fichier
# ---------------------------------------------------------------------------
#
# Ce script crée une base, cinq rôles, deux comptes système, six unités
# systemd, et les détruit. C'est l'outil le plus dangereux du dépôt. Trois
# règles, toutes mécaniques :
#
#   1. TOUT est marqué. Cluster, cerveau, base, unités, comptes, dossiers :
#      chaque nom porte « acceptation ». C'est ce qui rend le démontage
#      DÉCIDABLE — voir tests/acceptance/garde_isolement.sh.
#   2. RIEN ne démarre avant les gardes. Ports de production refusés
#      nommément, ports d'essai constatés libres, unités et cluster constatés
#      absents. Un doute vaut un refus : « je n'ai pas pu savoir » n'est
#      jamais « c'est libre ».
#   3. RIEN n'est détruit sans être revalidé. Le démontage repasse les gardes
#      sur chaque valeur AVANT de l'effacer. Entre le démarrage et la fin, il
#      s'est écoulé une installation entière.
#
# Et, de part et d'autre, la preuve que la production est intacte : les
# services vivants, la sonde de l'API, le compte des souvenirs, et
# l'EMPREINTE DES MOTS DE PASSE DES RÔLES du cluster de production. Ce
# dernier contrôle est le seul qui aurait attrapé l'incident d'origine — un
# `ALTER ROLE … PASSWORD` ne casse rien de visible avant le redémarrage
# suivant des services de la victime, des heures plus tard.
#
# Usage :  sudo tests/acceptance/acceptance.sh --help
# ===========================================================================

# `set -e` est VOLONTAIREMENT absent. Ce script mesure des échecs : ils sont
# sa matière première, pas sa fin. `-u` et `pipefail` restent armés.
set -uo pipefail

# ---------------------------------------------------------------------------
# LA RÈGLE QUI DÉCOULE DE `pipefail` : AUCUN TEXTE N'ENTRE DANS UN `grep`
# PAR UN TUYAU. On le lui donne par une CHAÎNE ICI (`<<<"$var"`).
# ---------------------------------------------------------------------------
#
# `grep -q` sort au PREMIER appariement et ferme le tuyau. Le producteur, qui
# n'a pas fini d'écrire, meurt alors de SIGPIPE et rend 141 ; `pipefail` le
# remonte comme code du pipeline, et la CONDITION devient fausse ALORS QUE LE
# MOTIF EST LÀ. Le juge condamne au hasard, et son motif est démenti par la
# sortie qu'il imprime lui-même six lignes plus bas.
#
# MESURÉ, sur la sortie réelle de `ops/uninstall_check.sh --gestes` (7 458
# octets) et sur la condition exacte de l'étape 8 :
#     forme au tuyau      → 10 condamnations à tort sur 3 000, code 141
#     forme en chaîne ici →  0 condamnation  à tort sur 3 000
# Dix-sept conditions de cette forme vivaient dans ce fichier, dont une jouée
# cinq fois : de quoi condamner une exécution sur sept.
#
# Une chaîne ici ne crée AUCUN processus producteur — bash place le texte
# dans le descripteur avant d'exécuter `grep` — donc aucun SIGPIPE n'est
# possible, et le code rendu est celui de `grep` seul.
#
# `tests/test_le_juge_ne_tire_pas_au_sort.py` refuse mécaniquement le retour
# de cette forme dans les fichiers de ce dossier, et REJOUE le mécanisme.

_ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPOT_SOURCE="$(cd "$_ICI/../.." && pwd)"

# shellcheck source=tests/acceptance/garde_isolement.sh
source "$_ICI/garde_isolement.sh"

# ===========================================================================
# Options
# ===========================================================================

MODE_COMPLET=0
PORT_PG="${ACC_PORT_PG:-}"
PORT_API="${ACC_PORT_API:-}"
PORT_COCKPIT="${ACC_PORT_COCKPIT:-}"
JOURNAL=""
CLE_EMBEDDINGS="${ACC_CLE_EMBEDDINGS:-}"
#: L'adresse du fournisseur d'embeddings. Vide = le vrai, qui facture.
BASE_URL_EMBEDDINGS="${ACC_EMBEDDINGS_BASE_URL:-}"

#: Les planchers. Ce ne sont pas des valeurs par défaut : ce sont les points de
#: départ d'une RECHERCHE (voir `choisir_port`). Un numéro par défaut fixe est
#: exactement ce qui a fait qu'une unité d'essai s'est posée sur le 8000.
#:
#: ILS SE DÉDUISENT DES MINIMA DE LA GARDE, ILS NE LES RECOPIENT PAS.
#: `5461`, `8211` et `8231` étaient écrits en dur, à quelques lignes de
#: `GARDE_PG_PORT_MIN=5460` et `GARDE_SERVICE_PORT_MIN=8200` qui les rendent
#: acceptables — deux écritures d'une même contrainte. Le jour où la règle du
#: chantier relève ses planchers, la garde refuserait chacun des ports que
#: cette recherche propose, et le harnais ne démarrerait plus, sans que rien
#: n'indique pourquoi. Ici, le décalage est du RANGEMENT (PostgreSQL juste
#: au-dessus du minimum, l'API dix plus haut, le cockpit trente) ; le plancher,
#: lui, vient de la garde.
PLANCHER_PG=$(( GARDE_PG_PORT_MIN + 1 ))
PLANCHER_API=$(( GARDE_SERVICE_PORT_MIN + 11 ))
PLANCHER_COCKPIT=$(( GARDE_SERVICE_PORT_MIN + 31 ))

aide() {
    cat <<'AIDE'

  acceptance.sh — le critère d'acceptation du framework, rendu exécutable.

  Installe RÉELLEMENT un cerveau depuis un clone, sur un cluster PostgreSQL
  qui lui est propre, vérifie les neuf étapes — dont la DÉSINSTALLATION du
  §13, jouée à la lettre —, puis démonte tout, y compris en cas d'échec.

  USAGE
      sudo tests/acceptance/acceptance.sh [options]

  OPTIONS
      --complet           mode complet : la chaîne d'apprentissage est menée
                          jusqu'à l'atome porteur d'embedding, et jusqu'au
                          rappel. EXIGE --cle-embeddings, et DÉPENSE de
                          l'argent (quelques centimes).
      --cle-embeddings X  clé d'embeddings (ou ACC_CLE_EMBEDDINGS)
      --embeddings-base-url U
                          L'ADRESSE du fournisseur d'embeddings (ou
                          ACC_EMBEDDINGS_BASE_URL). Elle existe pour une
                          raison précise : le mode complet est le SEUL qui
                          dépense, donc le seul que personne ne rejoue —
                          et un mode qu'on ne rejoue pas pourrit. Il a
                          d'ailleurs POSTÉ pendant deux manches un corps que
                          l'API refusait en 422, sans que rien ne le voie.
                          Avec cette option, on double le FOURNISSEUR (un
                          serveur local qui rend un vecteur) sans jamais
                          doubler le produit : la vraie route écrit, le vrai
                          vecteur est stocké, le vrai rappel interroge — et
                          rien n'est facturé. Le rapport DIT alors que la
                          facturation, elle, n'a pas été prouvée.
      --port-pg N         port du cluster d'essai      (≥ 5460)
      --port-api N        port de l'API d'essai        (≥ 8200)
      --port-cockpit N    port du cockpit d'essai      (≥ 8200)
                          Sans ces options, le premier port LIBRE au-dessus
                          des planchers est choisi et annoncé. Un port donné
                          explicitement n'est jamais déplacé.
      --journal FICHIER   où écrire le journal complet
      -h, --help          cette aide

  MODE GRATUIT (défaut)
      Aucune clé, aucune dépense. La chaîne d'apprentissage est vérifiée
      jusqu'où elle peut l'être sans payer, et le rapport DIT ce qu'il n'a
      pas pu prouver. L'étape 6 rend alors « PARTIEL », jamais « PROUVÉ ».

  CE QUE MÊME LE MODE COMPLET NE COUVRE PAS
      La CURATION. Le cycle n'appelle pas une API de curation : il lance le
      binaire `claude` en sous-processus (agents/lib/claude_cli.py). Il n'y a
      donc pas de clé à fournir, mais une AUTHENTIFICATION de ce binaire sous
      le compte d'agent — session d'abonnement, ou ANTHROPIC_API_KEY que
      c'est LUI qui lit. Armer la dépense sur une machine où ce binaire est
      présent ferait dépenser sans qu'on l'ait demandé : ce harnais ne l'arme
      JAMAIS. Il constate que le frein tient, et nomme la curation comme non
      testée.
      Ce que l'installation, elle, vérifie désormais AVANT de se déclarer
      réussie : que ce binaire existe, qu'il est exécutable par le compte
      d'agent, qu'il a de quoi s'authentifier, et que les deux interrupteurs
      de dépense sont nommés avec leur geste (§7 de verify_install.sh). Le
      prérequis n'est plus une découverte de troisième jour.

  CE QU'IL FAUT AVOIR
      root, systemd, PostgreSQL avec pgvector, un accès réseau pour pip.

  CE QUE CE SCRIPT NE TOUCHE JAMAIS
      Le cluster PostgreSQL par défaut (5432), les ports 8000 et 8100, les
      unités systemd sans son marqueur, /var/log/arac, /var/backups/arac,
      les comptes « arac » et « aracagent ». Les gardes refusent de démarrer
      plutôt que de s'en approcher.

AIDE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --complet)         MODE_COMPLET=1 ;;
        --cle-embeddings)  CLE_EMBEDDINGS="${2:-}"; shift ;;
        --embeddings-base-url) BASE_URL_EMBEDDINGS="${2:-}"; shift ;;
        --port-pg)         PORT_PG="${2:-}"; shift ;;
        --port-api)        PORT_API="${2:-}"; shift ;;
        --port-cockpit)    PORT_COCKPIT="${2:-}"; shift ;;
        --journal)         JOURNAL="${2:-}"; shift ;;
        -h|--help)         aide; exit 0 ;;
        *) printf 'Option inconnue : %s\n' "$1" >&2; aide >&2; exit 2 ;;
    esac
    shift
done

# ===========================================================================
# L'identité de CETTE exécution
# ===========================================================================
#
# Un identifiant court, dérivé de l'horloge et du PID. Il entre dans le nom du
# cluster, du cerveau, des comptes et des dossiers : deux exécutions
# simultanées ne se marchent pas dessus, et une exécution abandonnée ne
# bloque pas la suivante.

RUN="$(printf '%s%s' "$(date +%s%N)" "$$" | sha256sum | cut -c1-6)"

# --- LE CHOIX DES PORTS -----------------------------------------------------
#
# Un numéro de port appartient à la MACHINE, jamais à un essai. Un serveur qui
# a déjà porté un cerveau, ou les restes d'un essai abandonné, tient des ports
# qu'aucune valeur par défaut ne peut prévoir — et un harnais qui échoue là
# demande une intervention humaine, ce que son propre critère interdit.
#
# On CHERCHE donc, au lieu de supposer. Chaque candidat passe la garde AVANT
# d'être considéré : la recherche ne peut pas dériver vers un port de
# production, puisqu'un port de production ne passe jamais la garde. Et le
# numéro retenu est ANNONCÉ — un port choisi en silence est un port qu'on ne
# saura pas retrouver dans un journal.
#
# Un numéro donné explicitement (--port-api, ACC_PORT_API) n'est PAS déplacé :
# quand quelqu'un désigne un port, il a une raison, et la lui changer dans son
# dos serait pire que de refuser.
#: LES PORTS QUE `ss` NE PEUT PAS VOIR — la moitié aveugle de « ce port est libre ».
#: `ss` ne montre que ce qui ÉCOUTE. Un cluster PostgreSQL déclaré sur un port
#: mais ARRÊTÉ n'y apparaît pas : le harnais le croit libre, y pose le sien, et
#: c'est le voisin qui ne redémarrera plus. Mesuré : `pg_createcluster 16 X
#: --port 5497` accepte sans broncher un port déjà déclaré par un autre
#: cluster ; c'est au `--start` que la collision tombe, code 25, en laissant
#: une grappe à moitié créée. On lit donc la déclaration, pas seulement la
#: socket.
ports_pg_declares() {
    command -v pg_lsclusters >/dev/null 2>&1 || return 0
    pg_lsclusters -h 2>/dev/null | awk '{print $3}'
}

#: Quel cluster déclare CE port ? (vide = aucun)
ports_pg_declares_sur() { # port
    command -v pg_lsclusters >/dev/null 2>&1 || return 0
    pg_lsclusters -h 2>/dev/null | awk -v p="$1" '$3==p {print $1"/"$2}'
}

choisir_port() { # valeur_explicite plancher role garde [ports_interdits...]
    local explicite="$1" plancher="$2" role="$3" garde="$4"; shift 4
    if [[ -n "$explicite" ]]; then printf '%s' "$explicite"; return 0; fi
    local p x pris
    for (( p = plancher; p < plancher + 20; p++ )); do
        "$garde" "$p" "$role" >/dev/null 2>&1 || continue
        garde_port_libre "$p" "$role" >/dev/null 2>&1 || continue
        pris=0
        for x in "$@"; do [[ "$x" == "$p" ]] && { pris=1; break; }; done
        (( pris )) && continue
        printf '%s' "$p"; return 0
    done
    # Aucun port libre dans la fenêtre : on rend le plancher. Les gardes, plus
    # bas, refuseront et DIRONT qui le tient. Rendre une valeur bidon ici
    # ferait échouer le test sur un message inutile.
    printf '%s' "$plancher"
}

PORT_PG="$(choisir_port "$PORT_PG" "$PLANCHER_PG" "PostgreSQL" garde_port_pg $(ports_pg_declares))"
PORT_API="$(choisir_port "$PORT_API" "$PLANCHER_API" "l'API" garde_port_service)"
PORT_COCKPIT="$(choisir_port "$PORT_COCKPIT" "$PLANCHER_COCKPIT" "le cockpit" garde_port_service)"
#: LE DOUBLE D'EMBEDDINGS. Il ne double PAS le produit — il double le
#: FOURNISSEUR PAYANT, et c'est toute la différence : le code d'ARAC s'exécute
#: entier, `POST /v1/atoms` compris, seul l'appel sortant vers OpenAI est
#: remplacé par une réponse déterministe en boucle locale. Cf.
#: `_etape_6_route_reelle_sans_depense`.
PORT_DOUBLE_EMB="$(choisir_port "" "$PLANCHER_COCKPIT" "le double d'embeddings" garde_port_service "$PORT_API" "$PORT_COCKPIT")"
DOUBLE_EMB_PID=""
#: Le domaine réellement employé par l'atome témoin de l'étape 6. Le §13.10 le
#: cherche dans le journal : un domaine EST de la mémoire (cf. app/journal.py).
FEUILLE_TEMOIN=""

CERVEAU="acceptation-$RUN"          # ce que l'entretien recevra comme réponse
PROPRIETAIRE="Alex"                 # prénom fictif, générique et assumé
POSTE="acceptation-poste-$RUN"      # le node_id déclaré
CLUSTER="acceptation$RUN"           # le cluster PostgreSQL, à nous

# Ces trois valeurs sont DÉDUITES par le bootstrap. On les recalcule ici
# à l'identique — c'est la seule façon de les faire passer sous les gardes
# AVANT que quoi que ce soit n'existe. Si le bootstrap changeait sa règle de
# dérivation, l'étape 4 s'en apercevrait (elle les confronte au réel).
ARAC_DB="$(printf '%s' "$CERVEAU" | tr -c 'a-zA-Z0-9' '_' | sed 's/_*$//')"
PREFIXE_UNITE="arac-$ARAC_DB"
ARAC_ETC="/etc/arac/$ARAC_DB"

# ---------------------------------------------------------------------------
# À QUI EST CETTE SOCKET ? — la question que le démontage ne posait pas
# ---------------------------------------------------------------------------
#
# Rend « nous », « tiers » ou « inconnu » pour un PID. Trois chemins, et le
# premier qui répond tranche. Aucun n'énumère : chacun DÉRIVE l'appartenance de
# l'identité de cette exécution.
#
#   1. le cgroup nomme une unité de CE cerveau ($PREFIXE_UNITE) ;
#   2. l'environnement du processus porte ARAC_DB=$ARAC_DB — c'est ce que
#      systemd y pose, et un imposteur ne peut pas le servir, seulement le
#      PORTER, auquel cas c'est bien lui qu'on identifie ;
#   3. le processus descend du harnais lui-même (chaîne des PPID jusqu'à $$).
#
# FAIL-CLOSED : ne pas pouvoir lire /proc ne vaut pas « c'est un tiers ». On
# rend « inconnu », et l'appelant le dit sans conclure. Ne pas savoir n'est ni
# une accusation ni une absolution.
proprietaire_du_port() { # pid
    local pid="${1-}" ligne vu ancetre garde=0
    [[ -n "$pid" && "$pid" =~ ^[0-9]+$ ]] || { printf 'inconnu'; return; }
    [[ -d "/proc/$pid" ]] || { printf 'inconnu'; return; }

    if [[ -r "/proc/$pid/cgroup" ]]; then
        if grep -q -- "$PREFIXE_UNITE" "/proc/$pid/cgroup" 2>/dev/null; then
            printf 'nous'; return
        fi
        garde=1
    fi
    if [[ -r "/proc/$pid/environ" ]]; then
        vu="$(tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null \
              | sed -n 's/^ARAC_DB=//p' | head -1)"
        [[ "$vu" == "$ARAC_DB" ]] && { printf 'nous'; return; }
        garde=1
    fi

    # Descendance : on remonte les PPID jusqu'à init, en bornant la remontée.
    ancetre="$pid"
    while [[ "$ancetre" != "1" && "$ancetre" != "0" && -r "/proc/$ancetre/stat" ]]; do
        [[ "$ancetre" == "$$" ]] && { printf 'nous'; return; }
        ancetre="$(awk '{print $4}' "/proc/$ancetre/stat" 2>/dev/null)"
        [[ -n "$ancetre" ]] || break
        garde=$((garde + 1))
        (( garde > 64 )) && break
    done

    (( garde )) && { printf 'tiers'; return; }
    printf 'inconnu'
}

U_SERVICE="aracacceptation$RUN"     # compte des services (API, cockpit)
U_AGENT="agentacceptation$RUN"      # compte des cycles

BASE_TRAVAIL="/var/lib/arac-acceptation/$RUN"
ARAC_HOME="$BASE_TRAVAIL/depot"
FAUX_MAC="$BASE_TRAVAIL/mac"
ARAC_LOG_DIR="/var/log/arac-acceptation/$RUN"
ARAC_BACKUP_DIR="/var/backups/arac-acceptation/$RUN"
# Déduits par le bootstrap depuis $ARAC_DB — donc marqués sans qu'on s'en mêle.
ARAC_AGENT_HOME="/var/lib/arac/$ARAC_DB"
ARAC_STATE_SERVICE="/var/lib/arac/$ARAC_DB-service"   # posé par StateDirectory=

ARAC_ENV_FILE="$ARAC_ETC/arac.env"
ARAC_SECRETS_COCKPIT="$ARAC_ETC/cockpit.env"
ARAC_VENV="$ARAC_HOME/.venv"
ARAC_ETAT="$BASE_TRAVAIL/avancement.state"

JOURNAL="${JOURNAL:-/var/tmp/acceptation-$RUN.log}"

URL_API="http://127.0.0.1:$PORT_API"
URL_COCKPIT="http://127.0.0.1:$PORT_COCKPIT"

# ===========================================================================
# La voix
# ===========================================================================

_couleur() { [[ -t 1 && -z "${NO_COLOR:-}" ]]; }
_c() { if _couleur; then printf '\033[%sm%s\033[0m' "$1" "$2"; else printf '%s' "$2"; fi; }
_trait() { local i; for (( i=0; i<${1:-1}; i++ )); do printf '─'; done; }

dire()  { printf '  %s\n' "${1-}"; }
info()  { printf '  %s %s\n' "$(_c 2 '·')" "${1-}"; }
ok()    { printf '  %s %s\n' "$(_c 32 '✓')" "${1-}"; }
ko()    { printf '  %s %s\n' "$(_c 31 '✗')" "${1-}"; }
attn()  { printf '  %s %s\n' "$(_c 33 '⚠')" "${1-}"; }
vide()  { printf '\n'; }
titre() { vide; printf '  %s\n  %s\n' "$(_c 1 "${1-}")" "$(_c 2 "$(_trait "${#1}")")"; }

# ===========================================================================
# Le registre des verdicts
# ===========================================================================

declare -a E_TITRE=() E_VERDICT=() E_PREUVE=() E_DUREE=()
declare -a NON_TESTES=()
declare -a INTERVENTIONS=()

V_CODE=""; V_PREUVE=""

#: 1 dès que l'installation a réellement abouti. Les étapes 4 à 7 n'ont
#: aucun sens avant : les juger « en ÉCHEC » alors qu'elles n'ont jamais été
#: exercées transformerait UNE panne en cinq, noierait la cause réelle sous
#: ses conséquences, et ferait perdre une minute à interroger un cockpit qui
#: n'a jamais été installé. Une étape non exercée est NON TESTÉE.
CERVEAU_INSTALLE=0

verdict()   { V_CODE="$1"; V_PREUVE="$2"; }
nonteste()  { NON_TESTES+=("$1"); }

#: Rend 0 (et pose le verdict) quand il n'y a rien à exercer.
exige_installation() { # nom_de_l_etape
    (( CERVEAU_INSTALLE )) && return 1
    info "l'installation n'a pas abouti : il n'y a aucun cerveau à interroger."
    nonteste "$1 — l'étape 3 n'a pas abouti, cette étape n'a jamais été exercée"
    verdict "NON_TESTÉ" "non exercée : l'installation n'a pas abouti (voir l'étape 3)"
    return 0
}

#: Un geste que le bootstrap aurait dû poser lui-même. Un seul suffit à ce
#: que le framework ne soit pas prêt : l'utilisateur n'aura pas ce script.
intervention() { # ce_qu_on_a_du_faire pourquoi remede_documente
    INTERVENTIONS+=("$1|$2|$3")
    vide
    attn "$(_c 1 "INTERVENTION MANUELLE — le critère « sans intervention » est violé ici.")"
    dire "     ce qu'il a fallu faire : $1"
    dire "     pourquoi               : $2"
    dire "     documenté dans         : $3"
    vide
}

_symbole_verdict() {
    case "$1" in
        PROUVÉ)     _c 32 '✓ PROUVÉ' ;;
        PARTIEL)    _c 33 '◐ PARTIEL' ;;
        NON_TESTÉ)  _c 2  '· NON TESTÉ' ;;
        *)          _c 31 '✗ ÉCHEC' ;;
    esac
}

#: LE PROGRAMME — la seule source du nombre d'étapes.
#:
#: L'en-tête écrivait « ÉTAPE 8 / 7 » : le dénominateur était une constante
#: tapée à la main, trois lignes au-dessus d'un commentaire qui parlait déjà de
#: huit. Un rapport dont tout le métier est de mesurer ne publie pas un nombre
#: qu'il n'a pas compté.
declare -a PROGRAMME=(
    "Cloner le dépôt|etape_1_cloner"
    "Suivre la documentation|etape_2_documentation"
    "Installer ARAC|etape_3_installer"
    "Créer son cerveau|etape_4_son_cerveau"
    "Synchroniser ses conversations|etape_5_synchroniser"
    "Voir son cerveau apprendre|etape_6_apprendre"
    "Utiliser son cockpit|etape_7_cockpit"
    "Prouver sa sauvegarde|etape_8_prouver_sa_sauvegarde"
    "Désinstaller|etape_9_desinstaller"
)
TOTAL_ETAPES=${#PROGRAMME[@]}

etape() { # numero titre fonction
    local numero="$1" titre_e="$2" fonction="$3"
    titre "ÉTAPE $numero / $TOTAL_ETAPES — $titre_e"
    V_CODE="ÉCHEC"; V_PREUVE="l'étape n'a rendu aucun verdict"
    local debut fin non_testes_avant=${#NON_TESTES[@]}
    debut="$(date +%s)"
    "$fonction"
    fin="$(date +%s)"

    # UNE PARTIELLE QUI NE NOMME RIEN EST UNE VERTE DÉGUISÉE.
    #
    # « PARTIEL » ne vaut, dans ce fichier, qu'accompagné de ce qui n'a PAS pu
    # être prouvé — c'est écrit en tête, et c'est toute la différence entre un
    # rapport honnête et un rapport arrangeant. On ne se contente pas de
    # l'écrire : on le fait tenir mécaniquement. Une étape qui rend PARTIEL
    # sans avoir inscrit une seule ligne au registre « CE QUI N'A PAS ÉTÉ
    # TESTÉ » est requalifiée en ÉCHEC, et la raison est dite.
    if [[ "$V_CODE" == "PARTIEL" ]] && (( ${#NON_TESTES[@]} == non_testes_avant )); then
        V_CODE="ÉCHEC"
        V_PREUVE="verdict PARTIEL sans rien nommer au registre « ce qui n'a pas été testé » — une partielle qui ne dit pas ce qu'elle n'a pas prouvé est une verte déguisée. Preuve d'origine : $V_PREUVE"
    fi
    E_TITRE+=("$titre_e")
    E_VERDICT+=("$V_CODE")
    E_PREUVE+=("$V_PREUVE")
    E_DUREE+=("$((fin - debut))")
    vide
    printf '  %s  %s\n' "$(_symbole_verdict "$V_CODE")" "$V_PREUVE"
}

# ===========================================================================
# Outils
# ===========================================================================

psql_super() { sudo -u postgres psql -v ON_ERROR_STOP=1 -p "$PORT_PG" "$@"; }
sql()        { psql_super -d "$ARAC_DB" -tAc "$1" 2>/dev/null; }
#: Lecture SEULE sur le cluster de production. Aucun appel de ce script ne
#: doit jamais y écrire : le seul usage légitime est de constater que rien n'a
#: bougé. La base est un ARGUMENT, jamais une valeur par défaut — voir la note
#: dans `preuve_production`.
sql_prod()   { sudo -u postgres psql -v ON_ERROR_STOP=1 -p 5432 -d "$1" -tAc "$2" 2>/dev/null; }

#: Lit une variable d'un fichier d'environnement, sans la faire passer par
#: l'espace des processus : `ps` est lisible par tout le monde.
lire_env() { # fichier cle
    [[ -r "$1" ]] || return 1
    python3 - "$1" "$2" <<'PY' 2>/dev/null || return 1
import pathlib, sys
for l in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if not l.lstrip().startswith("#") and "=" in l and l.split("=", 1)[0].strip() == sys.argv[2]:
        print(l.split("=", 1)[1]); break
else:
    raise SystemExit(1)
PY
}

#: Attend qu'une URL réponde, ou renonce. Rend le code HTTP, ou 000.
attendre_http() { # url secondes
    local url="$1" reste="${2:-30}" code
    while (( reste > 0 )); do
        code="$(curl -s -o /dev/null -m 3 -w '%{http_code}' "$url" 2>/dev/null)"
        [[ "$code" != "000" ]] && { printf '%s' "$code"; return 0; }
        sleep 1; reste=$((reste - 1))
    done
    printf '000'
}

#: ATTEND QU'UN PORT SE TAISE. Un `sleep` fixe n'est pas une attente : c'est
#: un pari sur la vitesse de la machine, et il se perd sous charge. Rend 0 dès
#: que plus personne n'écoute, 1 si l'on a renoncé.
attendre_port_libre() { # port secondes
    local p="$1" reste="${2:-20}" l
    while (( reste > 0 )); do
        l="$(ss -ltnH "sport = :$p" 2>/dev/null)"
        [[ -z "${l//[[:space:]]/}" ]] && return 0
        sleep 1; reste=$((reste - 1))
    done
    return 1
}

#: Les PID que systemd attribue à une unité — principal ET cgroup.
#: Même mécanique que `bootstrap/lib/core.sh` : un serveur n'écoute pas
#: toujours depuis son PID principal.
pids_unite() { # unite
    local principal cg
    principal="$(systemctl show -p MainPID --value "$1" 2>/dev/null || true)"
    [[ -n "$principal" && "$principal" != 0 ]] && printf '%s\n' "$principal"
    cg="/sys/fs/cgroup/system.slice/$1/cgroup.procs"
    [[ -r "$cg" ]] && cat "$cg" 2>/dev/null
    return 0
}

#: LA SOCKET DE CE PORT APPARTIENT-ELLE À CETTE UNITÉ ?
#: 0 oui · 1 non, quelqu'un d'autre la tient · 2 on n'a pas pu savoir.
#: Le troisième code n'est pas une commodité : sans lui, « je n'ai pas vu de
#: PID » deviendrait « ce n'est pas le nôtre ».
socket_de_l_unite() { # port unite
    local ligne; ligne="$(ss -ltnHp "sport = :$1" 2>/dev/null)"; ligne="${ligne%%$'\n'*}"
    [[ -z "$ligne" ]] && return 1
    local -a du_socket=() de_lunite=()
    mapfile -t du_socket < <(grep -oE 'pid=[0-9]+' <<<"$ligne" | cut -d= -f2)
    (( ${#du_socket[@]} )) || return 2
    mapfile -t de_lunite < <(pids_unite "$2")
    (( ${#de_lunite[@]} )) || return 2
    local a b
    for a in "${du_socket[@]}"; do
        for b in "${de_lunite[@]}"; do
            [[ -n "$a" && "$a" == "$b" ]] && return 0
        done
    done
    return 1
}

# ===========================================================================
# LA PRODUCTION EST-ELLE INTACTE ? — mesuré avant, mesuré après
# ===========================================================================
#
# Quatre contrôles. Les trois premiers sont ceux que tout le monde connaît ;
# le quatrième est le seul qui aurait attrapé l'incident d'origine.
#
# Un `ALTER ROLE … PASSWORD` sur un rôle de production ne casse RIEN de
# visible : les services déjà connectés gardent leur connexion, l'API répond,
# le cockpit répond, les souvenirs sont là. La panne n'apparaît qu'au
# redémarrage suivant, des heures plus tard, sans rapport apparent avec ce
# qu'on avait fait. Les trois premiers contrôles auraient donc tous été VERTS
# le jour de l'incident.
#
# `pg_authid.rolpassword` porte l'empreinte SCRAM du mot de passe. On n'en lit
# pas la valeur : on en prend un condensat, et on compare avant/après. C'est
# suffisant pour affirmer « personne n'y a touché », et cela ne fait sortir
# aucun secret du serveur.

EMPREINTE_ROLES_AVANT=""

empreinte_roles_production() {
    sudo -u postgres psql -p 5432 -d postgres -tAc \
        "SELECT rolname || ':' || coalesce(rolpassword, '-') FROM pg_authid ORDER BY rolname" \
        2>/dev/null | sha256sum | cut -c1-16
}

preuve_production() { # moment
    local moment="$1" souci=0 valeur
    titre "La production est-elle intacte ? ($moment)"

    valeur="$(systemctl is-active arac-api.service arac-control-center.service 2>&1 | tr '\n' ' ')"
    if [[ "$valeur" == "active active "* ]]; then
        ok "services de production      $valeur"
    else
        ko "services de production      $valeur (attendu : active active)"; souci=1
    fi

    valeur="$(curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:8000/healthz 2>/dev/null)"
    if [[ "$valeur" == "200" ]]; then
        ok "sonde de l'API (8000)       $valeur"
    else
        ko "sonde de l'API (8000)       $valeur (attendu : 200)"; souci=1
    fi

    # `-d arac` n'est pas décoratif : sans lui, psql se connecte à la base
    # `postgres` — où `arac.memory_atoms` n'existe pas. La requête rendait
    # alors une chaîne vide, lue comme « production illisible », et ce test
    # refusait de démarrer sur une machine parfaitement saine. Un contrôle
    # qui crie au loup est un contrôle qu'on finit par désarmer.
    valeur="$(sql_prod arac "SELECT count(*) FROM arac.memory_atoms")"
    if [[ -n "$valeur" ]] && (( valeur >= 1914 )); then
        ok "souvenirs en production     $valeur"
    else
        ko "souvenirs en production     ${valeur:-illisible} (attendu : ≥ 1914)"; souci=1
    fi

    valeur="$(empreinte_roles_production)"
    if [[ "$moment" == "avant" ]]; then
        EMPREINTE_ROLES_AVANT="$valeur"
        ok "empreinte des rôles (5432)  $valeur — référence"
        info "  C'est ce contrôle, et lui seul, qui aurait vu l'incident :"
        info "  un ALTER ROLE … PASSWORD ne casse rien de visible avant le"
        info "  redémarrage suivant des services de la victime."
    elif [[ "$valeur" == "$EMPREINTE_ROLES_AVANT" ]]; then
        ok "empreinte des rôles (5432)  $valeur — inchangée"
    else
        ko "empreinte des rôles (5432)  $valeur ≠ $EMPREINTE_ROLES_AVANT"
        ko "  DES RÔLES DE PRODUCTION ONT ÉTÉ MODIFIÉS. C'est l'incident."
        souci=1
    fi

    return "$souci"
}

# ===========================================================================
# LES GARDES — avant toute écriture, avant tout démarrage
# ===========================================================================

gardes() {
    titre "Gardes d'isolement"

    local refus=0

    if [[ $EUID -ne 0 ]]; then
        ko "root est nécessaire : créer un cluster, des rôles, des unités."
        return 1
    fi

    local sortie
    sortie="$(garde_isolement_valeurs \
        "$PORT_PG" "$PORT_API" "$PORT_COCKPIT" \
        "$CERVEAU" "$CLUSTER" "$PREFIXE_UNITE" \
        "$U_SERVICE" "$U_AGENT" \
        "$ARAC_HOME" "$ARAC_ETC" "$ARAC_LOG_DIR" "$ARAC_BACKUP_DIR" \
        "$ARAC_AGENT_HOME" "$ARAC_STATE_SERVICE" "$BASE_TRAVAIL" "$FAUX_MAC" 2>&1)" || refus=1
    [[ -n "$sortie" ]] && printf '%s\n' "$sortie" | while IFS= read -r l; do ko "$l"; done

    sortie="$(garde_port_libre "$PORT_API" "l'API" 2>&1)"     || { refus=1; ko "$sortie"; }
    sortie="$(garde_port_libre "$PORT_COCKPIT" "le cockpit" 2>&1)" || { refus=1; ko "$sortie"; }
    sortie="$(garde_port_libre "$PORT_PG" "PostgreSQL" 2>&1)" || { refus=1; ko "$sortie"; }
    sortie="$(garde_cluster_absent "$PG_MAJEURE" "$CLUSTER" 2>&1)" || { refus=1; ko "$sortie"; }

    # LES UNITÉS SONT LUES DANS LE BOOTSTRAP QUI LES POSE, PAS RECOPIÉES ICI.
    # Cette liste-ci en tenait QUATRE là où le bootstrap en pose CINQ : la
    # garde d'avant-vol acceptait donc de démarrer avec une unité de
    # RESTAURATION homonyme déjà en place. C'est la même maladie que la liste
    # du §13, au même dépôt, sur une autre liste.
    local u
    local -a u_suffixes=()
    while IFS= read -r u; do [[ -n "$u" ]] && u_suffixes+=("$u"); done < <(suffixes_d_unite)
    if (( ${#u_suffixes[@]} == 0 )); then
        refus=1
        ko "le juge ne sait plus lire les noms d'unité dans bootstrap/lib/config.sh — il refuse d'en tenir une copie"
    fi
    for u in "${u_suffixes[@]}"; do
        sortie="$(garde_unite_absente "$PREFIXE_UNITE-$u.service" 2>&1)" || { refus=1; ko "$sortie"; }
    done

    if (( refus )); then
        vide
        ko "$(_c 1 'Rien n'\''a été créé. Ces valeurs pourraient toucher une installation vivante.')"
        return 1
    fi

    ok "ports         PostgreSQL $PORT_PG · API $PORT_API · cockpit $PORT_COCKPIT — libres et hors production"
    ok "cluster       $PG_MAJEURE/$CLUSTER — absent, donc à nous"
    ok "unités        $PREFIXE_UNITE-{$(IFS=,; printf '%s' "${u_suffixes[*]}")} — les ${#u_suffixes[@]} que le bootstrap pose, LUES chez lui, absentes"
    ok "comptes       $U_SERVICE · $U_AGENT — marqués, jamais « arac »"
    ok "dossiers      tous marqués « acceptation », aucun chemin de production"
    return 0
}

# ===========================================================================
# LA LISTE DU §13, LUE DANS LA PAGE — JAMAIS RECOPIÉE ICI
# ===========================================================================
#
# TROIS MANCHES, TROIS DIVERGENCES, UNE SEULE CAUSE : DEUX LISTES.
#
# La liste des fichiers que le §13 fait effacer vivait à DEUX endroits — dans
# `docs/INSTALLATION.md` et, recopiée, dans ce fichier. Elle a divergé trois
# fois :
#
#   0.1.9   le harnais sautait `config/brain.toml` et `config/scopes.toml`,
#           puis reprochait à la page de ne pas les nommer. On a corrigé LE
#           HARNAIS.
#   0.1.11  la page a ajouté `app/schemas/scope_generated.py` et
#           `db/seeds/scopes.sql`. On a corrigé LA PAGE.
#   0.1.12  le harnais, resté à quatre chemins, rejouait la seconde passe,
#           la trouvait nécessaire, et imprimait à CHAQUE passage : « la
#           liste ordonnée du §13, elle, ne les mentionne pas » — une phrase
#           devenue fausse, adressée à une page qui avait raison.
#
# Chaque fois, on a corrigé la COPIE qui avait tort. Aucune fois, on n'a
# supprimé la copie. Un ⚠ qu'un juge imprime à tous les coups devient du
# décor, et c'est exactement ce que ce dépôt combat ailleurs sous le nom de
# « section d'honnêteté périmée » — appliqué cette fois à son propre juge.
#
# LA FORME QUI FERME LA CLASSE ENTIÈRE EST DÉJÀ CONNUE DU DÉPÔT : ne pas
# recopier ce qu'on surveille, ALLER LE LIRE. Le garde du journal lit les
# `ExecStart=` des unités plutôt que d'en tenir la liste ; le contrôle de
# départ lit l'empreinte dans le dump plutôt que de la déduire d'un nom ; le
# garde ELF lit la table des symboles. Ici : le juge LIT le §13.
#
# CE QU'IL LIT, ET CE QU'IL NE LIT PAS.
#   · `rm -f` seulement. Les `rm -rf` du §13 visent des RÉPERTOIRES dont ce
#     harnais déplace délibérément trois (`ARAC_LOG_DIR`, `ARAC_BACKUP_DIR`,
#     `BASE_TRAVAIL`) hors des chemins de production : les rejouer
#     littéralement ne viserait rien. Ils sont détruits par leurs variables,
#     juste au-dessus, et le contrôle de l'étape 9 les recompte.
#   · hors commentaire. La page écrit `# sudo rm -rf … && rm -f "$ADIEU"`
#     comme BRANCHE (b) commentée : un commentaire n'est pas un geste.
#   · `$BASE` et `${BASE}` prennent la valeur du cerveau ; tout jeton qui
#     porte encore un `$` après cette substitution est une variable que ce
#     harnais ne sait pas résoudre, et il ne l'invente pas — il la NOMME.
#   · un chemin relatif est relatif AU CLONE, comme dans la page (l'utilisateur
#     y est `cd` depuis le §2).
#
# SI LA LECTURE NE REND RIEN, C'EST UN ÉCHEC, PAS UN SILENCE. Une dérivation
# qui rend zéro chemin sans le dire serait pire qu'une copie : elle
# prétendrait suivre la page tout en ne jouant plus rien. Les appelants
# refusent une liste vide.

#: LA page, c'est celle que l'utilisateur a sous les yeux : celle du CLONE.
#: Le dépôt source ne sert que tant que le clone n'existe pas encore — et si
#: les deux divergeaient, c'est le clone qui a raison, puisque c'est lui qu'on
#: installe et lui qu'on désinstalle.
page_installation() {
    [[ -r "$ARAC_HOME/docs/INSTALLATION.md" ]] \
        && { printf '%s\n' "$ARAC_HOME/docs/INSTALLATION.md"; return 0; }
    printf '%s\n' "$DEPOT_SOURCE/docs/INSTALLATION.md"
}

#: Les cibles des `rm -f` du §13, une par ligne, dans l'ordre de la page.
#: Sans effet de bord : ne lit que le fichier, n'efface rien.
chemins_rm_du_13() {
    local page; page="$(page_installation)"
    [[ -r "$page" ]] || return 1
    local ligne dans=0 t
    local -a mots
    while IFS= read -r ligne || [[ -n "$ligne" ]]; do
        if (( ! dans )); then
            [[ "$ligne" == '## 13. '* ]] && dans=1
            continue
        fi
        [[ "$ligne" == '## '* ]] && break
        [[ "$ligne" =~ ^[[:space:]]*# ]] && continue
        ligne="${ligne#"${ligne%%[![:space:]]*}"}"
        ligne="${ligne#sudo }"
        [[ "$ligne" == 'rm -f '* ]] || continue
        ligne="${ligne#rm -f }"
        ligne="${ligne%%#*}"
        # `read -ra` découpe sur IFS SANS développer les jokers : le
        # développement, quand il a lieu, se fait plus bas et sous garde.
        mots=(); read -ra mots <<< "$ligne"
        for t in "${mots[@]}"; do
            t="${t%\"}"; t="${t#\"}"; t="${t%\'}"; t="${t#\'}"
            [[ -n "$t" ]] || continue
            t="${t//\$\{BASE\}/$ARAC_DB}"
            t="${t//\$BASE/$ARAC_DB}"
            [[ "$t" == *'$'* ]] && { printf '?%s\n' "$t"; continue; }
            [[ "$t" == /* ]] || t="$ARAC_HOME/$t"
            printf '%s\n' "$t"
        done
    done < "$page"
    return 0
}

#: LES UNITÉS QUE LE §13 FAIT DÉSARMER, LUES DANS LA PAGE.
#: La page écrit sa commande sur trois lignes continuées ; on les recolle, on
#: prend ce qui suit `--now`, et on substitue `$BASE`. Le commentaire qui la
#: précède dit « LES CINQ, pas quatre » — précisément parce que la version
#: d'avant en oubliait une. Une liste qu'on recopie perd un jour son
#: cinquième élément ; une liste qu'on lit, non.
unites_a_desarmer_du_13() {
    local page; page="$(page_installation)"
    [[ -r "$page" ]] || return 1
    local ligne dans=0 accu="" t
    local -a mots
    while IFS= read -r ligne || [[ -n "$ligne" ]]; do
        if (( ! dans )); then
            [[ "$ligne" == '## 13. '* ]] && dans=1
            continue
        fi
        [[ "$ligne" == '## '* ]] && break
        [[ "$ligne" =~ ^[[:space:]]*# ]] && continue
        if [[ -z "$accu" && "$ligne" != *'systemctl disable'* ]]; then continue; fi
        accu+=" ${ligne%\\}"
        [[ "$ligne" == *\\ ]] || break
    done < "$page"
    [[ "$accu" == *' --now '* ]] || return 1
    mots=(); read -ra mots <<< "${accu#* --now }"
    for t in "${mots[@]}"; do
        t="${t%\"}"; t="${t#\"}"; t="${t%\'}"; t="${t#\'}"
        [[ -n "$t" ]] || continue
        t="${t//\$\{BASE\}/$ARAC_DB}"
        t="${t//\$BASE/$ARAC_DB}"
        [[ "$t" == *'$'* ]] && continue
        printf '%s\n' "$t"
    done
}

#: LES SUFFIXES DE RÔLE QUE LE §13 FAIT TOMBER, LUS DANS LA PAGE.
#: Distincts, VOLONTAIREMENT, de `suffixes_de_role` : celui-ci dit ce que le
#: produit CRÉE, celui-là ce que la page DÉTRUIT. Les confondre reviendrait à
#: rendre indétectable le seul défaut qui compte ici — une page qui a oublié
#: un rôle. En les lisant chacun à sa source, le harnais joue le §13 tel qu'il
#: est écrit et laisse le contrôle de l'étape 9 nommer ce qui survit.
suffixes_de_role_du_13() {
    local page; page="$(page_installation)"
    [[ -r "$page" ]] || return 1
    awk '
        !dans && /^## 13\. / { dans = 1; next }
        !dans                { next }
        /^## /               { exit }
        /^for f in .*; do$/  { l = $0; sub(/^for f in /, "", l); sub(/; do$/, "", l); garde = l; next }
        garde != "" && /DROP ROLE/ { print garde; exit }
    ' "$page" | tr ' ' '\n' | sed -e 's/[^a-z_]//g' -e '/^$/d'
}

#: LES CINQ SUFFIXES DE RÔLE, LUS DANS LE MODULE QUI LES CRÉE.
#: `db/alembic/roles.py` est la seule autorité du dépôt sur ce point — c'est
#: la migration qui les fabrique. Ce harnais en tenait DEUX copies (le contrôle
#: de l'étape 3 et le §13.5) ; il n'en tient plus. Le jour où un sixième rôle
#: apparaît, le juge le cherche et le détruit sans qu'une ligne d'ici ne bouge.
suffixes_de_role() {
    local src
    for src in "$ARAC_HOME/db/alembic/roles.py" "$DEPOT_SOURCE/db/alembic/roles.py"; do
        [[ -r "$src" ]] || continue
        sed -n 's/^SUFFIXES[[:space:]]*=[[:space:]]*(\(.*\))[[:space:]]*$/\1/p' "$src" \
            | tr ',' '\n' | sed -e 's/[^a-z_]//g' -e '/^$/d'
        return 0
    done
    return 1
}

#: LES SUFFIXES D'UNITÉ, LUS DANS LE BOOTSTRAP QUI LES POSE.
#: `bootstrap/lib/config.sh` écrit `U_API="${PREFIXE_UNITE}-api"` et ses
#: quatre sœurs : c'est là que les noms sont DÉCIDÉS. Trois endroits de ce
#: harnais en tenaient copie — la garde d'avant-vol, le démontage et le §13.1
#: — et la garde d'avant-vol en avait déjà perdu un (« restauration »), donc
#: acceptait de démarrer avec une unité de restauration homonyme en place.
suffixes_d_unite() {
    local src
    for src in "$ARAC_HOME/bootstrap/lib/config.sh" "$DEPOT_SOURCE/bootstrap/lib/config.sh"; do
        [[ -r "$src" ]] || continue
        sed -n 's/^[[:space:]]*U_[A-Z_]*="\${PREFIXE_UNITE}-\([a-z]*\)".*$/\1/p' "$src"
        return 0
    done
    return 1
}

#: Les seuls chemins du §13 qui vivent DANS LE CLONE — c'est-à-dire ce qu'un
#: dépôt fraîchement cloné ne doit surtout pas porter, et ce qu'un départ doit
#: reprendre. Rendus RELATIFS au clone, comme la page les écrit.
fichiers_du_clone_selon_le_13() {
    local c
    while IFS= read -r c; do
        [[ "$c" == '?'* ]] && continue
        [[ "$c" == "$ARAC_HOME/"* ]] || continue
        printf '%s\n' "${c#"$ARAC_HOME/"}"
    done < <(chemins_rm_du_13)
}

# ===========================================================================
# LE DÉMONTAGE — sous trap EXIT, y compris en cas d'échec
# ===========================================================================
#
# « Un essai qui survit à son agent est un essai qui casse la production de
# quelqu'un. » Ce démontage tourne donc quoi qu'il arrive : succès, échec,
# interruption au clavier, erreur non prévue.
#
# IL REVALIDE TOUT AVANT DE DÉTRUIRE. Ce n'est pas de la redondance : entre le
# démarrage et ici, il s'est écoulé une installation entière, et une variable
# a pu être réécrite par une étape. Une garde qui ne s'exécute qu'au début
# protège le début.

DEMONTAGE_FAIT=0
DEMONTAGE_RESTES=()

_detruire_dossier() { # chemin
    local c="$1"
    [[ -e "$c" ]] || return 0
    if ! garde_chemin_jetable "$c" "dossier à effacer" >/dev/null; then
        DEMONTAGE_RESTES+=("$c (REFUSÉ par la garde — laissé en place)")
        ko "démontage refusé sur $c"
        return 1
    fi
    rm -rf "$c" 2>/dev/null
    [[ -e "$c" ]] && DEMONTAGE_RESTES+=("$c (effacement incomplet)")
    return 0
}

demonter() {
    local code_sortie=$?
    (( DEMONTAGE_FAIT )) && return "$code_sortie"
    DEMONTAGE_FAIT=1

    titre "Démontage"

    # --- Les unités ------------------------------------------------------
    if garde_prefixe_unite "$PREFIXE_UNITE" >/dev/null && command -v systemctl >/dev/null 2>&1; then
        # LE DÉMONTAGE NE TIENT AUCUNE LISTE D'UNITÉS : IL REGARDE CE QUI EST
        # LÀ. Une liste recopiée ici aurait exactement le défaut du §13 —
        # elle vieillit sans prévenir, et ce qu'elle a perdu survit à un
        # démontage qui s'annonce complet. On prend donc la RÉUNION de deux
        # sources, aucune des deux écrite ici : les noms que le bootstrap
        # décide (`suffixes_d_unite`, lus chez lui) et les unités RÉELLEMENT
        # posées sous ce préfixe (lues chez systemd et sur le disque). Le
        # préfixe, lui, vient de passer `garde_prefixe_unite` : rien de ce qui
        # suit ne peut désigner l'unité d'un voisin.
        local u f n
        local -a a_demonter=()
        while IFS= read -r u; do
            [[ -n "$u" ]] || continue
            for f in service timer; do a_demonter+=("$PREFIXE_UNITE-$u.$f"); done
        done < <(suffixes_d_unite)
        while IFS= read -r n; do
            [[ -n "$n" ]] || continue
            a_demonter+=("$n")
        done < <( { systemctl list-unit-files --no-legend "$PREFIXE_UNITE-*" 2>/dev/null | awk '{print $1}'
                    for n in /etc/systemd/system/"$PREFIXE_UNITE"-*.service \
                             /etc/systemd/system/"$PREFIXE_UNITE"-*.timer; do
                        [[ -e "$n" ]] && basename "$n"
                    done; } | sort -u )
        for n in "${a_demonter[@]}"; do
            systemctl disable --now "$n" >/dev/null 2>&1
            systemctl reset-failed "$n" >/dev/null 2>&1
            rm -f "/etc/systemd/system/$n"
        done
        systemctl daemon-reload >/dev/null 2>&1
        # LES ESTAMPILLES DES MINUTEURS SURVIVENT À LEURS UNITÉS.
        #
        # systemd garde la date du dernier déclenchement d'un minuteur
        # persistant dans /var/lib/systemd/timers/stamp-<unité>.timer. Ni
        # `disable --now`, ni la suppression du fichier d'unité, ni
        # `daemon-reload`, ni `reset-failed` ne l'effacent. Un démontage qui
        # annonce « aucune unité » laissait donc derrière lui une date que la
        # PROCHAINE unité homonyme héritait : `ops/install_check.sh` lisait
        # « le minuteur a déjà sonné » sur une installation où il n'avait
        # jamais tiré, et rendait une panne, code 2. Mesuré : 175 estampilles
        # orphelines sur cette machine. Ce qu'on pose, on le retire — y compris
        # ce que systemd pose pour nous.
        rm -f "/var/lib/systemd/timers/stamp-$PREFIXE_UNITE-"*.timer 2>/dev/null
        ok "unités          $PREFIXE_UNITE-* désarmées, supprimées, estampilles de minuteur effacées"
    else
        ko "unités          préfixe refusé par la garde — RIEN n'a été désarmé"
        DEMONTAGE_RESTES+=("unités $PREFIXE_UNITE-*")
    fi

    # --- Le double d'embeddings ------------------------------------------
    # Ce que ce harnais pose, il le retire — y compris un processus de vingt
    # lignes qui n'écoute que la boucle locale.
    if [[ -n "${DOUBLE_EMB_PID:-}" ]] && kill -0 "$DOUBLE_EMB_PID" 2>/dev/null; then
        kill "$DOUBLE_EMB_PID" 2>/dev/null
        sleep 0.3
        kill -9 "$DOUBLE_EMB_PID" 2>/dev/null
        ok "double          le double d'embeddings ($PORT_DOUBLE_EMB) est arrêté"
    fi

    # --- Le cluster -------------------------------------------------------
    # AVANT les dossiers : il y écrit encore.
    if garde_nom_cluster "$CLUSTER" >/dev/null && command -v pg_dropcluster >/dev/null 2>&1; then
        if pg_lsclusters -h 2>/dev/null | awk -v v="$PG_MAJEURE" -v n="$CLUSTER" '$1==v && $2==n {t=1} END{exit !t}'; then
            pg_dropcluster --stop "$PG_MAJEURE" "$CLUSTER" >/dev/null 2>&1 \
                && ok "cluster         $PG_MAJEURE/$CLUSTER arrêté et détruit" \
                || { ko "cluster         $PG_MAJEURE/$CLUSTER n'a pas pu être détruit"
                     DEMONTAGE_RESTES+=("cluster $PG_MAJEURE/$CLUSTER"); }
        else
            info "cluster         $PG_MAJEURE/$CLUSTER — jamais créé"
        fi
    else
        ko "cluster         nom refusé par la garde — RIEN n'a été détruit"
        DEMONTAGE_RESTES+=("cluster $CLUSTER")
    fi

    # --- Les dossiers -----------------------------------------------------
    local d
    for d in "$BASE_TRAVAIL" "$ARAC_ETC" "$ARAC_LOG_DIR" "$ARAC_BACKUP_DIR" \
             "$ARAC_AGENT_HOME" "$ARAC_STATE_SERVICE"; do
        _detruire_dossier "$d"
    done
    # Les parents, seulement s'ils sont vides : d'autres exécutions peuvent
    # tourner en même temps, et `rmdir` refuse tout seul un dossier peuplé.
    rmdir /var/lib/arac-acceptation /var/log/arac-acceptation \
          /var/backups/arac-acceptation 2>/dev/null
    ok "dossiers        travail, secrets, journaux, sauvegardes, état effacés"

    # --- Les comptes système ---------------------------------------------
    local c
    for c in "$U_SERVICE" "$U_AGENT"; do
        if ! garde_nom_systeme "$c" "compte" >/dev/null; then
            ko "compte          $c refusé par la garde — NON supprimé"
            DEMONTAGE_RESTES+=("compte $c")
            continue
        fi
        id -u "$c" >/dev/null 2>&1 || continue
        userdel "$c" >/dev/null 2>&1 \
            && ok "compte          $c supprimé" \
            || { ko "compte          $c n'a pas pu être supprimé"
                 DEMONTAGE_RESTES+=("compte $c"); }
    done

    # --- LA PREUVE que le démontage a bien démonté ------------------------
    #
    # Un démontage qui ne se vérifie pas est une intention, pas un geste.
    #
    # MAIS UN PORT TENU NE PROUVE RIEN TANT QU'ON NE SAIT PAS QUI LE TIENT.
    # Ce contrôle-ci a déjà menti. Lors d'un passage où l'installation avait
    # échoué à l'étape 3 — donc où AUCUN service n'avait jamais été démarré,
    # donc où le harnais n'avait jamais lié 8211 ni 8231 — le démontage a
    # conclu « LA MACHINE N'EST PAS REVENUE À SON ÉTAT INITIAL », en s'imputant
    # deux ports qu'un tiers avait pris entre-temps. L'utilisateur part alors
    # chercher une fuite qui n'existe pas ; et le jour où le harnais en laissera
    # vraiment une, il aura appris à ne pas croire ce message.
    #
    # C'est la faute même que ce dépôt a érigée en doctrine ailleurs
    # (`bootstrap/checks/verify_install.sh` remonte socket → PID → cgroup →
    # environnement pour NOMMER le cerveau derrière une socket), et le harnais
    # d'acceptation ne s'en servait pas sur lui-même. On la lui applique.
    local restes=0 port
    for port in "$PORT_API" "$PORT_COCKPIT" "$PORT_PG"; do
        local ligne pid qui
        ligne="$(ss -ltnHp "sport = :$port" 2>/dev/null)"; ligne="${ligne%%$'\n'*}"
        [[ -n "$ligne" ]] || continue
        pid="$(sed -n 's/.*[^a-z]pid=\([0-9]\+\).*/\1/p;q' <<<"$ligne")"
        qui="$(proprietaire_du_port "$pid")"
        case "$qui" in
            nous)
                ko "le port $port est encore tenu par CETTE exécution (PID ${pid:-?})"
                restes=1; DEMONTAGE_RESTES+=("port $port")
                ;;
            tiers)
                dire "  · le port $port est tenu par un tiers (PID ${pid:-?}, \
$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | cut -c1-60)) — ce n'est PAS \
un reste de cette exécution."
                ;;
            *)
                ko "le port $port est tenu et je ne peux pas dire par qui \
(PID ${pid:-inconnu} : /proc illisible ?). Je ne conclus pas à votre place."
                restes=1; DEMONTAGE_RESTES+=("port $port — propriétaire inconnu")
                ;;
        esac
    done
    local unites_restantes
    unites_restantes="$(systemctl list-unit-files --no-legend 2>/dev/null)"
    if grep -q "^$PREFIXE_UNITE" <<<"$unites_restantes"; then
        ko "des unités $PREFIXE_UNITE-* subsistent"; restes=1
    fi
    if (( ${#DEMONTAGE_RESTES[@]} )); then
        vide
        ko "$(_c 1 'LA MACHINE N'\''EST PAS REVENUE À SON ÉTAT INITIAL :')"
        local r; for r in "${DEMONTAGE_RESTES[@]}"; do dire "     · $r"; done
        restes=1
    fi
    (( restes == 0 )) && ok "vérifié         ports libérés, aucune unité, aucun cluster, aucun compte"

    # --- Et la production, après tout cela ? ------------------------------
    preuve_production "après" || restes=1

    rapport

    # `exit` et non `return` : dans un piège EXIT, un `return` laisse le shell
    # sortir avec le code qu'il avait DÉJÀ — un démontage incomplet passerait
    # donc inaperçu, ce qui est exactement la classe de silence qu'on combat.
    (( restes )) && exit 1
    exit "$code_sortie"
}

# ===========================================================================
# ÉTAPE 1 — cloner le dépôt
# ===========================================================================

MODE_CLONE=""

etape_1_cloner() {
    mkdir -p "$BASE_TRAVAIL"

    if git -C "$DEPOT_SOURCE" rev-parse --verify HEAD >/dev/null 2>&1; then
        if git clone --quiet --depth 1 "file://$DEPOT_SOURCE" "$ARAC_HOME" 2>/dev/null; then
            MODE_CLONE="git clone"
        fi
    fi

    if [[ -z "$MODE_CLONE" ]]; then
        # LE DÉPÔT N'A PAS ENCORE UN SEUL COMMIT.
        # On ne fait pas SEMBLANT d'avoir cloné : on copie ce que git EMPORTE,
        # et l'étape rend PARTIEL en le disant. Le jour où le dépôt aura un
        # commit, la branche ci-dessus s'exécutera d'elle-même et l'étape
        # passera à PROUVÉ sans qu'une ligne change ici.
        #
        # C'EST `git ls-files` QUI DIT CE QUE GIT EMPORTE — PAS UN rsync.
        #
        # La copie se faisait par `rsync --filter=':- .gitignore'`, et elle
        # mentait dans LES DEUX SENS :
        #
        #   · en MOINS — rsync ne comprend pas les négations de `.gitignore`.
        #     `.env.example` est explicitement réadmis par un `!.env.example`,
        #     tout comme `config/*.example.toml` ; rsync les voyait exclus par
        #     `.env.*`, et le « clone » ne les portait pas. Six tests du dépôt
        #     tombent sans `.env.example`, et l'entretien perd son modèle de
        #     taxonomie ;
        #   · en PLUS — rsync copie les répertoires VIDES. `static/` en était
        #     un, et il arrivait donc dans le clone alors que git ne l'aurait
        #     jamais transporté. C'est exactement le défaut qui a empêché
        #     l'API de démarrer chez celui qui clone, et cette copie-ci le
        #     rendait invisible à l'épreuve censée le voir.
        #
        # `git ls-files --cached --others --exclude-standard` répond à la
        # question littérale — « quels FICHIERS git connaît-il ? » — négations
        # comprises, et ne connaît aucun répertoire, donc aucun répertoire
        # vide. On copie cette liste, et rien d'autre.
        mkdir -p "$ARAC_HOME"
        if git -C "$DEPOT_SOURCE" ls-files -z --cached --others --exclude-standard 2>/dev/null \
             | (cd "$DEPOT_SOURCE" && cpio -0 -pdum --quiet "$ARAC_HOME" 2>/dev/null); then
            MODE_CLONE="copie de « git ls-files » (aucun commit dans le dépôt source)"
        else
            # Ni commit, ni git utilisable : on le dit, et on copie au plus
            # près. C'est le seul chemin qui puisse encore mentir, et il est
            # nommé dans le verdict.
            rsync -a --exclude='.git/' --exclude='.venv/' --exclude='__pycache__/' \
                  --filter=':- .gitignore' "$DEPOT_SOURCE/" "$ARAC_HOME/" 2>/dev/null
            find "$ARAC_HOME" -type d -empty -delete 2>/dev/null
            MODE_CLONE="copie rsync (ni commit, ni « git ls-files » utilisable)"
        fi
    fi
    info "obtenu par : $MODE_CLONE"

    local manque=()
    local f
    for f in bootstrap/wizard.py bootstrap/bootstrap.sh bootstrap/checks/verify_install.sh \
             Makefile requirements.txt README.md config/scopes.example.toml \
             alembic.ini mac/arac-sync.py; do
        [[ -e "$ARAC_HOME/$f" ]] || manque+=("$f")
    done

    # UN DÉPÔT CLONÉ NE PORTE LE CERVEAU DE PERSONNE.
    # C'est l'assertion F1/F2 rendue mécanique à l'endroit exact où elle se
    # joue : si ces fichiers étaient là, l'inconnu hériterait de la taxonomie,
    # de l'identité ou des secrets de quelqu'un d'autre.
    #
    # LA MÊME LISTE QU'AU §13.7, ET C'EST LA MÊME QUESTION. « Ce qu'un départ
    # doit retirer du clone » et « ce qu'un clone frais ne doit pas porter »
    # sont deux formulations d'un seul ensemble : celui des fichiers qui
    # portent une identité. Ce fichier en tenait DEUX copies ; il n'en tient
    # plus aucune — la liste est LUE dans le §13 (voir `chemins_rm_du_13`), et
    # `.env`/`.venv` s'y ajoutent, qui ne sont pas au §13 parce qu'ils ne sont
    # pas versionnés et ne partent donc pas avec un déménagement.
    local herite=() liste_clone=()
    while IFS= read -r f; do [[ -n "$f" ]] && liste_clone+=("$f"); done \
        < <(fichiers_du_clone_selon_le_13)
    if (( ${#liste_clone[@]} == 0 )); then
        ko "le juge ne sait plus lire la liste du §13 dans $(page_installation) — il refuse d'en tenir une copie"
        verdict "ÉCHEC" "la liste des fichiers d'identité du clone n'est plus dérivable du §13"
        return
    fi
    liste_clone+=(.env .venv)
    for f in "${liste_clone[@]}"; do
        [[ -e "$ARAC_HOME/$f" ]] && herite+=("$f")
    done

    if (( ${#manque[@]} )); then
        ko "pièces absentes du clone : ${manque[*]}"
        verdict "ÉCHEC" "le clone ne porte pas de quoi installer : ${manque[*]}"
        return
    fi
    ok "le clone porte l'entretien, le bootstrap, le contrôle, le moteur et le pont"

    if (( ${#herite[@]} )); then
        ko "le clone porte le cerveau de quelqu'un d'autre : ${herite[*]}"
        verdict "ÉCHEC" "valeurs héritées présentes dans le clone : ${herite[*]}"
        return
    fi
    ok "aucune identité, aucune taxonomie, aucun secret hérité"

    # CE QUE LA PHRASE ANNONCE, ET CE QUE LA MÉTHODE MESURE.
    # `find … -type f` comptait les objets, les crochets et les références de
    # `.git` avec le dépôt : « 474 fichiers clonés » là où `git clone` en
    # transporte 445. Dans le seul document dont toute la valeur tient à ce que
    # ses nombres soient MESURÉS, on compte ce que la phrase nomme — et on dit
    # par quelle méthode, comme `tests/corpus_du_depot.py` le fait déjà.
    local fichiers methode
    fichiers="$(git -C "$ARAC_HOME" ls-files 2>/dev/null | wc -l)"
    if (( fichiers > 0 )); then
        methode="fichiers suivis par git"
    else
        fichiers="$(find "$ARAC_HOME" -type f -not -path '*/.git/*' | wc -l)"
        methode="fichiers (compte disque, hors .git — git n'a pas répondu)"
    fi
    if [[ "$MODE_CLONE" == "git clone" ]]; then
        verdict "PROUVÉ" "$fichiers $methode ; ni brain.toml, ni scopes.toml, ni .env"
    else
        nonteste "le clone par « git clone » — le dépôt source n'a aucun commit ; l'étape a été exercée par $MODE_CLONE"
        verdict "PARTIEL" "$fichiers $methode ; obtenu par $MODE_CLONE, pas par « git clone »"
    fi
}

# ===========================================================================
# ÉTAPE 2 — suivre la documentation
# ===========================================================================
#
# « Suivre la documentation » n'est pas mécaniquement décidable dans son
# entier — personne ne peut prouver qu'un texte est compréhensible. Trois
# choses le sont, et ce sont celles qui échouent en pratique :
#
#   · les commandes que la documentation donne EXISTENT et s'exécutent ;
#   · les documents qu'elle cite EXISTENT ;
#   · la règle pédagogique du bootstrap est MÉCANIQUE, pas morale — `ui.sh`
#     refuse d'afficher une étape qui n'annonce pas ses trois raisons.
#
# Le troisième point est le seul qui protège la pédagogie d'une érosion
# silencieuse. On l'exerce en lui donnant une étape amputée : elle doit
# mourir en code 70, pas s'afficher à moitié.

etape_2_documentation() {
    cd "$ARAC_HOME" || { verdict "ÉCHEC" "clone inaccessible"; return; }
    local souci=0

    local rc=0
    python3 bootstrap/wizard.py --check >/dev/null 2>&1 || rc=$?
    if (( rc <= 1 )); then
        ok "python3 bootstrap/wizard.py --check   rend son bilan de prérequis (code $rc)"
    else
        ko "python3 bootstrap/wizard.py --check   code $rc"; souci=1
    fi

    local etapes n_etapes n_attendu
    etapes="$(./bootstrap/bootstrap.sh --etapes 2>&1)"; rc=$?
    # LE MOTIF EXIGEAIT UNE MINUSCULE ET NE POUVAIT DONC PAS VOIR « (épilogue) » :
    # il annonçait « 10 étapes » pendant que l'installateur écrivait « ÉTAPE
    # 11 / 11 » à l'écran. On compte toute ligne indentée non vide, et — c'est
    # le point — on CONFRONTE le compte à la constante que le programme mesuré
    # publie lui-même. Un rapport qui mesure doit tomber d'accord avec sa source.
    n_etapes="$(grep -cE '^[[:space:]]{2}[^[:space:]]' <<<"$etapes")"
    # ON DEMANDE SA VALEUR AU PROGRAMME, ON NE LA LIT PLUS DANS SON TEXTE.
    # Ce contrôle prenait `TOTAL_ETAPES` par `sed`, ce qui n'a de sens que tant
    # que la constante est écrite en chiffres. Elle se COMPTE désormais
    # (`${#ETAPES[@]} + 1`), et le `sed` n'aurait plus rien rendu : le juge
    # aurait condamné le bootstrap pour « ne publie aucun TOTAL_ETAPES » alors
    # qu'il en publie un, mieux qu'avant. On source, et on lit la valeur.
    n_attendu="$(bash -c 'source bootstrap/lib/ui.sh 2>/dev/null
                          source bootstrap/lib/core.sh 2>/dev/null
                          printf "%s" "${TOTAL_ETAPES:-}"' 2>/dev/null)"
    n_attendu="${n_attendu%%$'\n'*}"
    if (( rc != 0 )); then
        ko "./bootstrap/bootstrap.sh --etapes     code $rc"; souci=1
    elif (( n_etapes == 0 )); then
        ko "./bootstrap/bootstrap.sh --etapes     n'annonce aucune étape"; souci=1
    elif [[ -z "$n_attendu" ]]; then
        ko "./bootstrap/bootstrap.sh --etapes     annonce $n_etapes étapes, mais bootstrap/lib/core.sh ne publie aucun TOTAL_ETAPES à confronter"
        souci=1
    elif (( n_etapes != n_attendu )); then
        ko "./bootstrap/bootstrap.sh --etapes     rend $n_etapes lignes, bootstrap/lib/core.sh en annonce $n_attendu"
        souci=1
    else
        ok "./bootstrap/bootstrap.sh --etapes     annonce $n_etapes étapes, et bootstrap/lib/core.sh en publie autant"
    fi

    ./bootstrap/bootstrap.sh --help >/dev/null 2>&1 && ok "./bootstrap/bootstrap.sh --help       répond" \
        || { ko "./bootstrap/bootstrap.sh --help       échoue"; souci=1; }

    # --- LES CINQ RÔLES : LE SHELL ET LA MIGRATION DISENT-ILS LA MÊME CHOSE ?
    #
    # Le bootstrap est du shell, la migration qui CRÉE les rôles est du Python
    # (`db/alembic/roles.py`). Aucun des deux ne peut lire l'autre au moment où
    # il s'exécute — le bootstrap tourne avant que le venv existe. La liste est
    # donc écrite deux fois, et c'est le seul endroit de ce chantier où elle ne
    # peut PAS être dérivée. Ce qui peut l'être, c'est le CONSTAT : le juge, lui,
    # lit les deux et n'en tient aucune. Un rôle ajouté d'un seul côté rougit
    # ici, à l'étape 2, avant qu'une installation ne le découvre.
    local r_shell r_python
    r_shell="$(bash -c 'source bootstrap/lib/ui.sh 2>/dev/null
                        source bootstrap/lib/core.sh 2>/dev/null
                        printf "%s\n" "${SUFFIXES_DE_ROLE[*]:-}"' 2>/dev/null)"
    r_python="$(suffixes_de_role | tr '\n' ' ')"
    r_shell="${r_shell%"${r_shell##*[![:space:]]}"}"
    r_python="${r_python%"${r_python##*[![:space:]]}"}"
    if [[ -z "$r_shell" || -z "$r_python" ]]; then
        ko "rôles           impossible de confronter bootstrap/lib/core.sh et db/alembic/roles.py (« $r_shell » / « $r_python »)"
        souci=1
    elif [[ "$r_shell" != "$r_python" ]]; then
        ko "rôles           bootstrap/lib/core.sh dit « $r_shell », db/alembic/roles.py dit « $r_python » — deux écritures d'une même liste, et elles divergent"
        souci=1
    else
        ok "rôles           bootstrap/lib/core.sh et db/alembic/roles.py nomment les mêmes rôles : $r_python"
    fi

    # --- La garde pédagogique, exercée -----------------------------------
    rc=0
    bash -c 'source bootstrap/lib/ui.sh; etape_entete 1 1 "essai" "pourquoi" "construit" ""' \
        >/dev/null 2>&1 || rc=$?
    if (( rc == 70 )); then
        ok "ui.sh REFUSE une étape sans ses trois raisons (code 70)"
    else
        ko "ui.sh a accepté une étape amputée de sa conséquence (code $rc, attendu 70)"
        souci=1
    fi
    rc=0
    bash -c 'source bootstrap/lib/ui.sh; etape_entete 1 1 "essai" "pourquoi" "construit" "conséquence"' \
        >/dev/null 2>&1 || rc=$?
    (( rc == 0 )) && ok "…et l'accepte quand les trois sont là" \
        || { ko "ui.sh refuse une étape COMPLÈTE (code $rc)"; souci=1; }

    # --- Les documents cités existent-ils ? ------------------------------
    #
    # LA CLASSE DE CARACTÈRES EST EN ASCII PUR, ET C'EST UNE CICATRICE.
    # Elle a d'abord porté « À-ÿ », par précaution, pour les noms accentués.
    # Sous une locale C, « À » vaut deux octets : la classe devient une plage
    # inversée, grep rend « Invalid range end » et ne trouve RIEN. Comme
    # l'erreur partait dans /dev/null et qu'aucun document trouvé signifie
    # aucun document manquant, le contrôle affichait « les 0 documents cités
    # existent » — et passait. Une garde qui réussit parce qu'elle n'a rien
    # regardé est pire qu'une garde absente.
    # Deux corrections, pas une : la classe est en ASCII (aucun nom de
    # document n'a jamais eu besoin d'autre chose), et zéro citation est
    # désormais un ÉCHEC.
    local cites absents=()
    cites="$(grep -rhoE 'docs/[A-Za-z0-9_.-]+\.md' README.md bootstrap/ | sort -u)"
    local d
    while IFS= read -r d; do
        [[ -z "$d" ]] && continue
        [[ -e "$ARAC_HOME/$d" ]] || absents+=("$d")
    done <<< "$cites"
    local n_cites; n_cites="$(printf '%s\n' "$cites" | grep -c .)"
    if (( n_cites == 0 )); then
        ko "aucun document cité par le README ni par le bootstrap — le contrôle n'a rien regardé"
        souci=1
    elif (( ${#absents[@]} == 0 )); then
        ok "les $n_cites documents cités par le README et le bootstrap existent"
    else
        ko "documents cités et ABSENTS : ${absents[*]}"; souci=1
    fi

    if (( souci )); then
        verdict "ÉCHEC" "la documentation promet des gestes ou des documents qui manquent"
    else
        verdict "PROUVÉ" "$n_etapes étapes annoncées, $n_cites documents cités présents, ui.sh refuse mécaniquement une étape sans ses trois raisons"
    fi
    nonteste "la COMPRÉHENSIBILITÉ des textes : aucune machine ne la mesure. Ce que ce test prouve, c'est que rien de ce que la documentation promet n'est absent"
}

# ===========================================================================
# ÉTAPE 3 — installer ARAC
# ===========================================================================

JOURNAL_BOOTSTRAP=""
#: Où le journal de l'installation est recopié quand elle échoue.
#:
#: `$JOURNAL_BOOTSTRAP` vit sous `$BASE_TRAVAIL`, que le démontage EFFACE — y
#: compris en cas d'échec, et c'est la bonne règle : cette épreuve ne laisse
#: rien derrière elle. Mais « voir /var/lib/arac-acceptation/<id>/bootstrap.log »
#: désignait alors un fichier qui n'existait plus quand on lisait la phrase.
#: Le seul cas où l'on a besoin du journal est précisément celui-là.
JOURNAL_SURVIVANT=""

# ---------------------------------------------------------------------------
# POURQUOI L'INSTALLATION A ÉCHOUÉ — dit ici, pas ailleurs
#
# Le message rendu était : « l'installation a échoué (code 1) — voir <journal> ».
# Trois défauts, dans le seul moment où ce script doit être utile :
#
#   1. le journal cité est effacé par le démontage, quelques secondes plus tard ;
#   2. le `grep '✗|ÉCHEC|Traceback|error'` peut ne RIEN trouver — une étape qui
#      s'arrête sur un refus poli n'écrit aucun de ces mots — et l'on rendait
#      alors un échec sans une ligne d'explication ;
#   3. la cause la plus fréquente, deux manches d'affilée, n'est PAS dans ce
#      journal : quand l'API ne démarre pas, le bootstrap voit « ce cerveau
#      n'est pas sain » et la raison est dans le journal de systemd, que
#      personne n'allait chercher.
#
# On répond donc aux trois : on conserve le journal hors du dossier de travail,
# on montre la fin du journal quoi qu'il arrive, et on va chercher ce que
# systemd a à dire des deux unités.
# ---------------------------------------------------------------------------
_dire_pourquoi_l_installation_a_echoue() { # code
    local l
    JOURNAL_SURVIVANT="${TMPDIR:-/tmp}/arac-acceptation-$RUN-bootstrap.log"
    if cp -f "$JOURNAL_BOOTSTRAP" "$JOURNAL_SURVIVANT" 2>/dev/null; then
        chmod 0600 "$JOURNAL_SURVIVANT" 2>/dev/null
        info "journal conservé : $JOURNAL_SURVIVANT (hors du dossier démonté)"
    else
        JOURNAL_SURVIVANT="(le journal n'a pas pu être conservé)"
    fi

    # La dernière ÉTAPE atteinte : c'est elle qui situe la panne. Le bootstrap
    # imprime « ÉTAPE n/N — titre » ; on rend la dernière vue.
    local derniere
    derniere="$(grep -aE '(ÉTAPE|ETAPE) [0-9]+/[0-9]+' "$JOURNAL_BOOTSTRAP" 2>/dev/null | tail -1)"
    [[ -n "$derniere" ]] && info "dernière étape atteinte : $derniere"

    # Ce qui ressemble à une cause, S'IL Y EN A. Puis, quoi qu'il arrive, la
    # fin du journal : mieux vaut vingt lignes brutes qu'un silence poli.
    local -a indices=()
    mapfile -t indices < <(grep -anE '✗|ÉCHEC|REFUS|Traceback|Error|error:|Errno' \
                                  "$JOURNAL_BOOTSTRAP" 2>/dev/null | tail -8)
    if (( ${#indices[@]} )); then
        info "ce que le journal accuse :"
        for l in "${indices[@]}"; do info "  $l"; done
    fi
    info "les 20 dernières lignes du journal :"
    tail -20 "$JOURNAL_BOOTSTRAP" 2>/dev/null | while IFS= read -r l; do info "  $l"; done

    # LA CAUSE QUI N'EST PAS DANS CE JOURNAL. Une unité qui ne démarre pas ne
    # dit rien au bootstrap : elle le dit à systemd, en boucle.
    local u
    for u in api cockpit; do
        local fichier_unite
        fichier_unite="$(systemctl list-unit-files --no-legend "$PREFIXE_UNITE-$u.service" 2>/dev/null)"
        [[ -n "${fichier_unite//[[:space:]]/}" ]] || continue
        info "systemd, $PREFIXE_UNITE-$u.service : $(systemctl is-active "$PREFIXE_UNITE-$u.service" 2>/dev/null)"
        journalctl -u "$PREFIXE_UNITE-$u.service" -n 12 --no-pager 2>/dev/null \
            | while IFS= read -r l; do info "  $l"; done
    done
}

etape_3_installer() {
    cd "$ARAC_HOME" || { verdict "ÉCHEC" "clone inaccessible"; return; }
    JOURNAL_BOOTSTRAP="$BASE_TRAVAIL/bootstrap.log"

    # --- Le cluster, à nous ----------------------------------------------
    info "création du cluster PostgreSQL $PG_MAJEURE/$CLUSTER sur le port $PORT_PG"
    # LE PORT A ÉTÉ CHOISI AU DÉMARRAGE ; UNE INSTALLATION ENTIÈRE S'EST
    # ÉCOULÉE DEPUIS. Sur une machine partagée, un tiers a pu le prendre entre
    # les deux — et `pg_createcluster --start` rendrait alors un code 25 nu,
    # que le lecteur imputerait au framework. On regarde AVANT, et on NOMME.
    local tenu_par declare_par
    tenu_par="$(ss -ltnHp "sport = :$PORT_PG" 2>/dev/null)"; tenu_par="${tenu_par%%$'\n'*}"
    declare_par="$(ports_pg_declares_sur "$PORT_PG")"
    if [[ -n "$tenu_par" || -n "$declare_par" ]]; then
        ko "le port $PORT_PG n'est plus libre depuis que ce test l'a choisi"
        [[ -n "$tenu_par" ]]    && info "  il est ÉCOUTÉ par : $tenu_par"
        [[ -n "$declare_par" ]] && info "  il est DÉCLARÉ par le cluster : $declare_par (arrêté ou non)"
        info "  ce n'est pas une panne du framework : relancez, un autre port sera choisi."
        verdict "ÉCHEC" "le port PostgreSQL $PORT_PG a été pris par un tiers pendant l'exécution"
        return
    fi
    local sortie_cluster rc_cluster=0
    sortie_cluster="$(pg_createcluster "$PG_MAJEURE" "$CLUSTER" --port "$PORT_PG" --start 2>&1)" || rc_cluster=$?
    if (( rc_cluster != 0 )); then
        ko "pg_createcluster a rendu $rc_cluster"
        tail -4 <<<"$sortie_cluster" | while IFS= read -r l; do info "  $l"; done
        verdict "ÉCHEC" "le cluster d'essai n'a pas pu être créé (code $rc_cluster)"
        return
    fi
    ok "cluster $PG_MAJEURE/$CLUSTER démarré sur $PORT_PG — les rôles de ce cerveau y vivront, isolés par construction"

    # --- L'entretien, sans intervention humaine ---------------------------
    #
    # `wizard.py` n'a PAS de mode non interactif, et sa docstring dit
    # pourquoi. On ne lui en invente pas un : on lui parle comme un humain le
    # ferait, par l'entrée standard. C'est le vrai entretien qui tourne, avec
    # ses validations et ses valeurs par défaut.
    local reponses
    reponses="$(printf '%s\n' \
        "$PROPRIETAIRE" \
        "$CERVEAU" \
        "$POSTE" \
        "1 10 11" \
        "n" \
        "" "n" \
        "" "n" \
        "" "n" \
        "o")"
    if ! python3 bootstrap/wizard.py > "$BASE_TRAVAIL/entretien.log" 2>&1 <<<"$reponses"; then
        ko "l'entretien n'a pas abouti — voir $BASE_TRAVAIL/entretien.log"
        tail -5 "$BASE_TRAVAIL/entretien.log" | while IFS= read -r l; do info "$l"; done
        verdict "ÉCHEC" "l'entretien a échoué"
        return
    fi
    if [[ ! -r config/brain.toml || ! -r config/scopes.toml ]]; then
        ko "l'entretien n'a pas écrit config/brain.toml et config/scopes.toml"
        verdict "ÉCHEC" "l'entretien n'a produit aucune description de cerveau"
        return
    fi
    ok "entretien mené sans intervention : config/brain.toml et config/scopes.toml écrits"

    # --- La simulation, et sa pédagogie -----------------------------------
    #
    # F3 dit : chaque étape annonce POURQUOI elle existe, CE QU'ELLE CONSTRUIT
    # et sa CONSÉQUENCE. `ui.sh` le rend mécanique à l'affichage ; ici on
    # vérifie que les onze étapes de la simulation le font TOUTES.
    #
    # COMPTER LES LIGNES « Pourquoi » NE SUFFIT PAS, et la première version de
    # ce contrôle est morte là-dessus : l'étape 3 porte un intertitre
    # « Pourquoi quatre rôles, et non un » qui commence par le même mot. Le
    # compte rendait 12 pour 11 en-têtes, et le test accusait la pédagogie
    # d'un défaut qui était le sien.
    #
    # On vérifie donc BLOC PAR BLOC, à la colonne exacte où `_triade` écrit
    # ses étiquettes — ce qu'un intertitre, écrit par `dire`, ne fait pas.
    local simulation
    simulation="$(_env_bootstrap ./bootstrap/bootstrap.sh --dry-run --no-color 2>&1)"
    local rc_sim=$?
    printf '%s\n' "$simulation" > "$BASE_TRAVAIL/simulation.log"
    # LA SIMULATION EST LUE DEPUIS UN FICHIER, PAS DEPUIS UN TUBE.
    # `printf … | python3 - <<'PY'` ne marche pas : le document en ligne
    # FOURNIT l'entrée standard (c'est de là que `python3 -` lit son
    # programme), et le tube n'atteint jamais `sys.stdin`. Le contrôle
    # analysait donc une entrée vide, trouvait zéro bloc, et accusait la
    # simulation de ne rien enseigner. Le fichier lève l'ambiguïté.
    local pedagogie
    pedagogie="$(python3 - "$BASE_TRAVAIL/simulation.log" <<'PY'
import pathlib, re, sys

# `ui.sh:_triade` écrit :  deux espaces + étiquette calée sur 13 caractères
# + un espace + le texte. Le texte commence donc TOUJOURS colonne 16 — ce
# qu'un intertitre écrit par `dire` ne fait jamais, même quand il commence
# par le mot « Pourquoi ».
ETIQUETTES = ("Pourquoi", "Construit", "Conséquence")
ENTETE = re.compile(r"^  ÉTAPE \d+ / \d+ — (.+)$")

blocs, courant = [], None
for ligne in pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    m = ENTETE.match(ligne)
    if m:
        courant = {"titre": m.group(1).strip(), "vues": set()}
        blocs.append(courant)
        continue
    if courant is None or len(ligne) < 16:
        continue
    if ligne[2:15].rstrip() in ETIQUETTES and ligne[15:].strip():
        courant["vues"].add(ligne[2:15].rstrip())

amputees = [b["titre"] for b in blocs if set(ETIQUETTES) - b["vues"]]
print(f"{len(blocs)}|{' / '.join(amputees)}")
PY
)"
    local n_blocs="${pedagogie%%|*}" amputees="${pedagogie#*|}"
    if (( rc_sim == 0 )) && [[ "$n_blocs" =~ ^[0-9]+$ ]] && (( n_blocs > 0 )) && [[ -z "$amputees" ]]; then
        ok "simulation : $n_blocs étapes, chacune annonçant Pourquoi + Construit + Conséquence"
    else
        ko "simulation : code $rc_sim, $n_blocs bloc(s) ; amputées : ${amputees:-—}"
        info "  sortie complète : $BASE_TRAVAIL/simulation.log (effacé au démontage)"
        grep -nE '✗|ÉCHEC' "$BASE_TRAVAIL/simulation.log" | head -6 \
            | while IFS= read -r l; do info "$l"; done
        verdict "ÉCHEC" "la simulation n'enseigne pas ce qu'elle promet"
        return
    fi

    # --- L'installation réelle -------------------------------------------
    info "installation en cours (pip, migrations, unités) — quelques minutes"
    _env_bootstrap ./bootstrap/bootstrap.sh --yes --no-color > "$JOURNAL_BOOTSTRAP" 2>&1
    local rc_boot=$?
    if (( rc_boot != 0 )); then
        ko "bootstrap.sh --yes a rendu $rc_boot"
        _dire_pourquoi_l_installation_a_echoue "$rc_boot"
        verdict "ÉCHEC" "l'installation a échoué (code $rc_boot) — cause ci-dessus, journal conservé dans $JOURNAL_SURVIVANT"
        return
    fi
    ok "bootstrap.sh --yes : installation complète, code 0"

    # --- Le contrôle a posteriori, tel que la documentation le donne ------
    _env_bootstrap ./bootstrap/bootstrap.sh --verify --no-color > "$BASE_TRAVAIL/verify.log" 2>&1
    local rc_verify=$?
    # `grep -c` ÉCRIT « 0 » puis rend 1 quand il ne trouve rien. Un
    # `|| printf 0` derrière lui produirait « 00 » — un compte faux, et non
    # nul, donc lu comme un échec.
    local rates
    rates="$(grep -cE '✗' "$BASE_TRAVAIL/verify.log" 2>/dev/null)"
    rates="${rates:-0}"
    if (( rc_verify == 0 )); then
        ok "bootstrap.sh --verify : le contrôle a posteriori ne relève aucun échec"
    else
        ko "bootstrap.sh --verify : code $rc_verify, $rates échec(s)"
        grep -E '^\s+✗' "$BASE_TRAVAIL/verify.log" | head -10 \
            | while IFS= read -r l; do info "$l"; done
    fi

    # --- Les services répondent-ils ? -------------------------------------
    local code_api; code_api="$(attendre_http "$URL_API/healthz" 90)"
    if [[ "$code_api" == "200" ]]; then
        ok "l'API du cerveau répond sur 127.0.0.1:$PORT_API (healthz $code_api)"
    else
        ko "l'API du cerveau ne répond pas sur $PORT_API (healthz $code_api)"
        journalctl -u "$PREFIXE_UNITE-api.service" -n 12 --no-pager 2>/dev/null \
            | while IFS= read -r l; do info "$l"; done
    fi

    # Le bootstrap a rendu 0 : la base, les rôles, les migrations, les secrets
    # et les unités existent. Les étapes suivantes ont donc de quoi mordre,
    # même si le contrôle a posteriori relève des reproches.
    CERVEAU_INSTALLE=1

    local restauration=0
    _preuve_restauration && restauration=1

    # UNE « PARTIELLE » QUI CACHAIT TROIS ÉCHECS, ET QUI RENDAIT LE CODE 0.
    #
    # Ce verdict était « PARTIEL … le contrôle relève N échec(s), ET/OU l'API
    # rend X, ET/OU la restauration n'a pas pu être prouvée ». Trois défauts
    # sous un seul mot, séparés par des « et/ou » qui empêchent de savoir
    # lequel est tombé — et PARTIEL ne compte pas dans « en échec » : une
    # installation dont le contrôle a posteriori proteste sortait donc en
    # code 0, sous une ligne qu'on lit comme une nuance.
    #
    # La définition est en tête de ce fichier : PARTIEL = « exercée, mais une
    # partie de ce qu'elle affirme n'a pas pu l'être, et cette partie est
    # NOMMÉE » ; ÉCHEC = « exercée, et le résultat contredit ce qui est
    # promis ». Les trois cas ci-dessous contredisent. Ce sont des échecs, et
    # on dit LEQUEL.
    local -a contredits=()
    (( rc_verify != 0 ))         && contredits+=("le contrôle a posteriori rend $rc_verify et relève $rates échec(s)")
    [[ "$code_api" != "200" ]]   && contredits+=("l'API du cerveau rend « $code_api » sur /healthz, pas 200")
    (( restauration == 0 ))      && contredits+=("la sauvegarde armée par le bootstrap n'a pas pu être RESTAURÉE")
    if (( ${#contredits[@]} == 0 )); then
        verdict "PROUVÉ" "installation complète en une commande, contrôle a posteriori sans échec, API vivante sur $PORT_API, et une sauvegarde RESTAURÉE pour de vrai dans une base jetable"
    else
        local quoi; quoi="$(printf '%s ; ' "${contredits[@]}")"
        verdict "ÉCHEC" "l'installation s'est déclarée terminée, et pourtant : ${quoi%; }"
    fi
}

# ---------------------------------------------------------------------------
# UNE SAUVEGARDE JAMAIS RESTAURÉE N'EST PAS UNE SAUVEGARDE
# ---------------------------------------------------------------------------
#
# C'est la seule promesse de ce dépôt que personne n'avait jamais pu vérifier,
# et elle était prescrite par TROIS documents et par le contrôle quotidien :
# `docs/INSTALLATION.md` §11 la donne comme un contrôle, `docs/EXPLOITATION.md`
# la range parmi ses cinq commandes, `ops/install_check.sh` porte en permanence
# « ? aucune restauration n'a jamais été vérifiée » et `ops/watchdog.sh` crie
# « vos dumps sont une hypothèse ».
#
# Elle était INTENABLE : `ops/restore_verify.sh` crée sa base jetable sous le
# rôle d'administration du cerveau, qui n'avait pas l'attribut CREATEDB — et
# rien dans le dépôt ne le lui donnait. Sur tout cerveau posé par le bootstrap,
# le script mourait sur « permission denied to create database ». Le chemin de
# secours documenté (`--prepare-template`) échouait EXACTEMENT pareil, parce
# que copier un gabarit exige aussi CREATEDB — et cette branche-là n'imprimait
# même pas de geste.
#
# Une promesse que personne ne peut exercer finit par n'être exercée par
# personne. On l'exerce donc ici, à chaque acceptation, sur une installation
# RÉELLE posée par le vrai bootstrap : dump, restauration dans une base
# jetable, lecture du contenu, destruction de la base jetable. Et on exige que
# la réserve d'`ops/install_check.sh` TOMBE — c'est elle, le produit fini.
#
# LE DUMP EST PRODUIT PAR L'UNITÉ QUE LE BOOTSTRAP VIENT DE POSER, PAS PAR
# L'AUTRE CHEMIN — ET C'EST LA CORRECTION LA PLUS IMPORTANTE DE CETTE ÉTAPE.
#
# Cette fonction lançait `ops/backup.sh` puis `ops/restore_verify.sh`, dos à
# dos. Les deux marchaient, le vert tombait à chaque exécution — et
# l'installation que ce test venait de faire n'empruntait JAMAIS ce chemin :
# l'unité `arac-<base>-sauvegarde.service` inlinait son propre `pg_dump -Fc`,
# sans `--schema`, et le dump qui en sortait était déclaré irrestaurable par
# `ops/restore_verify.sh` (« le dump ne se restaure pas. Le coffre est
# vide. »). Une assertion qui ne peut pas rencontrer son contre-exemple n'est
# pas une preuve : le test certifiait une branche que le lecteur n'a pas.
#
# On démarre donc L'UNITÉ. Si un jour son `ExecStart` cesse d'appeler
# `ops/backup.sh`, cette étape rougit — c'est tout ce qu'on lui demande.
#: LANCER L'UNITÉ DE RESTAURATION, PAS LE SCRIPT.
#:
#: LE DÉFAUT QU'ELLE FERME, ET IL A DÉJÀ COÛTÉ UNE FUITE ENTIÈRE. Ce harnais
#: appelait `ops/restore_verify.sh` de sa propre main, en redirigeant sa sortie
#: dans un fichier à lui. L'unité `arac-<base>-restauration.service` — celle
#: que le bootstrap arme, que la minuterie déclenche chaque dimanche, et que le
#: §7 de SAUVEGARDE.md fait lancer — porte pourtant EXACTEMENT le même
#: `ExecStart`, sans argument. La différence n'est pas le code exécuté : c'est
#: OÙ VA SA SORTIE. Appelée à la main, elle parle à un fichier du harnais ;
#: démarrée par systemd, elle parle à journald. Toute cette famille était donc
#: hors du champ du juge PAR CONSTRUCTION, et c'est là qu'un échantillon de
#: souvenirs en clair a vécu des mois sans que rien ne le voie.
#:
#: Rend le code de sortie RÉEL du processus (`ExecMainStatus`), pas le verdict
#: de systemd : l'unité déclare `SuccessExitStatus=2`, donc « restauré, preuve
#: partielle » y compte comme un succès — ce qui est juste pour systemd et faux
#: pour ce harnais, qui doit savoir lequel des deux il a obtenu.
_unite_restauration_lance() { # journal_de_repli
    local rc=0
    systemctl start "$PREFIXE_UNITE-restauration.service" >/dev/null 2>&1 || rc=$?
    local statut
    statut="$(systemctl show -p ExecMainStatus --value "$PREFIXE_UNITE-restauration.service" 2>/dev/null)"
    [[ -n "$statut" ]] && rc="$statut"
    # La sortie est là où le PRODUIT la met. On la recopie pour le rapport,
    # sans jamais faire semblant qu'elle vient d'ailleurs.
    journalctl -u "$PREFIXE_UNITE-restauration.service" --no-pager -o cat -n 200 \
        > "${1:-/dev/null}" 2>/dev/null
    return "$rc"
}

_preuve_restauration() {
    local souci=0 rc=0

    systemctl start "$PREFIXE_UNITE-sauvegarde.service" >/dev/null 2>&1 || rc=$?
    if (( rc != 0 )) || [[ "$(systemctl show -p Result --value "$PREFIXE_UNITE-sauvegarde.service")" != "success" ]]; then
        ko "sauvegarde      $PREFIXE_UNITE-sauvegarde.service a échoué (rc=$rc)"
        journalctl -u "$PREFIXE_UNITE-sauvegarde.service" -n 8 --no-pager -o cat 2>/dev/null \
            | while IFS= read -r l; do info "$l"; done
        return 1
    fi
    ok "sauvegarde      dump produit par l'UNITÉ posée par le bootstrap, pas par un autre chemin"
    local dump
    dump="$(ls -1t "$ARAC_BACKUP_DIR"/*.dump 2>/dev/null | head -1)"
    ok "sauvegarde      un dump réel : $(basename "${dump:-?}") ($(stat -c %s "${dump:-/dev/null}" 2>/dev/null) octets)"

    rc=0
    _unite_restauration_lance "$BASE_TRAVAIL/restauration.log" || rc=$?
    # 0 = prouvé ; 2 = restauré mais fraîcheur non comparable. Sur une
    # installation neuve, seul 0 est acceptable : la base vivante est là.
    if (( rc != 0 )); then
        ko "restauration    $PREFIXE_UNITE-restauration.service a rendu $rc — la sauvegarde n'est PAS prouvée"
        grep -E 'ÉCHEC|ERROR|permission denied|✗' "$BASE_TRAVAIL/restauration.log" | head -6 \
            | while IFS= read -r l; do info "$l"; done
        souci=1
    else
        local lignes
        lignes="$(grep -c '  ✓ ' "$BASE_TRAVAIL/restauration.log" 2>/dev/null)"
        ok "restauration    dump RESTAURÉ dans une base jetable, ${lignes:-0} preuve(s) au vert, sans superutilisateur"
        # La base jetable ne doit RIEN laisser derrière elle. On vise le nom
        # HORODATÉ (`<base>_restore_<epoch>`) et lui seul : un `LIKE
        # '<base>\_restore\_%'` ramasserait aussi `<base>_restore_template`,
        # le gabarit vide que le bootstrap POSE et qui doit rester. Cette
        # nuance a d'abord manqué, et l'acceptation a accusé le démontage
        # d'avoir laissé une base qu'elle était censée trouver.
        local restes
        restes="$(sudo -u postgres psql -p "$PORT_PG" -tAc \
            "SELECT count(*) FROM pg_database WHERE datname ~ '^${ARAC_DB}_restore_[0-9]+\$'" 2>/dev/null)"
        if [[ "${restes:-0}" == "0" ]]; then
            ok "base jetable    détruite — il ne reste que le gabarit vide"
        else
            ko "base jetable    ${restes} base(s) « ${ARAC_DB}_restore_<horodatage> » survivent à la vérification"
            souci=1
        fi
    fi

    # LA RÉSERVE PERMANENTE TOMBE-T-ELLE ? C'est la seule façon de savoir que
    # la correction porte là où l'utilisateur la lit.
    local check
    check="$( cd "$ARAC_HOME" && ARAC_ENV_FILE="$ARAC_ENV_FILE" ops/install_check.sh 2>&1 )"
    if grep -q "aucune restauration n'a jamais été vérifiée" <<<"$check"; then
        ko "réserve levée   ops/install_check.sh porte TOUJOURS « aucune restauration n'a jamais été vérifiée »"
        souci=1
    elif grep -q "dernière restauration PROUVÉE" <<<"$check"; then
        ok "réserve levée   ops/install_check.sh dit « dernière restauration PROUVÉE » — la promesse est tenue"
    else
        ko "réserve levée   ops/install_check.sh ne parle plus de restauration du tout"
        souci=1
    fi

    return "$souci"
}

#: L'environnement d'un cerveau d'essai. Tout ce qui n'est pas ici est DÉDUIT
#: par le bootstrap — et c'est voulu : l'étape 4 vérifie ces déductions contre
#: le réel plutôt que de les imposer.
_env_bootstrap() {
    env \
        ARAC_HOME="$ARAC_HOME" \
        ARAC_DB_PORT="$PORT_PG" \
        ARAC_API_PORT="$PORT_API" \
        ARAC_COCKPIT_PORT="$PORT_COCKPIT" \
        ARAC_LOG_DIR="$ARAC_LOG_DIR" \
        ARAC_BACKUP_DIR="$ARAC_BACKUP_DIR" \
        ARAC_SERVICE_USER="$U_SERVICE" \
        ARAC_AGENT_USER="$U_AGENT" \
        ARAC_ETAT="$ARAC_ETAT" \
        ARAC_UI_COULEUR=jamais \
        LC_ALL=C.UTF-8 \
        "$@"
}

# ===========================================================================
# ÉTAPE 4 — créer son cerveau : c'est le SIEN
# ===========================================================================
#
# L'étape 3 a prouvé que l'installation aboutit. Celle-ci prouve autre chose,
# et c'est l'assertion F2 : le cerveau installé porte les réponses de CET
# utilisateur, et rien de personne d'autre.

etape_4_son_cerveau() {
    exige_installation "créer son cerveau" && return
    local souci=0 valeur

    # --- Ce que le bootstrap a DÉDUIT correspond-il à ce qui a été répondu ?
    if [[ "$(sql "SELECT current_database()")" == "$ARAC_DB" ]]; then
        ok "base            « $ARAC_DB » — déduite du nom de cerveau « $CERVEAU »"
    else
        ko "base            la base attendue « $ARAC_DB » n'existe pas sur $PORT_PG"; souci=1
    fi

    for valeur in ARAC_NODE_ID:"$POSTE" ARAC_BRAIN_NAME:"$CERVEAU" ARAC_BRAIN_OWNER:"$PROPRIETAIRE"; do
        local cle="${valeur%%:*}" attendu="${valeur#*:}" lu
        lu="$(lire_env "$ARAC_ENV_FILE" "$cle" || true)"
        if [[ "$lu" == "$attendu" ]]; then
            ok "$(printf '%-15s' "${cle#ARAC_}")« $lu » — issu de l'entretien"
        else
            ko "$(printf '%-15s' "${cle#ARAC_}")« $lu » ≠ « $attendu »"; souci=1
        fi
    done

    # --- LA TAXONOMIE : ce qui est en base est EXACTEMENT ce qui a été décidé
    #
    # Une ÉGALITÉ D'ENSEMBLES, jamais un compte. Un compte périme à la
    # première migration et se satisfait de deux erreurs qui se compensent.
    local declares en_base
    declares="$(cd "$ARAC_HOME" && python3 - config/scopes.toml <<'PY'
import pathlib, sys, tomllib
d = tomllib.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
chemins = [r["key"] for r in d.get("root", [])]
chemins += [f"{f['root']}/{f['key']}" for f in d.get("leaf", [])]
print("\n".join(sorted(chemins)))
PY
)"
    en_base="$(sql "SELECT path FROM arac.scopes ORDER BY path" | sort)"
    if [[ "$declares" == "$en_base" ]]; then
        ok "taxonomie       $(printf '%s\n' "$declares" | grep -c .) domaines en base, identiques à config/scopes.toml"
    else
        ko "taxonomie       la base et config/scopes.toml divergent"
        diff <(printf '%s\n' "$declares") <(printf '%s\n' "$en_base") | head -10 \
            | while IFS= read -r l; do info "$l"; done
        souci=1
    fi

    # --- L'énumération engendrée dit-elle la même chose ? -----------------
    local en_python
    en_python="$(cd "$ARAC_HOME" && python3 -c "
import sys; sys.path.insert(0, '.')
from app.schemas.scope_generated import Scope
print('\n'.join(sorted(s.value for s in Scope)))" 2>/dev/null | sort)"
    if [[ "$en_python" == "$declares" ]]; then
        ok "énumération     app/schemas/scope_generated.py porte la même taxonomie"
    else
        ko "énumération     scope_generated.py diverge de config/scopes.toml"; souci=1
    fi

    # --- LES CINQ RÔLES, ET LA VRAIE PROPRIÉTÉ QU'ILS DOIVENT AVOIR -------
    #
    # ON NE CODE PAS LES NOMS EN DUR ICI, ET C'EST LE CŒUR DE L'AFFAIRE.
    # La première version de ce contrôle attendait `arac_admin`, `arac_app`…
    # C'était précisément le défaut qui a coûté cinq rôles de production : des
    # noms fixes, donc PARTAGÉS entre tous les cerveaux d'un même cluster, donc
    # écrasés par la seconde installation. Un test qui les fige les rend
    # définitifs.
    #
    # La source de vérité est `ARAC_ROLE_PREFIX`, écrit par le bootstrap dans
    # le fichier d'environnement. On lit ce qu'il a décidé, puis on vérifie les
    # trois propriétés qui comptent vraiment :
    #   1. les cinq rôles existent sur NOTRE cluster ;
    #   2. le préfixe porte l'identité de CE cerveau — sans quoi deux cerveaux
    #      sur un même cluster se partageraient encore leurs rôles ;
    #   3. aucun d'eux n'existe sur le cluster de PRODUCTION. C'est l'assertion
    #      décisive : elle serait fausse le jour de l'incident, et vraie
    #      aujourd'hui.
    local prefixe_role trouves manquants=() r
    prefixe_role="$(lire_env "$ARAC_ENV_FILE" ARAC_ROLE_PREFIX || true)"
    if [[ -z "$prefixe_role" ]]; then
        ko "rôles           ARAC_ROLE_PREFIX absent de $ARAC_ENV_FILE : impossible de savoir comment ce cerveau nomme ses rôles"
        souci=1
    else
        trouves="$(psql_super -d postgres -tAc \
            "SELECT rolname FROM pg_roles ORDER BY rolname" 2>&1)"
        # LE PRÉFIXE ÉTAIT DÉJÀ LU ; LES SUFFIXES, EUX, ÉTAIENT RECOPIÉS.
        # La moitié du nom était donc dérivée et l'autre figée : ajouter un
        # sixième rôle au produit laissait ce contrôle vert et le §13.5
        # incapable de le détruire. On les LIT dans `db/alembic/roles.py`.
        local -a r_suffixes=()
        while IFS= read -r r; do [[ -n "$r" ]] && r_suffixes+=("$r"); done < <(suffixes_de_role)
        if (( ${#r_suffixes[@]} == 0 )); then
            ko "rôles           le juge ne sait plus lire SUFFIXES dans db/alembic/roles.py — il refuse d'en tenir une copie"
            souci=1
        fi
        for r in "${r_suffixes[@]}"; do
            grep -qx "${prefixe_role}_$r" <<<"$trouves" || manquants+=("${prefixe_role}_$r")
        done
        if (( ${#manquants[@]} )); then
            ko "rôles           absents du cluster $PORT_PG : ${manquants[*]}"
            info "  rôles présents : $(printf '%s' "$trouves" | tr '\n' ' ')"
            souci=1
        else
            ok "rôles           ${prefixe_role}_{$(IFS=,; printf '%s' "${r_suffixes[*]}")} existent sur le cluster $PORT_PG — suffixes LUS dans db/alembic/roles.py"
        fi

        if [[ "$prefixe_role" == *"$ARAC_DB"* ]]; then
            ok "nommage         le préfixe « $prefixe_role » porte l'identité de ce cerveau : deux cerveaux ne peuvent plus se partager leurs rôles"
        else
            ko "nommage         le préfixe « $prefixe_role » ne porte pas « $ARAC_DB » — deux cerveaux sur un même cluster écraseraient leurs mots de passe mutuels"
            souci=1
        fi

        local fuites
        fuites="$(sql_prod postgres \
            "SELECT rolname FROM pg_roles WHERE rolname LIKE '${prefixe_role}\_%' ORDER BY rolname")"
        if [[ -z "$fuites" ]]; then
            ok "isolement       aucun rôle de ce cerveau n'existe sur le cluster de production (5432)"
        else
            ko "isolement       ces rôles d'essai ont ATTERRI sur le cluster de production : $(printf '%s' "$fuites" | tr '\n' ' ')"
            souci=1
        fi
    fi

    # --- « Impossible », pas « interdit » : le cockpit ne PEUT pas écrire ---
    local dsn_ro sortie
    dsn_ro="$(lire_env "$ARAC_ENV_FILE" ARAC_DB_URL_READONLY || true)"
    if [[ -n "$dsn_ro" ]]; then
        local rc_ecriture=0
        sortie="$(psql "$dsn_ro" -v ON_ERROR_STOP=1 -tAc \
            "INSERT INTO arac.scopes (name, path, depth) VALUES ('essai','essai-acceptation',0)" 2>&1)" \
            || rc_ecriture=$?
        if (( rc_ecriture != 0 )) && grep -qi 'read-only' <<<"$sortie"; then
            ok "lecture seule   une écriture réelle sous le rôle du cockpit est REFUSÉE par le moteur"
        else
            ko "lecture seule   le rôle du cockpit a pu écrire — ou a échoué pour une autre raison : $sortie"
            souci=1
        fi
    else
        ko "lecture seule   DSN du rôle en lecture seule introuvable"; souci=1
    fi

    # --- Et l'incident : les rôles de la production sont-ils intacts ? ----
    if [[ "$(empreinte_roles_production)" == "$EMPREINTE_ROLES_AVANT" ]]; then
        ok "isolement       l'empreinte des rôles du cluster 5432 est INCHANGÉE après cette installation"
    else
        ko "isolement       DES RÔLES DE PRODUCTION ONT ÉTÉ MODIFIÉS PAR CETTE INSTALLATION"; souci=1
    fi

    if (( souci )); then
        verdict "ÉCHEC" "le cerveau installé ne correspond pas entièrement aux réponses de l'entretien"
    else
        verdict "PROUVÉ" "identité, taxonomie et énumération issues de l'entretien ; cinq rôles sur le cluster d'essai ; le cluster de production intact"
    fi
}

# ===========================================================================
# ÉTAPE 5 — synchroniser ses premières conversations
# ===========================================================================

MESSAGES_ATTENDUS=0
CONVERSATIONS_ATTENDUES=0
JETON_CORPUS=""

etape_5_synchroniser() {
    exige_installation "synchroniser ses premières conversations" && return
    local souci=0
    JETON_CORPUS="ACC$RUN"

    # --- Le corpus, aux formats réels -------------------------------------
    local manifeste="$BASE_TRAVAIL/corpus.json"
    if ! python3 "$_ICI/corpus.py" --racine "$FAUX_MAC" --jeton "$JETON_CORPUS" \
            --manifeste "$manifeste" >/dev/null 2>&1; then
        ko "le corpus fictif n'a pas pu être construit"
        verdict "ÉCHEC" "corpus non construit"
        return
    fi
    MESSAGES_ATTENDUS="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['messages_attendus'])" "$manifeste")"
    CONVERSATIONS_ATTENDUES="$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['conversations_attendues'])" "$manifeste")"
    ok "corpus fictif   $CONVERSATIONS_ATTENDUES conversations, $MESSAGES_ATTENDUS messages, aux deux formats réels (Claude Code CLI et export claude.ai)"

    # --- Le jeton de CE cerveau, avant tout le reste -----------------------
    #
    # Il sert deux fois maintenant : au pont (comme avant), et à toutes les
    # requêtes de cette étape — l'API n'accepte plus rien sans lui, boucle
    # locale comprise.
    local conf="$FAUX_MAC/pont.conf" jeton_api
    jeton_api="$(lire_env "$ARAC_ENV_FILE" ARAC_API_BEARER_TOKEN || true)"
    if [[ -z "$jeton_api" ]]; then
        ko "jeton de l'API introuvable dans $ARAC_ENV_FILE"
        verdict "ÉCHEC" "aucun jeton porteur : plus rien ne peut parler à l'API"
        return
    fi

    # --- LA PORTE : sans jeton, on n'entre pas ----------------------------
    #
    # Ce contrôle est NOUVEAU, et il est le plus important de l'étape.
    #
    # Ce que deux épreuves adversariales ont fait, sur une machine à deux
    # cerveaux, depuis le compte `nobody` et depuis le compte de service du
    # cerveau voisin : un GET a rendu 200 avec un souvenir privé EN CLAIR, un
    # POST a rendu 202 et écrit un faux souvenir. Sans présenter un seul
    # secret. Cette porte ne passait par aucun fichier : ni les comptes
    # système, ni les coffres 0700, ni les rôles PostgreSQL ne la fermaient.
    #
    # On la refrappe ici, sur une VRAIE installation, à chaque acceptation.
    local code_lecture code_ecriture
    code_lecture="$(curl -s -o /dev/null -m 10 -w '%{http_code}' \
        "$URL_API/v1/dashboard/search?q=acceptation")"
    code_ecriture="$(curl -s -o /dev/null -m 10 -w '%{http_code}' -X POST \
        -H 'Content-Type: application/json' \
        -H "X-ARAC-Node-Id: $POSTE" \
        --data '{"source_type":"claude_code","conversation_uid":"sans-jeton","messages":[{"role":"user","content":"tentative"}]}' \
        "$URL_API/v1/ingest/messages")"
    if [[ "$code_lecture" == "401" && "$code_ecriture" == "401" ]]; then
        ok "porte fermée    sans jeton : lecture 401, écriture 401 — sur 127.0.0.1, avec un poste POURTANT déclaré"
    else
        ko "porte fermée    sans jeton : lecture $code_lecture, écriture $code_ecriture (attendu 401/401)"
        info "  Un compte local quelconque lit et corrompt la mémoire de ce cerveau."
        souci=1
    fi

    # Et le refus doit ENSEIGNER : un 401 nu se paie en heures de recherche.
    local corps_401
    corps_401="$(curl -s -m 10 "$URL_API/v1/dashboard/search?q=acceptation")"
    if grep -q 'ou_est_le_jeton' <<<"$corps_401" \
       && grep -q 'arac.env' <<<"$corps_401"; then
        ok "refus qui enseigne  le 401 dit ce qui manque, pourquoi, et OÙ trouver le jeton"
    else
        ko "refus qui enseigne  le 401 ne dit pas où est le jeton : $(printf '%s' "$corps_401" | head -c 200)"
        souci=1
    fi

    # --- La liste blanche est-elle FERMÉE pour un poste inconnu ? ---------
    #
    # On le vérifie AVANT d'envoyer quoi que ce soit de légitime : une garde
    # qu'on ne teste que sur le chemin heureux n'est pas une garde. C'est le
    # blocage le plus cruel de l'installation quand il est mal posé — tout
    # tourne, rien n'entre, et rien ne le dit.
    #
    # LA REQUÊTE PORTE MAINTENANT UN JETON VALIDE, et c'est ce qui rend le
    # contrôle plus fort qu'avant : sans jeton, ce POST repartirait en 401 et
    # ne dirait donc RIEN de la liste blanche — on prouverait la porte deux
    # fois et la liste zéro. Avec le jeton, la requête atteint bien la
    # résolution de node_id, et c'est elle qui refuse.
    local code_403
    code_403="$(curl -s -o /dev/null -m 10 -w '%{http_code}' -X POST \
        -H 'Content-Type: application/json' \
        -H "Authorization: Bearer $jeton_api" \
        -H 'X-ARAC-Node-Id: poste-jamais-declare' \
        --data '{"source_type":"claude_code","conversation_uid":"intrus","messages":[{"role":"user","content":"tentative"}]}' \
        "$URL_API/v1/ingest/messages")"
    if [[ "$code_403" == "403" ]]; then
        ok "liste blanche   un poste non déclaré est refusé en 403, avant toute écriture — jeton valide compris"
    else
        ko "liste blanche   un poste non déclaré a reçu $code_403 (attendu 403)"; souci=1
    fi

    # --- Le VRAI pont, sur un faux Mac ------------------------------------
    #
    # `mac/arac-sync.py` n'est pas simulé : c'est lui qui lit le corpus, le
    # découpe, le compresse, pose ses en-têtes et parle à l'API. Ce qui est
    # remplacé, c'est le TRANSPORT — le tunnel SSH devient une boucle locale.
    # C'est LUI la seconde moitié de la preuve : la porte est fermée ET le
    # produit fonctionne encore.
    ( umask 077; printf '%s\n' "$jeton_api" > "$FAUX_MAC/jeton_ingest" )
    chmod 600 "$FAUX_MAC/jeton_ingest"
    cat > "$conf" <<CONF
ARAC_NODE_ID=$POSTE
ARAC_INGEST_URL=$URL_API/v1/ingest/messages
ARAC_TOKEN_FILE=$FAUX_MAC/jeton_ingest
ARAC_CLAUDE_CODE_DIR=$FAUX_MAC/claude/projects
ARAC_DESKTOP_EXPORT=$FAUX_MAC/arac/export-desktop/conversations.json
ARAC_STATE_FILE=$FAUX_MAC/etat-pont.json
ARAC_LOG_FILE=$FAUX_MAC/journal/arac-pont.log
ARAC_MAX_CONVERSATIONS=0
CONF

    local rc=0
    ( cd "$ARAC_HOME" && python3 mac/arac-sync.py --conf "$conf" --jenvoie ) \
        > "$BASE_TRAVAIL/synchro.log" 2>&1 || rc=$?
    if (( rc != 0 )); then
        ko "le pont a rendu $rc"
        tail -12 "$BASE_TRAVAIL/synchro.log" | while IFS= read -r l; do info "$l"; done
        souci=1
    else
        ok "pont            mac/arac-sync.py a envoyé et obtenu l'acquittement du serveur"
    fi

    # --- Ce que la base a réellement reçu ---------------------------------
    local n_msg n_conv
    n_msg="$(sql "SELECT count(*) FROM arac.raw_messages")"
    n_conv="$(sql "SELECT count(*) FROM arac.conversations")"
    if [[ "$n_msg" == "$MESSAGES_ATTENDUS" && "$n_conv" == "$CONVERSATIONS_ATTENDUES" ]]; then
        ok "en base         $n_conv conversations, $n_msg messages — exactement ce que le manifeste annonçait"
    else
        ko "en base         $n_conv/$CONVERSATIONS_ATTENDUES conversations, $n_msg/$MESSAGES_ATTENDUS messages"
        souci=1
    fi

    # --- Le node_id est-il celui de l'entretien, jusqu'en base ? ----------
    local n_bon_noeud
    n_bon_noeud="$(sql "SELECT count(*) FROM arac.raw_messages WHERE node_id = '$POSTE'")"
    if [[ "$n_bon_noeud" == "$n_msg" ]]; then
        ok "provenance      les $n_msg messages portent le poste déclaré à l'entretien, « $POSTE »"
    else
        ko "provenance      $n_bon_noeud/$n_msg messages seulement portent « $POSTE »"; souci=1
    fi

    # --- Le rejeu n'invente rien ------------------------------------------
    rc=0
    ( cd "$ARAC_HOME" && python3 mac/arac-sync.py --conf "$conf" --jenvoie --tout ) \
        > "$BASE_TRAVAIL/synchro2.log" 2>&1 || rc=$?
    local n_msg2; n_msg2="$(sql "SELECT count(*) FROM arac.raw_messages")"
    if (( rc == 0 )) && [[ "$n_msg2" == "$n_msg" ]]; then
        ok "idempotence     un second envoi COMPLET n'ajoute aucun message ($n_msg2)"
    else
        ko "idempotence     second envoi : code $rc, $n_msg2 messages (attendu $n_msg)"; souci=1
    fi

    nonteste "le tunnel SSH — remplacé ici par une boucle locale"
    nonteste "launchd — aucun déclenchement périodique n'a été exercé"
    nonteste "l'emplacement RÉEL des données de Claude Desktop sur macOS — le corpus reproduit les formats, pas leur origine"

    if (( souci )); then
        verdict "ÉCHEC" "l'ingestion n'a pas rendu ce que le manifeste annonçait"
    else
        verdict "PROUVÉ" "$n_msg messages entrés par le vrai pont et la vraie API ; poste inconnu refusé en 403 ; rejeu complet sans doublon"
    fi
}

# ===========================================================================
# ÉTAPE 6 — voir son cerveau apprendre
# ===========================================================================
#
# L'étape qui coûte. Deux modes, et le mode gratuit doit DIRE ce qu'il n'a pas
# pu prouver plutôt que de le passer sous silence.

etape_6_apprendre() {
    exige_installation "voir son cerveau apprendre" && return
    local souci=0
    local dsn_agent; dsn_agent="$(lire_env "$ARAC_ENV_FILE" DATABASE_URL_AGENT || true)"
    if [[ -z "$dsn_agent" ]]; then
        ko "DSN du rôle des cycles introuvable"
        verdict "ÉCHEC" "le rôle des cycles n'a pas de DSN : la digestion ne peut pas démarrer"
        return
    fi

    # --- 1. La matière est là, et le cerveau la voit comme non digérée ----
    local sonde
    sonde="$( cd "$ARAC_HOME" && DATABASE_URL_AGENT="$dsn_agent" \
        "$ARAC_VENV/bin/python" "$_ICI/sonde_apprentissage.py" --racine "$ARAC_HOME" 2>&1 )"
    printf '%s\n' "$sonde" > "$BASE_TRAVAIL/sonde-avant.json"

    _sonde() { printf '%s' "$sonde" | python3 -c "
import json,sys
try: d=json.load(sys.stdin)
except Exception: print(-1); raise SystemExit
c=d
for k in sys.argv[1].split('.'):
    c = c.get(k, 0) if isinstance(c, dict) else 0
print(c)" "$1"; }

    local non_cures; non_cures="$(_sonde messages_non_cures)"
    if [[ "$non_cures" == "$MESSAGES_ATTENDUS" ]]; then
        ok "à digérer       $non_cures messages au-delà du curseur de curation : le cerveau SAIT qu'il a du travail"
    else
        ko "à digérer       $non_cures messages non curés (attendu $MESSAGES_ATTENDUS)"; souci=1
    fi

    # --- 2. La sélection choisit bien CES messages, sans rien dépenser ----
    local pack_conv pack_msg
    pack_conv="$(_sonde pack.conversations_retenues)"
    pack_msg="$(_sonde pack.messages_presentes)"
    if [[ "$pack_conv" == "$CONVERSATIONS_ATTENDUES" ]] && [[ "$pack_msg" == "$MESSAGES_ATTENDUS" ]]; then
        ok "sélection       build_pack retient les $pack_conv conversations et met $pack_msg messages sous les yeux du curateur — sans un appel payant"
    elif [[ "$pack_conv" == "$CONVERSATIONS_ATTENDUES" ]] && (( pack_msg > 0 )); then
        ok "sélection       build_pack retient les $pack_conv conversations et présente $pack_msg/$MESSAGES_ATTENDUS messages (le reste est reporté au cycle suivant : $(_sonde pack.messages_reportes))"
    else
        ko "sélection       build_pack retient $pack_conv/$CONVERSATIONS_ATTENDUES conversations, $pack_msg/$MESSAGES_ATTENDUS messages présentés"
        info "  ce que la sonde a lu : $(printf '%s' "$sonde" | tr -d '\n' | tail -c 400)"
        souci=1
    fi

    # --- 3. Le cycle RÉEL tourne, et refuse honnêtement -------------------
    #
    # On ne DÉSARME PAS le frein de dépense. C'est le point : sans clé de
    # curation, un cycle doit s'arrêter net, à coût nul, en écrivant POURQUOI.
    # Un cycle qui échouerait en silence serait indistinguable d'un cycle qui
    # n'a rien trouvé — et c'est la panne la plus coûteuse à diagnostiquer.
    systemctl start "$PREFIXE_UNITE-cycle.service" >/dev/null 2>&1
    local reste=90
    while (( reste > 0 )) && systemctl is-active --quiet "$PREFIXE_UNITE-cycle.service"; do
        sleep 1; reste=$((reste - 1))
    done
    # Une attente qui expire doit se DIRE. Sans cela, « aucun reçu en base »
    # accuse le cycle d'un silence qui n'est que de la patience manquante.
    if systemctl is-active --quiet "$PREFIXE_UNITE-cycle.service"; then
        ko "cycle réel      le cycle tourne encore après 90 s — ce qui suit ne mesure pas un cycle terminé"
        souci=1
    fi
    local recu
    recu="$(sql "SELECT coalesce(status,'?') || ' / ' || coalesce(skip_reason,'—') FROM arac.run_receipts ORDER BY id DESC LIMIT 1")"
    if [[ -n "$recu" ]]; then
        ok "cycle réel      un reçu a été écrit en base : « $recu »"
        if [[ "$recu" == skipped* ]]; then
            ok "                le frein de dépense a tenu : aucun appel payant, et la raison est écrite"
        fi
    else
        ko "cycle réel      aucun reçu en base — le cycle n'a pas atteint la base"
        journalctl -u "$PREFIXE_UNITE-cycle.service" -n 15 --no-pager 2>/dev/null \
            | while IFS= read -r l; do info "$l"; done
        souci=1
    fi

    # --- 4. LA ROUTE D'ÉCRITURE RÉELLE, gratuite ------------------------
    # Elle tourne dans les DEUX modes : c'est le seul moyen que le garde du
    # journal porte sur le chemin qui a réellement fui.
    _etape_6_route_reelle_sans_depense || souci=1

    # --- 5. Le mode complet : jusqu'à l'atome porteur d'embedding ---------
    local atomes vecteurs
    if (( MODE_COMPLET )); then
        _etape_6_mode_complet || souci=1
    fi

    sonde="$( cd "$ARAC_HOME" && DATABASE_URL_AGENT="$dsn_agent" \
        "$ARAC_VENV/bin/python" "$_ICI/sonde_apprentissage.py" --racine "$ARAC_HOME" 2>&1 )"
    printf '%s\n' "$sonde" > "$BASE_TRAVAIL/sonde-apres.json"
    atomes="$(_sonde atomes)"
    vecteurs="$(_sonde atomes_avec_vecteur)"

    dire ""
    dire "  état de la mémoire : $atomes atome(s), dont $vecteurs porteur(s) d'un vecteur,"
    dire "                       $(_sonde liens_entre_atomes) lien(s) explicite(s) entre atomes."

    if (( souci )); then
        verdict "ÉCHEC" "la chaîne de digestion est rompue avant même la frontière de dépense"
        return
    fi

    if (( MODE_COMPLET )) && (( atomes > 0 )) && [[ "$vecteurs" == "$atomes" ]]; then
        if [[ -n "$BASE_URL_EMBEDDINGS" ]]; then
            # Le verdict dit ce qu'il a vu, jamais ce qu'il aurait aimé voir :
            # la chaîne est entière, le FOURNISSEUR était doublé.
            verdict "PROUVÉ" "$atomes atome(s) produits, tous porteurs d'un vecteur de 3072 dimensions, et rappelables — fournisseur d'embeddings DOUBLÉ ($BASE_URL_EMBEDDINGS) : la chaîne est prouvée, la facturation ne l'est pas"
        else
            verdict "PROUVÉ" "$atomes atome(s) produits, tous porteurs d'un vecteur de 3072 dimensions, et rappelables"
        fi
        return
    fi

    # MODE GRATUIT — et le rapport le dit sans détour.
    nonteste "la production d'un ATOME : elle exige la curation, qui est payante"
    nonteste "le calcul d'un EMBEDDING : il exige une clé d'embeddings, qui est payante"
    nonteste "le RAPPEL par similarité : sans atome ni vecteur, il n'y a rien à rappeler"
    if (( MODE_COMPLET )); then
        verdict "ÉCHEC" "mode complet demandé, et pourtant $atomes atome(s) : la chaîne payante n'a pas abouti"
    else
        verdict "PARTIEL" "la chaîne est prouvée jusqu'à la frontière de dépense (matière vue, tranche sélectionnée, cycle exécuté, refus tracé) ; l'atome, le vecteur et le rappel restent NON TESTÉS — relancez avec --complet et une clé"
    fi
}

#: LA ROUTE D'ÉCRITURE RÉELLE, SANS DÉPENSER UN CENTIME.
#:
#: LE DÉFAUT QUE CETTE ÉTAPE FERME. `POST /v1/atoms` est la route par laquelle
#: TOUT ce que ce cerveau apprend entre — `agents/cortex/atoms_client.py` ne
#: connaît qu'elle et la supersédure. C'est aussi la seule route qui ait jamais
#: versé un souvenir dans journald. Et ce harnais ne l'empruntait JAMAIS en
#: mode gratuit : elle exige un vecteur, donc une clé payante, donc `--complet`
#: — un mode dont le fichier lui-même écrit qu'il « n'a jamais tourné avec de
#: vraies clés ». Le garde du §13.10 cherchait donc une fuite sur un chemin que
#: personne n'avait pris, et rendait « ✓ » à chaque passage.
#:
#: CE QU'ON DOUBLE, ET CE QU'ON NE DOUBLE PAS. On ne réécrit rien du produit :
#: l'unité `arac-<base>-api.service` reste celle du bootstrap, son ExecStart
#: reste `uvicorn app.main:app`, sa sortie part dans SON journal. Ce qu'on
#: remplace, c'est le FOURNISSEUR PAYANT au bout du fil — vingt lignes qui
#: rendent un vecteur déterministe de 3072 flottants sur la boucle locale. Le
#: chemin d'ARAC, lui, est joué en entier : validation Pydantic, `embed()`,
#: INSERT, déclencheur d'archivage, avertissements, `audit_log`, journalisation.
#:
#: CE QUE ÇA NE PROUVE PAS, et c'est dit : un vecteur factice ne mesure aucune
#: similarité. Le rappel par le SENS reste NON TESTÉ, comme avant. Ce qui est
#: prouvé ici, c'est que la route d'écriture s'exécute et que RIEN de ce qu'on
#: lui confie ne ressort dans le journal de la machine.
_etape_6_route_reelle_sans_depense() {
    local jeton feuille temoin_valeur temoin_pourquoi temoin_cle rep code corps
    local dbl="$BASE_TRAVAIL/double_embeddings.py"

    temoin_cle="temoin-route-$RUN"
    temoin_valeur="TEMOINROUTE$RUN la posologie est de 400 mg matin et soir"
    temoin_pourquoi="POURQUOIROUTE$RUN parce que le cardiologue l'a demandé en mars"

    # --- 1. Le double, sur un port constaté libre -------------------------
    if ! garde_port_libre "$PORT_DOUBLE_EMB" "le double d'embeddings" >/dev/null 2>&1; then
        nonteste "la route d'écriture réelle — aucun port libre pour le double d'embeddings"
        return 0
    fi
    cat > "$dbl" <<'PYDOUBLE'
"""Double DÉTERMINISTE du fournisseur d'embeddings, boucle locale seulement.

Il ne double pas ARAC : il double ce qu'ARAC paie. Même valeur -> même vecteur,
donc deux passages du harnais rendent le même contenu de base.
"""
import hashlib, json, math, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

DIM = 3072

def vecteur(texte):
    x = int.from_bytes(hashlib.sha256(texte.encode("utf-8")).digest(), "big") % (2**61 - 1) or 1
    out = []
    for _ in range(DIM):
        x = (x * 6364136223846793005 + 1442695040888963407) % (2**64)
        out.append(((x >> 11) / float(2**53)) - 0.5)
    n = math.sqrt(sum(v * v for v in out)) or 1.0
    return [v / n for v in out]

class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        corps = json.loads(self.rfile.read(n) or b"{}")
        entree = corps.get("input")
        items = entree if isinstance(entree, list) else [entree]
        charge = json.dumps({
            "object": "list",
            "data": [{"object": "embedding", "index": i, "embedding": vecteur(str(t))}
                     for i, t in enumerate(items)],
            "model": corps.get("model", "text-embedding-3-large"),
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(charge)))
        self.end_headers()
        self.wfile.write(charge)

HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
PYDOUBLE
    python3 "$dbl" "$PORT_DOUBLE_EMB" > "$BASE_TRAVAIL/double_embeddings.log" 2>&1 &
    DOUBLE_EMB_PID=$!
    # Donner du texte à `grep -q` PAR UNE CHAÎNE, jamais par un tuyau : sous
    # `pipefail`, `grep -q` ferme le tuyau, le producteur meurt de SIGPIPE et la
    # condition rend 141 ALORS QUE LE MOTIF EST LÀ. C'est la règle du dépôt
    # (`tests/test_le_juge_ne_tire_pas_au_sort.py`) — on capture, puis on
    # cherche.
    local reste=30 sockets=""
    while (( reste > 0 )); do
        sockets="$(ss -tln 2>/dev/null || true)"
        grep -q "127.0.0.1:$PORT_DOUBLE_EMB " <<<"$sockets" && break
        sleep 0.2; reste=$((reste - 1))
    done
    if ! grep -q "127.0.0.1:$PORT_DOUBLE_EMB " <<<"$sockets"; then
        nonteste "la route d'écriture réelle — le double d'embeddings n'a pas démarré"
        return 0
    fi
    ok "double          fournisseur d'embeddings doublé sur 127.0.0.1:$PORT_DOUBLE_EMB — le produit, lui, n'est pas doublé"

    # --- 2. La clé entre par le chemin DOCUMENTÉ --------------------------
    # `--only cles` est le geste que la documentation prescrit ; on ne réécrit
    # pas l'unité à la main. `OPENAI_BASE_URL` est ajoutée au fichier
    # d'environnement de l'unité : c'est la variable que le client OpenAI lit
    # lui-même, et elle DIT où va l'appel.
    python3 - "$ARAC_ENV_FILE" "$PORT_DOUBLE_EMB" <<'PYENV'
import os, pathlib, sys
chemin, port = pathlib.Path(sys.argv[1]), sys.argv[2]
poses = {
    "ARAC_EMBEDDINGS_API_KEY": "sk-double-local-acceptation",
    "OPENAI_BASE_URL": f"http://127.0.0.1:{port}/v1",
}
lignes = [l for l in chemin.read_text(encoding="utf-8").splitlines()
          if l.split("=", 1)[0].strip() not in poses]
lignes += [f"{k}={v}" for k, v in poses.items()]
chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
os.chmod(chemin, 0o600)
PYENV
    ( cd "$ARAC_HOME" && _env_bootstrap ./bootstrap/bootstrap.sh --only cles --yes --no-color ) \
        >> "$BASE_TRAVAIL/bootstrap.log" 2>&1 || true
    systemctl restart "$PREFIXE_UNITE-api.service" >/dev/null 2>&1
    if [[ "$(attendre_http "$URL_API/healthz" 90)" != "200" ]]; then
        nonteste "la route d'écriture réelle — l'API n'est pas revenue après la pose de la clé doublée"
        return 0
    fi

    # --- 3. L'ÉCRITURE, par la vraie route --------------------------------
    jeton="$(lire_env "$ARAC_ENV_FILE" ARAC_API_BEARER_TOKEN || true)"
    feuille="$(sql "SELECT path FROM arac.scopes WHERE depth > 0 ORDER BY path LIMIT 1")"
    if [[ -z "$jeton" || -z "$feuille" ]]; then
        nonteste "la route d'écriture réelle — jeton ou feuille de taxonomie introuvable"
        return 0
    fi
    rep="$(curl -s -m 60 -w '\n%{http_code}' -X POST -H 'Content-Type: application/json' \
        -H "Authorization: Bearer $jeton" \
        --data "$(python3 -c "
import json, sys
print(json.dumps({
  'kind': 'decision', 'scope': sys.argv[1], 'key': sys.argv[2],
  'value': sys.argv[3], 'rationale': sys.argv[4],
  'confidence': 'producer', 'node_id': sys.argv[5],
}))" "$feuille" "$temoin_cle" "$temoin_valeur" "$temoin_pourquoi" "$POSTE")" \
        "$URL_API/v1/atoms")"
    code="$(printf '%s' "$rep" | tail -n1)"
    corps="$(printf '%s' "$rep" | sed '$d')"
    if [[ "$code" != "201" ]]; then
        nonteste "la route d'écriture réelle — POST /v1/atoms a rendu $code (double d'embeddings)"
        info "  $(printf '%s' "$corps" | head -c 240)"
        return 0
    fi
    FEUILLE_TEMOIN="$feuille"
    ok "route réelle    POST /v1/atoms rend 201 — la route par laquelle TOUT ce que ce cerveau apprend entre est enfin exercée par ce harnais"

    # Une seconde écriture sur la MÊME (domaine, clé) : le 409, puis la
    # supersédure — les deux autres portes d'`atoms_client`.
    curl -s -o /dev/null -m 60 -X POST -H 'Content-Type: application/json' \
        -H "Authorization: Bearer $jeton" \
        --data "$(python3 -c "
import json, sys
print(json.dumps({'kind':'decision','scope':sys.argv[1],'key':sys.argv[2],
  'value':sys.argv[3]+' (bis)','rationale':sys.argv[4],
  'confidence':'producer','node_id':sys.argv[5]}))" \
        "$feuille" "$temoin_cle" "$temoin_valeur" "$temoin_pourquoi" "$POSTE")" \
        "$URL_API/v1/atoms" 2>/dev/null

    # --- 3bis. LES ROUTES DE LECTURE, EMPRUNTÉES POUR DE VRAI -------------
    #
    # POURQUOI CE BLOC EXISTE. Ce harnais appelait déjà
    # `GET /v1/dashboard/search` — SANS jeton, pour vérifier le 401 (étape 5).
    # La route était donc ATTEINTE à chaque acceptation, et son corps n'a
    # jamais été exécuté une seule fois. Pendant ce temps, `dashboard.py`
    # livrait `journal.sha8()` sans avoir importé `journal` : les deux
    # dernières instructions de `atoms_by_scope` et de `search` levaient
    # `NameError`, les deux routes rendaient 500 sur un cerveau sain, et
    # `make acceptance` rendait « 0 en échec » trois fois de suite.
    #
    # « Atteindre » n'est pas « emprunter ». Une requête arrêtée par
    # l'authentification ne dit rien du code de la route. On l'emprunte donc
    # ici, avec un jeton valide, sur le cerveau réel, JUSTE APRÈS avoir écrit
    # un souvenir par la vraie route — et on exige que ce souvenir-là se
    # relise par les routes de lecture. Un 200 sur une liste vide prouverait
    # que la fonction ne lève pas ; il ne prouverait pas qu'elle lit.
    local echec_lecture=0 route code corps
    # `search` cherche dans la VALEUR (ILIKE sur `value`), jamais dans la clé :
    # interroger sur `$temoin_cle` rendrait une liste vide et prouverait
    # seulement que la fonction ne lève pas. On interroge donc sur un mot du
    # souvenir lui-même, et on exige la clé DANS LA RÉPONSE.
    for route in "atoms_by_scope?scope=$feuille&limit=50" \
                 "search?q=posologie" \
                 "scopes_summary" "timeline?days=7" "foundations_state" \
                 "ingest_stats"; do
        code="$(curl -s -o "$BASE_TRAVAIL/lecture.json" -m 30 -w '%{http_code}' \
            -H "Authorization: Bearer $jeton" \
            "$URL_API/v1/dashboard/${route}" 2>/dev/null)"
        if [[ "$code" != "200" ]]; then
            ko "route de lecture GET /v1/dashboard/${route%%\?*} rend $code (attendu 200)"
            info "  $(head -c 200 "$BASE_TRAVAIL/lecture.json" 2>/dev/null)"
            dire "                  journalctl -u $PREFIXE_UNITE-api.service --since '-2 min' | tail -40"
            echec_lecture=1
        fi
    done
    # Le souvenir écrit à l'instant doit RESSORTIR par les deux routes qui le
    # cherchent. C'est ce qui distingue « la fonction s'exécute » de « la
    # fonction rend la mémoire ».
    corps="$(curl -s -m 30 -H "Authorization: Bearer $jeton" \
        "$URL_API/v1/dashboard/atoms_by_scope?scope=$feuille&limit=50" 2>/dev/null)"
    if ! grep -qF "$temoin_cle" <<<"$corps"; then
        ko "route de lecture GET /v1/dashboard/atoms_by_scope rend 200 mais SANS le souvenir écrit à l'instant ($temoin_cle)"
        echec_lecture=1
    fi
    corps="$(curl -s -m 30 -H "Authorization: Bearer $jeton" \
        "$URL_API/v1/dashboard/search?q=posologie" 2>/dev/null)"
    if ! grep -qF "$temoin_cle" <<<"$corps"; then
        ko "route de lecture GET /v1/dashboard/search ne retrouve pas le souvenir écrit à l'instant ($temoin_cle)"
        echec_lecture=1
    fi
    if (( echec_lecture )); then
        return 1
    fi
    ok "routes de lecture les six routes du tableau de bord sont EMPRUNTÉES avec un jeton valide, et les deux qui cherchent rendent le souvenir écrit à l'instant"

    # --- 4. LE JOURNAL DE L'UNITÉ, RELU MAINTENANT ------------------------
    # Pas après la désinstallation : ici, pendant que le cerveau vit, sur les
    # témoins que la route vient TOUT JUSTE d'écrire. Un garde qui attend la
    # fin cherche ce qui a déjà pu être purgé.
    sleep 1
    local fuite
    fuite="$(journalctl --quiet -u "$PREFIXE_UNITE-api.service" --no-pager -o cat --since '-5 min' 2>/dev/null \
             | grep -F -e "TEMOINROUTE$RUN" -e "POURQUOIROUTE$RUN" -e "$temoin_cle" -e "$feuille" \
             | head -5)"
    if [[ -z "$fuite" ]]; then
        ok "journal         après une écriture RÉELLE, le journal de l'API ne rend ni le souvenir, ni son pourquoi, ni sa clé, ni son domaine"
    else
        ko "journal         LA ROUTE D'ÉCRITURE VERSE ENCORE LA MÉMOIRE DANS LE JOURNAL DE LA MACHINE :"
        while IFS= read -r l; do info "  $(printf '%.200s' "$l")"; done <<<"$fuite"
        dire "                  journalctl -u $PREFIXE_UNITE-api.service | grep '$temoin_cle'"
        dire "                  Le remède est dans app/journal.py : empreinte, jamais valeur."
        return 1
    fi

    nonteste "le RAPPEL par le sens — le vecteur du double est déterministe, pas sémantique"
    return 0
}

#: LA CHAÎNE PAYANTE, DE BOUT EN BOUT.
#:
#: NON EXERCÉ à ce jour : ce bloc n'a jamais tourné avec de vraies clés. Il est
#: écrit, il est lisible, et cette ligne dit qu'il n'est pas prouvé. Le taire
#: aurait été le présenter comme éprouvé.
_etape_6_mode_complet() {
    if [[ -z "$CLE_EMBEDDINGS" ]]; then
        ko "mode complet demandé sans clé d'embeddings (--cle-embeddings)"
        return 1
    fi

    # La clé entre par le chemin documenté : le fichier d'environnement, puis
    # `--only cles` qui repose le pont de vocabulaire (ARAC_EMBEDDINGS_API_KEY
    # -> OPENAI_API_KEY), puis un redémarrage de l'API.
    python3 - "$ARAC_ENV_FILE" ARAC_EMBEDDINGS_API_KEY <<PY
import os, pathlib, sys
chemin, cle, valeur = pathlib.Path(sys.argv[1]), sys.argv[2], """$CLE_EMBEDDINGS"""
lignes = [l for l in chemin.read_text(encoding="utf-8").splitlines()
          if l.split("=", 1)[0].strip() != cle]
lignes.append(f"{cle}={valeur.strip()}")
chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
os.chmod(chemin, 0o600)
PY
    ( cd "$ARAC_HOME" && _env_bootstrap ./bootstrap/bootstrap.sh --only cles --yes --no-color ) \
        >> "$BASE_TRAVAIL/bootstrap.log" 2>&1

    # LE FOURNISSEUR PEUT ÊTRE DOUBLÉ ; LE PRODUIT, JAMAIS. (Le pourquoi est
    # dans l'aide, à `--embeddings-base-url` : un mode qu'on ne peut rejouer
    # qu'en payant n'est pas rejoué, donc il pourrit.)
    if [[ -n "$BASE_URL_EMBEDDINGS" ]]; then
        printf 'OPENAI_BASE_URL=%s\n' "$BASE_URL_EMBEDDINGS" >> "$ARAC_ENV_FILE"
        chmod 0600 "$ARAC_ENV_FILE"
        info "  fournisseur d'embeddings DOUBLÉ ($BASE_URL_EMBEDDINGS) : la chaîne"
        info "  est jouée en entier, la FACTURATION n'est pas prouvée."
    fi

    systemctl restart "$PREFIXE_UNITE-api.service" >/dev/null 2>&1
    [[ "$(attendre_http "$URL_API/healthz" 90)" == "200" ]] || {
        ko "l'API n'est pas revenue après l'ajout de la clé"; return 1; }

    # Un atome, par la VRAIE route : POST /v1/atoms embarque l'appel
    # d'embedding. Le scope choisi est une FEUILLE — un atome posé sur une
    # racine existe et ne remonte jamais.
    # Le jeton est relu ICI : `etape_5` l'avait dans une variable LOCALE, et
    # une variable locale ne traverse pas une fonction. Sans cette ligne, les
    # deux appels ci-dessous partiraient avec un en-tête vide et repartiraient
    # en 401 — un mode complet qui échoue pour une raison qui n'a rien à voir
    # avec ce qu'il prétend mesurer.
    local feuille reponse jeton_api code_atome corps_atome
    jeton_api="$(lire_env "$ARAC_ENV_FILE" ARAC_API_BEARER_TOKEN || true)"
    if [[ -z "$jeton_api" ]]; then
        ko "jeton de l'API introuvable : le mode complet ne peut pas parler à l'API"
        return 1
    fi
    feuille="$(sql "SELECT path FROM arac.scopes WHERE depth > 0 ORDER BY path LIMIT 1")"
    # LE PREMIER APPEL PAYANT DE TOUT LE HARNAIS. On capture son code HTTP :
    # c'est ici que l'argent part, et une dépense dont on ne sait pas si elle a
    # été acceptée n'est pas une preuve, c'est une facture.
    #
    # DEUX MOTS QUI N'EXISTAIENT PAS, ET QUI RENDAIENT CE MODE INJOUABLE.
    # Ce corps portait `kind: 'fact'` et `confidence: 'high'` — absents des
    # énumérations (app/schemas/kind.py, app/schemas/atom.py). Mesuré contre
    # une API vivante : 422 sur ce corps-là, 201 sur celui-ci.
    reponse="$(curl -s -m 60 -w '\n%{http_code}' -X POST -H 'Content-Type: application/json' \
        -H "Authorization: Bearer $jeton_api" \
        --data "$(python3 -c "
import json,sys
print(json.dumps({
  'kind': 'decision', 'scope': sys.argv[1],
  'key': 'acceptation-retention-sauvegardes',
  'value': \"La rétention des sauvegardes passe de 14 à 30 jours, et une restauration complète est rejouée chaque mois.\",
  'confidence': 'producer', 'node_id': sys.argv[2],
  'rationale': \"Décision prise dans le corpus d'acceptation ${JETON_CORPUS}.\",
}))" "$feuille" "$POSTE")" \
        "$URL_API/v1/atoms")"
    code_atome="$(printf '%s' "$reponse" | tail -n1)"
    corps_atome="$(printf '%s' "$reponse" | sed '$d')"
    local atome_id
    atome_id="$(printf '%s' "$corps_atome" | python3 -c "import json,sys;print(json.load(sys.stdin).get('id',''))" 2>/dev/null)"
    if [[ -z "$atome_id" ]]; then
        ko "création d'atome refusée (HTTP $code_atome) : $(printf '%s' "$corps_atome" | head -c 300)"
        return 1
    fi
    ok "atome           créé par POST /v1/atoms (HTTP $code_atome) — $atome_id"

    local dims
    dims="$(sql "SELECT vector_dims(embedding::vector) FROM arac.memory_atoms WHERE id='$atome_id'")"
    if [[ "$dims" == "3072" ]]; then
        ok "vecteur         l'atome porte un embedding de $dims dimensions"
    else
        ko "vecteur         dimensions lues : ${dims:-aucune}"; return 1
    fi

    # LE RAPPEL — et le champ s'appelle `k`, pas `limit`.
    #
    # Cette requête portait `{"query": …, "limit": 5}`. `RecallRequest`
    # (app/schemas/atom.py) déclare `k`, et son `model_config` porte
    # `extra="forbid"` : un champ inconnu ne se contente pas d'être ignoré, il
    # fait rendre 422 AVANT que la moindre recherche ait lieu. L'étape ne
    # prouvait donc RIEN de ce qu'elle annonce — et elle ne le prouvait qu'en
    # mode `--complet`, c'est-à-dire seulement après avoir payé l'embedding de
    # l'atome. C'est la pire forme de dépense : elle achète une réponse qu'on
    # n'a même pas demandée.
    #
    # ON NE CROIT PLUS UN CORPS SUR PAROLE : on capture le CODE HTTP. Un
    # `grep` sur le corps d'un 422 échoue de la même façon qu'un rappel qui ne
    # ramène rien — deux causes très différentes, un seul message. Le code
    # sépare « la requête était mal formée » de « le rappel n'a rien ramené »,
    # et c'est la règle que ce dépôt s'applique partout ailleurs : un corps ne
    # prouve rien tant qu'on ne sait pas ce que le serveur a répondu.
    local rappel code_rappel corps_rappel
    rappel="$(curl -s -m 60 -w '\n%{http_code}' -X POST -H 'Content-Type: application/json' \
        -H "Authorization: Bearer $jeton_api" \
        --data '{"query":"combien de temps garde-t-on les sauvegardes ?","k":5}' \
        "$URL_API/v1/atoms/recall")"
    code_rappel="$(printf '%s' "$rappel" | tail -n1)"
    corps_rappel="$(printf '%s' "$rappel" | sed '$d')"
    if [[ "$code_rappel" != "200" ]]; then
        ko "rappel          POST /v1/atoms/recall a rendu $code_rappel, pas 200 —
                  la requête n'a pas été acceptée, donc RIEN n'a été mesuré.
                  $(printf '%s' "$corps_rappel" | head -c 300)"
        return 1
    fi
    if grep -q "$atome_id" <<<"$corps_rappel"; then
        ok "rappel          200, et une question posée en mots ramène cet atome par similarité"
    else
        ko "rappel          200, mais l'atome n'est pas revenu : $(printf '%s' "$corps_rappel" | head -c 200)"
        return 1
    fi
    return 0
}

# ===========================================================================
# ÉTAPE 7 — utiliser son cockpit
# ===========================================================================
#
# « Le cockpit répond 200 » ne prouve rien : le jour de l'incident, un
# /healthz à 200 était servi par un usurpateur qui avait pris le port. Cette
# étape établit quatre choses distinctes :
#
#   1. la socket appartient bien à NOTRE unité (pas « quelqu'un répond ») ;
#   2. le gardien de session existe réellement (401 sans cookie) ;
#   3. l'authentification complète passe — mot de passe ET second facteur ;
#   4. les chiffres servis CONCORDENT avec la base, par la propre requête de
#      preuve du cockpit, rejouée à la main.

etape_7_cockpit() {
    exige_installation "utiliser son cockpit" && return
    local souci=0

    # --- 1. Qui tient ce port ? -------------------------------------------
    socket_de_l_unite "$PORT_COCKPIT" "$PREFIXE_UNITE-cockpit.service"
    case "$?" in
        0) ok "propriété       la socket $PORT_COCKPIT appartient au processus de $PREFIXE_UNITE-cockpit" ;;
        1) ko "propriété       le port $PORT_COCKPIT est tenu par un AUTRE processus — ou par personne"
           souci=1 ;;
        2) attn "propriété       impossible de savoir à qui appartient la socket (ss sans droits)" ;;
    esac

    local code; code="$(attendre_http "$URL_COCKPIT/cc/healthz" 90)"
    if [[ "$code" == "200" ]]; then
        ok "vivant          /cc/healthz rend $code"
    else
        ko "vivant          /cc/healthz rend $code"
        journalctl -u "$PREFIXE_UNITE-cockpit.service" -n 12 --no-pager 2>/dev/null \
            | while IFS= read -r l; do info "$l"; done
        verdict "ÉCHEC" "le cockpit ne répond pas sur $PORT_COCKPIT"
        return
    fi

    # --- 2. Le gardien existe-t-il vraiment ? -----------------------------
    code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$URL_COCKPIT/cc/v1/metrics")"
    if [[ "$code" == "401" ]]; then
        ok "gardien         sans session, /cc/v1/metrics rend 401 — la lecture est réellement fermée"
    else
        ko "gardien         sans session, /cc/v1/metrics rend $code (attendu 401)"; souci=1
    fi

    # --- 3. L'authentification complète -----------------------------------
    local provisionne
    provisionne="$(curl -s -m 10 "$URL_COCKPIT/cc/healthz" \
        | python3 -c "import json,sys;p=json.load(sys.stdin)['provisioned'];print(int(all(p.values())))" 2>/dev/null)"
    if [[ "$provisionne" != "1" ]]; then
        ko "identifiants    le cockpit se déclare NON PROVISIONNÉ : il refusera toute connexion (503)"
        info "  Le bootstrap écrit ARAC_CC_SESSION_SECRET / ARAC_CC_ADMIN_PASSWORD_HASH /"
        info "  ARAC_CC_TOTP_SECRET ; le cockpit lit CC_SESSION_SECRET / CC_ADMIN_PASSWORD_HASH /"
        info "  CC_TOTP_SECRET. Les deux vocabulaires ne se rencontrent pas."
        _remede_documente_cockpit || { verdict "ÉCHEC" "le cockpit ne peut pas être ouvert"; return; }
        souci=1
    fi

    local mdp totp
    mdp="$(_mot_de_passe_engendre)"
    totp="$(lire_env "$ARAC_SECRETS_COCKPIT" ARAC_CC_TOTP_SECRET || true)"
    if [[ -z "$mdp" || -z "$totp" ]]; then
        ko "identifiants    mot de passe ou secret TOTP introuvables"
        verdict "ÉCHEC" "impossible de se connecter au cockpit sans intervention humaine"
        return
    fi

    local code_totp cookie entetes
    # TOTP RFC 6238 tel que `control_center/security.py` le vérifie :
    # HMAC-SHA1, pas de 30 s, six chiffres. On le recalcule ici plutôt que
    # d'importer le module du cockpit — sinon le test et le code vérifié
    # partageraient leur erreur, et le second facteur serait prouvé par
    # lui-même.
    code_totp="$(python3 - "$totp" <<'PY'
import base64, hmac, hashlib, struct, sys, time
brut = sys.argv[1].strip().upper()
secret = base64.b32decode(brut + "=" * ((8 - len(brut) % 8) % 8))
compteur = int(time.time()) // 30
h = hmac.new(secret, struct.pack(">Q", compteur), hashlib.sha1).digest()
decalage = h[-1] & 0x0F
valeur = struct.unpack(">I", h[decalage:decalage + 4])[0] & 0x7FFFFFFF
print(f"{valeur % 1000000:06d}")
PY
)"

    _tenter_connexion() {
        entetes="$(curl -s -i -m 15 -X POST \
            --data-urlencode "password=$mdp" --data-urlencode "totp_code=$code_totp" \
            "$URL_COCKPIT/cc/login")"
        cookie="$(grep -i -m1 '^set-cookie: cc_session=' <<<"$entetes" \
            | sed 's/.*cc_session=\([^;]*\).*/\1/' | tr -d '\r')"
        [[ -n "$cookie" ]]
    }

    if ! _tenter_connexion; then
        local ligne1; ligne1="$(printf '%s' "$entetes" | head -1 | tr -d '\r')"
        ko "connexion       refusée : $ligne1"
        # UN 500 SUR LE FORMULAIRE DE CONNEXION A UNE CAUSE CONNUE, ET IL FAUT
        # LA NOMMER PLUTÔT QUE DE RENDRE « 500 ».
        # `/cc/login` est la SEULE route non-GET du cockpit, et la seule à lire
        # un formulaire. Starlette délègue l'analyse d'un `multipart/form-data`
        # à `python-multipart` : sans lui, `await request.form()` lève, et
        # l'utilisateur reçoit un 500 en texte brut, sans un mot dans le
        # journal applicatif. La panne est invisible partout où ce paquet est
        # déjà installé — c'est-à-dire sur la machine de qui a écrit le code.
        if [[ "$ligne1" == *500* ]] && ! "$ARAC_VENV/bin/python" -c 'import multipart' 2>/dev/null; then
            _remede_dependance_multipart && _tenter_connexion
        fi
    fi

    if [[ -n "$cookie" ]]; then
        ok "connexion       mot de passe + code à six chiffres acceptés, session établie"
    else
        printf '%s' "$entetes" | tail -3 | while IFS= read -r l; do info "$l"; done
        verdict "ÉCHEC" "l'authentification du cockpit échoue"
        return
    fi

    # --- 4. LES CHIFFRES CONCORDENT-ILS AVEC LA BASE ? --------------------
    #
    # On ne se contente pas de lire une valeur : on demande au cockpit SA
    # PREUVE — la requête SQL qu'il a exécutée — et on la rejoue soi-même
    # contre la base. Un cockpit qui ne peut pas être contredit ne mérite pas
    # d'être cru.
    local cle="pipeline_messages_absorbed_24h"
    local valeur_cockpit
    valeur_cockpit="$(curl -s -m 20 -H "Cookie: cc_session=$cookie" \
        "$URL_COCKPIT/cc/v1/metrics/$cle" \
        | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('value'))" 2>/dev/null)"
    local en_base
    en_base="$(sql "SELECT count(*) FROM arac.raw_messages WHERE received_at > now() - interval '24 hours'")"

    if [[ "$valeur_cockpit" == "$en_base" ]] && [[ "$en_base" == "$MESSAGES_ATTENDUS" ]]; then
        ok "concordance     « $cle » = $valeur_cockpit, et la base en compte $en_base — les $MESSAGES_ATTENDUS messages de CE cerveau"
    else
        ko "concordance     le cockpit dit $valeur_cockpit, la base dit $en_base, le corpus annonçait $MESSAGES_ATTENDUS"
        souci=1
    fi

    local preuve_sql
    preuve_sql="$(curl -s -m 20 -H "Cookie: cc_session=$cookie" \
        "$URL_COCKPIT/cc/v1/evidence/$cle" \
        | python3 -c "import json,sys;print(json.load(sys.stdin).get('sql',''))" 2>/dev/null)"
    if [[ -n "$preuve_sql" ]]; then
        ok "preuve          le cockpit livre le SQL de sa mesure : elle est rejouable depuis un terminal"
    else
        ko "preuve          le cockpit ne livre aucun SQL pour « $cle »"; souci=1
    fi

    # --- 4bis. LE COCKPIT MONTRE-T-IL QUELQUE CHOSE ? ---------------------
    #
    # C'EST LE CONTRÔLE QUI MANQUAIT, ET IL A COÛTÉ SEPT ROUTES.
    #
    # Tout ce qui précède emprunte CINQ routes du cockpit : `/cc/healthz`,
    # `/cc/login`, `/cc/v1/metrics`, `/cc/v1/metrics/{clé}` et
    # `/cc/v1/evidence/{clé}`. Le cockpit en sert soixante-neuf. Les
    # soixante-quatre autres n'étaient empruntées par personne — et sept
    # d'entre elles, dont la fiche d'un souvenir, l'arbre de la taxonomie et
    # la liste des conversations, étaient MORTES sur toute installation issue
    # du chemin documenté, en rendant HTTP 200.
    #
    # LA LEÇON, ET LA RAISON DE CE BLOC : un 200 sur une réponse vide ne
    # prouve que l'absence d'exception. Le cockpit ne LÈVE pas, il DIT — il
    # rend `state: "unavailable"` avec une empreinte d'erreur, sous un 200
    # parfaitement vert. Un harnais qui lit le code et pas le corps voit un
    # cockpit en pleine santé pendant qu'il ne montre rien.
    #
    # `parcours_cockpit.py` emprunte donc TOUTES les routes servies — la liste
    # vient de l'application elle-même, pas d'un tableau écrit à la main — et
    # exige de chacune qu'elle ressorte ce que CE cerveau contient : l'atome
    # de l'étape 6, sa clé, l'uid d'une conversation de l'étape 5, le domaine
    # où l'atome est rangé. Deux passes, parce que l'absence de
    # `config/projects.toml` EST le cas nominal et qu'elle a tué cinq routes :
    # une SANS le fichier (le seul état qu'un nouvel arrivant connaisse), une
    # AVEC.
    _etape_7_parcours_du_cockpit "$cookie" || souci=1

    # --- 5. ET SI C'ÉTAIT UN USURPATEUR ? ---------------------------------
    #
    # Le contrôle décisif, et il coûte deux secondes : on arrête NOTRE unité.
    # Si le port continue de répondre, c'est que quelqu'un d'autre le tenait
    # depuis le début — et tout ce qui précède portait sur le mauvais service.
    systemctl stop "$PREFIXE_UNITE-cockpit.service" >/dev/null 2>&1
    # `systemctl stop` rend la main quand l'unité est morte, pas quand le noyau
    # a rendu le port : on ATTEND le silence, on ne le suppose pas au bout de
    # deux secondes de sommeil.
    attendre_port_libre "$PORT_COCKPIT" 20 || true
    local code_muet
    code_muet="$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$URL_COCKPIT/cc/healthz" 2>/dev/null)"
    systemctl start "$PREFIXE_UNITE-cockpit.service" >/dev/null 2>&1
    local code_revenu; code_revenu="$(attendre_http "$URL_COCKPIT/cc/healthz" 90)"
    if [[ "$code_muet" == "000" && "$code_revenu" == "200" ]]; then
        ok "non-usurpation  unité arrêtée → le port se tait ; unité relancée → il répond. C'est bien NOTRE cockpit."
    elif [[ "$code_muet" != "000" ]]; then
        ko "non-usurpation  unité arrêtée, le port répond encore ($code_muet) — un autre service tient $PORT_COCKPIT"
        souci=1
    else
        # LE MOTIF COMPTE AUTANT QUE LE VERDICT. Le port S'EST tu : il est donc
        # bien à nous. Ce qui a manqué, c'est le retour du cockpit — dire
        # « usurpation » ici enverrait chercher un intrus qui n'existe pas.
        ko "non-usurpation  le port s'est tu à l'arrêt (il est donc bien à nous), mais le cockpit n'est pas revenu en 90 s : $code_revenu"
        journalctl -u "$PREFIXE_UNITE-cockpit.service" -n 10 --no-pager 2>/dev/null \
            | while IFS= read -r l; do info "  $l"; done
        souci=1
    fi

    if (( ${#INTERVENTIONS[@]} )); then
        verdict "ÉCHEC" "le cockpit fonctionne, mais il a fallu un geste manuel que le bootstrap ne pose pas : le critère « sans intervention » n'est pas tenu"
    elif (( souci )); then
        verdict "ÉCHEC" "le cockpit répond mais ne dit pas la vérité sur ce cerveau"
    else
        verdict "PROUVÉ" "socket appartenant à notre unité, gardien réel (401), connexion par mot de passe + TOTP, « $cle » = $valeur_cockpit concordant avec la base, et le port se tait quand l'unité s'arrête"
    fi
}

#: LE PARCOURS DE CONTENU — soixante-sept routes, deux passes, et un compte.
#:
#: Rend 0 si toutes les routes empruntées ont montré quelque chose. Il ne
#: CONDAMNE jamais faute de matière : sur un cerveau sans atome ni
#: conversation, il n'y a rien à ressortir, et il le DIT (« NON TESTÉ »)
#: plutôt que d'accuser le cockpit de ne pas montrer ce qui n'existe pas.
_etape_7_parcours_du_cockpit() { # cookie
    local cookie="$1"
    local ctx="$BASE_TRAVAIL/contexte-cockpit.json"
    local sortie rc=0

    # --- Les marques de CE cerveau, lues dans SA base ---------------------
    #
    # On les LIT plutôt que de les supposer : le parcours doit exiger que le
    # cockpit ressorte ce que la base contient réellement, pas ce que le
    # harnais croit y avoir mis.
    local a_id a_cle a_scope conv lie
    conv="$(sql "SELECT conversation_uid FROM arac.conversations ORDER BY created_at LIMIT 1")"
    # ON PRÉFÈRE UN ATOME QUI DÉCLARE CETTE CONVERSATION : c'est lui qui permet
    # d'exiger de `…/story` qu'elle ressorte la naissance du souvenir. À défaut
    # — un atome entré par `POST /v1/atoms` n'en déclare aucune —, on prend le
    # plus récent et on n'exige plus l'uid : accuser une route de taire ce que
    # la base ne contient pas serait un faux rouge, et un faux rouge désarme un
    # garde plus sûrement qu'un trou.
    a_id="$(sql "SELECT id FROM arac.memory_atoms
                  WHERE kind <> 'agent_message'
                    AND source_ref->>'conversation_uid' = '$conv'
                  ORDER BY created_at DESC LIMIT 1")"
    lie=true
    if [[ -z "$a_id" ]]; then
        lie=false
        a_id="$(sql "SELECT id FROM arac.memory_atoms WHERE kind <> 'agent_message' ORDER BY created_at DESC LIMIT 1")"
    fi
    a_cle="$(sql "SELECT key FROM arac.memory_atoms WHERE id = '$a_id'")"
    a_scope="$(sql "SELECT scope FROM arac.memory_atoms WHERE id = '$a_id'")"

    if [[ -z "$a_id" || -z "$conv" ]]; then
        attn "parcours        NON TESTÉ — ce cerveau ne porte pas encore d'atome ($a_id) ou de conversation ($conv) :"
        info "  il n'y a rien à exiger d'une fiche de souvenir sur un cerveau vide. Le parcours"
        info "  ne condamne pas faute de matière — il le dit."
        return 0
    fi

    python3 - "$ctx" "$a_id" "$a_cle" "$a_scope" "$conv" "$CERVEAU" "$ARAC_DB" "$lie" <<'PYCTX'
import json, sys
chemin, a_id, a_cle, a_scope, conv, cerveau, base, lie = sys.argv[1:9]
json.dump({
    "atome_id": a_id, "atome_cle": a_cle, "scope": a_scope,
    "conversation_uid": conv, "cerveau": cerveau, "base": base,
    "atome_lie_a_la_conversation": lie == "true",
    "metrique": "pipeline_messages_absorbed_24h",
    "projet_id": "parcours", "projet_label": "Parcours",
}, open(chemin, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
PYCTX

    if [[ "$lie" != "true" ]]; then
        info "  parcours : aucun atome ne DÉCLARE la conversation « $conv » (l'atome témoin"
        info "  est entré par POST /v1/atoms, qui n'en cite aucune). « l'histoire d'un"
        info "  souvenir » est donc exigée sur l'atome seul, pas sur sa naissance."
    fi

    # --- PASSE 1 : SANS config/projects.toml ------------------------------
    #
    # C'est l'état de TOUTE installation issue du chemin documenté : ni le
    # bootstrap ni l'entretien n'écrivent ce fichier. Trois documents du dépôt
    # promettent que son absence ne casse rien ; cette passe est ce qui rend
    # cette promesse vérifiable.
    rm -f "$ARAC_HOME/config/projects.toml"
    systemctl restart "$PREFIXE_UNITE-cockpit.service" >/dev/null 2>&1
    attendre_http "$URL_COCKPIT/cc/healthz" 90 >/dev/null
    sortie="$("$ARAC_VENV/bin/python" "$_ICI/parcours_cockpit.py" \
        --racine "$ARAC_HOME" --base "$URL_COCKPIT" --cookie "$cookie" \
        --contexte "$ctx" --phase sans-projets --prefixe '  ' 2>&1)" || rc=1
    if (( rc == 0 )); then
        ok "parcours        SANS config/projects.toml — $(grep -c '✓' <<<"$sortie") route(s) empruntées, chacune a montré ce que ce cerveau contient"
    else
        ko "parcours        SANS config/projects.toml — des routes rendent 200 sans rien montrer :"
        grep -E '✗|LE COMPTE|empruntées|EN DÉFAUT|·' <<<"$sortie" \
            | while IFS= read -r l; do info "$l"; done
    fi
    grep -E 'LE COMPTE|empruntées AVEC|hors parcours' <<<"$sortie" \
        | while IFS= read -r l; do info "$l"; done

    # --- PASSE 2 : AVEC un projet déclaré ---------------------------------
    #
    # La famille « projets » n'existe que si quelqu'un l'a déclarée. On joue
    # donc le geste que la documentation prescrit — écrire
    # `config/projects.toml` — et on exige que les trois routes de projets
    # ressortent CE projet-là.
    local racine_scope="${a_scope%%/*}"
    cat > "$ARAC_HOME/config/projects.toml" <<TOMLP
[[project]]
id = "parcours"
label = "Parcours"
prefixes = ["$racine_scope"]
TOMLP
    systemctl restart "$PREFIXE_UNITE-cockpit.service" >/dev/null 2>&1
    attendre_http "$URL_COCKPIT/cc/healthz" 90 >/dev/null
    local rc2=0
    sortie="$("$ARAC_VENV/bin/python" "$_ICI/parcours_cockpit.py" \
        --racine "$ARAC_HOME" --base "$URL_COCKPIT" --cookie "$cookie" \
        --contexte "$ctx" --phase avec-projets --prefixe '  ' 2>&1)" || rc2=1
    if (( rc2 == 0 )); then
        ok "parcours        AVEC un projet déclaré — la liste, la fiche et le graphe du projet « Parcours » le ressortent"
    else
        ko "parcours        AVEC un projet déclaré — des routes rendent 200 sans rien montrer :"
        grep -E '✗|EN DÉFAUT|·' <<<"$sortie" \
            | while IFS= read -r l; do info "$l"; done
        rc=1
    fi

    # On REMET le cerveau dans l'état documenté : `config/projects.toml` est
    # une déclaration de l'utilisateur, pas un résidu du harnais. Le §13 de
    # l'étape 9 doit trouver le clone tel que l'installation l'a laissé.
    rm -f "$ARAC_HOME/config/projects.toml"
    systemctl restart "$PREFIXE_UNITE-cockpit.service" >/dev/null 2>&1
    attendre_http "$URL_COCKPIT/cc/healthz" 90 >/dev/null
    return "$rc"
}

#: Le mot de passe engendré par le bootstrap en mode non interactif.
#: Il est affiché UNE fois, sur la sortie, et jamais stocké en clair. C'est
#: donc le journal de l'installation qui le porte — et c'est le seul endroit.
_mot_de_passe_engendre() {
    [[ -r "$JOURNAL_BOOTSTRAP" ]] || return 1
    grep -A3 'Mot de passe engendré' "$JOURNAL_BOOTSTRAP" 2>/dev/null \
        | sed -n '2p' | tr -d ' \t\r'
}

#: UNE DÉPENDANCE QUE `requirements.txt` NE DÉCLARE PAS.
#:
#: `python-multipart` n'est ni dans `requirements.txt`, ni dans
#: `requirements.lock.txt`. Il est pourtant présent dans l'environnement
#: Python de l'installation d'origine — installé un jour, par autre chose,
#: et jamais remonté dans le fichier canonique. Sur une installation NEUVE,
#: qui n'a que ce que `requirements.txt` demande, il manque.
#:
#: Conséquence exacte : `POST /cc/login` — la seule route non-GET du cockpit,
#: donc la seule porte d'entrée — rend 500 en texte brut. Le cockpit démarre,
#: `/cc/healthz` répond 200, `provisioned` est vrai partout : tout dit que
#: l'installation est saine, et personne ne peut se connecter.
#:
#: C'est la forme la plus coûteuse d'une dépendance manquante : elle ne se
#: voit que sur une machine qui n'a jamais servi à développer.
_remede_dependance_multipart() {
    intervention \
        "installer python-multipart dans l'environnement du cerveau ($ARAC_VENV)" \
        "requirements.txt ne le déclare pas, alors que POST /cc/login (seule route non-GET du cockpit) en dépend : sans lui, toute tentative de connexion rend 500 en texte brut, sur une installation qui se dit saine" \
        "nulle part — c'est un défaut de requirements.txt, à corriger là et non à documenter"

    "$ARAC_VENV/bin/pip" install --quiet python-multipart >/dev/null 2>&1 || {
        ko "python-multipart n'a pas pu être installé"; return 1; }
    systemctl restart "$PREFIXE_UNITE-cockpit.service" >/dev/null 2>&1
    [[ "$(attendre_http "$URL_COCKPIT/cc/healthz" 90)" == "200" ]] || return 1
    ok "dépendance      python-multipart installé APRÈS coup — le formulaire de connexion peut être lu"
    return 0
}

#: LE GESTE QUE LE BOOTSTRAP NE POSE PAS.
#:
#: Le bootstrap écrit les trois secrets du cockpit sous des noms préfixés
#: `ARAC_` ; `control_center/config.py` les lit sous leurs noms historiques.
#: Les deux vocabulaires sont défendables ; ce qui ne l'est pas, c'est qu'ils
#: ne se rencontrent pas — le cockpit rend alors 503 sur toute connexion, et
#: l'installation s'était pourtant déclarée terminée.
#:
#: `poser_pont_de_vocabulaire` (bootstrap/lib/secrets.sh) traduit déjà les DSN
#: et les clés d'API. Il ne traduit pas ces trois-là.
#:
#: On applique donc ici le correctif que `docs/DEPANNAGE.md` donne — et on
#: l'ENREGISTRE comme une intervention. C'est ce qui permet au rapport de dire
#: à la fois « le cockpit marche » et « il n'a pas marché tout seul ».
_remede_documente_cockpit() {
    intervention \
        "traduire ARAC_CC_SESSION_SECRET / ARAC_CC_ADMIN_PASSWORD_HASH / ARAC_CC_TOTP_SECRET vers CC_SESSION_SECRET / CC_ADMIN_PASSWORD_HASH / CC_TOTP_SECRET dans $ARAC_SECRETS_COCKPIT, puis redémarrer le cockpit" \
        "le bootstrap écrit ces trois secrets sous des noms préfixés ARAC_ que control_center/config.py ne lit pas ; sans traduction, /cc/login rend 503 alors que l'installation s'est déclarée terminée" \
        "docs/DEPANNAGE.md (le pont de vocabulaire) — et bootstrap/lib/secrets.sh:poser_pont_de_vocabulaire, qui traduit les DSN et les clés mais pas ceux-ci"

    local cle
    for cle in SESSION_SECRET ADMIN_PASSWORD_HASH TOTP_SECRET; do
        local valeur
        valeur="$(lire_env "$ARAC_SECRETS_COCKPIT" "ARAC_CC_$cle" || true)"
        [[ -z "$valeur" ]] && { ko "ARAC_CC_$cle absent du coffre : rien à traduire"; return 1; }
        printf 'CC_%s=%s\n' "$cle" "$valeur" >> "$ARAC_SECRETS_COCKPIT"
    done
    chmod 600 "$ARAC_SECRETS_COCKPIT"
    systemctl restart "$PREFIXE_UNITE-cockpit.service" >/dev/null 2>&1
    [[ "$(attendre_http "$URL_COCKPIT/cc/healthz" 90)" == "200" ]] || return 1
    local provisionne
    provisionne="$(curl -s -m 10 "$URL_COCKPIT/cc/healthz" \
        | python3 -c "import json,sys;p=json.load(sys.stdin)['provisioned'];print(int(all(p.values())))" 2>/dev/null)"
    [[ "$provisionne" == "1" ]] || { ko "le cockpit reste non provisionné après traduction"; return 1; }
    ok "identifiants    provisionnés APRÈS le geste manuel ci-dessus"
    return 0
}

# ===========================================================================
# ÉTAPE 8 — prouver sa sauvegarde : le cycle complet, sur un cerveau réel
# ===========================================================================
#
# POURQUOI CETTE ÉTAPE EXISTE, ET POURQUOI ELLE ARRIVE SI TARD
#
# La sauvegarde est une promesse du produit — `docs/SAUVEGARDE.md` ouvre sur
# « une sauvegarde qui n'a jamais été restaurée n'est pas une sauvegarde ».
# C'était le seul sous-système que ce harnais ne traversait pas : l'étape 3
# fabriquait son dump avec `ops/backup.sh`, jamais avec l'unité que le
# bootstrap venait de poser, et cette unité produisait des dumps que
# `ops/restore_verify.sh` déclarait irrestaurables. Un vert qui porte sur la
# branche que l'installation n'emprunte pas.
#
# Elle arrive après le cockpit parce qu'elle a besoin d'un cerveau COMPLET :
# des atomes, une taxonomie, un schéma migré. Un dump de base vide se restaure
# toujours ; il ne prouve rien.
#
# CE QU'ELLE ÉPROUVE, ET QUI PEUT ROUGIR
#   1. la sauvegarde est ARMÉE et se déclenche seule (minuterie, calendrier
#      valide, prochaine échéance réelle) ;
#   2. le dump produit par l'UNITÉ se restaure et se compare ;
#   3. la réserve permanente d'`ops/install_check.sh` TOMBE ;
#   4. la base de restauration n'est PAS lisible par toute la grappe ;
#   5. une base VOISINE sur la même grappe n'est pas touchée — ni par le
#      nettoyage, ni par un `ARAC_RESTORE_DB` malencontreux ;
#   6. la vérification ne laisse RIEN derrière elle, et ce qui reste après une
#      désinstallation est nommé, avec sa cause.
etape_8_prouver_sa_sauvegarde() {
    exige_installation "prouver sa sauvegarde" && return
    local souci=0 rc=0
    local U_SAUV="$PREFIXE_UNITE-sauvegarde"
    local U_REST="$PREFIXE_UNITE-restauration"
    local TPL="${ARAC_DB}_restore_template"
    local TEMOIN="voisin_temoin_$$"

    # --- 1. La minuterie est armée, et son calendrier est réel -------------
    local n_armees=0 u
    for u in "$U_SAUV.timer" "$U_REST.timer"; do
        local etat suivant
        etat="$(systemctl is-enabled "$u" 2>/dev/null)"
        suivant="$(systemctl show -p NextElapseUSecRealtime --value "$u" 2>/dev/null)"
        if [[ "$etat" == "enabled" && -n "$suivant" && "$suivant" != "0" && "$suivant" != "n/a" ]]; then
            ok "minuterie       $u armée — prochaine échéance : $(systemctl show -p NextElapseUSecRealtime --value "$u" | head -c 40)"
            n_armees=$(( n_armees + 1 ))
        else
            ko "minuterie       $u n'est pas armée (is-enabled=$etat) : « aucun minuteur ne le fait à votre place » resterait vrai"
            souci=1
        fi
    done
    # Le service ne doit PAS pouvoir être armé directement : c'est la minuterie
    # qui le déclenche. Une section [Install] dans le service ferait deux
    # horloges pour un seul geste.
    if grep -q '^\[Install\]' "/etc/systemd/system/$U_SAUV.service" 2>/dev/null; then
        ko "minuterie       $U_SAUV.service porte une section [Install] : deux façons de l'armer, donc deux horloges"
        souci=1
    else
        ok "minuterie       $U_SAUV.service n'est déclenché que par sa minuterie"
    fi

    # --- 2. L'unité produit un dump, et ce dump se restaure ----------------
    #
    # C'est LE point de bascule. On ne fabrique pas le dump par un autre
    # chemin : on démarre l'unité, exactement comme la minuterie le fera.
    local avant apres
    avant="$(ls -1 "$ARAC_BACKUP_DIR"/*.dump 2>/dev/null | wc -l)"
    rc=0; systemctl start "$U_SAUV.service" >/dev/null 2>&1 || rc=$?
    apres="$(ls -1 "$ARAC_BACKUP_DIR"/*.dump 2>/dev/null | wc -l)"
    if (( rc != 0 )) || (( apres <= avant )); then
        ko "sauvegarde      l'unité n'a pas produit de dump (rc=$rc, $avant → $apres)"
        journalctl -u "$U_SAUV.service" -n 8 --no-pager -o cat 2>/dev/null \
            | while IFS= read -r l; do info "$l"; done
        souci=1
    else
        local dernier
        dernier="$(ls -1t "$ARAC_BACKUP_DIR"/*.dump | head -1)"
        ok "sauvegarde      l'unité a produit $(basename "$dernier") ($(stat -c %s "$dernier") octets)"
        # Le dump de l'unité doit être celui que la restauration sait relire :
        # `--schema`, donc AUCUNE entrée d'extension dans son sommaire.
        local n_ext
        n_ext="$(pg_restore -l "$dernier" 2>/dev/null | grep -c 'EXTENSION' || true)"
        if [[ "${n_ext:-0}" == "0" ]]; then
            ok "sauvegarde      sommaire sans entrée EXTENSION — restaurable sans être propriétaire des extensions"
        else
            ko "sauvegarde      $n_ext entrée(s) EXTENSION dans le sommaire : la restauration échouera sur « must be owner of extension »"
            souci=1
        fi
    fi

    # --- 3. Un VOISIN sur la même grappe, et il ne doit pas bouger ---------
    psql_super -d postgres -qc "CREATE DATABASE $TEMOIN" >/dev/null 2>&1
    psql_super -d "$TEMOIN" -qc "CREATE TABLE t(x int); INSERT INTO t VALUES (1),(2),(3)" >/dev/null 2>&1
    local temoin_avant
    temoin_avant="$(psql_super -d "$TEMOIN" -tAc "SELECT count(*) FROM t" 2>/dev/null)"

    # 3a. Le refus explicite : viser une base qu'on n'a pas créée.
    rc=0
    ( cd "$ARAC_HOME" && ARAC_ENV_FILE="$ARAC_ENV_FILE" ARAC_RESTORE_DB="$TEMOIN" \
        ops/restore_verify.sh ) > "$BASE_TRAVAIL/restauration-voisin.log" 2>&1 || rc=$?
    local temoin_apres
    temoin_apres="$(psql_super -d "$TEMOIN" -tAc "SELECT count(*) FROM t" 2>/dev/null)"
    if (( rc != 0 )) && [[ "$temoin_apres" == "$temoin_avant" ]] \
       && grep -q 'existe déjà' "$BASE_TRAVAIL/restauration-voisin.log"; then
        ok "voisin          ARAC_RESTORE_DB=<base d'un autre> REFUSÉ avant toute création — la base voisine est intacte ($temoin_apres lignes)"
    else
        ko "voisin          la base voisine « $TEMOIN » a été visée (rc=$rc, $temoin_avant → ${temoin_apres:-DÉTRUITE})"
        grep -E 'REFUS|DROP|échoué' "$BASE_TRAVAIL/restauration-voisin.log" | head -4 \
            | while IFS= read -r l; do info "$l"; done
        souci=1
    fi
    # 3b. Le gabarit non plus n'est pas une cible.
    rc=0
    ( cd "$ARAC_HOME" && ARAC_ENV_FILE="$ARAC_ENV_FILE" ARAC_RESTORE_DB="$TPL" \
        ops/restore_verify.sh ) > "$BASE_TRAVAIL/restauration-gabarit.log" 2>&1 || rc=$?
    if (( rc != 0 )) && [[ "$(psql_super -d postgres -tAc \
            "SELECT count(*) FROM pg_database WHERE datname='$TPL'")" == "1" ]]; then
        ok "gabarit         viser le gabarit est REFUSÉ, et le gabarit est toujours là"
    else
        ko "gabarit         « $TPL » a été détruit ou réutilisé : la preuve de sauvegarde redevient impossible"
        souci=1
    fi

    # --- 4. La restauration complète, et la base fermée à PUBLIC ----------
    rc=0
    ( cd "$ARAC_HOME" && ARAC_ENV_FILE="$ARAC_ENV_FILE" ARAC_RESTORE_KEEP=1 \
        ops/restore_verify.sh --keep ) > "$BASE_TRAVAIL/restauration-keep.log" 2>&1 || rc=$?
    local jetable
    jetable="$(psql_super -d postgres -tAc \
        "SELECT datname FROM pg_database WHERE datname ~ '^${ARAC_DB}_restore_[0-9]+\$' ORDER BY 1 DESC LIMIT 1" 2>/dev/null)"
    if (( rc != 0 )) || [[ -z "$jetable" ]]; then
        ko "restauration    --keep n'a pas laissé de base à examiner (rc=$rc)"
        grep -E 'ÉCHEC|ERROR|✗' "$BASE_TRAVAIL/restauration-keep.log" | head -6 \
            | while IFS= read -r l; do info "$l"; done
        souci=1
    else
        local acl
        acl="$(psql_super -d postgres -tAc \
            "SELECT coalesce(array_to_string(datacl,' | '),'NULL') FROM pg_database WHERE datname='$jetable'")"
        # `datacl` NULL = défaut PostgreSQL = PUBLIC a CONNECT. Une base qui
        # porte l'intégralité d'une mémoire privée ne doit pas être plus
        # ouverte que la mémoire elle-même.
        if [[ "$acl" == "NULL" ]] || grep -qE '(^|\| *)=[A-Za-z]*c' <<<"$acl"; then
            ko "droits          « $jetable » laisse CONNECT à PUBLIC : datacl=$acl"
            souci=1
        else
            ok "droits          « $jetable » fermée à PUBLIC — seule la mémoire de ce cerveau y accède"
        fi
        # Et le gabarit permanent, lui aussi.
        local acl_tpl
        acl_tpl="$(psql_super -d postgres -tAc \
            "SELECT coalesce(array_to_string(datacl,' | '),'NULL') FROM pg_database WHERE datname='$TPL'")"
        if [[ "$acl_tpl" == "NULL" ]] || grep -qE '(^|\| *)=[A-Za-z]*c' <<<"$acl_tpl"; then
            ko "droits          le gabarit « $TPL » laisse CONNECT à PUBLIC : datacl=$acl_tpl"
            souci=1
        else
            ok "droits          le gabarit « $TPL » fermé à PUBLIC — et lui est PERMANENT"
        fi
        psql_super -d postgres -qc "DROP DATABASE \"$jetable\"" >/dev/null 2>&1
    fi

    # --- 5. La réserve permanente tombe, et rien ne survit ----------------
    rc=0
    _unite_restauration_lance "$BASE_TRAVAIL/restauration-cycle.log" || rc=$?
    if (( rc != 0 )); then
        ko "restauration    le cycle complet, par SON UNITÉ, a rendu $rc — la sauvegarde n'est PAS prouvée"
        grep -E 'ÉCHEC|ERROR|✗' "$BASE_TRAVAIL/restauration-cycle.log" | head -6 \
            | while IFS= read -r l; do info "$l"; done
        souci=1
    else
        ok "restauration    dump de l'unité RESTAURÉ et COMPARÉ au cerveau vivant, sans superutilisateur"
    fi
    local restes
    restes="$(psql_super -d postgres -tAc \
        "SELECT count(*) FROM pg_database WHERE datname ~ '^${ARAC_DB}_restore_[0-9]+\$'" 2>/dev/null)"
    if [[ "${restes:-0}" == "0" ]]; then
        ok "base jetable    détruite — il ne reste que le gabarit vide"
    else
        ko "base jetable    $restes base(s) « ${ARAC_DB}_restore_<horodatage> » survivent"
        souci=1
    fi

    local check
    check="$( cd "$ARAC_HOME" && ARAC_ENV_FILE="$ARAC_ENV_FILE" ops/install_check.sh 2>&1 )"
    if grep -q "dernière restauration PROUVÉE" <<<"$check"; then
        ok "réserve levée   « vos dumps sont une hypothèse » a disparu d'ops/install_check.sh"
    else
        ko "réserve levée   ops/install_check.sh ne dit pas « dernière restauration PROUVÉE »"
        souci=1
    fi

    # --- 6. Ce qui reste d'une désinstallation, et POURQUOI ---------------
    #
    # On n'exécute pas la désinstallation ici — elle détruirait le cerveau que
    # les étapes suivantes n'ont plus à examiner, mais surtout elle n'est pas
    # ce qu'on éprouve. Ce qu'on éprouve, c'est que le CONTRÔLE sache voir la
    # base que le bootstrap a posée et dire ce qu'elle bloque : sans cela, le
    # lecteur du §13 voit une erreur au milieu d'un bloc « IRRÉVERSIBLE » et
    # aucun geste pour s'en sortir.
    local sortie_reste
    sortie_reste="$( cd "$ARAC_HOME" && ops/uninstall_check.sh "$ARAC_DB" --port "$PORT_PG" --gestes 2>&1 )"
    # ON CHERCHE LA SUBSTANCE, PAS LA PHRASE.
    #
    # Ces trois motifs étaient des phrases françaises entières — « gabarit de
    # restauration « X » ». Le jour où `ops/uninstall_check.sh` a amélioré sa
    # formulation (« base « X » sur la grappe 5461 (7 735 kB, propriétaire :
    # …) »), cette étape est passée au rouge sans qu'aucune promesse ne soit
    # tombée : le gabarit était nommé, sa conséquence écrite, son dropdb
    # imprimé. Un contrôle qui épingle la prose du contrôlé mesure son style.
    # On garde donc les trois choses qui DOIVENT y être — le NOM de la base,
    # la conséquence (« DROP ROLE »), et le geste exact — et rien de plus.
    local -a motifs_restes=(
        "$TPL"
        "DROP ROLE"
        "dropdb -p $PORT_PG --if-exists '$TPL'"
    )
    local m manquants_restes=()
    for m in "${motifs_restes[@]}"; do
        grep -qF -- "$m" <<<"$sortie_reste" || manquants_restes+=("$m")
    done
    if (( ${#manquants_restes[@]} == 0 )); then
        ok "désinstallation ops/uninstall_check.sh voit le gabarit, dit qu'il BLOQUE le DROP ROLE, et imprime le dropdb"
    else
        # Un juge dit CE QU'IL A CHERCHÉ et ce qu'il n'a pas trouvé. Sans cela,
        # un faux négatif contredit silencieusement la sortie qu'il imprime.
        ko "désinstallation le contrôle des restes ne dit pas : ${manquants_restes[*]}"
        head -12 <<<"$sortie_reste" | while IFS= read -r l; do info "$l"; done
        souci=1
    fi

    psql_super -d postgres -qc "DROP DATABASE IF EXISTS $TEMOIN" >/dev/null 2>&1

    # --- 7. LA BASCULE — le chapitre qu'on exécute en panique, JOUÉ ---------
    _preuve_bascule || souci=1

    if (( souci )); then
        verdict "ÉCHEC" "la sauvegarde armée par le bootstrap n'est pas prouvable de bout en bout"
    else
        verdict "PROUVÉ" "l'unité armée par le bootstrap produit un dump que ops/restore_verify.sh RESTAURE et COMPARE, sans superutilisateur ; la base de restauration est fermée à PUBLIC ; la base voisine et le gabarit sont refusés comme cibles et intacts ; la réserve « vos dumps sont une hypothèse » est levée ; la BASCULE du §7 est jouée à la lettre sur un cerveau cassé pour de vrai et le cerveau revient ; rien ne survit"
    fi
}

# ---------------------------------------------------------------------------
# LA BASCULE RÉELLE — docs/SAUVEGARDE.md §7, joué comme un lecteur le joue
# ---------------------------------------------------------------------------
#
# POURQUOI CETTE FONCTION EXISTE, ET POURQUOI ELLE ARRIVE SI TARD.
#
# Tout ce que l'étape 8 éprouvait jusqu'ici se joue dans une base JETABLE :
# on restaure à côté, on compte, on détruit. C'est la bonne preuve pour une
# vérification hebdomadaire, et ce n'est PAS la restauration. La restauration
# — celle qui remet un cerveau debout — a un nom dans ce dépôt, un chapitre
# écrit « pour être suivi ligne par ligne, sans réfléchir », et personne ne
# l'avait jamais jouée. Elle ne marchait pas :
#
#   · l'étape 1 (« prouver le dump AVANT de s'en servir ») rendait ÉCHEC sur
#     un dump parfaitement bon, parce que la base vivante — abîmée, c'est la
#     raison d'être du chapitre — était lue comme « zéro atome » ;
#   · l'étape 5.3 (`bootstrap.sh --only migrations`, « la commande qui met le
#     schéma à niveau ET réapplique les droits ») mourait en code 7 sur
#     « permission denied for schema arac », et le remède qu'elle imprimait
#     rendait la même erreur ;
#   · l'étape 5.4 (`verify_install.sh`) certifiait « ✓ Ce cerveau fonctionne »
#     sur une base dont aucun rôle ne pouvait lire un souvenir.
#
# Une bascule jamais jouée est une promesse non tenue. Celle-ci casse le
# cerveau POUR DE VRAI — `DROP SCHEMA … CASCADE` sur la base vivante du
# cerveau d'essai — et exige qu'il revienne, avec ses atomes, lus SOUS LE RÔLE
# DE L'APPLICATION et servis par l'API.
_preuve_bascule() {
    local souci=0 rc=0
    local DATE_B; DATE_B="$(date -u +%Y%m%d%H%M%S)"
    local NEUVE="${ARAC_DB}_restauree_${DATE_B}"
    local AVARIE="${ARAC_DB}_avarie_${DATE_B}"
    local JB="$BASE_TRAVAIL/bascule"
    mkdir -p "$JB"

    # UN TÉMOIN DANS LA MÉMOIRE, SANS QUOI L'ÉPREUVE EST VIDE.
    #
    # En mode GRATUIT ce cerveau n'a AUCUN atome : la curation et les
    # embeddings sont payants, et ce harnais ne les arme jamais. « 0 atome
    # avant, 0 atome après » est un vert qui ne prouve rien — c'est exactement
    # la famille de faux verts que cette manche traque. On pose donc trois
    # souvenirs reconnaissables, par SQL, avant de tout casser. Ils ne
    # prouvent pas l'apprentissage (l'étape 6 dit ce qu'elle ne prouve pas) ;
    # ils prouvent que la BASCULE rapporte la mémoire qu'on lui a confiée.
    local pose
    pose="$(psql_super -d "$ARAC_DB" -tAc "
        INSERT INTO arac.memory_atoms (kind, scope, key, value, desc_hash, node_id,
                                       confidence, confidence_score, status)
        SELECT 'note',
               coalesce((SELECT path FROM arac.scopes ORDER BY id LIMIT 1), 'divers'),
               'temoin-bascule-' || i,
               'Souvenir temoin numero ' || i || ' — il doit survivre a la bascule.',
               md5('temoin-bascule-' || i),
               '$POSTE', 'producer', 80, 'active'
          FROM generate_series(1,3) i
        RETURNING 1" 2>&1 | grep -c '^1$' || true)"
    if [[ "${pose:-0}" != "3" ]]; then
        ko "bascule         impossible de poser les souvenirs témoins : l'épreuve serait vide"
        info "  $(psql_super -d "$ARAC_DB" -tAc "SELECT 1" 2>&1 | head -1)"
        return 1
    fi
    ok "bascule         3 souvenirs témoins posés dans la mémoire — la bascule devra les rapporter"

    # LE DUMP DOIT LES CONTENIR : on redemande à l'UNITÉ d'en produire un.
    # Reprendre celui d'avant reviendrait à prouver la bascule sur une mémoire
    # que le fichier ne porte pas.
    systemctl start "$PREFIXE_UNITE-sauvegarde.service" >/dev/null 2>&1

    # ET L'UNITÉ DE RESTAURATION, MÉMOIRE EN BASE — ce que ce harnais n'avait
    # JAMAIS fait, et c'est pour cela qu'une fuite entière lui a échappé.
    #
    # Le harnais exerçait `ops/restore_verify.sh` en l'appelant lui-même, et
    # lisait sa sortie dans son propre journal de passage. Il n'a jamais démarré
    # `arac-<base>-restauration.service` — l'unité que le bootstrap arme, que la
    # minuterie déclenche chaque dimanche, et que `docs/SAUVEGARDE.md` §7 étape 6
    # fait lancer à la main. Or la différence entre les deux n'est pas le code
    # exécuté : c'est OÙ VA SA SORTIE. Appelé à la main, il parle à un terminal
    # qui se ferme ; démarré par systemd, il parle à journald, qui garde des
    # semaines et que le §13 ne peut pas effacer. Tout ce que le produit laisse
    # derrière lui dans le journal était donc hors du champ du juge, par
    # construction — et c'est là qu'on a retrouvé les clés et les domaines de
    # trois souvenirs après un départ déclaré PROPRE.
    #
    # On démarre donc l'unité ICI, la mémoire en base : c'est le seul moment du
    # parcours où elle a quelque chose à trahir. Ce qu'elle écrit sera relu à
    # l'étape 9, APRÈS la désinstallation.
    local rc_rest_unite=0
    systemctl start "$PREFIXE_UNITE-restauration.service" >/dev/null 2>&1 || rc_rest_unite=$?
    if (( rc_rest_unite == 0 )); then
        ok "bascule         « $PREFIXE_UNITE-restauration.service » démarrée avec 3 souvenirs en base — l'unité que la page fait lancer, et que ce harnais n'exerçait pas"
    else
        # Non bloquant : l'unité peut rendre 2 (réserve) sans que la mémoire
        # cesse d'être en jeu. Ce qui compte ici est qu'elle ait PARLÉ.
        info "bascule         « $PREFIXE_UNITE-restauration.service » rend $rc_rest_unite — sa sortie est dans le journal, et c'est elle qu'on relira à l'étape 9"
    fi

    local avant
    avant="$(sql "SELECT count(*) FROM arac.memory_atoms")"
    if [[ -z "$avant" || "$avant" == "0" ]]; then
        ko "bascule         aucun atome à sauver : rien à prouver"
        return 1
    fi

    local dump
    dump="$(ls -1t "$ARAC_BACKUP_DIR/$ARAC_DB"-*.dump 2>/dev/null | head -1)"
    if [[ -z "$dump" ]]; then
        ko "bascule         aucun dump de l'unité : la bascule n'a rien à restaurer"
        return 1
    fi
    info "bascule : $avant atome(s) avant, dump de départ $(basename "$dump")"

    # --- ON CASSE POUR DE VRAI --------------------------------------------
    psql_super -d "$ARAC_DB" -qc "DROP SCHEMA arac CASCADE" >/dev/null 2>&1
    if [[ -n "$(sql "SELECT to_regclass('arac.memory_atoms')")" ]]; then
        ko "bascule         le cerveau n'a pas pu être cassé : l'épreuve serait fausse"
        return 1
    fi
    ok "bascule         cerveau CASSÉ pour de vrai (DROP SCHEMA arac CASCADE) — $avant atome(s) perdus"

    # --- ÉTAPE 1 du §7 : prouver le dump AVANT de s'en servir --------------
    #
    # C'est ici que le chapitre s'arrêtait. Le contrôle doit dire « restauré,
    # preuve partielle » (code 2) : le dump est bon, c'est le CERVEAU qui est
    # mort. Un code 1 renverrait le lecteur essayer tous ses dumps, l'un après
    # l'autre, et conclure que son coffre est vide.
    rc=0
    ( cd "$ARAC_HOME" && ARAC_ENV_FILE="$ARAC_ENV_FILE" ops/restore_verify.sh "$dump" ) \
        > "$JB/etape1.log" 2>&1 || rc=$?
    if (( rc == 2 )) && grep -q "ne se laisse plus lire" "$JB/etape1.log"; then
        ok "bascule §7.1    le dump est PROUVÉ malgré un cerveau mort (code 2), et le contrôle dit pourquoi"
    else
        ko "bascule §7.1    ops/restore_verify.sh a rendu $rc sur un dump sain : le §7 s'arrête à sa première ligne"
        grep -E '✗|VERDICT' "$JB/etape1.log" | head -4 | while IFS= read -r l; do info "  $l"; done
        souci=1
    fi
    # Et l'identité : le dump doit dire de QUEL cerveau il vient.
    if grep -q "PREUVE D" "$JB/etape1.log" && grep -q "empreinte d'installation identique" "$JB/etape1.log"; then
        ok "bascule §7.1    le dump porte l'empreinte de CE cerveau — elle a voyagé dans le fichier"
    else
        ko "bascule §7.1    le dump ne dit pas de quel cerveau il vient : restaurer celui du voisin passerait pour une preuve"
        souci=1
    fi

    # --- ÉTAPE 3 du §7 : restaurer dans une base NEUVE ---------------------
    psql_super -d postgres -qc "CREATE DATABASE \"$NEUVE\"" >/dev/null 2>&1
    psql_super -d "$NEUVE" -qc "CREATE EXTENSION vector; CREATE EXTENSION pg_trgm" >/dev/null 2>&1
    rc=0
    cat "$dump" | sudo -u postgres pg_restore -p "$PORT_PG" --dbname="$NEUVE" \
        --no-owner --no-privileges > "$JB/etape3.log" 2>&1 || rc=$?
    local dans_neuve
    dans_neuve="$(psql_super -d "$NEUVE" -tAc "SELECT count(*) FROM arac.memory_atoms" 2>/dev/null)"
    if (( rc == 0 )) && [[ "$dans_neuve" == "$avant" ]]; then
        ok "bascule §7.3    « $NEUVE » restaurée : $dans_neuve atome(s), comme avant la casse"
    else
        ko "bascule §7.3    pg_restore rc=$rc, ${dans_neuve:-aucun} atome(s) dans la base neuve"
        tail -5 "$JB/etape3.log" | while IFS= read -r l; do info "  $l"; done
        souci=1
    fi

    # --- ÉTAPE 5 du §7 : la bascule ---------------------------------------
    systemctl stop "$PREFIXE_UNITE-api" "$PREFIXE_UNITE-cockpit" \
                   "$PREFIXE_UNITE-cycle.timer" "$PREFIXE_UNITE-sauvegarde.timer" >/dev/null 2>&1
    psql_super -d postgres -qc "ALTER DATABASE \"$ARAC_DB\" RENAME TO \"$AVARIE\"" >/dev/null 2>&1
    psql_super -d postgres -qc "ALTER DATABASE \"$NEUVE\" RENAME TO \"$ARAC_DB\"" >/dev/null 2>&1

    rc=0
    ( cd "$ARAC_HOME" && _env_bootstrap ./bootstrap/bootstrap.sh --only migrations --yes --no-color ) \
        > "$JB/etape5.log" 2>&1 || rc=$?
    if (( rc == 0 )); then
        ok "bascule §7.5    « bootstrap.sh --only migrations » a repris la propriété du schéma et réappliqué les droits"
    else
        ko "bascule §7.5    « bootstrap.sh --only migrations » a rendu $rc — la page laisse le lecteur sans cerveau et sans remède"
        grep -E 'permission denied|ÉCHEC|✗' "$JB/etape5.log" | head -5 \
            | while IFS= read -r l; do info "  $l"; done
        souci=1
    fi

    systemctl start "$PREFIXE_UNITE-api" "$PREFIXE_UNITE-cockpit" >/dev/null 2>&1
    # `verify_install.sh`, plus bas, interroge des services vivants. Trois
    # secondes de sommeil suffisaient sur une machine au repos et pas sur une
    # machine chargée : on attend la réponse, avec une borne.
    [[ "$(attendre_http "$URL_API/healthz" 90)" == "200" ]] \
        || info "l'API n'a pas répondu en 90 s après la bascule — la suite le dira"


    # --- CE QUI COMPTE : LE CERVEAU EST-IL REVENU ? ------------------------
    #
    # Pas « quelque chose répond-il », et pas non plus un comptage sous le
    # superutilisateur — à qui aucun droit ne manque jamais. On lit SOUS LE
    # RÔLE DE L'APPLICATION, qui est celui que l'API emploie.
    local dsn_app apres_app
    dsn_app="$(lire_env "$ARAC_ENV_FILE" DATABASE_URL_APP || true)"
    if [[ -n "$dsn_app" ]]; then
        apres_app="$(psql "$dsn_app" -tAc "SELECT count(*) FROM arac.memory_atoms" 2>/dev/null || true)"
    fi
    local temoins=''
    [[ -n "$dsn_app" ]] && temoins="$(psql "$dsn_app" -tAc \
        "SELECT count(*) FROM arac.memory_atoms WHERE key LIKE 'temoin-bascule-%'" 2>/dev/null || true)"
    if [[ "$apres_app" == "$avant" && "$temoins" == "3" ]]; then
        ok "bascule         $apres_app atome(s) relus SOUS LE RÔLE DE L'APPLICATION, dont les 3 témoins — le cerveau est revenu"
    else
        ko "bascule         le rôle de l'application lit « ${apres_app:-rien} » atome(s) et « ${temoins:-0} » témoin(s) là où il y avait $avant et 3 : la mémoire n'est pas revenue"
        souci=1
    fi

    # --- ÉTAPE 5.4 du §7 : le contrôle que la page prescrit ----------------
    rc=0
    ( cd "$ARAC_HOME" && _env_bootstrap ./bootstrap/checks/verify_install.sh ) \
        > "$JB/verify.log" 2>&1 || rc=$?
    if (( rc == 0 )) && grep -q "souvenir(s) lus SOUS CE RÔLE" "$JB/verify.log"; then
        ok "bascule §7.5    verify_install.sh conclut sur une lecture réelle du schéma, sous chaque rôle"
    else
        ko "bascule §7.5    verify_install.sh a rendu $rc, ou ne lit rien sous les rôles du cerveau"
        grep -E '✗' "$JB/verify.log" | head -6 | while IFS= read -r l; do info "  $l"; done
        souci=1
    fi
    # Il doit AUSSI nommer la copie que la bascule laisse derrière elle.
    if grep -q "$AVARIE" "$JB/verify.log"; then
        ok "bascule         verify_install.sh NOMME « $AVARIE » — une copie complète de la mémoire, gardée exprès"
    else
        ko "bascule         « $AVARIE » porte tout le cerveau et aucun contrôle ne le dit"
        souci=1
    fi

    # --- ET LA DÉSINSTALLATION LA VOIT-ELLE ? -----------------------------
    local restes
    restes="$( cd "$ARAC_HOME" && ops/uninstall_check.sh "$ARAC_DB" --port "$PORT_PG" --gestes 2>&1 )"
    # Même raison qu'à l'étape 8 : le NOM et le GESTE, pas la phrase.
    local -a motifs_bascule=(
        "$AVARIE"
        "dropdb -p $PORT_PG --if-exists '$AVARIE'"
    )
    local mb manquants_bascule=()
    for mb in "${motifs_bascule[@]}"; do
        grep -qF -- "$mb" <<<"$restes" || manquants_bascule+=("$mb")
    done
    if (( ${#manquants_bascule[@]} == 0 )); then
        ok "bascule         ops/uninstall_check.sh voit la base avariée et imprime son dropdb"
    else
        ko "bascule         la désinstallation laisserait « $AVARIE » : le contrôle ne dit pas ${manquants_bascule[*]}"
        souci=1
    fi

    # On ne garde pas deux fois la mémoire du cerveau d'essai.
    psql_super -d postgres -qc "DROP DATABASE IF EXISTS \"$AVARIE\"" >/dev/null 2>&1
    return "$souci"
}

# ===========================================================================
# LE RAPPORT
# ===========================================================================

rapport() {
    titre "Rapport d'acceptation — cerveau « $CERVEAU »"

    local i n_prouve=0 n_partiel=0 n_nonteste=0 n_echec=0
    for i in "${!E_TITRE[@]}"; do
        printf '  %d. %-42s %-24s %4ds\n' \
            "$((i + 1))" "${E_TITRE[$i]}" "$(_symbole_verdict "${E_VERDICT[$i]}")" "${E_DUREE[$i]}"
        printf '     %s\n' "$(_c 2 "${E_PREUVE[$i]}")"
        case "${E_VERDICT[$i]}" in
            PROUVÉ)    n_prouve=$((n_prouve + 1)) ;;
            PARTIEL)   n_partiel=$((n_partiel + 1)) ;;
            NON_TESTÉ) n_nonteste=$((n_nonteste + 1)) ;;
            *)         n_echec=$((n_echec + 1)) ;;
        esac
    done

    if (( ${#NON_TESTES[@]} )); then
        vide
        dire "$(_c 1 'CE QUI N'\''A PAS ÉTÉ TESTÉ — nommé, jamais présenté comme vérifié')"
        local t; for t in "${NON_TESTES[@]}"; do dire "     · $t"; done
    fi

    if (( ${#INTERVENTIONS[@]} )); then
        vide
        dire "$(_c 31 "INTERVENTIONS MANUELLES : ${#INTERVENTIONS[@]}")"
        local x
        for x in "${INTERVENTIONS[@]}"; do
            dire "     · ${x%%|*}"
            local reste="${x#*|}"
            dire "       pourquoi   : ${reste%%|*}"
            dire "       documenté  : ${reste#*|}"
        done
        vide
        dire "  Chacune est un geste que l'utilisateur devrait poser LUI-MÊME, après une"
        dire "  installation qui s'est pourtant déclarée terminée. Le critère dit"
        dire "  « sans intervention » : une seule suffit à ce que le framework ne soit"
        dire "  pas prêt, quel que soit l'état des neuf étapes."
    fi

    vide
    dire "  $n_prouve prouvée(s) · $n_partiel partielle(s) · $n_nonteste non testée(s) · $n_echec en échec · ${#INTERVENTIONS[@]} intervention(s)"
    vide
    if (( n_nonteste > 0 )); then
        ko "$(_c 1 'LE FRAMEWORK N'\''EST PAS PRÊT.')"
        dire "     $n_nonteste étape(s) n'ont jamais été exercées : une étape amont a échoué."
        dire "     Réparez-la, relancez. Ce rapport ne dit RIEN de ces étapes-là —"
        dire "     ni qu'elles marchent, ni qu'elles sont cassées."
    elif (( n_echec == 0 && ${#INTERVENTIONS[@]} == 0 )); then
        if (( n_partiel == 0 )); then
            ok "$(_c 1 'UN INCONNU PEUT CRÉER SON CERVEAU SEUL.')"
        else
            attn "$(_c 1 'Aucun échec, aucune intervention — mais des étapes ne sont que partiellement prouvées.')"
            dire "     Relisez la liste ci-dessus avant de conclure quoi que ce soit."
        fi
    else
        ko "$(_c 1 'LE FRAMEWORK N'\''EST PAS PRÊT.')"
    fi
    vide
    dire "  journal complet : $JOURNAL"
    vide
}

# ===========================================================================
# ÉTAPE 9 — DÉSINSTALLER, POUR DE VRAI
# ===========================================================================
#
# Les huit étapes précédentes prouvaient qu'on peut ARRIVER. Aucune ne prouvait
# qu'on peut PARTIR. Le §13 de docs/INSTALLATION.md n'a pas de script — c'est
# délibéré, « un outil qui sait détruire une mémoire est dangereux à livrer » —
# et jusqu'ici le harnais se contentait de vérifier que le CONTRÔLE des restes
# savait NOMMER ce qui restait. Nommer n'est pas traverser : une promesse que
# le harnais ne traverse pas n'est pas prouvée.
#
# Cette étape joue les gestes du §13 dans l'ordre, sur le cerveau d'essai, puis
# pose les deux questions que la page pose elle-même :
#
#   · `ops/uninstall_check.sh` dit-il « VERDICT : PROPRE », code 0 ?
#   · ET — la question que la page ne pose à personne — reste-t-il, quelque
#     part sur cette machine, une COPIE DE LA MÉMOIRE de ce cerveau ?
#
# La seconde ne se déduit pas de la première : `uninstall_check.sh` regarde les
# chemins PAR DÉFAUT d'une installation. Ici on demande à la grappe elle-même
# ce qu'elle porte encore, et on compte les octets qui restent sous chacun des
# dossiers que CETTE installation a réellement employés.
#
# Le seul dump qui a le droit de survivre est celui que le §13.2 fait écrire
# AVANT de détruire — « l'adieu ». On le NOMME, et le démontage l'efface avec
# le reste du banc.
# ===========================================================================

etape_9_desinstaller() {
    exige_installation "désinstaller — le §13 joué à la lettre" && return
    cd "$ARAC_HOME" || { verdict "ÉCHEC" "clone inaccessible"; return; }
    local souci=0

    # --- Les gardes, une fois de plus, sur les valeurs de MAINTENANT ------
    # Entre l'étape 1 et ici, il s'est écoulé une installation entière et une
    # bascule. Ce qui suit détruit une base, cinq rôles et deux comptes : on ne
    # le fait pas sur des variables qu'on a validées il y a huit étapes.
    local sortie
    if ! sortie="$(garde_nom_cerveau "$CERVEAU" 2>&1)"; then
        ko "$sortie"; verdict "ÉCHEC" "le cerveau à désinstaller n'est pas marqué — rien n'a été touché"; return
    fi
    # La BASE dérive du cerveau par `tr -c a-zA-Z0-9 _` : elle porte donc des
    # soulignés, que `garde_nom_cerveau` refuse à juste titre. On la vérifie
    # pour ce qu'elle est — un identifiant SQL marqué — parce que c'est elle
    # que le `dropdb` et les cinq `DROP ROLE` vont recevoir.
    if [[ "$ARAC_DB" != *"$GARDE_MARQUEUR"* || ! "$ARAC_DB" =~ ^[a-z][a-z0-9_]*$ ]]; then
        ko "la base « $ARAC_DB » n'est pas un identifiant marqué « $GARDE_MARQUEUR »"
        verdict "ÉCHEC" "la base à détruire n'est pas marquée — rien n'a été touché"; return
    fi
    if ! sortie="$(garde_port_pg "$PORT_PG" 2>&1)"; then
        ko "$sortie"; verdict "ÉCHEC" "la grappe visée n'est pas celle d'un essai — rien n'a été touché"; return
    fi
    if ! sortie="$(garde_prefixe_unite "$PREFIXE_UNITE" 2>&1)"; then
        ko "$sortie"; verdict "ÉCHEC" "le préfixe d'unités n'est pas marqué — rien n'a été touché"; return
    fi

    # --- §13, préambule : le port et l'empreinte, LUS dans le coffre ------
    local port_coffre empreinte
    port_coffre="$(lire_env "$ARAC_ENV_FILE" ARAC_DB_PORT || true)"
    empreinte="$(lire_env "$ARAC_ENV_FILE" ARAC_INSTALL_UUID || true)"
    if [[ "$port_coffre" == "$PORT_PG" ]]; then
        ok "§13 préambule   ARAC_DB_PORT du coffre = $port_coffre : la page sait retrouver la grappe de ce cerveau"
    else
        ko "§13 préambule   le coffre annonce le port « ${port_coffre:-rien} », le cerveau vit sur $PORT_PG — la page enverrait le dropdb sur la mauvaise grappe"
        souci=1
    fi

    # --- §13, contrôle 0 : à qui sont les rôles qu'on va détruire ? -------
    local prefixe_role etrangers
    prefixe_role="$(lire_env "$ARAC_ENV_FILE" ARAC_ROLE_PREFIX || true)"
    if [[ -z "$prefixe_role" || -z "$empreinte" ]]; then
        ko "§13 contrôle 0  sans ARAC_ROLE_PREFIX ni ARAC_INSTALL_UUID, la page tombe dans son « cas 3 » : le nom seul, qui ne prouve rien"
        souci=1
    else
        etrangers="$(psql_super -d postgres -tAc \
            "SELECT rolname FROM pg_roles
              WHERE rolname LIKE '${prefixe_role}\\_%'
                AND coalesce(shobj_description(oid,'pg_authid'),'')
                    NOT LIKE '%;empreinte=${empreinte};%'
              ORDER BY 1" 2>/dev/null)"
        if [[ -z "$etrangers" ]]; then
            ok "§13 contrôle 0  les rôles « ${prefixe_role}_* » portent TOUS l'empreinte de cette installation : aucun n'est au voisin"
        else
            ko "§13 contrôle 0  des rôles ne portent pas cette empreinte — la page dit ARRÊTEZ-VOUS, et on s'arrête : $(tr '\n' ' ' <<<"$etrangers")"
            verdict "ÉCHEC" "le contrôle 0 du §13 refuse : rien n'a été détruit"
            return
        fi
    fi

    # --- §13, 0 bis : les deux comptes, RELEVÉS pendant que les unités sont là
    local u_service u_agent
    u_service="$(systemctl show "$PREFIXE_UNITE-api"   -p User --value 2>/dev/null)"
    u_agent="$(  systemctl show "$PREFIXE_UNITE-cycle" -p User --value 2>/dev/null)"
    if [[ "$u_service" == "$U_SERVICE" && "$u_agent" == "$U_AGENT" ]]; then
        ok "§13 0 bis       les deux comptes se LISENT dans les unités ($u_service · $u_agent) — la page n'a pas à les recalculer"
    else
        ko "§13 0 bis       les unités annoncent « ${u_service:-rien} » et « ${u_agent:-rien} », l'installation a posé « $U_SERVICE » et « $U_AGENT »"
        souci=1
        u_service="$U_SERVICE"; u_agent="$U_AGENT"
    fi

    # --- §13.1 : arrêter et désarmer — LA LISTE EST CELLE DE LA PAGE ------
    # UNE LISTE LUE EST UNE LISTE VENUE DU DEHORS : ELLE PASSE LA GARDE.
    # Le nom que la page construit est `arac-$BASE-…` et ce harnais installe
    # sous `$PREFIXE_UNITE` — les deux coïncident par construction. On le
    # VÉRIFIE quand même, un par un : le jour où ils cesseraient de coïncider,
    # ce `systemctl disable --now` viserait l'unité de quelqu'un d'autre.
    local -a u13=()
    local _u
    while IFS= read -r _u; do
        [[ -n "$_u" ]] || continue
        if [[ "$_u" != "$PREFIXE_UNITE-"* ]]; then
            ko "§13.1           le §13 nomme « $_u », qui n'est pas une unité de ce cerveau ($PREFIXE_UNITE-*) — REFUSÉ"
            souci=1; continue
        fi
        u13+=("$_u")
    done < <(unites_a_desarmer_du_13)
    if (( ${#u13[@]} == 0 )); then
        ko "§13.1           le juge ne sait plus lire la commande « systemctl disable » du §13 dans $(page_installation)"
        souci=1
    else
        systemctl disable --now "${u13[@]}" >/dev/null 2>&1
    fi
    local encore
    encore="$(systemctl list-units --all --no-legend "$PREFIXE_UNITE-*" 2>/dev/null)"
    if grep -qE '\b(active|waiting|running)\b' <<<"$encore"; then
        ko "§13.1           une unité de ce cerveau est encore vivante après le disable --now :"
        head -6 <<<"$encore" | while IFS= read -r l; do info "  $l"; done
        souci=1
    else
        ok "§13.1           les ${#u13[@]} unités que le §13 nomme, désarmées — liste RELUE dans la page, y compris la restauration hebdomadaire, celle qu'on oublie"
    fi

    # --- §13.2 : L'ADIEU — sauvegarder AVANT de détruire ------------------
    local adieu="$BASE_TRAVAIL/adieu-$ARAC_DB.dump" rc_adieu=0
    sudo -u postgres pg_dump -p "$PORT_PG" -Fc "$ARAC_DB" > "$adieu" 2>"$BASE_TRAVAIL/adieu.err" || rc_adieu=$?
    local toc=""
    (( rc_adieu == 0 )) && [[ -s "$adieu" ]] && toc="$(pg_restore --list "$adieu" 2>/dev/null | head -3)"
    if [[ -n "$toc" ]]; then
        ok "§13.2           l'adieu s'écrit et s'OUVRE : $(stat -c %s "$adieu") octets, sommaire lisible — c'est ce qui sépare une désinstallation d'une perte"
    else
        ko "§13.2           l'adieu prescrit par la page ne s'écrit pas ou ne s'ouvre pas (rc=$rc_adieu) — la page détruirait sans dump"
        head -3 "$BASE_TRAVAIL/adieu.err" 2>/dev/null | while IFS= read -r l; do info "  $l"; done
        souci=1
    fi

    # --- §13.3 : retirer les unités, APRÈS le disable --------------------
    rm -f /etc/systemd/system/"$PREFIXE_UNITE"-*.service \
          /etc/systemd/system/"$PREFIXE_UNITE"-*.timer 2>/dev/null
    rm -f /etc/systemd/system/*.target.wants/"$PREFIXE_UNITE"-* 2>/dev/null
    systemctl daemon-reload >/dev/null 2>&1
    systemctl reset-failed "$PREFIXE_UNITE-*" >/dev/null 2>&1

    # --- §13.4 : la base, sur SA grappe ----------------------------------
    sudo -u postgres dropdb -p "$PORT_PG" --if-exists "$ARAC_DB" >/dev/null 2>&1

    # --- §13.4 bis : LES BASES ANNEXES, chacune une copie complète -------
    local annexes n_annexes=0 d
    annexes="$(psql_super -d postgres -tAc \
        "SELECT datname FROM pg_database
          WHERE datname LIKE '${ARAC_DB}\\_restore\\_%'
             OR datname LIKE '${ARAC_DB}\\_restauree\\_%'
             OR datname LIKE '${ARAC_DB}\\_avarie\\_%'
          ORDER BY 1" 2>/dev/null)"
    while IFS= read -r d; do
        [[ -z "$d" ]] && continue
        n_annexes=$((n_annexes + 1))
        sudo -u postgres dropdb -p "$PORT_PG" --if-exists "$d" >/dev/null 2>&1
    done <<< "$annexes"
    info "§13.4 bis       $n_annexes base(s) annexe(s) détruite(s) — chacune portait une copie complète de la mémoire"

    # --- §13.5 : les rôles. LE contrôle de l'étape 4 bis : ils tombent TOUS
    #
    # LA LISTE EST CELLE DE LA PAGE, LUE DANS LA PAGE. On joue le §13 tel
    # qu'il est écrit — jamais tel qu'on se souvient qu'il est écrit. Si la
    # page en oubliait un, ce harnais l'oublierait avec elle, et le contrôle
    # de l'étape 9 le nommerait : c'est ainsi qu'un défaut de la page devient
    # visible au lieu d'être masqué par un juge plus complet qu'elle.
    local f refus_role=()
    local -a r13=()
    while IFS= read -r f; do [[ -n "$f" ]] && r13+=("$f"); done < <(suffixes_de_role_du_13)
    if (( ${#r13[@]} == 0 )); then
        ko "§13.5           le juge ne sait plus lire la boucle « DROP ROLE » du §13 dans $(page_installation)"
        souci=1
    fi
    for f in "${r13[@]}"; do
        psql_super -d postgres -qc "DROP ROLE IF EXISTS ${prefixe_role:-arac_$ARAC_DB}_$f" >/dev/null 2>&1 \
            || refus_role+=("${prefixe_role:-arac_$ARAC_DB}_$f")
    done
    if (( ${#refus_role[@]} == 0 )); then
        ok "§13.5           les ${#r13[@]} DROP ROLE que le §13 prescrit passent — c'est exactement ce que l'étape 4 bis débloque"
    else
        ko "§13.5           PostgreSQL refuse ces rôles : ${refus_role[*]} — une base annexe les retient encore"
        souci=1
    fi

    # --- §13.6 et §13.7 : le coffre, les dossiers, les estampilles -------
    local dossiers_de_ce_cerveau=(
        "$ARAC_ETC" "$ARAC_LOG_DIR" "$ARAC_BACKUP_DIR"
        "$ARAC_AGENT_HOME" "$ARAC_STATE_SERVICE"
    )
    for d in "${dossiers_de_ce_cerveau[@]}"; do
        _detruire_dossier "$d" || souci=1
    done
    rm -f "/var/lib/systemd/timers/stamp-$PREFIXE_UNITE-"*.timer 2>/dev/null

    # LES `rm -f` DU §13, JOUÉS DEPUIS LA PAGE ELLE-MÊME.
    #
    # Ici vivait une COPIE de quatre chemins. Elle a divergé trois fois de la
    # liste qu'elle recopiait (voir « LA LISTE DU §13, LUE DANS LA PAGE »), et
    # la troisième fois le juge en accusait la page. Il n'y a plus de copie :
    # `chemins_rm_du_13` OUVRE `docs/INSTALLATION.md`, y relève les `rm -f`
    # écrits hors commentaire dans le chapitre 13, et c'est CELA qu'on joue.
    # Le jour où la page nommera un sixième fichier, ce harnais le jouera sans
    # qu'une ligne d'ici ne bouge — et le jour où elle en retirera un, il
    # cessera de le jouer.
    #
    # Trois refus mécaniques, parce qu'une dérivation muette serait pire
    # qu'une copie :
    #   · liste VIDE  → la page a changé de forme et le juge ne sait plus la
    #     lire. C'est un ÉCHEC, dit comme tel, jamais un silence.
    #   · jeton NON RÉSOLU (`?…`) → une variable de la page que ce harnais ne
    #     sait pas remplacer. On la NOMME au lieu de l'inventer.
    #   · chemin REFUSÉ par la garde du démontage → on ne l'efface pas, on le
    #     dit. Ce harnais n'efface jamais un chemin qu'il n'a pas su relire.
    local _f_page _n_page=0
    local -a _page_lus=() _page_inconnus=()
    while IFS= read -r _f_page; do
        [[ -n "$_f_page" ]] || continue
        if [[ "$_f_page" == '?'* ]]; then _page_inconnus+=("${_f_page#\?}"); continue; fi
        _page_lus+=("$_f_page")
    done < <(chemins_rm_du_13)

    if (( ${#_page_lus[@]} == 0 )); then
        ko "§13.7           le juge ne sait plus lire la liste des « rm -f » du §13 dans $(page_installation) — il refuse d'en tenir une copie"
        souci=1
    fi
    if (( ${#_page_inconnus[@]} )); then
        ko "§13.7           le §13 nomme des chemins que ce harnais ne sait pas résoudre : ${_page_inconnus[*]}"
        souci=1
    fi

    local _cible
    for _f_page in "${_page_lus[@]}"; do
        # Un joker de la page se développe ICI, et chaque résultat passe la
        # garde séparément. Un joker qui ne s'apparie pas ne laisse rien.
        local -a _cibles=()
        if [[ "$_f_page" == *[\*\?\[]* ]]; then
            local _g; for _g in $_f_page; do [[ -e "$_g" ]] && _cibles+=("$_g"); done
        else
            _cibles=("$_f_page")
        fi
        for _cible in "${_cibles[@]}"; do
            [[ -e "$_cible" ]] || continue
            if garde_chemin_jetable "$_cible" "§13.7, ligne écrite dans la page" >/dev/null 2>&1; then
                rm -f "$_cible" && _n_page=$((_n_page + 1))
            else
                ko "§13.7           la garde refuse un chemin que la page fait effacer : $_cible"
                souci=1
            fi
        done
    done
    ok "§13.6/7         coffre, journaux, état, dumps, estampilles — et les ${#_page_lus[@]} « rm -f » RELUS DANS LE §13 ($_n_page présents, effacés)"

    # --- §13.8 : les deux comptes système --------------------------------
    local c
    for c in "$u_agent" "$u_service"; do
        [[ -n "$c" ]] || continue
        if ! sortie="$(garde_nom_systeme "$c" "compte" 2>&1)"; then
            ko "§13.8           $sortie"; souci=1; continue
        fi
        id -u "$c" >/dev/null 2>&1 || continue
        userdel "$c" >/dev/null 2>&1 || { ko "§13.8           userdel $c a échoué"; souci=1; }
    done

    # --- §13.9 : LE CONTRÔLE DE FIN, tel que la page le prescrit ---------
    local restes rc_restes=0
    restes="$( ops/uninstall_check.sh "$ARAC_DB" --port "$PORT_PG" 2>&1 )" || rc_restes=$?

    # LA SECONDE PASSE, QUE LA PAGE PRESCRIT ELLE-MÊME.
    #
    # Le §13.9 ne s'arrête pas au verdict : « S'il reste quelque chose,
    # `--gestes` imprime les commandes manquantes DANS L'ORDRE OÙ ELLES
    # PASSENT. […] Lisez-les, puis passez-les. » Le harnais fait donc ce que la
    # page dit de faire — et il DIT qu'il a dû le faire, avec la liste : une
    # seconde passe nécessaire est un manque de la liste ordonnée, pas un
    # détail. On n'exécute que ce qu'on sait relire : un effacement de FICHIER,
    # sur des chemins que la garde du démontage accepte un par un. Une base, un
    # rôle, un compte imprimés ici seraient REFUSÉS et signalés : à ce stade,
    # ils ne devraient plus exister.
    local -a passes=() refuses=()
    if (( rc_restes != 0 )); then
        local gestes g chemin
        gestes="$( ops/uninstall_check.sh "$ARAC_DB" --port "$PORT_PG" --gestes 2>&1 )"
        while IFS= read -r g; do
            g="${g#"${g%%[![:space:]]*}"}"
            [[ "$g" =~ ^(sudo[[:space:]]+)?rm[[:space:]]+-[rf]+[[:space:]]+\' ]] || continue
            while [[ "$g" =~ \'(/[^\']+)\' ]]; do
                chemin="${BASH_REMATCH[1]}"
                g="${g/\'$chemin\'/}"
                if garde_chemin_jetable "$chemin" "reste imprimé par le contrôle" >/dev/null 2>&1; then
                    rm -rf "$chemin" 2>/dev/null && passes+=("$chemin")
                else
                    refuses+=("$chemin")
                fi
            done
        done <<< "$gestes"
        rc_restes=0
        restes="$( ops/uninstall_check.sh "$ARAC_DB" --port "$PORT_PG" 2>&1 )" || rc_restes=$?
    fi

    if (( ${#refuses[@]} )); then
        ko "§13.9           le contrôle imprime des effacements que la garde REFUSE : ${refuses[*]}"
        souci=1
    fi
    if (( rc_restes == 0 )) && grep -qF "VERDICT : PROPRE" <<<"$restes"; then
        if (( ${#passes[@]} == 0 )); then
            ok "§13.9           ops/uninstall_check.sh : « VERDICT : PROPRE », code 0 — la liste ordonnée du §13 suffit, sans en inventer un seul geste"
        else
            # LE REPROCHE EST VÉRIFIÉ AVANT D'ÊTRE IMPRIMÉ — CONTRE LA PAGE,
            # PAS CONTRE UN SOUVENIR DE LA PAGE.
            #
            # C'est ici que la ⚠ mentait trois manches durant : elle affirmait
            # « le §13 ne les mentionne pas » sans jamais l'avoir demandé au
            # §13. On le lui demande. Un reste que la page NOMME n'est pas une
            # omission de la page : c'est un geste que ce juge a manqué, et
            # c'est alors LUI qu'on met en échec.
            local x _dans_la_page
            local -a hors_page=() dans_page=()
            for x in "${passes[@]}"; do
                _dans_la_page=0
                while IFS= read -r _f_page; do
                    [[ "$_f_page" == "$x" ]] && { _dans_la_page=1; break; }
                done < <(chemins_rm_du_13)
                if (( _dans_la_page )); then dans_page+=("$x"); else hors_page+=("$x"); fi
            done

            if (( ${#dans_page[@]} )); then
                ko "§13.9           le §13 NOMME ces chemins et ce juge ne les a pas effacés : ${dans_page[*]}"
                dire "                  Le reproche serait donc adressé à la page pour une omission du juge. Corriger le juge."
                souci=1
            fi
            if (( ${#hors_page[@]} )); then
                attn "§13.9           « VERDICT : PROPRE », code 0 — mais SEULEMENT APRÈS la seconde passe que le §13.9 prescrit."
                dire "                  Les gestes du §13, joués ici ligne par ligne — « rm -f » RELUS DANS LA PAGE compris —"
                dire "                  laissent ceci derrière eux :"
                for x in "${hors_page[@]}"; do dire "                    · $x"; done
                dire "                  Le contrôle de l'étape 9 les nomme et prescrit leur effacement ; le §13, LU À L'INSTANT"
                dire "                  dans $(page_installation), ne les nomme pas."
            fi
        fi
    else
        ko "§13.9           ops/uninstall_check.sh rend le code $rc_restes après une désinstallation menée À LA LETTRE, seconde passe comprise"
        grep -E '✗|reste|RESTE' <<<"$restes" | head -10 | while IFS= read -r l; do info "  $l"; done
        souci=1
    fi

    # --- §13.10 : LA MÉMOIRE DANS LE JOURNAL SYSTÈME, APRÈS LE DÉPART ----
    #
    # C'EST LA SEULE FUITE DU CHANTIER QU'AUCUN CONTRÔLE NE VOYAIT, ET LA
    # RAISON EN EST SIMPLE : PERSONNE NE PENSE À CHERCHER SA MÉMOIRE DANS UN
    # JOURNAL SYSTÈME. Le §13 efface la base, les rôles, le coffre, les
    # dossiers, les dumps, les unités, les estampilles et les comptes ; il n'a
    # jamais rien pu contre journald, qui garde des semaines et que systemd ne
    # sait pas purger unité par unité. Un utilisateur qui désinstalle croit être
    # parti — et le contenu de ses souvenirs reste lisible par tout compte du
    # groupe « systemd-journal ».
    #
    # Le témoin est ici parfait : les trois souvenirs de la bascule portent des
    # clés que RIEN d'autre sur cette machine ne peut écrire. Si l'une d'elles
    # se retrouve dans le journal des unités de ce cerveau, alors la mémoire a
    # survécu au départ — et on le dit en ÉCHEC, pas en réserve.
    #
    # On cherche à l'endroit exact où la fuite vivait (les unités de CE cerveau,
    # jamais celles d'un voisin), et on cherche les DEUX formes : la clé du
    # souvenir, et la phrase d'en-tête sous laquelle elle était imprimée.
    # LES TÉMOINS, AU PLURIEL, ET SUR LES DEUX CHEMINS D'ENTRÉE.
    #
    # Ce garde ne cherchait qu'UNE chaîne : `temoin-bascule-`, la clé des trois
    # souvenirs que l'étape 8 pose par `INSERT` psql. Deux trous, tous deux
    # mécaniques : (1) ces témoins-là n'entrent JAMAIS par l'API, or la seule
    # route qui ait fui est celle de l'API ; (2) chercher le témoin d'une
    # ancienne fuite ne peut, par construction, révéler aucune des suivantes.
    # On cherche donc maintenant TOUT ce que ce cerveau a reçu de reconnaissable
    # — la clé et la VALEUR des témoins de la bascule, la clé, la valeur, le
    # POURQUOI et le DOMAINE de l'atome écrit par la route réelle de l'étape 6 —
    # et l'en-tête sous lequel l'ancienne fuite s'imprimait.
    local temoin_cle='temoin-bascule-'
    local -a temoins=(
        "$temoin_cle"
        "Souvenir temoin numero"
        "temoin-route-$RUN"
        "TEMOINROUTE$RUN"
        "POURQUOIROUTE$RUN"
        "échantillon d'atomes réellement relus :"
    )
    local f_scope
    f_scope="$(printf '%s' "${FEUILLE_TEMOIN:-}" | tr -d '[:space:]')"
    [[ -n "$f_scope" ]] && temoins+=("$f_scope")
    if ! command -v journalctl >/dev/null 2>&1; then
        info "§13.10          journalctl absent : la recherche de mémoire dans le journal n'a pas pu avoir lieu"
        nonteste "la mémoire dans le journal système — journalctl absent de cette machine"
    else
        local fuite_j
        local -a motifs=()
        local t
        for t in "${temoins[@]}"; do [[ -n "$t" ]] && motifs+=(-e "$t"); done
        fuite_j="$(journalctl --quiet -u "$PREFIXE_UNITE-*" --no-pager -o cat 2>/dev/null \
                   | grep -F "${motifs[@]}" | head -5)"
        if [[ -z "$fuite_j" ]]; then
            ok "§13.10          le journal système ne rend plus un seul souvenir de ce cerveau — ${#temoins[@]} témoins cherchés sous « $PREFIXE_UNITE-* », dont ceux entrés par la ROUTE de l'API, après un départ déclaré PROPRE"
        else
            ko "§13.10          APRÈS LE DÉPART, LE JOURNAL SYSTÈME REND ENCORE LA MÉMOIRE de ce cerveau :"
            while IFS= read -r l; do info "  $l"; done <<<"$fuite_j"
            dire "                  journalctl -u $PREFIXE_UNITE-* --no-pager | grep '$temoin_cle'"
            dire "                  Le §13 ne peut rien contre journald : la correction est de ne pas y écrire."
            souci=1
        fi
    fi

    # --- CE QUE LA PAGE NE DEMANDE À PERSONNE ----------------------------
    #
    # « PROPRE » est rendu par un contrôle qui regarde les chemins PAR DÉFAUT.
    # On repose donc la question à la machine, sur les chemins que CETTE
    # installation a réellement employés, et à la grappe sur ce qu'elle porte.
    local bases_restantes roles_restants octets=0 traces=()
    bases_restantes="$(psql_super -d postgres -tAc \
        "SELECT datname FROM pg_database WHERE datname LIKE '${ARAC_DB}%' ORDER BY 1" 2>/dev/null)"
    [[ -n "${bases_restantes//[[:space:]]/}" ]] && traces+=("bases sur la grappe $PORT_PG : $(tr '\n' ' ' <<<"$bases_restantes")")
    roles_restants="$(psql_super -d postgres -tAc \
        "SELECT rolname FROM pg_roles WHERE rolname LIKE '%${ARAC_DB}%' ORDER BY 1" 2>/dev/null)"
    [[ -n "${roles_restants//[[:space:]]/}" ]] && traces+=("rôles sur la grappe $PORT_PG : $(tr '\n' ' ' <<<"$roles_restants")")
    for d in "${dossiers_de_ce_cerveau[@]}"; do
        [[ -e "$d" ]] || continue
        octets=$(( octets + $(du -sb "$d" 2>/dev/null | cut -f1) ))
        traces+=("dossier « $d » encore présent")
    done
    for c in "$u_agent" "$u_service"; do
        [[ -n "$c" ]] && id -u "$c" >/dev/null 2>&1 && traces+=("compte système « $c » encore présent")
    done

    if (( ${#traces[@]} == 0 )); then
        ok "aucune copie    plus une base, plus un rôle, plus un octet sous les dossiers de ce cerveau"
        ok "l'adieu         la SEULE copie de la mémoire qui subsiste est celle que le §13.2 fait écrire exprès : $adieu"
    else
        local t; for t in "${traces[@]}"; do ko "copie restante  $t"; done
        souci=1
    fi

    if (( souci )); then
        verdict "ÉCHEC" "les gestes du §13 ne suffisent pas à faire disparaître ce cerveau"
    else
        verdict "PROUVÉ" "les gestes du §13 sont joués à la lettre — les cinq unités, l'adieu vérifié, la base, les bases annexes, les cinq rôles, le coffre, les dossiers, les estampilles et les deux comptes ; ops/uninstall_check.sh conclut « PROPRE » en code 0, et il ne reste sur la machine ni base, ni rôle, ni octet de la mémoire de ce cerveau — sauf l'adieu, nommé"
    fi
}

# ===========================================================================
# Déroulé
# ===========================================================================

principal() {
    printf '\n  %s\n  %s\n\n' \
        "$(_c 1 "ARAC — test d'acceptation")" \
        "$(_c 2 "$(_trait 26)")"
    dire "  exécution   $RUN"
    dire "  mode        $( (( MODE_COMPLET )) && printf 'COMPLET (clés fournies, dépense réelle)' || printf 'GRATUIT (aucune clé, aucune dépense)')"
    dire "  cerveau     $CERVEAU        base $ARAC_DB"
    dire "  cluster     $PG_MAJEURE/$CLUSTER sur le port $PORT_PG"
    dire "  services    API $PORT_API · cockpit $PORT_COCKPIT"
    dire "  journal     $JOURNAL"

    preuve_production "avant" || {
        vide
        ko "$(_c 1 'LA PRODUCTION N'\''EST PAS SAINE AVANT MÊME DE COMMENCER.')"
        dire "     Rien n'a été créé. Réparez d'abord — ce test ne s'exécute pas"
        dire "     sur une machine dont l'état initial est déjà douteux."
        exit 3
    }

    gardes || exit 3

    # Le démontage n'est armé qu'ICI : avant les gardes, il n'aurait rien à
    # démonter, et il porterait des valeurs qui n'ont pas encore été validées.
    trap demonter EXIT INT TERM

    local n=0 ligne
    for ligne in "${PROGRAMME[@]}"; do
        n=$((n + 1))
        etape "$n" "${ligne%%|*}" "${ligne##*|}"
    done

    # Le critère est « les NEUF étapes, sans intervention » — arriver ET
    # partir. Une étape en échec, une étape jamais exercée, ou un geste
    # manuel : chacun suffit à ce que la réponse soit non.
    local i
    for i in "${!E_VERDICT[@]}"; do
        case "${E_VERDICT[$i]}" in ÉCHEC|NON_TESTÉ) return 1 ;; esac
    done
    (( ${#INTERVENTIONS[@]} )) && return 1
    return 0
}

# --- La version majeure de PostgreSQL, constatée et non supposée ------------
PG_MAJEURE="$(ls /usr/lib/postgresql 2>/dev/null | sort -V | tail -1)"
if [[ -z "$PG_MAJEURE" ]]; then
    printf '\n  PostgreSQL est introuvable sous /usr/lib/postgresql.\n\n' >&2
    exit 3
fi

mkdir -p "$(dirname "$JOURNAL")"
principal 2>&1 | tee "$JOURNAL"
exit "${PIPESTATUS[0]}"
