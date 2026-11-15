"""Rebuild a partial/full evidence report and ZIP without restarting any service."""
import argparse
from pathlib import Path

from bbtest.report import archive, build


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    if not args.run.is_dir() or not (args.run / "config.json").is_file():
        parser.error("Select an existing acceptance run directory with config.json")
    print("STATUS:", build(args.run)["overall_status"])
    print("ARCHIVE:", archive(args.run))
