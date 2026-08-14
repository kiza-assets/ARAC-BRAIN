# Les minuteurs — ce qui tournera sans vous

Tout ce qui est ici est un **gabarit**. Rien ne s'installe seul, rien ne s'arme
seul, et c'est délibéré : armer un minuteur systemd, c'est promettre qu'une
commande tournera en votre nom, indéfiniment, sur votre serveur. Cette promesse
se lit avant de se faire.

```bash
ops/systemd/render.sh "/tmp/arac-units-$ARAC_UNIT_PREFIX"   # substitue VOS chemins, n'installe rien
less "/tmp/arac-units-$ARAC_UNIT_PREFIX/$ARAC_UNIT_PREFIX-health.service"  # lisez ce que vous armez
```

Le rendu affiche ensuite les commandes exactes à passer. Elles ne sont pas
exécutées pour vous.

> **Le nom lu ici est celui d'un fichier que ce répertoire produit vraiment.**
> Cette ligne faisait ouvrir `…-sauvegarde.service`, que `render.sh` n'écrit
> pas : le premier geste de la page rendait « No such file or directory ». Le
> gabarit de sauvegarde ne vit pas ici — voir juste en dessous.

---

## Ce qui est ici, et ce qui n'y est PAS

**La sauvegarde et la restauration vérifiée ne sont pas des gabarits.** Le
bootstrap les arme lui-même, à son étape 9, sous les noms
`<prefixe>-sauvegarde` et `<prefixe>-restauration`. Ce répertoire a longtemps
porté deux gabarits de plus — `arac-backup` et `arac-restore-verify` — qui
appelaient exactement les mêmes scripts : **une seule implémentation, deux
familles d'unités pour l'appeler.** Les armer ne doublait pas la protection,
elle la retirait : les deux écrivaient dans le même répertoire de dumps, le
même `ops/backup.sh` y faisait sa rotation, et le gabarit d'ici ne portait pas
`ARAC_BACKUP_RETENTION_DAYS` — il retombait donc sur **7** jours là où le
bootstrap promet **14**. Armer la seconde famille effaçait, sans un mot, les
dumps de la deuxième semaine.

Ce qui reste ici est exactement ce que le bootstrap n'arme pas. Les vôtres se
lisent ainsi :

```bash
systemctl cat "$ARAC_UNIT_PREFIX-sauvegarde.service" "$ARAC_UNIT_PREFIX-restauration.service"
systemctl list-timers "$ARAC_UNIT_PREFIX-*"
```

---

## Ce que chaque unité fait, et à quelle cadence

Les deux premières lignes sont posées par le **bootstrap**, pas par ce
répertoire ; elles figurent ici parce qu'on ne comprend les autres qu'en
sachant ce qu'elles complètent.

| Unité | Posée par | Cadence | Ce qu'elle garantit |
|---|---|---|---|
| `<prefixe>-sauvegarde` | bootstrap | 00/06/12/18:30 UTC | il existe une copie d'hier |
| `<prefixe>-restauration` | bootstrap | dimanche, 03:00 UTC | cette copie **s'ouvre** et contient le cerveau |
| `<prefixe>-backup-offsite` | *ici* | toutes les 30 min | une copie chiffrée vit **ailleurs** |
| `<prefixe>-backup-watchdog` | *ici* | toutes les 30 min | quelqu'un crie quand une des trois cesse d'être vraie |
| `<prefixe>-health` | *ici* | toutes les 6 h | le cerveau apprend, rappelle, digère |
| `<prefixe>-install-check` | *ici* | lundi, 08:00 | l'installation n'a pas dérivé |

La cadence de sauvegarde est calée sur celle de la digestion : **sauvegardez
juste avant de digérer, pas juste après.** Un cycle qui tourne mal est ainsi
rejouable depuis une copie prise avant lui.

---

## Pourquoi les services sont « inactive » et pourquoi c'est normal

Un service `Type=oneshot` déclenché par un minuteur est actif quelques secondes
par jour. Le reste du temps il est `inactive`, et **ce n'est pas une panne**.
Ce qu'il faut surveiller, c'est :

```bash
systemctl list-timers 'arac-*'        # les minuteurs sont-ils armés ?
systemctl --failed | grep arac        # un passage a-t-il échoué ?
journalctl -u "$ARAC_UNIT_PREFIX-sauvegarde" -n 50   # qu'a dit le dernier passage ?
```

`ops/install_check.sh` applique exactement cette règle : il vérifie les
minuteurs, et ne signale les services que s'ils sont en échec.

---

## `SuccessExitStatus` — pourquoi certains codes non nuls sont des succès

Trois de ces unités rendent des **verdicts**, pas des résultats :

| Unité | Codes tolérés | Ce qu'ils veulent dire |
|---|---|---|
| `<prefixe>-restauration` *(bootstrap)* | 2 | restauré, mais la comparaison avec la base vivante n'a pas pu se faire |
| `<prefixe>-backup-watchdog` | 1, 2 | dégradé / critique — le chien de garde a fait son travail |
| `<prefixe>-health` | 1, 2, 3 | WARNING / CRITICAL / UNKNOWN |

Sans ces déclarations, `systemctl --failed` se remplirait d'unités qui ont
parfaitement fonctionné, et vous cesseriez de le lire. On veut pouvoir
distinguer **« le chien de garde est cassé »** de **« le chien de garde aboie »**.

---

## Le durcissement, et le piège qui va avec

Chaque unité pose `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`,
`NoNewPrivileges=yes`, et n'ouvre en écriture que les répertoires qui lui sont
nécessaires (`ReadWritePaths=`). Un script d'exploitation compromis ne peut donc
pas grand-chose de plus que son travail.

> **Piège** : `ProtectHome=yes` rend `/home` et `/root` invisibles au service.
> Si votre installation vit dans un répertoire personnel (`/home/vous/arac`),
> **le service ne démarrera pas** — le message parlera d'un exécutable
> introuvable, pas d'un répertoire protégé. Deux issues : installer sous
> `/opt/arac` (recommandé), ou retirer `ProtectHome` du gabarit en sachant ce
> que vous retirez.

`ReadWritePaths` doit lister les répertoires que le script écrit vraiment. Si
vous déplacez `ARAC_BACKUP_DIR` après avoir installé les unités, **re-rendez et
recopiez les gabarits** : sinon le service échouera sur un « read-only file
system » parfaitement légitime.

---

## Vérifier un gabarit avant de l'armer

```bash
systemd-analyze verify "/tmp/arac-units-$ARAC_UNIT_PREFIX/$ARAC_UNIT_PREFIX-health.service"  # syntaxe
systemd-analyze security "$ARAC_UNIT_PREFIX-health.service"                 # ce qui reste ouvert
```

Les neuf gabarits de ce répertoire passent `systemd-analyze verify` sans une
remarque, une fois rendus.

---

## Et si vous n'avez pas systemd

Rien ici n'est indispensable : ce sont quatre commandes lancées à heure fixe. Un
`crontab` fait le même travail, en perdant trois choses — le rattrapage après
une machine éteinte (`Persistent=true`), le journal structuré, et le
durcissement. Si vous prenez cron, gardez au moins ceci :

```cron
# <clone> et <cerveau> : CEUX DE CE CERVEAU. cron n'a ni $ARAC_UNIT_PREFIX ni
# votre environnement — recopier un chemin par habitude, c'est écrire les
# journaux de deux cerveaux dans un seul fichier, et ne plus savoir lequel a
# produit quelle ligne au moment où on cherche lequel a cassé.
# Sans systemd, le bootstrap n'a rien armé non plus : la sauvegarde et la
# restauration vérifiée sont ici, et elles n'y sont qu'ICI. Sous systemd, ces
# deux lignes-là feraient DOUBLON avec les unités du bootstrap.
0 1 * * *    cd <clone> && ops/backup.sh         >> /var/log/arac/<cerveau>/backup.log 2>&1
0 3 * * 0    cd <clone> && ops/restore_verify.sh >> /var/log/arac/<cerveau>/backup.log 2>&1
*/30 * * * * cd <clone> && ops/watchdog.sh       >> /var/log/arac/<cerveau>/backup.log 2>&1
```

Les scripts `ops/*.sh` lisent eux-mêmes `$ARAC_HOME/.env` (via `ops/env.sh`),
donc ils s'en sortent sous cron. **Les deux scripts Python, non** : ils lisent
l'environnement du processus, comme le fait tout programme lancé par systemd
avec `EnvironmentFile=`. Sous cron, il faut donc le leur donner :

```cron
# <clone> = LE dépôt de CE cerveau, et son coffre. Deux cerveaux ont deux
# clones, deux .env et deux .venv : une racine écrite en dur ici ferait
# alerter l'un avec les seuils, les DSN et les destinataires de l'autre.
0 */6 * * *  set -a; . /etc/arac/<cerveau>/arac.env; set +a; <clone>/.venv/bin/python <clone>/scripts/ops/alerts.py
```
