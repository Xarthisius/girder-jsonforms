#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import logging
from pathlib import Path

import cherrypy
import pandas as pd
from bson import ObjectId
from girder import events
from girder.api import access
from girder.api import rest as girderRest
from girder.api.describe import Description, autoDescribeRoute
from girder.constants import AccessType, TokenScope, registerAccessFlag
from girder.exceptions import GirderException, ValidationException
from girder.models.collection import Collection
from girder.models.file import File
from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.setting import Setting
from girder.models.user import User
from girder.plugin import GirderPlugin, registerPluginStaticContent
from girder.utility import search
from girder.utility.model_importer import ModelImporter

from .lib.announcement import Announcement
from .lib.google_drive import authenticate_gdrive, upload_file_to_gdrive
from .lib.jq import convert_dates
from .lib.events import ensure_group
from .models.deposition import Deposition as DepositionModel
from .models.deposition import PrefixCounter as PrefixCounterModel
from .models.entry import FormEntry as FormEntryModel
from .models.form import Form as FormModel
from .models.project import Project as ProjectModel
from .rest.aimdl import AIMDL, append_vega
from .rest.deposition import Deposition
from .rest.entry import FormEntry
from .rest.form import Form
from .settings import IGSN_REGEX, PluginSettings
from .rest.project import Project
from .worker_plugin.amdee import register_deposition_with_aimd
from .worker_plugin.folder_ops import assign_igsn_task, delete_folder_task

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

    if (
        not isinstance(reference, dict)
        or not reference.get("igsn")
        or not reference.get("type")
    ):
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


@access.user(scope=TokenScope.DATA_WRITE)
@girderRest.boundHandler
@autoDescribeRoute(
    Description("Assign an IGSN to all files withing a folder recursively.")
    .modelParam(
        "id", "The ID of the folder to process.", model=Folder, level=AccessType.WRITE
    )
    .param(
        "igsn",
        "The IGSN to assign to the folder.",
        paramType="query",
        required=True,
        dataType="string",
    )
    .param(
        "progress",
        "Whether to report progress.",
        paramType="query",
        required=False,
        dataType="boolean",
        default=False,
    )
    .errorResponse("ID was invalid.", 400)
    .errorResponse("IGSN was invalid.", 400)
    .errorResponse("Write access was denied on the folder.", 403)
)
def _assign_igsn_to_folder(self, folder, igsn, progress):
    if not IGSN_REGEX.match(igsn):
        raise ValidationException(f"IGSN {igsn} is not valid.", "igsn")
    assign_igsn_task.delay(
        folderId=str(folder["_id"]),
        progress=progress,
        igsn=igsn,
        userId=str(self.getCurrentUser()["_id"]),
        itemsOnly=True,
    )
    return {
        "message": f"Assigning IGSN {igsn} to all files in folder {folder['name']}."
    }


@access.public(scope=TokenScope.DATA_READ)
@girderRest.filtermodel(model=Collection)
@girderRest.boundHandler
def _search_collection_by_name(self, event):
    params = event.info["params"]
    if not params.get("name"):
        return

    filters = {"name": params["name"]}
    if text := params.get("text"):
        filters["$text"] = {"$search": text}

    limit, offset, sort = self.getPagingParameters(params, "name")
    event.preventDefault().addResponse(
        Collection().findWithPermissions(
            filters,
            sort=sort,
            user=self.getCurrentUser(),
            level=AccessType.READ,
            limit=limit,
            offset=offset,
        )
    )


@access.public
def announce(event):
    item = event.info
    metadata = item.get("meta", {})
    if not metadata:
        return

    igsn = metadata.get("igsn")
    data_type = metadata.get("data_type")
    if not igsn or data_type != "pdv_alpss_result":
        return

    try:
        for fobj in Item().childFiles(item, limit=1):
            with File().open(fobj) as fptr:
                df = pd.read_csv(fptr)
            data = json.loads(json.dumps(df.to_dict(orient="records")[0]))
            data["igsn"] = igsn
            data["itemId"] = str(item["_id"])
            data["experiment_date"] = metadata.get("experiment_date")
            Announcement("pdv_alpss_result", data).flush()
    except Exception:
        logger.exception("Failed to announce item %s", item["_id"])


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


def handle_deposition_registration(event: events.Event) -> None:
    ids = event.info.get("ids", [])
    if not ids:
        return
    cursor = DepositionModel().collection.find(
        {"_id": {"$in": [ObjectId(_id) for _id in ids]}}, {"_id": 1, "igsn": 1}
    )
    data = [{"_id": str(doc["_id"]), "igsn": doc.get("igsn")} for doc in cursor]
    register_deposition_with_aimd.delay(
        data, girder_job_title=f"Registering {len(data)} deposition(s) with AIMD"
    )


@access.public
@girderRest.boundHandler
def add_public_settings(self, event):
    print(event.info)
    settings = event.info["returnVal"]
    public_settings = [PluginSettings.AIMDL_COUNTS]
    settings.update({key: Setting().get(key) for key in public_settings})


class JSONFormsPlugin(GirderPlugin):
    DISPLAY_NAME = "JSON Forms"

    def load(self, info):
        from girder.api.v1.collection import (
            Collection as CollectionResource,  # noqa: F401
        )
        from girder.api.v1.folder import Folder as FolderResource  # noqa: F401

        Item().ensureIndices([("meta.data_type", {"unique": False})])
        ModelImporter.registerModel("deposition", DepositionModel, plugin="jsonforms")
        ModelImporter.registerModel("entry", FormEntryModel, plugin="jsonforms")
        ModelImporter.registerModel("form", FormModel, plugin="jsonforms")
        ModelImporter.registerModel("project", ProjectModel, plugin="jsonforms")
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
        info["apiRoot"].folder.route(
            "PUT", (":id", "assign_igsn"), _assign_igsn_to_folder
        )
        info["apiRoot"].aimdl = AIMDL()
        info["apiRoot"].form = Form()
        info["apiRoot"].entry = FormEntry()
        info["apiRoot"].deposition = Deposition()
        info["apiRoot"].project = Project()
        try:
            DepositionModel().validate({})  # To initialize the model and bind events
        except ValidationException:
            pass
        events.bind("data.process", "jsonforms", annotate_uploads)
        events.bind("deposition.created", "jsonforms", handle_deposition_registration)
        events.bind(
            "rest.delete.folder/:id.before", "jsonforms", _delayed_delete_folder
        )
        events.bind(
            "rest.get.collection.before", "jsonforms", _search_collection_by_name
        )
        events.bind("rest.get.item/:id.after", "jsonforms", append_vega)
        events.bind("model.item.save.after", "jsonforms", announce)
        events.bind(
            "rest.get.system/public_settings.after", "jsonforms", add_public_settings
        )
        events.bind("model.project.save", "jsonforms", ensure_group)
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
        CollectionResource.find.description.param(
            "name",
            "Pass to lookup a collection by exact name match.",
            required=False,
            dataType="string",
        )

        Collection().createCollection(
            Setting().get(PluginSettings.PROJECTS_COLLECTION_NAME),
            creator=User().findOne({"admin": True}),
            public=True,
            reuseExisting=True,
        )

        registerPluginStaticContent(
            plugin="jsonforms",
            css=["/style.css"],
            js=["/girder-plugin-jsonforms.umd.cjs"],
            staticDir=Path(__file__).parent / "web_client" / "dist",
            tree=info["serverRoot"],
        )

        registerAccessFlag(
            key="jsonforms.review_projects",
            name="Review Projects",
            description="Allow users to review and approve projects.",
        )
