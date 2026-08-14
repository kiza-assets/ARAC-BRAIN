# Décisions d'architecture

Ce document dit **pourquoi** ARAC est fait comme il est fait. Pas comment — cela,
[`docs/ARCHITECTURE.md`](ARCHITECTURE.md) s'en charge. Ce qu'il **ne sait pas
encore** faire est en [`docs/LIMITES-CONNUES.md`](LIMITES-CONNUES.md), seul endroit
où vit une limite assumée ; les décisions ci-dessous y renvoient plutôt que de la
redire.

Chaque décision porte le problème qu'elle résout, ce qui a été écarté, et le prix
qu'elle coûte. Une décision sans prix écrit est une décision qu'on n'a pas prise :
on a seulement suivi la pente.

Plusieurs de ces décisions sont nées d'un incident réel. Elles le disent.

> **Pourquoi ce fichier ne s'appelle pas `docs/DECISIONS.md`, et pourquoi ses
> entrées sont `DA-` et non `D-`.** Il a d'abord porté ce nom-là, et cela cassait
> deux choses à la fois. D'une part, `docs/DECISIONS.md` est un chemin **réservé
> au lecteur** : le cockpit l'indexe pour peupler sa page « Décisions »
> (`control_center/collectors/reports_council.py`), et il propose au lecteur d'y
> écrire les siennes, au format `### D-001 — ce que vous avez tranché`. Livrer nos
> décisions à cet endroit revenait à afficher, dans le cockpit d'un inconnu, les
> arbitrages de quelqu'un d'autre présentés comme les siens — et à les faire
> écraser le jour où il écrirait vraiment son registre. D'autre part, le garde F1
> interdit la forme `D-NN` dans les pages livrées, parce qu'elle a longtemps servi
> à citer un registre privé que personne ne pouvait ouvrir : le déposer tel quel
> rendait `make test` **rouge sur un clone neuf**, c'est-à-dire au tout premier
> geste que le README demande à un inconnu. Le nom et la numérotation ont donc
> changé ; rien du contenu.

---

## Les fondations

### DA-01 — La mémoire naît des conversations, pas des notes

**Le problème.** Une note est ce qu'on a eu le temps d'écrire. Une conversation
est ce qu'on a réellement pensé — avec les hésitations, les raisons, les pistes
écartées. Or ce sont les raisons qui manquent six mois plus tard, et on ne prend
jamais de notes sur ses raisons.

**Écarté.** Un éditeur de notes assisté, où l'utilisateur écrit et le système
range. C'est le modèle d'Obsidian et de ses cousins ; il est meilleur qu'ARAC si
c'est ce que vous voulez.

**Le prix.** Une conversation est brute, longue, pleine de bruit. Il faut la
trier, ce qui coûte des jetons et introduit un jugement automatique sur ce qui
mérite d'être retenu. **Vous acceptez qu'une machine décide de ce dont vous vous
souviendrez.** C'est le pari central du produit, et il n'est pas neutre.

### DA-02 — Un souvenir est une affirmation autonome, pas un passage retrouvé

**Le problème.** Un moteur de recherche vectoriel rend des passages : il vous
ramène à la conversation. Ce n'est pas se souvenir, c'est retrouver.

**La décision.** L'unité de mémoire est l'**atome** : une affirmation qui tient
sans son contexte, datée, sourcée, rangée dans un domaine, portant une confiance
et une provenance remontant jusqu'à la conversation d'origine.

**Le prix.** L'extraction est un travail de modèle, donc payant et faillible.
Un atome mal formé est un souvenir faux qui a l'air vrai — d'où DA-09.

### DA-03 — La taxonomie est fermée, et déclarée par l'utilisateur

**Le problème.** Un rangement libre se fragmente. En six mois, on obtient
`finance`, `Finance`, `argent`, `budget` — et le rappel se dilue entre quatre
catégories jumelles.

**La décision.** Les domaines forment une énumération **fermée**, déclarée pendant
l'entretien d'installation. Un domaine hors de la liste est refusé par l'API (422)
et par la base (clé étrangère).

**Écarté.** L'invention à la volée, avec fusion périodique. Cela reporte le
problème sur une tâche de nettoyage que personne ne fait.

**Le prix.** Une rigidité réelle. Changer un domaine plus tard coûte une
migration, et un domaine supprimé emporte ce qu'il contenait. C'est pourquoi
l'entretien insiste tant sur ce choix.

### DA-04 — Les souvenirs vivent sur les feuilles

**Le problème.** Une racine est un conteneur, une feuille est un rangement. Un
souvenir posé sur une racine devient orphelin (voir `LIMITES-CONNUES.md` §1.4).

**La décision.** L'installation l'annonce **avant** que vous choisissiez votre
taxonomie, le générateur le répète, et la documentation le nomme « le piège le
plus coûteux du système ».

**Le prix.** On ne peut pas l'interdire mécaniquement sans casser des usages
légitimes. C'est donc une règle enseignée, pas une règle appliquée — et c'est la
seule de ce document dans ce cas.

---

## Ce que l'incident a enseigné

Le 8 août 2026, des essais du framework ont détruit l'accès au cerveau de
production de son auteur : cinq rôles PostgreSQL écrasés, un port d'API usurpé, un
service en boucle de redémarrage, et un contrôle de santé qui répondait « tout va
bien » depuis le service usurpateur. Aucune donnée n'a été perdue ; l'accès l'a été
pendant plusieurs heures.

*Ce récit est un **témoignage**, pas une mesure : il porte sur une machine que ce
dépôt ne peut pas interroger, et rien ici ne le rejoue. C'est dit parce que le
dépôt s'interdit ailleurs les chiffres qu'on ne peut pas reproduire — un compte de
redémarrages y figurait, il a été retiré. Ce qui **est** vérifiable, c'est la
mécanique : les rôles PostgreSQL sont globaux au cluster, et deux installations
qui ne se nomment pas se les disputent. La démonstration tient en une ligne :*

```
Rejouer :  grep -n "les cinq rôles s'appelaient" bootstrap/lib/config.sh
Critère :  le code porte lui-même la convention et la raison qui l'impose.
```

Les cinq décisions suivantes en sont nées. Elles ne sont pas des précautions
ajoutées après coup : elles corrigent des défauts qui auraient frappé **n'importe
quel utilisateur possédant deux cerveaux** — et deux installations posées côte à
côte l'ont démontré depuis, sans incident.

### DA-05 — Tout ce qu'une installation pose porte le nom de son cerveau

**Le problème.** Les rôles PostgreSQL sont **globaux au cluster**, pas propres à
une base. `arac_app` créé pour le cerveau A **est** `arac_app` du cerveau B. Une
seconde installation change le mot de passe et détruit l'accès de la première,
silencieusement, sans erreur.

**La décision.** Rôles, base, comptes système, ports, unités, minuteries,
journaux, sauvegardes, coffres et fichiers d'état sont **dérivés du nom du
cerveau**. Convention retenue pour les rôles : `arac_<base>_<fonction>`.

**Écarté.** Un préfixe configurable seul : il laisse le défaut ouvert par défaut,
et c'est le défaut qui blesse.

**Le prix.** Des noms plus longs, et une troncature avec empreinte au-delà de la
limite système — sans quoi deux noms voisins reformeraient une collision au
soixante-troisième caractère.

### DA-06 — On ne réutilise jamais ce qu'on n'a pas créé

**La décision.** Chaque rôle créé reçoit une **plaque de propriété** lisible
(`COMMENT ON ROLE`), qui nomme le cerveau et son coffre. Le bootstrap **refuse**
un rôle qu'il ne reconnaît pas, **avant toute écriture**, et n'exécute
**jamais** `ALTER ROLE … PASSWORD` sur un rôle préexistant — sous aucun drapeau.

C'est l'instruction exacte qui a détruit la production.

**Le prix.** Une réinstallation légitime doit s'authentifier auprès de sa propre
plaque. Le refus dit ce qu'il a trouvé, ce qu'il attendait, et le geste.

### DA-07 — Un contrôle vérifie **qui** répond, jamais qu'on lui réponde

**Le problème.** Pendant l'incident, `/healthz` répondait 200 — depuis le service
usurpateur. La mesure la plus rassurante du diagnostic était la plus fausse.

**La décision.** Le contrôle de santé remonte la socket jusqu'au processus, lit son
environnement, et compare l'identité du cerveau. Un port est vérifié **libre avant
d'être lié**, et « je n'ai pas pu vérifier » n'est jamais rendu comme « c'est
bon » ni comme « c'est cassé ».

**Généralisation.** Aucun contrôle du dépôt ne conclut sur une sortie vide.

---

## Sécurité

### DA-08 — Le cockpit ne peut pas écrire

**La décision.** Le cockpit se connecte avec un rôle en lecture seule et n'expose
**aucune route d'écriture**, sauf la connexion. Chaque métrique porte la requête
SQL qui la produit, rejouable à la main.

**Pourquoi.** Un observatoire qui peut modifier ce qu'il observe finit par le
modifier. Et une métrique dont on ne peut pas rejouer le calcul est une opinion.

**Le prix.** Aucune correction ne se fait depuis l'écran. C'est délibéré, et la
documentation cesse désormais de promettre l'inverse — elle l'a promis longtemps,
et c'était faux.

### DA-09 — Aucun texte n'est produit librement

**La décision.** Le cockpit et les rapports n'engendrent pas de phrases : ils
assemblent des gabarits à partir de valeurs mesurées et de leurs sources. Une
donnée absente est affichée comme **indisponible**, avec sa raison — jamais comme
un zéro.

**Pourquoi.** Un système de mémoire qui invente une phrase plausible détruit la
seule chose qu'il vend : la confiance dans ce qu'il rend.

### DA-10 — Le jeton est exigé, y compris en boucle locale

**Le problème.** Le raisonnement d'origine tenait, et cette page le cite pour
dire qu'il est **périmé** : le service n'écoute que sur la boucle locale, la
boucle locale n'est joignable qu'après le tunnel SSH, donc le tunnel est
l'authentification. Chaque prémisse était vraie. La conclusion, elle, **n'est
plus** celle du produit : elle supposait une quatrième proposition que personne
n'avait écrite — *atteindre `127.0.0.1` exige d'avoir franchi SSH*. **Sur une
machine à deux cerveaux, tout compte local lit la mémoire du voisin et y écrit,
sans un seul secret.** Mesuré.

**La décision.** Le jeton est exigé de toute requête, `127.0.0.1` compris. Seul
`/healthz` reste public. Le desserrage existe mais exige **deux** variables : la
valeur **et** un motif daté, écrit.

**Pourquoi deux.** Ce qui a laissé cette porte ouverte n'est pas une valeur mal
choisie : c'est une valeur **implicite**, que personne n'avait écrite, donc que
personne ne pouvait relire. Le bootstrap écrit désormais la posture dans le coffre
alors même qu'elle est le défaut du moteur : une posture qu'on peut relire est une
posture qu'on peut contester.

**Le prix.** Tout appelant doit porter son jeton. Onze l'ont appris d'un coup.

### DA-11 — Le journal ne porte que des empreintes

**Le problème.** Après une désinstallation complète et un verdict « propre », le
journal système rendait encore des clés et des domaines de souvenirs. Personne ne
pense à chercher sa mémoire dans un journal système.

**La décision.** Rien de lisible ne part dans le journal : ni clé, ni domaine, ni
titre, ni fragment, ni message d'exception issu d'une donnée. Des empreintes
(`sha8:…`), stables donc corrélables, illisibles donc inoffensives.

**Pourquoi ce niveau.** Parce que `systemd` ne sait pas purger une seule unité
(voir `LIMITES-CONNUES.md` §3.1). Ce qu'on écrit dans le journal doit pouvoir y
rester : la bonne question n'était pas « comment l'effacer » mais **« fallait-il
l'écrire »**.

**Le prix.** Un diagnostic un peu plus long : on corrèle par empreinte au lieu de
lire. Le garde qui l'impose enveloppe la fabrique d'enregistrements du journal —
seul endroit qui couvre les modules chargés plus tard.

---

## Comment le dépôt se garde lui-même

Ces trois décisions n'ont pas d'effet direct pour vous. Elles expliquent pourquoi
le dépôt tient dans le temps, et elles ont été apprises à répétition.

### DA-12 — Un garde décrit une **forme**, jamais une liste

**Le problème.** Cinq fois, un garde a laissé passer un défaut parce qu'il
énumérait : une liste de dossiers, puis de suffixes, puis de noms d'unités, puis
d'outils. **Une énumération oublie par construction**, et sa vertu apparente
retarde la découverte.

**La décision.** Chaque garde répond par une propriété mesurable, pas par une
appartenance :
- *« cet outil peut-il exécuter ce qu'on lui donne ? »* → lecture de la table des
  symboles dynamiques du binaire, qui a trouvé trois exécutants que personne
  n'avait nommés ;
- *« ce fichier porte-t-il la mémoire de ce cerveau ? »* → lecture de ses premiers
  octets puis de l'empreinte d'installation qu'il contient, jamais de son nom ;
- *« ce chemin sort-il du périmètre ? »* → ce que le noyau **atteint**, pas ce qui
  est **écrit**.

### DA-13 — On ne recopie pas ce qu'on surveille : on va le lire

**Le problème.** Trois fois, deux listes tenues en deux endroits ont divergé — et
le juge accusait la documentation d'une omission qu'elle n'avait plus.

**La décision.** Le garde du journal lit les lignes de commande dans les unités
qu'il surveille. Le juge d'acceptation lit la procédure de désinstallation dans la
page qui la prescrit. Le contrôle de départ lit l'empreinte dans le dump.

### DA-14 — Une preuve doit pouvoir échouer, et une mesure doit pouvoir vieillir

**Le problème.** Un test affirmait l'immuabilité d'un champ par
`assert "confidence" not in …` — le champ s'appelle `confidence_score`.
L'assertion était **vraie de toute éternité** et ne prouvait rien. Elle a survécu
à six manches d'audit **parce qu'elle était verte**.

**La décision.** Une assertion négative doit porter sur un nom qui existe
réellement quelque part ; un tableau « vérifié » doit porter la méthode qui le
prouve, et cette méthode est rejouée ; une affirmation datée porte sa **date**, sa
**commande** et un **critère** qui survit au changement de chiffre.

**Corollaire, appris deux fois.** Une justification est une affirmation comme une
autre. Deux exceptions ont été trouvées fausses **le jour même de leur écriture** —
dont une qui affirmait qu'une clé privée « ne vit pas là », à l'endroit exact où
elle vit. Le dépôt écrit donc **moins** de justifications, et mesure chacune.

---

## Ce que nous n'avons pas décidé

Trois questions restent ouvertes, et nous préférons le dire que trancher vite.
Les trois ont leur conséquence pratique décrite dans
[`docs/LIMITES-CONNUES.md`](LIMITES-CONNUES.md) — §1.1, §1.5 et §1.2 : ici le
raisonnement, là ce que ça change pour vous.

**Faut-il détecter les contradictions ?** Techniquement possible ; le coût en
jetons et le risque de faux positifs sont inconnus. Un cerveau qui vous
contredirait à tort serait pire qu'un cerveau qui se tait.

**Faut-il faire vieillir les souvenirs ?** Les colonnes existent. Personne ne sait
encore ce qu'un savoir « périmé » veut dire pour un humain : une décision de 2024
peut être dépassée ou structurante, et rien dans le texte ne le dit.

**Faut-il que la confiance pondère le rappel ?** Un module qui le ferait est écrit
(`app/services/context_router.py`), et **aucune route servie ne l'importe** : il
n'y a pas de drapeau à lever, il n'y a pas de chemin. Nous ne le branchons pas
parce que nous ne savons pas encore si le score mesure ce qu'on croit qu'il
mesure. *(Cette page a d'abord écrit « le chemin existe, derrière deux drapeaux ».
C'était faux dans le sens dangereux : cela laissait croire à un réglage
à trouver.)*
