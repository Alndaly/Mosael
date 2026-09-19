#!/usr/bin/env python3
"""Export the real built-in templates for the website, without user-specific resources.

Run with backend/.venv/bin/python scripts/sync-website-workflows.py.
--check verifies committed downloads without modifying them; the backend test gate runs it too.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain.workflows.revisions import graph_digest
from app.domain.workflows.templates import (
    TEMPLATE_CATALOG,
    ModelChoice,
    full_video_generation_graph,
    localised_names,
    transcript_video_cleanup_graph,
    translated_dub_graph,
)


def catalog_files() -> dict[str, str]:
    #: 说明只有一份 —— 后端的模板目录(应用里的模板卡片读的也是它)。这里只补"这一份对应哪张图"。
    graphs = {
        "full_video_generation": full_video_generation_graph(chat=ModelChoice(), image=ModelChoice(), video=ModelChoice()),
        "transcript_video_cleanup": transcript_video_cleanup_graph(chat=ModelChoice()),
        # 音色按工作区取,导出给官网的那份不能带任何本机资源 —— 留空,导入后由用户自己挑。
        "translated_dub": translated_dub_graph(voice_id=""),
    }
    templates = [{**template, "graph": graphs[template["id"]]} for template in TEMPLATE_CATALOG]
    files: dict[str, str] = {}
    catalog = []
    for template in templates:
        graph = template.pop("graph")
        entry = {**template, "author": "Mosael", "version": graph["meta"]["template_version"],
                 "nodes": len(graph["nodes"]), "download": {}}
        for locale in ("zh", "en"):
            name = f'{template["id"]}.{locale}.mosael-workflow.json'
            entry["download"][locale] = f"/workflows/{name}"
            #: **节点名按这一份的语言定下来。** 图里的名字是语言对象(翻译贴着节点写,见
            #: domain/workflows/templates),而下载下来的这份是要被导入的 —— 导入方拿到的必须是
            #: 一个名字,不是一个待挑的对象。
            localised = localised_names(locale, copy.deepcopy(graph))
            payload = {"format": "mosael-workflow", "version": 1, "workflow_revision": 1,
                       "name": template["name"][locale], "description": template["summary"][locale],
                       "graph_hash": graph_digest(localised), "graph": localised}
            files[name] = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        catalog.append(entry)
    files["catalog.json"] = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    out = ROOT / "website" / "public" / "workflows"
    files = catalog_files()
    if args.check:
        stale = [name for name, text in files.items()
                 if not (out / name).exists() or (out / name).read_text(encoding="utf-8") != text]
        if stale:
            raise SystemExit("Website workflow downloads need regeneration: " + ", ".join(stale))
    else:
        out.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (out / name).write_text(text, encoding="utf-8")
    print(f"Verified {len(files) - 1} workflow downloads and their catalog")


if __name__ == "__main__":
    main()
