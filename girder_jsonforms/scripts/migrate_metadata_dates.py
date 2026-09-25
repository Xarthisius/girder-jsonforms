"""One-off migration: convert pre-existing ISO date strings in Item/Folder
``meta`` into BSON ``datetime`` objects.

The ``model.item.save`` / ``model.folder.save`` event handler installed by this
plugin only coerces metadata as documents are (re)saved. Documents written
before the handler existed still hold date strings. This script back-fills them
using the exact same strict :func:`coerce_dates` logic, so migrated data is
indistinguishable from freshly-saved data.

It talks to MongoDB through Girder's model layer, so it uses whatever database
the running Girder is configured for (env / girder config file). It updates the
raw collection directly (``$set`` on ``meta``) rather than calling ``save()``:
that skips per-document validation/events and only touches documents whose
metadata actually changes. Re-running is safe -- coercion is idempotent.

Usage::

    girder-jsonforms-migrate-metadata-dates            # migrate items + folders
    girder-jsonforms-migrate-metadata-dates --dry-run  # report only, no writes
    girder-jsonforms-migrate-metadata-dates --collection folder
"""

import argparse
import logging
import sys

from pymongo import UpdateOne

from girder_jsonforms.lib.metadata_dates import coerce_dates

logger = logging.getLogger("girder_jsonforms.migrate_metadata_dates")

# Only scan documents that actually carry a non-empty metadata object.
_QUERY = {"meta": {"$exists": True, "$type": "object", "$nin": [None, {}]}}


def _migrate_model(model, dry_run, batch_size):
    """Coerce date strings in one collection. Returns (scanned, changed)."""
    collection = model.collection
    scanned = 0
    changed = 0
    ops = []

    # Use an explicit session so the long-lived cursor is not reaped by the
    # 30-minute idle-session timeout. Metadata mutations keep the document
    # matching ``_QUERY`` and coercion is idempotent, so a document re-observed
    # mid-scan (e.g. after moving on WiredTiger) is a harmless no-op.
    with collection.database.client.start_session() as session:
        cursor = collection.find(
            _QUERY,
            projection={"meta": 1},
            no_cursor_timeout=True,
            session=session,
        )
        try:
            for doc in cursor:
                scanned += 1
                meta = doc.get("meta")
                if not isinstance(meta, dict) or not meta:
                    continue

                new_meta = coerce_dates(meta)
                if new_meta == meta:
                    continue

                changed += 1
                logger.debug("%s %s: meta updated", model.name, doc["_id"])
                if not dry_run:
                    ops.append(
                        UpdateOne({"_id": doc["_id"]}, {"$set": {"meta": new_meta}})
                    )
                    if len(ops) >= batch_size:
                        collection.bulk_write(ops, ordered=False)
                        ops = []
        finally:
            cursor.close()

        if ops and not dry_run:
            collection.bulk_write(ops, ordered=False)

    verb = "would update" if dry_run else "updated"
    logger.info("%s: scanned %d, %s %d", model.name, scanned, verb, changed)
    return scanned, changed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--collection",
        choices=("item", "folder", "all"),
        default="all",
        help="Which collection(s) to migrate (default: all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many documents would change without writing.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of updates per bulk write (default: 500).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    # Imported here so ``--help`` works without a configured Girder/DB.
    from girder.models.folder import Folder
    from girder.models.item import Item

    models = []
    if args.collection in ("item", "all"):
        models.append(Item())
    if args.collection in ("folder", "all"):
        models.append(Folder())

    if args.dry_run:
        logger.info("DRY RUN -- no changes will be written.")

    total_changed = 0
    for model in models:
        _, changed = _migrate_model(model, args.dry_run, args.batch_size)
        total_changed += changed

    logger.info(
        "Done. %d document(s) %s.",
        total_changed,
        "would be updated" if args.dry_run else "updated",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
