-- ============================================================================
-- ARAC — Phase 1b — 01_init.sql
-- Schéma `arac` : baseline Phase 1b (ce fichier) + trigger functions.
-- NB : la base LIVE compte 14 BASE TABLE au total après les migrations
-- alembic 0001->0011 (memory_atoms, sessions, session_buffer, nodes,
-- nodes_heartbeat_history, audit_log, audit_links, audit_feedback, arac_config,
-- scopes, raw_conversations, incoming_proposal_queue, memory_review_queue,
-- alembic_version) — décompte réel vérifié, ce n'est ni 9 ni 12.
-- Ce fichier EST le schéma de référence : il fait foi, pas un document.
-- halfvec(3072) au lieu de vector(3072) (HNSW jusqu'à 4000 dim)
-- UUID : gen_random_uuid() (natif PG 13+, conforme V2 spec lignes 143/248/341/364)
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- search_path : tables créées dans `arac`, types pgvector/uuid-ossp/pg_trgm dans `public`
SET LOCAL search_path TO arac, public;

-- ============================================================================
-- 1. Trigger functions
-- ============================================================================

-- updated_at automatique à chaque UPDATE
CREATE OR REPLACE FUNCTION arac.tg_set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Auto-archive des suggestions agents à faible score (<70)
-- Seuil 70 hardcodé ici = arac_config.low_confidence_archive_threshold
CREATE OR REPLACE FUNCTION arac.tg_auto_archive_low_confidence() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.audit_source = 'autonomous_agent_suggest'
       AND NEW.confidence_score IS NOT NULL
       AND NEW.confidence_score < 70
       AND NEW.status = 'active' THEN
        NEW.status := 'low_confidence_archive';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 2. Tables (ordre des FK)
-- ============================================================================

-- ---------------------------------------------------------------------------
-- arac.nodes — qui peut écrire quoi (heartbeat calibré par node)
-- Source V2 §2.2 lignes 73-87
-- ---------------------------------------------------------------------------
CREATE TABLE arac.nodes (
    node_id                  TEXT        PRIMARY KEY,
    -- account : QUI PAIE l'appel. 'human' = votre abonnement ; 'agent' =
    -- une clé d'API facturée à l'usage ; 'system' = rien du tout (un cron).
    -- La distinction n'est pas cosmétique : elle vous dit où part l'argent.
    account                  TEXT        NOT NULL CHECK (account IN ('human', 'system', 'agent')),
    -- owner : VERS QUEL cerveau le savoir est routé. 'owner' = le vôtre.
    owner                    TEXT        NOT NULL CHECK (owner IN ('owner', 'system')),
    role                     TEXT        NOT NULL CHECK (role IN ('owner_producer', 'agent', 'service')),
    auditor_kind             TEXT        CHECK (auditor_kind IN ('technical', 'pattern', 'coherence', 'curator')),
    last_heartbeat           TIMESTAMPTZ DEFAULT NOW(),
    expected_cadence_minutes INT,                                  -- NULL = humain
    silent_warn_minutes      INT         DEFAULT 30,               -- seuil hérité du prototype antérieur
    silent_critical_minutes  INT         DEFAULT 120,              -- seuil hérité du prototype antérieur
    quiet_hours_local        TEXT,                                 -- ex: '22:00-08:00 Europe/Paris'
    active                   BOOLEAN     DEFAULT TRUE,
    created_at               TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- arac.sessions — fenêtres de travail
-- Source V2 §2.5 lignes 247-261
-- ---------------------------------------------------------------------------
CREATE TABLE arac.sessions (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id             TEXT        NOT NULL REFERENCES arac.nodes(node_id),
    scope               TEXT        NOT NULL,
    topic               TEXT,
    started_at          TIMESTAMPTZ DEFAULT NOW(),
    ended_at            TIMESTAMPTZ,                               -- NULL = ouverte
    summary             TEXT,
    summary_embedding   halfvec(3072),                             -- halfvec : HNSW n'indexe pas au-delà de 4000 dimensions
    atoms_created       UUID[],                                    -- dénormalisé à clôture
    accomplishments     TEXT[]      DEFAULT '{}',
    blockers            TEXT[]      DEFAULT '{}',
    next_steps          TEXT[]      DEFAULT '{}',
    closed_by           TEXT        CHECK (closed_by IN ('manual', 'auto_cron'))
);

-- ---------------------------------------------------------------------------
-- arac.session_buffer — scratchpad volatile par session (CASCADE)
-- Source V2 §2.5 lignes 278-285
-- ---------------------------------------------------------------------------
CREATE TABLE arac.session_buffer (
    session_id      UUID        NOT NULL REFERENCES arac.sessions(id) ON DELETE CASCADE,
    event_type      TEXT        NOT NULL,                          -- ex: 'note_brute', 'capture'
    payload         JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- arac.memory_atoms — cœur du système (15 kinds, halfvec 3072, FK session SET NULL)
-- Source V2 §2.4 lignes 142-184 + plan Lightning §1b.2 (15 kinds, mood retiré)
-- ---------------------------------------------------------------------------
CREATE TABLE arac.memory_atoms (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    kind              TEXT        NOT NULL CHECK (kind IN (
                                      'decision', 'pattern', 'gotcha', 'state', 'todo', 'killed', 'note',
                                      'idea', 'insight', 'question', 'reference',
                                      'alert', 'validation', 'contradiction', 'suggestion'
                                  )),
    scope             TEXT        NOT NULL,
    key               TEXT        NOT NULL CHECK (key ~ '^[a-z0-9][a-z0-9-]*[a-z0-9]$'),
    value             TEXT        NOT NULL,
    embedding         halfvec(3072),                               -- halfvec : HNSW n'indexe pas au-delà de 4000 dimensions
    desc_hash         TEXT,                                        -- sha256 pour dédup
    tags              TEXT[]      DEFAULT '{}',
    status            TEXT        DEFAULT 'active' CHECK (status IN (
                                      'active', 'draft', 'superseded', 'archived', 'low_confidence_archive'
                                  )),
    superseded_by     UUID        REFERENCES arac.memory_atoms(id) ON DELETE SET NULL,
    confidence        TEXT        DEFAULT 'producer' CHECK (confidence IN (
                                      'producer', 'auditor_validated', 'agent_suggest'
                                  )),
    audit_source      TEXT        CHECK (audit_source IN (
                                      'interactive_human_validated', 'autonomous_agent_suggest'
                                  )),
    confidence_score  INT         CHECK (confidence_score >= 0 AND confidence_score <= 100),
    source_ref        JSONB,
    rationale         TEXT,                                        -- pourquoi (obligatoire decision via app logic)
    node_id           TEXT        NOT NULL REFERENCES arac.nodes(node_id),
    session_id        UUID        REFERENCES arac.sessions(id) ON DELETE SET NULL,
    version           INT         DEFAULT 1,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE TRIGGER memory_atoms_updated_at
    BEFORE UPDATE ON arac.memory_atoms
    FOR EACH ROW EXECUTE FUNCTION arac.tg_set_updated_at();

CREATE TRIGGER memory_atoms_auto_archive
    BEFORE INSERT ON arac.memory_atoms
    FOR EACH ROW EXECUTE FUNCTION arac.tg_auto_archive_low_confidence();

-- ---------------------------------------------------------------------------
-- arac.nodes_heartbeat_history — innovation ARAC (forensic temporel, rotation 30j)
-- Source V2 §2.3 lignes 121-127
-- ---------------------------------------------------------------------------
CREATE TABLE arac.nodes_heartbeat_history (
    id              BIGSERIAL   PRIMARY KEY,
    node_id         TEXT        NOT NULL REFERENCES arac.nodes(node_id),
    heartbeat_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ip_observed     INET,
    metadata        JSONB
);

-- ---------------------------------------------------------------------------
-- arac.audit_log — journal de tous les appels MCP/REST
-- target_atom_id sans FK (forensic : tolère orphelins après hard-delete)
-- Source V2 §2.6 lignes 312-325
-- ---------------------------------------------------------------------------
CREATE TABLE arac.audit_log (
    id              BIGSERIAL   PRIMARY KEY,
    node_id         TEXT        NOT NULL REFERENCES arac.nodes(node_id),
    action          TEXT        NOT NULL,
    tool_name       TEXT,
    target_atom_id  UUID,                                          -- pas de FK (forensic)
    query           TEXT,
    result_summary  JSONB,
    tokens_used     INT,
    latency_ms      INT,                                           -- ARAC ajoute la latence
    success         BOOLEAN     NOT NULL DEFAULT TRUE,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- arac.audit_links — liens audit → atome cible (alertes/validations)
-- target_atom_id sans FK (forensic), audit_atom_id FK vers memory_atoms
-- Source V2 §2.6 lignes 340-353
-- ---------------------------------------------------------------------------
CREATE TABLE arac.audit_links (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    target_atom_id      UUID        NOT NULL,                      -- pas de FK (forensic)
    audit_atom_id       UUID        NOT NULL REFERENCES arac.memory_atoms(id),
    kind                TEXT        NOT NULL CHECK (kind IN ('alert', 'validation', 'contradiction', 'suggestion')),
    priority            TEXT        CHECK (priority IN ('info', 'warn', 'critical')),
    audit_source        TEXT        NOT NULL CHECK (audit_source IN ('interactive_human_validated', 'autonomous_agent_suggest')),
    confidence_score    INT         CHECK (confidence_score >= 0 AND confidence_score <= 100),
    acknowledged        BOOLEAN     NOT NULL DEFAULT FALSE,
    acknowledged_at     TIMESTAMPTZ,
    acknowledged_by     TEXT        REFERENCES arac.nodes(node_id),
    decision            TEXT,                                       -- ex: 'patch', 'ignore', 'investigate'
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- arac.audit_feedback — calibration agents (was_useful par feedback humain)
-- Source V2 §2.6 lignes 363-371
-- ---------------------------------------------------------------------------
CREATE TABLE arac.audit_feedback (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_link_id   UUID        NOT NULL REFERENCES arac.audit_links(id) ON DELETE CASCADE,
    audit_atom_id   UUID        NOT NULL REFERENCES arac.memory_atoms(id),
    was_useful      BOOLEAN     NOT NULL,
    judged_by       TEXT        NOT NULL REFERENCES arac.nodes(node_id),
    judged_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    note            TEXT
);

-- ---------------------------------------------------------------------------
-- arac.arac_config — config runtime ajustable sans redéploiement
-- Source V2 §2.7 lignes 403-409
-- ---------------------------------------------------------------------------
CREATE TABLE arac.arac_config (
    key             TEXT        PRIMARY KEY,
    value           JSONB       NOT NULL,
    description     TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by      TEXT
);

COMMIT;
