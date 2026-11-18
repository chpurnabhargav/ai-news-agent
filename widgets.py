"""Small Tkinter building blocks styled from theme.T."""
import tkinter as tk
from tkinter import ttk

import theme
from theme import T, font


def is_inside(widget, x_root, y_root):
    target = widget.winfo_containing(x_root, y_root)
    while target is not None:
        if target is widget:
            return True
        target = target.master
    return False


def bind_hover(widget, on_enter, on_leave):
    """Hover callbacks that don't flicker when the pointer moves over child widgets."""
    def enter(_):
        on_enter()

    def leave(event):
        if not is_inside(widget, event.x_root, event.y_root):
            on_leave()

    widget.bind("<Enter>", enter, add="+")
    widget.bind("<Leave>", leave, add="+")


def bind_click(widgets, command):
    for widget in widgets:
        widget.bind("<Button-1>", lambda e: (command(), "break")[1])
        widget.configure(cursor="hand2")


class Button(tk.Label):
    """A label-based button: looks the same on every platform, with hover.

    kind: primary, secondary (outlined), ghost (text with hover fill), link, quiet.
    """

    def __init__(self, parent, text, command=None, kind="secondary", size=10, padx=14, pady=6, bg=None, **kw):
        self.kind = kind
        self.parent_bg = bg or T.surface
        self.command = command
        self.fg_override = None  # e.g. the gold of a "Saved" toggle
        super().__init__(parent, text=text, font=font(size, "semibold" if kind in ("primary", "secondary") else "normal"),
                         padx=padx, pady=pady, cursor="hand2", **kw)
        self._paint(False)
        bind_hover(self, lambda: self._paint(True), lambda: self._paint(False))
        self.bind("<Button-1>", self._click)

    def _colors(self, hover):
        if self.kind == "primary":
            return (T.accent_hover if hover else T.accent), T.on_accent, None
        if self.kind == "secondary":
            return (T.surface_alt if hover else T.surface), T.text, (T.text3 if hover else T.border_strong)
        if self.kind == "ghost":
            return (T.surface_alt if hover else self.parent_bg), T.text2, None
        if self.kind == "link":
            return self.parent_bg, (T.accent_hover if hover else T.accent), None
        return self.parent_bg, (T.text if hover else T.text3), None  # quiet

    def repaint(self):
        self._paint(False)

    def _paint(self, hover):
        bg, fg, border = self._colors(hover)
        fg = self.fg_override or fg
        self.configure(bg=bg, fg=fg, highlightthickness=1 if border else 0,
                       highlightbackground=border or bg, highlightcolor=border or bg)

    def _click(self, _):
        if self.command:
            self.command()
        return "break"


def pill(parent, text, color, bg=None, command=None, size=9, solid=False):
    """A small rounded-looking tag. `solid` fills it with the colour."""
    label = tk.Label(parent, text=text, font=font(size, "semibold"), padx=8, pady=2,
                     bg=color if solid else (bg or theme.soft(color)),
                     fg=T.surface if solid else color)
    if command:
        label.configure(cursor="hand2")
        label.bind("<Button-1>", lambda e: (command(), "break")[1])
        base = label.cget("bg")
        bind_hover(label, lambda: label.configure(bg=theme.mix(base, color, 0.12)),
                   lambda: label.configure(bg=base))
    return label


def divider(parent, bg=None, pady=0, padx=0):
    line = tk.Frame(parent, bg=bg or T.border, height=1)
    line.pack(fill="x", pady=pady, padx=padx)
    return line


class Card(tk.Frame):
    """A white panel with a 1px border that darkens on hover."""

    def __init__(self, parent, padx=20, pady=16, hover=True, bg=None, border=None, **kw):
        self.border = border or T.border
        super().__init__(parent, bg=bg or T.surface, padx=padx, pady=pady, highlightthickness=1,
                         highlightbackground=self.border, highlightcolor=self.border, **kw)
        if hover:
            bind_hover(self, lambda: self.configure(highlightbackground=T.border_strong),
                       lambda: self.configure(highlightbackground=self.border))


class ScrollFrame(tk.Frame):
    """A vertically scrolling page with a centred column of at most `max_width` pixels.

    Long lines are hard to read, so content never stretches across a very wide window.
    """

    def __init__(self, parent, bg=None, max_width=980, gutter=32):
        bg = bg or T.bg
        super().__init__(parent, bg=bg)
        self.max_width, self.gutter = max_width, gutter
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="n")
        self._wrapped = []
        self.width = max_width
        self.inner.bind("<Configure>", lambda e: self._update_region())
        self.canvas.bind("<Configure>", self._on_resize)

    def _column_width(self, canvas_width):
        return max(320, min(self.max_width, canvas_width - 2 * self.gutter))

    def wrap(self, label, margin=0):
        """Re-wrap `label` to the column width minus `margin` whenever the window resizes."""
        self._wrapped.append((label, margin))
        label.configure(wraplength=max(160, self.width - margin))
        return label

    def clear(self):
        for child in self.inner.winfo_children():
            child.destroy()
        self._wrapped = []
        self.canvas.yview_moveto(0)

    def _update_region(self):
        # The region spans the whole canvas width, so the centred column is not shifted sideways.
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), self.inner.winfo_reqheight()))

    def _on_resize(self, event):
        self.width = self._column_width(event.width)
        self.canvas.coords(self._window, event.width / 2, 0)
        self._update_region()
        self.canvas.itemconfig(self._window, width=self.width)
        for label, margin in self._wrapped:
            if label.winfo_exists():
                label.configure(wraplength=max(160, self.width - margin))

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


def flow(frame, widgets, gap=8, row_gap=8):
    """Lay widgets out left to right, wrapping onto new rows to fit the frame width."""
    def layout(_=None):
        width = frame.winfo_width()
        if width <= 1:
            return
        x = y = row_height = 0
        for widget in widgets:
            w, h = widget.winfo_reqwidth(), widget.winfo_reqheight()
            if x and x + w > width:
                x, y = 0, y + row_height + row_gap
                row_height = 0
            widget.place(x=x, y=y)
            x += w + gap
            row_height = max(row_height, h)
        frame.configure(height=max(1, y + row_height))

    frame.bind("<Configure>", layout)
    frame.after_idle(layout)


def page_header(parent, title, subtitle=None, bg=None):
    """Big page title with an optional line underneath. Returns the right-hand action area."""
    bg = bg or T.bg
    frame = tk.Frame(parent, bg=bg)
    frame.pack(fill="x", pady=(28, 6))
    actions = tk.Frame(frame, bg=bg)
    actions.pack(side="right", anchor="s")
    tk.Label(frame, text=title, bg=bg, fg=T.text, font=font(22, "bold"), anchor="w").pack(anchor="w")
    if subtitle:
        tk.Label(frame, text=subtitle, bg=bg, fg=T.text3, font=font(11), anchor="w").pack(anchor="w", pady=(2, 0))
    return actions


def section_header(parent, title, subtitle=None, bg=None, top=30):
    """A section title. Returns the right-hand action area."""
    bg = bg or T.bg
    frame = tk.Frame(parent, bg=bg)
    frame.pack(fill="x", pady=(top, 10))
    actions = tk.Frame(frame, bg=bg)
    actions.pack(side="right")
    tk.Label(frame, text=title, bg=bg, fg=T.text, font=font(15, "bold")).pack(side="left")
    if subtitle:
        tk.Label(frame, text=subtitle, bg=bg, fg=T.text3, font=font(10)).pack(side="left", padx=10, pady=(3, 0))
    return actions


def eyebrow(parent, text, color=None, bg=None):
    """A small all-caps label above a block of content."""
    label = tk.Label(parent, text=text.upper(), bg=bg or T.surface, fg=color or T.text3, font=font(8, "bold"),
                     anchor="w")
    return label


def empty_state(parent, title, hint, icon="◇"):
    frame = tk.Frame(parent, bg=T.bg)
    frame.pack(fill="x", pady=70)
    tk.Label(frame, text=icon, bg=T.bg, fg=T.border_strong, font=font(30)).pack()
    tk.Label(frame, text=title, bg=T.bg, fg=T.text, font=font(14, "bold")).pack(pady=(8, 0))
    tk.Label(frame, text=hint, bg=T.bg, fg=T.text3, font=font(11)).pack(pady=4)
    return frame


class Segmented(tk.Frame):
    """Two or more mutually exclusive options shown as joined buttons."""

    def __init__(self, parent, options, variable, command=None, bg=None):
        super().__init__(parent, bg=T.border_strong, padx=1, pady=1)
        self.variable, self.command, self.labels = variable, command, {}
        for option in options:
            label = tk.Label(self, text=option, font=font(10, "semibold"), padx=12, pady=5, cursor="hand2")
            label.pack(side="left", padx=(0 if not self.labels else 1, 0))
            label.bind("<Button-1>", lambda e, o=option: self._select(o))
            self.labels[option] = label
        self._paint()

    def _select(self, option):
        self.variable.set(option)
        self._paint()
        if self.command:
            self.command()

    def _paint(self):
        for option, label in self.labels.items():
            active = option == self.variable.get()
            label.configure(bg=T.accent_soft if active else T.surface, fg=T.accent if active else T.text2)


class SearchBox(tk.Frame):
    """A bordered entry with a search glyph and placeholder text."""

    def __init__(self, parent, variable, placeholder="Search", width=30, on_submit=None, bg=None):
        super().__init__(parent, bg=T.surface, highlightthickness=1, highlightbackground=T.border_strong,
                         highlightcolor=T.accent)
        self.variable, self.placeholder = variable, placeholder
        tk.Label(self, text="⌕", bg=T.surface, fg=T.text3, font=font(13)).pack(side="left", padx=(10, 0))
        self.entry = tk.Entry(self, textvariable=variable, width=width, bg=T.surface, fg=T.text,
                              insertbackground=T.text, relief="flat", font=font(11), highlightthickness=0,
                              disabledbackground=T.surface)
        self.entry.pack(side="left", padx=(6, 10), pady=6, fill="x", expand=True)
        self.hint = tk.Label(self.entry, text=placeholder, bg=T.surface, fg=T.text3, font=font(11), cursor="xterm")
        self.hint.bind("<Button-1>", lambda e: self.entry.focus_set())
        self.entry.bind("<FocusIn>", lambda e: self.configure(highlightbackground=T.accent), add="+")
        self.entry.bind("<FocusOut>", lambda e: self.configure(highlightbackground=T.border_strong), add="+")
        if on_submit:
            self.entry.bind("<Return>", lambda e: on_submit())
        self.entry.bind("<Escape>", lambda e: variable.set(""))
        variable.trace_add("write", lambda *_: self._update_hint())
        self._update_hint()

    def _update_hint(self):
        if self.variable.get():
            self.hint.place_forget()
        else:
            self.hint.place(x=1, rely=0.5, anchor="w")


def style_ttk(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TCombobox", fieldbackground=T.surface, background=T.surface, foreground=T.text,
                    arrowcolor=T.text2, bordercolor=T.border_strong, lightcolor=T.surface, darkcolor=T.surface,
                    padding=(8, 5), arrowsize=14)
    style.map("TCombobox", fieldbackground=[("readonly", T.surface)], foreground=[("readonly", T.text)],
              selectbackground=[("readonly", T.surface)], selectforeground=[("readonly", T.text)],
              bordercolor=[("focus", T.accent), ("hover", T.text3)], background=[("active", T.surface_alt)])
    root.option_add("*TCombobox*Listbox.background", T.surface)
    root.option_add("*TCombobox*Listbox.foreground", T.text)
    root.option_add("*TCombobox*Listbox.selectBackground", T.accent_soft)
    root.option_add("*TCombobox*Listbox.selectForeground", T.text)
    root.option_add("*TCombobox*Listbox.font", font(11))
    root.option_add("*TCombobox*Listbox.borderWidth", 0)
    style.configure("Vertical.TScrollbar", background=T.scroll, troughcolor=T.bg, bordercolor=T.bg,
                    arrowcolor=T.text3, lightcolor=T.scroll, darkcolor=T.scroll, gripcount=0, arrowsize=12)
    style.map("Vertical.TScrollbar", background=[("active", T.text3), ("pressed", T.text3)])
    style.configure("Treeview", background=T.surface, fieldbackground=T.surface, foreground=T.text,
                    rowheight=round(36 * theme.SCALE), bordercolor=T.border, lightcolor=T.border,
                    darkcolor=T.border, borderwidth=0, font=font(11))
    style.configure("Treeview.Heading", background=T.surface_alt, foreground=T.text2, relief="flat",
                    font=font(10, "bold"), padding=(10, 8), bordercolor=T.border, lightcolor=T.surface_alt,
                    darkcolor=T.surface_alt)
    style.map("Treeview", background=[("selected", T.accent_soft)], foreground=[("selected", T.text)])
    style.map("Treeview.Heading", background=[("active", T.border)])
    style.configure("TCheckbutton", background=T.bg, foreground=T.text2, font=font(10),
                    indicatorbackground=T.surface, indicatorforeground=T.accent)
