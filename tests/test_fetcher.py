import unittest

from fetcher import clean_summary, parse_published


class FetcherTests(unittest.TestCase):
    def test_clean_summary_removes_markup_and_limits_length(self):
        result = clean_summary("<p>Hello&nbsp;world</p>")
        self.assertEqual(result, "Hello&nbsp;world")
        self.assertLessEqual(len(clean_summary("x" * 1000)), 800)

    def test_parse_published_uses_published_time(self):
        entry = {"published_parsed": (2026, 8, 23, 12, 30, 0)}
        self.assertEqual(parse_published(entry).year, 2026)
        self.assertEqual(parse_published(entry).hour, 12)


if __name__ == "__main__":
    unittest.main()