"""ARAC — Control Center : collecteurs READ-ONLY (V1.7B / T2).

Doctrine : OBSERVE FIRST. DO NOT CONTROL. + READ ONLY.

Ce sous-package regroupe les COLLECTEURS de l'état du cerveau ARAC. Trois
familles, toutes en lecture pure :

  - ``db_metrics``      : métriques PostgreSQL (rôle ``arac_readonly``,
                          ``default_transaction_read_only=on``). SELECT only.
  - ``system_metrics``  : état système via subprocess sous ALLOWLIST stricte
                          de binaires NON mutateurs (git, df, ss, tmux,
                          systemctl en lecture seule).
  - ``reports_council`` : fichiers du repo (docs/*.md, DECISIONS.md) + sessions
                          Council dry-run (metadata only, jamais de transcript).

Garanties structurelles (vérifiées statiquement par les tests) :
  - Aucun INSERT / UPDATE / DELETE / TRUNCATE / DROP dans ces modules.
  - Aucun verbe système mutateur (start/stop/restart/enable/disable/kill/...)
    hors de l'allowlist-de-refus défensive.
  - Chaque collecteur est résilient : une source injoignable retourne un dict
    ``{"error": ...}`` (ou une liste vide) plutôt que de lever une exception.
"""

from control_center.collectors import db_metrics, reports_council, system_metrics

__all__ = ["db_metrics", "system_metrics", "reports_council"]
