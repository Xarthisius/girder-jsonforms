#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import logging
from pathlib import Path

from girder import events
from girder.constants import AccessType
from girder.exceptions import GirderException
from girder.models.file import File
from girder.models.item import Item
from girder.models.setting import Setting
from girder.plugin import GirderPlugin, registerPluginStaticContent
from girder.utility import search
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


def igsn_search(query, types, user, level, limit, offset):
    results = {}
    allowed = {
        "folder": ["_id", "name", "description", "parentId", "meta.igsn"],
        "item": ["_id", "name", "description", "folderId", "meta.igsn"],
    }
    query = {"meta.igsn": {"$regex": query, "$options": "i"}}
    for modelName in types:
        if modelName not in allowed:
            continue
        model = ModelImporter.model(modelName)
        if model is None:
            continue
        if hasattr(model, "filterResultsByPermission"):
            cursor = model.find(query, fields=allowed[modelName] + ["public", "access"])
            results[modelName] = list(
                model.filterResultsByPermission(
                    cursor, user, level, limit=limit, offset=offset
                )
            )
        else:
            results[modelName] = list(
                model.find(query, fields=allowed[modelName], limit=limit, offset=offset)
            )
    return results


def igsn_text_search(query, types, user, level, limit, offset):
    results = {}
    allowed = {
        "deposition": [
            "_id",
            "igsn",
            "metadata.attributes.alternateIdentifiers",
            "metadata.titles",
            "metadata.descriptions",
        ],
    }
    query = {
        "$or": [
            {"igsn": {"$regex": query, "$options": "i"}},
            {
                "metadata.attributes.alternateIdentifiers.alternateIdentifier": {
                    "$regex": query,
                    "$options": "i",
                }
            },
            {"metadata.titles.title": {"$regex": query, "$options": "i"}},
            {"metadata.descriptions.description": {"$regex": query, "$options": "i"}},
        ]
    }
    for modelName in types:
        if modelName not in allowed:
            continue
        cursor = DepositionModel().find(
            query, fields=allowed[modelName] + ["public", "access"]
        )
        results[modelName] = list(
            DepositionModel().filterResultsByPermission(
                cursor, user, level, limit=limit, offset=offset
            )
        )
    for entry in results["deposition"]:
        local_id = None
        attrs = entry["metadata"].get("attributes", {}).get("alternateIdentifiers", [])
        for attr in attrs:
            if attr["alternateIdentifierType"].lower() == "local":
                local_id = attr["alternateIdentifier"]
                break
        if local_id:
            tag = f"{entry['igsn']} ({local_id})"
        else:
            tag = f"{entry['igsn']}"
        entry["name"] = f"{tag} - {entry['metadata']['titles'][0]['title']}"
    return results


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
        DepositionModel().validate({})  # To initialize the model and bind events
        events.bind("data.process", "jsonforms", annotate_uploads)
        if GDRIVE_SERVICE is not None:
            events.bind("gdrive.upload", "jsonforms", upload_to_gdrive)
        try:
            search.addSearchMode("igsn", igsn_search)
        except GirderException:
            logger.warning("IGSN search mode already registered.")
        try:
            search.addSearchMode("igsnText", igsn_text_search)
        except GirderException:
            logger.warning("IGSN text search mode already registered.")
        registerPluginStaticContent(
            plugin="jsonforms",
            css=["/style.css"],
            js=["/girder-plugin-jsonforms.umd.cjs"],
            staticDir=Path(__file__).parent / "web_client" / "dist",
            tree=info["serverRoot"],
        )
