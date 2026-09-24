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

# How many model-release articles to download in full per fetch. The full text
# is where benchmark tables, context windows and prices usually live.
MAX_ENRICH_PER_FETCH = 15
REQUEST_TIMEOUT = 12

# Optional: Claude writes comparison briefs when an Anthropic API key is set
# (ANTHROPIC_API_KEY, or an `ant auth login` profile). Everything else works offline.
CLAUDE_MODEL = os.getenv("AI_NEWS_AGENT_CLAUDE_MODEL", "claude-opus-5")

_GOOGLE_NEWS = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="

# kind:
#   official  - AI lab / vendor blogs, weighted higher when ranking
#   news      - AI-focused news desks
#   general   - broad tech feeds; only AI-related stories are kept
#   community - aggregators and practitioner blogs; only AI-related stories are kept
SOURCES = [
    {"name": "OpenAI", "kind": "official", "url": "https://openai.com/news/rss.xml"},
    {"name": "Google DeepMind", "kind": "official", "url": "https://deepmind.google/blog/rss.xml"},
    {"name": "Google AI", "kind": "official", "url": "https://blog.google/technology/ai/rss/"},
    {"name": "Hugging Face", "kind": "official", "url": "https://huggingface.co/blog/feed.xml"},
    {"name": "NVIDIA Blog", "kind": "general", "url": "https://blogs.nvidia.com/feed/"},
    {"name": "TechCrunch AI", "kind": "news", "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    {"name": "VentureBeat AI", "kind": "news", "url": "https://venturebeat.com/category/ai/feed/"},
    {"name": "The Verge AI", "kind": "news", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
    {"name": "MIT Tech Review", "kind": "news", "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed/"},
    {"name": "Wired AI", "kind": "news", "url": "https://www.wired.com/feed/tag/ai/latest/rss"},
    {"name": "The Decoder", "kind": "news", "url": "https://the-decoder.com/feed/"},
    {"name": "Ars Technica", "kind": "general", "url": "https://feeds.arstechnica.com/arstechnica/technology-lab"},
    {"name": "Simon Willison", "kind": "community", "url": "https://simonwillison.net/atom/everything/"},
    {"name": "Hacker News", "kind": "community",
     "url": "https://hnrss.org/newest?points=100&q=LLM+OR+GPT+OR+Claude+OR+Gemini+OR+Llama+OR+OpenAI+OR+Anthropic"},
    {"name": "Google News AI", "kind": "news", "url": _GOOGLE_NEWS + "artificial+intelligence+when:2d"},
    {"name": "Google News: Model launches", "kind": "news",
     "url": _GOOGLE_NEWS + "%22new+model%22+(OpenAI+OR+Anthropic+OR+Gemini+OR+Llama+OR+DeepSeek+OR+Qwen+OR+Mistral+OR+Grok)+when:7d"},
    {"name": "Google News: Benchmarks", "kind": "news",
     "url": _GOOGLE_NEWS + "AI+model+benchmark+(outperforms+OR+beats+OR+comparison)+when:7d"},
]

SOURCE_KINDS = {source["name"]: source["kind"] for source in SOURCES}
