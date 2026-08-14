"""Tests d'intégration API dashboard — endpoint Ingest Health (v0.5 Bloc I6).

Cible : `GET /v1/dashboard/ingest_stats` (extension de `app/routers/dashboard.py`).

Stratégie (alignée test_dashboard.py / conftest) :
- Utilise les fixtures `client` + `initialized_pool` du conftest → init pool DB,
  cleanup `key LIKE 'test-%'` avant + après chaque test.
- Read-only : on ne POST/PATCH/DELETE jamais via /v1/dashboard/*. Les
  données sont insérées directement par l'admin DSN (raw_conversations
  n'a pas d'endpoint POST côté dashboard — c'est attendu).
- Skip si DATABASE_URL_APP/ADMIN absent (conftest skip + module skip ici).

Squelette I6 (1-2 tests). Le pack complet T1..T7 est livré par I8 :
- T1 schema 200 + JSON valide IngestStats (ici en stub) — exige une BDD.
- T2 la porte : SANS jeton, l'endpoint rend 401, `127.0.0.1` compris.
- Les autres tests (DB vide, fixtures, ratios, last_successful_ingest,
  archived_ratio) sont laissés à I8 (cf D4 §6).

CE QUE T2 DISAIT, ET POURQUOI IL A ÉTÉ RETOURNÉ
==============================================
T2 s'appelait `test_ingest_stats_accessible_without_bearer` et affirmait
« sans header Authorization -> 200 (loopback OK) ». Sa docstring ajoutait :
« si une vague future durcit l'auth dashboard, ce test deviendra le canari ».
La vague est arrivée — `app/auth.py` exige le jeton de TOUTE requête depuis le
2026-08-08 — et le canari n'a rien dit : il était `SKIPPED`, faute de
`DATABASE_URL_APP/ADMIN`, et `make test` restait vert.

D'où la seconde correction, qui compte plus que la première : **un canari ne
doit pas dépendre d'une base.** T2 n'en a jamais eu besoin — le middleware
refuse AVANT d'atteindre la route, donc avant toute connexion. Le `skipif` de
base ne couvre donc plus que T1, qui, lui, lit vraiment des données.

Convention test : aucun atome créé ici (les compteurs M7 peuvent retourner
ce qui existe déjà en DB partagée — on vérifie la *forme* de la réponse,
pas les valeurs absolues).
"""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app import main


#: T1 lit des données : il lui faut une base. T2, non — et c'est le but.
#: Un `pytestmark` de module aurait remis le canari à dormir.
_exige_une_base = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL_ADMIN"),
    reason="DATABASE_URL_APP/ADMIN absent — tests dashboard nécessitent BDD réelle",
)


# ============================================================================
# T1 — GET /v1/dashboard/ingest_stats retourne JSON valide IngestStats
# ============================================================================


@_exige_une_base
async def test_ingest_stats_returns_valid_schema(client):
    """GET /ingest_stats → 200 + JSON conforme schema IngestStats.

    Vérifie la *forme* de la réponse (clés présentes, types corrects),
    pas les valeurs absolues — la DB partagée peut contenir des données
    arbitraires d'autres tests. Les tests de valeur (T2..T7) sont I8.
    """
    r = await client.get("/v1/dashboard/ingest_stats")
    assert r.status_code == 200, r.text
    body = r.json()

    # Champs top-level présents (Pydantic schema IngestStats).
    assert isinstance(body, dict)
    for key in (
        "period_days",
        "daily",
        "ratio_atoms_per_message",
        "last_successful_ingest",
        "failed_bundles_7d",
        "archived_by_curator_30d",
        "created_by_curator_30d",
        "archived_ratio",
    ):
        assert key in body, f"clé manquante: {key}"

    # period_days = 7 (constante côté router, série journalière 7j).
    assert body["period_days"] == 7
    assert isinstance(body["daily"], list)
    # generate_series 7j inclusif → exactement 7 entrées (continuité, pas de gap).
    assert len(body["daily"]) == 7

    # Chaque point quotidien a la bonne forme (IngestDailyPoint).
    for point in body["daily"]:
        assert set(point.keys()) >= {
            "date",
            "bundles_received",
            "messages_total",
            "atoms_generated",
        }
        assert isinstance(point["date"], str)              # 'YYYY-MM-DD'
        assert isinstance(point["bundles_received"], int)
        assert isinstance(point["messages_total"], int)
        assert isinstance(point["atoms_generated"], int)

    # Counters : int ≥ 0.
    assert isinstance(body["failed_bundles_7d"], int) and body["failed_bundles_7d"] >= 0
    assert isinstance(body["archived_by_curator_30d"], int) and body["archived_by_curator_30d"] >= 0
    assert isinstance(body["created_by_curator_30d"], int) and body["created_by_curator_30d"] >= 0

    # Ratios : float | None — None si dénominateur = 0 (anti-fabulation).
    assert body["ratio_atoms_per_message"] is None or isinstance(
        body["ratio_atoms_per_message"], (int, float)
    )
    assert body["archived_ratio"] is None or isinstance(
        body["archived_ratio"], (int, float)
    )

    # last_successful_ingest : str ISO datetime | None.
    assert body["last_successful_ingest"] is None or isinstance(
        body["last_successful_ingest"], str
    )


# ============================================================================
# T2 — LE CANARI : sans jeton, la porte refuse — 127.0.0.1 compris
# ============================================================================


async def test_ingest_stats_refuse_sans_jeton():
    """GET /ingest_stats sans en-tête Authorization → 401, depuis 127.0.0.1.

    Ce test affirmait exactement l'inverse (« 200, loopback OK ») et se
    déclarait lui-même le canari du durcissement à venir. Le durcissement est
    arrivé — `app/auth.py`, 2026-08-08 : le jeton est exigé de toute requête,
    la boucle locale n'est plus une exception, seul `/healthz` est public — et
    le canari n'a pas chanté, parce qu'il dormait derrière un `skipif` de base.

    Il ne dort plus : **aucune base n'est ouverte ici**. Le middleware refuse
    avant d'atteindre la route, donc avant la moindre connexion. C'est ce qui
    fait de ce test un canari plutôt qu'une intention.

    L'adresse du pair est celle que pose `ASGITransport` : `127.0.0.1`. Le
    refus vient donc bien de la règle, pas d'une origine étrangère.
    """
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/v1/dashboard/ingest_stats")
    assert r.status_code == 401, r.text
    corps = r.json()
    # Le refus ENSEIGNE : il dit ce qui manque, pourquoi, et où est le jeton.
    for champ in ("detail", "pourquoi", "ou_est_le_jeton", "geste"):
        assert champ in corps, f"le 401 ne porte pas « {champ} » : {corps}"
