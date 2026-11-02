# `bootstrap/` — donner corps à un cerveau

Ce dossier contient les trois outils qui font naître un cerveau ARAC, dans
l'ordre où on les rencontre :

| Fichier | Rôle | Écrit-il quelque chose ? |
|---|---|---|
| `wizard.py` | L'entretien. Cinq questions, cinq minutes. Il vous fait décider de la forme de votre mémoire. | `config/brain.toml` et `config/scopes.toml`, et rien d'autre. |
| `generate_scopes.py` | Traduit votre taxonomie en énumération Python et en SQL. Refuse les taxonomies qui feraient perdre du savoir. | `app/schemas/scope_generated.py`, `db/seeds/scopes.sql`. Jamais la base. |
| `bootstrap.sh` | L'installation. Base, rôles, vecteurs, migrations, taxonomie, secrets, clés, services, contrôle. | La base, `/etc/arac/<votre-base>/`, `/etc/systemd/system/`. |
| `checks/verify_install.sh` | Le contrôle a posteriori. « Ce cerveau est-il toujours sain ? » | **Rien.** Il lit, il compte, il dit. |

La séparation est volontaire : **décider et exécuter ne sont pas le même
geste.** L'entretien produit une *description* de votre cerveau ; le bootstrap
lui donne corps, en annonçant ce qu'il s'apprête à faire avant de le faire.

---

## En trois commandes

```bash
python3 bootstrap/wizard.py            # décider (5 min, n'installe rien)
./bootstrap/bootstrap.sh --dry-run     # voir ce qui va se passer (n'écrit rien)
sudo ./bootstrap/bootstrap.sh          # installer
```

Puis, plus tard, aussi souvent que vous voulez :

```bash
./bootstrap/checks/verify_install.sh   # ce cerveau est-il sain ?
```

---

## Ce qu'il faut savoir AVANT de lancer quoi que ce soit

Rien de ce qui suit n'est en annexe. Si l'un de ces points est rédhibitoire
pour vous, mieux vaut le savoir maintenant.

### 1. Il faut un serveur, pas un ordinateur portable

Ubuntu (ou Debian), PostgreSQL 16 avec pgvector, **Python ≥ 3.12**, systemd,
`git`, `ssh`, `sudo`, `openssl`. Le bootstrap constate tout cela à l'étape 1 et
vous donne la commande exacte pour chaque pièce manquante — **il n'installe rien
sans votre accord.**

> **Et une onzième pièce, qui décide si le cerveau APPREND** : le binaire
> `claude` (Claude Code CLI), sur ce serveur. Le cycle de digestion n'appelle
> aucune API — il **lance ce binaire** en sous-processus, sous le compte d'agent
> du cerveau. L'étape 1 le constate désormais, dans sa propre section, et le
> contrôle final le revérifie **sous le dossier personnel du compte d'agent**.
> C'est le **seul prérequis qui n'arrête pas l'installation** : sans lui le
> cerveau naît, ingère et se laisse interroger — il n'apprend simplement jamais
> rien de neuf.
>
> ```bash
> sudo npm install -g @anthropic-ai/claude-code
> # si le binaire n'atterrit pas dans le PATH du service (nvm, préfixe npm
> # utilisateur…), nommez-le au lieu de le déplacer :
> #   ARAC_CLAUDE_BIN=/chemin/absolu/vers/claude   dans /etc/arac/<base>/arac.env
> ```
>
> Ce que le bootstrap ne vérifie **pas** : que `npm` existe pour poser ce
> binaire, et l'espace disque.

> **Attention au 3.11.** L'étape 1 se contente de Python ≥ 3.11, parce que
> `tomllib` — de quoi lire votre taxonomie — y est apparu. Mais `pyproject.toml`
> exige `>=3.12`, et l'installation des dépendances échouera à l'étape 5. Si
> vous êtes sur une Ubuntu 22.04 (Python 3.10/3.11), réglez la question
> **maintenant** : un prérequis qui passe au vert puis casse trois étapes plus
> loin est le contraire d'une installation réparable.

```bash
sudo apt install postgresql-16 postgresql-16-pgvector postgresql-client-16 \
                 python3 python3-venv python3-pip git openssh-client
sudo systemctl enable --now postgresql
```

### 2. Ça coûte de l'argent, tous les mois

Deux fonctions se paient, sans lesquelles le cerveau est amputé — **mais pas
de la même façon**, et l'étape 8 le dit avant de rien vous demander :

| Fonction | À quoi elle sert | Ce qui la paie | Sans elle |
|---|---|---|---|
| **Embeddings** (OpenAI, `text-embedding-3-large`) | transformer un texte en vecteur de sens | `ARAC_EMBEDDINGS_API_KEY`, **lue par ARAC**. Un vecteur par souvenir produit, un par question posée. | plus aucun rappel par similarité |
| **Curation** (le binaire `claude` de ce serveur) | décider ce qui, dans une conversation, mérite d'être retenu | **ce qui authentifie le binaire** : une session d'abonnement ouverte pour le compte d'agent (rien de plus à payer), **ou** `ARAC_CURATION_API_KEY` — que le binaire lit, et qu'ARAC n'ouvre jamais. | les cycles tournent et ne produisent **aucun** souvenir |

> **Une clé de curation ne remplace pas le binaire, et le binaire rend souvent
> la clé inutile.** L'étape 8 constate le binaire et son authentification avant
> de vous demander quoi que ce soit : si une session d'abonnement est déjà
> ouverte, elle vous dit de laisser la clé vide.

**Mesures réelles** sur le cerveau de référence, en régime établi :
3 cycles de digestion par jour · ~87 000 jetons par cycle · ~31 500 jetons par
souvenir effectivement produit. Soit de l'ordre de **8 millions de jetons
d'entrée par mois**.

Au tarif public d'août 2026, avec un modèle de la classe Sonnet (3 $ par
million de jetons d'entrée), cela représente **de l'ordre de 25 $ par mois**
pour la curation, plus la sortie ; trois à cinq fois plus avec un modèle de la
classe Opus. Les embeddings coûtent deux ordres de grandeur moins cher :
quelques euros par mois au plus.

> **Vérifiez ces tarifs vous-même** avant de vous engager. Ce dépôt ne peut pas
> vous promettre un prix qu'il ne contrôle pas.

Vous pouvez refuser les deux clés : le cerveau démarre alors en **mode dégradé
déclaré** (`ARAC_MODE_DEGRADE` dans le fichier d'environnement), et le
bootstrap vous dit précisément ce qui ne marchera pas. Le mode dégradé
`curation` ne se déclare plus sur l'absence d'une clé, mais sur ce qui décide
vraiment : **le binaire est-il là, et a-t-il de quoi s'authentifier ?**

**Et deux interrupteurs, fermés à la sortie d'usine.** Même tout configuré,
aucun cycle ne dépense un centime tant que les deux ne sont pas ouverts :
`ARAC_ALLOW_PAID_AI` dans `arac.env` (l'étape 8 pose la ligne à `0` pour
qu'elle soit visible et basculable), et `arac_config.paid_ai_enabled` **en
base**, qui ne s'arme que par `agents.lib.paid_ai_control arm --confirm`. Le
contrôle final les nomme tous les deux, avec leur geste.

### 3. Ce que le bootstrap ne fait pas

- **Il n'expose rien sur Internet.** L'API et le cockpit n'écoutent que
  `127.0.0.1`. On y accède par un tunnel SSH. Il n'y a donc ni TLS, ni
  reverse-proxy, ni pare-feu à configurer. **Ce qui ne veut pas dire qu'il n'y
  a rien à défendre** : le tunnel dit d'où vient une requête, jamais qui
  l'envoie, et sur une machine à deux cerveaux `127.0.0.1` est un couloir
  partagé. Le bootstrap engendre donc un jeton porteur, l'écrit dans votre
  coffre, et pose `ARAC_API_TRUST_LOOPBACK=0` : le jeton est exigé de toute
  requête, boucle locale comprise. Il pose cette ligne **alors même que c'est
  déjà le défaut du moteur** (`app/auth.py`) — une posture qu'on peut relire
  dans son propre coffre est une posture qu'on peut contester ; un défaut
  implicite, non.
- **Il ne configure pas le Mac.** Le pont Mac → serveur est livré
  (`mac/arac-pont.sh`, `mac/arac-sync.py`, les deux gabarits `launchd`) et
  documenté dans [`docs/PONT-MAC.md`](../docs/PONT-MAC.md) — mais il s'installe
  **depuis le Mac**, après le bootstrap. L'épilogue de l'étape 11 prépare ce
  passage de témoin : il donne votre commande de tunnel, rappelle votre
  `node_id` et vous dit où lire le jeton ; les gestes du pont eux-mêmes sont
  dans `docs/PONT-MAC.md`. Ces scripts sont validés sur Linux contre un serveur
  d'ingestion simulé ; ils n'ont jamais été exercés sur un vrai Mac
  (`launchctl`, `plutil`, l'emplacement réel des données de Claude Desktop).
- **Il ne supprime jamais une base.** Si elle existe, il dit ce qu'elle
  contient et demande la permission de continuer dessus.
- **Il ne restaure pas votre cerveau à votre place — mais il ne se contente plus
  de programmer un dump.** Son étape 9 arme **deux** unités : `…-sauvegarde`
  (`ops/backup.sh`, quatre fois par jour) et `…-restauration`
  (`ops/restore_verify.sh`, le dimanche à 03:00), qui recharge réellement le
  dernier dump dans une base **jetable**, le compare au vivant et conclut
  « VERDICT : PROUVÉ » ou échoue bruyamment. Ce qu'il ne fait pas, et que
  personne ne peut faire à votre place, c'est la **bascule** — remettre un dump
  restauré à la place de la base vivante le jour du sinistre. Elle est écrite pas
  à pas au §7 de [`../docs/SAUVEGARDE.md`](../docs/SAUVEGARDE.md) ; lisez-la
  **avant** d'en avoir besoin.
- **Le seul geste destructeur de tout le bootstrap** est la rétention des
  sauvegardes : les dumps de plus de `ARAC_BACKUP_RETENTION` jours (14 par
  défaut) sont supprimés. C'est annoncé à l'étape 9, avant d'être posé.

### 4. Vos services écriront dans le journal de la machine, et ça ne s'efface pas

Les unités que ce bootstrap pose impriment dans **journald**, qui n'appartient pas
à votre cerveau : il appartient à la machine. Il est lisible par root et par tout
compte du groupe `systemd-journal`, il est conservé des semaines, et **aucun geste
de désinstallation ne peut en retirer votre part** — `journalctl --vacuum-*`
travaille sur des *fichiers* de journal, et un fichier de journal porte aussi les
autres services et, sur une machine à plusieurs cerveaux, celui du voisin.
**systemd ne sait pas effacer les entrées d'une seule unité.**

La conséquence gouverne ce que le produit a le droit d'y écrire : **ce qu'il y
écrit doit pouvoir y rester.** Ce qui s'y trouve aujourd'hui : des comptes, des
durées, des verdicts, des noms d'unités ; et, partout où du texte venu de votre
mémoire s'approche du journal — l'échantillon d'atomes de la restauration
vérifiée, le contexte des avertissements d'écriture de l'API —, des
**empreintes** de la forme `sha8:<empreinte>/<n caractères>` à la place du
texte. C'est [`../app/journal.py`](../app/journal.py) qui en décide, **fermé par
défaut** : ce qui sort en clair doit se démontrer inoffensif, et un domaine — la
liste des domaines étant le plan d'une existence — n'en fait pas partie.

**Ce que ça vous laisse quand même, et c'est ce qu'il faut savoir avant
d'installer :** la **forme** de votre mémoire — combien d'atomes, à quel rythme,
quand, quels avertissements — reste lisible par tout compte du groupe
`systemd-journal`, et elle ne s'efface pas. Le détail de ce qui y va, la commande
pour mesurer **vous-même** sur vos propres mots, et les deux seules issues
possibles sont au §13 de
[`../docs/INSTALLATION.md`](../docs/INSTALLATION.md), sous « Le journal système ».
C'est là, et **là seulement**, que cette liste est tenue à jour : cette page-ci
la résume et ne la recopie pas.

---

## Les quatre promesses

### Idempotent

Relancez-le autant de fois que vous voulez. Une base existante est réutilisée,
jamais écrasée ; des mots de passe déjà engendrés sont réutilisés, jamais
régénérés ; une unité systemd identique n'est pas réécrite, une unité modifiée
est sauvegardée à côté avant remplacement ; le seed des domaines est un
`INSERT … ON CONFLICT` qui ne supprime rien.

### Reprenable

L'avancement est écrit dans `.bootstrap-install.state` après chaque étape
réussie. Une étape échoue → vous réparez → vous relancez → il reprend là.

```bash
sudo ./bootstrap/bootstrap.sh --from migrations   # reprendre à partir de…
sudo ./bootstrap/bootstrap.sh --only scopes       # ne rejouer que…
sudo ./bootstrap/bootstrap.sh --rejouer           # tout reprendre depuis zéro
```

### Simulable

`--dry-run` n'écrit rien, ne crée rien, ne démarre rien. La base n'est ouverte
qu'en **lecture** — juste assez pour pouvoir vous dire ce qu'elle contient
déjà. Une seule fonction, `reel`, garde la porte : dans le code, aucun effet de
bord n'existe hors d'un `reel || return 0`.

### Réparable

Chaque échec dit trois choses : **ce qui a échoué**, **pourquoi**, et **le
geste exact** pour repartir. Si vous tombez sur un échec qui ne dit pas les
trois, c'est un bogue de ce bootstrap — pas de votre installation.

---

## Les onze étapes

Chacune annonce, avant d'agir : *pourquoi elle existe*, *ce qu'elle construit*,
*ce que cela changera dans le comportement de votre cerveau*.

> **Onze, dont dix qui agissent.** `./bootstrap/bootstrap.sh --etapes` liste **dix**
> noms d'étape puis `(épilogue)` : la onzième n'installe rien, elle vous passe le
> relais vers le Mac. Les en-têtes du `--dry-run` comptent bien « ÉTAPE *n* / 11 ».
> Si vous comptez dix d'un côté et onze de l'autre, ce n'est pas une erreur : c'est
> cette ligne-là.

| # | Étape | Ce qu'elle laisse derrière elle |
|---|---|---|
| 1 | `prereqs` | Rien. Elle constate et explique. |
| 2 | `config` | Rien. Elle déduit tous les noms et chemins de `config/brain.toml`. |
| 3 | `base` | La base, son schéma, **cinq rôles** (quatre qui se connectent, plus `_backup`, sans connexion — cible des `GRANT SELECT` des migrations), le coffre à secrets, le fichier d'environnement. |
| 4 | `vecteurs` | Les extensions `vector` et `pg_trgm`. |
| 5 | `migrations` | Le venv Python, les dépendances, le schéma complet. |
| 6 | `scopes` | L'énumération Python, le seed SQL, la table des domaines peuplée. |
| 7 | `secrets` | Jeton d'API, secret de session, empreinte du mot de passe, secret TOTP. |
| 8 | `cles` | La clé d'embeddings (lue par ARAC) et, pour la curation, de quoi authentifier le binaire `claude` — abonnement ou clé, qu'ARAC ne lit jamais. Ou un mode dégradé déclaré. Pose aussi `ARAC_ALLOW_PAID_AI=0`, l'interrupteur 1 sur 2. |
| 9 | `services` | **Huit** unités systemd : cinq services (`api`, `cockpit`, `cycle`, `sauvegarde`, `restauration`) et trois minuteries (`cycle`, `sauvegarde`, `restauration`). La liste vraie, sur votre machine : `systemctl list-unit-files 'arac-<base>-*'`. |
| 10 | `controle` | Un rapport. (Délègue à `checks/verify_install.sh`.) |
| 11 | *(épilogue)* | La marche à suivre pour brancher le Mac. |

### Pourquoi plusieurs rôles PostgreSQL et non un

| Rôle | Peut | Ne peut pas |
|---|---|---|
| `<préfixe>_admin` | créer et modifier les tables (migrations) | — |
| `<préfixe>_app` | lire, insérer, mettre à jour (l'API) | supprimer, modifier le schéma |
| `<préfixe>_agent` | lire tout, insérer des propositions (les cycles) | modifier le savoir existant |
| `<préfixe>_readonly` | lire (le cockpit) | **écrire — structurellement** |
| `<préfixe>_backup` | rien : **sans connexion**, il n'est que la cible des `GRANT SELECT` posés par les migrations | se connecter |

Ils sont **cinq**, dont **quatre** qui se connectent — c'est pourquoi le coffre ne porte
que quatre mots de passe et `arac.env` que quatre DSN, et pourquoi la famille 3 du
contrôle a posteriori en éprouve quatre. `sudo grep -c '^COMMENT ON ROLE' ` n'existe pas ;
ce qui se compte, c'est la plaque, et elle est posée cinq fois.

Le rôle du cockpit porte `default_transaction_read_only = on` : PostgreSQL
ouvre **toutes** ses transactions en lecture seule et refuse le moindre
`INSERT` avant même de le lire. C'est la différence entre « interdit » et
« impossible ». Le contrôle a posteriori le vérifie en *tentant réellement une
écriture* — il ne se contente pas de faire confiance à la configuration.

---

## Où vont les secrets

**Hors du dépôt.** Un `git add .` distrait ne peut pas les publier.

```
/etc/arac/<votre-base>/          0700 root:root
├── arac.env                     0600 — DSN des quatre rôles, jeton d'API, clés externes
├── roles.env                    0600 — les quatre mots de passe (le coffre)
├── cockpit.env                  0600 — session, empreinte du mot de passe, secret TOTP
└── backup-recipients.txt        0600 — VOS clés publiques age. Le bootstrap ne
                                        l'écrit PAS : sans lui, les dumps restent
                                        en clair (docs/SAUVEGARDE.md §4)
```

Les trois premiers sont posés par l'installation ; le quatrième est le seul que vous ayez
à écrire, et il est facultatif — au prix nommé ci-dessus.

`systemd` lit ces fichiers en PID 1 (root) **avant** d'abandonner ses
privilèges : les services tournent sous un utilisateur sans droits et
n'accèdent jamais aux fichiers eux-mêmes.

### Ce que le bootstrap écrit — et ce que le moteur lit

Voici ce que l'installation dépose. **Ce n'est pas la même chose que ce que le
moteur lit**, et cette phrase est la plus importante de la page.

| Variable écrite | Où | Ce que c'est | Nom réellement lu par le moteur |
|---|---|---|---|
| `ARAC_DB_URL_ADMIN` | `arac.env` | DSN du rôle des migrations | `DATABASE_URL_ADMIN` |
| `ARAC_DB_URL_APP` | `arac.env` | DSN de l'API | `DATABASE_URL_APP` |
| `ARAC_DB_URL_AGENT` | `arac.env` | DSN des cycles | `DATABASE_URL_AGENT` |
| `ARAC_DB_URL_READONLY` | `arac.env` | DSN du cockpit (lecture seule stricte) | `DATABASE_URL_READONLY` |
| `ARAC_API_BEARER_TOKEN` | `arac.env` | jeton porteur exigé par l'API | `ARAC_NODE_TOKEN_<NODE_ID>` |
| `ARAC_INGEST_ALLOWED_NODES` | `arac.env` | postes autorisés à déposer | **le même nom** |
| `ARAC_EMBEDDINGS_API_KEY` | `arac.env` | clé OpenAI | `OPENAI_API_KEY` |
| `ARAC_CURATION_API_KEY` | `arac.env` | clé Anthropic | `ANTHROPIC_API_KEY` (lue par le binaire `claude`) |
| `ARAC_MODE_DEGRADE` | `arac.env` | `embeddings`, `curation`, les deux, ou vide | *(lue par le contrôle, pas par le moteur)* |
| `ARAC_HOME` `ARAC_DB` `ARAC_SCHEMA` `ARAC_NODE_ID` `ARAC_BRAIN_NAME` `ARAC_BRAIN_OWNER` | `arac.env` | l'identité et les chemins — `ARAC_SCHEMA` y vaut toujours `arac`, seule valeur supportée (voir « Deux réglages qui n'existent pas ») | **les mêmes noms** |
| `ARAC_CC_SESSION_SECRET` | `cockpit.env` | signature des sessions du cockpit | `CC_SESSION_SECRET` |
| `ARAC_CC_ADMIN_PASSWORD_HASH` | `cockpit.env` | empreinte du mot de passe | `CC_ADMIN_PASSWORD_HASH` |
| `ARAC_CC_TOTP_SECRET` | `cockpit.env` | secret TOTP, base32, 160 bits (RFC 6238) | `CC_TOTP_SECRET` |

**Les deux colonnes se rencontrent, et c'est le bootstrap qui les fait se
rencontrer.** Il préfixe tout par `ARAC_` — c'est ce qui permet à deux cerveaux
de cohabiter sur une machine ; le moteur, lui, lit les noms historiques. À la
fin de l'étape 8, `poser_pont_de_vocabulaire()` (`bootstrap/lib/secrets.sh`)
**copie** chaque valeur sous le nom que le moteur lit, dans le même fichier.
Copie, et non renommage : les deux noms restent lisibles côte à côte, et le
jour où le moteur adoptera le vocabulaire du bootstrap, retirer ce pont ne
cassera rien.

> Cette traduction a longtemps été une **consigne** : un script à recopier
> depuis la documentation de dépannage, *après* un bootstrap qui s'était
> pourtant déclaré terminé. Tant qu'on ne l'avait pas exécuté, l'API démarrait
> puis s'arrêtait sur `DATABASE_URL_APP non définie`, le cockpit répondait
> `503`, les embeddings levaient `OPENAI_API_KEY non définie`, le pont recevait
> `401` — et rien ne disait que l'installation n'était pas finie. **Une
> installation qui exige un geste que l'installateur ne fait pas n'est pas une
> installation.** C'est la leçon, et elle vaut au-delà de ce tableau.

Le pont est **idempotent** et se repose à chaque `--only secrets` : c'est le
geste documenté pour faire tourner le jeton, et sans ce rappel la rotation
écrirait un nouveau `ARAC_API_BEARER_TOKEN` en laissant le moteur lire l'ancien
`ARAC_NODE_TOKEN_…` — un jeton révoqué qui continue d'ouvrir.

**Deux lignes méritent d'être lues deux fois :**

- `ARAC_INGEST_ALLOWED_NODES` porte le même nom des deux côtés — rien à
  traduire. Elle est *fail-closed* : absente ou vide, l'ingestion refuse
  **tout** en `403`, même avec un jeton valide. L'étape 7 la pose depuis
  `config/brain.toml` ; avant cela, elle ne l'était pas, et c'était le blocage
  le plus coûteux de l'installation — parce qu'il ne casse rien de visible.
- `ARAC_API_BEARER_TOKEN` n'est lu par personne tel quel. `app/auth.py` balaie
  l'environnement à la recherche du préfixe `ARAC_NODE_TOKEN_` et construit une
  table `jeton → poste`. Le nom **porte** donc l'identité du poste : c'est ce
  qui permet de révoquer un poste sans toucher aux autres. Le pont le recopie
  sous `ARAC_NODE_TOKEN_<VOTRE_NODE_ID_EN_MAJUSCULES>`, les tirets et les
  points devenant des soulignés (`mac.local` → `ARAC_NODE_TOKEN_MAC_LOCAL`).

Ce tableau n'est pas maintenu à la main : `bootstrap/checks/audit_env.py`
échoue si `.env.example` documente un nom que rien ne lit, ou si le code lit un
nom que ni `.env.example` ni `bootstrap/checks/env_contract.toml` ne déclarent.

**Format de l'empreinte du mot de passe**, à respecter côté cockpit :

```
pbkdf2_sha256$<itérations>$<sel en hexadécimal>$<empreinte en hexadécimal>
```

PBKDF2-HMAC-SHA256, 260 000 itérations par défaut (au-dessus du minimum OWASP
2024). Le nombre d'itérations est **stocké dans l'empreinte** : on pourra
l'augmenter plus tard sans invalider les anciennes.

Aucun secret ne transite jamais par la ligne de commande (`ps` est souvent
lisible par tous) : les valeurs passent par des variables du shell puis par
l'entrée standard.

---

## Tout est paramétré

Aucun chemin n'est en dur : chaque valeur ci-dessous se remplace par une
variable d'environnement — c'est ce qui permet de faire tourner **deux
cerveaux sur la même machine** sans qu'ils se marchent dessus. Deux exceptions,
et elles sont dites juste après le tableau plutôt que passées sous silence.

| Variable | Défaut | Ce qu'elle décide |
|---|---|---|
| `ARAC_HOME` | racine du dépôt | où vit le code |
| `ARAC_DB` | déduit de `brain.name` | nom de la base |
| `ARAC_NODE_ID` | `source.node_id` | poste autorisé à envoyer des conversations |
| `ARAC_DB_HOTE` · `ARAC_DB_PORT` | `127.0.0.1` · `5432` | où joindre PostgreSQL |
| `ARAC_PG_SUPERUSER` | `postgres` | superutilisateur PostgreSQL |
| `ARAC_ETC` | `/etc/arac/$ARAC_DB` | dossier des secrets |
| `ARAC_ENV_FILE` | `$ARAC_ETC/arac.env` | fichier d'environnement |
| `ARAC_SERVICE_USER` | `arac_<base>` | utilisateur de l'API et du cockpit |
| `ARAC_AGENT_USER` | `aracagent_<base>` | utilisateur des cycles |
| `ARAC_VENV` | `$ARAC_HOME/.venv` | environnement Python |
| `ARAC_API_PORT` · `ARAC_COCKPIT_PORT` | **attribués** : premier libre en boucle locale à partir de 8000 · 8100, puis retenus | ports, en boucle locale |
| `ARAC_LOG_DIR` | `/var/log/arac/<base>` | journaux fichiers |
| `ARAC_BACKUP_DIR` | `/var/backups/arac/<base>` | sauvegardes |
| `ARAC_BACKUP_RETENTION` | `14` | jours avant suppression d'un dump |
| `ARAC_CYCLES` | `04:00 13:00 21:00` | heures de digestion |
| `ARAC_CYCLE_TZ` | fuseau du système | fuseau des cycles |
| `ARAC_UNITS_DIR` | `/etc/systemd/system` | où poser les unités |
| `ARAC_ETAT` | `$ARAC_HOME/.bootstrap-install.<base>.state` | fichier d'avancement |

> **Trois de ces lignes ont été fausses, et toujours dans le même sens : celui
> qui fait entrer en collision deux cerveaux d'une même machine.** Les ports
> étaient donnés comme des *défauts* (`8000` · `8100`) alors qu'ils sont
> **attribués** — le bootstrap prend le premier libre à partir de là et le
> retient ; annoncer un défaut fixe, c'est promettre au second cerveau la place
> du premier. Les journaux, les sauvegardes et le fichier d'avancement étaient
> donnés **sans le nom de la base**, alors que les trois le portent : c'est ce
> suffixe qui empêche le second bootstrap de lire l'avancement du premier et de
> se déclarer terminé sans avoir rien fait.
>
> **La table qui fait autorité est celle du code**, pas celle-ci :
> `./bootstrap/bootstrap.sh --help` l'imprime depuis `bootstrap/lib/core.sh`.
> Si les deux divergent, c'est `--help` qui a raison, et cette page qui a
> vieilli.

Exemple — un deuxième cerveau, sur d'autres ports :

```bash
sudo ARAC_API_PORT=8010 ARAC_COCKPIT_PORT=8110 ./bootstrap/bootstrap.sh
```

### Deux réglages qui n'existent pas

`ARAC_SCHEMA` et `ARAC_ROLE_PREFIX` ont longtemps figuré dans le tableau ci-dessus.
Ils n'y sont plus, parce qu'ils **ne sont pas honorés** : le bootstrap **refuse**
toute valeur autre que `arac` et s'arrête avec le code `6`, avant d'avoir rien
créé. Reproduisez-le en une commande :

```bash
# → « ✗ ARAC_SCHEMA ne peut pas encore être changé. », code de sortie 6
ARAC_SCHEMA=moncerveau ./bootstrap/bootstrap.sh --dry-run
```

La cause n'est pas dans le bootstrap, qui saurait faire : elle est dans les
**migrations**, qui écrivent `arac.memory_atoms` et `GRANT … TO arac_app` en
toutes lettres. Avec une autre valeur, l'installation mourait vingt migrations
plus loin sur `role "arac_app" does not exist` — ou, sur une machine hébergeant
déjà un cerveau, donnait silencieusement des droits aux rôles de **l'autre**
cerveau. **Un réglage honoré à moitié est pire qu'un réglage absent** : on le
pose, on lit qu'il est pris en compte, et la panne survient ailleurs, plus tard,
sous un autre nom. Le refus est donc précoce et explicite ; le jour où les
migrations liront ces deux valeurs, le garde disparaît, et lui seul.

Ce que cela implique, et qui déborde ces deux variables : **les rôles PostgreSQL
sont globaux au cluster, pas à la base.**

> **Ce qu'on lisait ici était vrai avant août 2026, et est faux aujourd'hui** :
> « deux cerveaux sur le même serveur PostgreSQL partagent leurs rôles — le
> second bootstrap change les mots de passe du premier ; pour une séparation
> réelle, deux grappes ou deux machines ». C'est **précisément ce qui a été
> corrigé.** Les rôles portent maintenant le nom du cerveau
> (`arac_<votre_base>_<fonction>`), chacun reçoit à sa création une **plaque de
> propriété** (`COMMENT ON ROLE`) portant l'**empreinte** de l'installation, et
> l'étape 3 refuse net, avant toute écriture, un rôle dont l'empreinte n'est pas
> la sienne. Aucun `ALTER ROLE … PASSWORD` n'est engendré nulle part.
>
> Deux grappes restent **plus sûres** — elles séparent aussi les objets globaux
> que ce dépôt ne nomme pas — mais ce n'est **plus obligatoire**. Le geste qui
> l'est, lui, est ailleurs : **un clone du dépôt par cerveau** (l'étape 2 le
> refuse sinon), parce que la taxonomie engendrée à l'étape 6 vit dans le dépôt
> et, elle, ne porte le nom de personne.

---

## Le contrôle a posteriori

`checks/verify_install.sh` répond à une seule question, et ne modifie rien.

```bash
./bootstrap/checks/verify_install.sh          # partiel sans root
sudo ./bootstrap/checks/verify_install.sh     # complet (lit les secrets)
```

Les familles sont **numérotées de 0 à 8**, et le script les annonce lui-même —
`./bootstrap/checks/verify_install.sh --simulation` les liste sans rien exiger
d'installé, et joue la famille 0 pour de vrai :

0. **le contrat des variables d'environnement** — `.env.example` contre le code ;
   la seule qui ne demande aucune installation ;
1. **la description** — `brain.toml`, `scopes.toml`, taxonomie à jour ;
2. **la base** — existence, pgvector, tables, révision du schéma ;
3. **les rôles** — les quatre qui se connectent existent, chacun se connecte, et
   une **tentative d'écriture réelle** avec le rôle du cockpit doit ÉCHOUER ;
4. **la taxonomie et ce qu'elle porte** — dont deux comptages qui n'existent
   que parce qu'ils ont coûté cher au cerveau de référence :
   - les souvenirs posés sur une **racine** nue, donc hors de l'état courant,
     de la vue des scopes et de la couverture (près d'un sur onze, sur le
     cerveau de référence),
   - les souvenirs **sans provenance**, donc invérifiables (76 % là-bas, après
     un changement de format du champ `source_ref`) ;
5. **les secrets** — présence et permissions, mode dégradé éventuel ;
6. **les services** — actifs, et le port tenu par **ce** cerveau ;
7. **les sauvegardes de ce cerveau** — la dernière, son âge, et comment la restaurer ;
8. **le croisement code ↔ schéma** — tout ce que le code nomme existe-t-il en base ?

Sortie : `0` si sain (des avertissements restent possibles), `1` si au moins un
contrôle a échoué. Chaque échec est suivi du geste exact qui le corrige.

---

## Restaurer une sauvegarde

À faire **au moins une fois pour de vrai**, avant d'en avoir besoin.

**C'est le seul geste de tout ce dépôt qui CHARGE une mémoire dans une base.** Tous les
autres lisent, écrivent ou détruisent la vôtre ; celui-ci prend un fichier et en fait une
mémoire vivante. Si le fichier n'est pas le vôtre, vous venez d'installer les souvenirs de
quelqu'un d'autre dans votre serveur — sans erreur, sans avertissement, avec un compte
d'atomes rassurant à la fin. Les trois précautions ci-dessous ne sont donc pas du zèle :
elles sont le geste.

```bash
# 0. QUI, ET OÙ. Sans ces deux valeurs, les commandes suivantes désignent
#    le cerveau du voisin — son serveur, ses dumps, sa base d'essai.
BASE=<votre_base>          # exactement brain.name de config/brain.toml
PGPORT_BASE=$(sudo sed -n 's/^ARAC_DB_PORT=//p' "/etc/arac/$BASE/arac.env")
: "${PGPORT_BASE:?port introuvable dans /etc/arac/$BASE/arac.env — arretez-vous, cette installation nest pas identifiee}"

# 1. LE DUMP : le vôtre. On ne prend PAS « le dernier fichier du dossier ».
#    /var/backups/arac est commun à toute la machine ; le sous-dossier et le
#    préfixe portent tous deux le nom de votre base, et c'est ce qui distingue
#    votre mémoire de celle des autres cerveaux du serveur.
DUMP=$(sudo find "/var/backups/arac/$BASE" -maxdepth 1 -name "$BASE-*.dump" \
         -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)
echo "${DUMP:?aucune sauvegarde de $BASE — ne restaurez rien dautre ; lancez dabord la sauvegarde}"

# 2. DANS UNE BASE D'ESSAI, sur VOTRE grappe, jamais par-dessus la vraie.
#    Le nom de la base d'essai est dérivé lui aussi : un « brain_test » figé
#    est un objet global de la grappe, que deux cerveaux se disputeraient.
sudo -u postgres createdb -p "$PGPORT_BASE" "${BASE}_test"
sudo -u postgres psql -p "$PGPORT_BASE" -d "${BASE}_test" -q \
  -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;"

# 3. RESTAURER. `sudo cat` lit le dump ; `pg_restore` le charge.
#    Les deux moitiés ne sont pas la même personne, et c'est voulu — voir plus bas.
sudo cat "$DUMP" | sudo -u postgres pg_restore -p "$PGPORT_BASE" \
  -d "${BASE}_test" --no-owner --no-privileges

# 4. VÉRIFIER — et vérifier AUSSI où l'on est. Un compte seul ne prouve rien.
sudo -u postgres psql -p "$PGPORT_BASE" -d "${BASE}_test" -tAc \
  "SELECT current_setting('port'), current_database(),
          count(*) FROM arac.memory_atoms WHERE status='active'"

# 5. JETER la base d'essai (IRRÉVERSIBLE, et c'est le but : elle est un brouillon)
sudo -u postgres dropdb -p "$PGPORT_BASE" "${BASE}_test"
```

**Les quatre pièges que ces commandes désamorcent**, dans l'ordre où ils vous
attraperaient :

| Le piège | Ce qu'il donne | Ce qui le désamorce |
|---|---|---|
| `-p` absent | `createdb`, `pg_restore` et `dropdb` s'adressent à la grappe **par défaut** de la machine (`5432`), pas à celle de votre cerveau | `-p "$PGPORT_BASE"`, lu dans votre coffre |
| le dump pris à la racine commune | `/var/backups/arac/` contient les dumps de **tous** les cerveaux du serveur ; en prendre un au hasard charge la mémoire d'un voisin | le sous-dossier `/$BASE/` **et** le préfixe `$BASE-` |
| un nom de base d'essai figé | une base est un objet **global à la grappe** : deux cerveaux qui utilisent le même nom d'essai se détruisent l'un l'autre à l'étape 5 | `${BASE}_test`, dérivé |
| `pg_restore` lancé sous `postgres` sur un dump que `postgres` ne peut pas lire | `could not open input file … Permission denied` — le dossier est en `0700 root:root`, comme il doit l'être | `sudo cat "$DUMP" \|` : root lit, `postgres` charge |

> **Pourquoi couper le geste en deux (`sudo cat` d'un côté, `sudo -u postgres` de
> l'autre)** — un dump contient l'intégralité d'un cerveau **en clair**. Son dossier est en
> `0700 root:root` exactement pour que le compte de service PostgreSQL, qui n'a aucune
> raison de lire vos souvenirs sur disque, ne le puisse pas. La réponse n'est donc pas
> d'affaiblir les droits du dossier — c'est de faire lire le fichier par celui qui y a
> droit, et de ne donner à PostgreSQL que le flux. Le format `custom` se restaure très bien
> depuis l'entrée standard.

> **Ce que ce contrôle prouve, et ce qu'il ne prouve pas.** Il prouve que le fichier est
> lisible, complet et rechargeable, et que le savoir y est. Il ne prouve **pas** que votre
> cerveau redémarrerait dessus : les rôles, les secrets et les unités ne sont pas dans le
> dump. La procédure complète de reconstruction est au § *Repartir d'une sauvegarde* de
> [`docs/SAUVEGARDE.md`](../docs/SAUVEGARDE.md).

---

## Quand ça coince

| Symptôme | Cause la plus fréquente | Geste |
|---|---|---|
| « Votre cerveau n'a pas encore été décrit » | l'entretien n'a pas été fait | `python3 bootstrap/wizard.py` |
| « Taxonomie refusée » | une racine sans feuille, une clé invalide | le message dit quoi corriger, et où |
| « pgvector n'est pas disponible » ou « trop ancien » | paquet absent, pour une autre version majeure, ou < 0.7.0 (Ubuntu 24.04 livre 0.6.0) | dépôt PGDG : `sudo apt install -y postgresql-common && sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh`, puis `sudo apt install postgresql-16-pgvector && sudo systemctl restart postgresql` |
| Alembic s'arrête | extension manquante, ou droits | relire le message ; puis `--from migrations` |
| « Retrait refusé — du savoir vivant serait orphelin » | un domaine habité a disparu de `scopes.toml` | le remettre, ou déplacer ses souvenirs d'abord |
| Un service ne démarre pas | `ExecStart` pointe vers du code absent | `journalctl -u <unité> -n 40 --no-pager` |
| Le cockpit refuse le mot de passe | second facteur non appairé | `sudo ./bootstrap/bootstrap.sh --only secrets` |
| Aucun souvenir après plusieurs jours | mode dégradé (clé de curation absente) | `sudo ./bootstrap/bootstrap.sh --only cles` |
| Un cycle ne produit rien | identifiants de poste incohérents — cause n°1 des cycles perdus sur le cerveau de référence (36 %) | comparer `ARAC_NODE_ID` côté serveur et côté Mac |

---

## Ce qui a été éprouvé, et ce qui ne l'est toujours pas

Honnêteté d'abord, dans les deux sens : ce bootstrap a été **mené deux fois de
bout en bout**, en réel, depuis une base absolument vide, avec **deux
taxonomies différentes**. Ont donc bien tourné : la création de la base et de
ses rôles, `CREATE EXTENSION vector`, `alembic upgrade head` jusqu'à la tête
des migrations, l'écriture des secrets, `systemctl enable --now`, et le
contrôle a posteriori sans un seul échec. Les deux schémas obtenus sont **les
mêmes** — c'est le critère, pas leur taille, qui bougera à la prochaine
migration. « Les mêmes » a un sens précis : identiques une fois retirée, des
deux côtés, la **plaque d'identité** que ce bootstrap grave dans le commentaire
du schéma (`cerveau=`, `empreinte=`, `poste=`) et que `pg_dump` emporte
exprès — c'est elle qui permet à `ops/restore_verify.sh` de dire « ce dump vient
bien de CE cerveau ». Elle doit donc différer, et deux dumps rigoureusement
identiques seraient un défaut, pas une preuve. La commande, en deux temps, est
au §7c du `README` de la racine.

**Les saisies interactives ont été jouées le 9 août 2026**, derrière un vrai
pseudo-terminal : `bootstrap.sh --only secrets`, mot de passe du cockpit tapé
deux fois aux invites `getpass`, URI `otpauth://` affichée une seule fois, puis
« Appairage effectué ? (O/n) » — **sans qu'aucun code à six chiffres soit
demandé ni vérifié**, ce que ce README annonce plus haut. Et le mot de passe
tapé ouvre le cockpit pour de vrai : `POST /cc/login` avec ce mot de passe et un
code calculé depuis le secret appairé rend `303` vers `/cc/`, pose la session,
et `/cc/v1/atoms` répond `200` ; un mot de passe faux rend `401`.

**Et le chemin interactif complet a été joué depuis** — cette page a écrit
« seule l'étape des secrets l'a été », et ce n'est plus vrai. Le 10 août 2026,
deux cerveaux sont nés du chemin entier derrière un vrai pseudo-terminal, depuis
deux clones distincts et avec deux taxonomies sans un domaine commun :
`bootstrap/wizard.py` mené question par question, `--dry-run` lu, puis
`bootstrap.sh` **sans `--yes`** — mot de passe du cockpit tapé aux invites
`getpass`, appairage confirmé, et les clés payantes **refusées** à leur
invite, ce qui est le cas que vit un lecteur prudent.

**Ce qui reste ouvert dans F4** : le rejeu depuis un Ubuntu *nu* — la machine
d'essai portait déjà PostgreSQL et pgvector — et l'appairage TOTP sur un
téléphone réel (le code a été calculé depuis le secret, pas lu sur un appareil).

**Ce qui reste ouvert au-delà de F4**, et qui pèse plus lourd : aucune
conversation n'a été ingérée **par une installation issue de ce bootstrap**.
La précision compte, et elle a manqué ici : sur le cerveau de référence, qui
n'a pas été posé par ce bootstrap, la chaîne complète tourne — ingestion,
embeddings facturés, extraction, rappel — et laisse un reçu de cycle citable.
C'est le §7c du `README` de la racine qui tient cette distinction à jour. Ce
qui manque est donc le chemin *installation neuve → première conversation →
premier atome*.

**Ce qui a cessé de manquer : la restauration.** Cette page écrivait que la
restauration d'une sauvegarde « n'a été rejouée nulle part ». C'est faux
depuis que les unités que ce bootstrap arme sont exercées : l'unité
`arac-<base>-sauvegarde.service` — dont l'`ExecStart` **est** `ops/backup.sh`,
`systemctl cat` le montre — produit un dump que `ops/restore_verify.sh`
recharge dans une base jetable et compare (« *VERDICT : PROUVÉ — ce dump se
restaure, et le cerveau en sort entier* »), et le bootstrap arme aussi la
vérification hebdomadaire (`arac-<base>-restauration.timer`, dimanche 03:00).
Sur un cerveau posé par ce bootstrap puis détruit pour de vrai
(`DROP SCHEMA arac CASCADE`), le § 7 de `docs/SAUVEGARDE.md` l'a remis debout
et ses souvenirs ont été relus **sous le rôle de l'application**.
`make acceptance` rejoue tout cela à chaque passage, étape 8 — c'est là qu'il
faut regarder, pas ici : une ligne de README se périme, un juge qui tourne,
non. Ce qui reste non joué de la sauvegarde : le chemin **chiffré** (`age -d`)
et la copie **hors site**, qui demandent une clé et une seconde machine.

Si vous êtes la première personne à le lancer sur une machine neuve : notez
chaque friction. C'est exactement ce que `GOAL.md` appelle le test
d'installation à l'aveugle, et c'est la dernière chose qui manque.
