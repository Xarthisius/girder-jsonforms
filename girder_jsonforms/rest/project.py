from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import (
    Resource,
    filtermodel,
)
from girder.constants import AccessType, SortDir
from girder.exceptions import AccessException, RestException

from ..models.project import Project as ProjectModel


class Project(Resource):
    def __init__(self):
        super(Project, self).__init__()
        self.resourceName = "project"
        self.route("GET", (), self.list_project)
        self.route("POST", (), self.create_project)
        self.route("DELETE", (":id",), self.delete_project)
        self.route("GET", (":id",), self.get_project)
        self.route("PUT", (":id",), self.update_project)

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
        Description("Create a new project").jsonParam(
            "project",
            "The project to create.",
            paramType="body",
            requireObject=True,
        )
    )
    @filtermodel(model="project", plugin="jsonforms")
    def create_project(self, project):
        """
        Create a new project.
        """
        user = self.getCurrentUser()
        project["creatorId"] = user["_id"]
        return ProjectModel().create_project(project, user)

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
