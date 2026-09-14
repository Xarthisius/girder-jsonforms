"""Tests for the ASGI timing middleware.

Model level, no ``server`` fixture -- see CLAUDE.md on not mixing the two in one
module. The middleware is plain ASGI, so it is driven here with hand-built
scopes rather than a real server; that keeps the tests honest about the
protocol contract (what a ``send`` sees, what an exception does) instead of
about Starlette.
"""

import asyncio
import logging
import os

import pytest

from ..lib import timing
from ..lib.timing import (
    DEFAULT_THRESHOLD_MS,
    ENV_VAR,
    POOL_ENV_VAR,
    TimingMiddleware,
    default_pool_size,
    install_executor,
    shutdown_executor,
    threshold_from_env,
)

LOGGER_NAME = "girder_jsonforms.lib.timing"


def run(coro):
    return asyncio.run(coro)


async def _noop_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def http_scope(path="/api/v1/aimdl/count", method="GET", query=b""):
    return {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": query,
        "headers": [],
    }


def responder(status=200, delay=0.0):
    """An inner app that answers after ``delay`` seconds."""

    async def app(scope, receive, send):
        if delay:
            await asyncio.sleep(delay)
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b"{}", "more_body": False})

    return app


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    return caplog


class TestThresholdFromEnv:
    def test_unset_is_default(self):
        assert threshold_from_env({}) == DEFAULT_THRESHOLD_MS

    def test_blank_is_default(self):
        assert threshold_from_env({ENV_VAR: "   "}) == DEFAULT_THRESHOLD_MS

    def test_zero_means_log_everything(self):
        assert threshold_from_env({ENV_VAR: "0"}) == 0

    def test_explicit_value(self):
        assert threshold_from_env({ENV_VAR: "250"}) == 250

    def test_negative_disables(self):
        assert threshold_from_env({ENV_VAR: "-1"}) < 0

    def test_garbage_falls_back(self):
        # A typo in a deployment env var should not silently turn logging off.
        assert threshold_from_env({ENV_VAR: "soon"}) == DEFAULT_THRESHOLD_MS

    def test_reads_os_environ_by_default(self, monkeypatch):
        monkeypatch.setenv(ENV_VAR, "123")
        assert threshold_from_env() == 123


class TestHttp:
    def test_logs_when_over_threshold(self, logs):
        app = TimingMiddleware(responder(200), threshold_ms=0)
        run(app(http_scope(), _noop_receive, _collect()))
        assert len(logs.records) == 1
        message = logs.records[0].getMessage()
        assert "pid=%d" % os.getpid() in message
        assert " 200 " in message
        assert "GET" in message
        assert "/api/v1/aimdl/count" in message

    def test_silent_when_under_threshold(self, logs):
        app = TimingMiddleware(responder(200), threshold_ms=10_000)
        run(app(http_scope(), _noop_receive, _collect()))
        assert logs.records == []

    def test_slow_request_crosses_threshold(self, logs):
        app = TimingMiddleware(responder(200, delay=0.05), threshold_ms=10)
        run(app(http_scope(), _noop_receive, _collect()))
        assert len(logs.records) == 1

    def test_reports_the_status_it_saw(self, logs):
        app = TimingMiddleware(responder(404), threshold_ms=0)
        run(app(http_scope(), _noop_receive, _collect()))
        assert " 404 " in logs.records[0].getMessage()

    def test_query_string_is_not_logged(self, logs):
        # /notifications/me?token=... carries a live session token.
        scope = http_scope(path="/notifications/me", query=b"token=sup3rs3cr3t")
        app = TimingMiddleware(responder(200), threshold_ms=0)
        run(app(scope, _noop_receive, _collect()))
        message = logs.records[0].getMessage()
        assert "/notifications/me" in message
        assert "sup3rs3cr3t" not in message
        assert "token" not in message

    def test_response_is_passed_through_unchanged(self):
        sent = []
        app = TimingMiddleware(responder(201), threshold_ms=0)
        run(app(http_scope(), _noop_receive, _collect(sent)))
        assert [m["type"] for m in sent] == [
            "http.response.start",
            "http.response.body",
        ]
        assert sent[0]["status"] == 201
        assert sent[1]["body"] == b"{}"

    def test_includes_pool_and_inflight_fields(self, logs):
        app = TimingMiddleware(responder(200), threshold_ms=0)
        run(app(http_scope(), _noop_receive, _collect()))
        message = logs.records[0].getMessage()
        for field in ("inflight=", "threads=", "pool=", "q="):
            assert field in message


class TestFailures:
    def test_exception_propagates_and_is_logged(self, logs):
        async def broken(scope, receive, send):
            raise RuntimeError("boom")

        app = TimingMiddleware(broken, threshold_ms=0)
        with pytest.raises(RuntimeError):
            run(app(http_scope(), _noop_receive, _collect()))
        assert "RuntimeError" in logs.records[0].getMessage()

    def test_inflight_returns_to_zero_after_failure(self, logs):
        async def broken(scope, receive, send):
            raise RuntimeError("boom")

        before = timing._inflight
        app = TimingMiddleware(broken, threshold_ms=0)
        with pytest.raises(RuntimeError):
            run(app(http_scope(), _noop_receive, _collect()))
        assert timing._inflight == before

    def test_broken_logger_does_not_break_the_request(self, monkeypatch):
        # The log call happens in a finally; if it can throw, it can replace a
        # real response with an exception.
        def explode(*args, **kwargs):
            raise ValueError("logging is down")

        monkeypatch.setattr(timing.logger, "info", explode)
        sent = []
        app = TimingMiddleware(responder(200), threshold_ms=0)
        run(app(http_scope(), _noop_receive, _collect(sent)))
        assert sent[0]["status"] == 200


class TestWebsocket:
    def test_logs_close_code_and_lifetime(self, logs):
        async def socket(scope, receive, send):
            await send({"type": "websocket.accept"})
            await asyncio.sleep(0.02)
            await send({"type": "websocket.close", "code": 1001})

        scope = {"type": "websocket", "path": "/notifications/me", "headers": []}
        app = TimingMiddleware(socket, threshold_ms=0)
        run(app(scope, _noop_receive, _collect()))
        message = logs.records[0].getMessage()
        assert "1001" in message
        assert "WS" in message
        assert "/notifications/me" in message

    def test_accepted_but_never_closed_reports_101(self, logs):
        async def socket(scope, receive, send):
            await send({"type": "websocket.accept"})

        scope = {"type": "websocket", "path": "/notifications/me", "headers": []}
        app = TimingMiddleware(socket, threshold_ms=0)
        run(app(scope, _noop_receive, _collect()))
        assert " 101 " in logs.records[0].getMessage()


class TestPassthrough:
    def test_lifespan_is_not_timed(self, logs):
        seen = []

        async def app(scope, receive, send):
            seen.append(scope["type"])

        wrapped = TimingMiddleware(app, threshold_ms=0)
        run(wrapped({"type": "lifespan"}, _noop_receive, _collect()))
        assert seen == ["lifespan"]
        assert logs.records == []


def _collect(into=None):
    """A ``send`` that records what it was given."""
    into = [] if into is None else into

    async def send(message):
        into.append(message)

    return send


class TestInflight:
    def test_lone_request_counts_itself(self, logs):
        app = TimingMiddleware(responder(200), threshold_ms=0)
        run(app(http_scope(), _noop_receive, _collect()))
        assert "inflight=1" in logs.records[0].getMessage()

    def test_counts_concurrent_requests(self, logs):
        app = TimingMiddleware(responder(200, delay=0.05), threshold_ms=0)

        async def three_at_once():
            await asyncio.gather(
                *(app(http_scope(), _noop_receive, _collect()) for _ in range(3))
            )

        run(three_at_once())
        counts = sorted(
            int(r.getMessage().split("inflight=")[1].split()[0]) for r in logs.records
        )
        # They overlap, so the last to finish must have seen all three.
        assert counts == [1, 2, 3]

    def test_returns_to_zero(self, logs):
        before = timing._inflight
        app = TimingMiddleware(responder(200), threshold_ms=0)
        run(app(http_scope(), _noop_receive, _collect()))
        assert timing._inflight == before


class TestPoolSize:
    def test_unset_matches_cpython_default(self):
        assert default_pool_size({}) == min(32, (os.cpu_count() or 1) + 4)

    def test_explicit_value(self):
        assert default_pool_size({POOL_ENV_VAR: "8"}) == 8

    def test_zero_falls_back(self):
        assert default_pool_size({POOL_ENV_VAR: "0"}) == min(
            32, (os.cpu_count() or 1) + 4
        )

    def test_garbage_falls_back(self):
        assert default_pool_size({POOL_ENV_VAR: "lots"}) == min(
            32, (os.cpu_count() or 1) + 4
        )


class TestExecutor:
    """The regression that made pool=- q=- in the first place.

    UvicornWorker runs loop="auto", so uvloop whenever installed, and uvloop
    keeps _default_executor as a C-level attribute getattr cannot reach. These
    run on both loops because only one of them ever showed the bug.
    """

    @staticmethod
    async def _stats_after_install():
        install_executor({POOL_ENV_VAR: "6"})
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: 1)
            return timing._pool_stats()
        finally:
            shutdown_executor()

    def test_reports_on_asyncio_loop(self):
        alive, maximum, queued = asyncio.run(self._stats_after_install())
        assert maximum == 6
        assert alive >= 1
        assert queued == 0

    def test_reports_on_uvloop(self):
        uvloop = pytest.importorskip("uvloop")
        loop = uvloop.new_event_loop()
        try:
            stats = loop.run_until_complete(self._stats_after_install())
            alive, maximum, queued = stats
        finally:
            loop.close()
        assert maximum == 6
        assert alive >= 1
        assert queued == 0

    def test_middleware_logs_real_numbers_under_uvloop(self, logs):
        uvloop = pytest.importorskip("uvloop")

        async def scenario():
            install_executor({POOL_ENV_VAR: "6"})
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: 1)
                app = TimingMiddleware(responder(200), threshold_ms=0)
                await app(http_scope(), _noop_receive, _collect())
            finally:
                shutdown_executor()

        loop = uvloop.new_event_loop()
        try:
            loop.run_until_complete(scenario())
        finally:
            loop.close()
        message = logs.records[-1].getMessage()
        assert "pool=-" not in message
        assert "q=-" not in message
        assert "/6" in message

    def test_shutdown_clears_the_reference(self):
        async def scenario():
            install_executor({POOL_ENV_VAR: "2"})
            assert timing._executor is not None
            shutdown_executor()
            assert timing._executor is None

        asyncio.run(scenario())
