"""Render the proposal workflow email templates locally.

Renders ``girder_jsonforms/mail_templates`` with sample data straight through
Mako, exactly the way ``mail_utils.renderTemplate`` does at runtime, so the
markup can be eyeballed (or pasted into a mail client) without a running
Girder, a database, or an SMTP server. Only Mako is needed -- nothing here
imports Girder, so the module can also be run as a plain file:

    python girder_jsonforms/scripts/preview_mail.py --open
    girder-jsonforms-preview-mail --variant accepted --stdout

With --eml it instead writes complete messages, logo attached by Content-ID
just as lib/mail.py sends them, for opening in a real mail client:

    girder-jsonforms-preview-mail --eml --logo-file ~/logo.png --out /tmp/mail
"""

import argparse
import base64
import email.utils
import pathlib
import sys
import webbrowser
from email.message import EmailMessage
from email.policy import SMTP

from mako.lookup import TemplateLookup

#: Must match lib/mail.py:LOGO_CID. Duplicated rather than imported so this
#: script stays runnable without Girder installed; test_mail_preview.py
#: asserts the two agree.
LOGO_CID = "jsonforms-mail-logo"

TEMPLATE_DIR = pathlib.Path(__file__).resolve().parent.parent / "mail_templates"

#: Logos bundled in the package. --logo-file accepts a bare name from here,
#: matching how the jsonforms.mail_logo setting resolves one (see
#: lib/mail.py:resolve_logo).
ASSET_DIR = pathlib.Path(__file__).resolve().parent.parent / "mail_assets"

#: Image types --logo-file will inline. SVG is listed because it is what the
#: CAIMEE mark ships as and it renders in a browser preview; see the caveat on
#: --logo-file about which mail clients actually show it.
LOGO_MIME_TYPES = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

#: Stands in for a Project document. Only the keys the templates touch are
#: needed; ``_id`` is a plain string here since nothing resolves it.
SAMPLE_PROJECT = {
    "_id": "6512f0a4b5c9d81234567890",
    "projectId": "JHU250001",
    "name": "Shock response of high-entropy alloys",
}

SAMPLE_SUBMITTER = "Ada Lovelace"

SAMPLE_COMMENT = (
    "Requested beamtime exceeds the quarterly allocation for a "
    "single-instrument project. Please resubmit with a reduced scope."
)

#: Each variant is (template, extra params). ``status`` drives the accepted vs.
#: declined branch inside projectDecision.mako. The plain-text alternative
#: lives beside each template as <stem>.txt.mako, the way lib/mail.py renders
#: the pair.
VARIANTS = {
    "submitted": ("projectSubmitted.mako", {"submitter": SAMPLE_SUBMITTER}),
    "accepted": ("projectDecision.mako", {"status": "accepted", "comment": None}),
    "rejected": ("projectDecision.mako", {"status": "rejected", "comment": None}),
    "accepted-with-comment": (
        "projectDecision.mako",
        {
            "status": "accepted",
            "comment": "Approved for two runs on MAXIMA in Q3.",
        },
    ),
    "rejected-with-comment": (
        "projectDecision.mako",
        {"status": "rejected", "comment": SAMPLE_COMMENT},
    ),
}

#: Subject lines, mirroring the ones lib/mail.py sends.
SUBJECTS = {
    "submitted": f"Proposal {SAMPLE_PROJECT['projectId']} submitted for review",
    "accepted": f"Proposal {SAMPLE_PROJECT['projectId']} accepted",
    "rejected": f"Proposal {SAMPLE_PROJECT['projectId']} declined",
    "accepted-with-comment": f"Proposal {SAMPLE_PROJECT['projectId']} accepted",
    "rejected-with-comment": f"Proposal {SAMPLE_PROJECT['projectId']} declined",
}

# Wrapper for browser viewing only. The email body itself is a fragment, the
# same as core Girder's templates; --raw writes exactly what gets sent.
_WRAPPER = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
</head>
<body style="margin: 0; background-color: #ffffff;">
{body}</body>
</html>
"""


def resolve_logo(value):
    """A bare name means a bundled asset; anything else is a path."""
    if "/" not in str(value):
        return ASSET_DIR / str(value)
    return pathlib.Path(value).expanduser()


def logo_data_uri(path):
    """Read an image file and return it as a base64 ``data:`` URI.

    Lets a local file (an SVG shield, say) be embedded straight into the
    rendered header with no hosting involved. Raises ValueError for a suffix
    that is not a known image type -- guessing a MIME type from bytes is not
    worth it for a preview tool.
    """
    path = resolve_logo(path)
    mime = LOGO_MIME_TYPES.get(path.suffix.lower())
    if mime is None:
        raise ValueError(
            f"{path.name}: expected one of {', '.join(sorted(LOGO_MIME_TYPES))}"
        )
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def eml_message(subject, text, html, sender, recipient, logo_path=None):
    """Build a full RFC 822 message, mirroring what ``lib/mail.py`` sends.

    Same shape as lib/mail.py:build_message -- multipart/alternative with the
    plain text first and, when ``logo_path`` is given, the HTML wrapped in a
    multipart/related carrying the image as an inline CID part. Opening the
    result in a mail client shows whether that client renders the logo and,
    with the network off, that nothing is fetched to display it.

    Kept in step with build_message by test_mail_preview.py rather than
    importing it, so this script still runs without Girder installed.
    """
    logo = None
    if logo_path is not None:
        logo_path = resolve_logo(logo_path)
        mime = LOGO_MIME_TYPES.get(logo_path.suffix.lower())
        if mime is None:
            raise ValueError(
                f"{logo_path.name}: expected one of "
                f"{', '.join(sorted(LOGO_MIME_TYPES))}"
            )
        logo = (logo_path.read_bytes(), mime.split("/", 1)[1], logo_path.name)

    message = EmailMessage(policy=SMTP)
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message["Date"] = email.utils.formatdate(localtime=True)
    message["Message-ID"] = email.utils.make_msgid(
        domain=sender.rpartition("@")[2].strip(">") or None
    )
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    if logo is not None:
        data, subtype, filename = logo
        message.get_payload()[-1].add_related(
            data,
            maintype="image",
            subtype=subtype,
            cid=f"<{LOGO_CID}>",
            disposition="inline",
            filename=filename,
        )
    return message.as_string()


def render(
    variant,
    brand_name,
    host,
    projects_base,
    logo_url=None,
    logo_height=None,
    comment=None,
    plain=False,
):
    """Render one variant's HTML body, or its text alternative with plain."""
    template_name, extra = VARIANTS[variant]
    if plain:
        template_name = template_name.replace(".mako", ".txt.mako")
    project = dict(SAMPLE_PROJECT)
    if "status" in extra:
        project["status"] = extra["status"]
    params = {
        "project": project,
        "projectUrl": f"{projects_base}/proposal/{project['_id']}",
        "brandName": brand_name,
        "host": host,
        "logoUrl": logo_url,
        "logoHeight": logo_height,
        # renderTemplate() always supplies these two; the templates that do not
        # take them simply ignore the extras.
        "submitter": extra.get("submitter", SAMPLE_SUBMITTER),
        "comment": comment if comment is not None else extra.get("comment"),
    }
    lookup = TemplateLookup(directories=[str(TEMPLATE_DIR)], collection_size=50)
    return lookup.get_template(template_name).render(**params)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--variant",
        action="append",
        choices=sorted(VARIANTS),
        help="Variant to render; repeatable. Defaults to all of them.",
    )
    parser.add_argument(
        "--out",
        default="mail-preview",
        help="Directory to write the .html files into (default: ./mail-preview).",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Write to stdout instead of files (one variant at a time).",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        dest="open_browser",
        help="Open the rendered files in a browser.",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help=(
            "Emit the bare fragment that becomes the message's HTML part, "
            "instead of wrapping it in a minimal HTML document."
        ),
    )
    parser.add_argument(
        "--brand",
        default="AIMD-L Project Proposals",
        help="Value for brandName, normally the core.brand_name setting.",
    )
    parser.add_argument(
        "--host",
        default="https://girder.local.example.com",
        help="Value for host, normally the core.email_host setting.",
    )
    parser.add_argument(
        "--domain",
        default="local.example.com",
        help="Domain the proposals UI links are built from ($DOMAIN at runtime).",
    )
    logo = parser.add_mutually_exclusive_group()
    logo.add_argument(
        "--logo",
        default=None,
        help=(
            "URL for the optional header logo, e.g. "
            "https://projects.<domain>/CAIMEE-Icon.png. Omitted by default, "
            "matching what lib/mail.py sends."
        ),
    )
    logo.add_argument(
        "--logo-file",
        default=None,
        metavar="PATH",
        help=(
            "Inline an image as a "
            "base64 data: URI. This is the local stand-in for the CID "
            "attachment a real send uses -- it shows how the header will look "
            "in a browser, but note that a real send needs a raster image, "
            "since Gmail and Outlook do not render SVG by any transport. "
            "Takes a path, or the bare name of an image bundled in "
            "mail_assets/ (as the jsonforms.mail_logo setting does)."
        ),
    )
    parser.add_argument(
        "--logo-height",
        type=int,
        default=None,
        metavar="PX",
        help="Rendered logo height in pixels (default: 32).",
    )
    form = parser.add_mutually_exclusive_group()
    form.add_argument(
        "--text",
        action="store_true",
        help=(
            "Render the plain-text alternative instead of the HTML -- the "
            "part a text-only reader, and a spam filter, sees."
        ),
    )
    form.add_argument(
        "--eml",
        action="store_true",
        help=(
            "Write .eml messages instead of .html, matching what a real send "
            "produces: with --logo-file the image becomes an inline CID "
            "attachment rather than a data: URI. Open one in a mail client "
            "(offline, to prove nothing is fetched) to check it renders."
        ),
    )
    parser.add_argument(
        "--comment",
        default=None,
        help="Override the review comment shown on the decision templates.",
    )
    args = parser.parse_args()

    variants = args.variant or sorted(VARIANTS)
    projects_base = f"https://projects.{args.domain}"
    if args.eml and args.open_browser:
        parser.error("--open renders HTML; open the .eml with your mail client")

    # In .eml mode the local file rides along as a CID part, so the markup
    # references it the way a real send does instead of embedding the bytes.
    logo_url = args.logo
    if args.logo_file:
        if args.eml:
            logo_url = f"cid:{LOGO_CID}"
        else:
            try:
                logo_url = logo_data_uri(args.logo_file)
            except (OSError, ValueError) as exc:
                parser.error(f"--logo-file: {exc}")

    def _render(variant):
        kwargs = {
            "brand_name": args.brand,
            "host": args.host,
            "projects_base": projects_base,
            "comment": args.comment,
        }
        if args.text:
            return render(variant, plain=True, **kwargs)
        body = render(
            variant,
            logo_url=logo_url,
            logo_height=args.logo_height,
            **kwargs,
        )
        if args.eml:
            recipient = (
                f"reviewer@{args.domain}"
                if variant == "submitted"
                else f"pi@{args.domain}"
            )
            try:
                return eml_message(
                    SUBJECTS[variant],
                    render(variant, plain=True, **kwargs),
                    body,
                    sender=f"no-reply@{args.domain}",
                    recipient=recipient,
                    logo_path=args.logo_file,
                )
            except (OSError, ValueError) as exc:
                parser.error(f"--logo-file: {exc}")
        if args.raw:
            return body
        return _WRAPPER.format(title=f"{args.brand} - {variant}", body=body)

    if args.stdout:
        if len(variants) > 1:
            parser.error("--stdout renders one variant; pass a single --variant")
        sys.stdout.write(_render(variants[0]))
        return 0

    suffix = "eml" if args.eml else "txt" if args.text else "html"
    out_dir = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for variant in variants:
        path = out_dir / f"{variant}.{suffix}"
        path.write_text(_render(variant), encoding="utf8")
        print(path)
        if args.open_browser:
            webbrowser.open(path.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
