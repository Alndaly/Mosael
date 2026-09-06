#!/usr/bin/env python3
"""Export the real built-in templates for the website, without user-specific resources.

Run with backend/.venv/bin/python scripts/sync-website-workflows.py.
--check verifies committed downloads without modifying them; the backend test gate runs it too.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain.workflows.revisions import graph_digest
from app.domain.workflows.templates import ModelChoice, full_video_generation_graph, transcript_video_cleanup_graph


def catalog_files() -> dict[str, str]:
    templates = [
        {
            "id": "full_video_generation",
            "name": {"zh": "从主题到完整视频", "en": "Topic to finished video"},
            "summary": {
                "zh": "输入一个主题，生成创意主旨、脚本、视觉方案与分镜，逐镜生成视频并组装导出。可选添加旁白。",
                "en": "Turn a topic into a creative brief, script, visual direction and storyboard, then generate, assemble and export the video. Narration is optional.",
            },
            "requires": {
                "zh": ["AI 对话模型", "支持文生视频的模型", "旁白可选：克隆音色"],
                "en": ["Chat model", "Text-to-video model", "Optional narration: cloned voice"],
            },
            "stages": {
                "zh": ["输入主题", "脚本与视觉方案", "生成分镜", "逐镜生成与组装", "导出成片"],
                "en": ["Choose a topic", "Script and visual direction", "Storyboard", "Generate and assemble", "Export"],
            },
            "graph": full_video_generation_graph(chat=ModelChoice(), video=ModelChoice()),
        },
        {
            "id": "transcript_video_cleanup",
            "name": {"zh": "口播与访谈智能整理", "en": "Transcript-based video cleanup"},
            "summary": {
                "zh": "将已有视频转为带时间码的逐字稿，识别停顿、口头禅与重复内容，生成裁切方案和整理版视频。保留原素材。",
                "en": "Transcribe an existing video with timestamps, identify pauses, fillers and repetition, then create a cut plan and a cleaned video while preserving the original.",
            },
            "requires": {
                "zh": ["AI 对话模型", "可用的转写引擎", "待整理的视频素材"],
                "en": ["Chat model", "Available transcription engine", "Source video"],
            },
            "stages": {
                "zh": ["选择视频", "生成逐字稿", "诊断与裁切方案", "波纹裁切", "导出整理版"],
                "en": ["Choose a video", "Transcribe", "Review and plan cuts", "Ripple cut", "Export"],
            },
            "graph": transcript_video_cleanup_graph(chat=ModelChoice()),
        },
    ]
    files: dict[str, str] = {}
    catalog = []
    for template in templates:
        graph = template.pop("graph")
        entry = {**template, "author": "Mosael", "version": graph["meta"]["template_version"],
                 "nodes": len(graph["nodes"]), "download": {}}
        for locale in ("zh", "en"):
            name = f'{template["id"]}.{locale}.mosael-workflow.json'
            entry["download"][locale] = f"/workflows/{name}"
            payload = {"format": "mosael-workflow", "version": 1, "workflow_revision": 1,
                       "name": template["name"][locale], "description": template["summary"][locale],
                       "graph_hash": graph_digest(graph), "graph": graph}
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
