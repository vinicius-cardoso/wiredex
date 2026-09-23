from wiredex.bootstrap.settings import DEFAULT_DATABASE_URL, Settings


def test_database_url_defaults_to_the_compose_database() -> None:
    assert Settings().database_url.get_secret_value() == DEFAULT_DATABASE_URL


def test_database_password_never_shows_in_repr() -> None:
    assert "wiredex:wiredex" not in repr(Settings())
