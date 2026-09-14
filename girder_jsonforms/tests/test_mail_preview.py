"""Guard for the local template preview script.

Pure Mako rendering -- no Girder fixtures, no database -- so this stays in its
own module rather than alongside the ``server``-backed mail tests.
"""

import base64

import pytest

from ..scripts.preview_mail import VARIANTS, logo_data_uri, render

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>'


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_every_variant_renders(variant):
    html = render(
        variant,
        brand_name="Test Proposals",
        host="https://girder.test",
        projects_base="https://projects.test",
    )
    assert "Test Proposals" in html
    assert "JHU250001" in html
    assert "https://projects.test/proposal/" in html


def test_comment_override_reaches_the_decision_template():
    html = render(
        "accepted",
        brand_name="Test Proposals",
        host="https://girder.test",
        projects_base="https://projects.test",
        comment="Approved for two runs.",
    )
    assert "Approved for two runs." in html


def test_logo_is_omitted_unless_asked_for():
    kwargs = {
        "brand_name": "Test Proposals",
        "host": "https://girder.test",
        "projects_base": "https://projects.test",
    }
    assert "<img" not in render("submitted", **kwargs)
    assert "logo.png" in render("submitted", logo_url="https://x.test/logo.png", **kwargs)


def test_logo_data_uri_inlines_an_svg(tmp_path):
    path = tmp_path / "shield.svg"
    path.write_bytes(SVG)
    uri = logo_data_uri(path)
    assert uri.startswith("data:image/svg+xml;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]) == SVG


def test_logo_data_uri_rejects_a_non_image(tmp_path):
    path = tmp_path / "shield.txt"
    path.write_bytes(SVG)
    with pytest.raises(ValueError):
        logo_data_uri(path)


def test_logo_data_uri_expands_a_home_relative_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "shield.svg").write_bytes(SVG)
    assert logo_data_uri("~/shield.svg").startswith("data:image/svg+xml;base64,")


def test_inline_logo_and_height_reach_the_header(tmp_path):
    path = tmp_path / "shield.svg"
    path.write_bytes(SVG)
    html = render(
        "submitted",
        brand_name="Test Proposals",
        host="https://girder.test",
        projects_base="https://projects.test",
        logo_url=logo_data_uri(path),
        logo_height=48,
    )
    assert 'src="data:image/svg+xml;base64,' in html
    assert 'height="48"' in html
    assert "height: 48px" in html


def test_logo_height_defaults_to_32():
    html = render(
        "submitted",
        brand_name="Test Proposals",
        host="https://girder.test",
        projects_base="https://projects.test",
        logo_url="https://x.test/logo.png",
    )
    assert 'height="32"' in html


def test_preview_cid_matches_the_send_path():
    """The script duplicates LOGO_CID to stay importable without Girder; if it
    drifts, an .eml preview stops matching what lib/mail.py actually sends."""
    from ..lib.mail import LOGO_CID as send_cid
    from ..scripts.preview_mail import LOGO_CID as preview_cid

    assert preview_cid == send_cid


def test_eml_structure_matches_the_send_path(tmp_path):
    """The script rebuilds the message instead of importing build_message (so
    it runs without Girder), so assert the two produce the same MIME tree."""
    import email

    from ..lib.mail import build_message
    from ..scripts.preview_mail import eml_message

    logo = tmp_path / "shield.png"
    logo.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-png")
    kwargs = {
        "subject": "Proposal JHU250001 accepted",
        "text": "plain body",
        "html": "<p>html body</p>",
        "sender": "no-reply@test",
    }

    for logo_arg in (None, logo):
        sent = build_message(
            to=["pi@test"],
            logo=(
                None
                if logo_arg is None
                else (logo.read_bytes(), "png", logo.name)
            ),
            **kwargs,
        )
        previewed = email.message_from_string(
            eml_message(recipient="pi@test", logo_path=logo_arg, **kwargs)
        )
        assert [p.get_content_type() for p in previewed.walk()] == [
            p.get_content_type() for p in sent.walk()
        ]
        assert {h for h, _ in previewed.items()} == {h for h, _ in sent.items()}


def test_eml_carries_the_logo_as_an_inline_cid_part(tmp_path):
    import email

    from ..scripts.preview_mail import LOGO_CID, eml_message

    logo = tmp_path / "shield.png"
    logo.write_bytes(b"\x89PNG\r\n\x1a\nnot-a-real-png")
    html = render(
        "submitted",
        brand_name="Test Proposals",
        host="https://girder.test",
        projects_base="https://projects.test",
        logo_url=f"cid:{LOGO_CID}",
    )
    raw = eml_message(
        "Proposal JHU250001 submitted for review",
        render(
            "submitted",
            brand_name="Test Proposals",
            host="https://girder.test",
            projects_base="https://projects.test",
            plain=True,
        ),
        html,
        sender="no-reply@test",
        recipient="reviewer@test",
        logo_path=logo,
    )

    msg = email.message_from_string(raw)
    assert [p.get_content_type() for p in msg.walk()] == [
        "multipart/alternative",
        "text/plain",
        "multipart/related",
        "text/html",
        "image/png",
    ]
    html_part, image = msg.get_payload()[1].get_payload()
    assert f'src="cid:{LOGO_CID}"' in html_part.get_payload(decode=True).decode()
    assert image["Content-ID"] == f"<{LOGO_CID}>"
    assert image.get_payload(decode=True) == logo.read_bytes()


def test_eml_without_a_logo_is_text_plus_html():
    import email

    from ..scripts.preview_mail import eml_message

    raw = eml_message(
        "Subject",
        "hi",
        "<p>hi</p>",
        sender="no-reply@test",
        recipient="pi@test",
    )
    msg = email.message_from_string(raw)
    assert [p.get_content_type() for p in msg.walk()] == [
        "multipart/alternative",
        "text/plain",
        "text/html",
    ]


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_every_variant_has_a_text_alternative(variant):
    text = render(
        variant,
        brand_name="Test Proposals",
        host="https://girder.test",
        projects_base="https://projects.test",
        plain=True,
    )
    assert "JHU250001" in text
    assert "https://projects.test/proposal/" in text
    # Plain text: no markup, and no HTML escaping applied to it.
    assert "<p" not in text
    assert "&amp;" not in text


def test_preview_resolves_bundled_logos_like_the_send_path(tmp_path):
    """The script resolves --logo-file the way jsonforms.mail_logo resolves;
    both must agree on what a bare name versus a path means."""
    from ..lib.mail import resolve_logo as send_resolve
    from ..scripts.preview_mail import ASSET_DIR
    from ..scripts.preview_mail import resolve_logo as preview_resolve

    for value in ("caimee-shield-80.png", str(tmp_path / "x.png"), "~/x.png"):
        assert preview_resolve(value) == send_resolve(value)
    assert (ASSET_DIR / "caimee-shield-80.png").is_file()


def test_bundled_logo_can_be_inlined_by_name():
    from ..scripts.preview_mail import ASSET_DIR

    uri = logo_data_uri("caimee-shield-80.png")
    assert uri.startswith("data:image/png;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]) == (
        ASSET_DIR / "caimee-shield-80.png"
    ).read_bytes()
