"""和一台 ComfyUI 说话:HTTP(标准库 urllib)。

插件进程跑在随应用发的那个 Python 上,只有标准库 —— 为了发几个请求装一个 httpx 不值得,
而 urllib 该有的都有:JSON 进出、multipart 上传(传参考图)、流式下载(取成片)。

**不走任何代理。** ComfyUI 在本机或局域网里;macOS 上 urllib 默认会读系统代理,而开着代理软件
的机器上,一个 192.168.x.x 的请求被送去代理只会换回一句莫名其妙的 502。
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from lines import ComfyError, say

#: 普通请求的上限。ComfyUI 的接口都是本地的、立即返回的;排队和生成不在这些请求里等。
TIMEOUT_SECONDS = 30.0
#: 下载成片的上限。一段几百 MB 的视频在局域网里也就几十秒。
DOWNLOAD_TIMEOUT_SECONDS = 600.0

#: 出错时最多读多少正文。
_MAX_ERROR_BODY = 1024 * 1024

_OPENER = request.build_opener(request.ProxyHandler({}))


class Comfy:
    """一台 ComfyUI 服务器。短命的:一次调用一个。"""

    def __init__(self, base_url: str, locale: str = "zh") -> None:
        base = (base_url or "").strip().rstrip("/")
        if not base:
            raise ComfyError(say(locale, "没填 ComfyUI 的服务器地址", "The ComfyUI server URL is empty"))
        if not base.startswith(("http://", "https://")):
            base = f"http://{base}"
        self.base = base
        self.locale = locale

    # --- 传输 -------------------------------------------------------------

    def _open(self, method: str, path: str, *, params: dict[str, Any] | None = None, body: bytes | None = None,
              headers: dict[str, str] | None = None, timeout: float = TIMEOUT_SECONDS):
        url = f"{self.base}{path}"
        if params:
            url = f"{url}?{parse.urlencode(params)}"
        req = request.Request(url, data=body, method=method, headers=headers or {})
        try:
            return _OPENER.open(req, timeout=timeout)
        except error.HTTPError:
            raise
        except (error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ComfyError(
                say(self.locale, f"连不上 ComfyUI({self.base}):{reason}。请确认它在运行、地址填对了",
                    f"Can't reach ComfyUI ({self.base}): {reason}. Make sure it is running and the URL is right")
            ) from exc

    def request_json(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                     body: Any = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        try:
            with self._open(method, path, params=params, body=data, headers=headers) as response:
                raw = response.read()
        except error.HTTPError as exc:
            raise self._http_error(exc) from exc
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise ComfyError(say(self.locale, f"ComfyUI 回了一段不是 JSON 的东西({path})",
                                 f"ComfyUI answered {path} with something that is not JSON")) from exc

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.request_json("GET", path, params=params)

    def post(self, path: str, body: Any) -> Any:
        return self.request_json("POST", path, body=body)

    def _http_error(self, exc: error.HTTPError) -> ComfyError:
        # 正文留全(调用方要解析它:/prompt 的校验错误带着整张可选值列表,动辄几 KB),给人看的那句才截短
        try:
            body = exc.read(_MAX_ERROR_BODY).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 — 正文读不出来也要把状态码说出来
            body = ""
        shown = body[:400] or exc.reason
        return ComfyError(say(self.locale, f"ComfyUI 回了 HTTP {exc.code}:{shown}",
                              f"ComfyUI answered HTTP {exc.code}: {shown}"), status=exc.code, body=body)

    # --- 接口 -------------------------------------------------------------

    def object_info(self) -> dict[str, Any]:
        """全部节点的定义(输入类型、可选值、上下界)。转换、描述参数都要它。"""
        info = self.get("/object_info")
        return info if isinstance(info, dict) else {}

    def list_workflows(self) -> list[str]:
        """用户在 ComfyUI 里**保存**的工作流(相对 workflows/ 的路径)。"""
        paths = [str(item.get("path")) for item in self.workflow_listing() if str(item.get("path") or "").endswith(".json")]
        return sorted(paths, key=str.lower)

    def fetch_workflow(self, path: str) -> dict[str, Any]:
        graph = self.get(f"/api/userdata/{parse.quote('workflows/' + path, safe='')}")
        if not isinstance(graph, dict):
            raise ComfyError(say(self.locale, f"工作流「{path}」不是一个 JSON 对象", f"Workflow “{path}” is not a JSON object"))
        return graph

    def workflow_listing(self) -> list[dict[str, Any]]:
        """保存的工作流连同大小和修改时间。**便宜** —— 只列目录,不取内容;判「有没有变」用它。"""
        items = self.get("/api/userdata", {"dir": "workflows", "recurse": "true", "split": "false", "full_info": "true"})
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    def system_stats(self) -> dict[str, Any]:
        stats = self.get("/system_stats")
        return stats if isinstance(stats, dict) else {}

    def queue(self) -> tuple[list[str], list[str]]:
        """(在跑的任务号, 排队的任务号)。"""
        queue = self.get("/queue") or {}

        def ids(entries: Any) -> list[str]:
            return [str(item[1]) for item in entries or [] if isinstance(item, list) and len(item) > 1]

        return ids(queue.get("queue_running")), ids(queue.get("queue_pending"))

    def history(self, prompt_id: str | None = None, *, max_items: int | None = None) -> dict[str, Any]:
        """一个任务的历史(`{任务号: 条目}`),或最近的几条(给了 `max_items`)。"""
        if prompt_id:
            found = self.get(f"/history/{parse.quote(prompt_id, safe='')}")
        else:
            found = self.get("/history", {"max_items": max_items} if max_items else None)
        return found if isinstance(found, dict) else {}

    def model_folders(self) -> list[str] | None:
        """服务器上有哪些模型目录(`/models`)。老版本没有这个接口 —— 回 None,调用方改看 object_info。"""
        try:
            found = self.get("/models")
        except ComfyError as exc:
            if exc.status == 404:
                return None
            raise
        return [str(one) for one in found] if isinstance(found, list) else None

    def models_in(self, folder: str) -> list[str]:
        found = self.get(f"/models/{parse.quote(folder, safe='')}")
        return [str(one) for one in found] if isinstance(found, list) else []

    def upload_image(self, source: Path, name: str) -> str:
        """把一份输入素材传进 ComfyUI 的 input 目录,返回读素材的节点该填的那个名字。

        图、视频、音频走的都是这一个接口(ComfyUI 自己的前端上传视频也用它)。"""
        boundary = f"----mosael{uuid.uuid4().hex}"
        parts: list[bytes] = []
        for key, value in (("overwrite", "true"), ("type", "input"), ("subfolder", "mosael")):
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode("utf-8")
            )
        parts.append(
            (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
             "Content-Type: application/octet-stream\r\n\r\n").encode("utf-8")
            + source.read_bytes()
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        try:
            with self._open("POST", "/upload/image", body=b"".join(parts), headers=headers) as response:
                answer = json.loads(response.read().decode("utf-8") or "{}")
        except error.HTTPError as exc:
            raise self._http_error(exc) from exc
        stored = str(answer.get("name") or name)
        subfolder = str(answer.get("subfolder") or "")
        return f"{subfolder}/{stored}" if subfolder else stored

    def download(self, item: dict[str, Any], target: Path) -> Path:
        """取回一份产出(`/view`),流式写到 `target`。"""
        params = {"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")}
        try:
            with self._open("GET", "/view", params=params, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                with target.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
        except error.HTTPError as exc:
            raise self._http_error(exc) from exc
        return target

    def ws_url(self, client_id: str) -> str:
        scheme = "wss" if self.base.startswith("https://") else "ws"
        host = self.base.split("://", 1)[1]
        return f"{scheme}://{host}/ws?clientId={parse.quote(client_id)}"


def env_base_url() -> str:
    return os.environ.get("SERVER_URL", "").strip()
