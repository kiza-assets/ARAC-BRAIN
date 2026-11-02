# shellcheck shell=bash
# ---------------------------------------------------------------------------
# database.sh — étapes 3 à 6 : la mémoire prend corps.
#
#   3. la base et ses rôles          (pourquoi plusieurs, et non un)
#   4. pgvector                      (pourquoi une base a besoin de vecteurs)
#   5. les migrations Alembic        (ce qu'elles construisent)
#   6. la taxonomie                  (votre découpage devient du schéma)
#
# Aucune base existante n'est jamais écrasée. Si elle est là, on dit ce
# qu'elle contient, et on demande.
# ---------------------------------------------------------------------------

base_existe() { [[ "$(pg_lire "SELECT 1 FROM pg_database WHERE datname='$ARAC_DB'")" == 1 ]]; }
role_existe() { [[ "$(pg_lire "SELECT 1 FROM pg_roles WHERE rolname='$1'")" == 1 ]]; }

# ---------------------------------------------------------------------------
# À QUI APPARTIENT CE RÔLE ? — la question que personne n'avait posée
# ---------------------------------------------------------------------------
#
# Un rôle PostgreSQL ne porte, nativement, aucune trace de ce qui l'a créé. Le
# bootstrap trouvait donc `arac_app`, ne pouvait rien en dire, et faisait
# `ALTER ROLE … PASSWORD` — c'est-à-dire qu'il prenait possession du rôle d'un
# autre cerveau sans le savoir et sans le dire.
#
# On pose donc une plaque au moment de la création : un COMMENT ON ROLE qui
# nomme le cerveau propriétaire et l'endroit où vivent ses secrets. Elle est
# lisible par un humain (`\du+` dans psql) autant que par ce script, elle
# survit aux redémarrages et aux sauvegardes du cluster, et elle transforme
# « ce rôle existe » — qui n'apprend rien — en « ce rôle appartient au cerveau
# X, dont les secrets sont en /etc/arac/X », qui dit quoi faire.
# CE QUE LA PLAQUE DOIT PORTER — et pourquoi le nom n'y suffisait pas.
#
# Première version : `arac:cerveau=<base>;secrets=<dossier>`. Elle répondait à
# « quel cerveau ? » et jamais à « QUI ? ». Or les deux champs qu'elle porte
# sont l'un et l'autre DÉRIVÉS du nom saisi à l'entretien : deux personnes qui
# appellent leur cerveau « perso » posent, au caractère près, la même plaque.
# La reconnaissance « ces rôles sont les nôtres » était donc vraie de tous
# ceux qui avaient choisi le même mot.
#
# Elle porte maintenant, en plus, le propriétaire déclaré (pour l'humain qui
# lit `\du+` et doit savoir à qui parler) et l'EMPREINTE de l'installation
# (pour ce script, qui doit trancher). Seule l'empreinte fait autorité : le
# propriétaire est une chaîne saisie, deux « Camille » existent.
_marque_role() {
    printf 'arac:cerveau=%s;proprietaire=%s;empreinte=%s;secrets=%s' \
           "$ARAC_DB" "${BRAIN_OWNER:-inconnu}" "${ARAC_INSTALL_UUID:-}" "$ARAC_ETC"
}

_marque_de() { # role  → le commentaire posé sur ce rôle, ou vide
    pg_lire "SELECT shobj_description(oid, 'pg_authid') FROM pg_roles WHERE rolname='$1'"
}

#: Un champ d'une plaque, ou vide s'il n'y figure pas. Lire un champ ABSENT
#: comme une chaîne vide serait ici la faute exacte à ne pas commettre : deux
#: plaques sans empreinte se ressembleraient alors parfaitement.
#: `arac:` en tête devient `;` pour que le PREMIER champ se lise comme les
#: autres. Sans cela, « cerveau » — qui est justement le champ le plus lu —
#: était le seul introuvable, et le message de refus nommait un cerveau vide.
_champ_de_marque() { # marque champ
    local normalisee=";${1#arac:}"
    case "$normalisee" in
        *";$2="*) local r="${normalisee#*;$2=}"; printf '%s' "${r%%;*}" ;;
        *) printf '' ;;
    esac
}

#: Levé dès qu'une plaque d'avant l'empreinte a été rencontrée. L'appelant le
#: dit à voix haute : reconnaître un rôle sur son seul nom est le comportement
#: qu'on corrige, et le pratiquer en silence pendant la transition serait le
#: reconduire.
PLAQUE_SANS_EMPREINTE=0

#: 0 le rôle est le nôtre · 1 il est à un autre, ou on ne peut pas le dire
_role_est_a_nous() { # role
    local m emp
    m="$(_marque_de "$1")"
    [[ -n "$m" ]] || return 1
    case "$m" in arac:cerveau=*) : ;; *) return 1 ;; esac

    emp="$(_champ_de_marque "$m" empreinte)"
    if [[ -n "$emp" ]]; then
        # LE SEUL TEST QUI COMPTE. Pas le nom, pas le dossier de secrets :
        # l'empreinte, et elle seule, appartient à une installation.
        [[ -n "${ARAC_INSTALL_UUID:-}" && "$emp" == "$ARAC_INSTALL_UUID" ]]
        return
    fi

    # PLAQUE D'AVANT L'EMPREINTE. Elle ne peut rien prouver ; on retombe sur
    # le nom, c'est-à-dire sur l'ancien comportement, POUR CE CAS SEUL et en
    # le disant. C'est la migration, pas la règle.
    local nom; nom="$(_champ_de_marque "$m" cerveau)"
    if [[ "$nom" == "$ARAC_DB" ]]; then
        PLAQUE_SANS_EMPREINTE=1
        return 0
    fi
    return 1
}

#: Le cerveau que la plaque désigne, en clair, pour le message de refus.
_proprietaire_lisible() { # role
    local m; m="$(_marque_de "$1")"
    if [[ -z "$m" ]]; then
        printf 'à un propriétaire inconnu — ce rôle ne porte aucune plaque ARAC'
        return 0
    fi
    case "$m" in
        arac:cerveau=*)
            local nom prop emp secrets
            nom="$(_champ_de_marque "$m" cerveau)"
            prop="$(_champ_de_marque "$m" proprietaire)"
            emp="$(_champ_de_marque "$m" empreinte)"
            secrets="$(_champ_de_marque "$m" secrets)"
            printf "l'installation du cerveau « %s »%s, secrets en %s%s" \
                   "$nom" \
                   "${prop:+, déclarée par $prop}" \
                   "${secrets:-?}" \
                   "${emp:+, empreinte $emp}" ;;
        *) printf '%s' "$m" ;;
    esac
}

#: Un rôle étranger porte-t-il le MÊME nom de cerveau que nous ? C'est
#: l'homonymie — le cas fréquent, pas le cas tordu — et elle appelle un
#: message différent de « ce rôle appartient à un autre cerveau ».
_role_est_un_homonyme() { # role
    local m; m="$(_marque_de "$1")"
    [[ -n "$m" ]] || return 1
    [[ "$(_champ_de_marque "$m" cerveau)" == "$ARAC_DB" ]]
}

pg_lire_base() { # requete, dans la base du cerveau
    psql_super -d "$ARAC_DB" -tAc "$1" 2>/dev/null || true
}

table_existe() {
    [[ "$(pg_lire_base "SELECT 1 FROM information_schema.tables WHERE table_schema='$ARAC_SCHEMA' AND table_name='$1'")" == 1 ]]
}

# ===========================================================================
# ÉTAPE 3 — la base et ses rôles
# ===========================================================================

etape_base() {
    etape_entete "$(rang_etape base)" "$TOTAL_ETAPES" "${TITRE_ETAPE[base]}" \
"Tout ce que le cerveau saura tiendra dans une seule base. Les rôles
qui l'entourent ne sont pas de la bureaucratie : ils décident de ce qui est
STRUCTURELLEMENT impossible, plutôt que de ce qui est simplement interdit." \
"La base « $ARAC_DB », son schéma « $ARAC_SCHEMA », les rôles PostgreSQL du
cerveau — quatre qui se connectent, chacun avec un mot de passe engendré
localement, plus « $R_BACKUP » qui n'a pas de connexion —, et un fichier d'environnement à
permissions restreintes qui les porte." \
"Le cockpit se connectera avec un rôle en lecture seule STRICTE. Même un
bogue, même une injection, même une fausse manœuvre ne pourra pas écrire :
la transaction elle-même sera refusée par PostgreSQL."

    exiger_root "base"

    _lecon_quatre_roles

    # --- La base existe-t-elle déjà ? -------------------------------------
    if base_existe; then
        local tables atomes scopes taille
        tables="$(pg_lire_base "SELECT count(*) FROM information_schema.tables WHERE table_schema='$ARAC_SCHEMA'")"
        taille="$(pg_lire "SELECT pg_size_pretty(pg_database_size('$ARAC_DB'))")"
        atomes="—"; scopes="—"
        table_existe memory_atoms && atomes="$(pg_lire_base "SELECT count(*) FROM $ARAC_SCHEMA.memory_atoms")"
        table_existe scopes && scopes="$(pg_lire_base "SELECT count(*) FROM $ARAC_SCHEMA.scopes")"

        alerte "$(_c 1 "La base « $ARAC_DB » existe déjà.")"
        vide
        dire "Voici ce qu'elle contient, avant que vous ne décidiez :"
        dire "   tables (schéma $ARAC_SCHEMA)   ${tables:-0}"
        dire "   souvenirs                  ${atomes:-0}"
        dire "   domaines                   ${scopes:-0}"
        dire "   taille sur disque          ${taille:-inconnue}"
        vide
        note "Ce bootstrap ne SUPPRIME jamais une base. Il continuera dessus :
les migrations manquantes seront appliquées, la taxonomie resemée, les
rôles remis à jour. Aucun souvenir ne sera perdu.
Si vous vouliez repartir de zéro, c'est un geste explicite, à vous :
  sudo -u $ARAC_PG_SUPERUSER dropdb -p $ARAC_DB_PORT $ARAC_DB
Le « -p » désigne LA GRAPPE de ce cerveau. Sans lui, dropdb s'adresse à
celle par défaut de la machine — et détruit la base qui y porte ce nom,
c'est-à-dire, sur un poste à deux serveurs, celle du voisin."
        vide
        if ! confirmer "Continuer sur cette base existante ?" oui; then
            dire "Arrêt demandé. Rien n'a été modifié."
            exit 0
        fi
    else
        plan "CREATE DATABASE $ARAC_DB (encodage UTF8)"
    fi
    plan "CREATE SCHEMA IF NOT EXISTS $ARAC_SCHEMA"
    plan "CREATE ROLE $R_ADMIN, $R_APP, $R_AGENT, $R_READONLY"
    plan "CREATE ROLE $R_BACKUP (sans connexion — exigé par les migrations 0009 et 0010)"
    plan "ALTER ROLE $R_ADMIN CREATEDB (bases JETABLES de vérification de sauvegarde ;
       la base « $ARAC_DB » appartient à $ARAC_PG_SUPERUSER, ce rôle ne peut pas la détruire)"
    plan "mots de passe : 32 octets aléatoires chacun, jamais affichés"
    plan "écriture de $ARAC_SECRETS_ROLES et $ARAC_ENV_FILE (0600, root)"

    reel || { vide; note "Simulation : rien n'a été créé."; return 0; }

    # --- LE REFUS PASSE AVANT LA PREMIÈRE ÉCRITURE -------------------------
    #
    # Cet ordre est le correctif d'une faute constatée en essayant le refus :
    # il venait APRÈS la création de la base et du coffre. Le message disait
    # « Rien n'a été écrit » — et une base « dune » venait de naître, avec son
    # dossier de secrets. La garantie de fond tenait (aucun mot de passe
    # étranger n'avait été touché), mais le compte rendu était faux, et un
    # compte rendu faux dans un message de refus est exactement ce que ce
    # chantier combat : on le croit, on ne va pas voir, et on nettoie à moitié.
    #
    # On lit donc le coffre — lecture seule, aucun dossier créé — pour savoir
    # si ces rôles sont les nôtres, on tranche, et seulement ensuite on écrit.
    local pwd_admin pwd_app pwd_agent pwd_readonly reutilise=0
    if [[ -r "$ARAC_SECRETS_ROLES" ]]; then
        pwd_admin="$(lire_var "$ARAC_SECRETS_ROLES" PWD_ADMIN || true)"
        pwd_app="$(lire_var "$ARAC_SECRETS_ROLES" PWD_APP || true)"
        pwd_agent="$(lire_var "$ARAC_SECRETS_ROLES" PWD_AGENT || true)"
        pwd_readonly="$(lire_var "$ARAC_SECRETS_ROLES" PWD_READONLY || true)"
        [[ -n "$pwd_admin" && -n "$pwd_app" && -n "$pwd_agent" && -n "$pwd_readonly" ]] && reutilise=1
    fi

    _controle_propriete_des_roles "$reutilise" || exit 7

    # --- Le coffre des mots de passe --------------------------------------
    mkdir -p "$ARAC_ETC"; chmod 0700 "$ARAC_ETC"
    if (( reutilise )); then
        bien "Coffre existant réutilisé : $ARAC_SECRETS_ROLES"
        note "  Ce coffre est la preuve que ces rôles sont les nôtres, et c'est à
   ce titre qu'ils ne seront pas retouchés.
   POUR CHANGER UN MOT DE PASSE, ne supprimez pas ce fichier : ce
   bootstrap refuserait de continuer, faute de pouvoir distinguer « mon
   rôle dont j'ai perdu le secret » de « le rôle du voisin ». La
   rotation est un geste à vous, en deux temps — ALTER ROLE dans psql,
   puis la même valeur ici — et vous saurez alors quels services
   redémarrer. Voir le message de refus, qui donne les deux lignes."
    else
        pwd_admin="$(secret_hex 32)"; pwd_app="$(secret_hex 32)"
        pwd_agent="$(secret_hex 32)"; pwd_readonly="$(secret_hex 32)"
        poser_var "$ARAC_SECRETS_ROLES" PWD_ADMIN    "$pwd_admin"
        poser_var "$ARAC_SECRETS_ROLES" PWD_APP      "$pwd_app"
        poser_var "$ARAC_SECRETS_ROLES" PWD_AGENT    "$pwd_agent"
        poser_var "$ARAC_SECRETS_ROLES" PWD_READONLY "$pwd_readonly"
        bien "Quatre mots de passe engendrés localement, jamais affichés."
        note "  Coffre : $ARAC_SECRETS_ROLES (0600, root:root)"
    fi

    # --- La base ----------------------------------------------------------
    if ! base_existe; then
        if ! psql_super -d postgres -c "CREATE DATABASE \"$ARAC_DB\" ENCODING 'UTF8'" >/dev/null; then
            echec "création de la base $ARAC_DB" \
                  "PostgreSQL a refusé le CREATE DATABASE." \
                  "sudo -u $ARAC_PG_SUPERUSER psql -p $ARAC_DB_PORT -c \"CREATE DATABASE \\\"$ARAC_DB\\\" ENCODING 'UTF8'\"
Le « -p » vise la grappe de ce cerveau : sans lui, la base serait créée
sur celle par défaut de la machine, pendant que les DSN écrits ici
continueraient de pointer sur $ARAC_DB_HOTE:$ARAC_DB_PORT.
puis relancez : $(geste_bootstrap "--from base")"
            exit 7
        fi
        bien "Base « $ARAC_DB » créée."
    fi
    psql_super -d "$ARAC_DB" -c "CREATE SCHEMA IF NOT EXISTS $ARAC_SCHEMA" >/dev/null
    bien "Schéma « $ARAC_SCHEMA » présent."

    # --- Les rôles ---------------------------------------------------------
    #
    # La propriété a été tranchée plus haut, AVANT toute écriture. Ce qui
    # existe ici a été reconnu comme nôtre ; ce qui manque va être créé et
    # marqué. Aucun mot de passe préexistant n'est retouché.
    local sql; sql="$(_sql_roles "$pwd_admin" "$pwd_app" "$pwd_agent" "$pwd_readonly")"
    if ! printf '%s' "$sql" | psql_super -d "$ARAC_DB" -q -f - >/dev/null; then
        echec "création des rôles" \
              "Le DDL des rôles a été refusé. Le détail est au-dessus." \
              "Vérifiez que vous êtes bien superutilisateur PostgreSQL :
  sudo -u $ARAC_PG_SUPERUSER psql -p $ARAC_DB_PORT -c '\\du'
puis relancez : $(geste_bootstrap "--from base")"
        exit 7
    fi
    unset sql
    # LA PLAQUE SE MET À JOUR — une fois, pour les rôles d'avant l'empreinte.
    #
    # Ce n'est pas un `ALTER ROLE` : un commentaire ne change ni le mot de
    # passe ni les droits. C'est le seul geste qui fasse sortir de la
    # transition, et il n'est joué que sur des rôles déjà reconnus comme les
    # nôtres, quelques lignes plus haut, avant toute écriture.
    if (( PLAQUE_SANS_EMPREINTE )); then
        local r
        for r in "$R_ADMIN" "$R_APP" "$R_AGENT" "$R_READONLY" "$R_BACKUP"; do
            role_existe "$r" || continue
            psql_super -d "$ARAC_DB" -c \
                "COMMENT ON ROLE $r IS '$(_marque_role)'" >/dev/null || true
        done
        bien "Plaques mises à jour : elles portent désormais l'empreinte $ARAC_INSTALL_UUID."
    fi
    bien "Rôles qui se connectent, en place : $R_ADMIN · $R_APP · $R_AGENT · $R_READONLY"
    note "  Et un cinquième, $R_BACKUP, sans connexion possible : les migrations
   0009 et 0010 lui donnent SELECT, et PostgreSQL refuse un GRANT vers un
   rôle absent. Sans lui, l'étape 5 ne passerait pas."

    # --- Le fichier d'environnement ----------------------------------------
    local hp="$ARAC_DB_HOTE:$ARAC_DB_PORT/$ARAC_DB"
    # LES QUATRE DSN SE DÉDUISENT DE `ROLES_AVEC_DSN` (lib/core.sh).
    # Ces quatre lignes vivaient à l'identique ici, dans `lib/secrets.sh` (la
    # traduction vers `DATABASE_URL_*`) et dans `checks/verify_install.sh` (la
    # relecture sous chaque rôle) : TROIS écritures d'une même liste, qu'aucun
    # mécanisme ne tenait ensemble. Un cinquième DSN ajouté ici serait resté
    # muet dans les deux autres.
    local _l _v_arac _v_db _v_role _v_pwd
    for _l in "${DSN_PAR_ROLE[@]}"; do
        read -r _v_arac _v_db _v_role _v_pwd <<< "$_l"
        poser_var "$ARAC_ENV_FILE" "$_v_arac" "postgresql://${!_v_role}:${!_v_pwd}@$hp"
    done
    poser_var "$ARAC_ENV_FILE" ARAC_HOME     "$ARAC_HOME"
    poser_var "$ARAC_ENV_FILE" ARAC_DB       "$ARAC_DB"
    poser_var "$ARAC_ENV_FILE" ARAC_SCHEMA   "$ARAC_SCHEMA"
    poser_var "$ARAC_ENV_FILE" ARAC_NODE_ID  "$ARAC_NODE_ID"
    # LE SERVEUR OÙ CE CERVEAU VIT — écrit, et pas seulement enfoui dans les DSN.
    #
    # `ARAC_DB_PORT` n'était nulle part en clair : il ne vivait qu'à l'intérieur
    # des quatre URL de connexion. Tout ce qui voulait interroger la base sans
    # DSN — au premier rang `bootstrap/checks/verify_install.sh`, que la
    # documentation fait lancer à l'étape 6 — retombait donc sur 5432, c'est-à-
    # dire sur le cluster par défaut de la machine. Un cerveau installé sur son
    # propre cluster était contrôlé contre celui du voisin.
    poser_var "$ARAC_ENV_FILE" ARAC_DB_HOTE  "$ARAC_DB_HOTE"
    poser_var "$ARAC_ENV_FILE" ARAC_DB_PORT  "$ARAC_DB_PORT"
    # Les noms comptent : `arac_runtime.py` lit ARAC_BRAIN_NAME et
    # ARAC_BRAIN_OWNER. Ce fichier a longtemps écrit ARAC_BRAIN et ARAC_OWNER —
    # deux variables que RIEN ne lisait, pendant que le moteur retombait
    # silencieusement sur `config/brain.toml`. Une surcharge qui ne surcharge
    # rien ne se remarque jamais : elle marche, mais pour la mauvaise raison.
    poser_var "$ARAC_ENV_FILE" ARAC_BRAIN_NAME  "$BRAIN_NOM"
    poser_var "$ARAC_ENV_FILE" ARAC_BRAIN_OWNER "$BRAIN_OWNER"
    # L'EMPREINTE VIT AUSSI ICI, ET PAS SEULEMENT SUR LES RÔLES.
    #
    # Deux raisons, et la seconde est la vraie. La première : l'étape 2 la lit
    # pour refuser un homonyme AVANT d'ouvrir le coffre, sans avoir besoin de
    # PostgreSQL. La seconde : c'est ce qui rend le refus RÉVERSIBLE. Quelqu'un
    # qui a perdu son config/brain.toml n'a pas perdu son cerveau — le message
    # de refus lui montre cette ligne, il la recopie, il est reconnu. Un garde
    # dont on ne peut pas sortir n'est pas un garde, c'est une porte murée.
    poser_var "$ARAC_ENV_FILE" ARAC_INSTALL_UUID "$ARAC_INSTALL_UUID"
    # LES PORTS RETENUS VIVENT ICI, PAS DANS UNE CONSTANTE.
    # C'est ce qui rend une réinstallation stable : l'étape 2 les relit avant
    # d'en chercher de libres. Sans cela, un cerveau installé sur 8001 parce
    # que 8000 était pris reprendrait 8000 le jour où le voisin s'arrête — et
    # tout ce qui pointait vers 8001 (tunnel SSH, signets, scripts) casserait
    # sans qu'une seule ligne de configuration ait été touchée.
    poser_var "$ARAC_ENV_FILE" ARAC_API_PORT     "$ARAC_API_PORT"
    poser_var "$ARAC_ENV_FILE" ARAC_COCKPIT_PORT "$ARAC_COCKPIT_PORT"
    # LE PORT NE SUFFIT PAS : IL FAUT AUSSI L'ADRESSE COMPLÈTE.
    #
    # Le cockpit n'interroge pas la base pour tout : il passe par l'API de SON
    # cerveau (`control_center/collectors/brain_api.py`), dont il lit l'adresse
    # dans ARAC_API_BASE. Cette variable n'était écrite NULLE PART — ni ici, ni
    # dans l'unité du cockpit — pendant que l'unité de cycle recevait bien son
    # ARAC_API_URL dérivé du port. Le collecteur retombait donc sur son défaut,
    # http://127.0.0.1:8000, c'est-à-dire sur le PREMIER cerveau de la machine.
    #
    # Constaté sur pièces : la page /cc/brain du cockpit du second cerveau
    # affichait la taxonomie complète du premier. Ce n'est pas une destruction,
    # c'est pire — c'est un cerveau qui montre à quelqu'un la mémoire d'un
    # autre, sans une erreur, sans une ligne de journal, et avec un cadenas
    # vert dans la barre d'adresse.
    #
    # Les deux noms existent parce que deux publics les lisent : ARAC_API_URL
    # pour les agents (cycle, cortex, orchestrateur), ARAC_API_BASE pour le
    # cockpit. `bootstrap/checks/env_contract.toml` fige déjà ce contrat ; il
    # n'était honoré que pour moitié.
    poser_var "$ARAC_ENV_FILE" ARAC_API_BASE "http://127.0.0.1:$ARAC_API_PORT"
    poser_var "$ARAC_ENV_FILE" ARAC_API_URL  "http://127.0.0.1:$ARAC_API_PORT"
    # Les noms propres de ce cerveau, pour tout ce qui vient après : les
    # scripts d'exploitation (ops/env.sh) et le contrôle de santé les lisent
    # au lieu de les recalculer — deux calculs valent deux vérités.
    poser_var "$ARAC_ENV_FILE" ARAC_ROLE_PREFIX  "$ARAC_ROLE_PREFIX"
    poser_var "$ARAC_ENV_FILE" ARAC_UNIT_PREFIX  "$PREFIXE_UNITE"
    # LE COMPTE QUI DIGÈRE — écrit ici parce que trois lecteurs en ont besoin
    # et qu'aucun ne doit le recalculer : le contrôle de santé, qui va lire
    # l'authentification du binaire de curation SOUS CE COMPTE ; l'écran de
    # fin, qui doit nommer sous quel compte ouvrir la session ; et vous, le
    # jour où vous chercherez qui a écrit dans /var/lib/arac.
    poser_var "$ARAC_ENV_FILE" ARAC_AGENT_USER   "$ARAC_AGENT_USER"
    # Le chemin du binaire de curation, s'il a été NOMMÉ à l'installation.
    # Sans cette ligne, un `ARAC_CLAUDE_BIN=…` passé au bootstrap vivait le
    # temps de l'installation et disparaissait : le service, lui, ne le voyait
    # jamais — donc le cycle cherchait de nouveau dans le PATH, et échouait
    # exactement comme avant. Ce qu'on a dit à l'installation doit survivre à
    # l'installation.
    [[ -n "${ARAC_CLAUDE_BIN:-}" ]] && \
        poser_var "$ARAC_ENV_FILE" ARAC_CLAUDE_BIN "$ARAC_CLAUDE_BIN"
    poser_var "$ARAC_ENV_FILE" ARAC_LOG_DIR      "$ARAC_LOG_DIR"
    poser_var "$ARAC_ENV_FILE" ARAC_BACKUP_DIR   "$ARAC_BACKUP_DIR"
    poser_var "$ARAC_ENV_FILE" ARAC_BACKUP_PREFIX "$ARAC_DB"
    unset pwd_admin pwd_app pwd_agent pwd_readonly
    bien "Environnement écrit : $ARAC_ENV_FILE (0600, root:root)"
    note "  systemd le lira en PID 1, avant d'abandonner ses privilèges. Les
   services tournent sous « $ARAC_SERVICE_USER » et ne touchent jamais ce
   fichier directement."
    return 0
}

#: LE REFUS. Il vaut mieux qu'une installation s'arrête ici, en disant tout,
#: qu'une autre production tombe demain sans que personne sache pourquoi.
_controle_propriete_des_roles() { # coffre_reutilise
    local coffre_reutilise="$1"
    local etrangers=() a_nous=() r
    for r in "$R_ADMIN" "$R_APP" "$R_AGENT" "$R_READONLY" "$R_BACKUP"; do
        role_existe "$r" || continue
        if _role_est_a_nous "$r"; then a_nous+=("$r"); else etrangers+=("$r"); fi
    done

    # Cas 1 — rien ne préexiste. On crée, on marque, on continue.
    (( ${#etrangers[@]} == 0 && ${#a_nous[@]} == 0 )) && return 0

    # Cas 2 — tout ce qui préexiste porte NOTRE plaque.
    if (( ${#etrangers[@]} == 0 )); then
        if (( coffre_reutilise )); then
            bien "Rôles déjà en place et reconnus comme les nôtres : ${a_nous[*]}"
            note "  Leur mot de passe n'est PAS retouché : il est déjà dans le coffre.
   Ce bootstrap n'exécute jamais ALTER ROLE … PASSWORD — c'est
   l'instruction exacte qui a détruit une production."
            if (( PLAQUE_SANS_EMPREINTE )); then
                alerte "Reconnus sur leur NOM seul — leur plaque est antérieure à l'empreinte."
                note "  C'est l'ancien comportement, et il ne prouve rien : n'importe
   quelle installation qui aurait choisi le nom « $ARAC_DB » aurait été
   reconnue de la même façon. La plaque va être remise à jour avec
   l'empreinte de CETTE installation ($ARAC_INSTALL_UUID) ; à partir
   de la prochaine fois, le nom ne suffira plus.
   Si ces rôles ne sont pas les vôtres, arrêtez maintenant (Ctrl-C)."
            fi
            return 0
        fi
        # Nos rôles, mais le coffre a disparu : on ne peut pas se reconnecter,
        # et on ne réencodera pas pour autant. Le geste est à l'opérateur.
        vide
        mal "$(_c 1 'Ces rôles sont les nôtres, mais leur mot de passe est perdu.')"
        vide
        dire "   ${a_nous[*]}"
        vide
        note "Leur plaque désigne bien ce cerveau (« $ARAC_DB »), mais le coffre
qui portait leurs mots de passe est absent ou incomplet :
  $ARAC_SECRETS_ROLES

Ce bootstrap ne réencode JAMAIS un rôle qu'il n'a pas créé dans la
même exécution. Ce n'est pas de la prudence de principe : c'est
l'instruction « ALTER ROLE … PASSWORD » qui a détruit une production,
parce qu'elle réussit toujours, ne dit rien, et n'échoue que chez le
voisin, plus tard.

Le geste vous appartient donc — et il est court. Choisissez un mot de
passe, posez-le des deux côtés, dans cet ordre :

  sudo -u $ARAC_PG_SUPERUSER psql -p $ARAC_DB_PORT \\
       -c \"ALTER ROLE $R_APP PASSWORD 'xxx'\"      # …et les quatre autres
  sudoedit $ARAC_SECRETS_ROLES                      # PWD_APP=xxx, etc.

Puis relancez. Vous saurez alors exactement quels services redémarrer."
        vide
        dire "$(_c 1 'Aucun mot de passe n'\''a été changé. Rien n'\''a été écrit.')"
        vide
        return 1
    fi

    # Cas 3 — au moins un rôle appartient à quelqu'un d'autre. REFUS NET.
    vide
    mal "$(_c 1 'REFUS — ces rôles ne sont pas les nôtres.')"
    vide
    dire "Sur ce cluster PostgreSQL (port $ARAC_DB_PORT), ces rôles existent déjà :"
    vide
    for r in "${etrangers[@]}"; do
        dire "   $(_c 1 "$r")"
        dire "      appartient à $(_proprietaire_lisible "$r")"
    done
    vide
    dire "$(_c 1 'CE QU'\''UN RÔLE EST, ET POURQUOI CELA COMPTE ICI')"
    note "Un rôle PostgreSQL est une identité de connexion, avec son mot de
passe et ses droits. Il vit dans le CLUSTER, au-dessus des bases : il
n'appartient à aucune d'elles, et toutes le voient. « $R_APP » n'est
donc pas « le rôle applicatif de ma base » — c'est LE rôle de ce nom,
sur ce serveur, pour tout le monde."
    vide
    dire "$(_c 1 'CE QUE LE RÉUTILISER DÉTRUIRAIT')"
    note "Pour m'en servir, il me faudrait son mot de passe. Ne l'ayant pas,
la seule façon de continuer serait de le CHANGER — et changer le mot
de passe d'un rôle, c'est retirer l'accès à tout ce qui s'en sert
aujourd'hui. Le propriétaire ne s'en apercevrait pas maintenant : ses
services ont déjà leur connexion ouverte. Il s'en apercevrait au
prochain redémarrage, sans aucun lien visible avec cette installation.

C'est arrivé. Cinq rôles de production perdus d'un coup, et une
soirée pour comprendre pourquoi.

Je ne le fais donc pas, et aucun drapeau ne me le fera faire."
    vide
    dire "$(_c 1 'LE GESTE')"
    if _role_est_un_homonyme "${etrangers[0]}"; then
        # HOMONYMIE — le cas fréquent. Le nom est le même, l'installation non.
        local emp_trouvee
        emp_trouvee="$(_champ_de_marque "$(_marque_de "${etrangers[0]}")" empreinte)"
        note "Ces rôles portent le nom de ce cerveau (« $ARAC_DB ») mais l'empreinte
d'une AUTRE installation :

   trouvée sur les rôles   ${emp_trouvee:-aucune}
   attendue ici            ${ARAC_INSTALL_UUID:-aucune}   (config/brain.toml)

Deux issues, et il faut choisir selon qui vous êtes."
        vide
        dire "  · $(_c 1 'Ce cerveau est le vôtre') — vous avez reconstruit ou reperdu"
        dire "    config/brain.toml. Son empreinte n'est pas perdue pour autant :"
        dire "    elle est gravée sur les rôles, et écrite dans votre coffre."
        cmd "sudo grep '^ARAC_INSTALL_UUID=' $ARAC_ENV_FILE"
        dire "    Reportez-la dans config/brain.toml, section [brain] :"
        cmd "uuid = \"${emp_trouvee:-…}\""
        dire "    puis relancez. Vous serez alors reconnu, et rien ne sera recréé."
        vide
        dire "  · $(_c 1 'Ce cerveau est celui de quelqu'\''un d'\''autre') — donnez au vôtre"
        dire "    un autre nom. C'est une ligne, et tout suit : la base, les"
        dire "    rôles, les secrets, les unités, les dossiers."
        cmd "\$EDITOR $ARAC_HOME/config/brain.toml     # brain.name = \"…\""
        cmd "$(geste_bootstrap "--from config")"
        vide
        note "Je ne peux pas trancher à votre place : je constate deux empreintes
différentes, pas une intention. Ce que je peux garantir, c'est que la
reprise du cerveau d'un autre ne se fera plus toute seule — il y faut
désormais un geste, écrit, que vous aurez fait exprès."
    else
        note "Ces rôles ne portent aucune plaque ARAC : ils viennent d'avant ce
nommage, ou d'une autre application. Deux issues, toutes deux à vous :

  · donnez un autre nom à ce cerveau (config/brain.toml, brain.name),
    et tout suit — c'est la voie sûre ;
  · ou, si vous êtes CERTAIN que ces rôles sont des restes dont plus
    rien ne se sert, retirez-les vous-même, puis relancez :
      sudo -u $ARAC_PG_SUPERUSER psql -p $ARAC_DB_PORT \\
           -c 'DROP ROLE ${etrangers[0]}'
    PostgreSQL refusera tant qu'un objet leur appartient — c'est le
    dernier filet, et il vaut mieux qu'il se déclenche."
    fi
    vide
    dire "$(_c 1 'Aucun mot de passe n'\''a été changé. Rien n'\''a été écrit.')"
    vide
    return 1
}

_lecon_quatre_roles() {
    dire "$(_c 1 'Pourquoi quatre rôles qui se connectent, et non un')"
    vide
    dire "   $(printf '%-12s' "$R_ADMIN")  crée et modifie les tables. Ne sert QU'aux migrations."
    dire "   $(printf '%-12s' "$R_APP")  l'API : lit, insère, met à jour. Ne peut rien DÉTRUIRE."
    dire "   $(printf '%-12s' "$R_AGENT")  les cycles : lit tout, n'écrit que sa trace de travail."
    dire "   $(printf '%-12s' "$R_READONLY")  le cockpit : lecture seule STRICTE."
    vide
    note "« Sa trace de travail », pour le rôle des cycles, ce sont cinq tables
nommées une à une : le registre de dépense, le curseur de digestion, la
file de revue humaine, le cache des domaines, les liens entre atomes.
Pas « memory_atoms ». Un cycle ne peut pas écrire un souvenir dans votre
mémoire — il ne peut que proposer, et c'est l'API, sous votre décision,
qui écrit. C'est pour cela que le rôle du cycle n'est pas celui de l'API."
    note "Un seul rôle « qui peut tout » aurait été plus simple à installer, et
c'est exactement pour cela qu'il est dangereux : le jour où le cockpit a un
bogue, il écrit dans la mémoire. Ici, il ne le peut pas — le rôle du
cockpit porte default_transaction_read_only = on, donc PostgreSQL ouvre
toutes ses transactions en lecture seule et refuse le moindre INSERT avant
même de le lire.

C'est la différence entre « interdit » et « impossible »."
    vide
}

_sql_roles() { # pwd_admin pwd_app pwd_agent pwd_readonly
    cat <<SQL
\\set ON_ERROR_STOP on
BEGIN;

-- CE BLOC NE CONTIENT AUCUN « ALTER ROLE … PASSWORD », ET C'EST LE POINT.
--
-- Il en contenait quatre. Chacun était gardé par un « IF EXISTS », ce qui
-- avait toutes les apparences de la prudence : on ne créait pas deux fois,
-- on mettait « à jour ». Sauf qu'un rôle est global au cluster — le rôle
-- trouvé n'était pas le nôtre d'hier, c'était celui du voisin, et « mettre à
-- jour » son mot de passe, c'est lui retirer sa base.
--
-- On ne crée donc QUE ce qui n'existe pas. Ce qui existe a déjà été reconnu
-- comme nôtre par _controle_propriete_des_roles (pas de guillemets obliques
-- ici : ce document en ligne est NON protégé, une paire de backquotes y
-- serait une substitution de commande, exécutée à la génération du SQL),
-- sans quoi ce SQL n'aurait
-- jamais été engendré : le mot de passe en place est celui du coffre, et il
-- n'y a rien à changer.
DO \$arac\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$R_ADMIN') THEN
    CREATE ROLE $R_ADMIN WITH LOGIN PASSWORD '$1';
    COMMENT ON ROLE $R_ADMIN IS '$(_marque_role)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$R_APP') THEN
    CREATE ROLE $R_APP WITH LOGIN PASSWORD '$2';
    COMMENT ON ROLE $R_APP IS '$(_marque_role)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$R_AGENT') THEN
    CREATE ROLE $R_AGENT WITH LOGIN PASSWORD '$3';
    COMMENT ON ROLE $R_AGENT IS '$(_marque_role)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$R_READONLY') THEN
    CREATE ROLE $R_READONLY WITH LOGIN PASSWORD '$4';
    COMMENT ON ROLE $R_READONLY IS '$(_marque_role)';
  END IF;
  -- LE CINQUIÈME RÔLE, QUE PERSONNE NE DEMANDE ET QUE TOUT LE MONDE SUPPOSE.
  --
  -- Les migrations n'exigent pas quatre rôles, elles en exigent CINQ :
  --   db/alembic/versions/0009_grants_raw_conv_node.py
  --   db/alembic/versions/0010_incoming_proposal_queue.py
  -- toutes deux : GRANT SELECT ... TO le rôle de sauvegarde de CE cerveau,
  -- soit ici $R_BACKUP (les migrations le déduisent du rôle d'administration
  -- sous lequel elles tournent — voir db/alembic/roles.py).
  -- PostgreSQL refuse un GRANT vers un rôle absent. Sur une grappe vierge,
  -- l'installation mourait donc à l'étape 5 sur :
  --       psycopg.errors.UndefinedObject: role "arac_backup" does not exist
  -- Invisible partout où ce rôle existait déjà — c'est-à-dire sur toute
  -- machine ayant hébergé un cerveau. Il a fallu une grappe neuve pour le voir.
  --
  -- Créé SANS LOGIN, et c'est délibéré : le contrat des migrations demande
  -- qu'on puisse lui DONNER des droits, pas qu'on puisse s'y connecter. Un
  -- rôle connectable dont personne ne se sert est une porte de plus, avec un
  -- mot de passe que rien ne fait tourner. L'unité de sauvegarde posée à
  -- l'étape 9 utilise le rôle d'administration, pas celui-ci.
  -- Le jour où vous voudrez sauvegarder sous ce rôle :
  --       ALTER ROLE $R_BACKUP WITH LOGIN PASSWORD '…';
  --
  -- On ne touche JAMAIS à un rôle existant : sur un serveur où il a déjà été
  -- provisionné avec LOGIN, le remettre en NOLOGIN casserait ses sauvegardes.
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$R_BACKUP') THEN
    CREATE ROLE $R_BACKUP WITH NOLOGIN;
    COMMENT ON ROLE $R_BACKUP IS '$(_marque_role)';
  END IF;
END
\$arac\$;

-- Le cockpit ne peut pas écrire : ce n'est pas une convention, c'est le
-- moteur qui refuse d'ouvrir une transaction en écriture pour ce rôle.
ALTER ROLE $R_READONLY SET default_transaction_read_only = on;

-- LE RÔLE D'ADMINISTRATION PEUT CRÉER DES BASES — et c'est ce qui rend une
-- sauvegarde PROUVABLE au lieu de supposée.
--
-- « ops/restore_verify.sh » restaure un dump dans une base JETABLE, la lit,
-- puis la détruit. C'est le seul contrôle qui distingue « un fichier existe »
-- de « ce fichier contient le cerveau ». Sans cet attribut, il mourait sur
-- « permission denied to create database » sur TOUTE installation posée par
-- ce bootstrap — et la réserve « aucune restauration n'a jamais été
-- vérifiée » d'ops/install_check.sh ne pouvait être levée par personne. Une
-- promesse que le produit ne sert pas est un mensonge à retardement : ici
-- elle se paye le jour du désastre.
--
-- POURQUOI C'EST SÛR, ET MESURABLE :
--   · CREATEDB ne donne AUCUN droit sur une base existante. Ce n'est pas un
--     droit d'accès, c'est un droit de fabrication.
--   · La base vivante « $ARAC_DB » appartient au superutilisateur PostgreSQL,
--     pas à $R_ADMIN. Un rôle ne peut détruire ou renommer que les bases dont
--     il est PROPRIÉTAIRE : ce rôle ne peut donc pas détruire le cerveau.
--     Mesuré : DROP DATABASE rendu « must be owner of database ».
--   · Le cerveau du VOISIN reste hors d'atteinte : son CONNECT est révoqué
--     de PUBLIC, et CREATEDB n'en donne pas.
--   · $R_ADMIN possède déjà le schéma « $ARAC_SCHEMA » et fait tourner les
--     migrations : il peut déjà détruire les tables de CE cerveau. CREATEDB
--     n'agrandit pas ce périmètre, il en ouvre un autre, à côté, jetable.
--
-- C'est le privilège MINIMAL qui rend le contrôle possible — et infiniment
-- moins que le superutilisateur, que la page SAUVEGARDE refuse à juste titre
-- de réclamer toutes les semaines.
ALTER ROLE $R_ADMIN CREATEDB;

-- Personne d'autre ne se connecte à cette base.
REVOKE CONNECT ON DATABASE "$ARAC_DB" FROM PUBLIC;
GRANT  CONNECT ON DATABASE "$ARAC_DB" TO $R_ADMIN, $R_APP, $R_AGENT, $R_READONLY;
-- Pas de CONNECT pour $R_BACKUP : il est NOLOGIN. Le lui donner le jour où
-- on l'ouvrira est un geste de plus, donc une décision de plus.

-- Le schéma public reste vide et fermé : tout vit dans $ARAC_SCHEMA.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

ALTER SCHEMA $ARAC_SCHEMA OWNER TO $R_ADMIN;
GRANT USAGE ON SCHEMA $ARAC_SCHEMA TO $R_APP, $R_AGENT, $R_READONLY;
GRANT ALL   ON SCHEMA $ARAC_SCHEMA TO $R_ADMIN;

COMMIT;
SQL
}

#: LES SIX TABLES QUE LE CYCLE DE DIGESTION ÉCRIT, ET RIEN D'AUTRE.
#:
#: Le rôle « agent » ne recevait que SELECT. Or le cycle — le maillon qui
#: transforme les conversations en souvenirs — se connecte avec CE rôle
#: (agents/cortex/cycle.py : `DATABASE_URL_AGENT`) et commence par un INSERT.
#: Aucun cycle ne pouvait donc aboutir sur une installation neuve, et la panne
#: n'apparaissait qu'au premier passage nocturne, longtemps après le bootstrap.
#:
#: Deux réparations étaient possibles. Faire pointer le cycle sur le rôle de
#: l'API aurait suffi à le débloquer — et lui aurait donné INSERT sur les
#: TRENTE-DEUX tables, dont `memory_atoms`. Un cycle qui a le droit d'écrire
#: directement un souvenir n'est plus un proposeur, c'est un auteur : la
#: garantie « l'agent propose, l'humain dispose » cesse d'être structurelle.
#: On accorde donc l'écriture table par table, sur la surface réelle.
#:
#:   run_receipts           le registre de dépense, écrit AVANT tout appel payant
#:   conversations          le curseur de digestion (jusqu'où on a lu, backoff)
#:   digestion_review_queue les candidats écartés, mis en attente de revue humaine
#:   project_registry       le cache des centroïdes par domaine (recalculé)
#:   atom_links             les liens entre atomes (recalculés à chaque cycle)
#:
#: Ce que l'agent n'a TOUJOURS pas, et ne doit pas avoir : INSERT/UPDATE sur
#: `memory_atoms`, `raw_messages`, `nodes`, `arac_config`. Il lit tout, il
#: n'écrit que sa propre trace de travail. Ajouter une table ici est une
#: décision, pas une formalité : elle élargit ce qu'un cycle emballé peut faire.
#:
#: Une table absente est ignorée sans erreur : `appliquer_droits` tourne aussi
#: après l'étape 3, quand les migrations n'ont encore rien créé.
_TABLES_ECRITES_PAR_AGENT="run_receipts conversations digestion_review_queue project_registry atom_links"

#: REPRENDRE POSSESSION DU SCHÉMA — ce que `pg_restore --no-owner` a perdu.
#:
#: CE QUE CETTE FONCTION RÉPARE, ET ELLE A ÉTÉ MESURÉE SUR UN CERVEAU RÉEL.
#: `docs/SAUVEGARDE.md` §7 — le chapitre qu'on exécute en panique — fait
#: restaurer le dump sous le compte `postgres`, avec `--no-owner
#: --no-privileges`. Le schéma « $ARAC_SCHEMA » renaît alors PROPRIÉTÉ DU
#: SUPERUTILISATEUR, sans un seul droit pour les cinq rôles du cerveau. La page
#: clôt ensuite la bascule par `bootstrap.sh --only migrations`, annoncée en
#: toutes lettres comme « la commande qui met le schéma à niveau ET réapplique
#: les droits ».
#:
#: Elle ne le faisait pas. `alembic` se connecte sous $R_ADMIN et lit
#: `$ARAC_SCHEMA.alembic_version` AVANT que le moindre droit ne soit
#: réappliqué : « permission denied for schema $ARAC_SCHEMA », code 7. Et le
#: remède imprimé par cet échec — rejouer alembic à la main sous le même
#: DSN — échouait à l'identique. Le lecteur venait de renommer sa base
#: vivante en « <base>_avarie_… » : il n'avait plus de cerveau, et les deux
#: seules commandes que la page lui donnait rendaient la même erreur.
#:
#: `appliquer_droits` ne rattrapait rien non plus : elle ne fait que des
#: « GRANT … ON ALL TABLES IN SCHEMA », jamais un `GRANT USAGE ON SCHEMA` ni
#: un `ALTER SCHEMA … OWNER`. Un GRANT sur les tables d'un schéma auquel on
#: n'a pas USAGE n'ouvre rien : la porte de la pièce reste fermée.
#:
#: TROIS CHOSES SE RÉPARENT ICI, ET AUCUNE NE TOUCHE À UN RÔLE.
#:   1. la PORTE de la base — `REVOKE CONNECT … FROM PUBLIC` puis le CONNECT
#:      des quatre rôles. Une base fabriquée par `createdb` naît ouverte à
#:      PUBLIC : après une bascule, le cerveau restauré était connectable par
#:      tout rôle de la grappe, y compris ceux du voisin. Mesuré : `datacl`
#:      NULL sur la base issue du §7, contre un ACL fermé sur l'originale.
#:   2. la PROPRIÉTÉ du schéma et de tout ce qu'il contient. Un GRANT ne
#:      suffit pas : `ALTER TABLE` exige d'être PROPRIÉTAIRE, donc sans cette
#:      reprise la migration SUIVANTE échouerait à son tour.
#:   3. l'IDENTITÉ, gravée dans le commentaire du schéma — voir plus bas.
#:
#: Elle est idempotente et ne fait rien quand tout est déjà en ordre : sur une
#: installation saine, aucune des boucles ne trouve d'objet à reprendre.
reprendre_le_schema() {
    reel || return 0

    # L'EMPREINTE VOYAGE AVEC LES DONNÉES, PAS À CÔTÉ D'ELLES.
    #
    # `config/brain.toml` porte une empreinte « choisie par personne », et le
    # bootstrap la grave sur les rôles PostgreSQL. Les rôles sont GLOBAUX à la
    # grappe : ils ne sont pas dans le dump. Un dump ne disait donc pas de quel
    # cerveau il venait — et `ops/restore_verify.sh` concluait quand même.
    #
    # Un commentaire de schéma, lui, EST dans le dump : le `pg_dump --schema`
    # d'ops/backup.sh l'emporte avec les tables. C'est le seul endroit
    # où l'identité d'une installation peut voyager dans le fichier qu'on
    # restaure, sans dépendre du nom qu'on a donné à ce fichier.
    local marque
    marque="ARAC cerveau=$ARAC_DB empreinte=${ARAC_INSTALL_UUID:-} poste=${ARAC_NODE_ID:-}"

    psql_super -d "$ARAC_DB" -q -f - <<SQL >/dev/null
\\set ON_ERROR_STOP on
BEGIN;

-- 1. LA PORTE. Personne d'autre que les rôles de ce cerveau n'entre ici.
REVOKE CONNECT ON DATABASE "$ARAC_DB" FROM PUBLIC;
GRANT  CONNECT ON DATABASE "$ARAC_DB" TO $R_ADMIN, $R_APP, $R_AGENT, $R_READONLY;

-- 2. LA PROPRIÉTÉ, objet par objet. On ne touche qu'à ce qui n'est pas déjà
--    au rôle d'administration : sur une installation saine, zéro instruction.
DO \$arac_pos\$
DECLARE r record;
BEGIN
    IF to_regnamespace('$ARAC_SCHEMA') IS NULL THEN RETURN; END IF;

    IF (SELECT nspowner FROM pg_namespace WHERE nspname = '$ARAC_SCHEMA')
       <> '$R_ADMIN'::regrole THEN
        EXECUTE format('ALTER SCHEMA %I OWNER TO %I', '$ARAC_SCHEMA', '$R_ADMIN');
    END IF;

    -- Tables, partitions, vues, vues matérialisées, tables distantes.
    -- Les INDEX suivent leur table : les nommer serait une erreur.
    FOR r IN
        SELECT c.oid::regclass AS obj,
               CASE c.relkind WHEN 'v' THEN 'VIEW'
                              WHEN 'm' THEN 'MATERIALIZED VIEW'
                              WHEN 'f' THEN 'FOREIGN TABLE'
                              ELSE 'TABLE' END AS genre
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = '$ARAC_SCHEMA'
           AND c.relkind IN ('r','p','v','m','f')
           AND c.relowner <> '$R_ADMIN'::regrole
    LOOP
        EXECUTE format('ALTER %s %s OWNER TO %I', r.genre, r.obj, '$R_ADMIN');
    END LOOP;

    -- Les séquences AUTONOMES seulement. Celle qui est rattachée à une colonne
    -- a suivi sa table à la boucle précédente, et PostgreSQL refuse qu'on
    -- l'en détache (« cannot change owner of sequence »).
    FOR r IN
        SELECT c.oid::regclass AS obj
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = '$ARAC_SCHEMA'
           AND c.relkind = 'S'
           AND c.relowner <> '$R_ADMIN'::regrole
           AND NOT EXISTS (SELECT 1 FROM pg_depend d
                            WHERE d.classid = 'pg_class'::regclass
                              AND d.objid   = c.oid
                              AND d.deptype IN ('a','i'))
    LOOP
        EXECUTE format('ALTER SEQUENCE %s OWNER TO %I', r.obj, '$R_ADMIN');
    END LOOP;

    -- Les types NOMMÉS par une migration. Les composites d'une table et les
    -- tableaux qui les doublent suivent leur table : les toucher échouerait.
    FOR r IN
        SELECT t.oid::regtype AS obj, t.typtype
          FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
         WHERE n.nspname = '$ARAC_SCHEMA'
           AND t.typtype IN ('e','d','r')
           AND t.typowner <> '$R_ADMIN'::regrole
    LOOP
        IF r.typtype = 'd' THEN
            EXECUTE format('ALTER DOMAIN %s OWNER TO %I', r.obj, '$R_ADMIN');
        ELSE
            EXECUTE format('ALTER TYPE %s OWNER TO %I', r.obj, '$R_ADMIN');
        END IF;
    END LOOP;

    -- Fonctions et procédures du schéma — les déclencheurs en vivent. On
    -- écarte celles qui appartiennent à une EXTENSION : elles sont au
    -- superutilisateur et doivent y rester.
    FOR r IN
        SELECT p.oid::regprocedure AS obj,
               CASE p.prokind WHEN 'p' THEN 'PROCEDURE' ELSE 'FUNCTION' END AS genre
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = '$ARAC_SCHEMA'
           AND p.proowner <> '$R_ADMIN'::regrole
           AND NOT EXISTS (SELECT 1 FROM pg_depend d
                            WHERE d.classid = 'pg_proc'::regclass
                              AND d.objid   = p.oid
                              AND d.deptype = 'e')
    LOOP
        EXECUTE format('ALTER %s %s OWNER TO %I', r.genre, r.obj, '$R_ADMIN');
    END LOOP;
END
\$arac_pos\$;

-- 3. L'IDENTITÉ. Elle part avec le dump, et c'est tout l'intérêt.
DO \$arac_id\$
BEGIN
    IF to_regnamespace('$ARAC_SCHEMA') IS NOT NULL THEN
        EXECUTE format('COMMENT ON SCHEMA %I IS %L', '$ARAC_SCHEMA', '$marque');
    END IF;
END
\$arac_id\$;
COMMIT;
SQL
}

#: Droits sur les objets EXISTANTS + droits par défaut sur les FUTURS.
#: Appelée après la création des rôles ET après chaque migration : une table
#: créée hier ne doit pas être un trou dans le mur d'aujourd'hui.
appliquer_droits() {
    reel || { plan "réapplication des droits sur les tables du schéma $ARAC_SCHEMA"; return 0; }

    # LA PROPRIÉTÉ D'ABORD, LES DROITS ENSUITE — et jamais l'inverse.
    # Un GRANT sur les tables d'un schéma auquel on n'a pas USAGE n'ouvre rien.
    reprendre_le_schema

    # Les GRANT ciblés du rôle agent, engendrés depuis la liste ci-dessus.
    local grants_agent="" t
    for t in $_TABLES_ECRITES_PAR_AGENT; do
        grants_agent+="
DO \$g\$ BEGIN
  IF to_regclass('$ARAC_SCHEMA.$t') IS NOT NULL THEN
    EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON $ARAC_SCHEMA.$t TO $R_AGENT';
  END IF;
END \$g\$;"
    done

    psql_super -d "$ARAC_DB" -q -f - <<SQL >/dev/null
\\set ON_ERROR_STOP on
BEGIN;
-- LE SCHÉMA LUI-MÊME, AVANT SES TABLES. Ces trois lignes n'existaient qu'à
-- l'étape 3, dans le bloc qui CRÉE les rôles — donc jamais rejouées après une
-- restauration. Sans USAGE sur le schéma, les GRANT qui suivent n'ouvrent
-- rien du tout : « permission denied for schema $ARAC_SCHEMA » sur chaque
-- lecture, y compris celle d'alembic.
GRANT USAGE ON SCHEMA $ARAC_SCHEMA TO $R_APP, $R_AGENT, $R_READONLY;
GRANT ALL   ON SCHEMA $ARAC_SCHEMA TO $R_ADMIN;

GRANT SELECT, INSERT, UPDATE ON ALL TABLES    IN SCHEMA $ARAC_SCHEMA TO $R_APP;
GRANT USAGE, SELECT           ON ALL SEQUENCES IN SCHEMA $ARAC_SCHEMA TO $R_APP;
GRANT SELECT                  ON ALL TABLES    IN SCHEMA $ARAC_SCHEMA TO $R_AGENT, $R_READONLY;
GRANT USAGE, SELECT           ON ALL SEQUENCES IN SCHEMA $ARAC_SCHEMA TO $R_AGENT;
GRANT ALL                     ON ALL TABLES    IN SCHEMA $ARAC_SCHEMA TO $R_ADMIN;
GRANT ALL                     ON ALL SEQUENCES IN SCHEMA $ARAC_SCHEMA TO $R_ADMIN;

-- L'écriture de l'agent, table par table (voir _TABLES_ECRITES_PAR_AGENT).
$grants_agent

-- Les futurs objets : créés par les migrations (rôle admin) ou par le
-- superutilisateur. Sans ces deux blocs, chaque migration ouvrirait un trou.
-- Rien ici pour l'écriture de l'agent : elle est NOMMÉE, jamais par défaut.
-- Une table créée demain lui sera muette tant qu'on ne l'aura pas décidé.
ALTER DEFAULT PRIVILEGES FOR ROLE $R_ADMIN IN SCHEMA $ARAC_SCHEMA
    GRANT SELECT, INSERT, UPDATE ON TABLES TO $R_APP;
ALTER DEFAULT PRIVILEGES FOR ROLE $R_ADMIN IN SCHEMA $ARAC_SCHEMA
    GRANT USAGE, SELECT ON SEQUENCES TO $R_APP, $R_AGENT;
ALTER DEFAULT PRIVILEGES FOR ROLE $R_ADMIN IN SCHEMA $ARAC_SCHEMA
    GRANT SELECT ON TABLES TO $R_AGENT, $R_READONLY;
ALTER DEFAULT PRIVILEGES FOR ROLE $ARAC_PG_SUPERUSER IN SCHEMA $ARAC_SCHEMA
    GRANT SELECT, INSERT, UPDATE ON TABLES TO $R_APP;
ALTER DEFAULT PRIVILEGES FOR ROLE $ARAC_PG_SUPERUSER IN SCHEMA $ARAC_SCHEMA
    GRANT SELECT ON TABLES TO $R_AGENT, $R_READONLY;
COMMIT;
SQL
}

# ===========================================================================
# ÉTAPE 4 — pgvector
# ===========================================================================

etape_vecteurs() {
    etape_entete "$(rang_etape vecteurs)" "$TOTAL_ETAPES" "${TITRE_ETAPE[vecteurs]}" \
"Se souvenir, ce n'est pas retrouver un mot : c'est retrouver un SENS. Une
base de données ordinaire sait comparer des chaînes ; elle ne sait pas que
« ma boîte perd de l'argent » et « la trésorerie se dégrade » parlent de la
même chose." \
"Les extensions vector (comparaison de sens) et pg_trgm (comparaison de
formes, pour la recherche floue sur les noms propres), installées dans
la base « $ARAC_DB »." \
"Chaque souvenir sera stocké avec un vecteur de 3072 nombres qui encode ce
qu'il veut dire. Poser une question, c'est vectoriser la question et
demander à la base les souvenirs les plus proches. Sans pgvector, le
rappel se réduit à du « ctrl-F » : le cerveau retrouve ce dont vous vous
souvenez déjà."

    exiger_root "vecteurs"

    local dispo
    dispo="$(pg_lire "SELECT default_version FROM pg_available_extensions WHERE name='vector'")"
    if [[ -z "$dispo" ]]; then
        echec "pgvector n'est pas disponible sur ce serveur" \
              "PostgreSQL ne connaît pas l'extension « vector ». Le paquet n'est
pas installé, ou pas pour cette version majeure du serveur." \
              "$(remede_pgvector_pgdg)
$(geste_bootstrap "--from vecteurs")"
        exit 7
    fi

    # Présent ne suffit pas : halfvec (0.7.0) est exigé par la première
    # migration. Ubuntu 24.04 livre 0.6.0 — le paquet s'installe, puis les
    # migrations échouent. On refuse ICI, avec le remède, pas à l'étape 5.
    if ! version_au_moins "$dispo" "$ARAC_PGVECTOR_MIN"; then
        echec "pgvector $dispo est trop ancien (minimum : $ARAC_PGVECTOR_MIN)" \
              "Le schéma du cerveau utilise le type halfvec, apparu en pgvector
$ARAC_PGVECTOR_MIN. Le paquet du dépôt Ubuntu (24.04) livre 0.6.0 : il s'installe,
puis la migration échoue sur « type \"halfvec\" does not exist ».
Il faut le paquet du dépôt officiel PostgreSQL (PGDG)." \
              "$(remede_pgvector_pgdg)
$(geste_bootstrap "--from vecteurs")"
        exit 7
    fi

    # Et si l'extension existe DÉJÀ dans la base en version ancienne, mettre à
    # jour le paquet ne suffit pas : CREATE EXTENSION IF NOT EXISTS ne la touche pas.
    local deja
    deja="$(pg_lire_base "SELECT extversion FROM pg_extension WHERE extname='vector'")"
    if [[ -n "$deja" ]] && ! version_au_moins "$deja" "$ARAC_PGVECTOR_MIN"; then
        echec "l'extension vector de « $ARAC_DB » est en v$deja (minimum : $ARAC_PGVECTOR_MIN)" \
              "Le paquet disponible est assez récent (v$dispo), mais l'extension déjà
créée dans la base reste à sa version d'origine tant qu'on ne la met pas à jour.
Sans halfvec, la migration échouera sur « type \"halfvec\" does not exist »." \
              "sudo systemctl restart postgresql
sudo -u $ARAC_PG_SUPERUSER psql -p $ARAC_DB_PORT -d \"$ARAC_DB\" -c 'ALTER EXTENSION vector UPDATE;'
$(geste_bootstrap "--from vecteurs")"
        exit 7
    fi

    plan "CREATE EXTENSION IF NOT EXISTS vector   (disponible : v$dispo)"
    plan "CREATE EXTENSION IF NOT EXISTS pg_trgm"
    plan "CREATE DATABASE $GABARIT_RESTAURATION OWNER $R_ADMIN — le gabarit vide qui
       rend « ops/restore_verify.sh » exécutable sans superutilisateur"

    reel || { vide; _lecon_dimensions; return 0; }

    psql_super -d "$ARAC_DB" -c "CREATE EXTENSION IF NOT EXISTS vector"  >/dev/null
    psql_super -d "$ARAC_DB" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm" >/dev/null
    local installe
    installe="$(pg_lire_base "SELECT extversion FROM pg_extension WHERE extname='vector'")"
    bien "pgvector actif dans « $ARAC_DB » (v${installe:-?})"

    _gabarit_de_restauration

    vide
    _lecon_dimensions
    return 0
}

# ---------------------------------------------------------------------------
# LE GABARIT DE RESTAURATION — posé ici parce que c'est ici qu'on a le pouvoir
# ---------------------------------------------------------------------------
#
# « ops/restore_verify.sh » est le seul contrôle qui distingue « un dump
# existe » de « ce dump contient le cerveau ». Il restaure dans une base
# JETABLE. Pour cela, il lui faut deux choses, et il n'en avait aucune :
#
#   1. un rôle capable de créer une base  → l'étape 3 vient de donner CREATEDB
#      à $R_ADMIN, et la base vivante ne lui appartient pas ;
#   2. les extensions du schéma — halfvec(3072) vient de pgvector, qui n'est
#      PAS une extension « trusted » : CREATE EXTENSION vector exige le
#      superutilisateur, toujours.
#
# Le point 2 est la raison pour laquelle ce geste vit ICI et nulle part
# ailleurs : le bootstrap est le seul moment où le superutilisateur PostgreSQL
# est légitimement à la manœuvre. On fabrique donc UNE FOIS une base vide
# contenant les deux extensions ; toute vérification ultérieure la COPIE.
#
# La documentation prescrivait à sa place un geste manuel
# (`ops/restore_verify.sh --prepare-template`, puis un bloc SQL à passer en
# superutilisateur). Ce geste existe toujours — il répare les installations
# posées AVANT cette version — mais il ne devrait plus jamais être nécessaire :
# une promesse que le produit ne tient pas tout seul finit par n'être tenue
# par personne. Le §11 d'INSTALLATION donne la restauration vérifiée comme un
# CONTRÔLE ; un contrôle qui réclame un geste préalable non posé n'est pas un
# contrôle, c'est une intention.
#
# LE GABARIT APPARTIENT AU RÔLE, IL N'EST PAS « datistemplate ».
#
# Deux façons de laisser un rôle copier une base sans être superutilisateur :
# la marquer `datistemplate`, ou la lui faire POSSÉDER. On a choisi la
# seconde, pour deux raisons mesurables :
#   · `datistemplate = true` autorise TOUT rôle du serveur ayant CREATEDB à
#     la copier — y compris le rôle d'administration du cerveau VOISIN. La
#     propriété, elle, ne s'étend à personne d'autre ;
#   · une base marquée `datistemplate` REFUSE d'être détruite (« cannot drop a
#     template database ») tant qu'on ne l'a pas démarquée. La désinstallation
#     du §13 aurait laissé derrière elle une base indestructible au premier
#     essai, sur une machine où l'on vient de tout retirer.
#
# LE NOM DU GABARIT NE SE COLLE PLUS DANS LE TEXTE SQL — il se LIE.
#
# Ce nom vient de `GABARIT_RESTAURATION`, donc de `ARAC_RESTORE_TEMPLATE_DB`,
# donc de l'environnement — et il finissait interpolé nu dans quatre
# instructions passées à `psql_super`, c'est-à-dire à `sudo -u postgres psql`.
# Personne ne relit ce texte-là : contrairement au bloc de
# `ops/restore_verify.sh --prepare-template`, il n'est pas imprimé, il est
# exécuté. Une apostrophe suffisait à faire exécuter une seconde instruction
# par le SUPERUTILISATEUR, sur n'importe quelle base de la grappe — le voisin
# compris.
#
# Deux protections, indépendantes exprès, comme partout ailleurs ici :
#   1. `_valider_nom_base` refuse l'installation en amont (config.sh) ;
#   2. ici, la valeur passe par une VARIABLE psql (`-v tpl=…`) et n'entre dans
#      le SQL que par `:'tpl'`, que psql cite lui-même, puis par `format()` qui
#      la recite en IDENTIFIANT (%I) ou en CHAÎNE (%L). Aucun contenu ne peut
#      quitter ces guillemets-là.
_gabarit_de_restauration() {
    local tpl="$GABARIT_RESTAURATION" existe proprio
    existe="$(psql_super -d postgres -tAc \
        "SELECT count(*) FROM pg_database WHERE datname = :'tpl'" \
        -v tpl="$tpl" 2>/dev/null || true)"
    if [[ "${existe:-0}" != 1 ]]; then
        if ! psql_super -d postgres -v tpl="$tpl" -v admin="$R_ADMIN" -f - >/dev/null <<'SQL'
SELECT format('CREATE DATABASE %I OWNER %I ENCODING ''UTF8''', :'tpl', :'admin')\gexec
SQL
        then
            alerte "Le gabarit de restauration « $tpl » n'a pas pu être créé."
            note "  Conséquence exacte : « ops/restore_verify.sh » réclamera le
   superutilisateur pour créer pgvector dans sa base jetable, et la réserve
   « aucune restauration n'a jamais été vérifiée » d'ops/install_check.sh
   restera. Le cerveau, lui, fonctionne : ce n'est pas une panne d'installation.
   Le geste, quand vous voudrez le poser :
       ops/restore_verify.sh --prepare-template"
            return 0
        fi
    fi
    # Idempotent, et RÉPARATEUR : un gabarit hérité d'une version précédente
    # (créé par --prepare-template, donc marqué `datistemplate` et possédé par
    # le superutilisateur) est remis dans la forme ci-dessus, sans être détruit.
    psql_super -d postgres -v tpl="$tpl" -v admin="$R_ADMIN" -f - >/dev/null 2>&1 <<'SQL' || true
SELECT format('UPDATE pg_database SET datistemplate = false WHERE datname = %L', :'tpl')\gexec
SELECT format('ALTER DATABASE %I OWNER TO %I', :'tpl', :'admin')\gexec
SQL
    psql_super -d "$tpl" -c "CREATE EXTENSION IF NOT EXISTS vector"  >/dev/null 2>&1 || true
    psql_super -d "$tpl" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm" >/dev/null 2>&1 || true

    # LE GABARIT SE FERME COMME LA BASE VIVANTE — le raisonnement ci-dessus
    # s'arrêtait une ligne trop tôt.
    #
    # On a refusé `datistemplate` pour que le voisin ne puisse pas COPIER cette
    # base. Elle restait pourtant CONNECTABLE par lui : PostgreSQL donne
    # CONNECT à PUBLIC sur toute base neuve, et la base vivante, quinze lignes
    # plus haut, reçoit son `REVOKE CONNECT … FROM PUBLIC` pour exactement
    # cette raison. Mesuré sur un banc à deux cerveaux : le rôle applicatif du
    # voisin se connectait au gabarit avec son propre mot de passe.
    #
    # Le gabarit est VIDE, donc rien de la mémoire n'y fuit — mais il n'est pas
    # une fenêtre, il est permanent, et la base jetable qui en est copiée
    # contient, elle, tout le cerveau. Fermer les deux est le même geste, et
    # `ops/restore_verify.sh` pose le second.
    psql_super -d postgres -v tpl="$tpl" -v admin="$R_ADMIN" -f - >/dev/null 2>&1 <<'SQL' || true
SELECT format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', :'tpl')\gexec
SELECT format('GRANT  CONNECT ON DATABASE %I TO %I', :'tpl', :'admin')\gexec
SQL

    proprio="$(psql_super -d postgres -tAc \
        "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = :'tpl'" \
        -v tpl="$tpl" 2>/dev/null || true)"
    bien "Gabarit de restauration « $tpl » prêt (propriétaire : ${proprio:-?})."
    note "  Base VIDE : deux extensions, zéro donnée. Elle sert à
   « ops/restore_verify.sh », qui la copie pour y restaurer un dump, la lit,
   puis détruit la copie. Sans elle, prouver une sauvegarde réclamerait le
   superutilisateur toutes les semaines.
   ELLE SURVIT À LA DÉSINSTALLATION SI PERSONNE NE LA NOMME, et elle bloque
   alors la suite : elle APPARTIENT à $R_ADMIN, et PostgreSQL refuse de
   détruire un rôle qui possède encore une base (« cannot be dropped because
   some objects depend on it / owner of database $tpl »). Un rôle de
   connexion, portant CREATEDB, survivrait à son cerveau sur une grappe que
   vous partagez peut-être — avec un mot de passe effacé avec le coffre, donc
   plus modifiable par personne. Elle se détruit comme n'importe quelle base :
       sudo -u $ARAC_PG_SUPERUSER dropdb -p $ARAC_DB_PORT $tpl
   Pour savoir ce qui reste après coup, et POURQUOI :
       ops/uninstall_check.sh"
}

_lecon_dimensions() {
    lecon "3072 dimensions, et pourquoi ce chiffre vous concerne" \
"Le modèle d'embeddings retenu (OpenAI text-embedding-3-large) produit des
vecteurs de 3072 nombres. Or l'index HNSW de pgvector — celui qui rend la
recherche rapide — plafonne à 2000 dimensions pour le type « vector ».
C'est pourquoi le schéma utilise « halfvec(3072) » : demi-précision, deux
fois moins de place, indexable. La perte de précision est indétectable au
rappel ; l'absence d'index, elle, se voit tout de suite.

Si vous changez de modèle d'embeddings un jour, vous changez la dimension,
donc la colonne, donc l'index : c'est une migration, pas un réglage."
}

# ===========================================================================
# ÉTAPE 5 — les migrations
# ===========================================================================

moteur_present() {
    [[ -f "$ARAC_HOME/alembic.ini" && -d "$ARAC_HOME/db/alembic/versions" ]]
}

#: UN ENVIRONNEMENT PYTHON DÉPLACÉ EST MORT — ET IL A L'AIR VIVANT.
#:
#: Le garde était `[[ ! -x "$ARAC_VENV/bin/python" ]]`. Or `bin/python` est un
#: LIEN vers `python3`, lui-même vers /usr/bin/python3 : il reste exécutable
#: après n'importe quel déplacement du dépôt. Le garde concluait donc « venv
#: sain », ne reconstruisait rien, et l'étape repartait sur des exécutables
#: morts.
#:
#: Ce qui meurt au déplacement, ce n'est pas l'interpréteur : ce sont les
#: SCRIPTS de `bin/` — pip, alembic, uvicorn — dont la première ligne porte le
#: chemin ABSOLU de l'ancien emplacement. Chacun rend alors :
#:     …/pip: cannot execute: required file not found        (code 127)
#: On éprouve donc ce dont cette étape a réellement besoin : qu'un SCRIPT du
#: venv s'exécute. Ce n'est pas un détail de forme — c'est ce qui rendait
#: inopérant le remède « déplacez le dépôt » proposé par l'étape 9.
venv_utilisable() {
    [[ -x "$ARAC_VENV/bin/python" ]] || return 1
    if [[ -e "$ARAC_VENV/bin/pip" ]]; then
        "$ARAC_VENV/bin/pip" --version >/dev/null 2>&1 || return 1
    fi
    "$ARAC_VENV/bin/python" -c 'import sys' >/dev/null 2>&1 || return 1
    return 0
}

etape_migrations() {
    local n=0
    [[ -d "$ARAC_HOME/db/alembic/versions" ]] && \
        n="$(find "$ARAC_HOME/db/alembic/versions" -maxdepth 1 -name '*.py' -type f 2>/dev/null | wc -l)"

    etape_entete "$(rang_etape migrations)" "$TOTAL_ETAPES" "${TITRE_ETAPE[migrations]}" \
"Le schéma d'un cerveau n'est pas un détail technique : c'est la forme que
prend sa pensée. Les migrations le construisent pas à pas, dans un ordre
qu'on peut rejouer, et dont on garde la trace." \
"Les tables du schéma « $ARAC_SCHEMA » : les souvenirs et leurs vecteurs, les
conversations brutes et leur provenance, les domaines, les liens entre
atomes, les preuves d'audit, la file de propositions, le journal des
cycles. ($n migration(s) trouvée(s).)" \
"C'est ici que se décide ce dont le cerveau pourra se souvenir. Notamment
le format de « source_ref », le lien entre un souvenir et la conversation
qui l'a produit — voir la leçon ci-dessous."

    lecon "76 % de la provenance perdue" \
"Sur le cerveau de référence, un changement de format du champ source_ref
a coupé le lien entre les souvenirs et les conversations dont ils venaient.
Trois quarts du savoir ne savent plus d'où ils viennent : ils sont encore
là, mais plus vérifiables. Un souvenir sans provenance n'est pas un
souvenir, c'est une rumeur.

La leçon tient en une phrase : FIGEZ LE FORMAT DE LA PROVENANCE TÔT, et
ne le changez qu'avec une migration qui convertit l'existant."
    vide

    if ! moteur_present; then
        alerte "$(_c 1 'Le moteur n'\''est pas encore présent dans ce dépôt.')"
        vide
        note "Il manque alembic.ini et/ou db/alembic/versions/.
Ce dépôt contient pour l'instant l'entretien, le générateur de taxonomie et
ce bootstrap ; l'extraction du moteur (API, agents, cockpit, migrations)
est en cours et n'est pas encore publiée.

Les étapes 5, 6, 9 et 10 supposent ces fichiers. Le reste — prérequis,
base, rôles, vecteurs, secrets, clés — a déjà été fait et reste valide :
relancez ce bootstrap quand le moteur sera là, il reprendra ici."
        vide
        dire "$(_c 1 'État réel du framework : voir GOAL.md, tableau « ÉTAT ».')"
        vide
        return 8
    fi

    plan "création/vérification de l'environnement Python : $ARAC_VENV"
    plan "pip install -r requirements.txt          (accès réseau requis)"
    plan "reprise de la propriété du schéma $ARAC_SCHEMA et des droits (AVANT alembic)"
    plan "alembic upgrade head                     ($n migration(s))"
    plan "réapplication des droits sur les tables créées"

    reel || return 0

    exiger_root "migrations"

    # --- L'environnement Python -------------------------------------------
    if ! venv_utilisable; then
        if [[ -e "$ARAC_VENV/bin/python" ]]; then
            alerte "$(_c 1 "L'environnement Python présent est INUTILISABLE.")"
            note "  $ARAC_VENV existe, son interpréteur répond, et pourtant ses scripts
   ne s'exécutent pas. La cause est presque toujours la même : le dépôt a
   été DÉPLACÉ. Les scripts de bin/ (pip, alembic, uvicorn) portent le
   chemin absolu de l'ancien emplacement dans leur première ligne, et
   rendent « required file not found ». Un venv ne se déplace pas : il se
   refait — c'est ce que fait la ligne suivante, avec --clear."
        fi
        if ! confirmer "Créer l'environnement Python et installer les dépendances (réseau) ?" oui; then
            echec "dépendances Python absentes" \
                  "Sans elles, ni Alembic ni l'API ne peuvent démarrer." \
                  "python3 -m venv --clear $ARAC_VENV
$ARAC_VENV/bin/pip install -r $ARAC_HOME/requirements.txt
$(geste_bootstrap "--from migrations")"
            exit 7
        fi
        # `--clear` et non une simple création : sur un venv PRÉSENT mais mort,
        # `python3 -m venv <dir>` ne réécrit pas les scripts de bin/. Sans lui,
        # la reconstruction serait un geste vide, et la panne reviendrait
        # identique une étape plus loin.
        python3 -m venv --clear "$ARAC_VENV"
        "$ARAC_VENV/bin/pip" install --quiet --upgrade pip
        bien "Environnement Python créé : $ARAC_VENV"
    fi
    if [[ -f "$ARAC_HOME/requirements.txt" ]]; then
        "$ARAC_VENV/bin/pip" install --quiet -r "$ARAC_HOME/requirements.txt" || {
            echec "installation des dépendances Python" \
                  "pip a échoué. Le plus souvent : pas d'accès réseau, ou un paquet
système manquant pour compiler (python3-dev, build-essential)." \
                  "sudo apt install python3-dev build-essential
$ARAC_VENV/bin/pip install -r $ARAC_HOME/requirements.txt
$(geste_bootstrap "--from migrations")"
            exit 7
        }
        bien "Dépendances Python installées."
    fi

    # --- Alembic -----------------------------------------------------------
    local dsn; dsn="$(lire_var "$ARAC_ENV_FILE" ARAC_DB_URL_ADMIN || true)"
    if [[ -z "$dsn" ]]; then
        echec "DSN d'administration introuvable" \
              "ARAC_DB_URL_ADMIN est absent de $ARAC_ENV_FILE. L'étape 3 n'a pas
abouti." \
              "$(geste_bootstrap "--from base")"
        exit 7
    fi
    # LES DROITS AVANT ALEMBIC, ET C'EST LA CORRECTION DE LA BASCULE.
    #
    # `alembic` se connecte sous $R_ADMIN et lit `alembic_version` à sa
    # première ligne. Sur une base qui sort de `pg_restore --no-owner`, ce rôle
    # n'a ni la propriété du schéma ni le droit d'y entrer : l'étape mourait en
    # code 7, et le remède qu'elle imprimait rejouait exactement la même chose.
    # `reprendre_le_schema` (dans `appliquer_droits`) rend la base lisible à
    # ses propres rôles AVANT qu'on lui demande de la lire. Sur une
    # installation saine, ces deux appels ne changent rien : ils sont
    # idempotents, et c'est ce qui permet de les faire deux fois.
    appliquer_droits
    bien "Propriété et droits repris sur « $ARAC_SCHEMA » — alembic peut lire la base."

    local avant apres
    avant="$(pg_lire_base "SELECT version_num FROM $ARAC_SCHEMA.alembic_version LIMIT 1")"
    [[ -n "$avant" ]] && note "  Révision actuelle : $avant"

    if ! ( cd "$ARAC_HOME" && DATABASE_URL="$dsn" "$ARAC_VENV/bin/alembic" upgrade head ); then
        echec "application des migrations" \
              "Alembic s'est arrêté. Le message exact est au-dessus ; c'est
presque toujours une extension manquante ou un rôle sans droit." \
              "cd $ARAC_HOME
sudo DATABASE_URL=\"\$(sudo grep ^ARAC_DB_URL_ADMIN= $ARAC_ENV_FILE | cut -d= -f2-)\" \\
     $ARAC_VENV/bin/alembic upgrade head
puis : $(geste_bootstrap "--from migrations")"
        exit 7
    fi
    unset dsn
    apres="$(pg_lire_base "SELECT version_num FROM $ARAC_SCHEMA.alembic_version LIMIT 1")"
    local tables
    tables="$(pg_lire_base "SELECT count(*) FROM information_schema.tables WHERE table_schema='$ARAC_SCHEMA'")"
    bien "Migrations appliquées — révision « ${apres:-?} », ${tables:-0} tables."

    appliquer_droits
    bien "Droits réappliqués sur les tables nouvellement créées."
    return 0
}

# ===========================================================================
# ÉTAPE 6 — la taxonomie
# ===========================================================================

etape_scopes() {
    etape_entete "$(rang_etape scopes)" "$TOTAL_ETAPES" "${TITRE_ETAPE[scopes]}" \
"Votre découpage de la vie n'a de valeur que s'il est OPPOSABLE : l'API doit
refuser un domaine inconnu, la base doit refuser une clé étrangère
manquante. Sinon la mémoire se fragmente en catégories jumelles et le
rappel se dilue." \
"Depuis config/scopes.toml : l'énumération Python (app/schemas/scope_generated.py),
le seed SQL (db/seeds/scopes.sql), puis le peuplement de la table
$ARAC_SCHEMA.scopes." \
"Chaque souvenir devra désormais nommer un domaine qui existe. Un domaine
inventé sera refusé à l'entrée — 422 côté API, violation de contrainte
côté base — plutôt que de créer silencieusement un dixième rangement pour
la même chose."

    lecon "près d'un souvenir actif sur onze, posé sur une racine" \
"Les souvenirs vivent sur les FEUILLES. Une racine (« travail ») est un
conteneur ; une feuille (« travail/strategie ») est un rangement. Un
souvenir posé sur une racine existe en base et n'apparaît JAMAIS dans un
rappel : il est invisible.

C'est le piège numéro un, et il ne fait aucun bruit. Le contrôle final
(étape 10) compte ces souvenirs orphelins et vous les montre."
    vide

    if ! reel && ! base_existe; then
        plan "python3 bootstrap/generate_scopes.py --config config/scopes.toml"
        plan "psql -f db/seeds/scopes.sql   (INSERT ... ON CONFLICT, ne supprime rien)"
        vide
        note "En simulation, la base n'existe pas encore : le contenu exact du
seed ne peut pas être montré. Il sera engendré depuis config/scopes.toml,
et vous pourrez le lire avant qu'il ne soit appliqué :
  python3 bootstrap/generate_scopes.py --config config/scopes.toml
  cat db/seeds/scopes.sql"
        return 0
    fi

    if ! table_existe scopes; then
        alerte "La table $ARAC_SCHEMA.scopes n'existe pas encore."
        note "  Elle est créée par les migrations. Cette étape a besoin d'elles.
  Reprenez à l'étape 5 : $(geste_bootstrap "--from migrations")"
        return 8
    fi

    # --- Sûreté : ne jamais orpheliner du savoir vivant -------------------
    _controle_scopes_habites || return 8

    plan "python3 bootstrap/generate_scopes.py --config config/scopes.toml"
    plan "psql -f db/seeds/scopes.sql   (INSERT ... ON CONFLICT, ne supprime rien)"

    reel || return 0

    if ! ( cd "$ARAC_HOME" && python3 bootstrap/generate_scopes.py --config config/scopes.toml ); then
        echec "génération de la taxonomie" \
              "Le générateur a refusé config/scopes.toml. Son message dit quoi
corriger et où." \
              "\$EDITOR $ARAC_HOME/config/scopes.toml
$(geste_bootstrap "--scopes-only")"
        exit 7
    fi
    # LE FICHIER EST LU PAR ROOT, PAS PAR POSTGRES.
    #
    # `-f <chemin>` fait ouvrir le fichier par le processus psql, qui tourne
    # sous « postgres » : il lui faut donc le droit de traverser TOUT le chemin
    # du dépôt. Sur une racine que seul son propriétaire peut traverser (un
    # dépôt sous /root, un /home en 0700 — le cas d'un utilisateur qui essaie
    # avant de déployer), l'installation meurt à l'étape 6 sur :
    #     psql: error: …/db/seeds/scopes.sql: Permission denied
    # …après avoir créé la base, les rôles et trente-quatre tables. Le message
    # ne désigne ni la cause ni le remède, et le geste proposé (« reprenez aux
    # migrations ») ne peut pas aider.
    #
    # On lit donc le fichier ICI, où l'on est root, et on le donne à psql par
    # l'entrée standard. Le contenu est le même ; les droits requis ne le sont
    # pas.
    if ! psql_super -d "$ARAC_DB" -q -f - < "$ARAC_HOME/db/seeds/scopes.sql" >/dev/null; then
        echec "peuplement de la table des domaines" \
              "Le seed SQL a été refusé. Le plus souvent : la table $ARAC_SCHEMA.scopes
n'a pas la forme attendue (migrations incomplètes)." \
              "$(geste_bootstrap "--from migrations")"
        exit 7
    fi
    local n racines feuilles
    n="$(pg_lire_base "SELECT count(*) FROM $ARAC_SCHEMA.scopes")"
    racines="$(pg_lire_base "SELECT count(*) FROM $ARAC_SCHEMA.scopes WHERE depth=0")"
    feuilles="$(pg_lire_base "SELECT count(*) FROM $ARAC_SCHEMA.scopes WHERE depth>0")"
    bien "Taxonomie semée : ${n:-0} domaines (${racines:-0} racines, ${feuilles:-0} feuilles)."
    note "  Le seed ne SUPPRIME jamais : un domaine retiré de la configuration
   reste en base tant que vous n'avez pas décidé du sort de ce qu'il porte."
    return 0
}

#: Compare les domaines habités en base à ceux déclarés dans la configuration.
#: Aucune commande ne reçoit de mot de passe : on passe par le
#: superutilisateur local, en lecture.
#:
#: POURQUOI `|| true` EST APRÈS LA PARENTHÈSE FERMANTE, ET NON SUR LA LIGNE
#: D'OUVERTURE DU DOCUMENT EN LIGNE.
#: Bash délimite d'abord le `$( … )` en cherchant la parenthèse fermante, PUIS
#: analyse le texte extrait comme un script. Ce second passage relit la ligne
#: d'ouverture du here-document, consomme le corps jusqu'à `PY`, et retrouve
#: derrière lui le `|| true` qu'on croyait déjà placé — désormais orphelin,
#: collé au `)`. D'où, à l'EXÉCUTION seulement :
#:     command substitution: syntax error near unexpected token `||'
#: `bash -n` et `shellcheck` ne le voient pas : ni l'un ni l'autre ne relit le
#: corps d'une substitution, c'est bash lui-même qui le fait, au moment de
#: l'évaluer. L'étape 6 mourait donc en EXIT=2, sans message et sans bilan.
#: Règle qui en découle : sur la ligne qui ouvre un `<<'EOF'` dans un `$( … )`,
#: rien après le délimiteur — redirections avant, opérateurs après le `)`.
_controle_scopes_habites() {
    table_existe memory_atoms || return 0
    local declares liste
    declares="$(cd "$ARAC_HOME" && python3 - config/scopes.toml 2>/dev/null <<'PY'
import pathlib, sys, tomllib
d = tomllib.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
for r in d.get("root", []):
    print(r["key"])
for f in d.get("leaf", []):
    print(f"{f['root']}/{f['key']}")
PY
)" || true
    [[ -z "$declares" ]] && return 0
    liste="$(printf '%s\n' "$declares" | sed "s/'/''/g; s/^/'/; s/$/'/" | paste -sd, -)"
    local orphelins
    orphelins="$(pg_lire_base "SELECT scope || '  ' || count(*) FROM $ARAC_SCHEMA.memory_atoms
        WHERE status='active' AND scope NOT IN ($liste) GROUP BY scope ORDER BY 1")"
    [[ -z "$orphelins" ]] && return 0

    vide
    mal "$(_c 1 'Retrait refusé — du savoir vivant deviendrait orphelin.')"
    vide
    dire "Ces domaines portent des souvenirs actifs mais ne sont plus déclarés"
    dire "dans config/scopes.toml :"
    vide
    printf '%s\n' "$orphelins" | while IFS= read -r l; do dire "   $l souvenir(s)"; done
    vide
    note "Deux issues, toutes deux explicites :
  · remettez ces domaines dans config/scopes.toml ;
  · ou déplacez d'abord leurs souvenirs, puis relancez.
Ce bootstrap ne tranchera pas à votre place."
    vide
    return 1
}
