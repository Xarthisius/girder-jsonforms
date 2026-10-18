"""Pull IGSN registry state onto local depositions.

Publication is asynchronous the whole way down: Girder queues it with the
registry, the registry queues it with DataCite, and nothing pushes the outcome
back. ``publish_deposition`` polls for a while after queuing one, which covers
the ordinary case, but not a record published straight against the registry's
API, not one that settled while Girder was down, and not one that took longer
than that poll chain was willing to wait. This is the backstop for those, and
is meant to run on a timer::

    */15 * * * *  girder-jsonforms-reconcile-igsn --quiet

It runs the ``reconcile`` task in-process -- no broker, no worker -- against
whatever database the local Girder configuration points at, so it is also the
quickest way to repair one record by hand.

By default it only looks at depositions that have not settled locally, which is
what a timer is for and what keeps ``--limit`` meaningful: the scan has no
ordering, so a flat limit over every deposition would re-check the same first
thousand for ever. ``--all`` does the full pass, which is the one that also
reports depositions the registry has never heard of.

Usage::

    girder-jsonforms-reconcile-igsn                       # unsettled records
    girder-jsonforms-reconcile-igsn --all                 # full audit, to --limit
    girder-jsonforms-reconcile-igsn --prefix JHAMAL
    girder-jsonforms-reconcile-igsn --igsn JHAMAL00001 --igsn JHAMAL00002
    girder-jsonforms-reconcile-igsn --quiet               # summary only on trouble

Exits non-zero when a record could not be read from the registry, so a cron
run that hit a broken service says so. A deposition the registry has never
heard of is logged and counted, but is not a failure: it is a finding for a
human, and reconcile deliberately does not invent the missing record.
"""

import argparse
import logging
import sys

logger = logging.getLogger("girder_jsonforms.reconcile_igsn")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--prefix",
        help="Only reconcile depositions whose IGSN starts with this prefix.",
    )
    parser.add_argument(
        "--igsn",
        action="append",
        dest="igsns",
        metavar="IGSN",
        help="Reconcile one IGSN. Repeatable; overrides --prefix.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="check_all",
        help=(
            "Also re-check records that have already settled locally, and "
            "report any the registry does not have."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Maximum number of depositions to check (default: 1000).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Log warnings and errors only -- a quiet cron run stays quiet.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    args = parser.parse_args(argv)

    level = logging.INFO
    if args.quiet:
        level = logging.WARNING
    if args.verbose:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s %(message)s")

    # Imported here so ``--help`` works without a configured Girder/DB.
    from girder_jsonforms.worker_plugin.igsn_registry import reconcile

    summary = reconcile(
        prefix=args.prefix,
        igsns=args.igsns,
        limit=args.limit,
        pending_only=not args.check_all,
    )
    if summary is None:
        # Local mode. Not an error: an instance that allocates its own IGSNs has
        # no registry to reconcile against, and a cron entry left behind after
        # switching modes should not start failing.
        logger.warning("No IGSN registry is configured; nothing to reconcile.")
        return 0

    logger.info(
        "Reconciled: %(updated)s updated, %(unchanged)s unchanged, "
        "%(missing)s missing, %(errors)s error(s).",
        summary,
    )
    if summary["missing"]:
        logger.warning(
            "%s deposition(s) are not in the registry; see the lines above.",
            summary["missing"],
        )
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
