"""Control Center v1 — routes de NAVIGATION (le maillage cliquable).

Ce module est le **maillage** du cockpit : il transforme des chiffres en objets
que l'on peut ouvrir. Depuis une métrique on atteint une conversation, depuis une
conversation ses atomes, depuis un atome ses voisins, ses projets, ses rappels.

Doctrine, identique au socle (``routes.py``) :
  - ``@a.get`` uniquement — aucun verbe mutant, aucune écriture ;
  - garde de session (``session_api``) sur chaque route ;
  - journal de lecture (``audit_read_log``) sur chaque accès ;
  - handlers **synchrones** (``def``) : FastAPI les exécute en threadpool, la
    boucle d'événements n'est jamais bloquée par l'I/O PostgreSQL.

Principe cardinal appliqué sans exception :

    « Le cerveau produit les métriques. Chaque chiffre doit être traçable
      jusqu'à sa source. »

Conséquences dans ce fichier :
  - **toute l'arithmétique est en SQL** (pourcentages, rangs ``row_number()``,
    moyennes, comptes, distances ``<=>``). Python n'additionne rien, ne divise
    rien, ne trie rien ; il transporte des lignes ;
  - **toute réponse porte son ``evidence``** : le SQL RÉELLEMENT exécuté, avec
    ses paramètres déjà substitués (``ClientCursor.mogrify``), normalisé sur une
    ligne. On copie, on colle dans ``psql``, on obtient les mêmes lignes. Un
    cockpit qui ne peut pas être contredit ne mérite pas d'être cru ;
  - **une absence n'est jamais un zéro** : ``null`` + un champ qui dit pourquoi ;
  - une entité introuvable rend ``{"state": "unavailable", "reason": …}``,
    jamais une exception 500.

Dépendance non lue : ``arac.atom_links``. Le maillon « Reliée » et le bloc
``links`` sont ``unavailable``, mais leur raison est **constatée**, jamais
supposée — ``links_dependency()`` interroge le catalogue et distingue « la table
n'est pas là » (il manque une migration) de « la table est là mais ce panneau ne
la lit pas » (il manque une lecture). Envoyer relancer une migration déjà passée
est aussi trompeur que taire l'absence. Le substitut utilisable aujourd'hui
reste le voisinage sémantique.

Routes exposées :

  GET /cc/v1/conversations           la file, ses facettes, la chaîne de vie
  GET /cc/v1/conversations/{uid}     une conversation : ce qu'elle a produit
  GET /cc/v1/atoms                   les atomes, 9 vues, facettes
  GET /cc/v1/atoms/{id}              un atome : contenu, lignée, voisins, usage
  GET /cc/v1/scopes                  l'arbre des scopes et sa dette
  GET /cc/v1/projects                les projets déclarés (des VUES, pas des dossiers)
  GET /cc/v1/projects/{id}           la fiche d'un projet
"""

from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse

import re as _re_journal

from app.journal import empreinte, raison, reduire, sha8

#: La forme d'un `where` littéral : « scope.neighbours », « atom.links ».
_BLOC_LITTERAL = _re_journal.compile(r"^[A-Za-z0-9_.\- ]+$")
from control_center.cc_v1 import service
from control_center.cc_v1.metric import lire_sql
from control_center.cc_v1.projects import NO_PROJECTS_NOTE, load_projects, union_ou_vide

__all__ = [
    "register",
    "PROJECTS",
    "union_ou_vide",
    "ATOM_VIEWS",
    "conversations_list",
    "conversation_detail",
    "atoms_list",
    "atom_detail",
    "scopes_list",
    "projects_list",
    "project_detail",
]

logger = logging.getLogger("arac.cc.v1.entities")

_PREFIX = "/cc/v1"

#: Plafond dur de pagination. Aucune route ne peut ramener davantage : une page
#: qui déborde n'est plus lisible, et une requête sans borne n'est plus sûre.
MAX_LIMIT = 200
_DEFAULT_LIMIT = 50

#: Bornes des listes secondaires d'une fiche (atomes d'une conversation, rejets,
#: passages, décisions d'un projet…). Une fiche reste une fiche.
_DETAIL_LIMIT = 100
_NEIGHBOURS = 8

#: Borne par bloc d'une fiche projet (décisions, pièges, états, références).
#: Chaque bloc a SA borne : une borne globale affamerait les blocs suivants.
_PER_KIND = 25

#: Motif ``LIKE`` du séparateur de scope. Passé en **paramètre** et jamais écrit
#: dans le corps du SQL : psycopg réserve ``%`` au marquage des paramètres, et un
#: ``LIKE '%/%'` littéral casserait la liaison.
_SLASH = "%/%"

#: UN RAPPEL, UNE LIGNE — le prédicat qui dédoublonne ``arac.context_receipts``.
#: Il s'applique à un reçu aliasé ``cr`` et se colle dans une clause ``WHERE``.
#:
#: POURQUOI. Depuis FOLD V2, chaque rappel réel écrit DEUX lignes : le moteur
#: SERVI (``ce-shadow-r3pur-v1``) puis le moteur d'ombre ``v2-fold``, avec le MÊME
#: ``request_id``, le MÊME horodatage et les MÊMES ``served_ids``
#: (``app/routers/atoms.py`` appelle ``run_shadow_v2`` juste après ``run_shadow``).
#: Mesuré le 2026-08-05 : 3 340 lignes pour 1 709 rappels, dont 1 631 paires
#: strictement identiques quant à ce qui a été servi.
#:
#: Compter les lignes, c'était donc annoncer le DOUBLE partout où le cockpit
#: chiffre le dernier maillon de la chaîne : rappels d'un scope, « fois servi »
#: d'un atome, événements « rappel » d'une chronologie.
#:
#: On retient le PREMIER reçu écrit — le chemin SERVI, « vérité de référence »
#: selon le commentaire de colonne — plutôt qu'un filtre sur ``engine_version`` :
#: cela reste juste le jour où un moteur v3 écrira un troisième reçu. Vérifié en
#: base : le premier reçu de chacun des 1 709 ``request_id`` est bien un v1.
#: PostgreSQL en fait un anti-join haché (~2 ms sur 3 340 lignes).
#:
#: Commentaire de BLOC et jamais ``--`` : ces requêtes sont servies APLATIES sur
#: une ligne (règle 9), un commentaire de ligne masquerait tout ce qui suit.
UN_RECU_PAR_RAPPEL = """AND NOT EXISTS (
           /* un rappel = un request_id ; le premier recu ecrit est le chemin servi */
           SELECT 1 FROM arac.context_receipts p
            WHERE p.request_id = cr.request_id AND p.id < cr.id)"""

#: La table des liens explicites entre atomes, et la sonde qui la CONSTATE.
#:
#: `to_regclass` interroge le catalogue et rend NULL quand la relation n'existe
#: pas, sans jamais lever : c'est la seule façon de parler de cette table sans
#: la toucher.
LINKS_TABLE: str = "arac.atom_links"
LINKS_PROBE_SQL: str = "SELECT to_regclass('arac.atom_links') IS NOT NULL AS deployee"

#: La SECONDE sonde, tirée seulement quand la première a répondu « oui ».
#:
#: POURQUOI DEUX REQUÊTES ET NON UN ``CASE``
#: -----------------------------------------
#: PostgreSQL analyse la requête entière avant de l'exécuter : un
#: ``FROM arac.atom_links`` fait échouer la requête quand la table manque, y
#: compris dans la branche d'un ``CASE`` qui ne l'atteint jamais. Regarder le
#: contenu exige donc d'avoir d'abord constaté la présence — deux aller-retours,
#: et c'est le prix de l'honnêteté.
#:
#: ``EXISTS`` et non ``count(*)`` : la question est « y a-t-il un lien ? », pas
#: « combien » ; l'index suffit, et le cockpit ne balaie pas une table qui peut
#: devenir grande pour afficher une phrase.
LINKS_CONTENT_SQL: str = "SELECT EXISTS (SELECT 1 FROM arac.atom_links) AS peuplee"

#: Ce que le cockpit dit de la couche de liens QUAND IL N'A PAS PU REGARDER.
#:
#: POURQUOI CE TEXTE N'AFFIRME PLUS RIEN
#: -------------------------------------
#: Il affirmait « la table arac.atom_links n'existe pas (migration 0033 non
#: appliquée) », sans condition, dans une constante servie telle quelle sur une
#: dizaine de panneaux. C'était l'état d'UNE base — celle sur laquelle le
#: cockpit a été écrit — gravé dans le code et resservi à tout le monde.
#:
#: Or ce dépôt LIVRE cette couche : la migration qui crée `arac.atom_links`
#: FAIT PARTIE de la chaîne qu'`alembic upgrade head` applique (le raisonnement
#: n'a besoin que de cela ; dire « elle en est la tête » serait un rang, et un
#: rang périme à la migration suivante — c'est déjà arrivé),
#: `app/services/atom_links.py` calcule les arêtes, et le cycle cortex appelle
#: son recalcul à chaque tour. Chez qui a suivi l'installation, la table EST là
#: — et le cockpit lui affirmait le contraire à chaque écran.
#:
#: Une affirmation sur l'état d'une base ne peut venir que d'un regard porté sur
#: cette base : c'est le rôle de `links_dependency()` ci-dessous. Cette constante
#: n'est plus que le repli du cas « je n'ai pas pu regarder », et elle dit
#: exactement cela.
LINKS_UNAVAILABLE: dict[str, str] = {
    "state": "unavailable",
    "reason": ("l'état de la couche de liens explicites n'a pas pu être "
               "constaté : le schéma n'a pas été interrogé"),
    "gesture": "vérifiez que le cockpit peut lire le schéma en lecture seule",
    "substitute": "voisinage sémantique",
}

#: Ce que le cockpit dit quand il a regardé et que la table N'EST PAS LÀ.
LINKS_ABSENT: dict[str, str] = {
    "state": "unavailable",
    "reason": ("la table arac.atom_links est absente du schéma : la couche de "
               "liens explicites n'est pas déployée"),
    "gesture": "appliquez les migrations en attente : alembic upgrade head",
    "substitute": "voisinage sémantique",
}

#: Ce que le cockpit dit quand il a regardé, que la table est là, et qu'elle
#: est VIDE.
#:
#: Ce cas-là existe vraiment et il fallait le distinguer : le dépôt livre bien
#: un producteur — ``app/services/atom_links.py`` calcule les arêtes et
#: ``agents/cortex/cycle.py`` appelle leur recalcul à chaque tour, avant le
#: garde-dépense, donc même quand l'IA payante est coupée — mais un cerveau qui
#: vient de naître n'a pas encore vu passer un cycle. Lui dire « ce panneau ne
#: lit pas » serait exact et inutile : ce qui lui manque, c'est un tour de
#: digestion, pas une lecture.
LINKS_EMPTY: dict[str, str] = {
    "state": "unavailable",
    "reason": ("la table arac.atom_links est déployée mais ne porte aucune "
               "arête : aucun recalcul de liens n'a encore abouti sur cette base"),
    "gesture": ("attendez le prochain cycle de digestion, ou lancez-en un : le "
                "recalcul des liens tourne à chaque tour, avant le garde-dépense"),
    "substitute": "voisinage sémantique",
}

#: Ce que le cockpit dit quand il a regardé, que la table est là, et qu'elle
#: PORTE des arêtes.
#:
#: L'indisponibilité change alors de nature, et elle doit le dire : ce n'est ni
#: le substrat ni le producteur qui manque, c'est CE panneau qui ne lit pas
#: encore ce qui existe. Confondre ces cas enverrait le lecteur relancer une
#: migration déjà passée, ou brancher un agent qui tourne déjà trois fois par
#: jour.
LINKS_NOT_READ: dict[str, str] = {
    "state": "unavailable",
    "reason": ("la table arac.atom_links est déployée et porte des arêtes, mais "
               "ce panneau ne lit pas encore son contenu"),
    "gesture": ("consultez les liens par la vue de voisinage ; ce panneau reste "
                "à brancher sur arac.atom_links"),
    "substitute": "voisinage sémantique",
}

#: Les trois textes qu'une SONDE produit — et qu'aucun d'eux n'a le droit
#: d'être servi autrement.
#:
#: Ils affirment l'état de la base du lecteur : « absente », « déployée »,
#: « aucune arête ». Cette affirmation n'est licite que parce qu'elle descend
#: d'un regard. Le tuple est le contrat, et les tests s'en servent : y figurer
#: signifie « produit après avoir regardé », et l'inverse — servir ces textes
#: sans sonder — est une faute qu'un test attrape.
TEXTES_CONSTATES: tuple[dict[str, str], ...] = (
    LINKS_ABSENT, LINKS_EMPTY, LINKS_NOT_READ,
)


def links_dependency(conn: Any = None) -> dict[str, str]:
    """L'état CONSTATÉ de la couche de liens explicites entre atomes.

    Quatre réponses, et elles ne se confondent pas — parce que les gestes
    qu'elles appellent sont quatre gestes différents :

    - le schéma n'a pas pu être lu  → le cockpit ne sait pas, et le dit ;
    - la table est absente          → il manque une migration ;
    - la table est là, sans arête   → il manque un passage du cycle ;
    - la table est là, avec arêtes  → il manque une LECTURE, pas un déploiement.

    Les deux derniers cas sont ceux que la manche précédente confondait, et
    c'est le plus coûteux des deux : dire « alimentez la table » à qui a déjà
    un producteur qui tourne trois fois par jour, c'est l'envoyer chercher
    quelque chose qui existe.

    Ne lève jamais : un échec de connexion retombe sur ``LINKS_UNAVAILABLE``,
    le seul des quatre textes qui n'affirme rien sur la base. Un panneau ne
    doit pas tomber parce qu'il a voulu être honnête.

    Args:
        conn: connexion déjà ouverte à réutiliser. Sinon une connexion en
              lecture seule est ouverte et refermée pour la seule sonde.
    """
    own = conn is None
    try:
        c = service._connect_readonly() if own else conn
        try:
            with c.cursor() as cur:
                cur.execute(LINKS_PROBE_SQL)
                row = cur.fetchone()
                if not (row and row[0]):
                    return dict(LINKS_ABSENT)
                # On ne lit le contenu qu'APRÈS avoir constaté la présence :
                # cf. LINKS_CONTENT_SQL, un CASE ne suffirait pas.
                cur.execute(LINKS_CONTENT_SQL)
                contenu = cur.fetchone()
        finally:
            if own:
                c.close()
    except Exception:  # noqa: BLE001 — ne pas savoir n'est pas une panne de page
        return dict(LINKS_UNAVAILABLE)
    return dict(LINKS_NOT_READ if (contenu and contenu[0]) else LINKS_EMPTY)


# ============================================================================
# Garde lecture seule — même contrat que registry._assert_read_only
# ============================================================================

FORBIDDEN_SQL: tuple[str, ...] = (
    "insert", "update", "delete", "truncate", "drop", "alter", "create",
    "grant", "revoke", "copy", "vacuum", "refresh", "call", "do",
)
"""Mots-clés interdits en position d'instruction. Troisième couche de défense,
après le rôle ``arac_readonly`` et ``default_transaction_read_only=on``."""

_WORD = re.compile(r"[a-z_]+")


def _assert_read_only(sql: str, where: str) -> None:
    """Lève ``ValueError`` si le SQL contient une instruction mutante.

    LE GARDE JUGE CE QUI S'EXÉCUTE, PAS CE QUI SE LIT. ``metric.lire_sql``
    parcourt la requête comme l'analyseur le ferait et écarte d'abord les
    littéraux **et** les commentaires : un mot dans une chaîne est de la
    donnée, un mot dans un commentaire n'est rien du tout. Le contrôle porte
    sur le **gabarit**, pas sur la requête liée — sans quoi une recherche de
    l'utilisateur contenant « update » condamnerait sa propre requête.

    CE QUE CETTE VERSION RÉPARE. La précédente cherchait ``--`` dans une chaîne
    dont seuls les littéraux avaient été retirés. La requête des conversations
    porte, DANS un commentaire de bloc, une phrase française contenant « -- » :
    le garde refusait donc la requête du produit lui-même, et les deux routes
    des conversations rendaient ``state: unavailable`` sur toute installation,
    en HTTP 200. Un ``--`` à l'intérieur d'un ``/* … */`` ne commente rien —
    c'est ``*/`` qui referme le bloc, l'aplatissement de la preuve n'y change
    rien.
    """
    corps, commentaire_de_ligne, bloc_non_ferme = lire_sql(sql)
    hit = set(_WORD.findall(corps)) & set(FORBIDDEN_SQL)
    if hit:
        raise ValueError(f"{where}: instruction mutante interdite : {sorted(hit)}")
    # Un commentaire `--` survit à l'exécution mais PAS à la mise sur une ligne :
    # il y avalerait tout ce qui suit, et la preuve publiée deviendrait
    # injouable. Une preuve qu'on ne peut pas rejouer n'est pas une preuve.
    if commentaire_de_ligne:
        raise ValueError(f"{where}: commentaire SQL '--' interdit (casse la preuve sur une ligne)")
    if bloc_non_ferme:
        raise ValueError(f"{where}: commentaire de bloc '/*' jamais refermé (la fin de la requête serait avalée)")


# ============================================================================
# Exécution — une connexion read-only, des lignes, et le SQL rejouable
# ============================================================================


@contextmanager
def _readonly() -> Iterator[Any]:
    """Une connexion read-only, refermée quoi qu'il arrive."""
    conn = service._connect_readonly()
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001 — fermer ne doit jamais masquer l'erreur utile
            pass


def _client_cursor(conn: Any) -> Any:
    """Curseur à liaison **côté client** : le SQL envoyé est celui qu'on affiche.

    C'est ce qui rend la preuve honnête. Avec une liaison côté serveur, on ne
    pourrait montrer qu'un gabarit à trous — donc quelque chose que le lecteur ne
    peut pas rejouer, donc une preuve qui n'en est pas une.
    """
    import psycopg

    return psycopg.ClientCursor(conn)


def _sql_text(conn: Any, sql: str, params: dict[str, Any] | None) -> str:
    """La requête réellement exécutée, paramètres substitués, sur une ligne."""
    try:
        rendered = _client_cursor(conn).mogrify(sql, params) if params else sql
    except Exception:  # noqa: BLE001 — une preuve dégradée vaut mieux qu'une panne
        rendered = sql
    return " ".join(rendered.split())


def _rows(conn: Any, sql: str, params: dict[str, Any] | None = None,
          *, where: str = "requête") -> list[dict[str, Any]]:
    """Exécute et retourne des lignes JSON-ables. Aucun calcul n'est fait ici.

    ``params`` vide vaut ``None`` : sans paramètre, psycopg n'interprète plus
    ``%`` — c'est ce qui rend une preuve **rejouable telle quelle**, motifs
    ``LIKE '%/%'`` compris.
    """
    _assert_read_only(sql, where)
    with _client_cursor(conn) as cur:
        cur.execute(sql, params if params else None)
        cols = [d.name for d in (cur.description or [])]
        raw = cur.fetchall()
    return [{c: service._jsonable(v) for c, v in zip(cols, r)} for r in raw]


def _one(conn: Any, sql: str, params: dict[str, Any] | None = None,
         *, where: str = "requête") -> dict[str, Any] | None:
    rows = _rows(conn, sql, params, where=where)
    return rows[0] if rows else None


def _bounded(limit: Any, default: int = _DEFAULT_LIMIT) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(n, MAX_LIMIT))


def _clean(v: Any) -> str | None:
    """Une chaîne vide n'est pas un filtre : c'est l'absence de filtre."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _like(v: Any) -> str | None:
    s = _clean(v)
    return f"%{s}%" if s else None


def _unavailable(reason: str, **extra: Any) -> dict[str, Any]:
    return {"state": "unavailable", "reason": reason, "computed_at": service._now(), **extra}



def _where_pour_journal(where: object) -> str:
    """« bloc:valeur » -> « bloc:sha8:… » — le bloc reste, la valeur s'efface.

    Même règle, au caractère près, que ``cycle._errors_pour_journal`` : le code
    de ce qui a échoué dit quoi corriger, la valeur ne le dit pas et peut être
    un domaine, un identifiant de conversation ou une clé d'atome. Fermé par
    défaut : sans « : », la chaîne entière est traitée comme une valeur, SAUF
    si elle ne porte que des caractères d'un identifiant de bloc (lettres,
    chiffres, point, tiret bas, tiret) — la forme des ``where`` littéraux de ce
    fichier, dont on peut lire dans le source qu'ils ne portent rien.
    """
    texte = "" if where is None else str(where)
    bloc, sep, valeur = texte.partition(":")
    if not sep:
        return texte if _BLOC_LITTERAL.match(texte) else empreinte(texte)
    return f"{bloc}:{empreinte(valeur)}"


def _failure(where: str, exc: Exception) -> dict[str, Any]:
    """Une panne se dit ; elle ne se déguise pas en résultat vide.

    LE MESSAGE EST AUTOPORTEUR, `extra=` NE L'EST PAS. Aucun formateur n'est
    configuré dans ce service (ni ``basicConfig``, ni ``dictConfig``, ni
    ``log_config``) : uvicorn applique son format par défaut, ``%(message)s``.
    Tout ce qui était rangé dans ``extra=`` n'était donc JAMAIS rendu — les 16
    pannes réelles du 2026-08-05 se lisaient, en tout et pour tout,
    « cc_v1.entities_failed » : sans route, sans type d'exception, sans message,
    donc indiagnosticables.

    Le contexte passe désormais par les arguments du message, et ``exc_info``
    ajoute la trace. ``extra=`` reste rempli pour le jour où un formateur
    structuré sera posé — il n'est plus la SEULE copie de l'information.

    GARDE-FOU — ET IL ÉTAIT FAUX SUR SES DEUX MOITIÉS. Cette docstring disait
    « on journalise ``where`` (route + bloc) […] jamais la valeur d'un atome »
    et « le message d'exception PostgreSQL cite au pire une colonne ». MESURÉ
    sur un cerveau vivant, en révoquant un SELECT pour provoquer une vraie
    panne :

        cc_v1.entities_failed where=scope:perso/sante raison=…

    ``where`` n'est pas « route + bloc » : ses appelants le COMPOSENT avec la
    valeur regardée — ``f"scope:{resolved}"``, ``f"atom:{atom_id}"``,
    ``f"conversation:{uid}"``. Le domaine partait donc en clair dans le journal
    de la machine à chaque panne du cockpit. Et un message PostgreSQL ne cite
    pas « au pire une colonne » : un ``NotNullViolation`` porte
    ``DETAIL:  Failing row contains (…)``, c'est-à-dire la ligne entière.

    LE REMÈDE est celui que ce dépôt s'applique déjà dans
    ``agents/cortex/cycle._errors_pour_journal`` : ce qui précède le premier
    « : » est le BLOC (un littéral de ce fichier, il dit quoi regarder) ; tout
    ce qui suit est une VALEUR, donc empreinte. Et ``raison()`` remplace le
    message de l'exception par sa classe, son SQLSTATE et son empreinte.
    """
    logger.warning("cc_v1.entities_failed where=%s raison=%s",
                   _where_pour_journal(where), raison(exc),
                   extra={"where": _where_pour_journal(where),
                          "error": type(exc).__name__}, exc_info=True)
    # La RÉPONSE, elle, garde le `where` entier : elle part au navigateur du
    # propriétaire, sous session, et c'est SA mémoire. Le journal est un
    # magasin partagé par la machine ; ce n'est pas le même destinataire.
    return _unavailable(f"source indisponible ({raison(exc)})", scope=where)


# ============================================================================
# Les projets — un projet est une VUE, pas un dossier
# ============================================================================
#
# La règle vit en configuration serveur (``config/projects.toml``, chargé par
# ``cc_v1/projects.py``) : elle évolue sans migration, et elle est SERVIE au
# client — jamais recopiée dans le frontend.
#
# `scopes`     : scopes exacts.
# `prefixes`   : sous-arbres, notés « x/* » dans l'interface. La RACINE NUE est
#                incluse : les atomes posés directement sur une racine
#                appartiennent bel et bien au projet — les cacher fabriquerait
#                un trou. Ils sont par ailleurs invisibles au rappel, ce qui est
#                une raison de plus de les montrer plutôt que de les taire.
# `keywords`   : appliqués sur `key` ET sur `tags`. Quand il y en a, ils
#                RESTREIGNENT les scopes (« ces scopes ET ces mots »), sans quoi
#                un chantier précis avalerait tout un scope de vie.
#
# Deux projets peuvent se recouvrir VOLONTAIREMENT. Un atome appartient à
# plusieurs projets ; l'interface l'assume et ne résout jamais l'appartenance.
#
# Aucun projet n'est fourni par le dépôt : ce sont les vôtres, ou aucun. Sans
# ``config/projects.toml``, les routes de projet répondent « aucun projet
# déclaré » — le cockpit préfère se taire plutôt que deviner.

PROJECTS: tuple[dict[str, Any], ...] = load_projects()

_PROJECT_BY_ID = {p["id"]: p for p in PROJECTS}

#: Au-delà, un projet est « en veille » : son dernier atome date. État neutre et
#: informatif — un projet en veille n'est pas un projet malade.
_DORMANT_DAYS = 30


def _project_rule(p: dict[str, Any]) -> dict[str, Any]:
    """La règle, telle qu'elle doit être AFFICHÉE : lisible, pas déduite.

    LA RÈGLE AFFICHÉE EST LA RÈGLE APPLIQUÉE — c'est tout l'objet de cette
    fonction, et c'était précisément ce qu'elle ne faisait pas. Elle n'écrivait
    que ``x/*`` pour chaque préfixe, alors que ``_project_predicate`` matche
    ``scope = x OR scope LIKE x || '/%'`` : la racine NUE en plus des feuilles.
    L'écran publiait donc une règle qui excluait des atomes que le même écran
    comptait : la règle affichée montrait ``['x/*']`` tandis que le décompte
    incluait aussi la racine nue — un écart d'autant plus grand que la dette
    root-level est importante. Les deux branches du prédicat sont maintenant
    rendues, dans l'ordre où il les évalue.
    """
    patterns = list(p["scopes"]) + [m for x in p["prefixes"] for m in (x, f"{x}/*")]
    note = "un atome peut appartenir à plusieurs projets ; le recouvrement est voulu"
    if p["prefixes"]:
        note += (" — la racine nue est citée en plus des feuilles : ses atomes sont "
                 "invisibles au rappel (dette root-level), le projet doit "
                 "néanmoins les compter")
    return {
        "scopes": patterns,
        "keywords": list(p["keywords"]),
        "combination": ("scopes ET mots-clés" if p["keywords"] else "scopes seuls"),
        "note": note,
    }


def provenance_block(atoms_active: Any, sans_conversation: Any,
                     legacy: Any = None) -> dict[str, Any]:
    """Ce que le compte de conversations NE dit pas — écrit UNE fois.

    RÈGLE I2 : un compte de conversations posé à côté d'un compte d'atomes se lit
    comme une causalité (« ces N conversations ont produit ces M atomes »). C'est
    faux partout où la provenance est perdue — et elle se perd : sur le cerveau
    de référence, 76 pour cent des atomes ne portaient plus aucun
    ``conversation_uid`` après un simple changement de format de ``source_ref``.
    L'absence est donc DITE, avec sa raison, son geste et son substitut — jamais
    laissée à la déduction du lecteur, jamais rendue par un zéro.

    Une seule définition, partagée par la fiche de scope et la fiche de projet :
    deux formulations divergeraient, et le cockpit servirait deux vérités.

    Les nombres arrivent tels quels du SQL ; cette fonction choisit la phrase.
    """
    if atoms_active is None or sans_conversation is None:
        return {
            "state": "unavailable",
            "value": None,
            "reason": "la provenance n'a pas pu être comptée",
            "gesture": "rejouer la requête servie dans evidence.queries",
            "substitute": "le compte de conversations, qui reste servi tel quel",
        }
    if not sans_conversation:
        return {
            "state": "ok",
            "atomes_sans_conversation": 0,
            "atomes_provenance_legacy": 0,
            "note": ("tous les atomes actifs portent un conversation_uid : le compte de "
                     "conversations couvre la totalité du savoir affiché"),
        }
    precision = (f" ({legacy} portent une provenance legacy curator_raw_id)"
                 if legacy else "")
    return {
        "state": "unavailable",
        "value": None,
        "atomes_sans_conversation": sans_conversation,
        "atomes_provenance_legacy": legacy,
        "reason": (f"{sans_conversation} des {atoms_active} atomes actifs ne portent pas de "
                   f"conversation_uid{precision} : le compte de conversations ne les couvre pas"),
        # Le geste ne cite plus « 849 des 1 097 » : c'était une mesure d'un jour gravée
        # dans une phrase servie, donc un chiffre qui devient faux tout seul — la faute
        # même que ce cockpit corrige ailleurs. Le nombre d'atomes concernés ICI est
        # servi à côté (`atomes_provenance_legacy`), compté en SQL à l'instant du clic.
        "gesture": ("résoudre curator_raw_id via arac.raw_conversations, dont le source_path "
                    "cite le conversation_uid — la fiche d'un atome le fait déjà, atome "
                    "par atome, et dit par quelle voie le rattachement a été obtenu"),
        "substitute": ("la capture brute d'origine servie sur /cc/v1/atoms/{id}/story : "
                       "node_id, source_path, message_count, statut"),
    }


def _project_predicate(p: dict[str, Any], alias: str, tag: str) -> tuple[str, dict[str, Any]]:
    """Traduit une règle de projet en prédicat SQL paramétré.

    Retourne ``(sql, params)``. Les noms de paramètres sont préfixés par ``tag``
    afin que huit prédicats puissent cohabiter dans une seule requête.
    """
    params: dict[str, Any] = {}
    territory: list[str] = []

    if p["scopes"]:
        params[f"{tag}_scopes"] = list(p["scopes"])
        territory.append(f"{alias}.scope = ANY(%({tag}_scopes)s)")
    for i, prefix in enumerate(p["prefixes"]):
        params[f"{tag}_root{i}"] = prefix
        params[f"{tag}_sub{i}"] = f"{prefix}/%"
        territory.append(
            f"({alias}.scope = %({tag}_root{i})s OR {alias}.scope LIKE %({tag}_sub{i})s)"
        )
    sql = "(" + " OR ".join(territory) + ")" if territory else "false"

    if p["keywords"]:
        params[f"{tag}_kw"] = list(p["keywords"])
        params[f"{tag}_kwlike"] = [f"%{k}%" for k in p["keywords"]]
        sql += (
            f" AND ({alias}.key ILIKE ANY(%({tag}_kwlike)s)"
            f" OR {alias}.tags && %({tag}_kw)s)"
        )
    return f"({sql})", params


# ============================================================================
# CONVERSATIONS — la file, sa chaîne de vie, ses facettes
# ============================================================================
#
# La chaîne de vie compte 6 maillons. Elle est construite EN SQL : ce que
# l'interface dessine est exactement ce que la base affirme, et le lecteur peut
# rejouer la requête pour vérifier chaque pastille.

_CHAIN_SQL = """
        jsonb_build_array(
            jsonb_build_object(
                'link', 1, 'label', 'Détectée',
                'state', CASE WHEN d.uid IS NOT NULL THEN 'done' ELSE 'unavailable' END,
                'reason', CASE WHEN d.uid IS NOT NULL THEN NULL
                               ELSE 'aucun reçu d''ingestion ne porte cet identifiant' END,
                'source', 'arac.ingest_receipts.conversation_uid'),
            jsonb_build_object(
                'link', 2, 'label', 'Absorbée',
                'state', CASE WHEN f.messages > 0 THEN 'done' ELSE 'pending' END,
                'detail', f.messages,
                'source', 'arac.raw_messages'),
            jsonb_build_object(
                'link', 3, 'label', 'Analysée',
                'state', CASE f.status
                              WHEN 'done' THEN 'done'
                              WHEN 'partial' THEN 'partial'
                              WHEN 'excluded' THEN 'skipped'
                              WHEN 'error' THEN 'error'
                              ELSE 'pending' END,
                'detail', f.curated_pct,
                'source', 'arac.conversations.curated_through_message_id'),
            jsonb_build_object(
                'link', 4, 'label', 'Atomisée',
                'state', CASE WHEN z.uid IS NOT NULL THEN 'done'
                              WHEN f.status = 'done' THEN 'empty'
                              ELSE 'pending' END,
                'reason', CASE WHEN z.uid IS NOT NULL THEN NULL
                               WHEN f.status = 'done'
                                   THEN 'analysée sans atome actif retenu'
                               ELSE 'analyse non terminée' END,
                'voie', CASE WHEN z.uid IS NULL THEN NULL
                             WHEN z.declare THEN 'source_ref'
                             ELSE 'legacy_source_path' END,
                'declare', CASE WHEN z.uid IS NULL THEN NULL ELSE z.declare END,
                'atomes_declares', z.atomes_declares,
                'atomes_reconstruits', z.atomes_reconstruits,
                'detail', CASE WHEN z.uid IS NULL OR z.declare THEN NULL
                               ELSE 'lien RECONSTRUIT : aucun atome ne déclare cette '
                                    || 'conversation, le rattachement vient du chemin '
                                    || 'de la capture brute (curator_raw_id -> '
                                    || 'raw_conversations.source_path), résolu sans '
                                    || 'ambiguïté' END,
                'source', CASE WHEN z.uid IS NULL OR z.declare
                                   THEN 'arac.memory_atoms.source_ref'
                               ELSE 'arac.memory_atoms.source_ref->curator_raw_id '
                                    || '-> arac.raw_conversations.source_path' END),
            /* Maillon 5 : l'etat de la couche de liens est CONSTATE ici, dans la
               requete meme qui sert le maillon. Le texte precedent affirmait sans
               condition que la table n'existait pas ; il restait affiche apres la
               migration qui la cree, et envoyait relancer un upgrade deja passe.
               `to_regclass` regarde le catalogue -- c'est la seule facon de le
               dire sans le supposer. */
            jsonb_build_object(
                'link', 5, 'label', 'Reliée',
                'state', 'unavailable',
                'reason', CASE WHEN to_regclass('arac.atom_links') IS NULL
                               THEN 'la table arac.atom_links est absente du schéma : '
                                    || 'la couche de liens explicites n''est pas déployée'
                               ELSE 'la table arac.atom_links est déployée, mais ce '
                                    || 'maillon ne lit pas encore son contenu' END,
                'gesture', CASE WHEN to_regclass('arac.atom_links') IS NULL
                                THEN 'appliquez les migrations en attente : alembic upgrade head'
                                ELSE 'ce maillon reste à brancher sur arac.atom_links' END,
                'substitute', 'voisinage sémantique',
                'source', 'arac.atom_links'),
            jsonb_build_object(
                'link', 6, 'label', 'Retrouvée',
                'state', CASE WHEN r.uid IS NOT NULL THEN 'done'
                              WHEN z.uid IS NOT NULL THEN 'pending'
                              ELSE 'unavailable' END,
                'reason', CASE WHEN r.uid IS NOT NULL THEN NULL
                               WHEN z.uid IS NOT NULL
                                   THEN 'aucun de ses atomes n''a encore été servi'
                               ELSE 'aucun atome à retrouver' END,
                'voie', CASE WHEN r.uid IS NULL THEN NULL
                             WHEN r.declare THEN 'source_ref'
                             ELSE 'legacy_source_path' END,
                'declare', CASE WHEN r.uid IS NULL THEN NULL ELSE r.declare END,
                'source', 'arac.context_receipts.served_ids')
        ) AS chain
"""

def _status_case(conv: str, cursor: str, max_id: str) -> str:
    """LA dérivation du statut d'une conversation, écrite UNE fois.

    Elle est employée par la liste, par la fiche ET par les projets. Si elle
    existait en trois exemplaires, deux écrans pourraient un jour afficher deux
    statuts différents pour la même conversation — et le cockpit cesserait d'être
    opposable. L'ordre est normatif : ``excluded`` → ``error`` → ``done`` →
    ``partial`` → ``pending``.
    """
    return (
        f"CASE WHEN {conv}.exclusion_reason IS NOT NULL THEN 'excluded'"
        f"     WHEN {conv}.last_curation_error IS NOT NULL THEN 'error'"
        f"     WHEN {max_id} IS NOT NULL AND {cursor} >= {max_id} THEN 'done'"
        f"     WHEN {cursor} > 0 THEN 'partial'"
        f"     ELSE 'pending' END"
    )


#: Le statut dérivé, indexé par uid — pour les routes qui parlent des
#: conversations sans en dresser la liste (projets). ``max(m.id)`` est servi par
#: ``idx_rawmsg_conv_id`` : un accès clé, jamais un parcours des 125 900 messages.
_CONV_STATUS_CTE = f"""
conv_status AS (
    SELECT c.conversation_uid AS uid,
           {_status_case('c', 'COALESCE(c.curated_through_message_id, 0)',
                         's.max_message_id')} AS status
      FROM arac.conversations c
      CROSS JOIN LATERAL (
          SELECT max(m.id) AS max_message_id
            FROM arac.raw_messages m
           WHERE m.conversation_id = c.id
      ) s
)
"""

# Le socle commun : une ligne par conversation, ses statistiques de messages,
# son statut dérivé, son pourcentage de curation et son rang de file.
#
# POURQUOI `msg` EST GROUPÉE ET NON LATÉRALE (corrigé 2026-08-05) :
# la forme LATERAL exécutait l'agrégat UNE FOIS PAR CONVERSATION — 365 balayages
# de raw_messages (`Aggregate … loops=365`) pour une page qui n'en rend que 50,
# le LIMIT n'intervenant qu'APRÈS l'agrégat. Coût mesuré : 670 ms pour la requête
# d'items, 497 ms pour celle des facettes, soit 1,10 s de bout en bout sur
# /cc/v1/conversations. Un N+1 non pas en Python mais DANS le SQL.
# La forme groupée ne balaye raw_messages qu'une fois : 65 ms, valeurs
# rigoureusement identiques (365 conversations · 133 389 messages · 108 634 curés,
# mêmes max_message_id, content_date et queue_key).
# `LEFT JOIN` et `COALESCE(..., 0)` dans `base` : la forme LATERAL rendait une
# ligne même pour une conversation SANS message ; un GROUP BY, non. Aujourd'hui
# les 365 conversations ont au moins un message, mais la première conversation
# vide aurait disparu de la liste sans un mot.
#
# L'accès à raw_messages reste indexé (idx_rawmsg_conv_id) ; ce qui change, c'est
# qu'on n'y revient plus une fois par conversation.
_CONV_BASE = f"""
WITH conv AS (
    SELECT c.id,
           c.conversation_uid          AS uid,
           c.title,
           c.source_type,
           c.node_id,
           COALESCE(c.curated_through_message_id, 0) AS cursor_id,
           c.curated_at,
           c.atoms_generated,
           c.last_curation_error,
           c.retry_count,
           c.next_retry_at,
           c.acked,
           c.exclusion_reason,
           c.exclusion_category,
           c.excluded_at,
           c.created_at,
           c.updated_at
      FROM arac.conversations c
),
msg AS (
    SELECT m.conversation_id                                  AS conv_id,
           count(*)                                           AS messages,
           max(m.id)                                          AS max_message_id,
           max(COALESCE(m.msg_created_at, m.received_at))     AS content_date,
           max(m.received_at)                                 AS received_date,
           min(COALESCE(m.msg_created_at, m.received_at))
               FILTER (WHERE m.id > c.cursor_id)              AS queue_key,
           count(*) FILTER (WHERE m.id <= c.cursor_id)        AS curated_messages
      FROM arac.raw_messages m
      JOIN conv c ON c.id = m.conversation_id
     GROUP BY m.conversation_id
),
base AS (
    SELECT c.*, COALESCE(m.messages, 0) AS messages, m.max_message_id,
           m.content_date, m.received_date, m.queue_key,
           COALESCE(m.curated_messages, 0) AS curated_messages,
           {_status_case('c', 'c.cursor_id', 'm.max_message_id')} AS status,
           round(100.0 * m.curated_messages / nullif(m.messages, 0), 1) AS curated_pct
      FROM conv c
      LEFT JOIN msg m ON m.conv_id = c.id
),
queue AS (
    SELECT id,
           row_number() OVER (ORDER BY queue_key ASC NULLS LAST, created_at ASC, id)
               AS queue_rank
      FROM base
     WHERE status IN ('pending', 'partial', 'error')
),
detected AS (
    SELECT DISTINCT conversation_uid AS uid
      FROM arac.ingest_receipts
     WHERE conversation_uid IS NOT NULL
),
/* POURQUOI UNE SECONDE VOIE DE RATTACHEMENT (ajoutée 2026-08-05) :
   la « provenance perdue » était traitée comme une fatalité — 1 097 atomes actifs
   portent un `source_ref` legacy (`curator_raw_id`) sans `conversation_uid`, et
   la chaîne s'arrêtait pour eux au maillon « Analysée ». C'est faux pour plus des
   trois quarts d'entre eux : `curator_raw_id` -> `raw_conversations.source_path`,
   dont le chemin CITE le `conversation_uid`. Mesuré le 2026-08-05 : 1 093 captures
   brutes retrouvées, 849 atomes rattachés à 126 conversations, 0 ambiguïté.
   `strpos(...) > 0` et non `LIKE '.uid.'` : le corps ne doit porter AUCUN signe
   pour-cent, que psycopg réserve au marquage des paramètres (cf. `_SLASH`) et qui
   casserait la liaison ET la preuve rejouable. Équivalence vérifiée : 849 = 849,
   zéro désaccord sur le rattachement atome par atome.
   GARDE D'UNICITÉ : `HAVING count(DISTINCT …) = 1`. Un chemin qui citerait DEUX
   conversations connues ne rattache rien — un lien douteux vaut moins qu'un lien
   absent, et l'écran resterait alors sur son `pending` motivé.
   HONNÊTETÉ : la voie est portée jusqu'à l'affichage (`voie`, `declare`). Un lien
   RECONSTRUIT ne doit jamais être présenté comme un lien DÉCLARÉ. */
atom_conv_legacy AS (
    SELECT atom_id, uid, 'legacy_source_path'::text AS voie
      FROM (
          SELECT a.id                         AS atom_id,
                 min(c.conversation_uid)      AS uid,
                 count(DISTINCT c.conversation_uid) AS n_match
            FROM arac.memory_atoms a
            JOIN arac.raw_conversations rc
                 ON rc.id::text = a.source_ref->>'curator_raw_id'
            JOIN arac.conversations c
                 ON strpos(rc.source_path, c.conversation_uid) > 0
           WHERE a.status = 'active'
             AND NOT (a.source_ref ? 'conversation_uid')
           GROUP BY a.id
      ) r
     WHERE r.n_match = 1
),
atom_conv AS (
    SELECT a.id AS atom_id, a.source_ref->>'conversation_uid' AS uid,
           'source_ref'::text AS voie
      FROM arac.memory_atoms a
     WHERE a.status = 'active' AND a.source_ref ? 'conversation_uid'
    UNION ALL
    SELECT atom_id, uid, voie FROM atom_conv_legacy
),
served AS (
    SELECT DISTINCT s AS atom_id
      FROM arac.context_receipts cr
      CROSS JOIN LATERAL unnest(cr.served_ids) s
),
atomised AS (
    SELECT uid,
           bool_or(voie = 'source_ref')                        AS declare,
           count(*) FILTER (WHERE voie = 'source_ref')         AS atomes_declares,
           count(*) FILTER (WHERE voie = 'legacy_source_path') AS atomes_reconstruits
      FROM atom_conv
     GROUP BY uid
),
recalled AS (
    SELECT ac.uid, bool_or(ac.voie = 'source_ref') AS declare
      FROM atom_conv ac
      JOIN served sv ON sv.atom_id = ac.atom_id
     GROUP BY ac.uid
)
"""

_CONV_ORDER: dict[str, str] = {
    "content_date": "f.content_date DESC NULLS LAST, f.uid",
    "received_date": "f.received_date DESC NULLS LAST, f.uid",
    "messages": "f.messages DESC, f.uid",
    "atoms_generated": "f.atoms_generated DESC NULLS LAST, f.uid",
    "curated_at": "f.curated_at DESC NULLS LAST, f.uid",
    "curated_pct": "f.curated_pct ASC NULLS FIRST, f.uid",
    "queue_rank": "f.queue_rank ASC NULLS LAST, f.uid",
    "title": "f.title ASC NULLS LAST, f.uid",
    "status": "f.status ASC, f.content_date DESC NULLS LAST",
}


def _conv_filters(status: str | None, source: str | None, q: str | None,
                  uid: str | None) -> tuple[dict[str, str], dict[str, Any]]:
    """Les prédicats de filtrage et leurs paramètres, un par dimension."""
    preds: dict[str, str] = {}
    params: dict[str, Any] = {}
    if uid:
        preds["uid"] = "b.uid = %(uid)s"
        params["uid"] = uid
    if q:
        preds["q"] = "(b.title ILIKE %(q)s OR b.uid ILIKE %(q)s)"
        params["q"] = _like(q)
    if status:
        preds["status"] = "b.status = %(status)s"
        params["status"] = status
    if source:
        preds["source"] = "b.source_type = %(source)s"
        params["source"] = source
    return preds, params


def _where(preds: dict[str, str], *, skip: str | None = None) -> str:
    kept = [sql for name, sql in preds.items() if name != skip]
    return ("WHERE " + " AND ".join(kept)) if kept else ""


def conversations_list(limit: int = _DEFAULT_LIMIT, offset: int = 0,
                       status: str | None = None, source: str | None = None,
                       q: str | None = None, order: str = "content_date") -> dict[str, Any]:
    """La file des conversations : où en est chacune, et pourquoi.

    Le statut est dérivé DANS CET ORDRE — ``excluded`` → ``error`` → ``done`` →
    ``partial`` → ``pending``. L'ordre compte : une conversation exclue et en
    erreur est d'abord exclue, sinon l'interface signalerait une panne là où il
    n'y a qu'une décision.
    """
    limit = _bounded(limit)
    offset = max(0, int(offset or 0))
    status, source, q = _clean(status), _clean(source), _clean(q)
    order = order if order in _CONV_ORDER else "content_date"

    preds, params = _conv_filters(status, source, q, None)
    params |= {"limit": limit, "offset": offset}

    items_sql = f"""{_CONV_BASE}
, f AS (
    SELECT b.*, qu.queue_rank
      FROM base b
      LEFT JOIN queue qu ON qu.id = b.id
      {_where(preds)}
)
SELECT f.uid, f.title, f.source_type, f.status, f.messages, f.atoms_generated,
       f.curated_pct, f.content_date, f.received_date, f.curated_at,
       f.last_curation_error AS error, f.retry_count, f.queue_rank,
       f.exclusion_reason, f.exclusion_category,
{_CHAIN_SQL}
  FROM f
  LEFT JOIN detected d ON d.uid = f.uid
  LEFT JOIN atomised z ON z.uid = f.uid
  LEFT JOIN recalled r ON r.uid = f.uid
 ORDER BY {_CONV_ORDER[order]}
 LIMIT %(limit)s OFFSET %(offset)s"""

    # Les facettes se calculent sur la recherche, PAS sur les filtres qu'elles
    # servent à choisir : filtrer sur « done » ne doit pas faire disparaître les
    # autres statuts du sélecteur — sinon l'utilisateur perd la sortie.
    facets_sql = f"""{_CONV_BASE}
SELECT (SELECT count(*) FROM base b {_where(preds)}) AS total,
       (SELECT COALESCE(jsonb_object_agg(t.status, t.n), '{{}}'::jsonb)
          FROM (SELECT b.status, count(*) AS n FROM base b
                 {_where(preds, skip='status')} GROUP BY b.status) t) AS by_status,
       (SELECT COALESCE(jsonb_object_agg(t.source_type, t.n), '{{}}'::jsonb)
          FROM (SELECT b.source_type, count(*) AS n FROM base b
                 {_where(preds, skip='source')} GROUP BY b.source_type) t) AS by_source,
       (SELECT count(*) FROM queue) AS queue_size"""

    started = time.perf_counter()
    try:
        with _readonly() as conn:
            items = _rows(conn, items_sql, params, where="conversations.items")
            head = _one(conn, facets_sql, params, where="conversations.facets") or {}
            evidence_sql = _sql_text(conn, items_sql, params)
            facets_evidence = _sql_text(conn, facets_sql, params)
    except Exception as exc:  # noqa: BLE001
        return _failure("conversations", exc) | {"items": [], "total": None,
                                                 "limit": limit, "offset": offset}

    return {
        "state": "ok",
        "items": items,
        "total": head.get("total"),
        "limit": limit,
        "offset": offset,
        "order": order,
        "filters": {"status": status, "source": source, "q": q},
        "facets": {
            "by_status": head.get("by_status") or {},
            "by_source": head.get("by_source") or {},
            "note": "facettes calculées avant application du filtre qu'elles proposent",
        },
        "queue": {
            "size": head.get("queue_size"),
            "rule": ("rang parmi les conversations non terminées (pending, partial, error), "
                     "triées par date du plus ancien message NON CURÉ croissante — "
                     "c'est le tri anti-famine du gate de digestion"),
        },
        "chain_legend": {
            "1": "Détectée (reçu d'ingestion)", "2": "Absorbée (messages bruts)",
            "3": "Analysée (curseur de curation)", "4": "Atomisée (atomes actifs)",
            "5": "Reliée (indisponible)", "6": "Retrouvée (servie au rappel)",
        },
        "evidence": {"kind": "sql", "sql": evidence_sql,
                     "label": "les conversations de cette page, telles que la base les décrit",
                     "queries": [evidence_sql, facets_evidence]},
        "computed_at": service._now(),
        "duration_ms": service._ms(started),
    }


def conversation_detail(uid: str) -> dict[str, Any]:
    """Une conversation : ce qu'elle a produit, ce qu'elle a raté, où elle en est.

    N'expose NI le contenu des messages NI la valeur des atomes : une fiche de
    navigation n'a pas besoin de la matière intime pour être utile, et ce qui
    n'est pas servi ne peut pas fuir.
    """
    uid = _clean(uid) or ""
    if not uid:
        return _unavailable("identifiant de conversation vide")

    preds, params = _conv_filters(None, None, None, uid)
    header_sql = f"""{_CONV_BASE}
, f AS (
    SELECT b.*, qu.queue_rank
      FROM base b
      LEFT JOIN queue qu ON qu.id = b.id
      {_where(preds)}
)
SELECT f.id, f.uid, f.title, f.source_type, f.node_id, f.status, f.messages,
       f.atoms_generated, f.curated_pct, f.curated_messages, f.cursor_id,
       f.max_message_id, f.content_date, f.received_date, f.curated_at,
       f.last_curation_error AS error, f.retry_count, f.next_retry_at, f.acked,
       f.exclusion_reason, f.exclusion_category, f.excluded_at,
       f.created_at, f.updated_at, f.queue_rank,
{_CHAIN_SQL}
  FROM f
  LEFT JOIN detected d ON d.uid = f.uid
  LEFT JOIN atomised z ON z.uid = f.uid
  LEFT JOIN recalled r ON r.uid = f.uid
 LIMIT 1"""

    # `count(*) OVER ()` porte le total AVANT la borne : une liste coupée doit
    # pouvoir dire qu'elle est coupée, sinon elle affirme un total faux.
    # POURQUOI LES DEUX VOIES ICI AUSSI (2026-08-05) :
    # le maillon « Atomisée » de la chaîne rattache désormais les atomes legacy par
    # `curator_raw_id -> raw_conversations.source_path`. Si cette liste-ci ne
    # connaissait que `source_ref->>'conversation_uid'`, la fiche dirait
    # « Atomisée : done » au-dessus d'une liste d'atomes VIDE — exactement la
    # contradiction preuve/valeur qu'on vient de corriger ailleurs. La colonne
    # `voie` accompagne chaque ligne : un rattachement reconstruit s'annonce.
    atoms_sql = """
WITH rattache AS (
    SELECT a.id, 'source_ref'::text AS voie
      FROM arac.memory_atoms a
     WHERE a.source_ref->>'conversation_uid' = %(uid)s
    UNION ALL
    SELECT atom_id AS id, 'legacy_source_path'::text AS voie
      FROM (
          SELECT a.id AS atom_id,
                 min(c.conversation_uid) AS uid,
                 count(DISTINCT c.conversation_uid) AS n_match
            FROM arac.memory_atoms a
            JOIN arac.raw_conversations rc
                 ON rc.id::text = a.source_ref->>'curator_raw_id'
            JOIN arac.conversations c
                 ON strpos(rc.source_path, c.conversation_uid) > 0
           WHERE a.status = 'active'
             AND NOT (a.source_ref ? 'conversation_uid')
           GROUP BY a.id
      ) r
     WHERE r.n_match = 1 AND r.uid = %(uid)s
)
SELECT a.id, a.kind, a.scope, a.key, a.status, a.version, a.confidence_score,
       a.created_at, a.updated_at,
       (a.version > 1 OR a.supersedes IS NOT NULL) AS enriched,
       t.voie,
       count(*) OVER () AS total_for_conversation
  FROM arac.memory_atoms a
  JOIN rattache t ON t.id = a.id
 ORDER BY a.created_at DESC
 LIMIT %(detail_limit)s"""

    dropped_sql = """
SELECT d.drop_reason, d.kind, d.scope, d.created_at, d.incumbent_atom_id,
       d.status, d.run_ref
  FROM arac.digestion_review_queue d
 WHERE d.conversation_uid = %(uid)s
 ORDER BY d.created_at DESC
 LIMIT %(detail_limit)s"""

    # Un passage « concerne » la conversation s'il l'a EMBARQUÉE (pack) ou s'il a
    # RENDU COMPTE d'elle (progress). Les deux existent : un passage peut charger
    # une conversation sans jamais produire de disposition.
    runs_sql = """
SELECT r.id, r.slot_key, r.status, r.trigger, r.model, r.started_at, r.ended_at,
       r.stop_reason, r.outcome, r.items, r.atoms_created, r.atoms_quarantined,
       (r.progress -> %(uid)s) AS report
  FROM arac.run_receipts r
 WHERE (r.pack @> jsonb_build_array(jsonb_build_object('uid', %(uid)s::text))
        OR (r.progress ? %(uid)s))
 ORDER BY r.id DESC
 LIMIT %(detail_limit)s"""

    # L'aperçu compte, date et ventile par rôle — SANS jamais lire un contenu.
    # L'accès à raw_messages est clé par conversation_id (target), donc borné.
    preview_sql = """
WITH target AS (
    SELECT c.id FROM arac.conversations c WHERE c.conversation_uid = %(uid)s LIMIT 1
),
per_role AS (
    SELECT m.role, count(*) AS n,
           min(COALESCE(m.msg_created_at, m.received_at)) AS first_at,
           max(COALESCE(m.msg_created_at, m.received_at)) AS last_at
      FROM arac.raw_messages m
      JOIN target t ON t.id = m.conversation_id
     GROUP BY m.role
)
SELECT COALESCE(sum(n), 0)     AS count,
       min(first_at)           AS first_at,
       max(last_at)            AS last_at,
       COALESCE(jsonb_object_agg(role, n), '{}'::jsonb) AS roles
  FROM per_role"""

    params |= {"detail_limit": _DETAIL_LIMIT}
    started = time.perf_counter()
    try:
        with _readonly() as conn:
            header = _one(conn, header_sql, params, where="conversation.header")
            if header is None:
                return _unavailable(
                    f"aucune conversation ne porte l'identifiant {uid!r}",
                    uid=uid,
                    evidence={"kind": "sql", "sql": _sql_text(conn, header_sql, params),
                              "label": "la requête qui n'a rien trouvé"},
                )
            atoms = _rows(conn, atoms_sql, params, where="conversation.atoms")
            dropped = _rows(conn, dropped_sql, params, where="conversation.dropped")
            runs = _rows(conn, runs_sql, params, where="conversation.runs")
            preview = _one(conn, preview_sql, params, where="conversation.preview") or {}
            evidence_sql = _sql_text(conn, header_sql, params)
            queries = [evidence_sql] + [
                _sql_text(conn, s, params)
                for s in (atoms_sql, dropped_sql, runs_sql, preview_sql)
            ]
            # La connexion est ICI, et c'est le seul endroit où elle vit : la
            # sonde des liens doit donc être tirée dans le bloc, pas à la
            # composition de la réponse. Le faire après, c'était servir « je
            # n'ai pas pu regarder » sur une page qui venait de tout lire.
            links = links_dependency(conn)
    except Exception as exc:  # noqa: BLE001
        return _failure(f"conversation:{uid}", exc)

    chain = header.pop("chain", [])
    atoms_total = atoms[0]["total_for_conversation"] if atoms else 0
    for a in atoms:
        a.pop("total_for_conversation", None)
    return {
        "state": "ok",
        "header": header,
        "chain": chain,
        # La partition créés / enrichis vient du SQL (colonne `enriched`) ; Python
        # ne fait que ranger deux piles déjà décidées par la base.
        "atoms_created": [a for a in atoms if not a.get("enriched")],
        "atoms_enriched": [a for a in atoms if a.get("enriched")],
        "atoms_total": atoms_total,
        "atoms_truncated": atoms_total > len(atoms),
        "atoms_limit": _DETAIL_LIMIT,
        "dropped": dropped,
        "runs": runs,
        "messages_preview": {
            "count": preview.get("count"),
            "first_at": preview.get("first_at"),
            "last_at": preview.get("last_at"),
            "roles": preview.get("roles") or {},
            "note": "aucun contenu de message n'est servi par cette route (données personnelles)",
        },
        "links": links,
        "evidence": {"kind": "sql", "sql": evidence_sql,
                     "label": "l'état de cette conversation, tel que la base l'affirme",
                     "queries": queries},
        "computed_at": service._now(),
        "duration_ms": service._ms(started),
    }


# ============================================================================
# ATOMES — 9 vues sur le savoir
# ============================================================================
#
# Une vue est un COUPLE (filtre, tri) déclaré ici et exécuté en SQL. Le client
# choisit un nom ; il n'écrit ni prédicat ni ordre — sinon deux écrans pourraient
# afficher deux « jamais rappelés » différents.

ATOM_VIEWS: dict[str, dict[str, Any]] = {
    "tous": {"where": None, "order": "b.created_at DESC, b.id",
             "label": "Tous les atomes du périmètre"},
    "nouveaux": {"where": "b.created_at >= now() - interval '7 days'",
                 "order": "b.created_at DESC, b.id",
                 "label": "Nés dans les 7 derniers jours"},
    "enrichis": {"where": "(b.version > 1 OR b.supersedes IS NOT NULL)",
                 "order": "b.updated_at DESC, b.id",
                 "label": "Révisés au moins une fois depuis leur naissance"},
    "jamais_rappeles": {"where": "b.never_served",
                        "order": "b.created_at DESC, b.id",
                        "label": "Jamais remontés dans un contexte servi"},
    "les_plus_utilises": {"where": "b.usage_count > 0",
                          "order": "b.usage_count DESC, b.last_served_at DESC, b.id",
                          "label": "Les plus servis au rappel"},
    "perimes": {"where": "(b.confirmed_until IS NOT NULL AND b.confirmed_until < now())",
                "order": "b.confirmed_until ASC, b.id",
                "label": "Dont la date de confirmation est dépassée",
                "requires": "confirmed_until"},
    "dette_root": {"where": "b.is_root_scoped",
                   "order": "b.created_at DESC, b.id",
                   "label": "Posés sur un scope racine : invisibles au rappel"},
    "anciens": {"where": None, "order": "b.created_at ASC, b.id",
                "label": "Du plus ancien au plus récent"},
    "recents": {"where": None, "order": "b.created_at DESC, b.id",
                "label": "Du plus récent au plus ancien"},
}

_ATOM_ORDER: dict[str, str] = {
    "created_at": "b.created_at DESC, b.id",
    "updated_at": "b.updated_at DESC, b.id",
    "usage_count": "b.usage_count DESC, b.created_at DESC, b.id",
    "confidence_score": "b.confidence_score DESC NULLS LAST, b.id",
    "key": "b.key ASC, b.id",
    "scope": "b.scope ASC, b.key ASC, b.id",
    "kind": "b.kind ASC, b.created_at DESC, b.id",
    "last_served_at": "b.last_served_at DESC NULLS LAST, b.id",
}

# `matches_q` porte la recherche sur la valeur ENTIÈRE (index trigramme
# ix_memory_atoms_value_trgm), pas sur l'extrait de 200 caractères : chercher
# dans l'extrait raterait en silence, et un silence se prend pour une absence.
# Seul le booléen sort de la base ; la valeur, jamais.
#
# Aucun commentaire SQL (`--`) dans ces gabarits : la preuve est normalisée sur
# UNE ligne, et un commentaire de fin de ligne y avalerait toute la requête.
_ATOM_BASE = """
WITH usage AS (
    /* UN RAPPEL, UNE LIGNE (corrige 2026-08-05). Sans le predicat ci-dessous,
       `usage_count` comptait les RECUS et non les RAPPELS : la liste annoncait
       424 la ou la fiche d'histoire du meme atome annonce 212. Deux ecrans, deux
       verites pour « combien de fois ce souvenir est-il ressorti ». */
    SELECT s AS atom_id, count(*) AS usage_count, max(cr.created_at) AS last_served_at
      FROM arac.context_receipts cr
      CROSS JOIN LATERAL unnest(cr.served_ids) s
     WHERE TRUE
       """ + UN_RECU_PAR_RAPPEL + """
     GROUP BY s
),
base AS (
    SELECT a.id, a.kind, a.scope, a.key, a.status, a.version, a.confidence,
           a.confidence_score, a.tags, a.created_at, a.updated_at, a.observed_at,
           a.last_verified_at, a.confirmed_until, a.supersedes, a.superseded_by,
           a.node_id, a.session_id, a.audit_source,
           (a.scope NOT LIKE %(slash)s) AS is_root_scoped,
           CASE WHEN a.confirmed_until IS NULL THEN NULL
                ELSE a.confirmed_until < now() END AS is_stale,
           COALESCE(u.usage_count, 0) AS usage_count,
           u.last_served_at,
           (u.atom_id IS NULL) AS never_served,
           a.source_ref->>'conversation_uid' AS source_conversation_uid,
           left(a.value, 200) AS excerpt,
           (%(q)s IS NULL OR a.key ILIKE %(q)s OR a.value ILIKE %(q)s) AS matches_q
      FROM arac.memory_atoms a
      LEFT JOIN usage u ON u.atom_id = a.id
)
"""


#: Les statuts qu'un atome peut réellement porter. Sert à distinguer « ce statut
#: existe mais aucun atome ne le porte » de « ce statut n'existe pas » — deux
#: réponses vides qui ne veulent pas dire la même chose.
_ATOM_STATUSES: frozenset[str] = frozenset(
    {"active", "archived", "superseded", "draft", "low_confidence_archive"})


def atoms_list(limit: int = _DEFAULT_LIMIT, offset: int = 0, scope: str | None = None,
               scope_prefix: str | None = None, kind: str | None = None,
               status: str | None = "active", view: str | None = None,
               q: str | None = None, order: str = "created_at") -> dict[str, Any]:
    """Les atomes du cerveau, filtrés, facettés, jamais résumés par le client.

    ``status`` vaut ``active`` par défaut : seuls les atomes actifs sont
    rappelables. ``status='*'`` ouvre le tiroir complet (archivés, supersédés,
    brouillons) — c'est un geste explicite, pas un défaut.

    Ne rend JAMAIS la valeur complète d'un atome ni son plongement : seulement un
    extrait de 200 caractères, découpé EN SQL.
    """
    limit = _bounded(limit)
    offset = max(0, int(offset or 0))
    scope, scope_prefix, kind, q = (_clean(scope), _clean(scope_prefix),
                                    _clean(kind), _clean(q))
    status = _clean(status)
    # Une entrée non reconnue n'est JAMAIS avalée en silence : elle est
    # remplacée ET signalée. Sans cela, `?view=inventée` rendait la vue par
    # défaut sans le dire, et `?status=all` rendait 0 atome en état « ok » —
    # une demande refusée passée pour un résultat.
    notices: list[str] = []

    demande_vue = _clean(view)
    view_name = demande_vue or "tous"
    if view_name not in ATOM_VIEWS:
        notices.append(
            f"vue {demande_vue!r} inconnue — vue « tous » appliquée. "
            f"Vues admises : {', '.join(sorted(ATOM_VIEWS))}."
        )
        view_name = "tous"
    spec = ATOM_VIEWS[view_name]

    demande_ordre = order
    order = order if order in _ATOM_ORDER else "created_at"
    if demande_ordre and demande_ordre != order:
        notices.append(
            f"tri {demande_ordre!r} inconnu — tri « {order} » appliqué. "
            f"Tris admis : {', '.join(sorted(_ATOM_ORDER))}."
        )

    # « tout » s'écrit de plusieurs façons naturelles : les trois sont admises,
    # parce qu'un utilisateur qui demande tout ne doit pas recevoir rien.
    _TOUT = {"*", "all", "tous"}
    if status and status.lower() in _TOUT:
        status = None
        notices.append("filtre de statut levé : tous les statuts sont servis.")
    elif status and status not in _ATOM_STATUSES:
        notices.append(
            f"statut {status!r} inconnu — aucun atome ne le porte. "
            f"Statuts admis : {', '.join(sorted(_ATOM_STATUSES))}, "
            "ou « all » pour lever le filtre."
        )

    preds: dict[str, str] = {}
    params: dict[str, Any] = {"slash": _SLASH, "limit": limit, "offset": offset,
                              "q": _like(q)}
    if status and status != "*":
        preds["status"] = "b.status = %(status)s"
        params["status"] = status
    if scope:
        preds["scope"] = "b.scope = %(scope)s"
        params["scope"] = scope
    if scope_prefix:
        preds["scope_prefix"] = "(b.scope = %(scope_root)s OR b.scope LIKE %(scope_like)s)"
        params["scope_root"] = scope_prefix.rstrip("/")
        params["scope_like"] = scope_prefix.rstrip("/") + "/%"
    if kind:
        preds["kind"] = "b.kind = %(kind)s"
        params["kind"] = kind
    if q:
        preds["q"] = "b.matches_q"
    if spec["where"]:
        preds["view"] = spec["where"]

    # Le tri de la vue prime sur le tri générique : « les plus utilisés » sans son
    # ordre ne serait plus une vue, juste un filtre. La réponse annonce alors le
    # tri RÉELLEMENT appliqué — pas celui qui a été demandé.
    view_orders = view_name not in ("tous", "recents")
    order_sql = spec["order"] if view_orders else _ATOM_ORDER[order]
    effective_order = f"view:{view_name}" if view_orders else order

    # Chaque facette ignore le filtre qu'elle sert à choisir : sans cela, filtrer
    # sur un kind ferait disparaître les autres kinds du sélecteur, et l'utilisateur
    # perdrait la sortie de son propre filtre.
    preds_no_scope = {k: v for k, v in preds.items() if k not in ("scope", "scope_prefix")}

    items_sql = f"""{_ATOM_BASE}
SELECT b.id, b.kind, b.scope, b.key, b.status, b.version, b.confidence,
       b.confidence_score, b.tags, b.created_at, b.updated_at,
       b.last_verified_at, b.confirmed_until, b.is_stale, b.is_root_scoped,
       b.usage_count, b.last_served_at, b.never_served,
       b.source_conversation_uid, b.excerpt
  FROM base b
  {_where(preds)}
 ORDER BY {order_sql}
 LIMIT %(limit)s OFFSET %(offset)s"""

    facets_sql = f"""{_ATOM_BASE}
SELECT (SELECT count(*) FROM base b {_where(preds)}) AS total,
       (SELECT COALESCE(jsonb_object_agg(t.kind, t.n), '{{}}'::jsonb)
          FROM (SELECT b.kind, count(*) AS n FROM base b {_where(preds, skip='kind')}
                 GROUP BY b.kind) t) AS by_kind,
       (SELECT COALESCE(jsonb_object_agg(t.scope, t.n), '{{}}'::jsonb)
          FROM (SELECT b.scope, count(*) AS n FROM base b {_where(preds_no_scope)}
                 GROUP BY b.scope) t) AS by_scope,
       (SELECT COALESCE(jsonb_object_agg(t.status, t.n), '{{}}'::jsonb)
          FROM (SELECT b.status, count(*) AS n FROM base b {_where(preds, skip='status')}
                 GROUP BY b.status) t) AS by_status,
       (SELECT count(*) FROM arac.memory_atoms a WHERE a.confirmed_until IS NOT NULL)
           AS with_confirmed_until"""

    started = time.perf_counter()
    try:
        with _readonly() as conn:
            items = _rows(conn, items_sql, params, where="atoms.items")
            head = _one(conn, facets_sql, params, where="atoms.facets") or {}
            evidence_sql = _sql_text(conn, items_sql, params)
            facets_evidence = _sql_text(conn, facets_sql, params)
    except Exception as exc:  # noqa: BLE001
        return _failure("atoms", exc) | {"items": [], "total": None,
                                         "limit": limit, "offset": offset}

    out: dict[str, Any] = {
        "state": "ok",
        "items": items,
        "total": head.get("total"),
        "limit": limit,
        "offset": offset,
        "order": effective_order,
        "order_requested": order,
        "view": {"key": view_name, "label": spec["label"], "available": sorted(ATOM_VIEWS)},
        "filters": {"scope": scope, "scope_prefix": scope_prefix, "kind": kind,
                    "status": status, "q": q,
                    "status_note": ("aucun filtre de statut : tous les statuts servis"
                                    if status is None else None)},
        # Toute entrée refusée ou remplacée est nommée ici. Une liste vide dit
        # que rien n'a été substitué — ce n'est pas la même chose qu'un silence.
        "notices": notices,
        "facets": {
            "by_kind": head.get("by_kind") or {},
            "by_scope": head.get("by_scope") or {},
            "by_status": head.get("by_status") or {},
            "note": "facettes calculées avant application du filtre qu'elles proposent",
        },
        "evidence": {"kind": "sql", "sql": evidence_sql,
                     "label": "les atomes de cette page, tels que la base les décrit",
                     "queries": [evidence_sql, facets_evidence]},
        "computed_at": service._now(),
        "duration_ms": service._ms(started),
    }

    # Une vue vide parce que la colonne qu'elle interroge n'est jamais alimentée
    # n'est PAS un résultat : c'est une absence. Elle doit se dire.
    if spec.get("requires") == "confirmed_until" and not head.get("with_confirmed_until"):
        out["view"] = out["view"] | {
            "state": "unavailable",
            "reason": ("aucun atome ne porte de date de confirmation (confirmed_until "
                       "n'est alimenté par aucun agent) : cette vue est vide par absence "
                       "de donnée, pas parce que rien n'est périmé"),
            "gesture": "alimenter memory_atoms.confirmed_until à la curation",
        }
        out["total"] = None
    return out


def atom_detail(atom_id: str) -> dict[str, Any]:
    """Un atome : son identité, son contenu, sa lignée, ses voisins, son usage.

    C'est la seule route qui sert la valeur complète d'un atome — parce que c'est
    la seule où l'utilisateur a explicitement demandé CET atome.
    """
    atom_id = _clean(atom_id) or ""
    if not atom_id:
        return _unavailable("identifiant d'atome vide")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", atom_id):
        return _unavailable(f"{atom_id!r} n'est pas un identifiant d'atome (uuid attendu)",
                            id=atom_id)

    identity_sql = """
WITH usage AS (
    /* UN RAPPEL, UNE LIGNE (corrige 2026-08-05). Cette fiche annoncait 424 « fois
       servi » quand /cc/v1/atoms/{id}/story, qui porte deja le predicat, en
       annonce 212 pour le MEME atome. Le rang moyen etait pire qu'un doublon :
       il moyennait les rangs du moteur SERVI (v1) avec ceux du moteur d'ombre
       (v2-fold), fabriquant un rang qu'aucun moteur n'a produit. */
    SELECT count(*) AS served_count,
           max(cr.created_at) AS last_served_at,
           round(avg(array_position(cr.served_ids, %(id)s::uuid))::numeric, 2) AS avg_rank
      FROM arac.context_receipts cr
     WHERE cr.served_ids @> ARRAY[%(id)s::uuid]
       """ + UN_RECU_PAR_RAPPEL + """
)
SELECT a.id, a.kind, a.scope, a.key, a.status, a.version, a.confidence,
       a.confidence_score, a.tags, a.audit_source, a.node_id, a.session_id,
       a.created_at, a.updated_at, a.observed_at, a.last_verified_at,
       a.confirmed_until, a.dedupe_key, a.supersedes, a.superseded_by,
       a.value, a.rationale, a.source_ref,
       (a.scope NOT LIKE %(slash)s) AS is_root_scoped,
       CASE WHEN a.confirmed_until IS NULL THEN NULL
            ELSE a.confirmed_until < now() END AS is_stale,
       (a.embedding IS NOT NULL) AS has_embedding,
       a.source_ref->>'conversation_uid' AS conversation_uid,
       c.title AS conversation_title,
       c.source_type AS conversation_source_type,
       u.served_count, u.last_served_at, u.avg_rank,
       (u.served_count = 0) AS never_served
  FROM arac.memory_atoms a
  CROSS JOIN usage u
  LEFT JOIN arac.conversations c
         ON c.conversation_uid = a.source_ref->>'conversation_uid'
 WHERE a.id = %(id)s::uuid
 LIMIT 1"""

    lineage_sql = """
WITH RECURSIVE ancestors AS (
    SELECT a.id, a.version, a.created_at, a.status, a.key, a.scope, a.supersedes, 0 AS hop
      FROM arac.memory_atoms a WHERE a.id = %(id)s::uuid
    UNION ALL
    SELECT p.id, p.version, p.created_at, p.status, p.key, p.scope, p.supersedes, an.hop - 1
      FROM arac.memory_atoms p
      JOIN ancestors an ON p.id = an.supersedes
     WHERE an.hop > -20
),
descendants AS (
    SELECT a.id, a.version, a.created_at, a.status, a.key, a.scope, a.superseded_by, 0 AS hop
      FROM arac.memory_atoms a WHERE a.id = %(id)s::uuid
    UNION ALL
    SELECT n.id, n.version, n.created_at, n.status, n.key, n.scope, n.superseded_by, de.hop + 1
      FROM arac.memory_atoms n
      JOIN descendants de ON n.id = de.superseded_by
     WHERE de.hop < 20
)
SELECT id, version, created_at, status, key, scope, min(hop) AS hop
  FROM (SELECT id, version, created_at, status, key, scope, hop FROM ancestors
        UNION ALL
        SELECT id, version, created_at, status, key, scope, hop FROM descendants) t
 GROUP BY id, version, created_at, status, key, scope
 ORDER BY hop, created_at
 LIMIT 40"""

    neighbours_sql = """
WITH me AS (SELECT embedding FROM arac.memory_atoms WHERE id = %(id)s::uuid LIMIT 1)
SELECT a.id, a.key, a.scope, a.kind, a.status,
       round((a.embedding <=> (SELECT embedding FROM me))::numeric, 4) AS distance
  FROM arac.memory_atoms a
 WHERE a.id <> %(id)s::uuid
   AND a.status = 'active'
   AND a.embedding IS NOT NULL
   AND (SELECT embedding FROM me) IS NOT NULL
 ORDER BY a.embedding <=> (SELECT embedding FROM me)
 LIMIT %(neighbours)s"""

    # UN RAPPEL, UN ÉVÉNEMENT (corrigé 2026-08-05). Cette liste servait CHAQUE
    # rappel deux fois — 20 lignes pour 10 interrogations réelles, mêmes
    # horodatage, consommateur et filtres, seul le rang variant d'un moteur à
    # l'autre. Le lecteur voyait la mémoire interrogée deux fois plus souvent
    # qu'elle ne l'a été, et deux « bandes » contradictoires pour un seul rappel.
    queries_sql = """
SELECT cr.created_at, cr.consumer, cr.final_band, cr.raw_band, cr.stop_reason,
       cr.scope_filter, cr.kind_filter, cr.k_requested, cr.budget_k,
       array_position(cr.served_ids, %(id)s::uuid) AS rank
  FROM arac.context_receipts cr
 WHERE cr.served_ids @> ARRAY[%(id)s::uuid]
   """ + UN_RECU_PAR_RAPPEL + """
 ORDER BY cr.created_at DESC
 LIMIT 20"""

    proj_blocks: list[str] = []
    proj_params: dict[str, Any] = {}
    for p in PROJECTS:
        pred, prm = _project_predicate(p, "a", f"p_{p['id']}")
        proj_params |= prm
        proj_params[f"lab_{p['id']}"] = p["label"]
        proj_blocks.append(
            f"SELECT '{p['id']}' AS id, %(lab_{p['id']})s AS label"
            f"  FROM arac.memory_atoms a WHERE a.id = %(id)s::uuid AND {pred}"
        )
    # Zéro projet déclaré ne veut pas dire zéro SQL : `union_ou_vide` rend une
    # relation vide et TYPÉE, sans quoi il ne resterait ici qu'un `LIMIT 8` nu.
    projects_sql = union_ou_vide(
        proj_blocks, (("id", "text"), ("label", "text")),
    ) + "\nLIMIT 8"

    params: dict[str, Any] = {"id": atom_id, "slash": _SLASH, "neighbours": _NEIGHBOURS}
    started = time.perf_counter()
    try:
        with _readonly() as conn:
            row = _one(conn, identity_sql, params, where="atom.identity")
            if row is None:
                return _unavailable(
                    f"aucun atome ne porte l'identifiant {atom_id}",
                    id=atom_id,
                    evidence={"kind": "sql", "sql": _sql_text(conn, identity_sql, params),
                              "label": "la requête qui n'a rien trouvé"},
                )
            lineage = _rows(conn, lineage_sql, params, where="atom.lineage")
            recalls = _rows(conn, queries_sql, params, where="atom.queries")
            projects = _rows(conn, projects_sql, params | proj_params, where="atom.projects")
            evidence_sql = _sql_text(conn, identity_sql, params)
            queries_evidence = [
                evidence_sql,
                _sql_text(conn, lineage_sql, params),
                _sql_text(conn, queries_sql, params),
            ]
            # Le voisinage sémantique dépend de pgvector ET du plongement. S'il
            # manque l'un des deux, on le DIT et on rend une liste vide — on ne
            # plante pas la fiche pour un organe optionnel.
            try:
                neighbours = _rows(conn, neighbours_sql, params, where="atom.neighbours")
                neighbours_state = {"state": "ok", "reason": None}
                queries_evidence.append(_sql_text(conn, neighbours_sql, params))
            except Exception as exc:  # noqa: BLE001
                # Message autoporteur : le formateur par défaut d'uvicorn ne rend
                # jamais `extra=` (cf. _failure). Sans cela, la ligne journalisée était
                # le seul jeton « cc_v1.neighbours_failed », sans atome ni cause.
                logger.warning("cc_v1.neighbours_failed atom_id=%s raison=%s",
                               atom_id, raison(exc),
                               extra={"atom_id": atom_id, "error": type(exc).__name__},
                               exc_info=True)
                neighbours = []
                neighbours_state = {
                    "state": "unavailable",
                    "reason": f"voisinage sémantique indisponible ({raison(exc)})",
                }
            # Même règle que partout : la sonde des liens est tirée là où la
            # connexion existe. Cette fiche affichait « le schéma n'a pas été
            # interrogé » après avoir interrogé le schéma cinq fois.
            links = links_dependency(conn)
    except Exception as exc:  # noqa: BLE001
        return _failure(f"atom:{atom_id}", exc)

    if not row.get("has_embedding") and neighbours_state["state"] == "ok" and not neighbours:
        neighbours_state = {"state": "unavailable",
                            "reason": "cet atome n'a pas de plongement : aucun voisin calculable"}

    identity_keys = ("id", "kind", "scope", "key", "status", "version", "confidence",
                     "confidence_score", "tags", "audit_source", "created_at", "updated_at",
                     "observed_at", "last_verified_at", "confirmed_until", "dedupe_key",
                     "is_stale", "is_root_scoped", "has_embedding")
    return {
        "state": "ok",
        "identity": {k: row.get(k) for k in identity_keys},
        "content": {"value": row.get("value"), "rationale": row.get("rationale")},
        "provenance": {
            "conversation_uid": row.get("conversation_uid"),
            "conversation_title": row.get("conversation_title"),
            "conversation_source_type": row.get("conversation_source_type"),
            "node_id": row.get("node_id"),
            "session_id": row.get("session_id"),
            "source_ref": row.get("source_ref"),
        },
        "lineage": {
            "versions": lineage,
            "supersedes": row.get("supersedes"),
            "superseded_by": row.get("superseded_by"),
        },
        "neighbors": neighbours,
        "neighbors_state": neighbours_state | {
            "operator": "pgvector <=> (distance cosinus)", "limit": _NEIGHBOURS,
        },
        "usage": {
            "served_count": row.get("served_count"),
            "last_served_at": row.get("last_served_at"),
            "never_served": row.get("never_served"),
            "avg_rank": row.get("avg_rank"),
            "queries": recalls,
        },
        "links": links | {"substitute": "voisinage sémantique"},
        "projects": projects,
        "evidence": {"kind": "sql", "sql": evidence_sql,
                     "label": "cet atome, tel que la base le décrit",
                     "queries": queries_evidence},
        "computed_at": service._now(),
        "duration_ms": service._ms(started),
    }


# ============================================================================
# SCOPES — l'arbre du savoir et sa dette
# ============================================================================


def scopes_list(limit: int = MAX_LIMIT) -> dict[str, Any]:
    """Les scopes peuplés, leur poids, leur part dormante, leur dette de racine.

    Un scope racine (sans ``/``) est INVISIBLE au rappel : ses atomes existent
    mais ne remontent jamais. C'est la dette root-level, et elle se voit ici.
    """
    limit = _bounded(limit, MAX_LIMIT)
    sql = """
WITH served AS (
    SELECT DISTINCT s AS atom_id
      FROM arac.context_receipts cr
      CROSS JOIN LATERAL unnest(cr.served_ids) s
),
agg AS (
    SELECT a.scope AS path,
           count(*)                                       AS atom_count,
           count(*) FILTER (WHERE sv.atom_id IS NULL)     AS dormant_count,
           count(*) FILTER (WHERE a.kind = 'decision')    AS decisions,
           count(*) FILTER (WHERE a.kind = 'gotcha')      AS gotchas,
           max(a.created_at)                              AS last_atom_at,
           min(a.created_at)                              AS first_atom_at,
           count(DISTINCT a.kind)                         AS kinds
      FROM arac.memory_atoms a
      LEFT JOIN served sv ON sv.atom_id = a.id
     WHERE a.status = 'active'
     GROUP BY a.scope
)
SELECT g.path,
       (g.path NOT LIKE %(slash)s)                                   AS is_root,
       (length(g.path) - length(replace(g.path, '/', '')) + 1)       AS depth,
       split_part(g.path, '/', 1)                                    AS root,
       g.atom_count, g.dormant_count, g.decisions, g.gotchas,
       g.kinds, g.first_atom_at, g.last_atom_at,
       round(100.0 * g.dormant_count / nullif(g.atom_count, 0), 1)   AS dormant_pct,
       pr.member_count                                               AS member_count_registry,
       pr.updated_at                                                 AS registry_updated_at
  FROM agg g
  LEFT JOIN arac.project_registry pr ON pr.scope = g.path
 ORDER BY g.atom_count DESC, g.path
 LIMIT %(limit)s"""

    totals_sql = """
SELECT count(DISTINCT a.scope)                                          AS scopes,
       count(DISTINCT a.scope) FILTER (WHERE a.scope NOT LIKE %(slash)s) AS root_scopes,
       count(*) FILTER (WHERE a.scope NOT LIKE %(slash)s)                AS root_level_debt,
       count(*)                                                          AS atoms,
       (SELECT count(*) FROM arac.project_registry)                      AS registry_scopes
  FROM arac.memory_atoms a
 WHERE a.status = 'active'"""

    params = {"slash": _SLASH, "limit": limit}
    started = time.perf_counter()
    try:
        with _readonly() as conn:
            items = _rows(conn, sql, params, where="scopes")
            totals = _one(conn, totals_sql, params, where="scopes.totals") or {}
            evidence_sql = _sql_text(conn, sql, params)
            totals_evidence = _sql_text(conn, totals_sql, params)
    except Exception as exc:  # noqa: BLE001
        return _failure("scopes", exc) | {"items": []}

    return {
        "state": "ok",
        "items": items,
        "count": len(items),
        "limit": limit,
        "totals": totals,
        "note": ("member_count_registry vient de arac.project_registry ; il est null pour "
                 "un scope que le routeur de projets n'a pas encore indexé"),
        "evidence": {"kind": "sql", "sql": evidence_sql,
                     "label": "les scopes peuplés et leur dette",
                     "queries": [evidence_sql, totals_evidence]},
        "computed_at": service._now(),
        "duration_ms": service._ms(started),
    }


# ============================================================================
# PROJETS — 8 vues transverses (D-CC-09)
# ============================================================================


def _project_stats_sql() -> tuple[str, dict[str, Any]]:
    """Une seule requête pour tous les projets : comptes, activité, état.

    Tout est agrégé en SQL — y compris l'état (actif / veille / bloqué / vide) et
    le nombre de conversations en attente qui concernent le projet.
    """
    blocks: list[str] = []
    params: dict[str, Any] = {"slash": _SLASH, "dormant_days": _DORMANT_DAYS}
    for p in PROJECTS:
        pred, prm = _project_predicate(p, "a", f"p_{p['id']}")
        params |= prm
        params[f"lab_{p['id']}"] = p["label"]
        blocks.append(
            f"SELECT '{p['id']}'::text AS id, %(lab_{p['id']})s::text AS label,"
            f" a.id AS atom_id FROM arac.memory_atoms a"
            f" WHERE a.status = 'active' AND {pred}"
        )
    # `membership` est inséré entre parenthèses (`membership AS ( … )`) et
    # joint plus bas sur `m.atom_id` : la relation de repli doit donc porter
    # les trois mêmes colonnes, typées, même quand elle ne rend aucune ligne.
    membership = union_ou_vide(
        blocks, (("id", "text"), ("label", "text"), ("atom_id", "uuid")),
    )

    sql = f"""
WITH served AS (
    SELECT DISTINCT s AS atom_id
      FROM arac.context_receipts cr
      CROSS JOIN LATERAL unnest(cr.served_ids) s
),
membership AS (
{membership}
),
enriched AS (
    SELECT m.id, m.label, a.id AS atom_id, a.kind, a.scope, a.created_at, a.updated_at,
           a.source_ref->>'conversation_uid' AS uid,
           /* Pourquoi la voie legacy est portée jusqu'ici : la fiche de SCOPE sert
              `atomes_provenance_legacy`, la fiche de PROJET servait
              un `null` nu au même endroit — deux fiches, deux niveaux de détail pour
              la même absence. La distinction n'est pas cosmétique : un atome sans
              conversation_uid MAIS avec curator_raw_id est récupérable (le
              source_path de la capture brute cite le conversation_uid), un atome sans
              ni l'un ni l'autre ne l'est pas. Le geste proposé ne vaut que pour les
              premiers ; les compter, c'est dire combien de la dette est réparable. */
           (a.source_ref ? 'curator_raw_id') AS legacy_source,
           (sv.atom_id IS NULL) AS dormant
      FROM membership m
      JOIN arac.memory_atoms a ON a.id = m.atom_id
      LEFT JOIN served sv ON sv.atom_id = a.id
),
{_CONV_STATUS_CTE.strip().rstrip(',')}
SELECT e.id, e.label,
       count(*)                                              AS atom_count,
       count(*) FILTER (WHERE e.kind = 'decision')            AS decisions,
       count(*) FILTER (WHERE e.kind = 'gotcha')              AS gotchas,
       count(*) FILTER (WHERE e.kind = 'state')               AS states,
       count(*) FILTER (WHERE e.kind = 'reference')           AS references_count,
       count(*) FILTER (WHERE e.dormant)                      AS dormant_count,
       round(100.0 * count(*) FILTER (WHERE e.dormant) / nullif(count(*), 0), 1)
                                                              AS dormant_pct,
       count(DISTINCT e.uid)                                  AS conversation_count,
       /* LE DÉNOMINATEUR DE `conversation_count`. « 557 atomes · 23 conversations »
          se lit comme « 23 conversations ont produit 557 atomes » ; en réalité 292
          des 557 atomes du projet ARAC n'ont AUCUNE origine tracée. La limite
          « 75 pour cent de la provenance est perdue » était oubliée sur la fiche
          projet, exactement là où elle change la lecture du chiffre voisin. */
       count(*) FILTER (WHERE e.uid IS NULL)                  AS atomes_sans_conversation,
       count(*) FILTER (WHERE e.uid IS NULL AND e.legacy_source)
                                                              AS atomes_provenance_legacy,
       count(DISTINCT e.uid) FILTER (WHERE cs.status IN ('pending', 'partial', 'error'))
                                                              AS conversations_waiting,
       count(DISTINCT e.scope)                                AS scope_count,
       max(e.created_at)                                      AS last_activity,
       min(e.created_at)                                      AS first_activity,
       CASE WHEN count(*) = 0 THEN 'vide'
            WHEN count(DISTINCT e.uid) FILTER
                 (WHERE cs.status IN ('pending', 'partial', 'error')) > 0 THEN 'bloqué'
            WHEN max(e.created_at) < now() - (%(dormant_days)s || ' days')::interval
                 THEN 'veille'
            ELSE 'actif' END                                  AS state
  FROM enriched e
  LEFT JOIN conv_status cs ON cs.uid = e.uid
 GROUP BY e.id, e.label
 ORDER BY count(*) DESC
 LIMIT 8"""
    return sql, params


def projects_list() -> dict[str, Any]:
    """Les les projets déclarés : des VUES sur le savoir, pas des dossiers.

    La règle de chaque projet est SERVIE avec ses chiffres — l'interface affiche
    « ce projet regroupe : scope X, scope Y, mot-clé Z » sans jamais l'inventer.
    Un projet vide n'est jamais affiché nu : il porte sa règle et son explication.
    """
    sql, params = _project_stats_sql()
    started = time.perf_counter()
    try:
        with _readonly() as conn:
            rows = _rows(conn, sql, params, where="projects")
            evidence_sql = _sql_text(conn, sql, params)
    except Exception as exc:  # noqa: BLE001
        return _failure("projects", exc) | {"items": []}

    by_id = {r["id"]: r for r in rows}
    items: list[dict[str, Any]] = []
    for p in PROJECTS:
        stats = by_id.get(p["id"])
        entry: dict[str, Any] = {
            "id": p["id"],
            "label": p["label"],
            "rule": _project_rule(p),
            "href": f"{_PREFIX}/projects/{p['id']}",
        }
        if stats is None:
            # Aucune ligne : la règle ne sélectionne rien. On l'annonce avec la
            # règle sous les yeux, et on propose le geste — jamais un projet nu.
            entry |= {
                "state": "vide",
                "atom_count": 0,
                "conversation_count": 0,
                "atomes_sans_conversation": 0,
                "decisions": 0,
                "gotchas": 0,
                "dormant_count": 0,
                "last_activity": None,
                "reason": "la règle de ce projet ne sélectionne aucun atome actif",
                "gesture": "élargir la règle (scopes ou mots-clés) dans config/projects.toml",
            }
        else:
            entry |= {k: v for k, v in stats.items() if k not in ("id", "label")}
        # Le compte de conversations n'est jamais servi seul (règle I2) : cf.
        # provenance_block — sur la liste comme sur la fiche.
        entry["provenance"] = provenance_block(entry.get("atom_count"),
                                               entry.get("atomes_sans_conversation"),
                                               entry.get("atomes_provenance_legacy"))
        items.append(entry)

    return {
        "state": "ok",
        "items": items,
        "count": len(items),
        "decision": ("un projet est une règle de sélection, pas un dossier — "
                     "deux projets peuvent se recouvrir volontairement, et un "
                     "atome appartenir aux deux"),
        "note": None if PROJECTS else NO_PROJECTS_NOTE,
        "states_legend": {
            "actif": f"un atome de moins de {_DORMANT_DAYS} jours",
            "veille": f"dernier atome il y a plus de {_DORMANT_DAYS} jours",
            "bloqué": "au moins une conversation non terminée le concerne",
            "vide": "la règle ne sélectionne aucun atome actif",
        },
        "evidence": {"kind": "sql", "sql": evidence_sql,
                     "label": "les projets, comptés par leur règle",
                     "queries": [evidence_sql]},
        "computed_at": service._now(),
        "duration_ms": service._ms(started),
    }


def project_detail(project_id: str) -> dict[str, Any]:
    """La fiche d'un projet : décisions, pièges, état, références, chronologie."""
    pid = _clean(project_id) or ""
    p = _PROJECT_BY_ID.get(pid)
    if p is None:
        return _unavailable(
            f"aucun projet ne porte l'identifiant {pid!r}"
            if PROJECTS else NO_PROJECTS_NOTE,
            id=pid,
            available=[x["id"] for x in PROJECTS],
        )

    pred, pparams = _project_predicate(p, "a", "sel")
    params: dict[str, Any] = pparams | {
        "slash": _SLASH, "dormant_days": _DORMANT_DAYS, "detail_limit": _DETAIL_LIMIT,
        "per_kind": _PER_KIND,
    }

    members_cte = f"""
WITH served AS (
    SELECT DISTINCT s AS atom_id
      FROM arac.context_receipts cr
      CROSS JOIN LATERAL unnest(cr.served_ids) s
),
members AS (
    SELECT a.id, a.kind, a.scope, a.key, a.status, a.version, a.confidence_score,
           a.tags, a.created_at, a.updated_at, a.supersedes, a.superseded_by,
           a.source_ref->>'conversation_uid' AS uid,
           left(a.value, 200) AS excerpt
      FROM arac.memory_atoms a
     WHERE a.status = 'active' AND {pred}
)
"""

    # Les quatre blocs sont bornés CHACUN, en SQL, par un rang partitionné :
    # une limite globale donnerait 100 décisions et zéro piège sur un gros projet
    # — l'utilisateur croirait qu'il n'y a pas de piège. C'est exactement le
    # mensonge qu'un plafond mal placé fabrique.
    kinds_sql = f"""{members_cte}
SELECT t.kind, t.id, t.scope, t.key, t.created_at, t.updated_at,
       t.confidence_score, t.excerpt, t.uid, t.rank, t.total_of_kind
  FROM (
      SELECT m.*,
             row_number() OVER (PARTITION BY m.kind ORDER BY m.created_at DESC) AS rank,
             count(*)     OVER (PARTITION BY m.kind)                            AS total_of_kind
        FROM members m
       WHERE m.kind IN ('decision', 'gotcha', 'state', 'reference')
  ) t
 WHERE t.rank <= %(per_kind)s
 ORDER BY t.kind, t.created_at DESC
 LIMIT %(detail_limit)s"""

    breakdown_sql = f"""{members_cte}
SELECT m.scope,
       count(*)                                             AS atom_count,
       count(*) FILTER (WHERE sv.atom_id IS NULL)            AS dormant_count,
       round(100.0 * count(*) FILTER (WHERE sv.atom_id IS NULL)
             / nullif(count(*), 0), 1)                       AS dormant_pct,
       max(m.created_at)                                     AS last_atom_at
  FROM members m
  LEFT JOIN served sv ON sv.atom_id = m.id
 GROUP BY m.scope
 ORDER BY count(*) DESC
 LIMIT 40"""

    timeline_sql = f"""{members_cte}
SELECT t.at, t.type, t.label, t.ref
  FROM (
      SELECT m.created_at AS at, 'atome' AS type, m.kind || ' · ' || m.key AS label,
             m.id::text AS ref
        FROM members m
      UNION ALL
      SELECT m.updated_at AS at, 'révision' AS type,
             'version ' || m.version || ' · ' || m.key AS label, m.id::text AS ref
        FROM members m
       WHERE m.version > 1 AND m.updated_at > m.created_at
      UNION ALL
      SELECT c.curated_at AS at, 'conversation' AS type,
             COALESCE(c.title, c.conversation_uid) AS label,
             c.conversation_uid AS ref
        FROM arac.conversations c
       WHERE c.curated_at IS NOT NULL
         AND c.conversation_uid IN (SELECT DISTINCT uid FROM members WHERE uid IS NOT NULL)
  ) t
 WHERE t.at IS NOT NULL
 ORDER BY t.at DESC
 LIMIT 40"""

    conversations_sql = f"""{members_cte.rstrip()},
{_CONV_STATUS_CTE.strip().rstrip(',')}
SELECT c.conversation_uid AS uid, c.title, c.source_type, c.curated_at,
       c.atoms_generated, c.last_curation_error AS error,
       cs.status                               AS status,
       count(m.id)                             AS atoms_here,
       max(m.created_at)                       AS last_atom_at
  FROM members m
  JOIN arac.conversations c ON c.conversation_uid = m.uid
  JOIN conv_status cs ON cs.uid = c.conversation_uid
 GROUP BY c.conversation_uid, c.title, c.source_type, c.curated_at,
          c.atoms_generated, c.last_curation_error, cs.status
 ORDER BY max(m.created_at) DESC
 LIMIT %(detail_limit)s"""

    started = time.perf_counter()
    try:
        with _readonly() as conn:
            stats_sql, stats_params = _project_stats_sql()
            all_stats = _rows(conn, stats_sql, stats_params, where="project.stats")
            stats = next((r for r in all_stats if r["id"] == pid), None)
            kinds = _rows(conn, kinds_sql, params, where="project.kinds")
            breakdown = _rows(conn, breakdown_sql, params, where="project.breakdown")
            timeline = _rows(conn, timeline_sql, params, where="project.timeline")
            conversations = _rows(conn, conversations_sql, params, where="project.conversations")
            evidence_sql = _sql_text(conn, kinds_sql, params)
            queries = [evidence_sql] + [
                _sql_text(conn, s, params)
                for s in (breakdown_sql, timeline_sql, conversations_sql)
            ] + [_sql_text(conn, stats_sql, stats_params)]
            # Le sous-graphe du projet est la promesse la plus visible de cette
            # fiche : elle doit dire ce qui manque VRAIMENT pour l'obtenir.
            links = links_dependency(conn)
    except Exception as exc:  # noqa: BLE001
        return _failure(f"project:{pid}", exc)

    def _pick(kind: str) -> list[dict[str, Any]]:
        return [{k: v for k, v in r.items() if k not in ("kind", "rank", "total_of_kind")}
                for r in kinds if r["kind"] == kind]

    # Ce qui est coupé se dit : un bloc tronqué en silence fait croire que le
    # cerveau n'en sait pas plus.
    blocks = {}
    for kind in ("decision", "gotcha", "state", "reference"):
        rows_of_kind = [r for r in kinds if r["kind"] == kind]
        total_of_kind = rows_of_kind[0]["total_of_kind"] if rows_of_kind else 0
        blocks[kind] = {"shown": len(rows_of_kind), "total": total_of_kind,
                        "truncated": total_of_kind > len(rows_of_kind)}

    header: dict[str, Any] = {"id": p["id"], "label": p["label"], "rule": _project_rule(p)}
    if stats is None:
        header |= {
            "state": "vide",
            "atom_count": 0,
            "reason": "la règle de ce projet ne sélectionne aucun atome actif",
            "gesture": "élargir la règle (scopes ou mots-clés) dans config/projects.toml",
        }
    else:
        header |= {k: v for k, v in stats.items() if k not in ("id", "label")}

    return {
        "state": "ok",
        "header": header,
        # RÈGLE I2 : `conversation_count` ne doit jamais être servi seul. Sur ARAC,
        # « 557 atomes · 23 conversations » laissait déduire une origine à 292 atomes
        # qui n'en ont aucune de tracée.
        "provenance": provenance_block(header.get("atom_count"),
                                       header.get("atomes_sans_conversation"),
                                       header.get("atomes_provenance_legacy")),
        "decisions": _pick("decision"),
        "gotchas": _pick("gotcha"),
        "states": _pick("state"),
        "references": _pick("reference"),
        "blocks": blocks,
        "timeline": timeline,
        "scopes_breakdown": breakdown,
        "conversations": conversations,
        "links": links | {
            "impact": "sous-graphe du projet indisponible",
            "substitute": "répartition par scope + voisinage sémantique atome par atome",
        },
        "evidence": {"kind": "sql", "sql": evidence_sql,
                     "label": "les atomes structurants de ce projet",
                     "queries": queries},
        "computed_at": service._now(),
        "duration_ms": service._ms(started),
    }


# ============================================================================
# Enregistrement des routes — GET uniquement, session + journal de lecture
# ============================================================================


def register(
    a: FastAPI,
    session_api: Callable[..., Any],
    audit_read_log: Callable[[str, str], Any],
) -> None:
    """Enregistre les routes de navigation ``/cc/v1/*`` sur l'application.

    Args:
        a: l'instance FastAPI du Control Center.
        session_api: la dépendance de session en mode API (401 JSON si absente).
        audit_read_log: le journal de lecture du socle (chemin, principal).
    """

    @a.get(f"{_PREFIX}/conversations")
    def cc_v1_conversations(
        principal: dict = Depends(session_api),
        limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        offset: int = Query(default=0, ge=0),
        status: str | None = Query(default=None, max_length=32),
        source: str | None = Query(default=None, max_length=64),
        q: str | None = Query(default=None, max_length=200),
        order: str = Query(default="content_date", max_length=32),
    ) -> JSONResponse:
        """La file des conversations : statut dérivé, chaîne de vie, rang de file.

        Le statut n'est pas stocké : il est DÉRIVÉ en SQL du curseur de curation
        et du dernier message. Aucun agent n'a besoin de le tenir à jour, donc
        aucun agent ne peut le laisser mentir.
        """
        audit_read_log(f"{_PREFIX}/conversations", principal.get("sub", "?"))
        return JSONResponse(conversations_list(limit=limit, offset=offset, status=status,
                                               source=source, q=q, order=order))

    @a.get(f"{_PREFIX}/conversations/{{uid}}")
    def cc_v1_conversation(uid: str, principal: dict = Depends(session_api)) -> JSONResponse:
        """Une conversation : ce qu'elle a produit, rejeté, coûté.

        Un identifiant inconnu ne lève pas : il rend ``state='unavailable'`` avec
        sa raison ET la requête qui n'a rien trouvé.
        """
        audit_read_log(f"{_PREFIX}/conversations/{uid}", principal.get("sub", "?"))
        return JSONResponse(conversation_detail(uid))

    @a.get(f"{_PREFIX}/atoms")
    def cc_v1_atoms(
        principal: dict = Depends(session_api),
        limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        offset: int = Query(default=0, ge=0),
        scope: str | None = Query(default=None, max_length=200),
        scope_prefix: str | None = Query(default=None, max_length=200),
        kind: str | None = Query(default=None, max_length=64),
        status: str | None = Query(default="active", max_length=32),
        view: str | None = Query(default=None, max_length=32),
        q: str | None = Query(default=None, max_length=200),
        order: str = Query(default="created_at", max_length=32),
    ) -> JSONResponse:
        """Les atomes, selon 9 vues déclarées côté serveur.

        Ni la valeur complète ni le plongement ne sortent d'ici : un extrait de
        200 caractères, découpé en SQL, suffit à choisir.
        """
        audit_read_log(f"{_PREFIX}/atoms", principal.get("sub", "?"))
        return JSONResponse(atoms_list(limit=limit, offset=offset, scope=scope,
                                       scope_prefix=scope_prefix, kind=kind, status=status,
                                       view=view, q=q, order=order))

    @a.get(f"{_PREFIX}/atoms/{{atom_id}}")
    def cc_v1_atom(atom_id: str, principal: dict = Depends(session_api)) -> JSONResponse:
        """Un atome : identité, contenu, lignée, voisins sémantiques, usage réel."""
        audit_read_log(f"{_PREFIX}/atoms/{atom_id}", principal.get("sub", "?"))
        return JSONResponse(atom_detail(atom_id))

    @a.get(f"{_PREFIX}/scopes")
    def cc_v1_scopes(
        principal: dict = Depends(session_api),
        limit: int = Query(default=MAX_LIMIT, ge=1, le=MAX_LIMIT),
    ) -> JSONResponse:
        """L'arbre des scopes : poids, part dormante, dette de racine."""
        audit_read_log(f"{_PREFIX}/scopes", principal.get("sub", "?"))
        return JSONResponse(scopes_list(limit=limit))

    @a.get(f"{_PREFIX}/projects")
    def cc_v1_projects(principal: dict = Depends(session_api)) -> JSONResponse:
        """Les les projets déclarés, avec la règle qui les compose — jamais codée côté client."""
        audit_read_log(f"{_PREFIX}/projects", principal.get("sub", "?"))
        return JSONResponse(projects_list())

    @a.get(f"{_PREFIX}/projects/{{project_id}}")
    def cc_v1_project(project_id: str, principal: dict = Depends(session_api)) -> JSONResponse:
        """La fiche d'un projet : décisions, pièges, état, chronologie, conversations."""
        audit_read_log(f"{_PREFIX}/projects/{project_id}", principal.get("sub", "?"))
        return JSONResponse(project_detail(project_id))
