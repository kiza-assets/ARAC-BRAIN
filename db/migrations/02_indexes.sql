-- ============================================================================
-- ARAC — Phase 1b — 02_indexes.sql
-- Indexes pour : UNIQUE partial, HNSW halfvec, multi-axes, trigram fuzzy, audit
-- Source : plan Lightning §1b.3 + V2 §2.4/2.5/2.6
-- HNSW params m=16, ef_construction=64 (défauts pgvector)
-- ⚠️ maintenance_work_mem='2GB' AVANT les CREATE INDEX HNSW
-- ============================================================================

\set ON_ERROR_STOP on

-- ----------------------------------------------------------------------------
-- maintenance_work_mem : booster mémoire pour build HNSW
-- ----------------------------------------------------------------------------
-- Note : SET LOCAL aurait demandé une transaction explicite (BEGIN/COMMIT).
-- CREATE INDEX en HNSW ne tolère pas d'être dans une transaction multi-statement
-- avec d'autres CREATE INDEX dans certaines combinaisons → on reste en autocommit
-- avec `SET` session-wide pour la durée de la session psql.
SET maintenance_work_mem = '2GB';
SET search_path TO arac, public;

-- ============================================================================
-- 1. memory_atoms — UNIQUE partial + HNSW + multi-axes + trigram
-- ============================================================================

-- L'index UNIQUE critique (règle héritée du prototype antérieur : un seul actif par scope+key)
CREATE UNIQUE INDEX ux_memory_atoms_active_scope_key
    ON arac.memory_atoms (scope, key) WHERE status = 'active';

-- HNSW sur halfvec(3072) — opérateur halfvec_cosine_ops
-- Build long sur grande table → maintenance_work_mem='2GB' déjà SET ci-dessus
CREATE INDEX ix_memory_atoms_embedding ON arac.memory_atoms
    USING hnsw (embedding halfvec_cosine_ops) WITH (m = 16, ef_construction = 64);

-- Filtres multi-axes
CREATE INDEX ix_memory_atoms_scope_kind_status ON arac.memory_atoms (scope, kind, status);
CREATE INDEX ix_memory_atoms_node_id           ON arac.memory_atoms (node_id);
CREATE INDEX ix_memory_atoms_tags              ON arac.memory_atoms USING GIN (tags);
CREATE INDEX ix_memory_atoms_session           ON arac.memory_atoms (session_id) WHERE session_id IS NOT NULL;
CREATE INDEX ix_memory_atoms_author_created    ON arac.memory_atoms (node_id, created_at DESC);
CREATE INDEX ix_memory_atoms_updated           ON arac.memory_atoms (updated_at DESC);
CREATE INDEX ix_memory_atoms_superseded        ON arac.memory_atoms (superseded_by) WHERE superseded_by IS NOT NULL;
CREATE INDEX ix_memory_atoms_desc_hash         ON arac.memory_atoms (desc_hash);

-- Trigram fuzzy (recherche RRF)
CREATE INDEX ix_memory_atoms_key_trgm   ON arac.memory_atoms USING GIN (key gin_trgm_ops);
CREATE INDEX ix_memory_atoms_value_trgm ON arac.memory_atoms USING GIN (value gin_trgm_ops);

-- ============================================================================
-- 2. sessions — HNSW summary_embedding + filtres
-- ============================================================================

CREATE INDEX ix_sessions_summary_embedding ON arac.sessions
    USING hnsw (summary_embedding halfvec_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE INDEX ix_sessions_node_started   ON arac.sessions (node_id, started_at DESC);
CREATE INDEX ix_sessions_open           ON arac.sessions (ended_at) WHERE ended_at IS NULL;
CREATE INDEX ix_sessions_scope_closed   ON arac.sessions (scope, ended_at DESC NULLS FIRST);

-- ============================================================================
-- 3. session_buffer
-- ============================================================================

CREATE INDEX ix_session_buffer_session ON arac.session_buffer (session_id, created_at DESC);

-- ============================================================================
-- 4. audit_log
-- ============================================================================

CREATE INDEX ix_audit_log_node_time   ON arac.audit_log (node_id, created_at DESC);
CREATE INDEX ix_audit_log_action_time ON arac.audit_log (action, created_at DESC);
CREATE INDEX ix_audit_log_target      ON arac.audit_log (target_atom_id) WHERE target_atom_id IS NOT NULL;
CREATE INDEX ix_audit_log_time        ON arac.audit_log (created_at DESC);

-- ============================================================================
-- 5. audit_links
-- ============================================================================

CREATE INDEX ix_audit_links_target           ON arac.audit_links (target_atom_id);
CREATE INDEX ix_audit_links_pending          ON arac.audit_links (created_at DESC) WHERE acknowledged = FALSE;
CREATE INDEX ix_audit_links_priority_pending ON arac.audit_links (priority, created_at DESC) WHERE acknowledged = FALSE;

-- ============================================================================
-- 6. audit_feedback
-- ============================================================================

CREATE INDEX ix_audit_feedback_atom   ON arac.audit_feedback (audit_atom_id);
CREATE INDEX ix_audit_feedback_judged ON arac.audit_feedback (judged_at DESC);

-- ============================================================================
-- 7. nodes_heartbeat_history
-- ============================================================================

CREATE INDEX ix_heartbeat_history_node_time ON arac.nodes_heartbeat_history (node_id, heartbeat_at DESC);
CREATE INDEX ix_heartbeat_history_time      ON arac.nodes_heartbeat_history (heartbeat_at DESC);
