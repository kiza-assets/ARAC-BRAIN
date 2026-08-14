# Le premier jour — la naissance d'un cerveau

L'installation est finie. Les services tournent. Le cockpit s'ouvre. Et il ne dit rien :

```
  Le cerveau n'a rien appris depuis 24 heures.
  Personne ne m'a rien demandé depuis 24 heures : aucun rappel servi.
```

**Ce document raconte les vingt-quatre heures qui suivent.** Il n'est pas une
procédure — l'installation a la sienne, [`INSTALLATION.md`](INSTALLATION.md) — c'est le
récit de ce que vous allez voir, dans l'ordre où vous allez le voir, avec les endroits
où vous croirez que quelque chose est cassé alors que tout va bien.

---

## Lisez ceci avant tout le reste

**Le premier jour, votre cerveau sera décevant.** Pas « perfectible » : décevant. Vous
lui poserez une question, il rendra trois souvenirs à moitié pertinents, avec une
confiance basse, et vous vous demanderez si tout cela valait une demi-journée
d'installation.

C'est le comportement attendu, et il a une cause simple : **un cerveau ne sait que ce
qu'il a digéré.** Le vôtre a digéré une poignée de conversations. Sur le cerveau qui a
servi de référence à ce dépôt, le rappel n'est devenu réellement utile que vers
**quelques centaines d'atomes** — soit, à la cadence observée d'environ **150 atomes par
mois**, entre **deux et quatre mois** d'usage.

Il y a donc deux façons de vivre ce premier jour :

| Si vous attendez… | Vous obtiendrez… |
|---|---|
| une mémoire qui répond juste dès ce soir | une déception, et un serveur désinstallé dans la semaine |
| **la preuve que la chaîne fonctionne de bout en bout** | exactement ça — et c'est le seul objectif raisonnable aujourd'hui |

**L'objectif du premier jour est de voir un souvenir naître d'une conversation
réelle et de remonter jusqu'à elle.** Un seul. S'il naît, la machine est bonne ; le
reste n'est plus qu'une question de temps et de conversations.

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

## Le déroulé, en un coup d'œil

| | Ce que vous faites | Durée | Ce que vous obtenez |
|---|---|---|---|
| **1** | la première synchronisation | 10–40 min | des messages bruts sur le serveur |
| **2** | le premier cycle de digestion | 3–20 min | des atomes, ou une leçon |
| **3** | le premier souvenir | 10 min | la preuve que la chaîne tient |
| **4** | la première question | 5 min | une réponse médiocre, et sa raison |
| **5** | la première semaine | — | de la patience, informée |

---

## 1. La première synchronisation — vos conversations quittent votre machine

### Ce qui se passe

Sur votre machine, tunnel SSH ouvert :

```bash
./arac-pont.sh premiere-synchro
```

Le pont vous annonce le trajet avant de le parcourir — inventaire, tunnel, annonce,
accord, envoi, rapport — puis il s'arrête net à l'étape 3 pour vous montrer ce qui
partirait :

```
  CE QUI VA PARTIR DE CETTE MACHINE
  ────────────────────────────────────────────────────────────────────

  34 conversation(s), 2 118 message(s) au total.

   messages  dernière activité   source        conversation
   ──────────────────────────────────────────────────────────────────
        214  2026-08-04 18:22    claude_code   migration du serveur de prod…
        118  2026-08-04 09:41    claude_code   refonte de la facturation
         96  2026-08-03 21:07    claude_code   pourquoi ce test est flaky
   …

  « +N » = N messages déjà acquittés par le serveur, qui ne repartiront pas.
```

Puis, seulement ensuite : `Envoyer ? [o/N]`.

**Ce point d'arrêt n'est pas une politesse.** Ces conversations contiennent une vie —
des noms, des chiffres, peut-être des choses que vous ne vous rappelez pas y avoir
écrites. Vous devez voir ce qui part avant que ça parte. C'est la seule fois où on vous
le demandera : une fois `./arac-pont.sh automatiser` lancé, la synchronisation devient
horaire et silencieuse.

### Ce que vous devez voir à la fin

```
  RAPPORT
  ────────────────────────────────────────────────────────────────────
  trouvées sur le disque    34
  déjà connues, ignorées    0
  tentées                   34
  acceptées entièrement     34
  en échec                  0

  messages envoyés          2118
  messages insérés          2118
  messages déjà connus      0  (déduplication serveur)
```

### Combien de temps

Quelques minutes pour un historique modeste, jusqu'à une demi-heure pour plusieurs
milliers de messages. Le facteur limitant est le tunnel, pas le serveur : chaque
conversation part en un appel, et le serveur déduplique message par message.

**Relancer ne coûte rien.** Si la synchronisation s'interrompt — veille du Mac, tunnel
coupé, réseau —, relancez : ce qui est déjà passé sera compté dans `déjà connus`, pas
réenvoyé.

### Si rien ne remonte

Trois pannes, et une seule est grave. Le pont les distingue par son code de sortie :

| Code | Ce qu'il dit | Ce que ça veut dire | Le geste |
|---|---|---|---|
| **3** | aucune source de conversations trouvée | il n'y a rien à envoyer sur ce disque | `python3 ~/.arac/<votre_base>/arac-sync.py --inventaire` : il vous dit **où** il a cherché |
| **5** ou **7** | rien n'est passé | le tunnel est fermé, ou l'API n'écoute pas | `./arac-pont.sh etat`, puis `systemctl status arac-<votre_base>-api` |
| **4** | le serveur a refusé ce poste | **votre `node_id` n'est pas déclaré en base** | ci-dessous |

**Le code 4 est celui qu'il faut connaître par cœur.** Le serveur refuse toute
conversation venant d'un poste qu'il ne connaît pas — c'est ce garde-fou qui l'empêche
d'avaler n'importe quoi. Mais un `ARAC_NODE_ID` qui diffère d'un caractère entre votre
machine et le serveur produit exactement le même symptôme qu'une panne réseau : **rien
n'arrive, et rien ne crie.**

Le poste doit passer **deux** portes, et il faut vérifier les deux :

```bash
# 1. la liste blanche — fail-closed : si la variable est absente, TOUT est refusé
grep ARAC_INGEST_ALLOWED_NODES /etc/arac/<votre_base>/arac.env

# 2. le poste est-il déclaré en base ? (clé étrangère sur arac.nodes)
psql "$DSN_RO" -c "SELECT node_id, role, account, active FROM arac.nodes;"

# 3. sous quel nom se présente-t-il, côté machine ?
grep ARAC_NODE_ID ~/.arac/<votre_base>/pont.conf
```

Les trois chaînes doivent être **identiques**, à la casse près. Si elles divergent, le
symptôme est net : l'API répond **403**, rien n'entre, et vous le voyez dans la réponse
du pont — pas six heures plus tard.

> **Une quatrième valeur existe, et elle est normale.** L'unité systemd du cycle tourne
> sous `<votre-node-id>-cycle` — c'est écrit tel quel par le bootstrap
> (`bootstrap/lib/services.sh`), et vous le verrez dans
> `systemctl cat arac-<votre_base>-cycle.service`. C'est voulu : le cycle **n'ingère
> rien**, il ne franchit jamais la liste blanche ; ce suffixe sert à distinguer ce qu'il
> produit de ce que le pont dépose. Ne l'ajoutez pas à
> `ARAC_INGEST_ALLOWED_NODES` : les trois chaînes à comparer sont bien celles ci-dessus.

> **Ne confondez pas ce problème-ci avec la quarantaine.** L'identifiant de poste
> gouverne l'*entrée* : quand il est faux, rien n'arrive. La quarantaine, elle, frappe
> beaucoup plus loin dans la chaîne, sur des messages **déjà arrivés**, et pour une
> raison entièrement différente — voir *Si le cycle ne produit rien*.

### Le cas particulier de Claude Desktop

**Il n'existe aucune capture automatique de Claude Desktop.** L'application ne conserve
rien de lisible en local. Si vos conversations les plus précieuses sont là, la seule
voie est l'**export officiel de claude.ai** — manuel — déposé dans
`~/.arac/<votre_base>/export-desktop/`. Claude Code (CLI), lui, est capté automatiquement depuis
`~/.claude/projects/`.

Ce n'est pas un oubli, c'est une frontière du produit, et elle est détaillée dans
[`PONT-MAC.md`](PONT-MAC.md). Sachez-le maintenant plutôt qu'en cherchant pourquoi votre
cerveau ignore la moitié de votre vie.

---

## 2. Le premier cycle — un cerveau au repos n'est pas un cerveau en panne

### Ce qui vient d'arriver n'est pas encore de la mémoire

Vos 2 118 messages sont sur le serveur, dans la base, et le cockpit ne montre **aucun
souvenir**. C'est normal : ce sont des messages bruts. Entre le message brut et l'atome,
il y a un modèle de langage qui lit, décide et propose — et ça, ça se paie et ça se
planifie.

**Le cerveau digère par cycles, pas en continu.** Trois par jour sur l'installation de
référence : **04:00, 13:00, 21:00**. Entre deux cycles, il accumule. Ce que vous dites à
14 h n'est pas mémorisé à 14 h 01 ; il le sera à 21 h.

C'est un choix, pas une limite technique :

- **le coût** — un cycle consomme environ **87 000 jetons** et produit environ un atome
  tous les **31 500 jetons**. Digérer en continu multiplierait la facture sans améliorer
  la mémoire ;
- **le regroupement** — un modèle qui lit dix conversations d'un coup voit des liens
  qu'il ne verrait pas en les lisant une par une ;
- **la lisibilité** — trois rendez-vous par jour font une vie observable. Un flux continu
  ne se surveille pas.

### Forcer un cycle, pour voir

Personne n'attend 21 h le jour de l'installation. Sur le serveur :

```bash
sudo systemctl start arac-<votre_base>-cycle.service
journalctl -u arac-<votre_base>-cycle.service -f
```

Le service est un `oneshot` : il démarre, travaille, s'arrête. Il n'a **pas** de section
`[Install]` — il est déclenché par sa minuterie ou par vous, jamais « activé ». Son
délai de garde est de **1 200 secondes** : *un cycle qui dure vingt minutes est un cycle
qui a mal tourné.*

Ce que vous voyez passer dans le journal : la constitution d'une tranche de
conversations, l'appel de curation, les candidats proposés, le passage du filtre de
valeur, et l'écriture des atomes retenus.

### Ce que vous devez voir ensuite, dans le cockpit

```
  Depuis 24 heures, j'ai appris 5 conversation(s) et créé 9 atome(s) de savoir.
  Le domaine travail/strategie est celui qui s'est le plus enrichi : 4 atome(s).
  J'ai dépensé 87 400 jetons depuis 24 heures, soit 9 711 jetons par atome retenu.
```

**Neuf atomes pour trente-quatre conversations, ce n'est pas un échec.** C'est le taux
normal. L'essentiel d'une conversation n'est pas du savoir durable : c'est du contexte,
des tâtonnements, des politesses. Le rapport entre 87 000 jetons lus et 31 500 jetons
par atome produit dit exactement cela — **la plupart de ce qui est lu ne mérite pas
d'être retenu**, et c'est le travail du cerveau de le décider.

### Si le cycle ne produit rien

Un cycle stérile est banal : **36 % des cycles du cerveau de référence** se sont terminés
sans un seul atome. Vérifiez, dans cet ordre :

1. **Les DEUX interrupteurs sont-ils ouverts ?** Ils sont fermés sur un cerveau neuf, et
   c'est **le premier suspect, toujours**. `ARAC_ALLOW_PAID_AI=1` dans le coffre ne suffit
   pas : `arac_config.paid_ai_enabled` vit **en base** et ne s'arme que par
   `sudo .venv/bin/python -m agents.lib.paid_ai_control arm --confirm --coffre <coffre>`.
   La commande qui répond aux deux d'un coup, sans rien dépenser :
   `… paid_ai_control status --coffre <coffre>` — sa première ligne dit
   `env_allow=` et `config=`, et sa ligne `Curation (binaire):` dit si le Claude Code CLI
   est là. (Deux autres freins peuvent aussi retenir un cycle : le plafond
   `ARAC_PACK_TOKEN_BUDGET` et le garde-dépense `agents/lib/spend_guard.py`.)
2. **Les messages sont-ils bien arrivés ?**
   `SELECT count(*) FROM arac.raw_messages;` et
   `SELECT node_id, count(*) FROM arac.conversations GROUP BY 1;` — si c'est zéro, le
   problème est à l'étape 1, pas ici.
3. **Le cycle est-il parti en quarantaine ?**
   `SELECT status, count(*) FROM arac.run_receipts GROUP BY 1;`
4. **La clé de curation est-elle valide ?**
   `journalctl -u arac-<votre_base>-cycle.service -n 100` — quota, clé, quantité.

#### La quarantaine, et la vraie leçon des 36 %

C'est le point 3 qui mérite qu'on s'y arrête, parce que la cause qu'on devine
spontanément est la mauvaise.

Le cycle sert au modèle de curation un **paquet** : des messages, chacun portant un
identifiant. Le modèle rend un document JSON où chaque atome proposé doit **citer les
identifiants des messages qui le prouvent**. Le contrat de sortie vérifie que ces
identifiants appartiennent bien au paquet servi. Quand le modèle en cite un qui n'y est
pas — un message d'une autre conversation, un identifiant hors de la tranche —, **tout
le cycle part en quarantaine**. Pas l'atome fautif : le cycle entier. Aucun sauvetage
partiel.

Sur le cerveau de référence, **c'est cela, et non le volume, qui explique les 36 % de
cycles stériles**. L'hypothèse de départ — « mes tranches sont trop grosses » — était
fausse, et on ne l'a su qu'en lisant les corps mis en quarantaine.

Deux choses à en retenir, dans cet ordre :

- **La règle est dure exprès.** Un souvenir dont la provenance est fausse est pire
  qu'un souvenir manquant : il est indéfendable au moment où vous voudrez le vérifier.
  Le système préfère perdre un cycle payé plutôt qu'écrire une preuve inventée. C'est
  la même doctrine que le `DELETE` interdit et que les reçus rejouables.
- **Le bon geste n'est pas de réduire la tranche.** Réduire ne change rien à un
  désaccord d'identifiants — et sur le cerveau de référence, cela a produit une
  oscillation qui repayait le même cycle. Le geste utile est de lire le corps mis en
  quarantaine : il est **conservé en base et borné en taille**, exactement pour ça.
  Sans lui, la cause était introuvable.

Corollaire pratique : **quand un chiffre d'exploitation vous surprend, allez lire les
lignes avant de formuler une hypothèse.** Ce paragraphe existe parce que l'hypothèse
plausible a coûté un tiers d'un budget d'extraction.

Et si la file d'attente est vide et que rien n'est arrivé depuis, `scripts/ops/alerts.py`
ne lèvera rien du tout : il dira « le cerveau se repose ». **L'état de repos est un état
normal, et il est affiché comme tel plutôt que déguisé en incident.**

---

## 3. Le premier souvenir — le moment qui compte

C'est ici que le premier jour se joue. Pas dans une métrique : dans un atome que vous
ouvrez, que vous lisez, et dont vous remontez l'origine jusqu'à la phrase qui l'a
produit.

### Le trouver

Ouvrez le cockpit (`http://127.0.0.1:<le port cockpit>`, tunnel ouvert — le port est
attribué à votre installation, il se relève à l'étape 5 de
[`DEMARRAGE-RAPIDE.md`](DEMARRAGE-RAPIDE.md)), puis la liste des atomes.
En dessous de l'interface, c'est cette route qui répond — vous pouvez l'appeler
directement, elle rend du JSON :

```
GET /cc/v1/atoms                    tous, les plus récents d'abord
GET /cc/v1/atoms?scope=travail/strategie
GET /cc/v1/atoms/{id}               la fiche
```

Prenez le plus récent. Vous verrez quelque chose comme :

```
  clé          serveur-prod-version
  valeur       Le serveur de production tourne PostgreSQL 16.13.
  domaine      outillage/serveur
  nature       state                (l'état courant de quelque chose)
  confiance    agent_suggest        (proposé par le curateur, non validé par vous)
  créé le      2026-08-06 21:04
```

**Lisez la valeur.** Ce n'est pas un extrait de votre conversation : c'est ce que votre
conversation a permis de conclure. La phrase que vous aviez écrite a disparu ; ce qui
reste est l'affirmation. C'est toute la différence entre archiver et se souvenir.

### Ouvrir son histoire

```
GET /cc/v1/atoms/{id}/story
```

Une seule requête, et le cockpit répond à quatre questions qu'aucun compteur ne sait
poser : **d'où vient ce souvenir, qui l'a corrigé, qui s'en sert, depuis quand.** Vous y
trouverez :

- **la naissance** — le cycle (`run_ref`) qui l'a produit et la conversation
  (`conversation_uid`) dont il est né ;
- **la chronologie** — création, réécritures, remplacements, rappels servis ;
- **les voisins** — les atomes sémantiquement proches, avec cette mise en garde servie
  dans la réponse elle-même : *« un voisin n'est pas un lien : c'est une ressemblance
  calculée »* ;
- **l'`evidence`** — le SQL réellement exécuté, paramètres substitués, sur une ligne.
  Vous pouvez le coller dans `psql` et contredire le cockpit. Un cockpit qu'on ne peut
  pas contredire ne mérite pas d'être cru.

Deux blocs vous répondront `state: "unavailable"` avec leur raison. **Une absence de mesure
ne s'affiche jamais comme un zéro.** Un zéro se lit « c'est nul » ; une indisponibilité se
lit « on ne sait pas ». Ce ne sont pas les mêmes nouvelles.

Les deux ne disent d'ailleurs pas la même chose :

- `verification` — `last_verified_at` et `confirmed_until` ne sont alimentés par rien.
  Rien ne tourne derrière : c'est une vraie absence.
- `links` — **attention au contresens** : cela ne veut pas dire que la table de liens
  manque. Elle existe sur votre installation et le cycle la remplit. Cela veut dire que
  **cette vue ne lit pas son contenu** — et personne d'autre non plus, pas même le rappel.
  Ce que ces liens valent, et pourquoi ils ne sont pas encore servis, est au maillon ⑩ de
  [`ARCHITECTURE.md`](ARCHITECTURE.md).

### Remonter à la conversation

Dans l'histoire, la provenance porte un lien :

```
GET /cc/v1/conversations/{conversation_uid}
```

Et là, vous relisez la conversation d'où ce souvenir est né. **C'est le moment que ce
document tout entier existe pour vous faire atteindre.** Une phrase que vous avez écrite
un mardi soir est devenue une affirmation rangée dans un domaine, retrouvable sans que
vous vous rappeliez l'avoir écrite. La chaîne complète — machine, tunnel, ingestion,
curation, atome, embedding, cockpit — vient de se prouver sur un cas réel. (Cet ordre
n'est pas une coquille : l'embedding vient **après** l'atome, et porte sur lui. Le
message que vous venez de relire, lui, n'a jamais eu de vecteur.)

### Si la provenance manque

Vous verrez peut-être, à la place :

```
  state       unavailable
  reason      cet atome ne déclare aucune provenance de conversation
```

Ce n'est pas rare, et ce n'est pas votre faute : sur le cerveau de référence, **76 % de
la provenance a été perdue**. Cause : un changement du format de `source_ref` en cours de
route. Les atomes écrits avant le changement portent une clé que le code d'après ne sait
plus lire. Le lien atome ↔ conversation était pourtant intact au moment de l'écriture.

**La leçon, et elle vous concerne dès aujourd'hui : ne touchez pas au format de
`source_ref`.** C'est la structure la plus coûteuse à changer de tout le système, parce
qu'elle est la seule chose qui relie ce que le cerveau sait à l'endroit où il l'a appris.
Un souvenir sans provenance n'est pas faux — il est simplement impossible à vérifier, et
un savoir invérifiable finit par ne plus valoir grand-chose.

---

## 4. La première question — et pourquoi la réponse sera mauvaise

### Poser la question

Le tunnel ouvert, depuis votre machine. **L'API exige son jeton, y compris depuis la
boucle locale** — le tunnel SSH ne tient pas lieu d'authentification, parce qu'il ne dit
rien de *qui*, sur le serveur, atteint `127.0.0.1`. Posez-le une fois pour toutes dans le
terminal d'où vous lancez les commandes de cette page :

```bash
# sur le serveur, root uniquement — c'est votre coffre
sudo grep '^ARAC_API_BEARER_TOKEN=' "/etc/arac/$BASE/arac.env"

# puis, dans le terminal d'où vous appelez l'API
JETON=<la valeur relevée ci-dessus>
```

Chaque `curl` de cette page porte donc `-H "Authorization: Bearer $JETON"`.

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

```bash
curl -s -X POST http://127.0.0.1:$API/v1/atoms/recall \
     -H "Authorization: Bearer $JETON" \
     -H 'Content-Type: application/json' \
     -d '{"query": "quelle version de PostgreSQL tourne en production ?", "k": 5}' \
     | python3 -m json.tool
```

Ce qui se passe entre l'envoi et la réponse : votre phrase est envoyée au modèle
d'embeddings, qui rend **3 072 nombres** ; PostgreSQL compare ce vecteur à celui de
chaque atome actif par distance cosinus (index HNSW) et rend les `k` plus proches. **Vous
n'avez pas cherché des mots — vous avez cherché un sens.** Un atome qui dit « la base
tourne en 16.13 » remontera sans partager un seul mot avec votre question.

**Et notez ce que vous ne fouillez pas.** Les vecteurs comparés sont ceux des **atomes**
— le texte de l'affirmation écrite par le curateur. Vos messages bruts n'ont pas de
vecteur, donc cette requête ne les visite jamais. Une chose que vous avez dite mais que
le curateur n'a pas retenue reste consultable par sa conversation, jamais par le sens.
C'est un arbitrage, pas un oubli : il rend le rappel net, et il vous rend responsable de
la qualité de ce que le curateur écrit.

Chaque atome rendu porte sa `distance` : **plus elle est basse, plus il est proche.**

Deux variantes existent, et il vaut mieux les connaître tout de suite :
`/v1/atoms/context_for` ajoute aux résultats thématiques vos atomes **pierres
angulaires** — sélectionnés par étiquette, jamais par distance, donc toujours présents
quelle que soit la question. C'est la route que Claude Code appelle avant d'écrire du
code. `/v1/atoms/recall_fresh` écarte les atomes périmés.

### Pourquoi la réponse sera mauvaise ce soir

**Parce qu'il n'y a rien dedans.** Neuf atomes ne font pas une mémoire. Le rappel
rendra les neuf, classés par distance, et les plus proches seront à peine pertinents —
non parce que la recherche est mauvaise, mais parce que la bonne réponse n'existe pas
encore.

Trois choses à savoir avant de conclure quoi que ce soit :

**a. Le cerveau doute, et il le dit.** Sur le cerveau de référence, **96 % des rappels
sont rendus en confiance basse**. Un système qui vous répondrait « j'en suis sûr » avec
neuf atomes en base serait un menteur.

> **Ce doute, vous ne pouvez pas encore le lever — et il faut le savoir dès ce soir.**
> La confiance d'un atome (`agent_suggest`, `producer`, `auditor_validated`) est fixée
> **à sa naissance** et ne change plus jamais : le champ est absent du schéma de
> modification de l'API, et la supersédure l'hérite de l'atome qu'elle remplace. Il n'y
> a donc aucun chemin, nulle part, pour promouvoir en `auditor_validated` un atome né
> `agent_suggest`. Le cockpit, lui, ne sait qu'afficher : sa seule route non-GET est la
> page de connexion, et son rôle PostgreSQL ouvre toutes ses transactions en lecture
> seule. **Il n'y a pas de bouton à trouver.** La boucle de validation est un chantier
> déclaré, pas un réglage caché : [`ROADMAP.md`](ROADMAP.md), §2.4.
>
> Ce que vous pouvez faire, en revanche, existe : remplacer la **valeur** d'un atome
> faux. Le geste est décrit dans [`PREMIER-MOIS.md`](PREMIER-MOIS.md), « Corriger ce qui
> est faux ». Cela corrige le savoir. Cela ne déplace pas la calibration, qui est un fichier
> gelé et versionné (`app/context/r3_calibration.json`) : le moteur refuse toute
> calibration dont la version diffère de celle qu'il attend.

**b. Un atome posé sur une racine devient orphelin.** `travail` est un conteneur ;
`travail/strategie` est un rangement. Un atome rangé sur `travail` existe en base, et il
peut encore remonter sur une question qui lui ressemble — mais il est exclu de tout ce que
le cerveau construit au-dessus du rangement : pas d'état courant, pas de place dans la vue
des scopes, pas de comptage dans la couverture. Et une recherche qui précise un domaine ne
le trouvera jamais, l'égalité de scope étant stricte. Sur le cerveau de référence, **près
d'un souvenir actif sur onze est tombé dans ce piège**, et personne ne s'en est aperçu
pendant des mois, parce que rien ne fait de bruit. C'est le piège numéro un.

```bash
# à lancer une fois par mois — le compte doit rester à zéro
psql "$DSN_RO" -c \
  "SELECT scope, count(*) FROM arac.memory_atoms
    WHERE status='active' AND scope NOT LIKE '%/%' GROUP BY 1 ORDER BY 2 DESC;"
```

**c. Le cerveau est confiant sur ce qu'il n'a jamais vérifié.** **98 % du savoir du
cerveau de référence n'a jamais été audité.** Un atome extrait par un modèle et jamais
relu par un humain reste une hypothèse bien rangée. Le cockpit vous montre lesquels ;
c'est à vous de trancher.

---

## 5. La première semaine — ce à quoi ça ressemble vraiment

### Ce qui se passe sans vous

Une fois `./arac-pont.sh automatiser` lancé, plus rien ne vous demande quoi que ce soit :
le tunnel se rouvre après une veille, la synchronisation part toutes les heures, la
digestion tourne trois fois par jour, la sauvegarde toutes les six heures.

**Vous n'avez rien à ranger, rien à taguer, rien à écrire.** C'est le contrat.

### Les ordres de grandeur observés

| | Ordre de grandeur | Ce qu'il faut en faire |
|---|---|---|
| atomes produits | **~150 par mois** | vers 5/jour. Le double le premier mois : votre historique est digéré. |
| cycles stériles | **~36 %** | banal. Six d'affilée, non — c'est alors une alarme. |
| jetons par cycle | **~87 000** | à comparer à votre facture au bout d'une semaine. |
| jetons par atome | **~31 500** | ce que coûte réellement un souvenir. |
| rappel utile à partir de | **quelques centaines d'atomes** | soit **2 à 4 mois**. |

Ces chiffres viennent d'un cerveau, un seul, le vôtre différera. Ce sont des mesures,
pas des promesses.

### La courbe, honnêtement

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

**Le creux du premier mois est le vrai risque du projet**, et il n'est pas technique :
la machine marche, elle n'a simplement rien à dire. C'est là que la plupart des gens
arrêtent — deux semaines avant que ça devienne intéressant.

### Les cinq gestes de la première semaine

| Quand | Geste | Pourquoi |
|---|---|---|
| **jour 1, le soir** | ouvrir un atome, lire son histoire, remonter à sa conversation | la seule preuve qui vaille |
| **jour 2** | `ops/backup.sh` puis `ops/restore_verify.sh` | une sauvegarde jamais restaurée est une hypothèse, pas une garantie |
| **jour 3** | `.venv/bin/python scripts/ops/health_check.py` | apprendre à quoi ressemble « normal » **avant** d'avoir un incident |
| **jour 4** | poser `ARAC_ALERT_CMD` et la **tester** | sans elle, personne n'est réveillé — les alertes vont au journal, en silence |
| **jour 7** | compter les atomes posés sur des racines (requête ci-dessus) | le piège n°1 se corrige en une semaine, pas en six mois |

> **Ces trois-là veulent le même préfixe que partout ailleurs** — `sudo
> ARAC_ENV_FILE=/etc/arac/$BASE/arac.env` — parce qu'ils lisent le coffre, qui est en
> `0700 root`. Sans lui, `health_check.py` rend « UNKNOWN » et `restore_verify.sh` annonce
> « Aucun dump » alors que le dump est là. Le § 1 d'[`EXPLOITATION.md`](EXPLOITATION.md)
> donne le préfixe une fois pour toutes, et ce qu'on lit quand on l'oublie.

Et une chose à ne **pas** faire la première semaine : remanier votre taxonomie. Vous
n'aurez pas assez d'atomes pour savoir laquelle de vos feuilles est mal née. Attendez le
premier mois, puis appliquez la règle : une feuille sous **10 atomes en six mois**
n'aurait pas dû exister ; une feuille au-dessus de **250** gagnerait à être scindée.

---

## 6. Normal, ou cassé ? — le tableau à garder sous la main

| Ce que vous voyez | Normal | Cassé |
|---|---|---|
| aucun atome créé depuis 6 h | ✅ entre deux cycles, un cerveau accumule | |
| aucun atome depuis 48 h **et** la file n'est pas vide | | ❌ six cycles stériles d'affilée |
| un cycle qui ne rend rien | ✅ 36 % le font | |
| quatre cycles ratés d'affilée | | ❌ `alerts.py` calcule si c'est explicable par *votre* taux |
| 96 % des rappels en confiance basse | ✅ le cerveau doute, et le dit | |
| une métrique `unavailable` dans le cockpit | ✅ une absence n'est pas un zéro | |
| une métrique à `0` là où la donnée manque | | ❌ c'est un bug — signalez-le |
| rien n'entre depuis 26 h | | ❌ la panne la plus sournoise : la digestion continue, tout *paraît* normal |
| au 2ᵉ passage : « Rien à envoyer : tout ce qui est ici est déjà dans votre cerveau. » | ✅ l'état est bien sauvegardé | |
| des messages qui repartent à chaque passage | | ❌ l'état ne se sauve pas — droits de `~/.arac` |

---

## 7. Ce qui a été vérifié pour écrire ce document, et ce qui ne l'a pas été

**Lu dans le code de ce dépôt** — les textes, les codes de sortie, les routes et les
chemins cités ici viennent des sources : `mac/arac-pont.sh`, `mac/arac-sync.py`,
`bootstrap/lib/services.sh`, `agents/cortex/cycle.py`, `app/routers/atoms.py`,
`app/auth.py`, `control_center/cc_v1/lifestory.py`, `control_center/cc_v1/entities.py`,
`agents/curator/gate.py`.

**Mesuré sur le cerveau de référence** — les pourcentages et les ordres de grandeur
(près d'un souvenir actif sur onze posé sur une racine — le compte du jour et sa requête
sont au § 3 de [`COMMENT-IL-CREE-SES-SCOPES.md`](COMMENT-IL-CREE-SES-SCOPES.md), seul
endroit du dépôt qui porte ce chiffre —, 76 % de provenance perdue, 36 % de cycles en
quarantaine, 87 000 et 31 500 jetons, 96 % de rappels en confiance basse, 98 % de savoir
non audité, ~150 atomes par mois, 3 cycles/jour). Ce sont **des observations sur une
seule installation.** Les vôtres différeront.

**Jamais exécuté** — et il faut le dire : *aucune* des séquences de ce document n'a été
jouée de bout en bout sur une installation neuve. La première synchronisation réelle
depuis un Mac, le premier cycle de digestion contre une vraie base, le premier rappel
avec de vraies clés d'API : **rien de tout cela n'a été observé.** Les blocs de sortie
ci-dessus sont reconstruits à partir des chaînes de caractères que le code imprime
réellement, avec des valeurs plausibles.

**Si vous êtes la première personne à vivre ce premier jour, notez chaque friction** —
ce que vous avez vu et qui n'est pas écrit ici, ce qui est écrit ici et que vous n'avez
pas vu. C'est le test d'installation à l'aveugle que [`GOAL.md`](../GOAL.md) appelle
**F8**, et c'est la dernière chose qui manque à ce framework.
[`CONTRIBUER.md`](CONTRIBUER.md) dit comment le remonter.

---

## Et après

| | |
|---|---|
| quelque chose ne marche pas | [`DEPANNAGE.md`](DEPANNAGE.md) — classé par symptôme |
| comprendre ce qui vient de se passer | [`CONCEPTS.md`](CONCEPTS.md) et [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| surveiller un cerveau en service | [`EXPLOITATION.md`](EXPLOITATION.md) |
| dormir tranquille | [`SAUVEGARDE.md`](SAUVEGARDE.md) |
| ce qui manque encore | [`ROADMAP.md`](ROADMAP.md) |

**Revenez lire ce document dans un mois.** Vous verrez qu'il ne mentait pas — dans les
deux sens.
