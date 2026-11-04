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
