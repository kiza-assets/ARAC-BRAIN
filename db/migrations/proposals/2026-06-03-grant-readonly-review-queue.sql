-- ============================================================================
-- PROPOSAL v0.78 — GRANT SELECT review queue à __ARAC_ROLE_READONLY__ (GO HUMAIN REQUIS)
-- ============================================================================
-- ⚠ NE PAS EXÉCUTER AUTOMATIQUEMENT. Contexte : la vérification post-GO 2 avec
-- ARAC_READONLY_DSN a échoué car __ARAC_ROLE_READONLY__ n'a pas SELECT sur la NOUVELLE
-- table arac.memory_review_queue (créée par __ARAC_ROLE_ADMIN__ au GO 1A : les default
-- privileges « FOR ROLE postgres » ne s'appliquent pas — comportement attendu,
-- cf. D5 v0.76B). Ce GRANT permet les vérifications read-only futures.
--
-- QUI PEUT L'EXÉCUTER : __ARAC_ROLE_ADMIN__ SUFFIT (owner de memory_review_queue) —
-- pas besoin du DBA/postgres cette fois.
-- ============================================================================

-- 1) Le GRANT (lecture seule, aucune écriture accordée)
GRANT SELECT ON arac.memory_review_queue TO __ARAC_ROLE_READONLY__;

-- 2) Vérification (read-only)
SELECT privilege_type FROM information_schema.role_table_grants
WHERE grantee = '__ARAC_ROLE_READONLY__' AND table_schema = 'arac'
  AND table_name = 'memory_review_queue';            -- attendu : SELECT uniquement

-- 3) OPTIONNEL (décision séparée — NE PAS exécuter sans GO dédié) :
--    couvrir les FUTURES tables de gouvernance créées par __ARAC_ROLE_ADMIN__.
--    Recommandation : NE PAS l'appliquer ; préférer le GRANT au cas par cas
--    (chaque nouvelle table = décision explicite, pas d'héritage silencieux).
-- ALTER DEFAULT PRIVILEGES FOR ROLE __ARAC_ROLE_ADMIN__ IN SCHEMA arac
--     GRANT SELECT ON TABLES TO __ARAC_ROLE_READONLY__;

-- 4) ROLLBACK (jamais automatique)
-- REVOKE SELECT ON arac.memory_review_queue FROM __ARAC_ROLE_READONLY__;
