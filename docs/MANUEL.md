# Le manuel du cerveau

Ceci n'est pas une documentation technique. C'est le **manuel** : les questions que
quelqu'un se pose, dans l'ordre où il se les pose, avec une réponse à chacune et un
renvoi vers le texte qui la développe.

Il n'y a rien à installer pour le lire. Comptez une soirée pour le tout, une demi-heure
pour la colonne de droite seule.

---

## Les huit questions

| | La question | La réponse en une phrase | Où elle est développée |
|---|---|---|---|
| **1** | **Qu'est-ce qu'un cerveau ARAC ?** | Une mémoire qui se construit toute seule à partir de vos conversations avec Claude, et qui vous rend le savoir sans que vous ayez à vous rappeler où il était rangé. | [`CONCEPTS.md`](CONCEPTS.md) · [`CE-QUE-ARAC-N-EST-PAS.md`](CE-QUE-ARAC-N-EST-PAS.md) |
| **2** | **Pourquoi existe-t-il ?** | Parce que votre savoir n'a pas disparu — il est devenu inatteignable. Une archive répond quand on lui donne une adresse ; une mémoire revient sans qu'on lui en donne. | [`POURQUOI.md`](POURQUOI.md), les sept marches |
| **3** | **Comment apprend-il ?** | En quatre temps, décrits ci-dessous. C'est le seul chapitre qui n'a pas son document : c'est le plan des quatre suivants. | **§ « Comment il apprend »**, plus bas |
| **4** | **Comment se nourrit-il ?** | De vos sessions Claude Code, lues sur votre disque, et de l'export officiel de Claude Desktop. Rien d'autre n'entre. | [`COMMENT-IL-SE-NOURRIT.md`](COMMENT-IL-SE-NOURRIT.md) |
| **5** | **Comment se synchronise-t-il ?** | Par un tunnel SSH sortant, une fois par heure, derrière une garde qui refuse tout poste qu'elle ne connaît pas. | [`COMMENT-IL-SE-SYNCHRONISE.md`](COMMENT-IL-SE-SYNCHRONISE.md) |
| **6** | **Comment construit-il ses atomes ?** | Trois fois par jour, un modèle lit un lot de conversations et **propose** ; le code **dispose**. Il a le droit de ne rien retenir, et il l'exerce. | [`COMMENT-IL-CONSTRUIT-SES-ATOMES.md`](COMMENT-IL-CONSTRUIT-SES-ATOMES.md) |
| **7** | **Comment crée-t-il ses scopes ?** | Il ne les crée pas : **vous** les déclarez, une fois, et la liste est fermée. Les souvenirs vivent sur les feuilles. | [`COMMENT-IL-CREE-SES-SCOPES.md`](COMMENT-IL-CREE-SES-SCOPES.md) |
| **8** | **Comment retrouve-t-il naturellement ?** | Vous demandez sans savoir où c'était rangé. Il trouve — et il doute, ce qui est une limite mesurée, pas une figure de style. | [`POURQUOI.md`](POURQUOI.md), marche 7 |

**Trois documents complètent le manuel sans en faire partie :**
[`PREMIER-JOUR.md`](PREMIER-JOUR.md) et [`PREMIER-MOIS.md`](PREMIER-MOIS.md) — ce que vous
verrez vraiment, et pourquoi vous aurez envie d'arrêter au jour 2 —
et [`PHILOSOPHIE.md`](PHILOSOPHIE.md), qui donne les raisons de **ne pas** installer ARAC.

---

# Comment il apprend — le plan des quatre chapitres

Un cerveau ARAC apprend en quatre temps. Ils sont séquentiels, et chacun peut échouer
seul — c'est précisément pour ça qu'ils sont séparés.

```
   ①  SE NOURRIR          vos conversations quittent votre disque
       │                  ce qui est capté · ce qui ne l'est jamais
       ▼
   ②  SE SYNCHRONISER     elles atteignent votre base
       │                  le tunnel · le poste déclaré · la garde qui refuse
       ▼
   ③  DIGÉRER             elles deviennent des atomes — ou rien du tout
       │                  le modèle propose · le code dispose
       ▼
   ④  SE RANGER           chaque atome prend un territoire
                          la liste est fermée · les souvenirs vivent sur les feuilles

   ───  et alors seulement, ce que les quatre rendent possible  ───

       RAPPELER           vous demandez, il répond
                          il n'a pas de chapitre à lui : voir CONCEPTS.md,
                          et POURQUOI.md, marche 7.
```

**Ce qui distingue ces quatre temps d'un simple tuyau**, c'est que chacun a le droit de
**refuser**, et qu'aucun ne fait semblant :

| Temps | Son droit de refus | Ce qu'il refuse de faire |
|---|---|---|
| ① Se nourrir | masquer plutôt que transmettre | envoyer un secret reconnu |
| ② Se synchroniser | **fermer plutôt qu'ouvrir** | accepter un poste inconnu, ou une configuration incomplète |
| ③ Digérer | **s'abstenir plutôt qu'inventer** | produire un souvenir quand il n'y a rien à retenir |
| ④ Se ranger | `422` plutôt que créer | inventer un territoire qui n'a pas été déclaré |

Un système qui accepte tout produit une mémoire à laquelle on ne peut pas se fier. Les
quatre refus ci-dessus sont ce qui rend la mémoire **citable** — et une mémoire non
citable ne vaut pas mieux qu'un souvenir vague.

---

# Un cycle réel, pour rendre tout ça concret

Ce cerveau-ci a tourné le 8 août 2026, après une panne, sous les yeux de son
propriétaire. Voici son reçu — un cycle **réel**, avec ses réussites, ses abstentions et
sa quarantaine.

```
   12 conversations présentées
       ├──  8  ont produit du savoir
       ├──  3  n'avaient RIEN à retenir  ← une vertu, pas un échec
       └──  1  n'a pas rendu de décision ← re-présentée au cycle suivant

    7 atomes écrits · 1 candidat en quarantaine
    7 / 7 porteurs d'un embedding · 6 feuilles touchées · 0 sur une racine
   32 scopes recalculés (1 740 atomes membres)

    ⚠ un atome « alert » proposé spontanément : le cerveau a signalé
      un risque d'exposition de clés qu'on ne lui avait pas demandé
      de chercher.
```

Ces neuf lignes contiennent tout le manuel. Le § 8 de
[`COMMENT-IL-CONSTRUIT-SES-ATOMES.md`](COMMENT-IL-CONSTRUIT-SES-ATOMES.md) les lit une par
une.

---

# Ce que le manuel ne vous promettra pas

Un manuel honnête se juge à ce qu'il refuse de dire. Quatre choses, vérifiées dans le
code et non dans l'intention — et la liste **complète**, tenue avec le rejeu de chaque
entrée, est dans [`docs/LIMITES-CONNUES.md`](LIMITES-CONNUES.md) :

| Ce qu'on pourrait attendre | L'état réel |
|---|---|
| **Des liens explicites entre atomes** | Le modèle n'a aucun moyen de déclarer qu'un souvenir en **contredit** ou en **découle** un autre. Une couche de liens **dérivés** existe, elle est créée par les migrations et alimentée à chaque cycle — mais elle ne porte que trois relations mécaniques : ce souvenir en remplace un autre, ces souvenirs viennent de la même conversation, ces deux textes se ressemblent. Le détail et son rejeu : [`docs/LIMITES-CONNUES.md`](LIMITES-CONNUES.md) §1.1. |
| **La détection des contradictions** | Deux atomes qui s'opposent coexistent, tous deux actifs. Une seule exception, étroite : deux « états courants » sur un même scope lèvent une alerte critique. |
| **Un vrai graphe de connaissances** | Ce qui existe est de la proximité **sémantique** : « ces deux textes se ressemblent », jamais « ces deux faits se répondent ». |
| **Agir depuis le cockpit** | Le cockpit **n'a aucune route qui écrive dans la mémoire** — sa seule route non-GET est la connexion, qui pose un cookie ; et son rôle PostgreSQL est en lecture seule, donc écrire lui est impossible, pas seulement interdit. Il sert à comprendre un cerveau, pas à le piloter. Corriger un souvenir est un geste d'API. |

Le reste des manques est énuméré dans [`ROADMAP.md`](ROADMAP.md) et au § 7 du
[`README.md`](../README.md).

---

# L'ordre de lecture recommandé

**Vous hésitez encore à installer** — une soirée :
[`POURQUOI.md`](POURQUOI.md) → [`CE-QUE-ARAC-N-EST-PAS.md`](CE-QUE-ARAC-N-EST-PAS.md) →
[`PREMIER-MOIS.md`](PREMIER-MOIS.md)

**Vous voulez comprendre la machine** — ce manuel, dans l'ordre :
[nourrir](COMMENT-IL-SE-NOURRIT.md) → [synchroniser](COMMENT-IL-SE-SYNCHRONISE.md) →
[digérer](COMMENT-IL-CONSTRUIT-SES-ATOMES.md) → [ranger](COMMENT-IL-CREE-SES-SCOPES.md)

**Vous installez** :
[`DEMARRAGE-RAPIDE.md`](DEMARRAGE-RAPIDE.md) ou [`INSTALLATION.md`](INSTALLATION.md),
puis [`PONT-MAC.md`](PONT-MAC.md) pour les gestes du pont.

**Quelque chose ne marche pas** :
[`DEPANNAGE.md`](DEPANNAGE.md), classé par symptôme.
