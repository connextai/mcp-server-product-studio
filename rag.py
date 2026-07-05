"""The unstructured 'context' for Product Studio — a tiny in-memory doc corpus
with a dependency-free BM25 retriever.

These are the documents a product team actually reads: customer interviews,
feature requests, support themes, competitor notes and PRD excerpts. The RAG
tool retrieves the most relevant ones for a question. It references the same
features as db.py, so the SQL and RAG tools tell a joined story (e.g. "what are
users saying about onboarding, and where is that feature on the roadmap?").

Retrieval is a compact BM25 in pure Python — good enough to demonstrate the
pattern with zero external services. Swap it for a real vector store + embeddings
(pgvector, etc.) in production.
"""

from __future__ import annotations

import math
import re
from collections import Counter

# (id, title, kind, text)
DOCS: list[dict] = [
    {
        "id": "int-001", "title": "Interview: Acme Co (mid-market)", "kind": "customer_interview",
        "text": "New admins get lost right after signup — they don't know the first "
                "thing to do and there's no checklist or guide. Two of three seats went "
                "unused the first week. Activation clearly stalls at onboarding.",
    },
    {
        "id": "req-014", "title": "Feature request: SSO / SAML", "kind": "feature_request",
        "text": "Several enterprise prospects require SAML single sign-on and SCIM "
                "provisioning before they can roll us out company-wide. This is blocking "
                "at least two six-figure deals in security review.",
    },
    {
        "id": "sup-208", "title": "Support theme: activation drop-off", "kind": "support_theme",
        "text": "Recurring tickets: users sign up, poke around, and never return. The "
                "biggest complaint is not knowing how to get to first value. In-app "
                "nudges and guided templates are the most-requested fixes.",
    },
    {
        "id": "cmp-003", "title": "Competitor teardown: Rival App", "kind": "competitor_note",
        "text": "Rival ships guided templates and an interactive onboarding checklist "
                "out of the box, and markets time-to-value heavily. Their billing is "
                "seat-based; we can differentiate with usage-based billing.",
    },
    {
        "id": "prd-021", "title": "PRD excerpt: usage-based billing", "kind": "prd",
        "text": "Goal: meter usage (events, storage) and bill monthly with transparent "
                "overages. Finance wants proration and invoices; customers want to avoid "
                "seat lock-in. This is a P0 for the 2026-Q3 release.",
    },
    {
        "id": "int-002", "title": "Interview: Beacon Labs (SMB)", "kind": "customer_interview",
        "text": "The team lives in Slack and wants notifications and a slash command "
                "there rather than another dashboard to check. A Slack integration would "
                "meaningfully increase how often they engage.",
    },
    {
        "id": "sal-050", "title": "Sales note: enterprise blockers", "kind": "sales_note",
        "text": "Deals in the pipeline are gated on audit logs and SSO for compliance. "
                "Security teams ask for exportable audit trails. Without these, enterprise "
                "procurement stalls.",
    },
    {
        "id": "fb-311", "title": "Beta feedback: guided templates", "kind": "feedback",
        "text": "Beta users love guided templates — several said it cut setup from an "
                "afternoon to minutes and was the moment the product 'clicked'. Time-to-"
                "value dropped sharply for template users.",
    },
    {
        "id": "res-007", "title": "Research: mobile demand", "kind": "research",
        "text": "Only a small, vocal minority asks for a native mobile app; most usage is "
                "desktop during work hours. Demand is real but low-priority versus "
                "activation and billing work.",
    },
    {
        "id": "int-003", "title": "Interview: Northwind (mid-market)", "kind": "customer_interview",
        "text": "Happy customers said they'd refer peers if there were an incentive. A "
                "referral program could drive qualified signups, but only after "
                "onboarding is solid enough that referrals succeed.",
    },
]

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class _BM25:
    """Minimal BM25 (Okapi) over the corpus. No external dependencies."""

    def __init__(self, docs: list[dict], k1: float = 1.5, b: float = 0.75) -> None:
        self.docs = docs
        self.k1, self.b = k1, b
        self._doc_tokens = [_tokens(f"{d['title']} {d['text']}") for d in docs]
        self._lengths = [len(t) for t in self._doc_tokens]
        self._avglen = (sum(self._lengths) / len(self._lengths)) if docs else 0.0
        self._freqs = [Counter(t) for t in self._doc_tokens]
        n = len(docs)
        df: Counter = Counter()
        for toks in self._doc_tokens:
            df.update(set(toks))
        # BM25 idf with the standard +0.5 smoothing.
        self._idf = {
            term: math.log(1 + (n - d + 0.5) / (d + 0.5)) for term, d in df.items()
        }

    def search(self, query: str, k: int = 3) -> list[tuple[dict, float]]:
        q = _tokens(query)
        scored: list[tuple[dict, float]] = []
        for i, doc in enumerate(self.docs):
            freq, length = self._freqs[i], self._lengths[i]
            score = 0.0
            for term in q:
                if term not in freq:
                    continue
                idf = self._idf.get(term, 0.0)
                tf = freq[term]
                denom = tf + self.k1 * (1 - self.b + self.b * length / (self._avglen or 1))
                score += idf * (tf * (self.k1 + 1)) / denom
            if score > 0:
                scored.append((doc, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


_INDEX = _BM25(DOCS)


def search(query: str, k: int = 3) -> list[dict]:
    """Return the top-``k`` docs for ``query`` as ``{id, title, kind, text, score}``."""
    return [
        {**doc, "score": round(score, 3)}
        for doc, score in _INDEX.search(query, k=k)
    ]
