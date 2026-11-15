"""Write a resolved smoke/acceptance config outside the read-only Kaggle input."""
import argparse
import json
from pathlib import Path

import yaml

from bbtest.configuration import select


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("smoke", "acceptance"), default="smoke")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overrides", default="{}")
    args = parser.parse_args()
    config = select(Path(__file__).resolve().parents[1] / "config", args.mode, json.loads(args.overrides))
    args.output.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    print("Run mode:", config["profile"], "config:", args.output)
