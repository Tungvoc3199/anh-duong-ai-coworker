"""Cache data models and result types."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """Immutable cache entry with payload and metadata."""

    namespace: str
    key_hash: str
    dependency_fingerprint: str
    payload: Any
    payload_sha256: str
    created_at_epoch: float
    expires_at_epoch: float | None
    byte_size: int
    schema_version: int = 1
    expires_at_monotonic: float | None = None

@dataclass(frozen=True, slots=True)
class CacheHit:
    """Successful cache lookup."""

    outcome: Literal["hit"] = "hit"
    source: Literal["l1", "l2"] = "l1"
    payload: Any = None
    latency_ms: float = 0.0
    expires_at_epoch: float | None = None

@dataclass(frozen=True, slots=True)
class CacheMiss:
    """Failed cache lookup with reason."""

    outcome: Literal["miss"] = "miss"
    reason: str = "not_found"
    latency_ms: float = 0.0

CacheResult = CacheHit | CacheMiss
