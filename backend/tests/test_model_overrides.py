"""按模型的手动覆盖。

模型的上下文窗口/是否推理模型/认不认图片决定了我们怎么发请求,而唯一来源是供应商目录 ——
它经常不给(自定义模型名、别名、私有部署),给了也可能不准。取不到只能退回保守的 32000,
于是 128k 的模型被按 32k 用。

每条断言对应一个具体的坏结果:
  只存改过的键 → 否则目录更新永远追不上这份快照;
  空覆盖删条目 → 否则"有没有覆盖"变成"有键但里面是空的",下游每处都要多写一次判空;
  夹取下限     → 填成 0 会让每一轮都触发压缩。
"""

from __future__ import annotations

from app.domain import model_overrides
from tests.util import fresh_client


def test_只保留认识的键():
    values = model_overrides.normalize({"context_window": 128000, "vision": True, "随手加的": "x"})
    assert values == {"context_window": 128000, "vision": True}


def test_没传的键不落库():
    """全量落库会让目录更新永远追不上这份快照:端点把窗口从 32k 提到 128k,
    库里那份旧值仍按 32k 用,而用户根本没改过任何东西。"""
    assert model_overrides.normalize({"vision": True}) == {"vision": True}


def test_null_与空串是清除():
    assert model_overrides.normalize({"context_window": None, "vision": ""}) == {}


def test_上下文窗口夹在合法区间():
    assert model_overrides.normalize({"context_window": 0})["context_window"] == model_overrides.MIN_CONTEXT_WINDOW
    assert model_overrides.normalize({"context_window": 10**12})["context_window"] == model_overrides.MAX_CONTEXT_WINDOW
    assert model_overrides.normalize({"context_window": "abc"}) == {}


def test_空覆盖把整条删掉而不是留空对象():
    base = {"m1": {"vision": True}, "m2": {"context_window": 8192}}
    assert model_overrides.put(base, "m1", {}) == {"m2": {"context_window": 8192}}


def test_端到端_写入后来源标成_override():
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    resp = client.post(
        "/api/settings/providers",
        json={"name": "本地", "vendor": "openai-compatible", "config": {"base_url": "http://127.0.0.1:1/v1", "api_key": "k", "default_model": "my-model"}},
    )
    assert resp.status_code == 200, resp.text
    created = resp.json()

    # 端点连不上 → 目录取不到 → 来源是 fallback,且没有数值可给
    before = client.get(f"/api/settings/providers/{created['id']}/models/my-model/settings").json()
    assert before["context_window_source"] == "fallback"

    after = client.put(
        f"/api/settings/providers/{created['id']}/models/my-model/settings",
        json={"context_window": 128000, "vision": True},
    ).json()
    assert after["context_window"] == 128000
    assert after["context_window_source"] == "override"
    assert after["vision"] is True
    # 没设过的高级项保持 None(= 跟随保守默认),不能被写成 False
    assert after["reasoning"] is None

    cleared = client.put(
        f"/api/settings/providers/{created['id']}/models/my-model/settings",
        json={"context_window": None, "vision": None},
    ).json()
    assert cleared["context_window_source"] == "fallback"
