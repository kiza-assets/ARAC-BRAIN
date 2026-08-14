#!/usr/bin/env bash
# ============================================================================
# RENDRE LES GABARITS — sans rien installer, sans rien activer
#
#     ops/systemd/render.sh                              → affiche tout, à l'écran
#     ops/systemd/render.sh /tmp/arac-units-<prefixe>    → écrit les fichiers rendus
#
# CE SCRIPT NE TOUCHE PAS À SYSTEMD. Il ne copie rien dans /etc, n'appelle ni
# `daemon-reload`, ni `enable`, ni `start`. Il substitue des valeurs dans des
# gabarits et s'arrête là.
#
# POURQUOI CETTE SÉPARATION
# -------------------------
# Activer une unité systemd, c'est promettre qu'une commande tournera toute
# seule, en votre nom, indéfiniment. Cette promesse se lit avant de se faire.
# Un script d'ops qui installe et arme ses propres minuteurs vous fait signer
# sans lire — et le jour où l'un d'eux efface un répertoire, personne ne sait
# d'où il vient.
#
# Vous rendez, vous LISEZ, vous copiez, vous armez. Quatre gestes, dont un seul
# est irréversible.
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../env.sh
source "$HERE/../env.sh"

OUT="${1:-}"

# Les valeurs substituées viennent de votre environnement et de votre .env —
# jamais d'un chemin écrit en dur ici. C'est ce qui rend ces gabarits utilisables
# sur une installation dont l'auteur de ce dépôt ne sait rien.
USER_NAME="${ARAC_SERVICE_USER:-$(id -un)}"
GROUP_NAME="${ARAC_SERVICE_GROUP:-$(id -gn)}"
VAR_DIR="${ARAC_VAR_DIR:-$ARAC_HOME/var}"

# LE NOM DES UNITÉS PORTE CELUI DU CERVEAU — et ce n'est pas du rangement.
#
# Ces gabarits rendaient `arac-backup.service`, `arac-health.service`… c'est-à-
# dire les MÊMES noms pour tous les cerveaux d'une machine. `systemctl enable`
# du second écrasait l'unité du premier : un seul des deux tournait, et c'était
# le dernier installé. La sauvegarde de l'autre cessait sans un message, et le
# minuteur restait vert — il déclenchait bien quelque chose, simplement pas ce
# qu'on croyait.
UNIT_PREFIX="${ARAC_UNIT_PREFIX:-}"
if [ -z "$UNIT_PREFIX" ]; then
    _nom="$(arac_db_nom || true)"
    if [ -z "$_nom" ]; then
        printf '%s\n' \
"Impossible de savoir de quel cerveau il s'agit : ni ARAC_UNIT_PREFIX, ni
ARAC_DB, ni config/brain.toml.

Les noms d'unités doivent porter celui du cerveau, sinon deux installations
sur cette machine s'écrasent l'une l'autre au premier « systemctl enable ».
On ne rend donc rien plutôt que de rendre des noms partagés.

    ARAC_UNIT_PREFIX=arac-<votre-base> ops/systemd/render.sh" >&2
        exit 2
    fi
    UNIT_PREFIX="arac-$_nom"
fi

subst() {
    sed -e "s#__ARAC_HOME__#${ARAC_HOME}#g" \
        -e "s#__ARAC_ENV_FILE__#${ARAC_ENV_FILE}#g" \
        -e "s#__ARAC_USER__#${USER_NAME}#g" \
        -e "s#__ARAC_GROUP__#${GROUP_NAME}#g" \
        -e "s#__ARAC_BACKUP_DIR__#${ARAC_BACKUP_DIR}#g" \
        -e "s#__ARAC_BACKUP_STATE__#${ARAC_BACKUP_STATE}#g" \
        -e "s#__ARAC_VAR_DIR__#${VAR_DIR}#g" \
        "$1"
}

# ----------------------------------------------------------------------------
# ON RELIT CE QU'ON VIENT D'ÉCRIRE, PAS CE QU'ON A LU
# ----------------------------------------------------------------------------
#
# La liste de `subst` et la liste des marqueurs présents dans les gabarits sont
# DEUX listes. Elles sont justes aujourd'hui ; rien ne les tenait ensemble.
# Un marqueur ajouté demain à un gabarit — `__ARAC_LOG_DIR__` dans une nouvelle
# unité — serait recopié TEL QUEL dans le fichier rendu, puis dans
# /etc/systemd/system par le `sudo cp` imprimé plus bas. systemd n'a pas de mot
# pour cela : il refuse l'unité, ou pire, il l'accepte avec un chemin littéral
# `__ARAC_HOME__/ops/watchdog.sh` et la sauvegarde ne tourne jamais.
#
# Le même défaut, dans la même famille, a coûté au pont du Mac tout son
# cloisonnement : `installer` fabriquait pont.conf par un `sed` à trois
# substitutions qui ne touchait aucune des quatre lignes portant `<cerveau>`.
# On ne vérifie donc pas la liste : on vérifie le FICHIER.
controle_rendu() { # fichier
    if grep -nE '__[A-Z][A-Z0-9_]+__|@@[A-Za-z0-9_]+@@' "$1"; then
        printf '%s\n' \
"
« $(basename "$1") » a été rendu avec des marqueurs INTACTS (ci-dessus).

Un marqueur non substitué n'est pas un détail de forme : c'est un chemin, un
compte ou un port LITTÉRAL, qui part ensuite en root dans /etc/systemd/system.
Ajoutez-le à « subst » dans $0, puis recommencez.

Rien n'a été laissé en place : le fichier fautif est retiré." >&2
        rm -f "$1"
        exit 2
    fi
}

# ----------------------------------------------------------------------------
# LE RÉPERTOIRE DE SORTIE EST UNE DESTINATION, PAS UN BROUILLON
# ----------------------------------------------------------------------------
#
# Ce que rendent ces gabarits ne reste pas ici : la recette imprimée plus bas
# se termine par des `sudo cp` vers /etc/systemd/system/ et /etc/tmpfiles.d/.
# Ce qu'un AUTRE aura déposé dans ce dossier partirait donc avec le reste, en
# root, dans deux répertoires qui appartiennent à la machine entière.
#
# Le danger n'est pas hypothétique sur CETTE machine-ci : ce framework crée un
# compte local par cerveau (`arac_<base>`, `aracagent_<base>`). Le voisin dont
# il faut se garder a déjà un shell et un droit d'écriture dans /tmp.
#
# On refuse donc un dossier qui existe et n'est pas à nous, ou qui est
# inscriptible par d'autres. Trois lignes, et elles valent pour toutes les
# destinations à venir — c'est la CLASSE qu'on ferme, pas l'occurrence.
if [ -n "$OUT" ]; then
    if [ -e "$OUT" ]; then
        _proprio="$(stat -c %u "$OUT" 2>/dev/null || echo -1)"
        _mode="$(stat -c %a "$OUT" 2>/dev/null || echo '')"
        if [ ! -d "$OUT" ]; then
            printf '%s\n' \
"« $OUT » existe et n'est pas un répertoire. On ne rend rien dedans." >&2
            exit 2
        fi
        if [ "$_proprio" != "$(id -u)" ]; then
            printf '%s\n' \
"« $OUT » existe et ne vous appartient pas (propriétaire : uid $_proprio).

Les fichiers rendus ici finissent dans /etc/systemd/system/ et
/etc/tmpfiles.d/ par un « sudo cp » : ce qu'un autre y aura déposé partirait
avec eux, en root. Une ligne de tmpfiles.d peut rouvrir le coffre d'un autre
cerveau à chaque démarrage.

Choisissez un dossier à vous — celui-ci porte le nom de ce cerveau, ce qui
suffit à ne pas le partager :
    ops/systemd/render.sh /tmp/arac-units-$UNIT_PREFIX" >&2
            exit 2
        fi
        # `-perm /022` : le groupe OU les autres peuvent écrire. On ne compte
        # pas les chiffres à la main — un mode à quatre chiffres (setgid, bit
        # collant) ferait mentir la lecture du dernier caractère.
        if [ -n "$(find "$OUT" -maxdepth 0 -perm /022 2>/dev/null)" ]; then
            printf '%s\n' \
"« $OUT » est inscriptible par d'autres (mode $_mode). Même raison : ce qu'on
rend ici part ensuite en root dans /etc. Reprenez la main dessus —
    chmod go-w '$OUT'
— ou rendez ailleurs." >&2
            exit 2
        fi
    else
        # 0700 dès la création : ce n'est pas un dossier public, et le rendre
        # public par défaut serait rouvrir la porte qu'on vient de fermer.
        mkdir -p "$OUT"
        chmod 0700 "$OUT"
    fi
fi

for tpl in "$HERE"/*.template; do
    # `arac-health.service.template` → `<prefixe>-health.service`
    name="$(basename "${tpl%.template}")"
    name="$UNIT_PREFIX-${name#arac-}"
    if [ -n "$OUT" ]; then
        subst "$tpl" > "$OUT/$name"
        controle_rendu "$OUT/$name"
        printf 'rendu : %s/%s\n' "$OUT" "$name"
    else
        # Sur la sortie standard, il n'y a pas de fichier à relire : on rend
        # dans un fichier jetable, on le contrôle, on l'imprime. Le contrôle
        # doit valoir aussi pour ce qu'on donne à LIRE — c'est ce texte-là que
        # quelqu'un recopie.
        tampon="$(mktemp)"
        subst "$tpl" > "$tampon"
        controle_rendu "$tampon"
        printf '\n═══ %s ═══\n' "$name"
        cat "$tampon"
        rm -f "$tampon"
    fi
done

if [ -n "$OUT" ]; then
    cat <<EOF

Rien n'est installé. Relisez les fichiers, puis, si vous êtes d'accord :

    sudo cp $OUT/$UNIT_PREFIX-*.service $OUT/$UNIT_PREFIX-*.timer /etc/systemd/system/
    sudo cp $OUT/$UNIT_PREFIX-backup-dirs.conf /etc/tmpfiles.d/$UNIT_PREFIX-backup.conf
    sudo systemd-tmpfiles --create
    sudo systemctl daemon-reload
    sudo systemctl enable --now $UNIT_PREFIX-backup-watchdog.timer \\
                                $UNIT_PREFIX-health.timer \\
                                $UNIT_PREFIX-install-check.timer

Chaque nom porte celui de ce cerveau. C'est ce qui permet à un second cerveau
de vivre sur cette machine sans écraser ces unités-ci — et c'est ce qui vous
dira, dans « systemctl list-units », lequel des deux vient de tomber.

CE QUI N'EST PAS ICI, ET POURQUOI. Ce répertoire a longtemps porté deux
gabarits de plus — « -backup » et « -restore-verify » — qui appelaient
exactement les mêmes scripts que les unités posées par le bootstrap :
$UNIT_PREFIX-sauvegarde et $UNIT_PREFIX-restauration. Une seule
implémentation, deux familles d'unités pour l'appeler. Les armer ne doublait
pas la protection, elle la RETIRAIT : les deux écrivaient dans le même
répertoire de dumps, le même script y faisait sa rotation, et le gabarit
d'ici ne portait pas ARAC_BACKUP_RETENTION_DAYS — il retombait donc sur 7
jours là où le bootstrap promet 14. Armer la seconde famille effaçait, sans
un mot, les dumps de la deuxième semaine. Ce qui reste ici est exactement ce
que le bootstrap n'arme PAS.

Les vôtres, posées par le bootstrap, se lisent ainsi :
    systemctl cat $UNIT_PREFIX-sauvegarde.service $UNIT_PREFIX-restauration.service
    systemctl list-timers '$UNIT_PREFIX-*'

La copie hors site ne s'arme que si vous avez posé ARAC_OFFSITE_DEST :
    sudo systemctl enable --now $UNIT_PREFIX-backup-offsite.timer

Puis, sans attendre le premier passage — un minuteur armé n'est pas un
minuteur qui marche :

    sudo systemctl start $UNIT_PREFIX-health.service \\
      && journalctl -u $UNIT_PREFIX-health -n 20
EOF
fi
