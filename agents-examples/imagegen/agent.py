import base64
import json
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

RESULTS_DIR = Path(__file__).parent / "results"

ARGS_SCHEMA = {
    "prompt": {
        "type": "string",
        "description": "Text description of the image to generate",
        "required": True,
    },
}


def main():
    task = json.load(sys.stdin)

    if task.get("mode") == "describe":
        print(json.dumps({"args_schema": ARGS_SCHEMA, "result_schema": {"type": "file", "mime_type": "image/png"}}))
        return

    prompt = (task.get("body") or {}).get("prompt", "").strip()
    if not prompt:
        raise ValueError("body.prompt must be a non-empty string")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_images(
        model="imagen-4.0-generate-001",
        prompt=prompt,
        config=types.GenerateImagesConfig(number_of_images=1),
    )
    if not response.generated_images:
        reason = getattr(response, "prompt_feedback", None) or getattr(response, "filters", None)
        raise RuntimeError(f"Image generation returned no images: {reason}" if reason else
                           "Image generation returned no images — the prompt may have been blocked by content policy")
    image_bytes = response.generated_images[0].image.image_bytes

    print(json.dumps({"result": {
        "type": "file",
        "data": base64.b64encode(image_bytes).decode(),
        "mime_type": "image/png",
        "file_name": f"{uuid.uuid4()}.png",
    }}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
