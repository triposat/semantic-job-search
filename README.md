# Semantic Job Search

Search LinkedIn job postings by meaning instead of exact keywords. It scrapes with Bright Data, embeds and reranks with Cohere, and runs hybrid search (vector + full-text) locally with LanceDB.

## Setup

You need Python 3.10 or newer.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then add your two API keys
```

Two keys go in `.env`:

- Get `BRIGHTDATA_API_TOKEN` from brightdata.com. Enable the *LinkedIn → Job listings → Discover by keyword* scraper in the Web Scrapers Library first, or `scrape.py` fails with a 401/403.
- Get `COHERE_API_KEY` from dashboard.cohere.com. A free trial key is fine. It caps at 10 calls/min, so `eval.py` backs off partway through and takes about 90s instead of 15s.

## Run

```bash
python scrape.py       # scrape ~200 jobs into data/raw_jobs.json (about $0.31)
python index.py        # embed and store them in LanceDB
python search.py       # run a few demo queries
streamlit run app.py   # optional web UI at localhost:8501
```

## Files

```
scrape.py     Bright Data scrape (async, cost-capped)
index.py      embed + store in LanceDB (upsert, scalar indexes, FTS, version tags)
search.py     CLI search: vector / keyword / hybrid
compare.py    all three modes side by side
eval.py       precision@3 over 10 labeled queries
stats.py      summary of the indexed data
versions.py   list and open tagged snapshots
app.py        Streamlit web UI
lib.py        shared search backend
```

## Examples

```bash
python search.py "founding ML engineer at AI startup with computer vision"
python search.py "senior python engineer" --where "salary_min_annual >= 200000"
python compare.py "engineer working on LLMs and prompt engineering"
python eval.py
```

## Cost

The whole demo costs about $0.34. That's ~$0.31 to scrape 200 jobs, ~$0.02 to embed, and ~$0.01 to rerank. LanceDB is free.

## License

MIT. Data you scrape from LinkedIn is subject to LinkedIn's terms, so check before using it in production.
