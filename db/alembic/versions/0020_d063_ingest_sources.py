"""Registre des sources de perception — `arac.ingest_sources`.

Première migration de la vague « Perception V4 » (0020→0029). Le label 0024
est volontairement sauté ; l'en-tête de 0025 dit pourquoi.

Cette migration crée le registre honnête des sources de conversations que le
cerveau ARAC DEVRAIT capter — chaque row déclare explicitement si une source
est `captured` (ingérée), `excluded` (décommissionnée par design) ou
`uncovered` (trou de couverture connu, motif consigné). Objectif : rendre
visible ce qui N'EST PAS capté, plutôt que de laisser un angle mort silencieux
(WP-A/santé v2 lira cette table pour le cockpit).

Contenu STRICTEMENT ADDITIF :
  1. CREATE TABLE `arac.ingest_sources` (registre, clé naturelle `source_key`
     au format `<source_type>@<machine>`).
  2. Seed du nœud service de capture serveur, **inactif** : il existe pour que
     la source correspondante ait une cible FK propre, mais ne produira rien
     tant que la capture serveur n'est pas armée.
  3. Seed des DEUX sources du parcours standard, avec leur politique honnête :

       - `claude_code@<votre poste>`   `captured`, lag attendu 30 min.
         C'est le pont Mac → serveur : l'exportateur tourne chez vous et
         dépose les conversations de Claude Code.

       - `desktop_chat@claude.ai`      `uncovered`, motif consigné.
         La synchronisation des conversations Claude Desktop est livrée mais
         n'est PAS armée tant que vous n'avez pas chargé sa tâche planifiée.

POURQUOI `uncovered` ET NON `captured` PAR DÉFAUT — la leçon est structurelle :
déclarer capté ce qui ne l'est pas encore fait hurler le chien de garde en
continu pendant toute l'installation. On apprend alors à ignorer l'alarme, et
le jour où elle a raison, plus personne ne l'écoute. Le registre déclare donc
ce qui EST, pas ce qui devrait être. `uncovered` reste visible au cockpit,
avec son motif — c'est un trou ASSUMÉ, pas un angle mort.

Quand vous armez une source, faites basculer sa ligne :

    UPDATE arac.ingest_sources
       SET coverage_policy = 'captured',
           expected_max_lag_minutes = 60,
           exclusion_reason = NULL
     WHERE source_key = 'desktop_chat@claude.ai';

Tant que vous ne le faites pas, le chien de garde reste aveugle à cette
source. C'est le prix de l'honnêteté du registre, et il est explicite.

Grants (moindre privilège — registre géré par migrations/ops, pas par le
runtime applicatif) : SELECT pour `arac_app`/`arac_agent`/`arac_readonly`.
REVOKE défensif de INSERT/UPDATE sur `arac_app` (les DEFAULT PRIVILEGES du
schéma `arac` lui donnent `arw` sur toute nouvelle table — cf leçon 0015).
Les évolutions du registre passeront par une nouvelle migration ou par
`arac_admin` (déjà propriétaire complet par les DEFAULT PRIVILEGES).

Idempotence : `CREATE TABLE IF NOT EXISTS` + 2× `ON CONFLICT DO NOTHING`
(node puis sources) — un replay de l'upgrade est un no-op silencieux.

Doctrine : le DDL/DML est écrit à la main via op.execute. Jamais
l'autogenerate d'Alembic : un diff automatique propose de supprimer ce
qu'il ne comprend pas.

Revision ID: 0020_d063_ingest_sources
Revises: 0019_run_receipts
Create Date: 2026-07-06
"""

from typing import Sequence, Union

from alembic import op

import arac_runtime
from db.alembic.roles import roles_arac


def _lit(value: str) -> str:
    """Un litteral SQL. Alembic ne parametre pas `op.execute` en mode
    hors-ligne (`--sql`), donc on echappe explicitement."""
    return "'" + value.replace("'", "''") + "'"


#: VOTRE poste source, declare a l installation. Aucun defaut : deviner un
#: node_id reviendrait a ouvrir la porte que ce registre existe pour tenir.
_NODE = arac_runtime.node_id()

#: La partie « machine » de la cle naturelle `<source_type>@<machine>`.
_MACHINE = _NODE

#: Le pendant serveur : la machine ou tourne le cerveau produit, elle aussi,
#: des conversations.
_SERVER_MACHINE = f"{_NODE}-server"

_REASON_DESKTOP = 'La synchronisation des conversations Claude Desktop est livree mais non armee : sa tache planifiee reste a charger. Declaree uncovered plutot que captured, pour ne pas alerter en continu pendant l installation. Basculez cette ligne en captured le jour ou la synchro tourne vraiment.'

_REASON_SERVER = 'La capture des conversations Claude Code du SERVEUR lui-meme est livree mais non armee : son minuteur reste a installer. Meme raisonnement que la source desktop_chat ci-dessus.'


revision: str = "0020_d063_ingest_sources"
down_revision: Union[str, None] = "0019_run_receipts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    R = roles_arac()  # les cinq roles de CE cerveau (db/alembic/roles.py)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS arac.ingest_sources (
            source_key                text PRIMARY KEY
                                         CHECK (length(btrim(source_key)) > 0),
            node_id                   text NOT NULL
                                         REFERENCES arac.nodes(node_id) ON DELETE RESTRICT,
            source_type               text NOT NULL
                                         CHECK (source_type ~ '^[a-z][a-z0-9_]{0,63}$'),
            machine                   text NOT NULL
                                         CHECK (length(btrim(machine)) > 0),
            coverage_policy           text NOT NULL
                                         CHECK (coverage_policy IN ('captured', 'excluded', 'uncovered')),
            expected_max_lag_minutes  integer
                                         CHECK (expected_max_lag_minutes IS NULL
                                                OR expected_max_lag_minutes > 0),
            exclusion_reason          text,
            created_at                timestamptz NOT NULL DEFAULT now(),
            updated_at                timestamptz NOT NULL DEFAULT now(),
            -- Discipline honnêteté : un `captured` DOIT annoncer son lag attendu,
            -- un `excluded`/`uncovered` DOIT consigner un motif — pas de row muette.
            CONSTRAINT ingest_sources_honesty_check CHECK (
                (coverage_policy = 'captured' AND expected_max_lag_minutes IS NOT NULL)
                OR (coverage_policy IN ('excluded', 'uncovered') AND exclusion_reason IS NOT NULL)
            )
        )
        """
    )

    # Le nœud de capture serveur, INACTIF : il existe pour donner une cible FK
    # propre à la source correspondante, pas pour produire quoi que ce soit
    # aujourd'hui.
    op.execute(
        f"""
        INSERT INTO arac.nodes (
            node_id, account, owner, role,
            silent_warn_minutes, silent_critical_minutes, active
        )
        VALUES (
            {_lit(_SERVER_MACHINE)}, 'human', 'owner', 'service',
            300, 600, false
        )
        ON CONFLICT (node_id) DO NOTHING
        """
    )

    op.execute(
        f"""
        INSERT INTO arac.ingest_sources (
            source_key, node_id, source_type, machine,
            coverage_policy, expected_max_lag_minutes, exclusion_reason
        )
        VALUES
            ({_lit("claude_code@" + _MACHINE)}, {_lit(_NODE)},
             'claude_code', {_lit(_MACHINE)},
             'captured', 30, NULL),
            ('desktop_chat@claude.ai', {_lit(_NODE)},
             'desktop_chat', 'claude.ai',
             'uncovered', NULL, {_lit(_REASON_DESKTOP)}),
            ({_lit("claude_code@" + _SERVER_MACHINE)}, {_lit(_SERVER_MACHINE)},
             'claude_code', {_lit(_SERVER_MACHINE)},
             'uncovered', NULL, {_lit(_REASON_SERVER)})
        ON CONFLICT (source_key) DO NOTHING
        """
    )

    op.execute(f"GRANT SELECT ON arac.ingest_sources TO {R.app};")
    op.execute(f"GRANT SELECT ON arac.ingest_sources TO {R.agent};")
    op.execute(f"GRANT SELECT ON arac.ingest_sources TO {R.readonly};")
    # REVOKE défensif (DEFAULT PRIVILEGES du schéma arac donnent arw à arac_app).
    op.execute(f"REVOKE INSERT, UPDATE ON arac.ingest_sources FROM {R.app};")


def downgrade() -> None:
    op.execute(
        "DELETE FROM arac.ingest_sources WHERE source_key IN ("
        + _lit("claude_code@" + _MACHINE)
        + ", 'desktop_chat@claude.ai', "
        + _lit("claude_code@" + _SERVER_MACHINE)
        + ")"
    )
    op.execute("DELETE FROM arac.nodes WHERE node_id = " + _lit(_SERVER_MACHINE))
    op.execute("DROP TABLE IF EXISTS arac.ingest_sources CASCADE")
