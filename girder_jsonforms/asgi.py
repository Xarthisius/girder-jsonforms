from girder.asgi import _WSGIBridge, lifespan
from girder.notification import UserNotificationsSocket
from girder.wsgi import app as wsgi_app
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute

from .lib.announcement import announcement_socket_endpoint


def create_app():
    routes = [
        WebSocketRoute("/notifications/me", UserNotificationsSocket),
        WebSocketRoute("/notifications/public", announcement_socket_endpoint),
    ]
    application = Starlette(lifespan=lifespan, routes=routes)
    application.mount("/", _WSGIBridge(wsgi_app))
    return application


app = create_app()
