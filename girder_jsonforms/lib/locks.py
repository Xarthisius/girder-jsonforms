import contextlib
import functools
import logging
import os

import redis

logger = logging.getLogger(__name__)


@functools.lru_cache
def _redis_client() -> redis.Redis:
    url = os.environ.get("GIRDER_NOTIFICATION_REDIS_URL", "redis://localhost:6379")
    return redis.Redis.from_url(url, socket_timeout=None)


@contextlib.contextmanager
def distributed_lock(name: str, timeout: float = 30.0, blocking_timeout: float = 30.0):
    """Serialize a critical section across processes using a Redis lock.

    ``timeout`` bounds how long the lock is held before Redis auto-releases it
    (so a crashed holder can't wedge the others); ``blocking_timeout`` bounds
    how long we wait to acquire it. If Redis is unreachable we log and proceed
    without the lock rather than blocking startup.
    """
    lock = None
    try:
        lock = _redis_client().lock(
            name, timeout=timeout, blocking_timeout=blocking_timeout
        )
        acquired = lock.acquire()
        if not acquired:
            logger.warning("Timed out acquiring distributed lock %r; proceeding", name)
            lock = None
    except redis.RedisError:
        logger.exception("Redis unavailable for lock %r; proceeding without it", name)
        lock = None

    try:
        yield
    finally:
        if lock is not None:
            with contextlib.suppress(redis.RedisError, redis.lock.LockError):
                lock.release()
