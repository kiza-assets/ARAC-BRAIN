# Comment il se nourrit — d'où vient la matière

Un cerveau ARAC ne produit rien. Il **digère**. Tout ce qu'il saura un jour est entré par
la porte décrite ici, et rien d'autre n'y entrera jamais.

C'est le premier document du *comment*. Il ne vous demande aucune commande : il vous dit
**ce qui quitte votre machine, ce qui n'en sort jamais, à quel moment, et pourquoi ce
n'est pas de la surveillance**. Si un seul paragraphe vous met mal à l'aise, arrêtez-vous
là — c'est exactement le but qu'il ait été écrit avant l'installation, et pas après.

| | Ce que vous devriez savoir en quittant cette page |
|---|---|
| 1 | Il y a **deux** sources réelles, et une troisième que le framework refuse volontairement de lire. |
| 2 | Ce qui part est du **texte de conversation**, jamais vos fichiers. |
| 3 | Le premier lancement **n'envoie rien** : il montre. |
| 4 | Ce n'est pas de la surveillance parce que **vous êtes le destinataire** — mais deux prestataires voient passer du texte, et il faut le dire. |
| 5 | Il existe un endroit où votre cerveau écrit **sans que ce soit sa base** : le **journal système**, qui appartient à la machine et pas à lui. |

---

# 1. Les deux sources réelles

## Claude Code (le CLI) — la source solide

Quand vous travaillez avec Claude Code, le CLI écrit lui-même votre session sur votre
disque, sans qu'ARAC ait rien demandé :

```
~/.claude/projects/<projet>/<session>.jsonl
```

Un fichier par session, un objet JSON par ligne, **écrit au fil de l'eau et jamais
réécrit en arrière**. Chaque ligne porte `sessionId`, `uuid`, `parentUuid`, `timestamp`,
`type` (`user` / `assistant`) et `message.content`.

C'est la source la plus solide de la chaîne, pour trois raisons qui tiennent toutes à la
forme du fichier : elle est textuelle, elle est append-only, et elle est complète — le
CLI n'y met pas un résumé, il y met la session.

> **Une honnêteté nécessaire.** Cette forme est **observée**, pas garantie par un contrat
> public. Une mise à jour du CLI peut la changer. `mac/arac-sync.py` est donc écrit en
> lecteur tolérant : une ligne qu'il ne comprend pas est **comptée puis ignorée**, jamais
> fatale. Si le compteur « lignes incomprises » explose un jour, ce n'est pas votre
> installation qui est cassée — c'est le format qui a bougé. C'est votre signal d'alerte,
> et il est délibérément visible.

## Claude Desktop / claude.ai — l'export officiel, et rien d'autre

L'application de bureau ne dépose **pas** vos conversations dans un fichier lisible. La
seule voie stable est l'export de données :

> claude.ai → Paramètres → Confidentialité → « Exporter les données »

Vous recevez un lien par courriel ; l'archive contient `conversations.json` — une liste de
conversations, chacune avec `uuid`, `name`, `created_at`, `updated_at` et
`chat_messages[]`, chaque message portant son `uuid`, son `parent_message_uuid`, son
`sender` (`human` / `assistant`), son `created_at` et son `content[]`.

C'est un **instantané**. Pour rattraper la suite, il faut le redemander. Ce n'est pas
confortable ; c'est honnête, et surtout **ça ne casse pas**.

## La troisième voie — celle que le framework refuse

`~/Library/Application Support/Claude/` contient un cache d'application Electron
(LevelDB / IndexedDB). Ce n'est pas un journal de conversations : c'est un format
binaire, non documenté, susceptible de changer à chaque mise à jour — et **lire une base
LevelDB pendant que l'application la tient ouverte est une excellente façon de la
corrompre**.

**Le framework n'y touche pas.** Pas par prudence molle : parce qu'aucune promesse
tenable ne peut être faite sur cette source, et qu'un cerveau qui corrompt l'application
qui le nourrit est un cerveau qui se coupe le bras.

> ### Ah, d'accord n° 1
> Il n'existe **aucune** capture automatique de Claude Desktop — ni sur un Mac, ni sur un
> PC, ni dans ce dépôt, ni ailleurs. Qui vous promet le contraire vous décrit un logiciel
> qui n'existe pas. Sur les deux systèmes, la voie est l'export officiel.

---

# 2. Ce qui part, ce qui ne part pas

C'est le tableau que vous êtes venu chercher.

| | Part vers votre serveur | Ne part jamais |
|---|---|---|
| **Texte des messages** | ✅ le texte, tel que vous l'avez écrit | |
| **Identité du message** | ✅ son identifiant natif, celui de son parent, le rôle, l'horodatage | |
| **Titre de la conversation** | ✅ quand la source en donne un | |
| **Blocs d'outillage** | | ❌ `tool_use`, `tool_result`, `thinking` sans champ texte |
| **Vos fichiers** | | ❌ aucun fichier de votre disque n'est lu ni transmis |
| **Secrets reconnus** | | ❌ masqués **avant** l'envoi (voir ci-dessous) |
| **Le cache de l'application de bureau** | | ❌ jamais ouvert |

## Le masquage des secrets — un filet nommé, pas une garantie

Avant qu'un octet ne quitte votre machine, `masquer_secrets()`
(`mac/arac-sync.py`) remplace neuf formes connues par un **marqueur nommé** :

| Ce qui est reconnu | Ce qui part à la place |
|---|---|
| `sk-…` (clé d'API) | `[REDACTED:cle-api]` |
| `ghp_` / `gho_` / `ghu_` / `ghs_` / `ghr_` … | `[REDACTED:jeton-github]` |
| `AKIA…` / `ASIA…` | `[REDACTED:cle-aws]` |
| bloc `-----BEGIN … PRIVATE KEY-----` | `[REDACTED:cle-privee]` |
| jeton de forme JWT (`eyJ….….…`) | `[REDACTED:jwt]` |
| `password = …` | `password=[REDACTED]` |
| `bearer <20 caractères ou plus>` | `bearer [REDACTED]` |
| `postgresql://user:pass@…` | `postgresql://[REDACTED]@` |
| `token = <20 caractères ou plus>` | `token=[REDACTED]` |

**Nommé, jamais muet.** Un `[REDACTED:cle-api]` retrouvé dans un souvenir six mois plus
tard vous dira qu'il y avait là quelque chose, **et quoi**. Un trou silencieux ne vous
dirait rien, et vous concluriez que la phrase a toujours été incomplète.

> **Ce filtre est un filet, pas une garantie.** Il attrape les formes connues. Un secret
> qui ne ressemble à aucune des neuf lignes ci-dessus passera. Un second filet existe
> côté serveur (`app/brain/memory_policy.py` porte la même famille de motifs, appliquée
> au moment d'écrire un atome), et le modèle de digestion reçoit pour consigne explicite
> de ne **jamais recopier** un secret mais d'émettre à la place un atome `alert` qui le
> **décrit sans le citer**. Trois filets valent mieux qu'un ; aucun des trois n'est une
> promesse.

## Le journal système — ce qui sort du cerveau sans quitter la machine

Le tableau ci-dessus regarde la **porte** : ce qui sort de votre machine. Il existe un
endroit qu'il ne voyait pas, parce que rien n'y franchit la porte — et c'est pourtant un
endroit où votre cerveau écrit tout seul, plusieurs fois par jour : **le journal
système**. Les services de votre cerveau
(`arac-<votre_base>-api`, `-cycle`, `-sauvegarde`, `-restauration`) écrivent dans
**journald**, qui n'appartient pas à votre cerveau — il appartient à la **machine**.
Concrètement : lisible par root et par tout compte du groupe `systemd-journal`, conservé
des semaines, partagé avec les autres services et, sur un serveur à plusieurs cerveaux,
avec le voisin. Votre base est protégée par des rôles et un coffre en `0700` ; le journal,
lui, ne l'est par rien de tout cela.

Ce qui compte est donc **ce que le produit y écrit** :

| | Va dans le journal | N'y va pas |
|---|---|---|
| **Comptes et durées** | ✅ atomes, conversations, messages, embeddings, latences, verdicts | |
| **Identifiants techniques** | ✅ noms d'unités et de bases, `request_id`, votre `node_id` | |
| **Requêtes de l'API** | ✅ la méthode, le **chemin** (`/v1/dashboard/search`), le code de retour | ❌ la chaîne de requête, donc **le texte de ce que vous cherchez** |
| **Échantillon d'atomes relus** (`ops/restore_verify.sh`) | ✅ **empreintes** : `sha256` de la clé et du domaine, tronqué à huit caractères, la date, la longueur décodée | ❌ la clé, le domaine, la valeur |
| **Contexte d'un avertissement d'écriture** (`create_atom.warnings`, `supersede_atom.warnings`) | ✅ le **code** de l'avertissement, sa sévérité, l'`atom_id`, les longueurs et les seuils, les noms de champs | ❌ le domaine, les étiquettes, la clé, le `rationale` — **empreintés** |
| **Le texte d'un souvenir** | | ❌ pas par ces chemins-là, et c'est mesuré à chaque `make acceptance` — voir la borne ci-dessous |

L'empreinte est celle du reste du produit (`key_sha8`), ce qui permet de rapprocher deux
lignes qui parlent du même souvenir sans qu'aucune ne le cite. **Ce tableau ne dit pas
« aucun texte, jamais, nulle part » — un absolu de ce genre tombe au premier
contre-exemple, et le contre-exemple est arrivé deux fois.** Il dit : *sur ces chemins-là,
voici ce qui passe et ce qui ne passe pas*, et il donne le moyen de le refaire.

> **Ce n'était pas vrai avant cette version, et c'est la raison d'être de ce paragraphe —
> mais il y avait DEUX endroits, pas un, et c'est la vraie leçon.**
> `ops/restore_verify.sh` imprimait la **clé** et le **domaine** de trois souvenirs **en
> clair**, sous « *échantillon d'atomes réellement relus :* ». Le dépôt avait pourtant
> déjà écrit la règle ailleurs — « *aucune clé ne doit être écrite en clair dans un
> artefact durable ; `sha8` suffit à corréler deux occurrences sans rien révéler* » — et
> un autre module nommait même le destinataire à protéger : « *le candidat complet reste
> disponible pour la revue humaine via la DB, accès contrôlé, JAMAIS via journald* ».
>
> **Cet endroit-là fermé, il en restait un second, qui écrivait tout seul :** la route
> d'écriture de l'API versait dans journald le contexte complet de chaque avertissement —
> le domaine, les étiquettes, la clé, et jusqu'à deux cents caractères du `rationale` —
> et la digestion emprunte cette route trois fois par jour. Les deux sont fermés
> aujourd'hui, par le même moyen : [`app/journal.py`](../app/journal.py), *fermé par
> défaut*, qui empreinte toute chaîne dont on ne peut pas **démontrer** qu'elle ne porte
> rien. **La leçon est celle qui revient à chaque manche** : on avait fermé une classe en
> énumérant ses occurrences connues, pas en cherchant sa forme — « quels *autres*
> appelants versent un objet non filtré dans un `logger` dont la sortie est journald ? ».
> Une liste oublie ; ce qu'elle oublie est exactement ce que personne n'avait imaginé.

**Ce que ça change pour vous, et il faut le savoir *avant* d'installer.** Un journal ne se
nettoie pas par unité : `journalctl --vacuum-*` travaille sur des **fichiers**, qui
portent aussi le journal des autres services. Ce qu'un journal a avalé y reste jusqu'à la
rotation. Deux conséquences pratiques :

1. **Si vous installez maintenant**, ce que le journal de votre cerveau retient est sa
   **forme** — combien d'atomes, à quel rythme, quand, quels avertissements, et quelles
   empreintes se répètent —, pas ses mots. C'est de la métadonnée, et elle est lisible par
   les administrateurs de la machine. **Le critère est *rien*, et il se refait en une
   commande, sur un mot que vous seul avez écrit :**

   ```bash
   # rc=1 et aucune ligne = ce mot n'est nulle part dans le journal de ce cerveau.
   sudo journalctl -u "arac-$BASE-api.service" --no-pager | grep -i "<un mot à vous>"
   ```

   Mesuré ainsi le **10 août 2026**, sur un cerveau de banc rempli par la vraie route
   d'écriture puis désinstallé : seize motifs cherchés — valeurs, *pourquoi*, étiquettes,
   clés, domaines —, aucun trouvé. `make acceptance` le refait à chaque passage, sur son
   propre cerveau et ses propres témoins (§13.10 de son rapport).
2. **Si vous reprenez un cerveau installé plus tôt**, ou si vous rendez ce serveur, le
   chapitre du départ vous dit quoi regarder et ce que vous pouvez en faire :
   [`INSTALLATION.md` § 13, « Le journal système »](INSTALLATION.md#le-journal-système--ce-que-ce-chapitre-ne-peut-pas-effacer-et-pourquoi).
   **C'est la version qui fait foi** — cette page-ci dit ce qui *sort* du cerveau et
   s'arrête là ; le §13 tient l'inventaire de ce qui entre dans journald, et c'est le seul
   endroit où il est tenu. `ops/uninstall_check.sh` regarde le journal à l'étape 9 et
   refuse de dire « propre » quand il y trouve la signature de l'ancienne fuite — il
   cherche *une* signature, pas toutes les formes possibles, et le §13 dit pourquoi cette
   borne compte.

---

# 3. Pourquoi ce n'est pas de la surveillance

C'est la question qu'il faut se poser, et elle mérite mieux qu'un « faites-nous
confiance ». Quatre différences, toutes vérifiables sur votre machine.

## 1. Le premier lancement n'envoie rien

Au tout premier passage, le script **refuse** d'envoyer quoi que ce soit. Il vous montre
d'abord ce qu'il a trouvé — combien de conversations, lesquelles, depuis quand — et vous
rend la main.

```
--inventaire     # métadonnées seulement : nombre de fichiers, tailles, emplacements.
                 # aucun contenu affiché, aucun envoi.
```

Ces fichiers contiennent une vie. Vous devez voir ce qui part **avant** que ça parte.
Cette étape n'est pas un confort, c'est un verrou : elle rend le code de sortie `10` et
attend votre accord.

## 2. La destination est la vôtre

Le texte va à **votre** API, sur **votre** serveur, dans **votre** base. Il n'y passe pas
par un intermédiaire, et il ne traverse pas l'Internet ouvert : le transport est un
tunnel SSH que vous ouvrez, décrit dans
[`docs/COMMENT-IL-SE-SYNCHRONISE.md`](COMMENT-IL-SE-SYNCHRONISE.md).

Une surveillance a un observateur qui n'est pas l'observé. Ici, **il n'y en a pas** — et
c'est la seule définition qui compte.

## 3. Rien n'est effacé, rien n'est modifié chez vous

Le script **lit**. Il ne supprime rien, ne réécrit rien, ne déplace rien. La seule chose
qu'il écrit sur votre machine est son propre état, sous `~/.arac/`. L'unité systemd
fournie pour un serveur monte d'ailleurs `~/.claude` en **lecture seule**
(`BindReadOnlyPaths`) — la contrainte est posée par le système, pas seulement par la
bonne volonté du script.

## 4. Ce qui sort quand même de chez vous — dit franchement

Il faut le dire, parce que c'est vrai et que le taire ruinerait les trois points
précédents :

| Ce qui sort | Vers qui | Quand |
|---|---|---|
| Le **texte des conversations** sélectionnées pour un cycle | le fournisseur du modèle de curation (Anthropic) | trois fois par jour, borné par un budget de jetons |
| Le **texte d'un atome** et le **texte de vos questions** au moment du rappel | le fournisseur d'embeddings (OpenAI, `text-embedding-3-large`) | à la création d'un atome, et à chaque rappel |

**Ce sont les deux seuls appels externes de toute la chaîne.** Ils ne sont pas
optionnels : sans le premier, aucun souvenir n'est produit ; sans le second, il n'y a pas
de rappel par similarité. Le détail des coûts est en première page du
[`README.md`](../README.md) — délibérément, parce que c'est un contrat.

Un interrupteur existe et est armé **avant** le premier cycle : `ARAC_ALLOW_PAID_AI=0`
n'émet aucun appel payant. Le cerveau tourne alors sans jamais rien apprendre — c'est un
mode de découverte, pas un mode d'usage.

> ### Ah, d'accord n° 2
> « Ce n'est pas de la surveillance » ne veut pas dire « rien ne sort ». Cela veut dire
> que **le destinataire du savoir, c'est vous** : personne d'autre ne construit d'image
> de vous à partir de ce corpus, parce que personne d'autre ne le possède. Deux
> prestataires voient passer du texte au moment du traitement ; aucun ne détient votre
> mémoire.

# 4. Le moment — pourquoi le cerveau ne vous écoute pas en direct

La synchronisation passe **une fois par heure**, pas en continu.

```
OnCalendar=hourly
RandomizedDelaySec=300     # jusqu'à 5 min de décalage aléatoire
Persistent=true            # une machine éteinte rattrape au réveil
```
*(`deploy/systemd/arac-pont-sans-mac.timer.modele` — l'équivalent launchd est dans
`mac/com.arac.pont.sync.plist.modele`.)*

Le raisonnement est simple et vaut d'être compris : **le serveur ne digère que trois fois
par jour.** Synchroniser plus souvent ne fait rien arriver plus vite dans la mémoire ;
cela ne fait qu'augmenter le nombre d'occasions de casser quelque chose. L'heure est le
compromis : assez fin pour qu'une conversation du matin soit là pour le cycle de
l'après-midi, assez large pour que rien ne s'emballe.

Conséquence directe, et il faut l'accepter : **votre cerveau a toujours quelques heures de
retard sur vous.** Ce n'est pas un défaut à corriger, c'est le rythme d'un organe qui
consolide — voir [`docs/POURQUOI.md`](POURQUOI.md), marche 4.

---

# 5. Le cerveau ne sait pas d'où vient une conversation. Il sait de quel **poste**.

C'est la notion qui gouverne toute l'entrée, et elle n'est pas « machine » : c'est le
**nœud** (`node_id`). Une chaîne que vous choisissez, déclarée des deux côtés.

Sur le cerveau de référence, deux postes alimentent la même mémoire :

| Poste | Messages bruts reçus |
|---|---|
| le poste **serveur** (sessions Claude Code sur la machine elle-même) | ~130 000 |
| le poste **Mac** (sessions Claude Code du portable + exports déposés) | ~21 000 |

```sql
SELECT node_id, count(*) FROM arac.raw_messages GROUP BY 1 ORDER BY 2 DESC;
```

*(ordre de grandeur du 8 août 2026. `raw_messages` ne fait que grossir : un chiffre à
l'unité y est faux le jour même de sa publication. C'est le **rapport** entre les deux
lignes qui porte l'enseignement, et lui bouge lentement.)*

Deux enseignements tiennent dans ces deux lignes.

**Le premier :** un cerveau n'a pas besoin d'un Mac. Le script est du Python de la
bibliothèque standard ; lancé **sur le serveur, pour le serveur**, il n'a même pas besoin
du tunnel — la source et la destination partagent la boucle locale. Sans Mac, vous perdez
le confort, pas les capacités.

**Le second, moins agréable :** le poste serveur pèse ici six fois le poste Mac. Ces
sessions-là sont les conversations où le cerveau se regarde travailler — volumineuses,
faiblement porteuses de savoir durable. Le framework le sait et porte un garde-fou dédié
(`agents/cortex/value_gate.py`), livré en **observation seule** : il repère et journalise
ces conversations sans jamais décider à votre place. Vous relisez le journal avant
d'armer quoi que ce soit.

---

# 6. Ce que ça donne, et ce que ça ne donne pas

**Ce que la matière première vous garantit**

- Elle existe **sans effort supplémentaire**. Vous avez eu ces conversations de toute
  façon. Pas de rituel du soir, pas de discipline à tenir.
- Elle contient les **raisons**, pas seulement les conclusions — c'est tout l'argument de
  la marche 2 de [`POURQUOI.md`](POURQUOI.md).
- Elle est **rejouable** : renvoyer tout l'historique est sans danger (le serveur
  déduplique), ce qui vous donne un filet quand vous doutez d'un trou.

**Ce qu'elle ne donne pas, et ne donnera pas**

- Vos conversations Claude Desktop **en direct**. Elles n'arrivent que par export manuel.
- Ce que vous n'avez pas dit. Une décision prise dans votre tête n'entre nulle part.
- Ce que vous avez dit **ailleurs** : messagerie, réunions, appels, papier. Le corpus est
  celui de vos conversations avec Claude, et strictement celui-là.
- Une garantie que rien de sensible ne partira. Le filet attrape les formes connues.

---

# Ce qui a été vérifié pour écrire ce document

| Affirmation | Où elle se vérifie | État |
|---|---|---|
| Deux sources exploitées, la troisième refusée | `mac/arac-sync.py`, docstring d'en-tête | ✅ lu |
| Les neuf motifs de masquage | `mac/arac-sync.py`, `_MOTIFS_SECRETS` | ✅ lu, recopiés un par un |
| Second filet côté serveur | `app/brain/memory_policy.py`, `SECRET_PATTERNS` | ✅ lu |
| Consigne « ne recopie jamais un secret, émets un `alert` » | `agents/cortex/prompt.py`, règle 4 | ✅ lu |
| Le premier lancement n'envoie rien (code de sortie 10) | `mac/arac-sync.py`, `--inventaire` | ✅ lu |
| `~/.claude` monté en lecture seule | `deploy/systemd/arac-pont-sans-mac.service.modele` | ✅ lu |
| Rythme horaire, décalage aléatoire, rattrapage | `deploy/systemd/arac-pont-sans-mac.timer.modele` | ✅ lu |
| Modèle d'embeddings et dimension | `app/repr/builder.py`, `app/db.py` | ✅ lu |
| **Deux** postes alimentent la même mémoire, dans un rapport d'environ six pour un | `SELECT node_id, count(*) FROM arac.raw_messages GROUP BY 1 ORDER BY 2 DESC` sur le cerveau de référence. **Le nombre de postes et leur rapport sont l'affirmation ; les comptes ne le sont pas** — cette cellule a porté « 126 568 / 21 075 » et la même requête, rejouée le soir du jour où elle disait « mesuré », rendait déjà 136 622 / 21 102. `raw_messages` ne fait que grossir : c'est le § « deux postes » qui dit comment le lire | ✅ **mesuré le 08/08/2026, et rejoué** |
| Le value-gate n'écrit rien | `agents/cortex/value_gate.py`, docstring | ✅ lu |
| L'échantillon d'atomes du journal ne porte que des **empreintes** | `ops/restore_verify.sh`, le bloc « échantillon d'atomes réellement relus » : `substr(encode(sha256(convert_to(coalesce(key,''),'UTF8')),'hex'),1,8)` | ✅ lu, et joué sur un cerveau réel par `make acceptance` |
| Le contrôle de départ regarde le journal et nomme ce qu'il y trouve | `ops/uninstall_check.sh`, sa section 7 | ✅ lu, et joué à l'étape 9 de `make acceptance` |

**Ce qui n'a pas pu être vérifié :** personne n'a exécuté ce pont sur un Mac neuf avant
publication. Le format exact et la taille réelle de
`~/Library/Application Support/Claude/` sur *votre* machine sont la donnée que ce
document n'a pas pu constater. `--inventaire` est là pour ça, et il ne transmet rien.

---

**Suite du manuel :**
[`COMMENT-IL-SE-SYNCHRONISE.md`](COMMENT-IL-SE-SYNCHRONISE.md) — le trajet, de votre
disque à votre base.
**Les gestes**, eux, sont dans [`PONT-MAC.md`](PONT-MAC.md).
