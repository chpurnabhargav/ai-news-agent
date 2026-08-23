import os


def _data_dir():
    configured = os.getenv("AI_NEWS_AGENT_DATA_DIR")
    if configured:
        return configured
    if os.name == "nt":
        return os.path.join(os.getenv("LOCALAPPDATA", os.path.expanduser("~")), "AI News Agent")
    return os.path.join(
        os.getenv("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share")),
        "ai-news-agent",
    )


DATA_DIR = _data_dir()
DB_PATH = os.path.join(DATA_DIR, "news.db")

MAX_ARTICLES_PER_SOURCE = 25

SOURCES = [
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
    ("MIT Tech Review", "https://www.technologyreview.com/topic/artificial-intelligence/feed/"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("Google News AI", "https://news.google.com/rss/search?q=artificial+intelligence&hl=en-US&gl=US&ceid=US:en"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
    ("Wired AI", "https://www.wired.com/feed/tag/ai/latest/rss"),
]
