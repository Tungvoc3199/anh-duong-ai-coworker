"""L2 persistent SQLite cache."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

from app.cache.models import CacheEntry, CacheHit, CacheMiss, CacheResult

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cache_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cache_entries (
    namespace TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    key_hash TEXT NOT NULL,
    dependency_fingerprint TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_at_epoch REAL NOT NULL,
    expires_at_epoch REAL,
    accessed_at_epoch REAL NOT NULL,
    byte_size INTEGER NOT NULL,
    PRIMARY KEY (namespace, schema_version, key_hash)
);

CREATE INDEX IF NOT EXISTS idx_cache_entries_expiry 
    ON cache_entries(expires_at_epoch) WHERE expires_at_epoch IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cache_entries_accessed 
    ON cache_entries(accessed_at_epoch);
"""

class L2SQLiteCache:
    """L2 persistent cache with fail-open semantics."""
    
    def __init__(
        self,
        db_path: Path,
        *,
        max_entries: int = 10_000,
        cleanup_batch_size: int = 100,
    ) -> None:
        self._db_path = db_path
        self._max_entries = max_entries
        self._cleanup_batch_size = cleanup_batch_size
        self._enabled = False
    
    def initialize(self) -> None:
        """Create schema if needed; errors disable L2."""
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self._db_path),
                timeout=5.0,
                check_same_thread=False,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            
            conn.executescript(_SCHEMA_SQL)
            self._enforce_hard_capacity(conn, now_epoch=time.time())
            conn.commit()
            conn.close()

            self._enabled = True
        except Exception:
            self._enabled = False
    
    def get(self, cache_key: str, dependency_fingerprint: str) -> CacheResult:
        """Get entry from L2; fail-open on errors."""
        if not self._enabled:
            return CacheMiss(reason="not_found")
        
        start = time.monotonic()
        
        try:
            parts = cache_key.split(":")
            namespace = parts[2]
            key_hash = parts[3]
            schema_version = 1
            
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            cursor = conn.execute("""
                SELECT dependency_fingerprint, payload_json, payload_sha256, 
                       expires_at_epoch
                FROM cache_entries
                WHERE namespace = ? AND schema_version = ? AND key_hash = ?
            """, (namespace, schema_version, key_hash))
            
            row = cursor.fetchone()
            conn.close()
            
            if row is None:
                latency_ms = (time.monotonic() - start) * 1000.0
                return CacheMiss(reason="not_found", latency_ms=latency_ms)
            
            stored_dep, payload_json, payload_sha256, expires_at = row
            
            # Check dependency
            if stored_dep != dependency_fingerprint:
                latency_ms = (time.monotonic() - start) * 1000.0
                return CacheMiss(reason="dependency_mismatch", latency_ms=latency_ms)
            
            # Check expiry
            if expires_at is not None and time.time() >= expires_at:
                latency_ms = (time.monotonic() - start) * 1000.0
                return CacheMiss(reason="expired", latency_ms=latency_ms)
            
            # Parse and verify payload integrity using write's canonical contract.
            try:
                payload = json.loads(payload_json)
            except json.JSONDecodeError:
                self._delete_corrupt_entry(namespace, schema_version, key_hash)
                latency_ms = (time.monotonic() - start) * 1000.0
                return CacheMiss(reason="corrupt", latency_ms=latency_ms)
            if self._payload_sha256(payload) != payload_sha256:
                self._delete_corrupt_entry(namespace, schema_version, key_hash)
                latency_ms = (time.monotonic() - start) * 1000.0
                return CacheMiss(reason="corrupt", latency_ms=latency_ms)
            
            # Update accessed time
            try:
                conn3 = sqlite3.connect(str(self._db_path), timeout=5.0)
                conn3.execute("""
                    UPDATE cache_entries
                    SET accessed_at_epoch = ?
                    WHERE namespace = ? AND schema_version = ? AND key_hash = ?
                """, (time.time(), namespace, schema_version, key_hash))
                conn3.commit()
                conn3.close()
            except Exception:
                pass  # non-critical
            
            latency_ms = (time.monotonic() - start) * 1000.0
            return CacheHit(
                source="l2",
                payload=payload,
                latency_ms=latency_ms,
                expires_at_epoch=expires_at,
            )
        
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            latency_ms = (time.monotonic() - start) * 1000.0
            return CacheMiss(reason="unavailable", latency_ms=latency_ms)
        except Exception:
            latency_ms = (time.monotonic() - start) * 1000.0
            return CacheMiss(reason="not_found", latency_ms=latency_ms)
    
    def put(self, cache_key: str, entry: CacheEntry) -> None:
        """Store entry in L2; fail-open on errors."""
        if not self._enabled:
            return
        
        try:
            parts = cache_key.split(":")
            namespace = parts[2]
            key_hash = parts[3]
            schema_version = 1
            
            payload_json = json.dumps(entry.payload, ensure_ascii=False)
            payload_sha256 = self._payload_sha256(entry.payload)

            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            conn.execute("""
                INSERT OR REPLACE INTO cache_entries
                (namespace, schema_version, key_hash, dependency_fingerprint,
                 payload_json, payload_sha256, created_at_epoch, expires_at_epoch,
                 accessed_at_epoch, byte_size)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                namespace, schema_version, key_hash, entry.dependency_fingerprint,
                payload_json, payload_sha256, entry.created_at_epoch,
                entry.expires_at_epoch, time.time(), entry.byte_size
            ))
            now_epoch = time.time()
            self._cleanup_expired_batch(conn, now_epoch=now_epoch)
            entry_count = conn.execute("SELECT COUNT(*) FROM cache_entries").fetchone()[0]
            if entry_count > self._max_entries:
                self._enforce_hard_capacity(conn, now_epoch=now_epoch)
            conn.commit()
            conn.close()
        except Exception:
            pass  # fail-open
    
    def invalidate(self, cache_key: str) -> bool:
        """Remove key from L2; returns True if existed."""
        if not self._enabled:
            return False
        
        try:
            parts = cache_key.split(":")
            namespace = parts[2]
            key_hash = parts[3]
            schema_version = 1
            
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            cursor = conn.execute("""
                DELETE FROM cache_entries
                WHERE namespace = ? AND schema_version = ? AND key_hash = ?
            """, (namespace, schema_version, key_hash))
            existed = cursor.rowcount > 0
            conn.commit()
            conn.close()
            return existed
        except Exception:
            return False
    
    def cleanup_expired(self, now_epoch: float, limit: int = 100) -> int:
        """Remove expired entries; returns count removed."""
        if not self._enabled:
            return 0
        
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=5.0)
            cursor = conn.execute("""
                DELETE FROM cache_entries
                WHERE expires_at_epoch IS NOT NULL AND expires_at_epoch < ?
                LIMIT ?
            """, (now_epoch, limit))
            removed = cursor.rowcount
            conn.commit()
            conn.close()
            return removed
        except Exception:
            return 0
    
    def is_enabled(self) -> bool:
        """Check if L2 is available."""
        return self._enabled

    def _cleanup_expired_batch(
        self,
        conn: sqlite3.Connection,
        *,
        now_epoch: float,
    ) -> None:
        """Perform bounded opportunistic expiry maintenance on the put path."""
        batch_size = max(1, self._cleanup_batch_size)
        conn.execute(
            """
            DELETE FROM cache_entries
            WHERE rowid IN (
                SELECT rowid
                FROM cache_entries
                WHERE expires_at_epoch IS NOT NULL AND expires_at_epoch <= ?
                ORDER BY expires_at_epoch ASC
                LIMIT ?
            )
            """,
            (now_epoch, batch_size),
        )

    def _enforce_hard_capacity(
        self,
        conn: sqlite3.Connection,
        *,
        now_epoch: float,
    ) -> None:
        """Remove all expired rows, then evict exact excess valid rows by age."""
        conn.execute(
            """
            DELETE FROM cache_entries
            WHERE expires_at_epoch IS NOT NULL AND expires_at_epoch <= ?
            """,
            (now_epoch,),
        )
        entry_count = conn.execute("SELECT COUNT(*) FROM cache_entries").fetchone()[0]
        overflow = max(entry_count - self._max_entries, 0)
        if overflow:
            conn.execute(
                """
                DELETE FROM cache_entries
                WHERE rowid IN (
                    SELECT rowid
                    FROM cache_entries
                    WHERE expires_at_epoch IS NULL OR expires_at_epoch > ?
                    ORDER BY accessed_at_epoch ASC, created_at_epoch ASC, rowid ASC
                    LIMIT ?
                )
                """,
                (now_epoch, overflow),
            )

    def _delete_corrupt_entry(
        self,
        namespace: str,
        schema_version: int,
        key_hash: str,
    ) -> None:
        """Best-effort deletion after integrity failure; cache reads stay fail-open."""
        try:
            with sqlite3.connect(str(self._db_path), timeout=5.0) as conn:
                conn.execute(
                    """
                    DELETE FROM cache_entries
                    WHERE namespace = ? AND schema_version = ? AND key_hash = ?
                    """,
                    (namespace, schema_version, key_hash),
                )
        except Exception:
            pass

    @staticmethod
    def _payload_sha256(payload: object) -> str:
        """Return the canonical JSON payload checksum used for L2 persistence."""
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
