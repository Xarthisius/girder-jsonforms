"""Tests that AIMDL partition/filter logic works now that
``meta.experiment_date`` is stored as a BSON ``datetime`` rather than a string.
"""

import datetime

import pytest
from girder.constants import AccessType

import girder_jsonforms.rest.aimdl as aimdl_mod
from girder_jsonforms.rest.aimdl import (
    _experiment_date_query,
    _format_experiment_date,
)

UTC = datetime.timezone.utc


@pytest.fixture
def aimdl_collection(admin, monkeypatch):
    """Create the collection AIMDL treats as its root and point the module's
    ``_AIMDL_COLLECTION_ID`` at it, so the ``meta.igsn`` save hook resolves."""
    from girder.models.collection import Collection

    collection = Collection().createCollection("AIMDL", admin, public=True)
    monkeypatch.setattr(aimdl_mod, "_AIMDL_COLLECTION_ID", str(collection["_id"]))
    yield collection
    Collection().remove(collection)


class TestFormatExperimentDate:
    def test_datetime_full(self):
        value = datetime.datetime(2026, 1, 2, 13, 45, tzinfo=UTC)
        assert _format_experiment_date(value) == value.isoformat()

    def test_datetime_ignore_time(self):
        value = datetime.datetime(2026, 1, 2, 13, 45, tzinfo=UTC)
        assert _format_experiment_date(value, ignore_time=True) == "2026-01-02"

    def test_legacy_string_ignore_time(self):
        # Un-migrated string value is still reduced to a date.
        assert (
            _format_experiment_date("2026-01-02T13:45:00Z", ignore_time=True)
            == "2026-01-02"
        )

    def test_legacy_string_full(self):
        assert _format_experiment_date("whatever") == "whatever"


class TestExperimentDateQuery:
    def test_exact_datetime(self):
        q = _experiment_date_query("2026-01-02T00:00:00+00:00", ignore_time=False)
        assert q == datetime.datetime(2026, 1, 2, tzinfo=UTC)

    def test_day_range(self):
        q = _experiment_date_query("2026-01-02", ignore_time=True)
        assert q == {
            "$gte": datetime.datetime(2026, 1, 2, tzinfo=UTC),
            "$lt": datetime.datetime(2026, 1, 3, tzinfo=UTC),
        }

    def test_non_iso_fallback_exact(self):
        assert _experiment_date_query("not-a-date", ignore_time=False) == "not-a-date"

    def test_non_iso_fallback_regex(self):
        assert _experiment_date_query("not-a-date", ignore_time=True) == {
            "$regex": "^not\\-a\\-date"
        }


@pytest.mark.plugin("jsonforms")
class TestPartitionRoundTrip:
    """The partition key produced by list_partitions must resolve back to the
    same items via get_partition, through the datetime storage."""

    def _setup(self, admin, aimdl_collection):
        from girder.models.folder import Folder
        from girder.models.item import Item

        folder = Folder().createFolder(
            aimdl_collection, "data", parentType="collection", creator=admin
        )

        def _mk(name, meta):
            item = Item().createItem(name, admin, folder)
            return Item().setMetadata(item, meta)

        # Two xrd items sharing an igsn + experiment_date -> one partition.
        _mk(
            "xrd1",
            {
                "igsn": "JHAMAA00001",
                "data_type": "xrd_raw",
                "experiment_date": "2026-01-02",
                "checksum": {"sha256": "aaa"},
            },
        )
        _mk(
            "xrd2",
            {
                "igsn": "JHAMAA00001",
                "data_type": "xrd_raw",
                "experiment_date": "2026-01-02",
                "checksum": {"sha256": "bbb"},
            },
        )
        # A pdv item whose experiment_date carries a time component.
        _mk(
            "pdv1",
            {
                "igsn": "JHAMAA00002",
                "data_type": "pdv_alpss",
                "experiment_date": "2026-03-15T13:45:00Z",
                "checksum": {"sha256": "ccc"},
            },
        )
        return folder

    def _params(self, collection, dataType):
        return {
            "dataType": dataType,
            "baseParentType": "collection",
            "baseParentId": str(collection["_id"]),
        }

    def test_xrd_partition_roundtrip(self, server, admin, aimdl_collection):
        from girder.models.folder import Folder

        folder = self._setup(admin, aimdl_collection)
        try:
            resp = server.request(
                path="/aimdl/partition",
                method="GET",
                user=admin,
                params=self._params(aimdl_collection, "xrd_raw"),
            )
            from pytest_girder.assertions import assertStatusOk

            assertStatusOk(resp)
            keys = list(resp.json.keys())
            assert len(keys) == 1
            key = keys[0]
            # Key is igsn//<isoformat datetime>.
            assert key.startswith("JHAMAA00001//2026-01-02T00:00:00")

            resp = server.request(
                path="/aimdl/partition/details",
                method="GET",
                user=admin,
                params={"key": key, **self._params(aimdl_collection, "xrd_raw")},
            )
            assertStatusOk(resp)
            names = sorted(i["name"] for i in resp.json)
            assert names == ["xrd1", "xrd2"]
        finally:
            Folder().remove(folder)

    def test_pdv_partition_roundtrip_ignores_time(self, server, admin, aimdl_collection):
        from girder.models.folder import Folder
        from pytest_girder.assertions import assertStatusOk

        folder = self._setup(admin, aimdl_collection)
        try:
            resp = server.request(
                path="/aimdl/partition",
                method="GET",
                user=admin,
                params=self._params(aimdl_collection, "pdv_alpss"),
            )
            assertStatusOk(resp)
            keys = list(resp.json.keys())
            assert keys == ["JHAMAA00002//2026-03-15"]

            # The date-only key must resolve the item despite its 13:45 time.
            resp = server.request(
                path="/aimdl/partition/details",
                method="GET",
                user=admin,
                params={
                    "key": "JHAMAA00002//2026-03-15",
                    **self._params(aimdl_collection, "pdv_alpss"),
                },
            )
            assertStatusOk(resp)
            assert [i["name"] for i in resp.json] == ["pdv1"]
        finally:
            Folder().remove(folder)


@pytest.mark.plugin("jsonforms")
class TestPartitionPermissions:
    """``list_partitions`` resolves item access through the owning folder's ACL.

    The implementation no longer joins a folder onto every matching item (see
    ``BaseLabResource._readable_folder_clause``), so these pin the access
    semantics that replaced: public folders are readable, private ones are not,
    and a direct or group grant makes one readable.
    """

    @staticmethod
    def _mk_item(folder, creator, name, sha):
        from girder.models.item import Item

        item = Item().createItem(name, creator, folder)
        return Item().setMetadata(
            item,
            {
                "igsn": "JHAMAA00001",
                "data_type": "xrd_raw",
                "experiment_date": "2026-01-02",
                "checksum": {"sha256": sha},
            },
        )

    def _params(self, collection):
        return {
            "dataType": "xrd_raw",
            "baseParentType": "collection",
            "baseParentId": str(collection["_id"]),
        }

    def _request(self, server, collection, user):
        from pytest_girder.assertions import assertStatusOk

        resp = server.request(
            path="/aimdl/partition",
            method="GET",
            user=user,
            params=self._params(collection),
        )
        assertStatusOk(resp)
        return resp.json

    def test_private_folder_is_invisible(self, server, admin, user, aimdl_collection):
        from girder.models.folder import Folder

        # Folders inherit the parent collection's ACL (copyAccessPolicies), and
        # the fixture collection is public -- so opt out explicitly.
        folder = Folder().createFolder(
            aimdl_collection,
            "private",
            parentType="collection",
            creator=admin,
            public=False,
        )
        try:
            self._mk_item(folder, admin, "xrd1", "aaa")
            # admin reads everything; a plain user reads nothing here.
            assert len(self._request(server, aimdl_collection, admin)) == 1
            assert self._request(server, aimdl_collection, user) == {}
        finally:
            Folder().remove(folder)

    def test_public_folder_is_visible(self, server, admin, user, aimdl_collection):
        from girder.models.folder import Folder

        folder = Folder().createFolder(
            aimdl_collection,
            "public",
            parentType="collection",
            creator=admin,
            public=True,
        )
        try:
            self._mk_item(folder, admin, "xrd1", "aaa")
            assert list(self._request(server, aimdl_collection, user)) == [
                "JHAMAA00001//2026-01-02T00:00:00+00:00"
            ]
        finally:
            Folder().remove(folder)

    def test_direct_and_group_grants(self, server, admin, user, aimdl_collection):
        from girder.models.folder import Folder
        from girder.models.group import Group

        direct = Folder().createFolder(
            aimdl_collection,
            "direct",
            parentType="collection",
            creator=admin,
            public=False,
        )
        viagroup = Folder().createFolder(
            aimdl_collection,
            "viagroup",
            parentType="collection",
            creator=admin,
            public=False,
        )
        group = Group().createGroup("readers", admin)
        try:
            self._mk_item(direct, admin, "xrd1", "aaa")
            self._mk_item(viagroup, admin, "xrd2", "bbb")

            # Neither is readable yet, so the two items contribute no partition.
            assert self._request(server, aimdl_collection, user) == {}

            Folder().setUserAccess(direct, user, AccessType.READ, save=True)
            only_direct = self._request(server, aimdl_collection, user)

            Group().addUser(group, user, level=AccessType.READ)
            Folder().setGroupAccess(viagroup, group, AccessType.READ, save=True)
            both = self._request(server, aimdl_collection, user)

            # One partition key throughout (same igsn + date), but the digest
            # must change once the group grant brings the second checksum in.
            assert list(only_direct) == list(both)
            assert only_direct != both
            assert both == self._request(server, aimdl_collection, admin)
        finally:
            Group().remove(group)
            Folder().remove(direct)
            Folder().remove(viagroup)

    def test_both_folder_clause_branches_agree(
        self, server, admin, user, aimdl_collection, monkeypatch
    ):
        """``$nin <unreadable>`` and ``$in <readable>`` must select the same items.

        ``_readable_folder_clause`` names whichever side is smaller; forcing the
        threshold to 0 takes the ``$in`` branch on data that would otherwise take
        the ``$nin`` one, so the two have to agree.
        """
        from girder.models.folder import Folder

        readable = Folder().createFolder(
            aimdl_collection,
            "readable",
            parentType="collection",
            creator=admin,
            public=True,
        )
        hidden = Folder().createFolder(
            aimdl_collection,
            "hidden",
            parentType="collection",
            creator=admin,
            public=False,
        )
        try:
            self._mk_item(readable, admin, "visible", "aaa")
            self._mk_item(hidden, admin, "invisible", "bbb")

            via_nin = self._request(server, aimdl_collection, user)
            monkeypatch.setattr(aimdl_mod.BaseLabResource, "MAX_DENIED_FOLDERS", 0)
            via_in = self._request(server, aimdl_collection, user)

            assert via_nin == via_in
            # And neither leaks the hidden folder's checksum: the digest matches
            # the one-item partition, not the admin's two-item view.
            assert via_nin != self._request(server, aimdl_collection, admin)
        finally:
            Folder().remove(readable)
            Folder().remove(hidden)
