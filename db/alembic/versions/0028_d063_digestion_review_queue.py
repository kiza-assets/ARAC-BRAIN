"""`arac.digestion_review_queue` — file de revue humaine des candidats écartés.

Contrepartie de `run_receipts` (couverture agrégée par run, 0019/0027) au
niveau UNITAIRE : chaque candidat-atome que la digestion a produit puis
ÉCARTÉ (jamais posté à `memory_atoms`) atterrit ici pour revue humaine
différée, plutôt que de disparaître silencieusement dans les logs.

`drop_reason` (5 valeurs fermées) :
  - `kept_lower_confidence` : un doublon existait déjà avec une confiance
    supérieure ou égale — le candidat a perdu l'arbitrage (cf gotcha
    « supersede quasi jamais utilisé », mémoire projet — cette file donne
    enfin une trace des perdants de l'arbitrage plutôt qu'un silence total).
  - `policy_skip`           : refusé par une politique déterministe (gate,
    kind non autorisé, etc.) AVANT même le calcul de dédup.
  - `atom_quarantine`       : la génération a produit un extrait invalide/
    suspect, mis en quarantaine (cf `run_receipts.quarantine_output`, 0019).
  - `coverage_omitted`      : message jamais présenté au digesteur faute de
    place (troncature de contexte) — relié aux compteurs `coverage_omitted`
    de 0027 mais au niveau du message individuel candidat.
  - `oversized_message`     : message individuellement trop volumineux pour
    être digéré, écarté avant présentation.

`incumbent_atom_id` : **DÉVIATION DOCUMENTÉE vs** qui décrivait
un `bigint` — `arac.memory_atoms.id` est en réalité `uuid` (vérifié en prod
2026-07-06 via `\\d arac.memory_atoms`). La FK utilise donc `uuid`, seul type
qui référence réellement la PK de `memory_atoms`. `ON DELETE SET NULL` :
l'atome incumbent peut être archivé/superseded plus tard sans invalider la
row de revue (référence optionnelle, pas une dépendance dure).

`proposed_atom` (jsonb) : le candidat COMPLET tel qu'il aurait été posté
(scope/kind/key/value/rationale/tags…) — la revue doit pouvoir statuer sans
avoir à rejouer la digestion.

Grants — la revue humaine passe PAR `arac_admin` (déjà propriétaire complet
via les DEFAULT PRIVILEGES du schéma `arac`), PAS par un rôle applicatif :
  - `arac_agent` (le digesteur qui écarte le candidat) : INSERT/SELECT.
  - `arac_app` (cockpit de lecture) : SELECT seul.
  - REVOKE UPDATE/DELETE PARTOUT (`arac_app` ET `arac_agent`) — le
    changement de `status` (`pending` → `reviewed_kept`/`reviewed_dropped`)
    est un acte de REVUE HUMAINE, jamais un chemin d'écriture applicatif.
    C'est un choix plus strict que « moindre privilège » habituel (qui
    aurait pu laisser `arac_app` faire la transition de statut) : la revue
    de ce qui a été écarté de la mémoire durable est jugée suffisamment
    sensible pour rester un geste `arac_admin` explicite, cohérent avec la
    doctrine « écriture mémoire = GO auditeur ».

Downgrade : DROP TABLE (aucune autre table ne dépend de celle-ci).

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0028_d063_digestion_review_queue
Revises: 0027_d063_run_receipts_conserv
Create Date: 2026-07-06
"""

from typing import Sequence, Union

from alembic import op
from db.alembic.roles import roles_arac

revision: str = "0028_d063_digestion_review_queue"
down_revision: Union[str, None] = "0027_d063_run_receipts_conserv"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS arac.digestion_review_queue (
            id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            run_ref             text NOT NULL
                                  CHECK (length(btrim(run_ref)) > 0),
            conversation_uid    text NOT NULL
                                  CHECK (length(btrim(conversation_uid)) > 0),
            drop_reason         text NOT NULL CHECK (drop_reason IN (
                                    'kept_lower_confidence', 'policy_skip',
                                    'atom_quarantine', 'coverage_omitted',
                                    'oversized_message'
                                )),
            proposed_atom       jsonb NOT NULL,
            incumbent_atom_id   uuid
                                  REFERENCES arac.memory_atoms(id) ON DELETE SET NULL,
            scope               text NOT NULL,
            kind                text NOT NULL,
            status              text NOT NULL DEFAULT 'pending' CHECK (status IN (
                                    'pending', 'reviewed_kept', 'reviewed_dropped'
                                )),
            created_at          timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_digestion_review_queue_status "
        "ON arac.digestion_review_queue (status, created_at)"
    )

    op.execute(f"GRANT SELECT, INSERT ON arac.digestion_review_queue TO {R.agent};")
    op.execute(f"GRANT SELECT ON arac.digestion_review_queue TO {R.app};")
    op.execute(f"GRANT SELECT ON arac.digestion_review_queue TO {R.readonly};")
    # REVOKE défensif PARTOUT (cf docstring : la revue est un geste arac_admin
    # explicite, ni arac_app ni arac_agent ne font la transition de statut).
    op.execute(f"REVOKE UPDATE, DELETE ON arac.digestion_review_queue FROM {R.app};")
    op.execute(f"REVOKE UPDATE, DELETE ON arac.digestion_review_queue FROM {R.agent};")

    op.execute(
        "DO $$ "
        "DECLARE seq_name text := pg_get_serial_sequence('arac.digestion_review_queue', 'id'); "
        "BEGIN "
        f"  EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO {R.agent}', seq_name); "
        f"  EXECUTE format('REVOKE USAGE ON SEQUENCE %s FROM {R.app}', seq_name); "
        "END $$;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS arac.digestion_review_queue CASCADE")
