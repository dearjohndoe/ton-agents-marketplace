from __future__ import annotations

import base64
import json
import sys
import tempfile
import time
from pathlib import Path

CAPABILITY = "text2voice"

ARGS_SCHEMA: dict = {
    "text": {
        "type": "string",
        "description": "Text to synthesize",
        "required": True,
    },
    "rate": {
        "type": "number",
        "description": "Speech rate in words per minute (80–300, optional)",
        "required": False,
    },
}


def pick_english_voice(engine) -> str | None:
    for voice in engine.getProperty("voices"):
        voice_id = (voice.id or "").lower()
        voice_name = (voice.name or "").lower()
        langs = " ".join(
            [
                item.decode("utf-8", errors="ignore") if isinstance(item, bytes) else str(item)
                for item in (voice.languages or [])
            ]
        ).lower()
        if "en" in voice_id or "english" in voice_name or "en" in langs:
            return voice.id
    return None


def synthesize_to_wav_base64(text: str, rate: int | None = None) -> str:
    import pyttsx3

    engine = pyttsx3.init()
    english_voice = pick_english_voice(engine)
    if english_voice:
        engine.setProperty("voice", english_voice)

    if isinstance(rate, int) and 80 <= rate <= 300:
        engine.setProperty("rate", rate)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        engine.save_to_file(text, str(temp_path))
        engine.runAndWait()

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if temp_path.exists() and temp_path.stat().st_size > 0:
                break
            time.sleep(0.05)

        audio_bytes = temp_path.read_bytes()
        if not audio_bytes:
            raise RuntimeError("TTS backend produced empty audio")
        return base64.b64encode(audio_bytes).decode("ascii")
    finally:
        temp_path.unlink(missing_ok=True)


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

    rate = body.get("rate")
    if rate is not None:
        try:
            rate = int(rate)
        except (TypeError, ValueError) as exc:
            raise ValueError("body.rate must be a number") from exc

    audio_b64 = synthesize_to_wav_base64(text.strip(), rate)
    return {"result": {"audio_base64": audio_b64, "format": "wav"}}


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
