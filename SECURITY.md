# Sécurité

ARAC-BRAIN garde vos conversations. C'est la matière la plus intime qu'un logiciel
puisse détenir : ce n'est pas une base de données, c'est ce que vous avez pensé.
Cette page dit ce que le projet fait pour la protéger, ce qu'il ne fait pas, et
comment nous signaler un problème.

## Signaler une faille

**N'ouvrez pas d'issue publique.** Une faille décrite dans un dépôt public est une
faille exploitable avant d'être corrigée.

Utilisez l'onglet **Security → Report a vulnerability** de ce dépôt (avis de
sécurité privé GitHub). Si cette voie ne vous est pas accessible, ouvrez une issue
qui dit seulement *« j'ai un rapport de sécurité »*, sans détail, et nous
prendrons contact.

Dites-nous, autant que vous le pouvez : ce que vous avez obtenu, la commande ou la
requête qui l'obtient, la version du dépôt, et si votre cerveau tournait seul ou à
côté d'un autre sur la même machine.

Nous accusons réception sous quelques jours. Ce projet n'a pas d'équipe de garde :
soyez patient, et prévenez-nous si le silence dure.

## Ce que le produit protège, et comment

**Le jeton est exigé, toujours.** Toute requête à l'API doit le porter, y compris
depuis la boucle locale. Seule la sonde de santé reste publique. Le desserrage
existe mais exige deux variables : la valeur **et** un motif daté, écrit. Ce n'est
pas une chicane — une posture qu'on peut relire dans son coffre est une posture
qu'on peut contester ; un défaut implicite, non.

**Chaque cerveau est cloisonné.** Rôles PostgreSQL, comptes système, ports,
coffres de secrets, journaux, sauvegardes et unités système sont tous dérivés du
nom du cerveau. Une installation refuse un rôle qu'elle n'a pas créé, un port déjà
tenu, un nom déjà pris — et elle refuse **avant** d'écrire quoi que ce soit.

**Le journal ne porte que des empreintes.** Aucune clé, aucun domaine, aucun titre,
aucun fragment de souvenir ne part dans le journal système : seulement des
empreintes stables et illisibles. La raison est écrite dans
[`docs/DECISIONS-ARCHITECTURE.md`](docs/DECISIONS-ARCHITECTURE.md) — `systemd` ne sait pas purger le journal
d'une seule unité, donc ce qu'on y écrit doit pouvoir y rester.

**Le cockpit ne peut pas écrire.** Il se connecte avec un rôle en lecture seule et
n'expose aucune route d'écriture, hors la connexion.

**Rien ne sort sans que vous le sachiez.** Deux services externes sont appelés :
un fournisseur d'embeddings et un modèle de curation. Ce qui leur est envoyé est
décrit dans [`docs/COMMENT-IL-SE-NOURRIT.md`](docs/COMMENT-IL-SE-NOURRIT.md).
Aucun autre appel réseau sortant n'existe dans le produit.

## Ce que le produit ne protège pas

**Un administrateur de la machine.** Le cloisonnement protège des accidents et des
voisinages, pas de `sudo`. Qui est root lit tout.

**Vos clés d'API.** Elles vivent dans un coffre à `0600`, appartenant au compte du
cerveau. C'est tout ce qu'un fichier peut offrir.

**Le fournisseur externe.** Ce que vous envoyez à un modèle de curation est soumis
aux conditions de ce fournisseur, pas aux nôtres.

**La suite de tests contre un test hostile.** Elle s'exécute derrière deux
barrières, dont la couverture est partielle sans `Landlock`. Le modèle de menace
est écrit : cette barrière protège d'un test **distrait**, pas d'un test
**hostile** — un test hostile exécute déjà du code arbitraire chez vous.
Voir [`docs/LIMITES-CONNUES.md`](docs/LIMITES-CONNUES.md) §3.2.

## Avant de publier quoi que ce soit de votre cerveau

Un dump PostgreSQL de votre base **contient vos souvenirs en clair**. Une capture
d'écran de votre cockpit aussi. Si vous joignez quoi que ce soit à un rapport de
bogue, relisez-le : nous préférons une description imprécise à une fuite.

## Versions

Ce projet est en V1. Les correctifs de sécurité s'appliquent à la dernière version
publiée. Il n'y a pas de branche de maintenance à long terme aujourd'hui.
