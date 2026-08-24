"""Shared fixtures for the centralized-IGSN tests.

Girder's own fixtures (``db``, ``server``, ``admin``, ``user``, ...) come from
pytest-girder; everything here is specific to the IGSN registry. It lives in a
conftest rather than being imported between test modules so pytest resolves it
without cross-module fixture imports.

Names are prefixed ``igsn_`` to stay clear of the same-purpose fixtures the
older test modules define for themselves.
"""

from unittest.mock import MagicMock, patch

import pytest
from girder.models.setting import Setting

from ..lib import igsn_vocab
from ..lib.igsn_client import IGSNClient
from ..settings import PluginSettings

IGSN_SERVICE_URL = "https://igsn.example.org"
IGSN_SERVICE_TOKEN = "test-token"


@pytest.fixture
def igsn_settings(db):
    """Minimal institution/material vocabularies, as local settings."""
    institutions = {"AB": {"name": "Test Institution", "labs": {"C": "Test Lab"}}}
    materials = {"DE": {"name": "Test Material", "subcategories": {"F": "Sub"}}}
    Setting().set(PluginSettings.IGSN_INSTITUTIONS, institutions)
    Setting().set(PluginSettings.IGSN_MATERIALS, materials)
    Setting().set(PluginSettings.IGSN_PUBLISHER, {"name": "Test Publisher"})
    yield institutions, materials
    Setting().unset(PluginSettings.IGSN_INSTITUTIONS)
    Setting().unset(PluginSettings.IGSN_MATERIALS)
    Setting().unset(PluginSettings.IGSN_PUBLISHER)


@pytest.fixture
def local_mode(igsn_settings):
    """No registry configured: the plugin's original per-instance behavior."""
    Setting().unset(PluginSettings.IGSN_SERVICE_URL)
    Setting().unset(PluginSettings.IGSN_SERVICE_TOKEN)
    igsn_vocab.invalidate()
    yield
    igsn_vocab.invalidate()


@pytest.fixture
def remote_mode(igsn_settings):
    """Registry configured: allocation and publication are delegated."""
    Setting().set(PluginSettings.IGSN_SERVICE_URL, IGSN_SERVICE_URL)
    Setting().set(PluginSettings.IGSN_SERVICE_TOKEN, IGSN_SERVICE_TOKEN)
    igsn_vocab.invalidate()
    yield
    Setting().unset(PluginSettings.IGSN_SERVICE_URL)
    Setting().unset(PluginSettings.IGSN_SERVICE_TOKEN)
    igsn_vocab.invalidate()


@pytest.fixture
def igsn_metadata():
    """DataCite metadata sufficient for a deposition to validate."""
    return {
        "titles": [{"title": "Remote Sample"}],
        "creators": [{"name": "Doe, Jane", "nameType": "Personal"}],
        "publisher": {"name": "Test Publisher"},
        "publicationYear": "2026",
        "alternateIdentifiers": [
            {"alternateIdentifier": "LOCAL-1", "alternateIdentifierType": "Local"}
        ],
    }


def igsn_record(igsn, status="reserved", **kwargs):
    """A record as the registry's API would return it."""
    return {
        "igsn": igsn,
        "doi": f"10.83961/{igsn.lower()}",
        "prefix": igsn[:6],
        "status": status,
        "metadata": {},
        "landing_page": None,
        "datacite": {"last_error": None},
        **kwargs,
    }


class _patch_all:
    """Apply several ``patch`` context managers as one."""

    def __init__(self, targets, value):
        self._patchers = [patch(target, return_value=value) for target in targets]

    def __enter__(self):
        for patcher in self._patchers:
            patcher.start()
        return self

    def __exit__(self, *exc_info):
        for patcher in reversed(self._patchers):
            patcher.stop()
        return False


@pytest.fixture
def igsn_service():
    """Stub registry client, allocating ABCDEF00001, ABCDEF00002, ... in order.

    Patched into every module that resolves a client, since each imports
    ``get_client`` by name and so holds its own reference.
    """
    client = MagicMock(spec=IGSNClient)
    counter = {"n": 0}

    def allocate(prefix, count=1, **kwargs):
        records = []
        for _ in range(count):
            counter["n"] += 1
            records.append(igsn_record(f"{prefix}{counter['n']:05d}"))
        return records

    def allocate_children(igsn, indices=None, count=None, **kwargs):
        if indices is None:
            indices = [f"{i + 1:03d}" for i in range(count or 0)]
        return [igsn_record(f"{igsn}-{index}") for index in indices]

    client.allocate.side_effect = allocate
    client.allocate_children.side_effect = allocate_children
    client.put_record.side_effect = lambda igsn, **kwargs: igsn_record(igsn)
    client.get_record.side_effect = lambda igsn: igsn_record(igsn)
    client.publish.return_value = {"attempts": ["a1"], "queued": 1}
    client.revoke.return_value = igsn_record("ABCDEF00001", status="revoked")
    client.vocabularies.return_value = {
        "institutions": {"AB": {"name": "Remote Inst", "labs": {"C": "Remote Lab"}}},
        "materials": {"DE": {"name": "Remote Material", "subcategories": {"F": "Sub"}}},
    }

    targets = (
        "girder_jsonforms.lib.igsn_client.get_client",
        "girder_jsonforms.lib.igsn_vocab.get_client",
        "girder_jsonforms.models.deposition.get_client",
        "girder_jsonforms.rest.deposition.get_client",
        "girder_jsonforms.worker_plugin.igsn_registry.get_client",
    )
    with _patch_all(targets, client):
        yield client
