from openai import OpenAI
import os, time
from dotenv import load_dotenv
load_dotenv()

client = OpenAI(
    base_url=os.getenv("NVIDIA_BASE_URL"),
    api_key=os.getenv("NVIDIA_API_KEY")
)

print("Test 1: Chat completion...")
for intento in range(5):
    try:
        r = client.chat.completions.create(
            model=os.getenv("NVIDIA_MODEL"),
            messages=[{"role":"user","content":"Deci hola"}],
            max_tokens=50,
            stream=False
        )
        print(f"OK: {r.choices[0].message.content}")
        break
    except Exception as e:
        print(f"Intento {intento+1}: {e}")
        time.sleep(10)

print("\nTest 2: Embeddings...")
try:
    r = client.embeddings.create(
        model=os.getenv("NVIDIA_EMB_MODEL"),
        input="test de embedding",
        extra_body={"input_type": "passage"}
    )
    print(f"OK: {len(r.data[0].embedding)} dimensiones")
except Exception as e:
    print(f"ERROR: {e}")
