# ARAC BRAIN — notes de version 1.0.0

*Première version publique.*

---

## Ce que c'est

Vous parlez à Claude tous les jours, et tous les jours il oublie. ARAC BRAIN lit
ces conversations, en extrait ce qui mérite d'être retenu, et le range dans une
mémoire que vous pouvez interroger en langage ordinaire — six mois plus tard.

**Claude Desktop pour réfléchir. Claude Code pour construire. ARAC BRAIN pour se
souvenir.**

Ce n'est ni un éditeur de notes, ni un RAG, ni un chatbot, ni un tableau de bord.
[`docs/CE-QUE-ARAC-N-EST-PAS.md`](CE-QUE-ARAC-N-EST-PAS.md) dit pourquoi, et
quand un autre outil serait meilleur pour vous.

## Ce que la V1 fait

- **Un cerveau naît en une commande.** Un entretien décide de la forme de votre
  mémoire ; le bootstrap installe base, rôles, secrets, services, cockpit.
- **Vos conversations remontent** depuis un Mac par un tunnel SSH, ou depuis le
  serveur pour Claude Code CLI.
- **Elles deviennent des souvenirs** : des affirmations autonomes, datées,
  sourcées, rangées dans vos domaines, porteuses d'un vecteur de 3 072 dimensions.
- **Vous les retrouvez** en posant une question, sans vous souvenir où c'était.
- **Un cockpit montre le cerveau vivre** — chaque chiffre porte la requête SQL qui
  le produit, rejouable à la main.
- **Vous pouvez tout perdre et tout retrouver** : sauvegarde armée, restauration
  vérifiée, procédure de bascule éprouvée sur une base réellement détruite.
- **Vous pouvez partir.** La désinstallation nomme tout ce qui porte votre
  mémoire, et prouve qu'il n'en reste rien.

## Ce que la V1 ne fait pas

Le registre complet est dans
[`docs/LIMITES-CONNUES.md`](LIMITES-CONNUES.md). Les trois qui comptent :

- **Aucune détection de contradiction.** Deux décisions opposées cohabiteront sans
  que personne vous prévienne.
- **Rien ne vérifie qu'un savoir est encore vrai.** Un souvenir de huit mois vous
  est rendu avec la même assurance qu'un souvenir d'hier.
- **Le pont depuis un vrai Mac n'a jamais été éprouvé par nos essais** — aucun de
  nos agents n'a de Mac. C'est le maillon où vos retours comptent le plus.

## Ce que ça coûte

~87 000 jetons par cycle de digestion, ~31 500 par souvenir produit, trois cycles
par jour, ~150 souvenirs par mois. Les embeddings sont facturés à part et pèsent
peu.

**Deux interrupteurs vous protègent :** rien ne dépense votre argent sans un geste
explicite de votre part, et le premier `systemctl start` du cycle sera refusé —
volontairement.

**Le cerveau ne devient utile qu'après plusieurs semaines.** Si vous n'êtes pas
prêt à attendre un mois avant de juger, n'installez pas ARAC BRAIN aujourd'hui.

## Prérequis

Un Mac avec Claude Desktop · Claude Code CLI · un serveur Ubuntu · PostgreSQL 16
avec pgvector · une clé OpenAI pour les embeddings.

**Ce qui digère vos conversations est le binaire Claude Code CLI posé sur votre
serveur, pas une clé d'API.** Si vous avez déjà un abonnement Claude, vous n'avez
rien de plus à acheter pour la digestion. C'est le point que ce projet a mis le
plus longtemps à écrire correctement — voir plus bas.

## Comment commencer

```bash
git clone <votre-copie>/ARAC-BRAIN.git && cd ARAC-BRAIN
make venv && make test        # vert, sans base, sans réseau, sans clé
```

Puis [`docs/DEMARRAGE-RAPIDE.md`](DEMARRAGE-RAPIDE.md).
Pour comprendre avant d'installer : [`docs/POURQUOI.md`](POURQUOI.md).

---

## Comment cette version a été validée

Le critère de sortie n'était pas « zéro défaut ». Il était :

> **Un nouvel utilisateur possédant un Mac, Claude Desktop, Claude Code CLI et un
> serveur Ubuntu peut créer son propre cerveau sans notre aide.**

Il a été éprouvé par des relecteurs adversariaux à qui l'accès au cerveau
d'origine était **interdit** — ils ne pouvaient rien combler mentalement. Trois
regards, rejoués à chaque manche : celui qui installe sans rien savoir, celui qui
cherche ce qui pourrait nuire au cerveau d'un voisin, celui qui vérifie que la
documentation dit vrai.

Le dernier passage a rendu **PRÊT sur les trois, sans aucun P0**. Le parcours
complet a été joué : installation par le chemin interactif, conversations montées
par le vrai pont, sept souvenirs nés avec leurs vecteurs, cockpit ouvert page par
page, sauvegarde, restauration comparée, **base détruite pour de vrai** puis
remontée, souvenirs relus sous les quatre rôles, désinstallation propre en une
passe.

`make test` : vert dans quatre configurations. `make acceptance` : 8 étapes
prouvées, 0 échec, **0 intervention manuelle**.

## Ce que ces épreuves ont trouvé, et qui vaut d'être dit

Un projet gagne à publier ce qu'il a appris de ses propres erreurs. Trois
défauts qu'aucune relecture interne n'aurait vus :

**On faisait acheter la mauvaise chose.** L'installation demandait une clé d'API
pour la curation. Or le cycle ne l'utilise pas : il lance le binaire Claude Code
CLI. Un nouvel utilisateur payait pour un service dont son cerveau ne se servait
pas, et n'apprenait jamais. Personne dans le projet ne pouvait le voir : celui qui
a écrit le code avait ce binaire installé depuis toujours, et ne l'avait donc
jamais listé comme prérequis. **Il a fallu quelqu'un qui parte de rien, et qui
paie.**

**Un test vert peut ne rien prouver.** Une assertion affirmait l'immuabilité d'un
champ en cherchant un nom qui n'existait pas — vraie de toute éternité. Elle a
survécu à six passages d'audit *parce qu'elle était verte*. Le dépôt refuse
désormais mécaniquement une assertion négative portant sur un nom absent du
vocabulaire réel.

**Sept pages du cockpit rendaient 200 en étant mortes.** Le harnais les empruntait
et les voyait vertes. Il vérifie maintenant que chaque route **ressort le contenu
qu'on vient d'y mettre** : un code de retour ne prouve rien.

Le raisonnement complet de chaque décision, avec son prix, est dans
[`docs/DECISIONS-ARCHITECTURE.md`](DECISIONS-ARCHITECTURE.md).

## Ce qui reste ouvert

Classé, documenté, et sans effet sur votre installation : voir
[`docs/RELEASE-V1.md`](RELEASE-V1.md) §5. En résumé — le bac à sable de la
suite de tests a une couverture partielle sans `Landlock` (il protège d'un test
distrait, pas d'un test hostile) ; `systemd` ne sait pas purger le journal d'une
seule unité, raison pour laquelle le produit n'y écrit que des empreintes ; la
sauvegarde hors site et le canal d'alerte sont livrés en gabarits, parce qu'ils
demandent une décision qui vous appartient.

## Merci

Ce projet doit sa qualité à des relecteurs qui n'avaient pas le droit de deviner.
Si vous installez ARAC BRAIN et que quelque chose vous fait hésiter, dites-le même
si ce n'est pas un bogue : **un endroit où l'on doit deviner est un défaut de ce
projet, pas de son lecteur.**
