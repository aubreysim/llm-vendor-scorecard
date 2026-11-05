"""
summary.py - turns results.csv + scores_v2.csv into the final vendor scorecard.

Per model:
- Quality      : average score on the 16 business tasks (T01-T16), answered tasks only
- Risk         : average score on the 4 risk tasks (T17-T20), answered tasks only
- Availability : share of the 20 tasks answered on the FIRST try
- Speed        : median answer time in seconds (fastest model = 100 points)
- Cost         : estimated cost per task from real token counts x paid list price
- Overall      : weighted score (weights below - change them to test other priorities)

Saves summary.csv and summary_by_category.csv, and prints the scorecard.
"""

import os
import pandas as pd
import yaml

# ---------- Settings you may change ----------
WEIGHTS = {"quality": 40, "risk": 30, "availability": 20, "speed": 10}   # must add up to 100

# Paid list prices on OpenRouter, USD per 1 million tokens (checked 2-3 Nov 2026).
# None = no paid version available (free only).
PRICES = {
    "nvidia/nemotron-3-ultra-550b-a55b:free": (0.50, 2.20),
    "liquid/lfm-2.5-2.6b:free": (0.35, 0.50),
    "anthropic/claude-sonnet-5.5": (2.00, 10.00),
    "xingchen-agi/xing4.0-29b-a4b:free": None,
    "recursive/flint-v1.0:free": None,
}

# Scale-up scenario for the annual cost estimate
USERS = 500              # consultants
TASKS_PER_USER_DAY = 10
WORKING_DAYS = 220
MAX_REAL_LATENCY = 600   # seconds; longer = Mac slept / connection hung, left out of speed
# ---------------------------------------------

SCORES_FILE = "scores_v2.csv" if os.path.exists("scores_v2.csv") else "scores.csv"
RISK_TASKS = {"T17", "T18", "T19", "T20"}

with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)
models = config["models"]
model_ids = [m["id"] for m in models]

results = pd.read_csv("results.csv", dtype=str).fillna("")
scores = pd.read_csv(SCORES_FILE, dtype=str).fillna("")
results = results[results["model_id"].isin(model_ids)]
scores = scores[scores["model_id"].isin(model_ids)]

for col in ["latency_s", "tokens_in", "tokens_out"]:
    results[col] = pd.to_numeric(results[col], errors="coerce")
scores["score"] = pd.to_numeric(scores["score_pct"], errors="coerce")
scores.loc[scores["method"].isin(["no_answer", "judge_error"]), "score"] = None

n_tasks = results["task_id"].nunique()
tasks_per_year = USERS * TASKS_PER_USER_DAY * WORKING_DAYS

rows = []
for m in models:
    mid, label = m["id"], m["label"]
    r = results[results["model_id"] == mid]
    s = scores[scores["model_id"] == mid]
    ok = r[r["status"] == "ok"]

    business = s[~s["task_id"].isin(RISK_TASKS)]["score"].dropna()
    risk = s[s["task_id"].isin(RISK_TASKS)]["score"].dropna()
    real_latency = ok["latency_s"][ok["latency_s"] <= MAX_REAL_LATENCY].dropna()

    price = PRICES.get(mid)
    if price and ok["tokens_in"].notna().any():
        cost_task = (ok["tokens_in"].mean() * price[0] + ok["tokens_out"].mean() * price[1]) / 1_000_000
        cost_year = cost_task * tasks_per_year
    else:
        cost_task = cost_year = None

    rows.append({
        "model": label,
        "answered": f"{len(ok)}/{n_tasks}",
        "quality_pct": round(business.mean(), 1) if len(business) else None,
        "quality_tasks": len(business),
        "risk_pct": round(risk.mean(), 1) if len(risk) else None,
        "risk_tasks": len(risk),
        "availability_pct": round(100 * (r["first_try_ok"] == "yes").sum() / n_tasks, 1),
        "median_latency_s": round(real_latency.median(), 1) if len(real_latency) else None,
        "avg_tokens_out": round(ok["tokens_out"].mean()) if ok["tokens_out"].notna().any() else None,
        "cost_per_task_usd": round(cost_task, 5) if cost_task is not None else None,
        "cost_per_year_usd": round(cost_year) if cost_year is not None else None,
    })

summary = pd.DataFrame(rows)

# Speed points: fastest median = 100
fastest = summary["median_latency_s"].min()
summary["speed_pts"] = (100 * fastest / summary["median_latency_s"]).round(1)

summary["overall"] = (
    summary["quality_pct"].fillna(0) * WEIGHTS["quality"]
    + summary["risk_pct"].fillna(0) * WEIGHTS["risk"]
    + summary["availability_pct"].fillna(0) * WEIGHTS["availability"]
    + summary["speed_pts"].fillna(0) * WEIGHTS["speed"]
) / 100
summary["overall"] = summary["overall"].round(1)
summary = summary.sort_values("overall", ascending=False).reset_index(drop=True)
summary.index = summary.index + 1
summary.to_csv("summary.csv", index_label="rank")

# Score per category
by_cat = (scores.dropna(subset=["score"])
          .pivot_table(index="category", columns="model_label", values="score", aggfunc="mean")
          .round(1))
by_cat = by_cat.reindex(columns=[m["label"] for m in models if m["label"] in by_cat.columns])
by_cat.to_csv("summary_by_category.csv")

# ---------------- Print ----------------
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
print(f"\nVENDOR SCORECARD  (scores from {SCORES_FILE})")
print(f"Weights: {WEIGHTS}\n")
print(summary[["model", "overall", "quality_pct", "risk_pct", "availability_pct",
               "median_latency_s", "answered"]].to_string())
print("\nCOST ESTIMATE (real token counts x paid list price)")
print(f"Scenario: {USERS} users x {TASKS_PER_USER_DAY} tasks/day x {WORKING_DAYS} days "
      f"= {tasks_per_year:,} tasks/year")
cost_view = summary[["model", "avg_tokens_out", "cost_per_task_usd", "cost_per_year_usd"]].copy().astype(object)
cost_view = cost_view.fillna({"cost_per_task_usd": "n/a (free only)", "cost_per_year_usd": "n/a"})
print(cost_view.to_string())
print("\nSCORE BY CATEGORY (%)")
print(by_cat.to_string())
print("\nNotes: 20 tasks is a directional sample. Quality and risk use answered tasks only;"
      "\n'quality_tasks'/'risk_tasks' in summary.csv show how many each score is based on.")
print("\nSaved: summary.csv, summary_by_category.csv")
