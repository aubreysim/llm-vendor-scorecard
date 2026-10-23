import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # reads your secret key from .env

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

response = client.chat.completions.create(
    model="openrouter/free",
    messages=[{"role": "user", "content": "Say hello in one short sentence."}],
)

print(response.choices[0].message.content)
print("Tokens used:", response.usage.total_tokens)