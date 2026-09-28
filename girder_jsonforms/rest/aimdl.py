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
from girder.api.rest import (
    Resource,
    boundHandler,
    filtermodel,
    setResponseHeader,
)
from girder.constants import AccessType, TokenScope
from girder.exceptions import RestException
from girder.models.collection import Collection
from girder.models.file import File
from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.user import User
from girder.models.setting import Setting

from ..lib.announcement import Announcement
from ..lib.metadata_dates import _parse_iso, coerce_dates
from ..lib.response_cache import cached_call
from ..models.project import Project
from ..settings import PluginSettings

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


def _cache_ttl():
    """Seconds to cache the listing endpoints for; 0 disables it.

    Read per request rather than captured at import so an operator can turn
    caching off without a restart -- which is the first thing anyone will
    want to do if a listing ever looks stale.
    """
    return Setting().get(PluginSettings.AIMDL_CACHE_TTL)


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


class BaseLabResource(Resource):
    def __init__(self):
        super().__init__()
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
        # Outside the cache on purpose: this resolves the parent *and* checks
        # the caller may read it, and the pipeline below applies no ACL of its
        # own, so this is the only access check there is. A cache hit must not
        # be a way around it.
        query = self._get_base_parent(
            baseParentType, baseParentId, user=self.getCurrentUser()
        )
        if igsn:
            query["meta.igsn"] = igsn

        def compute():
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

        # No user in the key. The pipeline groups every item under the base
        # parent regardless of who asked, so everyone who got past the check
        # above gets the same answer; keying per user would buy a miss per user
        # for an identical result, which is most of the point of caching this.
        return cached_call(["aimdl.count", query], _cache_ttl(), compute)

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

        # Deliberately neither of the ACL strategies below. This query names one
        # IGSN and so matches a handful of items -- four, measured -- where the
        # $lookup costs nothing and enumerating the collection's folders costs
        # about twice the whole request. It also has to hand filtermodel a cursor
        # for the total count.
        return Item().findWithPermissions(q, user=user, level=AccessType.READ)

    #: How many undecided items to hold before resolving their folders in one
    #: query -- see :meth:`_find_readable_items`. Caps peak memory; the folder
    #: set saturates long before a large result set is exhausted, so raising it
    #: buys nothing and lowering it only costs a few more folder queries.
    FOLDER_RESOLVE_BATCH = 1000

    @staticmethod
    def _is_admin(user):
        """``user`` may be ``None`` (anonymous) or lack the flag entirely."""
        return bool(user and user.get("admin"))

    @staticmethod
    def _is_base_scoped(q):
        """Whether ``q`` names a base parent, so folders can be scoped by it."""
        return "baseParentId" in q and "baseParentType" in q

    @staticmethod
    def _readable_folder_ids(scope, user):
        """Ids of the folders matching ``scope`` that ``user`` can read.

        The one place this module asks girder about folder access. ``Folder`` is
        a real ``AccessControlledModel``, so this is a plain indexed find --
        unlike ``Item``, which carries no ACL of its own and can only be filtered
        by joining its folder. Both strategies below are built on it; they differ
        only in which folders they ask about.
        """
        return [
            folder["_id"]
            for folder in Folder().findWithPermissions(
                scope, user=user, level=AccessType.READ, fields={"_id": 1}
            )
        ]

    # Two ways to apply an item ACL, because there are two access patterns and
    # no single one wins both. Measured against a copy of production, listing
    # every item of a data type under the AIMDL collection:
    #
    #     items    findWithPermissions   _find_readable_items   _acl_scoped_query
    #        34                    1ms                    0ms                30ms
    #     9,355                  198ms                   39ms               106ms
    #    24,819                  562ms                  152ms               181ms
    #    40,094                  990ms                  262ms               339ms
    #    72,644                1,639ms                  515ms               486ms
    #
    # Batching wins nearly everywhere for *iteration* because it only resolves
    # the folders the result actually references -- 18 for xrd_calibrant_raw,
    # 1,704 for xrd_raw, against the 17,203 that exist. But it filters in Python,
    # so it cannot express the ACL as a query, which is what server-side sorting,
    # paging and count() need. Hence both.

    @classmethod
    def _acl_scoped_query(cls, q, user):
        """``q`` narrowed to the folders ``user`` can read, or ``None``.

        For callers that need a *query* rather than an iterable.
        ``Item().findWithPermissions`` builds one by ``$lookup``-ing the owning
        folder of every matching item and ``$match``-ing the joined document
        (see ``girder/utility/acl_mixin.py``) -- forty thousand joins to return a
        page of thirty. That join is 92-94% of the query's cost, and no index
        reaches it: only the pipeline's first ``$match`` is index-servable and it
        already accounts for ~46ms of a ~700ms query, while the ``$sort`` lands
        after the join where no index can serve it either. A compound index on
        the ``$match`` moved the total 2-4%.

        Naming the readable folders up front instead turns the whole thing into
        an ordinary indexed query -- ~10x faster for a sorted, counted page, and
        still a real cursor. The flat cost is enumerating every folder under the
        base parent (~30ms for seventeen thousand) whether one item matches or a
        hundred thousand do, which is why :meth:`_find_readable_items` exists for
        the cases that only need to iterate.

        The readable set is resolved per request rather than cached: it is cheap
        next to what it replaces, and an ACL answer that outlives the permission
        it describes is a worse thing to own than 30ms.

        Returns ``None`` when ``q`` names no base parent, so there is nothing to
        enumerate folders by and the caller should use ``findWithPermissions``.
        """
        if cls._is_admin(user):
            # Nothing to filter by: findWithPermissions short-circuits admins
            # the same way.
            return dict(q)
        if not cls._is_base_scoped(q):
            return None

        scoped = dict(q)
        # An item in an unreadable folder drops out, and so does one with no
        # folderId at all -- exactly what the $lookup did, which joined nothing
        # for either and so failed the permission $match. An empty list is
        # therefore the correct query for a user who can read nothing here.
        scoped["folderId"] = {
            "$in": cls._readable_folder_ids(
                {
                    "baseParentId": q["baseParentId"],
                    "baseParentType": q["baseParentType"],
                },
                user,
            )
        }
        return scoped

    @classmethod
    def _find_readable_items(cls, q, user=None, fields=None):
        """Yield the items matching ``q`` that ``user`` can read.

        For callers walking a whole result set. Runs the item query first and
        decides the folders it actually references, in batches and cached, so a
        query matching thirty-four items asks about eighteen folders rather than
        the seventeen thousand :meth:`_acl_scoped_query` would enumerate. That is
        worth 2-4x over either alternative up to about fifty thousand items --
        see the table above.

        The trade-off is that the ACL stops being a predicate Mongo can apply, so
        items the user cannot read are fetched and dropped here. The ``$lookup``
        this replaces did that too. What it costs is the ability to sort, page or
        count server-side; callers needing those want
        :meth:`_acl_scoped_query` instead.

        Yields documents rather than a cursor. Yielded documents always carry
        ``folderId``, which drives the decision, even if ``fields`` did not ask
        for it.
        """
        if cls._is_admin(user):
            yield from Item().find(q, fields=fields)
            return

        if not cls._is_base_scoped(q):
            # Not the shape this is for; nothing here is wrong for it, but the
            # folder set it would resolve is unbounded.
            yield from Item().findWithPermissions(
                q, user=user, level=AccessType.READ, fields=fields
            )
            return

        # folderId drives the access decision, so project it whether or not the
        # caller asked for it.
        if fields is not None and not fields.get("folderId"):
            fields = dict(fields, folderId=1)

        decided = {}
        pending = []

        def flush():
            unknown = {item.get("folderId") for item in pending} - set(decided)
            unknown.discard(None)
            if unknown:
                readable = set(
                    cls._readable_folder_ids({"_id": {"$in": list(unknown)}}, user)
                )
                decided.update({fid: fid in readable for fid in unknown})
            for item in pending:
                # An item with no folderId has no folder to inherit an ACL from;
                # the $lookup this replaces matched nothing for it either.
                if decided.get(item.get("folderId")):
                    yield item
            pending.clear()

        for item in Item().find(q, fields=fields):
            folder_id = item.get("folderId")
            if folder_id in decided:
                if decided[folder_id]:
                    yield item
                continue
            pending.append(item)
            if len(pending) >= cls.FOLDER_RESOLVE_BATCH:
                yield from flush()
        yield from flush()

    @classmethod
    def _igsn_date_map(cls, q, user=None, ignore_time=False):
        fields = {
            "meta.igsn": 1,
            "meta.checksum": 1,
            "meta.experiment_date": 1,
            "folderId": 1,
            "name": 1,
            "_id": 1,
        }

        igsn_map = {}
        for item in cls._find_readable_items(q, user=user, fields=fields):
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

        sort = deterministic_sort(sort)

        def compute():
            # Both halves have to be resolved in here. filtermodel fills in
            # Girder-Total-Count only when handed a cursor, and what a cached
            # call can return is a list -- so take the count alongside the page
            # and set the header below.
            try:
                scoped = self._acl_scoped_query(q, user)
                if scoped is not None:
                    return {
                        "items": list(
                            Item().find(
                                scoped,
                                fields=fields,
                                sort=sort,
                                limit=limit,
                                offset=offset,
                            )
                        ),
                        "total": Item().collection.count_documents(scoped),
                    }
                cursor = Item().findWithPermissions(
                    q,
                    user=user,
                    level=AccessType.READ,
                    sort=sort,
                    limit=limit,
                    offset=offset,
                    fields=fields,
                )
                # Guarded the way core guards it: the non-aggregation fallback
                # path of findWithPermissions returns a plain pymongo cursor,
                # which has had no count() since pymongo 4.
                counter = getattr(cursor, "count", None)
                total = counter() if callable(counter) else None
                return {"items": list(cursor), "total": total}
            except pymongo.errors.OperationFailure as e:
                raise RestException("Invalid 'extraFields' parameter: {}".format(e))

        # Keyed per user, unlike the counts: these results *are* ACL-filtered,
        # so two users asking the same question can get different pages. The
        # consequence is that a permission change takes up to one TTL to show.
        payload = cached_call(
            [
                "aimdl.datafiles",
                user["_id"],
                q,
                sorted(fields),
                limit,
                offset,
                sort,
            ],
            _cache_ttl(),
            compute,
        )
        if payload["total"] is not None:
            setResponseHeader("Girder-Total-Count", payload["total"])
        return payload["items"]


class AIMDL(BaseLabResource):
    def __init__(self):
        self.resourceName = "aimdl"
        super().__init__()


class IMQCAM(BaseLabResource):
    def __init__(self):
        self.resourceName = "imqcam"
        super().__init__()

    @staticmethod
    def _get_base_parent(parentType=None, parentId=None, user=None):
        if not parentType or not parentId:
            return {}
        if parentType == "collection":
            parent = Collection().load(
                parentId, user=user, level=AccessType.READ, exc=True
            )
        elif parentType == "user":
            parent = User().load(parentId, user=user, level=AccessType.READ, exc=True)
        else:
            raise RestException("Invalid parent type: {}".format(parentType), code=400)
        return {"baseParentId": parent["_id"], "baseParentType": parentType}


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
    if not Setting().get(PluginSettings.PROJECTS_ENABLED):
        logger.debug("Projects are not enabled, skipping propagation")
        return
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
