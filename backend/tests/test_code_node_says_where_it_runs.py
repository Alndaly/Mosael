"""代码节点的说明写的是它实际跑在哪里。

说明此前写「与插件同级的本地信任沙箱」—— 那是代码节点还在本机子进程里跑时的话;隔离早已搬到
domain/sandbox(无网络的 Docker 容器),执行器里却还留着那一套子进程的包装和环境(没人调用)。
读说明的人会以为代码能联网、能读本机文件,或者以为它和插件一样被信任。
"""

from __future__ import annotations

import inspect

from app.core.i18n import t
from app.domain import sandbox
from app.domain.workflows.executors import basic


def test_说明说的是_Docker_容器_没有网络() -> None:
    zh, en = t("wfNode_code_desc", "zh"), t("wfNode_code_desc", "en")
    assert "Docker" in zh and "没有网络" in zh and "信任" not in zh
    assert "Docker" in en and "no network" in en and "trusted" not in en
    # 说明对得上实现:沙箱确实断网。
    assert '"--network=none"' in inspect.getsource(sandbox)


def test_执行器里不再留着本机子进程那一套() -> None:
    for name in ("_CODE_WRAPPER", "_code_node_env", "CODE_OUTPUT_CAP"):
        assert not hasattr(basic, name), name
