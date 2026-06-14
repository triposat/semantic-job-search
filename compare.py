"""Side-by-side comparison: keyword vs vector vs hybrid+rerank.

Shows *why* a vector DB matters: the same query routed through three
retrieval strategies returns very different results. Keyword search
needs literal token overlap; vector search captures meaning; hybrid
combines both and reranks for precision.

Usage:
  python compare.py                            # runs preset queries
  python compare.py "your query here"
  python compare.py "ml infra" --top 3
"""

import argparse

from lib import search

# Queries chosen because they expose the weakness of pure keyword search:
# the desired jobs use *different vocabulary* than the query terms.
PRESETS = [
    "engineer working on LLMs and prompt engineering",
    "scrappy startup early-stage with equity",
    "computer vision and robotics",
    "build APIs and microservices",
]


def short(row) -> str:
    title = row["title"]
    if len(title) > 60:
        title = title[:57] + "..."
    return f"{title}  —  {row['company']}"


def compare(query: str, top: int = 5) -> None:
    print("\n" + "═" * 92)
    print(f"  query: {query}")
    print("═" * 92)

    modes = [("keyword (BM25)", "keyword"), ("vector (Cohere)", "vector"), ("hybrid + rerank", "hybrid")]
    results = {}
    for label, mode in modes:
        try:
            results[label] = search(query, mode=mode, limit=top)
        except Exception as e:
            results[label] = f"ERROR: {e}"

    for label, df in results.items():
        print(f"\n  ── {label} " + "─" * (88 - len(label)))
        if isinstance(df, str):
            print(f"  {df}")
            continue
        if df.empty:
            print("  (no results)")
            continue
        for i, (_, row) in enumerate(df.iterrows(), 1):
            print(f"  {i}. {short(row)}")

    # Compute overlap between modes — a coarse measure of how differently they rank.
    sets = {
        label: set(df["job_id"].tolist())
        for label, df in results.items()
        if not isinstance(df, str)
    }
    if len(sets) >= 2:
        kw, vec, hyb = sets.get("keyword (BM25)", set()), sets.get("vector (Cohere)", set()), sets.get("hybrid + rerank", set())
        print(f"\n  overlap: keyword∩vector={len(kw & vec)}/{top}  ·  hybrid∩vector={len(hyb & vec)}/{top}  ·  hybrid∩keyword={len(hyb & kw)}/{top}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare keyword / vector / hybrid retrieval modes.")
    parser.add_argument("query", nargs="*")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    queries = [" ".join(args.query)] if args.query else PRESETS
    for q in queries:
        compare(q, top=args.top)


if __name__ == "__main__":
    main()
