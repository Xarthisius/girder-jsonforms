"""Tests for ``GET /aimdl/datafiles`` and its optional ``dataType``.

``dataType`` used to be required, so ``meta.data_type`` was always part of the
query. It is now optional, and omitting it drops that clause entirely -- which
is the only thing between "every data type" and "every IGSN-tagged item the
caller can read". So these pin both halves: that the filter still filters when
asked, and that dropping it widens the result set over data types *without*
widening it over the ACL or over items that carry no IGSN at all.

Server level throughout, per CLAUDE.md on not mixing the two in one module.
"""

import pytest
from girder.constants import AccessType
from girder.models.collection import Collection
from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.setting import Setting
from girder.models.user import User
from pytest_girder.assertions import assertStatus, assertStatusOk

import girder_jsonforms.rest.aimdl as aimdl_mod
from girder_jsonforms.settings import PluginSettings


@pytest.fixture
def no_cache(db):
    """Caching off: these assert on what the query returns, not on a TTL.

    The listing cache is keyed per user and query, so it would not actually
    cross-contaminate the cases below -- but a stale entry surviving a fixture
    teardown would, and a zero TTL is the documented way to disable it.
    """
    Setting().set(PluginSettings.AIMDL_CACHE_TTL, 0)
    yield
    Setting().unset(PluginSettings.AIMDL_CACHE_TTL)


@pytest.fixture
def aimdl_collection(db, admin, monkeypatch):
    """The collection AIMDL treats as its root.

    ``_AIMDL_COLLECTION_ID`` has to point at it: the ``meta.igsn`` save hook
    resolves the blessed collection on every item save and 404s if it is
    missing.
    """
    collection = Collection().createCollection("AIMDL", admin, public=False)
    monkeypatch.setattr(aimdl_mod, "_AIMDL_COLLECTION_ID", str(collection["_id"]))
    yield collection
    Collection().remove(collection)


@pytest.fixture
def datafiles(aimdl_collection, admin, no_cache):
    """Two xrd items, one pdv, one with an IGSN but no data type, one with
    neither -- so each case below has something it must exclude."""
    folder = Folder().createFolder(
        aimdl_collection, "data", parentType="collection", creator=admin, public=False
    )

    def _mk(name, meta):
        item = Item().createItem(name, admin, folder)
        return Item().setMetadata(item, meta)

    items = {
        "xrd1": _mk("xrd1", {"igsn": "JHAMAA00001", "data_type": "xrd_raw"}),
        "xrd2": _mk("xrd2", {"igsn": "JHAMAA00002", "data_type": "xrd_raw"}),
        "pdv1": _mk("pdv1", {"igsn": "JHAMAA00003", "data_type": "pdv_alpss"}),
        # An IGSN with no data_type at all: unreachable while dataType was
        # required, and the clearest thing the widened query must now return.
        "untyped": _mk("untyped", {"igsn": "JHAMAA00004"}),
        # No IGSN: excluded either way, since that clause never moved.
        "stray": _mk("stray", {"data_type": "xrd_raw"}),
    }
    yield {"collection": aimdl_collection, "folder": folder, "items": items}
    Folder().remove(Folder().load(folder["_id"], force=True))


def request(server, user, collection, **params):
    base = {
        "baseParentType": "collection",
        "baseParentId": str(collection["_id"]),
    }
    return server.request(
        path="/aimdl/datafiles", method="GET", user=user, params={**base, **params}
    )


def names(resp):
    return sorted(item["name"] for item in resp.json)


@pytest.mark.plugin("jsonforms")
class TestDataTypeFilter:
    def test_data_type_still_filters(self, server, admin, datafiles):
        resp = request(server, admin, datafiles["collection"], dataType="xrd_raw")
        assertStatusOk(resp)
        assert names(resp) == ["xrd1", "xrd2"]

    def test_data_type_omitted_returns_every_type(self, server, admin, datafiles):
        resp = request(server, admin, datafiles["collection"])
        assertStatusOk(resp)
        assert names(resp) == ["pdv1", "untyped", "xrd1", "xrd2"]

    def test_data_type_omitted_includes_items_without_one(
        self, server, admin, datafiles
    ):
        # The item the old required-parameter query could not express.
        resp = request(server, admin, datafiles["collection"])
        assertStatusOk(resp)
        assert "untyped" in names(resp)

        resp = request(server, admin, datafiles["collection"], dataType="xrd_raw")
        assertStatusOk(resp)
        assert "untyped" not in names(resp)

    def test_igsn_clause_still_applies(self, server, admin, datafiles):
        # Dropping meta.data_type must not drop meta.igsn with it.
        for params in ({}, {"dataType": "xrd_raw"}):
            resp = request(server, admin, datafiles["collection"], **params)
            assertStatusOk(resp)
            assert "stray" not in names(resp)

    def test_unknown_data_type_returns_nothing(self, server, admin, datafiles):
        resp = request(server, admin, datafiles["collection"], dataType="nope")
        assertStatusOk(resp)
        assert resp.json == []

    def test_total_count_header_follows_the_filter(self, server, admin, datafiles):
        resp = request(server, admin, datafiles["collection"], dataType="xrd_raw")
        assertStatusOk(resp)
        assert resp.headers["Girder-Total-Count"] == 2

        resp = request(server, admin, datafiles["collection"])
        assertStatusOk(resp)
        assert resp.headers["Girder-Total-Count"] == 4


@pytest.mark.plugin("jsonforms")
class TestOmittedDataTypeKeepsAccessControl:
    """The widened query is still ACL-filtered.

    A missing ``meta.data_type`` clause means more documents reach the access
    check, so this is where a widened query would leak if the check were ever
    bypassed for the unfiltered case.
    """

    @pytest.fixture
    def outsider(self, db):
        person = User().createUser(
            "dfoutsider", "P@ssw0rd123", "Df", "Outsider", "dfoutsider@example.invalid"
        )
        yield person
        User().remove(User().load(person["_id"], force=True))

    def test_outsider_sees_nothing(self, server, datafiles, outsider):
        resp = request(server, outsider, datafiles["collection"])
        # The collection itself is private, so the parent load is what refuses.
        assertStatus(resp, 403)

    def test_outsider_sees_nothing_in_a_readable_collection(
        self, server, admin, datafiles, outsider
    ):
        # Readable collection, unreadable folder: the request gets through the
        # parent check and the items are filtered on their folder's ACL.
        Collection().setPublic(datafiles["collection"], True, save=True)
        resp = request(server, outsider, datafiles["collection"])
        assertStatusOk(resp)
        assert resp.json == []

    def test_partial_access_is_respected(self, server, admin, datafiles, outsider):
        Collection().setPublic(datafiles["collection"], True, save=True)
        other = Folder().createFolder(
            datafiles["collection"],
            "open",
            parentType="collection",
            creator=admin,
            public=True,
        )
        try:
            item = Item().createItem("open1", admin, other)
            Item().setMetadata(item, {"igsn": "JHAMAA00005", "data_type": "pdv_alpss"})
            resp = request(server, outsider, datafiles["collection"])
            assertStatusOk(resp)
            assert names(resp) == ["open1"]
        finally:
            Folder().remove(Folder().load(other["_id"], force=True))

    def test_user_with_a_grant_sees_the_granted_folder(
        self, server, admin, datafiles, outsider
    ):
        Collection().setPublic(datafiles["collection"], True, save=True)
        Folder().setUserAccess(
            datafiles["folder"], outsider, AccessType.READ, save=True
        )
        resp = request(server, outsider, datafiles["collection"])
        assertStatusOk(resp)
        assert names(resp) == ["pdv1", "untyped", "xrd1", "xrd2"]
