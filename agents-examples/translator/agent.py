from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

LOG_FILE = Path(__file__).parent / "logs.txt"

# gemini-2.5-flash pricing (USD per 1M tokens)
PRICE_INPUT_PER_1M = 0.15
PRICE_OUTPUT_PER_1M = 0.60

CAPABILITY = "translate"

ARGS_SCHEMA: dict = {
    "text": {
        "type": "string",
        "description": "Text to translate",
        "required": True,
    },
    "target_language": {
        "type": "string",
        "description": "Target language, e.g. 'Russian', 'Spanish', 'fr', 'de'",
        "required": True,
    },
}


def append_log(entry: dict) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def translate(text: str, target_language: str) -> str:
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")

    client = genai.Client(api_key=api_key)
    prompt = (
        f"Translate the following text to {target_language}. "
        "Return only the translated text, no explanations or extra content.\n\n"
        f"{text}"
    )
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)

    usage = response.usage_metadata
    input_tokens = usage.prompt_token_count or 0
    output_tokens = usage.candidates_token_count or 0
    price_usd = (input_tokens * PRICE_INPUT_PER_1M + output_tokens * PRICE_OUTPUT_PER_1M) / 1_000_000

    append_log({
        "ts": datetime.now(timezone.utc).isoformat(),
        "request": {"text": text, "target_language": target_language},
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "price_usd": round(price_usd, 8),
    })

    return response.text.strip()


def process_task(task: dict) -> dict:
    if task.get("mode") == "describe":
        return {"args_schema": ARGS_SCHEMA}

    capability = task.get("capability")
    if capability != CAPABILITY:
        raise ValueError(f"Unsupported capability: {capability!r}")

    body = task.get("body") or {}

    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("body.text must be a non-empty string")

    target_language = body.get("target_language")
    if not isinstance(target_language, str) or not target_language.strip():
        raise ValueError("body.target_language must be a non-empty string")

    translated = translate(text.strip(), target_language.strip())
    return {"result": translated}


def main() -> None:
    task = json.load(sys.stdin)
    result = process_task(task)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
