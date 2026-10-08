"""和一台 ComfyUI 说话:HTTP(标准库 http.client,保持连接)。

插件进程跑在随应用发的那个 Python 上,只有标准库 —— 为了发几个请求装一个 httpx 不值得,
http.client 该有的都有:JSON 进出、multipart 上传(传参考图)、流式下载(取成片)。

**不走任何代理。** ComfyUI 在本机或局域网里;开着代理软件的机器上,一个 192.168.x.x 的请求被送去代理只会换回一句
莫名其妙的 502。http.client 自己就不读代理设置。

**保持连接,不发 `Connection: close`。** 此前用 urllib:它给每个请求都强行带上 `Connection: close`(`AbstractHTTPHandler.do_open`
无条件设置)。经端口转发连 ComfyUI 时(UU 远程、frp、SSH 转发),转发那一头碰上这种请求大约一半会把连接提前断掉:插件报
「连不上这台 ComfyUI」(`Remote end closed connection without response`),6 MB 的 `/object_info` 有时读到一半就断
(`IncompleteRead`),浏览器打开却一切正常。实测同一个转发端口各 15 次:不带这个头 15/15 成功,带上 8/15。
现在一个 `Comfy` 里每个线程复用自己的一条连接(几个线程并发取东西时各用各的),用完 `close()`。

幂等的请求(GET、HEAD)碰上连接被对方断开、读到一半断了,换一条新连接重来一次:保持着的连接本来就可能被对方在空闲时
关掉,第一次就撞上的那种也一样。POST 不重来 —— 交出去的任务、写进去的文件不能交两遍。
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import sys
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar
from urllib import parse

import labels
from lines import ComfyError, say

#: 普通请求的上限。ComfyUI 的接口都是本地的、立即返回的;排队和生成不在这些请求里等。
TIMEOUT_SECONDS = 30.0
#: 下载成片的上限。一段几百 MB 的视频在局域网里也就几十秒。
DOWNLOAD_TIMEOUT_SECONDS = 600.0

#: 出错时最多读多少正文。
_MAX_ERROR_BODY = 1024 * 1024
#: 跳转最多跟几次(和 urllib 一样跟 301 / 302 / 303 / 307 / 308)。
_MAX_REDIRECTS = 5
_REDIRECTS = (301, 302, 303, 307, 308)
#: 连接被对方断开、读到一半断了:换一条新连接重来一次就好的那几种(只对 GET、HEAD)。
_RETRYABLE = (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError, http.client.IncompleteRead)
_IDEMPOTENT = ("GET", "HEAD")
#: 和此前 urllib 发的一样:有的反向代理、登录插件按它认人,换了没有好处。
_USER_AGENT = "Python-urllib/%d.%d" % sys.version_info[:2]

T = TypeVar("T")


class HTTPStatusError(Exception):
    """ComfyUI 回了 4xx / 5xx。`code` 状态码,`reason` 那一行的原因,`body` 正文(最多 _MAX_ERROR_BODY 字节)。"""

    def __init__(self, code: int, reason: str, body: bytes) -> None:
        super().__init__(f"HTTP {code} {reason}")
        self.code = code
        self.reason = reason
        self.body = body


_Origin = tuple[str, str, int]  # (scheme, host, port)


def _whole(response: http.client.HTTPResponse, result: T) -> T:
    """读到头了,却没读满对方说的那么长:是读到一半断了。

    http.client 按块读(`read(n)`)时碰上对方提前断开,只回一个空块、不报错(它自己的注释说「本该报 IncompleteRead,怕
    不兼容」)—— 一段一段写文件的下载会把半截当成整份交出去。这里补上这一句,好让 GET 换条连接重来。"""
    if response.isclosed() and response.length:
        raise http.client.IncompleteRead(b"", response.length)
    return result


def _origin_of(url: parse.SplitResult) -> _Origin:
    scheme = url.scheme or "http"
    return scheme, url.hostname or "", url.port or (443 if scheme == "https" else 80)


class Comfy:
    """一台 ComfyUI 服务器。短命的:一次调用一个,用完 `close()`(或 `with Comfy(...) as comfy:`)。"""

    def __init__(self, base_url: str, locale: str = "zh", access_token: str = "") -> None:
        base = (base_url or "").strip().rstrip("/")
        if not base:
            raise ComfyError(say(locale, "没填 ComfyUI 的服务器地址", "The ComfyUI server URL is empty"))
        if not base.startswith(("http://", "https://")):
            base = f"http://{base}"
        if "@" in parse.urlsplit(base).netloc:
            # 写在地址里的「用户名:密码@」会出现在连接名上
            raise ComfyError(say(locale, "服务器地址里别写用户名和密码 —— 把「用户名:密码」填进连接的「访问凭据」",
                                 "Don't put a user name and password in the server URL. Enter “user:password” as the connection's access credential."))
        self.base = base
        self.locale = locale
        #: 每个请求(含 WebSocket 握手)都带的头:ComfyUI 放在要登录的反向代理 / ComfyUI-Login 后面时要它
        self.headers = auth_headers(access_token)
        split = parse.urlsplit(base)
        self._origin = _origin_of(split)
        #: 地址里带着的路径前缀(ComfyUI 挂在反向代理的一个子路径下)
        self._prefix = split.path.rstrip("/")
        #: 每个线程自己那几条连接(按目标站分;跳转到别处时才会有第二条)。几个线程并发取东西时各用各的
        self._local = threading.local()
        self._opened: list[http.client.HTTPConnection] = []
        self._opened_lock = threading.Lock()

    def __enter__(self) -> Comfy:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        """关掉这个 `Comfy` 开过的所有连接。"""
        with self._opened_lock:
            opened, self._opened = self._opened, []
        for connection in opened:
            connection.close()

    # --- 传输 -------------------------------------------------------------

    def _connection(self, origin: _Origin, timeout: float) -> http.client.HTTPConnection:
        pool: dict[_Origin, http.client.HTTPConnection] = self._local.__dict__.setdefault("connections", {})
        connection = pool.get(origin)
        if connection is None:
            scheme, host, port = origin
            kind = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
            connection = kind(host, port, timeout=timeout)
            pool[origin] = connection
            with self._opened_lock:
                self._opened.append(connection)
        connection.timeout = timeout
        if connection.sock is not None:
            connection.sock.settimeout(timeout)
        return connection

    def _drop(self, origin: _Origin) -> None:
        """这条连接不能再用了(对方断了、回答没读完):关掉,下一个请求新开一条。"""
        pool = self._local.__dict__.get("connections", {})
        connection = pool.pop(origin, None)
        if connection is not None:
            connection.close()

    def exchange(self, method: str, path: str, consume: Callable[[http.client.HTTPResponse], T], *,
                 params: dict[str, Any] | None = None, body: bytes | None = None, headers: dict[str, str] | None = None,
                 timeout: float = TIMEOUT_SECONDS) -> T:
        """发一个请求,把 2xx 的回答交给 `consume` 读(它读多少由它定),交回它的结果。

        回 4xx / 5xx 抛 `HTTPStatusError`(带着正文);连不上、被断开抛给人看的 ComfyError。GET、HEAD 碰上连接被断开、
        读到一半断了,换一条新连接整个重来一次(`consume` 也重来:下载会从头写)。"""
        target = f"{self._prefix}{path}"
        if params:
            target = f"{target}?{parse.urlencode(params)}"
        sent = {"User-Agent": _USER_AGENT, **self.headers, **(headers or {})}
        origin = self._origin
        for _hop in range(_MAX_REDIRECTS + 1):
            response, connection_origin = self._send(method, origin, target, body, sent, timeout)
            try:
                location = response.getheader("Location")
                if response.status in _REDIRECTS and location and (
                        method in _IDEMPOTENT or (method == "POST" and response.status in (301, 302, 303))):
                    nxt = parse.urlsplit(parse.urljoin(f"{origin[0]}://{origin[1]}:{origin[2]}{target}", location))
                    if _origin_of(nxt) != origin:
                        sent = {key: value for key, value in sent.items() if key.lower() != "authorization"}
                    origin = _origin_of(nxt)
                    target = nxt.path + (f"?{nxt.query}" if nxt.query else "")
                    if method == "POST":  # 和 urllib 一样:POST 跳转之后改成不带正文的 GET
                        method, body = "GET", None
                        sent = {key: value for key, value in sent.items() if key.lower() != "content-type"}
                    continue
                if response.status >= 400:
                    raise HTTPStatusError(response.status, response.reason, response.read(_MAX_ERROR_BODY))
                return self._consume(method, response, consume, origin, target, body, sent, timeout)
            finally:
                if not response.isclosed():
                    self._drop(connection_origin)
        raise ComfyError(say(self.locale, f"ComfyUI 那边跳转了太多次({path})", f"ComfyUI redirected too many times ({path})"))

    def _send(self, method: str, origin: _Origin, target: str, body: bytes | None, headers: dict[str, str],
              timeout: float) -> tuple[http.client.HTTPResponse, _Origin]:
        """发出去、拿到回答的头。GET、HEAD 碰上连接被断开就换一条新连接再发一次。"""
        attempts = 2 if method in _IDEMPOTENT else 1
        if method not in _IDEMPOTENT:
            # 交东西(POST)用一条新连接:保持着的连接可能已经被对方在空闲时关了,而 POST 撞上了不能重来 —— 分不清对方
            # 收没收到。新开的连接不会是这种,也不带 `Connection: close`。
            self._drop(origin)
        for attempt in range(attempts):
            connection = self._connection(origin, timeout)
            try:
                connection.request(method, target, body=body, headers=headers)
                response = connection.getresponse()
                if method == "HEAD":
                    response.read()  # 没有正文;读这一下,连接才能接着用
                return response, origin
            except _RETRYABLE as exc:
                self._drop(origin)
                if attempt + 1 < attempts:
                    continue
                raise self._unreachable(exc) from exc
            except (OSError, http.client.HTTPException) as exc:
                self._drop(origin)
                raise self._unreachable(exc) from exc
        raise AssertionError("unreachable")

    def _consume(self, method: str, response: http.client.HTTPResponse, consume: Callable[[http.client.HTTPResponse], T],
                 origin: _Origin, target: str, body: bytes | None, headers: dict[str, str], timeout: float) -> T:
        """读回答的正文。GET 读到一半断了:换一条新连接把这个请求整个重来一次(只一次)。"""
        try:
            return _whole(response, consume(response))
        except _RETRYABLE as exc:
            self._drop(origin)
            if method not in _IDEMPOTENT:
                raise self._unreachable(exc) from exc
            first = exc
        except (OSError, http.client.HTTPException) as exc:
            self._drop(origin)
            raise self._unreachable(exc) from exc
        connection = self._connection(origin, timeout)
        try:
            connection.request(method, target, body=body, headers=headers)
            again = connection.getresponse()
            try:
                if again.status >= 400:
                    raise HTTPStatusError(again.status, again.reason, again.read(_MAX_ERROR_BODY))
                return _whole(again, consume(again))
            finally:
                if not again.isclosed():
                    self._drop(origin)
        except (OSError, http.client.HTTPException) as exc:
            self._drop(origin)
            raise self._unreachable(exc) from first

    def _unreachable(self, exc: BaseException) -> ComfyError:
        # 第一行是给人看的那句(该做什么),地址和原文(errno)换到下一行:界面把第一行当正文,其余收进「详情」
        reason = getattr(exc, "reason", None) or exc
        return ComfyError(
            say(self.locale, f"连不上这台 ComfyUI,确认它在运行、地址填对\n{self.base}:{reason}",
                f"Can't reach this ComfyUI. Make sure it is running and the URL is right\n{self.base}: {reason}")
        )

    def request_json(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                     body: Any = None, timeout: float = TIMEOUT_SECONDS) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        try:
            raw = self.exchange(method, path, lambda response: response.read(), params=params, body=data,
                                headers=headers, timeout=timeout)
        except HTTPStatusError as exc:
            raise self._http_error(exc) from exc
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise ComfyError(say(self.locale, f"ComfyUI 回了一段不是 JSON 的东西({path})",
                                 f"ComfyUI answered {path} with something that is not JSON")) from exc

    def get(self, path: str, params: dict[str, Any] | None = None, *, timeout: float = TIMEOUT_SECONDS) -> Any:
        """`timeout`:少数要等那台机器算一阵的(按哈希找模型要它把整个文件读一遍)才放宽。"""
        return self.request_json("GET", path, params=params, timeout=timeout)

    def head_length(self, path: str) -> int | None:
        """一个接口的回答有多大(`HEAD`,只要 Content-Length,不收正文)。aiohttp 对 GET 的路由照样答 HEAD:那台机器把回答
        算一遍,但一个字节都不发 —— 整份 `/object_info` 在慢的局域网上要传十几秒,问它多大不到一秒。没有这个接口、
        没说多大 → None。"""
        try:
            raw = self.exchange("HEAD", path, lambda response: response.getheader("Content-Length") or "")
        except HTTPStatusError as exc:
            if exc.code in (404, 405):
                return None
            raise self._http_error(exc) from exc
        return int(raw) if raw.isdigit() else None

    def get_text(self, path: str) -> str | None:
        """回一段纯文字的接口(ComfyUI-Manager 的 `/v2/manager/version` 回 `V4.2.1`)。没有这个接口(404)→ None。"""
        try:
            return self.exchange("GET", path, lambda response: response.read(4096).decode("utf-8", "replace").strip())
        except HTTPStatusError as exc:
            if exc.code == 404:
                return None
            raise self._http_error(exc) from exc

    def get_range(self, path: str, start: int, end: int) -> bytes | None:
        """读一个文件里的一段(`Range: bytes=start-end`,含两头),最多 `end - start + 1` 个字节。

        对方回 206 才算数;回 200 是不认 Range、要把整个文件发过来 —— 几 GB 的模型文件不能整个下,立刻关掉连接、回
        None。没有这个地址(404)也回 None;要的那一段整个在文件末尾之后(416)回空。"""

        def part(response: http.client.HTTPResponse) -> bytes | None:
            if response.status != 206:
                return None  # 没读的正文留在连接上:这条连接随即关掉(见 exchange)
            return response.read(end - start + 1)

        try:
            return self.exchange("GET", path, part, headers={"Range": f"bytes={start}-{end}"})
        except HTTPStatusError as exc:
            if exc.code == 404:
                return None
            if exc.code == 416:
                return b""
            raise self._http_error(exc) from exc

    def post(self, path: str, body: Any) -> Any:
        return self.request_json("POST", path, body=body)

    def _http_error(self, exc: HTTPStatusError) -> ComfyError:
        # 正文留全(调用方要解析它:/prompt 的校验错误带着整张可选值列表,动辄几 KB),给人看的那句才截短
        body = exc.body.decode("utf-8", "replace")
        shown = body[:400] or exc.reason
        return ComfyError(say(self.locale, f"ComfyUI 回了 HTTP {exc.code}:{shown}",
                              f"ComfyUI answered HTTP {exc.code}: {shown}"), status=exc.code, body=body)

    # --- 接口 -------------------------------------------------------------

    def object_info(self) -> dict[str, Any]:
        """全部节点的定义(输入类型、可选值、上下界)。转换、描述参数都要它。

        并上 ComfyUI 给节点和输入的各语言名字(`/i18n`,自定义节点包带的翻译;见 labels.with_i18n):能填的项、「结果取自」
        里的节点名从这里来,哪个界面都是同一个名字。老版本没有 `/i18n`、或者它出了错,就只用 object_info 自己的英文名。"""
        info = self.get("/object_info")
        if not isinstance(info, dict):
            return {}
        try:
            translations = self.get("/i18n")
        except ComfyError:
            return info
        return labels.with_i18n(info, translations)

    def saved_files(self) -> tuple[list[str], list[str]]:
        """工作流目录里的文件(相对 workflows/ 的路径):(**保存**的工作流, 别的文件)。隐藏文件都不算(老版本前端的
        .index.json)。

        别的文件(用户拷进去的压缩包之类)不是工作流,ComfyUI 自己也打不开;交出来是为了说清楚它为什么用不了。"""
        workflows: list[str] = []
        others: list[str] = []
        for item in self.workflow_listing():
            path = str(item.get("path") or "")
            if not path or any(part.startswith(".") for part in path.split("/")):
                continue
            (workflows if is_workflow_path(path) else others).append(path)
        return sorted(workflows, key=str.lower), sorted(others, key=str.lower)

    def fetch_workflow(self, path: str) -> dict[str, Any]:
        graph = self.get(f"/api/userdata/{parse.quote('workflows/' + path, safe='')}")
        if not isinstance(graph, dict):
            raise ComfyError(say(self.locale, f"工作流「{path}」不是一个 JSON 对象", f"Workflow “{path}” is not a JSON object"))
        return graph

    def fetch_workflow_text(self, path: str) -> tuple[dict[str, Any], str]:
        """一张工作流读出来的图和它的原文(`annotate` 照原文的排版写回,见 json_style)。"""
        try:
            text = self.exchange("GET", f"/api/userdata/{parse.quote('workflows/' + path, safe='')}",
                                 lambda response: response.read().decode("utf-8"))
        except HTTPStatusError as exc:
            raise self._http_error(exc) from exc
        try:
            graph = json.loads(text)
        except ValueError:
            graph = None
        if not isinstance(graph, dict):
            raise ComfyError(say(self.locale, f"工作流「{path}」不是一个 JSON 对象", f"Workflow “{path}” is not a JSON object"))
        return graph, text

    def workflow_listing(self) -> list[dict[str, Any]]:
        """保存的工作流连同大小和修改时间。**便宜** —— 只列目录,不取内容;判「有没有变」用它。"""
        try:
            items = self.get("/api/userdata", {"dir": "workflows", "recurse": "true", "split": "false", "full_info": "true"})
        except ComfyError as exc:
            if exc.status == 404:
                return []  # 还没存过工作流:workflows 目录不存在,ComfyUI 回 404 —— 就是一张都没有
            raise
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    def userdata_listing(self, directory: str) -> list[dict[str, Any]]:
        """用户目录里某个目录下的文件(相对那个目录的路径、大小、改动时间)。目录不存在 → 空。"""
        try:
            items = self.get("/api/userdata", {"dir": directory, "recurse": "true", "split": "false", "full_info": "true"})
        except ComfyError as exc:
            if exc.status == 404:
                return []
            raise
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    def userdata_tree(self, directory: str) -> list[dict[str, Any]] | None:
        """用户目录里某个目录下的**目录和文件**(`GET /api/v2/userdata?path=…`,ComfyUI 0.3.3x 起有):一层层走下去
        (os.walk),每项 `{name, path, type: "directory" | "file"}`,`path` 相对**用户目录**。空目录、隐藏文件都在里面 ——
        `/api/userdata` 只列文件(glob,跳过隐藏的),列不出空目录。

        回 404 的有两种:那个目录不存在,或者这版 ComfyUI 还没有这个接口 —— 分不出来,都回 None,调用方当「只知道有文件的
        那几个目录」。"""
        try:
            items = self.get("/api/v2/userdata", {"path": directory})
        except ComfyError as exc:
            if exc.status == 404:
                return None
            raise
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else None

    def write_userdata(self, path: str, value: Any) -> bool:
        """在用户目录里**新建**一份(相对用户目录的路径):已经有了就回 False(ComfyUI 回 409),**不覆盖**。"""
        body = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        try:
            self.exchange("POST", f"/api/userdata/{parse.quote(path, safe='')}", lambda response: response.read(),
                          params={"overwrite": "false", "full_info": "true"}, body=body,
                          headers={"Content-Type": "application/json"})
        except HTTPStatusError as exc:
            if exc.code == 409:
                return False
            raise self._http_error(exc) from exc
        return True

    def overwrite_userdata(self, path: str, text: str) -> dict[str, Any]:
        """**覆盖写**用户目录里已有的一份(写好的 JSON 原文),回 ComfyUI 给的文件信息(`{path, size, modified}`)。

        只有 `annotate`(改应用表单的标记,ADR 0038 §2)用它,而且调用方先核对过改动时间、照那张原来的排版写好了原文
        (json_style)—— 别的写操作一律走 `write_userdata` / `move_userdata`,不覆盖。"""
        body = text.encode("utf-8")
        try:
            raw = self.exchange("POST", f"/api/userdata/{parse.quote(path, safe='')}", lambda response: response.read(),
                                params={"overwrite": "true", "full_info": "true"}, body=body,
                                headers={"Content-Type": "application/json"})
        except HTTPStatusError as exc:
            raise self._http_error(exc) from exc
        try:
            info = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            info = {}
        return info if isinstance(info, dict) else {}

    def move_userdata(self, source: str, dest: str) -> bool:
        """在用户目录里挪一份(改名、挪目录、挪进 / 挪出回收目录):目标已经有了就回 False(409),**不覆盖**。

        ComfyUI 那边是 `shutil.move`:源是一个目录也挪得动(连同里面的一切)—— 文件夹改名、挪进回收目录走的就是它。
        源不在了 ComfyUI 回 404,照常抛出(`status` 是 404),调用方说「已经没有了」。"""
        path = f"/api/userdata/{parse.quote(source, safe='')}/move/{parse.quote(dest, safe='')}"
        try:
            self.exchange("POST", path, lambda response: response.read(), params={"overwrite": "false", "full_info": "true"},
                          body=b"", headers={"Content-Type": "application/json"})
        except HTTPStatusError as exc:
            if exc.code == 409:
                return False
            raise self._http_error(exc) from exc
        return True

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
        stored = self.upload_file(source, name, kind="input", subfolder="mosael")
        return f"{stored['subfolder']}/{stored['name']}" if stored["subfolder"] else stored["name"]

    def upload_file(self, source: Path, name: str, *, kind: str, subfolder: str) -> dict[str, str]:
        """经 `/upload/image` 把一个文件传进 ComfyUI 的某个目录(`kind`:input / temp),回它存下的 `name`、`subfolder`。
        同名的覆盖(名字是我们起的,带随机串)。"""
        boundary = f"----mosael{uuid.uuid4().hex}"
        parts: list[bytes] = []
        for key, value in (("overwrite", "true"), ("type", kind), ("subfolder", subfolder)):
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
            answer = json.loads(self.exchange("POST", "/upload/image", lambda response: response.read(),
                                              body=b"".join(parts), headers=headers).decode("utf-8") or "{}")
        except HTTPStatusError as exc:
            raise self._http_error(exc) from exc
        return {"name": str(answer.get("name") or name), "subfolder": str(answer.get("subfolder") or "")}

    def download(self, item: dict[str, Any], target: Path) -> Path:
        """取回一份产出(`/view`),流式写到 `target`。"""
        params = {"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")}

        def save(response: http.client.HTTPResponse) -> Path:
            # 读到一半断了,exchange 会换条连接整个重来一次:这里每次都从头写
            with target.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            return target

        try:
            return self.exchange("GET", "/view", save, params=params, timeout=DOWNLOAD_TIMEOUT_SECONDS)
        except HTTPStatusError as exc:
            raise self._http_error(exc) from exc

    def ws_url(self, client_id: str) -> str:
        scheme = "wss" if self.base.startswith("https://") else "ws"
        host = self.base.split("://", 1)[1]
        return f"{scheme}://{host}/ws?clientId={parse.quote(client_id)}"


def is_workflow_path(path: str) -> bool:
    return path.endswith(".json") and not any(part.startswith(".") for part in path.split("/"))


def env_base_url() -> str:
    return os.environ.get("SERVER_URL", "").strip()


def env_access_token() -> str:
    """连接的「访问凭据」(凭据 `access_token`,宿主注入成大写的环境变量)。"""
    return os.environ.get("ACCESS_TOKEN", "").strip()


def auth_headers(token: str) -> dict[str, str]:
    """访问凭据 → Authorization 头:`用户名:密码` 按 Basic(反向代理的登录),别的按 Bearer 令牌(ComfyUI-Login 等)。"""
    token = (token or "").strip()
    if not token:
        return {}
    if ":" in token:
        return {"Authorization": "Basic " + base64.b64encode(token.encode("utf-8")).decode("ascii")}
    return {"Authorization": f"Bearer {token}"}
