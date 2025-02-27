import pytest
from girder import plugin
from girder.models.setting import Setting
from girder_jsonforms.settings import PluginSettings


@pytest.fixture
def enable_gdrive(db):
    Setting().set(PluginSettings.GOOGLE_DRIVE_ENABLED, True)
    yield
    Setting().set(PluginSettings.GOOGLE_DRIVE_ENABLED, False)


@pytest.fixture
def mock_authorization(mocker):
    mock_auth = mocker.patch("girder_jsonforms.authenticate_gdrive")
    mock_auth.return_value = {"status": "Authorized"}
    return mock_auth


@pytest.fixture
def mock_apiRoot(mocker):
    mock_api = mocker.Mock()
    return mock_api


@pytest.mark.plugin("jsonforms")
def test_disabled_gdrive():
    from girder_jsonforms import GDRIVE_SERVICE as GDRIVE

    assert GDRIVE is None, "Google Drive plugin should be disabled"


def test_enabled_gdrive(enable_gdrive, mock_authorization, mock_apiRoot):
    assert plugin.loadedPlugins() == []

    plugin._loadPlugins(
        info={"apiRoot": mock_apiRoot, "serverRoot": mock_apiRoot}, names=["jsonforms"]
    )

    from girder_jsonforms import GDRIVE_SERVICE as GDRIVE

    assert GDRIVE == {"status": "Authorized"}, "Google Drive should be enabled"
