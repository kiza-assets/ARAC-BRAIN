"""UN CYCLE QUI NE FAIT RIEN DOIT DIRE POURQUOI — ET LEQUEL DES DEUX L'ARRÊTE.

CE QUE CE GARDE EMPÊCHE DE REVENIR
==================================
Il y a DEUX interrupteurs de dépense, et le second n'était nommé dans aucune
page destinée au lecteur. Mesuré sur une installation neuve : conversations
ingérées, cycle lancé comme le guide le prescrit, et rien. Le journal disait
`master_switch_env_off` ; le seul remède écrit était « posez
ARAC_ALLOW_PAID_AI=1 » ; on le pose, on relance — et le cycle refuse DE
NOUVEAU, sous un code qui n'existait nulle part ailleurs que dans le code :
`master_switch_config_off`. Le second verrou vit EN BASE
(`arac.arac_config.paid_ai_enabled`) et ne s'ouvre que par une commande que
personne ne pouvait deviner.

« Je n'ai pas pu » n'est ni « c'est bon » ni « c'est cassé » : c'est la règle
du dépôt, et un refus muet la viole. Trois choses sont donc tenues ici :

  1. CHAQUE refus levable repart avec un remède qui NOMME le verrou, dit OÙ
     il vit, et donne le GESTE ;
  2. aucun refus ne peut être construit hors du point unique qui attache ce
     remède — sinon un refus muet revient par une porte oubliée ;
  3. un refus ne CONSOMME PLUS le créneau du jour. Le reçu `skipped` était
     écrit sous une contrainte d'unicité : on réparait, on relançait, et le
     cycle ressortait en silence sur `duplicate_slot` jusqu'au prochain
     horaire circadien. Un reçu qui n'a rien dépensé ne réserve rien.

Hors-ligne : aucune base, aucun réseau. Le point 3 se vérifie sur le SQL
émis, capté par un faux exécuteur — c'est la seule façon de l'éprouver sans
PostgreSQL, et c'est exactement la clause qui portait le défaut.
"""

from __future__ import annotations

import ast
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from agents.lib import spend_guard as sg  # noqa: E402


COFFRE = "/etc/arac/moncerveau/arac.env"


class _LedgerMuet:
    """Ledger de test : un snapshot vide, et rien d'autre."""

    def __init__(self, **snap):
        self._snap = {"date": "2026-08-10", "runs": 0, "items": 0, "spawns": 0,
                      "tokens": 0, "last_run_at_epoch": None, "last_outcome": None}
        self._snap.update(snap)

    def snapshot(self, now):  # noqa: D401 - interface SpendLedger
        return dict(self._snap)


def _guard(**snap) -> sg.SpendGuard:
    return sg.SpendGuard(
        sg.BudgetConfig(), _LedgerMuet(**snap),
        clock=lambda: datetime(2026, 8, 10, 21, 15, tzinfo=timezone.utc),
        kill_switch_path=str(RACINE / "var" / "autonomy" / "KILL_PAID_AI"),
        env_file=COFFRE,
    )


# ---------------------------------------------------------------------------
# 1. Le refus nomme son verrou, son lieu et son geste
# ---------------------------------------------------------------------------


def test_le_premier_interrupteur_dit_ou_il_vit_et_quoi_taper() -> None:
    d = _guard().open_run(env_allow=False, config_enabled=False)
    assert d.allowed is False and d.code == "master_switch_env_off"
    assert "ARAC_ALLOW_PAID_AI" in d.remede
    assert COFFRE in d.remede, "le refus doit nommer le coffre de CE cerveau"
    assert "INTERRUPTEUR 1 sur 2" in d.remede
    # …et il annonce le second, sinon on répare la moitié du mur.
    assert "paid_ai_control arm --confirm" in d.remede


def test_le_second_interrupteur_est_nomme_avec_son_geste() -> None:
    d = _guard().open_run(env_allow=True, config_enabled=False)
    assert d.code == "master_switch_config_off"
    assert "arac_config" in d.remede and "paid_ai_enabled" in d.remede
    assert "paid_ai_control arm --confirm" in d.remede
    assert COFFRE in d.remede


def test_le_remede_voyage_dans_le_journal() -> None:
    """`as_dict` porte le remède : c'est par là qu'il atteint journald."""
    d = _guard().open_run(env_allow=True, config_enabled=False)
    assert d.as_dict()["remede"] == d.remede


def test_les_plafonds_ne_se_font_pas_passer_pour_une_panne() -> None:
    d = _guard(tokens=10**9).open_run(env_allow=True, config_enabled=True)
    assert d.code == "daily_tokens_exhausted"
    assert "n'est pas une panne" in d.remede


def test_aucun_refus_muet_ne_peut_revenir_par_une_porte_oubliee() -> None:
    """Aucun `Decision(False, …)` hors du point unique qui attache le remède.

    C'est le garde structurel : sans lui, le prochain refus ajouté à la classe
    repartirait sans geste, et personne ne s'en apercevrait avant qu'un
    cerveau ne cesse d'apprendre.
    """
    source = (RACINE / "agents/lib/spend_guard.py").read_text(encoding="utf-8")
    arbre = ast.parse(source)
    classe = next(n for n in ast.walk(arbre)
                  if isinstance(n, ast.ClassDef) and n.name == "SpendGuard")
    fautes = []
    # `_refus` est le point unique : c'est LUI qui construit le Decision(False).
    corps = [n for n in classe.body
             if not (isinstance(n, ast.FunctionDef) and n.name == "_refus")]
    for parent in corps:
        for noeud in ast.walk(parent):
            if not isinstance(noeud, ast.Call):
                continue
            if getattr(noeud.func, "id", "") != "Decision":
                continue
            if noeud.args and isinstance(noeud.args[0], ast.Constant) \
                    and noeud.args[0].value is False:
                fautes.append(noeud.lineno)
    assert not fautes, (
        "spend_guard.py : refus construits hors de `_refus` aux lignes "
        f"{fautes} — ils repartiraient SANS remède"
    )


# ---------------------------------------------------------------------------
# 2. Un refus ne brûle plus le créneau
# ---------------------------------------------------------------------------


class _LedgerEspion(sg.RunReceiptLedger):
    """Capte le SQL au lieu de l'exécuter — aucune base n'est ouverte."""

    def __init__(self):
        super().__init__("postgresql://jamais-ouvert/hermetique")
        self.sql: list[str] = []

    def _exec(self, sql: str, params: tuple = ()):  # noqa: D401
        self.sql.append(" ".join(sql.split()))
        return [(1,)]


def test_le_recu_d_un_refus_est_repris_et_non_verrouille() -> None:
    espion = _LedgerEspion()
    espion.create_receipt(slot_key="circadian_2100@2026-08-10", trigger="circadian_2100",
                          model="claude-sonnet-4-5", status="skipped",
                          skip_reason="master_switch_config_off")
    sql = espion.sql[0]
    assert "ON CONFLICT (slot_key) DO UPDATE" in sql, (
        "un refus qui n'a rien dépensé doit pouvoir être REPRIS : sinon il "
        "consomme le créneau du jour et tout ce qu'on répare ensuite est "
        "sans effet jusqu'au prochain horaire"
    )
    assert "DO NOTHING" not in sql


def test_la_garde_anti_double_tir_reste_entiere() -> None:
    """La reprise est bornée à un reçu qui n'a JAMAIS rien lancé."""
    espion = _LedgerEspion()
    espion.create_receipt(slot_key="circadian_2100@2026-08-10", trigger="circadian_2100",
                          model="claude-sonnet-4-5")
    sql = espion.sql[0]
    assert "run_receipts.status = 'skipped'" in sql
    assert "run_receipts.spawns = 0" in sql, (
        "sans cette condition, un second tir systemd écraserait le reçu d'un "
        "cycle en cours — la dépense écrite en write-ahead serait perdue"
    )
