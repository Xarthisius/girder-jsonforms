import datetime

import pytest

from girder_jsonforms.lib.metadata_dates import (
    coerce_dates,
    coerce_metadata_dates,
    _parse_iso,
)


class TestParseIso:
    """Unit tests for the strict ISO-8601 detector/parser (no DB needed)."""

    def test_date_only_becomes_midnight_utc(self):
        parsed = _parse_iso("2023-10-01")
        assert parsed == datetime.datetime(
            2023, 10, 1, 0, 0, tzinfo=datetime.timezone.utc
        )

    def test_datetime_with_z(self):
        parsed = _parse_iso("2023-10-01T12:30:00Z")
        assert parsed == datetime.datetime(
            2023, 10, 1, 12, 30, tzinfo=datetime.timezone.utc
        )

    def test_naive_datetime_assumed_utc(self):
        parsed = _parse_iso("2023-10-01T12:30:00")
        assert parsed.tzinfo == datetime.timezone.utc
        assert parsed.hour == 12

    def test_offset_converted_to_utc(self):
        parsed = _parse_iso("2023-10-01T12:00:00+02:00")
        assert parsed == datetime.datetime(
            2023, 10, 1, 10, 0, tzinfo=datetime.timezone.utc
        )

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "12",
            "12345",
            "2.0",
            "1.2.3",
            "March",
            "not a date",
            "2023",  # year only -> not a full date
            "2023-10",  # missing day
            "20231001",  # no separators (ambiguous, deliberately not matched)
            "hello 2023-10-01 world",  # fuzzy match must not fire
        ],
    )
    def test_non_dates_are_rejected(self, value):
        assert _parse_iso(value) is None

    def test_invalid_calendar_date_rejected(self):
        # Matches the regex shape but is not a real date.
        assert _parse_iso("2023-13-45") is None


class TestCoerce:
    """The recursive coercion used by the event handler."""

    def test_nested_structure(self):
        result = coerce_dates(
            {
                "collected": "2023-10-01T00:00:00Z",
                "label": "sample-42",  # left untouched
                "count": 5,
                "history": ["2020-01-01", "not-a-date"],
                "nested": {"born": "1999-12-31"},
            }
        )
        assert result["collected"] == datetime.datetime(
            2023, 10, 1, tzinfo=datetime.timezone.utc
        )
        assert result["label"] == "sample-42"
        assert result["count"] == 5
        assert result["history"][0] == datetime.datetime(
            2020, 1, 1, tzinfo=datetime.timezone.utc
        )
        assert result["history"][1] == "not-a-date"
        assert result["nested"]["born"] == datetime.datetime(
            1999, 12, 31, tzinfo=datetime.timezone.utc
        )

    def test_idempotent(self):
        once = coerce_dates({"d": "2023-10-01"})
        twice = coerce_dates(once)
        assert twice == once
        assert isinstance(twice["d"], datetime.datetime)

    def test_handler_ignores_missing_meta(self):
        class _Event:
            info = {"name": "no meta here"}

        event = _Event()
        coerce_metadata_dates(event)  # must not raise
        assert "meta" not in event.info

    def test_query_operators_preserved(self):
        # Same helper is used to coerce _item_advanced_search queries: operator
        # keys must survive, only the (date) values are coerced.
        query = coerce_dates(
            {
                "meta.collected": {"$gte": "2023-01-01", "$lt": "2024-01-01"},
                "meta.tag": "v1.2.3",
            }
        )
        assert query["meta.collected"]["$gte"] == datetime.datetime(
            2023, 1, 1, tzinfo=datetime.timezone.utc
        )
        assert query["meta.collected"]["$lt"] == datetime.datetime(
            2024, 1, 1, tzinfo=datetime.timezone.utc
        )
        assert query["meta.tag"] == "v1.2.3"


@pytest.mark.plugin("jsonforms")
class TestMetadataDatesIntegration:
    """End-to-end: dates set via setMetadata are stored as BSON datetimes."""

    def _make_folder(self, admin):
        from girder.models.collection import Collection
        from girder.models.folder import Folder

        collection = Collection().createCollection("Dates Collection", admin)
        folder = Folder().createFolder(
            collection, "Dates Folder", parentType="collection", creator=admin
        )
        return collection, folder

    def test_folder_metadata_coerced(self, server, admin):
        from girder.models.collection import Collection
        from girder.models.folder import Folder

        collection, folder = self._make_folder(admin)
        try:
            folder = Folder().setMetadata(
                folder, {"collected": "2023-10-01T12:00:00Z", "note": "v1.2.3"}
            )
            # Re-read raw from Mongo to confirm the stored BSON type.
            raw = Folder().collection.find_one({"_id": folder["_id"]})
            assert isinstance(raw["meta"]["collected"], datetime.datetime)
            assert raw["meta"]["note"] == "v1.2.3"
        finally:
            Folder().remove(folder)
            Collection().remove(collection)

    def test_item_metadata_coerced(self, server, admin):
        from girder.models.collection import Collection
        from girder.models.item import Item

        collection, folder = self._make_folder(admin)
        try:
            item = Item().createItem("dates-item", admin, folder)
            item = Item().setMetadata(item, {"born": "1999-12-31"})
            raw = Item().collection.find_one({"_id": item["_id"]})
            stored = raw["meta"]["born"]
            assert isinstance(stored, datetime.datetime)
            assert stored.year == 1999 and stored.month == 12 and stored.day == 31
        finally:
            from girder.models.folder import Folder

            Folder().remove(folder)
            Collection().remove(collection)


@pytest.mark.plugin("jsonforms")
class TestMigration:
    """The back-fill migration for pre-existing string dates."""

    def _fixtures(self, admin):
        from girder.models.collection import Collection
        from girder.models.folder import Folder
        from girder.models.item import Item

        collection = Collection().createCollection("Migration Collection", admin)
        folder = Folder().createFolder(
            collection, "Migration Folder", parentType="collection", creator=admin
        )
        item = Item().createItem("migration-item", admin, folder)
        # Write a legacy string date directly, bypassing the save-time handler.
        Item().collection.update_one(
            {"_id": item["_id"]},
            {"$set": {"meta": {"collected": "2021-05-06T00:00:00Z", "note": "v1"}}},
        )
        return collection, folder, item

    def _cleanup(self, collection, folder, item):
        from girder.models.collection import Collection
        from girder.models.folder import Folder
        from girder.models.item import Item

        Item().remove(item)
        Folder().remove(folder)
        Collection().remove(collection)

    def test_migrates_string_dates(self, server, admin):
        from girder.models.item import Item
        from girder_jsonforms.scripts.migrate_metadata_dates import _migrate_model

        collection, folder, item = self._fixtures(admin)
        try:
            scanned, changed = _migrate_model(Item(), dry_run=False, batch_size=100)
            assert scanned >= 1 and changed >= 1
            raw = Item().collection.find_one({"_id": item["_id"]})
            assert isinstance(raw["meta"]["collected"], datetime.datetime)
            assert raw["meta"]["note"] == "v1"
        finally:
            self._cleanup(collection, folder, item)

    def test_dry_run_makes_no_changes(self, server, admin):
        from girder.models.item import Item
        from girder_jsonforms.scripts.migrate_metadata_dates import _migrate_model

        collection, folder, item = self._fixtures(admin)
        try:
            _migrate_model(Item(), dry_run=True, batch_size=100)
            raw = Item().collection.find_one({"_id": item["_id"]})
            assert raw["meta"]["collected"] == "2021-05-06T00:00:00Z"
        finally:
            self._cleanup(collection, folder, item)
