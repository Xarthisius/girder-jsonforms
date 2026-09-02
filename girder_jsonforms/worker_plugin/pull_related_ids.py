import re
from girder_worker.app import app
from ..models.deposition import Deposition


@app.task(bind=True, queue="local")
def run(task, entry, **kwargs):
    regex = re.compile(f"/entry/{entry['_id']}$")
    query = {"metadata.relatedIdentifiers.relatedIdentifier": regex}
    update = {"$pull": {"metadata.relatedIdentifiers": {"relatedIdentifier": regex}}}
    Deposition().collection.update_many(query, update)
