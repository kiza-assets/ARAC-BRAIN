# shellcheck shell=bash
# ---------------------------------------------------------------------------
# config.sh — étape 2 : lire la description, en déduire tous les chemins.
#
# L'entretien a écrit deux fichiers. Ce sont les SEULES sources de vérité de
# l'identité du cerveau : son propriétaire, son nom, le poste d'où viennent
# ses conversations, et la forme de sa mémoire.
#
# Tout le reste — nom de la base, rôles, chemins, unités systemd — en est
# DÉDUIT. C'est ce qui garantit qu'aucune valeur héritée d'un autre cerveau
# ne subsiste : changez brain.toml, tout suit.
# ---------------------------------------------------------------------------

etape_config() {
    etape_entete "$(rang_etape config)" "$TOTAL_ETAPES" "${TITRE_ETAPE[config]}" \
"Le cerveau qu'on s'apprête à créer doit être le VÔTRE. Son nom, son
propriétaire et sa taxonomie viennent de vos réponses à l'entretien, pas
d'un gabarit." \
"Rien sur disque. Cette étape calcule, à partir de vos deux fichiers de
configuration, l'ensemble des noms et chemins que les étapes suivantes
utiliseront." \
"Un nom de base, quatre noms de rôles, un dossier de secrets, quatre
unités systemd : tous portent l'identité de votre cerveau. Deux cerveaux
sur la même machine ne se marchent pas dessus."

    local brain="$ARAC_HOME/config/brain.toml"
    local scopes="$ARAC_HOME/config/scopes.toml"

    if [[ ! -r "$brain" || ! -r "$scopes" ]]; then
        vide
        mal "$(_c 1 "Votre cerveau n'a pas encore été décrit.")"
        vide
        note "Il manque :"
        [[ -r "$brain"  ]] || note "  · config/brain.toml   — qui vous êtes, comment s'appelle ce cerveau"
        [[ -r "$scopes" ]] || note "  · config/scopes.toml  — la forme de votre mémoire"
        vide
        dire "Ces fichiers ne se rédigent pas à la main. Ils naissent d'un entretien"
        dire "de cinq minutes qui vous fait décider — en connaissance de cause — de"
        dire "la façon dont votre cerveau rangera ce qu'il apprend."
        vide
        dire "$(_c 1 'Commencez par là :')"
        cmd "python3 bootstrap/wizard.py"
        vide
        note "L'entretien n'installe rien. Il écrit deux fichiers, vous les montre
avant de les écrire, et vous rend la main. Revenez ici ensuite."
        exit 6
    fi

    # --- Identité ---------------------------------------------------------
    local sortie
    if ! sortie="$(python3 -c "$_PY_LIRE_BRAIN" "$brain" 2>&1)"; then
        echec "config/brain.toml illisible" \
              "$sortie" \
              "Rejouez l'entretien, qui réécrira un fichier valide :
  python3 bootstrap/wizard.py"
        exit 6
    fi
    eval "$sortie"

    if [[ -z "$BRAIN_NOM" || -z "$BRAIN_OWNER" || -z "$BRAIN_NODE" ]]; then
        echec "config/brain.toml incomplet" \
              "Il faut brain.owner, brain.name et source.node_id. L'un au moins manque." \
              "python3 bootstrap/wizard.py"
        exit 6
    fi

    # --- Chemins déduits ---------------------------------------------------
    ARAC_DB="${ARAC_DB:-$(printf '%s' "$BRAIN_NOM" | tr -c 'a-zA-Z0-9' '_' | sed 's/_*$//')}"
    ARAC_DB="${ARAC_DB,,}"
    ARAC_NODE_ID="${ARAC_NODE_ID:-$BRAIN_NODE}"
    ARAC_SCHEMA="${ARAC_SCHEMA:-arac}"

    # --- L'EMPREINTE — ce qui distingue une INSTALLATION d'un NOM ----------
    #
    # Tout ce qui suit est dérivé de `brain.name` : la base, les cinq rôles,
    # les unités, le coffre. C'était présenté comme la garantie que « deux
    # cerveaux ne se marchent pas dessus ». C'était faux, et d'une façon que
    # l'entretien lui-même rendait fréquente : il propose « <prénom>-brain »
    # et note que « beaucoup gardent arac ». Deux personnes qui appellent leur
    # cerveau « perso » ou « test » dérivent EXACTEMENT les mêmes noms. La
    # seconde n'était alors pas refusée — elle était reçue comme une
    # réinstallation de la première, dont elle rouvrait le coffre.
    #
    # Un nom ne peut pas authentifier : il est choisi, et les mêmes noms sont
    # choisis par tout le monde. L'empreinte, elle, n'est choisie par
    # personne — l'entretien l'engendre une fois, dans le dépôt de son auteur.
    #
    # CE QUE CETTE EMPREINTE PROUVE, ET CE QU'ELLE NE PROUVE PAS.
    # Elle prouve que l'installation en cours vient du MÊME dépôt décrit que
    # celle qui a posé les rôles. Elle ne prouve rien contre quelqu'un qui,
    # étant root, irait lire l'empreinte dans /etc/arac/<base>/arac.env pour
    # la recopier : root peut de toute façon tout faire sur cette machine, et
    # aucune plaque ne l'en empêchera. Ce qu'elle change est ailleurs, et
    # c'est ce qui compte ici : la reprise du cerveau d'un autre cesse d'être
    # un accident silencieux pour devenir un geste délibéré et nommé.
    ARAC_INSTALL_UUID="${ARAC_INSTALL_UUID:-${BRAIN_UUID:-}}"
    EMPREINTE_DERIVEE=0
    if [[ -z "$ARAC_INSTALL_UUID" ]]; then
        # brain.toml d'avant ce marquage, ou rédigé à la main. On ne refuse
        # pas pour autant : on dérive une empreinte des trois réponses de
        # l'entretien, qui n'est pas aléatoire mais reste PROPRE à la personne
        # — deux inconnus partagent un nom de cerveau bien plus volontiers
        # qu'un prénom, un nom et un identifiant de poste à la fois.
        ARAC_INSTALL_UUID="d-$(printf '%s\n%s\n%s\n' "$BRAIN_OWNER" "$BRAIN_NOM" "$ARAC_NODE_ID" \
                               | sha256sum | cut -c1-24)"
        EMPREINTE_DERIVEE=1
    fi
    if [[ ! "$ARAC_INSTALL_UUID" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{7,63}$ ]]; then
        echec "empreinte d'installation invalide" \
              "brain.uuid = « $ARAC_INSTALL_UUID » — attendu 8 à 64 caractères
parmi lettres, chiffres, tiret, souligné et point." \
              "Retirez la ligne « uuid = » de config/brain.toml et relancez
l'entretien, qui en écrira une valide :
  python3 bootstrap/wizard.py"
        exit 6
    fi

    # --- LES RÔLES PORTENT LE NOM DU CERVEAU ------------------------------
    #
    # Un rôle PostgreSQL est global au CLUSTER, pas propre à une base. Tant que
    # les cinq rôles s'appelaient `arac_app`, `arac_agent`, `arac_readonly`,
    # `arac_admin` et `arac_backup`, deux cerveaux posés sur le même serveur
    # n'avaient PAS deux jeux de rôles : ils avaient le même, et le second
    # bootstrap réencodait les mots de passe du premier.
    #
    # La convention retenue :  arac_<base>_<fonction>
    #
    #   « arac_ »      dit le produit. Un administrateur qui lit `\du` voit
    #                  d'un coup d'œil ce qui appartient à ce framework.
    #   « <base> »     dit LE CERVEAU. C'est déjà l'identifiant unique du
    #                  cerveau — il vient de brain.name, il nomme la base, le
    #                  dossier de secrets, les unités. Un sixième nom aurait
    #                  été un sixième endroit où se tromper.
    #   « <fonction> » dit le privilège, comme avant.
    #
    # Elle se défend sur trois points. D'abord la LISIBILITÉ du diagnostic :
    # devant `arac_nadia_brain_app`, on sait immédiatement quel cerveau perd
    # l'accès. Devant `arac_app`, on ne savait rien. Ensuite la RÉCIPROCITÉ :
    # les migrations déduisent les quatre autres rôles du rôle d'administration
    # sous lequel elles tournent (db/alembic/roles.py) — le nommage est donc
    # vérifiable des deux côtés, sans configuration à tenir en double. Enfin la
    # COMPATIBILITÉ : un cerveau déjà posé, dont le rôle d'administration
    # s'appelle `arac_admin`, garde ses cinq noms — la déduction rend `arac`.
    # LE NOM DE LA BASE EST JUGÉ POUR LUI-MÊME, ET PLUS PAR RICOCHET.
    #
    # Il ne l'était que par la validation du préfixe de rôles, deux lignes plus
    # bas : `arac_${ARAC_DB}` hérite des caractères de `ARAC_DB`, donc un nom de
    # base hostile faisait échouer le préfixe. Cette protection tombait dès que
    # `ARAC_ROLE_PREFIX` était posé, lui aussi, dans l'environnement — et alors
    # `ARAC_DB` atteignait `CREATE DATABASE "…"` sans avoir été regardé une
    # seule fois. Deux variables qui se protègent l'une l'autre ne protègent
    # rien : il suffit de poser les deux.
    _valider_nom_base "$ARAC_DB" ARAC_DB \
        "Il vient de brain.name (config/brain.toml), ou de ARAC_DB si vous
l'avez posée. C'est lui qui nomme la base, les rôles, le coffre et les
unités : le corriger ici corrige tout le reste." || exit 6

    ARAC_ROLE_PREFIX="${ARAC_ROLE_PREFIX:-arac_${ARAC_DB}}"
    _valider_prefixe_role "$ARAC_ROLE_PREFIX" || exit 6

    # Le préfixe des unités systemd. Il porte le nom du cerveau pour la même
    # raison que les rôles : `systemctl enable` d'un second cerveau écraserait
    # sinon l'unité du premier, et un seul des deux tournerait — le dernier
    # installé. Défini ICI, avant la résolution des ports, parce que celle-ci
    # doit pouvoir reconnaître NOS propres unités : un port que notre API tient
    # déjà n'est pas un conflit, c'est une réinstallation.
    PREFIXE_UNITE="arac-${ARAC_DB}"
    U_API="${PREFIXE_UNITE}-api"
    U_COCKPIT="${PREFIXE_UNITE}-cockpit"
    U_CYCLE="${PREFIXE_UNITE}-cycle"
    U_BACKUP="${PREFIXE_UNITE}-sauvegarde"
    # La RESTAURATION VÉRIFIÉE a son unité comme la sauvegarde a la sienne :
    # « une sauvegarde qui n'a jamais été restaurée n'est pas une sauvegarde »
    # est la première phrase de docs/SAUVEGARDE.md, et elle ne peut pas être
    # vraie tant que personne ne restaure. `ops/install_check.sh` portait donc
    # en permanence « aucune restauration n'a jamais été vérifiée — vos dumps
    # sont une hypothèse », et rien dans le produit ne pouvait lever cette
    # réserve : le mot « minuteur » n'apparaissait dans aucune unité posée.
    U_RESTORE="${PREFIXE_UNITE}-restauration"

    ARAC_ETC="${ARAC_ETC:-/etc/arac/$ARAC_DB}"
    ARAC_ENV_FILE="${ARAC_ENV_FILE:-$ARAC_ETC/arac.env}"

    # --- LE CLUSTER OÙ CE CERVEAU VIT DÉJÀ L'EMPORTE ----------------------
    #
    # CONSTATÉ, ET C'EST LE PIRE DÉFAUT DE CE FICHIER.
    #
    # `ARAC_DB_PORT` avait pour seule règle `${ARAC_DB_PORT:-5432}` : la
    # variable de l'appelant, sinon le cluster par défaut de la machine. Rien
    # ne relisait la valeur que l'installation avait RETENUE — alors que les
    # ports de service, eux, sont relus depuis ce fichier précisément pour
    # cela (voir _resoudre_ports, « un cerveau ne change pas de port parce
    # qu'on a relancé son bootstrap »).
    #
    # Conséquence mesurée sur cette machine : un cerveau installé sur un
    # cluster dédié (port 5471), puis relancé par le geste que la
    # documentation donne elle-même —
    #
    #     sudo ./bootstrap/bootstrap.sh --from services
    #
    # — sans repasser la variable. Le bootstrap est reparti sur 5432. Il y a
    # CRÉÉ une seconde base « perso » et CINQ RÔLES, qui sont globaux au
    # cluster, sur le serveur du voisin ; il a réécrit les quatre DSN du
    # coffre pour y pointer ; et les unités du cerveau se sont mises à servir
    # cette base-là. Rien n'a échoué. Aucun message n'a nommé le cluster.
    #
    # C'est l'incident que tout ce framework existe pour empêcher, dans le
    # fichier qui prétend l'empêcher — et il ne se déclenchait pas sur une
    # faute de l'utilisateur, mais sur le geste documenté.
    #
    # Deux règles, désormais :
    #   1. ce que le coffre a retenu fait autorité quand l'appelant se tait ;
    #   2. quand l'appelant demande un AUTRE cluster que celui retenu, on
    #      refuse. Déplacer un cerveau d'un cluster à un autre est un geste
    #      qui vaut une migration de données, jamais un effet de bord.
    local _port_retenu="" _hote_retenu=""
    if [[ -r "$ARAC_ENV_FILE" ]]; then
        _port_retenu="$(lire_var "$ARAC_ENV_FILE" ARAC_DB_PORT || true)"
        _hote_retenu="$(lire_var "$ARAC_ENV_FILE" ARAC_DB_HOTE || true)"
        # Coffre d'avant l'écriture de ces deux lignes : le port vit encore
        # dans les DSN, qui sont écrits depuis toujours.
        if [[ -z "$_port_retenu" || -z "$_hote_retenu" ]]; then
            local _dsn; _dsn="$(lire_var "$ARAC_ENV_FILE" ARAC_DB_URL_ADMIN || true)"
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
                [[ -z "$_hote_retenu" ]] && _hote_retenu="${_hp%% *}"
                [[ -z "$_port_retenu" ]] && _port_retenu="${_hp##* }"
            fi
        fi
    fi

    if [[ -n "$_port_retenu" ]]; then
        if [[ -n "${ARAC_DB_PORT:-}" && "$ARAC_DB_PORT" != "$_port_retenu" ]]; then
            vide
            mal "$(_c 1 'REFUS — ce cerveau vit déjà sur un autre serveur PostgreSQL.')"
            vide
            dire "   retenu par l'installation   ${_hote_retenu:-127.0.0.1}:$_port_retenu"
            dire "   demandé maintenant          ${ARAC_DB_HOTE:-127.0.0.1}:$ARAC_DB_PORT"
            vide
            note "Continuer reviendrait à CRÉER une seconde base et cinq rôles sur le
serveur demandé — les rôles sont globaux au cluster, donc partagés avec
tout ce qui y vit — puis à repointer les DSN et les unités de ce cerveau
vers cette base neuve et vide. Sa mémoire resterait sur l'autre serveur,
intacte et injoignable, et rien ne l'aurait dit.

Déplacer un cerveau d'un cluster à un autre est une migration de
données : un dump, une restauration, une vérification. Ce n'est pas un
réglage d'environnement.

Si vous vouliez seulement relancer une étape, retirez ARAC_DB_PORT de
votre environnement — le coffre porte la bonne valeur, et elle sera
reprise toute seule."
            vide
            dire "$(_c 1 'Rien n'\''a été créé, rien n'\''a été écrit.')"
            vide
            exit 6
        fi
        ARAC_DB_PORT="$_port_retenu"
        [[ -n "$_hote_retenu" ]] && ARAC_DB_HOTE="${ARAC_DB_HOTE:-$_hote_retenu}"
    fi
    unset _port_retenu _hote_retenu

    ARAC_DB_HOTE="${ARAC_DB_HOTE:-127.0.0.1}"
    ARAC_DB_PORT="${ARAC_DB_PORT:-5432}"
    ARAC_SECRETS_ROLES="${ARAC_SECRETS_ROLES:-$ARAC_ETC/roles.env}"
    ARAC_SECRETS_COCKPIT="${ARAC_SECRETS_COCKPIT:-$ARAC_ETC/cockpit.env}"
    # --- LES COMPTES SYSTÈME PORTENT LE NOM DU CERVEAU --------------------
    #
    # Ils valaient « arac » et « aracagent » : les MÊMES deux comptes pour tous
    # les cerveaux de la machine. Les noms étaient cloisonnés depuis deux
    # manches — base, rôles, unités, coffres, journaux, sauvegardes, ports —
    # mais les DROITS ne l'étaient pas, et c'est par les droits qu'on lit la
    # mémoire de quelqu'un.
    #
    # CE QU'UN COMPTE COMMUN OUVRE, CONCRÈTEMENT
    #
    #   1. `/proc/<pid>/environ` est lisible par le propriétaire du processus.
    #      Les unités reçoivent les quatre DSN — mots de passe compris — par
    #      `EnvironmentFile=`. Deux cerveaux sous le même UID : le processus de
    #      l'un lit le mot de passe d'administration de l'autre, et le refus de
    #      `CONNECT` posé sur la base ne sert plus à rien puisqu'il présente le
    #      bon rôle. Lecture ET écriture, sur toute la mémoire.
    #   2. `/var/log/arac/<autre>` est en 0750 — mais appartenait au même
    #      utilisateur : les journaux du voisin se lisent sans effort.
    #   3. `StateDirectory=` donne le dossier d'état à `User=` : même UID, même
    #      accès à l'état vivant de l'autre cerveau.
    #
    # Le coffre `/etc/arac/<base>/` (0700 root) et les rôles PostgreSQL étaient,
    # eux, déjà cloisonnés. C'est le compte système qui rouvrait la porte
    # derrière eux.
    #
    # LA CONVENTION :  arac_<base>  et  aracagent_<base>
    #
    # La même que celle des rôles PostgreSQL (`arac_<base>_<fonction>`), pour
    # la même raison : « arac_ » dit le produit, « <base> » dit LE cerveau, et
    # ce n'est pas un sixième identifiant à tenir — c'est celui qui nomme déjà
    # la base, le coffre et les unités.
    #
    # REPRISE D'UNE INSTALLATION EXISTANTE. Ces deux variables ne sont pas
    # écrites dans le coffre : elles se recalculent à chaque passage. Un
    # cerveau installé sous « arac » qui rejoue son bootstrap obtient donc ses
    # comptes propres, et l'étape 9 déplace la propriété de ses dossiers
    # (voir `_reprendre_la_propriete` dans services.sh). Les anciens comptes
    # communs restent en place — ils ne sont plus référencés par aucune unité,
    # et les supprimer est une décision d'administrateur, pas un effet de bord
    # de ce script.
    ARAC_SERVICE_USER="${ARAC_SERVICE_USER:-$(_compte_systeme arac)}"
    ARAC_AGENT_USER="${ARAC_AGENT_USER:-$(_compte_systeme aracagent)}"
    _valider_compte_systeme "$ARAC_SERVICE_USER" ARAC_SERVICE_USER || exit 6
    _valider_compte_systeme "$ARAC_AGENT_USER"   ARAC_AGENT_USER   || exit 6
    if [[ "$ARAC_SERVICE_USER" == "$ARAC_AGENT_USER" ]]; then
        echec "les deux comptes système sont le même" \
              "ARAC_SERVICE_USER et ARAC_AGENT_USER valent tous deux « $ARAC_SERVICE_USER ».
Les séparer est délibéré : l'API et le cockpit n'ont pas les mêmes droits
que la digestion, et un seul compte annulerait cette séparation." \
              "Laissez ces deux variables se déduire du nom du cerveau, ou
donnez-leur deux valeurs distinctes."
        exit 6
    fi
    ARAC_VENV="${ARAC_VENV:-$ARAC_HOME/.venv}"
    # Journaux et sauvegardes : un sous-dossier PAR CERVEAU. Le dossier commun
    # était le troisième nom partagé de l'incident — la rotation d'un cerveau
    # supprimait les dumps de l'autre, et deux flots de journaux se mêlaient
    # dans le fichier même qu'on ouvre pour savoir lequel des deux a cassé.
    ARAC_LOG_DIR="${ARAC_LOG_DIR:-/var/log/arac/$ARAC_DB}"
    ARAC_BACKUP_DIR="${ARAC_BACKUP_DIR:-/var/backups/arac/$ARAC_DB}"
    ARAC_CYCLES="${ARAC_CYCLES:-04:00 13:00 21:00}"
    if [[ -z "${ARAC_CYCLE_TZ:-}" ]]; then
        if command -v timedatectl >/dev/null 2>&1; then
            ARAC_CYCLE_TZ="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
        fi
        [[ -z "$ARAC_CYCLE_TZ" && -r /etc/timezone ]] && ARAC_CYCLE_TZ="$(cat /etc/timezone)"
        ARAC_CYCLE_TZ="${ARAC_CYCLE_TZ:-UTC}"
    fi

    # --- CE COFFRE EST-IL LE NÔTRE ? --------------------------------------
    #
    # AVANT les ports, AVANT les rôles, AVANT la moindre lecture de secret :
    # c'est tout l'intérêt de le poser ici. Le refus de l'étape 3 arrive après
    # que le coffre a été ouvert et ses mots de passe chargés en mémoire ;
    # celui-ci arrive avant qu'on ait touché à quoi que ce soit.
    _controle_empreinte_du_coffre || exit 6

    # --- Les ports : constatés libres, puis RETENUS dans la configuration ---
    _resoudre_ports || exit 6

    # --- Le serveur doit être local ----------------------------------------
    #
    # Tout le DDL passe par `psql_super`, c'est-à-dire `sudo -u postgres psql`
    # sur la socket Unix locale : c'est ce qui permet de n'avoir AUCUN mot de
    # passe de superutilisateur, nulle part. Contre un serveur distant, cette
    # commande s'adresse malgré tout au serveur local — la base serait créée
    # ici, et les DSN écrits pointeraient là-bas. Rien n'échouerait à
    # l'installation ; tout échouerait au démarrage.
    case "$ARAC_DB_HOTE" in
        127.0.0.1|localhost|::1|"") : ;;
        *)
            vide
            mal "$(_c 1 "Ce bootstrap installe sur un PostgreSQL LOCAL.")"
            vide
            dire "Vous avez posé   ARAC_DB_HOTE=$ARAC_DB_HOTE"
            vide
            note "Il crée la base, les rôles et les extensions en superutilisateur, par
la socket Unix locale (« sudo -u postgres psql ») : c'est ce qui lui
permet de n'exiger aucun mot de passe de superutilisateur. Contre un
serveur distant, il n'a aucun moyen de faire ce travail — et le faire
à moitié serait pire : la base ici, les DSN là-bas.

Pour une base gérée ailleurs, l'installation se fait en deux temps, et
ce bootstrap ne couvre pas le premier. Posez ARAC_DB_HOTE=127.0.0.1
si votre PostgreSQL est bien sur cette machine ; pour un port autre
que 5432, ARAC_DB_PORT est, lui, honoré de bout en bout."
            vide
            exit 6 ;;
    esac

    # --- LE SCHÉMA, LUI, N'EST PAS ENCORE PARAMÉTRABLE ---------------------
    #
    # `ARAC_ROLE_PREFIX` l'est désormais, et il est même dérivé du cerveau par
    # défaut : c'était la cause première de l'incident. `ARAC_SCHEMA` ne l'est
    # toujours pas — les migrations écrivent « arac.memory_atoms » en toutes
    # lettres. Poser une autre valeur produirait, vingt migrations plus loin,
    # une base à moitié construite.
    #
    # La différence entre les deux n'est pas de degré, elle est de nature, et
    # c'est pour cela que l'un est corrigé et l'autre seulement refusé : un
    # SCHÉMA vit DANS une base, deux cerveaux ne peuvent donc pas se le
    # disputer. Un RÔLE vit dans le cluster, au-dessus des bases : c'est le
    # seul des deux qui pouvait détruire le cerveau du voisin.
    #
    # Un réglage à moitié honoré est pire qu'un réglage absent : on le pose,
    # on lit qu'il est pris en compte, et la panne survient ailleurs, plus
    # tard, sous un autre nom. On refuse donc tôt et en clair.
    # Déclaré comme une LISTE, et pas écrit en toutes lettres dans le `if` :
    # la documentation est tenue de dire quels réglages sont refusés, et
    # `tests/test_la_doc_dit_vrai.py` lit CETTE liste pour le vérifier. Un
    # refus que le code connaît et que la doc ignore envoie l'utilisateur dans
    # un `exit 6` qu'il attribuera à sa propre machine.
    #
    # Elle n'a plus qu'une entrée. `ARAC_ROLE_PREFIX` en sortait le jour où les
    # migrations ont appris à déduire leurs rôles — c'est-à-dire le jour où le
    # défaut qui a détruit une production a été corrigé.
    local -a REGLAGES_NON_HONORES=(ARAC_SCHEMA:arac)
    local reglage
    for reglage in "${REGLAGES_NON_HONORES[@]}"; do
        local nom="${reglage%%:*}" attendu="${reglage##*:}"
        [[ "${!nom}" == "$attendu" ]] && continue
        vide
        mal "$(_c 1 "$nom ne peut pas encore être changé.")"
        vide
        dire "Vous avez posé   $nom=${!nom}"
        dire "Seule valeur supportée aujourd'hui : $(_c 1 "$attendu")"
        vide
        note "Ce sont les migrations qui ne suivent pas : elles nomment le schéma
en toutes lettres. Avec une autre valeur, l'installation meurt à
l'étape 5, sur un message qui ne dit pas la cause.

Ce n'est PAS un obstacle à faire tourner deux cerveaux sur la même
machine : un schéma vit dans une base, et chaque cerveau a la sienne.
Ce qu'il fallait séparer — les rôles, les ports, les unités, les
dossiers — l'est désormais, et automatiquement."
        vide
        dire "$(_c 1 'Retirez ce réglage et relancez.')"
        exit 6
    done

    # LES CINQ NOMS SONT POSÉS PAR `poser_noms_de_roles` (lib/core.sh), et
    # `checks/verify_install.sh` appelle la MÊME fonction. Ils étaient écrits
    # ici ET là-bas ; là-bas, le cinquième manquait.
    #
    # Le cinquième, justement. Il n'a pas de mot de passe, pas de DSN, et
    # n'apparaît dans aucune leçon : il n'existe que parce que deux migrations
    # lui donnent des droits (voir _sql_roles). Le taire aurait été plus
    # élégant ; c'est précisément ce silence qui rendait l'installation
    # impossible. Il est donc dans `SUFFIXES_DE_ROLE`, et hors de
    # `ROLES_AVEC_DSN`.
    poser_noms_de_roles "$ARAC_ROLE_PREFIX"

    # LA BASE JETABLE A UN GABARIT, ET IL PORTE LE NOM DU CERVEAU.
    #
    # Même règle que tout le reste ici : un nom partagé entre deux cerveaux est
    # un accident qui attend. Cette valeur est exactement celle que les scripts
    # d'exploitation dérivent de leur côté
    # (`${ARAC_BACKUP_PREFIX}_restore_template`, et ARAC_BACKUP_PREFIX vaut
    # ARAC_DB) : on la nomme ici pour que l'étape 4 et ops/ ne puissent pas
    # diverger en silence.
    GABARIT_RESTAURATION="${ARAC_RESTORE_TEMPLATE_DB:-${ARAC_DB}_restore_template}"

    # ET ON LE JUGE, PARCE QUE L'ÉTAPE 4 L'EXÉCUTE EN SUPERUTILISATEUR.
    #
    # C'est le chemin qui manquait, et c'était le pire des deux : le bloc
    # imprimé par `ops/restore_verify.sh --prepare-template` passe au moins
    # sous les yeux de la personne qui tape le sudo. Celui-ci, non. Quatre
    # instructions de `_gabarit_de_restauration` (database.sh) portent ce nom
    # jusqu'à `sudo -u postgres psql`, et `ARAC_RESTORE_TEMPLATE_DB` est une
    # variable que docs/CONFIGURATION.md présente au lecteur comme réglable.
    #
    # On refuse l'installation plutôt que de composer du DDL avec : c'est le
    # geste qui tient encore le jour où cette valeur n'arrivera plus de la main
    # d'un opérateur mais d'un fichier, d'un gabarit, d'un outil.
    _valider_nom_base "$GABARIT_RESTAURATION" ARAC_RESTORE_TEMPLATE_DB \
        "Ce nom est celui du GABARIT de restauration. Il est composé à partir de
ARAC_RESTORE_TEMPLATE_DB si vous l'avez posée, sinon du nom de la base.
L'étape 4 le passe à « sudo -u postgres psql » sans qu'aucun humain ne
relise la commande." || exit 6

    # Le nom de la base est connu : l'avancement peut enfin être rattaché au
    # bon cerveau plutôt qu'au dépôt (voir etat_ancrer).
    etat_ancrer


    # --- La taxonomie tient-elle debout ? ---------------------------------
    local rapport rc=0
    rapport="$(cd "$ARAC_HOME" && python3 bootstrap/generate_scopes.py \
        --config config/scopes.toml --check 2>&1)" || rc=$?
    if (( rc == 2 || rc == 3 )); then
        vide
        mal "$(_c 1 'Votre taxonomie est refusée.')"
        vide
        printf '%s\n' "$rapport"
        vide
        dire "$(_c 1 'Corrigez config/scopes.toml, puis relancez.')"
        exit 6
    fi

    # --- Ce que le cerveau sera --------------------------------------------
    local racines feuilles
    racines="$(grep -c '^\[\[root\]\]' "$scopes" || true)"
    feuilles="$(grep -c '^\[\[leaf\]\]' "$scopes" || true)"

    bien "$(_c 1 "Le cerveau de $BRAIN_OWNER, nommé « $BRAIN_NOM ».")"
    vide
    dire "$(_c 1 'Identité')"
    dire "   propriétaire      $BRAIN_OWNER"
    dire "   nom du cerveau    $BRAIN_NOM"
    dire "   poste source      $ARAC_NODE_ID"
    dire "   empreinte         $ARAC_INSTALL_UUID$( ((EMPREINTE_DERIVEE)) && printf '   (dérivée de vos trois réponses)')"
    dire "   taxonomie         $racines domaines, $feuilles rangements"
    vide
    dire "$(_c 1 'Ce que ces réponses engendrent')"
    dire "   serveur           $ARAC_DB_HOTE:$ARAC_DB_PORT"
    dire "   base              $ARAC_DB   (schéma $ARAC_SCHEMA)"
    dire "   rôles             $R_ADMIN · $R_APP · $R_AGENT · $R_READONLY"
    dire "   secrets           $ARAC_ETC/   (0700, root)"
    dire "   environnement     $ARAC_ENV_FILE"
    dire "   services          $PREFIXE_UNITE-api · -cockpit · -cycle · -sauvegarde"
    dire "   API               127.0.0.1:$ARAC_API_PORT"
    dire "   cockpit           127.0.0.1:$ARAC_COCKPIT_PORT"
    dire "   cycles            $ARAC_CYCLES ($ARAC_CYCLE_TZ)"
    dire "   sauvegardes       $ARAC_BACKUP_DIR"
    vide
    note "Rien de tout cela n'est en dur : chaque ligne se remplace par une
variable d'environnement (voir --help). Les secrets vivent hors du dépôt,
dans $ARAC_ETC, pour qu'un « git add . » distrait ne les publie jamais."
    vide

    _annoncer_cluster

    lecon "Le poste source n'est pas décoratif." \
"Le cerveau refuse toute conversation dont l'identifiant de poste n'est
pas déclaré. C'est ce qui l'empêche d'avaler n'importe quoi — un agent
mal configuré, un import de test, un doublon d'une autre machine.
Ici : « $ARAC_NODE_ID »."

    # --- UN AUTRE CERVEAU EST-IL DÉJÀ SERVI DEPUIS CE DÉPÔT ? --------------
    #
    # CE REFUS ARRIVAIT À L'ÉTAPE 9, ET C'ÉTAIT TROIS ÉTAPES TROP TARD.
    #
    # L'étape 6 engendre, DANS le clone, `app/schemas/scope_generated.py` et
    # `db/seeds/scopes.sql` — deux fichiers qui appartiennent au dépôt et non
    # au cerveau. Servis d'un même dépôt, deux cerveaux se les écrasent : le
    # premier gardait sa base, ses rôles, ses ports et sa mémoire intacts,
    # mais son API validait désormais les domaines contre la taxonomie du
    # SECOND. Rien n'échouait à l'installation ; tout échouait à la première
    # écriture, en 422, avec un message parlant d'un domaine inconnu et non
    # d'une installation partagée.
    #
    # Le refus disait lui-même « l'étape 6 a bien réécrit les deux fichiers
    # ci-dessus » et proposait au lecteur d'aller réparer chez le voisin. Un
    # garde qui constate les dégâts qu'il aurait dû empêcher n'est pas un
    # garde : c'est un constat d'huissier.
    #
    # Il tourne donc ICI, à l'étape 2, qui n'écrit rien — et donc aussi en
    # simulation, ce qui est le point : `--dry-run` doit pouvoir le dire
    # avant qu'un seul fichier ne bouge.
    #
    # `exit 6` ET NON `return 8`, ET LA NUANCE EST TOUT LE CORRECTIF.
    #
    # `return 8` signifie « étape incomplète » : la boucle de bootstrap.sh
    # l'enregistre et CONTINUE avec les étapes suivantes. Posé ici, il faisait
    # afficher le refus à l'étape 2… puis laissait l'étape 6 engendrer la
    # taxonomie dans le dépôt partagé, c'est-à-dire commettre exactement le
    # dégât qu'on venait d'annoncer. Un refus qu'on peut dépasser n'est pas un
    # refus : c'est un avertissement.
    #
    # `exit 6` est le code que cette étape emploie déjà pour ses erreurs
    # fatales de configuration (voir `_resoudre_ports`). Rien de ce qui suit
    # ne s'exécute.
    _controle_depot_non_partage || exit 6

    return 0
}

# ===========================================================================
# LES PORTS — constatés libres AVANT d'être attribués, puis retenus
# ===========================================================================
#
# CE QUE CETTE FONCTION EMPÊCHE
#
# Une unité d'essai a lié le 8000, celui de l'API de production. Celle-ci a
# redémarré 35 fois sur « [Errno 98] address already in use », et pendant tout
# ce temps `/healthz` répondait 200 — servi par l'usurpateur. C'est le pire
# genre de panne : elle se présente comme une santé, et le premier réflexe du
# diagnostic la confirme.
#
# ORDRE DE RÉSOLUTION — le premier qui répond gagne
#
#   1. l'environnement (ARAC_API_PORT / ARAC_COCKPIT_PORT) : décision explicite
#      de l'opérateur, honorée telle quelle — mais tout de même CONTRÔLÉE ;
#   2. la configuration du cerveau : [services] api_port dans brain.toml,
#      puis, si le cerveau a déjà été installé, le fichier d'environnement.
#      C'est ce qui rend une réinstallation stable — un cerveau ne change pas
#      de port parce qu'on a relancé son bootstrap ;
#   3. à défaut, un point de départ, et le premier numéro libre à partir de là.
#
# DANS TOUS LES CAS le numéro retenu est constaté libre — ou tenu par NOTRE
# propre unité, ce qui est une réinstallation et non un conflit.

# ---------------------------------------------------------------------------
# LE COFFRE PORTE UNE EMPREINTE, ET ON LA REGARDE AVANT DE L'OUVRIR
# ---------------------------------------------------------------------------
#
# `/etc/arac/<base>/` est dérivé du NOM du cerveau. Deux personnes qui
# choisissent le même nom visent donc le même dossier — et le second
# bootstrap y trouvait un `arac.env` complet : jeton porteur, DSN, mots de
# passe. Il le lisait, concluait « réinstallation », et repartait avec les
# secrets de quelqu'un d'autre. Constaté : liste blanche d'ingestion élargie
# au poste du second, ports du premier réécrits, unités du premier repointées
# vers le dépôt du second, et son cockpit servant sa propre base à un tiers.
#
# Ce contrôle ne coûte qu'une lecture. Il rend trois réponses, et la
# troisième — « je n'ai pas pu savoir » — n'est pas confondue avec « c'est le
# mien » : sans droit de lecture sur le coffre, on ne conclut rien, et l'étape
# 3, elle, tranchera en root sur les plaques des rôles.
_controle_empreinte_du_coffre() {
    [[ -e "$ARAC_ENV_FILE" ]] || return 0

    if [[ ! -r "$ARAC_ENV_FILE" ]]; then
        note "  Un coffre existe en $ARAC_ETC mais n'est pas lisible par $(id -un) :
   son appartenance n'est PAS vérifiée ici. L'étape 3, qui tourne en
   root, la vérifiera sur les plaques des rôles PostgreSQL."
        return 0
    fi

    local posee proprietaire_pose
    posee="$(lire_var "$ARAC_ENV_FILE" ARAC_INSTALL_UUID || true)"
    proprietaire_pose="$(lire_var "$ARAC_ENV_FILE" ARAC_BRAIN_OWNER || true)"

    # Coffre d'AVANT le marquage. On l'adopte — c'est la seule migration
    # possible — mais on le DIT, parce qu'adopter en silence est exactement le
    # geste qu'on corrige.
    if [[ -z "$posee" ]]; then
        alerte "Ce coffre est antérieur au marquage des installations."
        note "  $ARAC_ENV_FILE ne porte pas encore d'empreinte. Ce bootstrap va
   donc l'adopter et y graver la sienne :
       $ARAC_INSTALL_UUID
   Si ce coffre n'est PAS le vôtre, arrêtez maintenant (Ctrl-C) : après
   cette étape, il le sera."
        return 0
    fi

    [[ "$posee" == "$ARAC_INSTALL_UUID" ]] && return 0

    vide
    mal "$(_c 1 'REFUS — ce cerveau porte votre nom, pas votre empreinte.')"
    vide
    dire "Un cerveau nommé « $BRAIN_NOM » est déjà installé sur cette machine."
    vide
    dire "   coffre            $ARAC_ETC/"
    dire "   déclaré par       ${proprietaire_pose:-un propriétaire non déclaré}"
    dire "   empreinte trouvée $posee"
    dire "   empreinte attendue $ARAC_INSTALL_UUID   (config/brain.toml de ce dépôt)"
    vide
    dire "$(_c 1 'POURQUOI CE N'\''EST PAS UNE RÉINSTALLATION')"
    note "Tout ce que ce bootstrap fabrique descend du NOM que vous avez donné :
la base « $ARAC_DB », les rôles « ${ARAC_ROLE_PREFIX}_* », les unités
« $PREFIXE_UNITE-* », ce dossier de secrets. Deux personnes qui choisissent
le même nom — « perso », « test », un prénom — visent donc les mêmes
objets, au caractère près.

Sans empreinte, je ne pouvais pas distinguer « c'est mon cerveau, je le
réinstalle » de « c'est celui de quelqu'un d'autre, qui porte le même
nom ». Je choisissais la première réponse. Elle donnait au second
arrivant le jeton porteur du premier, sa liste blanche d'ingestion, ses
mots de passe de base, et ses unités systemd."
    vide
    dire "$(_c 1 'LE GESTE, SELON QUI VOUS ÊTES')"
    vide
    dire "  · $(_c 1 'Ce cerveau est le vôtre') — vous avez reperdu ou reconstruit"
    dire "    config/brain.toml. Reportez-y l'empreinte qu'il porte déjà :"
    vide
    cmd "sudo grep '^ARAC_INSTALL_UUID=' $ARAC_ENV_FILE"
    dire "    puis, dans config/brain.toml, section [brain] :"
    cmd "uuid = \"$posee\""
    vide
    dire "  · $(_c 1 'Ce cerveau est celui de quelqu'\''un d'\''autre') — donnez au vôtre"
    dire "    un autre nom, et tout le reste suivra :"
    cmd "python3 bootstrap/wizard.py        # et choisissez un autre nom"
    vide
    dire "$(_c 1 'Rien n'\''a été lu de ce coffre, rien n'\''a été écrit.')"
    vide
    return 1
}

_resoudre_ports() {
    local depart_api depart_cockpit
    depart_api=8000        # départ, pas attribution — voir premier_port_libre
    depart_cockpit=8100    # départ, pas attribution — voir premier_port_libre

    local prec_api prec_cockpit
    prec_api="${BRAIN_API_PORT:-}"
    prec_cockpit="${BRAIN_COCKPIT_PORT:-}"
    if [[ -r "$ARAC_ENV_FILE" ]]; then
        [[ -z "$prec_api"     ]] && prec_api="$(lire_var "$ARAC_ENV_FILE" ARAC_API_PORT || true)"
        [[ -z "$prec_cockpit" ]] && prec_cockpit="$(lire_var "$ARAC_ENV_FILE" ARAC_COCKPIT_PORT || true)"
    fi

    _resoudre_un_port API     ARAC_API_PORT     "$prec_api"     "$depart_api"     || return 1
    _resoudre_un_port cockpit ARAC_COCKPIT_PORT "$prec_cockpit" "$depart_cockpit" || return 1

    if [[ "$ARAC_API_PORT" == "$ARAC_COCKPIT_PORT" ]]; then
        vide
        mal "$(_c 1 "L'API et le cockpit ne peuvent pas partager un port.")"
        dire "   les deux valent $ARAC_API_PORT"
        vide
        return 1
    fi
    return 0
}

#: nom_lisible · variable · valeur souhaitée (peut être vide) · point de départ
_resoudre_un_port() {
    local nom="$1" var="$2" souhaite="$3" depart="$4"
    local unite="" retenu="" rc

    # L'unité de CE cerveau, si elle est déjà connue : un port qu'elle tient
    # déjà n'est pas un obstacle, c'est une réinstallation.
    case "$nom" in
        API)     unite="$U_API.service" ;;
        cockpit) unite="$U_COCKPIT.service" ;;
    esac

    local explicite=0
    [[ -n "${!var:-}" ]] && { souhaite="${!var}"; explicite=1; }
    [[ -z "$souhaite" ]] && souhaite="$depart"

    if [[ ! "$souhaite" =~ ^[0-9]+$ ]] || (( souhaite < 1 || souhaite > 65535 )); then
        vide
        mal "$(_c 1 "Port $nom invalide : « $souhaite »")"
        vide
        return 1
    fi

    if _port_disponible_pour_nous "$souhaite" "$unite"; then
        printf -v "$var" '%s' "$souhaite"
        return 0
    fi

    # Le port souhaité est tenu par quelqu'un d'autre.
    local tenant; tenant="$(tenant_du_port "$souhaite")"

    # Un choix EXPLICITE ne se contourne pas en douce : on refuse, on montre
    # le tenant, et on rend la main. Déplacer silencieusement un numéro que
    # l'opérateur a écrit lui-même produirait un service joignable ailleurs
    # que là où il l'attend — et il ne l'apprendrait qu'au premier appel.
    if (( explicite )); then
        vide
        mal "$(_c 1 "Le port $nom que vous avez posé ($souhaite) est déjà tenu.")"
        vide
        note "   $tenant"
        vide
        dire "Retirez $var pour laisser ce bootstrap en attribuer un libre,"
        dire "ou libérez ce port."
        vide
        return 1
    fi

    retenu="$(premier_port_libre "$((souhaite + 1))" 40)"; rc=$?
    if (( rc == 2 )); then
        vide
        mal "$(_c 1 "Impossible de savoir si un port est libre : « ss » est absent.")"
        vide
        note "Attribuer un port sans pouvoir constater qu'il est libre, c'est
exactement le geste qui a lié le port de l'API de production. On
refuse plutôt que de supposer.

  sudo apt install iproute2

…ou posez $var explicitement, en sachant ce que vous faites."
        vide
        return 1
    fi
    if (( rc != 0 )); then
        vide
        mal "$(_c 1 "Aucun port libre pour le $nom entre $souhaite et $((souhaite + 40)).")"
        vide
        return 1
    fi

    printf -v "$var" '%s' "$retenu"
    vide
    alerte "$(_c 1 "Port $nom : $souhaite est déjà tenu — ce cerveau prendra $retenu.")"
    note "   $tenant"
    note "Le numéro retenu est écrit dans la configuration de ce cerveau
   ($ARAC_ENV_FILE) : les unités, le contrôle final et le tunnel SSH le
   reprendront, et une relance de ce bootstrap le relira au lieu d'en
   choisir un autre."
    vide
    return 0
}

#: Vrai si le port est libre, OU tenu par notre propre unité (réinstallation).
#: Faux si tenu par autre chose. Faux aussi si on ne peut pas savoir : ne pas
#: savoir n'est pas une autorisation.
_port_disponible_pour_nous() { # port unite
    local port="$1" unite="$2" rc
    port_libre "$port"; rc=$?
    (( rc == 0 )) && return 0
    (( rc == 2 )) && return 1
    [[ -z "$unite" ]] && return 1
    local ligne; ligne="$(ss -ltnHp "sport = :$port" 2>/dev/null | head -1)"
    socket_appartient_a "$ligne" "$unite"
    [[ $? -eq 0 ]]
}

# ===========================================================================
# CE CLUSTER HÉBERGE-T-IL DÉJÀ UN CERVEAU ?
# ===========================================================================
#
# Le dire AVANT d'agir, et le dire en trois temps : ce qu'on a trouvé, ce
# qu'on va créer, ce qu'on ne touchera pas. C'est la phrase qui manquait le
# jour où une installation d'essai a écrasé une production — non parce que
# l'information était introuvable, mais parce que personne n'avait de raison
# de la chercher.

_cerveaux_du_cluster() {
    # Une famille de rôles « <préfixe>_admin » + « <préfixe>_app » désigne un
    # cerveau. On interroge le catalogue, en lecture : autorisé en simulation.
    pg_lire "
      SELECT DISTINCT left(a.rolname, length(a.rolname) - 6)
        FROM pg_roles a
        JOIN pg_roles b ON b.rolname = left(a.rolname, length(a.rolname) - 6) || '_app'
       WHERE a.rolname LIKE '%\_admin'
       ORDER BY 1"
}

# ---------------------------------------------------------------------------
# LA RECETTE DE LA GRAPPE DÉDIÉE — ET LE MOMENT OÙ ELLE SERT
# ---------------------------------------------------------------------------
#
# CE QUI ÉTAIT FAUX, ET C'EST UN RENVERSEMENT COMPLET DE L'INTENTION.
#
# Cette recette n'était imprimée que dans la branche « aucun autre cerveau ARAC
# détecté » — c'est-à-dire dans le SEUL cas où elle ne protège rien. Dès qu'un
# voisin était là, `_annoncer_cluster` listait les voisins, annonçait les cinq
# rôles à créer, promettait de ne toucher à rien… et ne disait plus un mot de
# la grappe dédiée. Mesuré : sur une grappe vide, `grep -c pg_createcluster`
# rend 1 ; sur la même grappe habitée par un cerveau, il rend 0 — et 0 aussi à
# l'installation réelle. Le conseil était donné quand il était inutile et tu
# exactement quand il comptait. `docs/INSTALLATION.md` §12.f s'appuyait
# pourtant sur lui : « et la simulation le recommande elle-même ».
#
# ET LE SECOND CRITÈRE, QUI COMPTE AUTANT : un bon conseil au mauvais moment ne
# vaut pas mieux qu'un mauvais conseil. Une fois le port RETENU dans le coffre,
# le choix n'est plus gratuit : ce bootstrap REFUSE (code 6) d'en changer, et
# déplacer un cerveau d'une grappe à une autre est une migration de données.
# Continuer à imprimer « donnez-lui sa propre grappe » à ce moment-là
# prescrirait un geste que le produit rejette trois écrans plus loin. On
# imprime donc la RECETTE tant que le choix est ouvert, et le CONSTAT — le port
# est retenu, il ne se change plus — dès qu'il est refermé.
_grappe_recette() { # nombre_de_voisins
    local voisins="${1:-0}" retenu="" majeure=""
    [[ -n "${ARAC_ENV_FILE:-}" && -r "${ARAC_ENV_FILE:-}" ]] &&
        retenu="$(lire_var "$ARAC_ENV_FILE" ARAC_DB_PORT 2>/dev/null || true)"

    if [[ -n "$retenu" ]]; then
        note "Ce cerveau a DÉJÀ retenu sa grappe : port $retenu, écrit dans
$ARAC_ENV_FILE. Le choix est refermé — ce bootstrap refuse (code 6) de
l'installer sur une autre, et l'y déplacer serait une migration de
données : un dump, une restauration, une vérification. Rien à faire ici."
        vide
        return 0
    fi

    # La version majeure du serveur auquel on parle, pas un nombre en dur :
    # `pg_createcluster 16` sur une machine en 15 rend « unsupported version ».
    majeure="$(pg_lire "SELECT current_setting('server_version_num')::int / 10000")"
    [[ "$majeure" =~ ^[0-9]+$ ]] || majeure="<version>"

    if (( voisins == 0 )); then
        note "Rien à ménager ici. Sachez tout de même que la voie RECOMMANDÉE
pour un second cerveau reste une grappe qui lui est propre."
    else
        alerte "$(_c 1 "CE CERVEAU VA VIVRE SUR LA MÊME GRAPPE QUE $voisins AUTRE(S).")"
        note "Ce n'est plus destructeur — les rôles portent le nom du cerveau. Mais
c'est le DERNIER moment où le choix est gratuit : après l'étape 3, le
port est retenu dans le coffre et ce bootstrap REFUSE (code 6) d'en
changer. La grappe à lui, maintenant ou jamais sans migration :"
    fi
    vide
    cmd "sudo pg_createcluster $majeure <nom> --port <port> --start
sudo ARAC_DB_PORT=<port> ./bootstrap/bootstrap.sh"
    vide
    note "C'est ARAC_DB_PORT qui transmet ce choix, et c'est la SEULE chose qui
le transmette : omise, elle vaut 5432 — la grappe par défaut de la
machine, donc, sur un serveur qui héberge déjà un cerveau, celle du
voisin. Le raisonnement complet est au §12.f de docs/INSTALLATION.md.

Les rôles, eux, sont nommés par cerveau : deux cerveaux peuvent
cohabiter sur une même grappe sans se détruire. La grappe dédiée reste
plus sûre — elle sépare aussi la mémoire partagée, les journaux du
serveur, et le geste « je jette ce cerveau » (pg_dropcluster)."
    vide
    return 0
}

_annoncer_cluster() {
    local familles; familles="$(_cerveaux_du_cluster)"
    local autres=()
    local f
    while IFS= read -r f; do
        [[ -z "$f" ]] && continue
        [[ "$f" == "$ARAC_ROLE_PREFIX" ]] && continue
        autres+=("$f")
    done <<< "$familles"

    dire "$(_c 1 "Ce cluster PostgreSQL (port $ARAC_DB_PORT)")"
    if (( ${#autres[@]} == 0 )); then
        dire "   aucun autre cerveau ARAC détecté"
        vide
        _grappe_recette 0
        return 0
    fi

    dire "   $(_c 1 "${#autres[@]} autre(s) cerveau(x) ARAC déjà présent(s) :")"
    for f in "${autres[@]}"; do
        local base; base="$(pg_lire "SELECT datname FROM pg_database WHERE datname = '${f#arac_}'")"
        dire "      rôles $f _admin/_app/_agent/_readonly/_backup${base:+   base « $base »}"
    done
    vide
    dire "$(_c 1 'CE QUE CETTE INSTALLATION VA CRÉER')"
    dire "   base      $ARAC_DB"
    dire "   rôles     ${ARAC_ROLE_PREFIX}_admin · _app · _agent · _readonly · _backup"
    dire "   ports     $ARAC_API_PORT (API) · $ARAC_COCKPIT_PORT (cockpit)"
    dire "   secrets   $ARAC_ETC/"
    vide
    dire "$(_c 1 'CE QU'\''ELLE NE TOUCHERA PAS')"
    dire "   aucun rôle listé ci-dessus : leurs noms diffèrent des siens, et"
    dire "   ce bootstrap REFUSE de réutiliser un rôle qu'il n'a pas créé"
    dire "   (étape 3) — il n'exécute jamais ALTER ROLE … PASSWORD."
    dire "   aucune base autre que « $ARAC_DB »."
    dire "   aucun port déjà en écoute : ils ont été constatés libres ci-dessus."
    vide
    _grappe_recette "${#autres[@]}"
    return 0
}
