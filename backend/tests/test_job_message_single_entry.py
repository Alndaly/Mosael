"""任务的「给人看的话」只有一个入口:`say()`。

绕开它直接写 `job.message` 的后果是**静默且永久**的:`message_key` 还停在建任务时那句,
而接口是**按 key 重翻**的(JobOut._translate),于是无论运行时把 message 改成什么,
用户看到的永远是最初那句。

真机上撞到的样子:一次视频生成 `job.queued` 与 `job.running` 相差 5 毫秒(根本没排过队),
跑了 311 秒成功落库、message 列写着 "Generation complete" —— 而接口从头到尾返回
"Queued for generation provider",连任务成功之后也是。用户因此以为任务卡在排队里。
"""

from __future__ import annotations

import pathlib
import re

from app.core.i18n import DEFAULT_LOCALE, t
from app.db.models import Job
from app.domain.jobs import say

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def test_没有人绕开say直接写job_message() -> None:
    offenders: list[str] = []
    for path in BACKEND.glob("app/**/*.py"):
        if path.name == "jobs.py" and path.parent.name == "domain":
            continue  # say() 自己住在这儿
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            # 只找对 Job 行的 message 赋值:`xxx_job.message =` / `job.message =`
            if re.search(r"\b\w*job\.message\s*=(?!=)", line, re.IGNORECASE):
                offenders.append(f"{path.relative_to(BACKEND)}:{number}: {line.strip()}")
    assert offenders == [], (
        "这些地方绕开了 say(),写进去的话用户永远看不到(接口按 message_key 重翻):\n  "
        + "\n  ".join(offenders)
    )


def test_say_让接口看到的那句跟着变() -> None:
    """建任务时是一句,运行时改成另一句 —— 接口必须返回后一句。"""
    from app.api.schemas import JobOut

    job = Job(workspace_id="w", kind="ai_generation", payload={})
    say(job, "jobMsg_generationQueued")
    first = JobOut.model_validate(_fill(job)).message

    say(job, "jobMsg_generationDone")
    second = JobOut.model_validate(_fill(job)).message

    assert first != second, "改过之后接口还在返回建任务时那句"
    assert second == t("jobMsg_generationDone", DEFAULT_LOCALE)


def test_认不出的key当字面量_运行时自由文本也不会丢() -> None:
    """供应商回报的进度、外部 worker 的报告都是自由文本,没有 key。

    它们照样得走 say() —— 认不出就原样存(create_job 的约定),但 message_key 会一起更新,
    不再被上一句盖住。
    """
    from app.api.schemas import JobOut

    job = Job(workspace_id="w", kind="render", payload={})
    say(job, "jobMsg_generationQueued")
    say(job, "正在合成第 3 段,共 8 段")
    assert JobOut.model_validate(_fill(job)).message == "正在合成第 3 段,共 8 段"


def _fill(job: Job) -> Job:
    """补齐 JobOut 需要但内存对象还没有的列(平时由数据库默认值给)。"""
    from app.db.models import now

    job.id = job.id or "j"
    job.status = job.status or "running"
    job.progress = job.progress or 0.0
    job.payload = job.payload or {}
    job.result = job.result or {}
    job.created_at = job.created_at or now()
    job.updated_at = job.updated_at or now()
    return job
