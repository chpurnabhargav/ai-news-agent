import unittest

import analyzer


def names(models):
    return [m["name"] for m in models]


def facts_by_key(facts):
    return {(f["model"], f["name"]): f["value"] for f in facts}


class ModelDetectionTests(unittest.TestCase):
    def test_detects_and_normalises_common_families(self):
        text = ("Meta ships Llama 4 Maverick; OpenAI's o3-mini and GPT-4o mini; Claude 3.5 Sonnet, "
                "Claude Opus 4.5, Gemini 2.5 Pro, DeepSeek-V3.2-Exp, Qwen3-Max, Grok 4 Heavy and Kimi K2.")
        found = names(analyzer.detect_models(text))
        for expected in ("Llama 4 Maverick", "o3-mini", "GPT-4o mini", "Claude Sonnet 3.5", "Claude Opus 4.5",
                         "Gemini 2.5 Pro", "DeepSeek-V3.2-Exp", "Qwen3-Max", "Grok 4 Heavy", "Kimi K2"):
            self.assertIn(expected, found)

    def test_requires_version_or_context(self):
        self.assertEqual(analyzer.detect_models("I asked Claude and Gemini about the weather"), [])
        # "o3" without an OpenAI context is not treated as a model
        self.assertEqual(analyzer.detect_models("Ozone (o3) levels rose in the city"), [])

    def test_most_mentioned_model_comes_first(self):
        text = "Gemini 3 Pro beats GPT-5.1. Gemini 3 Pro is available today."
        self.assertEqual(names(analyzer.detect_models(text))[0], "Gemini 3 Pro")


class FactExtractionTests(unittest.TestCase):
    def test_benchmarks_attach_to_the_right_model(self):
        text = ("GPT-5.2 scores 80.1% on SWE-bench Verified, while Claude Opus 4.5 hit 80.9%. "
                "GPT-5.2 also reaches 93.2% on GPQA Diamond. Gemini 3 Pro reached 1501 Elo on LMArena.")
        facts = facts_by_key(analyzer.extract_facts(text))
        self.assertEqual(facts[("GPT-5.2", "SWE-bench Verified")], 80.1)
        self.assertEqual(facts[("GPT-5.2", "GPQA Diamond")], 93.2)
        self.assertEqual(facts[("Claude Opus 4.5", "SWE-bench Verified")], 80.9)
        self.assertEqual(facts[("Gemini 3 Pro", "LMArena Elo")], 1501)

    def test_context_window_and_prices(self):
        text = ("Claude Opus 4.5 is priced at $5/$25 per million tokens. "
                "It has a 200K-token context window. DeepSeek-V3.2 costs $0.28 per million input tokens "
                "and $0.42 per million output tokens.")
        facts = facts_by_key(analyzer.extract_facts(text))
        self.assertEqual(facts[("Claude Opus 4.5", "Input price")], 5)
        self.assertEqual(facts[("Claude Opus 4.5", "Output price")], 25)
        self.assertEqual(facts[("Claude Opus 4.5", "Context window")], 200_000)
        self.assertEqual(facts[("DeepSeek-V3.2", "Input price")], 0.28)
        self.assertEqual(facts[("DeepSeek-V3.2", "Output price")], 0.42)

    def test_primary_model_is_used_when_sentence_names_none(self):
        primary = analyzer.detect_models("Qwen3-Max")[0]
        facts = analyzer.extract_facts("The model scores 88.5% on MMLU-Pro.", primary)
        self.assertEqual(facts_by_key(facts), {("Qwen3-Max", "MMLU-Pro"): 88.5})

    def test_ignores_impossible_percentages(self):
        self.assertEqual(analyzer.extract_facts("GPT-5.2 scores 180% on MMLU"), [])

    def test_format_fact_value(self):
        self.assertEqual(analyzer.format_fact_value("context", 1_000_000, "tokens"), "1M tokens")
        self.assertEqual(analyzer.format_fact_value("context", 128_000, "tokens"), "128K tokens")
        self.assertEqual(analyzer.format_fact_value("price_in", 1.25, "$/1M tokens"), "$1.25 / 1M")
        self.assertEqual(analyzer.format_fact_value("benchmark", 80.1, "%"), "80.1%")


class ClassificationTests(unittest.TestCase):
    def test_release_headline(self):
        result = analyzer.analyze("OpenAI launches GPT-5.2, beating Claude Opus 4.5 on coding benchmarks", "", "news")
        self.assertEqual(result["category"], "Model Release")
        self.assertTrue(result["is_release"])
        released = {m["name"]: m["released"] for m in result["models"]}
        self.assertEqual(released, {"GPT-5.2": True, "Claude Opus 4.5": True})

    def test_comparator_models_are_not_marked_released(self):
        result = analyzer.analyze("Google unveils Gemini 3 Pro", "It beats GPT-5.1 on most tests.", "news")
        released = {m["name"]: m["released"] for m in result["models"]}
        self.assertEqual(released, {"Gemini 3 Pro": True, "GPT-5.1": False})

    def test_topics(self):
        self.assertEqual(analyzer.classify("AI startup raises $500 million at $10 billion valuation")[0],
                         "Business & Funding")
        self.assertEqual(analyzer.classify("EU regulators open antitrust probe into AI deals")[0], "Policy & Safety")
        self.assertEqual(analyzer.classify("Nvidia's new GPU chips head to data centers")[0], "Hardware & Chips")
        self.assertEqual(analyzer.classify("A quiet week")[0], "General")

    def test_ai_filter_for_general_feeds(self):
        self.assertTrue(analyzer.is_ai_related("Microsoft adds AI agents to Windows"))
        self.assertTrue(analyzer.is_ai_related("Hands-on with Llama 4 Scout"))
        self.assertFalse(analyzer.is_ai_related("Review: the best mechanical keyboards of the year"))

    def test_release_scores_higher_than_general_news(self):
        release = analyzer.analyze("OpenAI launches GPT-5.2", "GPT-5.2 scores 80.1% on SWE-bench Verified.", "official")
        other = analyzer.analyze("Microsoft adds new Copilot features to Windows", "", "news")
        self.assertGreater(release["score"], other["score"])


class ClusterTests(unittest.TestCase):
    def test_merges_same_story_from_different_outlets(self):
        articles = [
            {"title": "OpenAI launches GPT-5.2 - The Verge", "models": ["GPT-5.2"]},
            {"title": "GPT-5.2 is here: OpenAI launches its new model", "models": ["GPT-5.2"]},
            {"title": "Nvidia earnings beat expectations", "models": []},
        ]
        clusters = analyzer.cluster_articles(articles)
        self.assertEqual(len(clusters), 2)
        self.assertEqual(len(clusters[0][1]), 1)


if __name__ == "__main__":
    unittest.main()
