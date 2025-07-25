import json
from unittest.mock import patch

import pytest
from girder.constants import AccessType
from girder.models.setting import Setting
from pytest_girder.assertions import assertStatus, assertStatusOk

from ..models.deposition import PrefixCounter
from ..settings import PluginSettings


@pytest.fixture
def sample_metadata():
    """Sample metadata for testing depositions."""
    return {
        "titles": [{"title": "Test Sample Deposition"}],
        "creators": [
            {
                "name": "Test Creator",
                "nameType": "Personal",
                "givenName": "Test",
                "familyName": "Creator",
            }
        ],
        "publisher": {"name": "Test Publisher"},
        "publicationYear": "2024",
        "descriptions": [
            {"description": "Test description", "descriptionType": "Abstract"}
        ],
        "alternateIdentifiers": [
            {
                "alternateIdentifier": "12345",
                "alternateIdentifierType": "Local",
            }
        ],
    }


@pytest.fixture
def igsn_settings():
    """Mock IGSN settings for testing."""
    institutions = {
        "AB": {
            "name": "Test Institution",
            "labs": {"C": "Test Lab"},
        }
    }
    materials = {
        "DE": {
            "name": "Test Material",
            "subcategories": {"F": "Test Subcategory"},
        }
    }
    return institutions, materials


@pytest.fixture
def mock_orcid_response():
    """Mock ORCID API response."""
    return {
        "expanded-result": [
            {
                "family-names": "Doe",
                "given-names": "John",
                "orcid-id": "0000-0000-0000-0000",
                "institution-name": ["Test University"],
            }
        ]
    }


@pytest.fixture
def setup_settings(db, igsn_settings):
    """Set up required settings for testing."""
    institutions, materials = igsn_settings
    Setting().set(PluginSettings.IGSN_INSTITUTIONS, institutions)
    Setting().set(PluginSettings.IGSN_MATERIALS, materials)
    Setting().set(PluginSettings.IGSN_PUBLISHER, "Test Publisher")
    yield
    # Cleanup settings after test
    Setting().unset(PluginSettings.IGSN_INSTITUTIONS)
    Setting().unset(PluginSettings.IGSN_MATERIALS)
    Setting().unset(PluginSettings.IGSN_PUBLISHER)


@pytest.fixture
def test_deposition(server, admin, sample_metadata, setup_settings):
    """Create a test deposition for testing."""
    resp = server.request(
        path="/deposition",
        method="POST",
        user=admin,
        params={
            "prefix": "ABCDEF",
            "metadata": json.dumps(sample_metadata),
        },
    )
    assertStatusOk(resp)
    deposition = resp.json

    yield deposition

    # Cleanup
    try:
        server.request(
            path="/deposition/%s" % deposition["_id"],
            method="DELETE",
            user=admin,
        )
    except Exception:
        pass  # Deposition might already be deleted in test


@pytest.fixture
def test_sample(server, admin):
    """Create a test sample for testing."""
    resp = server.request(
        path="/sample",
        method="POST",
        user=admin,
        params={
            "name": "Test Sample",
            "description": "This is a test sample.",
            "access": json.dumps(
                {
                    "users": [
                        {
                            "flags": [],
                            "id": str(admin["_id"]),
                            "level": 2,
                            "login": admin["login"],
                            "name": f"{admin['firstName']} {admin['lastName']}",
                        }
                    ],
                    "groups": [],
                }
            ),
        },
    )
    sample = resp.json
    yield sample

    # Ensure sample is removed after test
    resp = server.request(
        path="/sample/%s" % sample["_id"],
        method="DELETE",
        user=admin,
    )


@pytest.mark.plugin("sample_tracker")
@pytest.mark.plugin("jsonforms")
class TestDepositionResource:
    """Test cases for the Deposition Resource."""

    def test_create_deposition_success(
        self, server, admin, sample_metadata, setup_settings
    ):
        """Test successful deposition creation."""
        resp = server.request(
            path="/deposition",
            method="POST",
            user=admin,
            params={
                "prefix": "ABCDEF",
                "metadata": json.dumps(sample_metadata),
            },
        )
        assertStatusOk(resp)
        deposition = resp.json

        assert deposition["_id"] is not None
        assert deposition["igsn"].startswith("ABCDEF")
        assert deposition["metadata"]["titles"] == sample_metadata["titles"]
        assert deposition["metadata"]["creators"] == sample_metadata["creators"]
        assert deposition["creatorId"] == str(admin["_id"])
        assert "created" in deposition
        assert "updated" in deposition

    def test_create_deposition_with_tracking(
        self, server, admin, sample_metadata, setup_settings
    ):
        """Test creating deposition with sample tracking enabled."""
        resp = server.request(
            path="/deposition",
            method="POST",
            user=admin,
            params={
                "prefix": "ABCDEF",
                "track": True,
                "metadata": json.dumps(sample_metadata),
            },
        )
        assertStatusOk(resp)
        deposition = resp.json

        assert deposition["track"] is True
        assert deposition["sampleId"] is not None

    def test_create_deposition_with_batch(
        self, server, admin, sample_metadata, setup_settings
    ):
        """Test creating deposition with batch subsamples."""
        resp = server.request(
            path="/deposition",
            method="POST",
            user=admin,
            params={
                "prefix": "ABCDEF",
                "batch": 3,
                "metadata": json.dumps(sample_metadata),
            },
        )
        assertStatusOk(resp)
        deposition = resp.json

        # Should create parent deposition successfully
        assert deposition["_id"] is not None
        assert deposition["igsn"].startswith("ABCDEF")

        resp = server.request(
            path="/deposition",
            method="GET",
            user=admin,
            params={
                "igsnPrefix": deposition["igsn"][:6],  # Get the prefix
            },
        )
        assertStatusOk(resp)
        depositions = resp.json
        assert len(depositions) == 4  # Should create main and 3 subsamples

    def test_create_deposition_invalid_prefix(
        self, server, admin, sample_metadata, setup_settings
    ):
        """Test creating deposition with invalid prefix fails."""
        resp = server.request(
            path="/deposition",
            method="POST",
            user=admin,
            params={
                "prefix": "INVALID",  # Wrong length
                "metadata": json.dumps(sample_metadata),
            },
        )
        assertStatus(resp, 400)
        assert resp.json["message"] == "Prefix must be 6 characters long"

    def test_create_deposition_missing_metadata(self, server, admin, setup_settings):
        """Test creating deposition with missing metadata fails."""
        resp = server.request(
            path="/deposition",
            method="POST",
            user=admin,
            params={
                "prefix": "ABCDEF",
                "metadata": json.dumps({}),  # Empty metadata
            },
        )
        assertStatus(resp, 400)
        assert resp.json["message"].startswith("Metadata validation failed")

    def test_get_deposition_success(self, server, admin, test_deposition):
        """Test getting a deposition by ID."""
        resp = server.request(
            path="/deposition/%s" % test_deposition["_id"],
            method="GET",
            user=admin,
        )
        assertStatusOk(resp)
        deposition = resp.json

        assert deposition["_id"] == test_deposition["_id"]
        assert deposition["igsn"] == test_deposition["igsn"]
        assert deposition["metadata"]["titles"] == test_deposition["metadata"]["titles"]

    def test_get_deposition_not_found(self, server, admin):
        """Test getting non-existent deposition returns 400."""
        from bson import ObjectId

        fake_id = str(ObjectId())

        resp = server.request(
            path="/deposition/%s" % fake_id,
            method="GET",
            user=admin,
        )
        assertStatus(resp, 400)
        assert resp.json["message"] == f"Invalid deposition id ({fake_id})."

    def test_update_deposition_success(self, server, admin, test_deposition):
        """Test updating a deposition."""
        updated_metadata = test_deposition["metadata"].copy()
        updated_metadata["titles"][0]["title"] = "Updated Test Sample"

        resp = server.request(
            path="/deposition/%s" % test_deposition["_id"],
            method="PUT",
            user=admin,
            params={
                "metadata": json.dumps(updated_metadata),
            },
        )
        assertStatusOk(resp)
        deposition = resp.json

        assert deposition["metadata"]["titles"][0]["title"] == "Updated Test Sample"

    def test_update_deposition_with_sample_id(
        self, server, admin, test_deposition, test_sample
    ):
        """Test updating deposition with sample ID."""
        # Create a mock sample ID (in real scenario this would be from sample tracker)
        resp = server.request(
            path="/deposition/%s" % test_deposition["_id"],
            method="GET",
            user=admin,
        )
        assertStatusOk(resp)
        test_deposition = resp.json
        assert test_deposition["sampleId"] is None

        sample_id = test_sample["_id"]

        updated_metadata = test_deposition["metadata"].copy()
        resp = server.request(
            path="/deposition/%s" % test_deposition["_id"],
            method="PUT",
            user=admin,
            params={
                "sampleId": sample_id,
                "metadata": json.dumps(updated_metadata),
            },
        )
        assertStatusOk(resp)
        deposition = resp.json
        assert deposition["sampleId"] == sample_id

    def test_delete_deposition_success(self, server, admin, test_deposition):
        """Test deleting a deposition."""
        resp = server.request(
            path="/deposition/%s" % test_deposition["_id"],
            method="DELETE",
            user=admin,
        )
        assertStatusOk(resp)

        # Verify deposition is deleted
        resp = server.request(
            path="/deposition/%s" % test_deposition["_id"],
            method="GET",
            user=admin,
        )
        assertStatus(resp, 400)

    def test_delete_deposition_insufficient_permissions(
        self, server, user, test_deposition
    ):
        """Test deleting deposition without admin permissions fails."""
        resp = server.request(
            path="/deposition/%s" % test_deposition["_id"],
            method="DELETE",
            user=user,
        )
        assertStatus(resp, 403)

    def test_list_depositions_success(self, server, admin, test_deposition):
        """Test listing depositions."""
        resp = server.request(
            path="/deposition",
            method="GET",
            user=admin,
        )
        assertStatusOk(resp)
        depositions = resp.json

        assert len(depositions) >= 1
        # Find our test deposition in the list
        found = any(d["_id"] == test_deposition["_id"] for d in depositions)
        assert found

    def test_list_depositions_with_query(self, server, admin, test_deposition):
        """Test listing depositions with search query."""
        resp = server.request(
            path="/deposition",
            method="GET",
            user=admin,
            params={
                "q": "Test Sample",
            },
        )
        assertStatusOk(resp)
        depositions = resp.json

        # Should find our test deposition
        found = any(d["_id"] == test_deposition["_id"] for d in depositions)
        assert found

    def test_list_depositions_with_igsn_prefix(self, server, admin, test_deposition):
        """Test listing depositions with IGSN prefix filter."""
        igsn_prefix = test_deposition["igsn"][:6]  # Get first 6 characters

        resp = server.request(
            path="/deposition",
            method="GET",
            user=admin,
            params={
                "igsnPrefix": igsn_prefix,
            },
        )
        assertStatusOk(resp)
        depositions = resp.json

        # Should find our test deposition
        found = any(d["_id"] == test_deposition["_id"] for d in depositions)
        assert found

    def test_list_depositions_with_sample_id(self, server, admin, test_deposition):
        """Test listing depositions with sample ID filter."""
        # This test assumes the deposition doesn't have a sampleId
        resp = server.request(
            path="/deposition",
            method="GET",
            user=admin,
            params={
                "sampleId": "nonexistent_sample",
            },
        )
        assertStatusOk(resp)
        depositions = resp.json

        # Should return empty list for non-existent sample
        assert depositions == []

    def test_create_child_deposition_success(self, server, admin, test_deposition):
        """Test creating a child deposition."""
        child_metadata = {
            "titles": [{"title": "Child Sample"}],
            "descriptions": [
                {"description": "Child description", "descriptionType": "Abstract"}
            ],
        }

        resp = server.request(
            path="/deposition/%s/split" % test_deposition["_id"],
            method="POST",
            user=admin,
            params={
                "suffix": "001",
                "metadata": json.dumps(child_metadata),  # TODO: currently ignored
            },
        )
        assertStatusOk(resp)
        child_deposition = resp.json

        assert child_deposition["_id"] != test_deposition["_id"]
        assert child_deposition["igsn"] == f"{test_deposition['igsn']}-001"
        # assert child_deposition["metadata"]["titles"][0]["title"] == "Child Sample"
        assert (
            child_deposition["metadata"]["titles"][0]["title"]
            == f"{test_deposition['metadata']['titles'][0]['title']} - 001"
        )

    def test_create_child_deposition_invalid_suffix(
        self, server, admin, test_deposition
    ):
        """Test creating child deposition with invalid suffix fails."""
        resp = server.request(
            path="/deposition/%s/split" % test_deposition["_id"],
            method="POST",
            user=admin,
            params={
                "suffix": "invalid-suffix!",  # Contains special characters
            },
        )
        assertStatus(resp, 400)
        assert "alphanumeric" in resp.json["message"]

    def test_create_child_deposition_duplicate_suffix(
        self, server, admin, test_deposition
    ):
        """Test creating child deposition with duplicate suffix fails."""
        # Create first child
        resp = server.request(
            path="/deposition/%s/split" % test_deposition["_id"],
            method="POST",
            user=admin,
            params={
                "suffix": "001",
            },
        )
        assertStatusOk(resp)

        # Try to create another child with same suffix
        resp = server.request(
            path="/deposition/%s/split" % test_deposition["_id"],
            method="POST",
            user=admin,
            params={
                "suffix": "001",
            },
        )
        assertStatus(resp, 400)
        assert "already exists" in resp.json["message"]

    def test_get_deposition_access(self, server, admin, test_deposition):
        """Test getting deposition access control list."""
        resp = server.request(
            path="/deposition/%s/access" % test_deposition["_id"],
            method="GET",
            user=admin,
        )
        assertStatusOk(resp)
        access = resp.json

        assert "users" in access
        assert "groups" in access

    def test_update_deposition_access(self, server, admin, user, test_deposition):
        """Test updating deposition access control list."""
        access_list = {
            "users": [
                {
                    "login": user["login"],
                    "level": AccessType.READ,
                    "id": str(user["_id"]),
                    "flags": [],
                    "name": f"{user['firstName']} {user['lastName']}",
                }
            ],
            "groups": [],
        }

        resp = server.request(
            path="/deposition/%s/access" % test_deposition["_id"],
            method="PUT",
            user=admin,
            params={
                "access": json.dumps(access_list),
                "public": True,
            },
        )
        assertStatusOk(resp)

        # Verify access was updated
        resp = server.request(
            path="/deposition/%s/access" % test_deposition["_id"],
            method="GET",
            user=admin,
        )
        assertStatusOk(resp)
        access = resp.json

        # Check that the user was added to access list
        user_found = any(
            u["id"] == str(user["_id"]) and u["level"] == AccessType.READ
            for u in access["users"]
        )
        assert user_found

    def test_get_settings(self, server, admin, setup_settings):
        """Test getting deposition settings."""
        resp = server.request(
            path="/deposition/settings",
            method="GET",
            user=admin,
        )
        assertStatusOk(resp)
        settings = resp.json

        assert "igsn_institutions" in settings
        assert "igsn_materials" in settings
        assert "AB" in settings["igsn_institutions"]
        assert "DE" in settings["igsn_materials"]

    @patch("requests.post")
    @patch("requests.get")
    def test_autocomplete_orcid_success(
        self, mock_get, mock_post, server, admin, mock_orcid_response, setup_settings
    ):
        """Test ORCID autocomplete functionality."""
        # Mock token request
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "test_token"}

        # Mock search request
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_orcid_response

        resp = server.request(
            path="/deposition/autocomplete",
            method="GET",
            user=admin,
            params={
                "query": "John Doe",
                "limit": 10,
            },
        )
        assertStatusOk(resp)
        results = resp.json

        assert len(results) == 1
        assert "John" in results[0]["text"]
        assert "Doe" in results[0]["text"]
        assert "0000-0000-0000-0000" in results[0]["text"]

    @patch("requests.post")
    @patch("requests.get")
    def test_autocomplete_orcid_empty_results(
        self, mock_get, mock_post, server, admin, setup_settings
    ):
        """Test ORCID autocomplete with no results."""
        # Mock token request
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "test_token"}

        # Mock search request with no results
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"expanded-result": []}

        resp = server.request(
            path="/deposition/autocomplete",
            method="GET",
            user=admin,
            params={
                "query": "Nonexistent Person",
            },
        )
        assertStatusOk(resp)
        results = resp.json

        assert results == []

    @patch("requests.post")
    @patch("requests.get")
    def test_autocomplete_orcid_api_error(
        self, mock_get, mock_post, server, admin, setup_settings
    ):
        """Test ORCID autocomplete with API error."""
        # Mock token request
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"access_token": "test_token"}

        # Mock search request with error
        mock_get.return_value.status_code = 500

        resp = server.request(
            path="/deposition/autocomplete",
            method="GET",
            user=admin,
            params={
                "query": "John Doe",
            },
        )
        assertStatusOk(resp)
        results = resp.json

        assert results == []


@pytest.mark.plugin("jsonforms")
class TestPrefixCounter:
    """Test cases for the PrefixCounter model."""

    def test_prefix_counter_creation(self, setup_settings):
        """Test creating and incrementing prefix counters."""
        counter_model = PrefixCounter()

        # Get initial counter
        counter = counter_model.get_counter("ABCDEF")
        assert counter["prefix"] == "ABCDEF"
        assert counter["seq"] == 0

        # Get next IGSN
        igsn = counter_model.get_next("ABCDEF")
        assert igsn == "ABCDEF00001"

        # Get another IGSN - should increment
        igsn2 = counter_model.get_next("ABCDEF")
        assert igsn2 == "ABCDEF00002"

    def test_prefix_counter_validation(self, setup_settings):
        """Test prefix validation."""
        counter_model = PrefixCounter()

        # Test invalid prefix length
        with pytest.raises(Exception):
            counter_model.save({"prefix": "INVALID", "seq": 0})

        # Test invalid institution
        with pytest.raises(Exception):
            counter_model.save({"prefix": "ZZDEFG", "seq": 0})

        # Test invalid material
        with pytest.raises(Exception):
            counter_model.save({"prefix": "ABZZFG", "seq": 0})
