"""Background tasks that talk to the central IGSN registry.

Metadata sync runs out of band because several code paths mutate a deposition's
metadata with raw ``collection.update_*`` -- ``Deposition.updateRelations``,
``rest.deposition.update_deposition_relations``, ``relate_entry_to_igsn`` -- and
so never reach ``Model.save()``. Each of those has to push explicitly, and doing
it inline would put an HTTP round-trip in the middle of a form submission.

All three tasks are no-ops when ``jsonforms.igsn_service_url`` is unset, so
enqueueing them is harmless on an instance still in local mode.
"""

import logging

from bson import ObjectId
from girder_worker.app import app

from ..lib.igsn_client import IGSNServiceError, get_client
from ..models.deposition import Deposition

logger = logging.getLogger(__name__)


@app.task(queue="local")
def sync_deposition_metadata(depositionId):
    """Push one deposition's current metadata to the registry."""
    deposition = Deposition().load(depositionId, force=True)
    if deposition is None:
        logger.warning("Deposition %s no longer exists; nothing to sync", depositionId)
        return None
    return Deposition().sync_to_registry(deposition)


@app.task(queue="local")
def sync_depositions_metadata(depositionIds):
    """Push several depositions' metadata. Used after bulk relation updates."""
    for depositionId in depositionIds:
        try:
            sync_deposition_metadata(str(depositionId))
        except Exception:  # noqa: BLE001 - one bad record must not stop the rest
            logger.exception("Failed to sync deposition %s", depositionId)


@app.task(queue="local")
def publish_deposition(depositionId, target="findable", recurse=False, metadata_only=False):
    """Sync metadata and (unless ``metadata_only``) queue DataCite publication.

    Metadata always goes first: publishing whatever the registry happened to
    hold, rather than what Girder currently shows, is how you publish a stale
    record.
    """
    client = get_client()
    if client is None:
        logger.info("No IGSN registry configured; skipping publish")
        return None

    deposition = Deposition().load(depositionId, force=True)
    if deposition is None:
        raise ValueError(f"Deposition {depositionId} does not exist")

    # Checked again here, not only at the REST layer: this task is reachable
    # directly from celery and from other code, and "public before published"
    # is an invariant rather than an input-validation nicety.
    if not metadata_only:
        Deposition().require_publishable(deposition, recurse=recurse)

    Deposition().sync_to_registry(deposition)
    if metadata_only:
        return {"igsn": deposition["igsn"], "synced": True}

    result = client.publish(deposition["igsn"], target=target, recurse=recurse)
    logger.info(
        "Queued %s for publication as %s (%s attempt(s))",
        deposition["igsn"],
        target,
        result.get("queued"),
    )
    # Publication is asynchronous on the service side too, so the local mirror
    # is refreshed by `reconcile` once DataCite has actually accepted it.
    return result


@app.task(queue="local")
def reconcile(prefix=None, igsns=None, limit=1000):
    """Pull registry state onto local depositions and report divergence.

    Two kinds of drift are possible and only one is fixable here:

    * status drift -- the registry published a record and Girder still shows it
      as a draft. Fixed by mirroring the registry's status.
    * missing records -- a deposition exists locally with no registry record at
      all. Reported, not invented: creating one would mean guessing which tenant
      and prefix it belongs to, and a duplicate IGSN is worse than a warning.
    """
    client = get_client()
    if client is None:
        logger.info("No IGSN registry configured; nothing to reconcile")
        return None

    query = {}
    if igsns:
        query["igsn"] = {"$in": list(igsns)}
    elif prefix:
        query["igsn"] = {"$regex": f"^{prefix}"}

    updated = missing = unchanged = errors = 0
    cursor = Deposition().collection.find(
        query, {"_id": 1, "igsn": 1, "state": 1, "serviceStatus": 1}
    ).limit(limit)

    for deposition in cursor:
        try:
            record = client.get_record(deposition["igsn"])
        except IGSNServiceError:
            logger.exception("Could not read %s from the registry", deposition["igsn"])
            errors += 1
            continue

        if record is None:
            logger.warning(
                "%s exists in Girder but not in the IGSN registry", deposition["igsn"]
            )
            missing += 1
            continue

        if record.get("status") == deposition.get("serviceStatus"):
            unchanged += 1
            continue

        Deposition().apply_registry_state(deposition["_id"], record)
        updated += 1

    summary = {
        "updated": updated,
        "unchanged": unchanged,
        "missing": missing,
        "errors": errors,
    }
    logger.info("Reconcile finished: %s", summary)
    return summary


def sync_after_relation_change(deposition_ids):
    """Queue a metadata sync for depositions whose relations changed in place.

    Call this from anywhere that writes ``metadata`` with a raw
    ``collection.update_*``; those writes bypass ``save()`` and would otherwise
    never reach the registry.
    """
    if get_client() is None:
        return
    ids = [str(_id) for _id in deposition_ids if _id]
    if not ids:
        return
    sync_depositions_metadata.delay(
        ids, girder_job_title=f"Syncing {len(ids)} IGSN record(s) with the registry"
    )


def deposition_ids_for_igsns(igsns):
    """Resolve IGSN strings to local deposition ids."""
    cursor = Deposition().collection.find({"igsn": {"$in": list(igsns)}}, {"_id": 1})
    return [doc["_id"] for doc in cursor]


def object_ids(values):
    """Coerce a mixed list of ids/strings to ObjectIds, dropping junk."""
    out = []
    for value in values:
        try:
            out.append(value if isinstance(value, ObjectId) else ObjectId(value))
        except Exception:  # noqa: BLE001
            continue
    return out
