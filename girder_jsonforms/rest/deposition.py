import re

from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import (
    Resource,
    filtermodel,
)
from girder.constants import AccessType, SortDir

from ..models.deposition import Deposition as DepositionModel


class Deposition(Resource):
    def __init__(self):
        super(Deposition, self).__init__()
        self.resourceName = "deposition"
        self.route("GET", (), self.list_deposition)
        self.route("GET", (":id",), self.get_deposition)
        self.route("POST", (), self.create_deposition)
        self.route("PUT", (":id",), self.update_deposition)
        self.route("GET", (":id", "access"), self.get_access)
        self.route("PUT", (":id", "access"), self.update_access)

    @access.public
    @autoDescribeRoute(
        Description("List all depositions.")
        .param(
            "igsnPrefix",
            "Pass to lookup a form by exact IGSN prefix match.",
            required=False,
            dataType="string",
        )
        .param(
            "level",
            "The minimum access level to filter the forms by",
            dataType="integer",
            required=False,
            default=AccessType.READ,
            enum=[AccessType.NONE, AccessType.READ, AccessType.WRITE, AccessType.ADMIN],
        )
        .pagingParams(defaultSort="igsn", defaultSortDir=SortDir.ASCENDING)
    )
    @filtermodel(model="deposition", plugin="jsonforms")
    def list_deposition(self, igsnPrefix, level, limit, offset, sort):
        query = {}
        if igsnPrefix is not None:
            query["igsn"] = re.compile(f"^{igsnPrefix}.*$")

        return DepositionModel().findWithPermissions(
            query=query,
            offset=offset,
            limit=limit,
            sort=sort,
            user=self.getCurrentUser(),
            level=level,
        )

    @access.public
    @autoDescribeRoute(
        Description("Get a single deposition").modelParam(
            "id",
            model=DepositionModel,
            plugin="jsonforms",
            paramType="path",
            required=True,
            level=AccessType.READ,
        )
    )
    @filtermodel(model="deposition", plugin="jsonforms")
    def get_deposition(self, deposition):
        return deposition

    @access.user
    @autoDescribeRoute(
        Description("Create a new deposition")
        .param("prefix", "The prefix for IGSN", required=True, dataType="string")
        .jsonParam(
            "metadata",
            "JSON object with Datacite fields",
            requireObject=True,
            required=True,
        )
        .modelParam(
            "parentId",
            "The parent deposition ID.",
            model=DepositionModel,
            destName="parent",
            required=False,
            paramType="query",
            level=AccessType.WRITE,
        )
    )
    @filtermodel(model="deposition", plugin="jsonforms")
    def create_deposition(self, prefix, metadata, parent):
        # Logic to create a new deposition
        return DepositionModel().create(
            metadata, self.getCurrentUser(), prefix, parent=parent
        )

    @access.public
    def update_deposition(self, id, params):
        # Logic to update an existing deposition
        pass

    @access.public
    def get_access(self, id):
        # Logic to get access information for a deposition
        pass

    @access.public
    def update_access(self, id, params):
        # Logic to update access information for a deposition
        pass
