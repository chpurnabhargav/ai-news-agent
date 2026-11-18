import json
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

import ai_brief
import analyzer
import config
import db


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


def message(stop_reason, text):
    return types.SimpleNamespace(stop_reason=stop_reason, content=[types.SimpleNamespace(type="text", text=text)])


class AiBriefTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for patch in (mock.patch.object(config, "DATA_DIR", self.tmp),
                      mock.patch.object(config, "DB_PATH", f"{self.tmp}/news.db")):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        db.init_db()
        title, summary = "OpenAI launches GPT-5.2", "GPT-5.2 scores 80.1% on SWE-bench Verified."
        db.insert_article(title, "https://example.com/gpt", summary, "OpenAI", db.utcnow(),
                          analyzer.analyze(title, summary, "official"))

    def test_context_includes_extracted_figures_and_coverage(self):
        context = ai_brief.build_context(["GPT-5.2", "Claude Opus 4.5"])
        self.assertIn("GPT-5.2 | SWE-bench Verified: 80.1%", context)
        self.assertIn("Claude Opus 4.5: none extracted", context)
        self.assertIn("## OpenAI launches GPT-5.2", context)

    def test_generate_resumes_paused_turns_and_caches_the_brief(self):
        calls = []
        replies = [message("pause_turn", ""), message("end_turn", "## At a glance\n| a | b |")]

        def stream(**kwargs):
            calls.append(kwargs)
            return FakeStream(replies[len(calls) - 1])

        client = types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(stream=stream)))
        fake_sdk = types.SimpleNamespace(Anthropic=lambda: client)
        with mock.patch.dict(sys.modules, {"anthropic": fake_sdk}):
            text = ai_brief.generate_comparison(["GPT-5.2"])

        self.assertEqual(text, "## At a glance\n| a | b |")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["model"], config.BRIEF_MODEL)
        self.assertEqual(calls[0]["tools"][0]["type"], "web_search_20260209")
        self.assertEqual(calls[1]["messages"][-1]["role"], "assistant")
        self.assertEqual(db.get_brief(ai_brief.brief_key(["GPT-5.2"]))["text"], text)

    def test_must_know_digest_is_generated_and_cached(self):
        article = db.query_articles()[0]
        picks = [{"lead": article, "duplicates": [], "sources": [article["source"]], "importance": 80}]
        calls = []
        answer = json.dumps({
            "bottom_line": "One big launch today.",
            "must_know": [{"id": article["id"], "what": "OpenAI released GPT-5.2.", "why": "Better coding."}],
            "gists": [{"id": 999, "gist": "Other story."}, {"id": 1000, "gist": ""}],
        })

        def stream(**kwargs):
            calls.append(kwargs)
            return FakeStream(message("end_turn", answer))

        client = types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(stream=stream)))
        with mock.patch.dict(sys.modules, {"anthropic": types.SimpleNamespace(Anthropic=lambda: client)}):
            digest = ai_brief.generate_must_know(picks, [])

        request = calls[0]
        self.assertEqual(request["model"], config.BRIEF_MODEL)
        self.assertEqual(request["output_config"]["format"]["type"], "json_schema")
        self.assertIn(f"## id {article['id']}: OpenAI launches GPT-5.2", request["messages"][0]["content"])
        self.assertIn("GPT-5.2 SWE-bench Verified 80.1%", request["messages"][0]["content"])
        self.assertEqual(digest["bottom_line"], "One big launch today.")
        self.assertEqual(digest["items"][article["id"]]["why"], "Better coding.")
        self.assertEqual(digest["gists"], {999: "Other story."})
        self.assertEqual(ai_brief.get_must_know_digest()["bottom_line"], "One big launch today.")

    def test_must_know_rejects_truncated_answers(self):
        client = types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(
            stream=lambda **kwargs: FakeStream(message("max_tokens", "{")))))
        with mock.patch.dict(sys.modules, {"anthropic": types.SimpleNamespace(Anthropic=lambda: client)}):
            with self.assertRaises(RuntimeError):
                ai_brief.generate_must_know([], [])
        self.assertIsNone(ai_brief.get_must_know_digest())

    def test_refusal_raises(self):
        client = types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(
            stream=lambda **kwargs: FakeStream(message("refusal", "")))))
        with mock.patch.dict(sys.modules, {"anthropic": types.SimpleNamespace(Anthropic=lambda: client)}):
            with self.assertRaises(RuntimeError):
                ai_brief.generate_comparison(["GPT-5.2"])


if __name__ == "__main__":
    unittest.main()
