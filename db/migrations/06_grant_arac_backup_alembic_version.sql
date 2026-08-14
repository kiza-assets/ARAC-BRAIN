-- ============================================================================
-- ARAC — Phase 2.0 — 06_grant_arac_backup_alembic_version.sql
--
-- Correctif urgent 2026-05-10 : `arac.alembic_version` créée par
-- `alembic stamp` Phase 1b.8 est owned par `__ARAC_ROLE_ADMIN__`, pas par `postgres`.
-- Les grants de `04_role_backup.sql.template` (GRANT SELECT ON ALL TABLES +
-- ALTER DEFAULT PRIVILEGES FOR ROLE postgres) ne couvraient PAS cette table,
-- ce qui faisait planter `pg_dump` avec "permission denied for table alembic_version".
--
-- Ce fichier :
--   1. Accorde rétroactivement SELECT sur alembic_version à __ARAC_ROLE_BACKUP__
--   2. Ajoute ALTER DEFAULT PRIVILEGES FOR ROLE __ARAC_ROLE_ADMIN__ pour couvrir les
--      FUTURES tables/séquences créées par les migrations Alembic Phase 3+
--
-- Idempotent : GRANT déjà existant et ALTER DEFAULT PRIVILEGES déjà posés
-- ne génèrent pas d'erreur (PostgreSQL no-op silencieux).
--
-- Le DDL est écrit à la main ; deux incidents ont suivi une tentative
-- d'autogenerate.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- LES NOMS DE RÔLES SONT DES MARQUEURS, PAS DES CONSTANTES.
--
-- Un rôle PostgreSQL est GLOBAL AU CLUSTER, pas propre à une base : `arac_app`
-- du cerveau A **est** `arac_app` du cerveau B. Ce fichier portait ces cinq
-- noms en dur ; le rejouer à côté d'un cerveau existant réencodait ses cinq
-- mots de passe, dont les services tombaient au redémarrage suivant — sans
-- erreur, sans trace, et sans effet visible avant plusieurs jours. C'est
-- l'incident exact qui a détruit le cerveau de production de l'auteur.
--
-- La convention du produit est `arac_<base>_<fonction>` : le bootstrap la
-- calcule à l'étape 2 et l'applique lui-même (bootstrap/lib/database.sh). Ce
-- fichier est du DDL de RÉFÉRENCE ; si vous le rejouez à la main, substituez
-- d'abord les marqueurs, sinon vous écrasez les rôles du voisin.
--
--   __ARAC_ROLE_ADMIN__ __ARAC_ROLE_APP__ __ARAC_ROLE_AGENT__
--   __ARAC_ROLE_READONLY__ __ARAC_ROLE_BACKUP__   les cinq rôles de CE cerveau
--   __ARAC_DB__                                   le nom de SA base
-- ----------------------------------------------------------------------------

\set ON_ERROR_STOP on

BEGIN;

-- 1. Grant rétroactif sur alembic_version (table créée Phase 1b.8 par __ARAC_ROLE_ADMIN__)
GRANT SELECT ON arac.alembic_version TO __ARAC_ROLE_BACKUP__;

-- 2. Privilèges par défaut pour FUTURES tables créées par __ARAC_ROLE_ADMIN__
--    (toutes les futures migrations Alembic Phase 3+ créeront leurs tables
--     avec ce rôle, donc ce GRANT par défaut est essentiel pour la pérennité
--     des backups pg_dump --schema=arac)
ALTER DEFAULT PRIVILEGES FOR ROLE __ARAC_ROLE_ADMIN__ IN SCHEMA arac
    GRANT SELECT ON TABLES TO __ARAC_ROLE_BACKUP__;

ALTER DEFAULT PRIVILEGES FOR ROLE __ARAC_ROLE_ADMIN__ IN SCHEMA arac
    GRANT USAGE, SELECT ON SEQUENCES TO __ARAC_ROLE_BACKUP__;

COMMIT;
