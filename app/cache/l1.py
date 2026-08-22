"""L1 in-memory cache with TTL and LRU eviction."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

from app.cache.models import CacheEntry, CacheHit, CacheMiss, CacheResult


class L1Cache:
    """Thread-safe L1 cache with TTL and bounded capacity."""
    
    def __init__(
        self,
        *,
        max_entries_per_namespace: int = 100,
        max_bytes_per_namespace: int = 10 * 1024 * 1024,  # 10 MB
    ) -> None:
        self._max_entries = max_entries_per_namespace
        self._max_bytes = max_bytes_per_namespace
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._metrics = {"hits": 0, "misses": 0, "evictions": 0}
    
    def get(
        self,
        cache_key: str,
        *,
        now_monotonic: float | None = None,
        dependency_fingerprint: str | None = None,
    ) -> CacheResult:
        """Get entry from L1; returns hit or miss with reason."""
        start = time.monotonic()
        
        with self._lock:
            if cache_key not in self._store:
                self._metrics["misses"] += 1
                latency_ms = (time.monotonic() - start) * 1000.0
                return CacheMiss(reason="not_found", latency_ms=latency_ms)
            
            entry = self._store[cache_key]
            
            # Check dependency fingerprint if provided
            if (
                dependency_fingerprint is not None
                and entry.dependency_fingerprint != dependency_fingerprint
            ):
                self._metrics["misses"] += 1
                latency_ms = (time.monotonic() - start) * 1000.0
                return CacheMiss(reason="dependency_mismatch", latency_ms=latency_ms)
            
            # L1 TTL is process-local and must be monotonic-clock based.
            now = now_monotonic if now_monotonic is not None else time.monotonic()
            if (
                entry.expires_at_monotonic is not None
                and now >= entry.expires_at_monotonic
            ):
                # Expired entry: remove and return miss
                del self._store[cache_key]
                self._metrics["misses"] += 1
                latency_ms = (time.monotonic() - start) * 1000.0
                return CacheMiss(reason="expired", latency_ms=latency_ms)
            
            # Move to end (LRU)
            self._store.move_to_end(cache_key)
            
            self._metrics["hits"] += 1
            latency_ms = (time.monotonic() - start) * 1000.0
            return CacheHit(
                source="l1",
                payload=entry.payload,
                latency_ms=latency_ms,
            )
    
    def put(self, cache_key: str, entry: CacheEntry) -> None:
        """Store entry in L1 with eviction if needed."""
        with self._lock:
            # Remove old entry if exists
            if cache_key in self._store:
                del self._store[cache_key]
            
            # Add new entry
            self._store[cache_key] = entry
            
            # Evict by namespace constraints
            self._evict_if_needed(entry.namespace)
    
    def _evict_if_needed(self, namespace: str) -> None:
        """Evict LRU entries in namespace if over capacity."""
        # Count namespace entries and bytes
        ns_keys = [k for k in self._store if k.split(":")[2] == namespace]
        ns_bytes = sum(self._store[k].byte_size for k in ns_keys)
        
        # Evict LRU while over limits
        while len(ns_keys) > self._max_entries or ns_bytes > self._max_bytes:
            if not ns_keys:
                break
            
            # Find oldest (first) key in namespace
            oldest_key = next(k for k in self._store if k.split(":")[2] == namespace)
            # oldest_entry not needed, just delete by key
            
            del self._store[oldest_key]
            self._metrics["evictions"] += 1
            
            ns_keys = [k for k in self._store if k.split(":")[2] == namespace]
            ns_bytes = sum(self._store[k].byte_size for k in ns_keys)
    
    def invalidate(self, cache_key: str) -> bool:
        """Remove specific key; returns True if existed."""
        with self._lock:
            if cache_key in self._store:
                del self._store[cache_key]
                return True
            return False
    
    def clear_namespace(self, namespace: str) -> int:
        """Remove all keys in namespace; returns count removed."""
        with self._lock:
            to_remove = [k for k in self._store if k.split(":")[2] == namespace]
            for key in to_remove:
                del self._store[key]
            return len(to_remove)
    
    def get_metrics(self) -> dict[str, int]:
        """Return safe copy of metrics."""
        with self._lock:
            return self._metrics.copy()
