#!/usr/bin/env bash
# ============================================================================
# LE CHIEN DE GARDE DE LA SAUVEGARDE — il surveille la GARANTIE, pas les scripts
#
#     ops/watchdog.sh              # un verdict, un code de sortie
#     ops/watchdog.sh --explain    # les seuils et leur justification
#
# CODES DE SORTIE   0 tout va bien · 1 dégradé · 2 critique
#
# CE QU'IL SURVEILLE, ET POURQUOI CE N'EST PAS LA MÊME CHOSE
# ---------------------------------------------------------
# Une unité systemd qui échoue se voit dans `systemctl --failed`. Ce n'est pas
# ce qu'on veut savoir. Ce qu'on veut savoir, c'est si la GARANTIE tient :
#
#     « il existe, à cet instant, une copie récente de ce cerveau,
#       dont on a prouvé qu'elle se restaure. »
#
# Une sauvegarde peut cesser d'exister sans qu'aucun script n'échoue : le timer
# a été désactivé, le disque est plein, la copie hors site part vers une machine
# éteinte depuis trois semaines, la restauration hebdomadaire n'a plus tourné
# depuis un mois. Aucune de ces pannes n'allume de voyant rouge. Toutes se
# voient ici, parce qu'on regarde des DATES DE FICHIERS, pas des états de
# services.
#
# LE PULSE HEBDOMADAIRE — l'absence de mauvaise nouvelle n'est pas une bonne
# nouvelle. Si tout va bien, ce chien de garde envoie quand même un signe de vie
# une fois par semaine. Le jour où ce signe n'arrive pas, vous apprenez que
# votre canal d'alerte est muet — avant d'en avoir besoin.
# ============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$HERE/env.sh"
# shellcheck source=restore_guard.sh
source "$HERE/restore_guard.sh"


# ----------------------------------------------------------------------------
# LES SEUILS, ET D'OÙ ILS VIENNENT
# ----------------------------------------------------------------------------
#
# Aucun n'est une convention. Chacun se déduit d'une cadence observable ou d'une
# propriété de la machine. Quand vous changez une cadence, changez le seuil :
# un seuil qui ne correspond plus à la réalité entraîne à ignorer les alertes,
# et une alerte qu'on ignore est pire que pas d'alerte.

#: Âge du dump local. La sauvegarde tourne QUATRE FOIS PAR JOUR —
#: `OnCalendar=*-*-* 00,06,12,18:30:00 UTC`, et l'unité se décrit elle-même
#: « sauvegarde toutes les six heures ». La promesse n'est donc pas « au pire,
#: un jour de perdu » : c'est « au pire, SIX HEURES de perdues ».
#:
#: 26 h et 48 h sont HÉRITÉS d'une cadence quotidienne qui n'existe plus. Ils
#: valent aujourd'hui QUATRE passages manqués et HUIT. Ils sont conservés tels
#: quels — un seuil qu'on resserre sans y penser transforme une nuit de
#: maintenance en réveil — mais ils alertent TARD, et il faut le savoir : entre
#: la sixième heure et la vingt-sixième, ce contrôle est muet alors que trois
#: sauvegardes ont déjà été manquées.
#:
#: Pour coller à la cadence réelle : `ARAC_WD_DUMP_WARN_H=8` et
#: `ARAC_WD_DUMP_CRIT_H=14` — un passage manqué + 2 h, deux passages + 2 h.
#: C'est le réglage que demande la tolérance du § 8 de docs/SAUVEGARDE.md.
DUMP_WARN_H="${ARAC_WD_DUMP_WARN_H:-26}"
DUMP_CRIT_H="${ARAC_WD_DUMP_CRIT_H:-48}"

#: Âge de l'accusé de réception hors site. La copie tourne plus souvent que le
#: dump (toutes les 30 min chez nous), mais la machine de destination est un
#: portable : elle dort, elle voyage. 30 h tolère une nuit et une journée
#: d'absence ; 48 h dit qu'il n'existe plus AUCUNE copie hors de ce serveur —
#: donc qu'un incendie, un chiffrement malveillant ou une erreur de commande
#: emporte tout.
OFFSITE_WARN_H="${ARAC_WD_OFFSITE_WARN_H:-30}"
OFFSITE_CRIT_H="${ARAC_WD_OFFSITE_CRIT_H:-48}"

#: Âge de la dernière restauration PROUVÉE. Elle tourne une fois par semaine.
#: 192 h (8 j) = une occurrence manquée. 240 h (10 j) = deux, et l'on ne sait
#: plus si le coffre s'ouvre. C'est le seuil le plus important de ce fichier :
#: c'est le seul qui surveille la seule chose qui compte vraiment.
VERIFY_WARN_H="${ARAC_WD_VERIFY_WARN_H:-192}"
VERIFY_CRIT_H="${ARAC_WD_VERIFY_CRIT_H:-240}"

#: Occupation du système de fichiers qui porte les dumps.
#: 75 % : il reste de la place pour plusieurs dumps — on prévient sans urgence.
#: 85 % : sur un volume ordinaire, la marge restante est de l'ordre d'un seul
#: dump. Le prochain peut échouer à mi-écriture. Le seuil n'est donc pas « 85 %
#: c'est beaucoup », c'est « en dessous de cette marge, la prochaine sauvegarde
#: n'est plus garantie de tenir ».
DISK_WARN_PCT="${ARAC_WD_DISK_WARN_PCT:-75}"
DISK_CRIT_PCT="${ARAC_WD_DISK_CRIT_PCT:-85}"

#: Intervalle du signe de vie hebdomadaire, en heures.
PULSE_H="${ARAC_WD_PULSE_H:-168}"

if [ "${1:-}" = "--explain" ]; then
    sed -n '/^# LES SEUILS/,/^PULSE_H=/p' "$HERE/watchdog.sh" \
        | sed -e 's/^#: \{0,1\}/    /' -e 's/^# \{0,1\}//' -e 's/^#$//'
    exit 0
fi


# ----------------------------------------------------------------------------
# Les constats
# ----------------------------------------------------------------------------

problems=()
crit=0
note() { problems+=("$1"); }
alarm() { problems+=("$1"); crit=1; }

# --- 1. Le dump local
DUMP="$(arac_newest "$ARAC_BACKUP_DIR" "$ARAC_BACKUP_PREFIX-*.dump")"
[ -z "$DUMP" ] && DUMP="$(arac_newest "$ARAC_BACKUP_DIR" "$ARAC_BACKUP_PREFIX-*.dump.age")"
DUMP_AGE_H="$(arac_age_hours "${DUMP:-/nonexistent}")"
if [ -z "$DUMP" ]; then
    alarm "aucun dump dans $ARAC_BACKUP_DIR — la sauvegarde n'a JAMAIS produit de fichier"
elif [ "$DUMP_AGE_H" -gt "$DUMP_CRIT_H" ]; then
    alarm "dernier dump il y a ${DUMP_AGE_H} h (> ${DUMP_CRIT_H} h)"
elif [ "$DUMP_AGE_H" -gt "$DUMP_WARN_H" ]; then
    note "dernier dump il y a ${DUMP_AGE_H} h (> ${DUMP_WARN_H} h)"
fi

# --- 1 bis. Les dumps mis de côté par les contrôles de la sauvegarde
shopt -s nullglob
SET_ASIDE=( "$ARAC_BACKUP_DIR"/*.suspect "$ARAC_BACKUP_DIR"/*.incomplete )
shopt -u nullglob
[ "${#SET_ASIDE[@]}" -gt 0 ] && \
    note "${#SET_ASIDE[@]} dump(s) écarté(s) (.suspect / .incomplete) — un contrôle a refusé de les compter comme sauvegardes"

# --- 2. La copie hors site
OFFSITE_AGE_H=-1
if [ -n "${ARAC_OFFSITE_DEST:-}" ]; then
    RECEIPT="$(arac_newest "$ARAC_BACKUP_STATE/receipts" '*.ok')"
    OFFSITE_AGE_H="$(arac_age_hours "${RECEIPT:-/nonexistent}")"
    if [ -z "$RECEIPT" ]; then
        alarm "copie hors site configurée mais AUCUN accusé de réception — rien n'est jamais parti"
    elif [ "$OFFSITE_AGE_H" -gt "$OFFSITE_CRIT_H" ]; then
        alarm "dernière copie hors site il y a ${OFFSITE_AGE_H} h (> ${OFFSITE_CRIT_H} h) — plus aucune copie hors de ce serveur"
    elif [ "$OFFSITE_AGE_H" -gt "$OFFSITE_WARN_H" ]; then
        note "dernière copie hors site il y a ${OFFSITE_AGE_H} h (> ${OFFSITE_WARN_H} h)"
    fi
fi

# --- 3. La restauration prouvée
VERIFY_AGE_H="$(arac_age_hours "$ARAC_BACKUP_STATE/last_verify_ok")"
if [ ! -e "$ARAC_BACKUP_STATE/last_verify_ok" ]; then
    # LE TÉMOIN ABSENT AUTORISE À DIRE « JE NE SAIS PAS ». IL N'AUTORISE PAS À
    # DIRE POURQUOI. La raison est chez systemd, et c'est lui qu'on interroge.
    #
    # Le bootstrap arme « <prefixe>-restauration.timer » : le dimanche à 03:00.
    # Entre l'installation et le premier dimanche, ce témoin manque pour une
    # raison parfaitement saine — l'échéance n'est pas venue. Une ALARME
    # CRITIQUE pendant six jours sur toute installation neuve est la meilleure
    # façon d'apprendre à un lecteur que ce chien de garde aboie pour rien ;
    # le jour où il aboiera pour de bon, plus personne ne l'écoutera.
    #
    # On distingue donc « pas encore » de « jamais » : la première est une
    # note, la seconde reste une alarme.
    _T_REST=""
    if [ -n "${ARAC_UNIT_PREFIX:-}" ] && command -v systemctl >/dev/null 2>&1; then
        _T_REST="$(systemctl list-units --plain --no-legend --no-pager --type=timer \
                   "$ARAC_UNIT_PREFIX-restauration.timer" 2>/dev/null | awk '{print $1}')"
    fi
    if [ -n "$_T_REST" ] && \
       [ "$(systemctl show -p LastTriggerUSec --value "$_T_REST" 2>/dev/null)" = "n/a" ]; then
        note "aucune restauration vérifiée à ce jour — $_T_REST est armé et n'a pas encore sonné. Pour ne pas attendre : systemctl start ${_T_REST%.timer}.service"
    else
        alarm "aucune restauration n'a JAMAIS été vérifiée — vos dumps sont une hypothèse (ops/restore_verify.sh)"
    fi
    unset _T_REST
elif [ "$VERIFY_AGE_H" -gt "$VERIFY_CRIT_H" ]; then
    alarm "dernière restauration prouvée il y a ${VERIFY_AGE_H} h (> ${VERIFY_CRIT_H} h)"
elif [ "$VERIFY_AGE_H" -gt "$VERIFY_WARN_H" ]; then
    note "dernière restauration prouvée il y a ${VERIFY_AGE_H} h (> ${VERIFY_WARN_H} h)"
fi

# --- 4. Le disque
DISK_PCT="$(df --output=pcent "$ARAC_BACKUP_DIR" 2>/dev/null | tail -1 | tr -dc '0-9')"
DISK_PCT="${DISK_PCT:-0}"
if [ "$DISK_PCT" -gt "$DISK_CRIT_PCT" ]; then
    alarm "le volume des sauvegardes est plein à ${DISK_PCT} % (> ${DISK_CRIT_PCT} %)"
elif [ "$DISK_PCT" -gt "$DISK_WARN_PCT" ]; then
    note "le volume des sauvegardes est plein à ${DISK_PCT} % (> ${DISK_WARN_PCT} %)"
fi

# --- 5. La taille du dernier dump face à l'habitude
#
# Se calibre sur VOUS : personne ne peut dire quelle taille doit faire votre
# cerveau, mais votre cerveau d'hier le peut. La médiane des trente derniers
# dumps ne se laisse pas emporter par un jour anormal, contrairement à la
# moyenne. Sous 50 % de cette médiane, quelque chose a disparu.
LEDGER="$ARAC_BACKUP_STATE/dump_sizes"
if [ -r "$LEDGER" ] && [ -n "$DUMP" ]; then
    MED="$(cut -d' ' -f2 "$LEDGER" | tail -30 | arac_median || true)"
    LAST_SIZE="$(stat -c %s "$DUMP")"
    if [ -n "$MED" ] && [ "$MED" -gt 0 ] && arac_requires_force "$LAST_SIZE" "$MED"; then
        alarm "le dernier dump pèse $LAST_SIZE octets contre une médiane de $MED — moins de la moitié de l'habitude"
    fi
fi

# --- 6. Les destinataires du chiffrement n'ont pas changé dans votre dos
#
# Substituer une clé publique suffit à recevoir toutes les sauvegardes suivantes
# sans casser quoi que ce soit : rien n'échoue, tout continue, et le chiffrement
# protège désormais quelqu'un d'autre. On épingle donc l'empreinte du fichier.
if [ -n "${ARAC_BACKUP_RECIPIENTS:-}" ] && [ -n "${ARAC_BACKUP_RECIPIENTS_SHA:-}" ]; then
    CUR="$(sha256sum "$ARAC_BACKUP_RECIPIENTS" 2>/dev/null | cut -d' ' -f1)"
    [ "$CUR" != "$ARAC_BACKUP_RECIPIENTS_SHA" ] \
        && alarm "le fichier des destinataires de chiffrement a CHANGÉ (empreinte $CUR) — vos sauvegardes chiffrent peut-être pour quelqu'un d'autre"
fi


# ----------------------------------------------------------------------------
# Le verdict
# ----------------------------------------------------------------------------

status="ok"; rc=0
[ "${#problems[@]}" -gt 0 ] && { status="degraded"; rc=1; }
[ "$crit" -eq 1 ] && { status="critical"; rc=2; }

arac_log "watchdog.tick" \
"\"status\":\"$status\",\"dump_age_h\":$DUMP_AGE_H,\"offsite_age_h\":$OFFSITE_AGE_H,\"verify_age_h\":$VERIFY_AGE_H,\"disk_pct\":$DISK_PCT,\"problems\":${#problems[@]}"

if [ "${#problems[@]}" -gt 0 ]; then
    msg="SAUVEGARDE [$status] : $(printf '%s ; ' "${problems[@]}" | sed 's/ ; $//')"
    arac_alert "$([ "$crit" -eq 1 ] && echo critical || echo warn)" "$msg"
    printf '%s\n' "$msg"
fi

# --- Le signe de vie hebdomadaire
PULSE="$ARAC_BACKUP_STATE/last_pulse"
if [ "$status" = "ok" ] && [ "$(arac_age_hours "$PULSE")" -gt "$PULSE_H" ]; then
    arac_alert warn "SAUVEGARDE OK — dump ${DUMP_AGE_H} h, restauration prouvée il y a ${VERIFY_AGE_H} h, disque ${DISK_PCT} %. (Signe de vie hebdomadaire : si vous cessez de le recevoir, c'est le canal d'alerte lui-même qui est mort.)"
    mkdir -p "$ARAC_BACKUP_STATE" 2>/dev/null || true
    : > "$PULSE"
fi

[ "$status" = "ok" ] && printf 'sauvegarde : tout va bien (dump %s h, restauration prouvée %s h, disque %s %%)\n' \
    "$DUMP_AGE_H" "$VERIFY_AGE_H" "$DISK_PCT"

exit "$rc"
