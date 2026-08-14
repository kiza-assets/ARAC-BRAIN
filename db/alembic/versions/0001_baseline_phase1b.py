"""baseline — le schéma de départ, construit pour de bon.

CE QUE CETTE RÉVISION FAIT
--------------------------
Elle applique, dans l'ordre, les trois fichiers SQL qui décrivent le schéma
de départ du cerveau :

    db/migrations/01_init.sql     le schéma `arac` et ses neuf tables de base
    db/migrations/02_indexes.sql  les index (dont les deux HNSW halfvec)
    db/migrations/03_views.sql    la vue v_agent_usefulness

Après quoi les révisions 0002…n peuvent s'appuyer dessus.

POURQUOI ELLE A CHANGÉ — ET POURQUOI ICI PLUTÔT QU'AILLEURS
-----------------------------------------------------------
Cette révision était un no-op volontaire. Elle « stampait » un état construit
à la main, hors d'Alembic, sur la machine de son auteur. Cela marchait chez
lui : sa base possédait déjà le schéma. Sur une base VIDE, rien dans le dépôt
n'appliquait jamais ces trois fichiers, et la première migration réelle
mourait sur :

    UndefinedTable: relation "arac.memory_atoms" does not exist

Autrement dit : personne ne pouvait installer ce cerveau. Le défaut était
invisible précisément parce qu'il ne pouvait se voir que sur une machine
neuve.

Deux réparations étaient possibles. Faire appliquer les trois fichiers par le
bootstrap avant `alembic upgrade head` en aurait été une. Elle a été écartée :
elle demande au shell de savoir ce qu'Alembic sait déjà — « ce schéma a-t-il
déjà été bâti ? ». Deux gardiens pour un même état, c'est un état qui dérive.
Et surtout, `alembic upgrade head` est la commande écrite dans la
documentation, dans le message d'erreur de l'étape 5 du bootstrap et dans
l'intégration continue : une révision de départ qui ment rend menteuses
toutes celles-là d'un coup.

Ici, une seule autorité répond à la question, et c'est celle dont c'est le
métier. `alembic upgrade head` sur une base vide rend un schéma complet.

CE QUI PROTÈGE LES INSTALLATIONS EXISTANTES
-------------------------------------------
Une base bâtie avant cette révision porte déjà `arac.memory_atoms` et une
ligne dans `arac.alembic_version`. Alembic ne rejoue jamais une révision déjà
appliquée : ces bases ne passent pas ici. Le garde `_schema_deja_bati()`
couvre le seul cas restant — un schéma construit hors d'Alembic mais JAMAIS
stampé : on ne recrée rien, on se contente d'ancrer l'état. C'est exactement
le comportement historique de cette révision, conservé pour ce cas-là.

CE QU'ELLE NE FAIT PAS
----------------------
Elle ne crée pas les extensions `vector` et `pg_trgm` : sur PostgreSQL,
`CREATE EXTENSION vector` exige le superutilisateur, que le rôle des
migrations n'est pas (et ne doit pas être — une API qui peut modifier son
propre schéma peut aussi le détruire). L'étape 4 du bootstrap les pose. Si
elles manquent, cette révision s'arrête avec le geste exact à faire, plutôt
que d'échouer trois cents lignes plus loin sur un type `halfvec` inconnu.

Le DDL est écrit à la main, jamais engendré : une migration doit dire
exactement ce qu'elle fait. Les fichiers SQL restent la source unique — ils
ne sont pas recopiés ici, ils sont lus et exécutés. Deux copies d'un schéma
divergent toujours.

Revision ID: 0001_baseline_phase1b
Revises: None
Create Date: 2026-05-10
"""

import pathlib
import re
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_baseline_phase1b"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# db/alembic/versions/<ce fichier> → parents[2] == db/
_MIGRATIONS = pathlib.Path(__file__).resolve().parents[2] / "migrations"

_FICHIERS = ("01_init.sql", "02_indexes.sql", "03_views.sql")

# Un tag de dollar-quoting : $$ ou $nom$. Sert UNIQUEMENT à savoir si une
# ligne se trouve à l'intérieur d'un corps de fonction plpgsql — voir
# _sans_meta_psql().
_TAG_DOLLAR = re.compile(r"\$[A-Za-z_][A-Za-z_0-9]*\$|\$\$")

# Les extensions dont le schéma de départ a besoin, et pourquoi.
_EXTENSIONS = {
    "vector": "le type halfvec(3072) des colonnes d'embedding et l'index HNSW",
    "pg_trgm": "les index trigramme (recherche floue sur les noms propres)",
}


def _sans_meta_psql(texte: str) -> str:
    """Rend un script `psql` exécutable par le pilote de base de données.

    Deux différences, et deux seulement, séparent un script psql d'un script
    SQL ordinaire :

    · les méta-commandes (`\\set ON_ERROR_STOP on`) — psql les comprend, le
      serveur PostgreSQL non ;
    · le `BEGIN;` / `COMMIT;` de premier niveau — Alembic a DÉJÀ ouvert une
      transaction, et un `COMMIT` au milieu la refermerait sous ses pieds,
      laissant les instructions suivantes hors transaction. Une migration à
      moitié appliquée est pire qu'une migration refusée.

    Le suivi du dollar-quoting n'est pas une coquetterie : les corps plpgsql
    de `01_init.sql` contiennent des lignes `END;` et `BEGIN` qui, elles,
    doivent être préservées telles quelles. On ne retire donc `BEGIN;` et
    `COMMIT;` que HORS d'un bloc `$$ … $$`.
    """
    sortie: list[str] = []
    dans_dollar = False
    for ligne in texte.splitlines():
        if not dans_dollar and ligne.lstrip().startswith("\\"):
            continue
        if not dans_dollar and ligne.strip().upper() in ("BEGIN;", "COMMIT;"):
            continue
        # Un nombre impair de tags sur la ligne fait basculer l'état.
        if len(_TAG_DOLLAR.findall(ligne)) % 2 == 1:
            dans_dollar = not dans_dollar
        sortie.append(ligne)
    return "\n".join(sortie)


def _executer_script(bind, sql: str) -> None:
    """Exécute un script SQL entier, sans le faire relire par personne.

    On descend jusqu'à la connexion du pilote plutôt que de passer par
    `exec_driver_sql`. Raison : le pilote n'interprète les `%` comme des
    marqueurs de paramètres QUE si on lui passe des paramètres. La couche
    au-dessus en passe toujours, ne serait-ce qu'un tuple vide — et le premier
    commentaire venu (« si pct < 50% ») fait alors échouer tout le fichier sur
    un « only '%s' … are allowed as placeholders ». Ces trois fichiers sont du
    SQL littéral : rien n'a à y être substitué.
    """
    with bind.connection.driver_connection.cursor() as cur:
        cur.execute(sql)


def _schema_deja_bati(bind) -> bool:
    """Le schéma existe-t-il déjà, bâti hors d'Alembic ?

    `arac.memory_atoms` est le témoin : c'est la table centrale de
    `01_init.sql`. Si elle est là, on n'a rien à construire — on ancre.
    """
    return bool(
        bind.exec_driver_sql(
            "SELECT to_regclass('arac.memory_atoms') IS NOT NULL"
        ).scalar()
    )


def _ou_tourne_cette_migration(bind) -> tuple[str, str]:
    """La base ET LE PORT de la grappe où cette migration tourne réellement.

    UN REMÈDE IMPRIMÉ SANS `-p` NE S'ADRESSE PAS À CETTE GRAPPE.

    `sudo -u postgres psql -d <base>` s'adresse à la grappe PAR DÉFAUT de la
    machine. Sur un serveur qui suit la recommandation de ce dépôt — une
    grappe par cerveau — ce n'est pas la nôtre : c'est celle du premier
    installé. Et si deux amis ont donné le même nom à leur cerveau, le remède
    ouvre la base du voisin. C'est au pire moment que cette ligne est lue :
    l'installation est en panne, on copie, on colle, on ne relit pas.

    On ne DEVINE donc pas le port, et on ne l'écrit pas en dur : on le
    DEMANDE au serveur auquel on est déjà connecté. `current_setting('port')`
    rend le port du postmaster qui exécute cette migration — c'est-à-dire
    exactement la grappe que le remède doit viser, y compris quand on est
    arrivé par une socket Unix, où l'URL de connexion ne porte aucun port.

    Un constructeur de message ne doit jamais échouer lui-même : si la
    connexion ne répond plus, on retombe sur l'URL, puis sur un gabarit qui
    dit franchement ce qu'il ne sait pas.
    """
    try:
        base, port = bind.exec_driver_sql(
            "SELECT current_database(), current_setting('port')"
        ).first()
        return str(base), str(port)
    except Exception:  # noqa: BLE001 — un message d'erreur ne lève jamais
        url = getattr(getattr(bind, "engine", None), "url", None)
        base = getattr(url, "database", None) or "<votre-base>"
        port = getattr(url, "port", None)
        return str(base), str(port) if port else "<le port de VOTRE grappe>"


def _exiger_extensions(bind) -> None:
    manquantes = [
        f"  · {nom:<8} — {raison}"
        for nom, raison in _EXTENSIONS.items()
        if not bind.exec_driver_sql(
            "SELECT 1 FROM pg_extension WHERE extname = %s", (nom,)
        ).first()
    ]
    if not manquantes:
        return
    base, port = _ou_tourne_cette_migration(bind)
    raise RuntimeError(
        "Le schéma de départ ne peut pas être construit : il manque des\n"
        "extensions PostgreSQL dans cette base.\n\n"
        + "\n".join(manquantes)
        + "\n\n"
        "Elles s'installent en superutilisateur, une seule fois par base :\n"
        f"    sudo -u postgres psql -p {port} -d {base} \\\n"
        "         -c 'CREATE EXTENSION IF NOT EXISTS vector' \\\n"
        "         -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm'\n\n"
        f"Le « -p {port} » désigne la grappe où CETTE migration tourne — la\n"
        "vôtre. Sans lui, la commande s'adresse à la grappe par défaut de la\n"
        "machine, c'est-à-dire, sur un serveur à plusieurs cerveaux, à celle\n"
        "du voisin.\n\n"
        "Le bootstrap le fait pour vous à l'étape 4 :\n"
        "    sudo ./bootstrap/bootstrap.sh --from vecteurs"
    )


def upgrade() -> None:
    bind = op.get_bind()

    if _schema_deja_bati(bind):
        # Cas historique : schéma bâti à la main avant qu'Alembic n'existe
        # sur cette base. On ancre, on ne reconstruit pas.
        return

    _exiger_extensions(bind)

    for nom in _FICHIERS:
        chemin = _MIGRATIONS / nom
        if not chemin.is_file():
            raise RuntimeError(
                f"Fichier de schéma introuvable : {chemin}\n"
                "Le dépôt est incomplet — ces trois fichiers SONT le schéma de\n"
                "départ, ils ne sont pas de la documentation."
            )
        _executer_script(bind, _sans_meta_psql(chemin.read_text(encoding="utf-8")))

    # 01_init.sql pose `SET LOCAL search_path TO arac, public`. Ce réglage
    # survit jusqu'à la fin de la transaction, donc jusqu'aux révisions
    # suivantes. Elles nomment toutes leur schéma explicitement, mais rien ne
    # le garantit pour celles de demain : on rend le search_path tel qu'on
    # l'a trouvé.
    bind.exec_driver_sql('SET LOCAL search_path TO "$user", public')


def downgrade() -> None:
    """Redescendre sous la baseline, c'est jeter le cerveau.

    Refus explicite. Le geste existe, il est à vous, et il se dit en clair —
    avec le port de la grappe où l'on se trouve, jamais sans : c'est la
    commande la plus destructrice que ce dépôt imprime, et une commande
    destructrice qui laisse choisir la grappe à la machine choisit celle du
    voisin.
    """
    try:
        base, port = _ou_tourne_cette_migration(op.get_bind())
    except Exception:  # noqa: BLE001 — un refus ne lève jamais autre chose
        base, port = "<votre-base>", "<le port de VOTRE grappe>"
    raise RuntimeError(
        "downgrade sous 0001 refusé : cela supprimerait le schéma entier et\n"
        "tout ce qu'il contient. Si c'est bien ce que vous voulez, dites-le\n"
        f"explicitement :  sudo -u postgres dropdb -p {port} {base}\n"
        f"\n"
        f"Le « -p {port} » n'est pas décoratif : sans lui, `dropdb` s'adresse\n"
        "à la grappe par défaut de la machine et détruit ce qui y porte ce\n"
        "nom — le cerveau de quelqu'un d'autre, sur un serveur partagé."
    )
