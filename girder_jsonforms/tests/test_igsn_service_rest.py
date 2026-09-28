"""REST-level tests for centralized IGSN handling.

Kept separate from ``test_igsn_service.py``: pytest-girder loads plugins into a
process-global CherryPy app for the ``server`` fixture, and mixing server-backed
tests with plain model-level ones in a single module leaves later tests tripping
over that state.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from pytest_girder.assertions import assertStatus, assertStatusOk

from ..lib.igsn_client import IGSNServiceError
from ..models.deposition import Deposition
from ..settings import PluginSettings
from .conftest import IGSN_SERVICE_TOKEN, igsn_record

pytestmark = [
    pytest.mark.plugin("sample_tracker"),
    pytest.mark.plugin("wholetale"),
    pytest.mark.plugin("jsonforms"),
]


@pytest.fixture(autouse=True)
def _eager_tasks(eagerWorkerTasks):
    """Run celery tasks inline.

    With the plugin loaded, creating a deposition fires ``deposition.created``,
    whose handler dispatches a girder-worker task -- and there is no broker in
    the test environment.
    """


class TestSecrets:
    def test_token_is_not_a_public_setting(self, remote_mode, server, admin):
        """The service token must never reach the browser."""
        response = server.request(path="/system/public_settings", method="GET")
        assertStatusOk(response)
        assert IGSN_SERVICE_TOKEN not in json.dumps(response.json)
        assert PluginSettings.IGSN_SERVICE_TOKEN not in response.json


class TestSettingsEndpoint:
    def test_serves_registry_vocabularies(self, remote_mode, igsn_service, server):
        """So the form dropdowns offer what the registry will actually accept."""
        response = server.request(path="/deposition/settings", method="GET")
        assertStatusOk(response)
        assert response.json["igsn_institutions"]["AB"]["name"] == "Remote Inst"

    def test_falls_back_to_local_settings(self, local_mode, server, igsn_settings):
        institutions, _ = igsn_settings
        response = server.request(path="/deposition/settings", method="GET")
        assertStatusOk(response)
        assert response.json["igsn_institutions"] == institutions


class TestMirroredStateApi:
    def test_mirror_fields_are_exposed(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        Deposition().apply_registry_state(
            deposition["_id"], igsn_record(deposition["igsn"], status="findable")
        )
        response = server.request(
            path=f"/deposition/{deposition['_id']}", method="GET", user=admin
        )
        assertStatusOk(response)
        assert response.json["serviceStatus"] == "findable"
        assert response.json["state"] == "published"


class TestPublishEndpoint:
    def test_requires_the_publish_access_flag(
        self, remote_mode, igsn_service, server, admin, user, igsn_metadata
    ):
        """Admin on the document is not enough: publishing a DOI is forever."""
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        Deposition().setUserAccess(deposition, user=user, level=2, save=True)
        response = server.request(
            path=f"/deposition/{deposition['_id']}/task",
            method="PUT",
            user=user,
            params={"action": "publish"},
        )
        assertStatus(response, 403)

    def test_refused_in_local_mode(self, local_mode, server, admin, igsn_metadata):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        response = server.request(
            path=f"/deposition/{deposition['_id']}/task",
            method="PUT",
            user=admin,
            params={"action": "publish"},
        )
        assertStatus(response, 400)
        assert "not configured" in response.json["message"]

    def test_unknown_action_is_rejected(
        self, local_mode, server, admin, igsn_metadata
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        response = server.request(
            path=f"/deposition/{deposition['_id']}/task",
            method="PUT",
            user=admin,
            params={"action": "nonsense"},
        )
        assertStatus(response, 400)


class TestPublishTask:
    """The task itself.

    Driven directly rather than through ``PUT /deposition/:id/task``: that
    endpoint returns ``task.job``, and celery's eager results -- which the tests
    have to use, there being no broker -- carry no job. The endpoint's own
    behavior (authorization, local-mode refusal) is covered above.
    """

    def test_publish_syncs_metadata_first_then_publishes(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        from ..worker_plugin.igsn_registry import publish_deposition

        # Public, because publishing a private record is refused outright.
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=True
        )
        igsn_service.put_record.reset_mock()

        with patch(
            "girder_jsonforms.worker_plugin.igsn_registry.get_client",
            return_value=igsn_service,
        ), patch(
            "girder_jsonforms.models.deposition.get_client", return_value=igsn_service
        ):
            publish_deposition(str(deposition["_id"]), target="findable", recurse=True)

        # Metadata goes first: publishing whatever the registry happened to hold
        # is how you publish a stale record.
        igsn_service.put_record.assert_called_once()
        igsn_service.publish.assert_called_once_with(
            "ABCDEF00001", target="findable", recurse=True
        )

    def test_sync_pushes_metadata_without_publishing(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        from ..worker_plugin.igsn_registry import publish_deposition

        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
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

    def test_is_a_noop_in_local_mode(
        self, local_mode, server, admin, igsn_metadata
    ):
        from ..worker_plugin.igsn_registry import publish_deposition

        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        assert publish_deposition(str(deposition["_id"])) is None


class TestDeleteRevokes:
    def test_delete_tombstones_the_identifier(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        response = server.request(
            path=f"/deposition/{deposition['_id']}", method="DELETE", user=admin
        )
        assertStatusOk(response)
        igsn_service.revoke.assert_called_once_with("ABCDEF00001")
        assert Deposition().load(deposition["_id"], force=True) is None

    def test_published_record_cannot_be_deleted(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        igsn_service.revoke.side_effect = IGSNServiceError("published", status_code=409)
        response = server.request(
            path=f"/deposition/{deposition['_id']}", method="DELETE", user=admin
        )
        assertStatus(response, 400)
        assert Deposition().load(deposition["_id"], force=True) is not None

    def test_unreachable_registry_does_not_block_the_delete(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        """Reconcile reports the orphan; a dead registry must not wedge Girder."""
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        igsn_service.revoke.side_effect = IGSNServiceError("unreachable")
        response = server.request(
            path=f"/deposition/{deposition['_id']}", method="DELETE", user=admin
        )
        assertStatusOk(response)
        assert Deposition().load(deposition["_id"], force=True) is None


class TestChildDepositionEndpoint:
    def test_batch_indices_come_from_the_registry(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        response = server.request(
            path=f"/deposition/{deposition['_id']}/split",
            method="POST",
            user=admin,
            params={"batch": 2},
        )
        assertStatusOk(response)
        # Asked once for the indices; not registered a second time by create_batch.
        igsn_service.allocate_children.assert_called_once_with(
            "ABCDEF00001", count=2
        )
        assert Deposition().find({"parentId": deposition["_id"]}).count() == 2

    def test_registry_rejection_surfaces_as_a_client_error(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        igsn_service.allocate_children.side_effect = IGSNServiceError(
            "already exist", status_code=409
        )
        response = server.request(
            path=f"/deposition/{deposition['_id']}/split",
            method="POST",
            user=admin,
            params={"suffix": "abc"},
        )
        assertStatus(response, 400)
        assert Deposition().find({"parentId": deposition["_id"]}).count() == 0


class TestRelationUpdateSyncs:
    def test_relation_change_queues_a_metadata_sync(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        """These writes bypass save(), so the push has to be explicit."""
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        igsn_service.put_record.reset_mock()

        queued = MagicMock()
        with patch(
            "girder_jsonforms.worker_plugin.igsn_registry.sync_depositions_metadata",
            queued,
        ), patch(
            "girder_jsonforms.worker_plugin.igsn_registry.get_client",
            return_value=igsn_service,
        ):
            Deposition().queue_registry_sync([deposition["_id"]])

        queued.delay.assert_called_once()
        assert queued.delay.call_args.args[0] == [str(deposition["_id"])]

    def test_no_sync_is_queued_in_local_mode(
        self, local_mode, server, admin, igsn_metadata
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        queued = MagicMock()
        with patch(
            "girder_jsonforms.worker_plugin.igsn_registry.sync_depositions_metadata",
            queued,
        ):
            Deposition().queue_registry_sync([deposition["_id"]])
        queued.delay.assert_not_called()


class TestReconcile:
    def test_mirrors_registry_status_onto_local_depositions(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        from ..worker_plugin.igsn_registry import reconcile

        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF"
        )
        igsn_service.get_record.side_effect = lambda igsn: igsn_record(
            igsn, status="findable"
        )
        with patch(
            "girder_jsonforms.worker_plugin.igsn_registry.get_client",
            return_value=igsn_service,
        ):
            summary = reconcile()

        assert summary["updated"] == 1
        refreshed = Deposition().load(deposition["_id"], force=True)
        assert refreshed["serviceStatus"] == "findable"
        assert refreshed["state"] == "published"

    def test_reports_depositions_the_registry_does_not_have(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        """Reported, never invented: guessing would risk a duplicate IGSN."""
        from ..worker_plugin.igsn_registry import reconcile

        Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        igsn_service.get_record.side_effect = lambda igsn: None
        with patch(
            "girder_jsonforms.worker_plugin.igsn_registry.get_client",
            return_value=igsn_service,
        ):
            summary = reconcile()
        assert summary == {
            "updated": 0,
            "unchanged": 0,
            "missing": 1,
            "errors": 0,
        }

    def test_is_a_noop_in_local_mode(self, local_mode, server, admin, igsn_metadata):
        from ..worker_plugin.igsn_registry import reconcile

        Deposition().create_deposition(igsn_metadata, admin, prefix="ABCDEF")
        assert reconcile() is None


class TestRegistryEnabledPublicSetting:
    """The web client gates the Publish action on this.

    It used to gate on the record's own serviceStatus, which hid publishing for
    every batch child (they carried none) and for any record that had not synced
    yet.
    """

    def test_true_in_remote_mode(self, remote_mode, server):
        response = server.request(path="/system/public_settings", method="GET")
        assertStatusOk(response)
        assert response.json["jsonforms.igsn_registry_enabled"] is True

    def test_false_in_local_mode(self, local_mode, server):
        response = server.request(path="/system/public_settings", method="GET")
        assertStatusOk(response)
        assert response.json["jsonforms.igsn_registry_enabled"] is False

    def test_neither_url_nor_token_is_published(self, remote_mode, server):
        response = server.request(path="/system/public_settings", method="GET")
        assertStatusOk(response)
        assert PluginSettings.IGSN_SERVICE_URL not in response.json
        assert PluginSettings.IGSN_SERVICE_TOKEN not in response.json
        assert IGSN_SERVICE_TOKEN not in json.dumps(response.json)


class TestChildDepositionIsPublishable:
    def test_a_split_child_can_be_published(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        """End to end for the reported problem: split, then publish the child."""
        from ..worker_plugin.igsn_registry import publish_deposition

        # Children inherit the parent's public flag, so one setting covers both.
        parent = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=True
        )
        response = server.request(
            path=f"/deposition/{parent['_id']}/split",
            method="POST",
            user=admin,
            params={"batch": 1},
        )
        assertStatusOk(response)
        child = Deposition().findOne({"parentId": parent["_id"]})
        # The mirror is what makes the UI offer publishing at all.
        assert child["serviceStatus"] == "reserved"

        igsn_service.publish.reset_mock()
        with patch(
            "girder_jsonforms.worker_plugin.igsn_registry.get_client",
            return_value=igsn_service,
        ), patch(
            "girder_jsonforms.models.deposition.get_client", return_value=igsn_service
        ):
            publish_deposition(str(child["_id"]), target="findable")
        igsn_service.publish.assert_called_once_with(
            child["igsn"], target="findable", recurse=False
        )


class TestOnlyPublicMetadataIsPublished:
    """Only the public components of an IGSN may reach DataCite.

    A ``HasMetadata`` related identifier points at a form entry, and entries are
    ``AccessControlMixin`` -- their ACL comes from the parent form. Fetching a
    deposition as admin and anonymously returns different
    ``metadata.relatedIdentifiers``, and it is the anonymous projection that is
    publishable: a DataCite record is world readable.

    Publication used the raw document, so a private entry's URL would have been
    published.
    """

    @staticmethod
    def _entry_link(admin, public):
        from ..models.entry import FormEntry
        from ..models.form import Form

        form = Form().create_form(
            name=f"Form public={public}",
            description="",
            schema={"type": "object", "properties": {"a": {"type": "string"}}},
            creator=admin,
            uniqueField="a",
        )
        Form().setPublic(form, public, save=True)
        entry = FormEntry().create_entry(form, {"a": "x"}, None, None, admin)
        return {
            "relationType": "HasMetadata",
            "relatedIdentifier": f"/api/v1/entry/{entry['_id']}",
            "relatedIdentifierType": "URL",
        }

    @pytest.fixture
    def public_link(self, admin, db):
        return self._entry_link(admin, True)

    @pytest.fixture
    def private_link(self, admin, db):
        return self._entry_link(admin, False)

    def test_admin_sees_the_private_link_and_anonymous_does_not(
        self, local_mode, server, admin, igsn_metadata, private_link
    ):
        """The comparison at the heart of the report, over the REST API."""
        igsn_metadata["relatedIdentifiers"] = [private_link]
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=True
        )

        as_admin = server.request(
            path=f"/deposition/{deposition['_id']}", method="GET", user=admin
        )
        assertStatusOk(as_admin)
        as_anon = server.request(
            path=f"/deposition/{deposition['_id']}", method="GET"
        )
        assertStatusOk(as_anon)

        assert private_link in as_admin.json["metadata"]["relatedIdentifiers"]
        assert private_link not in as_anon.json["metadata"]["relatedIdentifiers"]

    def test_a_public_link_is_visible_to_both(
        self, local_mode, server, admin, igsn_metadata, public_link
    ):
        igsn_metadata["relatedIdentifiers"] = [public_link]
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=True
        )
        as_anon = server.request(
            path=f"/deposition/{deposition['_id']}", method="GET"
        )
        assertStatusOk(as_anon)
        assert public_link in as_anon.json["metadata"]["relatedIdentifiers"]

    def test_what_is_published_matches_the_anonymous_view(
        self,
        remote_mode,
        igsn_service,
        server,
        admin,
        igsn_metadata,
        public_link,
        private_link,
    ):
        """The invariant: pushed metadata == what an anonymous reader sees."""
        igsn_metadata["relatedIdentifiers"] = [public_link, private_link]
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=True
        )

        as_anon = server.request(
            path=f"/deposition/{deposition['_id']}", method="GET"
        )
        assertStatusOk(as_anon)
        pushed = igsn_service.put_record.call_args.kwargs["metadata"]

        assert pushed["relatedIdentifiers"] == (
            as_anon.json["metadata"]["relatedIdentifiers"]
        )
        assert pushed["relatedIdentifiers"] == [public_link]

    def test_publishing_never_sends_a_private_link(
        self, remote_mode, igsn_service, server, admin, igsn_metadata, private_link
    ):
        from ..worker_plugin.igsn_registry import publish_deposition

        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=True
        )
        # As it happens in practice: added after creation by a raw update.
        Deposition().collection.update_one(
            {"_id": deposition["_id"]},
            {"$addToSet": {"metadata.relatedIdentifiers": private_link}},
        )
        igsn_service.put_record.reset_mock()

        with patch(
            "girder_jsonforms.worker_plugin.igsn_registry.get_client",
            return_value=igsn_service,
        ), patch(
            "girder_jsonforms.models.deposition.get_client", return_value=igsn_service
        ):
            publish_deposition(str(deposition["_id"]), target="findable")

        pushed = igsn_service.put_record.call_args.kwargs["metadata"]
        assert private_link not in pushed["relatedIdentifiers"]
        # But Girder keeps it.
        stored = Deposition().load(deposition["_id"], force=True)
        assert private_link in stored["metadata"]["relatedIdentifiers"]

    def test_a_relation_sync_does_not_leak_either(
        self, remote_mode, igsn_service, server, admin, igsn_metadata, private_link
    ):
        """update_deposition_relations writes raw, then queues a sync."""
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=True
        )
        Deposition().collection.update_one(
            {"_id": deposition["_id"]},
            {"$addToSet": {"metadata.relatedIdentifiers": private_link}},
        )
        igsn_service.put_record.reset_mock()
        Deposition().sync_to_registry(
            Deposition().load(deposition["_id"], force=True)
        )
        pushed = igsn_service.put_record.call_args.kwargs["metadata"]
        assert private_link not in pushed["relatedIdentifiers"]


def _stub_dispatch(user):
    """A stand-in for publish_deposition whose .delay() returns a real job.

    The endpoint is decorated @filtermodel(model="job"), and celery's eager
    results -- the only kind available without a broker -- carry no job at all.
    """
    from girder_jobs.models.job import Job

    job = Job().createJob(title="stub", type="test", user=user, public=True)
    dispatched = MagicMock()
    dispatched.delay.return_value = MagicMock(job=job)
    return dispatched


class TestPublishEndpointRequiresPublic:
    """The REST gate. Publishing a private record is refused, not silently
    fixed by making it public."""

    def test_private_deposition_is_rejected(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=False
        )
        response = server.request(
            path=f"/deposition/{deposition['_id']}/task",
            method="PUT",
            user=admin,
            params={"action": "publish"},
        )
        assertStatus(response, 400)
        assert "not public" in response.json["message"]
        igsn_service.publish.assert_not_called()
        # And it is still private afterwards.
        assert Deposition().load(deposition["_id"], force=True)["public"] is False

    def test_public_deposition_is_accepted(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        """Stubs the dispatch: the endpoint returns task.job, and celery's eager
        results -- which the tests must use, there being no broker -- have none."""
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=True
        )
        dispatched = _stub_dispatch(admin)
        with patch(
            "girder_jsonforms.rest.deposition.publish_deposition", dispatched
        ):
            response = server.request(
                path=f"/deposition/{deposition['_id']}/task",
                method="PUT",
                user=admin,
                params={"action": "publish", "recurse": True},
            )
        assertStatusOk(response)
        dispatched.delay.assert_called_once()
        assert dispatched.delay.call_args.kwargs["recurse"] is True
        assert dispatched.delay.call_args.kwargs["metadata_only"] is False

    def test_recursive_publish_checks_children(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=True
        )
        Deposition().create_batch(deposition, [("001", None)])
        Deposition().collection.update_one(
            {"igsn": "ABCDEF00001-001"}, {"$set": {"public": False}}
        )
        response = server.request(
            path=f"/deposition/{deposition['_id']}/task",
            method="PUT",
            user=admin,
            params={"action": "publish", "recurse": True},
        )
        assertStatus(response, 400)
        assert "ABCDEF00001-001" in response.json["message"]

    def test_sync_of_a_private_deposition_is_still_allowed(
        self, remote_mode, igsn_service, server, admin, igsn_metadata
    ):
        """Syncing metadata is reversible and sends only the public projection."""
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=False
        )
        dispatched = _stub_dispatch(admin)
        with patch(
            "girder_jsonforms.rest.deposition.publish_deposition", dispatched
        ):
            response = server.request(
                path=f"/deposition/{deposition['_id']}/task",
                method="PUT",
                user=admin,
                params={"action": "sync"},
            )
        assertStatusOk(response)
        assert dispatched.delay.call_args.kwargs["metadata_only"] is True

    def test_the_access_flag_is_checked_before_publicness(
        self, remote_mode, igsn_service, server, admin, user, igsn_metadata
    ):
        """A user without the grant gets 403, not a hint about the public flag."""
        deposition = Deposition().create_deposition(
            igsn_metadata, admin, prefix="ABCDEF", public=False
        )
        Deposition().setUserAccess(deposition, user=user, level=2, save=True)
        response = server.request(
            path=f"/deposition/{deposition['_id']}/task",
            method="PUT",
            user=user,
            params={"action": "publish"},
        )
        assertStatus(response, 403)
