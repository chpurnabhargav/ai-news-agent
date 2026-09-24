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

    def test_refusal_raises(self):
        client = types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(
            stream=lambda **kwargs: FakeStream(message("refusal", "")))))
        with mock.patch.dict(sys.modules, {"anthropic": types.SimpleNamespace(Anthropic=lambda: client)}):
            with self.assertRaises(RuntimeError):
                ai_brief.generate_comparison(["GPT-5.2"])


if __name__ == "__main__":
    unittest.main()
