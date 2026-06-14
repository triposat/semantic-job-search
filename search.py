"""CLI search over indexed LinkedIn jobs.

Default mode is hybrid (vector + FTS, reranked by Cohere). Use --mode to
switch to pure vector or pure keyword for comparison.

Usage:
  python search.py                              # demo mode: preset queries
  python search.py "remote ml engineer"
  python search.py "python backend" --mode vector
  python search.py "senior ml" --where "salary_min_annual >= 200000"
"""

import argparse
import textwrap

from lib import render, search

DEMO_QUERIES = [
    ("deep learning model training with GPUs", None),
    ("backend engineer building distributed systems", None),
    ("LLM and generative AI applications", None),
    ("senior python engineer", "seniority = 'Mid-Senior level'"),
    ("machine learning role paying at least $200k", "salary_min_annual >= 200000"),
    ("entry-level data role", "seniority = 'Entry level'"),
]


def run_demo(mode: str) -> None:
    print(f"\n[mode: {mode}]")
    for query, where in DEMO_QUERIES:
        print("\n" + "═" * 78)
        print(f"  query : {query}")
        if where:
            print(f"  filter: {where}")
        print("─" * 78)
        df = search(query, mode=mode, limit=5, where=where)
        print(render(df))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hybrid semantic + filter search over LinkedIn jobs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            examples:
              python search.py
              python search.py "remote ml engineer at AI startup"
              python search.py "senior python" --where "seniority = 'Mid-Senior level'"
              python search.py "ai infra" --mode vector
        """),
    )
    parser.add_argument("query", nargs="*", help="natural-language query")
    parser.add_argument(
        "--mode",
        choices=["vector", "keyword", "hybrid"],
        default="hybrid",
        help="retrieval mode (default: hybrid + Cohere rerank)",
    )
    parser.add_argument("--where", help="SQL filter, e.g. \"salary_min_annual >= 200000\"")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    if not args.query:
        run_demo(args.mode)
        return

    query = " ".join(args.query)
    df = search(query, mode=args.mode, limit=args.limit, where=args.where)
    print(f"\n  query : {query}")
    print(f"  mode  : {args.mode}")
    if args.where:
        print(f"  filter: {args.where}")
    print("─" * 78)
    print(render(df))


if __name__ == "__main__":
    main()
