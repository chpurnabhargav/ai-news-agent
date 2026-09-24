"""Optional AI-written comparison briefs using the Anthropic API.

Needs the `anthropic` package and credentials (ANTHROPIC_API_KEY, or a profile
from `ant auth login`). The rest of the app works without it.
"""
import datetime
import importlib.util

import analyzer
import config
import db

SYSTEM_PROMPT = """You are the analyst behind a daily AI news reader. The reader wants to understand \
new AI model releases quickly: what changed, how the models compare, and which one to pick for what.

You receive news excerpts and figures that were extracted automatically from those articles. \
The extracted figures can be wrong or attributed to the wrong model, so cross-check them against \
the excerpts, and use web search to confirm headline numbers or fill important gaps (release date, \
benchmark scores, context window, pricing, open weights, availability). Prefer official sources.

Write the brief in plain Markdown that reads well as plain text:
- Start with a 2-3 sentence bottom line.
- `## At a glance`: one Markdown table, one column per model, rows for developer, release date, \
  access (API / app / open weights), context window, price per 1M input/output tokens, and the \
  3-6 benchmarks where numbers are available for most of the models. Use "n/a" for unknowns; \
  never invent numbers.
- `## What's new`: short bullets per model.
- `## How they compare`: strengths, weaknesses and trade-offs, citing numbers.
- `## Which to use`: bullets mapping use cases (coding, agents, long documents, cost-sensitive, \
  local/self-hosted...) to a model.
- `## Sources`: the article or page titles you relied on.

Keep it under about 600 words. Note when benchmark numbers come from the vendor rather than \
independent evaluations."""


def availability():
    """Return (available, reason)."""
    if importlib.util.find_spec("anthropic") is None:
        return False, "Install the optional package to enable AI briefs:  pip install anthropic"
    return True, ""


def brief_key(models):
    return "compare:" + "|".join(sorted(models)) + ":" + datetime.date.today().isoformat()


def build_context(models, max_articles_per_model=4, max_chars=6_000):
    facts = db.model_facts(models)
    lines = [f"Today is {datetime.date.today():%B %d, %Y}.", f"Models to compare: {', '.join(models)}", ""]
    lines.append("# Figures extracted from the news (unverified)")
    for model in models:
        rows = facts.get(model) or []
        if not rows:
            lines.append(f"- {model}: none extracted")
            continue
        for fact in rows[:25]:
            value = analyzer.format_fact_value(fact["kind"], fact["value"], fact["unit"])
            lines.append(f"- {model} | {fact['name']}: {value} (from \"{fact['title']}\", {fact['source']})")

    seen = set()
    lines += ["", "# News coverage"]
    for model in models:
        for article in db.query_articles(model=model, sort="top", limit=max_articles_per_model):
            if article["link"] in seen:
                continue
            seen.add(article["link"])
            content = db.get_article_content(article["id"]) or article["summary"] or ""
            published = article["published_at"].strftime("%Y-%m-%d") if article["published_at"] else "unknown date"
            lines += [
                "",
                f"## {article['title']}",
                f"Source: {article['source']}, {published}, {article['link']}",
                content[:max_chars],
            ]
    return "\n".join(lines)


def generate_comparison(models):
    """Ask the AI model for a comparison brief of the given models. Returns Markdown text."""
    import anthropic

    client = anthropic.Anthropic()
    messages = [{
        "role": "user",
        "content": build_context(models) + "\n\nWrite the comparison brief for: " + ", ".join(models),
    }]
    response = None
    # Web search runs server-side; a long search turn may pause and must be resumed.
    for _ in range(4):
        with client.beta.messages.stream(
            model=config.BRIEF_MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}],
            # If the primary model declines, the API retries on a fallback model in the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": response.content})

    if response.stop_reason == "refusal":
        raise RuntimeError("The AI model declined to write this brief.")
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise RuntimeError(f"The AI model returned no text (stop reason: {response.stop_reason}).")
    db.save_brief(brief_key(models), text)
    return text


def describe_error(error):
    """Turn SDK exceptions into a message for the UI."""
    try:
        import anthropic
    except ImportError:
        return str(error)
    if isinstance(error, anthropic.AuthenticationError):
        return "The API rejected the credentials. Set ANTHROPIC_API_KEY or run `ant auth login`."
    if isinstance(error, anthropic.RateLimitError):
        return "Rate limited by the Anthropic API. Try again in a minute."
    if isinstance(error, anthropic.APIConnectionError):
        return "Could not reach the Anthropic API. Check your internet connection."
    if isinstance(error, anthropic.APIStatusError):
        return f"Anthropic API error ({error.status_code}): {error.message}"
    if isinstance(error, TypeError) and "authentication" in str(error).lower():
        return "No Anthropic API credentials found. Set ANTHROPIC_API_KEY or run `ant auth login`."
    return str(error)
