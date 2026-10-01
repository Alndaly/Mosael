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
from app.domain.workflows.templates_business import (
    fabric_lookbook_graph,
    footage_montage_graph,
    highlight_shorts_graph,
    product_on_model_graph,
    product_pitch_short_graph,
    talking_script_video_graph,
)


def _graphs(locale: str) -> dict[str, dict]:
    """每个模板的图。**按这一份的语言建** —— 图里给人看的默认值(新项目的名字、完成通知)在建图时定语言,
    和节点名同一条(见 domain/workflows/templates 的 transcript_video_cleanup_graph / translated_dub_graph)。"""
    return {
        #: 视频模型留空 = 按"还没挑模型"出片计划:每镜 5 秒、只走首帧那条路。**首帧是每一个能用的视频模型都收的
        #: 那一条**(参考素材那条只有部分模型收),而导入的人挑哪个模型这里不知道。出图 / 视频的画幅、尺寸、分辨率
        #: 照样接到开始参数(templates_models._video_plan):挑模型时编辑器只留新模型仍收的绑定和值(前端
        #: carriedParameters),不收 5 秒的模型由运行前检查在花钱之前说清。
        "full_video_generation": full_video_generation_graph(chat=ModelChoice(), image=ModelChoice(), video=ModelChoice()),
        "transcript_video_cleanup": transcript_video_cleanup_graph(chat=ModelChoice(), locale=locale),
        # 音色按工作区取,导出给官网的那份不能带任何本机资源 —— 留空,导入后由用户自己挑。
        "translated_dub": translated_dub_graph(chat=ModelChoice(), voice_id="", locale=locale),
        "translated_dub_lipsync": translated_dub_graph(chat=ModelChoice(), voice_id="", lipsync=True, locale=locale),
        "highlight_shorts": highlight_shorts_graph(chat=ModelChoice()),
        #: 空的 ModelChoice 表示"这台机器上还没选默认模型" —— 官网那份本来就不该带任何本机选择。
        #: 上身图这条按**带视频**导出(`motion=True`),视频模型那一格留空,由导入的人挑;没有视频模型的话,在画布上
        #: 删掉「把这一组动起来」和「归档这一组的视频」两个节点即可 —— 循环交出的是上身图,不依赖它们。
        #: 反过来(导成不带视频)则是有视频模型的人看不到那一步,而他不会知道本来有。
        "product_on_model": product_on_model_graph(
            chat=ModelChoice(), image=ModelChoice(), video=ModelChoice(), motion=True,
        ),
        "product_pitch_short": product_pitch_short_graph(chat=ModelChoice(), image=ModelChoice(), voice_id=""),
        "product_pitch_presenter": product_pitch_short_graph(chat=ModelChoice(), image=ModelChoice(), voice_id="", presenter=True),
        "fabric_lookbook": fabric_lookbook_graph(chat=ModelChoice(), image=ModelChoice()),
        "footage_montage": footage_montage_graph(chat=ModelChoice(), voice_id=""),
        "talking_script_video": talking_script_video_graph(voice_id=""),
    }


def catalog_files() -> dict[str, str]:
    #: 说明只有一份 —— 后端的模板目录(应用里的模板卡片读的也是它)。这里只补"这一份对应哪张图"。
    graphs = {locale: _graphs(locale) for locale in ("zh", "en")}
    files: dict[str, str] = {}
    catalog = []
    for template in TEMPLATE_CATALOG:
        graph = graphs["zh"][template["id"]]
        entry = {**template, "author": "Mosael", "version": graph["meta"]["template_version"],
                 "nodes": len(graph["nodes"]), "download": {}}
        #: 前置条件在后端是「一条一个对象」(带检查键,给应用里的就绪状态用);官网只展示句子,
        #: 这里摊回「一种语言一串」—— 检查键说的是**这台机器**,对官网没有意义。
        entry["requires"] = {
            locale: [one["text"][locale] for one in template["requires"]] for locale in ("zh", "en")
        }
        for locale in ("zh", "en"):
            name = f'{template["id"]}.{locale}.mosael-workflow.json'
            entry["download"][locale] = f"/workflows/{name}"
            #: **节点名按这一份的语言定下来。** 图里的名字是语言对象(翻译贴着节点写,见
            #: domain/workflows/templates),而下载下来的这份是要被导入的 —— 导入方拿到的必须是
            #: 一个名字,不是一个待挑的对象。
            localised = localised_names(locale, copy.deepcopy(graphs[locale][template["id"]]))
            payload = {"format": "mosael-workflow", "version": 1, "workflow_revision": 1,
                       "name": template["name"][locale], "description": template["summary"][locale],
                       "graph_hash": graph_digest(localised), "graph": localised}
            files[name] = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        catalog.append(entry)
    files["catalog.json"] = json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
    return files


#: 这个目录里由本脚本生成的那几种文件。别的(将来手放的说明、图片)不归它管,不查也不删。
GENERATED = "*.mosael-workflow.json"


def orphans(out: Path, files: dict[str, str]) -> list[str]:
    """目录里有、这一次却不再生成的下载文件 —— 删掉或改名的模板留下的。它们照样能从官网被下载、被导入。"""
    return sorted(path.name for path in out.glob(GENERATED) if path.name not in files)


def sync(out: Path, files: dict[str, str], *, check: bool) -> None:
    """把生成的那几份和目录对齐。`check`:只核对,对不上就报(内容过期、缺的、多出来的都算)。

    此前 --check 只看「该有的在不在、对不对」,多出来的孤儿文件发现不了;写入模式也只覆盖不删 ——
    删掉或改名一个模板,旧的那份下载会一直留在官网上。
    """
    orphaned = orphans(out, files) if out.is_dir() else []
    if check:
        stale = [name for name, text in files.items()
                 if not (out / name).exists() or (out / name).read_text(encoding="utf-8") != text]
        problems = ([f"need regeneration: {', '.join(stale)}"] if stale else []) + \
            ([f"no longer generated: {', '.join(orphaned)}"] if orphaned else [])
        if problems:
            raise SystemExit("Website workflow downloads " + "; ".join(problems))
        return
    out.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    for name in orphaned:
        (out / name).unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files = catalog_files()
    sync(ROOT / "website" / "public" / "workflows", files, check=args.check)
    print(f"Verified {len(files) - 1} workflow downloads and their catalog")


if __name__ == "__main__":
    main()
