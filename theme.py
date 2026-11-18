"""Colours and fonts for the desktop app.

Widgets read colours from `T` when they are created, so switching themes means
calling `apply()` and rebuilding the window. Every text colour meets WCAG AA
contrast (4.5:1) on the surfaces it is used on.
"""
import types
import tkinter.font as tkfont

LIGHT = {
    "bg": "#F4F5F7",
    "surface": "#FFFFFF",
    "surface_alt": "#F0F2F5",
    "sidebar": "#FAFAFB",
    "border": "#E1E4E9",
    "border_strong": "#C5CBD3",
    "text": "#111418",
    "text2": "#3B424D",
    "text3": "#5F6773",
    "accent": "#2456D3",
    "accent_hover": "#1C46B0",
    "accent_soft": "#E8EEFC",
    "on_accent": "#FFFFFF",
    "important": "#B93A0A",
    "important_soft": "#FFF0E6",
    "good": "#11704F",
    "good_soft": "#E3F3EC",
    "star": "#9A6100",
    "nav_active": "#E8EEFC",
    "scroll": "#C5CBD3",
}

DARK = {
    "bg": "#0E1014",
    "surface": "#171A20",
    "surface_alt": "#1F232B",
    "sidebar": "#12151A",
    "border": "#272C35",
    "border_strong": "#3B414D",
    "text": "#ECEEF2",
    "text2": "#BCC3CD",
    "text3": "#8D96A3",
    "accent": "#7EA6FF",
    "accent_hover": "#A2BFFF",
    "accent_soft": "#1C2944",
    "on_accent": "#0B1020",
    "important": "#FF9B5E",
    "important_soft": "#35231A",
    "good": "#4FD4A2",
    "good_soft": "#15302A",
    "star": "#F2C14E",
    "nav_active": "#1C2944",
    "scroll": "#3B414D",
}

CATEGORY_LIGHT = {
    "Model Release": "#6A3CD4",
    "Research": "#0A6B7D",
    "Open Source": "#25793A",
    "Products & Tools": "#1F58C7",
    "Business & Funding": "#935400",
    "Policy & Safety": "#BF2547",
    "Hardware & Chips": "#B4480C",
    "General": "#58606C",
}

CATEGORY_DARK = {
    "Model Release": "#B39BFF",
    "Research": "#45CBDD",
    "Open Source": "#6FDA82",
    "Products & Tools": "#7DAEFF",
    "Business & Funding": "#FFC452",
    "Policy & Safety": "#FF8A9C",
    "Hardware & Chips": "#FFA366",
    "General": "#A6AEBA",
}

T = types.SimpleNamespace(**LIGHT)
CATEGORY = dict(CATEGORY_LIGHT)
NAME = "light"

FAMILY = "TkDefaultFont"
SEMIBOLD = None  # a separate semibold family, when the platform has one
MONO = "TkFixedFont"
SCALE = 1.0


def apply(name):
    """Switch the palette in place ("light" or "dark")."""
    global NAME
    NAME = "dark" if name == "dark" else "light"
    T.__dict__.update(DARK if NAME == "dark" else LIGHT)
    CATEGORY.clear()
    CATEGORY.update(CATEGORY_DARK if NAME == "dark" else CATEGORY_LIGHT)


def mix(color, other, amount):
    """Blend `amount` (0-1) of `other` into `color`."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def soft(color):
    """A tinted background for a coloured label or pill."""
    return mix(color, T.surface, 0.86 if NAME == "light" else 0.80)


def category_color(category):
    return CATEGORY.get(category, CATEGORY["General"])


def setup_fonts(root, text_size="normal"):
    global FAMILY, SEMIBOLD, MONO, SCALE
    families = set(tkfont.families(root))
    for name in ("Segoe UI", "SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue", "Inter", "Ubuntu",
                 "Cantarell", "Noto Sans", "DejaVu Sans"):
        if name in families:
            FAMILY = name
            break
    SEMIBOLD = next((n for n in ("Segoe UI Semibold", "Inter SemiBold", "Inter Semi Bold") if n in families), None)
    MONO = next((n for n in ("Cascadia Mono", "Consolas", "SF Mono", "Menlo", "JetBrains Mono",
                             "DejaVu Sans Mono", "Liberation Mono") if n in families), "TkFixedFont")
    SCALE = 1.15 if text_size == "large" else 1.0


def font(size, weight="normal", italic=False):
    """weight: normal, semibold or bold."""
    size = max(7, round(size * SCALE))
    family = FAMILY
    if weight == "semibold":
        family, weight = (SEMIBOLD, "normal") if SEMIBOLD else (FAMILY, "bold")
    spec = (family, size, weight)
    return spec + ("italic",) if italic else spec


def mono(size):
    return (MONO, max(7, round(size * SCALE)))
