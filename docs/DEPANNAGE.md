# Dépannage — classé par symptôme

On ne cherche pas une panne par composant : on la cherche par **ce qu'on voit**. Ce
document est donc rangé par symptôme.

Chaque entrée suit la même forme :

> **Ce qui se passe** — le mécanisme, pas juste le message.
> **Comment le confirmer** — une commande qui tranche.
> **Comment réparer** — le geste exact.

**Les trois commandes qui ne coûtent rien et qu'on peut lancer cent fois**, y compris
pendant un incident. Aucune n'écrit dans le cerveau, aucune ne dépense un centime :

```bash
sudo ./bootstrap/checks/verify_install.sh                      # cette installation est-elle saine ?
sudo ops/install_check.sh                                      # tient-elle debout au quotidien ?
sudo -E .venv/bin/python scripts/ops/health_check.py           # comment va le cerveau lui-même ?
```

> **`sudo` sur les trois, et il n'est décoratif sur aucune.** Les secrets d'une
> installation posée par le bootstrap vivent dans `/etc/arac/<votre_base>/`, un dossier en
> **0700 root** : sans root, ces outils ne peuvent pas seulement lire le coffre, ils ne
> peuvent même pas savoir qu'il existe. Ce qu'ils font alors, mesuré sur un cerveau
> parfaitement sain dont l'API répondait `200` à la même seconde :
>
> | sans root | ce qu'il rend | code |
> |---|---|---|
> | `bootstrap/checks/verify_install.sh` | un rapport **PARTIEL**, et il dit ce qu'il n'a pas pu voir | `0` |
> | `ops/install_check.sh` | « *CE CONTRÔLE N'A PAS PU MESURER — et il ne rendra donc aucun verdict* », suivi du geste exact | `3` |
> | `scripts/ops/health_check.py` | « *UNKNOWN : DATABASE_URL_READONLY n'est pas définie* », aucun bulletin | `3` |
>
> **La troisième ligne de ce bloc a longtemps été écrite ici sans `sudo`**, avec un
> paragraphe qui expliquait pourquoi elle n'en avait pas besoin. Elle en a besoin : elle
> lit la base avec le rôle en lecture stricte, et ce DSN est dans le coffre comme les
> autres. `ops/install_check.sh` le dit lui-même, à l'écran, quand il refuse de juger.
> Aucun de ces trois ne rend un faux diagnostic quand il ne voit pas — c'est acquis, et
> c'est ce qui rend l'oubli du préfixe rattrapable au lieu d'être trompeur.
>
> **Et sur une machine qui porte plusieurs cerveaux, `sudo` ne suffit pas.** Le script ne
> devine pas — mais il ne s'arrête pas pour autant : il sert le cerveau que **le clone
> d'où vous tapez** décrit (`config/brain.toml`) et il l'annonce avant de juger quoi que
> ce soit (« *ops/ sert le cerveau « … » — ce dépôt le décrit, il n'a pas été deviné* »,
> avec le coffre, la preuve et le nombre de candidats). Il ne s'arrête, code 1 et
> « *ARRÊT AVANT TOUT GESTE* », que si ce clone ne décrit aucun cerveau ou en décrit un
> qui n'a pas de coffre ici. **Lisez cette annonce** : c'est elle qui vous dit sur quel
> cerveau porte le verdict que vous allez lire. Et nommez le coffre vous-même —
>
> ```bash
> sudo ARAC_ENV_FILE=/etc/arac/$BASE/arac.env ops/install_check.sh
> ```
>
> C'est le §0 ci-dessous appliqué au coffre : **un chemin par défaut ne dit pas à quel
> cerveau il mène**, pas plus qu'un numéro de port — et **un dossier courant non plus**.
> Les cinq rangs de cette résolution sont au tableau d'`ARAC_ENV_FILE` de
> [`CONFIGURATION.md`](CONFIGURATION.md).

> **Une réserve qui n'en est plus une, et il vaut la peine de savoir pourquoi.** Cette page
> a longtemps mis en garde contre la section 5 d'`ops/install_check.sh` : elle balayait les
> unités systemd par le motif `arac-*`, ramassait les minuteurs de **tous** les cerveaux de
> la machine, et une unité **voisine** en échec faisait basculer le verdict de **votre**
> installation sur « ne tient PAS debout », code `2`, pour une installation qui n'avait
> rien. C'était la même faute que celle du §0, montée d'un cran : un nom d'unité ne dit pas
> à quel cerveau il mène.
>
> **Le script l'a corrigée.** Il dérive maintenant son motif de l'identité de votre cerveau
> — `ARAC_UNIT_PREFIX`, sinon `arac-<nom de votre base>-*` — et **nomme** les unités des
> autres sans jamais les compter : vous les verrez sous « *PAS LES VÔTRES* », suivies de
> « *Leur état ne dit rien du vôtre, et ne pèse pas sur le verdict ci-dessous* ». S'il ne
> peut pas savoir quelles unités sont les vôtres, il ne tranche pas : il rend un `?`.
>
> Vous pouvez le constater vous-même, et c'est la façon la plus honnête de le croire :
>
> ```bash
> systemctl list-units --plain --no-legend --type=timer 'arac-*'      | wc -l
> systemctl list-units --plain --no-legend --type=timer "arac-$BASE-*" | wc -l
> systemctl list-units --plain --no-legend --state=failed 'arac-*'    # les échecs, tous cerveaux confondus
> ```
>
> Le premier nombre est plus grand que le second dès qu'un voisin partage la machine, et
> une unité en échec dans la troisième liste ne change **rien** au verdict que la section 5
> rendra sur vous. **Sa section 5 est donc à lire comme un verdict, pas comme une liste.**

---

## 0. Les quatre valeurs dont tout le reste dépend

**Aucune commande de cette page ne contient de numéro de port.** C'est délibéré, et c'est
la leçon la plus chère de ce dépôt : le jour de l'incident, l'API de production
redémarrait pour la 35ᵉ fois sur *address already in use* — et le contrôle de santé
répondait `200`. Il interrogeait un **numéro**, et un numéro ne dit pas à quel cerveau il
mène. Le diagnostic confirmait la panne comme une bonne santé.

Posez donc ces quatre valeurs dans votre terminal avant tout le reste. Le document s'en
sert partout.

```bash
BASE=<votre_base>          # brain.name de config/brain.toml
API=$(systemctl show "arac-$BASE-api"     -p ExecStart --value | sed -n 's/.*--port \([0-9]\{1,\}\).*/\1/p')
CC=$( systemctl show "arac-$BASE-cockpit" -p ExecStart --value | sed -n 's/.*--port \([0-9]\{1,\}\).*/\1/p')
PGPORT_BASE=$(sudo sed -n 's/^ARAC_DB_PORT=//p' "/etc/arac/$BASE/arac.env")
echo "cerveau $BASE · API $API · cockpit $CC · PostgreSQL ${PGPORT_BASE:?introuvable dans /etc/arac/$BASE/arac.env}"
```

On lit **l'unité** et **le coffre**, pas des valeurs convenues : l'unité est ce qui lie
réellement le port HTTP, et `arac.env` est ce que les services chargent réellement pour
joindre la base.

### Pourquoi la quatrième, et pourquoi elle est la plus dangereuse des quatre

Les trois premières sont des numéros qu'on écrit. La quatrième est un numéro qu'on
**n'écrit pas** — et c'est pire, parce qu'on l'écrit quand même. `psql`, `createdb`,
`dropdb`, `pg_dump`, `pg_restore` lancés **sans `-p`** ne s'abstiennent pas de choisir :
ils choisissent la grappe **par défaut** de la machine, `5432`. Sur un poste qui porte
deux cerveaux — la situation que ce dépôt tient pour normale, et qu'il recommande lui-même
au §12 de [`INSTALLATION.md`](INSTALLATION.md) — la grappe par défaut est très souvent
celle du **voisin**.

Ce que cela donne, symptôme par symptôme : un diagnostic qui « ne trouve pas vos rôles »
alors qu'ils existent ; un compte d'atomes qui décrit une autre mémoire que la vôtre ; et,
au bout de la page, un `dropdb` **irréversible** exécuté chez quelqu'un d'autre. C'est la
faute du §0 transposée du HTTP à PostgreSQL : **un port qu'on tait est un port qu'on
choisit à l'aveugle.**

Toutes les commandes PostgreSQL de cette page portent donc `-p "$PGPORT_BASE"`. Si vous en
recopiez une ailleurs, recopiez le `-p` avec.

> **Vous installez, et `/etc/arac/$BASE/arac.env` n'existe pas encore ?** Alors le port de
> votre futur cerveau n'est pas encore lisible : c'est celui que vous vous apprêtez à
> donner au bootstrap. `sudo pg_lsclusters` vous montre les grappes de la machine et leurs
> ports ; posez le vôtre à la main. C'est la seule situation où ce numéro se **décide** —
> partout ailleurs, il se lit.

### Et la question qui vient juste après : QUI répond ?

```bash
systemctl show "arac-$BASE-api" -p MainPID --value
sudo ss -ltnp "sport = :$API" | sed -n 's/.*pid=\([0-9]\{1,\}\),.*/\1/p'
```

**Les deux nombres doivent être identiques.** S'ils diffèrent, quelqu'un d'autre tient
votre port : tout ce que vous lirez ensuite décrit son cerveau, pas le vôtre. C'est le cas
à écarter *avant* de croire quoi que ce soit d'autre sur cette page, et
`bootstrap/checks/verify_install.sh` le fait pour vous — il va jusqu'à lire `ARAC_DB` dans
`/proc/<pid>/environ` pour **nommer** le cerveau derrière la socket.

> Si vous n'avez qu'un seul cerveau sur la machine, ce contrôle vous coûtera dix secondes
> et ne servira jamais. Le jour où vous en aurez deux, il sera la seule chose qui vous
> évitera de passer une soirée à réparer une installation qui n'avait rien.

---

## Sommaire des symptômes

**Installation**
1. [L'API ne démarre pas — DATABASE_URL_APP non définie](#1-lapi-ne-démarre-pas--database_url_app-non-définie)
2. [Le cockpit répond 503 à toute connexion](#2-le-cockpit-répond-503-à-toute-connexion)
3. [Le bootstrap s'arrête sur pgvector](#3-le-bootstrap-sarrête-sur-pgvector)
4. [Alembic s'arrête au milieu des migrations](#4-alembic-sarrête-au-milieu-des-migrations)

**Le cerveau n'apprend pas**

5. [Les cycles tournent et ne produisent aucun souvenir](#5-les-cycles-tournent-et-ne-produisent-aucun-souvenir)
6. [La synchronisation ne trouve rien à envoyer](#6-la-synchronisation-ne-trouve-rien-à-envoyer)
   · 6 bis. [Le pont refuse — ce poste pilote plusieurs cerveaux](#6-bis-le-pont-refuse--ce-poste-pilote-plusieurs-cerveaux)
7. [HTTP 403 — le serveur refuse ce poste](#7-http-403--le-serveur-refuse-ce-poste)
8. [HTTP 401 — pas de jeton, ou pas le bon](#8-http-401--pas-de-jeton-ou-pas-le-bon)
9. [Serveur injoignable — le tunnel](#9-serveur-injoignable--le-tunnel)

**Le cockpit ment, ou se tait**

10. [Le cockpit affiche zéro souvenir](#10-le-cockpit-affiche-zéro-souvenir)
11. [Le cockpit refuse le mot de passe, ou le code à six chiffres](#11-le-cockpit-refuse-le-mot-de-passe-ou-le-code-à-six-chiffres)
12. [Le cockpit affiche des chiffres, mais tout est à zéro](#12-le-cockpit-affiche-des-chiffres-mais-tout-est-à-zéro)

**Le cerveau se souvient mal**

13. [Le rappel ne trouve rien, alors que je sais que c'est là](#13-le-rappel-ne-trouve-rien-alors-que-je-sais-que-cest-là)
14. [Le rappel doute de tout](#14-le-rappel-doute-de-tout)
15. [Un domaine est refusé — erreur 422](#15-un-domaine-est-refusé--erreur-422)
16. [Retrait refusé — du savoir vivant serait orphelin](#16-retrait-refusé--du-savoir-vivant-serait-orphelin)

**Exploitation**

17. [La facture est plus élevée que prévu](#17-la-facture-est-plus-élevée-que-prévu)
18. [La sauvegarde est en échec depuis des jours](#18-la-sauvegarde-est-en-échec-depuis-des-jours)
19. [Un minuteur est armé mais rien ne se passe](#19-un-minuteur-est-armé-mais-rien-ne-se-passe)
20. [Rien de tout cela — comment fouiller](#20-rien-de-tout-cela--comment-fouiller)

---

## 1. L'API ne démarre pas — DATABASE_URL_APP non définie

**Le symptôme.** `systemctl status arac-<votre_base>-api` affiche `activating` puis
`failed`, en boucle. Le journal dit :

```
RuntimeError: DATABASE_URL_APP non définie — l'API ne sait pas à quelle base parler.
```

**Ce qui se passe.** Le bootstrap et le moteur ne parlent pas le même dialecte. Le
bootstrap écrit ses variables préfixées (`ARAC_DB_URL_APP`) ; le moteur, extrait de
l'installation d'origine, lit les noms historiques (`DATABASE_URL_APP`). Les deux sont
présents et corrects, ils ne se rencontrent simplement pas. Le tableau complet des
correspondances est dans [`CONFIGURATION.md`](CONFIGURATION.md#le-double-vocabulaire).

**Sur une installation neuve, ce symptôme ne devrait plus apparaître** :
`poser_pont_de_vocabulaire` (`bootstrap/lib/secrets.sh`) pose la traduction dans
`arac.env` **et** dans `cockpit.env`, à la fin de l'étape des clés. Il reste **deux**
situations où vous le rencontrerez, et elles justifient à elles seules que cette section
existe :

1. **une installation antérieure au correctif** — le pont n'avait jamais été posé ;
2. **un `bootstrap.sh --only secrets` ou `--only cles` rejoué**, si l'étape s'interrompt
   avant sa dernière ligne : les noms préfixés sont réécrits, les traductions non.

**Comment le confirmer.**

```bash
sudo grep -c '^ARAC_DB_URL_' /etc/arac/<votre_base>/arac.env     # attendu : 4
sudo grep -c '^DATABASE_URL_' /etc/arac/<votre_base>/arac.env    # si 0 → c'est ça
```

**Comment réparer.** Ce traducteur est **idempotent** (relançable sans dégât) et a été
testé, y compris son idempotence. Il ne supprime rien : il ajoute les noms manquants avec
les mêmes valeurs.

> `systemd` n'interprète pas les variables dans un `EnvironmentFile` : écrire
> `DATABASE_URL_APP=$ARAC_DB_URL_APP` ne marcherait pas. Il faut **dupliquer les
> valeurs**, ce que fait ce script.

```bash
sudo python3 - /etc/arac/<votre_base> <<'PY'
import os, pathlib, re, sys
etc = pathlib.Path(sys.argv[1])
ALIAS = {
    "ARAC_DB_URL_ADMIN": "DATABASE_URL_ADMIN",
    "ARAC_DB_URL_APP": "DATABASE_URL_APP",
    "ARAC_DB_URL_AGENT": "DATABASE_URL_AGENT",
    "ARAC_DB_URL_READONLY": "DATABASE_URL_READONLY",
    "ARAC_EMBEDDINGS_API_KEY": "OPENAI_API_KEY",
    "ARAC_CURATION_API_KEY": "ANTHROPIC_API_KEY",
    "ARAC_CC_SESSION_SECRET": "CC_SESSION_SECRET",
    "ARAC_CC_ADMIN_PASSWORD_HASH": "CC_ADMIN_PASSWORD_HASH",
    "ARAC_CC_TOTP_SECRET": "CC_TOTP_SECRET",
}
def lire(p):
    d = {}
    for l in p.read_text(encoding="utf-8").splitlines():
        if not l.lstrip().startswith("#") and "=" in l:
            k, v = l.split("=", 1)
            d[k.strip()] = v
    return d
def poser(p, paires):
    lignes = p.read_text(encoding="utf-8").splitlines()
    gardees = [l for l in lignes if "=" not in l or l.split("=", 1)[0].strip() not in paires]
    gardees += [f"{k}={v}" for k, v in paires.items()]
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text("\n".join(gardees).rstrip("\n") + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600); os.replace(tmp, p)
for nom in ("arac.env", "cockpit.env"):
    p = etc / nom
    if not p.exists():
        continue
    src = lire(p)
    ajout = {ALIAS[k]: v for k, v in src.items() if k in ALIAS}
    if "ARAC_API_BEARER_TOKEN" in src and "ARAC_NODE_ID" in src:
        slug = re.sub(r"[^A-Z0-9]", "_", src["ARAC_NODE_ID"].upper())
        ajout[f"ARAC_NODE_TOKEN_{slug}"] = src["ARAC_API_BEARER_TOKEN"]
    if ajout:
        poser(p, ajout)
        print(f"{p} : {len(ajout)} variable(s) traduite(s) — {', '.join(sorted(ajout))}")
PY
```

Attendu — **deux lignes, une par fichier**, chacune nommant ce qu'elle a traduit :

```
/etc/arac/<votre_base>/arac.env : N variable(s) traduite(s) — ARAC_NODE_TOKEN_<VOTRE_POSTE>, DATABASE_URL_ADMIN, DATABASE_URL_AGENT, DATABASE_URL_APP, DATABASE_URL_READONLY[, OPENAI_API_KEY, ANTHROPIC_API_KEY]
/etc/arac/<votre_base>/cockpit.env : 3 variable(s) traduite(s) — CC_ADMIN_PASSWORD_HASH, CC_SESSION_SECRET, CC_TOTP_SECRET
```

> **N n'est pas un critère, et ce paragraphe a déjà menti dessus** : il annonçait `7`, ce
> qui n'est vrai que si vous avez donné **les deux clés externes**. Avec les deux clés
> différées — le cas le plus fréquent au premier passage, et le cas *normal* de qui a déjà
> un abonnement Claude, puisqu'il n'a pas de clé de curation à donner —, la première ligne
> rend `5` : les
> quatre `DATABASE_URL_*` et le jeton de votre poste, et rien d'autre à traduire. Le critère,
> ce sont les **noms** : les quatre rôles doivent être là, et la seconde ligne doit rendre
> `3`. Si un fichier n'a rien à traduire, il n'imprime **aucune** ligne — le script ne parle
> que de ce qu'il a changé.

Puis :

```bash
sudo systemctl restart "arac-$BASE-api" "arac-$BASE-cockpit"
curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:$API/healthz"    # attendu : 200
```

**À refaire** après chaque `bootstrap.sh --only secrets` ou `--only cles`, qui
réécrivent les noms préfixés sans toucher aux traductions. Le script est idempotent :
relancez-le sans crainte.

---

## 2. Le cockpit répond 503 à toute connexion

**Ce qui se passe.** Le cockpit est **fail-closed** : s'il lui manque l'un de ses trois
secrets (`CC_SESSION_SECRET`, `CC_ADMIN_PASSWORD_HASH`, `CC_TOTP_SECRET`), il refuse
toute connexion et journalise `not_provisioned`. Il ne s'ouvre jamais par accident.

Neuf fois sur dix, la cause est celle du §1 : les secrets existent sous les noms
préfixés (`ARAC_CC_*`), et le cockpit ne lit que les autres.

**Comment le confirmer.**

```bash
# On nomme les trois, plutôt que de compter tout ce qui commence par CC_ :
# un compte ne dit pas LESQUELS manquent, et c'est la seule chose utile ici.
sudo grep -cE '^(CC_SESSION_SECRET|CC_ADMIN_PASSWORD_HASH|CC_TOTP_SECRET)=' \
     /etc/arac/<votre_base>/cockpit.env                     # attendu : 3
journalctl -u arac-<votre_base>-cockpit -n 30 --no-pager | grep -i not_provisioned
```

**Comment réparer.** Le traducteur du §1. Si les secrets manquent réellement :

```bash
sudo ./bootstrap/bootstrap.sh --only secrets   # puis rejouez le traducteur du §1
```

---

## 3. Le bootstrap s'arrête sur pgvector

**Ce qui se passe.** L'extension `vector` n'est pas disponible **pour cette version
majeure de PostgreSQL**. Le paquet Debian/Ubuntu est lié à la majeure : installer
`postgresql-16-pgvector` sur un serveur qui tourne en 15 ou 17 ne sert à rien.

**Comment le confirmer.**

```bash
sudo -u postgres psql -p "$PGPORT_BASE" -tAc "SHOW server_version"
sudo -u postgres psql -p "$PGPORT_BASE" -tAc "SELECT default_version FROM pg_available_extensions WHERE name='vector'"
```

> **Ici, `$PGPORT_BASE` ne vient pas du coffre** — vous êtes en cours d'installation, le
> coffre n'existe pas encore : c'est le port que vous vous apprêtez à donner au bootstrap,
> posé à la main après un `sudo pg_lsclusters` (voir le §0). Le `-p` n'est pas facultatif
> pour autant : `SHOW server_version` sans lui répond pour la grappe par défaut, et vous
> installeriez pgvector pour la mauvaise majeure de PostgreSQL.

Si la seconde commande ne rend **rien**, l'extension n'est pas installée pour cette
majeure. Si elle rend un numéro mais que `CREATE EXTENSION` échoue quand même, le
serveur n'a pas été redémarré depuis l'installation du paquet.

**Comment réparer.**

```bash
sudo apt install postgresql-<VOTRE_MAJEURE>-pgvector
sudo systemctl restart postgresql
sudo ./bootstrap/bootstrap.sh --from vecteurs
```

**Version trop ancienne (`type "halfvec" does not exist`).** Le schéma exige
**pgvector ≥ 0.7.0** ; Ubuntu 24.04 livre 0.6.0. Le bootstrap le refuse à l'étape 4 ; si
vous voyez plutôt l'erreur `psycopg.errors.UndefinedObject: type "halfvec" does not
exist` pendant les migrations, la cause est la même. Remède : le dépôt officiel PostgreSQL
(PGDG), puis, si l'extension existe déjà dans la base, sa mise à jour.

```bash
sudo apt install -y postgresql-common && sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
sudo apt install postgresql-16-pgvector
sudo systemctl restart postgresql
sudo -u postgres psql -p "$PGPORT_BASE" -d <votre_base> -c 'ALTER EXTENSION vector UPDATE;'
sudo ./bootstrap/bootstrap.sh --from vecteurs
```

**Pourquoi c'est bloquant et non contournable.** Sans pgvector, le rappel se réduit à du
`ctrl-F` : le cerveau retrouve exactement ce dont vous vous souvenez déjà, ce qui est
l'inverse du but.

---

## 4. Alembic s'arrête au milieu des migrations

**Ce qui se passe.** Trois causes, par ordre de fréquence : l'extension `vector` manque
(voir §3, les migrations créent des colonnes `halfvec`) ; le rôle utilisé n'est pas
`arac_admin` et n'a pas le droit de créer des tables ; ou une migration a échoué à
mi-course et l'état est partiel.

**Comment le confirmer.**

```bash
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc "SELECT extname FROM pg_extension ORDER BY 1"
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc "SELECT version_num FROM arac.alembic_version"
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='arac'"
```

Une révision présente mais un nombre de tables anormalement bas = migration partielle.

**Comment réparer.**

```bash
# après avoir corrigé la cause :
sudo ./bootstrap/bootstrap.sh --from migrations
```

**Si l'état est vraiment incohérent** et que la base ne contient encore **aucun
souvenir**, la voie la plus sûre est de repartir de zéro plutôt que de rafistoler :

```bash
# CONTRÔLE BLOQUANT — les deux lignes, dans cet ordre, et sur la MÊME grappe.
# La première dit sur quel serveur vous êtes ; la seconde, ce que vous détruiriez.
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc \
  "SELECT current_setting('port'), current_database()"
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc \
  "SELECT count(*) FROM arac.memory_atoms"          # doit rendre 0

# et seulement alors — IRRÉVERSIBLE :
sudo -u postgres dropdb -p "$PGPORT_BASE" "$BASE"
sudo ./bootstrap/bootstrap.sh --rejouer
```

> **Ne faites cela que sur une base vide de savoir**, et vérifiez-le *sur la grappe que
> vous allez viser* — c'est tout l'objet du contrôle ci-dessus. Un `count(*)` qui rend `0`
> sur la grappe par défaut pendant que votre cerveau vit sur la sienne ne prouve
> strictement rien, et le `dropdb` qui suit tomberait sur la base du voisin. Si la première
> ligne ne rend pas le port que vous attendez, **arrêtez-vous**.
>
> Si `arac.memory_atoms` n'existe pas encore, la deuxième ligne échoue : c'est une bonne
> nouvelle, il n'y a rien à perdre.

---

## 5. Les cycles tournent et ne produisent aucun souvenir

**Le symptôme.** Les cycles s'exécutent à l'heure, le journal ne montre pas d'erreur, et
le compte d'atomes ne bouge pas. Le cockpit dit :

```
  Le cerveau n'a rien appris depuis 24 heures.
```

**Ce qui se passe.** Quatre causes, par ordre décroissant de fréquence.

**a) Les identifiants de poste sont incohérents.** C'est **la** cause n°1 : sur le
cerveau de référence, **36 % des cycles sont partis en quarantaine sans produire un seul
atome**, et ce n'était pas une question de volume. Le cerveau refuse ce qui vient d'un
nœud non déclaré ; la tranche arrive avec un `node_id` qui n'est pas celui de
`config/brain.toml`, et tout est jeté d'un bloc.

```bash
# côté serveur
sudo grep '^ARAC_NODE_ID=' /etc/arac/<votre_base>/arac.env
grep node_id config/brain.toml
# côté machine source
grep -i node "$HOME/.arac/<votre_base>/pont.conf"
```

Les trois doivent dire **exactement** la même chose. Un tiret de plus suffit à tout
perdre.

**b) Les DEUX interrupteurs de dépense, ou le binaire de curation.** C'est la cause la
plus fréquente, et de loin : sur un cerveau neuf, **les deux interrupteurs sont fermés**
et le cycle refuse avant tout travail. Ce n'est pas une panne, c'est l'état d'usine.

```bash
# interrupteur 1/2 — dans le coffre
sudo grep -E '^(ARAC_MODE_DEGRADE|ARAC_ALLOW_PAID_AI)=' /etc/arac/<votre_base>/arac.env

# interrupteur 2/2 — EN BASE, et le binaire de curation : les deux d'un coup
cd /chemin/de/votre/clone && sudo .venv/bin/python -m agents.lib.paid_ai_control status \
     --coffre /etc/arac/<votre_base>/arac.env
```

La sortie de `status` nomme les trois choses qui décident, et **imprime le geste exact
qui manque** :

```
IA payante ARMÉE : NON  (env_allow=False config=None kill_switch=off)
  → INTERRUPTEUR 1 sur 2 — côté service. … Il reste ensuite l'INTERRUPTEUR 2, en base : …
Curation (binaire): OUI — /usr/bin/claude
```

Réparer, dans cet ordre :

```bash
sudo sed -i 's/^ARAC_ALLOW_PAID_AI=.*/ARAC_ALLOW_PAID_AI=1/' /etc/arac/<votre_base>/arac.env
sudo .venv/bin/python -m agents.lib.paid_ai_control arm --confirm \
     --coffre /etc/arac/<votre_base>/arac.env
```

**`Curation (binaire): NON`** est un cas à part, et aucune clé ne le répare : la digestion
n'appelle aucune API, elle **lance** le Claude Code CLI en sous-processus. Le geste est
`sudo npm install -g @anthropic-ai/claude-code` — et si le binaire n'atterrit pas dans le
`PATH` du service, `ARAC_CLAUDE_BIN=/chemin/absolu/vers/claude` dans le coffre. Le binaire
doit aussi avoir **sa propre authentification sous le compte d'agent** :
`sudo ./bootstrap/checks/verify_install.sh` (§7) imprime les deux chemins exacts.

**Et si vous avez réparé puis relancé sans rien voir** : le créneau du jour est
peut-être déjà pris (`cortex.duplicate_slot` dans le journal). Posez
`ARAC_CORTEX_FORCE_MANUAL=1` dans le coffre, relancez le service, **puis retirez la
ligne** — laissée en place, chaque tir de la minuterie ouvrirait un créneau neuf au lieu
d'un par horaire.

**c) La file est vide.** Le cerveau se repose. Ce n'est pas une panne : si rien n'est
entré, rien ne peut sortir. Vérifiez d'abord la synchronisation (§6).

**d) La tranche est trop grosse.** Une tranche trop grande ne cause pas l'échec, mais
elle rend chaque échec total : on perd tout d'un coup. Descendez
`ARAC_PACK_TOKEN_BUDGET` et `ARAC_PACK_MAX_CONVS`, remontez-les quand vous aurez vu
trois cycles réussir.

**Le diagnostic qui tranche.**

```bash
journalctl -u arac-<votre_base>-cycle.service -n 100 --no-pager
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc \
  "SELECT count(*) FROM arac.memory_atoms WHERE created_at > now() - interval '48 hours'"
.venv/bin/python scripts/ops/alerts.py --explain
```

---

### 5 bis. Les cycles sortent « vides » en boucle, et l'alerte se répète

**Le symptôme.** Chaque cycle se termine en `empty`, l'alerte « message(s)
surdimensionné(s) » revient à chaque passage, et aucun atome n'est produit.

**Ce qui se passe.** Après deux quarantaines non attribuables, le cycle réduit sa tranche
(bisection) jusqu'à une seule conversation. Si le premier message de la plus ancienne
dépasse à lui seul le budget, la tranche reste vide, et le cycle recommence indéfiniment.
Deux garde-fous évitent cette boucle : la bisection est relâchée dès qu'un cycle vide lui est
postérieur, et une conversation dont un message dépasse le budget est parquée 7 jours
(le curseur n'avance pas, rien n'est perdu), avec une seule ligne de revue par message.

```bash
# les messages écartés, en attente de revue (remplacez le DSN par le vôtre, lecture seule)
psql "$DATABASE_URL_READONLY" -c "SELECT conversation_uid, status, proposed_atom FROM arac.digestion_review_queue WHERE kind = 'oversized_message' ORDER BY 1 DESC LIMIT 20;"
```

Si le message géant est un artefact d'outillage (un bundle injecté, sans connaissance),
déclarez son début dans `ARAC_OVERSIZED_SKIP_PREFIXES` (voir `docs/CONFIGURATION.md`) : il sera
sauté au prochain passage au lieu d'être parqué.

---

## 6. La synchronisation ne trouve rien à envoyer

**Ce qui se passe.** Trois cas, très différents.

**a) C'est normal — l'export de Claude Desktop est manuel.** **Il n'existe aucune
capture automatique de l'application Claude Desktop.** Elle ne garde rien de lisible en
local. La seule voie stable est l'export officiel de claude.ai, que vous déclenchez
vous-même. Claude Code (CLI), en revanche, est capté automatiquement depuis
`~/.claude/projects/`.

Si vous n'utilisez que l'application de bureau et que vous n'avez jamais exporté, le
pont n'a rien à trouver. Ce n'est pas une panne.

**b) Tout a déjà été envoyé.** Le pont ne remonte que le nouveau ou le modifié.
`code=0` et « Rien de nouveau » sont le résultat **attendu** d'un deuxième passage.

**c) L'état est corrompu ou le chemin est faux.**

```bash
./arac-pont.sh etat                     # quel maillon est cassé ?
ls -la ~/.claude/projects/ | head       # y a-t-il des .jsonl ?
ls -la ~/.arac/                         # l'état est-il inscriptible ?
```

**Comment réparer.** En cas de doute sur un trou dans votre mémoire, **renvoyer ne coûte
rien** : le serveur déduplique par message.

```bash
python3 "$HOME/.arac/<votre_base>/arac-sync.py" --tout
```

Si des messages repartent à **chaque** passage, l'état ne se sauve pas : vérifiez les
droits de `~/.arac/<votre_base>/`. **Un foyer par cerveau** : deux cerveaux pilotés depuis
un même poste partageraient sinon leur curseur de synchronisation, et le pont du second
marquerait « déjà envoyées » des conversations que le premier n'a jamais reçues.

Le détail complet : [`PONT-MAC.md`](PONT-MAC.md).

---

## 6 bis. Le pont refuse — ce poste pilote plusieurs cerveaux

**Ce qui se passe.** Ce n'est **pas une panne, c'est une garde.** Dès que
`~/.arac/` contient plus d'un dossier muni d'un `pont.conf`, ni `arac-pont.sh` ni
`arac-sync.py` ne choisissent à votre place : deviner reviendrait à décider dans quelle
mémoire déposer des conversations privées. Ils sortent en **code 2**, sans rien envoyer,
en nommant les cerveaux qu'ils connaissent :

```
  × Ce poste pilote plusieurs cerveaux ; lequel ?
       alpha  beta
     Précisez :  --cerveau <nom>   (ou ARAC_CERVEAU=<nom>)
```

**Comment le confirmer.**

```bash
ls -d ~/.arac/*/ | xargs -n1 basename        # un dossier = un cerveau piloté d'ici
```

**Comment réparer** — en nommant le cerveau. Les deux outils ne prennent pas les mêmes
formes, et c'est le seul piège :

```bash
# arac-sync.py accepte le drapeau OU la variable
python3 "$HOME/.arac/<votre_base>/arac-sync.py" --cerveau <votre_base> --tout
ARAC_CERVEAU=<votre_base> python3 "$HOME/.arac/<votre_base>/arac-sync.py" --tout

# arac-pont.sh n'accepte QUE la variable
ARAC_CERVEAU=<votre_base> ./arac-pont.sh etat
```

Ordre de résolution, dans `arac-sync.py` : `--cerveau`, puis `ARAC_CERVEAU`, puis
`--conf <fichier>` (un fichier nommé explicitement fait autorité et suffit à lui seul),
puis — **et seulement s'il n'y en a qu'un** — le cerveau unique. C'est pour cela que la
commande du §6 ci-dessus fonctionne tant que vous n'avez qu'un cerveau, et cesse de
fonctionner le jour où vous en installez un second.

> **⚠ Et l'automatisation est concernée elle aussi — vérifiez-la.** L'agent launchd posé
> par `arac-pont.sh automatiser` lance `~/.arac/<cerveau>/arac-sync.py` **sans drapeau**,
> et son bloc `EnvironmentVariables` ne pose ni `ARAC_CERVEAU` ni `--conf`
> (`mac/com.arac.pont.sync.plist.modele`). Sur un poste à un seul cerveau, le repli
> « l'unique » fait le travail. Sur un poste à deux cerveaux, **les deux agents sortent en
> code 2 toutes les heures sans rien envoyer** — et comme la sortie part dans un journal,
> rien ne vous le dit. Le contrôle qui tranche :
>
> ```bash
> tail -20 ~/Library/Logs/arac-pont-<cerveau>-sync.log   # « plusieurs cerveaux ; lequel ? »
> ```
>
> En attendant que le gabarit porte le nom du cerveau, ajoutez-le vous-même dans le plist
> installé, puis rechargez l'agent :
>
> ```bash
> plutil -insert EnvironmentVariables.ARAC_CERVEAU -string '<votre_base>' \
>        ~/Library/LaunchAgents/com.arac.<votre_base>.pont.sync.plist
> plutil -lint  ~/Library/LaunchAgents/com.arac.<votre_base>.pont.sync.plist
> launchctl bootout   "gui/$(id -u)/com.arac.<votre_base>.pont.sync" 2>/dev/null
> launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.arac.<votre_base>.pont.sync.plist
> ```
>
> *(Constat ouvert, reproduit en lançant le script exactement comme le fait l'agent —
> répertoire de travail `~/.arac/<cerveau>`, aucun argument, deux cerveaux configurés :
> code 2. Le correctif appartient au gabarit `mac/`, pas à cette page. Le pont n'a jamais
> tourné sur un vrai Mac : ce geste-ci non plus.)*

Si le message dit au contraire « Aucun cerveau n'est configuré sur ce poste », il n'y a
rien à trancher : c'est `mac/arac-pont.sh installer` qu'il faut lancer.

---

## 7. HTTP 403 — le serveur refuse ce poste

**Ce qui se passe.** Le jeton est valide, mais le poste n'a pas franchi l'une des **trois
portes** que l'ingestion lui oppose. Elles sont indépendantes, et il faut les vérifier
toutes les trois — sinon on répare la mauvaise.

| Porte | Où elle vit | Comportement si elle manque |
|---|---|---|
| **1. le jeton** | `ARAC_NODE_TOKEN_<NODE_ID>` dans l'environnement de l'API | `401` (voir §8) |
| **2. la liste blanche** | `ARAC_INGEST_ALLOWED_NODES` (liste séparée par des virgules) | **fail-closed : variable absente = TOUT est refusé** |
| **3. la déclaration en base** | une ligne dans `arac.nodes` — clé étrangère obligatoire | la requête échoue avant d'avoir touché la mémoire |

> **Les trois portes sont posées par l'installation.** La liste blanche est écrite par le
> bootstrap depuis l'identité de votre entretien (`bootstrap/lib/secrets.sh`), la ligne de
> `arac.nodes` par la migration `0008` qui lit le même `config/brain.toml`, et le jeton
> par l'étape des clés. Sur une installation neuve conforme, elles s'ouvrent donc pour
> votre poste. Ce qui vous amène ici, en pratique, c'est une **divergence** entre ces
> écritures — un `node_id` qui n'est pas exactement le même partout.

**Comment le confirmer.**

```bash
# porte 2 — la liste blanche
sudo grep '^ARAC_INGEST_ALLOWED_NODES=' /etc/arac/<votre_base>/arac.env

# porte 3 — la déclaration en base
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -c "SELECT node_id FROM arac.nodes"

# la référence qui fait foi
grep node_id config/brain.toml
# et, côté machine source
grep -i node "$HOME/.arac/<votre_base>/pont.conf"
```

Toutes ces chaînes doivent être **identiques**, à la casse près. Un tiret de plus suffit
à tout perdre — c'est la cause réelle des **36 % de cycles partis en quarantaine** sur le
cerveau de référence.

**Comment réparer** — seulement si l'un des contrôles ci-dessus est venu vide. Si les
trois chaînes sont là mais diffèrent, ne posez rien : alignez-les sur
`config/brain.toml`.

```bash
# porte 2 — ajouter un poste absent de la liste (la virgule sépare, elle n'écrase pas)
sudo sh -c 'printf "ARAC_INGEST_ALLOWED_NODES=%s\n" "<votre-node-id>" >> /etc/arac/<votre_base>/arac.env'
sudo systemctl restart arac-<votre_base>-api

# porte 3 — semer la table des postes (idempotent ; inutile sur une installation neuve,
#           où la migration 0008 l'a déjà fait)
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -v ON_ERROR_STOP=1 \
     -v arac_node_id="$(.venv/bin/python -c 'import arac_runtime; print(arac_runtime.node_id())')" \
     -f db/seeds/01_nodes_and_config.sql
```

Le seed refuse de deviner : sans la variable `arac_node_id`, il s'arrête et vous renvoie
à l'entretien. **Un `node_id` inventé ouvrirait exactement la porte que cette table sert
à tenir fermée.**

> Le `node_id` de `config/brain.toml` fait foi. Alignez la machine source dessus, **pas
> l'inverse** : changer le `node_id` du serveur scinderait en deux populations la
> provenance de tout ce qui est déjà entré.

*(Les deux commandes ci-dessus n'ont pas pu être exécutées ici, faute de base
installée — voir la note en fin de document.)*

---

## 8. HTTP 401 — pas de jeton, ou pas le bon

**Ce qui se passe.** `app/auth.py` ne connaît pas de jeton global. Il scanne
l'environnement à la recherche du préfixe `ARAC_NODE_TOKEN_` et construit une table
`jeton → node_id`. Le nom de la variable est le `node_id` en majuscules, tirets
remplacés par des soulignés :

```
mon-portable  →  ARAC_NODE_TOKEN_MON_PORTABLE
```

Le bootstrap, lui, écrit un `ARAC_API_BEARER_TOKEN` unique — un nom que l'API ne lit
jamais. C'est pourquoi il le recopie sous `ARAC_NODE_TOKEN_<NODE_ID>` en même temps que le
reste du pont de vocabulaire (§1).

> **Avant de chercher plus loin : lisez le corps du `401`.** Le jeton est exigé de
> **toute** requête, y compris depuis `127.0.0.1` — seul `/healthz` est public. Un `401`
> ne veut donc pas dire « je viens du mauvais endroit », il veut dire « je n'ai pas
> présenté de jeton valide ». **Le corps de la réponse le dit** : il porte un champ
> `pourquoi` qui nomme la raison exacte, et un champ `geste`. Si vous avez posé
> `ARAC_API_TRUST_LOOPBACK=1` et que rien n'a changé, c'est normal et c'est écrit dans le
> `pourquoi` : le desserrage n'est appliqué qu'accompagné de son motif,
> `ARAC_API_TRUST_LOOPBACK_RAISON` ([`CONFIGURATION.md` §6](CONFIGURATION.md#6-lapi)).

**Comment le confirmer.**

```bash
sudo grep -c '^ARAC_NODE_TOKEN_' /etc/arac/<votre_base>/arac.env    # attendu : ≥ 1
```

**Comment réparer.** Si le compte est `0`, rejouez le pont du §1, puis
`systemctl restart arac-<votre_base>-api`.

**Pour ajouter un second poste** (par exemple Claude Code sur le serveur lui-même) :

```bash
JETON=$(openssl rand -hex 32)
sudo sh -c "printf 'ARAC_NODE_TOKEN_CLAUDE_CODE_SERVEUR=%s\n' '$JETON' >> /etc/arac/<votre_base>/arac.env"
sudo systemctl restart arac-<votre_base>-api
```

Le `node_id` correspondant doit aussi être déclaré côté cerveau. **Révoquer un poste** :
retirez sa ligne, redémarrez. Il est fermé à la requête suivante.

---

## 9. Serveur injoignable — le tunnel

**Ce qui se passe.** L'API et le cockpit n'écoutent que `127.0.0.1`. Le tunnel SSH est la
**seule** porte. Trois raisons de la trouver fermée : le tunnel n'est pas ouvert, il a
été tué par un réveil de veille, ou le serveur l'a libéré côté `sshd`.

**Comment le confirmer.**

```bash
# sur le serveur — $BASE, $API, $CC viennent du §0
sudo ss -ltnp | grep -E "127\.0\.0\.1:($API|$CC)\b"   # les services écoutent-ils ?
systemctl is-active "arac-$BASE-api" "arac-$BASE-cockpit"

# sur votre machine, tunnel censé être ouvert (mêmes deux numéros, relevés sur le serveur)
curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:$CC"
ss -ltn | grep -E "127\.0\.0\.1:($API|$CC)\b"        # les ports sont-ils là ?
```

**Comment réparer.**

```bash
# sur un Mac : la commande fournie, qui lit les ports de VOTRE cerveau
#   (ARAC_PORT_API / ARAC_PORT_COCKPIT de ~/.arac/<votre_base>/pont.conf,
#    deux valeurs sans défaut — un numéro plausible vous brancherait sur le voisin)
mac/arac-pont.sh tunnel ouvrir

# à la main, ailleurs
ssh -N -L "$CC:127.0.0.1:$CC" -L "$API:127.0.0.1:$API" <utilisateur>@<votre-serveur>
```

**Pour que ça tienne** après un réveil de veille, il faut `autossh` côté machine source
et `ClientAliveInterval` côté serveur (`deploy/ssh/99-arac-pont.conf`) — sans quoi le
serveur garde un tunnel mort et refuse d'en ouvrir un nouveau sur le même port.

**Le vrai test** n'est pas d'ouvrir le tunnel : c'est de fermer le Mac, de le rouvrir une
heure plus tard, et de vérifier que le tunnel est revenu tout seul.

> Si `ss -ltnp` montre l'API sur `0.0.0.0` côté serveur — et non sur `127.0.0.1` —,
> **arrêtez tout** : quelque chose a été modifié, votre mémoire est joignable depuis le
> réseau, et il n'y a ni TLS ni authentification forte devant elle.

---

## 10. Le cockpit affiche zéro souvenir

**Ce qui se passe.** Quatre causes, à distinguer avant de toucher à quoi que ce soit.

**a) Il n'y a réellement rien.** Cerveau neuf, ou rien n'est encore entré. Le cockpit dit
alors « Le cerveau n'a rien appris depuis 24 heures » — et **c'est une information**, pas
un bandeau vide.

**b) Le cockpit ne voit pas la base.** `DATABASE_URL_READONLY` manque (voir §1).

**c) Les souvenirs existent, mais ils sont hors des vues du cockpit.** C'est le piège n°1,
et il ne fait aucun bruit : **un atome posé sur une racine nue n'apparaît dans aucune vue
de scope, ne contribue à aucun état courant et ne compte dans aucune couverture** — ce sont
exactement les chiffres que le cockpit affiche. Il reste rappelable par une question qui
lui ressemble, ce qui explique qu'on puisse le retrouver par l'API et ne jamais le voir à
l'écran. Sur le cerveau de référence, près d'un souvenir actif sur onze est tombé dedans.

**d) La fenêtre est trop courte.** La vue « Aujourd'hui » est glissante : essayez `7d` ou
`30d` avant de conclure.

**Comment le confirmer.**

```bash
# combien de souvenirs, en tout ?
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc \
  "SELECT count(*) FROM arac.memory_atoms WHERE status='active'"

# combien sont posés sur une racine nue, donc hors des vues du cockpit ?
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc \
  "SELECT count(*) FROM arac.memory_atoms a
     JOIN arac.scopes s ON s.path = a.scope
    WHERE a.status='active' AND s.depth = 0"
```

> **C'est mot pour mot la requête du produit**, pas une paraphrase : elle est copiée de
> `bootstrap/checks/verify_install.sh`, qui fait ce comptage sans que vous ayez à écrire
> une ligne de SQL — lancez-le plutôt, il dira aussi ce que le nombre veut dire.
> *(Cette page a longtemps écrit `SELECT key FROM arac.scopes WHERE parent_key IS NULL`.
> Ces deux colonnes n'existent pas : la table porte `path`, `parent_id` et `depth`, et la
> requête rendait `ERROR: column "parent_key" does not exist` sur toute installation. Une
> requête de diagnostic qu'on recopie un mauvais jour n'a pas droit à une faute de frappe.)*

**Comment réparer** le cas (c) : déplacez ces atomes vers une feuille. Il n'y a pas de
commande magique, et c'est volontaire — déplacer du savoir est une décision, pas un
`UPDATE`. Le cockpit permet de le faire souvenir par souvenir, en voyant ce qu'on
déplace.

**Comment l'éviter** : c'est une affaire de taxonomie. Si vos rédacteurs (vous, ou la
curation) posent souvent sur des racines, c'est que vos feuilles ne couvrent pas le
terrain. Ajoutez-en.

---

## 11. Le cockpit refuse le mot de passe, ou le code à six chiffres

**Ce qui se passe.** Trois causes.

**a) Le second facteur n'est pas appairé** — vous avez sauté ou raté l'étape 7 du
bootstrap.

**b) L'horloge dérive.** TOTP est fondé sur le temps. Une dérive de plus de trente
secondes entre le serveur et votre téléphone suffit à invalider tous les codes.

```bash
timedatectl status | grep -E 'synchronized|Time zone'
```

Si `System clock synchronized: no` : `sudo timedatectl set-ntp true`.

**c) L'empreinte du mot de passe est absente ou dans le mauvais dialecte** (voir §1 et
§2) — mais alors vous auriez un `503`, pas un refus.

**Comment réparer.**

```bash
sudo ./bootstrap/bootstrap.sh --only secrets    # réappaire, redemande un mot de passe
# puis rejouez le traducteur du §1
```

**Si vous avez perdu l'appareil TOTP** : supprimez la ligne `ARAC_CC_TOTP_SECRET` de
`/etc/arac/<votre_base>/cockpit.env`, ainsi que sa traduction `CC_TOTP_SECRET`, puis
relancez `--only secrets`. Un nouveau secret est engendré et réaffiché.

---

## 12. Le cockpit affiche des chiffres, mais tout est à zéro

**Ce qui se passe.** À distinguer du §10 : ici, les métriques s'affichent, avec leurs
seuils et leurs libellés, mais leurs valeurs sont nulles ou marquées indisponibles.

C'est le signe que le cockpit **parle à la base** mais que la base **ne contient pas la
matière** : pas de reçus de rappel, pas de journal de cycle, pas d'atomes. Un cerveau
neuf ressemble à ça pendant quelques jours.

`health_check.py` distingue explicitement les deux situations, et c'est important :

| Code | Sens |
|---|---|
| 0 | OK |
| 1 | WARNING |
| 2 | CRITICAL |
| **3** | **UNKNOWN** — base injoignable, cockpit incomplet |

Une base injoignable et un cerveau malade **ne demandent pas le même geste**. Une sonde
qui confond les deux vous envoie chercher au mauvais endroit à trois heures du matin. Et
elle ne doit surtout pas répondre « OK » : transformer une panne d'observation en bonne
nouvelle est l'erreur la plus coûteuse d'un système de surveillance.

**Comment confirmer.**

```bash
sudo -E .venv/bin/python scripts/ops/health_check.py --all
sudo -E .venv/bin/python scripts/ops/health_check.py --metric brain_health_index
```

`--all` montre les 148 métriques, pas seulement les fâchées. Chacune porte sa définition,
sa formule et sa requête de preuve : de la phrase on atteint le chiffre, du chiffre on
atteint la ligne.

---

## 13. Le rappel ne trouve rien, alors que je sais que c'est là

**Ce qui se passe.** Par ordre de fréquence :

**a) L'atome est sur une racine nue.** Il est en base et il reste atteignable par une
question qui lui ressemble — mais **pas** par une requête qui précise un domaine, car
l'égalité de scope est stricte : demander `travail/finance` ne rend jamais un atome rangé
sur `travail`. Voir §10(c).

**b) L'atome n'a pas de vecteur.** Sans clé d'embeddings — ou si elle a été ajoutée
après coup — les souvenirs entrés entre-temps n'ont jamais été vectorisés. Ils ne
remonteront jamais par similarité.

**c) Vous filtrez sur le mauvais domaine.** Le rappel filtre par domaine avant de
comparer les vecteurs. Un filtre trop étroit rend un résultat vide alors que le souvenir
existe deux feuilles plus loin.

**d) Le modèle d'embeddings a changé.** C'est le pire cas, parce qu'il est **silencieux**.
Deux populations de vecteurs incomparables cohabitent alors dans le même index : la
recherche fonctionne, ne lève aucune erreur, et rend n'importe quoi. Aucun test n'échoue.

**Comment le confirmer.**

```bash
# des atomes sans vecteur ?
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc \
  "SELECT count(*) FROM arac.memory_atoms WHERE status='active' AND embedding IS NULL"
sudo grep -E '^(OPENAI_API_KEY|ARAC_MODE_DEGRADE)=' /etc/arac/<votre_base>/arac.env
```

**Comment réparer.** Poser la clé (§1 et `--only cles`) répare l'avenir, pas le passé :
les atomes déjà entrés doivent être **re-vectorisés**, donc re-payés. Faites-le tôt,
tant que le corpus est petit.

---

## 14. Le rappel doute de tout

**Ce n'est pas une panne.** Sur le cerveau de référence, **96 % des rappels sont rendus
en confiance basse**. Le rappel trouve, mais doute.

Un cerveau qui vous répond « je crois, à 40 % » est honnête. Le contraire — un cerveau
qui affirme tout à 95 % — serait beaucoup plus inquiétant, d'autant que **98 % du savoir
du cerveau de référence n'a jamais été audité**. Le cerveau est confiant sur ce qu'il n'a
jamais vérifié.

**Ce que vous ne pouvez pas faire, et il vaut mieux le savoir que le chercher :** faire
monter cette confiance. Elle est fixée à la naissance de l'atome — le champ est absent du
schéma de modification de l'API, et la supersédure l'hérite de l'atome remplacé. Le
cockpit ne peut pas davantage : sa seule route non-GET est la connexion, et son rôle
PostgreSQL ouvre toutes ses transactions en lecture seule. Il n'y a **pas** de rituel
hebdomadaire d'arbitrage, parce qu'il n'y a rien à cliquer ; la boucle de validation est
déclarée comme un chantier dans [`ROADMAP.md`](ROADMAP.md), §2.4.

**Ce que vous pouvez faire :** corriger le savoir lui-même. Un atome faux se remplace par
`POST /v1/atoms/{id}/supersede`, se retouche par `PATCH /v1/atoms/{id}`, s'archive par
`DELETE /v1/atoms/{id}`. Le geste complet, avec ses commandes, est dans
[`PREMIER-MOIS.md`](PREMIER-MOIS.md), « Corriger ce qui est faux ». Cela rend le corpus
plus juste ; cela ne déplace pas la calibration, qui est un fichier gelé et versionné.

---

## 15. Un domaine est refusé — erreur 422

**Ce qui se passe.** Un domaine hors de votre taxonomie est refusé à l'entrée : `422`
côté API, violation de clé étrangère côté base. **C'est délibéré.** Sans cette rigidité,
la mémoire se fragmenterait en dizaines de catégories jumelles — `travail`,
`boulot`, `job`, `pro` — et le rappel se diluerait sans que rien ne le signale.

**Comment le confirmer.**

```bash
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -c "SELECT path FROM arac.scopes ORDER BY 1"
grep -E '^\[\[|^key' config/scopes.toml
```

**Comment réparer.** Ajoutez la feuille manquante à `config/scopes.toml`, puis :

```bash
sudo ./bootstrap/bootstrap.sh --scopes-only
```

**Ajouter est facile ; retirer ne l'est pas.** Voir §16.

---

## 16. Retrait refusé — du savoir vivant serait orphelin

**Ce qui se passe.** Vous avez supprimé un domaine de `config/scopes.toml`, et
`sudo ./bootstrap/bootstrap.sh --scopes-only` refuse : « *Retrait refusé — du savoir
vivant deviendrait orphelin* », suivi de chaque domaine et de son nombre de souvenirs. Il
ne fait pas de zèle : ce domaine **contient encore des atomes vivants**, et les retirer
les rendrait orphelins — c'est-à-dire perdus.

> **C'est le bootstrap qui porte cette garde, pas le générateur seul.** Le refus vient
> d'une interrogation de VOTRE base, faite avant la régénération.
> `python3 bootstrap/generate_scopes.py --config config/scopes.toml`, appelé directement,
> ne voit aucune base : il régénère sans un mot. Il sait le faire — `--dsn <votre DSN>` —
> mais il faut le lui demander, et rien dans ce dépôt ne le lui demande. **Passez par
> `--scopes-only`**, c'est la seule voie qui refuse.

**Comment le confirmer.** Le message nomme le domaine. Pour compter :

```bash
sudo -u postgres psql -p "$PGPORT_BASE" -d "$BASE" -tAc \
  "SELECT scope, count(*) FROM arac.memory_atoms WHERE status='active' GROUP BY 1 ORDER BY 2 DESC"
```

**Comment réparer.** Deux voies, et seulement deux :

1. **Remettre le domaine** dans `config/scopes.toml`. C'est souvent la bonne : un domaine
   habité mérite peut-être d'exister.
2. **Déplacer ses souvenirs d'abord**, dans le cockpit, un par un, en voyant ce qu'on
   déplace. Puis retirer le domaine.

Il n'y a volontairement pas de troisième voie. Un `--force` qui efface du savoir n'a pas
sa place dans un outil qui prétend s'en souvenir.

---

## 17. La facture est plus élevée que prévu

**Ce qui se passe.** Le poste dominant est la **curation**, pas les embeddings. Et le
rapport qui compte n'est pas le nombre de jetons, c'est le **rendement** : sur le cerveau
de référence, ~87 000 jetons par cycle pour ~31 500 jetons par atome effectivement
produit. **La plupart des jetons lus ne produisent rien** — c'est normal, mais un
rendement qui s'effondre coûte cher sans rien rapporter.

**Comment le confirmer.** Le cockpit sert deux phrases faites pour ça :

```
  J'ai dépensé N jetons depuis 24 heures, soit M jetons par atome retenu.
  J'ai dépensé N jetons depuis 24 heures sans retenir un seul atome.
```

La seconde, répétée, est le signal d'alarme : vous payez pour rien. La cause est
presque toujours celle du §5(a).

**Comment réparer.**

```bash
# 1. couper la dépense, tout de suite
sudo sed -i 's/^ARAC_ALLOW_PAID_AI=.*/ARAC_ALLOW_PAID_AI=0/' /etc/arac/<votre_base>/arac.env
sudo systemctl restart arac-<votre_base>-cycle.timer

# 2. comprendre, puis seulement remettre
journalctl -u arac-<votre_base>-cycle.service --since '3 days ago' --no-pager | tail -100
```

**Les trois leviers**, dans l'ordre où il faut les tirer :

1. **Réparer les identifiants de poste** (§5a) — les cycles en quarantaine sont dépensés
   et perdus.
2. **Réduire la cadence** : `ARAC_CYCLES="04:00 21:00"` au lieu de trois.
3. **Réduire la tranche** : `ARAC_PACK_TOKEN_BUDGET`, `ARAC_PACK_MAX_CONVS`.

Changer `ARAC_CURATOR_MODEL` pour un modèle plus petit coûte moins **et extrait moins**.
Le rapport n'est pas linéaire : mesurez avant de descendre.

---

## 18. La sauvegarde est en échec depuis des jours

**Ce qui se passe.** Une sauvegarde peut mentir de quatre façons, et c'est pour cela que
`ops/backup.sh` fait quatre contrôles au lieu d'un : le dump minuscule, le dump qui a
maigri, le dump amputé (une table vitale manque), et le dump qui ne se restaure pas.

**Comment le confirmer.**

```bash
sudo ARAC_ENV_FILE="/etc/arac/$BASE/arac.env" ops/watchdog.sh   # encore une garantie ?
sudo ls -lt "/var/backups/arac/$BASE" | head
journalctl -u "arac-$BASE-sauvegarde.service" -n 50 --no-pager
```

> **`sudo` sur les deux premières, et ici c'est vital.** Le répertoire des dumps est en
> `0700 root`. Sans root, `watchdog.sh` ne voit aucun fichier, en conclut qu'il n'y en a
> pas, et rend `critical` — « *aucun dump […] la sauvegarde n'a JAMAIS produit de
> fichier* », code `2` — **sur une sauvegarde qui vient de tourner**. Mesuré à la même
> seconde, dump en place : sans root `dump_age_h=99999`, `problems=2` ; avec root
> `dump_age_h=0`, `problems=0`, code `0`. Vous êtes sur cette page parce que quelque chose
> ne va pas : ne laissez pas un défaut de droits vous en fabriquer un second.

**Comment réparer.** Les causes ordinaires : disque plein, droits du répertoire
(`0700` n'est pas décoratif), rôle de sauvegarde absent, ou `ARAC_ENV_FILE` qui pointe au
mauvais endroit.

```bash
df -h /var/backups
sudo install -d -m 0700 -o "$(id -un)" "/var/backups/arac/$BASE"
# À la main, pour voir le message en clair — et en NOMMANT le cerveau. Sans la
# variable, sur une machine qui en porte plusieurs, ces scripts ne s'arrêtent
# pas : ils servent le cerveau que CE CLONE décrit, après l'avoir annoncé
# (« ops/ sert le cerveau « … » — ce dépôt le décrit, il n'a pas été deviné »).
# C'est le dossier courant qui décide, et ce n'est pas ce qu'on veut ici.
sudo ARAC_ENV_FILE="/etc/arac/$BASE/arac.env" ops/backup.sh
```

**Et surtout** : une sauvegarde jamais restaurée n'est pas une sauvegarde, c'est une
hypothèse.

```bash
# restaure VRAIMENT dans une base jetable et prouve le contenu
sudo ARAC_ENV_FILE="/etc/arac/$BASE/arac.env" ops/restore_verify.sh
# ou, sans rien à poser : l'unité, qui porte déjà le coffre de ce cerveau
sudo systemctl start "arac-$BASE-restauration.service"
```

Tout est dans [`SAUVEGARDE.md`](SAUVEGARDE.md), y compris la restauration réelle — celle
qu'on exécute en panique, et qu'il vaut mieux avoir lue avant.

---

## 19. Un minuteur est armé mais rien ne se passe

**Ce qui se passe.** Un `.timer` armé ne prouve pas que le `.service` qu'il déclenche
réussit. Les deux se regardent séparément.

**Comment le confirmer.**

```bash
systemctl list-timers 'arac-*' --all --no-pager
systemctl status arac-<votre_base>-cycle.service --no-pager
journalctl -u arac-<votre_base>-cycle.service -n 50 --no-pager
```

`list-timers` donne le **prochain** passage ; `status` donne le **dernier résultat**.
`ops/install_check.sh` fait les deux d'un coup et signale les `DERNIER PASSAGE EN ÉCHEC`.

**Comment réparer.** Les causes ordinaires : `ExecStart` pointe vers un module absent
(vérifiez `ARAC_HOME` et `PYTHONPATH` dans l'unité), l'environnement manque (§1), ou
`Persistent=true` a déclenché un rattrapage qui a échoué et n'a pas été rejoué.

```bash
systemctl cat arac-<votre_base>-cycle.service     # lire ce qui tourne vraiment
sudo systemctl start arac-<votre_base>-cycle.service   # forcer, pour voir l'erreur
```

---

## 20. Rien de tout cela — comment fouiller

**Dans l'ordre**, du moins cher au plus cher :

```bash
# 1. l'installation tient-elle debout ?
sudo ./bootstrap/checks/verify_install.sh
sudo ARAC_ENV_FILE="/etc/arac/$BASE/arac.env" ops/install_check.sh

# 2. le cerveau va-t-il bien ? — root, pour la même raison qu'au point 1 :
#    ces deux-là lisent la base, et leur DSN est dans le coffre.
sudo -E .venv/bin/python scripts/ops/health_check.py --all
sudo -E .venv/bin/python scripts/ops/alerts.py
.venv/bin/python scripts/ops/alerts.py --explain   # celui-ci ne lit rien : pas de root

# 3. qu'a fait le service qui coince ?
journalctl -u arac-<votre_base>-<api|cockpit|cycle> -n 200 --no-pager

# 4. qu'a fait l'agent, exactement ? (prompt et réponse inclus)
ls -lt "$(.venv/bin/python -c 'import arac_runtime as r; print(r.agent_logs_dir())')" | head
```

Le point 4 est le plus utile et le moins connu : `logs/agents/` contient **une ligne
JSONL par mission**, prompt et réponse compris. C'est ce qui permet de rejouer une
décision d'agent six mois plus tard. Le cerveau de référence lui doit l'essentiel de ce
qu'il sait de ses propres erreurs.

**Le code est la dernière documentation, et il est écrit pour être lu** :
`bootstrap/README.md` pour l'installation, `ops/README.md` pour l'exploitation,
`mac/README.md` pour le pont, et les docstrings de `arac_runtime.py`,
`control_center/cc_v1/today.py` et `app/auth.py`, qui expliquent leurs décisions plutôt
que leur implémentation.

---

## Le principe qui gouverne tous ces outils

**Constater, expliquer, ne rien réparer.** Aucun script de `ops/` ne redémarre un
service, ne purge une file, ne restaure par-dessus une base vivante. Chacun dit ce qui ne
va pas et quel geste le corrige — puis s'arrête.

Un outil d'exploitation qui répare tout seul finit par cacher la panne qu'il répare. On
s'en aperçoit le jour où il n'y arrive plus, et il est alors trop tard pour comprendre ce
qui se cassait depuis six mois.

---

## Ce qui a été réellement exécuté pour écrire ce document

**Vérifié** : `bootstrap/checks/verify_install.sh` (sur une installation **incomplète** —
sortie et messages de réparation observés) · `ops/install_check.sh` ·
`ops/backup_toc_check.sh selftest` · `ops/restore_guard.sh selftest` · `make test` ·
`make doctor` · `bootstrap.sh --check` et `--dry-run` · le traducteur du §1, y compris
son idempotence, sur des fichiers d'environnement fabriqués reproduisant exactement ce
qu'écrit `bootstrap/lib/database.sh` et `secrets.sh`.

**Vérifié depuis, sur une grappe jetable montée pour cela** (`pg_createcluster 16 … --port
5471`, un cerveau d'essai, puis démontage) : la **forme** de toutes les commandes `psql` de
cette page — `-p "$PGPORT_BASE" -d "$BASE"` —, le contrôle bloquant du §4
(`SELECT current_setting('port'), current_database()`), les deux commandes du §3, et la
lecture du port dans `/etc/arac/<base>/arac.env`. Et le défaut qu'elles corrigent a été
reproduit dans le même terminal : la même commande **sans `-p`** répond `5432`, c'est-à-dire
la grappe par défaut de la machine.

**Éprouvé depuis, sur un cerveau né du chemin réel — et rejouable chez vous.**

- **`ops/backup.sh`**, lancé exactement comme le §18 l'écrit
  (`sudo ARAC_ENV_FILE=… ops/backup.sh`) : dump produit, ses quatre contrôles passés,
  code `0`. Et par l'autre chemin, celui que le bootstrap arme lui-même —
  `systemctl start arac-<base>-sauvegarde.service` —, dont l'`ExecStart` **est**
  `ops/backup.sh` : `systemctl cat` le montre en une ligne.
- **`ops/restore_verify.sh`**, sur le dump ainsi produit :
  *« VERDICT : PROUVÉ — ce dump se restaure, et le cerveau en sort entier »*, code `0`,
  les témoins écrits avant la sauvegarde relus dans la base jetable, laquelle est
  détruite ensuite. Puis le **code `2`** que le §7 de [`SAUVEGARDE.md`](SAUVEGARDE.md)
  annonce : obtenu sur le même dump après un `DROP SCHEMA arac CASCADE` sur la base
  vivante — preuves A, B et D rendues, seule la comparaison au vivant impossible.
- **Le cerveau cassé, puis retrouvé** : le §7 joué ligne par ligne après cette
  destruction — base neuve, `pg_restore`, renommage, `bootstrap.sh --only migrations` —
  et les souvenirs relus **sous le rôle de l'application**, pas sous le superutilisateur.
- **`make acceptance` traverse ces deux scripts à chaque passage** (étapes 3 et 8) : c'est
  là qu'il faut regarder, pas ici. Une ligne de ce paragraphe se périme ; un juge qui
  tourne, non.
- **Les sorties de `health_check.py` et d'`alerts.py` contre une vraie base** :
  bulletin complet rendu, alarmes rendues avec leurs seuils. Sur un cerveau
  neuf, elles disent surtout ce qui n'a pas encore eu lieu — c'est leur travail.
- **Toutes les commandes `psql` de cette page**, rejouées une par une contre un schéma
  **complet** (celui que les migrations bâtissent, pas un squelette). Deux d'entre elles
  nommaient des colonnes qui n'existent pas — `scopes.key` et `scopes.parent_key` — et
  ont été corrigées ici (§10 et §15) pour la forme que le code lui-même emploie
  (`s.path = a.scope`, `s.depth = 0`).

**Toujours non vérifié** : les **valeurs** que ces requêtes rendent sur un cerveau
**habité** — le cerveau de banc porte des souvenirs écrits à la main, mais aucune
conversation, aucun vecteur, aucun reçu de cycle, faute de ce que la digestion réclame
(le binaire de curation, son authentification, et les deux interrupteurs de dépense) ; les branches de cette page qui commencent par « il y a trop de… » ne
peuvent donc pas se lire sur lui · le chemin **chiffré** de la sauvegarde (`age -d`) et la
copie hors site, qui demandent une clé et une seconde machine · tout ce qui concerne le
**tunnel depuis un Mac**.

> **Pourquoi ce paragraphe a été réécrit, et pourquoi c'est ici que ça compte le plus.**
> Il déclarait « non vérifié » `ops/backup.sh` et `ops/restore_verify.sh` — les deux
> commandes que le §18 de cette page donne comme **remède**, cent lignes plus haut, à
> quelqu'un dont la sauvegarde ne se fait plus. Les deux moitiés ne pouvaient pas être
> vraies ensemble : on donnait deux gestes pour se sauver, puis on avouait ne les avoir
> jamais essayés. Une section d'honnêteté périmée ne rassure pas : elle **retire de la
> valeur au reste**, parce qu'elle est le seul endroit dont toute l'utilité tient à ce
> qu'il soit exactement vrai. Et sous-estimer trompe autant que surestimer — celui qui lit
> cette page-ci est, par construction, celui chez qui quelque chose est déjà cassé.
