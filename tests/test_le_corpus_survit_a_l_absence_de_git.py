"""LE CORPUS DES GARDES NE S'EFFONDRE PLUS QUAND `git` N'EST PAS LÀ.

CE QUI ÉTAIT CASSÉ, ET CE QUE ÇA COÛTAIT
========================================
``tests/test_f1_aucune_trace_de_l_auteur.py`` et
``tests/test_la_doc_dit_vrai.py`` obtenaient leur corpus par
``subprocess.run([... "git", "ls-files" ...], check=True)``, **au niveau du
module** — ``PERIMETRE = perimetre()``, ``DOCUMENTS = _documents()``. Ces deux
lignes s'exécutent à la COLLECTE. Dans une copie du dépôt privée de son
``.git`` — ce que reçoit quiconque télécharge une archive plutôt que de
cloner — la suite entière tombait ainsi :

    ERROR tests/test_f1_aucune_trace_de_l_auteur.py - subprocess.CalledProcessError
    ERROR tests/test_la_doc_dit_vrai.py - subprocess.CalledProcessError
    !!!!!! Interrupted: 2 errors during collection !!!!!!

Zéro test exécuté, code de sortie 2, et pas une phrase sur la cause. La suite
n'était pas cassée, elle était **inaccessible** — et celui qui la lance en
conclut que le dépôt ne marche pas chez lui.

CE QUE CE FICHIER GARDE
=======================
Trois choses, et la troisième est celle qui compte :

1. le repli existe et rend un corpus **complet** ;
2. il **dit** ce qu'il fait — une phrase lisible, pas un silence ;
3. **il rend EXACTEMENT le même corpus que `git`**, mesuré ici à chaque
   passage, là où `git` est disponible. Un repli dont personne ne compare le
   résultat est un second corpus qui dérive : le jour où quelqu'un écrit dans
   `.gitignore` un motif que le petit lecteur de `corpus_du_depot` ne sait pas
   lire, c'est ce test-ci qui rougit — chez nous, dans un dépôt où `git`
   marche — et jamais chez l'inconnu qui n'a que l'archive.

Hors-ligne : ce module ne lit que des fichiers et n'appelle `git` que sur le
dépôt lui-même, ce que `tests/test_hermeticite_de_la_suite.py` déclare permis.
"""

from __future__ import annotations

import pathlib

from tests.corpus_du_depot import (
    PHRASE_DU_REPLI,
    REGIME,
    REGIME_DISQUE,
    REGIME_GIT,
    _git_rend_la_liste,
    _parcours_du_disque,
    est_ignore,
    fichiers_du_depot,
)

RACINE = pathlib.Path(__file__).resolve().parents[1]


def test_le_corpus_est_complet_quel_que_soit_le_regime():
    """Un corpus vide passe tous les gardes. C'est le premier piège, et il ne
    doit pas se rouvrir par le repli."""
    fichiers = fichiers_du_depot()
    assert len(fichiers) > 300, f"régime « {REGIME} » : {len(fichiers)} fichiers"
    for temoin in ("README.md", "Makefile", "bootstrap/lib/verify.sh",
                   "tests/conftest.py", "app/main.py"):
        assert temoin in fichiers, f"{temoin} manque au corpus ({REGIME})"


def test_le_repli_rend_exactement_le_meme_corpus_que_git():
    """LA PRÉMISSE DU REPLI, et la seule qui vaille : les deux chemins doivent
    rendre le même ensemble, au fichier près.

    Ce test est sauté hors d'un dépôt git — c'est le seul endroit du module où
    sauter est juste : sans `git`, il n'y a pas de second avis à comparer. Il
    ne saute donc JAMAIS chez nous, et c'est là qu'il doit mordre.
    """
    depuis_git = _git_rend_la_liste()
    if depuis_git is None:
        import pytest
        pytest.skip("hors dépôt git : aucun second avis à comparer")
    a, b = set(depuis_git), set(_parcours_du_disque())
    assert a == b, (
        "le repli sur disque ne rend plus ce que `git` rend. Ce n'est pas "
        "anodin : les deux gardes documentaires balaieraient un corpus "
        "différent selon la machine, et personne ne saurait lequel des deux "
        "ment. `tests/corpus_du_depot.py` déclare les quatre formes de "
        "`.gitignore` qu'il ne sait pas lire (`**`, .gitignore imbriqués, "
        "`.git/info/exclude`, motifs ancrés par un `/` de tête) — l'une "
        "d'elles vient probablement d'apparaître.\n"
        f"  vus par git seulement    : {sorted(a - b)}\n"
        f"  vus par le disque seul   : {sorted(b - a)}"
    )


def test_le_repli_dit_ce_qu_il_fait():
    """Un repli muet est un mensonge par omission : la suite tourne, l'utilisateur
    croit qu'elle a tout balayé, et rien ne lui dit qu'elle a changé de chemin."""
    assert REGIME in (REGIME_GIT, REGIME_DISQUE), REGIME
    for morceau in ("SANS git", "archive", "git init"):
        assert morceau in PHRASE_DU_REPLI, PHRASE_DU_REPLI
    assert len(PHRASE_DU_REPLI) > 120, "une phrase trop courte n'enseigne rien"


def test_le_repli_PRONONCE_sa_phrase_et_pas_seulement_l_ecrit():
    """LE TEST AU-DESSUS VÉRIFIAIT LA PHRASE, PAS SA PRONONCIATION.

    Éprouvé le 9 août 2026 : en retirant la ligne
    `warnings.warn(PHRASE_DU_REPLI, …)` de `_decider()`, ce fichier rendait
    « 4 passed ». La constante restait, et elle suffisait — le repli pouvait
    redevenir muet sans qu'un seul test bouge. C'est la même faute que le
    tableau qui coche à côté de sa méthode : on contrôle la présence du TEXTE
    au lieu du GESTE.

    Ici on force le régime disque — `git` déclaré indisponible — et on exige
    l'avertissement. C'est le seul endroit du dépôt où le repli est exécuté
    pour de vrai sur une machine qui a `git`.
    """
    import pytest

    from tests import corpus_du_depot as corpus

    ancien = corpus._git_rend_la_liste
    corpus._git_rend_la_liste = lambda: None  # type: ignore[assignment]
    try:
        with pytest.warns(UserWarning) as prononce:
            fichiers, regime = corpus._decider()
    finally:
        corpus._git_rend_la_liste = ancien  # type: ignore[assignment]

    assert regime == REGIME_DISQUE, regime
    assert len(fichiers) > 300, len(fichiers)
    dites = [str(w.message) for w in prononce]
    assert any(PHRASE_DU_REPLI in d for d in dites), (
        "le repli est devenu MUET : la suite change de chemin de balayage et "
        "ne le dit plus. L'utilisateur qui lance `make test` sur une archive "
        "sans `.git` croira avoir tout vérifié.\n"
        f"  avertissements réellement prononcés : {dites}")


def test_la_question_versionne_reste_posable_sans_git():
    """`git check-ignore` était le seul juge de « versionné ». Sans `git`, il
    répondait « non » à tout — la règle 4 du garde documentaire se désarmait
    en silence. Elle a maintenant une réponse dans les deux régimes."""
    assert est_ignore(".env") is True
    assert est_ignore("config/brain.toml") is True
    assert est_ignore("config/scopes.example.toml") is False
    assert est_ignore("README.md") is False
