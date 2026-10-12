"""蒙版:从源图的像素算一张灰度蒙版,落成一份新素材(ADR 0056 决定 6)。

**契约是这一条,所有断言都绕着它**:灰度 PNG、白 = 要改的地方、**没有 alpha 通道**。带透明通道的
图在 ComfyUI 那条注入的路(`LoadImageMask(channel="red")`)上读出来是整块不透明 —— **静默地什么都
不重绘**,所以这里有一条**显式**断言钉着「灰度 + alpha 不透明」;别的都能靠肉眼看出来,这一条不能。

纯函数那几条用小图(8×8)逐像素断言:阈值、alpha、反选、扩张、羽化各一条。
"""

from __future__ import annotations

import io
import json
import wave

import numpy as np
import pytest
from PIL import Image

from app.media.masks import (
    MaskError,
    feather_mask,
    grow_mask,
    invert_mask,
    mask_from_alpha,
    mask_from_luminance,
    read_rgba,
    write_mask_png,
)

W = H = 8
SIZE = (W, H)


def _pixels(at_pixel) -> bytes:
    """8×8 的 RGBA 像素:每一格由 `at_pixel(x, y)` 给 `(r, g, b, a)`。"""
    data = bytearray(W * H * 4)
    for y in range(H):
        for x in range(W):
            at = (y * W + x) * 4
            data[at:at + 4] = bytes(at_pixel(x, y))
    return bytes(data)


def _gray_split() -> bytes:
    """左半边 30、右半边 220 的灰:一条竖着的分界线落在第 4 列上。"""
    return _pixels(lambda x, _y: (30, 30, 30, 255) if x < W // 2 else (220, 220, 220, 255))


def _solid(rgba: tuple[int, int, int, int]) -> bytes:
    return _pixels(lambda _x, _y: rgba)


def test_按亮度阈值_亮的一侧变白() -> None:
    mask = mask_from_luminance(_gray_split(), SIZE, 0.5)
    assert len(mask) == W * H and set(mask) == {0, 255}, "二值化:非黑即白"
    assert mask[:W] == bytes([0, 0, 0, 0, 255, 255, 255, 255])
    #: 每一行都一样(分界线是竖的),不是只有第一行对。
    assert all(mask[y * W:(y + 1) * W] == mask[:W] for y in range(H))


def test_阈值判的是_大于等于_而且按Rec601加权() -> None:
    #: `>=`:128 在阈值 0.5(切在 127.5)之上算白,127 不算。
    assert set(mask_from_luminance(_solid((128, 128, 128, 255)), SIZE, 0.5)) == {255}
    assert set(mask_from_luminance(_solid((127, 127, 127, 255)), SIZE, 0.5)) == {0}
    #: 加权:纯红 0.299×255≈76、纯绿 0.587×255≈150 —— 取平均的话两个都是 85,那就分不出来了。
    assert set(mask_from_luminance(_solid((255, 0, 0, 255)), SIZE, 0.5)) == {0}
    assert set(mask_from_luminance(_solid((0, 255, 0, 255)), SIZE, 0.5)) == {255}
    #: 两头都是合法输入:0 全白,1 只剩纯白。
    assert set(mask_from_luminance(_gray_split(), SIZE, 0.0)) == {255}
    assert set(mask_from_luminance(_gray_split(), SIZE, 1.0)) == {0}
    assert set(mask_from_luminance(_solid((255, 255, 255, 255)), SIZE, 1.0)) == {255}


def test_按alpha阈值_不透明的地方变白() -> None:
    #: 两半的颜色完全不同、只有透明度是分界 —— 取的是 alpha,不是亮度。
    picture = _pixels(lambda x, _y: (10, 200, 30, 0) if x < W // 2 else (250, 0, 0, 255))
    assert mask_from_alpha(picture, SIZE, 0.5)[:W] == bytes([0, 0, 0, 0, 255, 255, 255, 255])
    #: 半透明按阈值切:alpha 128 在 0.5 之上,alpha 127 不算。
    assert set(mask_from_alpha(_solid((0, 0, 0, 128)), SIZE, 0.5)) == {255}
    assert set(mask_from_alpha(_solid((0, 0, 0, 127)), SIZE, 0.5)) == {0}
    #: 源图没有透明通道时是整块白 —— 不是算错,是那张图本来就没有透的地方。
    assert set(mask_from_alpha(_gray_split(), SIZE, 0.5)) == {255}


def test_反选_黑变白白变黑_灰边按255减() -> None:
    base = mask_from_luminance(_gray_split(), SIZE, 0.5)
    flipped = invert_mask(base)
    assert flipped[:W] == bytes([255, 255, 255, 255, 0, 0, 0, 0])
    assert invert_mask(flipped) == base, "翻两次回到原样"
    #: 灰的(羽化过的边)按 255-v 翻,不重新二值化:翻过来还是一条同样软的边。
    soft = bytes([0, 64, 128, 200, 255]) + bytes(W * H - 5)
    assert invert_mask(soft)[:5] == bytes([255, 191, 127, 55, 0])


def test_扩张_白的一圈长出去_收缩反过来() -> None:
    base = mask_from_luminance(_gray_split(), SIZE, 0.5)
    assert grow_mask(base, SIZE, 1)[:W] == bytes([0, 0, 0, 255, 255, 255, 255, 255]), "扩张啃掉一格黑"
    assert grow_mask(base, SIZE, -1)[:W] == bytes([0, 0, 0, 0, 0, 255, 255, 255]), "收缩啃掉一格白"
    assert grow_mask(base, SIZE, 0) == base
    #: 两轴都跑:正中间一个白点,扩张一格得到一个 3×3 的块(只跑横轴的话是一条横线)。
    dot = bytearray(W * H)
    dot[3 * W + 3] = 255
    grown = grow_mask(bytes(dot), SIZE, 1)
    assert [grown[y * W + x] for y in (2, 3, 4) for x in (2, 3, 4)] == [255] * 9
    assert grown[3 * W + 1] == 0 and grown[1 * W + 3] == 0
    #: 四边夹取:白顶着右边,扩张之后右边一整列还是白(补零的话它会缩掉一圈)。
    assert grow_mask(base, SIZE, 1)[7] == 255 and grow_mask(base, SIZE, 1)[15] == 255
    #: 灰的照灰的取最大,不先二值化 —— 那一圈软边不该被这一步啃成硬边。
    soft = bytearray(W * H)
    soft[3 * W + 3] = 128
    assert grow_mask(bytes(soft), SIZE, 1)[3 * W + 2] == 128


def test_羽化_把边晕开_四边夹取() -> None:
    base = mask_from_luminance(_gray_split(), SIZE, 0.5)
    soft = feather_mask(base, SIZE, 2)
    row = soft[:W]
    assert list(row) == sorted(row), "从左到右越来越白"
    assert 0 < row[0] and row[-1] < 255, "两头都软了,不是硬边"
    assert len(set(row)) > 2
    #: `radius < 1` 什么都不做。
    assert feather_mask(base, SIZE, 0.4) == base
    #: 边缘夹取而不是补零:整块白的图羽化之后还是整块白,不会四周自己黑一圈。
    assert set(feather_mask(bytes([255]) * (W * H), SIZE, 3)) == {255}
    assert set(feather_mask(bytes([0]) * (W * H), SIZE, 3)) == {0}


def test_像素数目对不上就报错_不静默出一张错图(tmp_path) -> None:
    with pytest.raises(MaskError):
        mask_from_luminance(bytes(W * H * 4 - 1), SIZE, 0.5)
    with pytest.raises(MaskError):
        grow_mask(bytes(W * H - 1), SIZE, 1)
    with pytest.raises(MaskError):
        write_mask_png(tmp_path / "never-written.png", bytes(W * H - 1), SIZE)


# ---------------- 落盘:契约那两条 ----------------


def _flat_rgba(path) -> np.ndarray:
    with Image.open(path) as image:
        return np.frombuffer(image.convert("RGBA").tobytes(), dtype=np.uint8).reshape(-1, 4)


def test_落盘的蒙版是灰度_而且没有alpha通道(tmp_path) -> None:
    path = write_mask_png(tmp_path / "mask.png", mask_from_luminance(_gray_split(), SIZE, 0.5), SIZE)
    with Image.open(path) as image:
        #: 图里**根本没有** alpha 通道(模式 L)。带 alpha 的图在插件那条路上读出来是整块不透明。
        assert image.mode == "L"
        assert image.size == SIZE
    pixel = _flat_rgba(path)
    assert (pixel[:, 0] == pixel[:, 1]).all() and (pixel[:, 1] == pixel[:, 2]).all(), "r = g = b"
    assert (pixel[:, 3] == 255).all(), "alpha 一律不透明"
    assert set(pixel[:, 0].tolist()) == {0, 255}


def test_读源图拿到的像素是RGBA_而且尺寸是宽高(tmp_path) -> None:
    path = tmp_path / "source.png"
    Image.new("RGBA", (5, 3), (10, 20, 30, 40)).save(path)
    pixels, size = read_rgba(path)
    assert size == (5, 3) and len(pixels) == 5 * 3 * 4
    assert tuple(pixels[:4]) == (10, 20, 30, 40)


# ---------------- 接口 ----------------


def _png_bytes() -> bytes:
    """64×64:左半边黑、右半边白 —— 蒙版算出来就是一列白边。"""
    image = Image.new("RGB", (64, 64), "black")
    image.paste(Image.new("RGB", (32, 64), "white"), (32, 0))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)
    return buffer.getvalue()


def _import(client, workspace_id: str, filename: str, data: bytes, media_type: str) -> dict:
    made = client.post("/api/assets/import", data={"workspace_id": workspace_id}, files={"file": (filename, data, media_type)})
    assert made.status_code in (200, 201), made.text
    return made.json()


def test_接口产出一张新素材_名字带来源_不打标签() -> None:
    from tests.util import fresh_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    source = _import(client, workspace, "scene.png", _png_bytes(), "image/png")

    made = client.post(f"/api/assets/{source['id']}/mask", json={"source": "luminance", "threshold": 0.5})
    assert made.status_code == 200, made.text
    mask = made.json()
    assert mask["name"] == f"蒙版 · {source['name']}", "名字带来源(ADR 0056 决定 5)"
    assert mask["id"] != source["id"] and mask["kind"] == "image"
    assert mask["derived_from"] == [{"asset_id": source["id"], "op": "mask"}]
    #: 标签是用户自己的词表,不往里塞一个随界面语言变的词。
    assert mask["tags"] == []
    #: 原素材一个字节都不动。
    again = client.get(f"/api/assets/{source['id']}")
    assert again.status_code == 200 and again.json()["name"] == source["name"]
    assert again.json()["derived_from"] == []
    #: 它在素材库里看得见(不是中间产物)。
    listed = client.get(f"/api/assets?workspace_id={workspace}")
    assert mask["id"] in [one["id"] for one in listed.json()["items"]]


def test_产出的蒙版是灰度_而且alpha不透明() -> None:
    """**契约里最容易静默失效的一条。** 带透明通道的图在 `LoadImageMask(channel="red")` 上读出来是
    整块不透明:局部重绘什么都不改,而界面上看不出哪里错了。"""
    from app.core.db import SessionLocal
    from app.db.models import Asset
    from app.media.paths import resolve_key
    from tests.util import fresh_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    source = _import(client, workspace, "scene.png", _png_bytes(), "image/png")
    made = client.post(f"/api/assets/{source['id']}/mask", json={"source": "luminance"})
    assert made.status_code == 200, made.text

    with SessionLocal() as db:
        path = resolve_key(db.get(Asset, made.json()["id"]).file_key)
    with Image.open(path) as image:
        mode, size = image.mode, image.size
    pixel = _flat_rgba(path)
    print(f"产出:{path.name} 模式={mode} 尺寸={size} 通道数={pixel.shape[1]}")
    print(f"r=g=b 的行数:{int(((pixel[:, 0] == pixel[:, 1]) & (pixel[:, 1] == pixel[:, 2])).sum())}/{len(pixel)}")
    print(f"alpha=255 的行数:{int((pixel[:, 3] == 255).sum())}/{len(pixel)}  取到的灰度值={sorted(set(pixel[:, 0].tolist()))}")

    assert mode == "L", f"蒙版是灰度图,不该带 alpha 通道(实际模式 {mode})"
    assert size == (64, 64)
    assert (pixel[:, 0] == pixel[:, 1]).all() and (pixel[:, 1] == pixel[:, 2]).all(), "r = g = b"
    assert (pixel[:, 3] == 255).all(), "alpha 一律不透明"
    #: 左边黑、右边白:要改的地方是右半张。
    assert pixel[32 * 64 + 10, 0] == 0 and pixel[32 * 64 + 40, 0] == 255


def test_形状四步都走通_顺序是阈值反选扩张羽化() -> None:
    from app.core.db import SessionLocal
    from app.db.models import Asset
    from app.media.paths import resolve_key
    from tests.util import fresh_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    source = _import(client, workspace, "scene.png", _png_bytes(), "image/png")

    made = client.post(f"/api/assets/{source['id']}/mask", json={"invert": True, "grow": 2, "feather": 0})
    assert made.status_code == 200, made.text
    with SessionLocal() as db:
        path = resolve_key(db.get(Asset, made.json()["id"]).file_key)
    row = _flat_rgba(path)[32 * 64:(32 + 1) * 64, 0]
    #: 反选之后要改的是**左**半张,再往外扩张 2 像素:白的边界从第 31 格(含)挪到第 33 格。
    assert row[0] == 255 and row[31] == 255 and row[33] == 255
    assert row[34] == 0 and row[63] == 0


def test_源素材不存在时是404() -> None:
    from tests.util import fresh_client

    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    missing = client.post("/api/assets/nope/mask", json={"source": "luminance"})
    assert missing.status_code == 404, missing.text


def test_不是图片的素材报错而不是产出一张废图() -> None:
    from tests.util import fresh_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    audio = _import(client, workspace, "tone.wav", _wav_bytes(), "audio/wav")
    made = client.post(f"/api/assets/{audio['id']}/mask", json={"source": "luminance"})
    assert made.status_code == 400, made.text
    assert "不是图片" in made.json()["detail"]
    #: 一份废图都没落进素材库。
    listed = client.get(f"/api/assets?workspace_id={workspace}")
    assert [one["id"] for one in listed.json()["items"]] == [audio["id"]]


# ---------------- 智能体那条路(和 split_image_grid / reparse_document 同一形状) ----------------


def test_智能体按同一形状接上了_开卡说明白要算什么_批准后交回新素材() -> None:
    import mcp_server
    from app.domain.agent.confirmable.registry import tool_spec
    from tests.util import fresh_client

    assert "create_mask" in mcp_server.CONFIRMATION_TOOLS, "它是一条确认卡工具"
    spec = tool_spec("create_mask")
    assert spec is not None and spec.writes == ("assets",) and spec.permission == "edit"

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    source = _import(client, workspace, "scene.png", _png_bytes(), "image/png")
    payload = {"asset_id": source["id"], "source": "alpha", "threshold": 0.5, "invert": True, "grow": -3, "feather": 1}

    opened = client.post("/api/confirmations", json={"workspace_id": workspace, "tool": "create_mask", "payload": payload})
    assert opened.status_code == 200, opened.text
    card = opened.json()
    assert card["writes"] == ["assets"]
    #: 卡上说的就是待会儿真要算的那几项。断言打在 `headline` 上 —— 那是界面上摆着的那一行
    #: (`summary` 那一栏由领域层按缺省语言落库,给飞书 / MCP 那种只有一行字的出口读)。
    assert card["headline"] == f"按透明通道从「{source['name']}」算一张新蒙版(阈值 50%;反选、收缩 3 像素、羽化 1 像素),原图不变"
    english = client.post(
        "/api/confirmations", headers={"Accept-Language": "en-US"},
        json={"workspace_id": workspace, "tool": "create_mask", "payload": payload},
    ).json()["headline"]
    assert english == (
        f"Make a new mask from “{source['name']}” by alpha (threshold 50%; inverted, shrunk by 3 px, feathered by 1 px); "
        "the original is unchanged"
    ), english

    approved = client.post(f"/api/confirmations/{card['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "executed", approved.text
    result = approved.json()["result"]
    assert result["source_asset_id"] == source["id"]
    made = client.get(f"/api/assets/{result['asset_id']}").json()
    assert made["name"] == f"蒙版 · {source['name']}" and made["derived_from"] == [{"asset_id": source["id"], "op": "mask"}]


def test_智能体那张卡对不是图片的素材根本不开() -> None:
    """"注定执行不了的卡没有让用户去点的道理"(见 confirmable/registry 的 validate)。"""
    from tests.util import fresh_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    audio = _import(client, workspace, "tone.wav", _wav_bytes(), "audio/wav")
    refused = client.post(
        "/api/confirmations",
        json={"workspace_id": workspace, "tool": "create_mask", "payload": {"asset_id": audio["id"], "source": "luminance"}},
    )
    assert refused.status_code == 422, refused.text
    assert "只有图片素材" in refused.json()["detail"]


# ---------------- 在浏览器里画出来的蒙版:导入这条路上带着出处 ----------------


def _import_mask(client, workspace_id: str, data: bytes, derived_from: str | None = None, name: str = "mask.png"):
    """`POST /api/assets/import` —— 浏览器里画完蒙版存下来的那条路(见 MaskEditor 的 importAsset)。

    `derived_from` 是**可选**的表单栏:不给就是一次普通导入(挑素材、槽位上传、桌面端导入都在用这条路)。
    """
    form: dict[str, str] = {"workspace_id": workspace_id}
    if derived_from is not None:
        form["derived_from"] = derived_from
    return client.post("/api/assets/import", data=form, files={"file": (name, data, "image/png")})


def test_导入时说了出处_存下来的素材就记着是哪张图画的() -> None:
    """画出来的蒙版此前是**没有出处**的:它在导入这条路上进来,而这条路不收出处 ⇒ 素材详情「来自」
    永远空着、AI 标识也跟着漏。现在调用方说得出源素材,存下来的素材就得记着它。"""
    from tests.util import fresh_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    source = _import(client, workspace, "scene.png", _png_bytes(), "image/png")

    made = _import_mask(client, workspace, _png_bytes(), json.dumps([{"asset_id": source["id"], "op": "mask"}]))
    assert made.status_code == 200, made.text
    mask = made.json()
    assert mask["derived_from"] == [{"asset_id": source["id"], "op": "mask"}]
    #: `derived` 是后端算的那一格:素材详情据它决定「来自」那一行出不出现(见 api/schemas/media 的 AssetOut)。
    assert mask["derived"] is True

    #: 「来自」那条链读得到出处本身(不是只存了一个 id)。
    lineage = client.get(f"/api/assets/{mask['id']}/lineage")
    assert lineage.status_code == 200, lineage.text
    parents = lineage.json()["parents"]
    assert [(one["asset_id"], one["op"]) for one in parents] == [(source["id"], "mask")]
    assert parents[0]["name"] == source["name"] and parents[0]["kind"] == "image"


def test_出处里认不得的op_响亮拒绝而不是静默丢掉() -> None:
    """写路径严格:`op` 不在 lineage.OPS 里就拒绝这次导入。

    静默丢掉的话,一份「从某张图画的蒙版」会悄悄登记成一张没有出处的普通素材 —— 界面看不出哪里错了,
    正是这条来源链要修的病。**而且一个字节都不落盘**(先过闸、再看出处、最后才读字节)。
    """
    from tests.util import fresh_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    source = _import(client, workspace, "scene.png", _png_bytes(), "image/png")

    bad = [
        json.dumps([{"asset_id": source["id"], "op": "画个圈"}]),
        #: 形状也不放行:不是列表、不是一项一项的、缺 asset_id(见 lineage.parse_derived_from)。
        json.dumps({"asset_id": source["id"], "op": "mask"}),
        json.dumps([source["id"]]),
        json.dumps([{"op": "mask"}]),
        "{not json",
    ]
    for payload in bad:
        refused = _import_mask(client, workspace, _png_bytes(), payload)
        assert refused.status_code == 422, f"{payload} → {refused.status_code}: {refused.text}"
        assert refused.json()["detail"]
    #: 认不得的那个 op 要点名说出来,不能只说一句"请求不对"。
    named = _import_mask(client, workspace, _png_bytes(), json.dumps([{"asset_id": source["id"], "op": "画个圈"}]))
    assert "画个圈" in named.json()["detail"], named.text

    listed = client.get(f"/api/assets?workspace_id={workspace}")
    assert [one["id"] for one in listed.json()["items"]] == [source["id"]], "拒掉的导入一份都不该落进素材库"


def test_不带出处时_和加这个字段之前逐字相同() -> None:
    """这条路别处也在用(挑素材、生成面板的槽位、桌面端导入):不给 `derived_from`(或者给一个空串)
    入库的那份素材与加这个字段之前一模一样 —— 没有出处、不含 AI、来源还是「导入的」。"""
    from tests.util import fresh_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    for derived_from in (None, ""):
        made = _import_mask(client, workspace, _png_bytes(), derived_from)
        assert made.status_code == 200, made.text
        bare = made.json()
        assert bare["derived_from"] == [], f"derived_from={derived_from!r}"
        assert bare["derived"] is False
        assert bare["ai_generated"] is False
        assert bare["source"] == "imported"
        assert client.get(f"/api/assets/{bare['id']}/lineage").json()["parents"] == []


def test_从AI生成的图画的蒙版_被标含AI(tmp_path) -> None:
    """**AI 继承这条线**:出处里有一份含 AI 的,产出就含 AI(`importer` 的 `ai_generated or inherits_ai(...)`)。

    标识办法认的正是这一步加工:一张 AI 生成图上画出来的蒙版,进成片时它自己就得带着标识 ——
    此前这条路没有出处,继承无从谈起(`inherits_ai` 拿到的是空列表)。
    """
    from app.core.db import SessionLocal
    from app.domain.assets import register_file_asset
    from tests.util import fresh_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    generated = tmp_path / "ai.png"
    generated.write_bytes(_png_bytes())
    with SessionLocal() as db:
        #: 生成任务交回的一份素材(见 generation.runner 的登记那一步)。
        ai_source = register_file_asset(
            db, workspace_id=workspace, project_id=None, source_path=generated, name="AI 图.png",
            source="generated", ai_generated=True,
        ).id

    made = _import_mask(client, workspace, _png_bytes(), json.dumps([{"asset_id": ai_source, "op": "mask"}]))
    assert made.status_code == 200, made.text
    assert made.json()["ai_generated"] is True, "从 AI 生成图画的蒙版没被标含 AI"

    #: 反面照:从一份普通导入的图画的蒙版**不**含 AI —— 否则上面那条可能只是恒真。
    plain_source = _import(client, workspace, "scene.png", _png_bytes(), "image/png")
    plain = _import_mask(client, workspace, _png_bytes(), json.dumps([{"asset_id": plain_source["id"], "op": "mask"}]))
    assert plain.status_code == 200, plain.text
    assert plain.json()["ai_generated"] is False
    assert plain.json()["derived_from"] == [{"asset_id": plain_source["id"], "op": "mask"}]
