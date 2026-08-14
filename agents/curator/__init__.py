"""Agent CURATOR — v0.5 Vague 2 « Cerveau Vivant ».

5e agent applicatif de la triade ARAC (7e service systemd).
Subscribe le canal PG `conversation_ingested` (trigger sur INSERT dans
`arac.raw_conversations`), lance un subprocess Claude Sonnet 4.5 avec MCP
ARAC pour appliquer la politique de seuils par kind et extraire
des atomes cognitifs depuis les conversations Claude Code ingérées.

Modules :
  - main      : entrypoint asyncio (heartbeat + listen PG + dispatch)
  - policy    : politique HYBRID (seuils confidence par kind, anti-bruit)
  - prompt    : `CURATION_PROMPT_TEMPLATE` (string, ~200 lignes)
"""

__version__ = "0.5.0"
