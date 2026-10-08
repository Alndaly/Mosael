"""棘轮:**路由里写死的报错原文(`HTTPException(detail="…")`)只减不增。**

路由里直接写的报错用 `tr("key")`,按这次请求的语言翻(见 test_route_and_plugin_errors_follow_the_ui_language)。那条测试只抽查
几处,而全仓还躺着三十多处写死的英文:英文界面里没事,中文界面里冒出「Current password is incorrect」。这里按文件数
`app/api` 下 detail 是字符串字面量(含 f-string)的 `HTTPException`,和下面的表对不上就红:

- 新加一处 → 红。用 `tr`,在 `app/core/messages/routes.py` 里加 key(中英各一份)。
- 改掉一处 → 也红,把表里的数改小 —— 表只能往下走,不然它会变成谁都能往里加的白名单。

剩下的大多是给执行器、`<img>` / `<video>` 这类不会把原文给人看的调用方的(缩略图、代理、工作者通道)。
"""

from __future__ import annotations

import ast
import pathlib

RATCHET = True

API = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"

#: 文件(相对 app/api)→ 写死原文的 HTTPException 有几处。只减不增。
FROZEN = {
    "deps/__init__.py": 1,
    "deps/auth.py": 4,
    "routes/agent_tools.py": 1,
    "routes/assets.py": 12,
    "routes/auth.py": 4,
    "routes/browser_worker.py": 1,
    "routes/confirmations.py": 1,
    "routes/documents.py": 1,
    "routes/fonts.py": 1,
    "routes/publish_worker.py": 2,
    "routes/sequences.py": 3,
    "routes/settings/provider_pricing.py": 1,
}


def literal_details(source: str) -> int:
    """这段源码里 detail 是写死的字符串(字面量或 f-string)的 HTTPException 有几处。`tr(...)`、`str(exc)` 不算。"""
    count = 0
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or (getattr(node.func, "id", "") or getattr(node.func, "attr", "")) != "HTTPException":
            continue
        for keyword in node.keywords:
            value = keyword.value
            if keyword.arg == "detail" and (
                isinstance(value, ast.JoinedStr) or (isinstance(value, ast.Constant) and isinstance(value.value, str))
            ):
                count += 1
    return count


def test_写死的报错原文只减不增() -> None:
    current = {}
    for path in sorted(API.rglob("*.py")):
        found = literal_details(path.read_text(encoding="utf-8"))
        if found:
            current[path.relative_to(API).as_posix()] = found
    grew = {name: (FROZEN.get(name, 0), count) for name, count in current.items() if count > FROZEN.get(name, 0)}
    assert not grew, (
        "这些文件里写死的报错原文变多了(表里的数 → 现在):"
        + ";".join(f"{name} {was} → {now}" for name, (was, now) in sorted(grew.items()))
        + "。路由里的报错用 tr(\"key\"),key 加在 app/core/messages/routes.py。"
    )
    shrank = {name: (count, current.get(name, 0)) for name, count in FROZEN.items() if current.get(name, 0) < count}
    assert not shrank, (
        "这些文件里写死的原文少了,把表里的数改小:"
        + ";".join(f"{name} {was} → {now}" for name, (was, now) in sorted(shrank.items()))
    )


def test_数法本身() -> None:
    source = '''
from fastapi import HTTPException
raise HTTPException(status_code=404, detail="Not found")
raise HTTPException(404, detail=f"Tool {name} not found")
raise HTTPException(status_code=404, detail=tr("routeErr_x"))
raise HTTPException(status_code=422, detail=str(exc))
raise HTTPException(status_code=409, detail={"code": "x"})
'''
    assert literal_details(source) == 2


def test_改掉的几处按读的人的语言说() -> None:
    from tests.util import fresh_client

    client = fresh_client()
    body = {"current_password": "wrong-password", "new_password": "new-pass-1234"}
    en = client.post("/api/auth/me/password", json=body, headers={"Accept-Language": "en-US"})
    assert (en.status_code, en.json()["detail"]) == (401, "The current password is incorrect.")
    zh = client.post("/api/auth/me/password", json=body, headers={"Accept-Language": "zh-CN"})
    assert zh.json()["detail"] == "当前密码不对"
