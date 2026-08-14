# `mac/` — le pont, côté machine source

Ces cinq fichiers font sortir vos conversations de votre machine pour les
porter, par un tunnel SSH, jusqu'à votre cerveau.

**Tout est expliqué dans [`docs/PONT-MAC.md`](../docs/PONT-MAC.md)** : la
chaîne de bout en bout, où sont réellement les conversations sur un Mac, les
pannes courantes et leur diagnostic, la liste de contrôle à exécuter, et la
liste honnête de ce qui n'a pas pu être vérifié faute de Mac.

## Les cinq gestes

```bash
./arac-pont.sh installer          # le nom du cerveau, PUIS cinq questions
                                  # → tout est posé dans ~/.arac/<cerveau>/
./arac-pont.sh cle-ssh            # la clé du tunnel, bridée côté serveur
                                  # + déposer le jeton d'ingestion
./arac-pont.sh premiere-synchro   # le trajet complet, raconté
./arac-pont.sh automatiser        # launchd prend le relais
./arac-pont.sh etat               # à tout moment : quel maillon est cassé ?
```

**`installer` demande TOUJOURS le nom du cerveau, et c'est la question 0.**
C'est le nom de sa base sur le serveur, celui du dossier `/etc/arac/<base>/`
— à vérifier par `ls /etc/arac/`. Tout en découle : le pont pose alors sa
configuration, sa copie d'`arac-sync.py`, son jeton, son curseur et son
journal **sous un foyer qui n'appartient qu'à ce cerveau**, `~/.arac/<cerveau>/`
en `0700`.

**Sans nom, il refuse et n'écrit rien** — mesuré, code de sortie `2` :

```
  × Sans nom, ce pont s'installerait dans le foyer COMMUN — ~/.arac —
  et le prochain cerveau de ce poste s'installerait par-dessus :
  même curseur, même jeton, même étiquette launchd. Rien n'a été
  fait. Reprenez avec le nom de la base de votre cerveau.
```

Ce refus n'est pas une pédanterie : deux ponts dans un foyer commun partagent
un seul curseur et un seul jeton, et c'est la seule perte silencieuse et
définitive de tout le système.

**Ce que `installer` pose réellement**, relevé sur une installation jouée pour
ce fichier. `<cerveau>` est partout le nom que vous avez donné à la question 0 —
et il n'est pas décoratif : c'est lui qui empêche deux ponts de partager un
curseur.

```
~/.arac/<cerveau>/                   (0700)
~/.arac/<cerveau>/pont.conf          (0600 — aucun secret, mais votre node_id)
~/.arac/<cerveau>/arac-sync.py       (copié, pas lié)
~/.arac/<cerveau>/journal/
~/.arac/<cerveau>/export-desktop/
~/.arac/<cerveau>/jeton_ingest       (à déposer vous-même, en 0600)
~/.arac/<cerveau>/etat-pont.json     (le curseur, écrit à la 1ʳᵉ synchro)
```

**Un poste qui pilote plusieurs cerveaux** : toutes les commandes prennent
alors `ARAC_CERVEAU=<nom>` en préfixe. Le pont ne devine pas — s'il en voit
plusieurs et qu'on ne lui dit rien, il sort en `2` plutôt que de choisir dans
quelle mémoire déposer vos conversations.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `arac-sync.py` | la synchronisation elle-même — Python standard, aucune dépendance |
| `arac-pont.sh` | installation, tunnel, diagnostic, launchd — bash 3.2, celui de macOS |
| `pont.conf.example` | le gabarit de la configuration, commenté ; `installer` le substitue et écrit le résultat en `~/.arac/<cerveau>/pont.conf` — jamais en `~/.arac/pont.conf` |
| `com.arac.pont.sync.plist.modele` | agent launchd : une passe par heure |
| `com.arac.pont.tunnel.plist.modele` | agent launchd : le tunnel permanent |

Les deux `.modele` portent des marqueurs à double arobase et **aucun chemin
réel** : `arac-pont.sh automatiser` les remplit et écrit le résultat dans
`~/Library/LaunchAgents/`. Ne les installez pas tels quels.

## Trois choses à savoir avant de lancer quoi que ce soit

**Au premier lancement, rien n'est envoyé.** Le pont liste ce qu'il a trouvé
et vous rend la main. Ces conversations contiennent une vie : vous devez voir
ce qui part avant que ça parte. `automatiser` refuse d'ailleurs de travailler
tant que cette première synchronisation n'a pas eu lieu.

**Il n'existe aucune capture automatique de Claude Desktop.** L'application
ne garde rien de lisible en local. La seule voie stable est l'export officiel
de claude.ai, qui est manuel. Claude Code (CLI), lui, est capté
automatiquement. Les raisons sont dans `docs/PONT-MAC.md`.

**Renvoyer ne coûte rien.** Le serveur déduplique par message. En cas de
doute sur un trou dans votre mémoire, le filet de sécurité — **le chemin
porte le nom de votre cerveau**, il n'y a pas de copie à la racine de
`~/.arac` :

```bash
python3 ~/.arac/<cerveau>/arac-sync.py --tout
```

Si ce poste pilote plusieurs cerveaux, nommez celui que vous rejouez :
`--cerveau <nom>` (ou `ARAC_CERVEAU=<nom>`). Avec un seul, `arac-sync.py` le
trouve seul, et il **refuse de deviner** dès qu'il y en a plusieurs. Quand il
n'est pas prêt, il ne se contente pas de se plaindre : il **nomme le fichier
qu'il a lu** — `Configuration lue dans : ~/.arac/<cerveau>/pont.conf` —, ce qui
est la seule façon de savoir à quel cerveau on parlait.

## Sans Mac

`arac-sync.py` est du Python de la bibliothèque standard : il tourne tel quel
sur Linux, y compris sur le serveur lui-même — auquel cas le tunnel devient
inutile. L'ordonnancement se fait alors par
`deploy/systemd/arac-pont-sans-mac.{service,timer}.modele`. Ce qui est perdu :
`launchctl`, `plutil`, les notifications. Ce qui ne l'est pas : tout le reste.
