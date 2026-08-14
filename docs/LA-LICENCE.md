# Le choix de la licence

*Cette page était une note en fin de `LICENSE`. Elle en a été retirée pour que
GitHub reconnaisse la licence MIT — un fichier `LICENSE` qui porte autre chose que
le texte de la licence n'est identifié par aucun outil.*

-------------------------------------------------------------------------------

Licence retenue : MIT. Le titulaire est nommé dans `LICENSE`, qui fait autorité —
une seule source, pour qu'elles ne divergent jamais.

Ce que MIT implique, en deux phrases : n'importe qui peut utiliser, modifier,
redistribuer et VENDRE ce code, y compris dans un produit fermé, à la seule
condition de conserver cet avis de copyright. Et vous ne garantissez rien —
si le logiciel casse quelque chose chez quelqu'un, ce n'est pas votre
responsabilité.

Si ce n'est pas ce que vous voulez, deux autres directions courantes :

  · AGPL-3.0  — quiconque exploite une version modifiée, y compris comme
                service en ligne, doit publier ses modifications. C'est le
                choix de ceux qui refusent qu'un tiers referme leur travail.
  · Apache-2.0 — proche de MIT, avec en plus une concession explicite de
                brevets et une clause de contribution. Plus long, plus sûr
                pour un usage en entreprise.

Deux points à trancher avant de publier, quels que soient vos goûts :

  1. La licence ne dit rien de VOS DONNÉES. Ce dépôt ne distribue que du
     code : la mémoire engendrée par un cerveau appartient à la personne qui
     l'a installé, sur son serveur, dans sa base. Aucun texte de licence n'a
     à en parler — mais il vaut mieux l'écrire quelque part.
  2. Les DÉPENDANCES ont leurs propres licences (PostgreSQL, pgvector,
     FastAPI, psycopg, Alembic, les bibliothèques clientes des fournisseurs
     de modèles). Elles ne sont pas couvertes par celle-ci. Vérifiez-les
     avant une redistribution commerciale.

Le fichier `pyproject.toml` déclare aujourd'hui `license = { text = "MIT" }`.
Si vous changez de licence, changez-le aussi — deux déclarations divergentes
valent moins que pas de déclaration du tout.
