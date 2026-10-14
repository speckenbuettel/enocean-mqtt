"""Session-based authentication for the Web UI.

The Web UI authenticates against the existing API token registry. The token is
kept server-side and represented in the browser by an opaque HttpOnly session
cookie. Requests from an authenticated browser session to ``/api/v1`` receive
an internal Bearer header before the existing API authentication middleware is
executed.
"""

from __future__ import annotations

import hmac
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

SESSION_COOKIE = "enocean_web_session"
CSRF_COOKIE = "enocean_web_csrf"
SESSION_LIFETIME_SECONDS = 8 * 60 * 60
READ_METHODS = {"GET", "HEAD", "OPTIONS"}

_PUBLIC_PATHS = {
    "/login",
    "/logout",
    "/favicon.ico",
}

_PROTECTED_UI_PATHS = {
    "/",
    "/busmonitor",
    "/devices-ui",
    "/runtime-ui",
    "/metrics-ui",
    "/logs-ui",
    "/configuration-ui",
    "/documentation-ui",
}


@dataclass(slots=True)
class WebSession:
    username: str
    bearer_token: str
    roles: set[str]
    csrf_token: str
    expires_monotonic: float


_sessions: dict[str, WebSession] = {}
_installed = False


def _load_token_entries(token_file: str | Path) -> list[dict[str, Any]]:
    token_path = Path(token_file)

    try:
        with token_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []

    tokens = payload.get("tokens") if isinstance(payload, dict) else None
    if not isinstance(tokens, list):
        return []

    return [item for item in tokens if isinstance(item, dict)]


def _authenticate(
    token_file: str | Path,
    username: str,
    password: str,
) -> tuple[str, set[str]] | None:
    for item in _load_token_entries(token_file):
        name = str(item.get("name") or "")
        token = item.get("token")
        roles = item.get("roles", [])

        if not isinstance(token, str) or not isinstance(roles, list):
            continue

        if name == username and hmac.compare_digest(token, password):
            role_set = {str(role) for role in roles}
            if "admin" in role_set:
                role_set.add("read")
            return token, role_set

    return None


def _purge_expired_sessions() -> None:
    now = time.monotonic()
    expired = [
        session_id
        for session_id, session in _sessions.items()
        if session.expires_monotonic <= now
    ]
    for session_id in expired:
        _sessions.pop(session_id, None)


def _get_session(request: Request) -> tuple[str, WebSession] | None:
    _purge_expired_sessions()
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return None

    session = _sessions.get(session_id)
    if session is None:
        return None

    return session_id, session


def _with_authorization_header(request: Request, token: str) -> None:
    headers = list(request.scope.get("headers", []))
    if any(name.lower() == b"authorization" for name, _ in headers):
        return

    headers.append((b"authorization", f"Bearer {token}".encode("latin-1")))
    request.scope["headers"] = headers


def _is_https(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded_proto.lower() == "https"


def _login_redirect(request: Request) -> RedirectResponse:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    return RedirectResponse(
        url=f"/login?next={quote(next_path, safe='/?:=&')}",
        status_code=303,
    )


def install_web_authentication(
    app: FastAPI,
    templates: Jinja2Templates,
    *,
    enabled: bool,
    token_file: str | Path,
) -> None:
    """Install login routes and session middleware exactly once."""

    global _installed
    if _installed:
        return
    _installed = True

    token_path = Path(token_file)

    async def login_get(request: Request) -> Response:
        if not enabled:
            return RedirectResponse(url="/", status_code=303)

        session_entry = _get_session(request)
        if session_entry is not None:
            return RedirectResponse(url="/", status_code=303)

        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": None,
                "next_path": request.query_params.get("next", "/"),
            },
        )

    async def login_post(request: Request) -> Response:
        if not enabled:
            return RedirectResponse(url="/", status_code=303)

        raw_body = (await request.body()).decode("utf-8", errors="replace")
        form = parse_qs(raw_body, keep_blank_values=True)
        username = form.get("username", [""])[0].strip()
        password = form.get("password", [""])[0]
        next_path = form.get("next", ["/"])[0]
        if not next_path.startswith("/") or next_path.startswith("//"):
            next_path = "/"

        authenticated = _authenticate(token_path, username, password)
        if authenticated is None:
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={
                    "error": "Invalid username or password.",
                    "next_path": next_path,
                },
                status_code=401,
            )

        bearer_token, roles = authenticated
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        _sessions[session_id] = WebSession(
            username=username,
            bearer_token=bearer_token,
            roles=roles,
            csrf_token=csrf_token,
            expires_monotonic=time.monotonic() + SESSION_LIFETIME_SECONDS,
        )

        response = RedirectResponse(url=next_path, status_code=303)
        secure = _is_https(request)
        response.set_cookie(
            SESSION_COOKIE,
            session_id,
            max_age=SESSION_LIFETIME_SECONDS,
            httponly=True,
            secure=secure,
            samesite="strict",
            path="/",
        )
        response.set_cookie(
            CSRF_COOKIE,
            csrf_token,
            max_age=SESSION_LIFETIME_SECONDS,
            httponly=False,
            secure=secure,
            samesite="strict",
            path="/",
        )
        return response

    async def logout(request: Request) -> Response:
        session_entry = _get_session(request)
        if session_entry is not None:
            session_id, _ = session_entry
            _sessions.pop(session_id, None)

        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")
        return response

    app.add_api_route(
        "/login",
        login_get,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_api_route(
        "/login",
        login_post,
        methods=["POST"],
        include_in_schema=False,
    )
    app.add_api_route(
        "/logout",
        logout,
        methods=["POST"],
        include_in_schema=False,
    )

    @app.middleware("http")
    async def web_session_middleware(request: Request, call_next):
        request.state.web_user = None
        request.state.web_roles = set()

        if not enabled:
            request.state.web_roles = {"read", "admin"}
            return await call_next(request)

        path = request.url.path
        if path.startswith("/static/") or path in _PUBLIC_PATHS:
            return await call_next(request)

        session_entry = _get_session(request)
        if session_entry is None:
            if path in _PROTECTED_UI_PATHS:
                return _login_redirect(request)
            return await call_next(request)

        _, session = session_entry
        request.state.web_user = session.username
        request.state.web_roles = session.roles

        if path.startswith("/api/v1/"):
            if request.method.upper() not in READ_METHODS:
                provided_csrf = request.headers.get("x-csrf-token", "")
                if not hmac.compare_digest(provided_csrf, session.csrf_token):
                    return Response(
                        content='{"detail":"Missing or invalid CSRF token"}',
                        status_code=403,
                        media_type="application/json",
                    )
            _with_authorization_header(request, session.bearer_token)

        return await call_next(request)
