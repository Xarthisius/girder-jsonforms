#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import logging
from pathlib import Path

import cherrypy
from bson import ObjectId
from girder import events
from girder.api import access
from girder.api import rest as girderRest
from girder.api.describe import Description, autoDescribeRoute
from girder.constants import AccessType, TokenScope
from girder.exceptions import GirderException, ValidationException
from girder.models.file import File
from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.setting import Setting
from girder.models.user import User
from girder.plugin import GirderPlugin, registerPluginStaticContent
from girder.utility import search
from girder.utility.model_importer import ModelImporter

from .lib.google_drive import authenticate_gdrive, upload_file_to_gdrive
from .lib.jq import convert_dates
from .models.deposition import Deposition as DepositionModel
from .models.deposition import PrefixCounter as PrefixCounterModel
from .models.entry import FormEntry as FormEntryModel
from .models.form import Form as FormModel
from .rest.deposition import Deposition
from .rest.entry import FormEntry
from .rest.form import Form
from .settings import PluginSettings
from .worker_plugin.delete_folder import run as delete_folder_task

GDRIVE_SERVICE = None
logger = logging.getLogger(__name__)


def annotate_uploads(event):
    file = event.info["file"]
    if "itemId" not in file:
        return

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

    if not isinstance(reference, dict) or not reference.get("igsn") or not reference.get("type"):
        return

    item = Item().load(file["itemId"], force=True)
    if item is None:
        return
    Item().setMetadata(item, {"igsn": reference["igsn"], "type": reference["type"]})


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
            results[modelName] = [
                model.filter(obj, user)
                for obj in model.filterResultsByPermission(
                    cursor, user, level, limit=limit, offset=offset
                )
            ]
        else:
            results[modelName] = list(
                model.find(query, fields=allowed[modelName], limit=limit, offset=offset)
            )
    return results


def search_by_user(query, types, user, level, limit, offset):
    allowed = {
        "folder": ["_id", "name", "description", "parentId", "meta.user", "created"],
        "item": ["_id", "name", "description", "folderId", "meta.user", "created"],
        "deposition": [
            "_id",
            "created",
            "igsn",
            "metadata.alternateIdentifiers",
            "metadata.titles",
            "metadata.descriptions",
        ],
    }
    results = {_type: [] for _type in types if _type in allowed}
    if not query:
        return results

    try:
        ObjectId(query)
        creator = User().load(query, level=AccessType.READ, user=user, exc=True)
    except Exception:
        return results

    for modelName in types:
        if modelName not in allowed:
            continue
        if modelName == "deposition":
            model = DepositionModel()
        else:
            model = ModelImporter.model(modelName)
            if model is None:
                continue
        cursor = model.find(
            {"creatorId": creator["_id"]},
            fields=allowed[modelName] + ["public", "access"],
            sort=[("created", -1)],
        )
        results[modelName] = [
            model.filter(obj, user)
            for obj in model.filterResultsByPermission(
                cursor, user, level, limit=limit, offset=offset
            )
        ]
    return results


def igsn_text_search(query, types, user, level, limit, offset):
    results = {}
    allowed = {
        "deposition": [
            "_id",
            "igsn",
            "metadata.alternateIdentifiers",
            "metadata.titles",
            "metadata.descriptions",
        ],
    }
    query = {
        "$or": [
            {"igsn": {"$regex": query, "$options": "i"}},
            {
                "metadata.alternateIdentifiers.alternateIdentifier": {
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
        attrs = entry["metadata"].get("alternateIdentifiers", [])
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


@access.user(scope=TokenScope.DATA_OWN)
@girderRest.boundHandler
def _delayed_delete_folder(self, event):
    folderId = event.info["id"]
    user = self.getCurrentUser()
    folder = Folder().load(folderId, user=user, level=AccessType.ADMIN)

    if not folder:
        return  # proceed as normal and let girder handle the error

    params = event.info["params"]
    try:
        countdown = float(params.get("countdown", "0"))
        if countdown <= 0:
            raise ValueError
    except ValueError:
        return  # proceed as normal and let girder handle the deletion immediately

    delete_folder_task.apply_async(
        args=(),
        kwargs={
            "folderId": str(folder["_id"]),
            "progress": params.get("progress", False),
            "userId": str(user["_id"]),
            "girder_job_title": f"Delete temporary folder '{folder['name']}'",
        },
        countdown=countdown,
    )
    event.preventDefault().addResponse(
        {
            "message": f"Marked folder {folder['name']} for deletion in {countdown} seconds"
        }
    )


@access.user
@autoDescribeRoute(
    Description("Search items using mongo query syntax.")
    .jsonParam("query", "The MongoDB query to apply.", requireObject=True)
    .pagingParams(defaultSort="lowerName")
    .errorResponse()
    .errorResponse("You are not authorized to search items.", 403)
)
@girderRest.boundHandler
def _item_advanced_search(self, query, limit, offset, sort):
    user = self.getCurrentUser()
    query = convert_dates(query)
    cursor = Item().findWithPermissions(
        query, sort=sort, user=user, level=AccessType.READ, limit=limit, offset=offset
    )
    if callable(getattr(cursor, "count", None)):
        cherrypy.response.headers["Girder-Total-Count"] = cursor.count()
    return [Item().filter(doc, user) for doc in cursor]


class JSONFormsPlugin(GirderPlugin):
    DISPLAY_NAME = "JSON Forms"

    def load(self, info):
        from girder.api.v1.folder import Folder as FolderResource  # noqa: F401

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
        info["apiRoot"].item.route("GET", ("query",), _item_advanced_search)
        info["apiRoot"].form = Form()
        info["apiRoot"].entry = FormEntry()
        info["apiRoot"].deposition = Deposition()
        try:
            DepositionModel().validate({})  # To initialize the model and bind events
        except ValidationException:
            pass
        events.bind("data.process", "jsonforms", annotate_uploads)
        events.bind(
            "rest.delete.folder/:id.before", "jsonforms", _delayed_delete_folder
        )
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
        try:
            search.addSearchMode("byCreator", search_by_user)
        except GirderException:
            logger.warning("byCreator search mode already registered.")

        FolderResource.deleteFolder.description.param(
            "countdown",
            (
                "Number of seconds into the future that the task should execute. "
                "Defaults to immediate execution."
            ),
            required=False,
            dataType="float",
        )

        registerPluginStaticContent(
            plugin="jsonforms",
            css=["/style.css"],
            js=["/girder-plugin-jsonforms.umd.cjs"],
            staticDir=Path(__file__).parent / "web_client" / "dist",
            tree=info["serverRoot"],
        )
