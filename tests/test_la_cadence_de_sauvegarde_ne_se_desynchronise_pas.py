"""LA CADENCE DE SAUVEGARDE SE LIT DANS LA MINUTERIE, ELLE NE SE RECOPIE PAS.

CE QUE CE GARDE EMPÊCHE, EN UNE PHRASE
======================================
`ops/watchdog.sh --explain` existe pour une seule raison, qu'il écrit lui-même
en tête : « Aucun [seuil] n'est une convention. Chacun se déduit d'une cadence
observable […] Quand vous changez une cadence, changez le seuil : un seuil qui
ne correspond plus à la réalité entraîne à ignorer les alertes, et une alerte
qu'on ignore est pire que pas d'alerte. » La ligne suivante disait, à l'écran :
« La sauvegarde tourne une fois par jour ». La minuterie que le bootstrap arme
porte `OnCalendar=*-*-* 00,06,12,18:30:00 UTC` et se décrit elle-même
« sauvegarde toutes les six heures ».

26 h ne valait donc pas « un cycle manqué » mais QUATRE, 48 h en valait HUIT, et
la promesse n'était pas « au pire, un jour de perdu » mais « au pire, six heures
de perdues ». Le même écart vivait dans `ops/restore_verify.sh` (« un intervalle
de sauvegarde quotidien ») et dans l'en-tête d'`ops/backup.sh` (« un dump par
jour », « le geste quotidien ») — à sept lignes d'un message qui dit, lui, « un
avertissement imprimé quatre fois par jour n'est plus un avertissement ».

POURQUOI UN GARDE, ET PAS UNE CORRECTION DE PLUS
================================================
C'est la TROISIÈME fois que cette cadence se désynchronise. Les pages ont été
corrigées, le CHANGELOG l'a déclaré honnêtement en « connu et non résolu » — et
le PRODUIT a continué d'imprimer l'inverse, à l'endroit exact où il prétend
justifier ses chiffres. Une fausseté déclarée reste imprimée à l'écran de qui
cherche pourquoi un seuil vaut ce qu'il vaut.

Ce garde-ci fait ce que fait déjà `test_l_ecran_de_fin_ne_promet_pas_un_effet_
absent.py` avec le seuil de 70 : il LIT la source de vérité — la ligne
`OnCalendar=` que `bootstrap/lib/services.sh` écrit dans la minuterie — au lieu
de recopier un nombre.

CE QU'IL NE COUVRE PAS, DIT PLUTÔT QUE TU
=========================================
Les tournures interdites sont une LISTE : ce sont les formes exactes qui ont
été mesurées dans ce dépôt. « une sauvegarde nocturne », « chaque matin », « le
dump du jour » y échapperaient. Une liste de formes n'est pas un critère de
sens, et on ne prétend pas le contraire. Ce qui ferme la classe pour de bon est
l'autre moitié de ce fichier : l'exigence que les trois outils qui citent la
cadence citent la LIGNE de la minuterie elle-même. Le jour où elle change, ils
rougissent, et personne n'a besoin d'avoir pensé à la bonne tournure.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
SERVICES = RACINE / "bootstrap" / "lib" / "services.sh"

#: Les fichiers d'`ops/` qui CITENT la cadence de sauvegarde pour en déduire un
#: seuil ou une promesse. Chacun a menti au moins une fois.
CITENT_LA_CADENCE = ("watchdog.sh", "restore_verify.sh", "backup.sh")

#: LES TOURNURES QUI DISENT « UNE PAR JOUR ». Relevées une par une dans ce
#: dépôt — ce sont celles qui ont réellement été écrites, pas celles qu'on
#: imagine. Elles sont refusées tant que la minuterie ne passe pas exactement
#: une fois par jour.
TOURNURES_QUOTIDIENNES = (
    "une fois par jour",
    "un dump par jour",
    "le geste quotidien",
    "un jour de perdu",
    "sauvegarde quotidienne",
    "intervalle de sauvegarde quotidien",
    "dump quotidien",
)


def _ligne_oncalendar_de_la_sauvegarde() -> str:
    """La ligne `OnCalendar=` que le bootstrap écrit dans la minuterie de dump.

    On la prend DANS la fonction qui engendre l'unité, pas n'importe où dans le
    fichier : `services.sh` en écrit trois (le cycle du cortex, la vérification
    hebdomadaire de restauration, la sauvegarde), et confondre deux cadences
    est précisément le défaut qu'on garde ici.
    """
    texte = SERVICES.read_text(encoding="utf-8")
    debut = texte.index("_unite_backup_timer()")
    corps = texte[debut:debut + 2000]
    trouve = re.search(r"^OnCalendar=(.+)$", corps, re.MULTILINE)
    assert trouve, corps[:500]
    return trouve.group(1).strip()


def _passages_par_jour(oncalendar: str) -> int:
    """Combien de fois la minuterie passe par jour, DÉDUIT de sa ligne."""
    trouve = re.match(r"\*-\*-\* ([0-9,]+):", oncalendar)
    assert trouve, f"forme d'OnCalendar non gérée par ce garde : {oncalendar}"
    return len(trouve.group(1).split(","))


def test_la_minuterie_dit_la_meme_chose_que_sa_propre_description():
    """La première cohérence est INTERNE : l'unité ne se contredit pas elle-même."""
    texte = SERVICES.read_text(encoding="utf-8")
    debut = texte.index("_unite_backup_timer()")
    corps = texte[debut:debut + 2000]
    passages = _passages_par_jour(_ligne_oncalendar_de_la_sauvegarde())
    assert passages == 4, corps[:600]
    assert "toutes les six heures" in corps, (
        "La description de la minuterie ne dit plus la cadence que sa ligne "
        f"OnCalendar impose ({passages} passages par jour).")


@pytest.mark.parametrize("nom", CITENT_LA_CADENCE)
def test_aucun_outil_ne_promet_une_sauvegarde_par_jour(nom):
    """Le produit ne dit pas l'inverse de sa propre minuterie."""
    passages = _passages_par_jour(_ligne_oncalendar_de_la_sauvegarde())
    if passages == 1:
        pytest.skip("la minuterie passe bien une fois par jour")
    texte = (RACINE / "ops" / nom).read_text(encoding="utf-8")
    plat = re.sub(r"\s*\n#:?\s*", " ", texte)
    for tournure in TOURNURES_QUOTIDIENNES:
        for phrase in re.findall(r"[^.\n]*" + re.escape(tournure) + r"[^.\n]*",
                                 plat):
            # UNE CITATION DU PASSÉ N'EST PAS UNE PROMESSE, ET UNE NÉGATION
            # NON PLUS. Le commentaire qui raconte d'où viennent 26 h et 48 h
            # doit pouvoir nommer la cadence dont ils sont HÉRITÉS, et celui
            # qui corrige doit pouvoir écrire « la promesse n'est pas “un jour
            # de perdu” » — sinon on interdit d'expliquer la dette, et une
            # dette qu'on ne peut pas écrire est une dette qu'on oublie.
            assert re.search(r"HÉRIT|hérit|révolu|n['’]existe plus|au lieu de"
                             r"|n['’]est (?:donc )?pas|ne vaut pas", phrase), (
                f"ops/{nom} promet une cadence QUOTIDIENNE alors que la "
                f"minuterie passe {passages} fois par jour "
                f"(OnCalendar={_ligne_oncalendar_de_la_sauvegarde()}). Un "
                "seuil qui ne correspond plus à la réalité entraîne à ignorer "
                f"les alertes.\nPhrase : {phrase.strip()}")


@pytest.mark.parametrize("nom", CITENT_LA_CADENCE)
def test_chaque_outil_cite_la_minuterie_plutot_que_de_la_paraphraser(nom):
    """LA MOITIÉ QUI FERME LA CLASSE.

    Une paraphrase se désynchronise en silence ; une citation rougit. Chacun
    des trois outils doit porter, en clair, soit la ligne `OnCalendar=` de la
    minuterie, soit l'intervalle qu'elle impose. Le jour où la cadence change,
    ce test tombe — et il tombe AVANT que quelqu'un n'aille chercher pourquoi
    son alerte n'est pas partie.
    """
    oncalendar = _ligne_oncalendar_de_la_sauvegarde()
    passages = _passages_par_jour(oncalendar)
    heures = 24 // passages
    texte = (RACINE / "ops" / nom).read_text(encoding="utf-8")
    plat = re.sub(r"\s*\n#:?\s*", " ", texte)
    attendus = (oncalendar, f"{passages} fois par jour",
                f"{passages} FOIS PAR JOUR",
                {1: "une", 2: "deux", 3: "trois", 4: "quatre", 6: "six",
                 8: "huit", 12: "douze", 24: "vingt-quatre"}[passages]
                + " fois par jour",
                f"toutes les {heures} heures",
                {6: "toutes les six heures", 12: "toutes les douze heures",
                 8: "toutes les huit heures", 4: "toutes les quatre heures",
                 24: "une fois par jour"}.get(heures, "toutes les %d heures"
                                              % heures))
    assert any(a in plat for a in attendus), (
        f"ops/{nom} parle de la sauvegarde sans jamais citer la cadence que la "
        f"minuterie impose ({oncalendar}). Une paraphrase se désynchronise en "
        "silence : c'est arrivé trois fois.")
