-- ============================================================================
-- PROPOSAL v0.76 — arac.memory_review_queue (GO HUMAIN n°1 REQUIS)
-- ============================================================================
-- ⚠ NE PAS EXÉCUTER AUTOMATIQUEMENT. Ce fichier est une PROPOSITION : il n'est
-- appliqué par AUCUN outil du repo (ni Alembic, ni executor, ni CI). Application
-- MANUELLE par l'opérateur (compte admin/owner du schéma arac), uniquement après
-- accord explicite de l'exploitant et diagnostics de permissions.
-- Après application : vérifier que la table est bien lue par ses deux
-- consommateurs (agents/cortex/review_queue.py et le panneau « files » du
-- cockpit) — une file que personne ne relit est une file qui grossit.
-- Table ADDITIVE uniquement : aucune modification de arac.memory_atoms, jamais.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1) TABLE
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS arac.memory_review_queue (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- cible : uuid RÉSOLU par l'opérateur au moment du write (vérif target_ref_hash — T7).
    target_atom_id           uuid NOT NULL,
    target_atom_id_redacted  text NOT NULL,
    target_ref_hash          text NOT NULL,                 -- sha256 tronqué (non réversible)
    source_batch_id          text NOT NULL,                 -- ex. v068_ced89f5605b2
    source_plan_id           text NOT NULL,                 -- ex. map_1e5cb8e57691
    write_plan_id            text NOT NULL UNIQUE,          -- ex. owp_636f007c7b0e (anti-rejeu)
    action_type              text NOT NULL,
    reason                   text NOT NULL,                 -- ≤200, redacté — JAMAIS de raw value
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

    -- CONTRAINTES DURES : la table ne peut structurellement pas servir à autre chose
    -- qu'à des entrées de revue additives.
    CONSTRAINT ck_mrq_action_type CHECK (action_type = 'CREATE_REVIEW_QUEUE_ITEM'),
    CONSTRAINT ck_mrq_status CHECK (status IN ('pending_human_review', 'reviewed',
                                               'rejected', 'closed')),
    CONSTRAINT ck_mrq_no_value_change CHECK (no_value_change IS TRUE),
    CONSTRAINT ck_mrq_no_scope_change CHECK (no_scope_change IS TRUE),
    CONSTRAINT ck_mrq_redacted_nonempty CHECK (target_atom_id_redacted <> ''),
    CONSTRAINT ck_mrq_ref_hash_nonempty CHECK (target_ref_hash <> ''),
    CONSTRAINT ck_mrq_write_plan_nonempty CHECK (write_plan_id <> ''),

    -- Option A (préférée) : FK vers memory_atoms. Sûre car (1) la vérification FK
    -- s'exécute avec les droits du propriétaire de la table (le writer n'a pas besoin
    -- de privilège supplémentaire), (2) lecture seule sur memory_atoms, aucune
    -- cascade (pas de ON DELETE CASCADE : un atome référencé ne peut pas être
    -- supprimé silencieusement — protection supplémentaire, pas un risque).
    CONSTRAINT fk_mrq_target_atom FOREIGN KEY (target_atom_id)
        REFERENCES arac.memory_atoms(id)
);

-- ---------------------------------------------------------------------------
-- 2) INDEX
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_memory_review_queue_target
    ON arac.memory_review_queue(target_atom_id);
CREATE INDEX IF NOT EXISTS idx_memory_review_queue_status
    ON arac.memory_review_queue(status);

-- ---------------------------------------------------------------------------
-- 3) PERMISSIONS — rôle writer LIMITÉ (créer SEULEMENT si le compte le permet ;
--    sinon, demander au DBA — ne jamais forcer)
-- ---------------------------------------------------------------------------
-- CREATE ROLE arac_review_writer LOGIN PASSWORD '<motdepasse-fort>';  -- décommenter si GO
GRANT USAGE ON SCHEMA arac TO arac_review_writer;
GRANT INSERT, SELECT ON arac.memory_review_queue TO arac_review_writer;
GRANT SELECT ON arac.memory_atoms TO arac_review_writer;   -- lecture seule (vérif post-action)
-- INTERDIT — ne JAMAIS exécuter :
--   GRANT UPDATE/DELETE ON arac.memory_review_queue TO arac_review_writer;
--   GRANT INSERT/UPDATE/DELETE ON arac.memory_atoms TO arac_review_writer;
-- (le writer ne peut PAS modifier le cerveau, même si tout le code était compromis)

-- ---------------------------------------------------------------------------
-- 4) ROLLBACK (JAMAIS automatique — GO humain séparé)
-- ---------------------------------------------------------------------------
-- DROP TABLE IF EXISTS arac.memory_review_queue;          -- ne touche PAS memory_atoms
-- REVOKE ALL ON arac.memory_review_queue FROM arac_review_writer;
-- REVOKE SELECT ON arac.memory_atoms FROM arac_review_writer;
-- REVOKE USAGE ON SCHEMA arac FROM arac_review_writer;
-- DROP ROLE IF EXISTS arac_review_writer;
