"""0034 memory_review_queue — la table que DEUX lecteurs attendaient depuis toujours.

POURQUOI CETTE MIGRATION EXISTE
===============================

`arac.memory_review_queue` était lue par deux consommateurs de production et
créée par AUCUNE migration :

  - `app/perception/ingest_watchdog.py` —, profondeur et âge du
    plus vieux « pending » des TROIS files de revue ;
  - `control_center/collectors/db_metrics.py` — `mrq_summary()`, servi au
    cockpit.

Son DDL dormait dans `db/migrations/proposals/`, un répertoire que rien
n'applique — ni Alembic, ni le bootstrap, ni l'intégration continue. Les deux
lecteurs dégradent proprement (SAVEPOINT côté watchdog, try/except côté
cockpit) : la panne ne produisait donc aucune erreur, aucune ligne de journal,
aucun test rouge. Elle était SILENCIEUSE ET PERMANENTE, et l'en-tête de
`db/migrations/01_init.sql` annonçait pourtant la table comme existante.

Sur une base neuve, la métrique censée empêcher un backlog de revue d'être
« structurellement silencieux » était elle-même muette. C'est le défaut qu'on
répare ici : une file vide qui répond « 0 » est une mesure ; une file absente
qui répond « indisponible » est un trou.

CE QUE CETTE FILE EST — ET CE QU'ELLE N'EST PAS
===============================================

Une file de REVUE D'ATOMES EXISTANTS, pas une file de candidats nouveaux : la
distinction est établie par 0010, qui a créé `incoming_proposal_queue`
précisément parce que les deux ne se confondent pas. D'où la clé étrangère
`target_atom_id` NOT NULL vers `memory_atoms`, et les deux contraintes dures
`no_value_change` / `no_scope_change` : la table ne peut STRUCTURELLEMENT pas
servir à autre chose qu'à des entrées de revue additives. Aucun chemin passant
par elle ne peut modifier un souvenir.

AUCUN PRODUCTEUR DANS CE DÉPÔT — ET IL FAUT LE DIRE
===================================================

Cette file a deux lecteurs et zéro écrivain ici. Elle est alimentée par un
outil d'opérateur qui n'est pas publié, sous un rôle dédié dont
`db/migrations/proposals/2026-06-03-create-arac-review-writer-role.sql` décrit
la création — un geste manuel, réservé au DBA, jamais joué par ce bootstrap.
Sur votre installation, elle restera donc vide, et c'est normal : ce n'est pas
une panne, c'est une file sans producteur. Le cockpit affichera « 0 en
attente », ce qui est vrai, au lieu de « indisponible », qui ne l'était pas.

GRANTS — AUX RÔLES QUE LE BOOTSTRAP CRÉE, ET À EUX SEULS
========================================================

La proposition d'origine accordait des droits à `arac_review_writer`. Ce rôle
n'existe pas sur une grappe neuve, et PostgreSQL REFUSE un GRANT vers un rôle
absent : la migration aurait tué l'étape 5 de toute première installation —
exactement la panne que `arac_backup` a causée, et qu'il a fallu une grappe
vierge pour voir. On n'accorde donc qu'aux quatre rôles que l'étape 3 crée, et
seulement en LECTURE : aucun rôle applicatif ne doit pouvoir écrire dans une
file dont le sens est « un humain doit trancher ».

Doctrine : le DDL est écrit à la main via op.execute. Jamais l'autogenerate
d'Alembic : un diff automatique propose de supprimer ce qu'il ne comprend pas.
"""

from __future__ import annotations

from typing import Union

from alembic import op
from db.alembic.roles import roles_arac

revision: str = "0034_memory_review_queue"
down_revision: Union[str, None] = "0033_atom_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS arac.memory_review_queue (
            id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            -- La cible : un atome qui EXISTE DÉJÀ. C'est ce qui distingue cette
            -- file de `incoming_proposal_queue` (candidats nouveaux, sans cible).
            target_atom_id           uuid NOT NULL,
            target_atom_id_redacted  text NOT NULL,
            target_ref_hash          text NOT NULL,
            source_batch_id          text NOT NULL,
            source_plan_id           text NOT NULL,
            write_plan_id            text NOT NULL UNIQUE,   -- anti-rejeu
            action_type              text NOT NULL,
            reason                   text NOT NULL,          -- redacté, jamais de valeur brute
            candidate_type           text NOT NULL,
            scope                    text NOT NULL,
            confidence               numeric,
            status                   text NOT NULL DEFAULT 'pending_human_review',
            created_by               text NOT NULL DEFAULT 'arac_operator',
            created_at               timestamptz NOT NULL DEFAULT now(),
            review_required          boolean NOT NULL DEFAULT true,
            executed_by_operator     boolean NOT NULL DEFAULT true,
            no_value_change          boolean NOT NULL DEFAULT true,
            no_scope_change          boolean NOT NULL DEFAULT true,
            rollback_ref             text,
            audit_log_redacted       jsonb NOT NULL DEFAULT '{}'::jsonb,

            -- CONTRAINTES DURES : la table ne peut structurellement pas servir
            -- à autre chose qu'à des entrées de revue ADDITIVES.
            CONSTRAINT ck_mrq_action_type
                CHECK (action_type = 'CREATE_REVIEW_QUEUE_ITEM'),
            CONSTRAINT ck_mrq_status
                CHECK (status IN ('pending_human_review', 'reviewed',
                                  'rejected', 'closed')),
            CONSTRAINT ck_mrq_no_value_change CHECK (no_value_change IS TRUE),
            CONSTRAINT ck_mrq_no_scope_change CHECK (no_scope_change IS TRUE),
            CONSTRAINT ck_mrq_redacted_nonempty CHECK (target_atom_id_redacted <> ''),
            CONSTRAINT ck_mrq_ref_hash_nonempty CHECK (target_ref_hash <> ''),
            CONSTRAINT ck_mrq_write_plan_nonempty CHECK (write_plan_id <> ''),

            -- Pas de ON DELETE CASCADE, et c'est délibéré : un atome référencé
            -- par une revue en cours ne doit pas pouvoir disparaître en silence.
            CONSTRAINT fk_mrq_target_atom FOREIGN KEY (target_atom_id)
                REFERENCES arac.memory_atoms(id)
        )
        """
    )
    # Les deux index que les lecteurs utilisent réellement : la cible (revue
    # d'un atome donné) et le status (profondeur de la file).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_review_queue_target "
        "ON arac.memory_review_queue (target_atom_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_review_queue_status "
        "ON arac.memory_review_queue (status)"
    )
    # LECTURE SEULE pour les trois rôles applicatifs. Le status d'une entrée
    # (`pending_human_review` → `reviewed`/`rejected`) est un acte de revue
    # HUMAINE : il n'a aucun chemin d'écriture applicatif, par construction.
    op.execute(f"GRANT SELECT ON arac.memory_review_queue TO {R.app};")
    op.execute(f"GRANT SELECT ON arac.memory_review_queue TO {R.agent};")
    op.execute(f"GRANT SELECT ON arac.memory_review_queue TO {R.readonly};")


def downgrade() -> None:
    # Ne touche PAS memory_atoms : la contrainte tombe avec la table qui la porte.
    op.execute("DROP TABLE IF EXISTS arac.memory_review_queue")
