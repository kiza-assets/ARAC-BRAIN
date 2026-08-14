"""La constitution : plafond de coût, chargement, empreinte servie.

Ce que ces tests protègent, et pourquoi :

1. **Le plafond de jetons.** La constitution est injectée à CHAQUE session.
   Chaque phrase ajoutée est payée à chaque connexion, pour toujours. Le gate
   à 3000 jetons cl100k n'est pas une préférence esthétique : c'est la limite
   au-delà de laquelle le texte cesse d'être lu et devient un coût fixe. On ne
   relève pas ce plafond — on refactore dans les atomes « pierre angulaire »,
   qui eux sont lus à la demande.

2. **La surcharge fonctionne.** Un utilisateur qui écrit sa propre
   `config/constitution.md` doit voir SON texte servi, pas celui du dépôt.

3. **L'empreinte est cohérente.** Elle est ce qui permet, des mois plus tard,
   de savoir sous quelles règles un atome a été écrit. Si elle mentait, elle
   serait pire qu'absente.
"""

from __future__ import annotations

import hashlib
import os

import pytest
import tiktoken

from app import constitution

_needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL_ADMIN"),
    reason="DB reelle requise",
)

#: Plafond DUR. Au-delà, on refactore le texte, on ne relève pas la borne.
_CONSTITUTION_TOKEN_CEILING = 3000


def test_constitution_tokens_under_ceiling():
    """Le texte par défaut tient sous le plafond — sinon il coûte à chaque session."""
    enc = tiktoken.get_encoding("cl100k_base")
    n = len(enc.encode(constitution.DEFAULT_CONSTITUTION))
    assert n < _CONSTITUTION_TOKEN_CEILING, (
        f"La constitution fait {n} jetons cl100k, au-dessus du plafond dur "
        f"({_CONSTITUTION_TOKEN_CEILING}). Elle est relue à chaque session : "
        "déplacez le détail dans un atome « pierre angulaire », lu à la "
        "demande, plutôt que de relever le plafond."
    )


def test_constitution_default_is_complete():
    """Sept articles, tous présents. Un article manquant est une règle qui
    cesse silencieusement de s'appliquer."""
    text = constitution.text()
    assert isinstance(text, str) and text
    for n in range(1, 8):
        assert f"ARTICLE {n}" in text, f"article {n} absent de la constitution"


def test_constitution_is_overridable(tmp_path, monkeypatch):
    """La constitution de l'utilisateur REMPLACE celle du dépôt.

    C'est la différence entre un framework et un logiciel : les règles sous
    lesquelles votre cerveau opère vous appartiennent.
    """
    mine = tmp_path / "constitution.md"
    mine.write_text("# ARTICLE 1 — mes propres regles\n", encoding="utf-8")
    monkeypatch.setenv("ARAC_CONSTITUTION_FILE", str(mine))

    assert constitution.text() == "# ARTICLE 1 — mes propres regles\n"
    assert constitution.sha256() == hashlib.sha256(
        constitution.text().encode("utf-8")
    ).hexdigest()
    assert constitution.char_count() == len(constitution.text())


def test_constitution_falls_back_when_override_missing(tmp_path, monkeypatch):
    """Un fichier de surcharge absent ne casse rien : on retombe sur le défaut.

    Un cerveau sans constitution serait un cerveau sans règles — on préfère
    des règles héritées à pas de règles du tout."""
    monkeypatch.setenv("ARAC_CONSTITUTION_FILE", str(tmp_path / "absent.md"))
    assert constitution.text() == constitution.DEFAULT_CONSTITUTION


def test_constitution_sha_matches_text():
    """L'empreinte est bien celle du texte servi, pas d'un autre."""
    assert constitution.sha256() == hashlib.sha256(
        constitution.text().encode("utf-8")
    ).hexdigest()
    assert len(constitution.sha256()) == 64
    assert all(c in "0123456789abcdef" for c in constitution.sha256())


@_needs_db
async def test_constitution_hash_endpoint(client):
    """GET /v1/constitution/hash sert l'empreinte du texte réellement chargé."""
    r = await client.get("/v1/constitution/hash")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"sha256", "chars"}
    assert body["sha256"] == constitution.sha256()
    assert body["chars"] == constitution.char_count()
