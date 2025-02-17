from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import (
    Resource,
    filtermodel,
)
from girder.constants import AccessType, SortDir


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
        # Logic to list all depositions
        pass

    @access.public
    def get_deposition(self, id):
        # Logic to get a single deposition by ID
        pass

    @access.user
    @autoDescribeRoute(
        Description("Create a new deposition")
        .param("name", "The name of the form", required=True, dataType="string")
        .jsonParam(
            "metadata",
            "JSON object with Datacite fields",
            requireObject=True,
            required=True,
        )
    )
    @filtermodel(model="deposition", plugin="jsonforms")
    def create_deposition(self, params):
        # Logic to create a new deposition
        pass

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
