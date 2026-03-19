from __future__ import annotations

import base64
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

RESULTS_DIR = Path(__file__).parent / "results"
LOG_FILE = Path(__file__).parent / "logs.txt"

# veo-3.1 pricing (USD per second of generated video)
PRICE_PER_SECOND = 0.35

CAPABILITY = "videogen"

ARGS_SCHEMA: dict = {
    "prompt": {
        "type": "string",
        "description": "Text description of the video to generate",
        "required": True,
    },
}


def append_log(entry: dict) -> None:
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def generate_video(prompt: str) -> str:
    """Generate video and return base64-encoded MP4."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")

    client = genai.Client(api_key=api_key)

    operation = client.models.generate_videos(
        model="veo-3.1-generate-preview",
        prompt=prompt,
        config=types.GenerateVideosConfig(
            number_of_videos=1,
            aspect_ratio="16:9",
        ),
    )

    while not operation.done:
        time.sleep(10)
        operation = client.operations.get(operation)

    video = operation.result.generated_videos[0].video
    client.files.download(file=video)
    video_bytes = video.video_bytes

    # Save locally for debugging / caching
    RESULTS_DIR.mkdir(exist_ok=True)
    output_path = RESULTS_DIR / f"{uuid.uuid4()}.mp4"
    output_path.write_bytes(video_bytes)

    append_log({
        "ts": datetime.now(timezone.utc).isoformat(),
        "request": {"prompt": prompt},
        "price_usd": PRICE_PER_SECOND,
        "output_file": str(output_path),
    })

    return base64.b64encode(video_bytes).decode("ascii")


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

    video_b64 = generate_video(prompt.strip())
    return {"result": {"video_base64": video_b64, "format": "mp4"}}


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
