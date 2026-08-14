# Contribuer à ARAC-BRAIN

Merci d'être venu jusqu'ici. Le guide complet — comment le dépôt est organisé,
comment lancer les tests, ce que les gardes vérifient et pourquoi — vit dans
**[`docs/CONTRIBUER.md`](docs/CONTRIBUER.md)**.

Ce fichier-ci ne dit que l'essentiel, pour que GitHub le trouve et que vous ne
perdiez pas de temps.

## En trente secondes

```bash
make venv     # l'environnement
make test     # la suite, hermétique : ni base, ni réseau, ni clé
make lint     # la forme
```

`make test` doit être **vert sans qu'aucun service ne tourne**. Si un test rouge
vous dit « PostgreSQL n'est pas lancé », c'est le test qui a tort — signalez-le.

## Ce que ce projet attend d'une contribution

**Reproduisez avant de corriger.** Un correctif qui n'a pas de reproduction est
une hypothèse.

**Écrivez le contrôle qui aurait attrapé la faute**, et vérifiez qu'il rougit
quand vous réintroduisez le défaut. Un garde qui ne mord pas est une fausse
sécurité — ce dépôt en a rencontré plusieurs, et il a payé cher pour l'apprendre.

**N'énumérez pas : décrivez une forme.** Une liste de cas interdits oublie par
construction. Ce projet a corrigé cinq fois le même défaut sous cinq visages avant
de comprendre. Voir [`docs/DECISIONS-ARCHITECTURE.md`](docs/DECISIONS-ARCHITECTURE.md), DA-12.

**Ne recopiez pas ce que vous surveillez : allez le lire.** Deux listes tenues en
deux endroits divergent toujours. Voir DA-13.

**Une affirmation datée porte sa date, sa commande et son critère.** Un chiffre
exact périt au prochain ajout ; un critère survit. Voir DA-14.

## Ce qui fera refuser une contribution

- Du texte engendré librement dans une sortie utilisateur — le produit assemble
  des gabarits à partir de valeurs mesurées, jamais des phrases inventées.
- Une donnée absente affichée comme un zéro.
- Une trace de votre propre installation : nom, chemin, taxonomie, compteur.
  Un garde le vérifie et il balaie tout le dépôt.
- Un nom de rôle, de port, d'unité ou de dossier écrit en dur au lieu d'être
  dérivé du cerveau. Un autre garde le vérifie.
- Un contenu de souvenir écrit dans le journal système.

## Signaler un problème

Trois gabarits d'issue existent : **bogue**, **question**, **idée**. Prenez celui
qui correspond ; ils demandent ce dont nous avons besoin pour vous répondre.

Pour une faille de sécurité, **n'ouvrez pas d'issue** : voir
[`SECURITY.md`](SECURITY.md).

## Ce qui aide le plus, aujourd'hui

Le dépôt cherche en priorité des retours sur **ce qu'il n'a jamais pu éprouver
lui-même** — la liste est dans [`docs/LIMITES-CONNUES.md`](docs/LIMITES-CONNUES.md)
§2. En tête : **le pont depuis un vrai Mac**. Aucun de nos essais n'a de Mac.

Si vous installez ARAC-BRAIN et que quelque chose vous fait hésiter, dites-le même
si ce n'est pas un bogue. Un endroit où l'on doit deviner est un défaut de ce
projet, pas de son lecteur.
