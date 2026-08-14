# Les critères de validation — le premier cerveau d'un inconnu

Ce document dit **à quelle condition ARAC BRAIN est considéré comme terminé**. Ce
n'est pas une feuille de route (voir `docs/ROADMAP.md`) ni un registre de défauts
(voir `docs/RELEASE-V1.md`) : ce sont les huit assertions qu'une version doit tenir
pour être publiée, et la manière dont chacune se vérifie.

Il est né d'un basculement : ARAC a cessé d'être le cerveau d'une personne pour
devenir la machine qui permet à n'importe qui de créer le sien.

> À chaque décision, une seule question :
> **« Si quelqu'un clone ce dépôt aujourd'hui, pourra-t-il créer son propre cerveau
> sans connaître l'auteur ? »**
> Si la réponse est non, le framework n'est pas terminé.

---

## CONDITION D'ACHÈVEMENT (booléenne, vérifiable)

Le framework est terminé quand **un nouvel utilisateur** — muni d'un Mac, de Claude
Desktop, de Claude Code CLI et d'un serveur Ubuntu — **suit la documentation et obtient
un cerveau opérationnel, de façon reproductible**.

> **« Claude Code CLI » figure deux fois dans cette phrase, et ce ne sont pas les mêmes.**
> Sur **le Mac**, c'est la seule source que le pont capte **automatiquement**
> (`~/.claude/projects/**/*.jsonl`) — et l'utilisateur peut s'en passer, au prix de
> l'export manuel de Claude Desktop. Sur **le serveur**, c'est le **binaire que le cycle
> de digestion lance en sous-processus** : sans lui, le cerveau naît, ingère, se laisse
> interroger — et **n'apprend jamais rien**. La curation n'appelle aucune API ; ce n'est
> donc pas une clé d'API qu'il faut acheter pour digérer, c'est ce binaire qu'il faut
> installer, et l'authentifier sous le compte d'agent. Le tableau complet — ce qu'il faut
> posséder, ce qu'il faut acheter, ce que chaque chose paie, et ce que le bootstrap
> vérifie ou non — est en [README §5](README.md#5-ce-quil-vous-faut-et-ce-que-vous-naurez-pas).

| # | Assertion | Vérification | Seuil |
|---|---|---|---|
| **F1** | **Aucune trace de l'auteur.** Ni son nom, ni sa société, ni son village, ni ses proches, ni ses chemins, ni son `node_id` — sauf dans un exemple explicitement désigné comme le sien et marqué « ne copiez pas ». | balayage du dépôt | **0 occurrence non désignée** |
| **F2** | **Le cerveau est celui de l'utilisateur.** Sa taxonomie, ses scopes, son identité, son poste source sont issus de SES réponses, et engendrent l'énumération, le schéma, les seeds et la configuration. | entretien → artefacts générés | **0 valeur héritée** |
| **F3** | **Le bootstrap enseigne.** Chaque étape dit pourquoi elle existe, ce qu'elle construit, et comment cela influencera le cerveau. | relecture pédagogique | **chaque étape porte les 3** |
| **F4** | **L'installation est reproductible.** Depuis un Ubuntu nu : prérequis → base → rôles → migrations → secrets → taxonomie → services → cockpit → première synchronisation. | rejeu complet, deux fois | **2 succès identiques** |
| **F5** | **La chaîne est expliquée de bout en bout.** Claude Desktop → conversations locales → synchronisation → tunnel SSH → serveur → ingestion → embeddings → extraction → atomes → graphes → mémoire → cockpit → Claude Code. | lecture de la doc | **aucun maillon non expliqué** |
| **F6** | **La documentation enseigne, elle n'instruit pas.** Un lecteur comprend ce qu'est un atome, pourquoi une conversation devient un vecteur, comment naît un graphe, comment fonctionne le rappel, et pourquoi ARAC augmente Claude au lieu de le remplacer. | relecture | **les 5 notions acquises** |
| **F7** | **Rien n'est caché.** Prérequis, dépendances externes, coûts d'exploitation, limites connues, ce qui ne marche pas encore : tout est en première page, pas en annexe. | relecture | **déclaré avant l'installation** |
| **F8** | **L'inconnu réussit seul.** Un agent qui ne connaît rien au projet installe en suivant la seule documentation, et note chaque friction. | test d'installation à l'aveugle | **0 blocage exigeant l'auteur** |

---

## CE QUE L'UTILISATEUR DOIT POSSÉDER À LA FIN

son cerveau · son serveur · sa taxonomie · ses scopes · son tunnel SSH · ses services ·
son ingestion · son cockpit · ses sauvegardes · ses tests · son monitoring.

---

## PRINCIPES DE CONSTRUCTION

**Le bootstrap est la première rencontre.** Elle doit être mémorable. L'utilisateur doit
avoir le sentiment de donner naissance à quelque chose, pas de remplir un formulaire.

**Décider et exécuter sont séparés.** L'entretien produit une *description* du cerveau.
L'installation lui donne corps, en annonçant ce qu'elle s'apprête à faire.

**L'expérience de l'auteur devient le manuel.** Ses erreurs sont les leçons : près d'un
souvenir actif sur onze perdu sur une racine (le compte du jour est au § 3 de
[`docs/COMMENT-IL-CREE-SES-SCOPES.md`](docs/COMMENT-IL-CREE-SES-SCOPES.md), seul endroit
du dépôt qui le porte), 76 % de provenance effacée, 36 % de cycles jetés. Un utilisateur
prévenu ne refera pas ces fautes. Les chiffres sont cités comme des mesures, jamais comme
des menaces.

**Le coût est annoncé.** Embeddings et curation sont des dépenses récurrentes. Un framework
qui cache son coût d'exploitation n'est pas honnête.

---

## ÉTAT

**Comment lire ce tableau.** ✅ = écrit **et** exercé ici, avec la commande qui le
montre. ◐ = écrit, mais jamais exercé dans les conditions qui compteraient vraiment.
⬜ = pas fait. Rien n'est coché sur la seule foi que le fichier existe : un tableau
d'état qui ment sur l'avancement décourage exactement le contributeur dont F8 a besoin.
**Et une méthode qui ne peut pas échouer ne coche rien** : « le fichier existe » n'est
pas une vérification, c'est un constat de présence. Chaque ligne ci-dessous porte donc une
commande qu'on peut jouer et qui peut rendre le contraire de ce qu'on attend.
*Relu, et chaque méthode rejouée, le 8 août 2026. Rejouées de nouveau le **9 août 2026**,
une par une, sur un clone neuf et sur un cerveau installé pour l'occasion : entretien,
générateur de taxonomie (les six refus et le témoin), `bootstrap.sh` complet et son
`--dry-run`, `arac_runtime.home()` avec et sans `ARAC_HOME`, les neuf familles de
`verify_install.sh --simulation`, `make test`, `pytest tests/test_monitor.py`,
`ops/lint_shell.sh`, `health_check.py --json`, `pytest tests/test_la_doc_dit_vrai.py`,
`pytest tests/test_l_import_n_ecrit_rien_sur_le_disque.py`. Les deux lignes qui reposent
sur le cerveau de **référence** — la vie du cerveau, le reçu de cycle — n'ont **pas** été
rejouées ce jour-là : elles portent leur date du 8 août, et c'est ce qu'il faut lire.*

| Pièce | État | Comment le vérifier |
|---|---|---|
| Assistant d'entretien (`bootstrap/wizard.py`) | ✅ | cinq questions de fond (prénom, nom du cerveau, identifiant du poste, domaines, rangements) ; `python3 bootstrap/wizard.py --check` rend son bilan de prérequis. **Aucun test automatisé ne le couvre** — c'est un manque connu |
| Générateur de taxonomie (`bootstrap/generate_scopes.py`) | ✅ | **rejoué le 9 août 2026** sur six taxonomies invalides écrites pour l'occasion — aucune racine · racine sans feuille · majuscule dans une clé · espace dans une clé · feuille orpheline · chemin en double : **6 refus sur 6**, code de sortie `2`, et **chaque message nomme le défaut exact** — « Aucune racine déclarée », « Aucune feuille déclarée », « clé 'Travail' invalide », « clé 'tra vail' invalide », « racine 'inconnu' inconnue », « chemin 'travail/strategie' déclaré deux fois ». *(Cette case a annoncé « six messages différents » : ils sont cinq formes, la majuscule et l'espace partageant le message de forme de clé — qui cite tout de même la clé fautive. Une case qui compte est une case qui périme.)* La méthode compte un **témoin** : une septième taxonomie, valide, qui n'est **pas** refusée — sans lui, six refus ne prouveraient rien d'autre que le refus de tout. `generate_scopes.py --config <fichier> --check` n'écrit rien et suffit à le rejouer. **Aucun test automatisé ne le couvre** non plus |
| `bootstrap.sh` complet | ✅ | 11 étapes (`bootstrap/lib/*.sh`), **rejouées deux fois en réel** depuis une base absolument vide, avec deux taxonomies différentes : base, rôles **nommés d'après le cerveau** et portant leur plaque de propriété, `CREATE EXTENSION vector`, `alembic upgrade head`, secrets, unités systemd, contrôle a posteriori sans un échec. `./bootstrap/bootstrap.sh --dry-run` va jusqu'au bilan sans rien écrire |
| Extraction du moteur et du cockpit, chemins paramétrés | ✅ | le paramétrage **s'éprouve**, il ne se constate pas : `python3 -c "import arac_runtime as r; print(r.home())"` rend le dépôt, et la même commande précédée de `ARAC_HOME=/tmp/ailleurs` rend `/tmp/ailleurs` — il n'y a donc aucun chemin absolu figé. Doublé d'un garde de forme : `tests/test_l_import_n_ecrit_rien_sur_le_disque.py` échoue si un module d'application fabrique quoi que ce soit **à l'import** |
| Contrôle d'installation (`bootstrap/checks/verify_install.sh`) | ✅ | **neuf** familles, numérotées 0 à 8 — et ce n'est pas ce tableau qui les compte : `./bootstrap/checks/verify_install.sh --simulation` les annonce lui-même, sans rien exiger d'installé, et joue pour de vrai la famille 0 (`.env.example` contre le code). La famille 3 comporte une **écriture réelle qui doit échouer**. Le nombre de *verdicts*, lui, n'est écrit nulle part : il dépend de l'installation |
| Pont Mac ↔ serveur | ◐ écrit, jamais exercé sur un Mac | `mac/` (6 fichiers) ; validé sur Linux contre un serveur simulé — `launchctl`, `plutil`, l'emplacement réel des données de Claude Desktop restent non vérifiés |
| Tests | ✅ | `make test`. **L'herméticité n'est plus une promesse écrite, c'est un garde** : `tests/garde_hermetique.py` coupe le réseau et les commandes machine pendant la suite, et refuse toute base qui n'appartient pas au test lui-même — la question n'est plus « est-ce la base de l'auteur ? » mais « cette base m'appartient-elle ? ». **Le compte exact n'est un critère nulle part** — il monte à chaque correctif. **Et l'absence de `failed` n'est plus le critère à elle seule** : elle a été obtenue par une livraison qui servait deux routes en 500 et dont le kill-switch de l'IA payante mourait à l'import. Le critère est désormais à trois lignes — le garde des noms (`tests/test_aucun_nom_non_resolu.py`, qui prouve une **négative universelle** sur tout le Python livré), le bloc « ce que cette session a réellement emprunté » (`tests/parcours.py`, qui **mesure** au lieu de rougir), puis la ligne pytest sans `failed`. La quatrième, `sudo make acceptance`, exige un serveur. Le raisonnement fait autorité en [première page du `README`](README.md#6-le-chemin-le-plus-court-vers-un-cerveau-qui-vit) |
| Monitoring | ✅ | `scripts/ops/health_check.py` (lit le registre de métriques du cockpit), `scripts/ops/alerts.py`, `ops/watchdog.sh` — **exercés**, pas seulement présents : `pytest tests/test_monitor.py` et `./ops/lint_shell.sh`. `health_check.py --json` rend un verdict machine sans rien écrire |
| Sauvegardes | ✅ produites, restaurées, **et la bascule jouée** | Il n'existe plus qu'**une** implémentation de la sauvegarde, et c'est l'unité qui l'appelle : `systemctl cat arac-<base>-sauvegarde.service \| grep ExecStart` → `ops/backup.sh`. Le cycle entier est rejoué à chaque `make acceptance`, étape 8 : l'unité produit un dump, `ops/restore_verify.sh` le **restaure** dans une base jetable et le compare (« VERDICT : PROUVÉ »), puis la **bascule du §7** est jouée sur un cerveau **cassé pour de vrai** (`DROP SCHEMA arac CASCADE`) — restauration dans une base neuve, renommage, `bootstrap.sh --only migrations`, et les souvenirs sont relus **sous le rôle de l'application**, pas sous le superutilisateur. Rejouée à la main, ligne par ligne, le 9 août 2026 sur un cerveau né du chemin réel. **Ce qui reste non joué** : le chemin *chiffré* (§7 étape 2, `age -d`) et la copie hors site — l'un et l'autre demandent une clé et une seconde machine que ces essais n'avaient pas |
| **La vie du cerveau** — ingestion, embeddings, rappel sur un vrai corpus | ◐ éprouvée sur **un seul** corpus | **La chaîne complète tourne, et elle laisse une trace citable.** Sur le cerveau de référence : `SELECT status, items, atoms_created, atoms_quarantined, coverage_presented, coverage_covered, coverage_no_new_knowledge, coverage_omitted FROM arac.run_receipts WHERE started_at >= '2026-08-08 13:14' ORDER BY started_at LIMIT 1` — ce reçu rend 12 conversations présentées = 8 couvertes + 3 sans rien à retenir + 1 omise, 7 atomes créés, **1 candidat d'atome mis en quarantaine** — `atoms_quarantined` compte des candidats écartés à la disposition (`agents/cortex/dispose.py`), pas des cycles : un cycle en quarantaine, lui, porte `status = 'quarantined'`, et ce reçu-ci est `done` ; et `SELECT count(*) FROM arac.memory_atoms WHERE status='active' AND embedding IS NULL` rend **0**. *(Ce reçu est désigné par sa DATE. La même ligne disait `ORDER BY started_at DESC LIMIT 1` — « le dernier » — et rejouée le soir même elle rendait un tout autre reçu, en quarantaine, tout à zéro : une méthode qui désigne « le dernier » ne prouve rien d'un cycle précis.)* **Ce qui manque** : ce corpus est celui de l'auteur, et lui seul. Les cerveaux posés par le bootstrap portent, eux, zéro conversation et zéro atome — la digestion exige le **binaire de curation** sur le serveur, son authentification sous le compte d'agent, et les **deux interrupteurs de dépense** ouverts — qu'aucun essai gratuit et reproductible n'arme. Le chemin *installation neuve → première conversation → premier atome* n'a donc jamais été parcouru d'un bout à l'autre |
| Documentation pédagogique | ✅ | `docs/POURQUOI.md` (les sept marches), `CONCEPTS`, `PHILOSOPHIE`, `CE-QUE-ARAC-N-EST-PAS`, `GLOSSAIRE`, `PREMIER-JOUR`, `PREMIER-MOIS`. **Ce qui est exercé, ce n'est pas leur présence** : `make acceptance` rend un verdict sur F3, F5, F6 et F7 en jouant le parcours, et `pytest tests/test_la_doc_dit_vrai.py` refuse mécaniquement une page qui promet un geste que le code ne sert pas |
| Documentation opératoire | ✅ | `INSTALLATION`, `DEMARRAGE-RAPIDE`, `CONFIGURATION`, `EXPLOITATION`, `SAUVEGARDE`, `DEPANNAGE`, `PONT-MAC`, `ARCHITECTURE`, `ROADMAP`, `FAQ`. **Exercée** par `pytest tests/test_la_doc_dit_vrai.py`, qui balaie tout ce que `git` transporte — Markdown **et** commentaires du code — et fait échouer la suite sur un document qui déclare versionné un fichier ignoré, qui dit « jamais » d'une commande exécutée, ou qui donne un rang dans la chaîne Alembic |
| **F4** — installation rejouée deux fois sur un Ubuntu nu | ◐ | **la reproductibilité est acquise** : deux installations complètes depuis une base vide, avec deux taxonomies différentes, rendent le **même schéma** : `pg_dump --schema-only` identique une fois neutralisée, des deux côtés, l'**identité** que le bootstrap grave exprès dans le commentaire du schéma (`cerveau=`, `empreinte=`, `poste=`) et que `pg_dump` emporte — c'est cette identité, et elle seule, qui doit différer. Le critère est cette égalité-là, pas un compte d'objets qui périmerait à la migration suivante, ni un filtre appris par cœur sur la ligne du moment qui périmerait à la prochaine amélioration. Commande en deux temps au §7c du `README`. **Ce qui manque encore** : l'Ubuntu était *nu* au sens du dépôt mais pas de la machine — PostgreSQL 16 et pgvector y étaient déjà, alors que le bootstrap n'installe aucun paquet, il les nomme. Les **saisies interactives**, elles, ont été faites depuis, le **9 août 2026**, derrière un vrai pseudo-terminal : mot de passe du cockpit tapé deux fois aux invites `getpass`, URI TOTP affichée une seule fois, puis `POST /cc/login` avec ce mot de passe et un code à six chiffres calculé depuis le secret appairé → `303` vers `/cc/`, session posée, `/cc/v1/atoms` à `200`, mot de passe faux à `401`. Ce qui reste non joué à la main, c'est l'installation **complète** en interactif de bout en bout : seule l'étape des secrets l'a été |
| **F8** — test d'installation à l'aveugle réussi | ⬜ | **la dernière chose qui manque** — voir `README.md` §7 |

Les limites connues du système lui-même — les trois relations mécaniques de la couche de
liens, l'absence de détection de contradictions, la vérification non alimentée — ne sont
pas dans ce tableau. Elles sont **tenues**, avec la commande qui rejoue chacune, dans
[`docs/LIMITES-CONNUES.md`](docs/LIMITES-CONNUES.md), qui fait autorité ; la première page
du [`README`](README.md), §7, en est la porte d'entrée, et
[`docs/ROADMAP.md`](docs/ROADMAP.md) en tire les conséquences pour la suite.

**Pourquoi elles ne sont pas ici.** Ce tableau mesure l'avancement d'un mandat ; ce
document-là mesure ce que le produit ne sait pas faire. Les mélanger ferait disparaître
une limite assumée le jour où le mandat serait rempli — or elle serait toujours là.
