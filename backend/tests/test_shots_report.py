"""镜头表 → 给人读的报告(domain/shots/report.py):Markdown 表格、分镜提示词、统计。全是代码算的。"""

from __future__ import annotations

from app.domain.shots import report


def _shots() -> list[dict]:
    return [
        {"id": "S01", "start": 0.0, "end": 2.0, "seconds": 2.0, "motion": 0.1,
         "size": "wide", "category": "establishing", "camera": ["static"], "rhythm": "hook",
         "subjects": ["海"], "onscreen_text": "", "audio": "旁白",
         "dialogue": "开场白", "frame": "大海和沙滩,远处有个人在走", "prompt": "全景,固定,海边日出"},
        {"id": "S02", "start": 2.0, "end": 3.5, "seconds": 1.5, "motion": 30.0,
         "size": "close", "category": "subject", "camera": ["push-in"], "rhythm": "beat",
         "subjects": ["主播"], "onscreen_text": "3 个技巧",
         "dialogue": "", "frame": "主播面部特写,背景虚化的书架", "prompt": "特写,推,主播面向镜头"},
        {"id": "S03", "start": 3.5, "end": 6.0, "seconds": 2.5, "motion": 2.0,
         "size": "medium", "category": "dialogue", "camera": ["static"], "rhythm": "payoff",
         "subjects": ["主播"], "onscreen_text": "", "audio": "主播",
         "dialogue": "第一点是选题", "frame": "主播半身,坐在桌前比划", "prompt": ""},
    ]


def test_stats_counts_shots_and_spreads() -> None:
    numbers = report.stats(_shots(), 6.0)
    assert numbers["shots"] == 3
    assert numbers["duration"] == 6.0
    assert numbers["average_seconds"] == 2.0
    assert numbers["shortest_seconds"] == 1.5
    assert numbers["longest_seconds"] == 2.5
    assert numbers["cuts_per_minute"] == 20.0  # (3-1)/6*60
    assert numbers["sizes"] == {"wide": 1, "close": 1, "medium": 1}
    assert numbers["camera"] == {"static": 2, "push-in": 1}
    assert numbers["rhythm"] == {"hook": 1, "beat": 1, "payoff": 1}
    assert numbers["categories"]["dialogue"] == 1


def test_stats_empty_shots() -> None:
    numbers = report.stats([], 0.0)
    assert numbers["shots"] == 0 and numbers["average_seconds"] == 0 and numbers["cuts_per_minute"] == 0


def test_shot_table_markdown_rows_and_escapes() -> None:
    markdown = report.shot_table_markdown(_shots(), lang="zh")
    lines = markdown.splitlines()
    assert lines[0].startswith("| # | 时间 | 时长 | 景别 | 运镜 | 画面 | 台词 / 字幕 |")
    assert lines[1].startswith("| --- |")
    assert len(lines) == 2 + 3
    assert "| S01 | 0:00.0–0:02.0 | 2.0s | 全景 | 固定 | 大海和沙滩" in lines[2]
    assert "开场白" in lines[2]
    #: 台词 / 字幕并在一格;画面里的竖线转义,不把表撑破。
    row = lines[3]
    assert "特写 | 推 | 主播面部特写" in row
    assert "3 个技巧" in row
    assert "\\|" not in row or row.count("|") == 8


def test_shot_table_markdown_english() -> None:
    markdown = report.shot_table_markdown(_shots(), lang="en")
    assert markdown.splitlines()[0].startswith("| # | Time | Length | Size | Camera |")


def test_storyboard_prompts_use_judged_prompt() -> None:
    items = report.storyboard_prompts(_shots(), lang="zh")
    assert items[0]["prompt"] == "全景,固定,海边日出"  # 模型写过的 prompt 直接拿去用,不重复拼景别运镜
    assert items[1]["id"] == "S02"
    #: 没判过画面的镜照样子出来,至少带时长。
    bare = [{"id": "S09", "start": 0.0, "seconds": 1.0, "end": 1.0, "motion": 0.0}]
    (item,) = report.storyboard_prompts(bare, lang="zh")
    assert item["id"] == "S09" and item["seconds"] == 1.0


def test_storyboard_prompts_fall_back_to_frame() -> None:
    shots = _shots()
    shots[0]["prompt"] = ""
    (first,) = report.storyboard_prompts(shots[:1], lang="zh")
    assert first["prompt"].startswith("全景, 固定")
    assert "大海和沙滩" in first["prompt"]


def test_report_markdown_combines_stats_table_and_prompts() -> None:
    markdown = report.report_markdown("样片", _shots(), 6.0, lang="zh")
    assert "## 镜头表 · 样片" in markdown
    assert "3 镜,共 6.0 秒" in markdown
    assert "景别:全景 1、特写 1、中景 1" in markdown
    assert "## 分镜提示词" in markdown
    assert "**S02** (0:02.0, 1.5s)" in markdown


def test_stats_markdown_english() -> None:
    numbers = report.stats(_shots(), 6.0)
    markdown = report.stats_markdown(numbers, lang="en")
    assert "3 shots in 6.0s" in markdown
    assert "Sizes: Wide 1" in markdown
