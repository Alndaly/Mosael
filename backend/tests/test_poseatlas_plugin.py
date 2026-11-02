"""PoseAtlas 插件(ADR 0091 第 5 步):把原站的姿势 / 服装图鉴接成参考库。直接 import 入口脚本验,不联网。

钉的是用户看得到的后果:机位落到资产库的角度上;成人内容没打开时**根本不出现**;中英日名称、编号、分类都搜得到;
每一条都带出处和许可;取用时下的是原站那一张、落在这次调用的暂存目录;插件目录里一张图都不带。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from mosael_formats.plugin_manifest import REFERENCE_LIBRARY, parse

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "poseatlas"

POSES = {
    "series": [
        {"key": "full_std", "short": {"zh": "标准全身", "en": "Standard", "ja": "標準系"}},
        {"key": "full_sexy", "short": {"zh": "性感全身", "en": "Sexy", "ja": "セクシー系"}},
        {"key": "upper", "short": {"zh": "上半身", "en": "Upper body", "ja": "上半身"}},
        {"key": "duo", "short": {"zh": "双人", "en": "Couples", "ja": "ペア"}},
    ],
    "categories": [
        {"key": "坐姿", "names": {"zh": "坐姿", "en": "Sitting", "ja": "座り"}},
        {"key": "站姿", "names": {"zh": "站姿", "en": "Standing", "ja": "立ち"}},
        {"key": "可爱系", "names": {"zh": "可爱系", "en": "Cute", "ja": "かわいい系"}},
        {"key": "性感・大胆系", "names": {"zh": "性感・大胆系", "en": "Bold", "ja": "セクシー"}},
    ],
    "poses": [
        {"id": "full_single_P001", "series": "full_std", "category": "坐姿", "no": "P001",
         "names": {"zh": "后仰坐・单膝立起", "en": "Reclining sit, one knee up", "ja": "仰け反り座り・片膝立て"},
         "variants": [
             {"angle": "high", "thumb": "thumbs/a_high.jpg", "full": "img/a_high.png"},
             {"angle": "front", "thumb": "thumbs/a_front.jpg", "full": "img/a_front.png"},
             {"angle": "diagonal", "thumb": "thumbs/a_diag.jpg", "full": "img/a_diag.png"},
             {"angle": "low", "thumb": "thumbs/a_low.jpg", "full": "img/a_low.png"},
             {"angle": "side", "thumb": "thumbs/a_side.jpg", "full": "img/a_side.png"},
         ]},
        {"id": "full_single_P002", "series": "full_std", "category": "站姿", "no": "P002",
         "names": {"zh": "叉腰站", "en": "Hands on hips", "ja": "腰に手"},
         "variants": [{"angle": "front", "thumb": "thumbs/b_front.jpg", "full": "img/b_front.png"}]},
        {"id": "upper_P001", "series": "upper", "category": "可爱系", "no": "P001",
         "names": {"zh": "比心", "en": "Finger heart", "ja": "指ハート"},
         "variants": [{"angle": "front", "thumb": "thumbs/c_front.jpg", "full": "img/c_front.png"}]},
        {"id": "upper_P050", "series": "upper", "category": "性感・大胆系", "no": "P050",
         "names": {"zh": "大胆", "en": "Bold", "ja": "大胆"},
         "variants": [{"angle": "front", "thumb": "thumbs/d_front.jpg", "full": "img/d_front.png"}]},
        {"id": "full_sexy_P001", "series": "full_sexy", "category": "站姿", "no": "P001",
         "names": {"zh": "S形站姿", "en": "S-curve stance", "ja": "S字立ち"},
         "variants": [{"angle": "front", "thumb": "thumbs/e_front.jpg", "full": "img/e_front.png"}]},
        {"id": "duo_P001", "series": "duo", "category": "站姿", "no": "P001",
         "names": {"zh": "双人", "en": "Duo", "ja": "ペア"},
         "variants": [{"angle": "front", "thumb": "thumbs/f_front.jpg", "full": "img/f_front.png"}]},
    ],
}
COSTUMES = [
    {"id": "SPR-0001", "cat": "spring", "group": "top", "color": "ivory", "main": "knit",
     "tags": ["ivory", "knit", "denim"], "thumb": "costume/thumbs/SPR-0001.webp", "image": "costume/img/SPR-0001.webp"},
    {"id": "LIN-0001", "cat": "lingerie", "group": "set", "color": "black", "main": "lace",
     "tags": ["black", "lace"], "thumb": "costume/thumbs/LIN-0001.webp", "image": "costume/img/LIN-0001.webp"},
]

TAGS_JS = """export const TAG_NAMES = {
  ivory: { zh: '象牙白', en: 'Ivory', ja: 'アイボリー' },
  knit: { zh: '针织', en: 'Knit', ja: 'ニット' },
  denim: { zh: '牛仔', en: 'Denim', ja: 'デニム' },
};
"""


@pytest.fixture
def plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("poseatlas_main", PLUGIN / "tools" / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    downloaded: list[str] = []

    def fake_download(url: str) -> bytes:
        downloaded.append(url)
        if url.endswith("data/poses.json"):
            return json.dumps(POSES).encode()
        if url.endswith("data/costumes.json"):
            return json.dumps(COSTUMES).encode()
        if url.endswith("costume-tags.js"):
            return TAGS_JS.encode()
        return b"\x89PNG fake image bytes"

    monkeypatch.setattr(module, "_download", fake_download)
    monkeypatch.setenv("MOSAEL_PLUGIN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MOSAEL_PLUGIN_OUTPUT_DIR", str(tmp_path / "out"))
    (tmp_path / "out").mkdir()
    monkeypatch.delenv("POSEATLAS_ADULT", raising=False)
    module.downloaded = downloaded
    return module


def _call(plugin, op: str, locale: str = "zh", **payload):
    return plugin.poseatlas_library({"op": op, **payload}, locale)


def test_清单认领参考库_插件目录里一张图都不带() -> None:
    manifest = parse(json.loads((PLUGIN / "mosael.plugin.json").read_text(encoding="utf-8")), "poseatlas")
    assert REFERENCE_LIBRARY in manifest.provides
    images = [p for p in PLUGIN.rglob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}]
    assert images == [], "只引用原站的图,不分发"


def test_机位落到资产库的角度上_正面排第一(plugin) -> None:
    item = _call(plugin, "item", item_id="full_single_P001", collection="poses")["item"]
    assert [view["role"] for view in item["views"]] == ["front", "three_quarter", "side", "high_angle", "low_angle"]
    assert item["views"][0]["original"] == plugin.BASE + "img/a_front.png"
    assert item["thumbnail"] == plugin.BASE + "thumbs/a_front.jpg"
    assert item["kind"] == "pose" and item["nsfw"] is False


def test_成人内容没打开时根本不出现_打开后标NSFW(plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    ids = lambda: {one["id"] for one in _call(plugin, "search", collection="poses", limit=50)["items"]}  # noqa: E731
    assert ids() == {"full_single_P001", "full_single_P002", "upper_P001"}
    costumes = {one["id"] for one in _call(plugin, "search", collection="costumes")["items"]}
    assert costumes == {"SPR-0001"}
    with pytest.raises(plugin.ToolError):
        _call(plugin, "item", item_id="duo_P001")

    monkeypatch.setenv("POSEATLAS_ADULT", "true")
    found = {one["id"]: one["nsfw"] for one in _call(plugin, "search", collection="poses", limit=50)["items"]}
    assert found["duo_P001"] is True and found["full_sexy_P001"] is True and found["upper_P050"] is True
    assert found["full_single_P001"] is False


def test_中英日名称_编号_分类都搜得到_筛选与翻页(plugin) -> None:
    for query in ("单膝", "knee", "片膝", "P001", "坐姿", "sitting"):
        hits = [one["id"] for one in _call(plugin, "search", collection="poses", q=query)["items"]]
        assert "full_single_P001" in hits, query
    standing = _call(plugin, "search", collection="poses", filters={"category": "站姿"})["items"]
    assert [one["id"] for one in standing] == ["full_single_P002"]

    first = _call(plugin, "search", collection="poses", limit=2)
    assert len(first["items"]) == 2 and first["next_cursor"] == "2"
    rest = _call(plugin, "search", collection="poses", limit=2, cursor=first["next_cursor"])
    assert len(rest["items"]) == 1 and rest["next_cursor"] == ""


def test_每一条都带出处与许可_按读的人的语言(plugin) -> None:
    zh = _call(plugin, "item", item_id="SPR-0001", collection="costumes")["item"]
    en = _call(plugin, "item", "en", item_id="SPR-0001", collection="costumes")["item"]
    assert "giaaibusi" in zh["provenance"]["author"] and zh["provenance"]["url"].startswith(plugin.BASE)
    assert "禁止再分发" in zh["provenance"]["license"]
    assert "redistributing" in en["provenance"]["license"]
    assert zh["views"] == [{"role": "front", "thumbnail": plugin.BASE + "costume/thumbs/SPR-0001.webp",
                            "original": plugin.BASE + "costume/img/SPR-0001.webp"}]


def test_服装名字和标签按读的人的语言_词表取不到时照英文(plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    zh = _call(plugin, "item", item_id="SPR-0001", collection="costumes")["item"]
    en = _call(plugin, "item", "en", item_id="SPR-0001", collection="costumes")["item"]
    assert zh["name"]["zh"] == "春 · 象牙白 针织 · SPR-0001"
    assert en["name"]["en"] == "Spring · Ivory Knit · SPR-0001"
    assert zh["tags"] == ["象牙白", "针织", "牛仔"] and en["tags"] == ["Ivory", "Knit", "Denim"]
    assert "SPR-0001" in [one["id"] for one in _call(plugin, "search", collection="costumes", q="针织")["items"]]

    for cached in Path(plugin._cache_dir()).glob("*"):
        cached.unlink()
    real = plugin._download
    monkeypatch.setattr(plugin, "_download", lambda url: b"not a dictionary" if url.endswith(".js") else real(url))
    fallback = _call(plugin, "item", item_id="SPR-0001", collection="costumes")["item"]
    assert fallback["name"]["zh"] == "春 · ivory knit · SPR-0001"


def test_图集目录给出条目数与筛选维度(plugin) -> None:
    listed = {one["id"]: one for one in _call(plugin, "collections")["collections"]}
    assert listed["poses"]["kind"] == "pose" and listed["poses"]["count"] == 3
    assert listed["costumes"]["kind"] == "costume" and listed["costumes"]["count"] == 1
    series = next(one for one in listed["poses"]["filters"] if one["key"] == "series")
    assert {value["value"] for value in series["values"]} == {"full_std", "upper"}, "没打开成人内容时不列成人系列"


def test_取用下的是原站那一张_落在这次调用的暂存目录(plugin, tmp_path: Path) -> None:
    output = _call(plugin, "fetch", item_id="full_single_P001", collection="poses")
    assert output["artifact"] == {"path": "full_single_P001_front.png"}
    assert (tmp_path / "out" / "full_single_P001_front.png").read_bytes().startswith(b"\x89PNG")
    assert plugin.downloaded[-1] == plugin.BASE + "img/a_front.png"


def test_取用按视角取_没有的视角报错(plugin, tmp_path: Path) -> None:
    """「存为资产」宿主每个视角各问一次(`role`),「用作素材」问用户选中的那一个。"""
    views = _call(plugin, "item", item_id="full_single_P001", collection="poses")["item"]["views"]
    other = views[1]["role"]
    output = _call(plugin, "fetch", item_id="full_single_P001", collection="poses", role=other)
    assert output["artifact"] == {"path": f"full_single_P001_{other}.png"}
    assert plugin.downloaded[-1] == views[1]["original"]
    with pytest.raises(plugin.ToolError):
        _call(plugin, "fetch", item_id="full_single_P001", collection="poses", role="no_such_view")


def test_索引缓存一天_原站连不上时用旧的_一份都没有才报错(plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    _call(plugin, "collections")
    fetched = len(plugin.downloaded)
    _call(plugin, "collections")
    assert len(plugin.downloaded) == fetched, "缓存新鲜时不再去原站"

    def offline(url: str) -> bytes:
        raise plugin.urllib.error.URLError("offline")

    monkeypatch.setattr(plugin, "_download", offline)
    monkeypatch.setattr(plugin, "CACHE_SECONDS", -1)
    assert _call(plugin, "collections")["collections"], "过期但连不上:继续用旧的"

    for cached in (Path(plugin._cache_dir())).glob("*.json"):
        cached.unlink()
    with pytest.raises(plugin.ToolError):
        _call(plugin, "collections")


def test_不认识的操作说清楚(plugin) -> None:
    with pytest.raises(plugin.ToolError):
        _call(plugin, "delete_everything")
