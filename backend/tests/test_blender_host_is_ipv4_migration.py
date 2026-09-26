"""`blender-host-is-ipv4`:Blender 连接的主机从 `::1` 改成 `127.0.0.1`。

`::1` 这一项从来连不上:mcp-for-blender 2.0.3 的 MCP 服务和 Blender 里的 Add-on 两头都开的是 IPv4 套接字
(`socket.AF_INET`),拿 `::1` 去连直接是「nodename nor servname provided」,界面上说的却是「Add-on 没开」。
清单里的这一项删了;存着它的连接在这里改成同一台机器的 IPv4 回环,别的包、别的键一样不碰,再跑一次什么都不动。
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

from app.core.db import SessionLocal
from app.db.migrations import _migrate_blender_host_is_ipv4 as migrate
from app.db.models import PluginInstance, PluginPackage
from tests.util import fresh_client, user_id

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


def test_存着ipv6回环的连接改成127_别的不碰_再跑一次不动() -> None:
    fresh_client()
    me = user_id("tester")
    with SessionLocal() as db:
        db.add_all([
            PluginPackage(id="dev.mosael.blender", name="Blender MCP", version="0.3.0", manifest={}),
            PluginPackage(id="dev.example.other", name="Other", version="1.0.0", manifest={}),
        ])
        db.flush()
        db.add_all([
            PluginInstance(id="b6", owner_user_id=me, package_id="dev.mosael.blender", name="B",
                           config={"BLENDER_HOST": "::1", "BLENDER_PORT": "9877", "DISABLE_TELEMETRY": "true"}),
            PluginInstance(id="b4", owner_user_id=me, package_id="dev.mosael.blender", name="B",
                           config={"BLENDER_HOST": "localhost", "BLENDER_PORT": "9876"}),
            PluginInstance(id="other", owner_user_id=me, package_id="dev.example.other", name="O",
                           config={"BLENDER_HOST": "::1"}),
        ])
        db.commit()

    migrate()
    migrate()

    with SessionLocal() as db:
        assert db.get(PluginInstance, "b6").config == {"BLENDER_HOST": "127.0.0.1", "BLENDER_PORT": "9877", "DISABLE_TELEMETRY": "true"}
        assert db.get(PluginInstance, "b4").config == {"BLENDER_HOST": "localhost", "BLENDER_PORT": "9876"}
        assert db.get(PluginInstance, "other").config == {"BLENDER_HOST": "::1"}
