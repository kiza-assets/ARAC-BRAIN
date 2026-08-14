# Configuration — chaque réglage, et ce qui casse si on se trompe

Ce document est une référence. On ne le lit pas en entier : on y cherche une variable et
on veut quatre choses — **ce qu'elle fait**, **sa valeur par défaut**, **quand la
changer**, **ce qui casse si on se trompe**.

Deux principes gouvernent tout ce qui suit.

**Aucun chemin n'est écrit en dur.** Le cerveau de référence avait le même chemin
d'installation, en dur, dans plus de trois cents fichiers source. C'est très
concrètement la différence entre un programme personnel et un cadre réutilisable. Si
vous ajoutez un chemin absolu quelque part dans ce dépôt, vous refermez la porte.

**Aucun secret n'est versionné.** `.env.example` et les fichiers de `/etc/arac/` sont
deux mondes distincts : le premier est un document, le second contient des valeurs. Un
jeton commité est un jeton à révoquer, même après suppression — l'historique de git le
garde pour toujours.

---

## Table des matières

- [Où vivent les réglages](#où-vivent-les-réglages)
- [Le double vocabulaire](#le-double-vocabulaire) ← **à lire en premier**
- [1. Où vit ce cerveau — les chemins](#1-où-vit-ce-cerveau--les-chemins)
- [2. Qui est ce cerveau — l'identité](#2-qui-est-ce-cerveau--lidentité)
- [3. La base et ses rôles](#3-la-base-et-ses-rôles)
- [4. Les embeddings](#4-les-embeddings)
- [5. La curation, et les freins à dépense](#5-la-curation-et-les-freins-à-dépense)
- [6. L'API](#6-lapi)
- [7. Le cockpit](#7-le-cockpit)
- [8. Les services et les cadences](#8-les-services-et-les-cadences)
- [9. Les sauvegardes](#9-les-sauvegardes)
  · [`ARAC_ENV_FILE` — les cinq rangs](#arac_env_file--les-cinq-rangs-et-lequel-sapplique-à-vous)
- [10. Les alertes](#10-les-alertes)
- [11. Telegram — facultatif](#11-telegram--facultatif)
- [12. Les drapeaux de comportement](#12-les-drapeaux-de-comportement)
- [13. La taxonomie](#13-la-taxonomie)
- [14. Le bootstrap lui-même](#14-le-bootstrap-lui-même)
- [Changer un réglage sans casser quelque chose](#changer-un-réglage-sans-casser-quelque-chose)

---

## Où vivent les réglages

| Fichier | Écrit par | Lu par | Versionné ? |
|---|---|---|---|
| `config/brain.toml` | `bootstrap/wizard.py` | `arac_runtime.py`, le bootstrap | non (votre identité) |
| `config/scopes.toml` | `bootstrap/wizard.py`, vous | `bootstrap/generate_scopes.py` | non (votre taxonomie) |
| `/etc/arac/<votre_base>/arac.env` | `bootstrap/bootstrap.sh` | les unités systemd (`EnvironmentFile=`) | **jamais** |
| `/etc/arac/<votre_base>/roles.env` | `bootstrap/bootstrap.sh` | rien d'automatique — c'est le coffre | **jamais** |
| `/etc/arac/<votre_base>/cockpit.env` | `bootstrap/bootstrap.sh` | l'unité du cockpit | **jamais** |
| `$ARAC_HOME/.env` | vous, depuis `.env.example` | les scripts de `ops/`, les commandes lancées à la main | **jamais** |
| `.env.example` | ce dépôt | personne — c'est de la documentation | oui |
| `config/scopes.example.toml` | ce dépôt | personne — c'est un modèle commenté | oui |
| `config/projects.example.toml` | ce dépôt | personne — modèle pour le cockpit | oui |

### Les deux fichiers d'environnement

Il y en a **deux**, et c'est aujourd'hui une source de confusion réelle :

- **`/etc/arac/<votre_base>/arac.env`** — engendré par le bootstrap, hors du dépôt (un
  `git add .` distrait ne peut pas le publier), lu par systemd en PID 1 avant
  d'abandonner ses privilèges. **C'est le fichier de production.**
- **`$ARAC_HOME/.env`** — copié de `.env.example` par vous, lu par les scripts
  d'exploitation de `ops/` et par ce que vous lancez à la main.

Les deux ne portent pas les mêmes noms de variables. Voir la section suivante.

> **Ne sourcez jamais `.env` avant `make test`.** Les drapeaux de comportement armés en
> production feraient rougir la suite sans qu'une ligne de code ait changé. La suite les
> neutralise, mais autant ne pas les poser.

---

## Le double vocabulaire

Le bootstrap et le moteur ne parlent pas encore le même dialecte. Le bootstrap préfixe
tout par `ARAC_` ; le moteur, extrait de l'installation d'origine, lit encore les noms
historiques. Les deux sont corrects ; il faut les faire se rencontrer, en **copiant**
chaque variable sous l'autre nom — les deux colonnes cohabitent alors dans le même
fichier.

**Le pont est posé sur un fichier, pas sur les deux.** C'est le point à retenir de cette
section, et il décide si votre cockpit s'ouvrira.

| Ce que le **bootstrap écrit** | Ce que le **moteur lit** | Dans quel fichier | Posé par le bootstrap ? |
|---|---|---|---|
| `ARAC_DB_URL_ADMIN` | `DATABASE_URL_ADMIN` | `arac.env` | **oui** |
| `ARAC_DB_URL_APP` | `DATABASE_URL_APP` | `arac.env` | **oui** |
| `ARAC_DB_URL_AGENT` | `DATABASE_URL_AGENT` | `arac.env` | **oui** |
| `ARAC_DB_URL_READONLY` | `DATABASE_URL_READONLY` | `arac.env` | **oui** |
| `ARAC_EMBEDDINGS_API_KEY` | `OPENAI_API_KEY` | `arac.env` | **oui** |
| `ARAC_CURATION_API_KEY` | `ANTHROPIC_API_KEY` | `arac.env` | **oui** |
| `ARAC_API_BEARER_TOKEN` | `ARAC_NODE_TOKEN_<NODE_ID>` | `arac.env` | **oui** |
| `ARAC_CC_SESSION_SECRET` | `CC_SESSION_SECRET` | **`cockpit.env`** | **oui** |
| `ARAC_CC_ADMIN_PASSWORD_HASH` | `CC_ADMIN_PASSWORD_HASH` | **`cockpit.env`** | **oui** |
| `ARAC_CC_TOTP_SECRET` | `CC_TOTP_SECRET` | **`cockpit.env`** | **oui** |

`poser_pont_de_vocabulaire` (`bootstrap/lib/secrets.sh`) traite les **deux** fichiers :
les sept premières lignes dans `arac.env`, les trois dernières dans `cockpit.env`. Chaque
valeur reste dans le fichier où elle est née — l'empreinte du mot de passe et le secret
TOTP n'ont aucune raison d'être visibles de l'API ni des cycles, qui ne chargent que
`arac.env`.

> **Cette page a dit deux faussetés successives sur ces trois lignes.** D'abord « traduites
> » alors qu'elles ne l'étaient pas — une intention écrite comme un fait. Puis « **non**,
> et c'est le seul geste que l'installation ne pose pas elle-même », maintenu après que le
> bootstrap eut cessé d'avoir ce défaut. **Une colonne périme dans les deux sens.** C'est
> pourquoi elle est doublée d'un contrôle qui se lance : c'est lui qui fait foi, pas elle.

**Ce qui casse si la colonne de droite manque** : l'API démarre puis s'arrête sur
`DATABASE_URL_APP non définie`. Le cockpit démarre mais répond `503` à toute connexion.
Les embeddings lèvent `OPENAI_API_KEY non définie`. Le pont reçoit `401`.

**Les deux contrôles**, et ce sont eux qui font foi :

```bash
sudo grep -c '^DATABASE_URL_' /etc/arac/<votre_base>/arac.env      # attendu : 4
sudo grep -cE '^(CC_SESSION_SECRET|CC_ADMIN_PASSWORD_HASH|CC_TOTP_SECRET)=' \
     /etc/arac/<votre_base>/cockpit.env                            # attendu : 3
```

Si le second rend `0`, **votre cockpit ne s'ouvrira pas** tant que vous n'aurez pas posé la
traduction — et votre installation est antérieure au correctif. Le geste manuel,
idempotent, testé, et qui traite **les deux fichiers**, est dans
[`DEPANNAGE.md` §1](DEPANNAGE.md#1-lapi-ne-démarre-pas--database_url_app-non-définie).

**La dernière ligne mérite une explication.** `app/auth.py` n'accepte pas un jeton
global : il scanne l'environnement à la recherche du préfixe `ARAC_NODE_TOKEN_` et
construit une table `jeton → node_id`. Le nom de la variable est donc le `node_id` en
majuscules, tirets remplacés par des soulignés :

```
mon-portable        →  ARAC_NODE_TOKEN_MON_PORTABLE
claude-code-serveur →  ARAC_NODE_TOKEN_CLAUDE_CODE_SERVEUR
```

C'est ce qui permet de **révoquer un poste sans toucher aux autres** : retirez sa
variable, redémarrez l'API, il est fermé à la requête suivante.

---

## 1. Où vit ce cerveau — les chemins

Résolus par `arac_runtime.py`. Chacun a un défaut ; aucun n'est en dur ailleurs.

| Variable | Défaut | Ce qu'elle fait | Quand la changer | Ce qui casse |
|---|---|---|---|---|
| `ARAC_HOME` | le dépôt qui contient `arac_runtime.py` | la racine de l'installation ; tout le reste en découle | quand le code vit ailleurs que là où vous lancez les commandes ; les unités systemd la posent toujours explicitement | mauvaise valeur → logs, verrous et secrets cherchés au mauvais endroit ; les services démarrent puis ne trouvent rien |
| `ARAC_LOGS_DIR` | `$ARAC_HOME/logs` | ce que le cerveau raconte de lui-même | disque dédié, partition de logs | rien d'immédiat : les journaux partent ailleurs, silencieusement |
| `ARAC_MISSIONS_DIR` | `$ARAC_LOGS_DIR/agents` | une ligne JSONL par mission d'agent, **prompt et réponse inclus** | idem | vous perdez la capacité de rejouer une décision d'agent six mois plus tard |
| `ARAC_VAR_DIR` | `$ARAC_HOME/var` | l'état vivant : verrous, curseurs, marqueurs de cycle | volume rapide | deux cycles peuvent se chevaucher si le verrou change de place en cours de route |
| `ARAC_DATA_DIR` | `$ARAC_HOME/data` | l'espace de travail des agents (HOME, caches) | volume dédié | les agents écrivent dans un `HOME` inattendu |
| `ARAC_SECRETS_DIR` | `$ARAC_HOME/secrets` | jetons et mots de passe posés à la main (mode `0700`) | quand vous préférez `/etc/arac/…` — ce que fait le bootstrap | secrets introuvables |
| `ARAC_BACKUP_DIR` | `/var/backups/arac/<base>` | où atterrissent les dumps — **hors de la racine par défaut**, et **sous le nom de votre cerveau** : le dossier parent est commun à la machine | disque distinct, toujours | une sauvegarde qui vit dans le dossier qu'elle sauvegarde ne sauvegarde rien |
| `ARAC_PYTHON` | `$ARAC_HOME/.venv/bin/python` | l'interpréteur qui a les dépendances | venv ailleurs, Python système | les sous-processus lancés par les agents échouent sur un `ImportError` |
| `ARAC_ALEMBIC` | `$ARAC_HOME/.venv/bin/alembic` | la commande de migration | idem | les messages « tapez ceci » donnent une commande inexistante |

---

## 2. Qui est ce cerveau — l'identité

`config/brain.toml`, écrit par l'entretien :

```toml
[brain]
owner = "<votre prénom>"
name  = "<le nom de votre cerveau>"

[source]
node_id = "<l-identifiant-de-votre-poste>"
```

| Réglage | Ce qu'il fait | Quand le changer | Ce qui casse |
|---|---|---|---|
| `brain.owner` | affichage seulement | jamais, ou quand vous voulez | rien |
| `brain.name` | **engendre le nom de la base** (points et tirets → soulignés), le préfixe des unités systemd et le chemin `/etc/arac/<base>/` | avant la première installation, et pas après | après coup : votre base et vos unités ne correspondent plus au nom déclaré ; le contrôle a posteriori cherche une base qui n'existe pas |
| `source.node_id` | l'identifiant du poste d'où les conversations arrivent. **Le cerveau refuse toute conversation d'un nœud non déclaré.** | avant la première synchronisation | après coup : les conversations existantes gardent l'ancien `node_id`, la provenance se scinde en deux populations, et les cycles partent en quarantaine — **cause n°1 des 36 % de cycles stériles du cerveau de référence** |

**Les surcharges d'environnement** — `ARAC_BRAIN_CONFIG`, `ARAC_NODE_ID`,
`ARAC_BRAIN_NAME`, `ARAC_BRAIN_OWNER` — existent pour un test ou une migration
ponctuelle. Elles court-circuitent la lecture du fichier. Ne les posez pas en
production : deux vérités concurrentes sur l'identité d'un cerveau, c'est exactement le
problème qu'`arac_runtime` a été écrit pour résoudre.

> Si `config/brain.toml` n'existe pas, le code ne dit pas « fichier introuvable » : il
> renvoie à l'entretien. Un cerveau sans identité n'est pas un défaut de configuration,
> c'est une naissance qui n'a pas eu lieu.

---

## 3. La base et ses rôles

```
DATABASE_URL_ADMIN=postgresql://arac_<votre_base>_admin:…@127.0.0.1:<votre_port_pg>/<votre_base>
DATABASE_URL_APP=postgresql://arac_<votre_base>_app:…@127.0.0.1:<votre_port_pg>/<votre_base>
DATABASE_URL_AGENT=postgresql://arac_<votre_base>_agent:…@127.0.0.1:<votre_port_pg>/<votre_base>
DATABASE_URL_READONLY=postgresql://arac_<votre_base>_readonly:…@127.0.0.1:<votre_port_pg>/<votre_base>
```

**Le nom d'utilisateur porte celui de votre cerveau**, parce qu'un rôle PostgreSQL est
global au cluster : c'est ce qui permet à deux cerveaux de vivre sur une même grappe sans
se réencoder mutuellement les mots de passe. Le bootstrap écrit ces quatre lignes
lui-même ; vous n'avez rien à recopier.

Ce ne sont pas quatre façons d'écrire la même chose. Chaque rôle a le pouvoir **minimal**
de sa fonction, et c'est ce qui rend les erreurs rattrapables.

| Rôle | Ce qu'il peut | Ce qu'il ne peut pas | Ce qui casse si vous mettez le mauvais |
|---|---|---|---|
| `_ADMIN` | DDL — utilisé **uniquement** par les migrations | — | donner l'ADMIN à l'API, c'est lui donner le pouvoir de détruire son propre schéma |
| `_APP` | lire, insérer, mettre à jour | **supprimer** | donner l'APP aux migrations : `alembic upgrade head` échoue sur un `CREATE TABLE` |
| `_AGENT` | lire tout, insérer des propositions | modifier le savoir existant | un agent avec l'APP peut réécrire du savoir sans passer par le circuit de proposition |
| `_READONLY` | lire, en transaction **read-only stricte** | **écrire — structurellement** | donner autre chose au cockpit lui rend le pouvoir d'écrire dans la mémoire. Le tableau de bord n'est plus un tableau de bord. |

Le rôle du cockpit porte `default_transaction_read_only = on` : PostgreSQL ouvre
**toutes** ses transactions en lecture seule et refuse le moindre `INSERT` avant même de
le lire. C'est la différence entre « interdit » et « impossible ». Le contrôle a
posteriori le vérifie en **tentant réellement une écriture**.

**Une cinquième variable, facultative** : `DATABASE_URL_BACKUP`. Sans elle, la
sauvegarde tourne sous le rôle ADMIN — elle marche, mais un processus automatique non
surveillé a alors le pouvoir de détruire le schéma. `ops/install_check.sh` le signale.

**Réglages de connexion**, posés à l'installation :

| Variable | Défaut | Quand la changer |
|---|---|---|
| `ARAC_DB` | déduit de `brain.name` | jamais après la première installation |
| `ARAC_DB_HOTE` · `ARAC_DB_PORT` | `127.0.0.1` · `5432` | base distante — **et alors chiffrez le lien** |
| `ARAC_PG_SUPERUSER` | `postgres` | cluster géré avec un autre superutilisateur |

> **`ARAC_ROLE_PREFIX` : une histoire en trois temps, et il faut connaître la fin.**
>
> **Temps 1.** Cette page présentait le préfixe comme un réglage libre. Il ne l'était pas :
> les migrations écrivaient `GRANT … TO` les cinq noms **en toutes lettres**. Le poser
> faisait mourir l'installation vingt migrations plus loin — ou, pire, donnait
> silencieusement des droits aux rôles d'un autre cerveau.
>
> **Temps 2.** Le bootstrap s'est mis à **refuser** toute valeur autre que `arac`
> (sortie `6`). Honnête, et invivable : deux cerveaux sur une grappe partageaient alors
> leurs cinq rôles, et le second bootstrap réencodait les mots de passe du premier. C'est
> l'incident qui a détruit le cerveau de production de l'auteur.
>
> **Temps 3, aujourd'hui.** Les migrations ne nomment plus aucun rôle : elles les
> **déduisent** de `current_user`, c'est-à-dire du rôle d'administration sous lequel elles
> tournent (`db/alembic/roles.py`). Le bootstrap, symétriquement, dérive
> `ARAC_ROLE_PREFIX=arac_<votre_base>` du nom du cerveau. Le nommage est donc vérifiable
> **des deux côtés, sans configuration tenue en double**, et la faute est devenue
> structurellement impossible : pour qu'une migration donne des droits aux rôles d'un
> autre cerveau, il faudrait s'être connecté avec l'identité d'administration de cet autre
> cerveau.
>
> **Ce qui reste vrai, et qu'il ne faut jamais oublier : les rôles PostgreSQL sont globaux
> au cluster, pas à la base.** C'est la raison de tout ce qui précède. Le préfixe reste
> surchargeable, mais il n'y a aucune raison de le faire : le seul contrôle du bootstrap
> porte désormais sur sa **forme** (minuscules, chiffres, `_`, et une longueur qui ne se
> fera pas tronquer à 63 octets par PostgreSQL), plus sur son contenu.
>
> Une installation antérieure au nommage par cerveau continue de fonctionner : son rôle
> d'administration n'a pas de préfixe, la déduction rend `arac`, et elle retrouve
> exactement ses cinq noms d'avant.

---

## 4. Les embeddings

```
OPENAI_API_KEY=sk-…
```

Modèle : `text-embedding-3-large`, **3 072 dimensions**, stocké en `halfvec(3072)`.

**Pourquoi `halfvec` et pas `vector`** : l'index HNSW de pgvector plafonne à
2 000 dimensions pour le type `vector`. La demi-précision divise la place par deux et
reste indexable. La perte de précision est indétectable au rappel ; l'absence d'index,
elle, se voit tout de suite.

> ⚠ **Changer de modèle ou de dimension est irréversible sans tout recalculer.** Les
> vecteurs déjà en base ont été produits par l'ancien modèle. Deux populations
> incomparables cohabitent alors dans le même index, et **le rappel se dégrade sans
> qu'aucun test n'échoue** — c'est le pire type de panne : silencieuse. Si vous devez en
> changer : nouvelle colonne, nouvel index, recalcul de tout le corpus, donc **re-paiement
> de tout le corpus**. C'est une migration, pas un réglage.

Peut-on utiliser un autre fournisseur d'embeddings ? Voir [`FAQ.md`](FAQ.md).

---

## 5. La curation, et les freins à dépense

```
ANTHROPIC_API_KEY=sk-ant-…      # JAMAIS lue par ARAC : posée là pour le binaire `claude`
ARAC_ALLOW_PAID_AI=0            # interrupteur 1 sur 2 ; le second vit EN BASE
```

> **La curation n'est pas un appel d'API.** Le cycle lance le binaire `claude` (Claude
> Code CLI) en sous-processus sur ce serveur, sous le compte d'agent
> (`agents/lib/claude_cli.py`). `ANTHROPIC_API_KEY` n'est donc lue par aucune ligne du
> produit : elle est posée dans l'environnement du service, et c'est le binaire qui la
> trouve — ou qui l'ignore, s'il a déjà une session d'abonnement.

| Variable | Défaut | Ce qu'elle fait | Ce qui casse |
|---|---|---|---|
| `ARAC_ALLOW_PAID_AI` | `0` | **l'interrupteur 1 sur 2**, côté service. Tant qu'il n'est pas à `1`, aucun appel payant n'est émis (refus `master_switch_env_off`). | à `0` : les cycles tournent et ne produisent rien. C'est voulu tant que l'installation n'est pas vérifiée — un cycle lancé sur une configuration à moitié faite dépense pour rien. |
| `arac.arac_config`, clé `paid_ai_enabled` | *(absente)* | **l'interrupteur 2 sur 2**, côté cerveau — **il ne vit pas dans ce fichier, il vit EN BASE**, et ne s'ouvre que par `sudo .venv/bin/python -m agents.lib.paid_ai_control arm --confirm --coffre <coffre>` (refus `master_switch_config_off`). | fermé : le cycle refuse même avec `ARAC_ALLOW_PAID_AI=1`. C'est le verrou que personne ne trouve, parce qu'aucun `grep` sur un fichier ne le montre. |
| `ARAC_CLAUDE_BIN` | *(vide)* | le chemin du binaire de curation, quand il n'est pas dans le `PATH` du service. Résolution : cette variable, puis le `PATH`, puis `/usr/bin/claude`. | mal renseigné : `spawn_failed` à chaque cycle, curseurs intouchés, aucun atome — indéfiniment. |
| `ARAC_CORTEX_FORCE_MANUAL` | *(vide)* | **la valve** : rejoue un cycle immédiatement sur un créneau « manuel », sans attendre l'horaire suivant. Utile après un ré-armement, quand le créneau du jour porte déjà un reçu. | **à retirer après usage** : laissée en place, chaque tir de la minuterie ouvre un créneau neuf au lieu d'un par horaire. |
| `ARAC_CURATOR_MODEL` | celui du code | quel modèle lit vos conversations | un modèle plus petit coûte moins **et extrait moins**. Le rapport n'est pas linéaire : mesurez avant de descendre. |
| `ARAC_PACK_TOKEN_BUDGET` | `80000` | le plafond de jetons par cycle — **le frein principal**. Une valeur plus grande est ramenée à `135000`, plafond dur du code | trop haut : chaque échec coûte cher, car on perd toute la tranche d'un coup. |
| `ARAC_PACK_MAX_CONVS` | `0` = illimité (le pack s'arrête de lui-même à 20 conversations examinées) | combien de conversations sont ADMISES dans une tranche. **Le code recommande `4`** : l'enquête sur les quarantaines n'a vu aucune attribution croisée sur les paquets de 3 à 5 conversations, et une sur deux au-delà de 6 | même logique |
| `ARAC_CURATOR_QUIET_HOURS` | *(vide)* | heures pendant lesquelles le cerveau ne digère pas | rien ne casse ; les cycles tombant dans la fenêtre sont sautés |

**La leçon derrière `ARAC_PACK_TOKEN_BUDGET`.** Sur le cerveau de référence, **36 % des
cycles sont partis en quarantaine sans produire un seul atome**. La cause n'était **pas**
le volume — c'étaient des identifiants incohérents dans la tranche. Mais une tranche trop
grosse rend chaque échec plus cher : on perd tout, d'un coup. **Commencez petit. Vous
augmenterez quand vous aurez vu trois cycles réussir.**

Un garde-dépense (`agents/lib/spend_guard.py`) complète l'interrupteur. Armez les deux
**avant** le premier cycle, pas après la première facture.

---

## 6. L'API

| Variable | Défaut | Ce qu'elle fait | Ce qui casse |
|---|---|---|---|
| `ARAC_NODE_TOKEN_<NODE_ID>` | *(aucun)* | un jeton porteur **par poste autorisé**. Générez avec `openssl rand -hex 32`. | absent → `401` pour toute requête **non exemptée** (voir l'encadré ci-dessous) |
| `ARAC_API_TRUST_LOOPBACK` | **`0` — fermé** | le desserrage de la boucle locale. Par défaut le jeton est exigé **partout**, `127.0.0.1` compris. `1` **plus** un motif écrit dans `ARAC_API_TRUST_LOOPBACK_RAISON` rouvre la boucle locale ; `1` **seul** ne rouvre rien, et le refus le dit. | posée à `1` sans motif → rien ne change, et c'est voulu |
| `ARAC_API_TRUST_LOOPBACK_RAISON` | *(aucune)* | le motif écrit du desserrage — une date, une raison, un numéro de ticket. Il voyage avec l'état : `verify_install.sh` et les journaux le recopient. | absente alors que le desserrage est posé → le desserrage n'est **pas** appliqué |
| `ARAC_INGEST_ALLOWED_NODES` | *(aucune)* | liste blanche des `node_id` autorisés à déposer, séparés par des virgules | **fail-closed : variable absente = tout est refusé (`403`)**, boucle locale comprise. Posée par le bootstrap depuis votre entretien — voir [`DEPANNAGE.md` §7](DEPANNAGE.md#7-http-403--le-serveur-refuse-ce-poste). |
| `ARAC_API_BASE` / `ARAC_API_URL` | posés par le bootstrap depuis `ARAC_API_PORT` | où les agents et le cockpit joignent l'API | **absents, le code retombe sur un numéro codé en dur** — et sur une machine à deux cerveaux, il interroge alors celui du voisin |
| `ARAC_API_PORT` | **attribué**, pas fixé : le premier libre à partir de 8 000, constaté par `ss` puis **écrit** dans `arac.env` | le port d'écoute, **en boucle locale** | port imposé et déjà tenu → le bootstrap refuse, en nommant l'occupant (sortie `6`) ; il ne déplace jamais votre choix en douce |
| `LOG_LEVEL` | `INFO` | verbosité des journaux JSON | `DEBUG` en production remplit le journal et peut y écrire des extraits de conversation |

**L'API n'écoute que `127.0.0.1`.** Ce n'est pas un défaut modifiable par confort : c'est
ce qui rend l'absence de TLS acceptable. On y accède par un tunnel SSH. Si vous voyez
l'API sur `0.0.0.0` dans `ss -ltnp` — et non sur `127.0.0.1` —, quelque chose a été
modifié et votre mémoire est joignable depuis le réseau.

> ### Le jeton est exigé de tout le monde — et la boucle locale n'est plus une exception
>
> **La règle** : toute requête présente son jeton, **y compris** celles qui arrivent de la
> machine elle-même par `127.0.0.1`. Seul `/healthz` reste public. La règle tient dans une
> fonction pure, `app/auth.bearer_requis()`, qu'on peut lire et éprouver sans démarrer
> quoi que ce soit.
>
> #### La leçon, parce qu'elle vaut plus que le réglage
>
> Le raisonnement d'avant était bon, et il était faux. Il disait : « l'API n'écoute que
> `127.0.0.1` ; le seul chemin depuis le Mac est un tunnel SSH ; donc la frontière réelle
> est SSH, qui a déjà authentifié la personne par sa clé ». Chaque proposition est vraie.
> La conclusion ne l'est pas, parce qu'elle suppose en silence une quatrième proposition
> que personne n'avait écrite : **qu'atteindre `127.0.0.1` exige d'avoir franchi SSH.**
>
> C'est faux dès qu'un second compte a un shell sur la machine — et un second cerveau en
> amène au moins un. Mesuré, sur une machine à deux cerveaux, depuis le compte `nobody`,
> sans un seul secret :
>
> ```
> GET  http://127.0.0.1:<port du voisin>/v1/dashboard/search  → 200, la mémoire en clair
> POST http://127.0.0.1:<port du voisin>/v1/ingest/messages   → 202, écrit chez le voisin
> ```
>
> **Ce qui rend cette porte instructive, c'est ce qui ne la ferme pas.** Comptes système
> distincts, coffres en `0700`, rôles PostgreSQL, grappes séparées, unités systemd
> nommées : tout cela avait été fait, et rien de tout cela ne la voit. Elle ne passe par
> **aucun fichier** — donc aucune permission ne s'y applique. Une frontière qui repose sur
> « par où la requête est *forcément* passée » n'est pas une frontière : c'est une
> hypothèse sur l'environnement, et l'environnement change sans prévenir.
>
> **La règle générale, à emporter ailleurs :** une exemption fondée sur l'*origine* d'une
> requête vaut ce que vaut l'hypothèse sur qui peut prendre cette origine. Ici l'origine
> `127.0.0.1` ne prouve pas « c'est le propriétaire », elle prouve « c'est quelqu'un sur
> cette machine » — ce qui est exactement la population dont on voulait se protéger.
>
> #### Pourquoi inverser le défaut plutôt que fermer « quand il y a un voisin »
>
> Fermer à l'arrivée d'un second cerveau serait **asymétrique** : le nouveau se fermerait,
> l'ancien resterait ouvert, et le fermer exigerait d'écrire dans le coffre du voisin —
> c'est-à-dire de violer l'isolement qu'on prétend défendre. Un défaut fermé fait
> disparaître l'asymétrie : un cerveau installé seul est protégé exactement comme un
> cerveau installé à côté d'un autre, et l'ordre d'installation ne décide plus de rien.
>
> **Le coût pour vous est nul** : le bootstrap engendre déjà le jeton, et tout ce qui
> appelle l'API le porte — le pont Mac, le pont sans-Mac, le cycle, le cockpit, les
> agents. Rien de plus ne vous est demandé.
>
> #### Une exception, et elle est voulue : `verify_install.sh`
>
> Le contrôle d'installation, lui, frappe à la porte **sans** jeton — et c'est délibéré.
> Il ne cherche pas à entrer : il vérifie que la porte **refuse**. Il envoie un `GET` de
> recherche sans le moindre en-tête d'autorisation et regarde ce que l'API répond
> vraiment, maintenant : `401`, la porte est fermée ; `200`, elle est ouverte, et aucune
> lecture de fichier ne peut prétendre le contraire.
>
> C'est le point qui vaut d'être retenu : **il MESURE un état au lieu de lire une
> variable.** La version précédente de ce contrôle lisait `ARAC_API_TRUST_LOOPBACK` dans
> le coffre — donc une **intention**, pas un état. Or le coffre peut dire « fermé »
> pendant que le service tourne encore avec l'ancienne valeur, faute de redémarrage :
> c'est même le cas le plus probable juste après une modification à la main,
> c'est-à-dire très exactement le moment où l'on lance ce contrôle.
>
> Et le desserrage n'obtient **jamais** de `✓`. S'il est motivé, le contrôle recopie le
> motif en clair et le range parmi les points « à surveiller » — le rendre vert, ce
> serait le faire disparaître du rapport. S'il est posé **sans** motif, c'est un échec :
> le desserrage n'est alors pas appliqué par le moteur, et une variable qui ne fait pas
> ce qu'elle a l'air de faire est une panne. Enfin, si la mesure trouve la porte
> réellement ouverte, le contrôle **sort en échec** et le rapport se termine par « ce
> cerveau n'est pas sain » — pour qu'un lecteur pressé ne referme pas sur une page verte.
>
> Le même refus de la page verte vaut à l'installation : le bootstrap **écrit**
> `ARAC_API_TRUST_LOOPBACK=0` dans votre coffre alors même que c'est déjà le défaut du
> moteur. Ce n'est pas une redondance — **une posture qu'on peut relire dans son propre
> coffre est une posture qu'on peut contester ; un défaut implicite, non.** C'est
> précisément l'implicite qui a laissé cette porte ouverte deux versions durant.
>
> #### Rouvrir la boucle locale : deux variables, jamais une
>
> Une sonde tierce qu'on ne peut pas modifier, un banc de mesure : la raison peut exister.
> Il faut alors **deux** lignes, pas une :
>
> ```bash
> ARAC_API_TRUST_LOOPBACK=1
> ARAC_API_TRUST_LOOPBACK_RAISON="2026-08-08 — sonde héritée qu'on ne peut pas modifier, ticket #412"
> ```
>
> **Sans la seconde, le desserrage n'est pas appliqué** : le jeton reste exigé, et le refus
> dit pourquoi. Ce n'est pas une chicane. Ce qui a laissé cette porte ouverte, ce n'est pas
> une valeur mal choisie, c'est une valeur **implicite** — que personne n'avait écrite,
> donc que personne ne pouvait relire ni contester. Une exception qu'on ne peut pas relire
> est une exception qu'on oublie.
>
> **Trois cas exigent le jeton en toutes circonstances** : une origine autre que la boucle
> locale ; la présence d'un en-tête de proxy (`X-Forwarded-For`, `X-Real-IP`, `Forwarded`) ;
> et le défaut, c'est-à-dire l'absence de desserrage motivé. La liste blanche
> `ARAC_INGEST_ALLOWED_NODES` reste en travers du chemin dans tous les cas : un `node_id`
> non déclaré repart en `403`, boucle locale ou pas.

**Révoquer un poste** : retirez sa variable `ARAC_NODE_TOKEN_…`, redémarrez l'API. Il est
fermé à la requête suivante.

**Un poste doit franchir trois portes indépendantes** : son **jeton**
(`ARAC_NODE_TOKEN_…`), la **liste blanche** (`ARAC_INGEST_ALLOWED_NODES`), et une ligne
dans **`arac.nodes`** — clé étrangère obligatoire. Pour le poste déclaré à l'entretien,
l'installation ouvre les trois toute seule (étape des clés pour les deux premières,
migration `0008` pour la troisième). Pour en ajouter un **second**, il faut les poser à la
main : ajouter son `node_id` à la liste blanche, et semer sa ligne avec
`db/seeds/01_nodes_and_config.sql`. Le seed refuse de deviner le `node_id` : il faut le
lui passer. Un `node_id` inventé ouvrirait exactement la porte que cette table sert à
tenir fermée.

---

## 7. Le cockpit

| Variable | Défaut | Ce qu'elle fait | Ce qui casse |
|---|---|---|---|
| `CC_SESSION_SECRET` | *(aucun)* | signe les cookies de session (HMAC-SHA256) | absent → **503 sur toute connexion**. Changé → toutes les sessions ouvertes tombent (c'est aussi la façon de déconnecter tout le monde). |
| `CC_ADMIN_PASSWORD_HASH` | *(aucun)* | `pbkdf2_sha256$<itérations>$<sel hex>$<empreinte hex>`, 260 000 itérations par défaut | absent → **503**. Le serveur ne connaît pas votre mot de passe, seulement de quoi vérifier que vous le connaissez. |
| `CC_TOTP_SECRET` | *(aucun)* | second facteur, base32, 160 bits (RFC 6238) | absent → **503**. Perdu avec l'appareil → supprimez la ligne et rejouez `bootstrap.sh --only secrets`. |
| `DATABASE_URL_READONLY` | *(aucun)* | la seule connexion du cockpit | absent → le cockpit démarre et n'affiche aucune donnée |
| `ARAC_COCKPIT_PORT` | **attribué** comme celui de l'API : le premier libre à partir de 8 100, constaté puis retenu dans `arac.env` | le port, **en boucle locale** | port imposé et déjà tenu → refus avec l'occupant nommé |

**Le cockpit est fail-closed.** Si l'un des trois secrets manque, il répond `503` et
journalise `not_provisioned` — il ne s'ouvre jamais par accident. L'unité systemd charge
son fichier de secrets avec un tiret (`EnvironmentFile=-…`), donc fichier facultatif :
sans lui, le cockpit démarre mais refuse tout le monde. Fermé par défaut.

**Trois couches de lecture seule**, et pas une : le rôle PostgreSQL, la transaction
`READ ONLY`, et un garde applicatif qui refuse tout SQL contenant `insert`, `update`,
`delete`, `truncate`, `drop`, `alter`, `create`, `grant`, `revoke`, `copy`, `vacuum`,
`refresh`, `call`, `do`.

**`config/projects.toml`** (modèle : `config/projects.example.toml`) déclare vos projets
pour la vue « Aujourd'hui ». Facultatif : sans lui, le cockpit le dit plutôt que
d'afficher une section vide.

---

## 8. Les services et les cadences

| Variable | Défaut | Ce qu'elle fait | Quand la changer |
|---|---|---|---|
| `ARAC_SERVICE_USER` | `arac_<base>` | l'utilisateur de l'API et du cockpit | politique d'utilisateurs système |
| `ARAC_AGENT_USER` | `aracagent_<base>` | l'utilisateur des cycles | idem — le séparer du précédent est délibéré |
| `ARAC_CYCLES` | `04:00 13:00 21:00` | les heures de digestion | fuseau différent, ou rythme différent |
| `ARAC_CYCLE_TZ` | fuseau du système | le fuseau des cycles | serveur en UTC, vous ailleurs |
| `ARAC_UNITS_DIR` | `/etc/systemd/system` | où poser les unités | rarement |
| `ARAC_API_APP` | `app.main:app` | le point d'entrée ASGI de l'API | jamais |
| `ARAC_COCKPIT_APP` | `control_center.app:app` | le point d'entrée du cockpit | jamais |
| `ARAC_CYCLE_MODULE` | `agents.cortex.cycle` | le module lancé par le cycle | jamais |
| `ARAC_VENV` | `$ARAC_HOME/.venv` | l'environnement Python des unités | venv partagé |
| `ARAC_LOG_DIR` | `/var/log/arac/<base>` | les journaux fichiers | partition dédiée |

**Trois cycles par jour, pas un flux continu.** Ce n'est pas une limitation technique :
penser coûte, et une pensée continue coûte en continu. Entre deux cycles, le cerveau
accumule ; au cycle, il traite tout ce qui s'est accumulé d'un coup.

**Corollaire à retenir** : ce que vous dites à 14 h n'est pas mémorisé à 14 h 01. Un
cerveau au repos qui n'a rien produit depuis six heures fonctionne peut-être
parfaitement. Si vous changez `ARAC_CYCLES`, changez aussi `ARAC_ALERT_STALL_HOURS`
(§10) : sinon l'alarme « le cerveau a cessé d'apprendre » sonnera pour un cerveau en
bonne santé, et vous la couperez.

---

## 9. Les sauvegardes

Deux dispositifs coexistent aujourd'hui, et ils ne se connaissent pas.

**a) Celui du bootstrap** — une unité `arac-<base>-sauvegarde`, `pg_dump -Fc` toutes les
six heures, avec une seule variable :

| Variable | Défaut | Ce qu'elle fait |
|---|---|---|
| `ARAC_BACKUP_RETENTION` | `14` | **jours avant SUPPRESSION d'un dump.** C'est le seul geste destructeur de tout le bootstrap. |

**b) Celui de `ops/`** — nettement plus sérieux : contrôles de sincérité du dump,
chiffrement au repos, restauration réellement prouvée, copie hors site, chien de garde.

| Variable | Défaut | Ce qu'elle décide | Ce qui casse |
|---|---|---|---|
| `ARAC_ENV_FILE` | le coffre d'`ops/`, résolu en **cinq rangs** — voir juste sous ce tableau | où `ops/` lit les secrets | pointé au mauvais endroit → tous les scripts de `ops/` se croient sans configuration. **Dès qu'il y a deux cerveaux**, `ops/` ne devine pas mais il **choisit** — celui que votre clone décrit — et il l'annonce ; il ne s'arrête que si ce choix n'est pas évident. La poser vous-même reste le bon réflexe : c'est la seule façon de ne pas dépendre du dossier d'où vous tapez |
| `ARAC_BACKUP_DIR` | `/var/backups/arac/<base>` | où atterrissent les dumps | doit exister en `0700` ; sinon la sauvegarde échoue. **Le `<base>` n'est pas décoratif** : `/var/backups/arac` est commun à la machine, et deux cerveaux qui y déposent leurs dumps se mêlent — puis se font effacer par la rotation de l'autre |
| `ARAC_BACKUP_STATE` | `/var/lib/arac/<base>/backup` | reçus, preuves, registres | perdu → le chien de garde ne sait plus quand la dernière preuve a été faite |
| `ARAC_BACKUP_DSN` | `DATABASE_URL_BACKUP`, sinon `_ADMIN` | avec quel rôle on dumpe | ADMIN = un automate a le pouvoir de détruire le schéma |
| `ARAC_BACKUP_RETENTION_DAYS` | `7` si vous appelez `ops/backup.sh` à la main — mais **`14` en service** : l'unité posée par le bootstrap la fixe depuis `ARAC_BACKUP_RETENTION` (`systemctl cat arac-<base>-sauvegarde.service \| grep RETENTION`) | rétention locale | trop court = une corruption découverte tard n'a plus d'antécédent sain |
| `ARAC_BACKUP_KEEP_MIN` | `3` | dumps gardés **quoi qu'il arrive** | à `0`, une rétention mal réglée peut tout effacer |
| `ARAC_BACKUP_RECIPIENTS` | `/etc/arac/<base>/backup-recipients.txt` **s'il existe**, sinon vide | clés publiques `age` → chiffrement au repos | vide = vos dumps sont **en clair** sur le disque. Un chemin **commun à la machine** est pire encore : le dernier cerveau qui l'écrit décide pour qui les dumps des autres sont chiffrés, et cela ne se découvre qu'à la restauration |
| `ARAC_BACKUP_CLEAR_LOCAL` | `1` | garder aussi le dump en clair | à `1` avec chiffrement activé, l'intérêt du chiffrement disparaît |
| `ARAC_BACKUP_IDENTITY` | *(vide)* | clé privée `age`, pour restaurer | **ne doit pas vivre sur le serveur** que vous sauvegardez |
| `ARAC_OFFSITE_DEST` | *(vide)* | `utilisateur@machine` de la copie hors site | vide = vos sauvegardes disparaîtront avec le serveur qui les héberge |
| `ARAC_RESTORE_TEMPLATE_DB` | `<base>_restore_template` — il **porte le nom de votre cerveau** | le gabarit qui évite de demander les pleins pouvoirs | absent → `restore_verify.sh` ne peut pas travailler. Lui donner un nom **commun à la machine** (`arac_restore_template`) est le début de l'accident habituel : le SQL du gabarit commence par un `DROP DATABASE`, et deux cerveaux qui partagent ce nom se le détruisent l'un l'autre |
| `ARAC_RESTORE_FRESHNESS_H` | `26` | retard toléré du dump sur le vivant | trop grand = un dump périmé passe pour frais |

### `ARAC_ENV_FILE` — les cinq rangs, et lequel s'applique à vous

C'est la seule ligne du dépôt qui décide, pour **toutes** les commandes d'`ops/`, à quel
cerveau elles vont s'adresser : `ops/backup.sh` dumpe la base qu'elle désigne, la rotation
efface les dumps du dossier qu'elle désigne, `ops/restore_verify.sh` restaure ce qu'elle
désigne. La règle est écrite en toutes lettres au-dessus du code, dans `ops/env.sh`, et
elle tient en une phrase : **on n'agit jamais sur un cerveau que personne n'a nommé.**

| | Situation | Ce que `ops/` fait |
|---|---|---|
| 1 | `ARAC_ENV_FILE` est posée | il obéit, **sans un mot**. C'est une désignation, et une désignation ne se commente pas. C'est le rang des unités systemd, qui portent `Environment=ARAC_ENV_FILE=…` : sous systemd, rien n'est jamais imprimé |
| 2 | `$ARAC_HOME/.env` est lisible | il le prend, **sans un mot** — un dépôt n'a qu'un `.env` |
| 3 | un seul coffre sur la machine | il le prend, **sans un mot**… sauf si votre clone décrit un **autre** cerveau : ce n'est pas une ambiguïté, c'est un désaccord, et il **s'arrête** |
| 4 | plusieurs coffres, et ce clone en décrit un qui existe | il le prend **et il le dit**, sur la sortie d'erreur, avant le premier geste |
| 5 | tout le reste | **arrêt avant tout geste**, code 1, avec la raison exacte et la liste des coffres prêts à recopier |

Le rang 4 est celui qui surprend, parce qu'une version antérieure de ce produit
**refusait** ici, et que sept pages de ce manuel l'ont promis plus longtemps que le code
ne l'a tenu. Voici ce qu'il imprime, tel quel — les noms de cerveaux sont les vôtres :

```
ops/ sert le cerveau « <votre_base> » — ce dépôt le décrit, il n'a pas été deviné.
    coffre      /etc/arac/<votre_base>/arac.env
    preuve      /opt/<votre_base>/config/brain.toml nomme « <votre_base> »
    candidats   2 coffres sous /etc/arac
Pour en servir un AUTRE, nommez-le — c'est la seule façon de ne pas dépendre
du dossier d'où vous tapez :
    sudo ARAC_ENV_FILE=/etc/arac/<base>/arac.env <votre commande>
```

Et voici le rang 5, qui **arrête le script appelant** — pas trois écrans plus loin, sous
un message qui n'aurait plus rien à voir avec la cause :

```
ARRÊT AVANT TOUT GESTE — 2 cerveaux sont installés sous /etc/arac, et ce dépôt n'en décrit
aucun (config/brain.toml absent ou illisible).
Aucun cerveau n'est choisi à votre place : nommez celui que vous visez.
Ceux que cette machine porte, tels quels :
    ARAC_ENV_FILE=/etc/arac/<votre_base>/arac.env
    ARAC_ENV_FILE=/etc/arac/<base_du_voisin>/arac.env
Puis relancez, la variable devant la commande :
    sudo ARAC_ENV_FILE=… <votre commande>
```

**Ce que ce changement veut dire pour vous.** Le refus d'autrefois n'a jamais été tenu
pour de bon — le socle refusait le DSN, puis dérivait du **même** `config/brain.toml` le
dossier de dumps, le préfixe de rotation et l'étiquette du journal : il disait « je ne
choisis pas » en choisissant tout le reste. Ce qui manquait n'était pas le rattachement,
c'était de le **dire**. Un clone par cerveau (§12.d de
[`INSTALLATION.md`](INSTALLATION.md)) rend le rang 4 exact ; **un clone partagé par deux
cerveaux le rend faux**, et c'est alors la variable, posée à la main, qui décide.

**Choisissez-en un.** Faire tourner les deux, c'est doubler la charge et se retrouver
avec deux séries de dumps dont aucune n'est vérifiée. `ops/` est le plus complet ;
[`SAUVEGARDE.md`](SAUVEGARDE.md) le décrit entièrement.

---

## 10. Les alertes

Quatre alarmes, et c'est délibéré : une liste d'alarmes qu'on finit par ignorer ne
protège plus rien, elle apprend juste à ignorer les alarmes. Chacune est une
**conjonction**, pas un seuil isolé.

| Variable | Défaut | Ce qu'elle décide |
|---|---|---|
| `ARAC_ALERT_CMD` | *(vide)* | **comment un humain est prévenu.** Vide = personne n'est prévenu de rien. |
| `ARAC_ALERT_STALL_HOURS` | `48` | au bout de combien d'heures sans atome l'alarme « le cerveau a cessé d'apprendre » se déclenche — **et seulement si la file n'est pas vide** |
| `ARAC_WD_*` | voir `ops/watchdog.sh --explain` | les seuils du chien de garde de sauvegarde |

La seconde condition de la première alarme (« la file n'est pas vide ») est ce qui
distingue une panne d'un week-end. Sans elle, l'alarme sonnerait chaque fois que vous ne
travaillez pas. Quand la file est vide, le script dit « le cerveau se repose » et **ne
lève rien**.

Si vous digérez une fois par jour, montez `ARAC_ALERT_STALL_HOURS` à 72 ou 96.

**Les seuils de santé ne se règlent pas ici.** `scripts/ops/health_check.py` n'invente
aucun seuil : il **lit** le registre du cockpit, qui sert 148 métriques avec leur
définition, leur formule, leur requête de preuve et — pour 54 d'entre elles — leurs
seuils. Écrire un second jeu de seuils créerait deux vérités : le tableau de bord dirait
« ça va » pendant que la sonde crie. Vous ajustez à un seul endroit.

Détail complet : [`EXPLOITATION.md`](EXPLOITATION.md).

---

## 11. Telegram — facultatif

```
# TELEGRAM_BOT_TOKEN=
# TELEGRAM_ALLOWED_CHAT_IDS=
```

Le pont qui vous permet de parler aux agents depuis votre téléphone. Sans ces variables,
le service ne démarre simplement pas : rien d'autre n'est affecté.

`TELEGRAM_ALLOWED_CHAT_IDS` n'est pas optionnel si vous activez le pont : sans liste
blanche, n'importe qui ayant trouvé votre bot parle à votre cerveau.

---

## 12. Les drapeaux de comportement

```
# ARAC_PACK_SOURCE_FAIR=0
# ARAC_PACK_DROP_EMPTY=0
# ARAC_DISPOSE_COVERAGE_V2=0
# ARAC_VALUE_GATE_SHADOW=0
```

Ils changent ce que le cerveau **fait** sans changer une ligne de code. C'est pratique et
c'est dangereux : deux installations avec le même code et des drapeaux différents ne se
comportent pas pareil, et le diagnostic devient impossible.

**N'y touchez pas au début.** Quand vous en armerez un, notez-le quelque part : dans six
mois, vous chercherez pourquoi votre cerveau ne se comporte pas comme la documentation.

La suite de tests les neutralise explicitement — sinon un `source .env` avant
`make test` suffisait à faire rougir le gate sans qu'une seule ligne ait bougé.

---

## 13. La taxonomie

`config/scopes.toml` est **la** source de vérité de la forme de votre mémoire. Après
toute modification :

```bash
sudo ./bootstrap/bootstrap.sh --scopes-only
# ou, sans toucher à la base :
make scopes
```

Cela régénère `app/schemas/scope_generated.py` (l'énumération opposable côté Python) et
`db/seeds/scopes.sql`, puis peuple `arac.scopes`.

| Réglage | Défaut | Ce qu'il fait | Ce qui casse |
|---|---|---|---|
| `taxonomy.max_depth` | `2` | profondeur d'un chemin de domaine (`racine/feuille`) | au-delà de 2, le rappel se dilue : chaque niveau supplémentaire multiplie les catégories jumelles |
| `taxonomy.label_language` | `fr` | la langue des libellés | affichage seulement |
| `[[root]]` | — | un **monde** de votre vie : quelque chose dont vous parlez sans jamais confondre | une racine sans feuille est refusée par le générateur |
| `[[leaf]]` | — | un **rangement**. C'est là que vivent les atomes. | — |

**Les trois règles :**

1. **Les atomes vivent sur les feuilles.** Un atome posé sur une racine existe en base,
   reste rappelable par similarité pure, et devient pourtant orphelin : hors de l'état
   courant, hors de la vue des scopes, hors de la couverture — et hors d'atteinte de toute
   recherche qui précise un domaine. Près d'un souvenir actif sur onze du cerveau de
   référence est tombé dedans. Le contrôle a posteriori les compte et vous les montre.
2. **Un domaine ne s'invente pas à la volée.** Hors liste = refusé par l'API (422) et
   par la base (clé étrangère).
3. **Le bootstrap refuse de retirer un domaine encore habité** — « *Retrait refusé — du
   savoir vivant deviendrait orphelin* », et il nomme chaque domaine avec son nombre de
   souvenirs. Il vous dit lesquels et vous laisse décider : c'est un garde-fou, pas une
   limitation, parce qu'un domaine supprimé emporte le savoir qu'il contenait.
   **Le geste qui porte cette garde est `sudo ./bootstrap/bootstrap.sh --scopes-only`**,
   qui interroge votre base avant de régénérer. `python3 bootstrap/generate_scopes.py`
   appelé seul, lui, ne voit aucune base : il régénère sans un mot, sauf si vous lui
   donnez `--dsn`. Passez par le bootstrap — c'est le chemin que
   [`DEPANNAGE.md` §16](DEPANNAGE.md) prescrit.

**Ordres de grandeur observés** : un cerveau actif accumule ~150 atomes par mois. Une
feuille qui n'atteint pas 10 atomes en six mois n'aurait pas dû exister ; une feuille qui
dépasse 250 atomes gagnerait à être scindée.

---

## 14. Le bootstrap lui-même

Options : `--dry-run`, `--yes`, `--from ÉTAPE`, `--only ÉTAPE`, `--scopes-only`,
`--rejouer`, `--check`, `--verify`, `--etapes`, `--bavard`, `--no-color`, `--help`,
`--version`.

| Variable | Défaut | Ce qu'elle décide |
|---|---|---|
| `ARAC_ETC` | `/etc/arac/$ARAC_DB` | le dossier des secrets |
| `ARAC_ENV_FILE` | `$ARAC_ETC/arac.env` | le fichier d'environnement de production |
| `ARAC_ETAT` | `$ARAC_HOME/.bootstrap-install.state` | le fichier d'avancement — ce qui rend le bootstrap reprenable |
| `NO_COLOR` | *(non posée)* | sortie sans couleurs (respecte la convention usuelle) |

Un exemple qui résume la philosophie — un deuxième cerveau, sur d'autres ports :

```bash
sudo ARAC_API_PORT=8010 ARAC_COCKPIT_PORT=8110 ./bootstrap/bootstrap.sh
```

---

## Changer un réglage sans casser quelque chose

**La méthode, en quatre gestes :**

```bash
# 1. voir la valeur actuelle
sudo grep '^LA_VARIABLE=' /etc/arac/<votre_base>/arac.env

# 2. la changer (jamais par un éditeur qui laisse un fichier temporaire lisible)
sudo install -m 600 -o root -g root /dev/null /tmp/x && sudo nano /etc/arac/<votre_base>/arac.env

# 3. redémarrer ce qui la lit — et RIEN d'autre
sudo systemctl restart arac-<votre_base>-api

# 4. vérifier que le cerveau est toujours sain
sudo ./bootstrap/checks/verify_install.sh
```

**Les réglages qu'on ne change pas après coup**, et pourquoi :

| Réglage | Pourquoi |
|---|---|
| le modèle ou la dimension des embeddings | tous les vecteurs existants deviennent incomparables — dégradation **silencieuse** du rappel |
| le format de `source_ref` | 76 % de la provenance perdue sur le cerveau de référence, pour cette raison exacte |
| `source.node_id` | scinde la provenance en deux populations et envoie les cycles en quarantaine |
| `brain.name` | la base et les unités portent l'ancien nom ; plus rien ne se retrouve |

`ARAC_SCHEMA` ne figure pas dans ce tableau : ce n'est pas un réglage qu'on évite de
changer après coup, c'est un réglage qui **n'existe pas** — le bootstrap le refuse dès le
départ, parce que les migrations nomment le schéma en toutes lettres. Voir l'encadré du §3.

**Les réglages qu'on peut changer à tout moment** : `ARAC_CYCLES`, `ARAC_CYCLE_TZ`,
`ARAC_PACK_TOKEN_BUDGET`, `ARAC_PACK_MAX_CONVS`, `ARAC_CURATOR_MODEL`,
`ARAC_ALLOW_PAID_AI`, `LOG_LEVEL`, `ARAC_ALERT_*`, `ARAC_BACKUP_*`, les ports, et
l'ajout d'un `ARAC_NODE_TOKEN_…` pour un nouveau poste.

**Ajouter un domaine** est facile ; en retirer un ne l'est pas. Ajoutez généreusement,
retirez avec précaution.
