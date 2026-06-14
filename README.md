# Semantic Job Search · LanceDB + Bright Data

Build a hybrid semantic search engine over real LinkedIn job postings in about 1,000 lines of Python across nine small files (one of which is a precision@3 eval harness).

- 🌐 **[Bright Data](https://brightdata.com)** — scrapes LinkedIn jobs into structured JSON
- 🧠 **[Cohere](https://cohere.com)** — embeddings (`embed-english-v3.0`) + rerank
- 🗄️ **[LanceDB](https://lancedb.com)** — local vector store with hybrid (vector + FTS) search
- 🖥️ **[Streamlit](https://streamlit.io)** — optional web UI

---

## Quick start

```bash
# 1. install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. add your API keys
cp .env.example .env
# edit .env — see "Get API keys" below

# 3. scrape → index → search
python scrape.py        # ~1–3 min, fetches ~200 jobs (~$0.31 in BD credits)
python index.py         # ~30s, embeds and stores in LanceDB
python search.py        # runs preset demo queries

# 4. (optional) launch the web UI
streamlit run app.py    # opens http://localhost:8501
```

## Get API keys

| Service | Where to get it | Free tier? |
|---|---|---|
| **Bright Data** token | [brightdata.com/cp/api_keys](https://brightdata.com/cp/api_keys) | Trial credits available; this demo costs ~$0.31/run. **You also need to enable the *LinkedIn → Job listings → Discover by keyword* scraper in the Web Scrapers Library** before `scrape.py` will work. |
| **Cohere** API key | [dashboard.cohere.com/api-keys](https://dashboard.cohere.com/api-keys) | Yes — trial tier covers scrape, index, and ad-hoc search. Trial keys are **rate-limited to 10 calls/min**; `eval.py` makes 30+ calls and will hit this, but the script catches the 429 and backs off automatically — it just takes ~90s instead of ~15s. Upgrade if you'll iterate frequently. |

Paste both into `.env`:

```
BRIGHTDATA_API_TOKEN=...
COHERE_API_KEY=...
```

## What's in the box

```
.
├── scrape.py     # Bright Data → data/raw_jobs.json (async + cost-capped)
├── index.py      # raw_jobs.json → LanceDB: merge_insert upsert, scalar
│                 # indexes (BTREE/BITMAP), FTS, Cohere embeddings, version tag
├── search.py     # CLI hybrid search; --mode {vector|keyword|hybrid}
├── compare.py    # side-by-side: keyword vs vector vs hybrid
├── eval.py       # 10-query precision@3 harness — measure, don't guess
├── stats.py      # summary of what's indexed
├── versions.py   # list tagged snapshots and time-travel back to any
├── app.py        # Streamlit web UI
└── lib.py        # shared search backend
```

## Example queries

```bash
# semantic — finds jobs whose JD matches the meaning, not just keywords
python search.py "founding ML engineer at AI startup with computer vision"

# hybrid — vector + SQL filter (uses scalar indexes under the hood)
python search.py "senior python engineer" --where "salary_min_annual >= 200000"

# explore the dataset
python stats.py

# see why semantic search beats keyword search
python compare.py "engineer working on LLMs and prompt engineering"

# measure quality across all 3 modes (precision@3 over 10 hand-labeled queries)
python eval.py

# browse version history (each `python index.py` creates a tagged snapshot)
python versions.py
python versions.py --tag <one-of-the-tags-listed-above>   # open a historical snapshot
```

## What makes this a LanceDB demo (not a generic vector DB demo)

The pipeline showcases LanceDB-specific capabilities most tutorials skip:

- **`merge_insert` upserts** — `index.py` is re-runnable; existing jobs refresh, new ones insert, all in one atomic transaction.
- **Scalar indexes** — `BTREE` on salary, `BITMAP` on seniority / keyword / employment_type. Filters stay fast at 100k+ rows.
- **Native FTS + hybrid search** — full-text BM25 alongside vector search, fused and reranked by Cohere.
- **Auto-versioning with tags** — every ingest is a snapshot you can time-travel to. Zero extra infrastructure.
- **Embedding registry** — embeddings happen automatically on insert and query; no manual `cohere.embed()` calls anywhere.

## Customise the search

Edit `SEARCHES` in `scrape.py` to scrape different keywords / locations:

```python
SEARCHES = [
    {"location": "Berlin", "keyword": "rust developer", "country": "DE", ...},
    {"location": "London", "keyword": "data engineer",  "country": "GB", ...},
]
```

Each search costs `limit_per_input × $0.0015`. Default `LIMIT_PER_INPUT = 100` → $0.15/keyword.

## How it works

```
            Bright Data                    Cohere               LanceDB
        ┌──────────────────┐         ┌──────────────┐      ┌──────────────┐
keyword │ Discover jobs by │  jobs   │   embed +    │      │  vector + FTS│
─────►  │ keyword (async)  │ ──────► │   rerank     │ ───► │   indexes    │
        │   $0.0015/job    │ JSON    │              │      │              │
        └──────────────────┘         └──────────────┘      └──────┬───────┘
                                                                  │
                              query  ──────────────────►──────────┘
```

- **Auto-embeddings** via LanceDB's embedding registry — query strings are embedded automatically with Cohere's asymmetric `search_query` input type.
- **Prefilter** SQL `WHERE` clauses before vector scan — faster + more accurate than post-filtering.
- **Hybrid search** combines vector similarity and BM25 (LanceDB's native FTS), then Cohere Rerank produces the final ordering.

## Costs

| Operation | Cost |
|---|---|
| Scrape ~200 jobs (Bright Data, $0.0015/record) | ~$0.31 |
| Embed 200 jobs (Cohere, ~228k tokens @ $0.10/1M) | ~$0.02 |
| Rerank per query (Cohere, $2/1k searches) | ~$0.002 |
| LanceDB | free, runs locally |

## License

MIT. The data you scrape from LinkedIn is subject to LinkedIn's terms — Bright Data handles compliance for permitted use cases; review before deploying to production.
