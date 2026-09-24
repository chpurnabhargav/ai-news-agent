import datetime
import threading
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from collections import Counter
from tkinter import ttk

import ai_brief
import analyzer
import db
import fetcher

# Catppuccin Mocha
BG = "#11111b"
PANEL = "#181825"
CARD = "#1e1e2e"
CARD_HI = "#26263a"
BORDER = "#313244"
BORDER_HI = "#45475a"
TEXT = "#cdd6f4"
SUBTEXT = "#a6adc8"
MUTED = "#7f849c"
ACCENT = "#89b4fa"
GREEN = "#a6e3a1"
YELLOW = "#f9e2af"
PEACH = "#fab387"
RED = "#f38ba8"
MAUVE = "#cba6f7"
SKY = "#89dceb"
TEAL = "#94e2d5"
PINK = "#f5c2e7"

CATEGORY_COLORS = {
    "Model Release": MAUVE,
    "Research": SKY,
    "Open Source": GREEN,
    "Products & Tools": ACCENT,
    "Business & Funding": YELLOW,
    "Policy & Safety": RED,
    "Hardware & Chips": PEACH,
    "General": MUTED,
}

RANGES = {"Last 24 hours": 24, "Last 3 days": 72, "Last 7 days": 168, "Last 30 days": 720, "All time": None}
PAGE_SIZE = 40
FONT = "TkDefaultFont"


def pick_font(root):
    families = set(tkfont.families(root))
    for name in ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Inter", "Ubuntu", "Cantarell", "Noto Sans", "DejaVu Sans"):
        if name in families:
            return name
    return "TkDefaultFont"


def f(size, weight="normal"):
    return (FONT, size, weight)


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


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class FlatButton(tk.Label):
    """A label-based button: consistent look on every platform, with hover."""

    STYLES = {
        "primary": (ACCENT, "#11111b", "#b4befe"),
        "ghost": (BORDER, TEXT, BORDER_HI),
        "subtle": (CARD, SUBTEXT, BORDER),
        "nav": (PANEL, SUBTEXT, CARD),
        "nav_active": (CARD, TEXT, CARD),
    }

    def __init__(self, parent, text, command=None, style="ghost", size=10, padx=12, pady=5, **kw):
        bg, fg, hover = self.STYLES[style]
        super().__init__(parent, text=text, bg=bg, fg=fg, font=f(size, "bold" if style == "primary" else "normal"),
                         padx=padx, pady=pady, cursor="hand2", **kw)
        self._bg, self._hover, self.command = bg, hover, command
        self.bind("<Enter>", lambda e: self.configure(bg=self._hover))
        self.bind("<Leave>", lambda e: self.configure(bg=self._bg))
        self.bind("<Button-1>", self._click)

    def _click(self, _):
        if self.command:
            self.command()
        return "break"

    def set_style(self, style):
        self._bg, fg, self._hover = self.STYLES[style]
        self.configure(bg=self._bg, fg=fg)


def pill(parent, text, color, bg=CARD, command=None, size=8):
    label = tk.Label(parent, text=f" {text} ", bg=bg, fg=color, font=f(size, "bold"),
                     highlightthickness=1, highlightbackground=color, padx=4, pady=1)
    if command:
        label.configure(cursor="hand2")
        label.bind("<Button-1>", lambda e: (command(), "break")[1])
    return label


class ScrollFrame(tk.Frame):
    """Vertically scrolling frame whose labels re-wrap when the window resizes."""

    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self._wrapped = []
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._on_resize)

    def wrap(self, label, margin):
        self._wrapped.append((label, margin))
        label.configure(wraplength=max(200, self.canvas.winfo_width() - margin))
        return label

    def clear(self):
        for child in self.inner.winfo_children():
            child.destroy()
        self._wrapped = []
        self.canvas.yview_moveto(0)

    def _on_resize(self, event):
        self.canvas.itemconfig(self._window, width=event.width)
        for label, margin in self._wrapped:
            if label.winfo_exists():
                label.configure(wraplength=max(200, event.width - margin))

    def scroll(self, units):
        if self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(units, "units")

    @staticmethod
    def install_wheel(root):
        """One global wheel handler that scrolls whichever ScrollFrame is under the pointer."""
        def target(event):
            widget = root.winfo_containing(event.x_root, event.y_root)
            while widget is not None and not isinstance(widget, ScrollFrame):
                widget = widget.master
            return widget

        def on_wheel(event):
            frame = target(event)
            if frame:
                delta = event.delta // 120 if abs(event.delta) >= 120 else event.delta  # Windows vs macOS
                frame.scroll(-3 * delta)

        root.bind_all("<MouseWheel>", on_wheel)
        root.bind_all("<Button-4>", lambda e: (frame := target(e)) and frame.scroll(-3))
        root.bind_all("<Button-5>", lambda e: (frame := target(e)) and frame.scroll(3))


def flow(frame, widgets, gap=6):
    """Lay widgets out left to right, wrapping onto new rows to fit the frame width."""
    def layout(_=None):
        width = frame.winfo_width()
        if width <= 1:
            return
        x = y = row_height = 0
        for widget in widgets:
            w, h = widget.winfo_reqwidth(), widget.winfo_reqheight()
            if x and x + w > width:
                x, y = 0, y + row_height + gap
                row_height = 0
            widget.place(x=x, y=y)
            x += w + gap
            row_height = max(row_height, h)
        frame.configure(height=y + row_height)

    frame.bind("<Configure>", layout)
    frame.after_idle(layout)


def section_title(parent, text, subtitle=None, bg=BG):
    frame = tk.Frame(parent, bg=bg)
    frame.pack(fill="x", padx=24, pady=(22, 8))
    tk.Label(frame, text=text, bg=bg, fg=TEXT, font=f(15, "bold")).pack(side="left")
    if subtitle:
        tk.Label(frame, text=subtitle, bg=bg, fg=MUTED, font=f(10)).pack(side="left", padx=10, pady=(4, 0))
    return frame


def empty_state(parent, title, hint):
    frame = tk.Frame(parent, bg=BG)
    frame.pack(fill="x", pady=60)
    tk.Label(frame, text=title, bg=BG, fg=SUBTEXT, font=f(14, "bold")).pack()
    tk.Label(frame, text=hint, bg=BG, fg=MUTED, font=f(10)).pack(pady=6)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class NewsApp:
    def __init__(self, root):
        global FONT
        FONT = pick_font(root)
        self.root = root
        root.title("AI News Agent")
        root.geometry("1240x800")
        root.minsize(960, 600)
        root.configure(bg=BG)
        self._style_ttk()
        ScrollFrame.install_wheel(root)

        self.fetching = False
        self.compare_models = []
        self.views = {}
        self.nav_buttons = {}

        self._build_header()
        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True)
        self._build_sidebar(body)
        self.main = tk.Frame(body, bg=BG)
        self.main.pack(side="left", fill="both", expand=True)
        self._build_statusbar()

        self.views = {
            "briefing": BriefingView(self.main, self),
            "news": NewsView(self.main, self),
            "saved": NewsView(self.main, self, saved_only=True),
            "models": ModelsView(self.main, self),
            "compare": CompareView(self.main, self),
        }
        self.show("briefing")
        self.refresh()

    # --- chrome -----------------------------------------------------------
    def _style_ttk(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=CARD, background=BORDER, foreground=TEXT,
                        arrowcolor=TEXT, bordercolor=BORDER, lightcolor=CARD, darkcolor=CARD, padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", CARD)], foreground=[("readonly", TEXT)],
                  selectbackground=[("readonly", CARD)], selectforeground=[("readonly", TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", CARD)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", BORDER_HI)
        self.root.option_add("*TCombobox*Listbox.font", f(10))
        style.configure("Vertical.TScrollbar", background=BORDER, troughcolor=BG, bordercolor=BG,
                        arrowcolor=MUTED, lightcolor=BORDER, darkcolor=BORDER, gripcount=0)
        style.map("Vertical.TScrollbar", background=[("active", BORDER_HI)])
        style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, rowheight=30,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, borderwidth=0, font=f(10))
        style.configure("Treeview.Heading", background=PANEL, foreground=SUBTEXT, relief="flat",
                        font=f(10, "bold"), padding=6)
        style.map("Treeview", background=[("selected", BORDER_HI)], foreground=[("selected", TEXT)])
        style.map("Treeview.Heading", background=[("active", CARD)])

    def _build_header(self):
        bar = tk.Frame(self.root, bg=PANEL, padx=20, pady=12)
        bar.pack(fill="x")
        tk.Label(bar, text="◆", bg=PANEL, fg=MAUVE, font=f(18, "bold")).pack(side="left")
        titles = tk.Frame(bar, bg=PANEL)
        titles.pack(side="left", padx=10)
        tk.Label(titles, text="AI News Agent", bg=PANEL, fg=TEXT, font=f(15, "bold")).pack(anchor="w")
        tk.Label(titles, text="Model releases, comparisons and the AI stories that matter",
                 bg=PANEL, fg=MUTED, font=f(9)).pack(anchor="w")
        self.refresh_btn = FlatButton(bar, "⟳  Refresh", self.refresh, style="primary", padx=16, pady=7)
        self.refresh_btn.pack(side="right")
        self.updated_var = tk.StringVar()
        tk.Label(bar, textvariable=self.updated_var, bg=PANEL, fg=MUTED, font=f(9)).pack(side="right", padx=14)

    def _build_sidebar(self, parent):
        side = tk.Frame(parent, bg=PANEL, width=230)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(side, bg=PANEL, height=14).pack()
        for key, label in (
            ("briefing", "☀   Daily briefing"),
            ("news", "☰   All news"),
            ("models", "◈   Model tracker"),
            ("compare", "⇄   Compare models"),
            ("saved", "★   Saved"),
        ):
            button = FlatButton(side, label, lambda k=key: self.show(k), style="nav", size=11, padx=18, pady=9,
                                anchor="w")
            button.pack(fill="x", padx=8, pady=1)
            self.nav_buttons[key] = button

        tk.Label(side, text="TOPICS", bg=PANEL, fg=MUTED, font=f(8, "bold")).pack(anchor="w", padx=26, pady=(24, 6))
        for category in analyzer.CATEGORIES:
            row = tk.Frame(side, bg=PANEL, cursor="hand2")
            row.pack(fill="x", padx=(26, 8), pady=3)
            dot = tk.Label(row, text="●", bg=PANEL, fg=CATEGORY_COLORS[category], font=f(9))
            dot.pack(side="left")
            name = tk.Label(row, text=category, bg=PANEL, fg=SUBTEXT, font=f(10))
            name.pack(side="left", padx=6)
            for widget in (row, dot, name):
                widget.bind("<Button-1>", lambda e, c=category: self.open_category(c))
                widget.bind("<Enter>", lambda e, n=name: n.configure(fg=TEXT))
                widget.bind("<Leave>", lambda e, n=name: n.configure(fg=SUBTEXT))

    def _build_statusbar(self):
        self.status_var = tk.StringVar(value="Loading…")
        tk.Label(self.root, textvariable=self.status_var, bg=PANEL, fg=MUTED, anchor="w",
                 font=f(9), padx=12, pady=4).pack(fill="x", side="bottom")

    # --- navigation -------------------------------------------------------
    def show(self, key):
        for name, view in self.views.items():
            view.pack_forget()
            self.nav_buttons[name].set_style("nav_active" if name == key else "nav")
        self.current = key
        self.views[key].pack(fill="both", expand=True)
        self.views[key].load()

    def open_category(self, category):
        self.views["news"].set_filters(category=category)
        self.show("news")

    def open_model_news(self, model):
        self.views["news"].set_filters(search=model, hours=None)
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
        button.configure(text="★ Saved" if article["bookmarked"] else "☆ Save",
                         fg=YELLOW if article["bookmarked"] else SUBTEXT)

    # --- data -------------------------------------------------------------
    def refresh(self):
        if self.fetching:
            return
        self.fetching = True
        self.refresh_btn.configure(text="⟳  Fetching…")
        self.status_var.set("Fetching the latest AI news…")
        threading.Thread(target=self._fetch_worker, daemon=True).start()

    def _fetch_worker(self):
        try:
            count = fetcher.fetch_all(progress=lambda m: self.root.after(0, self.status_var.set, m))
            self.root.after(0, self._after_fetch, f"Fetched {count} new articles.")
        except Exception as e:
            self.root.after(0, self._after_fetch, f"Fetch failed: {e}")

    def _after_fetch(self, message):
        self.fetching = False
        self.refresh_btn.configure(text="⟳  Refresh")
        self.status_var.set(f"{message}  ·  {db.count_articles()} articles stored")
        self.views[self.current].load()
        self.update_timestamp()

    def update_timestamp(self):
        last = db.stats(24)["last_fetch"]
        self.updated_var.set(f"Updated {time_ago(last)}" if last else "Not fetched yet")

    # --- shared rendering -------------------------------------------------
    def render_card(self, scroll, article, duplicates=(), compact=False):
        color = CATEGORY_COLORS.get(article["category"], MUTED)
        outer = tk.Frame(scroll.inner, bg=BORDER)
        outer.pack(fill="x", padx=24, pady=5)
        stripe = tk.Frame(outer, bg=color, width=4)
        stripe.pack(side="left", fill="y")
        card = tk.Frame(outer, bg=CARD, padx=16, pady=12)
        card.pack(side="left", fill="both", expand=True, padx=(0, 1), pady=1)

        def open_link(_=None, link=article["link"]):
            webbrowser.open(link)

        def hover(on):
            outer.configure(bg=color if on else BORDER)

        for widget in (outer, card):
            widget.bind("<Enter>", lambda e: hover(True))
            widget.bind("<Leave>", lambda e: hover(False))

        meta = tk.Frame(card, bg=CARD)
        meta.pack(fill="x")
        pill(meta, article["category"], color).pack(side="left")
        tk.Label(meta, text=article["source"], bg=CARD, fg=SUBTEXT, font=f(9, "bold")).pack(side="left", padx=(10, 0))
        tk.Label(meta, text=f"·  {time_ago(article['published_at'])}", bg=CARD, fg=MUTED,
                 font=f(9)).pack(side="left", padx=6)
        if article["score"] >= 60:
            tk.Label(meta, text="▲ High impact", bg=CARD, fg=PEACH, font=f(8, "bold")).pack(side="right")

        title = tk.Label(card, text=article["title"], bg=CARD, fg=TEXT, font=f(12 if compact else 13, "bold"),
                         justify="left", anchor="w", cursor="hand2")
        title.pack(fill="x", pady=(6, 0))
        scroll.wrap(title, 290)
        title.bind("<Button-1>", open_link)
        title.bind("<Enter>", lambda e: title.configure(fg=ACCENT))
        title.bind("<Leave>", lambda e: title.configure(fg=TEXT))

        summary = shorten(article["summary"], 220 if compact else 320)
        if summary and summary.lower() != article["title"].lower():
            scroll.wrap(tk.Label(card, text=summary, bg=CARD, fg=SUBTEXT, font=f(10), justify="left",
                                 anchor="w"), 290).pack(fill="x", pady=(4, 0))

        if duplicates:
            names = sorted({d["source"] for d in duplicates} - {article["source"]})
            if names:
                tk.Label(card, text=f"Also covered by {', '.join(names[:4])}" + (" …" if len(names) > 4 else ""),
                         bg=CARD, fg=MUTED, font=f(9, "italic"), anchor="w").pack(fill="x", pady=(4, 0))

        actions = tk.Frame(card, bg=CARD)
        actions.pack(fill="x", pady=(8, 0))
        FlatButton(actions, "Open ↗", open_link, style="ghost", size=9, padx=10, pady=3).pack(side="left")
        save = FlatButton(actions, "★ Saved" if article["bookmarked"] else "☆ Save", style="subtle", size=9,
                          padx=10, pady=3)
        save.configure(fg=YELLOW if article["bookmarked"] else SUBTEXT)
        save.command = lambda a=article, b=save: self.toggle_bookmark(a, b)
        save.pack(side="left", padx=6)
        models = article["models"][:4]
        if models:
            FlatButton(actions, "⇄ Compare", lambda m=models: self.compare(m), style="subtle", size=9,
                       padx=10, pady=3).pack(side="left")
            for model in reversed(models):
                pill(actions, model, MAUVE, command=lambda m=model: self.compare([m])).pack(side="right", padx=2)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class BriefingView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True)

    def load(self):
        self.scroll.clear()
        inner = self.scroll.inner
        now = datetime.datetime.now()
        greeting = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 18 else "Good evening"
        head = tk.Frame(inner, bg=BG)
        head.pack(fill="x", padx=24, pady=(22, 0))
        tk.Label(head, text=f"{greeting} — here's your AI briefing", bg=BG, fg=TEXT, font=f(20, "bold")).pack(anchor="w")
        tk.Label(head, text=now.strftime("%A, %B %d"), bg=BG, fg=MUTED, font=f(11)).pack(anchor="w")

        day, week = db.stats(24), db.stats(24 * 7)
        tiles = tk.Frame(inner, bg=BG)
        tiles.pack(fill="x", padx=18, pady=(16, 0))
        for value, label, color in (
            (day["articles"], "stories in the last 24h", ACCENT),
            (week["releases"], "model-release stories this week", MAUVE),
            (week["models"], "models in the news this week", GREEN),
            (day["sources"], "sources reporting today", PEACH),
        ):
            tile = tk.Frame(tiles, bg=CARD, padx=18, pady=14, highlightthickness=1, highlightbackground=BORDER)
            tile.pack(side="left", fill="x", expand=True, padx=6)
            tk.Label(tile, text=str(value), bg=CARD, fg=color, font=f(24, "bold")).pack(anchor="w")
            tk.Label(tile, text=label, bg=CARD, fg=SUBTEXT, font=f(9)).pack(anchor="w")

        self._releases(inner)
        self._top_stories(inner)
        self._topics(inner)
        self.app.update_timestamp()

    def _releases(self, inner):
        releases = db.model_leaderboard(hours=24 * 7, releases_only=True, limit=6)
        header = section_title(inner, "New model releases", "detected this week")
        if releases:
            FlatButton(header, "Compare these ⇄", lambda: self.app.compare([r["model"] for r in releases[:4]]),
                       style="ghost", size=9).pack(side="right")
        if not releases:
            tk.Label(inner, text="No model launches detected this week yet.", bg=BG, fg=MUTED,
                     font=f(10)).pack(anchor="w", padx=24)
            return
        facts = db.model_facts([r["model"] for r in releases])
        grid = tk.Frame(inner, bg=BG)
        grid.pack(fill="x", padx=18)
        for column in range(3):
            grid.columnconfigure(column, weight=1, uniform="release")
        for index, release in enumerate(releases):
            card = tk.Frame(grid, bg=CARD, padx=14, pady=12, highlightthickness=1, highlightbackground=BORDER)
            card.grid(row=index // 3, column=index % 3, sticky="nsew", padx=6, pady=6)
            tk.Label(card, text=release["developer"] or release["family"], bg=CARD, fg=MUTED,
                     font=f(9, "bold")).pack(anchor="w")
            tk.Label(card, text=release["model"], bg=CARD, fg=TEXT, font=f(14, "bold")).pack(anchor="w")
            tk.Label(card, text=f"{release['mentions']} stories · {release['sources']} sources · first seen "
                                f"{time_ago(release['first_seen'])}", bg=CARD, fg=SUBTEXT, font=f(9)).pack(anchor="w")
            highlights = summarize_facts(facts.get(release["model"], []), limit=3)
            for name, value in highlights:
                row = tk.Frame(card, bg=CARD)
                row.pack(fill="x", pady=(4 if name == highlights[0][0] else 0, 0))
                tk.Label(row, text=name, bg=CARD, fg=MUTED, font=f(9)).pack(side="left")
                tk.Label(row, text=value, bg=CARD, fg=GREEN, font=f(9, "bold")).pack(side="right")
            buttons = tk.Frame(card, bg=CARD)
            buttons.pack(fill="x", pady=(10, 0))
            FlatButton(buttons, "Compare", lambda m=release["model"]: self.app.compare([m]), style="ghost",
                       size=9, padx=10, pady=3).pack(side="left")
            FlatButton(buttons, "News", lambda m=release["model"]: self.app.open_model_news(m), style="subtle",
                       size=9, padx=10, pady=3).pack(side="left", padx=6)

    def _top_stories(self, inner):
        section_title(inner, "Top stories", "ranked by impact, duplicates merged")
        articles = db.query_articles(hours=48, sort="top", limit=80)
        if len(articles) < 5:
            articles = db.query_articles(hours=24 * 7, sort="top", limit=80)
        clusters = analyzer.cluster_articles(articles)[:8]
        if not clusters:
            empty_state(inner, "No stories yet", "Click Refresh to fetch the latest AI news.")
            return
        for lead, dupes in clusters:
            self.app.render_card(self.scroll, lead, dupes, compact=True)

    def _topics(self, inner):
        counts = db.category_counts(24 * 7)
        if not counts:
            return
        section_title(inner, "This week by topic")
        box = tk.Frame(inner, bg=CARD, padx=18, pady=14, highlightthickness=1, highlightbackground=BORDER)
        box.pack(fill="x", padx=24, pady=(0, 24))
        top = max(counts.values())
        for category in analyzer.CATEGORIES:
            count = counts.get(category, 0)
            row = tk.Frame(box, bg=CARD, cursor="hand2")
            row.pack(fill="x", pady=3)
            name = tk.Label(row, text=category, bg=CARD, fg=SUBTEXT, font=f(10), width=18, anchor="w")
            name.pack(side="left")
            bar = tk.Canvas(row, bg=CARD, height=14, highlightthickness=0)
            bar.pack(side="left", fill="x", expand=True, padx=8)
            bar.bind("<Configure>", lambda e, b=bar, c=count, col=CATEGORY_COLORS[category]: (
                b.delete("all"), b.create_rectangle(0, 2, max(3, e.width * c / top), 12, fill=col, width=0)))
            tk.Label(row, text=str(count), bg=CARD, fg=TEXT, font=f(10, "bold"), width=5, anchor="e").pack(side="right")
            for widget in (row, name, bar):
                widget.bind("<Button-1>", lambda e, c=category: self.app.open_category(c))


class NewsView(tk.Frame):
    def __init__(self, parent, app, saved_only=False):
        super().__init__(parent, bg=BG)
        self.app = app
        self.saved_only = saved_only
        self.category = "All"
        self.limit = PAGE_SIZE
        self._search_job = None

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=24, pady=(18, 4))
        tk.Label(bar, text="Saved articles" if saved_only else "All news", bg=BG, fg=TEXT,
                 font=f(18, "bold")).pack(side="left")
        self.count_var = tk.StringVar()
        tk.Label(bar, textvariable=self.count_var, bg=BG, fg=MUTED, font=f(10)).pack(side="left", padx=12, pady=(6, 0))

        filters = tk.Frame(self, bg=BG)
        filters.pack(fill="x", padx=24, pady=6)
        self.search_var = tk.StringVar()
        search = tk.Frame(filters, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        search.pack(side="left")
        tk.Label(search, text="⌕", bg=CARD, fg=MUTED, font=f(12)).pack(side="left", padx=(8, 0))
        entry = tk.Entry(search, textvariable=self.search_var, width=28, bg=CARD, fg=TEXT, insertbackground=TEXT,
                         relief="flat", font=f(10), highlightthickness=0)
        entry.pack(side="left", padx=6, pady=5)
        self.search_var.trace_add("write", lambda *_: self._debounced_reload())

        self.range_var = tk.StringVar(value="All time" if saved_only else "Last 3 days")
        self.sort_var = tk.StringVar(value="Top")
        self.source_var = tk.StringVar(value="All")
        for label, var, values, width in (
            ("Range", self.range_var, list(RANGES), 12),
            ("Sort", self.sort_var, ["Top", "Latest"], 7),
            ("Source", self.source_var, ["All"], 20),
        ):
            tk.Label(filters, text=label, bg=BG, fg=MUTED, font=f(9)).pack(side="left", padx=(16, 4))
            combo = ttk.Combobox(filters, textvariable=var, values=values, width=width, state="readonly", font=f(10))
            combo.pack(side="left")
            combo.bind("<<ComboboxSelected>>", lambda e: self.reload())
            if var is self.source_var:
                self.source_combo = combo

        self.chips = tk.Frame(self, bg=BG, height=30)
        self.chips.pack(fill="x", padx=24, pady=(6, 4))
        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True)

    def set_filters(self, category="All", search="", hours="keep"):
        self.category = category
        self.search_var.set(search)
        if hours is None:
            self.range_var.set("All time")

    def _debounced_reload(self):
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(300, self.reload)

    def load(self):
        self.reload()

    def reload(self):
        self.limit = PAGE_SIZE
        self._render()

    def _render(self):
        hours = RANGES[self.range_var.get()]
        search = self.search_var.get().strip()
        sources = db.get_sources(hours)
        self.source_combo["values"] = ["All"] + sources
        if self.source_var.get() not in sources:
            self.source_var.set("All")

        articles = db.query_articles(
            hours=hours, category=self.category, source=self.source_var.get(), search=search or None,
            saved_only=self.saved_only, sort="top" if self.sort_var.get() == "Top" else "latest",
        )
        self._render_chips(hours, search)
        clusters = analyzer.cluster_articles(articles) if self.sort_var.get() == "Top" else [(a, []) for a in articles]
        self.count_var.set(f"{len(articles)} articles" + (f" · {len(clusters)} stories" if len(clusters) != len(articles) else ""))

        self.scroll.clear()
        if not clusters:
            if self.saved_only:
                empty_state(self.scroll.inner, "Nothing saved yet", "Use ☆ Save on any story to keep it here.")
            else:
                empty_state(self.scroll.inner, "No matching stories",
                            "Try a longer time range, another topic, or click Refresh.")
            return
        for lead, dupes in clusters[:self.limit]:
            self.app.render_card(self.scroll, lead, dupes)
        if len(clusters) > self.limit:
            more = FlatButton(self.scroll.inner, f"Show more ({len(clusters) - self.limit} remaining)",
                              self._show_more, style="ghost")
            more.pack(pady=16)

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
                                         source=self.source_var.get()):
            counts[article["category"]] += 1
        chips = [("All", sum(counts.values()), TEXT)] + [
            (c, counts[c], CATEGORY_COLORS[c]) for c in analyzer.CATEGORIES if counts[c] or c == self.category
        ]
        widgets = []
        for name, count, color in chips:
            active = name == self.category
            chip = tk.Label(self.chips, text=f"{name}  {count}", bg=color if active else CARD,
                            fg=BG if active else color, font=f(9, "bold"), padx=10, pady=4, cursor="hand2",
                            highlightthickness=1, highlightbackground=color if active else BORDER)
            chip.bind("<Button-1>", lambda e, n=name: self._select_category(n))
            widgets.append(chip)
        flow(self.chips, widgets)

    def _select_category(self, name):
        self.category = name
        self.reload()


class ModelsView(tk.Frame):
    COLUMNS = ("model", "developer", "status", "first", "mentions", "sources", "highlights")

    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=24, pady=(18, 4))
        tk.Label(head, text="Model tracker", bg=BG, fg=TEXT, font=f(18, "bold")).pack(side="left")
        tk.Label(head, text="Every AI model mentioned in the news, with extracted benchmarks and specs",
                 bg=BG, fg=MUTED, font=f(10)).pack(side="left", padx=12, pady=(6, 0))

        controls = tk.Frame(self, bg=BG)
        controls.pack(fill="x", padx=24, pady=8)
        self.range_var = tk.StringVar(value="Last 30 days")
        tk.Label(controls, text="Range", bg=BG, fg=MUTED, font=f(9)).pack(side="left", padx=(0, 4))
        combo = ttk.Combobox(controls, textvariable=self.range_var, values=list(RANGES)[1:], width=12,
                             state="readonly", font=f(10))
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda e: self.load())
        self.releases_only = tk.BooleanVar(value=False)
        tk.Checkbutton(controls, text="Releases only", variable=self.releases_only, command=self.load, bg=BG,
                       fg=SUBTEXT, selectcolor=CARD, activebackground=BG, activeforeground=TEXT,
                       font=f(10)).pack(side="left", padx=14)
        self.compare_btn = FlatButton(controls, "⇄ Compare selected", self._compare_selected, style="primary")
        self.compare_btn.pack(side="right")
        tk.Label(controls, text="Select up to 5 rows (Ctrl/Shift-click)", bg=BG, fg=MUTED,
                 font=f(9)).pack(side="right", padx=10)

        table = tk.Frame(self, bg=BG)
        table.pack(fill="both", expand=True, padx=24, pady=(0, 8))
        self.tree = ttk.Treeview(table, columns=self.COLUMNS, show="headings", selectmode="extended")
        for column, heading, width, anchor in (
            ("model", "Model", 190, "w"), ("developer", "Developer", 110, "w"), ("status", "Status", 110, "w"),
            ("first", "First seen", 95, "w"), ("mentions", "Stories", 80, "center"),
            ("sources", "Sources", 85, "center"), ("highlights", "Extracted highlights", 380, "w"),
        ):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, anchor=anchor, stretch=column == "highlights")
        self.tree.tag_configure("release", foreground=MAUVE)
        scrollbar = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda e: self._compare_selected())

        self.detail = ScrollFrame(self)
        self.detail.configure(height=220)
        self.detail.pack(fill="x", padx=0, pady=(0, 4))
        self.detail.pack_propagate(False)

    def load(self):
        self.tree.delete(*self.tree.get_children())
        rows = db.model_leaderboard(hours=RANGES[self.range_var.get()], releases_only=self.releases_only.get())
        facts = db.model_facts([r["model"] for r in rows])
        for row in rows:
            highlights = ",  ".join(f"{n} {v}" for n, v in summarize_facts(facts.get(row["model"], []), limit=3))
            released = row["release_mentions"] > 0
            self.tree.insert("", "end", iid=row["model"], tags=("release",) if released else (), values=(
                row["model"], row["developer"], "New release" if released else "In the news",
                local_time(row["first_seen"]).strftime("%b %d") if row["first_seen"] else "",
                row["mentions"], row["sources"], highlights or "—",
            ))
        self._show_detail(None)
        if not rows:
            self.app.status_var.set("No models detected in this range yet. Try a longer range or Refresh.")

    def _on_select(self, _):
        selection = self.tree.selection()
        self.compare_btn.configure(text=f"⇄ Compare selected ({len(selection)})" if selection else "⇄ Compare selected")
        self._show_detail(selection[-1] if selection else None)

    def _show_detail(self, model):
        self.detail.clear()
        inner = self.detail.inner
        if not model:
            tk.Label(inner, text="Select a model to see its latest headlines.", bg=BG, fg=MUTED,
                     font=f(10)).pack(anchor="w", padx=24, pady=10)
            return
        tk.Label(inner, text=f"Latest on {model}", bg=BG, fg=TEXT, font=f(12, "bold")).pack(anchor="w", padx=24, pady=(8, 4))
        for article in db.query_articles(model=model, sort="latest", limit=8):
            row = tk.Frame(inner, bg=BG, cursor="hand2")
            row.pack(fill="x", padx=24, pady=2)
            tk.Label(row, text=f"{time_ago(article['published_at']):>8}", bg=BG, fg=MUTED, font=f(9), width=9,
                     anchor="w").pack(side="left")
            tk.Label(row, text=article["source"], bg=BG, fg=GREEN, font=f(9, "bold"), width=18,
                     anchor="w").pack(side="left")
            title = tk.Label(row, text=shorten(article["title"], 120), bg=BG, fg=SUBTEXT, font=f(10), anchor="w")
            title.pack(side="left", fill="x")
            for widget in (row, title):
                widget.bind("<Button-1>", lambda e, link=article["link"]: webbrowser.open(link))
            title.bind("<Enter>", lambda e, t=title: t.configure(fg=ACCENT))
            title.bind("<Leave>", lambda e, t=title: t.configure(fg=SUBTEXT))

    def _compare_selected(self):
        selection = list(self.tree.selection())[:5]
        if selection:
            self.app.compare_models = []
            self.app.compare(selection)


class CompareView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app = app
        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True)
        self.brief_running = False

    def load(self):
        self.scroll.clear()
        inner = self.scroll.inner
        models = self.app.compare_models

        head = tk.Frame(inner, bg=BG)
        head.pack(fill="x", padx=24, pady=(18, 4))
        tk.Label(head, text="Compare models", bg=BG, fg=TEXT, font=f(18, "bold")).pack(side="left")
        tk.Label(head, text="Side-by-side specs and benchmark scores pulled from the news", bg=BG, fg=MUTED,
                 font=f(10)).pack(side="left", padx=12, pady=(6, 0))

        picker = tk.Frame(inner, bg=BG)
        picker.pack(fill="x", padx=24, pady=8)
        tk.Label(picker, text="Add model", bg=BG, fg=MUTED, font=f(9)).pack(side="left", padx=(0, 6))
        add_var = tk.StringVar()
        combo = ttk.Combobox(picker, textvariable=add_var, values=db.known_models(), width=26, font=f(10))
        combo.pack(side="left")

        def add(_=None):
            name = add_var.get().strip()
            if name and name not in models and len(models) < 5:
                self.app.compare_models.append(name)
                self.load()

        combo.bind("<<ComboboxSelected>>", add)
        combo.bind("<Return>", add)
        for model in models:
            chip = tk.Frame(picker, bg=CARD, highlightthickness=1, highlightbackground=MAUVE)
            chip.pack(side="left", padx=(8, 0))
            tk.Label(chip, text=model, bg=CARD, fg=MAUVE, font=f(9, "bold"), padx=8, pady=3).pack(side="left")
            remove = tk.Label(chip, text="✕", bg=CARD, fg=MUTED, font=f(9), padx=6, cursor="hand2")
            remove.pack(side="left")
            remove.bind("<Button-1>", lambda e, m=model: self._remove(m))
        if models:
            FlatButton(picker, "Clear", self._clear, style="subtle", size=9).pack(side="left", padx=8)

        if not models:
            suggestions = [r["model"] for r in db.model_leaderboard(hours=24 * 14, limit=4)]
            empty_state(inner, "Pick models to compare",
                        "Add up to five models above, or use ⇄ Compare on any story or in the Model tracker.")
            if suggestions:
                FlatButton(inner, f"Try: {' vs '.join(suggestions)}", lambda: self.app.compare(suggestions),
                           style="ghost").pack()
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
        for kind, label, better in (("context", "Context window", "max"), ("price_in", "Input price", "min"),
                                    ("price_out", "Output price", "min")):
            values = [best[m].get((kind, label)) for m in models]
            rows.append((label, values, better))
        benchmarks = sorted({name for m in models for (kind, name) in best[m] if kind == "benchmark"},
                            key=lambda n: -sum(1 for m in models if ("benchmark", n) in best[m]))
        for name in benchmarks:
            rows.append((name, [best[m].get(("benchmark", name)) for m in models], "max"))

        section_title(inner, "At a glance", "★ marks the best value in each row")
        frame = tk.Frame(inner, bg=BORDER)
        frame.pack(fill="x", padx=24)
        for column in range(len(models) + 1):
            frame.columnconfigure(column, weight=1 if column else 0, uniform="cmp" if column else "")
        header_cells = ["Metric"] + models
        for column, text in enumerate(header_cells):
            tk.Label(frame, text=text, bg=PANEL, fg=MAUVE if column else SUBTEXT, font=f(10, "bold"), anchor="w",
                     padx=12, pady=8).grid(row=0, column=column, sticky="nsew", padx=(0, 1), pady=(0, 1))

        for index, (label, values, better) in enumerate(rows, start=1):
            bg = CARD if index % 2 else CARD_HI
            tk.Label(frame, text=label, bg=bg, fg=SUBTEXT, font=f(10), anchor="w", padx=12, pady=6,
                     width=22).grid(row=index, column=0, sticky="nsew", padx=(0, 1), pady=(0, 1))
            winner = self._winner(values, better)
            for column, value in enumerate(values, start=1):
                text = self._display(value)
                is_best = winner is not None and column - 1 == winner
                tk.Label(frame, text=("★ " if is_best else "") + text, bg=bg, fg=GREEN if is_best else
                         (MUTED if text == "—" else TEXT), font=f(10, "bold" if is_best else "normal"), anchor="w",
                         padx=12, pady=6).grid(row=index, column=column, sticky="nsew", padx=(0, 1), pady=(0, 1))

        note = tk.Label(inner, text="Figures are extracted automatically from articles and vendor posts; they can be "
                                    "incomplete or vendor-reported. Check the evidence below before relying on them.",
                        bg=BG, fg=MUTED, font=f(9, "italic"), justify="left", anchor="w")
        note.pack(fill="x", padx=24, pady=(6, 0))
        self.scroll.wrap(note, 60)

    @staticmethod
    def _display(value):
        if value is None:
            return "—"
        if isinstance(value, dict):
            return analyzer.format_fact_value(value["kind"], value["value"], value["unit"])
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
        header = section_title(inner, "AI comparison brief", "written by Claude from the coverage + web search")
        available, reason = ai_brief.availability()
        box = tk.Frame(inner, bg=CARD, padx=18, pady=14, highlightthickness=1, highlightbackground=BORDER)
        box.pack(fill="x", padx=24)
        cached = db.get_brief(ai_brief.brief_key(models))
        self.brief_status = tk.StringVar()
        if available:
            label = "↻ Regenerate" if cached else "✦ Generate brief"
            FlatButton(header, label, lambda: self._run_brief(models), style="primary", size=9).pack(side="right")
        self.brief_text = tk.Text(box, bg=CARD, fg=TEXT, font=f(10), wrap="word", relief="flat", height=4,
                                  padx=4, pady=4, highlightthickness=0, cursor="arrow")
        self.brief_text.pack(fill="x")
        tk.Label(box, textvariable=self.brief_status, bg=CARD, fg=MUTED, font=f(9), anchor="w").pack(fill="x")
        if cached:
            self._show_brief(cached["text"])
            self.brief_status.set(f"Generated {cached['created_at']} UTC")
        elif available:
            self._show_brief("Get a written comparison — what's new, the numbers side by side, and which model "
                             "to use for what. Requires an Anthropic API key (ANTHROPIC_API_KEY).")
        else:
            self._show_brief(reason)

    def _show_brief(self, text):
        widget = self.brief_text
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.tag_configure("h", font=f(12, "bold"), foreground=MAUVE, spacing1=10, spacing3=4)
        widget.tag_configure("table", font=("Courier New", 10), foreground=SUBTEXT)
        widget.tag_configure("bullet", lmargin1=8, lmargin2=22)
        table = []

        def flush_table():
            if not table:
                return
            columns = max(len(row) for row in table)
            rows = [row + [""] * (columns - len(row)) for row in table]
            widths = [max(len(row[i]) for row in rows) for i in range(columns)]
            for index, row in enumerate(rows):
                line = "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()
                widget.insert("end", line + "\n", ("table", "table_head") if index == 0 else "table")
            widget.insert("end", "\n")
            table.clear()

        widget.tag_configure("table_head", foreground=TEXT)
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
                widget.insert("end", "•  " + stripped[2:].replace("**", "") + "\n", "bullet")
            else:
                widget.insert("end", stripped.replace("**", "") + "\n")
        flush_table()
        lines = int(widget.index("end-1c").split(".")[0])
        widget.configure(height=min(max(lines + 2, 4), 60), state="disabled")

    def _run_brief(self, models):
        if self.brief_running:
            return
        self.brief_running = True
        self.brief_status.set(f"Claude is researching {', '.join(models)}… this can take a minute.")
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
        if models != self.app.compare_models or not self.winfo_ismapped():
            return
        if error:
            self.brief_status.set(f"Could not generate the brief: {error}")
            return
        self._show_brief(text)
        self.brief_status.set("Generated just now")

    def _evidence(self, inner, models, facts):
        section_title(inner, "Evidence & coverage")
        for model in models:
            box = tk.Frame(inner, bg=CARD, padx=16, pady=12, highlightthickness=1, highlightbackground=BORDER)
            box.pack(fill="x", padx=24, pady=5)
            tk.Label(box, text=model, bg=CARD, fg=MAUVE, font=f(12, "bold")).pack(anchor="w")
            seen = set()
            for fact in facts.get(model, [])[:8]:
                key = (fact["name"], fact["value"])
                if key in seen:
                    continue
                seen.add(key)
                row = tk.Frame(box, bg=CARD, cursor="hand2")
                row.pack(fill="x", pady=1)
                value = analyzer.format_fact_value(fact["kind"], fact["value"], fact["unit"])
                tk.Label(row, text=f"{fact['name']}: {value}", bg=CARD, fg=GREEN, font=f(9, "bold"), width=34,
                         anchor="w").pack(side="left")
                source = tk.Label(row, text=f"{fact['source']} — {shorten(fact['title'], 90)}", bg=CARD, fg=SUBTEXT,
                                  font=f(9), anchor="w")
                source.pack(side="left", fill="x")
                for widget in (row, source):
                    widget.bind("<Button-1>", lambda e, link=fact["link"]: webbrowser.open(link))
            articles = db.query_articles(model=model, sort="top", limit=4)
            if articles:
                tk.Label(box, text="Top coverage", bg=CARD, fg=MUTED, font=f(9, "bold")).pack(anchor="w", pady=(8, 2))
            for article in articles:
                link = tk.Label(box, text=f"↗  {article['title']}  ({article['source']}, "
                                          f"{time_ago(article['published_at'])})",
                                bg=CARD, fg=SUBTEXT, font=f(10), anchor="w", justify="left", cursor="hand2")
                link.pack(fill="x")
                self.scroll.wrap(link, 110)
                link.bind("<Button-1>", lambda e, url=article["link"]: webbrowser.open(url))
                link.bind("<Enter>", lambda e, l=link: l.configure(fg=ACCENT))
                link.bind("<Leave>", lambda e, l=link: l.configure(fg=SUBTEXT))
            if not facts.get(model) and not articles:
                tk.Label(box, text="No coverage stored for this model yet.", bg=CARD, fg=MUTED,
                         font=f(9)).pack(anchor="w")
        tk.Frame(inner, bg=BG, height=24).pack()


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
    return [(name, analyzer.format_fact_value(f_["kind"], f_["value"], f_["unit"])) for (_, name), f_ in order][:limit]


def main():
    try:  # crisp text on high-DPI Windows displays
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    db.init_db()
    root = tk.Tk()
    NewsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
