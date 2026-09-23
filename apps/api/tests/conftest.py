import pytest


@pytest.fixture
def anyio_backend() -> str:
    # Async tests run on asyncio only, like uvicorn in production.
    return "asyncio"
