"""插件接入归配它的那个人,不是这台部署共用一份。

和供应商连接同一条(见 test_connections_belong_to_a_person)。**包**和**接入**是两件事:

  - `plugin_packages` 是这台机器上装了什么 —— 扫描目录得来的,像 vendor 预设,仍归部署;
  - `plugin_instances` 是"我用我的账号接上了 TikHub" —— 配置、凭据、权限、暴露哪些工具,
    全是他自己的选择,花的也是他自己的额度。

此前整份都是部署级的:接入由管理员配一次,所有人的智能体共用那一把第三方密钥。于是用量算不到
人头上(管理页那张按人分的花销图看不到插件调用),而一个新账号一进插件页就看到别人接好的一排。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import PluginInstance
from tests.test_plugins import KEYED, install
from tests.util import second_client


def _instance(client, package_id: str, name: str) -> str:
    created = client.post(f"/api/plugins/{package_id}/instances", json={"name": name})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _first_package(client) -> str:
    return client.get("/api/plugins").json()[0]["id"]


def _my_instances(client) -> list[dict]:
    """实例嵌在包里返回(没有独立的列表端点)。"""
    return [inst for pkg in client.get("/api/plugins").json() for inst in pkg["instances"]]


def test_a_new_account_sees_no_instances() -> None:
    admin = install(KEYED)
    _instance(admin, _first_package(admin), "管理员接的")

    mate = second_client("mate")

    assert _my_instances(mate) == []


def test_anyone_can_add_their_own() -> None:
    """接一个插件不再要部署管理员 —— 那是他自己的账号、他自己的额度。"""
    admin = install(KEYED)
    package_id = _first_package(admin)
    mate = second_client("mate")

    mine = _instance(mate, package_id, "我接的")

    assert [row["id"] for row in _my_instances(mate)] == [mine]


def test_i_cannot_touch_someone_elses() -> None:
    admin = install(KEYED)
    theirs = _instance(admin, _first_package(admin), "管理员接的")
    mate = second_client("mate")

    assert mate.patch(f"/api/plugins/instances/{theirs}", json={"name": "改名"}).status_code == 404
    assert mate.delete(f"/api/plugins/instances/{theirs}").status_code == 404
    assert mate.get(f"/api/plugins/instances/{theirs}/credentials").status_code == 404
    with SessionLocal() as db:
        assert db.get(PluginInstance, theirs) is not None, "被别人删掉了"


def test_the_package_list_is_still_the_machines() -> None:
    """装了什么是这台机器的事实,人人看得到 —— 但只有管理员能扫、能删。"""
    admin = install(KEYED)
    assert len(admin.get("/api/plugins").json()) >= 1
    mate = second_client("mate")

    assert len(mate.get("/api/plugins").json()) >= 1
    assert mate.post("/api/plugins/scan").status_code == 403


def test_his_tools_do_not_leak_into_my_agent() -> None:
    """智能体的工具表只含**我自己**接好的插件 —— 否则我的智能体用着别人的第三方密钥。"""
    admin = install(KEYED)
    theirs = _instance(admin, _first_package(admin), "管理员接的")
    admin.patch(f"/api/plugins/instances/{theirs}/permissions", json={"granted": []})
    mate = second_client("mate")

    tools = mate.get("/api/agent/tools").json()

    assert not [tool for tool in tools if tool["name"].startswith("plugin__")], "别人接的插件工具进了我的工具表"


def test_clearing_my_call_log_is_not_an_uninstall() -> None:
    """`DELETE /plugins/invocations` 曾被 `/plugins/{package_id}` 吃掉。

    FastAPI 按声明顺序匹配,那条吃通配的路径在上面时,清空调用记录被当成"卸载一个叫
    invocations 的包" —— 连部署管理员来也是一句 "Plugin not found",这件事从来没成功过。
    两条路由都要求管理员的年代看不出来:两边都是 4xx,像权限不够。
    """
    admin = install(KEYED)

    assert admin.delete("/api/plugins/invocations").status_code == 204


def test_someone_elses_call_log_is_not_mine() -> None:
    """记录里带着每次调用的 input/output —— 别人的请求参数和返回内容没有理由出现在我这儿。"""
    admin = install(KEYED)
    _instance(admin, _first_package(admin), "管理员接的")
    mate = second_client("mate")

    assert mate.get("/api/plugins/invocations").json() == []


def test_my_workflow_cannot_run_on_someone_elses_instance() -> None:
    """工作流里的插件节点,落到的连接也得是**跑这条流程的人**自己的。

    此前节点解析连接时不按人过滤:我没接这个插件,「只有一个可用连接就自动用它」就自动用上
    管理员那条 —— 拿着他的第三方密钥、花他的额度,账上看不出是我;点名他的连接 id 也照跑。
    """
    import pytest

    from app.db.models import User, Workflow, Workspace
    from app.domain.plugins.nodes import node_type_id
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.executors import get_executor
    from tests.test_plugins import SIMPLE
    from tests.util import acting_as

    admin = install(SIMPLE)
    theirs = _my_instances(admin)[0]["id"]
    assert admin.patch(f"/api/plugins/instances/{theirs}", json={"enabled": True}).status_code == 200
    second_client("mate")
    run = get_executor(node_type_id("dev.simple", "shout"))

    with SessionLocal() as db:
        mate_id = db.query(User).filter(User.username == "mate").one().id
        workflow = Workflow(workspace_id=db.query(Workspace).first().id, name="借用", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.flush()
        with acting_as(db, mate_id):
            with pytest.raises(WorkflowDomainError) as auto:
                run(db, workflow, {"text": "hi"})
            assert auto.value.key == "pluginErr_noInstance"
            with pytest.raises(WorkflowDomainError) as named:
                run(db, workflow, {"text": "hi", "instance_id": theirs})
            assert named.value.key == "pluginErr_instanceGone"
        # 对照:接了它的人自己跑,照常自动选中他那唯一一条。
        with acting_as(db, None):
            assert run(db, workflow, {"text": "hi"})["output"]["loud"] == "HI"


def test_选连接只在执行者自己的连接里找() -> None:
    """resolve_instance 是工作流节点和(以后)画板上的工具共用的那一条:执行者由调用方给,
    不从上下文猜。别人存下的连接 id 对我不可用;执行者是连接的主人时,同一个 id 照常可用。"""
    import pytest

    from app.db.models import User
    from app.domain.plugins import PluginDomainError
    from app.domain.plugins.nodes import resolve_instance
    from tests.test_plugins import SIMPLE

    admin = install(SIMPLE)
    theirs = _my_instances(admin)[0]["id"]
    assert admin.patch(f"/api/plugins/instances/{theirs}", json={"enabled": True}).status_code == 200
    second_client("mate")

    with SessionLocal() as db:
        mate_id = db.query(User).filter(User.username == "mate").one().id
        owner_id = db.get(PluginInstance, theirs).owner_user_id
        with pytest.raises(PluginDomainError) as named:
            resolve_instance(db, "dev.simple", "shout", theirs, mate_id)
        assert named.value.key == "pluginErr_instanceGone"
        with pytest.raises(PluginDomainError) as auto:
            resolve_instance(db, "dev.simple", "shout", "", mate_id)
        assert auto.value.key == "pluginErr_noInstance"
        assert resolve_instance(db, "dev.simple", "shout", theirs, owner_id) == theirs
        assert resolve_instance(db, "dev.simple", "shout", "", owner_id) == theirs
