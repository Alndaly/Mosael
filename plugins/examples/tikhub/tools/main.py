"""TikHub — 抖音 / TikTok / 小红书 / B站 / 快手等平台的公开数据。

协议同其它插件:stdin 一个 JSON 请求 {"tool": name, "input": {...}},stdout 一个 JSON 响应。

**为什么只给一个通用的 tikhub_fetch,而不是几十个专用工具**:TikHub 跨十几个平台、上百个
端点,而且各平台的 App/Web 版本还在迭代(抖音已经到 App V3)。在这里抄一份端点清单,等于
把一个每月都在变的东西冻在插件里 —— 它会烂,而且烂得很安静。path 直接取自 TikHub 自己的
文档,那份永远是最新的。

**Key 从插件目录的 config.json 读**,不从环境变量:Open Studio 的插件运行时只透传
PATH/HOME/LANG(见 backend/app/domain/plugins/runtime.py),这是有意的隔离 —— 插件拿不到
应用的任何凭据。代价是插件自己的凭据也得自己管。config.json 已在 .gitignore 里。

只允许 GET。TikHub 也有写类接口(下单、投放),但一个"读数据"的插件不该顺手具备那些能力 ——
真要用,那属于另一个插件、另一次授权。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
DEFAULT_BASE = "https://api.tikhub.io"
TIMEOUT_SECONDS = 20
#: 单次响应上限。运行时本身有 1MB 的 stdout 封顶,这里先一步截断并说清楚,
#: 而不是让调用方收到一个被砍断的 JSON。
MAX_BYTES = 800_000


def _config() -> dict:
    if not CONFIG_PATH.is_file():
        raise ValueError(
            f"没有找到 {CONFIG_PATH.name}:把 config.example.json 复制成 config.json 并填入 TikHub API Key"
        )
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    key = str(data.get("api_key") or "").strip()
    if not key or key.startswith("把你的"):
        raise ValueError("config.json 里的 api_key 还没填")
    return {"api_key": key, "base_url": str(data.get("base_url") or DEFAULT_BASE).rstrip("/")}


def _get(path: str, params: dict) -> dict:
    config = _config()
    if not path.startswith("/"):
        path = "/" + path
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    url = f"{config['base_url']}{path}" + (f"?{query}" if query else "")
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {config['api_key']}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = exc.read(2000).decode("utf-8", "replace")
        # 把 401/403 单独说清楚 —— 这两个几乎总是 Key 的问题,而不是路径写错。
        if exc.code in (401, 403):
            raise ValueError(f"TikHub 拒绝了这次调用({exc.code}),多半是 API Key 无效或额度用尽:{detail[:300]}")
        raise ValueError(f"TikHub 返回 {exc.code}:{detail[:300]}")
    except urllib.error.URLError as exc:
        raise ValueError(f"连不上 TikHub({config['base_url']}):{exc.reason}")
    if len(raw) > MAX_BYTES:
        raise ValueError("响应过大,请用接口自带的分页/字段参数缩小范围")
    return json.loads(raw.decode("utf-8", "replace"))


def tikhub_fetch(payload: dict) -> dict:
    path = str(payload.get("path") or "").strip()
    if not path:
        raise ValueError("path 不能为空;端点见 https://docs.tikhub.io")
    params = payload.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError("params 必须是键值对")
    return {"path": path, "data": _get(path, params)}


def tikhub_quota(_payload: dict) -> dict:
    """额度自查。放一个专门的工具而不是让人去猜路径 —— "配好没有"是第一个要回答的问题。"""
    return {"data": _get("/api/v1/tikhub/user/get_user_info", {})}


TOOLS = {"tikhub_fetch": tikhub_fetch, "tikhub_quota": tikhub_quota}


def main() -> None:
    try:
        request = json.loads(sys.stdin.read())
        tool = TOOLS.get(str(request.get("tool")))
        if tool is None:
            raise ValueError(f"unknown tool: {request.get('tool')}")
        json.dump({"ok": True, "output": tool(request.get("input") or {})}, sys.stdout, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — report, don't crash silently
        json.dump({"ok": False, "error": str(exc)}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
