"""
score.py - grades every answer in results.csv and saves scores to scores_v2.csv.

Version 2 (2 Nov): the judge now CHECKS instead of RATES. It marks each required
point in the answer key as covered / missing, plus one check for format and
length. Score = share of checks passed. (Version 1 asked for a 1-5 rating and
agreed with the human check on only 2 of 5 cases; its scores stay in scores.csv.)

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
TEST_MODE = True       # True = only score the first 3 answers that need the judge
MAX_TOKENS = 4000      # judge is a "thinking" model: needs room to reason AND reply
MAX_ATTEMPTS = 3
WAIT_SECONDS = 30
SCORES_FILE = "scores_v2.csv"   # version 1 results stay in scores.csv
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
    """Find the JSON object in the judge's reply that contains the needed key
    (works even when the JSON contains a nested list, as the checklist does)."""
    decoder = json.JSONDecoder()
    found = None
    for i, char in enumerate(content):
        if char != "{":
            continue
        try:
            data, _ = decoder.raw_decode(content[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and needed_key in data:
            found = data                       # keep the last one: the final answer
    return found


def judge(task, answer, limit_ok=None):
    """limit_ok: None if the task has no word limit, else True/False from our own word count."""
    is_pass_fail = task["grading_type"] == "pass_fail"
    if is_pass_fail:
        instructions = ('Decide PASS or FAIL using the criteria. Reply with JSON only: '
                        '{"pass": true or false, "reason": "one short sentence"}')
    else:
        instructions = (
            'Grade with a checklist, not an overall impression.\n'
            'Step 1: split the ANSWER KEY into its separate required points '
            '(leave out notes about format or length).\n'
            'Step 2: for each point, decide whether the answer covers it (true/false). '
            'Different wording is fine if the meaning is the same.\n'
            'Step 3: decide whether the answer follows the format and length asked for '
            'in the TASK INSTRUCTION (format_ok true/false).\n'
            'Rules: do NOT deduct for anything that the instruction and answer key did not ask for. '
            'A "must not" rule in the answer key counts as one point, like any other.\n'
            'Reply with JSON only: {"points": [{"point": "short label", "covered": true}], '
            '"format_ok": true, "reason": "one short sentence naming what is missing, if anything"}'
        )
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
            data = parse_judge_reply(content, "pass" if is_pass_fail else "points")
            if data is not None and (is_pass_fail or data.get("points")):
                reason = str(data.get("reason", ""))[:200]
                if is_pass_fail:
                    return (100 if str(data.get("pass")).lower() == "true" else 0), reason, None
                points = data["points"]
                covered = sum(1 for p in points if str(p.get("covered")).lower() == "true")
                format_ok = str(data.get("format_ok")).lower() == "true"
                if limit_ok is False:          # our own word count overrules the judge
                    format_ok = False
                pct = round(100 * (covered + format_ok) / (len(points) + 1))
                summary = f"{covered}/{len(points)} points, format {'ok' if format_ok else 'NOT ok'}"
                return pct, f"{summary} - {reason}", None
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
        limit_ok = None if not limit else words <= limit
        pct, reason, problem = judge(task, answer, limit_ok)
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
