from __future__ import annotations

import io

import pytest

from app.media.render_executor import _resolve_font_stack
from tests.util import fresh_client, second_client


def _build_font(family: str) -> bytes:
    """A minimal but genuinely parseable TTF carrying `family` in its name table."""
    fontTools = pytest.importorskip("fontTools")
    assert fontTools
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "A"])
    builder.setupCharacterMap({ord("A"): "A"})
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0))
    pen.lineTo((0, 700))
    pen.lineTo((500, 700))
    pen.closePath()
    glyph = pen.glyph()
    builder.setupGlyf({".notdef": glyph, "A": glyph})
    builder.setupHorizontalMetrics({".notdef": (500, 0), "A": (500, 0)})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": family, "styleName": "Regular", "psName": family.replace(" ", "")})
    builder.setupOS2()
    builder.setupPost()
    buffer = io.BytesIO()
    builder.save(buffer)
    return buffer.getvalue()


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_upload_reads_family_from_the_font_not_the_filename() -> None:
    client = fresh_client()
    ws = _workspace(client)

    res = client.post(
        "/api/fonts",
        data={"workspace_id": ws},
        files={"file": ("some-download-name.ttf", _build_font("Studio Display"), "font/ttf")},
    )
    assert res.status_code == 200, res.text
    font = res.json()
    # The filename is deliberately unrelated: libass matches on the family in the name table,
    # so storing the filename would make export miss a font the preview rendered.
    assert font["family"] == "Studio Display"
    assert font["original_filename"] == "some-download-name.ttf"

    listing = client.get("/api/fonts", params={"workspace_id": ws}).json()
    assert [f["id"] for f in listing] == [font["id"]]

    assert client.get(f"/api/fonts/{font['id']}/file").status_code == 200
    assert client.delete(f"/api/fonts/{font['id']}").status_code == 204
    assert client.get("/api/fonts", params={"workspace_id": ws}).json() == []


def test_upload_rejects_non_font_and_wrong_extension() -> None:
    client = fresh_client()
    ws = _workspace(client)

    woff = client.post(
        "/api/fonts",
        data={"workspace_id": ws},
        files={"file": ("x.woff2", b"whatever", "font/woff2")},
    )
    # woff renders in the browser but not in libass — accepting it would preview correctly
    # and then export in a fallback face.
    assert woff.status_code == 422

    junk = client.post(
        "/api/fonts",
        data={"workspace_id": ws},
        files={"file": ("fake.ttf", b"not a font at all", "font/ttf")},
    )
    assert junk.status_code == 422
    assert client.get("/api/fonts", params={"workspace_id": ws}).json() == []


def test_font_is_scoped_to_its_workspace() -> None:
    client = fresh_client()
    ws = _workspace(client)
    font_id = client.post(
        "/api/fonts",
        data={"workspace_id": ws},
        files={"file": ("f.ttf", _build_font("Private Face"), "font/ttf")},
    ).json()["id"]

    other = second_client()
    assert other.get(f"/api/fonts/{font_id}/file").status_code in (403, 404)


def test_export_resolves_an_uploaded_font_to_its_family_and_directory() -> None:
    from app.core.db import SessionLocal
    from app.db.models import Sequence
    from app.domain.render import _resolve_subtitle_font

    client = fresh_client()
    ws = _workspace(client)
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws, "project_id": project["id"], "name": "S"},
    ).json()
    font = client.post(
        "/api/fonts",
        data={"workspace_id": ws},
        files={"file": ("f.ttf", _build_font("Burned In"), "font/ttf")},
    ).json()

    saved = client.put(
        f"/api/sequences/{sequence['id']}/subtitle-style",
        json={"style": {"font_id": font["id"], "font_family": '"Burned In", sans-serif'}},
    )
    assert saved.status_code == 200, saved.text

    with SessionLocal() as db:
        resolved = _resolve_subtitle_font(db, db.get(Sequence, sequence["id"]))
    assert resolved["font_family"] == "Burned In"
    assert resolved["font_dir"], "libass needs a directory or it silently falls back"


@pytest.mark.parametrize(
    ("stack", "expected"),
    [
        # Leading generics must be skipped: system-ui resolves to a Latin-only face with no
        # CJK glyphs, so taking the first entry would break Chinese subtitles on export.
        ('system-ui, -apple-system, "PingFang SC", sans-serif', "PingFang SC"),
        ('"Xingkai SC", "STXingkai", "KaiTi", cursive', "Xingkai SC"),
        ("sans-serif", "Sans"),
        ("", "Sans"),
        (None, "Sans"),
        # A newline in a family name would otherwise inject extra ASS Style:/Dialogue: lines.
        ("Evil\nStyle: Injected", "Evil Style: Injected"),
    ],
)
def test_font_stack_resolves_to_one_libass_family(stack, expected) -> None:
    assert _resolve_font_stack(stack) == expected
