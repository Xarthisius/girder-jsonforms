import hashlib
import logging

import dateutil.parser
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, filtermodel
from girder.constants import AccessType
from girder.exceptions import RestException
from girder.models.collection import Collection
from girder.models.item import Item

_AIMDL_COLLECTION_ID = "665de536bcc722774ce53754"  # TODO: make this configurable
logger = logging.getLogger(__name__)


class AIMDL(Resource):
    def __init__(self):
        super().__init__()
        self.resourceName = "aimdl"
        self.route("GET", ("count",), self.count_datafiles)
        self.route("GET", ("datatype",), self.get_datatypes)
        self.route("GET", ("datafiles",), self.get_items_by_datatype)
        self.route("GET", ("partition",), self.list_partitions)
        self.route("GET", ("partition", "details"), self.get_partition)

    @access.public
    @autoDescribeRoute(
        Description("Count the number of data files per type in the AIMDL collection.")
    )
    def count_datafiles(self):
        aimdl_collection = Collection().load(_AIMDL_COLLECTION_ID, force=True)
        if not aimdl_collection:
            raise RestException("AIMDL collection not found.", code=404)
        pipeline = [
            {
                "$match": {
                    "baseParentId": aimdl_collection["_id"],
                    "baseParentType": "collection",
                }
            },
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
        .errorResponse("You are not authorized to access this resource.", 403)
    )
    def list_partitions(self, dataType, since):
        """
        Get a list of IGSNS and correspoding items
        """
        user = self.getCurrentUser()
        aimdl_collection = Collection().load(
            _AIMDL_COLLECTION_ID, user=user, level=AccessType.READ, exc=True
        )
        q = {
            "baseParentId": aimdl_collection["_id"],
            "baseParentType": "collection",
            "meta.data_type": dataType,
            "meta.igsn": {"$exists": True},
        }
        if since:
            q["updated"] = {"$gt": dateutil.parser.parse(since)}

        if dataType.startswith("xrd"):
            return self._igsn_date_map(q, user=user)
        else:
            raise RestException(
                f"Data type {dataType} is not supported for partitions."
            )

    @access.user
    @autoDescribeRoute(
        Description("Get a Dagster partition for a given dataType")
        .param("key", "The partition key", required=True)
        .param("dataType", "The data type to filter items by.", required=False)
        .errorResponse("You are not authorized to access this resource.", 403)
    )
    @filtermodel(model=Item)
    def get_partition(self, key, dataType):
        try:
            igsn, experiment_date = key.split("//")
        except ValueError:
            raise RestException(
                "Invalid partition key format. Expected 'igsn//experiment_date',"
                f"got '{key}'."
            )
        user = self.getCurrentUser()
        aimdl_collection = Collection().load(
            _AIMDL_COLLECTION_ID, user=user, level=AccessType.READ, exc=True
        )
        q = {
            "baseParentId": aimdl_collection["_id"],
            "baseParentType": "collection",
            "meta.igsn": igsn,
            "meta.experiment_date": experiment_date,
        }
        if dataType:
            q["meta.data_type"] = dataType

        return Item().findWithPermissions(q, user=user, level=AccessType.READ)

    @staticmethod
    def _igsn_date_map(q, user=None):
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
                key = item["meta"]["igsn"] + "//" + item["meta"]["experiment_date"]
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
        .pagingParams(defaultSort="lowerName")
        .errorResponse("You are not authorized to access this resource.", 403)
    )
    def get_items_by_datatype(self, dataType, limit, offset, sort):
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
        aimdl_collection = Collection().load(
            _AIMDL_COLLECTION_ID, user=user, level=AccessType.READ, exc=True
        )
        q = {
            "meta.igsn": {"$exists": True},
            "meta.data_type": dataType,
            "baseParentId": aimdl_collection["_id"],
            "baseParentType": "collection",
        }

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

        return Item().findWithPermissions(
            q,
            user=user,
            level=AccessType.READ,
            sort=sort,
            limit=limit,
            offset=offset,
            fields=fields,
        )
