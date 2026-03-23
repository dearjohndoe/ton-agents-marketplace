import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ARGS_SCHEMA = {
    "text": {
        "type": "string",
        "description": "Text to summarize",
        "required": True,
    },
    "max_sentences": {
        "type": "number",
        "description": "Maximum number of sentences in the summary (optional, default 5)",
        "required": False,
    },
}


def main():
    task = json.load(sys.stdin)

    if task.get("mode") == "describe":
        print(json.dumps({"args_schema": ARGS_SCHEMA, "result_schema": {"type": "string"}}))
        return

    body = task.get("body") or {}

    text = body.get("text", "").strip()
    if not text:
        raise ValueError("body.text must be a non-empty string")

    max_sentences = max(1, int(body.get("max_sentences", 5)))

    from google import genai

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    prompt = (
        f"Summarize the following text in no more than {max_sentences} sentences. "
        "Return only the summary, no explanations or extra content.\n\n"
        f"{text}"
    )
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)

    print(json.dumps({"result": {"type": "string", "data": response.text.strip()}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
