from alembic.config import Config
from alembic.script import ScriptDirectory

SCRIPT_LOCATION = "wiredex:migrations"


def alembic_config(database_url: str) -> Config:
    """Alembic settings built in code: there is no alembic.ini to keep in sync."""
    config = Config()
    config.set_main_option("script_location", SCRIPT_LOCATION)
    # File names follow the revision id: 0001_baseline.py, 0002_identity.py, ...
    config.set_main_option("file_template", "%%(rev)s_%%(slug)s")
    config.attributes["database_url"] = database_url
    return config


def next_revision_id(config: Config) -> str:
    """Sequential, readable revision ids (0001, 0002, ...) instead of random hashes."""
    heads = ScriptDirectory.from_config(config).get_heads()
    return f"{max((int(head) for head in heads), default=0) + 1:04d}"
