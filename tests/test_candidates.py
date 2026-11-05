import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

candidates = [
    "thinkingmachines/inkling-small:free",
    "xingchen-agi/xing4.0-29b-a4b:free",
    "recursive/flint-v1.0:free",
]

for model_id in candidates:
    try:
        r = client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": "In two sentences, what is a SWOT analysis?"}],
            max_tokens=300,
        )
        text = (r.choices[0].message.content or "").strip()
        print("OK   ", model_id, "->", text[:120], "\n")
    except Exception as e:
        print("FAIL ", model_id, "->", str(e)[:150], "\n")