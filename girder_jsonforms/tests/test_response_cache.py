"""Tests for the Redis-backed listing cache.

Model level throughout, no ``server`` fixture -- see CLAUDE.md on not mixing the
two in one module. These exercise :mod:`girder_jsonforms.lib.response_cache`
directly against the real Redis the suite already requires; what matters about
this module is its failure behavior, and that is only interesting against a
client that can actually fail.
"""

import datetime

import pytest
import redis
from bson import ObjectId

from ..lib import response_cache
from ..lib.response_cache import cache_key, cached_call, invalidate_all

UTC = datetime.timezone.utc


@pytest.fixture
def clean_cache():
    """Leave no keys behind in either direction."""
    invalidate_all()
    yield
    invalidate_all()


class Counter:
    """A ``compute`` that records how many times it actually ran."""

    def __init__(self, value):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.value


class TestCacheKey:
    def test_stable_across_dict_order(self):
        # Two filters that differ only in insertion order are the same query
        # and must not each get their own entry.
        a = cache_key(["x", {"meta.igsn": "A", "meta.data_type": "xrd"}])
        b = cache_key(["x", {"meta.data_type": "xrd", "meta.igsn": "A"}])
        assert a == b

    def test_distinguishes_values(self):
        assert cache_key(["x", {"a": 1}]) != cache_key(["x", {"a": 2}])

    def test_distinguishes_namespace(self):
        assert cache_key(["count", {"a": 1}]) != cache_key(["datafiles", {"a": 1}])

    def test_handles_bson(self):
        # ObjectIds and datetimes turn up inside base-parent queries and
        # coerced date filters; plain json.dumps would raise on both.
        key = cache_key(
            [
                "x",
                {
                    "baseParentId": ObjectId("665de536bcc722774ce53754"),
                    "updated": datetime.datetime(2026, 9, 14, tzinfo=UTC),
                },
            ]
        )
        assert key.startswith(response_cache.KEY_PREFIX)

    def test_prefixed(self):
        assert cache_key(["x"]).startswith(response_cache.KEY_PREFIX)


class TestCachedCall:
    def test_caches_within_ttl(self, clean_cache):
        compute = Counter({"xrd": 3})
        first = cached_call(["t.caches", 1], 60, compute)
        second = cached_call(["t.caches", 1], 60, compute)
        assert first == second == {"xrd": 3}
        assert compute.calls == 1

    def test_distinct_keys_do_not_share(self, clean_cache):
        compute = Counter({"xrd": 3})
        cached_call(["t.distinct", 1], 60, compute)
        cached_call(["t.distinct", 2], 60, compute)
        assert compute.calls == 2

    def test_zero_ttl_disables(self, clean_cache):
        compute = Counter({"xrd": 3})
        cached_call(["t.zero", 1], 0, compute)
        cached_call(["t.zero", 1], 0, compute)
        assert compute.calls == 2

    def test_negative_ttl_disables(self, clean_cache):
        compute = Counter({"xrd": 3})
        cached_call(["t.negative", 1], -1, compute)
        cached_call(["t.negative", 1], -1, compute)
        assert compute.calls == 2

    def test_zero_ttl_does_not_write(self, clean_cache):
        cached_call(["t.nowrite", 1], 0, Counter({"xrd": 3}))
        # A disabled cache that still populates would serve stale data the
        # moment someone turned it back on.
        compute = Counter({"xrd": 99})
        assert cached_call(["t.nowrite", 1], 60, compute) == {"xrd": 99}
        assert compute.calls == 1

    def test_round_trips_bson(self, clean_cache):
        # Naive datetimes because that is what comes back from Mongo: neither
        # pymongo nor girder's getDbConnection sets tz_aware, so a cached
        # document has to match an uncached one, which is naive UTC.
        value = {
            "items": [
                {
                    "_id": ObjectId("665de536bcc722774ce53754"),
                    "created": datetime.datetime(2026, 9, 14, 12, 30),
                    "name": "sample.xrdml",
                }
            ],
            "total": 1,
        }
        cached_call(["t.bson", 1], 60, Counter(value))
        cached = cached_call(["t.bson", 1], 60, Counter(None))
        assert cached["items"][0]["_id"] == value["items"][0]["_id"]
        assert cached["items"][0]["created"] == value["items"][0]["created"]
        assert cached["items"][0]["name"] == "sample.xrdml"
        assert cached["total"] == 1

    def test_aware_datetimes_come_back_naive(self, clean_cache):
        """Documenting a round-trip limit rather than asserting it is desirable.

        ``json_util`` deserializes to naive UTC. Harmless for these endpoints,
        whose datetimes originate in Mongo and are therefore already naive --
        but anything that starts caching tz-aware values will find they do not
        compare equal on the way back out.
        """
        aware = datetime.datetime(2026, 9, 14, 12, 30, tzinfo=UTC)
        cached_call(["t.aware", 1], 60, Counter({"d": aware}))
        cached = cached_call(["t.aware", 1], 60, Counter(None))
        assert cached["d"] == aware.replace(tzinfo=None)
        assert cached["d"].tzinfo is None

    def test_caches_falsy_values(self, clean_cache):
        # An empty page is a perfectly good answer; `if not hit` instead of
        # `if hit is None` would recompute it every time.
        compute = Counter({"items": [], "total": 0})
        cached_call(["t.falsy", 1], 60, compute)
        cached_call(["t.falsy", 1], 60, compute)
        assert compute.calls == 1

    def test_exception_propagates_and_is_not_cached(self, clean_cache):
        def boom():
            raise ValueError("no")

        with pytest.raises(ValueError):
            cached_call(["t.boom", 1], 60, boom)
        # The failure must not have poisoned the key.
        compute = Counter({"ok": True})
        assert cached_call(["t.boom", 1], 60, compute) == {"ok": True}
        assert compute.calls == 1


class TestDegradation:
    """A cache problem must never become a request failure."""

    def test_redis_unreachable_on_read(self, monkeypatch, clean_cache):
        def unreachable():
            raise redis.ConnectionError("down")

        monkeypatch.setattr(response_cache, "_redis_client", unreachable)
        compute = Counter({"xrd": 3})
        assert cached_call(["t.down", 1], 60, compute) == {"xrd": 3}
        assert compute.calls == 1

    def test_redis_unreachable_on_write(self, monkeypatch, clean_cache):
        class FailingWrite:
            """Real client in every respect but ``set``.

            Delegating the rest matters: the single-flight path still needs a
            usable ``get``, and ``distributed_lock`` still needs ``lock``.
            """

            def __init__(self, real):
                self._real = real

            def __getattr__(self, name):
                return getattr(self._real, name)

            def set(self, *args, **kwargs):
                raise redis.ConnectionError("down")

        real = response_cache._redis_client()
        monkeypatch.setattr(response_cache, "_redis_client", lambda: FailingWrite(real))
        compute = Counter({"xrd": 3})
        assert cached_call(["t.wfail", 1], 60, compute) == {"xrd": 3}
        assert compute.calls == 1

    def test_unserializable_value_still_returned(self, clean_cache):
        sentinel = object()
        compute = Counter({"bad": sentinel})
        # json_util cannot represent this; the request should still succeed and
        # simply never be cached.
        assert cached_call(["t.unser", 1], 60, compute)["bad"] is sentinel
        assert cached_call(["t.unser", 1], 60, compute)["bad"] is sentinel
        assert compute.calls == 2

    def test_poisoned_entry_is_replaced(self, clean_cache):
        key = cache_key(["t.poison", 1])
        response_cache._redis_client().set(key, b"{not json", ex=60)
        compute = Counter({"xrd": 3})
        assert cached_call(["t.poison", 1], 60, compute) == {"xrd": 3}
        assert compute.calls == 1
        # And the bad entry is gone, not re-read on the next request.
        assert cached_call(["t.poison", 1], 60, compute) == {"xrd": 3}
        assert compute.calls == 1


class TestInvalidateAll:
    def test_drops_entries(self, clean_cache):
        compute = Counter({"xrd": 3})
        cached_call(["t.inv", 1], 60, compute)
        assert invalidate_all() >= 1
        cached_call(["t.inv", 1], 60, compute)
        assert compute.calls == 2

    def test_leaves_foreign_keys_alone(self, clean_cache):
        client = response_cache._redis_client()
        client.set("someone-elses-key", b"1", ex=60)
        try:
            cached_call(["t.scoped", 1], 60, Counter({"xrd": 3}))
            invalidate_all()
            assert client.get("someone-elses-key") == b"1"
        finally:
            client.delete("someone-elses-key")

    def test_survives_unreachable_redis(self, monkeypatch):
        def unreachable():
            raise redis.ConnectionError("down")

        monkeypatch.setattr(response_cache, "_redis_client", unreachable)
        assert invalidate_all() == 0
