# services/ollama_generate.py
import os, json, time
import urllib.request

BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")

def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))

def main():
    prompt = "Explica en 2 líneas qué es un número primo."
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
        },
    }

    t0 = time.time()
    out = post_json(f"{BASE_URL}/api/generate", payload)
    dt = time.time() - t0

    text = out.get("response", "").strip()
    print(text)
    print(f"\n---\nmodel={MODEL} time_s={dt:.2f}")

if __name__ == "__main__":
    main()
