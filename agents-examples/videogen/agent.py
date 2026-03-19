import base64
import json
import os
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

RESULTS_DIR = Path(__file__).parent / "results"

ARGS_SCHEMA = {
    "prompt": {
        "type": "string",
        "description": "Text description of the video to generate",
        "required": True,
    },
}


def main():
    task = json.load(sys.stdin)

    if task.get("mode") == "describe":
        print(json.dumps({"args_schema": ARGS_SCHEMA}))
        return

    prompt = (task.get("body") or {}).get("prompt", "").strip()
    if not prompt:
        raise ValueError("body.prompt must be a non-empty string")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    operation = client.models.generate_videos(
        model="veo-3.1-generate-preview",
        prompt=prompt,
        config=types.GenerateVideosConfig(number_of_videos=1, aspect_ratio="16:9"),
    )

    while not operation.done:
        time.sleep(10)
        operation = client.operations.get(operation)

    video = operation.result.generated_videos[0].video
    client.files.download(file=video)
    video_bytes = video.video_bytes

    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / f"{uuid.uuid4()}.mp4").write_bytes(video_bytes)

    print(json.dumps({"result": {"video_base64": base64.b64encode(video_bytes).decode(), "format": "mp4"}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
