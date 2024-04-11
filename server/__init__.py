#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json

from girder import events, logger
from girder.constants import AccessType
from girder.models.item import Item
from girder.models.file import File

from .rest.entry import FormEntry
from .rest.form import Form
from .lib.google_drive import authenticate_gdrive, upload_file_to_gdrive


GDRIVE_SERVICE = None


def annotate_uploads(event):
    info = event.info
    if "reference" not in info:
        return

    try:
        reference = json.loads(info["reference"])
    except (ValueError, TypeError):
        return

    if "sampleId" in reference:
        parent = Item().load(
            info["file"]["itemId"], level=AccessType.WRITE, user=info["currentUser"]
        )

        reference.pop("file", None)
        Item().setMetadata(parent, reference)


def upload_to_gdrive(event):
    global GDRIVE_SERVICE
    info = event.info
    file = info["file"]

    with File().open(info["file"]) as fh:
        gdrive_file_id = upload_file_to_gdrive(
            GDRIVE_SERVICE,
            info["gdriveFolderId"],
            info["path"],
            fh,
            mimetype=file["mimeType"],
        )
    parent = Item().load(
        info["file"]["itemId"], level=AccessType.WRITE, user=info["currentUser"]
    )
    Item().setMetadata(parent, {"gdriveFileId": gdrive_file_id})


def load(info):
    global GDRIVE_SERVICE
    try:
        GDRIVE_SERVICE = authenticate_gdrive()
    except ValueError:
        logger.exception("Failed to authenticate with Google Drive")
    info["apiRoot"].form = Form()
    info["apiRoot"].entry = FormEntry()
    events.bind("data.process", "jsonforms", annotate_uploads)
    events.bind("gdrive.upload", "jsonforms", upload_to_gdrive)
