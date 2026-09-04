"""上下文水位契约的后端一侧:跑 contracts/context-meter-cases.json。

sidecar 的 `test/context-meter.parity.test.mjs` 跑**同一份文件**。

为什么需要契约:同一件事(这段对话占了多少 token)有两份实现 —— sidecar 那份
(`compaction.ts`)决定**压不压**,后端这份(`domain/context_meter.py`)在界面上显示
**还能聊多久**。`context_meter.py` 的模块注释早就写着「两份实现必须保持同一套锚点规则,
改一处就要改另一处」,而**它已经没做到**:后端补上了 `cacheRead`(缓存命中的部分照样占
窗口),sidecar 那份没跟上。开着 prompt caching 时 input 只剩新增的一小段,于是 sidecar
看到的水位只有真实值的零头 —— 界面显示 90%,压缩迟迟不触发,直到某一轮直接超窗失败。

**靠注释提醒对方不是机制。**

为什么不合并成一份:压缩发生在 Node 侧的 pi 循环里,展示发生在 Python 侧的 HTTP 响应里,
中间隔着一次进程边界;而水位要在"还没开口"时就能看(打开旧会话、刚换模型、上一轮失败),
那些时刻根本没有新的一轮可以回报。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.agent.host import FALLBACK_CONTEXT_WINDOW, LOCAL_FALLBACK_CONTEXT_WINDOW, fallback_context_window
from app.domain.context_meter import CHARS_PER_TOKEN, context_tokens

_CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "context-meter-cases.json"


def _load() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def _cases() -> list[dict]:
    return _load()["cases"]


def _ids() -> list[str]:
    return [case["name"] for case in _cases()]


def test_contract_file_is_present_and_versioned() -> None:
    """语料找不到就静默跳过是最坏的结果 —— 那样两侧都「通过」,而契约根本没跑。"""
    assert _CONTRACT.is_file(), f"上下文水位契约语料缺失: {_CONTRACT}"
    data = _load()
    assert data["contract"] == "context-meter"
    assert isinstance(data["version"], int)
    assert data["cases"], "语料为空 = 没有任何一致性保护"


def test_constants_match_the_contract() -> None:
    """两个常量各在两侧写了一遍,注释里互相叮嘱「必须一致」—— 现在由语料说了算。"""
    constants = _load()["constants"]

    assert CHARS_PER_TOKEN == constants["chars_per_token"]
    assert FALLBACK_CONTEXT_WINDOW == constants["fallback_context_window"]
    assert LOCAL_FALLBACK_CONTEXT_WINDOW == constants["local_fallback_context_window"]


@pytest.mark.parametrize("case", _load()["fallback_cases"])
def test_unknown_model_window_fallback_matches_contract(case: dict) -> None:
    assert fallback_context_window(case["base_url"]) == case["context_window"]


@pytest.mark.parametrize("case", _cases(), ids=_ids())
def test_context_tokens_match_contract(case: dict) -> None:
    actual = context_tokens(case["messages"])

    assert actual == case["context_tokens"], (
        f"{case['name']}\n  契约: {case['context_tokens']}\n  实际: {actual}\n"
        f"  用例理由: {case.get('why', '')}"
    )
