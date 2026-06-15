# Semantic Job Search

A hybrid semantic search engine over real LinkedIn job postings, in about 1,000 lines of Python. Bright Data scrapes the jobs, Cohere turns them into embeddings and reranks the results, and LanceDB stores everything and runs the search locally.

## Setup

Needs Python 3.10 or newer.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your two API keys
```

Add these to `.env`:

- `BRIGHTDATA_API_TOKEN` from brightdata.com. You also have to enable the *LinkedIn → Job listings → Discover by keyword* scraper in the Web Scrapers Library, or `scrape.py` will fail.
- `COHERE_API_KEY` from dashboard.cohere.com. The free trial key works. It allows 10 calls per minute, so `eval.py` runs a bit slower but still finishes.

## Run

```bash
python scrape.py       # fetch ~200 jobs into data/raw_jobs.json (about $0.31)
python index.py        # embed the jobs and store them in LanceDB
python search.py       # run a few demo queries
streamlit run app.py   # optional web UI at localhost:8501
```

## Files

- `scrape.py` scrapes jobs from Bright Data (async, cost-capped).
- `index.py` loads, embeds, and stores them in LanceDB (upsert, scalar indexes, full-text search, version tags).
- `search.py` runs CLI search in vector, keyword, or hybrid mode.
- `compare.py` shows the three modes side by side.
- `eval.py` scores precision@3 over 10 labeled queries.
- `stats.py` summarizes the indexed data.
- `versions.py` lists and opens tagged snapshots.
- `app.py` is the Streamlit web UI.
- `lib.py` is the shared search backend.

## Examples

```bash
python search.py "founding ML engineer at AI startup with computer vision"
python search.py "senior python engineer" --where "salary_min_annual >= 200000"
python compare.py "engineer working on LLMs and prompt engineering"
python eval.py
```

## Cost

About $0.34 for the whole demo: ~$0.31 to scrape 200 jobs, ~$0.02 to embed, ~$0.01 to rerank. LanceDB is free and runs on your machine.

## License

MIT. Data scraped from LinkedIn is subject to LinkedIn's terms; review before production use.
