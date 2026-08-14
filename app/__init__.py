"""ARAC — l'API du cerveau.

Cette couche est le seul endroit par lequel un savoir entre dans la mémoire
ou en ressort. Tout le reste — agents, cockpit, ponts — passe par elle.

Trois choses s'y jouent, et rien d'autre :
  - la VALIDATION (`schemas/`)  : un scope hors taxonomie part en 422 avant
    d'avoir touché la base ;
  - la MÉMOIRE (`routers/atoms.py`, `routers/sessions.py`) : écrire un atome,
    le retrouver par sens, le remplacer sans jamais l'effacer ;
  - le CONTEXTE (`context/`, `repr/`) : ce que le cerveau ressort quand on
    lui pose une question, et la trace de pourquoi il a ressorti ça.

Aucune suppression physique n'existe ici. Un atome dépassé est SUPERSÉDÉ :
la version d'avant reste lisible. Un cerveau qui oublie ses erreurs
recommence.
"""
