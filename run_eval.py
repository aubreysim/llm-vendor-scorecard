"""
run_eval.py - sends every task in tasks.csv to every model in config.yaml
and saves the answers to results.csv.

- Waits and retries when a free model is busy (429) or returns an empty answer.
- Saves after every answer, so nothing is lost if it stops.
- Can be run again: answers that already worked are skipped,
  only missing or failed ones are tried again.
"""

import os
import csv
import time
from datetime import datetime

import yaml
from dotenv import load_dotenv
from openai import OpenAI

# ---------- Settings you may change ----------
TEST_MODE = False     # True = only the first 2 tasks (quick check). False = all 20.
MAX_TOKENS = 2000     # word allowance per answer ("thinking" models need room)
MAX_ATTEMPTS = 3      # tries per task before marking it as failed
WAIT_SECONDS = 30     # pause between tries when a model is busy
RESULTS_FILE = "results.csv"
# ---------------------------------------------

FIELDS = [
    "task_id", "category", "model_id", "model_label", "status", "attempts",
    "first_try_ok", "latency_s", "tokens_in", "tokens_out", "response",
    "error", "timestamp",
]

load_dotenv()
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    timeout=180,
)

with open("config.yaml", encoding="utf-8") as f:
    config = yaml.safe_load(f)

with open("tasks.csv", encoding="utf-8") as f:
    tasks = list(csv.DictReader(f))

if TEST_MODE:
    tasks = tasks[:2]
    print("TEST MODE: running only the first 2 tasks.\n")

# Load earlier results so a re-run continues where it stopped
results = {}
if os.path.exists(RESULTS_FILE):
    with open(RESULTS_FILE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            results[(row["task_id"], row["model_id"])] = row


def save_results():
    with open(RESULTS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for key in sorted(results):
            writer.writerow(results[key])


def is_daily_limit(message):
    text = message.lower()
    return "per-day" in text or "per day" in text


stop_all = False

# Tasks on the outside, models inside: spreads the load across providers
for task in tasks:
    for model in config["models"]:
        key = (task["id"], model["id"])
        previous = results.get(key)
        if previous and previous["status"] == "ok":
            continue  # already answered in an earlier run

        previous_attempts = int(previous["attempts"]) if previous else 0
        messages = [{"role": "user", "content": f"{task['prompt']}\n\n{task['input_text']}"}]

        status, error, answer = "failed", "", ""
        tokens_in = tokens_out = latency = ""
        attempts_now = 0

        for attempt in range(1, MAX_ATTEMPTS + 1):
            attempts_now = attempt
            start = time.time()
            try:
                r = client.chat.completions.create(
                    model=model["id"], messages=messages, max_tokens=MAX_TOKENS
                )
                latency = round(time.time() - start, 2)
                content = r.choices[0].message.content if r.choices else None
                if content and content.strip():
                    answer, status, error = content.strip(), "ok", ""
                    if r.usage:
                        tokens_in = r.usage.prompt_tokens
                        tokens_out = r.usage.completion_tokens
                    break
                error = "empty response"
            except Exception as e:
                error = str(e)[:300]
                if is_daily_limit(error):
                    stop_all = True
                    break
            if attempt < MAX_ATTEMPTS:
                print(f"   ...{model['label']} busy, retrying in {WAIT_SECONDS}s")
                time.sleep(WAIT_SECONDS)

        results[key] = {
            "task_id": task["id"],
            "category": task["category"],
            "model_id": model["id"],
            "model_label": model["label"],
            "status": status,
            "attempts": previous_attempts + attempts_now,
            "first_try_ok": "yes" if (previous_attempts == 0 and status == "ok" and attempts_now == 1) else "no",
            "latency_s": latency,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "response": answer,
            "error": error,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        save_results()

        mark = "OK  " if status == "ok" else "FAIL"
        print(f"{mark} {task['id']} | {model['label']} | {latency}s | {error[:80]}")

        if stop_all:
            break
    if stop_all:
        print("\nDaily free limit reached. Run again tomorrow - finished answers are kept.")
        break

done = sum(1 for r in results.values() if r["status"] == "ok")
print(f"\nFinished: {done} of {len(results)} answers saved in {RESULTS_FILE}.")
