"""Send the "proposal is waiting for review" email for one existing proposal.

Unlike ``preview_mail.py``, which renders the templates with sample data and
no Girder at all, this talks to the live instance: it loads the proposal out
of MongoDB, renders the same templates with the same parameters, and hands the
message to the same ``_sendmail`` event a status transition would, so the
result is byte-for-byte what ``lib/mail.py:send_submitted_notification``
sends. Only the recipient differs -- it is the address given on the command
line rather than the proposal's resolved reviewer set.

The point is to be runnable from a shell inside a production container, where
the plugin is installed but no Girder server is being served::

    docker exec -it <girder-container> \\
        girder-jsonforms-send-review-notice JHU250001 reviewer@example.edu

    # or, without the console script on PATH:
    python -m girder_jsonforms.scripts.send_review_notice JHU250001 you@example.edu

Nothing is written back: the proposal's status is left alone, so this can be
used to nudge a reviewer about a proposal that is already under review, or to
smoke-test SMTP from the container. Pass ``--dry-run`` to print the assembled
message instead of connecting to the SMTP server.

The database, SMTP server, From address and brand name all come from the
container's own Girder configuration (``GIRDER_MONGO_URI`` and the ``core.*``
settings), so no arguments beyond the proposal and the address are needed.
"""

import argparse
import logging
import os
import sys

logger = logging.getLogger("girder_jsonforms.send_review_notice")


def find_project(identifier):
    """Load a proposal by its ``projectId`` (e.g. ``JHU250001``) or Mongo id.

    ``projectId`` is tried first and matched case-insensitively, since that is
    the identifier that appears in the UI and in the subject line of the mail
    being re-sent; a 24-character hex string is also accepted so an operator
    can paste the ``_id`` out of a URL.
    """
    import re

    from bson.objectid import ObjectId
    from girder_jsonforms.models.project import Project

    model = Project()
    project = model.findOne(
        {"projectId": {"$regex": f"^{re.escape(identifier)}$", "$options": "i"}}
    )
    if project is not None:
        return project
    if ObjectId.is_valid(identifier):
        return model.load(ObjectId(identifier), force=True)
    return None


def send_notice(project, recipients):
    """Send ``project``'s "submitted for review" mail to ``recipients``.

    ``lib.mail.send_submitted_notification`` resolves the reviewer set itself
    and takes no override, so the resolver it calls is swapped out for the
    duration of the call. Reimplementing the send instead would defeat the
    point -- subject, templates, parameters and logo have to be identical to
    an automatic send -- and adding an override parameter would not help: this
    script is dropped into an *already deployed* container and has to work
    against whatever version of the plugin is installed there, not against one
    shipping alongside it. Nothing is written back; the proposal's ACL and
    status are untouched.
    """
    from girder_jsonforms.lib import mail

    resolver = mail.reviewer_emails
    mail.reviewer_emails = lambda _project: list(recipients)
    try:
        mail.send_submitted_notification(project)
    finally:
        mail.reviewer_emails = resolver


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "project",
        metavar="PROJECT",
        help="Proposal to notify about: its projectId (e.g. JHU250001) or _id.",
    )
    parser.add_argument(
        "email",
        metavar="EMAIL",
        nargs="+",
        help="Address to send to; repeatable, one message per address.",
    )
    parser.add_argument(
        "--domain",
        default=None,
        help=(
            "Override $DOMAIN, which is what the proposal link in the mail is "
            "built from (https://girder.<domain>/#project/<id>, Girder's own "
            "project page) unless core.email_host is set explicitly, which "
            "then wins. Defaults to the container's own $DOMAIN. A container "
            "running a plugin older than this script links to "
            "https://projects.<domain>/proposal/<id> instead."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the assembled message instead of sending it. Uses core's "
            "GIRDER_EMAIL_TO_CONSOLE path, so everything short of the SMTP "
            "connection runs exactly as it would for a real send."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if args.domain:
        os.environ["DOMAIN"] = args.domain
    if args.dry_run:
        # Read by girder.utility.mail_utils._submitEmail, which prints the
        # message instead of opening an SMTP connection.
        os.environ["GIRDER_EMAIL_TO_CONSOLE"] = "1"

    # Imported here so --help works without a configured Girder or database.
    from pathlib import Path

    from girder.utility import mail_utils

    import girder_jsonforms

    # The Mako lookup normally gets this directory from JSONFormsPlugin.load,
    # which has not run: no server is being started here. Appended rather than
    # prepended for the same reason the plugin appends it -- the lookup is
    # process-global and a prepended directory shadows core's templates.
    mail_utils.addTemplateDirectory(
        str(Path(girder_jsonforms.__file__).parent / "mail_templates")
    )

    project = find_project(args.project)
    if project is None:
        parser.error(f"No proposal matching {args.project!r}")

    logger.info(
        "Proposal %s (%s), status %r -> %s",
        project.get("projectId"),
        project["_id"],
        project.get("status"),
        ", ".join(args.email),
    )
    send_notice(project, args.email)
    logger.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
