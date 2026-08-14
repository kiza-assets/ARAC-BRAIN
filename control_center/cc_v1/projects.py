"""Les projets : le savoir vu par INTENTION, pas par rangement.

    Un scope dit OÙ un atome est rangé.
    Un projet dit À QUOI il sert.

Les deux ne coïncident pas, et c'est le point. Un déménagement vit à la fois
dans le territoire où vous rangez votre logement et dans celui où vous suivez
ce qui est en cours ; un lancement produit traverse la stratégie, la finance et
la publicité. Si les projets étaient des dossiers, il faudrait choisir — et
choisir, ici, c'est perdre.

Un projet est donc une **règle de sélection** appliquée au savoir vivant. Trois
conséquences, qui expliquent la forme de tout le module :

1. **Un atome appartient à plusieurs projets.** Les décomptes par projet ne
   s'additionnent donc jamais en un total : le cockpit compte toujours en
   ``count(DISTINCT id)``. Une somme de colonnes compterait deux fois le même
   atome, et mentirait.
2. **Un projet peut être vide.** La règle existe indépendamment du savoir. Un
   projet sans atome doit apparaître comme vide, pas disparaître.
3. **Du savoir peut n'appartenir à aucun projet.** C'est la mesure la plus
   utile de la famille : un scope peuplé qu'aucune règle ne cite est du savoir
   qu'aucune intention ne réclame.

D'OÙ VIENNENT VOS PROJETS
-------------------------
De ``config/projects.toml``, que vous écrivez. Le dépôt n'en propose aucun :
les projets d'un cerveau sont ceux de son propriétaire, et hériter de ceux
d'un autre serait exactement le contraire de l'objectif.

Modèle commenté : ``config/projects.example.toml``.

**Sans ce fichier, le cockpit fonctionne.** La famille « projets » affiche
simplement « aucun projet déclaré » au lieu d'inventer. C'est délibéré : un
tableau de bord qui remplit ses trous tout seul est un tableau de bord qui
ment.

POURQUOI CE MODULE ENGENDRE DU SQL
----------------------------------
Le cockpit ne sert jamais un chiffre sans la requête qui l'a produit — c'est
sa règle cardinale, et le registre (``registry.py``) la rend impossible à
contourner. Les règles de projet doivent donc exister **dans** le SQL servi,
sous forme littérale, copiable dans un terminal. Elles sont engendrées ici une
fois, dans les trois formes dont le cockpit a besoin, à partir d'une seule
déclaration : deux transcriptions qui divergeraient produiraient une valeur et
une preuve contradictoires.

INJECTION SQL
-------------
Ce module fabrique du SQL par concaténation de littéraux. La source est un
fichier de configuration local, pas une entrée réseau — mais un fichier de
configuration reste une entrée. Chaque valeur est donc validée contre une
expression régulière stricte (:func:`_check`) puis échappée (:func:`_lit`)
avant d'entrer dans une chaîne. Une valeur non conforme fait
échouer le chargement au démarrage, bruyamment : mieux vaut un cockpit qui
refuse de démarrer qu'un cockpit qui exécute ce qu'on lui a glissé.
"""

from __future__ import annotations

import os
import re
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

import arac_runtime

__all__ = [
    "ProjectConfigError",
    "load_projects",
    "projects_values_cte",
    "projects_table_cte",
    "union_ou_vide",
    "PROJECT_MATCH",
]


class ProjectConfigError(RuntimeError):
    """``config/projects.toml`` est présent mais mal formé."""


#: Un identifiant de projet : minuscules, chiffres, tirets. Sert d'ancre d'URL.
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

#: Un motif de scope : ce qu'on écrit dans une taxonomie, plus le joker `%`.
_SCOPE_RE = re.compile(r"^[a-z0-9][a-z0-9/_%-]{0,126}$")

#: Un mot-clé : pas d'apostrophe, pas de méta-caractère d'expression régulière
#: qu'on n'ait pas voulu. Les mots-clés sont assemblés en alternative `a|b|c`.
_KEYWORD_RE = re.compile(r"^[\w-]{1,64}$", re.UNICODE)

#: Un libellé affiché. Tout sauf des caractères de contrôle et l'apostrophe,
#: qui est le délimiteur des littéraux SQL.
_LABEL_RE = re.compile(r"^[^\x00-\x1f']{1,64}$")


def _check(value: Any, rx: re.Pattern[str], what: str, where: str) -> str:
    if not isinstance(value, str) or not rx.match(value):
        raise ProjectConfigError(
            f"config/projects.toml — projet « {where} » : {what} invalide "
            f"({value!r}).\n"
            f"Attendu : {rx.pattern}\n"
            "Ces valeurs entrent littéralement dans le SQL servi comme preuve ; "
            "ce qui n'est pas validable n'est pas servi."
        )
    return value


def _lit(s: str) -> str:
    """Un littéral texte SQL. L'apostrophe est déjà refusée en amont ; on
    double quand même, parce qu'une défense qui dépend d'une autre défense
    n'en est pas une."""
    return "'" + s.replace("'", "''") + "'"


def _array(items: tuple[str, ...]) -> str:
    if not items:
        return "ARRAY[]::text[]"
    return "ARRAY[" + ", ".join(_lit(i) for i in items) + "]::text[]"


# ============================================================================
# ZÉRO PROJET N'EST PAS ZÉRO SQL
# ============================================================================
#
# LE DÉFAUT QUE CETTE FONCTION FERME, ET POURQUOI IL A COÛTÉ SEPT ROUTES.
# Cinq endroits du cockpit engendrent UNE BRANCHE PAR PROJET puis les cousent
# par ``UNION ALL``, et insèrent le résultat dans un gabarit qui l'attend entre
# parenthèses : ``membership AS ( … )``, ``FROM ( … ) t``, ``( … ) x``, ou un
# ``LIMIT 8`` posé derrière. Sans ``config/projects.toml`` — c'est-à-dire sur
# TOUTE installation issue du chemin documenté, puisque ni le bootstrap ni
# l'entretien ne créent ce fichier — la liste des branches est VIDE,
# ``str.join`` rend la chaîne VIDE, et le gabarit produit ``AS (\n\n)`` : une
# erreur de syntaxe PostgreSQL (42601). Les routes concernées rendaient quand
# même **HTTP 200**, avec ``state: unavailable`` dans le corps : le harnais les
# empruntait et les voyait vertes.
#
# LA CAUSE N'EST PAS « le fichier manque » — trois documents promettent que son
# absence ne casse rien, et ils ont raison de le promettre. La cause est qu'on
# a écrit « aucune branche » avec une CHAÎNE VIDE là où SQL attend une
# RELATION. Zéro ligne se dit en SQL, et se dit ``WHERE false`` : une relation
# vide, mais typée, nommée et bien formée, que le moteur analyse sans broncher
# et qui rend exactement ce que le produit veut dire — aucun projet.
#
# Le repli existait déjà, deux fonctions plus bas (``projects_values_cte`` et
# ``projects_table_cte`` le font depuis toujours). Ce qui manquait, c'est qu'il
# soit à un SEUL endroit : cinq recopies d'une même précaution, c'est quatre
# occasions de l'oublier — et elle l'a été cinq fois sur cinq.


def union_ou_vide(
    blocs: list[str],
    colonnes: tuple[tuple[str, str], ...],
    *,
    separateur: str = "\nUNION ALL\n",
) -> str:
    """Coud les branches par ``UNION ALL`` — ou rend une relation VIDE et TYPÉE.

    Args:
        blocs: une branche ``SELECT`` par projet déclaré. Peut être vide.
        colonnes: la signature de la relation, ``(nom, type)`` dans l'ordre de
            projection. Elle doit décrire ce que les branches projettent : le
            gabarit d'accueil lit ces noms (``ORDER BY t.rang``,
            ``JOIN … ON a.id = m.atom_id``), et un nom qui manquerait ferait
            échouer la requête *pour une autre raison*.
        separateur: la couture. Certains gabarits n'ajoutent pas de saut de
            ligne avant ``UNION ALL`` ; ce paramètre le respecte.

    Returns:
        Du SQL toujours analysable, quel que soit le nombre de projets.
    """
    if blocs:
        return separateur.join(blocs)
    projection = ", ".join(f"NULL::{typ} AS {nom}" for nom, typ in colonnes)
    return (
        "/* aucun projet declare (config/projects.toml absent) : une relation VIDE\n"
        "   et BIEN FORMEE, pas une chaine vide. Zero ligne se dit WHERE false ;\n"
        "   une chaine vide, elle, ne se dit pas — elle casse la requete. */\n"
        f"SELECT {projection}\n WHERE false"
    )


# ============================================================================
# Chargement
# ============================================================================


def _config_path() -> Path:
    return Path(
        os.environ.get("ARAC_PROJECTS_CONFIG")
        or arac_runtime.config_dir() / "projects.toml"
    )


@lru_cache(maxsize=1)
def _load(marker: tuple[str, float] | None) -> tuple[dict[str, Any], ...]:
    if marker is None:
        return ()
    raw = tomllib.loads(Path(marker[0]).read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(raw.get("project") or ()):
        where = str(item.get("id", f"#{i + 1}"))
        pid = _check(item.get("id"), _ID_RE, "id", where)
        if pid in seen:
            raise ProjectConfigError(
                f"config/projects.toml — deux projets portent l'id « {pid} ». "
                "L'id est l'ancre d'URL du cockpit : il doit être unique."
            )
        seen.add(pid)
        label = _check(item.get("label", pid), _LABEL_RE, "label", where)
        scopes = tuple(
            _check(s, _SCOPE_RE, "scope", where) for s in (item.get("scopes") or ())
        )
        prefixes = tuple(
            _check(s, _SCOPE_RE, "prefix", where) for s in (item.get("prefixes") or ())
        )
        keywords = tuple(
            _check(k, _KEYWORD_RE, "keyword", where) for k in (item.get("keywords") or ())
        )
        if not scopes and not prefixes:
            raise ProjectConfigError(
                f"config/projects.toml — le projet « {pid} » ne cite ni scope ni "
                "préfixe : il ne pourra jamais contenir un seul atome. Un projet "
                "vide par erreur et un projet vide par nature ne se distinguent "
                "plus une fois affichés — donc on refuse ici."
            )
        out.append({
            "id": pid,
            "label": label,
            "scopes": scopes,
            "prefixes": prefixes,
            "keywords": keywords,
        })
    return tuple(out)


def load_projects() -> tuple[dict[str, Any], ...]:
    """Les projets déclarés, ou un tuple vide si aucun ne l'est.

    Relit le fichier quand il change (le cache est indexé sur sa date de
    modification), pour qu'un ajout de projet ne demande pas un redémarrage.
    """
    p = _config_path()
    try:
        marker: tuple[str, float] | None = (str(p), p.stat().st_mtime)
    except OSError:
        marker = None
    return _load(marker)


# ============================================================================
# Les trois formes SQL
# ============================================================================

#: Ce qu'on affiche quand personne n'a déclaré de projet. Le cockpit doit dire
#: « je ne sais pas » ; il ne doit jamais deviner.
NO_PROJECTS_NOTE = (
    "aucun projet déclaré — écrivez config/projects.toml "
    "(modèle : config/projects.example.toml)"
)


def projects_values_cte(name: str = "proj") -> str:
    """Le CTE ``(id, label, scopes, prefixes, keywords)``, forme « entités ».

    Utilisé par les métriques qui rendent une ligne par projet et ont besoin de
    l'identifiant technique (ancre d'URL) autant que du libellé.
    """
    rows = load_projects()
    if not rows:
        return (
            f"{name} (id, label, scopes, prefixes, keywords) AS (\n"
            "    /* Aucun projet déclaré : CTE typé mais vide. La famille rend\n"
            "       « aucun projet déclaré » plutôt qu'un chiffre inventé. */\n"
            "    SELECT * FROM (VALUES\n"
            "        (NULL::text, NULL::text, NULL::text[], NULL::text[], NULL::text[])\n"
            "    ) v(id, label, scopes, prefixes, keywords) WHERE false\n"
            ")"
        )
    body = ",\n".join(
        "      ({}, {}, {}, {}, {})".format(
            _lit(p["id"]), _lit(p["label"]),
            _array(p["scopes"]), _array(p["prefixes"]), _array(p["keywords"]),
        )
        for p in rows
    )
    return (
        f"{name} (id, label, scopes, prefixes, keywords) AS (\n"
        "    VALUES\n" + body + "\n)"
    )


def projects_table_cte(name: str = "projets") -> str:
    """Le CTE ``(rang, projet, scopes, motifs)``, forme « famille projets ».

    Ici les préfixes sont aplatis en motifs ``LIKE`` : ``travail`` devient
    ``ARRAY['travail', 'travail/%']`` — la racine NUE **en plus** des feuilles.

    POURQUOI LA RACINE NUE : un atome posé sur une racine est invisible au
    rappel. Sur le cerveau de référence, 157 atomes (9 %) étaient dans ce cas.
    Si le projet ne les comptait pas, la dette resterait invisible et ne serait
    jamais résorbée. On les compte donc — précisément parce qu'ils sont perdus.

    ``motifs`` est une expression régulière insensible à la casse appliquée à
    ``key`` et à chaque ``tag``. ``NULL`` = aucun filtre.
    """
    rows = load_projects()
    if not rows:
        return (
            f"    WITH {name}(rang, projet, scopes, motifs) AS (\n"
            "        /* Aucun projet déclaré (config/projects.toml absent) :\n"
            "           CTE typé mais vide, aucune ligne inventée. */\n"
            "        SELECT * FROM (VALUES\n"
            "            (NULL::int, NULL::text, NULL::text[], NULL::text)\n"
            "        ) v(rang, projet, scopes, motifs) WHERE false\n"
            "    )"
        )
    parts = []
    for rank, p in enumerate(rows, start=1):
        pats = list(p["scopes"])
        for pref in p["prefixes"]:
            pats += [pref, f"{pref}/%"]
        motifs = (
            _lit("|".join(p["keywords"])) if p["keywords"] else "NULL::text"
        )
        parts.append(
            f"          ({rank}, {_lit(p['label'])},\n"
            f"              {_array(tuple(pats))},\n"
            f"              {motifs})"
        )
    return (
        f"    WITH {name}(rang, projet, scopes, motifs) AS (\n"
        "        VALUES\n" + ",\n".join(parts) + "\n    )"
    )


#: Le prédicat d'appartenance, forme « entités » : alias ``a`` (memory_atoms)
#: et ``p`` (le CTE). Écrit une fois, appliqué partout — deux prédicats qui
#: divergent, c'est un cockpit qui se contredit lui-même.
PROJECT_MATCH = """
        (a.scope = ANY(p.scopes)
         OR EXISTS (SELECT 1 FROM unnest(p.prefixes) x
                     WHERE a.scope = x OR a.scope LIKE x || '/%'))
    AND (cardinality(p.keywords) = 0
         OR a.tags && p.keywords
         OR EXISTS (SELECT 1 FROM unnest(p.keywords) k WHERE a.key ILIKE '%' || k || '%'))
"""
