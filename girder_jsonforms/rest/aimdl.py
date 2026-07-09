import hashlib
import json
import logging

import dateutil.parser
import pymongo
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, boundHandler, filtermodel
from girder.constants import AccessType, TokenScope
from girder.exceptions import RestException
from girder.models.collection import Collection
from girder.models.item import Item
from girder.models.user import User

_AIMDL_COLLECTION_ID = "665de536bcc722774ce53754"  # TODO: make this configurable
logger = logging.getLogger(__name__)


def deterministic_sort(sort):
    # Ensure that the sort order is deterministic by adding _id as a tiebreaker
    if sort is None:
        return [("_id", 1)]
    if not any(field == "_id" for field, _ in sort):
        sort.append(("_id", 1))
    return sort


def parse_dates(data):
    if isinstance(data, dict):
        return {k: parse_dates(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [parse_dates(item) for item in data]
    elif isinstance(data, str):
        # Skip purely numeric strings so IDs or counts aren't converted to dates
        if data.isdigit():
            return data
        try:
            # fuzzy=False ensures it doesn't grab dates out of normal sentences
            return dateutil.parser.parse(data, fuzzy=False)
        except (ValueError, TypeError):
            return data
    return data


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
    )
    def count_datafiles(self, baseParentType, baseParentId):
        base_parent = self._get_base_parent(
            baseParentType, baseParentId, user=self.getCurrentUser()
        )
        pipeline = [
            {"$match": base_parent},
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
            q["meta.experiment_date"] = experiment_date
        elif dataType.startswith("pdv") or dataType.startswith("nmd"):
            q["meta.experiment_date"] = {"$regex": f"^{experiment_date}"}
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
                if ignore_time:
                    experiment_date = (
                        dateutil.parser.parse(item["meta"]["experiment_date"])
                        .date()
                        .isoformat()
                    )
                else:
                    experiment_date = item["meta"]["experiment_date"]
                key = item["meta"]["igsn"] + "//" + experiment_date
            except KeyError:
                logger.warning(
                    "Item {} is missing either an IGSN or an experiment date.".format(
                        item["_id"]
                    )
                )
                continue
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
        filters = parse_dates(filters) if filters else {}
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
