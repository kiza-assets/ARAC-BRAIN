"""La table des scopes : la forme de la mémoire, garantie par la base.

CE QUE FAIT CETTE MIGRATION
---------------------------
Elle crée ``arac.scopes`` (l'arbre de vos territoires) et l'attache à
``arac.memory_atoms`` par une clé étrangère. À partir d'ici, un atome dont le
scope n'existe pas dans l'arbre est REFUSÉ par PostgreSQL, pas seulement par
l'API.

CE QU'ELLE NE FAIT PAS — ET POURQUOI
------------------------------------
Elle n'insère **aucun scope**. Pas un seul.

Votre taxonomie ne vient pas d'une migration : elle vient de vos réponses.
L'entretien (``bootstrap/wizard.py``) écrit ``config/scopes.toml`` ;
``bootstrap/generate_scopes.py`` en tire deux artefacts jumeaux —
``app/schemas/scope_generated.py`` (le rempart de l'API) et
``db/seeds/scopes.sql`` (le peuplement de cette table). Les deux sortent de la
MÊME source, ce qui est le seul moyen de garantir qu'ils ne divergeront pas.

ORDRE D'INSTALLATION, non négociable :

    alembic upgrade head          crée la table, vide
    psql -f db/seeds/scopes.sql   la peuple avec VOTRE taxonomie

Dans cet ordre. La clé étrangère est posée ici alors que ``memory_atoms`` est
encore vide — sur une base neuve elle ne peut rien rejeter. Sur une base
peuplée, elle rejetterait tout atome dont le scope n'est pas encore semé :
c'est exactement le comportement voulu, et c'est pourquoi le seed vient juste
après.

LES DEUX RÈGLES QUE CETTE TABLE FAIT RESPECTER
----------------------------------------------
1. **Un scope ne s'invente pas à la volée.** La FK ``atoms_scope_fk`` le rend
   impossible : un scope hors arbre lève une 23503. Sans cette rigidité, la
   mémoire se fragmente en catégories jumelles et le rappel se dilue entre
   elles.

2. **Un nom est unique au sein de son parent, pas globalement.**
   ``strategie`` peut exister sous deux racines différentes — ce sont deux
   territoires distincts. ``NULLS NOT DISTINCT`` (PostgreSQL 15+) fait qu'au
   niveau des racines, où ``parent_id`` est NULL, les noms sont bien forcés à
   être distincts entre eux.

``ON UPDATE CASCADE`` : renommer un chemin de scope emmène ses atomes avec lui.
``ON DELETE RESTRICT`` : supprimer un scope encore habité est refusé. Une
suppression emporterait le savoir qu'il contient — cela doit être une décision
explicite, jamais l'effet de bord d'une commande de nettoyage.

Revision ID: 0007_scopes_hierarchique
Revises: 0006_developer_delivery_backfill
Create Date: 2026-05-22
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_scopes_hierarchique"
down_revision: Union[str, None] = "0006_developer_delivery_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Profondeur maximale d'un chemin. 3 est un plafond technique, pas une
#: recommandation : au-delà de « racine/feuille », l'expérience montre que
#: personne ne retrouve plus rien. Le générateur de taxonomie impose sa propre
#: limite (``max_depth`` dans ``config/scopes.toml``), plus stricte.
_MAX_DEPTH = 3


def upgrade() -> None:
    # --- L'arbre ------------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE arac.scopes (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name        varchar(64) NOT NULL,
            path        varchar(256) UNIQUE NOT NULL,
            parent_id   uuid NULL REFERENCES arac.scopes(id) ON DELETE RESTRICT,
            depth       smallint NOT NULL DEFAULT 0
                        CHECK (depth >= 0 AND depth <= {_MAX_DEPTH}),
            description text NULL,
            archived_at timestamptz NULL,
            created_at  timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT scopes_name_per_parent_unique
                UNIQUE NULLS NOT DISTINCT (parent_id, name)
        )
        """
    )

    # `path` est interrogé de trois façons, d'où trois index :
    #   - égalité (la FK et le filtre de rappel servi) ;
    #   - similarité trigramme (la recherche de scope du cockpit, qui doit
    #     tolérer une faute de frappe) ;
    #   - remontée d'arbre par parent (l'arborescence du cockpit).
    op.execute("CREATE INDEX idx_scopes_path_btree ON arac.scopes (path)")
    op.execute(
        "CREATE INDEX idx_scopes_path_trgm ON arac.scopes USING gin (path gin_trgm_ops)"
    )
    op.execute("CREATE INDEX idx_scopes_parent ON arac.scopes (parent_id)")

    # --- Le rempart côté base ----------------------------------------------
    # L'API valide déjà (422 Pydantic). Deux remparts, parce qu'un seul finit
    # toujours par être contourné : un script d'import, une migration, un
    # `psql` d'urgence à 2 h du matin.
    op.execute(
        """
        ALTER TABLE arac.memory_atoms
        ADD CONSTRAINT atoms_scope_fk
        FOREIGN KEY (scope)
        REFERENCES arac.scopes(path)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE arac.memory_atoms DROP CONSTRAINT IF EXISTS atoms_scope_fk"
    )
    # Les index et la clé étrangère réflexive tombent avec la table.
    op.execute("DROP TABLE IF EXISTS arac.scopes")
