"""Le garde qui empêche la suite de détruire un cerveau — sa non-régression.

CE QUI A CHANGÉ, ET POURQUOI
============================

Ce fichier affirmait autrefois que le garde refuse « tout DSN visant `arac` ».
C'était le nom du cerveau de l'AUTEUR, et rien d'autre. Le framework, lui,
nomme la base d'après le cerveau : `camille_brain`, `nadia_brain`, celle de
n'importe qui. **Le cerveau de tout autre utilisateur traversait le garde** —
et la suite y jouait alors une vraie migration 0006 UP/DOWN, plus un
``UPDATE arac.memory_atoms`` dont le ``WHERE`` vise explicitement les lignes
NON-test.

La question posée était mauvaise. Ce n'est pas « *est-ce la base de l'auteur ?* »
— on ne peut pas énumérer les cerveaux du monde. C'est :

    **« cette base m'appartient-elle, à moi, test ? »**

Une base de test se RECONNAÎT : elle porte une marque, posée sur la base
elle-même. Tout le reste est refusé. *Fail-closed*.

Ces tests n'ouvrent aucune connexion : ils exercent la DÉCISION du garde sur
des réponses de base simulées. C'est ce qui leur permet de tourner dans une
suite hermétique — et c'est aussi ce qui permet de prouver le refus d'un DSN de
production QUELCONQUE sans avoir de production sous la main.
"""

from __future__ import annotations

import pytest

from tests.garde_hermetique import (
    MARQUE_DE_TEST,
    RefusHermetique,
    nom_de_base,
    verifie_la_marque_sync,
)


# ============================================================================
# Une base simulée : on lui dit quel commentaire elle porte
# ============================================================================


class _CurseurSimule:
    def __init__(self, commentaire):
        self._commentaire = commentaire

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, requete, *a, **k):
        assert "shobj_description" in requete, requete
        assert "current_database()" in requete, requete

    def fetchone(self):
        return None if self._commentaire is None else (self._commentaire,)


class _BaseSimulee:
    """Une base qui répond ce qu'on lui a dit de répondre à la question du garde."""

    def __init__(self, commentaire):
        self._commentaire = commentaire

    def cursor(self):
        return _CurseurSimule(self._commentaire)


# ============================================================================
# LE CŒUR : un DSN de production QUELCONQUE est refusé
# ============================================================================

#: Des cerveaux réels, tous nommés autrement que celui de l'auteur. C'est la
#: liste que l'ancien garde laissait passer en entier.
CERVEAUX_DE_PRODUCTION = [
    "postgresql://u:p@127.0.0.1:5432/arac",            # celui de l'auteur
    "postgresql://u:p@127.0.0.1:5432/camille_brain",   # ceux que l'ancien
    "postgresql://u:p@127.0.0.1:5432/nadia_brain",     # garde laissait passer
    "postgresql://u:p@127.0.0.1:5432/dominique_brain",
    "postgresql://u:p@10.0.0.4:5432/cerveau",
    "postgresql://u:p@127.0.0.1:5460/arac_b",
    # Le piège inverse : un NOM qui a l'air d'un test, sur une base qui ne
    # porte pas la marque. Le nom ne donne aucun droit.
    "postgresql://u:p@127.0.0.1:5432/arac_test",
    "postgresql://u:p@127.0.0.1:5433/test",
]


@pytest.mark.parametrize("dsn", CERVEAUX_DE_PRODUCTION)
def test_un_cerveau_quelconque_est_refuse(dsn):
    """Le refus ne dépend d'aucune liste de noms — donc il couvre tout le monde."""
    base = nom_de_base(dsn)
    with pytest.raises(RefusHermetique) as pris:
        verifie_la_marque_sync(_BaseSimulee(None), base, "DATABASE_URL_ADMIN")
    message = str(pris.value)
    assert base in message
    # Un refus doit dire quoi faire, sinon il se contourne au lieu de se respecter.
    assert MARQUE_DE_TEST in message
    assert "COMMENT ON DATABASE" in message


@pytest.mark.parametrize(
    "commentaire",
    [
        None,                                   # pas de ligne (base inconnue)
        "",                                     # aucun commentaire
        "cerveau de production — ne pas toucher",
        "arac",                                 # le NOM, pas la marque
        "base de test",                         # une intention, pas la marque
        "arac:cerveau=camille;secrets=/etc/arac/camille",  # la plaque d'un cerveau
    ],
)
def test_tout_ce_qui_n_est_pas_la_marque_est_refuse(commentaire):
    """Fail-closed : dans le doute, on refuse. Seule la marque exacte ouvre."""
    with pytest.raises(RefusHermetique):
        verifie_la_marque_sync(_BaseSimulee(commentaire), "peu_importe")


def test_une_base_marquee_est_acceptee_quel_que_soit_son_nom():
    """La marque, pas le nom : une base de test peut s'appeler comme elle veut."""
    marque = f"{MARQUE_DE_TEST} — son contenu peut être détruit à tout instant"
    for base in ("arac_test", "camille_test", "essai", "zzz"):
        verifie_la_marque_sync(_BaseSimulee(marque), base)  # ne lève pas


def test_il_n_y_a_plus_de_derogation_par_variable_d_environnement(monkeypatch):
    """`ARAC_ALLOW_PROD_TEST_DB=1` ouvrait la prod d'une seule frappe.

    Une variable de shell voyage : elle s'exporte, atterrit dans un `.env`,
    survit à un `source`, et personne ne se souvient de l'avoir posée. La
    marque, elle, est attachée à la base qu'elle décrit — on ne la porte pas
    par accident.
    """
    monkeypatch.setenv("ARAC_ALLOW_PROD_TEST_DB", "1")
    with pytest.raises(RefusHermetique):
        verifie_la_marque_sync(_BaseSimulee(None), "arac", "DATABASE_URL_ADMIN")


def test_le_garde_est_pose_sur_tous_les_chemins_de_connexion():
    """Y compris `psycopg.connect`, qu'utilisent les tests hors fixtures.

    `psycopg.connect` est une méthode DÉJÀ LIÉE, capturée à l'import du paquet.
    Remplacer la classmethod ne la change pas — c'est le trou par lequel
    `test_migration_0006/0007/0008` et `test_bus` ouvraient leur connexion sans
    passer par le moindre garde.
    """
    import psycopg

    from tests.garde_hermetique import installer_les_gardes

    installer_les_gardes()  # idempotent
    for accès in (psycopg.connect, psycopg.Connection.connect,
                  psycopg.AsyncConnection.connect):
        assert getattr(accès, "__name__", "") .startswith("_connect_garde"), accès


def test_nom_de_base_extrait_bien_le_nom():
    """Il ne décide plus rien, mais il nomme la base dans les messages."""
    assert nom_de_base("postgresql://u:p@127.0.0.1:5432/arac") == "arac"
    assert nom_de_base("postgresql://u:p@127.0.0.1:5433/arac_test") == "arac_test"
    assert nom_de_base("postgresql://u:p@h:5432/camille_brain?sslmode=require") \
        == "camille_brain"
