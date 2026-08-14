"""G3 — AUCUNE COMMANDE IMPRIMÉE NE DÉSIGNE SA GRAPPE PAR OMISSION.

CE QUE CE GARDE MESURE, EN UNE PHRASE
=====================================
Toute commande `libpq` que le produit IMPRIME — message d'erreur, sortie de
migration, refus du bootstrap, message d'un agent, ligne d'un runbook —
doit porter le port de la grappe qu'elle vise. Sinon elle vise celle du
voisin.

POURQUOI CE GARDE EXISTE, ET POURQUOI IL EST D'UNE AUTRE NATURE QUE G1
======================================================================
G1 interroge des LITTÉRAUX : un nom de rôle, un port écrit en dur, un chemin
absolu. Il ne peut pas voir une ABSENCE. Or le troisième nom global de
l'incident — la grappe — n'est presque jamais écrit : il est donné par son
omission. `sudo -u postgres psql -d ma_base` ne nomme aucune grappe ; il
s'adresse donc à celle que la machine désigne par défaut, c'est-à-dire, sur
un serveur qui suit la recommandation de ce dépôt (une grappe par cerveau),
à celle du PREMIER installé. Et si deux amis ont donné le même nom à leur
cerveau, `dropdb` détruit celui de l'autre.

G1 a déclaré cette zone lui-même, dans `ZONES_NON_COUVERTES` — « un nom donné
par OMISSION » —, en écrivant que le contrôle qui la verrait « est d'une
autre nature » et « n'existe pas encore ». Le voici. Il est d'une autre
nature en effet : il ne cherche pas ce qui est écrit, il exige ce qui manque.

LE MOMENT OÙ CES LIGNES SONT LUES EST LE PIRE DE TOUS
=====================================================
Une commande imprimée n'est pas de la documentation : c'est un remède,
délivré à quelqu'un dont l'installation vient de tomber. Il copie, il colle,
il ne relit pas — c'est précisément la conduite que le remède encourage. Une
page de manuel se lit à froid ; un message d'erreur se lit à chaud.

LE PÉRIMÈTRE N'EST PAS UNE LISTE DE RÉPERTOIRES — ET C'EST LE POINT
====================================================================
La zone aveugle déclarée par G1 bornait le contrôle manquant à « aucune
commande libpq de docs/, bootstrap/ ou ops/ ». C'était la même faute de
forme, d'un cran au-dessus : le seul `dropdb` sans `-p` du dépôt vivait dans
`db/alembic/versions/`, hors des trois répertoires nommés — et il était
imprimé au moment d'une panne.

Ce garde balaie donc EXACTEMENT le même corpus que G1 : tout ce que git
transporte, moins ce que `EXEMPTIONS_ZONE` exempte nommément. On importe ces
deux fonctions de G1 plutôt que de les recopier : deux corpus qui se
ressemblent finissent par diverger, et le jour où ils divergent, personne ne
sait lequel des deux ment.

CE QUI COMPTE COMME « IMPRIMÉ » — la définition, et rien d'autre
================================================================
· PYTHON — toute chaîne atteinte par un `raise` ou par un appel de sortie
  (`print`, `write`, `warn`, `error`, `log`…), en suivant UN saut par une
  constante de module. Ce saut n'est pas une analyse de flot : c'est la
  résolution d'un nom écrit à l'endroit même où l'on imprime. Il a servi dès
  le premier passage — `GESTE_DE_MARQUAGE`, dans `tests/garde_hermetique.py`,
  était un remède fautif assemblé par ce chemin exact.
· SHELL — les lignes d'un appel à une fonction de sortie (`echo`, `printf`,
  `note`, `warn`, `bad`, `ko`, `dire`, `arac_die`…), jusqu'à la fermeture de
  la chaîne, et le corps des documents en ligne (`<<EOF`).
· TOUT LE RESTE (Markdown, SQL, unités systemd, gabarits) — ce que `code_de`
  de G1 tient déjà pour du code : un manuel est un remède imprimé dans les
  mains d'un humain, et il se copie de la même façon.

CE QUE CE GARDE NE COUVRE PAS — écrit ici, pas ailleurs
========================================================
Voir `ZONES_NON_COUVERTES_G3`, imprimé en fin de session comme celui de G1.
Un garde qui ne dit pas où s'arrête sa vue donne une confiance qu'il ne
mérite pas, et la confiance est ce qui empêche de regarder.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

# On réutilise le corpus de G1, on ne le recopie pas : deux corpus qui se
# ressemblent divergent, et le jour où ils divergent personne ne sait lequel
# ment. `code_de` porte en plus toute la connaissance de G1 sur ce qui
# S'EXÉCUTE dans un document (blocs encadrés, blocs indentés, cellules de
# tableau, spans au fil du texte) — la réécrire serait la réécrire moins bien.
from tests.test_g1_aucun_nom_partage_entre_cerveaux import (  # noqa: E402
    _LIANT,
    _SPAN,
    _fichiers_balayes,
    code_de,
)

RACINE = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# CE QU'ON CHERCHE
# ---------------------------------------------------------------------------

#: Les programmes clients de libpq. Tous acceptent `-p`, tous retombent sur la
#: grappe par défaut sans lui, tous peuvent détruire ou divulguer.
OUTILS_LIBPQ = (
    "psql", "pg_dump", "pg_dumpall", "pg_restore", "createdb", "dropdb",
    "createuser", "dropuser", "reindexdb", "vacuumdb", "clusterdb",
    "pg_isready", "pg_basebackup",
)
_OUTILS = "(?:" + "|".join(OUTILS_LIBPQ) + ")"

_APPEL = re.compile(rf"(?<![\w./-])({_OUTILS})(?![\w-])")

#: Ce qui DÉSIGNE la grappe. `-p`, `--port`, `PGPORT`, `--cluster` (le
#: sur-ensemble Debian, qui nomme version + grappe et vaut donc mieux qu'un
#: port). Un DSN complet la porte aussi : elle est dans l'URL.
_PORT = re.compile(r"(?<![\w-])-p(?![\w-])|--port|PGPORT|--cluster")

#: Une cible donnée sous forme de DSN porte déjà son port — ou l'assume
#: explicitement, ce qui est un choix écrit, pas une omission.
_DSN = re.compile(r"postgres(?:ql)?://|(?<![-\w])dbname=|DSN|_URL\b|conninfo|service=")

#: Ce qui peut légitimement précéder un programme sur une ligne de commande.
#: Tout le reste veut dire qu'on n'est pas en position de commande : on est
#: dans une phrase qui PARLE de la commande.
_PREFIXE = re.compile(
    r"^(?:sudo|env|nohup|setsid|timeout|exec|command|\d+|-{1,2}[\w-]+"
    r"|[A-Z_][A-Z0-9_]*=\S*|postgres|root|\$\{?\w+\}?)$"
)
#: Ce qui SÉPARE une phrase de la commande qu'elle introduit. Les deux-points
#: et la flèche sont dans cette liste parce que c'est ainsi que ce dépôt
#: présente ses remèdes — « dites-le explicitement :  sudo -u postgres dropdb
#: <votre-base> ». Sans eux, le garde ratait la commande la plus destructrice
#: qu'il existe pour la seule raison qu'un mot français la précédait sur la
#: ligne. Mesuré : c'était le cas de `db/alembic/versions/0001` ligne 218.
_SEPARATEUR = re.compile(r"\$\(|&&|\|\||[|;&(){}`\n:→]")


def _en_position_de_commande(ligne: str, debut: int) -> bool:
    """Ce littéral est-il un programme QU'ON LANCE, ou un mot dans une phrase ?

    « et le dropdb final y détruirait ce qui porte ce nom » parle d'un
    `dropdb` ; il n'en lance aucun. Un garde qui accuse la phrase écrite pour
    nous avertir apprend à ses lecteurs à l'ignorer — et c'est le jour où il a
    raison que plus personne ne l'écoute.
    """
    morceau = _SEPARATEUR.split(ligne[:debut])[-1]
    morceau = morceau.replace('\\"', " ").replace("\\n", " ")
    morceau = re.sub(r"""["'+]""", " ", morceau)
    return all(_PREFIXE.match(jeton) for jeton in morceau.split())


def _citation_dans_une_phrase(ligne: str, debut: int) -> bool:
    """La commande est-elle CITÉE en police de code au fil d'une phrase ?

    G1 a déjà écrit cette règle et payé son prix : « la PROSE … Retenir la
    prose ferait accuser la phrase écrite pour nous avertir ». Le message de
    refus de `garde_hermetique` RACONTE l'incident — « c'est l'erreur exacte
    qui a laissé passer `sudo -n -u postgres psql -d arac` pendant des mois ».
    Cette ligne n'est pas un remède : c'est la leçon. Lui faire porter un
    `-p` la rendrait fausse.
    """
    for m in _SPAN.finditer(ligne):
        if m.start(1) <= debut < m.end(1):
            reste = _SPAN.sub(" ", ligne)
            return not _LIANT.match(reste)
    return False


def _cible_nue(queue: str, outil: str) -> str | None:
    """Le nom de base visé, quand il est donné NU (donc sans grappe)."""
    m = re.search(r"\s(?:-d|--dbname)[= ]\s*(\S+)", queue)
    if m:
        return m.group(1)
    if outil in ("createdb", "dropdb", "createuser", "dropuser"):
        m = re.search(
            rf"^{outil}((?:\s+-{{1,2}}[\w-]+(?:[= ]\S+)?)*)\s+([^\s|;&)]+)", queue
        )
        if m:
            return m.group(2)
    return None


def commandes_sans_grappe(texte: str) -> list[tuple[int, str, str]]:
    """(décalage de ligne, outil, ligne) — une entrée par faute trouvée."""
    trouve: list[tuple[int, str, str]] = []
    for decalage, ligne in enumerate(texte.splitlines()):
        for m in _APPEL.finditer(ligne):
            outil = m.group(1)
            if not _en_position_de_commande(ligne, m.start()):
                continue
            if _citation_dans_une_phrase(ligne, m.start()):
                continue
            queue = ligne[m.start():]
            # Le port peut précéder le programme — `PGPORT=5461 psql …`. On
            # regarde donc aussi le préfixe de commande, mais LUI SEUL : un
            # « posez PGPORT » écrit trois phrases plus haut n'acquitte rien.
            prefixe = _SEPARATEUR.split(ligne[:m.start()])[-1]
            if _PORT.search(queue) or _DSN.search(queue) or _PORT.search(prefixe):
                continue
            if _cible_nue(queue, outil) is None:
                continue        # rien à ouvrir : `psql --version`, `arac_require psql`
            trouve.append((decalage, outil, ligne.strip()))
    return trouve


# ---------------------------------------------------------------------------
# CE QUI COMPTE COMME « IMPRIMÉ »
# ---------------------------------------------------------------------------

#: Les appels par lesquels un texte SORT du programme. On énumère ici, et
#: c'est assumé : l'inversion (« énumérer le légitime ») n'a pas de sens pour
#: une sortie, puisqu'il n'existe pas de liste close des appels qui n'écrivent
#: pas. Le prix de l'oubli est écrit dans ZONES_NON_COUVERTES_G3.
APPELS_DE_SORTIE = frozenset({
    "print", "write", "writelines", "warn", "warning", "info", "debug",
    "error", "critical", "exception", "log", "note", "echo", "fail", "die",
    "abort", "usage", "puts", "render", "message",
})


def _nom_appele(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def textes_imprimes_python(p: Path) -> list[tuple[int, str]]:
    """Les chaînes qu'un `raise` ou un appel de sortie fait sortir du programme.

    LE SAUT PAR UNE CONSTANTE DE MODULE, ET POURQUOI IL S'ARRÊTE À UN.
    `f"  {GESTE_DE_MARQUAGE}\\n"` est un remède imprimé, et son texte n'est
    pas là : il est vingt lignes plus haut, dans une constante. Suivre ce
    saut-là n'est pas une analyse de flot — c'est lire un nom écrit à
    l'endroit même où l'on imprime. Le suivre plus loin en serait une, et G1
    déclare déjà, à juste titre, qu'il ne la fait pas.
    """
    try:
        arbre = ast.parse(p.read_text(encoding="utf-8"))
    except (SyntaxError, ValueError):
        return []

    constantes: dict[str, list[ast.Constant]] = {}
    for n in arbre.body:
        if not (isinstance(n, ast.Assign) and len(n.targets) == 1):
            continue
        cible = n.targets[0]
        if not isinstance(cible, ast.Name):
            continue
        morceaux = [
            c for c in ast.walk(n.value)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)
        ]
        if morceaux:
            constantes[cible.id] = morceaux

    sortie: list[tuple[int, str]] = []
    for n in ast.walk(arbre):
        if isinstance(n, ast.Raise) and n.exc is not None:
            racines: list[ast.AST] = [n.exc]
        elif isinstance(n, ast.Call) and _nom_appele(n) in APPELS_DE_SORTIE:
            racines = list(n.args) + [k.value for k in n.keywords]
        else:
            continue
        for r in racines:
            for c in ast.walk(r):
                if isinstance(c, ast.Constant) and isinstance(c.value, str):
                    sortie.append((c.lineno, c.value))
                elif isinstance(c, ast.Name) and c.id in constantes:
                    sortie.extend((cc.lineno, cc.value) for cc in constantes[c.id])
    return sortie


#: Les fonctions par lesquelles ce dépôt PARLE en shell. Elles sont nommées
#: une fois ici ; `test_les_fonctions_de_sortie_existent_encore` vérifie
#: qu'elles sont toujours celles que les scripts appellent.
FONCTIONS_DE_SORTIE_SHELL = (
    "echo", "printf", "cat", "note", "dire", "info", "warn", "bad", "ok", "ko",
    "say", "die", "arac_die", "arac_alert", "arac_note", "plan", "verdict",
    "nonteste", "attention", "expliquer", "erreur", "conseil", "astuce",
    "aide", "refus", "titre", "etape",
    # `cmd` MANQUAIT, ET C'EST LA FONCTION DONT LE MÉTIER EST D'IMPRIMER DES
    # COMMANDES. `bootstrap/lib/ui.sh` la définit pour ça, et l'écran de fin
    # de l'installation ne prescrit ses gestes que par elle. Une liste d'écoute
    # qui oublie le porte-voix principal n'écoute rien : mesuré en remettant un
    # `psql -d <base>` sans port dans un `cmd`, G3 est resté vert.
    "cmd", "lecon", "mal", "bien", "alerte", "action", "sous_titre",
    "banniere", "etape_entete", "echec",
)
#: LE PRÉFIXE DE CONTINUATION — l'angle mort que ce motif avait, et qui
#: n'était déclaré nulle part. Ce dépôt écrit la plupart de ses remèdes en
#: continuation d'un test : `[ … ] && ok "…" || bad "…" "le remède"`. Ancré en
#: TÊTE de ligne, le motif n'en voyait aucun — trente-quatre lignes du corpus,
#: dont une portait un `psql` sans port (`ops/install_check.sh`, la
#: réinstallation des scopes). Un garde qui promet plus qu'il ne tient est
#: pire qu'un garde absent : il donne confiance.
_SORTIE_SH = re.compile(
    r"^\s*(?:(?:\|\||&&|;)\s*)?(?:local\s+\w+=)?(?:sudo\s+)?(?:"
    + "|".join(FONCTIONS_DE_SORTIE_SHELL)
    + r")\b"
)
_DOC_EN_LIGNE = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")


def _guillemets_impairs(l: str) -> bool:
    return len(re.findall(r'(?<!\\)"', l)) % 2 == 1


def textes_imprimes_shell(p: Path) -> list[tuple[int, str]]:
    """Les lignes qu'un script fait s'afficher : appels de sortie et documents
    en ligne, une entrée par ligne physique (pour que le constat porte un
    numéro qu'on peut ouvrir).

    L'APPEL LUI-MÊME EST RETIRÉ DE LA LIGNE, et c'est une correction, pas un
    détail. On rendait la ligne BRUTE — `cmd "  sudo -u postgres psql -d ma_base"`
    — à `commandes_sans_grappe`, qui demande ensuite si l'outil est « en
    position de commande » : tout ce qui précède doit être un préfixe connu
    (`sudo`, `env`, `timeout`, une variable…). `cmd`, `dire`, `echo` n'en sont
    pas. Le verdict était donc « ce psql est un mot dans une phrase », et le
    garde se taisait — sur TOUTE commande imprimée en shell tenant sur une
    seule ligne, c'est-à-dire sur presque toutes.

    Mesuré : `commandes_sans_grappe('  sudo -u postgres psql -d ma_base')`
    rend une faute ; la même chaîne précédée de n'importe laquelle des huit
    fonctions de sortie essayées n'en rend aucune. Le chemin PYTHON, lui,
    était juste depuis toujours — il rend la valeur de la chaîne, pas la ligne
    — et c'est pourquoi le seul contre-essai du garde, écrit en Python, ne
    pouvait pas voir le trou.
    """
    lignes = p.read_text(encoding="utf-8", errors="replace").splitlines()
    sortie: list[tuple[int, str]] = []
    dans_chaine = False
    fin_doc: str | None = None
    for i, l in enumerate(lignes, start=1):
        if fin_doc is not None:
            if l.strip() == fin_doc:
                fin_doc = None
            else:
                sortie.append((i, l))
            continue
        if dans_chaine:
            sortie.append((i, l))
            if _guillemets_impairs(l):
                dans_chaine = False
            continue
        appel = _SORTIE_SH.match(l)
        if appel:
            sortie.append((i, l[appel.end():]))
            m = _DOC_EN_LIGNE.search(l)
            if m:
                fin_doc = m.group(1)
            elif _guillemets_impairs(l):
                dans_chaine = True
    return sortie


def _est_du_shell(p: Path) -> bool:
    if p.suffix in (".sh", ".bash"):
        return True
    if p.suffix in ("", ".modele", ".template"):
        try:
            return p.read_text(encoding="utf-8", errors="replace")[:2] == "#!"
        except OSError:
            return False
    return False


def textes_imprimes(p: Path) -> list[tuple[int, str]]:
    if p.suffix == ".py":
        return textes_imprimes_python(p)
    if _est_du_shell(p):
        return textes_imprimes_shell(p)
    # Un manuel est un remède imprimé dans les mains d'un humain.
    return list(code_de(p))


# ---------------------------------------------------------------------------
# LE BALAYAGE
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Faute:
    fichier: str
    ligne: int
    outil: str
    texte: str

    def __str__(self) -> str:
        return f"{self.fichier}:{self.ligne}  [{self.outil}]  {self.texte[:120]}"


def balayage_g3() -> list[Faute]:
    fautes: list[Faute] = []
    for p in _fichiers_balayes():
        rel = str(p.relative_to(RACINE))
        for depart, texte in textes_imprimes(p):
            for decalage, outil, ligne in commandes_sans_grappe(texte):
                fautes.append(Faute(rel, depart + decalage, outil, ligne))
    return sorted(set(fautes), key=lambda f: (f.fichier, f.ligne))


def test_aucune_commande_imprimee_ne_vise_le_cluster_par_defaut() -> None:
    """LE GARDE. Une commande imprimée sans `-p` vise la grappe du voisin."""
    fautes = balayage_g3()
    assert not fautes, (
        "Des commandes libpq IMPRIMÉES ne désignent aucune grappe. Sans `-p`,\n"
        "elles s'adressent à la grappe PAR DÉFAUT de la machine — donc, sur un\n"
        "serveur qui pose une grappe par cerveau, à celle du voisin. Et elles\n"
        "sont lues au pire moment : celui de la panne, quand on copie sans\n"
        "relire.\n\n"
        "Le remède : faire porter à la commande le port de la grappe CONCERNÉE.\n"
        "Ne l'écrivez pas en dur — demandez-le à la connexion que vous avez\n"
        "déjà (`SELECT current_setting('port')`), comme le fait\n"
        "`db/alembic/versions/0001_baseline_phase1b.py`.\n\n"
        + "\n".join(f"  · {f}" for f in fautes)
    )


# ---------------------------------------------------------------------------
# LE GARDE MIS À L'ÉPREUVE — il doit voir, et il doit se taire
# ---------------------------------------------------------------------------

#: Des commandes qui DOIVENT être vues. Chacune est une forme réellement
#: rencontrée dans ce dépôt ou dans sa documentation.
SONDES_FAUTIVES = (
    ("sudo -u postgres psql -d <votre-base> -c 'CREATE EXTENSION vector'",
     "le remède de la migration de départ, imprimé pendant une panne"),
    ("sudo -u postgres dropdb <votre-base>",
     "la commande la plus destructrice que ce dépôt imprime"),
    ("explicitement :  sudo -u postgres dropdb <votre-base>",
     "la MÊME, introduite par une phrase — sa forme réelle dans 0001:218"),
    ("Le geste → sudo -u postgres dropdb <votre-base>",
     "la même, introduite par une flèche"),
    ("psql -d <base> -c \"COMMENT ON DATABASE <base> IS 'jetable'\"",
     "un remède assemblé depuis une constante de module"),
    ("pg_dump -d ma_base --format=custom -f /var/backups/x.dump",
     "un dump pris sur la mauvaise grappe est un dump de quelqu'un d'autre"),
    ("sudo -u postgres createdb ma_base_test",
     "la base de vérification créée chez le voisin"),
    ("pg_restore -d ma_base /var/backups/arac/dernier.dump",
     "restaurer par-dessus la base du voisin"),
    ("PGPASSWORD=x psql --dbname=ma_base -c 'SELECT 1'",
     "une enveloppe d'environnement ne fournit pas le port"),
    ("timeout 5 sudo -u postgres psql -d ma_base",
     "une enveloppe de délai non plus"),
    ("dropuser arac_app",
     "un rôle est GLOBAL au cluster : le détruire ailleurs coupe le voisin"),
)

#: Des commandes qui doivent laisser le garde MUET. Un garde qui crie sur ce
#: qui va bien s'apprend à ignorer.
SONDES_SAINES = (
    ("sudo -u postgres psql -p 5461 -d ma_base -c 'SELECT 1'", "le port, écrit"),
    ("psql --port=5461 -d ma_base", "le port, en forme longue"),
    ("PGPORT=5461 psql -d ma_base", "le port, par l'environnement"),
    ("psql \"$DATABASE_URL_READONLY\" -qtAc 'SELECT 1'", "un DSN porte son port"),
    ("psql 'postgresql://u@h:5461/b' -c 'SELECT 1'", "une URL aussi"),
    # La grappe est nommée d'après le cerveau : G1 refuserait un nom figé ici,
    # et il a raison — une sonde de G3 n'a pas le droit d'être un contre-exemple
    # pour G1.
    ("sudo -u postgres psql --cluster 16/$ARAC_DB -d ma_base", "la grappe, nommée"),
    ("psql --version", "aucune base ouverte"),
    ("command -v psql >/dev/null 2>&1", "on cherche l'outil, on ne l'ouvre pas"),
    ("arac_require pg_restore", "on exige l'outil, on ne l'ouvre pas"),
    ("et le dropdb final y détruirait ce qui porte ce nom",
     "une PHRASE qui parle d'un dropdb n'en lance aucun"),
)


@pytest.mark.parametrize("commande,pourquoi", SONDES_FAUTIVES)
def test_le_garde_voit_la_grappe_donnee_par_omission(commande: str, pourquoi: str) -> None:
    assert commandes_sans_grappe(commande), (
        f"Le garde n'a PAS vu : {commande}\n  ({pourquoi})\n"
        "Une sonde muette est un garde qui promet plus qu'il ne tient."
    )


@pytest.mark.parametrize("commande,pourquoi", SONDES_SAINES)
def test_le_garde_se_tait_quand_la_grappe_est_nommee(commande: str, pourquoi: str) -> None:
    assert not commandes_sans_grappe(commande), (
        f"Le garde a crié à tort sur : {commande}\n  ({pourquoi})"
    )


def test_le_garde_lit_ce_qui_est_imprime_et_pas_le_reste(tmp_path: Path) -> None:
    """La définition d'« imprimé » est mesurée, pas seulement écrite.

    Un spécimen posé dans une liste — la matière que les gardes de ce dépôt
    se donnent à eux-mêmes — n'est pas un remède : personne ne le lit, donc
    personne ne le copie. Une chaîne levée par un `raise`, elle, atterrit sur
    l'écran de quelqu'un dont l'installation vient de tomber.
    """
    source = (
        "SPECIMENS = [\n"
        "    'sudo -u postgres dropdb marc_brain',\n"
        "]\n"
        "def f():\n"
        "    raise RuntimeError(\n"
        "        'Le geste, dites-le explicitement :\\n'\n"
        "        '    sudo -u postgres dropdb marc_brain\\n'\n"
        "    )\n"
    )
    fichier = tmp_path / "sonde.py"
    fichier.write_text(source, encoding="utf-8")
    vus = textes_imprimes_python(fichier)
    fautes = [f for _, t in vus for f in commandes_sans_grappe(t)]
    assert len(fautes) == 1, (
        "Le garde doit voir la commande LEVÉE et se taire sur le spécimen posé "
        f"dans une liste. Vu : {fautes}"
    )


@pytest.mark.parametrize("fonction", ["cmd", "dire", "echo", "note", "mal",
                                      "alerte", "printf", "bien"])
def test_le_garde_voit_une_commande_imprimee_PAR_UNE_FONCTION(
    fonction: str, tmp_path: Path,
) -> None:
    """LE CONTRE-ESSAI QUI MANQUAIT, ET QUI EXPLIQUE UN TROU DE HUIT MOIS.

    Le seul contre-essai du garde — `test_le_garde_lit_ce_qui_est_imprime_et_
    pas_le_reste` — est écrit en PYTHON. Or les deux chemins ne rendent pas la
    même matière : `textes_imprimes_python` rend la VALEUR de la chaîne,
    `textes_imprimes_shell` rendait la LIGNE, appel compris. Le shell était
    donc aveugle à toute commande imprimée sur une seule ligne, et personne ne
    pouvait s'en apercevoir : le garde qui l'aurait montré n'existait pas.

    C'est la forme la plus fréquente de fausse sécurité dans ce dépôt — un
    garde éprouvé sur UNE de ses entrées, déclaré éprouvé sur toutes.
    """
    fichier = tmp_path / "sonde.sh"
    fichier.write_text(
        "#!/usr/bin/env bash\n"
        f"{fonction} \"  sudo -u postgres psql -d ma_base -c 'SELECT 1'\"\n",
        encoding="utf-8",
    )
    vus = textes_imprimes_shell(fichier)
    fautes = [f for _, t in vus for f in commandes_sans_grappe(t)]
    assert fautes, (
        f"Une commande libpq imprimée par `{fonction}` n'est pas vue. "
        f"Textes extraits : {vus}"
    )


def test_le_garde_se_tait_sur_une_commande_imprimee_qui_porte_son_port(
    tmp_path: Path,
) -> None:
    """La moitié qui empêche le garde d'être désarmé à la première gêne."""
    fichier = tmp_path / "sonde.sh"
    fichier.write_text(
        "#!/usr/bin/env bash\n"
        "cmd \"  sudo -u postgres psql -p 5461 -d ma_base -c 'SELECT 1'\"\n",
        encoding="utf-8",
    )
    vus = textes_imprimes_shell(fichier)
    assert vus, "rien n'a été extrait : l'essai ne prouve rien"
    assert [f for _, t in vus for f in commandes_sans_grappe(t)] == []


def test_le_garde_voit_tout_ce_que_git_transporte() -> None:
    """Le périmètre n'est pas une liste de répertoires — c'est le dépôt.

    C'est la leçon que le dépôt s'est écrite lui-même : « le corpus à
    balayer, ce n'est pas docs/ : c'est tout ce que git transporte ». La
    zone aveugle qui a laissé vivre le `dropdb` sans `-p` bornait le contrôle
    manquant à trois répertoires ; le fichier fautif n'était dans aucun.
    """
    vus = {str(p.relative_to(RACINE)) for p in _fichiers_balayes()}
    for temoin in (
        "db/alembic/versions/0001_baseline_phase1b.py",   # là où vivait la faute
        "tests/garde_hermetique.py",                      # hors docs/bootstrap/ops
        "ops/install_check.sh",
        "bootstrap/checks/verify_install.sh",
        "docs/DEPANNAGE.md",
    ):
        assert temoin in vus, f"{temoin} échappe au balayage de G3"


# ---------------------------------------------------------------------------
# CE QUE CE GARDE NE COUVRE PAS
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ZoneAveugleG3:
    zone: str
    pourquoi: str


ZONES_NON_COUVERTES_G3: tuple[ZoneAveugleG3, ...] = (
    ZoneAveugleG3(
        "un remède assemblé à plus d'un saut",
        "On suit UN saut : le nom d'une constante de module écrit à l'endroit "
        "où l'on imprime. Un remède composé par deux fonctions successives, ou "
        "lu depuis un fichier de gabarits, n'est pas vu. Suivre plus loin "
        "serait une analyse de flot ; G1 déclare déjà ne pas en faire, et deux "
        "gardes qui prétendent des choses différentes sur le même dépôt est "
        "précisément ce qu'on essaie d'éviter.",
    ),
    ZoneAveugleG3(
        "une fonction de sortie qu'on n'a pas nommée",
        "`APPELS_DE_SORTIE` et `FONCTIONS_DE_SORTIE_SHELL` sont des listes, "
        "donc elles oublient. Un dépôt qui se donnerait demain un `raconter()` "
        "maison imprimerait sans être vu. L'inversion — énumérer ce qui "
        "N'IMPRIME PAS — n'a pas de sens ici : cette liste-là est infinie. Le "
        "prix est assumé et il est écrit.",
    ),
    ZoneAveugleG3(
        "le port porté par une variable dont on ne sait rien",
        "`psql -p \"$PORT\" -d b` est tenu pour sain. Rien ne prouve que "
        "`$PORT` vaut la grappe de CE cerveau ; il pourrait être vide, et "
        "`-p ''` retombe sur le défaut. Le garde vérifie qu'un port est "
        "DEMANDÉ, pas qu'il est juste — c'est le travail de `verify_install.sh`, "
        "qui, lui, remonte la socket jusqu'au processus.",
    ),
    ZoneAveugleG3(
        "l'hôte donné par omission",
        "Une commande peut porter son `-p` et viser quand même la mauvaise "
        "machine si la base est distante et que `-h` manque. Le dégât est réel "
        "mais d'une autre famille : `sudo -u postgres` n'a de sens qu'en local, "
        "et une base distante rend le remède faux pour une raison qui se voit. "
        "Le port, lui, échoue en SILENCE — c'est pour cela qu'on commence par "
        "lui.",
    ),
    ZoneAveugleG3(
        "ce qu'un humain tape et que le dépôt n'a jamais écrit",
        "Ce garde ne protège que les commandes que le PRODUIT imprime. La "
        "ligne qu'un ami compose lui-même à trois heures du matin n'est dans "
        "aucun fichier. Le seul recours contre celle-là est que tout ce qu'il a "
        "sous les yeux — manuel, messages, refus — porte l'exemple juste.",
    ),
)


def test_le_garde_declare_ce_qu_il_ne_couvre_pas() -> None:
    assert ZONES_NON_COUVERTES_G3, (
        "Un garde qui ne déclare aucune limite prétend n'en avoir aucune."
    )
    for z in ZONES_NON_COUVERTES_G3:
        assert len(z.pourquoi) > 80, (
            f"La zone « {z.zone} » ne dit pas assez POURQUOI elle n'est pas "
            "couverte. « Non couvert » sans raison mécanique est une excuse."
        )


def test_les_fonctions_de_sortie_existent_encore() -> None:
    """Les noms qu'on écoute sont-ils encore ceux que le dépôt appelle ?

    Une liste d'écoute qui ne correspond plus à rien rend le même vert qu'une
    liste juste. On exige donc qu'une bonne part des fonctions nommées soit
    réellement appelée quelque part dans le shell du dépôt.
    """
    shell = [p for p in _fichiers_balayes() if _est_du_shell(p)]
    corpus = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in shell)
    vivantes = [
        f for f in FONCTIONS_DE_SORTIE_SHELL
        if re.search(rf"^\s*{re.escape(f)}\b", corpus, re.MULTILINE)
    ]
    assert len(vivantes) >= 8, (
        "Trop peu des fonctions de sortie écoutées par G3 sont encore "
        f"appelées : {vivantes}. Le garde écoute un vocabulaire mort."
    )
