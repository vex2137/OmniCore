"""Set the canonical release version; run uv lock afterwards to refresh metadata."""

import argparse
import json
import re
from pathlib import Path

from packaging.version import Version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="For example 0.2.0-beta.3")
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?", args.version):
        parser.error("Use X.Y.Z or X.Y.Z-{alpha,beta,rc}.N")
    Version(args.version)
    path = Path(__file__).resolve().parents[1] / "backend/src/omnicore/distribution.json"
    data = json.loads(path.read_text())
    data["version"] = args.version
    path.write_text(json.dumps(data, indent=2) + "\n")
    print("Version updated. Run uv lock, export contracts and tests before building.")


if __name__ == "__main__":
    main()
