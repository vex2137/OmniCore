"""Distribution versions are separate from the stable backend component/API version."""

import json
from importlib.resources import files


def distribution_version() -> str:
    return json.loads(files("omnicore").joinpath("distribution.json").read_text())["version"]
