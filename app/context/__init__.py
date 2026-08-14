"""Package `app.context` — ContextVars partagés + lib PURE du Context Engine.

Historique (shadow R3-pur simplifié) : ce package remplace l'ancien
module `app/context.py`. L'import public `from app.context import
request_id_var` est PRÉSERVÉ à l'identique — `request_id_var` vit ici même,
dans `__init__.py`, et cet `__init__` n'importe AUCUN sous-module de la lib
Context Engine : une calibration corrompue/absente ne peut donc jamais faire
échouer le démarrage de l'API (invariant shadow : bruyant, jamais fatal au
chemin servi). Les consommateurs de la lib importent explicitement
`app.context.policy` / `app.context.calibration` / `app.context.receipts` /
`app.context.shadow_scope`.

ContextVars partagés entre middleware FastAPI et services applicatifs.

`request_id_var` est `set` par le middleware request_id (`app/main.py`) à
chaque requête HTTP. Les services qui s'exécutent dans le contexte de cette
requête (embed(), futurs audit_writer, etc.) peuvent le lire via
`request_id_var.get()` pour propager l'ID de requête dans tous leurs logs
sans avoir à le passer en paramètre.

ContextVar isole proprement par tâche asyncio (une requête = une tâche), ce
qui évite les fuites entre requêtes concurrentes contrairement à des globals.
"""

from contextvars import ContextVar


request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
