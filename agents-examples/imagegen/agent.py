from __future__ import annotations

import base64
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

RESULTS_DIR = Path(__file__).parent / "results"
LOG_FILE = Path(__file__).parent / "logs.txt"

# imagen-4 pricing (USD per image)
PRICE_PER_IMAGE = 0.04

CAPABILITY = "imagegen"

ARGS_SCHEMA: dict = {
    "prompt": {
        "type": "string",
        "description": "Text description of the image to generate",
        "required": True,
    },
}


def append_log(entry: dict) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def generate_image(prompt: str) -> str:
    """Generate image and return base64-encoded PNG."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_images(
        model="imagen-4.0-generate-001",
        prompt=prompt,
        config=types.GenerateImagesConfig(number_of_images=1),
    )
    image_bytes = response.generated_images[0].image.image_bytes

    # Save locally for debugging / caching
    RESULTS_DIR.mkdir(exist_ok=True)
    output_path = RESULTS_DIR / f"{uuid.uuid4()}.png"
    output_path.write_bytes(image_bytes)

    append_log({
        "ts": datetime.now(timezone.utc).isoformat(),
        "request": {"prompt": prompt},
        "images_generated": 1,
        "price_usd": PRICE_PER_IMAGE,
        "output_file": str(output_path),
    })

    return base64.b64encode(image_bytes).decode("ascii")


def process_task(task: dict) -> dict:
    if task.get("mode") == "describe":
        return {"args_schema": ARGS_SCHEMA}

    capability = task.get("capability")
    if capability != CAPABILITY:
        raise ValueError(f"Unsupported capability: {capability!r}")

    body = task.get("body") or {}

    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("body.prompt must be a non-empty string")

    image_b64 = generate_image(prompt.strip())
    return {"result": {"image_base64": image_b64, "format": "png"}}


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
