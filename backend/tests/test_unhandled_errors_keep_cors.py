"""后端抛了没接住的异常,浏览器也要能读到那个 500。

Starlette 最外层的 ServerErrorMiddleware 在 CORS 外面 —— 它回的 500 不带
Access-Control-Allow-Origin,浏览器连状态码都不给页面看,fetch 直接失败,前端只能说
「127.0.0.1:8800 连不上」。线上 Blender「发送当前场景」因为一个 AttributeError 连着这么
报了好几次,而后端一直好好的。AnswerCrashes 在 CORS 里面把它答成一个普通的 JSON 500。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_an_unhandled_error_is_a_readable_500_with_cors():
    app = create_app()

    @app.get("/api/__boom")
    def boom():
        raise AttributeError("'Scene3DModel' object has no attribute 'scene_id'")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/api/__boom", headers={"Origin": "http://localhost:5173", "Accept-Language": "en-US"})
    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "backend hit an error" in r.json()["detail"]
    # 异常本身不外泄给页面(它可能带着路径、表名);堆栈在后端日志里。
    assert "scene_id" not in r.text
