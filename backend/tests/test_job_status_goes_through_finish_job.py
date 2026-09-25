"""棘轮:**执行体写任务状态走 finish_job,不直接 `job.status = …`**。

执行体手里那份 Job 是开始时读的,取消是别的会话写进来的。直接赋值就把取消盖掉了:
取消过的导出重新出现在素材库里(test_job_cancellation),取消了工作流之后,它等着的转写、
转 GIF、分离、降噪跑完照样变回「完成」,字幕配音还把剩下的句子一句句合成完。

finish_job 先确认这一行还活着,再写;返回 False 时调用方就该停手。起步那一下(queued →
running)也一样 —— 排队时就被取消的,不能在执行体开始时被写回 running。

判据走 AST:给名叫 `job` 的东西的 `.status` 赋值。剩下的几处列在 REMAINING 里,**只减不增**。
"""

from __future__ import annotations

import ast
import pathlib

RATCHET = True

APP = pathlib.Path(__file__).resolve().parents[1] / "app"

#: 总线自己:落取消态、重启收尾的就是它。
OWNER = "domain/jobs.py"

#: 还没改过来的执行体。**只减不增**:改好一处就从这里删一处。
REMAINING = {
    # 发布任务的状态机在 PublishTask 上,_sync_job 把它映射到 job;任务被取消后回报直接返回,
    # 不会走到这里的赋值 —— 但它仍是直接赋值,等发布那条链一起收。
    "domain/publish/worker.py",
    "domain/voices/voices.py",
    "domain/assets/from_url.py",
    "domain/assets/proxies.py",
    "domain/boards/trim.py",
}


def _writes_job_status(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AugAssign | ast.AnnAssign) else []
        for target in targets:
            if (
                isinstance(target, ast.Attribute)
                and target.attr == "status"
                and isinstance(target.value, ast.Name)
                and target.value.id == "job"
            ):
                return True
    return False


def _offenders() -> set[str]:
    return {
        path.relative_to(APP).as_posix()
        for path in APP.rglob("*.py")
        if _writes_job_status(ast.parse(path.read_text(encoding="utf-8")))
    }


def test_执行体经_finish_job_写任务状态() -> None:
    new = sorted(_offenders() - REMAINING - {OWNER})
    assert not new, (
        "这些文件直接给 job.status 赋值 —— 取消会被盖掉。改用 domain/jobs.finish_job,"
        "它返回 False 时停手:\n  " + "\n  ".join(new)
    )


def test_改好了的就从名单里删掉() -> None:
    stale = sorted(REMAINING - _offenders())
    assert not stale, f"这些文件已经不再直接赋值了,从 REMAINING 里删掉:{stale}"
