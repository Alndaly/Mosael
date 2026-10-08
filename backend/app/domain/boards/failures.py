"""画板格子上的失败,**读的时候**才变成给人看的样子。

格子里存的是失败的原样(`run.error` 原文、`run.error_key` 文案 key、`run.error_params` 参数 —— 和任务同形,见
outputs._canvas_with_delivered_result)。出口(BoardOut.failures)给每一格跑挂了的出三样,按读的人的语言:

- `error_summary`:那一句(和 AI 工作台的失败卡同一个来源,见 domain/failure_summary.summarize);
- `error_detail`:原文,比那一句多出信息时才有;
- `error_hint`:认得出的原因和怎么修(`{cause, steps}`),没有是 None。

画布本身原样出、原样存:给人看的这几样另放一张表(格子 id → 三样),不混进画布 —— 混进去的话客户端存画布时又带回来。
此前回执把那一句按回执那一刻的语言摘好存死,中文界面跑的格子切到英文界面看还是中文。
"""

from __future__ import annotations

from typing import Any

from app.domain.failure_summary import detail_of, hint_of, summarize


def failures_of(canvas: Any, locale: str) -> dict[str, dict[str, Any]]:
    """画布里跑挂了的格子 → `{格子 id: {error_summary, error_detail, error_hint}}`(按 `locale`)。"""
    items = canvas.get("items") if isinstance(canvas, dict) else None
    out: dict[str, dict[str, Any]] = {}
    for item in items if isinstance(items, list) else []:
        run = item.get("run") if isinstance(item, dict) else None
        if not isinstance(run, dict) or run.get("status") != "failed" or not (run.get("error") or run.get("error_key")):
            continue
        error = str(run.get("error") or "")
        key = str(run.get("error_key") or "")
        params = run.get("error_params") if isinstance(run.get("error_params"), dict) else {}
        out[str(item.get("id"))] = {
            "error_summary": summarize(error, key, params, locale) or None,
            "error_detail": detail_of(error, key, params, locale),
            "error_hint": hint_of(params, locale),
        }
    return out


__all__ = ["failures_of"]
