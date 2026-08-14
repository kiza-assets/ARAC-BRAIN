"""Gardes de CONVERGENCE — deux défauts trouvés hors des constats d'audit, le 2026-08-05.

Ces tests ne remplacent pas ``tests/test_cc_v1_preuve_rejouable.py`` (qui vérifie
qu'une preuve est REJOUABLE et qu'elle porte un marqueur) : ils vérifient qu'elle
est **complète**, c'est-à-dire qu'elle porte le chiffre qu'elle prétend soutenir
même quand elle ne montre qu'une partie de ses lignes, et qu'aucune lecture des
reçus de rappel ne compte deux fois le même rappel.

1. LA PREUVE TRONQUÉE PAR SON PROPRE ``LIMIT``
   ------------------------------------------
   Les preuves ligne à ligne de la famille ``aujourdhui`` portent ``LIMIT 60`` et
   invitent le lecteur à compter les lignes marquées ``dans_la_fenetre``. Sur la
   fenêtre de 30 jours, ``today_atoms_created`` affirmait 383 pendant que sa preuve
   n'exposait que 58 lignes marquées, et rien ne le disait ; idem pour les
   conversations reçues (161 → 60), curées (116 → 55) et les cycles (134 → 60).
   La preuve contredisait donc le chiffre — le même défaut que le marqueur calé
   sur un jour tronqué, à ceci près qu'il n'apparaît qu'à partir de la 61e ligne.
   Chaque preuve sert désormais ``total_fenetre``, calculée par fonction de
   fenêtrage (donc AVANT le ``LIMIT``), qui vaut exactement la valeur servie.

2. UN RAPPEL, UNE LIGNE — DANS LES FAMILLES AUSSI
   ----------------------------------------------
   ``entities.py``, ``lifestory.py`` et ``scopes.py`` sont déjà gardés par
   ``test_toute_lecture_comptante_des_recus_est_dedoublonnee``. Les familles ne
   l'étaient pas : cinq lectures de ``families/vues.py`` comptaient les LIGNES de
   ``arac.context_receipts`` et affichaient donc le DOUBLE des rappels réels — 222
   pour un atome dont la fiche annonçait 111 dans le même cockpit. Le doublement
   n'étant pas uniforme (78 rappels sur 1 709 n'ont pas de jumeau v2-fold),
   ``view_load_bearing`` servait 85 atomes porteurs au lieu de 87 : une VALEUR
   fausse, pas seulement un affichage.

Hors-ligne : aucun accès base. Ces tests lisent le SQL déclaré, pas ses résultats.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from control_center.cc_v1.families import aujourdhui

_CC_V1 = pathlib.Path(__file__).resolve().parents[1] / "control_center" / "cc_v1"


def _flat(sql: str) -> str:
    """Le SQL tel que l'API le sert : sur une ligne."""
    return " ".join(sql.split())


# ---------------------------------------------------------------------------
# 1. Une preuve ligne à ligne dit le total qu'elle ne montre pas
# ---------------------------------------------------------------------------

#: Les ``Spec`` dont la preuve est un AGRÉGAT (par jour, par statut, par motif,
#: par projet) : leurs lignes tiennent toutes sous le ``LIMIT``, parce que le
#: regroupement est borné par la fenêtre elle-même (30 jours ⇒ 31 lignes au plus,
#: ``LIMIT 40``) ou par un domaine fini (8 projets, 5 statuts). Elles se
#: reconstruisent par SOMME des colonnes ``…_dans_la_fenetre``, sans troncature
#: possible. Toute autre Spec est servie ligne à ligne et DOIT porter son total.
_PREUVES_AGREGEES = {
    "today_messages_absorbed",     # une ligne par jour, LIMIT 40
    "today_projects_progressed",   # une ligne par projet, sans LIMIT
    "today_cycles_done",           # une ligne par statut
    "today_candidates_dropped",    # une ligne par motif de refus
    "today_recall_served",         # une ligne par jour, LIMIT 40
    "today_cost_per_atom",         # une ligne par jour, LIMIT 40
}

#: Mesures déclarées non mesurables : leur preuve CONSTATE une dépendance absente.
_ABSENTES = {s.key for s in aujourdhui.SPECS if not s.measurable}


@pytest.mark.parametrize("spec", aujourdhui.SPECS, ids=lambda s: s.key)
def test_une_preuve_ligne_a_ligne_porte_le_total_de_sa_fenetre(spec):
    """``LIMIT 60`` + « comptez les lignes marquées » = un chiffre faux au-delà de 60."""
    if spec.key in _ABSENTES or spec.key in _PREUVES_AGREGEES:
        return
    for window in aujourdhui.WINDOWS:
        rendu = _flat(spec.evidence_sql(window))
        assert "AS total_fenetre" in rendu, (
            f"{spec.key}[{window}] : preuve ligne à ligne sans colonne `total_fenetre`. "
            "Son LIMIT la tronque en silence — sur 30 jours, `today_atoms_created` "
            "affirmait 383 en n'exposant que 58 lignes marquées. Le total doit être "
            "calculé par fonction de fenêtrage (`… OVER ()`), donc AVANT le LIMIT."
        )
        assert "OVER ()" in rendu, (
            f"{spec.key}[{window}] : `total_fenetre` doit être une fonction de "
            "fenêtrage — un agrégat simple serait calculé après regroupement, un "
            "compte côté client serait du calcul dans le navigateur."
        )


@pytest.mark.parametrize("spec", aujourdhui.SPECS, ids=lambda s: s.key)
def test_le_total_de_la_fenetre_porte_le_meme_predicat_que_la_valeur(spec):
    """Un total calculé sur un autre prédicat que la valeur serait un second mensonge."""
    if spec.key in _ABSENTES or spec.key in _PREUVES_AGREGEES:
        return
    for window in aujourdhui.WINDOWS:
        intervalle = aujourdhui.WINDOWS[window]
        rendu = _flat(spec.evidence_sql(window))
        # Le total doit porter l'intervalle de la fenêtre demandée, jamais un autre.
        avant, _, apres = rendu.partition("AS total_fenetre")
        fragment = avant[-400:]
        assert f"interval '{intervalle}'" in fragment, (
            f"{spec.key}[{window}] : `total_fenetre` ne cite pas l'intervalle "
            f"'{intervalle}' de la fenêtre servie — il compterait autre chose que "
            "la valeur qu'il prétend porter."
        )


# ---------------------------------------------------------------------------
# 2. Un rappel, une ligne — dans les familles du registre aussi
# ---------------------------------------------------------------------------

#: Les marques d'un dédoublonnage explicite, quel que soit le module qui l'écrit.
_DEDUP_TOKENS = (
    "_UN_RECU_PAR_RAPPEL", "_PREMIER_RECU", "premier_recu", "UN_RECU_PAR_RAPPEL",
    "p.request_id = cr.request_id", "DISTINCT request_id",
)


def _lectures_des_recus_dans_les_familles():
    """(module, ligne, source) pour CHAQUE CHAÎNE SQL de famille lisant les reçus.

    La granularité est la chaîne, pas l'instruction : un ``Metric(...)`` porte
    deux requêtes (valeur et preuve), et juger l'appel entier laisserait passer
    une requête non dédoublonnée dès que l'autre l'est — c'est exactement ainsi
    que le défaut a survécu dans ``vues.py``. Les f-strings sont lues à la source,
    donc avec leurs interpolations (``{_UN_RECU_PAR_RAPPEL}``) sous les yeux.
    """
    for chemin in sorted((_CC_V1 / "families").glob("*.py")):
        source = chemin.read_text(encoding="utf-8")
        arbre = ast.parse(source)
        fstrings = [n for n in ast.walk(arbre) if isinstance(n, ast.JoinedStr)]
        plages = [(n.lineno, n.end_lineno or n.lineno) for n in fstrings]
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.JoinedStr):
                segment = ast.get_source_segment(source, noeud) or ""
            elif isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
                dans_une_fstring = any(
                    d <= noeud.lineno and (noeud.end_lineno or noeud.lineno) <= f
                    for d, f in plages)
                if dans_une_fstring:
                    continue
                segment = noeud.value
            else:
                continue
            if "FROM arac.context_receipts" in segment:
                yield chemin.name, noeud.lineno, segment


def test_aucune_famille_ne_compte_deux_fois_le_meme_rappel():
    """``count(*)`` sur ``context_receipts`` sans dédoublonnage = le double affiché."""
    fautes = []
    vus = set()
    for module, ligne, segment in _lectures_des_recus_dans_les_familles():
        # Un même `Call` imbriqué remonte plusieurs fois : on ne juge qu'une fois
        # par (module, ligne) et on retient le segment le plus proche de la lecture.
        if (module, ligne) in vus:
            continue
        vus.add((module, ligne))
        if any(t in segment for t in _DEDUP_TOKENS):
            continue
        if "SELECT DISTINCT" in segment:
            continue      # ENSEMBLE d'atomes servis : le doublon y est absorbé
        if re.search(r"EXISTS\s*\(\s*SELECT\s+1\s+FROM\s+arac\.context_receipts", segment):
            continue      # test d'existence : « a-t-il déjà été rappelé ? »
        # La ventilation PAR MOTEUR est la seule lecture qui DOIVE voir les deux
        # reçus : c'est elle qui rend le doublement visible au lieu de le cacher.
        # Elle est exemptée à une condition : nommer ce qu'elle compte — des
        # `recus`, jamais des `rappels`. Un compte de lignes qui se ferait passer
        # pour un compte de rappels retomberait dans la faute.
        if "engine_version" in segment and ("AS recus" in segment
                                            or "count(DISTINCT" in segment):
            continue
        fautes.append(f"{module}:{ligne}")
    assert not fautes, (
        "lecture(s) de arac.context_receipts sans dédoublonnage dans les familles : "
        f"{fautes}. Depuis FOLD V2 chaque rappel écrit DEUX reçus au même "
        "`request_id` (moteur servi v1, moteur d'ombre v2-fold) : compter les lignes "
        "affiche le double, et `view_load_bearing` servait 85 porteurs au lieu de 87. "
        "Coller `_UN_RECU_PAR_RAPPEL` dans le WHERE, ou compter des `request_id` "
        "distincts, ou passer par un `SELECT DISTINCT` d'atomes servis.")


def test_le_fragment_de_dedoublonnage_des_vues_survit_a_la_mise_sur_une_ligne():
    """Règle 9 : un ``--`` dans un fragment servi masquerait tout ce qui suit."""
    from control_center.cc_v1.families import vues

    for nom, fragment in (("_PREMIER_RECU", vues._PREMIER_RECU),
                          ("_UN_RECU_PAR_RAPPEL", vues._UN_RECU_PAR_RAPPEL),
                          ("_UN_RECU_PAR_RAPPEL_SEUL", vues._UN_RECU_PAR_RAPPEL_SEUL)):
        plat = _flat(fragment)
        assert "--" not in plat, f"vues.{nom} : commentaire SQL '--' interdit."
        assert "%" not in plat, (
            f"vues.{nom} : un '%' littéral serait lu comme un marqueur de paramètre.")
