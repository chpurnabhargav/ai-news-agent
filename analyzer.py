"""Offline analysis of AI news articles.

Everything here is pure text processing: classify articles into topics, detect
AI model names, pull benchmark scores / context windows / prices out of the
text, score how important a story is, and group near-duplicate stories.
"""
import re
from collections import Counter

CATEGORIES = [
    "Model Release",
    "Research",
    "Open Source",
    "Products & Tools",
    "Business & Funding",
    "Policy & Safety",
    "Hardware & Chips",
    "General",
]

_CATEGORY_PATTERNS = {
    "Research": r"\b(paper|arxiv|researchers?|study|studies|dataset|breakthrough|state[- ]of[- ]the[- ]art|sota|"
                r"reasoning|interpretability|alignment research|technical report|evals?|benchmarks?)\b",
    "Open Source": r"\b(open[- ]source|open[- ]weights?|hugging ?face|github|apache 2\.0|mit license|"
                   r"weights (are|now) available|gguf|ollama)\b",
    "Products & Tools": r"\b(app|feature|rolls? out|rolling out|update|agents?|assistant|plugin|api|sdk|chatgpt|"
                        r"copilot|browser|coding tool|integration|subscription|pricing|now available)\b",
    "Business & Funding": r"\b(funding|raises?|raised|valuation|acquisition|acquires?|acquired|ipo|revenue|"
                          r"investments?|investors?|layoffs?|deal|partnership|startup|series [a-f]|"
                          r"\$\d+(\.\d+)?\s*(billion|million|bn|b|m)\b)",
    "Policy & Safety": r"\b(regulat\w*|laws?|legislation|policy|lawsuit|sues?|sued|court|copyright|safety|ban|"
                       r"bans|senate|congress|eu ai act|government|ethic\w*|deepfakes?|privacy|misinformation|"
                       r"white house|executive order|antitrust)\b",
    "Hardware & Chips": r"\b(chips?|gpus?|nvidia|tpus?|semiconductors?|data ?cent(er|re)s?|h100|h200|b200|gb200|"
                        r"blackwell|rubin|compute|supercomputer|tsmc|amd|asics?)\b",
}
_CATEGORY_RE = {name: re.compile(p, re.IGNORECASE) for name, p in _CATEGORY_PATTERNS.items()}

_CATEGORY_WEIGHT = {
    "Model Release": 0,
    "Research": 6,
    "Open Source": 6,
    "Hardware & Chips": 4,
    "Policy & Safety": 4,
    "Business & Funding": 3,
    "Products & Tools": 3,
    "General": 0,
}

_RELEASE_RE = re.compile(
    r"\b(launch(es|ed|ing)?|releas(e|es|ed|ing)|unveil(s|ed|ing)?|introduc(e|es|ed|ing)|announc(e|es|ed|ing)|"
    r"debut(s|ed)?|rolls? out|rolled out|ships?|shipped|drops|dropped|now available|open[- ]sources?|"
    r"meet|new model|preview|is here|arrives?|our (?:new|newest|latest|most \w+) model)\b",
    re.IGNORECASE,
)
_COMPARISON_RE = re.compile(
    r"\b(benchmarks?|outperform\w*|beats?|tops?|leaderboard|state[- ]of[- ]the[- ]art|sota|vs\.?|versus|"
    r"compar\w*|head[- ]to[- ]head|rivals?)\b",
    re.IGNORECASE,
)
_AI_RE = re.compile(
    r"\b(AI|A\.I\.|artificial intelligence|machine learning|deep learning|LLMs?|neural|GPT|chatbots?|OpenAI|"
    r"Anthropic|DeepMind|Gemini|Claude|Llama|Copilot|generative|foundation models?|language models?|"
    r"Hugging Face|Mistral|DeepSeek|Qwen)\b"
)

# ---------------------------------------------------------------------------
# Model detection
# ---------------------------------------------------------------------------

_V = r"(\d+(?:\.\d+)?)"


def _gpt(m):
    name = f"GPT-{m.group(1)}{m.group(2) or ''}"
    return f"{name} {m.group(3).lower()}" if m.group(3) else name


def _suffix(base, sep=" "):
    def fmt(m):
        parts = [g for g in m.groups()[1:] if g]
        text = base.format(v=m.group(1))
        return text + "".join(f"{sep}{p}" for p in parts)
    return fmt


# (family, developer, regex, formatter, required context regex or None)
_MODEL_PATTERNS = [
    ("GPT", "OpenAI", re.compile(rf"\bGPT[- ]?{_V}(o)?(?:[- ](mini|nano|pro|turbo|codex))?\b", re.IGNORECASE), _gpt, None),
    ("GPT", "OpenAI", re.compile(r"\bgpt-oss-(\d+)b\b", re.IGNORECASE), lambda m: f"gpt-oss-{m.group(1)}b", None),
    ("o-series", "OpenAI", re.compile(r"\b(o[1-9])(?:[- ](mini|pro))?\b"),
     lambda m: m.group(1) + (f"-{m.group(2)}" if m.group(2) else ""), re.compile(r"OpenAI|ChatGPT")),
    ("Claude", "Anthropic", re.compile(rf"\bClaude\s+(Opus|Sonnet|Haiku|Fable|Mythos)\s+{_V}\b", re.IGNORECASE),
     lambda m: f"Claude {m.group(1).title()} {m.group(2)}", None),
    ("Claude", "Anthropic", re.compile(rf"\bClaude\s+{_V}\s+(Opus|Sonnet|Haiku)\b", re.IGNORECASE),
     lambda m: f"Claude {m.group(2).title()} {m.group(1)}", None),
    ("Gemini", "Google", re.compile(rf"\bGemini\s+{_V}(?:\s+(Pro|Flash-Lite|Flash|Ultra|Nano|Deep Think))?\b", re.IGNORECASE),
     lambda m: f"Gemini {m.group(1)}" + (f" {m.group(2).title()}" if m.group(2) else ""), None),
    ("Gemma", "Google", re.compile(rf"\bGemma\s?{_V}\b", re.IGNORECASE), lambda m: f"Gemma {m.group(1)}", None),
    ("Veo", "Google", re.compile(rf"\bVeo\s?{_V}\b"), lambda m: f"Veo {m.group(1)}", None),
    ("Imagen", "Google", re.compile(rf"\bImagen\s?{_V}\b"), lambda m: f"Imagen {m.group(1)}", None),
    ("Llama", "Meta", re.compile(rf"\bLlama[- ]?{_V}(?:\s+(Scout|Maverick|Behemoth))?\b", re.IGNORECASE),
     lambda m: f"Llama {m.group(1)}" + (f" {m.group(2).title()}" if m.group(2) else ""), None),
    ("Grok", "xAI", re.compile(rf"\bGrok[- ]?{_V}(?:\s+(Heavy|Fast|Mini|Code))?\b", re.IGNORECASE),
     lambda m: f"Grok {m.group(1)}" + (f" {m.group(2).title()}" if m.group(2) else ""), None),
    ("DeepSeek", "DeepSeek", re.compile(r"\bDeepSeek[- ](V\d+(?:\.\d+)?|R\d+)(?:[- ](Exp|Terminus))?\b", re.IGNORECASE),
     lambda m: f"DeepSeek-{m.group(1).upper()}" + (f"-{m.group(2).title()}" if m.group(2) else ""), None),
    ("Qwen", "Alibaba", re.compile(rf"\bQwen\s?{_V}(?:[- ](Max|Coder|VL|Omni))?\b", re.IGNORECASE),
     lambda m: f"Qwen{m.group(1)}" + (f"-{m.group(2)}" if m.group(2) else ""), None),
    ("Mistral", "Mistral AI", re.compile(r"\b(Mistral|Magistral|Devstral)\s+(Large|Medium|Small)(?:\s+(\d+(?:\.\d+)?))?\b"),
     lambda m: f"{m.group(1)} {m.group(2)}" + (f" {m.group(3)}" if m.group(3) else ""), None),
    ("Phi", "Microsoft", re.compile(rf"\bPhi-{_V}(?:[- ](mini|vision|reasoning))?\b"),
     lambda m: f"Phi-{m.group(1)}" + (f"-{m.group(2)}" if m.group(2) else ""), None),
    ("Kimi", "Moonshot AI", re.compile(rf"\bKimi[- ]K{_V}\b", re.IGNORECASE), lambda m: f"Kimi K{m.group(1)}", None),
    ("GLM", "Zhipu AI", re.compile(rf"\bGLM-{_V}\b"), lambda m: f"GLM-{m.group(1)}", None),
    ("MiniMax", "MiniMax", re.compile(rf"\bMiniMax[- ]M{_V}\b", re.IGNORECASE), lambda m: f"MiniMax-M{m.group(1)}", None),
    ("Nova", "Amazon", re.compile(r"\bNova\s+(Premier|Pro|Lite|Micro)\b"), lambda m: f"Nova {m.group(1)}", re.compile(r"Amazon|AWS")),
    ("Sora", "OpenAI", re.compile(r"\bSora\s?(\d+)\b"), lambda m: f"Sora {m.group(1)}", None),
    ("Midjourney", "Midjourney", re.compile(rf"\bMidjourney\s+V{_V}\b", re.IGNORECASE), lambda m: f"Midjourney V{m.group(1)}", None),
]

MODEL_DEVELOPERS = {family: dev for family, dev, *_ in _MODEL_PATTERNS}


def _model_matches(text):
    """Yield (start, end, name, family, developer) for every model mention."""
    if not text:
        return
    for family, developer, regex, fmt, context in _MODEL_PATTERNS:
        if context is not None and not context.search(text):
            continue
        for m in regex.finditer(text):
            yield m.start(), m.end(), fmt(m), family, developer


def detect_models(text):
    """Return detected models as a list of dicts, most mentioned first."""
    counts = Counter()
    first_seen = {}
    info = {}
    for start, _, name, family, developer in _model_matches(text):
        counts[name] += 1
        first_seen[name] = min(start, first_seen.get(name, start))
        info[name] = {"name": name, "family": family, "developer": developer}
    return [info[n] for n in sorted(counts, key=lambda n: (-counts[n], first_seen[n]))]


# ---------------------------------------------------------------------------
# Fact extraction (benchmarks, context window, pricing)
# ---------------------------------------------------------------------------

_BENCHMARKS = [
    ("MMLU-Pro", r"MMLU[- ]Pro"),
    ("MMLU", r"MMLU"),
    ("GPQA Diamond", r"GPQA[- ]Diamond"),
    ("GPQA", r"GPQA"),
    ("SWE-bench Verified", r"SWE[- ]?bench[- ]Verified"),
    ("SWE-bench Pro", r"SWE[- ]?bench[- ]Pro"),
    ("SWE-bench", r"SWE[- ]?bench"),
    ("Terminal-Bench", r"Terminal[- ]?Bench(?:\s*2(?:\.0)?)?"),
    ("HumanEval", r"HumanEval"),
    ("LiveCodeBench", r"LiveCodeBench"),
    ("AIME 2025", r"AIME\s*(?:20)?25"),
    ("AIME 2024", r"AIME\s*(?:20)?24"),
    ("AIME", r"AIME"),
    ("MATH-500", r"MATH[- ]500"),
    ("GSM8K", r"GSM[- ]?8K"),
    ("Humanity's Last Exam", r"Humanity['’]s Last Exam|\bHLE\b"),
    ("ARC-AGI-2", r"ARC[- ]AGI[- ]2"),
    ("ARC-AGI", r"ARC[- ]AGI"),
    ("MMMU", r"MMMU"),
    ("OSWorld", r"OSWorld(?:[- ]Verified)?"),
    ("τ²-bench", r"(?:τ|tau)[²2]?[- ]?bench"),
    ("BrowseComp", r"BrowseComp"),
    ("SimpleQA", r"SimpleQA"),
    ("FrontierMath", r"FrontierMath"),
]
_BENCH_ALT = "|".join(f"(?P<b{i}>{p})" for i, (_, p) in enumerate(_BENCHMARKS))
_NUM = r"(\d{1,3}(?:\.\d+)?)"
_BENCH_AFTER = re.compile(rf"(?:{_BENCH_ALT})\b[^.%\d\n]{{0,40}}?{_NUM}\s*(?:%|percent)", re.IGNORECASE)
_BENCH_BEFORE = re.compile(rf"{_NUM}\s*(?:%|percent)\s+(?:on|in|for|at)\s+(?:the\s+)?(?:{_BENCH_ALT})", re.IGNORECASE)
_ARENA = re.compile(r"\b(?:LMArena|Chatbot Arena|Arena)\b[^.\n]{0,40}?\b(1\d{3})\b(?:\s*Elo)?", re.IGNORECASE)
_ARENA_BEFORE = re.compile(r"\b(1\d{3})\s*(?:Elo|points?)\s+(?:on|in|at)\s+(?:the\s+)?(?:LMArena|Chatbot Arena)", re.IGNORECASE)

_CONTEXT_PATTERNS = [
    re.compile(r"(\d+(?:\.\d+)?)\s*(k|m|thousand|million)[- ]tokens?\s+(?:of\s+)?context", re.IGNORECASE),
    re.compile(r"context\s+(?:window|length)\s+(?:of\s+)?(?:up\s+to\s+)?(\d[\d,]*(?:\.\d+)?)\s*(k|m|thousand|million)?\s*tokens",
               re.IGNORECASE),
]
_PRICE_EACH = re.compile(
    r"\$(\d+(?:\.\d+)?)\s*(?:per|/|a)\s*(?:1m|1 m|one million|1 million|million|m)\s+(input|output)\s+tokens",
    re.IGNORECASE,
)
_PRICE_PAIR = re.compile(
    r"\$(\d+(?:\.\d+)?)\s*(?:/|and)\s*\$(\d+(?:\.\d+)?)\s*(?:per|/)\s*(?:1m|one million|1 million|million|m)\b",
    re.IGNORECASE,
)
_SCORE_AFTER_MODEL = re.compile(r"[^.%\d\n]{0,30}?(\d{1,3}(?:\.\d+)?)\s*(?:%|percent)")
_ANY_BENCH = re.compile(_BENCH_ALT, re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“])|\n+")


def _bench_name(match):
    for i, (name, _) in enumerate(_BENCHMARKS):
        if match.group(f"b{i}"):
            return name
    return None


def _to_tokens(value, unit):
    number = float(value.replace(",", ""))
    unit = (unit or "").lower()
    if unit in ("k", "thousand"):
        number *= 1_000
    elif unit in ("m", "million"):
        number *= 1_000_000
    return number


def _closest_model(models_in_sentence, position, fallback):
    before = [m for m in models_in_sentence if m[0] <= position]
    if before:
        return max(before, key=lambda m: m[0])
    if models_in_sentence:
        return min(models_in_sentence, key=lambda m: m[0])
    return fallback


def extract_facts(text, primary_model=None):
    """Extract model facts from free text.

    Returns a list of dicts with keys: model, family, developer, kind, name,
    value, unit. `kind` is one of benchmark, context, price_in, price_out.
    Facts in a sentence are attached to the nearest preceding model mention in
    that sentence, falling back to `primary_model` (a detect_models() dict).
    """
    if not text:
        return []
    primary = None
    if primary_model:
        primary = (0, 0, primary_model["name"], primary_model["family"], primary_model["developer"])
    previous = None  # last model named in an earlier sentence ("It scores ...")

    facts = []
    seen = set()

    def add(model, kind, name, value, unit):
        if model is None:
            return
        key = (model[2], kind, name, round(value, 3))
        if key in seen:
            return
        seen.add(key)
        facts.append({
            "model": model[2], "family": model[3], "developer": model[4],
            "kind": kind, "name": name, "value": value, "unit": unit,
        })

    for sentence in _SENTENCE_SPLIT.split(text):
        if not sentence or len(sentence) > 1200:
            continue
        models = sorted(_model_matches(sentence))
        fallback = previous or primary
        benchmarked = set()

        # "80.1% on SWE-bench" is unambiguous, so it wins over "SWE-bench ... 80.1%" when they overlap.
        taken = []
        for m in _BENCH_BEFORE.finditer(sentence):
            score = float(m.group(1))
            if score <= 100:
                model = _closest_model(models, m.start(), fallback)
                add(model, "benchmark", _bench_name(m), score, "%")
                benchmarked.add(model and model[2])
                taken.append(m.span())
        for m in _BENCH_AFTER.finditer(sentence):
            score = float(m.group(m.lastindex))
            if score <= 100 and not any(m.start() < end and start < m.end() for start, end in taken):
                model = _closest_model(models, m.start(), fallback)
                add(model, "benchmark", _bench_name(m), score, "%")
                benchmarked.add(model and model[2])
        # "... on SWE-bench Verified, while Claude Sonnet 4.5 hit 72.1%"
        for model in models:
            if model[2] in benchmarked:
                continue
            bench = None
            for b in _ANY_BENCH.finditer(sentence, 0, model[0]):
                bench = _bench_name(b)
            m = _SCORE_AFTER_MODEL.match(sentence, model[1])
            if bench and m and float(m.group(1)) <= 100:
                add(model, "benchmark", bench, float(m.group(1)), "%")
        for m in _ARENA_BEFORE.finditer(sentence):
            add(_closest_model(models, m.start(), fallback), "benchmark", "LMArena Elo", float(m.group(1)), "Elo")
        for m in _ARENA.finditer(sentence):
            add(_closest_model(models, m.start(), fallback), "benchmark", "LMArena Elo", float(m.group(1)), "Elo")

        for regex in _CONTEXT_PATTERNS:
            for m in regex.finditer(sentence):
                tokens = _to_tokens(m.group(1), m.group(2))
                if 1_000 <= tokens <= 100_000_000:
                    add(_closest_model(models, m.start(), fallback), "context", "Context window", tokens, "tokens")

        for m in _PRICE_EACH.finditer(sentence):
            kind = "price_in" if m.group(2).lower() == "input" else "price_out"
            label = "Input price" if kind == "price_in" else "Output price"
            add(_closest_model(models, m.start(), fallback), kind, label, float(m.group(1)), "$/1M tokens")
        for m in _PRICE_PAIR.finditer(sentence):
            if "token" not in sentence.lower():
                continue
            model = _closest_model(models, m.start(), fallback)
            add(model, "price_in", "Input price", float(m.group(1)), "$/1M tokens")
            add(model, "price_out", "Output price", float(m.group(2)), "$/1M tokens")
        if models:
            previous = models[0]  # the sentence subject is usually named first
    return facts


def format_fact_value(kind, value, unit):
    if kind == "context":
        if value >= 1_000_000:
            return f"{value / 1_000_000:g}M tokens"
        return f"{value / 1_000:g}K tokens"
    if kind in ("price_in", "price_out"):
        return f"${value:g} / 1M"
    if unit == "%":
        return f"{value:g}%"
    return f"{value:g} {unit}".strip()


# ---------------------------------------------------------------------------
# Classification and scoring
# ---------------------------------------------------------------------------

def is_ai_related(title, summary=""):
    text = f"{title} {summary}"
    return bool(_AI_RE.search(text) or detect_models(text))


def classify(title, summary="", models=None):
    """Return (primary_category, tags, is_release)."""
    models = models if models is not None else detect_models(f"{title} {summary}")
    title_models = detect_models(title)
    is_release = bool(title_models and _RELEASE_RE.search(title)) or bool(
        models and _RELEASE_RE.search(summary[:300]) and _RELEASE_RE.search(title)
    )

    hits = {}
    for name, regex in _CATEGORY_RE.items():
        score = 3 * len(regex.findall(title)) + len(regex.findall(summary))
        if score:
            hits[name] = score
    tags = sorted(hits, key=lambda n: (-hits[n], CATEGORIES.index(n)))
    if is_release:
        return "Model Release", ["Model Release"] + tags, True
    primary = tags[0] if tags else "General"
    return primary, tags or ["General"], False


def score_article(category, is_release, models, facts, source_kind, title, summary=""):
    """Heuristic 0-100 importance score."""
    score = 10.0
    if is_release:
        score += 25
    score += min(len(models), 3) * 5
    score += min(len([f for f in facts if f["kind"] == "benchmark"]), 4) * 4
    score += 4 if any(f["kind"] != "benchmark" for f in facts) else 0
    score += {"official": 12, "news": 4, "community": 2}.get(source_kind, 0)
    score += _CATEGORY_WEIGHT.get(category, 0)
    if _COMPARISON_RE.search(title):
        score += 8
    elif _COMPARISON_RE.search(summary):
        score += 3
    return min(score, 100.0)


def analyze(title, summary="", source_kind="news"):
    text = f"{title}. {summary}"
    models = detect_models(text)
    title_models = detect_models(title)
    primary = title_models[0] if len(title_models) == 1 else (models[0] if len(models) == 1 else None)
    facts = extract_facts(text, primary)
    category, tags, is_release = classify(title, summary, models)
    title_names = {m["name"] for m in title_models}
    for model in models:
        # Only the models a release headline names were released; others are comparisons.
        model["released"] = is_release and model["name"] in title_names
    return {
        "category": category,
        "tags": tags,
        "is_release": is_release,
        "models": models,
        "primary_model": primary,
        "facts": facts,
        "score": score_article(category, is_release, models, facts, source_kind, title, summary),
        "gist": make_gist(title, summary),
    }


# ---------------------------------------------------------------------------
# Story clustering
# ---------------------------------------------------------------------------

_STOP = set(
    "a an the and or of to in on for with by at from as is are was be its it this that new how why what "
    "will can could says said after over into about up out than more just now you your their has have "
    "ai us we our my me i so".split()
)
_WORD = re.compile(r"[a-z0-9][a-z0-9.\-]*")
_POSSESSIVE = re.compile(r"['’]s\b")
_ENTITY = re.compile(r"\b[A-Z][A-Za-z0-9.\-]*")
_ENTITY_STOP = set(
    "The A An And Or For With In On Of To At By From Is It Its This That How Why What When Who New Here Says "
    "After Over Into About Inside AI Show HN Ask".split()
)


def _headline(title):
    title = re.sub(r"\s+[-–|]\s+[^-–|]{2,40}$", "", title)  # drop " - Publisher" suffixes
    return _POSSESSIVE.sub("", title)


def story_tokens(title):
    return {w for w in _WORD.findall(_headline(title).lower()) if w not in _STOP and len(w) > 1}


def story_entities(title):
    """Capitalised names in a headline ("EU", "Act", "Nvidia"), minus common words."""
    return {e.rstrip(".") for e in _ENTITY.findall(_headline(title)) if e not in _ENTITY_STOP and len(e) > 1}


def cluster_articles(articles, threshold=0.45):
    """Group near-duplicate stories. Input must be ordered best-first.

    Returns a list of (lead_article, [duplicate_articles]).
    """
    clusters = []
    for article in articles:
        tokens = story_tokens(article["title"])
        models = set(article.get("models") or [])
        headline_models = {m["name"] for m in detect_models(article["title"])}
        entities = story_entities(article["title"])
        release = bool(article.get("is_release"))
        for cluster in clusters:
            lead_tokens, lead_models, lead_headline_models, lead_entities, lead_release = cluster[2:]
            if not tokens or not lead_tokens:
                continue
            overlap = len(tokens & lead_tokens) / len(tokens | lead_tokens)
            same_models = models and models == lead_models and overlap >= threshold / 2
            # Outlets word headlines very differently ("Introducing X" / "Company releases X"), so
            # two headlines about the same model count as one story when both announce it, and
            # headlines that name the same two things ("EU", "Act") need less word overlap.
            same_launch = headline_models & lead_headline_models and (
                (release and lead_release) or overlap >= threshold / 3)
            same_names = len(entities & lead_entities) >= 2 and overlap >= threshold / 3
            if overlap >= threshold or same_models or same_launch or same_names:
                cluster[1].append(article)
                break
        else:
            clusters.append((article, [], tokens, models, headline_models, entities, release))
    return [(lead, dupes) for lead, dupes, *_ in clusters]


# ---------------------------------------------------------------------------
# Gists: a short, readable "what is this story about" for every article
# ---------------------------------------------------------------------------

_GIST_BOILERPLATE = [
    re.compile(r"\bThe post\b.{3,300}?\bappeared first on\b.{2,120}$", re.IGNORECASE),
    re.compile(r"\b(Continue reading|Read more|Read the full (story|article|post)|Click here|Keep reading)\b.*$",
               re.IGNORECASE),
    re.compile(r"\[(…|\.\.\.|&hellip;)\]\s*$"),
    re.compile(r"https?://\S+"),
]
# hnrss.org summaries are just links and counters
_HN_SUMMARY = re.compile(r"\b(Article URL|Comments URL):|\bPoints:\s*\d+|#\s*Comments:\s*\d+", re.IGNORECASE)
# "SAN FRANCISCO (Reuters) - " style datelines
_DATELINE = re.compile(r"^[A-Z][A-Z .,'’-]{2,40}\s*(\([^)]{2,30}\))?\s*[-—–]\s+")
_JUNK_LINE = re.compile(
    r"\b(cookies?|subscribe|sign up|sign in|log in|newsletter|advertis\w*|all rights reserved|©|"
    r"share this|follow us|privacy policy|terms of (use|service)|javascript)\b",
    re.IGNORECASE,
)


def _gist_sentences(text):
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s and s.strip()]


def _shorten_words(text, limit):
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:-–—") + "…"


def short_gist(gist, limit=200):
    """Trim a gist to whole sentences that fit in `limit` characters."""
    gist = (gist or "").strip()
    if len(gist) <= limit:
        return gist
    out = ""
    for sentence in _gist_sentences(gist):
        candidate = f"{out} {sentence}".strip()
        if len(candidate) > limit:
            break
        out = candidate
    return out or _shorten_words(gist, limit)


def _same_as_title(text, title):
    """True when the text is just the headline again (Google News puts 'Headline  Publisher' here)."""
    title_tokens, text_tokens = story_tokens(title), story_tokens(text)
    if not text_tokens:
        return True
    if not title_tokens:
        return False
    overlap = len(title_tokens & text_tokens) / len(text_tokens)
    return overlap >= 0.75 and len(text) <= len(title) + 60


def _clean_summary_for_gist(summary, title):
    if not summary or _HN_SUMMARY.search(summary):
        return ""
    text = summary.strip()
    for pattern in _GIST_BOILERPLATE:
        text = pattern.sub("", text).strip()
    if title and text.lower().startswith(title.lower()):
        text = text[len(title):].lstrip(" .:-–—|")
    text = _DATELINE.sub("", text).strip()
    if len(text) < 40 or _same_as_title(text, title or ""):
        return ""
    return text


def _clean_content_for_gist(content, title):
    if not content:
        return ""
    lines = []
    for line in content.splitlines():
        line = line.strip()
        if len(line) < 60 or _JUNK_LINE.search(line) or _same_as_title(line, title or ""):
            continue
        lines.append(_DATELINE.sub("", line))
        if sum(len(item) for item in lines) > 450:
            break
    return " ".join(lines)


def make_gist(title, summary, content=None, limit=420, enough=220):
    """A short gist of the story: whole sentences from the feed summary (or the article
    body when the feed has none), skipping boilerplate and text that repeats the headline.

    Stops adding sentences once the gist is `enough` characters long. Returns "" when
    there is nothing beyond the headline to go on.
    """
    for text in (_clean_summary_for_gist(summary, title), _clean_content_for_gist(content, title)):
        if not text:
            continue
        gist = ""
        for sentence in _gist_sentences(text):
            if len(sentence) < 25 and not gist:
                continue  # stray fragments like "Photo: Reuters."
            candidate = f"{gist} {sentence}".strip()
            if len(candidate) > limit:
                break
            gist = candidate
            if len(gist) >= enough:
                break
        gist = gist or _shorten_words(text, limit)
        if gist:
            return gist
    return ""


# ---------------------------------------------------------------------------
# "Must know": the few stories worth your attention, and why
# ---------------------------------------------------------------------------

_MONEY = re.compile(r"\$\s?(\d+(?:\.\d+)?)\s*(trillion|billion|million|bn|tn|[bmt])\b", re.IGNORECASE)
_MONEY_UNITS = {"trillion": "trillion", "tn": "trillion", "t": "trillion", "billion": "billion", "bn": "billion",
                "b": "billion", "million": "million", "m": "million"}

_CATEGORY_WHY = {
    "Model Release": "A new model you may want to try or compare",
    "Research": "New research that could change what AI systems can do",
    "Open Source": "Openly available: you can download, inspect or self-host it",
    "Products & Tools": "A product change that affects the AI tools people use",
    "Business & Funding": "Money and deals that shape which AI companies lead",
    "Policy & Safety": "Rules, lawsuits or safety issues that affect how AI is built and used",
    "Hardware & Chips": "Affects the supply and cost of the compute AI runs on",
}


def money_mentions(text):
    """Dollar amounts such as "$2 billion" in the order they appear in the text."""
    found = []
    for amount, unit in _MONEY.findall(text or ""):
        label = f"${float(amount):g} {_MONEY_UNITS[unit.lower()]}"
        if label not in found:
            found.append(label)
    return found


def story_sources(lead, duplicates=()):
    """Distinct sources covering a story, lead source first."""
    sources = []
    for article in (lead, *duplicates):
        if article["source"] not in sources:
            sources.append(article["source"])
    return sources


def importance(lead, coverage, age_hours):
    """Rank a story for "Must know": its score, boosted by how many outlets cover it and by
    big money or policy stakes, fading after a day."""
    value = lead.get("score") or 0
    value += min(max(coverage - 1, 0), 5) * 6
    if lead.get("category") == "Policy & Safety":
        value += 6
    if any(amount.endswith(("billion", "trillion")) for amount in money_mentions(lead.get("title", ""))):
        value += 10
    if age_hours > 24:
        value *= max(0.5, 1 - (age_hours - 24) / 120)
    return value


def pick_must_know(clusters, now, limit=6, per_category=3, floor=20.0):
    """Choose the stories you should know about from (lead, duplicates) clusters.

    Returns dicts with lead, duplicates, sources and importance, most important first. The top
    three stories are always kept; the rest must reach `floor`. At most `per_category` stories
    come from one topic, so a busy topic (usually model launches) leaves room for big deals,
    policy and research.
    """
    ranked = []
    for lead, duplicates in clusters:
        sources = story_sources(lead, duplicates)
        published = lead.get("published_at") or now
        age_hours = max(0.0, (now - published).total_seconds() / 3600)
        ranked.append({"lead": lead, "duplicates": list(duplicates), "sources": sources,
                       "importance": importance(lead, len(sources), age_hours)})
    ranked.sort(key=lambda item: -item["importance"])

    picks, per_topic = [], Counter()
    for item in ranked:
        if len(picks) >= limit:
            break
        category = item["lead"].get("category") or "General"
        if per_topic[category] >= per_category:
            continue
        if len(picks) >= 3 and item["importance"] < floor:
            break
        picks.append(item)
        per_topic[category] += 1
    return picks


def fact_text(fact, with_model=False):
    """ "SWE-bench Verified 82.4%", or "GPT-5.5 · SWE-bench Verified 82.4%" with the model."""
    value = format_fact_value(fact["kind"], fact["value"], fact["unit"])
    unit = fact.get("unit") or ""
    if unit and fact["name"].endswith(unit) and value.endswith(unit):
        value = value[:-len(unit)].strip()  # "LMArena Elo 1532", not "LMArena Elo 1532 Elo"
    text = f"{fact['name']} {value}"
    return f"{fact['model']} · {text}" if with_model else text


def why_it_matters(lead, sources, facts=(), source_kind="news"):
    """Plain-language reasons a story matters, built from what the app knows about it."""
    reasons = []
    title = lead.get("title", "")
    category = lead.get("category") or "General"
    title_models = detect_models(title)

    if lead.get("is_release") and title_models:
        developer = title_models[0]["developer"]
        names = ", ".join(m["name"] for m in title_models[:3])
        reasons.append(f"New model release from {developer}: {names}")
    if source_kind == "official":
        reasons.append(f"Official announcement from {lead['source']}")
    if len(sources) >= 2:
        shown = ", ".join(sources[:3]) + (f" and {len(sources) - 3} more" if len(sources) > 3 else "")
        reasons.append(f"Covered by {len(sources)} outlets ({shown})")

    benchmarks, specs, seen = [], [], set()
    for fact in facts:
        key = (fact["name"], round(fact["value"], 2))
        if key in seen:
            continue
        seen.add(key)
        value = format_fact_value(fact["kind"], fact["value"], fact["unit"])
        if fact["kind"] == "benchmark":
            benchmarks.append(fact_text(fact))
        elif fact["kind"] == "context":
            specs.append(f"{value} context")
        else:
            specs.append(f"{fact['name'].split()[0].lower()} {value}")
    if benchmarks:
        reasons.append("Reported benchmark scores: " + ", ".join(benchmarks[:3]))
    if specs:
        reasons.append("Specs: " + ", ".join(specs[:3]))

    money = money_mentions(f"{title}. {lead.get('gist') or lead.get('summary') or ''}")
    if money and category in ("Business & Funding", "Hardware & Chips", "Policy & Safety", "General"):
        reasons.append("Money involved: " + " and ".join(money[:2]))
    if _COMPARISON_RE.search(title) and title_models:
        reasons.append("Compares models head to head")
    if len(reasons) < 2 and category in _CATEGORY_WHY:
        reasons.append(_CATEGORY_WHY[category])
    return reasons[:4]
