"""Pure adaptive policy: validity failures never become a backend capacity bound."""
import math


INVALID = {"GENERATOR_LIMITED", "FIXTURE_EXHAUSTED", "ENVIRONMENT_LIMITED", "INCOMPLETE", "BUDGET_EXHAUSTED"}


class Search:
    def __init__(self, initial=20, growth=1.6, precision=0.05, probes=2, overload_factor=1.1):
        self.initial, self.growth, self.precision = initial, growth, precision
        self.probes, self.overload_factor = probes, overload_factor
        self.low = self.high = None
        self.next = initial
        self.phase = "discovery"
        self.probed = 0
        self.stopped = None
        self.history = []
        self.contradictions = []

    def observe(self, vu, status):
        self.history.append({"vu": vu, "status": status, "phase": self.phase})
        if status in INVALID or status == "CORRECTNESS_FAILURE":
            self.stopped = status
            return None
        if self.phase == "overload":
            if status == "PASS":
                self.contradictions.append({"failed_bound": self.high, "higher_passing_vu": vu})
                self.low, self.high = vu, None
                self.phase, self.probed = "discovery", 0
                self.next = max(vu + 1, math.ceil(vu * self.growth))
                return self.next
            self.probed += 1
            if self.probed >= self.probes:
                self.stopped = "BRACKETED" if self.low else "NO_PASSING_LEVEL"
                return None
            self.next = max(vu + 1, math.ceil(vu * self.overload_factor))
            return self.next
        if status == "PASS":
            self.low = max(self.low or 0, vu)
        else:
            self.high = min(self.high or vu, vu)
        if self.high is None:
            self.next = max(vu + 1, math.ceil(vu * self.growth))
        elif self.low is None:
            if vu > 1:
                self.next = max(1, vu // 2)
            else:
                self.phase = "overload"
                self.next = math.ceil(self.high * self.overload_factor) if self.probes else None
        elif self.high - self.low > max(1, math.ceil(self.low * self.precision)):
            self.phase = "refine"
            self.next = (self.low + self.high) // 2
        else:
            self.phase = "overload"
            self.next = math.ceil(self.high * self.overload_factor) if self.probes else None
        if self.next is None:
            self.stopped = "BRACKETED" if self.low else "NO_PASSING_LEVEL"
        return self.next


def classify(stats, load, oracle=None):
    """Use all completed measured-start requests, including timeout latency, for SLOs."""
    if oracle and oracle["status"] == "FAIL":
        return "CORRECTNESS_FAILURE"
    if stats.get("assertions", 0) or stats.get("all_phase_assertions", 0):
        return "CORRECTNESS_FAILURE"
    if not stats.get("complete") or stats.get("pending", 0) or not stats.get("requests"):
        return "INCOMPLETE"
    if stats.get("fixture_exhausted"):
        return "FIXTURE_EXHAUSTED"
    if stats.get("generator_limited"):
        return "GENERATOR_LIMITED"
    if stats.get("target_not_maintained"):
        return "GENERATOR_LIMITED"
    if stats.get("backend_exited"):
        return "OVERLOAD"
    if stats["unexpected_errors"] / stats["requests"] > load["max_unexpected_error_ratio"]:
        return "SLO_BREACH"
    for family in ("read", "write"):
        p95 = stats.get(family + "_p95_ms")
        if p95 is not None and p95 > load["slo_" + family + "_p95_ms"]:
            return "SLO_BREACH"
    for name, endpoint in stats.get("endpoints", {}).items():
        family = "read" if name.startswith("GET ") else "write"
        if endpoint.get("p95_ms") is not None and endpoint["p95_ms"] > load["slo_" + family + "_p95_ms"]:
            return "SLO_BREACH"
    return "PASS"
