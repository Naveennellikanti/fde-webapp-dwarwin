"""Lightweight PII masking for the sample rows that go into the LLM prompt.

This is deliberately conservative: it masks values that *look* like emails, phone
numbers, long digit sequences (cards/SSNs/account numbers), and generic long tokens.
The real data always stays in DuckDB; only these masked samples ever transit to a
hosted model. In local (Ollama) mode nothing leaves the machine at all.
"""
from __future__ import annotations

import re
from typing import Any

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Phone-like: 10+ digits with separators, but NOT date/timestamp shaped (see _DATELIKE).
_PHONE = re.compile(r"(?<![\d/-])(\+?\d[\d\s().-]{8,}\d)(?![\d/-])")
_LONG_DIGITS = re.compile(r"(?<!\d)\d{9,}(?!\d)")  # SSN/card/account-like

# Dates and timestamps must never be masked — they are essential schema signal for
# trend questions, and they are not PII on their own.
_DATELIKE = re.compile(
    r"""^\s*(
        \d{4}[-/]\d{1,2}([-/]\d{1,2})?          # 2024-07-01 / 2024/07
      | \d{1,2}[-/]\d{1,2}[-/]\d{2,4}           # 01-07-2024
    )
    ([ T]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?)?       # optional time part
    \s*(Z|[+-]\d{2}:?\d{2})?\s*$""",
    re.X,
)


def mask_value(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        # Only mask suspiciously long integers; leave normal numbers intact for accuracy.
        if isinstance(value, int) and not isinstance(value, bool) and len(str(abs(value))) >= 9:
            return "«masked»"
        return value

    if _DATELIKE.match(value):
        return value

    s = value
    s = _EMAIL.sub("«email»", s)
    # Order matters: an unbroken run of 9+ digits is an id/account/card, not a phone.
    s = _LONG_DIGITS.sub("«id»", s)
    s = _PHONE.sub("«phone»", s)
    return s


def mask_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: mask_value(v) for k, v in row.items()}


def mask_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [mask_row(r) for r in rows]
