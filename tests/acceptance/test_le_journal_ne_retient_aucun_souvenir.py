"""LE GARDE QUI MORD : rien de la mémoire ne peut plus entrer dans journald.

CE QUE CE TEST REMPLACE
-----------------------
Le contrôle précédent cherchait une CHAÎNE de caractères dans le journal d'un
cerveau d'essai : `grep temoin-bascule-`. Il rendait « ✓ » à chaque passage, et
il avait deux trous, tous deux mécaniques :

  1. les témoins entraient en base par un `INSERT` psql, jamais par l'API — or
     la seule route qui fuyait était celle de l'API, que l'acceptation
     n'emprunte pas faute de clé d'embeddings payante ;
  2. il cherchait le témoin d'une ANCIENNE fuite, donc il ne pouvait par
     construction voir aucune des suivantes.

Chercher un témoin, c'est demander à la fuite de se produire pendant qu'on
regarde. Ce test-ci ne regarde pas : il lit le CODE des modules qu'un
`ExecStart` peut atteindre et refuse la FORME qui laisse fuir — avant même
qu'un cerveau existe.

Le contrôle par témoin garde sa place (il vérifie l'exécution réelle, sur le
banc, cf. le §13 de l'installation). Les deux ne se remplacent pas : l'un dit
« ce qui a coulé aujourd'hui », l'autre dit « ce qui peut couler demain ».
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from garde_journal import (  # noqa: E402
    REDUCTEURS,
    VOCABULAIRE_MEMOIRE,
    entrees_execstart,
    fermeture,
    inventaire,
)

RACINE = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 1. Le périmètre est réel, et il est vaste
# ---------------------------------------------------------------------------


def test_le_garde_lit_les_execstart_du_produit_et_non_une_liste_recopiee():
    """Les entrées viennent de `bootstrap/lib/services.sh`, pas d'ici.

    Un garde qui recopie ce qu'il surveille surveille sa copie : le jour où une
    quatrième unité démarre un quatrième module, la copie reste verte.
    """
    entrees = entrees_execstart(RACINE)
    assert entrees, (
        "aucune entrée ExecStart lue dans bootstrap/lib/services.sh — le garde "
        "ne surveille plus rien"
    )
    assert "app.main" in entrees
    assert "control_center.app" in entrees
    assert "agents.cortex.cycle" in entrees


def test_le_perimetre_atteint_les_modules_charges_dynamiquement():
    """`cc_v1/scopes.py` et `lifestory.py` sont DANS le périmètre.

    Ils ne sont atteignables que par `importlib.import_module` depuis
    `cc_v1/registry.py` : une fermeture d'imports statique ne les voit pas, et
    c'est exactement là que dormaient deux des trois fuites restantes. Si ce
    test tombe, le garde est redevenu aveugle là où il l'a déjà été.
    """
    fichiers = {str(p.relative_to(RACINE)) for p in fermeture(RACINE)}
    for attendu in (
        "control_center/cc_v1/scopes.py",
        "control_center/cc_v1/lifestory.py",
        "control_center/cc_v1/entities.py",
        "agents/cortex/dispose.py",
        "app/routers/atoms.py",
        "app/main.py",
    ):
        assert attendu in fichiers, f"{attendu} est hors du périmètre du garde"
    assert len(fichiers) > 100, (
        f"périmètre suspicieusement étroit ({len(fichiers)} fichiers)"
    )


# ---------------------------------------------------------------------------
# 2. Le verdict
# ---------------------------------------------------------------------------


def test_aucun_execstart_ne_peut_imprimer_un_souvenir():
    """LE test. Zéro violation, et le rapport nomme chaque ligne fautive."""
    violations = inventaire(RACINE)
    if violations:
        rapport = "\n".join(
            f"  {v.fichier}:{v.ligne} [{v.regle}] {v.motif}\n      {v.extrait}"
            for v in violations
        )
        pytest.fail(
            f"{len(violations)} ligne(s) de journalisation peuvent imprimer un "
            f"souvenir dans journald :\n{rapport}\n\n"
            "Le remède : `app.journal.sha8` pour une clé ou un domaine, "
            "`app.journal.raison` pour une exception, `app.journal.reduire` "
            "pour une structure entière. La substance va en base, jamais dans "
            "le journal de la machine."
        )


# ---------------------------------------------------------------------------
# 3. LE GARDE MORD — la preuve, et elle est jouée
# ---------------------------------------------------------------------------
#
# Un garde qu'on n'a jamais vu échouer n'est pas un garde : c'est une
# décoration. Chacune des quatre règles est réintroduite pour de vrai, dans un
# fichier temporaire du périmètre, et le garde doit la voir.


@pytest.fixture
def module_du_perimetre(tmp_path, monkeypatch):
    """Fabrique un faux dépôt minimal, avec ses ExecStart et son périmètre."""

    def _fabrique(corps: str, entree: str = "") -> Path:
        racine = tmp_path / "faux_depot"
        (racine / "bootstrap" / "lib").mkdir(parents=True)
        (racine / "bootstrap" / "lib" / "services.sh").write_text(
            'ARAC_API_APP="${ARAC_API_APP:-paquet.entree:app}"\n', encoding="utf-8"
        )
        # `paquet` n'est pas un paquet de première partie : on le déclare tel
        # quel dans le garde via son nom, donc on réutilise `app`.
        (racine / "app").mkdir()
        (racine / "app" / "__init__.py").write_text("", encoding="utf-8")
        (racine / "bootstrap" / "lib" / "services.sh").write_text(
            'ARAC_API_APP="${ARAC_API_APP:-app.entree:app}"\n', encoding="utf-8"
        )
        (racine / "app" / "entree.py").write_text(
            "import logging\n"
            "from app.journal import installer_garde_journal\n"
            "installer_garde_journal()\n"
            "logger = logging.getLogger('x')\n" + entree,
            encoding="utf-8",
        )
        (racine / "app" / "journal.py").write_text(
            "def installer_garde_journal():\n    return 0\n", encoding="utf-8"
        )
        (racine / "app" / "fuite.py").write_text(
            "import logging\nlogger = logging.getLogger('x')\n" + textwrap.dedent(corps),
            encoding="utf-8",
        )
        return racine

    return _fabrique


def test_le_garde_mord_sur_un_domaine_en_clair(module_du_perimetre):
    """G3 — `extra={"scope": …}` : la forme exacte des sites 6, 7 et 8."""
    racine = module_du_perimetre(
        """
        def f(scope_value):
            logger.info("x", extra={"scope": scope_value})
        """
    )
    violations = inventaire(racine)
    assert any(v.regle == "G3" for v in violations), violations
    assert any("scope" in v.motif for v in violations)


def test_le_garde_mord_sur_un_gabarit_qui_nomme_un_champ_de_memoire(module_du_perimetre):
    """G4 — `"… scope=%s …", resolved` : la ligne de `cc_v1/scopes.py:827`."""
    racine = module_du_perimetre(
        """
        def f(resolved):
            logger.warning("cc_v1.x scope=%s", resolved)
        """
    )
    assert any(v.regle == "G4" for v in inventaire(racine))


def test_le_garde_mord_sur_une_exception_en_clair(module_du_perimetre):
    """G2 — `f"{type(e).__name__}: {e}"` : le message porte la ligne fautive.

    MESURÉ : `NotNullViolation: null value in column "rationale" … DETAIL:
    Failing row contains (…, perso/sante, temoin-…, <LE SOUVENIR>, …)`.
    """
    racine = module_du_perimetre(
        """
        def f():
            try:
                pass
            except Exception as exc:
                logger.error("x", extra={"error": f"{type(exc).__name__}: {exc}"})
        """
    )
    assert any(v.regle == "G2" for v in inventaire(racine))


def test_le_garde_mord_sur_un_champ_compose_que_le_vocabulaire_ne_nomme_pas(
    module_du_perimetre,
):
    """G5 — `where=%s` avec un `where` composé : la fuite MESURÉE du cockpit.

    Aucun vocabulaire de la mémoire ne contient le mot « where », et il n'y a
    aucune raison qu'il le contienne. Pourtant `_failure(f"scope:{resolved}")`
    y range un domaine, et `journalctl -u …-cockpit.service` rendait
    « where=scope:perso/sante » à chaque panne. G3 n'aurait jamais pu le voir ;
    G5, fermé par défaut sur le texte du message, le voit.
    """
    racine = module_du_perimetre(
        """
        def f(where):
            logger.warning("cc_v1.entities_failed where=%s", where)
        """
    )
    violations = inventaire(racine)
    assert any(v.regle == "G5" for v in violations), violations


def test_le_garde_ne_mord_pas_sur_une_ligne_correcte(module_du_perimetre):
    """La contrepartie : un garde qui crie à tort finit désarmé."""
    racine = module_du_perimetre(
        """
        from app.journal import raison, sha8
        def f(scope_value, payload):
            try:
                pass
            except Exception as exc:
                logger.error("x", extra={"scope_sha8": sha8(scope_value),
                                         "raison": raison(exc),
                                         "n": len(payload)})
        """
    )
    assert inventaire(racine) == []


def test_le_garde_mord_quand_le_filet_n_est_pas_pose(module_du_perimetre):
    """G1 — un ExecStart sans `installer_garde_journal()` n'assainit rien."""
    racine = module_du_perimetre("", entree="")
    (racine / "app" / "entree.py").write_text(
        "import logging\nlogger = logging.getLogger('x')\n", encoding="utf-8"
    )
    violations = inventaire(racine)
    assert any(v.regle == "G1" for v in violations), violations


# ---------------------------------------------------------------------------
# 4. Le garde ne peut pas devenir aveugle en silence
# ---------------------------------------------------------------------------


def test_le_vocabulaire_couvre_les_colonnes_du_schema():
    """Ce que le SCHÉMA appelle mémoire doit être dans le vocabulaire.

    `arac.memory_atoms` porte `scope`, `key`, `value`, `rationale`. Si une
    migration renomme une colonne sans que ce vocabulaire suive, le garde
    devient aveugle sur elle — et personne ne s'en aperçoit.
    """
    for colonne in ("scope", "key", "value", "rationale"):
        assert colonne in VOCABULAIRE_MEMOIRE, (
            f"« {colonne} » est une colonne de arac.memory_atoms et n'est plus "
            "dans le vocabulaire du garde"
        )


def test_les_reducteurs_existent_vraiment():
    """Chaque réducteur autorisé doit être une fonction réelle du dépôt.

    Sans cela, une faute de frappe dans la liste (`sha_8`) ouvrirait une porte
    silencieuse : le garde laisserait passer tout ce qui s'appelle ainsi.
    """
    import app.journal as journal
    from agents.cortex import dedup_thresholds

    for nom in ("sha8", "empreinte", "reduire", "raison", "diagnostic_exception",
                "trace_assainie", "assainir_texte"):
        assert nom in REDUCTEURS
        assert callable(getattr(journal, nom)), nom
    assert callable(dedup_thresholds.key_sha8)


# ---------------------------------------------------------------------------
# 5. Le filet fait ce qu'il promet — mesuré, pas raisonné
# ---------------------------------------------------------------------------


def test_le_filet_efface_la_ligne_fautive_d_une_erreur_postgres():
    """Le canal MESURÉ, rejoué en une seconde et sans base.

    On reconstruit à l'identique le message que PostgreSQL a rendu sur le banc,
    on le fait passer par `_logger.exception` avec le filtre posé, et on
    vérifie qu'aucun des trois témoins ne survit.
    """
    import io
    import logging

    import app.journal as journal

    class FausseDiag:
        sqlstate = "23502"
        constraint_name = None
        table_name = "memory_atoms"
        column_name = "rationale"
        schema_name = "arac"
        datatype_name = None

    class FausseNotNullViolation(Exception):
        diag = FausseDiag()

    message = (
        'null value in column "rationale" of relation "memory_atoms" violates '
        "not-null constraint\n"
        "DETAIL:  Failing row contains (c0318c68, note, perso/sante, "
        "temoin-jrn1-500, SECRETJRN1500 traitement lithium 400mg matin et "
        "soir, [0.0099], 3c899bf5, {}, active, null)."
    )

    tampon = io.StringIO()
    journaliseur = logging.getLogger("arac.test.filet")
    journaliseur.handlers.clear()
    journaliseur.propagate = False
    collecteur = logging.StreamHandler(tampon)
    collecteur.addFilter(journal.FiltreMemoire())
    journaliseur.addHandler(collecteur)
    journaliseur.setLevel(logging.ERROR)

    try:
        raise FausseNotNullViolation(message)
    except FausseNotNullViolation:
        journaliseur.exception("request.failed")

    sortie = tampon.getvalue()
    for temoin in ("SECRETJRN1500", "lithium", "perso/sante", "temoin-jrn1-500"):
        assert temoin not in sortie, (
            f"« {temoin} » a survécu au filet :\n{sortie}"
        )
    # Ce qui doit RESTER : de quoi dépanner.
    assert "request.failed" in sortie
    assert "FausseNotNullViolation" in sortie
    assert "23502" in sortie
    assert "memory_atoms" in sortie and "rationale" in sortie
    assert "sha8:" in sortie
    # Et la forme courte, celle qui remplace `f"{type(e).__name__}: {e}"` :
    courte = journal.raison(FausseNotNullViolation(message))
    assert courte.startswith("FausseNotNullViolation[23502 memory_atoms.rationale]")
    for temoin in ("SECRETJRN1500", "lithium", "perso/sante"):
        assert temoin not in courte


def test_le_filet_est_pose_sur_uvicorn_aussi():
    """La trace sortait TROIS fois : une par nous, deux par uvicorn.

    Corriger `_logger.exception` seul en aurait laissé passer deux. Le filtre
    s'installe donc sur TOUS les journaliseurs du processus, y compris ceux
    qu'aucune relecture de `app/` n'aurait trouvés.
    """
    import logging

    import app.journal as journal

    logging.getLogger("uvicorn.error")  # le journaliseur existe désormais
    poses = journal.installer_garde_journal()
    assert poses >= 0
    cible = logging.getLogger("uvicorn.error")
    assert any(isinstance(f, journal.FiltreMemoire) for f in cible.filters), (
        "le journaliseur d'uvicorn n'est pas couvert — la trace en ressortirait"
    )


def test_reduire_est_ferme_par_defaut():
    """`reduire` empreinte tout texte, garde les nombres, ne devine rien."""
    import app.journal as journal

    contexte = {
        "length": 85,
        "target_min": 200,
        "preview": "POURQUOI parce que Jrn a fait un choc anaphylactique",
        "scope": "perso/sante",
        "existing_combos": [{"scope": "perso/sante", "kind": "decision", "count": 1}],
    }
    reduit = journal.reduire(contexte)
    texte = repr(reduit)
    assert "anaphylactique" not in texte
    assert "perso/sante" not in texte
    assert reduit["length"] == 85 and reduit["target_min"] == 200
    assert reduit["preview"].startswith("sha8:")
    # Stable : la même valeur rend la même empreinte, donc on corrèle encore.
    assert journal.reduire("perso/sante") == journal.reduire("perso/sante")


def test_le_garde_tourne_en_moins_de_dix_secondes():
    """Un garde lent finit contourné. Il lit 134 fichiers : il doit être rapide."""
    import time

    debut = time.perf_counter()
    inventaire(RACINE)
    assert time.perf_counter() - debut < 10.0


def test_le_garde_est_jouable_seul():
    """Il se lance sans pytest, pour qu'un mainteneur puisse le tirer à la main."""
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys;sys.path.insert(0, %r);"
         "from garde_journal import inventaire;"
         "from pathlib import Path;"
         "v=inventaire(Path(%r));"
         "print(len(v));sys.exit(1 if v else 0)"
         % (str(Path(__file__).resolve().parent), str(RACINE))],
        capture_output=True, text=True, cwd=str(RACINE),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
