"""Safe transfer of provider input/output media across HTTP trust boundaries.

住在 `ai/` 下而不是 `ai/providers/` 下:下载模型权重的运行时(`ai/runtime`)也要用它,而它
放在 providers 里时,runtime 只能反过来 import providers —— 后端唯一的一处双向依赖就是这么
来的。这段代码谁都不属于:它是「跨信任边界搬一份媒体」这件事本身。

Provider API clients carry bearer/API-key headers. Generated assets usually live on a
pre-signed object-storage URL, and user-supplied source URLs may point anywhere. Reusing the
API client for either leaks credentials (or invalidates the signature). This module is the
single seam that decides whether a hop is trusted and drops headers again after a cross-origin
redirect.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.http_retry import RetryingClient, backoff_seconds
from app.core.i18n import LocalizedError

_MAX_REDIRECTS = 5

#: 下到一半断了(连接被重置、读超时、对面没发完就关了)之后,从断的地方接着下,最多接这么多次。
_RESUME_ATTEMPTS = 5


class MediaDownloadError(LocalizedError, RuntimeError):
    """一份远端媒体没能拉回本地:断了几次都没接上、链接过期、对面不给。`detail` 是脱敏过的原因(不带签名链接)。

    **故意不是 httpx 的异常。** 供应商适配器把 httpx 异常一律翻成「X 请求失败」—— 下载断线也被说成了供应商出错,而
    那一刻服务商早就做完、扣了钱。它从适配器的 `except httpx.HTTPError` 旁边穿过去,由调用方说一句对得上的话:生成的
    运行器说「已经生成好了,只是没取回来,可以重新取回」(见 generation.runner);下模型权重的说「下载失败」。
    """

    def __init__(self, detail: str) -> None:
        super().__init__("transferErr_downloadFailed", detail=detail)


def _failure_detail(exc: BaseException) -> str:
    """下载失败的原因,**不带地址**:成片地址是带签名的预签名链接,httpx 的状态码异常会把整条地址写进消息里。"""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    text = str(exc) or exc.__class__.__name__
    return re.sub(r"https?://\S+", "<url>", text)[:200]


@dataclass(frozen=True)
class DownloadedBytes:
    data: bytes
    content_type: str


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80 if parsed.scheme.lower() == "http" else None
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


def trusted_headers_for_url(url: str, trusted_base_url: str, headers: dict[str, str] | None) -> dict[str, str]:
    """Return credentials only when the absolute URL is exactly same-origin as the API."""
    if not headers or not trusted_base_url or _origin(url) != _origin(trusted_base_url):
        return {}
    return dict(headers)


def _redirect_target(current: str, response) -> str | None:
    if not response.is_redirect:
        return None
    location = str(response.headers.get("location") or "").strip()
    return urljoin(current, location) if location else None


def download_to_path(
    url: str,
    target: Path,
    *,
    timeout: float = 180,
    trusted_base_url: str = "",
    trusted_headers: dict[str, str] | None = None,
) -> str:
    """Stream a remote asset to disk without carrying credentials across origins.

    **下到一半断了就从断的地方接着下**(`Range`,最多接 `_RESUME_ATTEMPTS` 次):几百 MB 的成片走家庭网络或代理,断
    一下是常事,而此前断一下整份就丢了 —— 那一刻服务商早已做完、扣了钱。对面不认 Range(回 200 而不是 206)就从头
    重下。收完按 `Content-Length` / `Content-Range` 对一遍长度,短了也算断了。接不上、链接过期、对面拒绝,抛
    `MediaDownloadError`(不是 httpx 的异常,见它的说明)。半截文件只在 `.part` 里,成功才换到 `target`。
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{target.name}.part")
    try:
        with partial.open("wb") as handle:
            for attempt in range(_RESUME_ATTEMPTS + 1):
                try:
                    content_type, total = _receive(
                        str(url), handle, timeout=timeout, trusted_base_url=trusted_base_url,
                        trusted_headers=trusted_headers,
                    )
                except httpx.TransportError as exc:
                    # 连上了又断了(或者这一次压根没连上):攒下的留着,下一次从这里接着要。
                    if attempt == _RESUME_ATTEMPTS:
                        raise MediaDownloadError(_failure_detail(exc)) from exc
                    handle.flush()
                    time.sleep(backoff_seconds(attempt))
                    continue
                except httpx.HTTPStatusError as exc:
                    # 链接过期(403)、对面没有(404)这一类:再要也一样。
                    raise MediaDownloadError(_failure_detail(exc)) from exc
                if total is not None and handle.tell() < total:
                    # 对面说了多长却没发够就收了尾:和断线一样,接着要剩下的。
                    if attempt == _RESUME_ATTEMPTS:
                        raise MediaDownloadError(f"incomplete body: {handle.tell()} of {total} bytes")
                    time.sleep(backoff_seconds(attempt))
                    continue
                break
        partial.replace(target)
        return content_type
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _receive(
    url: str,
    handle: BinaryIO,
    *,
    timeout: float,
    trusted_base_url: str,
    trusted_headers: dict[str, str] | None,
) -> tuple[str, int | None]:
    """连一次、收一段:跟重定向,文件里已经有 `handle.tell()` 字节时带 `Range` 从那里接着要。返回 (content-type, 总长或 None)。"""
    offset = handle.tell()
    current = url
    for _hop in range(_MAX_REDIRECTS + 1):
        headers = trusted_headers_for_url(current, trusted_base_url, trusted_headers)
        if offset:
            headers = {**headers, "Range": f"bytes={offset}-"}
        with RetryingClient(timeout=timeout, headers=headers, follow_redirects=False) as client:
            with client.stream("GET", current) as response:
                redirected = _redirect_target(current, response)
                if redirected is not None:
                    current = redirected
                    continue
                response.raise_for_status()
                if offset and response.status_code != 206:
                    # 对面不认 Range,回的是整份:从头收。
                    handle.seek(0)
                    handle.truncate()
                    offset = 0
                total = _total_length(response, offset)
                for chunk in response.iter_bytes():
                    handle.write(chunk)
                return str(response.headers.get("content-type") or "").split(";", 1)[0].strip(), total
    raise MediaDownloadError(f"more than {_MAX_REDIRECTS} redirects")


def _total_length(response: httpx.Response, offset: int) -> int | None:
    """这份东西一共多长(按它自己说的);说不清、或者传输时压缩过(解压后长度对不上),就是 None —— 不核对。"""
    if response.headers.get("content-encoding"):
        return None
    if response.status_code == 206:
        found = re.match(r"bytes\s+\d+-\d+/(\d+)", str(response.headers.get("content-range") or ""))
        return int(found.group(1)) if found else None
    length = response.headers.get("content-length")
    return offset + int(length) if length and length.isdigit() else None


def fetch_bytes(
    url: str,
    *,
    timeout: float = 120,
    max_bytes: int = 64 * 1024 * 1024,
    trusted_base_url: str = "",
    trusted_headers: dict[str, str] | None = None,
) -> DownloadedBytes:
    """Fetch a bounded source asset for APIs that require inline/multipart bytes."""
    current = str(url)
    for _hop in range(_MAX_REDIRECTS + 1):
        headers = trusted_headers_for_url(current, trusted_base_url, trusted_headers)
        with RetryingClient(timeout=timeout, headers=headers, follow_redirects=False) as client:
            with client.stream("GET", current) as response:
                redirected = _redirect_target(current, response)
                if redirected is not None:
                    current = redirected
                    continue
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise ValueError(f"Remote media exceeds {max_bytes} bytes")
                return DownloadedBytes(
                    bytes(body),
                    str(response.headers.get("content-type") or "").split(";", 1)[0].strip(),
                )
    raise RuntimeError(f"Too many redirects while downloading media: {url}")


def put_to_presigned_url(url: str, data: bytes, headers: dict[str, str] | None = None, *, timeout: float = 600) -> None:
    """把字节 PUT 到供应商发的预签名上传地址(HeyGen 的直传)。

    **不带任何凭据**:地址本身就是授权,供应商的 Key 不该跟着去对象存储那边;对面要求的头(`upload_headers`)
    原样带上 —— 签名里签过它们,少一个就 403。
    """
    with RetryingClient(timeout=timeout, follow_redirects=False) as client:
        client.put(url, content=data, headers=dict(headers or {})).raise_for_status()


__all__ = [
    "DownloadedBytes",
    "MediaDownloadError",
    "download_to_path",
    "fetch_bytes",
    "put_to_presigned_url",
    "trusted_headers_for_url",
]
