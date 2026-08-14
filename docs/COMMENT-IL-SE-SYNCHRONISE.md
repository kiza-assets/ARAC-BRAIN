# Comment il se synchronise — le pont, de bout en bout

Entre le fichier posé sur votre disque et la ligne écrite dans votre base, il y a six
maillons. Ce document les traverse dans l'ordre, en s'arrêtant sur le seul qui demande
vraiment à être compris : **la garde qui refuse un poste inconnu**.

Ce document explique **comment le pont marche et pourquoi il est fait ainsi**. Les gestes
— installer, appairer la clé, automatiser, diagnostiquer commande par commande — sont
dans [`PONT-MAC.md`](PONT-MAC.md). Ne lisez celui-ci que si vous voulez comprendre ce que
vous tapez.

---

# 1. La chaîne, en une image

```
   VOTRE MACHINE                                    VOTRE SERVEUR
   ─────────────                                    ─────────────

   ~/.claude/projects/*.jsonl        ┐
   ~/.arac/<cerveau>/export-desktop/ ┘
            │
            │  ① lecture (jamais d'écriture, jamais de suppression)
            ▼
      arac-sync.py  ──② masquage des secrets──┐
            │                                  │
            │  ③ lots de messages              │
            ▼                                  │
   127.0.0.1:<port API> ══④ tunnel SSH sortant═▶│  127.0.0.1:<port API>
   (port local, ouvert par autossh)             │  l'API n'écoute QUE la boucle locale
                                               ▼
                                    ⑤ POST /v1/ingest/messages
                                       Bearer <jeton>
                                       X-ARAC-Node-Id: <votre poste>
                                               │
                                               ▼
                                    ⑥ ┌──────────────────────┐
                                      │  LA GARDE             │  ← le cœur de ce document
                                      │  fail-closed          │
                                      └──────────┬───────────┘
                                                 │ acceptée
                                                 ▼
                                        arac.raw_messages
                                        + arac.ingest_receipts
```

Deux propriétés de cette image méritent d'être remarquées tout de suite.

**L'API n'est jamais exposée.** Elle écoute la boucle locale du serveur. Le port que
votre machine appelle est un port **local à votre machine**, ouvert par le tunnel.
Il n'existe aucune adresse publique à trouver, à scanner, ou à laisser fuiter.

**Ce numéro est celui de VOTRE cerveau, et il n'est écrit nulle part dans ce document.**
Le bootstrap l'a attribué après l'avoir constaté libre, puis l'a retenu ; côté poste, il
vit dans `ARAC_PORT_API` de `~/.arac/<cerveau>/pont.conf`, **sans valeur par défaut**. Un
numéro plausible — le premier venu, celui de la documentation — est précisément ce qui,
sur une machine à deux cerveaux, envoie vos conversations privées dans la mémoire de
quelqu'un d'autre.

**La flèche ne va que dans un sens.** Le serveur ne se connecte jamais à votre poste, ne
sait pas où il est, et ne peut pas l'appeler. C'est toujours vous qui parlez.

---

# 2. Le tunnel — pourquoi pas une adresse publique

La question se pose honnêtement : ouvrir l'API sur Internet avec un jeton serait plus
simple. Trois raisons de ne pas le faire.

| | Adresse publique + jeton | Tunnel SSH |
|---|---|---|
| **Surface d'attaque** | tout Internet peut frapper à la porte | rien n'atteint le port sans une session SSH établie |
| **Ce qu'un jeton fuité donne** | l'accès, tout de suite, de partout | rien depuis le réseau : il faut *aussi* la clé SSH. Depuis un compte **déjà sur le serveur**, il donne l'accès — c'est pour cela que le jeton est exigé aussi en boucle locale |
| **Ce qu'il faut faire tourner** | TLS, certificats, renouvellement, un frontal | `ssh` |

Le tunnel n'est pas une couche de sécurité en plus du jeton : c'est **une seconde serrure
qui n'ouvre pas avec la même clé**. Un jeton d'ingestion qui traîne dans une sauvegarde
n'est utilisable, **depuis le réseau**, par personne qui n'a pas aussi votre clé privée.

Les deux serrures ne se remplacent pas, et c'est le sens du changement de `app/auth.py` :
la clé SSH garde la porte extérieure, le jeton garde la porte intérieure. Quelqu'un qui a
déjà un compte sur le serveur est **derrière** la première ; s'il n'y avait que le tunnel,
il entrerait sans rien présenter. C'est pourquoi le jeton est exigé aussi en boucle
locale.

## Pourquoi `autossh` et pas `ssh` seul

Une session `ssh -L` meurt : le Wi-Fi change, le portable dort, le serveur redémarre.
`ssh` ne s'en aperçoit pas toujours — il garde une session **ouverte et muette**, ce qui
est le pire des deux mondes : la synchronisation croit avoir un tunnel, envoie, et
attend.

`autossh` sonde en permanence et **reconstruit** la session quand elle cesse de répondre.
Le gabarit fourni (`mac/com.arac.pont.tunnel.plist.modele`) l'ouvre au démarrage de votre
session et le garde en vie.

## Ce que la clé a le droit de faire

La clé posée sur le serveur ne doit **pas** être une clé de connexion générale. Elle est
restreinte au seul transfert de port : pas de shell, pas d'agent, pas de X11, pas de
tty. Une clé volée n'ouvre alors rien d'autre que deux ports en écoute locale — et sur un
serveur qu'il faut déjà savoir nommer. La forme exacte de la restriction est dans
[`PONT-MAC.md`](PONT-MAC.md) et sous `deploy/ssh/`.

---

# 3. launchd — pourquoi deux agents et pas un

Sur un Mac, deux agents sont posés, et la séparation est délibérée :

| Agent | Rôle | Rythme |
|---|---|---|
| `com.arac.pont.tunnel` | maintenir le tunnel | permanent, relancé s'il meurt |
| `com.arac.pont.sync` | lire, masquer, envoyer | une fois par heure |

**Pourquoi ne pas tout mettre dans un seul ?** Parce que les deux pannes ne se
diagnostiquent pas pareil, et surtout parce qu'elles ne se réparent pas pareil. Un tunnel
mort se voit en une commande (`lsof` sur le port). Une synchronisation qui échoue laisse
un code de sortie et une ligne de journal. Fondus dans un seul agent, les deux symptômes
deviennent « ça ne marche pas » — le diagnostic le plus coûteux qui soit.

Les gabarits portent des marqueurs `@@…@@` à remplacer ; ils restent des fichiers plist
**valides** avant substitution, pour que `plutil -lint` tranche avant que vous n'ayez rien
installé.

Sur un serveur Linux, l'équivalent est
`deploy/systemd/arac-pont-sans-mac.service.modele` accompagné de son `.timer.modele`, et
le tunnel disparaît :
source et destination partagent la boucle locale.

---

# 4. Le nœud déclaré — la notion qui gouverne tout

**Un cerveau ne sait pas d'où vient une conversation. Il sait de quel poste.**

Le `node_id` est une chaîne que **vous** choisissez, et qui doit être déclarée **des deux
côtés** :

| Côté | Réglage | Rôle |
|---|---|---|
| votre poste | `ARAC_NODE_ID` dans `~/.arac/<cerveau>/pont.conf` | ce qu'il annonce |
| votre serveur | `ARAC_INGEST_ALLOWED_NODES` (liste séparée par des virgules) | ce qu'il accepte |

Ce n'est pas une étiquette décorative. Le `node_id` est écrit sur chaque message brut, il
suit jusque dans la provenance des atomes, et il sert à répondre à des questions que vous
poserez un jour : *« ce souvenir vient-il de mon portable ou du serveur ? »*, *« ce poste
alimente-t-il encore le cerveau ? »*.

C'est aussi la cause la plus fréquente de la panne « rien n'arrive et tout a l'air
normal ». Les deux valeurs doivent être **identiques au caractère près**.

---

# 5. La garde — pourquoi elle refuse plutôt que d'accepter

Voici le maillon qui justifie ce document. Le code tient en une fonction,
`_resolve_node_id()` dans `app/routers/ingest.py`, réutilisée telle quelle par la
version 2 de l'ingestion. Elle décide **avant** que le corps de la requête ne soit
regardé.

## Ce qu'elle fait, dans l'ordre

```
① Le middleware a-t-il authentifié un jeton porteur d'un nœud ?
     oui → c'est CE nœud qui fait foi.
           Si l'en-tête X-ARAC-Node-Id est présent ET différent  → 403
     non → l'en-tête X-ARAC-Node-Id devient obligatoire          → 400 s'il manque

② ARAC_INGEST_ALLOWED_NODES est-il défini côté serveur ?
     non → 403  « Ingest not configured »   ← AUCUN nœud n'est autorisé
     oui → suite

③ Le nœud est-il dans la liste ?
     non → 403  « Node not allowed for ingest »
     oui → la requête continue
```

## Les trois refus, et ce que chacun protège

**① Le jeton l'emporte sur l'en-tête, et un désaccord est fatal.**
Un jeton valide identifie un poste. Si la requête *dit* être un autre poste, l'un des deux
ment. Accepter reviendrait à laisser un poste légitime écrire sous l'identité d'un autre —
et donc à **corrompre la provenance de tout ce qu'il envoie**. Le refus est immédiat, et
il est journalisé avec les deux valeurs, parce qu'un diagnostic sans les deux valeurs ne
sert à rien.

**② L'absence de configuration ferme la porte, elle ne l'ouvre pas.**
C'est la décision la plus importante du fichier, et la moins intuitive. Une variable
d'environnement absente pourrait vouloir dire « pas de restriction ». Ici elle veut dire
**« aucun nœud autorisé »**.

Pourquoi ? Parce que « env absente » n'est jamais le signe d'une configuration
permissive : c'est le signe d'une **configuration incomplète**. C'est l'état exact d'une
installation à moitié faite, d'un service redémarré sans son fichier d'environnement,
d'une unité systemd recopiée trop vite. Le défaut ouvert transformerait chacun de ces
accidents ordinaires en porte grande ouverte, **silencieusement**.

**③ Un nœud hors liste est refusé, même avec un jeton valide.**
La liste blanche est la seule chose qui vous permette de dire : *ce cerveau-ci accepte ces
postes-là, et pas d'autres.* Sans elle, un jeton suffirait — et un jeton se recopie.

## Le principe, énoncé une fois

> **Un refus est bruyant, immédiat, et se répare en une minute.
> Une acceptation à tort est silencieuse, et se découvre des mois plus tard.**

La mémoire d'un cerveau ARAC est en ajout seul, et sa valeur tient largement à sa
**provenance** — savoir d'où vient chaque chose. Une ligne entrée sous une identité
douteuse ne sera jamais rattrapée : elle sera digérée, elle produira des atomes, et ces
atomes citeront une origine fausse. Sur le cerveau de référence, une rupture de
provenance a coûté **76 % du lien entre les atomes et les conversations qui les avaient
produits**. Le savoir était là, et plus personne ne pouvait dire d'où il venait.

C'est pour ça que la garde refuse en cas de doute. Ce n'est pas de la prudence : c'est de
l'arithmétique sur les coûts de l'erreur.

---

# 6. L'acquittement — pourquoi un `200 OK` ne suffit pas

Le pont **n'accepte pas un code 2xx comme preuve**. Le serveur répond trois nombres :

```json
{ "received": 40, "inserted": 37, "duplicates": 3 }
```

Deux égalités sont exigées pour que le lot soit considéré comme acquitté :

```
received  ==  ce que le pont a envoyé
received  ==  inserted + duplicates
```

Toute autre réponse fait **échouer le lot sans avancer le curseur**.

La raison tient en une phrase : *mieux vaut un renvoi inutile qu'un trou silencieux dans
la mémoire.* Un renvoi coûte quelques secondes et se termine en doublons comptés. Un trou
ne se voit jamais — vous découvrirez son existence le jour où le cerveau ne se souviendra
pas d'une conversation dont vous êtes certain qu'elle a eu lieu, six mois trop tard pour
savoir laquelle.

## Idempotence : renvoyer n'est pas grave

Chaque message porte une **clé naturelle** — son identifiant natif, ou l'empreinte de son
contenu s'il n'en a pas. Une seconde insertion du même message est comptée « doublon »
sans rien écrire.

Conséquence pratique : `--tout` (renvoyer tout l'historique) est **sans danger**. C'est le
filet de rattrapage quand vous doutez d'un trou.

L'état local (`~/.arac/<cerveau>/etat-pont.json` — un curseur **par cerveau**, jamais
partagé) n'est donc **qu'une optimisation** : il évite de
relire et de renvoyer du connu. Il retient, par conversation, combien de messages ont été
acquittés et l'empreinte de ce préfixe. Si le préfixe a changé — conversation réécrite —
le pont reprend cette conversation depuis le début. Perdre ce fichier ne perd aucune
donnée : cela coûte un passage plus long.

## Ce que le serveur garde comme preuve

Chaque requête d'ingestion, **acceptée ou refusée**, laisse un reçu
(`arac.ingest_receipts`) portant son `request_id` — écrit dans le corps *et* dans l'en-tête
de la réponse. Le reçu d'une acceptation est écrit **dans la même transaction** que les
messages : si l'un est annulé, l'autre l'est aussi. Le reçu d'un refus est écrit en
connexion autonome, pour ne jamais masquer l'erreur d'origine.

Vous pouvez donc toujours répondre à « qu'est-il arrivé à mon envoi de 14 h ? » — c'est
exactement la question à laquelle un pont muet ne sait pas répondre.

---

# 7. Ce qui casse en pratique, et comment le voir

Cinq pannes couvrent la quasi-totalité des cas. Chacune a une **signature distincte** —
c'est tout l'intérêt d'avoir séparé les maillons.

| Ce que vous voyez | Ce que c'est | Où regarder |
|---|---|---|
| **`403` — `Node not allowed for ingest`** | `ARAC_NODE_ID` (poste) ≠ une entrée de `ARAC_INGEST_ALLOWED_NODES` (serveur) | comparer les deux valeurs, caractère par caractère. C'est **la** panne fréquente. |
| **`403` — `Ingest not configured`** | `ARAC_INGEST_ALLOWED_NODES` n'est pas définie côté serveur : la garde ferme | l'environnement du service d'API, pas votre poste |
| **`401`** | jeton absent, expiré, ou pas celui de ce cerveau | `ARAC_TOKEN_FILE` sur le poste ; le jeton attendu côté serveur |
| **« serveur injoignable »** | le tunnel est mort | `lsof -nP -iTCP:"$ARAC_PORT_API" -sTCP:LISTEN` sur le poste — doit montrer `ssh`/`autossh` |
| **Rien n'arrive, et tout dit « OK »** | le cas le plus pénible : voir ci-dessous | |

## La panne qui ment

Un pont peut se déclarer en bonne santé alors que rien n'entre. Trois causes, dans
l'ordre où il faut les écarter :

1. **L'agent ne tourne pas.** launchd (ou le timer systemd) ne l'a jamais lancé. Vérifiez
   la présence des deux agents, pas seulement du tunnel.
2. **Il tourne et ne trouve rien.** `ARAC_CLAUDE_CODE_DIR` pointe à côté, ou vous n'avez
   utilisé que Claude Desktop — dont rien n'est capté automatiquement.
3. **Il envoie et le serveur refuse.** C'est un `403`, et il est dans le journal du pont
   (`~/.arac/journal/arac-pont.log`) autant que dans les reçus d'ingestion côté serveur.

**La question qui tranche**, côté serveur, est toujours la même : *depuis combien de temps
le cerveau n'a-t-il rien reçu ?* — et elle se pose sur `received_at` (l'instant où le
serveur a écrit), jamais sur la date du message. Le premier dit si le pont vit encore ; le
second dit seulement quand vous avez tapé. La commande exacte est dans
[`PREMIER-MOIS.md`](PREMIER-MOIS.md), jour 2.

> ### Ah, d'accord n° 3
> Un port qui répond n'est pas une preuve que le bon service répond. Sur la machine de
> référence, un service d'essai a un jour lié le port de l'API de production : `/healthz`
> répondait `200` — **servi par l'usurpateur**. Le vrai service, lui, redémarrait en
> boucle sans jamais pouvoir se lier. Vérifiez toujours *quel* processus tient un port
> (`ss -tlnp`), jamais seulement qu'il répond.

---

# 8. Ce que ce pont ne fait pas

- **Il ne chiffre rien lui-même.** Le chiffrement est celui de SSH, et il s'arrête au
  serveur. Sur le serveur, le texte est en clair dans PostgreSQL. Le chiffrement au repos
  est votre affaire (disque chiffré, sauvegardes chiffrées — voir
  [`SAUVEGARDE.md`](SAUVEGARDE.md)).
- **Il ne supprime rien**, ni chez vous ni sur le serveur. Effacer un souvenir est un
  geste séparé et délibéré.
- **Il ne pousse pas.** Le serveur ne peut pas demander une synchronisation. Si votre
  poste est éteint, rien n'arrive, et c'est tout.
- **Il ne résout pas les conflits.** Deux postes qui envoient la même conversation
  produisent des doublons comptés, pas une fusion.

---

# Ce qui a été vérifié pour écrire ce document

| Affirmation | Où elle se vérifie | État |
|---|---|---|
| L'ordre exact des trois contrôles de la garde | `app/routers/ingest.py`, `_resolve_node_id()` | ✅ lu ligne à ligne |
| `403` sur désaccord jeton / en-tête | `app/routers/ingest.py` | ✅ lu |
| Env absente ⇒ `403 Ingest not configured` (fail-closed) | `app/routers/ingest.py` | ✅ lu |
| La v2 de l'ingestion réutilise la même garde | `app/routers/ingest_v2.py` (import de `_resolve_node_id`) | ✅ lu |
| Reçu écrit pour toute issue, acceptée ou refusée | `app/routers/ingest_v2.py`, docstring + `app/services/ingest_receipts.py` | ✅ lu |
| Reçu d'acceptation dans la même transaction | idem | ✅ lu |
| Les deux égalités d'acquittement | `mac/arac-sync.py`, docstring d'en-tête | ✅ lu |
| Rôle de `etat-pont.json` (optimisation, pas vérité) | `mac/arac-sync.py` | ✅ lu |
| Deux agents launchd distincts | `mac/com.arac.pont.sync.plist.modele` et `mac/com.arac.pont.tunnel.plist.modele` | ✅ lus |
| L'absence de port et d'URL par défaut, et sa raison | `mac/pont.conf.example` (`ARAC_INGEST_URL=` et `ARAC_PORT_API=` sont vides) | ✅ lu |
| Équivalent serveur sans tunnel | `deploy/systemd/arac-pont-sans-mac.service.modele` | ✅ lu |
| 76 % de provenance perdue | mesure du cerveau de référence, citée dans `mac/arac-sync.py` | ✅ lu, non re-mesuré ici |

**Ce dont ce document n'est pas certain :** le comportement de `launchd` au réveil après
une longue veille n'a pas été observé sur un Mac réel. Les deux gabarits posent
`RunAtLoad` et un intervalle ; ce que macOS en fait exactement après plusieurs jours de
sommeil reste à constater. Signalez ce que vous voyez — c'est précisément le genre
d'observation que ce dépôt ne peut pas fabriquer.

---

**Suite du manuel :**
[`COMMENT-IL-CONSTRUIT-SES-ATOMES.md`](COMMENT-IL-CONSTRUIT-SES-ATOMES.md) — ce qui se
passe une fois que la conversation est dans la base.
