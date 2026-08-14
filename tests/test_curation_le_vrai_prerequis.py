"""LE VRAI PRÉREQUIS DE LA CURATION EST NOMMÉ, VÉRIFIÉ, ET DÉPLAÇABLE.

CE QUE CE GARDE EMPÊCHE DE REVENIR — il a coûté une installation entière.
=========================================================================
L'étape 8 de l'installation faisait acheter une **clé d'API Anthropic**
« pour la curation ». Or le cycle de digestion n'appelle AUCUNE API : il
lance le binaire `claude` (Claude Code CLI) en sous-processus, sur le
serveur, sous le compte d'agent (`agents/lib/claude_cli.py`). Le chemin de ce
binaire était FIGÉ sur une installation npm globale sous préfixe système,
aucun contrôle de prérequis ne le nommait, et `bootstrap.sh --check` concluait quand même « Tout est là ».

Le prix : un cerveau qui ingère, se laisse interroger, affiche 39 pages de
cockpit — et n'apprend JAMAIS un seul souvenir, sans qu'un seul écran ne le
dise. Un prérequis qu'on découvre trois jours plus tard, quand rien ne s'est
produit, n'est pas un prérequis : c'est un piège.

Quatre choses sont donc tenues ici, et chacune ferme une porte précise :
  1. le chemin du binaire se RÉSOUT à l'exécution (variable, puis PATH, puis
     le chemin historique) — une installation npm posée sous nvm ou sous un
     préfixe local ne fait plus échouer le cycle en boucle ;
  2. la constante n'est plus lue directement à l'endroit du spawn ;
  3. le bootstrap NOMME ce prérequis dans son écran d'étape, et son contrôle
     final le vérifie sous le compte d'agent avant de conclure ;
  4. l'étape des clés ne vend plus « une clé de curation » comme si c'était
     elle qui digérait.

Hors-ligne : lecture de fichiers et d'un module. Aucun sous-processus
`claude` n'est lancé — ce garde ne dépense rien et ne dépend d'aucune
machine où le binaire serait installé.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from agents.lib import claude_cli  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Le chemin se résout, et il se laisse déplacer
# ---------------------------------------------------------------------------


def test_la_variable_deplace_le_binaire(monkeypatch: pytest.MonkeyPatch,
                                        tmp_path: Path) -> None:
    """`ARAC_CLAUDE_BIN` l'emporte sur tout — c'est le geste rendu au lecteur."""
    ailleurs = str(tmp_path / "npm-global" / "bin" / "claude")
    monkeypatch.setenv("ARAC_CLAUDE_BIN", ailleurs)
    assert claude_cli.resolve_claude_bin() == ailleurs


def test_a_defaut_on_cherche_dans_le_chemin(monkeypatch: pytest.MonkeyPatch,
                                            tmp_path: Path) -> None:
    """Sans variable, le PATH du service décide — pas un chemin figé."""
    faux = tmp_path / "claude"
    faux.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    faux.chmod(0o755)
    monkeypatch.delenv("ARAC_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert claude_cli.resolve_claude_bin() == str(faux)


def test_le_dernier_recours_reste_le_chemin_historique(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Rien dans le PATH : on retombe sur le chemin historique, jamais sur rien."""
    monkeypatch.delenv("ARAC_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "vide"))
    assert claude_cli.resolve_claude_bin() == claude_cli.CLAUDE_BIN


def test_le_spawn_ne_lit_plus_la_constante() -> None:
    """La commande est construite avec `resolve_claude_bin()`, pas `CLAUDE_BIN`.

    C'est la forme du défaut : un chemin figé à l'IMPORT ne se laisse plus
    corriger par l'environnement du service.
    """
    source = (RACINE / "agents/lib/claude_cli.py").read_text(encoding="utf-8")
    arbre = ast.parse(source)
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.List):
            continue
        if not noeud.elts:
            continue
        premier = noeud.elts[0]
        # La liste `cmd = [ …, "-p", … ]` : son premier élément est le binaire.
        suivants = [e for e in noeud.elts[1:3] if isinstance(e, ast.Constant)]
        if not any(getattr(e, "value", None) == "-p" for e in suivants):
            continue
        assert isinstance(premier, ast.Call), (
            "la commande claude doit être construite avec resolve_claude_bin(), "
            "pas avec une constante figée à l'import"
        )
        assert getattr(premier.func, "id", "") == "resolve_claude_bin"
        return
    pytest.fail("la construction de la commande `claude -p` est introuvable")


def test_l_absence_du_binaire_se_dit_avec_son_geste(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Absent, il est NOMMÉ, et la phrase porte l'installation à faire."""
    monkeypatch.setenv("ARAC_CLAUDE_BIN", str(tmp_path / "nulle-part"))
    dispo, chemin, remede = claude_cli.curation_disponible()
    assert dispo is False
    assert str(tmp_path / "nulle-part") in chemin
    assert "npm install -g @anthropic-ai/claude-code" in remede
    assert "ARAC_CLAUDE_BIN" in remede
    # La phrase doit corriger le modèle mental, pas seulement donner un geste.
    assert "AUCUNE API" in remede


def test_present_et_executable_il_est_declare_disponible(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    faux = tmp_path / "claude"
    faux.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    faux.chmod(0o755)
    monkeypatch.setenv("ARAC_CLAUDE_BIN", str(faux))
    dispo, chemin, remede = claude_cli.curation_disponible()
    assert dispo is True and chemin == str(faux) and remede == ""


# ---------------------------------------------------------------------------
# 2. L'installation le nomme et le vérifie
# ---------------------------------------------------------------------------


def _texte(rel: str) -> str:
    return (RACINE / rel).read_text(encoding="utf-8")


def test_l_etape_des_prerequis_nomme_le_binaire() -> None:
    """Le prérequis est constaté à l'étape 1, avec son geste d'installation."""
    s = _texte("bootstrap/lib/prereqs.sh")
    assert "_prerequis_de_la_curation" in s
    assert "auth status --json" in s, (
        "l'authentification doit être LUE, et par la seule sonde qui ne "
        "dépense rien"
    )
    assert "npm install -g @anthropic-ai/claude-code" in s


def test_la_conclusion_ne_promet_plus_ce_qu_elle_n_a_pas_vu() -> None:
    """« Tout est là » ne peut plus être rendu quand la curation manque."""
    s = _texte("bootstrap/lib/prereqs.sh")
    assert 'CURATION_BINAIRE_PRESENT" == oui' in s or \
           '"$CURATION_BINAIRE_PRESENT" == oui' in s
    i = s.index("Tout est là")
    # La phrase optimiste doit être gardée par le constat de curation.
    assert "CURATION_BINAIRE_PRESENT" in s[max(0, i - 400):i]


def test_le_controle_final_verifie_la_curation_avant_de_conclure() -> None:
    """Une installation ne se déclare pas réussie sans avoir regardé ça."""
    s = _texte("bootstrap/checks/verify_install.sh")
    assert "controle_curation()" in s
    # …et il est réellement APPELÉ par le contrôle, pas seulement défini.
    corps = s[s.index("main() {"):]
    assert "controle_curation" in corps
    for attendu in ("ARAC_AGENT_USER", "agent-home", "auth status --json",
                    "ARAC_ALLOW_PAID_AI", "paid_ai_enabled"):
        assert attendu in s, f"le contrôle de curation ne regarde pas {attendu}"


def test_l_etape_des_cles_ne_vend_plus_la_mauvaise_chose() -> None:
    """Ce qu'on fait acheter doit être ce dont la curation a besoin."""
    s = _texte("bootstrap/lib/secrets.sh")
    assert "_dire_ce_que_chaque_secret_paie" in s
    assert "JAMAIS LUE PAR ARAC" in s, (
        "la clé Anthropic n'est lue par aucun fichier du produit : le dire "
        "est le minimum dû à qui paie"
    )
    # Le mode dégradé « curation » doit se décider sur le VRAI prérequis.
    assert "_constater_curation" in s


def test_le_fichier_canonique_nomme_la_variable_de_chemin() -> None:
    s = _texte(".env.example")
    assert "ARAC_CLAUDE_BIN" in s
