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

The registry's vocabulary is global but allocation is tenant-scoped, so the two
are not the same list. ``GET /vocabularies`` returns every institution the
registry knows; ``GET /whoami`` says which of them this instance's tenant may
allocate under. Without the intersection the form happily offers JH to a tenant
that only holds AB, and the refusal arrives after the metadata has been filled
in -- readable now, but still a dead end.
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


def _permitted(institutions, client):
    """Narrow the registry's institutions to the ones this tenant may use.

    An empty ``allowed_institutions`` means unrestricted -- the service reads it
    that way too (``validate_prefix`` only checks when the list is non-empty),
    and the two must agree or the form offers less than the registry accepts.

    A ``whoami`` that fails is not worth discarding a good vocabulary over: the
    unfiltered list is what was shown before, and the allocation is validated
    again at the service anyway.
    """
    try:
        allowed = set((client.whoami() or {}).get("allowed_institutions") or ())
    except IGSNServiceError:
        logger.exception("Could not read the tenant from the IGSN service")
        return institutions

    if not allowed:
        return institutions

    permitted = {
        code: value for code, value in institutions.items() if code in allowed
    }
    if not permitted:
        # Nothing the tenant is allowed to use exists in the vocabulary, so the
        # dropdown will be empty. That is the honest answer -- every prefix
        # would be refused -- but it is a misconfiguration, not a normal state.
        logger.warning(
            "Tenant is allowed institutions %s, none of which the IGSN "
            "vocabulary defines",
            sorted(allowed),
        )
    return permitted


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
            "institutions": _permitted(remote["institutions"], client),
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
