"""
app.py - interview dashboard for the LLM vendor scorecard.

Run locally:   streamlit run app.py
It only reads the CSV files in this folder - no API calls, no cost, no API key needed.
"""

import os
import altair as alt
import pandas as pd
import streamlit as st
import yaml

st.set_page_config(page_title="LLM Vendor Scorecard", layout="wide")

SCORES_FILE = "scores_v2.csv" if os.path.exists("scores_v2.csv") else "scores.csv"
RISK_TASKS = {"T17", "T18", "T19", "T20"}
MAX_REAL_LATENCY = 600
# Paid list prices on OpenRouter, USD per 1M tokens (input, output), checked 2-3 Nov 2026
PRICES = {
    "nvidia/nemotron-3-ultra-550b-a55b:free": (0.50, 2.20),
    "liquid/lfm-2.5-2.6b:free": (0.35, 0.50),
    "anthropic/claude-sonnet-5.5": (2.00, 10.00),
}
# Fixed colours for the paid models on the cost chart (reference palette, slots 1-3)
CHART_COLOURS = ["#2a78d6", "#eb6834", "#1baf7a"]


@st.cache_data
def load_data():
    with open("config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    models = config["models"]
    ids = [m["id"] for m in models]
    tasks = pd.read_csv("tasks.csv", dtype=str).fillna("")
    results = pd.read_csv("results.csv", dtype=str).fillna("")
    scores = pd.read_csv(SCORES_FILE, dtype=str).fillna("")
    results = results[results["model_id"].isin(ids)].copy()
    scores = scores[scores["model_id"].isin(ids)].copy()
    for col in ["latency_s", "tokens_in", "tokens_out"]:
        results[col] = pd.to_numeric(results[col], errors="coerce")
    scores["score"] = pd.to_numeric(scores["score_pct"], errors="coerce")
    scores.loc[scores["method"].isin(["no_answer", "judge_error"]), "score"] = None
    return models, tasks, results, scores


def build_scorecard(models, results, scores, weights, tasks_per_year):
    n_tasks = results["task_id"].nunique()
    rows = []
    for m in models:
        r = results[results["model_id"] == m["id"]]
        s = scores[scores["model_id"] == m["id"]]
        ok = r[r["status"] == "ok"]
        business = s[~s["task_id"].isin(RISK_TASKS)]["score"].dropna()
        risk = s[s["task_id"].isin(RISK_TASKS)]["score"].dropna()
        latency = ok["latency_s"][ok["latency_s"] <= MAX_REAL_LATENCY].dropna()
        price = PRICES.get(m["id"])
        cost_task = None
        if price and ok["tokens_in"].notna().any():
            cost_task = (ok["tokens_in"].mean() * price[0] + ok["tokens_out"].mean() * price[1]) / 1e6
        rows.append({
            "Model": m["label"],
            "Quality %": business.mean() if len(business) else None,
            "Risk %": risk.mean() if len(risk) else None,
            "Availability %": 100 * (r["first_try_ok"] == "yes").sum() / n_tasks,
            "Median speed (s)": latency.median() if len(latency) else None,
            "Answered": f"{len(ok)}/{n_tasks}",
            "Cost per task ($)": cost_task,
            "Cost per year ($)": cost_task * tasks_per_year if cost_task is not None else None,
        })
    card = pd.DataFrame(rows)
    fastest = card["Median speed (s)"].min()
    card["Speed pts"] = 100 * fastest / card["Median speed (s)"]
    total = sum(weights.values()) or 1
    card["Overall"] = (
        card["Quality %"].fillna(0) * weights["quality"]
        + card["Risk %"].fillna(0) * weights["risk"]
        + card["Availability %"].fillna(0) * weights["availability"]
        + card["Speed pts"].fillna(0) * weights["speed"]
    ) / total
    card = card.sort_values("Overall", ascending=False).reset_index(drop=True)
    card.index = card.index + 1
    return card


models, tasks, results, scores = load_data()

# ---------------- Sidebar: priorities and scenario ----------------
st.sidebar.header("Client priorities")
st.sidebar.caption("Move the sliders to see how the ranking changes. Weights are relative.")
weights = {
    "quality": st.sidebar.slider("Quality", 0, 100, 40, 5),
    "risk": st.sidebar.slider("Risk & trust", 0, 100, 30, 5),
    "availability": st.sidebar.slider("Availability", 0, 100, 20, 5),
    "speed": st.sidebar.slider("Speed", 0, 100, 10, 5),
}
st.sidebar.header("Scale-up scenario")
users = st.sidebar.number_input("Users", 10, 100_000, 500, 50)
tasks_per_day = st.sidebar.number_input("Tasks per user per day", 1, 200, 10, 1)
days = st.sidebar.number_input("Working days per year", 1, 365, 220, 5)
tasks_per_year = users * tasks_per_day * days

card = build_scorecard(models, results, scores, weights, tasks_per_year)

# ---------------- Header and headline ----------------
st.title("LLM Vendor Scorecard")
st.caption(f"{len(models)} models · {results['task_id'].nunique()} consulting tasks · "
           f"answers checked against fixed checklists · scores from {SCORES_FILE}")

top = card.iloc[0]
paid = card[card["Cost per year ($)"].notna()]
close = paid[paid["Overall"] >= top["Overall"] - 10]
value = close.sort_values("Cost per year ($)").iloc[0] if len(close) else None

col1, col2, col3 = st.columns(3)
col1.metric("Highest overall score", top["Model"], f"{top['Overall']:.1f} points", delta_color="off")
if value is not None:
    col2.metric("Best value (within 10 points of the top)", value["Model"],
                f"${value['Cost per year ($)']:,.0f} per year", delta_color="off")
col3.metric("Tasks per year in scenario", f"{tasks_per_year:,}")

if value is not None and value["Model"] != top["Model"] and pd.notna(top["Cost per year ($)"]):
    ratio = top["Cost per year ($)"] / value["Cost per year ($)"]
    st.info(f"**{value['Model']}** scores {top['Overall'] - value['Overall']:.1f} points below "
            f"**{top['Model']}** at about **1/{ratio:.1f} of the cost** "
            f"(${value['Cost per year ($)']:,.0f} vs ${top['Cost per year ($)']:,.0f} per year).")

tab_card, tab_cost, tab_cat, tab_answers, tab_method = st.tabs(
    ["Scorecard", "Score vs cost", "By category", "Answers", "Method & limits"])

# ---------------- Scorecard ----------------
with tab_card:
    view = card[["Model", "Overall", "Quality %", "Risk %", "Availability %",
                 "Median speed (s)", "Answered", "Cost per task ($)", "Cost per year ($)"]]
    st.dataframe(
        view.style.format({
            "Overall": "{:.1f}", "Quality %": "{:.1f}", "Risk %": "{:.1f}",
            "Availability %": "{:.0f}", "Median speed (s)": "{:.1f}",
            "Cost per task ($)": lambda v: "free only" if pd.isna(v) else f"{v:.5f}",
            "Cost per year ($)": lambda v: "n/a" if pd.isna(v) else f"{v:,.0f}",
        }),
        use_container_width=True,
    )
    st.caption("Quality = 16 business tasks · Risk = 4 trust tasks (unknown answer, policy, privacy, "
               "false premise) · Availability = answered on the first try · Speed = median seconds. "
               "'Free only' = no paid version available.")

# ---------------- Score vs cost chart ----------------
with tab_cost:
    chart_data = card[card["Cost per year ($)"].notna()].copy()
    chart_data["Overall"] = chart_data["Overall"].round(1)
    chart_data["Cost per year ($)"] = chart_data["Cost per year ($)"].round(0)
    domain = chart_data["Model"].tolist()
    base = alt.Chart(chart_data).encode(
        x=alt.X("Cost per year ($):Q", title="Estimated cost per year (USD)",
                scale=alt.Scale(zero=True), axis=alt.Axis(format="$,.0f", grid=False)),
        y=alt.Y("Overall:Q", title="Overall score", scale=alt.Scale(domain=[50, 100]),
                axis=alt.Axis(gridOpacity=0.3)),
    )
    points = base.mark_circle(size=220, opacity=1, stroke="white", strokeWidth=2).encode(
        color=alt.Color("Model:N", scale=alt.Scale(domain=domain, range=CHART_COLOURS[:len(domain)]),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["Model", alt.Tooltip("Overall:Q", format=".1f"),
                 alt.Tooltip("Cost per year ($):Q", format="$,.0f"),
                 alt.Tooltip("Quality %:Q", format=".1f"), alt.Tooltip("Risk %:Q", format=".1f")],
    )
    labels = base.mark_text(align="left", dx=12, dy=-8, fontSize=13).encode(text="Model")
    st.altair_chart((points + labels).properties(height=420), use_container_width=True)
    free = card[card["Cost per year ($)"].isna()]
    if len(free):
        st.caption("Not shown (no paid version, so no cost): "
                   + ", ".join(f"{row['Model']} ({row['Overall']:.1f} pts, "
                               f"{row['Availability %']:.0f}% availability)"
                               for _, row in free.iterrows()))
    st.caption("Top-left is best: high score, low cost. Cost = real token counts × paid list price.")

# ---------------- By category ----------------
with tab_cat:
    by_cat = (scores.dropna(subset=["score"])
              .pivot_table(index="category", columns="model_label", values="score", aggfunc="mean"))
    order = [m["label"] for m in models if m["label"] in by_cat.columns]
    st.dataframe(by_cat[order].style.format("{:.1f}"), use_container_width=True)
    st.caption("Average score per task category (%), answered tasks only.")

# ---------------- Answers ----------------
with tab_answers:
    c1, c2 = st.columns(2)
    task_id = c1.selectbox("Task", [f"{t.id} - {t.category}: {t.prompt[:60]}..." for t in tasks.itertuples()])
    task_id = task_id.split(" - ")[0]
    model_label = c2.selectbox("Model", [m["label"] for m in models])
    task = tasks[tasks["id"] == task_id].iloc[0]
    res = results[(results["task_id"] == task_id) & (results["model_label"] == model_label)]
    sc = scores[(scores["task_id"] == task_id) & (scores["model_label"] == model_label)]

    left, right = st.columns(2)
    with left:
        st.markdown("**Instruction**")
        st.info(task["prompt"])
        with st.expander("Task input"):
            st.text(task["input_text"])
    with right:
        st.markdown("**Model's answer**")
        if res.empty or res.iloc[0]["status"] != "ok":
            st.warning("No answer: the model was unavailable for this task.")
        else:
            st.markdown(res.iloc[0]["response"])
        if not sc.empty:
            s = sc.iloc[0]
            st.markdown(f"**Score: {s['score_pct']}%** · {s['reason']}")
            if s.get("details"):
                for item in s["details"].split(" | "):
                    st.write(("✅ " if item.startswith("OK:") else "❌ ") + item.split(": ", 1)[-1])

# ---------------- Method & limits ----------------
with tab_method:
    st.markdown("""
**Method**
- 20 consulting tasks in 5 categories (Summarize, Analyze, Extract, Write, Risk), fictional Swiss/DACH companies.
- Same prompt for every model via OpenRouter. Up to 3 tries per task; availability = answered on the first try.
- Scoring: automatic checks for tasks with one right answer; an independent judge model (Google Gemini) checks
  every other answer against a **fixed checklist** per task, plus one format/length check.
- Judge calibrated against an expert review: agreement rose from **40%** (1-5 rating) to **63%** (checklist)
  to **88%** (strict checklist; 7 of 8 cases, 8 of 8 within 10 points).
- The ranking stayed the same across all three judge versions.

**Limitations**
- 20 tasks is a directional sample, not a statistical benchmark.
- Claude ran on a paid tier, the others on free tiers: part of the speed/availability gap may be the tier.
- Costs are estimates (real token counts × list prices); free-only models have no cost.
- Fictional inputs, English only. Accessed via OpenRouter, not direct vendor contracts or data-residency checks.
""")
