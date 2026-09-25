import logging
from girder.models.collection import Collection
from girder.models.item import Item
from girder.models.user import User

from girder_worker.app import app


logger = logging.getLogger(__name__)


@app.task(queue="local")
def remove_sample_data(
    projectId: str,
    samples: list[str],
):
    from ..models.project import Project

    project = Project().load(projectId, force=True)
    project_collection = Collection().findOne({"name": project["projectId"]})
    q = {
        "baseParentId": project_collection["_id"],
        "baseParentType": "collection",
        "projectId": project["_id"],
    }
    q.update(Project.igsn_query(samples))
    count = 0
    for item in Item().find(q):
        Item().remove(item)
        count += 1
    logger.info(f"Removed {count} files")


@app.task(queue="local")
def add_sample_data(
    projectId: str,
    samples: list[str],
):
    from ..models.project import Project
    from ..rest.aimdl import propagate_item_to_project, AIMDL

    project = Project().load(projectId, force=True)
    project_collection = Collection().findOne({"name": project["projectId"]})
    creator = User().findOne({"admin": True})
    query = AIMDL._get_base_parent()
    query.update(Project.igsn_query(samples))
    count = 0
    for item in Item().find(query):
        propagate_item_to_project(
            item, project, collection=project_collection, creator=creator
        )
        count += 1
    logger.info(f"Added {count} files")
