# Questions fréquentes

Les vraies questions, avec de vraies réponses — y compris quand la réponse est « non »
ou « on ne sait pas ».

---

## L'argent

### Combien ça coûte, vraiment ?

**Cela dépend d'une chose, et ce n'est pas celle qu'on croit : comment le binaire de
curation s'authentifie.**

| Votre cas | Ce que vous payez en plus |
|---|---|
| Vous avez **déjà un abonnement Claude** et vous ouvrez sa session pour le compte d'agent | **rien pour la curation** — elle consomme le quota de votre abonnement. Reste 5 à 15 € de serveur et quelques euros d'embeddings. |
| Vous authentifiez le binaire par une **clé d'API Anthropic** | **20 à 100 $ par mois** selon le modèle, plus 5 à 15 € de serveur. |

**La curation n'est pas une API qu'ARAC appelle** : c'est le binaire `claude` (Claude Code
CLI) que le cycle *lance* sur votre serveur. C'est donc **ce binaire** qui est facturé, ou
non, selon ce avec quoi il s'authentifie. Une clé d'API Anthropic achetée sans ce binaire
ne produit pas un souvenir ; un abonnement déjà payé rend cette clé inutile.

Le chiffre du second cas dépend presque entièrement du modèle de curation choisi. Les
mesures relevées sur le cerveau de référence, en régime établi :

```
  3 cycles de digestion par jour        (04:00 · 13:00 · 21:00)   mesuré
  ~87 000 jetons consommés par cycle                              mesuré
  ~31 500 jetons par souvenir effectivement produit               mesuré
  ≈ 260 000 jetons par jour · ≈ 8 000 000 par mois                calculé : 3 × 87 000
```

**La facture suit les cycles, pas les atomes.** Elle est la même le mois où le cerveau
retient beaucoup et celui où il ne retient rien : c'est le nombre de cycles et la taille
des lots qui la font, pas le rendement.

Au tarif public d'août 2026, 8 millions de jetons d'entrée avec un modèle de la classe
Sonnet (3 $/million) reviennent à **~25 $/mois**, plus la sortie. Avec un modèle de la
classe Opus, comptez **trois à cinq fois plus**. Les embeddings sont deux ordres de
grandeur en dessous : **quelques euros par mois**.

**Vérifiez ces tarifs vous-même.** Ce dépôt ne peut pas vous promettre un prix qu'il ne
fixe pas.

### Pourquoi le rendement est-il si mauvais — 87 000 jetons pour un atome à 31 500 ?

Parce que **la plupart d'une conversation n'est pas du savoir durable**. Le cerveau lit
tout et ne retient presque rien : c'est exactement son travail. Un système qui retiendrait
tout ne serait pas une mémoire, ce serait une archive — et vous en avez déjà une.

Ce qu'il faut surveiller, ce n'est pas le rapport en soi, c'est sa **dégradation**. Le
cockpit sert la phrase qui le dit : « J'ai dépensé N jetons depuis 24 heures **sans
retenir un seul atome** ». Répétée, elle veut dire que vous payez pour rien.

**Attention à ne pas confondre deux symptômes très différents.** *Dépenser sans retenir*
est un problème de rendement, et là les identifiants de poste incohérents sont une cause
classique. *Ne rien dépenser du tout et ne rien retenir* est autre chose : sur un cerveau
neuf, c'est presque toujours l'un des **deux interrupteurs de dépense**, fermés d'usine,
ou le **binaire de curation** absent. Le tableau qui trie les deux, code de journal par
code de journal, est à l'étape 9 du
[démarrage rapide](DEMARRAGE-RAPIDE.md).

### Y a-t-il un mode gratuit ?

**Non**, et c'est dit en première page plutôt qu'en annexe. Deux fonctions se paient :
les embeddings (transformer un texte en vecteur de sens) et la curation (décider ce qui
mérite d'être retenu). **Mais pas de la même façon** : les embeddings sont une API
qu'ARAC appelle et qui exige sa clé ; la curation est un **binaire** que le cycle lance,
et qui se paie par ce que ce binaire a — un abonnement déjà payé, ou une clé d'API.

Vous pouvez refuser les deux clés : le bootstrap installe alors un **mode dégradé
déclaré** et vous dit exactement ce qui ne marchera pas. Sans embeddings : aucun rappel
par similarité. Sans curation : les cycles tournent et ne produisent aucun souvenir. Le
cerveau existe, mais il n'apprend ni ne se souvient. Ce n'est pas un mode d'usage, c'est
un mode d'attente.

### Comment éviter les mauvaises surprises ?

Les freins existent, et ils sont armés **avant** le premier cycle, pas après la première
facture — à commencer par **deux interrupteurs fermés d'usine**, `ARAC_ALLOW_PAID_AI`
dans le coffre et `arac_config.paid_ai_enabled` en base, sans lesquels aucun cycle ne
dépense un centime :

| Frein | Effet |
|---|---|
| `ARAC_ALLOW_PAID_AI=0` (coffre) | **l'interrupteur 1 sur 2**, côté service. Aucun appel payant n'est émis. C'est le défaut. |
| `arac_config.paid_ai_enabled` (base) | **l'interrupteur 2 sur 2**, côté cerveau. Il ne s'arme que par `agents.lib.paid_ai_control arm --confirm`. C'est celui que personne ne trouve, parce qu'il n'est dans aucun fichier. |
| `ARAC_PACK_TOKEN_BUDGET` | le plafond de jetons par cycle |
| `agents/lib/spend_guard.py` | le garde-dépense : plafonds du jour, et un kill-switch qui n'est jamais retiré automatiquement |

Laissez les deux interrupteurs fermés jusqu'à ce que le reste de l'installation soit
vérifié : un cycle lancé sur une configuration à moitié faite dépense pour rien.
**Corollaire** : tant que vous ne les avez pas ouverts *tous les deux*, votre cerveau
n'apprendra rien — et c'est la première chose à vérifier quand un premier cycle ne rend
rien.

---

## Les données

### Mes conversations partent-elles quelque part ?

**Elles vivent sur votre serveur, dans votre base PostgreSQL.** Il n'y a pas de service
hébergé, pas de compte à créer, pas de télémétrie. Le dépôt n'appelle aucune adresse en
dehors du fournisseur d'embeddings. *(Le second flux sortant, la curation, n'est pas
émis par ARAC : c'est le binaire `claude` qu'il lance qui parle à Anthropic — le texte
sort quand même, et c'est ce que dit le tableau ci-dessous.)*

Mais soyons précis, parce que la réponse honnête n'est pas « rien ne sort » :

| Ce qui sort | Vers qui | Quand |
|---|---|---|
| le **texte à vectoriser** (extraits de conversation, atomes, questions de rappel) | OpenAI | à chaque embedding |
| le **texte à curer** (des tranches entières de conversation) | Anthropic — **par le binaire `claude` que le cycle lance**, pas par une requête d'ARAC | à chaque cycle, 3 fois par jour |
| rien d'autre | — | — |

Autrement dit : **le contenu de vos conversations transite par ces deux fournisseurs**,
puisque c'est précisément ce qu'on leur demande de lire. Si c'est rédhibitoire pour vous,
ARAC dans sa forme actuelle ne convient pas. Lisez leurs conditions d'utilisation
d'entreprise, pas leurs pages grand public.

Ce qui ne sort **jamais** : la base elle-même, les vecteurs, les graphes, les journaux,
les secrets, et vos sauvegardes — sauf si vous configurez explicitement une copie hors
site (`ARAC_OFFSITE_DEST`).

### Le serveur est-il exposé sur Internet ?

**Non.** L'API et le cockpit n'écoutent que sur `127.0.0.1`. On y accède par un tunnel
SSH. Il n'y a donc ni TLS à installer, ni reverse-proxy, ni pare-feu à régler — le
chiffrement, c'est SSH qui le fait.

> **Mais « pas exposé » ne veut pas dire « rien à défendre ».** Cette page l'a écrit, et
> c'était faux. Le tunnel dit d'**où** vient une requête ; il ne dit jamais **qui**
> l'envoie. Sur un serveur, `127.0.0.1` n'est pas « chez moi » : c'est un couloir que
> partagent tous les comptes de la machine — le vôtre, celui d'un script, celui du cerveau
> d'un ami installé à côté. Mesuré depuis le compte `nobody`, sans un seul secret : la
> mémoire d'un cerveau lue en clair, un faux souvenir écrit dedans. C'est pourquoi **le
> jeton porteur est exigé de toute requête, `127.0.0.1` compris** ; seul `/healthz` reste
> public. Vous n'avez rien à faire de plus : le bootstrap engendre ce jeton et tout ce qui
> parle à l'API le porte. La règle et son desserrage motivé sont dans
> [`CONFIGURATION.md` §6](CONFIGURATION.md).
>
> Et la leçon qui dépasse ARAC : **une machine qui n'accueillera jamais qu'un cerveau
> n'est pas une raison de laisser sa mémoire lisible par tout compte local.** « Je suis
> seul sur ce serveur » est une hypothèse sur l'avenir, pas une propriété du système.

Le contrôle qui tranche l'exposition réseau ne contient **aucun numéro** — les ports sont
attribués à l'installation, pas fixés, et un numéro ne dit pas à quel cerveau il mène :

```bash
BASE=<votre_base>
sudo ss -ltnp | grep -E "pid=$(systemctl show "arac-$BASE-api" -p MainPID --value)\b"
# l'adresse doit commencer par 127.0.0.1 — jamais 0.0.0.0
```

Si vous voyez un jour `0.0.0.0` en face de l'un de vos services, quelque chose a été
modifié et il faut s'en occuper tout de suite.

Le cockpit ajoute deux verrous par-dessus : mot de passe (haché en PBKDF2-SHA256,
260 000 itérations) et second facteur TOTP. Il est **fail-closed** : sans ses secrets, il
répond `503` plutôt que de s'ouvrir.

### Mes sauvegardes sont-elles chiffrées ?

**Pas par défaut.** `ops/backup.sh` sait chiffrer au repos avec `age`, mais tant que
`ARAC_BACKUP_RECIPIENTS` est vide, vos dumps sont **en clair** sur le disque.
`ops/install_check.sh` vous le dit à chaque passage.

Le point important si vous activez le chiffrement : **la clé privée ne doit pas vivre sur
le serveur qu'elle protège.** Sinon vous avez chiffré une porte en laissant la clé sur la
serrure.

### Puis-je supprimer un souvenir ?

Oui, mais le système est construit pour vous en dissuader. La doctrine est qu'un savoir
**se supersède**, jamais ne s'efface : le nouveau remplace l'ancien, et l'ancien reste,
daté. C'est pour cela que le rôle PostgreSQL de l'API n'a **pas** le droit de `DELETE`.

Vous gardez ainsi la trace de ce que vous avez cru, et de quand vous avez changé d'avis —
ce qui est souvent l'information la plus utile.

Pour un souvenir qui n'aurait jamais dû entrer (une donnée sensible arrivée par erreur),
il faut passer par le rôle administrateur, à la main, en sachant ce qu'on fait.

---

## Les modèles

### Puis-je utiliser un autre modèle d'embeddings ?

**Techniquement oui, pratiquement non — sauf au premier jour.**

Le schéma est figé sur `text-embedding-3-large`, **3 072 dimensions**, stocké en
`halfvec(3072)`. La demi-précision n'est pas une économie de bout de chandelle : l'index
HNSW de pgvector plafonne à 2 000 dimensions pour le type `vector`, et sans index la
recherche s'écroule.

Changer de modèle ou de dimension **invalide tous les vecteurs déjà calculés**. Deux
populations incomparables cohabitent alors dans le même index, et — c'est le vrai
danger — **le rappel se dégrade silencieusement**. Aucune erreur, aucun test rouge,
juste des résultats un peu moins bons chaque semaine.

Si vous devez en changer : nouvelle colonne, nouvel index, recalcul de tout le corpus,
donc **re-paiement** de tout le corpus. C'est une migration, pas un réglage.

**Le bon moment pour décider, c'est avant le premier cycle.** Après, c'est cher.

### Puis-je utiliser un modèle local, ou un autre fournisseur de curation ?

Ce n'est **pas prévu ni testé aujourd'hui**, et les deux côtés ne se substituent pas de
la même façon. Les embeddings sont un **appel d'API** qu'ARAC émet lui-même
(`app/services/embeddings.py`) : changer de fournisseur, c'est changer un client HTTP. La
curation, elle, n'est pas un appel d'API du tout — c'est un **sous-processus** :
`agents/lib/claude_cli.py` lance le binaire `claude` avec ses garde-fous (liste blanche
d'outils, bac à sable `--add-dir`, délai dur). En changer, ce n'est pas remplacer une URL,
c'est remplacer un exécutable et tout ce que ce contrat suppose. La substitution reste
faisable — mais personne ne l'a faite, et ce document ne va pas vous promettre que ça
marche.

Deux choses à savoir avant de vous lancer :

- **La curation est la partie difficile.** Ce n'est pas « résumer une conversation » :
  c'est décider ce qui est un savoir durable, le rattacher à un domaine, lui donner une
  confiance et une provenance, et détecter qu'il contredit un savoir existant. Un petit
  modèle échoue à la troisième étape, silencieusement — il produit des atomes plausibles
  et faux.
- **Les embeddings sont interchangeables sur le principe**, à condition d'accepter le
  recalcul intégral (voir ci-dessus).

### Un modèle de curation moins cher, ça change quoi ?

Il coûte moins **et extrait moins**. Le rapport n'est pas linéaire, et il n'a pas été
mesuré ici. Si vous descendez, mesurez : le cockpit vous donne les jetons dépensés et les
atomes retenus, donc le rendement. C'est le seul juge.

### Est-ce que ça remplace Claude ?

**Non. ARAC augmente Claude, il ne le remplace pas.**

Claude raisonne remarquablement et oublie tout entre deux conversations. ARAC ne raisonne
pas : il retient, et il rend au bon moment. Le premier sans le second recommence à zéro
chaque matin ; le second sans le premier n'est qu'une base de données.

---

## Le matériel et les prérequis

### Qu'est-ce que je dois vraiment ACHETER avant de commencer ?

**Une clé d'API OpenAI. Et pour la curation, rien du tout si vous avez déjà un abonnement
Claude.**

Le tableau complet — obligatoire ou non, à quoi ça sert, et si le bootstrap le vérifie —
est en [README §5](../README.md#5-ce-quil-vous-faut-et-ce-que-vous-naurez-pas). En trois
lignes :

- **la clé OpenAI** est la seule qu'ARAC lise lui-même. Elle paie un vecteur par souvenir
  produit et un par question posée. Sans elle, le rappel par le sens est mort ;
- **la curation n'a pas de clé à elle.** Elle a besoin d'un **binaire** — le Claude Code
  CLI, `sudo npm install -g @anthropic-ai/claude-code` — installé **sur votre serveur**.
  C'est gratuit ;
- **ce binaire, lui, doit pouvoir s'authentifier** : soit par une session d'abonnement
  ouverte pour le compte d'agent du cerveau (rien de plus à payer), soit par une clé
  d'API Anthropic qu'il lira dans l'environnement du service. ARAC ne lit jamais cette
  clé — il ne fait que la poser là où le binaire la trouvera.

**L'erreur à ne pas faire** : acheter une clé d'API Anthropic en croyant qu'elle digère.
Sans le binaire, elle ne produit pas un seul souvenir — et si vous avez un abonnement,
elle ne sert à rien.

### Le bootstrap vérifie-t-il le binaire de curation ?

**Oui, depuis cette manche — et deux fois.** L'étape 1 (`./bootstrap/bootstrap.sh
--check`) le constate, donne sa version, et **lit son authentification sans rien
dépenser**. Le contrôle final (`bootstrap/checks/verify_install.sh`, §7) la repose **sous
le dossier personnel du compte d'agent**, qui est le seul dont l'avis compte : c'est ce
compte qui lancera les cycles, et une session ouverte dans `/root` n'y est pas.

C'est le **seul prérequis qui n'arrête pas l'installation**. Absent, le verdict de l'étape
1 le dit en toutes lettres : « Le serveur peut porter un cerveau. ⚠ Mais PAS le faire
apprendre ». Ce qui n'est **pas** vérifié : que `npm` existe pour poser le binaire, et
l'espace disque.

### Faut-il vraiment un Mac ?

**Non.** Le pont d'ingestion (`mac/arac-sync.py`) est du Python de la bibliothèque
standard : il tourne tel quel sur Linux, y compris sur le serveur lui-même — auquel cas le
tunnel devient inutile, tout étant déjà en local. L'ordonnancement se fait alors par
`deploy/systemd/arac-pont-sans-mac.{service,timer}.modele`.

Ce qu'on perd sans Mac : `launchctl`, `plutil`, les notifications macOS.
Ce qu'on ne perd pas : l'inventaire, l'annonce avant envoi, la déduplication, la reprise,
l'acquittement — c'est-à-dire tout ce qui compte.

Honnêteté : **le pont n'a jamais été exercé sur un Mac.** Il est validé sur Linux contre
un serveur d'ingestion simulé. La liste exhaustive de ce qui n'a pas pu être vérifié est
en fin de [`PONT-MAC.md`](PONT-MAC.md).

### Peut-on faire tourner ça sur un Raspberry Pi ou un NAS ?

Rien ne l'interdit — PostgreSQL 16, pgvector et Python 3.12 suffisent — mais **ce n'est
pas testé**. Deux points de vigilance : pgvector aime la RAM au moment de construire ses
index, et un `pip install` de `numpy`/`psycopg` sur ARM sans roues précompilées peut
durer très longtemps.

### Faut-il vraiment un serveur, ou un portable suffit ?

Un portable **fonctionne**, mais ne convient pas : le cerveau digère à 04:00, 13:00 et
21:00, sauvegarde toutes les six heures (`00,06,12,18:30 UTC`) et surveille en continu. Un
ordinateur qui dort ne digère pas. Vous vous retrouverez avec une file qui grossit, des
cycles qui ne passent jamais et des sauvegardes qui sautent.

Si vous n'avez qu'un portable, décalez les cycles sur des heures où il est allumé
(`ARAC_CYCLES`) et montez `ARAC_ALERT_STALL_HOURS` pour que l'alarme ne sonne pas à
tort.

### Combien d'espace disque ?

20 Go sont confortables pour des années. Une base de cerveau actif pèse quelques centaines
de mégaoctets par an, vecteurs compris ; l'essentiel de la croissance vient des
conversations brutes conservées pour la provenance. Prévoyez la place des sauvegardes
séparément (`/var/backups/arac/<votre_base>` — le sous-dossier n'est pas décoratif : la
racine est commune à tous les cerveaux de la machine), et **sur un autre disque** : une
sauvegarde qui vit dans le dossier qu'elle sauvegarde ne sauvegarde rien.

### Pourquoi pas de Docker ?

C'est un choix, pas un oubli. `systemd` et un environnement virtuel Python suffisent, se
diagnostiquent mieux, et évitent une couche de plus entre vous et la panne. Aucune image,
aucun `docker-compose` n'est fourni.

Rien n'empêche de faire tourner **la base** dans un conteneur : pour ARAC, c'est une base
distante comme une autre (`ARAC_DB_HOTE`, `ARAC_DB_PORT`). Non testé.

---

## L'usage

### Combien de temps avant que ce soit utile ?

**Quelques jours pour voir quelque chose, quelques semaines pour que ça vaille le coup.**

Un cerveau neuf ne sait rien. Il lui faut des conversations, des cycles, et — c'est le
point le plus souvent oublié — **votre relecture**. Sur le cerveau de référence, **98 %
du savoir n'a jamais été audité** : le cerveau est confiant sur ce qu'il n'a jamais
vérifié.

Prenez l'habitude, une fois par semaine, d'ouvrir le cockpit et de **lire** ce qui a été
extrait — la page d'un domaine (`GET /cc/v1/scopes/<chemin>`) liste ses atomes fragiles.
Ce que vous jugez faux se corrige ensuite par l'API : `supersede` pour remplacer, `PATCH`
pour retoucher, `DELETE` pour archiver. Voir
[`PREMIER-MOIS.md`](PREMIER-MOIS.md), « Corriger ce qui est faux ».

**Ce que ce geste ne fait pas** : marquer un savoir comme **vérifié**. Il faut distinguer
deux champs que le mot « confiance » confond, et le partage n'est pas celui qu'on croit :

- **le score chiffré, `confidence_score` (0-100), est modifiable** — `PATCH /v1/atoms/<id>`
  l'accepte et l'écrit. Ce n'est pas un geste vain : c'est vous qui dites à quel point vous
  croyez cette phrase-là.
- **la trace d'audit, `audit_source`, ne l'est pas.** L'API la refuse explicitement — un
  `PATCH` qui la porte rend `422 extra_forbidden` —, et le niveau déclaré `confidence`
  (`producer` / `auditor_validated` / `agent_suggest`) est hérité, jamais retouché. Or
  c'est exactement `audit_source` que compte la mesure « 98 % du savoir jamais audité »
  (`control_center/cc_v1/families/confiance.py`, `unaudited_knowledge_share`). **Aucun
  chemin servi ne fait donc descendre ce 98 %** : voilà ce qui manque, et c'est un chantier
  déclaré ([`ROADMAP.md`](ROADMAP.md), §2.4), pas un réglage à trouver.

Le **cockpit**, lui, ne sait qu'afficher : il n'a **aucune** route d'écriture — une seule
route non-`GET`, `POST /cc/login`, qui pose un cookie de session —, et son rôle PostgreSQL
ouvre toutes ses transactions en lecture stricte. Tout ce qui corrige passe par l'API.

> *Ce paragraphe a dit, jusqu'en août 2026, que « la confiance est fixée à sa naissance et
> n'est modifiable par aucun chemin servi ». C'était faux d'un champ sur deux, et la
> vérification qui l'avait laissé passer cherchait un champ nommé `confidence` dans le
> schéma du `PATCH` — il s'appelle `confidence_score`. Une preuve qui interroge le mauvais
> nom rend « absent » avec le même aplomb qu'une preuve juste.*

### Est-ce que ça remplace Obsidian, Notion, ou mes notes ?

**Non, et ce n'est pas le même geste.**

Obsidian et Notion sont des outils où **vous écrivez**. Vous décidez ce qui mérite une
note, vous la rédigez, vous la rangez, vous la reliez. Ce travail a une immense valeur —
et il a un coût que la plupart des gens finissent par ne plus payer.

ARAC ne vous demande **rien à écrire**. Il lit ce que vous avez déjà dit, en extrait ce
qui compte, et vous le rend quand la question se repose. C'est une mémoire, pas un
espace de rédaction.

Les deux cohabitent très bien : Obsidian pour ce que vous voulez **penser**, ARAC pour ce
que vous ne voulez pas avoir à **retenir**.

Trois différences concrètes :

| | Notes classiques | ARAC |
|---|---|---|
| Qui écrit ? | vous | la curation, depuis vos conversations |
| Qui range ? | vous | la taxonomie que vous avez définie une fois |
| Comment on retrouve ? | par le titre, les tags, la recherche plein texte | par le **sens** : la question devient un vecteur |

### Comment Claude Code s'en sert-il ?

Par l'**API HTTP**, à travers le tunnel : `POST /v1/atoms/context_for` et
`POST /v1/atoms/recall` rendent les souvenirs pertinents pour une question ou un contexte
de travail. **Le préfixe `/v1` fait partie du chemin** — sans lui, l'API répond `404`, et
c'est le genre de détail qu'on recopie sans le voir juste avant d'écrire sa propre colle.
La liste des routes de rappel réellement servies est au §5 du
[`README`](../README.md).

**Il n'y a pas de serveur MCP ni d'intégration clés en main dans ce dépôt**, et c'est une
limite réelle. Vous devez écrire vous-même le petit bout de colle qui appelle l'API
(quelques lignes de `curl`, ou une commande personnalisée). Le jeton porteur du poste
« serveur » se déclare comme n'importe quel autre poste — voir
[`DEPANNAGE.md` §8](DEPANNAGE.md#8-http-401--pas-de-jeton-ou-pas-le-bon).

### Ça marche en anglais ? Dans une autre langue ?

Le **contenu** de vos conversations peut être dans n'importe quelle langue : les
embeddings et la curation sont multilingues, et la comparaison par le sens fonctionne
même entre deux langues différentes.

L'**outil**, lui, parle français : messages, cockpit, documentation. `label_language`
dans `config/scopes.toml` ne change que la langue de vos propres libellés de domaines.

### Puis-je changer ma taxonomie après coup ?

**Ajouter : oui, facilement. Retirer : c'est une décision, pas un réglage.**

```bash
# éditez config/scopes.toml, puis :
sudo ./bootstrap/bootstrap.sh --scopes-only
```

Le générateur **refuse de retirer un domaine qui contient encore des atomes vivants**. Il
vous dit lesquels et vous laisse décider. Deux voies, et seulement deux : remettre le
domaine, ou déplacer ses souvenirs d'abord — dans le cockpit, un par un, en voyant ce
qu'on déplace.

Il n'y a volontairement pas de `--force`. Un outil qui prétend se souvenir n'a pas à
proposer un raccourci pour oublier.

**Le conseil pratique** : ajoutez généreusement dès que vous sentez qu'un savoir n'a pas
de bonne place. Une taxonomie trop étroite pousse la curation à poser les atomes sur les
**racines**, où ils deviennent orphelins : encore rappelables par similarité pure, mais
hors de l'état courant, hors de la vue des scopes et hors de la couverture — et
inatteignables par toute recherche qui précise un domaine. C'est le piège n°1, et il a
coûté près d'un souvenir actif sur onze au cerveau de référence.

### Combien de domaines faut-il ?

**Cinq à huit racines, trois à six feuilles chacune** — l'ordre de grandeur est donné une
seule fois, dans [`COMMENT-IL-CREE-SES-SCOPES.md`](COMMENT-IL-CREE-SES-SCOPES.md) §5, et
tout le reste du dépôt y renvoie.

Ordres de grandeur observés : un cerveau actif accumule ~150 atomes par mois. Une feuille
qui n'atteint pas 10 atomes en six mois n'aurait pas dû exister ; une feuille qui dépasse
250 atomes gagnerait à être scindée.

Et la règle qui gouverne tout : **les atomes vivent sur les feuilles.** Une racine est un
conteneur, une feuille est un rangement. Un atome posé sur une racine existe en base et
devient orphelin — voir le piège n°1, et le mécanisme exact au §4 de
[`COMMENT-IL-CREE-SES-SCOPES.md`](COMMENT-IL-CREE-SES-SCOPES.md).

### Pourquoi le cerveau doute-t-il autant ?

Parce qu'il est honnête. Sur le cerveau de référence, **96 % des rappels sont rendus en
confiance basse**. Le rappel trouve, mais doute.

Un cerveau qui affirmerait tout à 95 % serait bien plus inquiétant, surtout au vu du
chiffre précédent : 98 % du savoir n'a jamais été audité.

**Mais ne comptez pas améliorer cette mesure-là en relisant.** « 96 % des rappels en
confiance basse » ne décrit pas vos atomes : c'est `recall_low_band_ratio`, la part des
**rappels servis** dont la bande finale est `low` ou `none`, calculée sur
`arac.context_receipts`. Aucun geste d'utilisateur n'y touche — elle bouge quand le corpus
grossit et que les distances se resserrent.

Ce que vous pouvez faire, et ce que vous ne pouvez pas, est détaillé plus haut, à
« Pourquoi mon cerveau ne trouve rien après une semaine ? » : le score chiffré d'un atome se
retouche par `PATCH`, la **trace d'audit** ne se pose pas — et c'est elle que compte l'autre
chiffre de ce paragraphe, les 98 %.

### Pourquoi trois cycles par jour et pas en continu ?

**Parce que penser coûte, et qu'une pensée continue coûte en continu.**

Entre deux cycles, le cerveau accumule ; au cycle, il traite tout ce qui s'est accumulé
d'un coup. Corollaire à retenir : **ce que vous dites à 14 h n'est pas mémorisé à
14 h 01.** Un cerveau au repos qui n'a rien produit depuis six heures fonctionne
peut-être parfaitement.

Vous pouvez changer les heures (`ARAC_CYCLES`) ou en supprimer. Pensez alors à ajuster
`ARAC_ALERT_STALL_HOURS`, sinon l'alarme « le cerveau a cessé d'apprendre » sonnera pour
un cerveau en bonne santé — et vous la couperez, ce qui est le début de la fin d'un
système d'alerte.

---

## La panne, la perte, la reprise

### Que se passe-t-il si je perds le serveur ?

**Vous perdez tout ce qui n'était pas dans une sauvegarde restaurable.** Pas
« sauvegardée » : **restaurable**. Ce n'est pas la même chose, et la différence se mesure
le jour où ça arrive.

Ce qu'il faut avoir fait **avant** :

1. Une sauvegarde qui tourne (le bootstrap en arme une toutes les six heures).
2. **Une restauration réellement exécutée au moins une fois** :
   `ops/restore_verify.sh` restaure dans une base jetable et prouve le contenu.
   Tant que vous ne l'avez pas fait, vos dumps sont une hypothèse.
3. **Une copie hors site** (`ARAC_OFFSITE_DEST`). Sans elle, vos sauvegardes
   disparaissent avec le serveur qui les héberge — ce qui est précisément le scénario
   qu'on prépare.
4. Le chiffrement au repos (`ARAC_BACKUP_RECIPIENTS`), **avec la clé privée ailleurs**.

La reconstruction, elle, est rapide : `git clone`, `wizard.py` avec les mêmes réponses,
`bootstrap.sh`, puis `pg_restore` du dernier dump. Le code est reproductible ; c'est la
mémoire qui ne l'est pas.

Tout est dans [`SAUVEGARDE.md`](SAUVEGARDE.md), y compris la procédure de restauration
réelle — celle qu'on exécute en panique, et qu'il vaut mieux avoir lue à froid.

### Puis-je déplacer mon cerveau sur un autre serveur ?

Oui, et la procédure complète — exécutée de bout en bout, avec ce que rend chaque
commande — est au **§ 9 de [`SAUVEGARDE.md`](SAUVEGARDE.md)**. Rien n'est en dur :
`ARAC_HOME` décide où vit le code, `config/brain.toml` décide de l'identité.

**Emportez trois choses, pas une** : le dump, `config/brain.toml` et `config/scopes.toml`.
Le premier porte la mémoire ; le deuxième porte l'**empreinte d'installation**, sans
laquelle la machine d'arrivée en fabrique une neuve et votre propre dump cesse d'être
reconnu comme le vôtre (mesuré : « *✗ CE DUMP N'EST PAS LE VÔTRE* », et cela ne se
rattrape pas après coup) ; le troisième porte la taxonomie, dont dépendent les scopes de
chaque atome.

**Deux pièges, tous deux mesurés.** `pg_restore` **directement dans la base que le
bootstrap vient de créer** rend 210 erreurs et un cerveau que `verify_install.sh` refuse
(« *✗ Ce cerveau n'est pas sain* ») : on restaure dans une base neuve et on bascule,
exactement comme au § 7. Et « refaire les `GRANT` » ne suffit pas — un `GRANT` sur les
tables d'un schéma dont on n'est pas propriétaire n'ouvre rien : c'est
`sudo ./bootstrap/bootstrap.sh --only migrations` qui reprend la propriété, referme la
base à `PUBLIC` et rejoue les migrations, dans cet ordre.

**Gardez le même `node_id`.** Le changer scinderait la provenance de tout ce qui est déjà
entré en deux populations.

**Et finissez le déménagement** : l'ancienne machine porte encore votre mémoire tant que
vous n'avez pas fait le [§ 13 d'`INSTALLATION.md`](INSTALLATION.md#13-désinstaller) en
entier, contrôle de fin compris.

### Et si je veux tout arrêter ?

Il n'y a pas de script de désinstallation, délibérément : un outil qui sait détruire une
mémoire est un outil dangereux à livrer. Les gestes, à faire à la main, sont listés dans
[`INSTALLATION.md` §13](INSTALLATION.md#13-désinstaller).

Le premier d'entre eux est un `pg_dump`. Faites-le même si vous êtes sûr de vous : ce que
contenait ce cerveau avait coûté des mois de conversations et une facture d'API.

Le **dernier** d'entre eux est un contrôle, et il compte autant. « Arrêter » ne veut pas
dire « ne plus s'en servir » : un dump se restaure, donc tant qu'il en reste un ici, votre
mémoire est ici — sur une machine dont vous venez de retirer le coffre, les rôles et les
unités qui la protégeaient. `ops/uninstall_check.sh` reconnaît ces copies à l'**empreinte
gravée dedans**, pas à leur nom, et refuse de dire « PROPRE » tant qu'il en trouve une.

---

## Le projet

### Est-ce que ça marche vraiment, ou est-ce une démo ?

**Le moteur tourne depuis des mois sur une installation réelle** — c'est de là que
viennent tous les chiffres cités dans cette documentation. Ce sont des mesures, pas des
estimations.

**Et ce dépôt-ci a été installé de bout en bout, plusieurs fois, sur des machines neuves.**
Cette réponse a longtemps dit le contraire — « seule la *simulation* du bootstrap a été
vérifiée ». C'était vrai en juillet ; ça ne l'est plus, et une alarme périmée coûte aussi
cher qu'une promesse creuse. Voici la coupure exacte, à la date du 10 août 2026.

**Ce qui a réellement tourné**, et pas une fois :

- **des installations complètes**, par le chemin documenté — l'entretien derrière un vrai
  terminal, le mot de passe du cockpit tapé aux invites, l'appairage à deux facteurs
  confirmé, puis `bootstrap.sh` **sans** `--yes` : base, rôles nommés d'après le cerveau,
  extension vectorielle, migrations, secrets, unités `systemd`, API et cockpit qui
  répondent ;
- **le cycle de vie entier** : un souvenir écrit par la vraie route `POST /v1/atoms`, une
  supersession, une conversation ingérée par le vrai pont, une sauvegarde produite par
  **l'unité** (pas par une commande à la main), cette sauvegarde **restaurée** et comparée,
  la base détruite pour de vrai (`DROP SCHEMA arac CASCADE`) puis le cerveau remonté depuis
  son dump, et enfin la désinstallation du § 13 jouée mot pour mot jusqu'au verdict
  « PROPRE » ;
- **deux cerveaux côte à côte sur la même machine**, installés par le vrai chemin : ils ne
  se lisent pas, ne s'écrivent pas, ne se détruisent pas. Le jeton de l'un rend 401 chez
  l'autre, le coffre de l'un est illisible depuis le compte de l'autre, et une seconde
  installation qui reprendrait le nom ou le port de la première est **refusée avant toute
  écriture** ;
- `sudo make acceptance`, qui rejoue tout cela à chaque passage et rend **0 échec, 0
  intervention manuelle**.

**Ce qui n'a toujours pas été éprouvé**, et c'est court :

- **la moitié macOS du pont.** Les deux programmes du pont ont tourné, sur Linux, contre
  des cerveaux vivants, jusqu'à l'ingestion réelle d'une conversation. Mais `launchd`,
  `plutil`, l'emplacement réel des données de Claude Desktop et un tunnel SSH ouvert depuis
  un poste réel n'ont jamais tourné : aucun agent de ce dépôt n'a de Mac. **C'est le
  maillon que vous éprouverez le premier** ;
- **la dépense réelle.** Le harnais double le fournisseur d'embeddings pour ne pas payer ;
  le mode qui paie existe mais **meurt à sa première dépense** aujourd'hui (une erreur de
  validation, corrigée en quelques lignes le jour où quelqu'un s'en occupera) ;
- **la durée.** Aucun cerveau né de ce framework n'a plus de quelques jours. Tout ce que
  cette documentation dit du long terme vient du cerveau de référence, qui a précédé le
  framework.

Le détail, avec la commande qui rejoue chaque affirmation, est dans
[`docs/LIMITES-CONNUES.md`](LIMITES-CONNUES.md) §2 — seul endroit où cette liste est tenue.

**Ce qui reste vrai, et qui compte le plus** : le chemin a été parcouru par des agents qui
avaient le dépôt sous les yeux. Il n'a pas encore été parcouru par **vous**. C'est
l'assertion F8 de [`GOAL.md`](../GOAL.md), et c'est la dernière qui manque.

Le point qui bloquait jusqu'ici — bootstrap et moteur lisant des noms de variables
différents — est traité **entièrement** : `poser_pont_de_vocabulaire`
(`bootstrap/lib/secrets.sh`) traduit les sept variables de `arac.env` **et** les trois
secrets du cockpit dans `cockpit.env`. C'était la dernière intervention humaine du
parcours. Le contrôle qui tranche, sur votre machine :
`sudo grep -cE '^(CC_SESSION_SECRET|CC_ADMIN_PASSWORD_HASH|CC_TOTP_SECRET)='
/etc/arac/<votre_base>/cockpit.env` doit rendre `3` ; s'il rend `0`, votre installation est
antérieure au correctif et le geste manuel est dans
[`DEPANNAGE.md` §1](DEPANNAGE.md#1-lapi-ne-démarre-pas--database_url_app-non-définie).

Si vous êtes la première personne à parcourir ce chemin : **notez chaque friction.**
C'est la dernière chose qui manque.

### Puis-je l'utiliser à plusieurs ?

**Non.** Un cerveau, une personne. Il n'y a pas de gestion d'utilisateurs, pas de
permissions par domaine, pas de partage. Le cockpit a un mot de passe, pas des comptes.

Plusieurs cerveaux peuvent cohabiter sur la même machine — tout ce qui dépend de
l'identité est engendré, jamais recopié, y compris les noms d'unités systemd :

```bash
sudo ARAC_API_PORT=8010 ARAC_COCKPIT_PORT=8110 ./bootstrap/bootstrap.sh
```

Mais ce sont deux cerveaux séparés qui ne partagent rien, pas un cerveau à deux têtes.

### Puis-je modifier le code ?

C'est fait pour. Deux conseils, tirés de ce qui a coûté cher :

1. **N'écrivez jamais un chemin absolu.** Passez par `arac_runtime.path()`. Le cerveau de
   référence avait le même chemin d'installation, en dur, dans plus de trois cents
   fichiers ; le premier travail du portage a été de tous les remplacer.
2. **Ne changez pas le format de la provenance** (`source_ref`) sans écrire, dans la même
   migration, la conversion de l'existant. C'est exactement ce qui a coupé le lien entre
   les souvenirs et leurs conversations sur le cerveau de référence : **76 % du savoir ne
   sait plus d'où il vient.** Il est encore là, mais plus vérifiable. Un souvenir sans
   provenance n'est pas un souvenir, c'est une rumeur.

Et avant tout : `make test`. La suite est **hermétique** — ni base, ni réseau, ni clé —
et ce n'est pas une promesse : `tests/garde_hermetique.py` coupe le réseau et refuse toute
base qui n'appartient pas au test. Elle tourne donc sur un dépôt fraîchement cloné, en une
vingtaine de secondes, **y compris sur un serveur qui héberge déjà un cerveau**.

### Pourquoi tant de contraintes — quatre rôles, pas de DELETE, une taxonomie figée ?

Parce que chacune vient d'une erreur qui a coûté quelque chose.

| Contrainte | L'erreur qu'elle empêche |
|---|---|
| des rôles PostgreSQL séparés — et nommés d'après le cerveau —, cockpit en lecture **stricte** | un tableau de bord qui a un bogue et écrit dans la mémoire ; et un second cerveau qui, en s'installant, réencode les mots de passe du premier |
| pas de `DELETE` pour le rôle applicatif | perdre la trace de ce qu'on a cru et de quand on a changé d'avis |
| taxonomie opposable (422 à l'entrée) | une mémoire fragmentée en dizaines de catégories jumelles, sans que rien ne le signale |
| refus des conversations d'un nœud non déclaré | avaler n'importe quoi : un agent mal configuré, un import de test, un doublon |
| le `--dry-run` du bootstrap | découvrir ce qu'on a installé après l'avoir installé |

Un cadre qui rendrait ces contraintes optionnelles serait plus agréable la première heure
et beaucoup plus coûteux le sixième mois.

### Où sont les leçons du cerveau de référence ?

Elles sont partout dans cette documentation, et ce n'est pas un hasard : **l'expérience de
l'installation d'origine est le manuel**. Les sept chiffres qui reviennent :

| Fait mesuré | La leçon |
|---|---|
| près d'un souvenir actif sur onze posé sur une racine nue | il reste rappelable par similarité pure, mais il est hors de l'état courant, de la vue des scopes et de la couverture — le piège n°1 |
| 76 % de la provenance perdue | figez le format de `source_ref` tôt |
| 36 % des cycles en quarantaine, 0 atome | la cause était des identifiants incohérents, pas le volume |
| ~87 000 jetons/cycle, ~31 500/atome | le coût d'exploitation est réel, et il s'annonce en première page |
| 96 % des rappels en confiance basse | le rappel trouve, mais doute : la calibration compte autant que la recherche |
| 98 % du savoir jamais audité | le cerveau est confiant sur ce qu'il n'a jamais vérifié |
| 3 cycles/jour, 04:00 · 13:00 · 21:00 | le cerveau digère par cycles : l'état de repos est normal |

Ce sont des mesures, jamais des menaces. Un utilisateur prévenu ne refera pas ces fautes —
c'est tout l'intérêt de les écrire.
