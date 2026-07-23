"""Coerce ISO-8601 date/datetime strings in Item/Folder metadata to BSON dates.

Girder's ``setMetadata`` on Item and Folder accepts arbitrary JSON, which is
parsed with the stdlib ``json`` module. That never produces ``datetime``
objects, so a value like ``"2023-10-01T12:00:00Z"`` lands in MongoDB as a plain
string and cannot be used with range/date queries. This module provides an
event handler (bound to ``model.item.save`` / ``model.folder.save``) that walks
the document's ``meta`` field and rewrites strict ISO-8601 strings into
timezone-aware ``datetime`` objects, which pymongo stores as BSON dates.

Detection is deliberately strict (a full ``YYYY-MM-DD`` date is the minimum):
it must not misfire on non-date metadata (version strings, plain
integers-as-strings, free text) since it mutates data on the way into the
database. The same :func:`coerce_dates` helper is reused to coerce Mongo query
values (see ``_item_advanced_search``) so that queries and stored values agree
on exactly which strings are dates.
"""

import datetime
import logging
import re

logger = logging.getLogger(__name__)

# Full date, optionally followed by a time (with optional seconds, fractional
# seconds, and 'Z' or numeric UTC offset). 'T' or a space may separate the
# date and time. A bare date (no time) is accepted and stored at midnight UTC.
_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:[Zz]|[+-]\d{2}:?\d{2})?)?$"
)


def _parse_iso(value):
    """Parse a strict ISO-8601 string to a UTC-aware datetime, or return None.

    A date-only string becomes midnight UTC. A naive datetime is assumed to be
    UTC; an offset-aware datetime is converted to UTC so that the stored instant
    matches how Girder's ``JsonEncoder`` serializes it back out.
    """
    if not _ISO_RE.match(value):
        return None
    try:
        # datetime.fromisoformat handles 'Z' and space separators on 3.11+, but
        # normalize defensively so behavior does not depend on the interpreter.
        normalized = value.replace(" ", "T")
        if normalized[-1] in ("Z", "z"):
            normalized = normalized[:-1] + "+00:00"
        parsed = datetime.datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def coerce_dates(value):
    """Recursively coerce ISO date strings within an arbitrary JSON value.

    Returns a new structure with strict ISO-8601 strings replaced by UTC-aware
    ``datetime`` objects. Used both to normalize ``meta`` before saving and to
    coerce Mongo query values so that queries match the stored BSON dates. Dict
    keys are never touched, so query operators (``$gte`` and friends) survive.
    """
    if isinstance(value, str):
        parsed = _parse_iso(value)
        return parsed if parsed is not None else value
    if isinstance(value, dict):
        return {k: coerce_dates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [coerce_dates(item) for item in value]
    # int/float/bool/None/datetime and anything else pass through unchanged,
    # which also makes re-saving an already-coerced document idempotent.
    return value


def coerce_metadata_dates(event):
    """Girder event handler for ``model.item.save`` / ``model.folder.save``.

    Rewrites ISO-8601 date strings in the document's ``meta`` field to BSON
    ``datetime`` objects in place, before the document is persisted. This fires
    for every save path (REST ``setMetadata``, internal ``save`` calls, other
    plugins), not just the metadata REST endpoints.
    """
    document = event.info
    if not isinstance(document, dict):
        return
    meta = document.get("meta")
    if not isinstance(meta, dict) or not meta:
        return
    try:
        document["meta"] = coerce_dates(meta)
    except Exception:  # pragma: no cover - never block a save on coercion
        logger.warning("Failed to coerce metadata dates; leaving meta unchanged",
                       exc_info=True)
