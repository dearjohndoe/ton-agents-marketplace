import base64
import importlib.util
import unittest
from unittest.mock import patch

from agent import process_task, synthesize_to_wav_base64


HAS_PYTTSX3 = importlib.util.find_spec("pyttsx3") is not None


class TestText2VoiceAgent(unittest.TestCase):
    @patch("agent.synthesize_to_wav_base64", return_value="ZmFrZV93YXY=")
    def test_process_task_success(self, synth_mock):
        payload = {
            "capability": "text2voice",
            "body": {
                "text": "Hello world",
                "rate": 140,
            },
        }

        result = process_task(payload)

        self.assertEqual(result["result"]["format"], "wav")
        self.assertEqual(result["result"]["audio_base64"], "ZmFrZV93YXY=")
        synth_mock.assert_called_once_with("Hello world", 140)

    def test_process_task_rejects_empty_text(self):
        payload = {
            "capability": "text2voice",
            "body": {
                "text": "   ",
            },
        }

        with self.assertRaisesRegex(ValueError, "body.text must be a non-empty string"):
            process_task(payload)

    def test_process_task_rejects_bad_capability(self):
        payload = {
            "capability": "translate",
            "body": {
                "text": "Hello",
            },
        }

        with self.assertRaisesRegex(ValueError, "Unsupported capability"):
            process_task(payload)


@unittest.skipUnless(HAS_PYTTSX3, "pyttsx3 is not installed")
class TestText2VoiceAudioGeneration(unittest.TestCase):
    def test_synthesize_generates_valid_wav_base64(self):
        try:
            audio_b64 = synthesize_to_wav_base64("hello from test", rate=150)
        except (OSError, RuntimeError) as exc:
            self.skipTest(f"TTS backend is not available: {exc}")

        self.assertIsInstance(audio_b64, str)
        self.assertGreater(len(audio_b64), 0)

        audio_bytes = base64.b64decode(audio_b64)
        self.assertGreater(len(audio_bytes), 44)
        self.assertEqual(audio_bytes[:4], b"RIFF")
        self.assertEqual(audio_bytes[8:12], b"WAVE")


if __name__ == "__main__":
    unittest.main()
