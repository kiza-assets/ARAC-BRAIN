"""Mode dégradé : sans clé d'embeddings, l'API ENSEIGNE au lieu de planter.

Ce fichier existe parce qu'une installation faite exactement comme le bootstrap
la propose — sans clé, « pour observer la chaîne d'ingestion avant d'engager la
moindre dépense » — rendait ceci sur le tout premier rappel :

    HTTP/1.1 500 Internal Server Error
    content-type: text/plain
    Internal Server Error

Le premier geste d'un nouvel utilisateur produisait une erreur nue. On vérifie
donc trois choses, qui ne se déduisent pas l'une de l'autre :

  1. l'absence de clé lève un type RECONNAISSABLE (et non `RuntimeError` nu) ;
  2. l'application réelle a bien le handler branché — sans quoi tout le reste
     est vrai en laboratoire et faux en production ;
  3. la réponse est un 503 JSON qui dit ce qui manque, pourquoi, et le geste.

Hermétique : ni base, ni réseau, ni clé.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app import errors, main
from app.services import embeddings


@pytest.fixture(autouse=True)
def _sans_cle(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(embeddings, "_client", None)
    yield
    monkeypatch.setattr(embeddings, "_client", None)


# ---------------------------------------------------------------------------
# 1. Le type
# ---------------------------------------------------------------------------


def test_sans_cle_le_type_leve_est_reconnaissable():
    with pytest.raises(embeddings.EmbeddingsIndisponibles):
        embeddings._get_client()


def test_reste_une_runtime_error():
    """Compatibilité : le code qui attrapait `RuntimeError` marche toujours."""
    assert issubclass(embeddings.EmbeddingsIndisponibles, RuntimeError)


def test_le_message_ne_designe_pas_un_fichier_qui_n_existe_pas():
    """L'ancien message envoyait vers `$ARAC_HOME/.env`, qu'aucun bootstrap
    n'écrit — le fichier réellement posé est /etc/arac/<base>/arac.env."""
    with pytest.raises(embeddings.EmbeddingsIndisponibles) as exc:
        embeddings._get_client()
    assert "ARAC_HOME" not in str(exc.value)


# ---------------------------------------------------------------------------
# 2. Le branchement sur l'application RÉELLE
# ---------------------------------------------------------------------------


def test_le_handler_est_branche_sur_l_application():
    assert embeddings.EmbeddingsIndisponibles in main.app.exception_handlers


# ---------------------------------------------------------------------------
# 3. La réponse rendue
# ---------------------------------------------------------------------------


def _app_temoin() -> FastAPI:
    """Une application minimale portant le MÊME handler que la vraie.

    On ne passe pas par les routes réelles : elles exigent une connexion à la
    base avant même d'appeler `embed()`, et la suite est hermétique.
    """
    app = FastAPI()
    errors.enregistrer_handlers(app)

    @app.post("/v1/atoms/recall")
    async def _recall():
        return await embeddings.embed("bonjour")

    @app.post("/v1/atoms")
    async def _creer():
        return await embeddings.embed("bonjour")

    return app


async def _appeler(chemin: str):
    transport = ASGITransport(app=_app_temoin(), client=("127.0.0.1", 4242))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.post(chemin)


async def test_le_rappel_rend_503_et_non_500():
    r = await _appeler("/v1/atoms/recall")
    assert r.status_code == 503
    assert r.headers["content-type"].startswith("application/json")


async def test_la_reponse_enseigne():
    """Ce qui manque, POURQUOI, et LE GESTE — les trois, ou ce n'est pas une
    réponse, c'est une excuse."""
    corps = (await _appeler("/v1/atoms/recall")).json()
    assert corps["manque"] == "OPENAI_API_KEY"
    assert "embeddings" in corps["detail"]
    assert "vecteur" in corps["pourquoi"]
    # Le geste est une commande exacte, copiable telle quelle.
    assert corps["geste"].startswith("sudo ./bootstrap/bootstrap.sh")
    # Et il ne renvoie pas vers un fichier que le bootstrap n'écrit pas.
    assert "$ARAC_HOME/.env" not in corps["verifier"]
    assert corps["verifier"].startswith("sudo grep -c '^OPENAI_API_KEY=' /etc/arac/")


async def test_l_ecriture_dit_que_rien_n_a_ete_ecrit():
    """Un utilisateur dont l'écriture échoue veut savoir si son souvenir est
    perdu. Il ne l'est pas : rien n'a été inséré. On le dit."""
    corps = (await _appeler("/v1/atoms")).json()
    assert "Rien n'a été écrit" in corps["detail"]


def test_le_mode_declare_est_cite(monkeypatch):
    monkeypatch.setenv("ARAC_MODE_DEGRADE", "embeddings,curation")
    corps = errors.corps_embeddings_indisponibles(path="/v1/atoms/recall")
    assert "ARAC_MODE_DEGRADE=embeddings,curation" in corps["pourquoi"]


def test_sans_mode_declare_on_ne_l_invente_pas(monkeypatch):
    """Clé absente SANS mode dégradé déclaré : ce n'est plus un choix, c'est
    un oubli de configuration. La phrase doit changer."""
    monkeypatch.delenv("ARAC_MODE_DEGRADE", raising=False)
    corps = errors.corps_embeddings_indisponibles(path="/v1/atoms/recall")
    assert "ARAC_MODE_DEGRADE=" not in corps["pourquoi"]
    assert "OPENAI_API_KEY manque" in corps["pourquoi"]


def test_le_chemin_du_fichier_env_suit_la_base(monkeypatch):
    monkeypatch.setenv("ARAC_DB", "cerveau_de_test")
    corps = errors.corps_embeddings_indisponibles()
    assert "/etc/arac/cerveau_de_test/arac.env" in corps["verifier"]


# ---------------------------------------------------------------------------
# Le filet : une erreur IMPRÉVUE ne sort plus en texte brut non plus
# ---------------------------------------------------------------------------


def test_le_filet_est_branche_sur_l_application():
    assert Exception in main.app.exception_handlers


def test_l_erreur_inattendue_donne_de_quoi_la_retrouver():
    corps = errors.corps_erreur_inattendue("abc-123")
    assert corps["request_id"] == "abc-123"
    assert "abc-123" in corps["geste"]
    assert "journalctl" in corps["geste"]


def test_l_erreur_inattendue_ne_divulgue_rien():
    """Le détail d'une exception peut porter un DSN, une clé, un souvenir.
    Il reste dans le journal ; ce qui sort est l'identifiant, rien d'autre."""
    corps = errors.corps_erreur_inattendue("abc-123")
    assert set(corps) == {"detail", "pourquoi", "request_id", "geste"}
    assert "Traceback" not in corps["detail"]
