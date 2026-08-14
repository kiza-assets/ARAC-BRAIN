"""`arac.memory_atom_reprs` — représentations alternatives d'atomes,
APPEND-ONLY (FOLD V2, V5 « Cerveau Cognitif »).

Une row par (atome, version de représentation). Ce chantier n'écrit qu'UNE
`repr_version` : `'rm1-fold-a50'` — le champion gelé du banc
(`normalize(0.5·normalize(emb(T_meta)) + 0.5·normalize(mean(normalize(
emb(extrait_user≤256tok)))))`, calibration `rm1_calibration.json`).

Table d'OBSERVATION pure : rien du chemin servi ne la lit tant qu'aucun
flag serve-v2 n'existe (et aucun n'existe dans ce chantier — les bandes v1
ne sont pas transposables à la géométrie v2, consigné). Écrivain unique :
le batch borné `ARAC_V2_REPR_BUILD_ENABLED` (option B — jamais de
trigger/NOTIFY) ; lecteur : le shadow `ARAC_SHADOW_CE_V2_ENABLED`.

ZÉRO TEXTE DE SPAN / ZÉRO PII (règle V0.107) : la table ne stocke JAMAIS le
texte des messages sources ni le doc borné — `doc_sha256` est une EMPREINTE
seulement, `build` des métadonnées de construction (compteurs, tokens,
fallback), jamais du contenu. Contrat rappelé en COMMENT au plus près de la
donnée.

Append-only PAR GRANT (leçon 0015 : les DEFAULT PRIVILEGES donnent UPDATE à
arac_app sur toute nouvelle table — REVOKE explicite pour que « append-only »
soit vrai par construction, pas par convention) : `arac_app` SELECT+INSERT,
REVOKE UPDATE/DELETE ; `arac_agent`/`arac_readonly` SELECT seul. Pas de
séquence à granter (PK composite, pas d'IDENTITY).

`ON DELETE CASCADE` vers `memory_atoms` : l'API ne hard-delete jamais un
atome (soft-delete only) — la cascade ne joue qu'en purge admin
directe, et garantit alors qu'aucune repr orpheline ne survit.

Index HNSW partiel `WHERE repr_version = 'rm1-fold-a50'` (m=16,
ef_construction=64, modèle `ix_memory_atoms_embedding` / épinglage des paramètres HNSW) :
tout kNN v2 filtre sur cette version ; si d'autres versions cohabitent un
jour, elles ne polluent pas le graphe HNSW de la version observée. Même
vigilance `SET LOCAL hnsw.ef_search` côté lecteur que pour le shadow v1
(défaut pgvector 40 = troncature silencieuse des pools > 40).

⚠ DÉPLOIEMENT (PROSPECTIF) : cette migration s'empile sur `0030` (branche
feature, worktree fold-v2). L'application en prod exige un GO humain
explicite — hors périmètre de ce chantier (aucune écriture DB prod ici).

Downgrade : DROP TABLE (table nouvelle, aucune autre n'en dépend —
non destructif pour l'existant).

Doctrine : le DDL est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0031_memory_atom_reprs
Revises: 0030_context_receipts
Create Date: 2026-07-08
"""

from typing import Sequence, Union

from alembic import op
from db.alembic.roles import roles_arac

revision: str = "0031_memory_atom_reprs"
down_revision: Union[str, None] = "0030_context_receipts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS arac.memory_atom_reprs (
            atom_id       uuid NOT NULL
                              REFERENCES arac.memory_atoms(id) ON DELETE CASCADE,
            repr_version  text NOT NULL,
            embedding     halfvec(3072) NOT NULL,
            manifest_sha  text NOT NULL,
            doc_sha256    text,
            build         jsonb,
            created_at    timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (atom_id, repr_version)
        )
        """
    )

    # Commentaires (contrat ZÉRO TEXTE/PII + append-only, au plus près de la donnée).
    op.execute(
        "COMMENT ON TABLE arac.memory_atom_reprs IS "
        "'Representations alternatives d''atomes (fold v2, rm1-fold-a50). "
        "APPEND-ONLY par grants — une repr posee ne s''edite pas, on insere une "
        "autre (atom_id, repr_version). Table d''OBSERVATION : aucun chemin servi "
        "ne la lit (pas de flag serve-v2 dans ce chantier). ZERO texte de span "
        "stocke, ZERO PII : empreintes et metadonnees seulement.'"
    )
    op.execute(
        "COMMENT ON COLUMN arac.memory_atom_reprs.embedding IS "
        "'halfvec(3072) text-embedding-3-large — recette gelee rm1-fold-a50 "
        "(fold alpha=0.5 de emb(T_meta) et mean-pool des embeds user bornes "
        "256 tok cl100k ; degenere en emb(T_meta) seul sans span user).'"
    )
    op.execute(
        "COMMENT ON COLUMN arac.memory_atom_reprs.manifest_sha IS "
        "'sha256 du RECIPE canonicalise fige dans le writer prod — distinct du "
        "manifest_sha du banc (contexte source raw_messages direct).'"
    )
    op.execute(
        "COMMENT ON COLUMN arac.memory_atom_reprs.doc_sha256 IS "
        "'EMPREINTE sha256 hex du doc borne embedde — JAMAIS le texte du doc "
        "ni des spans (regle V0.107, zero PII).'"
    )
    op.execute(
        "COMMENT ON COLUMN arac.memory_atom_reprs.build IS "
        "'Metadonnees de construction (compteurs de spans, tokens, fallback "
        "T_meta-only, source de l''ancrage) — JAMAIS de texte de message ni de PII.'"
    )

    # Index HNSW partiel — modèle ix_memory_atoms_embedding (m=16/ef_construction=64,
    # paramètres HNSW épinglés). Partiel sur la seule version observée : le kNN v2 filtre toujours
    # repr_version='rm1-fold-a50' ; d'autres versions futures ne pollueraient pas
    # le graphe.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memory_atom_reprs_embedding "
        "ON arac.memory_atom_reprs "
        "USING hnsw (embedding halfvec_cosine_ops) "
        "WITH (m = 16, ef_construction = 64) "
        "WHERE repr_version = 'rm1-fold-a50'"
    )

    # Grants (moindre privilège, spec §3.4 — mirror 0021/0030) : arac_app écrit
    # et lit, jamais n'édite/supprime une repr posée. Lecteurs SELECT seul.
    op.execute(f"GRANT SELECT, INSERT ON arac.memory_atom_reprs TO {R.app};")
    op.execute(f"GRANT SELECT ON arac.memory_atom_reprs TO {R.agent};")
    op.execute(f"GRANT SELECT ON arac.memory_atom_reprs TO {R.readonly};")
    # REVOKE défensifs (leçon 0015 : DEFAULT PRIVILEGES donnent arw à arac_app,
    # r à arac_agent — on ferme explicitement l'écriture pour les deux).
    op.execute(f"REVOKE UPDATE, DELETE ON arac.memory_atom_reprs FROM {R.app};")
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON arac.memory_atom_reprs FROM {R.agent};")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS arac.memory_atom_reprs CASCADE")
