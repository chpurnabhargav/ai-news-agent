import datetime
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

    def test_merges_launch_coverage_worded_differently(self):
        articles = [
            {"title": "Introducing GPT-5.5: faster reasoning and better coding", "models": ["GPT-5.5"],
             "is_release": True},
            {"title": "OpenAI launches GPT-5.5 with a big jump in coding scores", "models": ["GPT-5.5", "GPT-5.2"],
             "is_release": True},
            {"title": "OpenAI releases GPT-5.5 - Reuters", "models": ["GPT-5.5"], "is_release": True},
            {"title": "GPT-5.5 system card", "models": ["GPT-5.5"], "is_release": False},
        ]
        clusters = analyzer.cluster_articles(articles)
        self.assertEqual([len(dupes) for _, dupes in clusters], [2, 0])

    def test_merges_headlines_naming_the_same_things(self):
        articles = [
            {"title": "EU begins enforcing AI Act obligations for frontier model makers", "models": []},
            {"title": "The EU AI Act's rules for general-purpose models start to bite", "models": []},
            {"title": "EU fines a social network over data transfers", "models": []},
        ]
        clusters = analyzer.cluster_articles(articles)
        self.assertEqual([len(dupes) for _, dupes in clusters], [1, 0])


class GistTests(unittest.TestCase):
    def test_uses_whole_sentences_and_drops_boilerplate(self):
        summary = ("SAN FRANCISCO (Reuters) - OpenAI on Tuesday released GPT-5.5, a model it says is better at "
                   "coding. It scores 82% on SWE-bench Verified. The post OpenAI launches GPT-5.5 appeared first "
                   "on Example News.")
        self.assertEqual(analyzer.make_gist("OpenAI launches GPT-5.5", summary),
                         "OpenAI on Tuesday released GPT-5.5, a model it says is better at coding. "
                         "It scores 82% on SWE-bench Verified.")

    def test_headline_only_summaries_have_no_gist(self):
        self.assertEqual(analyzer.make_gist("Nvidia earnings beat - Reuters", "Nvidia earnings beat - Reuters  Reuters"),
                         "")
        hn = "Article URL: https://example.com Comments URL: https://news.ycombinator.com/item?id=1 Points: 9"
        self.assertEqual(analyzer.make_gist("Show HN: a tool", hn), "")

    def test_falls_back_to_article_text(self):
        content = ("Subscribe to our newsletter.\n"
                   "The new model can summarise long reports and answer questions about them in seconds.\n")
        self.assertEqual(analyzer.make_gist("A new model", "", content),
                         "The new model can summarise long reports and answer questions about them in seconds.")

    def test_short_gist_keeps_whole_sentences(self):
        gist = "First sentence is here. Second sentence is a little longer than the first one."
        self.assertEqual(analyzer.short_gist(gist, 30), "First sentence is here.")
        self.assertEqual(analyzer.short_gist(gist, 500), gist)
        self.assertTrue(analyzer.short_gist("x" * 50 + " word " * 20, 40).endswith("…"))

    def test_analysis_includes_a_gist(self):
        analysis = analyzer.analyze("Meta releases Llama 5", "Meta released Llama 5 today under an open license.")
        self.assertEqual(analysis["gist"], "Meta released Llama 5 today under an open license.")


class MustKnowTests(unittest.TestCase):
    NOW = datetime.datetime(2026, 11, 18, 12, 0)

    def story(self, title, score, category="General", hours=2, source="News", **extra):
        return dict(title=title, score=score, category=category, source=source,
                    published_at=self.NOW - datetime.timedelta(hours=hours), **extra)

    def test_ranks_by_importance_with_a_topic_cap_and_a_floor(self):
        releases = [(self.story(f"Release {i}", 70 - i, "Model Release"), []) for i in range(5)]
        clusters = releases + [
            (self.story("Startup raises $2 billion", 17, "Business & Funding"), []),
            (self.story("A practical guide", 12, "Products & Tools"), []),
        ]
        picks = analyzer.pick_must_know(clusters, self.NOW)
        self.assertEqual([p["lead"]["title"] for p in picks],
                         ["Release 0", "Release 1", "Release 2", "Startup raises $2 billion"])

    def test_wide_coverage_and_recency_raise_importance(self):
        lead = self.story("Story", 30)
        self.assertGreater(analyzer.importance(lead, 4, 2), analyzer.importance(lead, 1, 2))
        self.assertLess(analyzer.importance(lead, 1, 96), analyzer.importance(lead, 1, 2))

    def test_sources_are_distinct_and_lead_first(self):
        lead = self.story("A", 10, source="OpenAI")
        dupes = [self.story("B", 5, source="The Verge"), self.story("C", 5, source="OpenAI")]
        self.assertEqual(analyzer.story_sources(lead, dupes), ["OpenAI", "The Verge"])

    def test_why_it_matters_explains_a_release(self):
        lead = self.story("OpenAI launches GPT-5.5", 80, "Model Release", source="OpenAI", is_release=True)
        facts = [{"model": "GPT-5.5", "kind": "benchmark", "name": "SWE-bench Verified", "value": 82.4, "unit": "%"},
                 {"model": "GPT-5.5", "kind": "context", "name": "Context window", "value": 1e6, "unit": "tokens"}]
        reasons = analyzer.why_it_matters(lead, ["OpenAI", "The Verge"], facts, "official")
        self.assertEqual(reasons, [
            "New model release from OpenAI: GPT-5.5",
            "Official announcement from OpenAI",
            "Covered by 2 outlets (OpenAI, The Verge)",
            "Reported benchmark scores: SWE-bench Verified 82.4%",
        ])

    def test_why_it_matters_mentions_money_and_topic(self):
        lead = self.story("Chip startup raises $2 billion at a $30 billion valuation", 17, "Business & Funding")
        self.assertEqual(analyzer.why_it_matters(lead, ["TechCrunch"]), [
            "Money involved: $2 billion and $30 billion",
            "Money and deals that shape which AI companies lead",
        ])

    def test_fact_text_does_not_repeat_units(self):
        fact = {"model": "Gemini 3.5 Pro", "kind": "benchmark", "name": "LMArena Elo", "value": 1532.0, "unit": "Elo"}
        self.assertEqual(analyzer.fact_text(fact), "LMArena Elo 1532")
        self.assertEqual(analyzer.fact_text(fact, with_model=True), "Gemini 3.5 Pro · LMArena Elo 1532")


if __name__ == "__main__":
    unittest.main()
