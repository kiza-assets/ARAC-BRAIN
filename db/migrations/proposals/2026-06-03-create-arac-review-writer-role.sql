-- ============================================================================
-- PROPOSAL v0.76B — rôle arac_review_writer (GO HUMAIN 1B REQUIS)
-- ============================================================================
-- ⚠ NE PAS EXÉCUTER AUTOMATIQUEMENT. __ARAC_ROLE_ADMIN__ NE PEUT PAS créer de rôle
-- (pas de CREATEROLE) : la section 1 doit être exécutée par le DBA / postgres
-- (superuser ou rolcreaterole). Préparé pour GO 1B après GO 1A (table
-- arac.memory_review_queue créée, validator = MIGRATION_NEEDS_FIX : rôle absent).
-- AUCUN rôle existant n'est réutilisable (cf. V0.76B-WRITER-ROLE-OPERATOR-PLAN) :
--   __ARAC_ROLE_APP__   : INSERT+UPDATE sur memory_atoms  -> STOP_SECURITY validator
--   __ARAC_ROLE_AGENT__ : INSERT sur memory_atoms         -> STOP_SECURITY validator
--   __ARAC_ROLE_READONLY__ : refusé PAR DESIGN pour écrire (garde executor v0.75)
--   __ARAC_ROLE_ADMIN__ : ALL PRIVILEGES / compte DDL     -> jamais comme writer applicatif
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1) À EXÉCUTER PAR LE DBA / postgres (session superuser ou rolcreaterole)
-- ---------------------------------------------------------------------------
-- Mot de passe : préférer le définir INTERACTIVEMENT (jamais dans l'historique) :
--   CREATE ROLE arac_review_writer LOGIN;
--   \password arac_review_writer
-- (ou décommenter avec un mot de passe fort si la session n'est pas interactive)
-- CREATE ROLE arac_review_writer LOGIN PASSWORD '<motdepasse-fort>';

-- Le plus simple : le DBA fait AUSSI les GRANT schéma + memory_atoms
-- (USAGE exige le owner du schéma ; SELECT memory_atoms exige le owner de la table) :
GRANT USAGE ON SCHEMA arac TO arac_review_writer;
GRANT SELECT ON arac.memory_atoms TO arac_review_writer;   -- lecture seule (vérif post-action)

-- ---------------------------------------------------------------------------
-- 2) À EXÉCUTER PAR __ARAC_ROLE_ADMIN__ (OWNER de memory_review_queue créée au GO 1A)
--    (le DBA peut aussi le faire dans la même session)
-- ---------------------------------------------------------------------------
GRANT INSERT, SELECT ON arac.memory_review_queue TO arac_review_writer;

-- INTERDIT — ne JAMAIS exécuter :
--   GRANT UPDATE/DELETE/TRUNCATE ON arac.memory_review_queue TO arac_review_writer;
--   GRANT INSERT/UPDATE/DELETE ON arac.memory_atoms TO arac_review_writer;
--   GRANT CREATE ON SCHEMA arac TO arac_review_writer;
--   ALTER DEFAULT PRIVILEGES ... TO arac_review_writer;   (aucun droit automatique futur)

-- ---------------------------------------------------------------------------
-- 3) VÉRIFICATIONS (lecture seule, après les GRANT)
-- ---------------------------------------------------------------------------
-- 3a. le rôle existe, peut se connecter, n'est ni superuser ni createrole :
SELECT rolname, rolcanlogin, rolsuper, rolcreaterole
FROM pg_roles WHERE rolname = 'arac_review_writer';        -- attendu : t | f | f

-- 3b. privilèges effectifs (attendu : queue=INSERT,SELECT ; memory_atoms=SELECT) :
SELECT table_name, privilege_type
FROM information_schema.role_table_grants
WHERE grantee = 'arac_review_writer' AND table_schema = 'arac'
ORDER BY 1, 2;

-- 3c. DÉFENSE EN PROFONDEUR — vérifier qu'AUCUN autre rôle applicatif n'a hérité
--     de droits d'écriture sur la queue (les default privileges 'FOR ROLE postgres'
--     donnent INSERT+UPDATE à __ARAC_ROLE_APP__ sur les tables créées PAR postgres ;
--     la queue a été créée par __ARAC_ROLE_ADMIN__, donc attendu : rien pour __ARAC_ROLE_APP__) :
SELECT grantee, privilege_type
FROM information_schema.role_table_grants
WHERE table_schema = 'arac' AND table_name = 'memory_review_queue'
  AND grantee NOT IN ('__ARAC_ROLE_ADMIN__', 'arac_review_writer')
ORDER BY 1, 2;
-- si __ARAC_ROLE_APP__/__ARAC_ROLE_AGENT__ apparaissent avec INSERT/UPDATE :
--   REVOKE INSERT, UPDATE ON arac.memory_review_queue FROM __ARAC_ROLE_APP__;   -- (à adapter)

-- ---------------------------------------------------------------------------
-- 4) PREUVE READ-ONLY-CERVEAU (connecté EN arac_review_writer, pas admin)
-- ---------------------------------------------------------------------------
-- INSERT INTO arac.memory_atoms DEFAULT VALUES;                      -- attendu : ERROR permission denied
-- UPDATE arac.memory_review_queue SET status='closed' WHERE false;   -- attendu : ERROR permission denied
-- DELETE FROM arac.memory_review_queue WHERE false;                  -- attendu : ERROR permission denied
-- SELECT count(*) FROM arac.memory_review_queue;                     -- attendu : OK (0)

-- ---------------------------------------------------------------------------
-- 5) ROLLBACK (JAMAIS automatique — GO séparé)
-- ---------------------------------------------------------------------------
-- REVOKE ALL ON arac.memory_review_queue FROM arac_review_writer;
-- REVOKE SELECT ON arac.memory_atoms FROM arac_review_writer;
-- REVOKE USAGE ON SCHEMA arac FROM arac_review_writer;
-- DROP ROLE IF EXISTS arac_review_writer;
