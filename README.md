# mcp-server-product-studio

A **full-feature MCP server** for the Connext platform — a small **product-development
copilot**. It shows how to combine, in one server:

- 🔐 **Its own login** — the server is its own OAuth 2.1 provider with a simple
  username/password page (same pattern as [`mcp-server-example`](https://github.com/connextai/mcp-server-example)).
- 🔎 **A RAG tool** — semantic-ish search over product documents (customer
  interviews, feature requests, PRDs, competitor notes) with a dependency-free
  BM25 retriever.
- 🗄️ **A SQL tool** — a **read-only** SQL query over a seeded product database
  (features / experiments / metrics).
- 📊 **A chart MCP App** — tools that return an inline-SVG chart Connext renders
  in the chat, derived from the product data.
- 👤 **Per-user identity** — tools run *as the signed-in user* (e.g. "my features").

It's **fully self-contained**: a seeded in-memory SQLite database + an in-memory
doc corpus, so it clones and runs with **zero external services**. Built on
[FastMCP](https://gofastmcp.com).

---

## What it demonstrates

| Capability | Tool(s) | Backed by |
| --- | --- | --- |
| Retrieve unstructured context (the "why") | `search_product_docs` | `rag.py` — BM25 over a doc corpus |
| Query structured records (the "what/when") | `run_sql`, `describe_data` | `db.py` — read-only SQLite |
| Visualise the data | `chart_roadmap`, `chart_feature_adoption` | `charts.py` — inline SVG MCP App |
| Know who's asking | all of them | own OAuth login (`auth.py`) |

The demo interactions that show them working together:

- *"What are customers saying about onboarding?"* → **RAG**
- *"Show build-stage features ranked by RICE"* → **SQL** → **chart**
- *"How is the Onboarding checklist doing?"* → **SQL** + **adoption chart**
- *"Draft next sprint's priorities"* → **RAG** (pain points) **+** **SQL** (backlog)

---

## Quick start

Requires Python 3.11+.

```bash
# 1. install
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. run
python server.py
# -> serving on http://localhost:8000  (MCP endpoint: http://localhost:8000/mcp/)

# 3. in another terminal, connect the way a client does (opens a browser login)
python examples/connect_with_client.py
# sign in as  alice / password123   (or  priya / hunter2)
```

Demo users are product managers whose usernames own features in the data, so
"my features" works:

| username | password | owns |
| -------- | -------- | ---- |
| `alice`  | `password123` | Onboarding, Billing, SSO, … |
| `priya`  | `hunter2`     | Growth, Activation, Dashboard, … |

---

## The tools

**`search_product_docs(query, limit=3)`** — BM25 retrieval over the doc corpus in
`rag.py` (customer interviews, feature requests, support themes, competitor
notes, PRDs). Returns the most relevant passages with scores.

**`describe_data()` → `run_sql(sql)`** — the model calls `describe_data` for the
schema, then `run_sql` with a `SELECT`. The query runs against a SQLite file
opened **read-only** (`mode=ro`) and is additionally checked to be a single
read-only statement — a tool can never mutate the data. The signed-in username is
available for `WHERE owner = '<username>'`.

**`chart_roadmap(owner=None)`** and **`chart_feature_adoption(feature)`** — MCP
Apps. Each returns a `ToolResult` carrying both a text summary (what the model
reads) **and** a `ui://` resource with self-contained HTML+SVG (what the user
sees). Connext renders the HTML in a sandboxed iframe.

---

## The data (all seeded, self-contained)

`db.py` — three tables modelling a team building a SaaS product:

```
features(id, title, stage, priority, rice_score, effort_weeks, owner, target_release)
  stage ∈ idea → discovery → design → build → beta → ga   (NPD stage-gate)
experiments(id, feature_id, hypothesis, metric, control, variant, lift_pct, status)
metrics(feature_id, week, adoption, retention)            (weekly time series)
```

`rag.py` — ~10 short product documents (interviews, requests, PRDs, competitor
notes) that reference the same features, so RAG and SQL tell a **joined** story.

---

## The chart MCP App

An MCP App is a tool whose result includes a `ui://` **resource** carrying HTML.
The charts here are **inline SVG** built in `charts.py` — no external scripts or
assets, so they render under the iframe's strict Content-Security-Policy — and
they use the host's `var(--mcp-color-*)` variables so they match the chat's
light/dark theme. The two-series colours are a **validated** categorical palette
(blue/aqua, checked for colour-blind separation and contrast).

```python
# a chart tool returns text (for the model) + a ui:// resource (for the user)
return ToolResult(
    content=[
        TextContent(text="Roadmap chart: 6 alice's features — {...}"),
        EmbeddedResource(resource=TextResourceContents(
            uri="ui://product-studio/chart",
            mimeType="text/html;profile=mcp-app",
            text="<!doctype html>…<svg>…</svg>…")),
    ],
    structured_content={"counts": {...}},
)
```

---

## Connecting it to Connext

Same as `mcp-server-example` — this server is its own OAuth provider, so Connext
drives standard OAuth 2.1 with dynamic client registration:

1. **Expose the server on a public HTTPS URL** and run it with `PUBLIC_URL` set to
   that URL (every OAuth discovery endpoint is built from it).
2. **Register it in Connext** (Admin → MCP Servers → Add): URL
   `https://<your-host>/mcp`, Transport HTTP, Auth OAuth, client id/secret blank
   (dynamic registration handles it). Enable **Allow UI** so the charts render.
3. **Connect as a user** — click Connect, sign in on this server's login page, and
   the agent can call the tools *as that user*.

---

## Taking it to production

This example keeps everything in memory / in a demo file so it's easy to read.
For a real deployment:

- **Users:** replace `DEMO_USERS` in `auth.py` with your real user store + hashed
  passwords (or delegate to SSO — see the sibling `mcp-server-entra-example`).
- **SQL:** point `db.py` at your real warehouse (Postgres/Snowflake/…) and keep
  the read-only + single-statement guardrails (add query timeouts + row limits).
- **RAG:** swap the in-memory BM25 for a real vector store + embeddings (pgvector,
  etc.) and chunk your documents.
- **Charts:** the SVG builders scale fine; add a hover/tooltip layer for richer
  interactivity if your host allows scripts in the MCP App iframe.
- **Tokens/HTTPS:** persist tokens (or issue signed JWTs) and terminate TLS in
  front; set `PUBLIC_URL` to the `https://` URL.

---

## The files

| File | What it does |
| ---- | ------------ |
| `server.py` | Entry point: seeds the DB, builds the FastMCP server with its own OAuth login, registers tools + `/health`, runs it. |
| `auth.py` | The OAuth provider + login page + demo users (from `mcp-server-example`). |
| `db.py` | Seeded, **read-only** SQLite: `features` / `experiments` / `metrics`, plus the schema the SQL tool advertises. |
| `rag.py` | The document corpus + a dependency-free BM25 retriever. |
| `tools.py` | The five tools: `search_product_docs`, `run_sql`, `describe_data`, `chart_roadmap`, `chart_feature_adoption`. |
| `charts.py` | Theme-aware inline-SVG chart builders + the MCP App HTML wrapper. |
| `examples/connect_with_client.py` | A client that runs the same OAuth flow Connext does. |
