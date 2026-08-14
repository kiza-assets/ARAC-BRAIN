# `deploy/` — ce qui se pose sur le serveur

Ce dossier contient les pièces qui vivent **hors du dépôt** une fois
installées : configuration SSH, unités systemd, exemples de reverse proxy.
Toutes sont des **gabarits** : elles portent des marqueurs à remplacer et
aucun chemin réel. Rien ici ne s'installe tout seul.

| Chemin | Ce que c'est | État |
|---|---|---|
| `ssh/99-arac-pont.conf` | durcissement sshd + libération des tunnels morts | gabarit, non testé sur votre machine |
| `ssh/authorized_keys.modele` | la clé du pont, bridée à deux ports | gabarit |
| `ssh/README.md` | pourquoi un tunnel et pas une adresse publique | à lire avant d'installer |
| `systemd/arac-pont-sans-mac.{service,timer}.modele` | la synchronisation quand il n'y a pas de Mac | gabarit |
| `nginx/README.md` | pourquoi ce framework n'installe aucun serveur web | à lire |
| `nginx/ingest-tls.conf.exemple` | le seul cas où un proxy se défend | exemple non testé |

## Ce qui n'est PAS ici

**Les unités systemd du cerveau lui-même** — API, cockpit, cycle de
digestion, sauvegardes. Elles ne sont pas des fichiers : elles sont
**engendrées** par `bootstrap/bootstrap.sh` à partir de votre
`config/brain.toml`. Leurs noms portent celui de votre cerveau, pour que deux
cerveaux sur la même machine ne se marchent jamais dessus.

C'est voulu, et c'est la même règle partout dans ce dépôt : ce qui dépend de
votre identité est engendré, jamais recopié. Un gabarit figé dans `deploy/`
finirait par mentir sur ce qui tourne réellement.

Pour voir ce que le bootstrap a écrit :

```bash
systemctl cat <votre-prefixe>-api.service
```

## L'ordre d'installation

1. Le cerveau — `bootstrap/bootstrap.sh` (base, rôles, migrations, services).
2. La porte — `ssh/`, sur le serveur.
3. Le pont — `mac/arac-pont.sh`, sur la machine où vous parlez à Claude.

Le pont vient en dernier : il n'a rien à traverser tant qu'il n'y a personne
de l'autre côté. Tout est raconté de bout en bout dans `docs/PONT-MAC.md`.
