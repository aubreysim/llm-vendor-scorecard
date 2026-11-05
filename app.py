"""
app.py - interview dashboard for the LLM vendor scorecard (consulting style).

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
TEST_PERIOD = "Oct-Nov 2026"
# Paid list prices on OpenRouter, USD per 1M tokens (input, output), checked 2-3 Nov 2026
PRICES = {
    "nvidia/nemotron-3-ultra-550b-a55b:free": (0.50, 2.20),
    "liquid/lfm-2.5-2.6b:free": (0.35, 0.50),
    "anthropic/claude-sonnet-5.5": (2.00, 10.00),
}

# Short display names (the size class goes into a footnote)
SHORT_NAMES = {
    "anthropic/claude-sonnet-5.5": ("Claude Sonnet", "premium, paid"),
    "nvidia/nemotron-3-ultra-550b-a55b:free": ("NVIDIA Nemotron", "large"),
    "liquid/lfm-2.5-2.6b:free": ("Liquid LFM", "small"),
    "recursive/flint-v1.0:free": ("Recursive Flint", "mid-size, free only"),
    "xingchen-agi/xing4.0-29b-a4b:free": ("Xingchen", "mid-size, free only"),
}
FRACTIONS = {2: "half", 3: "a third", 4: "a quarter", 5: "a fifth", 6: "a sixth",
             7: "a seventh", 8: "an eighth", 9: "a ninth", 10: "a tenth"}


def short_name(model_id, label):
    if model_id in SHORT_NAMES:
        return SHORT_NAMES[model_id][0]
    return label.split("(")[-1].rstrip(")") if "(" in label else label


# Colours: one accent for emphasis, neutral grey for everything else
ACCENT = "#2a78d6"
NEUTRAL = "#b9b8b2"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e6e5e1"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]   # identity colours for max. 3 points on the scatter

# ---------------- Page styling ----------------
st.markdown(f"""
<style>
  #MainMenu, footer, [data-testid="stToolbar"] {{visibility: hidden;}}
  .block-container {{padding-top: 2rem; max-width: 1200px;}}
  .eyebrow {{font-size: 0.8rem; letter-spacing: 0.08em; text-transform: uppercase;
             color: {INK_2}; margin-bottom: 0.2rem;}}
  .action-title {{font-size: 1.9rem; font-weight: 700; line-height: 1.25; color: {INK};
                  margin: 0 0 0.4rem 0;}}
  .subtitle {{color: {INK_2}; font-size: 0.95rem; margin-bottom: 1.2rem;}}
  .exec-box {{border-left: 4px solid {ACCENT}; background: #f3f2ef; padding: 0.9rem 1.2rem;
              border-radius: 4px; margin-bottom: 1.2rem;}}
  .exec-box ul {{margin: 0.3rem 0 0 1rem; padding: 0;}}
  .exec-box li {{margin-bottom: 0.3rem;}}
  .kpi {{border: 1px solid {GRID}; border-radius: 6px; padding: 0.8rem 1rem; background: #ffffff;}}
  .kpi-label {{font-size: 0.78rem; color: {INK_2}; text-transform: uppercase; letter-spacing: 0.05em;}}
  .kpi-value {{font-size: 1.35rem; font-weight: 700; color: {INK}; margin-top: 0.15rem;}}
  .kpi-note {{font-size: 0.82rem; color: {INK_2};}}
  .exhibit-title {{font-weight: 700; font-size: 1.05rem; color: {INK}; margin: 0.4rem 0 0.1rem 0;}}
  .source {{font-size: 0.78rem; color: {INK_2}; margin-top: 0.3rem;}}
</style>
""", unsafe_allow_html=True)


def kpi(col, label, value, note=""):
    col.markdown(f'<div class="kpi"><div class="kpi-label">{label}</div>'
                 f'<div class="kpi-value">{value}</div><div class="kpi-note">{note}</div></div>',
                 unsafe_allow_html=True)


def exhibit(title):
    st.markdown(f'<div class="exhibit-title">{title}</div>', unsafe_allow_html=True)


def source(text):
    st.markdown(f'<div class="source">{text}</div>', unsafe_allow_html=True)


def style_chart(chart):
    return (chart.configure_view(strokeWidth=0)
            .configure_axis(labelColor=INK_2, titleColor=INK_2, domainColor=GRID,
                            tickColor=GRID, gridColor=GRID, labelFontSize=12, titleFontSize=12)
            .configure_legend(labelColor=INK_2, labelFontSize=12))


# ---------------- Data ----------------
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
    # short display names everywhere
    for m in models:
        m["name"] = short_name(m["id"], m["label"])
    names = {m["id"]: m["name"] for m in models}
    results["name"] = results["model_id"].map(names)
    scores["name"] = scores["model_id"].map(names)
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
            "Model": m["name"],
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

# ---------------- Sidebar ----------------
st.sidebar.markdown("### Client priorities")
st.sidebar.caption("Move the sliders to see how the ranking changes. Weights are relative.")
weights = {
    "quality": st.sidebar.slider("Quality", 0, 100, 40, 5),
    "risk": st.sidebar.slider("Risk & trust", 0, 100, 30, 5),
    "availability": st.sidebar.slider("Availability", 0, 100, 20, 5),
    "speed": st.sidebar.slider("Speed", 0, 100, 10, 5),
}
st.sidebar.markdown("### Scale-up scenario")
st.sidebar.caption("Estimate the annual cost for a client: enter how many people use the AI, "
                   "how many tasks each runs per day, and working days per year. "
                   "Annual cost = tasks per year × each model's cost per task.")
users = st.sidebar.number_input("Users", 10, 100_000, 500, 50)
tasks_per_day = st.sidebar.number_input("Tasks per user per day", 1, 200, 10, 1)
days = st.sidebar.number_input("Working days per year", 1, 365, 220, 5)
tasks_per_year = users * tasks_per_day * days

card = build_scorecard(models, results, scores, weights, tasks_per_year)
n_tasks = results["task_id"].nunique()

# ---------------- Key facts for the headline ----------------
top = card.iloc[0]
paid = card[card["Cost per year ($)"].notna()]
close = paid[paid["Overall"] >= top["Overall"] - 10]
value = close.sort_values("Cost per year ($)").iloc[0] if len(close) else top

leakers = scores[(scores["task_id"] == "T19") & (scores["score"] == 0)]["name"].tolist()
unreliable = card[card["Availability %"] < 50]["Model"].tolist()

if value["Model"] != top["Model"] and pd.notna(top["Cost per year ($)"]):
    ratio = top["Cost per year ($)"] / value["Cost per year ($)"]
    gap = top["Overall"] - value["Overall"]
    fraction = FRACTIONS.get(round(ratio), f"1/{ratio:.0f}")
    action_title = f"{value['Model']}: near-{top['Model']} results at {fraction} of the cost"
    rec = (f"<b>Recommend {value['Model']}</b> as the default: near-top scores at "
           f"${value['Cost per year ($)']:,.0f} per year vs ${top['Cost per year ($)']:,.0f} for "
           f"{top['Model']}. Use {top['Model']} where its edge matters most.")
else:
    action_title = f"{top['Model']} leads on the client's priorities"
    rec = f"<b>Recommend {top['Model']}</b>: highest overall score under the current priorities."

# ---------------- Header ----------------
st.markdown('<div class="eyebrow">AI vendor evaluation · consulting use cases</div>', unsafe_allow_html=True)
st.markdown(f'<div class="action-title">{action_title}</div>', unsafe_allow_html=True)
subtitle = (f"{len(models)} AI models tested on {n_tasks} consulting tasks "
            f"· answers checked against fixed checklists · {TEST_PERIOD}")
if value["Model"] != top["Model"] and pd.notna(top["Cost per year ($)"]):
    subtitle = (f"Within {gap:.0f} points of the top score for ${value['Cost per year ($)']:,.0f} instead of "
                f"${top['Cost per year ($)']:,.0f} a year · " + subtitle)
st.markdown(f'<div class="subtitle">{subtitle}</div>', unsafe_allow_html=True)

bullets = [rec]
if leakers:
    bullets.append(f"<b>Trust separates the vendors more than quality:</b> {len(leakers)} of {len(models)} "
                   f"models put salary, address or health data into a team summary "
                   f"({', '.join(leakers)}).")
if unreliable:
    bullets.append(f"<b>Free-only models are not business-ready:</b> {', '.join(unreliable)} answered "
                   f"under half of the tasks on the first try, with no paid service available.")
st.markdown('<div class="exec-box"><b>Executive summary</b><ul>'
            + "".join(f"<li>{b}</li>" for b in bullets) + "</ul></div>", unsafe_allow_html=True)

k1, k2, k3, k4 = st.columns(4)
kpi(k1, "Highest score", top["Model"], f"{top['Overall']:.1f} of 100 points")
kpi(k2, "Best value", value["Model"],
    f"${value['Cost per year ($)']:,.0f} per year" if pd.notna(value["Cost per year ($)"]) else "")
kpi(k3, "Scenario", f"{tasks_per_year/1e6:.1f}m tasks/yr", f"{users:,} users × {tasks_per_day}/day × {days} days")
kpi(k4, "Scoring reliability", "88%", "7 of 8 AI gradings matched a human check")
st.write("")

tab_card, tab_cost, tab_cat, tab_answers, tab_method = st.tabs(
    ["Scorecard", "Score vs cost", "By category", "Answers", "Method & limits"])

# ---------------- Scorecard ----------------
with tab_card:
    exhibit("Overall score by vendor, under the current client priorities")
    bars = alt.Chart(card.reset_index()).mark_bar(cornerRadiusEnd=4, height=22).encode(
        x=alt.X("Overall:Q", title="Overall score (0-100)", scale=alt.Scale(domain=[0, 100]),
                axis=alt.Axis(grid=True, tickCount=5)),
        y=alt.Y("Model:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220)),
        color=alt.condition(alt.datum.Model == value["Model"], alt.value(ACCENT), alt.value(NEUTRAL)),
        tooltip=["Model", alt.Tooltip("Overall:Q", format=".1f"), alt.Tooltip("Quality %:Q", format=".1f"),
                 alt.Tooltip("Risk %:Q", format=".1f"), alt.Tooltip("Availability %:Q", format=".0f")],
    )
    text = alt.Chart(card.reset_index()).mark_text(align="left", dx=6, color=INK, fontSize=12).encode(
        x="Overall:Q", y=alt.Y("Model:N", sort="-x"), text=alt.Text("Overall:Q", format=".1f"))
    st.altair_chart(style_chart((bars + text).properties(height=230)), use_container_width=True)
    source(f"Highlighted: recommended vendor (best value within 10 points of the top). "
           f"Weights: quality {weights['quality']}, risk {weights['risk']}, "
           f"availability {weights['availability']}, speed {weights['speed']}.")

    exhibit("Scorecard detail")
    table = card[["Model", "Overall", "Quality %", "Risk %", "Availability %", "Median speed (s)", "Answered"]].copy()
    table["Cost per task"] = card["Cost per task ($)"].apply(lambda v: "free only" if pd.isna(v) else f"${v:.4f}")
    table["Cost per year"] = card["Cost per year ($)"].apply(lambda v: "n/a" if pd.isna(v) else f"${v:,.0f}")
    pct = lambda label: st.column_config.ProgressColumn(label, min_value=0, max_value=100, format="%.0f")
    st.dataframe(
        table, use_container_width=True,
        column_config={
            "Overall": pct("Overall"), "Quality %": pct("Quality"), "Risk %": pct("Risk & trust"),
            "Availability %": pct("Availability"),
            "Median speed (s)": st.column_config.NumberColumn("Speed (s)", format="%.1f"),
        },
    )
    source("Quality: average score on 16 everyday consulting tasks (4 each: summarise, analyse, extract, write) "
           "· Risk & trust: 4 tasks (unknown answer, policy, privacy, false premise) "
           "· Availability: answered on the first try · Speed: median seconds · Cost: real token counts × "
           "paid list price. Source: own evaluation via OpenRouter, " + TEST_PERIOD + ".")
    source("Models: " + " · ".join(f"{m['name']} ({SHORT_NAMES.get(m['id'], ('', 'n/a'))[1]})"
                                    for m in models) + ".")

# ---------------- Score vs cost ----------------
with tab_cost:
    exhibit("What you get vs what you pay: score and annual cost side by side")
    data = card.reset_index().copy()
    data["Cost label"] = data["Cost per year ($)"].apply(
        lambda v: "free only - no paid service" if pd.isna(v) else f"${v:,.0f}")
    data["Cost bar"] = data["Cost per year ($)"].fillna(0)
    order = data["Model"].tolist()                       # same order in both panels (by score)
    highlight = alt.condition(alt.datum.Model == value["Model"], alt.value(ACCENT), alt.value(NEUTRAL))
    y = alt.Y("Model:N", sort=order, title=None, axis=alt.Axis(labelLimit=200))

    score_bars = alt.Chart(data).mark_bar(cornerRadiusEnd=4, height=22).encode(
        x=alt.X("Overall:Q", title="Overall score (0-100)", scale=alt.Scale(domain=[0, 110]),
                axis=alt.Axis(values=[0, 25, 50, 75, 100])),
        y=y, color=highlight,
        tooltip=["Model", alt.Tooltip("Overall:Q", format=".1f")],
    )
    score_text = alt.Chart(data).mark_text(align="left", dx=6, color=INK, fontSize=12).encode(
        x="Overall:Q", y=y, text=alt.Text("Overall:Q", format=".1f"))

    max_cost = data["Cost bar"].max() or 1
    cost_bars = alt.Chart(data).mark_bar(cornerRadiusEnd=4, height=22).encode(
        x=alt.X("Cost bar:Q", title="Estimated cost per year (USD)",
                scale=alt.Scale(domain=[0, max_cost * 1.45]), axis=alt.Axis(format="$,.0f", tickCount=4)),
        y=alt.Y("Model:N", sort=order, title=None, axis=alt.Axis(labels=False, ticks=False)),
        color=highlight,
        tooltip=["Model", alt.Tooltip("Cost label:N", title="Cost per year")],
    )
    cost_text = alt.Chart(data).mark_text(align="left", dx=6, color=INK, fontSize=12).encode(
        x="Cost bar:Q", y=alt.Y("Model:N", sort=order), text="Cost label:N")

    panel = alt.hconcat(
        (score_bars + score_text).properties(width=330, height=240, title="Overall score"),
        (cost_bars + cost_text).properties(width=330, height=240, title="Annual cost"),
        spacing=30,
    ).configure_title(anchor="start", fontSize=13, color=INK)
    st.altair_chart(style_chart(panel), use_container_width=False)

    if value["Model"] != top["Model"] and pd.notna(top["Cost per year ($)"]):
        st.markdown(
            f'<div class="exec-box"><b>So what:</b> {value["Model"]} gives up {gap:.1f} points to '
            f'{top["Model"]} but saves <b>${top["Cost per year ($)"] - value["Cost per year ($)"]:,.0f} '
            f'a year</b> ({ratio:.1f}× cheaper) in this scenario.</div>', unsafe_allow_html=True)
    source(f"Highlighted: recommended vendor. Scenario: {tasks_per_year:,} tasks per year. "
           "Free-only models have no paid service, so no cost and no service guarantee.")

# ---------------- By category ----------------
with tab_cat:
    exhibit("Average score by task category (%)")
    by_cat = (scores.dropna(subset=["score"])
              .pivot_table(index="category", columns="name", values="score", aggfunc="mean"))
    order = [m["name"] for m in models if m["name"] in by_cat.columns]
    st.dataframe(
        by_cat[order], use_container_width=True,
        column_config={c: st.column_config.ProgressColumn(c, min_value=0, max_value=100, format="%.0f")
                       for c in order},
    )
    source("Answered tasks only. Extract tasks are easy for all models; Risk and Write separate them most.")

# ---------------- Answers ----------------
with tab_answers:
    exhibit("Inspect any answer and how it was scored")
    c1, c2 = st.columns(2)
    task_choice = c1.selectbox("Task", [f"{t.id} - {t.category}: {t.prompt[:60]}..." for t in tasks.itertuples()])
    task_id = task_choice.split(" - ")[0]
    model_name = c2.selectbox("Model", [m["name"] for m in models])
    task = tasks[tasks["id"] == task_id].iloc[0]
    res = results[(results["task_id"] == task_id) & (results["name"] == model_name)]
    sc = scores[(scores["task_id"] == task_id) & (scores["name"] == model_name)]

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
    m1, m2 = st.columns(2)
    with m1:
        exhibit("Method")
        st.markdown("""
- **20 consulting tasks** in 5 categories (Summarize, Analyze, Extract, Write, Risk), fictional Swiss/DACH companies.
- **Same prompt for every model** via OpenRouter; up to 3 tries per task. Availability = answered on the first try.
- **Scoring:** automatic checks where there is one right answer; an independent judge model (Google Gemini)
  checks every other answer against a **fixed checklist**, plus one format/length check.
- **Calibration:** judge-expert agreement rose from **40%** (1-5 rating) to **63%** (checklist) to
  **88%** (strict checklist; 7 of 8 cases, 8 of 8 within 10 points), based on one expert reviewer.
- **Robustness:** the ranking stayed the same across all three judge versions.
""")
    with m2:
        exhibit("Limitations")
        st.markdown("""
- **Directional sample:** 20 tasks, not a statistical benchmark.
- **Reviewer bias:** the expert who checked the judge also designed the tasks, checklists and judge fixes,
  and reviewed only 8 cases. Agreement may partly reflect the judge being tuned to one person's view;
  an independent second reviewer is the next step.
- **Unequal tiers:** Claude ran on a paid tier, the others on free tiers; part of the speed and availability gap may be the tier.
- **Cost is estimated:** real token counts × list prices; free-only models have no cost.
- **Scope:** fictional inputs, English only; accessed via OpenRouter, not direct vendor contracts or data-residency checks.
- **Next step before a real decision:** pilot the top two vendors on paid tiers with real (secured) client data,
  and check contracts, service levels and Swiss data residency.
""")
