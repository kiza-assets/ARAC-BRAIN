"""Le code et le schéma disent-ils la même chose ? (`bootstrap/checks/audit_schema_refs.py`)

CE QUE CE FICHIER GARDE, ET POURQUOI IL EXISTE
==============================================

`arac.memory_review_queue` a été lue par deux consommateurs de production
pendant toute la vie du dépôt sans qu'AUCUNE migration ne la crée : son DDL
dormait dans `db/migrations/proposals/`, que rien n'applique. Les deux lecteurs
dégradent proprement (SAVEPOINT, try/except) : la panne ne produisait donc
aucune erreur, aucune ligne de journal, aucun test rouge. Elle était invisible.

Aucun garde-fou du dépôt ne croisait ces deux moitiés. Celui-ci le fait, et il
tourne dans `make test` : hermétique, sans base, sur le seul contenu du dépôt.

Trois tests, et le troisième compte autant que les deux premiers :
  1. toute référence `arac.<objet>` du code se résout dans le schéma bâti ;
  2. les deux consommateurs connus de `memory_review_queue` sont bien vus par
     le détecteur — sans quoi le point 1 passerait au vert en ne regardant rien ;
  3. le détecteur ÉCHOUE quand on lui retire un objet du schéma. Un contrôle
     qu'on n'a jamais vu échouer n'est pas un contrôle : c'est une décoration.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[1]
_AUDIT = _RACINE / "bootstrap" / "checks" / "audit_schema_refs.py"

sys.path.insert(0, str(_AUDIT.parent))
import audit_schema_refs as asr  # noqa: E402


def test_toutes_les_references_se_resolvent():
    """Chaque `arac.<objet>` nommé par le code existe dans le schéma bâti."""
    r = subprocess.run(
        [sys.executable, str(_AUDIT)],
        capture_output=True, text=True, cwd=str(_RACINE),
    )
    assert r.returncode == 0, (
        "Une référence du code ne correspond à aucun objet du schéma.\n"
        "C'est une panne SILENCIEUSE : les lecteurs dégradent sans rien dire.\n\n"
        + r.stdout + r.stderr
    )


def test_le_detecteur_voit_les_noms_portes_par_un_litteral():
    """Le nom de table en variable est la forme qui manquait au détecteur.

    `ingest_watchdog` construit sa requête depuis un tuple de noms
    (`"arac.memory_review_queue"`) puis interpole. Une détection qui n'aurait
    reconnu que `FROM arac.…` aurait laissé passer exactement le défaut qui a
    motivé ce contrôle.
    """
    refs = asr.references(_RACINE)
    assert "memory_review_queue" in refs, (
        "Le détecteur ne voit plus la référence portée par un littéral : "
        "il ne garde plus rien."
    )
    assert "memory_atoms" in refs and "run_receipts" in refs


def test_le_detecteur_ecarte_les_journaux_et_les_evenements():
    """`arac.` préfixe aussi des journaux et des événements SSE, jamais des tables."""
    refs = asr.references(_RACINE)
    for faux in ("api", "cortex", "cc", "event", "env"):
        assert faux not in refs, (
            f"« arac.{faux} » n'est pas un objet SQL : le détecteur confond un "
            f"espace de noms avec une relation, et rendra des faux positifs."
        )


def test_le_detecteur_echoue_quand_un_objet_manque(tmp_path, monkeypatch):
    """Retirer un objet du schéma DOIT rendre le contrôle rouge.

    Sans ce test, une régression du détecteur (une expression rationnelle qui
    ne trouve plus rien, une racine de balayage réduite) rendrait un ✓ vert
    éternel — la faute exacte de la manche précédente, où le seul garde F1
    bornait son balayage à un répertoire.
    """
    bati = asr.schema_statique(_RACINE)
    assert "memory_atoms" in bati, "le schéma statique ne se lit plus"

    ampute = tmp_path / "objets.txt"
    ampute.write_text(
        "\n".join(sorted(bati - {"memory_atoms"})) + "\n", encoding="utf-8"
    )
    r = subprocess.run(
        [sys.executable, str(_AUDIT), "--objets", str(ampute)],
        capture_output=True, text=True, cwd=str(_RACINE),
    )
    assert r.returncode == 1, "un objet manquant n'a PAS été signalé"
    assert "arac.memory_atoms" in r.stdout


def test_liste_vide_ne_conclut_rien(tmp_path):
    """Une mesure impossible se dit « 2 », jamais « 0 » ni « 1 ».

    C'est la doctrine de `verify_install.sh` appliquée ici : un contrôle qui
    n'a pas pu mesurer n'a le droit ni de rassurer, ni d'alarmer.
    """
    vide = tmp_path / "vide.txt"
    vide.write_text("", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(_AUDIT), "--objets", str(vide)],
        capture_output=True, text=True, cwd=str(_RACINE),
    )
    assert r.returncode == 2
