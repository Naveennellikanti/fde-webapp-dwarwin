"""Turn arbitrary file / sheet names into safe, stable SQL identifiers."""
from __future__ import annotations

import re


def sanitize_identifier(raw: str) -> str:
    name = raw.strip().lower()
    name = re.sub(r"[^0-9a-z]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        name = "table"
    if name[0].isdigit():
        name = f"t_{name}"
    return name


def unique_name(candidate: str, taken: set[str]) -> str:
    base = sanitize_identifier(candidate)
    name = base
    i = 2
    while name in taken:
        name = f"{base}_{i}"
        i += 1
    taken.add(name)
    return name
