"""对象存储插件的共用主体:上传、取限时直链、下载回素材库、列目录。

## 为什么三家共用这一份

S3、火山 TOS、阿里云 OSS 的 HTTP 接口**是同一套**(PUT/GET 对象、list-objects-v2),
只有签名方言不同(见 sigv4.Flavor)。三份各写一遍的话,差异会出现在那些平时走不到的地方 ——
比如 key 里带中文时的转义、list 的分页参数 —— 而那种差异的表现是 403 或"少了几条",
不是报错。

三个插件各自是独立可分发的包,所以这个文件在三个包里各有一份**字节相同**的拷贝,
由棘轮钉住(backend/tests/test_storage_plugins_share_one_core.py)。拷贝不可怕,
**悄悄漂掉的拷贝**才可怕。

## 它解决的那个具体问题

方舟 Seedance 的参考视频**只收公网直链**(官方文档:「请确保 URL 是公网可公开访问的链接,
建议存放在 TOS 对象存储服务中」)—— 而 Mosael 是本地优先的,素材库里的文件没有公网地址。
`*_upload` 就是那座桥:把本地素材传上去,交回一条限时直链,直接粘进生成节点的参考视频那一格。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import sigv4

#: 限时直链的默认有效期。一小时够一次生成任务用完(方舟自己的任务过期是 48 小时,
#: 但它在**提交时**就把文件取走了),又不会把一条可公开下载的地址长期留在外面。
DEFAULT_EXPIRES = 3600
#: 一次 list 最多回多少条。接口自己的上限是 1000。
MAX_KEYS = 1000


def line(locale: str, zh: str, en: str) -> str:
    """一句给人看的话 —— 按调用方的语言挑(`zh-CN` 和 `zh` 是同一件事)。"""
    return zh if locale.replace("_", "-").split("-")[0].lower() == "zh" else en


class StorageError(RuntimeError):
    """说得出口的失败。消息直接进工具结果,所以要是一句人话。"""


def _stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _request(url: str, *, method: str, headers: dict[str, str], body: bytes | None = None) -> bytes:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as exc:  # 对象存储的错误正文是 XML,里面那句 Message 才有用
        detail = exc.read().decode("utf-8", "replace")
        message = ""
        try:
            message = (ET.fromstring(detail).findtext("Message") or "").strip()
        except ET.ParseError:
            message = detail[:300]
        raise StorageError(f"{exc.code} {message or detail[:300]}") from exc
    except urllib.error.URLError as exc:
        # **带上连的是哪个主机。** 底层原因常常看不出地址错了:开着代理时,一个不存在的域名
        # 不会报"解析失败",而是被代理接下再断开,变成一句 SSL UNEXPECTED_EOF。
        host = urllib.parse.urlsplit(url).hostname or url
        raise StorageError(f"连不上对象存储 {host}:{exc.reason}") from exc


class Bucket:
    """一个桶。**端点由配置给**,所以同一套代码也能连自建的 S3 兼容服务。"""

    def __init__(self, *, flavor: sigv4.Flavor, endpoint: str, bucket: str, region: str,
                 access_key: str, secret: str) -> None:
        if not bucket:
            raise StorageError("没有配置桶名")
        if not access_key or not secret:
            raise StorageError("没有配置访问密钥")
        self.flavor, self.bucket, self.region = flavor, bucket, region
        self.access_key, self.secret = access_key, secret
        # 用户常把整条 URL 贴进来(带协议、带路径),只取主机名。
        host = endpoint.strip().replace("https://", "").replace("http://", "").strip("/").split("/")[0]
        if "." not in host and ":" not in host and host != "localhost":
            # 最常见的填法错误:把地域(cn-shanghai / us-east-1)填进了接入点。照原样拼出来的
            # `桶名.cn-shanghai` 不是一个域名,而报出来的往往是一句看不懂的网络错误。
            # 自建的 S3 兼容服务(localhost:9000、minio:9000)带端口或就是 localhost,不在此列。
            raise StorageError(
                f"接入点「{endpoint}」不是一个域名 —— 看起来像地域。地域填在「区域」那一格;"
                "接入点要填完整域名,通常留空,会按区域自动拼。"
            )
        self.host = host
        #: **虚拟主机式寻址**(桶名在域名里)是三家的默认,路径式正在被淘汰。
        if not self.host.startswith(f"{bucket}."):
            self.host = f"{bucket}.{self.host}"
        self.base = f"https://{self.host}"

    def _path(self, key: str) -> str:
        return "/" + sigv4.quote(key.lstrip("/"))

    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
        stamp = _stamp()
        payload = sigv4.UNSIGNED if self.flavor.unsigned_payload_only else sigv4.sha256_hex(data)
        headers = {
            "host": self.host,
            self.flavor.date_header: stamp,
            self.flavor.sha_header: payload,
            "content-type": content_type,
            "content-length": str(len(data)),
        }
        headers["authorization"] = sigv4.authorization(
            method="PUT", path=self._path(key), query="", headers=headers, payload_hash=payload,
            access_key=self.access_key, secret=self.secret, region=self.region,
            stamp=stamp, flavor=self.flavor, bucket=self.bucket,
        )
        _request(self.base + self._path(key), method="PUT", headers=headers, body=data)

    def presign(self, key: str, *, expires: int = DEFAULT_EXPIRES, method: str = "GET") -> str:
        """一条**限时**直链。桶不必设成公共读 —— 签名在查询串里,谁拿到谁能下。"""
        query = sigv4.presigned_query(
            method=method, path=self._path(key), host=self.host, expires=expires,
            access_key=self.access_key, secret=self.secret, region=self.region,
            stamp=_stamp(), flavor=self.flavor, bucket=self.bucket,
        )
        return f"{self.base}{self._path(key)}?{query}"

    def public_url(self, key: str) -> str:
        """桶设成公共读时的那条地址。**没设的话它会 403** —— 所以工具同时交回限时直链。"""
        return f"{self.base}{self._path(key)}"

    def listing(self, prefix: str = "", limit: int = 100) -> list[dict]:
        stamp = _stamp()
        params = {"list-type": "2", "max-keys": str(max(1, min(int(limit or 100), MAX_KEYS)))}
        if prefix:
            params["prefix"] = prefix
        query = "&".join(f"{sigv4.quote(k, safe='')}={sigv4.quote(v, safe='')}"
                         for k, v in sorted(params.items()))
        payload = sigv4.UNSIGNED
        headers = {"host": self.host, self.flavor.date_header: stamp, self.flavor.sha_header: payload}
        headers["authorization"] = sigv4.authorization(
            method="GET", path="/", query=query, headers=headers, payload_hash=payload,
            access_key=self.access_key, secret=self.secret, region=self.region,
            stamp=stamp, flavor=self.flavor, bucket=self.bucket,
        )
        body = _request(f"{self.base}/?{query}", method="GET", headers=headers)
        root = ET.fromstring(body)
        namespace = root.tag.split("}")[0] + "}" if "}" in root.tag else ""
        out = []
        for item in root.findall(f"{namespace}Contents"):
            out.append({
                "key": item.findtext(f"{namespace}Key") or "",
                "size": int(item.findtext(f"{namespace}Size") or 0),
                "last_modified": item.findtext(f"{namespace}LastModified") or "",
            })
        return out


#: 常见后缀 → Content-Type。**要发对**:供应商按它判断这是不是一段视频,发成
#: `application/octet-stream` 的话对面可能直接拒。
_TYPES = {
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".m4v": "video/x-m4v",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".aac": "audio/aac",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
    ".gif": "image/gif", ".json": "application/json", ".txt": "text/plain",
}


def content_type_of(name: str) -> str:
    return _TYPES.get(os.path.splitext(name)[1].lower(), "application/octet-stream")


def run(tools: dict) -> None:
    """stdio 协议的外壳:读一个请求,写一个响应。三个插件共用。"""
    try:
        request = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error": f"bad request json: {exc}"}))
        return
    locale = str(request.get("locale") or os.environ.get("MOSAEL_LOCALE") or "zh")
    handler = tools.get(str(request.get("tool") or ""))
    if handler is None:
        print(json.dumps({"ok": False, "error": f"unknown tool: {request.get('tool')}"}))
        return
    try:
        output = handler(dict(request.get("input") or {}), locale)
    except StorageError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return
    except Exception as exc:  # noqa: BLE001 —— 插件的异常不该只剩一个栈
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return
    print(json.dumps({"ok": True, "output": output}, ensure_ascii=False))
