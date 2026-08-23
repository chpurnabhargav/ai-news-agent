import datetime
import os
import sqlite3

from config import DATA_DIR, DB_PATH


def get_connection():
    os.makedirs(DATA_DIR, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            link TEXT NOT NULL UNIQUE,
            summary TEXT,
            source TEXT,
            published_at TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def article_exists(link):
    conn = get_connection()
    exists = conn.execute("SELECT 1 FROM news WHERE link = ? LIMIT 1", (link,)).fetchone() is not None
    conn.close()
    return exists


def insert_article(title, link, summary, source, published_at):
    conn = get_connection()
    conn.execute(
        """
        INSERT OR IGNORE INTO news (title, link, summary, source, published_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (title, link, summary, source, published_at.isoformat()),
    )
    conn.commit()
    conn.close()


def get_news_for_date(date):
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT title, link, summary, source, published_at, fetched_at
        FROM news
        WHERE date(fetched_at) = date(?)
        ORDER BY published_at DESC, id DESC
        """,
        (date,),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        article = dict(row)
        article["published_at"] = (
            datetime.datetime.fromisoformat(article["published_at"])
            if article["published_at"]
            else None
        )
        result.append(article)
    return result


def get_available_dates():
    conn = get_connection()
    rows = conn.execute("SELECT DISTINCT date(fetched_at) FROM news ORDER BY 1 DESC").fetchall()
    conn.close()
    return [r[0] for r in rows]


def count_articles():
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    conn.close()
    return n
