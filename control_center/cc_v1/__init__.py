"""Control Center v1 — BFF du cockpit vivant.

Paquet ADDITIF : il ne modifie aucune route ni aucun collecteur existant.

Sa règle unique — et la raison d'être du cockpit : **aucun chiffre affiché
sans la requête qui l'a produit.** Un tableau de bord qui montre un nombre
sans pouvoir le prouver enseigne la confiance aveugle ; le registre
(`registry.py`) rend cette faute impossible à commettre par construction.
"""

from __future__ import annotations

__all__ = ["registry", "service"]
