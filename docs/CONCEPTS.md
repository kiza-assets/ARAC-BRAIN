# Les cinq notions — ce qu'il faut avoir compris avant d'installer

Ce document n'explique pas comment se servir d'ARAC. Il explique **de quoi ARAC est
fait**. Cinq notions, dans l'ordre : chacune a besoin de la précédente, aucune ne se
saute.

| | La notion | La question à laquelle elle répond |
|---|---|---|
| 1 | **L'atome** | Qu'est-ce qu'un souvenir, au juste ? |
| 2 | **Le scope** | Où ce souvenir habite-t-il ? |
| 3 | **L'embedding** | Comment une machine peut-elle chercher du *sens* ? |
| 4 | **Le rappel** | Comment une question retrouve-t-elle un souvenir ? |
| 5 | **La preuve** | Pourquoi devrais-je croire ce que le cerveau affiche ? |

**Sur les chiffres de ce document.** Ils viennent d'un cerveau réel, observé pendant
huit mois d'usage quotidien, environ 1 700 atomes. Ce sont des **mesures**, pas des
moyennes de l'industrie ni des menaces. Elles sont citées parce qu'un utilisateur
prévenu ne refait pas la même faute — et parce qu'un framework qui ne montre que ses
succès n'apprend rien à personne.

---

# 1. L'atome

## Une conversation n'est pas une mémoire

Vous avez une longue conversation avec Claude. Deux cents messages. À la fin, vous avez
choisi PostgreSQL plutôt que SQLite, vous avez découvert que l'extension vectorielle
refuse les vecteurs de plus de 2 000 dimensions dans un index classique, et vous avez
renoncé à une idée qui vous plaisait.

Cette conversation est **complète**. Elle est aussi **inutilisable**. Elle est
chronologique là où votre besoin futur sera thématique. Elle contient dix fois plus de
mots que de savoir. Les trois choses que vous voudrez retrouver dans six mois y sont
noyées parmi cent quatre-vingt-dix-sept messages d'exploration, d'erreurs corrigées et
de politesses.

Une conversation est une **trace**. Elle prouve que quelque chose s'est passé. Elle ne
vous dit pas quoi.

## Une mémoire n'est pas un atome

Supposons que vous notiez, le soir, dans un carnet : « aujourd'hui j'ai réglé le
problème d'index vectoriel ». C'est une mémoire. Elle est courte, elle est datée, elle
est à vous.

Elle est aussi **muette hors de son contexte**. « Le problème d'index vectoriel » —
lequel ? Réglé comment ? Dans six mois, cette phrase ne vous rendra pas la solution :
elle vous rappellera seulement que vous l'aviez trouvée. C'est la frustration la plus
banale de la prise de notes, et c'est exactement ce qu'ARAC cherche à éliminer.

## L'atome : la plus petite chose qui reste vraie toute seule

Un atome est une unité de savoir qui **survit à la disparition de son contexte**.

Le test est simple, et il est le seul qui compte :

> Lisez cet atome dans six mois, seul, sans la conversation dont il vient, sans vous
> souvenir de la journée. Vous dit-il encore quelque chose de vrai et d'actionnable ?
> Si vous devez retrouver la conversation pour le comprendre, ce n'est pas un atome.

En pratique, un atome porte :

| Champ | Ce que c'est |
|---|---|
| `kind` | Le **type** de savoir — décision, piège, état, motif… (voir plus bas) |
| `scope` | Le **domaine** où il vit (notion 2) |
| `key` | Un identifiant court en minuscules-tirets, unique dans son scope |
| `value` | Le savoir lui-même, en clair |
| `rationale` | **Pourquoi**. Obligatoire pour une décision. |
| `source_ref` | D'où il vient : la conversation, les messages exacts |
| `confidence_score` | 0 à 100 — à quel point on y croit |
| `status` | `active`, `draft`, `superseded`, `archived`… |
| `embedding` | 3 072 nombres (notion 3) |

Exemple, écrit correctement :

```
kind      : gotcha
scope     : outillage/infrastructure
key       : index-vectoriel-limite-dimensions
value     : L'index vectoriel classique refuse les vecteurs au-delà de 2 000
            dimensions. Avec des vecteurs de 3 072, il faut stocker en demi-
            précision et indexer avec l'opérateur cosinus adapté à ce type.
rationale : Trois heures perdues sur une erreur d'index qui ne nommait pas la
            cause. Le message d'erreur parle de type, pas de dimension.
```

Il ne cite aucune date, aucun « aujourd'hui », aucun « comme on disait ». Il tient
debout tout seul. C'est ça, un atome.

## Les quatre types qui portent presque tout le savoir

ARAC accepte une vingtaine de types d'atomes. Quatre d'entre eux représentent **74 % du
savoir réellement utile** sur le cerveau observé. Ce n'est pas un hasard : ce sont les
quatre formes que prend l'expérience.

### `decision` — ce que vous avez choisi, et pourquoi

Le champ `rationale` est **obligatoire** pour ce type, et l'API refuse une décision qui
en manque. La raison est douloureusement pratique : une décision sans son pourquoi ne
vous empêche pas de refaire le débat six mois plus tard. Elle vous dit seulement que
vous l'avez déjà eu. Le savoir n'est pas dans le choix, il est dans l'arbitrage.

Une décision n'est jamais effacée quand elle est révisée. Elle passe au statut
`superseded` et pointe vers celle qui la remplace. Vous gardez ainsi la trace de
l'évolution de votre pensée — et la possibilité de comprendre pourquoi vous avez changé
d'avis.

### `gotcha` — le piège rencontré, et sa sortie

Le meilleur rapport valeur/octet de tout le système. Un `gotcha` vous rend exactement le
temps qu'il vous a coûté. C'est aussi le type le plus difficile à écrire à la main, parce
qu'au moment où vous sortez enfin du piège, la dernière chose dont vous avez envie est
de le documenter. C'est précisément pour ça qu'ARAC l'extrait automatiquement des
conversations : la machine n'est pas fatiguée.

### `state` — où en est une chose, maintenant

Le seul type qui **périme**. « Le serveur tourne en version 16 », « le dossier
d'assurance est chez le courtier » : vrai aujourd'hui, faux dans trois mois, et rien
dans le texte ne le signale.

C'est pour lui qu'existe la colonne `confirmed_until` — une date au-delà de laquelle
l'affirmation n'est plus garantie. Une leçon vaut d'être retenue : sur le cerveau
observé, **presque tout le corpus a cette colonne vide**. Le système traite une date
absente comme « fraîcheur inconnue », jamais comme « frais ». L'absence de preuve de
fraîcheur n'est pas une preuve de fraîcheur — c'est une règle qu'on ne peut pas relâcher
sans commencer à mentir.

### `pattern` — la forme que vous avez vue plusieurs fois

« À chaque fois que je change ce réglage, tel effet se produit trois jours plus tard. »
Un `pattern` est une régularité observée, pas une théorie. Il est plus rare que les
trois autres, et c'est normal : il faut plusieurs occurrences pour qu'une forme émerge.

### Et les types qui diluent

`note` et `idea` existent, et ils sont utiles. Mais un cerveau majoritairement peuplé de
`note` est redevenu un carnet : beaucoup de texte, peu de savoir portable. Si vous voyez
cette proportion monter dans le cockpit, ce n'est pas une panne — c'est le signe que la
consolidation extrait de la matière molle. Les autres types (`todo`, `question`,
`insight`, `reference`, `killed`…) ont chacun leur usage, mais aucun ne porte le poids
des quatre premiers.

## Un atome n'est pas encore une connaissance

Un atome est **un point**. Une connaissance est un **ensemble cohérent** de points : des
liens, des contradictions résolues, une hiérarchie entre ce qui est fondamental et ce
qui est de détail.

ARAC, aujourd'hui, produit des atomes en abondance et n'a qu'un **début** de graphe.
Le cycle écrit trois sortes d'arêtes dans une table dédiée : « ceci remplace cela »,
« ceci suivait cela dans la même conversation », et « ces deux atomes se ressemblent »
(voisinage vectoriel réciproque, sous un seuil). Deux choses doivent être dites
franchement à leur sujet :

- **Aucune de ces arêtes ne porte un rapport de sens.** « Se ressemble » n'est pas
  « confirme », et encore moins « contredit ». La géométrie ne fait pas la différence :
  « nous adoptons X » et « nous renonçons à X » sont, pour elle, deux textes très
  proches. **Aucun mécanisme ne détecte qu'un atome en contredit un autre** — deux
  affirmations opposées cohabitent en base sans que rien ne s'allume.
- **Aucun chemin de rappel ne lit cette table.** Elle est calculée, elle est fraîche,
  et elle n'est servie nulle part : ce que le cerveau vous rend vient de la distance
  vectorielle et du filtre de domaine, jamais de ces arêtes.

Autrement dit, ce qui existe est un **voisinage sémantique**, pas un graphe de
connaissances. C'est écrit ici en toutes lettres parce que c'est la limite la plus
importante à connaître avant d'installer — et parce qu'un lecteur venu du monde des
« graphes de connaissances » attendrait exactement l'inverse.

## La confiance, et le savoir jamais vérifié

Chaque atome porte une confiance à deux étages : un **score** de 0 à 100, et une
**origine** de confiance (`producer` par défaut — « c'est ce que la source disait » ;
`auditor_validated` — « quelque chose ou quelqu'un l'a vérifié »).

Sur le cerveau observé, **98 % du corpus n'a jamais été audité**. Autrement dit : le
cerveau est parfaitement à l'aise avec un savoir que personne n'a jamais confirmé. Ce
n'est pas un bug, c'est la conséquence d'un pipeline automatique — mais c'est une chose
à savoir quand une réponse vous paraît trop assurée.

### Ce que le score ne fait pas — et c'est presque tout

**Le score ne pèse pas sur le rappel.** Ni sur ce qui vous est rendu, ni sur l'ordre dans
lequel ça l'est. `POST /v1/atoms/recall` trie sur une pure distance de sens
(`ORDER BY embedding <=> votre question`), et rien d'autre n'entre dans ce tri. Deux
souvenirs au texte **identique**, l'un à 95 et l'autre à 10, sortent à la même distance —
et rien ne garantit que le plus sûr sorte le premier. L'organe qui pèserait la confiance
et la fraîcheur existe dans le code (`app/context/calibration.py`), mais il appartient au
Context Engine, dont les drapeaux sont **fermés par défaut** et que votre installation ne
pose pas.

Corollaire pratique, et il est libérateur : **monter ou baisser un score ne change rien à
ce que le cerveau vous répond.** Le score est un aveu, pas une commande. Vous pouvez
corriger un chiffre injuste sans craindre de déplacer quoi que ce soit.

### Ce que le score fait vraiment — un seuil, une seule fois, à la naissance

Il existe un garde-fou en base, et il est plus étroit que sa réputation. Le déclencheur
`arac.tg_auto_archive_low_confidence` est un **`BEFORE INSERT`** : il ne regarde que les
**écritures**, jamais les modifications. À l'instant où un atome est **écrit** en portant à
la fois la trace d'audit `autonomous_agent_suggest` et un score **strictement inférieur à
70**, la base le range aussitôt en `low_confidence_archive` — donc hors de tout rappel, qui
ne lit que les atomes `active`. À 69 il est archivé, à 70 il vit.

Trois conséquences, qui sont exactement les trois façons de se tromper ici :

- **Descendre un score ne déclasse rien.** `PATCH /v1/atoms/<id> {"confidence_score": 10}`
  rend `200`, l'atome reste `active`, et il continue d'être servi. Le déclencheur ne voit
  pas les `UPDATE`. Si vous vouliez retirer ce souvenir de la circulation, baisser son
  chiffre ne l'a pas fait : c'est `DELETE /v1/atoms/<id>` qui l'archive.
- **Un atome ordinaire n'est jamais concerné.** Sans la trace `autonomous_agent_suggest`,
  un atome écrit à 10 naît `active` et le reste. Et un atome **sans score du tout** —
  `confidence_score` accepte `NULL`, et c'est ce que rend un `POST /v1/atoms` qui ne le
  mentionne pas — n'est jamais archivé par ce seuil.
- **La curation ne déclenche jamais ce seuil.** Des douze types que le cortex a le droit
  de produire, un seul est un type auditeur et reçoit cette trace : `alert`. Or la
  politique de curation refuse une `alert` sous **80**, c'est-à-dire au-dessus du seuil
  d'archivage. Le chemin automatique ne peut donc pas fabriquer un atome que ce
  déclencheur archive : **il n'archive que ce que vous écrivez vous-même par l'API.**

### Le piège qui coûte un souvenir : la supersédure qui hérite

C'est le plus cher des trois, avec l'atome posé sur une racine, et il ne se voit pas.

Une supersédure **écrit un atome neuf**, donc elle passe sous le déclencheur. Et quand
elle ne dit rien du chiffre, le nouvel atome **hérite** du score de l'ancien. Superséder
une suggestion d'agent tombée sous 70 — ne serait-ce que pour corriger une tournure —
marque l'ancien `superseded` et fait naître le remplaçant `low_confidence_archive`. Il ne
reste alors **aucun** atome actif sur ce domaine et cette clé, et le rappel ne rend plus
rien. La réponse, elle, est un `201` : rien n'a échoué.

Depuis août 2026 l'API le **dit** : la réponse porte un avertissement nommé `W-008` —
*« L'atome écrit n'est pas actif : la base l'a rangé en « low_confidence_archive » à
l'insertion. Il ne ressortira d'aucun rappel. »* — et il est conservé dans
`arac.audit_log`. C'est un avertissement, pas un refus : **l'écriture a bien lieu, le
`201` reste un `201`**, et un appelant qui ne lit pas le champ `warnings` ne verra
toujours rien. Les avertissements n'empêchent jamais rien, ici comme ailleurs.

Les deux gestes qui évitent le piège :

- pour **abaisser** une confiance, faites-le par `PATCH` : c'est sans effet de bord ;
- pour **superséder** un atome dont le score est sous 70, passez `new_confidence_score`
  à 70 ou plus dans l'appel — ou remontez d'abord le score de l'original par `PATCH`.

> **Le nombre 70 apparaît dans deux rôles qu'il ne faut pas confondre.** Ici, il
> **archive** — mais seulement à l'écriture, et seulement avec la trace d'agent. Dans le
> cockpit, le même 70 ne fait qu'**étiqueter** : la fiche d'un domaine appelle « fragiles »
> les atomes sous ce score *et* ceux qui n'en ont pas, et elle rappelle elle-même le seuil
> qu'elle applique. Une étiquette qui compte n'a jamais rangé personne.

---

# 2. Le scope

## Pourquoi ranger, si la recherche est sémantique ?

C'est la première objection, et elle est bonne. Si la machine sait retrouver par le sens
(notion 3), à quoi bon des catégories ?

Parce que **la recherche classe, elle ne décide pas**. Elle vous rend les dix atomes les
plus proches de votre question, et elle les rendra même si aucun n'est pertinent : une
recherche par similarité retourne toujours un premier résultat. Le scope apporte quatre
choses qu'aucune proximité géométrique ne donne :

1. **Un filtre exact.** « Uniquement dans mes finances professionnelles » est une
   question à laquelle la géométrie ne sait pas répondre — mais un `WHERE` sait.
2. **Une cloison.** Votre vie privée et votre travail ne se mélangent pas dans un
   contexte envoyé à un agent, quoi qu'en dise la similarité.
3. **Un état courant par domaine.** ARAC peut maintenir un « où en est-on ? » par
   scope. Sans scope, il n'y a rien à résumer.
4. **Une unité de comptage.** Le cockpit compte, mesure et alerte par scope. Sans
   scope, tous les chiffres sont globaux, donc muets.

## Pourquoi exactement deux niveaux

Un seul niveau produit, au bout de six mois, une quarantaine de catégories plates que
plus personne ne tient cohérentes : `finance`, `finances`, `compta`, `argent` finissent
par coexister, et le savoir se dilue entre des jumeaux.

Trois niveaux et plus produisent l'effet inverse : personne ne se souvient si le savoir
est en `travail/finance/tva/declarations` ou en `travail/compta/tva`. La profondeur tue
le rangement qu'elle prétendait organiser.

Deux niveaux, c'est la profondeur à laquelle un humain garde tout l'arbre en tête. Une
**racine** est un monde de votre vie — quelque chose que vous ne confondez jamais avec
le reste. Une **feuille** est un rangement réel. Cinq à huit racines suffisent presque
toujours, trois à six feuilles chacune ; la profondeur maximale est un réglage de votre
taxonomie (`taxonomy.max_depth`, qui vaut 2 ou 3 — jamais plus), pas une constante du
code. L'ordre de grandeur est argumenté une seule fois, dans
[`COMMENT-IL-CREE-SES-SCOPES.md`](COMMENT-IL-CREE-SES-SCOPES.md) §5.

## Le piège n° 1 : l'atome posé sur une racine

**Un atome posé sur une racine nue devient un souvenir orphelin : présent, encore
rappelable par similarité pure, mais exclu de tout ce que le cerveau construit *au-dessus*
du rangement.** Sur le cerveau de référence, **près d'un souvenir actif sur onze** est
tombé dedans, et n'en est jamais ressorti par lui-même.

Voici le mécanisme exact, parce qu'une règle qu'on ne comprend pas ne se retient pas.
Une racine (`travail`) est un **conteneur** ; une feuille (`travail/finance`) est un
**rangement**.

### Ce dont un atome de racine n'est PAS exclu

`POST /v1/atoms/recall` sélectionne `status = 'active' AND embedding IS NOT NULL`, avec le
scope en filtre **facultatif**. **Il n'y a aucun filtre sur les feuilles.** Un atome posé
sur une racine, actif et porteur d'un embedding, **peut remonter** sur une question qui lui
ressemble. `context_for` ne filtre même pas du tout par scope. Écrire le contraire serait
vous mentir — et ce document l'a écrit.

Ce qui reste vrai, et qui est la moitié utile de l'ancienne formule : **une recherche qui
précise un domaine ne le trouvera jamais.** L'égalité de scope est stricte — une requête
sur `travail/finance` ne rend pas un atome rangé sur `travail`.

### Ce dont il EST réellement exclu — et c'est beaucoup

| Ce qu'il perd | Où c'est décidé |
|---|---|
| **L'état courant.** Un scope sans `/` est classé « racine nue » : jamais éligible à un état courant, jamais candidat à une proposition, score de maturité forcé à **0**. | `app/brain/scope_discovery.py` |
| **L'existence dans la vue des scopes.** `/v1/brain/current-state` **saute** les scopes racines. Ils ne sont pas « à zéro » : ils ne sont pas listés. | `app/routers/brain.py` |
| **La mesure de couverture.** Elle se calcule sur les feuilles **éligibles** seulement : un atome de racine ne compte ni au numérateur ni au dénominateur. | idem |

L'« état courant » est la synthèse qui répond à *« où en est ce sujet aujourd'hui ? »* — la
forme la plus utile qu'un cerveau puisse rendre. Un atome sur une racine n'y contribue
jamais, et ne le fera jamais.

C'est moins spectaculaire que « invisible ». C'est tout aussi coûteux sur la durée, et
**c'est vrai** — ce qui compte davantage, parce qu'une règle exagérée finit par n'être plus
crue du tout.

### Le cerveau vous le dit, au-dessus d'un seuil

L'anti-dérive lève l'avertissement **`W-STATE-007` — « dette de racine »** dès qu'une
racine nue porte au moins vingt atomes actifs, avec pour geste suggéré de proposer un
re-rangement vers des feuilles. *Proposition seulement — l'application reste humaine.*

**Déclarez donc au moins une feuille par racine utile.** Le générateur de taxonomie
refuse une racine sans feuille, et vous dit pourquoi.

## Pourquoi la liste est rigide

Un scope hors taxonomie est refusé deux fois : par l'API (erreur 422, avant même de
toucher la base) et par la base elle-même (clé étrangère vers la table des scopes). Deux
remparts, parce qu'un seul finit toujours par être contourné.

Cette rigidité est volontaire. Elle est le prix à payer pour que `travail/finance` reste
un territoire unique au lieu de se fragmenter. Elle a un coût : changer de taxonomie plus
tard est une migration, pas un renommage — les atomes déjà rangés doivent être déplacés,
et supprimer un scope emporterait le savoir qu'il contient. Le générateur refuse de
retirer un scope encore habité ; il vous dit lesquels et vous laisse décider.

C'est pour cette raison que la taxonomie est la **première** question de l'entretien
d'installation, et la décision la plus structurante de tout le système.

---

# 3. L'embedding

C'est la notion centrale. C'est aussi celle que la plupart des présentations expédient en
trois lignes — « on transforme le texte en vecteurs et on cherche les plus proches » — ce
qui n'explique rien et ne prépare à aucune des surprises. Prenons le temps.

> **Où cette notion intervient dans la chaîne — à fixer avant de lire la suite.**
> Beaucoup de systèmes voisins vectorisent **tout ce qui entre**, puis cherchent dans
> cette masse. ARAC fait l'inverse : le message qui arrive est écrit **en texte**, sans
> vecteur ; le curateur le **lit** ; et c'est seulement l'**atome** produit qui reçoit un
> vecteur. Sur le chemin réellement servi, trois vecteurs existent et **aucun n'est un
> message** : celui de l'atome, celui du résumé de session, et celui de votre question au
> moment du rappel. Retenez l'ordre : **on lit d'abord, on vectorise la conclusion
> ensuite.** Tout ce qui suit — coût, portée, limites — en découle.

## Le problème : une machine ne sait pas lire

Vous cherchez ce que vous aviez décidé au sujet de vos prix. Vous tapez « tarifs ».
L'atome dit « politique de **prix** revue à la hausse ».

`grep` ne trouve rien. Une recherche en texte intégral, même avec racinisation et
synonymes, ne trouve rien non plus : « tarif » et « prix » n'ont **aucune lettre en
commun**. Pour une machine qui compare des caractères, ces deux mots sont aussi éloignés
que « tarif » et « autruche ».

C'est le problème de fond : **le sens n'est pas dans les caractères**. Il faudrait
comparer les *idées*, et une idée n'est pas une chaîne de caractères.

## L'idée : donner à chaque texte des coordonnées

Un modèle d'embedding est un programme qui lit un texte et rend **une liste de nombres**.
Toujours la même longueur, quel que soit le texte : ici **3 072 nombres**, chacun un
décimal autour de zéro.

```
"politique de prix revue à la hausse"
        │
        ▼   modèle d'embedding
[ 0.014, -0.221, 0.087, ... , -0.003 ]      3 072 nombres
```

Ces 3 072 nombres sont des **coordonnées**. Le texte devient un point dans un espace à
3 072 dimensions.

Et voici la propriété qui fait tout marcher : le modèle a été entraîné de telle sorte que
**deux textes de sens voisin reçoivent des coordonnées voisines**. « tarifs » et « prix »
atterrissent à quelques centièmes l'un de l'autre. « tarifs » et « autruche » sont à
l'autre bout.

Comparer deux sens devient alors une opération que n'importe quel ordinateur sait faire
très vite : **mesurer une distance**.

## Que veut dire « 3 072 dimensions » ?

Prenons plus petit. Décrivez un vin avec deux nombres : sucre et acidité. Chaque vin
devient un point sur une feuille, et deux vins proches sur la feuille se ressemblent
vraiment. Vous venez de fabriquer un embedding à 2 dimensions.

Deux nombres ne suffisent pas pour un vin. Ajoutez tanin, alcool, âge : cinq dimensions.
On ne peut plus dessiner la feuille, mais la **distance** se calcule exactement pareil —
et elle veut toujours dire « se ressemblent ».

Un texte est infiniment plus riche qu'un vin. Il faut des milliers d'axes. 3 072, en
l'occurrence, parce que c'est ce que produit le modèle retenu.

**Attention au contresens le plus répandu.** Ces axes ne portent pas de nom. Il n'y a pas
un axe « sucre », un axe « politesse » et un axe « finance ». Personne n'a choisi ces
3 072 directions : elles ont **émergé** de l'entraînement. Prises isolément, elles ne
signifient rien — aucun humain ne peut dire ce que mesure la dimension 1 749. Seule la
configuration d'ensemble a un sens, et elle n'en a un que **relativement** : ce point est
plus près de celui-ci que de celui-là.

## L'analogie de la carte — et l'endroit précis où elle casse

Une carte routière est un embedding à 2 dimensions du territoire. Deux villes proches sur
la carte sont proches sur le terrain. Vous pouvez mesurer une distance à la règle, sans
rien savoir des villes.

L'analogie tient sur trois points, et casse sur trois autres. Les connaître vous évitera
la moitié des mauvaises surprises.

| Ce qui tient | Ce qui casse |
|---|---|
| La proximité mesurée approche la proximité réelle | Sur une carte, les axes ont un sens (nord, est). Ici, **aucun axe n'a de nom.** |
| On peut comparer sans comprendre le contenu | Une distance sur carte a une **unité** (le kilomètre). Ici, une distance n'a **aucune signification absolue** : 0,18 n'est ni « bon » ni « mauvais » dans l'abstrait, seulement plus proche que 0,31. |
| La carte est stable et réutilisable | Une carte est **fidèle** au territoire. Ici, la carte est un **résumé statistique** : le modèle a appris que certains textes apparaissent dans des contextes similaires. Ce n'est pas une définition du sens, c'en est une approximation. |

Ce dernier point est le plus important. Un embedding ne « comprend » rien. Il reflète des
régularités d'usage observées dans d'immenses quantités de texte. Que cette statistique
approche si bien notre notion de sens est un **fait empirique remarquable**, pas une
garantie logique. Toutes les limites qui suivent découlent de là.

## Mesurer la distance : pourquoi l'angle, et pas la longueur

ARAC utilise la **distance cosinus**. Elle mesure l'**angle** entre deux vecteurs, en
ignorant leur longueur.

```
        ▲                    Deux textes de même sens :
        │      ● A           même direction depuis l'origine,
        │    ●               angle petit  →  distance proche de 0.
        │   ● B
        │  ∕
        │ ∕                  Deux textes sans rapport :
        │∕                   directions divergentes,
        └──────────▶         angle large  →  distance proche de 1.
```

Pourquoi ignorer la longueur ? Parce que la longueur d'un vecteur reflète surtout la
longueur et l'intensité du texte. Un atome de deux lignes et un paragraphe de dix lignes
disant la même chose doivent être proches. En ne gardant que la direction, on compare
le **sujet** sans se laisser distraire par le volume.

En pratique, la distance cosinus va de 0 (même direction) à 2 (opposées). Sur du texte
réel, on observe surtout des valeurs entre 0,05 et 0,6.

## Ce que ça permet

- **Poser une question dans vos mots.** Vous cherchez « combien je facture », l'atome dit
  « politique tarifaire » : ils se retrouvent.
- **Retrouver sans avoir mémorisé d'étiquette.** Vous n'avez pas besoin de savoir comment
  vous aviez nommé la chose.
- **Détecter les doublons.** Deux atomes exprimant la même chose avec des mots différents
  sont géométriquement voisins. C'est ainsi que le cerveau évite de réapprendre ce qu'il
  sait déjà.
- **Franchir la barrière de langue**, partiellement — les modèles multilingues placent
  « prix » et « price » près l'un de l'autre.

## Ce que ça rate — et il faut le savoir avant, pas après

### La négation

C'est le défaut le plus contre-intuitif, et le plus coûteux.

```
"nous avons choisi PostgreSQL"          ─┐
"nous avons renoncé à PostgreSQL"       ─┴─ vecteurs TRÈS proches
```

Ces deux phrases parlent du même sujet, dans le même registre, avec presque les mêmes
mots. Géométriquement, elles sont voisines. **L'embedding voit le sujet, pas le verdict.**

Conséquence directe : le rappel vous rendra les deux, à peu près au même rang, et rien
dans les distances ne vous dira laquelle est vraie aujourd'hui. C'est aussi la raison de
fond pour laquelle une détection automatique de contradiction n'est pas triviale — et
pourquoi ARAC n'en a pas.

**Ce qui sauve la mise :** le statut. Un atome remplacé passe en `superseded` et sort du
chemin de lecture courant. C'est du SQL, pas de la géométrie. Ne comptez jamais sur
l'embedding pour arbitrer entre deux versions d'une vérité.

### Les identifiants et les nombres

```
"facture 4471"  et  "facture 4417"   →  quasiment le même vecteur
```

Un embedding est très mauvais avec les littéraux exacts : numéros, versions, références,
UUID. Deux identifiants qui diffèrent d'un chiffre sont, pour lui, presque le même texte.

C'est pourquoi le rappel prévoit un profil dit **strict**, réservé aux recherches
d'identifiants exacts : budget court et exigence de la meilleure bande de confiance,
faute de quoi il **s'abstient franchement** plutôt que de rendre un voisin plausible.
Rendre « facture 4417 » quand on demandait « 4471 » est bien pire que ne rien rendre.

### Le temps

Un vecteur ne porte **aucune date**. « Le serveur tourne en version 14 », écrit il y a
deux ans, est géométriquement aussi pertinent que la même phrase écrite hier.

La fraîcheur doit donc être une **colonne**, gérée séparément, et c'est le rôle de
`confirmed_until`. Le moteur en tient compte au moment du classement — mais seulement là
où la donnée existe, ce qui, on l'a vu, est rare.

### Les noms propres qui n'appartiennent qu'à vous

Le modèle a été entraîné sur du texte public. Le nom de votre entreprise, le surnom de
votre projet, votre jargon interne : il ne les a jamais vus. Il les place
approximativement, par analogie de forme. Les atomes qui reposent lourdement sur du
vocabulaire privé se rappellent moins bien. Ce n'est pas réparable ; c'est à savoir.

### Le contexte manquant

L'embedding porte sur le **texte de l'atome**, pas sur la conversation dont il vient. Un
atome mal écrit — allusif, dépendant de son contexte — reçoit un vecteur qui reflète
fidèlement son texte allusif. La géométrie ne répare pas une mauvaise rédaction. C'est un
argument de plus pour le test de la notion 1.

## Trois faits d'exploitation que rien ne rattrape

**Un embedding est un appel réseau à un prestataire externe.** Pas d'inférence locale.
Sans clé d'API, sans réseau, ou en cas de panne du prestataire, **aucun atome nouveau ne
peut être écrit et aucun rappel ne peut aboutir** — la recherche a besoin d'embedder
votre question, pas seulement vos souvenirs. C'est la dépendance externe la plus dure du
système.

**Un embedding coûte, mais peu.** Le tarif se compte en fractions de centime pour
plusieurs milliers de mots. Point crucial d'architecture : **seuls les atomes sont
embeddés, jamais les messages bruts.** Vous pouvez ingérer des centaines de milliers de
messages sans dépenser un centime d'embedding. Le vrai coût d'exploitation d'ARAC n'est
pas là — il est dans l'extraction (notion suivante, et le tableau des coûts en première
page du dépôt).

**Un embedding est prisonnier de son modèle.** Les 3 072 nombres n'ont de sens que dans
l'espace du modèle qui les a produits. Changer de modèle d'embedding, ou même de nombre
de dimensions, rend **tout le corpus incomparable d'un coup** : il faut tout recalculer.
Ce n'est pas une mise à jour, c'est une reconstruction. Choisissez tôt, et n'en changez
pas sans le décider explicitement.

## Où ça vit, concrètement

Chaque vecteur est stocké en demi-précision (2 octets par dimension) : **environ 6 Kio
par atome** en base, contre ~24 Kio si on le sérialisait en JSON — raison pour laquelle
l'API ne renvoie jamais le vecteur avec l'atome.

Un index approché accélère la recherche : au lieu de comparer votre question aux 1 700
atomes un par un, il navigue dans un graphe de voisinage et n'en examine qu'une fraction.
**« Approché » est un mot honnête** : cet index peut manquer un vrai plus proche voisin.
En échange, il rend le rappel quasi instantané même sur des dizaines de milliers
d'atomes. C'est un compromis assumé, pas un détail d'implémentation.

---

# 4. Le rappel

## Le trajet d'une question

```
  votre question, en français
        │
        ▼
  ① embedding de la question           (1 appel externe, ~200-300 ms)
        │
        ▼
  ② k plus proches voisins             SELECT … ORDER BY embedding <=> requête
     parmi les atomes ACTIFS              (index approché, distance cosinus)
     dont le vecteur existe
        │
        ▼
  les atomes rendus, chacun avec sa distance BRUTE
        ┊
        ┊  ── au-delà de ce trait, RIEN NE TOURNE sur une installation
        ┊     standard : les trois étages ci-dessous appartiennent au
        ┊     Context Engine, dont les drapeaux sont fermés par défaut.
        ▼
  ③ ajustements bornés                 fraîcheur → confiance → type
     (pondérations douces)               plafond total ±0,20, jamais un filtre
        │
        ▼
  ④ classement par bande de confiance  haute / moyenne / basse / abstention
        │
        ▼
  ⑤ budget du consommateur             k=3, k=10, ou strict
```

Retenez l'étape ②. Le filtre `status = 'active'` y est décisif : c'est **là** que les
atomes remplacés et les archives de faible confiance disparaissent du rappel. Ce n'est
pas la géométrie qui arbitre entre deux versions d'une vérité, c'est le statut.

> **Où s'arrête votre installation.** `POST /v1/atoms/recall` fait ① et ②, puis rend les
> atomes avec leur **distance brute** — pas de bande, pas de pondération, pas de budget.
> `POST /v1/atoms/context_for` ajoute les pierres angulaires et range par type, sans
> davantage d'ajustement. Les étages ③④⑤ vivent dans le Context Engine
> (`app/context/calibration.py`, `app/services/context_shadow.py`) et ne s'activent que
> derrière des drapeaux d'expérimentation — `ARAC_SHADOW_CE_ENABLED`,
> `ARAC_CE_SERVE_*` — que le bootstrap **ne pose pas**, et qui ne desservent que deux
> consommateurs internes. Vous pouvez le constater sur votre machine :
>
> ```bash
> sudo tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value arac-<base>-api.service)/environ \
>   | grep -E 'ARAC_SHADOW_CE|ARAC_CE_'      # ne rend rien après une installation nominale
> ```
>
> Ce qui suit décrit donc un organe **réel et lisible dans le code**, pas le comportement
> de votre rappel d'aujourd'hui. C'est aussi pourquoi la confiance ne déplace rien chez
> vous : l'étage qui la pèserait est celui-là.

## Les ajustements sont des pondérations, jamais des filtres

Trois organes peuvent modifier la distance d'un candidat, dans un ordre fixe :

- **Fraîcheur.** Un atome dont la date de confirmation est passée est *pénalisé*. Un
  atome confirmé dans le futur est *favorisé*. Un atome **sans date est traité comme
  inconnu, donc neutre** — jamais comme frais. Cet invariant est délibéré : l'absence
  d'information n'est pas une bonne nouvelle.
- **Confiance.** Score élevé : léger bonus. Score faible : légère pénalité. Score absent :
  neutre, même honnêteté.
- **Type.** Présent dans la chaîne mais **désactivé** — le gain n'a pas été confirmé au
  calibrage, et le système préfère un organe honnêtement inerte à un organe qu'on croit
  utile.

Deux garde-fous comptent :

1. L'ajustement **cumulé** est plafonné à ±0,20, même si les trois organes poussent dans
   le même sens.
2. Aucun ajustement n'**exclut** jamais un candidat. Il ne peut que déplacer son rang.
   L'exclusion reste le monopole de la bande de confiance et du budget, en aval.

Cette discipline a une raison : un filtre discret est indébogable. Quand un souvenir ne
remonte pas, vous devez pouvoir répondre à « pourquoi » — et un rang qui a bougé se
lit, alors qu'une ligne supprimée en silence ne se voit pas.

Chaque résultat conserve d'ailleurs sa distance brute **et** chaque ajustement appliqué :
le classement est auditable ligne à ligne.

## Les bandes de confiance

À l'issue du classement, la distance du meilleur résultat est traduite en une déclaration
lisible :

| Bande | Distance | Ce que ça veut dire |
|---|---|---|
| **haute** | ≤ 0,15 | Très probablement le bon souvenir. |
| **moyenne** | ≤ 0,23 | Plausible. À lire avant d'agir. |
| **basse** | ≤ 0,53 | Il y a quelque chose, mais je ne parierais pas. |
| **abstention** | au-delà | Je ne réponds pas. |

**Ces seuils ne sont pas des constantes choisies à l'avance.** Ils viennent d'un banc de
calibration : on a mesuré la distribution réelle des distances sur un corpus réel, et on
a coupé aux quantiles. C'est la différence entre un seuil et un vœu pieux.

Ils sont ensuite **gelés** : le fichier de calibration porte une version, et le
chargeur **refuse** tout fichier d'une autre version. On ne « met pas à jour » une
calibration en douce — on en grave une nouvelle, avec un nouveau nom. La raison est
simple : si les seuils bougent silencieusement, les mesures d'hier et celles
d'aujourd'hui ne sont plus comparables, et vous ne savez plus si votre cerveau s'améliore
ou si le thermomètre a changé.

Notez que **la bande basse répond quand même**. Elle avertit, elle ne censure pas. Seule
l'abstention se tait.

## Pourquoi 96 % des rappels sont en confiance basse

Sur le cerveau observé, **96 % des rappels tombent dans la bande basse**. Le chiffre
surprend. Il mérite d'être compris, parce qu'il dit quelque chose de vrai sur ce genre de
système.

Le rappel **trouve**. Il rend, la plupart du temps, un atome pertinent. Mais il **doute** :
la distance mesurée reste au-dessus de 0,23.

Trois causes, aucune n'étant une panne :

1. **Une question n'est pas un atome.** Vous demandez « qu'est-ce que j'avais décidé pour
   les prix ? » — c'est une interrogation, à la première personne, avec des mots vagues.
   L'atome est une affirmation dense et rédigée. Même sujet, formes très différentes,
   donc angle non nul. L'écart entre une question et sa réponse est structurel.
2. **Un corpus personnel est hétérogène.** Vos atomes couvrent des mondes sans rapport,
   écrits sur des mois, avec du vocabulaire qui vous appartient. Les distances y sont
   naturellement plus grandes que dans un corpus thématique homogène.
3. **Les seuils sont sévères, et c'est voulu.** Ils ont été coupés sur une distribution
   où « haute » devait vraiment vouloir dire haute. Un système qui annonce « confiance
   haute » sur tout n'informe plus de rien.

**La leçon à emporter :** ne confondez jamais *trouver* et *être sûr*. Un cerveau qui
rendrait le bon atome en annonçant systématiquement « confiance haute » serait plus
agréable et beaucoup moins fiable. La calibration compte autant que la recherche —
c'est elle qui vous dit quand relire avant d'agir.

## Le budget, par consommateur

Tous les usages n'ont pas besoin du même nombre de résultats. Trois profils existent :

| Profil | k | Particularité |
|---|---|---|
| Déduplication (le cerveau se relit) | 3 | Recherche ciblée, jamais large |
| Session interactive (par défaut) | 10 | Le profil courant |
| Strict | 3 | **S'abstient** si la bande n'est pas haute |

L'arrêt est **budgétaire seul** : on prend k résultats, on s'arrête. Un mécanisme
d'arrêt plus subtil, fondé sur l'écart entre résultats successifs, a été essayé au
calibrage et **retiré** — il n'apportait rien de démontrable. Ce genre de retrait mérite
d'être signalé : un organe conservé « au cas où » est une complexité que quelqu'un devra
déboguer un jour.

---

# 5. La preuve

## Le problème : un chiffre ne prouve rien

Votre cockpit affiche « Savoir invisible au rappel : 9 % ».

*(L'étiquette du cockpit dit « invisible ». Elle exagère : ces atomes-là restent
rappelables par similarité pure — voir « Le piège n° 1 » plus haut. Ce que le chiffre
mesure exactement, c'est la part du savoir posée sur une racine nue, donc hors de l'état
courant, de la vue des scopes et de la couverture. Le libellé du produit n'a pas encore
été repris ; la mesure, elle, est juste.)*

Pourquoi le croiriez-vous ? Ce chiffre a pu être calculé sur les mauvaises lignes,
arrondi dans le mauvais sens, mis en cache trois semaines, ou tout simplement écrit en
dur par quelqu'un qui voulait finir sa journée. Rien, dans l'affichage, ne permet de
distinguer une mesure d'une invention.

C'est un problème universel des tableaux de bord, et il est plus grave ici qu'ailleurs :
un cerveau qu'on ne peut pas vérifier ne mérite pas qu'on lui confie sa mémoire.

## La règle : aucun chiffre sans ses lignes

Dans ARAC, chaque métrique du cockpit déclare **deux** requêtes SQL :

- celle qui produit **la valeur** ;
- celle qui produit **les lignes sources** dont la valeur est issue.

Et la règle est transformée en **contrainte de type** plutôt qu'en consigne : le
constructeur de l'objet `Metric` **refuse de s'instancier** si la requête de preuve est
vide. Il n'existe donc aucun chemin par lequel un chiffre décoratif — un chiffre sans
lignes — puisse atteindre l'écran. Ce n'est pas une bonne pratique qu'on peut oublier un
vendredi soir : c'est une impossibilité.

Depuis n'importe quel nombre affiché, un clic donne les lignes qui le composent. Et
surtout : la réponse **contient le SQL exécuté**. Vous pouvez le coller dans un terminal,
le rejouer, et comparer.

## Le corollaire : le tableau de bord ne calcule pas

Second invariant, aussi important : **l'arithmétique appartient au moteur**.

Chaque métrique porte une requête qui produit sa **valeur finale**, division et
pourcentage compris. Ni le serveur d'affichage ni le navigateur ne font le moindre calcul
sur les données du cerveau.

Pourquoi cette sévérité ? Parce qu'un calcul fait en JavaScript est un calcul qu'on ne
peut pas rejouer depuis un terminal. Dès qu'une division se fait côté affichage, il
existe deux vérités possibles — celle de la base et celle de l'écran — et le jour où
elles divergent, rien ne permet de trancher.

Le cockpit se connecte d'ailleurs à la base avec un rôle **en lecture stricte**, et
aucune instruction autre que `SELECT` n'apparaît dans son registre — invariant vérifié
par un test qui inspecte le code source. Un tableau de bord ne doit pas pouvoir modifier
ce qu'il observe.

## Pourquoi c'est la propriété qui rend un cerveau croyable

Un cerveau se juge sur trois questions, et une seule d'entre elles se règle par de
l'ingénierie ordinaire :

1. *Sait-il retrouver ?* — Mesurable, testable, améliorable.
2. *Se trompe-t-il ?* — Difficile, partiellement traité.
3. **« *Comment le saurais-je ?* »** — C'est ici que tout se joue.

Sans preuve rejouable, la troisième question n'a pas de réponse, et la confiance devient
un acte de foi. Avec elle, chaque affirmation du système est **opposable** : vous pouvez
la contredire, avec vos propres yeux, sur les lignes réelles.

C'est aussi ce qui rend le diagnostic possible. Quand le cockpit annonce « 36 % des
cycles en quarantaine », la preuve vous donne les cycles concernés, avec leur motif. Sur
le cerveau observé, ce taux avait une cause qu'on ne pouvait pas deviner sans les lignes
sources : non pas des tranches de travail trop grosses comme on l'avait d'abord cru,
mais des **identifiants incohérents** dans les réponses du modèle d'extraction — une
majuscule là où le format n'en tolère pas. Trois jours de fausse piste, réglés par un
clic sur la preuve.

Le même principe explique une autre mesure du cerveau observé : **76 % de la provenance
perdue**. Un changement de format du champ `source_ref` avait coupé le lien entre les
atomes et les conversations dont ils venaient. Les atomes étaient intacts, mais ils ne
pouvaient plus dire d'où ils venaient. Un atome sans provenance n'est plus vérifiable :
il devient une affirmation qu'on croit ou qu'on ne croit pas.

**Figez le format de votre provenance tôt**, et ne le changez plus. C'est la deuxième
leçon la plus chère de ce projet, après celle des racines.

---

# Ce que vous savez maintenant

- Une conversation est une trace ; un atome est un savoir qui tient debout sans elle.
- Quatre types — décision, piège, état, motif — portent l'essentiel de ce qui sert.
- Le scope est un rangement à deux niveaux, et **un atome sur une racine est perdu**.
- Un embedding donne des coordonnées au sens ; il rate la négation, les identifiants
  exacts et le temps.
- Le rappel trouve souvent et doute presque toujours — et il a raison de le dire.
- Un chiffre sans ses lignes n'est pas une mesure, c'est une affirmation.

**Ce qui reste ouvert**, et qu'aucune de ces notions ne résout : les arêtes entre atomes
sont calculées mais **aucun chemin servi ne les lit**, rien ne détecte les
contradictions, et l'immense majorité du savoir n'est jamais auditée. Ces limites sont
détaillées dans [`ARCHITECTURE.md`](ARCHITECTURE.md), maillon par maillon.

Pour la vue d'ensemble du système : [`ARCHITECTURE.md`](ARCHITECTURE.md).
Pour le vocabulaire : [`GLOSSAIRE.md`](GLOSSAIRE.md).
Pour le pari de fond : [`PHILOSOPHIE.md`](PHILOSOPHIE.md).
