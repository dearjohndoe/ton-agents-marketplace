"""Тесты для list-seller агента.

Главная цель — убедиться, что при параллельном вызове из разных процессов:
  * каждый токен выдаётся ровно одному вызову (нет дублирования),
  * лишние вызовы получают out_of_stock,
  * файл токенов не повреждается.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import agent


HERE = Path(__file__).resolve().parent
AGENT_PATH = HERE / "agent.py"


def _run_agent(env: dict, payload: dict, timeout: float = 30.0) -> tuple[int, dict | None, str]:
    """Запускает agent.py в subprocess. Возвращает (exit_code, parsed_stdout_or_None, stderr)."""
    proc = subprocess.run(
        [sys.executable, str(AGENT_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
    parsed: dict | None = None
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError:
            parsed = None
    return proc.returncode, parsed, proc.stderr


def _make_env(tokens_path: Path, log_path: Path | None = None) -> dict:
    env = os.environ.copy()
    env["TOKENS_FILE_PATH"] = str(tokens_path)
    if log_path is not None:
        env["LOG_FILE_PATH"] = str(log_path)
    env["CALLER_ADDRESS"] = "EQTEST_address"
    env["CALLER_TX_HASH"] = "tx_test"
    env["PAYMENT_RAIL"] = "TON"
    return env


class TestUnit(unittest.TestCase):
    def test_describe(self):
        with tempfile.TemporaryDirectory() as td:
            tokens = Path(td) / "tokens-default.txt"
            tokens.write_text("a\nb\n")
            code, out, err = _run_agent(_make_env(tokens), {"mode": "describe"})
            self.assertEqual(code, 0, err)
            self.assertIn("args_schema", out)
            self.assertIn("result_schema", out)

    def test_pop_first_token_atomic(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.txt"
            p.write_text("alpha\nbeta\ngamma\n")
            self.assertEqual(agent._pop_first_token(p), "alpha")
            self.assertEqual(p.read_text(), "beta\ngamma\n")
            self.assertEqual(agent._pop_first_token(p), "beta")
            self.assertEqual(p.read_text(), "gamma\n")
            self.assertEqual(agent._pop_first_token(p), "gamma")
            self.assertEqual(p.read_text(), "")
            self.assertIsNone(agent._pop_first_token(p))

    def test_pop_skips_blank_lines(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.txt"
            p.write_text("\n\nx\n\n\ny\n")
            self.assertEqual(agent._pop_first_token(p), "x")
            self.assertEqual(agent._pop_first_token(p), "y")
            self.assertIsNone(agent._pop_first_token(p))

    def test_mask(self):
        self.assertEqual(agent._mask("short"), "***")
        self.assertEqual(agent._mask("abcdefghijkl"), "abcd...ijkl")

    def test_out_of_stock_when_empty(self):
        with tempfile.TemporaryDirectory() as td:
            tokens = Path(td) / "tokens-default.txt"
            tokens.write_text("")
            code, out, err = _run_agent(_make_env(tokens), {"body": {"sku": "default"}})
            self.assertEqual(code, 0, err)
            self.assertEqual(out.get("error"), "out_of_stock")
            self.assertEqual(out.get("sku"), "default")

    def test_missing_tokens_file_fails(self):
        with tempfile.TemporaryDirectory() as td:
            tokens = Path(td) / "absent.txt"
            code, out, err = _run_agent(_make_env(tokens), {"body": {}})
            self.assertNotEqual(code, 0)
            self.assertIn("tokens file not found", err)

    def test_missing_env_fails(self):
        env = os.environ.copy()
        env.pop("TOKENS_FILE_PATH", None)
        proc = subprocess.run(
            [sys.executable, str(AGENT_PATH)],
            input=json.dumps({"body": {}}),
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("TOKENS_FILE_PATH", proc.stderr)

    def test_sku_substitution(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "tokens-premium.txt").write_text("PREMIUM_KEY_1\n")
            (Path(td) / "tokens-basic.txt").write_text("BASIC_KEY_1\n")
            template = str(Path(td) / "tokens-<sku>.txt")
            env = os.environ.copy()
            env["TOKENS_FILE_PATH"] = template
            env["LOG_FILE_PATH"] = str(Path(td) / "log.txt")
            env["CALLER_ADDRESS"] = "EQ_x"
            env["CALLER_TX_HASH"] = "tx_x"

            code, out, _ = _run_agent(env, {"body": {"sku": "premium"}})
            self.assertEqual(code, 0)
            self.assertEqual(out["result"]["data"], "PREMIUM_KEY_1")

            code, out, _ = _run_agent(env, {"body": {"sku": "basic"}})
            self.assertEqual(code, 0)
            self.assertEqual(out["result"]["data"], "BASIC_KEY_1")

    def test_log_written(self):
        with tempfile.TemporaryDirectory() as td:
            tokens = Path(td) / "tokens-default.txt"
            tokens.write_text("SECRETTOKEN12345\n")
            log = Path(td) / "log.txt"
            code, out, err = _run_agent(_make_env(tokens, log), {"body": {"note": "hi"}})
            self.assertEqual(code, 0, err)
            self.assertEqual(out["result"]["data"], "SECRETTOKEN12345")
            line = log.read_text().strip()
            entry = json.loads(line)
            self.assertEqual(entry["sku"], "default")
            self.assertEqual(entry["caller_address"], "EQTEST_address")
            self.assertEqual(entry["caller_tx_hash"], "tx_test")
            # Полный токен не должен попасть в лог.
            self.assertNotIn("SECRETTOKEN12345", line)
            self.assertEqual(entry["token_preview"], "SECR...2345")
            self.assertEqual(entry["body"], {"note": "hi"})


class TestQuoteMode(unittest.TestCase):
    def test_peek_does_not_modify(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.txt"
            p.write_text("alpha\nbeta\n")
            self.assertEqual(agent._peek_first_token(p), "alpha")
            self.assertEqual(agent._peek_first_token(p), "alpha")
            self.assertEqual(p.read_text(), "alpha\nbeta\n")

    def test_peek_returns_none_on_empty(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.txt"
            p.write_text("")
            self.assertIsNone(agent._peek_first_token(p))
            p.write_text("\n\n   \n")
            self.assertIsNone(agent._peek_first_token(p))

    def test_parse_skus_env(self):
        original = os.environ.get("AGENT_SKUS")
        try:
            os.environ["AGENT_SKUS"] = "basic:infinite:ton=100000000,premium:5:ton=500000000:usd=2000000"
            self.assertEqual(agent._parse_skus_env("basic"), (100000000, None))
            self.assertEqual(agent._parse_skus_env("premium"), (500000000, 2000000))
            self.assertEqual(agent._parse_skus_env("missing"), (None, None))
        finally:
            if original is None:
                os.environ.pop("AGENT_SKUS", None)
            else:
                os.environ["AGENT_SKUS"] = original

    def test_quote_subprocess_returns_price(self):
        with tempfile.TemporaryDirectory() as td:
            tokens = Path(td) / "tokens-default.txt"
            tokens.write_text("token1\ntoken2\n")
            env = _make_env(tokens)
            env["AGENT_SKUS"] = "default:infinite:ton=123456789"
            code, out, err = _run_agent(env, {"mode": "quote", "sku": "default", "body": {}})
            self.assertEqual(code, 0, err)
            self.assertEqual(out["price"], 123456789)
            self.assertIn("plan", out)
            self.assertEqual(out["ttl"], agent.DEFAULT_QUOTE_TTL)
            # Файл не должен быть тронут (peek, не pop).
            self.assertEqual(tokens.read_text(), "token1\ntoken2\n")

    def test_quote_subprocess_fails_on_empty(self):
        with tempfile.TemporaryDirectory() as td:
            tokens = Path(td) / "tokens-default.txt"
            tokens.write_text("")
            env = _make_env(tokens)
            env["AGENT_SKUS"] = "default:infinite:ton=100"
            code, out, err = _run_agent(env, {"mode": "quote", "sku": "default", "body": {}})
            # Sidecar ожидает exit != 0 → отдаст 500 клиенту до 402.
            self.assertNotEqual(code, 0)
            self.assertIn("out_of_stock", err)

    def test_quote_subprocess_fails_without_price(self):
        with tempfile.TemporaryDirectory() as td:
            tokens = Path(td) / "tokens-default.txt"
            tokens.write_text("X\n")
            env = _make_env(tokens)
            env.pop("AGENT_SKUS", None)
            env.pop("AGENT_PRICE", None)
            env.pop("AGENT_PRICE_USD", None)
            code, _, err = _run_agent(env, {"mode": "quote", "sku": "default", "body": {}})
            self.assertNotEqual(code, 0)
            self.assertIn("no price", err)

    def test_quote_uses_usd_when_only_usd_configured(self):
        with tempfile.TemporaryDirectory() as td:
            tokens = Path(td) / "tokens-default.txt"
            tokens.write_text("X\n")
            env = _make_env(tokens)
            env["AGENT_SKUS"] = "default:infinite:usd=2000000"
            code, out, err = _run_agent(env, {"mode": "quote", "sku": "default", "body": {}})
            self.assertEqual(code, 0, err)
            self.assertEqual(out["price"], 2000000)
            self.assertEqual(out.get("price_usdt"), 2000000)

    def test_quote_per_sku_routing(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "tokens-basic.txt").write_text("B\n")
            (Path(td) / "tokens-premium.txt").write_text("")  # пусто
            env = os.environ.copy()
            env["TOKENS_FILE_PATH"] = str(Path(td) / "tokens-<sku>.txt")
            env["AGENT_SKUS"] = "basic:infinite:ton=1,premium:infinite:ton=2"

            code, out, err = _run_agent(env, {"mode": "quote", "sku": "basic", "body": {}})
            self.assertEqual(code, 0, err)
            self.assertEqual(out["price"], 1)

            code, _, err = _run_agent(env, {"mode": "quote", "sku": "premium", "body": {}})
            self.assertNotEqual(code, 0)
            self.assertIn("out_of_stock", err)


class TestConcurrency(unittest.TestCase):
    """N параллельных subprocess'ов на одном файле — каждый токен выдаётся
    максимум одному вызову, остальные получают out_of_stock."""

    def _run_concurrent(self, n_tokens: int, n_workers: int) -> list[tuple[int, dict | None]]:
        with tempfile.TemporaryDirectory() as td:
            tokens = Path(td) / "tokens-default.txt"
            log = Path(td) / "log.txt"
            tokens.write_text("\n".join(f"tok_{i:04d}" for i in range(n_tokens)) + "\n")
            env = _make_env(tokens, log)
            results: list[tuple[int, dict | None]] = [None] * n_workers  # type: ignore

            def worker(idx: int) -> None:
                code, out, _ = _run_agent(env, {"body": {}})
                results[idx] = (code, out)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_workers)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # После всех вызовов — файл должен быть чистым (никаких .tmp висящих).
            for stray in tokens.parent.glob("*.tmp"):
                self.fail(f"stray tmp file left behind: {stray}")

            # И в файле должны остаться ровно те токены, что не выдавались.
            issued = {r[1]["result"]["data"] for r in results if r[1] and "result" in r[1]}
            remaining = {ln for ln in tokens.read_text().splitlines() if ln.strip()}
            self.assertTrue(issued.isdisjoint(remaining), "issued token still in file")
            expected_remaining = max(0, n_tokens - len(issued))
            self.assertEqual(len(remaining), expected_remaining)
            return results

    def test_more_workers_than_tokens(self):
        n_tokens, n_workers = 5, 12
        results = self._run_concurrent(n_tokens, n_workers)
        successes = [r for r in results if r[1] and "result" in r[1]]
        oos = [r for r in results if r[1] and r[1].get("error") == "out_of_stock"]
        self.assertEqual(len(successes) + len(oos), n_workers)
        self.assertEqual(len(successes), n_tokens)
        # Все выданные токены уникальны.
        issued = [r[1]["result"]["data"] for r in successes]
        self.assertEqual(len(issued), len(set(issued)), "duplicate token issued!")

    def test_more_tokens_than_workers(self):
        results = self._run_concurrent(20, 8)
        successes = [r for r in results if r[1] and "result" in r[1]]
        self.assertEqual(len(successes), 8)
        issued = [r[1]["result"]["data"] for r in successes]
        self.assertEqual(len(issued), len(set(issued)))

    def test_exact_match(self):
        results = self._run_concurrent(10, 10)
        successes = [r for r in results if r[1] and "result" in r[1]]
        self.assertEqual(len(successes), 10)
        issued = {r[1]["result"]["data"] for r in successes}
        self.assertEqual(issued, {f"tok_{i:04d}" for i in range(10)})


if __name__ == "__main__":
    unittest.main()
