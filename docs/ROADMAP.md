# Feuille de route — ce qui manque, et dans quel ordre

Ce document n'est pas un palmarès. C'est la liste de ce que ce framework **ne fait pas
encore**, de ce qu'il fait **mal**, et de ce qu'il fait **sans qu'on l'ait jamais
vérifié**. Il est écrit pour que vous décidiez en connaissance de cause avant d'installer,
pas pour que vous le découvriez au troisième mois.

Les mesures citées viennent d'**une seule** installation — le cerveau qui a servi de
référence à ce dépôt. Ce sont des observations, pas des lois.

---

## Comment lire les statuts

| Statut | Ce que ça veut dire |
|---|---|
| **prouvé** | exécuté, observé, et le résultat est reproductible |
| **écrit, non exercé** | le code existe, il est testé unitairement, **il n'a jamais tourné en conditions réelles** |
| **absent** | rien ne le produit. Le squelette existe parfois ; il n'est branché à rien |
| **faux** | le système affirme quelque chose d'inexact. C'est le pire des quatre |

---

## 1. Ce qui bloque aujourd'hui

### 1.1 Le double vocabulaire bootstrap ↔ moteur — **ponté, pas résolu**

**Statut : pont posé par le bootstrap. La dette de fond reste entière.**

`bootstrap/bootstrap.sh` écrit ses variables sous des noms préfixés
(`ARAC_DB_URL_APP`, `ARAC_EMBEDDINGS_API_KEY`, `ARAC_CC_SESSION_SECRET`…) ; le moteur
extrait de la source lit encore les noms historiques (`DATABASE_URL_APP`,
`OPENAI_API_KEY`, `CC_SESSION_SECRET`…). Cela faisait, après un bootstrap réussi, une API
qui démarrait puis s'arrêtait sur `DATABASE_URL_APP non définie` — et un installateur qui
se déclarait terminé alors qu'il exigeait encore un geste.

Le pont est désormais posé par le bootstrap lui-même, à la fin de son étape des clés
(`poser_pont_de_vocabulaire`, `bootstrap/lib/secrets.sh`) : il **copie** chaque variable
sous l'autre nom, si bien que les deux cohabitent dans le fichier d'environnement. On le
constate d'une commande : `sudo grep -c '^DATABASE_URL_' /etc/arac/<votre_base>/arac.env`
rend `4`.

**Ce n'est pas la résolution, c'est un pont** — et un pont qu'on n'enlève jamais devient
une pièce d'architecture. **Ce qu'il reste à faire :** choisir **un** vocabulaire et le
faire descendre partout. Le
préfixé (`ARAC_*`) est le bon candidat : il ne collisionne avec rien sur un serveur
partagé, et il rend un `env | grep ARAC_` exhaustif. Le jour où ce sera fait,
`poser_pont_de_vocabulaire()` doit disparaître, pas rester.

### 1.2 L'installation est rejouée et reproductible ; aucun cerveau posé par le bootstrap n'a encore vécu

**Statut : exercé pour la pose. Exercé pour l'usage aussi — mais sur un seul corpus, et
sur un cerveau que le bootstrap n'a pas posé.**

Le bootstrap a été mené **deux fois de bout en bout**, depuis une base absolument vide,
avec **deux taxonomies différentes** (trois domaines chacune, mais aucun domaine en
commun), sur Ubuntu 24.04 / PostgreSQL 16.13 / pgvector 0.8.2. Ont donc bien tourné :
`CREATE DATABASE`, les rôles du cerveau, `CREATE EXTENSION vector`, `alembic upgrade head`
jusqu'à la tête des migrations, l'écriture des secrets, `systemctl enable --now`, et le
contrôle a posteriori — `en échec 0` les deux fois.

**Le critère est l'identité des deux schémas, l'identité des installations mise à part**,
et pas leur taille : un compte d'objets périme à la migration suivante, une égalité non.
Le bootstrap grave dans le commentaire du schéma une plaque — `cerveau=`, `empreinte=`,
`poste=` — que `pg_dump` emporte **exprès** : c'est ce qui permet à un dump de dire de
quel cerveau il vient. Elle doit donc différer, et le contrôle la traite comme telle.

**La commande de référence est au [§7c du `README`](../README.md#c-ce-qui-est-éprouvé-sur-quoi-et-ce-qui-nest-pas)**,
en deux temps : le schéma identique une fois l'identité neutralisée des deux côtés, puis
l'identité qui, elle, diffère. Elle n'est pas recopiée ici — **une commande recopiée en
deux endroits est une commande qui divergera**, et c'est cette page-ci qui a porté
pendant une version la variante devenue fausse.

Ce qui reste ouvert dans F4 : le rejeu depuis un Ubuntu **nu** — la machine d'essai
portait déjà PostgreSQL et pgvector — et l'installation **complète** en interactif de bout
en bout, dont seule l'étape des secrets a été menée à la main.

**La connexion au cockpit, elle, n'est plus ouverte** : mot de passe tapé aux invites
`getpass` derrière un vrai pseudo-terminal, appairage TOTP, puis `POST /cc/login` avec ce
mot de passe et un code calculé depuis le secret appairé → `303 See Other` vers `/cc/`,
session posée, `GET /cc/` et `GET /cc/v1/atoms` à `200`, mot de passe faux à `401`. Mesuré
le 9 août 2026 ([`INSTALLATION.md` § 12.g](INSTALLATION.md)), remesuré depuis sur un
cerveau né du chemin réel, et rejoué par `make acceptance` à son étape 7, à chaque
passage. Ce qui reste, sur ce point précis, tient en une ligne : le code TOTP a toujours
été **calculé depuis le secret**, jamais **lu sur un téléphone**.

> **▸ Cette phrase-ci a survécu une version de trop, et il faut dire pourquoi.** Elle
> disait « personne ne s'est jamais connecté au cockpit avec un mot de passe tapé et un
> code TOTP » pendant que trois autres pages du même dépôt décrivaient cette connexion,
> datée et mesurée — et que le juge la rejouait à chaque passage. Aucun garde ne pouvait
> l'attraper : `tests/test_la_doc_dit_vrai.py` interdit de déclarer « jamais exercée »
> une commande d'une liste de quatre motifs (`CREATE DATABASE`, `alembic upgrade head`,
> `systemctl enable --now`, `bootstrap.sh en réel`), et une connexion au cockpit n'en
> fait pas partie. **Allonger la liste ne réglerait pas le fond** : ce qu'il faudrait
> savoir voir, c'est deux sections d'honnêteté du même dépôt qui parlent du même geste et
> se contredisent. Aucun test ne le fait aujourd'hui, et c'est le vrai manque.

**Ce qui reste ouvert au-delà de F4, et qui compte davantage.** Cette section a longtemps
écrit ici que « aucune conversation n'a jamais été ingérée » et que toutes les bases
portaient zéro atome. C'était faux, et il y avait de quoi s'en apercevoir sans quitter ce
document : le §2.4 ci-dessous cite des taux de confiance et de couverture qu'aucun cerveau
vide ne saurait produire. Deux objets étaient confondus — **le cerveau de référence**, qui
a vécu huit mois, et **les cerveaux d'essai**, que le bootstrap pose vides. La distinction
est tenue, avec le reçu de cycle qui la prouve, au §7c du
[`README`](../README.md#c-ce-qui-est-éprouvé-sur-quoi-et-ce-qui-ne-lest-pas) ; c'est
**là** qu'elle est à jour, et cette page ne fait qu'en tirer la conséquence pour la
feuille de route.

Restent donc ouverts, en propre — et chacun est **tenu**, avec son rejeu, dans
[`docs/LIMITES-CONNUES.md`](LIMITES-CONNUES.md), seul endroit où vit une limite
assumée. Cette page n'en tire que la conséquence pour la feuille de route :

- **le chemin *installation neuve → première conversation → premier atome*.** Il n'a pas
  été parcouru d'un bout à l'autre : les cerveaux que le bootstrap pose sont vides, parce
  que la digestion réclame le binaire de curation, son authentification sous le compte
  d'agent et les deux interrupteurs de dépense — qu'un essai gratuit n'arme pas ;
- **le rappel sur un corpus construit par quelqu'un d'autre.** Toutes les mesures citées
  ici viennent d'une seule installation, celle de l'auteur. Une installation ne fait pas
  une loi ;
- **la sauvegarde *chiffrée* et la copie hors site.** Le §7 étape 2 de
  [`SAUVEGARDE.md`](SAUVEGARDE.md) (`age -d`) et la copie sur une seconde machine n'ont
  jamais été joués : ils demandent une clé et une machine que les essais n'ont pas eues.

> **▸ Cette liste a porté une version de trop « la restauration d'une sauvegarde, qui n'a
> pas été rejouée sur une base de service ».** C'était faux, et c'était la pire place où
> l'écrire : la page qu'on lit **pour décider avant d'installer**, sous le statut que son
> propre tableau range comme « le pire des quatre ». Quatre pages du même dépôt disaient
> déjà l'inverse — [`GOAL.md`](../GOAL.md) (ligne « Sauvegardes »), le §7c du
> [`README`](../README.md#c-ce-qui-est-éprouvé-sur-quoi-et-ce-qui-nest-pas), le
> « Éprouvé depuis, sur des cerveaux réels » d'[`INSTALLATION.md`](INSTALLATION.md), et
> le §7 de [`SAUVEGARDE.md`](SAUVEGARDE.md) — et le juge la rejouait à chaque passage.
> C'est la même mécanique à deux listes que cette section vient de payer quelques
> paragraphes plus haut sur la connexion au cockpit : une copie jamais relue.

**La restauration n'est plus ouverte, et voici de quoi le démentir.** *Mesuré le 10 août
2026*, sur le cerveau de banc que le juge pose et démonte lui-même — grappe et ports
choisis par lui au-dessus de ses planchers (ce jour-là : PostgreSQL 5461, API 8211) —, en
comptant les restaurations d'un passage complet :

```bash
sudo make acceptance 2>&1 | grep -cE '✓ (restauration|bascule §7\.3)'
```

*(Rien à écrire nulle part : le juge garde son propre journal complet et en imprime le
chemin — nommé d'après le cerveau d'essai — à sa dernière ligne.)*

**Critère** — et c'est lui qui survivra au chiffre : les **trois** preuves que compte
cette commande sont de *trois natures différentes*, et chacune doit rester présente. (Le
passage en joue d'autres au passage — la restauration `--keep` qu'on inspecte, le refus de
viser la base d'un voisin — mais ces trois-là sont celles qui décident.)

| Où | Ce qui est restauré | Ligne à voir |
|---|---|---|
| étape 3 | le dump que le bootstrap vient d'armer, par **son unité** `arac-<base>-restauration.service` | `✓ restauration … dans une base jetable` |
| étape 8 | le dump de l'unité, **restauré et comparé** au cerveau vivant, sans superutilisateur | `✓ restauration … RESTAURÉ et COMPARÉ` |
| étape 8 | la **bascule du §7** sur un cerveau cassé pour de vrai (`DROP SCHEMA arac CASCADE`), relu ensuite **sous le rôle de l'application** | `✓ bascule §7.3 … comme avant la casse` |

Obtenu ce jour-là : `3`, l'étape 8 conclut `PROUVÉ`, aucune ligne `✗`, et le rapport final
rend `0 en échec · 0 intervention(s)`. Le jour où la commande rend moins de trois, ou
qu'une des trois lignes manque, **c'est ce paragraphe qui a tort** — pas le juge.

Un cerveau qui se pose parfaitement et que personne n'a encore nourri n'est pas un
cerveau : c'est une installation.

### 1.3 Le premier jour n'a jamais été vécu — **F8 ouvert**

**Statut : absent.**

Aucune personne extérieure au projet n'a installé ce framework en suivant la seule
documentation. Tant que ce n'est pas fait, la promesse centrale du dépôt — *« un inconnu
réussit seul »* — reste une hypothèse.

C'est la contribution la plus utile qu'on puisse apporter aujourd'hui. Voir
[`CONTRIBUER.md`](CONTRIBUER.md).

### 1.4 Le pont n'a pas été exercé sur un Mac

**Statut : écrit, non exercé.**

`mac/arac-sync.py` et `mac/arac-pont.sh` sont validés sur Linux contre un serveur
d'ingestion simulé. `launchctl`, `plutil`, les notifications macOS et l'emplacement réel
des données n'ont jamais été éprouvés sur la machine à laquelle ils sont destinés.

---

## 2. Les quatre dettes mesurées

Ce sont les défauts observés sur le cerveau de référence. Ils ne bloquent pas
l'installation ; ils limitent ce que le cerveau sait faire.

### 2.1 Les liens entre atomes — le moteur les écrit, personne ne les lit

**Statut : produits à chaque cycle, servis nulle part.**

La migration `0033_atom_links` **fait partie de la chaîne** qu'`alembic upgrade head`
applique — l'étape 5 du bootstrap l'exécute, la table existe donc sur toute installation
neuve.

> **Ce document ne dit ni laquelle est la tête de la chaîne, ni combien elle compte de
> révisions.** Ces deux valeurs périment à chaque migration ajoutée, et elles l'ont fait :
> « la tête est `0033` » était écrit ici même, puis `0034_memory_review_queue` est arrivé.
> Le compte du jour, c'est le bootstrap qui l'annonce à l'écran, à l'étape 5 — « *N*
> migration(s) trouvée(s) ». C'est cette ligne-là qui fait foi ; un nombre recopié dans un
> document ne fait foi que jusqu'à la migration suivante. Et `agents/cortex/cycle.py` appelle
`app/services/atom_links.recompute()` à chaque cycle — avant le garde-dépense, donc même
quand l'IA payante est coupée. Elle se remplit de trois natures d'arêtes :

| Arête | D'où elle vient | Ce qu'elle vaut |
|---|---|---|
| `supersedes` | la colonne `superseded_by` | certaine — c'est un fait de la base |
| `same_thread` | chaîne chronologique dans une même provenance | certaine — déterministe |
| `semantic_neighbor` | mutual-kNN sur les embeddings, seuil θ = 0,25 | **inférée** — une ressemblance, pas un lien de sens |

**Ce qui manque, et c'est là tout le chantier : personne ne lit ces arêtes.** Ni
`/v1/atoms/recall`, ni `/v1/atoms/context_for`, ni `/v1/atoms/resume` — la fonction
d'enrichissement `app/services/atom_links.enrich_resume()` existe et n'a aucun appelant
dans le dépôt (`grep -rn enrich_resume --include='*.py' .`). Le cockpit ne les lit pas
davantage, et le déclare panneau par panneau.

**Ce qui a déjà été réparé, et qui est la leçon la plus transportable de ce dépôt :** le
cockpit affirmait, en dur et sans condition, « la table `arac.atom_links` n'existe pas
(migration 0033 non appliquée) ». C'était l'état d'**une** base gravé dans le code et
resservi à tout le monde — un message faux chez quiconque avait suivi l'installation. Les
panneaux constatent désormais en base (`to_regclass('arac.atom_links')`) et distinguent
deux nouvelles très différentes : « la table est absente » et « la table est là, mais ce
panneau ne la lit pas ». On peut le vérifier :

```bash
grep -rn "0033 non appliquée" control_center/    # ne rend plus rien
```

> **La leçon générale**, et elle vaut au-delà de ce cas : une indisponibilité codée en dur
> est une mesure comme une autre — elle doit venir de la base, pas d'une constante. Un
> « indisponible » qui ment est aussi grave qu'un zéro qui ment.

### 2.2 La détection de contradictions — le juge existe, personne ne l'appelle

**Statut : absent.**

Le vocabulaire est là : `contradiction` est une nature d'atome reconnue par le schéma,
et `agents/curator/gate.py` sait rendre le verdict `DISPUTED` — *« contradiction :
visible, non promue »* — avec sa place exacte dans l'ordre de priorité :

```
source tronquée > métadonnées manquantes > LLM indisponible > contradiction > promotion
```

Mais le paramètre `contradiction=` de `evaluate()` et d'`apply_gate()` **n'est passé par
aucun appelant du dépôt** :

```bash
grep -rn "apply_gate" --include='*.py' .   # → gate.py (définition) et tests/ uniquement
```

Autrement dit : **rien ne détecte une contradiction, donc rien n'en produit jamais.** Un
cerveau qui apprend « la base tourne en 16.13 » puis « la base tourne en 17.2 » garde les
deux, actifs, côte à côte, sans rien signaler.

**Ce qu'il faut construire**, dans cet ordre :

1. un détecteur — le candidat naturel est le voisinage sémantique déjà calculé
   (`semantic_neighbor`) restreint aux atomes de même clé ou de même scope ;
2. le branchement du gate sur son verdict ;
3. l'affichage : un atome contesté doit être **visible et non promu**, pas supprimé.
   Le modèle est le remplacement (`superseded_by`), qui garde la trace.

C'est le chantier fonctionnel le plus important de cette feuille de route. Une mémoire
qui ne sait pas se contredire ne vieillit pas : elle se périme.

### 2.3 La provenance — 76 % perdue

**Statut : dette historique, irrécupérable en amont, évitable en aval.**

Sur le cerveau de référence, **76 % des atomes ne peuvent plus être reliés à la
conversation dont ils sont nés.** La cause n'est ni une panne ni une perte de données :
un **changement de format de `source_ref`** en cours de route. Les atomes écrits avant
portent une clé que le code d'après ne sait plus lire.

Le cockpit sait le dire honnêtement — `lifestory.py` distingue trois cas : provenance
déclarée, provenance héritée (`curator_raw_id`), aucune provenance — mais il ne peut pas
la reconstruire.

**Ce qu'il faut faire :**

- **figer le format** et le déclarer contractuel, au même titre qu'un schéma d'API ;
- ajouter un contrôle qui **refuse d'écrire un atome sans `conversation_uid`** — le gate
  sait déjà rendre `BLOCKED` sur `missing_provenance`, il suffit de l'armer ;
- exposer le taux de provenance comme une constante vitale, pas comme une métrique
  d'information. Un effondrement doit réveiller quelqu'un le jour où il se produit, pas
  au bout de deux ans.

> **Si vous ne retenez qu'une chose de ce document :** ne renommez jamais une clé de
> `source_ref`. Ajoutez-en une. C'est la seule structure qui relie ce que le cerveau sait
> à l'endroit où il l'a appris.

### 2.4 Le rappel doute — 96 % en confiance basse, 98 % jamais audité

**Statut : mécanisme partiel.**

Trois mesures qui racontent la même histoire :

| Mesure | Ce qu'elle dit |
|---|---|
| **96 %** des rappels rendus en confiance basse | le rappel trouve, mais il n'ose pas |
| **98 %** du savoir jamais audité | le cerveau est sûr de choses que personne n'a relues |
| **près d'un atome actif sur onze** posé sur une racine nue | hors de l'état courant, de la vue des scopes et de la couverture — silencieusement |

Ce qui manque, concrètement :

- **la boucle de validation.** Un atome naît `agent_suggest` ; il ne devient
  `auditor_validated` que si un humain le confirme. Le cockpit sait montrer les candidats,
  mais **la validation n'est pas branchée** — et le cockpit est en lecture stricte par
  conception, donc l'écriture devra passer ailleurs. C'est un choix d'architecture à
  faire, pas un bouton à ajouter ;
- **le mécanisme de vérification.** `last_verified_at` et `confirmed_until` existent en
  base et sont `NULL` sur la totalité des atomes. Rien ne les alimente. Tant que c'est le
  cas, un savoir de deux ans et un savoir d'hier se ressemblent ;
- **la garde contre les atomes sur racines.** La règle est documentée partout ; **aucun
  contrôle ne l'applique.** Une contrainte `CHECK (scope LIKE '%/%')` sur les atomes
  actifs coûterait une migration et supprimerait définitivement le piège n° 1.

Cette dernière est le meilleur rapport effort/valeur de toute la feuille de route.

---

## 3. Deux vocabulaires de sauvegarde

**Statut : les deux fonctionnent, ils ne se connaissent pas.**

`ops/` (dumps chiffrés, restauration prouvée, chien de garde) lit `$ARAC_HOME/.env` et
`DATABASE_URL_*`. Le bootstrap engendre sa propre unité de sauvegarde, qui lit
`/etc/arac/<votre_base>/arac.env` et `ARAC_DB_URL_ADMIN`.

Choisissez-en un — [`SAUVEGARDE.md`](SAUVEGARDE.md) décrit le premier, plus complet. La
convergence attend la décision du point 1.1 : c'est le même problème de vocabulaire.

---

## 4. Les résidus d'origine

**Statut : cosmétique, mais visible.**

Des identifiants internes de l'installation d'origine subsistent dans les commentaires et
quelques valeurs par défaut d'`app/`, `agents/` et `control_center/` — un nom de
déploiement, des chemins de journaux, des renvois vers des spécifications absentes du
dépôt (`docs/RETRIEVAL.md`, `docs/RUNBOOK.md`).

Ils ne bloquent rien. Ils trahissent que le portage n'est pas fini, et ils envoient le
lecteur vers des documents qui n'existent pas. À nettoyer au fil des modifications
plutôt qu'en une passe : une réécriture massive de commentaires rend illisible tout
l'historique du dépôt.

---

## 5. L'ordre dans lequel tout cela devrait être fait

Par ordre décroissant de valeur rendue à un nouvel utilisateur :

| # | Chantier | Pourquoi en premier |
|---|---|---|
| **1** | une installation à l'aveugle, racontée (§1.3) | tout le reste est de la conjecture tant que ce n'est pas fait |
| **2** | unifier le vocabulaire des variables (§1.1) | le pont tient, mais un pont provisoire vieillit mal |
| **3** | interdire les atomes sur racines (§2.4) | une migration, et le piège n° 1 disparaît pour tout le monde |
| **4** | rendre `source_ref` contractuelle (§2.3) | la dette la plus chère est celle qu'on ne peut pas rembourser |
| **5** | servir `atom_links` — au rappel et au cockpit (§2.1) | une couche entière est écrite à chaque cycle et n'est lue par personne |
| **6** | détecter les contradictions (§2.2) | le premier vrai saut de capacité |
| **7** | la boucle de validation humaine (§2.4) | ce qui fera passer la confiance de « basse » à « justifiée » |
| **8** | converger les sauvegardes (§3) | après 1, parce que c'est le même problème |

---

## 6. Ce qui ne sera pas fait

Ce n'est pas un manque de temps, c'est une décision de portée. La dire évite d'attendre
quelque chose qui n'arrivera pas :

- **le multi-utilisateur** — un cerveau, une personne ;
- **une interface web publique** — l'API et le cockpit écoutent sur `127.0.0.1`, le
  tunnel SSH est la seule porte depuis l'extérieur, et c'est ce qui permet de n'avoir ni
  TLS, ni reverse-proxy, ni pare-feu à régler. Cela ne veut pas dire qu'il n'y a rien à
  défendre : sur la machine elle-même, la porte est le **jeton**, exigé de toute
  requête, `127.0.0.1` compris (`app/auth.py`) ;
- **une application mobile** — un pont Telegram existe, il est facultatif ;
- **Docker** — `systemd` et un `venv` se diagnostiquent mieux à trois heures du matin ;
- **un mode gratuit** — les embeddings et la curation sont des services payants. Un
  framework qui prétendrait s'en passer mentirait sur ce qu'il est.

---

## 7. Comment cette feuille de route est tenue

Une ligne ne change de statut que lorsque **quelqu'un l'a exécutée**. « Écrit, non
exercé » ne devient « prouvé » ni par une relecture, ni par un test unitaire, ni par une
conviction : par une exécution réelle, racontée, avec ses frictions.

Si vous en franchissez une, dites-le — c'est exactement le genre de rapport que
[`CONTRIBUER.md`](CONTRIBUER.md) attend. Et si vous en trouvez une qui manque à cette
liste, elle y a sa place : **un défaut connu et écrit vaut infiniment mieux qu'un défaut
découvert par le troisième utilisateur.**

### 7.1 Les sections d'honnêteté — où elles sont, et pourquoi elles pourrissent

**Ce dépôt a corrigé une section d'honnêteté périmée à six reprises, dans six pages
différentes, et chaque fois en la découvrant par hasard.** Ce n'est pas de la malchance,
c'est une propriété de l'objet : une section d'honnêteté s'écrit **une fois**, dans un
moment de lucidité, et **personne ne la relit jamais** — parce qu'elle ne sert à rien
tant qu'on ne s'en méfie pas, et qu'elle rassure celui qui l'a écrite. Elle vieillit donc
dans les deux sens : le produit progresse et elle sous-estime ; le produit change et elle
surestime. **Sous-estimer trompe autant que surestimer**, et se lit au pire moment — par
quelqu'un qui vient de perdre sa base, ou qui s'apprête à rendre son serveur.

**La sixième l'a démontré dans le sens qu'on n'attendait pas.** Les cinq premières
promettaient trop. Celle-ci **effrayait** trop : trois pages annonçaient, sous le mot
« mesuré », que la route d'écriture de l'API versait le domaine, les étiquettes, la clé et
deux cents caractères du *pourquoi* de chaque décision dans un journal partagé — alors que
le produit avait été réparé entre-temps. C'était la raison la plus sérieuse de ne pas
installer, écrite dans la page qu'on lit avant d'installer, et elle était fausse. **Une
page qui exagère le danger n'est pas moins mensongère qu'une page qui le tait :** elle
fait renoncer, ou installer ailleurs, sur une mesure périmée.

Voici la liste, pour qu'elles cessent d'être invisibles. Elle se refait en une commande :

```bash
grep -rn -E "^#{2,4} .*(réellement exécuté|reste à vérifier|NON vérifié|éprouvé|ne fait pas|n'est pas fait)" \
  --include='*.md' . | grep -v '\.venv'
```

| Où | Ce qu'elle affirme | Comment on la rejoue |
|---|---|---|
| [`README.md` §7c](../README.md#c-ce-qui-est-éprouvé-sur-quoi-et-ce-qui-nest-pas) | le partage cerveau de référence / cerveaux d'essai, la reproductibilité, ce qui n'a pas eu lieu | les deux commandes du §7c, et les requêtes `psql` qu'il donne |
| `README.md`, encadré « mon meilleur ami » | l'état du mandat, en première page | il renvoie au §7c : c'est **là** qu'on mesure |
| [`INSTALLATION.md`](INSTALLATION.md) — « Ce qui a été réellement exécuté » | tout ce qui a tourné pour écrire la page d'installation | `make acceptance`, puis le §13 joué mot pour mot |
| [`DEMARRAGE-RAPIDE.md`](DEMARRAGE-RAPIDE.md) — idem | le chemin court | idem |
| [`DEPANNAGE.md`](DEPANNAGE.md) — idem | les commandes de diagnostic, sur une grappe jetable | rejouer les commandes citées, avec `-p` |
| [`EXPLOITATION.md`](EXPLOITATION.md) — idem | les cinq commandes du §1, deux fois de suite | les rejouer coup sur coup et comparer les verdicts |
| [`SAUVEGARDE.md` §8](SAUVEGARDE.md) — « Ce qui n'est pas fait » | pas de PITR, quatre dumps par jour | `systemctl cat arac-<base>-sauvegarde.timer \| grep OnCalendar` |
| [`PONT-MAC.md` §12](PONT-MAC.md) | la frontière exacte du pont | les commandes `grep` que la section donne elle-même |
| [`bootstrap/README.md`](../bootstrap/README.md) — « Ce qui a été éprouvé » | l'installation, les secrets en interactif | `bootstrap.sh --only secrets` derrière un pseudo-terminal |
| [`GOAL.md`](../GOAL.md) — le tableau F1…F8 | l'état assertion par assertion | chaque ligne porte sa méthode |
| [`INSTALLATION.md` §13](INSTALLATION.md) — « Le journal système » | ce que le produit écrit dans journald, et ce que le §13 ne peut pas effacer | écrire un souvenir par `POST /v1/atoms`, puis `journalctl -u "arac-$BASE-api.service" \| grep -i "<un mot à vous>"` |
| [`COMMENT-IL-SE-NOURRIT.md`](COMMENT-IL-SE-NOURRIT.md) — « Le journal système » | le tableau de ce qui va dans le journal et de ce qui n'y va pas | idem — **et c'est le §13 qui fait foi**, cette page-là y renvoie |
| **cette page**, §1.1 à §1.4 et §2 | ce qui bloque, ce qui est dû | chaque section porte sa commande |

> **La commande ci-dessus ne trouve pas les deux dernières lignes de ce tableau, et c'est
> précisément pour cela qu'elles ont pourri deux fois.** Une section d'honnêteté ne
> s'annonce pas toujours par « ce qui n'est pas fait » : celles-ci s'appellent « Le
> journal système » et ressemblent à de la documentation ordinaire. Un inventaire par
> **titre** attrape ce qui se déclare ; il rate ce qui rend un aveu sans en porter le nom.
> Elles sont ici à la main, faute de mieux — et ce « faute de mieux » est la dette nommée
> au bas de cette section.

**Quatre règles, tirées des six fois où l'une d'elles s'est trouvée en retard.**

1. **Aucun absolu.** « Jamais », « aucun », « personne » tombent au premier
   contre-exemple, et le contre-exemple arrive toujours. Écrivez ce qui a été fait, avec
   sa date, et ce qui ne l'a pas été — pas un absolu qui périme.
2. **Aucun instantané comme critère.** Ni un compte exact, ni une taille, ni un motif
   appris par cœur sur la ligne que le produit imprime aujourd'hui. Un critère doit
   survivre à l'amélioration suivante, sinon c'est une photographie. C'est la leçon du
   §1.2 : la preuve de reproductibilité du dépôt est devenue fausse **parce que le
   produit s'est amélioré ailleurs**, et elle l'est restée jusqu'à ce que quelqu'un
   rejoue la commande.
3. **Une commande plutôt qu'une phrase.** Une case cochée se périme ; un juge qui tourne,
   non. Chaque fois qu'une affirmation peut devenir une commande, elle le doit.
4. **Une mesure porte de quoi la démentir.** C'est la règle de la sixième fois, et elle
   vise le mot lui-même. « Mesuré » n'est pas un adjectif de qualité : c'est la
   revendication qu'un geste a eu lieu, à une date, sur un objet, avec un résultat. Écrit
   nu, il fait exactement l'inverse de ce qu'il promet — il transforme une information
   périmée en **fait certifié**, et il décourage précisément le lecteur qui aurait pu la
   corriger. Une mesure qui ne dit pas comment la refaire n'est pas une mesure : c'est une
   affirmation avec un mot de plus.

### Le patron d'une mesure qui vieillit honnêtement

Quatre éléments, et le quatrième est celui qu'on oublie toujours.

| | | Pourquoi |
|---|---|---|
| **QUAND** | une date | sans elle, personne ne peut savoir si la mesure a survécu au lot suivant — et « depuis » n'a pas de sens |
| **SUR QUOI** | l'objet, nommé | un cerveau de banc, une grappe, un clone : une mesure sans objet ne se rejoue pas |
| **COMMENT** | la commande, rejouable telle quelle | c'est elle qui rend le démenti moins cher que la croyance |
| **À QUOI ON RECONNAÎT** | un **critère**, pas un chiffre | un chiffre est une photographie ; `code 0`, `identique`, `rc=1 et rien`, `même md5` survivent à l'amélioration suivante |

En clair, la même mesure écrite des deux façons :

```
✗  « Mesuré : la route verse le domaine du souvenir dans journald. »
      → quand ? sur quoi ? comment le refaire ? à quoi verrait-on que c'est fini ?
      → et si c'est corrigé demain, la phrase reste vraie d'apparence pour toujours.

✓  « Mesuré le 10 août 2026 sur un cerveau de banc né du chemin réel, en écrivant un
     souvenir par POST /v1/atoms puis en cherchant un mot que personne d'autre n'avait
     écrit :

         sudo journalctl -u "arac-$BASE-api.service" --no-pager | grep -i "<un mot à vous>"

     Critère : aucune ligne, rc=1. Obtenu : aucune ligne, rc=1, sur seize motifs. »
      → un lecteur de 2027 rejoue la commande en dix secondes et sait, sans discuter.
```

**L'état du corpus, mesuré le 10 août 2026 — et le chiffre que cette section a elle-même
publié faux.** Elle a écrit ici « sur les **173** emplois de « mesuré » … **22** … **52**
… **5** … **104** », en donnant juste en dessous la commande qui refait le compte. Jouée
telle quelle **le jour même**, cette commande rendait **136** lignes. Pas 173. La section
qui légifère sur la mesure honnête portait donc, en son centre, le défaut exact qu'elle
définit — et elle fournissait elle-même de quoi s'en apercevoir, ce qui est le seul point
qui l'a sauvée. On ne remplace pas un chiffre faux par un chiffre juste qui périmera au
prochain lot : **on publie ce qui le recalcule.**

L'inventaire brut, une ligne par emploi — il montait à `141` le 10 août 2026 après ce lot,
et **ce nombre-là n'est pas un critère** : il grossit chaque fois qu'une page devient plus
honnête, puisqu'une mesure bien écrite emploie le mot :

```bash
grep -rniE "\bmesuré(e|s|es)?\b" --include='*.md' . | grep -v '\.venv'
```

La ventilation par les trois critères du patron ci-dessus — **date**, **commande**,
**critère** — étendue aux quatre mots qui revendiquent un état du monde (« mesuré »,
« vérifié », « jamais testé », « non vérifié »). Deux conventions, qui font partie de la
mesure et sont donc *dans* la commande plutôt que dans une phrase : le contexte est la
fenêtre de **±10 lignes** autour de l'emploi, et les **blocs de commande sont sautés** —
sans quoi ce compteur se compterait lui-même, ses quatre motifs étant écrits dans son
propre source :

```bash
python3 - <<'PY'
import re, pathlib, collections
M = {"mesuré":       r"\bmesuré(e|s|es)?\b",
     "vérifié":      r"\bvérifié(e|s|es)?\b",
     "jamais testé": r"jamais\s+(été\s+)?(testé|exercé|rejoué|essayé)",
     "non vérifié":  r"(non|pas)\s+vérifié|n'a\s+pas\s+été\s+vérifié"}
DATE = r"\b\d{1,2}\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b"
CMD  = r"^\s*(```|    \S|\$ |sudo |grep |make |python3? |psql |systemctl |journalctl |git |ss |curl |pytest|bash |\S+\.sh\b|\S+\.py\b)"
CRIT = r"critère|code 0|rc\s*=|identique|aucune ligne|même md5|0 échec|VERDICT|sans échec"
t, c = collections.Counter(), collections.Counter()
d = collections.defaultdict(collections.Counter)
for p in sorted(pathlib.Path('.').rglob('*.md')):
    if '.venv' in p.parts: continue
    L = p.read_text(encoding='utf-8', errors='replace').splitlines()
    fence = False
    for i, l in enumerate(L):
        if l.lstrip().startswith('```'): fence = not fence; continue
        if fence: continue          # un bloc de commande n'affirme rien
        for nom, rx in M.items():
            if not re.search(rx, l, re.I): continue
            ctx = L[max(0, i-10): i+11]
            a = any(re.search(DATE, x, re.I) for x in ctx)
            b = any(re.match(CMD, x) for x in ctx)
            k = any(re.search(CRIT, x, re.I) for x in ctx)
            t[nom] += 1; d[nom]['D'] += a; d[nom]['C'] += b; d[nom]['K'] += k
            c[nom] += (a and b and k)
print(f"{'marqueur':<14}{'total':>6}{'date':>6}{'cmd':>6}{'crit':>6}{'LES TROIS':>11}")
for n in M:
    print(f"{n:<14}{t[n]:>6}{d[n]['D']:>6}{d[n]['C']:>6}{d[n]['K']:>6}{c[n]:>11}")
print(f"{'TOTAL':<14}{sum(t.values()):>6}{sum(d[n]['D'] for n in M):>6}"
      f"{sum(d[n]['C'] for n in M):>6}{sum(d[n]['K'] for n in M):>6}{sum(c.values()):>11}")
PY
```

Obtenu le **10 août 2026**, à la racine du dépôt, après les corrections de ce lot :

```
marqueur       total  date   cmd  crit  LES TROIS
mesuré           129    25    41    50          4
vérifié           88    14    40    30          6
jamais testé      16     7     6     9          2
non vérifié       16     3     7     9          1
TOTAL            249    49    94    98         13
```

Avant ce lot, la même commande sur le même corpus rendait `237` affirmations et `7`
conformes aux trois critères. **Sept sur deux cent trente-sept** : c'est cela, la dette,
et c'est pour cela qu'elle est structurelle et non anecdotique.

**Critère, et c'est lui qu'il faut retenir plutôt que les chiffres :** la colonne
« LES TROIS » doit **monter** d'un lot au suivant, jamais descendre. Un lot qui ajoute une
affirmation datée sans commande ni critère la fait descendre : c'est cela qu'on surveille,
pas `13`. Le jour où la colonne « LES TROIS » égale la colonne « total », cette section
n'a plus de raison d'exister.

**Ce que ce compte ne sait pas faire, et il faut le dire ici plutôt qu'au bas de la
page.** La détection est *lexicale* : elle voit une date, un bloc de commande, un mot de
critère à moins de dix lignes. Elle ne sait pas si la date est celle de *cette*
mesure-là, ni si la commande refait *celle-ci*. Elle compte donc **trop généreusement** —
un emploi conforme au sens de ce compteur peut rester une mesure molle. C'est une borne
inférieure de la dette, jamais une supérieure. **Combien ont été refaites depuis ?** La
question reste sans réponse mécanique, et c'est le fond du constat.

**Et voici ce qu'aucun garde ne sait faire aujourd'hui**, ce qui explique que le motif
revienne : `tests/test_la_doc_dit_vrai.py` sait interdire de déclarer « jamais exercée »
une commande d'une **liste** de quatre motifs. Il ne sait pas voir **deux sections
d'honnêteté du même dépôt qui parlent du même geste et se contredisent** — et c'est de
cette forme-là qu'étaient les six. Allonger la liste ne referme rien ; croiser les
sections entre elles, si. C'est une dette, et elle est ici pour être vue.

**Ce que la règle 4 rend possible, et la limite qu'elle ne franchit pas — il faut le dire
plutôt que promettre.** Une mesure écrite selon le patron devient **mécaniquement
vérifiable** : un garde peut exiger qu'un paragraphe portant « mesuré » contienne une date
et un bloc de commande, et *cela* referme la forme la plus fréquente du défaut — le
« mesuré » nu, qui est aujourd'hui la majorité. Ce qu'aucun garde ne pourra faire, et
c'est la borne honnête : **décider si une mesure datée et rejouable est encore vraie**.
Pour le savoir, il faut la rejouer, donc un cerveau, une grappe, des ports — ce que
`make test` n'a pas, par construction, et ce que seul `make acceptance` peut offrir. Le
défaut n'est donc pas rendu *impossible* ; il est rendu **cher à commettre et bon marché
à découvrir**, ce qui est le mieux qu'une page puisse faire d'elle-même. Prétendre
davantage serait, ici même, la faute que cette section combat.

**La garde proposée, et pourquoi elle n'est pas encore posée.** Le compteur ci-dessus est
déjà un garde, à une ligne près : il suffit de le faire échouer. La forme exacte —
`tests/test_une_mesure_datee_est_rejouable.py`, hermétique, aucune base, aucun réseau :

1. **un cliquet, pas un seuil.** Le nombre d'affirmations **non** conformes aux trois
   critères est comparé à un plafond versionné dans le test. Il peut descendre — le test
   exige alors qu'on abaisse le plafond ; il ne peut jamais monter. Un plafond fixe est un
   instantané, donc interdit par la règle 2 ; un cliquet est un critère.
2. **le rouge est nominatif.** Le test n'imprime pas un compte mais les `fichier:ligne`
   des affirmations qui ont fait monter le total, avec lequel des trois manque. Un garde
   qui dit « 250 au lieu de 249 » n'apprend rien à qui doit corriger.
3. **il se relit lui-même.** Le bloc de résultat publié dans cette section est comparé à
   la sortie de la commande. S'ils divergent, c'est cette page qui est en échec — ce qui
   aurait attrapé les « 173 » le jour de leur écriture.

**Ce que cette garde n'attrapera pas, et il faut le dire ici plutôt qu'au moment où elle
échouera à le faire.** Elle ne voit que la *forme*. Elle laisse passer une date qui n'est
pas celle de la mesure, une commande qui ne refait pas *celle-ci*, un critère décoratif.
Surtout, elle est **aveugle à la moitié qui a coûté le plus cher ce mois-ci : l'alarme
périmée.** Une page qui déclare un défaut ouvert alors qu'il est fermé porte souvent sa
date et sa commande — elle est *conforme*, et fausse. Le seul contrôle qui la démente est
de rejouer la commande, donc `make acceptance`, donc un cerveau, une grappe et des ports.
La garde ci-dessus rend la classe **visible et bornée** ; elle ne la ferme pas, et aucune
garde hermétique ne le pourra.

**Elle n'est pas posée dans ce lot** parce que ce lot ne touche que des pages : poser un
test, c'est écrire du code, et un lot qui déborde de son mandat est la manière la plus
sûre de casser ce qu'il ne regardait pas. Elle est décrite ici assez précisément pour être
écrite par quelqu'un d'autre — c'est le sens de cette page.
