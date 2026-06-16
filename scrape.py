"""Bulk-scrape LinkedIn jobs from Bright Data → save raw JSON.

Uses the async `/trigger` endpoint with `limit_per_input` to cap spend.
Polls until the snapshot is ready, then downloads the structured JSON.
"""

import json
import sys
import time
from pathlib import Path

import requests

from lib import require_env

BD_TOKEN = require_env("BRIGHTDATA_API_TOKEN", "get one at https://brightdata.com/cp/api_keys")
DATASET_ID = "gd_lpfll7v5hcqtkxl6l"  # LinkedIn jobs - discover by keyword
LIMIT_PER_INPUT = 100  # cap jobs per keyword
PRICE_PER_RECORD = 0.0015  # USD, per Bright Data dataset pricing

SEARCHES = [
    {
        "location": "San Francisco",
        "keyword": "machine learning engineer",
        "country": "US",
        "time_range": "Past month",
        "job_type": "Full-time",
        "experience_level": "",
        "remote": "",
        "company": "",
        "location_radius": "",
    },
    {
        "location": "New York",
        "keyword": "python developer",
        "country": "US",
        "time_range": "Past month",
        "job_type": "Full-time",
        "experience_level": "",
        "remote": "",
        "company": "",
        "location_radius": "",
    },
]

API = "https://api.brightdata.com/datasets/v3"
HEADERS = {
    "Authorization": f"Bearer {BD_TOKEN}",
    "Content-Type": "application/json",
}
OUT_PATH = Path("data/raw_jobs.json")


def trigger_snapshot() -> str:
    params = {
        "dataset_id": DATASET_ID,
        "include_errors": "true",
        "type": "discover_new",
        "discover_by": "keyword",
        "limit_per_input": str(LIMIT_PER_INPUT),
    }
    r = requests.post(
        f"{API}/trigger", headers=HEADERS, params=params, json={"input": SEARCHES}
    )
    r.raise_for_status()
    snap = r.json()["snapshot_id"]
    print(f"  triggered snapshot: {snap}")
    return snap


def wait_until_ready(snapshot_id: str, poll_seconds: int = 10, timeout_seconds: int = 900) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        r = requests.get(f"{API}/progress/{snapshot_id}", headers=HEADERS)
        r.raise_for_status()
        status = r.json().get("status")
        sys.stdout.write(f"\r  status: {status:<12}")
        sys.stdout.flush()
        if status == "ready":
            print()
            return
        if status == "failed":
            raise RuntimeError(f"snapshot {snapshot_id} failed: {r.json()}")
        time.sleep(poll_seconds)
    raise TimeoutError(f"snapshot {snapshot_id} not ready after {timeout_seconds}s")


def download(snapshot_id: str) -> list[dict]:
    r = requests.get(
        f"{API}/snapshot/{snapshot_id}", headers=HEADERS, params={"format": "json"}
    )
    r.raise_for_status()
    return r.json()


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    max_records = LIMIT_PER_INPUT * len(SEARCHES)
    est_cost = max_records * PRICE_PER_RECORD
    print(f"→ scraping {len(SEARCHES)} keyword searches, max {LIMIT_PER_INPUT} jobs each")
    print(f"  estimated max cost: ${est_cost:.2f} (at ${PRICE_PER_RECORD}/record × {max_records} max records)")

    snap = trigger_snapshot()
    wait_until_ready(snap)
    jobs = download(snap)
    actual_cost = len(jobs) * PRICE_PER_RECORD
    OUT_PATH.write_text(json.dumps(jobs, indent=2))
    print(f"✓ saved {len(jobs)} jobs → {OUT_PATH}")
    print(f"  actual cost: ${actual_cost:.2f}")
    print("  next step: `python index.py`")


if __name__ == "__main__":
    main()
