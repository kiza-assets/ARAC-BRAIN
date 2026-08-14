"""ARAC — Control Center (cockpit d'observation READ-ONLY).

Doctrine : OBSERVE FIRST. DO NOT CONTROL.

Ce package est un cockpit de lecture pure du cerveau ARAC.
Il n'a AUCUNE capacité d'écriture sur la base de données, aucun endpoint
de mutation, aucun appel aux routes ARAC d'ingestion ou de modification.

Rôle PostgreSQL utilisé : arac_readonly (SELECT uniquement, aucun DML).
Connexion forcée read-only au niveau session (default_transaction_read_only=on)
en plus du rôle, couche défensive double.

Le Control Center consulte — il n'agit pas.
Toute consultation est auditée (cc_access.log, append-only, sans données
sensibles). Aucun atome n'est créé, modifié, archivé, ni supprimé depuis ici.
"""
