"""Value objects for action and workflow outcomes; no desktop or storage IO."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

__all__ = ["StepResult", "ExecutionReport", "success", "failure"]


@dataclass(frozen=True)
class StepResult:
    status: str
    message: str = ""
    action: str = ""
    line: int = 0

    @property
    def ok(self) -> bool:
        return self.status in {"succeeded", "handed_off", "skipped"}


def success(message: str = "") -> StepResult:
    return StepResult("succeeded", message)


def failure(message: str, status: str = "failed") -> StepResult:
    return StepResult(status, message)


@dataclass
class ExecutionReport:
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(step.ok for step in self.steps)

    @property
    def status(self) -> str:
        for status in ("failed", "blocked", "unsupported", "cancelled"):
            if any(step.status == status for step in self.steps):
                return status
        if not self.steps or all(step.status == "skipped" for step in self.steps):
            return "skipped"
        if any(step.status == "handed_off" for step in self.steps):
            return "handed_off"
        return "succeeded"

    def to_dict(self) -> dict:
        error = next((step.message for step in self.steps if not step.ok), None)
        return {"success": self.ok, "status": self.status, "error": error,
                "steps": [asdict(step) for step in self.steps]}
