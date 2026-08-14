# Le premier mois — ce que vous allez vraiment voir

**Lisez ce document avant d'installer, pas après.**

Ce n'est pas une liste d'objectifs. C'est le récit de ce qui se passe entre le moment où
le cerveau naît et celui où vous ne voulez plus vous en passer — avec, à chaque étape,
**ce que vous verrez**, **pourquoi**, **ce qui est normal**, **ce qui ne l'est pas**, et
**quoi faire** dans le second cas.

Si vous cherchez le premier jour dans le détail opératoire — la première synchronisation,
le premier cycle forcé, le premier `curl` — c'est [`PREMIER-JOUR.md`](PREMIER-JOUR.md) qui
le tient. Ce document-ci prend le relais et va jusqu'au trentième.

---

## Le risque n° 1 de ce projet n'est pas technique

Il faut le dire au moment où vous décidez, pas au moment où vous décrochez.

**Vous allez installer un cerveau, et pendant plusieurs jours il ne vous servira à
rien.** Pas parce qu'il est cassé : parce qu'il est vide. Un cerveau se remplit au rythme
de ce que vous dites, et vous ne dites pas mille choses par jour. Le système fonctionnera
parfaitement, il n'aura simplement rien à répondre.

```
  utilité du rappel
        │                                                    ╭──────
        │                                          ╭─────────╯
        │                              ╭───────────╯
        │                ╭─────────────╯
        │      ╭─────────╯
        │ ╭────╯
        └─┴────┬─────────┬─────────────┬───────────┬─────────┬──────▶
        J1    J7        M1            M2          M3        M6
              ▲                        ▲
              │                        │
      « ça ne sert à rien »   « je ne peux plus travailler sans »
```

**Le creux est réel, il dure environ un mois, et c'est là que les gens arrêtent** — deux
à six semaines avant que ça devienne intéressant. Ce n'est pas une faiblesse
d'implémentation : aucune mémoire, humaine ou machine, n'est utile le jour de sa
naissance.

Trois choses vous aideront à traverser ce creux, et elles sont toutes dans ce document :

1. **savoir à l'avance ce que chaque jour ressemble** — pour ne pas confondre « vide » et
   « cassé » ;
2. **avoir un moment de preuve tôt** — au jour 3, quand vous ouvrirez un souvenir et
   remonterez jusqu'à la conversation qui l'a produit. Ce moment ne prouve pas l'utilité,
   il prouve que la chaîne fonctionne. C'est suffisant pour tenir ;
3. **ne pas mesurer la mauvaise chose.** Au jour 5, le nombre d'atomes ne veut rien dire.
   Ce qui veut dire quelque chose, c'est : *le cerveau reçoit-il ? digère-t-il ? range-t-il
   sur des feuilles ?* Trois questions auxquelles on peut répondre dès la première
   semaine.

> **Si vous n'êtes pas prêt à attendre un mois avant de juger, n'installez pas ARAC
> aujourd'hui.** Ce n'est pas un outil qu'on essaie une soirée. Les raisons de ne pas
> l'installer du tout sont dans [`PHILOSOPHIE.md`](PHILOSOPHIE.md), et elles sont
> sérieuses.

---

## « Je suis au jour N et je vois ceci — est-ce que ça va ? »

Le tableau à consulter en premier. La colonne de droite renvoie à la section qui explique.

| Jour | Ce que vous voyez | Verdict | Où lire |
|---|---|---|---|
| 1 | « Le cerveau n'a rien appris depuis 24 heures. » | ✅ **normal** | [Jour 1](#jour-1--le-cerveau-est-né-et-il-ne-sait-rien) |
| 1 | un rappel qui rend zéro résultat | ✅ **normal** — il n'y a rien à trouver | [Jour 1](#la-première-question-et-pourquoi-elle-ne-rend-rien) |
| 1 | un rappel qui rend une **erreur** au lieu d'une liste vide | ❌ **cassé** | [Jour 1](#normal-ou-cassé--jour-1) |
| 1–2 | des centaines de conversations reçues, très peu d'atomes | ✅ **normal** — la file se digère par tranches | [Jour 1](#si-vous-avez-un-historique-le-cerveau-ne-lavale-pas-dun-coup) |
| 2 | *toujours* aucun atome, et la file n'est pas vide | ⚠️ à vérifier | [Jour 2](#jour-2--le-jour-où-lon-arrête-et-pourquoi-il-ne-faut-pas) |
| 2–3 | 1 cycle sur 3 en quarantaine | ✅ **normal** — 36 % observés | [Jour 3](#les-cycles-stériles-et-la-vraie-cause) |
| 3 | des atomes, mais aucune provenance de conversation | ⚠️ à vérifier tout de suite | [Jour 3](#si-la-provenance-manque-nattendez-pas) |
| 3–7 | 96 % des rappels en confiance basse | ✅ **normal** — le cerveau doute et le dit | [Jour 7](#pourquoi-la-confiance-reste-basse-et-pourquoi-cest-bon-signe) |
| 7 | un rappel qui rend des atomes hors sujet | ✅ **normal** à 30 atomes | [Jour 7](#ce-que-vous-devez-tester-au-jour-7) |
| 7 | des atomes posés sur une **racine** | ❌ **à corriger** — ils sont hors de l'état courant, de la vue des scopes et de la couverture | [Jour 7](#le-piège-n-1-se-corrige-au-jour-7-pas-au-mois-6) |
| 7–30 | rien n'entre depuis 26 h, mais la digestion tourne | ❌ **cassé** — la panne la plus sournoise | [Jour 30](#normal-ou-cassé--le-tableau-du-mois) |
| 30 | ~150 atomes | ✅ **normal** — c'est l'ordre de grandeur observé | [Jour 30](#jour-30--le-cerveau-commence-à-anticiper) |
| 30 | 400 atomes | ✅ **normal** aussi — votre historique a été digéré | [Jour 30](#combien-datomes-au-bout-dun-mois) |
| 30 | 20 atomes | ❌ **anormal** | [Jour 30](#combien-datomes-au-bout-dun-mois) |
| 30 | « ce savoir dort » — beaucoup d'atomes jamais servis | ✅ **normal** au premier mois | [Jour 30](#le-savoir-dormant) |

---

# Jour 1 — le cerveau est né, et il ne sait rien

## Ce que vous voyez

Vous ouvrez le cockpit (tunnel SSH ouvert, `http://127.0.0.1:<le port cockpit>` — il est
attribué à votre installation, jamais fixé). Vous vous attendez à
un tableau de bord. Vous obtenez une phrase :

```
  Le cerveau n'a rien appris depuis 24 heures.
  Personne ne m'a rien demandé depuis 24 heures : aucun rappel servi.
```

C'est décevant, et c'est délibéré. Le cockpit **refuse d'afficher un bandeau vide** qu'on
prendrait pour un chargement en cours : une journée sans rien est une information, et elle
se dit en toutes lettres.

Si votre première synchronisation est déjà passée et qu'un cycle a tourné, vous verrez
plutôt quelque chose comme :

```
  Depuis 24 heures, j'ai appris 3 conversation(s) et créé 4 atome(s) de savoir.
  J'ai absorbé 1 240 message(s) depuis 24 heures, dont 380 pour la seule
  conversation « refonte du script de déploiement ».
  Personne ne m'a rien demandé depuis 24 heures : aucun rappel servi.
```

**Quatre atomes.** Voilà où vous en êtes. Ce n'est pas peu : c'est *exactement* ce à quoi
ressemble un cerveau d'un jour.

## Pourquoi si peu, alors que tant de messages sont entrés

Parce qu'ARAC ne stocke pas ce que vous dites : il stocke ce que vous avez **conclu**.
Mille deux cent quarante messages, c'est une journée de travail bavarde. Ce qui, dedans,
reste vrai demain — une décision, une version, un piège rencontré — tient en quelques
phrases. Le reste est du raisonnement en cours, et il ne mérite pas d'être mémorisé.

C'est l'inversion la plus importante à intégrer, et elle est mesurable : **~87 000 jetons
lus par cycle pour ~31 500 jetons par atome retenu.** La plupart de ce qui est lu ne
produit rien. Ce n'est pas du gâchis : c'est le tri.

## Si vous avez un historique, le cerveau ne l'avale pas d'un coup

Si Claude Code (CLI) tourne chez vous depuis des mois, votre `~/.claude/projects/` contient
peut-être des centaines de sessions. Le pont les remontera toutes — mais la digestion, elle,
travaille **par tranches** :

| Garde | Valeur par défaut | Fichier |
|---|---|---|
| budget de jetons par cycle | **80 000** (`ARAC_PACK_TOKEN_BUDGET`) | `agents/cortex/pack.py` |
| conversations admises par cycle | **20** (recommandé : 4, `ARAC_PACK_MAX_CONVS`) | idem |
| cycles par jour | **3** (04:00 · 13:00 · 21:00) | unité systemd |

Autrement dit : **une douzaine à une soixantaine de conversations digérées par jour, au
mieux.** Trois cents conversations d'historique, ce sont une à trois semaines de
rattrapage. Pendant ce temps, la file se voit :

```
  La file grandit : 41 conversation(s) reçue(s) depuis 24 heures
  pour 12 entièrement curée(s).
```

Cette phrase n'est pas une alarme au jour 1. Elle en devient une si elle est encore là au
jour 30 (voir [Jour 30](#la-file-qui-ne-se-résorbe-jamais)).

## La première question, et pourquoi elle ne rend rien

Le tunnel ouvert, depuis votre machine :

> **Le port de l'API est celui de VOTRE cerveau.** Relevez-le sur le serveur, puis posez-le
> dans le terminal d'où vous lancez ces commandes :
>
> ```bash
> BASE=<votre_base>
> API=$(systemctl show "arac-$BASE-api" -p ExecStart --value | sed -n 's/.*--port \([0-9]\{1,\}\).*/\1/p')
> ```
>
> Sur un Mac, c'est `ARAC_PORT_API` de `~/.arac/<votre_base>/pont.conf` — la même valeur,
> du côté du tunnel. Aucun numéro n'est écrit en dur ici : sur une machine à deux cerveaux,
> un numéro plausible interroge la mémoire de quelqu'un d'autre, et rien ne vous le dit.

> **Et le jeton, dans le même terminal.** L'API l'exige de **toute** requête, `127.0.0.1`
> compris : le tunnel SSH ne dit rien de *qui*, sur le serveur, atteint la boucle locale.
>
> ```bash
> # sur le serveur, root uniquement
> sudo grep '^ARAC_API_BEARER_TOKEN=' "/etc/arac/$BASE/arac.env"
> # puis, dans le terminal d'où vous appelez l'API
> JETON=<la valeur relevée ci-dessus>
> ```

```bash
curl -s -X POST http://127.0.0.1:$API/v1/atoms/recall \
     -H "Authorization: Bearer $JETON" \
     -H 'Content-Type: application/json' \
     -d '{"query": "quelle version de PostgreSQL tourne en production ?", "k": 5}' \
     | python3 -m json.tool
```

Vous obtiendrez `[]`, ou quatre atomes sans rapport avec votre question, classés par
`distance` croissante.

**Ce n'est pas un défaut de la recherche.** Le rappel fait exactement ce qu'on lui demande :
il rend les atomes les plus proches de votre question. Quand il n'y en a que quatre en
base, « les plus proches » veut dire « les moins éloignés », ce qui n'est pas la même
chose que « pertinents ». Un moteur de recherche sur quatre documents rend toujours quatre
documents.

**Ce qu'il faut vérifier au jour 1, ce n'est pas la pertinence — c'est la mécanique :**
la requête part, l'embedding est calculé, la base répond, chaque atome porte sa
`distance`. Si c'est le cas, la chaîne de rappel est saine. La pertinence viendra du
volume, pas d'un réglage.

---

## Avant la première commande de cette page : à quel cerveau parlez-vous ?

Un serveur peut porter plusieurs cerveaux. Les commandes `psql` de cette page interrogent
donc **un DSN**, jamais un simple nom de base — un DSN porte l'hôte, le port et la base, et
c'est la seule forme qui ne puisse pas se tromper de serveur.

```bash
BASE=<votre_base>          # brain.name de config/brain.toml
DSN_RO=$(sudo sed -n 's/^DATABASE_URL_READONLY=//p' "/etc/arac/$BASE/arac.env")
: "${DSN_RO:?introuvable dans /etc/arac/$BASE/arac.env — arretez-vous ici}"
```

Le rôle en **lecture stricte** ne peut rien casser : c'est celui qu'on colle dans un
terminal sans réfléchir. **Mais si vous sautez ces deux lignes, `psql "$DSN_RO"` devient
`psql ""`** — et `psql` sans adresse ne s'abstient pas de choisir : il se rabat sur la
grappe **par défaut** de la machine, `5432`, sous votre nom d'utilisateur. Sur un serveur
qui porte deux cerveaux, c'est celle du voisin, et rien ne vous le dira.

---

## Normal ou cassé — jour 1

| Ce que vous voyez | Verdict | Quoi faire |
|---|---|---|
| « Le cerveau n'a rien appris depuis 24 heures. » | ✅ normal | rien. Attendez le premier cycle. |
| un rappel qui rend `[]` | ✅ normal | rien. |
| un rappel qui rend des atomes hors sujet | ✅ normal | rien. |
| un rappel qui rend **une erreur 500** | ❌ cassé | la clé d'embeddings. `journalctl -u arac-<base>-api -n 50` |
| le cockpit répond **503** | ❌ cassé | le double vocabulaire — [`DEPANNAGE.md` §1](DEPANNAGE.md#1-lapi-ne-démarre-pas--database_url_app-non-définie) |
| le pont dit **403** en poussant | ❌ cassé | les deux portes de l'ingestion — [`DEPANNAGE.md` §7](DEPANNAGE.md#7-http-403--le-serveur-refuse-ce-poste) |
| des conversations reçues, **zéro** message absorbé | ❌ cassé | même cause : le poste n'est pas déclaré |
| beaucoup de messages absorbés, zéro atome, **et le cycle n'a pas encore tourné** | ✅ normal | forcez-en un : `sudo systemctl start arac-<base>-cycle.service` |

**Le geste du jour 1**, et il n'est pas négociable : ouvrez un atome, lisez-le, et notez
son identifiant quelque part. Vous en aurez besoin au jour 3.

---

# Jour 2 — le jour où l'on arrête, et pourquoi il ne faut pas

Il n'y a rien de nouveau à voir au jour 2. C'est précisément le problème.

Le pont tourne, la digestion tourne, la sauvegarde tourne, et le cockpit affiche six ou
huit atomes au lieu de quatre. Vous avez passé une demi-journée à installer un système qui
sait moins de choses que le post-it collé sur votre écran. **C'est ici que la majorité des
abandons ont lieu**, et ils ont lieu pour une bonne raison : rien, dans ce que vous voyez,
ne ressemble encore à une mémoire.

Deux repères pour ce jour-là.

**Ce que vous devez vérifier au jour 2 n'est pas « est-ce utile ? » mais « est-ce
vivant ? ».** Trois signes suffisent :

```bash
# 1. le cerveau reçoit-il encore ? (doit être < 26 h)
#    `received_at` = l'instant où le serveur a écrit le message, pas celui où
#    vous l'avez tapé (`msg_created_at`). C'est bien le premier qui dit si le
#    pont vit encore.
psql "$DSN_RO" -c \
  "SELECT max(received_at) FROM arac.raw_messages;"

# 2. digère-t-il ? (au moins un cycle abouti dans les 24 h)
journalctl -u arac-<base>-cycle.service --since '24 hours ago' | tail -20

# 3. range-t-il sur des feuilles ? (le compte DOIT rester à zéro)
psql "$DSN_RO" -c \
  "SELECT scope, count(*) FROM arac.memory_atoms
    WHERE status='active' AND scope NOT LIKE '%/%' GROUP BY 1 ORDER BY 2 DESC;"
```

Trois oui : le cerveau va bien, il est simplement jeune. Un non : la section
correspondante ci-dessus vous dit quoi faire.

**Et le geste du jour 2, qui n'a rien à voir avec la mémoire :** prouvez votre sauvegarde.

```bash
# Le plus simple, et le plus sûr : les unités, qui portent déjà le coffre de CE cerveau
sudo systemctl start "arac-$BASE-sauvegarde.service"     # une sauvegarde, tout de suite
sudo systemctl start "arac-$BASE-restauration.service"   # et sa preuve, base jetable
sudo journalctl -u "arac-$BASE-restauration.service" -n 40 --no-pager
```

À la main, hors des unités, nommez le cerveau — sinon, sur une machine qui en porte
plusieurs, les deux scripts ne s'arrêtent pas : ils servent celui que **le clone d'où
vous tapez** décrit, après l'avoir annoncé. C'est exact tant qu'un clone ne sert qu'un
cerveau ; la variable, elle, ne dépend pas du dossier courant :
`sudo ARAC_ENV_FILE="/etc/arac/$BASE/arac.env" ops/backup.sh`.

C'est le meilleur jour pour le faire — vous n'avez encore rien à perdre, donc l'exercice
est sans enjeu, et vous saurez que ça marche avant d'avoir un an de mémoire dedans. Une
sauvegarde jamais restaurée n'est pas une sauvegarde, c'est une hypothèse.
[`SAUVEGARDE.md`](SAUVEGARDE.md) tient le sujet.

---

# Jour 3 — le cerveau comprend, et vous pouvez le prouver

## Ce que vous voyez

Trois jours, neuf cycles. Le bandeau commence à raconter une journée plutôt qu'un
incident :

```
  Depuis 24 heures, j'ai appris 5 conversation(s) et créé 9 atome(s) de savoir.
  Le domaine outillage/serveur est celui qui s'est le plus enrichi : 4 atome(s)
  créé(s) depuis 24 heures.
  Le dernier souvenir retenu est un decision dans travail/strategie :
  « choix-base-vectorielle ».
  1 cycle(s) sur 3 sont partis en quarantaine depuis 24 heures ; cycles
  réellement aboutis : 2. Ce que les autres portaient n'a pas été retenu.
  J'ai dépensé 174 300 jetons depuis 24 heures, soit 19 366 jetons par atome retenu.
```

Vous avez entre 15 et 40 atomes. **Le rappel ne sert toujours à rien**, et il ne servira à
rien avant plusieurs semaines. Ce n'est pas ce qu'il faut regarder aujourd'hui.

## Le moment qui compte : ouvrir un souvenir et remonter à sa naissance

C'est *le* geste du jour 3, et c'est le seul moment du premier mois où vous obtenez une
preuve tangible que tout le système fonctionne. Prenez cinq minutes, faites-le vraiment.

**1. Prenez un atome.** Dans le cockpit, ou directement :

```
GET /cc/v1/atoms                    tous, les plus récents d'abord
GET /cc/v1/atoms?scope=travail/strategie
```

Vous verrez quelque chose comme :

```
  clé          choix-base-vectorielle
  valeur       Le stockage vectoriel se fait dans PostgreSQL via pgvector,
               retenu contre une base dédiée pour éviter un second système
               à sauvegarder.
  domaine      travail/strategie
  nature       decision            (ce que vous avez choisi, et pourquoi)
  confiance    agent_suggest       (proposé par le curateur, non validé par vous)
```

**Lisez la valeur, et comparez-la mentalement à ce que vous aviez écrit.** La phrase que
vous aviez tapée a disparu. Ce qui reste est l'affirmation qu'elle contenait, réécrite pour
tenir debout toute seule, hors de son contexte. C'est toute la différence entre archiver et
se souvenir : une archive vous rend votre phrase, une mémoire vous rend votre conclusion.

**2. Ouvrez son histoire.**

```
GET /cc/v1/atoms/{id}/story
```

Une seule requête répond à quatre questions qu'aucun compteur ne sait poser : **d'où vient
ce souvenir, qui l'a corrigé, qui s'en sert, depuis quand.** Vous y trouverez la naissance
(le cycle et la conversation), la chronologie, les voisins sémantiques — avec cette mise
en garde servie dans la réponse elle-même : *« un voisin n'est pas un lien : c'est une
ressemblance calculée »* — et l'`evidence` : le SQL réellement exécuté, paramètres
substitués, sur une ligne. **Vous pouvez le coller dans `psql` et contredire le cockpit.**
Un cockpit qu'on ne peut pas contredire ne mérite pas d'être cru.

**3. Remontez à la conversation.**

```
GET /cc/v1/conversations/{conversation_uid}
```

Et là, vous relisez l'échange d'où ce souvenir est né. **C'est le moment que ce document
tout entier existe pour vous faire atteindre.** Une phrase écrite un mardi soir, sans
intention de la garder, est devenue une affirmation rangée dans un domaine, retrouvable
sans que vous vous rappeliez l'avoir écrite. Machine → tunnel → ingestion → curation →
atome → embedding → cockpit : la chaîne complète vient de se prouver sur un cas réel.

*(L'ordre n'est pas une coquille : l'embedding vient **après** l'atome et porte sur lui. Le
message que vous venez de relire, lui, n'a jamais eu de vecteur.)*

## Deux blocs vous répondront « indisponible »

Dans l'histoire de l'atome, `links` et `verification` diront tous les deux :

```
  state       unavailable
```

**Une absence de mesure ne s'affiche jamais comme un zéro** — un zéro se lit « c'est nul »,
une indisponibilité se lit « on ne sait pas ». C'est la même règle que pour la fraîcheur.

Mais les deux ne disent pas la même chose, et la nuance vaut d'être connue :

- **`verification`** est une vraie absence : `last_verified_at` et `confirmed_until` ne
  sont alimentés par rien du tout. Il n'y a pas de mécanisme derrière.
- **`links`**, lui, ne dit **pas** que la table de liens manque. Elle est là, posée par
  votre installation, et le cycle la remplit à chaque tour. Ce que ce bloc dit, c'est que
  **ce panneau-là ne lit pas son contenu** — et il a raison, personne ne le lit encore,
  pas même le rappel. Si vous voulez voir les arêtes, elles sont en base :
  `SELECT relation_type, count(*) FROM arac.atom_links GROUP BY 1;`

Ce que la couche de liens fait et ne fait pas est décrit au maillon ⑩ de
[`ARCHITECTURE.md`](ARCHITECTURE.md), et résumé au §7a du
[`README`](../README.md#a-le-graphe-de-liens-est-écrit-mais-jamais-servi--et-il-ne-porte-aucun-sens).

## Les cycles stériles, et la vraie cause

Vous verrez régulièrement :

```
  1 cycle(s) sur 3 sont partis en quarantaine depuis 24 heures ; cycles
  réellement aboutis : 2. Ce que les autres portaient n'a pas été retenu.
```

Sur le cerveau de référence, **36 % des cycles n'ont produit aucun atome**. C'est banal, et
le cockpit classe volontairement cette phrase **avant** les réussites : deux cycles perdus
en disent plus long sur une journée qu'un troisième projet qui avance.

**Mais attention à la cause.** L'explication intuitive — « il n'y avait rien
d'intéressant » — était fausse. La cause réelle mesurée était **des identifiants de poste
incohérents entre le pack servi au modèle et sa réponse** : le cycle travaillait, le modèle
répondait, et la réponse était jetée parce qu'elle référençait des identifiants que le
serveur ne reconnaissait pas. Ce n'était pas un problème de volume, et aucune quantité de
conversations en plus ne l'aurait résolu.

| Ce que vous observez | Verdict | Quoi faire |
|---|---|---|
| 1 cycle stérile sur 3 | ✅ normal | rien |
| 4 cycles ratés d'affilée | ⚠️ | `scripts/ops/alerts.py` calcule si c'est explicable par *votre* taux |
| **6 cycles stériles d'affilée** et la file n'est pas vide | ❌ cassé | vérifiez que `ARAC_NODE_ID` est **identique** côté serveur et côté machine source, au tiret près |
| « J'ai dépensé N jetons depuis 24 heures sans retenir un seul atome. » | ❌ cassé | même piste. Vous payez pour rien : coupez `ARAC_ALLOW_PAID_AI` le temps de comprendre |

Cette dernière phrase (`cost_without_yield`) est celle qu'il faut surveiller le plus au
premier mois : elle veut dire que la facture court sans que la mémoire grandisse.

## Si la provenance manque, n'attendez pas

Vous verrez peut-être, à la place de la naissance :

```
  state       unavailable
  reason      cet atome ne déclare aucune provenance de conversation
```

Sur le cerveau de référence, **76 % de la provenance a été perdue** — non par négligence,
mais parce que le format de `source_ref` a changé en cours de route : les atomes écrits
avant le changement portent une clé que le code d'après ne sait plus lire. Le lien était
pourtant intact au moment de l'écriture.

**La leçon vous concerne dès aujourd'hui : ne touchez pas au format de `source_ref`.**
C'est la structure la plus coûteuse à changer de tout le système, parce qu'elle est la
seule chose qui relie ce que le cerveau sait à l'endroit où il l'a appris. Un souvenir sans
provenance n'est pas faux — il est simplement invérifiable, et un savoir invérifiable finit
par ne plus valoir grand-chose.

Si la provenance manque sur une installation **neuve**, ce n'est pas ce phénomène-là :
c'est un bug, et il faut le signaler ([`CONTRIBUER.md`](CONTRIBUER.md)).

---

# Jour 7 — les premiers sujets deviennent rappelables

## Ce que vous voyez

Une semaine, vingt et un cycles, entre 30 et 80 atomes selon votre bavardage et votre
historique. Le bandeau parle maintenant de projets :

```
  Depuis 24 heures, j'ai appris 4 conversation(s) et créé 6 atome(s) de savoir.
  Le projet migration-serveur progresse : 3 atome(s) de plus depuis 24 heures.
  3 atome(s) existants ont été réécrits depuis 24 heures : j'ai affiné plutôt
  qu'ajouté.
  J'ai servi 2 rappel(s) depuis 24 heures.
```

Deux phrases méritent votre attention.

**« j'ai affiné plutôt qu'ajouté »** est le premier signe que le cerveau accumule du savoir
et non des lignes. Un atome réécrit, c'est une affirmation que le curateur a retrouvée,
reconnue, et précisée. C'est ce qui distingue une mémoire d'un journal.

**« Le projet X progresse »** est le premier signe que le cerveau a un territoire. Un
projet qui gagne trois atomes en un jour est un sujet sur lequel vous travaillez
réellement — et c'est exactement celui sur lequel il faut tester le rappel.

## Ce que vous devez tester au jour 7

Posez une question sur **quelque chose que vous avez travaillé la semaine passée** — pas
sur un sujet vague, pas sur quelque chose d'ancien : un sujet précis, récent, sur lequel
vous avez eu plusieurs conversations.

```bash
curl -s -X POST http://127.0.0.1:$API/v1/atoms/recall \
     -H "Authorization: Bearer $JETON" \
     -H 'Content-Type: application/json' \
     -d '{"query": "pourquoi avons-nous abandonné le déploiement par conteneur ?", "k": 5}' \
     | python3 -m json.tool
```

**Ce qui doit se passer au jour 7 :** parmi les cinq résultats, **un ou deux** sont
réellement liés à votre question, et les autres sont du bruit. C'est le premier signal
positif du mois. Il est modeste, et il est suffisant.

**Ce qui ne doit pas se passer :** cinq résultats sans aucun rapport, alors que vous *savez*
que le sujet a été discuté et qu'un atome existe. Trois causes possibles, dans cet ordre :

| Cause | Comment la reconnaître | Correctif |
|---|---|---|
| l'atome est posé sur une **racine** | la requête ci-dessous rend un compte > 0 | voir juste en dessous |
| la conversation n'a **pas encore été digérée** | la file grandit encore | patience — ou forcez un cycle |
| l'atome existe mais dit la chose **allusivement** | ouvrez-le, lisez sa `valeur` | c'est la limite du curateur : un atome allusif reçoit un vecteur allusif |

Et une quatrième, qui n'est pas un défaut mais une propriété du système : **si le curateur
n'a pas retenu la chose, elle n'est pas retrouvable par le sens.** Elle reste en base, dans
sa conversation, horodatée et attribuée — mais vos messages bruts n'ont pas de vecteur, et
le rappel ne les visite jamais. C'est un arbitrage assumé : il rend le rappel net, et il
vous rend dépendant de la qualité de ce que le curateur écrit.

## Le piège n° 1 se corrige au jour 7, pas au mois 6

```bash
# le compte DOIT rester à zéro
psql "$DSN_RO" -c \
  "SELECT scope, count(*) FROM arac.memory_atoms
    WHERE status='active' AND scope NOT LIKE '%/%' GROUP BY 1 ORDER BY 2 DESC;"
```

Un atome rangé sur `travail` (une **racine**) au lieu de `travail/strategie` (une
**feuille**) existe en base, et il peut encore remonter sur une question qui lui ressemble.
Mais il est exclu de tout ce que le cerveau construit **au-dessus** du rangement : pas
d'état courant, pas de place dans la vue des scopes, pas de comptage dans la couverture.
Et une recherche qui précise un domaine ne le trouvera jamais — l'égalité de scope est
stricte. C'est un souvenir orphelin : présent, et hors de la vie du cerveau. Rien ne fait
de bruit.

Sur le cerveau de référence, **près d'un souvenir actif sur onze est tombé dans ce piège**,
et personne ne s'en est aperçu pendant des mois. Le cockpit dit la chose quand elle se
produit :

```
  Attention : 3 atome(s) de la fenêtre ont été posés sur la racine travail,
  où le rappel ne les verra jamais.
```

*(La phrase du cockpit exagère, comme son étiquette « Savoir invisible au rappel » : ces
atomes-là restent rappelables par similarité pure. Ce qu'elle signale est juste — ils sont
hors de tout ce que le cockpit affiche. Le libellé du produit n'a pas encore été repris.)*

**Au jour 7, cette dette se corrige en quelques minutes ; au mois 6, elle représente des
centaines d'atomes et un travail de reclassement.** C'est la raison pour laquelle cette
vérification est le geste du jour 7, et pas du jour 180.

## Pourquoi la confiance reste basse, et pourquoi c'est bon signe

Chaque rappel porte une confiance, et sur le cerveau de référence **96 % des rappels sont
rendus en confiance basse**. Au jour 7, ce sera 100 %.

Un système qui vous répondrait « j'en suis sûr » avec quarante atomes en base serait un
menteur.

**Et cette confiance-là ne montera pas.** Il faut le dire nettement, parce que c'est
contre-intuitif : la confiance d'un atome est une propriété de sa **naissance**, pas un
score qui s'affine à l'usage. Elle est absente du schéma de modification de l'API, et la
supersédure l'hérite de l'atome remplacé — un atome né `agent_suggest` le reste, y compris
après que vous en avez réécrit la valeur. Rien, dans le système d'aujourd'hui, ne promeut
un atome en `auditor_validated`. Le cockpit ne le peut pas non plus : sa seule route
non-GET est la connexion, et son rôle PostgreSQL ouvre toutes ses transactions en lecture
seule. **Il n'y a pas de rituel hebdomadaire de validation, parce qu'il n'y a rien à
cliquer.** C'est déclaré comme un chantier dans [`ROADMAP.md`](ROADMAP.md), §2.4 : la
validation devra passer par une route d'écriture **hors** du cockpit, qui reste en lecture
stricte par conception. C'est un choix d'architecture à faire, pas un bouton à ajouter.

Ce que vous pouvez faire, en revanche, est réel, et c'est le geste du mois.

### Corriger ce qui est faux

Le cerveau extrait ; il se trompe parfois. Trois gestes existent, tous par l'**API** —
aucun par le cockpit. Le tunnel ouvert, depuis votre machine : l'API **exige son jeton**,
boucle locale comprise, comme au premier jour. Relevez-le dans votre coffre
(`sudo grep '^ARAC_API_BEARER_TOKEN=' "/etc/arac/$BASE/arac.env"`) et posez-le dans
`JETON` ; chaque appel ci-dessous le porte.

```bash
# 1. Remplacer un atome faux par une version juste. L'ancien passe en
#    `superseded` et pointe vers le nouveau : rien n'est effacé.
curl -s -X POST http://127.0.0.1:$API/v1/atoms/<id>/supersede \
     -H "Authorization: Bearer $JETON" \
     -H 'Content-Type: application/json' \
     -d '{"new_value": "la formulation juste",
          "new_node_id": "<votre-node-id>",
          "new_rationale": "corrigé à la relecture du mois 1"}'

# 2. Retoucher sans versionner : valeur, étiquettes, justification, score.
curl -s -X PATCH http://127.0.0.1:$API/v1/atoms/<id> \
     -H "Authorization: Bearer $JETON" \
     -H 'Content-Type: application/json' \
     -d '{"rationale": "pourquoi cet atome existe"}'

# 3. Retirer du rappel un atome qui n'aurait jamais dû exister.
#    C'est une ARCHIVE (status='archived'), pas une suppression.
curl -s -X DELETE http://127.0.0.1:$API/v1/atoms/<id> \
     -H "Authorization: Bearer $JETON"
```

**Ce que ces trois gestes ne font pas**, et c'est la moitié utile de l'information : ils
ne touchent ni `confidence`, ni `audit_source`, ni la calibration du rappel. La
calibration est un fichier **gelé et versionné** (`app/context/r3_calibration.json`) ; le
moteur refuse au démarrage toute calibration dont la version diffère de celle qu'il
attend. On ne « met pas à jour » une calibration en douce — voir
[`CONCEPTS.md`](CONCEPTS.md).

**Où trouver quoi corriger.** Le cockpit sait vous les montrer, même s'il ne sait pas les
changer : la page d'un domaine liste ses atomes **fragiles** — ceux dont le score de
confiance passe sous le seuil de fragilité, et ceux qui n'ont pas de score du tout. La
page rappelle le seuil qu'elle applique ; ne le recopiez pas d'ici, lisez-le là-bas.

```
GET /cc/v1/scopes/travail/strategie      → bloc « confidence », liste « fragile »
```

C'est aussi le moment de savoir ceci : **98 % du savoir du cerveau de référence n'a jamais
été audité.** Un atome extrait par un modèle et jamais relu par un humain reste une
hypothèse bien rangée. Rien, dans le système, ne vérifie automatiquement qu'un savoir est
encore vrai — les colonnes prévues pour ça ne sont alimentées par rien. C'est à vous, et
c'est déclaré comme tel.

## Ce qu'il ne faut surtout pas faire au jour 7

**Ne remaniez pas votre taxonomie.** Vous n'avez pas assez d'atomes pour savoir laquelle de
vos feuilles est mal née. Une feuille vide au jour 7 ne prouve rien ; une feuille vide au
mois 6 prouve quelque chose. Attendez le jour 30, puis appliquez la règle : une feuille
sous **10 atomes en six mois** n'aurait pas dû exister ; une feuille au-dessus de **250**
gagnerait à être scindée.

---

# Jour 30 — le cerveau commence à anticiper

## Ce que vous voyez

Un mois, quatre-vingt-dix cycles. Le bandeau ressemble enfin à celui d'un système en
service :

```
  Depuis 24 heures, j'ai appris 6 conversation(s) et créé 8 atome(s) de savoir.
  Le projet migration-serveur progresse : 4 atome(s) de plus depuis 24 heures.
  Le domaine outillage/serveur est celui qui s'est le plus enrichi : 5 atome(s)
  créé(s) depuis 24 heures.
  2 atome(s) ont été remplacés depuis 24 heures : j'ai changé d'avis.
  J'ai servi 14 rappel(s) depuis 24 heures.
  312 atome(s) actifs n'ont jamais été servis à personne : ce savoir dort.
```

## Ce qui a changé, et qu'on ne voit pas dans les chiffres

Trois choses arrivent autour du trentième jour, et aucune n'est un compteur.

**1. Le rappel devient contextuel.** À quelques centaines d'atomes, une question sur un
sujet travaillé rend des réponses *dont vous aviez oublié l'existence*. C'est le premier
moment où le cerveau vous apprend quelque chose sur vous plutôt que de vous répéter ce que
vous saviez déjà.

**2. `context_for` devient l'appel intéressant.** Là où `/v1/atoms/recall` répond à une
question, `POST /v1/atoms/context_for` répond à un **contexte** : il ajoute aux résultats
thématiques vos atomes « pierres angulaires », sélectionnés par étiquette et non par
distance, donc **toujours présents quelle que soit la question**. C'est la route à appeler
avant d'écrire du code : elle rend le thème *et* la doctrine.

**3. « j'ai changé d'avis » apparaît.** Un atome remplacé, c'est le cerveau qui reconnaît
une décision antérieure et la met à jour au lieu d'en empiler une seconde. L'ancienne n'est
pas supprimée : elle est marquée `superseded` et conservée — le rôle applicatif PostgreSQL
n'a même pas le droit de `DELETE`. Vous pouvez donc toujours savoir ce que vous pensiez
avant.

**Ce qui n'arrive pas, et n'arrivera pas :** le cerveau ne vous dira **jamais** « ceci
contredit cela ». Si vous décidez X en mars et l'inverse en septembre, il gardera les deux,
les rendra tous les deux comme voisins de votre question, et ne vous préviendra pas. Aucun
mécanisme n'en produit. C'est la limite la plus importante du système et elle est déclarée
en première page du [`README`](../README.md#a-le-graphe-de-liens-est-écrit-mais-jamais-servi--et-il-ne-porte-aucun-sens).

## Combien d'atomes au bout d'un mois

| Ce que vous comptez | Verdict | Explication |
|---|---|---|
| **~150** | ✅ l'ordre de grandeur observé | ~5 par jour, en régime établi |
| **250 à 500** | ✅ normal aussi | votre historique a été digéré en plus du courant |
| **60 à 100** | ✅ acceptable | vous parlez moins, ou vos conversations sont plus opérationnelles que décisionnelles |
| **moins de 30** | ❌ anormal | quelque chose ne va pas : voir le tableau ci-dessous |

Ces chiffres viennent **d'un seul cerveau, observé huit mois.** Ce sont des mesures, pas
des promesses, et les vôtres différeront. Ce qui ne différera pas, c'est l'ordre de
grandeur : on ne produit pas mille atomes par mois, et un cerveau qui en produirait mille
retiendrait surtout du bruit.

**Et le repère qui compte vraiment : le rappel devient réellement utile vers quelques
centaines d'atomes**, soit deux à quatre mois pour la plupart des gens. Le jour 30 est le
moment où vous *sentez* que ça arrive, pas celui où c'est arrivé.

## Le savoir dormant

```
  312 atome(s) actifs n'ont jamais été servis à personne : ce savoir dort.
```

Au premier mois, c'est **normal** : vous interrogez peu, et le cerveau retient beaucoup. Un
grand nombre d'atomes dormants n'est pas un défaut de qualité, c'est la définition d'une
mémoire — l'essentiel de ce que vous savez ne vous sert pas aujourd'hui.

Cette phrase devient intéressante au troisième mois : si elle ne baisse **jamais** en
proportion, c'est que vous n'utilisez pas le rappel, et un cerveau qu'on n'interroge pas est
une dépense.

## La file qui ne se résorbe jamais

```
  La file grandit : 41 conversation(s) reçue(s) depuis 24 heures
  pour 12 entièrement curée(s).
```

Au jour 1, c'est du rattrapage d'historique. **Au jour 30, si la file grandit encore, c'est
une alarme** : votre débit de conversations dépasse durablement la capacité de digestion.
Deux réponses, dans cet ordre :

1. **augmenter le budget** — `ARAC_PACK_TOKEN_BUDGET` (défaut 80 000, plafond dur
   135 000) et `ARAC_PACK_MAX_CONVS`. Cela **augmente la facture** proportionnellement ;
2. **ajouter un créneau de digestion** — un cycle de plus par jour, soit environ
   +87 000 jetons par jour.

Vous verrez la phrase inverse quand ça va mieux :

```
  La file se résorbe : 19 conversation(s) entièrement curée(s) depuis 24 heures
  pour 6 reçue(s).
```

## Le geste du jour 30

Un seul, et il ne prend pas dix minutes : **relisez votre taxonomie avec un mois de données
sous les yeux.**

```bash
psql "$DSN_RO" -c \
  "SELECT scope, count(*) FROM arac.memory_atoms
    WHERE status='active' GROUP BY 1 ORDER BY 2 DESC;"
```

- une feuille à **0 ou 1 atome** en un mois : elle est probablement mal née. Ne la
  supprimez pas encore — attendez le mois 6 et la règle des 10 atomes ;
- une feuille qui a **avalé la moitié du corpus** : elle est trop large, et le filtrage par
  domaine ne sert plus à rien. C'est le bon moment pour la scinder ;
- **n'importe quelle racine avec un compte > 0** : corrigez. Ces atomes ne comptent dans
  aucun état courant et dans aucune couverture, et ils grossissent une dette que
  l'anti-dérive finira par vous signaler (`W-STATE-007`, à partir de vingt atomes actifs
  sur une même racine nue).

C'est la seule décision structurante du premier mois, et vous avez maintenant de quoi la
prendre — ce qui n'était pas le cas au jour 7.

## Normal ou cassé — le tableau du mois

| Ce que vous voyez | Normal | Cassé |
|---|---|---|
| aucun atome créé depuis 6 h | ✅ entre deux cycles, un cerveau accumule | |
| un cycle qui ne rend rien | ✅ 36 % le font | |
| quatre cycles ratés d'affilée | | ⚠️ `scripts/ops/alerts.py` tranche selon *votre* taux |
| aucun atome depuis 48 h **et** la file n'est pas vide | | ❌ six cycles stériles d'affilée — identifiants de poste |
| « j'ai dépensé N jetons sans retenir un seul atome » | | ❌ vous payez pour rien |
| 96 % des rappels en confiance basse | ✅ le cerveau doute, et le dit | |
| beaucoup d'atomes qui « dorment » | ✅ au premier mois | ⚠️ au troisième, si ça ne bouge pas |
| une métrique `unavailable` dans le cockpit | ✅ une absence n'est pas un zéro | |
| une métrique à `0` là où la donnée manque | | ❌ c'est un bug — signalez-le |
| **rien n'entre depuis 26 h** | | ❌ la panne la plus sournoise : la digestion continue, les compteurs bougent, tout *paraît* normal |
| des atomes sur une racine nue | | ❌ hors de l'état courant, de la vue des scopes et de la couverture — re-rangez-les sous une feuille |
| la file grandit encore au jour 30 | | ❌ capacité de digestion insuffisante |

**La panne la plus sournoise mérite un mot de plus.** Quand le pont s'arrête — tunnel
fermé, clé SSH expirée, `launchd` désarmé après une mise à jour du système — le cerveau
continue de digérer ce qu'il a déjà reçu. Les cycles aboutissent, des atomes se créent, le
bandeau parle. Pendant deux ou trois jours, **rien ne signale que plus rien n'entre**.
C'est pour cela que « quand le cerveau a-t-il reçu son dernier message ? » est la première
question à poser, et pas la dernière.

---

## Ce qui a été vérifié pour écrire ce document, et ce qui ne l'a pas été

**Lu dans le code de ce dépôt** — les phrases du cockpit, leurs conditions d'émission et
leur ordre de priorité viennent de `control_center/cc_v1/today.py` (`NARRATIVE_TEMPLATES`,
`SENTENCE_RULES`, `_P`, `MAX_SENTENCES = 6`). Les gardes de digestion viennent de
`agents/cortex/pack.py` (`DEFAULT_PACK_TOKEN_BUDGET = 80_000`,
`PACK_TOKEN_BUDGET_HARD_CAP = 135_000`, `DEFAULT_MAX_CONVERSATIONS = 20`,
`RECOMMENDED_PACK_MAX_CONVS = 4`). Les routes citées ont été relevées dans
`app/routers/atoms.py` (`/v1/atoms/recall`, `/v1/atoms/context_for`),
`control_center/cc_v1/entities.py` et `control_center/cc_v1/lifestory.py`
(`/cc/v1/atoms`, `/cc/v1/atoms/{id}/story`, `/cc/v1/conversations/{uid}`).

**Mesuré sur le cerveau de référence**, observé huit mois — les pourcentages et les ordres
de grandeur : près d'un souvenir actif sur onze posé sur une racine (~9 % — le compte du
jour et sa requête sont au § 3 de
[`COMMENT-IL-CREE-SES-SCOPES.md`](COMMENT-IL-CREE-SES-SCOPES.md), seul endroit du dépôt
qui porte ce chiffre), 76 % de provenance perdue, 36 % de
cycles en quarantaine, ~87 000 jetons par cycle et ~31 500 par atome, 96 % de rappels en
confiance basse, 98 % de savoir jamais audité, ~150 atomes par mois, 3 cycles par jour.
**Ce sont des observations sur une seule installation.**

**Jamais exécuté** — et il faut le dire : *aucune* des séquences de ce document n'a été
jouée sur une installation neuve. Les bandeaux ci-dessus sont **reconstruits** à partir des
gabarits que le code imprime réellement, remplis de valeurs plausibles. La progression
jour 1 → jour 30 est une reconstitution informée, pas un journal de bord.

**Si vous êtes la première personne à vivre ce premier mois, tenez ce journal de bord** —
ce que vous avez vu et qui n'est pas écrit ici, ce qui est écrit ici et que vous n'avez pas
vu, et surtout le jour où vous avez failli arrêter. C'est la contribution la plus utile
qu'on puisse faire à ce dépôt. [`CONTRIBUER.md`](CONTRIBUER.md) dit comment la remonter.

---

## Et après le premier mois

| | |
|---|---|
| le détail opératoire du tout premier jour | [`PREMIER-JOUR.md`](PREMIER-JOUR.md) |
| quelque chose ne marche pas | [`DEPANNAGE.md`](DEPANNAGE.md) — classé par symptôme |
| comprendre ce qui vient de se passer | [`CONCEPTS.md`](CONCEPTS.md) et [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| surveiller un cerveau en service | [`EXPLOITATION.md`](EXPLOITATION.md) |
| dormir tranquille | [`SAUVEGARDE.md`](SAUVEGARDE.md) |
| ce qui manque encore, et n'est pas promis | [`ROADMAP.md`](ROADMAP.md) |

**Revenez lire ce document au jour 30.** Vous verrez qu'il ne mentait pas — dans les deux
sens.
