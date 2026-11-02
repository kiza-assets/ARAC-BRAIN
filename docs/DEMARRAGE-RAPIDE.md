# Démarrage rapide — un cerveau qui vit, ce soir

Ce document est le chemin le plus court. Il ne montre qu'une variante de chaque choix.
Si quelque chose sort du cadre — PostgreSQL sur une autre machine, pas de Mac, deux
cerveaux sur un même serveur — allez directement à [`INSTALLATION.md`](INSTALLATION.md),
qui traite les variantes.

---

## Le temps que ça prend, sans mentir

| Situation de départ | Durée réaliste |
|---|---|
| Ubuntu 24.04, PostgreSQL 16 + pgvector et le binaire `claude` déjà installés, la clé d'embeddings sous la main | **~1 heure** |
| Ubuntu 24.04 nu, tout à installer | **une demi-journée** |
| + brancher votre Mac et voir arriver la première conversation | **+ 1 à 2 heures** |

Les vingt minutes n'existent pas. L'essentiel du temps n'est pas passé à taper des
commandes : il est passé à **décider de la forme de votre mémoire** (étape 2) et à
attendre le premier cycle de digestion (étape 9).

**Le minutage, étape par étape** — et, en face, la phrase qui prouve que ça a marché :

| Étape | Durée | Ce qu'on doit voir quand ça marche |
|---|---|---|
| 0 · vérifier le dépôt | 2 min | **trois** lignes, pas une : le garde des noms vert, le bloc « ce que cette session a réellement emprunté », et la ligne pytest sans `failed` |
| 1 · prérequis serveur | 15 min (5 s si tout est là) | `✓ Tout est là. Votre serveur peut porter un cerveau — et le digérer.` |
| 2 · l'entretien | 5 à 15 min | `config/brain.toml` et `config/scopes.toml`, et rien d'autre |
| 3 · la simulation | 5 min | `[simulation] Aucun changement n'a été appliqué.` |
| 4 · installer | 15 à 30 min | `✓ Accomplies : prereqs config base … controle` |
| 5 · vérifier les raccords | 2 min | le `node_id` rendu par `psql` · les deux vocabulaires présents |
| 6 · vérifier | 2 min | un verdict où **`en échec` vaut 0** |
| 7 · ouvrir le cockpit | 5 min | `Le cerveau n'a rien appris depuis 24 heures.` |
| 8 · brancher la machine source | 30 à 90 min | au 2ᵉ passage : « Rien de nouveau » |
| 9 · le premier cycle | 5 min | `… j'ai appris 3 conversation(s) et créé 4 atome(s) de savoir.` |
| 10 · la sauvegarde | 15 min | une restauration réelle, réussie, dans une base jetable |

**Une étape qui n'affiche pas sa phrase n'est pas finie.** Ne passez pas à la suivante en
espérant que ça se rattrape : dans une chaîne, une panne silencieuse se déguise toujours
en panne de l'étape d'après.

**Ce qu'il faut avoir sous la main avant de commencer**, sinon vous vous arrêterez au
milieu :

- un accès `sudo` sur le serveur ;
- **le binaire `claude` (Claude Code CLI) installé sur le SERVEUR** —
  `sudo npm install -g @anthropic-ai/claude-code`. **C'est le vrai prérequis de la
  curation, et ce n'est pas une clé d'API** : le cycle de digestion ne parle à aucune
  API, il *lance ce binaire* en sous-processus. Sans lui, votre cerveau ingérera et
  n'apprendra jamais rien. L'étape 1 le constate désormais ;
- **de quoi authentifier ce binaire — une seule des deux façons suffit** : une session
  d'abonnement Claude ouverte **pour le compte d'agent du cerveau**, ou une clé d'API
  Anthropic (facturée à l'appel). Si vous avez déjà un abonnement, **vous n'avez pas de
  clé de curation à acheter** ;
- **une clé d'API OpenAI** (embeddings) — c'est la seule clé qu'ARAC lise lui-même.
  Voir le coût en
  [première page du README](../README.md#4-ce-que-ça-coûte--en-première-page-parce-que-cest-un-contrat) ;
- une application d'authentification à deux facteurs sur votre téléphone (Aegis, Raivo,
  1Password, Google Authenticator…), pour le cockpit ;
- 20 Go de disque libre.

> **L'erreur la plus coûteuse qu'on puisse faire avant de commencer** : acheter une clé
> d'API Anthropic en croyant que c'est elle qui digère. Elle ne digère rien toute seule —
> c'est le binaire qui digère, et c'est lui qui lit la clé, si tant est qu'il en ait
> besoin. Le tableau complet — ce qu'il faut posséder, ce qu'il faut acheter, ce que
> chaque chose paie, et ce que le bootstrap vérifie ou non — est en
> [README §5](../README.md#5-ce-quil-vous-faut-et-ce-que-vous-naurez-pas).

---

## Étape 0 — Vérifier le dépôt avant de toucher au serveur — 2 min

À faire sur n'importe quelle machine, y compris votre portable. Aucune base, aucun
réseau, aucune clé.

```bash
git clone <l-adresse-de-ce-depot> arac
cd arac
make venv        # crée .venv et installe les dépendances (accès réseau requis)
make test
```

**Ce que vous devez voir — trois choses, et la ligne verte est la troisième.**

Ce paragraphe a longtemps demandé une seule chose : une ligne verte sans `failed`.
**Ce critère a été satisfait par une livraison cassée** — le dépôt affichait des milliers
de tests verts pendant que deux routes du tableau de bord rendaient 500 sur un cerveau
neuf et que la commande d'arrêt d'urgence de l'IA payante mourait à sa première ligne.
Aucun test n'était faux ; aucun n'était passé par là. Le raisonnement complet est en
[première page du README](../README.md#6-le-chemin-le-plus-court-vers-un-cerveau-qui-vit),
et c'est lui qui fait autorité. Les trois lignes, dans l'ordre où elles apparaissent :

1. **`tests/test_aucun_nom_non_resolu.py` est vert.** Il charge tout ce que le produit
   charge et demande à Python, pour chaque nom, s'il existe. C'est la seule des trois qui
   prouve une **négative universelle**.
2. **Le bloc « CE QUE CETTE SESSION A RÉELLEMENT EMPRUNTÉ »**, imprimé en fin de suite. Il
   ne rougit pas : il **mesure**. Lisez-le comme la carte de ce sur quoi le vert se tait.
3. **La ligne de pytest, sans `failed`**, de cette forme :

```
<N> passed, <M> skipped, <K> deselected, <X> xfailed, <W> warnings in <T>s
```

> **Sur cette troisième ligne, le critère est `failed` absent — pas les nombres.** Ils
> montent à chaque test ajouté au dépôt, donc le vôtre ne correspondra ni à celui d'un
> autre lecteur, ni à celui qu'un document afficherait. C'est pour cela qu'aucun compte
> exact n'est donné comme point de passage, ici ni ailleurs dans cette documentation — pas
> même celui-ci. **La durée non plus** : ce gabarit annonçait « in ~20s », et la suite met
> plusieurs fois cela sur un serveur modeste. Une durée écrite dans un manuel ne mesure que
> la machine de celui qui l'a écrite.
>
> **Et une quatrième ligne existe, qu'on n'obtient pas ici** : `sudo make acceptance`
> installe un cerveau réel et lui fait vraiment écrire, casser, restaurer. Elle demande une
> machine — c'est l'étape 10.

Les tests « skipped » ne sont pas des échecs cachés : ce sont les tests qui
exigeraient une base ou une clé d'API et qui **se déclarent ignorés** plutôt que de
rougir. C'est délibéré — un test rouge doit vouloir dire « le code est cassé », jamais
« PostgreSQL n'est pas lancé ».

> Si `make test` échoue ici, ne continuez pas : le problème est dans le dépôt ou dans
> votre Python, pas dans votre serveur.

---

## Étape 1 — Les prérequis du serveur — 15 min (ou 5 s si tout est là)

Sur le serveur, dans le dépôt cloné :

```bash
./bootstrap/bootstrap.sh --check
```

Cette commande **ne fait que constater**. Elle n'installe rien, ne demande rien, et
n'écrit pas une ligne.

**Ce que vous devez voir** — **une ligne `✓` par prérequis**, chacune disant à quoi il
sert, puis le rappel de ce que le bootstrap exigera du réseau, puis le verdict. Les
premières portent en plus la version **trouvée sur votre machine** :

```
  ✓ Ubuntu / Debian         systemd, apt et les chemins supposés par les gabarits (…)
  ✓ Python ≥ 3.11           … — trouvé <votre version>
  ✓ psql (client)           … — <votre version>
  ✓ PostgreSQL 16 (serveur) la mémoire elle-même
  ✓ pgvector                … — v<votre version>
  ✓ git   ✓ ssh   ✓ systemd   ✓ sudo   ✓ openssl      (une ligne chacun, abrégées ici)

  La curation — ce qui digère vos conversations en souvenirs

  ✓ claude (Claude Code CLI)digérer vos conversations : le cycle LANCE ce binaire,
                            il n'appelle aucune API — <votre version>
  ✓   son authentification  session d'abonnement ouverte pour CE compte
  …
  ✓ Tout est là. Votre serveur peut porter un cerveau — et le digérer.
```

> **La section « La curation » est nouvelle, et c'est la plus importante de cet écran.**
> Elle a été ajoutée après qu'une installation entière soit passée au vert **sans**
> pouvoir apprendre : dix prérequis, dix `✓`, un verdict « Tout est là » — et un cerveau
> qui ingérait sans jamais produire un souvenir, parce que le binaire `claude` n'était
> pas là. **Le verdict distingue désormais les deux** : « porter un cerveau » et « le
> digérer » ne sont pas la même promesse.
>
> **Si le binaire manque**, l'écran ne dit ni « ✓ » ni « installation impossible ». Il dit
> exactement ceci, et l'installation peut continuer — mesuré :
>
> ```
>   ⚠ claude (Claude Code CLI)ABSENT — sans lui, votre cerveau ingérera sans jamais apprendre.
>   …
>       sudo npm install -g @anthropic-ai/claude-code
>   Si votre binaire n'atterrit pas dans le PATH du service (nvm, npm
>   sous préfixe utilisateur…), nommez-le au lieu de le déplacer :
>       echo 'ARAC_CLAUDE_BIN=/chemin/absolu/vers/claude' | sudo tee -a /etc/arac/<votre-base>/arac.env
>   …
>   ✓ Le serveur peut porter un cerveau.
>   ⚠ Mais PAS le faire apprendre : le binaire de curation manque (voir ci-dessus).
> ```
>
> **C'est le seul prérequis qui n'arrête pas l'installation**, et c'est délibéré : un
> cerveau sans lui naît, ingère et se laisse interroger sur ce qu'il sait déjà. Il
> n'apprend simplement jamais rien de neuf.

> **Ce bloc est abrégé, et les versions sont celles de la machine d'essai, pas les
> vôtres.** Le seul critère est la dernière ligne : `✓ Tout est là.` Ni le nombre de
> lignes ni les numéros de version ne sont un point de passage — la liste des prérequis
> grandira, et vos versions seront les vôtres. **Un prérequis manquant se voit** : sa ligne
> porte `✗` au lieu de `✓`, et à la place du verdict le script imprime « *N* prérequis
> manquant(s) », puis « Les commandes exactes, dans l'ordre : » et les `apt install` à
> taper. Avec `--check`, il sort là, sans rien installer à votre place
> (`bootstrap/lib/prereqs.sh`).

**S'il manque quelque chose**, chaque ligne rouge porte la commande exacte. Le cas
général :

```bash
sudo apt update
sudo apt install -y postgresql-16 postgresql-16-pgvector postgresql-client-16 \
                    python3 python3-venv python3-pip git openssh-client
sudo systemctl enable --now postgresql
```

Puis relancez `./bootstrap/bootstrap.sh --check` jusqu'au vert.

> **Le piège de pgvector** : le paquet est lié à la version majeure de PostgreSQL. Si
> vous êtes en 15 ou en 17, `postgresql-16-pgvector` ne servira à rien. Adaptez le
> numéro, et vérifiez avec :
> ```bash
> sudo pg_lsclusters                 # les grappes de CETTE machine, et leurs ports
> PGPORT_BASE=<le_port_de_votre_grappe>   # celui où ce cerveau va vivre
> sudo -u postgres psql -p "$PGPORT_BASE" -tAc \
>   "SELECT default_version FROM pg_available_extensions WHERE name='vector'"
> ```
>
> Vous devez obtenir un numéro de version **≥ 0.7.0**, pas une ligne vide. Ubuntu 24.04
> livre 0.6.0, trop ancien (le type `halfvec` manque) : activez d'abord le dépôt officiel
> PostgreSQL, `sudo apt install -y postgresql-common && sudo
> /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh`, puis réinstallez
> `postgresql-16-pgvector`. Voir `docs/DEPANNAGE.md` §3. **Le `-p` désigne la grappe
> où votre cerveau va vivre** : sans lui, la réponse vient de la grappe **par défaut** de
> la machine, et vous installeriez pgvector pour la mauvaise majeure de PostgreSQL.
>
> **Et le numéro n'est pas deviné pour vous, délibérément.** Une machine neuve n'en a
> qu'une, et `pg_lsclusters` vous la montre en une ligne ; une machine qui en porte
> plusieurs n'a pas de « bonne » réponse automatique — prendre la première de la liste
> serait exactement le genre de choix silencieux que cette page vous apprend à refuser.
> Après l'installation, ce numéro ne se choisit plus : il se **lit**, dans
> `/etc/arac/<votre_base>/arac.env`.

> **Le piège du 3.11** : cette étape se contente de Python ≥ 3.11 — c'est ce qu'il faut
> pour lire votre taxonomie. Mais `pyproject.toml` exige **3.12**, et `pip install`
> échouera à l'étape 4. Si `python3 --version` vous rend 3.10 ou 3.11 (Ubuntu 22.04),
> réglez-le maintenant : un prérequis qui passe au vert puis casse trois étapes plus loin
> est exactement ce que cette page essaie de vous épargner.

---

## Étape 2 — L'entretien : votre cerveau prend forme — 5 à 15 min

```bash
python3 bootstrap/wizard.py
```

**Cinq questions.** Il n'installe rien, ne touche à aucune base, et n'écrit que deux
fichiers : `config/brain.toml` (qui vous êtes, d'où viennent vos conversations) et
`config/scopes.toml` (la forme de votre mémoire).

La quatrième question est la seule qui compte vraiment : **comment découpez-vous votre
vie ?** L'assistant propose des catégories génériques — travail, projets, personnel,
famille, finance, santé, outillage, savoir — et vous en choisissez, renommez, ajoutez.
Ce sont vos domaines, pas ceux de quelqu'un d'autre.

**Deux règles à garder en tête pendant que vous répondez :**

1. **Les souvenirs vivent sur les feuilles.** Une racine (`travail`) est un conteneur ;
   une feuille (`travail/strategie`) est un rangement. Un atome posé sur une racine
   existe en base, et il peut encore remonter sur une question qui lui ressemble — mais il
   est exclu de l'état courant, de la vue des scopes et de la couverture, et aucune
   recherche qui précise un domaine ne le trouvera. Sur le cerveau de référence, près d'un
   souvenir actif sur onze est tombé dedans.
2. **Cinq à huit racines suffisent presque toujours**, trois à six feuilles chacune
   (l'ordre de grandeur est argumenté dans
   [`COMMENT-IL-CREE-SES-SCOPES.md`](COMMENT-IL-CREE-SES-SCOPES.md) §5). Une feuille qui n'atteint pas
   10 atomes en six mois n'aurait pas dû exister ; une feuille qui dépasse 250 atomes
   gagnerait à être scindée. Ordre de grandeur observé : ~150 atomes par mois.

**Ce que vous devez voir à la fin** — vos deux fichiers, et rien d'autre :

```bash
cat config/brain.toml     # [brain] owner/name, [source] node_id
head -20 config/scopes.toml
```

Vous pouvez interrompre l'entretien (`Ctrl-C`) : rien n'aura été écrit, et
`python3 bootstrap/wizard.py --resume` reprend là où vous en étiez.

> **`[source].node_id`** est l'identifiant du poste d'où vos conversations arriveront.
> Ce n'est pas décoratif : le cerveau **refuse** toute conversation venant d'un nœud non
> déclaré. C'est ce garde-fou qui l'empêche d'avaler n'importe quoi — et c'est aussi la
> cause n°1 des cycles perdus quand il est incohérent entre le serveur et la machine
> source (36 % des cycles du cerveau de référence).

---

## Étape 3 — Voir l'installation avant de la subir — 5 min

```bash
./bootstrap/bootstrap.sh --dry-run
```

Rien n'est écrit, rien n'est créé, aucune base n'est ouverte autrement qu'en lecture.
Vous verrez défiler les onze étapes, chacune annonçant **pourquoi elle existe**, **ce
qu'elle construit** et **ce que cela changera** dans le comportement de votre cerveau.

**Ce que vous devez voir** — le récapitulatif de ce que vos réponses engendrent :

```
  Ce que ces réponses engendrent
     serveur           127.0.0.1:<le port de VOTRE grappe PostgreSQL>
     base              <votre_base>   (schéma arac)
     rôles             arac_<votre_base>_admin · arac_<votre_base>_app · … _agent · … _readonly
     secrets           /etc/arac/<votre_base>/   (0700, root)
     environnement     /etc/arac/<votre_base>/arac.env
     services          arac-<votre_base>-api · -cockpit · -cycle · -sauvegarde
     API               127.0.0.1:<un port constaté libre, puis retenu>
     cockpit           127.0.0.1:<un autre>
     cycles            04:00 13:00 21:00 (<votre fuseau>)
     sauvegardes       /var/backups/arac/<votre_base>
  ...
  ✓ Seraient accomplies : prereqs config base vecteurs migrations scopes secrets cles services controle
  [simulation] Aucun changement n'a été appliqué.
```

**Chaque ligne porte le nom de votre cerveau, et ce n'est pas de la cosmétique.** Les
rôles PostgreSQL sont globaux au cluster : sans ce préfixe, installer un second cerveau
réencode les mots de passe du premier. C'est ce qui a détruit le cerveau de production de
l'auteur. **Les deux ports non plus ne sont pas choisis d'avance** : l'étape 2 en constate
deux libres, les attribue, et les écrit dans `arac.env`. Sur une machine qui héberge déjà
un cerveau, ils ne seront pas les mêmes que les siens — notez-les, le tunnel de l'étape 7
en aura besoin.

**Lisez ce récapitulatif.** C'est le dernier moment où changer d'avis coûte zéro : une
fois la base créée et le premier cycle passé, changer le nom du cerveau ou le `node_id`
demande une migration.

---

## Étape 4 — Installer — 15 à 30 min

```bash
sudo ./bootstrap/bootstrap.sh
```

> **▸ Si cette machine porte DÉJÀ un cerveau, ne tapez pas cette ligne-là.** Sans rien de
> plus, le bootstrap installe sur la grappe **par défaut** — 5432, celle du voisin — et y
> pose cinq rôles, qui sont **globaux à la grappe**. Rien n'échouera, rien ne vous
> avertira. Le port choisi à l'étape 1 se transmet par **une variable, et une seule** :
>
> ```bash
> sudo pg_createcluster 16 <nom> --port <port> --start   # si la grappe n'existe pas encore
> sudo ARAC_DB_PORT=<port> ./bootstrap/bootstrap.sh
> ```
>
> Vous ne la repasserez plus : l'installation **retient** ce port dans
> `/etc/arac/<votre_base>/arac.env` et le relit ensuite ; en demander un autre fait
> **refuser** le bootstrap (code 6) avant qu'il n'écrive quoi que ce soit. Le pourquoi et
> le contrôle sont au [§12.f d'`INSTALLATION.md`](INSTALLATION.md#f-une-grappe-postgresql-pour-ce-cerveau).

Il vous demandera trois choses, dans cet ordre : un **mot de passe administrateur**
pour le cockpit (jamais affiché, stocké haché), l'**appairage TOTP** (une URI `otpauth://`
et un secret base32, à ajouter dans votre application d'authentification), et enfin vos
**clés externes** — la clé d'embeddings, lue par ARAC, et la clé de curation, que seul
le binaire `claude` lira (inutile si votre abonnement est déjà ouvert pour le compte
d'agent). Vous pouvez refuser les deux.

> **⚠ L'appairage TOTP n'est pas vérifié, et l'URI n'est affichée qu'une fois.** Le
> bootstrap imprime l'URI et la clé, puis demande « Appairage effectué ? » — mais il ne
> vous demande **aucun code à six chiffres** et ne valide rien : quelle que soit votre
> réponse, il continue. Si vous avez mal recopié la clé, vous ne l'apprendrez qu'à l'étape
> 7, devant le cockpit, **quand l'URI aura disparu de votre écran**. Le seul recours est
> alors d'aller supprimer la ligne `ARAC_CC_TOTP_SECRET` de
> `/etc/arac/<votre_base>/cockpit.env` (accès root) et de relancer
> `sudo ./bootstrap/bootstrap.sh --only secrets`.
>
> **Le geste qui vous évite cela** : tant que l'URI est encore à l'écran, ouvrez un second
> terminal et connectez-vous au cockpit (**étape 7** de ce guide — cette page numérote des
> étapes, pas des §). Trente secondes, et vous savez.
> C'est le seul secret de tout le parcours qui, mal recopié, ferme une porte pour de bon.

L'étape 5 (migrations) est la plus longue : `pip install` télécharge les dépendances, puis
`alembic upgrade head` applique **toute la chaîne**, de la première révision à la dernière.

> **Ce guide ne vous donne ni le nombre de révisions ni le nom de la dernière**, et ce
> n'est pas une omission. Ces deux valeurs changent à chaque migration ajoutée : la version
> précédente de ce paragraphe annonçait « 32 révisions, jusqu'à `0033_atom_links` » et
> fournissait même le `wc -l` censé le prouver — les deux étaient faux le jour où
> `0034_memory_review_queue` est arrivé, et le lecteur voyait défiler une révision qu'on ne
> lui avait pas annoncée. **Le compte du jour, c'est le bootstrap qui vous le dit**, à
> l'écran, au moment où il s'en sert : l'en-tête de l'étape 5 imprime
> « *N* migration(s) trouvée(s) ». Un nombre lu là est vrai ; le même nombre recopié ici ne
> l'est que jusqu'à la migration suivante.

**Ce que vous devez voir à la fin** : le bilan, puis l'épilogue « La suite : brancher le
Mac », qui contient la chaîne complète et vos commandes personnalisées.

```
  ✓ Accomplies : prereqs config base vecteurs migrations scopes secrets cles services controle
```

**Si une étape échoue**, le message dit *ce qui a échoué*, *pourquoi*, et *le geste
exact*. Réparez, puis reprenez — rien de ce qui a été fait n'est perdu :

```bash
sudo ./bootstrap/bootstrap.sh --from migrations
```

---

## Étape 5 — Constater les deux raccords — 2 min

Deux raccords décident si votre cerveau peut recevoir quoi que ce soit, et un troisième
décide si vous pourrez le regarder. **Le bootstrap pose les deux premiers ; le troisième
reste à votre charge.** Un raccord qu'on n'a jamais regardé est un raccord dont on ne sait
rien — et tous échouent en silence côté serveur.

### 1. Le pont de vocabulaire

Le bootstrap écrit ses variables sous des noms préfixés (`ARAC_DB_URL_APP`…) ; le moteur,
lui, lit encore les noms historiques (`DATABASE_URL_APP`…). À la fin de son étape des
clés, le bootstrap **copie** les unes vers les autres — les deux noms cohabitent alors
dans le même fichier (`poser_pont_de_vocabulaire`, `bootstrap/lib/secrets.sh`). Il
l'annonce à l'écran :

```
  ✓ Pont de vocabulaire posé : N variable(s) traduite(s) pour le moteur.
```

**Ce n'est pas cette page qui vous donne N**, et c'est délibéré : elle a écrit « 7 », puis
« 5 ou 7 », et les deux étaient faux le jour où la traduction des **trois secrets du
cockpit** a été ajoutée à la même fonction. Le bootstrap, lui, imprime sa propre fourchette
juste sous le compte, à l'écran, au moment où il s'en sert — c'est là qu'il faut la lire, et
elle est vraie par construction. **Ce nombre n'est de toute façon pas un critère de
réussite.** Le critère, ce sont les deux `grep` ci-dessous, et ils ne bougent pas :

```bash
sudo grep -c '^DATABASE_URL_' /etc/arac/<votre_base>/arac.env
```

**Ce que vous devez voir** : `4` — les quatre rôles (`ADMIN`, `APP`, `AGENT`,
`READONLY`).

**Et le contrôle qui décide si votre cockpit s'ouvrira** :

```bash
sudo grep -cE '^(CC_SESSION_SECRET|CC_ADMIN_PASSWORD_HASH|CC_TOTP_SECRET)=' \
     /etc/arac/<votre_base>/cockpit.env
```

**Ce que vous devez voir** : `3` — les trois secrets que le cockpit lit réellement.
Le bootstrap les traduit lui-même : il les engendre sous ses propres noms (`ARAC_CC_*`)
puis les recopie sous ceux que le cockpit lit, **dans le même fichier**
(`bootstrap/lib/secrets.sh`, `poser_pont_de_vocabulaire`).

> **Ce que ce paragraphe disait jusqu'en août 2026** : « ce que vous verrez aujourd'hui :
> `0` », suivi d'un geste manuel à faire soi-même. C'était vrai, et c'était la dernière
> intervention humaine du parcours — celle que `make acceptance` comptait contre lui-même.
> Elle n'existe plus : le pont de vocabulaire traite les deux fichiers. Si ce `grep` rend
> `0` chez vous, votre installation est **antérieure** à ce correctif, et le geste manuel
> est dans
> [`DEPANNAGE.md` §1](DEPANNAGE.md#1-lapi-ne-démarre-pas--database_url_app-non-définie).

Si le premier `grep` rend `0`, votre installation est antérieure à ce correctif :
le geste manuel, idempotent et testé, est dans
[`DEPANNAGE.md` §1](DEPANNAGE.md#1-lapi-ne-démarre-pas--database_url_app-non-définie).

### 2. Les deux portes de l'ingestion

L'ingestion n'accepte une conversation que si le poste qui la dépose est **déclaré deux
fois** : dans la liste blanche `ARAC_INGEST_ALLOWED_NODES`, et dans la table `arac.nodes`.
Les deux sont **fail-closed** — liste absente ou vide, et l'API répond `403` à tout, y
compris à votre propre Mac muni d'un jeton valide.

C'est une bonne protection, et elle est déjà en place : le bootstrap écrit la liste
blanche depuis l'identité de votre entretien (`bootstrap/lib/secrets.sh`), et la migration
`0008` déclare votre poste dans `arac.nodes` en lisant le même `config/brain.toml`. Vous
n'avez rien à poser — vous avez à **vérifier que les trois chaînes coïncident** :

```bash
BASE=<votre_base>          # brain.name de config/brain.toml
PGPORT_BASE=$(sudo sed -n 's/^ARAC_DB_PORT=//p' "/etc/arac/$BASE/arac.env")

# ce que le serveur autorise
sudo grep '^ARAC_INGEST_ALLOWED_NODES=' "/etc/arac/$BASE/arac.env"

# ce que la base connaît — sur SA grappe, pas sur celle par défaut de la machine
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc "SELECT node_id FROM arac.nodes"

# ce que votre entretien a décidé
grep '^node_id' config/brain.toml
```

**Ce que vous devez voir** : le `node_id` de votre `config/brain.toml` présent dans les
deux autres réponses. Un tiret de plus suffit à tout perdre — c'est la cause n° 1 des
conversations qui n'arrivent jamais.

> **Deux valeurs de plus existent, et les deux sont normales.**
> · La requête sur `arac.nodes` rend **deux** lignes, pas une : la migration `0020`
>   déclare aussi `<votre-node-id>-server`, le poste que le serveur représente pour
>   l'inventaire des sources d'ingestion. Il naît `active = false` et rien n'ingère sous ce
>   nom — `SELECT node_id, active FROM arac.nodes ORDER BY 1` le montre.
> · L'unité systemd du cycle, elle, tourne sous `<votre-node-id>-cycle`
>   (`bootstrap/lib/services.sh`). C'est voulu : le cycle n'ingère rien, il ne franchit
>   jamais la liste blanche.
>
> Les trois chaînes à comparer sont celles ci-dessus, pas celles-là.

Le détail des trois portes est dans
[`DEPANNAGE.md` §7](DEPANNAGE.md#7-http-403--le-serveur-refuse-ce-poste).

---

## Étape 6 — Vérifier — 2 min

```bash
sudo ./bootstrap/checks/verify_install.sh
```

Il ne modifie rien. Il lit, il compte, il dit. **Le nombre de familles, ce n'est pas
cette page qui vous le donne** : `./bootstrap/checks/verify_install.sh --simulation` les
annonce lui-même, sans rien exiger d'installé. Deux d'entre elles méritent d'être
connues : il **tente réellement une écriture** avec le rôle du cockpit, et cette écriture
doit **échouer** ; et il **frappe à la porte de l'API sans jeton**, en attendant un `401`.
C'est la différence entre vérifier une garantie et faire confiance à une promesse.

**Ce que vous devez voir** — le verdict, puis l'une de ces deux phrases :

```
  Verdict
  ───────
  sains <N>    à surveiller <M>    en échec 0

  ✓ Ce cerveau fonctionne.
```

**Le seul chiffre qui compte est `en échec 0`.** Le nombre de contrôles sains dépend de
votre installation : ne le comparez à rien. Et il y a **deux** phrases de réussite, pas
une :

- `✓ Ce cerveau est sain.` — zéro échec **et** zéro point à surveiller ;
- `✓ Ce cerveau fonctionne.` — zéro échec, mais des points à surveiller. Ils ne
  l'empêchent pas de vivre ; ils disent ce qu'il ne sait pas encore faire. Vous verrez
  souvent celle-ci au premier passage, et ce n'est pas un échec.

**Si vous voyez des ✗**, le script conclut `✗ Ce cerveau n'est pas sain.` et rend un code
de sortie non nul. Chaque ligne en échec porte le geste exact qui la corrige : reprenez-les
dans l'ordre, puis relancez.

---

## Étape 7 — Ouvrir le cockpit — 5 min

> **Refaites d'abord le contrôle de l'étape 5.** Le cockpit est *fail-closed* : sans ses
> trois secrets sous les noms que lui-même lit, il répond `503` à toute connexion, mot de
> passe correct compris. Le bootstrap les traduit désormais lui-même — mais tant que
> `sudo grep -cE '^(CC_SESSION_SECRET|CC_ADMIN_PASSWORD_HASH|CC_TOTP_SECRET)='
> /etc/arac/<votre_base>/cockpit.env` ne rend pas `3`, **cette étape échouera**, et l'échec
> ressemblera à un mot de passe refusé, ce qu'il n'est pas. Si le compte n'y est pas, le
> geste manuel de l'étape 5 le pose.

Le cockpit n'écoute que sur la boucle locale du serveur. Depuis **votre machine** :

D'abord, relevez **vos** deux numéros, sur le serveur :

```bash
BASE=<votre_base>
API=$(systemctl show "arac-$BASE-api"     -p ExecStart --value | sed -n 's/.*--port \([0-9]\{1,\}\).*/\1/p')
CC=$( systemctl show "arac-$BASE-cockpit" -p ExecStart --value | sed -n 's/.*--port \([0-9]\{1,\}\).*/\1/p')
echo "API $API · cockpit $CC"
```

Puis, depuis votre machine, avec ces deux valeurs :

```bash
API=<le port API relevé>   CC=<le port cockpit relevé>
ssh -N -L "$CC:127.0.0.1:$CC" -L "$API:127.0.0.1:$API" <utilisateur>@<votre-serveur>
```

Laissez ce terminal ouvert, puis ouvrez `http://127.0.0.1:<le port cockpit>` dans votre
navigateur. Sur un Mac, `mac/arac-pont.sh tunnel ouvrir` fait tout cela seul, en lisant les
deux numéros dans `~/.arac/<votre_base>/pont.conf`.

**Ce que vous devez voir** : une demande de mot de passe, puis une demande de code à six
chiffres. C'est le mot de passe et le second facteur de l'étape 4.

Ensuite, la synthèse. À ce stade elle sera honnête et décevante — c'est normal :

```
  Le cerveau n'a rien appris depuis 24 heures.
```

Le cerveau est né. Il ne sait rien. Il lui manque vos conversations.

---

## Étape 8 — Brancher la machine source — 30 à 90 min

C'est le seul morceau que ce document ne détaille pas : il a le sien,
[`PONT-MAC.md`](PONT-MAC.md), et il en a besoin.

Le résumé en cinq gestes, sur votre Mac :

```bash
./arac-pont.sh installer          # ~/.arac, la configuration, trois questions
./arac-pont.sh cle-ssh            # la clé du tunnel, bridée côté serveur
./arac-pont.sh premiere-synchro   # le trajet complet, raconté
./arac-pont.sh automatiser        # launchd prend le relais
./arac-pont.sh etat               # à tout moment : quel maillon est cassé ?
```

**Trois choses à savoir avant de lancer quoi que ce soit :**

- **Au premier lancement, rien n'est envoyé.** Le pont liste ce qu'il a trouvé et vous
  rend la main. Ces conversations contiennent une vie : vous devez voir ce qui part
  avant que ça parte.
- **Il n'existe aucune capture automatique de Claude Desktop.** L'application ne garde
  rien de lisible en local ; la seule voie stable est l'export officiel de claude.ai,
  manuel. Claude Code (CLI) est capté automatiquement.
- **Renvoyer ne coûte rien.** Le serveur déduplique par message.

**Ce que vous devez voir** au deuxième passage de synchronisation : `code=0` et
« Rien de nouveau ». Si des messages repartent, l'état ne se sauve pas — vérifiez les
droits de `~/.arac`.

**Sans Mac** : `mac/arac-sync.py` est du Python de la bibliothèque standard, il tourne
sur Linux, y compris sur le serveur lui-même — le tunnel devient alors inutile.
L'ordonnancement se fait par `deploy/systemd/arac-pont-sans-mac.{service,timer}.modele`.

---

## Étape 9 — Le premier cycle — 5 min d'attente, ou jusqu'au prochain créneau

### D'abord : ouvrez les deux interrupteurs, sinon ce geste sera refusé

**Sur un cerveau neuf, les deux interrupteurs de dépense sont FERMÉS.** C'est voulu — rien
ne dépense votre argent sans un geste humain — mais cela veut dire que le premier
`systemctl start` **sera refusé, sur cent pour cent des installations neuves**, si vous ne
faites pas ceci d'abord :

```bash
# Interrupteur 1 sur 2 — côté service, dans le coffre de ce cerveau
sudo sed -i 's/^ARAC_ALLOW_PAID_AI=.*/ARAC_ALLOW_PAID_AI=1/' /etc/arac/<votre_base>/arac.env

# Interrupteur 2 sur 2 — côté cerveau, EN BASE : il n'est dans aucun fichier
cd /chemin/de/votre/clone
sudo .venv/bin/python -m agents.lib.paid_ai_control arm --confirm \
     --coffre /etc/arac/<votre_base>/arac.env

# Et la vérification, qui ne dépense rien
sudo .venv/bin/python -m agents.lib.paid_ai_control status \
     --coffre /etc/arac/<votre_base>/arac.env
```

> **Le second est celui que personne ne trouve** : il ne vit pas dans un fichier mais dans
> la table `arac.arac_config`, clé `paid_ai_enabled`, et il ne s'ouvre que par ce geste
> explicite. Le contrôle de l'étape 6 les nomme tous les deux, avec leur remède.

### Ensuite, le cycle

Le cerveau digère à 04:00, 13:00 et 21:00. Pour ne pas attendre :

```bash
sudo systemctl start arac-<votre_base>-cycle.service
journalctl -u arac-<votre_base>-cycle.service -f
```

**Ce que vous devez voir** : le cycle lit une tranche de conversations, appelle la
curation, et propose des atomes. Puis, dans le cockpit :

```
  Depuis 24 heures, j'ai appris 3 conversation(s) et créé 4 atome(s) de savoir.
```

**Ce que vous devez savoir avant de juger votre cerveau :**

- **Un cycle stérile est banal.** Sur le cerveau de référence, **36 % des cycles** se
  sont terminés sans produire un seul atome — un cerveau qui ne retient rien d'une
  journée sans savoir durable fonctionne parfaitement.

**Mais si votre PREMIER cycle ne rend rien, ne cherchez pas la banalité : cherchez dans
cet ordre.** C'est l'ordre dans lequel le cycle lui-même refuse, et chaque ligne porte le
code exact que vous lirez dans `journalctl -u arac-<votre_base>-cycle.service`.

| # | Ce que dit le journal | La cause | Le geste |
|---|---|---|---|
| 1 | `master_switch_env_off` | **Interrupteur 1/2**, côté service : `ARAC_ALLOW_PAID_AI` n'est pas à `1`. **État d'usine.** | `sudo sed -i 's/^ARAC_ALLOW_PAID_AI=.*/ARAC_ALLOW_PAID_AI=1/' /etc/arac/<votre_base>/arac.env` |
| 2 | `master_switch_config_off` | **Interrupteur 2/2**, côté cerveau : `arac_config.paid_ai_enabled` n'a jamais été armé. **État d'usine, et il n'est dans aucun fichier.** | `sudo .venv/bin/python -m agents.lib.paid_ai_control arm --confirm --coffre /etc/arac/<votre_base>/arac.env` |
| 3 | `kill_switch_active` | le kill-switch a été posé à la main. Il n'est **jamais** retiré tout seul. | le même `arm --confirm` le retire |
| 4 | `spawn_failed`, ou « Not logged in » | le **binaire `claude`** manque sur le serveur, n'est pas exécutable par le compte d'agent, ou n'a **aucune session sous le dossier personnel de CE compte**. Votre propre session (root, ou la vôtre) n'est pas lue. | `sudo npm install -g @anthropic-ai/claude-code`, puis `sudo -u <compte-agent> -H env HOME=<agent_home>/data/agent-home claude auth login`. Le contrôle de l'étape 6 imprime les deux chemins exacts. |
| 5 | `cortex.duplicate_slot` | **le créneau du jour a déjà son reçu.** Vous avez réparé quelque chose puis relancé : le cycle ressort en silence jusqu'au prochain horaire. | la valve, **et retirez-la ensuite** : ajoutez `ARAC_CORTEX_FORCE_MANUAL=1` au coffre, relancez le service, puis **supprimez la ligne** — laissée en place, chaque tir de la minuterie ouvrirait un créneau neuf au lieu d'un par horaire |
| 6 | `daily_*_exhausted` | ce n'est pas une panne : le plafond de dépense du jour est atteint. Le cycle reprendra demain, seul. | rien, ou relever les plafonds (`ARAC_MAX_*`) |
| 7 | rien de tout cela, et la file est vide | le cerveau se repose : si rien n'est entré, rien ne peut sortir. | revoyez l'étape 8 |
| 8 | des messages entrés, un cycle qui tourne, zéro atome, plusieurs jours | **là seulement**, soupçonnez `ARAC_NODE_ID` : il doit être identique dans `config/brain.toml`, dans `ARAC_INGEST_ALLOWED_NODES`, et dans `~/.arac/<cerveau>/pont.conf`. | l'étape 5 vous l'a déjà fait vérifier |

> **Les deux premières lignes sont l'état d'usine, pas une panne.** Cette page a longtemps
> envoyé le lecteur vérifier `ARAC_NODE_ID` en premier — un défaut qu'il n'a
> statistiquement pas, puisque l'étape 5 le lui a fait vérifier et que l'étape 8 a réussi.
> Pendant ce temps la vraie cause, présente sur **cent pour cent** des installations
> neuves, n'était nommée nulle part.
- **Le cerveau doute.** 96 % des rappels du cerveau de référence sont rendus en
  confiance basse. Ce n'est pas une panne, c'est de l'honnêteté — et ce chiffre-là ne se
  lève pas par un geste : il mesure les **rappels servis**, pas vos atomes. Sur les atomes,
  vous pouvez corriger le *savoir* (`supersede`, `PATCH`, `DELETE` sur `/v1/atoms/`) et
  retoucher leur score chiffré (`confidence_score`, accepté par le `PATCH`) ; ce que vous
  ne pouvez pas encore, c'est les *valider* — la trace d'audit (`audit_source`) n'est
  exposée par aucune route de modification, et le cockpit est en lecture stricte. Voir
  [`PREMIER-MOIS.md`](PREMIER-MOIS.md), « Corriger ce qui est faux », et la
  [`FAQ`](FAQ.md), « Pourquoi mon cerveau ne trouve rien après une semaine ? ».
- **Ce que vous dites à 14 h n'est pas mémorisé à 14 h 01.** Entre deux cycles, le
  cerveau accumule. Un cerveau au repos qui n'a rien produit depuis six heures
  fonctionne peut-être parfaitement.

> **Et maintenant, la seule chose qui décide si vous resterez.** Votre cerveau est vivant
> et il ne sait presque rien. Il en sera de même demain, et après-demain. Ce n'est pas une
> panne : c'est la nature de la chose, et c'est là que la plupart des gens abandonnent.
> [`PREMIER-MOIS.md`](PREMIER-MOIS.md) décrit ce que vous verrez aux jours 1, 3, 7 et 30,
> ce qui est normal, ce qui ne l'est pas, et comment faire la différence. **Lisez-le ce
> soir**, pas au jour 5.

---

## Étape 10 — La sauvegarde, avant d'en avoir besoin — 15 min

Le bootstrap a déjà armé **deux** unités : la sauvegarde, toutes les six heures, et sa
**preuve** — `ops/restore_verify.sh`, le dimanche à 03:00, qui recharge le dernier dump
dans une base **jetable** et le compare au vivant. C'est déjà sérieux : une sauvegarde
jamais restaurée n'est pas une sauvegarde, c'est une hypothèse, et cette hypothèse-là est
levée toutes les semaines sans que vous ayez rien à faire.

**Ce qui manque encore, et que le bootstrap ne peut pas décider à votre place** : le
chiffrement au repos (avec quelle clé ?), la copie **hors site** (vers quoi ?), et le
chien de garde (qui alerter ?). Tant qu'ils ne sont pas armés, vos dumps sont **en clair
et sur cette seule machine**. Et la première preuve, celle qui vous apprend le geste,
vaut d'être faite **à la main, maintenant**, plutôt qu'attendue jusqu'à dimanche :

```bash
source ops/env.sh        # pose $ARAC_BACKUP_DIR et $ARAC_BACKUP_STATE, dérivés de $BASE
sudo install -d -m 0700 -o "$(id -un)" "$ARAC_BACKUP_DIR"
sudo install -d -m 0700 -o "$(id -un)" "$ARAC_BACKUP_STATE"

# Le gabarit de restauration : ce script IMPRIME le SQL et la commande qui
# l'exécute, PORT COMPRIS. Lisez-la, puis recopiez-la — ne la tuyautez pas en
# aveugle : le bloc commence par un DROP DATABASE, et sans « -p » il tombe sur
# la grappe par défaut de la machine, c'est-à-dire chez le voisin.
ops/restore_verify.sh --prepare-template

ops/backup.sh            # une sauvegarde, tout de suite, à la main
ops/restore_verify.sh    # et sa preuve : restauration réelle dans une base jetable
```

**Deux cerveaux sur cette machine ?** Alors ces trois commandes **ne s'arrêtent pas** :
elles servent le cerveau que **votre clone décrit** (`config/brain.toml`, écrit par
l'entretien de l'étape 2) — et elles le **disent**, sur la sortie d'erreur, avant le
premier geste :

```
ops/ sert le cerveau « <votre_base> » — ce dépôt le décrit, il n'a pas été deviné.
    coffre      /etc/arac/<votre_base>/arac.env
    preuve      <votre clone>/config/brain.toml nomme « <votre_base> »
    candidats   2 coffres sous /etc/arac
```

Elles ne s'arrêtent **avant tout geste** (code 1, « *ARRÊT AVANT TOUT GESTE* ») que
lorsque le choix n'est pas évident : ce clone ne décrit aucun cerveau, ou il en décrit un
qui n'a pas de coffre ici. **Préfixez-les quand même** de
`sudo ARAC_ENV_FILE="/etc/arac/$BASE/arac.env"` : c'est la seule façon de ne pas dépendre
du dossier d'où vous tapez, et le message d'annonce vous donne cette ligne toute faite.
Le détail des cinq cas est au tableau d'`ARAC_ENV_FILE` de
[`CONFIGURATION.md`](CONFIGURATION.md).

L'ordre compte. Armer un minuteur avant d'avoir vu la commande réussir une fois à la
main, c'est déléguer un problème qu'on n'a pas encore résolu.

Tout est dans [`SAUVEGARDE.md`](SAUVEGARDE.md), y compris le chiffrement au repos et la
copie hors site — parce que vos sauvegardes disparaîtront avec le serveur qui les
héberge.

---

## Récapitulatif — les commandes, dans l'ordre

```bash
# sur n'importe quelle machine
git clone <l-adresse-de-ce-depot> arac && cd arac
make venv
make test

# sur le serveur
./bootstrap/bootstrap.sh --check
python3 bootstrap/wizard.py
./bootstrap/bootstrap.sh --dry-run
sudo ./bootstrap/bootstrap.sh
# … puis les trois raccords de l'étape 5 :
#   le pont de vocabulaire, la liste blanche, le seed des postes …
sudo ./bootstrap/checks/verify_install.sh

# sur votre machine (les deux ports sont ceux relevés à l'étape 7)
ssh -N -L "$CC:127.0.0.1:$CC" -L "$API:127.0.0.1:$API" <utilisateur>@<votre-serveur>

# sur le serveur, pour ne pas attendre 04:00
sudo systemctl start arac-<votre_base>-cycle.service
```

---

## Ce qui a été réellement exécuté pour écrire ce document

**Vérifié** sur Ubuntu, Python 3.12, PostgreSQL 16.13 + pgvector 0.8.2 :
`make test` · `make doctor` · `bootstrap.sh --check` · `--etapes` · `--dry-run`
complet · `checks/verify_install.sh` · `generate_scopes.py` · `wizard.py --help` ·
`sudo ops/install_check.sh` (sans `sudo`, il ne peut pas lire le coffre) · les deux
auto-tests de `ops/` · la création d'un venv et l'installation de `requirements.txt` · le
pont de vocabulaire de l'étape 5, y compris son idempotence — **rejoué deux fois de suite,
sortie identique**.

**Vérifié en réel, deux fois, avec deux taxonomies différentes** :
`sudo ./bootstrap/bootstrap.sh` de bout en bout — base, rôles du cerveau, migrations jusqu'à
la tête, secrets, unités systemd, contrôle a posteriori. Les deux installations rendent
le **même schéma** — `pg_dump --schema-only` identique une fois retirée, des deux côtés,
la plaque d'identité que le bootstrap grave exprès dans le commentaire du schéma pour
qu'un dump sache dire de quel cerveau il vient. Le critère et sa commande, en deux temps
— le schéma qui doit être le même, l'identité qui doit différer —, sont au §7c du
[`README`](../README.md#c-ce-qui-est-éprouvé-sur-quoi-et-ce-qui-nest-pas).

**Vérifié depuis, derrière un vrai terminal** (9 août 2026) : l'étape des secrets en
**interactif** — mot de passe du cockpit tapé deux fois aux invites `getpass`, URI TOTP
affichée une seule fois, « Appairage effectué ? » sans code demandé — puis la **connexion
réelle au cockpit** avec ce mot de passe et un code à six chiffres : `303` vers `/cc/`,
session posée, `/cc/` et `/cc/v1/atoms` à `200`, mot de passe faux à `401`.

**Vérifié depuis, sur un cerveau réel** : la **restauration** d'une sauvegarde —
`ops/restore_verify.sh` recharge le dump produit par l'unité dans une base jetable, le
compare au vivant, et conclut « VERDICT : PROUVÉ — ce dump se restaure, et le cerveau en
sort entier ». Le bootstrap arme cette vérification lui-même
(`arac-<base>-restauration.timer`, dimanche 03:00), et `make acceptance` la rejoue à
chaque passage, à son étape 8, jusqu'à la **bascule** du §7 de
[`SAUVEGARDE.md`](SAUVEGARDE.md) sur un cerveau cassé pour de vrai.

**Toujours non vérifié** : le rejeu depuis un Ubuntu **nu**, l'installation complète en
interactif de bout en bout (seule l'étape des secrets l'a été), le tunnel SSH depuis un
Mac et `launchd`, l'ingestion d'une vraie conversation et donc le premier cycle de
digestion réel.

Quand vous les exécuterez, **notez chaque friction** : c'est le test d'installation à
l'aveugle que [`GOAL.md`](../GOAL.md) appelle F8, et c'est la dernière chose qui manque.
