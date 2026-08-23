"""Cache-aware persona loader."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.persona.loader import load_persona
from app.persona.models import PersonaSnapshot

if TYPE_CHECKING:
    from app.cache.service import CacheService

def create_cached_persona_loader(
    persona_root: Path,
    cache_service: CacheService | None,
    ttl_seconds: float,
) -> Callable[[], PersonaSnapshot]:
    """Create persona loader with optional L1-only cache.
    
    Cache key: persona root path
    Dependencies: none (persona is self-versioned via content_hash)
    Storage: L1 only (snapshot contains full text, unsuitable for L2 persistence)
    TTL: configurable (default 60s)
    """
    
    def cached_loader() -> PersonaSnapshot:
        if cache_service is None:
            return load_persona(persona_root)
        
        # Try cache
        key_data = {"root": str(persona_root.resolve())}
        dependencies: dict[str, Any] = {}  # Persona is self-versioned
        
        result = cache_service.get(
            "persona.snapshot",
            key_data,
            dependencies,
            use_l2=False,
        )
        
        # Cache hit
        if result.outcome == "hit":
            return PersonaSnapshot(**result.payload)
        
        # Persona snapshots contain full text and are strictly L1-only.
        snapshot = load_persona(persona_root)
        cache_service.put(
            "persona.snapshot",
            key_data,
            dependencies,
            snapshot.__dict__,
            ttl_seconds=ttl_seconds,
            use_l2=False,
        )
        return snapshot
    
    return cached_loader
