"""Le fichier canonique des variables dit-il la vérité sur le code ?

CE QUE CE TEST EMPÊCHE DE REVENIR
---------------------------------
`.env.example` a proposé pendant longtemps `CC_PASSWORD_HASH`, alors que le
cockpit lit `CC_ADMIN_PASSWORD_HASH`. Un caractère de différence, aucune erreur
nulle part : le service démarre, affiche sa page de connexion, et refuse le mot
de passe pour toujours. Le fichier que l'on relit pour trouver la panne est
justement celui qui ment.

Symétriquement, `ARAC_INGEST_ALLOWED_NODES` n'apparaissait nulle part dans le
fichier canonique alors qu'elle est *fail-closed* : absente, l'ingestion refuse
tout en `403`. Tout est installé, tout semble vivant, et rien n'entre.

Ces deux défauts ne se voient ni à la relecture ni à l'exécution. Ils se voient
en COMPARANT le fichier au code — c'est ce que fait `bootstrap/checks/audit_env.py`,
et c'est ce que ce test fige.

Il ne demande ni base, ni réseau, ni clé d'API : il lit des fichiers.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
AUDIT = RACINE / "bootstrap" / "checks" / "audit_env.py"


def _auditer(racine: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(racine / "bootstrap/checks/audit_env.py")],
        capture_output=True, text=True, timeout=120,
    )


def _copie_legere(destination: Path) -> Path:
    """Un double du dépôt en liens durs — rapide, et PIÉGEUX.

    `cp -al` ne copie pas le contenu : chaque fichier du double partage son
    inode avec l'original. Écrire « dans la copie » écrirait donc dans le
    dépôt de l'utilisateur. Ce piège s'est refermé une fois pendant l'écriture
    de ce test, qui a modifié le vrai `.env.example`. D'où `_reecrire`, plus
    bas : elle CASSE le lien avant d'écrire, et c'est le seul moyen sûr de
    toucher un fichier d'un arbre obtenu ainsi.
    """
    subprocess.run(["cp", "-al", str(RACINE), str(destination)], check=True)
    return destination


def _reecrire(chemin: Path, contenu: str) -> None:
    """Remplace un fichier sans écrire à travers un lien dur."""
    chemin.unlink(missing_ok=True)
    chemin.write_text(contenu, encoding="utf-8")


def test_le_fichier_canonique_et_le_code_sont_d_accord() -> None:
    """Aucune variable documentée sans être lue, ni lue sans être déclarée."""
    r = _auditer(RACINE)
    assert r.returncode == 0, (
        "`.env.example` s'écarte du code. Le détail et le geste sont "
        f"ci-dessous :\n\n{r.stdout}\n{r.stderr}"
    )


def test_une_variable_fantome_fait_echouer_le_controle(tmp_path: Path) -> None:
    """Une garde qui ne mord jamais n'est pas une garde.

    On recopie le dépôt (liens durs, pas de copie profonde), on rajoute au
    fichier canonique un nom que personne ne lit, et on exige un échec. Sans
    ce test, une régression du contrôle lui-même passerait inaperçue : il
    dirait « tout va bien » parce qu'il ne regarde plus rien.
    """
    faux = _copie_legere(tmp_path / "depot")

    canonique = faux / ".env.example"
    _reecrire(
        canonique,
        canonique.read_text(encoding="utf-8")
        + "\n# ARAC_VARIABLE_QUE_PERSONNE_NE_LIT=1\n",
    )

    r = _auditer(faux)
    assert (RACINE / ".env.example").read_text(encoding="utf-8").find(
        "ARAC_VARIABLE_QUE_PERSONNE_NE_LIT"
    ) == -1, "le test a écrit dans le dépôt réel — lien dur non cassé"
    assert r.returncode == 1, (
        "Le contrôle a accepté une variable documentée que rien ne lit. "
        f"Sortie :\n{r.stdout}\n{r.stderr}"
    )
    assert "ARAC_VARIABLE_QUE_PERSONNE_NE_LIT" in r.stdout


def test_une_variable_non_declaree_fait_echouer_le_controle(tmp_path: Path) -> None:
    """L'autre sens : le code lit un nom que rien ne déclare."""
    faux = _copie_legere(tmp_path / "depot")

    _reecrire(
        faux / "ops" / "sonde_test_contrat.sh",
        'echo "${ARAC_NOM_JAMAIS_DECLARE:-}"\n',
    )

    r = _auditer(faux)
    assert r.returncode == 1, (
        "Le contrôle a accepté une variable lue par le code et déclarée nulle "
        f"part. Sortie :\n{r.stdout}\n{r.stderr}"
    )
    assert "ARAC_NOM_JAMAIS_DECLARE" in r.stdout


def test_le_controle_refuse_de_juger_un_arbre_incomplet(tmp_path: Path) -> None:
    """Un verdict qu'on ne peut pas fonder ne se rend pas.

    Sur un arbre où le code manque, le balayage ne trouve rien — et « rien de
    lu » est indistinguable de « tout est faux ». Le contrôle doit sortir en 2
    (« je n'ai pas pu ») et surtout pas en 1 (« tout votre fichier est faux »),
    qui enverrait corriger quarante lignes parfaitement justes.
    """
    faux = tmp_path / "tronque"
    (faux / "bootstrap" / "checks").mkdir(parents=True)
    for nom in ("audit_env.py", "env_contract.toml"):
        (faux / "bootstrap" / "checks" / nom).write_text(
            (RACINE / "bootstrap" / "checks" / nom).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    (faux / ".env.example").write_text(
        (RACINE / ".env.example").read_text(encoding="utf-8"), encoding="utf-8"
    )

    r = _auditer(faux)
    assert r.returncode == 2, (
        "Le contrôle a rendu un verdict sur un dépôt tronqué. "
        f"Sortie :\n{r.stdout}\n{r.stderr}"
    )


@pytest.mark.parametrize(
    "nom",
    [
        # Le cockpit est fail-closed sur ces trois-là : sans elles, `503`.
        "CC_SESSION_SECRET",
        "CC_ADMIN_PASSWORD_HASH",
        "CC_TOTP_SECRET",
        # Fail-closed aussi : sans elle, toute ingestion repart en 403.
        "ARAC_INGEST_ALLOWED_NODES",
    ],
)
def test_les_variables_fail_closed_sont_dans_le_fichier_canonique(nom: str) -> None:
    """Le contrat général ne suffit pas pour celles-ci.

    `audit_env.py` accepte qu'une variable soit rangée dans le contrat plutôt
    que documentée. Pour une variable *fail-closed*, ce compromis est
    inacceptable : son absence ne produit pas une dégradation, elle produit un
    refus total et muet. Elle DOIT être en première page, nommément.
    """
    texte = (RACINE / ".env.example").read_text(encoding="utf-8")
    assert any(
        ligne.lstrip().lstrip("#").lstrip().startswith(f"{nom}=")
        for ligne in texte.splitlines()
    ), f"{nom} est fail-closed et doit figurer dans .env.example."
