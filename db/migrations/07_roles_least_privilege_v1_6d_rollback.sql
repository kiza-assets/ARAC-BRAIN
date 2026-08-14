-- ============================================================================
-- ARAC — V1.6D — ROLLBACK des rôles least-privilege (inverse exact de 07)
--
-- Sans effet sur __ARAC_ROLE_APP__/__ARAC_ROLE_AGENT__/__ARAC_ROLE_READONLY__/arac_review_writer.
-- Échoue volontairement (et c'est voulu) si un objet appartient encore à un
-- de ces rôles — il n'y en a aucun par design (rôles d'écriture, pas owners).
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
--       -v ON_ERROR_STOP=1 -f db/migrations/07_roles_least_privilege_v1_6d_rollback.sql
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
-- ============================================================================

BEGIN;

-- Idempotent (Red-Team V1.6B→V1.8) : REVOKE seulement si le rôle existe encore,
-- pour qu'une ré-exécution du rollback ne casse pas sur un rôle déjà droppé.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'arac_proposal_queue_writer') THEN
        REVOKE ALL ON arac.incoming_proposal_queue FROM arac_proposal_queue_writer;
        REVOKE USAGE ON SCHEMA arac FROM arac_proposal_queue_writer;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'arac_memory_writer') THEN
        REVOKE ALL ON arac.memory_atoms FROM arac_memory_writer;
        REVOKE USAGE ON SCHEMA arac FROM arac_memory_writer;
    END IF;
END
$$;

DROP ROLE IF EXISTS arac_proposal_queue_writer;
DROP ROLE IF EXISTS arac_memory_writer;

COMMIT;
