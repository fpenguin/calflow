"""Result values shared by trusted `run` backends and result handlers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RunResult:
    backend: str
    ok: bool
    title: str
    message: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: Optional[int] = None

    @property
    def result_text(self) -> str:
        """Human-facing result text for notify/copy/save handlers."""
        parts = []
        if self.message:
            parts.append(self.message)
        if self.stdout:
            parts.append(self.stdout.strip())
        if self.stderr:
            parts.append(self.stderr.strip())
        if not parts and self.returncode is not None:
            parts.append(f"exit code {self.returncode}")
        return "\n".join(p for p in parts if p).strip() or self.title


def ok_result(backend: str, message: str = "", *, stdout: str = "") -> RunResult:
    return RunResult(
        backend=backend,
        ok=True,
        title=f"CalFlow {backend} completed",
        message=message,
        stdout=stdout,
    )


def error_result(
    backend: str,
    message: str,
    *,
    stderr: str = "",
    returncode: Optional[int] = None,
) -> RunResult:
    return RunResult(
        backend=backend,
        ok=False,
        title=f"CalFlow {backend} failed",
        message=message,
        stderr=stderr,
        returncode=returncode,
    )
