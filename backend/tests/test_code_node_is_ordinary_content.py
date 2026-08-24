"""隔离到位之后,`code` 节点退回成**普通的内容编辑**。

此前它是「主机权限」:落库要部署管理员。那道闸(`ensure_graph_node_privileges`)本来就是缺沙箱
的补丁 —— 执行器不是沙箱,于是只好用角色去挡,而在多租户产品里「谁有资格写代码」是个错问题
(ADR 0008 D2)。正确的问题是「任何人写的代码跑起来能不能伤到别人」,那由 domain/sandbox 回答,
用例在 tests/test_sandbox.py。

这一组锁住撤闸之后的行为:editor 存得下 code 节点,而它跑在隔离里;隔离不可用时**执行**被拒,
不是保存被拒 —— 一张存着但这台机器上跑不了的图,和一张存不下的图，是两回事。
"""

from __future__ import annotations

from app.domain import sandbox
from tests.util import fresh_client, second_client

CODE_GRAPH = {
    "nodes": [
        {"id": "start_1", "type": "start", "config": {}},
        {"id": "code_1", "type": "code", "config": {"code": "output = 1"}},
    ],
    "edges": [],
}


def _editor_client():
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{workspace['id']}/invitations", json={"username": "mate", "role": "editor"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")
    return mate, workspace["id"]


def test_an_editor_can_save_a_code_node() -> None:
    """写代码是内容编辑。挡它的那道闸是缺沙箱时的补丁,沙箱到位就该撤。"""
    editor, workspace_id = _editor_client()
    made = editor.post("/api/workflows", json={"workspace_id": workspace_id, "name": "W", "graph": CODE_GRAPH})
    assert made.status_code == 200, made.text


def test_it_actually_runs_and_stays_isolated() -> None:
    """存得下不等于放开了 —— 它跑在 domain/sandbox 里。"""
    if sandbox.active_backend() is None:
        import pytest

        pytest.skip("这台机器上没有可用的隔离后端")
    from app.domain.workflows.executors.basic import run_python

    assert run_python("output = 6 * 7", {})["output"] == 42

    # 判据是「宿主机的东西看不见」,不是「某个系统调用被拒绝」—— 两种后端挡住它的方式不同
    # (seatbelt 内核拒绝 / docker 里那个文件根本不存在),测症状会把换了种挡法误报成漏了。
    # 详见 tests/test_sandbox.py 里同名那几条的说明。
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(dir=Path.home(), prefix=".openstudio-sentinel-", suffix=".txt") as sentinel:
        sentinel.write(b"host-only-secret")
        sentinel.flush()
        blocked = run_python(
            "import os\n"
            f"p = {str(sentinel.name)!r}\n"
            "try:\n"
            "    output = 'leaked' if 'host-only-secret' in open(p).read() else 'blocked'\n"
            "except OSError:\n"
            "    output = 'blocked'\n",
            {},
        )
    assert blocked["output"] == "blocked", f"沙箱读到了宿主机的文件:{blocked['output']}"


def test_without_isolation_execution_is_refused_but_saving_is_not(monkeypatch) -> None:
    """隔离不可用时拒绝的是**执行**,不是保存。

    保存一张图是内容;能不能在这台机器上跑它是部署的事实。把后者做成保存时的闸,等于让一个人
    在 A 机器上存的东西到 B 机器上就存不下 —— 而图是跟着数据走的。
    """
    editor, workspace_id = _editor_client()
    monkeypatch.setattr(sandbox, "_BACKENDS", ())
    sandbox.active_backend.cache_clear()
    try:
        made = editor.post(
            "/api/workflows", json={"workspace_id": workspace_id, "name": "W2", "graph": CODE_GRAPH}
        )
        assert made.status_code == 200, made.text

        from app.domain.workflows import WorkflowDomainError
        from app.domain.workflows.executors.basic import run_python
        import pytest

        with pytest.raises(WorkflowDomainError) as caught:
            run_python("output = 1", {})
        assert "Docker" in str(caught.value)
    finally:
        sandbox.active_backend.cache_clear()
