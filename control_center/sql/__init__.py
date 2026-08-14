"""Control Center — module SQL partagé du cockpit PERCEPTION (V5 vague 1).

Contient uniquement `perception_queries` : les constantes SQL AUTORITAIRES
importées du code métier (jamais ré-écrites) + les requêtes propres au
cockpit, définies UNE seule fois (exécutées ET affichées depuis le même
objet — mécanisme anti-fabrication, cf round1-synthese.json).
"""
