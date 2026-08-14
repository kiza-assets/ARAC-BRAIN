"""Familles de métriques du cockpit — extension du registre sans conflit.

Chaque module de ce paquet exporte ``METRICS: tuple[Metric, ...]``. Le chargement
est déclaré dans ``control_center/cc_v1/registry.py::FAMILY_MODULES`` et tolère
l'absence comme l'échec : une famille cassée est journalisée dans
``registry.LOAD_ERRORS``, elle n'abat jamais le socle.

L'invariant G1 s'applique identiquement ici : le type ``Metric`` refuse toute
métrique sans preuve, d'où qu'elle vienne.
"""

from __future__ import annotations
