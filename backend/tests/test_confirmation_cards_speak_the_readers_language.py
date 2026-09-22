"""确认卡上那句话按**读的人**的语言翻,和任务消息同一条规矩。

## 为什么这条看不出来

摘要是"这次调用要做什么"的一句话,它**看起来**像数据而不像文案,所以不会有人去问"它是哪种
语言"。而 `Job.message` 的注释把代价写得很清楚:

> 这一列落库,任务记录活得比一次请求久,写入时就翻会把语言冻死在那一刻 —— 用户切成英文后
> 历史任务仍是中文,**而那正是这次要修的毛病**

确认卡是同一层、同样落库、同样活得比请求久的另一份"给人看的文案",当时没跟着改:23 个
`_summarize_*` 返回的全是写死的中文。

**确认卡尤其不能含糊**:它是授权界面 —— 用户点「批准」之前唯一会读的就是这一行。一个英文
用户读不懂的授权提示,等于没有提示。

半截的痕迹就在旁边:`external_warning` 特地把节点名翻了,**包着它的那句话仍然写死中文**;
而且那条路上 `get_current_locale()` 恒为 `zh`(语言只在 HTTP 中间件里从 Accept-Language 取,
而确认卡由 sidecar / MCP 调进来,那条路不带这个头)—— 那个 `t()` 是一条走不到的分支。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
import re
from pathlib import Path

from app.core.i18n import MESSAGES

CONFIRMABLE = Path(__file__).resolve().parent.parent / "app" / "domain" / "agent" / "confirmable"
CJK = re.compile(r"[一-鿿]")


def test_每个摘要返回的都是key不是句子() -> None:
    """全仓 23 个 `_summarize_*`,返回的第一项必须是 MESSAGES 里的 key。"""
    offenders: list[str] = []
    for path in sorted(CONFIRMABLE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("_summarize_"):
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Return) or inner.value is None:
                    continue
                value = inner.value
                if isinstance(value, ast.Tuple) and value.elts:
                    head = value.elts[0]
                    if isinstance(head, ast.Constant) and head.value in MESSAGES:
                        continue
                offenders.append(f"{path.name}:{inner.lineno} {node.name} 返回的不是 (key, 参数)")
    assert not offenders, (
        "确认卡是授权界面,而这几处把它的措辞冻成了某一种语言:\n  " + "\n  ".join(offenders)
    )


def test_摘要里没有写死的中文() -> None:
    """拼进去的每一段自己也是文案 —— 当场翻的话,外层存了 key 内层还是冻着。"""
    offenders: list[str] = []
    for path in sorted(CONFIRMABLE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("_summarize_"):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str) and CJK.search(inner.value):
                    offenders.append(f"{path.name}:{inner.lineno} {node.name}: {inner.value[:30]!r}")
    assert not offenders, "这些摘要里还有写死的中文:\n  " + "\n  ".join(offenders)


def test_每条确认卡文案两种语言都有正文() -> None:
    """少一种语言的表现不是报错,是那一档静默回落到另一种语言。"""
    for name, text in MESSAGES.items():
        if not name.startswith("confirm_"):
            continue
        assert text.get("zh") and text.get("en"), f"{name} 少了一种语言"


def test_出口按请求方的语言翻() -> None:
    from app.api.schemas.agent import ConfirmationOut

    assert "summary_key" in ConfirmationOut.model_fields
    assert "summary_params" in ConfirmationOut.model_fields


def test_老卡原样返回() -> None:
    """存量卡没有 key —— 它们的 summary 就是当时那句话,和 JobOut 对老任务的处理一字不差。"""
    from datetime import datetime

    from app.api.schemas.agent import ConfirmationOut

    card = ConfirmationOut.model_validate({
        "id": "c1", "workspace_id": "w", "session_id": None, "tool": "run_code",
        "permission": "external", "summary": "老卡的原话", "summary_key": "", "summary_params": {},
        "payload": {}, "status": "pending", "result": {}, "error": None, "requested_by": "pi",
        "created_at": datetime.now(), "resolved_at": None,
    })
    assert card.summary == "老卡的原话"
