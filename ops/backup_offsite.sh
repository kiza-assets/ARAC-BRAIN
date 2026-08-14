#!/usr/bin/env bash
# ============================================================================
# LA COPIE HORS SITE — facultative, chiffrée, et jamais destructrice
#
#     ops/backup_offsite.sh
#
# CODES DE SORTIE   0 rien à signaler (y compris « destination endormie »)
#                   1 anomalie GRAVE (empreinte divergente, envoi corrompu)
#
# POURQUOI « FACULTATIVE » N'EST PAS « OPTIONNELLE POUR DE VRAI »
# --------------------------------------------------------------
# Tant que la seule copie de votre cerveau vit sur le serveur qui l'héberge,
# vous n'avez pas de sauvegarde : vous avez une copie locale, qui disparaît avec
# la machine — panne de disque, erreur de commande, hébergeur qui ferme,
# rançongiciel qui chiffre tout le volume. Le jour où c'est arrivé, il est trop
# tard pour configurer ceci.
#
# Elle reste facultative dans le code parce qu'elle exige une seconde machine,
# que ce dépôt ne peut pas inventer à votre place. Sans `ARAC_OFFSITE_DEST`, ce
# script ne fait rien et le dit — il ne prétend pas que tout va bien.
#
# CE QU'IL ENVOIE, ET CE QU'IL REFUSE D'ENVOYER
# ---------------------------------------------
# Uniquement des artefacts CHIFFRÉS (`*.dump.age`). Envoyer un cerveau en clair
# chez un tiers — un NAS, un cloud, la machine d'un proche — n'est pas un défaut
# raisonnable. Le serveur ne détient que les clés publiques : il chiffre, il ne
# déchiffre pas. Un serveur compromis ne livre donc pas l'historique.
#
# CE QU'IL NE FAIT JAMAIS
# -----------------------
# Supprimer quoi que ce soit à distance. La destination est en AJOUT SEUL, du
# point de vue de ce script. C'est ce qui fait qu'un serveur compromis ne peut
# pas effacer les sauvegardes — la première chose que fait un rançongiciel bien
# élevé. Le côté distant applique sa propre rétention, à son rythme, hors de
# portée d'ici. Pour verrouiller cette propriété, cf docs/SAUVEGARDE.md,
# section « la commande forcée ».
#
# DESTINATION ENDORMIE = NORMAL
# -----------------------------
# Si la destination est un portable, il dort la nuit et voyage le jour. Un envoi
# raté n'est pas une erreur : c'est l'ANCIENNETÉ de la dernière copie réussie
# qui compte, et c'est le chien de garde qui la surveille (ops/watchdog.sh).
# Ce script sort donc en 0 quand la destination est injoignable. Sinon, une
# unité systemd en échec toutes les 30 minutes finirait par n'être plus lue.
# ============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$HERE/env.sh"

DEST="${ARAC_OFFSITE_DEST:-}"
if [ -z "$DEST" ]; then
    echo "Copie hors site NON CONFIGURÉE (ARAC_OFFSITE_DEST vide)."
    echo "Vos sauvegardes ne quittent pas ce serveur : elles disparaîtront avec lui."
    echo "Voir docs/SAUVEGARDE.md, section « la deuxième machine »."
    arac_log "offsite.disabled"
    exit 0
fi

SSH_PORT="${ARAC_OFFSITE_PORT:-22}"
SSH_KEY="${ARAC_OFFSITE_SSH_KEY:-}"
REMOTE_DIR="${ARAC_OFFSITE_DIR:-arac-backups}"
RECEIPTS="$ARAC_BACKUP_STATE/receipts"
mkdir -p "$RECEIPTS" 2>/dev/null || true

arac_require ssh
arac_require scp

ssh_opts=( -p "$SSH_PORT" -o BatchMode=yes -o ConnectTimeout=10 )
scp_opts=( -P "$SSH_PORT" -o BatchMode=yes -o ConnectTimeout=10 )
[ -n "$SSH_KEY" ] && { ssh_opts+=( -i "$SSH_KEY" ); scp_opts+=( -i "$SSH_KEY" ); }

remote() { ssh "${ssh_opts[@]}" "$DEST" "$@"; }

# La destination répond-elle ? Une seule question, dix secondes, puis on renonce
# sans bruit.
if ! remote true >/dev/null 2>&1; then
    arac_log "offsite.unreachable" "\"dest\":\"$DEST\""
    echo "Destination injoignable ($DEST) — normal si c'est une machine qui dort."
    echo "C'est l'ancienneté de la dernière copie qui compte : ops/watchdog.sh la surveille."
    exit 0
fi

remote "mkdir -p '$REMOTE_DIR'" >/dev/null 2>&1 || true

shopt -s nullglob
CANDIDATES=( "$ARAC_BACKUP_DIR/$ARAC_BACKUP_PREFIX"-*.dump.age )
shopt -u nullglob

if [ "${#CANDIDATES[@]}" -eq 0 ]; then
    if [ "${ARAC_OFFSITE_ALLOW_CLEAR:-0}" = "1" ]; then
        shopt -s nullglob
        CANDIDATES=( "$ARAC_BACKUP_DIR/$ARAC_BACKUP_PREFIX"-*.dump )
        shopt -u nullglob
        arac_warn "⚠ ARAC_OFFSITE_ALLOW_CLEAR=1 : des dumps EN CLAIR vont partir hors de ce serveur."
        arac_warn "  Tout ce que votre cerveau sait sera lisible par qui contrôle la destination."
    else
        echo "Aucun artefact chiffré à envoyer."
        echo "Le chiffrement au repos est désactivé (ARAC_BACKUP_RECIPIENTS non posée),"
        echo "et ce script refuse d'envoyer un cerveau en clair chez un tiers."
        echo "Voir docs/SAUVEGARDE.md, section « la clé qui ne vit pas sur le serveur »."
        arac_log "offsite.nothing_encrypted"
        exit 0
    fi
fi

sent=0
rc=0
for artefact in "${CANDIDATES[@]}"; do
    name="$(basename "$artefact")"
    [ -f "$RECEIPTS/$name.ok" ] && continue

    local_sha="$(sha256sum "$artefact" | cut -d' ' -f1)"

    # L'envoi passe par un nom temporaire puis un renommage distant : un
    # transfert coupé en route ne laisse jamais un fichier au nom définitif,
    # que la restauration de l'année prochaine prendrait pour un dump entier.
    if ! scp "${scp_opts[@]}" -q "$artefact" "$DEST:$REMOTE_DIR/$name.partial" >/dev/null 2>&1; then
        arac_log "offsite.push_failed" "\"file\":\"$name\""
        rc=0   # la destination a pu s'endormir en cours de route : pas une erreur
        continue
    fi
    remote "mv '$REMOTE_DIR/$name.partial' '$REMOTE_DIR/$name'" >/dev/null 2>&1 || true

    # On vérifie ce qui est ARRIVÉ, pas ce qu'on a envoyé. Un transfert « réussi »
    # dont l'empreinte diffère est le seul cas vraiment grave de ce script :
    # corruption en vol, ou collision de nom avec un contenu différent.
    remote_sha="$(remote "sha256sum '$REMOTE_DIR/$name'" 2>/dev/null | cut -d' ' -f1)"
    if [ -z "$remote_sha" ]; then
        arac_log "offsite.no_remote_sum" "\"file\":\"$name\""
        continue
    fi
    if [ "$remote_sha" != "$local_sha" ]; then
        arac_alert critical "COPIE HORS SITE : empreinte divergente pour $name (local=$local_sha distant=$remote_sha). Le fichier arrivé n'est PAS celui qui est parti."
        rc=1
        continue
    fi

    printf '{"file":"%s","sha256":"%s","acked_at":"%s","dest":"%s"}\n' \
        "$name" "$local_sha" "$(arac_now)" "$DEST" > "$RECEIPTS/$name.ok"
    arac_log "offsite.acked" "\"file\":\"$name\""
    sent=$(( sent + 1 ))
done

arac_log "offsite.done" "\"sent\":$sent"
[ "$sent" -gt 0 ] && echo "$sent artefact(s) copié(s) hors site et vérifié(s) à l'arrivée."
exit "$rc"
