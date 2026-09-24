import unittest

from fetcher import clean_summary, extract_text, parse_published


class FetcherTests(unittest.TestCase):
    def test_clean_summary_removes_markup_and_limits_length(self):
        self.assertEqual(clean_summary("<p>Hello&nbsp;<b>world</b> &amp; friends</p>"), "Hello world & friends")
        self.assertLessEqual(len(clean_summary("x" * 1000)), 800)

    def test_parse_published_uses_published_time(self):
        entry = {"published_parsed": (2026, 8, 23, 12, 30, 0)}
        self.assertEqual(parse_published(entry).year, 2026)
        self.assertEqual(parse_published(entry).hour, 12)

    def test_extract_text_keeps_paragraphs_and_drops_scripts(self):
        page = """
            <html><head><script>var x = "GPT-9 scores 99% on MMLU";</script></head>
            <body><nav><p>Home | About | Subscribe to our newsletter today</p></nav>
            <p>GPT-5.2 scores 80.1% on <b>SWE-bench Verified</b> in our testing</p>
            <li>Context window of 400,000 tokens for every tier.</li></body></html>
        """
        text = extract_text(page)
        self.assertIn("GPT-5.2 scores 80.1% on SWE-bench Verified in our testing.", text)
        self.assertIn("400,000 tokens", text)
        self.assertNotIn("GPT-9", text)
        self.assertNotIn("newsletter", text)


if __name__ == "__main__":
    unittest.main()
