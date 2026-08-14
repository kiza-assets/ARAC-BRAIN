"""Le premier rempart : un scope hors taxonomie n'entre pas.

CE QUE FAIT CE FICHIER
----------------------
Il expose ``Scope``, l'énumération que Pydantic utilise pour valider tout
``scope`` reçu par l'API. Un scope hors liste part en **422** avant d'avoir
touché la base. C'est volontaire, et c'est le point sur lequel il ne faut pas
céder :

    « Un scope ne s'invente pas à la volée. »

Sans cette rigidité, la mémoire se fragmente. Sur un corpus de quelques
milliers d'atomes, ``travail/finance`` et ``travail/finances`` deviennent deux
territoires jumeaux et le rappel se dilue entre les deux. La base pose la même
règle de son côté (clé étrangère vers ``arac.scopes``) : deux remparts, parce
qu'un seul finit toujours par être contourné.

CE QUE CE FICHIER NE FAIT PAS
-----------------------------
Il ne décide **pas** de votre taxonomie. Il n'en contient aucune.

La liste des scopes vient de ``app/schemas/scope_generated.py``, produit par
``bootstrap/generate_scopes.py`` à partir de ``config/scopes.toml``, lui-même
issu de l'entretien d'installation. Trois fichiers, un seul sens de lecture :

    vos réponses  →  config/scopes.toml  →  scope_generated.py  →  ce rempart
                                         →  db/seeds/scopes.sql →  la base

Modifier l'énumération à la main ne sert à rien : la prochaine régénération
l'écrase, et la base ne suivrait pas.

CE QUI EST RÉEXPORTÉ ICI
------------------------
``Scope``  l'énumération, type Pydantic.
``ROOTS``  les racines. **Un atome posé sur une racine est invisible au
           rappel.** Sur le cerveau de référence, 157 atomes (9 % du corpus)
           sont tombés dans ce piège et n'en sont jamais ressortis. Cet
           ensemble existe pour que le code puisse le détecter et le dire.
``LEAVES`` les feuilles : les seuls scopes où un atome doit vivre.
``LABELS`` ce que le cockpit affiche.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Le chargement, et ce qu'on dit quand il échoue.
#
# Une ImportError brute enverrait le lecteur chercher un fichier manquant. Or
# le fichier n'est pas « manquant » : il n'a pas encore été engendré, parce que
# la taxonomie n'a pas encore été décidée. Le message doit désigner l'entretien,
# pas le symptôme.
# ---------------------------------------------------------------------------

_MISSING = """\
La taxonomie de ce cerveau n'existe pas encore.

`app/schemas/scope_generated.py` est un fichier ENGENDRÉ : il naît de vos
réponses, pas du dépôt. Tant qu'il est absent, l'API n'a aucune liste de
scopes à faire respecter — elle refuse donc de démarrer plutôt que d'accepter
n'importe quoi.

Pour lui donner naissance :

    python3 bootstrap/wizard.py            # l'entretien : vos racines, vos feuilles
    python3 bootstrap/generate_scopes.py   # config/scopes.toml -> énumération + seed SQL

Si `config/scopes.toml` existe déjà (vous l'avez écrit ou modifié à la main),
la seconde commande suffit.
"""

try:
    from app.schemas.scope_generated import (  # noqa: F401
        LABELS,
        LEAVES,
        ROOTS,
        Scope,
    )
except ImportError as exc:  # pragma: no cover - dépend d'un artefact engendré
    raise ImportError(_MISSING) from exc


__all__ = ["Scope", "ROOTS", "LEAVES", "LABELS", "is_leaf", "root_of"]


def root_of(scope: str) -> str:
    """La racine d'un scope. ``"travail/finance"`` → ``"travail"``.

    Pour une racine, se retourne elle-même : la fonction est idempotente, ce
    qui évite au code appelant de tester avant d'appeler.
    """
    return scope.split("/", 1)[0]


def is_leaf(scope: str) -> bool:
    """Vrai si un atome posé ici sera retrouvable.

    À utiliser avant d'écrire, pas après. Un atome écrit sur une racine est
    déjà perdu : il est en base, il est actif, et aucune question ne le fera
    remonter. Le corriger après coup demande une migration.
    """
    return scope in LEAVES
