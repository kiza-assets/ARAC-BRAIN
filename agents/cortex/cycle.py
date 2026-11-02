"""cortex-cycle — l'oneshot circadien : UN spawn max, JSON strict, disposant.

Machine à états (DESIGN-CORTEX-V3 §1) — chaque transition est committée
IMMÉDIATEMENT dans `arac.run_receipts` (write-ahead) :

  NO-GO SpendGuard        -> receipt(skipped, raison)         exit 0
  GO                      -> receipt(started)
  pack vide               -> receipt(empty)                   exit 0 (issue modale)
  pack prêt + before_spawn-> receipt(spawning, est, pack)     COMMIT AVANT exec
  spawn KO / stop quota   -> receipt(spawn_failed)            curseurs INTOUCHÉS
  sortie invalide         -> receipt(quarantined + bytea) + bump retry des
                             conversations du pack (anti-poison) + alerte
  dispose                 -> receipt(disposing) ; commit PAR conversation
  API down mid-dispose    -> receipt(dispose_interrupted)     reprise idempotente
  fin                     -> receipt(done, compteurs)

Le kill-switch fichier et les 3 freins fail-closed (env + flag DB + kill)
sont INCHANGÉS (SpendGuard). DB down => aucun spawn possible (fail-closed).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import arac_runtime  # noqa: E402

import psycopg  # noqa: E402

from agents.lib import spend_guard as sg  # noqa: E402
from app.journal import installer_garde_journal, raison  # noqa: E402
from agents.lib import paid_ai_flag  # noqa: E402
from agents.lib import runner_lock  # noqa: E402

from agents.cortex import contract, dispose, review_queue, value_gate  # noqa: E402
from agents.cortex.review_queue import PLACEHOLDER_SCOPE  # noqa: E402
from agents.cortex import pack as pack_mod  # noqa: E402
from agents.cortex.prompt import (  # noqa: E402
    CORTEX_SYSTEM_PROMPT,
    CORTEX_USER_TEMPLATE,
)
from agents.lib import claude_cli, curator_lib_v2  # noqa: E402
from agents.lib.claude_cli import run_claude_subprocess  # noqa: E402
from agents.lib.token_count import count_tokens  # noqa: E402
from app.schemas.scope import Scope  # noqa: E402

logger = logging.getLogger("arac.cortex.cycle")
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
# LE GARDE DU JOURNAL. Ce module est un `ExecStart` : tout ce qu'il écrit sur
# stderr part dans journald, un magasin partagé par la machine que la
# désinstallation ne sait pas purger. `_errors_pour_journal` protégeait déjà
# les erreurs de contrat ; le filtre protège tout le reste, y compris les
# traces d'exception — c'est là que psycopg range « Failing row contains (…) ».
installer_garde_journal()

_VALID_SCOPES: frozenset[str] = frozenset(s.value for s in Scope)
_VALID_SCOPES_BLOCK = "\n".join(f"  - {s.value}" for s in Scope)
_DEFAULT_MODEL = os.environ.get("ARAC_CURATOR_MODEL", "claude-sonnet-4-5")
_NODE_ID = os.environ.get("ARAC_NODE_ID", "arac-curator")
#: Nom de la variable qui porte le fuseau du cerveau, et son repli.
#: MÊME source que le cockpit (``control_center.config.cycle_tz``) et que les
#: minuteries systemd posées par le bootstrap.
CYCLE_TZ_ENV = "ARAC_CYCLE_TZ"
CYCLE_TZ_FALLBACK = "UTC"


def cycle_tz() -> ZoneInfo:
    """Le fuseau dans lequel se découpe une « journée » de ce cerveau.

    POURQUOI CE N'EST PLUS UNE CONSTANTE
    ------------------------------------
    Ce module portait un fuseau IANA gravé dans une constante. Les créneaux
    circadiens (04:00, 13:00, 21:00) étaient donc découpés sur l'horloge du pays
    où ce fichier a été écrit, pour tout le monde : à dix fuseaux de là, le
    créneau « nuit » tombait en fin d'après-midi. La documentation, elle, promet
    ``ARAC_CYCLE_TZ`` depuis le début — le code ne la lisait simplement pas.

    Le repli est UTC, et il est EXPLICITE : quand rien n'est déclaré, mieux vaut
    un fuseau visiblement neutre qu'un fuseau plausible et faux. Un nom inconnu de
    la base tzdata retombe sur le même repli plutôt que de faire tomber le cycle —
    un fuseau illisible ne doit pas empêcher le cerveau de tourner.

    Lu à CHAQUE appel : changer le fuseau ne demande pas de redémarrer le service.
    """
    declared = (os.environ.get(CYCLE_TZ_ENV) or "").strip()
    if declared:
        try:
            return ZoneInfo(declared)
        except Exception:  # noqa: BLE001 — un fuseau inconnu n'est pas une panne
            pass
    return ZoneInfo(CYCLE_TZ_FALLBACK)


def _log(event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, ensure_ascii=False, default=str))


def chemin_du_coffre() -> str:
    """Le fichier d'environnement de CE cerveau, nommé aussi précisément que possible.

    Même règle que `app.auth.chemin_du_coffre` : sur une machine à deux
    cerveaux, « /etc/arac/<votre-base>/arac.env » oblige à deviner, et deviner
    c'est aller regarder dans le coffre du voisin. On ne retombe sur le
    gabarit que hors unité systemd.
    """
    depuis_env = os.environ.get("ARAC_ENV_FILE", "").strip()
    if depuis_env:
        return depuis_env
    base = os.environ.get("ARAC_DB", "").strip()
    if base:
        return f"/etc/arac/{base}/arac.env"
    return sg.GABARIT_FICHIER_ENV


def _dire_le_refus(decision: Any) -> None:
    """Un refus de préflight, écrit pour un humain — pas seulement un code.

    « Je n'ai pas pu » n'est ni « c'est bon » ni « c'est cassé » : le journal
    doit porter la phrase ET le geste. C'est la seule chose que verra qui
    vient de taper `sudo systemctl start arac-<base>-cycle.service` puis
    `journalctl -u …`.
    """
    remede = decision.remede or (
        "aucun geste ne lève ce refus-ci : il a fait son travail (durée ou "
        "plafond de run atteint). Le code exact est dans l'événement "
        "`cortex.preflight` du journal, juste au-dessus.")
    logger.warning("ARAC cortex — aucun travail. %s", remede)


def _dire_le_creneau_deja_pris(slot_key: str) -> None:
    """Le créneau est tenu par un run qui a COMMENCÉ — et on dit la valve.

    Depuis le correctif de `create_receipt`, ce cas ne se produit plus pour un
    reçu qui n'a rien dépensé : il est repris. Il reste donc pour ce qu'il a
    toujours voulu dire — deux tirs sur le même créneau — et la sortie
    silencieuse était un mur. `ARAC_CORTEX_FORCE_MANUAL=1` rejoue un cycle
    sans attendre l'horaire suivant ; elle n'était écrite nulle part.
    """
    _log("cortex.duplicate_slot", slot_key=slot_key)
    logger.warning(
        "ARAC cortex — aucun travail : le créneau %s a déjà son reçu (un cycle "
        "l'a commencé). Pour rejouer MAINTENANT sans attendre le prochain "
        "horaire, posez la valve dans le fichier d'environnement de ce cerveau "
        "(%s) : ARAC_CORTEX_FORCE_MANUAL=1, relancez le service, puis RETIREZ "
        "la ligne — laissée en place, chaque tir de la minuterie ouvrirait un "
        "créneau neuf au lieu d'un par horaire.",
        slot_key, chemin_du_coffre())


def _errors_pour_journal(errors: Any) -> list[str]:
    """Les erreurs de contrat, RÉDUITES à ce qui peut rester dans journald.

    LE PROBLÈME. `_log()` écrit dans le journal systemd — un magasin PARTAGÉ
    par la machine, lisible par tout compte du groupe `systemd-journal`,
    conservé des semaines, et que le §13 de la désinstallation ne peut pas
    purger unité par unité (`journalctl --vacuum-*` travaille sur des FICHIERS,
    qui portent aussi le journal du voisin). Or `contract._validate_atom` écho
    la valeur fautive dans deux de ses erreurs — `key_invalid:{key!r}` et
    `scope_invalid:{scope!r}` — et ces erreurs partaient telles quelles dans
    `cortex.quarantined`. La clé d'un atome est proposée par le LLM à partir de
    la conversation de quelqu'un : « aucune clé ne doit être écrite en clair
    dans un artefact durable » (invariant I5 / règle V0.107,
    `dedup_thresholds.key_sha8`), et `dispose._sanitize_error_body` nomme le
    destinataire à protéger : la revue humaine passe par la DB, « JAMAIS via
    journald ».

    LE REMÈDE, ET SON SENS. La liste COMPLÈTE, valeurs comprises, continue
    d'être écrite dans `run_receipts.quarantine_errors` — en base, sous les
    droits du cerveau, et elle part avec lui à la désinstallation. Ce qui va au
    journal garde le CODE de la règle violée (c'est lui qui dit quoi corriger)
    et remplace la valeur par son empreinte sha8 — la même que partout
    ailleurs, donc deux occurrences de la même valeur restent reconnaissables.
    La ligne porte déjà `receipt_id` : qui veut la valeur sait où la lire.

    FERMÉ PAR DÉFAUT. On ne tient pas la liste des codes qui échoueraient une
    valeur sensible — une liste oublie toujours, et ce qu'elle oublie est
    précisément ce que personne n'avait imaginé. Tout ce qui suit le premier
    « : » est donc haché, SAUF deux formes dont on peut DÉMONTRER qu'elles ne
    portent rien : une suite de chiffres (un compte, un plafond), et une
    empreinte déjà calculée en amont (`sha8=…`), qu'un second hachage rendrait
    seulement incomparable.
    """
    out: list[str] = []
    for err in (errors or []):
        texte = err if isinstance(err, str) else str(err)
        code, sep, valeur = texte.partition(":")
        if not sep:
            out.append(code)
        elif valeur.isdigit() or valeur.startswith("sha8="):
            out.append(texte)
        else:
            # `contract` écrit ses valeurs en `repr` : la clé arrive entourée de
            # quotes. On les retire AVANT de hacher, sinon l'empreinte du
            # journal ne serait comparable à aucune autre du produit —
            # `key_sha8("abc")` et un hachage de `"'abc'"` ne se rencontrent
            # jamais. Une valeur dont le repr échappe des caractères garde son
            # empreinte propre : elle reste incomparable, mais elle ne révèle
            # toujours rien, et c'est l'ordre des priorités.
            nu = valeur
            if len(nu) >= 2 and nu[0] == nu[-1] and nu[0] in ("'", '"'):
                nu = nu[1:-1]
            out.append(f"{code}:sha8={hashlib.sha256(nu.encode('utf-8')).hexdigest()[:8]}")
    return out


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


# Fix round-1 (finding R2/C5) : SANS log d'armement, « flag ON mais cas jamais
# rencontré » et « flag jamais armé » sont INDISTINGUABLES dans journald — on
# peut conclure à tort qu'un correctif est mort. Chaque run logge donc l'état
# EXACT des flags de fidélité et de pack qu'il a lus (env pur, lu à chaque run).
_OBSERVED_FLAGS = (
    "ARAC_CORTEX_RUNREF_LENIENT",
    "ARAC_CORTEX_EMPTY_DROP_TOLERANT",
    "ARAC_CORTEX_UID_NEARMATCH",
    "ARAC_CORTEX_DEDUP_UID_STRICT",
    "ARAC_CORTEX_FORCE_MANUAL",
    "ARAC_PACK_DROP_EMPTY",
    "ARAC_PACK_STRICT_BOUNDARIES",
    "ARAC_PACK_SOURCE_FAIR",
    "ARAC_PACK_FILL_FLOOR",
    "ARAC_VALUE_GATE_SHADOW",
    # Fix round-2 (finding F7) : flag BOOLÉEN du chemin cortex, lu par
    # `dispose._coverage_v2_enabled()` — il change la disposition terminale
    # (park vs drain+exclusion low_yield) et il est ARMÉ EN PROD. Son
    # absence ici laissait ouvert, pour le seul flag de disposition réellement
    # actif pendant le soak, le trou que R2 était censé fermer.
    "ARAC_DISPOSE_COVERAGE_V2",
)
# Compteurs de fidélité produits par `contract.validate_document` (clés
# ABSENTES quand rien n'a été toléré/réparé -> aucun bruit flag OFF).
_FIDELITY_KEYS = (
    "_runref_lenient_count", "_runref_declared_sha8",
    "_empty_ids_tolerated_count", "_empty_ids_tolerated",
    "_uid_nearmatch_count", "_uid_nearmatch_repairs",
)


def _flags_armed() -> dict[str, Any]:
    """État des flags observés — valeur brute pour les non-booléens (budget,
    caps : `ARAC_PACK_*` numériques ne sont pas dans la liste), booléen sinon."""
    return {name: _env_truthy(name) for name in _OBSERVED_FLAGS}


def _fidelity_counters(doc: dict[str, Any]) -> dict[str, Any]:
    """Compteurs de fidélité présents dans le document nettoyé (vide si aucun
    correctif n'a agi — cas nominal et cas « tous flags OFF »)."""
    return {k: doc[k] for k in _FIDELITY_KEYS if k in doc}


#: Nom de la variable qui porte les HEURES de digestion, et son repli.
#: C'est la MÊME variable que celle dont le bootstrap tire les ``OnCalendar=``
#: de la minuterie systemd : la minuterie tire, ce module doit reconnaître le
#: coup de feu. Deux listes d'heures — une dans l'unité, une dans le code —
#: n'auraient aucune raison de rester d'accord.
CYCLES_ENV = "ARAC_CYCLES"
CYCLES_FALLBACK = "04:00 13:00 21:00"

#: Combien de temps AVANT et APRÈS l'heure déclarée un tir compte encore comme
#: ce créneau-là. Le retard toléré est plus généreux que l'avance : une
#: minuterie ``Persistent=true`` rattrape APRÈS coup (machine éteinte, service
#: retardé), elle n'anticipe jamais.
_AVANCE_MIN = 2 * 60
_RETARD_MIN = 4 * 60


def declared_cycles() -> tuple[tuple[int, int], ...]:
    """Les heures de digestion déclarées, en (heure, minute), triées.

    Lue à chaque appel, comme le fuseau : changer la cadence ne demande pas de
    redémarrer le service. Une valeur illisible retombe sur le trio par défaut
    plutôt que de faire tomber le cycle — une liste d'heures mal écrite est une
    faute de configuration, pas une panne du cerveau.
    """
    brut = (os.environ.get(CYCLES_ENV) or "").strip() or CYCLES_FALLBACK
    heures: set[tuple[int, int]] = set()
    for jeton in brut.replace(",", " ").split():
        try:
            h, _, m = jeton.partition(":")
            hh, mm = int(h), int(m or 0)
        except ValueError:
            continue
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            heures.add((hh, mm))
    if not heures:
        heures = {(4, 0), (13, 0), (21, 0)}
    return tuple(sorted(heures))


def resolve_slot(now_utc: datetime | None = None) -> tuple[str, str]:
    """(trigger, slot_key) — le créneau déclaré le plus proche, sinon `manual`.

    DEUX CHOSES SONT LUES, PAS GRAVÉES
    ----------------------------------
    1. Le FUSEAU (``cycle_tz()``) : « la nuit » doit être la nuit de celui à qui
       le cerveau appartient, pas celle du pays où ce fichier a été écrit.
    2. Les HEURES (``declared_cycles()``) : elles portaient les créneaux d'une
       seule installation — 04:00 / 13:00 / 21:00, en dur. La documentation
       promet pourtant ``ARAC_CYCLES`` réglable, et le bootstrap en tire la
       minuterie. Qui déclarait ``ARAC_CYCLES="09:00 18:00"`` voyait donc sa
       minuterie tirer à 09:00 et ce module répondre ``manual@<minute>`` : le
       slot_key n'était plus unique par jour, et comme la minuterie porte
       ``Persistent=true``, le rattrapage et le tir nominal obtenaient DEUX
       reçus distincts — deux cycles payants là où il n'en fallait qu'un.

    Le créneau retenu est le déclaré le plus proche parmi ceux dont la fenêtre
    contient l'instant. Une fenêtre ne franchit jamais minuit local : le
    slot_key porte la DATE locale, et un créneau qui déborderait sur le
    lendemain entrerait en collision avec celui du lendemain.
    """
    now = (now_utc or datetime.now(timezone.utc)).astimezone(cycle_tz())
    # Valve manuelle (« consolider maintenant ») : slot manuel unique à la
    # minute — ne consomme JAMAIS un créneau déclaré, utile après ré-armement
    # pour ne pas attendre le prochain cycle.
    manuel = f"manual@{now.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M')}"
    if os.environ.get("ARAC_CORTEX_FORCE_MANUAL", "").strip().lower() in ("1", "true", "yes"):
        return "manual", manuel

    minute_du_jour = now.hour * 60 + now.minute
    meilleur: tuple[int, str] | None = None
    for hh, mm in declared_cycles():
        cible = hh * 60 + mm
        debut = max(cible - _AVANCE_MIN, 0)
        fin = min(cible + _RETARD_MIN, 24 * 60)
        if not (debut <= minute_du_jour < fin):
            continue
        ecart = abs(minute_du_jour - cible)
        if meilleur is None or ecart < meilleur[0]:
            meilleur = (ecart, f"circadian_{hh:02d}{mm:02d}")
    if meilleur is None:
        return "manual", manuel
    trig = meilleur[1]
    return trig, f"{trig}@{now.strftime('%Y-%m-%d')}"


def _alert(text: str) -> None:
    """Alerte best-effort — un SEUL émetteur pour tout le cerveau.

    L'envoi passe par ``app.perception.ingest_watchdog.send_telegram``, importé
    normalement. Ce module était auparavant chargé À LA MAIN depuis un chemin
    de fichier construit à l'exécution — un chemin qui n'existe pas dans ce
    dépôt : chaque alerte du moteur tombait donc silencieusement dans
    ``cortex.alert_failed``, et le seul symptôme visible était l'absence
    d'alerte. Un import ordinaire échoue à l'import, pas à l'incident.

    Le résultat ``(ok, detail)`` est LOGGÉ, succès compris : sans log de
    succès, « l'alerte n'est pas partie » et « l'alerte est partie et personne
    ne l'a vue » sont indiscernables dans le journal.
    """
    try:
        from app.perception.ingest_watchdog import send_telegram

        ok, detail = send_telegram(text)
        _log("cortex.alert_sent", ok=bool(ok), detail=detail)
    except Exception as e:  # noqa: BLE001 — l'alerte ne casse jamais le cycle
        _log("cortex.alert_failed", error=raison(e))


def _pack_signature(pack_meta: list[dict[str, Any]]) -> str:
    """Signature déterministe d'un pack (bisection) : hash des
    `(uid, cursor_from, max_id)` de chaque conversation, TRIÉ (ordre-
    indépendant) — deux packs identiques (même sous-ensemble de conversations
    aux mêmes tranches) produisent la MÊME signature quel que soit l'ordre
    dans lequel `build_pack` les a énumérées."""
    key = sorted(
        (str(m.get("uid")), int(m.get("cursor_from") or 0), int(m.get("max_id") or 0))
        for m in pack_meta
    )
    blob = json.dumps(key, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


async def _bisected_max_conversations(conn, *, default: int, rid: int | None = None) -> int:
    """Bisection anti-poison NON-attribuable : relit les 2
    DERNIERS reçus. Si les deux sont `quarantined`, NON-attribuables
    (`quarantine_attributed_uids` vide/null — une quarantaine attribuable
    punit déjà la conversation coupable, le pack suivant se réduit tout seul
    par backoff, « split gratuit », pas besoin de bisection) ET portent la
    MÊME signature de pack (le pack REPRÉSENTÉ n'a pas bougé), le poison est
    structurel (pas une conversation précise) -> on BISECTE `max_conversations`
    du pack de CE cycle pour l'isoler. Sinon `default` inchangé.

    `rid` (revue adversariale, constat 2) : id du reçu 'started' du run
    COURANT, déjà committé write-ahead par `create_receipt` AVANT cet appel
    (cf `run_cycle`) — SUR UNE AUTRE CONNEXION, donc déjà visible ici. Sans
    l'exclure, `ORDER BY id DESC LIMIT 2` se relit LUI-MÊME comme le reçu le
    plus récent (`status='started'` != `'quarantined'`) -> retourne toujours
    `default`, la bisection anti-poison ne se déclenche JAMAIS. `rid=None`
    (tests hermétiques, ou appel hors `run_cycle`) désactive l'exclusion.
    """
    # Seuls les reçus TERMINAUX pour la bisection ('done'/'quarantined'/
    # 'spawn_failed') sont éligibles : un reçu en cours ('started'/'spawning'/
    # 'disposing') ou sans pack pertinent ('skipped'/'empty') ne doit jamais
    # compter parmi les « 2 derniers ».
    sql = ("SELECT id, status, pack, quarantine_attributed_uids "
           "FROM arac.run_receipts "
           "WHERE status IN ('done', 'quarantined', 'spawn_failed') ")
    params: tuple[Any, ...] = ()
    if rid is not None:
        sql += "AND id <> %s "
        params = (rid,)
    sql += "ORDER BY id DESC LIMIT 2"
    async with conn.cursor() as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()
    if len(rows) < 2:
        return default

    metas: list[list[dict[str, Any]]] = []
    for _rid, status, pack, attributed_uids in rows:
        if status != "quarantined" or attributed_uids:
            return default
        if not pack:
            return default
        meta = pack if isinstance(pack, list) else json.loads(pack)
        if not meta:
            return default
        metas.append(meta)

    if _pack_signature(metas[0]) != _pack_signature(metas[1]):
        return default
    n = len(metas[0])
    if n <= 1:
        return default  # déjà minimal, rien à bisecter

    # Bisection NON permanente : les reçus `empty` ne comptent pas comme
    # terminaux, donc les 2 mêmes quarantaines resteraient « les 2 derniers »
    # indéfiniment. Si un reçu `empty` leur est POSTÉRIEUR, la bisection a déjà
    # été tentée sans rien isoler -> on la relâche. Invariant : une bisection
    # s'applique au plus jusqu'au premier run vide.
    newest_quarantined_id = max(int(r[0]) for r in rows)
    empty_sql = ("SELECT id FROM arac.run_receipts "
                 "WHERE status = 'empty' AND id > %s ")
    empty_params: tuple[Any, ...] = (newest_quarantined_id,)
    if rid is not None:
        empty_sql += "AND id <> %s "
        empty_params += (rid,)
    empty_sql += "LIMIT 1"
    async with conn.cursor() as cur:
        await cur.execute(empty_sql, empty_params)
        empty_row = await cur.fetchone()
    if empty_row:
        _log("cortex.bisection_released", empty_receipt_id=empty_row[0],
             quarantined_receipt_id=newest_quarantined_id)
        return default
    return max(1, n // 2)


async def _punish_quarantine(
    conn,
    attributed_uids: list[str],
    pack_meta: list[dict[str, Any]],
    *,
    slot_key: str,
) -> list[str]:
    """Punition après quarantaine : CIBLÉE sur les conversations
    RÉELLEMENT attribuées (jamais tout le pack). `attributed_uids` vide (JSON
    illisible/tronqué…) -> AUCUNE punition. Un uid attribué mais ABSENT de CE
    pack (défense en profondeur — ne devrait pas arriver, `contract.py`
    n'attribue jamais un uid hors `presented`) est IGNORÉ, pas puni.

    Les conversations SAINES du pack (jamais dans `attributed_uids`) ne
    prennent PAS `retry_count + 1` : elles restent éligibles au prochain
    cycle, seul le poison recule en backoff (« split gratuit »).

    Retourne les uids EFFECTIVEMENT punis (logs, `quarantine_attributed_uids`
    du reçu, tests).
    """
    by_uid = {m["uid"]: m for m in pack_meta}
    punished: list[str] = []
    for uid in attributed_uids:
        meta = by_uid.get(uid)
        if meta is None:
            continue
        await dispose.curator_lib_v2.mark_curation_failed(
            conn, meta["conversation_id"],
            error=f"cortex_quarantine_attributed:{slot_key}")
        punished.append(uid)
    return punished


async def _shadow_scan_guarded(conn) -> None:
    """Value-gate SHADOW — enveloppe « jamais bloquante »
    RÉELLEMENT non bloquante (fix round-1) : un échec SQL de `shadow_scan`
    laisse la transaction psycopg AVORTÉE (InFailedSqlTransaction) — sans
    rollback, la requête SUIVANTE du cycle (bisection/pack) crashait : le
    shadow « observabilité pure » cassait tout le cycle (prouvé par repro
    psycopg réel, round 1). Le rollback est lui-même GARDÉ : s'il échoue
    (connexion morte), on logge — le cycle échouera fail-closed sur la
    requête suivante, curseurs intouchés."""
    try:
        await value_gate.shadow_scan(conn)
    except Exception as e:  # noqa: BLE001 — shadow, jamais bloquant
        _log("cortex.value_gate_shadow_failed",
             error=raison(e))
        try:
            await conn.rollback()
        except Exception as re:  # noqa: BLE001 — cf docstring (fail-closed)
            _log("cortex.value_gate_shadow_rollback_failed",
                 error=raison(re))


def _coverage_signals(
    progress: dict[str, Any], slot_key: str,
) -> list[tuple[str, str, list[str]]]:
    """Fonction PURE (fix round-1, régression de visibilité au flip) :
    dérive de `progress` (retour de `dispose_document`) les signaux de
    couverture qui méritent alerte humaine, en (event_log, texte_alerte,
    uids). Trois signaux, PARITÉ de visibilité park/exclusion :

      - `parked`   (flag OFF) : park après 3 omissions — comportement ;
      - `excluded` (flag ON)  : drain-exclusion low_yield — reçu 0023 posé
        par le disposant SANS acked, donc trigger 0029 inerte : SANS cette
        alerte l'exclusion était structurellement invisible (ni Telegram, ni
        audit_log, ni compteur lu) ;
      - `drained`  sans `excluded` (flag ON) : delta présenté drainé au
        seuil mais conversation PROTÉGÉE par la garde atoms_generated>0 —
        elle reste dans le gate ; signalé pour l'audit du soak.

    Les uids sont des identifiants techniques, jamais une PII (V0.107).

    Fix round-2 (finding F8) : les MÉTA-clés réservées de `progress` (préfixe
    `_`, ex. `_fidelity` — jamais un conversation_uid, qui est un UUID) sont
    filtrées EXPLICITEMENT ici, et les entrées non-dict ignorées : le filtrage
    ne repose plus sur la coïncidence « ces valeurs ne portent pas les clés
    lues »."""
    progress = {uid: p for uid, p in progress.items()
                if isinstance(uid, str) and not uid.startswith("_")
                and isinstance(p, dict)}
    out: list[tuple[str, str, list[str]]] = []
    parked = sorted(uid for uid, p in progress.items() if p.get("parked"))
    if parked:
        out.append((
            "cortex.omission_parked",
            f"🧠🅿️ ARAC cortex : conversation(s) PARQUÉE(S) après 3 "
            f"omissions consécutives ({slot_key}) — {', '.join(parked)} "
            f"— ré-armement humain requis (retry_count)",
            parked))
    excluded = sorted(uid for uid, p in progress.items() if p.get("excluded"))
    if excluded:
        out.append((
            "cortex.omission_excluded",
            f"🧠🗂️ ARAC cortex : conversation(s) EXCLUE(S) low-yield "
            f"({slot_key}) — {', '.join(excluded)} — >=3 présentations "
            f"complètes sans atome, curseur avancé au max présenté, reçu "
            f"0023 posé (réversible : exclude_conversation.py --reinclude ; "
            f"contenu conservé raw_messages)",
            excluded))
    drained = sorted(uid for uid, p in progress.items()
                     if p.get("drained") and not p.get("excluded"))
    if drained:
        out.append((
            "cortex.omission_drained_kept",
            f"🧠🚰 ARAC cortex : delta drainé SANS exclusion ({slot_key}) — "
            f"{', '.join(drained)} — seuil d'omissions atteint mais "
            f"atoms_generated>0 (garde dure) : la conversation reste "
            f"éligible pour son contenu futur",
            drained))
    return out


# Artefacts d'outillage reconnus (message géant sans connaissance) : début de
# contenu -> saut du message au lieu du parking. Jamais de regex.
TOOL_ARTIFACT_PREFIXES: tuple[str, ...] = ("Base directory for this skill:",)


_MIN_PREFIX_LEN = 12  # un préfixe trop court risquerait de sauter un vrai message
# Longueur de la tête lue en base (`left(content, N)`) : un préfixe plus long ne
# pourrait jamais correspondre, il est donc refusé explicitement.
_MAX_PREFIX_LEN = 120


def _prefix_fingerprint(prefix: str) -> str:
    """Empreinte courte d'un préfixe reconnu : le journal ne retient aucun
    contenu de message, seulement de quoi retrouver quelle règle a joué."""
    return hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:12]


def _tool_artifact_prefixes() -> tuple[str, ...]:
    """Préfixes reconnus : env `ARAC_OVERSIZED_SKIP_PREFIXES` (séparateur `|`),
    vide/absent = `TOOL_ARTIFACT_PREFIXES`. Préfixe < 12 ou > 120 caractères refusé."""
    raw = os.environ.get("ARAC_OVERSIZED_SKIP_PREFIXES", "").strip()
    parsed = []
    for p in (x.strip() for x in raw.split("|")):
        if not p:
            continue
        if len(p) < _MIN_PREFIX_LEN:
            _log("cortex.oversized_skip_prefix_refused", length=len(p))
            continue
        if len(p) > _MAX_PREFIX_LEN:
            _log("cortex.oversized_skip_prefix_too_long", length=len(p))
            continue
        parsed.append(p)
    return tuple(parsed) or TOOL_ARTIFACT_PREFIXES


async def _record_oversized_messages(
    conn, oversized: list[dict[str, Any]], *, slot_key: str,
) -> str:
    """Traite les messages BLOQUÉS par `pack.build_pack` : un
    message individuellement plus gros que le budget PLEIN ne peut jamais
    être présenté au digesteur -> trace en review-queue humaine + alerte.

    Écriture via `review_queue.insert_review_row` (module
    d'écriture dédié — MIGRÉ depuis l'INSERT ad-hoc) :
    best-effort (une file indisponible ne bloque jamais le cycle), PAS DE
    COMMIT ici (même discipline que `curator_lib_v2` : le caller committe).

    Finding revue sceptique fix-round-1 (ex-cycle.py:233) : cette fonction
    appelait `_alert` (BLOQUANT — hérite du retry, pire-cas ~55 s par
    chat_id) PAR message oversized, TRANSACTION OUVERTE (INSERTs review non
    committés pendant les sleeps, connexion psycopg tenue), dans le budget
    TimeoutStartSec=1200 déjà consommé par le spawn (900 s) -> risque de
    SIGTERM mid-run = créneau circadien brûlé (aggrave). Désormais :
    AUCUN _alert ici — la fonction RETOURNE un texte d'alerte AGRÉGÉ (une
    seule alerte quel que soit le nombre de messages, pire-cas ×1 au lieu de
    ×n) que le caller envoie APRÈS `conn.commit()` (plus jamais de sleep
    réseau transaction ouverte).

    `scope`/`kind`/`proposed_atom` sont NOT NULL sur la table mais n'ont pas
    de sens ici (le message n'a jamais atteint la digestion) : placeholders
    documentés `scope=PLACEHOLDER_SCOPE`, `kind="oversized_message"`, `proposed_atom`
    = le détail du message écarté (id/taille/tokens estimés — jamais son
    contenu brut).
    """
    skipped_ids: set[tuple[str, int]] = set()
    parked_ids: set[tuple[str, int]] = set()
    for om in oversized:
        # Dédoublonnage : une seule ligne `pending` par (conversation, message)
        # — sinon 1 INSERT par run pour le même message.
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT 1 FROM arac.digestion_review_queue "
                "WHERE conversation_uid = %s AND kind = 'oversized_message' "
                "AND status = 'pending' "
                "AND proposed_atom->>'message_id' = %s LIMIT 1",
                (om["uid"], str(int(om["message_id"]))),
            )
            already = await cur.fetchone()
        if already:
            _log("cortex.oversized_already_queued",
                 uid=om["uid"], message_id=om["message_id"])
        else:
            await review_queue.insert_review_row(
                conn, slot_key, om["uid"], "oversized_message",
                {"message_id": om["message_id"], "chars": om["chars"],
                 "est_tokens": om["est_tokens"]},
                None, PLACEHOLDER_SCOPE, "oversized_message",
            )
        # Artefact d'outillage reconnu : saut du seul message (curseur), sans parking.
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT left(content, %s) FROM arac.raw_messages "
                "WHERE id = %s AND role = 'user'",
                (_MAX_PREFIX_LEN, om["message_id"]),
            )
            head_row = await cur.fetchone()
        head = (head_row[0] or "").lstrip() if head_row else ""
        matched = next((p for p in _tool_artifact_prefixes()
                        if head.startswith(p)), None)
        if matched is not None:
            skipped = await curator_lib_v2.skip_tool_artifact_message(
                conn, om["uid"], om["message_id"])
            if skipped == 1:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE arac.digestion_review_queue "
                        "SET status = 'reviewed_dropped' "
                        "WHERE conversation_uid = %s "
                        "AND kind = 'oversized_message' AND status = 'pending' "
                        "AND proposed_atom->>'message_id' = %s",
                        (om["uid"], str(int(om["message_id"]))),
                    )
                # Journal : empreinte du préfixe, jamais le contenu du message.
                _log("cortex.oversized_tool_artifact_skipped",
                     uid=om["uid"], message_id=om["message_id"],
                     prefix_sha=_prefix_fingerprint(matched))
                skipped_ids.add((om["uid"], om["message_id"]))
                continue
            _log("cortex.oversized_tool_artifact_not_head_or_gap",
                 uid=om["uid"], message_id=om["message_id"],
                 prefix_sha=_prefix_fingerprint(matched))
        # Parking : la conversation ne monopolise plus le gate (curseur intouché).
        parked_rows = await curator_lib_v2.park_oversized_conversation(
            conn, om["uid"], om["message_id"])
        if isinstance(parked_rows, int) and parked_rows >= 1:
            parked_ids.add((om["uid"], om["message_id"]))
        else:
            _log("cortex.oversized_park_not_applied",
                 uid=om["uid"], message_id=om["message_id"])
    items = " ; ".join(
        f"conversation={om['uid']} message_id={om['message_id']} "
        f"~{om['est_tokens']} tokens ({om['chars']} chars) "
        + ("sauté (artefact d'outillage, curseur avancé)"
           if (om["uid"], om["message_id"]) in skipped_ids
           else "parqué 7 j (curseur gelé)"
           if (om["uid"], om["message_id"]) in parked_ids
           else "parking non appliqué")
        for om in oversized
    )
    return (f"🧠📦 ARAC cortex : {len(oversized)} message(s) surdimensionné(s) "
            f"({slot_key}) — {items} — voir "
            f"arac.digestion_review_queue")


async def run_cycle() -> int:
    # Moindre privilège : le cortex EST l'agent (receipts RW, curseur UPDATE,
    # brut SELECT) — jamais le rôle app (qui, lui, a INSERT sur le brut).
    dsn = os.environ.get("DATABASE_URL_AGENT") or os.environ.get("DATABASE_URL_APP")
    if not dsn:
        _log("cortex.no_dsn")
        return 2

    # Couche de liens projet (P-V6-017) : rafraîchir le registre de projet AVANT le spend
    # gate -> frais même quand l'IA payante est OFF (état nominal). Best-effort, connexion
    # séparée (autocommit) : ne casse JAMAIS le cortex. Coût 0 (embeddings déjà stockés).
    try:
        from app.services import project_registry as _projreg  # noqa: E402
        async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as _rconn:
            _rstats = await _projreg.recompute(_rconn)
        _log("project_registry.recompute", **_rstats)
    except Exception as _rexc:  # noqa: BLE001 — best-effort, jamais bloquant
        _log("project_registry.recompute_failed", error=type(_rexc).__name__)

    # Couche de liens atome<->atome — TROIS types, dont un INFÉRÉ :
    # `supersedes` et `same_thread` (certains), plus `semantic_neighbor`
    # (mutual-kNN, θ=0.25). Ce commentaire disait « increment 1 : arêtes
    # CERTAINES only » et « semantic_neighbor = inc.2 » : l'increment 2 est
    # arrivé, et `recompute` écrit les trois. Voir `app/services/atom_links.py`.
    # AVANT le spend gate -> frais même IA OFF. Best-effort, connexion séparée
    # (autocommit ; `recompute` ouvre sa propre transaction atomique) : ne casse
    # JAMAIS le cortex. Coût IA 0 (les embeddings sont déjà en base).
    try:
        from app.services import atom_links as _atomlinks  # noqa: E402
        async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as _lconn:
            _lstats = await _atomlinks.recompute(_lconn)
        _log("atom_links.recompute", **_lstats)
    except Exception as _lexc:  # noqa: BLE001 — best-effort, jamais bloquant
        _log("atom_links.recompute_failed", error=type(_lexc).__name__)

    trigger, slot_key = resolve_slot()
    model = _DEFAULT_MODEL
    ledger = sg.RunReceiptLedger(dsn)
    guard = sg.SpendGuard(sg.BudgetConfig.from_env(), ledger,
                          env_file=chemin_du_coffre())

    env_allow = _env_truthy("ARAC_ALLOW_PAID_AI")
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        config_enabled = await paid_ai_flag.read_paid_ai_enabled_async(conn)

        decision = guard.open_run(env_allow=env_allow, config_enabled=config_enabled)
        _log("cortex.preflight", allowed=decision.allowed, code=decision.code,
             trigger=trigger, slot_key=slot_key,
             **({"remede": decision.remede} if decision.remede else {}))
        # Armement (C5) : joignable au run par `slot_key`, émis AVANT toute
        # branche de sortie -> un flag armé sans effet reste démontrable.
        _log("cortex.flags_armed", slot_key=slot_key, **_flags_armed())
        if not decision.allowed:
            # UN CYCLE QUI NE FAIT RIEN DOIT DIRE POURQUOI, EN FRANÇAIS.
            # Le code seul (`master_switch_config_off`) n'apprend rien à qui
            # vient de taper `systemctl start` : la phrase et le geste
            # partent dans le journal, à côté du code.
            _dire_le_refus(decision)
            rid = ledger.create_receipt(slot_key=slot_key, trigger=trigger,
                                        model=model, status="skipped",
                                        skip_reason=decision.code)
            if rid is None:
                _dire_le_creneau_deja_pris(slot_key)
            return 0

        # LE VRAI PRÉREQUIS DE LA CURATION, CONSTATÉ AVANT DE RÉSERVER QUOI
        # QUE CE SOIT. Sans le binaire, le pack serait construit, le reçu
        # passerait en `spawning`, la dépense serait écrite en write-ahead —
        # et le spawn échouerait quatre fois en FileNotFoundError, lu comme un
        # « swap npm transitoire ». Un prérequis absent doit se dire par son
        # nom, pas se déguiser en incident passager.
        dispo, chemin_claude, remede_claude = claude_cli.curation_disponible()
        if not dispo:
            _log("cortex.curation_binaire_absent", chemin=chemin_claude,
                 remede=remede_claude, slot_key=slot_key)
            logger.error("ARAC cortex — %s", remede_claude)
            _alert(f"🧠🔌 ARAC cortex : la curation ne peut pas démarrer "
                   f"({slot_key}) — binaire introuvable : {chemin_claude}. "
                   f"{remede_claude}")
            ledger.create_receipt(slot_key=slot_key, trigger=trigger,
                                  model=model, status="skipped",
                                  skip_reason="curation_binaire_absent")
            return 0

        rid = ledger.create_receipt(slot_key=slot_key, trigger=trigger, model=model)
        if rid is None:
            _dire_le_creneau_deja_pris(slot_key)
            return 0

        # Value-gate en SHADOW LOG-ONLY, flag OFF par
        # défaut : score le backlog pending (lecture seule stricte) et logge
        # les candidats would-be-excluded pour VOTRE revue, AVANT tout
        # armement (l'exclusion réelle n'est pas implémentée). Un échec
        # du scan ne casse JAMAIS le cycle (observabilité pure).
        if _env_truthy("ARAC_VALUE_GATE_SHADOW"):
            await _shadow_scan_guarded(conn)

        max_conversations = await _bisected_max_conversations(
            conn, default=pack_mod.DEFAULT_MAX_CONVERSATIONS, rid=rid)
        if max_conversations != pack_mod.DEFAULT_MAX_CONVERSATIONS:
            _log("cortex.pack_bisected", max_conversations=max_conversations)
        built = await pack_mod.build_pack(conn, max_conversations=max_conversations)

        # Conservation-audit : ce que la construction du pack a
        # VU se remonte au reçu quelle que soit l'issue du cycle en aval
        # (spawn refusé/échoué, quarantaine, dispose…) — d'où le mark ICI,
        # avant toute branche de sortie.
        oversized = built.get("oversized_messages") or []
        if oversized:
            oversized_alert = await _record_oversized_messages(
                conn, oversized, slot_key=slot_key)
            await conn.commit()
            # Alerte APRÈS commit (finding fix-round-1) : le retry Telegram
            # ne tient plus jamais la transaction ouverte pendant ses
            # sleeps ; une seule alerte agrégée (pire-cas ×1, pas ×n).
            _alert(oversized_alert)
        ledger.mark(
            messages_reported=built.get("messages_reported", 0),
            messages_truncated=built.get("messages_truncated", 0),
            **({"oversized_messages": json.dumps(oversized, ensure_ascii=False, default=str)}
               if oversized else {}),
        )

        if not built["pack_meta"]:
            ledger.mark(status="empty", ended=True, outcome="empty")
            _log("cortex.empty")
            return 0

        system_prompt = CORTEX_SYSTEM_PROMPT.format(
            run_ref=slot_key, valid_scopes=_VALID_SCOPES_BLOCK)
        prompt = CORTEX_USER_TEMPLATE.format(
            known_atoms_block=built["known_atoms_block"],
            conversations_block=built["conversations_block"],
        )
        est = count_tokens(system_prompt) + count_tokens(prompt)

        gate = guard.before_spawn(est)
        if not gate.allowed:
            ledger.mark(status="skipped", ended=True, skip_reason=gate.code)
            _log("cortex.spawn_refused", code=gate.code, est=est)
            return 0

        # WRITE-AHEAD de la dépense : committé AVANT l'exec. Les tokens sont
        # comptés par record_spawn SEUL (les poser aussi ici doublerait le
        # compteur — mesuré sur le receipt #2 : 162k au lieu de 81k).
        ledger.mark(status="spawning",
                    pack=json.dumps(built["pack_meta"], default=str))
        # `items=len(pack_meta)` (correctif) : un seul spawn du
        # cortex circadien couvre TOUT le pack (pas de boucle par-item comme
        # batch_runner.py) — sans ce compte explicite, `max_items_per_day`/
        # `max_items_per_run` restaient inopérants pour ce chemin (cf
        # docstring `SpendGuard.record_spawn`).
        guard.record_spawn(tokens=est, duration_sec=0, items=len(built["pack_meta"]))
        _log("cortex.spawning", est_tokens=est, n_conversations=len(built["pack_meta"]))

        res = await run_claude_subprocess(
            prompt, timeout_sec=guard.config.per_spawn_timeout_sec,
            model=model, no_tools=True, system_prompt=system_prompt)

        cls = guard.classify_output(stdout=res.get("stdout"), stderr=res.get("stderr"),
                                    exit_code=res.get("exit_code", -1))
        if not res.get("ok") or cls["stop"]:
            reason = f"spawn:{cls['kind']}" if cls["stop"] else \
                     f"spawn:exit_{res.get('exit_code')}"
            ledger.mark(status="spawn_failed", ended=True, stop_reason=reason,
                        outcome=reason)
            # Alerte nommée (jusqu'ici muette) : distingue le
            # quota épuisé (attendu, rien à corriger) d'un échec dur (mérite
            # un oeil humain).
            if cls.get("quota_hit"):
                _alert(f"🧠⏳ ARAC cortex : quota Claude épuisé ({slot_key}) — "
                       f"spawn arrêté proprement, curseurs intouchés, reprise "
                       f"au prochain cycle sous intervalle mini")
            else:
                _alert(f"🧠💥 ARAC cortex : spawn KO ({slot_key}) — {reason} — "
                       f"curseurs intouchés, le prochain cycle re-tente")
            _log("cortex.spawn_failed", reason=reason,
                 duration_ms=res.get("duration_ms"), quota_hit=cls.get("quota_hit", False))
            return 0  # curseurs INTOUCHÉS — le prochain cycle re-tente

        stdout = res.get("stdout") or ""
        # Archive du stdout BRUT dans le reçu AVANT tout parsing : un crash du
        # disposant ne perd plus jamais la sortie payée (leçon receipt #5 —
        # reprise/diagnostic sans re-spawn).
        raw = stdout.encode("utf-8")[:1_048_576]
        ledger.mark(quarantine_output=raw,
                    quarantine_sha256=hashlib.sha256(raw).hexdigest())
        try:
            doc = contract.extract_json_object(stdout)
            doc = contract.validate_document(
                doc, expected_run_ref=slot_key, presented=built["presented"])
        except contract.ContractError as e:
            raw = stdout.encode("utf-8")[:1_048_576]
            attributed = sorted(getattr(e, "attributed_uids", None) or ())
            # Attribution du poison : punition CIBLÉE si
            # attribuable (les saines gardent retry_count intact -> restent
            # éligibles, split gratuit au pack suivant) ; AUCUNE punition
            # sinon (JSON illisible/tronqué… -> la bisection du prochain
            # cycle isole le poison structurel si ça persiste, cf
            # `_bisected_max_conversations`).
            punished = await _punish_quarantine(
                conn, attributed, built["pack_meta"], slot_key=slot_key)
            await conn.commit()
            ledger.mark(
                status="quarantined", ended=True,
                quarantine_output=raw,
                quarantine_sha256=hashlib.sha256(raw).hexdigest(),
                quarantine_errors=json.dumps(getattr(e, "errors", [str(e)])),
                outcome="quarantined",
                **({"quarantine_attributed_uids": json.dumps(punished)} if punished else {}),
            )
            if punished:
                _alert(f"🧠🧪 ARAC cortex : sortie LLM en QUARANTAINE ATTRIBUÉE "
                       f"({slot_key}) — conversation(s) fautive(s) : "
                       f"{', '.join(punished)} — le reste du pack reste éligible — "
                       f"voir run_receipts id={rid}")
            else:
                _alert(f"🧠🧪 ARAC cortex : sortie LLM en QUARANTAINE NON ATTRIBUABLE "
                       f"({slot_key}) — curseurs INTOUCHÉS, aucune punition — "
                       f"voir run_receipts id={rid}")
            _log("cortex.quarantined", receipt_id=rid,
                 errors=_errors_pour_journal(getattr(e, "errors", [str(e)])[:5]),
                 attributed_uids=attributed, punished=punished)
            return 0
        except Exception as e:  # noqa: BLE001 — JAMAIS un reçu ouvert orphelin
            # Fix round-3 (finding N1, défense en profondeur) : le parseur/
            # validateur travaille sur du JSON 100 % contrôlé par le LLM ; un
            # type inattendu pouvait y lever autre chose qu'une `ContractError`
            # (cas mesuré : `"atoms": 5` sous FIX C -> `TypeError`, cause racine
            # corrigée dans `contract._membership_proof_count`). Sans ce filet,
            # l'exception traversait `run_cycle` : le reçu restait au statut
            # `spawning` (ended_at NULL) -> spawn PAYÉ perdu sans trace
            # exploitable, bisection anti-poison DÉSARMÉE 2 cycles
            # (`_bisected_max_conversations` exige `quarantined`), et tuile
            # « run(s) ouvert(s) » du cockpit polluée indéfiniment
            # (`control_center/sql/perception_queries.py:121`).
            # Statut `quarantined` (pas de nouveau statut : la colonne porte un
            # CHECK, migration 0019) — sémantiquement exact : sortie
            # inexploitable, AUCUNE attribution, AUCUNE punition, curseurs
            # INTOUCHÉS. Le stdout brut est déjà archivé (mark ci-dessus).
            # On RE-LÈVE : le crash reste visible (unité systemd en échec),
            # seul le reçu orphelin disparaît.
            ledger.mark(
                status="quarantined", ended=True,
                quarantine_errors=json.dumps(
                    [f"contract_crashed:{type(e).__name__}:{e}"[:2000]]),
                outcome=f"contract_crashed:{type(e).__name__}",
            )
            _alert(f"🧠🛑 ARAC cortex : CRASH du contrat ({slot_key}) — "
                   f"{type(e).__name__} — sortie archivée, aucune punition, "
                   f"curseurs intouchés — voir run_receipts id={rid}")
            # LE TYPE, PAS LE MESSAGE. L'exception naît d'un JSON contrôlé de
            # bout en bout par le LLM : son message porte régulièrement le
            # fragment fautif (« invalid literal for int(): 'pénicilline' »),
            # c'est-à-dire de la conversation de quelqu'un, dans un journal que
            # la désinstallation ne sait pas purger. Le message complet reste
            # dans `run_receipts.quarantine_errors` (marqué juste au-dessus),
            # en base, avec le cerveau, et il part avec lui.
            _log("cortex.contract_crashed", receipt_id=rid,
                 error=type(e).__name__)
            raise

        ledger.mark(status="disposing")
        try:
            totals, progress = await dispose.dispose_document(
                conn, doc, built["presented"],
                run_ref=slot_key, node_id=_NODE_ID, valid_scopes=_VALID_SCOPES)
        except dispose.default_api.AtomsApiDown as e:
            ledger.mark(status="dispose_interrupted", ended=True,
                        stop_reason=f"api_down:{e}", outcome="dispose_interrupted")
            _alert(f"🧠⚠️ ARAC cortex : API atoms down en plein dispose ({slot_key}) "
                   f"— reprise idempotente au prochain cycle")
            _log("cortex.dispose_interrupted", raison=raison(e))
            return 0
        except Exception as e:  # noqa: BLE001 — JAMAIS un reçu ouvert orphelin
            ledger.mark(status="dispose_interrupted", ended=True,
                        stop_reason=f"crash:{type(e).__name__}:{e}",
                        outcome="dispose_interrupted")
            _alert(f"🧠🛑 ARAC cortex : crash du disposant ({slot_key}) — "
                   f"{type(e).__name__}, sortie archivée dans le reçu")
            _log("cortex.dispose_crashed", error=raison(e))
            raise

        # Oracle de couverture (oracle de couverture, fix round-1) : les issues
        # terminales de `dispose_document` qui méritent un oeil humain sont
        # alertées ICI — le module dispose est hermétique (zéro I/O externe).
        # Fix round-1 (régression de visibilité au flip) : le park (OFF)
        # alertait, le drain-exclusion (ON) était MUET (trigger 0029 inerte,
        # acked reste false ; compteur 'excluded' lu nulle part) — chaque
        # signal de couverture a désormais son alerte + son log nommé, à
        # parité de visibilité avec le park.
        for event, alert_text, uids in _coverage_signals(progress, slot_key):
            _alert(alert_text)
            _log(event, slot_key=slot_key, uids=uids)

        # Invariant receipts <-> atomes : ce que le reçu
        # prétend avoir créé/supersédé doit correspondre aux rows RÉELLEMENT
        # écrites dans `memory_atoms` pour CE run (détecte par ex. une API
        # qui répondrait 201 sans écrire réellement). Vérification
        # best-effort : une panne de LECTURE ici ne doit jamais transformer
        # un run par ailleurs réussi en crash — log + continue.
        try:
            atoms_in_db = await review_queue.count_atoms_for_run(conn, slot_key)
            invariant_ok, ecart = review_queue.check_receipt_atom_invariant(
                atoms_in_db=atoms_in_db,
                atoms_created=totals["atoms_created"],
                atoms_superseded=totals["atoms_superseded"])
            if not invariant_ok:
                expected = totals["atoms_created"] + totals["atoms_superseded"]
                _alert(f"🧠❗ ARAC cortex : RECEIPT_ATOM_MISMATCH ({slot_key}) — "
                       f"memory_atoms={atoms_in_db} attendu={expected} "
                       f"écart={ecart} — voir run_receipts id={rid}")
                _log("cortex.receipt_atom_mismatch", slot_key=slot_key,
                     receipt_id=rid, atoms_in_db=atoms_in_db,
                     expected=expected, ecart=ecart)
        except Exception as e:  # noqa: BLE001 — observabilité, jamais bloquant
            _log("cortex.receipt_atom_check_failed", error=raison(e))

        # Fix round-1 (finding R1/C4) : les compteurs de fidélité (A/B/C)
        # n'avaient AUCUN consommateur — ni colonne de reçu, ni log joignable à
        # un run : « combien de runs sauvés par B/C, lesquels » était
        # inrépondable depuis la DB, donc la « preuve mesurée » exigée avant
        # prod était impossible. Ils sont désormais (i) gravés dans le reçu
        # (jsonb `progress`, sous la clé réservée `_fidelity` — aucune
        # migration) et (ii) loggués avec le `slot_key`. Dict VIDE quand aucun
        # correctif n'a agi -> reçu bit-identique flags OFF.
        # Fix round-2 (finding F8) : la justification d'origine (« aucun
        # lecteur existant de cette colonne ») était FAUSSE — le cockpit lit
        # `progress` (`control_center/sql/perception_queries.py:122`). Impact
        # nul mesuré (ce lecteur ne sélectionne que les statuts
        # started/spawning/disposing/dispose_interrupted, or `_fidelity` n'est
        # écrit qu'au statut `done`), mais la forme persistée devient
        # polymorphe (map uid -> entrée + une clé réservée). CONVENTION posée
        # ici et respectée par `_coverage_signals` : toute clé de `progress`
        # préfixée `_` est une MÉTA-clé réservée, jamais un conversation_uid
        # (les uids sont des UUID, ils ne commencent jamais par `_`).
        fidelity = _fidelity_counters(doc)
        receipt_progress = dict(progress)
        if fidelity:
            receipt_progress["_fidelity"] = fidelity
        ledger.mark(status="done", ended=True, outcome="done",
                    progress=json.dumps(receipt_progress, ensure_ascii=False,
                                        default=str),
                    **{k: totals[k] for k in dispose.DisposeTotals.KEYS})
        _log("cortex.done", receipt_id=rid, **dict(totals),
             **({"fidelity": fidelity} if fidelity else {}))
        return 0


def main() -> int:
    import time as _time

    runtime_dir = os.environ.get("ARAC_BRAIN_RUNTIME_DIR", sg.DEFAULT_RUNTIME_DIR)
    os.makedirs(runtime_dir, exist_ok=True)
    lock_path = os.path.join(runtime_dir, "cortex-cycle.lock")
    run_id = f"cortex-{os.getpid()}-{int(_time.time())}"
    lk = runner_lock.acquire_lock(lock_path, run_id=run_id, owner=_NODE_ID,
                                  now_epoch=int(_time.time()), ttl_seconds=3600)
    if not lk.get("acquired"):
        _log("cortex.lock_busy", reason=lk.get("reason"))
        return 0
    try:
        return asyncio.run(run_cycle())
    finally:
        runner_lock.release_lock(lock_path, run_id=run_id)


if __name__ == "__main__":
    sys.exit(main())
