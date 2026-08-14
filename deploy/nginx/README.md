# `deploy/nginx/` — le serveur web que ce framework n'installe pas

Il n'y a pas de configuration nginx active dans ce dépôt, et c'est une
décision, pas un oubli.

## Pourquoi rien

L'API et le cockpit écoutent sur `127.0.0.1`. Il n'y a donc **rien à mettre
devant** : un reverse proxy ne sert qu'à rendre public ce qui ne l'est pas.
Chaque brique ajoutée ici est une brique à maintenir, à mettre à jour et à
surveiller pendant toute la vie de votre cerveau — pour un bénéfice qui se
résume, la plupart du temps, à s'épargner un `ssh -N -L`.

Le rapport est mauvais. Le tunnel gagne.

## Le seul cas où un proxy se défend

Une machine source qui ne peut pas tenir un tunnel : un poste d'entreprise
verrouillé, un réseau qui coupe SSH sortant, un appareil sur lequel vous ne
pouvez rien installer.

Dans ce cas — et **uniquement** dans ce cas — on peut exposer l'**ingestion**,
et elle seule. Le fichier `ingest-tls.conf.exemple` montre à quoi cela
ressemble : un seul chemin ouvert, `POST /v1/ingest/messages`, en TLS, avec
une limite de débit.

Ce qui n'est **jamais** exposé, dans aucun cas :

* le **cockpit** — il donne à lire toute votre mémoire ;
* les routes de **lecture** de l'API — même chose, sans l'interface ;
* PostgreSQL — cela va sans dire, mais cela va mieux en le disant.

## Le prix, dit avant

Ouvrir l'ingestion, c'est :

* un certificat à renouveler, et un service qui casse quand il expire ;
* un port ouvert que le monde entier balaiera dans l'heure ;
* un jeton porteur qui devient la seule chose entre l'Internet et l'écriture
  dans votre mémoire — un jeton qui fuit, et n'importe qui peut nourrir
  votre cerveau de ce qu'il veut ;
* une pile logicielle de plus à tenir à jour, pour toujours.

Le tunnel n'a aucun de ces quatre coûts. Si vous hésitez, prenez le tunnel :
on peut toujours ouvrir plus tard, on ne referme jamais ce qui a fuité.
