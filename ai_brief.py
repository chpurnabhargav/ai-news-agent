"""Optional AI-written comparison briefs using the Anthropic API.

Needs the `anthropic` package and credentials (ANTHROPIC_API_KEY, or a profile
from `ant auth login`). The rest of the app works without it.
"""
import datetime
import importlib.util
import json

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


MUST_KNOW_SYSTEM = """You write the "Must know" page of a daily AI news reader. The reader is busy and \
wants to understand quickly what happened in AI and why it matters to them.

You receive two lists of stories, each with an id. MUST_KNOW stories come with their headline, sources, \
an excerpt and figures that were extracted automatically from the coverage. OTHER stories come with a \
headline and a short summary.

Use only the information given. Do not add facts, numbers, names or dates that are not in the input. \
The extracted figures can be wrong or attributed to the wrong model: leave out any that the excerpt \
does not support.

For every MUST_KNOW story, write:
- what: what happened, in one or two plain sentences (at most 45 words).
- why: why it matters to someone who follows AI, in one or two sentences (at most 40 words). Be \
  concrete about who is affected and how. No hype words.

For every OTHER story, write gist: one sentence (at most 25 words) saying what the story is about. If \
the input says nothing beyond the headline, restate the headline plainly.

Also write bottom_line: two or three sentences that sum up the most important developments across the \
MUST_KNOW stories."""

MUST_KNOW_SCHEMA = {
    "type": "object",
    "properties": {
        "bottom_line": {"type": "string"},
        "must_know": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "what": {"type": "string"}, "why": {"type": "string"}},
                "required": ["id", "what", "why"],
                "additionalProperties": False,
            },
        },
        "gists": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "gist": {"type": "string"}},
                "required": ["id", "gist"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["bottom_line", "must_know", "gists"],
    "additionalProperties": False,
}


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


def must_know_key(day=None):
    return "mustknow:" + (day or datetime.date.today()).isoformat()


def get_must_know_digest(day=None):
    """Today's saved AI explanations: {bottom_line, items: {id: {what, why}}, gists: {id: text}, created_at}."""
    cached = db.get_brief(must_know_key(day))
    if not cached:
        return None
    try:
        data = json.loads(cached["text"])
    except ValueError:
        return None
    return {
        "bottom_line": data.get("bottom_line", ""),
        "items": {int(item["id"]): item for item in data.get("must_know", [])},
        "gists": {int(item["id"]): item["gist"] for item in data.get("gists", []) if item.get("gist")},
        "created_at": cached["created_at"],
    }


def _excerpt(text, limit):
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " ..."


def build_must_know_context(picks, others, max_excerpt=2_500, max_others=40):
    """picks: analyzer.pick_must_know() items; others: (lead, duplicates) clusters."""
    facts = db.article_facts([item["lead"]["id"] for item in picks])
    lines = [f"Today is {datetime.date.today():%B %d, %Y}.", "", "# MUST_KNOW"]
    for item in picks:
        lead = item["lead"]
        published = lead["published_at"].strftime("%Y-%m-%d") if lead.get("published_at") else "unknown date"
        lines += [
            "",
            f"## id {lead['id']}: {lead['title']}",
            f"Topic: {lead.get('category') or 'General'}. Published {published} by {lead['source']}. "
            f"Covered by: {', '.join(item['sources'])}.",
        ]
        other_titles = [d["title"] for d in item["duplicates"][:3]]
        if other_titles:
            lines.append("Other headlines: " + " | ".join(other_titles))
        article_facts = facts.get(lead["id"]) or []
        if article_facts:
            figures = "; ".join(
                f"{f['model']} {f['name']} {analyzer.format_fact_value(f['kind'], f['value'], f['unit'])}"
                for f in article_facts[:12]
            )
            lines.append(f"Extracted figures (unverified): {figures}")
        content = db.get_article_content(lead["id"]) or lead.get("summary") or ""
        lines.append("Excerpt: " + (_excerpt(content, max_excerpt) or "(headline only)"))

    lines += ["", "# OTHER"]
    for lead, _ in others[:max_others]:
        summary = _excerpt(lead.get("gist") or lead.get("summary") or "", 300)
        lines.append(f"- id {lead['id']}: {lead['title']} ({lead['source']})" + (f": {summary}" if summary else ""))
    return "\n".join(lines)


def generate_must_know(picks, others):
    """Ask the AI model to explain the must-know stories and gist the rest. Saves and returns the digest."""
    import anthropic

    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=config.BRIEF_MODEL,
        max_tokens=16000,
        system=MUST_KNOW_SYSTEM,
        messages=[{"role": "user", "content": build_must_know_context(picks, others)}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": MUST_KNOW_SCHEMA}},
        # If the primary model declines, the API retries on a fallback model in the same call.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        raise RuntimeError("The AI model declined to write the explanations.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("The AI answer was cut off before it finished. Try again.")
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    try:
        data = json.loads(text)
    except ValueError:
        raise RuntimeError("The AI model returned an answer that could not be read. Try again.")
    db.save_brief(must_know_key(), json.dumps(data))
    return get_must_know_digest()


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
