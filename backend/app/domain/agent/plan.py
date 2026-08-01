"""任务计划:一次会话里"现在做到哪一步了"。

参考 Codex 的 `update_plan` 与 Claude Code 的待办列表 —— 它们解决的是同一个问题:**多步骤
任务里,用户看不见模型打算做什么、做到哪了**。模型自己也受益:把步骤写下来之后,它更不容易
在中途漏掉一步或反复重做同一步。

三条设计:

1. **一份计划,不是一串历史**。会话上只存"当前状态";每次更新在时间线上留一张工具卡,
   进度演变由那些卡承载。再存一套版本记录只会多出一份要对齐的真相。

2. **同时最多一步 in_progress**。允许多步并行的话,"现在在做什么"就没有答案了,而这正是
   这个列表存在的理由。多于一步时只保留第一个,其余降回 pending。

3. **计划不是确认卡**。写计划不改动任何工程状态,所以它直接执行、不走确认门控 ——
   每一步都要用户点一次的计划,没有人会用。真正的改动仍然各自出卡。
"""

from __future__ import annotations

from typing import Any

#: 一步的三种状态。没有 "failed" —— 失败是模型该在回复里讲清楚的事,塞进状态机只会让
#: 界面多一种颜色而信息量不变。
STATUSES = ("pending", "in_progress", "done")

#: 步骤条数上限。超过这个数就不是"计划"而是"清单",模型也开始编凑数的步骤。
MAX_STEPS = 20

#: 单步文字上限。一步写成一段的话,列表就失去了扫一眼看清进度的作用。
MAX_STEP_CHARS = 160


def normalize(steps: Any) -> list[dict[str, str]]:
    """把模型给的任意形状收敛成 `[{"step", "status"}]`。

    模型给纯字符串数组是常见写法(它未必每次都带上 status),照收 —— 拒绝一个语义完全清楚
    的输入,只会让它多试几轮,而每一轮都是一次真实的模型调用。
    """
    if not isinstance(steps, list):
        raise ValueError("steps 必须是数组")
    out: list[dict[str, str]] = []
    for item in steps[:MAX_STEPS]:
        if isinstance(item, str):
            text, status = item, "pending"
        elif isinstance(item, dict):
            text = str(item.get("step") or item.get("title") or item.get("content") or "").strip()
            status = str(item.get("status") or "pending").strip().lower()
        else:
            continue
        text = text.strip()
        if not text:
            continue
        if status not in STATUSES:
            status = "pending"
        out.append({"step": text[:MAX_STEP_CHARS], "status": status})
    if not out:
        raise ValueError("计划至少要有一步")
    # 同时最多一步在做:多于一步时"现在在做什么"就没有答案了,而这正是这份列表的用处。
    seen_running = False
    for step in out:
        if step["status"] != "in_progress":
            continue
        if seen_running:
            step["status"] = "pending"
        seen_running = True
    return out


def summarize(plan: Any) -> str:
    """一行进度,给工具卡的折叠态用。"""
    steps = plan if isinstance(plan, list) else []
    done = sum(1 for step in steps if isinstance(step, dict) and step.get("status") == "done")
    running = next(
        (str(step.get("step", "")) for step in steps if isinstance(step, dict) and step.get("status") == "in_progress"),
        "",
    )
    head = f"{done}/{len(steps)}"
    return f"{head} · {running}" if running else head
