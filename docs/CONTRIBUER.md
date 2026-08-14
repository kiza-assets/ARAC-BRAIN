# Contribuer — les règles qui font la valeur du produit

Ce document n'est pas une liste de formalités. C'est la **doctrine** de ce dépôt : ce
qu'on peut y écrire, ce qu'on ne peut pas, et pourquoi certaines interdictions n'ont
aucune exception.

Un cerveau personnel n'a qu'un seul actif : **on peut le croire.** Le jour où une seule
de ses affirmations est fabriquée, plus aucune ne vaut rien — et l'utilisateur n'aura
aucun moyen de savoir laquelle. Les trois règles qui suivent existent pour ça, et elles
priment sur l'élégance, sur la performance et sur la complétude d'une fonctionnalité.

---

## Les trois règles non négociables

### 1. Aucune donnée simulée. Jamais.

Un chiffre affiché est un chiffre **lu en base**. Pas moyenné, pas extrapolé, pas rempli
par une valeur de repli, pas engendré par un modèle de langage.

**Ce qui est interdit, en clair :**

- les jeux de données de démonstration qui se substituent aux vraies données quand
  celles-ci manquent ;
- les valeurs par défaut « raisonnables » injectées à la place d'une mesure absente ;
- toute phrase du cockpit rédigée par un modèle. Le serveur ne rend que des **clés de
  gabarit et des nombres** ; le texte est un gabarit figé, versionné, relisible ;
- les captures d'écran et blocs de sortie inventés dans la documentation. Si vous n'avez
  pas exécuté la commande, **dites-le** — comme le font aujourd'hui
  [`DEMARRAGE-RAPIDE.md`](DEMARRAGE-RAPIDE.md) et [`PREMIER-JOUR.md`](PREMIER-JOUR.md)
  dans leur dernière section.

**Ce qui est autorisé** : un exemple **désigné comme tel**, avec des valeurs plausibles,
et une phrase qui le dit. Le README le fait : *« Les chiffres ci-dessus sont plausibles,
pas capturés. »* Une seule ligne, et le lecteur sait ce qu'il lit.

> Une donnée simulée ne se voit pas. Elle passe la revue, passe les tests, s'installe, et
> ressort deux ans plus tard sous la forme d'une décision prise sur un chiffre qui
> n'existait pas.

### 2. Chaque chiffre est traçable jusqu'à sa source

Toute métrique servie par le cockpit porte, dans sa propre réponse, **le SQL qui l'a
produite** — paramètres substitués, sur une ligne, collable dans `psql` :

```json
"evidence": {
  "kind": "sql",
  "sql": "SELECT count(*) FROM arac.memory_atoms WHERE status='active' AND created_at > now() - interval '24 hours'",
  "label": "les atomes créés dans les 24 dernières heures"
}
```

Ce n'est pas du confort de développeur, c'est la **condition de réfutabilité**. Un
cockpit qu'on ne peut pas contredire ne mérite pas d'être cru. Si un chiffre vous paraît
faux, vous devez pouvoir le prouver en trente secondes sans lire une ligne de Python.

**Les conséquences pratiques, quand vous écrivez du code :**

- **toute l'arithmétique est en SQL.** Cumuls, rangs, percentiles, distances, ratios :
  la base calcule, Python transporte. Un total accumulé côté client est un total qui
  dépend de l'ordre d'arrivée des paquets — donc un total qui peut mentir ;
- **une nouvelle métrique arrive avec sa définition, sa formule, sa requête de preuve et
  ses seuils.** Pas de métrique orpheline : `scripts/ops/health_check.py` **lit** le
  registre du cockpit plutôt que de redéfinir ses propres seuils, précisément pour qu'il
  n'existe jamais deux vérités ;
- **le cockpit est en lecture stricte.** Rôle `arac_readonly`,
  `default_transaction_read_only=on`, garde lexicale sur chaque requête. Un `INSERT`
  dans `control_center/` est un défaut, pas un raccourci.

### 3. Une absence de mesure ne s'affiche jamais comme un zéro

C'est la règle la plus violée dans les tableaux de bord du monde entier, et la plus
coûteuse.

| Ce que l'utilisateur lit | Ce qu'il comprend |
|---|---|
| `0 atome créé` | « le cerveau ne produit rien » → il va chercher une panne de digestion |
| `indisponible : le rôle n'a pas accès à arac.scopes` | « je ne sais pas » → il va regarder les droits |

Ce ne sont pas les mêmes nouvelles, et elles n'appellent pas le même geste. Le format est
déjà en place dans tout le dépôt, et une nouvelle contribution doit le respecter :

```json
{
  "state": "unavailable",
  "reason": "last_verified_at et confirmed_until sont NULL sur la totalité des atomes",
  "gesture": "brancher un vérificateur qui écrive last_verified_at",
  "substitute": "la date du dernier rappel (usage.last_served_at)"
}
```

Quatre champs : **ce que c'est**, **pourquoi**, **comment le réparer**, **par quoi s'en
passer en attendant**. Le troisième et le quatrième sont ce qui distingue une
indisponibilité honnête d'un simple aveu d'impuissance.

La même règle vaut pour les sondes : `scripts/ops/health_check.py` sort en code **3
(UNKNOWN)** quand la base est injoignable, jamais en 0 (OK). *Transformer une panne
d'observation en bonne nouvelle est l'erreur la plus coûteuse d'un système de
surveillance.*

---

## Les règles de dépôt

### Aucune trace personnelle — assertion F1

Ce dépôt est un **framework**, pas le cerveau de quelqu'un. Il ne doit contenir :

- aucun prénom, nom, société, ville, ni nom de proche ;
- aucun scope réel appartenant à une personne ;
- aucun chemin absolu propre à une machine (`/opt/…`, `/root/…`, `/Users/…`) ;
- aucun identifiant de poste réel.

**Tout chemin est paramétré** : `ARAC_HOME`, `ARAC_DB`, `ARAC_NODE_ID`,
`ARAC_BACKUP_DIR`… Une valeur en dur dans un fichier livré est un défaut bloquant.

**La seule exception est un exemple explicitement désigné**, accompagné d'un « ne copiez
pas ceci, écrivez le vôtre ». `config/scopes.example.toml` montre comment le faire
correctement.

Avant de proposer une modification, passez le balayage — c'est celui que
l'intégration continue applique, dans `.github/workflows/tests.yml` :

```bash
git grep -nE '/Users/[A-Za-z0-9._-]+' -- .        # chemins de machine personnelle
git ls-files | grep -E '^(\.env$|config/brain\.toml|config/scopes\.toml)'   # doit être vide
```

Le second balayage est le plus important : `config/brain.toml` et `config/scopes.toml`
décrivent **une personne** — son identité, son poste, son découpage de la vie. Ils sont
engendrés à l'installation, ignorés par git, et leur présence dans un dépôt public
signifie que quelqu'un a publié son cerveau.

### Aucun secret, aucun appel réseau à l'exécution des tests

- Pas de clé, de jeton, de mot de passe ni d'empreinte dans le dépôt — même « de test ».
- `.env` n'est jamais versionné. `ops/install_check.sh` vérifie qu'il ne l'est pas :
  un `.env` commité est une fuite **définitive**, l'historique le garde même après
  suppression, et toutes les clés sont à révoquer.
- **La suite de tests est hermétique, et c'est une garde, pas une promesse**
  (`tests/garde_hermetique.py`) : les sockets sortantes et les commandes qui interrogent
  la machine sont coupées pendant la suite, et toute base qui n'appartient pas au test
  lui-même est refusée à l'ouverture de la connexion. Un test qui exigerait une base
  **se déclare ignoré** plutôt que de rougir.
- **Le critère du garde n'est pas un nom, c'est une propriété.** Il ne suffit pas de
  refuser la base nommée `arac` : le framework nomme la base d'après le cerveau, et celle
  de n'importe quel autre utilisateur passerait. La question posée est
  *« cette base m'appartient-elle, à moi, test ? »*. Si vous ajoutez un chemin d'accès à
  une base, il doit passer par là.

> *Un test rouge doit vouloir dire « le code est cassé », jamais « PostgreSQL n'est pas
> lancé ».* Une suite qui rougit pour des raisons d'environnement est une suite qu'on
> apprend à ignorer — et une suite ignorée ne protège plus rien.

### Ce qui coûte de l'argent ne se déclenche pas tout seul

Aucune cible de `Makefile`, aucun test, aucune commande de diagnostic ne doit émettre un
appel payant. Les freins existants ne se contournent pas « juste pour un essai », et il y
en a **quatre**, dont **deux interrupteurs** — pas un :

- `ARAC_ALLOW_PAID_AI`, à `0` par défaut, dans le fichier d'environnement du cerveau ;
- `arac.arac_config.paid_ai_enabled`, **en base**, qui ne s'arme que par un geste humain
  explicite (`agents.lib.paid_ai_control arm --confirm`) ;
- `ARAC_PACK_TOKEN_BUDGET`, le plafond par cycle ;
- `agents/lib/spend_guard.py`, les plafonds du jour et le kill-switch.

Le second interrupteur est celui qu'on oublie de nommer parce qu'aucun `grep` sur un
fichier ne le montre. Une page qui n'en cite qu'un envoie son lecteur réparer la moitié
d'une panne.

Une fonctionnalité qui dépense doit **annoncer son coût** avant de dépenser, et le
mesurer après.

### Les migrations vont vers l'avant

- Une migration Alembic est **additive et réversible** (`downgrade` écrit et testé).
- **Aucune donnée n'est supprimée silencieusement.** Le modèle est un remplacement
  (`superseded_by`) qui garde la trace, pas un `DELETE`. C'est pour cela que le rôle
  applicatif n'a pas le droit de supprimer.
- **Ne changez pas le format de `source_ref`.** C'est la structure la plus coûteuse à
  faire évoluer de tout le système : sur le cerveau de référence, un changement de format
  a coupé le lien atome ↔ conversation sur **76 % du corpus**, sans erreur, sans alerte,
  et de façon irrécupérable. Si vous devez l'étendre, **ajoutez une clé**, ne renommez
  jamais.

---

## Comment écrire — le style est une fonctionnalité

**La documentation est en français, et elle enseigne.** Chaque document doit apprendre
quelque chose à quelqu'un qui découvre le projet.

| Écrivez | Pas |
|---|---|
| « Le serveur refuse toute conversation venant d'un poste non déclaré : c'est ce garde-fou qui l'empêche d'avaler n'importe quoi. » | « Veuillez configurer `ARAC_NODE_ID`. » |
| « 36 % des cycles du cerveau de référence n'ont produit aucun atome. La cause n'était pas le volume. » | « Des échecs de cycles peuvent survenir. » |
| « Ce que vous devez voir : … » | « L'opération devrait aboutir. » |

Quatre exigences, dans les documents comme dans les commentaires de code :

1. **Dire pourquoi**, pas seulement quoi. Un seuil sans sa justification est un seuil
   qu'on changera au hasard dans six mois.
2. **Citer les mesures comme des mesures**, jamais comme des menaces. « près d'un souvenir
   actif sur onze est tombé dans ce piège » enseigne ; « attention, danger » n'enseigne
   rien. Et **une mesure exacte ne vit qu'à un seul endroit** : celle-ci a vécu à six
   endroits avec trois valeurs, jusqu'à ce que le bloc de résultat le plus lu cesse de
   correspondre à la requête imprimée au-dessus de lui. Partout ailleurs, on nomme la
   proportion et on renvoie à l'endroit qui fait autorité.
3. **Ne rien cacher** : prérequis, dépendances payantes, limites connues, ce qui ne
   marche pas encore — en première page, pas en annexe.
4. **Aucune promesse invérifiable.** Si ce n'est pas testé, écrivez-le. Chaque document
   long de ce dépôt se termine par « ce qui a été vérifié et ce qui ne l'a pas été » :
   c'est une convention, tenez-la.

Pour le code : commentaires en français, docstrings qui expliquent la **décision** et pas
la syntaxe, et le nom des choses dans la langue du domaine (`atome`, `rappel`, `cycle`,
`provenance`).

---

## Le circuit

### Avant d'ouvrir quoi que ce soit

```bash
make test        # la suite hermétique
make doctor      # l'installation peut-elle démarrer ?
```

Si `make test` ne passe pas sur `main` chez vous, **c'est ça, le premier rapport à
ouvrir** — pas votre modification.

> **`make test` n'est pas « le seul gate qui compte », et cette page l'a écrit
> pendant des mois.** Le jour où la formule a été démentie, la suite était verte et
> le produit livrait quatre noms jamais importés — deux routes du tableau de bord
> en 500 sur un cerveau neuf, et le kill-switch de l'IA payante mort à sa première
> ligne. Lisez donc **trois** lignes dans la sortie, et non une : le garde des noms
> (`tests/test_aucun_nom_non_resolu.py`), le bloc « ce que cette session a
> réellement emprunté », puis la ligne pytest sans `failed`. La quatrième —
> `sudo make acceptance` — demande une machine, et c'est la seule qui réponde à
> *« ces chemins marchent-ils ? »* plutôt qu'à *« sont-ils chargeables ? »*. Le
> détail fait autorité en
> [première page du `README`](../README.md#6-le-chemin-le-plus-court-vers-un-cerveau-qui-vit).

### Ouvrir un ticket

Trois gabarits, dans `.github/ISSUE_TEMPLATE/` :

| Gabarit | Quand |
|---|---|
| **Bogue** | quelque chose se comporte autrement que ce que la documentation annonce |
| **Question** | la documentation ne répond pas, ou répond de façon ambiguë — **c'est un rapport utile**, pas un dérangement |
| **Idée** | une fonctionnalité, une amélioration, une friction récurrente |

Une **question** est un signalement de première classe : si vous avez dû lire le code
pour comprendre un comportement, la documentation a échoué, et c'est un défaut réparable.

### Proposer une modification

1. une branche par sujet ;
2. `make test` vert **avant** d'ouvrir la proposition ;
3. le gabarit de proposition (`.github/PULL_REQUEST_TEMPLATE.md`) rempli — en
   particulier la case **« ce que j'ai réellement exécuté »**, qui est la seule qui
   compte lors de la revue ;
4. la documentation mise à jour **dans la même proposition**. Une fonctionnalité non
   documentée n'existe pas ; une fonctionnalité documentée mais non testée est pire,
   parce qu'elle est promise.

### Ce que la revue regarde, dans cet ordre

1. **Est-ce que ça peut mentir ?** — donnée simulée, chiffre sans preuve, zéro à la
   place d'une absence. Rédhibitoire.
2. **Est-ce que ça trahit quelqu'un ?** — trace personnelle, chemin en dur, secret. F1
   est booléen.
3. **Est-ce que ça dépense sans le dire ?**
4. **Est-ce que ça enseigne ?** — la documentation associée apprend-elle quelque chose ?
5. **Est-ce que c'est juste ?** — les tests, enfin. Ils viennent après, parce qu'un code
   correct qui ment reste inacceptable.

---

## Les contributions les plus utiles aujourd'hui

Par ordre décroissant d'utilité réelle, et sans détour :

1. **Un récit d'installation à l'aveugle.** Prenez un Ubuntu neuf, suivez la seule
   documentation, notez **chaque** friction — y compris celles que vous avez contournées
   en dix secondes. C'est l'assertion **F8** de [`GOAL.md`](../GOAL.md), c'est la
   dernière chose qui manque, et personne ne peut la produire à votre place.
2. **Un récit de premier jour.** Vos vrais chiffres : combien de conversations, combien
   d'atomes, quel coût réel la première semaine. Le dépôt ne dispose aujourd'hui que des
   mesures d'**une seule** installation ; deux valent infiniment mieux qu'une.
3. **Le pont exercé sur un vrai Mac.** `launchctl`, les notifications, l'emplacement réel
   des données : rien de tout cela n'a été vérifié.
4. **Les chantiers ouverts** de [`ROADMAP.md`](ROADMAP.md).

Et une chose qui n'est **pas** demandée : des fonctionnalités nouvelles avant que les
existantes soient prouvées. Ce dépôt a plus besoin d'un cerveau installé deux fois de la
même manière que d'une fonctionnalité de plus.

---

## Portée du projet — ce qui sera refusé, sans rancune

- **Pas de multi-utilisateur.** Un cerveau, une personne.
- **Pas d'interface web publique.** L'API et le cockpit écoutent sur `127.0.0.1` ; le
  tunnel SSH est la seule porte **depuis l'extérieur**, et c'est ce qui permet de n'avoir
  ni TLS, ni reverse-proxy, ni pare-feu à régler. Sur la machine elle-même, la porte est
  le jeton porteur, exigé de toute requête y compris en boucle locale (`app/auth.py`) :
  une contribution qui rouvrirait `127.0.0.1` par défaut sera refusée pour cette
  raison-là.
- **Pas de Docker.** C'est un choix : `systemd` et un `venv` se diagnostiquent mieux à
  trois heures du matin.
- **Pas de dépendance à un service tiers de plus.** Il y en a deux, payants, annoncés en
  première page. Un troisième devrait justifier son existence contre cette page-là.
