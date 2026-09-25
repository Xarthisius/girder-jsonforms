import pathlib
import struct
import zlib

import pytest

from girder.exceptions import ValidationException
from girder.models.setting import Setting
from girder.models.user import User

from ..lib import mail
from ..models.project import Project as ProjectModel
from ..settings import MAIL_ASSET_DIR, PluginSettings


def _png_bytes():
    """Smallest valid 1x1 PNG, built rather than checked in as a fixture."""

    def chunk(kind, payload):
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(
            ">I", zlib.crc32(body)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00"))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def logo_file(tmp_path):
    path = tmp_path / "shield.png"
    path.write_bytes(_png_bytes())
    return path


@pytest.fixture
def draft_project(server, user):
    return ProjectModel().create_project(
        {
            "name": "Shock response of <alloys>",
            "description": "A project for testing proposal emails",
            "creatorId": user["_id"],
            "members": [
                {"email": "pi@example.com", "role": "PI", "firstName": "Ada"},
                {"email": "grad@example.com", "role": "user"},
            ],
        },
        user,
    )


def _part(msg, content_type):
    """The first part of the given type. Messages are multipart/alternative
    now, so a body assertion has to name which representation it means."""
    for part in msg.walk():
        if part.get_content_type() == content_type:
            return part.get_payload(decode=True).decode("utf8")
    raise AssertionError(f"no {content_type} part in message")


def _body(msg):
    return _part(msg, "text/html")


def _text(msg):
    return _part(msg, "text/plain")


@pytest.mark.plugin("jsonforms")
def test_submitting_notifies_reviewers(
    server, admin, user, draft_project, sent_mail, eagerWorkerTasks
):
    ProjectModel().update_project(draft_project, {"status": "under review"}, user)

    assert len(sent_mail) == 1
    msg, recipients = sent_mail[0]
    assert recipients == [admin["email"]]
    # Each reviewer gets their own copy, addressed to them: a Bcc header would
    # have been transmitted with the message and disclosed the whole list.
    assert msg["To"] == admin["email"]
    assert msg["Bcc"] is None
    assert draft_project["projectId"] in msg["Subject"]
    body = _body(msg)
    assert "is ready for review" in body
    assert f"/proposal/{draft_project['_id']}" in body
    # The project name is user input and must reach the email escaped.
    assert "&lt;alloys&gt;" in body
    assert "<alloys>" not in body


@pytest.mark.parametrize(
    "status,expected",
    [("accepted", "accepted"), ("rejected", "declined")],
)
@pytest.mark.plugin("jsonforms")
def test_decision_notifies_submitter_and_pis(
    server, admin, user, draft_project, sent_mail, eagerWorkerTasks, status, expected
):
    ProjectModel().update_project(draft_project, {"status": status}, admin)

    assert len(sent_mail) == 1
    msg, recipients = sent_mail[0]
    # sendMail computes the recipient list through a set, so compare unordered.
    assert set(recipients) == {user["email"], "pi@example.com"}
    # The 'user' role member is not told about the decision.
    assert "grad@example.com" not in recipients
    assert msg["To"] == ", ".join(sorted({user["email"], "pi@example.com"}))
    assert msg["Subject"] == f"Proposal {draft_project['projectId']} {expected}"
    assert expected in _body(msg)


@pytest.mark.plugin("jsonforms")
def test_no_mail_without_a_status_transition(
    server, user, draft_project, sent_mail, eagerWorkerTasks
):
    ProjectModel().update_project(draft_project, {"description": "Reworded"}, user)
    assert sent_mail == []


@pytest.mark.plugin("jsonforms")
def test_reviewer_emails_include_flag_holders(
    server, admin, user, draft_project, eagerWorkerTasks
):
    """Access flags are per-document, so a user granted the review flag on a
    proposal is notified alongside the site admins."""
    reviewer = User().createUser(
        login="reviewer",
        password="password",
        firstName="Rev",
        lastName="Iewer",
        email="reviewer@example.com",
    )
    project = ProjectModel().setUserAccess(
        draft_project,
        reviewer,
        level=0,
        save=True,
        flags=[mail.REVIEW_FLAG],
        currentUser=admin,
    )

    assert mail.reviewer_emails(project) == sorted(
        {admin["email"], reviewer["email"]}
    )


@pytest.mark.plugin("jsonforms")
def test_projects_url_follows_domain(server, draft_project, monkeypatch):
    monkeypatch.setenv("DOMAIN", "example.org")
    assert mail.projects_url() == "https://projects.example.org"
    assert mail.projects_url(draft_project) == (
        f"https://projects.example.org/proposal/{draft_project['_id']}"
    )


@pytest.mark.plugin("jsonforms")
def test_every_message_carries_a_text_alternative(
    server, admin, user, draft_project, sent_mail, eagerWorkerTasks
):
    """HTML-only bodies score badly with spam filters, so each message is a
    multipart/alternative with the plain text first (RFC 2046 orders
    alternatives least- to most-preferred)."""
    ProjectModel().update_project(draft_project, {"status": "accepted"}, admin)

    msg, _ = sent_mail[0]
    assert msg.get_content_type() == "multipart/alternative"
    assert [p.get_content_type() for p in msg.get_payload()] == [
        "text/plain",
        "text/html",
    ]
    text = _text(msg)
    assert "has been accepted" in text
    assert f"/proposal/{draft_project['_id']}" in text
    # Plain text, so the raw project name appears unescaped here.
    assert "<alloys>" in text
    assert "<p" not in text


@pytest.mark.plugin("jsonforms")
def test_deliverability_headers_are_set(
    server, admin, user, draft_project, sent_mail, eagerWorkerTasks
):
    """Core's _createMessage writes neither Date nor Message-ID, and filters
    count both against a message."""
    ProjectModel().update_project(draft_project, {"status": "accepted"}, admin)

    msg, _ = sent_mail[0]
    assert msg["Date"]
    sender_domain = msg["From"].rpartition("@")[2].strip(">")
    assert msg["Message-ID"].startswith("<")
    assert msg["Message-ID"].endswith(f"@{sender_domain}>")
    assert msg["Auto-Submitted"] == "auto-generated"
    # Core's submitter calls as_string(); under the SMTP policy that has to be
    # 7-bit clean or smtplib's ascii encode would fail on non-ASCII input.
    assert msg.as_string().isascii()


@pytest.mark.plugin("jsonforms")
def test_no_logo_means_no_image_part(
    server, admin, user, draft_project, sent_mail, eagerWorkerTasks
):
    """With jsonforms.mail_logo unset (the default) nothing is attached and the
    header renders typographically."""
    ProjectModel().update_project(draft_project, {"status": "accepted"}, admin)

    msg, _ = sent_mail[0]
    assert not any(p.get_content_maintype() == "image" for p in msg.walk())
    assert "<img" not in _body(msg)


@pytest.mark.plugin("jsonforms")
def test_logo_is_attached_by_cid_not_fetched(
    server, admin, user, draft_project, sent_mail, logo_file, eagerWorkerTasks
):
    """The logo must ride along as an inline related part the HTML references
    by cid:, so rendering the message never fetches anything from us."""
    Setting().set(PluginSettings.MAIL_LOGO, str(logo_file))

    ProjectModel().update_project(draft_project, {"status": "under review"}, user)

    msg, _ = sent_mail[0]
    # The logo lives inside the HTML alternative, so the text part is not
    # dragged into a related subtree it has no use for.
    assert [p.get_content_type() for p in msg.walk()] == [
        "multipart/alternative",
        "text/plain",
        "multipart/related",
        "text/html",
        "image/png",
    ]
    body = _body(msg)
    assert f'src="cid:{mail.LOGO_CID}"' in body
    # No remote reference of any kind is left in the markup.
    assert "https://projects" not in body.split("<img")[1].split("/>")[0]

    image = list(msg.walk())[-1]
    assert image["Content-ID"] == f"<{mail.LOGO_CID}>"
    assert image.get_filename() == logo_file.name
    assert image.get("Content-Disposition", "").startswith("inline")
    assert image.get_payload(decode=True) == logo_file.read_bytes()


@pytest.mark.plugin("jsonforms")
def test_missing_logo_file_degrades_to_no_logo(
    server, admin, user, draft_project, sent_mail, tmp_path, eagerWorkerTasks
):
    """A configured-but-absent logo (setting written before the file is
    mounted) must not fail the send."""
    Setting().set(PluginSettings.MAIL_LOGO, str(tmp_path / "absent.png"))

    ProjectModel().update_project(draft_project, {"status": "under review"}, user)

    msg, _ = sent_mail[0]
    assert not any(p.get_content_maintype() == "image" for p in msg.walk())
    assert "<img" not in _body(msg)


@pytest.mark.plugin("jsonforms")
def test_mail_logo_setting_rejects_svg(server, logo_file):
    """SVG renders in no major mail client, so it is refused up front rather
    than silently producing a broken logo."""
    with pytest.raises(ValidationException):
        Setting().set(PluginSettings.MAIL_LOGO, "/srv/logo.svg")
    # A raster image and the empty default are both fine.
    Setting().set(PluginSettings.MAIL_LOGO, str(logo_file))
    Setting().set(PluginSettings.MAIL_LOGO, "")


@pytest.mark.plugin("jsonforms")
def test_each_reviewer_gets_a_separate_copy(
    server, admin, user, draft_project, sent_mail, eagerWorkerTasks
):
    """Reviewers span site admins and per-project flag holders, who must not
    learn each other's addresses -- so one message each, never a shared Bcc."""
    second_admin = User().createUser(
        login="admin2",
        password="password",
        firstName="Second",
        lastName="Admin",
        email="admin2@example.com",
        admin=True,
    )

    ProjectModel().update_project(draft_project, {"status": "under review"}, user)

    assert len(sent_mail) == 2
    assert {msg["To"] for msg, _ in sent_mail} == {
        admin["email"],
        second_admin["email"],
    }
    for msg, recipients in sent_mail:
        assert msg["Bcc"] is None
        assert recipients == [msg["To"]]
        # Distinct Message-IDs: two copies are two messages, not one resent.
        assert msg["Message-ID"]
    assert sent_mail[0][0]["Message-ID"] != sent_mail[1][0]["Message-ID"]


@pytest.mark.plugin("jsonforms")
def test_bundled_logo_is_named_not_pathed(
    server, admin, user, draft_project, sent_mail, eagerWorkerTasks
):
    """A bare filename resolves to an image shipped inside the package, so a
    deployment needs no image mounted into the container."""
    bundled = MAIL_ASSET_DIR / "caimee-shield-80.png"
    assert bundled.is_file(), "the CAIMEE shield should ship with the package"

    Setting().set(PluginSettings.MAIL_LOGO, bundled.name)
    ProjectModel().update_project(draft_project, {"status": "accepted"}, admin)

    msg, _ = sent_mail[0]
    image = list(msg.walk())[-1]
    assert image.get_content_type() == "image/png"
    assert image.get_filename() == bundled.name
    assert image.get_payload(decode=True) == bundled.read_bytes()
    assert f'src="cid:{mail.LOGO_CID}"' in _body(msg)


@pytest.mark.plugin("jsonforms")
def test_mail_logo_setting_checks_bundled_names(server, tmp_path):
    """A bundled name can be verified at set time, unlike a mounted path."""
    with pytest.raises(ValidationException):
        Setting().set(PluginSettings.MAIL_LOGO, "no-such-logo.png")
    Setting().set(PluginSettings.MAIL_LOGO, "caimee-shield-80.png")
    # A path is accepted unchecked -- the file may not be mounted yet.
    Setting().set(PluginSettings.MAIL_LOGO, str(tmp_path / "later.png"))


def test_resolve_logo_distinguishes_names_from_paths(tmp_path):
    assert mail.resolve_logo("caimee-shield-80.png") == (
        MAIL_ASSET_DIR / "caimee-shield-80.png"
    )
    assert mail.resolve_logo(str(tmp_path / "x.png")) == tmp_path / "x.png"
    assert mail.resolve_logo("~/x.png") == pathlib.Path.home() / "x.png"
