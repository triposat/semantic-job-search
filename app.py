"""Streamlit UI for the LinkedIn jobs search demo.

Run with:
  streamlit run app.py
"""

import streamlit as st

from lib import search

st.set_page_config(page_title="LinkedIn Jobs · LanceDB + Bright Data", layout="wide")

st.title("🔎 LinkedIn Jobs Search")
st.caption("Powered by **Bright Data** (scraping) · **Cohere** (embeddings + rerank) · **LanceDB** (vector store)")


with st.sidebar:
    st.header("Filters")
    mode = st.radio(
        "Retrieval mode",
        ["hybrid", "vector", "keyword"],
        format_func=lambda m: {
            "hybrid": "Hybrid (vector + FTS, reranked)",
            "vector": "Vector only (Cohere embeddings)",
            "keyword": "Keyword only (BM25)",
        }[m],
        help="Hybrid = best quality. Vector = pure semantic. Keyword = literal token match.",
    )
    seniority = st.selectbox(
        "Seniority",
        ["any", "Entry level", "Associate", "Mid-Senior level", "Director", "Internship", "Not Applicable"],
    )
    keyword_filter = st.selectbox(
        "Source search",
        ["any", "machine learning engineer", "python developer"],
    )
    min_salary = st.slider("Min salary ($/yr)", 0, 500_000, 0, step=10_000)
    limit = st.slider("Results", 5, 25, 10)


query = st.text_input(
    "Search jobs",
    placeholder="e.g. remote ML engineer at AI startup with computer vision experience",
)

example_cols = st.columns(4)
EXAMPLES = [
    "deep learning model training with GPUs",
    "backend engineer building distributed systems",
    "LLM and generative AI applications",
    "scrappy startup with equity",
]
for col, example in zip(example_cols, EXAMPLES):
    if col.button(example, use_container_width=True):
        query = example


def build_where() -> str | None:
    clauses = []
    if seniority != "any":
        clauses.append(f"seniority = '{seniority}'")
    if keyword_filter != "any":
        clauses.append(f"search_keyword = '{keyword_filter}'")
    if min_salary > 0:
        clauses.append(f"salary_min_annual >= {min_salary}")
    return " AND ".join(clauses) if clauses else None


if query:
    where = build_where()
    with st.spinner(f"Searching ({mode})..."):
        df = search(query, mode=mode, limit=limit, where=where)

    meta_bits = [f"**{len(df)}** results", f"mode: `{mode}`"]
    if where:
        meta_bits.append(f"filter: `{where}`")
    st.markdown(" · ".join(meta_bits))

    if df.empty:
        st.info("No matches. Try relaxing the filters or rephrasing the query.")
    else:
        # Escape $ so Streamlit's LaTeX math rendering doesn't kick in on currency strings.
        esc = lambda s: str(s).replace("$", "\\$") if s else ""
        for _, row in df.iterrows():
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(f"### [{esc(row['title'])}]({row['apply_url']})")
                    st.markdown(f"**{esc(row['company'])}** — {esc(row['location'])}")
                    badges = []
                    if row["seniority"]:
                        badges.append(f":blue-background[{esc(row['seniority'])}]")
                    if row["employment_type"]:
                        badges.append(f":gray-background[{esc(row['employment_type'])}]")
                    if row.get("salary_display"):
                        badges.append(f":green-background[{esc(row['salary_display'])}]")
                    if badges:
                        st.markdown(" ".join(badges))
                    snippet = row.get("description_snippet") or ""
                    if snippet:
                        st.caption(f"_{esc(snippet)}…_")
                with c2:
                    score_keys = ["_relevance_score", "_distance", "_score"]
                    for k in score_keys:
                        if k in row.index and row[k] is not None:
                            st.metric("score", f"{float(row[k]):.3f}")
                            break
                    posted = row["posted_date"][:10] if row["posted_date"] else "—"
                    st.caption(f"posted: {posted}")
else:
    st.info("Enter a query above or click an example to start.")
