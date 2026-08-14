# L'architecture — la chaîne complète, maillon par maillon

Ce document suit une phrase que vous avez dite à Claude un mardi soir, jusqu'au jour où
elle vous revient sous forme de savoir. Treize maillons. **Aucun n'est sauté**, y compris
ceux qui n'existent pas encore — ils sont marqués comme tels.

Pour chaque maillon : ce qui entre, ce qui sort, ce qui peut mal tourner, et où
regarder quand ça tourne mal.

Prérequis de lecture : [`CONCEPTS.md`](CONCEPTS.md). Sans les notions d'atome, de scope
et d'embedding, ce document se lit mais ne s'apprend pas.

---

## La chaîne, vue de très haut

```
  VOTRE MACHINE                    │ LE TUNNEL │        VOTRE SERVEUR
  ─────────────────────────────────┼───────────┼──────────────────────────────────
                                   │           │
  ① Claude Desktop / Claude Code   │           │
        │ écrit sur disque         │           │
        ▼                          │           │
  ② conversations locales          │           │
        │ lues, filtrées           │           │
        ▼                          │           │
  ③ agent de synchronisation ──────┼─④ SSH ────┼──▶ ⑤ serveur (systemd + API)
                                   │           │         │
                                   │           │         ▼
                                   │           │    ⑥ ingestion  → messages bruts
                                   │           │         │
                                   │           │         ▼
                                   │           │    ⑧ extraction (cycles IA)
                                   │           │         │  ⑦ embeddings ◀── externe
                                   │           │         ▼
                                   │           │    ⑨ atomes
                                   │           │         │
                                   │           │         ├─▶ ⑩ graphes  (partiel)
                                   │           │         ├─▶ ⑪ mémoire
                                   │           │         └─▶ ⑫ cockpit  (lecture seule)
                                   │           │                  │
  ⑬ Claude Code ◀──────────────────┼───────────┼──────────────────┘
```

Deux propriétés à retenir avant d'entrer dans le détail :

- **Le serveur n'est jamais exposé.** L'API et le cockpit écoutent sur la boucle locale.
  Rien de tout cela n'a d'adresse publique. Le seul chemin d'entrée est le tunnel SSH.
- **Le flux est unidirectionnel à l'écriture.** Vos conversations montent, vos atomes
  descendent. Le serveur ne va jamais chercher quoi que ce soit sur votre machine.

---

## ① Claude Desktop · Claude Code — la source

**Entre** : vous, qui parlez.
**Sort** : des fichiers de conversation, sur le disque de votre machine.

C'est le seul maillon qu'ARAC ne contrôle pas du tout. Il n'y a pas d'API officielle pour
récupérer vos conversations : ARAC lit ce que ces applications laissent sur le disque.

- **Claude Code (CLI)** écrit un fichier par conversation dans `~/.claude/projects/`, au
  format une-ligne-par-message. C'est le cas le mieux traité : le format est lisible,
  stable, incrémental.
- **Claude Desktop** ne laisse pas de format documenté. La voie retenue est **l'export
  officiel** que vous déclenchez depuis l'application. Ce n'est pas automatique, et c'est
  une limite réelle du système, pas un oubli.

**Ce qui peut mal tourner.** Une mise à jour de l'application change le format sur disque
sans prévenir. Le symptôme est silencieux : la synchronisation dit « rien de nouveau »
alors que vous avez parlé toute la journée.
**Où diagnostiquer.** La commande d'inventaire du pont liste ce qu'elle voit, sans rien
envoyer. Si votre conversation d'hier n'y figure pas, le problème est ici, pas plus loin.
Le détail est dans [`PONT-MAC.md`](PONT-MAC.md).

---

## ② Les conversations locales — ce qui part, ce qui ne part pas

**Entre** : les fichiers du maillon ①.
**Sort** : une sélection, filtrée, que vous avez vue avant qu'elle parte.

Ce maillon n'est pas un tuyau : c'est une **porte**. Le principe est qu'on ne synchronise
jamais à l'aveugle. L'agent de synchronisation dispose d'un mode qui **annonce** ce qu'il
enverrait — combien de conversations, lesquelles, combien de messages — et **n'envoie
rien**. C'est ce mode qu'on lance en premier, et à chaque doute.

Le filtrage se règle dans votre fichier de configuration du pont : quels dossiers, quels
projets, quelles conversations sont exclus.

**Ce qui peut mal tourner.** Vous envoyez plus que ce que vous croyiez. C'est
irréversible : ce qui est parti est en base, et il faudra l'en sortir à la main.
**Où diagnostiquer.** Avant, jamais après. Le mode annonce est là pour ça.

---

## ③ La synchronisation — l'agent qui monte la garde

**Entre** : la sélection du maillon ②.
**Sort** : des requêtes HTTP vers l'API, une conversation par lot.

Sur votre machine, un agent tourne à intervalle régulier (via `launchd` sur Mac). Il
tient un **état local** : jusqu'où il est allé dans chaque conversation. C'est ce qui
rend une deuxième passe silencieuse — si vous relancez immédiatement, il ne doit **rien**
repartir.

Trois propriétés qui comptent :

- **Idempotence.** Chaque message porte une clé de déduplication. Renvoyer deux fois le
  même message ne crée pas de doublon en base : le second est ignoré.
- **Reprise.** Une coupure en cours de lot ne perd rien : le curseur local n'avance que
  sur ce que le serveur a explicitement acquitté.
- **Acquittement réel.** Un `200 OK` ne suffit pas. Le serveur répond avec le décompte de
  ce qu'il a effectivement écrit ; c'est ce décompte qui fait avancer le curseur.

**Ce qui peut mal tourner.** L'état local n'est pas persisté (droits insuffisants sur son
répertoire) : tout repart à chaque passe. Le serveur dédoublonne, donc la base reste
propre, mais vous générez du trafic inutile en permanence.
**Où diagnostiquer.** Lancez deux fois de suite. La seconde doit dire « rien de nouveau ».
Si elle renvoie des messages, c'est l'état local. Détail complet dans
[`PONT-MAC.md`](PONT-MAC.md).

---

## ④ Le tunnel SSH — pourquoi pas une adresse publique

**Entre** : les requêtes HTTP du maillon ③, sur la boucle locale de votre machine.
**Sort** : les mêmes requêtes, sur la boucle locale du serveur.

Le tunnel fait qu'un port de votre machine *est* un port du serveur. L'API n'écoute que
sur `127.0.0.1` côté serveur : sans le tunnel, elle est injoignable, y compris depuis
Internet, y compris si votre pare-feu est mal réglé.

**Pourquoi pas une adresse publique et un certificat ?** Parce que cela ferait de votre
mémoire personnelle un service exposé, avec tout ce que cela implique : balayages
automatisés permanents, gestion de certificats, surface d'attaque sur chaque
dépendance web. Le tunnel supprime le problème au lieu de le gérer. Le coût est réel : si
le tunnel est fermé, **rien ne monte**.

**Pourquoi une supervision du tunnel plutôt qu'un `ssh` simple ?** Un `ssh` seul meurt en
silence quand le réseau change (veille, Wi-Fi, VPN). Il est donc relancé par un
superviseur qui vérifie que le tunnel transporte réellement quelque chose, pas seulement
que le processus est vivant. Un tunnel « ouvert » qui ne transporte rien est le mode de
panne le plus fréquent, et le plus discret.

La clé SSH utilisée est **restreinte au seul tunnel** : elle ne doit pas pouvoir ouvrir
un shell sur le serveur.

**Ce qui peut mal tourner.** Le processus tourne, le port local existe, et rien ne passe.
**Où diagnostiquer.** Interroger le port local avec un client HTTP. Une réponse — même
`401` — prouve que le tunnel transporte. Aucune réponse : le tunnel est mort.

---

## ⑤ Le serveur — ce qui tourne, sous quels rôles

**Entre** : les requêtes acheminées par le tunnel.
**Sort** : tout le reste du système.

Sur un Ubuntu, gérés par `systemd` :

| Ce qui tourne | Rôle |
|---|---|
| L'API (FastAPI) | Reçoit l'ingestion, sert les atomes et le rappel |
| Le cockpit | Interface de lecture, sur la boucle locale |
| Les minuteries | Sauvegarde, vérification de restauration, santé, contrôle d'installation |
| Le cycle d'extraction | Trois fois par jour (maillon ⑧) |

Sous tout cela, **PostgreSQL 16 avec l'extension vectorielle**, et des rôles distincts —
c'est un point de conception, pas un détail d'exploitation. **Chacun porte le nom de votre
cerveau**, parce qu'un rôle PostgreSQL est global au *cluster* et non propre à une base :
sans ce préfixe, installer un second cerveau réencode les mots de passe du premier.

| Rôle | Peut faire | Pourquoi séparé |
|---|---|---|
| `arac_<base>_admin` | Modifier le schéma | Les migrations, et rien d'autre |
| `arac_<base>_app` | Lire et écrire les données | L'API |
| `arac_<base>_agent` | Lire, et écrire ce qui le concerne | Les agents d'extraction |
| `arac_<base>_readonly` | **Lire, strictement** | Le cockpit |
| `arac_<base>_backup` | Rien : rôle **sans connexion**, cible des `GRANT SELECT` de la sauvegarde | Un processus automatique n'a pas à pouvoir détruire un schéma |

Le cockpit sous rôle en lecture stricte est ce qui garantit qu'un tableau de bord ne peut
pas modifier ce qu'il observe — même en cas de faille dans son code.

Les migrations ne nomment aucun de ces rôles : elles les **déduisent** du rôle
d'administration sous lequel elles tournent (`db/alembic/roles.py`). Le nommage est donc
vérifiable des deux côtés, sans configuration tenue en double.

**Ce qui peut mal tourner.** Un service ne redémarre pas après un reboot ; une migration
n'a pas été appliquée et l'API refuse de démarrer ; **les droits** n'ont pas été
réappliqués après une restauration — une base restaurée avec `--no-owner` a perdu ses
`GRANT`, pas ses rôles, et c'est `bootstrap.sh --only migrations` qui les repose
(voir [`SAUVEGARDE.md`](SAUVEGARDE.md) §7).
**Où diagnostiquer.** Le contrôle d'installation et le bulletin de santé, décrits dans
[`EXPLOITATION.md`](EXPLOITATION.md).

---

## ⑥ L'ingestion — comment un message devient une ligne

**Entre** : une conversation et ses messages, par HTTP.
**Sort** : des lignes dans `arac.conversations` et `arac.raw_messages`.

C'est le maillon le plus défensif du système, parce que c'est la seule porte par laquelle
des données extérieures entrent. Ce qui s'y passe, dans l'ordre :

1. **Authentification** par jeton porteur, propre à chaque poste source, **sans
   exception d'origine** — la boucle locale comprise ; seul `/healthz` reste public. La
   boucle locale en était exemptée : sur une machine à deux cerveaux, tout compte local y
   lisait et y écrivait la mémoire du voisin sans un seul secret, et aucune permission de
   fichier ne voyait ce chemin. L'encadré de
   [`CONFIGURATION.md` §6](CONFIGURATION.md#6-lapi) raconte la leçon et dit comment
   rouvrir la boucle locale — deux variables, dont un motif écrit.
2. **Liste blanche de postes** : un `node_id` inconnu est refusé (`403`), même avec un
   jeton valide, et **y compris depuis la boucle locale**. C'est la seule des deux
   couches qui s'applique sans exception.
3. **Validation stricte** du corps : tout champ inattendu est refusé.
4. **Plafonds durs** hors validation : taille du corps, nombre de messages par lot,
   taille d'un message. Refusés avec un `400` qui **nomme le message fautif**.
5. **Masquage des secrets**, deuxième couche : l'agent de synchronisation a déjà masqué
   côté machine (maillon ③), le serveur remasque avant tout stockage. Une clé d'API ou un
   mot de passe repéré est remplacé, et le nombre de masquages est consigné dans le reçu.
   Deux filtres, parce qu'un seul finit toujours par être contourné — et parce que le
   serveur ne doit rien devoir à la bonne conduite du client.
6. **Empreinte calculée côté serveur**, après masquage. Jamais celle que le client
   annonce : une empreinte fournie par le client ne prouve rien.
7. **Écriture idempotente** : clé de déduplication par message, conflit ignoré.

Trois mécanismes de preuve, et ils méritent d'être compris :

- **Les reçus d'ingestion.** Chaque requête — acceptée **ou refusée** — laisse une ligne
  avec son identifiant de requête, renvoyé dans la réponse et dans un en-tête. Le reçu
  d'une acceptation est écrit **dans la même transaction** que les messages : si l'un est
  annulé, l'autre l'est aussi. Il n'existe pas d'état où les messages sont là sans reçu,
  ni l'inverse.
- **Les révisions.** Si un message déjà connu revient avec un **contenu différent**, le
  serveur **ne le modifie pas**. Il écrit une ligne de divergence dans une table en
  ajout-seul. Les messages bruts ne sont jamais réécrits — c'est la matière première, et
  une matière première qu'on réécrit n'est plus une preuve.
- **Le curseur de curation.** Chaque conversation porte un `curated_through_message_id` :
  jusqu'où l'extraction est allée. **L'ingestion n'y touche jamais.** Il appartient
  exclusivement au maillon ⑧.

**Aucun embedding n'est calculé ici.** Les messages bruts n'ont pas de vecteur. Vous
pouvez ingérer des centaines de milliers de messages pour zéro centime.

**Ce qui peut mal tourner.** `401` (jeton), `403` (poste non déclaré), `400` (contenu
refusé), `413` (trop gros), `429` (trop de messages sur l'heure).
**Où diagnostiquer.** Les reçus : ils existent aussi pour les refus, et portent le motif.
Chaque code d'erreur et sa marche à suivre sont dans [`PONT-MAC.md`](PONT-MAC.md).

---

## ⑦ Les embeddings — le seul appel externe

**Entre** : le texte d'un atome (à l'écriture), ou le texte d'une question (au rappel).
**Sort** : 3 072 nombres, stockés en demi-précision.

Ce maillon est **transversal** : il n'a pas sa place dans l'ordre du flux, il est appelé
depuis deux endroits.

```
  écriture d'un atome  ──▶ embed(valeur)  ──▶ colonne embedding
  rappel               ──▶ embed(question)──▶ comparaison
```

Le modèle est `text-embedding-3-large`, 3 072 dimensions, chez un prestataire externe.
**Pas d'inférence locale.** Trois tentatives sur erreur transitoire (limite de débit,
délai dépassé, coupure), échec immédiat sur erreur d'authentification ou de requête.

Sécurité : ni le texte envoyé ni la clé ne sont journalisés. Seule la **longueur** du
texte apparaît dans les journaux.

**Ce qui peut mal tourner, et c'est important.** Sans clé valide, sans réseau, ou pendant
une panne du prestataire :
- aucun atome nouveau ne peut être écrit (l'écriture embedde avant d'insérer) ;
- **aucun rappel ne peut aboutir** — il faut embedder la question, pas seulement les
  souvenirs.

C'est la dépendance externe la plus dure du système, et elle rend le cerveau
temporairement muet. Le cockpit, lui, continue de fonctionner : il ne fait que du SQL.

**Où diagnostiquer.** Les journaux portent un événement d'échec avec le type d'erreur et
la latence. Une erreur d'authentification pointe le fichier d'environnement du service ;
une erreur de connexion pointe le réseau du serveur.

---

## ⑧ L'extraction — la digestion, trois fois par jour

**Entre** : des messages bruts non encore curés.
**Sort** : des propositions d'atomes, en JSON strict.

C'est le maillon le plus coûteux, le plus fragile, et celui qui produit toute la valeur.

### Pourquoi par cycles, et pas en continu

Un cerveau digère, il ne rumine pas. Trois cycles par jour — typiquement **04:00, 13:00
et 21:00**, heure locale — sur le rythme observé. Entre deux cycles, le système est au
**repos** : rien ne bouge, aucun atome n'apparaît. **C'est l'état normal.** Un cockpit
qui n'a rien produit depuis quatre heures ne signale pas une panne ; il signale qu'on est
entre deux repas.

Trois raisons à ce choix : le coût (on décide combien on dépense par jour), la
prévisibilité (on sait quand regarder), et l'amortissement (une conversation encore
active a le temps de finir avant d'être digérée).

### La machine d'un cycle

```
  frein à dépense ──── NON ──▶ reçu « ignoré », motif, sortie propre
        │ OUI
        ▼
  reçu « démarré »                        ← écrit AVANT toute dépense
        │
        ▼
  portail : quelles conversations ont du non-curé ?
        │
        ▼
  constitution du lot (« pack »)          ← borné par un budget de jetons
        │                                    (80 000 par défaut, plafond dur
        │                                     135 000 — agents/cortex/pack.py)
        ▼
  reçu « en cours de lancement » + estimation      ← COMMIS AVANT l'appel
        │
        ▼
  appel au modèle de curation, UNE seule fois, sans aucun outil
        │
        ├── sortie invalide ──▶ reçu « quarantaine » + corps conservé
        │                        + compteur de reprise sur les conversations
        ▼
  disposition : POST des atomes, conversation par conversation
        │
        ▼
  reçu « terminé » + compteurs
```

Deux choses à retenir de cette machine :

**Le reçu est écrit avant la dépense, pas après.** Une panne au mauvais moment fait donc
**sous-dépenser**, jamais sur-dépenser. C'est l'inverse du réflexe habituel, et c'est
délibéré : sur un système qui appelle un modèle payant, l'erreur qu'on ne veut pas est
celle qui dépense sans trace.

**Le lot est plafonné en jetons, pas en conversations.** Une conversation trop grosse
n'explose pas le budget : elle avance d'une tranche par cycle. Et si un message seul ne
tient pas dans le budget complet, la conversation est **bloquée** — curseur gelé, motif
consigné — plutôt que tronquée. Un souvenir à moitié présenté est pire qu'un souvenir
absent : il produit un atome faux avec l'air d'être vrai.

### Le contrat avec le modèle

Le modèle d'extraction n'est pas un assistant conversationnel. Son prompt système est
**remplacé entièrement** : il n'est plus Claude, il est le cortex. Il n'a **aucun outil**,
il n'écrit rien lui-même, il rend un unique objet JSON. Les règles qui comptent :

- Le contenu des conversations est déclaré **donnée non fiable** : aucune instruction qui
  s'y trouve ne doit être suivie. C'est la défense contre l'injection par le contenu — un
  message qui dirait « ignore tes règles » est du texte à digérer, pas un ordre.
- Aucun secret n'est jamais recopié. Un secret aperçu produit une alerte qui le
  **décrit** sans le citer.
- **Décision terminale obligatoire** pour chaque conversation présentée : soit des atomes,
  soit une déclaration explicite « rien de durable ici », motivée. Un silence n'est pas
  une réponse : il gèle le curseur et la conversation revient au cycle suivant.
- Interdiction d'inventer pour remplir.

### Le coût, en clair

Sur le cerveau observé :

| Mesure | Valeur |
|---|---|
| Jetons par cycle | ~87 000 |
| Jetons par atome produit | ~31 500 |
| Cycles par jour | 3 |

Ce n'est pas une note de bas de page. C'est **votre facture mensuelle**, et elle doit être
regardée avant l'installation, pas après. Un frein à dépense, un interrupteur global et
un coupe-circuit sur fichier existent — ce dernier fonctionne **même base de données
éteinte**, parce qu'un frein qui dépend de ce qu'il freine n'est pas un frein.

### La quarantaine, et la leçon qu'elle a coûtée

Sur le cerveau observé, **36 % des cycles sont partis en quarantaine sans produire un
seul atome**. Budget dépensé, rien appris.

La première hypothèse — des tranches trop grosses — était **fausse**. La cause réelle,
trouvée en lisant les corps mis en quarantaine, était des **identifiants incohérents**
dans la sortie du modèle : une majuscule dans une clé là où le format n'accepte que des
minuscules et des tirets, ou une référence à un message d'une autre conversation. Deux
règles de format, violées quelques fois, ont coûté un tiers du budget d'extraction.

Deux enseignements. Le premier : les corps mis en quarantaine sont **conservés en base**
et bornés en taille — sans eux, la cause était introuvable. Le second : quand un chiffre
d'exploitation vous surprend, allez lire les lignes avant de formuler une hypothèse.

**Où diagnostiquer.** Les reçus de cycle : un par cycle **et un par cycle ignoré, avec le
motif**. La file de revue rassemble ce qui demande un arbitrage humain.

---

## ⑨ Les atomes — l'écriture, et ses remparts

**Entre** : les propositions du maillon ⑧.
**Sort** : des lignes dans `arac.memory_atoms`.

Chaque atome proposé passe par l'API comme n'importe quelle écriture :

1. **Validation du scope** contre l'énumération engendrée par votre taxonomie. Hors
   liste : `422`, avant la base. La base repose la question par clé étrangère.
2. **Validation du format de la clé** : minuscules, chiffres, tirets. Strictement.
3. **Règles de type** : une décision sans son pourquoi est refusée.
4. **Embedding** de la valeur (maillon ⑦), **hors transaction** pour ne pas tenir une
   connexion pendant un appel réseau de 300 ms.
5. **Insertion**, avec avertissements consignés si quelque chose sent mauvais sans être
   interdit : mélange de mondes dans une même valeur, collision d'empreinte, couple
   scope/type sans précédent, justification suspecte de brièveté.
6. **Archivage à la naissance** : un déclencheur en base
   (`arac.tg_auto_archive_low_confidence`, un `BEFORE INSERT`) range en archive de faible
   confiance tout atome **écrit** portant à la fois `audit_source =
   'autonomous_agent_suggest'` et un `confidence_score` non nul **sous 70** — 69 archivé,
   70 vivant. Il ne regarde ni les `UPDATE` (baisser un score par `PATCH` ne déclasse
   rien), ni les atomes sans cette trace, ni ceux sans score. Une supersédure passant par
   ce chemin **hérite** du score de l'atome remplacé : c'est le cas qui coûte un souvenir,
   et l'API le signale par l'avertissement `W-008` — qui, comme tous les avertissements
   ci-dessous, **n'empêche rien**.

Les avertissements sont un dispositif à part : ils **n'empêchent rien**. Ils laissent une
trace consultable. Un système qui refuse tout ce qui est douteux devient inutilisable ; un
système qui ne dit rien devient opaque.

**Ce qui peut mal tourner.** Un `422` en série sur les scopes signale que l'énumération et
la base ont divergé — typiquement, une taxonomie régénérée sans que la migration
correspondante soit appliquée.
**Où diagnostiquer.** Les compteurs du cycle, et le journal des avertissements.

---

## ⑩ Les graphes — ce qui existe, et ce qui n'existe pas

**Entre** : les atomes en base.
**Sort** : des arêtes dans `arac.atom_links`.

Le graphe est recalculé à chaque cycle, **avant le frein à dépense** : il ne coûte rien,
il ne fait que du SQL sur des données déjà présentes.

**Ce qui est écrit — trois types d'arêtes, et deux natures très différentes.**

*Certaines* (dérivées, sans seuil, zéro faux positif) :

- `supersedes` — « ceci remplace cela ». Dérivé d'une colonne, pas d'un seuil. Cette
  arête **traverse les statuts** : l'atome remplacé est en `superseded`, donc aucun
  filtre « actif » ne s'applique de son côté.
- `same_thread` — « ceci suivait cela dans la même conversation ». Chaîne
  chronologique **linéaire** : N atomes produisent N−1 arêtes, jamais N². Une conversation
  de 71 atomes donne 70 arêtes, pas 2 485. C'est le garde-fou anti-pelote : un graphe
  dense est illisible et coûteux, et il n'apprend rien de plus qu'une chaîne.

*Inférée* (seuil, donc faux positifs possibles) :

- `semantic_neighbor` — « ces deux atomes se ressemblent ». Voisinage **réciproque** :
  A n'est relié à B que si chacun figure parmi les 6 plus proches voisins de l'autre, et
  seulement en deçà d'une distance cosinus de 0,25. La réciprocité et le plafond de 6
  sont ce qui empêche un atome « moyen » de devenir un carrefour relié à tout.

**Ce que cette arête inférée n'est pas.** Elle dit *« ces deux textes se ressemblent »*,
et rien d'autre. Elle ne dit pas que l'un confirme l'autre, ni qu'il le contredit — la
géométrie ne distingue pas les deux (maillon ⑦). C'est une ressemblance matérialisée,
pas une relation de sens.

**Ce qui n'existe pas :**

- **Aucun chemin servi ne lit `atom_links`.** La table est écrite à chaque cycle, elle
  est fraîche, elle est interrogeable — mais ni `/v1/atoms/recall`, ni
  `/v1/atoms/context_for`, ni `/v1/atoms/resume` ne la consultent. Le rappel que vous
  obtenez ne doit **rien** à ce graphe : il vient de la distance vectorielle et du
  filtre de domaine. Traitez donc `atom_links` comme un matériau d'observation, pas
  comme une capacité sur laquelle s'appuyer.
- **Aucun mécanisme ne détecte les contradictions.** Deux atomes actifs qui s'opposent
  cohabitent sans qu'aucune alarme ne se déclenche. Il existe bien un type d'atome
  `contradiction` et une fonction pure capable de comparer deux atomes de même
  scope et même clé, mais **rien ne balaie le corpus** pour les trouver. Cette limite est
  aggravée par le maillon ⑦ : l'embedding rapproche les contraires au lieu de les
  opposer.

Ne comptez donc pas sur ARAC pour vous signaler que vous vous contredisez. Comptez sur
lui pour vous rendre les deux atomes, et arbitrez vous-même.

---

## ⑪ La mémoire — les règles qui décident de ce qui est vrai

**Entre** : les atomes et leurs liens.
**Sort** : un contexte petit, exact, récent, sourcé, borné.

Entre « avoir des atomes en base » et « se souvenir utilement », il y a un corps de règles.
Les invariants qui comptent :

- **Aucune décision active sans source.** Une vérité durable sans provenance ne peut pas
  être active.
- **Une décision remplacée n'est jamais supprimée**, elle devient `superseded`.
- **Une recherche courante exclut le remplacé**, sauf demande historique explicite.
- **Une source fragile ou tronquée ne devient pas une vérité active.**
- **Une incertitude reste une incertitude.** Une question, une idée, une suggestion ne se
  promeuvent pas silencieusement en fait établi.

Au-dessus, un routeur de contexte prépare ce qui est envoyé à un agent. Ses propriétés
sont déterministes — donc reproductibles, donc débogables :

- budgets de jetons stricts, séparés par nature (global, projet, mémoire) ;
- mémoire métier et mémoire de code **séparées** ;
- trois passes de recherche au maximum ;
- **provenance sur chaque élément injecté** ;
- exclusion automatique **et tracée** du bruit : remplacé, autre projet, doublon,
  journaux, fichiers de verrouillage, caches ;
- incertitudes et contradictions **listées explicitement** dans la sortie.

Le point le plus important est la trace des exclusions. Quand un souvenir n'apparaît pas
dans le contexte, vous pouvez savoir **pourquoi** il a été écarté. Un budget silencieux
est un cauchemar de diagnostic.

Ce routeur ne fait **aucun appel réseau et aucun appel de modèle** : il ordonne et
budgète, rien de plus.

---

## ⑫ Le cockpit — regarder sans toucher

**Entre** : la base, en lecture stricte.
**Sort** : des chiffres, chacun avec ses lignes.

Servi sur la boucle locale, atteignable par le tunnel. Authentification par mot de passe
**et** code à usage unique (TOTP standard). Les échecs sont journalisés.

Le cockpit repose sur deux invariants, détaillés dans
[`CONCEPTS.md`](CONCEPTS.md#5-la-preuve) :

1. **Aucune métrique sans sa preuve** — la contrainte est de type, pas de discipline : un
   objet métrique dont la requête de preuve est vide **refuse d'exister**.
2. **Le tableau de bord ne calcule pas.** Toute l'arithmétique, pourcentages compris, est
   faite par PostgreSQL. Un calcul fait dans le navigateur n'est pas rejouable dans un
   terminal, donc pas prouvable.

Le SQL du registre est **statique et littéral** : aucune interpolation, aucune entrée
utilisateur ne construit jamais de requête. La surface d'injection est nulle par
construction, pas par vigilance.

**Ce qui peut mal tourner.** Tous les chiffres à zéro alors que la base est peuplée : le
rôle en lecture n'a pas les droits sur le schéma — cas fréquent après une restauration.
**Où diagnostiquer.** [`EXPLOITATION.md`](EXPLOITATION.md) et
[`SAUVEGARDE.md`](SAUVEGARDE.md).

---

## ⑬ Claude Code — la boucle se referme

**Entre** : votre question, dans un outil.
**Sort** : une réponse qui tient compte de ce que vous savez déjà.

C'est le maillon qui justifie tous les autres — et c'est celui où il faut être le plus
précis sur ce qui est livré et ce qui ne l'est pas.

**Ce qui existe :** l'API expose le rappel et la construction de contexte. Elle est
atteignable depuis votre machine à travers le tunnel. Un agent, un script, ou vous-même
pouvez l'interroger et coller le résultat dans une session.

**Ce qui n'est pas livré dans ce dépôt :** un serveur MCP prêt à brancher sur Claude
Desktop ou Claude Code. La couche de règles injectée en début de session (« la
constitution ») est écrite et prévue pour cet usage, mais le connecteur lui-même n'est pas
là. Concrètement : **la dernière marche est à votre charge.**

C'est dit ici plutôt qu'en annexe parce que c'est exactement le genre de chose qu'on
découvre au mauvais moment.

### La constitution — pourquoi un texte plutôt que du code

Un court texte, lu au début de chaque session, énonce les règles non négociables
d'écriture en mémoire. Pourquoi un texte et pas des tests ?

Parce que **la plupart des façons de corrompre une mémoire ne sont pas des bugs**. Ce sont
des jugements : inventer un identifiant plausible, ranger un souvenir dans le mauvais
monde, effacer plutôt que remplacer. Aucun test ne les attrape. Un modèle qui a lu ces
règles au démarrage, si.

Ce texte est court **exprès** : il est relu à chaque session, donc chaque phrase ajoutée
est payée à chaque connexion, pour toujours. Une constitution de dix pages n'est pas dix
fois plus respectée — elle est lue en diagonale.

Son empreinte SHA-256 est servie par le point de santé et par le cockpit. C'est ce qui
permet de répondre, des mois plus tard, à « sous quelles règles cet atome a-t-il été
écrit ? » — l'empreinte change dès qu'un caractère change. Vous écrivez la vôtre en
déposant un fichier ; elle **remplace** le texte par défaut, elle ne s'y ajoute pas.

---

# Ce que cette architecture n'a pas

Récapitulé en un endroit, parce qu'un lecteur qui installe a le droit de savoir où sont
les trous.

| Manque | Conséquence concrète |
|---|---|
| **Le graphe est écrit mais jamais servi** | `atom_links` est recalculée à chaque cycle ; aucun chemin de rappel ne la lit. Votre rappel ne lui doit rien. |
| **Aucune détection de contradiction** | Deux atomes opposés cohabitent, sans alerte. À vous d'arbitrer. Le graphe dit « se ressemblent », jamais « s'opposent ». |
| **Le graphe n'est couvert par aucun test** | Aucun test du dépôt n'importe `app/services/atom_links.py` ni n'appelle ses fonctions — `grep -rn "import atom_links\|same_thread_pairs\|supersede_pairs\|mutual_knn_edges" tests/` ne rend rien. Une régression y passerait sans bruit. |
| **Pas de connecteur MCP livré** | La dernière marche vers Claude Code est à construire. |
| **Capture Claude Desktop non automatique** | Export manuel depuis l'application. |
| **Embedding = dépendance externe dure** | Panne du prestataire = ni écriture d'atome, ni rappel. |
| **98 % du savoir jamais audité** | Le cerveau est confiant sur ce qu'il n'a jamais vérifié. |
| **La fraîcheur est presque toujours inconnue** | `confirmed_until` est rarement renseigné ; l'ajustement de fraîcheur est donc neutre en pratique. |

---

# Pour aller plus loin

| Pour | Lire |
|---|---|
| Comprendre atome, scope, embedding, rappel, preuve | [`CONCEPTS.md`](CONCEPTS.md) |
| Installer et exploiter le pont Mac ↔ serveur | [`PONT-MAC.md`](PONT-MAC.md) |
| Surveiller, diagnostiquer, réparer | [`EXPLOITATION.md`](EXPLOITATION.md) |
| Sauvegarder, et prouver qu'on peut restaurer | [`SAUVEGARDE.md`](SAUVEGARDE.md) |
| Le vocabulaire | [`GLOSSAIRE.md`](GLOSSAIRE.md) |
| Pourquoi ARAC augmente Claude au lieu de le remplacer | [`PHILOSOPHIE.md`](PHILOSOPHIE.md) |
