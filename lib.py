"""Shared search backend used by search.py, compare.py and app.py.

Three retrieval modes — all return a pandas DataFrame with the same columns:
  - "vector"  : pure embedding similarity (Cohere embed-english-v3.0)
  - "keyword" : pure full-text search (LanceDB native FTS / BM25)
  - "hybrid"  : combines both, then reranks the union with Cohere Rerank

LanceDB's embedding registry handles query-side embedding automatically and
also picks the right Cohere `input_type` per call (search_query vs search_document).
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache

import lancedb
import pandas as pd
from dotenv import load_dotenv
from lancedb.rerankers import CohereReranker

load_dotenv()

DB_PATH = "data/lancedb"
TABLE = "jobs"

Mode = str  # "vector" | "keyword" | "hybrid"


def require_env(name: str, hint: str = "") -> str:
    """Read an env var or exit with a friendly message."""
    val = os.environ.get(name)
    if val:
        return val
    msg = f"\n✗ missing env var: {name}"
    if hint:
        msg += f"\n  → {hint}"
    msg += "\n  copy .env.example to .env and fill in your keys.\n"
    print(msg, file=sys.stderr)
    raise SystemExit(1)


@lru_cache(maxsize=1)
def _table():
    if not os.path.exists(DB_PATH):
        raise SystemExit(
            f"\n✗ no LanceDB found at {DB_PATH}\n"
            "  → run `python scrape.py && python index.py` first.\n"
        )
    return lancedb.connect(DB_PATH).open_table(TABLE)


@lru_cache(maxsize=1)
def _reranker() -> CohereReranker:
    # rerank-v3.5 pinned for its price/latency profile (the v3.0 default is dated).
    # Cohere's newer generation is rerank-v4.0: "rerank-v4.0-pro" (quality) or "rerank-v4.0-fast" (latency).
    api_key = require_env("COHERE_API_KEY", "get one at https://dashboard.cohere.com/api-keys")
    return CohereReranker(model_name="rerank-v3.5", api_key=api_key)


def search(query: str, mode: Mode = "hybrid", limit: int = 10, where: str | None = None) -> pd.DataFrame:
    """Run a search in the given mode and return a DataFrame of results."""
    table = _table()

    if mode == "vector":
        q = table.search(query, query_type="vector")
    elif mode == "keyword":
        q = table.search(query, query_type="fts")
    elif mode == "hybrid":
        q = table.search(query, query_type="hybrid").rerank(reranker=_reranker())
    else:
        raise ValueError(f"unknown mode: {mode!r} (expected vector|keyword|hybrid)")

    if where:
        q = q.where(where, prefilter=True)
    return q.limit(limit).to_pandas()


def render_row(row: pd.Series, snippet_chars: int = 220) -> str:
    """One job formatted for terminal output, including a description snippet."""
    bits = []
    score_keys = ("_relevance_score", "_distance", "_score")
    score = next((row[k] for k in score_keys if k in row.index and pd.notna(row[k])), None)
    head = f"  ▸ {row['title']}"
    if score is not None:
        head += f"  ·  score {float(score):.3f}"
    bits.append(head)
    bits.append(f"    {row['company']} — {row['location']}")
    meta = "  ·  ".join(
        x for x in [row["seniority"], row["employment_type"], row.get("salary_display") or "", row["posted_date"][:10] if row["posted_date"] else ""] if x
    )
    if meta:
        bits.append(f"    {meta}")
    snippet = row.get("description_snippet") or ""
    if snippet:
        bits.append(f"    “{snippet[:snippet_chars]}…”" if len(snippet) > snippet_chars else f"    “{snippet}”")
    if row.get("apply_url"):
        bits.append(f"    {row['apply_url']}")
    return "\n".join(bits)


def render(df: pd.DataFrame) -> str:
    if df.empty:
        return "  (no results)"
    return "\n\n".join(render_row(r) for _, r in df.iterrows())
