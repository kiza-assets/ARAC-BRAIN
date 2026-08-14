# shellcheck shell=bash
# ===========================================================================
# garde_isolement.sh — le contrôle qui aurait attrapé la faute.
#
# CE FICHIER EXISTE À CAUSE D'UN INCIDENT, ET IL FAUT LE RACONTER ICI PLUTÔT
# QU'AILLEURS, PARCE QUE C'EST ICI QU'ON REVIENDRA LE LIRE.
#
# Un essai du framework a cassé une installation de production. Trois causes,
# toutes des défauts de PRODUIT, aucune une faute d'exploitation :
#
#   1. les rôles PostgreSQL sont GLOBAUX AU CLUSTER. Le bootstrap les nomme
#      `arac_app`, `arac_agent`, `arac_readonly`, `arac_admin`, `arac_backup`,
#      en dur — parce que les migrations les nomment en dur. Une seconde
#      installation sur le MÊME cluster fait `ALTER ROLE … PASSWORD` et écrase
#      les secrets de la première. Cinq rôles perdus d'un coup, et la panne ne
#      se déclare qu'au redémarrage suivant des services de la victime : des
#      heures plus tard, sans rapport visible avec ce qu'on venait de faire.
#
#   2. un port se prend sans demander. Une unité d'essai a lié le 8000, celui
#      de l'API de production, qui a redémarré 35 fois sans jamais pouvoir se
#      lier. Pire que la panne : le `/healthz` répondait 200 — servi par
#      l'usurpateur. Le diagnostic mentait.
#
#   3. rien ne borne un cerveau à son cluster : tout atterrit sur le 5432.
#
# CE QUE CE FICHIER FAIT, ET CE QU'IL NE FAIT PAS
# ------------------------------------------------
# Il ne corrige aucun de ces trois défauts — ce n'est pas son rôle, et un
# correctif sans garde revient à la manche suivante. Il rend IMPOSSIBLE qu'un
# test d'acceptation les reproduise : le harnais refuse de démarrer si l'une
# de ses valeurs pourrait toucher une installation qui n'est pas la sienne.
#
# Un test qui casse la production en la vérifiant est pire que pas de test.
#
# POURQUOI DES PRÉDICATS PURS, DANS UN FICHIER SÉPARÉ
# ---------------------------------------------------
# Chaque fonction ci-dessous ne lit RIEN : ni la machine, ni l'environnement,
# ni le disque. Elle reçoit une valeur, elle rend 0 (acceptée) ou 1 (refusée),
# et écrit sur la sortie standard la raison du refus. C'est ce qui permet à
# `tests/acceptance/test_garde_isolement.py` de les exercer sur les valeurs
# EXACTES de l'incident — 5432, 8000, 8100, `arac-api`, `/var/backups/arac` —
# à l'intérieur de `make test`, sans base, sans réseau, sans root.
#
# Les deux seules fonctions impures sont nommées comme telles (`garde_port_libre`,
# `garde_unite_absente`) : elles interrogent la machine, elles ne peuvent pas
# être hermétiques, et elles vivent à la fin du fichier.
#
# LA CONVENTION DE NOMMAGE, QUI EST LE VRAI MÉCANISME
# ---------------------------------------------------
# Tout ce qu'un essai pose porte le mot « acceptation » dans son nom : le
# cluster, le cerveau (donc la base, donc le préfixe des unités systemd), les
# dossiers. Ce n'est pas de la cosmétique — c'est ce qui rend le démontage
# DÉCIDABLE. Un `rm -rf` ou un `systemctl disable` ne s'exécute ici que sur une
# valeur qui a repassé ces gardes juste avant. Un harnais qui sait créer sans
# savoir prouver ce qu'il a le droit de détruire est un harnais qu'on ne
# relance pas deux fois.
# ===========================================================================

#: Le mot qui marque tout ce qui est jetable. Changer cette valeur change la
#: convention entière, et les gardes suivent : elle n'est écrite qu'ici.
GARDE_MARQUEUR="${GARDE_MARQUEUR:-acceptation}"

#: Ports de production, refusés nommément. Ce ne sont pas « des exemples » :
#: ce sont les trois numéros qui ont réellement servi à casser une machine.
GARDE_PORTS_INTERDITS="5432 8000 8100"

#: Plancher des ports de base. La règle de sécurité du chantier dit « ≥ 5460 » ;
#: on la rend mécanique plutôt que morale.
GARDE_PG_PORT_MIN=5460

#: Plancher des ports de service. Idem, « ≥ 8200 ».
GARDE_SERVICE_PORT_MIN=8200

#: Chemins qui appartiennent à une installation vivante. Aucun essai n'y écrit,
#: et surtout : aucun démontage ne les efface. `/var/backups/arac` est le plus
#: dangereux des cinq — l'unité de sauvegarde SUPPRIME ce qu'elle y trouve de
#: plus de N jours. Un essai qui hériterait de ce chemin effacerait les
#: sauvegardes de quelqu'un d'autre, en silence, et sur minuterie.
#
#: AUCUN CHEMIN D'INSTALLATION PARTICULIÈRE N'EST NOMMÉ ICI, ET C'EST VOULU.
#: La première version listait le répertoire du cerveau qui a servi à écrire ce
#: framework. C'était doublement faux : cela publiait le chemin privé de
#: quelqu'un (l'assertion F1 l'a refusé, et elle a eu raison), et cela ne
#: protégeait personne d'autre — le lecteur qui installe ailleurs n'y aurait
#: pas trouvé le sien. Ce qui protège, c'est la règle du marqueur : un chemin
#: sans « acceptation » est refusé, où qu'il soit. La liste ci-dessous ne
#: couvre donc que les répertoires SYSTÈME, les mêmes sur toutes les machines.
GARDE_CHEMINS_INTERDITS="/ /etc /etc/arac /var /var/log /var/log/arac /var/lib /var/lib/arac /var/backups /var/backups/arac /opt /root /home /usr /srv /tmp /var/tmp"

#: N'ÉCRIT QUE LE MESSAGE, ET REND 0.
#:
#: Le réflexe naturel est de lui faire rendre 1, pour écrire
#: `condition && _garde_refus "…" && return 1`. C'est un piège, et il était
#: dans la première version de ce fichier : `&&` n'exécute la suite que si ce
#: qui précède a RÉUSSI. Avec un `_garde_refus` qui rend 1, le `return 1` ne
#: s'exécute jamais — la garde affiche son refus, poursuit, et rend le code de
#: son DERNIER contrôle. C'est-à-dire une garde qui parle et n'arrête rien :
#: exactement la classe de faute que ce fichier existe pour empêcher.
#: Elle rend donc 0, et chaque refus s'écrit `{ _garde_refus "…"; return 1; }`.
_garde_refus() { printf 'REFUS : %s\n' "$1"; return 0; }

# ---------------------------------------------------------------------------
# Prédicats purs
# ---------------------------------------------------------------------------

#: Un entier décimal, et rien d'autre. `[[ $x =~ ^[0-9]+$ ]]` plutôt qu'une
#: comparaison arithmétique : sous `set -u`, `(( "abc" > 5 ))` ne rend pas
#: « faux », il rend une ERREUR, et le harnais mourrait SUR la garde au lieu
#: d'être refusé PAR elle.
garde_entier() { # valeur nom
    local v="${1-}" nom="${2:-valeur}"
    [[ "$v" =~ ^[0-9]+$ ]] || { _garde_refus "$nom « $v » n'est pas un entier."; return 1; }
    return 0
}

#: LE PORT DE LA BASE.
#: Refuse 5432 nommément, et tout ce qui est sous le plancher. Les deux
#: contrôles sont nécessaires : 5432 est déjà sous le plancher, mais le dire à
#: part fait que le message nomme la production plutôt qu'un seuil abstrait.
garde_port_pg() { # port
    local p="${1-}"
    garde_entier "$p" "le port PostgreSQL" || return 1
    if [[ "$p" == 5432 ]]; then
        _garde_refus "le port 5432 est celui du cluster de production. Ses rôles sont GLOBAUX au cluster : un bootstrap d'essai y réencoderait les mots de passe des rôles vivants."
        return 1
    fi
    if (( p < GARDE_PG_PORT_MIN )); then
        _garde_refus "le port PostgreSQL $p est sous le plancher $GARDE_PG_PORT_MIN — un essai se donne un port qui n'appartient à personne."
        return 1
    fi
    return 0
}

#: UN PORT DE SERVICE (API, cockpit).
#: 8000 et 8100 sont les valeurs par DÉFAUT de tous les cerveaux : les refuser
#: nommément est la moitié du travail, le plancher est l'autre moitié.
garde_port_service() { # port nom
    local p="${1-}" nom="${2:-service}"
    garde_entier "$p" "le port de $nom" || return 1
    local interdit
    for interdit in $GARDE_PORTS_INTERDITS; do
        if [[ "$p" == "$interdit" ]]; then
            _garde_refus "le port $p ($nom) est un port de production. Une unité d'essai qui le lie fait redémarrer le service légitime en boucle, et son /healthz répond 200 — depuis l'usurpateur."
            return 1
        fi
    done
    if (( p < GARDE_SERVICE_PORT_MIN )); then
        _garde_refus "le port $p ($nom) est sous le plancher $GARDE_SERVICE_PORT_MIN."
        return 1
    fi
    return 0
}

#: LE NOM DU CERVEAU D'ESSAI.
#: Il commande tout le reste : la base en est déduite (`tr -c a-zA-Z0-9 _`),
#: le préfixe des unités systemd en est déduit, le dossier des secrets aussi.
#: L'exiger marqué ici évite d'avoir à le revérifier trois fois plus loin.
garde_nom_cerveau() { # nom
    local n="${1-}"
    if [[ -z "$n" ]]; then _garde_refus "le nom du cerveau est vide."; return 1; fi
    if [[ "$n" != *"$GARDE_MARQUEUR"* ]]; then
        _garde_refus "le nom de cerveau « $n » ne porte pas « $GARDE_MARQUEUR » : rien ne distinguerait sa base, ses secrets et ses unités de ceux d'un cerveau vivant."
        return 1
    fi
    if [[ ! "$n" =~ ^[a-z][a-z0-9-]*$ ]]; then
        _garde_refus "le nom de cerveau « $n » n'est pas un identifiant simple (minuscules, chiffres, tirets)."
        return 1
    fi
    return 0
}

#: LE NOM DU CLUSTER PostgreSQL.
#: `pg_createcluster` accepte à peu près tout ; `pg_dropcluster` aussi. C'est
#: exactement pour cela qu'on borne le nom : le démontage fait un
#: `pg_dropcluster --stop`, geste irréversible, et il ne doit pouvoir viser
#: qu'un cluster que ce harnais a lui-même créé.
garde_nom_cluster() { # nom
    local n="${1-}"
    if [[ -z "$n" ]]; then _garde_refus "le nom du cluster est vide."; return 1; fi
    if [[ "$n" == main ]]; then
        _garde_refus "« main » est le cluster de production. pg_dropcluster ne se rejoue pas."
        return 1
    fi
    if [[ "$n" != *"$GARDE_MARQUEUR"* ]]; then
        _garde_refus "le cluster « $n » ne porte pas « $GARDE_MARQUEUR » — le démontage refuse de détruire ce qu'il n'a pas créé."
        return 1
    fi
    if [[ ! "$n" =~ ^[a-z][a-z0-9]*$ ]]; then
        _garde_refus "le nom de cluster « $n » n'est pas un identifiant simple."
        return 1
    fi
    return 0
}

#: LE PRÉFIXE DES UNITÉS systemd.
#: Le bootstrap le calcule : `${ARAC_ROLE_PREFIX}-${ARAC_DB}`, soit
#: `arac-<base>`. Un cerveau nommé « acceptation-ab12 » donne donc
#: `arac-acceptation_ab12-api`. Ce qu'on refuse ici, c'est le cas où ce calcul
#: rendrait un nom d'unité de production — `arac-api`, `arac-control-center` —
#: parce que le démontage fait `systemctl disable --now` et `rm` dessus.
garde_prefixe_unite() { # prefixe
    local p="${1-}"
    if [[ -z "$p" ]]; then _garde_refus "le préfixe d'unité est vide."; return 1; fi
    case "$p" in
        arac|arac-api|arac-control-center|arac-cycle|arac-curator|arac-sauvegarde)
            _garde_refus "« $p » est un nom d'unité de production."
            return 1 ;;
    esac
    if [[ "$p" != *"$GARDE_MARQUEUR"* ]]; then
        _garde_refus "le préfixe d'unité « $p » ne porte pas « $GARDE_MARQUEUR » : le démontage ne saurait pas distinguer ces unités de celles d'un cerveau vivant."
        return 1
    fi
    if [[ ! "$p" =~ ^[a-z][a-z0-9_-]*$ ]]; then
        _garde_refus "le préfixe d'unité « $p » n'est pas un identifiant simple."
        return 1
    fi
    return 0
}

#: UN NOM D'UTILISATEUR SYSTÈME QUE LE DÉMONTAGE AURA LE DROIT DE SUPPRIMER.
#:
#: Le harnais ne réutilise PAS `arac` et `aracagent` — les comptes sous
#: lesquels tournent les services d'un cerveau vivant. Il crée les siens, et
#: les supprime à la fin. `userdel` est aussi irréversible que
#: `pg_dropcluster` : le nom doit donc porter le marqueur, et les deux comptes
#: de production sont refusés nommément plutôt que par déduction.
garde_nom_systeme() { # nom role
    local n="${1-}" role="${2:-compte}"
    if [[ -z "$n" ]]; then _garde_refus "le $role est vide."; return 1; fi
    case "$n" in
        root|postgres|arac|aracagent|daemon|nobody|www-data)
            _garde_refus "« $n » est un compte système ou de production. userdel ne se rejoue pas."
            return 1 ;;
    esac
    if [[ "$n" != *"$GARDE_MARQUEUR"* ]]; then
        _garde_refus "le $role « $n » ne porte pas « $GARDE_MARQUEUR » — le démontage refuse de supprimer un compte qu'il n'a pas créé."
        return 1
    fi
    # `useradd` refuse au-delà de 32 caractères, et le refus arrive au milieu
    # de l'installation plutôt qu'ici. Autant le dire tout de suite.
    if [[ ! "$n" =~ ^[a-z][a-z0-9]{0,30}$ ]]; then
        _garde_refus "le $role « $n » n'est pas un nom de compte acceptable (minuscules et chiffres, 31 caractères au plus)."
        return 1
    fi
    return 0
}

#: UN CHEMIN QUE LE DÉMONTAGE AURA LE DROIT D'EFFACER.
#:
#: Quatre conditions, et les quatre comptent :
#:   · absolu — un `rm -rf` sur un chemin relatif efface depuis le répertoire
#:     courant, qui n'est pas une notion stable dans un script ;
#:   · sans « .. » — sinon la vérification porte sur un chemin, et l'effacement
#:     sur un autre ;
#:   · marqué — il porte « acceptation », donc il vient de ce harnais ;
#:   · pas un chemin système — la liste plus haut est explicite, et elle
#:     contient les répertoires PARENTS autant que les cibles : `/var/log`
#:     autant que `/var/log/arac`.
#:
#: On refuse enfin tout chemin de moins de trois composants : `/acceptation`
#: porte le marqueur et reste une racine.
garde_chemin_jetable() { # chemin role
    local c="${1-}" role="${2:-chemin}"
    if [[ -z "$c" ]]; then _garde_refus "le $role est vide."; return 1; fi
    if [[ "$c" != /* ]]; then _garde_refus "le $role « $c » n'est pas absolu."; return 1; fi
    if [[ "$c" == *..* ]]; then _garde_refus "le $role « $c » contient « .. »."; return 1; fi
    local interdit
    for interdit in $GARDE_CHEMINS_INTERDITS; do
        if [[ "$c" == "$interdit" ]]; then
            _garde_refus "le $role « $c » est un répertoire système ou de production. Le démontage l'effacerait."
            return 1
        fi
    done
    if [[ "$c" != *"$GARDE_MARQUEUR"* ]]; then
        _garde_refus "le $role « $c » ne porte pas « $GARDE_MARQUEUR » : le démontage refuse d'effacer ce qu'il n'a pas créé."
        return 1
    fi
    # Trois composants au minimum : /a/b/c. `${c//[!\/]/}` ne garde que les
    # barres obliques ; on en compte la longueur.
    local barres="${c//[!\/]/}"
    if (( ${#barres} < 2 )); then
        _garde_refus "le $role « $c » est trop haut dans l'arborescence (moins de trois composants)."
        return 1
    fi
    return 0
}

#: TOUTES LES GARDES PURES, EN UN GESTE.
#: Rend 0 si l'ensemble des valeurs est acceptable, 1 sinon — et affiche TOUS
#: les refus, pas seulement le premier : celui qui corrige veut la liste
#: entière, pas une découverte par lancement.
garde_isolement_valeurs() { # port_pg port_api port_cc cerveau cluster prefixe u_service u_agent chemins...
    local port_pg="${1-}" port_api="${2-}" port_cc="${3-}" cerveau="${4-}" cluster="${5-}" prefixe="${6-}"
    local u_service="${7-}" u_agent="${8-}"
    shift 8 2>/dev/null || shift $#
    local refus=0 c
    garde_port_pg       "$port_pg"                 || refus=1
    garde_port_service  "$port_api"     "l'API"    || refus=1
    garde_port_service  "$port_cc"      "le cockpit" || refus=1
    garde_nom_cerveau   "$cerveau"                 || refus=1
    garde_nom_cluster   "$cluster"                 || refus=1
    garde_prefixe_unite "$prefixe"                 || refus=1
    garde_nom_systeme   "$u_service" "compte des services" || refus=1
    garde_nom_systeme   "$u_agent"   "compte des cycles"   || refus=1
    if [[ -n "$port_api" && "$port_api" == "$port_cc" ]]; then
        _garde_refus "l'API et le cockpit demandent le même port ($port_api)."
        refus=1
    fi
    for c in "$@"; do
        garde_chemin_jetable "$c" "chemin jetable" || refus=1
    done
    return "$refus"
}

# ---------------------------------------------------------------------------
# Les deux gardes IMPURES — elles interrogent la machine
# ---------------------------------------------------------------------------
#
# Elles ne peuvent pas être hermétiques, donc elles sont ici, séparées, et le
# test unitaire ne les exerce pas. Ce qu'elles vérifient est pourtant la moitié
# de la leçon numéro 2 : un port libre AU MOMENT du contrôle, pas « un port
# qu'on croit à nous ».

#: Personne n'écoute-t-il déjà sur ce port ?
#: `ss` absent : on ne conclut RIEN et on refuse. Ne pas savoir n'est pas
#: « c'est libre » — c'est précisément la confusion qui a fait qu'un /healthz
#: à 200 a été lu comme une bonne nouvelle.
garde_port_libre() { # port role
    local p="${1-}" role="${2:-service}"
    if ! command -v ss >/dev/null 2>&1; then
        _garde_refus "ss est absent : impossible de constater que le port $p ($role) est libre. On refuse plutôt que de supposer."
        return 1
    fi
    local ligne
    # Aucun tuyau : `head` fermerait la lecture au premier appariement et `ss`,
    # qui n'a pas fini d'écrire, mourrait de SIGPIPE. Sous `pipefail`, la garde
    # rendrait alors 141 — « je n'ai pas pu savoir » déguisé en « c'est libre ».
    ligne="$(ss -ltnH "sport = :$p" 2>/dev/null)"; ligne="${ligne%%$'\n'*}"
    if [[ -n "$ligne" ]]; then
        _garde_refus "le port $p ($role) est déjà tenu : $ligne"
        return 1
    fi
    return 0
}

#: Cette unité systemd existe-t-elle déjà ?
#: Si oui, elle n'est pas à nous : on ne l'écrase pas, et surtout on ne la
#: DÉMONTERA pas en croyant démonter la nôtre.
garde_unite_absente() { # unite
    local u="${1-}"
    command -v systemctl >/dev/null 2>&1 || return 0
    if [[ -e "/etc/systemd/system/$u" ]]; then
        _garde_refus "l'unité $u existe déjà — elle appartient à quelqu'un d'autre."
        return 1
    fi
    return 0
}

#: Ce cluster PostgreSQL existe-t-il déjà ?
garde_cluster_absent() { # version nom
    local v="${1-}" n="${2-}"
    command -v pg_lsclusters >/dev/null 2>&1 || return 0
    if pg_lsclusters -h 2>/dev/null | awk -v v="$v" -v n="$n" '$1==v && $2==n {t=1} END{exit !t}'; then
        _garde_refus "le cluster $v/$n existe déjà — ce harnais ne réutilise pas un cluster qu'il n'a pas créé."
        return 1
    fi
    return 0
}
