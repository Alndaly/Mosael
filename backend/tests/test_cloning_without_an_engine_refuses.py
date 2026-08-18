"""装不上引擎的时候,本地克隆要**说它跑不了**,而不是发一段占位音出来。

用户的话是「本地音色克隆现在有很大问题 根本克隆不了」。而任务列表里每一条都是"成功"。

这台机器上的实际情况:

    probe_interpreter('f5-tts') → {'worker_ready': False}      ← 设置页据此显示"未就绪"
    resolve_tts_python('f5_tts') → backend/.venv/bin/python    ← 合成据此照跑不误

同一个问题两处回答,于是两个答案。合成拿着后一个答案跑进 worker,worker 发现 `import f5_tts`
失败,就写了一段**按文本长度估算时长的正弦音**当结果,报 `engine: placeholder`;宿主把任务标成
`succeeded`,把这段音注册成音频素材放进素材库,唯一的痕迹是任务消息末尾一句括号。

于是用户拖到时间线上、播放,听到的是"嘟——",而不是自己的声音。**它不是没成功,它是假装成功了。**

判据:引擎跑不了是**建任务之前**就知道的事(探测一次解释器即可),那就在那个时候说;
说不了的时候不要给一个听起来像结果的东西。
"""

from __future__ import annotations

import io
import wave

import pytest

from app.audio import tts_models, voices
from app.domain import tts_config
from app.core.db import SessionLocal
from app.db.models import Job
from tests.util import fresh_client


#: 8 秒:够得着参考音频的下限(见 voices.REFERENCE_MIN_SECONDS)。此前这里是 1 秒,
#: 而那正是用户那条 2.6 秒音色的同类 —— 测试用的夹具比真实要求还宽,下限就测不出来。
def _tiny_wav(seconds: int = 8) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000 * seconds)
    return buf.getvalue()


def _a_voice(client) -> tuple[str, str]:
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    voice = client.post(
        "/api/voices/upload",
        data={"workspace_id": workspace_id, "name": "小明", "reference_text": "你好世界"},
        files={"file": ("ref.wav", _tiny_wav(), "audio/wav")},
    ).json()
    return workspace_id, voice["id"]


def test_it_refuses_before_creating_a_job(monkeypatch) -> None:
    """跑不了就当场说 —— 起一个注定发占位音的任务,等于把这句话藏进任务列表。"""
    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: None)
    client = fresh_client()
    _, voice_id = _a_voice(client)

    with SessionLocal() as db:
        before = db.query(Job).count()
        with pytest.raises(voices.VoiceError) as caught:
            voices.start_synthesis(db, text="这是一段测试配音。", project_id=None, created_by=None, voice_id=voice_id)
        assert db.query(Job).count() == before, "已经起了一个注定发占位音的任务"

    message = str(caught.value)
    assert "引擎" in message, f"没说清缺的是本地引擎:{message}"
    assert "*" not in message, f"纯文本界面里出现了 markdown:{message}"


def test_the_api_says_so_too(monkeypatch) -> None:
    """走接口也是同一句话,不是 500,也不是一个"成功"的任务。"""
    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: None)
    client = fresh_client()
    _, voice_id = _a_voice(client)

    resp = client.post(f"/api/voices/{voice_id}/synthesize", json={"text": "这是一段测试配音。"})

    assert resp.status_code == 422, resp.text  # 仓库里 VoiceError 一律 422
    assert "引擎" in resp.json()["detail"]


def test_one_question_one_answer(monkeypatch) -> None:
    """「哪个解释器能跑这个引擎」只有一处实现 —— 设置页和合成必须拿到同一个答案。

    此前是两处:探测说"没有",解析说"就用后端自己这个" —— 合成于是照跑,跑出占位音。
    """
    monkeypatch.setattr(tts_models, "candidate_pythons", lambda engine_id: [])  # 一个候选都没有

    assert tts_models.resolve_engine_python("f5-tts") is None
    # 探测是后台跑的(起子进程 import f5_tts,实测 7 秒),所以这里先探一次拿到确定的答案 ——
    # 否则读到的是「还没测过」,而这条测试要钉的是"测过之后两边说同一句话"。
    tts_models.refresh_runtime_status("f5-tts")
    probed = tts_models.probe_interpreter("f5-tts")
    assert probed["worker_ready"] is False and probed["worker_python"] == ""
    assert probed["worker_checked"] is True


def test_the_worker_no_longer_invents_audio(tmp_path) -> None:
    """引擎导不进来时,worker 报错,不写一段正弦音冒充结果。"""
    out = tmp_path / "out.wav"

    with pytest.raises(Exception):
        voices_worker_synthesize(out)

    assert not out.exists(), "引擎没跑起来却留下了一个 wav —— 它会被注册成素材"


def voices_worker_synthesize(out) -> None:
    from app.audio import tts_worker

    tts_worker.synthesize({"engine": "f5-tts", "text": "你好,测试一段语音合成。"}, str(out))


def test_the_engine_picker_says_it_up_front(monkeypatch) -> None:
    """挑引擎的那一刻就说清楚 —— 而不是等他填完文本、点了生成才拒绝。"""
    from app.audio import tts_providers

    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: None)
    tts_models.clear_runtime_probes()
    tts_models.refresh_runtime_status(tts_config.get().engine)
    clone = next(row for row in tts_providers.describe_engines() if row["id"] == "clone")
    assert clone["ready"] is False
    # 目录里存的是 key(见 core/i18n:领域数据不必知道语言),出口才翻。这里断言的是**说了哪句**,
    # 而不是那句话长什么样 —— 换个说法或者加一种语言都不该让这条用例红。
    assert clone["note"] == "ttsProviderNote_cloneMissing"

    # 探测挪到后台之后,引擎列表读的是缓存(它不该卡在 import torch 上,见
    # test_status_endpoints_do_not_probe_inline)。换了答案就显式重探一次。
    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: "/usr/bin/python3")
    tts_models.clear_runtime_probes()
    tts_models.refresh_runtime_status(tts_config.get().engine)
    clone = next(row for row in tts_providers.describe_engines() if row["id"] == "clone")
    assert clone["ready"] is True
    assert "下载" not in clone["note"]


def test_installing_invalidates_the_probe(monkeypatch) -> None:
    """探测带缓存(每个候选解释器一次子进程,不便宜),那就必须有人负责作废 ——
    否则用户装完引擎回到面板,它还在说"没装"。"""
    calls: list[str] = []

    def counting(engine_id: str) -> str | None:
        calls.append(engine_id)
        return None  # None = 资源不齐 → 直接不就绪,不起子进程

    monkeypatch.setattr(tts_models, "_probe_code", counting)
    tts_models.clear_runtime_probes()

    tts_models.resolve_engine_python("f5-tts")
    tts_models.resolve_engine_python("f5-tts")
    assert calls == ["f5-tts"], f"第二次没走缓存:{calls}"

    tts_models.clear_runtime_probes()
    tts_models.resolve_engine_python("f5-tts")
    assert calls == ["f5-tts", "f5-tts"], "作废之后没有重算 —— 装完引擎的人会一直看到旧答案"

    tts_models.clear_runtime_probes()


def test_installed_does_not_mean_runnable(monkeypatch) -> None:
    """权重下齐了 ≠ 跑得起来。

    这是转写那边刚踩过的同一个坑:模型页按**盘上的字节数**说「已安装」,而能不能跑取决于
    **有没有解释器装了这个包**。两者可以一真一假(权重是别的工具下的、托管 venv 被删了),
    于是页面说"声音克隆可用",一点合成却说"没有可用的引擎"。
    """
    monkeypatch.setattr(tts_models, "_is_installed", lambda engine: True)
    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: None)

    tts_models.refresh_runtime_status("f5-tts")
    row = tts_models.get_status("f5-tts")

    assert row["status"] == "installed"  # 字节数说的
    assert row["runtime_ready"] is False  # 解释器说的
    assert "可用" not in row["message"], f"权重齐了就说可用 —— 而它跑不了:{row['message']}"


def test_installed_and_runnable_says_so(monkeypatch) -> None:
    monkeypatch.setattr(tts_models, "_is_installed", lambda engine: True)
    monkeypatch.setattr(tts_models, "resolve_engine_python", lambda engine_id: "/usr/bin/python3")

    # 探测现在是**后台**跑的(列状态不该卡在 import torch 上,见
    # test_status_endpoints_do_not_probe_inline)。要一个确定答案就显式探一次。
    tts_models.refresh_runtime_status("f5-tts")
    row = tts_models.get_status("f5-tts")

    assert row["runtime_ready"] is True
    # 同上:领域里存 key,出口才翻。断言"说了哪句",不断言那句长什么样。
    assert row["message"] == "modelMsg_cloneReady"
