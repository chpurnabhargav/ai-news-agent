import datetime
import tkinter as tk
from tkinter import ttk
import webbrowser
import threading

import db
import fetcher


class NewsApp:
    def __init__(self, root):
        self.root = root
        root.title("AI News Agent")
        root.geometry("1050x700")
        root.minsize(800, 500)

        self.current_date = datetime.date.today().isoformat()
        self.articles = []
        self.filter_text = ""
        self.filter_source = "All"

        self._build_toolbar()
        self._build_list()
        self._build_status()

        threading.Thread(target=self._refresh_data, daemon=True).start()

    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg="#1e1e2e", padx=10, pady=8)
        bar.pack(fill="x")

        tk.Label(
            bar, text="AI News Agent", bg="#1e1e2e", fg="#cdd6f4",
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left")

        tk.Button(
            bar, text="Refresh", command=self._refresh_data_async,
            bg="#89b4fa", fg="#11111b", activebackground="#74c7ec",
            relief="flat", font=("Segoe UI", 10, "bold"),
        ).pack(side="left", padx=(20, 5))

        tk.Label(bar, text="Date:", bg="#1e1e2e", fg="#cdd6f4",
                 font=("Segoe UI", 10)).pack(side="left", padx=(15, 3))

        self.date_var = tk.StringVar(value=self.current_date)
        self.date_combo = ttk.Combobox(
            bar, textvariable=self.date_var, width=12, state="readonly"
        )
        self.date_combo.pack(side="left")
        self.date_combo.bind("<<ComboboxSelected>>", self._on_date_change)

        tk.Label(bar, text="Source:", bg="#1e1e2e", fg="#cdd6f4",
                 font=("Segoe UI", 10)).pack(side="left", padx=(15, 3))

        self.source_var = tk.StringVar(value="All")
        self.source_combo = ttk.Combobox(
            bar, textvariable=self.source_var, width=14, state="readonly"
        )
        self.source_combo.pack(side="left")
        self.source_combo.bind("<<ComboboxSelected>>", self._on_filter_change)

        tk.Label(bar, text="Search:", bg="#1e1e2e", fg="#cdd6f4",
                 font=("Segoe UI", 10)).pack(side="left", padx=(15, 3))

        self.search_entry = tk.Entry(
            bar, width=25, bg="#313244", fg="#cdd6f4", insertbackground="#cdd6f4",
            relief="flat", font=("Segoe UI", 10),
        )
        self.search_entry.pack(side="left")
        self.search_entry.bind("<KeyRelease>", self._on_search_change)

    def _build_list(self):
        wrap = tk.Frame(self.root)
        wrap.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(wrap, bg="#11111b", highlightthickness=0)
        self.scrollbar = tk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.content = tk.Frame(self.canvas, bg="#11111b")
        self.window_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")

        self.content.bind("<Configure>", self._sync_scrollregion)
        self.canvas.bind("<Configure>", self._resize_content)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _build_status(self):
        self.status_var = tk.StringVar(value="Loading news...")
        tk.Label(
            self.root, textvariable=self.status_var, bg="#181825", fg="#a6adc8",
            anchor="w", font=("Segoe UI", 9),
        ).pack(fill="x")

    def _sync_scrollregion(self, _):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_content(self, event):
        self.canvas.itemconfig(self.window_id, width=event.width)

    def _on_mousewheel(self, event):
        if self.canvas.winfo_exists():
            self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def _refresh_data(self):
        try:
            db.init_db()
            self.root.after(0, self._load_latest)
            count = fetcher.fetch_all()
            dates = db.get_available_dates()
            self.root.after(0, self._update_after_fetch, dates, count)
        except Exception as e:
            self.root.after(0, self.status_var.set, f"Error: {e}")

    def _load_latest(self):
        dates = db.get_available_dates()
        if dates:
            self.date_combo["values"] = dates
            self.current_date = dates[0]
            self.date_var.set(self.current_date)
            self._load_date()

    def _refresh_data_async(self):
        self.status_var.set("Refreshing...")
        threading.Thread(target=self._refresh_data, daemon=True).start()

    def _update_after_fetch(self, dates, count):
        if dates:
            self.date_combo["values"] = dates
            self.current_date = dates[0]
            self.date_var.set(self.current_date)
        self.status_var.set(f"Fetched {count} new articles today")
        self._load_date()

    def _on_date_change(self, _):
        self.current_date = self.date_var.get()
        self._load_date()

    def _on_filter_change(self, _):
        self.filter_source = self.source_var.get()
        self._render()

    def _on_search_change(self, _):
        self.filter_text = self.search_entry.get().strip().lower()
        self._render()

    def _load_date(self):
        self.articles = db.get_news_for_date(self.current_date)
        sources = sorted({a["source"] for a in self.articles})
        self.source_combo["values"] = ["All"] + sources
        self.source_var.set(
            self.filter_source if self.filter_source in sources else "All"
        )
        self._render()

    def _render(self):
        for widget in self.content.winfo_children():
            widget.destroy()

        items = self.articles
        if self.filter_source != "All":
            items = [a for a in items if a["source"] == self.filter_source]
        if self.filter_text:
            items = [
                a for a in items
                if self.filter_text in a["title"].lower()
                or self.filter_text in (a["summary"] or "").lower()
            ]

        self.status_var.set(
            f"{self.current_date}: {len(items)} articles"
            f" (total stored: {db.count_articles()})"
        )

        if not items:
            tk.Label(
                self.content, text="No news for this date. Click Refresh.",
                bg="#11111b", fg="#6c7086", font=("Segoe UI", 12),
            ).pack(pady=30)
            return

        for article in items:
            self._render_card(article)

    def _render_card(self, article):
        card = tk.Frame(
            self.content, bg="#1e1e2e", padx=12, pady=10, highlightthickness=0
        )
        card.pack(fill="x", padx=10, pady=5)

        published = article["published_at"]
        when = published.strftime("%b %d, %H:%M") if published else "unknown time"

        header = tk.Frame(card, bg="#1e1e2e")
        header.pack(fill="x")
        tk.Label(
            header, text=f"[{article['source']}]", bg="#1e1e2e", fg="#a6e3a1",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")
        tk.Label(
            header, text=when, bg="#1e1e2e", fg="#6c7086", font=("Segoe UI", 9),
        ).pack(side="right")

        tk.Label(
            card,
            text=article["title"],
            bg="#1e1e2e", fg="#cdd6f4", wraplength=940,
            font=("Segoe UI", 12, "bold"), justify="left",
            cursor="hand2",
        ).pack(fill="x", pady=(4, 0))
        if article["summary"]:
            tk.Label(
                card,
                text=article["summary"],
                bg="#1e1e2e", fg="#a6adc8", wraplength=940,
                font=("Segoe UI", 10), justify="left",
            ).pack(fill="x", pady=(2, 0))

        open_btn = tk.Button(
            card, text="Open article ↗", bg="#313244", fg="#89b4fa",
            activebackground="#45475a", activeforeground="#b4befe",
            relief="flat", cursor="hand2", font=("Segoe UI", 9),
            command=lambda link=article["link"]: webbrowser.open(link),
        )
        open_btn.pack(anchor="w", pady=(6, 0))

        card.bind("<Button-1>", lambda e, a=article: webbrowser.open(a["link"]))
        for child in card.winfo_children():
            child.bind("<Button-1>", lambda e, a=article: webbrowser.open(a["link"]), add="+")
        open_btn.bind("<Button-1>", lambda e: None, add="+")


def main():
    db.init_db()
    root = tk.Tk()
    NewsApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
