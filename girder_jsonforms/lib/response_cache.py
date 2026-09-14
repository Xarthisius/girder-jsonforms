"""Short-lived caching for the read-heavy AIMDL listing endpoints.

``Item`` carries no ACL of its own, so ``Item().findWithPermissions`` resolves
access by ``$lookup``-ing the owning folder of every matching item (see
``girder/utility/acl_mixin.py``) -- tens of thousands of joins to return a page
of fifteen. Girder's ``filtermodel`` then calls ``count()`` on the cursor it
gets back to fill in ``Girder-Total-Count``, so a single request runs that
pipeline twice.

None of that is per-request work in any useful sense. The dashboard polls
``/aimdl/count`` and ``/aimdl/datafiles`` on timers from every open browser
tab, so the same pipeline runs several times a minute around the clock whether
or not anything changed -- and it shares a database with everyone browsing the
data portal.

Cached in Redis rather than in-process because Girder runs several gunicorn
workers: a per-process cache would miss once per worker for every distinct key
and hold that many copies. Redis is already a hard dependency here -- see
``locks.py``, whose client and lock this reuses.

Every failure mode degrades to "compute it". A cache that is unreachable, slow,
or holding something unreadable must never turn a working request into a failed
one, so :func:`cached_call` swallows Redis and serialization errors and falls
through to ``compute``.
"""

import hashlib
import logging

import redis
from bson import json_util

from .locks import _redis_client, distributed_lock

logger = logging.getLogger(__name__)

#: Prefix on every key this module writes, so an operator sharing the Redis
#: instance with the notification stream can see -- and flush -- ours alone.
KEY_PREFIX = "jsonforms:cache:"

#: How long a worker waits for whichever one is already computing the same key.
#: Deliberately close to how long the uncached aggregation takes: a stampede
#: should cost a short wait rather than a pile-up, and a waiter that times out
#: just computes it itself, which is exactly the old behavior.
SINGLEFLIGHT_WAIT = 5.0


def cache_key(parts):
    """Hash ``parts`` into a stable Redis key.

    Hashed rather than concatenated because the parts include user-supplied
    filter objects of unbounded size. ``json_util`` so ObjectIds and datetimes
    inside those filters serialize at all; ``sort_keys`` so two equivalent
    filter dicts that differ only in insertion order land on the same key.
    """
    raw = json_util.dumps(parts, sort_keys=True)
    return KEY_PREFIX + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load(raw, key):
    """Deserialize a hit, or return ``None`` if it is unusable."""
    try:
        return json_util.loads(raw)
    except Exception:
        # Poisoned, truncated, or written by an incompatible older version.
        # Fall through to recompute and overwrite rather than failing.
        logger.exception("Discarding unreadable cache entry at %s", key)
        return None


def cached_call(parts, ttl, compute):
    """Return ``compute()``, memoized in Redis under ``parts`` for ``ttl`` seconds.

    A ``ttl`` of zero or less disables caching and calls ``compute`` directly;
    that is the documented way to turn this off at runtime, so callers do not
    need a separate flag of their own.

    The value must survive a ``json_util`` round trip. That covers what these
    endpoints return -- dicts of counts, lists of item documents -- but not
    arbitrary objects, and emphatically not a cursor: hand one over and it
    serializes to something useless. Failures to serialize are logged and the
    value returned uncached.

    Note that ``compute`` runs while the single-flight lock is held, so an
    exception raised inside it propagates to the caller unchanged and releases
    the lock on the way out.
    """
    if ttl <= 0:
        return compute()

    key = cache_key(parts)
    try:
        client = _redis_client()
        hit = client.get(key)
    except redis.RedisError:
        logger.exception("Redis unavailable reading %s; computing", key)
        return compute()

    if hit is not None:
        value = _load(hit, key)
        if value is not None:
            return value

    # Only one worker should pay for a miss. The lock is an optimization rather
    # than correctness -- distributed_lock says so and proceeds when Redis
    # cannot grant it, and the worst case is the stampede we had before.
    with distributed_lock(
        key + ":lock", timeout=SINGLEFLIGHT_WAIT, blocking_timeout=SINGLEFLIGHT_WAIT
    ):
        try:
            hit = client.get(key)
        except redis.RedisError:
            hit = None
        if hit is not None:
            value = _load(hit, key)
            if value is not None:
                return value

        value = compute()
        try:
            client.set(key, json_util.dumps(value), ex=ttl)
        except redis.RedisError:
            logger.exception("Redis unavailable writing %s", key)
        except (TypeError, ValueError):
            logger.exception("Value for %s is not serializable; not cached", key)
        return value


def invalidate_all():
    """Drop every entry this module owns.

    For tests, and for an operator who has changed something the TTL does not
    know about (a folder ACL, say) and does not want to wait it out. Scans
    rather than ``KEYS`` so it stays civil on a shared Redis, and reports how
    many it removed. Returns ``0`` if Redis is unreachable rather than raising:
    dropping a cache is never worth failing over.
    """
    removed = 0
    try:
        client = _redis_client()
        for key in client.scan_iter(match=KEY_PREFIX + "*", count=500):
            removed += client.delete(key)
    except redis.RedisError:
        logger.exception("Redis unavailable; cache not invalidated")
        return 0
    return removed
