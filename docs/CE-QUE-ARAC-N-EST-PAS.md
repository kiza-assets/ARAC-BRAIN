# Ce qu'ARAC n'est pas

ARAC ressemble à six choses qui existent déjà. Il n'en est aucune. Tant que la
ressemblance n'est pas levée, tout le reste de la documentation est lu de travers — vous
chercherez des fonctions qui n'existent pas et vous manquerez celles qui existent.

Ce document est frontal. Pour chacune des six confusions : **ce que c'est**, **pourquoi
on s'y trompe**, **ce qu'ARAC fait à la place**, et — le paragraphe qui compte le plus —
**quand l'autre outil est le bon choix**. Il y a des cas où c'est lui qu'il faut installer,
et ils sont dits.

| | La confusion | La phrase à retenir |
|---|---|---|
| 1 | Obsidian, Notion, un éditeur de notes | Vous n'écrivez rien et vous ne rangez rien. |
| 2 | Un RAG classique | Un RAG retrouve des passages ; ARAC retient des affirmations. |
| 3 | Un chatbot | ARAC ne répond pas. Il se souvient. |
| 4 | Une base vectorielle | pgvector est un composant, pas le produit. |
| 5 | Un tableau de bord | Le cockpit sert à comprendre un cerveau, pas à suivre des indicateurs. |
| 6 | Un remplaçant de Claude | Claude raisonne, ARAC retient. Ce sont deux métiers. |

---

# 1. Ce n'est pas Obsidian, ni un éditeur de notes

## Ce que c'est

Obsidian, Notion, Logseq, un dossier de fichiers Markdown : des outils où **vous** écrivez,
**vous** rangez, **vous** reliez. Ils sont excellents, matures, et ils font une chose
qu'ARAC ne fait pas du tout.

## Pourquoi on s'y trompe

Parce que le vocabulaire se recouvre : mémoire, notes, liens, graphe, recherche. Et parce
qu'ARAC répond au même besoin ressenti — « je ne retrouve plus ce que je savais ». Le
besoin est le même ; le moyen est opposé.

## Ce qu'ARAC fait à la place

**Rien n'est écrit à la main. Rien n'est rangé à la main. Il n'y a pas d'éditeur.**

Vous parlez à Claude comme vous l'auriez fait de toute façon. Trois fois par jour, la
digestion lit ce qui est nouveau et en extrait ce qui a l'air durable. Vous n'avez rien
noté, rien classé, rien relu. Il n'existe aucun endroit dans ARAC où vous écrivez une
note — et c'est délibéré, pas une fonctionnalité manquante.

La différence de fond n'est pas l'interface, c'est **qui fait le travail de classement**,
et surtout **quand**. Dans un outil de notes, ce travail vous incombe, juste après avoir
résolu le problème, au moment de la journée où vous en avez le moins envie. C'est là que
la plupart des systèmes de notes meurent : pas par manque d'outil, par manque de la
demi-heure quotidienne qu'ils exigent, indéfiniment.

Deuxième différence, moins visible et plus importante : **une note est écrite par un
humain pour un humain**. Elle a le droit d'être allusive, mal formée, dépendante du
contexte : vous la relirez et vous comprendrez. **Un atome est écrit par une machine pour
une machine**, et relu par vous en cas de doute. Il doit donc être auto-suffisant, typé,
daté, sourcé, rangé, vectorisé — des contraintes qu'aucun humain ne tient à la main
pendant huit mois.

## Ce qu'on perd, et il faut le dire

Écrire une note **est** une façon de penser. En reformulant, vous comprenez mieux. En
choisissant où ranger, vous décidez ce que la chose est. En reliant, vous découvrez des
rapprochements que personne ne vous aurait suggérés.

**ARAC vous prive de tout ça.** Le savoir arrive rangé sans que vous ayez fait l'effort de
le ranger — donc sans le bénéfice cognitif de cet effort.

## Quand Obsidian est le bon choix

**Si vous tenez réellement vos notes, gardez-les.** Pas par politesse : parce que vous
obtiendrez un meilleur résultat.

Un outil de notes est meilleur qu'ARAC quand :

- **écrire vous sert à penser** — vous perdriez l'essentiel en le déléguant ;
- **vous voulez décider vous-même ce qui mérite d'être retenu**, et vous le faites
  vraiment ;
- **vous voulez une structure que vous maîtrisez**, avec des liens que vous tracez et qui
  veulent dire quelque chose de précis ;
- **votre savoir n'arrive pas par des conversations** — vous lisez, vous observez, vous
  expérimentez, mais vous n'en parlez pas à une IA ;
- **vous ne voulez pas de coût récurrent** : un dossier Markdown est gratuit et le restera.

ARAC s'adresse à ceux qui **ne tiennent pas** leurs notes — et qui, s'ils sont honnêtes,
savent qu'ils ne les tiendront jamais. Cent atomes tièdes extraits automatiquement pendant
huit mois valent mieux que dix notes excellentes écrites pendant trois semaines, puis plus
rien. Le pari porte sur la **constance**, pas sur la qualité par unité. Si vous êtes
constant, vous n'avez pas besoin de ce pari.

**Et rien n'oblige à choisir.** ARAC ne demande à personne de fermer son outil de notes.
Ils ne se disputent pas le même geste.

---

# 2. Ce n'est pas un RAG classique

## Ce que c'est

Un RAG — *retrieval-augmented generation* — découpe des documents en morceaux, vectorise
chaque morceau, et, à chaque question, va chercher les morceaux les plus proches pour les
donner à lire au modèle. C'est l'architecture dominante pour interroger une base
documentaire, et elle marche très bien pour ça.

## Pourquoi on s'y trompe

Parce que les mots-clés sont identiques : embeddings, pgvector, similarité, recherche
sémantique, contexte injecté. Vu de loin, c'est la même pile technique. La différence
n'est pas dans les composants, elle est dans **ce qu'on met dedans**.

## La différence, par l'exemple

Vous demandez : *« qu'est-ce que j'avais décidé pour les sauvegardes ? »*

**Ce que rend un RAG classique** — le morceau de conversation le plus proche :

> *…et donc dans ce cas-là c'est mieux, oui. On part là-dessus alors ? — Oui, mais
> attention au point qu'on a évoqué tout à l'heure, sinon on va se retrouver dans la même
> situation qu'en mars.*

Le morceau est **authentique** et vient bien de la bonne conversation. Il est aussi
inutilisable : « ce cas-là », « là-dessus », « le point évoqué tout à l'heure » —
quarante messages plus haut —, « la situation de mars », que vous ne vous rappelez plus.
Vous avez retrouvé **l'endroit où le souvenir a été fabriqué**, et vous voilà à relire
deux cents messages.

**Ce que rend ARAC** — un atome, produit par un modèle qui a lu **toute** la conversation :

> **La sauvegarde du serveur est vérifiée par restauration réelle une fois par mois, et
> non par simple contrôle de la présence du fichier.**
> *decision · `infrastructure/sauvegardes` · datée · provenance : la conversation et les
> messages exacts · motif : une panne de mars a montré qu'une archive présente peut être
> illisible.*

Cette phrase **n'existe nulle part dans la conversation**. Personne ne l'a prononcée
ainsi. Elle est la synthèse de trois messages éloignés, dont un qui en corrigeait un
autre.

## Trois conséquences, pas une nuance

| | RAG classique | ARAC |
|---|---|---|
| **Ce qui est vectorisé** | tout ce qui entre, découpé | seulement l'**atome** extrait ; les messages sont stockés en texte, sans vecteur |
| **Quand le modèle lit** | **après** la recherche, pour rédiger la réponse | **avant** : il lit d'abord, il en tire une conclusion, et c'est elle qu'on vectorise |
| **Ce qui est rendu** | un extrait, fidèle et dépendant de son contexte | une affirmation autonome, datée, sourcée, typée, révisable |

La troisième ligne emporte tout le reste. Un RAG conserve le texte tel quel : il est
**fidèle** — il ne peut rien déformer, puisqu'il ne réécrit rien. ARAC produit une
interprétation : elle est **utilisable seule**, et elle peut se tromper. C'est un échange,
pas une supériorité.

C'est aussi pourquoi la provenance est traitée ici comme une propriété de premier rang :
puisque l'atome est une interprétation, il faut pouvoir remonter au texte d'origine et
juger soi-même. Un atome sans provenance est une rumeur bien rédigée.

## Quand un RAG classique est le bon choix

- **Quand la fidélité prime sur l'autonomie.** Contrats, réglementation, documentation
  technique, procédures : vous voulez la phrase exacte du document, pas un résumé qui a
  l'air juste. Ne mettez jamais un corpus juridique dans un système qui réécrit.
- **Quand le corpus est déjà rédigé pour être lu.** Un manuel est fait de paragraphes
  autonomes ; il n'a pas besoin qu'on en extraie des affirmations, il en est déjà fait.
- **Quand le corpus est partagé.** ARAC est bâti pour un corpus personnel, écrit dans
  votre vocabulaire, dont chaque fragment n'intéresse qu'une personne.
- **Quand vous ne pouvez pas payer une lecture complète.** Un RAG ne fait travailler le
  modèle qu'au moment de la question. ARAC le fait travailler à chaque digestion, sur tout
  ce qui est nouveau, que vous posiez une question ou non : **environ 87 000 jetons par
  cycle, trois cycles par jour, environ 31 500 jetons par atome conservé.**

---

# 3. Ce n'est pas un chatbot

## Ce que c'est

Une interface où l'on pose une question et où quelque chose répond en langage naturel.

## Pourquoi on s'y trompe

Parce qu'on interroge ARAC en français ordinaire, et qu'il rend quelque chose de lisible.
Le geste ressemble à une conversation. Il n'en est pas une.

## Ce qu'ARAC fait à la place

**ARAC ne répond pas. Il se souvient.**

Ce qu'il rend n'est pas une réponse rédigée pour vous : c'est un **ensemble d'atomes,
chacun avec sa distance brute, son domaine, sa date et sa provenance**. Pas d'étiquette
« confiance haute / basse » : la bande est un organe du Context Engine, éteint sur une
installation standard ([`CONCEPTS.md`](CONCEPTS.md) §4) — ce que vous lisez, c'est le
nombre, pas le mot. Il n'y a ni style, ni introduction, ni synthèse. Un rappel ressemble
davantage à une poignée de fiches sorties d'un tiroir qu'à une phrase.

C'est **Claude qui parle**. ARAC lui fournit ce que vous saviez ; Claude en fait une
réponse. Division du travail : l'un raisonne et rédige, l'autre retient et retrouve.

Trois conséquences directes :

- **ARAC ne prend jamais l'initiative.** Il ne vous rappelle rien, ne vous notifie rien,
  ne vous relance pas, ne vous suggère rien. Interrogé, il répond ; sinon, il se tait.
- **ARAC n'invente rien.** Il ne peut rendre que des atomes qui existent en base. Un
  rappel qui ne trouve rien de convaincant **s'abstient** au lieu de fabriquer.
- **ARAC affiche son doute.** Sur le cerveau observé, **96 % des rappels sont en confiance
  basse** : *« il y a quelque chose, mais je ne parierais pas dessus. »* Un chatbot ne
  parle jamais comme ça. Une mémoire honnête, si.

## Quand un chatbot est le bon choix

Presque toujours, en fait — pour tout ce qui n'est pas de la mémoire. Pour raisonner,
rédiger, expliquer, coder, arbitrer : ouvrez Claude, sans ARAC, et parlez-lui. Il est
excellent à ça et ARAC n'y ajoute rien tant que la conversation ne dépend pas de votre
passé.

ARAC ne devient utile qu'à partir du moment où la bonne réponse **dépend de quelque chose
que vous avez déjà décidé**.

---

# 4. Ce n'est pas une base vectorielle

## Ce que c'est

Pinecone, Weaviate, Qdrant, Chroma, ou pgvector employé seul : des moteurs qui stockent
des vecteurs et rendent les plus proches, très vite, très bien.

## Pourquoi on s'y trompe

Parce qu'ARAC en contient une. **PostgreSQL 16 avec pgvector, embeddings à 3 072
dimensions, distance cosinus, index approché.** C'est écrit dans l'architecture, c'est
vrai, et ça n'a jamais été le produit.

## Ce qu'ARAC fait à la place

Une base vectorielle répond à une question : *« quels sont les vecteurs les plus proches
de celui-ci ? »* C'est une question de **plomberie**, pas de mémoire. Toutes les questions
qui font une mémoire restent entières après y avoir répondu :

| La question | Qui y répond |
|---|---|
| Quels vecteurs sont les plus proches ? | la base vectorielle |
| **Qu'est-ce qui méritait de devenir un vecteur ?** | la curation — un modèle qui lit tout |
| **Cette affirmation tient-elle seule dans six mois ?** | la forme atome, et son test |
| **D'où vient-elle, et puis-je la vérifier ?** | la provenance |
| **A-t-elle été révisée depuis ?** | la lignée : un atome remplacé ne disparaît pas |
| **À quel point puis-je m'y fier ?** | les bandes de confiance, calibrées sur des distances réelles |
| **Comment je vois que mon cerveau dérive ?** | le cockpit, et ses preuves rejouables |

Le rapport est celui d'un moteur à une voiture. Le moteur est indispensable, il n'est pas
le véhicule, et changer de marque de moteur ne changerait presque rien à ce qu'est ARAC.

Un détail qui le montre bien : **sur le chemin réellement servi, aucun message n'est
vectorisé.** Trois vecteurs existent — celui de l'atome, celui du résumé de session, celui
de votre question. Une base vectorielle employée seule aurait vectorisé les messages, et
c'est précisément la conception qu'ARAC a refusée.

## Quand une base vectorielle seule est le bon choix

- **Quand vos documents sont déjà bons.** Corpus rédigé, propre, structuré : vectorisez
  et cherchez, la couche de curation n'ajouterait qu'un coût.
- **Quand vous construisez autre chose.** Recommandation, déduplication, détection de
  similarité, classification : ce sont des usages de vecteurs qui n'ont rien à voir avec
  une mémoire personnelle.
- **Quand vous ne voulez pas d'appels payants à chaque cycle.** ARAC paie de la lecture
  en continu. Une base vectorielle ne paie que l'indexation.

---

# 5. Ce n'est pas un tableau de bord

## Ce que c'est

Un tableau de bord affiche des indicateurs pour les suivre dans le temps : des chiffres,
des courbes, un vert, un rouge, une alerte quand un seuil est franchi.

## Pourquoi on s'y trompe

Parce que le cockpit d'ARAC ressemble à ça : des cartes, des nombres, des états. La forme
est familière ; l'intention est différente.

## Ce qu'ARAC fait à la place

Le cockpit ne sert pas à **suivre des indicateurs**. Il sert à **comprendre un cerveau** —
à répondre à des questions comme : qu'est-ce que ce cerveau a appris cette semaine ? où
range-t-il ce qu'il apprend ? à quel point se fie-t-il à ce qu'il rend ? qu'a-t-il jeté,
et pourquoi ?

Une règle de conception le distingue de tout tableau de bord ordinaire :

> **Aucun chiffre ne s'affiche sans les lignes qui le produisent.** Une métrique sans
> requête de preuve ne peut littéralement pas exister dans le code : l'objet refuse de
> s'instancier. Le cockpit ne calcule pas — il montre, et il fournit de quoi rejouer.

La conséquence est qu'on ne peut pas « croire » un chiffre du cockpit : on peut le
**vérifier**. Devant « 9 % des atomes sont posés sur une racine nue », vous ne haussez pas
les épaules, vous demandez lesquels — et vous obtenez la liste.

Ce n'est pas une élégance. C'est la seule défense contre la panne caractéristique de ce
genre de système : **un cerveau dérive en silence, sans jamais tomber en panne.** Les
atomes posés sur des racines nues — près d'un sur onze — n'ont déclenché aucune alarme :
ils étaient en base, corrects, sourcés, encore atteignables par une question qui leur
ressemblait, et pourtant absents de tout état courant, de toute vue de scope, de toute
mesure de couverture. Ils ont été trouvés parce que quelqu'un a regardé un chiffre qui
n'allait pas.

Corollaire honnête, du même ordre : **une sonde qui ne joint pas la base répond
« inconnu », jamais « tout va bien ».** Transformer une panne d'observation en bonne
nouvelle est l'erreur la plus coûteuse d'un système de surveillance.

## Quand un vrai tableau de bord est le bon choix

Quand vous voulez suivre l'état de vos **services** — charge, latence, disponibilité,
alertes. Grafana et ses semblables font ça infiniment mieux, et ARAC ne cherche pas à les
concurrencer. Le cockpit regarde **le savoir**, pas la machine.

Et une chose à savoir avant d'installer : **si vous ne regardez jamais votre cockpit, ARAC
est un journal coûteux.** Un cerveau dont personne ne lit les mesures dérive sans que ça
se voie. Cette curiosité régulière fait partie du contrat, elle n'est pas optionnelle.

---

# 6. Ce n'est pas un remplaçant de Claude

## Ce que c'est

La crainte, ou l'espoir, qu'ARAC soit un système qui répondrait à votre place, ou qui
rendrait Claude plus intelligent.

## Pourquoi on s'y trompe

Parce qu'on appelle ça « un cerveau », et qu'un cerveau, dans l'usage courant, pense.
Celui-ci ne pense pas. Il retient.

## Ce qu'ARAC fait à la place

**ARAC n'essaie pas de rendre Claude plus intelligent.** Il ne réentraîne rien, n'ajuste
rien, ne remplace aucun raisonnement. Il lui donne un **passé**.

```
   Claude seul     :  raisonnement × 0 mémoire      =  un très bon inconnu
   Claude + ARAC   :  raisonnement × votre passé    =  quelqu'un qui vous connaît
```

Le positionnement, en trois lignes, à comprendre avant la première commande :

| L'endroit | Ce que vous y faites | Ce qui n'y change pas |
|---|---|---|
| **Claude Desktop** | vous **réfléchissez** | vous continuez exactement comme avant |
| **Claude Code** | vous **construisez** | vous continuez exactement comme avant |
| **ARAC** | rien — vous n'y écrivez pas | c'est l'endroit où tout cela est **compris, organisé, relié et retrouvé automatiquement** |

Le point important est la troisième colonne. **Votre manière de travailler ne change
pas.** Il n'y a pas de nouvelle habitude à prendre, pas d'application à ouvrir le matin,
pas de rituel de rangement. La seule chose qui change, c'est que six mois plus tard,
quelque chose se souvient.

Cette division du travail a une conséquence pratique qu'on sous-estime : **ARAC survit au
changement de modèle.** Vos atomes ne vivent pas dans un modèle ; ils vivent dans votre
base PostgreSQL, sur votre serveur, en texte lisible. Le jour où vous changez d'outil de
raisonnement, votre mémoire ne bouge pas. C'est l'inverse exact d'un système où le savoir
vit chez un fournisseur.

## Quand Claude seul suffit

- **Si vous ne parlez pas beaucoup à Claude.** ARAC digère des conversations. Sans
  matière, il tourne à vide et coûte quand même.
- **Si votre travail ne dépend pas de votre passé.** Beaucoup de tâches excellentes ne
  demandent aucune continuité : traduire, expliquer, écrire un script, comprendre un
  concept. La mémoire n'y ajoute rien.
- **Si vous cherchez un assistant.** ARAC ne vous rappelle rien, ne vous propose rien, ne
  vous relance pas. Il se souvient. C'est tout — et c'est déjà bien plus difficile que ça
  n'en a l'air.

---

# À quoi ressemble le succès

Pas « le bootstrap fonctionne ». Pas un nombre d'atomes. Ceci :

> **Vous n'avez plus envie de revenir à un système où toute la mémoire dépend de notes
> écrites à la main.**

Concrètement, ça ressemble à trois moments, et ils arrivent tard — pas la première
semaine :

- Vous posez une question à Claude, et la réponse contient une décision que vous aviez
  prise il y a cinq mois et complètement oubliée. Vous ne l'aviez pas notée. Vous
  n'auriez pas su qu'il fallait la chercher.
- Vous vous apprêtez à explorer une piste, et il vous revient que vous l'aviez déjà
  écartée — avec le motif. Vous économisez une journée.
- Vous ouvrez le cockpit et vous découvrez un sujet dont vous ne saviez pas qu'il occupait
  un tiers de votre attention.

Aucun des trois n'est un gain quotidien. C'est la structure économique d'une assurance :
**la dépense est certaine et quotidienne, le bénéfice est rare et imprévisible.** C'est
psychologiquement désagréable, et il vaut mieux le savoir avant.

# Le pari, dit franchement

Le succès décrit ci-dessus suppose d'accepter quelque chose d'inconfortable, et ce n'est
pas technique.

**Une machine décide de ce qui mérite d'être retenu.**

Un souvenir humain, vous l'avez vécu. Une note, vous l'avez choisie. Un atome, vous ne
l'avez **ni vécu comme tel, ni choisi**. Un modèle a lu votre conversation et a jugé que
cette phrase-là méritait de survivre — et qu'une autre non. Il se trompera. Il gardera
des choses tièdes et laissera passer des choses justes.

Est-ce encore votre mémoire ? Ou une interprétation de votre mémoire, produite par
quelqu'un d'autre, que vous consulterez ensuite comme un fait ?

**ARAC ne tranche pas cette question.** Il fait une seule chose : il rend l'interprétation
**traçable**. Chaque atome porte sa provenance — la conversation, les messages exacts. Vous
pouvez toujours remonter au texte d'origine et juger vous-même. C'est aussi pourquoi la
perte de provenance mesurée sur le cerveau observé — **76 % des atomes ne pouvaient plus
dire d'où ils venaient** après un changement de format — n'était pas un incident parmi
d'autres, mais une atteinte au fondement.

Et il faut ajouter ceci, qui est la limite du pari : **ARAC n'arbitre pas à votre place.**
Aucun mécanisme n'y détecte qu'un atome en contredit un autre ; deux affirmations opposées
cohabitent en base sans que rien ne s'allume. Le rappel affiche son doute au lieu de le
lisser. La file de revue attend un humain. Un cerveau qui trancherait à votre place ne
serait pas un cerveau — ce serait un avis.

Si ce paragraphe vous fait hésiter, il a fait son travail.

---

| Pour | Lire |
|---|---|
| Les sept marches — pourquoi tout ceci existe | [`POURQUOI.md`](POURQUOI.md) |
| Le pari, et les raisons de ne pas installer | [`PHILOSOPHIE.md`](PHILOSOPHIE.md) |
| Les cinq notions, en détail technique | [`CONCEPTS.md`](CONCEPTS.md) |
| Ce qui ne marche pas encore | [`../README.md`](../README.md) |
| Le vocabulaire | [`GLOSSAIRE.md`](GLOSSAIRE.md) |
