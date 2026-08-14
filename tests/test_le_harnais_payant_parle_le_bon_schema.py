"""CE QUE `make acceptance --complet` ENVOIE DOIT ÊTRE ACCEPTÉ PAR L'API.

POURQUOI CE GARDE EXISTE
========================
L'étape 6 en mode `--complet` est la seule du harnais qui DÉPENSE de l'argent
réel : elle pose une clé d'embeddings, crée un atome par la vraie route, puis
prétend prouver le rappel par similarité. Le rapport recommande explicitement
de la relancer « avec une clé ».

Elle envoyait `{"query": …, "limit": 5}`. Le corps que la route accepte est
`RecallRequest`, qui déclare `k` — pas `limit` — et dont le `model_config`
porte `extra="forbid"`. Un champ inconnu ne fait donc pas « ignorer le
champ » : il fait rendre **422 avant toute recherche**. L'étape ne pouvait
pas prouver ce qu'elle annonçait, et elle ne le découvrait qu'APRÈS avoir
payé l'embedding.

C'est le pire défaut qu'un harnais d'acceptation puisse avoir : il coûte de
l'argent et il rend un verdict qui ne mesure rien.

CE QUE CE FICHIER MESURE, ET COMMENT
=====================================
Il lit `tests/acceptance/acceptance.sh`, en extrait CHAQUE corps JSON envoyé
par `curl --data '…'` avec l'URL de la route visée, et le fait valider par le
schéma Pydantic que cette route déclare. Aucune API n'est appelée, aucune
base n'est ouverte, rien n'est dépensé : on confronte deux fichiers du dépôt.

C'est une prémisse MÉCANIQUE, pas une relecture. Le jour où quelqu'un
renomme un champ de schéma, ce test rougit — au lieu que ce soit une
installation d'acceptation payante qui le découvre.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.atom import AtomCreate, RecallRequest

RACINE = Path(__file__).resolve().parent.parent
HARNAIS = RACINE / "tests" / "acceptance" / "acceptance.sh"

#: L'URL visée -> le schéma qui décide. On ne nomme ici que les routes dont le
#: harnais construit le corps LITTÉRALEMENT ; celles dont il fabrique le corps
#: en Python sont couvertes par les tests de schéma ordinaires.
SCHEMA_DE_LA_ROUTE = {
    "/v1/atoms/recall": RecallRequest,
    "/v1/atoms/recall_fresh": RecallRequest,
    "/v1/atoms": AtomCreate,
}

#: `curl … --data '<json>' … "<url>"` — le corps et l'URL sont sur des lignes
#: différentes. On lit donc l'invocation entière, continuations comprises.
_CURL = re.compile(
    r"curl\b(?P<corps>(?:[^\n]*\\\n)*[^\n]*)", re.MULTILINE
)
_DATA = re.compile(r"--data(?:-raw)?\s+'(?P<json>\{.*?\})'", re.DOTALL)
_URL = re.compile(r"\$URL_API(?P<chemin>/[\w/]*)")


def _invocations() -> list[tuple[str, str]]:
    """(chemin de la route, corps JSON littéral) pour chaque curl du harnais."""
    texte = HARNAIS.read_text(encoding="utf-8")
    trouve: list[tuple[str, str]] = []
    for m in _CURL.finditer(texte):
        bloc = m.group("corps")
        d = _DATA.search(bloc)
        u = _URL.search(bloc)
        if d and u:
            trouve.append((u.group("chemin"), d.group("json")))
    return trouve


def test_le_harnais_existe_et_appelle_l_api() -> None:
    """Sans cette prémisse, un vert ne voudrait rien dire."""
    assert HARNAIS.is_file(), f"{HARNAIS} introuvable"
    assert _invocations(), (
        "Aucun corps JSON littéral trouvé dans le harnais d'acceptation. Soit "
        "l'extraction est cassée, soit le harnais a changé de forme — dans les "
        "deux cas, ce garde ne garde plus rien."
    )


def test_chaque_corps_envoye_est_accepte_par_le_schema_de_sa_route() -> None:
    """LE GARDE. Un corps refusé = une étape payante qui ne prouve rien."""
    refuses: list[str] = []
    for chemin, corps in _invocations():
        schema = SCHEMA_DE_LA_ROUTE.get(chemin)
        if schema is None:
            continue
        try:
            donnees = json.loads(corps)
        except json.JSONDecodeError as exc:
            refuses.append(f"{chemin} : corps illisible ({exc}) — {corps[:120]}")
            continue
        try:
            schema.model_validate(donnees)
        except ValidationError as exc:
            champs = ", ".join(
                ".".join(str(p) for p in e["loc"]) + f" ({e['type']})"
                for e in exc.errors()
            )
            refuses.append(
                f"{chemin} : {schema.__name__} REFUSE ce corps → {champs}\n"
                f"    envoyé : {corps[:160]}"
            )
    assert not refuses, (
        "\n\nLe harnais d'acceptation envoie des corps que l'API REFUSE.\n\n"
        "Ces appels rendent 422 sans rien mesurer — et l'étape 6 en mode\n"
        "`--complet` les fait APRÈS avoir payé un embedding. Une dépense qui\n"
        "n'achète pas de preuve est le seul défaut qu'un harnais\n"
        "d'acceptation n'a pas le droit d'avoir.\n\n"
        + "\n".join(f"  · {r}" for r in refuses)
    )


@pytest.mark.parametrize(
    ("corps", "attendu"),
    [
        ({"query": "q", "k": 5}, True),
        ({"query": "q"}, True),
        ({"query": "q", "limit": 5}, False),      # LE DÉFAUT, épinglé
        ({"k": 5}, False),
    ],
)
def test_le_schema_de_rappel_refuse_bien_ce_qu_on_croit(corps: dict, attendu: bool) -> None:
    """La prémisse du garde : `extra="forbid"` refuse VRAIMENT `limit`.

    Sans ce test, le garde ci-dessus pourrait être vert parce que le schéma
    accepte tout — et personne ne le saurait.
    """
    try:
        RecallRequest.model_validate(corps)
        accepte = True
    except ValidationError:
        accepte = False
    assert accepte is attendu, f"RecallRequest sur {corps} : attendu {attendu}"


def test_le_mode_payant_capture_le_code_http() -> None:
    """Une dépense sans code HTTP n'est pas une preuve, c'est une facture.

    Un `grep` sur le corps d'une réponse échoue de la même façon quand la
    requête a été REFUSÉE (422) et quand le rappel n'a rien ramené (200 et
    liste vide). Deux causes très différentes, un seul message : c'est ainsi
    qu'un défaut de schéma a survécu à une étape qui coûte de l'argent.
    """
    texte = HARNAIS.read_text(encoding="utf-8")
    debut = texte.find("_etape_6_mode_complet()")
    assert debut > 0, "l'étape 6 en mode complet a disparu du harnais"
    bloc = texte[debut:debut + 6000]
    appels = bloc.count("curl -s -m 60")
    portent_le_code = bloc.count("%{http_code}")
    assert portent_le_code >= 2 and portent_le_code >= appels - 1, (
        "Les appels payants de l'étape 6 doivent capturer leur code HTTP "
        f"(-w '%{{http_code}}'). Vus : {appels} appels, {portent_le_code} "
        "capturent le code."
    )
