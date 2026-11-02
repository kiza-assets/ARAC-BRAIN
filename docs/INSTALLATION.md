# Installation — le chemin complet

Ce document décrit l'installation entière, avec ses variantes, et **un point de contrôle
après chaque étape** : « à ce stade, cette commande doit répondre ceci ».

Si vous voulez seulement le chemin le plus court, allez à
[`DEMARRAGE-RAPIDE.md`](DEMARRAGE-RAPIDE.md). Revenez ici quand quelque chose sort du
cadre.

**Convention de ce document.** Les valeurs à remplacer sont entre chevrons :
`<votre-serveur>`, `<votre_base>`, `<utilisateur>`. Aucun chemin n'est écrit en dur dans
le code ; ceux qui apparaissent ici sont les **défauts**, tous remplaçables par une
variable d'environnement (voir [`CONFIGURATION.md`](CONFIGURATION.md)).

---

## Table des matières

0. [Les décisions à prendre avant de taper quoi que ce soit](#0-les-décisions-à-prendre-avant-de-taper-quoi-que-ce-soit)
1. [Le serveur et ses paquets](#1-le-serveur-et-ses-paquets)
2. [Le dépôt et l'environnement Python](#2-le-dépôt-et-lenvironnement-python)
3. [L'entretien — votre cerveau prend forme](#3-lentretien--votre-cerveau-prend-forme)
4. [La simulation](#4-la-simulation)
5. [L'installation réelle, étape par étape](#5-linstallation-réelle-étape-par-étape)
6. [Les trois raccords — deux posés, un à finir vous-même](#6-les-trois-raccords--deux-posés-un-à-finir-vous-même)
7. [Le contrôle a posteriori](#7-le-contrôle-a-posteriori)
8. [Le tunnel et le cockpit](#8-le-tunnel-et-le-cockpit)
9. [La machine source](#9-la-machine-source)
10. [Le premier cycle](#10-le-premier-cycle)
11. [Les sauvegardes](#11-les-sauvegardes)
12. [Variantes](#12-variantes)
13. [Désinstaller](#13-désinstaller)
    · [Le journal système — ce que ce chapitre ne peut pas effacer](#le-journal-système--ce-que-ce-chapitre-ne-peut-pas-effacer-et-pourquoi)

---

## 0. Les décisions à prendre avant de taper quoi que ce soit

Cinq décisions coûtent cher à changer plus tard. Prenez-les maintenant.

| Décision | Pourquoi elle est difficile à défaire | Conseil |
|---|---|---|
| **La grappe PostgreSQL** où ce cerveau vivra | Les rôles PostgreSQL sont **globaux à la grappe** : installer sur celle d'un voisin y pose cinq rôles de plus, et c'est la famille de l'incident qui a détruit le cerveau de l'auteur. Déplacer un cerveau d'une grappe à une autre est une **migration de données**, pas un réglage : le bootstrap **refuse** (code 6) de le faire en effet de bord. | Sur une machine qui ne porte qu'un cerveau, la grappe par défaut (5432) convient. Dès qu'il y en a un second, donnez-lui la sienne — le geste complet est au [§12.f](#f-une-grappe-postgresql-pour-ce-cerveau), et il tient en deux lignes. Le numéro se choisit **au point de contrôle 1 du §1**, avant l'entretien. |
| **Votre taxonomie** (racines et feuilles) | Un domaine supprimé emporte le savoir qu'il contenait. Le générateur refuse d'ailleurs de retirer un domaine encore habité. | 5 à 8 racines, 3 à 6 feuilles chacune — l'ordre de grandeur est argumenté une seule fois, dans [`COMMENT-IL-CREE-SES-SCOPES.md`](COMMENT-IL-CREE-SES-SCOPES.md) §5. Ajouter est facile, retirer ne l'est pas. |
| **Votre `node_id`** | Le cerveau refuse toute conversation d'un nœud non déclaré. Le changer invalide la provenance de ce qui est déjà entré. | Un nom stable et descriptif : `portable-perso`, `poste-bureau`. Pas de date, pas de version. |
| **Le modèle d'embeddings** | Changer de modèle ou de dimension invalide **tous** les vecteurs déjà calculés. Deux populations incomparables cohabitent alors dans le même index, et le rappel se dégrade sans qu'aucun test n'échoue. | Gardez `text-embedding-3-large` (3 072 dimensions) tant que vous n'avez pas de raison mesurée d'en changer. |
| **Le format de la provenance** (`source_ref`) | Sur le cerveau de référence, un changement de format a coupé le lien entre les souvenirs et les conversations dont ils venaient : **76 % du savoir ne sait plus d'où il vient**. Il est encore là, mais plus vérifiable. Un souvenir sans provenance n'est pas un souvenir, c'est une rumeur. | N'y touchez pas. Si vous devez le faire, écrivez la migration qui convertit l'existant **en même temps**. |

---

## 1. Le serveur et ses paquets

### Ce que le serveur doit être

Ubuntu 24.04 LTS (ou Debian 12), avec `systemd`. 2 vCPU, 4 Go de RAM, 20 Go de disque
suffisent pour des années — la base d'un cerveau actif pèse quelques centaines de Mo par
an, les vecteurs compris.

**Pourquoi pas un portable ?** Parce que le cerveau digère trois fois par jour, sauvegarde
toutes les six heures, et prouve sa restauration le dimanche à 03:00. Un ordinateur qui
dort ne digère pas, et un cycle raté n'est pas rattrapé indéfiniment.

### Les paquets

```bash
sudo apt update
sudo apt install -y postgresql-16 postgresql-16-pgvector postgresql-client-16 \
                    python3 python3-venv python3-pip git openssh-client
sudo systemctl enable --now postgresql
```

> **Adaptez le numéro de version.** `postgresql-16-pgvector` ne sert à rien si votre
> serveur tourne en 15 ou 17. Le paquet pgvector est lié à la version majeure.

> **pgvector doit être en version 0.7.0 ou plus.** Le schéma emploie le type `halfvec`,
> qui n'existe pas avant. Ubuntu 24.04 livre **0.6.0** : le paquet ci-dessus s'installe,
> puis la migration échoue sur `type "halfvec" does not exist`. Sur Ubuntu 24.04, activez
> d'abord le dépôt officiel PostgreSQL (PGDG), qui livre une version récente :
>
> ```bash
> sudo apt install -y postgresql-common && sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
> sudo apt install postgresql-16-pgvector
> ```

### Le paquet qui n'est pas dans `apt`, et qui décide si le cerveau apprend

```bash
sudo npm install -g @anthropic-ai/claude-code
claude --version          # doit répondre un numéro
```

**Le cycle de digestion n'appelle aucune API.** Il **lance** ce binaire en sous-processus,
sur ce serveur, sous le compte d'agent du cerveau (`agents/lib/claude_cli.py`). Ce n'est
donc pas une clé qu'il faut acheter pour digérer : c'est ce binaire qu'il faut installer.
Une clé d'API Anthropic sans lui ne produit pas un seul souvenir.

Le binaire résout son chemin à l'exécution, dans cet ordre : `ARAC_CLAUDE_BIN` (le chemin
que **vous** nommez dans `/etc/arac/<votre_base>/arac.env`), puis le `PATH` du service,
puis `/usr/bin/claude` en dernier recours. Posé par `nvm` ou par un `npm -g` sous préfixe
utilisateur, **nommez-le** plutôt que de le déplacer.

Il lui faut enfin de quoi s'authentifier, et **une seule des deux façons suffit** :

- une **session d'abonnement Claude**, ouverte **sous le compte d'agent** du cerveau — pas
  sous le vôtre, ni sous `root` : le cycle force `HOME` sur le dossier de ce compte ;
- une **clé d'API Anthropic**, que l'étape 8 vous demandera et que **le binaire** lira
  dans l'environnement du service. ARAC ne l'ouvre jamais lui-même.

> **Ce que le bootstrap ne vérifie pas** : que `npm` (donc Node) soit présent pour poser
> ce binaire, et l'espace disque disponible. Tout le reste de cette section est constaté
> à l'étape 1, et le binaire de curation l'est **deux fois** — à l'étape 1, puis au
> contrôle final sous le compte d'agent.

### ▸ Point de contrôle 1

```bash
# LE PORT DE LA GRAPPE OÙ VOTRE CERVEAU VA VIVRE. Ici, et ici seulement, c'est
# vous qui le décidez : le coffre n'existe pas encore. Regardez ce que la
# machine porte, puis choisissez.
sudo pg_lsclusters                 # les grappes de cette machine, et leurs ports
PGPORT_BASE=<le_port_de_votre_grappe>   # celui où ce cerveau va vivre

# ET SI CETTE MACHINE PORTE DÉJÀ UN CERVEAU, donnez au vôtre sa propre grappe
# MAINTENANT — deux lignes, et le §12.f dit pourquoi :
#   sudo pg_createcluster 16 <nom> --port <port> --start
#   PGPORT_BASE=<port>

psql --version
sudo -u postgres psql -p "$PGPORT_BASE" -tAc "SHOW server_version"
sudo -u postgres psql -p "$PGPORT_BASE" -tAc \
  "SELECT name, default_version FROM pg_available_extensions
    WHERE name IN ('vector','pg_trgm') ORDER BY name"
```

**Doit répondre** : une version de client, une version de serveur ≥ 16, et **deux lignes**
d'extensions — une pour `pg_trgm`, une pour `vector`, dont la version doit être **≥ 0.7.0**
(Ubuntu 24.04 livre 0.6.0 : voir les deux commandes PGDG plus haut). Si `vector` manque à
l'appel, pgvector n'est pas installé pour cette version majeure de PostgreSQL.

> **Deux détails qui évitent de croire à une panne.** La troisième requête **nomme**
> l'extension et **trie** : sans `ORDER BY`, PostgreSQL ne garantit aucun ordre, et deux
> numéros nus dans un ordre imprévisible ne se lisent pas. Et les versions que rendent les
> deux premières commandes portent souvent le suffixe de votre distribution — par exemple
> `16.13 (Ubuntu 16.13-1.pgdg24.04+1)`. Ce n'est pas une anomalie : seul le numéro compte.

> **Pourquoi `-p` dès le premier contrôle du manuel.** `SHOW server_version` sans `-p`
> répond pour la grappe **par défaut** de la machine. Sur un serveur qui en porte déjà une
> autre, vous liriez la version d'un serveur qui n'est pas le vôtre — et vous installeriez
> `postgresql-<majeure>-pgvector` pour la mauvaise. Toutes les commandes PostgreSQL de ce
> manuel portent `-p`, pour la même raison. **Après l'installation**, ce numéro ne se
> devine plus : il se lit, `PGPORT_BASE=$(sudo sed -n 's/^ARAC_DB_PORT=//p'
> "/etc/arac/$BASE/arac.env")` — c'est ce que fait le §13.

> **▸ ET VOICI COMMENT CE NUMÉRO SE DONNE AU BOOTSTRAP — une variable, une seule fois.**
> Ce paragraphe vous fait *choisir* un port ; rien ne le transmet tout seul. Le bootstrap
> lit `ARAC_DB_PORT`, et **rien d'autre** : ni `config/brain.toml`, ni un drapeau, ni une
> question de l'entretien. Sans elle, il installe sur la grappe **par défaut** de la
> machine — 5432 — c'est-à-dire, sur un serveur qui porte déjà un cerveau, **sur celle du
> voisin**, sans rien annoncer d'anormal.
>
> ```bash
> sudo ARAC_DB_PORT="$PGPORT_BASE" ./bootstrap/bootstrap.sh --dry-run   # d'abord voir
> sudo ARAC_DB_PORT="$PGPORT_BASE" ./bootstrap/bootstrap.sh             # puis agir
> ```
>
> **Vous ne la repasserez plus jamais.** L'étape 3 écrit `ARAC_DB_PORT` dans
> `/etc/arac/<votre_base>/arac.env`, et toute exécution ultérieure du bootstrap **relit**
> cette valeur : `sudo ./bootstrap/bootstrap.sh --from services`, nu, reste sur votre
> grappe. Mieux : si vous demandez un **autre** port que celui retenu, il s'arrête net —
> « REFUS — ce cerveau vit déjà sur un autre serveur PostgreSQL », code **6**, rien créé,
> rien écrit. Déplacer un cerveau d'une grappe à une autre est une migration de données,
> jamais un effet de bord.
>
> La simulation vous le confirme avant tout geste : la ligne `serveur 127.0.0.1:<port>` et
> l'encadré « Ce cluster PostgreSQL (port `<port>`) » doivent porter **votre** numéro. S'ils
> disent 5432 alors que vous vouliez une grappe à vous, arrêtez-vous : la variable n'est pas
> passée. Le geste complet, `pg_createcluster` compris, est au
> [§12.f](#f-une-grappe-postgresql-pour-ce-cerveau).

**Rejoué le 9 août 2026** sur une grappe montée pour l'occasion — vos numéros seront les
vôtres, seule la **forme** est le contrôle :

```
psql (PostgreSQL) 16.13 (Ubuntu 16.13-1.pgdg24.04+1)
16.13 (Ubuntu 16.13-1.pgdg24.04+1)
pg_trgm|1.6
vector|0.8.2
```

---

## 2. Le dépôt et l'environnement Python

```bash
git clone <l-adresse-de-ce-depot> arac
cd arac
make venv
```

`make venv` crée `.venv/` à la racine du dépôt et y installe `requirements.txt`.
**Accès réseau requis** — c'est le seul moment de l'installation où `pip` télécharge.

### Où le code doit-il vivre ?

Le dépôt peut vivre n'importe où : le code ne contient **aucun chemin absolu**. La
racine est résolue par `arac_runtime.home()`, dans cet ordre :

1. la variable d'environnement `ARAC_HOME` — c'est ce que posent les unités systemd ;
2. à défaut, le dossier qui contient `arac_runtime.py`, c'est-à-dire le dépôt cloné.

Le second cas rend le dépôt utilisable immédiatement après un `git clone`, sans rien
configurer. Le premier le rend déplaçable : `/opt/arac`, `/srv/cerveau`, `~/arac` — le
code s'en moque.

> **Convention raisonnable pour un serveur : `/opt/<votre_base>`** — le nom de votre
> cerveau, jamais `/opt/arac`. Le dépôt est la **seule** pièce de l'installation qui ne se
> partage pas (§12d) : la taxonomie engendrée à l'étape 6 vit dedans, et elle ne porte le
> nom de personne. Un répertoire commun, c'est donc le début du même accident que des
> rôles communs — sauf qu'ici rien ne le refuserait. C'est ce que le bootstrap propose
> lui-même quand il refuse de poser les unités depuis un chemin privé : `sudo mv <dépôt>
> /opt/<votre_base>`. Posez ensuite `ARAC_HOME=/opt/<votre_base>` dans le fichier
> d'environnement, et donnez le répertoire à un utilisateur non privilégié.

### ▸ Point de contrôle 2

```bash
make test
make doctor
```

**`make test` doit répondre trois choses**, sans base ni réseau, et la ligne verte est la
troisième :

1. **`tests/test_aucun_nom_non_resolu.py` vert** — le garde qui charge tout le Python
   livré et refuse le moindre nom que le code irait chercher sans le trouver ;
2. **le bloc « CE QUE CETTE SESSION A RÉELLEMENT EMPRUNTÉ »** — il ne rougit pas, il
   mesure ce dont le corps a réellement été exécuté ;
3. **la ligne de pytest**, de cette forme :

```
<N> passed, <M> skipped, <K> deselected, <X> xfailed, <W> warnings in <T>s
```

> **Pourquoi trois et non une.** Ce point de contrôle a longtemps demandé la seule ligne
> verte. Elle a été rendue par une livraison qui servait deux routes en 500 et dont le
> kill-switch de l'IA payante mourait à l'import : un compte de tests verts ne dit pas ce
> qui a été **exécuté**. Le raisonnement entier est en
> [première page du README](../README.md#6-le-chemin-le-plus-court-vers-un-cerveau-qui-vit),
> qui fait autorité ; il n'est pas recopié ici.

> **Sur la troisième ligne, le critère n'est pas le nombre, c'est `failed` absent.** Ces compteurs
> montent à chaque test ajouté : le vôtre ne correspondra pas à celui d'un autre lecteur,
> et c'est normal. Un point de contrôle qui exige un chiffre exact fabrique de faux
> échecs — vous croiriez avoir raté une installation parfaitement saine. **La durée non
> plus n'est pas un critère** : elle dépend de votre machine, pas du dépôt. Ce gabarit a
> porté « 5 xfailed, 1 warning in ~20s » ; la suite en rend aujourd'hui cinq, d'avertissements,
> et met quatre fois plus longtemps sur un serveur modeste — un lecteur qui comparait ligne
> à ligne trouvait un écart là où le paragraphe venait de lui promettre qu'il n'y en aurait
> pas. Les tests « skipped » ne sont pas des échecs cachés : ce sont ceux qui exigeraient une
> base ou une clé d'API et qui se déclarent ignorés plutôt que de rougir.

**`make doctor` répond cinq lignes utiles**, et l'entretien n'ayant pas eu lieu, l'identité
est encore absente :

```
racine        : /chemin/vers/arac
identite      : ABSENTE — lancez : python3 bootstrap/wizard.py
taxonomie     : …                 (voir l'encadré ci-dessous)
projets       : aucun (config/projects.toml absent — le cockpit le dira)
constitution  : d287dce0c7ea (5766 caracteres)
```

> **Deux surprises à ce point précis du parcours, et aucune n'est une panne.**
>
> **1. Vous verrez plus que cinq lignes, et vous verrez le mot `Traceback`.** Chaque ligne
> de `make doctor` est un petit programme Python qui essaie de lire une pièce du cerveau et
> se rabat sur `ABSENTE` quand elle manque (`Makefile`, cible `doctor`). Le repli imprime sa
> ligne propre sur la sortie standard — mais la tentative qui a échoué, elle, a déjà craché
> sa trace sur la sortie d'erreur. Dans un terminal, les deux se mélangent. Sur un clone qui
> n'a jamais rien lancé, cela fait une quarantaine de lignes au lieu de cinq, dont deux
> traces complètes : `arac_runtime.BrainNotBornError` pour l'identité, puis
> `ModuleNotFoundError: No module named 'app.schemas.scope_generated'` re-levé en
> `ImportError` pour la taxonomie. Chacune se termine par le message pédagogique qui dit quoi
> faire. **Pour ne lire que le bilan** : `make doctor 2>/dev/null` — cinq lignes, exactement
> celles ci-dessus.
>
> **2. La ligne `taxonomie` ne dira pas `ABSENTE`, parce que `make test` vient de passer.**
> C'est l'ordre même de ce bloc qui produit l'effet : la suite de tests engendre au passage
> une taxonomie d'essai depuis `config/scopes.example.toml` quand elle n'en trouve pas
> (`tests/conftest.py`), et ce fichier reste sur le disque. La ligne rend alors le compte de
> l'EXEMPLE — pas le vôtre. Sur un clone qui n'a pas encore lancé `make test`, elle rend bien
> `taxonomie     : ABSENTE — lancez : make scopes`. Dans les deux cas il n'y a rien à
> réparer : **votre** taxonomie naît de l'entretien, au §3, et c'est le point de contrôle 3
> qui vous la fera vérifier.

> **`config/brain.toml` et `config/scopes.toml` ne sont pas versionnés** — `.gitignore`
> les exclut. En clonant, vous ne les recevez donc pas, et `make doctor` doit vous
> répondre qu'ils sont absents : c'est le comportement attendu avant l'entretien, pas une
> panne. S'ils existent malgré tout dans votre arborescence, ils viennent d'un passage
> antérieur du bootstrap sur cette machine, jamais du dépôt ; `rm config/brain.toml
> config/scopes.toml` vous remet dans l'état d'un clone neuf. Le dépôt ne livre que les
> modèles commentés, `config/scopes.example.toml` et `config/projects.example.toml`.

---

## 3. L'entretien — votre cerveau prend forme

```bash
python3 bootstrap/wizard.py
```

### Ce qu'il fait, et surtout ce qu'il ne fait pas

Il **n'installe rien**. Il ne touche à aucune base. Il n'appelle aucun service. Il pose
cinq questions et écrit deux fichiers.

C'est délibéré : **décider et exécuter ne sont pas le même geste.** L'entretien produit
une *description* de votre cerveau ; le bootstrap lui donne corps, en annonçant ce qu'il
s'apprête à faire avant de le faire.

### Les cinq questions

1. **À qui appartient ce cerveau ?** — affichage seulement, jamais une décision.
2. **Comment s'appelle-t-il ?** — devient le nom de la base (points et tirets convertis
   en soulignés) et le préfixe des unités systemd. Deux cerveaux différents sur la même
   machine ne se marchent donc jamais dessus.
3. **D'où viendront ses conversations ?** — le `node_id`. Le garde-fou décrit au §0.
4. **Comment découpez-vous votre vie ?** — la taxonomie. **La question qui compte.**
5. **Confirmation** — il montre ce qu'il va écrire avant de l'écrire.

### Choisir sa taxonomie

Une bonne racine correspond à un **monde** de votre vie : quelque chose dont vous parlez
sans jamais confondre avec le reste. Une bonne feuille est assez précise pour qu'un
atome y trouve sa place sans hésitation, et assez large pour ne pas rester vide.

Les deux règles qui gouvernent tout :

1. **Les atomes vivent sur les feuilles, pas sur les racines.** Une racine est un
   conteneur, une feuille est un rangement. Un atome posé sur une racine existe en base,
   et il peut encore remonter sur une question qui lui ressemble — mais il est exclu de
   tout ce que le cerveau construit au-dessus du rangement : pas d'état courant, pas de
   place dans la vue des scopes, pas de comptage dans la couverture. Et une recherche qui
   précise un domaine ne le trouvera pas : l'égalité de scope est stricte. Sur le cerveau
   de référence, près d'un souvenir actif sur onze est tombé dedans et n'en est jamais
   ressorti de lui-même. C'est le piège numéro un, et il ne fait aucun bruit.
2. **Un domaine ne s'invente pas à la volée.** Un domaine hors de votre liste est refusé
   par l'API (422) et par la base (clé étrangère). Cette rigidité est le prix à payer
   pour que la mémoire ne se fragmente pas en dizaines de catégories jumelles.

`config/scopes.example.toml` est le modèle commenté. Il contient, à la fin, un exemple
issu du cerveau de référence — **explicitement marqué « ne le copiez pas »**. Il est là
pour montrer à quoi ressemble une taxonomie qui a vécu, pas pour être repris.

### ▸ Point de contrôle 3

```bash
cat config/brain.toml
.venv/bin/python bootstrap/generate_scopes.py
make doctor
```

**`generate_scopes.py` doit répondre** :

```
  Taxonomie générée depuis config/scopes.toml
    N racines, M feuilles, N+M scopes
    → app/schemas/scope_generated.py
    → db/seeds/scopes.sql

  Rappel : les atomes vivent sur les feuilles. Un atome posé sur une racine
  devient orphelin — la similarité pure peut encore le faire remonter, mais il
  sort de l'état courant, de la vue des scopes et de la couverture, et une
  recherche qui précise un domaine ne le trouvera jamais.
```

**`make doctor` doit maintenant répondre** votre identité et votre taxonomie :

```
identite      : <votre-node-id>
taxonomie     : N racines, M feuilles
```

**Si le générateur refuse votre taxonomie**, il vous dit laquelle des règles est violée
et où. Six familles de taxonomies invalides sont refusées avec un message pédagogique
(racine sans feuille, clé invalide, doublon, profondeur excessive…). Corrigez
`config/scopes.toml` et relancez.

---

## 4. La simulation

```bash
./bootstrap/bootstrap.sh --dry-run
```

**Rien n'est écrit, rien n'est créé, aucun service n'est démarré.** La base n'est
ouverte qu'en **lecture** — juste assez pour pouvoir vous dire ce qu'elle contient déjà.
Dans le code du bootstrap, une seule fonction (`reel`) garde la porte : aucun effet de
bord n'existe hors d'un `reel || return 0`.

Faites-le **au moins une fois**. C'est là que vous verrez, avant qu'ils n'existent, les
noms de votre base, de vos rôles, de vos unités systemd et de vos fichiers de secrets.

Deux options utiles au passage :

```bash
./bootstrap/bootstrap.sh --etapes     # la liste des étapes, et sortir
./bootstrap/bootstrap.sh --dry-run --bavard   # + le contenu exact de chaque unité systemd
```

### ▸ Point de contrôle 4

La simulation doit se terminer par :

```
  ✓ Seraient accomplies : prereqs config base vecteurs migrations scopes secrets cles services controle
  ...
  [simulation] Aucun changement n'a été appliqué.
```

Si une étape apparaît comme **incomplète** dès la simulation, réglez-la maintenant : ce
sera un échec réel tout à l'heure.

---

## 5. L'installation réelle, étape par étape

```bash
sudo ./bootstrap/bootstrap.sh

# … ou, si vous avez choisi une grappe à vous au point de contrôle 1 du §1 —
# c'est le SEUL moyen de la lui donner, et il ne se répète pas (§12.f) :
sudo ARAC_DB_PORT=<le_port_de_votre_grappe> ./bootstrap/bootstrap.sh
```

Le script est **idempotent** (relançable sans dégât), **reprenable** (l'avancement est
écrit dans `.bootstrap-install.state` après chaque étape réussie), **simulable** et
**réparable** (chaque échec dit ce qui a échoué, pourquoi, et le geste exact).

```bash
sudo ./bootstrap/bootstrap.sh --from migrations   # reprendre à partir de…
sudo ./bootstrap/bootstrap.sh --only scopes       # ne rejouer que…
sudo ./bootstrap/bootstrap.sh --rejouer           # tout reprendre depuis zéro
```

Ce qui suit décrit les onze étapes et leur point de contrôle propre.

> **▸ Les deux valeurs que TOUS les points de contrôle de ce chapitre supposent posées.**
> Posez-les une fois dans votre terminal ; les blocs qui suivent s'en servent sans les
> redéfinir.
>
> ```bash
> BASE=<votre_base>          # exactement brain.name de config/brain.toml
> # Avant l'étape 3, le coffre n'existe pas encore : c'est le port que vous avez
> # choisi au point de contrôle 1 du §1, et que vous donnez au bootstrap par la
> # variable ARAC_DB_PORT — la seule chose qui le transmette :
> #     sudo ARAC_DB_PORT=<le_port> ./bootstrap/bootstrap.sh
> # Omise, elle vaut 5432 : la grappe par défaut de la machine (§12.f).
> PGPORT_BASE=<le_port_de_votre_grappe>   # celui où ce cerveau va vivre
> # À partir de l'étape 3, il ne se choisit plus, il se LIT — et c'est la seule
> # version qui ne puisse pas se tromper :
> PGPORT_BASE=$(sudo sed -n 's/^ARAC_DB_PORT=//p' "/etc/arac/$BASE/arac.env")
> ```
>
> **Le port n'est pas un ornement, c'est la moitié de l'adresse.** Un nom de base ne dit
> pas sur quel serveur PostgreSQL cette base se trouve. `psql`, `createdb`, `dropdb`,
> `pg_dump` et `pg_restore` lancés **sans `-p`** ne s'abstiennent pas de choisir : ils
> visent la grappe **par défaut** de la machine. Sur un serveur qui porte deux cerveaux —
> ce que le §12 explique comment faire — c'est très souvent celle du voisin, et un contrôle
> qui interroge le mauvais serveur ne rate pas bruyamment : il répond, calmement, sur une
> autre mémoire.

### Étape 1/11 — `prereqs` : constater

Ne fait que constater, n'installe rien sans votre accord. Elle annonce aussi, avant
toute chose, **ce que le bootstrap va exiger du réseau** : `pip` une fois, **une** clé
d'API payante à l'étape 8 (les embeddings), ce que le binaire `claude` a pour
s'authentifier — abonnement ou clé, et c'est LUI qui la lit —, et, une fois installé,
**aucun accès réseau entrant**.

### Étape 2/11 — `config` : déduire

Lit `config/brain.toml` et en déduit **tous** les noms et chemins : nom de base, schéma,
rôles, dossier de secrets, unités systemd, ports. Elle n'écrit rien.

> **▸ Contrôle** : le récapitulatif « Ce que ces réponses engendrent » doit correspondre
> à ce que vous attendez. C'est le dernier moment gratuit pour changer d'avis.

### Étape 3/11 — `base` : la base et ses rôles

Crée la base, le schéma `arac`, et les rôles PostgreSQL avec des mots de passe
engendrés localement (32 octets aléatoires chacun, jamais affichés, jamais passés par
`argv` — `ps` est lisible par tout le monde sur beaucoup de systèmes).

**Les noms de rôles portent celui de votre cerveau** — `arac_<votre_base>_<fonction>` —
parce qu'un rôle PostgreSQL est global au **cluster** et non propre à une base. Sans ce
préfixe, installer un second cerveau réencode les mots de passe du premier. Chaque rôle
créé reçoit en outre une **plaque de propriété** (`COMMENT ON ROLE`) qui permet à une
réinstallation de reconnaître les siens, et de refuser ceux d'un autre.

| Rôle | Peut | Ne peut pas |
|---|---|---|
| `arac_<base>_admin` | créer et modifier les tables (migrations) | — |
| `arac_<base>_app` | lire, insérer, mettre à jour (l'API) | **supprimer**, modifier le schéma |
| `arac_<base>_agent` | lire tout, insérer des propositions (les cycles) | modifier le savoir existant |
| `arac_<base>_readonly` | lire (le cockpit) | **écrire — structurellement** |
| `arac_<base>_backup` | rien : c'est un rôle **sans connexion**, cible de `GRANT SELECT` posés par les migrations `0009`/`0010` | se connecter |

**Pourquoi plusieurs et non un.** Un seul rôle « qui peut tout » serait plus simple à
installer, et c'est exactement pour cela qu'il est dangereux : le jour où le cockpit a
un bogue, il écrit dans la mémoire. Ici, il ne le *peut* pas — le rôle du cockpit porte
`default_transaction_read_only = on`, donc PostgreSQL ouvre **toutes** ses transactions
en lecture seule et refuse le moindre `INSERT` avant même de le lire. C'est la
différence entre « interdit » et « impossible ».

Et le rôle applicatif n'a pas le droit de `DELETE` parce que la doctrine du cerveau est
qu'un savoir **se supersède**, jamais ne s'efface. On garde la trace de ce qu'on a cru.

> **▸ Contrôle** :
> ```bash
> BASE=<votre_base>
> sudo -u postgres psql -p "$PGPORT_BASE" -tAc "SELECT datname FROM pg_database WHERE datname='$BASE'"
> sudo -u postgres psql -p "$PGPORT_BASE" -tAc "SELECT rolname, coalesce(shobj_description(oid,'pg_authid'),'—')
>                             FROM pg_roles WHERE rolname LIKE 'arac\_${BASE}\_%' ORDER BY 1"
> sudo ls -l "/etc/arac/$BASE/"
> sudo stat -c '%a %U' "/etc/arac/$BASE"    # le DOSSIER : `ls -l` ne montre pas son mode
> ```
> **Doit répondre** : le nom de votre base ; les rôles `arac_<votre_base>_*`, **chacun
> portant sa plaque** — quatre champs, de cette forme :
> `arac:cerveau=<votre_base>;proprietaire=<vous>;empreinte=<votre_empreinte>;secrets=/etc/arac/<votre_base>` ;
> `arac.env` et `roles.env` en `-rw------- root root`, et `700 root` pour le dossier qui
> les porte. *(`cockpit.env` n'existe pas encore : il naît à l'étape 7.)*
>
> Le critère qui compte n'est pas *combien* de rôles répondent — la liste bouge avec les
> migrations — ni le **nom** que la plaque porte : c'est l'**empreinte**. Deux personnes
> qui appellent leur cerveau « perso » posent, au caractère près, les mêmes champs
> `cerveau=` et `secrets=` ; seule `empreinte=` appartient à *une* installation. La vôtre
> est dans votre coffre :
> ```bash
> sudo grep '^ARAC_INSTALL_UUID=' "/etc/arac/$BASE/arac.env"
> ```
> **Tous** les rôles doivent porter celle-là, **aucun** une autre.

### Étape 4/11 — `vecteurs` : pgvector

`CREATE EXTENSION vector` et `pg_trgm` dans **votre** base (les extensions sont par
base, pas par cluster).

**Pourquoi `halfvec` et pas `vector`.** Le modèle d'embeddings produit 3 072 dimensions.
Or l'index HNSW de pgvector — celui qui rend la recherche rapide — plafonne à
2 000 dimensions pour le type `vector`. Le schéma utilise donc `halfvec(3072)` :
demi-précision, deux fois moins de place, indexable. La perte de précision est
indétectable au rappel ; l'absence d'index, elle, se voit tout de suite.

> **▸ Contrôle** :
> ```bash
> sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc "SELECT extname, extversion FROM pg_extension ORDER BY 1"
> ```
> **Doit répondre** au moins `pg_trgm`, `plpgsql` et `vector`.

### Étape 5/11 — `migrations` : le schéma

Crée le venv si besoin, installe les dépendances, applique la chaîne Alembic
(`alembic upgrade head`) sous le rôle d'administration de **votre** cerveau
(`arac_<votre_base>_admin`), puis réapplique les droits sur les tables créées.

C'est l'étape la plus longue, et celle qui décide de ce dont le cerveau pourra se
souvenir — notamment le format de `source_ref`, le lien entre un souvenir et la
conversation qui l'a produit. Relisez le §0 à ce sujet.

> **▸ Contrôle** :
> ```bash
> sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc "SELECT version_num FROM arac.alembic_version"
> sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='arac'"
> ```
> **Doit répondre** : une **révision non vide** et un **compte de tables non nul**. Ne
> comparez ni l'une ni l'autre aux nôtres — ce document ne nomme pas de révision, et ne
> donne pas de compte de tables : les deux montent à chaque migration ajoutée, et un
> chiffre exact recopié dans un manuel se périme le jour même. Ce contrôle a longtemps
> annoncé « un nombre de tables à deux chiffres », ce qui était vrai jusqu'à la centième.
> Le critère qui reste vrai, lui, est celui-ci : *quelque chose* répond aux deux requêtes.
> Si la première rend une ligne vide, ou l'erreur
> `relation "arac.alembic_version" does not exist`, les migrations n'ont pas été
> appliquées du tout.
>
> **Si Alembic s'arrête** : la cause est presque toujours une extension manquante
> (revenez à l'étape 4) ou un défaut de droits. Le message d'Alembic est le bon point de
> départ. Puis : `sudo ./bootstrap/bootstrap.sh --from migrations`.

### Étape 6/11 — `scopes` : semer votre taxonomie

Régénère `app/schemas/scope_generated.py` et `db/seeds/scopes.sql` depuis
`config/scopes.toml`, puis peuple `arac.scopes`. Le seed est un `INSERT … ON CONFLICT` :
il ne supprime jamais rien.

> **▸ Contrôle** :
> ```bash
> sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc "SELECT count(*) FROM arac.scopes"
> ```
> **Doit répondre** : racines + feuilles, exactement le nombre annoncé par
> `generate_scopes.py`.
>
> **Après toute modification de votre taxonomie** :
> `sudo ./bootstrap/bootstrap.sh --scopes-only`. La commande **refuse de retirer un
> domaine encore habité** : elle vous dit lesquels et vous laisse décider.

### Étape 7/11 — `secrets` : quatre valeurs qui décident de qui peut toucher

Engendre, dans `/etc/arac/<votre_base>/` (dossier `0700`, fichiers `0600`, `root`) :

| Secret | Ce qu'il protège |
|---|---|
| jeton porteur de l'API | toute écriture dans la mémoire, et toute lecture par l'API. Il est exigé **partout**, `127.0.0.1` compris — seul `/healthz` reste public. La posture d'origine l'exemptait sur la boucle locale, en supposant que `127.0.0.1` n'est atteignable qu'après un tunnel SSH ; **cette supposition tombe dès qu'un second compte a un shell sur la machine**, et un second cerveau en amène un. Le desserrage reste possible, mais il exige d'être **écrit et motivé** ([`CONFIGURATION.md` §6](CONFIGURATION.md#6-lapi)). |
| secret de session du cockpit | les cookies. Le voler, c'est fabriquer une session valide sans mot de passe. |
| empreinte du mot de passe | vous, devant le cockpit. Le serveur ne connaît pas votre mot de passe, seulement de quoi vérifier que vous le connaissez. |
| secret TOTP | le second facteur. Même votre mot de passe volé ne suffit pas. |

L'empreinte est au format `pbkdf2_sha256$<itérations>$<sel hex>$<empreinte hex>`,
260 000 itérations par défaut. Le nombre d'itérations est **stocké dans l'empreinte** :
on pourra l'augmenter plus tard sans invalider les anciennes.

**C'est ici que le TOTP s'appaire.** Le script affiche un secret base32 ; recopiez-le
dans votre application d'authentification et rendez le code à six chiffres. Notez le
secret ailleurs : si vous perdez l'appareil, la seule issue est de supprimer la ligne
`ARAC_CC_TOTP_SECRET` et de rejouer `--only secrets`.

> **▸ Contrôle** :
> ```bash
> sudo ls -l /etc/arac/<votre_base>/
> sudo stat -c '%a %U' /etc/arac/<votre_base>/arac.env
> sudo stat -c '%a %U' /etc/arac/<votre_base>          # le DOSSIER, pas son contenu
> ```
> **Doit répondre** : `arac.env`, `roles.env`, `cockpit.env`, tous en `600 root` — puis
> `700 root` pour le dossier.
>
> **La troisième ligne n'est pas un doublon.** `ls -l <dossier>/` liste ce qu'il *contient*
> et ne dit jamais son propre mode : ce contrôle a longtemps exigé « dans un dossier
> `700 root` » sans qu'aucune des commandes imprimées ne le montre. Or c'est le mode du
> dossier qui décide si un autre compte de la machine peut **entrer** — les `600` des
> fichiers ne protègent que la lecture directe.

### Étape 8/11 — `cles` : ce qui se paie, et ce que chaque chose paie

Le bootstrap **annonce le coût avant de demander la clé**, et il dit **qui lit quoi** —
parce que les deux clés qu'il écrit ne sont pas du tout du même genre :

| Variable écrite | Qui la lit | Ce qu'elle paie |
|---|---|---|
| `ARAC_EMBEDDINGS_API_KEY` → `OPENAI_API_KEY` | **ARAC lui-même** (`app/services/embeddings.py`) | un vecteur par souvenir **produit** — jamais par message ingéré — et un par question posée au rappel |
| `ARAC_CURATION_API_KEY` → `ANTHROPIC_API_KEY` | **jamais ARAC** : le binaire `claude`, lancé par le cycle, la trouve dans l'environnement du service | les jetons de la digestion, à l'appel. **Inutile si une session d'abonnement est ouverte pour le compte d'agent** — le bootstrap le constate et vous le dit. |

| Ce qui manque | Conséquence |
|---|---|
| la clé d'embeddings | les souvenirs n'ont pas de vecteur : le rappel par similarité est mort. |
| le **binaire** de curation | les cycles s'exécutent et ne produisent **aucun** atome — et **aucune clé n'y change rien**. |
| l'authentification du binaire (ni session, ni clé) | le cycle spawne et récolte « Not logged in ». Même résultat, autre cause. |

Le mode dégradé `curation` ne se déclare donc plus sur l'absence d'une clé, mais sur ce
qui décide réellement : le binaire est-il là, et a-t-il de quoi s'authentifier ?

> **▸ Contrôle** :
> ```bash
> sudo grep -c '^ARAC_EMBEDDINGS_API_KEY=\|^ARAC_CURATION_API_KEY=' /etc/arac/<votre_base>/arac.env
> sudo grep '^ARAC_MODE_DEGRADE=' /etc/arac/<votre_base>/arac.env
> ```
> **Doit répondre — et il y a TROIS réponses justes, selon ce que vous venez de
> décider :**
>
> · **vous avez donné les deux clés** → `2`, puis un `ARAC_MODE_DEGRADE=` vide ;
> · **vous avez donné la clé d'embeddings, et votre binaire `claude` a déjà une session
>   d'abonnement** → `1`, et un `ARAC_MODE_DEGRADE=` **vide quand même**. C'est le cas
>   normal de qui est déjà abonné : il n'y a pas de clé de curation à acheter, et
>   l'absence de cette ligne n'est pas une amputation ;
> · **vous les avez refusées**, ce que le paragraphe ci-dessus autorise en toutes lettres
>   → `0`, et le premier `grep` **sort en code 1** — c'est `grep` qui n'a rien trouvé, pas
>   votre installation qui a échoué —, puis `ARAC_MODE_DEGRADE=embeddings,curation`. C'est
>   l'état attendu d'un cerveau qui ingère mais n'apprend pas ; `verify_install.sh` le
>   redira, sans compter cela comme un échec.
>
> **Le critère n'est donc pas un chiffre, et ce n'est plus « une clé par fonction ».**
> C'est la cohérence entre les deux lignes **et ce que le binaire a sous la main** :
> `ARAC_MODE_DEGRADE` doit nommer `curation` si et seulement si **ni** le binaire **ni**
> son authentification ne sont là. La mesure qui tranche, et qui ne dépense rien :
>
> ```bash
> cd /chemin/de/votre/clone && sudo .venv/bin/python -m agents.lib.paid_ai_control status \
>      --coffre /etc/arac/<votre_base>/arac.env
> ```
>
> Sa ligne `Curation (binaire):` répond `OUI — <chemin>` ou `NON`, et c'est celle-là qui
> décide si votre cerveau apprendra.

### Étape 9/11 — `services` : le cerveau se met à vivre tout seul

Cinq unités et trois minuteries dans `/etc/systemd/system` :

| Unité | Rôle |
|---|---|
| `arac-<base>-api.service` | l'API, sur `127.0.0.1` et **le port attribué à ce cerveau** |
| `arac-<base>-cockpit.service` | le cockpit, sur `127.0.0.1` et **son propre port** |
| `arac-<base>-cycle.service` + `.timer` | la digestion, 04:00 · 13:00 · 21:00 |
| `arac-<base>-sauvegarde.service` + `.timer` | la sauvegarde par `ops/backup.sh`, toutes les six heures |
| `arac-<base>-restauration.service` + `.timer` | la restauration **prouvée** par `ops/restore_verify.sh`, dimanche 03:00 |

La liste exacte est celle que porte votre machine, pas celle-ci :
`systemctl list-units --all 'arac-<base>-*'`.

> **Les deux numéros de port sont ceux de VOTRE cerveau, et vous ne les choisissez pas.**
> L'étape 2 en a constaté deux libres, les a attribués, et les a **écrits** dans
> `/etc/arac/<votre_base>/arac.env`. Sur une machine qui héberge déjà un cerveau, ils ne
> seront pas les mêmes que les siens. **Toute** commande de ce document qui touche à un
> port les relit ; aucune n'en écrit un en clair. Pour les connaître :
>
> ```bash
> BASE=<votre_base>
> API=$(systemctl show "arac-$BASE-api"     -p ExecStart --value | sed -n 's/.*--port \([0-9]\{1,\}\).*/\1/p')
> CC=$( systemctl show "arac-$BASE-cockpit" -p ExecStart --value | sed -n 's/.*--port \([0-9]\{1,\}\).*/\1/p')
> echo "API $API · cockpit $CC"
> ```
>
> On lit ici l'unité plutôt que le fichier d'environnement : l'unité est ce qui **lie**
> réellement le port, donc la seule source qui ne puisse pas mentir. Gardez `$BASE`,
> `$API` et `$CC` dans votre terminal — le reste du document s'en sert.

Deux utilisateurs système sont créés, et ils **portent le nom de votre cerveau** :
`arac_<base>` (API et cockpit) et `aracagent_<base>` (les cycles) — un nom trop long est
tronqué puis suffixé d'une empreinte, ce qui se lit et ne se recalcule pas
(`systemctl show "arac-<base>-api" -p User --value`). C'était le dernier identifiant
partagé du produit : deux services sous le même UID lisent le `/proc/<pid>/environ` l'un de
l'autre, mots de passe compris. `systemd` lit les fichiers de secrets en PID 1 (root) **avant** d'abandonner
ses privilèges : les services tournent sous un utilisateur sans droits et n'accèdent
jamais aux fichiers eux-mêmes.

Les unités portent `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`,
`ProtectHome`, et le cycle est `Type=oneshot` avec `StartLimitBurst=10` par heure : le
cerveau ne peut pas se mettre à penser en rond.

> ⚠ **Le seul geste destructeur de tout le bootstrap** est ici : l'unité de sauvegarde
> supprime les dumps de plus de `ARAC_BACKUP_RETENTION` jours (14 par défaut) dans
> `/var/backups/arac/<votre_base>/` — **son** sous-dossier, jamais le dossier commun.
> C'est annoncé avant d'être posé. Pour le changer :
> `sudo ARAC_BACKUP_RETENTION=90 ./bootstrap/bootstrap.sh --only services`.

> **▸ Contrôle** :
> ```bash
> systemctl list-units "arac-$BASE-*" --all --no-pager
> systemctl cat "arac-$BASE-api.service"
> sudo ss -ltnp | grep -E "127\.0\.0\.1:($API|$CC)\b"
> ```
> **Doit répondre** : **toutes les unités que le tableau ci-dessus nomme**, sans exception
> — et `arac-<base>-restauration` en fait partie, c'est celle qu'on oublie ; le contenu de
> l'unité ; et **deux lignes d'écoute sur 127.0.0.1 uniquement**.
>
> *Le critère est la liste nommée, pas son cardinal : ce tableau en compte cinq et trois
> aujourd'hui, et ce compte montera le jour où une unité s'ajoutera. C'est votre machine
> qui fait foi — `systemctl list-units --all "arac-$BASE-*"` —, jamais un chiffre écrit
> ici.* Si l'adresse est `0.0.0.0`,
> arrêtez tout : quelque chose a été modifié, l'API n'est pas censée être joignable de
> l'extérieur.
>
> **Et vérifiez QUI écoute, pas seulement que quelqu'un écoute.** Le PID posé sur le port
> doit être celui de **votre** unité :
> ```bash
> systemctl show "arac-$BASE-api" -p MainPID --value
> sudo ss -ltnp "sport = :$API" | sed -n 's/.*pid=\([0-9]\{1,\}\),.*/\1/p'
> ```
> **Les deux nombres doivent être égaux.** S'ils diffèrent, un autre processus tient le
> port et répondra à votre place : c'est exactement la panne qui a fait déclarer saine une
> production morte. `bootstrap/checks/verify_install.sh` fait ce contrôle pour vous, et va
> plus loin — il lit `ARAC_DB` dans `/proc/<pid>/environ` pour nommer le cerveau derrière
> la socket.
>
> **Si un service ne démarre pas**, c'est presque toujours l'étape 6 de ce document —
> voir juste en dessous. Diagnostic :
> `journalctl -u arac-<votre_base>-api.service -n 40 --no-pager`.

### Étape 10/11 — `controle` : le rapport

Délègue à `bootstrap/checks/verify_install.sh`. Voir §7.

### Étape 11/11 — l'épilogue

Du texte, pas une action : la chaîne complète de bout en bout, vos commandes
personnalisées pour le tunnel et le premier cycle, et trois leçons mesurées à connaître
avant de juger votre cerveau (36 % de cycles stériles, 96 % de rappels en confiance
basse, 98 % du savoir jamais audité).

---

## 6. Les trois raccords — deux posés, un à finir vous-même

> Cette section a longtemps décrit trois gestes manquants. Le bootstrap les pose
> maintenant tous. Elle reste ici parce que ces raccords **échouent en silence** : ce qui
> compte, c'est de savoir les vérifier — sur VOTRE machine, avec les commandes ci-dessous,
> et pas en croyant ce paragraphe.

**1. Le pont de vocabulaire — posé pour l'API ET pour le cockpit.** `bootstrap.sh` écrit
ses variables sous des noms préfixés ; le moteur extrait de la source lit encore les noms
historiques. Sans traduction, l'API démarre puis s'arrête sur
`DATABASE_URL_APP non définie`, et le cockpit refuse toute connexion. À la fin de son
étape des clés, `poser_pont_de_vocabulaire` (`bootstrap/lib/secrets.sh`) **copie** chaque
variable sous l'autre nom, dans `arac.env` **et** dans `cockpit.env` — chaque valeur
restant dans le fichier où elle est née. Deux `grep` tranchent :

```bash
sudo grep -c '^DATABASE_URL_' "/etc/arac/$BASE/arac.env"      # attendu : 4
sudo grep -cE '^(CC_SESSION_SECRET|CC_ADMIN_PASSWORD_HASH|CC_TOTP_SECRET)=' \
     "/etc/arac/$BASE/cockpit.env"                            # attendu : 3
```

Si l'un des deux rend `0`, votre installation est **antérieure** à ce correctif. Le tableau
des correspondances est dans
[`CONFIGURATION.md`](CONFIGURATION.md#le-double-vocabulaire) ; le geste manuel, qui traite
**les deux fichiers**, dans
[`DEPANNAGE.md` §1](DEPANNAGE.md#1-lapi-ne-démarre-pas--database_url_app-non-définie).

**2 et 3. Les deux portes de l'ingestion.** L'API n'accepte une conversation que si le
poste qui la dépose figure dans la liste blanche `ARAC_INGEST_ALLOWED_NODES` **et** dans
la table `arac.nodes` (clé étrangère obligatoire). Les deux sont **fail-closed** : liste
absente ou vide, et tout repart en `403`, jeton valide compris. Le bootstrap écrit la
liste blanche depuis l'identité de votre entretien (`bootstrap/lib/secrets.sh`), et la
migration `0008` déclare votre poste dans `arac.nodes` en lisant le même
`config/brain.toml`.

Ce qu'il vous reste : constater que les trois écritures du `node_id` coïncident. Un tiret
de différence suffit à tout perdre.

> **Le sort de `db/seeds/01_nodes_and_config.sql`.** Sa moitié `arac.nodes` est devenue
> redondante : la migration `0008` fait déjà le travail pour le poste de votre entretien.
> Sa moitié `arac.arac_config` (modèle d'embedding, dimension, constantes de rappel…),
> elle, **n'est appliquée par rien** — sur une installation neuve, `arac.arac_config` est
> vide. Ce n'est pas bloquant : le code retombe sur ses valeurs par défaut, et
> `paid_ai_enabled` absent vaut *IA payante désarmée*, ce qui est le bon défaut. Mais si
> vous voulez ces constantes lisibles et modifiables en base, appliquez le seed :
> ```bash
> sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -v ON_ERROR_STOP=1 \
>      -v arac_node_id="$(.venv/bin/python -c 'import arac_runtime; print(arac_runtime.node_id())')" \
>      -f db/seeds/01_nodes_and_config.sql
> ```
> Il est idempotent (`ON CONFLICT`) et ne supprime rien.

> **▸ Contrôle** :
> ```bash
> sudo grep -c '^DATABASE_URL_' /etc/arac/<votre_base>/arac.env
> sudo grep -c '^ARAC_INGEST_ALLOWED_NODES=' /etc/arac/<votre_base>/arac.env
> sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc \
>      "SELECT node_id FROM arac.nodes WHERE active ORDER BY 1"
> curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:$API/healthz"
> ```
> **Doit répondre** : `4`, `1`, **exactement** le `node_id` de votre `config/brain.toml`,
> puis `200`.
>
> **Le critère des deux premiers est « non nul », pas le chiffre.** `4`, c'est le nombre de
> DSN d'aujourd'hui — un par rôle qui se connecte (`ADMIN`, `APP`, `AGENT`, `READONLY`) ;
> il montera le jour où un cinquième rôle se connectera. Ce qui doit vous arrêter, c'est
> `0` : le pont de vocabulaire n'a pas été posé, et l'API s'arrêtera sur
> `DATABASE_URL_APP non définie`.
>
> **Pourquoi `WHERE active`, et pas `SELECT node_id FROM arac.nodes` tout court.** La
> table en contient **deux** sur une installation neuve, et c'est normal : la migration
> `0020` déclare aussi `<votre_node_id>-server`, le poste que le serveur lui-même
> représente pour l'inventaire des sources d'ingestion — il naît `active = false`, et rien
> n'ingère sous ce nom. Ce contrôle a longtemps imprimé la requête nue en annonçant une
> seule ligne : un lecteur qui en obtenait deux croyait à un doublon sur son installation
> parfaitement saine. Si vous voulez les voir toutes :
> `SELECT node_id, active FROM arac.nodes ORDER BY 1`.
>
> `$API` est le port de **votre** API — voir l'encadré de l'étape 9. Sur une machine qui
> héberge un autre cerveau, un `200` obtenu sur un numéro écrit en dur ne prouve rien :
> il prouve que *quelqu'un* répond, pas que c'est vous.

---

## 7. Le contrôle a posteriori

```bash
./bootstrap/checks/verify_install.sh          # partiel, sans root
sudo ./bootstrap/checks/verify_install.sh     # complet — il lit les secrets
```

Il ne modifie **rien**. Les familles de contrôles sont **numérotées de 0 à 8**, et ce
n'est pas cette page qui les compte : c'est le script, qui les annonce lui-même.
**Demandez-lui la liste** — il n'a besoin d'aucune installation pour la donner :

```bash
./bootstrap/checks/verify_install.sh --simulation
```

0. **le contrat des variables d'environnement** — `.env.example` contre le code. C'est le
   seul contrôle qui n'exige rien d'installé : `--simulation` le joue **pour de vrai**,
   même sur un dépôt fraîchement cloné ;
1. **la description** — `brain.toml`, `scopes.toml`, taxonomie à jour ;
2. **la base** — existence, pgvector, tables, révision du schéma ;
3. **les rôles** — les quatre rôles qui se connectent existent, chacun se connecte, et une
   **tentative d'écriture réelle** avec le rôle du cockpit doit **échouer** ;
4. **la taxonomie et ce qu'elle porte** — dont deux comptages qui n'existent que parce
   qu'ils ont coûté cher : les souvenirs posés sur une **racine** nue (donc hors de l'état
   courant, de la vue des scopes et de la couverture) et les souvenirs **sans provenance**
   (donc invérifiables) ;
5. **les secrets** — présence, permissions, mode dégradé éventuel ;
6. **les services** — actifs, et le port tenu par **ce** cerveau ;
7. **les sauvegardes de ce cerveau** — la dernière, son âge, et comment la restaurer ;
8. **le croisement code ↔ schéma** — tout ce que le code nomme existe-t-il en base ?

Le contrôle n°3 mérite d'être compris : il ne lit pas la configuration du rôle, il
**essaie d'écrire** et exige que PostgreSQL refuse. On ne vérifie pas une promesse, on
vérifie une garantie.

> **▸ Contrôle** : **`en échec 0`**, et l'une des **deux** phrases de réussite —
> `✓ Ce cerveau est sain.` (rien à surveiller) ou `✓ Ce cerveau fonctionne.` (des points
> à surveiller, qui ne l'empêchent pas de vivre). Les deux rendent le code de sortie `0`.
> Le nombre de contrôles sains dépend de votre installation : ne le comparez à rien.
> N'attendez pas non plus zéro point à surveiller — une installation entièrement réussie
> en porte normalement quelques-uns au premier passage. Chaque ✗ porte le geste exact qui
> le corrige.

Un second outil, complémentaire, regarde l'exploitation plutôt que l'installation :

```bash
ops/install_check.sh
```

Cinq familles, que le script imprime en tête de chacune : le dépôt et son environnement,
l'identité et la taxonomie, la base et ses rôles, la sauvegarde, les services. Le
**nombre** de contrôles n'est écrit nulle part et ne doit l'être nulle part — il dépend
de votre installation, et le script le compte lui-même en dernière ligne
(« *N* contrôle(s) au vert, *M* réserve(s), *P* panne(s) »). Il lit `$ARAC_HOME/.env`,
pas `/etc/arac/…` — voir
[`CONFIGURATION.md`](CONFIGURATION.md#les-deux-fichiers-denvironnement).

---

## 8. Le tunnel et le cockpit

L'API et le cockpit n'écoutent que sur `127.0.0.1`. **Rien n'est exposé à l'Internet,
donc rien n'a besoin d'être défendu contre lui.** Il n'y a ni TLS à installer, ni
reverse-proxy, ni pare-feu à régler. C'est un choix, et c'est le plus sûr disponible
pour un service personnel.

**Le tunnel transporte les deux ports de votre cerveau, pas deux numéros convenus
d'avance.** Notez-les sur le serveur (encadré de l'étape 9), puis, depuis votre machine :

```bash
API=<le port API de votre cerveau>          # relevé sur le serveur
CC=<le port cockpit de votre cerveau>
ssh -N -L "$CC:127.0.0.1:$CC" -L "$API:127.0.0.1:$API" <utilisateur>@<votre-serveur>
```

Puis `http://127.0.0.1:$CC` dans le navigateur. Mot de passe, puis code à six chiffres.

Sur un Mac, ne montez pas ce tunnel à la main : `mac/arac-pont.sh tunnel ouvrir` le fait,
en lisant `ARAC_PORT_API` et `ARAC_PORT_COCKPIT` dans `~/.arac/<votre_base>/pont.conf` —
deux valeurs **sans défaut**, précisément pour qu'un numéro plausible ne vous branche pas
sur le cerveau du voisin.

Pour durcir la porte côté serveur (client alive, libération des tunnels morts, clé
bridée à deux ports uniquement) : `deploy/ssh/`, et son `README.md` qui explique
pourquoi un tunnel plutôt qu'une adresse publique.

> **▸ Contrôle**, depuis votre machine, tunnel ouvert :
> ```bash
> curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:$CC"
> ```
> **Doit répondre** : un code HTTP, **et c'est tout le critère** — sur une installation
> saine la racine rend `307` (redirection vers `/cc/`), puis `/cc/` rend `302` vers
> `/cc/login`, qui rend `200`. Ne retenez pas ces trois nombres : ils dépendent du chemin
> exact que vous demandez et de la version du cockpit. Ce que ce contrôle prouve, c'est
> que **quelque chose répond au bout du tunnel** ; ce qui le fait échouer, c'est
> `000` — `curl` n'a pas pu se connecter du tout : le tunnel n'est pas ouvert, ou le
> service ne tourne pas.
>
> Pour aller jusqu'à la page de connexion en une commande, laissez `curl` suivre les
> redirections :
> ```bash
> curl -sL -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:$CC"   # attendu : 200
> ```
> Dans un navigateur, vous ne verrez rien de tout cela : vous arriverez sur le formulaire,
> qui vous demandera un mot de passe puis un code à six chiffres.

---

## 9. La machine source

Tout est dans [`PONT-MAC.md`](PONT-MAC.md), qui raconte la chaîne de bout en bout, dit
où sont réellement les conversations, liste les pannes courantes et leur diagnostic,
donne une liste de contrôle à exécuter, et déclare honnêtement ce qui n'a pas pu être
vérifié faute de Mac.

Le résumé :

```bash
# sur le serveur : récupérer le jeton porteur (root uniquement)
sudo grep '^ARAC_API_BEARER_TOKEN=' /etc/arac/<votre_base>/arac.env

# sur votre machine
./arac-pont.sh installer          # ~/.arac, la configuration, trois questions
./arac-pont.sh cle-ssh            # la clé du tunnel + dépôt du jeton d'ingestion
./arac-pont.sh premiere-synchro   # le trajet complet, raconté
./arac-pont.sh automatiser        # launchd prend le relais
./arac-pont.sh etat               # à tout moment : quel maillon est cassé ?
```

**L'ordre d'installation général** est : le cerveau (§5), puis la porte
(`deploy/ssh/`), puis le pont. Le pont vient en dernier : il n'a rien à traverser tant
qu'il n'y a personne de l'autre côté.

> **▸ Contrôle** : le **deuxième** passage de synchronisation doit répondre `code=0` et
> « Rien de nouveau ». Si des messages repartent, l'état ne se sauve pas — vérifiez les
> droits de `~/.arac`.

---

## 10. Le premier cycle

**D'abord les deux interrupteurs, sinon ce geste sera refusé.** Sur un cerveau neuf ils
sont fermés — c'est voulu, rien ne dépense votre argent sans un geste humain — et le
premier `systemctl start` est donc refusé sur **cent pour cent** des installations
neuves :

```bash
# 1/2 — côté service, dans le coffre
sudo sed -i 's/^ARAC_ALLOW_PAID_AI=.*/ARAC_ALLOW_PAID_AI=1/' /etc/arac/<votre_base>/arac.env

# 2/2 — côté cerveau, EN BASE : il n'est dans aucun fichier
sudo .venv/bin/python -m agents.lib.paid_ai_control arm --confirm \
     --coffre /etc/arac/<votre_base>/arac.env
```

Puis :

```bash
sudo systemctl start arac-<votre_base>-cycle.service
journalctl -u arac-<votre_base>-cycle.service -f
```

> **▸ Contrôle** :
> ```bash
> sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc "SELECT count(*) FROM arac.memory_atoms WHERE status='active'"
> ```
> **Doit répondre** : un nombre supérieur à zéro, après un cycle réussi qui avait des
> conversations à digérer.

**Si le compte reste à zéro**, cherchez dans l'ordre où le cycle lui-même refuse, et lisez
le code que porte `journalctl` :

1. `master_switch_env_off` — **interrupteur 1/2**, ci-dessus. État d'usine ;
2. `master_switch_config_off` — **interrupteur 2/2**, en base. État d'usine, et il n'est
   dans aucun fichier ;
3. `kill_switch_active` — posé à la main, jamais retiré tout seul ; `arm --confirm` le
   retire ;
4. `spawn_failed` ou « Not logged in » — le **binaire `claude`** manque, n'est pas
   exécutable par le compte d'agent, ou n'a pas de session **sous le dossier personnel de
   ce compte** ;
5. `cortex.duplicate_slot` — vous avez réparé puis relancé, et le créneau du jour est déjà
   pris. Posez `ARAC_CORTEX_FORCE_MANUAL=1` dans le coffre, relancez, **puis retirez la
   ligne** ;
6. `daily_*_exhausted` — pas une panne : le plafond du jour est atteint ;
7. la file est vide — rien n'est entré, rien ne peut sortir (revoir §9) ;
8. **seulement ensuite**, l'incohérence des identifiants de poste : 36 % des cycles du
   cerveau de référence sont partis en quarantaine pour cette raison, mais c'est un
   défaut de **rendement** sur un cerveau qui tourne, pas la cause d'un premier cycle
   stérile. Comparez alors `ARAC_NODE_ID` côté serveur et côté machine source.

Voir [`DEPANNAGE.md` §5](DEPANNAGE.md#5-les-cycles-tournent-et-ne-produisent-aucun-souvenir).

---

## 11. Les sauvegardes

Le bootstrap a armé **deux** choses, et elles sont déjà sérieuses : `ops/backup.sh` toutes
les six heures — avec ses quatre contrôles de sincérité du dump — et `ops/restore_verify.sh`
le dimanche à 03:00, qui restaure réellement dans une base jetable et compare. C'est ce
second point qui fait la différence entre une sauvegarde et un fichier dont on suppose
qu'il contient quelque chose.

Il reste **trois** dispositifs qu'`ops/` fournit et que le bootstrap ne peut pas armer à
votre place, parce qu'ils réclament une décision qui n'est pas la sienne : le chiffrement
au repos avec une clé qui ne vit pas sur le serveur, la copie hors site (vers quoi ?), et
le chien de garde qui surveille la *garantie* plutôt que les scripts (qui alerter ?).
Tant qu'ils ne sont pas armés, vos dumps sont **en clair et sur cette seule machine** —
`ops/install_check.sh` le répète à chaque passage.

```bash
BASE=<votre_base>
# À POSER EN PREMIER, et c'est la ligne qu'on oublie. Sans elle, sur une machine
# qui porte plusieurs cerveaux, `ops/` ne s'arrête pas : il sert celui que CE
# CLONE décrit (config/brain.toml) et l'annonce avant d'agir — « ops/ sert le
# cerveau « … » — ce dépôt le décrit, il n'a pas été deviné ». C'est exact tant
# qu'un clone ne sert qu'un cerveau (§12.d) ; la variable, elle, ne dépend pas
# du dossier d'où vous tapez. Les cinq rangs : docs/CONFIGURATION.md, § 9.
export ARAC_ENV_FILE="/etc/arac/$BASE/arac.env"
source ops/env.sh          # pose $ARAC_BACKUP_DIR, $ARAC_BACKUP_STATE, $ARAC_BACKUP_PREFIX
export ARAC_UNIT_PREFIX="arac-$ARAC_BACKUP_PREFIX"   # env.sh ne le pose pas
sudo install -d -m 0700 -o "$(id -un)" "$ARAC_BACKUP_DIR"
sudo install -d -m 0700 -o "$(id -un)" "$ARAC_BACKUP_STATE"

# Le gabarit : ce script IMPRIME le SQL et la commande qui l'exécute, port compris.
# Lisez-la, puis recopiez-la — ne la tuyautez pas en aveugle : le bloc commence
# par un DROP DATABASE, et sans « -p » il tombe sur la grappe par défaut de la
# machine, c'est-à-dire sur le gabarit du voisin.
ops/restore_verify.sh --prepare-template

# Ces deux-là s'appuient sur l'ARAC_ENV_FILE exporté en tête de bloc. Dans un
# autre terminal, reposez-la — sinon, sur une machine à plusieurs cerveaux, ils
# repartent du clone où vous êtes, et c'est LUI qui désignera le cerveau.
ops/backup.sh
ops/restore_verify.sh
# Ce répertoire ne contient QUE ce que le bootstrap n'arme pas : copie hors
# site, chien de garde, santé, contrôle d'installation, et la ligne tmpfiles.d
# des répertoires de sauvegarde. Il n'y a PAS de « …-backup.service » ici, et
# c'est voulu : la sauvegarde et la restauration vérifiée sont déjà armées.
ops/systemd/render.sh "/tmp/arac-units-$ARAC_UNIT_PREFIX" \
  && less "/tmp/arac-units-$ARAC_UNIT_PREFIX/$ARAC_UNIT_PREFIX-health.service"

# les vôtres, celles que le bootstrap a posées :
systemctl cat "$ARAC_UNIT_PREFIX-sauvegarde.service" "$ARAC_UNIT_PREFIX-restauration.service"
```

> **Si vous copiez la ligne tmpfiles.d de ce répertoire, notez-la quelque part.** Elle
> devient `/etc/tmpfiles.d/<prefixe>-backup.conf`, elle **recrée** vos répertoires de
> sauvegarde à chaque démarrage, et elle survit à une désinstallation qui ne la nomme pas —
> le §13 la nomme désormais, à son étape 7.

**Les deux `install -d` créent des sous-dossiers, jamais les dossiers communs.**
`/var/backups/arac/` et `/var/lib/arac/` sont partagés par tous les cerveaux de la
machine ; `ops/env.sh` y ajoute le vôtre (`ARAC_BACKUP_DIR`, `ARAC_BACKUP_STATE`) et
**refuse de deviner** s'il n'arrive pas à nommer le cerveau. Les unités engendrées par
`ops/systemd/render.sh` portent le même préfixe que celles du bootstrap
(`arac-<votre_base>-…`) : posez `ARAC_UNIT_PREFIX` si le script ne peut pas le déduire.

L'ordre compte : **armer un minuteur avant d'avoir vu la commande réussir une fois à la
main, c'est déléguer un problème qu'on n'a pas encore résolu.**

Tout est dans [`SAUVEGARDE.md`](SAUVEGARDE.md).

> **▸ Contrôle** : `ops/restore_verify.sh` doit restaurer pour de vrai et prouver le
> contenu. Tant que vous ne l'avez pas exécuté une fois, vos dumps sont une hypothèse.

---

## 12. Variantes

### a. PostgreSQL sur une autre machine

```bash
sudo ARAC_DB_HOTE=10.0.0.12 ARAC_DB_PORT=5432 ./bootstrap/bootstrap.sh
```

Ce que ça change :

- Il faut un superutilisateur PostgreSQL joignable depuis le serveur (`ARAC_PG_SUPERUSER`).
- `pg_hba.conf` doit accepter les quatre rôles depuis l'adresse du serveur applicatif.
- **Chiffrez le lien.** Une base à distance en clair transporte tous vos souvenirs sur
  le réseau. Utilisez `sslmode=require` au minimum, ou faites passer la connexion par un
  tunnel.
- Les sauvegardes s'exécutent depuis la machine applicative : `pg_dump` doit pouvoir
  joindre le serveur de base.

### b. PostgreSQL dans Docker

**Le framework lui-même n'est pas conteneurisé, et ce n'est pas un oubli** : `systemd`
et un environnement virtuel suffisent, se diagnostiquent mieux, et évitent une couche de
plus entre vous et la panne. Aucune image, aucun `docker-compose` n'est fourni ni testé.

Rien n'empêche cependant de faire tourner **la base** dans un conteneur — pour ARAC,
c'est une base distante comme une autre. Utilisez une image qui embarque pgvector,
publiez le port sur `127.0.0.1` uniquement, montez un volume persistant, et traitez le
cas comme la variante (a). **Non testé.**

### c. Sans Mac

Le pont est du Python de la bibliothèque standard : il tourne sur Linux, y compris sur
le serveur lui-même — auquel cas le tunnel devient inutile, tout étant déjà en local.
L'ordonnancement se fait alors par
`deploy/systemd/arac-pont-sans-mac.{service,timer}.modele`.

Ce qui est perdu : `launchctl`, `plutil`, les notifications macOS. Ce qui ne l'est pas :
tout le reste — inventaire, annonce avant envoi, déduplication, reprise, acquittement.

Ce qui est perdu **quelle que soit la plateforme** : la capture automatique de Claude
Desktop, qui n'existe pas (voir [`PONT-MAC.md`](PONT-MAC.md)). Vous alimenterez le
cerveau par l'export officiel de claude.ai, manuellement, et par Claude Code (CLI), qui
lui est capté automatiquement.

### d. Deux cerveaux sur la même machine

Tout ce qui dépend de votre identité est **engendré**, jamais recopié : lancez le bootstrap
du second cerveau, il ne vous demandera rien de particulier.

```bash
sudo ./bootstrap/bootstrap.sh
```

**Rien de plus n'est *exigé*** — et il y a un geste à connaître et une chose à lire. Le
geste : donner à ce second cerveau **sa propre grappe**, ce qui reste la voie recommandée
et se joue en deux lignes au [§12.f](#f-une-grappe-postgresql-pour-ce-cerveau) ; il faut
le décider **avant** de lancer le bootstrap, parce qu'il ne se rattrape pas après. La
chose à lire est en fin de section, sous
« La porte qui manquait à ce tableau ». C'était, jusqu'en août 2026, le dernier chemin par
lequel deux cerveaux d'une même machine se lisaient l'un l'autre. Il est fermé ; ce qui
reste est la leçon, et elle sert ailleurs.

Ce qui porte le nom du cerveau — et, **à la fin du tableau, ce qui ne le porte pas** :
c'est là que se logent les deux seules choses que deux cerveaux peuvent encore partager
sans que rien ne l'annonce.

| | Porte le nom du cerveau ? | Forme |
|---|---|---|
| la base | oui | `<base>` |
| les rôles | oui | `arac_<base>_admin` · `_app` · `_agent` · `_readonly` · `_backup` |
| les unités systemd | oui | `arac-<base>-api` · `-cockpit` · `-cycle` · `-sauvegarde` · `-restauration` (cinq, dont trois minuteries) |
| les secrets | oui | `/etc/arac/<base>/` en `0700` |
| les journaux | oui | `/var/log/arac/<base>/` |
| les sauvegardes | oui | `/var/backups/arac/<base>/` |
| l'état | oui | `/var/lib/arac/<base>/` |
| les ports | attribués, puis retenus | écrits dans `/etc/arac/<base>/arac.env` |
| les comptes système | oui | `arac_<base>` (API, cockpit) · `aracagent_<base>` (cycles) |
| le côté Mac | oui | `~/.arac/<base>/`, étiquettes launchd `com.arac.<base>.pont.*` |
| **le dépôt cloné** | **non** | **la seule pièce qui ne porte le nom de personne** — `config/scopes.toml` et la taxonomie engendrée y vivent. Deux cerveaux qui partagent un clone partagent leur taxonomie, et **rien ne le refuserait**. Un clone par cerveau, `/opt/<votre_base>` (§2), et `ARAC_HOME` pour le dire aux unités (§12.e) |
| la **grappe** PostgreSQL | non — commune par défaut | les rôles y sont **globaux** ; lui en donner une propre est le [§12.f](#f-une-grappe-postgresql-pour-ce-cerveau) |

> **La porte qui manquait à ce tableau, et ce qu'elle enseigne.** Un tableau qui n'énumère
> que ce qui est séparé se lit comme une preuve d'étanchéité, et c'en est l'inverse : ce
> qu'il ne nomme pas, personne ne le cherche. Il restait **une** porte ouverte — elle ne
> passait par aucun fichier, donc aucun mode Unix ne la fermait. **Elle est fermée
> aujourd'hui, et vous n'avez rien à faire** ; ce qui suit est la leçon, qui vaut plus que
> le réglage.
>
> **Ce qui était ouvert.** L'API n'exigeait aucun jeton sur `127.0.0.1`. Sur une machine à
> deux cerveaux, n'importe quel compte local — même non privilégié, même sans tunnel —
> **lisait** la mémoire de l'autre cerveau (`GET /v1/dashboard/…` → `200`) et y **écrivait**
> de faux souvenirs (`POST /v1/ingest/messages` → `202`), sans présenter un seul secret.
>
> **Ce qui ne la fermait pas — c'est là qu'est la leçon.** Rôles PostgreSQL par cerveau,
> coffres en `0700`, comptes système distincts, grappes séparées, unités nommées : tout le
> tableau ci-dessus était déjà en place, et pas une ligne ne voyait cette porte. Elle était
> en HTTP, pas sur le disque, et **les permissions ne protègent que ce qui est un fichier.**
> Le raisonnement qui l'avait laissée ouverte était pourtant bon : « l'API n'écoute que
> `127.0.0.1`, on n'y arrive que par le tunnel SSH, donc SSH est la frontière ». Il
> reposait sur une prémisse que personne n'avait écrite — *qu'atteindre `127.0.0.1` exige
> d'avoir franchi SSH* — et qui est fausse dès qu'un second compte a un shell.
>
> **La règle à emporter** : une exemption fondée sur l'**origine** d'une requête ne vaut
> que ce que vaut l'hypothèse sur qui peut prendre cette origine. Ici, `127.0.0.1` ne
> prouve pas « c'est le propriétaire » : elle prouve « c'est quelqu'un sur cette machine »
> — exactement la population dont on voulait se protéger.
>
> **Ce qui est vrai maintenant.** Le jeton est exigé de **toute** requête, boucle locale
> comprise ; seul `/healthz` reste public. Le défaut est fermé, donc identique pour un
> cerveau installé seul et pour un cerveau installé à côté d'un autre : l'ordre
> d'installation ne décide plus de rien. Rien ne vous est demandé — le bootstrap engendre
> déjà le jeton et tout ce qui appelle l'API le porte. Rouvrir la boucle locale reste
> possible et demande **deux** variables, dont un motif écrit : sans le motif, le
> desserrage n'est pas appliqué ([`CONFIGURATION.md` §6](CONFIGURATION.md#6-lapi)).

**Les ports ne se posent plus à la main.** L'étape 2 constate qu'un numéro est libre
*avant* de l'attribuer, puis l'**écrit** dans `/etc/arac/<base>/arac.env` : une
réinstallation le relit au lieu d'en choisir un autre. Si vous en imposez un
(`ARAC_API_PORT=…`) et qu'il est déjà tenu, le bootstrap **refuse** en nommant son
occupant — il ne déplace jamais votre choix en douce.

> **Ce que le bootstrap contrôle avant d'écrire quoi que ce soit.** Les rôles PostgreSQL
> sont globaux au **cluster** : c'est ce qui a détruit le cerveau de production de
> l'auteur, quand un second bootstrap a réencodé les mots de passe du premier. Chaque rôle
> créé porte désormais une **plaque de propriété** — `COMMENT ON ROLE … IS
> 'arac:cerveau=<base>;proprietaire=<vous>;empreinte=<empreinte>;secrets=/etc/arac/<base>'`.
> Le champ qui tranche est `empreinte` : un nom se choisit, et deux inconnus choisissent
> le même. Avant la première écriture, l'étape 3 distingue quatre cas : rien ne préexiste
> (elle crée) ; tout porte **notre** empreinte et le coffre est là (réinstallation, elle
> continue) ; tout porte notre empreinte mais le coffre a disparu (**arrêt** : elle ne
> réencode pas un rôle qu'elle n'a pas créé dans la même exécution, et vous rend le geste) ;
> au moins un rôle est à quelqu'un d'autre (**refus net**, avec le propriétaire nommé en
> clair). Aucun `ALTER ROLE … PASSWORD` n'est engendré, nulle part.
>
> **Ce qu'on lisait ici avant août 2026 était vrai à l'époque et est faux aujourd'hui** :
> « vos deux cerveaux partageront les mêmes cinq rôles, sans préfixe, et le second
> bootstrap change les mots de passe du premier ». C'est précisément ce qui a été
> corrigé — les rôles portent maintenant le nom du cerveau. Il n'est plus
> nécessaire de séparer deux cerveaux par deux grappes PostgreSQL — c'est toujours plus
> sûr, ce n'est plus obligatoire. Le geste, quand vous le voulez, est au
> [§12.f](#f-une-grappe-postgresql-pour-ce-cerveau).
>
> **Ce que vous pouvez constater vous-même**, après avoir installé le second : les
> empreintes des rôles du premier n'ont pas bougé.
> ```bash
> sudo -u postgres psql -p "$PGPORT_BASE" -Atc "SELECT rolname, substr(rolpassword,1,25) FROM pg_authid
>                             WHERE rolname LIKE 'arac\_%' ORDER BY 1"
> ```
> Prenez-la avant, prenez-la après, `diff` doit être vide.

### e. Installer ailleurs que dans le dépôt cloné

```bash
sudo ARAC_HOME=/opt/arac ./bootstrap/bootstrap.sh
```

Les unités systemd poseront `ARAC_HOME=/opt/arac` et tout le reste suivra. Assurez-vous
que le code est bien à cet endroit et lisible par les deux comptes de **ce** cerveau —
`arac_<base>` et `aracagent_<base>`, jamais `arac` et `aracagent` tout court (§11).

### f. Une grappe PostgreSQL pour ce cerveau

C'est la variante que le §1 et le §5 annoncent, et la seule qui décide **où** votre
mémoire va vivre. Deux lignes :

```bash
sudo pg_lsclusters                  # les grappes d'ici, et les ports déjà pris
ss -ltn | grep ':<port>'            # doit ne RIEN rendre avant de créer
sudo pg_createcluster 16 <nom> --port <port> --start
sudo ARAC_DB_PORT=<port> ./bootstrap/bootstrap.sh
```

**Nommez la grappe d'après le cerveau**, jamais `arac` tout court : une grappe est globale
à la **machine**, et `pg_dropcluster 16 arac` détruirait celle du voisin — toutes ses
bases, tous ses rôles, d'un seul geste et sans confirmation. Le nom du cerveau dans le nom
de la grappe est ce qui rend ce geste sûr le jour où vous le taperez.

**`ARAC_DB_PORT` est la seule chose qui transmette ce choix.** Ni l'entretien, ni
`config/brain.toml`, ni un drapeau du bootstrap ne le portent. Omise, elle vaut `5432` :
la grappe **par défaut** de la machine. Sur un serveur qui héberge déjà un cerveau, cela
veut dire *sur celui du voisin* — et rien n'échoue, rien n'avertit : la base est créée, les
cinq rôles aussi, et les rôles sont **globaux à la grappe**.

**Vous ne la repasserez plus.** L'étape 3 écrit `ARAC_DB_PORT` dans
`/etc/arac/<votre_base>/arac.env` ; toute exécution ultérieure le **relit** de là, y
compris `sudo ./bootstrap/bootstrap.sh --from services` lancé nu. Et si vous demandez un
autre port que celui retenu, le bootstrap **refuse** avant d'écrire quoi que ce soit :

```
  ✗ REFUS — ce cerveau vit déjà sur un autre serveur PostgreSQL.

     retenu par l'installation   127.0.0.1:<le port de VOTRE grappe>
     demandé maintenant          127.0.0.1:<celui que vous venez de demander>

  Rien n'a été créé, rien n'a été écrit.
```

…et sort en code **6**. Ce n'est pas une rigidité gratuite : déplacer un cerveau d'une
grappe à une autre est une **migration de données** — un dump, une restauration, une
vérification (`SAUVEGARDE.md` §9) —, jamais un réglage d'environnement. Sans ce refus, la
seconde exécution créerait une base neuve et vide sur la grappe demandée, y repointerait
les quatre DSN et les unités, et laisserait votre mémoire sur l'autre serveur, intacte et
injoignable.

> **▸ Contrôle**, avant d'installer, puis après :
> ```bash
> # avant : la simulation doit nommer VOTRE port, deux fois
> sudo ARAC_DB_PORT=<port> ./bootstrap/bootstrap.sh --dry-run \
>   | grep -E 'serveur +127|Ce cluster PostgreSQL'
> # après : c'est le coffre qui fait foi
> sudo grep '^ARAC_DB_PORT=' /etc/arac/<votre_base>/arac.env
> ```
> **Doit répondre** : `serveur 127.0.0.1:<port>` et `Ce cluster PostgreSQL (port <port>)`
> avec **votre** numéro — s'il dit `5432` alors que vous vouliez une grappe à vous, la
> variable n'est pas passée, arrêtez-vous ; puis, après l'installation,
> `ARAC_DB_PORT=<port>`.

**Est-ce obligatoire ?** Non, et ça ne l'est plus depuis que les rôles portent le nom du
cerveau (voir la mise au point du §12.d) : deux cerveaux cohabitent sur une même grappe
sans se détruire. Ça reste **plus sûr** : une grappe dédiée sépare aussi la mémoire
partagée du serveur, ses journaux, et rend le geste « je jette ce cerveau » atomique
(`pg_dropcluster`). Sur une machine qui ne portera jamais qu'un cerveau, la grappe par
défaut convient très bien.

**Et la simulation vous le dit — mais lisez ce qu'elle dit, parce qu'il y a trois cas et
qu'ils ne racontent pas la même chose.** Mesuré sur une grappe de banc, aux trois états :

| ce que `--dry-run` trouve | ce qu'il imprime, sous « Ce cluster PostgreSQL (port …) » |
|---|---|
| **aucun autre cerveau**, le port n'est pas encore retenu | « *aucun autre cerveau ARAC détecté* », puis « *Rien à ménager ici. Sachez tout de même que la voie RECOMMANDÉE pour un second cerveau reste une grappe qui lui est propre* » — **et la recette**, `pg_createcluster` puis `ARAC_DB_PORT` |
| **un ou plusieurs voisins**, le port n'est pas encore retenu | ce qu'il va créer, ce qu'il ne touchera pas, puis en clair : « *⚠ CE CERVEAU VA VIVRE SUR LA MÊME GRAPPE QUE n AUTRE(S). […] c'est le DERNIER moment où le choix est gratuit : après l'étape 3, le port est retenu dans le coffre et ce bootstrap REFUSE (code 6) d'en changer* » — **et la même recette** |
| **le port est déjà retenu** dans `/etc/arac/<base>/arac.env` | « *Ce cerveau a DÉJÀ retenu sa grappe : port n, écrit dans … Le choix est refermé […] Rien à faire ici* » — **et pas de recette** |

**Le troisième cas est le plus instructif, et c'est pour lui que ce tableau existe.** Un
outil qui continuerait à conseiller « donnez-lui sa propre grappe » après l'étape 3
prescrirait un geste que le produit rejette trois écrans plus loin, en code `6`. La
recette est donc imprimée **tant que le choix est ouvert** — et le constat, dès qu'il est
refermé. Si vous ne voyez pas la recette, ce n'est pas un oubli : c'est que vous n'êtes
plus au moment où elle sert.

> *Cette page a écrit « et la simulation le recommande elle-même » alors que le produit ne
> la recommandait que sur une grappe **vide** — c'est-à-dire dans le seul cas où elle ne
> protège rien : dès qu'un voisin était détecté, l'écran passait à un texte rassurant et
> ne disait plus un mot du port. Le code a été corrigé, et cette phrase avec lui. Une page
> qui s'appuie sur ce que le produit imprime doit imprimer ce que le produit imprime.*

**Le jour où vous désinstallerez**, c'est ce numéro qui décide de ce que `dropdb` et
`DROP ROLE` atteignent : le §13 le relit dans le coffre avant tout geste, et son encadré
« Le port, ici comme partout » explique pourquoi une erreur y coûte la mémoire du voisin.

---

## 13. Désinstaller

**— et partir avec sa mémoire, qui est l'autre moitié du même geste.**

Il n'y a pas de script de désinstallation, et c'est délibéré : un outil qui sait
détruire une mémoire est un outil dangereux à livrer. Voici les gestes, dans l'ordre,
à faire à la main. Il existe en revanche un **contrôle** — `ops/uninstall_check.sh` — qui
ne détruit rien, dit ce qui reste, dit *pourquoi* ça reste, et sait imprimer les commandes
manquantes ; c'est l'étape 9.

> **Les sorties reproduites ici sont des relevés.** Elles viennent d'un cerveau de banc —
> `doc14b` — installé par le chemin réel, rempli, sauvegardé, puis désinstallé par cette
> page **mot pour mot**, contrôle de fin compris. Son nom apparaît tel quel dans les
> transcriptions ; le vôtre prendra sa place.

> **Ce chapitre a deux sujets, et le second n'est pas moins important que le premier.**
> Faire disparaître un cerveau de cette machine, oui — mais aussi **repartir avec lui**.
> Les deux gestes se jouent dans le même ordre et avec les mêmes commandes ; ce qui les
> distingue tient en trois lignes, à l'étape 7. Si vous êtes ici pour déménager plutôt que
> pour arrêter, lisez d'abord [`SAUVEGARDE.md` § 9](SAUVEGARDE.md), puis revenez faire ce
> chapitre en entier : un déménagement n'est fini que quand l'ancienne machine ne porte
> plus votre mémoire. Et la lecture qui explique *pourquoi* cette page existe est à la fin,
> sous « Partir — ce que ce chapitre veut vraiment dire ».

> **Ce que l'installation crée, cette page sait maintenant le nommer.** L'étape 4 du
> bootstrap pose une base annexe, `<base>_restore_template`, qui sert de gabarit à la
> vérification de restauration hebdomadaire. Elle n'apparaissait nulle part ici, et son
> existence **bloquait** le `DROP ROLE` de l'étape 5 au milieu du bloc irréversible, sans
> aucun remède imprimé. C'est l'objet de l'étape 4 bis.

> **Avant tout : une désinstallation détruit ce qu'on lui NOMME.** Les rôles PostgreSQL
> sont globaux au **cluster**, pas à la base : `DROP ROLE` ne demande pas de quelle base
> vous parlez. Une procédure de désinstallation qui écrit un nom de rôle en dur détruit
> donc le cerveau du voisin en même temps que le vôtre — et c'est exactement ce que cette
> page faisait avant août 2026. Rien de ce qui suit ne nomme un rôle : tout est **dérivé**
> du nom de votre base, et **contrôlé sur l'empreinte de votre installation** — pas sur ce
> nom, qu'un homonyme partagerait — avant d'être détruit.

**Posez d'abord le nom de votre cerveau — ET SON PORT.** Toutes les commandes en dépendent,
et aucune ne fonctionne si vous les oubliez :

```bash
BASE=<votre_base>          # exactement brain.name de config/brain.toml
PGPORT_BASE=$(sudo sed -n 's/^ARAC_DB_PORT=//p' "/etc/arac/$BASE/arac.env")
echo "cerveau $BASE · cluster PostgreSQL port ${PGPORT_BASE:?introuvable dans /etc/arac/$BASE/arac.env}"
```

> **▸ Le port, ici comme partout — mais ici il est irréversible.** Toutes les commandes
> PostgreSQL de ce manuel portent `-p` (voir le point de contrôle 1 du §1 et le préambule
> du §5) : sans lui, elles visent le cluster **par défaut** de la machine — 5432 — et un
> second cerveau vit très souvent sur son propre cluster (`pg_createcluster 16 <nom>
> --port <port>` puis `sudo ARAC_DB_PORT=<port> ./bootstrap/bootstrap.sh` : c'est le
> [§12.f](#f-une-grappe-postgresql-pour-ce-cerveau), **plus sûr sans être imposé**).
> Ailleurs, viser le mauvais cluster
> vous fait *lire* la mémoire du voisin ; **ici, cela vous la fait détruire.** Sans `-p`,
> le contrôle 0 ci-dessous interroge le cluster du voisin : il ne trouve pas vos rôles, ou
> pire, il en trouve d'autres du même nom — puis l'étape 4 fait tomber un `dropdb` dessus.
> `ARAC_DB_PORT` est écrit en clair dans `/etc/arac/<base>/arac.env` exactement pour ça,
> et `bootstrap/checks/verify_install.sh` le relit de la même façon. Si la commande
> ci-dessus ne rend rien, arrêtez-vous : vous n'avez pas identifié votre installation.

```bash
# 0. VÉRIFIER À QUI SONT LES RÔLES QU'ON VA DÉTRUIRE — ne rien détruire ici
#    Chaque rôle posé par ce bootstrap porte une plaque de propriété : un
#    COMMENT ON ROLE. Le champ qui TRANCHE est `empreinte=` — celle de VOTRE
#    installation est écrite dans votre coffre, à côté du port.
EMPREINTE=$(sudo sed -n 's/^ARAC_INSTALL_UUID=//p' "/etc/arac/$BASE/arac.env")
echo "empreinte de cette installation : ${EMPREINTE:-AUCUNE — lisez le cas 3 ci-dessous}"
#    ▸ NOTEZ-LA SUR UN PAPIER, MAINTENANT. Le contrôle de l'étape 9 vous la
#      redemandera — et à ce moment-là le coffre qui la porte aura été effacé
#      à l'étape 6, et cette variable de shell sera peut-être morte avec votre
#      terminal. Sans elle, ce contrôle retombe sur le NOM SEUL, qui ne prouve
#      rien : deux personnes appellent leur cerveau « perso ». Mesuré, sur une
#      désinstallation menée jusqu'au bout : « empreinte inconnue — ni
#      --empreinte, ni environnement, ni coffre, ni description ».

# a) la liste, pour l'œil : ce que portent les rôles qui commencent par votre nom
sudo -u postgres psql -p "$PGPORT_BASE" -tAc \
  "SELECT rolname, coalesce(shobj_description(oid,'pg_authid'),'AUCUNE PLAQUE')
   FROM pg_roles WHERE rolname LIKE 'arac\_${BASE}\_%' ORDER BY 1"

# b) le même contrôle, mécanique : il n'imprime QUE ce qui n'est pas à vous.
#    Il doit ne RIEN rendre. Toute ligne rendue est un rôle à ne pas détruire.
sudo -u postgres psql -p "$PGPORT_BASE" -tAc \
  "SELECT rolname || '  ->  ' || coalesce(shobj_description(oid,'pg_authid'),'AUCUNE PLAQUE')
     FROM pg_roles
    WHERE rolname LIKE 'arac\_${BASE}\_%'
      AND coalesce(shobj_description(oid,'pg_authid'),'')
          NOT LIKE '%;empreinte=${EMPREINTE};%'
    ORDER BY 1"

# et vérifiez que la base que vous allez détruire est bien SUR ce cluster
sudo -u postgres psql -p "$PGPORT_BASE" -tAc \
  "SELECT datname FROM pg_database WHERE datname = '$BASE'"     # doit rendre $BASE
```

> **▸ Contrôle, et il est bloquant.** La commande **b)** doit ne **rien** rendre, et la
> commande **a)** doit montrer les **cinq** rôles que l'étape 3 crée — `_admin`, `_app`,
> `_agent`, `_readonly`, `_backup` —, chacun portant une plaque de cette forme :
>
> ```
> arac_<votre_base>_admin|arac:cerveau=<votre_base>;proprietaire=<vous>;empreinte=<votre_empreinte>;secrets=/etc/arac/<votre_base>
> ```
>
> **Quatre champs, et un seul fait autorité : `empreinte`.** Les trois autres sont dérivés
> de ce que vous avez tapé à l'entretien : deux personnes qui appellent leur cerveau
> « perso » posent, au caractère près, la même paire `cerveau=` / `secrets=`. C'est
> précisément pourquoi l'empreinte a été ajoutée à la plaque, et pourquoi ce contrôle la
> lit plutôt que le nom — *contrôler un nom sur une page de désinstallation, c'est
> autoriser un `DROP ROLE` sur le cerveau de l'homonyme.* La commande b) le montre : elle
> retient toute ligne dont l'empreinte n'est pas la vôtre, **y compris** une ligne qui
> nomme pourtant votre base et votre coffre.
>
> **Ce que vous faites selon ce que b) rend :**
>
> | ce que b) imprime | ce que cela veut dire | ce qu'on fait |
> |---|---|---|
> | rien | les cinq rôles portent votre empreinte | continuez |
> | une ligne `AUCUNE PLAQUE` | ce rôle n'a pas été posé par ce bootstrap, ou l'a été avant les plaques | **arrêtez-vous** |
> | une ligne avec une **autre** empreinte | un autre cerveau, peut-être homonyme, vit sur cette grappe | **arrêtez-vous** — ce rôle n'est pas à vous |
> | une ligne sans champ `empreinte=` du tout | *cas 3* : plaque d'avant l'empreinte | voir ci-dessous |
>
> **Cas 3 — plaque, ou coffre, sans empreinte.** Si `$EMPREINTE` est vide, ou si des
> plaques s'arrêtent à `arac:cerveau=…;secrets=…`, votre installation est antérieure à
> l'empreinte. Le seul indice qui reste est alors le **nom**, et il ne prouve rien : c'est
> exactement le régime dégradé que `bootstrap/lib/database.sh` traite à voix haute plutôt
> qu'en silence. Ne détruisez ces rôles qu'après avoir constaté, avec
> `ls -d /etc/arac/*/`, qu'aucun **autre** cerveau ne vit sur cette machine.
>
> **Cas 4 — la liste a) est vide.** Votre installation est antérieure au nommage par
> cerveau : ses rôles ne portent pas de préfixe et sont donc **partagés avec tout autre
> cerveau de cette grappe**. Même précaution, et sachez que les détruire coupera l'accès
> de tout cerveau qui les utilise encore.

```bash
# 0 bis. LES DEUX COMPTES SYSTÈME DE CE CERVEAU — relevés MAINTENANT, pendant
#        que les unités existent encore. Ils portent le nom du cerveau
#        (`arac_<base>`, `aracagent_<base>`), mais un nom long est tronqué et
#        suffixé d'une empreinte : on les LIT, on ne les recalcule pas.
U_SERVICE=$(systemctl show "arac-$BASE-api"   -p User --value)
U_AGENT=$(  systemctl show "arac-$BASE-cycle" -p User --value)
echo "comptes de ce cerveau : ${U_SERVICE:?unité introuvable} · ${U_AGENT:?unité introuvable}"

# 1. arrêter et désarmer — seulement les unités de CE cerveau.
#    LES CINQ, pas quatre : le bootstrap arme aussi la restauration
#    hebdomadaire. Oubliée ici, sa minuterie reste `active waiting` après
#    une désinstallation « complète » et se réveillera le dimanche suivant
#    sur un cerveau dont la base et le coffre n'existent plus.
sudo systemctl disable --now "arac-$BASE-api" "arac-$BASE-cockpit" \
                             "arac-$BASE-cycle.timer" "arac-$BASE-sauvegarde.timer" \
                             "arac-$BASE-restauration.timer"

# le contrôle qui le prouve : cette commande ne doit plus rendre AUCUNE ligne
# « active » ni « waiting ».
systemctl list-units --all --no-legend "arac-$BASE-*"

# 2. SAUVEGARDER AVANT DE DÉTRUIRE — vous ne reviendrez pas en arrière.
#    `pg_dump` tourne sous le compte `postgres`, qui n'a AUCUN droit dans votre
#    foyer : lui demander d'y écrire (-f "$HOME/…") rend « Permission denied »,
#    et l'étape 4 détruirait la base sans qu'aucun dump n'existe. On lui fait
#    donc écrire sur sa SORTIE STANDARD, que votre shell redirige où il veut.
ADIEU="$HOME/adieu-$BASE-$(date -u +%Y%m%dT%H%M%SZ).dump"
#    ▸ ET ON LE CRÉE FERMÉ AVANT D'ÉCRIRE DEDANS. La redirection « > » est
#      faite par VOTRE shell, avec VOTRE umask : sans cette ligne le fichier
#      naît en 0644 — mesuré, deux fois : « -rw-r--r-- 1 root root 305467
#      /root/adieu-doc14b-….dump ». C'est le seul dump que cette page vous
#      OBLIGE à prendre, et c'était le seul de toute l'installation à naître
#      lisible par tout le monde : /var/backups/arac/<base> est en 0700 et ses
#      dumps en 0600, et `ops/install_check.sh` le vérifie. Un dump, c'est le
#      cerveau entier en clair.
install -m 600 /dev/null "$ADIEU"
sudo -u postgres pg_dump -p "$PGPORT_BASE" -Fc "$BASE" > "$ADIEU"

# et on VÉRIFIE que le fichier existe, s'ouvre, ET qu'il est fermé aux autres,
# avant de détruire quoi que ce soit
test -s "$ADIEU" && pg_restore --list "$ADIEU" | head -3
echo "adieu écrit : $ADIEU ($(stat -c '%s octets, mode %a' "$ADIEU"))"   # mode 600

# 3. retirer les unités — APRÈS l'étape 1, jamais avant. C'est `disable` qui
#    retire les liens de `*.target.wants/` ; effacer d'abord le fichier
#    d'unité laisse un lien ORPHELIN que systemd rapporte ensuite en
#    « not-found failed ». Le filet, si l'ordre a été inversé :
sudo rm -f /etc/systemd/system/arac-$BASE-*.service /etc/systemd/system/arac-$BASE-*.timer
sudo rm -f /etc/systemd/system/*.target.wants/arac-$BASE-*
sudo systemctl daemon-reload
sudo systemctl reset-failed "arac-$BASE-*" 2>/dev/null || true

# 4. la base (IRRÉVERSIBLE) — sur SON cluster, pas sur celui par défaut
sudo -u postgres dropdb -p "$PGPORT_BASE" "$BASE"

# 4 bis. LES BASES ANNEXES DE CE CERVEAU — sans cette étape, l'étape 5 échoue.
#        TROIS naissances, pas une, et elles ne viennent pas du même endroit :
#          · `<base>_restore_template`      posé par l'étape 4 du BOOTSTRAP,
#                                           POSSÉDÉ par votre rôle d'admin ;
#          · `<base>_restore_<horodatage>`  base jetable d'une vérification de
#                                           restauration interrompue ;
#          · `<base>_avarie_<date>` et `<base>_restauree_<date>`
#                                           nées de la BASCULE — docs/SAUVEGARDE.md
#                                           §7, qui demande expressément de garder
#                                           la première « jusqu'à ce que la nouvelle
#                                           ait fait ses preuves ».
#        Tant que l'une d'elles existe, PostgreSQL REFUSE le DROP ROLE :
#          ERROR: role "arac_<base>_admin" cannot be dropped because some
#          objects depend on it
#          DETAIL: privileges for database <base>_avarie_<date>
#                  owner of database <base>_restore_template
#                  49 objects in database <base>_avarie_<date>
#        NE COMPTEZ PAS LES ROLES QUI TOMBENT, LISEZ LE « DETAIL ». Combien
#        d'entre eux refusent dépend de ce que la base retenue accorde encore :
#        mesuré une fois QUATRE sur cinq, une autre fois LES CINQ, sur la même
#        version du produit. Le DETAIL, lui, NOMME la base qui retient, à
#        chaque fois — et c'est le seul critère qui ne bouge pas.
#        CHACUNE de ces bases contient une COPIE COMPLÈTE de votre mémoire, en
#        clair. Regardez ce qui va tomber AVANT de le faire tomber — et si vous
#        voulez en garder une, sortez-la d'ici plutôt que de sauter l'étape.
ANNEXES="SELECT datname FROM pg_database
          WHERE datname LIKE '${BASE}\_restore\_%'
             OR datname LIKE '${BASE}\_restauree\_%'
             OR datname LIKE '${BASE}\_avarie\_%'
          ORDER BY 1"
sudo -u postgres psql -p "$PGPORT_BASE" -tAc "$ANNEXES"
for d in $(sudo -u postgres psql -p "$PGPORT_BASE" -tAc "$ANNEXES"); do
  sudo -u postgres dropdb -p "$PGPORT_BASE" "$d"
done

# 5. les rôles (IRRÉVERSIBLE — et GLOBAUX AU CLUSTER : relisez le contrôle 0)
#    -p n'est pas un ornement : un rôle appartient à UN cluster. Sans lui,
#    vous détruisez les rôles du cluster par défaut, qui ne sont pas les vôtres.
for f in admin app agent readonly backup; do
  sudo -u postgres psql -p "$PGPORT_BASE" -c "DROP ROLE IF EXISTS arac_${BASE}_$f"
done

# 6. les secrets
sudo rm -rf "/etc/arac/$BASE"

# 7. le reste — un sous-dossier par cerveau, jamais le dossier commun.
#    `<base>-service` est posé par systemd (StateDirectory=) et survit à tout le
#    reste : c'est lui qui empoisonne une réinstallation ultérieure.
sudo rm -rf "/var/log/arac/$BASE" "/var/lib/arac/$BASE" "/var/lib/arac/$BASE-service"

# LES SAUVEGARDES — la seule décision de cette page, et il faut la prendre ICI.
#    `/var/backups/arac/$BASE` contient vos dumps : tout le cerveau, en clair si
#    vous n'aviez pas déposé de destinataire age. Deux issues, pas trois — et
#    « AILLEURS » veut dire une AUTRE MACHINE, jamais un autre répertoire de
#    celle-ci. Cette page a longtemps proposé « mv … "$HOME/dumps-…" » : mesuré,
#    le §13 suivi mot pour mot laissait alors QUATRE copies complètes et
#    lisibles de la mémoire sous /root, et le contrôle de l'époque disait
#    « PROPRE ». Déplacer n'est pas sortir.
#
#      · (a) VOUS LES GARDEZ. Trois temps, dans cet ordre, et le troisième ne
#        se joue qu'après le deuxième :
#           1. une empreinte, écrite À CÔTÉ des dumps, AVANT le départ ;
#           2. le transfert — rien n'est écrit sur la machine qu'on nettoie,
#              et le canal est chiffré ;
#           3. la vérification À L'ARRIVÉE, chez vous. Et alors seulement,
#              l'effacement ici.
#      · (b) VOUS NE LES GARDEZ PAS — alors dites-le, une fois, en clair.
#
#    Le contrôle de l'étape 9 compte toute copie de votre mémoire comme un
#    RESTE tant qu'elle est là, et il a raison de le faire. Choisissez :

# --- (a) GARDER : sortir, vérifier, PUIS effacer d'ici -----------------------
#   L'empreinte se prend en noms RELATIFS, et ce n'est pas un détail de style :
#   un SHA256SUMS qui porte « /var/backups/arac/<base>/… » fait vérifier, chez
#   vous, les fichiers restés ICI tant qu'ils existent encore. Le contrôle
#   rendrait « OK » sans avoir regardé une seule fois votre copie.
sudo sh -c 'cd "/var/backups/arac/'"$BASE"'" && sha256sum ./*.dump > SHA256SUMS'
sudo tar -cf - -C "/var/backups/arac/$BASE" . \
  | ssh <votre-poste> "mkdir -p 'dumps-$BASE' && tar -xf - -C 'dumps-$BASE'"
#   CHEZ VOUS, et seulement là :
#       cd dumps-<base> && sha256sum -c SHA256SUMS
#   Chaque ligne doit rendre « : OK ». Et alors seulement, ici :
sudo rm -rf "/var/backups/arac/$BASE"
#   ▸ N'OUBLIEZ PAS L'ADIEU DE L'ÉTAPE 2. Il est dans votre foyer, pas dans
#     /var/backups : c'est une copie complète de plus, et le contrôle de
#     l'étape 9 la nomme. Emportez-le de la même façon, puis :
#       rm -f "$ADIEU"
#   ▸ ET LA DESCRIPTION, si vous comptez rouvrir ce cerveau ailleurs : sans
#     `config/brain.toml`, la machine d'arrivée fabrique une empreinte neuve et
#     votre propre dump cesse d'être reconnu comme le vôtre. Voir
#     docs/SAUVEGARDE.md § 9. Emportez `config/brain.toml` et
#     `config/scopes.toml` AVANT l'étape suivante.

# --- (b) DÉTRUIRE : une ligne, et on l'écrit ---------------------------------
# sudo rm -rf "/var/backups/arac/$BASE" && rm -f "$ADIEU"

# la description de ce cerveau, restée dans votre clone — ET LES DEUX FICHIERS
# QU'ELLE ENGENDRE. Le §13 ne les a longtemps pas nommés ; le contrôle de
# l'étape 9, si — et il avait raison, ce qui suffisait à lui faire rendre
# « 2 RESTE(S) » et le code 1 à qui suivait cette liste mot pour mot. Aucun ne
# contient de souvenir, mais `brain.toml` porte votre empreinte et le nom de
# votre poste, et les trois autres portent vos domaines EN CLAIR — c'est la
# forme de votre mémoire. Git ne suit ni l'énumération ni le seed : effacer la
# source ne les efface pas.
rm -f config/brain.toml config/scopes.toml
rm -f app/schemas/scope_generated.py db/seeds/scopes.sql
rm -f ".bootstrap-install.$BASE.state"

# la ligne tmpfiles.d, si vous aviez armé les gabarits d'`ops/systemd/` (§11).
# Elle RECRÉE le répertoire de sauvegarde à chaque démarrage : sans ce geste,
# /var/backups/arac/<base> repousse tout seul après la désinstallation.
sudo rm -f "/etc/tmpfiles.d/arac-$BASE-backup.conf"

# les estampilles de minuteur : systemd s'en sert pour rattraper un
# déclenchement manqué (`Persistent=true`). Elles survivent au retrait des
# unités, et sans ce geste une réinstallation homonyme repart avec l'horloge
# du cerveau précédent — et déclenche une sauvegarde ou une restauration
# « en retard » dès son premier démarrage.
sudo rm -f /var/lib/systemd/timers/stamp-arac-$BASE-*.timer

# et si vous aviez posé ARAC_ETAT ailleurs que par défaut, le fichier
# d'avancement du bootstrap est là aussi : le contrôle de l'étape 9 le nomme.

# 8. les deux comptes système de CE cerveau, relevés au 0 bis
sudo userdel "$U_AGENT"
sudo userdel "$U_SERVICE"

# 9. LE CONTRÔLE DE FIN — une désinstallation qui ne se vérifie pas n'en est pas une.
#    Il doit rendre « VERDICT : PROPRE » et le code 0. « PROPRE » a un sens
#    littéral, et il est BORNÉ : « rien de ce cerveau AUX ENDROITS CI-DESSUS,
#    dumps compris » — et le rapport imprime la liste de ces endroits, grappes
#    et racines, sous « CE QUI A ÉTÉ REGARDÉ ». Un verdict ne vaut jamais plus
#    que son périmètre, et celui-ci le dit lui-même.
#
#    IL NE JUGE PLUS SUR LES NOMS. Il ouvre chaque base et lit le commentaire
#    de son schéma ; il lit les premiers octets de chaque fichier et, quand
#    c'est une archive `pg_dump`, demande à `pg_restore --schema-only` ce que
#    ce fichier DÉCLARE. C'est ainsi qu'une base au nom quelconque est
#    reconnue pour ce qu'elle est, et qu'un cerveau VOISIN portant exactement
#    votre nom est reconnu pour ce qu'il est : celui de quelqu'un d'autre,
#    pour lequel il n'imprimera aucun geste destructeur.
#
#    C'EST L'EMPREINTE QUI TRANCHE — celle du contrôle 0, celle que vous avez
#    notée. Sans elle il fouille quand même, mais il ne peut plus distinguer
#    deux homonymes, il le DIT, et il n'imprime aucun geste destructeur.
EMPREINTE="${EMPREINTE:-<celle que vous avez notée au contrôle 0>}"
sudo ops/uninstall_check.sh "$BASE" --port "$PGPORT_BASE" --empreinte "$EMPREINTE"

#    Ce qu'il compte, et que les étapes précédentes fabriquent elles-mêmes :
#    l'adieu de l'étape 2, tout dossier de dumps que vous auriez seulement
#    DÉPLACÉ, la ligne /etc/tmpfiles.d/arac-<base>-backup.conf, la description
#    restée dans votre clone, les drop-in `systemctl edit`, les bases annexes,
#    les rôles (et, pour chacun, ce qui le retient), les unités, les
#    estampilles, le coffre, les dossiers, les comptes — ET le journal système
#    (sa section 7), le seul endroit qu'aucun geste de cette page ne peut
#    nettoyer : voir « Le journal système » plus bas.
#
#    Deux options quand le verdict vous surprend :
#      --fouiller <dir>   ajouter un endroit aux racines regardées
#      --empreinte <uuid> lever toute ambiguïté avec un cerveau homonyme
#
#    S'il reste quelque chose, `--gestes` imprime les commandes manquantes DANS
#    L'ORDRE OÙ ELLES PASSENT — les bases avant les rôles, parce qu'un rôle qui
#    possède encore une base ne se détruit pas. Il n'exécute rien à votre place :
#    les rôles sont globaux à la grappe, et une erreur de nom coûte la mémoire
#    du voisin. Lisez-les, puis passez-les.
sudo ops/uninstall_check.sh "$BASE" --port "$PGPORT_BASE" --empreinte "$EMPREINTE" --gestes
```

> **▸ Ce que le contrôle a réellement rendu, joué de bout en bout.** §13 suivi mot pour
> mot sur un cerveau installé par le chemin réel, branche (a) telle qu'elle était écrite
> avant cette version — c'est-à-dire un simple `mv` vers le foyer :
>
> ```
> 2. Copies de la mémoire hors base (dumps)
>   ✗ copie complète de la mémoire : « /root/adieu-doc14b-….dump » (305467 octets, mode 644)
>       ↳ reconnue à l'empreinte qui voyage DANS le fichier, pas à son nom :
>         « COMMENT ON SCHEMA arac IS 'ARAC cerveau=doc14b empreinte=ec04294a… poste=…' »
>   ✗ copie complète de la mémoire : « /root/dumps-doc14b-conserves/doc14b-….dump » ×2
> VERDICT : 3 RESTE(S).                                                              rc=1
> ```
>
> Puis les dumps sortis pour de bon, vérifiés à l'arrivée (`sha256sum -c` → trois `OK`) et
> effacés d'ici :
>
> ```
> VERDICT : PROPRE — rien de ce cerveau aux endroits ci-dessus, dumps compris.       rc=0
>   grappes  : 5540
>   racines  : /var/backups/arac/ /var/tmp/ /tmp/ <votre clone> <votre foyer>
> ```
>
> **`/tmp` et `/var/tmp` sont dans les racines regardées** : une copie « de passage » posée
> là pour la durée du transfert est comptée comme un reste, et c'est exactement ce qu'elle
> est. Vérifié en la déplaçant hors de ces racines : le verdict passe de « 3 RESTE(S) » à
> « PROPRE ».

### Le journal système — ce que ce chapitre ne peut pas effacer, et pourquoi

**C'est l'endroit où personne ne pense à chercher sa mémoire, et il faut le savoir avant
de rendre un serveur.** Tout ce qu'impriment les unités `arac-<votre_base>-*` part dans
**journald**, un magasin **commun à la machine entière** : lisible par root et par tout
compte du groupe `systemd-journal`, conservé des semaines, et **hors de portée de tous les
gestes ci-dessus**. Le §13 efface la base, les rôles, le coffre, les dossiers, les dumps
et `/var/log/arac/<base>/` — il ne peut rien contre journald.

**Ce que le produit y écrit aujourd'hui, et il faut le lire en entier avant d'installer.**
Trois choses, et la troisième est celle à laquelle on ne pense pas — c'est le cerveau qui
écrit tout seul, plusieurs fois par jour, sans que personne lance quoi que ce soit.

1. **Des comptes, des durées, des verdicts, des noms d'unités.** Rien de votre mémoire.
2. **Pour l'échantillon d'atomes de `ops/restore_verify.sh` : des empreintes** (`sha256`
   tronqué à huit caractères) de la clé et du domaine, la date, et la longueur décodée —
   *« clé 46dcc5e9  domaine 9deb5bdc  2026-08-10  (12 + 65 caractères décodés) »*. Deux
   passages sur le même dump rendent les mêmes empreintes, ce qui suffit à reconnaître un
   dump ; aucune ne rend un mot de votre mémoire. Cette ligne-là a été corrigée : elle
   portait la clé et le domaine **en clair** (voir l'encadré ci-dessous).
3. **Et — c'est le point qu'il faut connaître — le contexte des avertissements
   d'écriture, lui aussi en empreintes.** Chaque fois qu'un souvenir est écrit avec un
   avertissement, l'API émet une ligne `create_atom.warnings` (ou
   `supersede_atom.warnings`). Elle porte le **code** de l'avertissement, sa **sévérité**,
   l'`atom_id` — un UUID tiré par la base, qui ne porte aucun mot —, les **nombres** du
   contexte (longueurs, seuils, comptes) et les **noms de champs**. Tout ce qui est du
   **texte** — le domaine, les étiquettes, la clé, et le `rationale` — y devient
   `sha8:<empreinte>/<n caractères>` avant d'atteindre journald. C'est
   [`app/journal.py`](../app/journal.py) qui le décide, **fermé par défaut** : ce qui
   sort en clair doit se *démontrer* inoffensif, on n'entretient pas la liste de ce qui
   serait sensible. **La digestion écrit par cette route, trois fois par jour, toute
   seule** — c'est pour cela qu'elle a été fermée à la source plutôt que réglée.

   ```
   arac-<base>-api[…]: {"message": "create_atom.warnings", "event": "warnings",
     "atom_id": "<UUID de la base>", "warning_count": 3,
     "detail_en_base": "arac.audit_log (action='warning')",
     "warnings": [{"code": "W-003", "severity": "info",
                   "context": {"length": 53, "target_min": 200,
                               "preview": "sha8:70b110c6/53"}},
                  {"code": "W-007", "severity": "info",
                   "context": {"scope": "sha8:cf35fd0b/11", …}}]}
   ```

   **Le texte, lui, est en base — et il part avec le cerveau.** C'est
   `arac.audit_log.warning_context`, sous les rôles de votre cerveau, que le geste 4
   du §13 détruit avec la base. Pour le lire pendant que le cerveau vit :

   ```bash
   sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" \
     -Atc "SELECT warning_code, warning_context FROM arac.audit_log
             WHERE action='warning' ORDER BY created_at DESC LIMIT 5"
   ```

   **Ce que ces lignes disent quand même, et c'est ce qui compte pour un serveur
   partagé :** la **forme** de votre mémoire — combien d'atomes, à quel rythme, quand,
   quels avertissements, et quelles empreintes se répètent. L'empreinte est stable, donc
   « ces quarante lignes portent le même `sha8:cf35fd0b` » reste lisible : on ne lit pas
   votre domaine, on voit qu'il y en a un et qu'il revient. Ces lignes ne s'effacent pas
   plus que les autres.

**Ce qu'il faut en conclure avant d'installer, et c'est la vraie règle :** ce que le
produit écrit dans le journal, il faut qu'il puisse **y rester**. Une donnée qu'on n'écrit
pas est une donnée qu'on n'a pas à effacer — et comme rien ici ne sait effacer une seule
unité (voir plus bas), c'est la seule protection qui tienne. Si votre serveur est partagé,
ou si vous comptez le rendre, sachez que **tout compte du groupe `systemd-journal` peut
lire ces lignes**, y compris celles-là, et que le §13 n'y peut rien.

> **Si votre cerveau a été installé avant cette version, lisez ceci avant de partir.**
> `ops/restore_verify.sh` imprimait alors la **clé** et le **domaine** de trois souvenirs
> **en clair**, sous « *échantillon d'atomes réellement relus :* ». Ce script est
> l'`ExecStart` d'`arac-<base>-restauration.service` — l'unité que le bootstrap arme
> lui-même (dimanche 03:00) et que le § 7 de [`SAUVEGARDE.md`](SAUVEGARDE.md) fait lancer
> à la main. Un §13 joué mot pour mot, un « VERDICT : PROPRE » en code 0, et ces lignes
> étaient encore là. Pour voir ce que le vôtre en garde :
>
> ```bash
> sudo journalctl -u "arac-$BASE-restauration.service" --no-pager \
>   | grep -A4 "échantillon d'atomes"
> ```
>
> **L'étape 9 le regarde pour vous** (section 7 de son rapport) : elle compte les lignes
> des unités `arac-<base>-*`, dit depuis quand, et cherche nommément **cette
> signature-là**. Elle prononce « il reste » — pas « propre » — quand elle la trouve.
>
> **Et voici sa limite, qui reste vraie quand bien même elle a désormais raison.** Elle
> cherche **une signature** — celle de la fuite d'avant —, pas la **forme** de toutes les
> fuites possibles. Elle ne peut donc rien promettre pour un défaut que personne n'a
> encore écrit. C'est une borne de méthode, pas un reproche : lisez sa ligne verte pour
> ce qu'elle dit — *cette signature-ci est absente* —, jamais comme « le journal ne porte
> rien de moi ».
>
> **Ce que la mesure a rendu, le 10 août 2026.** Un cerveau de banc né du chemin réel,
> deux souvenirs écrits par la vraie route `POST /v1/atoms` puis une supersédure, avec
> des mots que personne d'autre n'avait écrits — puis ce §13 joué mot pour mot jusqu'au
> « VERDICT : PROPRE » en code 0. Seize motifs cherchés ensuite dans le journal des cinq
> unités — les valeurs, les *pourquoi*, les étiquettes, les clés, les deux domaines, et
> trois mots du texte lui-même : **aucun trouvé**. La ligne verte disait donc vrai sur ce
> cas-là, et le point 3 ci-dessus dit pourquoi : le texte est empreinté avant d'atteindre
> journald.
>
> **Ne me croyez pas sur parole : la seule mesure qui vaille est la vôtre**, et c'est le
> même geste, sur vos mots à vous. Le critère est *rien*, pas *un compte* :
>
> ```bash
> # rc=1 et aucune ligne = ce mot n'est nulle part dans le journal de ce cerveau.
> sudo journalctl -u "arac-$BASE-api.service" --no-pager | grep -i "<un mot à vous>"
> ```

**Et elle ne prescrit aucun geste, délibérément.** systemd ne sait pas effacer les entrées
d'**une** unité : `journalctl --vacuum-size`, `--vacuum-time` et `--vacuum-files`
travaillent sur des **fichiers** de journal, et un fichier de journal porte tout ce que la
machine a écrit pendant sa période — les autres services, et le cerveau du voisin. Il n'y
a donc pas de purge bornée à votre cerveau. Deux issues, et ce sont les vôtres à
trancher :

- **attendre.** Ces lignes partent avec la rotation du journal, à la date que fixent
  `SystemMaxUse` et `MaxRetentionSec` (`man journald.conf` dit aussi où les poser). Si
  vous gardez la machine, c'est la réponse.
- **tout vider,** et seulement si ce serveur ne porte que ce cerveau et que vous le
  rendez : `sudo journalctl --rotate && sudo journalctl --vacuum-time=1s`. **Cette
  commande vide le journal de TOUTE la machine** — elle n'est pas bornée à ARAC, et elle
  emporte le journal de tout ce qui tourne ici. Elle ne figure pas dans la liste ordonnée
  du §13 pour cette raison exacte.

**La leçon, et elle vaut au-delà de journald :** une donnée qu'on n'écrit pas est une
donnée qu'on n'a pas à effacer. C'est pourquoi la correction porte sur ce que le produit
imprime, et pas seulement sur ce que la désinstallation nettoie.

**Les étapes 7 et 8 ne suppriment que ce qui porte le nom de votre cerveau, et c'est la
précaution qui compte.** `/var/log/arac/`, `/var/lib/arac/` et `/var/backups/arac/` sont
**communs à tous les cerveaux** de la machine ; seul le sous-dossier qui porte le nom du
vôtre est à vous. Effacer un de ces trois dossiers en entier détruit les journaux, l'état
et — le pire — les sauvegardes du voisin, silencieusement. De même, `userdel arac` (sans
suffixe) détruirait le compte d'un cerveau installé avant que ce nommage n'existe.

L'étape 2 n'est pas décorative. Un cerveau qu'on détruit sans dump est un cerveau perdu,
et ce qu'il contenait avait coûté des mois de conversations et une facture d'API. C'est
aussi pourquoi elle **vérifie** son propre résultat : un `pg_dump` qui échoue laisse un
fichier vide ou pas de fichier du tout, et rien dans les étapes suivantes ne s'en
apercevrait.

**Les comptes système sont détruits parce qu'ils appartiennent à ce cerveau, et à lui
seul.** Ils ont longtemps valu `arac` et `aracagent` pour tout le monde — c'était le
dernier identifiant partagé du produit, et il annulait tout le reste : deux services sous
le même UID lisent le `/proc/<pid>/environ` l'un de l'autre, mots de passe compris. Ils
portent désormais le nom du cerveau, donc ils se désinstallent avec lui. **Si le `User=`
relevé au 0 bis est `arac` ou `aracagent` sans suffixe**, votre installation est antérieure
à ce nommage : ce compte est alors **commun à toute la machine**, et le supprimer couperait
les services de tout cerveau qui l'utilise encore. La question à trancher avant l'étape 8
n'est pas « quel nom porte-t-il ? » mais « **quelqu'un s'en sert-il encore ?** », et elle a
une réponse mécanique — l'étape 1 ayant déjà arrêté vos propres unités :

```bash
ps -u "$U_SERVICE" -o pid,cmd --no-headers    # doit ne RIEN rendre
ps -u "$U_AGENT"   -o pid,cmd --no-headers    # doit ne RIEN rendre
```

Si l'une des deux rend une ligne, ce compte sert encore : ne le supprimez pas.

**Ce que cette procédure ne touche pas, volontairement** : le venv du dépôt, le **cluster**
PostgreSQL, le **journal système** (ci-dessus — elle ne le *peut* pas, et l'étape 9 dit ce
qu'il en reste), et le côté Mac.

Le cluster reste debout parce qu'il peut porter d'autres cerveaux. S'il a été créé **pour
celui-ci et pour lui seul** — c'est-à-dire par le
[§12.f](#f-une-grappe-postgresql-pour-ce-cerveau) —, et seulement dans ce cas, c'est un
geste séparé, à faire en connaissance de cause :

```bash
sudo -u postgres psql -p "$PGPORT_BASE" -tAc \
  "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres'"
# s'il ne reste RIEN, et seulement alors :
sudo pg_dropcluster 16 <nom_du_cluster> --stop        # IRRÉVERSIBLE
```

Sur le Mac, `arac-pont.sh desinstaller` retire les agents launchd de **ce** cerveau et
**ne touche à aucune donnée** : le dossier `~/.arac/<votre_base>/` — jeton, journal,
curseur de synchronisation — reste à vous de supprimer, en sachant qu'il porte le curseur
et que le perdre fait tout renvoyer. Si ce poste pilote plusieurs cerveaux, nommez celui
que vous retirez, sans quoi la commande refuse et rend `2` :

```bash
ARAC_CERVEAU=<votre_base> ./arac-pont.sh desinstaller
```

### Partir — ce que ce chapitre veut vraiment dire

Cette page enseigne à s'installer sur cent lignes et à partir sur dix ; c'est le mauvais
sens, et il faut le corriger ici plutôt que le laisser deviner.

**On ne désinstalle pas un cerveau par curiosité.** On le fait quand on rend le serveur,
quand on le vend, quand on le confie, quand on déménage. Ce jour-là, une seule question
compte, et elle a deux moitiés qui ne se remplacent pas l'une l'autre :

1. **Est-ce que je repars avec ma mémoire ?** Elle a coûté des mois de conversations et
   une facture d'API ; elle ne se rachète pas, elle se **repaie**. C'est l'étape 2, et
   c'est la branche (a) de l'étape 7 — avec, si vous comptez rouvrir ce cerveau ailleurs,
   les deux fichiers de `config/` qui portent son identité et sa forme
   ([`SAUVEGARDE.md` § 9](SAUVEGARDE.md)).
2. **Est-ce qu'il en reste ici ?** Un dump se restaure : tant qu'il est là, votre mémoire
   est là — sur une machine dont vous venez de retirer tout ce qui la protégeait, le
   coffre, les rôles, les unités. C'est l'étape 9, et c'est pour cela qu'elle ne se
   contente pas de compter des services.

**Ces deux moitiés sont la même promesse, prise par les deux bouts.** Un produit qui garde
votre mémoire prisonnière ne vous appartient pas ; un produit qui la laisse traîner
derrière vous ne vous protège pas. Le premier vous empêche de partir, le second vous
empêche de partir *proprement* — et les deux reviennent à dire que ce cerveau n'était pas
tout à fait le vôtre.

C'est aussi pourquoi il n'y a **pas** de `make uninstall`. Les gestes sont écrits, ils sont
lisibles, et vous les passez un par un. Le seul automatisme de ce chapitre est celui qui ne
détruit rien : le contrôle, qui répond à la seconde question et refuse de dire « propre »
tant que la réponse est non.

---

## Ce qui a été réellement exécuté pour écrire ce document

**Vérifié** sur Ubuntu, Python 3.12, PostgreSQL 16.13 + pgvector 0.8.2 : `make test`
(aucun échec ; **la durée dépend de la machine et n'est écrite nulle part comme un
critère**) · `make doctor`, sur un clone vierge **et** après `make test`, les deux sorties
comparées à ce que le §2 en dit · `make venv` (équivalent testé dans un répertoire jetable,
avec réseau) · `bootstrap.sh --check`, `--etapes`, `--help`, `--dry-run` complet ·
`bootstrap/checks/verify_install.sh` et son `--simulation` ·
`bootstrap/generate_scopes.py` · `wizard.py --help` et `--check` · `sudo
ops/install_check.sh` (sans `sudo`, il ne peut pas lire le coffre : voir
[`DEPANNAGE.md`](DEPANNAGE.md)) · `ops/backup_toc_check.sh selftest` ·
`ops/restore_guard.sh selftest` · les requêtes `psql` de contrôle des extensions
disponibles · le script de pont du §6, y compris son idempotence.

**Exécuté en réel, deux fois, avec deux taxonomies différentes** : `sudo
./bootstrap/bootstrap.sh` de bout en bout — `CREATE DATABASE`, `CREATE ROLE`,
`CREATE EXTENSION vector`, `alembic upgrade head`, le seed des domaines, la génération
des secrets, `systemctl enable --now`, et les points de contrôle qui interrogent une base
installée. Les deux installations rendent le **même schéma** — `pg_dump --schema-only`
identique **une fois l'identité de chaque installation neutralisée des deux côtés** : le
bootstrap grave `cerveau=`, `empreinte=` et `poste=` dans le commentaire du schéma, et
`pg_dump` les emporte exprès, pour qu'un dump sache dire de quel cerveau il vient. La
commande qui le prouve, en deux temps — le schéma identique, puis l'identité qui diffère —,
est au §7c du [`README`](../README.md#c-ce-qui-est-éprouvé-sur-quoi-et-ce-qui-nest-pas).

**Les saisies interactives ont été jouées, le 9 août 2026, derrière un vrai terminal.**
`bootstrap.sh --only secrets` lancé sous un pseudo-terminal : le mot de passe
administrateur a été **tapé deux fois** aux invites `getpass` (« Mot de passe
administrateur du cockpit : », « Répétez-le : »), haché en PBKDF2-SHA256 / 260 000
itérations ; l'URI `otpauth://totp/<cerveau>:<propriétaire>?secret=…` s'est affichée **une
seule fois**, suivie de « Appairage effectué ? (O/n) » — **sans qu'aucun code à six
chiffres ne soit demandé ni vérifié**, exactement comme l'avertit le §5. Et le mot de passe
tapé **ouvre réellement le cockpit** : `POST /cc/login` avec ce mot de passe et un code
calculé depuis le secret appairé rend `303 See Other` vers `/cc/` et pose la session ; `GET
/cc/` et `GET /cc/v1/atoms` rendent alors `200`, et un mot de passe faux rend `401`.
*(Ce qui n'a pas été rejoué à la main, c'est l'installation **complète** en interactif de
bout en bout : seule l'étape des secrets l'a été.)*

**Éprouvé depuis, sur des cerveaux réels — et rejouable chez vous.**

- **La RESTAURATION d'une sauvegarde**, et pas seulement le dump. `ops/restore_verify.sh`
  recharge le dump dans une base jetable et compare : *« VERDICT : PROUVÉ — ce dump se
  restaure, et le cerveau en sort entier. »* Le bootstrap arme cette vérification
  lui-même (`arac-<base>-restauration.timer`, dimanche 03:00), et `make acceptance` la
  rejoue à chaque passage, à son étape 8.
- **La BASCULE du §7 de [`SAUVEGARDE.md`](SAUVEGARDE.md)** — sur un cerveau **cassé pour
  de vrai** (`DROP DATABASE`, `DROP SCHEMA … CASCADE`) : restauration dans une base
  neuve, renommage, `bootstrap.sh --only migrations`, et les souvenirs relus **sous le
  rôle de l'application**. Étape 8 de `make acceptance`, et rejouée à la main le 9 août
  2026 sur un cerveau né du chemin réel.
- **Les gestes de désinstallation du §13**, joués mot pour mot — contrôle 0 et 0 bis,
  étapes 1 à 9, jusqu'au `VERDICT : PROPRE` en code 0 rendu par `ops/uninstall_check.sh`,
  **en une seule passe**. Étape 9 de `make acceptance`.
  *Cette phrase a été fausse une version durant, et la raison mérite d'être dite : la
  liste ordonnée n'effaçait pas `app/schemas/scope_generated.py` ni `db/seeds/scopes.sql`
  — engendrés depuis votre taxonomie, porteurs de vos domaines en clair, non suivis par
  git — que le contrôle de l'étape 9 comptait, à juste titre, comme des restes. Qui
  suivait la page mot pour mot obtenait donc « 2 RESTE(S) » et le code 1, là où on lui
  promettait « PROPRE » et le code 0 ; le juge du dépôt le signalait à chaque passage, et
  personne ne le levait. L'étape 7 les nomme désormais.*
- **La variante [§12.f](#f-une-grappe-postgresql-pour-ce-cerveau)** — cerveau installé sur
  une grappe dédiée par `ARAC_DB_PORT`, port relu ensuite depuis le coffre, et **refus en
  code 6** quand on en demande un autre.

**Toujours non vérifié** : le rejeu depuis un Ubuntu **nu** (la machine d'essai portait
déjà PostgreSQL et pgvector) · le chemin *installation neuve → première conversation →
premier atome*, qu'aucun cerveau posé par ce bootstrap n'a parcouru, faute de ce que la
digestion réclame (le binaire de curation, son authentification, et les deux interrupteurs
de dépense) · le **tunnel SSH depuis un vrai Mac**, `launchd`, et la
capture réelle de Claude Desktop (voir [`PONT-MAC.md`](PONT-MAC.md)) · les variantes
**(a), (b), (c) et (e)** du §12 · le chemin **chiffré** du §7 étape 2 (`age -d`) et la
copie **hors site**, qui demandent une clé et une seconde machine.

> **Pourquoi ce paragraphe a été réécrit, et ce que ça enseigne.** Il déclarait « toujours
> non vérifié » la restauration et le §13 — dans un dépôt dont le juge les prouve à chaque
> passage. Une section d'honnêteté périmée ne rassure pas : elle **retire de la valeur au
> reste**, parce qu'elle est le seul endroit dont toute l'utilité tient à ce qu'il soit
> exactement vrai. Sous-estimer trompe autant que surestimer, et se lit au pire moment —
> par quelqu'un qui vient de perdre sa base, ou qui s'apprête à rendre son serveur.

*(Sur le cerveau de **référence**, qui n'a pas été posé par ce bootstrap, l'ingestion, les
embeddings, l'extraction et le rappel tournent et laissent un reçu de cycle citable. La
distinction entre les deux objets est tenue au §7c du [`README`](../README.md) — ne la
confondez pas, c'est ce qui avait rendu ce paragraphe faux.)*

C'est l'assertion **F4** de [`GOAL.md`](../GOAL.md) : sa moitié « reproductible » est
tenue, sa moitié « depuis un Ubuntu nu » ne l'est pas. Si vous êtes la première personne
à parcourir ce chemin sur une machine neuve, **notez chaque friction**.
