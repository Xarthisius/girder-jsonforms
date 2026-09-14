"""Controlled vocabularies for IGSN prefixes.

Prefix validity is defined by the institution/material vocabularies. Those used
to live in per-instance settings (``jsonforms.igsn_institutions`` /
``jsonforms.igsn_materials``), which were free to drift apart between Girder
instances -- so two instances could disagree about whether a prefix was legal.

In remote mode the service is the source of truth and this module caches its
answer briefly. The local settings remain the fallback for local mode and for
when the service is momentarily unreachable: rejecting a prefix that was valid
five minutes ago is worse than using a slightly stale vocabulary, since the
service validates every allocation again anyway.
"""

import logging
import threading
import time

from girder.models.setting import Setting

from ..settings import PluginSettings
from .igsn_client import IGSNServiceError, get_client

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 300

_lock = threading.Lock()
_cache = {"expires": 0.0, "value": None}


def _from_settings():
    return {
        "institutions": Setting().get(PluginSettings.IGSN_INSTITUTIONS),
        "materials": Setting().get(PluginSettings.IGSN_MATERIALS),
    }


def invalidate():
    """Drop the cache. Useful in tests and after a vocabulary change."""
    with _lock:
        _cache["expires"] = 0.0
        _cache["value"] = None


def get_vocabularies():
    """Return ``{"institutions": ..., "materials": ...}``."""
    client = None
    try:
        client = get_client()
    except IGSNServiceError:
        logger.exception("IGSN service is misconfigured; using local vocabularies")

    if client is None:
        return _from_settings()

    now = time.monotonic()
    with _lock:
        if _cache["value"] is not None and _cache["expires"] > now:
            return _cache["value"]

    try:
        remote = client.vocabularies()
        value = {
            "institutions": remote["institutions"],
            "materials": remote["materials"],
        }
    except (IGSNServiceError, KeyError):
        logger.exception("Could not fetch vocabularies from the IGSN service")
        with _lock:
            if _cache["value"] is not None:
                # Serve stale rather than rejecting prefixes that are actually fine.
                return _cache["value"]
        return _from_settings()

    with _lock:
        _cache["value"] = value
        _cache["expires"] = time.monotonic() + CACHE_TTL_SECONDS
    return value
