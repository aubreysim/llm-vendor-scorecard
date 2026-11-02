"""
score.py - grades every answer in results.csv and saves scores to scores.csv.

- Automatic checks for tasks with one right answer (T06, T09, T11, T12).
- An LLM judge (from config.yaml) for all other tasks.
- Every score is converted to 0-100%.
- Only scores models listed in config.yaml.
- Can be run again: already-scored answers are skipped.
"""

import os
import re
import csv
import json
import time
from datetime import datetime

import yaml
from dotenv import load_dotenv
from openai import OpenAI

# ---------- Settings you may change ----------
TEST_MODE = False       # True = only score the first 3 answers that need the judge
MAX_TOKENS = 4000      # judge is a "thinking" model: needs room to reason AND reply
MAX_ATTEMPTS = 3
WAIT_SECONDS = 30
SCORES_FILE = "scores.csv"
# ---------------------------------------------

# Expected numbers for numeric tasks (score = share of numbers found)
NUMERIC_EXPECTED = {
    "T06": [7_020_000],            # SOM in CHF
    "T11": [18_000, 32_500],       # licence cost, total
}
# Word limits stated in the task instructions
WORD_LIMITS = {"T03": 60, "T13": 150, "T14": 100}

FIELDS = [
    "task_id", "category", "model_id", "model_label", "method",
    "score_pct", "reason", "word_count", "word_limit_ok", "timestamp",
]

load_dotenv()
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    timeout=180,
)

with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)
JUDGE = config["judge"]
MODEL_IDS = {m["id"] for m in config["models"]}

with open("tasks.csv", encoding="utf-8") as f:
    tasks = {t["id"]: t for t in csv.DictReader(f)}

with open("results.csv", encoding="utf-8") as f:
    results = [r for r in csv.DictReader(f) if r["model_id"] in MODEL_IDS]

scores = {}
if os.path.exists(SCORES_FILE):
    with open(SCORES_FILE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # re-check failed judge calls and answers that were missing last time
            if row["method"] not in ("judge_error", "no_answer"):
                scores[(row["task_id"], row["model_id"])] = row


def save_scores():
    with open(SCORES_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for key in sorted(scores):
            writer.writerow(scores[key])


# ---------------- Automatic checks ----------------

def find_numbers(text):
    """Return all numbers in the text; '7.02 million' becomes 7020000."""
    clean = text.replace("'", "").replace("’", "").replace(" ", "")
    values = []
    pattern = r"(\d[\d,]*(?:\.\d+)?)\s*(million|mio\.?|m\b)?"
    for number, unit in re.findall(pattern, clean, flags=re.IGNORECASE):
        try:
            value = float(number.replace(",", ""))
        except ValueError:
            continue
        if unit:
            value *= 1_000_000
        values.append(value)
    return values


def score_numeric(task_id, answer):
    expected = NUMERIC_EXPECTED[task_id]
    found = find_numbers(answer)
    hits = [e for e in expected if any(abs(v - e) <= e * 0.005 for v in found)]
    pct = round(100 * len(hits) / len(expected))
    missing = [e for e in expected if e not in hits]
    reason = "all expected numbers found" if not missing else f"missing: {missing}"
    return pct, reason


def score_json(answer):
    match = re.search(r"\{.*\}", answer, flags=re.DOTALL)
    if not match:
        return 0, "no JSON found"
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return 0, "invalid JSON"
    data = {k.lower(): str(v).lower() for k, v in data.items()}
    checks = {
        "company_acquired": "cloudnest" in data.get("company_acquired", ""),
        "buyer": "helvetia data systems" in data.get("buyer", ""),
        "deal_value": "85" in data.get("deal_value", "") and
                      ("eur" in data.get("deal_value", "") or "€" in data.get("deal_value", "")),
        "announcement_date": "2025-09-03" in data.get("announcement_date", "") or
                             ("3" in data.get("announcement_date", "") and
                              "sep" in data.get("announcement_date", "") and
                              "2025" in data.get("announcement_date", "")),
    }
    correct = sum(checks.values())
    wrong = [k for k, ok in checks.items() if not ok]
    reason = f"{correct}/4 fields correct" + (f" (wrong: {', '.join(wrong)})" if wrong else "")
    return round(100 * correct / 4), reason


def score_classification(reference, answer):
    expected = dict(re.findall(r"(\d+)\s*:\s*(\w+)", reference))
    given = {}
    for line in answer.splitlines():
        m = re.search(r"(\d+)\s*[:.)\-]\s*\**\s*(access|hardware|software|network)",
                      line, flags=re.IGNORECASE)
        if m:
            given[m.group(1)] = m.group(2).capitalize()
    correct = sum(1 for k, v in expected.items() if given.get(k) == v)
    return round(100 * correct / len(expected)), f"{correct}/{len(expected)} tickets correct"


# ---------------- LLM judge ----------------

def parse_judge_reply(content, needed_key):
    """Find the JSON object in the judge's reply that contains the needed key."""
    candidates = re.findall(r"\{[^{}]*\}", content, flags=re.DOTALL)
    for text in reversed(candidates):          # the final answer is usually last
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if needed_key in data:
            return data
    return None


def judge(task, answer):
    is_pass_fail = task["grading_type"] == "pass_fail"
    if is_pass_fail:
        instructions = ('Decide PASS or FAIL using the criteria. Reply with JSON only: '
                        '{"pass": true or false, "reason": "one short sentence"}')
    else:
        instructions = ('Score the answer from 1 (poor) to 5 (excellent) against the answer key: '
                        'coverage of required points, accuracy (no invented facts), and following '
                        'the instruction (format, length). Reply with JSON only: '
                        '{"score": 1-5, "reason": "one short sentence"}')
    prompt = (
        "You are a strict, fair grader of business tasks.\n\n"
        f"TASK INSTRUCTION:\n{task['prompt']}\n\n"
        f"TASK INPUT:\n{task['input_text']}\n\n"
        f"ANSWER KEY / CRITERIA:\n{task['reference']}\n\n"
        f"ANSWER TO GRADE:\n{answer}\n\n"
        f"{instructions}"
    )
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            r = client.chat.completions.create(
                model=JUDGE,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=MAX_TOKENS,
                temperature=0,
            )
            content = (r.choices[0].message.content or "") if r.choices else ""
            data = parse_judge_reply(content, "pass" if is_pass_fail else "score")
            if data is not None:
                reason = str(data.get("reason", ""))[:200]
                if is_pass_fail:
                    return (100 if str(data.get("pass")).lower() == "true" else 0), reason, None
                score = max(1, min(5, int(float(data["score"]))))
                return round((score - 1) / 4 * 100), f"{score}/5 - {reason}", None
            # OpenRouter sometimes hides the real error inside an empty response
            hidden = getattr(r, "error", None) or (getattr(r, "model_extra", None) or {}).get("error")
            if hidden:
                last_error = f"OpenRouter error: {str(hidden)[:200]}"
                print(f"   ...{last_error}")
                if "per-day" in last_error.lower() or "per day" in last_error.lower():
                    return None, last_error, "daily_limit"
            else:
                finish = r.choices[0].finish_reason if r.choices else "none"
                snippet = content.strip().replace("\n", " ")[:80] or "(empty)"
                last_error = f"judge gave no usable JSON (finish: {finish}, reply: {snippet})"
                print(f"   ...{last_error}")
        except Exception as e:
            last_error = str(e)[:200]
            if "per-day" in last_error.lower() or "per day" in last_error.lower():
                return None, last_error, "daily_limit"
        if attempt < MAX_ATTEMPTS:
            print(f"   ...judge busy, retrying in {WAIT_SECONDS}s")
            time.sleep(WAIT_SECONDS)
    return None, last_error, "error"


# ---------------- Main loop ----------------

judge_calls = 0
for row in sorted(results, key=lambda r: (r["task_id"], r["model_id"])):
    key = (row["task_id"], row["model_id"])
    if key in scores:
        continue
    task = tasks[row["task_id"]]
    answer = row["response"]
    words = len(answer.split())
    limit = WORD_LIMITS.get(row["task_id"])

    if row["status"] != "ok":
        method, pct, reason = "no_answer", 0, "model gave no answer"
    elif task["grading_type"] == "numeric":
        method, (pct, reason) = "auto", score_numeric(row["task_id"], answer)
    elif task["grading_type"] == "exact_match":
        method, (pct, reason) = "auto", score_json(answer)
    elif task["grading_type"] == "accuracy":
        method, (pct, reason) = "auto", score_classification(task["reference"], answer)
    else:
        if TEST_MODE and judge_calls >= 3:
            continue
        judge_calls += 1
        print(f"Judging {row['task_id']} | {row['model_label']} ... (can take up to a minute)")
        pct, reason, problem = judge(task, answer)
        if problem == "daily_limit":
            print("\nDaily free limit reached. Run again tomorrow - finished scores are kept.")
            break
        method = "judge" if problem is None else "judge_error"
        if pct is None:
            pct = ""

    scores[key] = {
        "task_id": row["task_id"],
        "category": row["category"],
        "model_id": row["model_id"],
        "model_label": row["model_label"],
        "method": method,
        "score_pct": pct,
        "reason": reason,
        "word_count": words,
        "word_limit_ok": "" if not limit else ("yes" if words <= limit else "no"),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    save_scores()
    print(f"{row['task_id']} | {row['model_label']} | {method} | {pct}% | {reason[:70]}")

done = sum(1 for s in scores.values() if s["method"] not in ("judge_error", "no_answer"))
print(f"\nScored {done} answers. Saved in {SCORES_FILE}.")
if TEST_MODE:
    print("TEST MODE was on: only 3 judge calls were made.")
