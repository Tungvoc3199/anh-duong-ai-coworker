"""Cache key generation with versioned canonical hashing."""
from __future__ import annotations

import hashlib
import json
from typing import Any

CACHE_KEY_VERSION = "v1"

def generate_cache_key(
    namespace: str,
    key_data: dict[str, Any],
) -> str:
    """Generate versioned cache key: adcache:v1:<namespace>:<sha256(canonical)>."""
    if not namespace or not isinstance(namespace, str):
        raise ValueError("namespace must be a non-empty string")
    
    canonical = json.dumps(key_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    key_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    
    return f"adcache:{CACHE_KEY_VERSION}:{namespace}:{key_hash}"

def extract_key_hash(cache_key: str) -> str:
    """Extract the SHA-256 hash portion from a cache key."""
    parts = cache_key.split(":")
    if len(parts) != 4 or parts[0] != "adcache":
        raise ValueError(f"invalid cache key format: {cache_key}")
    return parts[3]

def generate_dependency_fingerprint(dependencies: dict[str, Any]) -> str:
    """Generate SHA-256 fingerprint for dependency validation."""
    canonical = json.dumps(dependencies, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
