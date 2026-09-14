"""Remote (centralized) IGSN allocation.

Two tests here carry the migration's guarantees:

* ``TestLocalModeUnchanged`` -- with ``jsonforms.igsn_service_url`` unset,
  nothing about the existing behavior changes.
* ``test_no_local_counter_is_written`` -- with it set, this instance stops
  keeping its own sequence counter entirely. A counter still ticking locally
  would mean two instances could still diverge.

Fixtures live in ``conftest.py``.
"""

from unittest.mock import MagicMock, patch

import pytest
from girder.exceptions import ValidationException
from girder.models.setting import Setting

from ..lib import igsn_vocab
from ..lib.igsn_client import IGSNClient, IGSNServiceError, get_client, is_remote
from ..models.deposition import Deposition, PrefixCounter
from ..settings import PluginSettings
from .conftest import IGSN_SERVICE_URL, igsn_record


@pytest.fixture(autouse=True)
def _eager_tasks(eagerWorkerTasks):
    """Run celery tasks inline.

    Not because this module loads the plugin -- it doesn't -- but because a
    sibling module may already have, in which case creating a deposition fires
    ``deposition.created`` and its handler dispatches to a broker that isn't
    running. Without this the module passes alone and fails in a full run.
    """


# --------------------------------------------------------------------------- #


class TestClientConfiguration:
    def test_local_by_default(self, local_mode):
        assert is_remote() is False
        assert get_client() is None

    def test_remote_when_url_is_set(self, remote_mode):
        assert is_remote() is True
        client = get_client()
        assert isinstance(client, IGSNClient)
        assert client.base_url == IGSN_SERVICE_URL

    def test_url_without_token_raises_rather_than_falling_back(self, igsn_settings):
        """Silently reverting to local counters is the failure we're removing."""
        Setting().set(PluginSettings.IGSN_SERVICE_URL, IGSN_SERVICE_URL)
        Setting().unset(PluginSettings.IGSN_SERVICE_TOKEN)
        try:
            with pytest.raises(IGSNServiceError, match="is empty"):
                get_client()
        finally:
            Setting().unset(PluginSettings.IGSN_SERVICE_URL)

    def test_url_is_validated_and_normalized(self, db):
        with pytest.raises(Exception, match="http"):
            Setting().set(PluginSettings.IGSN_SERVICE_URL, "igsn.example.org")
        Setting().set(PluginSettings.IGSN_SERVICE_URL, "https://igsn.example.org/")
        assert Setting().get(PluginSettings.IGSN_SERVICE_URL) == "https://igsn.example.org"
        Setting().unset(PluginSettings.IGSN_SERVICE_URL)

    def test_allocating_posts_are_never_auto_retried(self, remote_mode):
        """A retried allocation would burn another block of sequence numbers."""
        client = get_client()
        adapter = client._session.get_adapter(IGSN_SERVICE_URL)
        assert "POST" not in adapter.max_retries.allowed_methods
        assert "GET" in adapter.max_retries.allowed_methods


class TestLocalModeUnchanged:
    """The no-disruption gate: local mode must behave exactly as before."""

    def test_counter_allocates_locally(self, local_mode):
        assert PrefixCounter().get_next("ABCDEF") == "ABCDEF00001"
        assert PrefixCounter().get_next("ABCDEF") == "ABCDEF00002"

    def test_counter_document_is_written(self, local_mode):
        PrefixCounter().get_next("ABCDEF")
        counter = PrefixCounter().findOne({"prefix": "ABCDEF"})
        assert counter["seq"] == 1

    def test_invalid_prefix_still_rejected_with_the_same_messages(self, local_mode):
        for prefix, message in [
            ("foo", "Prefix must be 6 characters long"),
            ("ZZCDEF", "Invalid institution ZZ"),
            ("ABZDEF", "Invalid subinstitution Z"),
            ("ABCZZZ", "Invalid material ZZ"),
            ("ABCDEZ", "Invalid submaterial Z"),
        ]:
            with pytest.raises(ValidationException) as excinfo:
                PrefixCounter().get_next(prefix)
            assert str(excinfo.value) == message

    def test_vocabularies_come_from_settings(self, local_mode, igsn_settings):
        institutions, materials = igsn_settings
        assert igsn_vocab.get_vocabularies() == {
            "institutions": institutions,
            "materials": materials,
        }

    def test_deposition_shape_is_unchanged(self, local_mode, admin, igsn_metadata):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        assert deposition["igsn"] == "ABCDEF00001"
        assert deposition["state"] == "draft"
        assert deposition["submitted"] is False
        # No registry mirror fields in local mode.
        assert "serviceStatus" not in deposition

    def test_increment_is_not_a_compare_and_swap(self, local_mode):
        """The old implementation filtered on the whole document.

        A concurrent increment then made find_one_and_update return None and
        get_next raised TypeError. Simulate the interleaving directly.
        """
        counter = PrefixCounter().get_counter("ABCDEF")
        PrefixCounter().increment(counter)  # someone else bumps it
        # `counter` is now stale; incrementing with it must still work.
        bumped = PrefixCounter().increment(counter)
        assert bumped is not None
        assert bumped["seq"] == 2


class TestRemoteAllocation:
    def test_get_next_uses_the_service(self, remote_mode, igsn_service):
        assert PrefixCounter().get_next("ABCDEF") == "ABCDEF00001"
        igsn_service.allocate.assert_called_once_with("ABCDEF", count=1)

    def test_no_local_counter_is_written(self, remote_mode, igsn_service):
        """The point of the exercise: this instance keeps no counter of its own."""
        PrefixCounter().get_next("ABCDEF")
        PrefixCounter().get_next("ABCDEF")
        assert PrefixCounter().find({}).count() == 0

    def test_get_next_many_allocates_a_block_in_one_call(self, remote_mode, igsn_service):
        igsns = PrefixCounter().get_next_many("ABCDEF", 3)
        assert igsns == ["ABCDEF00001", "ABCDEF00002", "ABCDEF00003"]
        igsn_service.allocate.assert_called_once_with("ABCDEF", count=3)

    def test_service_failure_is_fatal_not_a_local_fallback(self, remote_mode):
        """Falling back locally would recreate the divergence being removed."""
        broken = MagicMock(spec=IGSNClient)
        broken.allocate.side_effect = IGSNServiceError("service down")
        with patch(
            "girder_jsonforms.models.deposition.get_client", return_value=broken
        ):
            with pytest.raises(IGSNServiceError):
                PrefixCounter().get_next("ABCDEF")
        assert PrefixCounter().find({}).count() == 0

    def test_create_deposition_pushes_metadata_and_landing_page(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        from girder.settings import SettingKey

        Setting().set(SettingKey.SERVER_ROOT, "https://girder.example.org")
        try:
            deposition = Deposition().create_deposition(
                igsn_metadata, admin, prefix="ABCDEF"
            )
        finally:
            Setting().unset(SettingKey.SERVER_ROOT)
        assert deposition["igsn"] == "ABCDEF00001"
        igsn_service.put_record.assert_called_once()
        kwargs = igsn_service.put_record.call_args.kwargs
        assert kwargs["landing_page"] == (
            "https://girder.example.org/#igsn/ABCDEF00001"
        )
        assert kwargs["metadata"]["titles"] == [{"title": "Remote Sample"}]

    def test_prefix_is_not_validated_locally_in_remote_mode(
        self, remote_mode, igsn_service
    ):
        """The registry owns the vocabularies; it validates on allocation."""
        assert PrefixCounter().get_next("XYZXYZ") == "XYZXYZ00001"


class TestRemoteBatches:
    def test_children_are_registered_centrally_before_local_insert(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        main = Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        Deposition().create_batch(main, [("001", None), ("002", None)])

        igsn_service.allocate_children.assert_called_once()
        args, kwargs = igsn_service.allocate_children.call_args
        assert args[0] == "ABCDEF00001"
        assert kwargs["indices"] == ["001", "002"]
        assert Deposition().find({"parentId": main["_id"]}).count() == 2

    def test_local_identifiers_are_forwarded(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        main = Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        Deposition().create_batch(main, [("001", "BUILD-001"), ("002", None)])
        kwargs = igsn_service.allocate_children.call_args.kwargs
        assert kwargs["local_identifiers"] == {"001": "BUILD-001"}

    def test_lab_specific_index_labels_are_forwarded(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        main = Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        Deposition().create_batch(main, [("S1R0C0", None), ("S1R0C1", None)])
        assert igsn_service.allocate_children.call_args.kwargs["indices"] == [
            "S1R0C0",
            "S1R0C1",
        ]

    def test_registry_rejection_prevents_any_local_children(
        self, remote_mode, admin, igsn_metadata, igsn_service
    ):
        """Girder must never hold children the registry has not heard of."""
        main = Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        igsn_service.allocate_children.side_effect = IGSNServiceError(
            "already exist", status_code=409
        )
        with pytest.raises(IGSNServiceError):
            Deposition().create_batch(main, [("001", None), ("002", None)])
        assert Deposition().find({"parentId": main["_id"]}).count() == 0

    def test_already_registered_skips_a_second_allocation(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        main = Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        Deposition().create_batch(
            main, [("001", None)], already_registered=True
        )
        igsn_service.allocate_children.assert_not_called()
        assert Deposition().find({"parentId": main["_id"]}).count() == 1

    def test_child_indices_come_from_the_registry(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        """Not from a local max-scan, which is wrong across instances."""
        from ..rest.deposition import next_batch_indices

        main = Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        assert next_batch_indices(main, 2) == ["001", "002"]
        igsn_service.allocate_children.assert_called_once_with(
            "ABCDEF00001", count=2
        )

    def test_local_mode_child_indices_still_scan_locally(
        self, local_mode, admin, igsn_metadata
    ):
        from ..rest.deposition import next_batch_indices

        main = Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        Deposition().create_batch(main, [("001", None), ("002", None)])
        assert next_batch_indices(main, 2) == ["003", "004"]


class TestRemoteVocabularies:
    def test_vocabularies_come_from_the_service(self, remote_mode, igsn_service):
        vocabularies = igsn_vocab.get_vocabularies()
        assert vocabularies["institutions"]["AB"]["name"] == "Remote Inst"
        igsn_service.vocabularies.assert_called_once()

    def test_result_is_cached(self, remote_mode, igsn_service):
        igsn_vocab.get_vocabularies()
        igsn_vocab.get_vocabularies()
        assert igsn_service.vocabularies.call_count == 1

    def test_service_failure_falls_back_to_settings(
        self, remote_mode, igsn_settings
    ):
        """A stale vocabulary beats rejecting prefixes that are actually valid."""
        institutions, _ = igsn_settings
        broken = MagicMock(spec=IGSNClient)
        broken.vocabularies.side_effect = IGSNServiceError("down")
        with patch(
            "girder_jsonforms.lib.igsn_vocab.get_client", return_value=broken
        ):
            vocabularies = igsn_vocab.get_vocabularies()
        assert vocabularies["institutions"] == institutions


class TestMirroredState:
    def test_findable_marks_the_deposition_published(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        Deposition().apply_registry_state(
            deposition["_id"],
            igsn_record(deposition["igsn"], status="findable", published_at=None),
        )
        refreshed = Deposition().load(deposition["_id"], force=True)
        assert refreshed["serviceStatus"] == "findable"
        assert refreshed["state"] == "published"
        assert refreshed["submitted"] is True

    def test_reserved_stays_draft(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        Deposition().apply_registry_state(
            deposition["_id"], igsn_record(deposition["igsn"], status="reserved")
        )
        refreshed = Deposition().load(deposition["_id"], force=True)
        assert refreshed["state"] == "draft"
        assert refreshed["submitted"] is False

    def test_service_error_is_recorded_not_swallowed(
        self, remote_mode, admin, igsn_metadata, igsn_service
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        broken = MagicMock(spec=IGSNClient)
        broken.put_record.side_effect = IGSNServiceError("down")
        with patch(
            "girder_jsonforms.models.deposition.get_client", return_value=broken
        ):
            assert Deposition().sync_to_registry(deposition) is None
        refreshed = Deposition().load(deposition["_id"], force=True)
        assert refreshed["serviceError"] == "metadata sync failed"


class TestLandingPage:
    """Girder must not hand the registry a relative URL.

    ``core.server_root`` is unset on plenty of instances, and the old
    ``os.path.join(server_root, "#igsn", igsn)`` produced ``"#igsn/IGSN"`` when
    it was empty. Harmless while nothing published; once publication was
    automated DataCite answered 422 "URL is not valid".
    """

    def test_absolute_server_root_produces_a_real_url(self, local_mode):
        from girder.settings import SettingKey

        Setting().set(SettingKey.SERVER_ROOT, "https://girder.example.org")
        try:
            assert Deposition().landing_page("ABCDEF00001") == (
                "https://girder.example.org/#igsn/ABCDEF00001"
            )
        finally:
            Setting().unset(SettingKey.SERVER_ROOT)

    def test_trailing_slash_does_not_double_up(self, local_mode):
        from girder.settings import SettingKey

        Setting().set(SettingKey.SERVER_ROOT, "https://girder.example.org/")
        try:
            assert Deposition().landing_page("ABCDEF00001") == (
                "https://girder.example.org/#igsn/ABCDEF00001"
            )
        finally:
            Setting().unset(SettingKey.SERVER_ROOT)

    def test_unset_server_root_yields_none_not_a_fragment(self, local_mode):
        """The bug: an empty server root used to yield '#igsn/ABCDEF00001'."""
        assert Deposition().landing_page("ABCDEF00001") is None

    @pytest.mark.parametrize("stored", ["/girder", "girder.example.org", "  ", None])
    def test_non_absolute_server_root_yields_none(self, local_mode, stored):
        """Girder core rejects these via Setting(), but a direct Mongo write or a
        future default change would not, and the fragment bug came from exactly
        this shape."""
        with patch.object(Setting, "get", return_value=stored):
            assert Deposition().landing_page("ABCDEF00001") is None

    def test_deposition_metadata_omits_url_when_there_is_no_address(
        self, local_mode, admin, igsn_metadata
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        # Better absent than present-and-invalid: the registry's own resolver
        # becomes the landing page, which is the designed fallback.
        assert "url" not in deposition["metadata"]
        assert deposition["metadata"]["doi"]

    def test_batch_children_also_omit_url(self, local_mode, admin, igsn_metadata):
        main = Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        Deposition().create_batch(main, [("001", None)])
        child = Deposition().findOne({"igsn": "ABCDEF00001-001"})
        assert "url" not in child["metadata"]

    def test_batch_children_get_a_url_when_there_is_one(
        self, local_mode, admin, igsn_metadata
    ):
        from girder.settings import SettingKey

        Setting().set(SettingKey.SERVER_ROOT, "https://girder.example.org")
        try:
            main = Deposition().create_deposition(
                igsn_metadata, admin, prefix="ABCDEF"
            )
            Deposition().create_batch(main, [("001", None)])
            child = Deposition().findOne({"igsn": "ABCDEF00001-001"})
            assert child["metadata"]["url"] == (
                "https://girder.example.org/#igsn/ABCDEF00001-001"
            )
        finally:
            Setting().unset(SettingKey.SERVER_ROOT)

    def test_nothing_relative_is_pushed_to_the_registry(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        """The end of the chain that produced the 422."""
        Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        landing_page = igsn_service.put_record.call_args.kwargs["landing_page"]
        assert landing_page is None

    def test_an_absolute_root_is_pushed_through(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        from girder.settings import SettingKey

        Setting().set(SettingKey.SERVER_ROOT, "https://girder.example.org")
        try:
            Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
            assert igsn_service.put_record.call_args.kwargs["landing_page"] == (
                "https://girder.example.org/#igsn/ABCDEF00001"
            )
        finally:
            Setting().unset(SettingKey.SERVER_ROOT)


class TestChildrenAreMirrored:
    """Batch children must carry the registry's view, like their parent.

    They did not: ``create_batch`` builds child documents inline and
    ``insert_many``s them, so nothing set ``serviceStatus``. Anything keyed off
    that field -- notably the web client's Publish action -- then treated every
    split/batch child as if the registry had never heard of it, even though the
    registry held them with complete metadata and they were publishable.
    """

    def test_children_get_a_service_status(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        main = Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        Deposition().create_batch(main, [("001", None), ("002", None)])
        for igsn in ("ABCDEF00001-001", "ABCDEF00001-002"):
            child = Deposition().findOne({"igsn": igsn})
            assert child["serviceStatus"] == "reserved", igsn

    def test_children_are_exposed_with_it(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        main = Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        Deposition().create_batch(main, [("001", None)])
        child = Deposition().findOne({"igsn": "ABCDEF00001-001"})
        assert "serviceStatus" in Deposition().filter(child, user=admin)

    def test_pre_registered_children_are_mirrored_too(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        """The split endpoint registers indices itself, then passes
        already_registered=True; those children still need the mirror."""
        main = Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        Deposition().create_batch(main, [("001", None)], already_registered=True)
        child = Deposition().findOne({"igsn": "ABCDEF00001-001"})
        assert child["serviceStatus"] == "reserved"

    def test_local_mode_children_have_no_status(
        self, local_mode, admin, igsn_metadata
    ):
        main = Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        Deposition().create_batch(main, [("001", None)])
        child = Deposition().findOne({"igsn": "ABCDEF00001-001"})
        assert "serviceStatus" not in child


class TestParentMetadataAlwaysReachesTheRegistry:
    """A supplied IGSN must not skip the metadata push.

    register_deposition -- the form-entry path, and how most IGSNs are minted --
    allocates the identifier itself and passes it into create_deposition. Keying
    the push off "did this call allocate?" meant that path never sent metadata:
    the registry kept a bare doi/url, and batch children derived from it
    inherited nothing publishable.
    """

    def test_supplied_igsn_still_pushes_metadata(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        igsn = PrefixCounter().get_next("ABCDEF")
        igsn_service.put_record.reset_mock()
        Deposition().create_deposition(igsn_metadata, admin, igsn=igsn)
        igsn_service.put_record.assert_called_once()
        assert igsn_service.put_record.call_args.kwargs["metadata"]["titles"] == [
            {"title": "Remote Sample"}
        ]

    def test_parent_gets_a_service_status_at_creation(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        assert deposition["serviceStatus"] == "reserved"

    def test_an_igsn_the_registry_lacks_is_logged_not_fatal(
        self, remote_mode, igsn_service, admin, igsn_metadata, caplog
    ):
        """Girder holding an unknown identifier is a real problem, but refusing
        the local record would lose the data; reconcile reports it instead."""
        igsn_service.put_record.side_effect = IGSNServiceError(
            "no such record", status_code=404
        )
        with caplog.at_level("ERROR"):
            deposition = Deposition().create_deposition(
                igsn_metadata, admin, igsn="ABCDEF09999"
            )
        assert deposition["igsn"] == "ABCDEF09999"
        assert "not in the IGSN registry" in caplog.text

    def test_other_service_errors_still_fail_loudly(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        igsn_service.put_record.side_effect = IGSNServiceError(
            "service down", status_code=503
        )
        with pytest.raises(IGSNServiceError):
            Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")

    def test_local_mode_pushes_nothing(self, local_mode, admin, igsn_metadata):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        assert "serviceStatus" not in deposition

class TestOnlyPublicMetadataIsPublished:
    """A DataCite record is world readable, so only the public projection may go.

    ``relatedIdentifiers`` of type ``HasMetadata`` point at form entries, which
    carry their own ACLs -- ``Deposition.filter`` drops the ones a reader cannot
    see. Publication used the *raw* document, so a private entry's URL would
    have been published to DataCite.

    Entry lookups need the plugin's model registry, so the cases that turn on a
    real entry's ACL live in test_igsn_service_rest.py. What is checked here is
    that the registry never receives an identifier the filter rejected.
    """

    @pytest.fixture
    def unresolvable_identifier(self):
        """An entry link that resolves for nobody.

        The filter drops these, which is the fail-safe direction: an entry the
        service cannot verify is not published.
        """
        return {
            "relationType": "HasMetadata",
            "relatedIdentifier": "/api/v1/entry/6a8cba71d512f2658f11d50a",
            "relatedIdentifierType": "URL",
        }

    @pytest.fixture
    def public_identifier(self):
        return {
            "relationType": "IsPartOf",
            "relatedIdentifier": "ABCDEF00001",
            "relatedIdentifierType": "IGSN",
        }

    def test_unresolvable_entry_links_are_dropped(
        self, local_mode, unresolvable_identifier, public_identifier
    ):
        metadata = {
            "relatedIdentifiers": [public_identifier, unresolvable_identifier]
        }
        assert Deposition().public_metadata(metadata)["relatedIdentifiers"] == [
            public_identifier
        ]

    def test_non_entry_identifiers_survive(self, local_mode):
        """Only entry links are ACL-checked; a plain URL is not."""
        metadata = {
            "relatedIdentifiers": [
                {
                    "relationType": "HasMetadata",
                    "relatedIdentifier": "https://example.org/paper",
                    "relatedIdentifierType": "URL",
                }
            ]
        }
        assert len(Deposition().public_metadata(metadata)["relatedIdentifiers"]) == 1

    def test_other_metadata_is_untouched(self, local_mode, igsn_metadata):
        public = Deposition().public_metadata(igsn_metadata)
        assert public["titles"] == igsn_metadata["titles"]
        assert public["creators"] == igsn_metadata["creators"]
        assert public["alternateIdentifiers"] == igsn_metadata["alternateIdentifiers"]

    def test_filtering_does_not_mutate_the_input(
        self, local_mode, unresolvable_identifier, public_identifier
    ):
        """super().filter() copies field-by-field, so `metadata` was shared.

        Editing it in place meant filtering for one reader stripped identifiers
        out of the document every other caller was holding.
        """
        metadata = {
            "relatedIdentifiers": [public_identifier, unresolvable_identifier]
        }
        Deposition().public_metadata(metadata)
        assert metadata["relatedIdentifiers"] == [
            public_identifier,
            unresolvable_identifier,
        ]

    def test_filter_does_not_mutate_the_deposition(
        self, local_mode, admin, igsn_metadata, unresolvable_identifier
    ):
        igsn_metadata["relatedIdentifiers"] = [unresolvable_identifier]
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        Deposition().filter(deposition, user=None)
        # The caller's document still has it; only the returned copy is filtered.
        assert deposition["metadata"]["relatedIdentifiers"] == [
            unresolvable_identifier
        ]

    def test_creation_pushes_only_public_metadata(
        self, remote_mode, igsn_service, admin, igsn_metadata, unresolvable_identifier
    ):
        igsn_metadata["relatedIdentifiers"] = [unresolvable_identifier]
        Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        pushed = igsn_service.put_record.call_args.kwargs["metadata"]
        assert pushed["relatedIdentifiers"] == []

    def test_sync_pushes_only_public_metadata(
        self, remote_mode, igsn_service, admin, igsn_metadata, unresolvable_identifier
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        # Relations are added by raw collection writes after creation, which is
        # exactly where they come from in practice.
        Deposition().collection.update_one(
            {"_id": deposition["_id"]},
            {"$addToSet": {"metadata.relatedIdentifiers": unresolvable_identifier}},
        )
        deposition = Deposition().load(deposition["_id"], force=True)
        assert unresolvable_identifier in deposition["metadata"]["relatedIdentifiers"]

        igsn_service.put_record.reset_mock()
        Deposition().sync_to_registry(deposition)
        pushed = igsn_service.put_record.call_args.kwargs["metadata"]
        assert unresolvable_identifier not in pushed["relatedIdentifiers"]

    def test_the_local_record_keeps_everything(
        self, remote_mode, igsn_service, admin, igsn_metadata, unresolvable_identifier
    ):
        """Girder is not the thing being published; it keeps the full picture."""
        igsn_metadata["relatedIdentifiers"] = [unresolvable_identifier]
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        stored = Deposition().load(deposition["_id"], force=True)
        assert unresolvable_identifier in stored["metadata"]["relatedIdentifiers"]


class TestPublishRequiresPublic:
    """A DOI is world readable, so the record must be public *first*.

    Publication must not be the act that makes something public, and must not
    quietly flip the flag: whoever publishes has to have made that call
    deliberately.
    """

    def test_a_private_deposition_is_refused(self, local_mode, admin, igsn_metadata):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=False
        )
        with pytest.raises(ValidationException, match="not public"):
            Deposition().require_publishable(deposition)

    def test_a_public_deposition_is_allowed(self, local_mode, admin, igsn_metadata):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=True
        )
        assert Deposition().require_publishable(deposition) is None

    def test_the_message_names_the_record_and_says_what_to_do(
        self, local_mode, admin, igsn_metadata
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=False
        )
        with pytest.raises(ValidationException) as excinfo:
            Deposition().require_publishable(deposition)
        message = str(excinfo.value)
        assert "ABCDEF00001" in message
        assert "will not do it for you" in message

    def test_nothing_flips_the_flag(self, local_mode, admin, igsn_metadata):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=False
        )
        with pytest.raises(ValidationException):
            Deposition().require_publishable(deposition)
        assert Deposition().load(deposition["_id"], force=True)["public"] is False

    def test_a_private_child_blocks_a_recursive_publish(
        self, local_mode, admin, igsn_metadata
    ):
        """The registry publishes a batch as one unit, so a public parent must
        not carry private children into DataCite."""
        main = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=True
        )
        Deposition().create_batch(main, [("001", None)])
        Deposition().collection.update_one(
            {"igsn": "ABCDEF00001-001"}, {"$set": {"public": False}}
        )
        with pytest.raises(ValidationException, match="ABCDEF00001-001"):
            Deposition().require_publishable(main, recurse=True)

    def test_a_private_child_does_not_block_a_non_recursive_publish(
        self, local_mode, admin, igsn_metadata
    ):
        main = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=True
        )
        Deposition().create_batch(main, [("001", None)])
        Deposition().collection.update_one(
            {"igsn": "ABCDEF00001-001"}, {"$set": {"public": False}}
        )
        assert Deposition().require_publishable(main, recurse=False) is None

    def test_public_children_pass(self, local_mode, admin, igsn_metadata):
        """Children inherit the parent's public flag, so this is the normal case."""
        main = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=True
        )
        Deposition().create_batch(main, [("001", None), ("002", None)])
        assert Deposition().require_publishable(main, recurse=True) is None

    def test_many_private_children_are_summarized(
        self, local_mode, admin, igsn_metadata
    ):
        main = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=True
        )
        Deposition().create_batch(main, [(f"{n:03d}", None) for n in range(1, 16)])
        Deposition().collection.update_many(
            {"parentId": main["_id"]}, {"$set": {"public": False}}
        )
        with pytest.raises(ValidationException) as excinfo:
            Deposition().require_publishable(main, recurse=True)
        assert "and 5 more" in str(excinfo.value)


class TestPublishTaskRequiresPublic:
    """Enforced in the task too: it is reachable without going through REST."""

    def test_task_refuses_a_private_deposition(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        from ..worker_plugin.igsn_registry import publish_deposition

        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=False
        )
        with patch(
            "girder_jsonforms.worker_plugin.igsn_registry.get_client",
            return_value=igsn_service,
        ):
            with pytest.raises(ValidationException, match="not public"):
                publish_deposition(str(deposition["_id"]))
        igsn_service.publish.assert_not_called()

    def test_task_publishes_a_public_deposition(
        self, remote_mode, igsn_service, admin, igsn_metadata
    ):
        from ..worker_plugin.igsn_registry import publish_deposition

        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=True
        )
        with patch(
            "girder_jsonforms.worker_plugin.igsn_registry.get_client",
            return_value=igsn_service,
        ), patch(
            "girder_jsonforms.models.deposition.get_client", return_value=igsn_service
        ):
            publish_deposition(str(deposition["_id"]))
        igsn_service.publish.assert_called_once()

    def test_sync_is_exempt(self, remote_mode, igsn_service, admin, igsn_metadata):
        """Pushing metadata is reversible and sends only the public projection,
        so it is not gated on the record being public."""
        from ..worker_plugin.igsn_registry import publish_deposition

        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=False
        )
        igsn_service.put_record.reset_mock()
        with patch(
            "girder_jsonforms.worker_plugin.igsn_registry.get_client",
            return_value=igsn_service,
        ), patch(
            "girder_jsonforms.models.deposition.get_client", return_value=igsn_service
        ):
            publish_deposition(str(deposition["_id"]), metadata_only=True)
        igsn_service.put_record.assert_called_once()
        igsn_service.publish.assert_not_called()
