#!/usr/bin/env bash
# ============================================================================
# LA SAUVEGARDE — un dump toutes les six heures, vérifié avant d'être compté
#
#     ops/backup.sh                 # le geste, quatre fois par jour (unité systemd)
#     ops/backup.sh --dry-run       # dit ce qu'il ferait, ne touche à rien
#
# CE QU'IL FAIT, DANS L'ORDRE
#   1. dump du schéma du cerveau, format custom (pg_dump)
#   2. plancher absolu   : un dump minuscule est un échec silencieux
#   3. plancher relatif  : un dump deux fois plus petit que d'habitude aussi
#   4. sommaire          : les tables vitales sont-elles réellement dedans ?
#   5. chiffrement       : au repos, si vous avez fourni un destinataire age
#   6. rotation          : et seulement maintenant — jamais avant le succès
#   7. registre de taille: la mémoire qui permet aux seuils de se calibrer seuls
#
# CE QU'IL NE FAIT PAS
#   Il ne restaure rien, il ne vérifie pas que le dump se RESTAURE — c'est le
#   travail de `ops/restore_verify.sh`, et c'est le seul contrôle qui compte
#   vraiment. Un dump vérifié ici est un dump plausible, pas un dump prouvé.
#
# CE QU'IL COÛTE
#   Un `pg_dump` lit toute la base. Sur un cerveau jeune c'est instantané ; sur
#   un cerveau chargé d'embeddings (3072 dimensions par atome, en halfvec) le
#   dump est dominé par les vecteurs et pèse davantage que ce que « quelques
#   milliers d'atomes » laisse imaginer. Surveillez `df` avant de fixer une
#   rétention généreuse.
# ============================================================================
set -euo pipefail

# shellcheck source=env.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/env.sh"
# shellcheck source=backup_toc_check.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/backup_toc_check.sh"
# shellcheck source=restore_guard.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/restore_guard.sh"


# ----------------------------------------------------------------------------
# Réglages — chacun a un défaut, et le défaut a une raison
# ----------------------------------------------------------------------------

#: Combien de jours on garde. 7 par défaut : une semaine couvre le délai
#: réaliste entre une bêtise et le moment où on s'en aperçoit (« pourquoi ce
#: souvenir a disparu ? »). Au-delà, c'est la copie hors site qui prend le
#: relais, avec sa propre rétention.
RETENTION_DAYS="${ARAC_BACKUP_RETENTION_DAYS:-7}"

#: Le nombre de dumps qu'on garde QUOI QU'IL ARRIVE, même trop vieux. Sans ce
#: plancher, une machine éteinte deux semaines se réveille, prend un dump, et
#: la rotation efface les seuls dumps de l'époque où elle marchait encore.
KEEP_MIN="${ARAC_BACKUP_KEEP_MIN:-3}"

#: Plancher absolu, en octets. Un dump plus petit signale une base vide, une
#: authentification qui a échoué en douceur, ou un schéma qui n'existe pas.
#: 10 KiB : un schéma ARAC vide, sans une seule ligne, pèse déjà davantage.
MIN_BYTES="${ARAC_BACKUP_MIN_BYTES:-10240}"

#: Plancher relatif, en pourcentage de la taille MÉDIANE des derniers dumps.
#: 50 % : un cerveau ne perd pas la moitié de son volume en une nuit. Ce seuil
#: se calibre tout seul sur votre installation — il ne suppose aucune taille.
MIN_PCT_OF_MEDIAN="${ARAC_BACKUP_MIN_PCT_OF_MEDIAN:-50}"

#: Destinataires age pour le chiffrement au repos (fichier de clés publiques).
#: Vide = les dumps restent EN CLAIR sur le disque, et le script le dit.
RECIPIENTS="${ARAC_BACKUP_RECIPIENTS:-}"

#: Garder le dump en clair à côté du chiffré ? Oui par défaut : la restauration
#: d'urgence ne doit pas dépendre d'une clé privée qu'on cherche en panique.
#: À 0, seul le chiffré subsiste — plus sûr, mais alors la clé privée DOIT être
#: accessible depuis le serveur, ce qui annule une partie du bénéfice.
KEEP_CLEAR="${ARAC_BACKUP_CLEAR_LOCAL:-1}"

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1


# ----------------------------------------------------------------------------
# Préalables — tout ce qui manque est dit AVANT de commencer
# ----------------------------------------------------------------------------

arac_require pg_dump "installez le paquet postgresql-client de la même version majeure que le serveur"
arac_require pg_restore "il vient avec postgresql-client ; il sert ici à lire le sommaire du dump"

# Le nom du rôle de sauvegarde porte celui du cerveau — il n'y a pas UN rôle
# de sauvegarde par machine, il y en a un par cerveau. Le dire avec le vrai nom
# évite le geste qui a détruit une production : réutiliser le rôle du voisin
# parce qu'il portait le nom qu'on attendait.
_role_backup="${ARAC_ROLE_PREFIX:+${ARAC_ROLE_PREFIX}_backup}"
_role_backup="${_role_backup:-<prefixe-de-ce-cerveau>_backup}"

DSN="$(arac_backup_dsn)" || arac_die \
"Aucun DSN de sauvegarde.

Posez l'une de ces variables dans le fichier d'environnement de CE cerveau
(\$ARAC_ENV_FILE) :

    DATABASE_URL_BACKUP=postgresql://$_role_backup:...@localhost:<port>/<votre base>

Ce rôle lit tout et n'écrit rien. C'est le seul dont pg_dump a besoin — lui en
donner un plus puissant, c'est faire tourner un processus automatique et non
surveillé sous un rôle capable de détruire le schéma."

# UN AVERTISSEMENT PERMANENT N'EST PLUS UN AVERTISSEMENT.
#
# Ces trois lignes partaient QUATRE FOIS PAR JOUR, sur toute installation posée
# par ce bootstrap, depuis toujours. Le rôle « $_role_backup » est créé
# NOLOGIN — délibérément, et `bootstrap/lib/database.sh` explique pourquoi sur
# vingt lignes : « un rôle connectable dont personne ne se sert est une porte
# de plus ». `DATABASE_URL_BACKUP` ne peut donc pas exister, et l'avertissement
# ne peut pas s'éteindre. Il n'apprenait rien ; il apprenait seulement à ne
# plus lire le journal de la sauvegarde — c'est-à-dire l'endroit exact où un
# vrai message doit être vu.
#
# On sépare donc les deux situations, parce qu'elles ne demandent pas le même
# geste :
#
#   · le rôle NE PEUT PAS se connecter → c'est l'état voulu de l'installation.
#     On le dit UNE FOIS, et on se tait tant que rien ne change. Le témoin vit
#     dans l'état de la sauvegarde, à côté du registre des tailles.
#   · le rôle PEUT se connecter et `DATABASE_URL_BACKUP` manque → là, il y a
#     quelque chose à faire, et c'est le lecteur qui a ouvert la porte sans
#     brancher la sauvegarde dessus. On le dit à CHAQUE passage, jusqu'à ce que
#     ce soit fait.
#
# Le changement d'état RÉVEILLE le message : le témoin porte la situation
# constatée, pas un simple « déjà dit ».
if arac_backup_dsn_is_admin; then
    # « inconnu » est une mesure comme une autre, et elle a le droit d'exister :
    # sans psql, ou sans préfixe de rôle, on ne SAIT PAS si la porte est
    # ouverte. On le note tel quel dans le témoin plutôt que de supposer.
    _bkp_peut_se_connecter=inconnu
    if [ -n "${ARAC_ROLE_PREFIX:-}" ] && command -v psql >/dev/null 2>&1; then
        _bkp_peut_se_connecter="$(psql "$DSN" -qtAc \
            "SELECT rolcanlogin FROM pg_roles WHERE rolname='$_role_backup'" 2>/dev/null || true)"
        [ -n "$_bkp_peut_se_connecter" ] || _bkp_peut_se_connecter=inconnu
    fi

    _bkp_temoin="$ARAC_BACKUP_STATE/role_sauvegarde"
    _bkp_deja=''
    [ -r "$_bkp_temoin" ] && _bkp_deja="$(cat "$_bkp_temoin" 2>/dev/null)"

    if [ "$_bkp_peut_se_connecter" = "t" ]; then
        arac_warn "⚠ Le rôle « $_role_backup » PEUT se connecter, et la sauvegarde tourne"
        arac_warn "  quand même sous le rôle ADMIN (DDL) : DATABASE_URL_BACKUP n'est pas posée."
        arac_warn "  La porte est ouverte, rien n'est branché dessus. Une ligne à ajouter dans"
        arac_warn "  $ARAC_ENV_FILE, et ce processus automatique cesse de pouvoir modifier le schéma :"
        arac_warn "      DATABASE_URL_BACKUP=postgresql://$_role_backup:...@localhost:${ARAC_DB_PORT:-<port>}/${ARAC_DB:-<votre base>}"
    elif [ "$_bkp_deja" != "$_bkp_peut_se_connecter" ]; then
        arac_warn "⚠ La sauvegarde tourne sous le rôle ADMIN (DDL) : le rôle « $_role_backup »"
        arac_warn "  existe mais est NOLOGIN — c'est l'état posé par le bootstrap, et il est voulu."
        arac_warn "  Conséquence à connaître : un processus automatique et silencieux a le pouvoir"
        arac_warn "  de modifier le schéma. Pour l'ôter, c'est une décision en deux gestes :"
        arac_warn "      ALTER ROLE $_role_backup WITH LOGIN PASSWORD '…';"
        arac_warn "      puis DATABASE_URL_BACKUP=… dans $ARAC_ENV_FILE"
        arac_warn "  Ce message ne reviendra pas tant que cette situation ne changera pas :"
        arac_warn "  un avertissement imprimé quatre fois par jour n'est plus un avertissement."
    fi
    # `--dry-run` ne touche à rien, témoin compris : sinon la simulation
    # éteindrait, pour de bon, un message que l'exécution réelle n'a jamais dit.
    if [ "$DRY_RUN" -eq 0 ]; then
        mkdir -p "$ARAC_BACKUP_STATE" 2>/dev/null || true
        printf '%s\n' "$_bkp_peut_se_connecter" > "$_bkp_temoin" 2>/dev/null || true
    fi
fi

if [ ! -d "$ARAC_BACKUP_DIR" ]; then
    # LE RÉPERTOIRE DE RENDU PORTE LE NOM DE CE CERVEAU, ET LA COPIE NOMME SON
    # FICHIER. Trois endroits du dépôt disaient déjà cette phrase ; celui-ci,
    # le quatrième, était le seul à se terminer par un `sudo cp` vers un
    # répertoire commun à la machine — et il portait les deux fautes ensemble.
    #
    # `/tmp/units` est un nom commun dans un répertoire où TOUT compte local
    # écrit. Ce framework CRÉE des comptes locaux, un par cerveau
    # (`arac_<base>`, `aracagent_<base>`) : le voisin dont il faut se garder
    # est déjà sur la machine. S'il pose ce dossier avant vous, `render.sh`
    # écrivait dedans sans un mot (`mkdir -p` ne regarde pas le propriétaire —
    # il le regarde désormais, et refuse).
    #
    # Et `cp …/*-backup-dirs.conf` est un GLOB : il ne prend pas le fichier
    # qu'on vient de rendre, il prend TOUT ce qui, dans ce dossier, finit par
    # ce suffixe — l'ordre alphabétique mettant celui du voisin en premier. Une
    # ligne de `tmpfiles.d` n'est pas inerte : « z /etc/arac/<un autre> 0755 …»
    # change les droits du COFFRE d'un autre cerveau à chaque démarrage, et la
    # ligne suivante de ce remède demandait précisément `systemd-tmpfiles
    # --create`. Le coffre contient un arac.env complet : jeton, DSN, mots de
    # passe.
    #
    # Un fichier nommé, une destination nommée, aucun `*` — c'est ce que
    # `ops/systemd/render.sh` imprime lui-même à la fin de son rendu.
    _UP="${ARAC_UNIT_PREFIX:-arac-${ARAC_BACKUP_PREFIX:-<votre-base>}}"
    arac_die "Répertoire de sauvegarde absent : $ARAC_BACKUP_DIR

Il n'est pas créé automatiquement, et ce n'est pas un oubli : ses droits d'accès
sont une décision de sécurité (les dumps contiennent TOUT le cerveau, en clair).

    sudo install -d -m 0700 -o \"\$(id -un)\" '$ARAC_BACKUP_DIR'

ou, pour que systemd s'en charge à chaque démarrage — le gabarit est rendu au
nom de CE cerveau, jamais à un nom commun, et il se copie fichier par fichier :
    ops/systemd/render.sh '/tmp/arac-units-$_UP'
    sudo cp '/tmp/arac-units-$_UP/$_UP-backup-dirs.conf' '/etc/tmpfiles.d/$_UP-backup.conf'
    sudo systemd-tmpfiles --create"
fi

mkdir -p "$ARAC_BACKUP_STATE" 2>/dev/null || true
SIZE_LEDGER="$ARAC_BACKUP_STATE/dump_sizes"

if [ -z "$RECIPIENTS" ]; then
    arac_warn "⚠ Chiffrement au repos DÉSACTIVÉ (ARAC_BACKUP_RECIPIENTS non posée)."
    arac_warn "  Les dumps restent en clair dans $ARAC_BACKUP_DIR. Quiconque lit ce"
    arac_warn "  répertoire lit l'intégralité de votre cerveau. Voir docs/SAUVEGARDE.md."
    if [ -n "${ARAC_BACKUP_RECIPIENTS_ATTENDU:-}" ]; then
        arac_warn "  Pour l'activer, la clé PUBLIQUE age de CE cerveau se dépose ici :"
        arac_warn "      $ARAC_BACKUP_RECIPIENTS_ATTENDU"
        arac_warn "  et l'AJOUT se fait avec '>>', jamais avec '>' : un '>' remplace"
        arac_warn "  les clés déjà présentes, et le jour de la restauration la clé"
        arac_warn "  privée qu'on avait gardée ne déchiffre plus rien."
    fi
elif [ ! -r "$RECIPIENTS" ]; then
    arac_die "Fichier de destinataires illisible : $RECIPIENTS"
else
    # --- CE FICHIER EST-IL CELUI DE CE CERVEAU ? ----------------------------
    #
    # On ne dresse pas la liste des chemins interdits — elle oublierait, comme
    # toutes les listes de noms. On décrit ce qui est LÉGITIME : le fichier de
    # destinataires d'un cerveau vit dans le coffre de ce cerveau. Tout le
    # reste est possible, mais doit être délibéré, donc dit.
    #
    # Le cas qu'on attrape ainsi : `/etc/arac/backup-recipients.txt`, la racine
    # commune — le chemin que la documentation faisait écrire. Elle
    # n'appartient à personne, donc à tout le monde : le second cerveau y
    # dépose SA clé publique, et les dumps du premier partent chiffrés pour un
    # tiers. Personne ne s'en aperçoit avant le jour de la restauration.
    if [ -n "${ARAC_BACKUP_RECIPIENTS_ATTENDU:-}" ] \
       && [ "$RECIPIENTS" != "$ARAC_BACKUP_RECIPIENTS_ATTENDU" ]; then
        arac_warn "⚠ Destinataires age hors du coffre de ce cerveau :"
        arac_warn "     lu       $RECIPIENTS"
        arac_warn "     attendu  $ARAC_BACKUP_RECIPIENTS_ATTENDU"
        arac_warn "  Ce n'est pas une erreur en soi — vous avez pu le poser ailleurs"
        arac_warn "  exprès. Mais un fichier commun à la machine est partagé par tous"
        arac_warn "  les cerveaux : celui qui l'écrit en dernier décide POUR QUI les"
        arac_warn "  dumps des autres sont chiffrés, et cela ne se découvre qu'à la"
        arac_warn "  restauration. Vérifiez que ce fichier ne contient QUE vos clés :"
        arac_warn "      sudo cat $RECIPIENTS"
    fi
fi


# ----------------------------------------------------------------------------
# 1. Le dump
# ----------------------------------------------------------------------------

STAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
DUMP="$ARAC_BACKUP_DIR/$ARAC_BACKUP_PREFIX-$STAMP.dump"
PARTIAL="$DUMP.partial"

arac_log "backup.start" "\"target\":\"$DUMP\",\"schema\":\"$ARAC_DB_SCHEMA\",\"dsn\":\"$(arac_dsn_redacted "$DSN")\""

if [ "$DRY_RUN" -eq 1 ]; then
    echo "--dry-run : pg_dump --schema=$ARAC_DB_SCHEMA --format=custom → $DUMP"
    echo "--dry-run : rétention ${RETENTION_DAYS} j, plancher ${KEEP_MIN} dumps"
    echo "--dry-run : chiffrement $([ -n "$RECIPIENTS" ] && echo "age → $RECIPIENTS" || echo "AUCUN")"
    exit 0
fi

# On écrit d'abord dans un `.partial`, puis on renomme. Un `pg_dump` interrompu
# (machine coupée, disque plein, OOM) laisse alors un fichier qui ne ressemble
# PAS à un dump — au lieu d'un fichier tronqué au bon nom, que la restauration
# du mois prochain choisirait comme « le plus récent ».
if ! pg_dump "$DSN" \
        --schema="$ARAC_DB_SCHEMA" \
        --format=custom \
        --file="$PARTIAL"; then
    rm -f "$PARTIAL"
    arac_alert critical "SAUVEGARDE : pg_dump a échoué — aucun dump produit ce jour."
    exit 1
fi


# ----------------------------------------------------------------------------
# 2 et 3. Les deux planchers
# ----------------------------------------------------------------------------

SIZE=$(stat -c %s "$PARTIAL")

if [ "$SIZE" -lt "$MIN_BYTES" ]; then
    rm -f "$PARTIAL"
    arac_alert critical "SAUVEGARDE : dump de $SIZE octets (< $MIN_BYTES) — base vide, mauvais schéma, ou authentification muette. Rien n'a été gardé, la rotation n'a PAS tourné."
    exit 1
fi

MEDIAN=''
if [ -r "$SIZE_LEDGER" ]; then
    MEDIAN=$(cut -d' ' -f2 "$SIZE_LEDGER" | tail -30 | arac_median || true)
fi
if [ -n "$MEDIAN" ] && [ "$MEDIAN" -gt 0 ]; then
    if [ $(( SIZE * 100 )) -lt $(( MEDIAN * MIN_PCT_OF_MEDIAN )) ]; then
        mv "$PARTIAL" "$DUMP.suspect"
        arac_alert critical "SAUVEGARDE : dump de $SIZE octets contre une médiane de $MEDIAN — moins de ${MIN_PCT_OF_MEDIAN}% de l'habitude. Gardé sous le nom .suspect, la rotation n'a PAS tourné. Comparez avec le dump d'hier avant de conclure."
        exit 1
    fi
fi


# ----------------------------------------------------------------------------
# 4. Le sommaire — le dump contient-il ce qu'on croit ?
# ----------------------------------------------------------------------------

if ! TOC="$(pg_restore --list "$PARTIAL" 2>/dev/null)"; then
    mv "$PARTIAL" "$DUMP.suspect"
    arac_alert critical "SAUVEGARDE : dump ILLISIBLE (pg_restore --list échoue). Gardé sous .suspect."
    exit 1
fi

if ! MISSING="$(arac_toc_missing_tables "$ARAC_DB_SCHEMA" <<<"$TOC")"; then
    MISSING_CSV="$(tr '\n' ',' <<<"$MISSING" | sed 's/,$//')"
    mv "$PARTIAL" "$DUMP.incomplete"
    arac_alert critical "SAUVEGARDE : dump INCOMPLET, tables absentes : $MISSING_CSV. Gardé sous .incomplete. Cause la plus fréquente : une migration a créé une table que le rôle de sauvegarde n'a pas le droit de lire — vérifiez les GRANT avant de conclure à une corruption."
    exit 1
fi

mv "$PARTIAL" "$DUMP"
chmod 0600 "$DUMP"
arac_log "backup.dumped" "\"file\":\"$(basename "$DUMP")\",\"bytes\":$SIZE"


# ----------------------------------------------------------------------------
# 5. Le chiffrement au repos
# ----------------------------------------------------------------------------
#
# `age` en mode asymétrique : le serveur ne détient que les clés PUBLIQUES. Il
# peut chiffrer, il ne peut pas déchiffrer. C'est ce qui fait qu'un serveur
# compromis ne livre pas l'historique des sauvegardes — seulement les dumps en
# clair encore présents, d'où l'intérêt de ARAC_BACKUP_CLEAR_LOCAL=0 dès que
# vous avez une procédure de clé qui tient debout.

if [ -n "$RECIPIENTS" ]; then
    arac_require age "https://github.com/FiloSottile/age — paquet 'age' sur Ubuntu"
    CIPHER="$DUMP.age"
    if ! age -R "$RECIPIENTS" -o "$CIPHER.partial" "$DUMP"; then
        rm -f "$CIPHER.partial"
        arac_alert critical "SAUVEGARDE : chiffrement échoué pour $(basename "$DUMP") — le dump reste EN CLAIR sur le disque."
        exit 1
    fi
    sha256sum "$CIPHER.partial" | cut -d' ' -f1 > "$CIPHER.sha256"
    mv "$CIPHER.partial" "$CIPHER"
    chmod 0600 "$CIPHER" "$CIPHER.sha256"
    arac_log "backup.encrypted" "\"file\":\"$(basename "$CIPHER")\",\"bytes\":$(stat -c %s "$CIPHER")"

    if [ "$KEEP_CLEAR" = "0" ]; then
        rm -f "$DUMP"
        arac_log "backup.clear_removed" "\"file\":\"$(basename "$DUMP")\""
    fi
fi


# ----------------------------------------------------------------------------
# 6. La rotation — après le succès, jamais avant
# ----------------------------------------------------------------------------
#
# L'ordre n'est pas cosmétique. Si la rotation tournait en premier, un pg_dump
# qui échoue ensuite laisserait une machine avec un dump de moins et rien pour
# le remplacer. Répété trois nuits, ce détail d'ordonnancement vide un coffre.

DELETED=0
mapfile -t ALL < <(ls -1t "$ARAC_BACKUP_DIR/$ARAC_BACKUP_PREFIX"-*.dump 2>/dev/null || true)
if [ "${#ALL[@]}" -gt "$KEEP_MIN" ]; then
    for f in "${ALL[@]:$KEEP_MIN}"; do
        if [ -n "$(find "$f" -mtime "+$RETENTION_DAYS" -print -quit 2>/dev/null)" ]; then
            rm -f "$f" "$f.age" "$f.age.sha256"
            DELETED=$(( DELETED + 1 ))
        fi
    done
fi
[ "$DELETED" -gt 0 ] && arac_log "backup.rotated" "\"deleted\":$DELETED,\"retention_days\":$RETENTION_DAYS,\"keep_min\":$KEEP_MIN"


# ----------------------------------------------------------------------------
# 7. Le registre des tailles
# ----------------------------------------------------------------------------
#
# Une ligne par dump : « horodatage taille ». C'est la mémoire qui permet au
# plancher relatif (§3) et au chien de garde de se calibrer sur VOTRE cerveau
# plutôt que sur une convention. Trente lignes suffisent ; on ne garde pas plus.

printf '%s %s\n' "$STAMP" "$SIZE" >> "$SIZE_LEDGER"
tail -n 90 "$SIZE_LEDGER" > "$SIZE_LEDGER.tmp" && mv "$SIZE_LEDGER.tmp" "$SIZE_LEDGER"

arac_log "backup.done" "\"file\":\"$(basename "$DUMP")\",\"bytes\":$SIZE,\"encrypted\":$([ -n "$RECIPIENTS" ] && echo true || echo false),\"rotated\":$DELETED"
