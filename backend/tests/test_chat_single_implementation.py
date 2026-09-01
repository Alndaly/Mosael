"""结构性约束:**对话补全只有一个实现**。

这条守的是一类已经发生过的事故:`/chat/completions` 曾经被抄了八份(翻译、发布文案、图谱
抽取、提示词优化、AI 编排、素材分析、工作流 LLM 节点),抄件不会一起演进,于是分出了四种
用户看得见的差异 ——

  - 一半有重试一半没有,而设置页那句「连接断开/超时/限流时自动重试」是对全部功能的承诺;
  - 只有一处记得脱敏,其余把 httpx 的异常原文塞进错误消息,而那里面带着请求头,API key
    就这样进了任务日志和界面提示;
  - 只有一处处理了空密钥(本地无鉴权端点),其余发 `Bearer ` 让 httpx 抛一个和鉴权无关的错;
  - 一条用量都不记,首页的 Token 图和成本统计因此长期是漏的。

四件事没有一件是"这个模块的特殊需求",它们是每次调用都该有的。所以再出现第二个
`/chat/completions` 字面量,这条测试就红 —— 只减不增,和 tests/test_undo_registry.py、
test_agent_workflow_parity.py 是同一套棘轮。
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

BACKEND = Path(__file__).resolve().parents[1]

#: 唯一允许出现这个端点字面量的文件。
OWNER = "app/domain/ai_chat.py"

#: 例外:**不是** OpenAI 风格 chat 端点、或不经这条路的地方,写明理由。
EXEMPT: dict[str, str] = {
    # sidecar 那边是 TypeScript,由 pi 自己拼请求;这份 Python 目录不管它。
}


def _files_containing(needle: str) -> list[str]:
    """哪些文件在**代码里**出现了这个字面量。

    刻意走 AST 而不是文本搜索:注释和文档字符串里提到 `/chat/completions` 是在解释这条约束
    本身(ai_retry 的模块文档就在讲它),把那些算成违规,这条棘轮第一天就得挂一串豁免 ——
    而豁免清单一长,它就不再是约束了。
    """
    tracked = subprocess.run(
        ["git", "ls-files", "app", "mcp_server.py"], cwd=BACKEND, capture_output=True, text=True
    ).stdout.split()
    hits = []
    for rel in tracked:
        path = BACKEND / rel
        if not rel.endswith(".py") or not path.exists():
            continue
        tree = ast.parse(path.read_text("utf-8"))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", None) or []
                first = body[0] if body else None
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    docstrings.add(id(first.value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                if needle in node.value:
                    hits.append(rel)
                    break
    return sorted(hits)


def test_只有一个模块拼_chat_completions_请求() -> None:
    offenders = [rel for rel in _files_containing("/chat/completions") if rel != OWNER and rel not in EXEMPT]
    assert offenders == [], (
        "对话补全又出现了第二份实现 —— 请改用 app/domain/ai_chat.chat():\n  " + "\n  ".join(offenders)
    )


# 只查端点字面量,不查「谁解析了 choices」。后者听起来是同一件事的另一半,实际不成立:
# 通义万相的图像接口回包里也有 choices,形状却完全不同
# (app/ai/providers/adapters/alibaba/dashscope/image.py)。
# 为它挂一条豁免,就是用一条钝的约束换一条注定要不断加例外的清单 —— 而端点这条足够锋利:
# 重新实现一遍对话补全,绕不开 /chat/completions。


def test_豁免清单里没有过时条目() -> None:
    for rel in EXEMPT:
        assert (BACKEND / rel).exists(), f"豁免了不存在的文件: {rel}"
