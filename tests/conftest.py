"""Fixtures pytest partagées — Phase 2.3+.

Stratégie :
- Init pool DB une fois par test (overhead ~50ms acceptable pour ~10 tests)
- Cleanup via `key LIKE 'test-%'` avant ET après chaque test
- TestClient async via httpx.AsyncClient + ASGITransport (lifespan FastAPI
  géré manuellement par les fixtures, pas par AsyncClient)
- mock_embed pour mocker app.routers.atoms.embed (économie API + latence)

Doctrine du soft-delete : `arac_app` n'a PAS le grant DELETE — c'est
intentionnel (soft-delete only en prod). Le cleanup tests doit donc utiliser
une connexion ad-hoc avec `DATABASE_URL_ADMIN` (hors flux applicatif, légitime
côté admin tests).

Règle : les tests utilisent la DB `arac` réelle avec les
nodes seedés Phase 1b.6 (FK valides). L'option de DB de test isolée `arac_test`
est tracée comme migration possible Phase 2.6 si besoin.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock

import psycopg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_TEST_KEY_PATTERN = "test-%"
_TEST_TOPIC_PATTERN = "test-%"


# ============================================================================
# LES DEUX GARDES, POSÉS AVANT TOUT LE RESTE
# ============================================================================
#
# Ils sont posés ICI, à l'import du conftest racine, c'est-à-dire avant
# l'import du code testé (`from app import db, main`, plus bas) et avant le
# premier test. Un garde posé dans une fixture arrive après ce qu'il devait
# empêcher.
#
# Ce qu'ils font, et pourquoi, est écrit dans `tests/garde_hermetique.py`.
# En deux lignes :
#   - aucune socket TCP ne sort du processus. `make test` émettait de vrais
#     GET vers http://127.0.0.1:8000 — l'API de PRODUCTION sur la machine de
#     l'auteur — par le repli codé en dur du collecteur du cockpit ;
#   - aucune connexion ne s'ouvre sur une base qui ne porte pas la MARQUE de
#     base de test. L'ancien garde refusait un NOM (`arac`, le cerveau de
#     l'auteur) et laissait donc passer `camille_brain`, `nadia_brain`, le
#     cerveau de tout autre utilisateur.

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.garde_hermetique import (  # noqa: E402
    RefusHermetique,  # noqa: F401  — réexporté : les tests du garde l'importent d'ici
    controle_des_dsn_de_session,
    installer_les_gardes,
    nom_de_base,
)

installer_les_gardes()

# ============================================================================
# LA SECONDE BARRIÈRE — celle qui rend une évasion SANS EFFET
# ============================================================================
#
# Les gardes ci-dessus sont une PORTE, et on sait qu'elle a des mailles : quatre
# manches l'ont montré, chaque fois de la même façon — fermée là où on a
# regardé, ouverte juste à côté. `ZONES_NON_COUVERTES_DE_LA_PORTE` le déclare
# depuis le début : « toutes ces évasions n'atteignent un cerveau réel que parce
# que le processus en a le DROIT ». C'était un constat ; ceci en fait un
# dispositif.
#
# Landlock retire au NOYAU — pour cette session et pour toute sa descendance,
# irréversiblement — le droit de toucher un fichier hors du périmètre que le
# rideau de lecture déclare déjà. Une évasion qu'on n'a pas trouvée devient donc
# sans effet : `head`, `rm -rf`, un chemin calculé, `ctypes.CDLL("libc.so.6")`
# et le binaire statique qu'on n'a pas prévu échouent tous dans le noyau.
#
# Elle ne peut rien casser d'autre que nous : Landlock RETIRE des droits au
# processus appelant, jamais à un autre. C'est ce qui la distingue d'un espace
# de noms de montage, où une propagation mal maîtrisée masquerait `/etc/arac`
# pour l'API de PRODUCTION.
#
# Le verdict est gardé pour la fin de session : une barrière qu'on ne mesure pas
# est un espoir, et une barrière absente doit s'annoncer.
from tests.seconde_barriere import poser_depuis_le_garde  # noqa: E402

VERDICT_DE_LA_SECONDE_BARRIERE = poser_depuis_le_garde()

# ============================================================================
# LE MOUCHARD DES CHEMINS EMPRUNTÉS — posé ici, donc avant la première app
# ============================================================================
#
# Il ne garde rien et n'interdit rien : il NOTE quelles fonctions de route ont
# été exécutées pendant la session, et le compte rendu de fin de session le dit.
#
# Il existe parce que la ligne verte de ce dépôt a été satisfaite par une
# livraison cassée : deux routes servies rendaient 500 pendant que la suite
# affichait 5266 verts et que le harnais d'acceptation rendait « 0 en échec ».
# Ni l'un ni l'autre n'était en tort sur ses assertions — ils n'étaient jamais
# passés par là. Un compte de tests ne dit pas ce qui a été EXÉCUTÉ ; ce
# mouchard, si. Cf. `tests/parcours.py`.
from tests.parcours import poser_le_mouchard  # noqa: E402

poser_le_mouchard()


# ============================================================================
# Le dépôt, vu depuis les tests
# ============================================================================
#
# Aucun chemin absolu ici : la suite doit tourner sur la machine de n'importe
# qui, y compris sans installation. `ARAC_HOME` est posée sur le dépôt lui-même
# pour que le code testé résolve ses chemins sans dépendre du répertoire
# courant ni d'un service installé.

_REPO_ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("ARAC_HOME", str(_REPO_ROOT))

# L'identité du cerveau : celle de l'utilisateur si elle existe, sinon une
# identité d'ESSAI, visiblement synthétique. La suite ne doit dépendre ni
# d'une installation, ni du nom de machine de qui que ce soit.
#
# `setdefault` et non `environ[...]` : si quelqu'un lance la suite avec sa
# propre identité posée, on la respecte.
try:
    import arac_runtime as _rt

    _rt.node_id()
except Exception:
    os.environ.setdefault("ARAC_NODE_ID", "test-node")
    os.environ.setdefault("ARAC_BRAIN_NAME", "cerveau-de-test")
    os.environ.setdefault("ARAC_BRAIN_OWNER", "alice")

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ============================================================================
# SOUS QUEL CERVEAU LES MIGRATIONS TOURNENT-ELLES, SANS BASE ?
# ============================================================================
#
# Les migrations ne nomment plus leurs rôles : elles les DÉDUISENT du rôle
# d'administration sous lequel elles tournent (`db/alembic/roles.py`). C'est ce
# qui interdit qu'une migration donne des droits aux rôles d'un autre cerveau —
# il faudrait pour cela s'être connecté avec l'identité de cet autre cerveau.
#
# Cette suite, elle, est HERMÉTIQUE : pas de base, donc pas de connexion, donc
# aucun rôle d'administration à interroger. Plusieurs tests exécutent pourtant
# `upgrade()` avec un `op.execute` détourné, pour LIRE le SQL produit. Il faut
# donc leur dire de quel cerveau il s'agit — et `roles_arac()` n'invente jamais
# rien : ne pas savoir est, chez elle, une raison de lever une exception.
#
# On pose le préfixe de l'installation de référence, celui sur lequel les
# assertions existantes portent. Ce n'est pas un trou dans le garde : que les
# migrations DÉDUISENT correctement est éprouvé ailleurs, sans cette variable
# (tests/test_g2_le_bootstrap_ne_prend_pas_le_role_du_voisin.py), et qu'aucune
# ne nomme un rôle en dur est vérifié sur les SOURCES, où cette variable
# n'entre pas en jeu.
os.environ.setdefault("ARAC_ROLE_PREFIX", "arac")


# ============================================================================
# Une taxonomie pour les tests — engendrée, jamais héritée
# ============================================================================
#
# `app/schemas/scope_generated.py` naît des réponses de l'utilisateur : il
# n'est PAS versionné. Sur un dépôt fraîchement cloné, il n'existe donc pas,
# et rien ne s'importerait.
#
# Plutôt que d'en committer un — ce qui reviendrait à faire hériter le premier
# venu de la taxonomie de quelqu'un d'autre — on l'ENGENDRE ici depuis le
# modèle commenté (`config/scopes.example.toml`), avec le générateur réel.
#
# Deux bénéfices, un seul mécanisme :
#   - `make test` marche immédiatement après un `git clone`, sans installer
#     quoi que ce soit. C'est ce qui permet de vérifier une modification sans
#     rien déployer.
#   - le générateur est exercé par la suite elle-même, à chaque exécution.
#
# Si l'utilisateur a DÉJÀ sa taxonomie, on n'y touche pas : la sienne prime.

_GENERATED_ENUM = _REPO_ROOT / "app" / "schemas" / "scope_generated.py"

if not _GENERATED_ENUM.exists():
    import subprocess

    _example = _REPO_ROOT / "config" / "scopes.example.toml"
    _config = _REPO_ROOT / "config" / "scopes.toml"
    _source = _config if _config.exists() else _example
    subprocess.run(
        [sys.executable, str(_REPO_ROOT / "bootstrap" / "generate_scopes.py"),
         "--config", str(_source),
         "--enum-out", str(_GENERATED_ENUM),
         "--sql-out", str(_REPO_ROOT / "db" / "seeds" / "scopes.sql")],
        check=True, capture_output=True,
    )


# L'API n'est importable qu'une fois la taxonomie présente : son rempart de
# validation EST l'énumération engendrée ci-dessus.
from app import auth, db, main  # noqa: E402


# Flags de FIDÉLITÉ du cortex (chantier fidélité A+B+C) — lus en env PUR à
# chaque appel dans `agents/cortex/contract.py`. Sans neutralisation, le
# résultat de la suite DÉPEND du shell qui la lance : une fois les flags armés
# en prod (systemd) ou dans un shell d'opérateur, les tests qui affirment le
# comportement de `main` (ex. `test_cortex_contract::test_validate_run_ref_
# falsifie`) échouent alors que RIEN n'a changé dans le code. Le gate doit
# prouver « OFF = bit-identique » indépendamment de l'environnement : on force
# donc l'état OFF par défaut, et tout test qui veut le comportement ARMÉ le
# déclare EXPLICITEMENT (`monkeypatch.setenv`, appliqué après cette fixture).
_CORTEX_FIDELITY_FLAGS = (
    "ARAC_CORTEX_RUNREF_LENIENT",
    "ARAC_CORTEX_EMPTY_DROP_TOLERANT",
    "ARAC_CORTEX_UID_NEARMATCH",
    "ARAC_CORTEX_DEDUP_UID_STRICT",
    # Vérification finale A+B (2026-07-20) — la neutralisation ci-dessus ne
    # couvrait QUE les 4 flags du chantier fidélité, alors que le défaut
    # d'hermétisme visé par le finding R2 est GÉNÉRIQUE. Mesure : avec le seul
    # `ARAC_DISPOSE_COVERAGE_V2=1` — c'est-à-dire l'état RÉEL de la prod
    # (`$ARAC_HOME/.env`) — le gate rend `7 failed` (6 échecs
    # PRÉEXISTANTS sur `main` 67e1e56, mesurés sur worktree propre, + 1 échec
    # NOUVEAU introduit par ce chantier :
    # `test_verif_round1_abc::test_VF1_ref_le_doublon_existe_DEJA_flags_OFF`).
    # Autrement dit : un opérateur qui sourçait `.env` avant `make test` voyait
    # un gate ROUGE sans qu'aucune ligne de code n'ait bougé — exactement le
    # mode de panne que R2 devait fermer. Ces deux flags gouvernent des chemins
    # dont la suite affirme le comportement OFF ; les tests qui veulent l'état
    # ARMÉ le déclarent déjà EXPLICITEMENT par `monkeypatch.setenv` (appliqué
    # APRÈS cette fixture autouse), donc la neutralisation par défaut reproduit
    # à l'identique le gate de référence (2877 passed) et le rend
    # ENV-INDÉPENDANT.
    # La liste est celle, CANONIQUE, des flags BOOLÉENS de comportement que le
    # cortex logge lui-même à chaque run (`agents/cortex/cycle.py::
    # _OBSERVED_FLAGS`) : c'est la définition maison de « ce qui change le
    # comportement sans changer le code ». Mesure de la dépendance résiduelle,
    # tous flags armés : 9 échecs (dont `test_stab_wave2::test_drop_empty_head_
    # report_semantics_unchanged` et `::test_fully_presented_false_when_budget_
    # truncates` via les flags de pack). Neutralisés, le gate rend le MÊME
    # résultat sous `env -i` et sous un shell qui a sourcé `.env` prod.
    "ARAC_DISPOSE_COVERAGE_V2",
    "ARAC_PACK_DROP_EMPTY",
    "ARAC_PACK_STRICT_BOUNDARIES",
    "ARAC_PACK_SOURCE_FAIR",
    "ARAC_PACK_FILL_FLOOR",
    "ARAC_VALUE_GATE_SHADOW",
    "ARAC_CORTEX_FORCE_MANUAL",
)


@pytest.fixture(autouse=True)
def _cortex_fidelity_flags_off(monkeypatch):
    """Défaut OFF pour les flags de fidélité — hermétise la suite vis-à-vis de
    l'environnement (cf. bloc ci-dessus). Les tests armés font `setenv`."""
    for name in _CORTEX_FIDELITY_FLAGS:
        monkeypatch.delenv(name, raising=False)


#: Conservé sous son ancien nom pour les appelants ; il ne DÉCIDE plus rien —
#: il ne sert qu'à nommer la base dans un message. C'est le nom qui a menti.
_db_name = nom_de_base


def _admin_dsn_or_raise() -> str:
    """Lit DATABASE_URL_ADMIN ou raise (soft-delete : cleanup tests via admin).

    Il n'y a plus de contrôle de NOM ici. Le contrôle a lieu là où il ne peut
    pas être contourné : à l'ouverture de la connexion (`garde_hermetique`),
    qui demande à la base elle-même si elle porte la marque de base de test.
    Un test qui ouvre sa connexion à la main — 0006, 0007, 0008, bus — est
    couvert au même titre que ceux qui passent par les fixtures, ce qui
    n'était pas le cas avant.
    """
    admin_dsn = os.environ.get("DATABASE_URL_ADMIN")
    if not admin_dsn:
        raise RuntimeError(
            "DATABASE_URL_ADMIN non définie — cleanup tests impossible. "
            "Lance pytest via une DB de test (`make test`) ou `source .env.test`."
        )
    return admin_dsn


def pytest_configure(config):
    """Refuse la session AVANT le moindre test si un DSN vise un cerveau vivant.

    Ce hook est une COURTOISIE, pas la serrure : il dit tout de suite ce qui ne
    va pas, plutôt que de laisser vingt tests se planter un par un. La serrure,
    elle, est dans `garde_hermetique.installer_les_gardes()` — posée à l'import
    de ce fichier, elle interdit l'ouverture même d'une connexion vers une base
    non marquée, quel que soit le chemin de code qui la demande.

    Une base injoignable ne fait PAS échouer la session : la promesse du dépôt
    est qu'un test rouge veut dire « le code est cassé », jamais « PostgreSQL
    n'est pas lancé ».
    """
    refus = controle_des_dsn_de_session()
    if refus:
        raise pytest.UsageError("\n\n".join(refus))


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Dit à voix haute ce que les gardes ont arrêté.

    Sans cette ligne, l'hermétisme serait muet : le collecteur du cockpit avale
    toutes les exceptions (« résilience volontaire »), donc un GET refusé vers
    l'API de production ne laisserait aucune trace. On saurait que la suite est
    verte ; on ne saurait pas qu'elle a essayé de sortir.
    """
    from tests import garde_hermetique as _g

    if _g.TENTATIVES_RESEAU:
        terminalreporter.write_sep("-", "hermétisme : sorties réseau REFUSÉES")
        for ou in _g.TENTATIVES_RESEAU:
            terminalreporter.write_line(f"  {ou}")
        terminalreporter.write_line(
            "  Aucun paquet n'est sorti. Le code testé retombe sur son chemin "
            "d'indisponibilité — ce qui est l'état d'un dépôt fraîchement cloné."
        )
    if _g.TENTATIVES_MACHINE:
        terminalreporter.write_sep("-", "hermétisme : commandes MACHINE refusées")
        for binaire in _g.TENTATIVES_MACHINE:
            terminalreporter.write_line(f"  {binaire}")
        terminalreporter.write_line(
            "  La suite lit le dépôt ; elle n'interroge pas l'hôte. Le code "
            "appelant retombe sur son chemin d'indisponibilité."
        )
    descendants = _g.refus_des_descendants()
    if descendants:
        terminalreporter.write_sep(
            "-", "hermétisme : commandes refusées DANS UN SOUS-PROCESSUS")
        for binaire in descendants:
            terminalreporter.write_line(f"  {binaire}")
        terminalreporter.write_line(
            "  Ces appels ne venaient pas de pytest : ils venaient d'un script "
            "lancé par un test. Le PATH de refus les a arrêtés avant l'hôte — "
            "c'est par là que « sudo -u postgres psql -p 5432 » atteignait le "
            "cluster de PRODUCTION pendant un simple « make test »."
        )
    if _g.TENTATIVES_LECTURE:
        terminalreporter.write_sep("-", "hermétisme : LECTURES de l'hôte refusées")
        for chemin in _g.TENTATIVES_LECTURE:
            terminalreporter.write_line(f"  {chemin}")
        terminalreporter.write_line(
            "  La suite lit le dépôt. Un fichier de l'hôte n'a pas été ouvert — "
            "et ce rideau-là est le second : le jeton d'un cerveau voisin vit "
            "dans un fichier, et qui le lit n'a plus besoin ni de `psql`, ni de "
            "`sudo`, ni d'un chemin calculé."
        )
    if _g.TENTATIVES_BASE:
        terminalreporter.write_sep("-", "bases NON MARQUÉES refusées")
        for base in _g.TENTATIVES_BASE:
            terminalreporter.write_line(f"  {base}")
    _g.demonter_l_heritage()

    # LE RECENSEMENT DES CHEMINS LIVRÉS — ce que le vert prouve, et sur quoi il
    # se tait. Il est imprimé le premier parce qu'il répond à la question que le
    # lecteur se pose devant une ligne verte : « verte SUR QUOI ? ».
    from tests import parcours as _p

    terminalreporter.write_sep(
        "-", "CE QUE CETTE SESSION A RÉELLEMENT EMPRUNTÉ")
    for ligne in _p.compte_rendu():
        terminalreporter.write_line("  " + ligne)

    # LA PORTE DU SOUS-PROCESSUS — ce qu'elle NE ferme pas.
    #
    # Ce bloc est placé AVANT ceux de G1, G3 et G4 délibérément : les trois
    # suivants s'interrompent par un `return` si leur module n'a pas été
    # collecté (`-k`, `--deselect`, un fichier désélectionné), et l'aveu qui
    # vient après un `return` est un aveu qu'on ne lit jamais. Celui-ci porte
    # sur le garde qui protège la BASE de production : il passe en premier.
    #
    # Il imprime aussi l'`uid` effectif, et ce n'est pas une décoration. Toutes
    # les évasions que ce garde ne peut pas fermer — un chemin calculé, la libc
    # appelée directement, la lecture d'un fichier — n'atteignent un cerveau
    # réel que parce que le processus en a le DROIT. Un garde en espace
    # utilisateur rend une évasion visible et coûteuse ; il ne la rend pas
    # impossible. Le compte, lui, la rend sans effet.
    try:
        from tests.test_la_porte_du_sous_processus_est_fermee import (
            ZONES_NON_COUVERTES_DE_LA_PORTE,
        )
    except Exception:  # pragma: no cover — le fichier de la porte est désélectionné
        pass
    else:
        terminalreporter.write_sep(
            "-", "LA PORTE DU SOUS-PROCESSUS : CE QU'ELLE NE FERME PAS")
        for z in ZONES_NON_COUVERTES_DE_LA_PORTE:
            terminalreporter.write_line(f"  · {z.zone}")
            if z.instance:
                terminalreporter.write_line(f"      instance vivante : {z.instance}")
        import os as _os

        uid = _os.geteuid()
        qui = "root" if uid == 0 else f"uid {uid}"
        terminalreporter.write_line(
            f"  SECONDE BARRIÈRE : {VERDICT_DE_LA_SECONDE_BARRIERE}")
        terminalreporter.write_line(
            f"  Cette session a tourné sous {qui}. "
            + ("Sous root, `sudo -n -u postgres psql` ne demande rien à "
               "personne. La seconde barrière ci-dessus ferme les FICHIERS — "
               "le coffre et la sauvegarde d'un voisin — pour toute la "
               "descendance ; elle ne ferme ni la base, ni les services. Ce "
               "qui reste demande un compte ordinaire."
               if uid == 0 else
               "Un compte ordinaire est la seconde barrière : `sudo` échoue "
               "avant de commencer, et l'authentification `peer` du cluster "
               "fait le reste.")
        )

    # LE GARDE DU JETON — il lit du TEXTE, et il doit le dire. Quatre gardes de
    # ce dépôt impriment leurs zones aveugles ; celui-ci n'en déclarait aucune,
    # et il en a trois. Un garde de forme qui ne dit pas qu'il est un garde de
    # forme se fait croire complet.
    try:
        from tests.test_tout_appelant_porte_son_jeton import (
            ZONES_NON_COUVERTES_DU_JETON,
        )
    except Exception:  # pragma: no cover — le fichier du jeton est désélectionné
        pass
    else:
        terminalreporter.write_sep(
            "-", "LE GARDE DU JETON : CE QU'IL NE COUVRE PAS")
        for z in ZONES_NON_COUVERTES_DU_JETON:
            terminalreporter.write_line(f"  · {z.zone}")
        terminalreporter.write_line(
            "  Ce garde exige `headers=` sur tout appel qui vise `/v1/` ou "
            "`/cc/` de ce cerveau. Il lit du texte : une URL composée dans un "
            "AUTRE fichier lui échappe encore."
        )

    # G1 a changé de principe : il cherche des FORMES, plus des noms. Il trouve
    # donc des fautes que personne n'avait listées, dans des fichiers dont le
    # périmètre appartient à quelqu'un d'autre. Elles sont REMISES, pas
    # dispensées — et une remise qui ne se lit pas est une dispense déguisée.
    # CE BLOC AFFIRMAIT CE QU'IL N'AVAIT PAS MESURÉ, et c'est la faute que ce
    # dépôt s'interdit partout ailleurs (« un 200 ne prouve rien tant qu'on ne
    # sait pas QUI répond »). Il parcourait `CONSTATS_REMIS` et proclamait
    # « ces noms sont FIGÉS » sans jamais consulter le balayage : six des
    # soixante-trois étaient réparés, dont le bloquant de la manche précédente.
    # Un rapport faux à dix pour cent apprend à ne plus lire le rapport.
    # Il n'imprime plus que ce que `constats_mesures()` a CONSTATÉ.
    try:
        from tests.test_g1_aucun_nom_partage_entre_cerveaux import (
            ZONES_NON_COUVERTES, constats_mesures,
        )
        figes, reparees = constats_mesures()
    except Exception:  # pragma: no cover — G1 désélectionné
        return
    if figes:
        terminalreporter.write_sep(
            "-", "G1 : noms partagés entre cerveaux — CONSTATÉS ENCORE FIGÉS")
        par_qui: dict[str, list[str]] = {}
        from tests.test_g1_aucun_nom_partage_entre_cerveaux import CONSTATS_REMIS
        a_qui_de = {(r.fichier, r.motif): r.a_qui for r in CONSTATS_REMIS}
        for fichier, motif, litteral in figes:
            par_qui.setdefault(a_qui_de.get((fichier, motif), "?"), []).append(
                f"{fichier} [{motif}] {litteral}")
        for a_qui in sorted(par_qui):
            terminalreporter.write_line(f"  → {a_qui}")
            for ligne in sorted(set(par_qui[a_qui])):
                terminalreporter.write_line(f"      {ligne}")
        terminalreporter.write_line(
            f"  {len(figes)} littéraux, RENCONTRÉS par le balayage de cette "
            "session — pas récités d'une liste. Deux cerveaux sur une même "
            "machine se les disputent. Ils sont hors du périmètre de la manche "
            "qui a refait le garde ; chacun porte son dégât dans "
            "CONSTATS_REMIS. Un vert ne veut donc pas dire « il n'y a rien à "
            "faire »."
        )
    if reparees:  # pragma: no cover — dépend de l'état du dépôt
        terminalreporter.write_sep(
            "-", "G1 : RÉPARÉS — à retirer de CONSTATS_REMIS")
        for fichier, motif, litteral in sorted(reparees):
            terminalreporter.write_line(f"      {fichier} [{motif}] {litteral}")
    if ZONES_NON_COUVERTES:
        terminalreporter.write_sep(
            "-", "G1 : CE QUE LE GARDE NE COUVRE PAS")
        for z in ZONES_NON_COUVERTES:
            suite = f"  (exemple réel : {z.exemple})" if z.exemple else ""
            terminalreporter.write_line(f"  · {z.zone}{suite}")
        terminalreporter.write_line(
            "  Un garde qui ment sur sa couverture est pire qu'un garde "
            "absent : il donne confiance, et la confiance est ce qui empêche "
            "de regarder. Le détail de chaque zone est dans "
            "ZONES_NON_COUVERTES."
        )

    # G3 — la grappe donnée par OMISSION. Il déclare ses limites comme G1, et
    # pour la même raison : la seule chose qu'un garde ne doit jamais laisser
    # croire, c'est qu'il voit tout.
    try:
        from tests.test_g3_toute_commande_imprimee_porte_son_port import (
            ZONES_NON_COUVERTES_G3,
        )
    except Exception:  # pragma: no cover — G3 désélectionné
        return
    terminalreporter.write_sep(
        "-", "G3 : CE QUE LE GARDE DES COMMANDES IMPRIMÉES NE COUVRE PAS")
    for z in ZONES_NON_COUVERTES_G3:
        terminalreporter.write_line(f"  · {z.zone}")
    terminalreporter.write_line(
        "  G3 exige qu'une commande libpq IMPRIMÉE porte le port de sa "
        "grappe. Il ne dit rien de celles qu'un humain compose lui-même à "
        "trois heures du matin : contre celles-là, le seul recours est que "
        "tout ce qu'il a sous les yeux porte l'exemple juste."
    )

    # G4 — le geste prescrit par un texte que le PRODUIT imprime. Même raison,
    # troisième fois : ce garde-ci lit l'écran de fin de l'installation, que
    # personne ne peut sauter, et sa vue s'arrête quelque part.
    try:
        from tests.test_g4_tout_geste_prescrit_est_servi import (
            ZONES_NON_COUVERTES_G4,
        )
    except Exception:  # pragma: no cover — G4 désélectionné
        return
    terminalreporter.write_sep(
        "-", "G4 : CE QUE LE GARDE DES GESTES PRESCRITS NE COUVRE PAS")
    for z in ZONES_NON_COUVERTES_G4:
        terminalreporter.write_line(f"  · {z.zone}")
    terminalreporter.write_line(
        "  G4 exige qu'un geste PRESCRIT par un texte imprimé tombe sur une "
        "capacité réelle — une route, une commande, un fichier. Il répond "
        "« cet organe existe-t-il ? », jamais « fait-il ce que la phrase "
        "promet ? » : cette seconde question se joue sur un cerveau réel, "
        "dans `make acceptance`."
    )


async def _cleanup_test_atoms() -> None:
    """Supprime les atomes dont la `key` commence par `test-`.

    Utilise DATABASE_URL_ADMIN (connexion ad-hoc, pas le pool app) car
    `arac_app` n'a délibérément pas DELETE sur les tables `arac.*` (soft-delete :
    doctrine soft-delete intentionnelle). Le cleanup tests est de l'admin
    tests, hors flux applicatif — légitime via `arac_admin`.
    """
    admin_dsn = _admin_dsn_or_raise()
    async with await psycopg.AsyncConnection.connect(
        admin_dsn, autocommit=True
    ) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM arac.memory_atoms WHERE key LIKE %s",
                (_TEST_KEY_PATTERN,),
            )


async def _cleanup_test_sessions() -> None:
    """Supprime les sessions dont le `topic` commence par `test-`.

    `ON DELETE CASCADE` sur `session_buffer.session_id` purge automatiquement
    les buffer events associés (Q.G Phase 2.4).
    """
    admin_dsn = _admin_dsn_or_raise()
    async with await psycopg.AsyncConnection.connect(
        admin_dsn, autocommit=True
    ) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM arac.sessions WHERE topic LIKE %s",
                (_TEST_TOPIC_PATTERN,),
            )


@pytest_asyncio.fixture
async def initialized_pool():
    """Init pool DB + cleanup atomes test-* + sessions test-* avant et après.

    Note ordre : on cleanup sessions AVANT atomes pour respecter la FK
    `memory_atoms.session_id` (ON DELETE SET NULL — pas bloquant mais propre).
    """
    # Le garde de connexion (garde_hermetique) refuse déjà toute base non
    # marquée, y compris celles qu'ouvre le pool applicatif : il n'y a plus de
    # contrôle à répéter ici, et surtout plus de contrôle à OUBLIER ailleurs.
    await db.init_pool()
    await _cleanup_test_sessions()
    await _cleanup_test_atoms()
    try:
        yield
    finally:
        await _cleanup_test_sessions()
        await _cleanup_test_atoms()
        await db.close_pool()


#: LE POSTE ET LE JETON DE LA SUITE.
#:
#: Ils existent parce que le contrat a changé sous les tests : depuis que
#: `app/auth.py` exige le jeton de TOUTE requête — `127.0.0.1` compris — un
#: client sans en-tête `Authorization` ne parle plus à l'API, il se fait
#: refuser par le middleware AVANT d'atteindre la moindre route.
#:
#: Ce fait n'a été vu nulle part, et la raison mérite d'être écrite : les 106
#: tests qui passent par la fixture `client` exigent une base, donc ils sont
#: TOUS `skipped` dans `make test`. Un contrat inversé sous 106 tests
#: endormis rend exactement le même vert qu'un contrat respecté. C'est la même
#: leçon que le canari de `test_dashboard_ingest.py`, à l'échelle de la suite.
#:
#: Le jeton fait 64 caractères parce que `load_tokens_from_env` refuse en
#: dessous de 32 — un garde qu'on est content de rencontrer ici.
NODE_DE_TEST = "poste-de-test"
JETON_DE_TEST = "t" * 64


@pytest_asyncio.fixture
async def client(initialized_pool, monkeypatch) -> AsyncIterator[AsyncClient]:
    """TestClient async pour FastAPI app — AVEC son jeton, comme tout appelant.

    Note : on utilise ASGITransport directement, lifespan startup/shutdown
    n'est PAS automatique avec AsyncClient. C'est OK — `initialized_pool`
    fixture gère explicitement init/close. Setup logging via lifespan startup
    n'est pas non plus déclenché ; les loggers `arac.*` n'ont pas de handler
    en tests, ce qui est désirable (logs des tests sont silencieux).

    LE JETON EST DÉCLARÉ ICI, PAS DANS CHAQUE TEST. C'est la même règle que
    `app/api_token.py` applique aux onze appelants du produit : un seul
    endroit où l'on va chercher le jeton, sinon c'est onze occasions
    d'oublier. Un test qui veut éprouver la PORTE (le refus sans jeton) se
    construit son propre client — voir `tests/test_dashboard_ingest.py`, dont
    c'est précisément le sujet.

    Le cache de jetons est vidé des deux côtés : il est chargé une fois par
    processus, et un cache peuplé par un autre test rendrait celui-ci
    dépendant de l'ordre de collecte.
    """
    monkeypatch.setenv("ARAC_NODE_TOKEN_POSTE_DE_TEST", JETON_DE_TEST)
    auth._tokens_cache = None
    transport = ASGITransport(app=main.app)
    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {JETON_DE_TEST}"},
        ) as c:
            yield c
    finally:
        auth._tokens_cache = None


@pytest.fixture
def mock_embed(monkeypatch):
    """Mock `embed` → fake 3072 floats déterministes (patch dans tous les routers
    qui l'importent : atoms et sessions Phase 2.4+).

    Utilisé par défaut pour tous les tests routers (économie API + latence).
    Les seuls tests qui n'utilisent PAS ce mock sont les `@pytest.mark.live_api`
    (skip par défaut via pytest.ini).

    Note Phase 2.4 : on doit patcher CHAQUE module qui fait
    `from app.services.embeddings import embed` — un patch sur le module
    source n'atteint pas les copies dans les modules consommateurs.
    """
    fake_embedding = [0.001 * i for i in range(3072)]
    mock = AsyncMock(return_value=fake_embedding)
    monkeypatch.setattr("app.routers.atoms.embed", mock)
    monkeypatch.setattr("app.routers.sessions.embed", mock)
    return mock


# ============================================================================
# Fixtures DB test container (Bloc 2b — v0.4)
#
# Ces fixtures sont indépendantes de `initialized_pool` / `client`. Elles
# ciblent les tests qui doivent parler à la DB éphémère lancée par
# `docker-compose.test.yml`.
#
# Source DSN : variable d'env DATABASE_URL_APP_TEST (cf .env.test.template).
# Si la DB n'est pas disponible (env absente OU connexion échoue), les tests
# qui demandent ces fixtures sont SKIP — jamais ERROR. C'est volontaire pour
# permettre `pytest -q` même sans docker (les tests sans DB passent quand
# même).
# ============================================================================


def _test_dsn_or_none() -> str | None:
    """Lit DATABASE_URL_APP_TEST depuis l'env, ou None si absente."""
    return os.environ.get("DATABASE_URL_APP_TEST")


def _test_admin_dsn_or_none() -> str | None:
    """Lit DATABASE_URL_ADMIN_TEST depuis l'env, ou None si absente."""
    return os.environ.get("DATABASE_URL_ADMIN_TEST")


@pytest_asyncio.fixture
async def db_admin():
    """Connexion psycopg ADMIN à la DB test (port 5433).

    Skip si DATABASE_URL_ADMIN_TEST absente ou connexion échoue.
    Utile pour fixtures qui doivent préparer/cleanup des données hors flux
    applicatif (DELETE, TRUNCATE, etc).

    La connexion est en autocommit — pas de transaction wrapper. C'est
    cohérent avec le rôle « admin DDL/cleanup » de cette fixture.
    """
    dsn = _test_admin_dsn_or_none()
    if not dsn:
        pytest.skip("DB test not available (DATABASE_URL_ADMIN_TEST not set)")
    try:
        conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    except (psycopg.OperationalError, OSError) as exc:
        pytest.skip(f"DB test not available (connect failed: {exc})")
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def db_session():
    """Connexion psycopg APP à la DB test (port 5433), avec rollback teardown.

    Skip si DATABASE_URL_APP_TEST absente ou connexion échoue.

    Pattern : on ouvre une connexion NON-autocommit, on yield, puis on
    `rollback()` en finally. Tout INSERT/UPDATE effectué via cette fixture
    est annulé en fin de test — isolation parfaite entre tests sans avoir
    besoin d'un cleanup explicite.

    Limitation connue : si le code testé fait son propre `commit()`, le
    rollback n'aura plus rien à annuler. Pour les tests qui passent par le
    pool applicatif (app.db), préférer la fixture `initialized_pool` avec
    cleanup `test-%`.
    """
    dsn = _test_dsn_or_none()
    if not dsn:
        pytest.skip("DB test not available (DATABASE_URL_APP_TEST not set)")
    try:
        conn = await psycopg.AsyncConnection.connect(dsn, autocommit=False)
    except (psycopg.OperationalError, OSError) as exc:
        pytest.skip(f"DB test not available (connect failed: {exc})")
    try:
        yield conn
    finally:
        try:
            await conn.rollback()
        except psycopg.Error:
            pass
        await conn.close()
