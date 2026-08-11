from __future__ import annotations

import math
from typing import Protocol


class TokenEstimator(Protocol):
    """Estimate tokens deterministically; implementations need not be exact."""

    def estimate(self, text: str) -> int: ...


class Utf8ByteTokenEstimator:
    """Conservative deterministic estimate based on UTF-8 byte length."""

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text.encode("utf-8")) / 4))

