"""Print a summary of what's currently indexed in LanceDB.

Useful for sanity-checking after `python index.py` and for understanding
the dataset before you write filter queries.

Usage:
  python stats.py
"""

from collections import Counter

from lib import _table


def histogram(values, top: int = 10) -> str:
    counts = Counter(v for v in values if v).most_common(top)
    if not counts:
        return "  (none)"
    width = max(len(k) for k, _ in counts)
    most = counts[0][1]
    lines = []
    for label, n in counts:
        bar = "█" * int(20 * n / most)
        lines.append(f"  {label:<{width}}  {bar} {n}")
    return "\n".join(lines)


def main() -> None:
    table = _table()
    df = table.to_pandas()
    n = len(df)

    print(f"\n📊 LanceDB · table 'jobs'  ·  {n} rows\n")

    print("by source keyword")
    print(histogram(df["search_keyword"]))

    print("\nby seniority")
    print(histogram(df["seniority"]))

    print("\nby location (top 10)")
    print(histogram(df["location"]))

    print("\nby employment type")
    print(histogram(df["employment_type"]))

    print("\nby industry (top 10)")
    print(histogram(df["industry"]))

    with_salary = df[df["salary_min_annual"] > 0]
    print(f"\nsalary coverage: {len(with_salary)}/{n} jobs ({100 * len(with_salary) / n:.0f}%)")
    if not with_salary.empty:
        print(f"  min  ${int(with_salary['salary_min_annual'].min()):>9,}")
        print(f"  med  ${int(with_salary['salary_min_annual'].median()):>9,}")
        print(f"  max  ${int(with_salary['salary_max_annual'].max()):>9,}")
        top_paying = with_salary.nlargest(5, "salary_max_annual")[["title", "company", "salary_display"]]
        print("\n  highest-paying jobs:")
        for _, r in top_paying.iterrows():
            print(f"    • {r['title'][:55]:<55}  {r['company'][:25]:<25}  {r['salary_display']}")

    print("\ntop hiring companies (top 10)")
    print(histogram(df["company"]))


if __name__ == "__main__":
    main()
