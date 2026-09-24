import datetime
import json
import os
import sqlite3

import config

# Columns added after the first release; init_db() adds any that are missing so
# existing databases keep working.
_NEWS_COLUMNS = {
    "category": "TEXT",
    "tags": "TEXT",
    "models": "TEXT",
    "score": "REAL DEFAULT 0",
    "is_release": "INTEGER DEFAULT 0",
    "content": "TEXT",
    "bookmarked": "INTEGER DEFAULT 0",
    "analyzed": "INTEGER DEFAULT 0",
}

_ARTICLE_FIELDS = (
    "id, title, link, summary, source, published_at, fetched_at, category, tags, models, "
    "score, is_release, bookmarked"
)


def get_connection():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    connection = sqlite3.connect(config.DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _cutoff(hours):
    if hours is None:
        return "0000"
    return (utcnow() - datetime.timedelta(hours=hours)).isoformat(timespec="seconds")


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
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(news)")}
    for column, definition in _NEWS_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE news ADD COLUMN {column} {definition}")
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_news_published ON news(published_at);
        CREATE TABLE IF NOT EXISTS article_models (
            article_id INTEGER NOT NULL REFERENCES news(id) ON DELETE CASCADE,
            model TEXT NOT NULL,
            family TEXT,
            developer TEXT,
            released INTEGER DEFAULT 0,
            PRIMARY KEY (article_id, model)
        );
        CREATE INDEX IF NOT EXISTS idx_article_models_model ON article_models(model);
        CREATE TABLE IF NOT EXISTS model_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL REFERENCES news(id) ON DELETE CASCADE,
            model TEXT NOT NULL,
            family TEXT,
            developer TEXT,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT,
            UNIQUE (article_id, model, kind, name, value)
        );
        CREATE INDEX IF NOT EXISTS idx_model_facts_model ON model_facts(model);
        CREATE TABLE IF NOT EXISTS briefs (
            key TEXT PRIMARY KEY,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            text TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def article_exists(link):
    conn = get_connection()
    exists = conn.execute("SELECT 1 FROM news WHERE link = ? LIMIT 1", (link,)).fetchone() is not None
    conn.close()
    return exists


def insert_article(title, link, summary, source, published_at, analysis=None):
    """Insert an article and its analysis. Returns the new id, or None if the link exists."""
    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO news (title, link, summary, source, published_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (title, link, summary, source, published_at.isoformat(timespec="seconds")),
    )
    article_id = cursor.lastrowid if cursor.rowcount else None
    if article_id and analysis:
        _save_analysis(conn, article_id, analysis)
    conn.commit()
    conn.close()
    return article_id


def _save_analysis(conn, article_id, analysis):
    conn.execute(
        """
        UPDATE news SET category = ?, tags = ?, models = ?, score = ?, is_release = ?, analyzed = 1
        WHERE id = ?
        """,
        (
            analysis["category"],
            json.dumps(analysis["tags"]),
            json.dumps([m["name"] for m in analysis["models"]]),
            analysis["score"],
            int(analysis["is_release"]),
            article_id,
        ),
    )
    conn.execute("DELETE FROM article_models WHERE article_id = ?", (article_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO article_models (article_id, model, family, developer, released) VALUES (?, ?, ?, ?, ?)",
        [(article_id, m["name"], m["family"], m["developer"], int(m.get("released", False)))
         for m in analysis["models"]],
    )
    add_facts(article_id, analysis["facts"], conn=conn)


def save_analysis(article_id, analysis):
    conn = get_connection()
    _save_analysis(conn, article_id, analysis)
    conn.commit()
    conn.close()


def add_facts(article_id, facts, conn=None):
    own = conn is None
    conn = conn or get_connection()
    conn.executemany(
        """
        INSERT OR IGNORE INTO model_facts (article_id, model, family, developer, kind, name, value, unit)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (article_id, f["model"], f["family"], f["developer"], f["kind"], f["name"], f["value"], f["unit"])
            for f in facts
        ],
    )
    if own:
        conn.commit()
        conn.close()


def set_content(article_id, content, score=None):
    conn = get_connection()
    if score is None:
        conn.execute("UPDATE news SET content = ? WHERE id = ?", (content, article_id))
    else:
        conn.execute("UPDATE news SET content = ?, score = ? WHERE id = ?", (content, score, article_id))
    conn.commit()
    conn.close()


def set_bookmark(article_id, bookmarked):
    conn = get_connection()
    conn.execute("UPDATE news SET bookmarked = ? WHERE id = ?", (int(bookmarked), article_id))
    conn.commit()
    conn.close()


def save_brief(key, text):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO briefs (key, text) VALUES (?, ?)", (key, text))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def _article(row):
    article = dict(row)
    article["published_at"] = (
        datetime.datetime.fromisoformat(article["published_at"]) if article["published_at"] else None
    )
    article["tags"] = json.loads(article["tags"]) if article.get("tags") else []
    article["models"] = json.loads(article["models"]) if article.get("models") else []
    article["category"] = article.get("category") or "General"
    return article


def get_unanalyzed():
    conn = get_connection()
    rows = conn.execute("SELECT id, title, summary, source FROM news WHERE analyzed = 0 OR analyzed IS NULL").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_articles_to_enrich(limit, skip_domains=()):
    conn = get_connection()
    rows = conn.execute(
        f"""
        SELECT {_ARTICLE_FIELDS} FROM news
        WHERE is_release = 1 AND content IS NULL AND published_at >= ?
        ORDER BY score DESC, published_at DESC
        """,
        (_cutoff(24 * 7),),
    ).fetchall()
    conn.close()
    articles = [_article(r) for r in rows if not any(d in r["link"] for d in skip_domains)]
    return articles[:limit]


def query_articles(hours=None, category=None, source=None, search=None, saved_only=False,
                   model=None, sort="top", limit=None):
    sql = f"SELECT {_ARTICLE_FIELDS} FROM news WHERE published_at >= ?"
    params = [_cutoff(hours)]
    if category and category != "All":
        sql += " AND (category = ? OR tags LIKE ?)"
        params += [category, f'%"{category}"%']
    if source and source != "All":
        sql += " AND source = ?"
        params.append(source)
    if search:
        sql += " AND (title LIKE ? OR summary LIKE ? OR models LIKE ?)"
        params += [f"%{search}%"] * 3
    if saved_only:
        sql += " AND bookmarked = 1"
    if model:
        sql += " AND id IN (SELECT article_id FROM article_models WHERE model = ?)"
        params.append(model)
    sql += " ORDER BY score DESC, published_at DESC" if sort == "top" else " ORDER BY published_at DESC, score DESC"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    conn = get_connection()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_article(r) for r in rows]


def get_sources(hours=None):
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT source FROM news WHERE published_at >= ? ORDER BY source", (_cutoff(hours),)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def category_counts(hours=None):
    conn = get_connection()
    rows = conn.execute(
        "SELECT COALESCE(category, 'General'), COUNT(*) FROM news WHERE published_at >= ? GROUP BY 1",
        (_cutoff(hours),),
    ).fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


def model_leaderboard(hours=24 * 30, releases_only=False, limit=None):
    """Models mentioned in the window with coverage stats, newest releases first."""
    sql = """
        SELECT am.model, am.family, am.developer,
               COUNT(*) AS mentions,
               COUNT(DISTINCT n.source) AS sources,
               SUM(am.released) AS release_mentions,
               MIN(n.published_at) AS first_seen,
               MAX(n.published_at) AS last_seen,
               MAX(n.score) AS top_score
        FROM article_models am JOIN news n ON n.id = am.article_id
        WHERE n.published_at >= ?
        GROUP BY am.model
    """
    if releases_only:
        sql += " HAVING SUM(am.released) > 0"
    sql += " ORDER BY (SUM(am.released) > 0) DESC, MAX(n.published_at) DESC, COUNT(*) DESC"
    params = [_cutoff(hours)]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    conn = get_connection()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    result = []
    for row in rows:
        item = dict(row)
        for key in ("first_seen", "last_seen"):
            item[key] = datetime.datetime.fromisoformat(item[key]) if item[key] else None
        result.append(item)
    return result


def known_models():
    conn = get_connection()
    rows = conn.execute(
        "SELECT model, COUNT(*) FROM article_models GROUP BY model ORDER BY COUNT(*) DESC"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def model_info(models):
    """Family/developer for each model name."""
    if not models:
        return {}
    conn = get_connection()
    rows = conn.execute(
        f"SELECT DISTINCT model, family, developer FROM article_models WHERE model IN ({','.join('?' * len(models))})",
        list(models),
    ).fetchall()
    conn.close()
    return {r["model"]: dict(r) for r in rows}


def model_facts(models):
    """Facts per model: {model: [fact, ...]} with the source article attached."""
    if not models:
        return {}
    conn = get_connection()
    rows = conn.execute(
        f"""
        SELECT f.model, f.kind, f.name, f.value, f.unit, n.title, n.link, n.source, n.published_at
        FROM model_facts f JOIN news n ON n.id = f.article_id
        WHERE f.model IN ({','.join('?' * len(models))})
        ORDER BY n.published_at DESC
        """,
        list(models),
    ).fetchall()
    conn.close()
    facts = {m: [] for m in models}
    for row in rows:
        facts[row["model"]].append(dict(row))
    return facts


def get_brief(key):
    conn = get_connection()
    row = conn.execute("SELECT text, created_at FROM briefs WHERE key = ?", (key,)).fetchone()
    conn.close()
    return dict(row) if row else None


def count_articles():
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    conn.close()
    return n


def stats(hours=24):
    conn = get_connection()
    cutoff = _cutoff(hours)
    row = conn.execute(
        """
        SELECT COUNT(*) AS articles,
               COUNT(DISTINCT source) AS sources,
               COALESCE(SUM(is_release), 0) AS releases,
               MAX(fetched_at) AS last_fetch
        FROM news WHERE published_at >= ?
        """,
        (cutoff,),
    ).fetchone()
    models = conn.execute(
        """
        SELECT COUNT(DISTINCT am.model) FROM article_models am JOIN news n ON n.id = am.article_id
        WHERE n.published_at >= ?
        """,
        (cutoff,),
    ).fetchone()[0]
    last_fetch = conn.execute("SELECT MAX(fetched_at) FROM news").fetchone()[0]
    conn.close()
    result = dict(row)
    result["models"] = models
    result["last_fetch"] = datetime.datetime.fromisoformat(last_fetch) if last_fetch else None
    return result


def get_article_content(article_id):
    conn = get_connection()
    row = conn.execute("SELECT content FROM news WHERE id = ?", (article_id,)).fetchone()
    conn.close()
    return row[0] if row else None
