# Build a Semantic Job Search Engine with Bright Data, LanceDB, and Cohere

Job boards make you search the way a database does, by exact words, so the right role stays hidden whenever your phrasing doesn't match the posting's. Semantic search trades that literal matching for matching on meaning, which fits messy, human-written job descriptions far better. This guide builds that engine end to end over real LinkedIn postings, then measures which search approach wins instead of assuming the most complex one does.

---

## TL;DR

This guide builds a semantic job search engine over 200 real LinkedIn job postings using Bright Data (scraping), Cohere (embeddings + rerank), and LanceDB (local vector store).

- Keyword search matches characters; vector search matches meaning. A query like "engineer who works on LLMs" finds a "GenAI Developer" role that keyword search misses.
- Bright Data's Web Scraper API returns structured LinkedIn jobs as JSON for $0.0015 per record, with no HTML parsing or anti-bot handling.
- LanceDB runs locally and composes vector search with SQL filters (salary, seniority) in 1 query, plus full-text search and Cohere reranking.
- Measured result on 10 test queries: vector search scored 70% precision@3 vs 43% for keyword. Hybrid + rerank added no measurable lift at this scale, so below ~10k rows vector alone is the right default.
- The full project is ~1,000 lines across 9 files, including an eval harness, and the [complete code is on GitHub](https://github.com/YOUR-USERNAME/semantic-job-search). Total run cost: about $0.34.

---

## The problem with keyword search

Keyword search on a job board does exactly what you ask: it returns postings whose title or description contains the literal tokens in your query. Ask for *"engineer who works on LLMs and prompt engineering"* and you'll miss roles titled *"AI Engineer"* or *"GenAI Developer"* even when they're a perfect fit. Lexical search matches characters, not meaning.

**Vector search** matches on meaning instead of exact words. Each job description is converted into an embedding (a high-dimensional vector that captures its semantic content), and so is your query. A job whose vector lands close to your query's is a good match in meaning, even when it shares none of the same words.

Turning that into a working search engine takes 3 pieces:

1. **Bright Data** scrapes 200 real LinkedIn job postings into clean structured JSON.
2. **Cohere** turns the descriptions into embeddings and reranks the final results.
3. **LanceDB** stores the embeddings locally and serves hybrid (vector + full-text) queries with SQL-style filters.

By the end you'll have a working CLI and Streamlit UI, and a good intuition for when each retrieval strategy wins. The core of each pipeline stage is shown inline, with the complete code in the linked repo.

---

## The stack at a glance

What each layer does, and why we use it:

| Layer | Tool | Why this one |
|---|---|---|
| Web data | **Bright Data** Web Scraper API | Pre-built LinkedIn scraper returns structured JSON with salary, seniority, and location, with no HTML parsing or anti-bot handling. |
| Embeddings | **Cohere** `embed-english-v3.0` | Asymmetric encoding (different input types for documents vs queries). Cohere's newer multimodal generation is `embed-v4.0`; we use v3 here for its English-only price/latency profile (plan to re-embed when v3 reaches end-of-life). |
| Reranker | **Cohere** `rerank-v3.5` | We pin v3.5 for its price/latency profile; Cohere's newer generation is `rerank-v4.0` (`-pro` for quality, `-fast` for latency). |
| Vector store | **LanceDB** | Local, embedded, no servers; supports hybrid (vector + BM25) search and SQL prefilters. |
| UI (optional) | **Streamlit** | Smallest possible web UI for a Python data app. |

This stack runs from a single Python venv on your laptop. Bright Data and Cohere are the only managed services involved; there's nothing to deploy.

---

<!-- TODO BEFORE PUBLISHING: find/replace every occurrence of "YOUR-USERNAME/semantic-job-search" (in this Setup section, the TL;DR link, and the Next steps link) with the real public repo path. -->
## Setup

The complete, runnable project is on GitHub: **[github.com/YOUR-USERNAME/semantic-job-search](https://github.com/YOUR-USERNAME/semantic-job-search)**. Clone it and install the dependencies (Python 3.10 or newer):

```bash
git clone https://github.com/YOUR-USERNAME/semantic-job-search.git
cd semantic-job-search
pip install -r requirements.txt
```

Copy the example env file and add your two API keys (a Cohere trial key works for the whole guide, as covered in the FAQ):

```bash
cp .env.example .env
# then edit .env with your keys:
#   BRIGHTDATA_API_TOKEN=...
#   COHERE_API_KEY=...
```

One Bright Data step is easy to miss: enable the LinkedIn *Discover by keyword* scraper in the dashboard before your first run (the scraping section below shows where). After that, run `python scrape.py` to pull the data and `python index.py` to build the index, and you're ready to search. The sections below walk through each step.

---

## Architecture

The system is two flows, not one. **Ingest** builds the index (run once, or on a schedule); **query** runs on every search. Both use Cohere and LanceDB, but for different work, so drawing them as one line hides what happens.

![Two-flow architecture diagram. INGEST (run once, or on a schedule): a "keyword" arrow enters Bright Data ("Discover jobs by keyword (async)"), which sends "jobs (JSON)" to Cohere ("embed (document)"), which sends "vectors" to LanceDB ("vector + FTS + scalar indexes, versioned"). QUERY (per search, default hybrid mode): a "query" arrow enters Cohere ("embed (query)"), which sends a "query vector" to LanceDB ("vector + FTS search + SQL prefilter"), which sends "candidates" to Cohere ("rerank"), which returns "ranked results". Cohere and LanceDB are tinted to show they are reused across both flows; rerank runs in hybrid mode only.](docs/screenshots/architecture.png)

*The two flows side by side. Ingest embeds documents and stores them; query embeds the search text, runs vector + full-text search with a SQL prefilter, then reranks. Cohere and LanceDB appear in both flows but do different work in each, which is why rerank never touches the ingest path.*

3 scripts run the pipeline: `scrape.py`, `index.py`, `search.py`. 6 more helpers: `lib.py` (shared search backend), `compare.py` (mode comparison), `eval.py` (precision@3), `stats.py` (dataset summary), `versions.py` (snapshot browser), and `app.py` (Streamlit UI). The sections below build the pipeline stage by stage, then measure and extend it.

---

## Scraping LinkedIn with Bright Data

LinkedIn is the canonical source for job data, but it's hostile to scrapers: rate limits, login walls, anti-bot heuristics, and an HTML structure that changes without warning. The **Web Scraper API** handles all of that with purpose-built endpoints for popular sites that return clean structured JSON.

### Choosing the right endpoint

Bright Data exposes several LinkedIn scrapers:

- **People profiles** → individual member profiles
- **Company information** → company pages
- **Job listings → Collect by URL** → scrape specific job URLs you already have
- **Job listings → Discover by keyword** ← we want this
- **Job listings → Discover by URL** → scrape from a search-results URL
- **LinkedIn posts** and **People search** → other entity types

`Discover by keyword` is the right fit because we want bulk job discovery from a search query (like a user typing "machine learning engineer" into the LinkedIn search box). A single API call returns up to 1,000 structured job postings per keyword, complete with title, company, location, seniority level, employment type, salary range, and the full job description.

**Note:** on a fresh Bright Data account, you need to enable this specific scraper in the dashboard's *Web Scrapers Library → linkedin.com → Job listings → Discover by keyword* before the API will accept requests for it. Without that, `scrape.py` returns a 401/403 error. The `dataset_id` shown below (`gd_lpfll7v5hcqtkxl6l`) becomes available after enabling.

![Bright Data dashboard showing the Web Scrapers Library menu, with the LinkedIn job listings → "Discover by keyword" endpoint selected in the left sidebar. The middle panel shows the Configuration tab with example inputs (paris/product manager, New York/python developer). The right panel shows the Code examples view with an authenticated curl request containing `dataset_id=gd_lpfll7v5hcqtkxl6l`.](docs/screenshots/bd-scraper-page.png)

*The scraper page reached through Web Scrapers Library → linkedin.com → Job listings → Discover by keyword. The Code examples panel on the right is where the `dataset_id` for this scraper is exposed.*

### Sync vs async

Bright Data offers 2 delivery modes:

- **Synchronous** (`POST /datasets/v3/scrape`) returns the data inline. Best for tiny batches.
- **Asynchronous** (`POST /datasets/v3/trigger`) returns a snapshot ID; you poll for completion and download the result. Best for anything bigger.

Average response time is ~6 seconds **per input**. For 2 keywords with `limit_per_input=100` (200 jobs total), a sync call has to hold the connection open for the whole batch, which risks timing out. Async is the safe default, and the polling loop is ~6 lines of code (see `wait_until_ready` below).

### Cost control with `limit_per_input`

The Web Scraper API is priced at $0.0015 per record. The query parameter `limit_per_input=N` caps how many results each input search returns, which is exactly the knob you want for predictable spend:

```text
2 keywords × 100 jobs × $0.0015 = $0.30 per run
```

At that price you can re-run the pipeline several times without thinking about cost.

### The code

The scraper is short: trigger a snapshot, poll until ready, download the JSON. The core is below (a production version would add retry/backoff and richer error handling):

```python
# scrape.py
import json, time, sys
from pathlib import Path
import requests
from lib import require_env

BD_TOKEN = require_env("BRIGHTDATA_API_TOKEN")
DATASET_ID = "gd_lpfll7v5hcqtkxl6l"  # LinkedIn jobs - discover by keyword
LIMIT_PER_INPUT = 100

SEARCHES = [
    {"location": "San Francisco", "keyword": "machine learning engineer",
     "country": "US", "time_range": "Past month", "job_type": "Full-time",
     "experience_level": "", "remote": "", "company": "", "location_radius": ""},
    {"location": "New York", "keyword": "python developer",
     "country": "US", "time_range": "Past month", "job_type": "Full-time",
     "experience_level": "", "remote": "", "company": "", "location_radius": ""},
]

API = "https://api.brightdata.com/datasets/v3"
HEADERS = {"Authorization": f"Bearer {BD_TOKEN}", "Content-Type": "application/json"}

def trigger_snapshot() -> str:
    r = requests.post(f"{API}/trigger", headers=HEADERS, json={"input": SEARCHES},
        params={"dataset_id": DATASET_ID, "type": "discover_new",
                "discover_by": "keyword", "include_errors": "true",
                "limit_per_input": str(LIMIT_PER_INPUT)})
    r.raise_for_status()
    return r.json()["snapshot_id"]

def wait_until_ready(snapshot_id: str) -> None:
    while True:
        status = requests.get(f"{API}/progress/{snapshot_id}", headers=HEADERS).json()["status"]
        if status == "ready": return
        if status == "failed": raise RuntimeError("snapshot failed")
        time.sleep(10)

def download(snapshot_id: str) -> list[dict]:
    return requests.get(f"{API}/snapshot/{snapshot_id}",
                        headers=HEADERS, params={"format": "json"}).json()
```

Running it:

```text
$ python scrape.py
→ scraping 2 keyword searches, max 100 jobs each
  estimated max cost: $0.30 (at $0.0015/record × 200 max records)
  triggered snapshot: sd_mojicp6g39xwbwqn2
  status: ready
✓ saved 204 jobs → data/raw_jobs.json
  actual cost: $0.31
```

### What you get back

Each job in the JSON has 25+ fields. Here are the ones that matter:

```json
{
  "job_posting_id": "<id>",
  "job_title": "Associate Machine Learning Engineer",
  "company_name": "ExampleCo",
  "job_location": "San Francisco, CA",
  "job_seniority_level": "Entry level",
  "job_employment_type": "Full-time",
  "job_industries": "Software Development",
  "job_summary": "About ExampleCo. ExampleCo is the career network for the AI economy...",
  "base_salary": {
    "min_amount": 115000,
    "max_amount": 144000,
    "currency": "$",
    "payment_period": "yr"
  },
  "job_posted_date": "2026-04-25T03:41:21.072Z",
  "url": "https://www.linkedin.com/jobs/view/<id>"
}
```

The structured `base_salary` field is what makes salary-filter queries possible in the next step.

---

## Indexing with Cohere and LanceDB

We have 204 raw job records. Now we need to make them semantically searchable.

### Why Cohere

3 reasons we picked Cohere over alternatives (OpenAI's embedding models, Voyage AI, or local sentence-transformers):

1. **Asymmetric encoding.** Cohere lets you tag the input as `search_document` when indexing or `search_query` when searching. The model encodes each role differently, which beats treating both the same.
2. **Declarative embedding.** LanceDB's registry supports Cohere natively (as it does OpenAI and sentence-transformers), so embedding happens on insert and query with no manual `embed()` calls.
3. **The Rerank API.** A separate model that takes a query plus a candidate list and re-orders the candidates by actual relevance. It's the second stage that can sharpen a hybrid pipeline's ranking, and we add it with a single line.

### LanceDB's embedding registry

The cleanest way to use embeddings in LanceDB is through its embedding registry. You declare your schema once, and embeddings happen automatically on every insert and every query, including with the right `input_type` for each side.

```python
# index.py
import lancedb
from lancedb.embeddings import get_registry
from lancedb.pydantic import LanceModel, Vector

cohere = get_registry().get("cohere").create(
    name="embed-english-v3.0",
    api_key=COHERE_API_KEY,
)

class Job(LanceModel):
    text: str = cohere.SourceField()              # ← what to embed
    vector: Vector(cohere.ndims()) = cohere.VectorField()  # ← stored embedding
    job_id: str
    title: str
    company: str
    location: str
    seniority: str
    employment_type: str
    country_code: str
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
```

There are no explicit `cohere.embed(texts=...)` calls anywhere in our code. The `SourceField` declaration above is the entire interface.

### Schema design: the salary normalization trick

Most jobs have salaries quoted per year, but a few are per hour. To make `salary_min_annual >= 200000` work consistently, we normalize on ingest:

```python
HOURS_PER_YEAR = 2080

def _normalize_salary(base):
    if not base:
        return 0.0, 0.0, "", ""
    lo = float(base.get("min_amount") or 0)
    hi = float(base.get("max_amount") or 0)
    if (base.get("payment_period") or "").lower() == "hr":
        lo *= HOURS_PER_YEAR
        hi *= HOURS_PER_YEAR
    currency = base.get("currency") or ""
    display = f"{currency}{int(lo):,}–{currency}{int(hi):,}/yr" if (lo and hi) else ""
    return lo, hi, currency, display
```

We store both the raw numeric values (for filters) and a human-readable display string (for the UI).

### Incremental updates with `merge_insert`

The first time `index.py` runs it creates the table. Every subsequent run is an **upsert** keyed on `job_id`:

```python
result = (
    table.merge_insert("job_id")
         .when_matched_update_all()       # refresh existing job postings
         .when_not_matched_insert_all()   # add newly-discovered ones
         .execute(rows)
)
print(f"inserted={result.num_inserted_rows}, updated={result.num_updated_rows}")
```

New job postings from a fresh Bright Data scrape are inserted, and re-posted jobs (same `job_id`) have their salaries, descriptions, and timestamps refreshed. To prune stale postings entirely, chain `.when_not_matched_by_source_delete()`.

The whole upsert is a single atomic transaction. Because Lance stores data columnarly with copy-on-write, re-ingesting 200 unchanged jobs barely touches disk; only the changed columns and rows are rewritten.

### Scalar indexes: making SQL filters fast at scale

When `search.py --where "salary_min_annual >= 200000"` runs, LanceDB applies the filter *before* the vector scan (`prefilter=True`, covered in the hybrid-search section below). At 200 rows that's instant either way. At 200,000 rows the filter would walk the entire column unless we tell LanceDB how to index it:

```python
table.create_scalar_index("salary_min_annual", index_type="BTREE",  replace=True)
table.create_scalar_index("seniority",         index_type="BITMAP", replace=True)
table.create_scalar_index("search_keyword",    index_type="BITMAP", replace=True)
table.create_scalar_index("employment_type",   index_type="BITMAP", replace=True)
```

2 index types cover what we need:

- **BTREE** for sortable, higher-cardinality columns. `salary_min_annual` benefits because we want range queries (`>=`, `BETWEEN`).
- **BITMAP** for low-cardinality enums. `seniority` has ~6 distinct values, `employment_type` is almost all `Full-time`, and `search_keyword` is one of our 2 scrape inputs. Each distinct value gets its own bitmap; an `=` filter becomes a single bitwise AND.

Both run with `replace=True`, so re-running `index.py` rebuilds them idempotently. After the call, `table.list_indices()` reports all 5 (the 4 scalar + the FTS index):

```text
text_idx               type=FTS      columns=['text']
salary_min_annual_idx  type=BTree    columns=['salary_min_annual']
seniority_idx          type=Bitmap   columns=['seniority']
search_keyword_idx     type=Bitmap   columns=['search_keyword']
employment_type_idx    type=Bitmap   columns=['employment_type']
```

### Inspecting the indexed data

After running `python index.py`, our companion script `stats.py` summarizes what's in the database:

```text
$ python stats.py

📊 LanceDB · table 'jobs'  ·  200 rows

by source keyword
  machine learning engineer  ████████████████████ 100
  python developer           ████████████████████ 100

by seniority
  Mid-Senior level  ████████████████████ 99
  Entry level       ████████████ 62
  Not Applicable    ████ 20
  Internship        ██ 14
  Associate          4
  Director           1

salary coverage: 43/200 jobs (22%)
  min  $   65,000
  med  $  150,000
  max  $1,000,000

  highest-paying jobs:
    • Quantitative Developer (Python)                  Fintal Partners       $400,000–$1,000,000/yr
    • Machine Learning Engineer                        Mercor                $130,000–$500,000/yr
    • Data Scientist                                   Triumph               $200,000–$400,000/yr
    • Senior Python Developer (Middle Office Tech)     Quantitative Systems  $200,000–$400,000/yr
    • ML Engineer (Infra & Distributed training)       techire ai            $250,000–$400,000/yr

top hiring companies (top 10)
  Turing          ████████████████████ 7
  Handshake       █████████████████ 6
  OpenAI          █████████████████ 6
  Meta            █████████████████ 6
  Jack & Jill     ██████████████ 5
  DataAnnotation  ██████████████ 5
  Catalyst Labs   ███████████ 4
  Notion          ███████████ 4
  LangChain       ███████████ 4
  Uber            ████████ 3
```

Now let's search.

---

## Hybrid search with reranking

LanceDB supports 3 search modes, and our `lib.py` exposes all 3 behind a single function:

```python
# lib.py
from lancedb.rerankers import CohereReranker

reranker = CohereReranker(model_name="rerank-v3.5")  # pinned; Cohere's newer model is rerank-v4.0

def search(query: str, mode: str = "hybrid", limit: int = 10, where: str | None = None):
    table = _table()
    if mode == "vector":
        q = table.search(query, query_type="vector")
    elif mode == "keyword":
        q = table.search(query, query_type="fts")
    elif mode == "hybrid":
        q = table.search(query, query_type="hybrid").rerank(reranker=reranker)
    if where:
        q = q.where(where, prefilter=True)
    return q.limit(limit).to_pandas()
```

A few details worth noting:

- **`query_type="hybrid"`** combines vector similarity and BM25 scores from the full-text index we built at index time (LanceDB's native FTS). The union of candidates is then reranked.
- **`.rerank(reranker)`** sends the candidate list to Cohere's Rerank API and returns its ordering. We pass `model_name="rerank-v3.5"` explicitly because the LanceDB default is older (see note #3 below).
- **`prefilter=True`** applies the SQL `WHERE` clause *before* the vector scan, not after. This is faster (smaller search space) and more accurate (you don't lose results to truncation).

### A real query

A semantic-friendly query is the cleanest way to see hybrid search in action. Here are the top 2 results for a query that doesn't share many literal words with any job title in the dataset:

```text
$ python search.py "deep learning model training with GPUs"

  ▸ Training: ML Framework Engineer  ·  score 0.275
    OpenAI — San Francisco, CA
    Entry level · Full-time · 2026-04-22
    "About The Team Training Runtime designs the core distributed
     machine-learning training runtime that powers everything from early
     research experiments to frontier-scale model runs..."

  ▸ Machine Learning Engineer  ·  score 0.138
    Skild AI — San Mateo, CA
    Entry level · Full-time · 2026-04-15
    "Company Overview At Skild AI, we are building the world's first
     general purpose robotic intelligence that is robust and adapts to
     unseen scenarios without failing. We believe massive scale through
     data-driven machine learning..."
```

The snippets explain the match. Neither job's title contains "GPUs," but both descriptions are about distributed ML training, which is what the query is asking about. Pure keyword search would likely have missed both.

> A note on scores: vector mode returns cosine distance (lower = closer), hybrid+rerank returns Cohere's relevance score (0 to 1, higher = better), and keyword mode returns raw BM25 (unbounded, higher = more keyword overlap). The numbers aren't comparable across modes, only within a single mode.

### Combining semantics with hard constraints

Semantic similarity and SQL filters compose naturally in LanceDB:

```text
$ python search.py "fintech python role with equity" \
    --where "salary_min_annual >= 250000"

  ▸ Quantitative Developer (Python)  ·  score 0.374
    Fintal Partners — New York, United States
    Mid-Senior level · Full-time · $400,000–$1,000,000/yr · 2026-04-22

  ▸ Senior Software Engineer (Python)  ·  score 0.272
    Fintal Partners — New York, NY
    Mid-Senior level · Full-time · $250,000–$400,000/yr · 2026-04-23
```

The vector half handles the descriptive part ("fintech python with equity"); the SQL filter handles the numeric constraint (`>= $250k`). Both results are Fintal Partners roles in the right pay band.

The same hybrid + filter pattern in the Streamlit UI, run on a later scrape (the live listings differ from the CLI run above):

![Streamlit search interface with the query "fintech python role with equity" and the Min salary slider in the sidebar dragged to $250,000. The results header reads "3 results · mode: hybrid · filter: salary_min_annual >= 250000". The top result card shows Senior Software Engineer (Python) at Fintal Partners in New York, NY, with badges for Mid-Senior level, Full-time, and a green salary badge reading $300,000–$500,000/yr, relevance score 0.272, and a snippet about a quantitative trading firm. A second result, Data Scientist at OpenArt AI in San Francisco, score 0.165, begins below.](docs/screenshots/streamlit-salary-filter.png)

*A hybrid query with the salary slider set, served from `app.py`. The descriptive part goes through the vector index; the slider produces the `salary_min_annual >= 250000` SQL prefilter shown in the green-on-black filter banner.*

---

## Where the 3 modes disagree

Rather than argue from intuition, let's run the same query through all 3 modes. `compare.py` prints a side-by-side report:

```text
$ python compare.py "engineer working on LLMs and prompt engineering" --top 3

══════════════════════════════════════════════════════════════════════════
  query: engineer working on LLMs and prompt engineering
══════════════════════════════════════════════════════════════════════════

  ── keyword (BM25) ───────────────────────────────────────────────────────
  1. AI/ML Engineer                                          — Careerswift
  2. AI/ML Engineer                                          — Careerswift
  3. Applied AI Engineer                                     — Serval

  ── vector (Cohere) ──────────────────────────────────────────────────────
  1. Senior Software Engineer (Prompt Engineer Python/GenAI)        — Genpact
  2. 15+ Years exp/ Need f2f/ AI/ML Engineer or Python AI Engi...   — Jobs via Dice
  3. ML Engineer (Infra & Distributed training)                     — techire ai

  ── hybrid + rerank ──────────────────────────────────────────────────────
  1. Applied AI Engineer                                     — Serval
  2. Senior Software Engineer (Prompt Engineer Python/GenAI) — Genpact
  3. AI/ML Engineer                                          — Careerswift

  overlap: keyword∩vector=0/3 · hybrid∩vector=1/3 · hybrid∩keyword=2/3
```

Look at the overlap row: **keyword and vector found 0 of the same jobs in the top 3.** They're searching different conceptual spaces.

- Keyword (BM25) finds postings where the literal tokens "LLMs" and "prompt" appear most frequently. It returns generic AI/ML titles.
- Vector (Cohere) finds the *Senior Software Engineer (Prompt Engineer Python/GenAI)* posting at #1, even though the user query said "prompt engineering" (gerund) and the title says "Prompt Engineer" (noun). It also returns an LLM-focused listing from Jobs via Dice that is a strong semantic match but lexically distant from the query.
- Hybrid + rerank takes the union, dedupes, and runs it through Cohere Rerank. The Serval *Applied AI Engineer* role ($200k to $325k) moves to #1: its description is dense with prompt-engineering and LLM-agent work, but neither its title nor its top BM25-weighted terms would have returned it.

For this specific query, vector and hybrid both beat keyword; no amount of stemming would have returned the Genpact or Serval results from the raw token overlap alone. But a single query is an anecdote, not evidence. Whether that pattern holds in general is a question only a real eval can answer.

---

## Measuring quality with precision@3

To measure this properly, `eval.py` scores **10 hand-crafted queries** against all 3 modes and computes **precision@3**: the fraction of the top-3 results that match a transparent ground-truth predicate.

The ground truth for each query is a Python predicate, not a magic number, so a reader can decide whether they'd grade results the same way. For *"machine learning engineer at OpenAI"*, a result counts as relevant only if its `company` field contains "OpenAI." For *"quantitative developer at trading firm"*, the rule is broader. A result counts if the title contains "Quant" or "Trading", or the company is a known trading firm (Fintal Partners, DRW, Hudson River Trading, Tower Research, Mondrian Alpha). These predicates are tuned to the sample dataset, so if you scrape fresh jobs your scores will differ. Re-tune them to your own data before reading too much into the numbers.

Running it:

```text
$ python eval.py

precision@3 per query (hits/3)
────────────────────────────────────────────────────────────────────────
  query                                          keyword    vector     hybrid
────────────────────────────────────────────────────────────────────────
  machine learning engineer at OpenAI            1.00 (3/3)  1.00 (3/3)  1.00 (3/3)
  founding engineer at AI startup with equity    0.33 (1/3)  0.67 (2/3)  0.67 (2/3)
  prompt engineer working with LLMs              0.00 (0/3)  0.67 (2/3)  0.33 (1/3)
  quantitative developer at trading firm         0.67 (2/3)  1.00 (3/3)  1.00 (3/3)
  computer vision and robotics engineer          1.00 (3/3)  0.67 (2/3)  1.00 (3/3)
  data scientist role                            0.67 (2/3)  1.00 (3/3)  1.00 (3/3)
  distributed training infrastructure for ML     0.33 (1/3)  0.67 (2/3)  0.67 (2/3)
  backend engineer at AI company                 0.33 (1/3)  0.33 (1/3)  0.33 (1/3)
  python developer at fintech                    0.00 (0/3)  0.67 (2/3)  0.33 (1/3)
  high-paying machine learning role with equity  0.00 (0/3)  0.33 (1/3)  0.33 (1/3)
────────────────────────────────────────────────────────────────────────
  AVERAGE (10 queries)                           0.433       0.700       0.667
```

### What the numbers say

From the table:

- **Vector search beats keyword search by a wide margin** at **70% vs 43% average precision@3.** All 3 queries where keyword scored 0 ("prompt engineer," "python developer at fintech," "high-paying ML with equity") had at least 1 relevant hit under vector.
- **Below ~10k candidates, skip hybrid; vector is the right default.** The 67% vs 70% gap is within noise, and the reranker adds a Cohere call per query for no measurable lift. The FTS half returns lexical near-misses that the reranker then has to filter out, which is work without payoff. Past ~10k, the second stage starts to pay off.
- **No mode is strictly dominated.** "Computer vision and robotics" is the one query where keyword (1.00) beats vector (0.67), because the relevant companies all contain literal robotics terms in their descriptions.

### When should you turn on hybrid + rerank, then?

This depends on 3 things:

- **Candidate pool size matters.** At 200 candidates, vector alone is often enough. At 10k+, hybrid's 2-stage retrieval has more room to add value.
- **Query type matters.** Queries with both semantic intent *and* distinctive keywords (a brand name, a specific technology) benefit from hybrid. Pure-semantic queries don't.
- **Reranker quality matters more than you'd think.** Cohere's rerank-v3.5 performed well in our eval; if you swap in a different reranker, re-run `eval.py` before trusting it, since a weaker reranker can reorder good vector results downward on a small candidate pool.

Use `eval.py` to make the call on your own data. It's cheap to run and easy to extend with new queries.

**Note:** the hybrid eval runs fine on a free Cohere key. The trial Rerank endpoint caps at 10 requests/min, so it hits a 429 around the 11th rerank call, but `eval.py` backs off automatically and finishes in ~90 seconds instead of ~15. Upgrade your Cohere key if you'll iterate on this often.

---

## A web UI in ~110 lines

Streamlit turns the same search backend into a clickable web app in about 110 lines; the search-and-render core is below:

```python
# app.py
import streamlit as st
from lib import search

mode = st.sidebar.radio("Mode", ["hybrid", "vector", "keyword"])
seniority = st.sidebar.selectbox("Seniority", ["any", "Entry level", "Associate", "Mid-Senior level", "Director", "Internship", "Not Applicable"])
min_salary = st.sidebar.slider("Min salary ($/yr)", 0, 500_000, 0, step=10_000)

query = st.text_input("Search jobs", placeholder="e.g. remote ML engineer...")

if query:
    where_clauses = []
    if seniority != "any":
        where_clauses.append(f"seniority = '{seniority}'")
    if min_salary > 0:
        where_clauses.append(f"salary_min_annual >= {min_salary}")
    where = " AND ".join(where_clauses) or None

    df = search(query, mode=mode, where=where, limit=10)
    for _, row in df.iterrows():
        with st.container(border=True):
            st.markdown(f"### [{row['title']}]({row['apply_url']})")
            st.markdown(f"**{row['company']}** — {row['location']}")
            st.caption(row["description_snippet"] + "…")
```

Run it:

```bash
streamlit run app.py
```

You get a full search page at `localhost:8501`: search box, mode toggle, sidebar filters for seniority, source keyword, and salary, plus result cards with badges, scores, and snippet previews.

![Streamlit search interface for the query "founding ML engineer at AI startup with computer vision" showing a hybrid result list. The sidebar contains filters for retrieval mode, seniority, source-search keyword, minimum salary, and number of results. The top result card is "Founding ML Engineer | Frontier Medical AI | $150k–$200k | SF" from CoffeeSpace in San Francisco Bay Area, with Mid-Senior level + Full-time badges, a Cohere relevance score of 0.720, and a description snippet. A second result, "AI/ML Engineer - AI Design Software Leader" with score 0.711, begins below.](docs/screenshots/streamlit-search-results.png)

*The Streamlit app running a hybrid search. The score badge on each card is Cohere's relevance score, and the snippet below the badges shows why each result made it into the top 3.*

---

## Bonus: time-travel for free

Every write to LanceDB creates a new version automatically. There's no extra cost or extra infrastructure; it's how the underlying Lance columnar format works. To make a version easy to find later, `index.py` tags it after each ingest:

```python
table.tags.create(f"ingest-{datetime.now():%Y-%m-%d-%H%M}", table.version)
```

Our companion `versions.py` script then lets you browse and open historical snapshots. After running `python index.py` once you'll see 1 tag; after a second ingest (say, re-scraping a week later) you'll see 2:

```text
$ python versions.py

📊 table 'jobs'  ·  current version: 13  ·  200 rows

🏷  tags (2):
  • ingest-2026-05-20-0905           → version 7
  • ingest-2026-05-20-0906           → version 13  ← current

  travel back with: `python versions.py --tag <name>`

$ python versions.py --tag ingest-2026-05-20-0905

📌 snapshot 'ingest-2026-05-20-0905'  ·  version 7  ·  200 rows
  • Associate Machine Learning Engineer  — Handshake
  • Machine Learning Engineer            — RZR
  • Machine Learning Engineer            — ChatGPT Jobs
```

*(The tag names above are from our specific runs; yours will reflect the timestamps when you ran `index.py`. The version numbers grow with each write, so yours will start lower.)*

A single `table.checkout(tag_or_version)` call is the entire mechanism. For a job-search product it answers questions like *"what roles were posted last quarter?"* or *"is the salary distribution shifting over time?"* without a separate time-series database. That snapshotting falls out of the Lance columnar format rather than being bolted on, which is one reason we picked LanceDB here.

---

## Cost and scale

For the demo (200 jobs, ~5 example queries):

| Item | Cost |
|---|---|
| Bright Data scrape (204 records @ $0.0015/record) | **$0.31** |
| Cohere embeddings (~228k tokens total @ $0.10/1M) | ~$0.02 |
| Cohere rerank (~$0.002/query; Rerank v3.5 at $2 / 1k searches) | ~$0.01 for 5 queries |
| LanceDB | **free** |

Total for the entire end-to-end demo: **about $0.34**.

### Scaling up

The local demo handles 200 jobs comfortably. 5 concrete levers cover the path from here to a production-scale dataset:

- **More jobs**: change `LIMIT_PER_INPUT` (max 1,000 per keyword) or add more keyword searches. 10,000 jobs costs about $15 in Bright Data credits and embeddings remain trivial.
- **More keywords / locations**: add entries to the `SEARCHES` list in `scrape.py`.
- **Scheduled refresh**: the `merge_insert` upsert we built means rerunning the pipeline just refreshes what's changed. Bright Data supports scheduled collection and delivery from the dashboard; pair that with the upsert and you have a self-updating dataset.
- **Vector index**: past ~10k rows, swap brute-force search for an HNSW or IVF_PQ index via `table.create_index(vector_column_name="vector")`. It builds on CPU by default. For a GPU build, pass `accelerator="cuda"` (or `"mps"` on Apple Silicon) with PyTorch>2.0; automatic GPU indexing is a LanceDB Enterprise feature.
- **Production vector store**: LanceDB OSS comfortably handles millions of vectors on a single node. Past hundreds of millions of vectors or terabytes of data, LanceDB Cloud and Enterprise add distributed indexing and query execution (their docs target ~10 to 50B rows / ~10 to 30 TB).

Before any of those scaling moves, though, the demo itself has sharp edges. The next section lists them.

---

## Notes from building this

7 concrete bugs and quirks we hit. In case it saves you the same hours:

1. **`list_tables()` doesn't return a list.** In LanceDB 0.30 it returns a `ListTablesResponse` object that *looks* iterable in the REPL but `if TABLE in db.list_tables()` silently fails. Use `try: db.open_table(TABLE)` and catch the exception instead, or `.tables` on the response.
2. **`table.checkout(tag)` returns `None`** and mutates the table handle in place. Looks like a bug, isn't, but the docs are sparse. Do `t = db.open_table(...); t.checkout(tag); use(t)`, not `t = db.open_table(...).checkout(tag)`.
3. **The default `CohereReranker()` uses `rerank-english-v3.0`,** an old model. Always pass a model explicitly: `rerank-v3.5` (what we pin here) or the newer `rerank-v4.0-pro` for higher quality. The default doesn't warn you.
4. **Bright Data's sync endpoint risks timeouts on bigger batches.** With `limit_per_input=100` × 2 keywords (≈200 jobs), the `/scrape` endpoint can hang. Use `/trigger` + polling for anything above ~50 records; the polling loop is ~6 lines.
5. **Some Bright Data records are error rows.** Out of our 204 scraped jobs, 4 had an `error` field set (for example, `"Crawl aborted on job cancel"`); they look superficially like normal records but have no `job_title`. Filter them in `index.py` or `merge_insert` will fail on an empty `job_id`.
6. **Salaries come in 2 periods (`yr` and `hr`)** but the schema field is the same. Without normalizing to annual (multiply hourly by 2080), a filter like `salary_min_annual >= 200000` silently misses high-paying hourly contracts and includes implausibly low salaried roles.
7. **`argparse` help strings with raw `%` break on Python 3.14.** Writing `--where "salary > 200000 AND location LIKE '%SF%'"` in your help text raises `ValueError: badly formed help string` because argparse tries to format it. Escape as `%%` or rephrase the example.

---

## What you can build next

The pattern, *Bright Data ⟶ embeddings ⟶ vector DB ⟶ hybrid search*, generalizes to almost any domain:

| Domain | Bright Data product | What you'd query |
|---|---|---|
| **Agentic web access** | **The Web MCP** (free tier: 5,000 requests/mo) | *"give an AI agent live search + scrape tools, then ground its answers against a LanceDB-backed cache of past results"* |
| **Whole-site corpora** | **Crawl API** | *"index an entire docs site or knowledge base for hybrid retrieval"* |
| **E-commerce** | Web Scraper API (Amazon products) | *"comfortable running shoes under $100 with 4+ stars"* |
| **Real estate** | Web Scraper API (Zillow / Redfin) | *"quiet family home near good schools, 3+ beds"* |
| **News intelligence** | SERP API + Web Unlocker | *"AI safety articles from this week, ranked by relevance to alignment"* |
| **Sales prospecting** | LinkedIn company info | *"Series A startups in healthcare AI based in Europe"* |
| **Restaurants** | Yelp dataset | *"cozy Italian place with outdoor seating"* |

Some natural extensions of this exact project:

- **Multi-modal search.** Switch to Cohere `embed-v4.0` (natively multimodal) and embed company logos alongside job descriptions.
- **LLM-extracted filters.** Let the user type *"remote ML jobs paying $200k+"* and have an LLM extract `remote=true, salary_min_annual >= 200000` automatically.
- **Saved searches with email alerts.** Re-run a query against the most recent scrape and notify on new matches.
- **Resume matching.** Embed a resume and search jobs by similarity to the candidate.

---

## FAQ

The 4 questions most commonly asked when someone evaluates this stack for their own project:

### Can I use this stack for sites other than LinkedIn?

Yes. Bright Data's Scrapers Library covers hundreds of sites (Amazon, Zillow, Yelp, and more), each with its own `dataset_id`. Swap the `DATASET_ID` in `scrape.py` and the `to_row()` mapping in `index.py` for the new JSON shape; the rest of the pipeline is data-agnostic and reused as-is.

### Do I need a paid Cohere account for this?

No, a trial key runs the whole demo. Cohere's trial Rerank endpoint is capped at 10 calls/min, so `eval.py` hits a 429 around the 11th rerank call and backs off automatically (~90s instead of ~15s). Scraping, indexing, and ad-hoc search stay well under the limits. Upgrade only if you iterate on the eval often.

### Why LanceDB instead of Pinecone, Weaviate, or pgvector?

LanceDB is an embedded library: no server, no separate database, no managed-service bill. It does hybrid search and Cohere reranking natively, and every write is a version snapshot. Pinecone is managed-only; Weaviate self-hosts but runs a server; pgvector needs Postgres. For a single-machine pipeline, that's the least overhead.

### How often should I re-run the scraper?

Once a day suits an active job board. Bright Data can run scheduled collection from the dashboard, and the `merge_insert` upsert dedupes on the LanceDB side, so re-runs are cheap. Postings older than ~30 days are usually closed, so old snapshots become historical; `versions.py` keeps them queryable.

---

## Next steps

The [complete project on GitHub](https://github.com/YOUR-USERNAME/semantic-job-search) is about 1,000 lines across 9 small files. Before adapting it to your own data:

1. Run `python eval.py` on your own queries. Hybrid isn't automatically the winner; the mode that wins depends on your dataset.
2. Decide a refresh cadence. `merge_insert` makes daily upserts cheap, and `versions.py` lets you snapshot each ingest.
3. Plan a key-rotation routine as part of your secrets workflow. Both BD and Cohere keys end up in `.env`, so treat them the same way you'd treat any other API credential.

Swap LinkedIn jobs for any other Bright Data scraper (Amazon products, Zillow listings, Yelp reviews, and hundreds more). Only two spots change for a new data shape: the `DATASET_ID` constant in `scrape.py` and the `to_row()` mapping in `index.py`. The rest of the pipeline is reused as-is.
