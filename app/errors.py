"""ARAC — les réponses d'erreur qui enseignent.

POURQUOI CE FICHIER EXISTE
--------------------------
Le bootstrap propose explicitement d'installer SANS clé d'embeddings, pour
voir la chaîne d'ingestion fonctionner avant d'engager la moindre dépense.
Dans cet état, le premier geste d'un nouvel utilisateur — demander au cerveau
ce qu'il sait — rendait :

    HTTP/1.1 500 Internal Server Error
    content-type: text/plain
    Internal Server Error

Vingt et un octets. Ni JSON, ni cause, ni geste. Une exception non capturée
remontée jusqu'à la couche ASGI. L'utilisateur venait de suivre la
documentation à la lettre et découvrait un serveur qui casse : la conclusion
naturelle est « ce projet ne marche pas », alors que l'installation est saine
et que seule une clé, volontairement non posée, manque.

Une erreur attendue n'a pas le droit de ressembler à un plantage. Elle doit
dire, dans cet ordre : CE QUI MANQUE, POURQUOI, et LE GESTE.

CHOIX DU CODE : 503, pas 500 et pas 424
---------------------------------------
500 dit « j'ai un bogue » — faux, et cela ferait ouvrir une issue.
503 dit « ce service est temporairement indisponible » — exact : il le
redeviendra dès que la clé sera posée, sans rien changer au code. Le corps
nomme la dépendance manquante, ce qu'un 424 ne ferait pas mieux tout en étant
beaucoup moins connu des clients.

CE HANDLER EST GLOBAL, ET C'EST VOULU
-------------------------------------
`embed()` est appelée depuis sept endroits (rappel, rappel filtré, contexte
thématique, vérification d'intention, création d'atome, révision d'atome,
clôture de session). Un try/except dans le seul `/recall` aurait laissé six
routes rendre la 500 nue. On traite donc la cause là où elle est reconnaissable
— le type de l'exception — et non route par route.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.context import request_id_var
from app.services.embeddings import EmbeddingsIndisponibles


_logger = logging.getLogger("arac.api")

# Le nom de la base sert à écrire le chemin EXACT du fichier d'environnement.
# Le bootstrap écrit /etc/arac/<base>/arac.env — surtout pas $ARAC_HOME/.env,
# qu'aucune installation ne pose et qui a déjà envoyé chercher au mauvais
# endroit.
_ETC = "/etc/arac"


def _fichier_env() -> str:
    base = os.environ.get("ARAC_DB", "").strip()
    return f"{_ETC}/{base}/arac.env" if base else f"{_ETC}/<votre-base>/arac.env"


# Les chemins qui LISENT la mémoire. Les autres l'ÉCRIVENT : ce n'est pas la
# même déception, donc pas la même phrase. Un utilisateur qui n'a pas pu écrire
# veut savoir si son souvenir est perdu (il ne l'est pas : rien n'a été inséré).
_CHEMINS_DE_RAPPEL = ("/recall", "/recall_fresh", "/context_for", "/resume")


def corps_embeddings_indisponibles(
    exc: Exception | None = None, path: str | None = None
) -> dict:
    """Le corps JSON du 503. Fonction pure : testable sans serveur."""
    degrade = os.environ.get("ARAC_MODE_DEGRADE", "").strip()
    lecture = path is None or path.endswith(_CHEMINS_DE_RAPPEL)
    return {
        "detail": (
            "Rappel indisponible : ce cerveau tourne sans clé d'embeddings."
            if lecture
            else (
                "Écriture impossible : un souvenir a besoin de son vecteur, et "
                "ce cerveau tourne sans clé d'embeddings. Rien n'a été écrit."
            )
        ),
        "pourquoi": (
            "Ce cerveau cherche et range par SENS, pas par mots-clés : chaque "
            "question comme chaque souvenir devient un vecteur, et c'est la "
            "distance entre ces vecteurs qui fait le rappel. Sans clé "
            "d'embeddings, ce vecteur ne peut pas être calculé. L'ingestion, "
            "elle, continue de fonctionner : vos conversations sont bien "
            "collectées et conservées, et deviendront des souvenirs "
            "rappelables le jour où la clé sera posée — rien n'est perdu."
            + (
                f" Ce mode est déclaré dans votre installation "
                f"(ARAC_MODE_DEGRADE={degrade})."
                if degrade
                else " Aucun mode dégradé n'est pourtant déclaré : "
                "OPENAI_API_KEY manque à l'environnement du service."
            )
        ),
        "geste": "sudo ./bootstrap/bootstrap.sh --only cles",
        "verifier": f"sudo grep -c '^OPENAI_API_KEY=' {_fichier_env()}",
        "manque": "OPENAI_API_KEY",
        "cause": str(exc) if exc else None,
    }


def corps_erreur_inattendue(request_id: str | None) -> dict:
    """Le corps JSON d'une 500. Il ne dit RIEN de l'erreur — et c'est voulu.

    Le détail d'une exception peut contenir un DSN, une clé, un fragment de
    souvenir. Ce qui sort, c'est de quoi le retrouver : l'identifiant de la
    requête.

    CE QUE CETTE DOCSTRING DISAIT, ET QUI ÉTAIT FAUX. Elle disait : « Il reste
    dans le journal du serveur, QUI EST PROTÉGÉ », et le corps servi à l'écran
    ajoutait : « Il est ENTIER dans le journal du service. » Les deux phrases
    étaient fausses, et de deux manières différentes.

      1. Le journal n'est pas protégé. `journald` appartient à la MACHINE, pas
         au cerveau : lisible par `root` et par tout compte du groupe
         `systemd-journal`, conservé des semaines, et que la désinstallation ne
         sait pas purger unité par unité. La base, elle, est protégée par des
         rôles et un coffre en `0700`. Promettre « protégé » pour l'un en
         pensant à l'autre, c'est inviter un lecteur à y déposer ce qu'il n'y
         déposerait pas s'il savait.
      2. Le détail n'y est plus entier — et c'est le correctif, pas un aveu.
         `app/journal.py` empreinte le message de chaque exception avant que la
         trace ne parte : les CADRES restent (fichier, ligne, fonction), la
         CLASSE reste, le DIAGNOSTIC PostgreSQL reste (sqlstate, contrainte,
         table, colonne — ils viennent du schéma), le MESSAGE devient
         `sha8:…/n`. Ce module ne peut donc plus promettre au lecteur une
         chose que le processus ne fait plus.

    MESURÉ, avant correction, sur un cerveau vivant : un `POST /v1/atoms`
    heurtant une contrainte NOT NULL rendait ce corps-ci ET déposait dans
    journald, trois fois, « DETAIL:  Failing row contains (…, perso/sante,
    temoin-…, <LE SOUVENIR EN CLAIR>, …) ». La phrase servie à l'écran était
    donc exacte au mot près sur le mécanisme — et c'est ce mécanisme-là qui
    était le défaut.

    Ce que ça remplace : `Internal Server Error`, vingt et un octets de texte
    brut, sans identifiant — un lecteur ne pouvait même pas relier ce qu'il
    venait de voir à une ligne du journal.
    """
    return {
        "detail": "Erreur inattendue du serveur. Rien n'a été écrit dans la mémoire.",
        "pourquoi": (
            "Le détail n'est pas exposé ici, et il n'est pas non plus recopié "
            "en clair dans le journal : le journal systemd appartient à la "
            "machine, pas à votre cerveau, et la désinstallation ne sait pas "
            "l'effacer. Le journal garde de quoi dépanner — l'identifiant de "
            "cette requête, la trace, la classe de l'erreur, le diagnostic "
            "PostgreSQL — et l'empreinte du message, jamais le message."
        ),
        "request_id": request_id,
        "geste": (
            "sudo journalctl -u arac-<votre-base>-api.service -n 50 --no-pager"
            + (f" | grep {request_id}" if request_id else "")
        ),
    }


async def _handler_erreur_inattendue(request: Request, exc: Exception) -> JSONResponse:
    # Starlette relance l'exception après ce handler : le journal garde la
    # trace complète. On ne perd donc rien en rendant une réponse propre.
    #
    # On lit le MÊME identifiant que celui des lignes `request.received` /
    # `request.failed` (ContextVar posée par le middleware de journalisation),
    # sans quoi le `grep` proposé ne trouverait rien.
    rid = request_id_var.get() or request.headers.get("X-Request-ID")
    return JSONResponse(status_code=500, content=corps_erreur_inattendue(rid))


async def _handler_embeddings_indisponibles(
    request: Request, exc: EmbeddingsIndisponibles
) -> JSONResponse:
    _logger.warning(
        "embeddings.indisponible",
        extra={
            "event": "degraded",
            "path": request.url.path,
            "mode_degrade": os.environ.get("ARAC_MODE_DEGRADE", ""),
        },
    )
    return JSONResponse(
        status_code=503,
        content=corps_embeddings_indisponibles(exc, path=request.url.path),
    )


def enregistrer_handlers(app: FastAPI) -> None:
    """Branche les handlers sur l'application. Appelé une fois, dans main.py."""
    app.add_exception_handler(
        EmbeddingsIndisponibles, _handler_embeddings_indisponibles
    )
    # Le filet : une erreur qu'on n'avait pas prévue reste une erreur, mais
    # elle sort en JSON avec de quoi la retrouver, jamais en texte brut.
    app.add_exception_handler(Exception, _handler_erreur_inattendue)
