"""Load raw BD jobs → embed via Cohere → upsert into LanceDB.

Uses three LanceDB features beyond basic indexing:

  • `merge_insert` — upserts by `job_id` so re-runs add new jobs and refresh
    existing ones (instead of dropping and re-embedding everything).
  • Scalar indexes (BTREE / BITMAP) — speed up the SQL filters used by
    `search.py --where ...` at scale.
  • Tags — every successful ingest snapshot is tagged so you can time-travel
    back to it later (`versions.py` demonstrates this).
"""

import json
from datetime import datetime
from pathlib import Path

import lancedb
from lancedb.embeddings import get_registry
from lancedb.pydantic import LanceModel, Vector

from lib import require_env

DB_PATH = "data/lancedb"
TABLE = "jobs"
RAW_PATH = Path("data/raw_jobs.json")
SNIPPET_CHARS = 280

# Hours-per-year used to normalize hourly salaries → annual for filter parity
HOURS_PER_YEAR = 2080

cohere = get_registry().get("cohere").create(
    name="embed-english-v3.0",
    api_key=require_env("COHERE_API_KEY", "get one at https://dashboard.cohere.com/api-keys"),
)


class Job(LanceModel):
    text: str = cohere.SourceField()
    vector: Vector(cohere.ndims()) = cohere.VectorField()
    job_id: str
    title: str
    company: str
    location: str
    country_code: str
    seniority: str
    employment_type: str
    job_function: str
    industry: str
    posted_date: str
    apply_url: str
    search_keyword: str
    salary_min_annual: float
    salary_max_annual: float
    salary_currency: str
    salary_display: str
    description_snippet: str


def _s(d: dict, *keys: str) -> str:
    """Return the first non-empty string for any of `keys` in `d`."""
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return str(v)
    return ""


def _normalize_salary(base: dict | None) -> tuple[float, float, str, str]:
    """→ (min_annual, max_annual, currency, display). Zeros mean missing."""
    if not base:
        return 0.0, 0.0, "", ""
    lo = float(base.get("min_amount") or 0)
    hi = float(base.get("max_amount") or 0)
    period = (base.get("payment_period") or "").lower()
    if period == "hr":
        lo *= HOURS_PER_YEAR
        hi *= HOURS_PER_YEAR
    currency = base.get("currency") or ""
    if lo and hi:
        display = f"{currency}{int(lo):,}–{currency}{int(hi):,}/yr"
    elif lo or hi:
        amt = int(lo or hi)
        display = f"{currency}{amt:,}/yr"
    else:
        display = ""
    return lo, hi, currency, display


def _make_snippet(desc: str, n: int = SNIPPET_CHARS) -> str:
    """Trim description for preview — collapse whitespace, cut on word boundary."""
    if not desc:
        return ""
    s = " ".join(desc.split())
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return cut


def to_row(j: dict) -> dict:
    title = _s(j, "job_title")
    company = _s(j, "company_name")
    description = _s(j, "job_summary")
    text = f"{title} at {company}\n\n{description}".strip()

    discovery = j.get("discovery_input") or {}
    sal_min, sal_max, sal_cur, sal_disp = _normalize_salary(j.get("base_salary"))

    return {
        "text": text,
        "job_id": _s(j, "job_posting_id"),
        "title": title,
        "company": company,
        "location": _s(j, "job_location"),
        "country_code": _s(j, "country_code"),
        "seniority": _s(j, "job_seniority_level"),
        "employment_type": _s(j, "job_employment_type"),
        "job_function": _s(j, "job_function"),
        "industry": _s(j, "job_industries"),
        "posted_date": _s(j, "job_posted_date", "job_posted_time"),
        "apply_url": _s(j, "apply_link", "url"),
        "search_keyword": _s(discovery, "keyword"),
        "salary_min_annual": sal_min,
        "salary_max_annual": sal_max,
        "salary_currency": sal_cur,
        "salary_display": sal_disp,
        "description_snippet": _make_snippet(description),
    }


def _ensure_indexes(table) -> None:
    """Create FTS + scalar indexes. Idempotent (replace=True)."""
    # Full-text (BM25) index — enables keyword + hybrid search.
    table.create_fts_index("text", replace=True)
    # Scalar indexes — dramatically speed up SQL filters at scale.
    # BTREE for range/sortable values; BITMAP for low-cardinality enums.
    table.create_scalar_index("salary_min_annual", index_type="BTREE", replace=True)
    table.create_scalar_index("seniority", index_type="BITMAP", replace=True)
    table.create_scalar_index("search_keyword", index_type="BITMAP", replace=True)
    table.create_scalar_index("employment_type", index_type="BITMAP", replace=True)


def _table_exists(db, name: str) -> bool:
    """list_tables() returns a response object; check membership defensively."""
    try:
        db.open_table(name)
        return True
    except Exception:
        return False


def main() -> None:
    if not RAW_PATH.exists():
        raise SystemExit(
            f"\n✗ missing {RAW_PATH}\n"
            "  → run `python scrape.py` first to fetch jobs from Bright Data.\n"
        )

    raw = json.loads(RAW_PATH.read_text())
    # merge_insert needs a unique key — only keep records that have a job_id.
    valid = [
        j for j in raw
        if not j.get("error") and j.get("job_title") and j.get("job_posting_id")
    ]
    skipped = len(raw) - len(valid)
    print(f"→ {len(valid)} valid jobs (skipped {skipped} with errors / missing id)")

    rows = [to_row(j) for j in valid]
    with_salary = sum(1 for r in rows if r["salary_min_annual"])
    print(f"  {with_salary}/{len(rows)} jobs have structured salary data")

    db = lancedb.connect(DB_PATH)
    is_new = not _table_exists(db, TABLE)

    if is_new:
        print(f"  creating new table — embedding {len(rows)} jobs with Cohere (~10–30s)...")
        table = db.create_table(TABLE, schema=Job)
        table.add(rows)
        action = "created"
    else:
        print(f"  upserting into existing table — embedding new/changed jobs with Cohere...")
        table = db.open_table(TABLE)
        result = (
            table.merge_insert("job_id")
                 .when_matched_update_all()
                 .when_not_matched_insert_all()
                 .execute(rows)
        )
        action = f"upserted (inserted={result.num_inserted_rows}, updated={result.num_updated_rows})"

    _ensure_indexes(table)

    # Snapshot tag — enables time-travel via versions.py.
    tag = f"ingest-{datetime.now().strftime('%Y-%m-%d-%H%M')}"
    try:
        table.tags.create(tag, table.version)
        print(f"  tagged version {table.version} as '{tag}'")
    except Exception as e:
        print(f"  (tag '{tag}' skipped: {e})")

    print(f"✓ {action} — {table.count_rows()} jobs in LanceDB ({DB_PATH}/{TABLE})")
    print("  next step: `python search.py` or `streamlit run app.py`")


if __name__ == "__main__":
    main()
