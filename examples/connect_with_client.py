"""Connect to the running server and call its tools — the way a client does.

This uses FastMCP's own client, which performs the *exact same* OAuth flow the
Connext platform performs: it discovers the OAuth endpoints, registers itself,
opens your browser to the login page, then calls tools with the access token.

Run the server first (`python server.py`), then in another terminal:

    python examples/connect_with_client.py

Your browser opens the login page — sign in as alice / password123.
"""

import asyncio
import os

from fastmcp import Client

SERVER_URL = os.environ.get("PUBLIC_URL", "http://localhost:8000").rstrip("/") + "/mcp/"


async def main() -> None:
    # auth="oauth" runs discovery -> dynamic registration -> browser login.
    async with Client(SERVER_URL, auth="oauth") as client:
        tools = await client.list_tools()
        print("Tools:", [t.name for t in tools])

        dice = await client.call_tool("roll_dice", {"sides": 20})
        print("roll_dice ->", dice.data)

        card = await client.call_tool("greeting_card", {"message": "Hello from the client!"})
        print("greeting_card structured ->", card.structured_content)


if __name__ == "__main__":
    asyncio.run(main())
