"""Le jeton porteur : il est exigé, TOUJOURS. (app/auth.py)

Ce fichier existe parce que deux épreuves adversariales indépendantes ont lu un
souvenir privé et écrit un faux souvenir dans la mémoire d'un cerveau, depuis
le compte `nobody`, sans présenter le moindre secret — sur le seul chemin que
la documentation décrivait : la boucle locale.

L'exemption de boucle locale a d'abord été rendue explicite (elle ne
s'appliquait qu'à l'adresse RÉELLE du pair TCP, et se désarmait à la main).
Ce n'était pas assez : elle restait ARMÉE par défaut, donc héritée par toute
installation, donc jamais relue. Elle est maintenant DÉSARMÉE par défaut.

Ce que ce fichier garde, dans l'ordre d'importance :
  1. sans rien poser, le jeton est exigé — y compris sur 127.0.0.1 ;
  2. le desserrage exige DEUX variables, dont un motif écrit : un desserrage
     muet n'est pas appliqué ;
  3. une valeur inconnue ou mal orthographiée laisse la porte FERMÉE ;
  4. l'adresse qui décide reste celle du pair TCP, jamais un en-tête ;
  5. les refus ENSEIGNENT : ce qui manque, pourquoi, et où est le jeton.

Hermétique : ni base, ni réseau, ni clé.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app import auth


JETON = "f" * 64
NODE = "poste-de-test"


@pytest.fixture(autouse=True)
def _environnement_propre(monkeypatch):
    """Un seul poste déclaré, cache d'auth vidé entre les tests."""
    for cle in list(auth.os.environ):
        if cle.startswith(auth._ENV_PREFIX):
            monkeypatch.delenv(cle, raising=False)
    monkeypatch.setenv("ARAC_NODE_TOKEN_POSTE_DE_TEST", JETON)
    monkeypatch.delenv(auth._TRUST_LOOPBACK_VAR, raising=False)
    monkeypatch.delenv(auth._TRUST_LOOPBACK_RAISON_VAR, raising=False)
    auth._tokens_cache = None
    yield
    auth._tokens_cache = None


def _app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _auth(request, call_next):
        return await auth.bearer_middleware(request, call_next)

    @app.get("/healthz")
    async def _sante():
        return {"ok": True}

    @app.post("/v1/ingest/messages")
    async def _ingest(request: Request):
        return {"ecrit": True, "node": getattr(request.state, "auth_node_id", None)}

    return app


def _client(hote: str = "127.0.0.1") -> AsyncClient:
    """Un client dont le PAIR TCP est `hote` — c'est ce que voit le noyau."""
    return AsyncClient(
        transport=ASGITransport(app=_app(), client=(hote, 4242)),
        base_url="http://test",
    )


# ---------------------------------------------------------------------------
# La règle, en table de vérité (fonction pure : aucune I/O)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "hote", "proxy", "confiance", "attendu"),
    [
        # /healthz est public en toute circonstance : c'est une sonde.
        ("/healthz", "203.0.113.9", True, True, False),
        # Le régime DESSERRÉ, et lui seul : desserrage écrit ET motivé.
        ("/v1/ingest/messages", "127.0.0.1", False, True, False),
        ("/v1/ingest/messages", "::1", False, True, False),
        ("/v1/ingest/messages", "::ffff:127.0.0.1", False, True, False),
        # Le défaut corrigé : hors de la boucle locale, omettre un en-tête de
        # proxy ne desserre rien — l'adresse du pair TCP décide seule.
        ("/v1/ingest/messages", "203.0.113.9", False, True, True),
        ("/v1/ingest/messages", "10.0.0.4", False, True, True),
        # Un en-tête de proxy ne peut qu'AJOUTER de l'exigence, jamais en ôter.
        ("/v1/ingest/messages", "127.0.0.1", True, True, True),
        # Exemption désarmée : le jeton est exigé même sur la boucle locale.
        ("/v1/ingest/messages", "127.0.0.1", False, False, True),
        # En cas de doute sur l'origine (socket UNIX, client absent), on exige.
        ("/v1/ingest/messages", None, False, True, True),
        ("/v1/ingest/messages", "testclient", False, True, True),
    ],
)
def test_regle_bearer(path, hote, proxy, confiance, attendu):
    assert (
        auth.bearer_requis(
            path=path,
            hote_pair=hote,
            entetes_proxy_presents=proxy,
            confiance_loopback=confiance,
        )
        is attendu
    )


@pytest.mark.parametrize(
    ("valeur", "motif", "attendu"),
    [
        # LE DÉFAUT. C'est la ligne qui compte le plus de tout ce fichier :
        # rien de posé = jeton exigé, y compris en boucle locale.
        (None, None, False),
        # Desserrage écrit ET motivé : accordé, et lui seul.
        ("1", "2026-08-08 — banc de mesure", True),
        ("true", "idem", True),
        ("oui", "idem", True),
        ("on", "idem", True),
        # Desserrage écrit SANS motif : REFUSÉ. Une exception qu'on ne peut
        # pas relire est celle qu'on oublie — c'est l'histoire de ce défaut.
        ("1", None, False),
        ("1", "", False),
        ("1", "   ", False),
        # Fermetures explicites : fermées, motif ou pas.
        ("0", None, False),
        ("false", "peu importe", False),
        ("non", None, False),
        ("off", None, False),
        ("", None, False),
        # LA COQUILLE. Sous l'ancienne règle, on énumérait ce qui FERME, donc
        # « oui_mais » (hors liste) OUVRAIT. Maintenant on énumère ce qui
        # OUVRE : la même coquille FERME. Une liste d'exceptions se trompe
        # toujours du côté de son défaut ; ce côté-ci est le bon.
        ("oui_mais", "un motif pourtant écrit", False),
        ("2", "un motif pourtant écrit", False),
        ("O", "un motif pourtant écrit", False),
    ],
)
def test_drapeau_de_confiance(monkeypatch, valeur, motif, attendu):
    for var, v in ((auth._TRUST_LOOPBACK_VAR, valeur),
                   (auth._TRUST_LOOPBACK_RAISON_VAR, motif)):
        if v is None:
            monkeypatch.delenv(var, raising=False)
        else:
            monkeypatch.setenv(var, v)
    assert auth.loopback_de_confiance() is attendu


def test_le_desserrage_muet_est_dit_et_non_applique(monkeypatch):
    """Refuser en silence serait aussi mauvais qu'accepter : on NOMME l'état."""
    monkeypatch.setenv(auth._TRUST_LOOPBACK_VAR, "1")
    monkeypatch.delenv(auth._TRUST_LOOPBACK_RAISON_VAR, raising=False)
    desserre, etat = auth.etat_du_desserrage()
    assert desserre is False
    assert auth._TRUST_LOOPBACK_VAR in etat
    assert auth._TRUST_LOOPBACK_RAISON_VAR in etat


def test_le_motif_voyage_avec_l_etat(monkeypatch):
    """`verify_install.sh` et les journaux doivent pouvoir le RECOPIER."""
    monkeypatch.setenv(auth._TRUST_LOOPBACK_VAR, "1")
    monkeypatch.setenv(auth._TRUST_LOOPBACK_RAISON_VAR, "2026-08-08 — ticket #412")
    desserre, etat = auth.etat_du_desserrage()
    assert desserre is True
    assert etat == "2026-08-08 — ticket #412"


# ---------------------------------------------------------------------------
# La même chose, de bout en bout, à travers le middleware réel
# ---------------------------------------------------------------------------


async def test_la_porte_de_la_boucle_locale_est_fermee_par_defaut():
    """LE TEST DE CETTE MANCHE. Sans rien poser, 127.0.0.1 doit être REFUSÉ.

    C'est la reproduction exacte, en hermétique, de ce que deux épreuves
    adversariales ont fait depuis le compte `nobody` : un POST d'ingestion sur
    la boucle locale, sans un seul secret. Il rendait 202 et écrivait un faux
    souvenir. Il doit rendre 401.
    """
    async with _client("127.0.0.1") as c:
        r = await c.post("/v1/ingest/messages", json={})
    assert r.status_code == 401, "la boucle locale est redevenue une exemption"
    assert r.headers["WWW-Authenticate"] == "Bearer"


async def test_la_lecture_aussi_est_fermee_par_defaut():
    """L'autre moitié de la fuite : LIRE la mémoire du voisin, pas seulement y écrire."""
    async with _client("127.0.0.1") as c:
        r = await c.get("/v1/dashboard/search")
    assert r.status_code == 401


async def test_le_jeton_ouvre_la_boucle_locale():
    """L'autre moitié de la preuve : le produit doit CONTINUER de marcher.

    Fermer la porte sans ce test, c'est n'avoir prouvé que la moitié qui
    n'intéresse personne. Le pont, le cycle, le cockpit et les agents portent
    tous ce jeton-là.
    """
    async with _client("127.0.0.1") as c:
        r = await c.post(
            "/v1/ingest/messages", json={}, headers={"Authorization": f"Bearer {JETON}"}
        )
    assert r.status_code == 200
    assert r.json()["node"] == NODE


async def test_le_refus_par_defaut_enseigne():
    """Un 401 nu coûte une soirée. Celui-ci dit quoi, pourquoi, et OÙ."""
    async with _client("127.0.0.1") as c:
        r = await c.post("/v1/ingest/messages", json={})
    corps = r.json()
    assert {"detail", "pourquoi", "ou_est_le_jeton", "geste", "desserrer"} <= set(corps)
    # POURQUOI : la vraie raison, pas la règle générale.
    assert "127.0.0.1" in corps["pourquoi"]
    assert "compte" in corps["pourquoi"]
    # OÙ : un chemin, pas une invitation à deviner.
    assert corps["ou_est_le_jeton"].endswith("arac.env")
    # LE GESTE : exécutable tel quel.
    assert "grep" in corps["geste"] and "Bearer" in corps["geste"]
    # ET COMMENT DESSERRER, puisque c'est la question suivante.
    assert auth._TRUST_LOOPBACK_RAISON_VAR in corps["desserrer"]


async def test_le_refus_nomme_le_coffre_de_CE_cerveau(monkeypatch):
    """« /etc/arac/<votre-base>/arac.env » oblige à deviner ; deviner, sur une
    machine à deux cerveaux, c'est aller regarder chez le voisin."""
    monkeypatch.setenv("ARAC_DB", "camille_brain")
    monkeypatch.delenv("ARAC_ENV_FILE", raising=False)
    async with _client("127.0.0.1") as c:
        r = await c.post("/v1/ingest/messages", json={})
    assert r.json()["ou_est_le_jeton"] == "/etc/arac/camille_brain/arac.env"


async def test_le_desserrage_muet_refuse_et_le_dit():
    """Poser le drapeau sans motif ne rouvre rien — et le refus l'explique."""
    import os

    os.environ[auth._TRUST_LOOPBACK_VAR] = "1"
    try:
        async with _client("127.0.0.1") as c:
            r = await c.post("/v1/ingest/messages", json={})
    finally:
        os.environ.pop(auth._TRUST_LOOPBACK_VAR, None)
    assert r.status_code == 401
    assert "motif écrit" in r.json()["pourquoi"]


async def test_le_desserrage_motive_rouvre_la_boucle_locale(monkeypatch):
    """Il reste POSSIBLE : quelqu'un peut avoir une raison, et elle est écrite."""
    monkeypatch.setenv(auth._TRUST_LOOPBACK_VAR, "1")
    monkeypatch.setenv(auth._TRUST_LOOPBACK_RAISON_VAR, "2026-08-08 — banc de mesure")
    async with _client("127.0.0.1") as c:
        r = await c.post("/v1/ingest/messages", json={})
    assert r.status_code == 200


async def test_adresse_distante_sans_jeton_refusee():
    """Le trou : omettre X-Forwarded-For rendait ceci ACCEPTÉ. Plus maintenant."""
    async with _client("203.0.113.9") as c:
        r = await c.post("/v1/ingest/messages", json={})
    assert r.status_code == 401
    corps = r.json()
    # Un refus doit enseigner : ce qui manque, pourquoi, et le geste.
    assert "pourquoi" in corps and "geste" in corps
    assert "203.0.113.9" in corps["pourquoi"]


async def test_entete_de_proxy_exige_le_jeton_meme_en_boucle_locale():
    """Un reverse proxy tourne sur la même machine : le pair EST loopback.

    Sans cette règle, installer nginx devant l'API supprimerait l'authentification
    de tout l'Internet d'un coup.
    """
    async with _client("127.0.0.1") as c:
        r = await c.post(
            "/v1/ingest/messages", json={}, headers={"X-Forwarded-For": "203.0.113.9"}
        )
    assert r.status_code == 401


async def test_drapeau_desarme_exige_le_jeton_en_boucle_locale(monkeypatch):
    """La fermeture explicite tient aussi — elle est simplement redondante."""
    monkeypatch.setenv(auth._TRUST_LOOPBACK_VAR, "0")
    async with _client("127.0.0.1") as c:
        refus = await c.post("/v1/ingest/messages", json={})
        accepte = await c.post(
            "/v1/ingest/messages", json={}, headers={"Authorization": f"Bearer {JETON}"}
        )
    assert refus.status_code == 401
    assert refus.headers["WWW-Authenticate"] == "Bearer"
    assert accepte.status_code == 200
    assert accepte.json()["node"] == NODE


async def test_jeton_inconnu_refuse_et_explique(monkeypatch):
    monkeypatch.setenv(auth._TRUST_LOOPBACK_VAR, "0")
    async with _client("127.0.0.1") as c:
        r = await c.post(
            "/v1/ingest/messages", json={}, headers={"Authorization": "Bearer " + "a" * 64}
        )
    assert r.status_code == 401
    assert "geste" in r.json()


async def test_healthz_reste_public_meme_desarme(monkeypatch):
    monkeypatch.setenv(auth._TRUST_LOOPBACK_VAR, "0")
    async with _client("203.0.113.9") as c:
        r = await c.get("/healthz")
    assert r.status_code == 200


async def test_healthz_reste_public_par_defaut():
    """La sonde de monitoring ne porte pas de jeton — et ne lit rien.

    C'est la seule exemption qui reste, et elle est de CHEMIN, pas d'origine :
    elle vaut pour tout le monde, ce qui la rend relisible.
    """
    async with _client("127.0.0.1") as c:
        r = await c.get("/healthz")
    assert r.status_code == 200
