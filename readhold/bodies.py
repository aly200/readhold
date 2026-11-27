"""The base of every request body that holds a required text."""
from __future__ import annotations

from pydantic import BaseModel, model_validator


class Body(BaseModel):
    """A required text made only of spaces counts as empty.

    `min_length=1` alone lets "   " through; the routes then strip it and store an empty title.
    The text itself is not changed here: a note keeps its leading spaces and its last line break."""

    @model_validator(mode="after")
    def _no_blank_text(self):
        for name, field in type(self).model_fields.items():
            value = getattr(self, name)
            if isinstance(value, str) and not value.strip() and any(getattr(m, "min_length", 0) for m in field.metadata):
                raise ValueError(f"{name} is empty")
        return self
