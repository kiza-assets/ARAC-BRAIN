# `deploy/ssh/` — la seule porte du cerveau

Votre cerveau n'a pas de façade sur l'Internet. L'API et le cockpit écoutent
sur `127.0.0.1` et rien d'autre : depuis le réseau, ils n'existent pas. La
seule porte est SSH.

Ce dossier contient donc la totalité de la surface exposée **au réseau**. Il ne
contient pas toute la défense : sur la machine elle-même, `127.0.0.1` est un
couloir partagé par tous les comptes locaux, et c'est le **jeton porteur** qui
y fait la porte — exigé de toute requête, boucle locale comprise
([`app/auth.py`](../../app/auth.py)). Deux fichiers :

| Fichier | Où il va | Ce qu'il décide |
|---|---|---|
| `99-arac-pont.conf` | gabarit — rendu en `/etc/ssh/sshd_config.d/99-arac-<base>-pont.conf` | ce que le serveur accepte |
| `rendre-pont.sh` | rend le gabarit aux valeurs de CE cerveau, et refuse d'écraser | l'installation du fragment |
| `authorized_keys.modele` | `~/.ssh/authorized_keys` du compte de tunnel | ce que VOTRE clé peut faire |

---

## Pourquoi un tunnel plutôt qu'une adresse publique

C'est la question qu'on se pose une fois, et qu'on regrette d'avoir mal
tranchée pendant des années.

Le cockpit est en **lecture seule**. Cette phrase rassure, et c'est
exactement le piège : lecture seule ne veut pas dire sans conséquence. Le
cockpit donne à voir tout ce que votre cerveau a appris de vous — vos
projets, vos proches, vos décisions, vos échecs, vos habitudes, datés et
interrogeables. Personne ne peut rien y modifier ; n'importe qui pourrait
tout y lire.

Publier cela derrière un mot de passe, c'est parier que ce mot de passe, ce
certificat, cette version de serveur web et **toutes celles à venir**
tiendront aussi longtemps que vos souvenirs comptent. Le pari est perdu
d'avance : votre mémoire dure des décennies, une pile logicielle non.

Le tunnel ne fait pas ce pari. Il n'y a pas de port à attaquer, pas de page
de connexion à deviner, pas de version à surveiller. Il y a une clé, et cette
clé n'ouvre que deux ports.

**Le coût, dit honnêtement :** pas de cockpit depuis un téléphone en
déplacement sans ouvrir d'abord un tunnel. Pas d'accès depuis une machine où
vous ne pouvez pas installer votre clé. C'est le prix, et il est bas.

---

## Installer, dans l'ordre

**1. Un compte dédié au tunnel** — pas votre compte d'administration.
Si sa clé fuit, elle ne doit hériter de rien. **Son nom porte celui du
cerveau** : deux `Match User pont` sur une même machine, et `sshd` n'applique
que le premier — le durcissement du second n'existe pas.

```bash
BASE=<votre base>      # sudo grep '^ARAC_DB=' /etc/arac/*/arac.env
sudo adduser --disabled-password --gecos "" "pont-$BASE"
sudo -u "pont-$BASE" mkdir -p "/home/pont-$BASE/.ssh"
sudo -u "pont-$BASE" chmod 700 "/home/pont-$BASE/.ssh"
```

**2. La clé, côté machine source** — `mac/arac-pont.sh cle-ssh` fabrique une
clé ed25519 dédiée et vous affiche la ligne `authorized_keys` exacte, déjà
bridée. Copiez-la telle quelle.

```bash
sudo -u pont tee -a /home/pont/.ssh/authorized_keys   # collez, Ctrl-D
sudo -u pont chmod 600 /home/pont/.ssh/authorized_keys
```

**3. Le durcissement du serveur** — ne recopiez pas le gabarit : **rendez-le**.
`rendre-pont.sh` lit les valeurs retenues par l'installation (le compte, les
deux ports) dans `/etc/arac/<base>/arac.env`, et écrit un fichier dont le nom
porte le cerveau.

```bash
sudo ./deploy/ssh/rendre-pont.sh            # montre, n'écrit rien
sudo ./deploy/ssh/rendre-pont.sh --poser    # → 99-arac-<base>-pont.conf
sudo sshd -t                    # TESTER avant de recharger. Toujours.
sudo systemctl reload ssh
```

> `/etc/ssh/sshd_config.d/` appartient à la **machine**, pas à un cerveau. Un
> `cp` sous le nom fixe `99-arac-pont.conf` — ce que ce fichier disait de
> faire — remplaçait le fragment du cerveau déjà installé : son `PermitOpen`
> disparaissait avec son tunnel, ou, si les comptes différaient, son bloc
> `Match` entier, `ForceCommand` compris. `rendre-pont.sh` **refuse** d'écraser
> un fichier existant et vous dit comment le comparer avant de décider.

> **Gardez une session SSH ouverte** pendant toute cette étape, et testez la
> reconnexion depuis un **second** terminal avant de fermer le premier. Une
> erreur de syntaxe dans ce fichier, un `reload`, et la seule porte se
> referme sur vous.

**4. Vérifier que le bridage mord** — les commandes sont dans
`authorized_keys.modele`, section « vérifier ». Deux d'entre elles doivent
**échouer** : c'est le test.

---

## Le port qui reste occupé — la panne qui rend fou

Un Mac se met en veille. Sa session TCP ne se ferme pas : elle se tait. Le
serveur continue de la croire vivante et garde ses redirections. Au réveil,
`autossh` se reconnecte, demande les mêmes ports, et le serveur répond qu'ils
sont pris. Par lui-même. Indéfiniment.

Le symptôme : `Warning: remote port forwarding failed for listen port ...`
ou un tunnel qui « tourne » sans que rien n'arrive.

La correction est dans `99-arac-pont.conf` : `ClientAliveInterval 30` et
`ClientAliveCountMax 3`. Le serveur sonde le client, et libère la session
morte après quatre-vingt-dix secondes de silence. Sans ces deux lignes, il
faut aller tuer le processus à la main, à chaque veille.

---

## Ce que ce dossier ne fait pas

* **Il n'expose rien en HTTPS.** Voir `deploy/nginx/README.md` : le framework
  ne fournit pas de site web public, et explique pourquoi.
* **Il ne bannit pas les adresses hostiles.** `fail2ban` est utile, et c'est
  une décision à prendre séparément — avec son propre risque, celui de se
  bannir soi-même.
* **Il ne déplace pas le port de SSH.** Ça réduit le bruit des journaux, pas
  le risque. Faites-le si vous voulez ; ce n'est pas de la sécurité.
