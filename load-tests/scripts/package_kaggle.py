"""Create a clean upload kit, excluding historical output, caches and validation data."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def package(root, destination, jar=None):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = []
    for folder in ("scripts", "tests", "config"):
        files.extend(p for p in (root / folder).rglob("*") if p.is_file()
                     and p.suffix in (".py", ".yaml") and "__pycache__" not in p.parts)
    files.extend(root / name for name in ("requirements-kaggle.txt", "ACCEPTANCE.md", "README.md",
                                        "notebook/busbooking-architecture-acceptance.ipynb"))
    identities = {}
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(files):
            content = path.read_bytes()
            name = "load-tests/" + path.relative_to(root).as_posix()
            identities[name] = hashlib.sha256(content).hexdigest()
            bundle.writestr(name, content)
        if jar:
            jar = Path(jar).resolve()
            with zipfile.ZipFile(jar) as candidate:
                if "BOOT-INF/classes/com/example/busbooking/BusBookingApplication.class" not in candidate.namelist():
                    raise ValueError("Not the executable BusBooking Spring Boot JAR")
            bundle.write(jar, "artifacts/busbooking.jar")
            with open(jar, "rb") as stream:
                identities["artifacts/busbooking.jar"] = hashlib.file_digest(stream, "sha256").hexdigest()
        bundle.writestr("kit-manifest.json", json.dumps(identities, indent=2))
    return destination


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, help="Optional unchanged executable JAR to include")
    parser.add_argument("--output", type=Path, default=root / "local-runs/busbooking-kaggle-kit.zip")
    args = parser.parse_args()
    print(package(root, args.output, args.jar))
