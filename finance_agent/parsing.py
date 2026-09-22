from __future__ import annotations

import re

_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def strip_code_fence(text: str) -> str:
    """Models routinely wrap JSON replies in markdown code fences even when
    told not to. Strip that wrapper before attempting to parse."""
    text = text.strip()
    match = _FENCE_PATTERN.match(text)
    if match:
        return match.group(1).strip()
    return text
