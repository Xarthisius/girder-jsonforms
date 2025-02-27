from girder.exceptions import ValidationException
from girder.utility import setting_utilities


class PluginSettings:
    GOOGLE_DRIVE_ENABLED = "jsonforms.google_drive_enabled"


@setting_utilities.default(PluginSettings.GOOGLE_DRIVE_ENABLED)
def default_google_drive_enabled():
    """
    Default setting for enabling Google Drive integration.
    """
    return False


@setting_utilities.validator(PluginSettings.GOOGLE_DRIVE_ENABLED)
def validate_google_drive_enabled(doc):
    """
    Validate the Google Drive integration setting.
    """
    if not isinstance(doc["value"], bool):
        raise ValidationException(
            "Google Drive integration must be a boolean.",
            "value",
        )
