"""最小的 WebSocket 客户端(RFC 6455,只收文本帧),标准库手写。

ComfyUI 的**真实进度**只在 WebSocket 上:哪个节点在跑、采样器第几步、哪些节点命中了缓存。
HTTP 那一侧只能轮询 `/history` 和 `/queue` —— 看得到排队、看得到结束,看不到中间。

只做这件事需要的那一小块:握手、读帧(文本拼接分片,二进制预览图丢掉,ping 回 pong,
close 就结束)。发出去的只有 pong 和 close(客户端帧要加掩码)。连不上、握手不对、中途断了,
调用方一律退回轮询 —— 进度是锦上添花,拿不到绝不影响生成。
"""

from __future__ import annotations

import base64
import os
import select
import socket
import ssl
import struct
from urllib.parse import urlsplit


class WebSocketClosed(Exception):
    """连接断了或对面关了。"""


class WebSocket:
    def __init__(self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 5.0) -> None:
        parts = urlsplit(url)
        secure = parts.scheme == "wss"
        host = parts.hostname or "127.0.0.1"
        port = parts.port or (443 if secure else 80)
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        sock = socket.create_connection((host, port), timeout=timeout)
        if secure:
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
        self._sock = sock
        self._buffer = b""
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {f'[{host}]' if ':' in host else host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            + "".join(f"{name}: {value}\r\n" for name, value in (headers or {}).items())
            + "\r\n"
        )
        sock.sendall(handshake.encode("latin-1"))
        head = self._read_until(b"\r\n\r\n", limit=16384)
        status = head.split(b"\r\n", 1)[0]
        if b" 101" not in status:
            self.close()
            raise WebSocketClosed(status.decode("latin-1", "replace"))

    # --- 读 ---------------------------------------------------------------

    def _fill(self) -> None:
        # 读的时候断了(对面重置、读超时、TLS 出错)都是「连接没了」:调用方退回轮询,而不是让这次生成失败
        try:
            chunk = self._sock.recv(65536)
        except OSError as exc:
            raise WebSocketClosed(str(exc) or type(exc).__name__) from exc
        if not chunk:
            raise WebSocketClosed("connection closed")
        self._buffer += chunk

    def _read_until(self, marker: bytes, *, limit: int) -> bytes:
        while marker not in self._buffer:
            if len(self._buffer) > limit:
                raise WebSocketClosed("handshake too long")
            self._fill()
        head, self._buffer = self._buffer.split(marker, 1)
        return head

    def _read_exact(self, size: int) -> bytes:
        while len(self._buffer) < size:
            self._fill()
        data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data

    def _readable(self, timeout: float) -> bool:
        # TLS 层可能已经解好一段还没取走的数据:select 看不见它,只看套接字本身
        if self._buffer or (isinstance(self._sock, ssl.SSLSocket) and self._sock.pending()):
            return True
        try:
            ready, _, _ = select.select([self._sock], [], [], timeout)
        except (OSError, ValueError) as exc:
            raise WebSocketClosed(str(exc) or type(exc).__name__) from exc
        return bool(ready)

    def recv(self, timeout: float) -> str | None:
        """等一条文本消息,最多 `timeout` 秒。这期间没有完整消息就回 None(不丢已经收到一半的帧)。"""
        if not self._readable(timeout):
            return None
        # 一旦开始读一帧就读完它:帧读到一半停下,下一次就对不上边界了。
        try:
            self._sock.settimeout(30.0)
        except OSError as exc:
            raise WebSocketClosed(str(exc) or type(exc).__name__) from exc
        message = b""
        text = False
        while True:
            first, second = self._read_exact(2)
            fin = bool(first & 0x80)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if second & 0x80 else b""
            payload = self._read_exact(length)
            if mask:
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            if opcode == 0x8:
                self.close()
                raise WebSocketClosed("closed by server")
            if opcode == 0x9:
                self._send(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x2):
                text = opcode == 0x1
                message = payload
            elif opcode == 0x0:
                message += payload
            if fin:
                break
        # 二进制帧是预览图,不是消息 —— 让调用方接着等下一条。
        return message.decode("utf-8", "replace") if text else ""

    # --- 写 ---------------------------------------------------------------

    def _send(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        header = bytes([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header += bytes([0x80 | length])
        elif length < 65536:
            header += bytes([0x80 | 126]) + struct.pack("!H", length)
        else:
            header += bytes([0x80 | 127]) + struct.pack("!Q", length)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        try:
            self._sock.sendall(header + mask + masked)
        except OSError as exc:
            raise WebSocketClosed(str(exc)) from exc

    def close(self) -> None:
        try:
            self._send(0x8, b"")
        except Exception:  # noqa: BLE001 — 关的时候对面已经不在了也无所谓
            pass
        try:
            self._sock.close()
        except OSError:
            pass
