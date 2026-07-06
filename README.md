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
- 📊 **A chart MCP App** — tools that render an SVG chart (in the chat), derived
  from the product data.
- 📝 **A writable form MCP App** — a feedback form the user fills in *on the
  Connext side*; on Save it calls a tool back over the app bridge and the server
  **persists** the note, then re-renders the saved list.
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
| Visualise the data | `chart_roadmap`, `chart_feature_adoption` | `charts.py` — dynamic SVG MCP App |
| **Capture input that persists** | `feedback_form`, `log_feedback` | `feedback.py` — a **writable** form MCP App |
| Know who's asking | all of them | own OAuth login (`auth.py`) |

The demo interactions that show them working together:

- *"What are customers saying about onboarding?"* → **RAG**
- *"Show build-stage features ranked by RICE"* → **SQL** → **chart**
- *"How is the Onboarding checklist doing?"* → **SQL** + **adoption chart**
- *"Log some feedback about SSO"* → **form** → the note is **saved** and shown
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
Apps. Each returns a text summary (what the model reads) **and**
`structuredContent` (the chart data). Connext reads the shared
`ui://product-studio/chart` template and its JavaScript draws the SVG from that
data over the app bridge (see [MCP Apps](#mcp-apps-charts-read--a-form-write)).

**`feedback_form()` → `log_feedback(feature, sentiment, note)`** — a **writable**
MCP App. `feedback_form` opens the form with the feature list + recent notes; on
Save, the form's JS calls `log_feedback` back over the `tools/call` bridge, which
does a single parameterized `INSERT` (a read-write connection — `run_sql` stays
read-only) and returns the updated list. **Mark `log_feedback` app-callable in
Connext** so the form is allowed to call it.

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

## MCP Apps: charts (read) + a form (write)

An MCP App is a `ui://` HTML **resource** the host renders in a sandboxed iframe.
Connext reads the resource (`resources/read`) and talks to it over the SEP-1865
JSON-RPC bridge (`postMessage`), so the drawing/logic lives in the template's
**inline JS** — no external scripts or assets (strict CSP) — and it reads the
host's `var(--mcp-color-*)` theme tokens. Each template also reports its height
via `ui/notifications/size-changed` so the host fits the iframe to the content.

**Charts (read-only)** — `charts.py`. The tool sends the chart **data** as
`structuredContent`; the host delivers it to the template
(`ui/notifications/tool-result`) and the JS renders the SVG. The two-series
colours are a **validated** categorical palette (blue/aqua, checked for
colour-blind separation and contrast).

**Form (writable)** — `feedback.py`. Same bridge, plus the **write** direction:
on Save the form calls a tool back with `tools/call`, which the host proxies to
the server (gated by the **app-callable** allowlist):

```js
// inside the form template — call the server's write tool over the bridge
parent.postMessage({ jsonrpc: "2.0", id: 7, method: "tools/call",
  params: { name: "log_feedback",
            arguments: { feature, sentiment, note } } }, "*");
// host replies with the CallToolResult -> re-render the saved list
```

The server persists the note and returns the updated list, which the form shows —
the full **form → persist → read-back** loop, driven from the Connext side.

---

## Connecting it to Connext

Same as `mcp-server-example` — this server is its own OAuth provider, so Connext
drives standard OAuth 2.1 with dynamic client registration:

1. **Expose the server on a public HTTPS URL** and run it with `PUBLIC_URL` set to
   that URL (every OAuth discovery endpoint is built from it).
2. **Register it in Connext** (Admin → MCP Servers → Add): URL
   `https://<your-host>/mcp`, Transport HTTP, Auth OAuth, client id/secret blank
   (dynamic registration handles it). Enable **Allow UI** so the apps render, and
   mark **`log_feedback` app-callable** so the feedback form is allowed to save.
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
| `db.py` | Seeded SQLite: `features` / `experiments` / `metrics` (read-only) + `feedback` (writable via the form), plus the schema the SQL tool advertises. |
| `rag.py` | The document corpus + a dependency-free BM25 retriever. |
| `tools.py` | The seven tools: `search_product_docs`, `run_sql`, `describe_data`, `chart_roadmap`, `chart_feature_adoption`, `feedback_form`, `log_feedback`. |
| `charts.py` | The dynamic chart MCP App template (SVG drawn in-browser from the tool's data over the app bridge). |
| `feedback.py` | The **writable** feedback-form MCP App template (calls `log_feedback` back over the `tools/call` bridge). |
| `examples/connect_with_client.py` | A client that runs the same OAuth flow Connext does. |
