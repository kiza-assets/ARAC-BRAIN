"""G5 — UN ÉCRAN NE PROMET PAS UN EFFET QUE LE PRODUIT N'A PAS.

CE QUE CE GARDE FERME, ET POURQUOI IL A FALLU UN CINQUIÈME
==========================================================
G4 vérifie qu'un GESTE prescrit tombe sur un organe réel — « cette route
existe-t-elle ? ». Il l'écrit lui-même dans ses zones non couvertes : « le
geste servi mais SANS EFFET » lui échappe. C'est exactement par là que la
fausseté est revenue.

L'écran de fin de `bootstrap/bootstrap.sh` — le seul écran obligatoire du
parcours — a porté, dans la leçon « 96 % des rappels rendus en confiance
basse », la phrase suivante :

    « … et le cerveau s'en sert pour classer : sous 50 il éloigne, à 85 et
      plus il rapproche, de trois centièmes au plus. »

Le geste existait (`PATCH /v1/atoms/<id> {"confidence_score": …}` rend 200,
G4 le voyait servi), et l'effet n'existait pas. MESURÉ le 9 août 2026 sur un
cerveau posé par le vrai chemin (« vide1brain », grappe 5496, API 8320) :
deux atomes au texte STRICTEMENT identique, l'un à `confidence_score = 95`,
l'autre à `10`, remontent du même `POST /v1/atoms/recall` à la distance
`1.105593236593197` — la MÊME, au dernier chiffre.

La cause est dans le code et non dans la mesure : `recall()` fige sa réponse
sur un kNN dense pur, et le seul organe qui pèse la confiance
(`ConfidenceModifier`, `app/context/calibration.py`) n'est atteint que par
`context_shadow.serve_r3`, lui-même gardé par `serve_enabled_for()` — deux
drapeaux d'environnement, `ARAC_CE_SERVE_CORTEX_DEDUP` et
`ARAC_CE_SERVE_CANARI`, que le bootstrap n'écrit nulle part, et qui ne
concernent de toute façon que deux consommateurs internes.

C'EST LA MÊME FAMILLE QUE LA PREUVE VERTE PAR CONSTRUCTION
==========================================================
`tests/test_une_assertion_negative_doit_pouvoir_rougir.py` refuse une
assertion qui ne peut pas échouer. Celui-ci refuse une PHRASE qui ne peut pas
être vérifiée par le lecteur : elle décrit un effet, le lecteur n'a aucun
moyen de le constater, et elle reste imprimée sept manches de suite. Les deux
gardes protègent la même chose — qu'une affirmation du produit ait un
contre-exemple possible.

LES TROIS FAITS QUE CE GARDE TIENT ENSEMBLE
===========================================
1. LE CHEMIN SERVI EST AVEUGLE À LA CONFIANCE, et il l'est par construction :
   la réponse de `recall` est bâtie avant tout appel au moteur de contexte, et
   le moteur est derrière un drapeau absent de l'installation.
2. TANT QUE (1) TIENT, l'écran de fin ne doit pas dire le contraire.
3. LE SEUL EFFET RÉEL DU NOMBRE — l'archivage à l'écriture sous 70 — est lu
   dans le trigger SQL lui-même, jamais recopié : si la migration change de
   seuil ou de moment, c'est ici que ça rougit, et la leçon est à réécrire.

CE QUE CE GARDE NE COUVRE PAS — écrit, pas découvert
====================================================
Voir `ZONES_NON_COUVERTES`. En particulier il ne juge QUE l'effet de la
confiance sur le rappel et l'archivage : il n'a pas de forme générale pour
« cette phrase décrit-elle un effet réel ? ». Aucune n'existe. Ce qu'il
apporte, c'est qu'un défaut qui a coûté sept manches ne peut plus revenir en
silence sur cet écran-là.

Hors-ligne comme toute la suite : il lit des fichiers, il n'ouvre ni base ni
réseau.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]

VERIFY_SH = RACINE / "bootstrap" / "lib" / "verify.sh"
ROUTEUR_ATOMES = RACINE / "app" / "routers" / "atoms.py"
MIGRATION = RACINE / "db" / "migrations" / "01_init.sql"
OMBRE = RACINE / "app" / "services" / "context_shadow.py"
CALIBRATION = RACINE / "app" / "context" / "calibration.py"

ZONES_NON_COUVERTES: tuple[tuple[str, str], ...] = (
    ("les effets AUTRES que ceux de la confiance",
     "Ce garde tient le rappel et l'archivage. « Le cycle digère par "
     "tranches », « la sauvegarde tourne toutes les nuits » : rien ici ne les "
     "vérifie. Ils relèvent de `make acceptance`, sur un cerveau réel."),
    ("la formulation, tant qu'elle évite les mots surveillés",
     "Une phrase qui promettrait le même effet avec un vocabulaire neuf "
     "passerait. Le garde surveille des tournures NOMMÉES, apprises d'une "
     "fausseté réelle — il ne comprend pas le français."),
    ("l'effet une fois le drapeau ARMÉ",
     "Si `ARAC_CE_SERVE_CORTEX_DEDUP=1` est posé, le moteur R3 décide, et ce "
     "qu'il rend alors se mesure sur un cerveau, pas ici. Le garde rougit "
     "justement pour qu'on réécrive la leçon ce jour-là."),
    ("la DOCUMENTATION",
     "`docs/` est gardé par `tests/test_la_doc_dit_vrai.py`. Ce garde-ci ne "
     "lit que ce que le PROGRAMME imprime — c'est précisément l'écart qui a "
     "fait qu'une correction a atteint les manuels sept fois sans atteindre "
     "l'installateur."),
)


# ===========================================================================
# CE QUE LE PRODUIT FAIT RÉELLEMENT — lu dans le code, jamais recopié
# ===========================================================================


def _source(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def corps_de_recall() -> str:
    """Le corps de `recall()` tel qu'il est écrit, docstring exclue."""
    arbre = ast.parse(_source(ROUTEUR_ATOMES))
    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "recall":
            corps = list(n.body)
            if corps and isinstance(corps[0], ast.Expr) \
                    and isinstance(corps[0].value, ast.Constant):
                corps = corps[1:]
            return "\n".join(ast.unparse(x) for x in corps)
    raise AssertionError(
        "`recall` a disparu de app/routers/atoms.py : le rappel servi n'est "
        "plus là où ce garde le cherche, et toute la leçon « 96 % » est à "
        "relire sur le nouveau chemin.")


def le_rappel_servi_pese_la_confiance() -> bool:
    """Le chemin SERVI de `/recall` fait-il intervenir `confidence_score`
    dans son classement, sans qu'aucun drapeau soit à armer ?

    Deux conditions, et il faut les DEUX pour répondre oui :
      · le tri de la requête servie nomme la confiance ;
      · ou bien le moteur de contexte est appelé sans passer par
        `serve_enabled_for` — c'est-à-dire sans porte.
    """
    corps = corps_de_recall()

    # (a) le SQL servi trie-t-il sur la confiance ?
    tri = re.search(r"ORDER BY(.{0,200}?)LIMIT", corps, re.S | re.I)
    if tri and "confidence" in tri.group(1).lower():
        return True

    # (b) le moteur de contexte est-il atteint sans porte ?
    #     `serve_r3` est le SEUL chemin par lequel une décision R3 remplace la
    #     réponse dense ; s'il est appelé hors d'un test sur
    #     `serve_enabled_for`, le pesage devient inconditionnel.
    if "serve_r3" in corps and "serve_enabled_for" not in corps:
        return True

    return False


def drapeaux_de_serve() -> list[str]:
    """Les variables d'environnement qui ouvrent le chemin servi du moteur."""
    return sorted(set(re.findall(r'FLAG_SERVE_\w+\s*=\s*"([^"]+)"', _source(OMBRE))))


def drapeaux_poses_par_l_installation() -> list[str]:
    """Ceux de ces drapeaux que le bootstrap ÉCRIT réellement quelque part.

    Un drapeau seulement NOMMÉ (contrat de variables, liste d'audit) n'est pas
    posé : ce qui compte est `poser_var`/`export`/`NOM=valeur` dans ce que
    l'installation exécute.
    """
    poses: list[str] = []
    fichiers = [p for p in (RACINE / "bootstrap").rglob("*")
                if p.is_file() and p.suffix in {".sh", ".py", ".template", ""}]
    fichiers += [p for p in (RACINE / "ops").rglob("*") if p.is_file()]
    for nom in drapeaux_de_serve():
        motif = re.compile(rf"(poser_var[^\n]*{re.escape(nom)}|^\s*(export\s+)?"
                           rf"{re.escape(nom)}\s*=\s*\S)", re.M)
        for f in fichiers:
            try:
                if motif.search(f.read_text(encoding="utf-8", errors="ignore")):
                    poses.append(nom)
                    break
            except OSError:
                continue
    return poses


def seuil_du_declencheur() -> tuple[str, int, str]:
    """(moment, seuil, trace d'audit) lus DANS le trigger SQL lui-même."""
    sql = _source(MIGRATION)
    corps = re.search(
        r"CREATE OR REPLACE FUNCTION arac\.tg_auto_archive_low_confidence.*?"
        r"\$\$ LANGUAGE plpgsql;", sql, re.S)
    assert corps, (
        "`arac.tg_auto_archive_low_confidence` a disparu de la migration : le "
        "seul effet réel du score de confiance n'existe plus, et la leçon "
        "« 96 % » de bootstrap/lib/verify.sh est à réécrire de fond en comble.")
    seuil = re.search(r"confidence_score\s*<\s*(\d+)", corps.group(0))
    trace = re.search(r"audit_source\s*=\s*'([a-z_]+)'", corps.group(0))
    moment = re.search(
        r"CREATE TRIGGER memory_atoms_auto_archive\s+(BEFORE|AFTER)\s+"
        r"(INSERT|UPDATE)", sql)
    assert seuil and trace and moment, corps.group(0)[:400]
    return f"{moment.group(1)} {moment.group(2)}", int(seuil.group(1)), trace.group(1)


def lecon_de_la_confiance() -> str:
    """La leçon « 96 % » telle qu'elle sera IMPRIMÉE, guillemets compris."""
    src = _source(VERIFY_SH)
    debut = src.find('lecon "96 % des rappels rendus en confiance basse"')
    assert debut != -1, (
        "la leçon « 96 % des rappels rendus en confiance basse » a disparu de "
        "bootstrap/lib/verify.sh. Si elle a été renommée, ce garde ne lit plus "
        "rien et devient vert par construction — c'est exactement ce qu'il "
        "existe pour empêcher. Renommez-le en même temps qu'elle.")
    fin = src.find('\n    lecon "', debut + 10)
    return src[debut:fin if fin != -1 else len(src)]


# ===========================================================================
# LE GARDE
# ===========================================================================

#: Les tournures par lesquelles la fausseté s'est réellement écrite. Elles
#: promettent toutes le MÊME effet : que le nombre pèse sur ce qui remonte.
TOURNURES_DE_CLASSEMENT: tuple[str, ...] = (
    "s'en sert pour classer",
    "sert pour classer",
    "il éloigne",
    "il rapproche",
    "les rapproche",
    "les éloigne",
    "remonte plus haut",
    "remontent plus haut",
    "fait remonter",
    "pèse sur le rappel",
)


def promesses_de_classement(texte: str) -> list[str]:
    """Les tournures surveillées présentes dans `texte`. Fonction et non test,
    pour la même raison que `gestes_sans_organe` dans G4 : un garde qu'on ne
    peut pas éprouver sur une entrée fabriquée n'est pas éprouvé du tout."""
    bas = texte.lower()
    return [t for t in TOURNURES_DE_CLASSEMENT if t in bas]


def test_le_rappel_servi_est_aveugle_a_la_confiance() -> None:
    """FAIT 1 — mesuré sur cerveau réel, tenu ici sur le code.

    Deux atomes au texte identique, 95 et 10 : même distance à sept
    décimales. La raison est structurelle et c'est elle qu'on garde.
    """
    assert not le_rappel_servi_pese_la_confiance(), (
        "le rappel SERVI pèse désormais la confiance sans porte. C'est une "
        "bonne nouvelle, et elle a un prix : la leçon « 96 % » de "
        "bootstrap/lib/verify.sh doit REDIRE que le nombre classe, ce qu'elle "
        "nie aujourd'hui noir sur blanc. Corrigez l'écran, puis ce test.")

    drapeaux = drapeaux_de_serve()
    assert drapeaux, (
        "aucun drapeau de serve n'est plus déclaré dans "
        "app/services/context_shadow.py : ou le moteur est servi "
        "inconditionnellement, ou il a disparu. Les deux changent la leçon.")
    poses = drapeaux_poses_par_l_installation()
    assert not poses, (
        f"l'installation pose maintenant {poses} : le moteur de contexte est "
        f"servi sur un cerveau neuf, la confiance pèse sur le rappel, et "
        f"l'écran de fin ment dans l'autre sens.")


def test_l_ecran_de_fin_ne_promet_pas_le_classement_par_la_confiance() -> None:
    """FAIT 2 — la conséquence du fait 1, sur le seul écran obligatoire.

    C'est ce test qui aurait rougi pendant les sept manches.
    """
    lecon = lecon_de_la_confiance()
    # TÉMOIN — sans lui, un `find` qui rendrait une chaîne vide ferait passer
    # l'assertion d'absence ci-dessous pour une preuve.
    assert "confidence_score" in lecon or "NOMBRE de 0 à 100" in lecon, (
        "la leçon lue ne parle plus du nombre : le garde ne regarde plus le "
        "bon texte et deviendrait vert par construction.")
    promesses = promesses_de_classement(lecon)
    assert not promesses, (
        "l'écran de fin de l'installation promet que la confiance classe les "
        f"rappels — tournures trouvées : {promesses}. MESURÉ le 9 août 2026 "
        "sur un cerveau réel : deux atomes au texte identique, l'un à 95 "
        "l'autre à 10, remontent à la distance 1.105593236593197 tous les "
        "deux. Le lecteur n'a aucun moyen de constater l'effet promis ; il "
        "conclura que son installation est cassée, ou pire, il montera des "
        "scores pour rien.")


def test_l_ecran_de_fin_dit_le_seuil_que_la_base_applique() -> None:
    """FAIT 3 — le SEUL effet réel du nombre, lu dans le trigger, pas recopié."""
    moment, seuil, trace = seuil_du_declencheur()
    lecon = lecon_de_la_confiance()

    assert moment == "BEFORE INSERT", (
        f"le déclencheur d'archivage est devenu « {moment} ». S'il regarde "
        f"maintenant les UPDATE, alors « descendre un score par PATCH ne "
        f"déclenche rien » est faux, et la leçon « 96 % » ment.")
    assert str(seuil) in lecon, (
        f"la base archive sous {seuil}, et la leçon imprimée ne nomme pas ce "
        f"nombre. Un seuil qu'on ne dit pas est un piège qu'on laisse.")
    assert "PATCH" in lecon and "supersé" in lecon.lower(), (
        "la leçon ne distingue plus les deux gestes, alors que c'est TOUTE la "
        "différence : PATCH n'archive pas, la supersédure écrit et déclenche.")
    assert trace == "autonomous_agent_suggest", (
        f"le déclencheur ne lit plus la trace d'audit mais « {trace} » : la "
        f"leçon nomme la mauvaise population d'atomes.")


def test_l_atome_qui_nait_hors_du_rappel_le_dit() -> None:
    """La leçon promet un avertissement nommé. Il doit exister, et sortir des
    DEUX chemins d'écriture — sans quoi la promesse rejoint la famille."""
    routeur = _source(ROUTEUR_ATOMES)
    assert "_check_w008_ne_nait_pas_actif" in routeur, (
        "W-008 a disparu : la supersédure d'une suggestion d'agent sous le "
        "seuil redevient une perte silencieuse (201, aucune erreur, plus "
        "aucun atome actif sur ce domaine et cette clé).")
    arbre = ast.parse(routeur)
    appelants = {
        n.name
        for n in ast.walk(arbre)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and "_check_w008_ne_nait_pas_actif" in ast.unparse(n)
        and n.name != "_check_w008_ne_nait_pas_actif"
    }
    assert {"create_atom", "supersede_atom"} <= appelants, (
        f"W-008 n'est plus émis par les deux chemins d'ÉCRITURE : {appelants}. "
        f"Le trigger est BEFORE INSERT — les deux insèrent, les deux peuvent "
        f"rendre un atome mort-né.")
    assert "W-008" in lecon_de_la_confiance(), (
        "l'écran de fin ne nomme plus l'avertissement : le lecteur ne saura "
        "pas quoi chercher dans sa réponse.")


# ===========================================================================
# ÉPROUVER LE GARDE — on lui remet la phrase exacte, et on regarde s'il rougit
# ===========================================================================

#: La phrase telle qu'elle a été imprimée par `bootstrap/lib/verify.sh`, à la
#: virgule près. Elle est ici dans une chaîne : le garde la lit comme un texte
#: fabriqué, il ne se la reproche pas à lui-même.
LA_PHRASE_QUI_PROMETTAIT_UN_EFFET_ABSENT = (
    "C'est un aveu, pas un réglage — il dit ce que VOUS savez de ce souvenir, "
    "et le cerveau s'en sert pour classer : sous 50 il éloigne, à 85 et plus "
    "il rapproche, de trois centièmes au plus."
)

#: Des reformulations de la MÊME promesse. Le garde doit les voir aussi, sinon
#: il ne ferme qu'une virgule.
@pytest.mark.parametrize("phrase", [
    LA_PHRASE_QUI_PROMETTAIT_UN_EFFET_ABSENT,
    "Un souvenir à 90 remonte plus haut qu'un souvenir à 20.",
    "Monter la confiance d'un atome le fait remonter dans les rappels.",
    "Le score pèse sur le rappel : il rapproche ce dont vous êtes sûr.",
])
def test_le_garde_voit_la_promesse_d_un_effet_absent(phrase: str) -> None:
    assert promesses_de_classement(phrase), (
        f"le garde laisse passer une promesse de classement : {phrase!r}")


@pytest.mark.parametrize("phrase", [
    "Le NOMBRE de 0 à 100 se corrige : PATCH le sert.",
    "Deux atomes au texte identique remontent à la même distance, quel que "
    "soit leur score.",
    "Sous 70, un atome écrit avec la trace « suggestion d'agent autonome » "
    "est archivé à la naissance.",
])
def test_le_garde_se_tait_quand_la_phrase_est_vraie(phrase: str) -> None:
    assert not promesses_de_classement(phrase), (
        f"le garde reproche une phrase mesurée vraie : {phrase!r}")


def test_le_garde_declare_ce_qu_il_ne_couvre_pas() -> None:
    """Un garde qui ment sur sa portée est pire qu'un garde absent."""
    assert len(ZONES_NON_COUVERTES) >= 4
    for titre, detail in ZONES_NON_COUVERTES:
        assert titre and len(detail) > 60, titre
