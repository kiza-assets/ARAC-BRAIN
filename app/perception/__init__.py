"""La PERCEPTION : ce que le cerveau capte, et surtout ce qu'il ne capte pas.

Trois moteurs purs, aucune connexion ouverte ici :

``source_registry``     le registre honnête des sources — chaque source déclare
                        si elle est captée, exclue, ou trouée. Une source non
                        déclarée est un angle mort ; une source déclarée
                        `uncovered` est un trou ASSUMÉ, visible au cockpit.
``ingest_watchdog``     le chien de garde : une source captée qui se tait plus
                        longtemps que son délai annoncé est signalée.
``conservation_audit``  la question la plus difficile : ce qui est ENTRÉ
                        est-il toujours retrouvable ? Une conversation ingérée
                        dont plus aucun atome ne descend est du savoir perdu
                        en silence.

POURQUOI CE PAQUET EXISTE SÉPARÉMENT : la mémoire répond à « qu'est-ce que je
sais ? ». La perception répond à « qu'est-ce que j'aurais dû savoir ? ». Un
cerveau qui ne pose que la première question est confiant sur un corpus
mutilé — et il n'a aucun moyen de s'en apercevoir.
"""

