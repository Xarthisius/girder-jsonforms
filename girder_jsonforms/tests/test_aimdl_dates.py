"""Tests that AIMDL partition/filter logic works now that
``meta.experiment_date`` is stored as a BSON ``datetime`` rather than a string.
"""

import datetime

import pytest

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
