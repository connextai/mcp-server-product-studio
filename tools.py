"""The MCP tools this server exposes — a small product-development copilot.

Four capabilities over the seeded data (db.py) and doc corpus (rag.py):

  1. ``search_product_docs`` — RAG over customer interviews / feedback / PRDs.
  2. ``run_sql``             — a READ-ONLY SQL query over the product tables.
  3. ``describe_data``       — the schema, so the model can write ``run_sql``.
  4. ``chart_roadmap`` / ``chart_feature_adoption`` — MCP Apps that render a
                               chart (inline SVG) from the product data.

All tools run *as the signed-in user*; the SQL/chart tools can scope to
``owner = <username>`` for "my features" questions.
"""

from __future__ import annotations

import re

from mcp.types import TextContent

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token
from fastmcp.tools.tool import ToolResult

import charts
import db
import rag

CHART_URI = "ui://product-studio/chart"
CHART_MIME = "text/html;profile=mcp-app"

# run_sql is defence-in-depth. The connection is already read-only (mode=ro,
# the real guard), and we additionally require a single statement that STARTS
# with select/with AND contains no write/DDL keyword — so the guard is safe even
# if someone reuses it without mode=ro (e.g. a `WITH cte AS (...) INSERT ...`).
_READ_ONLY_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_WRITE_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|create|alter|replace|attach|detach|pragma|"
    r"vacuum|reindex|trigger|grant|revoke)\b",
    re.IGNORECASE,
)
_MAX_ROWS = 200


def _current_user() -> str:
    token = get_access_token()
    return token.subject if (token and token.subject) else "guest"


def register_tools(mcp: FastMCP) -> None:
    """Register all tools + the chart UI resource on the FastMCP app."""

    # --- 1. RAG over the product docs ------------------------------------
    @mcp.tool(
        name="search_product_docs",
        description=(
            "Search product-development documents (customer interviews, feature "
            "requests, support themes, competitor notes, PRDs) for the query and "
            "return the most relevant passages."
        ),
    )
    async def search_product_docs(query: str, limit: int = 3) -> ToolResult:
        hits = rag.search(query, k=max(1, min(limit, 8)))
        if not hits:
            return ToolResult(
                content=[TextContent(type="text", text=f"No documents matched {query!r}.")],
                structured_content={"query": query, "results": []},
            )
        lines = [
            f"[{h['kind']}] {h['title']} (score {h['score']})\n  {h['text']}"
            for h in hits
        ]
        return ToolResult(
            content=[TextContent(type="text", text="\n\n".join(lines))],
            structured_content={"query": query, "results": hits},
        )

    # --- 2. Read-only SQL over the product tables ------------------------
    @mcp.tool(
        name="run_sql",
        description=(
            "Run a READ-ONLY SQL SELECT over the product tables and return rows. "
            "Call describe_data first for the schema. The signed-in username is "
            "available for 'my features' filters (owner = '<username>')."
        ),
    )
    async def run_sql(sql: str) -> ToolResult:
        if ";" in sql.rstrip().rstrip(";"):
            raise ValueError("Only a single statement is allowed (no ';').")
        if not _READ_ONLY_START.match(sql):
            raise ValueError("Only read-only SELECT/WITH queries are allowed.")
        if _WRITE_KEYWORDS.search(sql):
            raise ValueError("Only read-only queries are allowed (write/DDL keyword found).")
        conn = db.connect_readonly()
        try:
            cur = conn.execute(sql)
            cols = [c[0] for c in cur.description] if cur.description else []
            rows = [dict(r) for r in cur.fetchmany(_MAX_ROWS)]
        finally:
            conn.close()
        preview = "\n".join(str(tuple(r.values())) for r in rows[:20]) or "(no rows)"
        text = f"{len(rows)} row(s) for user {_current_user()}:\ncolumns: {cols}\n{preview}"
        return ToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content={"columns": cols, "rows": rows, "row_count": len(rows)},
        )

    # --- 3. Schema helper ------------------------------------------------
    @mcp.tool(
        name="describe_data",
        description="Return the product-database schema for writing run_sql queries.",
    )
    async def describe_data() -> str:
        return db.SCHEMA_DESCRIPTION

    # --- 4a. Chart MCP App: roadmap funnel (features per stage) ----------
    @mcp.tool(
        name="chart_roadmap",
        description=(
            "Render a bar chart of how many features are at each roadmap stage "
            "(idea → ga). Optionally filter to one owner's features."
        ),
        meta={"ui": {"resourceUri": CHART_URI, "visibility": ["model", "app"]}},
    )
    async def chart_roadmap(owner: str | None = None) -> ToolResult:
        sql = "SELECT stage, COUNT(*) n FROM features"
        params: tuple = ()
        if owner:
            sql += " WHERE owner = ?"
            params = (owner,)
        sql += " GROUP BY stage"
        conn = db.connect_readonly()
        try:
            counts = {r["stage"]: r["n"] for r in conn.execute(sql, params)}
        finally:
            conn.close()
        total = sum(counts.values())
        scope = f"{owner}'s features" if owner else "all features"
        # The chart is drawn by the ui:// template (charts.py) from this
        # structured_content, which Connext delivers over the MCP App bridge.
        return ToolResult(
            content=[
                TextContent(type="text", text=f"Roadmap chart: {total} {scope} — {counts}"),
            ],
            structured_content={"scope": scope, "counts": counts},
        )

    # --- 4b. Chart MCP App: adoption + retention for a feature -----------
    @mcp.tool(
        name="chart_feature_adoption",
        description=(
            "Render a line chart of adoption and retention over time for a shipped "
            "feature (matched by title, e.g. 'Onboarding checklist')."
        ),
        meta={"ui": {"resourceUri": CHART_URI, "visibility": ["model", "app"]}},
    )
    async def chart_feature_adoption(feature: str) -> ToolResult:
        conn = db.connect_readonly()
        try:
            frow = conn.execute(
                "SELECT id, title FROM features WHERE title LIKE ? ORDER BY id LIMIT 1",
                (f"%{feature}%",),
            ).fetchone()
            if not frow:
                return ToolResult(
                    content=[TextContent(type="text", text=f"No feature matches {feature!r}.")],
                    structured_content={"feature": feature, "found": False},
                )
            series = conn.execute(
                "SELECT week, adoption, retention FROM metrics WHERE feature_id = ? "
                "ORDER BY week",
                (frow["id"],),
            ).fetchall()
        finally:
            conn.close()
        if not series:
            return ToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"'{frow['title']}' has no usage metrics yet (not shipped).",
                    )
                ],
                structured_content={"feature": frow["title"], "series": []},
            )
        weeks = [r["week"] for r in series]
        adoption = [r["adoption"] for r in series]
        retention = [r["retention"] for r in series]
        # The ui:// template (charts.py) draws the line chart from this data.
        return ToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"{frow['title']}: adoption {adoption[0]:.0%}→{adoption[-1]:.0%}, "
                    f"retention {retention[0]:.0%}→{retention[-1]:.0%}",
                ),
            ],
            structured_content={
                "feature": frow["title"],
                "weeks": weeks,
                "adoption": adoption,
                "retention": retention,
            },
        )

    # The shared chart MCP App (served via resources/read). This is the DYNAMIC
    # ui:// template both chart tools reference: its JS implements the SEP-1865
    # bridge, receives the tool's structured_content, and draws the SVG. Connext
    # renders THIS (not an inline result), so the drawing lives here, not in the
    # tool result.
    @mcp.resource(
        CHART_URI,
        name="product-studio-chart",
        mime_type=CHART_MIME,
        meta={"ui": {"csp": {"connectDomains": [], "resourceDomains": []}, "prefersBorder": True}},
    )
    async def chart_template() -> str:
        return charts.template_html()
