import copy
import datetime
import hashlib
import json
import logging
import os
import re

import dateutil.parser
import pandas as pd
import pymongo
from bson import Regex
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, boundHandler, filtermodel
from girder.constants import AccessType, TokenScope
from girder.exceptions import RestException
from girder.models.collection import Collection
from girder.models.file import File
from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.user import User

from ..lib.announcement import Announcement
from ..lib.metadata_dates import _parse_iso, coerce_dates
from ..models.project import Project

_AIMDL_COLLECTION_ID = os.environ.get(
    "AIMDL_COLLECTION_ID", "665de536bcc722774ce53754"
)  # TODO: make this configurable
ALLOWED_OPERATORS = {"$eq", "$ne", "$gt", "$gte", "$lt", "$lte", "$in", "$nin"}
ALLOWED_FIELDS = {
    "created",
    "creatorId",
    "description",
    "folderId",
    "meta",
    "meta.data_type",
    "meta.igsn",
    "meta.experiment_date",
    "meta.alpss_output_name",
    "name",
    "size",
    "updated",
}

logger = logging.getLogger(__name__)


def sanitize_query(data):
    if isinstance(data, (re.Pattern, Regex)):
        raise ValueError("Regex objects are not allowed")

    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            # Block keys starting with $ unless they are in the whitelist
            if k.startswith("$") and k not in ALLOWED_OPERATORS:
                raise ValueError(f"Unauthorized operator used: {k}")
            sanitized[k] = sanitize_query(v)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_query(item) for item in data]
    return data


def validate_fields(data):
    if isinstance(data, dict):
        for k, v in data.items():
            if not k.startswith("$") and k not in ALLOWED_FIELDS:
                raise ValueError(f"Unauthorized query field: {k}")
            validate_fields(v)
    elif isinstance(data, list):
        for item in data:
            validate_fields(item)


def deterministic_sort(sort):
    # Ensure that the sort order is deterministic by adding _id as a tiebreaker
    if sort is None:
        return [("_id", 1)]
    if not any(field == "_id" for field, _ in sort):
        sort.append(("_id", 1))
    return sort


def _format_experiment_date(value, ignore_time=False):
    """Render a stored ``meta.experiment_date`` as the string used in a
    partition key.

    ``experiment_date`` is normally a BSON ``datetime`` (coerced on save by
    :mod:`girder_jsonforms.lib.metadata_dates`). Legacy, un-migrated documents
    may still hold a string, which is handled best-effort.
    """
    if isinstance(value, datetime.datetime):
        return value.date().isoformat() if ignore_time else value.isoformat()
    # Legacy string value (pre-migration).
    if ignore_time:
        try:
            return dateutil.parser.parse(value).date().isoformat()
        except (ValueError, TypeError):
            return str(value)
    return str(value)


def _experiment_date_query(date_str, ignore_time=False):
    """Build a Mongo query for ``meta.experiment_date`` from the date component
    of a partition key so it matches stored BSON datetimes.

    ``ignore_time`` matches the whole calendar day (a half-open range) rather
    than an exact instant. If the key component is not ISO-8601 (legacy string
    storage) we fall back to string/regex matching so un-migrated data still
    resolves.
    """
    parsed = _parse_iso(date_str)
    if parsed is None:
        # Not ISO -> assume the value was stored as a plain string.
        return {"$regex": f"^{re.escape(date_str)}"} if ignore_time else date_str
    if ignore_time:
        start = datetime.datetime(
            parsed.year, parsed.month, parsed.day, tzinfo=datetime.timezone.utc
        )
        return {"$gte": start, "$lt": start + datetime.timedelta(days=1)}
    return parsed


class AIMDL(Resource):
    def __init__(self):
        super().__init__()
        self.resourceName = "aimdl"
        self.route("GET", ("count",), self.count_datafiles)
        self.route("GET", ("datatype",), self.get_datatypes)
        self.route("GET", ("datafiles",), self.get_items_by_datatype)
        self.route("GET", ("partition",), self.list_partitions)
        self.route("GET", ("partition", "details"), self.get_partition)

    @staticmethod
    def _get_base_parent(parentType=None, parentId=None, user=None):
        if not parentType or not parentId:
            aimdl_collection = Collection().load(_AIMDL_COLLECTION_ID, force=True)
            if not aimdl_collection:
                raise RestException(
                    "AIMDL collection not found. Please ensure the collection exists.",
                    code=404,
                )
            return {
                "baseParentId": aimdl_collection["_id"],
                "baseParentType": "collection",
            }
        if parentType == "collection":
            parent = Collection().load(
                parentId, user=user, level=AccessType.READ, exc=True
            )
        elif parentType == "user":
            parent = User().load(parentId, user=user, level=AccessType.READ, exc=True)
        else:
            raise RestException("Invalid parent type: {}".format(parentType), code=400)
        return {"baseParentId": parent["_id"], "baseParentType": parentType}

    @access.public
    @autoDescribeRoute(
        Description("Count the number of data files per type in the AIMDL collection.")
        .param(
            "baseParentId",
            "The ID of the parent collection to count items in.",
            required=False,
        )
        .param(
            "baseParentType",
            "The type of the parent",
            enum=["user", "collection"],
            required=False,
        )
        .param(
            "igsn",
            "The IGSN to filter items by.",
            required=False,
        )
    )
    def count_datafiles(self, baseParentType, baseParentId, igsn):
        query = self._get_base_parent(
            baseParentType, baseParentId, user=self.getCurrentUser()
        )
        if igsn:
            query["meta.igsn"] = igsn
        pipeline = [
            {"$match": query},
            {"$group": {"_id": "$meta.data_type", "count": {"$sum": 1}}},
        ]
        results = {}
        for result in Item().collection.aggregate(pipeline):
            if result["_id"] is not None:
                results[result["_id"]] = result["count"]
            else:
                results["unclassified"] = result["count"]
        return results

    @access.user
    @autoDescribeRoute(
        Description("Get a list of available data types for AIMDL.").errorResponse(
            "You are not authorized to access this resource.", 403
        )
    )
    def get_datatypes(self):
        """
        Get a list of available data types for AIMDL.
        """
        return Item().collection.distinct("meta.data_type")

    @access.user
    @autoDescribeRoute(
        Description("Get a list of IGSNS for a given dataType")
        .param("dataType", "The data type to filter items by.", required=True)
        .param(
            "since",
            "Only return items updated since this date (ISO 8601 format).",
            required=False,
        )
        .param(
            "baseParentId",
            "The ID of the parent collection to count items in.",
            required=False,
        )
        .param(
            "baseParentType",
            "The type of the parent",
            enum=["user", "collection"],
            required=False,
        )
        .errorResponse("You are not authorized to access this resource.", 403)
    )
    def list_partitions(self, dataType, since, baseParentType, baseParentId):
        """
        Get a list of IGSNS and correspoding items
        """
        user = self.getCurrentUser()
        base_parent = self._get_base_parent(baseParentType, baseParentId, user)
        q = {
            "meta.data_type": dataType,
            "meta.igsn": {"$exists": True},
        }
        q.update(base_parent)
        if since:
            q["updated"] = {"$gt": dateutil.parser.parse(since)}

        if dataType.startswith("xrd") or dataType.startswith("xrf"):
            return self._igsn_date_map(q, user=user)
        elif dataType.startswith("pdv") or dataType.startswith("nmd"):
            return self._igsn_date_map(q, user=user, ignore_time=True)
        else:
            raise RestException(
                f"Data type {dataType} is not supported for partitions."
            )

    @access.user
    @autoDescribeRoute(
        Description("Get a Dagster partition for a given dataType")
        .param("key", "The partition key", required=True)
        .param("dataType", "The data type to filter items by.", required=False)
        .param(
            "baseParentId",
            "The ID of the parent collection to count items in.",
            required=False,
        )
        .param(
            "baseParentType",
            "The type of the parent",
            enum=["user", "collection"],
            required=False,
        )
        .errorResponse("You are not authorized to access this resource.", 403)
    )
    @filtermodel(model=Item)
    def get_partition(self, key, dataType, baseParentType, baseParentId):
        try:
            igsn, experiment_date = key.split("//")
        except ValueError:
            raise RestException(
                "Invalid partition key format. Expected 'igsn//experiment_date',"
                f"got '{key}'."
            )
        user = self.getCurrentUser()
        base_parent = self._get_base_parent(baseParentType, baseParentId, user)
        q = {"meta.igsn": igsn}
        if dataType.startswith("xrd") or dataType.startswith("xrf"):
            q["meta.experiment_date"] = _experiment_date_query(
                experiment_date, ignore_time=False
            )
        elif dataType.startswith("pdv") or dataType.startswith("nmd"):
            q["meta.experiment_date"] = _experiment_date_query(
                experiment_date, ignore_time=True
            )
        q.update(base_parent)
        if dataType:
            q["meta.data_type"] = dataType

        return Item().findWithPermissions(q, user=user, level=AccessType.READ)

    @staticmethod
    def _igsn_date_map(q, user=None, ignore_time=False):
        fields = {
            "meta.igsn": 1,
            "meta.checksum": 1,
            "meta.experiment_date": 1,
            "folderId": 1,
            "name": 1,
            "_id": 1,
        }

        igsn_map = {}
        for item in Item().findWithPermissions(
            q, user=user, level=AccessType.READ, fields=fields
        ):
            # group by 'igsn//experiment_date'
            try:
                igsn = item["meta"]["igsn"]
                raw_date = item["meta"]["experiment_date"]
            except KeyError:
                logger.warning(
                    "Item {} is missing either an IGSN or an experiment date.".format(
                        item["_id"]
                    )
                )
                continue
            experiment_date = _format_experiment_date(raw_date, ignore_time=ignore_time)
            key = igsn + "//" + experiment_date
            if key not in igsn_map:
                igsn_map[key] = []

            try:
                igsn_map[key].append(item["meta"]["checksum"]["sha256"])
            except KeyError:
                logger.warning(
                    "Item {} is missing a sha256 checksum.".format(item["_id"])
                )
        result = {}
        for key, checksums in igsn_map.items():
            sha256 = hashlib.sha256()
            sha256.update("".join(sorted(checksums)).encode("utf-8"))
            result[key] = sha256.hexdigest()
        return result

    @access.user
    @filtermodel(model=Item)
    @autoDescribeRoute(
        Description("Get a list of items with a specific data type.")
        .param("dataType", "The data type to filter items by.", required=True)
        .param(
            "baseParentId",
            "The ID of the parent collection to count items in.",
            required=False,
        )
        .param(
            "baseParentType",
            "The type of the parent",
            enum=["user", "collection"],
            required=False,
        )
        .jsonParam(
            "extraFields",
            "JSON list of additional fields to include in the response items",
            requireArray=True,
            required=False,
        )
        .jsonParam(
            "filters",
            "A JSON object specifying additional filters to apply to the query.",
            required=False,
            requireObject=True,
        )
        .pagingParams(defaultSort="lowerName")
        .errorResponse("You are not authorized to access this resource.", 403)
    )
    def get_items_by_datatype(
        self,
        dataType,
        baseParentId,
        baseParentType,
        extraFields,
        filters,
        limit,
        offset,
        sort,
    ):
        """
        Get a list of items with a specific data type.
        """
        if limit is None:
            limit = 100
        if offset is None:
            offset = 0
        if limit > 100:
            raise RestException("Limit cannot exceed 100.")

        user = self.getCurrentUser()
        base_parent = self._get_base_parent(baseParentType, baseParentId, user)
        q = {
            "meta.igsn": {"$exists": True},
            "meta.data_type": dataType,
        }
        filters = filters or {}
        try:
            filters = sanitize_query(filters)
            validate_fields(filters)
            # Coerce date strings with the same strict rules used when the
            # metadata was stored, so filters match the BSON datetimes.
            filters = coerce_dates(filters)
        except Exception as e:
            raise RestException(f"Invalid 'filters' parameter: {e}")

        q.update(filters)
        q.update(base_parent)

        fields = {
            "name": 1,
            "meta.igsn": 1,
            "meta.data_type": 1,
            "size": 1,
            "update": 1,
            "created": 1,
            "creatorId": 1,
            "folderId": 1,
            "lowerName": 1,
            "baseParentId": 1,
            "baseParentType": 1,
            "copyOfItem": 1,
        }
        if extraFields:
            for field in extraFields:
                fields[field] = 1

        try:
            return Item().findWithPermissions(
                q,
                user=user,
                level=AccessType.READ,
                sort=deterministic_sort(sort),
                limit=limit,
                offset=offset,
                fields=fields,
            )
        except pymongo.errors.OperationFailure as e:
            raise RestException("Invalid 'extraFields' parameter: {}".format(e))


@access.public(scope=TokenScope.DATA_READ)
@boundHandler
def append_vega(self, event):
    item_response = event.info["returnVal"]
    item_response["meta"] = item_response.get("meta", {})
    vega_meta = {}
    vega_spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "width": "container",
        "mark": "line",
        "encoding": {
            "x": {"field": "x", "title": "placeholder", "type": "quantitative"},
            "y": {"field": "y", "title": "Intensity", "type": "quantitative"},
        },
    }
    if item_response["name"].endswith(".xrf"):
        vega_spec["encoding"]["x"]["title"] = "Channel"
        vega_meta.update(
            {
                "vega": json.dumps(vega_spec),
                "vega:separator": " ",
                "vega:skipRows": 11,
            }
        )
    elif item_response["name"].endswith("xrd.csv"):
        vega_spec["encoding"]["x"]["title"] = "Angle 2θ"
        vega_meta.update(
            {
                "vega": json.dumps(vega_spec),
                "vega:separator": ",",
                "vega:skipRows": 1,
            }
        )
    vega_meta.update(item_response["meta"])  # preserve existing metadata
    item_response["meta"] = vega_meta
    event.addResponse(item_response)


@access.public
def item_save(event):
    item = event.info
    metadata = item.get("meta", {})
    if not metadata:
        return

    igsn = metadata.get("igsn")
    data_type = metadata.get("data_type")
    if igsn and data_type == "pdv_alpss_result":
        announce_pdv_alpss_result(item)

    if igsn:
        propagate_to_projects(item)


def propagate_to_projects(item, sync=True):
    aimdl = AIMDL._get_base_parent()
    if item["baseParentId"] != aimdl["baseParentId"]:
        logger.debug("Item not in a blessed AIMDL collection")
        return
    # Find all the projects it belongs to
    for project in Project().use_sample(item["meta"]["igsn"]):
        if target := Item().findOne(
            {"copyOfItem": item["_id"], "projectId": project["_id"]}
        ):
            if sync:
                synchronize_item(item, target)
        else:
            propagate_item_to_project(item, project)


def propagate_item_to_project(item, project, collection=None, creator=None):
    if collection is None:
        collection = Collection().findOne({"name": project["projectId"]})

    if not collection:
        raise ValueError("Project collection not found")

    if creator is None:
        creator = User().findOne({"admin": True})

    parent = parent_type = None
    for part in Item().parentsToRoot(item, force=True):
        part_type = part["type"]
        if part_type == "collection":
            parent = collection
            parent_type = part_type
            continue
        obj = part["object"]
        parent = Folder().createFolder(
            parent,
            obj["name"],
            parentType=parent_type,
            creator=creator,
            reuseExisting=True,
        )
        parent_type = "folder"

    if Item().findOne(
        {"name": item["name"], "folderId": parent["_id"], "projectId": project["_id"]}
    ):
        logger.warning(f'Item "{item["name"]}" exists in {project["projectId"]}')
        return

    copied_item = Item().copyItem(item, creator, folder=parent)
    copied_item["projectId"] = project["_id"]
    Item().save(copied_item, triggerEvents=False)


def synchronize_item(source, target):
    creator = User().findOne({"admin": True})
    if "meta" in source:
        target["meta"] = copy.deepcopy(source["meta"])

    for file in Item().childFiles(target):
        File().remove(file, updateItemSize=False)
    for file in Item().childFiles(source):
        File().copyFile(file, creator=creator, item=target)

    for key in ["size", "updated"]:
        target[key] = source[key]

    Item().save(target, triggerEvents=False)


def announce_pdv_alpss_result(item):
    try:
        for fobj in Item().childFiles(item, limit=1):
            with File().open(fobj) as fptr:
                df = pd.read_csv(fptr)
            data = json.loads(json.dumps(df.to_dict(orient="records")[0]))
            data["igsn"] = item["meta"]["igsn"]
            data["itemId"] = str(item["_id"])
            experiment_date = item["meta"].get("experiment_date")
            if isinstance(experiment_date, datetime.datetime):
                # experiment_date is stored as a BSON datetime; emit ISO-8601
                # rather than json's default str() so consumers get a clean date.
                experiment_date = experiment_date.isoformat()
            data["experiment_date"] = experiment_date
            Announcement("pdv_alpss_result", data).flush()
    except Exception:
        logger.exception("Failed to announce item %s", item["_id"])
