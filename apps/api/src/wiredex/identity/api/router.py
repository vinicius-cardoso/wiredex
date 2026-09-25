from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from wiredex.identity.api.cookies import clear_session_cookies, set_session_cookies
from wiredex.identity.api.credentials import presented_token, require_csrf
from wiredex.identity.api.schemas import (
    CurrentUserResponse,
    LoginRequest,
    SessionResponse,
    TokenResponse,
    UserResponse,
)
from wiredex.identity.application.sessions import (
    Authenticate,
    CurrentUser,
    ListSessions,
    LoggedIn,
    LogIn,
    LoginAttempt,
    LogOut,
    RevokeSession,
)
from wiredex.identity.domain.errors import (
    IdentityError,
    SessionNotFoundError,
    TooManyAttemptsError,
)
from wiredex.identity.domain.values import Email, Password, SessionId, SessionToken


@dataclass(frozen=True, slots=True)
class SessionUseCases:
    log_in: LogIn
    authenticate: Authenticate
    log_out: LogOut
    list_sessions: ListSessions
    revoke_session: RevokeSession


UNAUTHENTICATED = HTTPException(
    status.HTTP_401_UNAUTHORIZED, "log in first", headers={"WWW-Authenticate": "Bearer"}
)


type CurrentUserDependency = Callable[[Request], Awaitable[CurrentUser]]


def create_router(use_cases: SessionUseCases) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    async def current_user(request: Request) -> CurrentUser:
        return await _current_user(use_cases, request)

    _add_login_routes(router, use_cases, current_user)
    _add_device_routes(router, use_cases, current_user)
    return router


def _add_login_routes(
    router: APIRouter, use_cases: SessionUseCases, current_user: CurrentUserDependency
) -> None:
    @router.post("/login")
    async def login(body: LoginRequest, request: Request, response: Response) -> UserResponse:
        """Web: log in and receive the session in an HttpOnly cookie."""
        logged_in = await _log_in(use_cases, body, request)
        set_session_cookies(response, logged_in.token)
        return UserResponse.from_user(logged_in.user)

    @router.post("/tokens")
    async def tokens(body: LoginRequest, request: Request) -> TokenResponse:
        """Mobile: log in and receive the token, for `Authorization: Bearer <token>`."""
        logged_in = await _log_in(use_cases, body, request)
        user = UserResponse.from_user(logged_in.user)
        return TokenResponse(token=logged_in.token.value, user=user)

    @router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
    async def logout(
        request: Request, response: Response, _: Annotated[CurrentUser, Depends(current_user)]
    ) -> None:
        """End this session and clear its cookies."""
        # The current_user dependency has already checked the token and the CSRF header.
        await use_cases.log_out(_token_of(request))
        clear_session_cookies(response)

    @router.get("/me")
    async def me(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUserResponse:
        return CurrentUserResponse.from_current(user)


def _add_device_routes(
    router: APIRouter, use_cases: SessionUseCases, current_user: CurrentUserDependency
) -> None:
    @router.get("/sessions")
    async def sessions(
        user: Annotated[CurrentUser, Depends(current_user)],
    ) -> list[SessionResponse]:
        """Your logged-in devices, most recently used first."""
        return [SessionResponse.from_device(d) for d in await use_cases.list_sessions(user)]

    @router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def revoke_session(
        session_id: UUID,
        response: Response,
        user: Annotated[CurrentUser, Depends(current_user)],
    ) -> None:
        """Log a device out. Revoking the current session also clears its cookies."""
        await _revoke(use_cases, user, SessionId(session_id))
        if session_id == user.session.id:
            clear_session_cookies(response)


async def _current_user(use_cases: SessionUseCases, request: Request) -> CurrentUser:
    presented = presented_token(request)
    if presented is None:
        raise UNAUTHENTICATED
    require_csrf(request, presented)
    user = await use_cases.authenticate(presented.token)
    if user is None:
        raise UNAUTHENTICATED
    return user


async def _log_in(use_cases: SessionUseCases, body: LoginRequest, request: Request) -> LoggedIn:
    try:
        return await use_cases.log_in(_attempt(body, request))
    except TooManyAttemptsError as error:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(error)) from error
    except IdentityError as error:
        # A malformed email or a too-short password gets the same answer as a wrong
        # one: nothing here may hint at which accounts exist.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong email or password") from error


async def _revoke(use_cases: SessionUseCases, user: CurrentUser, session_id: SessionId) -> None:
    try:
        await use_cases.revoke_session(user, session_id)
    except SessionNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error


def _token_of(request: Request) -> SessionToken:
    presented = presented_token(request)
    if presented is None:  # unreachable behind current_user; kept for the type checker
        raise UNAUTHENTICATED
    return presented.token


def _attempt(body: LoginRequest, request: Request) -> LoginAttempt:
    client = request.client.host if request.client else "unknown"
    device = request.headers.get("User-Agent", "unknown device")
    return LoginAttempt(Email(body.email), Password(body.password), device, client)
