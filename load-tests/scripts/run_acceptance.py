"""One command for an owned Kaggle/Linux acceptance run. No application build/edit."""
import argparse
from pathlib import Path
import sys
import signal

import yaml

from bbtest.acceptance import Acceptance, architecture
from bbtest.common import digest, save, validate_config
from bbtest.fixtures import Fixtures
from bbtest.report import archive, build
from bbtest.runner import Runner
from bbtest.runtime import Runtime
from bbtest.smoke import run as run_smoke


def main():
    def terminate(_signal, _frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "config/acceptance.yaml")
    parser.add_argument("--output", type=Path, required=True, help="Absent result directory")
    args = parser.parse_args()
    config = validate_config(yaml.safe_load(args.config.read_text(encoding="utf-8")))
    if not args.jar.is_file():
        parser.error("Upload the executable Spring Boot JAR as a Kaggle input")
    rt = Runtime(args.output, args.jar, config)
    code = 0
    try:
        save(rt.root / "config.json", config)
        sources = Path(__file__).resolve().parents[1]
        identity = {str(p.relative_to(sources)): digest(p) for p in sorted(sources.rglob("*"))
                    if p.is_file() and (p.suffix in (".py", ".yaml") or p.name == "requirements-kaggle.txt")
                    and not any(part in {"results", ".validation", "__pycache__"} for part in p.relative_to(sources).parts)}
        save(rt.root / "harness-identity.json", identity)
        save(rt.root / "architecture.json", architecture(args.jar))
        rt.setup()
        fixture = Fixtures(rt)
        fixture.prepare()
        if config["profile"] == "smoke":
            run_smoke(rt, fixture, Path(__file__).parent)
        else:
            Acceptance(rt, fixture).run()
            build(rt.root)
            archive(rt.root)
            # Keep collecting performance evidence even when a contract fails; never report a global pass.
            runner = Runner(rt, fixture, Path(__file__).parent)
            for workload in config["workloads"]:
                if runner.remaining() <= 0:
                    break
                runner.search(workload)
                # Keep a downloadable checkpoint even if a later long trial is interrupted.
                build(rt.root)
                archive(rt.root)
            runner.endurance()
            # Optional evidence: runs last so it can never take the soak's budget.
            build(rt.root)
            runner.open_model()
    except BaseException as error:
        code = 2
        save(rt.root / "fatal.json", {"type": type(error).__name__, "phase": "run",
                                    "message": "Run incomplete; inspect process logs and partial observations"})
        # Never serialize exception text which could contain DSN credentials.
        print("Acceptance interrupted:", type(error).__name__, flush=True)
    finally:
        try:
            rt.close()
        except Exception as error:
            save(rt.root / "cleanup.json", {"status": "UNKNOWN", "type": type(error).__name__})
            code = 2
        summary = build(rt.root)
        if summary["overall_status"] not in ("PASS_WITH_DECLARED_LIMITATIONS", "SMOKE_PASS"):
            code = 2
        print("REPORT:", rt.root / "REPORT.md", flush=True)
        print("ARCHIVE:", archive(rt.root), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
