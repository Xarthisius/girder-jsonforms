"""Email notifications for the projects (proposal) workflow.

Templates live in ``girder_jsonforms/mail_templates`` and are registered with
Girder's Mako lookup by ``JSONFormsPlugin.load``. Rendering goes through
``mail_utils.renderTemplate``, which injects ``host`` and ``brandName``, so
templates can always rely on those two.

The header logo travels as a CID attachment rather than an ``<img
src="https://...">`` so that displaying the message never makes the recipient's
mail client fetch anything from us. That rules out remote-image blocking (most
clients default to it, leaving a broken image until the reader opts in) and the
read-tracking that a remote fetch would otherwise hand us. ``data:`` URIs would
avoid the fetch too, but Gmail and Outlook strip them, so the image would break
unconditionally instead.

Messages are built with ``email.message.EmailMessage`` under the ``SMTP``
policy, following ``girder-sivacor``'s ``notifications.py``, rather than core's
``sendMail`` (which produces a lone ``MIMEText`` HTML part). Two reasons, both
about deliverability: every message carries a ``text/plain`` alternative
alongside the HTML, since an HTML-only body is a well-known spam signal and
scores badly with filters; and the headers a filter expects on legitimate mail
(``Date``, ``Message-ID``, ``Auto-Submitted``) get set, none of which core's
``_createMessage`` writes.

Unlike sivacor this does *not* ``unbind("_sendmail", "core.email")``. That
would route every Girder email -- core account mail, other plugins' -- through
a replacement submitter site-wide. It is unnecessary here: under the SMTP
policy ``as_string()`` (what core's submitter calls) is 7-bit clean, headers
RFC 2047-encoded and bodies transfer-encoded, so core's handler delivers these
messages correctly as they are.
"""

import email.utils
import logging
import os
import pathlib
from email.message import EmailMessage
from email.policy import SMTP

from girder import events
from girder.models.group import Group
from girder.models.setting import Setting
from girder.models.user import User
from girder.settings import SettingKey
from girder.utility import mail_utils

from ..settings import MAIL_ASSET_DIR, MAIL_LOGO_TYPES, PluginSettings

logger = logging.getLogger(__name__)

REVIEW_FLAG = "jsonforms.review_projects"

#: Content-ID of the header logo part. Fixed rather than generated per message:
#: it only has to be unique within the one message it appears in.
LOGO_CID = "jsonforms-mail-logo"


def projects_url(project=None):
    """Public URL of the proposals UI, or of a single proposal within it.

    Derived from ``$DOMAIN`` the same way ``worker_plugin/orcid.py`` derives
    the resource URL it registers with ORCID, so an emailed link and an ORCID
    record point at the same page. Falls back to Girder's ``core.email_host``
    when ``DOMAIN`` is unset.
    """
    domain = os.environ.get("DOMAIN", "")
    if domain:
        base = f"https://projects.{domain}"
    else:
        base = (Setting().get(SettingKey.EMAIL_HOST) or "").rstrip("/")
    if project is None:
        return base
    return f"{base}/proposal/{project['_id']}"


def _emails(users):
    return sorted({user["email"] for user in users if user.get("email")})


def reviewer_emails(project):
    """Addresses of everyone who can act on a submitted proposal: site admins
    plus any user or group holding the ``jsonforms.review_projects`` flag on
    the proposal.

    Girder access flags are per-document (``hasAccessFlags``), so a proposal
    that nobody has been explicitly granted the flag on resolves to the site
    admins alone.
    """
    recipients = list(User().getAdmins())
    access = project.get("access", {})
    for entry in access.get("users", []):
        if REVIEW_FLAG in (entry.get("flags") or []):
            if user := User().load(entry["id"], force=True):
                recipients.append(user)
    for entry in access.get("groups", []):
        if REVIEW_FLAG in (entry.get("flags") or []):
            if group := Group().load(entry["id"], force=True):
                recipients.extend(Group().listMembers(group))
    return _emails(recipients)


def submitter_emails(project):
    """Addresses to tell about a decision: whoever created the proposal, plus
    every member listed on it with the PI role."""
    recipients = set()
    if project.get("creatorId"):
        if creator := User().load(project["creatorId"], force=True):
            if creator.get("email"):
                recipients.add(creator["email"])
    for member in project.get("members", []):
        if member.get("role", "").lower() == "pi" and member.get("email"):
            recipients.add(member["email"])
    return sorted(recipients)


def _submitter_name(project):
    if project.get("creatorId"):
        if creator := User().load(project["creatorId"], force=True):
            return f"{creator['firstName']} {creator['lastName']}".strip()
    for member in project.get("members", []):
        if member.get("role", "").lower() == "pi":
            name = f"{member.get('firstName', '')} {member.get('lastName', '')}"
            return name.strip() or member["email"]
    return ""


def resolve_logo(value):
    """Turn a ``jsonforms.mail_logo`` value into a path.

    A bare filename names an image bundled in ``mail_assets``; anything with a
    separator is a filesystem path, so a deployment can mount its own without
    rebuilding the package.
    """
    if "/" not in value:
        return MAIL_ASSET_DIR / value
    return pathlib.Path(value).expanduser()


def logo_attachment():
    """The header logo as ``(bytes, subtype, filename)``, or None for no logo.

    Reads the file named by ``jsonforms.mail_logo``. A missing or unreadable
    file is logged and degrades to the text-only header rather than failing
    the send -- the setting is routinely configured before the file is mounted.
    """
    value = (Setting().get(PluginSettings.MAIL_LOGO) or "").strip()
    if not value:
        return None
    path = resolve_logo(value)
    subtype = MAIL_LOGO_TYPES.get(path.suffix.lower())
    if subtype is None:
        logger.warning("Unsupported email logo type: %s", path)
        return None
    try:
        data = path.read_bytes()
    except OSError:
        logger.warning("Email logo %s is not readable; sending without it", path)
        return None
    return data, subtype, path.name


def build_message(subject, text, html, sender, to=None, logo=None):
    """Assemble one message: plain text, HTML alternative, optional CID logo.

    The result is::

        multipart/alternative
        |- text/plain
        `- multipart/related        (only when there is a logo)
           |- text/html
           `- image/*               inline, Content-ID: <LOGO_CID>

    Text first, per RFC 2046: the last alternative is the richest, so clients
    that can render HTML pick it and the rest fall back to the text part.

    There is deliberately no ``bcc`` parameter. A Bcc header is serialized
    into the message like any other (core's ``sendMail`` transmits one, which
    discloses the whole list to every recipient), and a message with a Bcc and
    no To reads as bulk mail. Callers with several unrelated recipients send
    each their own copy instead -- see ``send_submitted_notification``.
    """
    to = to or []
    message = EmailMessage(policy=SMTP)
    message["Subject"] = subject
    message["From"] = sender
    if to:
        message["To"] = ", ".join(to)
    # Date and Message-ID are absent from core's _createMessage; filters count
    # missing ones against a message (SpamAssassin MISSING_DATE / MISSING_MID).
    # The Message-ID domain follows the From address so it aligns with whatever
    # SPF/DKIM identity the envelope uses.
    message["Date"] = email.utils.formatdate(localtime=True)
    domain = sender.rpartition("@")[2].strip(">") or None
    message["Message-ID"] = email.utils.make_msgid(domain=domain)
    # Marks the message as machine-generated, so vacation responders and the
    # like stay quiet instead of replying to a no-reply address.
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    if logo is not None:
        data, subtype, filename = logo
        # add_related on the HTML part turns it into the multipart/related
        # subtree above, leaving the text alternative untouched.
        message.get_payload()[-1].add_related(
            data,
            maintype="image",
            subtype=subtype,
            cid=f"<{LOGO_CID}>",
            disposition="inline",
            filename=filename,
        )
    return message


def _send(subject, text, html, to, logo=None):
    """Hand one built message to the same ``_sendmail`` event core triggers.

    Core's ``sendMail`` is bypassed because it can only produce a single
    ``MIMEText`` HTML part -- no text alternative, no related image, and none
    of the deliverability headers. Its submitter still does the delivery.
    """
    message = build_message(
        subject,
        text,
        html,
        sender=Setting().get(SettingKey.EMAIL_FROM_ADDRESS),
        to=to,
        logo=logo,
    )
    events.trigger(
        "_sendmail", info={"message": message, "recipients": sorted(set(to))}
    )


def send_submitted_notification(project):
    """Tell the reviewers that ``project`` was submitted for review."""
    recipients = reviewer_emails(project)
    if not recipients:
        logger.warning(
            "No reviewers to notify about proposal %s", project.get("projectId")
        )
        return
    logo = logo_attachment()
    params = {
        "project": project,
        "projectUrl": projects_url(project),
        "submitter": _submitter_name(project),
        "logoUrl": f"cid:{LOGO_CID}" if logo else None,
    }
    # One message per reviewer, each addressed to just that reviewer. The
    # reviewer set spans site admins and per-project flag holders who have no
    # business seeing each other's addresses, and Bcc would not have hidden
    # them: the header is transmitted with the message.
    subject = f"Proposal {project['projectId']} submitted for review"
    text = mail_utils.renderTemplate("projectSubmitted.txt.mako", params)
    html = mail_utils.renderTemplate("projectSubmitted.mako", params)
    for recipient in recipients:
        _send(subject, text, html, to=[recipient], logo=logo)


def send_decision_notification(project, comment=None):
    """Tell the submitter and PIs that ``project`` was accepted or rejected."""
    recipients = submitter_emails(project)
    if not recipients:
        logger.warning(
            "No submitter to notify about proposal %s", project.get("projectId")
        )
        return
    logo = logo_attachment()
    params = {
        "project": project,
        "projectUrl": projects_url(project),
        "comment": comment,
        "logoUrl": f"cid:{LOGO_CID}" if logo else None,
    }
    verb = "accepted" if project["status"] == "accepted" else "declined"
    # A single message with everyone in To, unlike the reviewer notification:
    # these recipients are the proposal's own creator and PIs, who already
    # know each other and may want to reply to the group.
    _send(
        f"Proposal {project['projectId']} {verb}",
        mail_utils.renderTemplate("projectDecision.txt.mako", params),
        mail_utils.renderTemplate("projectDecision.mako", params),
        to=recipients,
        logo=logo,
    )


def notify_project_status(event):
    """Send the workflow email for a proposal status transition.

    Bound to ``model.project.save``, which fires before the write (same hook
    ``ensure_group`` uses), so the saved document is compared against the
    persisted one to detect the transition. Mail delivery is synchronous, so
    failures are logged rather than propagated -- a dead SMTP server must not
    fail the save.
    """
    from ..models.project import Project

    document = event.info
    if "_id" not in document:
        return
    original = Project().load(document["_id"], force=True)
    if original is None or original.get("status") == document.get("status"):
        return
    status = document.get("status")
    try:
        if status == "under review":
            send_submitted_notification(document)
        elif status in ("accepted", "rejected"):
            send_decision_notification(document)
    except Exception:
        logger.exception(
            "Failed to send %s notification for proposal %s",
            status,
            document.get("projectId"),
        )
