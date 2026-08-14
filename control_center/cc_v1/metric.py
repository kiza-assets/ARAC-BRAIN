"""Le TYPE d'une métrique du cockpit — et rien d'autre.

POURQUOI CE MODULE EXISTE, SÉPARÉ DU REGISTRE
=============================================
``Metric`` vivait dans ``registry.py``. Les dix familles de métriques
l'importaient donc *depuis le registre*, pendant que le registre importait *les
familles* pour se construire : un cycle d'imports parfait.

Python le tolère, et c'est bien le problème — il le tolère en SILENCE. Quand
c'est une famille qui est importée en premier, elle demande ``Metric`` au
registre, le registre s'exécute, appelle ``_load_families()``, retrouve cette
famille dans ``sys.modules`` **à moitié initialisée**, y cherche ``METRICS``,
n'en trouve pas — et poursuit sans un mot. Le cockpit se retrouvait alors avec
130 métriques au lieu de 148 : les dix-huit du panneau « Aujourd'hui »
disparaissaient, sans erreur, sans entrée dans ``LOAD_ERRORS``, sans rien.
Exactement la faute que ce projet passe son temps à réparer ailleurs — une
absence qui ne se déclare pas.

Le type ne dépend de personne : il n'a aucune raison de vivre dans le module
qui, lui, dépend de tout le monde. Le cycle est rompu à sa racine, et l'ordre
d'import n'a plus d'effet observable. ``registry`` réexporte ``Metric`` et
``FORBIDDEN_SQL`` : rien de ce qui les importait de là n'a besoin de changer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Metric", "FORBIDDEN_SQL", "lire_sql"]


# ============================================================================
# Garde lecture seule — mots-clés interdits dans toute requête du registre
# ============================================================================

FORBIDDEN_SQL: tuple[str, ...] = (
    "insert", "update", "delete", "truncate", "drop", "alter", "create",
    "grant", "revoke", "copy", "vacuum", "refresh", "call", "do",
)
"""Mots-clés SQL interdits. Une métrique qui en contient un est rejetée à
l'instanciation. Double couche avec le rôle ``arac_readonly`` et la session
``default_transaction_read_only=on``."""

_WORD = re.compile(r"[a-z_]+")


# ============================================================================
# CE QUI S'EXÉCUTE, ET CE QUI SE LIT SEULEMENT
# ============================================================================
#
# LE DÉFAUT QUE CE LECTEUR FERME. Le garde de `entities` retirait les littéraux
# entre apostrophes, puis interdisait `--` dans ce qui restait. Il ne retirait
# PAS les commentaires de bloc `/* … */`. Or la requête des conversations en
# contient un, et ce commentaire est de la PROSE française : « `to_regclass`
# regarde le catalogue -- c'est la seule facon de le dire sans le supposer ».
# Le garde y a vu un commentaire SQL et a refusé la requête DU PRODUIT
# LUI-MÊME : `GET /cc/v1/conversations` et `GET /cc/v1/conversations/{uid}`
# rendaient `state: unavailable` sur 100 % des installations — en HTTP 200.
#
# LE GARDE AVAIT RAISON SUR LE PRINCIPE. Les requêtes du cockpit sont servies
# comme preuve, APLATIES sur une ligne (`_sql_text`, `service.evidence`) : un
# `--` réel y avalerait tout ce qui suit, et la preuve publiée deviendrait
# injouable — donc mensongère. La règle doit rester.
#
# IL AVAIT TORT SUR LA MÉTHODE. Il jugeait un CARACTÈRE là où SQL a une
# GRAMMAIRE. Un `--` à l'intérieur d'un `/* … */` n'est pas un commentaire de
# ligne : PostgreSQL ne lui donne aucun sens, et l'aplatissement ne lui en
# donne pas non plus, puisque c'est `*/` qui referme le bloc — pas la fin de
# ligne. Le seul `--` qui casse la preuve est celui qui commente VRAIMENT,
# c'est-à-dire hors littéral et hors bloc.
#
# Ce lecteur fait donc ce que fait l'analyseur : il parcourt la requête, et il
# sait à chaque instant s'il est dans du code, dans une chaîne, ou dans un
# commentaire. Il vit ici, avec le type, et non dans l'un des deux gardes :
# deux transcriptions d'une même grammaire finissent toujours par diverger.


def lire_sql(sql: str) -> tuple[str, bool, bool]:
    """Sépare ce qui s'EXÉCUTE de ce qui se LIT seulement.

    Args:
        sql: la requête, telle qu'elle sera envoyée au moteur.

    Returns:
        Un triplet ``(corps, commentaire_de_ligne, bloc_non_ferme)`` :

        - ``corps`` : la requête en minuscules, littéraux et commentaires
          remplacés par une espace. C'est là — et là seulement — qu'un mot-clé
          est une instruction ;
        - ``commentaire_de_ligne`` : un ``--`` a été rencontré en position de
          commentaire réel (hors chaîne, hors bloc). C'est celui qui casse la
          preuve mise sur une ligne ;
        - ``bloc_non_ferme`` : un ``/*`` n'a jamais été refermé. La requête est
          alors tronquée à l'exécution comme à la lecture — même dégât qu'un
          ``--``, et il faut le dire plutôt que de l'ignorer.

    Les commentaires de bloc s'IMBRIQUENT en PostgreSQL (``/* /* */ */``) : le
    parcours compte donc une profondeur, il ne cherche pas le premier ``*/``.
    Les apostrophes doublées (``''``) sont l'échappement du littéral, pas sa
    fin.
    """
    bas = sql.lower()
    n = len(bas)
    morceaux: list[str] = []
    i = 0
    profondeur = 0
    ligne = False
    while i < n:
        if profondeur:
            if bas.startswith("/*", i):
                profondeur += 1
                i += 2
            elif bas.startswith("*/", i):
                profondeur -= 1
                i += 2
            else:
                i += 1
            continue
        if bas.startswith("/*", i):
            profondeur += 1
            i += 2
            morceaux.append(" ")
            continue
        if bas.startswith("--", i):
            ligne = True
            saut = bas.find("\n", i)
            i = n if saut < 0 else saut
            morceaux.append(" ")
            continue
        if bas[i] == "'":
            j = i + 1
            while j < n:
                if bas[j] != "'":
                    j += 1
                elif j + 1 < n and bas[j + 1] == "'":
                    j += 2
                else:
                    j += 1
                    break
            i = j
            morceaux.append(" ")
            continue
        morceaux.append(bas[i])
        i += 1
    return "".join(morceaux), ligne, profondeur > 0


def _assert_read_only(sql: str, where: str) -> None:
    """Lève ``ValueError`` si ``sql`` contient une instruction mutante.

    L'analyse est lexicale (mots entiers, casse ignorée) mais elle porte sur ce
    qui S'EXÉCUTE : littéraux et commentaires sont écartés d'abord. Elle ne
    prétend pas remplacer le rôle read-only, elle attrape l'erreur
    d'inattention avant même qu'une connexion soit ouverte.

    Le second contrôle n'est pas de la sécurité, c'est de l'honnêteté : la
    requête d'une métrique est PUBLIÉE, aplatie sur une ligne
    (``service.evidence``). Un commentaire de ligne y masquerait tout ce qui
    suit — le lecteur recopierait dans son terminal une requête tronquée, donc
    une autre requête que celle qui a produit le chiffre.
    """
    corps, commentaire_de_ligne, bloc_non_ferme = lire_sql(sql)
    hit = set(_WORD.findall(corps)) & set(FORBIDDEN_SQL)
    if hit:
        raise ValueError(f"{where}: instruction mutante interdite dans le registre : {sorted(hit)}")
    if commentaire_de_ligne:
        raise ValueError(
            f"{where}: commentaire SQL '--' interdit — cette requête est publiée "
            "aplatie sur une ligne, un commentaire de ligne y masquerait tout ce "
            "qui suit et rendrait la preuve injouable. Utilisez /* … */."
        )
    if bloc_non_ferme:
        raise ValueError(
            f"{where}: commentaire de bloc '/*' jamais refermé — le moteur avalerait "
            "la fin de la requête."
        )


# ============================================================================
# Le type Metric — la contrainte structurelle
# ============================================================================


@dataclass(frozen=True)
class Metric:
    """Une métrique du cerveau, indissociable de sa preuve.

    Champs obligatoires — l'absence de l'un d'eux empêche l'instanciation :

    key           Identifiant stable, utilisé dans l'URL de preuve.
    label         Libellé humain affiché.
    unit          Unité affichée à côté de la valeur ("atomes", "%", "jours"…).
    definition    UNE phrase, affichable telle quelle dans l'infobulle.
    formula       La formule en clair, lisible par un humain.
    sql           Requête produisant la valeur FINALE (une ligne, colonne "value").
    evidence_sql  Requête produisant les LIGNES SOURCES derrière la valeur.
    evidence_label Ce que les lignes de preuve représentent.
    domain        Domaine d'interface propriétaire (cf SPEC §7).

    Optionnels :

    window        Fenêtre de mesure ("instant", "7d", "30d", "all").
    target        Seuils {"warn": x, "critical": y, "direction": "up"|"down"}.
    """

    key: str
    label: str
    unit: str
    definition: str
    formula: str
    sql: str
    evidence_sql: str
    evidence_label: str
    domain: str
    window: str = "instant"
    target: dict[str, Any] | None = field(default=None)
    unavailable_reason: str | None = field(default=None)
    """Raison à afficher quand la mesure ne peut pas être faite.

    Une métrique dont la source n'existe pas (table absente, colonne jamais
    alimentée) retourne NULL et devient ``unavailable``. Sans ce champ, elle
    hérite d'un message générique — « valeur nulle retournée par la source » —
    qui n'apprend rien. Or une indisponibilité doit être UTILE : elle doit dire
    ce qui manque et ce qui le débloquerait, sinon elle se lit comme une panne.
    """
    unavailable_gesture: str | None = field(default=None)
    """Le geste exact qui rendrait la mesure possible. Affiché, jamais exécuté."""
    substitute: str | None = field(default=None)
    """La mesure de repli proposée en attendant. Jamais présentée comme l'originale."""

    def __post_init__(self) -> None:
        # --- Le principe cardinal, appliqué comme une contrainte de type ---
        if not (self.evidence_sql or "").strip():
            raise ValueError(
                f"Métrique '{self.key}' sans preuve : evidence_sql est obligatoire. "
                "Aucune donnée ne doit être décorative — cf GOAL-COCKPIT-VIVANT.md G1."
            )
        for name in ("key", "label", "unit", "definition", "formula", "sql",
                     "evidence_label", "domain"):
            if not (getattr(self, name) or "").strip():
                # 'unit' peut être vide sémantiquement (ratio sans unité) : on
                # l'autorise explicitement, tout le reste est obligatoire.
                if name == "unit":
                    continue
                raise ValueError(f"Métrique '{self.key}' : champ '{name}' obligatoire et non vide.")

        _assert_read_only(self.sql, f"Métrique '{self.key}'.sql")
        _assert_read_only(self.evidence_sql, f"Métrique '{self.key}'.evidence_sql")

        if "value" not in self.sql.lower():
            raise ValueError(
                f"Métrique '{self.key}' : la requête doit projeter une colonne nommée 'value'."
            )
