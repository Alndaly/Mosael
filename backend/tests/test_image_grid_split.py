"""宫格切分:把九宫格、四宫格这类拼图等分切成单图(图片格的一项能力、工作流节点、智能体工具同一份实现)。"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.domain.assets.image_grid import ImageGridError, parse_grid, tile_boxes, trim_gutter


def test_等分_除不尽的像素分给相邻两张_不丢不重() -> None:
    boxes = tile_boxes(100, 50, 2, 3)
    assert boxes[0] == (0, 0, 33, 25) and boxes[2] == (67, 0, 100, 25) and boxes[-1] == (67, 25, 100, 50)
    #: 横向相邻的两张首尾相接。
    assert all(boxes[i][2] == boxes[i + 1][0] for i in (0, 1, 3, 4))
    assert sum((r - l) * (b - t) for l, t, r, b in boxes) == 100 * 50


def test_切法只认预设() -> None:
    assert parse_grid("3x3") == (3, 3) and parse_grid("2x3") == (2, 3)
    with pytest.raises(ImageGridError):
        parse_grid("5x5")


def test_去分隔线_只去同色的一圈_每边最多6成() -> None:
    #: 100×100 的白底,中间 80×80 是红的:四周 10 像素的白边就是分隔线,但每边最多去 6 像素。
    tile = Image.new("RGB", (100, 100), "white")
    tile.paste(Image.new("RGB", (80, 80), "red"), (10, 10))
    trimmed = trim_gutter(tile)
    assert trimmed.size == (88, 88)
    #: 没有同色的一圈(画面顶到边)就原样返回。
    plain = Image.new("RGB", (50, 50), "red")
    plain.paste(Image.new("RGB", (10, 10), "blue"), (0, 0))
    assert trim_gutter(plain).size == (50, 50)


def _grid_png(rows: int, cols: int, size: int = 90) -> bytes:
    colors = ["red", "green", "blue", "yellow", "purple", "orange", "white", "black", "gray"]
    image = Image.new("RGB", (size * cols, size * rows))
    for index in range(rows * cols):
        image.paste(Image.new("RGB", (size, size), colors[index % len(colors)]),
                    ((index % cols) * size, (index // cols) * size))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def test_切成九张进素材库_按阅读顺序_记着出处(tmp_path) -> None:
    from app.core.db import SessionLocal
    from app.db.models import Asset
    from app.domain.assets.image_grid import split_image_grid
    from app.media.paths import resolve_key
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    made = client.post("/api/assets/import", data={"workspace_id": ws},
                       files={"file": ("sheet.png", _grid_png(3, 3), "image/png")})
    assert made.status_code in (200, 201), made.text
    source_id = made.json()["id"]
    with SessionLocal() as db:
        pieces = split_image_grid(db, db.get(Asset, source_id), grid="3x3")
        source_name = db.get(Asset, source_id).name
        assert [piece.name for piece in pieces] == [f"{source_name} · {n}" for n in range(1, 10)]
        first, fifth = pieces[0], pieces[4]
        assert first.derived_from == [{"asset_id": source_id, "op": "grid_split"}] and first.media_info["grid_cell"] == [1, 1]
        assert fifth.media_info["grid_cell"] == [2, 2]
        with Image.open(resolve_key(fifth.file_key)) as tile:
            assert tile.size == (90, 90) and tile.convert("RGB").getpixel((45, 45)) == (128, 0, 128)


def test_画板上切出的几张照原来的宫格排_高度按原图比例() -> None:
    from app.domain.boards.canvas import _derive

    host = {"id": "h", "kind": "image", "x": 0, "y": 0, "width": 300, "height": 450}
    outputs = [{"type": "asset", "asset_id": f"a{n}"} for n in range(6)] + [{"type": "layout", "columns": 3}]
    assets = {f"a{n}": ("image", f"a{n}") for n in range(6)}
    items, edges = _derive(host, outputs, assets, [host], [])
    assert len(items) == 6 and len(edges) == 6
    xs = sorted({item["x"] for item in items})
    ys = sorted({item["y"] for item in items})
    assert len(xs) == 3 and len(ys) == 2, "3 列 2 行"
    #: 300×450 切成 2 行 3 列:每张 100×225,宽 200 时高 450。
    assert items[0]["height"] == pytest.approx(items[0]["width"] * 2.25)
    #: 下一行从上一行的底下再空出一截(每一格头上有标签)。
    assert ys[1] - ys[0] > items[0]["height"]
    #: 不带 layout 的照旧竖成一列。
    column, _ = _derive(host, outputs[:-1], assets, [host], [])
    assert len({item["x"] for item in column}) == 1


def test_节点在工作流里跑_交回全部和列数() -> None:
    from app.domain.workflows import NODE_TYPES

    spec = NODE_TYPES["image_grid_split"]
    assert spec["board_columns"] == "columns" and "board" in spec["surfaces"]
    assert spec["config"]["grid"]["default"] == "3x3"
