"""`arac.run_receipts` — colonnes de conservation (couverture digestion).

Ajout additif sur `run_receipts` (0019) : la conservation-audit bout-en-bout
(WP-C) doit pouvoir répondre, PAR RUN, à « qu'est-ce que Claude a VU vs ce
qu'il a RETENU » — sans ces colonnes, un run peut silencieusement omettre
des messages (troncature de contexte, message surdimensionné écarté) sans
qu'aucune trace ne le distingue d'un run qui a simplement décidé qu'il n'y
avait rien à apprendre.

8 colonnes additives nullable/DEFAULT 0 (metadata-only, aucune réécriture) :
  - `messages_reported`            : nb de messages REPORTÉS/différés au
                                      cycle suivant (pas « présentés » —
                                      corrigé depuis ; cf
                                      usage réel, `agents/cortex/`).
  - `messages_truncated`           : nb de messages coupés avant présentation
                                      (contexte trop long).
  - `oversized_messages`           : jsonb, détail des messages écartés pour
                                      taille (id/longueur), pas juste un total.
  - `coverage_presented`           : nb de messages présentés (référentiel
                                      pour les 3 lignes suivantes).
  - `coverage_covered`             : nb de messages ayant produit un atome.
  - `coverage_no_new_knowledge`    : nb jugés sans connaissance nouvelle
                                      (couverts mais volontairement sans suite).
  - `coverage_omitted`             : nb ni couverts ni jugés "no new
                                      knowledge" — le vrai signal d'alerte
                                      (watchdog v4 : `coverage_omitted > 0`
                                      répété = fuite de perception).
  - `quarantine_attributed_uids`   : jsonb, liste des `conversation_uid`
                                      dont des extraits sont partis en
                                      quarantaine sur CE run (0019 a déjà
                                      `quarantine_output`/`quarantine_errors`
                                      au niveau run — ceci relie la
                                      quarantaine aux conversations sources).

Aucun changement de grants : ces colonnes héritent des grants déjà posés en
0019 sur la table (`arac_agent` RW, `arac_app`/`arac_readonly` SELECT).

⚠️ Nom de fichier volontairement long (`..._conservation.py`, cohérent avec
le nom du chantier WP-C « conservation-audit ») mais IDENTIFIANT `revision`
raccourci : `arac.alembic_version.version_num` est `varchar(32)` et
`0027_d063_run_receipts_conservation` fait 35 caractères (> 32) — même
contrainte déjà rencontrée par 0008 (cf son en-tête). Le fichier garde le nom
long pour la lisibilité de la vague « Perception V4 », mais `revision` utilise le slug
tronqué `0027_d063_run_receipts_conserv` (30 caractères).

Downgrade : retire les 8 colonnes. Non destructif (aucune n'est réécrite).

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0027_d063_run_receipts_conserv
Revises: 0026_d063_capture_manifests
Create Date: 2026-07-06
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0027_d063_run_receipts_conserv"
down_revision: Union[str, None] = "0026_d063_capture_manifests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE arac.run_receipts "
        "  ADD COLUMN IF NOT EXISTS messages_reported          integer NOT NULL DEFAULT 0, "
        "  ADD COLUMN IF NOT EXISTS messages_truncated         integer NOT NULL DEFAULT 0, "
        "  ADD COLUMN IF NOT EXISTS oversized_messages         jsonb, "
        "  ADD COLUMN IF NOT EXISTS coverage_presented         integer NOT NULL DEFAULT 0, "
        "  ADD COLUMN IF NOT EXISTS coverage_covered           integer NOT NULL DEFAULT 0, "
        "  ADD COLUMN IF NOT EXISTS coverage_no_new_knowledge  integer NOT NULL DEFAULT 0, "
        "  ADD COLUMN IF NOT EXISTS coverage_omitted           integer NOT NULL DEFAULT 0, "
        "  ADD COLUMN IF NOT EXISTS quarantine_attributed_uids jsonb"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE arac.run_receipts "
        "  DROP COLUMN IF EXISTS quarantine_attributed_uids, "
        "  DROP COLUMN IF EXISTS coverage_omitted, "
        "  DROP COLUMN IF EXISTS coverage_no_new_knowledge, "
        "  DROP COLUMN IF EXISTS coverage_covered, "
        "  DROP COLUMN IF EXISTS coverage_presented, "
        "  DROP COLUMN IF EXISTS oversized_messages, "
        "  DROP COLUMN IF EXISTS messages_truncated, "
        "  DROP COLUMN IF EXISTS messages_reported"
    )
