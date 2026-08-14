"""`arac.conversations` — traçabilité d'exclusion + audit de l'ack.

Le curseur `acked` (0015) marque une conversation comme « traitée, plus
jamais retentée » — mais avant ce chantier, RIEN ne distingue un ack normal
(curée avec succès) d'un ack d'EXCLUSION (conversation délibérément écartée
de la curation : purge Anthropic, doublon de source, contenu non curable,
décision opérateur manuelle, conversation de test). Cette migration ajoute
la traçabilité honnête ET verrouille la règle par CHECK : on ne peut plus
acker une conversation SANS dire pourquoi si ce n'est pas une curation
normale (`exclusion_reason` obligatoire dès que le motif n'est pas la
curation).

4 colonnes additives nullable (metadata-only, aucune réécriture de table) :
  - `exclusion_reason`   : texte libre, motif humainement lisible.
  - `exclusion_category` : taxonomie fermée (5 valeurs) pour agrégation
                            cockpit — `anthropic_temporary_purged` (source
                            disparue côté Anthropic avant capture),
                            `duplicate_source` (même contenu déjà capté par
                            une autre source), `no_curable_content`
                            (transcript vide/sans substance), `operator_manual`
                            (décision manuelle — JAMAIS de prénom/nom dans
                            `excluded_by`, cf règle no-PII des audit-refs),
                            `test`.
  - `excluded_at`        : horodatage de l'exclusion.
  - `excluded_by`        : identifiant de COMPOSANT/rôle (ex: `curator_v2`,
                            `operator_review`) — jamais une identité
                            personnelle.

Contrainte `conversations_exclusion_ack_check` : `acked = false OR
exclusion_reason IS NOT NULL` — un ack sans motif d'exclusion documenté
n'est valide QUE si la conversation a été curée normalement... NON, en
réalité cette contrainte est plus stricte : elle interdit tout `acked=true`
sans `exclusion_reason` renseigné. Posée `NOT VALID` puis `VALIDATE`
immédiatement dans la MÊME migration : les 204 rows existantes ont toutes
`acked=false` (relevé en prod 2026-07-06 — `SELECT acked, count(*) FROM
arac.conversations GROUP BY acked`), la VALIDATE est donc instantanée et sans
risque. `NOT VALID` reste la bonne pratique (ne bloque pas les writers
concurrents pendant l'ALTER) même quand on sait la VALIDATE triviale.

⚠️ Conséquence FUTURE (hors périmètre de cette migration, code = WP-B/C) :
le curateur normal devra désormais aussi renseigner `exclusion_reason` (ex:
'curated_normally') pour poser `acked=true`, ou cette contrainte le bloquera.
C'est voulu — la contrainte est documentée ici pour que WP-B/C ne soit pas
surpris.

Trigger `trg_conversations_ack_audit` (BEFORE UPDATE, SECURITY DEFINER,
propriétaire = rôle DDL des migrations — `arac_admin` dans ce schéma, PAS un
superuser `postgres` littéral : vérifié en prod que les triggers/functions
existants — `tg_set_updated_at`, `tg_auto_archive_low_confidence` — sont déjà
possédés par `arac_admin`, cohérent avec `DATABASE_URL_ADMIN` = le rôle qui
exécute les migrations) : à la transition `acked` false→true, INSERT une row
dans `arac.audit_log` (node_id=NEW.node_id, action='conversation_ack_exclusion',
result_summary=jsonb avec conversation_id/uid/catégorie/excluded_by).
SECURITY DEFINER garantit que l'audit est posé quel que soit l'appelant
(`arac_app` ou `arac_agent`, qui ont tous deux INSERT direct sur audit_log
de toute façon — la garantie ici est la NON-CONTOURNABILITÉ : impossible
d'acker sans laisser de trace, même si un futur code oublie de le faire
explicitement). `SET search_path = arac, pg_catalog` sur la fonction :
durcissement défensif standard des fonctions SECURITY DEFINER (le corps
qualifie déjà tous ses objets `arac.xxx`, mais fixer le search_path ferme
par construction le vecteur classique de détournement par shadowing d'un
objet non qualifié dans un schéma public modifiable par l'appelant).

Downgrade : DROP trigger + function, DROP la contrainte, DROP les 4 colonnes.
⚠️ PAS purement additif malgré l'apparence « colonnes nullable » : sur le
schéma 0022 (celui vers lequel on redescend), rien ne contraint plus
`acked`/`exclusion_reason` — mais un `acked=true` sans colonne
`exclusion_reason` (dropée) redeviendrait un motif d'exclusion PERDU EN
SILENCE, et un futur re-`upgrade` vers 0023 referait `ADD COLUMN
exclusion_reason` (NULL par défaut) PUIS `VALIDATE CONSTRAINT
conversations_exclusion_ack_check` — qui échouerait sur CETTE row même
(`acked=true AND exclusion_reason IS NULL`), cassant tout re-upgrade après
un downgrade (revue adversariale, finding 26). Le downgrade remet donc
`acked=false` sur les conversations exclues (`acked=true AND
exclusion_reason IS NOT NULL`) AVANT de dropper les colonnes de motif : le
TEXTE du motif est bien perdu (conséquence honnête d'un rollback de schéma),
mais la conversation redevient réévaluable par le curateur plutôt que de
rester bloquée dans un état qui casse toute ré-application future de cette
migration. Testé bout-en-bout (upgrade→exclusion→downgrade→re-upgrade sans
échec VALIDATE) sur cluster jetable, cf tests de migration de la vague.

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0023_d063_conversation_exclusion
Revises: 0022_d063_raw_message_revisions
Create Date: 2026-07-06
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0023_d063_conversation_exclusion"
down_revision: Union[str, None] = "0022_d063_raw_message_revisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE arac.conversations "
        "  ADD COLUMN IF NOT EXISTS exclusion_reason    text, "
        "  ADD COLUMN IF NOT EXISTS exclusion_category  text "
        "    CHECK (exclusion_category IN ("
        "      'anthropic_temporary_purged', 'duplicate_source', "
        "      'no_curable_content', 'operator_manual', 'test')), "
        "  ADD COLUMN IF NOT EXISTS excluded_at         timestamptz, "
        "  ADD COLUMN IF NOT EXISTS excluded_by         text"
    )

    op.execute(
        "ALTER TABLE arac.conversations "
        "DROP CONSTRAINT IF EXISTS conversations_exclusion_ack_check"
    )
    op.execute(
        "ALTER TABLE arac.conversations ADD CONSTRAINT conversations_exclusion_ack_check "
        "CHECK (acked = false OR exclusion_reason IS NOT NULL) NOT VALID"
    )
    op.execute(
        "ALTER TABLE arac.conversations "
        "VALIDATE CONSTRAINT conversations_exclusion_ack_check"
    )

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


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_conversations_ack_audit ON arac.conversations"
    )
    op.execute("DROP FUNCTION IF EXISTS arac.conversations_ack_audit()")
    op.execute(
        "ALTER TABLE arac.conversations "
        "DROP CONSTRAINT IF EXISTS conversations_exclusion_ack_check"
    )
    # Finding 26 (revue adversariale) : reset AVANT le DROP des colonnes de
    # motif — sinon une conversation exclue (acked=true + exclusion_reason)
    # redevient acked=true SANS AUCUN motif après ce DROP, et un re-upgrade
    # ultérieur échoue à la VALIDATE CONSTRAINT ci-dessus (exclusion_reason
    # ré-ajoutée à NULL par défaut). Le motif texte est perdu (honnête,
    # documenté dans le docstring), mais la conversation redevient
    # réévaluable au lieu de rester dans un état qui casse toute
    # ré-application future de cette migration.
    op.execute(
        "UPDATE arac.conversations SET acked = false "
        "WHERE acked = true AND exclusion_reason IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE arac.conversations "
        "  DROP COLUMN IF EXISTS excluded_by, "
        "  DROP COLUMN IF EXISTS excluded_at, "
        "  DROP COLUMN IF EXISTS exclusion_category, "
        "  DROP COLUMN IF EXISTS exclusion_reason"
    )
