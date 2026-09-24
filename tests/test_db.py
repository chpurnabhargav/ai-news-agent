import datetime
import shutil
import tempfile
import unittest
from unittest import mock

import analyzer
import config
import db


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patches = [mock.patch.object(config, "DATA_DIR", self.tmp),
                   mock.patch.object(config, "DB_PATH", f"{self.tmp}/news.db")]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        db.init_db()

    def add(self, title, summary="", source="Test", hours_ago=1, kind="news"):
        published = db.utcnow().replace(microsecond=0) - datetime.timedelta(hours=hours_ago)
        return db.insert_article(title, f"https://example.com/{title}", summary, source, published,
                                 analyzer.analyze(title, summary, kind))

    def test_insert_is_idempotent_by_link(self):
        self.assertIsNotNone(self.add("OpenAI launches GPT-5.2"))
        self.assertIsNone(self.add("OpenAI launches GPT-5.2"))
        self.assertEqual(db.count_articles(), 1)

    def test_query_filters(self):
        self.add("OpenAI launches GPT-5.2", source="OpenAI", kind="official")
        self.add("AI startup raises $500 million", source="TechCrunch")
        self.add("Old news about Llama 3", hours_ago=24 * 40)
        self.assertEqual(len(db.query_articles(hours=24)), 2)
        self.assertEqual(len(db.query_articles()), 3)
        self.assertEqual([a["title"] for a in db.query_articles(category="Model Release")], ["OpenAI launches GPT-5.2"])
        self.assertEqual(len(db.query_articles(source="TechCrunch")), 1)
        self.assertEqual(len(db.query_articles(search="gpt-5.2")), 1)
        self.assertEqual(len(db.query_articles(model="GPT-5.2")), 1)
        self.assertEqual(db.query_articles(sort="top")[0]["title"], "OpenAI launches GPT-5.2")

    def test_bookmarks(self):
        article_id = self.add("Anthropic launches Claude Opus 4.5")
        db.set_bookmark(article_id, True)
        self.assertEqual(len(db.query_articles(saved_only=True)), 1)
        db.set_bookmark(article_id, False)
        self.assertEqual(db.query_articles(saved_only=True), [])

    def test_leaderboard_and_facts(self):
        self.add("Google unveils Gemini 3 Pro", "Gemini 3 Pro scores 91.9% on GPQA Diamond, ahead of GPT-5.1.")
        self.add("Gemini 3 Pro tops LMArena", "Gemini 3 Pro reached 1501 Elo on LMArena.", source="Other")
        board = {row["model"]: row for row in db.model_leaderboard()}
        self.assertEqual(board["Gemini 3 Pro"]["mentions"], 2)
        self.assertEqual(board["Gemini 3 Pro"]["sources"], 2)
        self.assertGreater(board["Gemini 3 Pro"]["release_mentions"], 0)
        self.assertEqual(board["GPT-5.1"]["release_mentions"], 0)
        self.assertEqual([r["model"] for r in db.model_leaderboard(releases_only=True)], ["Gemini 3 Pro"])
        facts = {(f["name"], f["value"]) for f in db.model_facts(["Gemini 3 Pro"])["Gemini 3 Pro"]}
        self.assertEqual(facts, {("GPQA Diamond", 91.9), ("LMArena Elo", 1501)})

    def test_feed_entries_are_filtered_analysed_and_stored(self):
        import feedparser
        import fetcher
        rss = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
            <item><title>Anthropic launches Claude Opus 4.5</title><link>https://example.com/a</link>
              <description>&lt;p&gt;Claude Opus 4.5 scores 80.9% on SWE-bench Verified.&lt;/p&gt;</description>
              <pubDate>Wed, 23 Sep 2026 10:00:00 GMT</pubDate></item>
            <item><title>The best budget laptops this fall</title><link>https://example.com/b</link></item>
        </channel></rss>"""
        source = {"name": "Tech", "kind": "general", "url": "unused"}
        self.assertEqual(fetcher._store_entries(source, feedparser.parse(rss)), 1)
        article = db.query_articles()[0]
        self.assertEqual(article["summary"], "Claude Opus 4.5 scores 80.9% on SWE-bench Verified.")
        self.assertEqual(article["published_at"], datetime.datetime(2026, 9, 23, 10, 0))
        facts = db.model_facts(["Claude Opus 4.5"])["Claude Opus 4.5"]
        self.assertEqual([(f["name"], f["value"]) for f in facts], [("SWE-bench Verified", 80.9)])

    def test_migrates_databases_from_the_first_version(self):
        conn = db.get_connection()
        conn.executescript("""
            DROP TABLE news;
            CREATE TABLE news (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, link TEXT NOT NULL UNIQUE,
                               summary TEXT, source TEXT, published_at TEXT,
                               fetched_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """)
        conn.execute("INSERT INTO news (title, link, summary, source, published_at) VALUES (?, ?, ?, ?, ?)",
                     ("Meta releases Llama 4 Maverick", "https://example.com/llama", "", "Old",
                      db.utcnow().isoformat(timespec="seconds")))
        conn.commit()
        conn.close()
        db.init_db()
        import fetcher
        self.assertEqual(fetcher.analyze_pending(), 1)
        self.assertEqual(db.query_articles()[0]["category"], "Model Release")
        self.assertEqual(db.model_leaderboard()[0]["model"], "Llama 4 Maverick")


if __name__ == "__main__":
    unittest.main()
