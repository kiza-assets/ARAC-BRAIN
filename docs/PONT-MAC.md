# Le pont — comment vos conversations arrivent dans votre cerveau

> Sans ce maillon, le cerveau ne reçoit rien. C'est aussi celui qu'on
> comprend le moins spontanément, et celui qui casse le plus souvent. Ce
> document existe pour qu'il ne reste rien d'obscur entre le moment où vous
> parlez à Claude et le moment où votre cerveau s'en souvient.

---

## À lire avant de commencer

**Ce qu'il vous faut.** Une machine où vous parlez à Claude (un Mac, mais pas
seulement — voir *Pas de Mac*), un serveur avec un cerveau déjà installé
(`bootstrap/bootstrap.sh`), un accès SSH par clé à ce serveur. Rien d'autre :
le pont est écrit en Python de la bibliothèque standard et en bash 3.2, il
n'installe aucune dépendance.

**Ce que ça coûte.** Le transport ne coûte rien, et **l'ingestion non plus** :
un message qui arrive est écrit tel quel, en texte, sans qu'aucun vecteur soit
calculé. Ce qui coûte, c'est ce qui arrive ensuite, au cycle de digestion — un
modèle de curation **lit** la tranche non digérée, et c'est là que part
l'essentiel de l'argent. L'embedding, lui, ne vient qu'**après** la curation et
ne porte que sur les **atomes** retenus : un atome = un appel d'embedding, pas
un message = un appel. C'est pourquoi la ligne « embeddings » de votre facture
restera petite et la ligne « curation » ne le sera pas. Ordre de grandeur mesuré
sur le cerveau de référence : **~87 000 jetons par cycle, ~31 500 jetons par
atome produit**. Remonter dix ans d'archives d'un coup se voit sur une facture —
non pas parce que dix ans de messages deviennent dix ans de vecteurs, mais parce
que le curateur devra **tout lire**. Le pont vous laisse d'ailleurs plafonner le
débit (`ARAC_MAX_CONVERSATIONS`) exactement pour cette raison.

**Ce qui ne marche pas, et ne marchera pas.** Il n'existe **aucune voie
automatique** pour capter ce que vous dites à l'application Claude Desktop.
Aucune. Ce document explique pourquoi, et ce qu'on fait à la place. Si vous
attendiez « ça marche tout seul », lisez d'abord la section *Où sont les
conversations*.

**Ce qui n'a pas été vérifié.** Ce pont a été écrit et testé sur Linux,
contre un serveur d'ingestion simulé. Personne n'a pu l'exécuter sur un vrai
Mac ni contre un vrai serveur avant sa publication. La section *Ce qui reste
à vérifier* dit exactement ce qui est prouvé et ce qui ne l'est pas, et la
*Liste de contrôle* vous fait faire cette vérification en dix minutes.

### Ce que `<cerveau>` veut dire — et comment on le nomme

`<cerveau>` revient à chaque chemin de ce document, et ce n'est pas un
ornement : **un poste peut piloter plusieurs cerveaux, et chacun a son foyer.**

```
~/.arac/<cerveau>/pont.conf          la configuration
~/.arac/<cerveau>/jeton_ingest       le jeton, en 0600
~/.arac/<cerveau>/etat-pont.json     le CURSEUR de synchronisation
~/.arac/<cerveau>/journal/           le journal
```

Le cloisonnement est ce qui protège le curseur : partagé, le pont du second
cerveau marquerait « déjà envoyées » des conversations que le premier n'a
jamais reçues, et elles ne repartiraient plus jamais. C'est la seule perte
silencieuse et définitive du système.

**Et donc, dès qu'il y en a deux, il faut dire lequel.** Le pont refuse de
deviner — deviner, ici, c'est choisir dans quelle mémoire déposer des
conversations privées :

```bash
# arac-sync.py : le drapeau OU la variable OU un fichier nommé
python3 ~/.arac/<cerveau>/arac-sync.py --cerveau <cerveau> --tout
ARAC_CERVEAU=<cerveau> python3 ~/.arac/<cerveau>/arac-sync.py --tout
python3 ~/.arac/<cerveau>/arac-sync.py --conf ~/.arac/<cerveau>/pont.conf

# arac-pont.sh : la variable seulement — il n'a pas de --cerveau
ARAC_CERVEAU=<cerveau> ./arac-pont.sh etat
```

Tant que vous n'avez **qu'un** cerveau configuré, vous pouvez tout omettre :
le repli « l'unique » s'en charge. C'est pour cela que le reste de ce document
écrit les commandes sans le sélecteur — et pour cela qu'il faut le connaître
avant d'installer le second. Le symptôme, le message exact et le cas de
l'automatisation launchd sont au
[§ 6 bis de `DEPANNAGE.md`](DEPANNAGE.md#6-bis-le-pont-refuse--ce-poste-pilote-plusieurs-cerveaux).

---

## 1. La chaîne, de bout en bout

```
   VOUS
    │  vous parlez à Claude — en ligne de commande, ou dans l'application
    ▼
 ┌─────────────────────────────── VOTRE MACHINE ────────────────────────────┐
 │                                                                          │
 │   Claude Code (CLI)                    Claude Desktop / claude.ai        │
 │        │                                        │                        │
 │        │ écrit en direct                        │ ne garde rien de       │
 │        ▼                                        │ lisible en local       │
 │   ~/.claude/projects/<projet>/<session>.jsonl   ▼                        │
 │        │                                 export officiel (manuel)        │
 │        │                                        │                        │
 │        │                                        ▼                        │
 │        │                    ~/.arac/<cerveau>/export-desktop/             │
 │        │                              conversations.json                 │
 │        │                                        │                        │
 │        └────────────────┬───────────────────────┘                        │
 │                         ▼                                                │
 │              arac-sync.py  (toutes les heures, via launchd)              │
 │                 · quoi est nouveau depuis la dernière fois ?             │
 │                 · extraire le texte, jeter le câblage d'outils           │
 │                 · masquer ce qui ressemble à un secret                   │
 │                 · découper en lots, compresser                           │
 │                         │                                                │
 │                         ▼                                                │
 │         127.0.0.1:$ARAC_PORT_API  ← entrée du tunnel, sur VOTRE machine  │
 └─────────────────────────┼────────────────────────────────────────────────┘
                           │  SSH, chiffré, sortant, clé bridée
                           │  (autossh le rouvre après veille et coupure)
 ┌─────────────────────────┼──────────────────── VOTRE SERVEUR ─────────────┐
 │                         ▼                                                │
 │         127.0.0.1:$ARAC_PORT_API  API — n'écoute QUE la boucle locale    │
 │                         │                                                │
 │                         ▼                                                │
 │              POST /v1/ingest/messages                                    │
 │                 · le jeton est-il présenté ?    sinon → 401, rien n'entre │
 │                 · ce poste est-il déclaré ?     sinon → 403, rien n'entre │
 │                 · ce message existe-t-il déjà ? oui   → compté « doublon »│
 │                 · écriture du BRUT en base                               │
 │                 · réponse : reçus / insérés / doublons  ← l'acquittement  │
 │                         │                                                │
 │                         ▼                                                │
 │              le brut reste du TEXTE — aucun vecteur ici, aucun coût      │
 │                         │                                                │
 │                         ▼                                                │
 │              cycle de digestion  (04:00 · 13:00 · 21:00 par défaut)      │
 │                 la tranche non digérée est choisie par curseur et date   │
 │                 la curation la LIT, décide, propose                      │
 │                         │                                                │
 │                         ▼                                                │
 │              atomes — une affirmation, un domaine, une provenance        │
 │                         │                                                │
 │                         ▼                                                │
 │              embeddings — c'est L'ATOME qui devient 3072 nombres         │
 │                         │                                                │
 │                         ▼                                                │
 │              voisinage sémantique → mémoire                              │
 │                 proximité des vecteurs + domaine partagé.                │
 │                 PAS un graphe de liens raisonnés : rien ne détecte       │
 │                 une contradiction.                                       │
 │                         │                                                │
 │              ┌──────────┴──────────┐                                     │
 │              ▼                     ▼                                     │
 │   cockpit ($ARAC_PORT_COCKPIT)   rappel pour Claude Code                 │
 │        lecture seule         au moment où vous codez                     │
 └──────────────────────────────────────────────────────────────────────────┘
```

Quatre choses à retenir de ce dessin :

1. **Le tunnel n'est pas un détail de sécurité, c'est le seul chemin.** L'API
   n'écoute que sur `127.0.0.1` côté serveur. Sans tunnel, il n'y a
   littéralement pas d'adresse où envoyer.
2. **Envoyer n'est pas se souvenir.** Ce qui arrive est du *brut*. Il devient
   de la mémoire au cycle suivant, pas avant. Entre deux cycles, un cerveau
   qui ne répond rien de neuf est un cerveau normal.
3. **On lit d'abord, on vectorise ensuite.** L'ordre du dessin est
   contre-intuitif et c'est voulu : beaucoup d'outils voisins vectorisent tout
   ce qui entre puis cherchent dedans. Ici, la vectorisation vient **après** la
   curation et ne porte que sur ce qui a été retenu. Un message que le curateur
   n'a pas jugé porteur reste en base — daté, attribué, consultable — mais **la
   recherche par le sens ne le verra pas**. C'est un arbitrage assumé : moins
   de bruit dans le rappel, au prix de ce que le curateur a laissé passer.
4. **Le serveur répond en chiffres, pas en promesses.** Un `200 OK` ne suffit
   pas : le pont compare ce qu'il a envoyé à ce que le serveur dit avoir reçu.
   Voir *L'acquittement*.

---

## 2. Où sont les conversations — et pourquoi c'est la partie fragile

### `~/.claude/projects/` — Claude Code (CLI)

**C'est la source solide.** Un fichier `.jsonl` par session, un objet JSON par
ligne, écrit en direct au fil de la conversation, jamais réécrit en arrière.
Chaque ligne porte `sessionId`, `uuid`, `parentUuid`, `timestamp`, `type`
(`user`/`assistant`) et `message.content`.

**Sa fragilité, dite honnêtement :** cette structure est *observée*, pas
garantie par un contrat public. Une mise à jour du CLI peut la changer sans
prévenir. Le pont est donc écrit en lecteur tolérant — une ligne
incompréhensible est **comptée** puis ignorée, jamais fatale — et il vous
signale le compteur dans son rapport :

```
  ! 412 ligne(s) de journal illisible(s) ont été ignorées.
```

Quelques-unes : normal. Des centaines d'un coup, alors qu'il n'y en avait
aucune : **le format a bougé**. C'est votre alarme. Lancez
`arac-sync.py --inventaire` et regardez ce qui a changé.

### L'application Claude Desktop — l'export officiel, et rien d'autre

**L'application ne stocke pas vos conversations dans un fichier lisible.**
Elles vivent sur les serveurs d'Anthropic ; l'application n'en garde qu'un
cache, dans `~/Library/Application Support/Claude/` : une base LevelDB /
IndexedDB d'application Electron. Binaire, non documentée, réécrite à chaque
mise à jour, et **ouverte en écriture tant que l'application tourne** — la
lire pendant ce temps est une bonne façon de la corrompre.

**Ce framework n'y touche pas, et vous conseille de ne pas y toucher.**

La seule voie stable est l'**export officiel** :

> claude.ai → Paramètres → Confidentialité → **Exporter les données**
> → vous recevez un lien par courriel → dézippez → déposez
> `conversations.json` dans `~/.arac/<cerveau>/export-desktop/`

C'est un **instantané**, pas un flux : il faut le redemander pour rattraper
la suite. Ce n'est pas confortable. C'est honnête, et ça ne casse pas.

Le format, lui, est stable et riche : une liste de conversations, chacune
avec `uuid`, `name`, `created_at`, `updated_at`, et `chat_messages[]` où
chaque message porte `uuid`, `parent_message_uuid`, `sender`, `created_at`,
`content[]`, `attachments[]` et `files[]`. Le pont conserve les uuid — c'est
ce qui permet à la déduplication de fonctionner et à la provenance de tenir.

### La troisième voie, celle qui n'existe pas encore

Un connecteur officiel, ou une extension MCP locale, rendrait la capture
automatique. Le jour où cela existera, il se branchera ici sans rien changer
au reste : dans `arac-sync.py`, une source est un objet à **deux méthodes**
(`inventaire()` et `messages()`). Le tunnel, l'ingestion, les cycles, la
mémoire et le cockpit ignorent jusqu'à son existence.

D'ici là, méfiez-vous de tout ce qui promet la capture automatique en passant
par un cookie de session ou une API web non documentée : cela fonctionne
jusqu'au jour où cela s'arrête, sans prévenir, et souvent sans bruit — le
pire mode de panne pour une mémoire.

---

## 3. Ce qui part, ce qui ne part pas

**Part :** pour chaque message, un identifiant, l'identifiant du parent, le
rôle, le **texte**, l'horodatage. Plus le titre de la conversation quand la
source en donne un.

**Ne part jamais :**

* les blocs d'outillage sans texte (`tool_use`, `tool_result`, `thinking`) —
  le cerveau apprend de ce qui a été *dit*, pas du câblage interne ;
* les fichiers de votre disque — jamais lus, jamais transmis ;
* ce qui ressemble à un secret : clés d'API, jetons, mots de passe, clés
  privées, JWT, URL de connexion à une base. Remplacés **avant l'envoi** par
  un marqueur nommé, `[REDACTED:cle-api]`.

Ce filtre est un **filet, pas une garantie** : il attrape les formes connues.
La bonne habitude reste de ne pas coller de secrets dans une conversation.

Les pièces jointes deviennent des marqueurs nommés : le contenu extrait par
claude.ai est conservé, un fichier sans contenu extrait laisse
`[ARAC fichier joint sans contenu extrait: <uuid>]`. Jamais un trou muet :
plus tard, quand un souvenir vous paraîtra incomplet, ce marqueur vous dira
pourquoi.

### La règle qui vous montre ce qui part

**Au premier lancement, le pont refuse d'envoyer quoi que ce soit.** Il liste
ce qu'il a trouvé — combien de conversations, lesquelles, depuis quand — et
vous rend la main. Ces fichiers contiennent une vie ; vous devez voir ce qui
part avant que ça parte.

```
  CE QUI VA PARTIR DE CETTE MACHINE
  ────────────────────────────────────────────────────────────────────

  47 conversation(s), 8 214 message(s) au total.

   messages  dernière activité   source        conversation
   ──────────────────────────────────────────────────────────────────
        312  2026-08-05 18:22    claude_code   mon-projet
        188  2026-08-04 09:10    desktop_chat  Préparer la réunion de jeudi
   …
```

`arac-pont.sh automatiser` **refuse** de confier le pont à launchd tant que
cette première synchronisation n'a pas eu lieu. Automatiser avant d'avoir
regardé, ce serait envoyer une vie sans l'avoir vue passer.

---

## 4. L'installation, dans l'ordre

Les cinq gestes. Chacun est réversible, aucun ne demande `sudo` sur votre
machine.

```bash
cd <votre-copie-du-depot>/mac

./arac-pont.sh installer          # 1. ~/.arac, la configuration, les questions
./arac-pont.sh cle-ssh            # 2. la clé du tunnel + la ligne à poser
                                  #    sur le serveur (voir deploy/ssh/)
                                  # 3. le jeton (ci-dessous)
./arac-pont.sh premiere-synchro   # 4. le trajet complet, raconté
./arac-pont.sh automatiser        # 5. launchd prend le relais
```

**Le jeton (geste 3).** Il se lit sur le serveur, en root, et se dépose sur
votre machine :

```bash
# sur le serveur
sudo grep '^ARAC_API_BEARER_TOKEN=' /etc/arac/<votre-base>/arac.env

# sur votre machine
umask 077 && cat > ~/.arac/<cerveau>/jeton_ingest      # collez, puis Ctrl-D
chmod 600 ~/.arac/<cerveau>/jeton_ingest
```

Le pont **refuse d'envoyer** si ce fichier est lisible par d'autres comptes : « *Le jeton
… est lisible par d'autres comptes de cette machine* », code **2**, avant toute connexion.
`--inventaire` et `--annonce`, eux, continuent de fonctionner — ils ne transmettent rien,
et c'est justement avec eux qu'on diagnostique avant de corriger.

**L'identifiant de poste.** C'est la valeur la plus importante de toute la
configuration. Elle doit être **exactement** celle de `source.node_id` dans le
`config/brain.toml` de votre serveur. Recopiez-la, ne la retapez pas.

Se tromper ici a un symptôme net et un seul : l'API répond **403**, rien
n'entre, et le cerveau reste vide. C'est un problème d'*ingestion*, visible
immédiatement dans la réponse du pont — à ne pas confondre avec le problème
de quarantaine décrit ci-dessous, qui survient bien plus tard dans la chaîne
et pour une raison entièrement différente.

> **Une leçon, mesurée — et elle ne parle pas de ce poste-ci.** Sur le cerveau
> de référence, **36 % des cycles de digestion se sont terminés sans produire
> un seul atome**. La cause n'était **pas** le volume de la tranche, et pas non
> plus l'identifiant de poste ci-dessus : c'était un désaccord d'identifiants
> **entre le paquet de messages servi au modèle de curation et la réponse qu'il
> a rendue**. Le modèle citait, comme preuve d'un atome, des identifiants de
> messages qui n'étaient pas dans le paquet qu'on lui avait donné. Le contrat
> de sortie refuse alors **le cycle entier** plutôt que d'écrire un souvenir
> dont la provenance est fausse : mieux vaut ne rien retenir que retenir une
> chose qu'on ne saura pas prouver. Ce que cela vous apprend, le jour où ça
> vous arrive : **réduire la tranche ne soignera rien.** On lit le corps mis en
> quarantaine, conservé en base exactement pour ça.

---

## 5. Le tunnel

### Pourquoi un tunnel, et pas une adresse publique

Le cockpit est en **lecture seule**, et c'est exactement ce qui trompe.
Lecture seule ne veut pas dire sans conséquence : le cockpit donne à voir
tout ce que votre cerveau a appris de vous. Vos projets, vos proches, vos
décisions, vos échecs, vos habitudes — datés, classés, interrogeables.
Personne ne pourrait rien y modifier ; n'importe qui pourrait tout y lire.

Publier cela derrière un mot de passe, c'est parier que ce mot de passe, ce
certificat, cette version de serveur web et **toutes celles à venir**
tiendront aussi longtemps que vos souvenirs comptent. Votre mémoire dure des
décennies. Une pile logicielle, non.

Le tunnel ne fait pas ce pari. Il n'y a pas de port à attaquer, pas de page
de connexion à deviner. Il y a une clé, et cette clé n'ouvre que deux ports,
en boucle locale, sur un compte sans shell.

**Le prix, dit franchement :** pas de cockpit depuis un téléphone sans ouvrir
d'abord un tunnel. Pas d'accès depuis une machine où vous ne pouvez pas
installer votre clé. C'est le prix, et il est bas.

### Pourquoi `autossh` et pas `ssh` seul

`KeepAlive` de launchd relance un processus **mort**. Or le problème d'un
tunnel n'est pas la mort : c'est le **coma**. Après une mise en veille du Mac
ou un changement de réseau, la session TCP survit côté client alors que plus
rien ne passe. Le processus vit, launchd ne relance rien, et le pont se tait
en silence — le pire mode de panne possible.

`autossh` sonde en permanence et reconstruit la session quand elle ne répond
plus. `brew install autossh`. Le pont fonctionne sans lui, mais vous devrez
relancer le tunnel à la main après chaque veille.

### Côté serveur

Voir `deploy/ssh/README.md`. Deux points qui sauvent des soirées :

* la clé est **bridée** dans `authorized_keys` (`restrict`, `permitopen` sur
  deux ports) : même volée, elle n'ouvre rien d'autre ;
* `ClientAliveInterval 30` libère les sessions mortes qui, sinon, gardent les
  ports occupés et empêchent la reconnexion **par vous-même**.

---

## 6. L'acquittement — pourquoi un `200 OK` ne suffit pas

À chaque lot envoyé, le serveur répond en chiffres :

```json
{"received": 312, "inserted": 40, "duplicates": 272, "msg_count": 312}
```

Le pont vérifie **deux égalités** avant de considérer le lot passé :

* `received` == ce qu'il a envoyé — rien n'a été perdu en route ;
* `received` == `inserted + duplicates` — rien n'a disparu à l'écriture.

Tout le reste — corps vide, tronqué par un proxy, JSON invalide, compteurs
absents — est un **échec**. Le curseur n'avance pas, la conversation repartira
au prochain passage.

C'est délibéré. Renvoyer un lot déjà connu ne coûte qu'un peu de réseau : le
serveur le comptera « doublon » et n'écrira rien. Un trou invisible dans une
mémoire, lui, ne se répare jamais — parce que personne ne sait qu'il existe.

**`duplicates` élevé n'est pas une anomalie.** C'est le fonctionnement normal
d'une conversation qui s'allonge : le pont renvoie parfois un peu plus que le
strict nécessaire, le serveur trie.

---

## 7. Idempotence et reprise

L'état local (`~/.arac/<cerveau>/etat-pont.json`) retient, par conversation, **combien
de messages le serveur a acquittés** et l'empreinte de ce préfixe. Il est
réécrit après **chaque lot**, de façon atomique.

Conséquences pratiques :

* le Mac s'endort au milieu d'une conversation de 4 000 messages → la reprise
  repart au message acquitté suivant, pas au premier ;
* une conversation a été réécrite en arrière (préfixe différent) → le pont la
  renvoie **entièrement**, sans qu'on lui demande ;
* vous supprimez l'état → tout repart, le serveur déduplique, rien n'est
  perdu ni dupliqué. **C'est le geste de dernier recours, et il est sûr.**

`arac-sync.py --tout` fait la même chose sans rien supprimer : il ignore
l'état et renvoie tout l'historique. C'est le filet de rattrapage quand vous
soupçonnez un trou.

---

## 8. La provenance — la leçon la plus chère

> Sur le cerveau de référence, **76 % de la provenance a été perdue**. Un
> changement de format dans la référence de source a coupé le lien entre un
> atome et la conversation qui l'avait produit. Le savoir est resté ; plus
> personne ne pouvait dire d'où il venait.

D'où une règle appliquée ici sans exception : **`conversation_uid` est
l'identifiant natif de la source** — le `sessionId` de Claude Code, l'`uuid`
de l'export. Jamais un identifiant recalculé, jamais un chemin de fichier.
Un chemin déménage ; un uuid, non.

**Ne changez pas cette règle après la première synchronisation.** Vous
couperiez le fil entre ce que votre cerveau sait et l'endroit où il l'a
appris — et vous ne vous en apercevriez que des mois plus tard.

---

## 9. Les pannes courantes, et leur diagnostic

Commencez **toujours** par :

```bash
mac/arac-pont.sh etat
```

Il déroule la chaîne maillon par maillon et s'arrête au premier `×`. Le
premier maillon cassé explique tous les suivants.

---

### « Rien n'arrive, et le pont dit que tout va bien »

**Symptôme.** Code de sortie 0, « Rien de nouveau », mais le cockpit ne
bouge pas.

**Cause la plus fréquente.** Rien n'est cassé : le brut est arrivé, mais le
**cycle de digestion** n'a pas encore tourné. Trois cycles par jour, pas de
digestion continue.

```bash
# sur le serveur
sudo systemctl start <prefixe>-cycle.service
journalctl -u <prefixe>-cycle.service -f
```

**Autre cause.** L'état local croit que tout est envoyé alors que le serveur
n'a rien. Tranchez en une commande : `arac-sync.py --tout`. S'il renvoie tout
et que le compteur `inserted` est élevé, l'état mentait.

---

### `HTTP 403` — le serveur refuse ce poste

**Deux causes, dans cet ordre de fréquence :**

1. `ARAC_NODE_ID` ne correspond pas à `source.node_id` du serveur — un espace,
   une majuscule, un tiret suffisent ;
2. le poste n'est pas dans `ARAC_INGEST_ALLOWED_NODES` côté serveur.

> **Ne cherchez pas ici un problème de jeton.** La règle qui évite de se
> tromper de page : **jeton absent ou inconnu → `401`** ; **jeton valide mais
> poste non déclaré → `403`**. Un jeton oublié après une rotation donne donc un
> `401`, pas un `403` — voir la section suivante.

```bash
# machine source
grep ARAC_NODE_ID ~/.arac/<cerveau>/pont.conf
# serveur
grep node_id ~/arac/config/brain.toml
sudo grep ARAC_INGEST_ALLOWED_NODES /etc/arac/<base>/arac.env
```

Ces valeurs doivent être **identiques au caractère près**.

---

### `HTTP 401` — pas de jeton, ou pas le bon

**C'est la panne n°1 du pont depuis que le jeton est exigé partout.** Le jeton
est demandé à **toute** requête, tunnel compris — seul `/healthz` est public.
Un `401` ne dit donc **rien** de l'endroit d'où vous appelez : il dit que le
jeton présenté est absent ou inconnu.

**Commencez par lire le corps de la réponse.** Il est écrit pour ce
moment-là : il porte `pourquoi` (la raison exacte du refus), `ou_est_le_jeton`
(le chemin du coffre sur le serveur) et `geste` (quoi faire).

Trois causes, dans cet ordre de fréquence :

1. **`ARAC_TOKEN_FILE` n'est pas renseigné dans `pont.conf`, ou le fichier
   qu'il désigne n'existe pas / n'est pas lisible.** C'est le cas le plus
   fréquent, et il n'y a aucun reverse proxy dans l'histoire — un simple
   tunnel SSH suffit à le produire ;
2. **un saut de ligne parasite** dans le fichier de jeton ;
3. **une rotation côté serveur non répercutée** : `ARAC_NODE_TOKEN_<NODE_ID>`
   a changé dans `/etc/arac/<base>/arac.env` et le fichier local porte encore
   l'ancienne valeur.

```bash
grep ARAC_TOKEN_FILE ~/.arac/<cerveau>/pont.conf   # (1) la ligne existe-t-elle ?
ls -l ~/.arac/<cerveau>/jeton_ingest               # (1) le fichier est-il là, en 0600 ?
wc -c ~/.arac/<cerveau>/jeton_ingest               # (2) une seule ligne, pas de blanc final
```

Pour (3), le geste est celui du §« Poser le jeton » : recopiez la valeur de
`ARAC_NODE_TOKEN_<NODE_ID>` depuis le coffre du serveur.

**Le cas du reverse proxy existe, mais il est rare** : si vous en avez placé
un devant l'API — ce que ce dépôt n'installe pas —, ses en-têtes
(`X-Forwarded-For`, `X-Real-IP`, `Forwarded`) font que le pair TCP vu par
l'API est le proxy, et non plus vous. Cela ne change rien au verdict : le
jeton était déjà exigé.

> **Et si vous aviez posé `ARAC_API_TRUST_LOOPBACK=1` côté serveur ?** Il ne
> desserre rien tout seul : le motif écrit
> (`ARAC_API_TRUST_LOOPBACK_RAISON`) est obligatoire, et le corps du `401` le
> dit. Voir [`CONFIGURATION.md` §6](CONFIGURATION.md).

---

### « serveur injoignable » — le tunnel

C'est presque toujours le tunnel. Dans l'ordre :

```bash
mac/arac-pont.sh tunnel etat                     # les ports sont-ils là ?
lsof -nP -iTCP:"$ARAC_PORT_API" -sTCP:LISTEN     # qui les tient ?
mac/arac-pont.sh tunnel ouvrir                   # au premier plan, pour VOIR l'erreur
```

| Message | Ce qu'il veut dire |
|---|---|
| `Permission denied (publickey)` | la clé n'est pas dans `authorized_keys` du serveur, ou le fichier y est trop ouvert (il faut 600, et 700 sur `~/.ssh`) |
| `administratively prohibited: open failed` | `permitopen` fait son travail : vous demandez un port non autorisé |
| `bind: Address already in use` | un ancien tunnel occupe encore le port **sur votre machine** — `lsof` puis `kill` |
| `remote port forwarding failed` | une session morte occupe le port **sur le serveur** — voir ci-dessous |
| silence, puis rien | le tunnel est en coma : installez `autossh` |

**Le port occupé par un fantôme.** Votre Mac s'endort, sa session TCP se tait
sans se fermer, le serveur la croit vivante et garde les redirections. Au
réveil, la reconnexion échoue parce que les ports sont pris — par vous-même,
en plus jeune. La correction est côté serveur, dans
`deploy/ssh/99-arac-pont.conf` : `ClientAliveInterval 30` et
`ClientAliveCountMax 3`. Sans ces deux lignes, il faut tuer le processus à la
main après chaque veille.

---

### `HTTP 400` — le serveur a refusé le contenu

Un lot dépasse un plafond du serveur (2 000 messages, 512 Ko par message,
10 Mo par lot). Le pont découpe et tronque bien en dessous ; si vous voyez ce
code, c'est que les plafonds du serveur ont changé. La conversation restera
bloquée tant que ce n'est pas résolu — c'est le seul cas où un blocage est
durable, et c'est pourquoi les marges sont larges.

---

### « des centaines de lignes illisibles d'un coup »

Le format de `.jsonl` de Claude Code a probablement changé. Vérifiez :

```bash
arac-sync.py --inventaire
ls -lt ~/.claude/projects/*/*.jsonl | head -3
tail -1 <le-fichier-le-plus-récent> | python3 -m json.tool
```

Si la structure a bougé, ce sont `SourceClaudeCode._role` et
`SourceClaudeCode._contenu` qu'il faut adapter — deux fonctions courtes,
volontairement isolées pour ce jour-là.

---

### launchd ne lance rien

```bash
CERVEAU=<votre_base>
launchctl list | grep "com.arac.$CERVEAU"
plutil -lint "$HOME/Library/LaunchAgents/com.arac.$CERVEAU.pont.sync.plist"
tail -f "$HOME/Library/Logs/arac-pont-$CERVEAU-sync.log"
launchctl kickstart -k "gui/$(id -u)/com.arac.$CERVEAU.pont.sync"    # forcer une passe
```

Deux pièges classiques :

* **`RunAtLoad` est à `false` pour la synchronisation, volontairement.**
  Recharger l'agent ne déclenche donc pas d'envoi. Ce n'est pas une panne :
  c'est pour qu'un rechargement ne fasse jamais partir vos conversations par
  surprise. Utilisez `kickstart` pour forcer.
* **Sous launchd, l'environnement est minimal** — ni votre `PATH`, ni ce que
  votre `.zshrc` exporte. Un `python3` installé par pyenv ou Homebrew se
  résout depuis un terminal et pas depuis launchd. C'est pourquoi le gabarit
  utilise un chemin **absolu**.

---

### Le journal, quand rien de tout cela ne suffit

```bash
tail -f ~/.arac/<cerveau>/journal/arac-pont.log
jq -c 'select(.evenement=="fin")'            ~/.arac/<cerveau>/journal/arac-pont.log
jq -c 'select(.evenement|test("erreur|echec"))' ~/.arac/<cerveau>/journal/arac-pont.log
```

Une ligne JSON par événement. Le jeton n'y figure jamais.

---

## 10. Pas de Mac ?

Le cerveau ne sait pas d'où viennent ses conversations : il sait de quel
**poste**. Rien dans l'architecture n'exige macOS.

**Ce qui marche exactement pareil, sur n'importe quel Linux :**

* Claude Code (CLI) écrit dans `~/.claude/projects/` de façon identique ;
* `arac-sync.py` est du Python de la bibliothèque standard : il tourne tel
  quel ;
* l'export officiel de claude.ai se dépose et s'ingère de la même façon ;
* si le script tourne **sur le serveur lui-même**, le tunnel devient inutile
  (source et destination partagent la boucle locale) — il reste à dire **vers
  quel cerveau** envoyer, et cela ne se devine pas : le port de l'API est
  *attribué* à l'installation, pas fixé. Lisez-le sur le serveur, puis posez-le
  dans `~/.arac/<cerveau>/pont.conf` :

  ```bash
  sudo grep '^ARAC_API_PORT=' /etc/arac/<votre-base>/arac.env
  #   → ARAC_API_PORT=<le numéro de VOTRE cerveau>

  # puis, dans ~/.arac/<cerveau>/pont.conf :
  ARAC_PORT_API=<ce numéro>
  # `arac-sync.py` en dérive ARAC_INGEST_URL=http://127.0.0.1:<ce numéro>/v1/ingest/messages
  ```

  **Il n'y a volontairement aucun défaut**, et surtout pas `8000`. Un défaut
  plausible est ce qu'il y a de plus dangereux ici : sur une machine qui porte
  deux cerveaux, il désigne le premier installé, et vos conversations privées
  partent dans la mémoire du voisin — avec un jeton valide et un HTTP 200. Un
  `200` ne prouve rien tant qu'on ne sait pas **qui** répond ;
* l'ordonnancement se fait par systemd :
  `deploy/systemd/arac-pont-sans-mac.{service,timer}.modele`.

**Ce qui ne marche pas :** `arac-pont.sh` s'appuie sur `launchctl`, `plutil`
et les notifications macOS pour `installer` et `automatiser`. Sur Linux,
utilisez directement `arac-sync.py` et les gabarits systemd. Les commandes
`etat` et `premiere-synchro` fonctionnent quand même, en dégradé (les
vérifications launchd sont simplement fausses).

**Ce que personne n'a :** la capture automatique de Claude Desktop. Elle
n'existe pas plus sur un Mac que sur un PC. Sur les deux, la voie est
l'export officiel.

En clair : **sans Mac, vous perdez le confort, pas les capacités.**

---

## 11. Liste de contrôle — à exécuter sur votre machine

Personne n'a pu exécuter ce pont sur un vrai Mac avant sa publication.
Ces quinze commandes font cette vérification. Comptez dix minutes. Notez ce
qui diverge : c'est exactement ce qu'un rapport de bogue utile contient.

### A. Avant de rien installer

```bash
# 1. python3 doit exister (Command Line Tools ; sinon : xcode-select --install)
python3 -V

# 2. les gabarits launchd doivent être valides — c'est plutil qui tranche
plutil -lint mac/com.arac.pont.sync.plist.modele
plutil -lint mac/com.arac.pont.tunnel.plist.modele
#    ATTENDU : « OK ». Les marqueurs @@…@@ sont des chaînes valides.

# 3. la syntaxe des scripts
bash -n mac/arac-pont.sh
python3 -m py_compile mac/arac-sync.py

# 4. où sont VOS conversations — métadonnées seulement, aucun envoi
python3 mac/arac-sync.py --inventaire
#    ATTENDU : ~/.claude/projects listé avec des .jsonl si vous utilisez le CLI.
#    NOTEZ le chemin réel de ~/Library/Application Support/Claude et sa taille :
#    c'est la donnée que ce document n'a pas pu vérifier.
```

### B. Après `installer` et `cle-ssh`

```bash
# 0. les deux numéros de VOTRE cerveau — sans défaut, et c'est voulu :
#    un numéro plausible vous brancherait sur le cerveau du voisin.
CERVEAU=<votre_base>
. "$HOME/.arac/$CERVEAU/pont.conf"      # pose ARAC_PORT_API et ARAC_PORT_COCKPIT

# 5. la clé ne doit ouvrir QUE le tunnel
ssh <votre-hôte> echo bonjour          # ATTENDU : ÉCHEC
ssh -N -L 5432:127.0.0.1:5432 <hôte>   # ATTENDU : « administratively prohibited »

# 6. le tunnel, lui, doit s'ouvrir
mac/arac-pont.sh tunnel ouvrir         # ATTENDU : silence (Ctrl-C pour sortir)

# 7. dans un autre terminal : les ports sont-ils là ?
lsof -nP -iTCP:"$ARAC_PORT_API" -sTCP:LISTEN
curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:$ARAC_PORT_COCKPIT/"
#    ATTENDU : une réponse HTTP du cockpit (souvent 200 ou 401/302)
```

### C. La première synchronisation

```bash
# 8. l'annonce ne doit RIEN envoyer
python3 ~/.arac/<cerveau>/arac-sync.py --annonce ; echo "code=$?"
#    ATTENDU : code=10, la liste de vos conversations, aucun envoi.

# 9. le trajet complet, raconté
mac/arac-pont.sh premiere-synchro
#    ATTENDU : inventaire → tunnel ✓ → annonce → votre accord → rapport chiffré.

# 10. deuxième passage : rien ne doit repartir
python3 ~/.arac/<cerveau>/arac-sync.py ; echo "code=$?"
#    ATTENDU : code=0 et « Rien de nouveau ». Si des messages repartent,
#    l'état ne se sauve pas — vérifiez les droits de ~/.arac/<cerveau>/.

# 11. le rappel de sécurité
grep -c REDACTED ~/.arac/<cerveau>/journal/arac-pont.log   # 0 est normal : le journal
                                                 # ne contient pas de contenu
ls -l ~/.arac/<cerveau>/jeton_ingest                       # ATTENDU : -rw-------
```

### D. L'automatisation

```bash
# 12. les agents doivent se charger
mac/arac-pont.sh automatiser
launchctl list | grep "com.arac.$CERVEAU"
#    ATTENDU : deux lignes. La colonne de gauche est le PID (tunnel) ou « - ».
#    Les étiquettes portent le nom du cerveau : sans cela, le second
#    « launchctl bootstrap » d'un même Mac remplacerait l'agent du premier,
#    dont la synchronisation cesserait sans une ligne d'erreur.

# 13. forcer une passe, sans attendre l'heure
launchctl kickstart -k "gui/$(id -u)/com.arac.$CERVEAU.pont.sync"
tail -20 ~/.arac/<cerveau>/journal/arac-pont.log

# 14. LE test qui compte vraiment : la veille
#     Fermez le Mac. Rouvrez-le une heure plus tard.
lsof -nP -iTCP:"$ARAC_PORT_API" -sTCP:LISTEN
#    ATTENDU : le tunnel est revenu tout seul. Sinon : autossh est-il
#    installé ? ClientAlive est-il posé côté serveur ?

# 15. le lendemain, après un cycle de digestion
#     Ouvrez le cockpit : http://127.0.0.1:$ARAC_PORT_COCKPIT
#     ATTENDU : des atomes issus de vos conversations d'hier.
```

---

## 12. Ce qui reste à vérifier

Honnêteté d'abord : voici la frontière exacte entre ce qui est prouvé et ce
qui ne l'est pas.

### Vérifié — et par quoi, exactement

Cette liste disait « par des tests automatisés » pour tout, et c'était trop
large. Elle a ensuite dit l'inverse — « **aucun** fichier de `tests/*.py`
n'exerce `mac/arac-sync.py` » — et c'est devenu faux à son tour, sans que
personne ne rejoue la commande qui l'accompagnait. **Le partage exact
aujourd'hui, et il se refait en deux commandes :**

```bash
grep -rl 'arac-sync' tests/          # qui parle du pont
grep -rn 'exec_module' tests/acceptance/test_les_promesses_exercables.py
```

- **Les gardes de forme** (`tests/test_tout_appelant_porte_son_jeton.py`,
  `tests/test_g1_aucun_nom_partage_entre_cerveaux.py`) *lisent* le fichier :
  ils vérifient qu'il porte son jeton et qu'il ne publie aucun nom partagé.
  Ils ne l'exécutent pas.
- **`tests/acceptance/test_les_promesses_exercables.py` l'exécute pour de
  vrai** : il charge `mac/arac-sync.py` comme module (`exec_module`) et
  éprouve son inventaire sur un faux foyer. C'est un vrai essai du pont, pas
  un garde de forme.
- **`tests/acceptance/acceptance.sh` lance le script entier** contre une vraie
  API — c'est le paragraphe suivant.

**La leçon est celle de ce dépôt tout entier, et elle vaut pour toute cette
section : un absolu (« aucun », « jamais ») se périme au premier fichier
ajouté. Ce qui ne se périme pas, c'est la commande qui le recalcule.** Rejouez
les deux ci-dessus plutôt que de croire la phrase.

**Rejoué à chaque `make acceptance`** — le vrai `mac/arac-sync.py`, non
modifié, contre une vraie API, le tunnel SSH seul étant remplacé par la boucle
locale (`tests/acceptance/acceptance.sh`, étape 5) :

* lecture des `.jsonl` de Claude Code : regroupement par `sessionId`, lignes
  de contrôle (`type: summary`, `type: system`) écartées du comptage ;
* lecture de l'export `conversations.json` ;
* le compte de conversations et de messages en base est **exactement** celui
  du manifeste du corpus ;
* provenance : tous les messages portent le `node_id` déclaré à l'entretien ;
* idempotence : un second envoi `--tout` n'ajoute aucun message ;
* le jeton porteur du pont, sans lequel l'API répond `401`.

**Annoncé comme vérifié, et rejoué par aucune commande de ce dépôt** — à
lire comme « écrit, non exercé » tant que rien ne les reprend :

* masquage des secrets avant l'envoi (le corpus d'acceptation n'en contient
  aucun : `grep -n 'sk-\|secret' tests/acceptance/corpus.py` ne rend rien) ;
* refus d'envoyer au premier lancement sans confirmation explicite — le
  harnais passe `--jenvoie`, donc ce chemin n'est jamais pris ;
* réessais sur 503, succès après deux échecs ;
* acquittement incohérent → échec **fail-closed**, curseur non avancé ;
* serveur injoignable → échec propre, aucun état corrompu ;
* configuration invalide → code 2 et explication ;
* journal JSON exploitable, **sans jeton** ;
* gabarits launchd : XML bien formé et plist valide après substitution — la
  page disait « validé par `plistlib` », mais `plistlib` n'apparaît dans
  **aucun** des fichiers que `git` transporte, sauf cette page elle-même
  (`grep -rln plistlib $(git ls-files)`) ;
* `bash -n` sur `arac-pont.sh` : `ops/lint_shell.sh` ne balaie que
  `bootstrap/` et `ops/` — `mac/` n'est pas dans sa liste.

**Mesuré à la main le 8 août 2026, et corrigé dans la foulée** : un `403` du
serveur fait bien sortir le pont en **code 4**. Le diagnostic imprimé
énumérait alors trois causes de `403`, dont « le jeton local n'est plus celui
du serveur » — or un jeton périmé rend `401`, pas `403`. Le pont sépare
désormais les deux codes et donne les gestes de chacun.

### Connu, reproduit, non corrigé — l'automatisation sur un poste à deux cerveaux

Le gabarit `mac/com.arac.pont.sync.plist.modele` lance
`~/.arac/<cerveau>/arac-sync.py` **sans argument**, et son bloc
`EnvironmentVariables` ne pose ni `ARAC_CERVEAU` ni `--conf`. Tant qu'un seul
cerveau est configuré, le repli « l'unique » fait le travail. **Dès qu'il y en a
deux, les deux agents sortent en code 2 à chaque heure et n'envoient rien** — et
comme leur sortie part dans un journal, rien ne le signale.

Reproduit sur Linux en appelant le script exactement comme l'agent le fait —
répertoire de travail `~/.arac/<cerveau>`, aucun argument, deux dossiers munis
d'un `pont.conf` — et le refus tombe :
« *Ce poste pilote plusieurs cerveaux ; lequel ?* », code **2**.

Le contournement, le contrôle et la commande `plutil` qui pose la variable dans
le plist **installé** sont au
[§ 6 bis de `DEPANNAGE.md`](DEPANNAGE.md#6-bis-le-pont-refuse--ce-poste-pilote-plusieurs-cerveaux).
Ce contournement-là n'a **pas** été exécuté sur un Mac.

### NON vérifié, faute de Mac

* **`plutil -lint`** n'a pas pu être exécuté : `plistlib` valide la même
  grammaire, mais c'est `plutil` qui fait foi sur macOS. → contrôle **2**.
* **`launchctl bootstrap` / `bootout` / `kickstart`** : aucune de ces
  commandes n'existe hors de macOS. Le comportement de chargement, le
  redémarrage après veille, la reprise après redémarrage : jamais exécutés.
  → contrôles **12**, **13**, **14**.
* **Le chemin réel du cache de Claude Desktop.** Il est décrit ici d'après
  la structure d'une application Electron ; sa forme exacte n'a pas pu être
  observée. Le pont ne le lit pas — le risque est donc documentaire, pas
  fonctionnel. → contrôle **4**.
* **La structure actuelle des `.jsonl` de Claude Code** a été reconstituée à
  partir de fichiers de session réels, mais elle peut avoir changé depuis, et
  changera. → contrôle **4**, puis le compteur « lignes illisibles ».
* **Les notifications macOS** (`osascript`) : jamais exécutées. En cas
  d'absence, la fonction est silencieuse — aucune conséquence.
* **`autossh`** : jamais exécuté. Les options (`-M 0`, `AUTOSSH_GATETIME=0`)
  sont documentées, non observées.
* **Le trajet contre une vraie API** : l'ingestion a été testée contre un
  serveur simulé conforme au contrat décrit ici (`received`/`inserted`/
  `duplicates`). Le contrat réel de **votre** serveur fait foi.
* **`deploy/ssh/99-arac-pont.conf`** n'a pas été appliqué à un vrai `sshd`.
  Faites toujours `sudo sshd -t` **avant** de recharger, et gardez une
  session ouverte.
* **`deploy/nginx/ingest-tls.conf.exemple`** n'a été ni installé ni testé :
  ni domaine, ni certificat, ni serveur disponibles. C'est un point de départ
  à relire, pas un fichier prêt à poser.

---

## 13. Les fichiers

| Fichier | Rôle |
|---|---|
| `mac/arac-sync.py` | la synchronisation : lecture, masquage, découpe, envoi, acquittement, état |
| `mac/arac-pont.sh` | installation, clé SSH, tunnel, diagnostic, première synchro, launchd |
| `mac/pont.conf.example` | la configuration, commentée — copiée en `~/.arac/<cerveau>/pont.conf` |
| `mac/com.arac.pont.sync.plist.modele` | agent launchd : une passe par heure |
| `mac/com.arac.pont.tunnel.plist.modele` | agent launchd : le tunnel permanent |
| `deploy/ssh/99-arac-pont.conf` | durcissement sshd, libération des sessions mortes |
| `deploy/ssh/authorized_keys.modele` | la clé bridée à deux ports |
| `deploy/systemd/arac-pont-sans-mac.*` | la même synchronisation, sans Mac |
| `deploy/nginx/` | pourquoi ce framework n'installe aucun serveur web |
