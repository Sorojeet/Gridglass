"""Errors the engine raises. Every one carries a plain-language message safe to show users."""
from __future__ import annotations

from typing import Any


class GridglassError(Exception):
    code = "error"

    def __init__(self, message: str, **details: Any):
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.details}


class InvalidStepsError(GridglassError):
    """The step list itself is malformed (unknown tool, missing option, wrong type)."""

    code = "invalid_steps"


class StepError(GridglassError):
    """A valid step couldn't be applied to this data (e.g. the column doesn't exist)."""

    code = "step_failed"

    def __init__(self, message: str, step_index: int, op: str):
        super().__init__(message, step_index=step_index, op=op)
        self.step_index = step_index
        self.op = op


class IngestError(GridglassError):
    code = "bad_file"


class ExportError(GridglassError):
    code = "export_failed"


class ColumnError(ValueError):
    """Raised inside a step; the pipeline turns it into a StepError with the step's position."""
