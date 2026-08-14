"""`arac.conversations_ack_audit()` — durcissement : journalise TOUT changement
de motif d'exclusion, pas seulement le premier ack (fix D36, clarification
decision d'exploitation, Perception V4 — cloture Phase 1).

Contexte : l'exploitant a valide l'exclusion de conversations `desktop_chat`
irrécupérables (purge côté fournisseur, irrécupérable)
UNIQUEMENT si elle est consignée DÉFINITIVEMENT — « aucune suppression
silencieuse, aucun acquittement silencieux ». La migration `0023` journalise
déjà la transition `acked` `false`→`true` (`action='conversation_ack_exclusion'`)
mais NE journalise RIEN si un `UPDATE` ultérieur, hors du chemin outillé
(`scripts/ops/exclude_conversation.py`), mute le MOTIF (`exclusion_reason`/
`exclusion_category`/`excluded_by`) d'une conversation DÉJÀ `acked=true` —
un `psql`/script tiers pourrait alors ré-écrire silencieusement le récit de
perte sans laisser de trace. DÉFENSE EN PROFONDEUR à 2 plans (aucun seul
n'est suffisant, cf `exclude_conversation.py::classify_reexclusion`
introduit dans le MÊME chantier) :

  (A) L'outil (`exclude_conversation.py`) REFUSE par défaut de ré-exclure
      avec un motif différent (`--force-motive-change` requis, explicite).
  (B) CETTE migration : le trigger `arac.conversations_ack_audit()` (0023)
      journalise MAINTENANT aussi la mutation d'un motif déjà consigné —
      garantit que même un `UPDATE` hors CLI (psql, autre script) laisse une
      trace, non-contournable (SECURITY DEFINER, cf 0023).

(A) seul laisse la DB capable d'écraser en silence via un autre chemin — pas
« définitif ». (B) seul autorise encore l'outil à muter le motif consigné
(journalisé, mais le registre définitif est modifié sans REFUS). Ensemble =
définitif (le 1er motif ne s'écrase pas par défaut) + non-contournable
(toute mutation DB tracée) + explicable au recall/audit.

`CREATE OR REPLACE FUNCTION` (idempotent, mirror 0023) AJOUTE une 2e branche
à la fonction existante :

  - Branche EXISTANTE (0023, INCHANGÉE) : `OLD.acked=false AND
    NEW.acked=true` -> `INSERT audit_log action='conversation_ack_exclusion'`.
  - Branche NOUVELLE : `OLD.acked=true AND NEW.acked=true` ET
    (`NEW.exclusion_reason IS DISTINCT FROM OLD.exclusion_reason` OU
    `NEW.exclusion_category IS DISTINCT FROM OLD.exclusion_category` OU
    `NEW.excluded_by IS DISTINCT FROM OLD.excluded_by`) ->
    `INSERT audit_log action='conversation_exclusion_motive_changed'`,
    `result_summary` jsonb avec `conversation_id`/`conversation_uid` +
    `old_reason`/`old_category`/`old_excluded_by` +
    `new_reason`/`new_category`/`new_excluded_by`, `success=true`.

NON-RÉGRESSION (important) : les `UPDATE` qui NE touchent PAS les colonnes
`exclusion_*`/`excluded_by` (ex. rembobinage `curated_through_message_id`
par `scripts/ops/heal_empty_messages.py`, avancée normale du curseur de
curation) NE déclenchent PAS cette nouvelle branche — le `IS DISTINCT FROM`
ne porte QUE sur les 3 colonnes de motif, jamais sur le reste de la row.
Aucun spam d'`audit_log` sur les écritures courantes du pipeline.

Trigger `BEFORE UPDATE ON arac.conversations` INCHANGÉ (toujours
`trg_conversations_ack_audit`, `CREATE OR REPLACE TRIGGER` idempotent —
aucun nouveau trigger, une seule fonction étendue).

Downgrade : `CREATE OR REPLACE FUNCTION` qui restaure EXACTEMENT le corps
`0023` (une seule branche, `conversation_ack_exclusion`) — symétrie
upgrade/downgrade vérifiée par `tests/test_d063_migrations.py`.

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0029_d063_exclusion_motive_audit
Revises: 0028_d063_digestion_review_queue
Create Date: 2026-07-07
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0029_d063_exclusion_motive_audit"
down_revision: Union[str, None] = "0028_d063_digestion_review_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION arac.conversations_ack_audit() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = arac, pg_catalog AS $$
        BEGIN
            IF OLD.acked = false AND NEW.acked = true THEN
                INSERT INTO arac.audit_log (node_id, action, result_summary, success)
                VALUES (
                    NEW.node_id,
                    'conversation_ack_exclusion',
                    jsonb_build_object(
                        'conversation_id', NEW.id,
                        'conversation_uid', NEW.conversation_uid,
                        'exclusion_category', NEW.exclusion_category,
                        'excluded_by', NEW.excluded_by
                    ),
                    true
                );
            ELSIF OLD.acked = true AND NEW.acked = true AND (
                NEW.exclusion_reason IS DISTINCT FROM OLD.exclusion_reason OR
                NEW.exclusion_category IS DISTINCT FROM OLD.exclusion_category OR
                NEW.excluded_by IS DISTINCT FROM OLD.excluded_by
            ) THEN
                INSERT INTO arac.audit_log (node_id, action, result_summary, success)
                VALUES (
                    NEW.node_id,
                    'conversation_exclusion_motive_changed',
                    jsonb_build_object(
                        'conversation_id', NEW.id,
                        'conversation_uid', NEW.conversation_uid,
                        'old_reason', OLD.exclusion_reason,
                        'old_category', OLD.exclusion_category,
                        'old_excluded_by', OLD.excluded_by,
                        'new_reason', NEW.exclusion_reason,
                        'new_category', NEW.exclusion_category,
                        'new_excluded_by', NEW.excluded_by
                    ),
                    true
                );
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_conversations_ack_audit "
        "BEFORE UPDATE ON arac.conversations "
        "FOR EACH ROW EXECUTE FUNCTION arac.conversations_ack_audit()"
    )


def downgrade() -> None:
    # Restaure EXACTEMENT le corps 0023 (une seule branche) — symétrie
    # upgrade/downgrade, cf tests/test_d063_migrations.py.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION arac.conversations_ack_audit() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = arac, pg_catalog AS $$
        BEGIN
            IF OLD.acked = false AND NEW.acked = true THEN
                INSERT INTO arac.audit_log (node_id, action, result_summary, success)
                VALUES (
                    NEW.node_id,
                    'conversation_ack_exclusion',
                    jsonb_build_object(
                        'conversation_id', NEW.id,
                        'conversation_uid', NEW.conversation_uid,
                        'exclusion_category', NEW.exclusion_category,
                        'excluded_by', NEW.excluded_by
                    ),
                    true
                );
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE OR REPLACE TRIGGER trg_conversations_ack_audit "
        "BEFORE UPDATE ON arac.conversations "
        "FOR EACH ROW EXECUTE FUNCTION arac.conversations_ack_audit()"
    )
