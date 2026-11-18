"""AI News Agent: a desktop briefing app for AI news."""
import datetime
import threading
import tkinter as tk
import webbrowser
from collections import Counter
from tkinter import ttk

import ai_brief
import analyzer
import config
import db
import fetcher
import theme
from theme import T, font
from widgets import (Button, Card, ScrollFrame, SearchBox, Segmented, bind_hover, divider, empty_state, eyebrow,
                     flow, page_header, pill, section_header, style_ttk)

RANGES = {"Last 24 hours": 24, "Last 3 days": 72, "Last 7 days": 168, "Last 30 days": 720, "All time": None}
PAGE_SIZE = 40
MUST_KNOW_LIMIT = 6
SCROLLBAR_INSET = 7  # half the scrollbar width, so fixed headers line up with scrolling content

NAV = [
    ("must", "★", "Must know"),
    ("today", "☀", "Today"),
    ("news", "☰", "All news"),
    ("models", "◈", "Model tracker"),
    ("compare", "⇄", "Compare"),
    ("saved", "♥", "Saved"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def time_ago(when):
    if not when:
        return "unknown time"
    seconds = (db.utcnow() - when).total_seconds()
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 7 * 86400:
        return f"{int(seconds // 86400)}d ago"
    return local_time(when).strftime("%b %d")


def local_time(when):
    return when.replace(tzinfo=datetime.timezone.utc).astimezone()


def shorten(text, limit):
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def open_url(url):
    if url:
        webbrowser.open(url)


def story_gist(lead, duplicates=(), ai_gists=None, limit=230):
    """The gist to show for a story: the AI one if written, else the first stored gist in the story."""
    if ai_gists and lead["id"] in ai_gists:
        return ai_gists[lead["id"]]
    for article in (lead, *duplicates):
        if article.get("gist"):
            return analyzer.short_gist(article["gist"], limit)
    return ""


def load_must_know(limit=MUST_KNOW_LIMIT):
    """(must-know picks, every other story as (lead, duplicates)) from the last few days."""
    articles = db.query_articles(hours=72, sort="top", limit=250)
    if len(articles) < 8:
        articles = db.query_articles(hours=24 * 7, sort="top", limit=250)
    clusters = analyzer.cluster_articles(articles)
    picks = analyzer.pick_must_know(clusters, db.utcnow(), limit=limit)
    chosen = {item["lead"]["id"] for item in picks}
    return picks, [(lead, dupes) for lead, dupes in clusters if lead["id"] not in chosen]


def recolor(widget, bg):
    """Set the background of a widget and all its descendants (labels and frames)."""
    try:
        widget.configure(bg=bg)
    except tk.TclError:
        pass
    for child in widget.winfo_children():
        if not getattr(child, "keep_bg", False):
            recolor(child, bg)


def descendants(widget):
    yield widget
    for child in widget.winfo_children():
        yield from descendants(child)


def label(parent, text, size=11, weight="normal", fg=None, bg=None, **kw):
    kw.setdefault("justify", "left")
    kw.setdefault("anchor", "w")
    return tk.Label(parent, text=text, font=font(size, weight), fg=fg or T.text, bg=bg or T.surface, **kw)


class Column(tk.Frame):
    """A fixed (non-scrolling) area whose content is centred and at most `max_width` wide,
    matching the column of a ScrollFrame below it."""

    def __init__(self, parent, max_width=980, gutter=32, bg=None):
        super().__init__(parent, bg=bg or T.bg, height=1)
        self.max_width, self.gutter = max_width, gutter
        self.inner = tk.Frame(self, bg=bg or T.bg)
        self.inner.place(relx=0.5, x=-SCROLLBAR_INSET, y=0, anchor="n", width=max_width)
        self.bind("<Configure>", self._resize)
        self.inner.bind("<Configure>", lambda e: self.configure(height=self.inner.winfo_reqheight()))

    def _resize(self, event):
        width = max(320, min(self.max_width, event.width - 2 * self.gutter - 2 * SCROLLBAR_INSET))
        self.inner.place_configure(width=width)


class NavItem(tk.Frame):
    def __init__(self, parent, icon, text, command):
        super().__init__(parent, bg=T.sidebar, cursor="hand2")
        self.active, self.badge_text, self.badge_important = False, "", False
        self.bar = tk.Frame(self, width=3, bg=T.sidebar)
        self.bar.pack(side="left", fill="y")
        self.icon = tk.Label(self, text=icon, font=font(12), width=2)
        self.icon.pack(side="left", padx=(12, 6), pady=9)
        self.label = tk.Label(self, text=text, font=font(11, "semibold"), anchor="w")
        self.label.pack(side="left", fill="x", expand=True)
        self.badge = tk.Label(self, text="", font=font(9, "bold"), padx=7, pady=1)
        self.badge.pack(side="right", padx=14)
        for widget in descendants(self):
            widget.bind("<Button-1>", lambda e: (command(), "break")[1])
            widget.configure(cursor="hand2")
        bind_hover(self, lambda: self._paint(True), lambda: self._paint(False))
        self._paint(False)

    def set_active(self, active):
        self.active = active
        self._paint(False)

    def set_badge(self, text, important=False):
        self.badge_text, self.badge_important = str(text) if text else "", important
        self._paint(False)

    def _paint(self, hover):
        bg = T.nav_active if self.active else (T.surface_alt if hover else T.sidebar)
        for widget in (self, self.icon, self.label):
            widget.configure(bg=bg)
        self.icon.configure(fg=T.accent if self.active else T.text3)
        self.label.configure(fg=T.accent if self.active else T.text)
        self.bar.configure(bg=T.accent if self.active else bg)
        if self.badge_text:
            badge_bg = T.important_soft if self.badge_important else (T.surface if self.active else T.surface_alt)
            self.badge.configure(text=self.badge_text, bg=badge_bg,
                                 fg=T.important if self.badge_important else T.text3)
        else:
            self.badge.configure(text="", bg=bg)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class NewsApp:
    def __init__(self, root):
        self.root = root
        self.settings = config.load_settings()
        theme.apply(self.settings["theme"])
        theme.setup_fonts(root, self.settings["text_size"])
        root.title("AI News Agent")
        root.geometry("1320x860")
        root.minsize(1000, 640)
        ScrollFrame.install_wheel(root)

        self.fetching = False
        self.compare_models = []
        self.current = "must"
        self.views = {}
        self.build()
        self.refresh()

    # --- layout -----------------------------------------------------------
    def build(self):
        """Create (or re-create, after a theme change) the whole window."""
        for child in self.root.winfo_children():
            child.destroy()
        self.root.configure(bg=T.bg)
        style_ttk(self.root)
        self._build_sidebar()
        main = tk.Frame(self.root, bg=T.bg)
        main.pack(side="left", fill="both", expand=True)
        self._build_topbar(main)
        self._build_statusbar(main)
        content = tk.Frame(main, bg=T.bg)
        content.pack(fill="both", expand=True)
        self.views = {
            "must": MustKnowView(content, self),
            "today": TodayView(content, self),
            "news": NewsView(content, self),
            "saved": NewsView(content, self, saved_only=True),
            "models": ModelsView(content, self),
            "compare": CompareView(content, self),
        }
        self.show(self.current)
        self.update_counts()

    def _build_sidebar(self):
        side = tk.Frame(self.root, bg=T.sidebar, width=round(240 * theme.SCALE))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(self.root, bg=T.border, width=1).pack(side="left", fill="y")

        brand = tk.Frame(side, bg=T.sidebar, padx=22, pady=22)
        brand.pack(fill="x")
        tk.Label(brand, text="◆", bg=T.sidebar, fg=T.accent, font=font(20, "bold")).pack(side="left")
        names = tk.Frame(brand, bg=T.sidebar)
        names.pack(side="left", padx=10)
        tk.Label(names, text="AI News Agent", bg=T.sidebar, fg=T.text, font=font(13, "bold")).pack(anchor="w")
        tk.Label(names, text="Your daily AI briefing", bg=T.sidebar, fg=T.text3, font=font(9)).pack(anchor="w")

        self.nav = {}
        for key, icon, text in NAV:
            item = NavItem(side, icon, text, lambda k=key: self.show(k))
            item.pack(fill="x", padx=10, pady=1)
            self.nav[key] = item

        tk.Label(side, text="TOPICS THIS WEEK", bg=T.sidebar, fg=T.text3, font=font(8, "bold")).pack(
            anchor="w", padx=26, pady=(26, 6))
        self.topic_counts = {}
        for category in analyzer.CATEGORIES:
            row = tk.Frame(side, bg=T.sidebar, padx=16, pady=4)
            row.pack(fill="x", padx=10)
            tk.Label(row, text="●", bg=T.sidebar, fg=theme.category_color(category), font=font(9)).pack(side="left")
            tk.Label(row, text=category, bg=T.sidebar, fg=T.text2, font=font(10)).pack(side="left", padx=8)
            count = tk.Label(row, text="", bg=T.sidebar, fg=T.text3, font=font(9))
            count.pack(side="right")
            self.topic_counts[category] = count
            for widget in descendants(row):
                widget.bind("<Button-1>", lambda e, c=category: self.open_category(c))
                widget.configure(cursor="hand2")
            bind_hover(row, lambda r=row: recolor(r, T.surface_alt), lambda r=row: recolor(r, T.sidebar))

        bottom = tk.Frame(side, bg=T.sidebar, padx=10, pady=14)
        bottom.pack(side="bottom", fill="x")
        divider(bottom, pady=(0, 10))
        dark = self.settings["theme"] == "dark"
        Button(bottom, "☀   Light mode" if dark else "☾   Dark mode", self.toggle_theme, kind="ghost", bg=T.sidebar,
               size=10, anchor="w", padx=14, pady=7).pack(fill="x")
        large = self.settings["text_size"] == "large"
        Button(bottom, "A   Normal text size" if large else "A+  Larger text", self.toggle_text_size, kind="ghost",
               bg=T.sidebar, size=10, anchor="w", padx=14, pady=7).pack(fill="x")

    def _build_topbar(self, parent):
        bar = tk.Frame(parent, bg=T.surface, padx=28, pady=12)
        bar.pack(fill="x")
        self.search_var = tk.StringVar()
        SearchBox(bar, self.search_var, "Search stories, models or sources…  (Enter)", width=44,
                  on_submit=self._global_search).pack(side="left")
        self.refresh_btn = Button(bar, "Fetching…" if self.fetching else "↻  Refresh", self.refresh, kind="primary",
                                  padx=18, pady=7)
        self.refresh_btn.pack(side="right")
        self.updated_var = tk.StringVar()
        tk.Label(bar, textvariable=self.updated_var, bg=T.surface, fg=T.text3, font=font(10)).pack(side="right",
                                                                                                padx=16)
        divider(parent)

    def _build_statusbar(self, parent):
        bar = tk.Frame(parent, bg=T.surface)
        bar.pack(fill="x", side="bottom")
        tk.Frame(bar, bg=T.border, height=1).pack(fill="x")
        previous = self.status_var.get() if hasattr(self, "status_var") else "Loading…"
        self.status_var = tk.StringVar(value=previous)
        tk.Label(bar, textvariable=self.status_var, bg=T.surface, fg=T.text3, anchor="w", font=font(9),
                 padx=18, pady=5).pack(fill="x")

    # --- settings ---------------------------------------------------------
    def toggle_theme(self):
        self.settings["theme"] = "light" if self.settings["theme"] == "dark" else "dark"
        config.save_settings(self.settings)
        theme.apply(self.settings["theme"])
        self.build()

    def toggle_text_size(self):
        self.settings["text_size"] = "normal" if self.settings["text_size"] == "large" else "large"
        config.save_settings(self.settings)
        theme.setup_fonts(self.root, self.settings["text_size"])
        self.build()

    # --- navigation -------------------------------------------------------
    def show(self, key):
        for name, view in self.views.items():
            view.pack_forget()
            self.nav[name].set_active(name == key)
        self.current = key
        self.views[key].pack(fill="both", expand=True)
        self.views[key].load()
        self.update_timestamp()

    def open_category(self, category):
        self.views["news"].set_filters(category=category, hours=168)
        self.show("news")

    def open_model_news(self, model):
        self.views["news"].set_filters(search=model, hours=None)
        self.show("news")

    def _global_search(self):
        query = self.search_var.get().strip()
        self.views["news"].set_filters(search=query, hours=None)
        self.search_var.set("")
        self.show("news")

    def compare(self, models):
        for model in models:
            if model not in self.compare_models:
                self.compare_models.append(model)
        self.compare_models = self.compare_models[-5:]
        self.show("compare")

    def toggle_bookmark(self, article, button):
        article["bookmarked"] = 0 if article["bookmarked"] else 1
        db.set_bookmark(article["id"], article["bookmarked"])
        paint_save(button, article["bookmarked"])
        self.nav["saved"].set_badge(db.count_saved())

    # --- data -------------------------------------------------------------
    def refresh(self):
        if self.fetching:
            return
        self.fetching = True
        self.refresh_btn.configure(text="Fetching…")
        self.status_var.set("Fetching the latest AI news…")
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        try:
            count = fetcher.fetch_all(progress=lambda m: self.root.after(0, lambda: self.status_var.set(m)))
            self.root.after(0, self._after_fetch, f"Fetched {count} new articles.")
        except Exception as e:
            self.root.after(0, self._after_fetch, f"Fetch failed: {e}")

    def _after_fetch(self, message):
        self.fetching = False
        self.refresh_btn.configure(text="↻  Refresh")
        self.status_var.set(f"{message}  ·  {db.count_articles()} articles stored")
        self.views[self.current].load()
        self.update_counts()
        self.update_timestamp()

    def update_timestamp(self):
        last = db.stats(24)["last_fetch"]
        self.updated_var.set(f"Updated {time_ago(last)}" if last else "Not fetched yet")

    def update_counts(self):
        picks, _ = load_must_know()
        self.nav["must"].set_badge(len(picks), important=True)
        self.nav["saved"].set_badge(db.count_saved())
        counts = db.category_counts(24 * 7)
        for category, count_label in self.topic_counts.items():
            count_label.configure(text=str(counts.get(category, 0) or ""))

    # --- shared rendering -------------------------------------------------
    def render_card(self, scroll, article, duplicates=(), gist=None, must_know=False):
        """A story card: topic, source, headline, gist, models and actions."""
        color = theme.category_color(article["category"])
        card = Card(scroll.inner, padx=22, pady=18)
        card.pack(fill="x", pady=6)

        meta = tk.Frame(card, bg=T.surface)
        meta.pack(fill="x")
        pill(meta, article["category"], color).pack(side="left")
        sources = analyzer.story_sources(article, duplicates)
        info = f"{article['source']}   ·   {time_ago(article['published_at'])}"
        if len(sources) > 1:
            info += f"   ·   {len(sources)} sources"
        label(meta, info, 10, fg=T.text3).pack(side="left", padx=12)
        if must_know:
            tk.Label(meta, text="★ Must know", bg=T.important_soft, fg=T.important, font=font(9, "bold"),
                     padx=8, pady=2).pack(side="right")
        elif article["score"] >= 60:
            label(meta, "High impact", 9, "bold", fg=T.important).pack(side="right")

        title = label(card, article["title"], 14, "semibold", cursor="hand2")
        title.pack(fill="x", pady=(10, 0))
        scroll.wrap(title, 50)
        title.bind("<Button-1>", lambda e: open_url(article["link"]))
        title.bind("<Enter>", lambda e: title.configure(fg=T.accent))
        title.bind("<Leave>", lambda e: title.configure(fg=T.text))

        gist = story_gist(article, duplicates) if gist is None else gist
        if gist:
            text = label(card, gist, 11, fg=T.text2)
            text.pack(fill="x", pady=(6, 0))
            scroll.wrap(text, 50)
        others = [s for s in sources if s != article["source"]]
        if others:
            label(card, "Also covered by " + ", ".join(others[:4]) + (" …" if len(others) > 4 else ""), 10,
                  fg=T.text3).pack(fill="x", pady=(6, 0))

        footer = tk.Frame(card, bg=T.surface)
        footer.pack(fill="x", pady=(14, 0))
        Button(footer, "Read story ↗", lambda: open_url(article["link"]), kind="secondary", size=10, padx=12,
               pady=4).pack(side="left")
        save = Button(footer, "", kind="quiet", size=10, padx=10, pady=4)
        save.command = lambda: self.toggle_bookmark(article, save)
        paint_save(save, article["bookmarked"])
        save.pack(side="left", padx=(8, 0))
        models = article["models"][:4]
        if models:
            Button(footer, "⇄ Compare", lambda: self.compare(models), kind="quiet", size=10, padx=10,
                   pady=4).pack(side="left")
            for model in reversed(models):
                pill(footer, model, theme.category_color("Model Release"),
                     command=lambda m=model: self.compare([m])).pack(side="right", padx=(6, 0))
        return card

    def story_row(self, parent, scroll, article, duplicates=(), gist=None, rank=None, margin=48, last=False):
        """A compact one-story row: topic and source, headline, one-line gist. Click to open."""
        color = theme.category_color(article["category"])
        row = tk.Frame(parent, bg=T.surface, padx=20, pady=13)
        row.pack(fill="x")
        meta = tk.Frame(row, bg=T.surface)
        meta.pack(fill="x")
        if rank:
            label(meta, str(rank), 10, "bold", fg=T.important).pack(side="left", padx=(0, 8))
        label(meta, "●  " + article["category"].upper(), 8, "bold", fg=color).pack(side="left")
        sources = analyzer.story_sources(article, duplicates)
        info = f"{article['source']}  ·  {time_ago(article['published_at'])}"
        if len(sources) > 1:
            info += f"  ·  {len(sources)} sources"
        label(meta, info, 9, fg=T.text3).pack(side="left", padx=10)
        title = label(row, article["title"], 12, "semibold")
        title.pack(fill="x", pady=(5, 0))
        scroll.wrap(title, margin)
        gist = story_gist(article, duplicates, limit=200) if gist is None else analyzer.short_gist(gist, 220)
        if gist:
            text = label(row, gist, 11, fg=T.text2)
            text.pack(fill="x", pady=(3, 0))
            scroll.wrap(text, margin)
        for widget in descendants(row):
            widget.bind("<Button-1>", lambda e: open_url(article["link"]))
            widget.configure(cursor="hand2")
        bind_hover(row, lambda: (recolor(row, T.surface_alt), title.configure(fg=T.accent)),
                   lambda: (recolor(row, T.surface), title.configure(fg=T.text)))
        if not last:
            tk.Frame(parent, bg=T.border, height=1).pack(fill="x", padx=20)
        return row


def paint_save(button, saved):
    button.configure(text="★ Saved" if saved else "☆ Save")
    button.fg_override = T.star if saved else None
    button.repaint()


# ---------------------------------------------------------------------------
# Must know
# ---------------------------------------------------------------------------

class MustKnowView(tk.Frame):
    """The few stories you should know about, each explained, plus a one-line gist of everything else."""

    def __init__(self, parent, app):
        super().__init__(parent, bg=T.bg)
        self.app = app
        self.scroll = ScrollFrame(self, max_width=900)
        self.scroll.pack(fill="both", expand=True)
        self.ai_running = False
        self.ai_status = tk.StringVar()
        self.status_label = self.status_anchor = None
        self.ai_status.trace_add("write", lambda *_: self._show_status())

    def _show_status(self):
        """The progress line only takes up space while there is something to say."""
        if self.status_label is not None and self.status_label.winfo_exists():
            if self.ai_status.get():
                self.status_label.pack(fill="x", pady=(8, 0), after=self.status_anchor)
            else:
                self.status_label.pack_forget()

    def load(self):
        self.scroll.clear()
        inner = self.scroll.inner
        picks, rest = load_must_know()
        self.picks, self.rest = picks, rest
        try:
            digest = ai_brief.get_must_know_digest()
        except Exception:
            digest = None
        available, _ = ai_brief.availability()

        today = datetime.date.today().strftime("%A, %B %d")
        actions = page_header(inner, "Must know", f"{today}   ·   the stories worth your attention right now")
        if available and picks:
            Button(actions, "↻ Update AI explanations" if digest else "✦ Explain with AI", self._run_ai,
                   kind="secondary", bg=T.bg).pack()

        self._intro(inner, digest, available, bool(picks))
        if not picks:
            empty_state(inner, "Nothing to catch up on yet", "Click Refresh to fetch the latest AI news.", "★")
            return

        facts = db.article_facts([item["lead"]["id"] for item in picks])
        for rank, item in enumerate(picks, start=1):
            ai_item = (digest or {}).get("items", {}).get(item["lead"]["id"])
            self._must_card(inner, rank, item, ai_item, facts.get(item["lead"]["id"], []))

        if rest:
            actions = section_header(inner, "Everything else, in one line", f"{len(rest)} more stories", top=36)
            Button(actions, "See all news  →", lambda: self.app.show("news"), kind="link", bg=T.bg,
                   padx=0).pack()
            box = Card(inner, padx=0, pady=4, hover=False)
            box.pack(fill="x", pady=(0, 32))
            shown = rest[:30]
            ai_gists = (digest or {}).get("gists")
            for index, (lead, dupes) in enumerate(shown):
                self.app.story_row(box, self.scroll, lead, dupes, gist=story_gist(lead, dupes, ai_gists),
                                   last=index == len(shown) - 1)

    def _intro(self, inner, digest, available, has_stories):
        """The AI bottom line when one has been written, otherwise a short explanation of the page."""
        if digest and digest.get("bottom_line"):
            box = Card(inner, padx=22, pady=18, hover=False, bg=T.accent_soft, border=T.accent_soft)
            box.pack(fill="x", pady=(14, 8))
            eyebrow(box, "✦  The bottom line", color=T.accent, bg=T.accent_soft).pack(anchor="w")
            text = label(box, digest["bottom_line"], 12, fg=T.text, bg=T.accent_soft)
            text.pack(fill="x", pady=(6, 0))
            self.scroll.wrap(text, 50)
            self.status_anchor = label(box, f"Written by AI from today's coverage at {digest['created_at']} UTC. "
                                            "Check the sources for anything important.", 9, fg=T.text3,
                                       bg=T.accent_soft)
            self.status_anchor.pack(fill="x", pady=(8, 0))
            self.status_label = label(box, "", 10, "semibold", fg=T.accent, bg=T.accent_soft,
                                      textvariable=self.ai_status)
            self._show_status()
            return
        note = ("Ranked by importance: model launches, official announcements, how many outlets cover a story, "
                "benchmark numbers and recency.")
        if available and has_stories:
            note += "  ✦ Explain with AI writes what happened and why it matters for each story (uses your " \
                    "Anthropic API key)."
        text = label(inner, note, 10, fg=T.text3, bg=T.bg)
        text.pack(fill="x", pady=(8, 4))
        self.scroll.wrap(text, 0)
        self.status_anchor = text
        self.status_label = label(inner, "", 10, "semibold", fg=T.accent, bg=T.bg, textvariable=self.ai_status)
        self._show_status()

    def _must_card(self, inner, rank, item, ai_item, facts):
        lead, duplicates, sources = item["lead"], item["duplicates"], item["sources"]
        color = theme.category_color(lead["category"])
        card = Card(inner, padx=0, pady=0)
        card.pack(fill="x", pady=8)
        tk.Frame(card, bg=T.important if rank <= 3 else T.border_strong, width=4).pack(side="left", fill="y")
        body = tk.Frame(card, bg=T.surface, padx=24, pady=20)
        body.pack(side="left", fill="both", expand=True)
        margin = 60

        top = tk.Frame(body, bg=T.surface)
        top.pack(fill="x")
        label(top, f"#{rank}", 13, "bold", fg=T.important).pack(side="left", padx=(0, 10))
        pill(top, lead["category"], color).pack(side="left")
        info = f"{lead['source']}   ·   {time_ago(lead['published_at'])}"
        if len(sources) > 1:
            info += f"   ·   {len(sources)} sources"
        label(top, info, 10, fg=T.text3).pack(side="left", padx=12)
        if ai_item:
            label(top, "✦ AI explained", 9, "bold", fg=T.accent).pack(side="right")

        title = label(body, lead["title"], 17, "bold", cursor="hand2")
        title.pack(fill="x", pady=(12, 0))
        self.scroll.wrap(title, margin)
        title.bind("<Button-1>", lambda e: open_url(lead["link"]))
        title.bind("<Enter>", lambda e: title.configure(fg=T.accent))
        title.bind("<Leave>", lambda e: title.configure(fg=T.text))

        what = ai_item["what"] if ai_item else story_gist(lead, duplicates, limit=420)
        if what:
            text = label(body, what, 12, fg=T.text2)
            text.pack(fill="x", pady=(8, 0))
            self.scroll.wrap(text, margin)

        # Why it matters
        why_box = tk.Frame(body, bg=T.important_soft, padx=16, pady=12)
        why_box.pack(fill="x", pady=(14, 0))
        eyebrow(why_box, "Why it matters", color=T.important, bg=T.important_soft).pack(anchor="w")
        if ai_item and ai_item.get("why"):
            text = label(why_box, ai_item["why"], 11, fg=T.text, bg=T.important_soft)
            text.pack(fill="x", pady=(4, 0))
            self.scroll.wrap(text, margin + 40)
        else:
            kind = config.SOURCE_KINDS.get(lead["source"], "news")
            for reason in analyzer.why_it_matters(lead, sources, facts, kind):
                row = tk.Frame(why_box, bg=T.important_soft)
                row.pack(fill="x", pady=(4, 0))
                label(row, "•", 11, "bold", fg=T.important, bg=T.important_soft).pack(side="left", anchor="n")
                text = label(row, reason, 11, fg=T.text, bg=T.important_soft)
                text.pack(side="left", fill="x", padx=(8, 0))
                self.scroll.wrap(text, margin + 60)

        # Key numbers
        numbers, seen = [], set()
        for fact in facts:
            key = (fact["model"], fact["name"], round(fact["value"], 2))
            if key in seen:
                continue
            seen.add(key)
            numbers.append(analyzer.fact_text(fact, with_model=True))
        if numbers:
            eyebrow(body, "Key numbers").pack(anchor="w", pady=(16, 6))
            chips_frame = tk.Frame(body, bg=T.surface, height=1)
            chips_frame.pack(fill="x")
            chips = [tk.Label(chips_frame, text=n, bg=T.good_soft, fg=T.good, font=font(10, "semibold"),
                              padx=10, pady=4) for n in numbers[:8]]
            flow(chips_frame, chips)

        # Coverage
        if duplicates:
            eyebrow(body, f"Coverage from {len(sources)} sources").pack(anchor="w", pady=(16, 4))
            for article in [lead] + duplicates[:4]:
                row = tk.Frame(body, bg=T.surface, cursor="hand2")
                row.pack(fill="x", pady=1)
                label(row, shorten(article["source"], 24), 10, "semibold", fg=T.text2, width=24).pack(
                    side="left", anchor="n")
                link = label(row, shorten(article["title"], 110) + "  ↗", 10, fg=T.text3, cursor="hand2")
                link.pack(side="left", fill="x")
                for widget in (row, link):
                    widget.bind("<Button-1>", lambda e, url=article["link"]: open_url(url))
                link.bind("<Enter>", lambda e, w=link: w.configure(fg=T.accent))
                link.bind("<Leave>", lambda e, w=link: w.configure(fg=T.text3))

        footer = tk.Frame(body, bg=T.surface)
        footer.pack(fill="x", pady=(18, 0))
        Button(footer, "Read full story ↗", lambda: open_url(lead["link"]), kind="primary", size=10, padx=14,
               pady=5).pack(side="left")
        save = Button(footer, "", kind="quiet", size=10, padx=12, pady=5)
        save.command = lambda: self.app.toggle_bookmark(lead, save)
        paint_save(save, lead["bookmarked"])
        save.pack(side="left", padx=(8, 0))
        models = lead["models"][:4]
        if models:
            Button(footer, "⇄ Compare models", lambda: self.app.compare(models), kind="quiet", size=10, padx=10,
                   pady=5).pack(side="left")
            for model in reversed(models):
                pill(footer, model, theme.category_color("Model Release"),
                     command=lambda m=model: self.app.compare([m])).pack(side="right", padx=(6, 0))

    def _run_ai(self):
        if self.ai_running:
            return
        self.ai_running = True
        self.ai_status.set("✦ Reading today's coverage and writing explanations… this can take a minute.")
        picks, rest = self.picks, self.rest

        def worker():
            try:
                ai_brief.generate_must_know(picks, rest)
                self.after(0, self._ai_done, None)
            except Exception as e:
                self.after(0, self._ai_done, ai_brief.describe_error(e))

        threading.Thread(target=worker, daemon=True).start()

    def _ai_done(self, error):
        self.ai_running = False
        if not self.winfo_exists():
            return
        if error:
            self.ai_status.set(f"Could not write the explanations: {error}")
            return
        self.ai_status.set("")
        if self.app.current == "must":
            self.load()


# ---------------------------------------------------------------------------
# Today
# ---------------------------------------------------------------------------

class TodayView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=T.bg)
        self.app = app
        self.scroll = ScrollFrame(self, max_width=1040)
        self.scroll.pack(fill="both", expand=True)

    def load(self):
        self.scroll.clear()
        inner = self.scroll.inner
        now = datetime.datetime.now()
        greeting = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 18 else "Good evening"
        page_header(inner, greeting, now.strftime("%A, %B %d") + "   ·   here's what's happening in AI")

        day, week = db.stats(24), db.stats(24 * 7)
        tiles = tk.Frame(inner, bg=T.bg)
        tiles.pack(fill="x", pady=(16, 0))
        for column in range(4):
            tiles.columnconfigure(column, weight=1, uniform="tile")
        for column, (value, text, color) in enumerate((
            (day["articles"], "stories in the last 24 hours", T.accent),
            (week["releases"], "model-release stories this week", theme.category_color("Model Release")),
            (week["models"], "AI models in the news this week", T.good),
            (day["sources"], "sources reporting today", T.important),
        )):
            tile = Card(tiles, padx=20, pady=16, hover=False)
            tile.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 6, 0 if column == 3 else 6))
            tk.Label(tile, text=str(value), bg=T.surface, fg=color, font=font(26, "bold")).pack(anchor="w")
            text_label = label(tile, text, 10, fg=T.text3)
            text_label.pack(anchor="w", fill="x")
            self.scroll.wrap(text_label, 820)

        self._must_know(inner)
        self._releases(inner)
        self._just_in(inner)
        self._topics(inner)

    def _must_know(self, inner):
        picks, _ = load_must_know(limit=3)
        actions = section_header(inner, "Must know right now", "the top stories, in brief")
        Button(actions, "Open Must know  →", lambda: self.app.show("must"), kind="link", bg=T.bg, padx=0).pack()
        if not picks:
            label(inner, "No stories yet. Click Refresh to fetch the latest AI news.", 11, fg=T.text3,
                  bg=T.bg).pack(anchor="w")
            return
        box = Card(inner, padx=0, pady=4, hover=False)
        box.pack(fill="x")
        for index, item in enumerate(picks):
            self.app.story_row(box, self.scroll, item["lead"], item["duplicates"], rank=index + 1,
                               last=index == len(picks) - 1)

    def _releases(self, inner):
        releases = db.model_leaderboard(hours=24 * 7, releases_only=True, limit=6)
        actions = section_header(inner, "New model releases", "detected this week")
        if releases:
            Button(actions, "Compare these  ⇄", lambda: self.app.compare([r["model"] for r in releases[:4]]),
                   kind="link", bg=T.bg, padx=0).pack()
        else:
            label(inner, "No model launches detected this week yet.", 11, fg=T.text3, bg=T.bg).pack(anchor="w")
            return
        facts = db.model_facts([r["model"] for r in releases])
        grid = tk.Frame(inner, bg=T.bg)
        grid.pack(fill="x")
        for column in range(3):
            grid.columnconfigure(column, weight=1, uniform="release")
        for index, release in enumerate(releases):
            column = index % 3
            card = Card(grid, padx=18, pady=16)
            card.grid(row=index // 3, column=column, sticky="nsew", pady=6,
                      padx=(0 if column == 0 else 6, 0 if column == 2 else 6))
            label(card, (release["developer"] or release["family"] or "").upper(), 8, "bold",
                  fg=theme.category_color("Model Release")).pack(anchor="w")
            label(card, release["model"], 15, "bold").pack(anchor="w", pady=(2, 0))
            label(card, f"{release['mentions']} stories  ·  {release['sources']} sources  ·  first seen "
                        f"{time_ago(release['first_seen'])}", 9, fg=T.text3).pack(anchor="w", pady=(2, 0))
            highlights = summarize_facts(facts.get(release["model"], []), limit=3)
            if highlights:
                divider(card, pady=(10, 6))
            for name, value in highlights:
                row = tk.Frame(card, bg=T.surface)
                row.pack(fill="x", pady=1)
                label(row, name, 10, fg=T.text2).pack(side="left")
                label(row, value, 10, "bold", fg=T.good).pack(side="right")
            buttons = tk.Frame(card, bg=T.surface)
            buttons.pack(fill="x", pady=(12, 0))
            Button(buttons, "Compare", lambda m=release["model"]: self.app.compare([m]), kind="secondary",
                   size=9, padx=10, pady=3).pack(side="left")
            Button(buttons, "News", lambda m=release["model"]: self.app.open_model_news(m), kind="quiet",
                   size=9, padx=10, pady=3).pack(side="left", padx=4)

    def _just_in(self, inner):
        articles = db.query_articles(hours=24, sort="latest", limit=40)
        clusters = analyzer.cluster_articles(articles)[:8]
        actions = section_header(inner, "Just in", "the latest stories, with a one-line gist")
        Button(actions, "All news  →", lambda: self.app.show("news"), kind="link", bg=T.bg, padx=0).pack()
        if not clusters:
            label(inner, "Nothing new in the last 24 hours.", 11, fg=T.text3, bg=T.bg).pack(anchor="w")
            return
        box = Card(inner, padx=0, pady=4, hover=False)
        box.pack(fill="x")
        for index, (lead, dupes) in enumerate(clusters):
            self.app.story_row(box, self.scroll, lead, dupes, last=index == len(clusters) - 1)

    def _topics(self, inner):
        counts = db.category_counts(24 * 7)
        if not counts:
            return
        section_header(inner, "This week by topic", "click a topic to read it")
        box = Card(inner, padx=22, pady=16, hover=False)
        box.pack(fill="x", pady=(0, 32))
        top = max(counts.values())
        for category in analyzer.CATEGORIES:
            count = counts.get(category, 0)
            color = theme.category_color(category)
            row = tk.Frame(box, bg=T.surface, cursor="hand2", pady=4)
            row.pack(fill="x")
            name = label(row, category, 11, fg=T.text2, width=20)
            name.pack(side="left")
            bar = tk.Canvas(row, bg=T.surface, height=16, highlightthickness=0, cursor="hand2")
            bar.pack(side="left", fill="x", expand=True, padx=10)
            bar.bind("<Configure>", lambda e, b=bar, c=count, col=color: (
                b.delete("all"),
                b.create_rectangle(0, 3, e.width, 13, fill=T.surface_alt, width=0),
                b.create_rectangle(0, 3, max(4, e.width * c / top), 13, fill=col, width=0)))
            label(row, str(count), 11, "bold", width=5, anchor="e").pack(side="right")
            for widget in descendants(row):
                widget.bind("<Button-1>", lambda e, c=category: self.app.open_category(c))


# ---------------------------------------------------------------------------
# All news / Saved
# ---------------------------------------------------------------------------

class NewsView(tk.Frame):
    def __init__(self, parent, app, saved_only=False):
        super().__init__(parent, bg=T.bg)
        self.app = app
        self.saved_only = saved_only
        self.category = "All"
        self.limit = PAGE_SIZE
        self._search_job = None

        column = Column(self, max_width=980)
        column.pack(fill="x")
        top = column.inner
        head = tk.Frame(top, bg=T.bg)
        head.pack(fill="x", pady=(28, 4))
        tk.Label(head, text="Saved" if saved_only else "All news", bg=T.bg, fg=T.text,
                 font=font(22, "bold")).pack(side="left")
        self.count_var = tk.StringVar()
        tk.Label(head, textvariable=self.count_var, bg=T.bg, fg=T.text3, font=font(11)).pack(
            side="left", padx=14, pady=(8, 0))

        filters = tk.Frame(top, bg=T.bg)
        filters.pack(fill="x", pady=(10, 4))
        self.search_var = tk.StringVar()
        SearchBox(filters, self.search_var, "Filter stories", width=22).pack(side="left")
        self.search_var.trace_add("write", lambda *_: self._debounced_reload())

        self.range_var = tk.StringVar(value="All time" if saved_only else "Last 3 days")
        self.sort_var = tk.StringVar(value="Top")
        self.source_var = tk.StringVar(value="All sources")
        range_box = ttk.Combobox(filters, textvariable=self.range_var, values=list(RANGES), width=12,
                                 state="readonly", font=font(10))
        range_box.pack(side="left", padx=(10, 0), ipady=2)
        range_box.bind("<<ComboboxSelected>>", lambda e: self.reload())
        self.source_combo = ttk.Combobox(filters, textvariable=self.source_var, values=["All sources"], width=22,
                                         state="readonly", font=font(10))
        self.source_combo.pack(side="left", padx=(10, 0), ipady=2)
        self.source_combo.bind("<<ComboboxSelected>>", lambda e: self.reload())
        Segmented(filters, ["Top", "Latest"], self.sort_var, self.reload).pack(side="right")

        self.chips = tk.Frame(top, bg=T.bg, height=34)
        self.chips.pack(fill="x", pady=(12, 8))
        self.scroll = ScrollFrame(self, max_width=980)
        self.scroll.pack(fill="both", expand=True)

    def set_filters(self, category="All", search="", hours="keep"):
        self.category = category
        self.search_var.set(search)
        if hours is None:
            self.range_var.set("All time")
        elif hours != "keep":
            self.range_var.set(next((k for k, v in RANGES.items() if v == hours), self.range_var.get()))

    def _debounced_reload(self):
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(300, self.reload)

    def load(self):
        self.reload()

    def reload(self):
        self.limit = PAGE_SIZE
        self._render()

    def _source(self):
        source = self.source_var.get()
        return None if source == "All sources" else source

    def _render(self):
        hours = RANGES[self.range_var.get()]
        search = self.search_var.get().strip()
        sources = db.get_sources(hours)
        self.source_combo["values"] = ["All sources"] + sources
        if self._source() not in sources:
            self.source_var.set("All sources")

        articles = db.query_articles(
            hours=hours, category=self.category, source=self._source(), search=search or None,
            saved_only=self.saved_only, sort="top" if self.sort_var.get() == "Top" else "latest",
        )
        self._render_chips(hours, search)
        clusters = analyzer.cluster_articles(articles) if self.sort_var.get() == "Top" else [(a, []) for a in articles]
        stories = f" in {len(clusters)} stories" if len(clusters) != len(articles) else ""
        self.count_var.set(f"{len(articles)} articles{stories}")

        self.scroll.clear()
        if not clusters:
            if self.saved_only:
                empty_state(self.scroll.inner, "Nothing saved yet", "Use ☆ Save on any story to keep it here.", "♥")
            else:
                empty_state(self.scroll.inner, "No matching stories",
                            "Try a longer time range, another topic, or click Refresh.", "⌕")
            return
        for lead, dupes in clusters[:self.limit]:
            self.app.render_card(self.scroll, lead, dupes)
        if len(clusters) > self.limit:
            Button(self.scroll.inner, f"Show more  ({len(clusters) - self.limit} remaining)", self._show_more,
                   kind="secondary", bg=T.bg).pack(pady=18)
        tk.Frame(self.scroll.inner, bg=T.bg, height=24).pack()

    def _show_more(self):
        position = self.scroll.canvas.yview()[0]
        self.limit += PAGE_SIZE
        self._render()
        self.after(50, lambda: self.scroll.canvas.yview_moveto(position))

    def _render_chips(self, hours, search):
        for child in self.chips.winfo_children():
            child.destroy()
        counts = Counter()
        for article in db.query_articles(hours=hours, search=search or None, saved_only=self.saved_only,
                                         source=self._source()):
            counts[article["category"]] += 1
        chips = [("All", sum(counts.values()), T.text)] + [
            (c, counts[c], theme.category_color(c)) for c in analyzer.CATEGORIES if counts[c] or c == self.category
        ]
        widgets = []
        for name, count, color in chips:
            active = name == self.category
            chip = tk.Label(self.chips, text=f"{name}   {count}", font=font(10, "semibold"), padx=12, pady=5,
                            cursor="hand2", bg=color if active else T.surface, fg=T.surface if active else color,
                            highlightthickness=1, highlightbackground=color if active else T.border_strong)
            chip.bind("<Button-1>", lambda e, n=name: self._select_category(n))
            widgets.append(chip)
        flow(self.chips, widgets)

    def _select_category(self, name):
        self.category = name
        self.reload()


# ---------------------------------------------------------------------------
# Model tracker
# ---------------------------------------------------------------------------

class ModelsView(tk.Frame):
    COLUMNS = ("model", "developer", "status", "first", "mentions", "sources", "highlights")

    def __init__(self, parent, app):
        super().__init__(parent, bg=T.bg)
        self.app = app
        head = tk.Frame(self, bg=T.bg)
        head.pack(fill="x", padx=36, pady=(28, 4))
        tk.Label(head, text="Model tracker", bg=T.bg, fg=T.text, font=font(22, "bold")).pack(anchor="w")
        tk.Label(head, text="Every AI model mentioned in the news, with the benchmarks and specs pulled from "
                            "the coverage", bg=T.bg, fg=T.text3, font=font(11)).pack(anchor="w", pady=(2, 0))

        controls = tk.Frame(self, bg=T.bg)
        controls.pack(fill="x", padx=36, pady=(14, 10))
        self.range_var = tk.StringVar(value="Last 30 days")
        combo = ttk.Combobox(controls, textvariable=self.range_var, values=list(RANGES)[1:], width=12,
                             state="readonly", font=font(10))
        combo.pack(side="left", ipady=2)
        combo.bind("<<ComboboxSelected>>", lambda e: self.load())
        self.scope_var = tk.StringVar(value="All models")
        Segmented(controls, ["All models", "New releases"], self.scope_var, self.load).pack(side="left", padx=10)
        self.compare_btn = Button(controls, "⇄  Compare selected", self._compare_selected, kind="primary", bg=T.bg)
        self.compare_btn.pack(side="right")
        tk.Label(controls, text="Select up to 5 rows (Ctrl/Shift-click), or double-click one", bg=T.bg,
                 fg=T.text3, font=font(10)).pack(side="right", padx=12)

        table = tk.Frame(self, bg=T.border, padx=1, pady=1)
        table.pack(fill="both", expand=True, padx=36, pady=(0, 10))
        self.tree = ttk.Treeview(table, columns=self.COLUMNS, show="headings", selectmode="extended")
        for column, heading, width, anchor in (
            ("model", "Model", 200, "w"), ("developer", "Developer", 120, "w"), ("status", "Status", 120, "w"),
            ("first", "First seen", 100, "w"), ("mentions", "Stories", 80, "center"),
            ("sources", "Sources", 80, "center"), ("highlights", "Extracted highlights", 380, "w"),
        ):
            self.tree.heading(column, text=heading, anchor=anchor)
            self.tree.column(column, width=width, anchor=anchor, stretch=column == "highlights")
        self.tree.tag_configure("release", foreground=theme.category_color("Model Release"))
        self.tree.tag_configure("odd", background=theme.mix(T.surface, T.surface_alt, 0.6))
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._compare_selected())

        self.detail = ScrollFrame(self, max_width=4000, gutter=36)
        self.detail.configure(height=230)
        self.detail.pack(fill="x")
        self.detail.pack_propagate(False)

    def load(self):
        self.tree.delete(*self.tree.get_children())
        rows = db.model_leaderboard(hours=RANGES[self.range_var.get()],
                                    releases_only=self.scope_var.get() == "New releases")
        facts = db.model_facts([r["model"] for r in rows])
        for index, row in enumerate(rows):
            highlights = ",   ".join(f"{n} {v}" for n, v in summarize_facts(facts.get(row["model"], []), limit=3))
            released = row["release_mentions"] > 0
            tags = (("release",) if released else ()) + (("odd",) if index % 2 else ())
            self.tree.insert("", "end", iid=row["model"], tags=tags, values=(
                row["model"], row["developer"], "★ New release" if released else "In the news",
                local_time(row["first_seen"]).strftime("%b %d") if row["first_seen"] else "",
                row["mentions"], row["sources"], highlights or "—",
            ))
        self._show_detail(None)
        if not rows:
            self.app.status_var.set("No models detected in this range yet. Try a longer range or Refresh.")

    def _on_select(self, _):
        selection = self.tree.selection()
        self.compare_btn.configure(text=f"⇄  Compare selected ({len(selection)})" if selection
                                   else "⇄  Compare selected")
        self._show_detail(selection[-1] if selection else None)

    def _show_detail(self, model):
        self.detail.clear()
        inner = self.detail.inner
        if not model:
            label(inner, "Select a model to see its latest headlines.", 11, fg=T.text3, bg=T.bg).pack(
                anchor="w", pady=12)
            return
        label(inner, f"Latest on {model}", 13, "bold", bg=T.bg).pack(anchor="w", pady=(10, 6))
        for article in db.query_articles(model=model, sort="latest", limit=8):
            row = tk.Frame(inner, bg=T.bg, cursor="hand2")
            row.pack(fill="x", pady=2)
            label(row, time_ago(article["published_at"]), 10, fg=T.text3, bg=T.bg, width=10).pack(side="left")
            label(row, article["source"], 10, "semibold", fg=T.good, bg=T.bg, width=20).pack(side="left")
            title = label(row, shorten(article["title"], 120), 11, fg=T.text2, bg=T.bg, cursor="hand2")
            title.pack(side="left", fill="x")
            for widget in (row, title):
                widget.bind("<Button-1>", lambda e, link=article["link"]: open_url(link))
            title.bind("<Enter>", lambda e, t=title: t.configure(fg=T.accent))
            title.bind("<Leave>", lambda e, t=title: t.configure(fg=T.text2))

    def _compare_selected(self):
        selection = list(self.tree.selection())[:5]
        if selection:
            self.app.compare_models = []
            self.app.compare(selection)


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

class CompareView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=T.bg)
        self.app = app
        self.scroll = ScrollFrame(self, max_width=1100)
        self.scroll.pack(fill="both", expand=True)
        self.brief_running = False

    def load(self):
        self.scroll.clear()
        inner = self.scroll.inner
        models = self.app.compare_models
        page_header(inner, "Compare models", "Side-by-side specs and benchmark scores pulled from the news")

        picker = tk.Frame(inner, bg=T.bg)
        picker.pack(fill="x", pady=(14, 4))
        add_var = tk.StringVar()
        combo = ttk.Combobox(picker, textvariable=add_var, values=db.known_models(), width=26, font=font(10))
        combo.pack(side="left", ipady=2)
        combo.set("Add a model…")
        combo.bind("<FocusIn>", lambda e: add_var.get() == "Add a model…" and combo.set(""))

        def add(_=None):
            name = add_var.get().strip()
            if name and name != "Add a model…" and name not in models and len(models) < 5:
                self.app.compare_models.append(name)
                self.load()

        combo.bind("<<ComboboxSelected>>", add)
        combo.bind("<Return>", add)
        violet = theme.category_color("Model Release")
        for model in models:
            chip = tk.Frame(picker, bg=theme.soft(violet))
            chip.pack(side="left", padx=(8, 0))
            tk.Label(chip, text=model, bg=theme.soft(violet), fg=violet, font=font(10, "semibold"), padx=10,
                     pady=4).pack(side="left")
            remove = tk.Label(chip, text="✕", bg=theme.soft(violet), fg=violet, font=font(9), padx=8,
                              cursor="hand2")
            remove.pack(side="left")
            remove.bind("<Button-1>", lambda e, m=model: self._remove(m))
        if models:
            Button(picker, "Clear", self._clear, kind="quiet", bg=T.bg, size=10).pack(side="left", padx=8)

        if not models:
            suggestions = [r["model"] for r in db.model_leaderboard(hours=24 * 14, limit=4)]
            empty_state(inner, "Pick models to compare",
                        "Add up to five models above, or use ⇄ Compare on any story or in the Model tracker.", "⇄")
            if suggestions:
                Button(inner, f"Try:  {'  vs  '.join(suggestions)}", lambda: self.app.compare(suggestions),
                       kind="secondary", bg=T.bg).pack()
            return

        info = db.model_info(models)
        facts = db.model_facts(models)
        leaderboard = {r["model"]: r for r in db.model_leaderboard(hours=None) if r["model"] in models}
        self._table(inner, models, info, facts, leaderboard)
        self._brief(inner, models)
        self._evidence(inner, models, facts)

    def _remove(self, model):
        self.app.compare_models.remove(model)
        self.load()

    def _clear(self):
        self.app.compare_models = []
        self.load()

    def _table(self, inner, models, info, facts, leaderboard):
        rows = [
            ("Developer", [(info.get(m) or {}).get("developer") or "—" for m in models], None),
            ("First seen in news", [local_time(leaderboard[m]["first_seen"]).strftime("%b %d, %Y")
                                    if m in leaderboard and leaderboard[m]["first_seen"] else "—" for m in models], None),
            ("News stories", [str(leaderboard[m]["mentions"]) if m in leaderboard else "0" for m in models], "max"),
            ("Sources covering", [str(leaderboard[m]["sources"]) if m in leaderboard else "0" for m in models], "max"),
        ]
        best = {m: consensus_facts(facts.get(m, [])) for m in models}
        for kind, name, better in (("context", "Context window", "max"), ("price_in", "Input price", "min"),
                                   ("price_out", "Output price", "min")):
            rows.append((name, [best[m].get((kind, name)) for m in models], better))
        benchmarks = sorted({name for m in models for (kind, name) in best[m] if kind == "benchmark"},
                            key=lambda n: -sum(1 for m in models if ("benchmark", n) in best[m]))
        for name in benchmarks:
            rows.append((name, [best[m].get(("benchmark", name)) for m in models], "max"))

        section_header(inner, "At a glance", "★ marks the best value in each row", top=24)
        frame = tk.Frame(inner, bg=T.border, padx=1, pady=1)
        frame.pack(fill="x")
        for column in range(len(models) + 1):
            frame.columnconfigure(column, weight=1 if column else 0, uniform="cmp" if column else "")
        violet = theme.category_color("Model Release")
        for column, text in enumerate(["Metric"] + models):
            tk.Label(frame, text=text, bg=T.surface_alt, fg=violet if column else T.text2, font=font(11, "bold"),
                     anchor="w", padx=14, pady=10).grid(row=0, column=column, sticky="nsew",
                                                        padx=(0, 1), pady=(0, 1))
        stripe = theme.mix(T.surface, T.surface_alt, 0.5)
        for index, (name, values, better) in enumerate(rows, start=1):
            bg = T.surface if index % 2 else stripe
            tk.Label(frame, text=name, bg=bg, fg=T.text2, font=font(11), anchor="w", padx=14, pady=8,
                     width=22).grid(row=index, column=0, sticky="nsew", padx=(0, 1), pady=(0, 1))
            winner = self._winner(values, better)
            for column, value in enumerate(values, start=1):
                text = self._display(value)
                is_best = winner is not None and column - 1 == winner
                tk.Label(frame, text=("★ " if is_best else "") + text, bg=bg,
                         fg=T.good if is_best else (T.text3 if text == "—" else T.text),
                         font=font(11, "bold" if is_best else "normal"), anchor="w", padx=14,
                         pady=8).grid(row=index, column=column, sticky="nsew", padx=(0, 1), pady=(0, 1))

        note = label(inner, "Figures are extracted automatically from articles and vendor posts. They can be "
                            "incomplete or vendor-reported, so check the evidence below before relying on them.",
                     10, fg=T.text3, bg=T.bg)
        note.pack(fill="x", pady=(8, 0))
        self.scroll.wrap(note, 0)

    @staticmethod
    def _display(value):
        if value is None:
            return "—"
        if isinstance(value, dict):
            return analyzer.fact_text(value)[len(value["name"]):].strip()
        return str(value)

    @staticmethod
    def _winner(values, better):
        if not better:
            return None
        numbers = []
        for i, value in enumerate(values):
            if isinstance(value, dict):
                numbers.append((value["value"], i))
            elif isinstance(value, str) and value.isdigit():
                numbers.append((int(value), i))
        if len(numbers) < 2 or len({n for n, _ in numbers}) == 1:
            return None
        return (max(numbers) if better == "max" else min(numbers))[1]

    def _brief(self, inner, models):
        actions = section_header(inner, "AI comparison brief", "written by AI from the coverage + web search")
        available, reason = ai_brief.availability()
        cached = db.get_brief(ai_brief.brief_key(models))
        if available:
            Button(actions, "↻ Regenerate" if cached else "✦ Generate brief", lambda: self._run_brief(models),
                   kind="secondary", bg=T.bg).pack()
        box = Card(inner, padx=22, pady=16, hover=False)
        box.pack(fill="x")
        self.brief_status = tk.StringVar()
        self.brief_text = tk.Text(box, bg=T.surface, fg=T.text, font=font(11), wrap="word", relief="flat",
                                  height=4, padx=2, pady=2, highlightthickness=0, cursor="arrow", spacing1=2,
                                  spacing3=2, selectbackground=T.accent_soft, selectforeground=T.text)
        self.brief_text.pack(fill="x")
        label(box, "", 10, fg=T.text3, textvariable=self.brief_status).pack(fill="x", pady=(6, 0))
        if cached:
            self._show_brief(cached["text"])
            self.brief_status.set(f"Generated {cached['created_at']} UTC")
        elif available:
            self._show_brief("Get a written comparison: what's new, the numbers side by side, and which model to "
                             "use for what. Uses your Anthropic API key (ANTHROPIC_API_KEY).")
        else:
            self._show_brief(reason)

    def _show_brief(self, text):
        widget = self.brief_text
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.tag_configure("h", font=font(13, "bold"), foreground=T.text, spacing1=14, spacing3=6)
        widget.tag_configure("table", font=theme.mono(10), foreground=T.text2)
        widget.tag_configure("table_head", foreground=T.text, font=theme.mono(10))
        widget.tag_configure("bullet", lmargin1=6, lmargin2=24)
        widget.tag_configure("body", foreground=T.text2)
        table = []

        def flush_table():
            if not table:
                return
            columns = max(len(row) for row in table)
            rows = [row + [""] * (columns - len(row)) for row in table]
            widths = [max(len(row[i]) for row in rows) for i in range(columns)]
            for index, row in enumerate(rows):
                line = "   ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
                widget.insert("end", line + "\n", "table_head" if index == 0 else "table")
            widget.insert("end", "\n")
            table.clear()

        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("|"):
                if not set(stripped) <= set("|-: "):
                    table.append([cell.strip().replace("**", "") for cell in stripped.strip("|").split("|")])
                continue
            flush_table()
            if stripped.startswith("#"):
                widget.insert("end", stripped.lstrip("#").strip() + "\n", "h")
            elif stripped.startswith(("- ", "* ")):
                widget.insert("end", "•   " + stripped[2:].replace("**", "") + "\n", ("bullet", "body"))
            else:
                widget.insert("end", stripped.replace("**", "") + "\n", "body")
        flush_table()
        lines = int(widget.index("end-1c").split(".")[0])
        widget.configure(height=min(max(lines + 2, 3), 60), state="disabled")

    def _run_brief(self, models):
        if self.brief_running:
            return
        self.brief_running = True
        self.brief_status.set(f"✦ Researching {', '.join(models)}… this can take a minute.")
        models = list(models)

        def worker():
            try:
                text = ai_brief.generate_comparison(models)
                self.after(0, self._brief_done, models, text, None)
            except Exception as e:
                self.after(0, self._brief_done, models, None, ai_brief.describe_error(e))

        threading.Thread(target=worker, daemon=True).start()

    def _brief_done(self, models, text, error):
        self.brief_running = False
        if not self.winfo_exists() or models != self.app.compare_models or not self.winfo_ismapped():
            return
        if error:
            self.brief_status.set(f"Could not generate the brief: {error}")
            return
        self._show_brief(text)
        self.brief_status.set("Generated just now")

    def _evidence(self, inner, models, facts):
        section_header(inner, "Evidence & coverage", "where each number came from")
        violet = theme.category_color("Model Release")
        for model in models:
            box = Card(inner, padx=22, pady=16, hover=False)
            box.pack(fill="x", pady=6)
            label(box, model, 13, "bold", fg=violet).pack(anchor="w")
            seen = set()
            for fact in facts.get(model, [])[:8]:
                key = (fact["name"], fact["value"])
                if key in seen:
                    continue
                seen.add(key)
                row = tk.Frame(box, bg=T.surface, cursor="hand2")
                row.pack(fill="x", pady=2)
                value = analyzer.format_fact_value(fact["kind"], fact["value"], fact["unit"])
                label(row, f"{fact['name']}:  {value}", 10, "semibold", fg=T.good, width=34).pack(side="left")
                source = label(row, f"{fact['source']}  —  {shorten(fact['title'], 90)}", 10, fg=T.text3,
                               cursor="hand2")
                source.pack(side="left", fill="x")
                for widget in (row, source):
                    widget.bind("<Button-1>", lambda e, link=fact["link"]: open_url(link))
            articles = db.query_articles(model=model, sort="top", limit=4)
            if articles:
                eyebrow(box, "Top coverage").pack(anchor="w", pady=(12, 4))
            for article in articles:
                link = label(box, f"↗   {article['title']}   ({article['source']}, "
                                  f"{time_ago(article['published_at'])})", 11, fg=T.text2, cursor="hand2")
                link.pack(fill="x", pady=1)
                self.scroll.wrap(link, 50)
                link.bind("<Button-1>", lambda e, url=article["link"]: open_url(url))
                link.bind("<Enter>", lambda e, w=link: w.configure(fg=T.accent))
                link.bind("<Leave>", lambda e, w=link: w.configure(fg=T.text2))
            if not facts.get(model) and not articles:
                label(box, "No coverage stored for this model yet.", 10, fg=T.text3).pack(anchor="w")
        tk.Frame(inner, bg=T.bg, height=32).pack()


# ---------------------------------------------------------------------------
# Fact helpers
# ---------------------------------------------------------------------------

def consensus_facts(facts):
    """Pick one value per (kind, name): the value most sources agree on, newest on ties."""
    grouped = {}
    for index, fact in enumerate(facts):  # facts arrive newest first
        grouped.setdefault((fact["kind"], fact["name"]), []).append((index, fact))
    result = {}
    for key, items in grouped.items():
        votes = Counter(round(fact["value"], 2) for _, fact in items)
        winner = max(votes, key=lambda v: (votes[v], -min(i for i, fct in items if round(fct["value"], 2) == v)))
        result[key] = next(fact for _, fact in items if round(fact["value"], 2) == winner)
    return result


def summarize_facts(facts, limit=3):
    best = consensus_facts(facts)
    order = sorted(best.items(), key=lambda item: (item[0][0] != "benchmark", item[0][1]))
    return [(name, analyzer.fact_text(fact)[len(name):].strip()) for (_, name), fact in order][:limit]


def main():
    try:  # crisp text on high-DPI Windows displays
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    db.init_db()
    fetcher.analyze_pending()
    root = tk.Tk()
    NewsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
