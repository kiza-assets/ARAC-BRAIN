"""La documentation dit-elle vrai — sur TOUS les documents, sans exception.

POURQUOI CE FICHIER EXISTE
==========================

Le dépôt avait déjà un garde F1 (« aucune trace de l'auteur »). Il bornait son
balayage à ``control_center/``. Il était vert, et **la réparation a eu
exactement la taille du garde-fou** : tout le reste est resté sale. La leçon a
été payée une fois ; ce module la prend au sérieux et ne connaît **aucun
répertoire**.

**Et il ne connaît plus non plus de type de fichier.** Le corpus s'est
longtemps arrêté aux ``.md`` — ``if f.endswith(".md")``, une ligne — et c'est
la cause mécanique du même défaut revenu cinq manches de suite : les faussetés
NOMMÉES étaient corrigées dans les manuels et survivaient dans les
commentaires du code, que personne ne balayait. Le corpus est maintenant
**tout ce que ``git`` transporte** et qui porte du texte ; hors du Markdown,
seules les **docstrings** et les **commentaires** sont lus, parce qu'eux seuls
s'adressent à un lecteur (voir ``_prose``).

**Et ce corpus ne s'effondre plus quand ``git`` n'est pas là.** Il était
obtenu par un ``check=True`` exécuté à la COLLECTE : dans une copie privée de
son ``.git`` — ce que reçoit quiconque télécharge une archive — toute la suite
tombait avant d'avoir exécuté un seul test, sur une exception qui ne disait
rien de la cause. Le corpus vient maintenant de ``tests/corpus_du_depot.py``,
qui replie sur le disque et **dit** qu'il l'a fait.

CE QUE CE MODULE NE LIT PAS, ET QUI LE LIT À SA PLACE
=====================================================
Hors Markdown, ``_prose`` s'arrête aux commentaires et aux docstrings — ce que
le développeur se dit à lui-même. **Ce que le PROGRAMME imprime à
l'utilisateur** (l'écran de fin du bootstrap, un refus, un remède) est le
corpus de ``tests/test_g4_tout_geste_prescrit_est_servi.py``, qui pose sur lui
une question voisine mais distincte : chaque geste prescrit est-il servi par
une capacité réelle ? Les deux corpus ne se recouvrent pas, et c'est
volontaire : deux gardes qui balaient le même texte avec des règles proches
finissent par diverger sans que personne sache lequel des deux ment.

Ce que ce module garde, ce n'est pas le style : c'est l'**exactitude**. Six
faussetés ont été trouvées à la main dans ce dépôt, et chacune avait la même
forme — une phrase vraie autrefois, laissée en place après que le code ou les
faits ont changé. Aucune n'aurait survécu à un contrôle mécanique. Les voici,
chacune avec le test qui la rattraperait aujourd'hui :

1. Quatre documents demandaient d'« ouvrir le cockpit chaque semaine pour
   trancher quelques propositions » et promettaient que « la calibration
   s'améliore quand vous validez ». Le cockpit n'a **aucune route
   d'écriture**, et `confidence` est **absent** des deux schémas de
   modification de l'API. Le lecteur attendait un effet qui ne pouvait pas
   venir, et concluait qu'il s'y prenait mal.
   → ``test_aucun_document_ne_promet_un_geste_que_le_code_ne_sert_pas``

2. Quatre documents affirmaient, **dans leurs sections consacrées à
   l'honnêteté**, que `CREATE DATABASE` et `alembic upgrade head` n'avaient
   « jamais tourné pour de vrai ». Deux installations complètes depuis une
   base vide les ont exécutés. Une section d'honnêteté périmée est la pire
   des faussetés : elle abîme la crédibilité de tout le reste.
   → ``test_aucun_document_ne_dit_jamais_d_une_commande_deja_executee``

3. Deux documents exigeaient du **même** contrôle deux verdicts
   incompatibles. L'un faisait échouer un utilisateur dont l'installation
   était saine.
   → ``test_les_deux_phrases_de_reussite_du_controle_sont_enseignees_ensemble``

4. Le §7f du README — la section où le dépôt promet de tout dire de ses
   résidus — déclarait « versionnés » deux fichiers que `.gitignore` exclut.
   → ``test_aucun_document_ne_declare_versionne_un_fichier_que_git_ignore``

5. Deux documents recommandaient encore `ARAC_SCHEMA` et `ARAC_ROLE_PREFIX`,
   que le bootstrap **refuse** désormais avec un code de sortie 6.
   → ``test_aucun_document_ne_recommande_un_reglage_que_le_bootstrap_refuse``

6. Deux commentaires de code affirmaient qu'une migration donnée « est la
   tête de la chaîne Alembic ». Elle l'a été ; `0034_memory_review_queue` est
   arrivé. Le raisonnement n'avait besoin que de l'APPARTENANCE à la chaîne,
   qui reste vraie. Un RANG, comme un compte, périme.
   → ``test_aucun_texte_ne_donne_un_rang_dans_la_chaine_alembic``

LA FORME DES RÈGLES — celle de ``bootstrap/lib/ui.sh``
======================================================

``ui.sh`` refuse mécaniquement une étape qui n'annonce pas ses trois raisons.
Le même principe est repris ici : la plupart des règles ci-dessous
n'**interdisent** pas un mot, elles exigent qu'il **voyage avec sa
contrepartie**. On peut nommer un geste absent — il faut dire dans le même
paragraphe qu'il est absent. On peut citer les deux phrases de succès du
contrôle — il faut les citer *toutes les deux*. C'est ce qui distingue un
garde d'une censure : le garde laisse écrire la vérité entière, et seulement
elle.

LES PRÉMISSES SONT ANCRÉES DANS LE CODE, PAS RECOPIÉES
=======================================================

Un garde documentaire qui recopie le fait qu'il vérifie pourrit avec lui. Les
tests ``test_le_cockpit_...``, ``test_la_confiance_d_un_atome_...`` et
``test_le_bootstrap_refuse_...`` établissent chacun, **depuis le code**, la
prémisse dont dépend une règle de rédaction. Le jour où le cockpit gagnera une
route d'écriture, c'est la prémisse qui tombera en premier — et son message
dira quels documents relire.

Hors-ligne : ce module ne lit que des fichiers et n'importe que des schémas.
Aucune base, aucun service, aucun réseau.
"""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess

import pytest

from tests.corpus_du_depot import REGIME, est_ignore, fichiers_du_depot

RACINE = pathlib.Path(__file__).resolve().parents[1]


# ===========================================================================
# LE CORPUS — tout ce que `git` transporte, aucun répertoire ni type privilégié
# ===========================================================================


#: Les suffixes que `git` transporte et qui portent du texte adressé à un
#: humain. La liste est là pour écarter le binaire et les données, jamais un
#: répertoire ni un rôle : le `.py` d'une migration y est autant que le `.md`
#: d'un manuel.
SUFFIXES_PORTEURS_DE_TEXTE = {
    ".md", ".py", ".sh", ".sql", ".toml", ".yml", ".yaml", ".ini", ".cfg",
    ".conf", ".js", ".css", ".html", ".txt", ".mako",
    ".template", ".modele", ".example", ".exemple",
}

#: Le marqueur de commentaire de chaque famille de fichiers. Ce qui n'est PAS
#: ici est lu en entier — c'est le cas du Markdown, qui est du texte de bout
#: en bout.
MARQUEUR_DE_COMMENTAIRE = {
    ".py": "#", ".sh": "#", ".toml": "#", ".yml": "#", ".yaml": "#",
    ".ini": "#", ".cfg": "#", ".conf": "#", ".template": "#", ".modele": "#",
    ".example": "#", ".exemple": "#", ".sql": "--", ".js": "//", ".css": "/*",
    ".mako": "##",
}


def _documents() -> list[pathlib.Path]:
    """Tout ce que `git` rendrait à un inconnu qui clone, et qui porte du texte.

    La liste vient de `tests/corpus_du_depot.py`, qui interroge `git` quand
    il est là et **replie sur le disque en le disant** quand il ne l'est pas.
    Cette fonction s'exécute à la COLLECTE : une exception ici emporte toute
    la suite, et c'est ce qui arrivait à quiconque travaillait dans une copie
    sans `.git`.

    **Le corpus n'est plus le Markdown.** Il l'a été, et c'est ce qui a laissé
    passer la cinquième manche du même défaut : les faussetés nommées étaient
    corrigées dans les ``.md`` et survivaient dans les ``.py``, où personne
    ne les balayait. La page canonique des scopes écrit la règle en toutes
    lettres — « le corpus à balayer, ce n'est pas ``docs/`` : c'est **tout ce
    que ``git`` transporte**, parce que le chiffre survit là où l'on ne
    balaie pas » — et cette fonction est l'endroit où elle s'applique.
    """
    vus = {
        f for f in fichiers_du_depot()
        if pathlib.PurePosixPath(f).suffix in SUFFIXES_PORTEURS_DE_TEXTE
        and (RACINE / f).is_file()
    }
    return [RACINE / f for f in sorted(vus)]


DOCUMENTS = _documents()


def _relatif(p: pathlib.Path) -> str:
    return str(p.relative_to(RACINE))


def _prose(doc: pathlib.Path) -> str:
    """Ce qui, dans ce fichier, s'adresse à un lecteur — et rien d'autre.

    Un ``.md`` est de la prose de bout en bout. Ailleurs, la prose est dans
    les **commentaires** et les **docstrings** ; le code, lui, n'est pas une
    affirmation adressée à quelqu'un, et le balayer produirait des reproches
    absurdes (une liste de mots interdits, un littéral SQL servi, le nom d'une
    variable). Ce sont exactement les faux positifs qui feraient désarmer le
    garde à la première gêne.

    Le texte rendu garde **une ligne pour une ligne** : ce qui n'est pas de la
    prose devient une ligne vide. Les numéros de ligne des reproches désignent
    donc le fichier réel, et deux commentaires séparés par du code sont deux
    paragraphes — jamais un seul, où la nuance de l'un couvrirait la fausseté
    de l'autre.
    """
    texte = doc.read_text(encoding="utf-8", errors="ignore")
    if doc.suffix == ".md":
        return texte

    lignes = texte.split("\n")
    garde = [""] * len(lignes)
    marqueur = MARQUEUR_DE_COMMENTAIRE.get(doc.suffix)
    if marqueur:
        for i, ligne in enumerate(lignes):
            nu = ligne.strip()
            if nu.startswith(marqueur):
                contenu = nu[len(marqueur):].lstrip("#!:-/* ")
                # Une ligne de commentaire VIDE (« # » seul) n'ouvre pas un
                # nouveau paragraphe : un bloc de commentaire se lit d'un
                # bloc, et sa nuance est presque toujours quelques lignes
                # plus bas que l'affirmation qu'elle nuance. La couper en
                # deux ferait reprocher au dépôt des phrases qu'il dément
                # lui-même six lignes plus loin.
                garde[i] = contenu if contenu else "·"

    if doc.suffix == ".py":
        try:
            arbre = ast.parse(texte)
        except SyntaxError:
            return "\n".join(garde)
        for noeud in ast.walk(arbre):
            corps = getattr(noeud, "body", None)
            if not isinstance(corps, list) or not corps:
                continue
            premier = corps[0]
            if not (isinstance(premier, ast.Expr)
                    and isinstance(premier.value, ast.Constant)
                    and isinstance(premier.value.value, str)):
                continue
            debut = premier.lineno - 1
            fin = (premier.end_lineno or premier.lineno) - 1
            for i, ligne in enumerate(lignes[debut:fin + 1], start=debut):
                if i < len(garde):
                    garde[i] = ligne.strip().strip('"').strip("'")
    return "\n".join(garde)


def test_le_corpus_couvre_tout_le_depot():
    """Un balayage qui ne lit rien passe toujours. C'est le premier piège.

    Les témoins nommés ici sont les fichiers où les faussetés ont été
    trouvées, plus les documents de tête. Restreindre le corpus à
    ``docs/`` — la tentation de l'avant-dernière manche — ou au seul
    Markdown — celle de la dernière — fait tomber ce test AVANT de faire
    passer les autres. C'est l'ordre qui compte : un corpus rétréci doit
    échouer bruyamment, jamais rendre les autres règles vertes en silence.
    """
    assert REGIME in ("git", "disque"), REGIME
    assert len(DOCUMENTS) >= 20, (
        f"corpus obtenu en régime « {REGIME} » : "
        + str([_relatif(p) for p in DOCUMENTS])
    )
    relatifs = {_relatif(p) for p in DOCUMENTS}
    for temoin in (
        "README.md", "GOAL.md", "CHANGELOG.md",
        "bootstrap/README.md", "mac/README.md",
        "docs/PREMIER-JOUR.md", "docs/PREMIER-MOIS.md", "docs/DEPANNAGE.md",
        "docs/FAQ.md", "docs/DEMARRAGE-RAPIDE.md", "docs/INSTALLATION.md",
        "docs/CONFIGURATION.md", "docs/ROADMAP.md",
        # Et les témoins HORS Markdown : le code exécuté, celui que le lecteur
        # ouvre quand il doute d'une phrase, et où quatre faussetés ont
        # survécu à quatre manches parce qu'aucun garde ne le lisait.
        "app/services/atom_links.py", "control_center/cc_v1/entities.py",
        "bootstrap/lib/database.sh", "bootstrap/generate_scopes.py",
        "tests/acceptance/sonde_apprentissage.py", ".env.example",
        "config/scopes.example.toml",
    ):
        assert temoin in relatifs, f"hors du balayage : {temoin}"
    # Et aucun répertoire, aucun TYPE de fichier n'est privilégié.
    assert any(not r.startswith("docs/") for r in relatifs)
    suffixes = {pathlib.PurePosixPath(r).suffix for r in relatifs}
    assert {".md", ".py", ".sh"} <= suffixes, sorted(suffixes)


def test_la_prose_extraite_est_bien_de_la_prose():
    """PRÉMISSE de l'élargissement : ce qu'on lit hors du Markdown.

    Trois faits, tenus sur un fichier fabriqué ici plutôt que sur le dépôt :
    un commentaire est lu, du code ne l'est pas, et **le numéro de ligne
    survit**. Sans ce dernier point, un reproche exact désignerait la mauvaise
    ligne, et le lecteur conclurait que le garde se trompe.
    """
    import tempfile

    source = (
        '"""Une docstring qui parle.\n'
        'Sur deux lignes.\n'
        '"""\n'
        'INTERDITS = ["ceci est du code, pas une affirmation"]\n'
        '# un commentaire, ligne 5\n'
        'x = 1  # une queue de ligne, qui n\'est pas de la prose\n'
    )
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "essai.py"
        p.write_text(source, encoding="utf-8")
        lignes = _prose(p).split("\n")
    assert "Une docstring qui parle." in lignes[0]
    assert "Sur deux lignes." in lignes[1]
    assert "code, pas une affirmation" not in lignes[3], lignes[3]
    assert lignes[4] == "un commentaire, ligne 5", lignes[4]
    assert lignes[5] == "", lignes[5]


def _a_plat(texte: str) -> str:
    """Le même texte, tous ses blancs écrasés en un seul espace.

    **Aucune règle de ce module ne doit chercher dans le texte brut.** Une
    phrase qui traverse un retour à la ligne est invisible à une recherche
    exacte, et c'est un défaut réel du dépôt, pas une hypothèse : la page
    canonique des scopes donnait pour preuve d'unicité un ``grep`` d'une
    phrase de quatre mots, et il ne voyait aucun des six fichiers fautifs —
    parce que la phrase y était coupée. Elle en a tiré la règle, en toutes
    lettres : « sur un texte dont on a d'abord écrasé les blancs, pour qu'une
    coupure de ligne ne cache plus rien ». C'est ici qu'elle s'applique.
    """
    return " ".join(texte.split())


def _paragraphes(texte: str) -> list[tuple[int, str]]:
    """Découpe le document en unités de lecture, avec le numéro de la première
    ligne de chacune.

    Une unité est un paragraphe (séparé par une ligne vide) — c'est là qu'une
    affirmation et sa nuance se tiennent, ou pas. **Sauf pour les tableaux** :
    une ligne de tableau est une affirmation complète et autonome, que le
    lecteur lit seule. Traiter un tableau comme un seul bloc laisserait la
    nuance d'une ligne couvrir la fausseté d'une autre — c'est exactement
    comme cela qu'un tableau d'état finit par mentir ligne à ligne tout en
    paraissant honnête dans l'ensemble.
    """
    blocs: list[tuple[int, str]] = []
    courant: list[str] = []
    debut = 1

    def clore() -> None:
        nonlocal courant
        if courant:
            blocs.append((debut, "\n".join(courant)))
            courant = []

    for n, ligne in enumerate(texte.split("\n"), start=1):
        if ligne.strip() == "":
            clore()
        elif ligne.lstrip().startswith("|"):
            clore()
            blocs.append((n, ligne))
        else:
            if not courant:
                debut = n
            courant.append(ligne)
    clore()
    return blocs


# ===========================================================================
# 1. LE GESTE IMPOSSIBLE — prémisses, puis règle de rédaction
# ===========================================================================


#: La seule route non-GET du cockpit, nommée et justifiée. C'est la
#: connexion : elle pose un cookie de session signé, et n'écrit **rien** —
#: ni en base, ni dans la mémoire. Une exception est un couple
#: (route, fichier), jamais un fichier en bloc : tout le reste de
#: `control_center/app.py` reste balayé.
CONNEXION_DU_COCKPIT = ("control_center/app.py", "/cc/login")


def test_le_cockpit_n_ecrit_dans_rien_qu_il_montre():
    """PRÉMISSE. Le jour où elle tombe, relisez tout ce que la règle 1 garde.

    Trois faits, tenus depuis le code plutôt que recopiés :
    la seule route non-GET du cockpit est la **connexion** ; aucun de ses
    modules ne porte de SQL d'écriture ; et le navigateur n'a qu'un `fetch`,
    sans `method`, donc GET.

    Le premier fait a été découvert par ce test, contre la formule trop ronde
    « le cockpit n'a aucune route d'écriture » : il en a une, elle pose un
    cookie. La nuance compte, parce qu'une phrase fausse par excès de
    simplicité se fait démentir par le premier lecteur qui ouvre le fichier.
    """
    routes = []
    for src in sorted((RACINE / "control_center").rglob("*.py")):
        rel = _relatif(src)
        for n, ligne in enumerate(src.read_text(encoding="utf-8",
                                                errors="ignore").split("\n"), 1):
            m = re.search(r"@\w+\.(post|put|patch|delete)\s*\(\s*[\"']([^\"']+)", ligne)
            if not m:
                continue
            if (rel, m.group(2)) == CONNEXION_DU_COCKPIT:
                continue
            routes.append(f"{rel}:{n} {m.group(1).upper()} {m.group(2)}")
    assert routes == [], (
        "le cockpit a gagné une route non-GET autre que la connexion : la "
        "documentation le décrit partout comme en lecture stricte — relisez "
        "PREMIER-JOUR, PREMIER-MOIS, DEPANNAGE, FAQ, DEMARRAGE-RAPIDE et "
        f"ROADMAP §2. {routes}"
    )
    ecritures = subprocess.run(
        ["grep", "-rniE", r"\b(insert into|update +arac\.|delete from)\b",
         "control_center"],
        cwd=RACINE, capture_output=True, text=True,
    ).stdout.strip()
    assert ecritures == "", (
        "du SQL d'écriture est apparu dans le cockpit, dont le rôle "
        "PostgreSQL ouvre pourtant toutes ses transactions en lecture "
        f"seule :\n{ecritures}"
    )
    appels = []
    for src in sorted((RACINE / "control_center").rglob("*.js")):
        texte = src.read_text(encoding="utf-8", errors="ignore")
        for n, ligne in enumerate(texte.split("\n"), 1):
            if "fetch(" in ligne:
                appels.append((f"{_relatif(src)}:{n}", ligne.strip()))
    assert appels, "plus aucun fetch : le cockpit a changé de nature, relisez la doc"
    for ou, ligne in appels:
        assert not re.search(r"method\s*:", ligne), (
            f"{ou} — un fetch du cockpit porte une méthode : le cockpit sait "
            "peut-être écrire, la documentation dit qu'il ne sait pas."
        )


def test_le_niveau_declare_et_la_trace_d_audit_ne_changent_jamais():
    """PRÉMISSE. `confidence` et `audit_source` ne sont modifiables par aucun
    chemin servi : absents du schéma de modification, hérités par la
    supersédure. Un atome né `agent_suggest` le reste.

    CE TEST S'APPELAIT « la confiance d'un atome ne change jamais après sa
    naissance », ET CE TITRE ÉTAIT FAUX. Il vérifiait — correctement — deux
    champs nommés `confidence` et `audit_source` ; il en tirait une phrase sur
    « la confiance », mot qui, dans ce dépôt, désigne aussi le NOMBRE
    `confidence_score`. Celui-là change : `PATCH /v1/atoms/<id>` avec
    `{"confidence_score": 95}` sur un atome à 40 rend 200, mesuré. Le titre
    d'un test est ce qu'on lit dans un rapport de `make test` : il enseigne
    autant que le code, et il doit donc être aussi exact.

    Lu dans les schémas plutôt que recopié : si un champ apparaît un jour, la
    prémisse tombe ici, et la doc doit être relue avant d'être crue.
    """
    from app.schemas.atom import AtomSupersede, AtomUpdate

    # Le témoin, sur la MÊME collection : sans lui, les absences ci-dessous
    # ne diraient pas si l'instrument voit quoi que ce soit.
    assert "confidence_score" in AtomUpdate.model_fields, (
        "le CHIFFRE a disparu du PATCH : l'écran de fin du bootstrap, qui "
        "décrit ce geste, redevient faux")

    for champ in ("confidence", "audit_source"):
        assert champ not in AtomUpdate.model_fields, (
            f"`{champ}` est devenu modifiable par PATCH — la documentation "
            "enseigne l'inverse."
        )
        assert f"new_{champ}" not in AtomSupersede.model_fields, (
            f"`{champ}` est devenu réglable à la supersédure — la "
            "documentation enseigne qu'il est hérité."
        )
    # L'héritage est dans le SQL du routeur, pas seulement dans le schéma.
    routeur = (RACINE / "app" / "routers" / "atoms.py").read_text(encoding="utf-8")
    for champ in ("confidence", "audit_source"):
        assert f'old["{champ}"]' in routeur, (
            f"la supersédure n'hérite plus `{champ}` de l'atome remplacé"
        )


#: Ce qu'un document ne peut pas promettre sans dire, dans le même
#: paragraphe, que ça n'existe pas. Chaque motif décrit un GESTE demandé au
#: lecteur ou un EFFET promis — jamais un simple vocabulaire : `auditor_validated`
#: doit pouvoir être défini, expliqué, et cité dans une sortie d'écran.
PROMESSES_SANS_ORGANE = (
    (r"cockpit[^.\n]{0,90}\bvalid(?:ez|er|ant|ation)", "valider dans le cockpit"),
    (r"\bvalid(?:ez|er)\b[^.\n]{0,90}cockpit", "valider dans le cockpit"),
    (r"tranch(?:er|ez)[^.\n]{0,60}proposition", "trancher des propositions"),
    (r"proposition[^.\n]{0,60}tranch(?:er|ez)", "trancher des propositions"),
    (r"agent_suggest[^.\n]{0,140}(?:devient|passe en)[^.\n]{0,60}auditor_validated",
     "promotion agent_suggest → auditor_validated"),
    # « recalibrer » n'est pas un mot interdit — c'est un GESTE qui n'existe
    # pas *quand on le demande au lecteur*. Le mot seul était refusé tant que
    # le corpus s'arrêtait au Markdown, où il ne paraît nulle part ; élargi au
    # code, il attrapait le nom d'une étiquette (`recalibration-candidate`) et
    # un seuil « jamais recalibré » — deux emplois justes. Une règle qui
    # reproche un vocabulaire finit désarmée à la première gêne ; celle-ci
    # exige donc que le geste soit ADRESSÉ.
    (r"recalibr\w*[^.\n]{0,80}\b(?:vous|votre|cockpit|utilisateur)\b",
     "« recalibrer » demandé au lecteur"),
    (r"\b(?:vous|votre|cockpit|utilisateur)\b[^.\n]{0,80}recalibr",
     "« recalibrer » demandé au lecteur"),
    (r"calibration\s+s'améliore", "calibration qui s'améliore"),
    (r"(?:confiance|calibration)\s+(?:monte|s'améliore)\s+quand\s+vous",
     "confiance qui monte quand vous agissez"),
)

#: Dire l'absence, c'est l'un de ces mots. La liste est courte exprès : une
#: liste longue laisserait passer n'importe quelle formule évasive.
MARQUEURS_D_ABSENCE = (
    "n'est pas branch", "pas branchée", "pas branché",
    "immuable", "immuables",
    "lecture stricte", "lecture seule",
    "aucune route d'écriture",
    "n'existe pas", "impossible",
    "ne change jamais", "ne changent jamais",
)


@pytest.mark.parametrize("doc", DOCUMENTS, ids=_relatif)
def test_aucun_document_ne_promet_un_geste_que_le_code_ne_sert_pas(doc):
    """Un geste absent peut être NOMMÉ ; il ne peut pas être PRESCRIT.

    La règle n'interdit pas d'écrire « la validation n'est pas branchée » —
    c'est même la seule phrase juste, et `docs/ROADMAP.md` la porte. Elle
    exige que la promesse et son démenti tiennent dans le même paragraphe,
    parce que c'est là que le lecteur les rencontre.
    """
    texte = _prose(doc)
    fautes = []
    for debut, para in _paragraphes(texte):
        plat = _a_plat(para)
        bas = plat.lower()
        if any(m in bas for m in MARQUEURS_D_ABSENCE):
            continue
        for motif, quoi in PROMESSES_SANS_ORGANE:
            if re.search(motif, plat, re.IGNORECASE):
                fautes.append(f"{_relatif(doc)}:{debut} — {quoi}")
                break
    assert fautes == [], (
        "geste promis sans l'organe qui l'exécuterait. Le cockpit n'a aucune "
        "route d'écriture et la confiance d'un atome ne change jamais après sa "
        "naissance : ou bien la phrase disparaît, ou bien elle dit dans le même "
        f"paragraphe que le geste n'existe pas.\n  " + "\n  ".join(fautes)
    )


# ===========================================================================
# 2. LE PASSÉ FAUX — « jamais » d'une commande qui a tourné
# ===========================================================================

#: Ces trois commandes ont été exécutées pour de vrai : deux installations
#: complètes depuis une base absolument vide, avec deux taxonomies
#: différentes, ont produit un `pg_dump --schema-only` identique. Aucun
#: document ne peut donc plus dire qu'elles n'ont « jamais » tourné.
#: Reproduction : voir `docs/ROADMAP.md` §1.2.
COMMANDES_EXERCEES = (
    r"CREATE DATABASE",
    r"alembic upgrade head",
    r"systemctl enable --now",
    r"bootstrap\.sh`?\s*en réel",
)

#: Les verbes par lesquels on dit qu'un geste a EU LIEU. « jamais » seul ne
#: veut rien dire — dans « il crée la TABLE, jamais le SCHÉMA », il porte sur
#: un objet, pas sur une exécution. C'est le corpus élargi qui l'a montré :
#: sur le seul Markdown, la coïncidence n'arrivait pas.
_EXECUTION = (r"tourn(?:é|er)|exécut|execut|jou(?:é|er)|lanc(?:é|er)|"
              r"rejou(?:é|er)|essay|éprouv|test(?:é|er)|appliqu|constat")

#: Les formules par lesquelles un document déclare qu'un geste n'a pas eu
#: lieu. Aucune n'est interdite en soi — elles le deviennent au contact d'un
#: geste dont l'exécution est établie.
MARQUEURS_DE_NON_EXERCICE = (
    rf"\bjamais\b[^.]{{0,40}}(?:{_EXECUTION})",
    rf"(?:{_EXECUTION})[^.]{{0,40}}\bjamais\b",
    r"[Nn]on vérifié",
    r"n'a pas (?:tourné|été|encore)",
    r"pas (?:exercé|éprouvé|rejoué)",
)

#: Citer la formule POUR LA DÉCLARER FAUSSE reste permis — c'est même le seul
#: moyen d'enseigner la leçon. Comme toutes les règles de ce module, celle-ci
#: n'interdit pas un mot : elle exige qu'il voyage avec sa contrepartie, dans
#: le même paragraphe. La liste est courte exprès.
MARQUEURS_DE_DEMENTI = (
    "ont exécuté", "les ont exécutés", "l'ont exécuté",
    "ont tourné", "a tourné pour de vrai",
    "était vrai", "est faux", "n'est plus vrai", "périm",
)


@pytest.mark.parametrize("doc", DOCUMENTS, ids=_relatif)
def test_aucun_document_ne_dit_jamais_d_une_commande_deja_executee(doc):
    """« jamais » est un absolu : il tombe au premier contre-exemple.

    Ce test ne défend pas l'orgueil du dépôt, il défend sa crédibilité — une
    section d'honnêteté en retard sur le produit retire de la valeur à tout
    ce qui l'entoure. Les « jamais » honnêtes restent permis, et il en
    reste : le pont n'a jamais tourné sur un Mac, et le chemin
    « installation neuve → première conversation → premier atome » n'a
    jamais été parcouru en entier, faute des deux clés payantes. Seuls les
    gestes de ``COMMANDES_EXERCEES`` sont couverts, parce que leur exécution
    est établie et rejouable.

    CE QUE CETTE DOCSTRING A PORTÉ, ET CE QUE ÇA MESURE DE LA MÉTHODE
    ================================================================
    Elle citait ici, en exemple d'un « jamais » honnête, « *la restauration
    d'une sauvegarde n'a jamais été rejouée* ». Elle **n'est plus vraie**
    depuis plusieurs versions : le bootstrap arme lui-même
    ``arac-<base>-restauration.timer`` (dimanche 03:00), ``make acceptance``
    la rejoue à son étape 8, et ``docs/INSTALLATION.md`` la déclare éprouvée
    dans sa propre section d'honnêteté. Le garde des sections d'honnêteté
    périmées en portait donc une. Ce n'est pas une ironie, c'est une mesure
    de sa portée — et elle a **deux** causes, l'une connue, l'autre non.

    1. ``COMMANDES_EXERCEES`` est une ÉNUMÉRATION de quatre motifs écrits à
       la main, et la restauration n'y figure pas. Un garde qui énumère
       hérite du défaut qu'il combat : il ne rattrape que ce qu'on a pensé à
       y mettre. Le ``CHANGELOG`` le disait déjà de son côté.

    2. Celle qu'on n'avait pas vue, et qui vaut pour TOUT le corpus :
       ``MARQUEURS_DE_DEMENTI`` est cherché dans le paragraphe ENTIER, et le
       mot « périm… » en fait partie. Un paragraphe qui **parle** de
       péremption est donc exempté du contrôle de sa propre péremption — et
       c'est exactement le paragraphe qu'écrit quiconque documente une
       section d'honnêteté. Mesuré, deux fois, sur ce fichier même : en
       injectant ici « alembic upgrade head n'a jamais été rejoué », ce test
       reste VERT ; en retirant du même paragraphe le seul mot « périmée »,
       il devient ROUGE et nomme la ligne. L'exemption reste nécessaire —
       citer une formule pour la déclarer fausse est le seul moyen
       d'enseigner la leçon — mais elle est aujourd'hui plus large que son
       intention, et c'est le premier endroit où regarder quand une fausseté
       traverse ce garde. La docstring ci-dessus est écrite pour ne PAS en
       bénéficier : ses « jamais » honnêtes vivent dans un paragraphe qui ne
       porte aucun marqueur de démenti, donc ce test les relit à chaque
       passage.
    """
    texte = _prose(doc)
    fautes = []
    for debut, para in _paragraphes(texte):
        plat = _a_plat(para)
        if any(m in plat.lower() for m in MARQUEURS_DE_DEMENTI):
            continue
        if not any(re.search(m, plat) for m in MARQUEURS_DE_NON_EXERCICE):
            continue
        for commande in COMMANDES_EXERCEES:
            if re.search(commande, plat):
                fautes.append(f"{_relatif(doc)}:{debut} — geste déclaré non "
                              f"exercé : « {commande} »")
    assert fautes == [], (
        "ces commandes ONT tourné : deux installations complètes depuis une "
        "base vide, avec deux taxonomies différentes, ont rendu un "
        "`pg_dump --schema-only` identique. Écrivez ce qui a été éprouvé et "
        "ce qui ne l'a pas été, daté, plutôt qu'un absolu qui périme.\n  "
        + "\n  ".join(fautes)
    )


# ===========================================================================
# 3. UN CONTRÔLE, DEUX VERDICTS DE RÉUSSITE
# ===========================================================================


def _phrases_du_controle() -> dict[str, str]:
    """Les verdicts que `verify_install.sh` peut réellement imprimer, lus
    dans le script — jamais recopiés."""
    src = (RACINE / "bootstrap" / "checks" / "verify_install.sh").read_text(
        encoding="utf-8")
    trouvees = {
        m.group(1).replace("'\\''", "'")
        for m in re.finditer(r"_c 1 '(Ce cerveau[^']*(?:'\\''[^']*)*)'", src)
    }
    return {p: p for p in trouvees}


def test_le_controle_a_bien_deux_phrases_de_reussite():
    """PRÉMISSE. Un échec fait échouer ; un simple point à surveiller, non —
    et le code de retour le dit (0)."""
    phrases = _phrases_du_controle()
    assert "Ce cerveau est sain." in phrases, phrases
    assert "Ce cerveau fonctionne." in phrases, phrases
    src = (RACINE / "bootstrap" / "checks" / "verify_install.sh").read_text(
        encoding="utf-8")
    bloc = src[src.index("if (( AVERTS > 0 ))"):]
    assert "Ce cerveau fonctionne." in bloc[:400], (
        "la branche « des points à surveiller » ne rend plus la phrase de "
        "réussite : la documentation qui l'enseigne doit être relue."
    )
    assert re.search(r"return 0", bloc[:600]), (
        "des avertissements font désormais échouer le contrôle — la "
        "documentation enseigne le contraire."
    )


@pytest.mark.parametrize("doc", DOCUMENTS, ids=_relatif)
def test_les_deux_phrases_de_reussite_du_controle_sont_enseignees_ensemble(doc):
    """Citer une seule des deux phrases fabrique un faux échec.

    Un utilisateur dont l'installation est saine mais porte des points à
    surveiller lit « ✓ Ce cerveau fonctionne. » Si son document ne lui a
    promis que « ✓ Ce cerveau est sain. », il croit avoir raté quelque chose,
    et recommence — c'est le pire coût qu'une documentation puisse infliger.
    """
    texte = _prose(doc)
    plat = _a_plat(texte)
    a_sain = "Ce cerveau est sain." in plat
    a_fonctionne = "Ce cerveau fonctionne." in plat
    if a_sain or a_fonctionne:
        assert a_sain and a_fonctionne, (
            f"{_relatif(doc)} ne cite qu'une des deux phrases de réussite de "
            "`verify_install.sh` (« Ce cerveau est sain. » = zéro échec ET zéro "
            "point à surveiller ; « Ce cerveau fonctionne. » = zéro échec, des "
            "points à surveiller). Les deux sont des réussites, code de retour 0."
        )
    fautes = [
        f"{_relatif(doc)}:{n}"
        for n, ligne in enumerate(texte.split("\n"), 1)
        if re.search(r"à surveiller\s+0\b", ligne)
        and "```" not in ligne
    ]
    assert fautes == [], (
        "« à surveiller 0 » posé comme critère : le nombre de points à "
        "surveiller dépend de l'installation, et n'a jamais empêché un cerveau "
        f"de vivre. Le seul critère est `en échec 0`.\n  " + "\n  ".join(fautes)
    )


# ===========================================================================
# 4. « VERSIONNÉ » — un mot que `git` peut contredire
# ===========================================================================

_CHEMIN_CITE = re.compile(r"`([A-Za-z0-9_.\-/]+\.[A-Za-z0-9]{1,6})`")


@pytest.mark.parametrize("doc", DOCUMENTS, ids=_relatif)
def test_aucun_document_ne_declare_versionne_un_fichier_que_git_ignore(doc):
    """Le seul juge de « versionné » est `git check-ignore`.

    Cette règle est générale par construction : elle ne connaît aucun chemin
    par avance, elle interroge `git` sur tout chemin qu'une phrase déclare
    versionné. Les phrases qui NIENT le versionnement sont ignorées — ce sont
    elles qu'on veut pouvoir écrire.

    (Elle ne nomme volontairement aucun fichier en exemple : le corpus
    élargi la fait maintenant passer sur elle-même, et un exemple cité dans
    une phrase qui porte le mot « versionné » se ferait reprocher à bon
    droit. Une règle qui ne survit pas à son propre balayage n'est pas une
    règle, c'est une exception.)
    """
    texte = _prose(doc)
    fautes = []
    for debut, para in _paragraphes(texte):
        for phrase in re.split(r"(?<=[.;:!?])\s+", _a_plat(para)):
            bas = phrase.lower()
            if "versionn" not in bas:
                continue
            if re.search(r"(?:ne\s+(?:sont|est)\s+pas|non|jamais|pas)\s+versionn", bas):
                continue
            for chemin in _CHEMIN_CITE.findall(phrase):
                cible = RACINE / chemin
                if not cible.exists():
                    continue
                if est_ignore(chemin):
                    fautes.append(f"{_relatif(doc)}:{debut} — « {chemin} » "
                                  "déclaré versionné, exclu par .gitignore")
    assert fautes == [], (
        "un lecteur qui clone ne recevra jamais ces fichiers : ce qu'on lui "
        f"promet à leur sujet ne peut donc pas se produire.\n  "
        + "\n  ".join(fautes)
    )


# ===========================================================================
# 5. UN RÉGLAGE QUE LE BOOTSTRAP REFUSE
# ===========================================================================


def _reglages_refuses() -> dict[str, str]:
    """Les réglages que `bootstrap/lib/config.sh` refuse, lus dans la LISTE
    qu'il déclare pour cela. Le jour où un réglage en sort — parce que le code
    aura appris à l'honorer — ce test le voit, et la doc peut rouvrir."""
    src = (RACINE / "bootstrap" / "lib" / "config.sh").read_text(encoding="utf-8")
    m = re.search(r"REGLAGES_NON_HONORES=\(([^)]*)\)", src)
    assert m, ("la liste des réglages non honorés a disparu de "
               "bootstrap/lib/config.sh — relisez INSTALLATION et CONFIGURATION "
               "avant de supprimer ce test.")
    return dict(p.split(":", 1) for p in m.group(1).split())


def test_le_bootstrap_refuse_bien_ce_reglage():
    """PRÉMISSE. `ARAC_SCHEMA` n'est pas « à éviter », il est refusé — et la
    raison est dans les migrations, qui écrivent `arac.memory_atoms` en
    toutes lettres.

    `ARAC_ROLE_PREFIX` était de la partie, et n'y est plus : les migrations
    DÉDUISENT désormais leurs cinq rôles du rôle d'administration sous lequel
    elles tournent (`db/alembic/roles.py`). Ce n'est pas un assouplissement,
    c'est le correctif de l'incident — un préfixe figé, c'est deux cerveaux
    qui se partagent des rôles globaux au cluster.

    La distinction que ce test fige : un SCHÉMA vit DANS une base, deux
    cerveaux ne peuvent pas se le disputer ; un RÔLE vit dans le cluster,
    au-dessus des bases, et c'est le seul des deux qui pouvait détruire le
    cerveau du voisin.
    """
    refuses = _reglages_refuses()
    assert refuses == {"ARAC_SCHEMA": "arac"}, refuses

    # La cause, pas le symptôme : les migrations nomment le SCHÉMA en dur…
    dur = subprocess.run(
        ["grep", "-rl", "arac.memory_atoms", "db/alembic/versions"],
        cwd=RACINE, capture_output=True, text=True,
    ).stdout.split()
    assert len(dur) >= 5, (
        "les migrations ne nomment plus le schéma en dur : le refus du "
        "bootstrap n'a peut-être plus lieu d'être, et la documentation peut "
        "rouvrir ce réglage."
    )
    # …et plus AUCUNE ne nomme un rôle en dur, ce qui est la raison pour
    # laquelle ARAC_ROLE_PREFIX a quitté cette liste. Si cette assertion
    # tombe, c'est le correctif de l'incident qui a régressé.
    roles_en_dur = subprocess.run(
        ["grep", "-rlE", r"TO arac_(app|agent|readonly|admin|backup)\b",
         "db/alembic/versions"],
        cwd=RACINE, capture_output=True, text=True,
    ).stdout.split()
    assert not roles_en_dur, (
        "ces migrations nomment de nouveau un rôle en dur : " + " ".join(roles_en_dur)
    )


#: Dire pourquoi le réglage n'existe pas, c'est l'un de ces mots.
MARQUEURS_DE_REFUS = (
    "refus", "refuse", "refusé",
    "ne peut pas", "ne peuvent pas",
    "seule valeur", "n'est pas honoré", "pas honorés",
    "en toutes lettres",
)

#: Poser le réglage refusé reste permis dans **un** cas : le montrer échouer.
#: Le paragraphe doit alors porter l'issue, pas seulement l'intention — c'est
#: la différence entre une démonstration et une recommandation déguisée.
MARQUEURS_DE_L_ECHEC_MONTRE = (
    "code de sortie 6", "code `6`", "code 6", "exit 6", "✗",
)


@pytest.mark.parametrize("doc", DOCUMENTS, ids=_relatif)
def test_aucun_document_ne_recommande_un_reglage_que_le_bootstrap_refuse(doc):
    """Nommer le réglage reste utile — c'est la leçon sur un schéma nommé en
    dur. Le nommer sans dire qu'il est refusé envoie l'utilisateur droit dans
    un `exit 6` qu'il attribuera à sa propre machine."""
    refuses = _reglages_refuses()
    texte = _prose(doc)
    fautes = []
    for debut, para in _paragraphes(texte):
        plat = _a_plat(para)
        bas = plat.lower()
        for nom, valeur in refuses.items():
            if nom not in plat:
                continue
            if not any(m in bas for m in MARQUEURS_DE_REFUS):
                fautes.append(f"{_relatif(doc)}:{debut} — « {nom} » cité sans "
                              "dire qu'il est refusé")
            autre = re.search(rf"{nom}=(?!{valeur}\b)\S+", plat)
            if autre and not any(m in bas for m in MARQUEURS_DE_L_ECHEC_MONTRE):
                fautes.append(f"{_relatif(doc)}:{debut} — « {autre.group(0)} » "
                              f"proposé sans montrer qu'il échoue ; seule valeur "
                              f"supportée : {valeur}")
    assert fautes == [], (
        "`bootstrap/lib/config.sh` s'arrête avec le code 6 sur ces réglages, "
        "parce que les migrations nomment le schéma et les quatre rôles en "
        f"toutes lettres.\n  " + "\n  ".join(fautes)
    )


# ===========================================================================
# 6. UN RANG DANS LA CHAÎNE ALEMBIC — la valeur qui périme le plus vite
# ===========================================================================


def _tete_reelle_de_la_chaine() -> set[str]:
    """La tête, recalculée depuis les fichiers de révision — jamais recopiée.

    Une révision qui n'est le ``down_revision`` de personne est une tête. Le
    motif est volontairement tolérant : ces fichiers écrivent tantôt
    ``revision = "0034_x"``, tantôt ``revision: str = "0034_x"``.
    """
    dossier = RACINE / "db" / "alembic" / "versions"
    revisions, precedentes = set(), set()
    for f in sorted(dossier.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        m = re.search(r"^revision\s*(?::[^=]+)?=\s*[\"']([^\"']+)", src, re.M)
        n = re.search(r"^down_revision\s*(?::[^=]+)?=\s*[\"']([^\"']+)", src, re.M)
        if m:
            revisions.add(m.group(1))
        if n:
            precedentes.add(n.group(1))
    return revisions - precedentes


#: « `00NN_x` est la tête de la chaîne » — un RANG, pas un fait. Il périme à la
#: migration suivante, et il l'a fait : « la tête est `0033` » a été écrit dans
#: quatre fichiers, puis `0034_memory_review_queue` est arrivé.
#: Le motif ne cherche PAS un numéro à côté : c'est ce qu'une première
#: version faisait, et elle ne voyait pas le cas réel — « la migration qui
#: crée `arac.atom_links` est la tête de la chaîne Alembic », où la révision
#: est désignée par ce qu'elle fait, sans son numéro. Ce qui se détecte, c'est
#: la FORME de l'affirmation : *quelque chose* est la tête, ou la chaîne
#: compte *tant* de révisions.
#: « révision » est un mot à deux emplois dans ce dépôt — la chaîne Alembic,
#: et les révisions d'un message brut (`raw_message_revisions`, où « 50
#: révisions » est un résultat de test parfaitement juste). Le compte n'est
#: donc reproché QUE dans le voisinage de la chaîne. C'est le corpus élargi
#: qui l'a appris : sur le seul Markdown, l'homonymie ne se rencontrait pas.
_RANG_DANS_LA_CHAINE = re.compile(
    r"(?:\b(?:tête|tete)\s+de\s+la\s+cha[îi]ne\b"
    r"|\b(?:alembic|cha[îi]ne)\b[^.]{0,80}\b\d{1,3}\s+r[ée]visions?\b"
    r"|\b\d{1,3}\s+r[ée]visions?\b[^.]{0,80}\b(?:alembic|cha[îi]ne)\b"
    r"|\bapplique\s+\d{1,3}\s+migrations?\b)",
    re.IGNORECASE,
)

#: Écrire le rang POUR DIRE qu'il ne se dit pas est exactement ce qu'on
#: veut lire : `README.md` et `docs/ROADMAP.md` le font, et c'est la seule
#: forme qui enseigne la leçon au lieu de la subir.
MARQUEURS_DE_REFUS_DU_RANG = (
    "ne nomme pas", "ne dit ni", "ne dit pas", "périm", "perim",
    "était écrit", "fait partie de la chaîne", "qu'on ne dit pas",
    "n'est un critère nulle part", "ni le nombre", "étaient faux",
    # Et la forme sous laquelle un rang est cité POUR ÊTRE dénoncé : celui
    # d'UNE installation, servi à tout le monde. C'est le défaut lui-même,
    # nommé ; l'interdire reviendrait à interdire d'en parler.
    "d'une installation", "servie comme", "a servi",
)


@pytest.mark.parametrize("doc", DOCUMENTS, ids=_relatif)
def test_aucun_texte_ne_donne_un_rang_dans_la_chaine_alembic(doc):
    """Le fait dont on a besoin, c'est l'APPARTENANCE, jamais le rang.

    « `0033_atom_links` est la tête de la chaîne, donc `alembic upgrade head`
    la pose » : le raisonnement n'utilise que la seconde moitié, et la
    première est fausse depuis `0034_memory_review_queue`. « fait partie de la
    chaîne qu'`alembic upgrade head` applique » dit la même chose et reste
    vrai quelle que soit la migration suivante.

    Cette règle a une prémisse qu'elle recalcule : si la tête réelle
    disparaissait ou se dédoublait, c'est le dépôt qu'il faudrait regarder
    avant la documentation.
    """
    tetes = _tete_reelle_de_la_chaine()
    assert len(tetes) == 1, (
        "la chaîne Alembic n'a plus exactement une tête — deux branches, ou "
        f"aucune : {sorted(tetes)}. Rien à reprocher à la documentation tant "
        "que le dépôt lui-même est ambigu."
    )
    fautes = []
    for debut, para in _paragraphes(_prose(doc)):
        plat = _a_plat(para)
        if any(m in plat.lower() for m in MARQUEURS_DE_REFUS_DU_RANG):
            continue
        if _RANG_DANS_LA_CHAINE.search(plat):
            fautes.append(f"{_relatif(doc)}:{debut}")
    assert fautes == [], (
        "un RANG dans la chaîne Alembic est donné comme un fait. La tête du "
        f"jour est {sorted(tetes)[0]!r}, et elle changera. Écrivez "
        "l'appartenance — « fait partie de la chaîne qu'`alembic upgrade "
        "head` applique » —, jamais le rang, et jamais un compte de "
        f"révisions.\n  " + "\n  ".join(fautes)
    )


# ===========================================================================
# 7. LA BOUCLE LOCALE N'EST PLUS UNE EXEMPTION — la prémisse manquait
# ===========================================================================
#
# Ce module balayait déjà TOUT ce que `git` transporte, et c'était le bon
# correctif. Il n'a pourtant rien vu du fait le plus neuf du dépôt : le jeton
# devenu exigé partout. `grep "boucle locale\|loopback\|jeton"` sur ce
# fichier ne rendait RIEN. Le corpus était le bon ; c'est la PRÉMISSE qui
# manquait — et l'ancienne règle a survécu dans le README, dans quatre
# docstrings de routers, dans la page de dépannage du pont, et dans un test
# qui s'était lui-même désigné comme le canari de ce durcissement.


def _porte_fermee_par_defaut() -> bool:
    """PRÉMISSE, lue dans le code : sans rien poser, le jeton est-il exigé ?

    On n'interroge pas l'environnement du test — il peut porter n'importe
    quoi. On interroge la RÈGLE : `bearer_requis` est une fonction pure, et
    `confiance_loopback=False` est ce que rend `etat_du_desserrage()` quand
    rien n'est écrit (le défaut de `ARAC_API_TRUST_LOOPBACK` est la chaîne
    `"0"`, qui n'est pas dans `_VALEURS_QUI_DESSERRENT`).
    """
    from app import auth

    return (
        "0" not in auth._VALEURS_QUI_DESSERRENT
        and auth.bearer_requis(
            path="/v1/dashboard/search",
            hote_pair="127.0.0.1",
            entetes_proxy_presents=False,
            confiance_loopback=False,
        )
    )


def test_le_jeton_est_bien_exige_sur_la_boucle_locale():
    """PRÉMISSE. Le jour où elle tombe, relisez tout ce que la règle 7 garde.

    Si le défaut redevenait « ouvert », la règle ci-dessous reprocherait au
    dépôt d'écrire la vérité — c'est le pire état possible pour un garde. Ce
    test est donc l'interrupteur : il échoue AVANT elle, et son message dit
    quoi relire.
    """
    from app import auth

    assert auth.bearer_requis(
        path="/v1/dashboard/search", hote_pair="127.0.0.1",
        entetes_proxy_presents=False, confiance_loopback=False,
    ), (
        "le jeton n'est plus exigé sur 127.0.0.1 sans desserrage : la règle 7 "
        "de ce module est devenue fausse, et tous les textes qu'elle a fait "
        "corriger sont à relire — README.md, docs/FAQ.md, docs/ROADMAP.md, "
        "docs/CONTRIBUER.md, bootstrap/README.md, bootstrap/lib/verify.sh, "
        "app/main.py, app/routers/{brain,ingest,missions}.py, docs/PONT-MAC.md."
    )
    assert auth.bearer_requis(
        path="/healthz", hote_pair="1.2.3.4",
        entetes_proxy_presents=False, confiance_loopback=False,
    ) is False, "/healthz doit rester public : la règle 7 le dit à tout le dépôt"
    assert "0" not in auth._VALEURS_QUI_DESSERRENT, (
        "la liste des valeurs qui DESSERRENT contient « 0 » : le sens de la "
        "liste s'est réinversé, et une coquille rouvrirait la porte"
    )


#: Les tournures de l'ancienne posture. Ce ne sont pas des mots interdits :
#: chacune est une AFFIRMATION qui était vraie et ne l'est plus. « Il n'y a
#: rien à défendre » a longtemps vécu dans cinq fichiers ; « jeton exigé hors
#: boucle locale » dans quatre docstrings ; « joignable sans Bearer » dans le
#: test qui se disait le canari du contraire.
_ANCIENNE_POSTURE = re.compile(
    r"(?:\brien\s+[àa]\s+d[ée]fendre\b"
    r"|\btunnel\s+\**est\**\s+l'authentification\b"
    r"|\bhors\s+boucle\s+locale\b"
    r"|\bboucle\s+locale\s+exempt[ée]e\b"
    r"|\bexempt(?:ion|[ée]e?)\b[^.]{0,60}\b(?:boucle\s+locale|loopback)\b"
    r"|\b(?:boucle\s+locale|loopback)\b[^.]{0,60}\bexempt(?:ion|[ée]e?)\b"
    r"|\b(?:joignable|accessible|atteignable)\b[^.]{0,40}\bsans\s+(?:bearer|jeton)\b"
    r"|\bsans\s+bearer\b[^.]{0,40}\bloopback\b"
    r"|\bloopback\b[^.]{0,40}\bsans\s+bearer\b"
    r"|\bjeton\b[^.]{0,40}\bn'est\s+pas\s+(?:exig[ée]|requis|n[ée]cessaire)\b)",
    re.IGNORECASE,
)

#: La seule dispense : le paragraphe cite la tournure POUR LA DÉCLARER
#: PÉRIMÉE. C'est la forme qui enseigne au lieu de subir, et l'interdire
#: reviendrait à interdire de raconter pourquoi le défaut a changé — c'est-à-dire
#: à refabriquer l'implicite qui avait laissé la porte ouverte.
MARQUEURS_DE_POSTURE_PERIMEE = (
    # Le passé, dit en toutes lettres.
    "jusqu'ici", "jusqu'alors", "valait", "a changé", "ont changé",
    "disait", "disaient", "écrivait", "écrivaient", "a longtemps",
    "l'a écrit", "affirmait", "s'appelait", "ancienne", "d'avant",
    "a d'abord été", "était faux", "c'était faux", "n'était pas assez",
    # La négation, dite en toutes lettres.
    "ne veut pas dire", "l'inverse", "périm", "perim",
    "n'est plus", "ne sont plus", "n'étant plus", "plus exempt",
    "est morte", "sont mortes", "désarmé", "desarme",
    "ne tient pas lieu", "retourné", "désormais", "desormais",
)


@pytest.mark.parametrize("doc", DOCUMENTS, ids=_relatif)
def test_aucun_texte_n_exempte_la_boucle_locale_du_jeton(doc):
    """L'exemption de boucle locale est morte : plus un texte ne l'enseigne.

    Le jeton porteur est exigé de TOUTE requête, `127.0.0.1` compris ; seul
    `/healthz` est public. Ces deux phrases ne sont plus vraies, et un lecteur
    qui tombe sur « il n'y a rien à défendre » ou « jeton exigé hors boucle
    locale » conclut qu'il n'a rien à poser et rien à surveiller — c'est très exactement la conclusion qui a
    laissé un compte `nobody` lire la mémoire d'un cerveau voisin.

    La règle n'interdit pas d'en PARLER : un paragraphe qui cite la tournure
    pour la déclarer périmée passe. C'est la seule forme qui transmette la
    leçon, et le dépôt l'écrit déjà à six endroits.
    """
    assert _porte_fermee_par_defaut(), (
        "prémisse tombée — voir test_le_jeton_est_bien_exige_sur_la_boucle_locale"
    )
    fautes = []
    for debut, para in _paragraphes(_prose(doc)):
        plat = _a_plat(para)
        bas = plat.lower()
        if any(m.lower() in bas for m in MARQUEURS_DE_POSTURE_PERIMEE):
            continue
        if _ANCIENNE_POSTURE.search(plat):
            fautes.append(f"{_relatif(doc)}:{debut}")
    assert fautes == [], (
        "l'ancienne posture réseau est enseignée comme un fait. Le jeton est "
        "exigé de TOUTE requête, boucle locale comprise (`app/auth.py`) ; le "
        "tunnel dit d'où vient une requête, jamais qui l'envoie. Écrivez ce "
        "qui est vrai — ou citez l'ancienne phrase POUR dire qu'elle est "
        "périmée, ce qui est la seule façon d'en tirer la leçon.\n  "
        + "\n  ".join(fautes)
    )


# ===========================================================================
# 8. LA ROUTE MORTE CITÉE PAR UN MANUEL
# ===========================================================================
#
# LE DÉFAUT, MESURÉ, ET LA MANCHE OÙ IL A ÉTÉ VU. En remettant dans `docs/FAQ.md`
# la phrase « Pour valider une proposition, appelez `POST /v1/atoms/valider` »
# — une route qui n'existe pas — ce fichier rendait **3 025 passed**. Le même
# défaut mis dans un écran du produit faisait rougir G4 depuis une manche. Deux
# gardes, deux corpus, et la faute passait par celui des deux que le lecteur
# ouvre en premier.
#
# LA DIVISION DU TRAVAIL RESTE CELLE QUI EST ÉCRITE EN TÊTE DE G4 : Markdown
# ici, écrans du produit là-bas. Ce qui change, c'est qu'on ne dupliquait pas
# seulement une règle — on laissait un trou. Les capacités sont lues au même
# endroit, dans le produit (`routes_servies()`), jamais recopiées : le jour où
# la route naît, ce garde se tait tout seul.
#
# POURQUOI L'IMPORT EST DIFFÉRÉ. `test_g4` importe ce module-ci au chargement
# (`MARQUEURS_D_ABSENCE`, `_a_plat`). L'import symétrique doit donc se faire
# DANS la fonction, sinon les deux modules s'attendent l'un l'autre.
#
# CE QUE CETTE RÈGLE NE JUGE PAS, ET POURQUOI — la leçon des dix reproches faux
# ==============================================================================
# G4 raconte ce qui arrive quand on applique une règle de prose à une matière
# qui n'en est pas : dix reproches, dix faux, et une règle désarmée le soir
# même. On borne donc, et chaque borne a sa raison MESURÉE sur le corpus réel :
#
#   · seuls les fichiers `.md` — un `POST /v1/…` dans un docstring de
#     `app/schemas/atom.py` documente un CONTRAT, il ne prescrit pas un geste ;
#   · `CHANGELOG.md` est hors corpus : un journal des versions dit ce qu'une
#     route ÉTAIT, et le lui reprocher reviendrait à interdire de tenir un
#     journal. Mesuré : quatre citations de routes retirées, toutes justes ;
#   · `tests/` est hors corpus : un test NOMME une route morte pour prouver
#     qu'elle est morte — c'est la ligne du dessus, et celle de G4 ;
#   · une citation TRONQUÉE (`GET /v1/dashboard/…`, ou une ligne coupée au
#     milieu d'un chemin) est acceptée dès qu'un préfixe servi existe : trois
#     cas réels, trois faux reproches évités, et on ne devine pas ce qu'un
#     lecteur ne voit pas non plus ;
#   · un paragraphe qui NOMME l'absence est exempté, comme partout ici :
#     « `POST /v1/atoms/valider` n'existe pas » est la seule phrase juste.


def _segments_de_route(chemin: str) -> list[str]:
    return [p for p in chemin.strip("/").split("/") if p]


def _colle(vu: str, motif: str) -> bool:
    """Un segment cité tombe-t-il sur un segment servi ? `{}` prend tout."""
    return vu == motif or motif == "{}"


def route_servie(methode: str, chemin: str) -> bool:
    """Cette route existe-t-elle dans l'une des deux applications ?

    Trois formes de citation sont reconnues comme JUSTES, et elles ont toutes
    été rencontrées dans les manuels de ce dépôt :
      · le paramètre écrit en clair — `GET /cc/v1/scopes/travail/strategie`
        tombe sur `/cc/v1/scopes/{}` ;
      · le paramètre laissé en suspens — `PATCH /v1/atoms/<id>`, dont le motif
        de citation ne garde que `/v1/atoms/` ;
      · la citation TRONQUÉE par une ellipse ou par un retour à la ligne.
    """
    from tests.test_g4_tout_geste_prescrit_est_servi import routes_servies

    chemin = chemin.rstrip(".,;:)!?")
    tronque = chemin.endswith("/")
    vus = _segments_de_route(chemin)
    for m, motif in routes_servies():
        if m != methode.upper():
            continue
        servis = _segments_de_route(motif)
        if tronque:
            # On ne devine pas la fin d'un chemin coupé : un préfixe servi
            # suffit. Fail-open ASSUMÉ, et borné à la troncature.
            if len(servis) >= len(vus) and all(map(_colle, vus, servis)):
                return True
            continue
        if len(servis) == len(vus) and all(map(_colle, vus, servis)):
            return True
        # Un convertisseur `:path` mange plusieurs segments d'un coup.
        if servis and servis[-1] == "{}" and len(vus) > len(servis) and all(
                map(_colle, vus, servis[:-1])):
            return True
    return False


def _manuels() -> list[pathlib.Path]:
    """Les manuels : ce qu'un lecteur ouvre pour savoir quoi taper."""
    return [d for d in DOCUMENTS
            if _relatif(d).endswith(".md")
            and _relatif(d) != "CHANGELOG.md"
            and not _relatif(d).startswith("tests/")]


def routes_mortes_citees() -> list[str]:
    """Les routes qu'un manuel fait appeler et que le produit ne sert pas."""
    from tests.test_g4_tout_geste_prescrit_est_servi import _routes_citees

    fautes: list[str] = []
    for doc in _manuels():
        for debut, para in _paragraphes(_prose(doc)):
            plat = _a_plat(para)
            if any(m in plat.lower() for m in MARQUEURS_D_ABSENCE):
                continue
            for methode, chemin in _routes_citees(plat):
                if "<" in chemin or ">" in chemin:
                    continue
                if route_servie(methode, chemin):
                    continue
                fautes.append(
                    f"{_relatif(doc)}:{debut} — « {methode} {chemin} » n'est "
                    "servie par aucune des deux applications"
                )
    return fautes


def test_aucun_manuel_ne_fait_appeler_une_route_que_le_produit_ne_sert_pas():
    """Une route citée dans un manuel est une route qu'on va taper.

    C'est le geste le plus littéral de tout le dépôt : il n'y a rien à
    interpréter, on recopie et on appelle. Un 404 à ce moment-là n'apprend pas
    « cette route n'existe pas » — il apprend « mon installation est cassée »,
    et c'est le contraire de ce qu'un manuel doit produire.
    """
    fautes = routes_mortes_citees()
    assert fautes == [], (
        "un manuel fait appeler une route morte. Ou bien la phrase nomme la "
        "route qui existe, ou bien elle dit dans le même paragraphe que "
        "celle-ci n'existe pas — c'est la seule forme qui enseigne.\n  "
        + "\n  ".join(fautes)
    )


def test_la_regle_des_routes_sait_encore_rougir():
    """TÉMOIN. Une règle qui ne peut plus rien voir est verte pour la pire des
    raisons, et ce dépôt a déjà payé ce défaut trois fois.

    On éprouve les deux bords sur des chemins écrits ici, sans toucher aux
    manuels : la route morte est vue, la route servie ne l'est pas.
    """
    assert not route_servie("POST", "/v1/atoms/valider"), (
        "la route morte témoin est devenue servie : si le produit sait "
        "désormais valider, c'est toute la famille « le cockpit ne tranche "
        "rien » qui est à relire — ici, dans G4, et dans les manuels."
    )
    assert route_servie("GET", "/v1/atoms"), (
        "la règle ne reconnaît plus une route pourtant servie : elle est sur "
        "le point de reprocher tout le corpus, et donc d'être désarmée."
    )
    assert route_servie("PATCH", "/v1/atoms/"), (
        "le paramètre laissé en suspens (`PATCH /v1/atoms/<id>`) doit rester "
        "accepté : le refuser reprocherait la forme JUSTE."
    )


# ===========================================================================
# 9. LE MODULE LUI-MÊME
# ===========================================================================


def test_le_module_de_garde_est_lui_meme_lisible():
    """Un garde dont on ne peut pas lire les règles finit par être contourné
    plutôt que corrigé : ce test échoue si le fichier cesse d'être du Python
    analysable, ou si l'un des tests ci-dessus perd sa raison écrite."""
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    arbre = ast.parse(source)
    sans_raison = [
        n.name for n in arbre.body
        if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
        and not ast.get_docstring(n)
    ]
    assert sans_raison == [], (
        "une règle sans raison écrite est une superstition : " f"{sans_raison}"
    )
