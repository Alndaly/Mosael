"""管理 → 引擎 → 降噪:三种实现上可以设**这台机器**的默认。

**两层,不能互相代替(和转写那条同一条规则):**

- **部署默认**(管理 → 引擎 → 降噪,部署级):这台机器默认用哪一种;只有部署管理员能改,和装引擎
  同一道门。它落在 `DenoiseConfig.default_engine` 上。
- **按人选的**(设置 → 能力提供方 → 降噪):某个人自己定过的那一家。他是更具体的一个人,压过部署
  默认;部署默认只补"他没选过"的那一半。

实际生效的值**只有一处**算:`domain/denoise_defaults.resolve_denoise_engine()`。所有降噪入口都
经过 `domain/assets/denoise.ready_adapter`,所以管理页写着的和真跑起来的永远是同一个答案。

设默认时**必须已经装好**:没装的设成默认,"默认"就是一句空话 —— 下一次降噪照样得先下载。
不认识的 id 直接拒。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import User
from tests.util import fresh_client, second_client

FFMPEG = "builtin:ffmpeg"
DEEPFILTER = "builtin:deepfilternet"
RNNOISE = "builtin:rnnoise"


def _client():
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    return client


def _me() -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == "tester").one().id


def _set_default(client, engine: str):
    """设这台机器的默认降噪引擎。"""
    return client.put("/api/settings/denoise", json={"engine": engine})


def _rows(client):
    reply = client.get("/api/denoise/engines")
    assert reply.status_code == 200, reply.text
    return reply.json()


def _defaults(client) -> list[str]:
    return [row["engine"] for row in _rows(client) if row["is_default"]]


def _choose_personal(client, provider_id: str):
    """这个人在「设置 → 能力提供方 → 降噪」里选的那一家。"""
    reply = client.put("/api/settings/capabilities/audio_denoise", json={"provider_id": provider_id})
    assert reply.status_code == 200, reply.text
    return reply.json()


@pytest.fixture
def deepfilter_installed(tmp_path, monkeypatch):
    """让 DeepFilterNet 看起来已经下载好。

    判据本身就是"那个文件在不在"(见 ai/runtime/denoise_models.deepfilter_ready);这里只把「装到哪」
    挪进 tmp_path,再放一个文件 —— 不替实现回答"装好了没有"。
    """
    from app.ai.runtime import denoise_models as dm

    monkeypatch.setattr(dm, "MANAGED_DENOISE_ROOT", tmp_path / "denoise")
    dm.deepfilter_ready.cache_clear()
    dm.deepfilter_path().parent.mkdir(parents=True, exist_ok=True)
    dm.deepfilter_path().write_bytes(b"deep-filter-test")
    yield dm
    dm.deepfilter_ready.cache_clear()


def _resolve(engine: str = "") -> str:
    """唯一那个解析点的答案。"""
    from app.domain.denoise_defaults import resolve_denoise_engine

    with SessionLocal() as db:
        return resolve_denoise_engine(db, _me(), explicit=engine)


def _adapter_engine(engine: str = "") -> str:
    """真的会给这一次降噪用的引擎 id(走执行入口那一个函数)。"""
    from app.domain.assets.denoise import ready_adapter

    with SessionLocal() as db:
        return ready_adapter(db, _me(), engine).engine_id


# ---------------------------------------------------------------------------
# ① 能设默认;未安装的设不了;不认识的 id 直接拒;只有部署管理员能改
# ---------------------------------------------------------------------------
def test_能设默认_列表里标出来() -> None:
    client = _client()

    reply = _set_default(client, FFMPEG)

    assert reply.status_code == 200, reply.text
    assert reply.json()["engine"] == FFMPEG
    assert reply.json()["is_default"] is True
    assert _defaults(client) == [FFMPEG]


def test_deepfilternet装好之后能设成默认(deepfilter_installed) -> None:
    client = _client()

    reply = _set_default(client, DEEPFILTER)

    assert reply.status_code == 200, reply.text
    assert reply.json()["is_default"] is True
    assert _defaults(client) == [DEEPFILTER]


def test_未安装的引擎设不了默认_而且不留下半份设置() -> None:
    """没装的设成默认,"默认"就是一句空话 —— 下一次降噪照样得先下载。"""
    client = _client()

    reply = _set_default(client, DEEPFILTER)

    assert reply.status_code == 409, reply.text
    #: 人话:说清是"还没装",并且指向下一步(下载)。
    assert "下载" in reply.json()["detail"], reply.json()["detail"]
    assert _defaults(client) == []


def test_不认识的引擎id直接拒() -> None:
    client = _client()

    reply = _set_default(client, "builtin:no-such-engine")

    assert reply.status_code == 404, reply.text
    #: 不是一句光秃秃的 Not Found:说清是哪一类东西不认识(和"路由不存在"要分得开)。
    assert "降噪引擎" in reply.json()["detail"], reply.json()["detail"]


def test_只有部署管理员能改默认() -> None:
    """默认是**这台机器**的设定(和装引擎同一类),所以和装引擎一样只给部署管理员。"""
    _client()
    member = second_client("member")

    assert _set_default(member, FFMPEG).status_code == 403
    assert member.get("/api/denoise/engines").status_code == 200


# ---------------------------------------------------------------------------
# ② 一处解析,优先级:按人选的 > 部署默认 > 内置兜底
# ---------------------------------------------------------------------------
def test_按人选的压过部署默认() -> None:
    """他在「能力提供方 → 降噪」点过的那一家是**他做的选择**,部署默认只补"他没选过"的那一半。"""
    client = _client()
    assert _set_default(client, FFMPEG).status_code == 200

    #: 选 RNNoise(不是"不定时本来就会用的"内置降噪),所以它是一次真的选择、会被存下来。
    _choose_personal(client, RNNOISE)

    assert _resolve() == RNNOISE


def test_部署默认压过内置兜底(deepfilter_installed) -> None:
    client = _client()
    assert _set_default(client, DEEPFILTER).status_code == 200

    #: 没人在能力提供方里选过,所以这一次用部署默认 —— 不是"第一个跑得起来的内置引擎"。
    assert _resolve() == DEEPFILTER
    assert _adapter_engine() == "deepfilternet"


def test_没设默认时还是第一个跑得起来的内置引擎() -> None:
    """不设默认 = 和这一格出现之前完全一致(内置降噪)。"""
    _client()

    assert _resolve() == ""
    assert _adapter_engine() == "ffmpeg"


# ---------------------------------------------------------------------------
# ③ 行为回归:有了部署默认,按人选择和点名那套照旧;降噪执行链没改
# ---------------------------------------------------------------------------
def test_部署默认不改点名的那一家(deepfilter_installed) -> None:
    """工作流节点 / 「用××重新降噪」点名的是提供方 id:那是一次明确的指派,默认不该改写它。"""
    client = _client()
    assert _set_default(client, DEEPFILTER).status_code == 200

    assert _adapter_engine(FFMPEG) == "ffmpeg"


def test_部署默认不改按人选择那套(deepfilter_installed) -> None:
    """「能力提供方 → 降噪」存的东西原样还在;选「自动」照旧是清掉这个人自己的选择。"""
    from app.domain import capabilities
    from app.domain.audio_capabilities import DENOISE

    client = _client()
    assert _set_default(client, DEEPFILTER).status_code == 200
    _choose_personal(client, RNNOISE)
    with SessionLocal() as db:
        assert capabilities.default_id(db, _me(), DENOISE) == RNNOISE
    #: 解析那一步认的就是他选的那一家(RNNoise 在这台机器上能不能跑是另一条判据,不在这里替它答)。
    assert _resolve() == RNNOISE

    #: 选回「不定时本来就会用的」内置降噪 = 清掉个人选择,回到部署默认。
    _choose_personal(client, "")
    with SessionLocal() as db:
        assert capabilities.default_id(db, _me(), DENOISE) is None
    assert _adapter_engine() == "deepfilternet"


# ---------------------------------------------------------------------------
# ④ 一处解析:有效引擎只能由一个函数决定
# ---------------------------------------------------------------------------
def test_有效引擎只有一处解析() -> None:
    """`DenoiseConfig` 只在 domain/denoise_defaults 里读写;`resolve_denoise_engine` 只在
    `ready_adapter` 里调一次。

    任何一个入口自己再算一遍,迟早给出两个答案 —— 管理页写着一个、降噪用的是另一个,
    而用户看到的是"设了却没生效"。
    """
    app_root = Path(__file__).resolve().parents[1] / "app"
    readers = sorted(
        str(path.relative_to(app_root)) for path in app_root.rglob("*.py") if "DenoiseConfig" in path.read_text()
    )
    #: ownership 只是归属地图上的一笔(它不读值),另外三处是模型定义、模型出口和那一个解析点。
    assert readers == [
        "db/model_slices/runtime_config.py",
        "db/models.py",
        "domain/denoise_defaults.py",
        "domain/ownership.py",
    ], readers

    denoise_source = (app_root / "domain/assets/denoise.py").read_text()
    assert denoise_source.count("resolve_denoise_engine(") == 1
