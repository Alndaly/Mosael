"""提交的 `openapi.json` 必须是 app 此刻的真实形状。

这道门一直只在 CI 上、而且排在后端与前端测试**之后**:本地跑完整套件全绿,推上去十二分钟
才红在一句「已过期」。这一轮就撞到了 —— `ClaimRequest.worker` 从「有默认值的可选」改成必填,
快照没重导,于是 `frontend/src/api/generated/schema.d.ts` 里它还是可选的:**前端的类型检查
替后端放行了一个后端会拒绝的请求**,而两边都是绿的。

判据和 `scripts/export_openapi.py --check` 一模一样 —— 这里不复制它的逻辑,直接调它,
免得哪天门的判据改了而这条测试还在守旧的那个。

它只管到快照这一层。`schema.d.ts` 由 `pnpm gen:api` 从快照生成,那一跳仍由 CI 的
`git diff --exit-code` 守;而只要快照本身不漂,那一跳就不会独自漂。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_openapi_快照跟得上路由() -> None:
    done = subprocess.run(
        [sys.executable, "scripts/export_openapi.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, (
        (done.stdout + done.stderr).strip()
        + "\n(在 backend/ 里跑 `python scripts/export_openapi.py`,再在仓库根跑 `pnpm gen:api`,"
        "两个生成物一起提交。)"
    )
