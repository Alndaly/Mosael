"""PoseAtlas —— 把 RuiC-PoseAtlas 的姿势图鉴、服装图鉴接成 Mosael 的参考库(ADR 0091 §7)。

协议:stdin 读一个 JSON 请求 {"tool": name, "input": {...}, "locale": "zh"},stdout 写
{"ok": true, "output": {...}} 或 {"ok": false, "error": "..."}。纯标准库。

认领 `reference_library`,按 `input.op` 回答:

- `collections` —— 两本图集(姿势、服装)、条目数、筛选维度;
- `search` —— 关键词(中英日名称、编号、分类、标签都认)+ 筛选 + 游标翻页;
- `item` —— 一个条目:名称、标签、各机位的缩略图与原图地址、NSFW、出处;
- `fetch` —— 把这个条目的第一张原图下到 `MOSAEL_PLUGIN_OUTPUT_DIR`,交回 `artifact`。

**引用,不分发**:图片永远从原站取,插件不带一张图,只在 `MOSAEL_PLUGIN_DATA_DIR` 里缓存索引 JSON;
每个条目都带出处(原作者、原站、许可说明),宿主取用时把它写进素材。

**成人内容默认不出现**:原站「性感」「双人」两个系列、上半身里的两类,以及服装的「内衣」「性感」两类在连接配置
`POSEATLAS_ADULT` 打开前根本不返回;打开后照样标 `nsfw`,由宿主按预览图设置模糊或隐藏。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://hruiccc.github.io/RuiC-PoseAtlas/"
SOURCES = {
    "poses": "data/poses.json",
    "costumes": "data/costumes.json",
    #: 服装单品的三语词表(`TAG_NAMES = { knit: { zh: '针织', en: 'Knit', ja: 'ニット' }, … }`)。原数据的颜色、
    #: 单品只有英文键,中文界面靠它把名字和标签翻过来;取不到就照英文显示,不算失败。
    "costume_tags": "assets/js/costume-tags.js",
}
_TAG_ENTRY = re.compile(r"([\w-]+):\s*\{\s*zh:\s*'([^']*)',\s*en:\s*'([^']*)',\s*ja:\s*'([^']*)'\s*\}")
#: 索引一天刷新一次;刷新失败用旧的,一份都没有才报错。
CACHE_SECONDS = 24 * 3600
TIMEOUT = 30
USER_AGENT = "Mosael-PoseAtlas/0.1 (+https://mosael.com)"

LICENSE = {
    "zh": "图片为 AI 生成的虚构参考素材,版权归原作者;仅供参考与创作使用,禁止再分发、转载或转售图片本身。",
    "en": "AI-generated fictional reference images; copyright belongs to the original author. For reference and "
          "creative use only — redistributing, reposting or reselling the images themselves is prohibited.",
}
POSE_AUTHOR = "ギア (@giaaibusi) · POSE-DB-01;整理:RuiC-PoseAtlas"
COSTUME_AUTHOR = "ギア (@giaaibusi) · COSTUME-DB-01;整理:RuiC-PoseAtlas"

#: 原站的机位 → 资产库的角度(entities/catalog.ROLES_BY_KIND["pose"])。
ANGLE_ROLES = {"front": "front", "diagonal": "three_quarter", "side": "side", "high": "high_angle", "low": "low_angle"}
#: 姿势条目的参考图按这个先后排:宿主取用时拿第一张。
ANGLE_ORDER = ("front", "diagonal", "side", "high", "low")

#: 成人内容。系列整个算的:性感全身、双人;上半身里只有这两类。
ADULT_SERIES = frozenset({"full_sexy", "duo"})
ADULT_CATEGORIES = frozenset({"挤胸・强调事业线系", "性感・大胆系"})
ADULT_COSTUME_CATS = frozenset({"lingerie", "sexy"})

COSTUME_CATS = {
    "spring": ("春", "Spring"), "summer": ("夏", "Summer"), "autumn": ("秋", "Autumn"), "winter": ("冬", "Winter"),
    "lingerie": ("内衣", "Lingerie"), "sexy": ("性感", "Sexy"), "swimwear": ("泳装", "Swimwear"), "party": ("派对", "Party"),
}


class ToolError(ValueError):
    """说得出口的失败,原样交回。"""


def _zh(locale: str) -> bool:
    return locale.replace("_", "-").split("-")[0].lower() == "zh"


def _line(locale: str, zh: str, en: str) -> str:
    return zh if _zh(locale) else en


def _adult_allowed() -> bool:
    return os.environ.get("POSEATLAS_ADULT", "").strip().lower() in {"1", "true", "yes", "on"}


# ── 索引 ──────────────────────────────────────────────────────────────────────


def _cache_dir() -> Path:
    root = Path(os.environ.get("MOSAEL_PLUGIN_DATA_DIR") or Path.home() / ".cache" / "mosael-poseatlas")
    folder = root / "index"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 — 固定的 https 原站
        return response.read()


def _cached(name: str, locale: str, check: Any) -> str:
    """一份原站文件的文字:缓存新鲜就用缓存,否则去原站取(`check` 先验过是完整的一份才换掉旧缓存);
    取不到时用旧缓存,一份都没有才报错。"""
    cached = _cache_dir() / Path(SOURCES[name]).name
    fresh = cached.is_file() and time.time() - cached.stat().st_mtime < CACHE_SECONDS
    if not fresh:
        try:
            body = _download(BASE + SOURCES[name])
            check(body.decode("utf-8"))
            staged = cached.with_suffix(".tmp")
            staged.write_bytes(body)
            os.replace(staged, cached)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            if not cached.is_file():
                raise ToolError(_line(locale, f"连不上 PoseAtlas 原站,取不到索引:{exc}",
                                      f"Couldn't reach the PoseAtlas site to load its index: {exc}")) from exc
    return cached.read_text(encoding="utf-8")


def _index(name: str, locale: str) -> Any:
    """一份 JSON 索引(`poses` / `costumes`)。"""
    return json.loads(_cached(name, locale, json.loads))


def _must_have_tags(text: str) -> None:
    if not _TAG_ENTRY.search(text):
        raise ValueError("costume tag dictionary has no entries")


def _tag_names(locale: str) -> dict[str, dict[str, str]]:
    """单品键 → 三语名称。词表取不到不影响浏览:名字照英文键显示。"""
    try:
        text = _cached("costume_tags", locale, _must_have_tags)
    except ToolError:
        return {}
    return {key: {"zh": zh, "en": en, "ja": ja} for key, zh, en, ja in _TAG_ENTRY.findall(text)}


def _names(value: Any) -> dict[str, str]:
    return {lang: str(value.get(lang) or "") for lang in ("zh", "en", "ja")} if isinstance(value, dict) else {}


def _pose_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    series = {one["key"]: _names(one.get("short") or one.get("names")) for one in data.get("series") or []}
    categories = {one["key"]: _names(one.get("names")) for one in data.get("categories") or []}
    items: list[dict[str, Any]] = []
    for record in data.get("poses") or []:
        variants = {one.get("angle"): one for one in record.get("variants") or []}
        views = [
            {"role": ANGLE_ROLES[angle], "thumbnail": BASE + variants[angle]["thumb"], "original": BASE + variants[angle]["full"]}
            for angle in ANGLE_ORDER if angle in variants and variants[angle].get("thumb")
        ]
        series_key, category_key = record.get("series", ""), record.get("category", "")
        category = categories.get(category_key) or {"zh": category_key, "en": category_key, "ja": category_key}
        names = _names(record.get("names"))
        items.append({
            "id": record["id"],
            "collection": "poses",
            "kind": "pose",
            "no": record.get("no", ""),
            "name": {"zh": names.get("zh") or record["id"], "en": names.get("en") or record["id"]},
            "search": " ".join([record["id"], record.get("no", ""), *names.values(), *category.values(),
                                *series.get(series_key, {}).values()]).casefold(),
            "facets": {"series": series_key, "category": category_key},
            "tags": [value for value in (category.get("zh"), category.get("en"), series.get(series_key, {}).get("zh")) if value],
            "views": views,
            "nsfw": series_key in ADULT_SERIES or category_key in ADULT_CATEGORIES,
            "provenance": {"author": POSE_AUTHOR, "url": BASE},
        })
    return items


def _costume_items(data: Any, names: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    records = data.get("costumes") if isinstance(data, dict) else data
    say = lambda key, lang: names.get(key, {}).get(lang) or key  # noqa: E731 — 词表里没有的照英文键
    items: list[dict[str, Any]] = []
    for record in records or []:
        cat = record.get("cat", "")
        cat_zh, cat_en = COSTUME_CATS.get(cat, (cat, cat))
        main, color = record.get("main", ""), record.get("color", "")
        keys = [str(tag) for tag in record.get("tags") or []]
        items.append({
            "id": record["id"],
            "collection": "costumes",
            "kind": "costume",
            "no": record["id"],
            "name": {"zh": f"{cat_zh} · {say(color, 'zh')} {say(main, 'zh')} · {record['id']}",
                     "en": f"{cat_en} · {say(color, 'en')} {say(main, 'en')} · {record['id']}"},
            "search": " ".join([record["id"], cat, cat_zh, cat_en, *(say(key, lang) for key in [main, color, *keys]
                                                                   for lang in ("zh", "en", "ja")), *keys]).casefold(),
            "facets": {"cat": cat, "color": color},
            "tags": [say(key, "zh") for key in keys],
            "tags_en": [say(key, "en") for key in keys],
            "views": [{"role": "front", "thumbnail": BASE + record["thumb"], "original": BASE + record["image"]}]
            if record.get("thumb") else [],
            "nsfw": cat in ADULT_COSTUME_CATS,
            "provenance": {"author": COSTUME_AUTHOR, "url": BASE + "costume.html"},
        })
    return items


def _items(collection: str, locale: str) -> list[dict[str, Any]]:
    """一本图集的全部条目;成人内容没打开时整条剔掉,不只是打标记。"""
    if collection == "poses":
        items = _pose_items(_index("poses", locale))
    elif collection == "costumes":
        items = _costume_items(_index("costumes", locale), _tag_names(locale))
    else:
        raise ToolError(_line(locale, f"没有这本图集:{collection}", f"No such collection: {collection}"))
    return items if _adult_allowed() else [one for one in items if not one["nsfw"]]


def _public(item: dict[str, Any], locale: str) -> dict[str, Any]:
    """交给宿主的那一份(去掉只给自己检索用的字段,补上许可说明)。"""
    out = {key: value for key, value in item.items() if key not in {"search", "facets", "no", "tags_en"}}
    if not _zh(locale) and "tags_en" in item:
        out["tags"] = item["tags_en"]
    out["thumbnail"] = item["views"][0]["thumbnail"] if item["views"] else ""
    out["provenance"] = {**item["provenance"], "license": LICENSE["zh" if _zh(locale) else "en"]}
    return out


# ── op ───────────────────────────────────────────────────────────────────────


def _values(items: list[dict[str, Any]], key: str, labels: dict[str, str]) -> list[dict[str, str]]:
    seen: list[str] = []
    for item in items:
        value = item["facets"].get(key, "")
        if value and value not in seen:
            seen.append(value)
    return [{"value": value, "label": labels.get(value, value)} for value in seen]


def collections(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    zh = _zh(locale)
    poses = _items("poses", locale)
    data = _index("poses", locale)
    series_labels = {one["key"]: _names(one.get("short") or one.get("names")).get("zh" if zh else "en", one["key"])
                     for one in data.get("series") or []}
    category_labels = {one["key"]: _names(one.get("names")).get("zh" if zh else "en", one["key"])
                       for one in data.get("categories") or []}
    costumes = _items("costumes", locale)
    cat_labels = {key: (pair[0] if zh else pair[1]) for key, pair in COSTUME_CATS.items()}
    color_labels = {key: value["zh" if zh else "en"] for key, value in _tag_names(locale).items()}
    return {"collections": [
        {"id": "poses", "kind": "pose", "name": {"zh": "姿势图鉴", "en": "Pose atlas"}, "count": len(poses),
         "filters": [
             {"key": "series", "label": _line(locale, "系列", "Series"), "values": _values(poses, "series", series_labels)},
             {"key": "category", "label": _line(locale, "分类", "Category"), "values": _values(poses, "category", category_labels)},
         ]},
        {"id": "costumes", "kind": "costume", "name": {"zh": "服装图鉴", "en": "Costume atlas"}, "count": len(costumes),
         "filters": [
             {"key": "cat", "label": _line(locale, "分类", "Category"), "values": _values(costumes, "cat", cat_labels)},
             {"key": "color", "label": _line(locale, "主色", "Main color"), "values": _values(costumes, "color", color_labels)},
         ]},
    ]}


def search(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    collection = str(payload.get("collection") or "poses")
    query = str(payload.get("q") or "").strip().casefold()
    filters = {str(key): str(value) for key, value in (payload.get("filters") or {}).items() if value not in (None, "")}
    try:
        offset = max(0, int(payload.get("cursor") or 0))
    except ValueError:
        offset = 0
    limit = max(1, min(int(payload.get("limit") or 40), 200))
    words = query.split()
    found = [
        item for item in _items(collection, locale)
        if all(word in item["search"] for word in words)
        and all(item["facets"].get(key) == value for key, value in filters.items())
    ]
    page = found[offset:offset + limit]
    following = offset + limit
    return {"items": [_public(item, locale) for item in page],
            "next_cursor": str(following) if following < len(found) else ""}


def _find(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    item_id = str(payload.get("item_id") or "").strip()
    collections_to_try = [str(payload["collection"])] if payload.get("collection") else ["poses", "costumes"]
    for collection in collections_to_try:
        for item in _items(collection, locale):
            if item["id"] == item_id:
                return item
    raise ToolError(_line(locale, f"图鉴里没有这一条(或它属于没打开的成人内容):{item_id}",
                          f"No such entry (or it is adult content that isn't enabled): {item_id}"))


def item(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    return {"item": _public(_find(payload, locale), locale)}


def fetch(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    """把条目里点名的那个视角(`role`,空 = 第一张)的原图下到这次调用的暂存目录。宿主收走后登记成素材、写上出处。
    「存为资产」时宿主每个视角各问一次,按视角挂成参考图。"""
    found = _find(payload, locale)
    if not found["views"]:
        raise ToolError(_line(locale, "这一条没有图", "This entry has no image"))
    role = str(payload.get("role") or "").strip()
    view = next((one for one in found["views"] if one["role"] == role), None) if role else found["views"][0]
    if view is None:
        raise ToolError(_line(locale, f"这一条没有这个视角:{role}", f"This entry has no {role} view"))
    out_dir = Path(os.environ.get("MOSAEL_PLUGIN_OUTPUT_DIR") or ".")
    suffix = Path(view["original"]).suffix or ".png"
    target = out_dir / f"{found['id']}_{view['role']}{suffix}"
    try:
        target.write_bytes(_download(view["original"]))
    except (urllib.error.URLError, OSError) as exc:
        raise ToolError(_line(locale, f"下载原图失败:{exc}", f"Couldn't download the original image: {exc}")) from exc
    return {"artifact": {"path": target.name}, "summary": _line(locale, f"已取 {found['id']}", f"Fetched {found['id']}")}


OPS = {"collections": collections, "search": search, "item": item, "fetch": fetch}


def poseatlas_library(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    op = str(payload.get("op") or "")
    handler = OPS.get(op)
    if handler is None:
        raise ToolError(_line(locale, f"不认识的操作:{op}", f"Unknown op: {op}"))
    return handler(payload, locale)


TOOLS = {"poseatlas_library": poseatlas_library}


def main() -> None:
    request = json.loads(sys.stdin.read() or "{}")
    payload = request.get("input") or {}
    locale = str(request.get("locale") or payload.get("locale") or os.environ.get("MOSAEL_LOCALE") or "zh")
    handler = TOOLS.get(str(request.get("tool") or ""))
    try:
        if handler is None:
            raise ToolError(_line(locale, f"没有这个工具:{request.get('tool')}", f"No such tool: {request.get('tool')}"))
        print(json.dumps({"ok": True, "output": handler(payload, locale)}, ensure_ascii=False))
    except ToolError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
