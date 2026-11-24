"""Sequential low-cost end-to-end plumbing check, distinct from full acceptance."""
from .acceptance import Acceptance
from .common import save
from .runner import Runner


def run(rt, fixtures, scripts):
    api = Acceptance(rt, fixtures)
    # Two sequential cases: real register/OTP/login, then catalog + booking + cancel.
    cases = [api.case("functional.auth", api.auth),
             api.case("functional.catalog_and_booking", api.catalog)]
    runner = Runner(rt, fixtures, scripts)
    trials = []
    for workload in ("read", "write", "mixed"):
        trials.append(runner.stage(workload, 1, rt.config["load"]["measure_seconds"],
                                   label="smoke", worker_override=1))
    result = {"status": "PASS" if all(c["status"] == "PASS" for c in cases)
              and all(t["status"] == "PASS" for t in trials) else "FAIL_OR_INCOMPLETE",
              "cases": [{"name": c["name"], "status": c["status"]} for c in cases],
              "trials": [{"workload": t["workload"], "status": t["status"]} for t in trials],
              "scope": "one VU, sequential auth/business/load/oracle/export plumbing; no capacity, concurrency, fault or endurance claim"}
    save(rt.root / "smoke.json", result)
    return result
