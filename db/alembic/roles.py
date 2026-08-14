"""LES CINQ RÔLES DU CERVEAU — déduits, jamais écrits en dur.

POURQUOI CE MODULE EXISTE
=========================

Un rôle PostgreSQL est global au CLUSTER, pas propre à une base. Tant que les
migrations écrivaient ``GRANT … TO arac_app`` en toutes lettres, deux cerveaux
posés sur le même serveur PostgreSQL se disputaient les mêmes cinq rôles :

  · la migration du cerveau B donnait des droits sur SA base au rôle du
    cerveau A — droits que personne n'avait demandés, sur des données que
    personne n'avait décidé de partager ;
  · et le bootstrap de B, trouvant les rôles déjà là, faisait
    ``ALTER ROLE … PASSWORD`` : les services de A perdaient l'accès à leur
    propre base, au redémarrage suivant, sans message et sans lien visible
    avec l'installation qui venait d'avoir lieu.

C'est arrivé. Cinq rôles de production perdus d'un coup.

D'OÙ VIENT LE NOM, ET POURQUOI DE LÀ
====================================

Le nom ne vient ni d'un fichier de configuration que la migration devrait
retrouver, ni d'une variable d'environnement qu'il faudrait penser à poser.
Il vient de **la connexion elle-même** : une migration tourne sous le rôle
d'administration du cerveau qu'elle migre, et les quatre autres rôles sont ses
frères. ``current_user`` = ``arac_nadia_brain_admin`` ⇒ le préfixe est
``arac_nadia_brain``, et les droits partent vers ``arac_nadia_brain_app``,
``…_agent``, ``…_readonly``, ``…_backup``.

Cette source n'est pas un raccourci commode, c'est la seule qui rende la faute
STRUCTURELLEMENT impossible : pour qu'une migration donne des droits aux rôles
d'un autre cerveau, il faudrait qu'elle se soit connectée avec l'identité
d'administration de cet autre cerveau — c'est-à-dire qu'on lui ait donné son
mot de passe. Aucun oubli de configuration ne peut produire l'accident ; il
faut le vouloir.

Effet de bord voulu : une installation antérieure, dont le rôle
d'administration s'appelle simplement ``arac_admin``, rend le préfixe ``arac``
et donc exactement les cinq noms d'avant. Les cerveaux déjà posés migrent sans
rien changer.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

#: PostgreSQL tronque tout identifiant à NAMEDATALEN-1 = 63 octets, SANS
#: erreur. Deux cerveaux aux noms longs et proches produiraient donc deux
#: préfixes distincts et un seul rôle réel : la collision silencieuse que ce
#: module existe pour empêcher, réintroduite par la porte de derrière. Le
#: suffixe le plus long est « _readonly » (9 caractères).
LONGUEUR_MAX_PREFIXE = 63 - len("_readonly")

_PREFIXE_VALIDE = re.compile(r"^[a-z_][a-z0-9_]*$")

#: Les cinq suffixes, et rien d'autre. Ajouter un rôle est une décision de
#: sécurité (une identité de plus qui peut se connecter), pas une formalité.
SUFFIXES = ("admin", "app", "agent", "readonly", "backup")


class PrefixeDeRoleInvalide(RuntimeError):
    """Le préfixe des rôles est inutilisable — on refuse plutôt que de deviner."""


@dataclass(frozen=True)
class RolesArac:
    """Les cinq rôles d'UN cerveau, tous dérivés du même préfixe."""

    prefixe: str

    @property
    def admin(self) -> str:
        return f"{self.prefixe}_admin"

    @property
    def app(self) -> str:
        return f"{self.prefixe}_app"

    @property
    def agent(self) -> str:
        return f"{self.prefixe}_agent"

    @property
    def readonly(self) -> str:
        return f"{self.prefixe}_readonly"

    @property
    def backup(self) -> str:
        return f"{self.prefixe}_backup"

    def tous(self) -> tuple[str, ...]:
        return tuple(f"{self.prefixe}_{s}" for s in SUFFIXES)


def valider_prefixe(prefixe: str) -> str:
    """Refuse un préfixe qui produirait un identifiant SQL douteux ou tronqué.

    On ne cite JAMAIS un nom de rôle entre guillemets dans le DDL engendré :
    un identifiant qui aurait besoin de guillemets est un identifiant qu'on
    refuse. C'est ce qui interdit, par construction, qu'un nom de cerveau
    devienne une injection SQL dans une migration.
    """
    if not prefixe:
        raise PrefixeDeRoleInvalide(
            "Préfixe de rôle vide.\n"
            "  Le nom des cinq rôles se déduit du rôle d'administration sous "
            "lequel la migration tourne, ou de ARAC_ROLE_PREFIX."
        )
    if not _PREFIXE_VALIDE.match(prefixe):
        raise PrefixeDeRoleInvalide(
            f"Préfixe de rôle refusé : {prefixe!r}\n"
            "  Attendu : minuscules, chiffres et « _ », commençant par une "
            "lettre ou « _ ».\n"
            "  Un identifiant qui exigerait des guillemets est un identifiant "
            "qu'on refuse : c'est ce qui interdit qu'un nom de cerveau devienne "
            "une injection SQL."
        )
    if len(prefixe) > LONGUEUR_MAX_PREFIXE:
        raise PrefixeDeRoleInvalide(
            f"Préfixe de rôle trop long ({len(prefixe)} > "
            f"{LONGUEUR_MAX_PREFIXE}) : {prefixe!r}\n"
            "  PostgreSQL tronque les identifiants à 63 octets SANS erreur. "
            "Deux cerveaux aux noms longs et voisins finiraient donc par "
            "partager un rôle sans que rien ne le signale — exactement la "
            "collision silencieuse que ce nommage existe pour empêcher.\n"
            "  Raccourcissez brain.name dans config/brain.toml."
        )
    return prefixe


def prefixe_depuis_role_admin(role: str) -> str:
    """« arac_nadia_brain_admin » → « arac_nadia_brain »."""
    if not role.endswith("_admin"):
        raise PrefixeDeRoleInvalide(
            f"La migration tourne sous le rôle « {role} », qui ne se termine "
            "pas par « _admin ».\n"
            "  Les cinq rôles d'un cerveau se déduisent de son rôle "
            "d'administration : c'est ce qui garantit qu'une migration ne peut "
            "pas donner de droits aux rôles d'un AUTRE cerveau.\n"
            "  Deux issues :\n"
            "    · connectez-vous avec ARAC_DB_URL_ADMIN "
            "(/etc/arac/<base>/arac.env) — c'est ce que fait le bootstrap ;\n"
            "    · ou, si vous savez ce que vous faites, posez explicitement "
            "ARAC_ROLE_PREFIX=<préfixe> pour cette invocation."
        )
    return role[: -len("_admin")]


def roles_arac(bind=None) -> RolesArac:
    """Les cinq rôles du cerveau que cette migration est en train de migrer.

    Ordre de résolution — le premier qui répond gagne :

      1. ``ARAC_ROLE_PREFIX`` dans l'environnement. Surcharge explicite : elle
         sert aux tests hors base, et à l'opérateur qui sait ce qu'il fait.
      2. ``current_user`` de la connexion. C'est le cas normal, et le seul qui
         ne demande rien à personne.

    Il n'y a PAS de troisième cas. Aucune valeur de repli, aucun « arac » par
    défaut : c'est précisément un défaut silencieux qui a détruit la
    production. Ne pas savoir sous quel cerveau on tourne est une raison de
    s'arrêter, pas de deviner.
    """
    depuis_env = os.environ.get("ARAC_ROLE_PREFIX", "").strip()
    if depuis_env:
        return RolesArac(valider_prefixe(depuis_env))

    if bind is None:
        from alembic import op  # import tardif : ce module est lisible hors alembic

        bind = op.get_bind()

    from sqlalchemy import text

    courant = bind.execute(text("SELECT current_user")).scalar_one()
    return RolesArac(valider_prefixe(prefixe_depuis_role_admin(str(courant))))
