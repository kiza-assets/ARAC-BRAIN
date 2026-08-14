# Comment il crée ses scopes — le rangement, et son prix

C'est le point le plus mal compris d'ARAC, et celui qui coûte le plus cher quand on le
comprend trop tard.

Un **scope** est un territoire de votre mémoire. Chaque atome en porte exactement un.
Deux choses surprennent toujours :

1. **Un scope ne s'invente pas à la volée.** L'énumération est fermée. Un scope inconnu
   part en `422` — l'atome est refusé, et perdu.
2. **Les atomes vivent sur les feuilles.** Un atome posé sur une racine est rangé dans une
   zone morte du cerveau, et il y reste.

Ce document explique le mécanisme, le compromis qu'il incarne, et — franchement — ce que
la deuxième règle coûte réellement, parce que ce dépôt le dit ailleurs de façon trop
large.

---

# 1. D'où vient votre taxonomie

Elle ne vient pas du dépôt. **Le dépôt n'en contient aucune.**

```
  vos réponses à l'entretien d'installation
              │
              ▼
      config/scopes.toml            ← LA source de vérité, que vous écrivez
              │
    ┌─────────┴──────────┐
    ▼                    ▼
app/schemas/          db/seeds/
scope_generated.py    scopes.sql
    │                    │
    ▼                    ▼
 rempart n° 1         rempart n° 2
 (Pydantic : 422)     (clé étrangère vers arac.scopes)
```

Trois fichiers, **un seul sens de lecture**. Modifier l'énumération à la main ne sert à
rien : la prochaine régénération l'écrase, et la base ne suivrait pas de toute façon.

```bash
python3 bootstrap/wizard.py            # l'entretien : vos racines, vos feuilles
python3 bootstrap/generate_scopes.py   # scopes.toml → énumération + seed SQL
```

Un extrait de `config/scopes.toml` — c'est du TOML, il se lit :

```toml
[[root]]
key = "travail"
label = "TRAVAIL"
description = "Votre activité professionnelle principale."

[[leaf]]
root = "travail"
key = "finance"
label = "Finance"
```

Cela donne la racine `travail` et la feuille `travail/finance`. Profondeur maximale : 2.

> **Le script n'écrit jamais en base.** Il produit du SQL que le bootstrap vous **montre**
> avant de l'appliquer. Et une suppression de scope est **refusée** tant que des atomes y
> vivent — le script vous dit lesquels. Un rangement ne disparaît pas sous les pieds de ce
> qu'il range.

## Pourquoi deux remparts pour la même règle

Parce qu'un rempart unique finit toujours par être contourné — par un script de
migration, un import en masse, une main dans `psql` un soir de fatigue.

| Rempart | Où | Ce qu'il attrape |
|---|---|---|
| L'énumération Pydantic | à l'entrée de l'API | un scope inconnu, **avant** d'avoir touché la base — `422` |
| La clé étrangère | dans PostgreSQL | tout le reste, y compris ce qui n'est pas passé par l'API |

Ils sortent du **même** fichier. Ils ne peuvent donc pas diverger — un vrai défaut du
cerveau de référence, où trois docstrings annonçaient 34, 40 et 45 scopes pendant que la
base en portait 38.

---

# 2. Le compromis : rigidité contre dilution

C'est une décision de conception, elle a un coût, et elle se défend.

## Ce que la souplesse coûterait

Imaginez qu'un scope inconnu soit créé à la volée. Au bout de six mois, sur quelques
milliers d'atomes, votre mémoire contient :

```
travail/finance        travail/finances       travail/Finance
travail/fin            travail/compta         travail/comptabilite
```

Six territoires jumeaux. Aucun n'est faux. Et **votre rappel se dilue entre les six** :
vous cherchez une décision budgétaire, elle est dans le quatrième, vous ne la trouvez
pas. Pire — vous ne saurez jamais qu'elle existait, parce qu'un scope de plus ne ressemble
pas à une panne.

C'est une dérive **silencieuse et irréversible**, et c'est exactement ce contre quoi la
liste fermée protège.

## Ce que la rigidité coûte

Elle coûte, et il faut le dire : **un savoir qui n'entre dans aucune de vos feuilles est
un savoir que le cerveau refuse.**

Trois issues, et une seule est bonne :

| Issue | Verdict |
|---|---|
| Le ranger dans la feuille la **moins mauvaise** | acceptable, souvent le bon réflexe |
| **Ajouter la feuille** : modifier `scopes.toml`, régénérer, réappliquer | la bonne réponse quand le sujet revient |
| L'écarter | légitime — tout ne mérite pas d'être retenu |

Le moteur a même un garde-fou pour la deuxième : quand un sujet revient sans avoir de
rangement propre, il **le signale** au lieu d'inventer un scope (qui partirait en `422`,
l'atome perdu). Vous décidez d'ajouter la feuille ou non — c'est votre taxonomie. Elle se
déclare, une ligne par sujet, dans un fichier `scope_suggestions.toml` que **vous créez**
sous `config/` — le dépôt n'en livre aucun, parce qu'il ne connaît ni votre métier ni vos
sujets. Tant qu'il n'existe pas, il n'y a simplement aucune suggestion. **Zéro suggestion
n'est pas une panne : c'est le silence d'un moteur qui ne connaît pas encore vos sujets.**

> ### Ah, d'accord n° 1
> La rigidité n'est pas de l'autoritarisme technique. C'est le seul moyen connu de garder
> une mémoire personnelle navigable au-delà de quelques milliers d'éléments. Un système
> qui vous laisse créer des catégories librement vous laisse aussi les fragmenter
> librement — et vous ne vous en apercevrez qu'une fois qu'il sera trop tard pour
> réparer.

---

# 3. La règle qui coûte le plus cher : les atomes vivent sur les feuilles

## Le principe

```
   travail                ← RACINE.  Un conteneur. Un atome n'a rien à faire ici.
   ├── travail/finance    ← FEUILLE. C'est ici qu'un souvenir vit.
   ├── travail/operations ← FEUILLE.
   └── travail/strategie  ← FEUILLE.
```

Un atome posé sur `travail` est **écrit, actif, et rangé dans une zone morte** du cerveau.

Le code le sait, et il expose l'ensemble pour qu'on puisse le détecter :

```python
from app.schemas.scope import is_leaf, ROOTS, LEAVES
is_leaf("travail")          # False  ← à vérifier AVANT d'écrire, pas après
is_leaf("travail/finance")  # True
```

## La mesure, sur le cerveau de référence — **la seule de tout le dépôt**

> **Ce paragraphe est la source unique de ce chiffre.** Partout ailleurs — `README`,
> `PREMIER-JOUR`, `PREMIER-MOIS`, `CONTRIBUER`, `config/scopes.example.toml`, l'entretien
> d'installation — la dette de racine est nommée **en proportion** et renvoie ici. C'est
> la règle que le dépôt s'est donnée dans `config/scopes.example.toml` : *« un chiffre
> recopié à trois endroits finit toujours par diverger »*. Il l'avait fait : le même
> compte a vécu à six endroits avec trois valeurs, dont l'une ne correspondait même pas à
> la requête imprimée au-dessus d'elle.

```sql
SELECT count(*) FILTER (WHERE scope NOT LIKE '%/%')  AS sur_une_racine,
       count(*)                                      AS total_actifs,
       round(100.0 * count(*) FILTER (WHERE scope NOT LIKE '%/%')
                   / count(*), 1)                    AS pourcent
FROM arac.memory_atoms
WHERE status = 'active';
```

```
 sur_une_racine | total_actifs | pourcent
----------------+--------------+----------
            164 |         1755 |      9.3
```

*(instantané du 8 août 2026, obtenu par la requête ci-dessus, sur le cerveau de référence
— et rien d'autre. **C'est la requête qui fait foi, pas le bloc.** Le corpus grossit à
chaque cycle, donc les deux comptes bougent ; la proportion, elle, tourne autour de 9 %
depuis huit mois. **C'est bien ça le problème** : rien ne la fait baisser toute seule. Le
filtre `status = 'active'` est celui du reste du système — c'est sur les atomes actifs que
`W-STATE-007` compte, et sans lui on additionne des atomes supersédés qui ne pèsent plus
sur rien.)*

**Près d'un souvenir actif sur onze.** Et il n'en est jamais ressorti de lui-même.

---

# 4. Ce que « perdu » veut dire exactement — la mise au point

Ce dépôt a longtemps écrit qu'un atome posé sur une racine était *« invisible au rappel »*,
et qu'*« aucune question ne le ferait jamais remonter »*. La formule est frappante, elle est
**trop large**, et un manuel se doit d'être exact : le reste de la documentation a donc été
repris, et l'entretien d'installation comme le générateur de taxonomie parlent désormais
comme cette page — **y compris dans le fichier que le générateur écrit chez vous**, ce qui
n'était pas le cas jusqu'en août 2026 : `app/schemas/scope_generated.py` portait encore, en
tête de son `ROOTS`, la formule trop large. Vérifiez-le en une commande, sur les deux
outils que vous lancez :

```bash
grep -rn "invisible au rappel\|jamais remonter" bootstrap/   # doit ne rien rendre
```

**Il en subsiste ailleurs, et on ne vous en donnera pas la liste.** Une liste de survivants
est fausse le jour où elle est écrite : la précédente en nommait deux, et il y en avait
huit. La règle est donc de forme, pas d'inventaire — **partout où ce dépôt écrit
« invisible au rappel » ou « aucune question ne le fera jamais remonter », c'est cette
page qui dit vrai**, que ce soit dans une étiquette du cockpit, dans la doctrine envoyée
au modèle de curation, ou dans un commentaire du moteur. Vous les repérez d'une commande :

```bash
grep -rn "invisible au rappel\|jamais remonter" .
```

Voici ce qui a été vérifié dans le code, ligne par ligne.

## Ce dont un atome sur une racine n'est **pas** exclu

`POST /v1/atoms/recall` — le rappel par similarité brute — sélectionne :

```sql
WHERE status = 'active' AND embedding IS NOT NULL
  AND (<scope demandé> IS NULL OR scope = <scope demandé>)
ORDER BY embedding <=> <votre question>
```

**Il n'y a aucun filtre sur les feuilles.** Un atome posé sur une racine, s'il porte un
embedding et qu'il est actif, **peut remonter** sur une question qui lui ressemble. Il en
va de même pour `context_for`. Écrire le contraire serait vous mentir.

## Ce dont il **est** réellement exclu — et c'est beaucoup

| | Ce qu'il perd | Où c'est décidé |
|---|---|---|
| **L'état courant** | une racine est marquée `root_level` : **jamais éligible** à un état courant, jamais candidate à une proposition. Son score de maturité est forcé à **0**. | `app/brain/scope_discovery.py` |
| **L'existence dans la vue des scopes** | `/v1/brain/current-state` **saute purement et simplement** les scopes racines. Ils ne sont pas « à zéro » : ils ne sont pas listés. | `app/routers/brain.py` |
| **La mesure de couverture** | le pourcentage de couverture se calcule sur les **feuilles éligibles** uniquement. Un atome sur une racine ne compte ni au numérateur ni au dénominateur. | idem |

L'« état courant » est la synthèse qui répond à *« où en est ce sujet aujourd'hui ? »* —
la forme la plus utile qu'un cerveau puisse rendre. Un atome sur une racine n'y contribue
jamais, et ne le fera jamais.

## La formulation juste

> **Un atome posé sur une racine n'est pas effacé, et il peut encore remonter par
> similarité pure. Mais il est exclu de tout ce que le cerveau construit *au-dessus* du
> rangement : pas d'état courant, pas de place dans la vue des scopes, pas de comptage
> dans la couverture. Il devient un souvenir orphelin — présent, et hors de la vie du
> cerveau.**

C'est moins spectaculaire que « invisible ». C'est tout aussi coûteux sur la durée, et
c'est vrai.

## Le cerveau vous le dit — au-dessus d'un seuil

Ce n'est pas totalement silencieux, et c'est une bonne nouvelle :

- **`W-STATE-007` — « dette de racine »** : l'anti-dérive lève un avertissement lorsqu'une
  racine nue porte **au moins 20 atomes actifs**, avec pour geste suggéré de proposer un
  re-rangement vers des feuilles. *Proposition seulement — l'application reste humaine.*
- **Le cockpit** en parle aussi, dans le récit du jour, lorsqu'un scope racine a gagné des
  atomes **dans la fenêtre observée**.

Deux limites qu'il faut connaître : le seuil de 20 laisse passer les racines faiblement
peuplées, et le signal du cockpit ne se déclenche que sur des atomes **récents** — une
dette ancienne et stable ne dit plus rien du tout. C'est très exactement ainsi que la
dette du § 3 a pu s'accumuler sans jamais déclencher d'alarme.

**La seule vérification fiable est celle que vous faites vous-même**, et elle tient en une
requête :

```sql
-- Le compte DOIT rester à zéro. Vérifiez-le au jour 7, pas au mois 6.
SELECT count(*) FROM arac.memory_atoms
WHERE status = 'active' AND scope NOT LIKE '%/%';
```

> ### Ah, d'accord n° 2
> Le piège n'est pas qu'un atome mal rangé soit perdu. C'est qu'il soit **parfaitement
> normal en apparence** : il est en base, il est actif, il a un embedding, il figure dans
> les totaux. Rien ne clignote. Un défaut qui ne se voit pas est un défaut qui dure.

---

# 5. Combien de feuilles — et pourquoi la profondeur s'arrête à 2

## Le nombre

**C'est ici, et ici seulement, que ce dépôt donne un ordre de grandeur.** L'entretien
(`bootstrap/wizard.py`) et le fichier d'exemple y renvoient plutôt que de le recopier : un
chiffre écrit à trois endroits diverge toujours — c'est exactement la faute du §1, où trois
docstrings annonçaient 34, 40 et 45 scopes pendant que la base en portait 38.

Un ordre de grandeur, donc, pas une règle : **cinq à huit racines**, **trois à six feuilles
par racine**. Une vingtaine à une quarantaine de feuilles au total. Le cerveau de référence,
après huit mois, en porte six et trente-neuf.

| Trop peu | Trop |
|---|---|
| tout finit dans deux ou trois feuilles fourre-tout | vous hésitez à chaque atome, et le modèle aussi |
| le rangement ne range plus rien | des feuilles jumelles se peuplent au hasard — la dilution revient par la porte que la liste fermée devait fermer |

## La profondeur

`max_depth = 2`, et c'est **le défaut recommandé**. Pas de `travail/finance/tva/2026`.

Deux raisons. **La première :** une hiérarchie profonde demande de savoir *où* une chose
va avant de savoir *ce qu'elle est* — or le cerveau range après avoir lu, pas avant. **La
seconde :** la finesse que vous cherchez en descendant, vous l'obtenez mieux par la
similarité. C'est le métier des embeddings ; ce n'est pas celui d'une arborescence.

**Le générateur accepte pourtant 2 ou 3**, et refuse tout le reste
(`bootstrap/generate_scopes.py` : « `taxonomy.max_depth` doit valoir 2 ou 3 — au-delà, plus
personne ne retrouve ses souvenirs »). Ce document disait 2 comme si 3 était impossible :
c'était plus strict que le code, et un lecteur qui posait 3 obtenait une taxonomie que le
manuel déclarait inexistante. Si vous posez 3, sachez ce que vous achetez : un niveau de
plus à tenir en tête au moment de ranger, pour une finesse que la similarité vous donnait
déjà. **Les deux raisons ci-dessus ne disparaissent pas parce que le générateur cède.**

---

# 6. Changer d'avis — parce que vous changerez d'avis

Votre taxonomie du premier jour ne sera pas la bonne. C'est prévu.

**Ajouter une feuille** est peu coûteux : une entrée dans `scopes.toml`, régénérer,
réappliquer. Rien n'est déplacé.

**Renommer ou supprimer** est coûteux, et c'est délibéré : le script **refuse** de
supprimer un scope tant que des atomes y vivent, et vous dit lesquels. Vous devez d'abord
les déplacer. Un rangement qui s'évapore en emportant ce qu'il rangeait serait la pire
panne possible.

**Le bon moment pour corriger un atome mal rangé, c'est le jour 7.** Pas le mois 6 —
d'ici là, d'autres atomes se seront appuyés dessus, et la correction deviendra une
migration.

---

# Ce qui a été vérifié pour écrire ce document

| Affirmation | Où elle se vérifie | État |
|---|---|---|
| La chaîne `scopes.toml` → énumération + seed SQL | `bootstrap/generate_scopes.py`, docstring | ✅ lu |
| Un scope hors liste part en `422` avant la base | `app/schemas/scope.py` | ✅ lu |
| Second rempart par clé étrangère vers `arac.scopes` | idem + `db/seeds/scopes.sql` | ✅ lu |
| Le script n'écrit jamais en base ; refus de supprimer un scope peuplé | `bootstrap/generate_scopes.py` — `scopes_habites_absents()` est en **lecture seule** et le retrait est refusé (« RETRAIT REFUSÉ — du savoir vivant serait orphelin »). **Précision ajoutée le 9 août 2026** : ce refus n'a lieu **que si `--dsn` est passé** ; sans DSN, le script ne consulte aucune base et ne peut donc rien refuser. C'est le bootstrap qui le lui passe | ✅ lu, et **rejoué** |
| `is_leaf` / `ROOTS` / `LEAVES` exportés pour la détection | `app/schemas/scope.py` | ✅ lu |
| Suggestions de feuilles manquantes, déclarées par vous | `app/brain/memory_policy.py`, `_load_scope_suggestions()` | ✅ lu |
| Profondeur maximale 2 | `bootstrap/generate_scopes.py` — `max_depth` vaut 2 à défaut et **n'accepte que 2 ou 3** (au-delà, refus motivé) ; le modèle qu'un clone reçoit, `config/scopes.example.toml`, pose 2. *(La méthode citait `config/scopes.toml` : ce fichier est engendré par l'entretien et exclu par `.gitignore` — un lecteur qui vient de cloner ne l'a pas, et la preuve lui était donc inexécutable.)* | ✅ lu, et **rejoué sur un clone** |
| **`/recall` ne filtre PAS sur les feuilles** | `app/routers/atoms.py`, SQL de `recall` et de `context_for` | ✅ **lu — d'où la mise au point du § 4** |
| Une racine est `root_level`, jamais éligible, score forcé à 0 | `app/brain/scope_discovery.py` | ✅ lu |
| `/brain/current-state` saute les scopes racines | `app/routers/brain.py` | ✅ lu |
| Couverture calculée sur les feuilles éligibles | idem | ✅ lu |
| `W-STATE-007`, seuil de 20 atomes actifs | `app/brain/anti_drift.py` | ✅ lu |
| Signal du cockpit sur la dette de racine récente | `control_center/cc_v1/today.py` | ✅ lu |
| **164 atomes actifs sur 1 755 (9,3 %) posés sur une racine** | `arac.memory_atoms` du cerveau de référence, requête du § 3 | ✅ **mesuré le 08/08/2026 — et ce document est le seul *Markdown* du dépôt à porter ce compte** |
| Aucun autre fichier ne recopie ce compte | — | ❌ **FAUX, et la ligne mentait deux fois.** Voir ci-dessous. |

> **▸ La ligne « aucun autre fichier ne recopie ce compte » était fausse, et sa preuve
> l'était aussi.** Elle proposait `grep -rn "sur une racine" .` — une recherche de **chaîne
> exacte**, c'est-à-dire une énumération d'un seul élément, qui échoue au premier retour à
> la ligne. Rejouée, elle ne voit aucun des fichiers fautifs, parce que la phrase y est
> coupée entre deux lignes.
>
> Le compte est bel et bien recopié **hors du Markdown**, avec une valeur qui a déjà
> divergé — `157` et « 9 % » là où ce document mesure `164` sur `1 755`, soit 9,3 % :
> `app/schemas/scope.py`, `control_center/cc_v1/projects.py`,
> `config/projects.example.toml` et `tests/test_scope_hierarchy.py`, deux fois. Deux
> autres l'**imprimaient à l'écran** pendant l'installation —
> `bootstrap/checks/verify_install.sh` et `bootstrap/lib/database.sh` — et c'était le pire
> cas : un installateur qui affirme un compte à un inconnu. Ces deux-là ne le disent plus,
> ils disent la proportion, et `verify_install.sh` renvoie au compte qu'il vient de
> mesurer sur la base du lecteur.
>
> **Cette liste est une dette DÉCLARÉE, pas un inventaire garanti** : elle date du
> 08/08/2026, elle a déjà été trouvée incomplète une fois, et une liste écrite à la main
> est exactement ce que le paragraphe suivant condamne. Ce qui la remplacera est un garde
> de FORME, sur tout ce que `git` transporte.
>
> **La leçon est celle du § 4, appliquée aux chiffres** : une promesse d'unicité vérifiée
> par une chaîne exacte est une promesse qu'on ne tient pas, on la *ressent*. Ce qui se
> détecte, c'est la **forme** — « un nombre à trois chiffres à moins de deux cents
> caractères d'un mot de la famille *racine nue*, hors de cette page » — sur un texte dont
> on a d'abord écrasé les blancs, pour qu'une coupure de ligne ne cache plus rien. Et le
> corpus à balayer, ce n'est pas `docs/` : c'est **tout ce que `git` transporte**, parce
> que le chiffre survit là où l'on ne balaie pas.

**Ce dont ce document n'est pas certain — et qui mérite un œil.** Les centroïdes de scope
(`app/services/project_registry.py`) sont calculés par un `GROUP BY scope` **sans filtre
sur les feuilles**. Sur le cerveau de référence, **4 racines nues portent un centroïde**.
Le routeur de reprise peut donc, en principe, orienter une reprise vers une racine. Cela
n'a pas été observé en service, et ce document ne l'affirme pas — il le signale comme une
incohérence à instruire, pas comme un comportement documenté.

---

**Vous êtes au bout du *comment*.** La dernière question — *comment il retrouve
naturellement ce qu'il sait* — est traitée à la marche 7 de
[`POURQUOI.md`](POURQUOI.md), avec la limite qui va avec : **il trouve, mais il doute.**
