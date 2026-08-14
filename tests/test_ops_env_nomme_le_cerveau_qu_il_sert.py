"""`ops/` NE SERT JAMAIS UN CERVEAU QUE PERSONNE N'A NOMMÉ.

CE QUI EST EN JEU
=================
`ops/env.sh` est la seule ligne du dépôt qui décide, pour TOUTES les commandes
d'exploitation, à quel cerveau elles vont s'adresser. `ops/backup.sh` dumpe la
base qu'elle désigne, `ops/backup.sh` fait tourner les dumps de plus de N jours
dans le dossier qu'elle désigne, `ops/restore_verify.sh` restaure ce qu'elle
désigne. Se tromper de cerveau ici, c'est le geste destructeur du framework
entier — et il n'y a pas de seconde chance.

L'ÉTAT QUI A RENDU CE FICHIER NÉCESSAIRE
========================================
Le socle avait appris à résoudre le coffre par `config/brain.toml`, et il ne
disait rien. Mesuré sur une machine portant dix coffres, depuis un dépôt qui en
décrivait un : `sudo ops/backup.sh` sans `ARAC_ENV_FILE` a rendu `backup.done`,
code 0, un dump complet de 132 411 octets — sans qu'une seule ligne dise qu'un
choix venait d'être fait, ni lequel, ni qu'il y avait neuf autres candidats. La
documentation, elle, promettait toujours un arrêt.

Le pire n'était pas le choix : c'était le SILENCE. Un outil qui agit sur un
cerveau que personne n'a nommé est le mécanisme exact qui a détruit la mémoire
de l'auteur de ce framework.

LA RÈGLE, ET LE GARDE
=====================
Cinq rangs, écrits en toutes lettres au-dessus du code d'`ops/env.sh` :
désigné, `.env` du dépôt, coffre unique, choix ANNONCÉ, refus. Ce fichier-ci
les éprouve un par un — et il le peut parce que la racine des coffres est
devenue une variable (`ARAC_ETC_DIR`). Une garde qu'on ne peut pas éprouver
disparaît sans qu'on l'apprenne : c'est exactement ce qui vient d'arriver à
celle-ci, et c'est ce qu'on referme ici.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
ENV_SH = RACINE / "ops" / "env.sh"

#: On ne demande à `env.sh` que ce qu'il a décidé — pas ce qu'il a chargé. Le
#: reste du fichier n'est pas le sujet, et le sourcer suffit à le mesurer :
#: c'est une propriété du socle qu'il n'ait AUCUN effet observable.
_CORPS = f'source "{ENV_SH}" ; printf "%s\\n" "$ARAC_ENV_FILE"'


class Verdict:
    def __init__(self, p: subprocess.CompletedProcess):
        self.rc = p.returncode
        self.choisi = p.stdout.strip()
        self.dit = p.stderr

    def __repr__(self) -> str:  # pragma: no cover — lisibilité d'un échec
        return f"<rc={self.rc} choisi={self.choisi!r} dit={self.dit!r}>"


def _machine(tmp_path, *, cerveaux, decrit=None, dot_env=False, designe=None):
    """Une machine à soi : N coffres, un dépôt qui décrit (ou non) un cerveau."""
    etc = tmp_path / "etc-arac"
    for nom in cerveaux:
        (etc / nom).mkdir(parents=True)
        (etc / nom / "arac.env").write_text(
            f"ARAC_DB={nom}\nARAC_UNIT_PREFIX=arac-{nom}\n", encoding="utf-8")
    depot = tmp_path / "depot"
    (depot / "config").mkdir(parents=True)
    if decrit is not None:
        (depot / "config" / "brain.toml").write_text(
            f'[brain]\nowner = "Quelqu\'un"\nname = "{decrit}"\n'
            '\n[source]\nnode_id = "un-poste"\n', encoding="utf-8")
    if dot_env:
        (depot / ".env").write_text("ARAC_DB=du-depot\n", encoding="utf-8")

    env = dict(os.environ)
    env.pop("ARAC_ENV_FILE", None)
    env["ARAC_HOME"] = str(depot)
    env["ARAC_ETC_DIR"] = str(etc)
    if designe is not None:
        env["ARAC_ENV_FILE"] = str(designe)
    return Verdict(subprocess.run(
        ["bash", "-c", _CORPS], capture_output=True, text=True,
        cwd=str(tmp_path), env=env))


# ---------------------------------------------------------------------------
# RANG 1 et 2 — une désignation ne se commente pas
# ---------------------------------------------------------------------------

def test_rang_1_ce_qui_est_designe_est_servi_sans_un_mot(tmp_path):
    """Nommer le coffre EST la désignation : l'outil n'a rien à ajouter.

    C'est ce que font les unités systemd (`Environment=ARAC_ENV_FILE=…`) : sous
    systemd, on est toujours au rang 1, et rien n'est imprimé quatre fois par
    jour dans le journal.
    """
    vise = tmp_path / "etc-arac" / "beta" / "arac.env"
    v = _machine(tmp_path, cerveaux=("alpha", "beta"), decrit="alpha",
                 designe=vise)
    assert v.rc == 0 and v.choisi == str(vise)
    assert v.dit == "", (
        "Une désignation explicite doit être silencieuse — sinon l'annonce "
        f"devient du bruit, et le bruit se filtre.\n{v!r}")


def test_rang_2_le_env_du_depot_gagne_et_se_tait(tmp_path):
    """L'installation manuelle : un dépôt n'a qu'un `.env`, pas d'ambiguïté."""
    v = _machine(tmp_path, cerveaux=("alpha", "beta"), decrit="alpha",
                 dot_env=True)
    assert v.rc == 0
    assert v.choisi == str(tmp_path / "depot" / ".env")
    assert v.dit == ""


# ---------------------------------------------------------------------------
# RANG 3 — un seul coffre : aucun choix n'est possible… sauf désaccord
# ---------------------------------------------------------------------------

def test_rang_3_un_seul_coffre_est_pris_sans_un_mot(tmp_path):
    """Le cas de l'immense majorité des machines. Il ne doit rien coûter."""
    v = _machine(tmp_path, cerveaux=("alpha",), decrit=None)
    assert v.rc == 0
    assert v.choisi == str(tmp_path / "etc-arac" / "alpha" / "arac.env")
    assert v.dit == ""


def test_rang_3_le_depot_qui_decrit_le_seul_coffre_passe_aussi(tmp_path):
    v = _machine(tmp_path, cerveaux=("alpha",), decrit="alpha")
    assert v.rc == 0
    assert v.choisi == str(tmp_path / "etc-arac" / "alpha" / "arac.env")


def test_rang_3_un_seul_coffre_qui_n_est_PAS_le_votre_est_un_refus(tmp_path):
    """LE DERNIER CHOIX SILENCIEUX QUI RESTAIT, et le plus traître.

    Un dépôt qui décrit « perso » sur une machine dont l'unique cerveau
    s'appelle « travail » se faisait servir « travail », sans un mot : un dump,
    une rotation, une restauration sur le cerveau d'à côté. Il n'y a pas
    d'ambiguïté ici — il y a un DÉSACCORD, et un désaccord se tranche par une
    question, jamais par un défaut.
    """
    v = _machine(tmp_path, cerveaux=("travail",), decrit="perso")
    assert v.rc == 1, f"le désaccord doit ARRÊTER, pas choisir\n{v!r}"
    assert "perso" in v.dit
    assert "travail" in v.dit


# ---------------------------------------------------------------------------
# RANG 4 — choisir, oui ; en silence, jamais
# ---------------------------------------------------------------------------

def test_rang_4_le_choix_est_fait_ET_dit(tmp_path):
    """Le cœur de la garde : le cerveau servi est NOMMÉ avant le premier geste.

    Quatre choses, et chacune répond à une question qu'on se pose au moment où
    on lit le message : lequel, où, sur quelle preuve, et comment en viser un
    autre.
    """
    v = _machine(tmp_path, cerveaux=("alpha", "beta", "gamma"), decrit="beta")
    attendu = tmp_path / "etc-arac" / "beta" / "arac.env"
    assert v.rc == 0 and v.choisi == str(attendu)
    assert v.dit, "un choix silencieux est le mécanisme qu'on ferme ici"
    assert "beta" in v.dit                      # lequel
    assert str(attendu) in v.dit                # où
    assert "brain.toml" in v.dit                # sur quelle preuve
    assert "3" in v.dit                         # combien de candidats
    assert "ARAC_ENV_FILE=" in v.dit            # comment en viser un autre


def test_rang_4_l_annonce_ne_pollue_pas_la_sortie_lisible_a_la_machine(tmp_path):
    """Ces scripts rendent du JSON qu'on relit avec `jq`. L'annonce va sur stderr."""
    v = _machine(tmp_path, cerveaux=("alpha", "beta"), decrit="beta")
    assert v.choisi == str(tmp_path / "etc-arac" / "beta" / "arac.env")
    assert "\n" not in v.choisi


# ---------------------------------------------------------------------------
# RANG 5 — le refus, et il s'arrête POUR DE BON
# ---------------------------------------------------------------------------

def test_rang_5_plusieurs_coffres_et_le_depot_n_en_decrit_aucun(tmp_path):
    v = _machine(tmp_path, cerveaux=("alpha", "beta"), decrit=None)
    assert v.rc == 1
    assert "ARRÊT AVANT TOUT GESTE" in v.dit
    for nom in ("alpha", "beta"):
        assert f"ARAC_ENV_FILE={tmp_path}/etc-arac/{nom}/arac.env" in v.dit, (
            "Un refus qui cache une partie de ce qu'il a vu oblige à refaire à "
            f"la main le travail qu'il vient de faire.\n{v!r}")


def test_rang_5_le_depot_decrit_un_cerveau_qui_n_a_pas_de_coffre_ici(tmp_path):
    """La raison imprimée doit être la VRAIE.

    L'ancien refus disait « config/brain.toml absent ou illisible » dans ce cas
    aussi — alors que le fichier est là et parfaitement lisible. Une clé de
    diagnostic fausse, le jour de la panne, coûte plus cher que pas de clé.
    """
    v = _machine(tmp_path, cerveaux=("alpha", "beta"), decrit="fantome")
    assert v.rc == 1
    assert "fantome" in v.dit
    assert "absent ou illisible" not in v.dit


def test_rang_5_s_arrete_AVANT_le_geste_et_non_trois_ecrans_plus_loin(tmp_path):
    """« S'arrêter avant d'agir » veut dire : le script appelant ne continue pas.

    L'ancien refus posait un `$ARAC_HOME/.env` inexistant et laissait couler :
    on découvrait le problème plus loin, sous un « Aucun DSN de sauvegarde »
    qui n'avait plus rien à voir avec la cause. On mesure donc qu'aucune ligne
    n'est exécutée APRÈS le `source`.
    """
    etc = tmp_path / "etc-arac"
    for nom in ("alpha", "beta"):
        (etc / nom).mkdir(parents=True)
        (etc / nom / "arac.env").write_text("ARAC_DB=x\n", encoding="utf-8")
    (tmp_path / "depot" / "config").mkdir(parents=True)
    env = dict(os.environ)
    env.pop("ARAC_ENV_FILE", None)
    env["ARAC_HOME"] = str(tmp_path / "depot")
    env["ARAC_ETC_DIR"] = str(etc)
    p = subprocess.run(
        ["bash", "-c", f'source "{ENV_SH}" ; echo JE-SUIS-PASSE'],
        capture_output=True, text=True, cwd=str(tmp_path), env=env)
    assert p.returncode == 1
    assert "JE-SUIS-PASSE" not in p.stdout, (
        "le socle a laissé le script continuer après un refus : la garde "
        "promise est « s'arrêter AVANT d'agir »")


# ---------------------------------------------------------------------------
# LA RÈGLE, ÉCRITE — parce que c'est la phrase qui survit aux relectures
# ---------------------------------------------------------------------------

def test_le_socle_ecrit_la_regle_qu_il_applique():
    """Sept pages ont promis une garde que le code avait perdue.

    Le remède mécanique n'est pas seulement le test ci-dessus : c'est que la
    règle soit écrite LÀ OÙ ELLE S'APPLIQUE, pour que celui qui change le code
    lise la promesse dans le même écran.
    """
    texte = ENV_SH.read_text(encoding="utf-8")
    assert "ON N'AGIT JAMAIS SUR UN CERVEAU QUE PERSONNE" in texte
    for rang in ("rang 1", "rang 2", "rang 3", "rang 4", "rang 5"):
        assert rang in texte, f"« {rang} » n'est plus décrit dans ops/env.sh"


@pytest.mark.parametrize("script", sorted(
    p.name for p in (RACINE / "ops").glob("*.sh")))
def test_aucun_script_d_ops_ne_compose_un_chemin_de_coffre_en_dur(script):
    """Une seule définition de « où vivent les coffres », et une seule règle.

    Deux conventions voisines pour la même question est la classe de défaut que
    ce dépôt passe des manches à éliminer — c'est elle qui avait produit le
    « je ne choisis pas » du DSN pendant qu'on choisissait, du même
    `brain.toml`, le dossier de dumps et le préfixe de rotation.

    Le motif cherché est la COMPOSITION — `/etc/arac/$…` — jamais la mention.
    Un message qui nomme `/etc/arac` à un humain enseigne ; une ligne qui
    fabrique le chemin décide, et une décision qui se prend à deux endroits
    finit par se prendre de deux façons.
    """
    if script == "env.sh":
        pytest.skip("c'est lui, l'endroit unique — c'est tout le sujet")
    texte = (RACINE / "ops" / script).read_text(encoding="utf-8")
    fautes = [n for n, ligne in enumerate(texte.splitlines(), 1)
              if "/etc/arac/$" in ligne]
    assert not fautes, (
        f"ops/{script} compose un chemin de coffre à partir d'un littéral, "
        f"lignes {fautes}. Employez `$ARAC_ETC_DIR`, comme ops/env.sh — sans "
        "quoi la règle des cinq rangs n'est ni unique ni éprouvable.")
