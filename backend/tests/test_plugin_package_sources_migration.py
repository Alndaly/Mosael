"""`migrate-plugin-connections-choose-package-sources`:包镜像改由宿主给,Manim / Remotion 自带的镜像配置项搬过去。

老版清单里 Manim 有 `PIP_INDEX_URL`、Remotion 有 `NPM_REGISTRY`(自由文本)。存着它们的连接要按原意落到
`plugin_instances.package_sources` 上 —— 正好是某个预设地址的记成预设 key —— 并从 config 里删掉;
别的包里同名的键不碰;`tts_config` 补上 npm 那一列。再跑一次什么都不动。
"""

from __future__ import annotations

import json

from sqlalchemy import inspect, text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_plugin_connections_choose_package_sources as migrate
from app.db.models import PluginInstance, PluginPackage
from tests.util import fresh_client

IDS = ("manim-preset", "manim-custom", "manim-empty", "remotion", "other")


def _rows() -> dict[str, tuple[dict, dict]]:
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, config, package_sources FROM plugin_instances")).all()
    return {row[0]: (json.loads(row[1]), json.loads(row[2])) for row in rows if row[0] in IDS}


def test_老连接里填的镜像搬成连接自己的覆盖_预设地址记成key_再跑一次不动() -> None:
    fresh_client()
    with SessionLocal() as db:
        for package_id in ("dev.mosael.manim", "dev.mosael.remotion", "dev.example.other"):
            db.add(PluginPackage(id=package_id, name=package_id, version="0.2.0", manifest={}))
        db.flush()
        db.add_all([
            PluginInstance(id="manim-preset", package_id="dev.mosael.manim", name="M", owner_user_id="u",
                           config={"PIP_INDEX_URL": "https://pypi.tuna.tsinghua.edu.cn/simple/", "UNRESTRICTED_CODE": "false"}),
            PluginInstance(id="manim-custom", package_id="dev.mosael.manim", name="M", owner_user_id="v",
                           config={"PIP_INDEX_URL": "https://pypi.corp.example/simple"}),
            PluginInstance(id="manim-empty", package_id="dev.mosael.manim", name="M", owner_user_id="w",
                           config={"PIP_INDEX_URL": ""}),
            PluginInstance(id="remotion", package_id="dev.mosael.remotion", name="R", owner_user_id="u",
                           config={"NPM_REGISTRY": "https://registry.npmmirror.com", "BROWSER_EXECUTABLE": "/x"}),
            #: 别的包里同名的键不是那两个插件的镜像项,不碰。
            PluginInstance(id="other", package_id="dev.example.other", name="O", owner_user_id="u",
                           config={"NPM_REGISTRY": "https://registry.npmmirror.com"}),
        ])
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE plugin_instances DROP COLUMN package_sources"))
        conn.execute(text("ALTER TABLE tts_config DROP COLUMN npm_registry"))
    engine.dispose()

    migrate()
    migrate()
    engine.dispose()

    assert "npm_registry" in {column["name"] for column in inspect(engine).get_columns("tts_config")}
    assert _rows() == {
        "manim-preset": ({"UNRESTRICTED_CODE": "false"}, {"pypi": "tsinghua"}),
        "manim-custom": ({}, {"pypi": "https://pypi.corp.example/simple"}),
        "manim-empty": ({}, {}),
        "remotion": ({"BROWSER_EXECUTABLE": "/x"}, {"npm": "npmmirror"}),
        "other": ({"NPM_REGISTRY": "https://registry.npmmirror.com"}, {}),
    }
