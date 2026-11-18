# AI News Agent

A desktop briefing app for artificial intelligence news. It pulls stories from AI labs, AI news desks and community sources, works out which ones matter, explains why, spots new model releases, and lines the models up side by side so you can compare them at a glance. Everything is stored locally in SQLite.

## Features

- **Must know**: the handful of stories you should not miss, each with a short summary, a "Why it matters" box, the key numbers, and every outlet that covered it. Ranked by model launches, official announcements, how widely a story is covered, benchmark numbers, big deals and policy stakes, and recency, with at most three stories from any one topic
- **A gist for every story**: one or two plain sentences taken from the feed or the article, with boilerplate and repeated headlines removed. The Must know page ends with every other story in one line each
- **Today**: stat tiles, the top three must-know stories, this week's new model releases with their headline numbers, the latest stories, and a breakdown by topic
- **Readable design**: light and dark themes, a larger-text option, a centred reading column and high-contrast text. Your choices are remembered
- **Better sources**: official lab blogs (OpenAI, Google DeepMind, Google AI, Hugging Face) plus AI news desks, Hacker News, Simon Willison's blog and targeted Google News searches for launches and benchmarks. Stories from general tech feeds are kept only when they are about AI
- **Topics**: every story is tagged as Model Release, Research, Open Source, Products & Tools, Business & Funding, Policy & Safety, Hardware & Chips or General
- **Relevance ranking**: stories are scored on model launches, benchmark numbers, official sources and comparison language, so the important ones rise to the top
- **Model tracker**: every AI model mentioned in the news (GPT, o-series, Claude, Gemini, Gemma, Llama, Grok, DeepSeek, Qwen, Mistral, Phi, Kimi, GLM and more) with coverage counts and extracted highlights
- **Model comparison**: pick up to five models to see developer, context window, input/output pricing and benchmark scores (SWE-bench, GPQA, MMLU-Pro, AIME, LMArena Elo and others) side by side, with the best value in each row starred and every number linked to the article it came from
- **Benchmark extraction**: the full text of model-release articles is downloaded so numbers from the article body are captured, not just the RSS summary
- **Optional AI explanations**: with an Anthropic API key, **Explain with AI** on the Must know page writes what happened and why it matters for each story, a bottom line for the day, and a one-line gist for every other story. **Generate brief** on the Compare page writes a model comparison (what's new, a numbers table, trade-offs and which model to use for what), checking the figures with web search
- Search, filter by time range, source or topic, and save articles for later
- Optionally fetches once per day when the computer is online

## Requirements

- Python 3.10 or newer
- Tkinter
- Internet access when fetching RSS feeds

SQLite is included with Python, so no database server is required.

## Setup

Clone the repository and open a terminal in the project directory:

```bash
git clone https://github.com/chpurnabhargav/ai-news-agent.git
cd ai-news-agent
```

Create a virtual environment, install the dependency, and start the app.

### Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

If PowerShell blocks activation, allow scripts for your user account and run the activation command again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

On Debian or Ubuntu, install Tkinter if it is not available:

```bash
sudo apt install python3-tk
```

When the app starts, it initializes the database, opens on **Must know** and fetches the latest articles. Use **Refresh** to fetch again.

## Using the App

| View | What it shows |
| --- | --- |
| **Must know** | The stories worth your attention from the last three days: summary, why it matters, key numbers and coverage, then everything else in one line |
| **Today** | Today's numbers, the top three must-know stories, new model releases, the latest stories and topics |
| **All news** | Every story with its gist, with filtering, time range, source, topic and sort (Top or Latest) |
| **Model tracker** | All models in the news. Select rows and click **Compare selected**, or double-click |
| **Compare** | Side-by-side specs and benchmarks, the AI brief, and the evidence behind each number |
| **Saved** | Stories you saved with **☆ Save** |

The search box at the top searches every story. Click a topic in the sidebar to read only that topic. Click a model tag on any story to compare that model, or **⇄ Compare** to compare every model the story mentions.

**Dark mode** and **Larger text** are at the bottom of the sidebar.

Figures in the comparison table are extracted automatically from articles, so they can be incomplete, attributed to the wrong model, or reported by the vendor rather than measured independently. Each number links to its source article under **Evidence & coverage**.

## AI Explanations and Briefs (Optional)

Two buttons use an AI model:

- **Explain with AI** on the Must know page writes, for each must-know story, what happened and why it matters, plus a bottom line for the day and a one-line gist for up to 40 other stories. It works only from the stored coverage, without web search.
- **Generate brief** on the Compare page writes a comparison of the selected models and checks the figures with web search.

Both need the `anthropic` package (included in `requirements.txt`) and an Anthropic API key:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python app.py
```

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
python app.py
```

Both use `claude-opus-5-5` by default and save their results for the day, so reopening the page does not call the API again. Click **Update AI explanations** or **Regenerate** to write them again. Set `AI_NEWS_AGENT_BRIEF_MODEL` to use a different model. Each click is one API request (a comparison brief may also run a few web searches), billed to your Anthropic account. The rest of the app works without a key.

## Automatic Daily Fetching

The optional watcher checks the internet connection every five minutes. Once a day, it fetches new articles and opens the desktop app after a successful fetch:

```bash
python watcher.py
```

On Windows, create a startup watcher shortcut and a desktop app shortcut with:

```powershell
.\setup_startup.ps1
```

Run the script from an activated environment after installing the requirements. The watcher is optional; running `python app.py` is enough for normal use.

## Data Storage

The app stores its SQLite database, display settings (`settings.json`) and daily watcher marker outside the repository:

- Windows: `%LOCALAPPDATA%\AI News Agent\news.db`
- macOS/Linux: `$XDG_DATA_HOME/ai-news-agent/news.db`, or `~/.local/share/ai-news-agent/news.db`

Set `AI_NEWS_AGENT_DATA_DIR` to use a custom data directory. For example, in PowerShell:

```powershell
$env:AI_NEWS_AGENT_DATA_DIR = "C:\path\to\ai-news-data"
python app.py
```

## Configuration

Edit `config.py` to:

- Add, remove, or change RSS feeds in `SOURCES`. Each feed has a `kind`: `official` feeds rank higher, and stories from `general` and `community` feeds are kept only when they are about AI
- Change the maximum number of articles fetched per source with `MAX_ARTICLES_PER_SOURCE`
- Change how many model-release articles are downloaded in full per fetch with `MAX_ENRICH_PER_FETCH`

Databases created by earlier versions are upgraded automatically: existing articles are classified and given gists on the next start.

Articles with a link already in the database are ignored on later fetches.

## Tests

Run the offline unit tests with:

```bash
python -m unittest discover -s tests -v
```

## Project Structure

| File | Purpose |
| --- | --- |
| `app.py` | Tkinter desktop application and its views |
| `theme.py` | Light and dark colour palettes and fonts |
| `widgets.py` | Shared interface components (buttons, cards, scrolling column, search box) |
| `fetcher.py` | RSS fetching, article parsing and full-text enrichment |
| `analyzer.py` | Topic classification, ranking, gists, must-know selection, model detection and benchmark extraction |
| `ai_brief.py` | Optional AI explanations and comparison briefs |
| `db.py` | SQLite database operations |
| `config.py` | Feed, storage and display-settings configuration |
| `watcher.py` | Optional daily background fetcher |
| `setup_startup.ps1` | Windows shortcut setup |
| `tests/` | Offline unit tests |

## License

No license has been added yet. Add one before distributing or accepting reuse of the project.