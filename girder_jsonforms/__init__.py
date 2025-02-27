#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import logging
from pathlib import Path

from girder import events
from girder.constants import AccessType
from girder.models.file import File
from girder.models.item import Item
from girder.models.setting import Setting
from girder.plugin import GirderPlugin, registerPluginStaticContent
from girder.utility.model_importer import ModelImporter

from .lib.google_drive import authenticate_gdrive, upload_file_to_gdrive
from .models.deposition import Deposition as DepositionModel
from .models.deposition import PrefixCounter as PrefixCounterModel
from .models.entry import FormEntry as FormEntryModel
from .models.form import Form as FormModel
from .rest.deposition import Deposition
from .rest.entry import FormEntry
from .rest.form import Form
from .settings import PluginSettings

GDRIVE_SERVICE = None
logger = logging.getLogger(__name__)


def annotate_uploads(event):
    info = event.info
    if "reference" not in info:
        return

    try:
        reference = json.loads(info["reference"])
    except (ValueError, TypeError):
        return

    if reference.get("annotate"):
        parent = Item().load(
            info["file"]["itemId"], level=AccessType.WRITE, user=info["currentUser"]
        )
        reference.pop("file", None)
        reference.pop("annotate", None)
        Item().setMetadata(parent, reference)


def upload_to_gdrive(event):
    global GDRIVE_SERVICE
    if GDRIVE_SERVICE is None:
        logger.error("Google Drive integration is not enabled.")
        return
    info = event.info
    file = info["file"]

    with File().open(file) as fh:
        gdrive_file_id = upload_file_to_gdrive(
            GDRIVE_SERVICE,
            info["gdriveFolderId"],
            info["path"],
            fh,
            mimetype=file["mimeType"],
        )
    parent = Item().load(
        file["itemId"], level=AccessType.WRITE, user=info["currentUser"]
    )
    Item().setMetadata(parent, {"gdriveFileId": gdrive_file_id})


class JSONFormsPlugin(GirderPlugin):
    DISPLAY_NAME = "JSON Forms"

    def load(self, info):
        ModelImporter.registerModel("deposition", DepositionModel, plugin="jsonforms")
        ModelImporter.registerModel("entry", FormEntryModel, plugin="jsonforms")
        ModelImporter.registerModel("form", FormModel, plugin="jsonforms")
        ModelImporter.registerModel(
            "prefixcounter", PrefixCounterModel, plugin="jsonforms"
        )
        global GDRIVE_SERVICE
        if Setting().get(PluginSettings.GOOGLE_DRIVE_ENABLED):
            try:
                GDRIVE_SERVICE = authenticate_gdrive()
            except ValueError:
                logger.exception("Failed to authenticate with Google Drive")
        info["apiRoot"].form = Form()
        info["apiRoot"].entry = FormEntry()
        info["apiRoot"].deposition = Deposition()
        events.bind("data.process", "jsonforms", annotate_uploads)
        if GDRIVE_SERVICE is not None:
            events.bind("gdrive.upload", "jsonforms", upload_to_gdrive)
        registerPluginStaticContent(
            plugin="jsonforms",
            css=["/style.css"],
            js=["/girder-plugin-jsonforms.umd.cjs"],
            staticDir=Path(__file__).parent / "web_client" / "dist",
            tree=info["serverRoot"],
        )
