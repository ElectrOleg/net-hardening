"""Redis-based distributed lock for HCS task deduplication.

Provides a simple, reliable locking mechanism using Redis SET NX EX
(atomic set-if-not-exists with TTL). Used to prevent:
- Duplicate scans from concurrent API requests
- Duplicate Beat executions in multi-node deployments
- Race conditions in scan orchestration
"""

import logging
import os
import time
from contextlib import contextmanager

import redis

logger = logging.getLogger(__name__)


class LockNotAcquired(Exception):
    """Raised when a distributed lock cannot be acquired."""

    pass


class DistributedLock:
    """Redis-based distributed lock with auto-expiry and safe release.

    Uses the SET NX EX pattern for atomic acquire, and a CAS-style
    check-and-delete for safe release (only the holder can release).

    Usage:
        lock = DistributedLock()
        try:
            with lock.acquire("scan:abc123", ttl=3600):
                # ... do work
        except LockNotAcquired:
            # another process holds the lock
            pass
    """

    # Lua script for atomic check-and-delete (CAS release)
    # Only deletes the key if the stored value matches our token
    _RELEASE_SCRIPT = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    else
        return 0
    end
    """

    def __init__(self, redis_url: str = None):
        if redis_url is None:
            from app.config import settings

            redis_url = settings.REDIS_URL
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._release_script = self._redis.register_script(self._RELEASE_SCRIPT)

    def try_acquire(self, key: str, ttl: int = 600) -> str | None:
        """Try to acquire a lock. Returns token on success, None on failure.

        Args:
            key: Lock name (will be prefixed with 'hcs:lock:')
            ttl: Lock expiry in seconds (guard against dead workers)

        Returns:
            Token string if acquired, None if lock is held
        """
        lock_key = f"hcs:lock:{key}"
        token = f"{time.time():.6f}:{os.getpid()}"

        acquired = self._redis.set(lock_key, token, nx=True, ex=ttl)
        if acquired:
            logger.debug(f"Lock acquired: {lock_key} (ttl={ttl}s)")
            return token

        # Log who holds the lock for debugging
        holder = self._redis.get(lock_key)
        remaining = self._redis.ttl(lock_key)
        logger.debug(f"Lock busy: {lock_key} (holder={holder}, ttl_remaining={remaining}s)")
        return None

    def release(self, key: str, token: str) -> bool:
        """Release a lock. Only succeeds if we still hold it (CAS).

        Args:
            key: Lock name (same as used in try_acquire)
            token: Token returned by try_acquire

        Returns:
            True if released, False if lock was already expired/stolen
        """
        lock_key = f"hcs:lock:{key}"
        result = self._release_script(keys=[lock_key], args=[token])
        if result:
            logger.debug(f"Lock released: {lock_key}")
        else:
            logger.warning(f"Lock release failed (expired or stolen): {lock_key}")
        return bool(result)

    def is_locked(self, key: str) -> bool:
        """Check if a lock is currently held (non-blocking, informational)."""
        return self._redis.exists(f"hcs:lock:{key}") > 0

    def force_release(self, key: str) -> bool:
        """Force-release a lock regardless of holder. Admin use only."""
        lock_key = f"hcs:lock:{key}"
        result = self._redis.delete(lock_key)
        if result:
            logger.warning(f"Lock force-released: {lock_key}")
        return bool(result)

    @contextmanager
    def acquire(self, key: str, ttl: int = 600):
        """Context manager for acquiring and auto-releasing a lock.

        Args:
            key: Lock name
            ttl: Lock expiry in seconds

        Raises:
            LockNotAcquired: if the lock is already held

        Example:
            with lock.acquire("scan:abc123", ttl=3600):
                run_scan()
        """
        token = self.try_acquire(key, ttl)
        if token is None:
            raise LockNotAcquired(f"Lock 'hcs:lock:{key}' is held by another process")

        try:
            yield token
        finally:
            self.release(key, token)


# Module-level singleton (lazy-init)
_lock_instance: DistributedLock | None = None


def get_lock() -> DistributedLock:
    """Get or create the singleton DistributedLock instance."""
    global _lock_instance
    if _lock_instance is None:
        _lock_instance = DistributedLock()
    return _lock_instance
