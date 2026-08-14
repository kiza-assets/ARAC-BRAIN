# Dossier de publication — ARAC BRAIN V1

Ce document est celui du mainteneur. Il dit ce que la V1 promet, comment on le
démontre, ce qui reste ouvert, et à quelle condition on publie.

---

## 1. Le critère de sortie

> **Un nouvel utilisateur possédant un Mac, Claude Desktop, Claude Code CLI et un
> serveur Ubuntu peut créer son propre cerveau sans notre aide.**

Ce n'est pas « zéro défaut ». Un défaut qui n'empêche pas cela ne bloque pas la
publication — il est classé, documenté, et publié avec le reste.

## 2. L'échelle de classement

| | | Effet sur la publication |
|---|---|---|
| **P0** | Empêche d'installer ou d'utiliser correctement son cerveau | **Bloque.** Corrigé avant publication. |
| **P1** | Fonctionne, mais l'expérience est dégradée ou l'information trompeuse | Corrigé si le coût est raisonnable. |
| **P2** | Robustesse, sécurité ou élégance | Ne bloque pas. |
| **P3** | Sujet réel, documenté honnêtement | Ne bloque pas. Va dans les limites connues. |

**La question qui tranche, pour chaque constat :** *est-ce que cela empêche
réellement un inconnu d'obtenir son cerveau ?* Si non, ce n'est pas un bloquant.

## 3. Les pièces du dossier

| Pièce | Fichier | État |
|---|---|---|
| README principal | `README.md` | ✅ |
| Guide d'installation | `docs/INSTALLATION.md` · `docs/DEMARRAGE-RAPIDE.md` | ✅ |
| Guide de compréhension | `docs/POURQUOI.md` · `docs/CONCEPTS.md` · les **quatre** `COMMENT-IL-*` · `docs/CE-QUE-ARAC-N-EST-PAS.md` · `docs/MANUEL.md` | ✅ — *ce document en comptait cinq. `ls docs/COMMENT-IL-*.md \| wc -l` → **4**. Le cinquième « comment » du manuel — « Comment apprend-il ? » — est le seul chapitre qui n'a pas son document, et `MANUEL.md:18` le dit ; le compter comme livré était une erreur de ce dossier, pas un fichier manquant.* |
| Bootstrap | `bootstrap/README.md` · `bootstrap/bootstrap.sh` | ✅ |
| Configuration | `docs/CONFIGURATION.md` · `.env.example` · `config/scopes.example.toml` | ✅ |
| Philosophie | `docs/PHILOSOPHIE.md` | ✅ |
| **Limites connues** | [`docs/LIMITES-CONNUES.md`](LIMITES-CONNUES.md) | ✅ intégré le 10 août 2026 — relu affirmation par affirmation, six corrections nommées en §6 |
| **Décisions d'architecture** | [`docs/DECISIONS-ARCHITECTURE.md`](DECISIONS-ARCHITECTURE.md) | ✅ intégré le 10 août 2026 — **renommé** : `docs/DECISIONS.md` est le chemin du registre du LECTEUR, que le cockpit indexe |
| **Critères de validation** | ce document · `tests/acceptance/` | ✅ intégré le 10 août 2026 |
| Exploitation, dépannage, sauvegarde, départ | `docs/EXPLOITATION.md` · `docs/DEPANNAGE.md` · `docs/SAUVEGARDE.md` · `docs/INSTALLATION.md §13` | ✅ |

## 4. Ce que la V1 démontre, et par quoi

**Cette section est un REGISTRE, pas une déclaration.** Chaque promesse ci-dessous
est *censée* être traversée par `make acceptance`, qui installe réellement un
cerveau sur une grappe jetable et se démonte ensuite. Ce que le harnais démontre
**aujourd'hui** n'est pas une propriété du projet : c'est un état, daté, qu'il
faut remesurer à chaque manche. La colonne « État » est donc la seule qui compte,
et elle a le droit de régresser.

> **Cette section a déjà menti par omission**, et c'est pourquoi elle est écrite
> ainsi. Elle a ouvert, une manche entière, sur *« chaque promesse ci-dessous est
> traversée par `make acceptance` »* — au présent, sans réserve — pendant que le
> harnais s'arrêtait à son étape 3 et n'en démontrait qu'**une**. Les huit lignes
> du tableau étaient alors adossées à des étapes qui n'avaient jamais été
> exercées. Un lecteur pressé ne lit que cette page ; elle ne peut pas être la
> seule à ne pas dire l'état réel.

### État du harnais — manche du 10 août 2026, 23:15 UTC

**Rejoué, pas recopié.** `make acceptance` sur ce dépôt, cerveau
`acceptation-5be1a6`, grappe jetable `16/acceptation5be1a6` sur le port **5461**,
ports d'essai **8211** (API) et **8231** (cockpit), banc entièrement démonté par
le juge :

```
  7 prouvée(s) · 2 partielle(s) · 0 non testée(s) · 0 en échec · 0 intervention(s)
  code de sortie : 0
```

**Les neuf étapes, une par une** — c'est le harnais qui les numérote, et il en a
**neuf**, pas huit :

| # | Étape du harnais | État mesuré |
|---|---|---|
| 1 | Cloner le dépôt | ◐ **PARTIEL** — obtenu par copie de `git ls-files`, faute d'un seul commit dans le dépôt source. Le `git clone` du guide n'est donc pas exercé. |
| 2 | Suivre la documentation | ✓ PROUVÉ — 11 étapes annoncées, 26 documents cités présents |
| 3 | Installer ARAC | ✓ PROUVÉ — installation complète **en une commande**, contrôle a posteriori sans échec, API vivante |
| 4 | Créer son cerveau — c'est le SIEN | ✓ PROUVÉ — identité, taxonomie et énumération issues de l'entretien ; cinq rôles sur la grappe d'essai ; **grappe de production intacte** |
| 5 | Synchroniser ses conversations | ✓ PROUVÉ — 16 messages entrés par le vrai pont et la vraie API ; poste inconnu refusé en 403 ; rejeu complet sans doublon |
| 6 | Voir son cerveau apprendre | ◐ **PARTIEL** — prouvé jusqu'à la **frontière de dépense** : matière vue, tranche sélectionnée, cycle exécuté, refus tracé (`skipped / master_switch_env_off`). L'atome par curation, le vecteur réel et le rappel sémantique restent NON TESTÉS. |
| 7 | Utiliser son cockpit | ✓ PROUVÉ — socket appartenant à notre unité, 401 sans session, mot de passe **et** second facteur, métrique concordante avec la base, port muet quand l'unité s'arrête |
| 8 | Prouver sa sauvegarde | ✓ PROUVÉ — l'**unité armée** produit le dump, `ops/restore_verify.sh` le restaure et le compare **sans superutilisateur** ; base voisine et gabarit refusés comme cibles et intacts ; **la bascule du §7 jouée sur un cerveau cassé pour de vrai** (`DROP SCHEMA arac CASCADE`), et le cerveau revient |
| 9 | Désinstaller | ✓ PROUVÉ — les gestes du §13 joués à la lettre ; `ops/uninstall_check.sh` conclut « PROPRE » en code 0 ; ni base, ni rôle, ni octet ne survit — sauf l'adieu, nommé |

**Les promesses de la V1, adossées à ce qui précède :**

| Promesse | Démontrée par | État |
|---|---|---|
| Un inconnu installe seul, sans intervention manuelle | harnais, étapes 2-3 | ✓ **0 intervention** comptée |
| L'installation est reproductible | deux installations, deux taxonomies → schéma identique à l'identité près | ✓ étape 4 |
| Deux cerveaux cohabitent sans se nuire | rôles, comptes, ports, coffres, journaux, sauvegardes croisés | ✓ étapes 4 et 8 (base voisine refusée comme cible et vérifiée intacte) |
| Un cerveau se sauvegarde | l'**unité armée** produit le dump, pas un appel à la main | ✓ étape 8 |
| Une sauvegarde se restaure | restauration réelle, comparée au vivant | ✓ étape 8 |
| On peut tout perdre et tout retrouver | base détruite pour de vrai, procédure de bascule jouée | ✓ étape 8 |
| On peut partir sans rien laisser | désinstallation, puis inventaire de ce qui reste | ✓ étape 9 |
| **Le cerveau APPREND** — une conversation devient un souvenir par la curation | — | ◐ **NON DÉMONTRÉ** — étape 6, frontière de dépense. C'est la seule promesse du produit qu'aucun essai n'a traversée. |
| La documentation dit vrai | gardes qui lisent le code et la doc, et échouent sur divergence | ✓ `make test` **vert**, voir ci-dessous — et la zone aveugle des gardes est déclarée : G1 ne lit ni la prose ni les colonnes d'explication d'un tableau, G4 ne lit pas le Markdown |

### État de `make test` — même manche

```
  5487 passed, 215 skipped, 3 deselected, 5 xfailed, 21 warnings   (137 s)
  code de sortie : 0
```

**Vert, et cette ligne a bougé deux fois dans la même soirée** — ce qui est
exactement pourquoi cette section est un registre. À 22:52 UTC : `4 failed`
(le P0 du pont). À 23:15 : `1 failed`, un test qui comptait deux appels payants
dans le harnais là où il n'y en a plus qu'un. À 23:30 : **`0 failed`**, mesuré
deux fois de suite.

**Et pas dans une seule configuration** — une suite qui n'est verte que là où on
l'a écrite ne prouve rien de ce qu'un inconnu obtiendra :

| Configuration | Résultat |
|---|---|
| le dépôt tel quel, `.venv` en place | `5487 passed, 215 skipped, 3 deselected, 5 xfailed` · **code 0** *(mesuré deux fois)* |
| le dépôt, **sans réseau** — `unshare -n -- bash -c 'ip link set lo up; make test'`, la preuve d'herméticité que le `Makefile` prescrit lui-même | `5487 passed, 215 skipped, 3 deselected, 5 xfailed` · **code 0** |
| un **clone neuf** (arbre recopié, `git init`, `python3 -m venv` et `pip install -r requirements.txt` refaits de zéro) | `5486 passed, 216 skipped, 3 deselected, 5 xfailed` · **code 0** — un `skipped` de plus : le clone n'a aucun commit, et le test concerné se déclare ignoré au lieu de rougir, ce qui est exactement la règle de ce dépôt |
| le **clone neuf, sans réseau** | `5486 passed, 216 skipped, 3 deselected, 5 xfailed` · **code 0** |

Aucune de ces quatre n'a touché une base, un réseau ou une clé : c'est ce qui
autorise l'étape 0 du guide à demander `make test` **avant** toute installation.

Le **P0 de la manche précédente est donc fermé** : `ARAC_CERVEAU_DEMANDE` est
classée, le littéral de port a quitté la ligne imprimée, et la simulation de
l'étape 3 du démarrage rapide passe — le harnais l'a rejouée et a installé pour
de vrai.

### Ce que le harnais ne traverse pas

Nommé dans son propre rapport, et tenu dans
[`docs/LIMITES-CONNUES.md`](LIMITES-CONNUES.md) §2 — qui fait autorité. La liste
courte : **la moitié macOS du pont** (tunnel SSH remplacé par une boucle locale,
`launchd` jamais déclenché, emplacement réel des données de Claude Desktop
jamais lu), **la dépense réelle** (ni atome par curation, ni embedding, ni rappel
sémantique), et **la durée**. Le mode qui doit prouver la dépense réelle
(`make acceptance-complet CLE=…`) **n'est plus cassé** — le corps qu'il postait
et que l'API refusait en 422 est corrigé — mais **il n'a jamais été joué avec une
vraie clé** : réparer ce qu'il envoie ne remplace pas la mesure. Voir §2.2 des
limites connues.

**La production, avant et après.** Le harnais mesure la machine de part et
d'autre de son passage, et le rapport de cette manche conclut : services de
production `active active`, sonde de l'API sur `8000` → `200`, **1 936 souvenirs
en production**, empreinte des rôles du cluster 5432 `7c95f182815537e9` —
inchangée.

## 5. Registre des constats ouverts

*(à tenir à jour à chaque manche. L'état ci-dessous a été **rejoué**, pas recopié,
le 10 août 2026 : chaque ligne fermée porte la commande qui l'a fermée.)*

### Ce que la manche précédente portait, et qui est FERMÉ

| Constat | Comment on le sait |
|---|---|
| **P0** — quatre noms non résolus livrés, dont le kill-switch de l'IA payante | `pytest tests/test_aucun_nom_non_resolu.py` → **1 passed** ; les trois imports sont en place (`app/routers/dashboard.py:50`, `agents/cortex/pack.py:46`, `agents/lib/paid_ai_control.py:28-29`), et `python -c "import agents.lib.paid_ai_control"` charge |
| **P1** — le critère de santé ne prouvait pas ce qu'il annonçait | le `README` §6 porte les **trois lignes** + la quatrième qui exige un serveur ; le garde des noms prouve une négative universelle sur tout le Python livré ; `tests/parcours.py` mesure ce qui a été **emprunté** |
| **P1** — `docs/ROADMAP.md` déclarait la restauration jamais rejouée | elle est jouée **trois fois** par passage de `make acceptance` (restauration par l'unité, comparaison au cerveau vivant, bascule §7.3 après un `DROP SCHEMA arac CASCADE`) |
| **P2** — `CHANGELOG` qui alarmait pour un défaut que son propre lot avait fermé | corrigé à la manche précédente |
| **P1** — le dossier de publication était écrit mais pas raccordé, et six de ses affirmations étaient périmées | relu affirmation par affirmation le 10 août 2026 ; les six corrections sont nommées en §6 de `LIMITES-CONNUES.md` ; le README §9 renvoie aux trois documents |
| **P1** — `docs/DECISIONS.md` occupait le chemin **réservé au lecteur**, que le cockpit indexe : ses décisions à lui s'y affichaient comme les nôtres, et `make test` rougissait sur un clone neuf | renommé en `docs/DECISIONS-ARCHITECTURE.md`, entrées `DA-01…DA-14` ; `pytest tests/test_f1_aucune_trace_de_l_auteur.py` → vert |
| **P1** — `docs/FAQ.md` répondait, à « est-ce que ça marche vraiment ? », que seule la *simulation* du bootstrap avait été vérifiée | réécrit avec ce qui a réellement tourné et ce qui n'a pas tourné ; renvoi à `LIMITES-CONNUES.md` §2 |
| **P1** — six pages enseignaient encore l'ancien critère de santé (« une ligne verte sans `failed` ») | alignées : `DEMARRAGE-RAPIDE` (tableau + étape 0), `INSTALLATION` (point de contrôle 2), `CONTRIBUER`, `GOAL.md` |
| **P1** — le journal des versions ne portait aucune ligne sur le lot des quatre noms non résolus | écrit : `CHANGELOG` `[0.1.13]`, avec le tableau des quatre et ce qu'il faut en retenir |
| **P1** — `mac/README.md` publiait encore le **foyer commun** : la configuration annoncée à la racine de `~/.arac`, et une commande de renvoi complet visant une copie d'`arac-sync.py` à cette même racine — un chemin qui n'existe sur aucune installation d'aujourd'hui, donc « fichier introuvable » | **procédure exécutée**, pas relue : `arac-pont.sh installer` sous un faux foyer pose `~/.arac/<cerveau>/{pont.conf,arac-sync.py,journal/,export-desktop/}` en `0700`, et **refuse en code 2** sans nom (« Sans nom, ce pont s'installerait dans le foyer COMMUN »). La page dit désormais cela, avec l'arborescence relevée. Mêmes corrections dans `COMMENT-IL-SE-SYNCHRONISE.md` (`pont.conf` et le curseur) |
| **P1** — l'étape 9 du démarrage rapide désignait, pour un cycle stérile, une cause (`ARAC_NODE_ID`) que le lecteur n'a statistiquement pas | remplacée par les **huit causes réelles dans l'ordre où le cycle refuse**, chacune avec le code de journal qui la nomme : `master_switch_env_off`, `master_switch_config_off`, `kill_switch_active`, `spawn_failed`, `cortex.duplicate_slot`, `daily_*_exhausted`, file vide, **puis** `ARAC_NODE_ID`. Corroboré par le harnais de cette manche, dont l'étape 6 écrit exactement `skipped / master_switch_env_off`. Mêmes corrections dans `INSTALLATION.md` §10, `DEPANNAGE.md` §5b, `PREMIER-JOUR.md`, `EXPLOITATION.md`, `FAQ.md` |
| **P2** — le dossier comptait « cinq `COMMENT-IL-*` » pour quatre fichiers, et « huit étapes » pour un harnais qui en a neuf | `ls docs/COMMENT-IL-*.md \| wc -l` → **4** ; le rapport du harnais numérote « ÉTAPE n / 9 » et solde 7 + 2 = **9**. Les deux comptes sont corrigés en §3 et §4 |

### P0 — bloquants

**Aucun P0 ouvert à cette manche.** Le seul que ce registre portait est **fermé**,
et il a été **rejoué**, pas déclaré :

| Constat de la manche précédente | Comment on sait qu'il est fermé |
|---|---|
| **Une variable non déclarée arrêtait à la fois `make test` et `make acceptance`.** `mac/arac-pont.sh` lisait `ARAC_CERVEAU_DEMANDE`, déclarée nulle part dans `bootstrap/checks/env_contract.toml` ; le même fichier figeait `8000` dans une ligne imprimée. Mesuré alors : `4 failed`, `bootstrap.sh --dry-run` en code 1, harnais arrêté à l'étape 3, `1 prouvée · 1 partielle · 6 non testée(s) · 1 en échec` | **10 août 2026, 23:15 UTC.** `make test` → `1 failed, 5 486 passed` — et le rouge restant n'a **rien à voir** (voir P1 ci-dessous). `make acceptance` va au bout : **`7 prouvée(s) · 2 partielle(s) · 0 non testée(s) · 0 en échec · 0 intervention(s)`, code 0**, sur la grappe jetable `16/acceptation5be1a6` (port 5461), banc démonté par le juge. L'étape 3 — celle qui échouait — est `✓ PROUVÉ` : « installation complète en une commande, contrôle a posteriori sans échec ». Le littéral `8000` a quitté la ligne imprimée : le texte affiché dit désormais « Aucun défaut, et c'est voulu : un numéro plausible vous brancherait sur le cerveau du voisin » |

*Le solde de ce lot est positif : la réparation du gabarit du pont, qui avait ouvert
ce P0, fermait un défaut plus grave — quatre chemins littéraux `<cerveau>` partagés
par tous les cerveaux d'un poste, c'est-à-dire un curseur et un jeton communs.*

### P1 — importants

| Constat | Mesuré | Décision |
|---|---|---|
| ~~`make test` rouge d'une ligne (`test_le_mode_payant_capture_le_code_http`)~~ **FERMÉ dans la soirée** | vu rouge à 23:15 UTC (`1 failed, 5 486 passed` · `Vus : 1 appels, 1 capturent le code` · `assert (1 >= 2)`), vert à 23:30 : `5 487 passed, 215 skipped, 3 deselected, 5 xfailed`, **code 0**, mesuré deux fois de suite | rien à faire. Noté ici parce qu'un registre qui n'enregistre que les ouvertures n'est pas un registre |
| ~~Le mode qui dépense réellement meurt à sa première dépense (422)~~ **FERMÉ** | le corps posté par `_etape_6_mode_complet` porte désormais `kind: 'decision'` / `confidence: 'producer'`, et capture son code HTTP. `grep -n "'kind'" tests/acceptance/acceptance.sh` → aucune occurrence de `'fact'` ni de `'high'` | reste ouvert **le fait que ce mode n'a jamais été joué avec une vraie clé** : réparer ce qu'il envoie ne remplace pas la mesure. Suivi en `LIMITES-CONNUES.md` §2.2 |
| **La curation exigeait un binaire que rien ne vérifiait et que la documentation ne nommait jamais** — l'étape 8 faisait acheter une clé d'API pour une fonction qui n'appelle aucune API | corrigé côté code (résolution `ARAC_CLAUDE_BIN` → `PATH` → `/usr/bin/claude` ; constat à l'étape 1 ; contrôle final §7 sous le compte d'agent). **Rejoué le 10 août 2026** : `./bootstrap/bootstrap.sh --check` → `✓ claude (Claude Code CLI) … 2.1.226` + `✓ son authentification — session d'abonnement`, verdict `✓ Tout est là. Votre serveur peut porter un cerveau — et le digérer.` ; et avec `ARAC_CLAUDE_BIN=/nowhere/claude` → `⚠ ABSENT`, geste `npm`, verdict `✓ Le serveur peut porter un cerveau. ⚠ Mais PAS le faire apprendre` | **côté documentation : FERMÉ à cette manche.** README §4 et §5, `DEMARRAGE-RAPIDE` (prérequis + étape 1), `INSTALLATION` §1 et étape 8, `FAQ`, `bootstrap/README` §1 et §2 disent désormais ce qu'il faut **posséder**, ce qu'il faut **acheter**, et ce que chaque chose paie |
| **Deux prérequis restent non vérifiés** : `npm` (dont dépend le remède que l'étape 1 prescrit) et l'espace disque | `grep -n "npm\|df -" bootstrap/lib/prereqs.sh` → une seule occurrence de `npm`, dans la commande imprimée ; aucune mesure d'espace | ne bloque pas — documenté en `LIMITES-CONNUES.md` §4.1, avec le geste manquant |
| `tests/test_aucun_nom_non_resolu.py:54` confie sa zone aveugle à `tests/test_parcours_des_chemins_livres.py`, **qui n'existe pas** — le fichier réel est `tests/parcours.py` | `ls tests/ \| grep parcours` → `parcours.py` ; `grep -rn test_parcours_des_chemins_livres .` → une seule occurrence, la citation elle-même | corriger la notice du garde. Aucune page de documentation ne cite ce nom : **la doc est saine**, c'est le fichier de test qui se trompe |

### P2 — robustesse, sécurité, élégance

| Constat | Décision |
|---|---|
| L'inventaire hors paquet du garde des noms est une liste de dossiers écrite à la main, alors que sa notice promet un inventaire qui grandit tout seul | ne bloque pas ; à reprendre quand le garde sera retouché |
| Un seul nom de cookie de session pour tous les cockpits d'une machine (les ports ne cloisonnent pas les cookies) | ne bloque pas — deux cockpits ouverts simultanément dans le même navigateur se déconnectent l'un l'autre, rien de plus |
| `config/projects.toml` n'est nommé ni par le §13 ni par le contrôle de départ, alors qu'il porte vos intentions en clair | ne bloque pas ; à ajouter aux six objets effacés |

### P3 — dette assumée

| Constat | Où c'est documenté |
|---|---|
| Bac à sable de la suite de tests : couverture partielle en régime sans `Landlock` (entrée standard, quotage ANSI-C, chemin composé, corps mis dans un fichier) | `LIMITES-CONNUES.md` §3.2, avec le modèle de menace. *(L'argv des primitives `os.*` et la valeur collée à une option courte, que ce registre listait, sont **fermées**.)* |
| `systemd` ne sait pas purger le journal d'une seule unité | `LIMITES-CONNUES.md` §3.1 |
| Sauvegarde hors site et canal d'alerte livrés en gabarits | `LIMITES-CONNUES.md` §3.4 |
| Deux vocabulaires de sauvegarde coexistent | `LIMITES-CONNUES.md` §3.5 |
| Résidus de l'origine du dépôt dans les commentaires et quelques valeurs par défaut | `LIMITES-CONNUES.md` §3.6 |
| Aucune détection de contradiction ; aucune vérification de péremption | `LIMITES-CONNUES.md` §1.1, §1.5 · `DECISIONS-ARCHITECTURE.md` §« ce que nous n'avons pas décidé » |
| La moitié macOS du pont n'a jamais été exécutée | `LIMITES-CONNUES.md` §2.1 |

**Règle de tenue :** un constat P3 ne se corrige pas — il se **documente**. S'il
n'est écrit nulle part dans les limites connues, il n'est pas P3 : il est P2 non
traité. C'est pourquoi la colonne de droite de ce tableau ne contient que des
renvois : si l'un d'eux tombe dans le vide, la ligne est à reclasser.

## 6. Ce qui reste avant publication

1. ~~Fermer le P0 et les deux P1.~~ **Fait** — voir le registre ci-dessus.
2. ~~Intégrer les trois documents manquants dans `docs/`, et les référencer depuis
   le README.~~ **Fait le 10 août 2026.** Les trois sont relus, corrigés,
   raccordés, et le README §9 les nomme.
3. ~~**Rendre `make test` vert sur un clone neuf.**~~ **Fait le 10 août 2026 à
   23:30 UTC** — et c'est la ligne de cette liste qui touchait le premier geste
   d'un inconnu.

   ```
   5487 passed, 215 skipped, 3 deselected, 5 xfailed, 21 warnings   (137 s)
   code de sortie : 0
   ```

   Les quatre échecs de la manche précédente — tous issus de `mac/arac-pont.sh` —
   sont fermés (voir le P0 clos au registre), et le cinquième, apparu puis refermé
   dans la même soirée, portait sur le harnais et non sur le produit. **La suite
   reste hermétique** : elle ne touche ni base, ni réseau, ni clé, ce qui est ce
   qui autorise un inconnu à la lancer avant d'avoir rien installé.

4. **Une démonstration finale de bout en bout**, par un agent qui n'a jamais lu
   le dépôt : clone, installation, conversations ingérées, souvenirs produits,
   domaines et projets alimentés, cockpit vivant. C'est le critère de sortie, et
   c'est la seule preuve qui compte.
5. **Un premier commit git.** Le dépôt n'en a toujours aucun — `git log` répond
   « does not have any commits yet », vérifié le 10 août 2026 — et le harnais
   fabrique son propre dépôt pour éprouver l'étape du clone. Tant qu'il n'y a pas
   d'historique, « votre ami clone le dépôt » reste simulé. *Décision de l'auteur.*

## 7. Ce que nous ne ferons pas pour la V1

- Poursuivre la course du bac à sable : elle est bornée, déclarée, et sans effet
  sur un cerveau installé.
- Corriger les limites de la section 1 des limites connues : ce sont des choix de
  produit, pas des défauts.
- Attendre qu'un audit ne trouve plus rien. Chaque manche ajoute du code, donc de
  la matière neuve à auditer. Le point d'arrêt est le critère de sortie, pas
  l'épuisement des juges.
