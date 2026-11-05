"""Shared desktop palette tokens and native preview swatches."""

DARK = ("#10151f", "#161e2b", "#1d2736", "#ecf1f9", "#9daec4", "#2b3749")
LIGHT = ("#f5f6fa", "#ffffff", "#edf0f6", "#202b3c", "#607189", "#dce2ec")
PALETTES = {
    "midnight": DARK,
    "graphite": ("#181818", "#222222", "#303030", "#f1f1f1", "#b0b0b0", "#444444"),
    "oled": ("#000000", "#090909", "#181818", "#f2f2f2", "#b3b3b3", "#383838"),
    "light": LIGHT,
    "ocean": ("#0d1725", "#102337", "#19344e", "#edf5ff", "#a8bdd1", "#30506a"),
    "forest": ("#101a15", "#17291e", "#233b2a", "#edf6ed", "#a9c2ad", "#385341"),
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


def readable_accent(color, foreground, backgrounds):
    """Adapt text/focus accents; preserve the chosen button fill separately."""
    for amount in range(0, 101, 5):
        channels = [
            round(
                int(color[i : i + 2], 16) * (1 - amount / 100)
                + int(foreground[i : i + 2], 16) * amount / 100
            )
            for i in (1, 3, 5)
        ]
        mixed = "#" + "".join(f"{channel:02x}" for channel in channels)
        if min(contrast_ratio(mixed, bg) for bg in backgrounds) >= 4.5:
            return mixed
    return foreground
