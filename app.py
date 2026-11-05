"""
app.py - interview dashboard for the LLM vendor scorecard (consulting style).

Run locally:   streamlit run app.py
It only reads the CSV files in this folder - no API calls, no cost, no API key needed.
"""

import html
import os
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st
import yaml

st.set_page_config(page_title="LLM Vendor Scorecard", layout="wide", initial_sidebar_state="collapsed")

# ---------------- Settings ----------------
REPO_URL = "https://github.com/aubreysim/llm-vendor-scorecard"   # check this matches your GitHub repo
AUTHOR = "aubreysim"
SCORES_FILE = "scores_v2.csv" if os.path.exists("scores_v2.csv") else "scores.csv"
RISK_TASKS = {"T17", "T18", "T19", "T20"}
MAX_REAL_LATENCY = 600
TEST_PERIOD = "Oct-Nov 2026"
CALIBRATION = ("88%", "7 of 8 AI gradings matched a human check")
# Paid list prices on OpenRouter, USD per 1M tokens (input, output), checked 2-3 Nov 2026
PRICES = {
    "nvidia/nemotron-3-ultra-550b-a55b:free": (0.50, 2.20),
    "liquid/lfm-2.5-2.6b:free": (0.35, 0.50),
    "anthropic/claude-sonnet-5.5": (2.00, 10.00),
}
SHORT_NAMES = {
    "anthropic/claude-sonnet-5.5": ("Claude Sonnet", "premium, paid"),
    "nvidia/nemotron-3-ultra-550b-a55b:free": ("NVIDIA Nemotron", "large"),
    "liquid/lfm-2.5-2.6b:free": ("Liquid LFM", "small"),
    "recursive/flint-v1.0:free": ("Recursive Flint", "mid-size, free only"),
    "xingchen-agi/xing4.0-29b-a4b:free": ("Xingchen", "mid-size, free only"),
}
FRACTIONS = {2: "half", 3: "a third", 4: "a quarter", 5: "a fifth", 6: "a sixth",
             7: "a seventh", 8: "an eighth", 9: "a ninth", 10: "a tenth"}
DEFAULTS = {"w_quality": 40, "w_risk": 30, "w_availability": 20, "w_speed": 10,
            "users": 500, "tasks_per_day": 10, "days": 220, "threshold": 10}
URL_KEYS = {"w_quality": "q", "w_risk": "r", "w_availability": "a", "w_speed": "s",
            "users": "u", "tasks_per_day": "t", "days": "d", "threshold": "b"}
LIMITS = {"w_quality": (0, 100), "w_risk": (0, 100), "w_availability": (0, 100), "w_speed": (0, 100),
          "users": (10, 100_000), "tasks_per_day": (1, 200), "days": (1, 365), "threshold": (0, 30)}
HELP = {
    "quality": "Average share of required checklist points covered on 16 everyday consulting tasks "
               "(4 each: summarise, analyse, extract, write).",
    "risk": "Average score on 4 trust tasks: admitting an answer isn't in the document, applying a policy, "
            "keeping personal data out, and correcting a false premise.",
    "availability": "Share of the 20 tasks the model answered on the first try (no 'busy' or 'down' errors).",
    "speed": "Median seconds per answer. In the overall score, the fastest model gets 100 speed points.",
    "cost": "Average tokens per task × the paid list price per token, then × tasks per year in the scenario.",
    "overall": "Weighted average of Quality, Risk, Availability and Speed points, using your priority mix.",
    "reliability": "How far the AI grader can be trusted: in 7 of 8 spot checks, a human reviewer agreed "
                   "with its score (8 of 8 within 10 points).",
}

# Colours: one accent for emphasis, neutral grey for the rest (text greys pass 4.5:1 contrast)
ACCENT = "#2a78d6"
NEUTRAL = "#b9b8b2"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e6e5e1"
WARN_BG = "#f9eeda"

# ---------------- Page styling ----------------
st.markdown(f"""
<style>
  #MainMenu, footer, [data-testid="stToolbar"], header[data-testid="stHeader"] {{display: none;}}
  [data-testid="stSidebarCollapsedControl"] {{display: none;}}
  .block-container {{padding-top: 1.6rem; max-width: 1200px;}}
  .eyebrow {{font-size: 0.8rem; letter-spacing: 0.08em; text-transform: uppercase; color: {INK_2};
             margin-bottom: 0.2rem;}}
  .action-title {{font-size: 1.9rem; font-weight: 700; line-height: 1.25; color: {INK}; margin: 0 0 0.4rem 0;}}
  .subtitle {{color: {INK_2}; font-size: 0.95rem; margin-bottom: 0.6rem;}}
  .why {{font-size: 0.95rem; color: {INK}; margin-bottom: 1rem;}}
  .exec-box {{border-left: 4px solid {ACCENT}; background: #f3f2ef; padding: 0.9rem 1.2rem;
              border-radius: 4px; margin-bottom: 0.8rem;}}
  .exec-box ul {{margin: 0.3rem 0 0 1rem; padding: 0;}}
  .exec-box li {{margin-bottom: 0.3rem;}}
  .next-box {{border-left: 4px solid {INK_2}; background: #ffffff; border: 1px solid {GRID};
              border-left-width: 4px; padding: 0.7rem 1.1rem; border-radius: 4px; margin-bottom: 1rem;}}
  .warn-box {{background: {WARN_BG}; padding: 0.6rem 0.9rem; border-radius: 4px; font-size: 0.88rem;
              color: {INK}; margin: 0.4rem 0 0.8rem 0;}}
  .kpi {{border: 1px solid {GRID}; border-radius: 6px; padding: 0.8rem 1rem; background: #ffffff;}}
  .kpi-label {{font-size: 0.78rem; color: {INK_2}; text-transform: uppercase; letter-spacing: 0.05em;}}
  .kpi-value {{font-size: 1.3rem; font-weight: 700; color: {INK}; margin-top: 0.15rem;}}
  .kpi-note {{font-size: 0.82rem; color: {INK_2};}}
  .section {{font-size: 1.25rem; font-weight: 700; color: {INK}; margin: 1.2rem 0 0.2rem 0;}}
  .exhibit-title {{font-weight: 700; font-size: 1.05rem; color: {INK}; margin: 0.4rem 0 0.1rem 0;}}
  .source {{font-size: 0.8rem; color: {INK_2}; margin-top: 0.3rem;}}
  .footer {{font-size: 0.82rem; color: {INK_2}; border-top: 1px solid {GRID}; margin-top: 2rem;
            padding-top: 0.8rem;}}
  /* keep the tab bar visible while scrolling */
  .stTabs [data-baseweb="tab-list"] {{position: sticky; top: 0; z-index: 50; background: #fcfcfb;
                                      padding-top: 0.3rem;}}
  /* settings box: looks like a button so it is obviously clickable */
  .st-key-settings_box [data-testid="stExpander"] details {{border: 2px solid {ACCENT}; border-radius: 8px;
                                                           background: #f3f8fe;}}
  .st-key-settings_box [data-testid="stExpander"] summary {{font-weight: 600; color: {INK}; min-height: 44px;}}
  .st-key-settings_box [data-testid="stExpander"] summary:hover {{background: #e7f1fb;}}
  /* section picker: stays at the top while scrolling */
  .st-key-nav {{position: sticky; top: 0; z-index: 60; background: #fcfcfb; padding: 0.3rem 0;}}
  .st-key-nav button {{min-height: 44px;}}
  @media (max-width: 1024px) {{
    .block-container {{padding-left: 1.2rem; padding-right: 1.2rem;}}
    .action-title {{font-size: 1.6rem;}}
  }}
  /* phones: tabs wrap onto several lines instead of needing a sideways swipe */
  @media (max-width: 640px) {{
    .stTabs [data-baseweb="tab-list"] {{flex-wrap: wrap; row-gap: 0.3rem; column-gap: 0.3rem;
                                        overflow-x: visible;}}
    .stTabs [data-baseweb="tab"] {{flex: 1 1 auto; min-height: 44px; padding: 0 0.6rem;
                                   border: 1px solid {GRID}; border-radius: 6px;}}
    .stTabs [data-baseweb="tab"][aria-selected="true"] {{background: #e7f1fb; border-color: {ACCENT};}}
    .stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] {{display: none;}}
  }}
  /* touch screens: bigger targets for help icons, number steppers and buttons (at least 44px) */
  @media (pointer: coarse) {{
    [data-testid="stTooltipHoverTarget"], [data-testid="stTooltipIcon"] {{min-width: 44px; min-height: 44px;
        display: inline-flex; align-items: center; justify-content: center;}}
    [data-testid="stNumberInputStepDown"], [data-testid="stNumberInputStepUp"] {{min-width: 44px; min-height: 44px;}}
    .stButton button, .stDownloadButton button {{min-height: 44px;}}
    [data-testid="stExpander"] summary {{min-height: 44px;}}
  }}
  @media (max-width: 640px) {{
    .block-container {{padding-top: 1rem; padding-left: 1rem; padding-right: 1rem;}}
    .action-title {{font-size: 1.35rem;}}
    .subtitle, .why {{font-size: 0.88rem;}}
    .kpi {{margin-bottom: 0.6rem;}}
    .exec-box, .next-box {{padding: 0.8rem 0.9rem;}}
  }}
</style>
""", unsafe_allow_html=True)


def kpi(col, label, value, note="", tip=""):
    tip_attr = f' title="{html.escape(tip)}"' if tip else ""
    info = " ⓘ" if tip else ""
    col.markdown(f'<div class="kpi"{tip_attr}><div class="kpi-label">{label}{info}</div>'
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


def short_name(model_id, label):
    if model_id in SHORT_NAMES:
        return SHORT_NAMES[model_id][0]
    return label.split("(")[-1].rstrip(")") if "(" in label else label


def money(v):
    return "free only ⚠" if pd.isna(v) else f"${v:,.0f}"


def fmt(v, pattern="{:.1f}"):
    return "n/a" if v is None or pd.isna(v) else pattern.format(v)


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
    for m in models:
        m["name"] = short_name(m["id"], m["label"])
        m["free_only"] = m["id"] not in PRICES
    names = {m["id"]: m["name"] for m in models}
    results["name"] = results["model_id"].map(names)
    scores["name"] = scores["model_id"].map(names)
    stamps = pd.to_datetime(pd.concat([results["timestamp"], scores["timestamp"]]), errors="coerce")
    updated = stamps.max().strftime("%d %b %Y") if stamps.notna().any() else TEST_PERIOD
    return models, tasks, results, scores, updated


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
            "Free only": m["free_only"],
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
    return card.sort_values("Overall", ascending=False).reset_index(drop=True)


# ---------------- Settings from the link (shareable scenarios) ----------------
params = st.query_params
if "knockout" not in st.session_state:
    st.session_state["knockout"] = params.get("k", "1") != "0"
for key, default in DEFAULTS.items():
    if key not in st.session_state:
        try:
            low, high = LIMITS[key]
            st.session_state[key] = min(max(int(params.get(URL_KEYS[key], default)), low), high)
        except (ValueError, TypeError):
            st.session_state[key] = default


def reset_defaults():
    for key, default in DEFAULTS.items():
        st.session_state[key] = default
    st.session_state["knockout"] = True


models, tasks, results, scores, last_updated = load_data()
n_tasks = results["task_id"].nunique()

# ---------------- Page areas (shown in this order) ----------------
header_area = st.container()
results_heading = st.container()
controls_area = st.container()

# ---------------- Controls ----------------
# The settings box title shows the current settings, so they are always visible without opening it
_ss = st.session_state
_total = (_ss.w_quality + _ss.w_risk + _ss.w_availability + _ss.w_speed) or 1
settings_label = (
    f"⚙️  Settings: Quality {100 * _ss.w_quality / _total:.0f}% · Risk {100 * _ss.w_risk / _total:.0f}% · "
    f"Availability {100 * _ss.w_availability / _total:.0f}% · Speed {100 * _ss.w_speed / _total:.0f}% · "
    f"{_ss.users * _ss.tasks_per_day * _ss.days:,} tasks/yr · threshold {_ss.threshold} pts · "
    f"knock-out {'on' if _ss.knockout else 'off'}  (tap to change)"
)

with controls_area:
    st.caption("👇 Try it: change the client's priorities or company size and watch the recommendation update.")
    settings_box = st.container(key="settings_box")
with settings_box:
    with st.expander(settings_label, expanded=False):
        p_col, s_col = st.columns(2)
        with p_col:
            st.markdown("**Client priorities**")
            st.caption("Weights are relative: they are converted to percentages automatically.")
            st.slider("Quality", 0, 100, step=5, key="w_quality", help=HELP["quality"])
            st.slider("Risk & trust", 0, 100, step=5, key="w_risk", help=HELP["risk"])
            st.slider("Availability", 0, 100, step=5, key="w_availability", help=HELP["availability"])
            st.slider("Speed", 0, 100, step=5, key="w_speed", help=HELP["speed"])
        with s_col:
            st.markdown("**Scale-up scenario**")
            st.caption("How many people use the AI, how many tasks each runs per day, and working days "
                       "per year. Annual cost = tasks per year × each model's cost per task.")
            st.number_input("Users", 10, 100_000, step=50, key="users")
            st.number_input("Tasks per user per day", 1, 200, step=1, key="tasks_per_day")
            st.number_input("Working days per year", 1, 365, step=5, key="days")
            st.slider("Best-value threshold (points below the top score)", 0, 30, step=1, key="threshold",
                      help="The recommended vendor is the cheapest paid model scoring within this many "
                           "points of the highest overall score.")
            st.checkbox("Knock-out: never recommend a model that leaked personal data", key="knockout",
                        help="Data protection is a must-have, not something to trade against cost. Models "
                             "that put salary, address or health data into the team summary (task T19) "
                             "are excluded from the recommendation.")
        st.button("↺  Reset to defaults", on_click=reset_defaults)

weights = {"quality": st.session_state.w_quality, "risk": st.session_state.w_risk,
           "availability": st.session_state.w_availability, "speed": st.session_state.w_speed}
users, tasks_per_day, days = st.session_state.users, st.session_state.tasks_per_day, st.session_state.days
threshold = st.session_state.threshold
tasks_per_year = users * tasks_per_day * days

# keep the current settings in the page address, so the link can be bookmarked or shared
for key in DEFAULTS:
    st.query_params[URL_KEYS[key]] = str(st.session_state[key])
st.query_params["k"] = "1" if st.session_state.knockout else "0"
knockout = st.session_state.knockout

with st.spinner("Updating…"):
    card = build_scorecard(models, results, scores, weights, tasks_per_year)

# ---------------- Key facts ----------------
leakers = scores[(scores["task_id"] == "T19") & (scores["score"] == 0)]["name"].tolist()
top = card.iloc[0]                                   # highest score, may be a free-only model
paid = card[(~card["Free only"]) & card["Cost per year ($)"].notna()]
if knockout:
    paid = paid[~paid["Model"].isin(leakers)]        # data protection is a must-have
best = paid.iloc[0] if len(paid) else top            # highest-scoring business-ready (paid) model
close = paid[paid["Overall"] >= top["Overall"] - threshold]
value = close.sort_values("Cost per year ($)").iloc[0] if len(close) else best   # recommended vendor
different = value["Model"] != best["Model"] and pd.notna(best["Cost per year ($)"])
top_note = (f" (The highest raw score, {top['Model']}, is free only with no service guarantee.)"
            if top["Free only"] else "")
total_w = sum(weights.values()) or 1
mix = " · ".join(f"{k.capitalize()} {100 * v / total_w:.0f}%" for k, v in weights.items())
free_only = card[card["Free only"]]["Model"].tolist()

if different:
    ratio = best["Cost per year ($)"] / value["Cost per year ($)"]
    gap = best["Overall"] - value["Overall"]
    saving = best["Cost per year ($)"] - value["Cost per year ($)"]
    fraction = FRACTIONS.get(round(ratio), f"1/{ratio:.0f}")
    action_title = f"{value['Model']}: near-{best['Model']} results at {fraction} of the cost"
    why = (f"<b>Why {value['Model']}:</b> it scores within {gap:.1f} points of {best['Model']} "
           f"(the best-value threshold is {threshold}) - quality {fmt(value['Quality %'])}% vs "
           f"{fmt(best['Quality %'])}%, risk {fmt(value['Risk %'], '{:.0f}')}% vs {fmt(best['Risk %'], '{:.0f}')}%, "
           f"speed {fmt(value['Median speed (s)'])}s vs {fmt(best['Median speed (s)'])}s - "
           f"and costs {ratio:.1f}× less.{top_note}")
    rec = (f"<b>Recommend {value['Model']}</b> as the default vendor; use {best['Model']} "
           f"where its edge matters most.")
else:
    action_title = f"{value['Model']}: the best fit for these client priorities"
    why = (f"<b>Why {value['Model']}:</b> highest-scoring business-ready model ({value['Overall']:.1f} points) "
           f"and no cheaper paid model within {threshold} points.{top_note}")
    rec = f"<b>Recommend {value['Model']}</b> under the current priorities."

# ---------------- Header ----------------
with header_area:
    st.markdown('<div class="eyebrow">AI vendor evaluation · consulting use cases</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="action-title">{action_title}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="subtitle">{len(models)} AI models tested on {n_tasks} consulting tasks · '
                f'answers checked against fixed checklists · priority mix: {mix}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="why">{why}</div>', unsafe_allow_html=True)

    with st.expander("ℹ️  How to use this scorecard", expanded=False):
        st.markdown(f"""
- **Scores (0-100):** *Quality* = everyday consulting work · *Risk & trust* = safe to rely on ·
  *Availability* = answered on the first try · *Overall* = weighted mix of all four (speed included).
- **Priorities:** open **⚙️ Adjust client priorities** below to change what matters to the client;
  the ranking, headline and recommendation update instantly. *Reset to defaults* brings everything back.
- **Best value:** the recommended vendor is the **cheapest paid model within {threshold} points** of the top
  score, a common way to avoid paying a premium for a marginal difference.
- **Knock-out rule:** models that leaked personal data in the privacy test are never recommended,
  however cheap (you can switch this off under ⚙️ to see the pure trade-off).
- **Free-only models (⚠):** no paid version exists, so there is **no service guarantee** and no cost estimate.
- **Share a scenario:** the page address updates with your settings; copy it from the browser to share.
""")

    bullets = [rec]
    if leakers:
        bullets.append(f"<b>Trust separates the vendors more than quality:</b> {len(leakers)} of {len(models)} "
                       f"models put salary, address or health data into a team summary "
                       f"({', '.join(leakers)}).")
    if free_only:
        bullets.append(f"<b>Free-only models are not business-ready:</b> {', '.join(free_only)} have no paid "
                       f"service, so no availability guarantee.")
    st.markdown('<div class="exec-box"><b>Executive summary</b><ul>'
                + "".join(f"<li>{b}</li>" for b in bullets) + "</ul></div>", unsafe_allow_html=True)
    st.markdown(f'<div class="next-box"><b>Recommended next step:</b> pilot {value["Model"]}'
                + (f" and {best['Model']}" if different else "")
                + " on paid tiers with real (secured) client data, and check contracts, service levels "
                  "and Swiss data residency before deciding.</div>", unsafe_allow_html=True)

    k1, k2, k3, k4 = st.columns(4)
    kpi(k1, "Highest score", top["Model"] + (" ⚠" if top["Free only"] else ""),
        f"{top['Overall']:.1f} of 100 points" + (" · free only" if top["Free only"] else ""), HELP["overall"])
    kpi(k2, "Best value", value["Model"],
        f"${value['Cost per year ($)']:,.0f} per year" if pd.notna(value["Cost per year ($)"]) else "",
        f"Cheapest paid model within {threshold} points of the top score.")
    if different:
        kpi(k3, "Annual saving", f"${saving:,.0f}", f"vs {best['Model']}, {tasks_per_year:,} tasks/yr", HELP["cost"])
    else:
        kpi(k3, "Tasks per year", f"{tasks_per_year:,}", f"{users:,} users × {tasks_per_day}/day × {days} days",
            HELP["cost"])
    kpi(k4, "Scoring reliability", CALIBRATION[0], CALIBRATION[1], HELP["reliability"])
    # Tap-friendly definitions (hover tooltips don't work on phones and tablets)
    with st.expander("ⓘ  What do these numbers mean?", expanded=False):
        st.markdown(f"""
- **Overall:** {HELP['overall']}
- **Quality:** {HELP['quality']}
- **Risk & trust:** {HELP['risk']}
- **Availability:** {HELP['availability']}
- **Speed:** {HELP['speed']}
- **Cost:** {HELP['cost']}
- **Scoring reliability:** {HELP['reliability']}
""")

# ---------------- Results ----------------
with results_heading:
    st.markdown('<div class="section">Explore the results</div>', unsafe_allow_html=True)

VIEWS = ["Comparison", "Score vs cost", "By category", "Answers", "Method & limits"]
with st.container(key="nav"):
    if hasattr(st, "segmented_control"):        # tap-friendly buttons that wrap on small screens
        view = st.segmented_control("Section", VIEWS, default=VIEWS[0], key="view",
                                    label_visibility="collapsed")
    else:                                        # fallback for older Streamlit versions
        view = st.radio("Section", VIEWS, horizontal=True, key="view", label_visibility="collapsed")
view = view or VIEWS[0]                          # tapping the selected button again clears it


def status(row):
    if row["Model"] == value["Model"]:
        return "★ Recommended"
    if knockout and row["Model"] in leakers and not row["Free only"]:
        return "✕ Knocked out: leaked personal data"
    if row["Free only"]:
        return "⚠ Free only, no guarantee" + (" · top score" if row["Model"] == top["Model"] else "")
    if row["Model"] == top["Model"]:
        return "Top score"
    if row["Model"] == best["Model"]:
        return "Best paid alternative"
    return ""


# ---------------- Comparison ----------------
if view == "Comparison":
    exhibit("All vendors side by side (click a column header to sort)")
    table = card.copy()
    table["Status"] = table.apply(status, axis=1)
    table["Cost per year"] = table["Cost per year ($)"].apply(money)
    table["Cost per task"] = table["Cost per task ($)"].apply(lambda v: "free only ⚠" if pd.isna(v) else f"${v:.4f}")
    table = table[["Status", "Model", "Overall", "Quality %", "Risk %", "Availability %",
                   "Median speed (s)", "Cost per year", "Cost per task", "Answered"]]
    pct = lambda label, tip: st.column_config.ProgressColumn(label, min_value=0, max_value=100,
                                                              format="%.0f", help=tip)
    st.dataframe(
        table, use_container_width=True, hide_index=True,
        column_config={
            "Overall": pct("Overall", HELP["overall"]),
            "Quality %": pct("Quality", HELP["quality"]),
            "Risk %": pct("Risk & trust", HELP["risk"]),
            "Availability %": pct("Availability", HELP["availability"]),
            "Median speed (s)": st.column_config.NumberColumn("Speed (s)", format="%.1f", help=HELP["speed"]),
            "Cost per year": st.column_config.TextColumn("Cost / year", help=HELP["cost"]),
            "Cost per task": st.column_config.TextColumn("Cost / task", help=HELP["cost"]),
            "Answered": st.column_config.TextColumn("Answered", help="Tasks answered in the end, after retries."),
        },
    )
    if free_only:
        st.markdown(f'<div class="warn-box">⚠ <b>{", ".join(free_only)}</b>: free-only models with no paid '
                    f'service, so no availability guarantee and no cost estimate. Not suitable for client work.</div>',
                    unsafe_allow_html=True)

    exhibit("Overall score under the current priorities")
    bars = alt.Chart(card).mark_bar(cornerRadiusEnd=4, height=22).encode(
        x=alt.X("Overall:Q", title="Overall score (0-100)", scale=alt.Scale(domain=[0, 105]),
                axis=alt.Axis(values=[0, 25, 50, 75, 100])),
        y=alt.Y("Model:N", sort="-x", title=None, axis=alt.Axis(labelLimit=200)),
        color=alt.condition(alt.datum.Model == value["Model"], alt.value(ACCENT), alt.value(NEUTRAL)),
        tooltip=["Model", alt.Tooltip("Overall:Q", format=".1f"), alt.Tooltip("Quality %:Q", format=".1f"),
                 alt.Tooltip("Risk %:Q", format=".1f"), alt.Tooltip("Availability %:Q", format=".0f")],
    )
    text = alt.Chart(card).mark_text(align="left", dx=6, color=INK, fontSize=12).encode(
        x="Overall:Q", y=alt.Y("Model:N", sort="-x"), text=alt.Text("Overall:Q", format=".1f"))
    st.altair_chart(style_chart((bars + text).properties(height=230)), use_container_width=True)
    source("Blue: recommended vendor. Models: " + " · ".join(
        f"{m['name']} ({SHORT_NAMES.get(m['id'], ('', 'n/a'))[1]})" for m in models)
        + f". Source: own evaluation via OpenRouter, {TEST_PERIOD}.")

# ---------------- Score vs cost ----------------
if view == "Score vs cost":
    exhibit("What you get vs what you pay")
    data = card.copy()
    data["Cost label"] = data["Cost per year ($)"].apply(lambda v: "free only - no paid service ⚠" if pd.isna(v)
                                                         else f"${v:,.0f}")
    data["Cost bar"] = data["Cost per year ($)"].fillna(0)
    order = data["Model"].tolist()
    highlight = alt.condition(alt.datum.Model == value["Model"], alt.value(ACCENT), alt.value(NEUTRAL))
    y = alt.Y("Model:N", sort=order, title=None, axis=alt.Axis(labelLimit=200))
    score_chart = (alt.Chart(data).mark_bar(cornerRadiusEnd=4, height=22).encode(
        x=alt.X("Overall:Q", title="Overall score (0-100)", scale=alt.Scale(domain=[0, 110]),
                axis=alt.Axis(values=[0, 25, 50, 75, 100])),
        y=y, color=highlight, tooltip=["Model", alt.Tooltip("Overall:Q", format=".1f")])
        + alt.Chart(data).mark_text(align="left", dx=6, color=INK, fontSize=12).encode(
            x="Overall:Q", y=y, text=alt.Text("Overall:Q", format=".1f")))
    max_cost = data["Cost bar"].max() or 1
    cost_chart = (alt.Chart(data).mark_bar(cornerRadiusEnd=4, height=22).encode(
        x=alt.X("Cost bar:Q", title="Estimated cost per year (USD)",
                scale=alt.Scale(domain=[0, max_cost * 1.6]), axis=alt.Axis(format="$,.0f", tickCount=4)),
        y=y, color=highlight, tooltip=["Model", alt.Tooltip("Cost label:N", title="Cost per year")])
        + alt.Chart(data).mark_text(align="left", dx=6, color=INK, fontSize=12).encode(
            x="Cost bar:Q", y=y, text="Cost label:N"))
    c_left, c_right = st.columns(2)
    with c_left:
        st.markdown("**Overall score**")
        st.altair_chart(style_chart(score_chart.properties(height=240)), use_container_width=True)
    with c_right:
        st.markdown("**Annual cost**")
        st.altair_chart(style_chart(cost_chart.properties(height=240)), use_container_width=True)
    if different:
        st.markdown(f'<div class="exec-box"><b>So what:</b> {value["Model"]} gives up {gap:.1f} points to '
                    f'{best["Model"]} but saves <b>${saving:,.0f} a year</b> ({ratio:.1f}× cheaper) '
                    f'for {tasks_per_year:,} tasks.</div>', unsafe_allow_html=True)
    source("Blue: recommended vendor. ⚠ Free-only models have no paid service, so no cost and no service guarantee.")

# ---------------- By category ----------------
if view == "By category":
    exhibit("Average score by task category (%)")
    by_cat = (scores.dropna(subset=["score"])
              .pivot_table(index="category", columns="name", values="score", aggfunc="mean"))
    cat_order = [m["name"] for m in models if m["name"] in by_cat.columns]
    st.dataframe(
        by_cat[cat_order], use_container_width=True,
        column_config={c: st.column_config.ProgressColumn(c + (" ⚠" if c in free_only else ""),
                                                          min_value=0, max_value=100, format="%.0f")
                       for c in cat_order},
    )
    source("Answered tasks only. Extract tasks are easy for every model; Risk and Write separate them most. "
           "⚠ = free only, no service guarantee.")

# ---------------- Answers ----------------
if view == "Answers":
    exhibit("Compare two models on the same task")
    f1, f2 = st.columns([1, 2])
    category = f1.selectbox("Category", ["All"] + sorted(tasks["category"].unique().tolist()))
    pool = tasks if category == "All" else tasks[tasks["category"] == category]
    task_choice = f2.selectbox("Task", [f"{t.id} - {t.category}: {t.prompt[:70]}" for t in pool.itertuples()])
    task_id = task_choice.split(" - ")[0]
    task = tasks[tasks["id"] == task_id].iloc[0]

    st.markdown("**Instruction**")
    st.info(task["prompt"])
    with st.expander("Task input (what every model was given)", expanded=True):
        st.text(task["input_text"])

    names = [m["name"] for m in models]
    m1, m2 = st.columns(2)
    model_a = m1.selectbox("Model A", names, index=names.index(value["Model"]))
    other = best["Model"] if different else next((n for n in names if n != value["Model"]), value["Model"])
    model_b = m2.selectbox("Model B", names, index=names.index(other))

    for col, model_name in ((m1, model_a), (m2, model_b)):
        res = results[(results["task_id"] == task_id) & (results["name"] == model_name)]
        sc = scores[(scores["task_id"] == task_id) & (scores["name"] == model_name)]
        with col:
            if not sc.empty and pd.notna(sc.iloc[0]["score"]):
                s = sc.iloc[0]
                st.markdown(f"**Score: {s['score']:.0f}%**")
                st.progress(int(s["score"]) / 100)
                st.caption(s["reason"])
                if s.get("details"):
                    for item in s["details"].split(" | "):
                        ok_flag = item.startswith("OK:")
                        st.markdown(("✅ " if ok_flag else "❌ ") + item.split(": ", 1)[-1])
            if res.empty or res.iloc[0]["status"] != "ok":
                st.warning("No answer: the model was unavailable for this task.")
            else:
                with st.expander("Model's answer", expanded=True):
                    st.markdown(res.iloc[0]["response"])

# ---------------- Method & limits ----------------
if view == "Method & limits":
    l, r = st.columns(2)
    with l:
        exhibit("Method")
        st.markdown(f"""
- **20 consulting tasks** in 5 categories (Summarise, Analyse, Extract, Write, Risk), fictional Swiss/DACH companies.
- **Same prompt for every model** via OpenRouter; up to 3 tries per task. Availability = answered on the first try.
- **Scoring:** automatic checks where there is one right answer; an independent judge model (Google Gemini)
  checks every other answer against a **fixed checklist**, plus one format/length check.
- **Calibration:** grader-human agreement rose from **40%** (1-5 rating) to **63%** (checklist) to
  **88%** (strict checklist; 7 of 8 cases, 8 of 8 within 10 points), based on one expert reviewer.
- **Robustness:** the ranking stayed the same across all three grading versions.
- **Cost:** {HELP['cost']}
""")
    with r:
        exhibit("Limitations")
        st.markdown("""
- **Directional sample:** 20 tasks, not a statistical benchmark.
- **Reviewer bias:** the expert who checked the grader also designed the tasks, checklists and grading fixes,
  and reviewed only 8 cases; an independent second reviewer is the next step.
- **Unequal tiers:** Claude ran on a paid tier, the others on free tiers; part of the speed and availability
  gap may be the tier.
- **Cost is estimated:** real token counts × list prices; free-only models have no cost.
- **Scope:** fictional inputs, English only; accessed via OpenRouter, not direct vendor contracts or
  data-residency checks.
""")

# ---------------- Export ----------------
st.markdown('<div class="section">Export</div>', unsafe_allow_html=True)
export = card.copy()
export.insert(0, "Rank", range(1, len(export) + 1))
export["Status"] = export.apply(status, axis=1)
export["Weights"] = mix
export["Tasks per year"] = tasks_per_year
csv_bytes = export.round(4).to_csv(index=False).encode("utf-8")

summary_rows = "".join(
    f"<tr><td>{i + 1}</td><td>{html.escape(row['Model'])}</td><td>{status(row)}</td>"
    f"<td>{fmt(row['Overall'])}</td><td>{fmt(row['Quality %'])}</td><td>{fmt(row['Risk %'], '{:.0f}')}</td>"
    f"<td>{fmt(row['Availability %'], '{:.0f}')}</td><td>{fmt(row['Median speed (s)'])}</td>"
    f"<td>{money(row['Cost per year ($)'])}</td></tr>"
    for i, row in card.iterrows())
summary_html = f"""<!doctype html><html><head><meta charset="utf-8"><title>LLM Vendor Scorecard</title>
<style>body{{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#0b0b0b;max-width:900px;
margin:2rem auto;padding:0 1rem}} h1{{font-size:1.5rem}} table{{border-collapse:collapse;width:100%;font-size:.9rem}}
th,td{{border-bottom:1px solid #e6e5e1;padding:.4rem;text-align:left}} .muted{{color:#52514e;font-size:.85rem}}
.box{{border-left:4px solid #2a78d6;background:#f3f2ef;padding:.7rem 1rem;margin:1rem 0}}</style></head><body>
<p class="muted">AI vendor evaluation · consulting use cases · data as of {last_updated}</p>
<h1>{html.escape(action_title)}</h1>
<p>{why}</p>
<div class="box"><b>Executive summary</b><ul>{''.join(f'<li>{b}</li>' for b in bullets)}</ul></div>
<p><b>Scenario:</b> {users:,} users × {tasks_per_day} tasks/day × {days} days = {tasks_per_year:,} tasks per year.
<b>Priority mix:</b> {mix}. <b>Best-value threshold:</b> {threshold} points.</p>
<table><tr><th>#</th><th>Model</th><th>Status</th><th>Overall</th><th>Quality %</th><th>Risk %</th>
<th>Availability %</th><th>Speed (s)</th><th>Cost / year</th></tr>{summary_rows}</table>
<p><b>Recommended next step:</b> pilot the recommended vendor on a paid tier with real (secured) client data,
and check contracts, service levels and Swiss data residency.</p>
<p class="muted">Limitations: 20-task directional sample; one expert reviewer who also designed the method;
Claude on a paid tier vs free tiers for others; costs are estimates. Source: {REPO_URL}</p>
</body></html>"""

e1, e2 = st.columns(2)
e1.download_button("⬇️  Download current scenario (CSV, opens in Excel)", csv_bytes,
                   file_name="llm_vendor_scorecard.csv", mime="text/csv", use_container_width=True)
e2.download_button("⬇️  Download one-page summary (HTML, print to PDF)", summary_html.encode("utf-8"),
                   file_name="llm_vendor_scorecard_summary.html", mime="text/html", use_container_width=True)
st.caption("To save the summary as PDF: on a laptop, open the downloaded file and use Print → Save as PDF. "
           "On iPhone or iPad, open it from the Files app, tap Share → Print, then share or save the "
           "preview as PDF.")

# ---------------- Footer ----------------
st.markdown(f'<div class="footer">Built by {AUTHOR} · <a href="{REPO_URL}" target="_blank">Source code and '
            f'method on GitHub</a> · Data last updated: {last_updated} · Prices checked 2-3 Nov 2026 · '
            f'Not affiliated with any vendor.</div>', unsafe_allow_html=True)
