import cherrypy
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import (
    Resource,
    filtermodel,
    getCurrentUser,
)
from girder.constants import AccessType, SortDir, TokenScope
from girder.exceptions import AccessException, RestException, ValidationException
from girder.models.file import File
from girder.models.folder import Folder
from girder.models.item import Item

from ..models.project import Project as ProjectModel


def _submission_projects(file):
    """Projects that list ``file`` and keep it inside their submission folder.

    Both conditions are required. ``files`` alone is not enough, because anyone
    with WRITE on a project can put an arbitrary fileId there, and honouring it
    would let them hand every reader of the project a file they could never
    read themselves. The submission folder is where the proposal app uploads
    documents, and only the creator (and admins) can write to it.
    """
    item = Item().load(file["itemId"], force=True)
    if item is None:
        return []
    folder_ids = []
    folder = Folder().load(item["folderId"], force=True)
    while folder is not None:
        folder_ids.append(folder["_id"])
        if folder.get("parentCollection") != "folder":
            break
        folder = Folder().load(folder["parentId"], force=True)
    return ProjectModel().find(
        {"files.fileId": file["_id"], "submissionFolderId": {"$in": folder_ids}}
    )


@access.public(scope=TokenScope.DATA_READ, cookie=True)
def download_project_file(event):
    """Let anyone who can read a project download its submitted documents.

    Bound to ``rest.get.file/:id/download[/:name].before``. Submission folders
    are private to the proposal's creator, so core's own check (READ on the
    file's folder) refuses reviewers, the project group and members alike.
    Rather than copy those principals onto the folder -- grants that would
    have to be written inside the project save, revoked when the project's ACL
    changes, and backfilled for existing proposals -- this asks the project's
    ACL at download time, so access follows the project automatically.
    Whenever core would already allow the download, it is left to core.
    """
    try:
        file = File().load(event.info["id"], force=True)
    except ValidationException:
        return  # core reports the bad id
    if file is None or not file.get("itemId"):
        return  # missing, or attached to something other than an item
    user = getCurrentUser()
    if File().hasAccess(file, user=user, level=AccessType.READ):
        return
    if not any(
        ProjectModel().hasAccess(project, user=user, level=AccessType.READ)
        for project in _submission_projects(file)
    ):
        return  # core raises the 403

    # Mirrors girder/api/v1/file.py:File.download, minus the access check.
    params = event.info["params"]
    offset = int(params.get("offset", 0))
    end_byte = params.get("endByte")
    end_byte = int(end_byte) if end_byte is not None else None
    range_request = cherrypy.request.headers.get("Range")
    if range_request and file.get("size") is None:
        File().updateSize(file)
    ranges = cherrypy.lib.httputil.get_ranges(range_request, file.get("size", 0))
    if ranges:
        offset, end_byte = ranges[0]
    event.preventDefault().addResponse(
        File().download(
            file,
            offset,
            endByte=end_byte,
            contentDisposition=params.get("contentDisposition", "attachment"),
        )
    )


class Project(Resource):
    def __init__(self):
        super(Project, self).__init__()
        self.resourceName = "project"
        self.route("GET", (), self.list_project)
        self.route("POST", (), self.create_project)
        self.route("DELETE", (":id",), self.delete_project)
        self.route("GET", (":id",), self.get_project)
        self.route("PUT", (":id",), self.update_project)
        self.route("PUT", (":id", "samples"), self.update_project_samples)

    @access.public
    @autoDescribeRoute(
        Description("List all projects.")
        .param(
            "level",
            "The minimum access level to filter the forms by",
            dataType="integer",
            required=False,
            default=AccessType.READ,
            enum=[AccessType.NONE, AccessType.READ, AccessType.WRITE, AccessType.ADMIN],
        )
        .pagingParams(defaultSort="name", defaultSortDir=SortDir.ASCENDING)
    )
    @filtermodel(model="project", plugin="jsonforms")
    def list_project(self, level, limit, offset, sort):
        """
        List all projects.
        """
        user = self.getCurrentUser()
        return ProjectModel().findWithPermissions(
            query={}, offset=offset, limit=limit, sort=sort, user=user, level=level
        )

    @access.public
    @autoDescribeRoute(
        Description("Get a single project").modelParam(
            "id",
            model=ProjectModel,
            plugin="jsonforms",
            paramType="path",
            required=True,
            level=AccessType.READ,
        )
    )
    @filtermodel(model="project", plugin="jsonforms")
    def get_project(self, project):
        return project

    @access.user
    @autoDescribeRoute(
        Description("Create a new project")
        .jsonParam(
            "project",
            "The project to create.",
            paramType="body",
            requireObject=True,
        )
        .param(
            "prefix",
            "Project ID prefix",
            required=False,
            dataType="string",
        )
    )
    @filtermodel(model="project", plugin="jsonforms")
    def create_project(self, project, prefix):
        """
        Create a new project.
        """
        user = self.getCurrentUser()
        project["creatorId"] = user["_id"]
        return ProjectModel().create_project(project, user, prefix=prefix)

    @access.user
    @autoDescribeRoute(
        Description("Update an existing project")
        .modelParam(
            "id",
            model=ProjectModel,
            plugin="jsonforms",
            paramType="path",
            required=True,
            level=AccessType.WRITE,
        )
        .jsonParam(
            "updates",
            "The project updates.",
            paramType="body",
            requireObject=True,
        )
    )
    @filtermodel(model="project", plugin="jsonforms")
    def update_project(self, project, updates):
        """
        Update an existing project.
        """
        user = self.getCurrentUser()
        if project["status"] != "draft":
            try:
                ProjectModel().requireAccessFlags(
                    project, user=user, flags="jsonforms.review_projects"
                )
            except AccessException:
                raise RestException(
                    "Only projects in draft status can be updated.", 403
                )
        updates.pop("_id", None)
        return ProjectModel().update_project(project, updates, user)

    @access.user
    @autoDescribeRoute(
        Description("Replace the list of samples on a project")
        .modelParam(
            "id",
            model=ProjectModel,
            plugin="jsonforms",
            paramType="path",
            required=True,
            level=AccessType.WRITE,
        )
        .jsonParam(
            "samples",
            "The full list of sample IGSNs the project should have.",
            paramType="body",
            requireArray=True,
        )
    )
    @filtermodel(model="project", plugin="jsonforms")
    def update_project_samples(self, project, samples):
        """
        Add/remove samples on a project. Allowed regardless of the
        project's status, unlike the general project update endpoint.
        """
        user = self.getCurrentUser()
        try:
            return ProjectModel().update_samples(project, samples, user)
        except AccessException:
            raise RestException(
                "Only users with the Sample Manager access flag can add or "
                "remove samples on this project.",
                403,
            )

    @access.user
    @autoDescribeRoute(
        Description("Delete a project").modelParam(
            "id",
            model=ProjectModel,
            plugin="jsonforms",
            paramType="path",
            required=True,
            level=AccessType.ADMIN,
        )
    )
    def delete_project(self, project):
        """
        Delete a project.
        """
        return ProjectModel().remove(project)
