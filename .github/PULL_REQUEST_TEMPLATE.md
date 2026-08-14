<!--
La case qui compte dans ce gabarit est « CE QUE J'AI RÉELLEMENT EXÉCUTÉ ».
Tout le reste peut se déduire du diff ; ça, non.

La doctrine complète est dans docs/CONTRIBUER.md. Le résumé tient en trois
phrases : aucune donnée simulée, chaque chiffre traçable jusqu'à sa source,
une absence de mesure ne s'affiche jamais comme un zéro.
-->

## Ce que ça change, et pourquoi

<!-- Deux ou trois phrases. Le manque d'abord, la solution ensuite. -->

Ferme #

---

## Ce que j'ai réellement exécuté

<!--
Les commandes, telles que vous les avez tapées, avec ce qu'elles ont rendu.
Ce qui n'a pas été exécuté se déclare ici — c'est attendu, ce n'est pas un
reproche. Un correctif « écrit, non exercé » reste utile ; un correctif
présenté comme éprouvé alors qu'il ne l'est pas coûte cher à tout le monde.
-->

```
$ make test
…

```

- [ ] `make test` — vert
- [ ] `make doctor`
- [ ] exécuté contre une **vraie** base / un **vrai** serveur
- [ ] jamais exécuté en conditions réelles — et c'est dit ci-dessus

---

## Les trois règles

- [ ] **Aucune donnée simulée.** Aucun jeu de démonstration, aucune valeur de repli à
      la place d'une mesure absente, aucune sortie inventée dans la documentation. Les
      exemples plausibles sont désignés comme tels, en toutes lettres.
- [ ] **Chaque chiffre est traçable.** Toute métrique ajoutée porte sa définition, sa
      formule, sa requête de preuve et ses seuils. L'arithmétique est en SQL.
- [ ] **Aucune absence affichée comme un zéro.** Les indisponibilités portent leurs
      quatre champs : `state`, `reason`, `gesture`, `substitute`.

## L'hygiène du dépôt

- [ ] **Aucune trace personnelle** — nom, société, lieu, scope réel, chemin de machine,
      identifiant de poste. Tout chemin est paramétré (`ARAC_HOME`, `ARAC_DB`,
      `ARAC_NODE_ID`…).
- [ ] **Aucun secret**, même « de test ». `.env` reste hors de git.
- [ ] **Rien ne dépense sans le dire.** Aucun appel payant déclenché par un test, une
      cible de `Makefile` ou une commande de diagnostic.
- [ ] **La suite reste hermétique** : les nouveaux tests ne demandent ni base, ni
      réseau, ni clé — ou se déclarent ignorés.

## Si vous avez touché à la base

- [ ] migration **additive**, `downgrade` écrit
- [ ] aucune suppression silencieuse — le modèle est le remplacement (`superseded_by`)
- [ ] **le format de `source_ref` est intact.** Une clé ajoutée, jamais renommée : c'est
      la seule structure qui relie ce que le cerveau sait à l'endroit où il l'a appris,
      et 76 % du corpus de référence a été délié par un renommage.

## Si ça se voit

- [ ] documentation mise à jour **dans cette proposition**
- [ ] le document modifié **enseigne** : il dit pourquoi, pas seulement quoi
- [ ] `CHANGELOG.md` complété, avec la mention « écrit, non exercé » si c'est le cas

---

## Ce que ça peut casser

<!--
Soyez précis. « Rien » est une réponse acceptable si elle est argumentée ;
c'est rarement la vraie.
-->
