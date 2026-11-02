# Journal des versions

Toutes les modifications notables de ce dépôt sont consignées ici.

Le format suit l'esprit de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) et
la numérotation celui de [SemVer](https://semver.org/lang/fr/), avec **une règle propre à
ce projet** :

> Une ligne de ce journal ne dit jamais qu'une chose fonctionne si elle n'a pas été
> exécutée. Le cas échéant, elle porte la mention **« écrit, non exercé »**.

C'est la même doctrine que [`docs/ROADMAP.md`](docs/ROADMAP.md) et
[`docs/CONTRIBUER.md`](docs/CONTRIBUER.md) : un journal qui promet plus que ce qui a
tourné est un journal qu'on cesse de croire.

Rubriques employées : **Ajouté**, **Modifié**, **Corrigé**, **Retiré**, **Sécurité**,
**Connu et non résolu**.

> **Les numéros de ce journal ne sont pas tous ceux de `pyproject.toml`.** La version
> **1.0.0** a été publiée (étiquette du 2026-08-14) et `pyproject.toml` porte désormais le
> numéro de la dernière version publiée. Les entrées **0.1.x** ci-dessous, plus anciennes,
> numérotent en revanche des **lots de travail** antérieurs à cette publication, pas des
> versions : elles n'ont jamais été publiées sous ces numéros. C'est dit ici pour qu'un lecteur qui compare
> les deux et trouve un écart sache lequel des deux ment — aucun : ils ne comptent pas la
> même chose.

---

## [1.1.0] — 2026-11-03

Lot **les cycles ne tournent plus à vide**. Notes de version :
[`docs/RELEASE-NOTES-1.1.0.md`](docs/RELEASE-NOTES-1.1.0.md). Mise à jour : `git pull`
puis redémarrage des services du curateur ; aucune migration.

### Corrigé

- **Une clé d'atome récupérable n'est plus un motif de quarantaine.** Une clé avec
  majuscules, accents ou séparateurs est normalisée (NFKD, minuscules, tirets, 128
  caractères au plus) au lieu de faire quarantiner tout le run pour `key_invalid`. Le
  journal n'en garde que les empreintes, jamais la clé brute. Une clé normalisée qui
  retomberait sur la clé d'un autre atome du même document n'est pas normalisée : elle reste
  `key_invalid`, comme avant. Couvert par des tests hermétiques.
- **Fin des cycles vides en boucle.** Après deux quarantaines, la bisection ramenait la
  tranche à une seule conversation ; si son premier message dépassait le budget, chaque
  cycle sortait `empty` et rien ne relâchait la bisection : cycles vides et alertes sans fin.
  La bisection ne compte plus que les reçus terminaux (`done`, `quarantined`,
  `spawn_failed`) et se relâche dès qu'un reçu `empty` suit la dernière quarantaine
  (`cortex.bisection_released`). **Écrit, non exercé** contre une base réelle : testé par
  des tests hermétiques seulement.
- **Un message géant en tête ne monopolise plus le cycle.** Il est dédoublonné dans la
  file de revue (une ligne `pending` par message). S'il commence par un préfixe d'artefact
  d'outillage reconnu, le curseur passe par-dessus ce seul message sous trois gardes
  (curseur en arrière du message, message en tête de tranche, clé par conversation) ;
  sinon la conversation est mise de côté 7 jours, curseur intouché. Les préfixes se règlent
  par `ARAC_OVERSIZED_SKIP_PREFIXES` (12 à 120 caractères chacun ; hors de ces bornes, le
  préfixe est refusé et journalisé). L'alerte n'affirme plus « parqué 7 j » quand la mise de
  côté n'a touché aucune ligne. **Écrit, non exercé** : le SQL de saut et de mise de côté n'a
  été joué que par des tests hermétiques, jamais sur une base réelle.

### Sécurité

- **Le jeton du bot d'alerte n'est plus écrit dans les journaux.** L'URL de l'API du bot
  porte le jeton et `httpx`/`httpcore` la journalisaient en INFO ; leur niveau passe à
  WARNING avant l'envoi d'une alerte. Les journaux déjà écrits avant la mise à jour peuvent
  contenir ce jeton : s'ils ont été conservés ou partagés, renouvelez-le.

### Modifié

- **CI** : l'étape des gardes de l'acceptation installe `requirements.txt` dans un venv
  jetable (le `conftest` importe le moteur dès la collecte) ; le workflow des tests remplit
  le cache de l'encodage tiktoken avant la suite, qui compte toujours avec le vrai
  encodage ; deux tests de la porte du sous-processus déclarent la lecture des binaires de
  l'hôte sur un Python installé hors de `/usr`. Les en-têtes des workflows disent ce qui a
  tourné. **Non observé** : aucun passage vert sur GitHub n'est encore constaté.
- Un réglage de plafond de messages par conversation a été ajouté puis **retiré avant
  publication** (il pouvait perdre des messages en silence) : il n'existe pas dans cette
  version.

### Ajouté (docs)

- [`docs/ROADMAP.md`](docs/ROADMAP.md) : section « cap après 1.1 : la confiance dans la
  mémoire », cinq phases et quatorze chantiers, chacun avec l'état constaté, la cible
  (PROSPECTIF) et son critère de fin.
- [`docs/DEPANNAGE.md`](docs/DEPANNAGE.md) : « Les cycles sortent vides en boucle » ;
  [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) et `.env.example` :
  `ARAC_OVERSIZED_SKIP_PREFIXES`.

### Connu et non résolu

- Le SQL de saut et de mise de côté (voir plus haut) n'a jamais tourné sur une vraie base.
- Un parking de 7 jours peut être écrasé par tout autre écrivain de `next_retry_at`, et sort
  la conversation du backlog « actionnable » du watchdog pendant ce temps ; la ligne de la
  file de revue reste le signal humain.
- Le premier passage vert de la CI publique n'est pas encore observé.
- Les limites de la 1.0.0 demeurent : [`docs/LIMITES-CONNUES.md`](docs/LIMITES-CONNUES.md).

---

## [1.0.0] — 2026-08-14

Première version publique. Voir [`docs/RELEASE-NOTES-1.0.0.md`](docs/RELEASE-NOTES-1.0.0.md)
et le dossier [`docs/RELEASE-V1.md`](docs/RELEASE-V1.md). Ce journal n'avait pas d'entrée
pour elle : les lots 0.1.x ci-dessous la précèdent.

---

## [0.1.15] — 2026-08-10

Lot **on ne fait plus acheter la mauvaise chose**.

### Corrigé

- **Le vrai prérequis de la curation est dit, partout où quelqu'un décide.** L'étape 8 de
  l'installation faisait acquérir une **clé d'API Anthropic** « pour la curation », et
  déclarait un mode dégradé si on la refusait. Or la curation **n'appelle aucune API** :
  le cycle lance le **binaire `claude`** (Claude Code CLI) en sous-processus sur le
  serveur, sous le compte d'agent (`agents/lib/claude_cli.py`). Une clé sans ce binaire ne
  produit **pas un seul souvenir** ; un abonnement Claude déjà ouvert rend cette clé
  inutile. Réécrit en conséquence : [`README.md`](README.md) §4 (ce que ça coûte) et §5
  (le tableau des prérequis, colonne par colonne : *obligatoire ? à quoi ça sert ? le
  bootstrap le vérifie-t-il ?*), [`docs/DEMARRAGE-RAPIDE.md`](docs/DEMARRAGE-RAPIDE.md)
  (ce qu'il faut avoir sous la main, et l'écran réel de l'étape 1),
  [`docs/INSTALLATION.md`](docs/INSTALLATION.md) §1 et étape 8,
  [`docs/FAQ.md`](docs/FAQ.md) (« qu'est-ce que je dois vraiment acheter ? »),
  [`bootstrap/README.md`](bootstrap/README.md) §1 et §2, [`GOAL.md`](GOAL.md).
  **Rejoué** : `./bootstrap/bootstrap.sh --check` rend la section « La curation » avec la
  version du binaire et son mode d'authentification, et conclut « Votre serveur peut
  porter un cerveau — **et le digérer** » ; le binaire retiré, il conclut « Le serveur
  peut porter un cerveau. ⚠ Mais **PAS le faire apprendre** ».
- **L'étape 9 du démarrage rapide ne désigne plus une cause que le lecteur n'a pas.** Elle
  envoyait vérifier `ARAC_NODE_ID` — un défaut que l'étape 5 a déjà fait vérifier et que
  l'étape 8 aurait révélé. Les causes réelles sont désormais listées **dans l'ordre où le
  cycle refuse**, chacune avec le code que porte `journalctl` : les **deux interrupteurs
  de dépense**, fermés d'usine (`master_switch_env_off`, puis `master_switch_config_off`
  — le second vit **en base**, dans aucun fichier), le kill-switch, le binaire de curation
  ou son authentification (`spawn_failed`, « Not logged in »), le créneau déjà pris
  (`cortex.duplicate_slot`, et la valve `ARAC_CORTEX_FORCE_MANUAL` **à retirer après
  usage**), les plafonds du jour, la file vide — **et seulement ensuite** `ARAC_NODE_ID`.
  Mêmes corrections dans `INSTALLATION.md` §10, `DEPANNAGE.md` §5b, `PREMIER-JOUR.md`,
  `EXPLOITATION.md`, `CONFIGURATION.md` §5 et `FAQ.md`.
- **`mac/README.md` n'enseigne plus l'ancien pont.** `arac-pont.sh installer` demande
  **toujours** le nom du cerveau (sa question 0) et pose tout sous `~/.arac/<cerveau>/` en
  `0700` ; sans nom il **refuse en code 2** sans rien écrire. La page publiait encore le
  foyer commun et une commande de renvoi complet qui ne pouvait que rendre « fichier
  introuvable ». **Procédure exécutée**, pas relue : l'arborescence publiée est celle
  qu'une installation a réellement posée. Même correction dans
  `docs/COMMENT-IL-SE-SYNCHRONISE.md` (le `pont.conf` et le curseur).

### Modifié

- [`docs/RELEASE-V1.md`](docs/RELEASE-V1.md) **§4 est devenue un registre**, avec une date
  et un état mesuré à chaque manche — elle affirmait au présent que huit promesses étaient
  traversées par un harnais qui, à ce moment-là, n'en démontrait qu'une. État de cette
  manche, **rejoué** : `make acceptance` → `7 prouvée(s) · 2 partielle(s) · 0 non
  testée(s) · **0 en échec** · **0 intervention(s)**`, code 0 ; `make test` → `1 failed,
  5 486 passed`. Les neuf étapes du harnais sont détaillées une par une, et la seule
  promesse du produit qu'aucun essai ne traverse — *le cerveau apprend* — est nommée
  comme telle.
- [`docs/LIMITES-CONNUES.md`](docs/LIMITES-CONNUES.md) : §2.2 ne porte plus une **alarme
  périmée** (le corps que le mode payant postait, refusé en 422, est corrigé) mais garde
  ce qui reste vrai — ce mode n'a jamais été joué avec une vraie clé. Nouveau §4.1 : les
  **deux prérequis que personne ne vérifie**, `npm` (dont dépend le remède que l'étape 1
  prescrit) et l'espace disque.
- Deux comptes faux corrigés dans le dossier de publication : « les cinq `COMMENT-IL-*` »
  pour quatre fichiers, et « huit étapes » pour un harnais qui en a **neuf**.

### Connu et non résolu

- **Le cerveau qui APPREND reste la seule promesse du produit qu'aucun essai ne traverse.**
  `make acceptance` va jusqu'à la **frontière de dépense** — matière vue, tranche
  sélectionnée, cycle exécuté, refus tracé — et s'arrête là, délibérément : un essai qui
  doit rester gratuit et reproductible n'arme pas les interrupteurs. Ni atome par
  curation, ni embedding réel, ni rappel sémantique. Voir `LIMITES-CONNUES.md` §2.2.
- **Deux prérequis ne sont vérifiés par personne** : `npm` — dont dépend le remède que
  l'étape 1 prescrit quand le binaire de curation manque — et l'espace disque.
  `LIMITES-CONNUES.md` §4.1.

### Vérifié pour ce lot

- `make test` → `5487 passed, 215 skipped, 3 deselected, 5 xfailed`, **code 0**, mesuré
  deux fois de suite après ces modifications. *(Cette ligne a bougé deux fois dans la
  soirée : `4 failed` à 22:52, `1 failed` à 23:15, vert à 23:30 — d'où l'horodatage.)*
- `make acceptance` → `7 prouvée(s) · 2 partielle(s) · 0 non testée(s) · **0 en échec** ·
  **0 intervention(s)**`, code 0, banc entièrement démonté.
- **La production, mesurée par le harnais de part et d'autre de son passage** : services
  `active active`, sonde de l'API sur `8000` → `200`, **1 936 souvenirs**, empreinte des
  rôles du cluster 5432 `7c95f182815537e9` — **inchangée**.

---

## [0.1.14] — 2026-08-10

Lot **le dossier de publication est raccordé, et il a été rejoué avant d'être cru**.

### Ajouté

- [`docs/LIMITES-CONNUES.md`](docs/LIMITES-CONNUES.md) — **le seul endroit où vit une
  limite assumée.** Ce que le cerveau ne sait pas faire, ce qui n'a jamais été éprouvé de
  bout en bout, ce que le système ne peut pas garantir. Chaque entrée porte la commande
  qui la rejoue et un critère qui survit au changement de chiffre.
- [`docs/DECISIONS-ARCHITECTURE.md`](docs/DECISIONS-ARCHITECTURE.md) — quatorze décisions
  avec ce qu'elles écartent et ce qu'elles coûtent ; cinq sont nées de l'incident du
  8 août.
- [`docs/RELEASE-V1.md`](docs/RELEASE-V1.md) — le critère de sortie, l'échelle P0-P3, et
  le registre des constats ouverts.

### Modifié

- **Les trois documents ont été rejoués affirmation par affirmation avant d'être
  raccordés**, et six affirmations étaient fausses ou périmées : le nombre de relations de
  `arac.atom_links` (trois, pas une) et le nom de sa colonne ; la pondération du rappel par
  la confiance, annoncée « derrière deux drapeaux » alors qu'**aucune route servie
  n'importe ce module** ; le pont Mac, déclaré « jamais exécuté » alors que ses deux
  moitiés ont tourné sur Linux contre des cerveaux vivants ; la commande du mode payant,
  qui n'existe pas sous la forme annoncée **et qui meurt en 422** ; les trois minuteries
  armées par le bootstrap, qui ne sont pas celles qui étaient nommées ; le tableau des
  coûts, recopié sans l'avertissement qui l'accompagne. Le détail est en §6 des limites
  connues.
- **Le critère de santé à trois lignes est propagé** dans les pages qui enseignaient encore
  l'ancien : `docs/DEMARRAGE-RAPIDE.md` (tableau des étapes et étape 0),
  `docs/INSTALLATION.md` (point de contrôle 2), `docs/CONTRIBUER.md` et `GOAL.md`.
- **`docs/FAQ.md`** ne dit plus que seule la *simulation* du bootstrap a été vérifiée.
  Cette réponse portait une alarme périmée de plusieurs semaines, à l'endroit exact où l'on
  demande « est-ce que ça marche vraiment ? ». Elle dit maintenant ce qui a réellement
  tourné — installations complètes par le chemin interactif, cycle de vie entier jusqu'à la
  destruction et la remontée, deux cerveaux côte à côte — et ce qui n'a pas tourné : la
  moitié macOS du pont, la dépense réelle, la durée.

### Retiré

- **`docs/DECISIONS.md` n'est pas livré, et ne doit pas l'être.** Ce chemin est **réservé
  au lecteur** : le cockpit l'indexe pour peupler sa page « Décisions »
  (`control_center/collectors/reports_council.py`), et propose au lecteur d'y écrire les
  siennes. Le document du framework y a été déposé un instant ; il y affichait, dans le
  cockpit d'un inconnu, les arbitrages de quelqu'un d'autre présentés comme les siens — et
  il faisait rougir `make test` sur un clone neuf, c'est-à-dire au tout premier geste que
  le `README` demande. Il vit désormais sous `docs/DECISIONS-ARCHITECTURE.md`, et ses
  entrées sont numérotées `DA-01…DA-14`.

---

## [0.1.13] — 2026-08-10

Lot **quatre noms que Python ne savait pas résoudre étaient dans la livraison, et le
critère de santé du dépôt les a laissés passer**. C'est le lot le plus grave de
l'histoire de ce dépôt, et il n'est pas grave par la taille du correctif — trois lignes
d'`import` — mais par ce qu'il apprend sur la façon dont le dépôt se croyait vert.

Le jour où ce constat a été fait, `make test` rendait **5 266 tests verts** et
`make acceptance` rendait « 0 en échec » pour la troisième fois consécutive. Au même
moment, le produit livrait ceci :

| Où | Le nom | Ce qui mourait |
|---|---|---|
| `app/routers/dashboard.py:256` | `journal.sha8()` sans `from app import journal` | `GET /v1/dashboard/atoms_by_scope` → **500** sur un cerveau neuf et sain |
| `app/routers/dashboard.py:335` | idem | `GET /v1/dashboard/search` → **500** |
| `agents/cortex/pack.py:784` | `raison(exc)` sans son import | le filet `except TypeError` posé exprès pour que la digestion survive à des dates incomparables : **il tuait le cycle qu'il devait sauver** |
| `agents/lib/paid_ai_control.py:29-30` | `import paid_ai_flag` / `import kill_switch` | **le kill-switch de l'IA payante** — la commande qu'on tape quand la facture s'emballe — mort sur `ModuleNotFoundError` à sa première ligne |

Le quatrième n'était pas un `NameError` mais un `ModuleNotFoundError` : **invisible à
toute recherche de « nom non défini »**. Le mandat qui a ouvert cette manche en annonçait
trois ; le garde écrit pour les fermer en a trouvé quatre.

### Corrigé — les quatre noms

`from app import journal` dans `app/routers/dashboard.py`, `from app.journal import raison`
dans `agents/cortex/pack.py`, et les deux imports de `agents/lib/paid_ai_control.py`
repointés sur `agents.lib`, où ces modules vivent réellement.

### Ajouté — `tests/test_aucun_nom_non_resolu.py` : une négative universelle

Le garde ne relit pas le code : il le **charge** — chaque module de `app/`, `agents/`,
`control_center/`, chaque script Python livré hors paquet — puis parcourt tous ses
objets-code et demande à Python, pour chaque `LOAD_GLOBAL` / `LOAD_NAME` /
`DELETE_GLOBAL`, si ce nom pourra être trouvé à l'exécution.

Ce qu'il prouve est rare : ***aucun* module livré ne contient *aucun* nom qui lèverait
`NameError`.** Il n'énumère pas ce qu'il interdit — il énumère ce que le produit charge,
c'est-à-dire une liste que le dépôt possède déjà, et qui grandit toute seule.

### Ajouté — `tests/parcours.py` : ce que la session a réellement **emprunté**

Le bloc imprimé en fin de suite compte les routes, commandes et unités que le produit
expose, et celles dont le **corps** a réellement été exécuté. Le mouchard s'installe sur
`fastapi.routing.run_endpoint_function`, seul point par lequel FastAPI appelle une
fonction de route **après** avoir résolu ses dépendances.

C'est cette distinction qui a coûté trois manches : `make acceptance` appelait bien
`GET /v1/dashboard/search` — **sans jeton**, pour vérifier le 401. La route était
« atteinte » à chaque passage, et son corps n'avait jamais été exécuté une seule fois.

### Modifié — le critère de santé du dépôt, réécrit en première page

Le `README` a longtemps dit : *ce qu'il faut voir, c'est une ligne verte sans `failed`*.
**Ce critère a été satisfait par la livraison décrite ci-dessus.** Il en faut désormais
trois, dans cet ordre — le garde des noms vert, le bloc « ce que cette session a
réellement emprunté », puis la ligne pytest sans `failed` — plus une quatrième qui exige
une machine : `sudo make acceptance`, seule à répondre à *« ces chemins marchent-ils ? »*
plutôt qu'à *« sont-ils chargeables ? »*.

### Ce qu'il faut en retenir

**Un compte de tests verts ne dit pas ce qui a été exécuté.** Il dit combien d'assertions
ont tenu sur les chemins que quelqu'un a pensé à emprunter. Les trois filets du dépôt ont
laissé passer les quatre noms, chacun pour la même raison : **aucun n'exécutait le code
livré** — la suite se déclarait *skipped* sans base, `make lint` ne lit que du shell, et
le harnais n'entrait jamais dans le corps des deux routes.

Et le corollaire, qui vaut au-delà de ce dépôt : **un test qui surveille du code en
lisant son texte ne surveille rien.** Le kill-switch était couvert par un test qui
vérifiait, par `read_text()`, qu'une clause SQL figurait bien dans le fichier — sans
jamais demander à Python si le fichier était chargeable.

### Connu et non résolu

- La notice de `tests/test_aucun_nom_non_resolu.py` confie sa zone aveugle déclarée à
  `tests/test_parcours_des_chemins_livres.py`, **qui n'existe pas** : le fichier réel est
  `tests/parcours.py`. Le garde fonctionne ; c'est son renvoi qui tombe dans le vide.
  Aucune page de documentation ne cite ce nom.
- L'inventaire *hors paquet* du même garde est une liste de dossiers écrite à la main
  (`DOSSIERS_HORS_PAQUET`), alors que sa notice promet un inventaire qui grandit tout
  seul. C'est vrai des trois paquets, parcourus récursivement ; c'est faux du reste.

---

## [0.1.12] — 2026-08-10

Lot **le produit a pris de l'avance sur ses pages, et personne ne l'avait écrit**. Ce
journal se donne pour règle de ne jamais dire qu'une chose fonctionne sans l'avoir
exécutée. Il lui manquait la moitié symétrique, et ce lot la paye : **un journal qui TAIT
ce qui a été réparé fait croire à un danger éteint, et c'est le même prix** — un lecteur
qui renonce, ou qui installe ailleurs, sur une mesure périmée. Un module de sécurité
entier, `app/journal.py`, était dans l'arbre sans qu'aucune ligne d'ici le nomme, pendant
que trois pages continuaient d'annoncer la fuite qu'il venait de fermer, **sous le mot
« mesuré »**.

Le banc : instantané fidèle de `/root/arac-oss` (453 fichiers) → `git init` + `git clone`,
grappe `16/kz77` montée pour l'occasion sur le port **5690**, un cerveau « kz77a » né du
chemin réel (entretien `wizard.py` derrière un vrai pseudo-terminal, taxonomie à 3
domaines / 8 rangements), ports **8760/8762**, plus **8766** pour un double d'embeddings
déterministe en boucle locale. Banc entièrement démonté par le §13 joué mot pour mot.

### Sécurité — `app/journal.py` : ce qui a le droit d'entrer dans journald, tranché une fois pour tout le dépôt

Le module n'apparaissait **nulle part** dans ce journal, ni dans aucune page. Il pose la
règle **fermée par défaut** : toute chaîne venue des données est réduite à
`sha8:<empreinte>/<n caractères>` ; ce qui reste en clair doit se *démontrer* inoffensif
(un nombre, un booléen, une empreinte déjà calculée, un UUID engendré par la machine, un
littéral écrit dans le source). On n'entretient pas la liste de ce qui serait sensible :
une liste oublie, et ce qu'elle oublie est précisément ce que personne n'avait imaginé.

Il tranche aussi une question que le dépôt s'était posée deux fois en sens contraires —
**un domaine est-il un secret ? oui.** Un domaine n'est pas un identifiant technique : la
liste des domaines est le plan de l'existence de quelqu'un, et elle se lit plus vite que
le contenu d'un souvenir. L'empreinte étant stable, corréler deux lignes reste possible ;
ce qui se perd, c'est de *lire* le domaine dans un journal partagé.

Le garde ne tient pas par une énumération de sites : il enveloppe
`logging.getLogRecordFactory()`, donc **toute ligne du processus** — celles d'ARAC, celles
d'uvicorn, celles d'un module qui n'existe pas encore — passe par lui avant qu'un
collecteur ne la voie. Le filtre par logger reste posé en plus, sur le seul chemin qui a
déjà fui.

**Mesuré le 10 août 2026**, par la vraie route `POST /v1/atoms` puis `…/supersede`, sur le
cerveau de banc décrit ci-dessus :

```
{"message": "create_atom.warnings", "atom_id": "<UUID>", "warning_count": 3,
 "warnings": [{"code": "W-003", "severity": "info",
               "context": {"length": 53, "target_min": 200, "preview": "sha8:70b110c6/53"}},
              {"code": "W-007", "severity": "info",
               "context": {"scope": "sha8:cf35fd0b/11", …}}]}
```

Aucun `message` d'avertissement, aucun domaine, aucune clé, aucune étiquette, aucun
caractère du `rationale`. Le texte, lui, est en base et part avec le cerveau :
`arac.audit_log.warning_context` le rend en clair, sous les rôles du cerveau — relu à la
même seconde pour le vérifier. Puis, après un §13 joué **mot pour mot** jusqu'au
« VERDICT : PROPRE » en code 0, **en une seule passe** : seize motifs cherchés dans le
journal des cinq unités — valeurs, *pourquoi*, étiquettes, clés, les deux domaines et
trois mots du texte —, **aucun trouvé**, et la commande que la page donne elle-même
(`journalctl … | grep -i`) rend `rc=1` sans une ligne.

### Sécurité — le garde qui refuse la FORME, et non la fuite d'hier

`tests/acceptance/test_le_journal_ne_retient_aucun_souvenir.py` (16 contrôles, verts dans
`make test`) et `tests/acceptance/garde_journal.py`. Le contrôle précédent cherchait une
chaîne témoin dans le journal d'un cerveau d'essai. Il avait deux trous mécaniques : les
témoins entraient par un `INSERT` psql, jamais par l'API — la seule route qui fuyait — et
il cherchait le témoin d'une **ancienne** fuite, donc ne pouvait par construction voir
aucune des suivantes. Le garde lit désormais le **code** des modules qu'un `ExecStart`
peut atteindre — entrées lues dans `bootstrap/lib/services.sh`, jamais recopiées — et
refuse la forme qui laisse fuir, avant même qu'un cerveau existe. Les deux contrôles
coexistent : l'un dit ce qui a coulé aujourd'hui, l'autre ce qui peut couler demain.

### Corrigé — trois pages annonçaient, sous le mot « mesuré », une fuite qui n'existe plus

`docs/INSTALLATION.md` (§13, « Le journal système », point 3 et l'encadré de la section 7
du rapport de l'étape 9), `bootstrap/README.md` (point 4), `docs/COMMENT-IL-SE-NOURRIT.md`
(le tableau et son encadré). C'est **l'inverse exact** des faussetés que ce chantier
poursuit d'habitude — la page n'y promettait pas trop, elle **effrayait** trop — et ça
trompe au même prix : la raison la plus sérieuse de ne pas installer était écrite dans la
page qu'on lit avant d'installer, et elle était fausse. Le mot « mesuré » aggravait tout :
il transformait une information périmée en fait certifié.

Le point 3 dit maintenant ce que le produit fait — code, sévérité, `atom_id`, nombres et
noms de champs en clair ; domaine, étiquettes, clé et `rationale` empreintés — **et ce
qu'il faut quand même savoir avant d'installer** : la *forme* de la mémoire reste lisible
par tout compte du groupe `systemd-journal`, et le §13 n'y peut rien. L'encadré cesse
d'apprendre au lecteur à **décroire** un contrôle qui a désormais raison : la borne de la
ligne verte reste dite (elle cherche *une* signature, pas toutes les formes), sans lui
prêter une fuite qui coulerait à côté.

`docs/COMMENT-IL-SE-NOURRIT.md` gagne la ligne de tableau qui manquait — le contexte des
avertissements d'écriture — et son encadré cesse d'affirmer que la restauration vérifiée
était « le seul endroit du produit qui envoyait la mémoire à journald » : **il y en avait
deux**, et le second écrivait tout seul, trois fois par jour. C'est la leçon qui revient à
chaque manche : une classe fermée en énumérant ses occurrences connues n'est pas fermée.
Les deux sections « Le journal système » du dépôt ne se contredisent plus, et **une seule
fait foi** : celle du §13 ; l'autre y renvoie et ne la recopie pas.

### Modifié — une mesure s'écrit désormais de façon à vieillir honnêtement

`docs/ROADMAP.md` §7.1. Les trois règles des sections d'honnêteté valaient déjà pour les
absolus ; il leur manquait la forme de **la mesure elle-même**, qui est le vrai vecteur —
un « mesuré » nu ne dit ni quand, ni comment le refaire, ni à quoi on reconnaîtrait qu'il
a cessé d'être vrai. Une quatrième règle et un patron sont ajoutés.

*Ce paragraphe a d'abord recopié cinq chiffres — « 173 emplois de « mesuré », 22 … 52 …
5 … 104 » — que la commande donnée dans la section démentait **le jour même** : elle en
rendait 136. Les chiffres ne sont plus ici : la section porte désormais la commande qui
les recalcule, et un critère (« la colonne LES TROIS monte, jamais ne descend ») qui
survivra au prochain lot. Un journal des versions n'est pas l'endroit où figer un
instantané que sa propre source recalcule — c'est l'endroit où dire que la source existe.*

### Corrigé — le juge d'acceptation LIT le §13 au lieu d'en garder une copie

`tests/acceptance/acceptance.sh` : `page_installation()` ouvre le §13 de
`docs/INSTALLATION.md` **du clone** — celui que l'utilisateur a sous les yeux — et
`chemins_rm_du_13()` en relève les `rm -f`, hors commentaire, en substituant `$BASE` ;
l'étape 9 joue cette liste-là et refuse une liste vide. Le ⚠ qui reprochait à la page une
omission qu'elle n'a plus a disparu, remplacé par un ✓ : « la liste ordonnée du §13
suffit, sans en inventer un seul geste ».

C'est la forme que ce dépôt connaît déjà et qu'il faut préférer partout : **ne pas
recopier ce qu'on surveille, aller le lire** — comme le garde du journal lit les
`ExecStart=` des unités, comme le contrôle de départ lit l'empreinte dans le dump.

Preuve, sans rien installer et sans rien effacer — on ajoute une cible au §13 d'une
**copie** de la page, et elle ressort de la liste que le harnais dérive :

```bash
B="$(mktemp -d)"; mkdir -p "$B/fauxclone/docs"
cp docs/INSTALLATION.md "$B/fauxclone/docs/"
{ echo "ARAC_HOME=$B/fauxclone; DEPOT_SOURCE=\$PWD; ARAC_DB=moncerveau"
  sed -n '/^page_installation() {/,/^}/p' tests/acceptance/acceptance.sh
  sed -n '/^chemins_rm_du_13() {/,/^}/p'  tests/acceptance/acceptance.sh
  echo 'chemins_rm_du_13'; } > "$B/lire13.sh"

bash "$B/lire13.sh" | wc -l        # les cibles dérivées de la page, telle quelle
sed -i '/^## 13\. /,/^## 14\. /{0,/^rm -f /s//rm -f SEULE-LA-PAGE-LE-SAIT\n&/}' \
        "$B/fauxclone/docs/INSTALLATION.md"
bash "$B/lire13.sh" | grep SEULE-LA-PAGE-LE-SAIT
rm -rf "$B"
```

**Critère** — il survivra au nombre de cibles : la cible ajoutée à la copie de la page
**ressort**, et la liste s'allonge d'exactement un. Une copie interne de la liste, par
construction, ne pourrait pas la voir. *Vérifié le 10 août 2026 : `10` cibles avant, `11`
après, et `SEULE-LA-PAGE-LE-SAIT` dans la sortie.*

### Corrigé — la page de décision annonçait « jamais rejouée » une restauration jouée trois fois par passage

`docs/ROADMAP.md` §1.2 rangeait encore, sous « restent ouverts, **en propre** », « la
restauration d'une sauvegarde, qui n'a pas été rejouée sur une base de service ». C'est la
page qu'on lit **pour décider avant d'installer**, et son propre tableau range ce statut
comme « le pire des quatre » — pendant que quatre autres pages du dépôt disaient l'inverse
et que le juge la rejouait. Encore une **alarme** périmée, pas une promesse : la raison la
plus sérieuse de renoncer était écrite dans la page faite pour décider, et elle était
fausse.

La liste ne garde plus que ce qui est vraiment ouvert sur ce point — le chemin *chiffré*
(§7 étape 2, `age -d`) et la copie hors site. À la place, la page porte les trois
restaurations du juge, **de trois natures différentes**, avec la commande qui les compte
et le critère qui survivra au chiffre. Mesuré le 10 août 2026 sur un cerveau de banc
démonté ensuite : `grep -cE '✓ (restauration|bascule §7\.3)'` rend `3`, l'étape 8 conclut
`PROUVÉ`, `0 en échec · 0 intervention(s)`.

### Connu et non résolu

- **Aucun garde ne croise les sections d'honnêteté entre elles.** C'est la dette du §7.1
  de `docs/ROADMAP.md`, et c'est elle qui a laissé passer ce lot-ci : trois pages ont
  décrit une fuite pendant qu'une quatrième main la fermait. Le patron de mesure ajouté au
  §7.1 rend la faute **visible** ; il ne la rend pas impossible.
- **Rien n'oblige un lot qui ferme un défaut décrit dans une page à l'écrire ici.** La
  règle en tête de ce journal ne couvre qu'un sens. `app/journal.py` — un module de
  sécurité entier — a vécu dans l'arbre sans une ligne ici, et c'est la cause **mécanique**
  du bloquant ci-dessus : aucune relecture du journal des versions ne pouvait rattraper
  l'écart.
- **Cette section a inquiété pour un défaut que son propre lot venait de fermer.** Elle
  écrivait ici : « le harnais d'acceptation garde **toujours** une copie de la liste de
  l'étape 7 au lieu de lire la page ; le ⚠ qu'il imprime **à chaque passage** reproche à
  `docs/INSTALLATION.md` une omission qu'elle n'a plus ». Les trois mots qui comptaient
  étaient faux : le harnais lit la page (voir « Corrigé » ci-dessus), et sur un passage
  complet du juge le 10 août 2026, la ligne du §13 est un **✓** — « la liste ordonnée du
  §13 suffit, sans en inventer un seul geste ». *Critère, et il faut le dire exactement :
  `sudo make acceptance 2>&1 | grep '⚠'` rend **une** ligne, et une seule — le rappel final
  « des étapes ne sont que partiellement prouvées ». **Aucun ⚠ ne porte sur la liste du
  §13**, et c'est cela qu'il fallait vérifier ; écrire « aucun ⚠ du tout » aurait été
  refaire, à l'endroit même où on la corrige, la faute qu'on corrige.* C'est la deuxième
  puce de cette liste — « rien n'oblige un lot qui ferme un
  défaut à l'écrire ici » — réalisée sur elle-même, un paragraphe plus haut, **et dans
  l'autre sens** : le journal ne promettait pas trop, il **alarmait** trop. Le prix est le
  même : un lecteur qui renonce.
- **Une alarme périmée coûte autant qu'une promesse périmée, et rien ne l'attrape.** La
  règle en tête de ce journal interdit de dire qu'une chose fonctionne sans l'avoir
  exécutée ; elle n'interdit pas de dire qu'une chose est cassée sans avoir vérifié
  qu'elle l'est encore. Les deux moitiés sont désormais nommées ; **aucune des deux n'est
  tenue par un garde.** Ce que la garde du §7.1 de `docs/ROADMAP.md` pourrait exiger — une
  date, une commande, un critère autour de chaque « mesuré », « vérifié », « jamais
  testé », « non vérifié » — rendrait ce défaut *cher à commettre et bon marché à
  découvrir*, jamais impossible : décider si une alarme datée est encore vraie demande de
  la rejouer, donc un cerveau, une grappe et des ports que `make test` n'a pas.

---

## [0.1.11] — 2026-08-10

Lot **la preuve devenue fausse, en première page**. Rien n'a été cassé : la phrase qui
répond au mandat dans le premier écran du dépôt — « deux installations rendent un
`pg_dump --schema-only` identique ligne pour ligne » — est devenue fausse **parce que le
produit s'est amélioré ailleurs**, le jour où le bootstrap s'est mis à graver l'empreinte
d'installation dans le commentaire du schéma. Le banc : instantané du dépôt (450
fichiers) → `git init` + `git clone`, grappe `16/kz20` montée pour l'occasion sur le port
**5610**, **trois** cerveaux nés du chemin réel (entretiens `wizard.py` derrière un vrai
pseudo-terminal, trois taxonomies sans un domaine en commun), ports 8610/8612, 8614/8616,
8622/8624. Banc entièrement démonté.

### Corrigé — la preuve de reproductibilité, refaite plutôt que retirée

`README.md` (encadré du premier écran et §7c), `docs/ROADMAP.md` §1.2,
`docs/DEMARRAGE-RAPIDE.md`, `docs/INSTALLATION.md`, `GOAL.md`, `bootstrap/README.md`.

La commande du §7c, recopiée mot pour mot sur deux installations réelles, rendait `1` et
une différence là où la page annonçait `# attendu : vide` :

```
31c31
< COMMENT ON SCHEMA arac IS 'ARAC cerveau=kza empreinte=54fbc7a8… poste=poste-kza';
---
> COMMENT ON SCHEMA arac IS 'ARAC cerveau=kzd empreinte=d8d07d07… poste=poste-kzd';
```

**La reproductibilité, elle, est toujours vraie** : 2 274 lignes de part et d'autre, une
seule différence, et c'est la plaque d'identité que `pg_dump` emporte **exprès** — celle
que `ops/restore_verify.sh` relit pour sa PREUVE D. C'est donc la formulation et la
commande qui étaient fausses, pas le fait.

Le critère devient : **le même schéma, l'identité de chaque installation neutralisée des
deux côtés** — et la commande ne filtre plus une ligne apprise par cœur, elle remplace les
**trois valeurs** que chaque installation lit dans son propre coffre (`ARAC_DB`,
`ARAC_INSTALL_UUID`, `ARAC_NODE_ID`). La différence n'est pas cosmétique, elle a été
**mesurée** : en gravant la même plaque sur une table en plus du schéma, le filtre par
motif rend une différence et le nouveau critère rend le vide. *Un critère qui périt à
chaque amélioration n'est pas un critère, c'est un instantané.* Le §7c ajoute un second
contrôle, complémentaire : l'identité, elle, **doit** différer.

### Corrigé — le §13 ne pouvait pas atteindre le verdict qu'il promettait

`docs/INSTALLATION.md` §13, étape 7. La liste ordonnée n'effaçait pas
`app/schemas/scope_generated.py` ni `db/seeds/scopes.sql` — engendrés depuis la taxonomie
de l'utilisateur, porteurs de ses domaines **en clair**, non suivis par git — que le
contrôle de l'étape 9 comptait, à juste titre, comme des restes. Mesuré : « VERDICT :
2 RESTE(S) », code 1, à qui suivait la page mot pour mot ; « PROPRE » et le code 0
n'arrivaient qu'après la seconde passe. L'étape 7 les nomme désormais, et le §13 rejoué en
entier sur un troisième cerveau rend « VERDICT : PROPRE », code 0, **en une seule passe**.
Le harnais d'acceptation signalait ce défaut à chaque passage sans que personne ne le
lève : un ⚠ qu'un juge imprime à tous les coups devient du décor.

### Corrigé — deux sections d'honnêteté qui se contredisaient, et la plus ancienne survivait

`docs/ROADMAP.md` §1.2 écrivait « personne ne s'est jamais connecté au cockpit avec un mot
de passe tapé et un code TOTP » pendant que trois autres pages décrivaient cette connexion,
datée et mesurée. Rejouée pour cette version, sur un cerveau de banc : mot de passe tapé
aux invites `getpass` derrière un vrai pseudo-terminal, appairage TOTP, puis `POST
/cc/login` → `303 See Other` vers `/cc/`, `GET /cc/` et `GET /cc/v1/atoms` à `200`, mot de
passe faux à `401`. Ce qui reste ouvert tient en une ligne : le code a toujours été
**calculé depuis le secret**, jamais **lu sur un téléphone**.

`docs/PONT-MAC.md` §12 affirmait « aucun fichier de `tests/*.py` n'exerce
`mac/arac-sync.py` » — faux depuis que `tests/acceptance/test_les_promesses_exercables.py`
le charge par `exec_module` et éprouve son inventaire. Trouvé en rejouant la commande que
la page donne elle-même.

### Ajouté — l'inventaire des sections d'honnêteté

`docs/ROADMAP.md` §7.1. **Cinq fois** ce dépôt a corrigé une section d'honnêteté périmée,
dans cinq pages différentes, et chaque fois en la découvrant par hasard. Elles ont une
propriété commune et dangereuse : on les écrit une fois, quand on est lucide, et on ne les
relit jamais. La nouvelle section les liste toutes, donne la commande qui refait
l'inventaire, dit comment rejouer chacune, et pose trois règles — aucun absolu, aucun
instantané comme critère, une commande plutôt qu'une phrase. Elle nomme aussi ce
qu'aucun garde ne sait faire : croiser deux sections d'honnêteté qui parlent du même geste
et se contredisent. C'était la forme des cinq.

### Modifié — ce que le produit écrit dans le journal, dit en entier

`docs/INSTALLATION.md` (« Le journal système ») et `bootstrap/README.md` (nouveau point 4
de « Ce qu'il faut savoir AVANT de lancer quoi que ce soit »). La page ne citait que les
empreintes `sha256` de la restauration vérifiée. Mesuré sur un cerveau de banc, en
écrivant **un seul** souvenir : la route `create_atom.warnings` de l'API verse dans
journald le **contexte** de chaque avertissement d'écriture — le **domaine**, les
**étiquettes**, la **clé** selon le cas, et jusqu'à **deux cents caractères du
`rationale`**, c'est-à-dire le *pourquoi* d'une décision, dans les mots de
l'utilisateur — et la digestion emprunte cette route trois fois par jour, toute seule.

La limite est dite avec sa conséquence : **systemd ne sait pas effacer les entrées d'une
seule unité** (`journalctl --vacuum-*` travaille sur des *fichiers* de journal, qui
portent aussi les autres services et le cerveau du voisin). Donc **ce que le produit écrit
dans le journal doit pouvoir y rester** — c'est la règle qui gouverne ce qu'il a le droit
d'y écrire, et elle est désormais annoncée **avant** l'installation, pas après.

> **Cette mesure était vraie le jour où elle a été prise, et elle ne l'est plus.** La
> fuite décrite ci-dessus est **fermée à la source** depuis `app/journal.py` — voir
> [0.1.12](#0112--2026-08-10), rubrique *Sécurité*. Ce paragraphe reste ici parce qu'un
> journal des versions raconte ce qui s'est passé ; il ne décrit **plus** le comportement
> du produit. La règle qu'il énonce, elle, n'a pas bougé.

### Corrigé — un contrôle vert qui rassurait au-delà de ce qu'il regarde

`docs/INSTALLATION.md`, encadré de la section 7 du rapport de l'étape 9. Mesuré : sur un
cerveau désinstallé par le §13 mot pour mot, le contrôle écrivait « ✓ aucune clé, aucun
domaine de souvenir dans le journal de ces unités » pendant que `journalctl` rendait
encore, à la même seconde, le domaine du souvenir et deux cents caractères de son
*pourquoi*. La ligne verte dit *cette signature-ci est absente*, pas *le journal ne porte
rien de vous* — la page le dit maintenant, et donne la commande pour mesurer soi-même.

> **La borne de la ligne verte reste exacte ; le contre-exemple qui la démontrait, non.**
> Depuis [0.1.12](#0112--2026-08-10), plus rien ne coule à côté d'elle : seize motifs
> cherchés après un §13 joué mot pour mot, aucun trouvé. L'encadré de la page a été
> réécrit en conséquence — il enseignait au lecteur à décroire un contrôle qui a
> désormais raison.

### Connu et non résolu

- Le garde `COMMANDES_EXERCEES` de `tests/test_la_doc_dit_vrai.py` est une **énumération**
  de quatre motifs ; il ne peut pas voir un « jamais » portant sur un geste absent de la
  liste. La docstring et le message d'assertion de ce garde s'appuient par ailleurs sur la
  formulation « `pg_dump --schema-only` identique », corrigée ci-dessus : la justification
  d'un garde vert n'est plus tout à fait celle qu'il énonce.
- Aucun test ne croise les sections d'honnêteté entre elles. C'est la dette nommée au
  §7.1 de `docs/ROADMAP.md`.
- **Le harnais d'acceptation garde une COPIE de la liste de l'étape 7 au lieu de lire la
  page.** `tests/acceptance/acceptance.sh` énumère en dur les quatre chemins que
  `docs/INSTALLATION.md` § 13.7 fait effacer. La page en nomme désormais six ; le harnais
  en joue toujours quatre, et continue donc d'imprimer son ⚠ « SEULEMENT APRÈS la seconde
  passe » en reprochant à la page une omission qu'elle n'a plus. Mesuré sur cette
  version : `make acceptance` rc=0, 0 échec, 0 intervention, et ce ⚠ toujours présent.
  C'est la **troisième** fois que cette liste diverge entre le texte et son juge : le
  correctif durable n'est pas d'y ajouter deux lignes, c'est que le harnais **relise la
  page** plutôt que d'en garder une copie.
  → **FERMÉ en 0.1.12** (« le juge d'acceptation LIT le §13 »). Cette puce reste écrite
  telle qu'elle l'était ce jour-là — un journal ne se réécrit pas —, mais une entrée
  « connu et non résolu » qui a été résolue doit dire **où**, sinon elle continue
  d'alarmer pour rien. C'est la deuxième moitié de la règle en tête de ce fichier.

---

## [0.1.10] — 2026-08-09

Lot **un produit en retard sur ses pages** — l'inverse exact de ce que ce dépôt chassait
depuis dix manches. Une garde promise par sept documents avait disparu du code ; la
mémoire d'un cerveau restait lisible dans le journal système après un départ déclaré
« PROPRE » ; et le garde des sections d'honnêteté en portait une dans sa propre docstring.
Le banc : instantané du dépôt (450 fichiers) → `git init` + `git clone`, `make venv`,
`make test` sur le clone **et** sur une copie sans `.git`, dans les **deux** régimes ;
`make acceptance` de bout en bout sur une grappe et des ports montés pour l'occasion, et
les cinq rangs d'`ops/env.sh` éprouvés un par un sur un faux `/etc` à moi. Banc démonté.

### Modifié — `ops/env.sh` choisit désormais, et le dit

- **`ops/` ne refuse plus dès qu'il y a deux cerveaux : il sert celui que le dépôt décrit,
  et il l'annonce avant le premier geste.** Cinq rangs, écrits au-dessus du code :
  `ARAC_ENV_FILE` posée (silence) · `$ARAC_HOME/.env` (silence) · coffre unique (silence,
  sauf désaccord avec `config/brain.toml`, qui **arrête**) · plusieurs coffres et ce dépôt
  en décrit un (**choix annoncé** sur stderr : quel cerveau, quel coffre, sur quelle
  preuve, combien de candidats, et la ligne pour en désigner un autre) · tout le reste
  (**« ARRÊT AVANT TOUT GESTE »**, code 1, la liste des coffres prête à recopier). Le refus
  d'autrefois n'avait jamais été tenu pour de bon : le socle refusait le DSN puis dérivait
  du **même** `brain.toml` le dossier de dumps, le préfixe de rotation et l'étiquette du
  journal — « je ne choisis pas » en choisissant tout le reste. Ce qui manquait n'était pas
  le rattachement, c'était de le **dire**. `ARAC_ETC_DIR` est devenue une variable pour que
  la règle soit éprouvable dans `make test`, qui est hermétique :
  `tests/test_ops_env_nomme_le_cerveau_qu_il_sert.py` mesure les cinq rangs.
- **Les sept documents qui promettaient l'ancien refus disent maintenant ce que le produit
  fait.** `docs/DEMARRAGE-RAPIDE.md`, `docs/CONFIGURATION.md` (qui gagne le tableau des
  cinq rangs, avec les deux sorties telles quelles), `docs/SAUVEGARDE.md` (trois passages),
  `docs/EXPLOITATION.md`, `docs/DEPANNAGE.md` (deux passages), `docs/INSTALLATION.md` (deux
  passages) — et **`docs/PREMIER-MOIS.md`, la septième, que le constat d'origine n'avait
  pas nommée**. Une huitième a été trouvée en cherchant la **promesse** plutôt que sa
  formule : `ops/README.md` donnait pour défaut d'`ARAC_ENV_FILE` « le coffre s'il est
  seul, sinon `$ARAC_HOME/.env` » — l'ordre inverse de celui qu'applique le socle, où le
  `.env` du dépôt passe **avant** le coffre unique. Elle porte désormais les cinq rangs.
  *Une même promesse vit toujours dans un endroit de plus qu'on ne croit — cinquième fois
  sur ce chantier.*

### Sécurité — la mémoire ne va plus dans le journal système

- **`ops/restore_verify.sh` imprimait la clé et le domaine de trois souvenirs en clair.**
  Ce script est l'`ExecStart` d'`arac-<base>-restauration.service`, que le bootstrap arme
  lui-même (dimanche 03:00) et que le § 7 de `SAUVEGARDE.md` fait lancer à la main : tout ce
  qu'il imprime part dans **journald**, magasin commun à la machine, lisible par tout compte
  du groupe `systemd-journal`, et **hors de portée du § 13**. Mesuré : après un § 13 joué mot
  pour mot et un « VERDICT : PROPRE » en code 0, `journalctl` rendait encore
  « · penicilline [perso/sante] ». Il n'imprime plus que des **empreintes** — `sha256`
  tronqué à huit caractères, la même que `key_sha8` ailleurs dans le produit — la date et
  la longueur décodée. La preuve en sort **plus forte** : `value`, la colonne qui porte le
  souvenir, n'était jamais lue ; elle l'est maintenant, sans qu'un caractère en sorte.
  *Le dépôt avait déjà écrit la règle ailleurs (« aucune clé ne doit être écrite en clair
  dans un artefact durable ») : c'était le seul endroit du produit qui l'enfreignait.*
- **`ops/uninstall_check.sh` regarde le journal (sa section 7)** : il compte les lignes des
  unités de ce cerveau, dit depuis quand, cherche nommément la signature de l'ancienne
  fuite, et **ne prescrit aucun geste** — parce qu'il n'en existe aucun qui soit borné à un
  cerveau : `journalctl --vacuum-*` travaille sur des **fichiers** de journal, qui portent
  aussi ceux du voisin. Il dit ce qu'il voit et laisse la décision à qui la porte.
- **Les deux pages concernées l'écrivent** : `docs/INSTALLATION.md` § 13 gagne « Le journal
  système — ce que ce chapitre ne peut pas effacer, et pourquoi », et
  `docs/COMMENT-IL-SE-NOURRIT.md` — la page de ce qui quitte la machine — gagne « Le journal
  système : ce qui sort du cerveau sans quitter la machine », avec ce qui y va et ce qui
  n'y va pas. Un lecteur doit pouvoir le savoir **avant** d'installer, pas le découvrir en
  partant.

### Corrigé — le garde des sections d'honnêteté en portait une

- **`tests/test_la_doc_dit_vrai.py`, docstring de
  `test_aucun_document_ne_dit_jamais_d_une_commande_deja_executee`** : elle citait « la
  restauration d'une sauvegarde n'a jamais été rejouée » comme exemple d'un « jamais »
  honnête. C'est faux depuis plusieurs versions — l'unité hebdomadaire, `make acceptance`
  étape 8, et la section d'honnêteté d'`INSTALLATION.md` le disent tous les trois.
- **Et la méthode a été mesurée, pas seulement relue.** Deux causes, dont une inconnue.
  (1) `COMMANDES_EXERCEES` est une énumération de quatre motifs : un garde qui énumère
  hérite du défaut qu'il combat — c'était déjà écrit. (2) **`MARQUEURS_DE_DEMENTI` est
  cherché dans le paragraphe entier, et « périm… » en fait partie : un paragraphe qui
  *parle* de péremption est exempté du contrôle de sa propre péremption**, ce qui est
  exactement le paragraphe qu'écrit quiconque documente une section d'honnêteté. Vérifié
  par injection sur ce fichier même : « alembic upgrade head n'a jamais été rejoué » laisse
  le test **vert** ; le même texte, privé du seul mot « périmée », le rend **rouge** et
  nomme la ligne. La docstring dit désormais cette limite, et elle est écrite pour ne pas
  en bénéficier.

### Connu et non résolu

- **L'exemption des marqueurs de démenti reste plus large que son intention.** Elle porte
  sur le paragraphe entier ; la restreindre à la phrase, ou exiger que le démenti et la
  formule démentie soient dans la même phrase, se discute — mais le remède n'est pas
  d'allonger encore une liste de mots. C'est nommé ici plutôt que tu.
- **Ce que le journal a déjà avalé ne se rattrape pas.** Un cerveau installé avant ce lot a,
  dans journald, des clés et des domaines en clair jusqu'à la rotation. `SystemMaxUse` et
  `MaxRetentionSec` fixent la date ; la seule purge complète vide le journal de toute la
  machine, et le § 13 le dit sans la prescrire.

---

## [0.1.9] — 2026-08-09

Lot **la page du dépannage se contredisait à cent lignes d'intervalle, et les promesses de
commodité n'avaient jamais été exercées**. Rien ci-dessous n'a été écrit depuis une
lecture. Le banc : un clone git fidèle du dépôt, `make venv`, `make test` **sur le clone
et sur une copie sans `.git`**, `make acceptance` de bout en bout sur des ports et une
grappe montés pour l'occasion ; puis un cerveau né du **chemin réel** — entretien
`bootstrap/wizard.py` par stdin, `--dry-run`, `sudo ARAC_DB_PORT=<un port à moi>
./bootstrap/bootstrap.sh --yes` sur ma grappe —, rempli de témoins, sauvegardé par son
unité, restauré, **cassé pour de vrai** (`DROP SCHEMA arac CASCADE`) et remis debout par
le § 7 de `SAUVEGARDE.md`, ses souvenirs relus sous le rôle de l'application. Banc
entièrement démonté.

### Corrigé — les sections d'honnêteté

- **`docs/DEPANNAGE.md` prescrivait deux commandes comme remède, puis les déclarait
  jamais vérifiées cent lignes plus bas.** Le § 18 (« la sauvegarde est en échec depuis des jours »)
  donne `ops/backup.sh` puis `ops/restore_verify.sh` — et le registre d'honnêteté de la
  même page les listait sous « **Non vérifié** ». Les deux moitiés ne pouvaient pas être
  vraies ensemble, et le lecteur de cette page est par construction celui chez qui
  quelque chose est déjà cassé. **Les deux ont été exécutés** sur un cerveau réel :
  `ops/backup.sh` rend un dump et ses quatre contrôles en code `0` ; `ops/restore_verify.sh`
  rend « VERDICT : PROUVÉ — ce dump se restaure, et le cerveau en sort entier », code `0` ;
  après un `DROP SCHEMA arac CASCADE` sur la base vivante, le **code `2`** annoncé par le
  § 7 de `SAUVEGARDE.md` — preuves A, B, D rendues, comparaison au vivant impossible. Le
  paragraphe dit désormais cela, et distingue ce qui reste réellement non vérifié : les
  valeurs sur un cerveau **habité**, le chemin chiffré, la copie hors site, le tunnel
  depuis un Mac. *C'est la quatrième occurrence du même motif, corrigée après les trois
  qu'avait traitées [0.1.8] — quand un défaut est corrigé par énumération, l'occurrence
  oubliée est la règle, pas l'exception.*
- **`bootstrap/README.md` écrivait que la restauration « n'a été rejouée nulle part ».**
  Elle l'est à chaque `make acceptance`, par les unités que ce bootstrap arme lui-même, et
  elle l'a été à la main sur un cerveau posé par lui. Corrigé, avec ce qui reste ouvert.
- **`CHANGELOG.md` [0.1.8] déclarait « Connu et non résolu » une cadence déjà corrigée.**
  `ops/watchdog.sh`, `ops/restore_verify.sh` et `ops/backup.sh` disent « QUATRE FOIS PAR
  JOUR » et « SIX HEURES » dans l'arbre d'aujourd'hui. Rubrique retirée. **Sous-estimer
  trompe autant que surestimer** : un lecteur qui lit une dette éteinte et n'ouvre pas les
  fichiers croit à un défaut qui n'existe plus.
- **`docs/EXPLOITATION.md` n'avait aucune section d'honnêteté** — et c'est précisément ce
  qui a laissé « vous pouvez les lancer cent fois » au-dessus de commandes qui ne
  pouvaient pas se lancer une seule fois. Elle en a une.

### Corrigé — les promesses de commodité, mesurées une par une

- **« Les cinq commandes […] vous pouvez les lancer cent fois » (`docs/EXPLOITATION.md`
  § 1) : quatre des cinq ne pouvaient pas se lancer une fois** telles qu'écrites, sur un
  cerveau posé par le bootstrap. Le coffre est en `0700 root` : sans root,
  `install_check.sh` refuse de juger (code `3`), `health_check.py` et `alerts.py` rendent
  « UNKNOWN » (code `3`), `restore_verify.sh` annonce « Aucun dump » alors que le dump est
  là. **Et `ops/watchdog.sh` ne se tait pas : il alerte** — « aucun dump […] la sauvegarde
  n'a JAMAIS produit de fichier », `critical`, code `2` — sur une sauvegarde qui vient de
  tourner ; mesuré à la même seconde, `dump_age_h=99999` sans root contre `0` avec. Les
  cinq portent désormais le même préfixe, et l'encadré nomme le seul dont la cécité prend
  la forme d'un verdict. **La promesse, elle, est vraie une fois le préfixe posé** :
  rejouées coup sur coup, verdicts identiques, aucun souvenir touché, aucune base laissée
  derrière.
- **`docs/DEPANNAGE.md`, « les trois commandes qu'on peut lancer cent fois » : la
  troisième était écrite sans `sudo`**, sous un paragraphe qui expliquait pourquoi elle
  n'en avait pas besoin. `health_check.py` lit la base avec le rôle en lecture stricte, et
  ce DSN est dans le coffre comme les autres — `ops/install_check.sh` le dit lui-même à
  l'écran. Le paragraphe portait aussi une description périmée de son propre voisin :
  `install_check.sh` sans root ne conclut plus « ne tient PAS debout » en code `2`, il
  **refuse de rendre un verdict** en code `3`. Les deux corrigés, avec le tableau des
  trois comportements mesurés.
- **`docs/EXPLOITATION.md` § 2 prescrivait `scripts/ops/health_check.py` sans son
  interpréteur.** Le script a un shebang, donc il démarre — sur le Python du système, qui
  n'a pas `psycopg` : « 148 métriques lues — 0 dans les clous […] 148 indisponibles »,
  `cc_v1.db_unreachable`, sur un cerveau en pleine santé. Un bulletin entièrement gris
  n'est pas un diagnostic, c'est un mauvais interpréteur.

### Corrigé — deux requêtes de diagnostic qui ne pouvaient pas s'exécuter

- **`docs/DEPANNAGE.md` § 13 et § 15 nommaient des colonnes qui n'existent pas.**
  `SELECT key FROM arac.scopes WHERE parent_key IS NULL` rend `ERROR: column "parent_key"
  does not exist` sur toute installation : la table porte `path`, `parent_id` et `depth`.
  Le comptage des souvenirs posés sur une racine est désormais **copié mot pour mot du
  produit** (`bootstrap/checks/verify_install.sh` : `JOIN arac.scopes s ON s.path =
  a.scope … s.depth = 0`), et vérifié sur un témoin — `0` avant qu'un atome soit posé sur
  une racine, `1` après. Une requête de diagnostic qu'on recopie un mauvais jour n'a pas
  droit à une faute de frappe.

### Corrigé — une phrase du manuel qui s'appuyait sur ce que le produit n'imprimait pas

- **`docs/INSTALLATION.md` § 12.f : « et la simulation le recommande elle-même ».** Elle
  ne le recommandait que sur une grappe **vide** — le seul cas où une grappe dédiée ne
  protège rien. Le code a été corrigé en parallèle ; cette page imprime maintenant **ce
  que la simulation imprime vraiment**, dans ses trois états, mesurés : grappe vide, grappe
  habitée (« ⚠ CE CERVEAU VA VIVRE SUR LA MÊME GRAPPE QUE n AUTRE(S) […] le DERNIER moment
  où le choix est gratuit », avec la recette), et port **déjà retenu** dans le coffre (« Le
  choix est refermé […] Rien à faire ici », sans recette — parce qu'un outil ne prescrit
  pas un geste que le produit refuse trois écrans plus loin, en code `6`).

### Vérifié sans rien changer — les promesses de commodité qui, elles, sont vraies

Chacune a été **exécutée**, plusieurs fois, sur un cerveau neuf puis sur un cerveau
rempli ; aucune n'a demandé de correction.

- **`--dry-run` « n'écrit rien, ne crée rien, ne démarre rien »** (`bootstrap/README.md`).
  Empreinte prise avant/après — coffre, rôles, unités, scopes, souvenirs : identique.
- **« Relancez-le autant de fois que vous voulez »** (le bootstrap, idempotent). Deux
  `bootstrap.sh --yes` complets de plus sur un cerveau vivant : coffre au même md5 — donc
  **aucun secret régénéré** —, mêmes rôles, mêmes unités, souvenirs intacts.
- **Le seed de la taxonomie « idempotent (`ON CONFLICT`), ne supprime rien »**
  (`INSTALLATION.md` § 6). Deux `--scopes-only` de plus : taxonomie identique au md5.
- **Le traducteur du § 1 de `DEPANNAGE.md`, « idempotent, relançable sans dégât »**.
  Cinq passages sur un coffre fabriqué : mêmes lignes imprimées, fichiers stables au md5
  dès le second — et le compte annoncé (`5` sans les clés payantes, `3` pour le cockpit)
  est bien celui qu'il rend.
- **« Renvoyer ne coûte rien » / « `--tout` est sans danger »** (`README`, `mac/README`,
  `COMMENT-IL-SE-NOURRIT.md`). C'est l'étape 5 de `make acceptance` : « *un second envoi
  COMPLET n'ajoute aucun message* ».
- **Les deux auto-tests d'`ops/`** (`backup_toc_check.sh selftest`,
  `restore_guard.sh selftest`) : rejoués, code `0` à chaque passage.

### Ce que ce lot n'a pas fait, et qui reste à faire dans le code

- `ops/watchdog.sh` rend un verdict `critical` là où il devrait dire qu'il n'a rien pu
  lire. Ses quatre voisins ont appris à distinguer « je ne vois rien » de « il n'y a
  rien » ; lui pas encore. La documentation le nomme en attendant, ce qui est le moins
  bon des deux remèdes.
- **Il manque un garde mécanique sur les sections d'honnêteté.** Quatre fois maintenant,
  une de ces sections a été trouvée en retard sur le produit ; trois fois, la correction
  s'est faite par énumération et a laissé une occurrence. Ce qu'il faudrait est étroit et
  se teste : refuser qu'un fichier d'`ops/` ou de `scripts/ops/` nommé sous « **Non
  vérifié** » soit en même temps **exercé par `make acceptance`** ou prescrit comme remède
  dans la même page. C'est un test, donc du code, donc hors du périmètre de ce lot.

## [0.1.8] — 2026-08-09

Lot **le manuel envoyait sur la grappe du voisin, et sa page d'honnêteté était périmée**.
Deux phrases, et une famille entière de points de contrôle. Rien ci-dessous n'a été écrit
depuis une lecture : un cerveau d'essai a été posé par le chemin réel — entretien
`wizard.py`, `--dry-run`, `sudo ARAC_DB_PORT=<un port à moi> ./bootstrap/bootstrap.sh --yes`
sur une grappe montée pour l'occasion et détruite après — puis **tous** les
points de contrôle du §5, du §6, du §7 et du §8 y ont été **exécutés**, un par un, et
comparés mot à mot à ce que la page annonce.

### Corrigé — la documentation

- **`docs/INSTALLATION.md` : le port de la grappe se choisissait sans jamais se donner.**
  Le point de contrôle 1 du §1 fait choisir « le port de la grappe où votre cerveau va
  vivre » ; le préambule du §5 promet qu'on le « donnera au bootstrap » ; le §13 renvoyait
  pour cela à un **§12.d qui n'en parle pas** — le mot `pg_createcluster` n'apparaissait
  qu'**une seule fois** dans les 1 591 lignes du fichier, dans la phrase qui l'attribuait à
  cette section. Aucune des trois ne nommait `ARAC_DB_PORT`. Mesuré : `./bootstrap/bootstrap.sh
  --dry-run` sans la variable annonce « Ce cluster PostgreSQL (port **5432**) », liste les
  **deux cerveaux de production** qui y vivent, et enchaîne « CE QUE CETTE INSTALLATION VA
  CRÉER : base <mon essai> · rôles arac_<mon essai>_admin · _app · _agent · _readonly ·
  _backup » — les
  rôles sont **globaux à la grappe**. C'est l'incident que ce framework existe pour
  empêcher, servi par le manuel. Le geste est désormais écrit **là où le lecteur en a
  besoin** : encadré du point de contrôle 1, préambule et commande d'ouverture du §5,
  §12.d, et une sous-section neuve **§12.f — « Une grappe PostgreSQL pour ce cerveau »**
  avec son contrôle avant/après. Les trois renvois pointent vers elle.
- **`docs/INSTALLATION.md` §12.f, éprouvé par exécution** : `sudo ARAC_DB_PORT=<mon port>
  ./bootstrap/bootstrap.sh --yes` → rc=0, le port retenu écrit dans le coffre ; relancé nu,
  le bootstrap le **relit** ; un AUTRE port demandé → « REFUS — ce cerveau vit déjà sur un
  autre serveur PostgreSQL », **code 6**, « Rien n'a été créé, rien n'a été écrit ».
- **La section d'honnêteté déclarait « toujours non vérifié » ce que le juge prouve à
  chaque passage** — et à **trois** endroits, pas un. `docs/INSTALLATION.md` (« la
  **restauration** d'une sauvegarde · les variantes du §12 et les gestes de désinstallation
  du §13 »), `README.md` §7c (« Des dumps existent ; aucun n'a jamais été rechargé » et
  « personne ne s'est jamais connecté au cockpit »), `docs/DEMARRAGE-RAPIDE.md` (« la
  **restauration** d'une sauvegarde »). Les trois sont réécrites : ce qui est éprouvé est
  nommé avec le geste qui le rejoue, ce qui ne l'est pas reste nommé — Ubuntu nu, première
  conversation, **tunnel SSH depuis un vrai Mac, `launchd`, capture réelle de Claude
  Desktop**, variantes (a) (b) (c) (e) du §12, chemin chiffré et copie hors site.
  Sous-estimer trompe autant que surestimer, et se lit au pire moment.
- **`bootstrap/README.md` : « Il ne teste pas vos sauvegardes »** — faux depuis que son
  étape 9 arme `arac-<base>-restauration.timer`. Remplacé par ce qu'il fait vraiment, et
  par ce qu'il ne fera jamais à votre place : la **bascule**.
- **`docs/DEMARRAGE-RAPIDE.md` étape 10** disait « le bootstrap a armé une sauvegarde…
  **ce n'est pas suffisant** » en ignorant l'unité de restauration qu'il arme aussi.

### Corrigé — les points de contrôle, tous rejoués sur un cerveau réel

- **§5 étape 8, cinquième manche : « Doit répondre : `2` » sur le chemin que la même
  section vient d'autoriser.** Mesuré, les deux clés refusées : `0`, `grep` en **code 1**,
  et `ARAC_MODE_DEGRADE=embeddings,curation`. Le contrôle donne désormais ses **deux**
  réponses justes, dit que le code 1 est celui de `grep` et non celui de l'installation, et
  le cas d'**une seule** clé — vérifié derrière un pseudo-terminal : `1`, rc=0,
  `ARAC_MODE_DEGRADE=curation`, la manquante et elle seule.
- **§6 : `SELECT node_id FROM arac.nodes` rend DEUX lignes sur une installation neuve.**
  La migration `0020` déclare aussi `<node_id>-server` (`active = false`). La page annonçait
  « **exactement** le `node_id` de votre `config/brain.toml` » : un lecteur sain croyait à
  un doublon. Requête corrigée en `WHERE active`, et les deux lignes expliquées ici et dans
  `DEMARRAGE-RAPIDE.md`.
- **§8 : le cockpit ne rend pas `200`, `302` ou `401`, il rend `307`.** Mesuré :
  `curl http://127.0.0.1:$CC` → **307** vers `/cc/`, puis `302` vers `/cc/login`, puis
  `200`. Le critère devient : *un* code HTTP — l'échec, c'est `000`, la connexion refusée —
  avec la variante `curl -sL` pour aller jusqu'à `200`.
- **§5 étapes 3 et 7 : un mode de dossier exigé qu'aucune commande imprimée ne montrait.**
  « dans un dossier `700 root` » alors que `ls -l <dossier>/` liste le contenu et jamais le
  mode du dossier. `stat -c '%a %U' /etc/arac/<base>` ajouté aux deux.
- **§5 étape 5 : « un nombre de tables à deux chiffres ».** Un critère qui devient faux à la
  centième table. Remplacé par « révision non vide, compte non nul », sans citer ni l'une ni
  l'autre — et l'erreur qui, elle, doit vous arrêter est nommée.
- **§5 étape 9 : « les cinq unités et les trois minuteries ».** Le critère est la **liste
  nommée**, pas son cardinal ; la machine fait foi.
- **§6 : « Doit répondre 4 ».** Le critère est « non nul » — `4` est le nombre de DSN
  d'aujourd'hui, un par rôle qui se connecte.

### Corrigé — les cadences

- **`docs/EXPLOITATION.md` « Plus rien n'entre » justifiait 26 h par « une synchronisation
  quotidienne + 2 h ».** Le pont passe **toutes les heures** (`StartInterval 3600` côté
  launchd, `OnCalendar=hourly` côté systemd) : 26 h ne valent pas un passage manqué mais
  vingt-six. Le seuil n'est pas calé sur la cadence du pont mais sur la **machine source**,
  un portable qui dort — c'est écrit, avec la variable qui le descend.
- **Le tableau des seuils du chien de garde** ne prétend plus dire ce qu'imprime
  `ops/watchdog.sh --explain` : cette sortie donne les justifications et les **valeurs par
  défaut du script**, pas celles que votre environnement impose.

### Corrigé — les renvois

- Le renvoi `§12.d` du §13 pour `pg_createcluster` (la section ne le contenait pas) pointe
  sur le §12.f neuf ; `(§12)` du §13 sur le cluster créé « pour celui-ci et pour lui seul »
  aussi ; `(§12d)` du §2 pour « le dépôt ne se partage pas » tombe maintenant sur un tableau
  qui **nomme le dépôt** — et la grappe, les deux seules pièces que deux cerveaux partagent
  sans que rien ne l'annonce. C'est exactement ce que l'encadré « La porte qui manquait à ce
  tableau » enseigne trois lignes plus bas.
- `docs/DEMARRAGE-RAPIDE.md` renvoyait au « §7 de ce guide » — cette page numérote des
  **étapes**, pas des §.
- **Balayage mécanique de tous les liens Markdown du dépôt** (fichier cible + ancre) :
  **0 lien mort, 0 ancre absente** sur l'ensemble des `*.md`. Les renvois `§n` restants ont
  été vérifiés un par un contre les titres de leur document cible.

*(Ce lot portait ici une rubrique « Connu et non résolu » sur la cadence de sauvegarde
imprimée par `ops/watchdog.sh`, `ops/restore_verify.sh` et `ops/backup.sh` — « la
sauvegarde tourne une fois par jour ». Elle a été **retirée en [0.1.9]** : les trois
fichiers disent aujourd'hui « QUATRE FOIS PAR JOUR » et « SIX HEURES », le défaut n'existe
plus, et une dette déclarée vivante alors qu'elle est éteinte trompe autant qu'une
promesse tenue trop tôt. Voir [0.1.9], « Les sections d'honnêteté ».)*

## [0.1.7] — 2026-08-09

Lot **le cycle de vie du cerveau, traversé en entier**. Installer, remplir, sauvegarder,
casser, basculer, désinstaller, **partir avec sa mémoire**, la rouvrir ailleurs. Aucune
des lignes ci-dessous n'a été écrite depuis une lecture : deux cerveaux ont été installés
par le chemin réel (entretien `wizard.py`, `bootstrap.sh --yes`, grappe et ports dédiés),
l'un cassé par un `DROP DATABASE` sur une base vivante, l'autre déménagé sur une
installation neuve, et les deux désinstallés jusqu'au verdict « PROPRE ».

### Corrigé — la documentation

- **`docs/SAUVEGARDE.md` § 7, « respirez et mesurez » : la troisième forme du sinistre.**
  La page annonçait deux réponses possibles à la commande de mesure, toutes deux
  supposant que la base existe encore. La perte **totale** — celle que le § 1 décrit
  pourtant comme ce qu'on perd — n'était nommée nulle part. Mesuré : `FATAL: database "…"
  does not exist`, et `psql` n'ouvre même pas la connexion. Les trois formes sont
  désormais dans un tableau, avec ce que chacune change pour la suite.
- **`docs/SAUVEGARDE.md` § 7, étape 5.2 : le rouge normal, écrit noir sur blanc.** Sur une
  base perdue, la **première commande de la bascule** rend `ERROR: database "…" does not
  exist`, code 1, sous un titre qui dit « C'est le moment irréversible » — et la page n'en
  disait pas un mot. Un encadré dit maintenant que c'est **la seconde ligne qui doit
  réussir**, et donne les trois rouges qui, eux, doivent faire arrêter (mauvaise grappe,
  base vivante encore là, connexions ouvertes).
- **`docs/SAUVEGARDE.md` § 7, étape 7 : la base d'avarie qui ne naît pas.** Le tableau
  affirmait que `<base>_avarie_<date>` naît « à l'étape 5.2 ». Sur une perte totale elle
  ne naît jamais et la requête de l'étape 7 ne rend rien. Mesuré des deux côtés.
- **`docs/SAUVEGARDE.md` § 7, étape 1 : ce que `1` veut dire.** Le `2` est confirmé normal
  sur les trois formes du sinistre. Le `1` **dit lequel des deux a échoué** — la
  restauration ou l'identité — et les deux verdicts sont donnés tels qu'ils s'impriment.
  **Et son exception est nommée** : un `1` dont PREUVE D est ✓ n'accuse pas le dump, il
  dit que la base de comparaison n'est pas celle d'où ce dump vient. Mesuré sur une
  installation neuve, vide, avec un dump parfait.
- **`docs/SAUVEGARDE.md` § 7, étape 5.3 : la troisième chose que fait cette commande.**
  Elle **referme la base à `PUBLIC`**. Une base née d'un `createdb` est ouverte à tous les
  rôles de la grappe : mesuré avant le 5.3, `datacl` NULL et un rôle étranger connecté ;
  après, `REVOKE CONNECT … FROM PUBLIC` et le même rôle refusé.
- **`docs/SAUVEGARDE.md`, nouveau § 9 — « Emporter son cerveau ailleurs ».** Le
  déménagement n'existait qu'en cinq lignes de FAQ, et elles étaient fausses sur deux
  points. Le chapitre dit ce qu'on emporte (le dump **et** `config/brain.toml` **et**
  `config/scopes.toml`), ce qui se passe si l'on part sans la description (une empreinte
  neuve, et son propre dump rejeté — mesuré, avec le refus `code 6` qui interdit de
  rattraper après coup), et la procédure complète, jouée jusqu'au « VERDICT : PROUVÉ ».
- **`docs/INSTALLATION.md` § 13 : le départ.** L'étape 2 crée son dump d'adieu en **0600**
  (mesuré en 0644 auparavant — le seul dump de toute l'installation à naître lisible par
  tous). La branche (a) de l'étape 7 **sort** les dumps de la machine au lieu de les
  déplacer dans le foyer, avec empreinte prise en **noms relatifs** — un `SHA256SUMS` en
  chemins absolus fait vérifier, à l'arrivée, les fichiers restés au départ. L'étape 7
  nomme enfin la ligne `/etc/tmpfiles.d/<prefixe>-backup.conf` (qui **recrée** le
  répertoire de dumps à chaque démarrage) et la description restée dans le clone. Le
  contrôle 0 demande de **noter l'empreinte** : l'étape 9 la redemande, et le coffre qui
  la porte a été effacé à l'étape 6.
- **`docs/INSTALLATION.md` § 13, étape 9 : ce que « PROPRE » veut dire.** Le contrôle ne
  juge plus sur les noms mais sur l'**empreinte gravée dans l'objet**, et son verdict est
  **borné** — il imprime les grappes et les racines regardées. Les options `--empreinte`
  et `--fouiller` sont documentées, et la sortie réelle des deux passages (3 restes, puis
  PROPRE) est reproduite.
- **`docs/INSTALLATION.md` § 13, clôture : « Partir — ce que ce chapitre veut vraiment
  dire ».** Pouvoir repartir avec sa mémoire, et pouvoir la faire disparaître, sont les
  deux bouts d'une même promesse. Une page qui explique comment s'installer sans expliquer
  comment partir est incomplète.
- **`docs/INSTALLATION.md` § 11 : une commande qui ouvrait un fichier inexistant.** Le
  `less` visait `<prefixe>-backup.service`, que `ops/systemd/render.sh` n'écrit plus.
  Vérifié par exécution du bloc entier.
- **La cadence de sauvegarde, partout où elle restait fausse.** `ops/README.md` disait
  « le dump **quotidien** » ; `docs/EXPLOITATION.md` justifiait ses seuils par « un cycle
  **quotidien** manqué » et « la promesse « au pire, **un jour perdu** » ». La minuterie
  réelle porte `OnCalendar=*-*-* 00,06,12,18:30:00 UTC` et se décrit elle-même
  « sauvegarde toutes les six heures » — relevé sur une installation neuve. Les seuils du
  chien de garde (26 h / 48 h) sont conservés **et expliqués pour ce qu'ils sont** : des
  valeurs héritées de la cadence quotidienne, qui alertent tard et jamais trop tôt.
- **Un compte exact retiré d'un critère.** « QUATRE des cinq `DROP ROLE` échouent » était
  donné comme une règle : mesuré une fois quatre, une autre fois **les cinq**, sur la même
  version. Les deux pages renvoient maintenant au `DETAIL` de l'erreur, qui **nomme** la
  base qui retient — le seul critère qui ne bouge pas.

### Connu et non résolu

- **`ops/watchdog.sh --explain` et `ops/restore_verify.sh` portent encore la justification
  d'une sauvegarde quotidienne** (« La sauvegarde tourne une fois par jour », « 26 h = un
  intervalle de sauvegarde quotidien + 2 h »). C'est le texte que le **produit imprime**,
  et il contredit désormais ses propres unités. `docs/EXPLOITATION.md` le dit ; le code
  n'a pas été touché.
- **Le contrôle de désinstallation ne regarde que les chemins par défaut.** Une
  installation qui a déplacé `ARAC_BACKUP_DIR` ou `ARAC_LOG_DIR` peut recevoir « PROPRE »
  pendant que ses dumps survivent ailleurs. `--fouiller` existe, mais il faut le savoir :
  c'est écrit dans le rapport, pas encore dans la page.

---

## [0.1.6] — 2026-08-09

Lot **la bascule, et les schémas**. Deux moitiés : le produit apprend à survivre à une
restauration, et les **figures** du dépôt sont relues contre le code qu'elles illustrent —
un travail que six lots de correction de phrases n'avaient jamais fait. Tout ce qui suit a
été joué sur un cerveau installé pour l'occasion par le chemin réel (entretien `wizard.py`
puis `bootstrap.sh --yes`, grappe et ports dédiés), puis entièrement démonté.

### Corrigé — le produit

- **La bascule du §7 ne va plus au bout : elle y va.** `pg_restore --no-owner` rendait le
  schéma au superutilisateur, sans un droit pour les rôles du cerveau ; `bootstrap.sh
  --only migrations` — la commande que la page prescrit — mourait alors en code 7 sur
  « permission denied for schema arac », et le remède qu'elle imprimait rendait la même
  erreur. `bootstrap/lib/database.sh` **reprend** désormais la propriété du schéma et de
  ses objets, rouvre `CONNECT` et `USAGE`, **avant** d'appeler alembic. Rejoué ligne par
  ligne : `DROP SCHEMA arac CASCADE` sur un cerveau vivant, restauration, renommage,
  `--only migrations` → **code 0**, et les souvenirs se relisent **sous le rôle de
  l'application**.
- **`verify_install.sh` ne peut plus certifier un cerveau que personne ne peut lire.** Le
  seul contrôle par rôle était un `SELECT 1`, qui ne touche aucun objet du schéma : il
  rendait « ✓ Ce cerveau fonctionne » sur une base dont l'API tombait en 500. Il lit
  maintenant `arac.memory_atoms` **sous chacun des quatre rôles** (« N souvenir(s) lus SOUS
  CE RÔLE »), et il **nomme** les copies de la mémoire laissées sur la grappe.
- **La désinstallation voit ce que la restauration a créé.** `ops/uninstall_check.sh` ne
  cherchait que `<base>_restore_*` : il imprimait « ✓ aucune base » sur une grappe portant
  `<base>_avarie_…`, c'est-à-dire le cerveau entier en clair, pendant que les `DROP ROLE`
  échouaient dessus. Il décrit maintenant ce qui est **légitime** — toute base dérivée du
  nom du cerveau — et refuse d'imprimer un geste pour la base d'un voisin homonyme.

### Corrigé — les schémas et les tableaux, relus contre le code

- **`docs/POURQUOI.md`, marche 7.** Le schéma du rappel imprimait deux étages qui
  n'existent pas chez le lecteur (« ③ pondérations douces », « ④ le système annonce sa
  confiance ») dans la page qui *enseigne* le rappel, cinquante lignes après une marche 5
  disant l'inverse. Le trait déjà écrit dans `CONCEPTS.md` §4 y est reporté : au-delà,
  rien ne tourne sur une installation standard. La phrase de clôture — « le système vous le
  dira lui-même à chaque réponse » — dit désormais ce qui est vrai : c'est la **distance
  brute** qu'on vous rend, et c'est à vous de la lire.
- **`README.md`, le bandeau du cockpit.** Ses six phrases étaient présentées dans un ordre
  que le produit ne produit jamais : `today.py` les trie par rang déclaré, plus bas d'abord.
  Le bandeau est remis dans cet ordre, et le commentaire qui l'accompagnait — « devant
  `project_progress` à 30 » — inversait l'échelle.
- **`README.md` et `docs/FAQ.md`, le bloc du coût.** Il enchaînait quatre mesures sous un
  trait de division : 8 000 000 ÷ 31 500 donne ≈ 250 atomes par mois, pas les ~150
  observés. Ce qui est mesuré et ce qui est calculé sont maintenant séparés, et le lecteur
  est prévenu que diviser deux mesures prises séparément ne mesure rien.
- **`docs/ARCHITECTURE.md`, le schéma du cycle** annonçait un budget de lot « ~90 000 par
  défaut » là où `agents/cortex/pack.py` porte `DEFAULT_PACK_TOKEN_BUDGET = 80_000` — la
  valeur que quatre autres pages citaient correctement.
- **`docs/SAUVEGARDE.md` §5** annonçait « trois preuves » ; le script en imprime **quatre**
  depuis que l'empreinte d'installation voyage dans le dump (preuve D — *ce dump vient-il
  de CE cerveau ?*). Le tableau les porte toutes, et dit laquelle tombe le jour du
  sinistre.
- **`docs/PREMIER-JOUR.md` et `docs/PREMIER-MOIS.md`** portaient la **même** courbe avec
  deux axes différents (`S1` contre `J7`) et la flèche « ça ne sert à rien » à deux endroits
  différents. Les deux figures sont désormais identiques.
- **`docs/INSTALLATION.md`**, le tableau « ce qui porte le nom du cerveau » listait quatre
  unités systemd ; le bootstrap en pose cinq depuis qu'il arme la restauration
  hebdomadaire.
- **`docs/COMMENT-IL-CONSTRUIT-SES-ATOMES.md`** étiquetait « des atomes écrits » une part
  de **reçus de cycle**.

### Corrigé — les pages

- **`docs/SAUVEGARDE.md` §7 réécrit d'après une exécution, pas d'après une intention.**
  Chaque commande a été jouée sur un cerveau réel cassé pour de vrai. Y sont entrés : le
  `ARAC_ENV_FILE` sans lequel `ops/restore_verify.sh` et `ops/backup.sh` s'arrêtent avant
  d'agir sur une machine à plusieurs cerveaux ; le fait que l'étape 1 rende **2** et non
  **0** le jour du sinistre, et que seul un **1** doive faire changer de dump ; la base sur
  laquelle porte l'inspection de l'étape 4 ; le **redémarrage des deux minuteries** que
  l'étape 5.1 arrête et que personne ne rarmait ; les unités plutôt que les scripts nus à
  l'étape 6 ; et une **étape 7** qui nomme les deux bases que la bascule laisse derrière
  elle, dit ce qu'elles pèsent et comment s'en défaire.
- **`docs/INSTALLATION.md` §13 tranche sur les dumps.** L'étape 7 disait « à vous de
  voir » pendant que le contrôle de l'étape 9 comptait `/var/backups/arac/<base>` comme un
  reste : le §13 suivi mot pour mot ne pouvait pas rendre le verdict qu'il exige. Il pose
  maintenant le choix — les sortir de la machine, ou les détruire — et dit ce que le
  contrôle répondra dans chaque cas. Son étape 4 bis cherche aussi les bases nées du §7.
- **La cadence de sauvegarde**, encore fausse dans le §8 de `SAUVEGARDE.md` (« une par
  jour », « perdre jusqu'à 24 h ») et dans `FAQ.md` (« sauvegarde à 00:30 ») : quatre par
  jour, six heures au pire, et la ligne d'`OnCalendar` qui le prouve.
- **`GOAL.md`** portait « Sauvegardes ◐ — restauration jamais rejouée, aucun dump n'a
  jamais été rechargé sur une base de service ». C'est faux depuis que `make acceptance`
  joue la bascule sur un cerveau cassé pour de vrai ; la case dit maintenant ce qui a
  tourné et ce qui reste non joué (le chemin chiffré, la copie hors site).

### Connu et non résolu

- `tests/acceptance/acceptance.sh` imprime toujours « **ÉTAPE 8 / 7** » : une huitième
  étape a été ajoutée, le dénominateur du gabarit est resté à 7. Constaté sur la sortie du
  9 août 2026.
- `ops/uninstall_check.sh` peut écrire « rien ne le retient : DROP ROLE passera » d'un rôle
  que PostgreSQL refuse pourtant de détruire : ce qui le retient est un privilège **sur une
  base** (`pg_shdepend.dbid = 0`), que la jointure sur `pg_database` ne nomme pas. L'ordre
  des gestes, lui, est bon — les bases avant les rôles — et suivi tel quel il aboutit.
- Le rôle `arac_<base>_backup` est `NOLOGIN` et sans mot de passe, alors que `ops/backup.sh`
  invite à « l'ouvrir » à chaque exécution et que `.env.example` le nomme. La réserve reste
  allumée sans issue écrite.

---

## [0.1.5] — 2026-08-09

Lot **documentaire** : le seuil de confiance, la sauvegarde armée, la désinstallation.
Chaque affirmation ci-dessous a été
jouée sur un cerveau installé pour l'occasion par le chemin réel (entretien puis
`bootstrap.sh --yes`, grappe et ports dédiés, entièrement démonté depuis).

> **Rectification apportée en 0.1.6.** Cette entrée s'ouvrait sur « Aucun fichier de code
> n'a été modifié dans ce lot ». C'était faux, et cela taisait le changement le plus
> important du lot : l'unité de sauvegarde a cessé d'inliner son propre `pg_dump` pour
> appeler `ops/backup.sh`, et le bootstrap arme depuis une cinquième unité,
> `arac-<base>-restauration`. Un journal qui promet plus que ce qui a tourné est un journal
> qu'on cesse de croire ; celui qui tait ce qui a tourné aussi.

### Corrigé

- **Le seuil de 70 : cinq pages disaient le contraire du code, et l'installateur disait
  vrai.** `docs/CONCEPTS.md`, `docs/GLOSSAIRE.md`, `docs/ARCHITECTURE.md` et
  `docs/POURQUOI.md` (la marche qui *enseigne* la confiance, jamais nommée jusqu'ici)
  écrivaient qu'un atome dont le score **tombe** sous 70 sort du rappel. Mesuré, et
  désormais écrit : le déclencheur `arac.tg_auto_archive_low_confidence` est un
  **`BEFORE INSERT`** ; il exige `audit_source = 'autonomous_agent_suggest'` et un
  `confidence_score` non nul **sous 70** (69 archivé · 70 vivant · `NULL` non archivé) ;
  un `PATCH` à 10 laisse l'atome `active` et servi ; un atome sans cette trace n'est
  jamais concerné. Les quatre pages portent maintenant la même partition que
  `bootstrap/lib/verify.sh`.
- **Le piège de la supersédure est écrit là où on l'enseigne.** Une supersédure qui ne dit
  rien du chiffre **hérite** du score : l'ancien passe `superseded`, le remplaçant naît
  `low_confidence_archive`, plus aucun atome actif sur ce domaine et cette clé, et le
  rappel rend `[]` — pour un `201` sans erreur. Reproduit de bout en bout. L'avertissement
  `W-008` a été **vérifié à l'exécution** : il est bien émis par les deux chemins
  d'écriture, il est conservé dans `arac.audit_log`, et — c'est dit explicitement — il
  **n'empêche rien**, la réponse reste un `201`. Les deux gestes qui évitent le piège sont
  écrits à côté.
- **Le score ne pèse pas sur le rappel, et les manuels le laissaient croire.** Mesuré :
  deux atomes au texte identique, l'un à 95 et l'autre à 10, sortent à la **même**
  distance, et rien ne garantit l'ordre entre eux. `docs/CONCEPTS.md` §4 présentait en
  outre cinq étages de rappel dont **trois ne tournent pas** sur une installation
  nominale : les ajustements (fraîcheur, confiance, type), les bandes de confiance et le
  budget appartiennent au Context Engine, dont les drapeaux `ARAC_SHADOW_CE_*` /
  `ARAC_CE_SERVE_*` ne sont posés ni par le bootstrap ni dans le coffre. Le schéma porte
  désormais le trait qui sépare ce qui tourne de ce qui dort, avec la commande qui le
  vérifie sur sa propre machine.
- **`docs/SAUVEGARDE.md` §2 s'intitulait « Ce qui est mis en place ».** Il décrivait quatre
  planifications dont deux n'existaient pas. Réécrit en deux blocs : ce que le bootstrap
  arme réellement — `ops/backup.sh` toutes les six heures (`00,06,12,18:30 UTC`) et
  `ops/restore_verify.sh` le dimanche à 03:00 UTC, vérifiés par `systemctl cat` et
  `list-timers` — et ce qui reste à armer soi-même (copie hors site, chien de garde), avec
  les deux manques nommés en toutes lettres : dumps **en clair**, **aucune copie
  ailleurs**, tels que `ops/install_check.sh` les rapporte.
- **`docs/INSTALLATION.md` §13 ne pouvait pas aller au bout.** Rejoué à la lettre :
  l'étape 1 ne désarmait que quatre unités et laissait `arac-<base>-restauration.timer`
  `active waiting` ; l'étape 5 échouait sur `DROP ROLE arac_<base>_admin` — *owner of
  database `<base>_restore_template`*, base que l'étape 4 du bootstrap pose et que la page
  ne nommait nulle part ; trois estampilles de minuteur survivaient ; et le contrôle de
  fin rendait le nom du rôle survivant **sans pouvoir dire pourquoi**. Ajoutés : la
  cinquième unité à l'étape 1, une étape **4 bis** qui détruit les `<base>_restore_*`, le
  retrait des estampilles à l'étape 7, et une étape 9 qui appelle `ops/uninstall_check.sh`
  — lequel a nommé les sept restes avec leur cause, puis rendu `VERDICT : PROPRE` et le
  code 0 après ses propres gestes.
- **Cadences fausses ailleurs qu'au §2.** `docs/INSTALLATION.md` §1 annonçait « sauvegarde
  à 00:30 » (une fois par jour) et sa table des unités en comptait « quatre unités et deux
  minuteries ». Corrigé en cinq unités, trois minuteries, avec la commande qui donne la
  liste vraie plutôt que celle-ci.

### Connu et non résolu

- **`app/schemas/atom.py:53` commente `low_confidence_archive` par « archivé par
  garbage_collector cron ».** Aucun `garbage_collector` n'existe dans ce dépôt ; ce statut
  est posé par le déclencheur `BEFORE INSERT`. C'est un commentaire de code, hors du lot
  documentaire — signalé, non corrigé ici.
- **`ops/uninstall_check.sh` ne voit pas un lien orphelin de `*.target.wants/`.** Mesuré à
  la fin de ma désinstallation : le fichier d'unité retiré sans `disable` préalable laisse
  `/etc/systemd/system/timers.target.wants/arac-<base>-restauration.timer` pointant dans le
  vide ; `systemctl list-units --all` le rapporte en `not-found failed failed`, et le
  contrôle rend pourtant « ✓ aucune unité ». Le §13 s'en protège désormais des deux côtés
  (étape 1 complète, filet à l'étape 3), mais le contrôle devrait le voir. Fichier de
  produit, hors du lot documentaire.
- **`tests/acceptance/acceptance.sh:872` annonce toujours « 10 étapes ».** Sixième manche.
  Son motif exige une minuscule en tête de ligne et rate `(épilogue)` ; le même rapport
  écrit « simulation : 11 étapes » treize lignes plus haut, et `bootstrap/lib/core.sh:37`
  porte `TOTAL_ETAPES=11`. Fichier de test, hors du lot documentaire.
- **`make test` n'est pas hermétique au reste de la machine.** Mesuré : sur un clone neuf
  (sans `config/brain.toml`, comme tout clone), `control_center/security.py:505` calcule
  `_CC_LOG_PRIMARY` à l'import et retombe sur `/var/log/arac/cerveau_de_test/cc_access.log`.
  Si ce fichier existe — c'est le cas ici, laissé par une autre session —, la garde
  hermétique refuse la lecture et **12 tests échouent**, sans qu'aucun ne concerne l'arbre.
  Avec `ARAC_LOG_DIR` pointé dans le dépôt : **4967 verts sur clone git, 4938 sur copie
  sans `.git`**, et l'unique rouge restant est `test_g2_…::test_chaque_chemin_porte_le_nom_du_cerveau`,
  qui lit cette même variable depuis l'environnement ambiant — il repasse au vert dès
  qu'on la retire. Les deux bouts sont des fichiers de produit et de test ; aucun n'est
  imputable à ce lot documentaire.

---

## [0.1.4] — 2026-08-09

Lot **la preuve verte par construction** : une assertion qui ne peut pas échouer, un écran
qui promet un effet que le produit n'a pas, et des gardes qu'on a enfin essayé de faire
rougir au lieu de les croire.

### Corrigé

- **L'écran de fin de `bootstrap.sh` promettait que la confiance classait les rappels.**
  La leçon « 96 % des rappels rendus en confiance basse » de `bootstrap/lib/verify.sh`
  écrivait « le cerveau s'en sert pour classer : sous 50 il éloigne, à 85 et plus il
  rapproche ». **Mesuré le 9 août 2026 sur un cerveau posé par le vrai chemin** (« vide1brain »,
  grappe `5496`, API `8320`) : deux atomes au texte STRICTEMENT identique, l'un à
  `confidence_score = 95`, l'autre à `10`, sortent du même `POST /v1/atoms/recall` à la
  distance `1.105593236593197` — la même, au dernier chiffre. La cause est structurelle :
  `recall()` fige sa réponse sur un kNN dense pur, et le seul organe qui pèse la confiance
  (`ConfidenceModifier`) n'est atteint que par `context_shadow.serve_r3`, gardé par
  `serve_enabled_for()` — deux drapeaux d'expérimentation que le bootstrap n'écrit nulle
  part, et qui ne concernent que deux consommateurs internes. La leçon dit désormais ce qui
  est mesuré : ce nombre ne change RIEN à ce qui est rendu ni à son ordre.
  *C'est la même famille que le défaut de la manche précédente, sur le même écran, dans la
  correction qui devait le fermer : un geste servi, un effet absent.*
- **Le seul effet réel du score était mal nommé, et il coûte un souvenir.**
  `arac.tg_auto_archive_low_confidence` est un trigger **BEFORE INSERT** — jamais UPDATE.
  Mesuré : seuil exact `69` archivé / `70` actif ; il ne lit pas le niveau déclaré
  `confidence` mais la trace d'audit `audit_source = 'autonomous_agent_suggest'` ; un atome
  `confidence='agent_suggest'` sans cette trace reste actif à `10`. Conséquence que l'écran
  taisait : la supersédure HÉRITE le score quand l'appelant n'en parle pas, donc superséder
  une suggestion d'agent déjà sous 70 — ne serait-ce que pour corriger une faute de frappe —
  archive le remplaçant à la seconde où il naît, alors que l'original vient d'être marqué
  `superseded`. **Mesuré : réponse `201`, aucune erreur, `warnings: []`, et
  `SELECT count(*) … status='active'` sur ce domaine et cette clé rend `0` ; `/recall` rend
  `[]`.** La leçon le dit maintenant, avec les deux gestes qui l'évitent.

### Ajouté

- **`W-008` — l'atome qui naît hors du rappel le dit.** `app/routers/atoms.py` compare
  désormais le `status` RENDU par la base au `status` demandé, sur les deux chemins
  d'écriture (`create_atom`, `supersede_atom`), et émet un warning nommé quand ils
  diffèrent. Éprouvé sur cerveau réel : la supersédure ci-dessus rend `201` **et** porte
  `W-008`, conservé dans `arac.audit_log`. Il lit le RÉSULTAT et non la cause : un futur
  trigger qui ferait naître un atome `draft` sortirait le même avertissement.
- **`tests/test_l_ecran_de_fin_ne_promet_pas_un_effet_absent.py` (G5).** G4 déclare lui-même
  ne pas couvrir « le geste servi mais SANS EFFET » : c'est par là que la fausseté est
  revenue. G5 tient trois faits ensemble — le chemin servi est aveugle à la confiance,
  l'écran ne doit donc pas dire le contraire, et le seuil imprimé est LU dans le trigger SQL
  au lieu d'être recopié. **Éprouvé en remettant la phrase exacte dans `verify.sh` : rouge.**

### Modifié

- **Le garde du jeton ne regardait que huit fichiers écrits à la main.** Éprouvé : le même
  appel nu ajouté à `agents/lib/bus.py` (listé) rendait `1 failed` ; ajouté à
  `control_center/collectors/db_metrics.py` (non listé), `27 passed`. Un appelant NEUF —
  et il y en avait eu onze le jour où la porte s'est fermée — n'était vu par personne. Un
  balayage de tout le dépôt complète la liste, avec un témoin qui refuse de rester vert si
  le motif d'appel cesse de reconnaître quoi que ce soit.
- **Le repli du corpus pouvait redevenir MUET sans qu'un test bouge.**
  `test_le_repli_dit_ce_qu_il_fait` vérifiait la CONSTANTE `PHRASE_DU_REPLI`, pas sa
  prononciation : en retirant `warnings.warn(...)` de `_decider()`, le fichier rendait
  `4 passed`. Le repli est maintenant EXÉCUTÉ, `git` déclaré indisponible, et
  l'avertissement exigé.
- **G4 ne voyait pas une route écrite en URL.** `curl -X POST http://…/v1/atoms/valider`
  passait (`20 passed`) là où `POST /v1/atoms/valider` rougissait — c'est-à-dire la forme
  même sous laquelle un écran montre une route à quelqu'un qui doit la taper. Le corpus
  imprimé n'en contenait alors aucune : faute latente, fermée avant qu'elle serve.

### Connu et non résolu

- **Une route morte citée dans un `.md` n'est vue par personne.** G4 déclare la
  documentation hors de son corpus et renvoie à `tests/test_la_doc_dit_vrai.py` ; ce
  dernier pose sept règles de prose, dont aucune ne demande si une route citée existe.
  Mesuré : `POST /v1/atoms/valider` ajouté à `docs/FAQ.md` → **`3018 passed`**. Non fermé
  ici parce que quatre citations actuelles (`PATCH /v1/atoms/`, `GET
  /cc/v1/scopes/travail/strategie`) sont des formes paramétrées qu'une règle naïve
  accuserait à tort : la règle doit être écrite avec le lot documentaire, pas contre lui.
---

---

## [0.1.3] — 2026-08-09

Lot **documentaire** : ne subsiste dans les manuels aucune sortie de programme qui n'ait
été obtenue, aujourd'hui, par la commande annoncée — ou qui ne soit déclarée comme ne
l'ayant pas été. Aucun fichier de code n'a été modifié dans ce lot ; tout ce qui suit est
mesuré sur un cerveau réellement installé pour l'occasion (grappe dédiée, ports dédiés,
démonté depuis) et sur un clone neuf.

### Corrigé

- **`docs/INSTALLATION.md` §2 promettait cinq lignes et un écran que personne ne voit.**
  Le point de contrôle 2 enchaîne `make test` puis `make doctor`, et annonçait « **cinq
  lignes** » dont `taxonomie : ABSENTE`. Mesuré : sur un clone vierge, `make doctor` rend
  bien cinq lignes sur la **sortie standard**, mais les deux sondes qui échouent ont déjà
  craché leur `Traceback` sur la sortie d'erreur — dans un terminal, cela fait une
  quarantaine de lignes et deux traces. Et surtout, la ligne `taxonomie` ne dit plus
  `ABSENTE` **à ce point du parcours** : `make test`, la commande juste au-dessus, engendre
  une taxonomie d'essai depuis `config/scopes.example.toml` (`tests/conftest.py`) et la
  laisse sur le disque — la ligne rend alors le compte de l'exemple. La page dit maintenant
  les deux, donne `make doctor 2>/dev/null` pour n'obtenir que le bilan, et cesse de
  promettre un écran qu'aucun lecteur suivant l'ordre des commandes ne verra.
- **`docs/DEPANNAGE.md` se méfiait du seul de ses trois contrôles qui a raison.** Une
  réserve de dix lignes, au présent, expliquait qu'`ops/install_check.sh` balaie les unités
  par le motif `arac-*` et qu'une unité d'un **voisin** en échec fait basculer le verdict.
  Le script l'a corrigé : il dérive son motif de l'identité du cerveau
  (`ARAC_UNIT_PREFIX`, sinon `arac-<base>-*`) et liste les autres sous « PAS LES VÔTRES »
  sans les compter. Mesuré sur une machine portant treize minuteurs `arac-*`, dont **une
  unité réellement en échec** : verdict `0 panne(s)`, code `1`. La réserve devient une
  leçon au passé ; « constat ouvert » disparaît.
- **La même page écrivait la première commande avec `sudo` et la deuxième sans.**
  `ops/install_check.sh` a besoin de root : le coffre est en `0700 root`. Mesuré depuis
  `nobody`, coffre pourtant nommé : sept `✗`, « Cette installation ne tient PAS debout »,
  code `2` — sur un cerveau dont `/healthz` répond `200` à la même seconde. Corrigé ici et
  dans `docs/EXPLOITATION.md` §1, avec la variante à poser sur une machine qui porte
  plusieurs cerveaux (`ARAC_ENV_FILE`), que le script réclame lui-même.
- **Trois pages recopiaient un compte de « pont de vocabulaire » périmé.**
  `DEMARRAGE-RAPIDE` annonçait « **7** variable(s) traduite(s) » et une fourchette « 5 ou
  7 » ; `DEPANNAGE` §1 donnait « 7 » comme attendu du script de réparation. Mesuré sur une
  installation aux deux clés différées : l'écran rend **8** (le bootstrap imprime sa propre
  fourchette, 8 ou 10, à jour), et le script de réparation rend **5**. Les deux pages
  cessent de recopier le nombre : elles renvoient à celui que le programme imprime et
  gardent le seul critère qui ne périme pas — les deux `grep`, qui doivent rendre `4` et
  `3` (rejoués, ils les rendent).
- **`docs/FAQ.md` citait deux routes sans leur préfixe de version.**
  `POST /atoms/context_for` et `POST /atoms/recall`, à l'endroit exact où le lecteur les
  recopie pour écrire sa colle. Mesuré : `404` sans `/v1`, la route existe avec.
- **`docs/FAQ.md` promettait encore que « la calibration s'améliore quand vous validez ».**
  C'est le rituel impossible corrigé en 0.1.1, resté dans un second exemplaire de la même
  page — soixante lignes sous le passage qui dit déjà juste.
- **Gabarits de sortie qui figeaient ce qui bouge.** La ligne verte de `make test` était
  écrite « 5 xfailed, 1 warning in ~20s » (mesuré : cinq avertissements, et quatre fois
  cette durée sur un serveur modeste) ; le verdict de `verify_install.sh` recopiait
  « sains 31 à surveiller 4 » (mesuré : `45` et `2` sur l'installation d'essai) ; le
  récapitulatif de `--dry-run` omettait sa première ligne (`serveur 127.0.0.1:<port>`) et
  le fuseau des cycles ; l'écran des prérequis condensait cinq lignes en une et figeait
  quatre numéros de version. Tous paramétrés, avec le critère qui reste vrai.
- **Un message de panne recopié de mémoire.** `DEPANNAGE.md` §1 citait « l'API ne sait pas
  à quelle base **se connecter** » ; `app/db.py` imprime « à quelle base **parler** ». Une
  page où l'on cherche par ce qu'on voit doit porter les mots qu'on voit.
- **Le contrôle PostgreSQL du §1 de `INSTALLATION.md` montrait deux versions sans leur
  nom, dans un ordre que la requête ne fixe pas.** La requête nomme maintenant l'extension
  et trie ; le bloc de sortie cesse de figer des numéros de version qui portent, en vrai,
  le suffixe de la distribution.

### Connu et non résolu

- **Les mesures du cerveau de référence citées dans les manuels datent du 8 août 2026** —
  proportions de quarantaine, de provenance perdue, de confiance basse, de savoir non
  audité, part des atomes posés sur une racine. Elles n'ont **pas** été re-mesurées le
  9 août : chaque cellule porte sa date, et c'est cette date qu'il faut lire. Ce sont des
  proportions, pas des comptes, précisément pour qu'elles vieillissent lentement.

---

## [0.1.2] — 2026-08-08

### Sécurité

- **Le jeton porteur est exigé de TOUTE requête, `127.0.0.1` compris.** Seul `/healthz`
  reste public. Ce n'est pas un durcissement de confort : c'était le dernier chemin par
  lequel deux cerveaux d'une même machine se lisaient et s'écrivaient l'un l'autre.
  **Mesuré**, depuis le compte `nobody`, sans un seul secret :
  `GET /v1/dashboard/search` → `200` (la mémoire du voisin en clair),
  `POST /v1/ingest/messages` → `202` (une écriture chez le voisin).

  **Ce qui rend cette porte instructive, c'est ce qui ne la fermait pas.** Comptes système
  distincts, coffres `0700`, rôles PostgreSQL par cerveau, grappes séparées, unités
  nommées : tout cela existait déjà et n'y changeait rien, parce que cette porte **ne
  passe par aucun fichier** — aucune permission ne s'y applique. La leçon, qui sert
  ailleurs : *une exemption fondée sur l'origine d'une requête ne vaut que ce que vaut
  l'hypothèse sur qui peut prendre cette origine.* `127.0.0.1` ne prouve pas « c'est le
  propriétaire » ; elle prouve « c'est quelqu'un sur cette machine », c'est-à-dire
  exactement la population dont on se protège.

  Le défaut est **fermé pour tous, dès la première installation** — et non « fermé quand
  un voisin apparaît », qui aurait été asymétrique : le second cerveau se serait fermé, le
  premier serait resté ouvert, et le fermer aurait exigé d'écrire dans le coffre du
  voisin. Coût pour l'utilisateur : **nul**, le bootstrap engendrait déjà le jeton et tout
  ce qui appelle l'API le porte.

  Le desserrage reste possible et exige désormais **deux** variables :
  `ARAC_API_TRUST_LOOPBACK=1` **et** `ARAC_API_TRUST_LOOPBACK_RAISON="<date — motif>"`.
  Sans le motif, il n'est pas appliqué, et le refus le dit. Ce qui avait laissé cette
  porte ouverte n'était pas une valeur mal choisie : c'était une valeur **implicite**, que
  personne n'avait écrite et que personne ne pouvait donc relire ni contester.

### Corrigé

- **Le dépôt enseignait encore « il n'y a rien à défendre », et il l'attribuait au
  fichier qui dit le contraire.** `README.md`, `docs/FAQ.md`, `docs/ROADMAP.md`,
  `docs/CONTRIBUER.md`, `bootstrap/README.md`, l'écran de fin de `bootstrap/lib/verify.sh`
  et le gabarit `deploy/ssh/99-arac-pont.conf` portaient l'ancienne posture réseau — dont
  la phrase « sur la boucle locale, le tunnel *est* l'authentification (`app/auth.py`) »,
  donnée comme vérifiée **dans** `app/auth.py`, qui vient d'être réécrit pour la nier. Les
  quatre docstrings d'en-tête gouvernées par ce middleware (`app/main.py`,
  `app/routers/{brain,ingest,missions}.py`) annonçaient elles aussi « jeton exigé hors
  boucle locale » : le lecteur qui suivait le renvoi trouvait l'inverse de ce qu'on venait
  de lui dire. Chaque passage a été réécrit **en leçon**, pas en note de version : le
  tunnel dit d'où vient une requête, jamais qui l'envoie ; une machine qui n'accueillera
  jamais qu'un cerveau n'est pas une raison de laisser sa mémoire lisible par tout compte
  local ; un défaut implicite est un défaut que personne ne peut relire.
- **Le garde documentaire n'avait aucune prémisse sur l'authentification.** Son corpus
  était pourtant le bon depuis la version précédente — tout ce que `git` transporte — et
  il n'a rien vu du fait le plus neuf du dépôt : `grep 'boucle locale\|loopback\|jeton'
  tests/test_la_doc_dit_vrai.py` ne rendait rien. Il porte désormais la règle 7, avec sa
  prémisse lue dans le code (`app.auth.bearer_requis`, et la liste des valeurs qui
  desserrent), et la seule dispense qui vaille : citer l'ancienne phrase **pour la
  déclarer périmée**. Elle a trouvé quatre exemplaires de plus que le balayage à la main.
- **Le canari s'était endormi derrière un `skip`.** `tests/test_dashboard_ingest.py`
  portait un test nommé « accessible sans Bearer » dont la docstring annonçait :
  « si une vague future durcit l'auth dashboard, ce test deviendra le canari ». La vague
  est passée ; il est resté vert parce qu'il était `SKIPPED` faute de base. Il est
  retourné — il attend `401` et les quatre champs du refus — et surtout **il ne dépend
  plus d'une base** : le middleware refuse avant d'atteindre la route, donc avant toute
  connexion. Un canari qui dort n'est pas un canari.
- **La page de dépannage du pont ouvrait sa section `401` sur le cas du reverse proxy.**
  C'était juste tant que la boucle locale était exemptée : un `401` ne pouvait alors venir
  que du dehors. Depuis le durcissement, la cause courante est tout autre —
  `ARAC_TOKEN_FILE` absent, fichier introuvable, rotation non répercutée — et sans le
  moindre proxy. La section est réordonnée et donne la règle qui évite de se tromper de
  page : *jeton absent ou inconnu → `401` ; jeton valide mais poste non déclaré → `403`.*
  `mac/arac-sync.py` imprimait la même confusion à l'écran au moment de l'échec ; son
  diagnostic sépare maintenant les deux codes.
- **Un tableau « ce qui a été vérifié » cochait une case que sa méthode ne soutenait pas.**
  `docs/COMMENT-IL-CONSTRUIT-SES-ATOMES.md` prouvait « le cockpit n'a aucune route
  d'écriture » par « aucun `@router.post/put/delete/patch` dans `control_center/` ». Ce
  balayage ne rend rien — mais pas parce que la route n'existe pas : parce qu'elle s'écrit
  `@a.post("/cc/login")`. La preuve était **verte par construction**. La méthode est
  maintenant l'énumération de la table de routage (`create_app().routes`), qui voit une
  route quelle que soit sa déclaration, doublée d'une écriture réellement tentée sous le
  rôle du cockpit. Toutes les cases du dépôt ont été repassées au même crible.
- **Le contrôle bloquant de la désinstallation décrivait une plaque de propriété périmée.**
  `docs/INSTALLATION.md` §13 annonçait `arac:cerveau=<base>;secrets=/etc/arac/<base>` ; la
  plaque porte quatre champs depuis l'ajout de l'**empreinte**. Pire que périmé :
  **insuffisant** — le critère annoncé accepte les rôles d'un cerveau **homonyme**, ce
  qu'un `DROP ROLE` rend irréversible. Le contrôle lit désormais `empreinte=`, et il est
  donné sous une forme mécanique qui ne doit rien rendre.
- **Le garde documentaire ne lisait que le Markdown.** `tests/test_la_doc_dit_vrai.py`
  balaie maintenant **tout ce que `git` transporte** ; hors Markdown, il lit les
  commentaires et les docstrings. C'est la cause mécanique du même défaut revenu cinq
  manches de suite : ce qui était nommé était corrigé dans les manuels et survivait dans
  le code.
- **`/opt/arac` ne portait le nom de personne.** `docs/INSTALLATION.md` et `.env.example`
  recommandaient un répertoire commun pour la seule pièce de l'installation qui ne se
  partage pas. La convention est `/opt/<votre_base>`, celle que le bootstrap propose
  lui-même.
- **Neuf familles de contrôles, pas sept.** `verify_install.sh` en annonce neuf (0 à 8) ;
  `GOAL.md`, `docs/INSTALLATION.md` §7 et `bootstrap/README.md` en listaient sept, et
  taisaient la seule qui tourne sans rien d'installé (`--simulation`, famille 0).
- **Les titres ne comptent plus les rôles.** Cette ligne disait, à la version précédente,
  « cinq rôles, dont quatre qui se connectent » et se rangeait sous *Corrigé*. Le **fait**
  était juste — `bootstrap/lib/database.sh` crée `_admin`, `_app`, `_agent`, `_readonly`
  avec `LOGIN`, puis `_backup` en `NOLOGIN`, parce que les migrations `0009` et `0010`
  lui accordent `SELECT` et que PostgreSQL refuse un `GRANT` vers un rôle absent. La
  **correction**, elle, n'avait atteint que `bootstrap/README.md` : le titre de l'étape 3
  rendu par `bootstrap.sh --etapes`, l'en-tête pédagogique de l'installation, le titre de
  la famille 3 de `verify_install.sh` et la section 1 de `.env.example` annonçaient
  toujours « quatre rôles ». Une ligne sous *Corrigé* qui laisse la fausseté vivante dans
  l'installateur lui-même contredit la règle en tête de ce journal.
  Le remède n'est pas de recopier le bon chiffre une sixième fois : c'est de **cesser de
  compter là où un critère qualitatif suffit**. Les titres disent maintenant « la base et
  ses rôles », « 3. Les rôles » ; le chiffre ne subsiste que là où il enseigne quelque
  chose — « quatre rôles **qui se connectent**, quatre pouvoirs différents » —, et
  l'étape 3 nomme `_backup` et sa raison au lieu de l'additionner. Un compte est la valeur
  qui périme le plus vite : il ne doit jamais être ce qu'un lecteur doit retenir.

---

## [0.1.1] — 2026-08-08

Aucun changement de comportement : cette version ne corrige que des **affirmations**.
Chacune était vraie quand elle a été écrite, et avait cessé de l'être. Les lignes de la
`0.1.0` ne sont pas réécrites — un journal daté vaut par ses dates ; celles qui suivent
les remplacent.

### Corrigé

- **Quatre documents enseignaient un rituel impossible.** `PREMIER-JOUR`, `PREMIER-MOIS`,
  `DEPANNAGE`, `FAQ` — et, non repéré jusqu'ici, `DEMARRAGE-RAPIDE` — demandaient
  d'ouvrir le cockpit chaque semaine pour « trancher quelques propositions », et
  promettaient que « la calibration s'améliore quand vous validez ». Le cockpit ne peut
  pas écrire : sa seule route non-GET est la connexion, et son rôle PostgreSQL ouvre
  toutes ses transactions en lecture seule. Et la confiance d'un atome est fixée à sa
  naissance — absente du schéma de modification de l'API, héritée par la supersédure.
  **Le lecteur attendait un effet qui ne pouvait pas venir, et en concluait qu'il s'y
  prenait mal.** Les cinq passages disent maintenant ce qui existe (`supersede`, `PATCH`,
  `DELETE` sur `/v1/atoms/`), ce qui n'existe pas, et où le chantier est déclaré.
- **Les sections d'honnêteté décrivaient un passé périmé.** `README` §7c, `ROADMAP` §1.2,
  `DEMARRAGE-RAPIDE`, `INSTALLATION` et `bootstrap/README` niaient encore l'exécution
  réelle du bootstrap. Elle a eu lieu : deux installations complètes depuis une base
  vide, avec deux taxonomies différentes, rendent un `pg_dump --schema-only` identique —
  c'est le critère retenu, une égalité plutôt qu'un compte d'objets, parce qu'un compte
  périme à la migration suivante. Ce qui n'a toujours pas eu lieu est écrit à côté, et
  c'est le plus important : **aucune conversation n'a été ingérée par une installation
  issue de ce bootstrap**, la restauration d'une sauvegarde n'a jamais été rejouée, le
  pont n'a jamais tourné sur un Mac, et personne ne s'est jamais connecté au cockpit avec
  un mot de passe tapé.
- **La même correction avait manqué son troisième exemplaire.** La phrase ci-dessus a
  d'abord été écrite sans sa restriction — « aucune conversation n'a jamais été ingérée »,
  au présent et sans sujet — et corrigée dans `README` §7c et `GOAL.md` seulement. Elle a
  survécu intacte dans `docs/ROADMAP.md` §1.2 et dans `bootstrap/README`, c'est-à-dire
  dans les documents vers lesquels les deux premiers renvoient. Le cerveau de référence a
  ingéré, digéré, vectorisé, et rappelle : `arac.run_receipts` porte la trace du cycle,
  et aucun atome actif n'est sans embedding. Les quatre exemplaires disent maintenant la
  même chose, et **un seul** — `README` §7c — la tient à jour ; les trois autres y
  renvoient. *Leçon retenue : une affirmation corrigée à deux endroits sur trois est une
  contradiction gagnée, pas une fausseté perdue.*
- **Deux documents exigeaient du même contrôle deux verdicts incompatibles.**
  `INSTALLATION` imposait zéro point à surveiller ; `verify_install.sh` réussit, et rend
  le code `0`, dès lors qu'aucun contrôle n'est en échec — avec l'une de ses **deux**
  phrases de réussite selon qu'il reste ou non des points à surveiller. Un utilisateur
  dont l'installation était saine s'arrêtait net. Les deux phrases sont désormais
  enseignées ensemble partout.
- **`README` §7f et `INSTALLATION` §2 se trompaient sur le versionnement** des deux
  fichiers de configuration écrits par l'entretien : ils ne sont pas versionnés,
  `.gitignore` les exclut, et `git check-ignore -v` le dit en une commande. Un lecteur
  qui clone ne les reçoit pas — ce qu'on lui promettait à leur sujet ne pouvait donc pas
  se produire.
- **`INSTALLATION` et `CONFIGURATION` recommandaient encore `ARAC_SCHEMA` et
  `ARAC_ROLE_PREFIX`**, que le bootstrap refuse désormais avec le code de sortie `6` —
  les migrations nomment le schéma et les quatre rôles en toutes lettres. La
  recommandation est retirée ; la leçon qu'elle portait est conservée, y compris sa
  conséquence : les rôles PostgreSQL sont globaux au cluster, pas à la base.
- **Un compte exact servait de critère** dans `EXPLOITATION` (le nombre de métriques à
  seuils, périmé d'une unité). Remplacé par la commande qui les recompte.

### Ajouté

- **`tests/test_la_doc_dit_vrai.py`** — le garde qui aurait attrapé les cinq faussetés
  ci-dessus. Il balaie **tout** le Markdown que `git` rendrait à un inconnu qui clone,
  sans privilégier aucun répertoire : le garde précédent du dépôt bornait son balayage à
  un seul dossier, et **la réparation avait eu exactement la taille du garde-fou**. Ses
  prémisses sont lues dans le code (routes du cockpit, schémas de l'API, verdicts de
  `verify_install.sh`, boucle de refus de `bootstrap/lib/config.sh`) plutôt que
  recopiées : le jour où le code change, c'est la prémisse qui tombe la première, et son
  message dit quels documents relire. Écrit **avant** les corrections, et laissé échouer
  d'abord.

### Connu et non résolu

- **Il n'y a aucun moyen de marquer un savoir comme vérifié.** `confidence` (le niveau
  déclaré : `producer` / `auditor_validated` / `agent_suggest`) et `audit_source` sont
  fixés à la naissance de l'atome : absents du `PATCH`, hérités par la supersédure. Un
  atome né `agent_suggest` le reste, même après que vous en avez réécrit la valeur. La
  boucle de validation devra passer par une route d'écriture hors du cockpit — c'est un
  choix d'architecture à faire, pas un bouton à ajouter.
  *(Précision apportée en 0.1.3, parce que cette ligne était trop large : le **score
  chiffré** `confidence_score` (0-100), lui, **est** modifiable — `PATCH /v1/atoms/<id>`
  l'accepte et l'écrit. Ce qui manque, c'est la **trace d'audit**, et c'est bien elle que
  compte la mesure « 98 % du savoir jamais audité ».)*

---

## [0.1.0] — 2026-08-06

Première version du dépôt en tant que **framework**. ARAC cesse d'être le cerveau d'une
personne pour devenir la machine qui permet à quelqu'un d'autre de créer le sien.

### Ajouté

- **L'entretien de naissance** — `bootstrap/wizard.py`. Cinq questions, aucune
  installation, deux fichiers écrits (`config/brain.toml`, `config/scopes.toml`). La
  taxonomie est construite par l'utilisateur ; aucune valeur n'est héritée de personne.
  *Testé.*
- **Le générateur de taxonomie** — `bootstrap/generate_scopes.py`. Transforme la
  taxonomie en énumération Python (`app/schemas/scope_generated.py`) et en seed SQL
  (`db/seeds/scopes.sql`). Refuse une taxonomie invalide avec un message qui **enseigne
  la règle** plutôt que de citer une erreur. Refuse de retirer un scope encore habité.
  *Testé — six taxonomies invalides sur six refusées.*
- **Le bootstrap d'installation** — `bootstrap/bootstrap.sh` et ses onze étapes, chacune
  annonçant pourquoi elle existe, ce qu'elle construit et ce que cela changera dans le
  comportement du cerveau. Modes `--check`, `--dry-run`, `--from <étape>`.
  *Écrit, non exercé sur une machine neuve.*
- **Le moteur** — API FastAPI (`app/`), agents de curation et de digestion (`agents/`),
  cockpit en lecture stricte (`control_center/`), la chaîne de migrations Alembic (`db/`).
  Chemins paramétrés (`ARAC_HOME`, `ARAC_DB`, `ARAC_NODE_ID`…).
- **Le pont machine → serveur** — `mac/arac-pont.sh`, `mac/arac-sync.py`. Montre ce qui
  part **avant** de l'envoyer, refuse d'automatiser tant que la première synchronisation
  n'a pas été vue. *Validé sur Linux contre un serveur simulé ; jamais exercé sur un Mac.*
- **L'exploitation** — `scripts/ops/health_check.py` (lit le registre de métriques du
  cockpit, ne redéfinit aucun seuil), `scripts/ops/alerts.py` (quatre alarmes, chacune
  une conjonction), `ops/watchdog.sh`, `ops/restore_verify.sh`, `ops/install_check.sh`.
- **La suite de tests hermétique** — ni base, ni réseau, ni clé d'API. Le critère est
  **aucun échec** ; le nombre de tests, lui, monte à chaque correctif et n'a pas à être
  comparé à une valeur de référence.
- **La documentation** — README (coût, prérequis et limites **en première page**),
  `DEMARRAGE-RAPIDE`, `INSTALLATION`, `PONT-MAC`, `EXPLOITATION`, `SAUVEGARDE`,
  `CONCEPTS`, `ARCHITECTURE`, `PHILOSOPHIE`, `GLOSSAIRE`,
  [`PREMIER-JOUR`](docs/PREMIER-JOUR.md), [`CONTRIBUER`](docs/CONTRIBUER.md),
  [`ROADMAP`](docs/ROADMAP.md).
- **Le cadre de projet** — `LICENSE` (MIT, proposée), gabarits d'issue et de proposition,
  intégration continue minimale qui lance la suite hermétique.

### Modifié

- **La taxonomie n'est plus livrée, elle est engendrée.** L'énumération de scopes n'est
  plus un fichier du dépôt : elle est produite depuis la taxonomie de l'utilisateur.
- **Tous les chemins sont paramétrés.** Plus aucun répertoire d'installation, nom de base
  ni identifiant de poste en dur.

### Retiré

- **Les notes personnelles de l'auteur d'origine** (plus d'un millier de fichiers de
  travail). Elles ont servi à comprendre le système ; elles n'ont pas leur place dans un
  framework.
- **Toute trace nominative** — noms, société, lieux, scopes réels, chemins de machine,
  identifiants de poste. Seule subsiste une taxonomie d'exemple, explicitement désignée
  comme telle et accompagnée d'un « ne copiez pas ceci, écrivez la vôtre »
  (`config/scopes.example.toml`).

### Sécurité

- **Rien n'écoute en dehors de la boucle locale.** API (`:8000`) et cockpit (`:8100`)
  sur `127.0.0.1` ; l'accès passe par un tunnel SSH, avec une clé bridée côté serveur
  (`restrict,port-forwarding,permitopen=…`) qui n'ouvre rien d'autre que ces deux ports.
- **Quatre rôles PostgreSQL séparés** — `arac_admin` (DDL), `arac_app` (lecture/écriture,
  sans `DELETE`), `arac_agent`, `arac_readonly` (le cockpit, en lecture stricte).
  `ops/install_check.sh` **tente réellement une écriture** avec le rôle en lecture seule :
  elle doit échouer.
- **Aucun appel payant par défaut.** `ARAC_ALLOW_PAID_AI=0` : le cerveau tourne, lit, et
  ne dépense rien tant que vous ne l'avez pas armé. Deux autres freins existent
  (`ARAC_PACK_TOKEN_BUDGET`, `agents/lib/spend_guard.py`).
- **Le poste source est authentifié** : liste blanche `ARAC_INGEST_ALLOWED_NODES`
  (fail-closed) **et** clé étrangère sur `arac.nodes`. Une conversation venant d'un poste
  non déclaré est refusée.
- **Les secrets ne sont pas versionnés.** `.env` en `0600`, hors de git, et un contrôle
  qui vérifie qu'il l'est resté.

### Connu et non résolu

Le détail, avec les gestes de contournement, est dans [`docs/ROADMAP.md`](docs/ROADMAP.md).

- ~~**Le bootstrap ne pose le pont de vocabulaire que pour `arac.env`, pas pour
  `cockpit.env`.**~~ **Corrigé.** `poser_pont_de_vocabulaire`
  (`bootstrap/lib/secrets.sh`) traite désormais les **deux** fichiers ; c'était la
  dernière intervention humaine du parcours d'installation. Le contrôle qui tranche, sur
  votre machine : `grep -cE '^(CC_SESSION_SECRET|CC_ADMIN_PASSWORD_HASH|CC_TOTP_SECRET)='
  /etc/arac/<votre_base>/cockpit.env` doit rendre `3`. S'il rend `0`, votre installation
  est antérieure au correctif : le geste manuel est dans `docs/DEPANNAGE.md` §1.
- **La couche de liens entre atomes est écrite, jamais lue.** La table `arac.atom_links`
  existe sur toute installation neuve (migration `0033`, dans la chaîne appliquée) et le cycle y
  écrit trois types d'arêtes à chaque tour. Aucun chemin de rappel ne la consulte, et le
  cockpit non plus — il le déclare panneau par panneau au lieu d'afficher un zéro.
- **Rien ne détecte les contradictions.** Le verdict `DISPUTED` existe dans
  `agents/curator/gate.py` ; aucun appelant ne lui passe le drapeau.
- **La vérification des atomes n'est alimentée par rien.** `last_verified_at` et
  `confirmed_until` sont `NULL` partout.
- **Aucun contrôle n'empêche un atome d'être posé sur une racine**, alors que c'est le
  piège le plus coûteux du système (9 % du corpus de référence).
- **Deux vocabulaires de sauvegarde coexistent** — `ops/` et l'unité engendrée par le
  bootstrap. Les deux fonctionnent, ils ne se connaissent pas.
- **Résidus d'origine** dans les commentaires d'`app/`, `agents/` et `control_center/`,
  dont des renvois vers des documents absents du dépôt.
- **Jamais exercé** : l'installation sur une machine neuve (F4), le premier jour vécu par
  un inconnu (F8), le pont sur un vrai Mac, un cycle de digestion contre une vraie base
  avec de vraies clés.

### Mesures citées dans cette version

Toutes proviennent d'**une seule** installation de référence, en régime établi. Elles
sont reprises dans la documentation comme des observations, jamais comme des garanties :
3 cycles par jour (04:00 · 13:00 · 21:00) · ~87 000 jetons par cycle · ~31 500 jetons par
atome produit · ~150 atomes par mois · 36 % de cycles sans atome · 76 % de provenance
perdue · 96 % de rappels en confiance basse · 98 % du savoir jamais audité · ~9 % des
atomes posés sur une racine nue (donc hors de l'état courant, de la vue des scopes et de
la couverture).

---

## Avant 0.1.0

Ce dépôt n'a pas d'histoire publique antérieure. Le système existait auparavant comme
installation personnelle ; son historique appartient à cette installation, pas à ce
framework.
