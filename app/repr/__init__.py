"""Package `app.repr` — lib PURE du write-path fold v2 (FOLD V2).

GARDE ANTI-BOOT (même modèle que `app/context/__init__.py`) : cet
`__init__` n'importe AUCUN sous-module de la lib — ni `recipe` (numpy +
tiktoken lazy), ni `spans`, ni `builder`. Un artefact corrompu ou une
dépendance manquante dans la lib repr ne peut donc JAMAIS faire échouer le
démarrage de l'API (invariant shadow : bruyant, jamais fatal au chemin
servi). Les consommateurs importent explicitement `app.repr.recipe` /
`app.repr.spans` / `app.repr.builder`.

Contenu du package :
  - `recipe.py`  : RECETTE prod GELÉE `rm1-fold-a50` — composition T_meta,
    borne user 256 jetons cl100k, fold α=0.5, MANIFEST_SHA. Les constantes
    viennent d'un banc de calibration mené hors dépôt ; elles sont GELÉES
    parce qu'un changement de recette invalide toutes les représentations
    déjà calculées (il faudrait tout recalculer, donc tout repayer).
  - `spans.py`   : extraction bi-format des textes user depuis
    `memory_atoms.source_ref` (cortex `message_ids` → `arac.raw_messages` ;
    legacy curator `curator_raw_id`+`message_indices` →
    `arac.raw_conversations.content_gz` gunzippé NDJSON).
  - `builder.py` : `build_repr(conn, embed_fn, atom_row)` — 2 embeddings max
    par atome, INSERT append-only `ON CONFLICT DO NOTHING` dans
    `arac.memory_atom_reprs`, BudgetLedger fail-closed AVANT toute dépense.
"""
