"""Generate deterministic contract snapshots without opening a database or socket."""

import argparse
import json
from pathlib import Path

from omnicore.adapters import TaskProgress, TaskRequest
from omnicore.app import create_app
from omnicore.config import RuntimeConfig
from omnicore.localization import catalog
from omnicore.schemas import ClientEvent, Locale, ModelMetadata, Preferences, ServerEvent

ROOT = Path(__file__).resolve().parents[1]


def snapshots() -> dict[str, dict]:
    app = create_app(RuntimeConfig(data_dir=Path("unused-contract-export")))
    result = {"openapi.json": app.openapi()}
    for model in [Preferences, ModelMetadata, ServerEvent, ClientEvent, TaskRequest, TaskProgress]:
        result[f"{model.__name__}.schema.json"] = model.model_json_schema()
    for locale in Locale:
        result[f"locales/{locale.value}.json"] = catalog(locale)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, data in snapshots().items():
        path = ROOT / "contracts" / name
        expected = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.check:
            if not path.is_file() or path.read_text() != expected:
                raise SystemExit(f"Contract out of date: {path.relative_to(ROOT)}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected)
    print("Contracts verified" if args.check else "Contracts exported")


if __name__ == "__main__":
    main()
