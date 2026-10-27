"""`blender-host-is-ipv4`:Blender 连接的主机从 `::1` 改成 `127.0.0.1`。

`::1` 这一项从来连不上:mcp-for-blender 2.0.3 的 MCP 服务和 Blender 里的 Add-on 两头都开的是 IPv4 套接字
(`socket.AF_INET`),拿 `::1` 去连直接是「nodename nor servname provided」,界面上说的却是「Add-on 没开」。
清单里的这一项删了;存着它的连接在这里改成同一台机器的 IPv4 回环,别的包、别的键一样不碰,再跑一次什么都不动。
"""

from __future__ import annotations

import json
import socket
from pathlib import Path


MANIFEST = Path(__file__).resolve().parents[2] / "plugins" / "examples" / "blender" / "mosael.plugin.json"


def test_ipv6回环本来就连不上_AF_INET的套接字认不得它() -> None:
    """钉住删掉这一项的理由:上游两头用的是 AF_INET。"""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.connect(("::1", 9))
    except OSError as exc:
        assert not isinstance(exc, ConnectionRefusedError), "连得上 IPv4 地址族的 ::1?那这条迁移就没有理由了"
    else:  # pragma: no cover
        raise AssertionError("AF_INET 连上了 ::1")
    finally:
        probe.close()


def test_清单里不再有ipv6回环() -> None:
    host = next(f for f in json.loads(MANIFEST.read_text(encoding="utf-8"))["instance"]["config"] if f["key"] == "BLENDER_HOST")
    assert [o["value"] for o in host["options"]] == ["127.0.0.1", "localhost"]
