# shellcheck shell=bash
# ---------------------------------------------------------------------------
# core.sh — les règles du jeu.
#
# Quatre garanties tiennent ce fichier, et tout le reste du bootstrap en
# dépend :
#
#   IDEMPOTENT   — chaque geste est écrit pour être rejouable. On ne crée
#                  jamais « si absent » sans savoir dire ce qu'on a trouvé.
#   REPRENABLE   — l'état d'avancement est écrit sur disque après chaque
#                  étape réussie. Une panne au milieu ne coûte que l'étape.
#   SIMULABLE    — `--dry-run` n'écrit rien, ne crée rien, ne se connecte à la
#                  base qu'en LECTURE. La fonction `reel` est le seul portail.
#   EXPLICITE    — aucune destruction sans avoir dit ce qui serait détruit.
#
# Tout chemin est paramétré. Rien n'est en dur. Voir `--help` pour la liste
# complète des variables d'environnement reconnues.
# ---------------------------------------------------------------------------

# Ces variables sont consommées par les autres bibliothèques, sourcées ensemble.
# shellcheck disable=SC2034
ARAC_VERSION_BOOTSTRAP="1.0.0"

# --- Options ----------------------------------------------------------------

SIMULATION=0        # --dry-run
ACCORD_AUTOMATIQUE=0 # --yes
BAVARD=0            # --bavard
REJOUER=0           # --rejouer
DEPUIS=""           # --from
SEULEMENT=""        # --only
MODE=""             # check | verify | etapes | ""

# --- Les étapes, dans l'ordre ----------------------------------------------

ETAPES=(prereqs config base vecteurs migrations scopes secrets cles services controle)

#: LE TOTAL SE COMPTE, IL NE SE RECOPIE PAS. Il valait « 11 » en dur : le
#: nombre d'étapes plus l'épilogue « la suite ». Inséré une onzième étape, le
#: chiffre restait à 11 et chaque en-tête annonçait « ÉTAPE 7 / 11 » sur une
#: installation qui en comptait douze. Le seul terme qui ne se déduit pas de
#: `ETAPES` est l'épilogue, et il est nommé ici.
TOTAL_ETAPES=$(( ${#ETAPES[@]} + 1 ))   # les étapes + l'épilogue « la suite »

#: LE RANG D'UNE ÉTAPE, LU DANS L'ORDRE OÙ ELLE PASSE.
#:
#: Chaque `etape_entete` portait son numéro en dur — `etape_entete 7
#: "$TOTAL_ETAPES" …` dans `secrets.sh`, `9` dans `services.sh`, et ainsi de
#: suite. C'était une SECONDE écriture de l'ordre défini juste au-dessus :
#: insérer une étape au milieu laissait dix en-têtes annoncer un rang faux,
#: sans qu'aucun contrôle ne puisse le voir. On le demande à `ETAPES`.
#:
#: Rend le rang (1..n) sur la sortie standard ; rend 1 et n'imprime rien si le
#: nom est inconnu — l'appelant verra un rang vide plutôt qu'un rang faux.
rang_etape() { # nom
    local nom="${1-}" i
    for i in "${!ETAPES[@]}"; do
        if [[ "${ETAPES[$i]}" == "$nom" ]]; then
            printf '%s' "$(( i + 1 ))"
            return 0
        fi
    done
    return 1
}


# --- Les cinq rôles, nommés UNE FOIS ----------------------------------------
#
# CE BLOC EXISTE PARCE QUE LA MÊME RÈGLE ÉTAIT ÉCRITE DEUX FOIS, ET QUE L'UNE
# DES DEUX AVAIT DÉJÀ PERDU UN RÔLE.
#
# `lib/config.sh` fabriquait `R_ADMIN`…`R_BACKUP` depuis `ARAC_ROLE_PREFIX` ;
# `checks/verify_install.sh` refaisait les MÊMES quatre lignes de son côté —
# et n'avait jamais eu la cinquième. Deux fichiers, une seule règle, aucun lien
# entre eux : c'est la forme exacte du défaut que ce dépôt a dû corriger trois
# fois sur la liste du §13. Les deux sourcent ce fichier ; la règle vit donc
# ici, et nulle part ailleurs.
#
# L'ordre et le contenu de `SUFFIXES_DE_ROLE` répondent à `db/alembic/roles.py`,
# qui est la migration qui les CRÉE : `tests/` tient les deux ensemble.

#: Les cinq suffixes, dans l'ordre de la migration qui les crée.
SUFFIXES_DE_ROLE=(admin app agent readonly backup)

#: LES DSN, UNE LIGNE PAR RÔLE : « variable ARAC · variable DATABASE · nom du
#: rôle · nom du mot de passe ».
#:
#: Le cinquième rôle — `backup` — n'y figure pas : il n'a ni mot de passe ni
#: DSN, il n'existe que parce que deux migrations lui donnent des droits. Cette
#: absence est une DÉCISION, elle est donc écrite, et une seule fois.
#:
#: Cette table remplace TROIS écritures de la même liste : l'étape 3 qui écrit
#: les DSN (`lib/database.sh`), l'étape 7 qui les traduit en `DATABASE_URL_*`
#: (`lib/secrets.sh`), et le contrôle qui se connecte sous chacun
#: (`checks/verify_install.sh`). Un cinquième DSN ajouté à l'une des trois
#: restait muet dans les deux autres.
#:
#: LES NOMS SONT ÉCRITS EN TOUTES LETTRES, ET C'EST LE POINT DÉLICAT.
#: `bootstrap/checks/audit_env.py` lit ce dépôt pour vérifier qu'aucune
#: variable n'est lue sans être déclarée dans `.env.example` ou le contrat.
#: Composer le nom à l'exécution — `"ARAC_DB_URL_$X"` — le rend AVEUGLE : il
#: ne voit plus qu'un fragment, `ARAC_DB_URL_`, qu'il range en « non classée »,
#: et les quatre vraies variables cessent d'être auditées. Mesuré : trois
#: tests rouges et `--dry-run` en code 1. Dériver ne vaut jamais qu'on rende
#: un garde aveugle ; ici, le remède est de n'écrire la liste QU'UNE FOIS,
#: en clair.
DSN_PAR_ROLE=(
    "ARAC_DB_URL_ADMIN    DATABASE_URL_ADMIN    R_ADMIN    pwd_admin"
    "ARAC_DB_URL_APP      DATABASE_URL_APP      R_APP      pwd_app"
    "ARAC_DB_URL_AGENT    DATABASE_URL_AGENT    R_AGENT    pwd_agent"
    "ARAC_DB_URL_READONLY DATABASE_URL_READONLY R_READONLY pwd_readonly"
)

#: Pose `R_ADMIN`, `R_APP`, `R_AGENT`, `R_READONLY`, `R_BACKUP` depuis le
#: préfixe. Aucun appelant ne réécrit ces noms.
poser_noms_de_roles() { # [prefixe]
    local p="${1:-${ARAC_ROLE_PREFIX:-}}" s
    if [[ -z "$p" ]]; then return 1; fi
    for s in "${SUFFIXES_DE_ROLE[@]}"; do
        printf -v "R_$(printf '%s' "$s" | tr 'a-z' 'A-Z')" '%s' "${p}_${s}"
    done
    return 0
}

declare -A TITRE_ETAPE=(
    [prereqs]="Constater les prérequis"
    [config]="Lire la description issue de l'entretien"
    [base]="Créer la base et ses rôles"
    [vecteurs]="Activer pgvector"
    [migrations]="Appliquer les migrations"
    [scopes]="Semer votre taxonomie"
    [secrets]="Engendrer les secrets"
    [cles]="Les clés externes, et ce qu'elles coûtent"
    [services]="Installer les services"
    [controle]="Vérifier, et rendre un rapport"
)

# --- Simulation -------------------------------------------------------------

#: `reel` est le SEUL portail vers un effet de bord. Aucune écriture, aucune
#: création, aucun `systemctl` ne doit exister hors d'un `reel || return 0`.
reel() { (( SIMULATION == 0 )); }

simulation_prefixe() { reel || printf '  %s ' "$(_c 35 '[simulation]')"; }

# --- UNE COMMANDE IMPRIMÉE EST UN GESTE PRESCRIT ----------------------------
#
# CE QUE CE BLOC EXISTE POUR EMPÊCHER, ET C'EST MESURÉ.
#
# La simulation lancée ainsi —
#
#     ARAC_DB_PORT=5640 ARAC_API_PORT=8290 ./bootstrap/bootstrap.sh --dry-run
#
# — annonçait « serveur 127.0.0.1:5640 », « Ce cluster PostgreSQL (port 5640) »,
# « ports 8290 (API) · 8292 (cockpit) », puis se terminait sur :
#
#     [simulation] Aucun changement n'a été appliqué.
#     Pour agir :
#         sudo ./bootstrap/bootstrap.sh
#
# Cette dernière ligne est celle qu'on recopie — c'est la seule qui dise « pour
# agir ». Recopiée telle quelle, elle rend « serveur 127.0.0.1:5432 » : la
# grappe par défaut de la machine, c'est-à-dire, sur un serveur qui héberge
# déjà un cerveau, celle du voisin. Le port avait changé sans qu'une ligne ne
# l'annonce, à la seule seconde du parcours où l'erreur ne se rattrape pas :
# une fois le port retenu dans le coffre, ce bootstrap REFUSE (code 6) d'en
# changer, et déplacer un cerveau d'une grappe à une autre est une migration de
# données, jamais un réglage.
#
# LA RÈGLE, DÉSORMAIS MÉCANIQUE : aucun texte de ce bootstrap ne cite
# `./bootstrap/bootstrap.sh` en dur. Toute citation passe par `geste_bootstrap`,
# qui reporte ce que l'invocation courante a RÉELLEMENT employé et que le
# coffre ne rendra pas tout seul. C'est la règle « un outil qui se cite
# lui-même doit se citer entier », déjà appliquée à `ops/uninstall_check.sh`.
#
# CE QU'ON REPORTE, ET CE QU'ON NE REPORTE PAS. On ne recopie que les quatre
# variables qui décident OÙ le cerveau se pose, et seulement celles que
# l'APPELANT a posées lui-même : le reste est déduit, donc se redéduira. Et
# quand le coffre porte déjà la même valeur, on l'omet — il la rendra de
# lui-même (`_resoudre_ports`, et la relecture du port en tête de l'étape 2) et
# une ligne plus courte est une ligne mieux recopiée.

#: Les variables d'implantation posées par l'appelant, relevées AVANT toute
#: résolution — c'est le seul instant où l'on peut distinguer « 5432 parce que
#: vous l'avez demandé » de « 5432 faute de mieux ».
ARAC_VARS_APPELANT=""
for _v in ARAC_DB_HOTE ARAC_DB_PORT ARAC_API_PORT ARAC_COCKPIT_PORT; do
    [[ -n "${!_v:-}" ]] && ARAC_VARS_APPELANT="$ARAC_VARS_APPELANT $_v"
done
unset _v

#: Le préfixe à reporter dans toute commande imprimée. Vide quand il n'y a
#: rien à transmettre — c'est le cas courant, et il ne doit rien coûter.
prefixe_invocation() {
    local out="" v val retenu
    for v in ARAC_DB_HOTE ARAC_DB_PORT ARAC_API_PORT ARAC_COCKPIT_PORT; do
        [[ " $ARAC_VARS_APPELANT " == *" $v "* ]] || continue
        val="${!v:-}"
        [[ -z "$val" ]] && continue
        retenu=""
        [[ -n "${ARAC_ENV_FILE:-}" && -r "${ARAC_ENV_FILE:-}" ]] &&
            retenu="$(lire_var "$ARAC_ENV_FILE" "$v" 2>/dev/null || true)"
        [[ "$retenu" == "$val" ]] && continue   # le coffre le rendra tout seul
        out="$out$v=$val "
    done
    printf '%s' "$out"
}

#: La commande à imprimer. `geste_bootstrap "--from services"` rend
#: « sudo ARAC_DB_PORT=5640 ./bootstrap/bootstrap.sh --from services ».
#: `geste_bootstrap "" nosudo` rend la même chose sans `sudo` (la simulation,
#: qui n'en a pas besoin).
geste_bootstrap() { # [arguments] [nosudo]
    local args="${1:-}" sans_sudo="${2:-}" tete="sudo "
    [[ "$sans_sudo" == nosudo ]] && tete=""
    printf '%s%s./bootstrap/bootstrap.sh%s' "$tete" "$(prefixe_invocation)" "${args:+ $args}"
}

# --- Accord de l'utilisateur -----------------------------------------------

confirmer() { # question [defaut_oui]
    local question="$1" defaut="${2:-non}" rep suffixe
    if (( ACCORD_AUTOMATIQUE )); then
        note "  ($question → oui, --yes)"
        return 0
    fi
    if ! reel; then
        note "  ($question → accord supposé, simulation)"
        return 0
    fi
    if [[ ! -t 0 ]]; then
        echec "accord impossible à obtenir" \
              "La question « $question » exige une réponse, mais l'entrée standard
n'est pas un terminal." \
              "Relancez depuis un terminal, ou acceptez d'avance :
  $(geste_bootstrap "--yes")"
        exit 3
    fi
    [[ "$defaut" == oui ]] && suffixe="O/n" || suffixe="o/N"
    while true; do
        read -r -p "  $(_c 36 "$question ($suffixe) ")" rep || rep=""
        rep="${rep,,}"
        [[ -z "$rep" ]] && rep="${defaut:0:1}"
        case "$rep" in
            o|oui|y|yes) return 0 ;;
            n|non|no)    return 1 ;;
            *) mal "Répondez par o (oui) ou n (non)." ;;
        esac
    done
}

# --- Fichier d'avancement ---------------------------------------------------

#: `ETAPES_HERITEES` — ce que le fichier portait AVANT ce lancement, et rien
#: d'autre. `ETAPES_FAITES` grossit au fil de la course : une étape que ce
#: lancement-ci vient d'accomplir y entre aussitôt. Confondre les deux faisait
#: dire au bootstrap, à la PREMIÈRE installation d'un clone neuf et juste après
#: avoir déroulé l'étape 2 sous les yeux de l'utilisateur : « ⚠ 1 étape(s) sur
#: 10 ont déjà été accomplies ici · config », puis « effacez le fichier
#: d'avancement — il vient de quelqu'un d'autre : rm … ». Trois faussetés dans
#: un même encadré : l'étape venait d'être accomplie ICI et MAINTENANT, le
#: fichier appartenait à cette installation-là, et le geste prescrit jetait son
#: propre avancement.
etat_charger() {
    ETAT_FICHIER="${ARAC_ETAT:-$ARAC_HOME/.bootstrap-install.state}"
    ETAPES_FAITES=""
    [[ -r "$ETAT_FICHIER" ]] && ETAPES_FAITES="$(cat "$ETAT_FICHIER" 2>/dev/null || true)"
    ETAPES_HERITEES="$ETAPES_FAITES"
    return 0
}

#: L'avancement appartient à UN cerveau, pas au dépôt qui l'a installé.
#:
#: Le fichier d'avancement était unique par clone. Installer un second cerveau
#: depuis le même dépôt le faisait donc lire l'avancement du PREMIER : « Créer
#: la base — déjà accomplie lors d'un passage précédent », six fois de suite,
#: et un bootstrap qui se termine en n'ayant rien fait. Le message était même
#: rassurant, ce qui est le pire des cas : rien à réparer, rien à chercher,
#: aucune base créée.
#:
#: Le nom porte donc désormais celui de la base. Appelée à la fin de l'étape 2,
#: dès que ce nom est connu — et pas avant, puisqu'il est DÉDUIT de
#: config/brain.toml.
#:
#: On ne REPREND PAS l'ancien fichier sans nom de cerveau, et c'est délibéré :
#: rien ne dit à quel cerveau il appartenait. Le recopier reviendrait à
#: réintroduire exactement le défaut qu'on corrige, au premier lancement du
#: second cerveau. Le prix de ne pas le faire est nul : une installation déjà
#: menée rejoue des étapes idempotentes, ce que ce bootstrap promet de savoir
#: faire. Le prix de se tromper de cerveau, lui, est une base jamais créée.
etat_ancrer() { # exige ARAC_DB
    [[ -n "${ARAC_ETAT:-}" ]] && return 0        # choix explicite : on n'y touche pas
    ETAT_FICHIER="$ARAC_HOME/.bootstrap-install.$ARAC_DB.state"
    ETAPES_FAITES=""
    [[ -r "$ETAT_FICHIER" ]] && ETAPES_FAITES="$(cat "$ETAT_FICHIER" 2>/dev/null || true)"
    ETAPES_HERITEES="$ETAPES_FAITES"
    return 0
}

etape_faite() { [[ " $ETAPES_FAITES " == *" $1 "* ]]; }
etape_heritee() { [[ " ${ETAPES_HERITEES:-} " == *" $1 "* ]]; }

etape_marquer() {
    etape_faite "$1" && return 0
    ETAPES_FAITES="$ETAPES_FAITES $1"
    reel || return 0
    printf '%s\n' "${ETAPES_FAITES# }" > "$ETAT_FICHIER" 2>/dev/null || true
}

# --- Privilèges -------------------------------------------------------------

detecter_sudo() {
    if [[ $EUID -eq 0 ]]; then SUDO=""; else SUDO="sudo"; fi
    if command -v sudo >/dev/null 2>&1; then SUDO_DISPO=1; else SUDO_DISPO=0; fi
}

exiger_root() { # etape
    [[ $EUID -eq 0 ]] && return 0
    if (( SUDO_DISPO )); then return 0; fi
    echec "privilèges insuffisants pour l'étape « $1 »" \
          "Créer une base, écrire dans /etc et installer des unités systemd
demande root. Ni root ni sudo ne sont disponibles." \
          "$(geste_bootstrap)"
    exit 4
}

# Exécute psql en tant que superutilisateur PostgreSQL.
#: Le `-p` n'est pas décoratif : sans lui, TOUT le DDL (créer la base, les
#: rôles, les extensions, semer la taxonomie) part sur la grappe PostgreSQL par
#: défaut, pendant que les DSN écrits dans le fichier d'environnement, eux,
#: portent bien `ARAC_DB_PORT`. Poser `ARAC_DB_PORT=5433` construisait donc le
#: cerveau sur le port 5432 et disait aux services d'aller le chercher sur le
#: 5433 : rien n'échoue à l'installation, tout échoue au démarrage.
#: On garde la socket Unix (donc l'authentification `peer`, donc aucun mot de
#: passe de superutilisateur nulle part) : les sockets sont numérotées par
#: port, `-p` suffit à désigner la bonne grappe.
psql_super() { # arguments psql
    local -a base=(-v ON_ERROR_STOP=1 -p "${ARAC_DB_PORT:-5432}")
    if [[ $EUID -eq 0 ]] && command -v sudo >/dev/null 2>&1; then
        sudo -u "$ARAC_PG_SUPERUSER" psql "${base[@]}" "$@"
    elif [[ $EUID -eq 0 ]]; then
        su - "$ARAC_PG_SUPERUSER" -c "psql $(printf '%q ' "${base[@]}" "$@")"
    else
        sudo -u "$ARAC_PG_SUPERUSER" psql "${base[@]}" "$@"
    fi
}

#: Lecture seule, autorisée même en simulation : on interroge le catalogue,
#: on n'y touche pas. Retourne la chaîne vide si la base est injoignable.
pg_lire() { # requete
    psql_super -d postgres -tAc "$1" 2>/dev/null || true
}

# --- LA VERSION MINIMALE DE PGVECTOR ----------------------------------------
#
# Le type halfvec (colonnes d'embeddings, index HNSW) n'existe qu'à partir de
# pgvector 0.7.0. Ubuntu 24.04 livre 0.6.0 : le paquet s'installe, l'extension
# se crée, puis la première migration échoue sur « type "halfvec" does not
# exist ». Le seuil est défini ICI, une seule fois ; l'étape 1 (constat), l'étape 4
# (activation) et la documentation le citent.
ARAC_PGVECTOR_MIN="0.7.0"

# Comparaison pure, sans dépendance : succès si $1 >= $2, composante par
# composante et numériquement (0.10.0 > 0.7.0). Une version vide ou illisible
# (rien d'autre que « N.N » ou « N.N.N ») est REFUSÉE : mieux vaut un faux refus
# expliqué qu'une migration qui casse au milieu.
version_au_moins() { # version minimum
    local v="${1:-}" min="${2:-}" re='^[0-9]+(\.[0-9]+){1,2}$'
    [[ "$v" =~ $re && "$min" =~ $re ]] || return 1
    local -a a b
    IFS=. read -r -a a <<< "$v"
    IFS=. read -r -a b <<< "$min"
    local i x y
    for i in 0 1 2; do
        x="${a[i]:-0}"; y="${b[i]:-0}"
        (( 10#$x > 10#$y )) && return 0
        (( 10#$x < 10#$y )) && return 1
    done
    return 0
}

# Le remède, partagé par l'étape 1 et l'étape 4 : le paquet du dépôt Ubuntu est
# trop vieux, il faut le dépôt officiel PostgreSQL (PGDG).
remede_pgvector_pgdg() {
    printf '%s\n' \
"sudo apt install -y postgresql-common && sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
sudo apt install postgresql-16-pgvector
sudo systemctl restart postgresql"
}

# --- À QUI APPARTIENT CE PORT ? ---------------------------------------------
#
# Un numéro de port appartient à la MACHINE, jamais à un cerveau. 8000 et 8100
# sont les valeurs par défaut de TOUS les cerveaux : sur un serveur qui en
# héberge deux, ou qui garde les restes d'un essai, la question « quelqu'un
# écoute-t-il sur 8100 ? » ne dit rien de l'installation qu'on contrôle.
#
# Elle est même trompeuse dans le sens le plus coûteux. Les unités sont en
# `Type=simple` : systemd les déclare `active` dès le fork, AVANT que le
# programme ait seulement tenté d'ouvrir sa socket. Un cockpit qui redémarre en
# boucle sur « address already in use » est donc `active` par intermittence,
# pendant qu'un AUTRE processus tient le port — et le contrôle décernait un ✓.
#
# On rattache donc la socket à son propriétaire, et le propriétaire à son unité.

#: Les PID que systemd attribue à une unité : le principal, plus les enfants
#: que porte son cgroup (un serveur multi-workers n'écoute pas toujours depuis
#: son PID principal).
pids_unite() { # unite
    command -v systemctl >/dev/null 2>&1 || return 1
    local principal cg
    principal="$(systemctl show -p MainPID --value "$1" 2>/dev/null || true)"
    [[ -n "$principal" && "$principal" != 0 ]] && printf '%s\n' "$principal"
    cg="/sys/fs/cgroup/system.slice/$1/cgroup.procs"
    [[ -r "$cg" ]] && cat "$cg" 2>/dev/null
    return 0
}

#: Les PID qu'une ligne de `ss -ltnHp` désigne : users:(("uvicorn",pid=42,fd=8))
pids_socket() { # ligne
    printf '%s\n' "${1-}" | grep -oE 'pid=[0-9]+' | cut -d= -f2
}

#: 0 la socket appartient à cette unité · 1 elle appartient à quelqu'un d'autre
#: · 2 on n'a PAS PU le savoir (ss sans droits ne montre aucun propriétaire).
#: Le troisième code n'est pas une commodité : sans lui, « je n'ai pas vu de
#: PID » deviendrait « ce n'est pas le nôtre », c'est-à-dire une panne inventée.
socket_appartient_a() { # ligne_ss unite
    local -a du_socket=() de_lunite=()
    mapfile -t du_socket < <(pids_socket "$1")
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

# --- LE NOM DES RÔLES -------------------------------------------------------

#: Refuse un préfixe qui produirait un identifiant SQL douteux — ou TRONQUÉ.
#:
#: PostgreSQL coupe tout identifiant à 63 octets sans le dire. Deux cerveaux
#: aux noms longs et voisins produiraient donc deux préfixes distincts et un
#: seul rôle réel : la collision silencieuse que ce nommage existe pour
#: empêcher, réintroduite par la porte de derrière.
#:
#: Aucun nom de rôle n'est jamais cité entre guillemets dans le DDL engendré :
#: un identifiant qui aurait besoin de guillemets est un identifiant qu'on
#: refuse. C'est ce qui interdit, par construction, qu'un nom de cerveau
#: devienne une injection SQL au moment du CREATE ROLE.
LONGUEUR_MAX_PREFIXE_ROLE=54   # 63 - len("_readonly")

_valider_prefixe_role() { # prefixe
    local p="$1"
    if [[ ! "$p" =~ ^[a-z_][a-z0-9_]*$ ]]; then
        vide
        mal "$(_c 1 'Le préfixe des rôles PostgreSQL est refusé.')"
        vide
        dire "Préfixe calculé   $p"
        vide
        note "Attendu : minuscules, chiffres et « _ », commençant par une lettre
ou « _ ». Aucun nom de rôle n'est cité entre guillemets dans le DDL
engendré — un identifiant qui en aurait besoin est un identifiant
qu'on refuse, et c'est ce qui interdit qu'un nom de cerveau devienne
une injection SQL.

Le préfixe vient de brain.name (config/brain.toml). Corrigez-le, ou
posez ARAC_ROLE_PREFIX explicitement."
        vide
        return 1
    fi
    if (( ${#p} > LONGUEUR_MAX_PREFIXE_ROLE )); then
        vide
        mal "$(_c 1 'Le nom de ce cerveau est trop long pour nommer ses rôles.')"
        vide
        dire "Préfixe calculé   $p   (${#p} caractères, maximum $LONGUEUR_MAX_PREFIXE_ROLE)"
        vide
        note "PostgreSQL tronque les identifiants à 63 octets SANS erreur, et le
plus long suffixe est « _readonly ». Deux cerveaux aux noms longs et
voisins finiraient donc par partager un rôle sans que rien ne le
signale — exactement la collision que ce nommage existe pour empêcher,
et sous la forme la plus difficile à voir.

Raccourcissez brain.name dans config/brain.toml."
        vide
        return 1
    fi
    return 0
}

# --- LES COMPTES SYSTÈME ----------------------------------------------------
#
# Même doctrine que les rôles PostgreSQL, sur une autre limite dure : Linux
# borne un nom de compte à 32 octets (`UT_NAMESIZE`), et `useradd` refuse
# au-delà. La différence tient dans la façon de traiter un nom trop long.
#
# Pour un rôle, on REFUSE : une base et cinq rôles se renomment en changeant
# `brain.name`, avant que quoi que ce soit n'existe. Ici, refuser reviendrait à
# interdire un nom de cerveau parfaitement légitime pour une contrainte que
# l'utilisateur n'a aucun moyen de connaître — et à l'étape 9, c'est-à-dire
# après la base, les rôles, les migrations et les secrets.
#
# On tronque donc, MAIS jamais à sec : six caractères d'empreinte du nom
# complet sont recollés au bout. Tronquer sans empreinte refabriquerait, au
# vingtième caractère, exactement le nom partagé qu'on est en train de
# supprimer — deux cerveaux « recherche_documentaire_alpha » et
# « recherche_documentaire_beta » retomberaient sur le même compte, donc sur
# le même UID, donc sur le même `/proc/<pid>/environ`.
LONGUEUR_MAX_COMPTE=31   # 32 - le NUL final

#: Le nom de compte système de CE cerveau, pour un rôle donné (`arac`,
#: `aracagent`). Déterministe : deux appels rendent la même valeur, et une
#: réinstallation retombe sur le compte qu'elle avait créé.
_compte_systeme() { # prefixe
    local prefixe="$1" nom="$1_${ARAC_DB}"
    (( ${#nom} <= LONGUEUR_MAX_COMPTE )) && { printf '%s' "$nom"; return 0; }
    local empreinte place
    empreinte="$(printf '%s' "$ARAC_DB" | sha256sum | cut -c1-6)"
    place=$(( LONGUEUR_MAX_COMPTE - ${#prefixe} - 8 ))   # "_" + tronqué + "_" + 6
    (( place < 1 )) && place=1
    printf '%s_%s_%s' "$prefixe" "${ARAC_DB:0:place}" "$empreinte"
}

#: Refuse un nom de BASE qui ne serait pas un identifiant PostgreSQL banal.
#:
#: POURQUOI CETTE FONCTION EXISTE, ET C'EST UNE PORTE QU'ON A LAISSÉE OUVERTE
#: DEUX MANCHES. `CREATE DATABASE`, `ALTER DATABASE`, `DROP DATABASE` et
#: `UPDATE pg_database` n'acceptent AUCUN paramètre lié : le nom est forcément
#: interpolé dans du texte SQL. Le bootstrap exécute ce texte sous
#: `sudo -u postgres`, c'est-à-dire en SUPERUTILISATEUR, sans qu'aucun humain
#: ne le relise — contrairement au bloc imprimé par
#: `ops/restore_verify.sh --prepare-template`, qui au moins passe sous les yeux
#: de quelqu'un. Un nom de base qui vient de l'ENVIRONNEMENT (ARAC_DB,
#: ARAC_RESTORE_TEMPLATE_DB) est donc, sans ce refus, une injection SQL
#: exécutée par le superutilisateur du serveur.
#:
#: Ce que cela coûte au voisin, mesuré : une instruction injectée dans le DDL
#: du gabarit marque la base d'un AUTRE cerveau `datistemplate = true`. Le
#: dépôt écrit lui-même ce que cela veut dire (database.sh, juste au-dessus du
#: geste) : cette base devient COPIABLE par tout rôle CREATEDB de la grappe, et
#: elle REFUSE d'être détruite. Sa mémoire est lisible, et sa désinstallation
#: est cassée.
#:
#: Même classe lexicale que `_valider_prefixe_role`, et c'est normal : une base
#: et un rôle sont deux identifiants PostgreSQL. 63 octets est la limite réelle
#: (NAMEDATALEN - 1) ; au-delà PostgreSQL TRONQUE SANS ERREUR, et deux cerveaux
#: aux noms longs et voisins se retrouvent sur la même base.
_valider_nom_base() { # nom variable [d_ou_vient_il]
    local nom="$1" var="$2" origine="${3:-}"
    if [[ ! "$nom" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then
        vide
        mal "$(_c 1 'Un nom de base PostgreSQL est refusé.')"
        vide
        dire "$var   $nom"
        vide
        note "Attendu : minuscules, chiffres et « _ », commençant par une lettre ou
« _ », 63 caractères au plus.

Ce nom finit interpolé dans du DDL — CREATE DATABASE, ALTER DATABASE,
UPDATE pg_database — qui n'accepte aucun paramètre lié, et que ce
bootstrap exécute en SUPERUTILISATEUR PostgreSQL. Il n'y a pas d'autre
protection que ce refus, et un superutilisateur peut rendre la base du
cerveau VOISIN copiable par tout le monde, ou indestructible.${origine:+

$origine}"
        vide
        return 1
    fi
    return 0
}

#: Refuse un nom de compte que `useradd` refuserait — ou qu'il tronquerait.
_valider_compte_systeme() { # nom variable
    local nom="$1" var="$2"
    if [[ ! "$nom" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
        vide
        mal "$(_c 1 'Le nom de compte système est refusé.')"
        vide
        dire "$var   $nom"
        vide
        note "Attendu : minuscules, chiffres, « _ » et « - », commençant par une
lettre ou « _ ». C'est ce que `useradd` accepte ; au-delà, la création
du compte échoue à l'étape 9, après la base, les rôles et les secrets."
        vide
        return 1
    fi
    if (( ${#nom} > LONGUEUR_MAX_COMPTE )); then
        vide
        mal "$(_c 1 'Le nom de compte système est trop long.')"
        vide
        dire "$var   $nom   (${#nom} caractères, maximum $LONGUEUR_MAX_COMPTE)"
        vide
        note "Linux borne un nom de compte à 32 octets. Le nom déduit du cerveau
tient dans cette limite tout seul — cette erreur ne peut venir que
d'une valeur posée à la main. Raccourcissez-la."
        vide
        return 1
    fi
    return 0
}

# --- LES PORTS --------------------------------------------------------------
#
# Un numéro de port appartient à la MACHINE, jamais à un cerveau. Le constater
# AVANT d'attribuer est la seule façon de ne pas écrire une unité condamnée :
# une fois l'unité posée et armée, l'échec de liaison ne se voit plus que dans
# le journal, pendant que le port répond — servi par son occupant légitime.

#: Vrai si PERSONNE n'écoute sur ce port. Sans `ss`, on ne conclut rien : la
#: fonction rend 2, et l'appelant refuse d'attribuer à l'aveugle plutôt que de
#: supposer libre. Supposer libre est précisément ce qui a lié le 8000.
port_libre() { # port
    command -v ss >/dev/null 2>&1 || return 2
    local ligne
    ligne="$(ss -ltnH "sport = :$1" 2>/dev/null | head -1)"
    [[ -z "$ligne" ]]
}

#: Qui tient ce port ? (première ligne de `ss -ltnHp`, vide si personne)
tenant_du_port() { # port
    command -v ss >/dev/null 2>&1 || return 1
    ss -ltnHp "sport = :$1" 2>/dev/null | head -1
}

#: Le premier port libre à partir de `depart`, sans dépasser `depart+plage`.
#: Rend le numéro sur la sortie standard ; rend 1 si aucun n'est libre, 2 si
#: on n'a pas pu savoir (pas de `ss`).
premier_port_libre() { # depart [plage]
    local depart="$1" plage="${2:-40}" p rc
    for (( p = depart; p < depart + plage; p++ )); do
        port_libre "$p"; rc=$?
        (( rc == 2 )) && return 2
        (( rc == 0 )) && { printf '%s' "$p"; return 0; }
    done
    return 1
}

# --- Génération de secrets --------------------------------------------------
#
# Aucun secret ne transite jamais par argv : `ps` est lisible par tout le
# monde sur beaucoup de systèmes. Les valeurs passent par des variables du
# shell (invisibles hors du processus) puis par l'entrée standard.

secret_hex() { # octets
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex "${1:-32}"
    else
        python3 -c 'import secrets,sys;print(secrets.token_hex(int(sys.argv[1])))' "${1:-32}"
    fi
}

secret_base32() { # octets (secret TOTP, RFC 6238 : 20 octets = 160 bits)
    python3 -c 'import base64,secrets,sys;print(base64.b32encode(secrets.token_bytes(int(sys.argv[1]))).decode())' "${1:-20}"
}

# --- Fichiers d'environnement (upsert atomique, 0600) -----------------------

_PY_POSER_VAR="$(cat <<'PY'
import os, pathlib, sys
chemin, cle = pathlib.Path(sys.argv[1]), sys.argv[2]
valeur = sys.stdin.read()
chemin.parent.mkdir(parents=True, exist_ok=True)
try:
    chemin.parent.chmod(0o700)
except OSError:
    pass
lignes = chemin.read_text(encoding="utf-8").splitlines() if chemin.exists() else []
sortie, pose = [], False
for l in lignes:
    nu = l.lstrip()
    if not nu.startswith("#") and "=" in l and l.split("=", 1)[0].strip() == cle:
        if not pose:
            sortie.append(f"{cle}={valeur}")
            pose = True
    else:
        sortie.append(l)
if not pose:
    sortie.append(f"{cle}={valeur}")
tmp = chemin.with_name(chemin.name + ".tmp")
tmp.write_text("\n".join(sortie).rstrip("\n") + "\n", encoding="utf-8")
os.chmod(tmp, 0o600)
os.replace(tmp, chemin)
PY
)"

poser_var() { # fichier cle valeur   (la valeur ne passe PAS par argv)
    printf '%s' "$3" | python3 -c "$_PY_POSER_VAR" "$1" "$2"
}

# --- LA DÉPOSE — la moitié qui manquait ------------------------------------
#
# `poser_var` savait ajouter et remplacer ; rien ne savait RETIRER. Une
# variable devenue fausse restait donc dans le fichier d'environnement, et
# systemd la relisait à chaque démarrage. Le cas constaté : un alias de jeton
# `ARAC_NODE_TOKEN_<ancien poste>` que plus personne n'écrivait mais que
# `app/auth.py` continuait de charger — un jeton révoqué qui ouvre encore.
#
# Poser sans savoir déposer, c'est un fichier qui ne peut que grossir, et dont
# chaque ligne périmée est une autorisation qui survit à sa raison d'être.
_PY_RETIRER_VARS="$(cat <<'PY'
import os, pathlib, sys
chemin = pathlib.Path(sys.argv[1])
a_retirer = set(sys.argv[2:])
if not chemin.exists() or not a_retirer:
    raise SystemExit(0)
lignes = chemin.read_text(encoding="utf-8").splitlines()
sortie, retirees = [], []
for l in lignes:
    nu = l.lstrip()
    if not nu.startswith("#") and "=" in l and l.split("=", 1)[0].strip() in a_retirer:
        retirees.append(l.split("=", 1)[0].strip())
        continue
    sortie.append(l)
if not retirees:
    raise SystemExit(0)
tmp = chemin.with_name(chemin.name + ".tmp")
corps = "\n".join(sortie).rstrip("\n")
tmp.write_text((corps + "\n") if corps else "", encoding="utf-8")
os.chmod(tmp, 0o600)
os.replace(tmp, chemin)
for r in retirees:
    print(r)
PY
)"

#: Retire une ou plusieurs variables d'un fichier d'environnement. Écrit sur
#: stdout le nom de chaque ligne effectivement retirée — un appelant qui n'a
#: rien à dire à l'utilisateur peut l'ignorer, mais il ne peut pas prétendre
#: que le geste a eu lieu s'il n'a rien lu.
retirer_var() { # fichier cle [cle...]
    local fichier="$1"; shift
    [[ -e "$fichier" ]] || return 0
    python3 -c "$_PY_RETIRER_VARS" "$fichier" "$@"
}

#: Les noms des variables d'un fichier d'environnement dont la VALEUR est
#: exactement celle lue sur l'entrée standard. Sert à répondre à une question
#: qu'aucune liste de noms ne peut poser : « ce secret est-il porté deux
#: fois ? »
_PY_CLES_DE_VALEUR="$(cat <<'PY'
import pathlib, sys
chemin, prefixe = pathlib.Path(sys.argv[1]), sys.argv[2]
cible = sys.stdin.read()
if not chemin.exists():
    raise SystemExit(0)
for l in chemin.read_text(encoding="utf-8").splitlines():
    nu = l.lstrip()
    if nu.startswith("#") or "=" not in l:
        continue
    cle, _, valeur = l.partition("=")
    cle = cle.strip()
    if prefixe and not cle.startswith(prefixe):
        continue
    if valeur == cible:
        print(cle)
PY
)"

cles_portant_la_valeur() { # fichier prefixe valeur
    [[ -r "$1" ]] || return 0
    printf '%s' "$3" | python3 -c "$_PY_CLES_DE_VALEUR" "$1" "$2"
}

lire_var() { # fichier cle
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

# --- Lecture de la description du cerveau (TOML) ---------------------------

_PY_LIRE_BRAIN="$(cat <<'PY'
import pathlib, shlex, sys, tomllib

d = tomllib.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
b, s = d.get("brain", {}), d.get("source", {})

def pose(cle, valeur):
    print(cle + "=" + shlex.quote(str(valeur)))

pose("BRAIN_OWNER", b.get("owner", ""))
pose("BRAIN_NOM", b.get("name", ""))
pose("BRAIN_NODE", s.get("node_id", ""))

# L'EMPREINTE DE CETTE INSTALLATION — pas son nom, son identité.
#
# Le nom du cerveau n'est pas une identité : « perso », « test », « arac »
# sont les noms que tout le monde choisit. Deux personnes qui les choisissent
# le même jour sur la même machine ne se distinguent par AUCUN des noms
# dérivés (base, rôles, unités, coffre) — le second est alors reçu comme une
# réinstallation du premier, et hérite de ses secrets.
#
# `uuid` est écrit UNE FOIS par l'entretien, dans le dépôt de son auteur.
# C'est la seule valeur de brain.toml que personne n'a de raison de choisir,
# donc la seule que deux inconnus ne peuvent pas se donner par hasard.
pose("BRAIN_UUID", b.get("uuid", ""))

# LES PORTS VIVENT DANS LA CONFIGURATION DU CERVEAU, PAS DANS UNE CONSTANTE.
# Absents, ils sont attribués au premier passage puis écrits dans le fichier
# d'environnement, d'où les relances les relisent : un cerveau ne change pas
# de port parce qu'on a relancé son bootstrap.
srv = d.get("services", {})
pose("BRAIN_API_PORT", srv.get("api_port", ""))
pose("BRAIN_COCKPIT_PORT", srv.get("cockpit_port", ""))
PY
)"

# --- Aide -------------------------------------------------------------------

afficher_aide() {
    cat <<'AIDE'

  bootstrap.sh — donner corps au cerveau décrit par l'entretien.

  L'entretien (bootstrap/wizard.py) produit une DESCRIPTION : qui vous êtes,
  comment votre mémoire est découpée. Ce script l'incarne : base de données,
  rôles, vecteurs, migrations, taxonomie, secrets, services, vérification.

  USAGE
      ./bootstrap/bootstrap.sh [options]

  OPTIONS
      -n, --dry-run     Montre tout, n'écrit rien. La base n'est ouverte
                        qu'en lecture. À faire au moins une fois.
      -y, --yes         Accepte d'avance. Pour l'automatisation.
          --from ÉTAPE  Reprend à partir de cette étape (et continue).
          --only ÉTAPE  N'exécute que cette étape.
          --scopes-only Raccourci de « --only scopes » : régénère et
                        ressème la taxonomie après avoir édité
                        config/scopes.toml.
          --rejouer     Ignore l'avancement enregistré et rejoue tout.
          --check       Constate les prérequis, puis sort.
          --verify      Lance seulement le contrôle a posteriori.
          --etapes      Liste les étapes et sort.
          --bavard      Montre le détail (unités systemd, SQL, requêtes).
          --no-color    Sortie sans couleurs (NO_COLOR marche aussi).
      -h, --help        Cette aide.
      -V, --version     Version de ce bootstrap.

  ÉTAPES
AIDE
    # LA LISTE DES ÉTAPES EST CELLE DE `ETAPES`, PAS UNE SECONDE ÉCRITURE.
    # Elle vivait ici en toutes lettres, à quelques centaines de lignes du
    # tableau qui la définit, dans le MÊME fichier : l'aide aurait annoncé
    # dix étapes à un bootstrap qui en aurait joué onze, et personne n'aurait
    # pu le voir. Le repli sur 62 colonnes est de la mise en page ; le
    # contenu, lui, ne peut plus diverger.
    printf '%s\n' "${ETAPES[*]}" | fold -s -w 62 | sed -e 's/[[:space:]]*$//' -e 's/^/      /'
    cat <<'AIDE'

  VARIABLES D'ENVIRONNEMENT — tout chemin est paramétré, rien n'est en dur

      ARAC_HOME          racine du dépôt          (déduite de ce script)
      ARAC_DB            nom de la base           (déduit de config/brain.toml)
      ARAC_NODE_ID       identifiant du poste     (config/brain.toml)
      ARAC_SCHEMA        schéma SQL               (arac)
      ARAC_ROLE_PREFIX   préfixe des rôles        (arac_<base> — déduit)
      ARAC_DB_HOTE       hôte PostgreSQL          (127.0.0.1)
      ARAC_DB_PORT       port PostgreSQL          (5432)
      ARAC_PG_SUPERUSER  superutilisateur         (postgres)
      ARAC_ETC           dossier des secrets      (/etc/arac/$ARAC_DB)
      ARAC_ENV_FILE      fichier d'environnement  ($ARAC_ETC/arac.env)
      ARAC_SERVICE_USER  utilisateur des services (arac_<base> — déduit)
      ARAC_AGENT_USER    utilisateur des cycles   (aracagent_<base> — déduit)
      ARAC_VENV          environnement Python     ($ARAC_HOME/.venv)
      ARAC_API_PORT      port de l'API            (attribué : premier libre,
                                                  en loopback, puis retenu)
      ARAC_COCKPIT_PORT  port du cockpit          (idem)
      ARAC_LOG_DIR       journaux fichiers        (/var/log/arac/<base>)
      ARAC_BACKUP_DIR    sauvegardes              (/var/backups/arac/<base>)
      ARAC_CYCLE_TZ      fuseau des cycles        (fuseau du système)
      ARAC_CYCLES        heures des cycles        (04:00 13:00 21:00)
      ARAC_ETAT          fichier d'avancement     ($ARAC_HOME/.bootstrap-install.<base>.state)

  EXEMPLES

      ./bootstrap/bootstrap.sh --dry-run          # voir sans agir
      sudo ./bootstrap/bootstrap.sh               # installer
      sudo ./bootstrap/bootstrap.sh --scopes-only # après avoir changé la taxonomie
      sudo ./bootstrap/bootstrap.sh --verify      # est-ce toujours sain ?

AIDE
}

# --- Analyse des arguments --------------------------------------------------

analyser_options() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -n|--dry-run)   SIMULATION=1 ;;
            -y|--yes)       ACCORD_AUTOMATIQUE=1 ;;
            --bavard|--verbose) BAVARD=1 ;;
            --rejouer|--replay) REJOUER=1 ;;
            --from)         DEPUIS="${2:-}"; shift ;;
            --from=*)       DEPUIS="${1#*=}" ;;
            --only)         SEULEMENT="${2:-}"; shift ;;
            --only=*)       SEULEMENT="${1#*=}" ;;
            --scopes-only)  SEULEMENT="scopes" ;;
            --check)        MODE="check" ;;
            --verify)       MODE="verify" ;;
            --etapes)       MODE="etapes" ;;
            --no-color)     ARAC_UI_COULEUR="jamais" ;;
            -h|--help)      afficher_aide; exit 0 ;;
            -V|--version)   printf 'bootstrap.sh %s\n' "$ARAC_VERSION_BOOTSTRAP"; exit 0 ;;
            *)
                printf '  Option inconnue : %s\n  Voir : ./bootstrap/bootstrap.sh --help\n' "$1" >&2
                exit 2 ;;
        esac
        shift
    done

    local e trouve
    for e in DEPUIS SEULEMENT; do
        local v="${!e}"
        [[ -z "$v" ]] && continue
        trouve=0
        local x; for x in "${ETAPES[@]}"; do [[ "$x" == "$v" ]] && trouve=1; done
        if (( ! trouve )); then
            printf '  Étape inconnue : %s\n  Étapes : %s\n' "$v" "${ETAPES[*]}" >&2
            exit 2
        fi
    done
}
