import logging
from ..worker_plugin.htmax import htmax_specimen_relations

logger = logging.getLogger(__name__)


def trigger_post_entry_task(task_name, entry, user):
    """
    Trigger a post entry task.
    This is a placeholder function that should be implemented to handle the task.
    """
    logger.info(
        f"Triggering post entry task: {task_name} for entry: {entry['_id']} by user: {user['login']}"
    )
    if task_name == "htmax_specimen":
        # Example task handling logic
        htmax_specimen_relations.delay(
            entry, user, girder_job_title="Updating relatedIdentifiers in Depositions"
        )
    else:
        logger.warning(f"Unknown task: {task_name} for entry: {entry['_id']}")
