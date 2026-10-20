#!/usr/bin/env python3
"""导出官方内容 bundle —— 部署时喂给 `cloud.cli seed-official`。

**官方内容 = 官方账号发布的分享**:插件 / 工作流本身也是分享,所以这里不另造一套数据,
只把仓库里已有的两份真源折成 cloud 认的 bundle 形状:

- 插件:`plugins/{bundled,examples}/<目录名>/mosael.plugin.json`,
  `slug` 就是目录名(官网 `/plugins/<slug>` 的 URL 段与 app 内市场的索引键都是它);
  标题 / 简介取 manifest 的 `name` / `summary`。manifest 里没有的语言**不补** ——
  没有英文就只导出 `zh-CN`,不拿中文冒充英文。
- 工作流:`website/public/workflows/catalog.json` 和它 `download` 指向的
  `.mosael-workflow.json`;`slug` 用官网静态条目的 slug(下划线折成连字符),
  这样官网能把云端分享按 slug 对回静态卡片。

**payload 是内容本体,不是整个目录**:

- 插件放 manifest 原文。整个插件目录会带上 `dist/`、模型清单之类的大文件
  (ComfyUI 目录 4.7MB),而 cloud 的 payload 上限是 2MB;目录里真正描述"这是什么"的
  就是 manifest。
- 工作流放那份 `.mosael-workflow.json` 的 JSON 内容(最大 73KB),不重新拼节点 / 简介。

**一份 payload 只能选一种语言**:cloud 的 bundle 每条只有一份 `payload`,而同一条内容的
`zh-CN` / `en-US` 是两行。工作流的 `.zh` / `.en` 文件里节点名是各自语言的,不能同时塞进
一份 payload,所以用 `--payload-locale` 选一份(缺省 `en`,和官网默认语言一致);官网静态
页面仍然按语言展示自己的标题 / 简介,详情页的下载也不经过这里。

**稳定 / 幂等**:条目按 slug 排序,`json.dumps(..., sort_keys=True)` 固定所有键的顺序,
末尾固定一个换行。同一份仓库导出两次逐字节一致 —— 发布时重跑不会产生无意义的 diff。

用法(仓库根):

    python3 scripts/export_official_bundle.py
    # 产出 deploy/official-bundle.json

    cd cloud
    uv run python -m cloud.cli seed-official --bundle ../deploy/official-bundle.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("deploy") / "official-bundle.json"

#: 站点的两种语言 → manifest / catalog 里的键。顺序固定,输出不依赖 dict 顺序。
LOCALES = (("zh-CN", "zh"), ("en-US", "en"))

#: 插件的两个来源。目录名 = slug;bundled 随应用内置,examples 从市场安装。
PLUGIN_SOURCES = (Path("plugins") / "bundled", Path("plugins") / "examples")
WORKFLOW_CATALOG = Path("website") / "public" / "workflows" / "catalog.json"

#: 和 cloud 的 `domain/shares.py` 保持同一组上限。bundle 在 seed 时会被整份校验,
#: 这里先挡住,免得部署时才发现某条标题 / 简介超长。
MAX_TITLE = 200
MAX_SUMMARY = 500
MAX_LICENSE = 64
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class ExportError(ValueError):
    """仓库里的源数据不满足 bundle 契约。CLI 把它变成 stderr + 退出码 2。"""


def text_of(value: Any, key: str) -> str | None:
    """取 manifest 里一种语言的文字。

    **不做跨语言回退**:只有字符串(语言中立)或字典里真有这个键时才算有。
    没有英文却回退到中文,正是"英文站看到中文"的来源。
    """
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        found = value.get(key)
        if isinstance(found, str):
            return found.strip() or None
    return None


def clip_summary(value: str) -> str:
    """cloud 的 summary 上限 500 字。超出的截断并明确标出省略号,不悄悄丢内容。"""
    if len(value) <= MAX_SUMMARY:
        return value
    return value[: MAX_SUMMARY - 1].rstrip() + "…"


def locale_texts(record: dict[str, Any]) -> dict[str, dict[str, str]]:
    """把 `name` / `summary` 折成 `{zh-CN: {title, summary?}, en-US: {...}}`。

    标题是必填:某种语言没有标题,就不发这一行(而不是拿另一种语言的标题顶上)。
    """
    locales: dict[str, dict[str, str]] = {}
    for cloud_locale, key in LOCALES:
        title = text_of(record.get("name"), key)
        if not title:
            continue
        if len(title) > MAX_TITLE:
            raise ExportError(f"标题超过 {MAX_TITLE} 字: {title[:40]}…")
        text: dict[str, str] = {"title": title}
        summary = text_of(record.get("summary"), key)
        if summary:
            text["summary"] = clip_summary(summary)
        locales[cloud_locale] = text
    if not locales:
        raise ExportError("name 里连一种可用的语言都没有")
    return locales


def check_slug(slug: str) -> str:
    if not isinstance(slug, str) or not slug or len(slug) > 80 or not SLUG_RE.fullmatch(slug):
        raise ExportError(f"不是合法 slug(小写字母 / 数字 / . _ -,最长 80): {slug!r}")
    return slug


def check_payload(payload: Any, where: str) -> None:
    """cloud 按紧凑 JSON 的 UTF-8 字节数量上限;这里用同一把尺子。"""
    try:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ExportError(f"{where}: payload 不是合法 JSON") from exc
    size = len(encoded.encode("utf-8"))
    if size > MAX_PAYLOAD_BYTES:
        raise ExportError(f"{where}: payload {size} 字节,超过 2 MB")


def read_json(path: Path, where: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ExportError(f"{where}: 读不到 {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExportError(f"{where}: {path} 不是合法 JSON: {exc}") from exc


def plugin_entries(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in PLUGIN_SOURCES:
        base = root / source
        if not base.is_dir():
            continue
        for folder in sorted(base.iterdir(), key=lambda one: one.name):
            if not folder.is_dir():
                continue
            manifest_path = folder / "mosael.plugin.json"
            if not manifest_path.is_file():
                continue
            slug = check_slug(folder.name)
            if slug in seen:
                raise ExportError(f"插件 slug 重复: {slug}")
            seen.add(slug)
            manifest = read_json(manifest_path, f"插件 {slug}")
            if not isinstance(manifest, dict):
                raise ExportError(f"插件 {slug}: manifest 顶层必须是对象")
            check_payload(manifest, f"插件 {slug}")
            entry: dict[str, Any] = {
                "slug": slug,
                "locales": locale_texts(manifest),
                "payload": manifest,
            }
            add_license(entry, manifest.get("license"))
            rows.append(entry)
    rows.sort(key=lambda entry: entry["slug"])
    return rows


def add_license(entry: dict[str, Any], value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        return
    license_text = value.strip()
    if len(license_text) > MAX_LICENSE:
        raise ExportError(f"{entry['slug']}: license 超过 {MAX_LICENSE} 个字符")
    entry["license"] = license_text


def workflow_payload_path(root: Path, record: dict[str, Any], slug: str, payload_locale: str) -> Path:
    download = record.get("download")
    if not isinstance(download, dict) or not download:
        raise ExportError(f"工作流 {slug}: catalog 缺 download")
    # 先按 `--payload-locale` 选;这种语言没有文件时退回固定顺序里的第一份。
    candidates = [payload_locale] + [key for _, key in LOCALES if key != payload_locale]
    for key in candidates:
        value = download.get(key)
        if isinstance(value, str) and value.strip():
            public = (root / "website" / "public").resolve()
            target = (public / value.lstrip("/")).resolve()
            if public not in target.parents:
                raise ExportError(f"工作流 {slug}: download 指向 public 之外: {value!r}")
            if not target.is_file():
                raise ExportError(f"工作流 {slug}: 找不到 payload {value}")
            return target
    raise ExportError(f"工作流 {slug}: download 里没有任何语言的文件")


def workflow_entries(root: Path, payload_locale: str) -> list[dict[str, Any]]:
    catalog = read_json(root / WORKFLOW_CATALOG, "工作流目录")
    if not isinstance(catalog, list):
        raise ExportError("catalog.json 顶层必须是数组")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, record in enumerate(catalog):
        if not isinstance(record, dict):
            raise ExportError(f"catalog[{index}] 必须是对象")
        raw_id = record.get("id")
        if not isinstance(raw_id, str) or not raw_id:
            raise ExportError(f"catalog[{index}] 缺 id")
        # 官网 WorkflowEntry.slug 就是 id 把下划线折成连字符;云端 slug 要能对它回来。
        slug = check_slug(raw_id.replace("_", "-"))
        if slug in seen:
            raise ExportError(f"工作流 slug 重复: {slug}")
        seen.add(slug)
        payload_path = workflow_payload_path(root, record, slug, payload_locale)
        payload = read_json(payload_path, f"工作流 {slug}")
        check_payload(payload, f"工作流 {slug}")
        entry: dict[str, Any] = {
            "slug": slug,
            "locales": locale_texts(record),
            "payload": payload,
        }
        add_license(entry, record.get("license"))
        rows.append(entry)
    rows.sort(key=lambda entry: entry["slug"])
    return rows


def build_bundle(root: Path, payload_locale: str) -> dict[str, Any]:
    return {
        "plugins": plugin_entries(root),
        "workflows": workflow_entries(root, payload_locale),
    }


def write_bundle(bundle: dict[str, Any], output: Path) -> None:
    text = json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 scripts/export_official_bundle.py",
        description="把仓库里的官方插件 / 工作流导出成 cloud seed-official 的 bundle",
    )
    parser.add_argument("--root", default=str(REPO_ROOT), help="仓库根(测试用,缺省是本脚本所在仓库)")
    parser.add_argument("--output", default="", help=f"输出路径,缺省 <root>/{DEFAULT_OUTPUT}")
    parser.add_argument(
        "--payload-locale",
        choices=("en", "zh"),
        default="en",
        help="工作流 payload 用哪份 .mosael-workflow.json(每条 bundle 只有一份 payload,缺省 en)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    output = Path(args.output).expanduser() if args.output else root / DEFAULT_OUTPUT
    try:
        bundle = build_bundle(root, args.payload_locale)
        write_bundle(bundle, output)
    except ExportError as exc:
        print(f"导出失败: {exc}", file=sys.stderr)
        return 2
    print(
        f"导出 {len(bundle['plugins'])} 个插件 / {len(bundle['workflows'])} 个工作流 "
        f"(工作流 payload: {args.payload_locale}) → {output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
