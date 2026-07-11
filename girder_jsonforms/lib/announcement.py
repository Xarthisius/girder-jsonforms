import asyncio
import datetime
import functools
import json
import logging
import os

import redis
import redis.asyncio as aioredis
from girder.constants import TokenScope
from girder.models.token import Token
from girder.notification import Notification
from starlette.websockets import WebSocket, WebSocketState

logger = logging.getLogger(__name__)


ANNOUNCEMENTS_CHANNEL = "announcements"


@functools.lru_cache
def _redis_client_async() -> aioredis.Redis:
    url = os.environ.get("GIRDER_NOTIFICATION_REDIS_URL", "redis://localhost:6379")
    return aioredis.Redis.from_url(url, socket_timeout=None)


@functools.lru_cache
def _redis_client_sync() -> redis.Redis:
    url = os.environ.get("GIRDER_NOTIFICATION_REDIS_URL", "redis://localhost:6379")
    return redis.Redis.from_url(url, socket_timeout=None)


@staticmethod
def _authenticate_token(token_id: str):
    token = Token().load(token_id, force=True, objectId=False)
    if (
        token is None
        or token["expires"] < datetime.datetime.now(datetime.timezone.utc)
        or "userId" not in token
        or not Token().hasScope(token, TokenScope.USER_AUTH)
    ):
        raise ValueError("Invalid token")
    return token["userId"]


async def announcement_socket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # 1. Handle one-time authentication
    try:
        auth_message = await websocket.receive_text()
        payload = json.loads(auth_message)

        if not payload.get("type") == "auth" or not payload.get("token"):
            await websocket.close(code=3000, reason="Authentication required")
            return

        user_id = _authenticate_token(payload["token"])
    except (json.JSONDecodeError, ValueError):
        await websocket.close(code=3000, reason="Invalid token")
        return
    except Exception:
        await websocket.close(code=3000, reason="Authentication failed")
        return

    # 2. Setup Redis
    pubsub = _redis_client_async().pubsub()
    await pubsub.subscribe(ANNOUNCEMENTS_CHANNEL)
    logger.info(f"User {user_id} subscribed to announcements channel")

    # This background task watches for client disconnects or server shutdowns
    async def forward_messages():
        try:
            async for message in pubsub.listen():
                if message and message.get("type") == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    await websocket.send_text(data)
        except asyncio.CancelledError:
            pass  # Gracefully handle server shutdown task cancellation

    # 3. Use an active task layout so Uvicorn can cancel it on exit
    stream_task = asyncio.create_task(forward_messages())

    try:
        # Keep the endpoint open and wait until the task completes or is cancelled
        # We also listen for an empty read which means the client disconnected.
        while not stream_task.done():
            try:
                # 0.5s timeout keeps the event loop fluid during shutdown signals
                await asyncio.wait_for(websocket.receive_text(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except Exception:
                # Client disconnected or socket closed
                break
    except asyncio.CancelledError:
        # Server is shutting down (SIGINT/SIGTERM received by Uvicorn)
        pass
    finally:
        # Clean up tasks and close channels immediately
        stream_task.cancel()
        try:
            await stream_task
        except Exception:
            pass

        try:
            await pubsub.unsubscribe(ANNOUNCEMENTS_CHANNEL)
            await pubsub.close()
        except Exception:
            pass

        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass


class Announcement(Notification):
    def __init__(self, type: str, data: dict, **payload):
        super().__init__(type, data, user=None, **payload)

    def flush(self):
        msg = json.dumps(self._payload, default=str)

        try:
            _redis_client_sync().publish(ANNOUNCEMENTS_CHANNEL, msg)
        except redis.RedisError:
            logger.exception("Error flushing announcement to redis")
