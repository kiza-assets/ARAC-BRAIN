"""0033 atom_links — la TABLE des liens atome<->atome (le schéma, pas son contenu).

Couche de relations entre atomes (« les bons liens ») — ADDITIF et RÉVERSIBLE
(downgrade = DROP TABLE). Comme `project_registry` (0032), c'est un CACHE DÉRIVÉ
des `memory_atoms`, recalculé à chaque tick cortex AVANT le spend gate — donc frais
même quand l'IA payante est OFF. Départ ASSUMÉ de l'append-only : table MUTABLE par
design (analogue à un index), jamais source de vérité, jamais de PII (uniquement des
uuid d'atomes + type de relation + score + evidence technique).

À la date de cette migration, deux types d'arêtes CERTAINES étaient peuplés
(déterministes, ~0 faux positif) :
  - `supersedes`      : dérivée de la colonne `superseded_by` (src = remplaçant,
                        dst = atome retiré ; SPAN les statuts — le retiré est
                        `status='superseded'`).
  - `same_thread`     : chaîne temporelle intra-conversation (LEAD par created_at
                        dans un groupe de provenance) — LINÉAIRE, jamais une clique.
`semantic_neighbor` (inféré, seuil) était DÉFÉRÉ à l'increment 2 au moment où
cette migration a été écrite. IL NE L'EST PLUS : l'increment 2 est arrivé, et
`app/services/atom_links.py` peuple ce type d'arête (mutual-kNN, K=6, θ=0.25).
La TABLE, elle, n'a pas changé — c'est bien pourquoi aucune migration nouvelle
n'a été nécessaire, et c'est aussi pourquoi cette phrase a survécu ici sans
que rien ne la contredise. Une docstring de migration décrit un schéma, jamais
l'état du code qui l'utilise ; celle-ci le faisait, et se trompait donc dès le
lendemain.

Table SÉPARÉE de `audit_links` (à dessein) : `audit_links` est une file d'audit
à acquittement humain (colonnes acknowledged/decision, CHECK kind différent) — un
workflow append-only incompatible avec un cache recalculé en masse (DELETE+UPSERT
par tick). Ne JAMAIS réutiliser `audit_links` pour ces arêtes dérivées.

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.
"""
from __future__ import annotations
from typing import Union
from alembic import op
from db.alembic.roles import roles_arac

revision: str = "0033_atom_links"
down_revision: Union[str, None] = "0032_project_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS arac.atom_links (
            src_atom_id   uuid        NOT NULL REFERENCES arac.memory_atoms(id) ON DELETE CASCADE,
            dst_atom_id   uuid        NOT NULL REFERENCES arac.memory_atoms(id) ON DELETE CASCADE,
            relation_type text        NOT NULL,
            directed      boolean     NOT NULL DEFAULT true,
            score         real        NOT NULL DEFAULT 1.0,
            evidence      jsonb,
            updated_at    timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (src_atom_id, relation_type, dst_atom_id),
            CONSTRAINT atom_links_no_self CHECK (src_atom_id <> dst_atom_id),
            CONSTRAINT atom_links_relation_type_check
                CHECK (relation_type IN ('supersedes', 'same_thread', 'semantic_neighbor'))
        )
        """
    )
    # Index de lecture (serve /resume) : voisins par src et par dst (arête
    # non-dirigée stockée en canonique -> le read résout les deux sens).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_atom_links_src "
        "ON arac.atom_links (src_atom_id, relation_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_atom_links_dst "
        "ON arac.atom_links (dst_atom_id, relation_type)"
    )
    # Grants — CACHE MUTABLE (PAS append-only) : le cortex (arac_agent) recalcule
    # (INSERT/UPDATE/DELETE) ; l'API (arac_app) et l'analyse (arac_readonly) LISENT.
    # Mirroir exact de 0032_project_registry.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON arac.atom_links TO {R.agent};")
    op.execute(f"GRANT SELECT ON arac.atom_links TO {R.app};")
    op.execute(f"GRANT SELECT ON arac.atom_links TO {R.readonly};")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS arac.atom_links")
