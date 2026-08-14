<p align="center">
  <img src="assets/banniere.svg" alt="ARAC BRAIN — Claude Desktop pour réfléchir. Claude Code pour construire. ARAC BRAIN pour se souvenir." width="100%">
</p>

<p align="center">
  <a href="docs/POURQUOI.md">Pourquoi</a> ·
  <a href="docs/DEMARRAGE-RAPIDE.md">Démarrer</a> ·
  <a href="docs/MANUEL.md">Comprendre</a> ·
  <a href="docs/LIMITES-CONNUES.md">Limites connues</a> ·
  <a href="docs/DECISIONS-ARCHITECTURE.md">Décisions</a>
</p>

# ARAC BRAIN — donner à Claude une mémoire qui dure

**Vous parlez à Claude tous les jours, et tous les jours il oublie.** ARAC lit ces
conversations, en tire ce qui mérite d'être retenu — une décision, un chiffre, une règle,
un piège — et le range dans une mémoire durable, sur votre serveur, dans votre base.

**Vous ne rangez rien, vous ne taguez rien, vous n'écrivez aucune note.** Le cerveau
digère trois fois par jour, tout seul, et vous montre ce qu'il a compris.

**Six mois plus tard, vous posez une question et il répond** — même si vous ne vous
rappelez plus l'avoir dit, ni quand, ni avec quels mots.

---

## Ce dépôt n'est le cerveau de personne

**ARAC BRAIN n'est pas un cerveau qu'on vous prête : c'est le cadre à partir duquel
vous construisez le vôtre.** Rien ici n'est hérité de quelqu'un d'autre — ni une
taxonomie, ni des rôles de base de données, ni des scopes, ni des exemples tirés de la vie
d'un inconnu.

> ### « Mon meilleur ami clone ce dépôt. Peut-il créer son cerveau sans mon aide ? »
>
> C'est la seule question à laquelle ce dépôt doit répondre, et voici où il en est.
>
> **Oui, pour ce qui s'installe.** Il lui faut un Mac (ou pas — voir plus bas), Claude
> Desktop, Claude Code et un serveur Ubuntu. `bootstrap/wizard.py` lui pose **ses**
> questions ; il en sort **sa** taxonomie, **ses** secrets, **ses** rôles PostgreSQL,
> **ses** services, **son** cockpit. La reproductibilité est prouvée : deux installations
> complètes depuis une base vide, avec deux taxonomies différentes, rendent **le même
> schéma** — identique **une fois retirée de part et d'autre l'identité de chaque
> installation**, que le produit grave exprès pour qu'un dump sache dire de quel cerveau
> il vient. Le critère et sa commande sont au [§7c](#c-ce-qui-est-éprouvé-sur-quoi-et-ce-qui-nest-pas).
>
> **Oui, pour ce qui se comprend.** Le [manuel](docs/MANUEL.md) répond aux huit questions
> qu'il se posera, dans l'ordre où il se les posera — sans jamais avoir à demander à
> quiconque.
>
> **Pas encore, sur deux points, et ils sont nommés :** le bootstrap n'installe aucun
> paquet système (il les *nomme* — PostgreSQL 16 et pgvector doivent être là), et
> l'installation **complète** en interactif n'a pas été menée de bout en bout — seule
> l'**étape des secrets** l'a été, et la connexion au cockpit qui la suit (mot de passe
> tapé, code TOTP, `303` vers `/cc/`) est, elle, mesurée : voir le §7c. L'état complet,
> assertion par assertion, est dans [`GOAL.md`](GOAL.md).

**Par où commencer :** [`docs/MANUEL.md`](docs/MANUEL.md) — les huit questions, dans
l'ordre, avec une réponse à chacune.

---

## 1. Le positionnement — à comprendre avant la première commande

Il y a trois endroits, et ils ne font pas le même métier.

| | Vous y faites | Ce qu'il en reste demain |
|---|---|---|
| **Claude Desktop** | vous **réfléchissez** — vous cherchez, vous hésitez, vous tranchez | rien : la conversation suivante repart de zéro |
| **Claude Code** | vous **construisez** — vous écrivez du code, vous corrigez, vous livrez | rien : le contexte meurt avec la session |
| **ARAC** | rien. Vous ne l'ouvrez pas pour travailler. | **tout ce qui valait la peine** — compris, rangé, relié, retrouvable |

**ARAC ne remplace pas Claude, il l'augmente.** Claude raisonne remarquablement et oublie
tout entre deux conversations. ARAC ne raisonne pas : il retient, et il rend au bon
moment. Le premier sans le second recommence à zéro chaque matin ; le second sans le
premier n'est qu'une base de données.

Concrètement : vous continuez à travailler exactement comme aujourd'hui. Rien ne change
dans vos habitudes. Ce qui change, c'est qu'une machine relit ce que vous avez dit,
pendant que vous dormez, et prépare de quoi vous le rappeler.

---

## 2. Ce qu'ARAC n'est pas

**Personne ne doit croire qu'il installe un nouvel Obsidian.** ARAC ressemble à six
choses qui existent déjà ; il n'en est aucune.

| Il ressemble à | Mais |
|---|---|
| **Obsidian, Notion, un éditeur de notes** | vous n'écrivez rien et vous ne rangez rien |
| **un RAG classique** | un RAG retrouve des passages ; ARAC retient des affirmations |
| **un chatbot** | ARAC ne répond pas, il se souvient — il n'a aucune interface de discussion |
| **une base vectorielle** | pgvector est un composant, pas le produit |
| **un tableau de bord** | le cockpit sert à comprendre un cerveau, pas à suivre des indicateurs |
| **un remplaçant de Claude** | Claude raisonne, ARAC retient — ce sont deux métiers |

Ce n'est pas non plus un produit fini qu'on installe : c'est un cadre à partir duquel
**vous créez votre cerveau**. Rien n'est hérité de personne.

*Les six confusions sont levées une par une — avec, à chaque fois, **quand l'autre outil
est le bon choix** — dans
[`docs/CE-QUE-ARAC-N-EST-PAS.md`](docs/CE-QUE-ARAC-N-EST-PAS.md). Le raisonnement qui
mène à ARAC est dans [`docs/POURQUOI.md`](docs/POURQUOI.md) ; les raisons de **ne pas**
l'installer, dans [`docs/PHILOSOPHIE.md`](docs/PHILOSOPHIE.md).*

---

## 3. À quoi ressemble un cerveau qui marche

Le cockpit (derrière un tunnel SSH, sur le port attribué à votre cerveau) ouvre sur une synthèse
narrative. Elle n'est **pas** générée par un modèle de langage : le serveur ne rend que
des clés de gabarit et des chiffres, chacun accompagné du lien vers la requête SQL qui le
prouve. Une phrase sans source n'est jamais affichée, et le bandeau est plafonné à six
phrases (`control_center/cc_v1/today.py`, `MAX_SENTENCES = 6`).

```
AUJOURD'HUI · fenêtre 24 h                              cerveau « <votre-cerveau> »
──────────────────────────────────────────────────────────────────────────────────
  Depuis 24 heures, j'ai appris 5 conversation(s) et créé 9 atome(s) de savoir.
  1 cycle(s) sur 3 sont partis en quarantaine depuis 24 heures ; cycles
  réellement aboutis : 2. Ce que les autres portaient n'a pas été retenu.
  J'ai servi 11 rappel(s) depuis 24 heures.
  Le domaine travail/strategie est celui qui s'est le plus enrichi : 4 atome(s)
  créé(s) depuis 24 heures.
  J'ai absorbé 613 message(s) depuis 24 heures, dont 214 pour la seule
  conversation « migration du serveur de production ».
  J'ai dépensé 174 300 jetons depuis 24 heures, soit 19 366 jetons par atome retenu.
```

Trois choses valent qu'on s'y arrête, parce qu'elles disent la doctrine du projet mieux
qu'un manifeste.

**Il annonce ses échecs au même rang que ses succès.** « 1 cycle sur 3 en quarantaine »
n'est pas relégué dans un journal : c'est la **deuxième** phrase du bandeau. L'ordre
n'est pas laissé au hasard — chaque phrase porte un rang déclaré dans
`control_center/cc_v1/today.py`, et **plus bas veut dire plus haut placé** :
`cycle_quarantined` vaut **36**, devant le rappel servi (44), le domaine enrichi (48) et
le coût (75). Ce qui le précède ne sont pas des succès : l'absence d'apprentissage
(`nothing_learned`, 10), les deux ouvertures (`learning_today` et
`learning_without_conversation`, 20) et l'avancée d'un projet (30). Le commentaire du code
dit pourquoi : *« un échec passe avant un succès de plus »*. Un cerveau qui ne raconterait que ses bons jours ne serait pas utilisable.

**Il annonce son coût.** Les jetons dépensés et les jetons par atome retenu sont des
phrases de la synthèse, pas une option de facturation cachée.

**Et quand il n'a rien à dire, il le dit** — plutôt qu'un bandeau vide qu'on prendrait
pour un chargement en cours :

```
  Le cerveau n'a rien appris depuis 24 heures.
  Personne ne m'a rien demandé depuis 24 heures : aucun rappel servi.
```

Trois phrases sont **interdites** dans ce bandeau, et le code les refuse : « aucune
contradiction », « aucune régression », « aucun lien créé ». Ces mesures n'existent pas
(§7a) ; l'absence de mesure se dit `measure_unavailable`, avec sa raison et le geste qui la
débloquerait. **Une absence n'est jamais affichée comme un zéro** — un zéro se lit « c'est
nul », une indisponibilité se lit « on ne sait pas ».

En ligne de commande, la même vérité sans navigateur :

```
$ .venv/bin/python scripts/ops/health_check.py
Indice de santé cérébrale : 48/100
148 métriques lues — 111 dans les clous, 6 en alerte, 9 critiques, 22 indisponibles

  ✗ V2 — Fraîcheur : 0 /100   [alerte 60, critique 40 — plus c'est haut, mieux c'est]
  ✗ Savoir invisible au rappel : 20 %   [alerte 5, critique 10 — plus c'est bas, mieux c'est]
    (l'étiquette exagère : ces atomes-là restent rappelables par similarité pure. Ce
     que la mesure compte, c'est le savoir posé sur une racine nue — donc hors de
     l'état courant, de la vue des scopes et de la couverture. Voir §7a.)
  ...
VERDICT : CRITICAL
```

> Les chiffres du bandeau ci-dessus sont **plausibles, pas capturés** : ce sont les
> gabarits réels de `control_center/cc_v1/today.py` remplis avec des valeurs d'exemple.
> Le seul bloc issu d'une exécution est celui de `health_check.py`, reproduit depuis
> [`docs/EXPLOITATION.md`](docs/EXPLOITATION.md).

---

## 4. Ce que ça coûte — en première page, parce que c'est un contrat

**ARAC n'a pas de mode gratuit.** Deux fonctions qu'il ne sait pas faire seul se paient
— mais **pas de la même façon**, et c'est la première chose à comprendre avant d'acheter
quoi que ce soit.

| Fonction | Ce qu'il faut **posséder** | Ce qui la paie | Ce qui meurt sans elle |
|---|---|---|---|
| **Embeddings** — OpenAI, `text-embedding-3-large` | rien à installer : ARAC appelle l'API lui-même | **une clé d'API OpenAI**, `ARAC_EMBEDDINGS_API_KEY`, **lue par ARAC** (`app/services/embeddings.py`). Elle paie **un vecteur par souvenir produit** — jamais par message ingéré — plus un vecteur par question posée au rappel. | le rappel par similarité : le cerveau ne retrouve plus que ce dont vous vous souvenez déjà |
| **Curation** — le Claude Code CLI | **le binaire `claude`, installé sur VOTRE serveur** : `sudo npm install -g @anthropic-ai/claude-code` | **ce qui authentifie ce binaire**, et rien d'autre : soit une **session d'abonnement Claude** ouverte pour le compte d'agent (rien de plus à payer à l'appel), soit une **clé d'API Anthropic** que **le binaire** lit dans l'environnement du service. ARAC ne lit ni ne transmet jamais cette clé. | les cycles tournent et ne produisent **aucun** souvenir |

> **La ligne la plus chère de cette page, et elle a longtemps été fausse.** La curation
> **n'appelle aucune API** : le cycle de digestion lance le binaire `claude` en
> sous-processus sur votre serveur, sous le compte d'agent du cerveau
> (`agents/lib/claude_cli.py`). **Une clé d'API Anthropic seule ne digère rien** si le
> binaire n'est pas là ; et **si vous avez déjà un abonnement Claude, vous n'avez aucune
> clé de curation à acheter** — il suffit d'ouvrir la session sous le bon compte.
> `./bootstrap/bootstrap.sh --check` constate désormais ce binaire, dit sa version, **et
> lit son authentification sans rien dépenser**.

**Mesures relevées sur le cerveau de référence**, observé huit mois en régime établi —
ce sont des observations, pas des estimations de brochure :

```
  MESURÉ
  3 cycles de digestion par jour        (04:00 · 13:00 · 21:00)
  ~87 000 jetons consommés par cycle
  ~31 500 jetons par souvenir effectivement produit
  ~150 atomes par mois                  (cadence observée sur la durée)
  ────────────────────────────────────────────────────
  CALCULÉ à partir des deux premières lignes, et de rien d'autre
  ≈ 260 000 jetons par jour · ≈ 8 000 000 par mois
```

**Ne divisez pas ce bloc par lui-même.** Les quatre mesures ne couvrent pas la même
fenêtre : 8 000 000 ÷ 31 500 donnerait ≈ 250 atomes par mois, ce qui n'est pas la cadence
observée sur la durée. Le quotient de deux mesures prises séparément n'est une mesure de
rien. Ce qui est établi, et suffit à décider : **votre facture suit les cycles, pas les
atomes** — elle est la même le mois où le cerveau retient beaucoup et celui où il ne
retient rien.

Le rapport entre 87 000 et 31 500 est la vraie leçon : **la plupart des jetons lus ne
produisent rien.** C'est normal — l'essentiel d'une conversation n'est pas du savoir
durable — mais il vaut mieux le savoir avant de commencer qu'en lisant la facture.

**Ordre de grandeur mensuel, pour un usage personnel :**

| Poste | Ordre de grandeur |
|---|---|
| Curation **facturée à l'appel** (le binaire s'authentifie par clé d'API), modèle de la classe Sonnet — 3 $/M de jetons d'entrée, tarif public d'août 2026 | **~25 $/mois**, plus la sortie |
| Curation **facturée à l'appel**, modèle de la classe Opus | **3 à 5 fois plus** |
| Curation **sur abonnement** (le binaire s'authentifie par une session Claude déjà ouverte) | **rien de plus que votre abonnement** — la digestion consomme alors son quota, pas votre carte |
| Embeddings | **quelques euros par mois** — deux ordres de grandeur en dessous |
| Serveur (VPS 2 vCPU / 4 Go) | **5 à 15 €/mois** |
| **Total réaliste, curation à l'appel** | **20 à 100 $ par mois**, selon le modèle choisi |
| **Total réaliste, curation sur abonnement** | **votre abonnement + 5 à 15 €** de serveur + quelques euros d'embeddings |

> **Vérifiez ces tarifs vous-même avant de vous engager.** Ce dépôt ne peut pas vous
> promettre un prix qu'il ne fixe pas.

Les freins existent et sont armés **avant** le premier cycle, pas après. Ils sont
**quatre**, et les deux premiers sont des interrupteurs **fermés à la sortie d'usine** —
sur cent pour cent des installations neuves :

| Frein | Où il vit | Comment on l'ouvre |
|---|---|---|
| **Interrupteur 1/2** — côté service | `ARAC_ALLOW_PAID_AI` dans `/etc/arac/<votre_base>/arac.env` | `sudo sed -i 's/^ARAC_ALLOW_PAID_AI=.*/ARAC_ALLOW_PAID_AI=1/' /etc/arac/<votre_base>/arac.env` |
| **Interrupteur 2/2** — côté cerveau | **en base** : `arac.arac_config`, clé `paid_ai_enabled` | `sudo .venv/bin/python -m agents.lib.paid_ai_control arm --confirm --coffre /etc/arac/<votre_base>/arac.env` |
| Plafond par cycle | `ARAC_PACK_TOKEN_BUDGET` | réglage |
| Garde-dépense (plafonds du jour, kill-switch) | `agents/lib/spend_guard.py` | réglage |

**Tant que les deux interrupteurs ne sont pas ouverts, aucun cycle ne produit un seul
souvenir** — et c'est délibéré : rien ne dépense votre argent sans un geste humain
explicite. Le premier cycle refusé porte, dans `journalctl`, le code exact du verrou qui
l'a arrêté (`master_switch_env_off`, puis `master_switch_config_off`) **et le geste qui
le lève**. Voir [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) et l'étape 9 du
[démarrage rapide](docs/DEMARRAGE-RAPIDE.md).

---

## 5. Ce qu'il vous faut, et ce que vous n'aurez pas

### Il vous faut

**Quatre colonnes, parce que « prérequis » ne veut rien dire tout seul.** Ce qui est
*obligatoire* n'est pas ce qui est *payant*, et ce qui est payant n'est pas forcément
*vérifié*. La dernière colonne est celle qui compte : **ce que le bootstrap ne vérifie
pas, c'est vous qui devrez y penser.**

#### Sur le serveur

| Il vous faut | Vraiment obligatoire ? | À quoi ça sert **ici** | Vérifié par le bootstrap ? |
|---|---|---|---|
| **Un serveur Ubuntu ou Debian** | **oui** | systemd, `apt`, et les chemins que supposent les gabarits. Pas un portable : le cerveau digère à 4 h du matin. 2 vCPU, 4 Go, 20 Go de disque suffisent des années. | **oui** — étape 1, ligne `Ubuntu / Debian`, avec le nom et la version trouvés |
| **PostgreSQL 16 (serveur)** | **oui** | la mémoire *est* la base : atomes, vecteurs, preuves, journal d'audit. | **oui** — par une requête réelle (`SELECT 1`), pas par la présence d'un paquet |
| **`psql` (client)** | **oui** | appliquer les seeds, et vous laisser rejouer vous-même les preuves du cockpit. | **oui** — avec sa version |
| **pgvector** | **oui** | comparer des sens, pas des mots. Sans lui, aucun rappel par similarité. | **oui** — la version disponible est lue dans `pg_available_extensions` |
| **Python ≥ 3.12** | **oui** | `pyproject.toml` l'exige. | **partiellement, et c'est un piège nommé** : l'étape 1 se contente de **≥ 3.11** (ce qu'il faut pour lire votre taxonomie). Avec 3.11, elle passe au vert et `pip install` échoue à l'étape 5. |
| **git, ssh, systemd, sudo, openssl** | **oui** | récupérer le framework · le tunnel du pont · faire vivre l'API, le cockpit, les cycles et les sauvegardes · écrire les secrets en `0600` · engendrer ces secrets. | **oui** — une ligne chacun |
| **Le binaire `claude` (Claude Code CLI)** — `sudo npm install -g @anthropic-ai/claude-code` | **oui pour APPRENDRE**, non pour naître | **c'est le vrai prérequis de la curation.** La digestion n'appelle **aucune API** : le cycle lance ce binaire en sous-processus, sous le compte d'agent (`agents/lib/claude_cli.py`). Absent, le cerveau ingère, se laisse interroger — et n'apprend jamais rien. | **oui, depuis cette manche** — étape 1 (section « La curation »), puis **de nouveau au contrôle final, sous le compte d'agent**, qui est le seul dont l'avis compte |
| **De quoi authentifier ce binaire** | **oui pour apprendre** | **une seule des deux suffit** : une session d'abonnement Claude ouverte pour le compte d'agent, **ou** une clé d'API Anthropic — que **le binaire** lit, jamais ARAC. | **oui** — `claude auth status`, joué **sous le dossier personnel du compte d'agent**, et sans rien dépenser |
| **`npm` / Node** | **seulement si le binaire n'est pas déjà là** | poser le Claude Code CLI. | **non** — le bootstrap donne la commande `npm`, il ne vérifie pas que `npm` existe. Voir [`docs/LIMITES-CONNUES.md`](docs/LIMITES-CONNUES.md). |
| **Une clé d'API OpenAI** | **oui pour se souvenir** | vectoriser chaque souvenir produit et chaque question posée. C'est **la seule clé qu'ARAC lise lui-même**. | **oui, indirectement** : refusée, l'étape 8 déclare `ARAC_MODE_DEGRADE=embeddings`, et le contrôle final affiche ce mode dégradé |
| **Un accès `sudo`** | **oui** | créer la base, écrire les secrets, poser les unités système. | **oui** |
| **Un accès réseau sortant** | **oui** | `pip install` (une fois), l'API d'embeddings (en continu), et ce que le binaire `claude` appelle. **Aucun accès entrant n'est requis** : l'API et le cockpit n'écoutent que sur `127.0.0.1`. | **annoncé** à l'étape 1, pas mesuré |
| **20 Go de disque libre** | recommandé | des années de mémoire, sauvegardes **exclues** (prévoyez-les sur un autre disque). | **non** — aucune mesure d'espace disque |
| **Une application d'authentification (TOTP) sur votre téléphone** | **oui pour ouvrir le cockpit** | le second facteur. Le mot de passe seul ne suffit pas. | **le secret est engendré et affiché une seule fois** à l'étape 7 (`secrets`) ; que vous l'ayez appairé, personne ne peut le vérifier à votre place |

#### Sur votre poste

| Il vous faut | Vraiment obligatoire ? | À quoi ça sert **ici** | Vérifié par le bootstrap ? |
|---|---|---|---|
| **Un Mac** | **non** | `launchd` pour l'ordonnancement, `plutil`, les notifications système. `mac/arac-sync.py` n'utilise que la bibliothèque standard : il tourne tel quel sur Linux, y compris **sur le serveur lui-même**, et le tunnel devient alors inutile (`deploy/systemd/arac-pont-sans-mac.{service,timer}.modele`). | **non, et il ne le peut pas** : le bootstrap tourne sur le serveur. **Honnêteté : le pont n'a jamais été exercé sur un vrai Mac** — voir [`docs/PONT-MAC.md`](docs/PONT-MAC.md). |
| **Claude Code (CLI) sur ce poste** | **non, mais c'est la seule source automatique** | ses sessions (`~/.claude/projects/**/*.jsonl`) sont captées **automatiquement** par le pont. | **non** — c'est le pont, pas le bootstrap, qui les lit |
| **Claude Desktop** | **non** | seconde source, **manuelle uniquement** : l'application ne conserve rien de lisible en local, et il n'existe aucune capture automatique. La seule voie stable est l'export officiel de claude.ai. | **non** |
| **Un client SSH** | **oui** (sauf si le pont tourne sur le serveur) | c'est par un tunnel SSH que vos conversations quittent le poste. | **non** côté poste ; **oui** côté serveur |

> **Ce que vous devez ACHETER, en une phrase.** Une clé d'API OpenAI, et — **seulement si
> vous n'avez pas déjà d'abonnement Claude** — de quoi authentifier le binaire `claude`.
> Le binaire lui-même ne s'achète pas : il s'installe. **Une clé d'API Anthropic achetée
> sans ce binaire ne produit pas un seul souvenir.**

> **Ce que vous pouvez refuser.** Les deux clés. Le cerveau démarre alors en **mode
> dégradé déclaré** (`ARAC_MODE_DEGRADE`), et vous dit, à l'installation puis à chaque
> contrôle, exactement ce qui ne marchera pas.

### Le pont d'ingestion suppose un Mac — et voici exactement ce que ça veut dire

Le cerveau ne va pas chercher vos conversations : c'est un **pont**, sur votre machine,
qui les lui pousse. Ce pont est écrit pour macOS — `launchd` pour l'ordonnancement,
`plutil`, les notifications système — et il connaît deux sources, pas une :

| Source | Capture | Où |
|---|---|---|
| **Claude Code (CLI)** | **automatique** | `~/.claude/projects/**/*.jsonl` |
| **Claude Desktop** | **manuelle** — export officiel depuis claude.ai | l'application ne conserve rien de lisible en local ; il n'existe aucune capture automatique, et [`docs/PONT-MAC.md`](docs/PONT-MAC.md) explique longuement pourquoi |

**Sans Mac, le cerveau tourne — mais il faut l'alimenter autrement.**
`mac/arac-sync.py` n'utilise que la bibliothèque standard : il fonctionne sur Linux, y
compris sur le serveur lui-même, auquel cas le tunnel devient inutile. L'ordonnancement
passe alors par `deploy/systemd/arac-pont-sans-mac.{service,timer}.modele`. Ce qu'on perd
sans Mac : `launchctl` et les notifications. Ce que **personne** n'a, avec Mac ou sans :
une capture automatique de Claude Desktop.

**Un poste peut piloter deux cerveaux sans qu'ils se mélangent.**
`./arac-pont.sh installer` demande **toujours** le nom du cerveau — c'est sa question 0 —
et pose sa configuration, sa copie d'`arac-sync.py`, son jeton, son curseur et son
journal sous `~/.arac/<cerveau>/`. Sans nom, il refuse et n'écrit rien (code `2`) :
deux ponts dans un foyer commun partageraient un seul curseur et un seul jeton. Voir
[`mac/README.md`](mac/README.md).

### Vous n'aurez pas

- **Aucun accès public.** L'API et le cockpit n'écoutent que sur `127.0.0.1`, chacun sur
  **un port attribué à votre cerveau** — constaté libre à l'installation, puis retenu dans
  `/etc/arac/<votre_base>/arac.env`. Deux cerveaux sur une même machine ne se disputent
  donc pas un numéro convenu d'avance, et aucune commande de cette documentation n'en écrit
  un en clair. On les atteint par un tunnel SSH : il n'y a donc ni TLS à installer, ni
  reverse-proxy, ni pare-feu à régler. **Mais le tunnel ne tient pas lieu
  d'authentification** — il dit d'où vient une requête, jamais qui l'envoie. Le jeton
  porteur est donc exigé de **toute** requête, `127.0.0.1` compris ; seul `/healthz` est
  public. La règle, sa raison et son desserrage — qui exige d'être écrit **et** motivé —
  sont dans [`app/auth.py`](app/auth.py) et dans
  [`docs/CONFIGURATION.md` §6](docs/CONFIGURATION.md).

  > **La leçon, parce qu'elle vaut plus que le réglage.** Cette page a longtemps écrit
  > « il n'y a rien à défendre — sur la boucle locale, le tunnel *est* l'authentification ».
  > Chaque prémisse était vraie : l'API n'écoute que `127.0.0.1`, le seul chemin depuis le
  > Mac est un tunnel SSH, SSH a déjà authentifié la personne par sa clé. La conclusion,
  > non — parce qu'elle en supposait une quatrième, que personne n'avait écrite :
  > **qu'atteindre `127.0.0.1` exige d'avoir franchi SSH.** C'est faux dès qu'un second
  > compte a un shell sur la machine, et un second cerveau en amène au moins un. Mesuré,
  > depuis le compte `nobody`, sans un seul secret : la mémoire du voisin lue en clair, un
  > faux souvenir écrit chez lui. Aucun coffre `0700`, aucun rôle PostgreSQL, aucune
  > grappe séparée ne ferme ce chemin : il ne passe par **aucun fichier**, donc aucune
  > permission ne s'y applique.
  >
  > Deux règles à emporter ailleurs. **Une machine qui n'accueillera jamais qu'un seul
  > cerveau n'est pas une raison de laisser sa mémoire lisible par tout compte local** :
  > « seul sur la machine » est une hypothèse sur l'avenir, pas une propriété du système,
  > et une exemption fondée sur l'*origine* d'une requête ne vaut que ce que vaut
  > l'hypothèse sur qui peut prendre cette origine. Et **un défaut implicite est un défaut
  > que personne ne peut relire** : ce qui a laissé cette porte ouverte, ce n'est pas une
  > valeur mal choisie, c'est une valeur que personne n'avait écrite — donc que personne
  > ne pouvait contester. C'est pourquoi le bootstrap **écrit** `ARAC_API_TRUST_LOOPBACK=0`
  > dans votre coffre, alors même que c'est déjà le défaut du moteur.
- **Aucun serveur MCP.** Claude Code atteint le cerveau par l'**API HTTP**, à travers le
  tunnel. Les routes réellement servies, vérifiées dans `app/routers/atoms.py` :

  ```
  POST /v1/atoms/recall          k plus proches voisins d'une question, purs
  POST /v1/atoms/recall_fresh    idem, en écartant les atomes périmés
  POST /v1/atoms/context_for     recall + vos atomes « pierres angulaires », toujours présents
  POST /v1/atoms/resume          routage par projet (désactivé par défaut : ARAC_PROJECT_ROUTER_ENABLED)
  GET  /v1/atoms/foundations     les pierres angulaires seules
  GET  /healthz                  le seul point public
  ```

  Ce sont les routes de **rappel**, celles que Claude Code appellera. `app/routers/atoms.py`
  en sert d'autres, d'écriture et de lecture unitaire — création, supersession, retouche,
  archivage, lignée, lecture par clé. Elles ne servent pas à se souvenir mais à **corriger**
  ce que le cerveau a cru, et le geste est décrit au jour 7 de
  [`docs/PREMIER-MOIS.md`](docs/PREMIER-MOIS.md) : c'est le seul recours, puisque le cockpit
  n'a aucune route qui écrive dans la mémoire — sa seule route non-GET est la connexion,
  et son rôle PostgreSQL est en lecture seule.

  Il n'y a **pas** d'intégration clés en main dans ce dépôt : à vous d'appeler ces routes
  depuis vos outils.
- **Aucun multi-utilisateur.** Un cerveau, une personne.
- **Aucun Docker.** C'est un choix : `systemd` et un `venv` suffisent et se diagnostiquent
  mieux.

---

## 6. Le chemin le plus court vers un cerveau qui vit

```bash
git clone <l-adresse-de-ce-depot> arac && cd arac
make venv                              # environnement Python + dépendances
python3 bootstrap/wizard.py            # l'entretien — 5 min, n'installe RIEN
./bootstrap/bootstrap.sh --dry-run     # tout montrer, ne rien écrire
sudo ./bootstrap/bootstrap.sh          # installer, pour de vrai
```

Puis, à tout moment : `./bootstrap/checks/verify_install.sh` — « ce cerveau est-il
sain ? ». Il ne modifie rien.

**Comptez une heure** si PostgreSQL 16 et pgvector sont déjà là et que vous avez vos deux
clés d'API sous la main. **Comptez une demi-journée** en partant d'un Ubuntu nu. Le détail
minuté, étape par étape, avec **ce qu'on doit voir quand ça marche**, est dans
[`docs/DEMARRAGE-RAPIDE.md`](docs/DEMARRAGE-RAPIDE.md).

Une chose que vous pouvez faire **tout de suite**, avant même d'avoir un serveur, pour
vérifier que le dépôt est sain :

```bash
make test        # ni base, ni réseau, ni clé d'API — et c'est vérifié, pas promis
```

**Ce qu'il faut voir — et pourquoi ce n'est plus « une ligne verte ».**

Cette phrase a longtemps dit : *ce qu'il faut voir, c'est une ligne verte sans `failed`*.
Ce critère a été **satisfait par une livraison cassée**, et il faut le raconter parce que
c'est ce qui a fait réécrire ce paragraphe. Le jour où le dépôt affichait 5 266 tests verts
et où `make acceptance` rendait « 0 en échec » pour la troisième fois, le produit livrait
quatre noms jamais importés : `GET /v1/dashboard/atoms_by_scope` et `GET
/v1/dashboard/search` levaient `NameError` à leur dernière instruction — **500 sur un
cerveau neuf et sain** — le filet qui devait sauver la digestion d'un tri impossible la
tuait, et la commande d'arrêt d'urgence de l'IA payante mourait sur `ModuleNotFoundError`
à sa première ligne. Aucun test n'était faux. Aucun n'était passé par là.

**Un compte de tests verts ne dit pas ce qui a été exécuté.** Il dit combien d'assertions
ont tenu sur les chemins que quelqu'un a pensé à emprunter. C'est pour cela que le nombre
n'a jamais été un critère ici — il ne vous sert à rien de le comparer au nôtre — et c'est
pour cela que la ligne verte n'en est plus un non plus, à elle seule. **La durée non plus
n'est pas un critère** : cette phrase a longtemps annoncé « une vingtaine de secondes »,
ce qui ne mesurait que la machine de celui qui l'écrivait ; comptez plutôt une à deux
minutes sur un petit serveur.

**Les trois lignes qui, ensemble, disent que ce dépôt est sain.** Elles sont dans la
sortie de `make test`, et elles se lisent dans cet ordre :

1. **`tests/test_aucun_nom_non_resolu.py` est vert.** Ce test **charge tout ce que le
   produit charge** — chaque module de `app/`, `agents/`, `control_center/`, chaque script
   Python livré — puis demande à Python, pour chaque nom que le code ira chercher à
   l'exécution, s'il existe quelque part. Il ne relit pas le code : il l'exécute au moins
   jusqu'à son import, et il échoue sur le moindre nom mort. C'est la seule des trois
   lignes qui prouve une **négative universelle** : *aucun* module livré ne contient
   *aucun* nom qui lèverait `NameError`. Les quatre défauts ci-dessus le font rougir, un
   par un.

2. **Le bloc « CE QUE CETTE SESSION A RÉELLEMENT EMPRUNTÉ »**, imprimé en fin de suite.
   Il compte les routes que le produit sert et **celles dont le corps a réellement été
   exécuté**, et il nomme les autres. « Empruntée » n'y veut pas dire « appelée » : une
   requête arrêtée par l'authentification n'est pas un emprunt — c'est exactement la nuance
   qui a laissé passer les deux 500, puisque le harnais appelait bien `/v1/dashboard/search`,
   mais sans jeton. Ce bloc ne rougit pas : il **mesure**. Lisez-le comme une carte de ce
   sur quoi le vert se tait — sur un dépôt fraîchement cloné, la majorité des routes ne
   sont pas empruntées, parce qu'elles exigent une base et que cette suite n'en a pas.

3. **La ligne de pytest sans `failed`.** Toujours nécessaire. Simplement plus suffisante.

**Et la quatrième, qui ne s'obtient pas sans serveur :** `sudo make acceptance` installe un
cerveau réel, lui fait écrire un souvenir par la vraie route, **relit ce souvenir par les
routes du tableau de bord avec un jeton valide**, casse la base, la restaure, puis
désinstalle tout. C'est la seule qui réponde à *« ces chemins marchent-ils ? »* plutôt qu'à
*« sont-ils chargeables ? »*. Les trois premières se lisent sur un portable en deux
minutes ; celle-là demande une machine, et c'est le prix d'une preuve d'exécution.

**L'herméticité est une garde, plus une affirmation** (`tests/garde_hermetique.py`). Elle
coupe les sockets sortantes et les commandes qui interrogent la machine, et elle refuse
toute base de données qui n'a pas été créée par le test lui-même. La question qu'elle pose
n'est pas *« est-ce la base de l'auteur ? »* — on ne peut pas énumérer les cerveaux du
monde — mais *« cette base m'appartient-elle, à moi, test ? »*. C'est ce qui vous garantit
que `make test`, lancé sur le serveur où tourne déjà un cerveau, **ne le touchera pas**.

**Et ensuite ?** Le cerveau sera vide, et il le restera plusieurs jours. Ce n'est pas une
panne, c'est la nature de la chose — mais c'est le moment où la plupart des gens
abandonnent. Lisez [`docs/PREMIER-MOIS.md`](docs/PREMIER-MOIS.md) **avant** d'installer,
pas après : il décrit ce que vous verrez au jour 1, au jour 3, au jour 7 et au jour 30, ce
qui est normal, ce qui ne l'est pas, et comment faire la différence.

---

## 7. Ce qui ne marche pas encore — honnêtement

Cette section est la plus importante de cette page. Elle n'est pas en annexe.

> **Elle est la porte, pas le registre.** Ce qui suit enseigne les manques qui
> décident : ceux qui vous feront peut-être renoncer, et qu'il serait malhonnête de
> reléguer plus loin. La **liste tenue** — chaque limite avec sa date, la commande
> qui la rejoue et le critère qui survivra au changement de chiffre — vit dans
> [`docs/LIMITES-CONNUES.md`](docs/LIMITES-CONNUES.md), et c'est elle qui fait
> autorité. Si les deux divergent un jour, c'est cette page-ci qui est à corriger.
> Ce qui reste **su et non corrigé**, avec sa classe de gravité, est au registre de
> [`docs/RELEASE-V1.md`](docs/RELEASE-V1.md) §5.

### a. Le graphe de liens est écrit mais jamais servi — et il ne porte aucun sens

C'est le malentendu le plus coûteux qu'on puisse avoir sur ce projet, alors disons-le
sans détour : **ARAC ne relie pas deux idées parce qu'il a compris qu'elles se
répondaient.**

Ce que le cerveau produit réellement, quand vous posez une question, est un **voisinage
sémantique** : deux atomes sont voisins parce que leurs vecteurs sont proches et qu'ils
partagent un domaine. C'est de la géométrie, calculée au moment de la question. Rien
d'autre.

Une couche de liens dérivés existe bien (`arac.atom_links`, migration
`0033_atom_links`) et le cycle la recalcule, mais elle ne porte que trois relations
**mécaniques** — succession d'un atome par un autre (`supersedes`), enchaînement dans une
même conversation (`same_thread`), et proximité vectorielle réciproque
(`semantic_neighbor`). Deux choses à savoir :

- **aucune de ces trois relations n'est un raisonnement.** Aucune ne dit « ceci confirme
  cela », aucune ne dit « ceci contredit cela » ;
- **aucun chemin de rappel servi ne lit cette table aujourd'hui.** Une fonction
  d'enrichissement existe (`app/services/atom_links.enrich_resume`) ; personne ne
  l'appelle, et la réponse de `POST /v1/atoms/resume` ne porte aucun champ de liens. Le
  cockpit ne la lit pas davantage — et il le déclare, en servant son bloc `links` en
  `unavailable` avec sa raison, plutôt qu'un zéro.

**Sur votre installation, la table est là** : `0033_atom_links` fait partie de la chaîne
que l'étape 5 du bootstrap applique avec `alembic upgrade head`. Vous n'avez rien à
poser. *(Ce document ne nomme pas la tête de la chaîne : c'est une valeur qui périme à
chaque migration, alors que la commande de constat ci-dessous reste vraie quoi qu'il
arrive.)* Vous pouvez le constater — et il vaut mieux constater que croire :

```bash
BASE=<votre_base>          # brain.name de config/brain.toml
PGPORT_BASE=$(sudo sed -n 's/^ARAC_DB_PORT=//p' "/etc/arac/$BASE/arac.env")

sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc "SELECT to_regclass('arac.atom_links')"
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -c "SELECT relation_type, count(*) FROM arac.atom_links GROUP BY 1"
```

> **Le `-p` fait partie du constat.** Sans lui, ces deux commandes interrogent la grappe
> **par défaut** de la machine, pas celle de votre cerveau — et sur un serveur qui en porte
> deux, la réponse décrit la mémoire du voisin. Le port de votre cerveau est écrit en clair
> dans son coffre, pour cette raison exacte.

Ce n'est donc pas une absence, c'est une **capacité écrite et non branchée**. Traitez-la
comme un matériau d'observation, jamais comme une capacité sur laquelle vous appuyer.

**Corollaire, et il est important : rien ne détecte de contradiction.** Si vous décidez X
en mars et l'inverse en septembre, le cerveau gardera les deux, les rendra tous les deux
comme voisins de votre question, et ne vous préviendra pas. La seule garantie réelle est
la **supersession** : quand un atome en remplace un autre, le remplacement est explicite,
et l'atome retiré est marqué et **conservé** — jamais supprimé. C'est pour cela que le
rôle applicatif PostgreSQL n'a pas le droit de `DELETE`.

**Et la vérification du savoir n'existe pas non plus.** Les colonnes prévues pour dater la
dernière vérification d'un atome ne sont alimentées par rien. Sur le cerveau de référence,
**98 % du savoir n'a jamais été audité** — un atome extrait par un modèle et jamais relu
par un humain reste une hypothèse bien rangée.

La feuille de route est dans [`docs/ROADMAP.md`](docs/ROADMAP.md) ; **rien de ce qui y
figure n'est promis comme existant.**

### b. Deux raccords entre l'installation et le moteur — posés, et vérifiables

Ces deux raccords ont longtemps été des gestes manuels. **Le bootstrap les pose
maintenant tous les deux.** Ils échouent en silence côté serveur : savoir les vérifier
vaut mieux qu'espérer.

**1. Le double vocabulaire — posé pour l'API ET pour le cockpit.** `bootstrap.sh` écrit
ses variables sous des noms préfixés (`ARAC_DB_URL_APP`, `ARAC_EMBEDDINGS_API_KEY`,
`ARAC_CC_SESSION_SECRET`…), tandis que le moteur extrait de la source lit encore les noms
historiques (`DATABASE_URL_APP`, `OPENAI_API_KEY`, `CC_SESSION_SECRET`…). À la fin de son
étape des clés, `poser_pont_de_vocabulaire` (`bootstrap/lib/secrets.sh`) **copie** les uns
vers les autres, dans `arac.env` **et** dans `cockpit.env` — chaque valeur restant dans le
fichier où elle est née, pour que l'empreinte du mot de passe et le secret TOTP ne soient
visibles ni de l'API ni des cycles.

```bash
sudo grep -c '^DATABASE_URL_' /etc/arac/<votre_base>/arac.env      # attendu : 4
sudo grep -cE '^(CC_SESSION_SECRET|CC_ADMIN_PASSWORD_HASH|CC_TOTP_SECRET)=' \
     /etc/arac/<votre_base>/cockpit.env                            # attendu : 3
```

Si le premier rend `0`, l'API démarrera puis s'arrêtera sur `DATABASE_URL_APP non
définie` ; si le second rend `0`, le cockpit refusera de s'ouvrir. Dans les deux cas votre
installation est **antérieure** à ce correctif, et le geste manuel — idempotent, testé, et
qui traite **les deux fichiers** — est dans
[`docs/DEPANNAGE.md` §1](docs/DEPANNAGE.md#1-lapi-ne-démarre-pas--database_url_app-non-définie).
Tableau complet des correspondances dans
[`docs/CONFIGURATION.md`](docs/CONFIGURATION.md#le-double-vocabulaire).

> **Cette page a dit deux faussetés successives sur ce même raccord**, et elles méritent
> d'être laissées en vue. D'abord : « `ARAC_CC_SESSION_SECRET → CC_SESSION_SECRET` fait
> partie des traductions faites » — c'était l'intention, pas le fait. Puis, une fois le
> défaut nommé : « le cas de toute installation à ce jour », maintenu **après** que le
> bootstrap eut cessé de le produire. Une fausseté corrigée peut donc en engendrer une
> seconde, exactement inverse, et tout aussi fausse. Ce sont les deux `grep` ci-dessus qui
> décident, sur VOTRE machine — pas ce paragraphe.

**2. Les deux portes de l'ingestion.** L'ingestion n'accepte une conversation que si le
poste qui la dépose est déclaré **deux fois** : dans la liste blanche
`ARAC_INGEST_ALLOWED_NODES`, et dans la table `arac.nodes`. Les deux sont **fail-closed** —
liste absente ou vide, et l'API répond `403` à tout, y compris à votre propre machine
munie d'un jeton valide. C'est une protection réelle, et le bootstrap la configure : il
écrit la liste blanche depuis l'identité de votre entretien (`bootstrap/lib/secrets.sh`)
et la migration `0008` déclare votre poste dans `arac.nodes` en lisant le même
`config/brain.toml`. Ce qu'il vous reste à faire est de **vérifier que les trois chaînes
coïncident** — celle de `config/brain.toml`, celle de la liste blanche, celle de
`arac.nodes`. Un tiret de plus suffit à tout perdre, et c'est la cause n° 1 des
conversations qui n'arrivent jamais. Les commandes de contrôle sont à l'étape 5 de
[`docs/DEMARRAGE-RAPIDE.md`](docs/DEMARRAGE-RAPIDE.md) ; le diagnostic complet, dans
[`docs/DEPANNAGE.md` §7](docs/DEPANNAGE.md#7-http-403--le-serveur-refuse-ce-poste).

### c. Ce qui est éprouvé, sur quoi, et ce qui ne l'est pas

**Il y a deux objets distincts, et les confondre est ce qui a rendu cette section fausse.**
Elle affirmait qu'« aucune conversation n'a jamais été ingérée » ; c'est vrai des cerveaux
d'essai, et faux du cerveau de référence, dont quatre autres pages de ce dépôt citent des
mesures. Un lecteur qui comparait ne pouvait pas savoir lequel croire — dans la section
même où l'on demande de nous faire confiance sur nos manques.

- **Le cerveau de référence** : l'installation d'origine de l'auteur, huit mois de vie
  réelle. Elle a été nourrie, elle a digéré, elle rappelle. **Tous les chiffres cités dans
  cette documentation viennent de là.**
- **Les cerveaux d'essai** : ceux que le bootstrap pose pour prouver qu'il sait poser un
  cerveau. Ils sont **vides** — aucune conversation, aucun atome — parce qu'aucune clé de
  curation payante ne leur a été donnée.

**Ce qui a réellement tourné à l'installation**, en août 2026, sur Ubuntu 24.04 /
PostgreSQL 16.13 / pgvector 0.8.2 : le bootstrap complet, **deux fois**, avec **deux
taxonomies différentes** — `CREATE DATABASE`, les rôles, `CREATE EXTENSION vector`,
`alembic upgrade head`, l'écriture des secrets, `systemctl enable --now`, l'API et le
cockpit en boucle locale, le contrôle a posteriori sans un seul échec, et une sauvegarde
produite par l'unité engendrée. Les deux schémas obtenus sont **les mêmes**, ce qui est le
seul critère qui vaille — pas leur taille, qui changera à la prochaine migration.

**« Les mêmes » veut dire : identiques une fois l'identité retirée des deux côtés — et
c'est la formulation entière, pas une réserve en petits caractères.** Le bootstrap grave
dans le commentaire du schéma une **plaque d'identité** — `COMMENT ON SCHEMA arac IS 'ARAC
cerveau=… empreinte=… poste=…'` — et `pg_dump` l'emporte, **exprès** : c'est elle que
`ops/restore_verify.sh` relit pour sa PREUVE D, « ce dump vient-il de CE cerveau ? ».
Deux installations qui rendraient un dump rigoureusement identique, octet pour octet,
seraient un défaut, pas une preuve : plus rien ne distinguerait votre mémoire de celle
d'un autre. **Ce qui doit être identique, c'est le schéma ; ce qui doit différer, c'est
l'identité.** Le contrôle ci-dessous dit les deux, dans cet ordre.

```bash
# Les deux cerveaux peuvent vivre sur la MÊME grappe ou sur deux : le port se lit,
# il ne se suppose pas. Sans « -p », les deux dumps viendraient de la grappe par
# défaut — et deux schémas identiques ne prouveraient rien, puisqu'ils seraient
# le même.
PORT_A=$(sudo sed -n 's/^ARAC_DB_PORT=//p' "/etc/arac/<base_a>/arac.env")
PORT_B=$(sudo sed -n 's/^ARAC_DB_PORT=//p' "/etc/arac/<base_b>/arac.env")
sudo -u postgres pg_dump -p "$PORT_A" --schema-only --no-owner --no-privileges -d <base_a> > a.sql
sudo -u postgres pg_dump -p "$PORT_B" --schema-only --no-owner --no-privileges -d <base_b> > b.sql

# On ne retire pas l'identité en apprenant par cœur la ligne qui la porte : le jour où
# le produit la gravera AILLEURS, un tel filtre laisserait passer la différence et le
# contrôle rougirait sans raison. On remplace les TROIS VALEURS qui nomment chaque
# installation — son cerveau, son empreinte, son poste —, lues dans SON PROPRE coffre.
# Un motif se périme à chaque amélioration ; des valeurs, non.
sans_identite() {                    # <base> : lit un dump sur l'entrée standard
  local env="/etc/arac/$1/arac.env" emp poste
  emp=$(sudo sed -n 's/^ARAC_INSTALL_UUID=//p' "$env")
  poste=$(sudo sed -n 's/^ARAC_NODE_ID=//p'    "$env")
  grep -vE '^\\(un)?restrict' \
    | sed -e "s/$poste/<poste>/g" -e "s/$emp/<empreinte>/g" -e "s/\b$1\b/<cerveau>/g"
}

# 1. LE SCHÉMA — c'est LUI, la reproductibilité.
diff <(sans_identite <base_a> < a.sql) <(sans_identite <base_b> < b.sql)
#    attendu : aucune ligne, et le code 0.

# 2. L'IDENTITÉ — elle, elle DOIT différer. C'est l'autre moitié de la preuve.
diff <(grep '^COMMENT ON SCHEMA arac' a.sql) <(grep '^COMMENT ON SCHEMA arac' b.sql)
#    attendu : deux lignes, différentes, et le code 1.
```

> **▸ Pourquoi ce critère-ci et pas l'autre.** Cette page a longtemps écrit « un
> `pg_dump --schema-only` identique ligne pour ligne », avec un `# attendu : vide`. La
> phrase était vraie quand elle a été écrite, et elle est devenue fausse **parce que le
> produit s'est amélioré ailleurs** : le jour où le bootstrap s'est mis à graver
> l'empreinte d'installation dans le commentaire du schéma, la commande de la page a
> commencé à rendre `1` et une différence — dans le premier écran du dépôt, sur la
> phrase qui répond au mandat. **Un critère qui périt à chaque amélioration n'est pas un
> critère, c'est un instantané.** Celui ci-dessus ne nomme aucune ligne et n'apprend
> aucun motif : il neutralise ce qui *identifie*, et compare le reste. Si une version
> future grave l'empreinte à un second endroit, il continue de rendre le vide sans qu'on
> y touche — mesuré, en gravant la plaque sur une table en plus du schéma : le filtre par
> motif rend alors une différence, celui-ci rend le vide. Et si un jour le produit grave
> quelque chose qui **n'est pas** de l'identité, la commande le montrera : c'est
> exactement l'alarme qu'on veut, et non un critère qui ment.

**Ce qui a réellement tourné à l'usage, sur le cerveau de référence.** La chaîne
`conversation → digestion → atome → embedding → rappel` est **exercée**, et elle laisse
une trace citable : chaque cycle écrit un **reçu**, et chaque reçu se relit.

```sql
-- le dernier cycle, tel qu'il s'est passé
SELECT status, items, atoms_created, atoms_quarantined,
       coverage_presented, coverage_covered,
       coverage_no_new_knowledge, coverage_omitted
FROM arac.run_receipts ORDER BY started_at DESC LIMIT 1;

-- l'invariant qui compte : aucun atome actif sans vecteur
SELECT count(*) FROM arac.memory_atoms
 WHERE status = 'active' AND embedding IS NULL;      -- attendu : 0
```

Sur le cycle du 8 août 2026 à 13:14 : **douze** conversations présentées, **huit**
couvertes par au moins un atome, **trois** déclarées sans rien à retenir, **une** omise —
douze qui se recomposent exactement, ce qui est le vrai contrôle. **Sept** atomes créés,
un run mis en quarantaine, et **aucun** atome actif sans embedding sur tout le corpus. Le
cerveau de référence porte, au moment où ces lignes sont écrites, quelques centaines de
conversations brutes, un peu moins de deux mille atomes, six racines et trente-neuf
feuilles.

**Ne retenez pas ces nombres, retenez les requêtes** : elles bougent à chaque cycle, et
un compte exact recopié dans un document se périme le jour même.

**Ce qui n'a toujours pas eu lieu**, et c'est l'essentiel de ce qui reste :

- **le rappel sur un corpus construit par quelqu'un d'autre que l'auteur.** C'est le
  manque central : la chaîne est exercée, mais sur **un seul** corpus, une seule
  taxonomie, une seule manière de parler. Rien ne dit encore comment elle se comporte sur
  la vôtre ;
- **les cerveaux posés par le bootstrap n'ont jamais rien digéré.** Ils portent zéro
  conversation et zéro atome : la digestion exige le **binaire de curation**, son
  authentification sous le compte d'agent, et les **deux interrupteurs de dépense**
  ouverts — qu'aucun essai gratuit et reproductible n'arme. Le chemin `installation → première conversation → premier
  atome` n'a donc jamais été parcouru **d'un bout à l'autre sur une installation neuve** ;
- le **tunnel SSH depuis un Mac** et le pont Claude Desktop — voir §d ;
- l'**installation complète en interactif**, de bout en bout. Seule l'étape des secrets
  l'a été, derrière un vrai pseudo-terminal (9 août 2026) : mot de passe du cockpit tapé
  deux fois aux invites `getpass`, URI TOTP affichée une seule fois, puis `POST /cc/login`
  avec ce mot de passe et un code à six chiffres → `303` vers `/cc/`, session posée,
  `/cc/v1/atoms` à `200`, mot de passe faux à `401` ;
- le rejeu depuis un Ubuntu **nu** : la machine d'essai avait déjà PostgreSQL et pgvector.

**Ce qui a cessé de manquer, et comment le rejouer.** La **restauration** d'une sauvegarde
n'est plus une hypothèse : `ops/restore_verify.sh` recharge le dump dans une base jetable,
compare, et conclut « VERDICT : PROUVÉ — ce dump se restaure, et le cerveau en sort
entier » ; le bootstrap arme cette vérification lui-même
(`arac-<base>-restauration.timer`, le dimanche à 03:00). La **bascule** du §7 de
[`docs/SAUVEGARDE.md`](docs/SAUVEGARDE.md) a été jouée sur des cerveaux **cassés pour de
vrai**, et les **gestes de désinstallation** du §13 de
[`docs/INSTALLATION.md`](docs/INSTALLATION.md) mot pour mot, jusqu'au « VERDICT : PROPRE »
en code 0 **en une seule passe** — ce qui n'a été vrai qu'à partir du moment où l'étape 7
du §13 a nommé les deux fichiers qu'elle engendre et n'effaçait pas.
`make acceptance` rejoue les deux à chaque passage, à ses étapes 8 et 9 : c'est
là qu'il faut regarder, pas ici — une case cochée dans un document se périme, un juge qui
tourne, non.

Si vous êtes la première personne à parcourir ce chemin sur une machine neuve : **notez
chaque friction.** C'est le test d'installation à l'aveugle que `GOAL.md` appelle F8, et
c'est la dernière chose qui manque.

### d. Le pont n'a pas été exercé sur un Mac

`mac/arac-sync.py` et `mac/arac-pont.sh` sont validés sur Linux contre un serveur
d'ingestion simulé. `launchctl`, `plutil`, les notifications macOS et l'emplacement réel
des données de Claude Desktop n'ont pas pu être vérifiés. La liste exhaustive de ce qui est
vérifié et de ce qui ne l'est pas est en fin de [`docs/PONT-MAC.md`](docs/PONT-MAC.md).

### e. Deux vocabulaires de sauvegarde coexistent

`ops/` (dumps chiffrés, restauration prouvée, chien de garde) lit `$ARAC_HOME/.env` et
`DATABASE_URL_*`. Le bootstrap, lui, engendre sa propre unité de sauvegarde qui lit
`/etc/arac/<base>/arac.env` et `ARAC_DB_URL_ADMIN`. Les deux fonctionnent ; ils ne se
connaissent pas. Choisissez-en un — [`docs/SAUVEGARDE.md`](docs/SAUVEGARDE.md) décrit le
premier, plus complet.

### f. Le dépôt contient encore des résidus de son origine

Des identifiants internes hérités de l'installation d'origine, des chemins de journaux
codés en dur et des renvois vers des spécifications absentes du dépôt subsistent dans les
commentaires et quelques valeurs par défaut de `app/`, `agents/` et `control_center/`. Ils
ne bloquent rien, mais ils trahissent que le portage n'est pas fini — et le premier chemin
en dur qu'on laisse passer est celui qui referme la porte qu'`arac_runtime.py` ouvre.

En revanche, **`config/brain.toml` et `config/scopes.toml` ne sont pas versionnés** :
`.gitignore` les exclut, et `git check-ignore -v config/brain.toml config/scopes.toml` le
confirme en une commande. Vous ne les recevez donc pas en clonant — c'est `bootstrap/wizard.py`
qui les écrit à partir de vos réponses. Le dépôt ne livre que les modèles commentés,
`config/scopes.example.toml` et `config/projects.example.toml`. Si vous en trouvez une
copie dans votre arborescence, elle vient d'un passage antérieur du bootstrap sur votre
machine, pas du dépôt.

---

## 8. La chaîne, de bout en bout — aucun maillon caché

```
   Claude Desktop / Claude Code (votre machine)
      │  vos conversations, stockées localement
      ▼
   synchronisation locale        mac/arac-sync.py, cadencé par launchd
      │  ne remonte que le nouveau ou le modifié ; renvoyer ne coûte rien
      ▼
   tunnel SSH  machine → serveur
      │  l'API n'écoute que 127.0.0.1 : le tunnel est la seule porte DEPUIS
      │  L'EXTÉRIEUR. Sur la machine elle-même, c'est le jeton qui fait la
      │  porte — il est exigé aussi sur 127.0.0.1 (app/auth.py)
      ▼
   ingestion (API, :<port>)      POST /v1/ingest/messages
      │  exige le jeton, vérifie le poste source, refuse l'inconnu,
      │  écrit le brut + la provenance
      │  AUCUN vecteur ici. Le message reste du texte, et ne coûte rien.
      ▼
   choix de la tranche à lire    agents/cortex/value_gate.py, agents/cortex/pack.py
      │  ce qui n'a pas encore été digéré, par curseur et par date
      │  jamais par ressemblance : aucun vecteur n'intervient dans ce choix
      ▼
   extraction / curation         agents/cortex/, 04:00 · 13:00 · 21:00
      │  un modèle lit ce texte, décide, propose. C'est ici que va l'argent.
      ▼
   atomes                        une affirmation · un domaine · une confiance · une provenance
      ▼
   embeddings                    app/services/embeddings.py
      │  c'est L'ATOME qui devient un vecteur de 3 072 nombres — jamais le message
      │  un atome = un appel. ~150 atomes/mois, pas 150 000 messages.
      ▼
   voisinage sémantique          proximité des vecteurs + domaine partagé
      │  calculé au moment de la question. Ce n'est PAS un graphe de liens
      │  raisonnés, et rien ne détecte de contradiction (§7a).
      ▼
   mémoire                       interrogeable par similarité, filtrable par domaine
      ├────────────▶ cockpit        127.0.0.1:<port>, rôle PostgreSQL en LECTURE STRICTE
      │                             GET /cc/v1/atoms · /cc/v1/atoms/{id}/story
      └────────────▶ Claude Code    POST /v1/atoms/context_for, au moment d'écrire du code
```

**L'ordre de ces maillons est la chose la plus contre-intuitive du système**, et la
plupart des outils voisins font l'inverse : ils vectorisent tout ce qui entre, puis
cherchent dedans. ARAC **lit d'abord, conclut ensuite, et ne vectorise que la
conclusion**. Vos messages bruts n'ont pas de vecteur — la table qui les stocke n'a même
pas de colonne pour en accueillir un (`db/alembic/versions/0015_ingest_v2_messages.py`).
Trois conséquences que vous constaterez dès la première semaine :

- **votre facture d'embeddings ne suit pas votre bavardage**, elle suit ce que le cerveau
  a jugé digne d'être retenu ;
- **ce qui n'est pas devenu un atome est introuvable par similarité** — il reste en base,
  horodaté et attribué, mais la recherche par le sens ne le voit pas ;
- **la qualité d'un rappel est celle de la phrase écrite par le curateur**, pas celle de la
  conversation d'origine. Un atome allusif reçoit un vecteur allusif.

Chaque maillon est repris un par un dans [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) :
ce qui entre, ce qui sort, ce qui peut mal tourner, où regarder quand ça tourne mal.

### Les trois mots à connaître avant d'installer

*(développement complet dans [`docs/CONCEPTS.md`](docs/CONCEPTS.md), définitions d'une
ligne dans [`docs/GLOSSAIRE.md`](docs/GLOSSAIRE.md))*

**Un atome** est la plus petite unité de savoir que le cerveau garde : *une* affirmation,
rangée dans *un* domaine, avec une *confiance* et une *provenance*. Ce n'est pas un
extrait de conversation — c'est ce que la conversation a permis de conclure. « Le serveur
de production est en 16.13 » est un atome ; le paragraphe qui l'a révélé n'en est pas un.

**Un vecteur** est ce qui permet de retrouver un souvenir sans se rappeler ses mots.
« Nous avons renoncé à MySQL » et « le passage à Postgres est acté » ne partagent aucun
mot : pour un `ctrl-F`, ce sont deux étrangers. Le modèle d'embeddings leur donne des
**coordonnées** — 3 072 nombres, quelle que soit la longueur du texte — et deux textes qui
parlent de la même chose atterrissent près l'un de l'autre. Chercher devient une question
de géométrie. C'est ce qui distingue « se souvenir » de « faire ctrl-F ». Et la géométrie
n'est qu'une *approximation* du sens : elle rate la négation, rate les littéraux exacts, et
ne porte aucune date. `docs/CONCEPTS.md` détaille les trois.

**Le rappel** est l'opération inverse : votre question devient un vecteur, la base rend
les atomes les plus proches, filtrés par domaine, avec une **confiance**. Sachez-le dès
maintenant : sur le cerveau de référence, **96 % des rappels sont rendus en confiance
basse**. Le cerveau trouve, mais doute. Un cerveau qui vous répond « je crois, à 40 % »
n'est pas cassé — il est honnête.

---

## 9. Où lire quoi

**Le manuel — les huit questions, dans l'ordre où on se les pose**

| Document | Quand |
|---|---|
| [`docs/MANUEL.md`](docs/MANUEL.md) | **Commencez ici.** La table des huit questions, avec une réponse à chacune et le renvoi qui la développe. |
| [`docs/COMMENT-IL-SE-NOURRIT.md`](docs/COMMENT-IL-SE-NOURRIT.md) | D'où vient la matière. Ce qui quitte votre machine, ce qui n'en sort jamais, et pourquoi ce n'est pas de la surveillance. |
| [`docs/COMMENT-IL-SE-SYNCHRONISE.md`](docs/COMMENT-IL-SE-SYNCHRONISE.md) | Le pont, de bout en bout — et la garde *fail-closed* qui refuse tout poste inconnu, avec la raison de ce refus. |
| [`docs/COMMENT-IL-CONSTRUIT-SES-ATOMES.md`](docs/COMMENT-IL-CONSTRUIT-SES-ATOMES.md) | Le cycle de digestion. Pourquoi « rien à retenir » est une vertu, et pourquoi 36 % des cycles partaient en quarantaine. |
| [`docs/COMMENT-IL-CREE-SES-SCOPES.md`](docs/COMMENT-IL-CREE-SES-SCOPES.md) | Le rangement, le compromis rigidité/dilution, et la règle qui coûte le plus cher. |

**Avant de décider si vous installez**

| Document | Quand |
|---|---|
| [`docs/POURQUOI.md`](docs/POURQUOI.md) | Les sept marches : pourquoi un cerveau personnel, pourquoi les conversations plutôt que les notes, pourquoi elles deviennent des embeddings, puis des atomes, puis des connaissances, puis un graphe, puis un rappel naturel. |
| [`docs/CE-QUE-ARAC-N-EST-PAS.md`](docs/CE-QUE-ARAC-N-EST-PAS.md) | Les six confusions levées une par une — et quand l'autre outil est le bon choix. |
| [`docs/PHILOSOPHIE.md`](docs/PHILOSOPHIE.md) | Le pari, et les raisons de **ne pas** installer ARAC. |
| [`docs/CONCEPTS.md`](docs/CONCEPTS.md) | Atome, scope, embedding, rappel, preuve — développés. |
| [`docs/PREMIER-MOIS.md`](docs/PREMIER-MOIS.md) | **À lire avant d'installer.** Ce que vous verrez aux jours 1, 3, 7 et 30 — et pourquoi vous aurez envie d'arrêter au jour 2. |
| [`docs/LIMITES-CONNUES.md`](docs/LIMITES-CONNUES.md) | **Le seul endroit où vit une limite assumée.** Ce que le cerveau ne sait pas faire, ce qui n'a jamais été éprouvé de bout en bout, ce que le système ne peut pas garantir — chaque entrée avec la commande qui la rejoue et le critère qui survivra au changement de chiffre. Le §7 de cette page en est la porte d'entrée ; c'est là que la liste est tenue. |
| [`docs/DECISIONS-ARCHITECTURE.md`](docs/DECISIONS-ARCHITECTURE.md) | **Pourquoi** ARAC est fait comme il est fait : quatorze décisions, chacune avec ce qu'elle écarte et ce qu'elle coûte. Cinq sont nées d'un incident réel qui a détruit l'accès à une production. Une décision sans prix écrit est une décision qu'on n'a pas prise. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | La chaîne complète, maillon par maillon, y compris ceux qui n'existent pas encore. |
| [`docs/GLOSSAIRE.md`](docs/GLOSSAIRE.md) | Chaque terme en une phrase, pour ne pas rester bloqué au milieu d'une page. |

**Pour installer**

| Document | Quand |
|---|---|
| [`docs/DEMARRAGE-RAPIDE.md`](docs/DEMARRAGE-RAPIDE.md) | Vous voulez un cerveau ce soir. Chemin minimal, minuté honnêtement. |
| [`docs/INSTALLATION.md`](docs/INSTALLATION.md) | Le chemin complet, avec les variantes et un point de contrôle après chaque étape. |
| [`bootstrap/README.md`](bootstrap/README.md) | Le détail des onze étapes et des quatre promesses du bootstrap. |
| [`docs/PONT-MAC.md`](docs/PONT-MAC.md) | Comment vos conversations quittent votre machine. |
| [`config/scopes.example.toml`](config/scopes.example.toml) | Le modèle commenté de taxonomie. Contient un exemple explicitement marqué « ne le copiez pas ». |

**Une fois installé**

| Document | Quand |
|---|---|
| [`docs/PREMIER-JOUR.md`](docs/PREMIER-JOUR.md) | Le cockpit s'ouvre et ne dit rien. Ce qui doit arriver, dans l'ordre, et quand. |
| [`docs/PREMIER-MOIS.md`](docs/PREMIER-MOIS.md) | « Je suis au jour 5 et je vois ceci — est-ce que ça va ? » |
| [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) | Chaque réglage : ce qu'il fait, son défaut, quand le changer, ce qui casse. |
| [`docs/DEPANNAGE.md`](docs/DEPANNAGE.md) | Quelque chose ne marche pas. Classé par **symptôme**. |
| [`docs/EXPLOITATION.md`](docs/EXPLOITATION.md) | Surveiller, diagnostiquer, réparer un cerveau en service. |
| [`docs/SAUVEGARDE.md`](docs/SAUVEGARDE.md) | Sauvegarder, et **prouver** qu'on sait restaurer. Le § 7 est la restauration réelle, celle qu'on exécute en panique ; le § 9 est le déménagement vers une autre machine. |
| [`docs/INSTALLATION.md` § 13](docs/INSTALLATION.md#13-désinstaller) | **Partir.** Faire disparaître ce cerveau de cette machine, ou repartir avec lui — et le contrôle qui refuse de dire « propre » tant qu'il en reste une copie. |
| [`docs/FAQ.md`](docs/FAQ.md) | Combien ça coûte, où vont mes données, puis-je changer de modèle, et si je perds le serveur. |

**Pour toucher au code**

| Document | Quand |
|---|---|
| [`docs/CONTRIBUER.md`](docs/CONTRIBUER.md) | La doctrine du dépôt : ce qu'on peut y écrire, ce qu'on ne peut pas, et pourquoi. |
| [`docs/DECISIONS-ARCHITECTURE.md`](docs/DECISIONS-ARCHITECTURE.md) | Avant de proposer un changement de fond : ce qui a déjà été tranché, ce qui a été écarté, et à quel prix. Les trois dernières décisions disent comment le dépôt se garde lui-même. |
| [`docs/RELEASE-V1.md`](docs/RELEASE-V1.md) | Le dossier de publication : le critère de sortie, l'échelle P0-P3, ce que la V1 démontre et par quoi, et le **registre des constats ouverts** — ce qui reste su et non corrigé, avec sa classe. |
| [`GOAL.md`](GOAL.md) | Ce que « terminé » veut dire, en huit assertions vérifiables. |

---

## 10. La première décision est la vôtre

`python3 bootstrap/wizard.py` vous pose cinq questions. La quatrième est la seule qui
compte vraiment : **comment découpez-vous votre vie ?** Cinq à huit domaines, chacun avec
deux ou trois rangements. L'assistant propose des catégories génériques ; il n'impose
jamais celles de quelqu'un d'autre.

Prenez ce moment au sérieux. Une taxonomie choisie au hasard produit un cerveau qui range
mal, et vous ne vous en apercevrez pas avant six mois.

**Et retenez déjà ceci :** les souvenirs vivent sur les **feuilles**, jamais sur les
racines. Un atome posé sur une racine existe en base, mais il est exclu de tout ce que le
cerveau construit au-dessus du rangement — pas d'état courant, pas de place dans la vue
des scopes, pas de comptage dans la couverture. Il devient un souvenir orphelin. Sur le
cerveau de référence, **près d'un souvenir actif sur onze** est tombé dans ce piège.
C'est le piège numéro un, et il ne fait aucun bruit.

*Le compte exact du jour, et la requête qui le donne, sont au § 3 de
[`docs/COMMENT-IL-CREE-SES-SCOPES.md`](docs/COMMENT-IL-CREE-SES-SCOPES.md) — **seul
endroit du dépôt qui porte ce chiffre**, pour qu'aucune copie ne diverge. Le mécanisme
exact — y compris ce dont un tel atome n'est **pas** exclu — est au § 4 du même document.*

---

<p align="center">
  <img src="assets/logo.svg" alt="" width="40" height="40"><br>
  <strong>ARAC BRAIN</strong> — un projet <a href="https://linkedin.com/in/renlew">Ren LEW</a><br>
  <sub>MIT · <a href="docs/LIMITES-CONNUES.md">Limites connues</a> · <a href="docs/DECISIONS-ARCHITECTURE.md">Décisions d'architecture</a> · <a href="SECURITY.md">Sécurité</a></sub>
</p>
