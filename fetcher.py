import datetime
import logging
import re

import feedparser

from config import SOURCES, MAX_ARTICLES_PER_SOURCE
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def clean_summary(raw):
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:800]


def parse_published(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime.datetime(*t[:6])
            except Exception:
                pass
    return datetime.datetime.now()


def fetch_all():
    total_new = 0
    for source, url in SOURCES:
        try:
            feed = feedparser.parse(url, agent="AI-News-Agent/1.0")
            for entry in feed.entries[:MAX_ARTICLES_PER_SOURCE]:
                title = getattr(entry, "title", "").strip()
                link = getattr(entry, "link", "").strip()
                if not title or not link:
                    continue
                if db.article_exists(link):
                    continue
                summary = clean_summary(getattr(entry, "summary", ""))
                published = parse_published(entry)
                db.insert_article(title, link, summary, source, published)
                total_new += 1
            logging.info(f"{source}: {len(feed.entries)} entries, new so far {total_new}")
        except Exception as e:
            logging.error(f"Failed {source}: {e}")
    logging.info(f"Done. New articles stored: {total_new}")
    return total_new


if __name__ == "__main__":
    db.init_db()
    fetch_all()
