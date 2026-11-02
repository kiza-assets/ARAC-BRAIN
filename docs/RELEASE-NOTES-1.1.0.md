# ARAC BRAIN — notes de version 1.1.0

*Le cerveau cesse de tourner à vide.*

---

## Ce qui change pour vous

- **Un souvenir n'est plus perdu pour une clé mal écrite.** Une clé avec majuscules,
  accents ou séparateurs est normalisée au lieu de faire quarantiner tout le run. Si la clé
  normalisée tombait sur celle d'un autre souvenir du même document, elle est refusée comme
  avant.
- **Plus de cycles vides en boucle.** Un message géant en tête de file pouvait faire sortir
  chaque cycle en `empty` et répéter la même alerte sans fin. Désormais la réduction de
  tranche (bisection) se relâche après un cycle vide, le message est dédoublonné dans la
  file de revue, et la conversation est mise de côté 7 jours (rien n'est perdu, le curseur
  n'avance pas). Un message reconnu comme artefact d'outillage est sauté ; la liste des
  débuts reconnus se règle par `ARAC_OVERSIZED_SKIP_PREFIXES` (12 à 120 caractères chacun).
  Voir [`DEPANNAGE.md`](DEPANNAGE.md) « Les cycles sortent vides en boucle ».
- **Sécurité : le jeton du bot d'alerte n'est plus écrit dans les journaux.** Si vos
  journaux antérieurs ont été conservés ou partagés, renouvelez ce jeton.
- **L'installation marche sur une machine neuve — et c'est observé.** pgvector 0.7.0 au
  moins est exigé dès le début (Ubuntu 24.04 livre 0.6.0 : le remède active le dépôt
  PGDG, voir [`INSTALLATION.md`](INSTALLATION.md)) ; le test d'acceptation accepte une
  machine vierge. Sur un exécuteur GitHub nu, huit des neuf étapes sont **PROUVÉES**, de
  l'installation à la désinstallation ; la neuvième (« voir son cerveau apprendre ») reste
  partielle sans clé, comme prévu.
- **CI** : les deux workflows sont verts sur GitHub.
- **Feuille de route** : [`ROADMAP.md`](ROADMAP.md) gagne « cap après 1.1 : la confiance
  dans la mémoire » (PROSPECTIF).

## Comment mettre à jour

```bash
git pull
# puis redémarrez les services du curateur (selon votre installation)
```

Aucune migration de base. Aucun réglage nouveau n'est obligatoire.

## Ce qui n'est pas prouvé

- Le SQL de saut et de mise de côté, et le relâchement de la bisection, n'ont été joués que
  par des tests hermétiques : **écrit, non exercé** sur une base réelle.
- « Voir son cerveau apprendre » n'est prouvé qu'avec une clé de curation ; la CI n'en a pas.
- Les limites de la 1.0.0 restent valables : [`LIMITES-CONNUES.md`](LIMITES-CONNUES.md).

Le détail, ligne par ligne : [`CHANGELOG.md`](../CHANGELOG.md).
