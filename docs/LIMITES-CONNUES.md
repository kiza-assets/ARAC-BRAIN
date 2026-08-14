# Limites connues

Ce document existe parce qu'un framework qui cache ses limites vous les fait
découvrir au pire moment. Tout ce qui suit est **mesuré**, pas supposé — chaque
entrée porte sa date, la commande qui la rejoue, et le critère qui restera vrai
quand le chiffre aura changé.

Rien ici n'empêche d'installer ARAC et de s'en servir tous les jours. Lisez
quand même : deux ou trois de ces limites décideront peut-être pour vous.

> **C'est ici, et nulle part ailleurs, qu'une limite assumée vit.** Le dépôt
> s'est donné une règle : un seul endroit fait autorité, les autres y renvoient.
> Une page qui dit « non couvert », « non vérifié » ou « connu et non résolu »
> doit donc renvoyer à ce document plutôt que le recopier — une limite écrite à
> deux endroits est une limite qui sera corrigée à un seul.
>
> Les deux voisins de cette page : [`docs/DECISIONS-ARCHITECTURE.md`](DECISIONS-ARCHITECTURE.md)
> dit **pourquoi** le produit est fait ainsi et ce que chaque choix coûte ;
> [`docs/RELEASE-V1.md`](RELEASE-V1.md) tient le registre des constats ouverts et
> la règle qui décide de ce qui bloque une publication.

*Relu et rejoué affirmation par affirmation le **10 août 2026**. Les corrections
de cette relecture sont nommées à la fin, en §6.*

---

## 1. Ce que le cerveau ne sait pas encore faire

### 1.1 Il relie les souvenirs par trois mécaniques, et aucune ne comprend

`arac.atom_links` existe et **est alimentée** : le cycle la recalcule à chaque
passage, et elle porte **trois** relations, pas une. La première rédaction de ce
paragraphe n'en annonçait qu'une, et son critère de rejeu aurait donc rougi au
premier cerveau vivant :

| Relation | Ce qu'elle veut dire | Comment elle naît |
|---|---|---|
| `supersedes` | ce souvenir en **remplace** un autre | lue dans la colonne `superseded_by` — zéro jugement |
| `same_thread` | ces souvenirs viennent de la **même conversation** | chaîne chronologique dans un groupe de provenance |
| `semantic_neighbor` | ces deux souvenirs se **ressemblent** | voisinage réciproque des vecteurs, six voisins au plus, distance ≤ 0,25 |

Les deux premières sont mécaniques : elles se déduisent d'une colonne, elles ne
peuvent pas se tromper. La troisième est **inférée** — elle a un seuil, donc elle
a des faux positifs.

Ce que le cerveau **ne fait pas** : aucun mécanisme ne détecte qu'un souvenir en
**contredit** un autre, ni qu'il le **confirme**. `supersedes` dit « celui-ci a
été remplacé », parce que quelqu'un l'a explicitement remplacé — pas « ceci
invalide cela », que personne n'a déclaré. Un graphe de connaissances au sens
fort n'existe pas. Deux genres de souvenirs s'appellent pourtant `contradiction`
et `validation` : ils existent pour que **vous** puissiez en écrire, jamais parce
que le cerveau en produirait.

Conséquence pratique : deux décisions opposées prises à six mois d'écart
cohabiteront sans que personne vous prévienne. Le rappel vous rendra les deux, et
c'est vous qui trancherez.

```
Rejouer :  psql "$DATABASE_URL_READONLY" -c \
           "SELECT relation_type, count(*) FROM arac.atom_links GROUP BY 1"
Critère :  au plus les TROIS familles du tableau ci-dessus. Le jour où une
           QUATRIÈME apparaît, cette limite a bougé — et c'est ce document
           qui a tort, pas votre installation.
Lire :     `app/services/atom_links.py`, qui porte les trois requêtes et les
           deux constantes calibrées (K=6, θ=0,25).
```

> La pédagogie de cette limite — pourquoi « voisin » n'est pas « lié », et
> pourquoi c'est le malentendu le plus coûteux qu'on puisse avoir sur ARAC — est
> en première page du [`README`](../README.md#7-ce-qui-ne-marche-pas-encore--honnêtement),
> §7a. Elle n'est pas recopiée ici.

### 1.2 La confiance ne change pas ce que vous retrouvez

Chaque souvenir porte un score de confiance. **Il n'entre pas dans le calcul du
rappel.** Deux souvenirs au texte identique, l'un noté 95 et l'autre 10,
remontent exactement à la même place — mesuré, à la distance près.

Le score sert au tri manuel et à un seul automatisme, décrit en 1.3.

Un module qui **pondérerait** le rappel par la confiance existe bien dans le
dépôt — `app/services/context_router.py`, où le score pèse pour un demi-point
contre deux points de correspondance de mots. La première rédaction de ce
paragraphe disait qu'il était « derrière deux drapeaux que l'installation ne pose
pas ». C'est plus faux que vrai, et dans le sens dangereux : **aucun drapeau ne
l'ouvre**, parce qu'aucune route servie ne l'importe. Seul un test le charge. Il
n'y a donc pas un réglage à trouver — il n'y a pas de chemin.

```
Rejouer :  grep -rn "context_router" app/ agents/ control_center/ --include=*.py \
           | grep -v "^app/services/context_router.py"
Critère :  aucune ligne d'appel (les mentions en commentaire ne comptent pas).
           Le jour où un routeur l'importe, cette limite a bougé.
```

Ne cherchez donc pas le réglage qui ferait « remonter » un bon souvenir : il n'y
en a pas. Ce qui fait remonter un souvenir, c'est la ressemblance de sens entre
votre question et son texte.

### 1.3 Un souvenir peut être archivé à sa naissance, en silence

Un souvenir **proposé par un agent** (et non produit par le cycle nominal) naît
archivé si son score de confiance est inférieur à 70. Le seuil est appliqué **à
l'insertion seulement** : baisser le score d'un souvenir déjà vivant ne l'archive
pas.

Le piège, et il coûte cher : **une supersession qui ne dit rien du score hérite
celui de l'ancien souvenir.** Si vous corrigez un souvenir d'agent noté 30, le
nouveau naît archivé, l'ancien passe en « remplacé », et **plus aucun souvenir
vivant ne reste sur ce sujet**. Le rappel ne rend plus rien.

Le produit vous avertit désormais (`W-008`) quand un souvenir naît dans un état
différent de celui demandé. **Lisez cet avertissement** : c'est le seul signe.

```
Rejouer :  poser un souvenir agent_suggest à 30, le superséder sans donner
           new_confidence_score, puis interroger le rappel sur son domaine.
Critère :  la réponse doit porter W-008. Si elle ne le porte pas, signalez-le.
```

### 1.4 Un souvenir posé sur une racine devient orphelin

Votre taxonomie a deux niveaux : des racines (`travail`) et des feuilles
(`travail/finance`). **Les souvenirs vivent sur les feuilles.**

Un souvenir posé directement sur une racine reste en base et peut encore remonter
par pure ressemblance — mais il est exclu de tout ce que le cerveau construit
au-dessus du rangement : pas d'état courant, pas de place dans la vue des
domaines, pas de comptage dans la couverture. Et une recherche qui **précise** un
domaine ne le trouvera jamais : l'égalité de domaine est stricte, demander
`travail/finance` ne rend pas un souvenir rangé sur `travail`.

C'est le piège le plus coûteux du système. Sur le cerveau de référence suivi huit
mois, près d'un souvenir actif sur onze est tombé dedans et n'en est jamais
ressorti de lui-même. *(Le compte exact du jour et la requête qui le rend sont au
§ 3 de [`docs/COMMENT-IL-CREE-SES-SCOPES.md`](COMMENT-IL-CREE-SES-SCOPES.md), seul
endroit du dépôt qui les porte — partout ailleurs, la fraction seule.)*

```
Rejouer :  psql "$DATABASE_URL_READONLY" -c \
           "SELECT count(*) FILTER (WHERE position('/' in scope) = 0) AS sur_racine,
                   count(*) AS actifs
            FROM arac.memory_atoms WHERE status = 'active'"
Critère :  `sur_racine` doit valoir 0 sur un cerveau qu'on tient bien. Ce n'est
           pas une panne s'il ne vaut pas 0 : c'est le piège, et il est à vous
           de le défaire (le geste est dans `docs/DEPANNAGE.md`).
```

### 1.5 Rien ne vérifie qu'un savoir est encore vrai

Les colonnes qui porteraient une date de dernière vérification ou une date de
péremption existent dans le schéma. **Aucun mécanisme ne les alimente.** Un
souvenir écrit il y a huit mois vous sera rendu avec la même assurance qu'un
souvenir d'hier.

Le cockpit affiche cette indisponibilité au lieu d'afficher un zéro rassurant.

### 1.6 Le cockpit ne sert qu'à regarder

Le cockpit n'a **aucune route d'écriture**, à une exception près : la page de
connexion. Vous ne pouvez y valider, corriger, trancher ni supprimer quoi que ce
soit. Toute modification passe par l'API.

Ce n'est pas un oubli : c'est le choix de garder un observatoire qui ne peut pas
abîmer ce qu'il observe (voir [`docs/DECISIONS-ARCHITECTURE.md`](DECISIONS-ARCHITECTURE.md), DA-08).

---

## 2. Ce qui n'a jamais été éprouvé de bout en bout

Cette section est la plus importante du document, et la plus inconfortable à
écrire. Elle sépare **ce que le dépôt prouve** de **ce qu'il affirme**.

### 2.1 Le pont depuis un vrai Mac

La première rédaction de ce paragraphe disait que le pont « n'a jamais tourné
dans les épreuves du dépôt ». C'était trop dur, et une alarme trop dure coûte
autant qu'une promesse creuse. Voici la coupure exacte.

Ce qui **a réellement tourné**, sur Linux, contre deux cerveaux vivants installés
par le vrai chemin : les deux moitiés du pont — `mac/arac-pont.sh` et
`mac/arac-sync.py` — dans deux foyers séparés, jusqu'à l'ingestion effective
d'une conversation témoin par `POST /v1/ingest/messages`. Sont également prouvés :
le refus d'un poste non déclaré, le curseur qui ne rejoue pas deux fois la même
conversation, l'ingestion de conversations au format réel de Claude Desktop et de
Claude Code CLI, et la configuration `sshd` du tunnel, livrée.

Ce qui **n'a jamais tourné** : rien de ce qui est propre à macOS. `launchd` et
`launchctl`, `plutil`, l'emplacement réel des données de Claude Desktop, un
tunnel SSH ouvert depuis un poste réel, et l'export que Claude Desktop produit
sur votre machine. Aucun agent de ce dépôt n'a de Mac : la moitié macOS du pont
est **écrite et relue, jamais exécutée**.

**C'est le maillon que vous éprouverez le premier**, et c'est là que nous
attendons vos retours en priorité.

Le partage exact — quel test *lit* le pont, lequel l'*exécute*, et les deux
commandes qui le recalculent au lieu de le réciter — est au **§12 de
[`docs/PONT-MAC.md`](PONT-MAC.md)**. C'est là qu'il est tenu ; il n'est pas
recopié ici, parce qu'un inventaire recopié se périme au premier fichier ajouté.

### 2.2 Le cycle payant, en dépense réelle — et le mode qui devait le prouver est cassé

Le harnais d'acceptation traverse la chaîne complète — installation, ingestion,
cycle, souvenirs, cockpit — mais son mode par défaut **ne dépense pas** : le
fournisseur d'embeddings est doublé. Le produit, lui, n'est jamais doublé : c'est
le fournisseur externe qui l'est.

Un mode complet existe, et la première rédaction de ce paragraphe l'annonçait
sous une commande qui n'existe pas (`make acceptance --complet` : `make` répond
« unrecognized option »). La vraie commande est :

```bash
sudo make acceptance-complet CLE="<votre clé d'embeddings>"
```

**Le défaut de schéma qui la rendait injouable est corrigé** — noté ici parce
qu'une alarme périmée coûte aussi cher qu'une alarme absente. Le 10 août 2026 au
matin, son premier appel payant postait un souvenir de genre `fact` et de
confiance `high` ; l'API ne connaît ni l'un ni l'autre, et rendait **422** avant
d'écrire. Le corps posté est désormais `kind: 'decision'` / `confidence:
'producer'` (`tests/acceptance/acceptance.sh`, `_etape_6_mode_complet`), et il
capture son code HTTP — une dépense dont on ne sait pas si elle a été acceptée
n'est pas une preuve, c'est une facture.

```
Rejouer :  grep -n "'kind'" tests/acceptance/acceptance.sh
Critère :  aucune occurrence de 'fact' ni de 'high' dans un corps posté.
           Vérifié le 10 août 2026 : les trois corps postés portent
           'decision' / 'producer'.
```

Ce que cela veut dire pour vous, exactement, **et cela n'a pas changé** : la
dépense réelle **n'est toujours prouvée nulle part dans ce dépôt**. Le mode par
défaut prouve la chaîne sans payer. Le mode qui paie est désormais *jouable*, mais
personne ne l'a joué avec une vraie clé et une vraie facture — corriger le corps
qu'il poste ne remplace pas la mesure. Tant que ce mode n'a pas tourné en dépense
réelle et rendu son rapport, cette ligne reste ouverte au registre de
[`docs/RELEASE-V1.md`](RELEASE-V1.md) : cela n'empêche pas d'installer un cerveau
ni de s'en servir — c'est le harnais qui est en cause, jamais le produit installé.

**Et c'est la même cause qui laisse un chemin entier non parcouru** : *installation
neuve → première conversation → premier souvenir*. Les cerveaux que les essais
posent sont **vides**, et il faut être exact sur pourquoi : la digestion ne réclame
pas « deux clés payantes ». Elle réclame **le binaire `claude` sur le serveur**,
**son authentification sous le compte d'agent**, et **les deux interrupteurs de
dépense ouverts** — dont aucun n'est armé dans un essai qui doit rester gratuit et
reproductible. Tout ce qui précède la digestion est prouvé (l'ingestion écrit
vraiment, le cycle démarre vraiment) ; c'est l'extraction elle-même, celle qui
transforme une conversation en souvenir, qui n'a jamais tourné sur un cerveau né de
ce framework. Les souvenirs des essais sont écrits par la route directe
`POST /v1/atoms`, pas par la curation.

### 2.3 La durée

Le cerveau de référence a huit mois. Aucun cerveau né de **ce** framework n'a plus
de quelques jours. Tout ce que ce dépôt dit du long terme — la dérive de la
taxonomie, la dette qui s'accumule sur les racines, le moment où le rappel devient
utile — vient d'un cerveau qui a précédé le framework.

C'est de l'expérience, pas de la mesure sur le produit livré.

---

## 3. Ce que le système ne peut pas garantir

### 3.1 Le journal système garde ce qu'on y écrit

Le produit n'écrit plus **aucun contenu de souvenir** dans le journal système :
ni clé, ni domaine, ni titre, ni fragment. Il n'y écrit que des empreintes
(`sha8:…`), stables donc corrélables, mais illisibles.

En revanche, **`systemd` ne sait pas effacer les entrées d'une seule unité.**
Ses commandes de purge travaillent sur des fichiers de journal, et un fichier
porte tout ce que la machine a écrit pendant sa période — le voisin compris.

Conséquence assumée : le contrôle de désinstallation **ne prescrit aucun geste**
sur le journal, parce qu'aucun geste ne serait à la fois efficace et borné à votre
cerveau. Ce que le produit écrit dans le journal doit pouvoir y rester. C'est
pourquoi il n'y écrit rien de lisible.

### 3.2 Le bac à sable de la suite de tests est une défense en profondeur

La suite de tests s'exécute derrière deux barrières : un rideau applicatif qui
juge les chemins, et — sur un noyau Linux qui le supporte — un confinement
`Landlock` hérité par toute la descendance.

En **régime nominal**, les deux tiennent. En **régime de repli** (noyau sans
`Landlock`, `macOS`, ou drapeau explicite), le rideau applicatif est seul, et sa
couverture est **partielle**. Les formes qui lui échappent ne sont pas laissées à
deviner : elles sont énumérées, avec leur mécanique, dans
`ZONES_NON_COUVERTES_DE_LA_PORTE`
(`tests/test_la_porte_du_sous_processus_est_fermee.py`), et un test **échoue** si
cette liste cesse de correspondre à ce que le rideau fait vraiment. Au 10 août
2026, quatre formes restent ouvertes en repli, et les quatre sont jouées à chaque
session : le corps passé par l'entrée standard (`bash -s`), le quotage ANSI-C, le
chemin composé à l'exécution, et le corps mis dans un fichier. Deux autres — l'argv
des primitives `os.*` et la valeur collée à une option courte — **ont été fermées**
et ne sont plus des zones aveugles.

Le modèle de menace est écrit noir sur blanc : **cette barrière protège contre un
test distrait, pas contre un test hostile.** Un test hostile exécute déjà du code
arbitraire sur votre machine — à ce stade, la seule protection qui compte est le
noyau. Nous ne prétendons pas gagner cette course.

Cela ne concerne en rien un cerveau installé : c'est du durcissement de
l'environnement de développement.

### 3.3 Deux cerveaux sur une machine : ce qui est garanti, et ce qui ne l'est pas

**Garanti, et éprouvé sur deux installations réelles :** rôles PostgreSQL,
comptes système, ports, coffres de secrets, journaux, sauvegardes et unités
`systemd` sont tous dérivés du nom du cerveau. Une installation refuse un rôle
qu'elle n'a pas créé, refuse un port déjà tenu, et refuse un nom de cerveau déjà
pris. Depuis le compte de l'un, le coffre, la base, les journaux et l'environnement
du processus de l'autre sont inaccessibles.

**Non garanti :** un compte disposant de `sudo` sur la machine peut évidemment
tout lire. L'isolement protège des accidents et des voisinages, pas d'un
administrateur.

### 3.4 Les sauvegardes hors site et l'alerte

Le bootstrap arme **trois** minuteries, et ce ne sont pas celles que la première
rédaction de ce paragraphe nommait. Les voici, lues dans le code qui les pose
(`bootstrap/lib/services.sh`) : le **cycle** de digestion, la **sauvegarde**, et
la **restauration de vérification**. Il n'y a pas de minuterie d'« hygiène ».

Quatre autres unités sont livrées **en gabarits, non armées** — `ops/systemd/` :
la copie hors site, le chien de garde de la sauvegarde, le contrôle de santé et
le contrôle d'installation. Deux d'entre elles restent des gabarits parce
qu'elles demandent une décision qui vous appartient : **la copie hors site**
(vers où ?) et **le canal d'alerte** (vers qui ?).

```
Rejouer :  grep -n '_poser_unite "\$U_.*\.timer"' bootstrap/lib/services.sh
Critère :  exactement trois lignes — cycle, sauvegarde, restauration. Une
           quatrième, et ce paragraphe a vieilli.
```

Tant qu'ils ne sont pas configurés, vos sauvegardes vivent sur la même machine que
votre cerveau. Un incendie de disque emporte les deux.

**Deux chemins de la sauvegarde n'ont jamais été joués**, pour la même raison — ils
demandent une clé et une seconde machine que les essais n'avaient pas : la
restauration d'un dump **chiffré** (§7 étape 2 de [`docs/SAUVEGARDE.md`](SAUVEGARDE.md),
`age -d`) et la copie hors site. Ce qui **est** joué à chaque passage du harnais :
le dump produit par l'unité, sa restauration dans une base jetable, sa comparaison
au cerveau vivant, et la bascule complète après une destruction réelle.

### 3.5 Deux vocabulaires de sauvegarde coexistent

`ops/` (dumps chiffrés, restauration prouvée, chien de garde) lit `$ARAC_HOME/.env`
et `DATABASE_URL_*`. Le bootstrap, lui, engendre sa propre unité de sauvegarde qui
lit `/etc/arac/<base>/arac.env` et `ARAC_DB_URL_ADMIN`. **Les deux fonctionnent ;
ils ne se connaissent pas.** Choisissez-en un —
[`docs/SAUVEGARDE.md`](SAUVEGARDE.md) décrit le premier, plus complet.

Ce n'est pas un défaut d'exécution, c'est une dette de vocabulaire : elle coûte au
lecteur, pas au cerveau. Elle est déclarée aussi en
[`README` §7e](../README.md#7-ce-qui-ne-marche-pas-encore--honnêtement), qui reste
la page d'entrée ; c'est ici qu'elle est tenue.

### 3.6 Le dépôt porte encore des résidus de son origine

Des identifiants internes hérités de l'installation d'origine, des chemins de
journaux codés en dur et des renvois vers des spécifications absentes du dépôt
subsistent dans les commentaires et quelques valeurs par défaut de `app/`,
`agents/` et `control_center/`.

Ils ne bloquent rien — aucun n'est sur un chemin qu'un cerveau neuf emprunte — mais
ils trahissent que le portage n'est pas fini, et **le premier chemin en dur qu'on
laisse passer est celui qui referme la porte qu'`arac_runtime.py` ouvre.** Deux
gardes tiennent la ligne (`tests/test_f1_aucune_trace_de_l_auteur.py` pour ce qui
nomme l'auteur, `tests/test_g1_aucun_nom_partage_entre_cerveaux.py` pour ce qui
nomme un cerveau) : ce qui reste est ce que ni l'un ni l'autre ne sait voir, et les
deux disent eux-mêmes ce qu'ils ne couvrent pas.

---

## 4. Ce qui coûte

**Le contrat de coût est en première page**, et il y reste :
[`README` §4](../README.md#4-ce-que-ça-coûte--en-première-page-parce-que-cest-un-contrat).
Il porte les quatre mesures du cerveau de référence, les ordres de grandeur
mensuels, et surtout l'avertissement qui les accompagne — *ne divisez pas ce bloc
par lui-même* : les quatre mesures ne couvrent pas la même fenêtre, et le
quotient de deux mesures prises séparément n'est une mesure de rien. Recopier le
tableau ici sans cette phrase, ce que faisait la première rédaction, revenait à
livrer le piège sans son garde-fou.

Ce qui appartient en propre à ce document est la limite, pas le prix :

**Le cerveau ne devient utile qu'après plusieurs semaines.** Vous paierez donc
plusieurs semaines avant de pouvoir juger. Si vous n'êtes pas prêt à attendre un
mois, n'installez pas ARAC aujourd'hui.

Les garde-fous de dépense sont posés par le bootstrap **avant** le premier cycle
et sont modifiables (les **deux** interrupteurs — `ARAC_ALLOW_PAID_AI` dans le
coffre et `arac_config.paid_ai_enabled` en base —, le plafond de jetons par
cycle, le garde-dépense) — voir [`docs/CONFIGURATION.md`](CONFIGURATION.md).

### 4.1 Deux prérequis ne sont vérifiés par personne

Le contrôle des prérequis (`bootstrap/lib/prereqs.sh`) constate onze pièces une
par une, dont le binaire de curation. **Deux choses lui échappent, et elles sont
nommées ici parce qu'elles ne le sont nulle part ailleurs :**

- **`npm` (donc Node).** Quand le binaire `claude` manque, l'écran donne le geste
  `sudo npm install -g @anthropic-ai/claude-code` — sans avoir vérifié que `npm`
  existe. Sur une Ubuntu nue, il n'existe pas : le remède prescrit échoue alors
  avec `npm: command not found`, et le lecteur doit deviner qu'il lui faut
  d'abord un Node. Conséquence bornée (un message d'erreur clair, aucun dégât),
  **P2** : le geste manquant est `sudo apt install -y nodejs npm`, ou
  l'installateur officiel de votre choix.
- **L'espace disque.** Toute la documentation recommande 20 Go ; rien ne les
  mesure. Un serveur trop juste ne le dira qu'au moment où `pip install`, un
  dump ou un index pgvector manquera de place. **P3** : documenté, non corrigé.

Ce que le bootstrap vérifie, en revanche, et qui ne l'était pas la manche
dernière : **le binaire de curation lui-même**, sa version, et son
authentification — à l'étape 1, puis **de nouveau au contrôle final sous le
dossier personnel du compte d'agent**, qui est le seul dont l'avis compte.

---

## 5. Où vit quoi — pour que rien ne soit déclaré à deux endroits

| Ce que vous cherchez | Où c'est tenu |
|---|---|
| une limite assumée du produit | **ici** |
| pourquoi le produit est fait ainsi, et ce que le choix coûte | [`docs/DECISIONS-ARCHITECTURE.md`](DECISIONS-ARCHITECTURE.md) |
| ce qui bloque une publication, et le registre des constats ouverts | [`docs/RELEASE-V1.md`](RELEASE-V1.md) |
| ce qui est prévu, et ce qui ne le sera pas | [`docs/ROADMAP.md`](ROADMAP.md) |
| ce qu'ARAC n'est pas, et ce qu'il ne cherche pas à être | [`docs/CE-QUE-ARAC-N-EST-PAS.md`](CE-QUE-ARAC-N-EST-PAS.md) |
| ce que le pont Mac vérifie et ce qu'il ne vérifie pas, en détail | fin de [`docs/PONT-MAC.md`](PONT-MAC.md) |
| l'état assertion par assertion du mandat (F1…F8) | [`GOAL.md`](../GOAL.md) |
| ce que ça coûte | [`README` §4](../README.md#4-ce-que-ça-coûte--en-première-page-parce-que-cest-un-contrat) |
| **ce qu'il faut posséder, ce qu'il faut acheter, et ce que le bootstrap vérifie ou non** | [`README` §5](../README.md#5-ce-quil-vous-faut-et-ce-que-vous-naurez-pas) — le tableau des prérequis, colonne par colonne. **Ce qui n'est PAS vérifié** est repris ici, en §4.1 |

La première page du README garde sa section « ce qui ne marche pas encore » : elle
est la **porte d'entrée** — F7 exige que rien ne soit relégué en annexe. Elle
enseigne ; ce document tient. Quand les deux divergeront, c'est celui-ci qui aura
raison, et l'autre qui sera à corriger.

---

## 6. Ce que la relecture du 10 août 2026 a corrigé

Ce document a été écrit de mémoire, puis rejoué affirmation par affirmation. Six
affirmations étaient fausses ou périmées. Les nommer coûte moins cher que de les
laisser découvrir :

| § | Ce qui était écrit | Ce qui est vrai |
|---|---|---|
| 1.1 | une seule famille de relation, colonne `relation` | **trois** familles, colonne `relation_type` — le critère de rejeu aurait rougi au premier cerveau vivant |
| 1.2 | la pondération par la confiance est « derrière deux drapeaux » | **aucun drapeau ne l'ouvre** : aucune route servie n'importe ce module |
| 2.1 | le pont « n'a jamais tourné » | ses **deux moitiés** ont tourné sur Linux contre deux cerveaux vivants ; c'est la part macOS qui n'a jamais tourné |
| 2.2 | `make acceptance --complet` « emprunte la vraie route et paie » | la commande n'existe pas sous cette forme, et le mode complet **meurt en 422** à sa première dépense |
| 3.4 | trois minuteries : sauvegarde, restauration, **hygiène** | cycle, sauvegarde, restauration — il n'y a pas d'hygiène |
| 4 | le tableau des coûts recopié | il vit en première page, **avec** l'avertissement qui l'accompagne |

Et une précision plutôt qu'une correction : en 3.2, l'énumération des zones
aveugles vit dans `tests/test_la_porte_du_sous_processus_est_fermee.py`, pas dans
le rideau lui-même ; deux de ces zones ont été fermées depuis.

---

## 7. Comment lire ce document dans six mois

Chaque affirmation ci-dessus porte, ou renvoie à, une commande qui la rejoue. Si
l'une d'elles ne se vérifie plus, **c'est ce document qui a tort**, pas votre
installation.

Les limites bougent. Celles qui bougeront le plus vite sont 1.1 (les relations
entre souvenirs), 1.5 (la vérification), et 2.1 (le pont depuis un vrai Mac) —
c'est précisément là que les retours d'utilisateurs comptent le plus.
