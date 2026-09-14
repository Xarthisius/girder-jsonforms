"""The config gate on ORCID research-resource registration.

Writing a research resource needs the ``/activities/update`` scope, which only
the sandbox provider requests, so accepting a project must not fire this at
production ORCID.
"""

from unittest.mock import patch

import pytest
from girder.models.setting import Setting
from girder_wholetale.lib.orcid import ORCID, SandboxORCID

from ..lib.orcid import get_orcid_provider
from ..settings import PluginSettings
from ..worker_plugin.orcid import (
    register_project_with_orcid,
    research_resources_enabled,
)


@pytest.fixture
def research_resources(db):
    """Set the gate explicitly, and put it back afterwards."""

    def _set(enabled):
        Setting().set(PluginSettings.ORCID_RESEARCH_RESOURCES, enabled)

    yield _set
    Setting().unset(PluginSettings.ORCID_RESEARCH_RESOURCES)


@pytest.mark.plugin("jsonforms")
def test_defaults_to_production_orcid_with_writes_off(db):
    """The out-of-the-box posture: read production, write nothing.

    Both gates are shut by default -- the setting is off, and the production
    provider could not satisfy the scope check even if it were on.
    """
    assert Setting().get(PluginSettings.ORCID_PROVIDER) == "orcid"
    assert get_orcid_provider() is ORCID
    assert Setting().get(PluginSettings.ORCID_RESEARCH_RESOURCES) is False
    assert research_resources_enabled(get_orcid_provider()) is False


@pytest.mark.plugin("jsonforms")
def test_off_by_default_even_for_sandbox(research_resources):
    """Opting in is required; being on the sandbox is not enough on its own."""
    assert research_resources_enabled(SandboxORCID) is False
    research_resources(True)
    assert research_resources_enabled(SandboxORCID) is True


@pytest.mark.plugin("jsonforms")
def test_production_orcid_is_refused_even_when_enabled(research_resources):
    """Production ORCID never requests the write scope, so the gate holds."""
    research_resources(True)
    assert ORCID._AUTH_SCOPES == ["/authenticate"]
    assert research_resources_enabled(ORCID) is False


@pytest.mark.plugin("jsonforms")
@pytest.mark.parametrize(
    "provider,enabled",
    [
        # Gate closed by the setting.
        (SandboxORCID, False),
        # Gate closed by the missing write scope, setting notwithstanding.
        (ORCID, True),
    ],
)
def test_gated_task_returns_before_touching_anything(
    provider, enabled, research_resources, admin
):
    """The gate short-circuits ahead of the user/token lookup, not just the POST.

    Asserting on ``User`` rather than ``requests`` is what makes this specific:
    the task has other early returns further down (no matching token, project
    not accepted) that would also leave ``requests`` untouched.
    """
    research_resources(enabled)
    with (
        patch(
            "girder_jsonforms.worker_plugin.orcid.get_orcid_provider",
            return_value=provider,
        ),
        patch("girder_jsonforms.worker_plugin.orcid.User") as mock_user,
        patch("girder_jsonforms.worker_plugin.orcid.requests") as mock_requests,
    ):
        register_project_with_orcid(str(admin["_id"]), str(admin["_id"]))

    mock_user.assert_not_called()
    mock_requests.post.assert_not_called()
    mock_requests.put.assert_not_called()


@pytest.mark.plugin("jsonforms")
def test_open_gate_lets_the_task_proceed(research_resources, admin):
    """Control for the test above: an open gate does not short-circuit."""
    research_resources(True)
    with (
        patch(
            "girder_jsonforms.worker_plugin.orcid.get_orcid_provider",
            return_value=SandboxORCID,
        ),
        patch("girder_jsonforms.worker_plugin.orcid.User") as mock_user,
    ):
        register_project_with_orcid(str(admin["_id"]), str(admin["_id"]))

    mock_user.assert_called()
