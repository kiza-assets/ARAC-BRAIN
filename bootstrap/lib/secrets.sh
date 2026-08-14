# shellcheck shell=bash
# ---------------------------------------------------------------------------
# secrets.sh — étapes 7 et 8 : ce qui protège le cerveau, et ce qu'il coûte.
#
#   7. les secrets qui vous appartiennent — engendrés ici, jamais transmis
#   8. les clés externes — annoncées avec leur prix, et refusables
#
# Aucun secret ne passe par la ligne de commande : `ps` est souvent lisible
# par tous. Les valeurs transitent par des variables du shell puis par
# l'entrée standard.
# ---------------------------------------------------------------------------

# ===========================================================================
# ÉTAPE 7 — les secrets
# ===========================================================================

etape_secrets() {
    etape_entete "$(rang_etape secrets)" "$TOTAL_ETAPES" "${TITRE_ETAPE[secrets]}" \
"Un cerveau contient ce que vous avez de plus intime : vos décisions, vos
comptes, vos proches. Quatre secrets décident de qui peut y toucher. Ils
sont engendrés ICI, sur votre serveur, et ne partent nulle part." \
"Quatre valeurs aléatoires dans $ARAC_ETC (dossier 0700, fichiers 0600,
root) : le jeton porteur de l'API, le secret de session du cockpit,
l'empreinte du mot de passe administrateur, et le secret TOTP de votre
application d'authentification. Plus une liste, qui n'est pas un secret :
celle des postes autorisés à déposer des conversations." \
"Sans jeton, l'API refuse tout — y compris votre Mac. Sans liste blanche,
elle les refuse AUSSI, en 403, même avec un jeton valide. Sans TOTP, le
cockpit refuse la connexion même avec le bon mot de passe. Le cerveau
démarre fermé, et vous l'ouvrez."

    exiger_root "secrets"

    plan "jeton porteur de l'API        (32 octets, hexadécimal)"
    plan "liste blanche d'ingestion     (le poste déclaré à l'entretien)"
    plan "secret de session du cockpit  (32 octets)"
    plan "mot de passe administrateur   (demandé, jamais affiché ; haché en PBKDF2-SHA256)"
    plan "secret TOTP                   (20 octets, base32 — RFC 6238)"

    vide
    dire "$(_c 1 'Ce que chacun protège')"
    vide
    dire "   jeton porteur    L'API. Toute écriture dans la mémoire — y compris"
    dire "                    celle de votre Mac — doit le présenter. Le voler,"
    dire "                    c'est pouvoir écrire de faux souvenirs."
    dire "   liste blanche    Les postes. Le jeton dit « je suis connu » ; la"
    dire "                    liste dit « celui-là a le droit d'écrire ». Un jeton"
    dire "                    volé sur une machine non déclarée ne suffit pas."
    dire "   secret session   Les cookies du cockpit. Le voler, c'est fabriquer"
    dire "                    une session valide sans mot de passe."
    dire "   mot de passe     Vous, devant le cockpit. Stocké HACHÉ : le serveur"
    dire "                    ne connaît pas votre mot de passe, seulement de quoi"
    dire "                    vérifier que vous le connaissez."
    dire "   secret TOTP      Le second facteur. Même votre mot de passe volé ne"
    dire "                    suffit pas à lire votre mémoire."
    vide

    reel || { note "Simulation : aucun secret engendré, aucun fichier écrit."; return 0; }

    mkdir -p "$ARAC_ETC"; chmod 0700 "$ARAC_ETC"

    # --- Jeton de l'API ----------------------------------------------------
    if lire_var "$ARAC_ENV_FILE" ARAC_API_BEARER_TOKEN >/dev/null 2>&1; then
        bien "Jeton de l'API déjà présent — conservé."
        note "  (rotation : supprimez la ligne ARAC_API_BEARER_TOKEN de
   $ARAC_ENV_FILE, relancez, puis réinstallez le jeton sur le Mac.)"
    else
        local jeton; jeton="$(secret_hex 32)"
        poser_var "$ARAC_ENV_FILE" ARAC_API_BEARER_TOKEN "$jeton"
        unset jeton
        bien "Jeton de l'API engendré (64 caractères, non affiché)."
    fi

    # --- La posture de la boucle locale, ÉCRITE ----------------------------
    _poser_posture_boucle_locale

    # --- La liste blanche des postes ---------------------------------------
    #
    # Le jeton dit « je suis un poste connu ». La liste blanche dit « ce
    # poste-là a le droit de déposer ». Les deux sont nécessaires, et la
    # seconde est *fail-closed* : absente ou vide, l'ingestion refuse TOUT
    # en 403. C'est le blocage le plus cruel de l'installation — tout tourne,
    # tout semble sain, et rien n'entre — parce qu'il ne produit aucune
    # panne : juste un refus poli, répété, dans un journal que personne ne
    # regarde le premier jour.
    #
    # Elle n'était pas posée jusqu'ici. Elle l'est maintenant, depuis
    # config/brain.toml, qui est la seule source légitime : le poste déclaré
    # à l'entretien est celui qui a le droit d'écrire.
    _poser_liste_blanche

    # --- Secret de session du cockpit --------------------------------------
    if lire_var "$ARAC_SECRETS_COCKPIT" ARAC_CC_SESSION_SECRET >/dev/null 2>&1; then
        bien "Secret de session du cockpit déjà présent — conservé."
    else
        local sess; sess="$(secret_hex 32)"
        poser_var "$ARAC_SECRETS_COCKPIT" ARAC_CC_SESSION_SECRET "$sess"
        unset sess
        bien "Secret de session du cockpit engendré."
    fi

    # --- Mot de passe administrateur ---------------------------------------
    if lire_var "$ARAC_SECRETS_COCKPIT" ARAC_CC_ADMIN_PASSWORD_HASH >/dev/null 2>&1; then
        bien "Mot de passe administrateur déjà provisionné — conservé."
        note "  (changement : supprimez la ligne ARAC_CC_ADMIN_PASSWORD_HASH puis
   relancez  $(geste_bootstrap "--only secrets"))"
    else
        _provisionner_mot_de_passe
    fi

    # --- TOTP ---------------------------------------------------------------
    if lire_var "$ARAC_SECRETS_COCKPIT" ARAC_CC_TOTP_SECRET >/dev/null 2>&1; then
        bien "Secret TOTP déjà présent — conservé."
        note "  Il n'est PAS réaffiché : votre application d'authentification le
   porte déjà. Le régénérer invaliderait l'appairage existant."
    else
        _provisionner_totp
    fi

    # Aussi ici, et pas seulement à l'étape 8 : `--only secrets` est le geste
    # documenté pour faire tourner le jeton. Sans ce rappel, la rotation
    # écrirait un nouveau `ARAC_API_BEARER_TOKEN` en laissant le moteur lire
    # l'ancien `ARAC_NODE_TOKEN_…` — un jeton révoqué qui continue d'ouvrir.
    poser_pont_de_vocabulaire
    return 0
}

#: LA POSTURE DE LA BOUCLE LOCALE — écrite, jamais héritée.
#:
#: `app/auth.py` exige le jeton par défaut : ce fichier n'a donc, en théorie,
#: rien à écrire. Il écrit quand même, et c'est le point de tout ce
#: paragraphe.
#:
#: La porte qu'on vient de fermer est restée ouverte deux versions entières
#: parce qu'elle était un DÉFAUT IMPLICITE : `os.environ.get(VAR, "1")`.
#: Personne ne l'avait choisie, donc personne ne pouvait la relire, donc
#: personne ne l'a remise en cause. Un exploitant qui ouvrait
#: `/etc/arac/<base>/arac.env` — le seul endroit où il va chercher ce qui est
#: vrai de SON installation — n'y voyait rien sur le sujet, et en concluait
#: raisonnablement qu'il n'y avait rien à savoir.
#:
#: Une ligne écrite coûte un octet et supprime cette classe entière : la
#: posture devient un fait constatable, dans le fichier que tout le monde
#: lit, plutôt qu'une valeur enfouie dans un appel Python. Le jour où
#: quelqu'un voudra la changer, il modifiera une ligne existante au lieu
#: d'en deviner le nom.
#:
#: On n'ÉCRASE JAMAIS une valeur déjà posée : quelqu'un a pu desserrer
#: volontairement, et une réinstallation ne doit pas défaire une décision
#: qu'elle n'a pas prise. On se contente alors de la NOMMER — et de dire ce
#: qui manque si le motif n'a pas été écrit, parce qu'un desserrage muet
#: n'est pas appliqué par le moteur.
_poser_posture_boucle_locale() {
    local actuelle motif
    actuelle="$(lire_var "$ARAC_ENV_FILE" ARAC_API_TRUST_LOOPBACK 2>/dev/null || true)"

    if [[ -z "$actuelle" ]]; then
        poser_var "$ARAC_ENV_FILE" ARAC_API_TRUST_LOOPBACK "0"
        bien "Jeton exigé de toute requête, boucle locale comprise — écrit dans le coffre."
        note "  Sans cette ligne, tout compte local de cette machine — un autre
   utilisateur, un script, le cerveau du voisin — lirait cette mémoire
   et y écrirait de faux souvenirs sans présenter le moindre secret.
   Aucune permission de fichier ne ferme ce chemin : il ne passe par
   aucun fichier.
   Rien de plus ne vous est demandé : le jeton engendré ci-dessus est
   celui que le pont, le cycle, le cockpit et les agents présentent
   déjà."
        return 0
    fi

    case "$(printf '%s' "$actuelle" | tr 'A-Z' 'a-z')" in
        1|true|yes|oui|on)
            motif="$(lire_var "$ARAC_ENV_FILE" ARAC_API_TRUST_LOOPBACK_RAISON 2>/dev/null || true)"
            if [[ -n "$motif" ]]; then
                alerte "Boucle locale DESSERRÉE sur ce cerveau — conservée telle quelle."
                note "  Motif déclaré : « $motif »
   Tout compte local lit et écrit cette mémoire sans jeton. C'est votre
   décision, elle est datée, et l'installation ne la défait pas."
            else
                alerte "ARAC_API_TRUST_LOOPBACK=$actuelle posé SANS motif écrit."
                note "  Ce desserrage n'est PAS appliqué : le moteur exige un motif.
   Écrivez-le, ou retirez la variable :
     ARAC_API_TRUST_LOOPBACK_RAISON=\"\$(date -I) — <pourquoi>\""
            fi ;;
        *)
            bien "Jeton exigé de toute requête — déjà écrit dans le coffre." ;;
    esac
    return 0
}

#: La liste blanche d'ingestion, posée depuis l'identité déclarée à
#: l'entretien. Jamais écrasée : quelqu'un qui a ajouté un second poste à la
#: main ne doit pas le perdre en relançant l'installation. On ne fait donc
#: qu'une chose — garantir que le poste de CE cerveau y figure.
_poser_liste_blanche() {
    local actuelle="" nouvelle

    if [[ -z "$ARAC_NODE_ID" ]]; then
        alerte "Aucun poste source déclaré : liste blanche non posée."
        note "  L'ingestion refusera tout en 403 tant que
   ARAC_INGEST_ALLOWED_NODES sera vide. Rejouez l'entretien :
     python3 bootstrap/wizard.py"
        return 0
    fi

    actuelle="$(lire_var "$ARAC_ENV_FILE" ARAC_INGEST_ALLOWED_NODES 2>/dev/null || true)"

    case ",${actuelle}," in
        *",${ARAC_NODE_ID},"*)
            bien "Liste blanche d'ingestion déjà ouverte à « $ARAC_NODE_ID »."
            return 0 ;;
    esac

    if [[ -z "$actuelle" ]]; then
        nouvelle="$ARAC_NODE_ID"
    else
        nouvelle="$actuelle,$ARAC_NODE_ID"
        note "  Un ou plusieurs postes étaient déjà déclarés : ils sont conservés."
    fi

    poser_var "$ARAC_ENV_FILE" ARAC_INGEST_ALLOWED_NODES "$nouvelle"
    bien "Liste blanche d'ingestion : « $nouvelle »."
    note "  L'API n'accepte de conversations QUE de ces postes. Tout autre
   dépôt repart en 403, y compris avec un jeton valide — un jeton volé
   sur une machine non déclarée ne suffit donc pas à écrire de faux
   souvenirs. Pour ajouter un poste plus tard, ajoutez son node_id à
   cette ligne, séparé par une virgule, puis redémarrez l'API."
}

_PY_HACHER="$(cat <<'PY'
import getpass, hashlib, os, secrets, sys

ITERATIONS = 260_000   # au-dessus du minimum OWASP 2024 (210 000)

if sys.argv[1] == "auto":
    mdp = secrets.token_urlsafe(18)
    sys.stderr.write(mdp + "\n")   # affiché UNE fois, sur la sortie d'erreur
else:
    a = getpass.getpass("  Mot de passe administrateur du cockpit : ")
    b = getpass.getpass("  Répétez-le : ")
    if a != b:
        raise SystemExit("  Les deux saisies diffèrent. Rien n'a été écrit.")
    if len(a) < 12:
        raise SystemExit(
            "  Douze caractères au minimum : ce mot de passe garde votre mémoire.")
    mdp = a

# PBKDF2-HMAC-SHA256. Le nombre d'itérations est stocké DANS l'empreinte :
# on pourra l'augmenter plus tard sans invalider les anciennes.
sel = os.urandom(16)
empreinte = hashlib.pbkdf2_hmac("sha256", mdp.encode("utf-8"), sel, ITERATIONS)
print(f"pbkdf2_sha256${ITERATIONS}${sel.hex()}${empreinte.hex()}")
PY
)"

_provisionner_mot_de_passe() {
    local mode="demande" empreinte genere=""
    if (( ACCORD_AUTOMATIQUE )) || [[ ! -t 0 ]]; then mode="auto"; fi

    if [[ "$mode" == auto ]]; then
        local tmp; tmp="$(mktemp)"; chmod 0600 "$tmp"
        empreinte="$(python3 -c "$_PY_HACHER" auto 2>"$tmp")" || {
            rm -f "$tmp"; echec "génération du mot de passe" "Python a échoué." \
                "python3 -V ; relancez : $(geste_bootstrap "--only secrets")"; exit 7; }
        genere="$(cat "$tmp")"; rm -f "$tmp"
        vide
        alerte "$(_c 1 'Mot de passe engendré — il ne sera JAMAIS réaffiché.')"
        dire "   $(_c 1 "$genere")"
        note "   Notez-le maintenant, dans votre gestionnaire de mots de passe.
   Il est aussi dans l'historique de ce terminal : pensez à le vider.
   Pour en choisir un vous-même, relancez sans --yes, depuis un terminal."
        vide
        unset genere
    else
        vide
        empreinte="$(python3 -c "$_PY_HACHER" demande)" || {
            vide; mal "Mot de passe non provisionné."
            note "  Relancez : $(geste_bootstrap "--only secrets")"
            return 0; }
    fi
    poser_var "$ARAC_SECRETS_COCKPIT" ARAC_CC_ADMIN_PASSWORD_HASH "$empreinte"
    unset empreinte
    bien "Mot de passe haché (PBKDF2-SHA256, 260 000 itérations) et stocké."
    note "  Format : pbkdf2_sha256\$<itérations>\$<sel hex>\$<empreinte hex>.
   Le mot de passe en clair n'existe nulle part sur ce serveur."
}

_provisionner_totp() {
    local totp uri
    totp="$(secret_base32 20)"
    poser_var "$ARAC_SECRETS_COCKPIT" ARAC_CC_TOTP_SECRET "$totp"
    uri="otpauth://totp/${BRAIN_NOM}:${BRAIN_OWNER}?secret=${totp}&issuer=${BRAIN_NOM}&algorithm=SHA1&digits=6&period=30"
    vide
    alerte "$(_c 1 'Second facteur — à appairer MAINTENANT, affiché une seule fois.')"
    vide
    dire "   $(_c 36 "$uri")"
    vide
    note "Ouvrez votre application d'authentification — une application dédiée,
ou celle intégrée à votre gestionnaire de mots de passe — et ajoutez cette
URI, ou saisissez la clé à la main :"
    dire "   clé : $(_c 1 "$totp")"
    vide
    note "Sans ce second facteur, le cockpit refusera votre mot de passe. Si vous
perdez l'appareil : supprimez la ligne ARAC_CC_TOTP_SECRET de
$ARAC_SECRETS_COCKPIT (accès root au serveur requis), puis relancez
  $(geste_bootstrap "--only secrets")"
    unset totp uri
    vide
    if [[ -t 0 ]] && (( ! ACCORD_AUTOMATIQUE )); then
        confirmer "Appairage effectué ?" oui >/dev/null || true
    fi
    bien "Secret TOTP en place."
}

# ===========================================================================
# ÉTAPE 8 — les clés externes, et leur coût
# ===========================================================================

etape_cles() {
    etape_entete "$(rang_etape cles)" "$TOTAL_ETAPES" "${TITRE_ETAPE[cles]}" \
"Deux choses qu'ARAC ne sait pas faire seul : transformer un texte en
vecteur de sens, et décider ce qui, dans une conversation, mérite d'être
retenu. Les deux se paient — mais PAS de la même façon, et c'est ce que
cette étape doit vous dire avant que vous n'achetiez quoi que ce soit." \
"Une variable lue par ARAC lui-même dans $ARAC_ENV_FILE : la clé
d'embeddings. Et, pour la curation, de quoi authentifier le BINAIRE
\`claude\` de ce serveur — soit une session d'abonnement déjà ouverte, soit
une clé d'API que ce binaire lira dans l'environnement du service." \
"Sans clé d'embeddings, les souvenirs n'ont pas de vecteur : le rappel par
similarité est mort. Sans curation authentifiée, les cycles s'exécutent et
ne produisent aucun atome : le cerveau ingère, mais n'apprend pas."

    _annoncer_couts
    _dire_ce_que_chaque_secret_paie

    reel || { note "Simulation : aucune clé demandée, aucun fichier écrit."; return 0; }
    exiger_root "cles"

    local degrade=()

    if lire_var "$ARAC_ENV_FILE" ARAC_EMBEDDINGS_API_KEY >/dev/null 2>&1; then
        bien "Clé d'embeddings déjà présente — conservée."
    else
        _demander_cle "ARAC_EMBEDDINGS_API_KEY" \
            "Clé OpenAI (embeddings, text-embedding-3-large) — LUE PAR ARAC" \
            || degrade+=("embeddings")
    fi

    # LA CURATION NE SE DÉCIDE PLUS SUR UNE CLÉ, MAIS SUR CE QU'ELLE EXIGE.
    #
    # On constatait ici « clé Anthropic absente → mode dégradé curation », et
    # c'était faux des deux côtés : une installation SANS cette clé mais AVEC
    # une session d'abonnement ouverte digère parfaitement, et une
    # installation AVEC la clé mais SANS le binaire ne digérera jamais. Ce qui
    # décide, c'est le binaire et son authentification — on les constate.
    _constater_curation
    if [[ "$CURATION_BINAIRE_PRESENT" != oui ]]; then
        vide
        alerte "$(_c 1 'Le binaire de curation est absent de ce serveur.')"
        note "Aucune clé n'y changera rien : la curation ne passe par aucune API,
elle lance \`claude\` en sous-processus. L'étape 1 a donné le geste
(\`sudo npm install -g @anthropic-ai/claude-code\`). La clé ci-dessous
reste utile pour le jour où le binaire sera là."
    fi

    if lire_var "$ARAC_ENV_FILE" ARAC_CURATION_API_KEY >/dev/null 2>&1; then
        bien "Clé Anthropic déjà présente — conservée (c'est le binaire qui la lira)."
    elif [[ "$CURATION_AUTH" == "claude.ai" ]]; then
        bien "Session d'abonnement déjà ouverte pour le binaire \`claude\` — aucune clé nécessaire."
        note "  Vérifiez seulement, à l'étape 9, que cette session est bien celle du
  COMPTE D'AGENT qui lancera les cycles : c'est son dossier personnel que
  le binaire lira, pas le vôtre."
    else
        _demander_cle "ARAC_CURATION_API_KEY" \
            "Clé Anthropic — NON LUE PAR ARAC : recopiée en ANTHROPIC_API_KEY, que le binaire \`claude\` lira" \
            || true
    fi

    # L'INTERRUPTEUR QUI N'EXISTAIT PAS DANS LE FICHIER.
    #
    # Le remède documenté partout est « posez ARAC_ALLOW_PAID_AI=1 dans le
    # fichier d'environnement ». Or l'installation n'y écrivait PAS la ligne :
    # un `sed -i 's/^ARAC_ALLOW_PAID_AI=.*/…=1/'` ne trouvait rien à
    # remplacer, ne disait rien, et le cycle refusait toujours. On pose donc
    # l'interrupteur à 0 — fermé, comme il doit l'être — pour qu'il soit
    # VISIBLE dans le coffre et BASCULABLE par le geste qu'on donne.
    poser_var "$ARAC_ENV_FILE" ARAC_ALLOW_PAID_AI "${ARAC_ALLOW_PAID_AI:-0}"

    # Le mode dégradé « curation » ne se déclare que si, TOUT COMPTE FAIT,
    # rien ne peut authentifier le binaire.
    _constater_curation
    if [[ "$CURATION_BINAIRE_PRESENT" != oui ]] \
       || { [[ "$CURATION_AUTH" != "claude.ai" && "$CURATION_AUTH" != "api_key" ]] \
            && ! lire_var "$ARAC_ENV_FILE" ARAC_CURATION_API_KEY >/dev/null 2>&1; }; then
        degrade+=("curation")
    fi

    if (( ${#degrade[@]} > 0 )); then
        local liste; liste="$(IFS=,; printf '%s' "${degrade[*]}")"
        poser_var "$ARAC_ENV_FILE" ARAC_MODE_DEGRADE "$liste"
        vide
        alerte "$(_c 1 "Mode dégradé déclaré : $liste")"
        vide
        for d in "${degrade[@]}"; do
            case "$d" in
                embeddings)
                    dire "   $(_c 1 'sans embeddings')"
                    note "     · les conversations sont ingérées et conservées ;
     · les souvenirs sont créés SANS vecteur ;
     · le rappel par similarité ne rend rien ;
     · le cockpit affiche la mémoire, mais ne sait plus la fouiller.
     Quand vous ajouterez la clé, il faudra revectoriser l'existant." ;;
                curation)
                    dire "   $(_c 1 'sans curation')"
                    note "     · les cycles se lancent aux heures prévues ;
     · ils sortent immédiatement, à coût nul ;
     · AUCUN souvenir n'est produit : le cerveau accumule sans digérer.
     C'est un état parfaitement valable pour observer la chaîne
     d'ingestion avant d'engager la moindre dépense.
     CE QUI MANQUE, PRÉCISÉMENT, sur CETTE machine :"
                    if [[ "$CURATION_BINAIRE_PRESENT" != oui ]]; then
                        note "       le binaire \`claude\` ($CURATION_BINAIRE_CHEMIN) — absent."
                    else
                        note "       de quoi authentifier \`claude\` : ni session ouverte, ni clé."
                    fi ;;
            esac
        done
        vide
        dire "Pour sortir du mode dégradé, plus tard :"
        cmd "$(geste_bootstrap "--only cles")"
    else
        poser_var "$ARAC_ENV_FILE" ARAC_MODE_DEGRADE ""
        bien "Les deux clés sont en place. Le cerveau pourra digérer."
    fi

    poser_pont_de_vocabulaire
    return 0
}

# ---------------------------------------------------------------------------
# LE PONT DE VOCABULAIRE
#
# Le bootstrap préfixe tout par `ARAC_` : c'est cohérent, et c'est ce qui
# permet à deux cerveaux de cohabiter sur une machine. Le moteur, lui, lit les
# noms historiques — `DATABASE_URL_APP`, `OPENAI_API_KEY`, et un jeton nommé
# d'après le poste. Les deux vocabulaires sont défendables ; ce qui ne l'est
# pas, c'est de les laisser ne pas se rencontrer.
#
# Jusqu'ici, la traduction était une CONSIGNE : un script à recopier depuis la
# documentation de dépannage, après un bootstrap qui s'était pourtant déclaré
# terminé. Tant qu'on ne l'avait pas fait, l'API démarrait puis s'arrêtait sur
# « DATABASE_URL_APP non définie », le cockpit répondait 503, et rien ne
# disait que l'installation n'était pas finie. Une installation qui exige un
# geste non fait par l'installateur n'est pas une installation.
#
# Elle est désormais posée ici, par le bootstrap lui-même, à la fin de l'étape
# des clés — donc après que tout ce qu'il y a à traduire a été écrit. Idempotente :
# `poser_var` remplace la ligne si elle existe, l'ajoute sinon.
#
# On COPIE plutôt qu'on ne renomme : les deux noms restent lisibles côte à
# côte dans le fichier, et le jour où le moteur adoptera le vocabulaire du
# bootstrap, retirer ce pont ne cassera rien.
# ---------------------------------------------------------------------------
poser_pont_de_vocabulaire() {
    reel || { plan "traduction des variables vers les noms lus par le moteur"
              plan "traduction des trois secrets du cockpit vers $ARAC_SECRETS_COCKPIT"
              plan "dépose des alias de jeton périmés"; return 0; }

    local n=0

    _copier_var() { # source cible [fichier_cible]
        local v cible_f="${3:-$ARAC_ENV_FILE}"
        v="$(lire_var "$ARAC_ENV_FILE" "$1")" || return 0   # absente : rien à traduire
        [[ -z "$v" ]] && return 0
        poser_var "$cible_f" "$2" "$v"
        unset v
        n=$((n + 1))
    }

    # `ARAC_DB_URL_<X>` → `DATABASE_URL_<X>` pour chaque rôle qui a un DSN.
    # La liste vient de `ROLES_AVEC_DSN` (lib/core.sh) : c'est la même que
    # celle qui a ÉCRIT ces variables à l'étape 3, et il n'y en a plus qu'une.
    local _l _v_arac _v_db _reste
    for _l in "${DSN_PAR_ROLE[@]}"; do
        read -r _v_arac _v_db _reste <<< "$_l"
        _copier_var "$_v_arac" "$_v_db"
    done
    _copier_var ARAC_EMBEDDINGS_API_KEY OPENAI_API_KEY
    _copier_var ARAC_CURATION_API_KEY   ANTHROPIC_API_KEY

    # Le jeton n'est pas lu sous un nom fixe : `app/auth.py` balaie
    # l'environnement à la recherche du préfixe `ARAC_NODE_TOKEN_` et
    # construit une table « jeton -> poste ». Le nom PORTE donc l'identité du
    # poste — c'est ce qui permet de révoquer un poste sans toucher aux
    # autres. D'où la transformation du node_id en suffixe majuscule.
    local suffixe
    suffixe="$(printf '%s' "$ARAC_NODE_ID" | tr 'a-z-' 'A-Z_' | tr -c 'A-Z0-9_' '_')"
    _deposer_alias_de_jeton_perimes "$suffixe"
    _copier_var ARAC_API_BEARER_TOKEN "ARAC_NODE_TOKEN_$suffixe"

    # --- LES TROIS SECRETS DU COCKPIT --------------------------------------
    #
    # C'ÉTAIT LA DERNIÈRE INTERVENTION HUMAINE DU PARCOURS, ET LA SEULE QUE
    # `make acceptance` COMPTAIT CONTRE LUI-MÊME.
    #
    # L'étape 7 engendre les trois secrets sous les noms du bootstrap
    # (`ARAC_CC_*`) et les écrit dans le coffre du cockpit. Le cockpit, lui,
    # lit `CC_SESSION_SECRET`, `CC_ADMIN_PASSWORD_HASH` et `CC_TOTP_SECRET`.
    # Le pont ne regardait que `$ARAC_ENV_FILE` : les trois valeurs existaient,
    # au bon endroit, sous le mauvais nom. L'installation se déclarait réussie,
    # et `POST /cc/login` répondait 503 « Login non provisionné ».
    #
    # La traduction se fait donc ici, dans le MÊME fichier que la source —
    # `$ARAC_SECRETS_COCKPIT`, chargé par l'unité du cockpit — et pas dans
    # l'environnement général : le hash du mot de passe et le secret TOTP
    # n'ont aucune raison d'être visibles de l'API ni des cycles.
    _copier_cockpit() { # source cible
        local v
        v="$(lire_var "$ARAC_SECRETS_COCKPIT" "$1")" || return 0
        [[ -z "$v" ]] && return 0
        poser_var "$ARAC_SECRETS_COCKPIT" "$2" "$v"
        unset v
        n=$((n + 1))
    }
    _copier_cockpit ARAC_CC_SESSION_SECRET      CC_SESSION_SECRET
    _copier_cockpit ARAC_CC_ADMIN_PASSWORD_HASH CC_ADMIN_PASSWORD_HASH
    _copier_cockpit ARAC_CC_TOTP_SECRET         CC_TOTP_SECRET

    unset -f _copier_var _copier_cockpit
    bien "Pont de vocabulaire posé : $n variable(s) traduite(s) pour le moteur."
    note "  Le compte varie : 8 si vous avez différé les deux clés (mode
   dégradé), 10 une fois qu'elles sont là — dont les trois du cockpit,
   traduites dans $ARAC_SECRETS_COCKPIT. Ce n'est pas un critère de
   réussite — le critère est que l'API démarre et que le cockpit accepte
   une connexion (étape 10 le vérifie)."
    return 0
}

# ---------------------------------------------------------------------------
# LA DÉPOSE — poser sans déposer, c'est révoquer sans révoquer
# ---------------------------------------------------------------------------
#
# `ARAC_NODE_TOKEN_<poste>` porte l'identité du poste DANS SON NOM. Changer de
# node_id — ou réinstaller depuis un autre poste — écrivait donc une NOUVELLE
# ligne et laissait l'ancienne intacte, avec la même valeur. Deux noms, un
# jeton.
#
# `app/auth.py::load_tokens_from_env` construit une table « jeton → poste » et
# lève `ValueError: Duplicate token detected` dès que deux postes présentent
# le même jeton. Cet appel est dans le `lifespan` : l'API ne démarre pas, elle
# boucle en 203/restart, après une installation qui s'est déclarée réussie.
# Constaté deux fois, sur deux cerveaux différents.
#
# Et le défaut est plus grave que la panne qu'il produit : tant que l'API
# démarrait quand même, l'alias périmé était un jeton RÉVOQUÉ QUI OUVRAIT
# ENCORE, sous le nom d'un poste dont plus personne ne se sert.
#
# La règle tient en une phrase : un jeton ne désigne qu'un poste. On retire
# donc, avant d'écrire, tout alias qui porte la valeur qu'on s'apprête à
# poser et qui n'est pas celui du poste courant. Les alias portant une AUTRE
# valeur ne sont pas touchés — ce sont les autres postes légitimes, et les
# effacer serait exactement le geste inverse.
_deposer_alias_de_jeton_perimes() { # suffixe_courant
    local suffixe="$1" jeton alias retires=()
    jeton="$(lire_var "$ARAC_ENV_FILE" ARAC_API_BEARER_TOKEN)" || return 0
    [[ -z "$jeton" ]] && return 0

    while IFS= read -r alias; do
        [[ -z "$alias" ]] && continue
        [[ "$alias" == "ARAC_NODE_TOKEN_$suffixe" ]] && continue
        retires+=("$alias")
    done < <(cles_portant_la_valeur "$ARAC_ENV_FILE" ARAC_NODE_TOKEN_ "$jeton")
    unset jeton

    (( ${#retires[@]} == 0 )) && return 0

    retirer_var "$ARAC_ENV_FILE" "${retires[@]}" >/dev/null
    alerte "Alias de jeton périmés retirés : ${retires[*]}"
    note "  Ils portaient la MÊME valeur que ARAC_NODE_TOKEN_$suffixe. Deux noms
   pour un jeton, c'est un poste révoqué qui ouvre encore — et, depuis
   que l'API le refuse au démarrage, une API qui ne démarre plus du tout.
   Le poste déclaré aujourd'hui est « $ARAC_NODE_ID » ; si un autre poste
   doit écrire, donnez-lui SON jeton, pas une copie de celui-ci."
    return 0
}

_annoncer_couts() {
    dire "$(_c 1 'Ce que ça coûte — mesures réelles, pas des estimations de brochure')"
    vide
    dire "   Sur le cerveau de référence, en régime établi :"
    dire "     · 3 cycles de digestion par jour ;"
    dire "     · ~87 000 jetons consommés par cycle ;"
    dire "     · ~31 500 jetons par souvenir effectivement produit."
    vide
    dire "   Soit de l'ordre de 260 000 jetons par jour, ~8 millions par mois."
    vide
    dire "   $(_c 1 'Curation (Anthropic)') — le poste dominant."
    note "     Avec un modèle de la classe Sonnet (3 \$ / million de jetons en
     entrée au tarif public d'août 2026), 8 M de jetons d'entrée par mois
     coûtent environ 25 \$, plus la sortie. Avec un modèle de la classe
     Opus, comptez trois à cinq fois plus. Ordre de grandeur pour un usage
     personnel : 20 à 100 \$ par mois selon le modèle choisi."
    vide
    dire "   $(_c 1 'Embeddings (OpenAI)') — marginal, mais pas nul."
    note "     Un embedding coûte deux ordres de grandeur moins cher qu'une
     curation. Pour un usage personnel : quelques euros par mois au plus.
     C'est la curation qu'il faut surveiller, pas les vecteurs."
    vide
    alerte "Ces tarifs datent d'août 2026. VÉRIFIEZ-LES sur les pages de prix des
     deux fournisseurs avant de vous engager : ce bootstrap ne peut pas
     vous promettre un prix qu'il ne contrôle pas."
    vide
    note "Le moteur pose des garde-fous : plafond de jetons par jour, nombre
maximal de cycles, durée maximale d'un cycle. Ils sont configurables et
actifs par défaut. Un cerveau qui coûte plus que prévu est un cerveau mal
configuré, pas une fatalité."
    vide
}

# ---------------------------------------------------------------------------
# CE QUE CHAQUE SECRET PAIE — MESURÉ DANS LE CODE, PAS SUPPOSÉ.
#
# Cette étape faisait acheter une clé d'API Anthropic « pour la curation ».
# Or aucun fichier du produit ne lit cette clé : `grep -rn ARAC_CURATION_API_KEY
# --include=*.py .` ne rend rien. Elle est recopiée en `ANTHROPIC_API_KEY` par
# le pont de vocabulaire, héritée par le sous-processus `claude`, et c'est LUI
# qui s'en sert — ou pas, s'il a déjà une session d'abonnement. Quelqu'un qui
# paie a le droit de savoir laquelle de ces deux choses il achète.
# ---------------------------------------------------------------------------
_dire_ce_que_chaque_secret_paie() {
    dire "$(_c 1 'Qui lit quoi — pour que vous sachiez ce que vous payez')"
    vide
    dire "   $(_c 1 'ARAC_EMBEDDINGS_API_KEY')  →  recopiée en OPENAI_API_KEY"
    note "     LUE PAR ARAC (app/services/embeddings.py). Elle paie UN vecteur
     par souvenir produit — jamais par message ingéré. Sans elle, l'API
     répond 503 sur la vectorisation et le rappel par similarité est mort."
    vide
    dire "   $(_c 1 'ARAC_CURATION_API_KEY')    →  recopiée en ANTHROPIC_API_KEY"
    note "     JAMAIS LUE PAR ARAC. Aucune ligne du produit ne l'ouvre : elle
     est posée dans l'environnement du service, et c'est le binaire
     \`claude\` — lancé par le cycle — qui la trouve et s'authentifie avec.
     Elle paie donc les jetons de la digestion, à l'appel.
     ELLE EST INUTILE SI vous avez ouvert une session d'abonnement pour le
     compte d'agent : le binaire préfère alors cette session, et rien ne
     se facture à l'appel. Laissez la clé vide dans ce cas."
    vide
    alerte "Ce que la curation exige VRAIMENT, ce n'est pas cette clé : c'est le
     binaire \`claude\` installé sur CE serveur. Sans lui, aucune clé ne
     produit un souvenir — l'étape 1 l'a constaté, le contrôle final le
     revérifie sous le compte d'agent."
    vide
}

_demander_cle() { # variable libelle
    local variable="$1" libelle="$2" valeur=""
    if (( ACCORD_AUTOMATIQUE )) || [[ ! -t 0 ]]; then
        note "  $libelle : non demandée (mode non interactif)."
        return 1
    fi
    vide
    dire "$libelle"
    note "  Collez la clé, ou appuyez sur Entrée pour différer (mode dégradé)."
    read -r -s -p "  $(_c 36 '> ')" valeur || valeur=""
    printf '\n'
    if [[ -z "$valeur" ]]; then
        note "  Différée."
        return 1
    fi
    poser_var "$ARAC_ENV_FILE" "$variable" "$valeur"
    unset valeur
    bien "$libelle enregistrée (non affichée)."
    return 0
}
