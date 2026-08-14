# shellcheck shell=bash
# ---------------------------------------------------------------------------
# services.sh — étape 9 : le cerveau se met à vivre tout seul.
#
# HUIT unités — cinq services et trois minuteries —, et aucun chemin en dur :
# chaque gabarit est engendré à partir des variables calculées à l'étape 2.
# Deux cerveaux sur la même machine portent des noms d'unités différents et ne
# se marchent pas dessus.
#
# Cet en-tête a dit « Quatre unités » jusqu'à cette manche, alors que
# `etape_services` en pose huit depuis que la restauration hebdomadaire existe.
# La liste qui fait foi est celle des `_poser_unite` ci-dessous ; elle se lit en
# huit lignes, et c'est la seule qui compte.
#
# CES UNITÉS N'ONT PAS DE GABARIT, ET CET EN-TÊTE A PRÉTENDU LE CONTRAIRE.
# Il annonçait : « si le dépôt fournit des gabarits dans
# deploy/systemd/*.service.template, ils sont préférés : les placeholders
# __ARAC_XXX__ y sont substitués ». Aucun code de `bootstrap/` ne lit ce
# répertoire, et `deploy/systemd/` ne contient aucun `*.service.template` —
# seulement les deux `.modele` du pont « sans Mac », qui se substituent à la
# main. Un mécanisme qu'on croit là est plus coûteux qu'un mécanisme absent :
# on y pose un gabarit, et rien ne le lit.
#
# Ce qui fait foi est ci-dessous, et nulle part ailleurs : les fonctions
# `_unite_*`, qui écrivent leur unité par un `cat <<EOF` où toute valeur est
# une variable du shell. Il n'y a donc AUCUN jeton de gabarit à substituer
# dans une unité posée par ce bootstrap — c'est ce que vérifie
# `tests/test_gabarits_le_fichier_pose_ne_porte_aucun_jeton.py`.
# ---------------------------------------------------------------------------

etape_services() {
    ARAC_API_APP="${ARAC_API_APP:-app.main:app}"
    ARAC_COCKPIT_APP="${ARAC_COCKPIT_APP:-control_center.app:app}"
    ARAC_CYCLE_MODULE="${ARAC_CYCLE_MODULE:-agents.cortex.cycle}"
    ARAC_AGENT_HOME="${ARAC_AGENT_HOME:-/var/lib/arac/$ARAC_DB}"
    ARAC_UNITS_DIR="${ARAC_UNITS_DIR:-/etc/systemd/system}"
    #: Le défaut est nommé une fois, et l'écran le CITE au lieu de citer la
    #: valeur courante : « un bootstrap relancé sans lui le ramène à 90 jours »
    #: alors qu'on venait de poser 90 se lit comme une promesse de stabilité,
    #: c'est-à-dire l'inverse exact de ce que la phrase veut dire.
    ARAC_BACKUP_RETENTION_DEFAUT=14
    ARAC_BACKUP_RETENTION="${ARAC_BACKUP_RETENTION:-$ARAC_BACKUP_RETENTION_DEFAUT}"

    # U_API / U_COCKPIT / U_CYCLE / U_BACKUP sont posés à l'étape 2, avec
    # PREFIXE_UNITE : la résolution des ports en a besoin pour reconnaître nos
    # propres unités. Les redéfinir ici en ferait deux vérités.

    etape_entete "$(rang_etape services)" "$TOTAL_ETAPES" "${TITRE_ETAPE[services]}" \
"Un cerveau qu'il faut lancer à la main n'est pas un cerveau : c'est un
script. Ces cinq unités le rendent autonome — il écoute, il se montre,
il digère à heures fixes, il se sauvegarde, et il PROUVE sa sauvegarde." \
"Cinq unités systemd et trois minuteries dans $ARAC_UNITS_DIR :
  · $(pad "$U_API" 30)l'API, en boucle locale (127.0.0.1:$ARAC_API_PORT)
  · $(pad "$U_COCKPIT" 30)le cockpit, en boucle locale (127.0.0.1:$ARAC_COCKPIT_PORT)
  · $(pad "$U_CYCLE" 30)la digestion, $ARAC_CYCLES ($ARAC_CYCLE_TZ)
  · $(pad "$U_BACKUP" 30)la sauvegarde, toutes les six heures
  · $(pad "$U_RESTORE" 30)la restauration VÉRIFIÉE, dimanche 03:00 UTC" \
"Le cerveau devient joignable sans vous. Il digère par cycles, pas en
continu : entre deux cycles, il est au repos — c'est normal, ce n'est pas
une panne. Et il n'écoute JAMAIS sur une adresse publique."

    lecon "Pourquoi la restauration a sa propre minuterie" \
"« Une sauvegarde qui n'a jamais été restaurée n'est pas une sauvegarde » est
la première phrase de docs/SAUVEGARDE.md. Elle était un slogan : le bootstrap
armait la sauvegarde et pas la restauration, et le contrôle quotidien répondait
« aucune restauration n'a jamais été vérifiée — vos dumps sont une hypothèse.
Aucun minuteur ne le fait à votre place. » C'était exact, et c'était le défaut.

$U_RESTORE restaure chaque dimanche le dump le plus récent dans une
base JETABLE, compte ce qui en sort, compare avec le cerveau vivant, puis
détruit ce qu'il a créé. Il ne touche jamais la base vivante, et il ne demande
aucun superutilisateur PostgreSQL. Si le coffre se vide un jour, vous
l'apprendrez dans la semaine, pas le jour du désastre."

    lecon "Trois cycles par jour, pas un flux continu" \
"Le cerveau de référence digère à 04:00, 13:00 et 21:00. Ce n'est pas une
limitation technique : penser coûte, et une pensée continue coûte en
continu. Entre deux cycles, le cerveau accumule ; au cycle, il traite tout
ce qui s'est accumulé d'un coup.

Corollaire : ce que vous dites à 14 h n'est pas mémorisé à 14 h 01. Un
cerveau au repos qui n'a rien produit depuis six heures fonctionne
peut-être parfaitement."
    vide

    if ! moteur_present; then
        alerte "Le moteur n'est pas encore présent : les services n'auraient rien à lancer."
        note "  ExecStart pointerait vers $ARAC_API_APP et $ARAC_CYCLE_MODULE,
  qui n'existent pas dans ce dépôt. Poser des unités qui échouent au
  démarrage serait pire que de ne rien poser.
  Cette étape sera rejouée telle quelle quand le moteur sera là :
    $(geste_bootstrap "--from services")"
        return 8
    fi

    # --- Le dépôt est-il seulement ATTEIGNABLE par les services ? ----------
    # Ce contrôle est AVANT `exiger_root` et avant toute écriture : il ne lit
    # que des permissions, il tourne donc aussi en simulation. C'est le point :
    # `--dry-run` doit pouvoir le dire avant qu'une seule unité n'existe.
    _controle_accessibilite_depot || return 8

    # Et les deux numéros de port que ces unités figent sont-ils libres ?
    # Même raison, même moment : rien n'est encore écrit.
    _controle_ports_libres || return 8

    # Un DEUXIÈME cerveau servi depuis CE dépôt ? Voir la fonction : c'est le
    # dernier nom que deux cerveaux se partagent encore, et le plus coûteux.
    _controle_depot_non_partage || return 8

    exiger_root "services"

    plan "utilisateurs système : $ARAC_SERVICE_USER (services) et $ARAC_AGENT_USER (cycles)"
    plan "dossiers : $ARAC_LOG_DIR, $ARAC_BACKUP_DIR, $ARAC_AGENT_HOME"
    plan "unités : $U_API.service $U_COCKPIT.service $U_CYCLE.{service,timer} $U_BACKUP.{service,timer} $U_RESTORE.{service,timer}"
    plan "systemctl daemon-reload puis enable --now"
    vide
    alerte "La sauvegarde SUPPRIME les dumps de plus de $ARAC_BACKUP_RETENTION jours dans"
    dire "     $ARAC_BACKUP_DIR. C'est le seul geste destructeur de tout ce"
    dire "     bootstrap."
    # LE GESTE IMPRIMÉ ÉTAIT INEXÉCUTABLE ET TROP LARGE À LA FOIS. Il disait
    # « ARAC_BACKUP_RETENTION=90 ./bootstrap/bootstrap.sh » : sans `sudo`, alors
    # que cette étape écrit dans /etc/systemd/system ; et en relançant les onze
    # étapes, alors que ce nombre ne vit QUE dans l'unité de sauvegarde
    # (`Environment=ARAC_BACKUP_RETENTION_DAYS=`) et nulle part ailleurs — ni
    # dans le coffre, ni en base. C'est aussi ce qui rend la dernière phrase
    # nécessaire : la valeur n'étant retenue nulle part, un bootstrap relancé
    # sans elle la ramène à son défaut.
    dire "     Pour le changer :"
    cmd "sudo ARAC_BACKUP_RETENTION=90 $(prefixe_invocation)./bootstrap/bootstrap.sh --from services"
    dire "     Ce nombre ne vit que dans l'unité : il n'est écrit ni dans le coffre"
    dire "     ni en base. Un bootstrap relancé sans lui le ramène à $ARAC_BACKUP_RETENTION_DEFAUT jours."
    dire "     Pour l'annuler : éditez l'unité après coup, ou sauvegardez ailleurs."
    vide

    if (( BAVARD )); then
        vide
        dire "$(_c 1 'Contenu des unités qui seront écrites :')"
        local u
        for u in api cockpit cycle cycle_timer backup backup_timer restauration restauration_timer; do
            vide
            dire "$(_c 2 "──── $u")"
            "_unite_$u" | sed 's/^/      /'
        done
    else
        note "  (--bavard montre le contenu exact de chaque unité avant écriture)"
    fi

    reel || return 0

    # --- Utilisateurs et dossiers -----------------------------------------
    _creer_utilisateur "$ARAC_SERVICE_USER" /nonexistent
    _creer_utilisateur "$ARAC_AGENT_USER"   "$ARAC_AGENT_HOME"

    # LES PARENTS SONT COMMUNS, LES FEUILLES SONT PRIVÉES — ET IL FAUT POSER
    # LES PARENTS D'ABORD.
    #
    # `install -d -m 0750 -o <compte>` applique le mode ET le propriétaire à
    # TOUS les répertoires qu'il crée, parents compris. Le premier cerveau
    # installé s'appropriait donc `/var/log/arac` LUI-MÊME, en 0750 : le second
    # ne pouvait plus seulement le TRAVERSER. Son dossier de journaux existait,
    # lui appartenait, portait les bons droits — et restait inatteignable pour
    # son propre service, parce que le chemin pour y arriver était fermé.
    #
    # Mesuré : `/var/log/arac  drwxr-x--- arac_<premier> arac_<premier>`.
    #
    # On repose donc les trois racines communes en root:0755 avant les
    # feuilles. Ce n'est pas un affaiblissement : ces répertoires ne portent
    # que des NOMS de cerveaux, jamais leur contenu. Un nom de dossier visible
    # n'apprend rien que `systemctl list-units` ne dise déjà.
    local racine
    for racine in "$ARAC_LOG_DIR" "$ARAC_BACKUP_DIR" "$ARAC_AGENT_HOME"; do
        install -d -m 0755 -o root -g root "$(dirname "$racine")"
    done

    # 0750, ET LE PROPRIÉTAIRE EST PROPRE À CE CERVEAU. Les deux moitiés
    # comptent : le mode seul ne protégeait rien tant que le propriétaire était
    # le compte commun de toute la machine.
    install -d -m 0750 -o "$ARAC_SERVICE_USER" -g "$ARAC_SERVICE_USER" "$ARAC_LOG_DIR"
    install -d -m 0700 -o root -g root "$ARAC_BACKUP_DIR"
    install -d -m 0750 -o "$ARAC_AGENT_USER" -g "$ARAC_AGENT_USER" "$ARAC_AGENT_HOME"
    # Les sous-dossiers d'état, créés ICI et pas par les services : sous
    # ProtectSystem=strict, un ReadWritePaths qui désigne un chemin ABSENT fait
    # échouer le démarrage de l'unité entière, avant tout code applicatif.
    local d
    for d in "$ARAC_AGENT_HOME/data" "$ARAC_AGENT_HOME/var"; do
        install -d -m 0750 -o "$ARAC_AGENT_USER" -g "$ARAC_AGENT_USER" "$d"
    done
    # LE DOSSIER PERSONNEL DE L'OUTIL DE CURATION — 0700, et pas 0750.
    #
    # C'est ici que le binaire `claude` lit et écrit ce qui l'authentifie
    # (`.claude/.credentials.json`, `.claude.json`). Le cycle force HOME sur ce
    # chemin (agents/lib/claude_cli.py) : une session ouverte AILLEURS —
    # dans /root, par exemple — n'est jamais vue, et c'est la cause exacte du
    # « Not logged in » qu'un cycle rend sans autre explication. On le crée
    # donc à l'installation, pour qu'il ait un nom à donner à qui doit s'y
    # connecter, et on le ferme aux autres comptes : des identifiants ne se
    # partagent pas avec un groupe.
    install -d -m 0700 -o "$ARAC_AGENT_USER" -g "$ARAC_AGENT_USER" \
            "$ARAC_AGENT_HOME/data/agent-home"
    # `install -d` ne corrige que le dossier de tête. Une installation reprise
    # depuis les comptes communs y laisserait tout son CONTENU au compte de la
    # machine — c'est-à-dire lisible par le cerveau voisin, qui tourne encore
    # sous ce compte-là.
    _reprendre_la_propriete "$ARAC_LOG_DIR"   "$ARAC_SERVICE_USER"
    _reprendre_la_propriete "$ARAC_AGENT_HOME" "$ARAC_AGENT_USER"
    # Le contrôle de santé va relire l'authentification de la curation SOUS ce
    # compte et DANS ce dossier : il les lit ici plutôt que de les recalculer.
    poser_var "$ARAC_ENV_FILE" ARAC_AGENT_HOME "$ARAC_AGENT_HOME"
    bien "Utilisateurs et dossiers en place."

    # --- LA PREUVE, maintenant que ces identités existent -------------------
    # Dernier moment où l'on peut encore ne rien écrire. Ce qui précède
    # déduisait ; ceci mesure, sous l'identité et sous les propriétés de
    # durcissement exactes de l'unité.
    _controle_execution_sous_unite || return 8

    # --- Unités -------------------------------------------------------------
    _poser_unite "$U_API.service"      _unite_api
    _poser_unite "$U_COCKPIT.service"  _unite_cockpit
    _poser_unite "$U_CYCLE.service"    _unite_cycle
    _poser_unite "$U_CYCLE.timer"      _unite_cycle_timer
    _poser_unite "$U_BACKUP.service"   _unite_backup
    _poser_unite "$U_BACKUP.timer"     _unite_backup_timer
    _poser_unite "$U_RESTORE.service"  _unite_restauration
    _poser_unite "$U_RESTORE.timer"    _unite_restauration_timer

    systemctl daemon-reload
    bien "systemd rechargé."

    local unite
    for unite in "$U_API.service" "$U_COCKPIT.service"; do
        systemctl enable --now "$unite" >/dev/null 2>&1 || {
            alerte "$unite n'a pas démarré."
            note "  Le journal dira pourquoi :  journalctl -u $unite -n 40 --no-pager"
        }
    done
    for unite in "$U_CYCLE.timer" "$U_BACKUP.timer" "$U_RESTORE.timer"; do
        systemctl enable --now "$unite" >/dev/null 2>&1 || alerte "$unite n'a pas été armée."
    done
    bien "Services et minuteries armés."
    note "  Le service de cycle n'est PAS activé directement : seule sa minuterie
   le déclenche. Pour digérer tout de suite, à la main :
     sudo systemctl start $U_CYCLE.service"
    return 0
}

# ---------------------------------------------------------------------------
# 203/EXEC — la panne qui ne dit pas son nom
#
# Les unités posent `User=arac`. systemd lit le fichier d'environnement en
# PID 1, puis abandonne ses privilèges AVANT d'exécuter ExecStart. Si
# l'exécutable est introuvable POUR CET UTILISATEUR, systemd rend
# `status=203/EXEC` et redémarre en boucle. Sur une machine observée : 16 350
# redémarrages, aucun message d'erreur applicatif, aucune ligne dans le
# journal de l'API — puisque l'API n'a jamais démarré.
#
# DEUX CAUSES, ET LA SECONDE NE LIT AUCUNE PERMISSION
#
#   1. la TRAVERSÉE. Un répertoire du chemin n'est pas franchissable par cet
#      utilisateur. Le cas arrive naturellement : on ouvre un shell root, on
#      clone où l'on se trouve, c'est-à-dire dans /root, qui est en 0700 sur
#      toute installation Ubuntu. Rien dans le geste n'était fautif.
#
#   2. `ProtectHome`. Ces unités le posent elles-mêmes (voir les gabarits plus
#      bas). `ProtectHome=true` ne consulte AUCUNE permission : le noyau monte
#      un tmpfs VIDE par-dessus /home ET /root pour le service. Un dépôt qui
#      vit là devient inexistant pour lui, quels que soient ses droits.
#
# La seconde cause rendait la première trompeuse : le remède « ouvrez la
# traversée » (`chmod o+x /root`) faisait passer le contrôle — `test -x` sous
# l'identité du service réussissait — et laissait la panne entière. On
# affaiblissait un répertoire privé pour rien.
#
# CE QU'ON VÉRIFIE DONC, DÉSORMAIS
#
# Pas « ce chemin est-il traversable ? », mais « CETTE UNITÉ, telle que je vais
# l'écrire, pourra-t-elle exécuter ce binaire ? ». Deux temps :
#
#   · avant tout (et donc aussi en simulation, sans root) : la traversée par
#     déduction, et la valeur de ProtectHome que l'emplacement du dépôt impose ;
#   · juste après la création des utilisateurs, avant qu'une seule unité
#     n'existe : la PREUVE, en exécutant réellement le binaire sous l'identité
#     et sous les propriétés de durcissement de l'unité (`systemd-run`).
#
# Ce qui peut être décidé sans l'utilisateur l'est (la valeur de ProtectHome).
# Ce qui est une décision — affaiblir /root, déplacer le dépôt — reste la
# sienne : on donne les deux gestes, entiers, et on ne tranche pas.
# ---------------------------------------------------------------------------

#: LE PREMIER CHEMIN QUI INTERDIT `ProtectHome=true`.
#: Rendu vide quand aucun ne le fait — auquel cas le durcissement reste plein.
_protect_home_verrou() { # chemin...
    local c
    for c in "$@"; do
        [[ -z "$c" ]] && continue
        case "$c/" in
            /home/*|/root/*) printf '%s\n' "$c"; return 0 ;;
        esac
    done
    return 0
}

#: La valeur que l'unité peut porter SANS s'interdire son propre ExecStart.
#:
#: `read-only` et non `false` : le service voit /home et /root, il ne peut
#: toujours PAS y écrire. On cède exactement ce que la lecture du binaire
#: exige, et rien de plus. Valeur éprouvée : `systemd-run --uid=arac
#: --property=ProtectHome=read-only … uvicorn --version` rend 0, là où `true`
#: rend 203.
_protect_home_valeur() { # chemin...
    if [[ -n "$(_protect_home_verrou "$@")" ]]; then printf 'read-only'
    else printf 'true'; fi
}

#: Premier composant de $1 qui n'est pas traversable par « les autres ».
#: Rendu vide si le chemin entier est traversable.
_premier_verrou() { # chemin_absolu
    local chemin="$1" cumul="" morceau mode
    while IFS= read -r morceau; do
        [[ -z "$morceau" ]] && continue
        cumul="$cumul/$morceau"
        # On lit le mode en OCTAL, pas la chaîne « drwxr-xr-x ». Raison : à la
        # place du x des autres, `ls` écrit « t » quand le sticky bit est posé
        # (/tmp est drwxrwxrwt et pourtant traversable par tous) et « T »
        # quand il l'est SANS le x. Compter des lettres se trompe donc dans
        # les deux sens ; le bit 0o001, lui, ne ment pas.
        mode="$(stat -c '%a' "$cumul" 2>/dev/null)" || continue
        (( 8#$mode & 1 )) || { printf '%s\n' "$cumul"; return 0; }
    done < <(printf '%s\n' "${chemin#/}" | tr '/' '\n')
    return 0
}

_controle_accessibilite_depot() {
    local binaire="$ARAC_VENV/bin/uvicorn" verrou="" u ph ph_verrou
    local -a coupables=()

    ph_verrou="$(_protect_home_verrou "$ARAC_HOME" "$ARAC_VENV")"
    ph="$(_protect_home_valeur "$ARAC_HOME" "$ARAC_VENV")"

    # Vérité de terrain quand les utilisateurs existent déjà (relance) :
    # `test -x` sous leur identité tranche mieux que n'importe quelle
    # déduction — il tient compte des ACL, des groupes, de tout.
    #
    # Uniquement en root, et c'est délibéré : `sudo -u` sans privilèges peut
    # réclamer un mot de passe, donc BLOQUER un contrôle qui doit rester
    # muet, ou échouer faute de terminal — et l'échec serait alors lu comme
    # « cet utilisateur ne peut pas exécuter le binaire », une panne inventée.
    if [[ $EUID -eq 0 ]]; then
        for u in "$ARAC_SERVICE_USER" "$ARAC_AGENT_USER"; do
            id -u "$u" >/dev/null 2>&1 || continue
            sudo -n -u "$u" test -x "$binaire" 2>/dev/null || coupables+=("$u")
        done
    fi

    # Déduction par les permissions : seule voie possible au tout premier
    # passage, où les utilisateurs système n'ont pas encore été créés.
    verrou="$(_premier_verrou "$ARAC_HOME")"
    [[ -z "$verrou" && ! -x "$binaire" ]] && verrou=""   # binaire absent : autre problème

    if (( ${#coupables[@]} == 0 )) && [[ -z "$verrou" ]]; then
        bien "Le dépôt est traversable par « $ARAC_SERVICE_USER » et « $ARAC_AGENT_USER »."
        _dire_protect_home "$ph" "$ph_verrou"
        return 0
    fi

    vide
    mal "$(_c 1 'Les services ne pourraient pas atteindre ce dépôt.')"
    vide
    dire "Le dépôt est ici :"
    dire "   $ARAC_HOME"
    vide
    if [[ -n "$verrou" ]]; then
        dire "Ce répertoire du chemin est fermé aux autres utilisateurs :"
        dire "   $(_c 1 "$verrou")   $(stat -c '%A %U:%G' "$verrou" 2>/dev/null)"
        vide
    fi
    if (( ${#coupables[@]} )); then
        dire "Vérifié sous leur identité : ${coupables[*]} ne peu(ven)t pas exécuter"
        dire "   $binaire"
        vide
    fi
    note "Les unités tournent sous « $ARAC_SERVICE_USER » et « $ARAC_AGENT_USER », jamais
sous root : c'est délibéré. Mais systemd abandonne ses privilèges AVANT
de lancer le programme. Un répertoire fermé sur le chemin donne alors :

    Process: … ExecStart=… (code=exited, status=203/EXEC)
    Active: activating (auto-restart)

…en boucle, sans un mot dans le journal de l'API, puisque l'API n'a
jamais démarré. Poser les unités maintenant fabriquerait cette boucle."
    vide
    dire "$(_c 1 'Deux issues. Choisissez — ce bootstrap ne tranchera pas à votre place.')"
    vide
    dire "$(_c 1 '1. Déplacer le dépôt hors d'\''un répertoire privé')  — recommandé"
    _remede_deplacer
    dire "   /opt est traversable par tous par convention. C'est là que vivent"
    dire "   les logiciels qui tournent sans session ouverte — ce qui est"
    dire "   exactement le cas d'un cerveau."
    vide
    dire "$(_c 1 '2. Ouvrir la traversée du chemin actuel')"
    if [[ -n "$verrou" ]]; then
        cmd "sudo chmod o+x $verrou
$(geste_bootstrap "--from services")"
    fi
    dire "   Attention à ce que cela veut dire : « o+x » sur un répertoire"
    dire "   n'autorise pas à le LISTER, seulement à le TRAVERSER. Sur"
    dire "   ${verrou:-ce chemin}, cela reste un affaiblissement d'un répertoire"
    dire "   privé, et c'est pourquoi ce n'est pas la voie recommandée."
    vide
    note "Et sachez pourquoi ce geste, SEUL, ne suffisait pas : ces unités
posent ProtectHome, qui ne lit aucune permission. Sous ProtectHome=true,
systemd monte un tmpfs VIDE par-dessus /home et /root pour le service —
un « chmod o+x /root » faisait donc passer ce contrôle et laissait la
boucle 203/EXEC entière. Ce bootstrap écrit désormais
ProtectHome=$ph dans les unités, ce qui traite cette moitié-là ; la
traversée, elle, reste à votre main."
    vide
    note "Aucune unité n'a été écrite. Rien n'est cassé, rien n'est à défaire :
réparez le chemin et relancez, cette étape reprendra telle quelle."
    vide
    return 1
}

#: LE REMÈDE QUI NE DOIT PAS CASSER CE QU'IL RÉPARE.
#:
#: `mv` déplace le dépôt, et laisse derrière lui un environnement Python MORT :
#: les scripts de `.venv/bin` (pip, alembic, uvicorn…) portent tous un shebang
#: ABSOLU vers l'ancien chemin. Après le déplacement, chacun rend
#:     …/uvicorn: cannot execute: required file not found      (code 127)
#: Un venv ne se déplace pas : il se refait. Le taire revenait à donner, comme
#: geste « recommandé », une commande qui remplaçait une panne par une autre.
_remede_deplacer() {
    local n=0
    if [[ -d "$ARAC_VENV/bin" ]]; then
        n="$(grep -ls "^#!$ARAC_VENV/" "$ARAC_VENV"/bin/* 2>/dev/null | wc -l)"
    fi
    cmd "sudo mv $ARAC_HOME /opt/${ARAC_DB}
cd /opt/${ARAC_DB}
sudo python3 -m venv --clear .venv
sudo .venv/bin/pip install -r requirements.txt
$(geste_bootstrap "--from services")"
    note "   Les trois lignes du milieu ne sont pas facultatives : un
   environnement Python n'est PAS déplaçable. ${n:-0} script(s) de
   $ARAC_VENV/bin portent le chemin absolu de l'emplacement actuel dans
   leur première ligne ; après le mv, pip, alembic et uvicorn rendent
   « required file not found » (code 127). On le refait sur place —
   c'est une minute, et c'est la seule façon que le geste tienne."
}

#: Le durcissement qu'on s'apprête à écrire, dit AVANT de l'écrire.
_dire_protect_home() { # valeur verrou
    [[ -z "$2" ]] && return 0
    vide
    alerte "Les unités porteront $(_c 1 "ProtectHome=$1"), et non « true »."
    note "  Parce que le dépôt vit sous $2.
  ProtectHome=true ne consulte aucune permission : systemd monte un
  tmpfs VIDE par-dessus /home et /root pour le service, qui ne trouve
  alors plus son propre exécutable — 203/EXEC, en boucle, sans un mot.
  « read-only » lui rend la LECTURE de ces arborescences, jamais
  l'écriture : c'est exactement ce que l'exécution du binaire exige, et
  rien de plus.
  Pour garder le durcissement plein, installez le dépôt ailleurs —
  /opt ou /srv — et relancez : ProtectHome=true sera réécrit."
}

# ---------------------------------------------------------------------------
# LA PREUVE — exécuter le binaire comme systemd l'exécutera
#
# Tout ce qui précède est de la DÉDUCTION. Elle est utile (elle tourne sans
# root, donc en simulation), et elle est incomplète par construction : elle ne
# connaît que ce à quoi elle a pensé. La seule mesure qui ne se trompe pas est
# de faire tourner le binaire sous l'identité ET sous les propriétés de l'unité
# qu'on s'apprête à écrire. `systemd-run` le permet, sans poser aucune unité.
#
# Il faut pour cela que les utilisateurs système existent : ce contrôle vient
# donc APRÈS leur création, et avant la première ligne écrite dans /etc.
# ---------------------------------------------------------------------------

_controle_execution_sous_unite() {
    local ph rc=0 sortie u binaire cible
    ph="$(_protect_home_valeur "$ARAC_HOME" "$ARAC_VENV")"

    if ! command -v systemd-run >/dev/null 2>&1; then
        alerte "Exécution réelle NON MESURÉE : systemd-run est absent."
        note "  On ne peut donc pas prouver ici que les unités atteindront leur
   binaire. Si elles restent en « activating », le journal dira 203/EXEC :
     journalctl -u $U_API -n 40 --no-pager"
        return 0
    fi

    local -a essais=()
    id -u "$ARAC_SERVICE_USER" >/dev/null 2>&1 && \
        essais+=("$ARAC_SERVICE_USER:$ARAC_VENV/bin/uvicorn")
    id -u "$ARAC_AGENT_USER" >/dev/null 2>&1 && \
        essais+=("$ARAC_AGENT_USER:$ARAC_VENV/bin/python")
    if (( ${#essais[@]} == 0 )); then
        alerte "Exécution réelle NON MESURÉE : les utilisateurs système n'existent pas encore."
        return 0
    fi

    local sonde statut
    for cible in "${essais[@]}"; do
        u="${cible%%:*}"; binaire="${cible#*:}"
        rc=0; statut=""
        sonde="arac-sonde-$$-$u"
        # PAS de `--collect`, et c'est délibéré : `systemd-run --wait` ne rend
        # que 1 quand le service a échoué, quel que soit le motif. Le code qui
        # COMPTE — celui qu'on lira dans journalctl, celui qu'on cherchera sur
        # le web — est `status=203/EXEC`, et il n'est lisible que sur l'unité,
        # avant qu'elle ne soit déchargée. On la décharge donc nous-mêmes,
        # juste après l'avoir interrogée.
        sortie="$(systemd-run --quiet --wait --service-type=oneshot \
            --unit="$sonde" \
            --uid="$u" \
            --property=ProtectHome="$ph" \
            --property=ProtectSystem=strict \
            --property=NoNewPrivileges=true \
            --property=PrivateTmp=true \
            --property=WorkingDirectory="$ARAC_HOME" \
            "$binaire" --version 2>&1)" || rc=$?
        statut="$(systemctl show "$sonde.service" -p ExecMainStatus --value 2>/dev/null || true)"
        systemctl stop "$sonde.service"        >/dev/null 2>&1 || true
        systemctl reset-failed "$sonde.service" >/dev/null 2>&1 || true

        (( rc == 0 )) && continue

        # systemd-run qui n'a pas pu PARLER à systemd n'a rien mesuré : le
        # confondre avec un service qui a échoué inventerait une panne.
        case "$sortie" in
            *"Failed to connect"*|*"Access denied"*|*"Interactive authentication"*|\
            *"Permission denied"*|*"not been booted"*)
                alerte "Exécution réelle NON MESURÉE sous « $u » : systemd-run n'a pas pu s'exécuter."
                note "  $(_premiere_ligne_sondage "$sortie")"
                return 0 ;;
        esac

        vide
        mal "$(_c 1 "L'unité, telle qu'elle serait écrite, ne peut pas exécuter son binaire.")"
        vide
        dire "Mesuré — pas déduit — avec la commande suivante :"
        cmd "systemd-run --wait --service-type=oneshot \\
    --uid=$u \\
    --property=ProtectHome=$ph \\
    --property=ProtectSystem=strict \\
    --property=WorkingDirectory=$ARAC_HOME \\
    $binaire --version"
        dire "   → systemd-run rend $(_c 1 "$rc")${statut:+, et le service a rendu status=$(_c 1 "$statut")}"
        [[ -n "$sortie" ]] && note "   $(_premiere_ligne_sondage "$sortie")"
        vide
        note "C'est exactement ce que systemd fera au démarrage de $U_API et de
$U_CYCLE. status=203 : l'exécutable est introuvable POUR CET UTILISATEUR
— traversée fermée, ou arborescence masquée par ProtectHome.
status=200 : le WorkingDirectory est inatteignable. Dans les deux cas,
l'unité bouclerait en « activating (auto-restart) » sans une ligne de
journal applicatif — puisque le programme n'aurait jamais démarré.

Aucune unité n'a été écrite."
        vide
        dire "$(_c 1 'Le geste — déplacer le dépôt là où un service peut vivre :')"
        _remede_deplacer
        vide
        return 1
    done

    bien "Exécution éprouvée sous « ${essais[0]%%:*} » avec ProtectHome=$ph : le binaire répond."
    return 0
}

#: La première ligne utile d'une sortie de sondage. Aucun secret n'y transite :
#: systemd nomme l'unité, l'utilisateur et le code, jamais un mot de passe.
_premiere_ligne_sondage() { printf '%s' "${1%%$'\n'*}"; }

# ---------------------------------------------------------------------------
# LES PORTS — un numéro appartient à la machine, pas à ce cerveau
#
# 8000 et 8100 sont les valeurs par défaut de TOUS les cerveaux. Un port déjà
# tenu produit une boucle de redémarrage muette côté systemd — « address
# already in use » n'apparaît que dans le journal de l'unité — et le contrôle
# final n'en sait dire que « NON CONTRÔLÉ ». On le constate avant.
# ---------------------------------------------------------------------------

_controle_ports_libres() {
    command -v ss >/dev/null 2>&1 || return 0
    local -a occupes=()
    local entree nom port unite ligne
    for entree in "API:$ARAC_API_PORT:$U_API.service" \
                  "cockpit:$ARAC_COCKPIT_PORT:$U_COCKPIT.service"; do
        nom="${entree%%:*}"; entree="${entree#*:}"
        port="${entree%%:*}"; unite="${entree#*:}"
        ligne="$(ss -ltnHp "sport = :$port" 2>/dev/null | head -1)"
        [[ -z "$ligne" ]] && continue
        # Si c'est NOTRE unité qui le tient déjà, ce n'est pas un obstacle :
        # c'est une réinstallation. Si on ne peut pas le savoir (ss sans
        # droits ne montre aucun propriétaire), on ne conclut rien non plus.
        socket_appartient_a "$ligne" "$unite"
        case "$?" in 0|2) continue ;; esac
        occupes+=("$nom|$port|$ligne")
    done
    (( ${#occupes[@]} == 0 )) && return 0

    vide
    mal "$(_c 1 'Un port que ces unités veulent est déjà tenu par autre chose.')"
    vide
    for entree in "${occupes[@]}"; do
        nom="${entree%%|*}"; entree="${entree#*|}"
        port="${entree%%|*}"; ligne="${entree#*|}"
        dire "   $(pad "$nom" 10) port $(_c 1 "$port")"
        note "      $ligne"
    done
    vide
    note "Un service qui ne peut pas ouvrir sa socket meurt à la seconde ligne :

    ERROR: [Errno 98] error while attempting to bind on address
           ('127.0.0.1', $ARAC_COCKPIT_PORT): address already in use

…puis redémarre toutes les cinq secondes, indéfiniment. Et pendant ce
temps le port RÉPOND — servi par celui qui le tient. Un contrôle de
santé naïf décernerait donc un ✓ à un service mort. C'est exactement
ce qui est arrivé, et c'est pour cela qu'aucune unité ne sera écrite."
    vide
    note "Ce contrôle ne devrait jamais se déclencher : l'étape 2 a constaté ces
deux numéros libres et les a retenus. S'il parle, c'est que quelque
chose a lié le port DEPUIS — un autre bootstrap lancé en parallèle, ou
un service qui vient de démarrer. C'est le dernier filet, volontairement
redondant : entre constater et écrire, il s'écoule des minutes."
    vide
    dire "$(_c 1 'Deux issues :')"
    cmd "# 1. libérer le port (identifiez le tenant ci-dessus), puis :
$(geste_bootstrap "--from services")

# 2. ou laisser l'étape 2 en attribuer de libres :
$(geste_bootstrap "--from config")"
    vide
    note "Les numéros retenus sont écrits dans la configuration de ce cerveau —
unités, contrôle final et tunnel SSH de l'épilogue les reprennent.
Aucune unité n'a été écrite."
    vide
    return 1
}

# ---------------------------------------------------------------------------
# UN DÉPÔT, UN CERVEAU — le dernier nom partagé, et le plus coûteux
#
# Les rôles, les ports, les unités, les bases, les journaux, les sauvegardes et
# l'état sont désormais nommés par cerveau. Il reste UNE chose qui ne l'est
# pas, et elle ne vit pas dans /etc : c'est le DÉPÔT lui-même.
#
# L'étape 6 engendre `app/schemas/scope_generated.py` et `db/seeds/scopes.sql`
# DANS le dépôt, depuis config/scopes.toml. Ces deux fichiers appartiennent
# donc au clone, pas au cerveau. Installer un second cerveau depuis le même
# clone les RÉÉCRIT avec la taxonomie du second — et les unités du premier,
# qui portent `WorkingDirectory=<ce dépôt>`, se mettent à valider les scopes
# du premier contre l'énumération du second.
#
# Constaté, et c'est pour cela que ce contrôle existe : deux cerveaux servis
# depuis un même clone, chacun avec sa base et sa taxonomie correctement
# semées — et l'API du premier refusant en 422 les domaines de sa propre
# mémoire, parce que le fichier Python qu'elle importe décrit ceux du second.
# Rien n'échoue à l'installation. Tout échoue à la première écriture, et le
# message parle d'un scope invalide, pas d'une installation partagée.
#
# Corriger la cause demanderait de sortir ces deux fichiers du dépôt — c'est
# une décision d'architecture qui touche `app/`, pas ce bootstrap. Ce qu'on
# peut faire ici, et qu'on fait : REFUSER de poser la seconde installation, et
# dire exactement pourquoi et comment s'en sortir. Un refus qui explique vaut
# mieux qu'une panne qui ment.
_controle_depot_non_partage() {
    command -v systemctl >/dev/null 2>&1 || return 0
    local -a etrangeres=() u autre
    while IFS= read -r u; do
        [[ -z "$u" ]] && continue
        [[ "$u" == "$U_API.service" || "$u" == "$U_COCKPIT.service" ]] && continue
        [[ "$(systemctl show -p WorkingDirectory --value "$u" 2>/dev/null)" == "$ARAC_HOME" ]] \
            && etrangeres+=("$u")
    done < <(systemctl list-unit-files --no-legend 'arac-*-api.service' 'arac-*-cockpit.service' 2>/dev/null | awk '{print $1}')

    (( ${#etrangeres[@]} == 0 )) && return 0

    vide
    mal "$(_c 1 'REFUS — un autre cerveau est déjà servi depuis ce dépôt.')"
    vide
    dire "Ces unités portent WorkingDirectory=$ARAC_HOME :"
    for u in "${etrangeres[@]}"; do dire "   $u"; done
    vide
    dire "$(_c 1 'POURQUOI CE N'\''EST PAS UN DÉTAIL DE RANGEMENT')"
    note "L'étape 6 écrirait, DANS ce dépôt, la taxonomie de « $ARAC_DB » :
    $ARAC_HOME/app/schemas/scope_generated.py
    $ARAC_HOME/db/seeds/scopes.sql
Ces fichiers appartiennent au dépôt, pas au cerveau. Ils écraseraient
ceux du cerveau installé avant, dont les services lisent le MÊME dossier.

Conséquence, si l'on continuait : l'autre cerveau garderait sa base,
ses rôles, ses ports et sa mémoire intacts — mais son API validerait
les domaines contre VOTRE taxonomie. Ses propres scopes deviendraient
invalides à l'écriture, en 422, avec un message parlant d'un domaine
inconnu et non d'une installation partagée."
    vide
    dire "$(_c 1 'LE GESTE — un clone par cerveau')"
    cmd "sudo git clone <dépôt> /opt/$ARAC_DB
cd /opt/$ARAC_DB
python3 bootstrap/wizard.py          # la description de CE cerveau
$(geste_bootstrap)"
    vide
    note "Le reste — base, rôles, secrets, unités, journaux, sauvegardes — est
déjà nommé par cerveau et cohabite sans peine sur une machine. C'est le
DÉPÔT, et lui seul, qui ne se partage pas.

RIEN N'A ÉTÉ ÉCRIT. Ce refus tombe à l'étape 2, avant la base, avant les
migrations, et surtout avant que l'étape 6 n'engendre la taxonomie dans
ce dépôt. Le cerveau installé avant garde la sienne, intacte : vous
n'avez rien à réparer chez lui."
    vide
    return 1
}

_creer_utilisateur() { # nom home
    id -u "$1" >/dev/null 2>&1 && return 0
    # --no-create-home : les dossiers sont posés juste après, avec les bons
    # droits. useradd n'a pas à décider de leur mode.
    #
    # Le groupe : `useradd --system` en crée un du même nom (USERGROUPS_ENAB).
    # C'est ce qui permet à `Group=$ARAC_SERVICE_USER` de ne désigner que ce
    # cerveau. Un groupe commun rouvrirait, par le bit de groupe des 0750,
    # exactement la porte que le compte propre vient de fermer.
    useradd --system --shell /usr/sbin/nologin --home-dir "$2" --no-create-home "$1"
    note "  Utilisateur système créé : $1"
}

#: Donne un dossier ET SON CONTENU au compte de ce cerveau, si ce n'est pas
#: déjà le cas. Muet quand il n'y a rien à faire — le cas normal.
#:
#: Le seul cas où cela sert : une installation posée quand les comptes étaient
#: communs à la machine, rejouée après. `install -d` aurait alors corrigé le
#: dossier de tête et laissé les journaux, l'état et le foyer d'agent au compte
#: partagé, c'est-à-dire lisibles par le cerveau voisin. Un cloisonnement qui
#: ne vaut que pour les fichiers créés après la correction n'est pas un
#: cloisonnement.
_reprendre_la_propriete() { # dossier compte
    local dossier="$1" compte="$2"
    [[ -d "$dossier" ]] || return 0
    # `install -d` vient de corriger le dossier de tête ; on cherche donc le
    # premier ÉLÉMENT, à n'importe quelle profondeur, qui appartient encore à
    # quelqu'un d'autre. `-print -quit` s'arrête au premier : on ne parcourt
    # l'arborescence entière que le jour où il y a effectivement à reprendre.
    if [[ -n "$(find "$dossier" \! -user "$compte" -print -quit 2>/dev/null)" ]]; then
        chown -R "$compte:$compte" "$dossier"
        note "  $dossier — propriété reprise par « $compte »"
    fi
}

_poser_unite() { # nom fonction
    local cible="$ARAC_UNITS_DIR/$1" tmp
    tmp="$(mktemp)"
    "$2" > "$tmp"
    if [[ -f "$cible" ]] && cmp -s "$tmp" "$cible"; then
        rm -f "$tmp"; note "  $1 — inchangée"; return 0
    fi
    if [[ -f "$cible" ]]; then
        cp -a "$cible" "$cible.avant-$(date -u +%Y%m%dT%H%M%SZ)"
        note "  $1 — remplacée (l'ancienne est conservée à côté)"
    fi
    install -m 0644 -o root -g root "$tmp" "$cible"
    rm -f "$tmp"
    bien "$1"
}

# --- Les gabarits -----------------------------------------------------------

_entete_unite() { # description [dependance_supplementaire]
    cat <<EOF
# Unité engendrée par bootstrap/bootstrap.sh pour le cerveau « $BRAIN_NOM ».
# Ne l'éditez pas à la main : elle sera réécrite au prochain bootstrap.
# Pour la modifier durablement, utilisez un drop-in :
#   sudo systemctl edit ${PREFIXE_UNITE}-...

[Unit]
Description=$1
Requires=postgresql.service${2:+ $2}
After=postgresql.service network.target${2:+ $2}
EOF
}

_unite_api() {
    local ph; ph="$(_protect_home_valeur "$ARAC_HOME" "$ARAC_VENV")"
    _entete_unite "ARAC ($BRAIN_NOM) — API, en boucle locale"
    cat <<EOF

[Service]
Type=simple
User=$ARAC_SERVICE_USER
Group=$ARAC_SERVICE_USER

# systemd lit ce fichier en PID 1 (root) AVANT d'abandonner ses privilèges.
# L'utilisateur $ARAC_SERVICE_USER n'a jamais accès au fichier lui-même.
EnvironmentFile=$ARAC_ENV_FILE
Environment=ARAC_HOME=$ARAC_HOME
Environment=ARAC_NODE_ID=$ARAC_NODE_ID
Environment=PYTHONPATH=$ARAC_HOME
# OÙ CE SERVICE A LE DROIT D'ÉCRIRE.
#
# \`ProtectSystem=strict\` ferme TOUT le disque en écriture. Rien ne le rouvrait
# pour ce service : il sert des lectures sans broncher et échoue à la première
# écriture d'état — donc plus tard, ailleurs, sous un autre nom. Or le moteur
# place par défaut son état vivant sous \$ARAC_HOME/var, c'est-à-dire DANS le
# dépôt : un dossier de code n'a aucune raison d'être inscriptible par un
# service, et \`ProtectSystem=strict\` avait raison de le refuser.
#
# \`StateDirectory\` est le mécanisme de systemd pour exactement cela : il crée
# le dossier, le donne à User=, et l'ajoute aux chemins inscriptibles. On ne
# desserre donc aucun durcissement — on déplace l'état là où il doit vivre.
# Il est distinct du HOME du cycle, qui tourne sous un AUTRE utilisateur :
# deux identités séparées ne partagent pas un dossier inscriptible, sinon la
# séparation des rôles s'arrête à la base de données.
StateDirectory=arac/$ARAC_DB-service/data arac/$ARAC_DB-service/var
# 0700 ET NON 0755, QUI EST LE DÉFAUT DE systemd.
# Le défaut rendait l'état vivant de ce cerveau lisible par TOUT compte de
# la machine — y compris celui du cerveau voisin. Le dossier appartient à
# User=, qui est désormais propre à ce cerveau : le mode ferme ce que le
# propriétaire distingue.
StateDirectoryMode=0700
Environment=ARAC_DATA_DIR=/var/lib/arac/$ARAC_DB-service/data
Environment=ARAC_VAR_DIR=/var/lib/arac/$ARAC_DB-service/var

WorkingDirectory=$ARAC_HOME
# 127.0.0.1 : jamais 0.0.0.0. On atteint l'API par un tunnel SSH, pas par
# l'Internet. C'est ce qui rend l'absence de TLS acceptable ici.
ExecStart=$ARAC_VENV/bin/uvicorn $ARAC_API_APP \\
    --host 127.0.0.1 --port $ARAC_API_PORT --no-access-log --workers 1

Restart=on-failure
RestartSec=5
SyslogIdentifier=$U_API
StandardOutput=journal
StandardError=journal

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
# CE QUE LE SERVICE VOIT DE /home ET DE /root.
#
# \`ProtectHome\` ne consulte AUCUNE permission : sous « true », le noyau monte
# un tmpfs VIDE par-dessus /home et /root pour ce service. Un dépôt qui vit là
# devient inexistant POUR LUI — l'ExecStart ci-dessus est introuvable, systemd
# rend 203/EXEC et redémarre en boucle, sans un mot dans le journal applicatif
# puisque le programme n'a jamais démarré.
#
# La valeur est calculée depuis l'emplacement RÉEL du dépôt (voir
# _protect_home_valeur) : « true » partout où c'est possible, « read-only »
# quand le dépôt vit sous /home ou /root. « read-only » rend la LECTURE de ces
# arborescences, jamais l'écriture : on cède exactement ce que l'exécution du
# binaire exige, et rien de plus.
ProtectHome=$ph
ProtectKernelTunables=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
# L'API n'avait AUCUN chemin inscriptible : ni celui-ci, ni StateDirectory.
ReadWritePaths=$ARAC_LOG_DIR

[Install]
WantedBy=multi-user.target
EOF
}

_unite_cockpit() {
    local ph; ph="$(_protect_home_valeur "$ARAC_HOME" "$ARAC_VENV")"
    _entete_unite "ARAC ($BRAIN_NOM) — cockpit, LECTURE SEULE"
    cat <<EOF

[Service]
Type=simple
User=$ARAC_SERVICE_USER
Group=$ARAC_SERVICE_USER
SupplementaryGroups=systemd-journal

EnvironmentFile=$ARAC_ENV_FILE
# Le tiret : fichier facultatif. Sans lui le cockpit démarre mais refuse
# toute connexion — fermé par défaut, jamais ouvert par accident.
EnvironmentFile=-$ARAC_SECRETS_COCKPIT
Environment=ARAC_HOME=$ARAC_HOME
Environment=PYTHONPATH=$ARAC_HOME
# DE QUEL CERVEAU CE COCKPIT EST-IL LE COCKPIT ?
#
# Il ne le savait pas. Le collecteur brain_api retombait sur 127.0.0.1:8000 et
# system_metrics demandait l'état de « arac-api » — deux noms qui, sur
# une machine à deux cerveaux, désignent le VOISIN. Un cockpit affichait donc
# la taxonomie et la santé d'un autre, sans jamais mentir explicitement.
#
# Ces trois lignes sont la réponse, et elles doivent être portées par l'unité
# elle-même : le fichier d'environnement est partagé avec l'API, l'unité est
# ce qui distingue ce processus-ci.
Environment=ARAC_API_BASE=http://127.0.0.1:$ARAC_API_PORT
Environment=ARAC_UNIT_API=$U_API
Environment=ARAC_UNIT_COCKPIT=$U_COCKPIT
Environment=ARAC_LOG_DIR=$ARAC_LOG_DIR
# OÙ CE SERVICE A LE DROIT D'ÉCRIRE.
#
# \`ProtectSystem=strict\` ferme TOUT le disque en écriture. Rien ne le rouvrait
# pour ce service : il sert des lectures sans broncher et échoue à la première
# écriture d'état — donc plus tard, ailleurs, sous un autre nom. Or le moteur
# place par défaut son état vivant sous \$ARAC_HOME/var, c'est-à-dire DANS le
# dépôt : un dossier de code n'a aucune raison d'être inscriptible par un
# service, et \`ProtectSystem=strict\` avait raison de le refuser.
#
# \`StateDirectory\` est le mécanisme de systemd pour exactement cela : il crée
# le dossier, le donne à User=, et l'ajoute aux chemins inscriptibles. On ne
# desserre donc aucun durcissement — on déplace l'état là où il doit vivre.
# Il est distinct du HOME du cycle, qui tourne sous un AUTRE utilisateur :
# deux identités séparées ne partagent pas un dossier inscriptible, sinon la
# séparation des rôles s'arrête à la base de données.
StateDirectory=arac/$ARAC_DB-service/data arac/$ARAC_DB-service/var
# 0700 ET NON 0755, QUI EST LE DÉFAUT DE systemd.
# Le défaut rendait l'état vivant de ce cerveau lisible par TOUT compte de
# la machine — y compris celui du cerveau voisin. Le dossier appartient à
# User=, qui est désormais propre à ce cerveau : le mode ferme ce que le
# propriétaire distingue.
StateDirectoryMode=0700
Environment=ARAC_DATA_DIR=/var/lib/arac/$ARAC_DB-service/data
Environment=ARAC_VAR_DIR=/var/lib/arac/$ARAC_DB-service/var

WorkingDirectory=$ARAC_HOME
ExecStart=$ARAC_VENV/bin/uvicorn $ARAC_COCKPIT_APP \\
    --host 127.0.0.1 --port $ARAC_COCKPIT_PORT --no-access-log --no-proxy-headers --workers 1

Restart=on-failure
RestartSec=5
SyslogIdentifier=$U_COCKPIT
StandardOutput=journal
StandardError=journal

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
# CE QUE LE SERVICE VOIT DE /home ET DE /root.
#
# \`ProtectHome\` ne consulte AUCUNE permission : sous « true », le noyau monte
# un tmpfs VIDE par-dessus /home et /root pour ce service. Un dépôt qui vit là
# devient inexistant POUR LUI — l'ExecStart ci-dessus est introuvable, systemd
# rend 203/EXEC et redémarre en boucle, sans un mot dans le journal applicatif
# puisque le programme n'a jamais démarré.
#
# La valeur est calculée depuis l'emplacement RÉEL du dépôt (voir
# _protect_home_valeur) : « true » partout où c'est possible, « read-only »
# quand le dépôt vit sous /home ou /root. « read-only » rend la LECTURE de ces
# arborescences, jamais l'écriture : on cède exactement ce que l'exécution du
# binaire exige, et rien de plus.
ProtectHome=$ph
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
ReadWritePaths=$ARAC_LOG_DIR
MemoryMax=256M

[Install]
WantedBy=multi-user.target
EOF
}

_unite_cycle() {
    local ph; ph="$(_protect_home_valeur "$ARAC_HOME" "$ARAC_VENV")"
    _entete_unite "ARAC ($BRAIN_NOM) — cycle de digestion (borné, oneshot)" "$U_API.service"
    cat <<EOF

# Anti-emballement : dix démarrages par heure au maximum. Combiné au
# Type=oneshot (aucun redémarrage automatique), cela borne tout scénario de
# boucle : le cerveau ne peut pas se mettre à penser en rond.
StartLimitIntervalSec=3600
StartLimitBurst=10

[Service]
Type=oneshot
User=$ARAC_AGENT_USER
Group=$ARAC_AGENT_USER

EnvironmentFile=$ARAC_ENV_FILE
Environment=ARAC_HOME=$ARAC_HOME
Environment=ARAC_NODE_ID=$ARAC_NODE_ID-cycle
Environment=ARAC_API_URL=http://127.0.0.1:$ARAC_API_PORT
Environment=PYTHONPATH=$ARAC_HOME
Environment=HOME=$ARAC_AGENT_HOME

# OÙ LE CYCLE A LE DROIT D'ÉCRIRE.
#
# \`ProtectSystem=strict\` (plus bas) rend TOUT le disque en lecture seule, sauf
# ce que \`ReadWritePaths\` rouvre. Or le moteur place par défaut son verrou de
# cycle, son registre de dépense et le HOME de l'outil de curation sous
# \$ARAC_HOME/data et \$ARAC_HOME/var — c'est-à-dire dans le dépôt, donc en
# lecture seule. Le cycle mourait à sa toute première ligne :
#     OSError: [Errno 30] Read-only file system: '$ARAC_HOME/data'
# …avant même d'ouvrir la base, donc sans jamais laisser de trace en base.
#
# On ne relâche PAS le durcissement pour autant : on déplace l'état vivant là
# où il doit être, sous le HOME de l'utilisateur du cycle, déjà rouvert
# ci-dessous. Un dépôt de code n'a aucune raison d'être inscriptible par un
# service — c'est même exactement ce que \`ProtectSystem=strict\` cherche à
# empêcher, et il avait raison.
Environment=ARAC_DATA_DIR=$ARAC_AGENT_HOME/data
Environment=ARAC_VAR_DIR=$ARAC_AGENT_HOME/var
# Le verrou de cycle DOIT vivre sous le dossier d'état vivant : \`runner_lock\`
# refuse tout verrou posé ailleurs (« un verrou posé ailleurs est un verrou
# qu'on oublie »), et il a raison. Or le dossier d'exécution se déduit par
# défaut de ARAC_DATA_DIR, donc du mauvais côté de cette frontière. On le
# nomme explicitement plutôt que d'élargir la zone permise : c'est la
# contrainte du moteur qui est juste, c'est le chemin par défaut qui ne l'est
# pas une fois l'état vivant déplacé hors du dépôt.
Environment=ARAC_BRAIN_RUNTIME_DIR=$ARAC_AGENT_HOME/var/.arac-runtime

WorkingDirectory=$ARAC_HOME
ExecStart=$ARAC_VENV/bin/python -m $ARAC_CYCLE_MODULE

# Un cycle qui dure vingt minutes est un cycle qui a mal tourné.
TimeoutStartSec=1200
KillSignal=SIGTERM
SyslogIdentifier=$U_CYCLE
StandardOutput=journal
StandardError=journal

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
# CE QUE LE SERVICE VOIT DE /home ET DE /root.
#
# \`ProtectHome\` ne consulte AUCUNE permission : sous « true », le noyau monte
# un tmpfs VIDE par-dessus /home et /root pour ce service. Un dépôt qui vit là
# devient inexistant POUR LUI — l'ExecStart ci-dessus est introuvable, systemd
# rend 203/EXEC et redémarre en boucle, sans un mot dans le journal applicatif
# puisque le programme n'a jamais démarré.
#
# La valeur est calculée depuis l'emplacement RÉEL du dépôt (voir
# _protect_home_valeur) : « true » partout où c'est possible, « read-only »
# quand le dépôt vit sous /home ou /root. « read-only » rend la LECTURE de ces
# arborescences, jamais l'écriture : on cède exactement ce que l'exécution du
# binaire exige, et rien de plus.
ProtectHome=$ph
ReadWritePaths=$ARAC_AGENT_HOME $ARAC_LOG_DIR

# Pas de section [Install] : ce service est déclenché EXCLUSIVEMENT par sa
# minuterie, ou à la main. L'activer directement n'aurait aucun sens.
EOF
}

_unite_cycle_timer() {
    cat <<EOF
# Minuterie engendrée par bootstrap/bootstrap.sh — cerveau « $BRAIN_NOM ».

[Unit]
Description=ARAC ($BRAIN_NOM) — cadence circadienne de la digestion

[Timer]
EOF
    local h
    for h in $ARAC_CYCLES; do
        printf 'OnCalendar=*-*-* %s:00 %s\n' "$h" "$ARAC_CYCLE_TZ"
    done
    cat <<EOF

# Un seul rattrapage après un arrêt machine, jamais une avalanche.
Persistent=true
RandomizedDelaySec=120
Unit=$U_CYCLE.service

[Install]
WantedBy=timers.target
EOF
}

_unite_backup() {
    _entete_unite "ARAC ($BRAIN_NOM) — sauvegarde de la base"
    cat <<'EOF_HEAD'

[Service]
Type=oneshot
User=root
EOF_HEAD
    cat <<EOF
EnvironmentFile=$ARAC_ENV_FILE
WorkingDirectory=$ARAC_HOME
UMask=0077

# IL N'Y A PLUS QU'UNE SEULE SAUVEGARDE DANS CE DÉPÔT, ET C'EST LA RAISON
# D'ÊTRE DE CETTE LIGNE.
#
# Cette unité inlinait son propre \`pg_dump -Fc\` — la base ENTIÈRE, extensions
# comprises. \`ops/backup.sh\`, lui, dumpe \`--schema=\$ARAC_DB_SCHEMA\`. Les deux
# produisaient donc deux objets différents sous le même nom, et seul le second
# se restaurait : le dump de l'unité porte deux entrées
# \`COMMENT - EXTENSION\` (vector, pg_trgm), et \`COMMENT ON EXTENSION\` exige
# d'être PROPRIÉTAIRE de l'extension. Or \`ops/restore_verify.sh\` restaure —
# délibérément — sous le rôle d'administration, qui n'est pas superutilisateur.
# Il rendait donc « le dump ne se restaure pas. Le coffre est vide. » sur le
# SEUL dump qu'une installation par ce bootstrap produise. Mesuré ici même.
#
# CE QU'ON GAGNE EN PRIME, et qu'aucune ligne inline ne pouvait donner :
# les deux planchers de sincérité (absolu et relatif à la médiane), le
# contrôle du sommaire (les tables vitales sont-elles réellement dedans ?),
# l'écriture en \`.partial\` puis renommage, le chiffrement au repos si vous
# posez des destinataires age, la rotation APRÈS le succès et jamais avant,
# et le registre des tailles qui permet aux seuils de se calibrer seuls.
#
# Rétention : $ARAC_BACKUP_RETENTION jours, ET un plancher de 3 dumps gardés quoi
# qu'il arrive. Au-delà, les dumps sont SUPPRIMÉS — après un dump réussi.
Environment=ARAC_HOME=$ARAC_HOME
Environment=ARAC_ENV_FILE=$ARAC_ENV_FILE
Environment=ARAC_BACKUP_RETENTION_DAYS=$ARAC_BACKUP_RETENTION
ExecStart=$ARAC_HOME/ops/backup.sh

SyslogIdentifier=$U_BACKUP
StandardOutput=journal
StandardError=journal
EOF
}

# ---------------------------------------------------------------------------
# LA RESTAURATION VÉRIFIÉE — la seule unité qui rend la première phrase vraie
# ---------------------------------------------------------------------------
#
# `docs/SAUVEGARDE.md` ouvre sur « une sauvegarde qui n'a jamais été restaurée
# n'est pas une sauvegarde ». Le bootstrap posait la sauvegarde et PAS la
# restauration : la phrase restait un slogan, et `ops/install_check.sh`
# répondait, sur toute installation, « aucune restauration n'a jamais été
# vérifiée — vos dumps sont une hypothèse. Aucun minuteur ne le fait à votre
# place ». C'était exact, et c'était le défaut.
#
# CE QUE CETTE UNITÉ NE FAIT PAS : elle ne restaure RIEN par-dessus le cerveau
# vivant. `ops/restore_verify.sh` crée une base jetable au nom horodaté, y
# restaure le dump le plus récent, compte, compare avec le vivant, puis détruit
# ce qu'il a créé — et refuse de viser une base qu'il n'a pas créée lui-même.
#
# « SANS PRIVILÈGE ÉLEVÉ » DÉSIGNE POSTGRESQL, PAS LE SYSTÈME DE FICHIERS, ET
# LA DISTINCTION EST TOUT LE PROPOS.
#
# Côté base : ce contrôle ne demande AUCUN superutilisateur PostgreSQL. Il se
# connecte par le DSN d'administration de CE cerveau — qui a CREATEDB et
# possède le gabarit — et rien d'autre. Le faire tourner sous `postgres` toutes
# les semaines pour la seule raison que pgvector n'est pas « trusted » serait
# exactement le geste que le gabarit existe pour éviter.
#
# Côté disque : `User=root`, comme l'unité de sauvegarde et pour la même raison
# qu'elle — le coffre est en 0700 root et les dumps en 0600 root, parce qu'un
# dump est le cerveau entier en clair. Ouvrir ce répertoire à un compte de
# service pour éviter d'écrire « root » ici serait échanger un mot contre une
# lecture réelle.
_unite_restauration() {
    _entete_unite "ARAC ($BRAIN_NOM) — restauration vérifiée (base jetable)"
    cat <<EOF

[Service]
Type=oneshot
User=root
EnvironmentFile=$ARAC_ENV_FILE
WorkingDirectory=$ARAC_HOME
UMask=0077
Environment=ARAC_HOME=$ARAC_HOME
Environment=ARAC_ENV_FILE=$ARAC_ENV_FILE
ExecStart=$ARAC_HOME/ops/restore_verify.sh

# CODE 2 = « restauré, preuve PARTIELLE » : le dump se restaure et son contenu
# est là, mais la base vivante n'était pas joignable pour comparer. Ce n'est
# pas un échec, et systemd doit le savoir — sans cette ligne, une unité
# parfaitement saine serait rouge dans \`systemctl status\` toutes les semaines,
# et un rouge permanent ne se lit plus.
SuccessExitStatus=2

SyslogIdentifier=$U_RESTORE
StandardOutput=journal
StandardError=journal
EOF
}

_unite_restauration_timer() {
    cat <<EOF
# Minuterie engendrée par bootstrap/bootstrap.sh — cerveau « $BRAIN_NOM ».

[Unit]
Description=ARAC ($BRAIN_NOM) — restauration vérifiée, une fois par semaine

[Timer]
# Dimanche 03:00 : après la sauvegarde de 00:30, avant la semaine. Une
# vérification par semaine suffit à faire tomber la question « est-ce que mes
# dumps valent quelque chose ? » de « jamais répondue » à « répondue il y a
# moins de sept jours ».
OnCalendar=Sun *-*-* 03:00:00 UTC
# Rattrapage après un arrêt machine : une semaine sans preuve, c'est une
# semaine où le coffre a pu se vider sans que personne ne le sache.
Persistent=true
RandomizedDelaySec=900
Unit=$U_RESTORE.service

[Install]
WantedBy=timers.target
EOF
}

_unite_backup_timer() {
    cat <<EOF
# Minuterie engendrée par bootstrap/bootstrap.sh — cerveau « $BRAIN_NOM ».

[Unit]
Description=ARAC ($BRAIN_NOM) — sauvegarde toutes les six heures

[Timer]
# Quatre sauvegardes par jour : au pire, six heures de mémoire perdue.
OnCalendar=*-*-* 00,06,12,18:30:00 UTC
Persistent=true
RandomizedDelaySec=300
Unit=$U_BACKUP.service

[Install]
WantedBy=timers.target
EOF
}
