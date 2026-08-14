# Pourquoi ARAC augmente Claude au lieu de le remplacer

Ce document explique le pari. Pas les fonctionnalités — le pari. Il est court, et il
contient les raisons pour lesquelles vous pourriez décider de **ne pas** installer ARAC.

> **Il se lit en troisième.** [`POURQUOI.md`](POURQUOI.md) explique en sept marches
> pourquoi tout ceci existe ; [`CE-QUE-ARAC-N-EST-PAS.md`](CE-QUE-ARAC-N-EST-PAS.md)
> lève les six confusions et dit quand un autre outil est meilleur. Ce document-ci
> suppose les deux lus, et s'occupe de ce qui reste : ce qu'on parie, et ce qu'on risque
> de perdre.

---

## 1. Claude oublie, et ce n'est pas un défaut

Ouvrez une conversation avec Claude. Passez deux heures à décider quelque chose de
difficile. Fermez la fenêtre. Rouvrez-en une : il ne sait plus qui vous êtes.

Le réflexe est d'appeler ça une limite. C'est une **propriété**. Un modèle sans état est
rapide, parallélisable, bon marché, et il ne conserve rien de vous. Ces quatre qualités
découlent de la même absence. Un modèle qui se souviendrait de tout serait plus lent, plus
cher, et il constituerait un dossier sur vous chez quelqu'un d'autre.

L'oubli n'est donc pas à réparer. Il est à **compenser** — et pas au même endroit.

## 2. Deux facultés, et une seule vous manque

Raisonner et retenir sont deux choses différentes. Un cerveau humain les sépare aussi :
la mémoire de travail tient quelques éléments pendant quelques secondes, la mémoire à long
terme tient des années et raisonne très mal.

| | Ce que ça fait | Qui le fait bien |
|---|---|---|
| **Raisonner** | Comprendre, arbitrer, formuler, écrire | Claude, remarquablement |
| **Retenir** | Traverser le temps sans se déformer | Claude, pas du tout |

Le constat qui fonde tout le reste : **la faculté rare, aujourd'hui, n'est pas
l'intelligence. C'est la continuité.**

Vous avez accès, pour quelques dizaines d'euros par mois, à un raisonnement de très haut
niveau, disponible à trois heures du matin, infatigable. Ce que vous n'avez pas, c'est
que ce raisonnement sache ce que vous lui avez déjà dit. Vous re-expliquez votre contexte
à chaque conversation. Vous reprenez les mêmes décisions parce que vous avez oublié
pourquoi vous les aviez prises. Vous retombez dans un piège dont vous êtes déjà sorti il
y a huit mois.

Ce n'est pas un problème d'intelligence. C'est un problème de mémoire.

## 3. Ce qu'ARAC essaie de faire, et ce qu'il n'essaie pas

ARAC **n'essaie pas** de rendre Claude plus intelligent. Il ne réentraîne rien, il
n'ajuste rien, il ne remplace aucun raisonnement.

Il essaie de lui donner un **passé**.

```
   Claude seul            :  raisonnement × 0 mémoire  =  un très bon inconnu
   Claude + ARAC          :  raisonnement × votre passé =  quelqu'un qui vous connaît
```

C'est une division du travail, pas une compétition. L'un raisonne, l'autre retient. La
question n'est jamais « lequel est le meilleur » — c'est « lequel fait quoi ».

Cette division a une conséquence pratique importante : **ARAC survit au changement de
modèle.** Vos atomes ne sont pas dans un modèle, ils sont dans votre base PostgreSQL, sur
votre serveur, en texte lisible. Le jour où vous changez d'outil de raisonnement, votre
mémoire ne bouge pas. C'est exactement l'inverse d'un système où le savoir vit dans un
fournisseur.

## 4. Ce que l'automatisation vous retire

La comparaison avec un outil de notes est traitée ailleurs — qui fait le rangement, pour
qui c'est écrit, et quand Obsidian reste le meilleur choix : voir
[`CE-QUE-ARAC-N-EST-PAS.md`](CE-QUE-ARAC-N-EST-PAS.md). Il reste ici la part qui relève
du pari, et elle est rarement dite.

Écrire une note **est** une façon de penser. En reformulant, vous comprenez mieux. En
choisissant où ranger, vous décidez ce que la chose est. En reliant, vous découvrez des
rapprochements que personne ne vous aurait suggérés.

**ARAC vous prive de tout ça.** Le savoir arrive rangé sans que vous ayez fait l'effort de
le ranger — donc sans le bénéfice cognitif de cet effort.

Ce n'est pas un mauvais échange pour tout le monde, mais ce n'en est pas un bon pour tout
le monde non plus. Si vous *aimez* tenir vos notes, si le fait de les écrire vous sert à
penser, ARAC vous retire quelque chose de réel. Il s'adresse à ceux qui ne les tiennent
pas — et qui, s'ils sont honnêtes, savent qu'ils ne les tiendront jamais.

Les deux peuvent d'ailleurs coexister. Rien dans ARAC ne vous demande de fermer votre
outil de notes.

## 5. Pourquoi c'est un pari, et pas une évidence

Quatre paris, tous discutables. Ils sont énoncés ici pour que vous puissiez décider en
connaissance de cause.

### Pari n° 1 — l'extraction automatique vaut mieux que la note délibérée

**Ce qui joue contre.** Vous, vous savez ce qui compte. La machine devine. Sur le cerveau
observé pendant huit mois, quatre types d'atomes — décision, piège, état, motif —
représentent 74 % du savoir réellement utile : le reste est du remplissage honnête mais
tiède. Un humain motivé aurait écrit moins et mieux.

**Ce qui joue pour.** Un humain motivé n'existe pas tous les jours. Cent atomes tièdes
écrits automatiquement pendant huit mois valent mieux que dix atomes excellents écrits
pendant trois semaines, puis plus rien. Le pari porte sur la **constance**, pas sur la
qualité par unité.

### Pari n° 2 — le rappel sémantique vaut mieux que la recherche dans vos notes

**Ce qui joue pour.** Vous retrouvez sans avoir mémorisé d'étiquette. Vous demandez
« combien je facture » et l'atome qui dit « politique tarifaire » remonte. Aucune
recherche textuelle ne fait ça.

**Ce qui joue contre, et c'est mesuré.** Sur le cerveau observé, **96 % des rappels
tombent en confiance basse**. Le système trouve, mais il doute — et il a raison de le
dire. Un rappel qui répond « voici quelque chose, mais je ne parierais pas dessus » n'est
pas la même expérience qu'un souvenir humain qui vous revient avec certitude.

C'est le pari le moins tranché des quatre. Il est aussi le plus honnêtement instrumenté :
la confiance est mesurée, affichée, et calibrée sur des distances réelles plutôt que sur
des seuils choisis à l'avance.

### Pari n° 3 — le coût vaut la peine

**Le coût est réel, récurrent, et il ne diminue pas.** Sur le rythme observé : trois
cycles par jour, environ 87 000 jetons par cycle, environ 31 500 jetons par atome produit.
Convertissez-le en votre monnaie avant d'installer, pas après.

Vous payez tous les jours pour un bénéfice qui n'arrive que **le jour où vous cherchez
quelque chose** — et ce jour-là est imprévisible. C'est la structure économique d'une
assurance, et elle est psychologiquement désagréable : la dépense est certaine et
quotidienne, le gain est incertain et rare.

Si ce paragraphe vous fait hésiter, il a fait son travail. Un framework qui cache son coût
d'exploitation n'est pas honnête.

### Pari n° 4 — une mémoire que vous n'avez pas écrite est encore la vôtre

Le pari le plus inconfortable, et il n'est pas technique.

Un souvenir humain, vous l'avez vécu. Une note, vous l'avez choisie. Un atome, vous ne
l'avez **ni vécu comme tel, ni choisi**. Un modèle a lu votre conversation et a décidé que
cette phrase-là méritait de survivre.

Est-ce encore votre mémoire ? Ou une interprétation de votre mémoire, produite par
quelqu'un d'autre, que vous consulterez comme un fait ?

ARAC ne tranche pas. Il fait une chose : il rend l'interprétation **traçable**. Chaque
atome porte sa provenance — la conversation, les messages exacts. Vous pouvez toujours
remonter au texte d'origine et juger vous-même.

C'est aussi pourquoi la perte de provenance mesurée sur le cerveau observé — **76 % des
atomes ne pouvaient plus dire d'où ils venaient**, après un changement de format — n'était
pas un incident technique parmi d'autres. C'était une atteinte au fondement : un atome
sans provenance n'est plus une mémoire vérifiable, c'est une affirmation qu'on croit ou
qu'on ne croit pas.

## 6. Ce qui découle de tout ça, dans le code

Les principes de conception d'ARAC ne sont pas des goûts. Ce sont des conséquences
directes des paris ci-dessus.

**Rien n'est caché.** Coût, prérequis, dépendances externes, ce qui ne marche pas encore :
en première page. Parce que le pari n° 3 ne peut être pris que par quelqu'un d'informé.

**Chaque chiffre porte ses lignes.** Une métrique du cockpit sans requête de preuve ne
peut littéralement pas être créée : l'objet refuse de s'instancier. Parce que le pari n° 4
n'est tenable que si l'interprétation reste vérifiable.

**Rien n'est effacé.** Une décision révisée devient `superseded`, elle ne disparaît pas.
L'histoire de votre pensée est une donnée, pas un déchet.

**Ce qui ne peut pas être prouvé est déclaré inconnu.** Une fraîcheur absente n'est jamais
traitée comme une fraîcheur bonne. Une sonde qui ne joint pas la base répond « inconnu »,
jamais « tout va bien ». Transformer une panne d'observation en bonne nouvelle est
l'erreur la plus coûteuse d'un système de surveillance.

**L'humain arbitre.** Le cerveau propose, il ne décide pas. La détection de contradiction
n'existe pas ; le rappel affiche son doute au lieu de le lisser ; la file de revue attend
un humain. Un cerveau qui trancherait à votre place ne serait pas un cerveau, ce serait un
avis.

## 7. Quand ARAC ne sert à rien

Trois cas, dits franchement.

**Si vous ne parlez pas beaucoup à Claude.** ARAC digère des conversations. Sans matière,
il tourne à vide et coûte quand même.

**Si vous ne regardez jamais votre cockpit.** Un cerveau dont personne ne lit les mesures
dérive sans que ça se voie. Les atomes orphelins posés sur des racines nues — près d'un
souvenir actif sur onze — n'ont pas été trouvés par une alarme : ils ont été trouvés parce
que quelqu'un a regardé un chiffre qui n'allait pas. Sans cette curiosité régulière, ARAC est un journal coûteux.

**Si vous cherchez un assistant.** ARAC ne vous rappelle rien, ne vous propose rien, ne
vous relance pas. Il se souvient. C'est tout — et c'est déjà beaucoup plus difficile que
ça n'en a l'air.

---

## En une phrase

Claude raisonne mieux que vous ne le ferez seul, et oublie tout. ARAC ne raisonne pas du
tout, et n'oublie rien. Ensemble, ils font quelque chose qu'aucun des deux ne fait —
à condition que vous acceptiez d'en payer le prix, d'en regarder les mesures, et d'arbitrer
vous-même quand ils se contredisent.

---

| Pour | Lire |
|---|---|
| Les sept marches — pourquoi tout ceci existe | [`POURQUOI.md`](POURQUOI.md) |
| Les six confusions, et quand un autre outil est meilleur | [`CE-QUE-ARAC-N-EST-PAS.md`](CE-QUE-ARAC-N-EST-PAS.md) |
| Les cinq notions du produit | [`CONCEPTS.md`](CONCEPTS.md) |
| La chaîne technique complète | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Le vocabulaire | [`GLOSSAIRE.md`](GLOSSAIRE.md) |
