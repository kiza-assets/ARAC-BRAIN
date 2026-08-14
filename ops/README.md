# `ops/` — garder le cerveau

Un cerveau qu'on perd n'était pas un cerveau. Ce répertoire contient tout ce qui
fait qu'une installation survit à une panne de disque, à une erreur de commande,
à un mois d'inattention.

| Fichier | Ce qu'il fait | Sans base ? |
|---|---|---|
| `env.sh` | le socle : où est l'installation, comment on lui parle, comment on alerte | oui, il ne fait rien seul |
| `backup.sh` | le dump — **quatre fois par jour**, `00,06,12,18:30 UTC` — ses quatre contrôles, le chiffrement, la rotation | non |
| `backup_toc_check.sh` | vérifie qu'un dump contient les tables vitales — **fonction pure** | **oui** (`selftest`) |
| `restore_guard.sh` | les garde-fous de la restauration — **fonctions pures** | **oui** (`selftest`) |
| `restore_verify.sh` | **restaure vraiment** dans une base jetable et prouve le contenu | non |
| `backup_offsite.sh` | pousse les artefacts chiffrés ailleurs, vérifie à l'arrivée | non |
| `watchdog.sh` | surveille la *garantie* de sauvegarde, pas les scripts | oui |
| `install_check.sh` | l'installation tient-elle debout ? une trentaine de contrôles | partiellement |
| `systemd/` | les gabarits de planification, à lire avant d'armer | oui |

Deux scripts complètent l'ensemble, côté Python :
`scripts/ops/health_check.py` (le verdict, depuis les 148 métriques du cockpit)
et `scripts/ops/alerts.py` (les quatre alarmes qui doivent chercher un humain).

**Documentation :** [`docs/SAUVEGARDE.md`](../docs/SAUVEGARDE.md) ·
[`docs/EXPLOITATION.md`](../docs/EXPLOITATION.md)

---

## Éprouver ce répertoire sans rien installer

```bash
bash ops/backup_toc_check.sh selftest    # dont le piège du préfixe de nom
bash ops/restore_guard.sh selftest       # cible interdite, injection, médiane
for f in ops/*.sh ops/systemd/*.sh; do bash -n "$f" || echo "SYNTAXE : $f"; done
```

**Ce que vous devez voir**, et c'est tout le critère : la dernière ligne de chacun
des deux auto-tests, `backup_toc_check : tout passe.` et
`restore_guard : tout passe.`, en **code de sortie 0** — et aucune ligne `SYNTAXE :`.
Le **nombre** de cas n'est écrit ici nulle part, délibérément : chaque auto-test
imprime les siens et les compte lui-même. Cette page a annoncé « 21 cas » quand il
y en avait 25, et un lecteur qui compte les lignes trouve alors un écart là où il
n'y a rien à réparer.

Ces trois commandes tournent sur un dépôt fraîchement cloné, sans PostgreSQL,
sans réseau, sans configuration. C'est volontaire : le code qui décide de
détruire une base doit être le code le plus testable du dépôt.

---

## Le premier jour

```bash
# 0. les noms de CE cerveau — tout ce qui suit en dépend.
#    Sans ces deux lignes, les chemins ci-dessous désigneraient le cerveau du
#    voisin, et l'étape 1 lui donnerait vos droits sur SES sauvegardes.
source ops/env.sh          # pose $ARAC_BACKUP_DIR, $ARAC_BACKUP_STATE, $ARAC_BACKUP_PREFIX
#    `ops/env.sh` ne pose PAS le préfixe des unités : c'est `render.sh` qui le
#    déduit, ou vous. Le poser ici rend la ligne 5 lisible et reproductible.
export ARAC_UNIT_PREFIX="arac-$ARAC_BACKUP_PREFIX"

# 1. le répertoire des dumps, avec ses droits — 0700 n'est pas décoratif
sudo install -d -m 0700 -o "$(id -un)" "$ARAC_BACKUP_DIR"
sudo install -d -m 0700 -o "$(id -un)" "$ARAC_BACKUP_STATE"

# 2. le gabarit de restauration (une fois, en superutilisateur)
# `--prepare-template` IMPRIME la commande complète, port compris : lisez-la,
# puis recopiez-la. Sans « -p », psql s'adresse à la grappe par défaut de la
# machine — et ce bloc commence par un DROP DATABASE.
ops/restore_verify.sh --prepare-template

# 3. une sauvegarde, tout de suite, à la main
ops/backup.sh

# 4. et sa preuve, tout de suite aussi
ops/restore_verify.sh

# 5. seulement maintenant, la planification de CE QUE LE BOOTSTRAP N'ARME PAS
#    La sauvegarde et la restauration vérifiée sont déjà armées par lui
#    (`<prefixe>-sauvegarde`, `<prefixe>-restauration`) : ce répertoire ne rend
#    que le reste — chien de garde, santé, contrôle d'installation, hors site.
#    Le dossier de sortie porte lui aussi le nom du cerveau : /tmp est commun à
#    la machine, et render.sh refuse désormais d'écrire dans un dossier qui ne
#    vous appartient pas — ce qu'on y dépose finit en root dans /etc.
ops/systemd/render.sh "/tmp/arac-units-$ARAC_UNIT_PREFIX" \
  && less "/tmp/arac-units-$ARAC_UNIT_PREFIX/$ARAC_UNIT_PREFIX-health.service"

# et pour lire celles que le bootstrap a posées :
systemctl cat "$ARAC_UNIT_PREFIX-sauvegarde.service" "$ARAC_UNIT_PREFIX-restauration.service"
```

L'ordre compte. Armer un minuteur avant d'avoir vu la commande réussir une fois
à la main, c'est déléguer un problème qu'on n'a pas encore.

---

## Les variables

Aucune n'est un chemin écrit en dur — et **aucun défaut n'est commun à la
machine** : tout ce qui désigne un endroit porte le nom de VOTRE base, lu par
`ops/env.sh` dans `config/brain.toml`. C'est la différence entre deux cerveaux
qui cohabitent et deux cerveaux dont la rotation de sauvegarde efface les dumps
de l'autre.

`<base>` ci-dessous, c'est `brain.name` assaini : minuscules, tout ce qui n'est
ni lettre ni chiffre devenu `_`. Sans `config/brain.toml`, les trois chemins de
sauvegarde restent **vides** et les scripts disent ce qui manque : `ops/env.sh`
ne devine pas un dossier commun « en attendant ».

| Variable | Défaut | Ce qu'elle décide |
|---|---|---|
| `ARAC_HOME` | le dépôt | où vit l'installation |
| `ARAC_ENV_FILE` | résolu en cinq rangs — voir « Quel cerveau ces scripts servent-ils ? » ci-dessous | où sont les secrets, **et donc quel cerveau est servi** |
| `ARAC_BACKUP_DIR` | `/var/backups/arac/<base>` | où atterrissent les dumps |
| `ARAC_BACKUP_STATE` | `/var/lib/arac/<base>/backup` | reçus, preuves, registres |
| `ARAC_BACKUP_PREFIX` | `<base>` | le préfixe des dumps, et le motif de rotation |
| `ARAC_UNIT_PREFIX` | *(vide — `render.sh` déduit `arac-<base>`)* | le préfixe des unités engendrées ici. `ops/env.sh` ne le pose **pas** : posez-le vous-même si vous l'utilisez dans vos propres chemins |
| `ARAC_DB_SCHEMA` | `arac` | le schéma sauvegardé |
| `ARAC_BACKUP_DSN` | `DATABASE_URL_BACKUP`, sinon `_ADMIN` | avec quel rôle on dumpe |
| `ARAC_BACKUP_RETENTION_DAYS` | `7` | rétention locale |
| `ARAC_BACKUP_KEEP_MIN` | `3` | dumps gardés quoi qu'il arrive |
| `ARAC_BACKUP_RECIPIENTS` | *(vide)* | clés publiques age → chiffrement au repos |
| `ARAC_BACKUP_CLEAR_LOCAL` | `1` | garder le dump en clair à côté du chiffré |
| `ARAC_BACKUP_IDENTITY` | *(vide)* | clé privée, pour restaurer depuis un chiffré |
| `ARAC_OFFSITE_DEST` | *(vide)* | `utilisateur@machine` de la copie hors site — **vide par défaut, et c'est une limite assumée** : voir [`docs/LIMITES-CONNUES.md`](../docs/LIMITES-CONNUES.md) §3.4 |
| `ARAC_RESTORE_TEMPLATE_DB` | `<base>_restore_template` | le gabarit sans superutilisateur |
| `ARAC_RESTORE_FRESHNESS_H` | `26` | retard toléré du dump sur le vivant |
| `ARAC_ALERT_CMD` | *(vide)* | **comment un humain est prévenu** — vide par défaut, même raison, même renvoi : personne d'autre que vous ne peut décider *vers qui* |

Les seuils du chien de garde (`ARAC_WD_*`) et des alarmes (`ARAC_ALERT_*`) sont
documentés là où ils vivent : `ops/watchdog.sh --explain` et
`scripts/ops/alerts.py --explain`.

### Quel cerveau ces scripts servent-ils ?

C'est la seule question qui puisse coûter une mémoire, et `ops/env.sh` y répond
en **cinq rangs**, écrits en toutes lettres au-dessus de son code :

1. `ARAC_ENV_FILE` posée → **on obéit, en silence.** C'est une désignation, et
   c'est le rang des unités systemd, qui la portent dans leur définition.
2. `$ARAC_HOME/.env` lisible → on le prend, en silence. Un dépôt n'a qu'un `.env`.
3. **un seul** coffre sur la machine → on le prend, en silence — sauf si ce dépôt
   décrit un AUTRE cerveau : ce n'est pas une ambiguïté, c'est un désaccord, et
   il **arrête**.
4. plusieurs coffres, et ce dépôt en décrit un qui existe → on le prend **et on
   le dit**, sur la sortie d'erreur, avant le premier geste : quel cerveau, quel
   coffre, sur quelle preuve, combien de candidats, et la ligne exacte pour en
   désigner un autre.
5. tout le reste → **arrêt avant tout geste**, code 1, avec la raison et la liste
   des coffres prêts à recopier.

La règle tient en une phrase : **on n'agit jamais sur un cerveau que personne n'a
nommé.** Ou bien vous le nommez (rang 1), ou bien l'outil le nomme tout haut avant
d'agir (rang 4). Le rang 4 n'a pas toujours existé : ces scripts ont longtemps
**refusé** dès qu'il y avait deux cerveaux, puis ont **choisi en silence**, et
sept pages du manuel ont continué de promettre le refus. Le tableau complet, avec
les sorties telles quelles, est au § 9 de
[`docs/CONFIGURATION.md`](../docs/CONFIGURATION.md).

**Conséquence pratique : le dossier d'où vous tapez décide.** Un clone par
cerveau (`/opt/<base>`) rend le rang 4 exact ; un clone partagé le rend faux.
Posez la variable, et la question ne se pose plus.

---

## Le principe qui gouverne tout ce répertoire

**Constater, expliquer, ne rien réparer.** Aucun de ces scripts ne redémarre un
service, ne purge une file, ne restaure par-dessus une base vivante. Chacun dit
ce qui ne va pas et quel geste le corrige — puis s'arrête.

Un outil d'exploitation qui répare tout seul finit par cacher la panne qu'il
répare. On s'en aperçoit le jour où il n'y arrive plus, et il est alors trop tard
pour comprendre ce qui se cassait depuis six mois.
