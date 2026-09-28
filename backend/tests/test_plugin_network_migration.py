"""`migrate-plugin-connections-choose-their-network`:插件连接补上宿主给的「网络」两列,MinerU 自己那套搬过去。

MinerU 曾在清单里自带 `MINERU_NETWORK`(system / direct / proxy)与 `MINERU_PROXY`。清单里删掉之后,存着
它们的连接要按原意落到新的两列上、并从 config 里删掉;别的包、没设过的连接一律 follow(此前它们的子进程
里本来就没有代理变量,follow 在没配全局代理时给的正是这样的环境)。再跑一次什么都不动。
"""

from __future__ import annotations

import json

from sqlalchemy import inspect, text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_plugin_connections_choose_their_network as migrate
from app.db.models import PluginInstance, PluginPackage
from tests.util import fresh_client

MINERU = "dev.mosael.mineru"


def _columns() -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("plugin_instances")}


IDS = ("system", "direct", "proxy", "proxy-empty", "untouched", "other")


def _rows() -> dict[str, tuple[dict, str, str]]:
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, config, network_mode, proxy_url FROM plugin_instances")).all()
    return {row[0]: (json.loads(row[1]), row[2], row[3]) for row in rows if row[0] in IDS}


def test_老库补上两列_MinerU_的网络设置按原意搬过去_再跑一次不动() -> None:
    fresh_client()
    base = {"MINERU_MODEL": "vlm", "MINERU_LANGUAGE": "ch"}
    with SessionLocal() as db:
        #: MinerU 随应用内置,建库时已经登记了包。
        assert db.get(PluginPackage, MINERU) is not None
        db.add(PluginPackage(id="dev.example.other", name="Other", version="1.0.0", manifest={}))
        db.flush()
        db.add_all([
            PluginInstance(id="system", package_id=MINERU, name="M", owner_user_id="u",
                           config={**base, "MINERU_NETWORK": "system", "MINERU_PROXY": ""}),
            PluginInstance(id="direct", package_id=MINERU, name="M", owner_user_id="v",
                           config={**base, "MINERU_NETWORK": "direct", "MINERU_PROXY": "http://stale:1"}),
            PluginInstance(id="proxy", package_id=MINERU, name="M", owner_user_id="w",
                           config={**base, "MINERU_NETWORK": "proxy", "MINERU_PROXY": " http://127.0.0.1:7890 "}),
            #: 选了走代理却没填地址:当时每次调用都报错。搬成 follow,而不是一个永远用不了的「代理」。
            PluginInstance(id="proxy-empty", package_id=MINERU, name="M", owner_user_id="x",
                           config={**base, "MINERU_NETWORK": "proxy", "MINERU_PROXY": ""}),
            PluginInstance(id="untouched", package_id=MINERU, name="M", owner_user_id="y", config=dict(base)),
            #: 别的包里同名的键不是 MinerU 的那一对,不碰。
            PluginInstance(id="other", package_id="dev.example.other", name="O", owner_user_id="u",
                           config={"MINERU_NETWORK": "direct"}),
        ])
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE plugin_instances DROP COLUMN network_mode"))
        conn.execute(text("ALTER TABLE plugin_instances DROP COLUMN proxy_url"))
    engine.dispose()
    assert not {"network_mode", "proxy_url"} & _columns()

    migrate()
    engine.dispose()

    assert {"network_mode", "proxy_url"} <= _columns()
    expected = {
        "system": (base, "follow", ""),
        "direct": (base, "direct", ""),
        "proxy": (base, "proxy", "http://127.0.0.1:7890"),
        "proxy-empty": (base, "follow", ""),
        "untouched": (base, "follow", ""),
        "other": ({"MINERU_NETWORK": "direct"}, "follow", ""),
    }
    assert _rows() == expected

    migrate()
    engine.dispose()
    assert _rows() == expected
