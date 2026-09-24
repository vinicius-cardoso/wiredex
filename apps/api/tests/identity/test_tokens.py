from wiredex.identity.infrastructure.tokens import SecretSessionTokens


def test_tokens_are_long_random_and_stored_as_sha256() -> None:
    tokens = SecretSessionTokens()

    first, second = tokens.issue(), tokens.issue()

    assert first != second
    assert len(first.value) >= 43  # 32 random bytes, base64url
    assert len(tokens.hash(first).value) == 64
    assert tokens.hash(first) == tokens.hash(first)
    assert first.value not in repr(first)
