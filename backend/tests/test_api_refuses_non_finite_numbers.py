"""棘轮:**请求体里的数必须是有限的**,而这条要在进门那一层挡。

`NaN` / `Infinity` 不是合法 JSON(RFC 8259 里没有它们),但 Python 的 json 认,pydantic 对
float 字段默认也放行。于是每一个 float 字段都是一个入口 —— 全后端七十个。

进来之后的代价不对称,而且发作得很晚:存下的 NaN 序列化回去是 `{"x": NaN}`,浏览器
`JSON.parse` 直接抛,那张画板、那条时间线从此打不开(而库里的数据其实完好);
`src_out = Infinity` 则是一段无限长的片段,会一路进到渲染计划里。

**用比较去挡是挡不住的。** 任何和 NaN 的比较都是 False,所以 `x < 0` / `x <= y` 这类判据
对 NaN 全部"满足"。画板和时间线两处都是这么漏的 —— 各自的校验函数看起来都在把关。

所以这里钉两件事:一个新 schema 不能绕过基类,以及那条路真的通到 HTTP 400/422。
"""

from __future__ import annotations

import importlib
import pkgutil

from pydantic import BaseModel

RATCHET = True


def _schema_classes() -> dict[str, type[BaseModel]]:
    import app.api.schemas as pkg

    found: dict[str, type[BaseModel]] = {}
    modules = [pkg] + [
        importlib.import_module(f"app.api.schemas.{info.name}") for info in pkgutil.iter_modules(pkg.__path__)
    ]
    for module in modules:
        for name, obj in vars(module).items():
            if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel:
                found.setdefault(obj.__qualname__, obj)
    return found


def test_每个_schema_都拒收非有限的数() -> None:
    from app.api.schemas.base import ApiModel

    leaky = sorted(
        name
        for name, cls in _schema_classes().items()
        if cls is not ApiModel and cls.model_config.get("allow_inf_nan") is not False
    )
    assert not leaky, (
        "这些 schema 仍然接受 NaN / Infinity —— 多半是直接继承了 BaseModel。"
        f"改成继承 app.api.schemas.base.ApiModel:\n  {leaky}"
    )


def test_真的通到接口上() -> None:
    """光看 model_config 不够 —— 要确认这条路真的把请求挡在门外,而不是在某一层被吞掉。"""
    from tests.util import fresh_client

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    board = client.post("/api/boards", json={"workspace_id": workspace_id, "name": "B"}).json()

    #: **声明为 float 的字段**由 schema 这一层挡下 —— 校验在进 handler 之前发生,所以
    #: asset_id 指向什么都不影响这一条。
    typed = client.post(
        f"/api/boards/{board['id']}/trim",
        content=(
            '{"workspace_id": "%s", "item_id": "i1", "asset_id": "a1", "start": NaN, "end": 5}' % workspace_id
        ),
        headers={"content-type": "application/json"},
    )
    assert typed.status_code == 422, f"声明为 float 的字段放进了 NaN(HTTP {typed.status_code})"

    #: 装在无类型 dict 里的数(画布 items)schema 管不到 —— 那一层由领域自己的
    #: `finite_number` 挡,回 400。两条路都要通,因为 NaN 从哪一条进来后果都一样。
    nested = client.patch(
        f"/api/boards/{board['id']}",
        content=(
            '{"workspace_id": "%s", "canvas": {"items": [{"id": "a", "kind": "note", "x": NaN, "y": 0}],'
            ' "edges": []}}' % workspace_id
        ),
        headers={"content-type": "application/json"},
    )
    assert nested.status_code == 400, f"画布里的 NaN 被放进来了(HTTP {nested.status_code})"

    # 正常的数照旧,别把好请求也拦了(负坐标合法:画布可以往左上延伸)。
    ok = client.patch(
        f"/api/boards/{board['id']}",
        json={
            "workspace_id": workspace_id,
            "canvas": {"items": [{"id": "a", "kind": "note", "x": 12.5, "y": -4}], "edges": []},
        },
    )
    assert ok.status_code == 200, ok.text


def test_拒绝的那一刻不能自己崩掉() -> None:
    """FastAPI 默认会把出错的原值回显进 422 的错误体,而 Starlette 用 allow_nan=False 编码
    —— 于是"请求里有个 NaN"的结局是编码器抛异常、客户端收到 500。

    一个**因为拒绝得对而崩掉**的响应比放行更难查:500 会让人以为服务端坏了,去看完全
    不相干的地方。所以这里既要 422,也要那个 422 真的能读。
    """
    from tests.util import fresh_client

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    board = client.post("/api/boards", json={"workspace_id": workspace_id, "name": "B"}).json()

    response = client.post(
        f"/api/boards/{board['id']}/trim",
        content='{"workspace_id": "%s", "item_id": "i", "asset_id": "a", "start": Infinity, "end": 5}'
        % workspace_id,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    body = response.json()  # 读得出来才算数
    # 原值仍然看得见,而且看得出是哪一种 —— 换成一句"不合法"的话,排查要靠猜。
    assert "inf" in str(body).lower()
    assert "start" in str(body)
