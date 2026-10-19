"""一轮对话的超时,量的应该是「多久没有进展」,不是「已经跑了多久」。

真机现场:智能体一直在正常干活 —— 连续多次工具调用、计划走到 3/4 —— 却在第 600 秒被
「运行超过 600 秒未返回,已终止」掐掉。用户的原话是「这明显是不合理的」。

两把表,两个意思:

- **空闲上限**(600 秒):连续这么久没有任何进展才终止。正文 / 思考的每个分片、每次工具
  调用(开始或结束)、子智能体的每一步都算进展。它不再回答「这一轮一共跑了多久」。
- **硬上限**(2 小时):有进展也算,防止真的无限跑。只有它才该说「运行超过 N 小时」。

超时不是静默的,也**不是取消**(`failed` 仍然是 `failed`)。失败卡要说得清它最后停在哪一步,
否则用户看到的仍然是「明明在正常跑」。

这些用例用假 sidecar + 打桩的时限,不真等十分钟。600 这个数不改 —— 改的是「什么叫在用」。
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from app.ai.sidecar import pi_client
from app.core.child_process import popen_text
from app.core.i18n import speaking, t
from tests.test_agent_queue import _session, _wait_idle
from tests.util import fresh_client


#: 持续有进展:每 0.15 秒一次工具调用,总共约 1.2 秒。比打桩的空闲上限(0.5 秒)长得多。
BUSY_SIDECAR = """
import json, sys, time
sys.stdin.readline()

def send(event):
    print(json.dumps(event), flush=True)

for index in range(8):
    send({"type": "tool_start", "turnId": "turn", "toolCallId": f"call-{index}", "name": "update_plan", "args": {}})
    send({"type": "tool_end", "turnId": "turn", "toolCallId": f"call-{index}", "result": {}, "isError": False})
    time.sleep(0.15)
send({"type": "turn_done", "turnId": "turn", "text": "做完了", "sessionState": []})
"""

#: 一句话都不说,也不退出 —— 真正的「卡死在半路」。
SILENT_SIDECAR = """
import json, sys, time
sys.stdin.readline()
time.sleep(30)
print(json.dumps({"type": "turn_done", "turnId": "turn", "text": "不该到这里", "sessionState": []}), flush=True)
"""

#: 调过一次工具,然后彻底没动静 —— 失败卡要留下「最后一步」.
TOOL_THEN_SILENT_SIDECAR = """
import json, sys, time
sys.stdin.readline()
print(json.dumps({"type": "tool_start", "turnId": "turn", "toolCallId": "call-plan", "name": "update_plan", "args": {}}), flush=True)
time.sleep(30)
print(json.dumps({"type": "turn_done", "turnId": "turn", "text": "不该到这里", "sessionState": []}), flush=True)
"""


def _install_fake_sidecar(tmp_path, monkeypatch, source: str) -> None:
    script = tmp_path / "sidecar.py"
    script.write_text(source)
    monkeypatch.setattr(
        pi_client,
        "spawn_pi",
        lambda **_: popen_text(
            [sys.executable, str(script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ),
    )


def _stub_timeouts(monkeypatch, *, idle: float, hard: float = 60.0) -> None:
    """把两把表都拨小。空闲那把仍叫原来的名字,只是语义换成了「没有进展」。"""
    monkeypatch.setattr(pi_client, "TURN_TIMEOUT_SECONDS", idle)
    monkeypatch.setattr(pi_client, "TURN_HARD_CAP_SECONDS", hard, raising=False)


def _run(*, on_tool=None) -> pi_client.TurnResult:
    return pi_client._run_pi(
        "hi",
        "system",
        "http://127.0.0.1:1",
        "token",
        "ws",
        {"base_url": "http://x/v1", "api_key": "k", "vendor": "v"},
        "m",
        None,
        None,
        on_tool,
    )


def test_一直在干活的一轮不会被空闲超时杀掉(tmp_path, monkeypatch) -> None:
    """① 持续有进展(间隔远小于空闲上限)跑过「600 秒」那一档 —— 仍然活着并正常收尾。

    打桩后这一轮要发 16 次工具事件,间隔 0.15 秒;空闲上限是 0.5 秒。修复前它量的是总时长,
    0.5 秒一到就杀,测试只能收到前几次事件 —— 所以判据数事件,不量挂钟。
    """
    _install_fake_sidecar(tmp_path, monkeypatch, BUSY_SIDECAR)
    _stub_timeouts(monkeypatch, idle=0.5)

    seen: list[dict] = []
    result = _run(on_tool=seen.append)

    assert result.text == "做完了"
    assert len(seen) >= 12, f"只收到 {len(seen)} 次工具事件 —— 这一轮在进展中途被杀掉了"


def test_没有进展的一轮会在空闲上限到点被杀且说清楚是没有进展(tmp_path, monkeypatch) -> None:
    """② 连续 0.4 秒没有任何进展 → 终止,文案说的是「连续 … 没有任何进展」。"""
    _install_fake_sidecar(tmp_path, monkeypatch, SILENT_SIDECAR)
    _stub_timeouts(monkeypatch, idle=0.4)

    with pytest.raises(pi_client.SidecarError) as caught:
        _run()

    human = caught.value.human
    assert "连续 0.4 秒没有任何进展" in human
    assert "运行超过" not in human, "空闲超时不该再说成「运行超过 N 秒」"


def test_有进展但总时长超过硬上限才说运行超过多少小时(tmp_path, monkeypatch) -> None:
    """③ 一直在动,但总时长越过硬上限 → 终止,文案明说上限,且不冒充空闲超时。"""
    _install_fake_sidecar(tmp_path, monkeypatch, BUSY_SIDECAR)
    #: 空闲上限比整段活动长(每 0.15 秒一次进展),只有硬上限会先到。
    _stub_timeouts(monkeypatch, idle=5.0, hard=0.6)

    with pytest.raises(pi_client.SidecarError) as caught:
        _run()

    human = caught.value.human
    assert "运行超过" in human and "小时" in human
    assert "连续" not in human, "硬上限不该冒充「没有进展」"
    assert f"{0.6 / 3600:g} 小时" in human, "要明说是哪个上限"


def test_失败卡里说得出最后一步是哪个工具(tmp_path, monkeypatch) -> None:
    """④ 停之前最后做过什么,要跟着失败气泡一起出来 —— 用户才看得出「最后停在哪」。"""
    _install_fake_sidecar(tmp_path, monkeypatch, TOOL_THEN_SILENT_SIDECAR)
    _stub_timeouts(monkeypatch, idle=0.4)

    with pytest.raises(pi_client.SidecarError) as caught:
        _run()

    assert "最后一步" in caught.value.human
    assert "update_plan" in caught.value.human


def test_两种超时的英文文案也分开() -> None:
    """中英都要分开说 —— 英文界面里不能再出现「ran for more than 600 seconds」。"""
    step = {"__key": "agentTurn_lastStepTool", "params": {"name": "update_plan"}}
    idle = t("aiErr_turnIdleTimeout", "en", seconds=600, last_step=step)
    hard = t("aiErr_turnHardCap", "en", hours=2, last_step=step)

    assert "No progress for 600 seconds" in idle
    assert "more than 600 seconds" not in idle
    assert "more than 2 hours" in hard
    assert "No progress" not in hard


def test_默认的六百秒空闲与两小时硬上限不变() -> None:
    """数值没变:空闲 600 秒;新增的硬上限是 2 小时。"""
    assert pi_client.TURN_TIMEOUT_SECONDS == 600
    assert pi_client.TURN_HARD_CAP_SECONDS == 2 * 60 * 60

    step = {"__key": "agentTurn_lastStepNone", "params": {}}
    zh_idle = t("aiErr_turnIdleTimeout", "zh", seconds=600, last_step=step)
    zh_hard = t("aiErr_turnHardCap", "zh", hours=2, last_step=step)
    assert "连续 600 秒没有任何进展" in zh_idle
    assert "运行超过 2 小时" in zh_hard


def _session_on_a_public_provider(client) -> str:
    """和 `_session` 同一条路,但连接地址是公网主机 —— `_provider_frame` 会拒绝回环地址。

    这一轮的假 sidecar 根本不连供应商,地址只为过出站检查。
    """
    session_id = _session(client)
    from app.core.db import SessionLocal
    from app.db.models import ProviderProfile

    with SessionLocal() as db:
        for profile in db.query(ProviderProfile).all():
            profile.base_url = "https://example.com/v1"
        db.commit()
    return session_id


def test_失败气泡真的带出最后一步(tmp_path, monkeypatch) -> None:
    """从 API 走到落库那一层:失败消息的 content 就是用户看到的那张卡。"""
    _install_fake_sidecar(tmp_path, monkeypatch, TOOL_THEN_SILENT_SIDECAR)
    monkeypatch.setattr(pi_client, "TURN_HARD_CAP_SECONDS", 60.0, raising=False)
    monkeypatch.setattr(pi_client, "TURN_TIMEOUT_SECONDS", 0.4, raising=False)

    client = fresh_client()
    session_id = _session_on_a_public_provider(client)
    assert client.post(f"/api/agent/sessions/{session_id}/messages", json={"content": "跑一下"}).status_code == 200
    _wait_idle(session_id)

    messages = client.get(f"/api/agent/sessions/{session_id}/messages").json()
    failed = messages[-1]
    assert failed["role"] == "assistant"
    assert "连续 0.4 秒没有任何进展" in failed["content"]
    assert "最后一步" in failed["content"]
    assert "update_plan" in failed["content"]
    assert failed["error"] and "update_plan" in failed["error"]
    # 这一轮的过程仍然留在 payload 里(失败不是取消,也不是静默)。
    assert failed["payload"]["timeline"], "失败轮的工具轨迹不该消失"


def test_英文界面下的失败气泡也是英文(tmp_path, monkeypatch) -> None:
    _install_fake_sidecar(tmp_path, monkeypatch, SILENT_SIDECAR)
    _stub_timeouts(monkeypatch, idle=0.4)

    with speaking("en"):
        with pytest.raises(pi_client.SidecarError) as caught:
            _run()

    assert "No progress for 0.4 seconds" in caught.value.human
