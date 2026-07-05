"""OAuth 2.1 authorization server with a real login page.

This is the *only* non-trivial piece of the example. The goal is to show how an
MCP server becomes its own OAuth provider so that the Connext platform can let a
user connect their account.

We do NOT implement OAuth from scratch. FastMCP already ships a complete
in-memory OAuth 2.1 provider (`InMemoryOAuthProvider`) that handles:

  * Dynamic Client Registration (RFC 7591)  -> POST /register
  * the authorization endpoint               -> GET  /authorize
  * the token endpoint                       -> POST /token
  * token refresh and revocation
  * the discovery documents                  -> /.well-known/oauth-*

The only thing it is missing is a *login* — out of the box it auto-approves
every authorization request. So we subclass it and override exactly one method,
`authorize()`, to redirect the user to our own login page first. After the user
signs in, we mint the authorization code using the parent's proven logic.

Everything else (your real user database, password hashing, "Sign in with
Google", etc.) is a drop-in replacement for the two clearly-marked spots below.
"""

from __future__ import annotations

import secrets
from urllib.parse import parse_qs, urlparse

from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from fastmcp import FastMCP
from fastmcp.server.auth.auth import (
    AccessToken,
    ClientRegistrationOptions,
    RevocationOptions,
)
from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider

# ---------------------------------------------------------------------------
# 1. Your users.  Replace this dict with a real database lookup + hashed
#    passwords (e.g. bcrypt/argon2).  Kept as a plain dict here so the whole
#    auth story fits on one screen.
# ---------------------------------------------------------------------------
# Demo product-team members. The username is used as the feature `owner` in the
# SQLite data (see db.py), so a signed-in user can ask about "my features".
DEMO_USERS: dict[str, str] = {
    "alice": "password123",  # PM — owns Onboarding & Billing
    "priya": "hunter2",      # PM — owns Growth & Activation
}


class LoginOAuthProvider(InMemoryOAuthProvider):
    """An in-memory OAuth provider that asks the user to log in first."""

    def __init__(self, public_url: str, users: dict[str, str], scopes: list[str]):
        super().__init__(
            # All endpoint URLs in the discovery documents are derived from this.
            # It MUST be the URL the *platform* uses to reach this server.
            base_url=public_url,
            # Let MCP clients register themselves automatically (RFC 7591).
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=scopes,
                default_scopes=scopes,
            ),
            # Allow the platform to revoke tokens when a user disconnects.
            revocation_options=RevocationOptions(enabled=True),
        )
        self._public_url = public_url.rstrip("/")
        self._users = dict(users)

        # Short-lived bookkeeping for the login round-trip.
        self._pending: dict[str, tuple[OAuthClientInformationFull, AuthorizationParams]] = {}
        self._code_user: dict[str, str] = {}  # auth code  -> username
        self._refresh_user: dict[str, str] = {}  # refresh token -> username

    # -- the one override that adds a login page ----------------------------
    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Instead of issuing a code immediately, send the user to /login.

        FastMCP redirects the user's browser to whatever URL we return here, so
        we park the request under a random transaction id and point the browser
        at our login page. `complete_login()` finishes the flow afterwards.
        """
        txn = secrets.token_urlsafe(24)
        self._pending[txn] = (client, params)
        return f"{self._public_url}/login?txn={txn}"

    # -- helpers used by the login routes -----------------------------------
    def authenticate_user(self, username: str, password: str) -> bool:
        """Return True if the credentials are valid (constant-time compare)."""
        expected = self._users.get(username)
        return expected is not None and secrets.compare_digest(expected, password)

    async def complete_login(self, txn: str, username: str) -> str:
        """Finish a pending authorization for an authenticated user.

        Returns the redirect URL (back to the platform) carrying the auth code.
        """
        client, params = self._pending.pop(txn)
        # Call the PARENT's authorize() directly to mint the code with the
        # battle-tested logic (this bypasses our override above, so no loop).
        redirect_url = await InMemoryOAuthProvider.authorize(self, client, params)
        # Remember which user this code (and the resulting token) belongs to.
        code = parse_qs(urlparse(redirect_url).query).get("code", [None])[0]
        if code:
            self._code_user[code] = username
        return redirect_url

    # -- carry the logged-in user onto the issued tokens --------------------
    # The platform sends the access token back on every tool call. By stamping
    # the username onto the token's `subject`, tools can tell *who* is calling
    # via `get_access_token().subject`.
    async def exchange_authorization_code(self, client, authorization_code):
        username = self._code_user.pop(authorization_code.code, None)
        token = await super().exchange_authorization_code(client, authorization_code)
        self._stamp_user(token, username)
        return token

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        username = self._refresh_user.pop(refresh_token.token, None)
        token = await super().exchange_refresh_token(client, refresh_token, scopes)
        self._stamp_user(token, username)
        return token

    def _stamp_user(self, token, username: str | None) -> None:
        if username is None:
            return
        access = self.access_tokens.get(token.access_token)
        if access is not None:
            # Re-store as a FastMCP AccessToken (a subclass of the SDK's) that
            # carries the user in `subject`. This is what lets a tool read the
            # caller with `get_access_token().subject`.
            data = access.model_dump()
            data["subject"] = username
            data["claims"] = data.get("claims") or {}  # FastMCP requires a dict
            self.access_tokens[token.access_token] = AccessToken(**data)
        if token.refresh_token:
            self._refresh_user[token.refresh_token] = username


# ---------------------------------------------------------------------------
# 2. The login page.  A single HTML form posting back to /login.  Style it
#    however you like — this is what your customer's end-user sees.
# ---------------------------------------------------------------------------
def _login_page(txn: str, client_name: str, scopes: list[str], error: str = "") -> str:
    scope_text = ", ".join(scopes) if scopes else "basic access"
    error_html = f'<p class="error">{error}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Sign in</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background: #f5f6f8; margin: 0;
            display: flex; min-height: 100vh; align-items: center; justify-content: center; }}
    .box {{ background: #fff; padding: 2rem; border-radius: 12px; width: 320px;
            box-shadow: 0 6px 24px rgba(0,0,0,.08); }}
    h1 {{ font-size: 1.25rem; margin: 0 0 .25rem; }}
    p.sub {{ color: #666; font-size: .9rem; margin: 0 0 1.25rem; }}
    label {{ display: block; font-size: .8rem; color: #444; margin: .75rem 0 .25rem; }}
    input {{ width: 100%; padding: .6rem; border: 1px solid #ccc; border-radius: 8px;
             box-sizing: border-box; font-size: 1rem; }}
    button {{ width: 100%; margin-top: 1.25rem; padding: .7rem; border: 0; border-radius: 8px;
              background: #4f46e5; color: #fff; font-size: 1rem; cursor: pointer; }}
    .error {{ color: #c0392b; font-size: .85rem; margin: .5rem 0 0; }}
    .hint {{ color: #999; font-size: .75rem; margin-top: 1rem; text-align: center; }}
  </style>
</head>
<body>
  <form class="box" method="post" action="/login">
    <h1>Sign in to Product Studio</h1>
    <p class="sub"><strong>{client_name}</strong> wants to access your account ({scope_text}).</p>
    {error_html}
    <input type="hidden" name="txn" value="{txn}" />
    <label for="username">Username</label>
    <input id="username" name="username" autocomplete="username" autofocus />
    <label for="password">Password</label>
    <input id="password" name="password" type="password" autocomplete="current-password" />
    <button type="submit">Sign in &amp; authorize</button>
    <p class="hint">Demo users: alice / password123 &nbsp;·&nbsp; priya / hunter2</p>
  </form>
</body>
</html>"""


def _message_page(message: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Product Studio</title></head><body style="font-family:system-ui;padding:2rem">
<p>{message}</p></body></html>"""


def register_login_routes(mcp: FastMCP, provider: LoginOAuthProvider) -> None:
    """Attach the GET/POST /login routes to the FastMCP app."""

    @mcp.custom_route("/login", methods=["GET", "POST"])
    async def login(request: Request) -> Response:
        if request.method == "GET":
            txn = request.query_params.get("txn", "")
            pending = provider._pending.get(txn)
            if pending is None:
                return HTMLResponse(
                    _message_page("This sign-in link is invalid or has expired."),
                    status_code=400,
                )
            client, params = pending
            client_name = client.client_name or client.client_id or "An application"
            return HTMLResponse(_login_page(txn, client_name, params.scopes or []))

        # POST: verify credentials, then complete the OAuth authorization.
        form = await request.form()
        txn = str(form.get("txn", ""))
        username = str(form.get("username", "")).strip()
        password = str(form.get("password", ""))

        pending = provider._pending.get(txn)
        if pending is None:
            return HTMLResponse(
                _message_page("This sign-in link is invalid or has expired."),
                status_code=400,
            )
        client, params = pending
        client_name = client.client_name or client.client_id or "An application"

        if not provider.authenticate_user(username, password):
            return HTMLResponse(
                _login_page(txn, client_name, params.scopes or [],
                            error="Invalid username or password."),
                status_code=401,
            )

        redirect_url = await provider.complete_login(txn, username)
        return RedirectResponse(redirect_url, status_code=302)
