import datetime
import html
import logging
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import feedparser

import analyzer
import db
from config import MAX_ARTICLES_PER_SOURCE, MAX_ENRICH_PER_FETCH, REQUEST_TIMEOUT, SOURCE_KINDS, SOURCES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

USER_AGENT = "Mozilla/5.0 (compatible; AI-News-Agent/2.0; +https://github.com/chpurnabhargav/ai-news-agent)"
# Aggregator links redirect through JavaScript, so their pages have no article text.
_NO_ENRICH = ("news.google.com", "news.ycombinator.com")


def clean_summary(raw):
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:800]


def parse_published(entry):
    """Entry time as naive UTC (feedparser normalises *_parsed to UTC)."""
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime.datetime(*t[:6])
            except Exception:
                pass
    return db.utcnow().replace(microsecond=0)


def _fetch_feed(source):
    # Download with a timeout ourselves; feedparser's own fetching can hang on a stalled feed.
    request = urllib.request.Request(source["url"], headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return source, feedparser.parse(response.read(5_000_000))
    except Exception as e:
        return source, feedparser.FeedParserDict(entries=[], bozo=1, bozo_exception=e)


def _store_entries(source, feed):
    new = 0
    kind = source["kind"]
    for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:
        title = clean_summary(entry.get("title", ""))
        link = entry.get("link", "").strip()
        if not title or not link or db.article_exists(link):
            continue
        summary = clean_summary(entry.get("summary", ""))
        if kind in ("general", "community") and not analyzer.is_ai_related(title, summary):
            continue
        analysis = analyzer.analyze(title, summary, kind)
        if db.insert_article(title, link, summary, source["name"], parse_published(entry), analysis):
            new += 1
    return new


def fetch_all(progress=None):
    """Fetch every feed, analyse new stories, then enrich model releases. Returns new article count."""
    def report(message):
        logging.info(message)
        if progress:
            progress(message)

    analyze_pending()
    total_new = 0
    report(f"Fetching {len(SOURCES)} feeds...")
    with ThreadPoolExecutor(max_workers=8) as pool:
        for source, feed in pool.map(_fetch_feed, SOURCES):
            try:
                if feed.get("bozo") and not feed.entries:
                    raise RuntimeError(feed.get("bozo_exception") or "no entries")
                new = _store_entries(source, feed)
                total_new += new
                logging.info(f"{source['name']}: {len(feed.entries)} entries, {new} new")
            except Exception as e:
                logging.error(f"Failed {source['name']}: {e}")

    enriched = enrich_releases(report)
    report(f"Done. {total_new} new articles, {enriched} release write-ups scanned for benchmarks.")
    return total_new


def analyze_pending():
    """Analyse articles stored by older versions of the app."""
    pending = db.get_unanalyzed()
    for row in pending:
        kind = SOURCE_KINDS.get(row["source"], "news")
        db.save_analysis(row["id"], analyzer.analyze(row["title"], row["summary"] or "", kind))
    if pending:
        logging.info(f"Analysed {len(pending)} previously stored articles")
    return len(pending)


# ---------------------------------------------------------------------------
# Full-text enrichment for model releases
# ---------------------------------------------------------------------------

def extract_text(page):
    page = re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header|aside|form)\b.*?</\1>", " ", page)
    blocks = re.findall(r"(?is)<(?:p|li|h[1-4]|td|th|figcaption)\b[^>]*>(.*?)</(?:p|li|h[1-4]|td|th|figcaption)>", page)
    lines = []
    for block in blocks:
        text = html.unescape(re.sub(r"<[^>]+>", " ", block))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 25:
            lines.append(text if text.endswith((".", "!", "?", ":")) else text + ".")
    return "\n".join(lines)


def download_text(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        if "html" not in response.headers.get("Content-Type", "html"):
            return ""
        charset = response.headers.get_content_charset() or "utf-8"
        page = response.read(3_000_000).decode(charset, errors="replace")
    return extract_text(page)


def _enrich(article):
    try:
        return article, download_text(article["link"])
    except Exception as e:
        logging.info(f"Could not download {article['link']}: {e}")
        return article, ""


def enrich_releases(report=None):
    articles = db.get_articles_to_enrich(MAX_ENRICH_PER_FETCH, _NO_ENRICH)
    if not articles:
        return 0
    if report:
        report(f"Reading {len(articles)} model-release articles for benchmarks and specs...")
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_enrich, articles))
    for article, text in results:
        text = text[:40_000]
        score = None
        if text:
            title_models = analyzer.detect_models(article["title"])
            primary = title_models[0] if title_models else None
            facts = analyzer.extract_facts(text, primary)
            db.add_facts(article["id"], facts)
            benchmarks = len({(f["model"], f["name"]) for f in facts if f["kind"] == "benchmark"})
            score = min(100.0, article["score"] + min(benchmarks, 5) * 2)
        db.set_content(article["id"], text, score)
    return sum(1 for _, text in results if text)


if __name__ == "__main__":
    db.init_db()
    fetch_all()
