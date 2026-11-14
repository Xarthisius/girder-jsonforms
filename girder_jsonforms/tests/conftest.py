"""Shared fixtures: one Girder server and database per module, and the IGSN tests'.

``db`` and ``server`` are overridden here (see ``_module_girder``); the rest of
Girder's fixtures (``admin``, ``user``, ``fsAssetstore``, ...) come from
pytest-girder and build on the overridden ``db``. The IGSN registry fixtures
live in a conftest rather than being imported between test modules so pytest
resolves them without cross-module fixture imports, and are prefixed ``igsn_``
to stay clear of the same-purpose fixtures the older test modules define for
themselves.
"""

import hashlib
import os
from unittest.mock import MagicMock, patch

import pytest
from girder.models.setting import Setting

from ..lib import igsn_vocab
from ..lib.igsn_client import IGSNClient
from ..settings import PluginSettings


def _module_plugins(module_node):
    """The one ``plugin`` marker set every test in a module agrees on.

    A module shares one server, so it can load only one set of plugins. Mixed
    sets are a usage error rather than something to guess around: give the
    odd tests the module's markers, or move them. Tests with no marker (plain
    or db-only ones) are ignored, and order does not count.
    """
    found = {}
    for item in module_node.session.items:
        if item.module is not module_node.obj:
            continue
        markers = list(item.iter_markers("plugin"))
        if not markers:
            continue
        if any(len(m.args) > 1 for m in markers):
            raise pytest.UsageError(
                f"{item.nodeid}: test-registered plugins are not supported"
            )
        names = [m.args[0] for m in markers]
        found.setdefault(frozenset(names), names)
    if len(found) > 1:
        raise pytest.UsageError(
            f"{module_node.nodeid}: tests ask for different plugin sets "
            f"{sorted(sorted(s) for s in found)}; one module shares one server"
        )
    return next(iter(found.values())) if found else []


@pytest.fixture(scope="module")
def _module_girder(request):
    """One database and one server per test module, per xdist worker.

    Replaces pytest-girder's per-test ``db``/``server``, which dropped the
    database, rebuilt every index and loaded every plugin for each test:
    fixtures were 98% of the suite's worker-time against a median test body
    of 0.01s. ``_fresh_db`` resets the data between tests instead and keeps
    the indexes.

    ``load()`` runs once per module now, but it also writes to the database --
    jsonforms creates the projects collection there -- so what the plugins
    wrote is snapshotted right after loading and restored by ``_fresh_db``,
    with the same ``_id``s, so anything that cached a seeded document (as
    ``Project.project_collection`` does) still points at a real one.

    Two things pytest-girder did that this deliberately does not:

    * reset each model's ``_instance`` on teardown. The live singletons are
      simply pointed at the next module's database below; resetting them
      without pruning ``_modelSingletons`` is the leak girder/girder#3991
      fixed upstream.
    * honour ``--keep-db`` / ``--mock-db``. Nothing here uses them.

    The database name carries the xdist worker id: two workers can each be
    handed part of the same module, and a name from the module alone would
    have them wipe each other's data.
    """
    from girder.models import _dbClients, getDbConnection, model_base
    from girder.models.user import User
    from pytest_girder.plugin_registry import PluginRegistry
    from pytest_girder.utils import serverContext

    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    digest = hashlib.md5(f"{worker}:{request.node.nodeid}".encode()).hexdigest()
    name = f"girder_test_{digest}"
    connection = getDbConnection(
        uri=f"{request.config.getoption('--mongo-uri')}/{name}", quiet=False
    )
    _dbClients[(None, None)] = connection
    connection.drop_database(name)
    for model in model_base._modelSingletons:
        try:
            model.reconnect()
        except OSError:
            pass  # lazy index creation, as pytest-girder ignores it too
    User()._cryptContext.scheme = "plaintext"  # skip bcrypt, as pytest-girder does

    try:
        with PluginRegistry()(), serverContext(
            _module_plugins(request.node)
        ) as server:
            database = connection.get_database()
            seeded = {
                coll: list(database[coll].find())
                for coll in database.list_collection_names()
                if not coll.startswith("system.")
            }
            yield connection, server, seeded
    finally:
        connection.drop_database(name)
        connection.close()
        _dbClients.clear()


@pytest.fixture
def _fresh_db(_module_girder):
    """Put the module's database back to how plugin loading left it."""
    from ..models.project import Project

    connection, _, seeded = _module_girder
    database = connection.get_database()
    for coll in database.list_collection_names():
        if coll.startswith("system."):
            continue
        database[coll].delete_many({})
        if seeded.get(coll):
            database[coll].insert_many(seeded[coll])
    # Restored with the same _id, but a test may rename the collection setting.
    Project()._project_collection = None
    return connection


@pytest.fixture
def db(_fresh_db):
    return _fresh_db


@pytest.fixture
def server(_module_girder, _fresh_db):
    return _module_girder[1]

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
    # An unrestricted tenant, which is what the service means by an empty
    # allowed_institutions. Tests that care about tenant scoping override it.
    client.whoami.return_value = {
        "slug": "test",
        "name": "Test Tenant",
        "allowed_institutions": [],
        "doi_prefix": "10.83961",
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


@pytest.fixture
def sent_mail(monkeypatch):
    """Capture what would have been handed to SMTP, as (message, recipients).

    ``lib/mail.py`` triggers the ``_sendmail`` event, whose core handler calls
    ``mail_utils._submitEmail``; patching that module attribute intercepts
    delivery while leaving the rest of the path intact.
    """
    from girder.utility import mail_utils

    messages = []

    def _capture(msg, recipients):
        messages.append((msg, recipients))

    monkeypatch.setattr(mail_utils, "_submitEmail", _capture)
    return messages
