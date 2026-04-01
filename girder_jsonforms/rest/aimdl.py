from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, filtermodel
from girder.constants import AccessType
from girder.exceptions import RestException
from girder.models.collection import Collection
from girder.models.item import Item


class AIMDL(Resource):
    def __init__(self):
        super().__init__()
        self.resourceName = "aimdl"
        self.route("GET", ("datatype",), self.get_datatypes)
        self.route("GET", ("datafiles",), self.get_items_by_datatype)

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
        aimdl_collection_id = "665de536bcc722774ce53754"  # TODO: make this configurable
        aimdl_collection = Collection().load(
            aimdl_collection_id, user=user, level=AccessType.READ, exc=True
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
