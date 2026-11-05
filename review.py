"""
review.py - a simple browser app to read answers and judge scores side by side,
and to record whether you agree with the judge (saved to calibration.csv).

Start it in the VS Code terminal with:
    streamlit run review.py
Stop it with Control + C in the terminal.
"""

import os
import pandas as pd
import streamlit as st
import yaml

st.set_page_config(page_title="Answer review", layout="wide")

VERSIONS = {
    "Version 2 - checklist judge": {
        "scores": "scores_v2.csv",
        "calibration": "calibration_v2.csv",
        # the 3 cases you disagreed with in version 1 + 5 new ones
        "cases": [("T02", "Mid open (Xingchen)"), ("T16", "Mid open (Xingchen)"),
                  ("T14", "Small (Liquid AI)"), ("T13", "Large (NVIDIA)"),
                  ("T15", "Mid open (Xingchen)"), ("T05", "Small (Liquid AI)"),
                  ("T01", "Mid (Recursive)"), ("T08", "Large (NVIDIA)")],
    },
    "Version 1 - 1 to 5 rating": {
        "scores": "scores.csv",
        "calibration": "calibration.csv",
        "cases": [("T19", "Small (Liquid AI)"), ("T03", "Large (NVIDIA)"),
                  ("T02", "Mid open (Xingchen)"), ("T16", "Mid open (Xingchen)"),
                  ("T14", "Small (Liquid AI)")],
    },
}

available = [name for name, v in VERSIONS.items() if os.path.exists(v["scores"])]
version_name = st.sidebar.radio("Scoring version", available)
VERSION = VERSIONS[version_name]
CALIBRATION_FILE = VERSION["calibration"]
CALIBRATION_CASES = VERSION["cases"]


@st.cache_data
def load(scores_file):
    with open("config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    model_labels = [m["label"] for m in config["models"]]
    tasks = pd.read_csv("tasks.csv", dtype=str).fillna("")
    results = pd.read_csv("results.csv", dtype=str).fillna("")
    scores = pd.read_csv(scores_file, dtype=str).fillna("")
    results = results[results["model_label"].isin(model_labels)]
    scores = scores[scores["model_label"].isin(model_labels)]
    return model_labels, tasks, results, scores


def load_calibration():
    if os.path.exists(CALIBRATION_FILE):
        return pd.read_csv(CALIBRATION_FILE, dtype=str).fillna("")
    return pd.DataFrame(columns=["task_id", "model_label", "judge_score", "your_view", "note"])


model_labels, tasks, results, scores = load(VERSION["scores"])

st.title("Answer review")
st.caption(f"Showing {version_name} (from {VERSION['scores']})")
tab_review, tab_overview = st.tabs(["Review one answer", "Overview of all scores"])

# ---------------- Review one answer ----------------
with tab_review:
    only_calibration = st.checkbox(f"Show only the {len(CALIBRATION_CASES)} calibration cases", value=True)

    if only_calibration:
        options = [f"{t} | {m}" for t, m in CALIBRATION_CASES]
        choice = st.radio("Calibration case", options, horizontal=True)
        task_id, model_label = [part.strip() for part in choice.split("|")]
    else:
        col_a, col_b = st.columns(2)
        task_options = [f"{r.id} - {r.category}" for r in tasks.itertuples()]
        task_id = col_a.selectbox("Task", task_options).split(" - ")[0]
        model_label = col_b.selectbox("Model", model_labels)

    task = tasks[tasks["id"] == task_id].iloc[0]
    result = results[(results["task_id"] == task_id) & (results["model_label"] == model_label)]
    score = scores[(scores["task_id"] == task_id) & (scores["model_label"] == model_label)]

    st.subheader(f"{task_id} ({task['category']}) - {model_label}")

    left, right = st.columns(2)
    with left:
        st.markdown("**Instruction**")
        st.info(task["prompt"])
        with st.expander("Task input (what the model was given)", expanded=False):
            st.text(task["input_text"])
        st.markdown("**Answer key / criteria**")
        st.success(task["reference"])

    with right:
        st.markdown("**Model's answer**")
        if result.empty or result.iloc[0]["status"] != "ok":
            st.warning("This model gave no answer for this task.")
        else:
            st.markdown(result.iloc[0]["response"])
            st.caption(f"Answer time: {result.iloc[0]['latency_s']} s")

        st.markdown("**Judge's verdict**")
        if score.empty:
            st.write("Not scored yet.")
        else:
            s = score.iloc[0]
            st.metric("Score", f"{s['score_pct']}%" if s["score_pct"] else "-")
            st.write(f"Method: {s['method']}")
            st.write(f"Reason: {s['reason']}")
            if s.get("details"):
                st.markdown("**Checklist**")
                for item in s["details"].split(" | "):
                    st.write(("✅ " if item.startswith("OK:") else "❌ ") + item.split(": ", 1)[-1])
            st.write(f"Word count: {s['word_count']}"
                     + (f"  (within limit: {s['word_limit_ok']})" if s["word_limit_ok"] else ""))

    st.divider()
    st.markdown("**Your view (calibration)**")
    calibration = load_calibration()
    existing = calibration[(calibration["task_id"] == task_id) & (calibration["model_label"] == model_label)]
    views = ["Agree with judge", "Judge too harsh", "Judge too generous"]
    default_view = views.index(existing.iloc[0]["your_view"]) if not existing.empty else 0
    your_view = st.radio("Do you agree with the judge's score?", views, index=default_view,
                         key=f"view_{CALIBRATION_FILE}_{task_id}_{model_label}")
    note = st.text_input("Note (optional)", value=existing.iloc[0]["note"] if not existing.empty else "",
                         key=f"note_{CALIBRATION_FILE}_{task_id}_{model_label}")
    if st.button("Save my view"):
        calibration = calibration[~((calibration["task_id"] == task_id) &
                                    (calibration["model_label"] == model_label))]
        new_row = {"task_id": task_id, "model_label": model_label,
                   "judge_score": score.iloc[0]["score_pct"] if not score.empty else "",
                   "your_view": your_view, "note": note}
        calibration = pd.concat([calibration, pd.DataFrame([new_row])], ignore_index=True)
        calibration.to_csv(CALIBRATION_FILE, index=False)
        st.success(f"Saved to {CALIBRATION_FILE}")

    saved = load_calibration()
    if not saved.empty:
        agree = (saved["your_view"] == "Agree with judge").sum()
        st.caption(f"Calibration so far: you agree with the judge on {agree} of {len(saved)} cases.")

# ---------------- Overview ----------------
with tab_overview:
    st.markdown("Score per task and model (%). Empty = no answer or not scored.")
    table = scores.copy()
    table["score"] = pd.to_numeric(table["score_pct"], errors="coerce")
    table.loc[table["method"] == "no_answer", "score"] = None
    pivot = table.pivot_table(index="task_id", columns="model_label", values="score", aggfunc="first")
    pivot = pivot.reindex(columns=[m for m in model_labels if m in pivot.columns])
    st.dataframe(pivot, use_container_width=True, height=760)

    st.markdown("**Average quality on answered tasks**")
    avg = table.dropna(subset=["score"]).groupby("model_label")["score"].agg(["mean", "count"])
    avg.columns = ["average %", "tasks answered"]
    st.dataframe(avg.round(1).sort_values("average %", ascending=False), use_container_width=True)
