"""镜头表 → 给人读的 Markdown、给生成用的分镜提示词、一组统计。全是代码算的,不调模型。

统计是写总结的模型拿到的「事实」:平均镜长、每分钟几刀、景别 / 运镜 / 节奏的分布 —— 让它去心算几十镜的平均值,
既浪费又会算错。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.domain.shots import vocab
from app.domain.shots.frames import timecode


def _cell(text: str) -> str:
    """Markdown 表格里一格:竖线和换行会把表撑破。"""
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def _camera(shot: dict[str, Any], lang: str) -> str:
    return " + ".join(vocab.camera_label(move, lang) for move in shot.get("camera") or [])


def stats(shots: list[dict[str, Any]], duration: float) -> dict[str, Any]:
    count = len(shots)
    seconds = [float(shot["seconds"]) for shot in shots]

    def spread(field: str) -> dict[str, int]:
        counter: Counter[str] = Counter()
        for shot in shots:
            values = shot.get(field)
            for value in values if isinstance(values, list) else [values]:
                if value:
                    counter[str(value)] += 1
        return dict(counter.most_common())

    return {
        "shots": count,
        "duration": round(duration, 2),
        "average_seconds": round(sum(seconds) / count, 2) if count else 0,
        "shortest_seconds": round(min(seconds), 2) if seconds else 0,
        "longest_seconds": round(max(seconds), 2) if seconds else 0,
        "cuts_per_minute": round((count - 1) / duration * 60, 1) if duration > 0 and count > 1 else 0,
        "sizes": spread("size"),
        "camera": spread("camera"),
        "categories": spread("category"),
        "rhythm": spread("rhythm"),
    }


def shot_table_markdown(shots: list[dict[str, Any]], *, lang: str) -> str:
    en = lang == "en"
    head = ("| # | Time | Length | Size | Camera | Picture | Dialogue / text |" if en
            else "| # | 时间 | 时长 | 景别 | 运镜 | 画面 | 台词 / 字幕 |")
    rows = [head, "| --- | --- | --- | --- | --- | --- | --- |"]
    for shot in shots:
        words = " / ".join(part for part in (shot.get("dialogue"), shot.get("onscreen_text")) if part)
        rows.append("| " + " | ".join([
            shot["id"],
            f"{timecode(shot['start'])}–{timecode(shot['end'])}",
            f"{shot['seconds']:.1f}s",
            _cell(vocab.label(vocab.SIZES, shot.get("size") or "", lang)),
            _cell(_camera(shot, lang)),
            _cell(shot.get("frame") or ""),
            _cell(words),
        ]) + " |")
    return "\n".join(rows)


def storyboard_prompts(shots: list[dict[str, Any]], *, lang: str) -> list[dict[str, Any]]:
    """每镜一条可以直接拿去生成的分镜提示词。模型写过的 prompt 本身已带景别 + 运镜,直接用;
    没判过画面的镜头用景别 / 运镜标签拼在画面描述前占位,只有机器量那一半(时长、动静)的也照样列出来。"""
    items: list[dict[str, Any]] = []
    for shot in shots:
        if shot.get("prompt"):
            prompt = str(shot["prompt"])
        else:
            size = vocab.label(vocab.SIZES, shot.get("size") or "", lang)
            camera = _camera(shot, lang)
            lead = ", ".join(part for part in (size, camera) if part)
            body = shot.get("frame") or ""
            prompt = f"{lead}. {body}".strip(". ").strip() if lead else body
        items.append({
            "id": shot["id"],
            "start": shot["start"],
            "seconds": shot["seconds"],
            "prompt": prompt,
        })
    return items


def storyboard_markdown(shots: list[dict[str, Any]], *, lang: str) -> str:
    lines = []
    for item in storyboard_prompts(shots, lang=lang):
        lines.append(f"- **{item['id']}** ({timecode(item['start'])}, {item['seconds']:.1f}s) {item['prompt']}".rstrip())
    return "\n".join(lines)


def stats_markdown(numbers: dict[str, Any], *, lang: str) -> str:
    en = lang == "en"

    def top(spread: dict[str, int], table: dict[str, Any] | None) -> str:
        parts = []
        for key, count in list(spread.items())[:5]:
            name = vocab.camera_label(key, lang) if table is None else vocab.label(table, key, lang)
            parts.append(f"{name} {count}")
        return ", ".join(parts) if en else "、".join(parts)

    lines = [
        (f"- {numbers['shots']} shots in {numbers['duration']:.1f}s; average {numbers['average_seconds']:.1f}s"
         f" (shortest {numbers['shortest_seconds']:.1f}s, longest {numbers['longest_seconds']:.1f}s);"
         f" {numbers['cuts_per_minute']} cuts per minute") if en else
        (f"- {numbers['shots']} 镜,共 {numbers['duration']:.1f} 秒;平均每镜 {numbers['average_seconds']:.1f} 秒"
         f"(最短 {numbers['shortest_seconds']:.1f}、最长 {numbers['longest_seconds']:.1f});每分钟 {numbers['cuts_per_minute']} 刀"),
    ]
    for key, table, zh, en_name in (("sizes", vocab.SIZES, "景别", "Sizes"), ("camera", None, "运镜", "Camera"),
                                    ("rhythm", vocab.RHYTHMS, "节奏", "Rhythm")):
        if numbers.get(key):
            lines.append(f"- {en_name}: {top(numbers[key], table)}" if en else f"- {zh}:{top(numbers[key], table)}")
    return "\n".join(lines)


def report_markdown(title: str, shots: list[dict[str, Any]], duration: float, *, lang: str) -> str:
    en = lang == "en"
    numbers = stats(shots, duration)
    return "\n\n".join([
        f"## {'Shot list' if en else '镜头表'} · {title}",
        stats_markdown(numbers, lang=lang),
        shot_table_markdown(shots, lang=lang),
        f"## {'Storyboard prompts' if en else '分镜提示词'}",
        storyboard_markdown(shots, lang=lang),
    ])


__all__ = ["report_markdown", "shot_table_markdown", "stats", "stats_markdown", "storyboard_markdown",
           "storyboard_prompts"]
