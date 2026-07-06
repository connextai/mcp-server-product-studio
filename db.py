"""The structured 'system of record' for Product Studio — a seeded SQLite DB.

Three tables model a product team building a SaaS product:

  * ``features``     — the backlog/roadmap. Each row has an NPD ``stage``
                      (idea → discovery → design → build → beta → ga), a
                      ``priority``, a RICE score, an ``effort`` estimate, an
                      ``owner`` (a demo username, so "my features" works) and a
                      ``target_release``.
  * ``experiments``  — hypotheses tied to a feature, with control/variant metric
                      values and the resulting ``lift`` (%).
  * ``metrics``      — a weekly time series of ``adoption``/``retention`` per
                      feature (for the trend charts).

Everything is in a throwaway SQLite file seeded once at startup. Tools open the
DB **read-only** (``mode=ro``) so a SQL query can never mutate it. Swap this file
for your real warehouse/connection in production.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

_DB_PATH: str | None = None

SCHEMA = """
CREATE TABLE features (
    id             INTEGER PRIMARY KEY,
    title          TEXT NOT NULL,
    stage          TEXT NOT NULL,   -- idea | discovery | design | build | beta | ga
    priority       TEXT NOT NULL,   -- P0 (highest) .. P3
    rice_score     REAL NOT NULL,   -- reach*impact*confidence / effort
    effort_weeks   INTEGER NOT NULL,
    owner          TEXT NOT NULL,   -- demo username (alice | priya)
    target_release TEXT NOT NULL    -- e.g. 2026-Q3
);
CREATE TABLE experiments (
    id          INTEGER PRIMARY KEY,
    feature_id  INTEGER NOT NULL REFERENCES features(id),
    hypothesis  TEXT NOT NULL,
    metric      TEXT NOT NULL,
    control     REAL NOT NULL,      -- baseline metric value
    variant     REAL NOT NULL,      -- treatment metric value
    lift_pct    REAL NOT NULL,      -- (variant-control)/control * 100
    status      TEXT NOT NULL       -- running | complete | inconclusive
);
CREATE TABLE metrics (
    feature_id  INTEGER NOT NULL REFERENCES features(id),
    week        TEXT NOT NULL,      -- ISO date of the week
    adoption    REAL NOT NULL,      -- fraction of active accounts using it
    retention   REAL NOT NULL       -- week-4 retention of adopters
);
CREATE TABLE feedback (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    feature      TEXT NOT NULL,     -- feature title the note is about
    sentiment    TEXT NOT NULL,     -- positive | neutral | negative
    note         TEXT NOT NULL,
    submitted_by TEXT NOT NULL,     -- the signed-in username
    created_at   TEXT NOT NULL      -- ISO timestamp
);
"""

# (id, title, stage, priority, rice, effort_weeks, owner, target_release)
FEATURES = [
    (1, "Onboarding checklist", "ga", "P0", 88.0, 2, "alice", "2026-Q2"),
    (2, "Usage-based billing", "build", "P0", 76.0, 6, "alice", "2026-Q3"),
    (3, "Passwordless login", "beta", "P1", 42.0, 3, "alice", "2026-Q3"),
    (4, "SSO / SAML", "design", "P1", 47.0, 5, "alice", "2026-Q4"),
    (5, "Audit logs", "build", "P2", 38.0, 3, "alice", "2026-Q3"),
    (6, "Export to CSV", "ga", "P2", 31.0, 1, "alice", "2026-Q2"),
    (7, "Team invites", "ga", "P1", 55.0, 2, "priya", "2026-Q2"),
    (8, "In-app activation nudges", "build", "P1", 61.0, 3, "priya", "2026-Q3"),
    (9, "Guided templates", "beta", "P1", 49.0, 3, "priya", "2026-Q3"),
    (10, "Dashboard v2", "design", "P1", 52.0, 6, "priya", "2026-Q4"),
    (11, "AI summary", "discovery", "P1", 44.0, 5, "priya", "2026-Q4"),
    (12, "Slack integration", "discovery", "P2", 34.0, 4, "priya", "2026-Q4"),
    (13, "Referral program", "idea", "P2", 29.0, 4, "priya", "2026-Q4"),
    (14, "Mobile app", "idea", "P3", 22.0, 12, "priya", "2027-Q1"),
]

# (id, feature_id, hypothesis, metric, control, variant, lift_pct, status)
EXPERIMENTS = [
    (1, 1, "An onboarding checklist raises new-account activation",
     "activation_rate", 0.38, 0.47, 23.7, "complete"),
    (2, 3, "Passwordless login reduces signup drop-off",
     "signup_completion", 0.62, 0.71, 14.5, "complete"),
    (3, 9, "Guided templates cut time-to-first-value",
     "time_to_value_min", 22.0, 15.0, -31.8, "complete"),
    (4, 8, "In-app nudges improve day-7 retention",
     "d7_retention", 0.41, 0.44, 7.3, "running"),
    (5, 7, "Team invites lift week-4 account retention",
     "w4_retention", 0.58, 0.60, 3.4, "inconclusive"),
]

# (id, feature, sentiment, note, submitted_by, created_at) — seeded so the
# feedback form's "Recent" list starts non-empty; the log_feedback tool (called
# BY the MCP App form over the tools/call bridge) appends to this table.
FEEDBACK = [
    (1, "Onboarding checklist", "positive",
     "Love the guided checklist — new-account activation is way up.",
     "priya", "2026-06-18T09:12:00"),
    (2, "Export to CSV", "neutral",
     "Works, but the export is slow for our biggest accounts.",
     "alice", "2026-06-21T14:03:00"),
    (3, "Guided templates", "positive",
     "Templates cut our time-to-first-value roughly in half.",
     "priya", "2026-06-25T11:40:00"),
]


def _metric_series() -> list[tuple]:
    """Weekly adoption/retention series for the shipped (ga/beta) features that
    have real usage — a gentle upward trend so the trend chart tells a story."""
    rows: list[tuple] = []
    # feature_id: (weeks, adoption_start, adoption_end, retention_start, retention_end)
    plans = {
        1: (8, 0.22, 0.63, 0.70, 0.79),   # Onboarding checklist (ga)
        6: (8, 0.10, 0.28, 0.55, 0.61),   # Export to CSV (ga)
        7: (8, 0.30, 0.66, 0.62, 0.71),   # Team invites (ga)
        9: (6, 0.05, 0.31, 0.48, 0.66),   # Guided templates (beta)
        3: (6, 0.08, 0.24, 0.51, 0.63),   # Passwordless login (beta)
    }
    for fid, (n, a0, a1, r0, r1) in plans.items():
        for i in range(n):
            frac = i / (n - 1)
            week = f"2026-{4 + i // 4:02d}-{1 + (i % 4) * 7:02d}"  # rough weekly dates
            adoption = round(a0 + (a1 - a0) * frac, 3)
            retention = round(r0 + (r1 - r0) * frac, 3)
            rows.append((fid, week, adoption, retention))
    return rows


def init_db() -> str:
    """Create + seed the SQLite file once; return its path."""
    global _DB_PATH
    if _DB_PATH and os.path.exists(_DB_PATH):
        return _DB_PATH
    fd, path = tempfile.mkstemp(prefix="product_studio_", suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO features VALUES (?,?,?,?,?,?,?,?)", FEATURES)
        conn.executemany(
            "INSERT INTO experiments VALUES (?,?,?,?,?,?,?,?)", EXPERIMENTS
        )
        conn.executemany("INSERT INTO metrics VALUES (?,?,?,?)", _metric_series())
        conn.executemany("INSERT INTO feedback VALUES (?,?,?,?,?,?)", FEEDBACK)
        conn.commit()
    finally:
        conn.close()
    _DB_PATH = path
    return path


def connect_readonly() -> sqlite3.Connection:
    """Open the seeded DB **read-only** so the SQL tool cannot mutate it."""
    conn = sqlite3.connect(f"file:{init_db()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")  # wait out the brief feedback-INSERT lock
    return conn


def connect_writable() -> sqlite3.Connection:
    """Open the seeded DB read-WRITE — used ONLY by the log_feedback tool, which
    does a single parameterized INSERT into ``feedback``. Everything else uses
    ``connect_readonly()``, so arbitrary SQL still cannot mutate the DB. Writes
    persist for the lifetime of this server process (the file is re-seeded on
    restart; point this at a real database to persist across restarts)."""
    conn = sqlite3.connect(init_db())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


# A compact schema the SQL tool hands to the model so it can write queries.
SCHEMA_DESCRIPTION = """\
features(id, title, stage, priority, rice_score, effort_weeks, owner, target_release)
  stage    ∈ idea, discovery, design, build, beta, ga   (NPD stage-gate order)
  priority ∈ P0 (highest) .. P3
  owner    ∈ alice, priya   (the signed-in username)
experiments(id, feature_id→features.id, hypothesis, metric, control, variant, lift_pct, status)
  status   ∈ running, complete, inconclusive
metrics(feature_id→features.id, week, adoption, retention)
  weekly time series; adoption/retention are fractions in [0,1]
feedback(id, feature, sentiment, note, submitted_by, created_at)
  sentiment ∈ positive, neutral, negative   (submitted via the feedback form)"""
