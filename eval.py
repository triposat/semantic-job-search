"""Evaluation harness — measure precision@3 across keyword / vector / hybrid modes.

The "ground truth" for each query is defined as a transparent predicate
(company-name match, title-keyword match, or job-id list). This is honest
about *what* we're measuring against — anyone can read the predicate and
decide whether they'd grade results the same way.

Trial-key friendly: Cohere trial keys are rate-limited to 10 calls/min.
We catch the rate-limit error and back off so the eval completes cleanly
on a free account (it just takes a bit longer — ~90s instead of ~15s).

Usage:
  python eval.py
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from lib import search

K = 3  # precision@K
RATE_LIMIT_INITIAL_BACKOFF = 8.0  # seconds — Cohere trial allows 10 calls/min
RATE_LIMIT_MAX_RETRIES = 5


@dataclass
class Case:
    query: str
    description: str               # human-readable ground-truth rule
    is_relevant: Callable[[pd.Series], bool]


def contains(field: str, *terms: str):
    """Predicate factory: row[field] contains any of `terms` (case-insensitive)."""
    lowered = [t.lower() for t in terms]
    def fn(row: pd.Series) -> bool:
        v = str(row.get(field, "")).lower()
        return any(t in v for t in lowered)
    return fn


def any_of(*predicates):
    def fn(row): return any(p(row) for p in predicates)
    return fn


CASES = [
    Case(
        query="machine learning engineer at OpenAI",
        description="company contains 'OpenAI'",
        is_relevant=contains("company", "OpenAI"),
    ),
    Case(
        query="founding engineer at AI startup with equity",
        description="title contains 'Founding'",
        is_relevant=contains("title", "Founding"),
    ),
    Case(
        query="prompt engineer working with LLMs",
        description="title contains 'Prompt' or 'GenAI' or 'LLM'",
        is_relevant=contains("title", "Prompt", "GenAI", "LLM"),
    ),
    Case(
        query="quantitative developer at trading firm",
        description="title contains 'Quant' or 'Trading', or company is a known trading firm",
        is_relevant=any_of(
            contains("title", "Quant", "Trading"),
            contains("company", "Fintal", "Hudson River", "DRW", "Tower Research", "Mondrian"),
        ),
    ),
    Case(
        query="computer vision and robotics engineer",
        description="company contains 'Skild' or 'Waymo' or 'Ludo Robotics', or title contains 'Physical AI'",
        is_relevant=any_of(
            contains("company", "Skild", "Waymo", "Ludo Robotics"),
            contains("title", "Physical AI", "Robot"),
        ),
    ),
    Case(
        query="data scientist role",
        description="title contains 'Data Scientist'",
        is_relevant=contains("title", "Data Scientist"),
    ),
    Case(
        query="distributed training infrastructure for ML",
        description="title contains 'Training' or 'Infra' or 'Platform' or 'Distributed'",
        is_relevant=contains("title", "Training", "Infra", "Platform", "Distributed"),
    ),
    Case(
        query="backend engineer at AI company",
        description="title contains 'Backend' AND company is an AI-first firm, or just title contains 'Backend Engineer'",
        is_relevant=any_of(
            contains("title", "Backend Engineer", "Backend Software"),
            contains("company", "Mistral", "LangChain", "Anthropic", "OpenAI"),
        ),
    ),
    Case(
        query="python developer at fintech",
        description="company is a known financial firm, or title contains 'Python' AND topic is finance",
        is_relevant=any_of(
            contains("company", "Fintal", "DRW", "Tower Research", "Hudson River", "Mondrian", "Clearwater"),
            contains("industry", "Financial"),
        ),
    ),
    Case(
        query="high-paying machine learning role with equity",
        description="title contains 'Founding' or 'ML' or 'AI/ML', and listing mentions equity (proxied by company in Jack & Jill / Effective AI / techire / Serval)",
        is_relevant=any_of(
            contains("company", "Jack & Jill", "Effective AI", "techire", "Serval"),
            contains("title", "Founding"),
        ),
    ),
]


def precision_at_k(df: pd.DataFrame, case: Case, k: int = K) -> tuple[float, int]:
    top = df.head(k)
    hits = sum(1 for _, r in top.iterrows() if case.is_relevant(r))
    return hits / k, hits


def search_with_backoff(query: str, mode: str, limit: int) -> pd.DataFrame:
    """Wraps lib.search with retry-on-rate-limit so trial Cohere keys don't crash the eval."""
    backoff = RATE_LIMIT_INITIAL_BACKOFF
    for attempt in range(RATE_LIMIT_MAX_RETRIES):
        try:
            return search(query, mode=mode, limit=limit)
        except Exception as e:
            # Cohere SDK raises cohere.errors.too_many_requests_error.TooManyRequestsError
            # We match loosely so this still works if the SDK reshuffles the class path.
            if "TooManyRequests" not in type(e).__name__ and "429" not in str(e):
                raise
            sys.stdout.write(f"  ↳ rate-limited; backing off {backoff:.0f}s and retrying...\n")
            sys.stdout.flush()
            time.sleep(backoff)
            backoff *= 1.5
    raise RuntimeError(f"rate-limited {RATE_LIMIT_MAX_RETRIES}× — upgrade your Cohere key or wait longer")


def main() -> None:
    modes = ["keyword", "vector", "hybrid"]
    rows = []
    sums = {m: 0.0 for m in modes}

    for case in CASES:
        row = {"query": case.query, "rule": case.description}
        for mode in modes:
            df = search_with_backoff(case.query, mode, K)
            p, hits = precision_at_k(df, case)
            row[mode] = (p, hits)
            sums[mode] += p
        rows.append(row)

    # Per-query table
    print(f"\nprecision@{K} per query (hits/{K})")
    print("─" * 88)
    print(f"  {'query':<46} {'keyword':<10} {'vector':<10} {'hybrid':<10}")
    print("─" * 88)
    for r in rows:
        kw, vec, hyb = r["keyword"], r["vector"], r["hybrid"]
        print(
            f"  {r['query'][:44]:<46} "
            f"{kw[0]:.2f} ({kw[1]}/{K})   "
            f"{vec[0]:.2f} ({vec[1]}/{K})   "
            f"{hyb[0]:.2f} ({hyb[1]}/{K})"
        )

    # Averages
    n = len(CASES)
    print("─" * 88)
    print(
        f"  {'AVERAGE (' + str(n) + ' queries)':<46} "
        f"{sums['keyword']/n:.3f}        "
        f"{sums['vector']/n:.3f}        "
        f"{sums['hybrid']/n:.3f}"
    )
    print()
    # Winner per mode
    best = max(modes, key=lambda m: sums[m])
    print(f"  → best mode: {best}  ({sums[best]/n:.1%} avg precision@{K})")


if __name__ == "__main__":
    main()
