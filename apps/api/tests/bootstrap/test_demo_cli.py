import pytest
from click.testing import CliRunner

from wiredex.bootstrap.cli import cli


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--email", "friend@example.com", "--expires", "forever"], "like 12h, 7d or 2w"),
        (["--email", "friend@example.com", "--expires", "1y"], "like 12h, 7d or 2w"),
        (["--email", "friend@example.com", "--expires", "91d"], "from 1 hour to 90 days"),
        (["--email", "not-an-email"], "is not an email address"),
    ],
)
def test_invite_refuses_bad_input_before_touching_the_database(
    arguments: list[str], message: str
) -> None:
    result = CliRunner().invoke(cli, ["demo", "invite", *arguments])

    assert result.exit_code == 1
    assert message in result.output
