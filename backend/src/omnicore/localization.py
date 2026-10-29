"""Packaged catalogs shared with all clients through the API and contracts."""

import json
from importlib.resources import files

from omnicore.schemas import Locale


def catalog(locale: Locale) -> dict[str, str]:
    return json.loads(files("omnicore").joinpath("locales", f"{locale.value}.json").read_text())


def negotiate_locale(header: str | None) -> Locale:
    choices = []
    for order, part in enumerate((header or "").split(",")):
        language, *params = part.strip().split(";")
        quality = 1.0
        for param in params:
            if param.strip().startswith("q="):
                try:
                    quality = float(param.strip()[2:])
                except ValueError:
                    quality = 0.0
        if 0 < quality <= 1:
            choices.append((-quality, order, language.lower().split("-")[0]))
    for _, _, language in sorted(choices):
        if language in {"pl", "en"}:
            return Locale.PL if language == "pl" else Locale.EN
    return Locale.EN


def message(code: str, header: str | None = None) -> str:
    return catalog(negotiate_locale(header))[f"error.{code}"]
