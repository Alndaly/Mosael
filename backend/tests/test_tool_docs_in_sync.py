"""结构性约束:**docs/MCP.md 的工具清单与代码一致**。

手写的清单会腐烂,而且**没有任何信号**:这份文档一度只列了 54 个工具里的 15 个,缺的恰恰是
后来加的那批(浏览器、记忆、通知)。读者据此以为智能体不会这些事,而没有人会去数一遍。

清单改由 scripts/sync-tool-docs.py 从注册表生成,这条测试守住它没过期。加了工具忘了重新生成,
这里会红,而不是等某个用户照着文档得出错误结论。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_MCP文档的工具清单没有过期() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync-tool-docs.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, (result.stdout + result.stderr).strip()
