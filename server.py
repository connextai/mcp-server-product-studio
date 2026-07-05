"""Entry point: build the FastMCP server, wire up auth + tools, and run it.

    python server.py

Product Studio is a **full-feature** MCP example: a product-development copilot
with its own login, a RAG tool over product docs, a read-only SQL tool over a
seeded product database, and chart MCP Apps that visualise the data. It reuses
the self-hosted OAuth login from ``mcp-server-example`` (its own login page +
demo users), so a Connext user connects by signing in to *this* server.

Configuration (all optional) comes from the environment — see .env.example:

    PUBLIC_URL   the URL the Connext platform uses to reach this server
                 (default http://localhost:8000). Everything in the OAuth
                 discovery documents is derived from it.
    HOST / PORT  the address uvicorn binds to (default 127.0.0.1:8000).
"""

from __future__ import annotations

import os

from starlette.requests import Request
from starlette.responses import PlainTextResponse

from fastmcp import FastMCP

from auth import DEMO_USERS, LoginOAuthProvider, register_login_routes
from db import init_db
from tools import register_tools

PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8000").rstrip("/")
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

SCOPES = ["read"]

# Seed the in-memory product database at startup.
init_db()

# The OAuth provider (this server is its own authorization server) — see auth.py.
provider = LoginOAuthProvider(public_url=PUBLIC_URL, users=DEMO_USERS, scopes=SCOPES)

mcp = FastMCP("Product Studio", auth=provider)

register_login_routes(mcp, provider)
register_tools(mcp)


# Unauthenticated liveness/readiness probe (for k8s + the GKE Ingress).
@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


if __name__ == "__main__":
    # Streamable-HTTP transport; the MCP endpoint is served at <PUBLIC_URL>/mcp/
    mcp.run(transport="http", host=HOST, port=PORT)
