# Sauvegarder un cerveau — et prouver qu'on peut le récupérer

> **La phrase à retenir avant toute autre :**
> une sauvegarde qui n'a jamais été restaurée n'est pas une sauvegarde.
> C'est un fichier dont vous supposez qu'il contient quelque chose.

Ce document explique comment ce dépôt sauvegarde un cerveau, pourquoi chaque
décision est prise ainsi, et — surtout — **quoi faire le jour où il faut tout
récupérer**. Cette dernière partie est celle qu'on lit en panique : elle est
écrite pour être suivie ligne par ligne, sans réfléchir.

---

## 1. Ce que vous perdez si vous ne faites rien

Un cerveau ARAC, ce n'est pas une base de données interchangeable. C'est :

- **des atomes** — du savoir que vous avez **payé** pour extraire. Le cerveau de
  référence a mesuré ~31 500 jetons de curation par atome réellement produit.
  Mille atomes, ce sont des dizaines de millions de jetons dépensés. Perdus, ils
  ne se retrouvent pas : ils se **rachètent**.
- **des embeddings** — 3072 dimensions par atome, recalculables mais repayables
  à l'identique.
- **des conversations brutes** — le substrat. Elles viennent de votre poste, où
  elles peuvent avoir été effacées entre-temps par une rotation qui n'est pas la
  vôtre.
- **des reçus** — ingestion, digestion, rappel. C'est la mémoire que le cerveau
  a de lui-même : sans elle, il ne sait plus ce qu'il a lu, ni ce qu'il a raté.

Autrement dit : la seule partie remplaçable de l'installation, c'est le code.

---

## 2. Ce que le bootstrap arme réellement, et ce qu'`ops/` sait faire en plus

Ce paragraphe s'est longtemps intitulé « ce qui est mis en place » et décrivait quatre
automatismes dont deux n'existaient pas après une installation. Il est maintenant coupé en
deux blocs qu'on ne peut plus confondre, parce que c'est le seul sujet où se tromper coûte
le cerveau entier.

### Armé par le bootstrap, sans que vous ayez rien à faire

Trois minuteries systemd portent le nom de votre cerveau. Deux concernent la sauvegarde :

| quand | quoi | unité |
|---|---|---|
| toutes les 6 h (`00,06,12,18:30 UTC`) | `ops/backup.sh` — `pg_dump` du schéma, les deux planchers de sincérité, contrôle du sommaire, écriture en `.partial`, rotation **après** succès, registre des tailles | `arac-<base>-sauvegarde.timer` |
| dimanche 03:00 UTC | `ops/restore_verify.sh` — restaure le dernier dump dans une base **jetable**, la compare au cerveau vivant, puis la détruit | `arac-<base>-restauration.timer` |

Il n'existe **qu'une seule** implémentation de la sauvegarde dans ce dépôt, et l'unité
l'appelle. Vous pouvez le vérifier sans rien croire :

```bash
systemctl cat arac-<base>-sauvegarde.service | grep ExecStart   # doit pointer sur ops/backup.sh
systemctl list-timers 'arac-<base>-*'                           # les trois minuteries et leur échéance
```

**Ce que cela ne fait pas, et il faut le lire.** Les dumps restent **en clair, sur cette
machine**, tant que vous n'avez pas déposé de destinataire `age` : le journal de la
sauvegarde l'écrit lui-même (`"encrypted":false`), et il n'existe **aucune copie
ailleurs**. Un disque qui meurt emporte le cerveau et ses sauvegardes ensemble.
`ops/install_check.sh` vous le redit à chaque passage, par deux réserves nommées —
« chiffrement au repos DÉSACTIVÉ » et « aucune copie hors site ».

### À armer vous-même — rien de ce qui suit n'est posé par le bootstrap

Ce sont les gabarits d'`ops/systemd/`, et c'est **vous** qui les rendez et les armez ; la
marche à suivre est au §11 d'[`INSTALLATION.md`](INSTALLATION.md). Ils réclament une
décision que le produit ne peut pas prendre à votre place — une destination distante, un
canal d'alerte :

```
   toutes les 30 min           ops/backup_offsite.sh
     pousse les artefacts CHIFFRÉS ailleurs, vérifie l'empreinte à l'arrivée,
     n'efface JAMAIS rien à distance

   toutes les 30 min           ops/watchdog.sh
     surveille la GARANTIE, pas les scripts ; signe de vie hebdomadaire
```

Tant que vous ne l'avez pas fait, aucune copie ne quitte cette machine et personne n'est
réveillé quand la garantie tombe.

Aucun des chemins de ce chapitre n'est écrit en dur : `ARAC_BACKUP_DIR`,
`ARAC_BACKUP_STATE`, `ARAC_OFFSITE_DEST`, `ARAC_DB_SCHEMA`… tout se règle par
variable d'environnement, lue depuis votre `.env`.

---

## 3. La sauvegarde, et les quatre façons dont elle ment

`ops/backup.sh` fait un `pg_dump --format=custom` du schéma. C'est la partie
facile. Le reste du script existe parce qu'un dump peut échouer **en silence**
de quatre façons, et qu'aucune ne se voit sur un `ls -lh`.

### a. Le dump minuscule
Une authentification qui échoue en douceur, un schéma inexistant, une base
vide : `pg_dump` réussit et produit quelques kilo-octets. **Plancher absolu :**
sous 10 KiB, le dump est refusé. Un schéma ARAC vide, sans une seule ligne, pèse
déjà davantage.

### b. Le dump qui a maigri
Plus vicieux : le dump fait la moitié de sa taille habituelle. **Plancher
relatif :** on garde un registre des tailles (`$ARAC_BACKUP_STATE/dump_sizes`)
et on compare à la **médiane** des trente derniers. Sous 50 %, refus.

Pourquoi la médiane et pas la moyenne : un seul jour d'import massif relèverait
la moyenne pour toujours et rendrait le contrôle aveugle. Pourquoi pas un seuil
en méga-octets : personne ne peut dire quelle taille doit faire *votre* cerveau.
Votre cerveau d'hier, si.

### c. Le dump amputé
Le fichier est parfait, lisible, complet — et il lui manque une table entière,
parce qu'il a été pris avant une migration, ou parce que le rôle de sauvegarde
n'a pas le droit de lire une table nouvellement créée. **Contrôle du
sommaire :** `pg_restore --list` est comparé à la liste des tables sans
lesquelles un cerveau ne se reconstruit pas.

> Le piège, gardé du cerveau de référence : chercher `nodes` par simple
> sous-chaîne est satisfait par la ligne de `nodes_heartbeat_history`. Un dump
> amputé de `nodes` passait le contrôle. Le motif est donc ancré à droite. Ce
> détail a coûté une confiance injustifiée pendant des mois.

`ops/backup_toc_check.sh selftest` éprouve ce contrôle sans base, sans réseau,
en une seconde. Y compris ce piège-là.

### d. Le dump qui ne se restaure pas
Aucun des trois contrôles précédents ne le voit. Seule une vraie restauration le
voit — c'est la section 5.

**Ce que fait le script quand un contrôle refuse :** il renomme le fichier en
`.suspect` ou `.incomplete`, **il ne fait PAS tourner la rotation**, et il
alerte. L'ordre compte : si la rotation tournait avant le dump, quelques jours
d'échec videraient le coffre — la sauvegarde passe quatre fois par jour, la
rotation efface sur une fenêtre en jours, et une panne silencieuse aurait donc
tout le temps de rattraper le plus ancien dump sain.

---

## 4. Le chiffrement au repos, et la clé qui ne vit pas sur le serveur

Un dump contient **tout** votre cerveau, en clair. Chaque atome, chaque
conversation, chaque secret qui y serait passé. Le répertoire est en mode 0700,
mais un mode Unix ne protège pas d'une sauvegarde de disque, d'un snapshot
d'hébergeur, ou d'un vol de machine.

```bash
# SUR VOTRE MACHINE, pas sur le serveur :
BASE=<votre_base>                        # brain.name de config/brain.toml
age-keygen -o ~/arac-backup-$BASE.key    # gardez-la comme un mot de passe maître
grep 'public key' ~/arac-backup-$BASE.key   # → age1...

# SUR LE SERVEUR — dans le coffre de CE cerveau, et en AJOUTANT :
BASE=<votre_base>                        # brain.name de config/brain.toml
sudo install -d -m 0700 -o root -g root "/etc/arac/$BASE"
echo 'age1...' | sudo tee -a "/etc/arac/$BASE/backup-recipients.txt" >/dev/null
sudo chmod 0600 "/etc/arac/$BASE/backup-recipients.txt"
sudo cat "/etc/arac/$BASE/backup-recipients.txt"     # relisez : QUE vos clés
```

Rien à poser dans le `.env` : `ops/env.sh` prend ce fichier **s'il existe**, et
`ARAC_BACKUP_RECIPIENTS` ne sert plus qu'à en désigner un autre, délibérément.

> **Deux détails qui coûtent tout le coffre, et qui ont failli le coûter ici.**
>
> **1. Le chemin porte le nom du cerveau.** Cette page faisait déposer ce
> fichier directement sous `/etc/arac/`, **sans le nom du cerveau** — la racine
> commune à la machine. Elle n'appartient à personne, donc à tout le monde : sur
> un serveur qui porte deux
> cerveaux, le second y dépose sa clé publique et les dumps du **premier**
> partent chiffrés pour un tiers. Le premier ne s'en aperçoit qu'au jour de la
> restauration, c'est-à-dire au pire moment possible. Le coffre d'un cerveau
> vit dans `/etc/arac/<base>/`, à côté de ses autres secrets, en 0600 root
> comme eux. `ops/backup.sh` le vérifie et vous avertit si le fichier lu n'est
> pas celui de ce cerveau — il ne l'interdit pas, mais il ne vous laisse plus
> l'ignorer.
>
> **2. `>>`, jamais `>`.** Un `>` sur un fichier qui contenait déjà une clé la
> **remplace**. Le jour de la restauration, la clé privée que vous aviez gardée
> précieusement ne déchiffre plus rien, et **il n'existe aucun recours**. C'est
> la seule commande de cette page qui détruise en ayant l'air d'ajouter.

Le chiffrement est **asymétrique** : le serveur ne détient que la clé publique.
Il peut chiffrer, il ne peut pas déchiffrer. Un serveur compromis ne livre donc
pas l'historique des sauvegardes.

**Le prix de cette propriété** : le jour de la restauration, il faut la clé
privée. Si vous la perdez, vos sauvegardes chiffrées sont du bruit — et personne,
nulle part, ne peut vous aider. Gardez-en deux copies, dans deux endroits, dont
un hors ligne.

Par défaut (`ARAC_BACKUP_CLEAR_LOCAL=1`) le dump en clair reste sur le serveur à
côté du chiffré : la restauration d'urgence ne dépend alors pas d'une clé qu'on
cherche en panique. Passez à `0` quand votre procédure de clé tient debout — et
sachez que la vérification hebdomadaire devra alors déchiffrer, donc disposer
d'une identité (`ARAC_BACKUP_IDENTITY`), ce qui annule une partie du bénéfice.
**Il n'y a pas de bonne réponse universelle ici. Il y a un choix, et il vous
appartient.**

Le chien de garde épingle l'empreinte du fichier de destinataires
(`ARAC_BACKUP_RECIPIENTS_SHA`) : substituer une clé publique suffirait à recevoir
toutes les sauvegardes suivantes sans que rien n'échoue.

---

## 5. La restauration vérifiée — le seul contrôle qui compte

```bash
# La minuterie le fait déjà toute seule chaque dimanche. Pour ne pas attendre,
# demandez-le à l'UNITÉ : elle porte le coffre et le dépôt de CE cerveau.
sudo systemctl start "arac-<base>-restauration.service"
sudo journalctl -u "arac-<base>-restauration.service" -n 40 --no-pager

# À la main, hors de l'unité, il faut nommer le cerveau soi-même :
sudo ARAC_ENV_FILE="/etc/arac/<base>/arac.env" ops/restore_verify.sh
```

> **Pourquoi `ARAC_ENV_FILE` quand on l'appelle à la main.** Sur une machine qui porte
> **un seul** cerveau, ce script trouve son coffre tout seul. Dès qu'il y en a deux, il ne
> s'arrête pas : il sert le cerveau que **votre clone décrit** (`config/brain.toml`) et il
> l'annonce avant d'agir — « *ops/ sert le cerveau « … » — ce dépôt le décrit, il n'a pas
> été deviné* », suivi du coffre, de la preuve et du nombre de candidats. Il ne s'arrête
> (code 1, « *ARRÊT AVANT TOUT GESTE* ») que si ce clone ne décrit aucun cerveau, ou en
> décrit un qui n'a pas de coffre ici. **C'est donc le dossier d'où vous tapez qui
> décide** — et un jour de restauration n'est pas le jour où l'on veut s'en apercevoir.
> Nommez le coffre, toujours. Les cinq rangs sont au tableau d'`ARAC_ENV_FILE` de
> [`CONFIGURATION.md`](CONFIGURATION.md).

Il crée une base **jetable**, y restaure vraiment, l'interroge, la détruit. Il ne
touche jamais à la base vivante : le garde lit le nom de votre base dans **votre**
configuration et refuse de la viser, quel que soit l'argument reçu.

Il rend **quatre** preuves, dans cet ordre à l'écran — A, B, D, puis C :

| Preuve | Ce qu'elle établit |
|---|---|
| **A — structure** | les tables vitales existent dans la base restaurée |
| **B — lisibilité** | les lignes se **relisent** : échantillon d'atomes affiché, embeddings décodés avec leur dimension. Compter des lignes ne prouve pas qu'elles se lisent |
| **D — identité** | *ce dump vient-il de CE cerveau ?* L'empreinte d'installation est gravée dans le **commentaire du schéma**, donc elle voyage **dans** le fichier. Sans elle, restaurer le dump du voisin passerait pour une preuve |
| **C — fidélité** | volumes cohérents avec le vivant, **empreinte md5 des identifiants d'atomes identique**, et retard du dump < 26 h. C'est la seule des quatre qui a besoin d'un cerveau vivant — donc la seule qui tombe le jour du sinistre |

L'empreinte md5 est ce qui distingue « le même nombre de lignes » de « les mêmes
lignes ». Elle porte sur les identifiants ordonnés des atomes antérieurs à
l'horizon du dump : un atome supersédé change de statut, jamais d'identifiant,
donc l'empreinte résiste à la digestion qui a continué après la copie.

**Codes de sortie** : `0` prouvé · `1` échec · `2` restauré mais preuve partielle.

Le `2` mérite d'être lu avant d'en avoir besoin, parce qu'**il est le verdict normal le
jour du sinistre** : il dit « le dump se restaure et son contenu est là (preuves A, B, D),
mais je n'ai pas pu le comparer au cerveau vivant ». Deux situations le produisent — la
base vivante est injoignable, ou elle **répond sans se laisser lire** (schéma détruit,
droits perdus), c'est-à-dire exactement l'état qui vous a amené ici. Le script le dit dans
ces termes et conclut « *Code de sortie 2, et non 1* ». Le seul code qui doit vous faire
changer de dump est le `1`.

### Le gabarit, ou pourquoi ce script ne demande pas les pleins pouvoirs

`CREATE EXTENSION vector` **exige le superutilisateur** : pgvector n'est pas une
extension « trusted ». Faire tourner la vérification hebdomadaire en
superutilisateur pour cette seule raison serait absurde. La sortie est un gabarit
préparé une fois :

```bash
ops/restore_verify.sh --prepare-template          # imprime le SQL, ne l'exécute pas
```

**Ne tuyautez pas cette sortie dans `psql` sans la lire.** Le script imprime, en tête du
bloc, **la commande complète à recopier — port compris**, parce que le SQL qu'il produit
commence par un `DROP DATABASE`. Sans `-p`, `sudo -u postgres psql` s'adresse à la grappe
**par défaut** de la machine : sur un poste à deux cerveaux, ce `DROP DATABASE` tombe sur
le gabarit du voisin. Lisez la commande imprimée, puis recopiez-la telle quelle.

Une base marquée `datistemplate` se copie avec le seul attribut `CREATEDB`. La
vérification n'a plus jamais besoin d'un privilège élevé.

---

## 6. La deuxième machine

Tant que la seule copie vit sur le serveur qui héberge le cerveau, vous n'avez
pas de sauvegarde : vous avez une copie locale, qui disparaît avec la machine.

```bash
# dans .env — <votre_base> partout, jamais un chemin commun
ARAC_OFFSITE_DEST=vous@votre-machine
ARAC_OFFSITE_SSH_KEY=/var/lib/arac/<votre_base>/backup/.ssh/push
ARAC_OFFSITE_DIR=arac-backups/<votre_base>
```

Le dossier distant porte lui aussi le nom du cerveau : deux cerveaux qui poussent vers la
même destination y déposent des dumps aux noms voisins, et la première rotation qui se
trompe de préfixe efface l'historique de l'autre.

Trois propriétés, dans l'ordre d'importance :

1. **Seuls des artefacts chiffrés partent.** Sans `ARAC_BACKUP_RECIPIENTS`, il
   n'y a rien à envoyer, et le script le dit plutôt que d'envoyer en clair.
2. **Le serveur n'efface jamais rien à distance.** C'est ce qui fait qu'un
   serveur compromis ne peut pas détruire l'historique — la première chose que
   fait un rançongiciel bien élevé.
3. **Une destination endormie n'est pas une erreur.** Si c'est un portable, il
   dort. Le script sort en 0 ; c'est l'**ancienneté** de la dernière copie qui
   alerte (chien de garde : 30 h, puis 48 h).

### La commande forcée

Pour verrouiller la propriété n° 2, la destination doit refuser autre chose que
« déposer » et « lire une empreinte ». Côté machine de destination, dans
`~/.ssh/authorized_keys` :

```
command="/usr/local/bin/arac-depot-sauvegardes",no-pty,no-port-forwarding,no-agent-forwarding ssh-ed25519 AAAA...
```

où `arac-depot-sauvegardes` n'accepte que `scp -t`, `mv *.partial`, `sha256sum` et
`mkdir`, **dans le répertoire du cerveau qui pousse et nulle part ailleurs**. Une clé volée
sur le serveur ne donne alors ni shell, ni droit d'effacer, ni accès aux dumps d'un autre
cerveau. Ce script-là dépend de votre machine : il n'est pas fourni ici, et prétendre le
contraire serait mentir sur ce qui est éprouvé.

---

## 7. LA RESTAURATION RÉELLE — celle qu'on exécute en panique

> **Les sorties reproduites dans ce chapitre sont des relevés, pas des exemples
> réécrits.** Elles viennent de deux cerveaux de banc — `doc14a` et `doc14b` — installés
> par le chemin réel, cassés pour de vrai (l'un par un `DROP DATABASE` sur une base
> vivante, l'autre par un `DROP SCHEMA … CASCADE`), remis debout par ce chapitre, puis
> démontés. Leurs noms apparaissent tels quels dans les transcriptions ; les vôtres
> prendront leur place.

> **Il n'existe volontairement aucun script « restaurer par-dessus la
> production ».** Une restauration écrase, et ce qu'elle écrase ne revient pas.
> Cet acte reste manuel, lu ligne par ligne, par un humain qui sait ce qu'il
> fait. Un `make restore` est une catastrophe à une frappe de distance.

> ### ⚠ AVANT LA PREMIÈRE LIGNE — nommez votre cerveau
>
> Ce chapitre s'ouvre le pire jour, et c'est le jour où l'on relit le moins. Chaque
> commande qui suit est donc **paramétrée** : elle agit sur le cerveau que vous nommez ici,
> et sur aucun autre.
>
> ```bash
> BASE=<votre_base>            # brain.name de config/brain.toml
> PGPORT_BASE=$(sudo sed -n 's/^ARAC_DB_PORT=//p' "/etc/arac/$BASE/arac.env")
> COFFRE="/etc/arac/$BASE/arac.env"
> echo "cerveau $BASE · PostgreSQL ${PGPORT_BASE:?introuvable dans $COFFRE — arrêtez-vous}"
> cd "$(sudo sed -n 's/^ARAC_HOME=//p' "$COFFRE")" && pwd   # le dépôt de CE cerveau
> ```
>
> **Le port est la seconde moitié du nom.** Un nom de base ne dit pas sur quel serveur
> PostgreSQL cette base se trouve : `createdb`, `pg_restore`, `dropdb` et `ALTER DATABASE`
> lancés sans `-p` s'adressent à la grappe **par défaut** de la machine. Le jour où l'on
> restaure, c'est la différence entre remettre son cerveau debout et fabriquer une base de
> plus, au mauvais endroit, pendant qu'on croit avoir fini.
>
> **Ce que cette page faisait avant août 2026, et qu'elle ne fait plus** : elle écrivait
> `ALTER DATABASE arac RENAME` sur un nom de base figé, `systemctl stop` sur des unités
> sans nom de cerveau, et surtout elle faisait rejouer
> un fichier de rôles portant `CREATE ROLE … PASSWORD` avec des noms **non préfixés**. Les
> rôles PostgreSQL sont globaux au **cluster** : sur une machine hébergeant un second
> cerveau, cette dernière ligne réencodait ses mots de passe et le tuait — pendant qu'on
> restaurait le premier. **C'est l'instruction exacte de l'incident, et elle était imprimée
> dans le document où l'on est le moins en état de la relire.**
>
> **Corollaire, et c'est la bonne nouvelle : une restauration n'a aucune raison de toucher
> aux rôles.** Ils vivent dans le cluster, pas dans le dump ; un sinistre de base ne les
> efface pas. Ce qu'un `pg_restore --no-owner` perd, ce sont les **droits** sur les objets
> restaurés — et ceux-là se réappliquent avec `bootstrap.sh --only migrations`, qui les
> dérive du nom de votre cerveau et ne crée aucun rôle. Si vos rôles ont **réellement**
> disparu (perte de la grappe entière), n'improvisez pas ici : relancez
> `sudo ./bootstrap/bootstrap.sh --from base` sur la base restaurée — c'est le seul chemin
> qui contrôle la propriété des rôles avant d'écrire.

### Avant de toucher à quoi que ce soit : respirez, et mesurez

```bash
# Qu'est-ce qui est encore là ? — VOS dumps, dans VOTRE sous-dossier.
sudo ls -lh "/var/backups/arac/$BASE"     # ops/env.sh pose ARAC_BACKUP_DIR ici même

# Et le vivant : le port ET la base, jamais la base seule. « psql -d <nom> »
# nu interrogerait la grappe par défaut de la machine.
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" \
  -c "SELECT count(*) FROM arac.memory_atoms;"
```

> `ls` sur `/var/backups/arac` **sans** le sous-dossier vous montrerait aussi les dumps des
> autres cerveaux de la machine. Le pire jour est le mauvais moment pour choisir un fichier
> dans une liste où tous les noms se ressemblent : ne regardez que le vôtre.

**Ce que rend la seconde commande quand le sinistre est réel.** Elle n'affiche pas un
nombre, elle affiche du rouge — et **c'est la mesure que vous étiez venu chercher**, pas
une faute de frappe de votre part. Il y a **trois** formes, et elles ne racontent pas la
même histoire :

| ce que vous lisez | ce que ça veut dire | ce que ça change pour la suite |
|---|---|---|
| `ERROR: relation "arac.memory_atoms" does not exist` | la base est là, son **schéma** est détruit | rien : le chapitre marche tel qu'il est écrit |
| `ERROR: permission denied for schema arac` | la base est là, ses **droits** sont perdus | rien non plus |
| `FATAL: database "<votre_base>" does not exist` — remarquez `FATAL`, pas `ERROR` : `psql` n'a même pas pu ouvrir la connexion | **la base n'existe plus du tout** | l'étape 5.2 va rendre une erreur, et c'est normal — lisez l'encadré de la bascule |

Mesuré sur un cerveau à qui l'on venait de faire un `DROP DATABASE` — la commande est
exactement celle du bloc ci-dessus, et voici ce qu'elle a rendu :

```
psql: error: connection to server on socket "…" failed:
FATAL:  database "…" does not exist
```

La question à trancher est : **la base vivante est-elle perdue, ou seulement
abîmée ?** Une base abîmée dont on n'a rien mesuré, restaurée par réflexe, c'est
une perte de données volontaire. Les deux premières formes disent « abîmée », la
troisième dit « perdue » — et c'est la seule différence que le reste du chapitre
vous demandera de vous rappeler.

### Étape 1 — choisir le dump, et le prouver AVANT de s'en servir

```bash
sudo ARAC_ENV_FILE="$COFFRE" \
     ops/restore_verify.sh "/var/backups/arac/$BASE/$BASE-2026-08-05T010000Z.dump"
echo "code = $?"
```

**Le verdict que vous attendez ici est `2`, pas `0`.** Il s'écrit « RESTAURÉ, preuve
partielle » et il est le bon : les preuves A (les tables vitales), B (les lignes se
relisent, échantillon d'atomes à l'appui) et D (ce dump porte l'empreinte de CE cerveau)
sont rendues ; seule la preuve C — comparer au cerveau vivant — ne peut pas l'être,
puisque le cerveau vivant est justement ce qui est cassé. Le script l'écrit lui-même :
« *ce n'est PAS un défaut du dump […] Code de sortie 2, et non 1.* »

**Le `2` vaut pour les trois formes du sinistre**, y compris la plus totale. Mesuré sur le
cerveau dont la base venait de disparaître : PREUVE A ✓, PREUVE B « 9 atomes, 9 embeddings
relus, 3072 dimensions », PREUVE D « ✓ empreinte d'installation identique », PREUVE C
« ~ base vivante injoignable — comparaison impossible », **code de sortie 2**. Un cerveau
sans base ne fait pas rougir ce contrôle : il le rend partiel, et il le dit.

**Le seul code qui condamne un dump est le `1`** — et il vous dit **lequel des deux vient
d'échouer**, parce que les gestes n'ont rien en commun :

- **la restauration** — `pg_restore` a rendu une erreur. Le fichier est inutilisable.
  Mesuré sur un dump tronqué : « *ÉCHEC : pg_restore a rendu une erreur* », puis, dans le
  journal, « *le dump […] ne se restaure pas. Le coffre est vide.* » **Là, oui : prenez le
  dump précédent et recommencez.** Restaurer un dump qui vient d'échouer sa vérification,
  c'est remplacer un problème connu par un problème inconnu ;
- **l'identité** — le fichier se restaure parfaitement, mais **il ne vient pas d'ici**. Le
  contrôle ne le devine pas au nom du fichier : le bootstrap grave l'**empreinte
  d'installation dans le commentaire du schéma**, donc elle voyage *à l'intérieur* du
  dump, et `pg_dump` l'emporte avec les tables. Mesuré, dump du voisin passé au coffre du
  nôtre :

```
PREUVE D — ce dump vient-il de CE cerveau ?
  ✗ CE DUMP N'EST PAS LE VÔTRE.
       empreinte dans le dump : ec04294a…   (cerveau « doc14b », poste « poste-doc14b »)
       empreinte de ce cerveau : 80bff73a…   (cerveau « doc14a »)
VERDICT : ÉCHEC — ce dump se restaure, mais il ne vient PAS de ce cerveau.
          Ne touchez pas à vos sauvegardes : elles ne sont pas en cause.
```

  « Ce dump n'est pas le vôtre » **clôt la question** : ne cherchez pas ailleurs dans vos
  sauvegardes, elles ne sont pas en cause — vous avez désigné le mauvais fichier, ou le
  mauvais coffre.

> **La seule exception, et il faut la connaître avant d'en avoir besoin : un `1` dont
> PREUVE D est ✓ n'accuse pas votre dump.** Il ne peut sortir que d'une chose — la base à
> laquelle on vient de comparer n'est pas celle d'où ce dump vient. C'est exactement
> l'état d'un cerveau **fraîchement installé sur une autre machine** : il répond, il se
> lit, et il est **vide**. PREUVE C tourne alors pour de bon et tombe. Mesuré :
> « *✓ empreinte d'installation identique* » suivi de « *✗ le dump contient plus d'atomes
> que la base vivante* », « *VERDICT : ÉCHEC — ce dump n'est pas une sauvegarde
> utilisable* », code 1 — sur un dump parfait, celui-là même qui a reconstruit le cerveau
> dix minutes plus tard. **Lisez PREUVE D avant de lire le code.** Si vous êtes en train
> d'emménager sur une machine neuve, vous n'êtes pas dans ce chapitre : allez au § 9.

Un `1` accompagné de « *ARRÊT AVANT TOUT GESTE* » n'accuse ni votre dump ni votre coffre :
il dit que vous avez oublié `ARAC_ENV_FILE` **et** que ce clone ne suffit pas à désigner
un cerveau. La ligne qui suit énumère les coffres de la machine, prête à recopier.

### Étape 2 — déchiffrer, si nécessaire

```bash
# Un dump déchiffré est le cerveau entier EN CLAIR : il ne va pas dans /tmp,
# que toute la machine peut lister. Il va dans le dossier de CE cerveau, en 0700.
sudo install -d -m 0700 -o root -g root "/var/backups/arac/$BASE"
sudo age -d -i ~/arac-backup-$BASE.key \
     -o "/var/backups/arac/$BASE/$BASE-restauration.dump" \
     "/var/backups/arac/$BASE/$BASE-2026-08-05T010000Z.dump.age"
CLAIR="/var/backups/arac/$BASE/$BASE-restauration.dump"
```

> **La clé porte le nom du cerveau, et ce n'est pas une coquetterie.** Une clé
> `~/arac-backup.key` serait la **même identité de déchiffrement pour tous les cerveaux**
> que ce poste restaure : celui qui la détient les lit tous. `ops/restore_verify.sh` le dit
> à l'écran quand il en réclame une.

### Étape 3 — restaurer dans une base NEUVE, jamais par-dessus la vivante

```bash
NEUVE="${BASE}_restauree_20260805"
sudo -u postgres createdb -p "$PGPORT_BASE" "$NEUVE"
sudo -u postgres psql -p "$PGPORT_BASE" -d "$NEUVE" \
  -c "CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;"
sudo cat "${CLAIR:-/var/backups/arac/$BASE/$BASE-2026-08-05T010000Z.dump}" \
  | sudo -u postgres pg_restore -p "$PGPORT_BASE" --dbname="$NEUVE" \
        --no-owner --no-privileges
```

**Le `-p "$PGPORT_BASE"` est la moitié de cette étape.** Sans lui, `createdb` fabrique la
base neuve sur la grappe **par défaut** de la machine, `pg_restore` y charge votre mémoire,
et l'étape 5 renomme… une base qui n'est pas sur le serveur de votre cerveau. Vous
croiriez avoir restauré, et le cerveau redémarrerait sur la base avariée.

**Et le `sudo cat` n'est pas un ornement non plus** : le dossier des dumps est en
`0700 root:root` — le compte `postgres` ne peut pas ouvrir le fichier, et `pg_restore`
s'arrête sur `could not open input file … Permission denied`. Root lit, PostgreSQL charge ;
les droits du coffre restent ce qu'ils doivent être.

Pas de `-j` (parallèle) : sur un schéma avec contraintes croisées, le gain de
minutes ne vaut pas le risque d'un ordre de restauration qui échoue à moitié.

Le nom de la base neuve **dérive du vôtre**. Sur une machine à deux cerveaux, un nom de
travail générique — `arac_restored`, `arac_tmp` — est le début du même accident : deux
restaurations concurrentes se marchent dessus, et l'on bascule la mauvaise.

### Étape 4 — regarder ce qu'on a récupéré, avant de basculer

**Dans `$NEUVE`, pas dans la base vivante** — c'est la base restaurée qu'on inspecte, et
elle ne porte pas encore votre nom :

```bash
sudo -u postgres psql -p "$PGPORT_BASE" -d "$NEUVE" <<'SQL'
SELECT count(*) FROM arac.memory_atoms;
SELECT count(*) FROM arac.conversations;
SELECT max(received_at) FROM arac.raw_messages;   -- jusqu'où va la récupération ?
SELECT version_num FROM arac.alembic_version;     -- ce code sait-il lire ces données ?
SQL
```

**La dernière ligne est celle qu'on oublie.** Si la version de schéma restaurée
est plus ancienne que ce que le code attend, il faut appliquer les migrations
manquantes sur la base restaurée **avant** de la mettre en service. C'est précisément ce
que fait l'étape 5.3, après la bascule : vous n'avez rien à jouer ici.

### Étape 5 — la bascule

C'est le moment irréversible. Arrêtez tout ce qui écrit **dans ce cerveau-là**, renommez,
réappliquez les droits, redémarrez :

```bash
# 1. arrêter — SEULEMENT les unités de ce cerveau
sudo systemctl stop "arac-$BASE-api" "arac-$BASE-cockpit" \
                    "arac-$BASE-cycle.timer" "arac-$BASE-sauvegarde.timer"

# 2. renommer — jamais supprimer, et sur la grappe de CE cerveau
#    LA PREMIÈRE DES DEUX LIGNES REND UNE ERREUR ROUGE SI VOTRE BASE A DISPARU,
#    et c'est NORMAL — voir l'encadré juste après ce bloc. Ne vous arrêtez pas.
sudo -u postgres psql -p "$PGPORT_BASE" -d postgres \
  -c "ALTER DATABASE \"$BASE\"   RENAME TO \"${BASE}_avarie_20260805\";"
sudo -u postgres psql -p "$PGPORT_BASE" -d postgres \
  -c "ALTER DATABASE \"$NEUVE\"  RENAME TO \"$BASE\";"

# 3. la PROPRIÉTÉ, la PORTE et les DROITS — pas les rôles, qui n'ont pas bougé.
#    `pg_restore --no-owner` a rendu le schéma « arac » à `postgres`, sans un
#    seul droit pour les rôles de votre cerveau : en l'état, ni l'API ni
#    alembic ne peuvent lire une ligne. Et une base fabriquée par `createdb`
#    naît GRANDE OUVERTE : tout rôle de la grappe peut s'y connecter.
#    Cette commande fait TROIS choses, dans cet ordre — elle REFERME la base
#    (REVOKE CONNECT … FROM PUBLIC, puis CONNECT aux quatre rôles de votre
#    cerveau), elle REPREND la propriété du schéma et de tous ses objets,
#    PUIS elle applique les migrations et réapplique les droits sur ce
#    qu'elles créent. Elle dérive les cinq noms de rôles du nom de votre
#    cerveau : elle n'en crée aucun et ne change aucun mot de passe.
sudo ./bootstrap/bootstrap.sh --only migrations

# 4. redémarrer — les DEUX services ET les DEUX minuteries arrêtées en 1.
#    Sans la seconde ligne, votre cerveau repart sans digestion et SANS
#    SAUVEGARDE, le jour où vous venez d'apprendre ce que vaut une sauvegarde.
sudo systemctl start "arac-$BASE-api" "arac-$BASE-cockpit"
sudo systemctl start "arac-$BASE-cycle.timer" "arac-$BASE-sauvegarde.timer"

# 5. constater
sudo ./bootstrap/checks/verify_install.sh
```

> ### ⚠ LE ROUGE DE L'ÉTAPE 5.2 — celui qui est normal, et celui qui ne l'est pas
>
> **Si votre base a disparu, la toute première commande de ce bloc rend une erreur, et
> vous devez continuer.** C'est le seul endroit du chapitre où l'on vous demande de passer
> outre du rouge, alors il est écrit ici et nulle part ailleurs.
>
> Mesuré, sur un cerveau dont la base venait d'être détruite pour de vrai — les deux
> commandes du 5.2, telles qu'elles sont écrites ci-dessus, ont rendu ceci :
>
> ```
> ERROR:  database "…" does not exist
> rc_rename_avarie=1                       ← NORMAL : il n'y a rien à mettre de côté
>
> ALTER DATABASE
> rc_rename_neuve=0                        ← C'EST CELLE-CI QUI COMPTE
> ```
>
> **La règle, en une phrase : c'est la SECONDE ligne qui doit réussir.** La première ne
> fait que mettre l'ancienne base de côté ; si l'ancienne base n'existe plus, il n'y a rien
> à mettre de côté et l'erreur ne dit rien d'autre que ça. Vous l'aviez d'ailleurs déjà
> appris au « respirez, et mesurez » : c'est la troisième forme, le `FATAL: database … does
> not exist`.
>
> **Les rouges qui, eux, doivent vous arrêter :**
>
> | ce que rend la ligne 2 | ce qui s'est passé | quoi faire |
> |---|---|---|
> | `ERROR: database "<base>_restauree_<date>" does not exist` | la base restaurée n'est pas là où vous croyez — le plus souvent : l'étape 3 s'est faite **sans `-p`**, donc sur la grappe par défaut de la machine | ne renommez rien, reprenez l'étape 3 avec `-p "$PGPORT_BASE"` |
> | `ERROR: database "<base>" already exists` | la base vivante existe encore : la ligne 1 n'a **pas** été jouée, ou elle a échoué pour une autre raison que l'absence | arrêtez-vous et relisez la sortie de la ligne 1 |
> | `ERROR: database "…" is being accessed by other users` | quelque chose écrit encore dans ce cerveau | reprenez le 5.1 — et regardez `systemctl list-units 'arac-<base>-*'` |
>
> **Et la conséquence, à connaître avant d'arriver à l'étape 7 :** sur une base **perdue**,
> aucune base `<base>_avarie_<date>` ne naît. La requête de l'étape 7 ne rendra rien, et
> c'est juste — il n'y a pas de « cerveau d'avant » à garder quelques jours, puisqu'il n'y
> en avait plus au moment de la bascule. Mesuré : la requête de l'étape 7 rend zéro ligne
> après une bascule sur base perdue, et rend `doc14b_avarie_20260809 (10 Mo)` après une
> bascule sur base abîmée.

> **Pourquoi `--only migrations` et pas un fichier de rôles.** `db/migrations/04_roles.sql`
> n'existe pas : il n'y a qu'un **gabarit** `.sql.template`, dont les noms de rôles sont des
> marqueurs à substituer. Le rejouer tel quel, c'est exécuter des `CREATE ROLE … PASSWORD`
> sur des noms non préfixés — donc écraser les comptes du cerveau voisin. L'étape
> `migrations` du bootstrap fait la seule chose dont une restauration a besoin — reprise de
> la propriété et des droits, **puis** `alembic upgrade head`, **puis** de nouveau les
> droits sur ce que les migrations viennent de créer — et elle **dérive** les noms de rôles
> au lieu de les écrire. L'ordre n'est pas indifférent : `alembic` lit
> `arac.alembic_version` à sa première ligne, sous le rôle d'administration. Tant que la
> reprise venait après, cette étape mourait sur « permission denied for schema arac », et le
> remède qu'elle imprimait rendait la même erreur.
>
> **La troisième chose que fait le 5.3, et pourquoi elle n'est pas facultative.** Une base
> née d'un `createdb` — celle de l'étape 3 — est **ouverte à tous les rôles de la grappe**.
> Ce n'est pas une supposition : mesuré juste avant le 5.3, `datacl` est NULL sur la base
> restaurée, `has_database_privilege('public', …, 'CONNECT')` rend `t`, et un rôle créé
> pour l'occasion, qui ne dérive de rien et n'a rien à voir avec ce cerveau, s'y est
> connecté (`connecté comme doc14_curieux`). Le même contrôle après le 5.3 :
> `datacl = {=T/postgres, …, arac_doc14a_admin=c/…, _app=c/…, _agent=c/…, _readonly=c/…}`,
> `has_database_privilege('public', …)` rend `f`, et le curieux reçoit
> « *FATAL: permission denied for database "doc14a" — User does not have CONNECT
> privilege.* » Sur une machine à plusieurs cerveaux, sauter le 5.3 laisse donc votre
> mémoire restaurée derrière une porte ouverte, y compris pour les rôles du voisin.
>
> **Pourquoi `verify_install.sh` plutôt qu'un `curl` sur un port.** Après une bascule, la
> question n'est pas « quelque chose répond-il ? » mais « **est-ce mon cerveau qui
> répond ?** ». `verify_install.sh` remonte la socket jusqu'au PID, puis lit `ARAC_DB` dans
> son environnement. Un `200` obtenu autrement ne prouve rien. Il fait trois choses de plus
> que compter des services, et chacune répond à une question que la bascule vient de poser :
> il **lit réellement `arac.memory_atoms` sous chacun des quatre rôles** — « *N souvenir(s)
> lus SOUS CE RÔLE* », donc il ne peut plus certifier « Ce cerveau fonctionne » sur une base
> dont l'application ne peut lire une ligne (la panne la plus probable d'après-bascule, et
> la seule que ce contrôle ne savait pas voir) ; il **compare l'empreinte gravée dans la
> base à celle de votre coffre** — « *✓ empreinte de la base … c'est bien la mémoire de
> cette installation* », ou « *✗ CE N'EST PAS LE CERVEAU DE CETTE INSTALLATION* » si vous
> avez restauré le mauvais dump ; et il **nomme `<base>_avarie_<date>` pour ce qu'elle
> est** — « *⚠ copies de la mémoire sur cette grappe   doc14b_avarie_20260809 (10079 kB)* »,
> avec sa taille, sous un intitulé qui ne laisse aucun doute sur ce qu'elle contient.

**Ce que le rapport doit dire, et ce qu'il ne doit pas dire.** Après cette étape, les
quatre lignes « lecture arac_<base>_admin / _app / _agent / _readonly » portent un compte
de souvenirs — pas un simple « connexion acceptée ». La ligne « propriétaire du schéma
arac » nomme `arac_<base>_admin`, jamais `postgres`. Et le verdict se termine par
**« en échec 0 »**. S'il reste des réserves, lisez-les : celle qui nomme
`<base>_avarie_…` est **attendue** — c'est l'étape 7 ci-dessous.

**On renomme, on ne supprime pas.** L'ancienne base garde son nom d'avarie
jusqu'à ce que la nouvelle ait fait ses preuves pendant plusieurs jours. Le
disque coûte moins cher qu'un regret.

### Étape 6 — refermer

```bash
# une sauvegarde de l'état restauré, tout de suite — par l'UNITÉ, qui porte le
# coffre et le dépôt de CE cerveau
sudo systemctl start "arac-$BASE-sauvegarde.service"
sudo journalctl -u "arac-$BASE-sauvegarde.service" -n 5 --no-pager   # → "backup.done"

# et sa preuve, par l'unité elle aussi
sudo systemctl start "arac-$BASE-restauration.service"
sudo journalctl -u "arac-$BASE-restauration.service" -n 40 --no-pager
#    → "VERDICT : PROUVÉ — ce dump se restaure, et le cerveau en sort entier."
```

> **Pourquoi les unités et pas `ops/backup.sh` en direct.** Appelés à la main sur une
> machine qui porte plus d'un cerveau, ces deux scripts **agissent** : ils servent le
> cerveau que le clone d'où vous tapez décrit, après l'avoir annoncé (« *ops/ sert le
> cerveau « … » — ce dépôt le décrit, il n'a pas été deviné* »). C'est commode et c'est
> exact — tant que ce clone est bien celui de ce cerveau-là. Les unités, elles, portent
> `ARAC_ENV_FILE` et `ARAC_HOME` dans leur définition : elles **ne peuvent pas** se
> tromper de cerveau, quel que soit le dossier courant, et c'est pourquoi ce sont elles
> qu'on lance ici. Si vous tenez à les lancer à la main, préfixez-les de
> `sudo ARAC_ENV_FILE="$COFFRE"`.

Écrivez ce qui s'est passé quelque part que vous relirez. Ce que vous venez
d'apprendre sur votre propre installation ne se retrouve pas dans ce document.

### Étape 7 — les bases que cette bascule laisse derrière elle

Une restauration laisse derrière elle **une base, ou deux** — cela dépend de la forme du
sinistre que vous avez mesurée au tout début, et c'est la seule chose que cette étape vous
demande de vous rappeler :

| base | née à | ce qu'elle contient | ce qu'on en fait |
|---|---|---|---|
| `<base>_restauree_<date>` | étape 3 | une copie complète du cerveau | elle n'existe **plus** si la bascule est allée jusqu'au bout : l'étape 5.2 l'a renommée en `<base>`. Si elle est encore là, c'est que la bascule s'est arrêtée en chemin — reprenez à l'étape 5, ou détruisez-la |
| `<base>_avarie_<date>` | étape 5.2, **si et seulement si la base vivante existait encore** | votre cerveau **d'avant**, entier, en clair | on la **garde** quelques jours, exprès. Puis on la détruit — voir ci-dessous |

> **Base perdue : la ligne du bas ne vous concerne pas, et la requête ci-dessous rendra
> zéro ligne.** C'est le cas où l'étape 5.2 a rendu du rouge sur sa première commande. Il
> n'y a pas de « cerveau d'avant » à garder : il avait disparu avant que vous n'arriviez.
> Mesuré des deux côtés — zéro ligne après une bascule sur base perdue,
> `doc14b_avarie_20260809 (10079 kB)` après une bascule sur base abîmée. Ne cherchez pas ce
> que vous avez raté : vous n'avez rien raté.

**Elles pèsent ce que pèse votre mémoire** et personne ne les surveille : ni rotation, ni
chiffrement, ni plancher de sincérité. Ce sont des copies en clair de tout ce que vous
savez, posées sur la même grappe que le cerveau vivant.

`bootstrap/checks/verify_install.sh` les nomme désormais à chaque passage, sous
« copies de la mémoire sur cette grappe », avec leur taille. Ce n'est pas une panne ; c'est
une chose à savoir, et une décision à prendre.

**Le jour où la nouvelle base a fait ses preuves** — quelques jours, pas quelques minutes :

```bash
# ce qui existe encore, avant de détruire quoi que ce soit
sudo -u postgres psql -p "$PGPORT_BASE" -tAc \
  "SELECT datname, pg_size_pretty(pg_database_size(datname))
     FROM pg_database
    WHERE datname LIKE '${BASE}\_avarie\_%'
       OR datname LIKE '${BASE}\_restauree\_%' ORDER BY 1"

# puis, nom par nom — jamais une boucle qu'on n'a pas lue
sudo -u postgres dropdb -p "$PGPORT_BASE" "${BASE}_avarie_<date>"
```

> **Et si vous ne le faites jamais ?** Elles vous rattraperont le jour de la
> désinstallation. Une base d'avarie **retient les `DROP ROLE`** de
> [`INSTALLATION.md`](INSTALLATION.md) §13 :
>
> ```
> ERROR:  role "arac_doc14b_admin" cannot be dropped because some objects depend on it
> DETAIL:  privileges for database doc14b_avarie_20260809
>          owner of database doc14b_restore_template
>          49 objects in database doc14b_avarie_20260809
> ```
>
> **Ne comptez pas les rôles qui tombent — lisez le `DETAIL`.** Combien refusent dépend de
> ce que la base retenue accorde encore : mesuré une fois **quatre sur cinq**, mesuré une
> autre fois **les cinq**, sur la même version du produit. Le `DETAIL`, lui, **nomme la
> base qui retient**, à chaque fois. Le §13 les cherche à son étape 4 bis, et
> `ops/uninstall_check.sh` les nomme pour ce qu'elles sont. Mais le meilleur moment pour
> s'en défaire est celui où l'on sait encore ce qu'elles sont.

---

## 8. Ce qui n'est pas fait, et pourquoi

**Pas de PITR / archivage des WAL.** Ce dépôt fait des sauvegardes *logiques*
(`pg_dump`), **quatre par jour** — la minuterie posée par le bootstrap porte
`OnCalendar=*-*-* 00,06,12,18:30:00 UTC`, et vous pouvez le relire chez vous avec
`systemctl cat arac-<base>-sauvegarde.timer | grep OnCalendar`. La conséquence est simple
et il faut la connaître : **vous pouvez perdre jusqu'à six heures.** Pour un cerveau nourri par cycles de
digestion, avec un substrat qui vit aussi sur le poste source, c'est un
compromis défendable — pas une fatalité. Si votre tolérance est plus basse,
`archive_command` et un archivage WAL sont la suite logique ; ils demandent un
stockage continu, une supervision de plus, et une procédure de restauration
sensiblement plus complexe.

**Pas de sauvegarde du répertoire d'installation.** Le code est dans git, les
secrets sont dans un `.env` que vous devez sauvegarder **séparément et
autrement** (un gestionnaire de mots de passe, pas ce répertoire). Ce que ces
scripts sauvegardent, c'est la base.

**Pas de restauration automatisée vers la production.** Cf section 7. C'est un
choix, pas un manque.

---

## 9. Emporter son cerveau ailleurs — la migration, et ce qu'il faut emporter avec

Ce chapitre-ci n'est pas un chapitre de panique. C'est celui du déménagement : un serveur
qu'on rend, un hébergeur qu'on change, une machine plus grosse. Il est ici parce qu'il ne
se joue qu'avec un dump, et parce que la moitié des gestes sont ceux du § 7.

> **La phrase à retenir avant toute autre :**
> **un dump n'est pas votre cerveau — c'est sa mémoire.**
> Son identité, elle, vit dans `config/brain.toml`. Partez sans lui et vous arriverez
> avec une mémoire que rien ne rattache à personne.

### Ce qu'on emporte — trois choses, pas une

| quoi | où c'est | pourquoi c'est indispensable |
|---|---|---|
| **le dump** | `/var/backups/arac/<base>/`, ou celui de l'étape 2 du § 13 | la mémoire elle-même |
| **`config/brain.toml`** | dans votre clone | il porte l'**empreinte d'installation**. Sans lui, la machine d'arrivée en fabrique une neuve, et votre propre cerveau ne se reconnaît plus dans son propre dump |
| **`config/scopes.toml`** | dans votre clone | la forme de la mémoire. Les atomes portent des chemins de scopes ; une taxonomie différente à l'arrivée, et la clé étrangère refuse la restauration |

Les secrets, eux, **ne se déménagent pas** : le bootstrap en fabrique de neufs sur la
machine d'arrivée. C'est voulu — un jeton porteur qui a vécu sur un serveur qu'on rend
n'a rien à faire sur le suivant. Notez seulement de **reprendre le même `node_id`**, sans
quoi la provenance de tout ce qui est déjà entré se scinde en deux populations.

### Ce qui se passe si l'on part sans la description — mesuré

Même prénom, même nom de cerveau, même poste, même taxonomie, refaits à l'entretien sur la
machine d'arrivée. Le résultat n'est pas le même cerveau :

```
empreinte du cerveau d'origine : ec04294aa534443a9fc0257bc408b7a1
empreinte après ré-entretien   : 9e21f2a280ad43fbbd8d1a65cee05324
```

Et le contrôle de restauration, à qui l'on présente alors votre propre dump, répond :

```
PREUVE D — ce dump vient-il de CE cerveau ?
  ✗ CE DUMP N'EST PAS LE VÔTRE.
VERDICT : ÉCHEC — ce dump se restaure, mais il ne vient PAS de ce cerveau.       code 1
```

**Et cela ne se rattrape pas après coup.** Remettre le bon `config/brain.toml` une fois le
cerveau installé fait refuser le bootstrap, et il a raison de refuser — c'est exactement
la protection qui empêche un homonyme de reprendre le coffre d'un autre :

```
✗ REFUS — ce cerveau porte votre nom, pas votre empreinte.
   empreinte trouvée 9e21f2a2…        empreinte attendue ec04294a…   (config/brain.toml)
Rien n'a été lu de ce coffre, rien n'a été écrit.                                 code 6
```

Le geste qu'il propose alors — recopier dans `brain.toml` l'empreinte que la machine porte
déjà — est le bon **quand on a perdu sa description**. Ce n'est **pas** le bon quand on
déménage : il vous ferait adopter définitivement l'identité du cerveau vide que vous venez
de créer. Dans ce cas, désinstallez-le (§ 13 d'[`INSTALLATION.md`](INSTALLATION.md), il n'a
rien à perdre) et recommencez avec la description que vous aviez emportée.

### Le déménagement, geste par geste

Sur la machine d'arrivée, avec vos trois fichiers sous la main :

```bash
git clone <l-adresse-de-ce-depot> /opt/<votre_base> && cd /opt/<votre_base>
make venv

# 1. la DESCRIPTION emportée remplace l'entretien — ne relancez PAS wizard.py
cp /votre/sauvegarde/brain.toml  config/brain.toml
cp /votre/sauvegarde/scopes.toml config/scopes.toml
.venv/bin/python bootstrap/generate_scopes.py     # doit rendre vos N racines / M feuilles

# 2. l'installation normale — elle crée la base, les rôles, les unités, un coffre NEUF
sudo ARAC_DB_PORT=<le port de la grappe d'ici> ./bootstrap/bootstrap.sh
sudo grep '^ARAC_INSTALL_UUID=' /etc/arac/<votre_base>/arac.env   # doit rendre VOTRE empreinte

# 3. la mémoire — c'est le § 7, étapes 3 à 5, sans l'étape 1 ni l'étape 2
BASE=<votre_base>; PGPORT_BASE=<le port>; NEUVE="${BASE}_restauree_$(date -u +%Y%m%d)"
sudo systemctl stop "arac-$BASE-api" "arac-$BASE-cockpit" \
                    "arac-$BASE-cycle.timer" "arac-$BASE-sauvegarde.timer"
sudo -u postgres createdb -p "$PGPORT_BASE" "$NEUVE"
sudo -u postgres psql -p "$PGPORT_BASE" -d "$NEUVE" \
  -c "CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;"
sudo cat /votre/sauvegarde/<le dump> \
  | sudo -u postgres pg_restore -p "$PGPORT_BASE" --dbname="$NEUVE" --no-owner --no-privileges
# la base que le bootstrap vient de créer est VIDE, mais on la met de côté
# comme partout ailleurs — et on garde le suffixe « _avarie_ », le seul que
# le § 13 (étape 4 bis) et les contrôles savent retrouver.
sudo -u postgres psql -p "$PGPORT_BASE" -d postgres \
  -c "ALTER DATABASE \"$BASE\"  RENAME TO \"${BASE}_avarie_$(date -u +%Y%m%d)\";"
sudo -u postgres psql -p "$PGPORT_BASE" -d postgres \
  -c "ALTER DATABASE \"$NEUVE\" RENAME TO \"$BASE\";"
sudo ./bootstrap/bootstrap.sh --only migrations
sudo systemctl start "arac-$BASE-api" "arac-$BASE-cockpit" \
                     "arac-$BASE-cycle.timer" "arac-$BASE-sauvegarde.timer"

# 4. constater, puis PROUVER
sudo ./bootstrap/checks/verify_install.sh
sudo systemctl start "arac-$BASE-sauvegarde.service"
sudo ARAC_ENV_FILE="/etc/arac/$BASE/arac.env" ops/restore_verify.sh
```

**Ce que doit rendre la dernière commande, et c'est le seul critère :**

```
  ✓ empreinte d'installation identique — ce dump est bien celui de « <votre_base> »
  ✓ empreinte des atomes identique de part et d'autre (383dccee…)
VERDICT : PROUVÉ — ce dump se restaure, et le cerveau en sort entier.            code 0
```

Puis détruisez `<base>_avarie_<date>` : elle ne contient rien — c'est la base vide du
bootstrap —, mais elle retiendra vos `DROP ROLE` le jour où vous désinstallerez cette
machine-ci. `verify_install.sh` la nommera d'ici là sous « copies de la mémoire sur cette
grappe » : ici, et ici seulement, cette réserve ne recouvre aucune mémoire.

> **Ce qu'il ne faut PAS faire, et pourquoi c'est tentant.** `pg_restore` **directement
> dans la base que le bootstrap vient de créer** paraît plus court d'une étape. Mesuré :
> **210 erreurs** et `rc=1` — « *schema "arac" already exists* », « *function … already
> exists with same argument types* », et ainsi de suite table après table. Les atomes
> arrivent quand même, ce qui est le pire des cas : un écran rouge sur lequel on n'a aucun
> moyen de savoir ce qui a été sauté. Et le cerveau qui en sort porte **l'empreinte du
> dump** dans son schéma et **celle du coffre neuf** dans son fichier d'environnement —
> `verify_install.sh` le refuse aussitôt : « *✗ empreinte de la base — CE N'EST PAS LE
> CERVEAU DE CETTE INSTALLATION* », « *✗ Ce cerveau n'est pas sain.* » On restaure dans une
> base neuve et on bascule : c'est plus long d'une commande, et c'est la seule forme qui se
> prouve.

### Et sur la machine qu'on quitte

Le déménagement n'est fini que quand l'ancienne machine ne porte plus votre mémoire.
C'est le § 13 d'[`INSTALLATION.md`](INSTALLATION.md) — **« Désinstaller », qui est aussi le
chapitre du départ** : il dit quoi faire des dumps qu'on garde, et son étape 9 vérifie, à
l'empreinte et non au nom, qu'il ne reste rien.
