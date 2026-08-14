# Glossaire

Chaque terme du produit, défini en une phrase. Les définitions longues vivent dans
[`CONCEPTS.md`](CONCEPTS.md) ; celles-ci servent à ne pas rester bloqué au milieu d'une
page.

Les renvois `→` pointent vers le terme à lire d'abord.

---

**Abstention** — Réponse du rappel quand le meilleur candidat est trop loin de la
question : le cerveau se tait au lieu de rendre un voisin plausible. → *Bande de
confiance*

**Acquittement** — Le décompte de ce que le serveur a réellement écrit, renvoyé à l'agent
de synchronisation ; c'est lui, et non le code HTTP `200`, qui autorise le curseur local à
avancer.

**Agent de synchronisation** — Le programme qui tourne sur votre machine, lit vos
conversations locales et les envoie au serveur à travers le tunnel. → *Pont*

**Alerte** — Au sens du monitoring : une des quatre conditions qui méritent de vous
réveiller (le cerveau n'apprend plus, les cycles échouent en série, la base gonfle, plus
rien n'entre). Au sens des atomes : un `kind` qui signale un risque.

**Atome** — La plus petite unité de savoir qui reste vraie et utilisable une fois séparée
de la conversation dont elle vient.

**Audit (d'un atome)** — Le fait qu'un agent ou un humain ait confirmé un atome après son
écriture ; sur le cerveau observé, 98 % du corpus n'a jamais été audité.

**Avertissement** — Une remarque consignée à l'écriture d'un atome quand quelque chose
sent mauvais sans être interdit (mélange de mondes, collision d'empreinte, justification
suspecte de brièveté) ; il n'empêche jamais l'écriture, il laisse une trace.

**Bande de confiance** — La traduction en mots de la distance du meilleur résultat d'un
rappel : haute (≤ 0,15), moyenne (≤ 0,23), basse (≤ 0,53), au-delà abstention ; la bande
basse répond quand même, elle avertit. **Elle n'apparaît pas dans la réponse de votre
installation** : elle appartient au Context Engine, dont les drapeaux sont fermés par
défaut. Ce que `POST /v1/atoms/recall` vous rend est la **distance**, dont ces seuils vous
donnent la lecture. → `CONCEPTS.md` §4

**Bulletin de santé** — Le rapport que produit la sonde de santé : un indice global et la
liste des métriques hors seuil, calculé en lisant le registre du cockpit plutôt qu'un
second jeu de seuils. → `EXPLOITATION.md`

**Calibration** — Le fichier gelé et versionné qui fixe les seuils des bandes de confiance
et les ajustements du rappel ; le chargeur refuse toute version autre que celle attendue,
pour qu'on ne modifie jamais un seuil en douce.

**Cerveau** — L'ensemble de votre installation : la base, les atomes, la taxonomie, les
services, le cockpit. Pas un logiciel, une instance.

**Clé (d'un atome)** — L'identifiant court d'un atome dans son scope, strictement en
minuscules, chiffres et tirets ; une majuscule est la première cause historique de mise en
quarantaine d'un cycle.

**Clé de déduplication** — L'empreinte qui permet à l'ingestion de reconnaître un message
déjà reçu et de l'ignorer sans créer de doublon. → *Idempotence*

**Cockpit** — L'interface web de lecture du cerveau, servie sur la boucle locale, protégée
par mot de passe et code à usage unique, connectée à la base avec un rôle en lecture
stricte.

**Constitution** — Un texte court, lu au début de chaque session, qui énonce les règles
non négociables d'écriture en mémoire ; son empreinte SHA-256 est publiée pour qu'on
puisse savoir, des mois plus tard, sous quelles règles un atome a été écrit.

**Contrat** — Le format JSON strict que le modèle d'extraction doit produire : un objet et
rien d'autre, sans texte avant ni après, avec une décision terminale par conversation.

**Cortex** — L'organe qui digère les conversations en atomes ; il n'a aucun outil, n'écrit
rien lui-même, et rend un unique objet JSON. → *Cycle*

**Coupe-circuit** — Un fichier dont la seule présence interdit toute dépense d'IA ; il est
un fichier, et non une ligne en base, pour fonctionner même base de données éteinte.

**Curateur** — Le rôle du modèle appelé pendant un cycle : lire des messages bruts et
proposer des atomes. → *Cortex*

**Curseur de curation** — Le marqueur, propre à chaque conversation, indiquant jusqu'où
l'extraction est allée ; l'ingestion n'y touche jamais, il appartient exclusivement au
cycle.

**Cycle** — Une passe de digestion complète, exécutée trois fois par jour (typiquement
04:00, 13:00, 21:00 heure locale) ; entre deux cycles le cerveau est au repos, et c'est
l'état normal.

**Digestion** — Le processus par lequel des conversations deviennent des atomes ; le mot
est employé pour insister sur son caractère discontinu. → *Cycle*

**Disposition** — La dernière phase d'un cycle : poster les atomes proposés, conversation
par conversation, et n'avancer les curseurs que sur ce qui a été réellement montré au
modèle.

**Distance cosinus** — La mesure d'écart entre deux vecteurs, fondée sur l'angle et non
sur la longueur ; 0 signifie « même direction », donc « même sens », et elle n'a aucune
signification absolue — seulement comparative.

**Embedding** — La liste de 3 072 nombres qu'un modèle produit à partir d'un texte, et qui
en constitue les coordonnées dans un espace où la proximité géométrique approche la
proximité de sens.

**Empreinte** — Une somme de contrôle SHA-256 ; ARAC en calcule sur le contenu des
messages (côté serveur, jamais celle du client), sur la constitution, et sur les corps mis
en quarantaine.

**Entretien** — Les cinq questions du bootstrap qui construisent votre taxonomie et votre
configuration ; il n'installe rien, il décrit le cerveau que l'installation fabriquera.

**État courant** — Un atome de type `state` qui résume où en est un domaine ; il n'existe
que pour les feuilles, jamais pour les racines.

**Extraction** — Voir *Cycle* et *Cortex*.

**Feuille** — Un scope de second niveau (`racine/feuille`) ; **c'est le seul endroit où un
atome doit vivre**.

**Fraîcheur** — L'état d'un atome vis-à-vis du temps, dérivé de la colonne
`confirmed_until` : périmé, frais, ou **inconnu** — l'absence de date n'est jamais traitée
comme une preuve de fraîcheur.

**Frein à dépense** — Le garde qui décide, avant chaque cycle, s'il reste du budget IA
pour la journée ; un cycle refusé laisse un reçu avec son motif.

**Gotcha** — Un `kind` d'atome : un piège rencontré et sa sortie ; le meilleur rapport
valeur/octet du corpus, parce qu'il vous rend exactement le temps qu'il vous a coûté.

**Graphe** — L'ensemble des liens entre atomes, matérialisés dans `arac.atom_links` et
recalculés à chaque cycle. Trois types : deux **certains** (« remplace », « suivait dans la
même conversation ») et un **inféré** (« se ressemble » — voisinage vectoriel réciproque).
Aucun ne porte de rapport de sens, et **aucun chemin de rappel ne les lit** : le graphe est
écrit, il n'est pas encore servi.

**Idempotence** — La propriété qui fait qu'envoyer deux fois la même chose produit le même
résultat qu'une seule fois ; elle est ce qui rend une reprise après coupure sans danger.

**Index approché** — La structure qui accélère la recherche vectorielle en n'examinant
qu'une fraction du corpus ; « approché » est un mot honnête, elle peut manquer un vrai plus
proche voisin.

**Ingestion** — La porte d'entrée des données : authentification, liste blanche de postes,
validation stricte, plafonds durs, masquage des secrets, écriture idempotente, reçu.

**Jeton (de modèle)** — L'unité de facturation d'un appel à un modèle ; sur le cerveau
observé, ~87 000 par cycle et ~31 500 par atome produit.

**Jeton (porteur)** — Le secret d'authentification d'un poste source auprès de l'API ; un
par poste, jamais partagé.

**`kind`** — Le type d'un atome ; une vingtaine existent, mais quatre — `decision`,
`gotcha`, `state`, `pattern` — portent 74 % du savoir réellement utile.

**Lien d'atome** — Une arête du graphe. → *Graphe*

**Lot** — L'ensemble des tranches de conversations présentées au modèle en un seul cycle,
plafonné par un budget de jetons et non par un nombre de conversations.

**Masquage des secrets** — Le filtre appliqué au contenu avant tout stockage : une clé
d'API ou un mot de passe repéré est remplacé, et le nombre de masquages est consigné dans
le reçu.

**Message brut** — Un message de conversation stocké tel qu'il est arrivé (après masquage
des secrets) ; il n'est jamais réécrit, et il n'a **pas** d'embedding.

**Métrique** — Un chiffre du cockpit, indissociable de la requête SQL qui produit ses
lignes sources ; une métrique sans preuve ne peut pas être créée.

**Poste source** (`node_id`) — L'identifiant d'une machine autorisée à envoyer des
conversations ; un poste inconnu est refusé même avec un jeton valide.

**Pont** — L'ensemble du chemin entre votre machine et le serveur : agent de
synchronisation, tunnel, ingestion. → `PONT-MAC.md`

**Preuve** — Les lignes sources d'une métrique, accompagnées du SQL exécuté, de sorte que
n'importe quel chiffre affiché puisse être rejoué dans un terminal.

**Provenance** (`source_ref`) — Le champ qui relie un atome à la conversation et aux
messages dont il est issu ; son format doit être figé tôt, un changement ayant coûté 76 %
de la provenance sur le cerveau observé.

**Quarantaine** — L'état d'un cycle dont la sortie du modèle était invalide : le corps est
conservé en base (borné en taille) pour qu'on puisse diagnostiquer, les curseurs restent
figés.

**Racine** — Un scope de premier niveau, sans `/` ; c'est un **conteneur, pas un
rangement**. Un atome posé là reste rappelable par similarité pure, mais il est exclu de
tout ce que le cerveau construit au-dessus du rangement : pas d'état courant, pas de place
dans la vue des scopes, pas de comptage dans la couverture. Un souvenir orphelin —
présent, et hors de la vie du cerveau. Voir *dette de racine*.

**Rappel** — L'opération qui retrouve des atomes à partir d'une question : embedding de la
question, plus proches voisins parmi les atomes actifs, ajustements bornés, bande de
confiance, budget.

**Reçu** — Une ligne écrite pour tracer un événement, avant qu'il ne produise ses effets ;
il en existe pour chaque requête d'ingestion (acceptée **ou refusée**) et pour chaque
cycle (exécuté **ou ignoré**).

**Registre (du cockpit)** — La liste des métriques, avec pour chacune sa définition, sa
formule, sa requête de valeur et sa requête de preuve ; tout son SQL est statique et
littéral, donc sans surface d'injection.

**Revue (file de)** — L'endroit où atterrit ce qui demande un arbitrage humain :
conversations bloquées, sorties mises en quarantaine, cas que le cycle a refusé de
trancher seul.

**Rôle** — Un compte PostgreSQL aux droits délimités : `arac_admin` (schéma), `arac_app`
(lecture/écriture), `arac_agent` (les agents), `arac_readonly` (le cockpit, en lecture
stricte).

**Scope** — Le domaine où un atome est rangé, sous la forme `racine/feuille` ; un scope
hors taxonomie est refusé par l'API (422) et par la base (clé étrangère).

**Score de confiance** — Un entier de 0 à 100, **facultatif** : un atome peut n'en porter
aucun, et beaucoup n'en portent pas. Il **ne pèse pas sur le rappel**, ni sur ce qui est
rendu ni sur l'ordre. Son seul effet mécanique est un seuil à l'**écriture** : un atome
écrit avec la trace d'audit `autonomous_agent_suggest` et un score **sous 70** naît
directement en archive de faible confiance (69 archivé, 70 vivant). Le déclencheur est un
`BEFORE INSERT` — **baisser un score par `PATCH` ne déclasse rien** —, et il ignore les
atomes sans cette trace comme ceux sans score. Voir [`CONCEPTS.md`](CONCEPTS.md) §1 pour
le piège de la supersédure, qui hérite du chiffre.

**Statut** — L'état d'un atome dans son cycle de vie : `draft`, `active`, `superseded`,
`archived`, `low_confidence_archive` ; **seuls les atomes actifs remontent au rappel**. Un
atome naît toujours `active` (l'API n'accepte pas de statut à la création) ; `DELETE`
l'archive au lieu de l'effacer.

**W-008** — L'avertissement que l'API joint à une écriture dont la base a changé le statut :
l'atome vient de naître **hors du rappel**. Il ne refuse rien — la réponse reste un `201` —
et il est conservé dans `arac.audit_log`. C'est le seul signal du piège de la supersédure
sous 70.

**Superseded (remplacé)** — Le statut d'un atome révisé ; ARAC ne supprime jamais une
décision, il la remplace en gardant le lien vers celle qui lui succède.

**Taxonomie** — Votre arbre de scopes, décidé pendant l'entretien, source unique dont
découlent l'énumération Python, la table des scopes et les validations ; la modifier plus
tard est une migration, pas un renommage.

**TOTP** — Le code à usage unique à six chiffres, renouvelé toutes les trente secondes,
exigé en plus du mot de passe pour ouvrir le cockpit.

**Tranche** — La portion d'une conversation présentée au modèle pendant un cycle ; une
conversation trop grosse avance d'une tranche par cycle plutôt que d'exploser le budget.

**Tunnel** — La liaison SSH qui fait qu'un port de votre machine est un port du serveur ;
elle existe pour que l'API et le cockpit n'aient **aucune adresse publique**.

**Vecteur** — Voir *Embedding*.

**Verdict** — La conclusion d'une sonde : `OK`, `WARNING`, `CRITICAL`, ou `UNKNOWN` ;
`UNKNOWN` (base injoignable) n'est jamais confondu avec `CRITICAL`, parce que réparer un
réseau et soigner un cerveau ne sont pas le même geste.

---

| Pour approfondir | Lire |
|---|---|
| Atome, scope, embedding, rappel, preuve | [`CONCEPTS.md`](CONCEPTS.md) |
| La chaîne complète, maillon par maillon | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Le pari de fond | [`PHILOSOPHIE.md`](PHILOSOPHIE.md) |
| Le pont Mac ↔ serveur | [`PONT-MAC.md`](PONT-MAC.md) |
| Surveiller et réparer | [`EXPLOITATION.md`](EXPLOITATION.md) |
| Sauvegarder et restaurer | [`SAUVEGARDE.md`](SAUVEGARDE.md) |
