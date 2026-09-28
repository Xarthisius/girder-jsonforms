"""Per-request timing for the ASGI app.

Why this rather than gunicorn's access log: the workers are
``uvicorn.workers.UvicornWorker``, which rewires the ``uvicorn.access`` logger
onto gunicorn's handlers but keeps uvicorn's own formatter -- so
``--access-logformat`` is ignored and neither ``%(D)s`` (duration) nor
``%(p)s`` (worker pid) ever appears. CherryPy's access log, which does come
through, carries no duration either. Duration and worker identity are exactly
the two things you want when the report is "the site is intermittently slow",
and nothing upstream can supply the second: the workers are forked from one
arbiter behind a single port, so Traefik and the load balancer see one server.

The thread numbers are here because of how girder's ``_WSGIBridge`` works. It
runs each WSGI request on its own ``threading.Thread`` -- unbounded, so no
ceiling there -- but pumps the response back through
``loop.run_in_executor(None, chunk_queue.get)``, the loop's *default* executor.
That one is capped and shared by every request on the worker, and one of its
threads stays blocked on the queue for the whole life of a request. So that
cap, not anything in girder itself, is the real per-worker concurrency ceiling,
and ``q`` is how you see it being hit.

:func:`install_executor` takes ownership of that executor at startup. Not for
the sake of changing it -- the default size is exactly what CPython would have
chosen -- but because there is otherwise no way to read it: UvicornWorker runs
``loop="auto"`` and therefore uvloop whenever it is installed, and uvloop keeps
``_default_executor`` as a C-level attribute that ``getattr`` cannot see. An
executor we created is one we can measure, and one ``POOL_ENV_VAR`` can resize
once the log says it needs resizing.

Read the fields as:

``pool=<alive>/<max>``
    Threads the default executor has created, against its cap. ``alive`` only
    ever grows -- the pool does not shrink -- so it is a high-water mark, not
    an occupancy reading. Do not infer "we are saturated now" from it.
``q=<n>``
    Work queued on that executor. *This* is the live pressure signal: a
    non-zero ``q`` means requests are waiting for a thread before they can send
    a byte, and it is the thing to correlate against a slow episode.
``inflight=<n>``
    Requests in flight on this worker, this one included -- so ``inflight=1``
    means it was alone, and a slow request can be read against whatever else
    was running beside it.

Query strings are deliberately not logged. ``/notifications/me?token=...``
carries a live session token, and anyone who can read ``docker logs`` can read
this.
"""

import asyncio
import concurrent.futures
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

#: Log requests at least this slow when the environment says nothing.
#: A second is far above the few milliseconds a healthy request takes here, so
#: the default is quiet on a well behaved instance and speaks up on a bad one.
DEFAULT_THRESHOLD_MS = 1000.0

#: Threshold in milliseconds. ``0`` logs every request -- which is what you
#: want for a worker-by-worker latency histogram, and too much for normal
#: running. A negative value leaves the middleware out of the stack entirely.
ENV_VAR = "GIRDER_JSONFORMS_TIMING_MS"

#: Requests currently inside the middleware on this worker. Mutated only from
#: coroutine code, which on a uvicorn worker means only ever from the event
#: loop thread, so it needs no lock. The WSGI handler runs on a thread of its
#: own but never touches this.
_inflight = 0


def threshold_from_env(environ=None):
    """Resolve the logging threshold in milliseconds.

    Environment rather than a Girder setting on purpose: this runs in the ASGI
    layer, outside any request context and potentially before plugins have
    loaded, and a diagnostic has no business opening a database connection on
    the hot path to find out whether it should log.
    """
    raw = (os.environ if environ is None else environ).get(ENV_VAR)
    if raw is None or not raw.strip():
        return DEFAULT_THRESHOLD_MS
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "Ignoring unparseable %s=%r; using %sms", ENV_VAR, raw, DEFAULT_THRESHOLD_MS
        )
        return DEFAULT_THRESHOLD_MS


#: Threads for the executor girder's WSGI bridge pumps responses through.
#: Unset keeps what CPython would have picked, so owning the executor is
#: observability rather than a behavior change. Raise it only on evidence --
#: a non-zero ``q`` in the log.
POOL_ENV_VAR = "GIRDER_JSONFORMS_POOL_SIZE"

#: The executor installed by :func:`install_executor`, if it ran.
_executor = None


def default_pool_size(environ=None):
    """Resolve the response executor's thread count."""
    fallback = min(32, (os.cpu_count() or 1) + 4)
    raw = (os.environ if environ is None else environ).get(POOL_ENV_VAR)
    if raw is None or not raw.strip():
        return fallback
    try:
        size = int(raw)
    except ValueError:
        logger.warning(
            "Ignoring unparseable %s=%r; using %d", POOL_ENV_VAR, raw, fallback
        )
        return fallback
    if size < 1:
        logger.warning(
            "Ignoring %s=%r; a pool needs at least one thread", POOL_ENV_VAR, raw
        )
        return fallback
    return size


def install_executor(environ=None):
    """Take ownership of the running loop's default executor.

    Call once per worker from lifespan startup, before any request is served --
    the executor has to be in place the first time the WSGI bridge reaches for
    it, because ``set_default_executor`` does not migrate work already queued
    on the one it replaces.
    """
    global _executor
    size = default_pool_size(environ)
    _executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=size, thread_name_prefix="girder-wsgi"
    )
    asyncio.get_running_loop().set_default_executor(_executor)
    logger.info("pid=%d WSGI response executor: %d threads", os.getpid(), size)
    return _executor


def shutdown_executor():
    """Drop the executor :func:`install_executor` installed.

    ``wait=False`` because this runs on the shutdown path: a thread still
    blocked on a response queue must not be able to wedge the worker's exit.
    """
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False)
        _executor = None


def _current_executor():
    """The executor the WSGI bridge will use, if it can be named.

    Ours when :func:`install_executor` has run, which is the normal case. The
    loop's own otherwise -- readable on the stdlib loop, invisible on uvloop,
    which is why we install our own at all.
    """
    if _executor is not None:
        return _executor
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    return getattr(loop, "_default_executor", None)


def _pool_stats():
    """``(alive, max, queued)`` for the response executor, or ``None``.

    Reads private attributes because ``ThreadPoolExecutor`` exposes no public
    introspection at all. Every one is optional: a rename in a future CPython
    should cost the log line a field, never the request.
    """
    executor = _current_executor()
    if executor is None:
        return None
    try:
        return (
            len(executor._threads),
            executor._max_workers,
            executor._work_queue.qsize(),
        )
    except AttributeError:
        return None


class TimingMiddleware:
    """Log how long each request took, and on which worker.

    A pure ASGI middleware rather than a Starlette ``BaseHTTPMiddleware``
    subclass: the latter buffers the response through an anyio stream, which
    would both add a thread hop to every request and defeat the streaming the
    WSGI bridge goes to some trouble to preserve.

    Websockets are timed too, and the duration is the lifetime of the
    connection -- which is the number you want when the question is why a
    notification socket dropped. Their status field reports the close code if
    one was seen, otherwise ``101`` once accepted.
    """

    def __init__(self, app, threshold_ms=DEFAULT_THRESHOLD_MS):
        self.app = app
        self.threshold_ms = threshold_ms

    async def __call__(self, scope, receive, send):
        kind = scope.get("type")
        if kind not in ("http", "websocket"):
            # "lifespan" and anything else added later: pass straight through.
            await self.app(scope, receive, send)
            return

        global _inflight
        seen = {"status": None}

        async def send_wrapper(message):
            message_type = message.get("type")
            if message_type == "http.response.start":
                seen["status"] = message.get("status")
            elif message_type == "websocket.accept":
                seen["status"] = 101
            elif message_type == "websocket.close":
                seen["status"] = message.get("code", 1000)
            await send(message)

        _inflight += 1
        started = time.perf_counter()
        failure = None
        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException as exc:
            # Including CancelledError: a client that hangs up mid-request is
            # worth seeing, and re-raising leaves the behavior unchanged.
            failure = type(exc).__name__
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            # Read before decrementing so the count includes this request,
            # then decrement before logging so a slow logger cannot hold the
            # gauge up.
            concurrent = _inflight
            _inflight -= 1
            self._log(scope, kind, seen["status"], failure, elapsed_ms, concurrent)

    def _log(self, scope, kind, status, failure, elapsed_ms, concurrent):
        if self.threshold_ms > 0 and elapsed_ms < self.threshold_ms:
            return
        try:
            pool = _pool_stats()
            logger.info(
                "pid=%d %.1fms %s %s %s inflight=%d threads=%d pool=%s q=%s",
                os.getpid(),
                elapsed_ms,
                failure or status or "-",
                scope.get("method") or ("WS" if kind == "websocket" else "-"),
                scope.get("path") or "-",
                concurrent,
                threading.active_count(),
                "{}/{}".format(pool[0], pool[1]) if pool else "-",
                pool[2] if pool else "-",
            )
        except Exception:
            # This runs in a finally, sometimes while an exception is already
            # propagating. A broken diagnostic must not replace or mask the
            # real failure, and there is nowhere useful left to report to.
            pass
