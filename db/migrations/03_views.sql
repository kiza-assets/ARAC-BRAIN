-- ============================================================================
-- ARAC — Phase 1b — 03_views.sql
-- Vue v_agent_usefulness : taux d'utilité des agents (suggestions) sur 30j glissants
-- Source : V2 §2.6 lignes 380-394 + plan Lightning §1b.4
-- Usage : MCP tool agent_usefulness(since="30d")
-- Si pct < arac_config.agent_usefulness_min_pct (50%) sur ≥ min_samples (10) → flag agent
-- ============================================================================

\set ON_ERROR_STOP on

SET search_path TO arac, public;

CREATE OR REPLACE VIEW arac.v_agent_usefulness AS
SELECT
    ma.node_id AS agent_node_id,
    COUNT(*) AS total_suggestions,
    COUNT(*) FILTER (WHERE af.was_useful = TRUE) AS useful_count,
    ROUND(100.0 * COUNT(*) FILTER (WHERE af.was_useful = TRUE) / NULLIF(COUNT(*), 0), 1) AS usefulness_pct,
    MIN(af.judged_at) AS first_feedback,
    MAX(af.judged_at) AS last_feedback
FROM arac.memory_atoms ma
JOIN arac.audit_links al ON al.audit_atom_id = ma.id
LEFT JOIN arac.audit_feedback af ON af.audit_atom_id = ma.id
WHERE ma.audit_source = 'autonomous_agent_suggest'
  AND af.judged_at >= NOW() - INTERVAL '30 days'
GROUP BY ma.node_id;
