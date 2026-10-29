import json
from importlib.resources import files


class Translator:
    def __init__(self, locale):
        core = json.loads(files("omnicore").joinpath(f"locales/{locale}.json").read_text())
        self.catalog = {
            k.removeprefix("error."): v for k, v in core.items() if k.startswith("error.")
        }
        self.catalog.update(
            json.loads(files("omnicore.desktop").joinpath(f"locales/{locale}.json").read_text())
        )

    def __call__(self, key, **values):
        return self.catalog.get(key, key).format(**values)
