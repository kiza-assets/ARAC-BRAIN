import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# DATABASE_URL est injectée au runtime depuis l'environnement — JAMAIS écrite
# dans alembic.ini, qui est versionné : y poser un DSN reviendrait à publier un
# mot de passe.
#
# CE MESSAGE A LONGTEMPS PRESCRIT UN GESTE QUI N'EXISTE PAS. Il renvoyait à un
# « wrapper » `scripts/alembic_run.sh` : ce fichier n'est nulle part dans le
# dépôt. Quelqu'un dont la migration vient d'échouer lisait donc, au pire
# moment, une commande introuvable — et il n'accuse pas le message, il
# s'accuse lui-même. C'est le bootstrap qui pose DATABASE_URL, dans
# `bootstrap/lib/database.sh` (`DATABASE_URL="$dsn" "$ARAC_VENV/bin/alembic"
# upgrade head`), et c'est donc lui que ce message nomme désormais.
#
# Pourquoi le rôle ADMIN et lui seul : les migrations font du DDL. Le rôle
# applicatif ne l'a pas, et c'est délibéré — une API qui peut modifier son
# propre schéma peut aussi le détruire.
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL non définie. Alembic ne devine pas quelle base migrer, "
        "et c'est voulu : le DSN porte un mot de passe, alembic.ini est "
        "versionné.\n"
        "\n"
        "LE GESTE QUI EXISTE — celui que le bootstrap fait lui-même :\n"
        "    sudo ./bootstrap/bootstrap.sh --from migrations\n"
        "\n"
        "À LA MAIN, si vous savez ce que vous faites. Le DSN se lit dans le "
        "coffre de CE cerveau, et il porte le port de SA grappe — un DSN "
        "emprunté à un autre cerveau migre la base d'un autre :\n"
        "    cd \"$ARAC_HOME\"\n"
        "    sudo DATABASE_URL=\"$(sudo grep '^DATABASE_URL_ADMIN=' "
        "\"$ARAC_ENV_FILE\" | cut -d= -f2-)\" \\\n"
        "         .venv/bin/alembic upgrade head\n"
        "\n"
        "ARAC_ENV_FILE est le coffre : /etc/arac/<votre-base>/arac.env pour "
        "une installation faite par le bootstrap, en 0700 root."
    )

# Le préfixe SQLAlchemy explicite pour psycopg3 est ajouté ICI, pas dans .env.
# Justification : .env doit rester en `postgresql://` natif pour être compatible
# avec pg_dump (bash, ne connaît pas `+psycopg`) et psycopg3 direct (FastAPI,
# psycopg3 direct, pas d'ORM). SQLAlchemy a besoin du préfixe
# `+psycopg` pour choisir le driver psycopg3 — donc on le rajoute uniquement
# pour Alembic (seul consommateur SA).
# Le DDL est écrit à la main, jamais engendré par --autogenerate.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.removeprefix("postgresql://")
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# target_metadata = None (intentionnel) : pas de modèles SQLAlchemy en Phase 1b.
# Les migrations sont écrites manuellement avec op.execute("DDL brut") plutôt
# que via --autogenerate. Le DDL est écrit à la main, jamais engendré.
target_metadata = None

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="arac",
    )

    with context.begin_transaction():
        context.run_migrations()


def _garantir_schema(connectable) -> None:
    """Le schéma `arac` doit exister AVANT qu'Alembic n'ouvre le chantier.

    Alembic tient son journal dans `arac.alembic_version`
    (``version_table_schema="arac"`` ci-dessous). Il crée la TABLE, jamais le
    SCHÉMA : sur une base neuve, `alembic upgrade head` s'arrêtait donc avant
    même d'avoir lu la première révision. Le schéma est une PRÉCONDITION
    d'Alembic lui-même, pas une étape de migration — c'est pourquoi il est
    posé ici et non dans la révision 0001.

    Deux précautions :

    · on ne tente le CREATE que si le schéma est absent. Créer un schéma
      demande le droit CREATE sur la base ; le rôle des migrations ne l'a pas
      forcément, et il n'en a pas besoin quand le bootstrap a déjà fait le
      travail (il crée le schéma en superutilisateur puis en donne la
      propriété au rôle des migrations).
    · connexion séparée en AUTOCOMMIT : la connexion des migrations, elle,
      appartient entièrement à la transaction d'Alembic.
    """
    with connectable.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as sonde:
        existe = sonde.exec_driver_sql(
            "SELECT to_regnamespace('arac') IS NOT NULL"
        ).scalar()
        if not existe:
            sonde.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS arac")


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    _garantir_schema(connectable)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="arac",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
