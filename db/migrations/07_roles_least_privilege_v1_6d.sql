-- ============================================================================
-- ARAC — V1.6D — Least-privilege roles (ADDITIF, NOLOGIN, zéro impact prod)
--
-- Crée 2 rôles d'écriture dédiés SANS LOGIN :
--   - arac_proposal_queue_writer : SELECT+INSERT+UPDATE(status,reject_reason,
--     updated_at) sur arac.incoming_proposal_queue UNIQUEMENT
--   - arac_memory_writer         : SELECT+INSERT sur arac.memory_atoms UNIQUEMENT
--     (pas d'UPDATE/DELETE : le supersede/archive reste un chemin admin gouverné)
--
-- AUCUN REVOKE ici : les droits existants d'__ARAC_ROLE_APP__/__ARAC_ROLE_AGENT__ sont intacts
-- (le retrait est l'étape 2 du plan V1.6D, fenêtre de maintenance + smoke tests,
--). NOLOGIN = personne ne
-- peut se connecter avec ces rôles tant que l'exploitant n'a pas exécuté l'étape
-- credentials (ALTER ROLE ... LOGIN PASSWORD '<openssl rand -hex 32>', password
-- bunker + .env, JAMAIS commité).
--
-- APPLICATION — LA COMMANDE D'AVANT VISAIT LE CERVEAU DE QUELQU'UN D'AUTRE.
--
-- Elle disait :  sudo -u postgres psql -d arac -v ON_ERROR_STOP=1 -f <ce fichier>
-- Deux défauts, et tous deux frappent quelqu'un qui ne peut pas les voir :
--
--   · « -d arac » nomme une base LITTÉRALE. C'est le nom qu'avait le cerveau
--     de l'auteur. Le vôtre s'appelle autrement — le bootstrap le dérive du
--     nom que vous avez donné à l'entretien. Recopier cette ligne, c'est au
--     mieux « database "arac" does not exist », au pire créer deux rôles dans
--     la base d'un autre cerveau de la même machine.
--   · « psql » sans « -p » se connecte à la grappe par défaut (5432). Si vous
--     avez installé votre cerveau sur une grappe à vous — ce que ce dépôt
--     recommande dès qu'une machine porte plus d'un cerveau — la commande
--     s'exécute silencieusement AILLEURS que là où vous croyez.
--
-- La forme juste lit les deux valeurs dans le coffre de VOTRE cerveau, qui
-- est le seul endroit qui les connaisse :
--
--     ARAC_ENV=/etc/arac/<votre-base>/arac.env
--     sudo -u postgres psql \
--       -p "$(sudo sed -n 's/^ARAC_DB_PORT=//p' "$ARAC_ENV")" \
--       -d "$(sudo sed -n 's/^ARAC_DB=//p'      "$ARAC_ENV")" \
--       -v ON_ERROR_STOP=1 -f db/migrations/07_roles_least_privilege_v1_6d.sql
--
-- CE QUE CE FICHIER NE VOUS DIT PAS ENCORE, ET QU'IL FAUT SAVOIR AVANT DE
-- L'EXÉCUTER : les deux rôles qu'il crée portent des noms FIXES, et un rôle
-- PostgreSQL est global à la GRAPPE, pas à la base. Sur une grappe partagée
-- par deux cerveaux, `arac_memory_writer` du premier EST celui du second.
-- Ce défaut est connu et remis (cf `tests/test_g1_aucun_nom_partage_entre_
-- cerveaux.py`, où ces deux noms sont listés) ; il n'est pas corrigé ici.
-- N'appliquez ce fichier que sur une grappe qui ne porte qu'un cerveau, ou
-- après avoir renommé les deux rôles.
--
-- Aucun outil de ce dépôt n'applique ce fichier : ni Alembic, ni le
-- bootstrap, ni la CI. C'est une application MANUELLE, et délibérée.
-- Rollback    : 07_roles_least_privilege_v1_6d_rollback.sql (inverse exact)
-- Idempotence : ré-exécution sûre (IF NOT EXISTS via DO block, GRANT idempotent).
-- ============================================================================

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'arac_proposal_queue_writer') THEN
        CREATE ROLE arac_proposal_queue_writer NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'arac_memory_writer') THEN
        CREATE ROLE arac_memory_writer NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA arac TO arac_proposal_queue_writer, arac_memory_writer;

-- Writer de la file de proposals : cycle de vie des statuts, jamais les colonnes sources.
GRANT SELECT, INSERT ON arac.incoming_proposal_queue TO arac_proposal_queue_writer;
GRANT UPDATE (status, reject_reason, updated_at)
    ON arac.incoming_proposal_queue TO arac_proposal_queue_writer;

-- Writer mémoire : INSERT only (+SELECT pour preflight dedup/counts). Pas d'UPDATE/DELETE.
GRANT SELECT, INSERT ON arac.memory_atoms TO arac_memory_writer;

COMMIT;
