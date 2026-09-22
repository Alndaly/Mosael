"""用户在「模型设置」里填的每一格,**两条执行通道上都要有人读它**。

## 为什么这条看不出来

同一件事有两条路:`domain/ai_chat.chat()` 直连 HTTP(翻译、素材分析、工作流 LLM 节点、
工作流 AI 编排、发布文案、提示词优化、画板写作、放行判断 —— 八个调用点),和
`provider_runtime.sidecar_provider()` → pi sidecar(智能体那条)。`RUNTIME_FIELDS` 声明了
七格「可被用户覆盖的运行时参数」,而它们只被拼进了 sidecar 那一份 payload。

于是用户填「最大输出 Token = 384000」,在智能体那条路上生效,在那八条路上**一个字节都发不
出去** —— 而设置页显示的 `effective_max_output_tokens` 那一行写着「运行时真正会用的数」,
两条路上长得一模一样。不填 `max_tokens` 时供应商用自己的默认值,通常能跑出结果,只是结果比
用户要求的短:**没有任何东西会报错,只是它比你要的短**。

`model_limits.resolve` 的文档写着「唯一的合并处」,那句话成立 —— 问题从来不是有第二处合并,
而是有一条通道根本不经过它。**一个声明了却只有一半消费者的枚举,是这种断链最典型的温床。**

这条棘轮问的不是「两侧一不一致」(那是契约语料的活),而是**「第二条通道接上了吗」**。
形状抄 `test_executor_outputs_are_declared.py`。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import ast
from pathlib import Path

from app.domain.provider_models import RUNTIME_FIELDS

BACKEND = Path(__file__).resolve().parent.parent
#: 直连那条通道的落点。这里读得到某一格,才算它在这条路上「接上了」。
DIRECT = (BACKEND / "app" / "domain" / "ai_chat.py",)
#: sidecar 那条通道的落点。
SIDECAR = (
    BACKEND / "app" / "domain" / "provider_runtime.py",
    BACKEND / "app" / "domain" / "provider_models.py",
    BACKEND / "app" / "ai" / "sidecar" / "adapters.py",
)

#: 只有 sidecar 用得上的格子。**每一条都要写清楚为什么**,而且这张表只减不增 ——
#: 它是一份"已知债务"清单,不是一个让整类字段消失的开关。
SIDECAR_ONLY: dict[str, str] = {
    "reasoning_effort": (
        "思考档位。**各家的参数不是同一套词,猜错一个值就是整轮 400**(见 domain/thinking),"
        "所以直连通道要发它必须先经查证过的按 vendor 映射 —— 那是 AI 审计 2.4 那条的活。"
        "在那之前宁可不发,也不发一个猜的。"
    ),
    "developer_role": "system/developer 角色名:pi 构造消息时用。直连通道的消息由调用方自己拼好,不经这一层。",
    "vision": "能不能看图:决定 sidecar 要不要把截图塞进回合。直连那八个调用点各自决定发不发图,不读这一格。",
    "generation_capability_ref": "生成参数按什么来 —— 这是**生成**(图/视频)那条链的格子,不属于对话通道。见 domain/generation/resolution。",
    "context_window": (
        "上下文窗口。sidecar 用它算上下文表并决定何时压缩;直连通道不做裁剪(消息由调用方构造完再交进来),"
        "所以这一格在那八条路上确实没有落点。**这不是「接上了」,是「这条路上没有这件事」** —— "
        "哪天直连也要做预算,这条理由就该删掉。"
    ),
}


def _names_in(paths: tuple[Path, ...]) -> set[str]:
    """这些文件里出现过的标识符与字符串字面量 —— 读得到就算有落点。"""
    found: set[str] = set()
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                found.add(node.id)
            elif isinstance(node, ast.Attribute):
                found.add(node.attr)
            elif isinstance(node, ast.keyword) and node.arg:
                found.add(node.arg)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.add(node.value)
    return found


def test_每一格在两条通道上都有落点() -> None:
    direct, sidecar = _names_in(DIRECT), _names_in(SIDECAR)
    missing_direct = [f for f in RUNTIME_FIELDS if f not in SIDECAR_ONLY and f not in direct]
    missing_sidecar = [f for f in RUNTIME_FIELDS if f not in sidecar]

    assert not missing_direct, (
        "这几格用户设得了,而**直连那条通道**(八个调用点:翻译/素材分析/工作流 LLM/AI 编排/"
        "发布文案/提示词优化/画板写作/放行判断)没有任何地方读它 —— 设置页那行「运行时真正会"
        "用的数」在那八条路上是一句不成立的话:\n  " + "\n  ".join(missing_direct)
    )
    assert not missing_sidecar, "这几格 sidecar 那条通道读不到:\n  " + "\n  ".join(missing_sidecar)


def test_只给sidecar的那张表只减不增() -> None:
    """每一格不接都要一直说得出理由。表变长时,先问问是不是又漏接了一条通道。"""
    # 6 → 5:`reasoning` 已经接上直连通道(查证不到思考行为时用它定输出预算)。
    assert len(SIDECAR_ONLY) <= 5, "又多了一格只有一条通道读得到的参数 —— 先确认那是真的合理"
    for name, reason in SIDECAR_ONLY.items():
        assert name in RUNTIME_FIELDS, f"{name} 已经不是运行时参数了,从表里删掉"
        assert len(reason.strip()) > 20, f"{name} 的理由太短,写清楚为什么只有一条通道需要它"


def test_直连通道真的经过唯一那处合并() -> None:
    """`model_limits.resolve` 自称「唯一的合并处」。这条钉住直连那边真的调了它 ——
    抄一份合并逻辑过去同样能让上面那条测试变绿,而那正是要防的事。"""
    source = (BACKEND / "app" / "domain" / "ai_chat.py").read_text(encoding="utf-8")
    assert "model_limits.resolve(" in source, "直连通道没走那个唯一的合并处"
