import base64
import json
import sys
import tempfile
import time
from pathlib import Path

ARGS_SCHEMA = {
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


def synthesize(text: str, rate: int | None = None) -> str:
    import pyttsx3

    engine = pyttsx3.init()

    # Prefer English voice if available
    for voice in engine.getProperty("voices"):
        langs = " ".join(
            item.decode("utf-8", errors="ignore") if isinstance(item, bytes) else str(item)
            for item in (voice.languages or [])
        ).lower()
        if "en" in (voice.id or "").lower() or "english" in (voice.name or "").lower() or "en" in langs:
            engine.setProperty("voice", voice.id)
            break

    if isinstance(rate, int) and 80 <= rate <= 300:
        engine.setProperty("rate", rate)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp = Path(f.name)

    try:
        engine.save_to_file(text, str(tmp))
        engine.runAndWait()

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if tmp.exists() and tmp.stat().st_size > 0:
                break
            time.sleep(0.05)

        audio_bytes = tmp.read_bytes()
        if not audio_bytes:
            raise RuntimeError("TTS backend produced empty audio")
        return base64.b64encode(audio_bytes).decode()
    finally:
        tmp.unlink(missing_ok=True)


def main():
    task = json.load(sys.stdin)

    if task.get("mode") == "describe":
        print(json.dumps({"args_schema": ARGS_SCHEMA}))
        return

    body = task.get("body") or {}

    text = body.get("text", "").strip()
    if not text:
        raise ValueError("body.text must be a non-empty string")

    rate = body.get("rate")
    if rate is not None:
        rate = int(rate)

    audio_b64 = synthesize(text, rate)
    print(json.dumps({"result": {"audio_base64": audio_b64, "format": "wav"}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
