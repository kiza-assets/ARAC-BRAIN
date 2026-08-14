"""SpendGuard — garde-fou de dépense IA payante du cerveau ARAC (sobriété).

Rôle : UNIQUE point de décision « ai-je le droit de dépenser des tokens IA
payants maintenant, et combien de budget reste-t-il ? ». Placé AVANT chaque
spawn `claude` du curateur batch (`agents/cortex/cycle.py` — a remplacé
`agents/curator/batch_runner.py`, retiré lors du chantier « Perception V4 »). Sans lui, le curateur
spawnait Opus sans plafond (incident 2026-07 : 1108 spawns/14j).

Trois freins INDÉPENDANTS, tous fail-closed (en cas de doute → REFUS) :

  1. Master-switch      — DEUX interrupteurs, et il faut les DEUX :
                          · env `ARAC_ALLOW_PAID_AI`, posé dans le fichier
                            d'environnement du cerveau (/etc/arac/<base>/arac.env),
                            lu par l'unité systemd — « ce service a le droit » ;
                          · flag DB `arac.arac_config.paid_ai_enabled`, armé à
                            la main (`agents.lib.paid_ai_control arm --confirm`) —
                            « et moi, aujourd'hui, je l'autorise ».
                          Défaut : REFUS. Chaque refus repart avec le geste qui
                          l'ouvre (`remede_pour`) : le second interrupteur a
                          coûté à un utilisateur un cerveau qui n'apprenait
                          pas, faute d'être nommé nulle part.
  2. Kill-switch fichier — présence de `var/autonomy/KILL_PAID_AI` (créé par un
                          HUMAIN root ; l'agent ne peut que le LIRE). Jamais
                          supprimé automatiquement. Présent → STOP immédiat.
  3. Budget journalier   — ledger fichier atomique (par jour) : plafonds
                          spawns/jour, items/jour, tokens/jour, runs/jour,
                          intervalle mini entre runs. + plafonds PAR RUN :
                          items/run, tokens/run, durée/run.

Le module est PUR et DÉTERMINISTE : aucune lecture d'env ni de DB en interne
(le caller lit env+DB et passe des booléens), horloge et chemins INJECTABLES.
Seule I/O : lecture/écriture atomique du fichier ledger (confiné, 0600).

Réutilise la doctrine des primitives autonomie existantes :
  - kill_switch.is_active (confinement var/ + tempdir, fail-closed)
  - quota_guard (détection épuisement + backoff ≥ 15 min, jamais de martèlement)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

# Import des primitives autonomie (scripts/autonomy est ajouté au sys.path par
# le point d'entrée ; en test, conftest ajoute scripts/brain et scripts/memory,
# et scripts/autonomy est importé via chemin explicite ci-dessous si besoin).
import sys as _sys

import arac_runtime

from agents.lib import kill_switch  # noqa: E402
from agents.lib import quota_guard  # noqa: E402


# ---------------------------------------------------------------------------
# Emplacements par défaut (injectables)
# ---------------------------------------------------------------------------

# Kill-switch : sous var/ (root écrit, agent lit). Chemin ACCEPTÉ par
# kill_switch.resolve_switch_path (repo var/ ou tempdir).
DEFAULT_KILL_SWITCH = str(arac_runtime.var_dir() / "autonomy" / "KILL_PAID_AI")

# Ledger : sous un répertoire ÉCRIVABLE par l'agent aracagent. var/ est
# root:aracagent 2755 (agent ne peut pas écrire) — on loge donc le ledger sous
# data/aracagent-home (déjà dans ReadWritePaths du service, agent-writable).
# Overridable via ARAC_BRAIN_RUNTIME_DIR (ex. var/curator-runtime après chown).
DEFAULT_RUNTIME_DIR = os.path.join(
    str(arac_runtime.data_dir()), "agent-home", ".arac-runtime"
)
_LEDGER_BASENAME = "ai_spend_ledger.json"


# ---------------------------------------------------------------------------
# Configuration budget
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetConfig:
    """Plafonds de dépense IA. Tous surchargables par env (préfixe ARAC_*).

    Valeurs par défaut = preset « Sobre » (bien en-dessous du rythme incident
    ~79 spawns/jour). `ARAC_DAILY_AI_BUDGET` = budget de tokens (proxy INPUT,
    tiktoken o200k). Semaine : num spawns/jour est le frein le plus fidèle à la
    consommation de session d'abonnement — d'où max_spawns_per_day.
    """

    max_items_per_run: int = 5          # conversations traitées par run (batch)
    max_runs_per_day: int = 6           # runs de curation par jour
    max_spawns_per_day: int = 40        # spawns `claude` (chunks) par jour
    max_items_per_day: int = 30         # conversations par jour
    daily_token_budget: int = 500_000   # tokens INPUT/jour (ARAC_DAILY_AI_BUDGET)
    max_tokens_per_run: int = 150_000   # tokens INPUT par run
    max_runtime_sec: int = 900          # durée max d'un run (ARAC_MAX_AI_RUNTIME_SECONDS)
    min_minutes_between_runs: int = 30  # intervalle mini entre deux runs
    per_spawn_timeout_sec: int = 900    # timeout d'un subprocess claude (15 min)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "BudgetConfig":
        e = env if env is not None else os.environ

        def _int(name: str, default: int) -> int:
            raw = e.get(name)
            if raw is None or str(raw).strip() == "":
                return default
            try:
                return max(0, int(str(raw).strip()))
            except (TypeError, ValueError):
                return default

        return cls(
            max_items_per_run=_int("ARAC_MAX_ITEMS_PER_RUN", cls.max_items_per_run),
            max_runs_per_day=_int("ARAC_MAX_RUNS_PER_DAY", cls.max_runs_per_day),
            max_spawns_per_day=_int("ARAC_MAX_SPAWNS_PER_DAY", cls.max_spawns_per_day),
            max_items_per_day=_int("ARAC_MAX_ITEMS_PER_DAY", cls.max_items_per_day),
            daily_token_budget=_int("ARAC_DAILY_AI_BUDGET", cls.daily_token_budget),
            max_tokens_per_run=_int("ARAC_MAX_TOKENS_PER_RUN", cls.max_tokens_per_run),
            max_runtime_sec=_int("ARAC_MAX_AI_RUNTIME_SECONDS", cls.max_runtime_sec),
            min_minutes_between_runs=_int(
                "ARAC_MIN_MINUTES_BETWEEN_RUNS", cls.min_minutes_between_runs
            ),
            per_spawn_timeout_sec=_int(
                "ARAC_CURATOR_TIMEOUT_SEC", cls.per_spawn_timeout_sec
            ),
        )


@dataclass
class Decision:
    """Verdict d'une porte du guard.

    `remede` n'est pas décoratif : un cycle qui ne fait rien DOIT dire
    pourquoi et quoi taper. Voir `remede_pour()` juste en dessous.
    """

    allowed: bool
    code: str
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)
    remede: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "code": self.code,
            "reason": self.reason,
            **({"remede": self.remede} if self.remede else {}),
            **({"detail": self.detail} if self.detail else {}),
        }


# ---------------------------------------------------------------------------
# LES DEUX INTERRUPTEURS, DITS PAR LEUR NOM — ET LE GESTE QUI LES OUVRE.
#
# IL Y EN A DEUX, ET LE SECOND N'ÉTAIT NOMMÉ NULLE PART.
#
# Mesuré sur une installation neuve : on ingère ses conversations, on lance le
# cycle comme le guide le prescrit, rien ne se produit. Le journal dit
# `master_switch_env_off`. On pose `ARAC_ALLOW_PAID_AI=1` — le seul remède
# écrit — on relance, et le cycle refuse DE NOUVEAU, sous un code que la
# documentation n'écrivait nulle part : `master_switch_config_off`. Le second
# verrou vit en base (`arac.arac_config.paid_ai_enabled`) et ne s'ouvre que
# par une commande qu'aucune page ne nommait.
#
# Un refus qui ne dit pas LEQUEL des deux verrous arrête, OÙ il vit et QUEL
# geste l'ouvre n'est pas un garde-fou : c'est un mur muet. Ces gestes-ci
# voyagent donc AVEC la décision — journal, cockpit, sortie du cycle — au lieu
# d'attendre dans une page que personne ne lit au bon moment.
# ---------------------------------------------------------------------------

#: Chemin affiché quand le caller ne sait pas nommer le coffre de SON cerveau.
GABARIT_FICHIER_ENV = "/etc/arac/<votre-base>/arac.env"


def geste_control_plane(verbe: str, *, env_file: str | None = None,
                        home: str | None = None) -> str:
    """La commande RÉELLE du control-plane, telle qu'elle se tape.

    Elle ne suppose aucun raccourci installé : `arac-arm-paid-ai` existe sur
    la machine de l'auteur, pas sur celle du lecteur, et prescrire un
    raccourci qu'on n'a pas posé est exactement le défaut que ce dépôt
    poursuit ailleurs. Ce qui est nommé ici existe dans le dépôt lui-même.
    """
    racine = home or str(arac_runtime.home())
    coffre = env_file or GABARIT_FICHIER_ENV
    return (f"cd {racine} && sudo .venv/bin/python -m agents.lib.paid_ai_control "
            f"{verbe} --coffre {coffre}")


def remede_pour(code: str, *, env_file: str | None = None,
                kill_switch_path: str | None = None,
                home: str | None = None) -> str:
    """Le geste EXACT qui lève ce refus-ci — ou "" si le refus n'est pas levable.

    Fonction PURE : tout ce qu'elle nomme lui est passé. Le module ne lit ni
    l'environnement ni la base (cf docstring du module) ; c'est l'appelant qui
    sait où vit SON coffre et SON kill-switch.
    """
    env_file = env_file or GABARIT_FICHIER_ENV
    kill = kill_switch_path or "<var>/autonomy/KILL_PAID_AI"
    armer = geste_control_plane("arm --confirm", env_file=env_file, home=home)
    etat = geste_control_plane("status", env_file=env_file, home=home)
    if code == "master_switch_env_off":
        return (
            "INTERRUPTEUR 1 sur 2 — côté service. Il vit dans le fichier "
            f"d'environnement de ce cerveau : {env_file}. "
            f"Le geste : sudo sed -i 's/^ARAC_ALLOW_PAID_AI=.*/ARAC_ALLOW_PAID_AI=1/' {env_file} "
            "(ou ajoutez la ligne), puis relancez le cycle. "
            f"Il reste ensuite l'INTERRUPTEUR 2, en base : {armer}"
        )
    if code == "master_switch_config_off":
        return (
            "INTERRUPTEUR 2 sur 2 — côté cerveau. Il vit EN BASE, dans "
            "arac.arac_config, clé `paid_ai_enabled`, et ne s'ouvre que par un "
            f"geste humain explicite. Le geste : {armer} . "
            f"Pour vérifier ensuite : {etat}"
        )
    if code == "kill_switch_active":
        return (
            f"Le kill-switch a été posé à la main : {kill}. Il n'est JAMAIS "
            f"retiré automatiquement. Le geste : {armer} (il retire le fichier "
            f"et réarme le flag), ou sudo rm {kill}"
        )
    if code in ("daily_runs_exhausted", "daily_spawns_exhausted",
                "daily_items_exhausted", "daily_tokens_exhausted",
                "run_tokens_exhausted"):
        return (
            "Ce n'est pas une panne : le plafond de dépense du jour est atteint. "
            f"Le cycle reprendra demain, seul. Ce qui a été dépensé : {etat} . "
            "Les plafonds se règlent dans "
            f"{env_file} (ARAC_MAX_*/ARAC_DAILY_AI_BUDGET)."
        )
    if code == "min_interval_not_elapsed":
        # ATTENTION — `ARAC_CORTEX_FORCE_MANUAL` NE LÈVE PAS CELUI-CI, et la
        # première version de ce message le prétendait. Mesuré sur un banc :
        # la valve posée, le cycle refuse quand même en
        # `min_interval_not_elapsed` — elle ne change que le CRÉNEAU, jamais
        # l'intervalle entre deux dépenses. Un remède faux coûte plus cher
        # qu'un refus muet : on l'a corrigé le jour où on l'a vu.
        return (
            "Deux dépenses trop rapprochées — c'est l'anti-martèlement, pas "
            "une panne. Attendez l'intervalle mini, ou abaissez-le : "
            f"ARAC_MIN_MINUTES_BETWEEN_RUNS dans {env_file}. "
            "(ARAC_CORTEX_FORCE_MANUAL ne lève PAS ce refus-ci : elle ouvre "
            "un créneau neuf, elle ne raccourcit pas l'intervalle.)"
        )
    return ""


# ---------------------------------------------------------------------------
# Ledger journalier (fichier atomique, confiné, 0600)
# ---------------------------------------------------------------------------


def _today_str(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%d")


class SpendLedger:
    """Compteur de dépense du JOUR courant, persistant, atomique.

    Un seul fichier JSON ; les compteurs se RÉINITIALISENT au changement de date
    (UTC). Ne stocke JAMAIS de contenu de conversation — uniquement des nombres.
    """

    def __init__(self, path: str | None = None):
        self.path = os.path.abspath(path or os.path.join(DEFAULT_RUNTIME_DIR, _LEDGER_BASENAME))

    # -- I/O atomique -------------------------------------------------------

    def _read_raw(self) -> dict[str, Any]:
        if os.path.islink(self.path) or not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (ValueError, OSError):
            return {}

    def _write_raw(self, data: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(tmp, flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        finally:
            pass
        os.replace(tmp, self.path)

    # -- Vue du jour --------------------------------------------------------

    def snapshot(self, now: datetime) -> dict[str, Any]:
        """Compteurs du JOUR `now` (réinitialisés si la date a changé).

        Fail-closed sur intégrité : un ledger SYMLINK est refusé (on n'écrit
        jamais via un lien — O_NOFOLLOW — donc un lien = manipulation) ; les
        compteurs NÉGATIFS (corruption / falsification pour gonfler le budget)
        sont clampés à >= 0 pour ne JAMAIS re-créditer de budget.
        """
        if os.path.islink(self.path):
            raise RuntimeError(
                f"ledger path is a symlink — refus fail-closed: {self.path}")
        raw = self._read_raw()
        today = _today_str(now)
        if raw.get("date") != today:
            return {
                "date": today,
                "runs": 0,
                "items": 0,
                "spawns": 0,
                "tokens": 0,
                "last_run_at_epoch": None,
                "last_outcome": None,
            }

        def _nn(key: str) -> int:  # non-négatif (clamp anti-inflation)
            try:
                return max(0, int(raw.get(key) or 0))
            except (TypeError, ValueError):
                return 0

        return {
            "date": today,
            "runs": _nn("runs"),
            "items": _nn("items"),
            "spawns": _nn("spawns"),
            "tokens": _nn("tokens"),
            "last_run_at_epoch": raw.get("last_run_at_epoch"),
            "last_outcome": raw.get("last_outcome"),
        }

    def record_run_start(self, now: datetime) -> dict[str, Any]:
        snap = self.snapshot(now)
        snap["runs"] += 1
        snap["last_run_at_epoch"] = int(now.timestamp())
        self._write_raw(snap)
        return snap

    def record_spawn(self, now: datetime, *, tokens: int, items: int = 0) -> dict[str, Any]:
        snap = self.snapshot(now)
        snap["spawns"] += 1
        snap["tokens"] += max(0, int(tokens))
        snap["items"] += max(0, int(items))
        self._write_raw(snap)
        return snap

    def record_item(self, now: datetime) -> dict[str, Any]:
        snap = self.snapshot(now)
        snap["items"] += 1
        self._write_raw(snap)
        return snap

    def record_outcome(self, now: datetime, outcome: str) -> dict[str, Any]:
        snap = self.snapshot(now)
        snap["last_outcome"] = str(outcome)[:120]
        self._write_raw(snap)
        return snap


# ---------------------------------------------------------------------------
# RunReceiptLedger — ledger de dépense EN DB (remplace le ledger fichier)
# ---------------------------------------------------------------------------


class RunReceiptLedger:
    """Ledger de dépense adossé à `arac.run_receipts` (source de vérité des caps).

    MÊME interface de comptage que `SpendLedger` (snapshot/record_*) — la
    logique de décision `SpendGuard` est inchangée. Différences structurelles :
      - write-ahead : chaque évènement est committé IMMÉDIATEMENT dans la row
        du run courant (connexion COURTE dédiée par appel — jamais la tx du
        disposant : un crash de celui-ci ne peut pas annuler la dépense) ;
      - sémantique paresseuse PRÉSERVÉE : `runs`/`last_run_at_epoch` du
        snapshot ne comptent que les runs qui ont SPAWNÉ (spawns > 0) ;
      - fail-closed : toute erreur DB en lecture lève -> SpendGuard NO-GO
        (le cortex a de toute façon besoin de la DB pour réclamer du travail).

    Le kill-switch RESTE un fichier (SpendGuard.kill_active) — STOP même DB down.
    """

    def __init__(self, dsn: str, receipt_id: int | None = None):
        self.dsn = dsn
        self.receipt_id = receipt_id

    # -- plomberie -----------------------------------------------------------

    def _exec(self, sql: str, params: tuple = ()) -> list[tuple]:
        import psycopg

        with psycopg.connect(self.dsn, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall() if cur.description else []
            conn.commit()
        return rows

    def _require_bound(self) -> int:
        if self.receipt_id is None:
            raise RuntimeError("RunReceiptLedger non lié à un reçu (create_receipt d'abord)")
        return self.receipt_id

    # -- cycle de vie du reçu (utilisé par l'orchestrateur cortex) -----------

    def create_receipt(self, *, slot_key: str, trigger: str, model: str,
                       status: str = "started", skip_reason: str | None = None) -> int | None:
        """INSERT du reçu du run (write-ahead). Retourne l'id, ou None si le
        slot est DÉJÀ pris par un run qui a commencé (double-fire systemd du
        même créneau -> no-op).

        UN REFUS NE RÉSERVE PLUS LE CRÉNEAU, ET C'EST UN CORRECTIF MESURÉ.
        Le geste que le guide prescrit — `sudo systemctl start
        arac-<base>-cycle.service` — est REFUSÉ sur un cerveau neuf (l'IA
        payante n'est pas armée). Ce refus écrivait quand même un reçu
        `skipped` sous la contrainte `UNIQUE (slot_key)` : le créneau du jour
        était consommé, et tout ce qu'on réparait ensuite ne servait plus à
        rien — le cycle ressortait en silence sur `duplicate_slot` jusqu'au
        prochain horaire circadien. Mesuré : refus à 21:15, deux interrupteurs
        armés à 21:19, `allowed: true` immédiatement suivi de
        `cortex.duplicate_slot`, zéro travail, aucune explication.

        Un reçu qui n'a RIEN dépensé ne réserve donc rien : il est REPRIS
        (`ON CONFLICT … DO UPDATE`) dès qu'un run revient sur le même créneau.
        La garde anti-double-fire, elle, est intacte — la reprise est
        conditionnée à `status = 'skipped' AND spawns = 0`, c'est-à-dire à un
        reçu qui n'a jamais rien lancé.
        """
        rows = self._exec(
            "INSERT INTO arac.run_receipts (slot_key, trigger, model, status, skip_reason) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (slot_key) DO UPDATE SET "
            "  trigger = EXCLUDED.trigger, "
            "  model = EXCLUDED.model, "
            "  status = EXCLUDED.status, "
            "  skip_reason = EXCLUDED.skip_reason, "
            "  started_at = now(), "
            "  ended_at = NULL, "
            "  utc_day = (now() AT TIME ZONE 'utc')::date "
            "WHERE run_receipts.status = 'skipped' "
            "  AND run_receipts.spawns = 0 "
            "RETURNING id",
            (slot_key, trigger, model, status, skip_reason),
        )
        if not rows:
            return None
        self.receipt_id = int(rows[0][0])
        return self.receipt_id

    def mark(self, *, status: str | None = None, ended: bool = False, **fields: Any) -> None:
        """UPDATE guidé du reçu courant (status, compteurs, pack/progress jsonb,
        quarantine_*…). `ended=True` pose ended_at=now(). Les clés de `fields`
        sont restreintes aux colonnes connues (défense anti-typo)."""
        allowed = {
            "skip_reason", "est_input_tokens", "pack", "progress", "outcome",
            "atoms_created", "atoms_superseded", "atoms_confirmed",
            "atoms_kept_lower_confidence", "atoms_policy_skips",
            "atoms_quarantined", "conflicts_409",
            "quarantine_output", "quarantine_sha256", "quarantine_errors",
            "stop_reason",
            # Conservation-audit (0027) : couverture digestion.
            "messages_reported", "messages_truncated", "oversized_messages",
            # Oracle de couverture + attribution du poison (0027).
            "coverage_presented", "coverage_covered", "coverage_no_new_knowledge",
            "coverage_omitted", "quarantine_attributed_uids",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"colonnes inconnues pour run_receipts: {sorted(unknown)}")
        jsonb_cols = {"pack", "progress", "quarantine_errors", "oversized_messages",
                     "quarantine_attributed_uids"}
        sets, params = [], []
        if status is not None:
            sets.append("status = %s"); params.append(status)
        for k, v in fields.items():
            # psycopg n'adapte pas str -> jsonb implicitement : cast SQL.
            sets.append(f"{k} = %s::jsonb" if k in jsonb_cols else f"{k} = %s")
            params.append(v)
        if ended:
            sets.append("ended_at = now()")
        if not sets:
            return
        params.append(self._require_bound())
        self._exec(f"UPDATE arac.run_receipts SET {', '.join(sets)} WHERE id = %s",
                   tuple(params))

    # -- interface SpendLedger (consommée par SpendGuard) ---------------------

    def snapshot(self, now: datetime) -> dict[str, Any]:
        day = _today_str(now)
        rows = self._exec(
            "SELECT count(*) FILTER (WHERE spawns > 0), "
            "       coalesce(sum(items), 0), "
            "       coalesce(sum(spawns), 0), "
            "       coalesce(sum(est_input_tokens), 0), "
            "       extract(epoch from max(first_spawn_at)) "
            "FROM arac.run_receipts WHERE utc_day = %s::date",
            (day,),
        )
        runs, items, spawns, tokens, last_epoch = rows[0]
        out_rows = self._exec(
            "SELECT coalesce(outcome, status) FROM arac.run_receipts "
            "WHERE utc_day = %s::date ORDER BY id DESC LIMIT 1",
            (day,),
        )
        return {
            "date": day,
            "runs": int(runs),
            "items": int(items),
            "spawns": int(spawns),
            "tokens": int(tokens),
            "last_run_at_epoch": int(last_epoch) if last_epoch is not None else None,
            "last_outcome": out_rows[0][0] if out_rows else None,
        }

    def record_run_start(self, now: datetime) -> dict[str, Any]:
        self._exec(
            "UPDATE arac.run_receipts SET first_spawn_at = coalesce(first_spawn_at, %s) "
            "WHERE id = %s",
            (now, self._require_bound()),
        )
        return self.snapshot(now)

    def record_spawn(self, now: datetime, *, tokens: int, items: int = 0) -> dict[str, Any]:
        self._exec(
            "UPDATE arac.run_receipts SET "
            "  spawns = spawns + 1, "
            "  est_input_tokens = est_input_tokens + %s, "
            "  items = items + %s, "
            "  first_spawn_at = coalesce(first_spawn_at, %s) "
            "WHERE id = %s",
            (max(0, int(tokens)), max(0, int(items)), now, self._require_bound()),
        )
        return self.snapshot(now)

    def record_item(self, now: datetime) -> dict[str, Any]:
        self._exec(
            "UPDATE arac.run_receipts SET items = items + 1 WHERE id = %s",
            (self._require_bound(),),
        )
        return self.snapshot(now)

    def record_outcome(self, now: datetime, outcome: str) -> dict[str, Any]:
        self._exec(
            "UPDATE arac.run_receipts SET outcome = %s WHERE id = %s",
            (str(outcome)[:120], self._require_bound()),
        )
        return self.snapshot(now)


# ---------------------------------------------------------------------------
# SpendGuard
# ---------------------------------------------------------------------------


class SpendGuard:
    """Porte de dépense IA. Instancié une fois par run de batch curator.

    Cycle d'utilisation :
        g = SpendGuard(config, ledger, clock=..., kill_switch_path=...)
        d = g.open_run(env_allow=..., config_enabled=...)   # préflight
        if not d.allowed: stop
        for item in candidates:
            d = g.before_item()
            if not d.allowed: stop           # budget/run caps atteints
            for chunk in chunks:
                d = g.before_spawn(est_tokens)
                if not d.allowed: stop/skip
                res = spawn(...)
                g.record_spawn(tokens=..., duration_sec=...)
                if g.classify_output(res).stop: stop  # quota → arrêt propre
    """

    def __init__(
        self,
        config: BudgetConfig,
        ledger: SpendLedger,
        *,
        clock: Callable[[], datetime] | None = None,
        kill_switch_path: str | None = None,
        env_file: str | None = None,
    ):
        self.config = config
        self.ledger = ledger
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.kill_switch_path = kill_switch_path or DEFAULT_KILL_SWITCH
        # Le coffre de CE cerveau, pour que le refus nomme un chemin RÉEL et
        # non un gabarit. Injecté (le module ne lit pas l'environnement) ;
        # `agents/cortex/cycle.py` le passe.
        self.env_file = env_file or GABARIT_FICHIER_ENV
        # État local du run (réinitialisé par open_run).
        self._run_started_at: datetime | None = None
        self._items_this_run = 0
        self._tokens_this_run = 0
        self._spawns_this_run = 0
        self._run_recorded = False

    def _now(self) -> datetime:
        return self._clock()

    def _refus(self, code: str, reason: str,
               detail: dict[str, Any] | None = None) -> Decision:
        """TOUT refus passe par ici, et repart avec son geste.

        Aucun `Decision(False, …)` n'est construit ailleurs dans cette classe :
        c'est ce qui garantit qu'un refus muet ne peut pas revenir par une
        porte oubliée (`tests/test_les_deux_interrupteurs_se_nomment.py` le vérifie).
        """
        return Decision(False, code, reason, detail or {},
                        remede=remede_pour(code, env_file=self.env_file,
                                           kill_switch_path=self.kill_switch_path))

    # -- Kill-switch (fail-closed : chemin invalide → considéré actif) -------

    def kill_active(self) -> bool:
        # Fail-closed sur TOUTE ambiguïté. On N'utilise PAS kill_switch.is_active
        # (os.path.isfile y avale les OSError -> un kill-switch PRÉSENT mais
        # non-stat'able, ex. parent non traversable, serait lu comme ABSENT =
        # fail-OPEN). On stat explicitement : seul FileNotFoundError = absent.
        try:
            resolved = kill_switch.resolve_switch_path(self.kill_switch_path)
        except Exception:
            return True  # chemin non autorisé -> fail-closed
        try:
            os.lstat(resolved)          # existe (fichier OU lien) -> kill actif
            return True
        except FileNotFoundError:
            return False                # réellement absent -> pas de kill
        except OSError:
            return True                 # indéterminable (perms, I/O) -> fail-closed

    # -- Préflight du run ---------------------------------------------------

    def open_run(self, *, env_allow: bool, config_enabled: bool) -> Decision:
        """Décision AVANT tout travail payant. Fail-closed partout.

        `env_allow`      : ARAC_ALLOW_PAID_AI vrai (posé dans l'unité systemd).
        `config_enabled` : arac_config.paid_ai_enabled == true (armé à la main).
        """
        now = self._now()
        snap = self.ledger.snapshot(now)

        if not env_allow:
            return self._refus("master_switch_env_off",
                            "ARAC_ALLOW_PAID_AI absent/false — IA payante non activée côté service.",
                            {"snapshot": snap})
        if not config_enabled:
            return self._refus("master_switch_config_off",
                            "arac_config.paid_ai_enabled != true — IA payante non armée.",
                            {"snapshot": snap})
        if self.kill_active():
            return self._refus("kill_switch_active",
                            f"Kill-switch présent ({self.kill_switch_path}) — STOP.",
                            {"snapshot": snap})

        # Plafonds journaliers déjà atteints ?
        if snap["runs"] >= self.config.max_runs_per_day:
            return self._refus("daily_runs_exhausted",
                            f"runs/jour atteint ({snap['runs']}/{self.config.max_runs_per_day}).",
                            {"snapshot": snap})
        if snap["spawns"] >= self.config.max_spawns_per_day:
            return self._refus("daily_spawns_exhausted",
                            f"spawns/jour atteint ({snap['spawns']}/{self.config.max_spawns_per_day}).",
                            {"snapshot": snap})
        if snap["items"] >= self.config.max_items_per_day:
            return self._refus("daily_items_exhausted",
                            f"items/jour atteint ({snap['items']}/{self.config.max_items_per_day}).",
                            {"snapshot": snap})
        if snap["tokens"] >= self.config.daily_token_budget:
            return self._refus("daily_tokens_exhausted",
                            f"budget tokens/jour atteint ({snap['tokens']}/{self.config.daily_token_budget}).",
                            {"snapshot": snap})

        # Intervalle mini entre runs (anti-martèlement même si le timer est serré).
        last = snap.get("last_run_at_epoch")
        if last is not None and self.config.min_minutes_between_runs > 0:
            elapsed_min = (now.timestamp() - float(last)) / 60.0
            if elapsed_min < self.config.min_minutes_between_runs:
                return self._refus("min_interval_not_elapsed",
                                f"intervalle mini non écoulé ({elapsed_min:.1f}/"
                                f"{self.config.min_minutes_between_runs} min).",
                                {"snapshot": snap, "elapsed_min": round(elapsed_min, 1)})

        # OK — on ouvre le run. IMPORTANT : on N'incrémente PAS `runs` ni
        # `last_run_at` ici. Un run QUI NE DÉPENSE PAS (idle : aucune matière,
        # ou tout superseded) ne doit PAS consommer le budget runs/jour ni
        # décaler l'intervalle — sinon les ticks du timer épuiseraient le cap
        # en périodes creuses et affameraient la vraie curation. Le compteur
        # `runs` + l'horodatage sont posés PARESSEUSEMENT au 1er spawn réel
        # (record_spawn), donc seuls les runs QUI DÉPENSENT comptent.
        self._run_started_at = now
        self._items_this_run = 0
        self._tokens_this_run = 0
        self._spawns_this_run = 0
        self._run_recorded = False
        return Decision(True, "run_open",
                        "Run autorisé (master-switch on, kill-switch off, sous budget).",
                        {"snapshot": self.ledger.snapshot(now)})

    # -- Avant chaque conversation -----------------------------------------

    def before_item(self) -> Decision:
        """Décision avant de curer UNE conversation de plus."""
        now = self._now()
        # Kill-switch re-vérifié à chaque item (un humain peut le poser en cours).
        if self.kill_active():
            return self._refus("kill_switch_active", "Kill-switch posé pendant le run — STOP.")
        # Runtime.
        elapsed = self._elapsed_sec(now)
        if elapsed >= self.config.max_runtime_sec:
            return self._refus("run_timeout",
                            f"durée max run atteinte ({elapsed:.0f}/{self.config.max_runtime_sec}s).")
        # Items/run.
        if self._items_this_run >= self.config.max_items_per_run:
            return self._refus("run_items_cap",
                            f"items/run atteint ({self._items_this_run}/{self.config.max_items_per_run}).")
        # Budgets journaliers (relus depuis le ledger : partagés entre runs).
        snap = self.ledger.snapshot(now)
        if snap["spawns"] >= self.config.max_spawns_per_day:
            return self._refus("daily_spawns_exhausted", "spawns/jour atteint.")
        if snap["items"] >= self.config.max_items_per_day:
            return self._refus("daily_items_exhausted", "items/jour atteint.")
        if snap["tokens"] >= self.config.daily_token_budget:
            return self._refus("daily_tokens_exhausted", "budget tokens/jour atteint.")
        return Decision(True, "item_ok", "Item autorisé.", {"snapshot": snap})

    # -- Avant chaque spawn (chunk) ----------------------------------------

    def before_spawn(self, estimated_tokens: int) -> Decision:
        """Décision avant UN spawn `claude` (un chunk). `estimated_tokens` = coût
        INPUT estimé de ce chunk (token_count). REFUSE si dépasserait un plafond.
        """
        now = self._now()
        if self.kill_active():
            return self._refus("kill_switch_active", "Kill-switch posé — STOP.")
        elapsed = self._elapsed_sec(now)
        if elapsed >= self.config.max_runtime_sec:
            return self._refus("run_timeout",
                            f"durée max run atteinte ({elapsed:.0f}/{self.config.max_runtime_sec}s).")
        est = max(0, int(estimated_tokens))
        snap = self.ledger.snapshot(now)
        # Plafond spawns/jour.
        if snap["spawns"] >= self.config.max_spawns_per_day:
            return self._refus("daily_spawns_exhausted",
                            f"spawns/jour atteint ({snap['spawns']}/{self.config.max_spawns_per_day}).")
        # Tokens/run.
        if self._tokens_this_run + est > self.config.max_tokens_per_run:
            return self._refus("run_tokens_cap",
                            f"tokens/run dépassé ({self._tokens_this_run}+{est}>"
                            f"{self.config.max_tokens_per_run}).",
                            {"tokens_this_run": self._tokens_this_run, "estimated": est})
        # Tokens/jour.
        if snap["tokens"] + est > self.config.daily_token_budget:
            return self._refus("daily_tokens_exhausted",
                            f"budget tokens/jour dépassé ({snap['tokens']}+{est}>"
                            f"{self.config.daily_token_budget}).",
                            {"tokens_today": snap["tokens"], "estimated": est})
        return Decision(True, "spawn_ok", "Spawn autorisé.",
                        {"estimated_tokens": est, "snapshot": snap})

    # -- Enregistrement après spawn / item ---------------------------------

    def record_spawn(self, *, tokens: int, duration_sec: float, items: int = 0) -> dict[str, Any]:
        """Enregistre UN spawn `claude`. `items` : nombre de
        conversations RÉELLEMENT couvertes par CE spawn.

        Comportement effectif (correctif) : avant ce correctif, le cortex
        circadien (`agents/cortex/cycle.py`) n'appelait NI `record_spawn(items=...)`
        NI `record_item_done()` (ce dernier suppose une boucle par-item, absente
        du modèle « un spawn = tout un pack multi-conversations ») — `items`
        restait à 0 pour TOUJOURS sur ses reçus, donc `max_items_per_day` /
        `max_items_per_run` ne pouvaient jamais se déclencher pour ce chemin
        (cap structurellement inopérant). Depuis, `cycle.py` passe
        `items=len(pack_meta)` ICI (un seul point d'appel, un seul spawn/pack)
        -> le cap redevient un frein réel sur le NOMBRE DE CONVERSATIONS
        digérées par jour, pas seulement sur les spawns/tokens. `batch_runner.py`
        (v1/v2, boucle par-item, RETIRÉ lors du chantier « Perception V4 ») comptait via
        `record_item_done()` et n'était pas affecté (appelait `record_spawn`
        SANS `items`, défaut 0) — chemin mort, `cycle.py` est désormais le
        SEUL appelant.
        """
        now = self._now()
        # Incrément PARESSEUX du run : seul un run qui dépense réellement compte
        # dans runs/jour et pose last_run_at (intervalle mini entre spends).
        if not getattr(self, "_run_recorded", False):
            self.ledger.record_run_start(now)
            self._run_recorded = True
        self._spawns_this_run += 1
        self._tokens_this_run += max(0, int(tokens))
        self._items_this_run += max(0, int(items))
        return self.ledger.record_spawn(now, tokens=tokens, items=items)

    def record_item_done(self) -> dict[str, Any]:
        now = self._now()
        self._items_this_run += 1
        return self.ledger.record_item(now)

    def record_outcome(self, outcome: str) -> dict[str, Any]:
        return self.ledger.record_outcome(self._now(), outcome)

    # -- Classification de la sortie d'un spawn (arrêt propre sur quota) -----

    def classify_output(self, *, stdout: str | None, stderr: str | None,
                        exit_code: int) -> dict[str, Any]:
        """Détecte l'épuisement de quota/session. En batch sobre, on NE fait PAS
        de pacing 6h : on ARRÊTE proprement le run (le timer relancera plus tard,
        sous intervalle mini). Renvoie {'quota_hit': bool, 'stop': bool, 'kind'}.
        """
        blob = f"{stdout or ''}\n{stderr or ''}"
        kind = quota_guard.classify_error(blob)
        quota_hit = kind == "quota"
        # quota OU erreur dure/timeout → stop du run (checkpoint via ledger,
        # reprise au prochain tick timer). Jamais de boucle serrée ici.
        stop = quota_hit or (exit_code != 0 and kind in ("quota", "transient", "hard"))
        return {"quota_hit": quota_hit, "stop": bool(stop), "kind": kind}

    # -- Helpers ------------------------------------------------------------

    def _elapsed_sec(self, now: datetime) -> float:
        if self._run_started_at is None:
            return 0.0
        return max(0.0, (now - self._run_started_at).total_seconds())

    def run_summary(self) -> dict[str, Any]:
        now = self._now()
        return {
            "items_this_run": self._items_this_run,
            "spawns_this_run": self._spawns_this_run,
            "tokens_this_run": self._tokens_this_run,
            "elapsed_sec": round(self._elapsed_sec(now), 1),
            "ledger": self.ledger.snapshot(now),
        }
