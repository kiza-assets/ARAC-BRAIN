# shellcheck shell=bash
# ---------------------------------------------------------------------------
# prereqs.sh — étape 1 : constater, expliquer, ne rien installer sans accord.
#
# Un bootstrap qui installe des paquets dans votre dos est un bootstrap en qui
# vous ne pouvez pas avoir confiance. Celui-ci constate, dit à quoi chaque
# pièce sert ICI, et vous donne la commande exacte. Vous décidez.
# ---------------------------------------------------------------------------

PREREQUIS_MANQUANTS=()
PREREQUIS_INSTALL=()

_prerequis() { # nom present role commande_installation
    local nom="$1" present="$2" role="$3" install="$4"
    if [[ "$present" == oui ]]; then
        bien "$(pad "$nom" 24)$(_c 2 "$role")"
    else
        mal "$(pad "$nom" 24)$(_c 2 "$role")"
        PREREQUIS_MANQUANTS+=("$nom")
        [[ -n "$install" ]] && PREREQUIS_INSTALL+=("$install")
    fi
}

_present() { command -v "$1" >/dev/null 2>&1 && echo oui || echo non; }

etape_prereqs() {
    etape_entete "$(rang_etape prereqs)" "$TOTAL_ETAPES" "${TITRE_ETAPE[prereqs]}" \
"Un cerveau n'est pas un fichier : c'est une base de données vectorielle,
une API, un cockpit et des services qui se réveillent trois fois par jour.
Chacune de ces pièces a un prérequis, et mieux vaut les découvrir
maintenant qu'à la moitié d'une migration." \
"Rien. Cette étape ne fait que constater — elle n'installe aucun paquet
sans votre accord explicite." \
"Un prérequis absent ne dégrade pas le cerveau : il l'empêche de naître.
L'installation s'arrêtera net, en vous disant quoi taper. Un seul fait
exception, et il est nommé plus bas : le binaire « claude », qui n'empêche
pas la naissance — il décide si le cerveau APPREND."

    PREREQUIS_MANQUANTS=(); PREREQUIS_INSTALL=()

    # --- Le système -------------------------------------------------------
    local distro="inconnu" version=""
    if [[ -r /etc/os-release ]]; then
        # shellcheck disable=SC1091
        distro="$(. /etc/os-release && printf '%s' "$NAME")"
        version="$(. /etc/os-release && printf '%s' "$VERSION_ID")"
    fi
    local ubuntu=non
    [[ "$distro" == *Ubuntu* || "$distro" == *Debian* ]] && ubuntu=oui
    _prerequis "Ubuntu / Debian" "$ubuntu" \
        "systemd, apt et les chemins supposés par les gabarits ($distro $version)" \
        ""

    # --- Python -----------------------------------------------------------
    local py=non pyv=""
    if command -v python3 >/dev/null 2>&1; then
        pyv="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0.0)"
        python3 -c 'import sys;raise SystemExit(0 if sys.version_info>=(3,11) else 1)' 2>/dev/null && py=oui
    fi
    _prerequis "Python ≥ 3.11" "$py" \
        "lire votre taxonomie (tomllib, apparu en 3.11), faire tourner l'API et les cycles — trouvé ${pyv:-aucun}" \
        "sudo apt install python3 python3-venv python3-pip"

    # --- PostgreSQL -------------------------------------------------------
    local psql_ok pgv=""
    psql_ok="$(_present psql)"
    [[ "$psql_ok" == oui ]] && pgv="$(psql --version 2>/dev/null | awk '{print $3}')"
    _prerequis "psql (client)" "$psql_ok" \
        "parler à la base, appliquer les seeds, et rejouer vous-même les preuves du cockpit — ${pgv:-absent}" \
        "sudo apt install postgresql-client-16"

    local serveur=non
    if pg_lire "SELECT 1" | grep -q 1; then serveur=oui; fi
    _prerequis "PostgreSQL 16 (serveur)" "$serveur" \
        "la mémoire elle-même : atomes, vecteurs, preuves, journal d'audit" \
        "sudo apt install postgresql-16
sudo systemctl enable --now postgresql"

    # --- pgvector ---------------------------------------------------------
    local vect=non vectv="" vecttxt="absent"
    vectv="$(pg_lire "SELECT default_version FROM pg_available_extensions WHERE name='vector'")"
    if [[ -n "$vectv" ]]; then vect=oui; vecttxt="v$vectv"; fi
    _prerequis "pgvector" "$vect" \
        "comparer des sens, pas des mots : sans lui, aucun rappel par similarité — $vecttxt" \
        "sudo apt install postgresql-16-pgvector"

    # --- Outils -----------------------------------------------------------
    _prerequis "git" "$(_present git)" \
        "récupérer et mettre à jour le framework" \
        "sudo apt install git"
    _prerequis "ssh" "$(_present ssh)" \
        "le pont : c'est par un tunnel SSH que vos conversations quitteront le Mac" \
        "sudo apt install openssh-client"
    _prerequis "systemd (systemctl)" "$(_present systemctl)" \
        "faire vivre l'API, le cockpit, les cycles de digestion et les sauvegardes" \
        ""
    _prerequis "sudo" "$(_present sudo)" \
        "créer la base, écrire les secrets en 0600, poser les unités système" \
        "apt install sudo"
    _prerequis "openssl" "$(_present openssl)" \
        "engendrer des secrets solides (repli sur Python si absent)" \
        "sudo apt install openssl"

    vide
    _prerequis_de_la_curation
    vide
    _dependances_externes

    if (( ${#PREREQUIS_MANQUANTS[@]} > 0 )); then
        vide
        alerte "$(_c 1 "${#PREREQUIS_MANQUANTS[@]} prérequis manquant(s) : ${PREREQUIS_MANQUANTS[*]}")"
        vide
        dire "Les commandes exactes, dans l'ordre :"
        local c
        for c in "${PREREQUIS_INSTALL[@]}"; do
            local l; while IFS= read -r l; do cmd "$l"; done <<< "$c"
        done
        vide
        note "Ce script n'installera rien à votre place : sur un serveur, un
paquet posé sans qu'on le sache est une dette qu'on découvre six mois
plus tard."
        vide
        if [[ "$MODE" == "check" ]]; then return 1; fi
        if ! confirmer "Continuer malgré tout (l'installation échouera plus loin) ?" non; then
            dire "Rien n'a été fait. Installez les prérequis, puis relancez."
            exit 5
        fi
    elif [[ "$CURATION_BINAIRE_PRESENT" == oui ]]; then
        bien "$(_c 1 'Tout est là. Votre serveur peut porter un cerveau — et le digérer.')"
    else
        # LA PHRASE NE PEUT PLUS PROMETTRE PLUS QU'ELLE N'A VU. « Tout est
        # là » était rendu par un contrôle qui ne regardait pas le binaire de
        # curation : dix ✓ et une conclusion fausse sur le seul point qui
        # décide si le cerveau apprendra un jour.
        bien "$(_c 1 'Le serveur peut porter un cerveau.')"
        alerte "$(_c 1 'Mais PAS le faire apprendre : le binaire de curation manque (voir ci-dessus).')"
    fi
    return 0
}

# ---------------------------------------------------------------------------
# LE PRÉREQUIS QUE PERSONNE NE VÉRIFIAIT, ET QUI DÉCIDE SI LE CERVEAU APPREND.
#
# CE QU'ON FAISAIT ACHETER N'ÉTAIT PAS CE DONT LA CURATION A BESOIN. L'étape 8
# demandait « une clé Anthropic (curation) », annonçait son coût, et déclarait
# un mode dégradé si on la refusait. Or la curation n'appelle AUCUNE API : le
# cycle lance le binaire `claude` — le Claude Code CLI — en sous-processus sur
# CE serveur (agents/lib/claude_cli.py). Sur un Ubuntu nu, ce binaire n'existe
# pas, et le contrôle des prérequis concluait quand même « Tout est là ».
# L'utilisateur payait la mauvaise chose, son cerveau ingérait sans jamais
# apprendre, et rien ne le lui disait — jusqu'à ce qu'il aille lire un journal
# trois jours plus tard.
#
# Un prérequis qu'on découvre trois jours plus tard n'est pas un prérequis :
# c'est un piège. Il est donc CONSTATÉ ici, NOMMÉ dans l'écran de l'étape, et
# repris par le contrôle final (bootstrap/checks/verify_install.sh).
#
# Il n'est pas BLOQUANT, et c'est délibéré : sans lui le cerveau naît, ingère,
# se laisse interroger sur ce qu'il sait déjà — il n'apprend simplement rien
# de neuf. Ce n'est pas la même chose qu'une base absente, et le dire
# autrement serait mentir dans l'autre sens.
# ---------------------------------------------------------------------------

#: Rempli par `_prerequis_de_la_curation` : oui/non. Lu par l'étape 8 (secrets.sh)
#: pour déclarer le mode dégradé sur le VRAI prérequis, pas sur une clé.
CURATION_BINAIRE_PRESENT=non
CURATION_BINAIRE_CHEMIN=""
CURATION_AUTH=""
CURATION_VERSION=""

#: CONSTATER sans rien imprimer — l'étape 1 en fait un écran, l'étape 8 en
#: tire le mode dégradé, et le contrôle final le rejoue. Trois lecteurs, une
#: seule mesure : deux mesures qui se ressemblent finissent par diverger.
_constater_curation() {
    CURATION_BINAIRE_PRESENT=non
    CURATION_BINAIRE_CHEMIN=""
    CURATION_AUTH=""
    CURATION_VERSION=""
    local chemin=""
    if [[ -n "${ARAC_CLAUDE_BIN:-}" ]]; then
        chemin="$ARAC_CLAUDE_BIN"
    else
        chemin="$(command -v claude 2>/dev/null || true)"
    fi
    CURATION_BINAIRE_CHEMIN="${chemin:-claude}"
    [[ -n "$chemin" && -x "$chemin" ]] || return 0
    CURATION_BINAIRE_PRESENT=oui
    CURATION_VERSION="$("$chemin" --version 2>/dev/null | head -1)"
    local etat; etat="$("$chemin" auth status --json 2>/dev/null || true)"
    if [[ -z "$etat" ]]; then
        CURATION_AUTH="illisible"
    else
        CURATION_AUTH="$(printf '%s' "$etat" | _lire_json_str authMethod)"
        [[ -z "$CURATION_AUTH" || "$CURATION_AUTH" == none ]] && CURATION_AUTH="aucune"
    fi
    return 0
}

_prerequis_de_la_curation() {
    dire "$(_c 1 'La curation — ce qui digère vos conversations en souvenirs')"
    vide
    _constater_curation
    local chemin="$CURATION_BINAIRE_CHEMIN"

    if [[ "$CURATION_BINAIRE_PRESENT" == oui ]]; then
        local v="$CURATION_VERSION"
        bien "$(pad "claude (Claude Code CLI)" 24)$(_c 2 "digérer vos conversations : le cycle LANCE ce binaire, il n'appelle aucune API — ${v:-version inconnue}")"
        # L'authentification est LUE, pas supposée — et sans rien dépenser :
        # `claude auth status` ne parle à personne, il dit ce que le binaire a
        # sous la main. C'est la seule sonde d'authentification qui ne coûte
        # rien ; un `claude -p "bonjour"` de contrôle, lui, se facture.
        case "$CURATION_AUTH" in
            claude.ai)
                bien "$(pad "  son authentification" 24)$(_c 2 "session d'abonnement ouverte pour CE compte — rien de plus à payer par appel")" ;;
            api_key)
                bien "$(pad "  son authentification" 24)$(_c 2 "clé ANTHROPIC_API_KEY lue dans l'environnement — facturation à l'appel")" ;;
            illisible)
                alerte "$(pad "  son authentification" 24)NON LUE — « claude auth status » n'a rien rendu sur cette version."
                note "Ce n'est pas un refus : c'est un aveu. Le contrôle final
(bootstrap/checks/verify_install.sh) la reposera sous le compte d'agent,
qui est le seul dont l'avis compte — c'est lui qui lancera le binaire." ;;
            *)
                alerte "$(pad "  son authentification" 24)ABSENTE — le binaire est là, mais il n'a pas de quoi parler à Anthropic."
                note "Le cycle spawnerait le binaire et récolterait « Not logged in ».
Deux façons, une seule suffit :
  · une session d'abonnement, ouverte SOUS LE COMPTE D'AGENT du cerveau
    (l'étape 9 nomme ce compte et le dossier où sa session est lue) ;
  · une clé d'API Anthropic, que l'étape 8 vous demandera : le binaire la
    lit dans l'environnement du service, ARAC ne s'en sert jamais lui-même." ;;
        esac
    else
        alerte "$(pad "claude (Claude Code CLI)" 24)ABSENT — sans lui, votre cerveau ingérera sans jamais apprendre."
        note "C'est le VRAI prérequis de la curation, et il n'est pas une clé
d'API : le cycle de digestion lance ce binaire en sous-processus sur ce
serveur, sous le compte d'agent du cerveau. Absent, chaque cycle
s'arrêtera sans produire un seul souvenir.
L'installation peut continuer — le cerveau naîtra, ingérera et se
laissera interroger — mais il n'apprendra rien de neuf tant que ceci
n'est pas fait :"
        cmd "sudo npm install -g @anthropic-ai/claude-code"
        note "Si votre binaire n'atterrit pas dans le PATH du service (nvm, npm
sous préfixe utilisateur…), nommez-le au lieu de le déplacer :"
        cmd "echo 'ARAC_CLAUDE_BIN=/chemin/absolu/vers/claude' | sudo tee -a ${ARAC_ENV_FILE:-/etc/arac/<votre-base>/arac.env}"
    fi
}

#: Extrait UNE chaîne d'un petit JSON, sans dépendance et sans jq.
_lire_json_str() { # cle  (JSON sur stdin)
    python3 -c 'import json,sys
try:
    print(json.load(sys.stdin).get(sys.argv[1], "") or "")
except Exception:
    print("")' "$1" 2>/dev/null || true
}

_dependances_externes() {
    dire "$(_c 1 'Ce que le bootstrap va exiger du réseau — dit maintenant, pas en annexe')"
    vide
    note "· pip devra télécharger les dépendances Python (une fois, à l'étape 5).
· UNE clé d'API vous sera demandée à l'étape 8 : OpenAI, pour les
  embeddings. Elle est PAYANTE et le bootstrap vous dira combien, en
  ordre de grandeur, avant de demander.
· La curation, elle, ne se paie pas par une clé d'ARAC : elle se paie par
  ce que le binaire « claude » de ce serveur a pour parler à Anthropic —
  votre abonnement (session ouverte) ou une clé d'API que c'est LUI qui
  lit. L'étape 8 le redit, et le contrôle final le vérifie.
· Vous pourrez refuser : le cerveau démarrera en mode dégradé déclaré, et
  vous dira exactement ce qui ne marche pas.
· Une fois installé, ARAC n'a besoin d'aucun accès réseau entrant. L'API
  et le cockpit n'écoutent que sur la boucle locale."
}
