import json

import pytest
from girder.constants import AccessType
from girder.models.folder import Folder
from pytest_girder.assertions import assertStatus, assertStatusOk


@pytest.fixture
def sample_schema():
    """Sample schema for testing form entries."""
    return {
        "type": "object",
        "properties": {
            "sampleId": {"type": "string", "title": "Sample ID"},
            "name": {"type": "string", "title": "Name"},
            "age": {"type": "integer", "title": "Age", "minimum": 0},
            "email": {"type": "string", "format": "email", "title": "Email"},
            "assignedIGSN": {"type": "string", "title": "Assigned IGSN"},
        },
        "required": ["sampleId", "name"],
    }


@pytest.fixture
def test_form(server, admin, sample_schema):
    """Create a test form for entry testing."""
    resp = server.request(
        path="/form",
        method="POST",
        params={
            "name": "Test Entry Form",
            "description": "Form for testing entries",
            "uniqueField": "sampleId",
        },
        body=json.dumps(sample_schema),
        type="application/json",
        user=admin,
    )
    assertStatusOk(resp)
    form = resp.json

    # Grant access to the form for testing
    resp = server.request(
        path="/form/%s/access" % form["_id"],
        method="PUT",
        user=admin,
        params={
            "access": json.dumps(
                {
                    "users": [
                        {
                            "login": admin["login"],
                            "level": AccessType.ADMIN,
                            "id": str(admin["_id"]),
                            "flags": [],
                            "name": f"{admin['firstName']} {admin['lastName']}",
                        }
                    ],
                    "groups": [],
                }
            ),
        },
    )
    assertStatusOk(resp)

    yield form

    # Cleanup
    server.request(
        path="/form/%s" % form["_id"],
        method="DELETE",
        user=admin,
    )


@pytest.fixture
def sample_entry_data():
    """Sample data for creating entries."""
    return {
        "sampleId": "SAMPLE_001",
        "name": "Test Sample",
        "age": 25,
        "email": "test@example.com",
    }


@pytest.fixture
def test_folder(server, admin):
    """Create a test folder for file operations."""
    from girder.models.collection import Collection

    collection = Collection().createCollection("Test Collection", admin)
    folder = Folder().createFolder(
        collection, "Test Folder", parentType="collection", creator=admin
    )
    yield folder

    # Cleanup
    Folder().remove(folder)
    Collection().remove(collection)


@pytest.mark.plugin("jsonforms")
class TestFormEntryResource:
    """Test cases for the FormEntry Resource."""

    def test_create_entry_success(self, server, admin, test_form, sample_entry_data):
        """Test successful entry creation."""
        resp = server.request(
            path="/entry",
            method="POST",
            user=admin,
            params={
                "formId": test_form["_id"],
                "data": json.dumps(sample_entry_data),
            },
        )
        assertStatusOk(resp)
        entry = resp.json

        assert entry["_id"] is not None
        assert entry["formId"] == test_form["_id"]
        assert entry["data"]["sampleId"] == sample_entry_data["sampleId"]
        assert entry["data"]["name"] == sample_entry_data["name"]
        assert entry["data"]["age"] == sample_entry_data["age"]
        assert entry["data"]["email"] == sample_entry_data["email"]

    def test_create_entry_duplicate_unique_field(
        self, server, admin, test_form, sample_entry_data
    ):
        """Test creating entry with duplicate unique field fails."""
        # Create first entry
        resp = server.request(
            path="/entry",
            method="POST",
            user=admin,
            params={
                "formId": test_form["_id"],
                "data": json.dumps(sample_entry_data),
            },
        )
        assertStatusOk(resp)

        # Try to create another entry with same sampleId
        resp = server.request(
            path="/entry",
            method="POST",
            user=admin,
            params={
                "formId": test_form["_id"],
                "data": json.dumps(sample_entry_data),
            },
        )
        assertStatus(resp, 400)
        assert "already exists" in resp.json["message"]

    def test_create_entry_missing_required_field(self, server, admin, test_form):
        """Test creating entry with missing required field fails."""
        incomplete_data = {
            "name": "Test Sample",  # Missing required sampleId
            "age": 25,
        }

        resp = server.request(
            path="/entry",
            method="POST",
            user=admin,
            params={
                "formId": test_form["_id"],
                "data": json.dumps(incomplete_data),
            },
        )
        # Should fail due to missing sampleId
        assertStatus(resp, 400)

    def test_create_entry_with_folders(
        self, server, admin, test_form, sample_entry_data, test_folder
    ):
        """Test creating entry with source and destination folders."""
        resp = server.request(
            path="/entry",
            method="POST",
            user=admin,
            params={
                "formId": test_form["_id"],
                "sourceId": test_folder["_id"],
                "destinationId": test_folder["_id"],
                "data": json.dumps(sample_entry_data),
            },
        )
        assertStatusOk(resp)
        entry = resp.json
        assert entry["_id"] is not None

    def test_get_entry_success(self, server, admin, test_form, sample_entry_data):
        """Test successful retrieval of an entry."""
        # Create entry first
        resp = server.request(
            path="/entry",
            method="POST",
            user=admin,
            params={
                "formId": test_form["_id"],
                "data": json.dumps(sample_entry_data),
            },
        )
        assertStatusOk(resp)
        entry_id = resp.json["_id"]

        # Get the entry
        resp = server.request(
            path="/entry/%s" % entry_id,
            method="GET",
            user=admin,
        )
        assertStatusOk(resp)
        entry = resp.json
        assert entry["_id"] == entry_id
        assert entry["data"]["sampleId"] == sample_entry_data["sampleId"]

    def test_get_entry_not_found(self, server, admin):
        """Test getting non-existent entry returns 400."""
        from bson import ObjectId

        fake_id = str(ObjectId())

        resp = server.request(
            path="/entry/%s" % fake_id,
            method="GET",
            user=admin,
        )
        assertStatus(resp, 400)

    def test_update_entry_success(self, server, admin, test_form, sample_entry_data):
        """Test successful entry update."""
        # Create entry first
        resp = server.request(
            path="/entry",
            method="POST",
            user=admin,
            params={
                "formId": test_form["_id"],
                "data": json.dumps(sample_entry_data),
            },
        )
        assertStatusOk(resp)
        entry_id = resp.json["_id"]

        # Update the entry
        updated_data = sample_entry_data.copy()
        updated_data["age"] = 30
        updated_data["email"] = "updated@example.com"

        resp = server.request(
            path="/entry/%s" % entry_id,
            method="PUT",
            user=admin,
            params={
                "data": json.dumps(updated_data),
            },
        )
        assertStatusOk(resp)
        entry = resp.json
        assert entry["data"]["age"] == 30
        assert entry["data"]["email"] == "updated@example.com"
        assert (
            entry["data"]["sampleId"] == sample_entry_data["sampleId"]
        )  # Should remain unchanged

    def test_update_entry_change_unique_field_fails(
        self, server, admin, test_form, sample_entry_data
    ):
        """Test updating unique field fails."""
        # Create entry first
        resp = server.request(
            path="/entry",
            method="POST",
            user=admin,
            params={
                "formId": test_form["_id"],
                "data": json.dumps(sample_entry_data),
            },
        )
        assertStatusOk(resp)
        entry_id = resp.json["_id"]

        # Try to update unique field
        updated_data = sample_entry_data.copy()
        updated_data["sampleId"] = "SAMPLE_002"  # Change unique field

        resp = server.request(
            path="/entry/%s" % entry_id,
            method="PUT",
            user=admin,
            params={
                "data": json.dumps(updated_data),
            },
        )
        assertStatus(resp, 400)
        assert "cannot change entry's unique id" in resp.json["message"]

    def test_update_entry_change_assigned_igsn_fails(
        self, server, admin, test_form, sample_entry_data
    ):
        """Test updating assigned IGSN fails."""
        # Create entry with IGSN
        entry_data_with_igsn = sample_entry_data.copy()
        entry_data_with_igsn["assignedIGSN"] = "IGSN123"

        resp = server.request(
            path="/entry",
            method="POST",
            user=admin,
            params={
                "formId": test_form["_id"],
                "data": json.dumps(entry_data_with_igsn),
            },
        )
        assertStatusOk(resp)
        entry_id = resp.json["_id"]

        # Try to update IGSN
        updated_data = entry_data_with_igsn.copy()
        updated_data["assignedIGSN"] = "IGSN456"  # Change IGSN

        resp = server.request(
            path="/entry/%s" % entry_id,
            method="PUT",
            user=admin,
            params={
                "data": json.dumps(updated_data),
            },
        )
        assertStatus(resp, 400)
        assert "cannot change entry's assigned IGSN" in resp.json["message"]

    def test_delete_entry_success(self, server, admin, test_form, sample_entry_data):
        """Test successful entry deletion."""
        from unittest.mock import patch

        # Create entry first
        resp = server.request(
            path="/entry",
            method="POST",
            user=admin,
            params={
                "formId": test_form["_id"],
                "data": json.dumps(sample_entry_data),
            },
        )
        assertStatusOk(resp)
        entry_id = resp.json["_id"]

        # Mock the Celery task that gets triggered on entry deletion
        with patch(
            "girder_jsonforms.worker_plugin.pull_related_ids.run.delay"
        ) as mock_task:
            # Delete the entry
            resp = server.request(
                path="/entry/%s" % entry_id,
                method="DELETE",
                user=admin,
            )
            assertStatusOk(resp)

            # Verify the Celery task was called
            mock_task.assert_called_once()
            # Get the call arguments
            call_args = mock_task.call_args
            entry_arg = call_args[0][0]  # First positional argument (entry)
            assert str(entry_arg["_id"]) == entry_id

            # Verify keyword arguments include user and job title
            call_kwargs = call_args[1]
            assert "user" in call_kwargs
            assert (
                call_kwargs["girder_job_title"]
                == "Updating relatedIdentifiers in Depositions"
            )

        # Verify entry is deleted
        resp = server.request(
            path="/entry/%s" % entry_id,
            method="GET",
            user=admin,
        )
        assertStatus(resp, 400)

    def test_list_entries_empty(self, server, admin, test_form):
        """Test listing entries when none exist."""
        resp = server.request(
            path="/entry",
            method="GET",
            user=admin,
            params={"formId": test_form["_id"]},
        )
        assertStatusOk(resp)
        assert resp.json == []

    def test_list_entries_with_data(self, server, admin, test_form):
        """Test listing entries with data."""
        # Create multiple entries
        entries_data = [
            {"sampleId": "SAMPLE_001", "name": "Sample 1", "age": 25},
            {"sampleId": "SAMPLE_002", "name": "Sample 2", "age": 30},
            {"sampleId": "SAMPLE_003", "name": "Sample 3", "age": 35},
        ]

        for data in entries_data:
            resp = server.request(
                path="/entry",
                method="POST",
                user=admin,
                params={
                    "formId": test_form["_id"],
                    "data": json.dumps(data),
                },
            )
            assertStatusOk(resp)

        # List entries
        resp = server.request(
            path="/entry",
            method="GET",
            user=admin,
            params={"formId": test_form["_id"]},
        )
        assertStatusOk(resp)
        entries = resp.json
        assert len(entries) == 3
        sample_ids = {entry["data"]["sampleId"] for entry in entries}
        expected_ids = {"SAMPLE_001", "SAMPLE_002", "SAMPLE_003"}
        assert sample_ids == expected_ids

    def test_list_entries_with_query(self, server, admin, test_form):
        """Test listing entries with query filter."""
        # Create multiple entries
        entries_data = [
            {"sampleId": "TEST_001", "name": "Test Sample 1", "age": 25},
            {"sampleId": "PROD_001", "name": "Production Sample 1", "age": 30},
            {"sampleId": "TEST_002", "name": "Test Sample 2", "age": 35},
        ]

        for data in entries_data:
            resp = server.request(
                path="/entry",
                method="POST",
                user=admin,
                params={
                    "formId": test_form["_id"],
                    "data": json.dumps(data),
                },
            )
            assertStatusOk(resp)

        # List entries with query
        resp = server.request(
            path="/entry",
            method="GET",
            user=admin,
            params={
                "formId": test_form["_id"],
                "query": "TEST_",
            },
        )
        assertStatusOk(resp)
        entries = resp.json
        assert len(entries) == 2
        for entry in entries:
            assert "TEST_" in entry["data"]["sampleId"]

    def test_search_entries(self, server, admin, test_form):
        """Test searching entries."""
        # Create multiple entries
        entries_data = [
            {"sampleId": "ABC_001", "name": "Alpha Sample", "age": 25},
            {"sampleId": "ABC_002", "name": "Beta Sample", "age": 30},
            {"sampleId": "XYZ_001", "name": "Gamma Sample", "age": 35},
        ]

        for data in entries_data:
            resp = server.request(
                path="/entry",
                method="POST",
                user=admin,
                params={
                    "formId": test_form["_id"],
                    "data": json.dumps(data),
                },
            )
            assertStatusOk(resp)

        # Search entries
        resp = server.request(
            path="/entry/search",
            method="GET",
            user=admin,
            params={
                "formId": test_form["_id"],
                "query": "ABC_",
            },
        )
        assertStatusOk(resp)
        results = resp.json
        assert len(results) == 2
        for result in results:
            assert "ABC_" in result  # Results are in format "id;sampleId"

    def test_search_entries_by_field(self, server, admin, test_form):
        """Test searching entries by specific field."""
        # Create multiple entries
        entries_data = [
            {"sampleId": "SAMPLE_001", "name": "Alpha Test", "age": 25},
            {"sampleId": "SAMPLE_002", "name": "Beta Sample", "age": 30},
            {"sampleId": "SAMPLE_003", "name": "Alpha Production", "age": 35},
        ]

        for data in entries_data:
            resp = server.request(
                path="/entry",
                method="POST",
                user=admin,
                params={
                    "formId": test_form["_id"],
                    "data": json.dumps(data),
                },
            )
            assertStatusOk(resp)

        # Search by name field
        resp = server.request(
            path="/entry/search",
            method="GET",
            user=admin,
            params={
                "formId": test_form["_id"],
                "query": "Alpha",
                "field": "name",
            },
        )
        assertStatusOk(resp)
        results = resp.json
        assert len(results) == 2  # Two entries with "Alpha" in name

    def test_entry_permissions(self, server, user, admin, test_form, sample_entry_data):
        """Test entry access permissions."""
        # Create entry as admin
        resp = server.request(
            path="/entry",
            method="POST",
            user=admin,
            params={
                "formId": test_form["_id"],
                "data": json.dumps(sample_entry_data),
            },
        )
        assertStatusOk(resp)
        entry_id = resp.json["_id"]

        # Regular user should not have access without permissions
        resp = server.request(
            path="/entry/%s" % entry_id,
            method="GET",
            user=user,
        )
        assertStatus(resp, 403)

        # Regular user should not be able to create entries without permissions
        new_data = {"sampleId": "SAMPLE_002", "name": "Another Sample"}
        resp = server.request(
            path="/entry",
            method="POST",
            user=user,
            params={
                "formId": test_form["_id"],
                "data": json.dumps(new_data),
            },
        )
        assertStatus(resp, 403)

    def test_pagination(self, server, admin, test_form):
        """Test pagination of entry listing."""
        # Create multiple entries
        for i in range(5):
            data = {
                "sampleId": f"SAMPLE_{i:03d}",
                "name": f"Sample {i}",
                "age": 20 + i,
            }
            resp = server.request(
                path="/entry",
                method="POST",
                user=admin,
                params={
                    "formId": test_form["_id"],
                    "data": json.dumps(data),
                },
            )
            assertStatusOk(resp)

        # Test pagination
        resp = server.request(
            path="/entry",
            method="GET",
            user=admin,
            params={
                "formId": test_form["_id"],
                "limit": 2,
                "offset": 0,
            },
        )
        assertStatusOk(resp)
        assert len(resp.json) == 2

        resp = server.request(
            path="/entry",
            method="GET",
            user=admin,
            params={
                "formId": test_form["_id"],
                "limit": 2,
                "offset": 2,
            },
        )
        assertStatusOk(resp)
        assert len(resp.json) == 2
