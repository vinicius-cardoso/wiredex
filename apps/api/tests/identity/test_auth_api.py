import asyncio
from http.cookies import SimpleCookie

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from support.identity import World
from wiredex.identity.api.cookies import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from wiredex.identity.api.router import create_router

LOGIN = {"email": "owner@example.com", "password": "correct horse battery"}


@pytest.fixture
def client() -> TestClient:
    world = asyncio.run(World().with_owner())
    app = FastAPI()
    app.include_router(create_router(world.session_use_cases()), prefix="/api")
    # https: the browser (and httpx) only send Secure cookies over TLS.
    return TestClient(app, base_url="https://testserver")


def cookie_attributes(response_headers: list[str], name: str) -> str:
    header = next(h for h in response_headers if h.startswith(f"{name}="))
    return header.lower()


def test_login_sets_a_host_only_httponly_session_and_a_readable_csrf_cookie(
    client: TestClient,
) -> None:
    response = client.post("/api/auth/login", json=LOGIN)

    assert response.status_code == 200
    assert response.json()["email"] == "owner@example.com"
    set_cookies = response.headers.get_list("set-cookie")
    session = cookie_attributes(set_cookies, SESSION_COOKIE)
    csrf = cookie_attributes(set_cookies, CSRF_COOKIE)
    for attribute in ("secure", "samesite=lax", "path=/"):
        assert attribute in session
        assert attribute in csrf
    assert "httponly" in session
    assert "httponly" not in csrf
    assert "domain=" not in session  # required by the __Host- prefix


def test_me_needs_a_session(client: TestClient) -> None:
    anonymous = client.get("/api/auth/me")
    assert anonymous.status_code == 401
    assert anonymous.headers["www-authenticate"] == "Bearer"

    client.post("/api/auth/login", json=LOGIN)

    assert client.get("/api/auth/me").json()["email"] == "owner@example.com"


def test_cookie_writes_need_the_csrf_header(client: TestClient) -> None:
    client.post("/api/auth/login", json=LOGIN)

    refused = client.post("/api/auth/logout")
    accepted = client.post("/api/auth/logout", headers={CSRF_HEADER: client.cookies[CSRF_COOKIE]})

    assert refused.status_code == 403
    assert accepted.status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_bearer_tokens_need_no_csrf(client: TestClient) -> None:
    token = client.post("/api/auth/tokens", json=LOGIN).json()["token"]
    bearer = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/auth/me", headers=bearer).status_code == 200
    assert client.post("/api/auth/logout", headers=bearer).status_code == 204
    assert client.get("/api/auth/me", headers=bearer).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"email": "owner@example.com", "password": "wrong but long enough"},
        {"email": "nobody@example.com", "password": "correct horse battery"},
        {"email": "not an email", "password": "correct horse battery"},
        {"email": "owner@example.com", "password": "short"},
    ],
)
def test_every_bad_login_gets_the_same_answer(client: TestClient, body: dict[str, str]) -> None:
    response = client.post("/api/auth/login", json=body)

    assert response.status_code == 401
    assert response.json() == {"detail": "wrong email or password"}
    assert "set-cookie" not in response.headers


def test_repeated_failures_answer_429(client: TestClient) -> None:
    wrong = {"email": "owner@example.com", "password": "wrong but long enough"}
    for _ in range(5):
        client.post("/api/auth/login", json=wrong)

    response = client.post("/api/auth/login", json=LOGIN)

    assert response.status_code == 429


def test_the_cookie_is_not_readable_from_the_response_body(client: TestClient) -> None:
    response = client.post("/api/auth/login", json=LOGIN)
    session_value = SimpleCookie(
        next(h for h in response.headers.get_list("set-cookie") if h.startswith(SESSION_COOKIE))
    )[SESSION_COOKIE].value

    assert session_value not in response.text


def csrf(client: TestClient) -> dict[str, str]:
    return {CSRF_HEADER: client.cookies[CSRF_COOKIE]}


def test_the_sessions_list_marks_the_current_device(client: TestClient) -> None:
    client.post("/api/auth/tokens", json=LOGIN, headers={"User-Agent": "Phone app"})
    client.post("/api/auth/login", json=LOGIN, headers={"User-Agent": "Firefox"})

    sessions = client.get("/api/auth/sessions").json()

    assert {(s["device"], s["current"]) for s in sessions} == {
        ("Firefox", True),
        ("Phone app", False),
    }


def test_revoking_another_device_keeps_you_logged_in(client: TestClient) -> None:
    token = client.post("/api/auth/tokens", json=LOGIN).json()["token"]
    client.post("/api/auth/login", json=LOGIN)
    other = next(s for s in client.get("/api/auth/sessions").json() if not s["current"])

    response = client.delete(f"/api/auth/sessions/{other['id']}", headers=csrf(client))

    assert response.status_code == 204
    assert "set-cookie" not in response.headers
    assert client.get("/api/auth/me").status_code == 200
    assert (
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    )


def test_revoking_the_current_session_logs_you_out(client: TestClient) -> None:
    client.post("/api/auth/login", json=LOGIN)
    current = client.get("/api/auth/sessions").json()[0]

    response = client.delete(f"/api/auth/sessions/{current['id']}", headers=csrf(client))

    assert response.status_code == 204
    assert SESSION_COOKIE in response.headers["set-cookie"]
    assert client.get("/api/auth/me").status_code == 401


def test_revoking_needs_the_csrf_header_and_an_existing_session(client: TestClient) -> None:
    client.post("/api/auth/login", json=LOGIN)
    made_up = "/api/auth/sessions/0199aaaa-0000-7000-8000-000000000000"

    assert client.delete(made_up).status_code == 403
    assert client.delete(made_up, headers=csrf(client)).status_code == 404
