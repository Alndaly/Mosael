"""对象存储的主体:上传(大文件分片)、取限时直链、列目录,以及把失败翻成人话。

## 它不认识任何一家

S3、火山 TOS、阿里云 OSS、腾讯云 COS 的 HTTP 接口**是同一套**(PUT/GET 对象、分片上传、列目录、
虚拟主机式寻址、XML 错误体),**只有签名和几处默认值不同**。那些不同全在 providers.py 那张表里;
签名是一个方言对象,回答三件事:

- `sign(bucket, method=, path=, params=, headers=, body=, now=)` → 真正发出去的请求头(含签名);
- `presign(bucket, method=, path=, expires=, now=)` → 限时直链的查询串;
- `list_v2`:列目录用不用 `list-type=2`(COS 只有 V1)。

`path` 交过去的是**未转义**的请求路径 —— 各家对路径的规范化不同(SigV4 签转义后的,COS 签原文),
由方言自己处理;发请求用的 URL 由这里统一转义。

此前这份主体在四个插件包里各有一份字节相同的拷贝,靠一条棘轮钉着不漂;现在四家是同一个插件的
四个选项(见 providers.py),拷贝本身没有了。

## 大文件

- **不整个读进内存**:此前 `handle.read()` 把一个几个 G 的成片整个读进来再 PUT;
- 超过 MULTIPART_THRESHOLD 走**分片上传**(Initiate → UploadPart × N → Complete,四家同一套),
  每片单独重试,中途失败或被取消就 Abort,不在桶里留下收费的碎片;
- 边传边报进度(`{"event": "progress", ...}`,见 docs/PLUGIN_MANIFEST 的「流式工具」),
  宿主建了取消文件(`MOSAEL_PLUGIN_CANCEL_FILE`)就在片与片之间停下。

单次 PUT 的上限四家都是 5GB,分片上限 10000 片 —— 片大小按文件大小放大,保证片数够用。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Callable, Iterator

#: 限时直链的默认有效期。一小时够一次生成任务用完(方舟在**提交时**就把文件取走了),
#: 又不会把一条可公开下载的地址长期留在外面。
DEFAULT_EXPIRES = 3600
#: 一次 list 最多回多少条。接口自己的上限是 1000。
MAX_KEYS = 1000
#: 超过这个大小走分片上传。单次 PUT 的正文要整个读进内存来签(SigV4 签正文哈希),所以门槛不能高。
MULTIPART_THRESHOLD = 64 * 1024 * 1024
#: 分片的起始大小。四家的下限:S3 / TOS 5MiB、COS 1MiB、OSS 100KiB —— 16MiB 高于所有人。
PART_BYTES = 16 * 1024 * 1024
MAX_PARTS = 10000
#: 一次请求失败后最多再试几次(只重试「过一会儿可能就好」的那几种,见 _retryable)。
RETRIES = 3
#: 单次请求的套接字超时。整次工具调用的预算由清单的 timeout_seconds 管。
REQUEST_TIMEOUT = 120

CANCEL_ENV = "MOSAEL_PLUGIN_CANCEL_FILE"


def line(locale: str, zh: str, en: str) -> str:
    """一句给人看的话 —— 按调用方的语言挑(`zh-CN` 和 `zh` 是同一件事)。"""
    return zh if locale.replace("_", "-").split("-")[0].lower() == "zh" else en


class StorageError(RuntimeError):
    """说得出口的失败。消息直接进工具结果,所以要是一句人话。"""


class Cancelled(StorageError):
    """宿主要停(建了取消文件)。"""


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def quote(value: str, *, safe: str = "/") -> str:
    """RFC 3986 转义,`~` 不转。发出去的 URL 用它;签名里的规范化由方言自己做。"""
    return urllib.parse.quote(value, safe=safe + "~")


def query_string(params: dict[str, str]) -> str:
    """URL 上的查询串。没有值的参数只写名字(`?uploads`)—— 四家都认这种写法。"""
    return "&".join(
        quote(k, safe="") if v == "" else f"{quote(k, safe='')}={quote(v, safe='')}"
        for k, v in sorted(params.items())
    )


# —— 进度与取消 ————————————————————————————————————————————————


class Reporter:
    """流式工具的那一侧:往 stdout 写进度行、看宿主有没有建取消文件。非流式调用用 `Reporter(stream=False)`。"""

    def __init__(self, *, stream: bool) -> None:
        self.stream = stream
        self.cancel_file = os.environ.get(CANCEL_ENV, "")

    def progress(self, fraction: float, message: str) -> None:
        if self.stream:
            print(json.dumps({"event": "progress", "progress": round(fraction, 4), "message": message},
                             ensure_ascii=False), flush=True)

    def cancelled(self) -> bool:
        return bool(self.cancel_file) and os.path.exists(self.cancel_file)


# —— HTTP 与错误 ——————————————————————————————————————————————————


class _HttpFailure(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(status)
        self.status, self.body = status, body


def _request(url: str, *, method: str, headers: dict[str, str],
             body: bytes | None = None) -> tuple[bytes, dict[str, str]]:
    """发一次请求,回 (正文, 响应头[小写])。HTTP 错误抛 _HttpFailure,网络错误抛 URLError。"""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return response.read(), {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        raise _HttpFailure(exc.code, exc.read().decode("utf-8", "replace")) from exc


def _parse(body: bytes | str) -> dict:
    """响应正文 → 一个字典。**XML 和 JSON 都认**:S3 / OSS / COS 回 XML,火山 TOS 的原生接口回 JSON
    (列目录、分片、错误体都是 —— 此前一律按 XML 解,TOS 的列目录直接崩在 ParseError 上)。

    XML 按元素名收成键(命名空间去掉),重复的元素收成列表,根元素名放在 `__root__`。读不出来是空字典。
    """
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    if text.lstrip().startswith("{"):
        try:
            parsed = json.loads(text)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}

    def fold(element) -> object:
        children = list(element)
        if not children:
            return (element.text or "").strip()
        out: dict = {}
        for child in children:
            name, value = child.tag.split("}")[-1], fold(child)
            if name in out:
                out[name] = (out[name] if isinstance(out[name], list) else [out[name]]) + [value]
            else:
                out[name] = value
        return out

    folded = fold(root)
    return {**(folded if isinstance(folded, dict) else {}), "__root__": root.tag.split("}")[-1]}


def _fields(body: bytes | str) -> dict[str, str]:
    """错误体里那几格(Code / Message / Region / Endpoint …),只留字符串的。"""
    return {key: value for key, value in _parse(body).items() if isinstance(value, str)}


def _items(value) -> list:
    """XML 里只有一个元素时收成的是它自己,不是一串 —— 统一成列表。"""
    if value in (None, ""):
        return []
    return value if isinstance(value, list) else [value]


#: 过一会儿可能就好的那几种:限流、服务端临时错误、请求超时。签名错、没权限重试多少次都一样。
_RETRYABLE_STATUS = {500, 502, 503, 504}
#: 时钟偏差(RequestTimeTooSkewed)不在此列:每次重签都用本机时间,差多少还是差多少。
_RETRYABLE_CODES = {"SlowDown", "RequestTimeout", "InternalError", "ServiceUnavailable"}


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, _HttpFailure):
        return exc.status in _RETRYABLE_STATUS or _fields(exc.body).get("Code", "") in _RETRYABLE_CODES
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


def explain(exc: Exception, *, host: str, bucket: str, locale: str) -> str:
    """一次失败 → 一句人话。**每一种失败对用户意味着不同的下一步**,所以按错误码分开说,并带上原始错误码
    (用户拿去搜、或者贴给我们看的就是它)。"""
    if isinstance(exc, _HttpFailure):
        fields = _fields(exc.body)
        code, message = fields.get("Code", ""), fields.get("Message", "") or exc.body[:300]
        raw = f"({exc.status} {code or ''} {message})".replace("  ", " ")
        region, endpoint = fields.get("Region", ""), fields.get("Endpoint", "")
        if region:
            return line(locale, f"桶「{bucket}」在 {region} 地域 —— 把连接的「地域」改成 {region}(接入点留空)。{raw}",
                        f"Bucket “{bucket}” lives in {region} — set the connection's region to {region} "
                        f"(and leave the endpoint empty). {raw}")
        if endpoint:
            return line(locale, f"桶「{bucket}」要通过 {endpoint} 访问 —— 地域或接入点填得和桶不一致。{raw}",
                        f"Bucket “{bucket}” must be reached through {endpoint} — the region or endpoint "
                        f"doesn't match the bucket. {raw}")
        hints = {
            "NoSuchBucket": ("桶「{b}」不存在 —— 检查桶名(腾讯云要带 APPID 后缀)和地域。",
                             "Bucket “{b}” does not exist — check the name (Tencent COS needs the APPID suffix) and region."),
            "InvalidAccessKeyId": ("访问密钥 ID 不对(或已被停用)。", "The access key ID is wrong or disabled."),
            "SignatureDoesNotMatch": ("签名对不上 —— 通常是密钥(Secret)填错了。",
                                      "The signature doesn't match — usually the secret key is wrong."),
            "AccessDenied": ("这把密钥没有这个桶的权限(上传要写、列目录要列、取链接要读)。",
                             "This key has no permission on the bucket (upload needs write, listing needs list, links need read)."),
            "RequestTimeTooSkewed": ("本机时钟和服务端差得太多 —— 校准一下系统时间。",
                                     "This machine's clock is too far off — sync the system time."),
            "EntityTooLarge": ("文件超过了这一家单次上传的上限。", "The file exceeds this service's upload size limit."),
            "NoSuchKey": ("桶里没有这个对象。", "No such object in the bucket."),
        }
        if code in hints:
            zh, en = hints[code]
            return line(locale, zh.format(b=bucket), en.format(b=bucket)) + " " + raw
        return f"{exc.status} {code} {message}".strip()
    if isinstance(exc, urllib.error.URLError):
        # **带上连的是哪个主机。** 底层原因常常看不出地址错了:开着代理时,一个不存在的域名
        # 不会报"解析失败",而是被代理接下再断开,变成一句 SSL UNEXPECTED_EOF。
        return line(locale, f"连不上对象存储 {host}:{exc.reason}", f"Can't reach object storage {host}: {exc.reason}")
    return line(locale, f"连不上对象存储 {host}:{exc}", f"Can't reach object storage {host}: {exc}")


# —— 桶 ————————————————————————————————————————————————————————


class Bucket:
    """一个桶。**端点由配置给**,所以同一套代码也能连自建的 S3 兼容服务。"""

    def __init__(self, *, provider, bucket: str, region: str, endpoint: str,
                 access_key: str, secret: str, locale: str = "zh") -> None:
        self.provider, self.locale = provider, locale
        self.dialect = provider.dialect
        self.bucket, self.region = bucket.strip(), region.strip()
        self.access_key, self.secret = access_key.strip(), secret.strip()
        if not self.bucket:
            raise StorageError(line(locale, "没有配置桶名", "No bucket configured"))
        if not self.region:
            raise StorageError(line(locale, "没有配置地域", "No region configured"))
        if not self.access_key or not self.secret:
            raise StorageError(line(locale, "没有配置访问密钥", "No access keys configured"))
        raw = endpoint.strip()
        if not raw:
            if provider.endpoint_for is None:
                raise StorageError(line(locale, "S3 兼容服务要填接入点(如 minio.example.com 或 http://localhost:9000)",
                                        "An S3-compatible service needs an endpoint (e.g. minio.example.com or http://localhost:9000)"))
            raw = provider.endpoint_for(self.region)
        # 用户常把整条 URL 贴进来(带协议、带路径),只取协议和主机名。协议只认他明写的 http,
        # 其余一律 https —— 本机的 MinIO 常常没有证书。
        scheme = "http" if raw.lower().startswith("http://") else "https"
        host = raw.split("://", 1)[-1].strip("/").split("/")[0]
        if "." not in host and ":" not in host and host != "localhost":
            # 最常见的填法错误:把地域(cn-shanghai / us-east-1)填进了接入点。照原样拼出来的
            # `桶名.cn-shanghai` 不是一个域名,而报出来的往往是一句看不懂的网络错误。
            # 自建的 S3 兼容服务(localhost:9000、minio:9000)带端口或就是 localhost,不在此列。
            raise StorageError(line(
                locale,
                f"接入点「{endpoint}」不是一个域名 —— 看起来像地域。地域填在「地域」那一格;"
                "接入点要填完整域名,通常留空,会按地域自动拼。",
                f"The endpoint “{endpoint}” is not a host name — it looks like a region. Put the region in "
                "“Region”; the endpoint is a full host and is usually left empty.",
            ))
        #: **虚拟主机式寻址**(桶名在域名里)是几家云的默认;S3 兼容服务走路径式(见 providers)。
        if not provider.path_style and not host.startswith(f"{self.bucket}."):
            host = f"{self.bucket}.{host}"
        self.host = host
        self.base = f"{scheme}://{host}"

    # —— 路径 ——

    def _path(self, key: str = "") -> str:
        """未转义的请求路径 —— 交给方言去签。路径式寻址时桶名在路径里。"""
        key = key.lstrip("/")
        if self.provider.path_style:
            return f"/{self.bucket}/{key}" if key else f"/{self.bucket}"
        return f"/{key}"

    def url_of(self, key: str) -> str:
        return self.base + quote(self._path(key))

    # —— 发请求 ——

    def _send(self, method: str, path: str, *, params: dict[str, str] | None = None,
              headers: dict[str, str] | None = None, body: bytes | None = None) -> tuple[bytes, dict[str, str]]:
        """签名、发出、按需重试(每次重签 —— 签名里有时间)。失败翻成 StorageError。"""
        params = params or {}
        url = self.base + quote(path) + (f"?{query_string(params)}" if params else "")
        attempt = 0
        while True:
            signed = self.dialect.sign(self, method=method, path=path, params=params,
                                       headers={"host": self.host, **(headers or {})}, body=body, now=_now())
            try:
                return _request(url, method=method, headers=signed, body=body)
            except (_HttpFailure, urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt < RETRIES and _retryable(exc):
                    attempt += 1
                    _sleep(2 ** (attempt - 1))
                    continue
                raise StorageError(explain(exc, host=self.host, bucket=self.bucket, locale=self.locale)) from exc

    # —— 上传 ——

    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
        """一次 PUT 传完(小文件)。"""
        self._send("PUT", self._path(key), body=data,
                   headers={"content-type": content_type, "content-length": str(len(data))})

    def upload_file(self, key: str, path: str, *, content_type: str, reporter: Reporter) -> None:
        """传一个本地文件。小的一次 PUT,大的分片;片与片之间报进度、看取消。"""
        size = os.path.getsize(path)
        if size <= MULTIPART_THRESHOLD:
            with open(path, "rb") as handle:
                self.put(key, handle.read(), content_type=content_type)
            reporter.progress(1.0, line(self.locale, "已上传", "Uploaded"))
            return
        self._multipart(key, path, size, content_type=content_type, reporter=reporter)

    def _multipart(self, key: str, path: str, size: int, *, content_type: str, reporter: Reporter) -> None:
        object_path = self._path(key)
        part_bytes = max(PART_BYTES, -(-size // MAX_PARTS))
        body, _ = self._send("POST", object_path, params={"uploads": ""}, body=b"",
                             headers={"content-type": content_type, "content-length": "0"})
        upload_id = str(_parse(body).get("UploadId") or "").strip()
        if not upload_id:
            raise StorageError(line(self.locale, "对象存储没有给出分片上传的 UploadId",
                                    "The storage service returned no UploadId for the multipart upload"))
        etags: list[str] = []
        try:
            sent = 0
            for number, chunk in enumerate(_chunks(path, part_bytes), start=1):
                if reporter.cancelled():
                    raise Cancelled(line(self.locale, "已取消上传", "Upload cancelled"))
                _, response_headers = self._send(
                    "PUT", object_path, params={"partNumber": str(number), "uploadId": upload_id}, body=chunk,
                    headers={"content-type": "application/octet-stream", "content-length": str(len(chunk))},
                )
                etag = response_headers.get("etag", "")
                if not etag:
                    raise StorageError(line(self.locale, f"第 {number} 片传完没有拿到 ETag",
                                            f"Part {number} returned no ETag"))
                etags.append(etag)
                sent += len(chunk)
                reporter.progress(sent / size, line(self.locale, f"已上传 {_mb(sent)} / {_mb(size)}",
                                                    f"Uploaded {_mb(sent)} of {_mb(size)}"))
            done = self._completion(etags)
            body, _ = self._send("POST", object_path, params={"uploadId": upload_id}, body=done,
                                 headers={"content-type": "application/json" if self.provider.json_api
                                          else "application/xml", "content-length": str(len(done))})
            # S3 的 Complete 可能 **200 里带着一个错误**(合并到一半失败)—— 光看状态码会把它当成功。
            reply = _parse(body)
            if reply.get("__root__") == "Error":
                raise StorageError(f"{reply.get('Code', '')} {reply.get('Message', '')}".strip())
        except BaseException:
            # 分片留在桶里是要收存储费的,而且在控制台里看不见 —— 失败或取消都要 Abort。
            try:
                self._send("DELETE", object_path, params={"uploadId": upload_id})
            except StorageError:
                pass
            raise

    def _completion(self, etags: list[str]) -> bytes:
        """CompleteMultipartUpload 的正文:分片号 + ETag。TOS 收 JSON,别家收 XML(官方 SDK 各自的写法)。"""
        if self.provider.json_api:
            parts = [{"PartNumber": number, "ETag": etag} for number, etag in enumerate(etags, start=1)]
            return json.dumps({"Parts": parts}, separators=(",", ":")).encode("utf-8")
        manifest = "".join(f"<Part><PartNumber>{n}</PartNumber><ETag>{e}</ETag></Part>"
                           for n, e in enumerate(etags, start=1))
        return f"<CompleteMultipartUpload>{manifest}</CompleteMultipartUpload>".encode("utf-8")

    # —— 链接 ——

    def clamp_expires(self, raw) -> int:
        """有效期(秒):没给用默认;给错了当场说;超过这一家的上限就按上限签(结果里如实交回签了多久)。"""
        if raw in (None, ""):
            return DEFAULT_EXPIRES
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise StorageError(line(self.locale, f"有效期要是秒数,收到的是「{raw}」",
                                    f"Expiry must be a number of seconds, got “{raw}”")) from None
        if value <= 0:
            raise StorageError(line(self.locale, "有效期要大于 0 秒", "Expiry must be more than 0 seconds"))
        ceiling = self.provider.max_expires
        return min(value, ceiling) if ceiling else value

    def presign(self, key: str, *, expires: int = DEFAULT_EXPIRES, method: str = "GET") -> str:
        """一条**限时**直链。桶不必设成公共读 —— 签名在查询串里,谁拿到谁能下。"""
        path = self._path(key)
        query = self.dialect.presign(self, method=method, path=path, expires=expires, now=_now())
        return f"{self.base}{quote(path)}?{query}"

    def public_url(self, key: str) -> str:
        """桶设成公共读时的那条地址。**没设的话它会 403** —— 所以工具同时交回限时直链。"""
        return self.url_of(key)

    # —— 列目录 ——

    def listing(self, prefix: str = "", limit: int = 100, cursor: str = "") -> tuple[list[dict], str]:
        """一页对象,和下一页的游标(没有下一页是空串)。"""
        params = {"max-keys": str(max(1, min(int(limit or 100), MAX_KEYS)))}
        if self.dialect.list_v2:
            params["list-type"] = "2"
            if cursor:
                params["continuation-token"] = cursor
        elif cursor:
            params["marker"] = cursor
        if prefix:
            params["prefix"] = prefix
        body, _ = self._send("GET", self._path(), params=params)
        page = _parse(body)
        out = [
            {
                "key": str(item.get("Key") or ""),
                "size": int(item.get("Size") or 0),
                "last_modified": str(item.get("LastModified") or ""),
            }
            for item in _items(page.get("Contents")) if isinstance(item, dict)
        ]
        truncated = str(page.get("IsTruncated") or "").strip().lower() == "true"
        following = ""
        if truncated:
            following = str(page.get("NextContinuationToken") or page.get("NextMarker") or "").strip()
            if not following and not self.dialect.list_v2 and out:
                # V1 不带分隔符时可以不给 NextMarker:下一页从这一页最后一个键之后开始(S3 / COS 文档同一条)。
                following = out[-1]["key"]
        return out, following


def _chunks(path: str, size: int) -> Iterator[bytes]:
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(size)
            if not chunk:
                return
            yield chunk


def _mb(size: int) -> str:
    return f"{size / 1024 / 1024:.1f} MB"


def content_hash(path: str) -> str:
    """文件内容的 SHA-256(流式算,不整个读进内存)。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


#: 常见后缀 → Content-Type。**要发对**:供应商按它判断这是不是一段视频,发成
#: `application/octet-stream` 的话对面可能直接拒。
_TYPES = {
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".m4v": "video/x-m4v",
    ".mkv": "video/x-matroska",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".aac": "audio/aac", ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
    ".gif": "image/gif", ".json": "application/json", ".txt": "text/plain", ".srt": "application/x-subrip",
    ".vtt": "text/vtt", ".pdf": "application/pdf",
}


def content_type_of(name: str) -> str:
    return _TYPES.get(os.path.splitext(name)[1].lower(), "application/octet-stream")


def run(tools: dict[str, Callable[[dict, str], dict]], *, streaming: frozenset[str] = frozenset()) -> None:
    """stdio 协议的外壳:读一个请求,写一个响应(流式工具前面还有若干进度行)。"""
    try:
        request = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error": f"bad request json: {exc}"}))
        return
    locale = str(request.get("locale") or os.environ.get("MOSAEL_LOCALE") or "zh")
    name = str(request.get("tool") or "")
    handler = tools.get(name)
    if handler is None:
        print(json.dumps({"ok": False, "error": f"unknown tool: {name}"}))
        return
    try:
        output = handler(dict(request.get("input") or {}), locale, Reporter(stream=name in streaming))
    except StorageError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return
    except Exception as exc:  # noqa: BLE001 —— 插件的异常不该只剩一个栈
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return
    print(json.dumps({"ok": True, "output": output}, ensure_ascii=False))
