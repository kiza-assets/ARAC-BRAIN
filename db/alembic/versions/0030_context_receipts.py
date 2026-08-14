"""`arac.context_receipts` — ledger APPEND-ONLY du Context Engine SHADOW
(V5 « Cerveau Cognitif », moteur `ce-shadow-r3pur-v1`).

Une row par exécution du shadow R3-pur simplifié dans `recall()` : ce que le
chemin SERVI a retourné (`served_ids`, vérité prod, JAMAIS modifiée par le
shadow) face à ce que le shadow AURAIT servi (`shadow_ids`, `[]` si abstention
`no_confident_context` — l'abstention est un fait receipt-grade, elle produit
une row). C'est la matière première de la compétition adversariale mesurée
(divergence servi/shadow, gain du fix scope-préfixe via
`scope_prefix_gain`, distribution des bandes, latence).

ZÉRO PII / ZÉRO TEXTE (règle V0.107 +) : pas de texte de
requête (seulement `query_sha256`), pas de `value`/`key` d'atome (seulement
des uuid), pas de nom d'opérateur. `scope_filter`/`kind_filter` sont les
filtres DEMANDÉS par l'appelant (paths de scope lowercase / kinds d'enum),
pas du contenu. `shadow_error` (PROSPECTIF — toujours NULL aujourd'hui :
reçu et kNN vivent dans le même savepoint, une erreur annule le reçu entier ;
colonne réservée à un futur reçu d'erreur persistant) est un TYPE d'erreur
(nom de classe/code), jamais un message porteur de payload — contrat côté
écrivain (`app/services/context_shadow.py`), rappelé en COMMENT de colonne.

Sémantique des colonnes de décision (alignée `app/context/policy.py`) :
  - `raw_band` ET `final_band` sont TOUTES DEUX classées sur la distance
    top-1 FINALE post-modifiers (fraîcheur → confiance → cap ±0.20) :
    `raw_band` = bande AVANT l'override du profil consommateur (ex.
    canari_strict rétrograde tout != high à none), `final_band` = bande
    APRÈS, celle qui décide. La distance AVANT modifiers, elle, est
    `top1_distance_raw` — sa bande n'est PAS stockée : ne pas comparer
    `classify(top1_distance_raw)` à `raw_band`.
  - `shadow_distances` : distances FINALES post-modifiers, alignées 1:1 sur
    `shadow_ids`.
  - `stop_reason` : pourquoi la coupe s'est arrêtée — `budget` (coupe k),
    `exhausted` (moins de candidats que le budget), `no_confident_context`
    (abstention franche), `no_embedding` (embedding requête indisponible),
    `corpus_exhausted` (kNN vide).
  - `scope_prefix_gain` : nb d'ids shadow atteints UNIQUEMENT grâce à la
    greffe (`scope = $s OR scope LIKE $s||'/%'`), mesure de la valeur
    du fix avant tout portage au chemin servi.

Append-only PAR GRANTS (mirror `0021_d063_ingest_receipts`) : `arac_app`
(le hook shadow dans `recall()`) INSERT/SELECT, JAMAIS UPDATE/DELETE — un
reçu est un fait immuable, on n'édite pas l'histoire. `arac_agent` /
`arac_readonly` SELECT seul (analyse/cockpit).

⚠ DÉPLOIEMENT (PROSPECTIF) : la prod est au head `0019` — cette migration
s'empile sur la lignée `0020→0029` codée mais NON appliquée. Le
déploiement réel exigera d'appliquer `0020→0030` d'un coup, sous GO humain
explicite — hors périmètre du chantier shadow.

Downgrade : DROP TABLE (aucune autre table ne dépend de celle-ci).

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0030_context_receipts
Revises: 0029_d063_exclusion_motive_audit
Create Date: 2026-07-08
"""

from typing import Sequence, Union

from alembic import op
from db.alembic.roles import roles_arac

revision: str = "0030_context_receipts"
down_revision: Union[str, None] = "0029_d063_exclusion_motive_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS arac.context_receipts (
            id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            request_id           uuid,
            consumer             text NOT NULL DEFAULT 'unknown',
            engine_version       text NOT NULL,
            calibration_version  text NOT NULL,
            query_sha256         varchar(64) NOT NULL
                                     CHECK (query_sha256 ~ '^[0-9a-f]{64}$'),
            scope_filter         text,
            kind_filter          text,
            k_requested          integer NOT NULL
                                     CHECK (k_requested BETWEEN 1 AND 100),
            budget_k             integer NOT NULL CHECK (budget_k >= 1),
            served_ids           uuid[] NOT NULL,
            shadow_ids           uuid[] NOT NULL,
            shadow_distances     real[] NOT NULL,
            top1_distance_raw    real,
            top1_distance_final  real,
            raw_band             text
                                     CHECK (raw_band IN ('high', 'medium', 'low', 'none')),
            final_band           text
                                     CHECK (final_band IN ('high', 'medium', 'low', 'none')),
            stop_reason          text NOT NULL CHECK (stop_reason IN (
                                     'budget', 'exhausted', 'no_confident_context',
                                     'no_embedding', 'corpus_exhausted'
                                 )),
            scope_prefix_gain    integer NOT NULL DEFAULT 0
                                     CHECK (scope_prefix_gain >= 0),
            shadow_latency_ms    real NOT NULL,
            shadow_error         text,
            created_at           timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # Commentaires (contrat ZÉRO PII rappelé au plus près de la donnée).
    op.execute(
        "COMMENT ON TABLE arac.context_receipts IS "
        "'Ledger append-only du Context Engine SHADOW (ce-shadow-r3pur-v1). "
        "Une row par exécution shadow de recall(). ZERO texte/PII : ids + "
        "query_sha256 uniquement, jamais la requete ni le contenu des atomes.'"
    )
    op.execute(
        "COMMENT ON COLUMN arac.context_receipts.query_sha256 IS "
        "'sha256 hex de payload.query — JAMAIS le texte de la requete.'"
    )
    op.execute(
        "COMMENT ON COLUMN arac.context_receipts.served_ids IS "
        "'Ce que le chemin SERVI (prod, bit-identique) a retourne — verite de reference.'"
    )
    op.execute(
        "COMMENT ON COLUMN arac.context_receipts.shadow_ids IS "
        "'Ce que le shadow aurait servi ([] si abstention no_confident_context).'"
    )
    op.execute(
        "COMMENT ON COLUMN arac.context_receipts.shadow_distances IS "
        "'Distances FINALES post-modifiers, alignees 1:1 sur shadow_ids.'"
    )
    op.execute(
        "COMMENT ON COLUMN arac.context_receipts.scope_prefix_gain IS "
        "'Nb d''ids shadow atteints uniquement grace au fix scope-prefixe.'"
    )
    op.execute(
        "COMMENT ON COLUMN arac.context_receipts.shadow_error IS "
        "'PROSPECTIF — toujours NULL aujourd''hui (une erreur shadow annule le "
        "recu entier, savepoint commun). Si arme un jour : TYPE d''erreur (nom "
        "de classe/code), jamais un message porteur de payload.'"
    )

    # Index (analyse temporelle, ventilation par consommateur, distribution des bandes).
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_context_receipts_created "
        "ON arac.context_receipts (created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_context_receipts_consumer "
        "ON arac.context_receipts (consumer, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_context_receipts_band "
        "ON arac.context_receipts (final_band)"
    )

    # Grants (moindre privilège, mirror 0021) : arac_app écrit et lit, jamais
    # n'édite/supprime un reçu posé. arac_agent / arac_readonly lisent seuls.
    op.execute(f"GRANT SELECT, INSERT ON arac.context_receipts TO {R.app};")
    op.execute(f"GRANT SELECT ON arac.context_receipts TO {R.agent};")
    op.execute(f"GRANT SELECT ON arac.context_receipts TO {R.readonly};")
    # REVOKE défensifs (DEFAULT PRIVILEGES du schéma donnent arw à arac_app,
    # r à arac_agent — on ferme explicitement l'écriture pour les deux).
    op.execute(f"REVOKE UPDATE, DELETE ON arac.context_receipts FROM {R.app};")
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON arac.context_receipts FROM {R.agent};")

    op.execute(
        "DO $$ "
        "DECLARE seq_name text := pg_get_serial_sequence('arac.context_receipts', 'id'); "
        "BEGIN "
        f"  EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO {R.app}', seq_name); "
        f"  EXECUTE format('REVOKE USAGE ON SEQUENCE %s FROM {R.agent}', seq_name); "
        "END $$;"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS arac.context_receipts CASCADE")
