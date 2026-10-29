import os
import yaml
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

with open("config.yaml") as f:
    config = yaml.safe_load(f)

model_ids = [m["id"] for m in config["models"]] + [config["judge"]]

for model_id in model_ids:
    try:
        r = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": "Reply with one short sentence."}],
            max_tokens=200,
        )
        text = (r.choices[0].message.content or "").strip()
        print("OK   ", model_id, "->", text[:60])
    except Exception as e:
        print("FAIL ", model_id, "->", str(e)[:150])