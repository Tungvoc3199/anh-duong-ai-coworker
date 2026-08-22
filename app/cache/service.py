"""Cache service coordinating L1 + L2 tiers."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.cache.keys import extract_key_hash, generate_cache_key, generate_dependency_fingerprint
from app.cache.l1 import L1Cache
from app.cache.l2_sqlite import L2SQLiteCache
from app.cache.models import CacheEntry, CacheHit, CacheMiss, CacheResult


@dataclass(frozen=True)
class CacheSettings:
    """Cache configuration."""
    enabled: bool
    l1_enabled: bool
    l2_enabled: bool
    l1_max_entries: int
    l1_max_bytes: int
    l2_max_payload_bytes: int
    default_ttl_seconds: float
    cache_db_path: Path | None = None
    persona_ttl_seconds: float = 60.0
    memory_retrieval_ttl_seconds: float = 15.0
    l2_max_entries: int = 10_000
    l2_cleanup_batch_size: int = 100

class CacheService:
    """Unified cache service with L1 RAM + L2 SQLite tiers."""
    
    def __init__(self, settings: CacheSettings, db_path: Path) -> None:
        self._settings = settings
        self._db_path = db_path
        self._l1: L1Cache | None = None
        self._l2: L2SQLiteCache | None = None
    
    def start(self) -> None:
        """Initialize cache tiers."""
        if not self._settings.enabled:
            return
        
        if self._settings.l1_enabled:
            self._l1 = L1Cache(
                max_entries_per_namespace=self._settings.l1_max_entries,
                max_bytes_per_namespace=self._settings.l1_max_bytes,
            )
        
        if self._settings.l2_enabled:
            self._l2 = L2SQLiteCache(
                self._db_path,
                max_entries=self._settings.l2_max_entries,
                cleanup_batch_size=self._settings.l2_cleanup_batch_size,
            )
            self._l2.initialize()
    
    def get(
        self,
        namespace: str,
        key_data: dict[str, Any],
        dependencies: dict[str, Any],
        *,
        use_l2: bool = True,
    ) -> CacheResult:
        """Get from L1 then optionally L2, promoting L2 hits into L1."""
        if not self._settings.enabled:
            return CacheMiss(reason="disabled")
        
        cache_key = generate_cache_key(namespace, key_data)
        dep_fingerprint = generate_dependency_fingerprint(dependencies)
        
        # Try L1
        if self._l1:
            result = self._l1.get(cache_key, dependency_fingerprint=dep_fingerprint)
            if isinstance(result, CacheHit):
                return result
        
        # Try L2 only for callers that explicitly permit persistence.
        if use_l2 and self._l2 and self._l2.is_enabled():
            result = self._l2.get(cache_key, dep_fingerprint)
            if isinstance(result, CacheHit):
                # Promote to L1 with only the remaining persisted TTL.
                if self._l1:
                    remaining_ttl = (
                        max(result.expires_at_epoch - time.time(), 0.0)
                        if result.expires_at_epoch is not None
                        else None
                    )
                    entry = CacheEntry(
                        namespace=namespace,
                        key_hash=extract_key_hash(cache_key),
                        dependency_fingerprint=dep_fingerprint,
                        payload=result.payload,
                        payload_sha256=self._hash_payload(result.payload),
                        created_at_epoch=time.time(),
                        expires_at_epoch=result.expires_at_epoch,
                        byte_size=len(json.dumps(result.payload, ensure_ascii=False)),
                        expires_at_monotonic=(
                            time.monotonic() + remaining_ttl
                            if remaining_ttl is not None
                            else None
                        ),
                    )
                    self._l1.put(cache_key, entry)
                return result
        
        return CacheMiss(reason="not_found")
    
    def put(
        self,
        namespace: str,
        key_data: dict[str, Any],
        dependencies: dict[str, Any],
        payload: Any,
        ttl_seconds: float | None = None,
        *,
        use_l2: bool = True,
    ) -> None:
        """Store in L1 and, only when permitted, L2."""
        if not self._settings.enabled:
            return
        
        cache_key = generate_cache_key(namespace, key_data)
        dep_fingerprint = generate_dependency_fingerprint(dependencies)
        payload_json = json.dumps(payload, ensure_ascii=False)
        payload_bytes = len(payload_json)
        
        ttl = ttl_seconds if ttl_seconds is not None else self._settings.default_ttl_seconds
        now_epoch = time.time()
        expires_at_epoch = now_epoch + ttl if ttl > 0 else None
        expires_at_monotonic = time.monotonic() + ttl if ttl > 0 else None
        
        entry = CacheEntry(
            namespace=namespace,
            key_hash=extract_key_hash(cache_key),
            dependency_fingerprint=dep_fingerprint,
            payload=payload,
            payload_sha256=self._hash_payload(payload),
            created_at_epoch=now_epoch,
            expires_at_epoch=expires_at_epoch,
            byte_size=payload_bytes,
            expires_at_monotonic=expires_at_monotonic,
        )
        
        # Store in L1
        if self._l1:
            self._l1.put(cache_key, entry)
        
        # Store in L2 only when explicitly permitted and under the size limit.
        if use_l2 and self._l2 and self._l2.is_enabled():
            if payload_bytes <= self._settings.l2_max_payload_bytes:
                self._l2.put(cache_key, entry)
    
    def invalidate(self, namespace: str, key_data: dict[str, Any]) -> None:
        """Remove from both tiers."""
        if not self._settings.enabled:
            return
        
        cache_key = generate_cache_key(namespace, key_data)
        
        if self._l1:
            self._l1.invalidate(cache_key)
        
        if self._l2 and self._l2.is_enabled():
            self._l2.invalidate(cache_key)
    
    def clear_namespace(self, namespace: str, l1_only: bool = False) -> None:
        """Clear entire namespace from L1 and optionally L2."""
        if not self._settings.enabled:
            return
        
        if self._l1:
            self._l1.clear_namespace(namespace)
        
        if not l1_only and self._l2 and self._l2.is_enabled():
            pass
    
    def get_metrics(self) -> dict[str, Any]:
        """Return safe metrics without payload content."""
        metrics: dict[str, Any] = {
            "enabled": self._settings.enabled,
            "l1": {},
            "l2": {},
        }
        
        if self._l1:
            metrics["l1"] = self._l1.get_metrics()
        
        if self._l2:
            metrics["l2"] = {"enabled": self._l2.is_enabled()}
        
        return metrics
    
    @staticmethod
    def _hash_payload(payload: Any) -> str:
        """Generate SHA-256 hash of payload."""
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
