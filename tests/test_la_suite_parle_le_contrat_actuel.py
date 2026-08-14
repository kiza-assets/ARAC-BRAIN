"""LA SUITE PARLE-T-ELLE LE CONTRAT D'AUJOURD'HUI, OU CELUI D'HIER ?

CE QUI S'EST PASSÉ
==================
`app/auth.py` exige désormais le jeton porteur de TOUTE requête, `127.0.0.1`
compris ; seul `/healthz` est public. Un test qui affirmait l'inverse a été
retourné (`tests/test_dashboard_ingest.py`), et il se déclarait lui-même le
canari de ce durcissement.

Il n'était pas seul, et le reste était plus gros que lui. **Cent six** tests
de cette suite appellent une route `/v1/…` par la fixture `client` et
attendent 200, sans porter le moindre en-tête `Authorization`. Ils affirment
donc, tous, le contrat d'AVANT. Personne ne l'a vu, et la raison est
mécanique : ils exigent une base, donc ils sont `skipped` dans `make test`.

UN CONTRAT INVERSÉ SOUS DES TESTS ENDORMIS REND EXACTEMENT LE MÊME VERT
QU'UN CONTRAT RESPECTÉ. C'est la leçon du canari, à l'échelle de la suite.

CE QUE CE FICHIER GARDE
=======================
1. la fixture `client` porte un jeton — comme les onze appelants du produit,
   qui passent tous par `app/api_token.py` ;
2. et ce jeton OUVRE réellement la porte : la requête traverse le middleware.

Le second point se prouve SANS BASE, et c'est ce qui rend ce garde utile :
le middleware décide avant toute connexion. Un client nu se fait refuser en
401 ; le client de la suite, lui, n'est plus refusé — il échoue plus loin,
faute de base, ce qui est un tout autre problème et un tout autre message.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app import auth, main
from tests.conftest import JETON_DE_TEST


#: Une route de LECTURE, représentative des 106 : elle n'écrit rien, elle
#: n'ingère rien, et elle n'existe que derrière la porte.
ROUTE = "/v1/dashboard/scopes_summary"


@pytest.fixture
def _un_seul_poste(monkeypatch):
    for cle in list(auth.os.environ):
        if cle.startswith(auth._ENV_PREFIX):
            monkeypatch.delenv(cle, raising=False)
    monkeypatch.setenv("ARAC_NODE_TOKEN_POSTE_DE_TEST", JETON_DE_TEST)
    monkeypatch.delenv(auth._TRUST_LOOPBACK_VAR, raising=False)
    monkeypatch.delenv(auth._TRUST_LOOPBACK_RAISON_VAR, raising=False)
    auth._tokens_cache = None
    yield
    auth._tokens_cache = None


async def test_un_client_nu_est_refuse_par_la_porte(_un_seul_poste):
    """La prémisse. Sans elle, le test suivant ne prouverait rien."""
    async with AsyncClient(
        transport=ASGITransport(app=main.app), base_url="http://test"
    ) as c:
        r = await c.get(ROUTE)
    assert r.status_code == 401, (
        "La porte s'est rouverte : une lecture sans jeton devrait rendre 401. "
        f"Rendu : {r.status_code}"
    )


async def test_le_jeton_de_la_suite_ouvre_la_porte(_un_seul_poste):
    """Le jeton de la fixture `client` traverse le middleware.

    On ne va pas plus loin : la route veut une base, et cette suite est
    hermétique. Ce qui est mesuré ici est exactement ce qui manquait aux 106
    tests — être ADMIS. Ce qu'ils font ensuite est leur affaire, et elle
    dépend d'une base.
    """
    async with AsyncClient(
        transport=ASGITransport(app=main.app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {JETON_DE_TEST}"},
    ) as c:
        try:
            r = await c.get(ROUTE)
        except Exception:
            # La route a été atteinte et a buté sur l'absence de base : c'est
            # précisément la preuve qu'on cherchait — le refus d'auth, lui,
            # n'aurait jamais levé, il aurait rendu 401.
            return
    assert r.status_code != 401, (
        "Le jeton de la fixture `client` ne passe pas la porte. Les 106 tests "
        "qui l'utilisent affirmeraient donc encore le contrat d'avant — et ils "
        "sont tous `skipped` dans make test, donc personne ne le verrait."
    )


def test_la_fixture_client_porte_un_en_tete_autorisation():
    """Le jeton est déclaré à UN endroit, et il y est encore.

    Une fixture partagée qui perd son en-tête ne casse rien tout de suite :
    elle rend 401 sur 106 tests qui, eux, sont endormis. On le vérifie donc
    ici, dans un test qui, lui, ne dort jamais.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parent / "conftest.py").read_text(encoding="utf-8")
    debut = source.find("async def client(")
    assert debut > 0, "la fixture `client` a disparu du conftest"
    corps = source[debut:debut + 2500]
    assert "Authorization" in corps and "JETON_DE_TEST" in corps, (
        "La fixture `client` ne porte plus de jeton. Sous le contrat actuel, "
        "elle ne parle plus à l'API : elle se fait refuser par le middleware."
    )
