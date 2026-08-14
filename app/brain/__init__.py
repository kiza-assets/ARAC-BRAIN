"""Les moteurs PURS du cerveau — zéro base de données, zéro réseau, zéro écriture.

Ces modules répondent à des questions sur le savoir sans jamais y toucher :
quels scopes existent réellement, où le cerveau dérive de sa propre doctrine,
quel est son état de santé, ce qu'un scope autorise ou interdit.

Ils vivaient à l'origine dans `scripts/`, trouvés par bricolage de `sys.path`.
Ils sont ici parce qu'ils sont du MOTEUR : `app/routers/brain.py` en dépend, et
une dépendance de l'API n'est pas un script d'exploitation.

Règle du paquet : aucun module ici n'ouvre de connexion, n'appelle de service
distant, ni n'écrit en mémoire. On leur passe des données, ils rendent un
jugement. C'est ce qui les rend testables sans infrastructure — et c'est
pourquoi la suite de tests tourne sans PostgreSQL.
"""

