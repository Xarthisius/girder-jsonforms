from contextlib import asynccontextmanager

from girder.asgi import _WSGIBridge, lifespan
from girder.notification import UserNotificationsSocket
from girder.wsgi import app as wsgi_app
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import WebSocketRoute

from .lib.announcement import announcement_socket_endpoint
from .lib.timing import (
    TimingMiddleware,
    install_executor,
    shutdown_executor,
    threshold_from_env,
)


@asynccontextmanager
async def _lifespan(app):
    """Girder's lifespan, with the WSGI response executor installed around it.

    First, and on the running loop: the bridge reaches for the default executor
    on its very first response, and replacing one that already has work queued
    would leave that work behind.
    """
    install_executor()
    try:
        async with lifespan(app):
            yield
    finally:
        shutdown_executor()


def create_app():
    routes = [
        WebSocketRoute("/notifications/me", UserNotificationsSocket),
        WebSocketRoute("/notifications/public", announcement_socket_endpoint),
    ]
    # Outermost, so the span it measures covers everything inside -- the WSGI
    # mount included. A negative threshold leaves it out of the stack entirely
    # rather than installing a middleware that only ever declines to log.
    threshold = threshold_from_env()
    middleware = (
        [Middleware(TimingMiddleware, threshold_ms=threshold)] if threshold >= 0 else []
    )
    application = Starlette(lifespan=_lifespan, routes=routes, middleware=middleware)
    application.mount("/", _WSGIBridge(wsgi_app))
    return application


app = create_app()
