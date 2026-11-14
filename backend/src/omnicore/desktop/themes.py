"""Design System 2.0 theme tokens, accessible color math, and palette compatibility."""

from dataclasses import dataclass

DARK = ("#0d1118", "#131924", "#1b2434", "#edf2fa", "#96a6bf", "#273347")
LIGHT = ("#f4f6fa", "#ffffff", "#eceff6", "#1b2434", "#5c6c84", "#d8dfeb")
PALETTES = {
    "midnight": DARK,
    "graphite": ("#16161a", "#202026", "#2c2c34", "#f1f2f6", "#ababba", "#3e3e4a"),
    "oled": ("#000000", "#0a0a0d", "#16161c", "#f3f4f8", "#aeafb8", "#2e2e3a"),
    "light": LIGHT,
    "ocean": ("#0c1623", "#112134", "#19314a", "#edf5ff", "#a4bbd3", "#2d4c68"),
    "forest": ("#0f1914", "#16261d", "#213729", "#edf6ed", "#a7c0ab", "#354f3e"),
}


def palette(theme, system_dark=False):
    return PALETTES.get(theme, DARK if theme == "dark" or system_dark else LIGHT)


def contrast_ratio(first, second):
    def luminance(color):
        rgb = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
        return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))

    bright, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (bright + 0.05) / (dark + 0.05)


def mix_hex(first: str, second: str, weight: float) -> str:
    """Linearly interpolate between two #rrggbb hex colors (`0.0 -> first`, `1.0 -> second`)."""
    t = max(0.0, min(1.0, weight))
    return "#" + "".join(
        f"{round(int(first[i : i + 2], 16) * (1 - t) + int(second[i : i + 2], 16) * t):02x}"
        for i in (1, 3, 5)
    )


def readable_accent(color, foreground, backgrounds):
    """Adapt text/focus accents; preserve the chosen button fill separately."""
    for amount in range(0, 101, 5):
        mixed = mix_hex(color, foreground, amount / 100)
        if min(contrast_ratio(mixed, bg) for bg in backgrounds) >= 4.5:
            return mixed
    return foreground


@dataclass(frozen=True)
class ThemeTokens:
    """Centralized visual design tokens for OmniCore Desktop UI 2.0."""

    dark: bool
    bg: str
    sidebar: str
    panel: str
    elevated: str
    field: str
    hover: str
    fg: str
    fg_secondary: str
    muted: str
    border: str
    border_subtle: str
    border_strong: str
    accent_button: str
    accent: str
    accent_hover: str
    accent_text: str
    accent_tint: str
    accent_border: str
    success: str
    success_tint: str
    warning: str
    warning_tint: str
    danger: str
    danger_tint: str
    # 4/8px spacing tokens (logical base before ui_scale)
    sp_xs: int = 4
    sp_sm: int = 8
    sp_md: int = 12
    sp_lg: int = 16
    sp_xl: int = 20
    sp_2xl: int = 24
    # Radius tokens
    r_sm: int = 6
    r_md: int = 8
    r_lg: int = 12
    r_xl: int = 16


def resolve_theme_tokens(
    theme: str, system_dark: bool = False, custom_accent: str = ""
) -> ThemeTokens:
    """Compute layered surfaces, text hierarchy, and purple primary accent tokens."""
    dark = theme not in {"system", "light"} or (theme == "system" and system_dark)
    bg, panel, field, fg, muted, border = palette(theme, dark)

    default_accent = {
        "ocean": "#59a8e8",
        "forest": "#65b780",
        "graphite": "#9d92f5",
        "oled": "#a596ff",
    }.get(theme, "#8b7cf6" if dark else "#6b5ce7")
    accent_button = custom_accent or default_accent
    accent_text = max(("#000000", "#ffffff"), key=lambda c: contrast_ratio(c, accent_button))
    accent = readable_accent(accent_button, fg, (bg, panel, field))

    sidebar = mix_hex(bg, panel, 0.72) if dark else panel
    elevated = mix_hex(panel, field, 0.55) if dark else mix_hex(panel, bg, 0.35)
    hover = mix_hex(field, fg, 0.08 if dark else 0.06)
    fg_secondary = mix_hex(fg, muted, 0.38)
    border_subtle = mix_hex(panel, border, 0.65)
    border_strong = mix_hex(border, fg, 0.22)
    accent_hover = mix_hex(accent_button, "#ffffff" if dark else "#000000", 0.14)
    accent_tint = mix_hex(panel, accent_button, 0.18 if dark else 0.11)
    accent_border = mix_hex(border, accent_button, 0.52)

    success = "#3dd68c" if dark else "#178a56"
    warning = "#f2b84b" if dark else "#b87408"
    danger = "#f06565" if dark else "#cf3535"

    return ThemeTokens(
        dark=dark,
        bg=bg,
        sidebar=sidebar,
        panel=panel,
        elevated=elevated,
        field=field,
        hover=hover,
        fg=fg,
        fg_secondary=fg_secondary,
        muted=muted,
        border=border,
        border_subtle=border_subtle,
        border_strong=border_strong,
        accent_button=accent_button,
        accent=accent,
        accent_hover=accent_hover,
        accent_text=accent_text,
        accent_tint=accent_tint,
        accent_border=accent_border,
        success=success,
        success_tint=mix_hex(panel, success, 0.15 if dark else 0.10),
        warning=warning,
        warning_tint=mix_hex(panel, warning, 0.15 if dark else 0.10),
        danger=danger,
        danger_tint=mix_hex(panel, danger, 0.16 if dark else 0.10),
    )
