"""结构性约束:**docs/CONVENTIONS.md 的棘轮清单与代码一致**。

这条测试是它自己守的那件事的又一个例子。上一版清单手写在 IMPLEMENTATION_STATUS.md 里,写下
时是对的,然后在没有任何信号的情况下烂掉:列了 7 条,而仓库里实际有 30 条。缺的那 23 条不是
边角料 —— 密钥落盘、写权限、子进程出口、打包版解释器,都在缺的那一批里。读者据此以为这个
仓库只守着 7 件事。

清单改由 scripts/sync-ratchet-docs.py 从 `RATCHET` 标记生成,这条守住它没过期。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_棘轮清单没有过期() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync-ratchet-docs.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, (result.stdout + result.stderr).strip()
