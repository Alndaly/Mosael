"""节点字段的动态选项(`options_from`)。

前端对所有带这个声明的字段走同一个接口,不认识具体节点。这里钉住:
1. 声明里用到的来源都真的存在 —— 写错一个名字,界面上就是一个永远空的下拉;
2. 引擎清单:克隆总在最前,只列就绪的,不列播客;
3. 音色清单跟着引擎变:克隆 → 工作区音色库(别的工作区的不列),其余 → 那个引擎的目录;
4. 接口本身:要有工作区权限,来源名写错说清楚。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.domain.workflows.field_options import OptionContext
from tests.util import fresh_client


def test_声明里用到的来源都存在() -> None:
    from app.domain.workflows import NODE_TYPES
    from app.domain.workflows.field_options import SOURCES

    used = {
        f"{name}.{key}": meta["options_from"]
        for name, spec in NODE_TYPES.items()
        for key, meta in (spec.get("config") or {}).items()
        if isinstance(meta, dict) and meta.get("options_from")
    }
    assert used, "至少语音节点在用"
    missing = {field: source for field, source in used.items() if source not in SOURCES}
    assert not missing, f"这些字段声明的选项来源不存在:{missing}"


def _ctx(workspace_id: str = "w", parent: str = ""):

    return OptionContext(workspace_id=workspace_id, user_id=None, parent=parent, locale="zh")


def test_引擎清单_克隆在前_只列就绪的_不列播客(monkeypatch) -> None:
    from app.domain.voices import engine_catalog
    from app.domain.workflows.field_options import field_options

    monkeypatch.setattr(engine_catalog, "describe_engines", lambda db=None, user_id=None: [
        {"id": "clone", "label": "ttsProvider_clone", "ready": False},
        {"id": "edge", "label": "Edge", "ready": True},
        {"id": "volcano", "label": "火山", "ready": False},
        {"id": engine_catalog.PODCAST_ENGINE, "label": "播客", "ready": True},
    ])
    options = field_options(None, "speech_engines", _ctx())
    assert [one["value"] for one in options] == ["clone", "edge"]
    assert options[0]["label"] == "克隆音色(配音库)"


def test_音色清单跟着引擎变(monkeypatch) -> None:
    from app.db.models import Voice, Workspace
    from app.domain.voices import engine_catalog
    from app.domain.workflows.field_options import field_options

    client = fresh_client()
    mine = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        other = Workspace(name="别人的")
        db.add(other)
        db.flush()
        db.add_all([
            Voice(workspace_id=mine, name="我的嗓子", reference_key="r1"),
            Voice(workspace_id=other.id, name="别人的嗓子", reference_key="r2"),
        ])
        db.commit()

        cloned = field_options(db, "speech_voices", _ctx(mine, parent="clone"))
        assert [one["label"] for one in cloned] == ["我的嗓子"]
        #: 没选引擎时按克隆算 —— 和执行体一致。
        assert field_options(db, "speech_voices", _ctx(mine, parent="")) == cloned

        monkeypatch.setattr(engine_catalog, "list_engine_voices", lambda db, engine, user_id: [
            {"value": f"{engine}-1", "label": "晓晓", "resource_id": "res"},
        ])
        assert field_options(db, "speech_voices", _ctx(mine, parent="edge")) == [{"value": "edge-1", "label": "晓晓"}]


def test_接口要工作区权限_来源写错说清楚() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    ok = client.get("/api/workflows/field-options", params={"source": "speech_voices", "workspace_id": workspace, "parent": "clone"})
    assert ok.status_code == 200, ok.text
    assert ok.json() == []

    wrong = client.get("/api/workflows/field-options", params={"source": "nope", "workspace_id": workspace})
    assert wrong.status_code == 404 and "nope" in wrong.text

    stranger = client.get("/api/workflows/field-options", params={"source": "speech_voices", "workspace_id": "not-mine"})
    assert stranger.status_code in {403, 404}


def test_节点类型接口把选项来源发下去() -> None:
    client = fresh_client()
    types = {item["type"]: item for item in client.get("/api/workflows/node-types").json()}
    config = types["synthesize_speech"]["config"]
    assert config["engine"]["options_from"] == "speech_engines"
    assert config["voice"]["options_from"] == "speech_voices"
    assert config["voice"]["depends_on"] == "engine"
    assert list(config).index("voice") == list(config).index("engine") + 1
    assert "required_one_of" not in types["synthesize_speech"]


class _VoiceDB:
    """克隆那条会核对音色的工作区;单测里给一个只认得这一条音色的库。"""

    def __init__(self, workspace_id: str) -> None:
        self.workspace_id = workspace_id

    def get(self, model, key):
        return type("V", (), {"id": key, "workspace_id": self.workspace_id})()


@pytest.mark.parametrize("engine", ["", "clone"])
def test_执行体把克隆音色交给克隆那条(engine, monkeypatch) -> None:
    from app.domain.workflows.executors import subjobs

    monkeypatch.setattr(subjobs, "current_actor", lambda db: None)
    workflow = type("W", (), {"workspace_id": "w"})()
    params = subjobs._speech_params(_VoiceDB("w"), workflow, {"engine": engine, "voice": "v1"})
    assert params["voice_id"] == "v1" and "engine_voice" not in params and "workspace_id" not in params


def test_执行体不收别的工作区的克隆音色(monkeypatch) -> None:
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.executors import subjobs

    monkeypatch.setattr(subjobs, "current_actor", lambda db: None)
    workflow = type("W", (), {"workspace_id": "w"})()
    with pytest.raises(WorkflowDomainError, match="配音库里没有这个音色"):
        subjobs._speech_params(_VoiceDB("别人的"), workflow, {"voice": "v1"})


class Test清单从哪来都由声明说了算:
    """此前这些清单是前端按**节点类型**写死的一串 if:插件的包和工具、发布账号、可调用工作流、
    对话连接与模型各一条。而插件节点是运行时才有的类型 —— 前端那张表永远覆盖不到它。

    现在都是 `options_from` 的一个来源,前端不认识任何具体节点。
    """

    def test_声明都指向真实存在的来源(self) -> None:
        from app.domain.plugins.nodes import node_meta
        from app.domain.workflows import NODE_TYPES
        from app.domain.workflows.field_options import SOURCES

        declared = {
            f"{name}.{key}": meta["options_from"]
            for name, spec in NODE_TYPES.items()
            for key, meta in (spec.get("config") or {}).items()
            if isinstance(meta, dict) and meta.get("options_from")
        }
        #: 插件节点的声明是运行时生成的,一起查。
        plugin = node_meta({"instance_id": "i", "instance_name": "n", "package_id": "p", "name": "t", "input_schema": {}})
        declared.update({
            f"plugin.{key}": meta["options_from"]
            for key, meta in plugin["config"].items()
            if isinstance(meta, dict) and meta.get("options_from")
        })
        assert {"llm.profile_id", "llm.model", "publish.account_id", "call_workflow.workflow_id",
                "plugin_tool.plugin_id", "plugin_tool.tool_name", "plugin.instance_id"} <= set(declared)
        missing = {field: source for field, source in declared.items() if source not in SOURCES}
        assert not missing, f"这些字段声明的选项来源不存在:{missing}"

    def test_可调用工作流把自己排掉(self) -> None:
        client = fresh_client()
        workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        graph = {"nodes": [{"id": "start", "type": "start", "config": {"params": {}}}], "edges": []}
        mine = client.post("/api/workflows", json={"workspace_id": workspace, "name": "我自己", "graph": graph}).json()["id"]
        other = client.post("/api/workflows", json={"workspace_id": workspace, "name": "别的", "graph": graph}).json()["id"]
        with SessionLocal() as db:
            from app.domain.workflows.field_options import field_options

            options = field_options(db, "callable_workflows", _ctx(workspace))
            assert {one["value"] for one in options} == {mine, other}
            mine_excluded = field_options(db, "callable_workflows", OptionContext(
                workspace_id=workspace, user_id=None, parent="", locale="zh", workflow_id=mine,
            ))
        assert [one["value"] for one in mine_excluded] == [other], "自调一定成环,不该摆在清单里"

    def test_发布账号只列这个工作区的(self) -> None:
        from app.db.models import PublishAccount
        from app.domain.workflows.field_options import field_options

        client = fresh_client()
        mine = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        other = client.post("/api/workspaces", json={"name": "别人的"}).json()["id"]
        with SessionLocal() as db:
            from app.db.models import User

            me = db.query(User).filter(User.username == "tester").one().id
            db.add_all([
                PublishAccount(workspace_id=mine, platform="douyin", name="我的号", owner_user_id=me),
                PublishAccount(workspace_id=other, platform="douyin", name="别人的号", owner_user_id=me),
            ])
            db.commit()
            ctx = OptionContext(workspace_id=mine, user_id=me, parent="", locale="zh")
            assert [one["label"] for one in field_options(db, "publish_accounts", ctx)] == ["我的号"]
            # 说不出是谁在挑 —— 一个都不给(和用的那一刻同一个判据,见 sharing.usable_filter)。
            assert field_options(db, "publish_accounts", _ctx(mine)) == []

    def test_插件节点的连接按它自己的包过滤(self, monkeypatch) -> None:
        """插件节点的包名在**节点类型**里(`plugin.<包>.<工具>`),不是某个字段的值 ——
        所以它走 node_type 这条上下文,而不是 parent。"""
        from app.domain.plugins import tools as plugin_tools
        from app.domain.workflows.field_options import field_options

        monkeypatch.setattr(plugin_tools, "exposed", lambda db, user_id: [
            {"instance_id": "i-a", "instance_name": "B站", "package_id": "pkg.a", "name": "fetch"},
            {"instance_id": "i-b", "instance_name": "抖音", "package_id": "pkg.b", "name": "fetch"},
        ])
        context = OptionContext(workspace_id="w", user_id=None, parent="", locale="zh", node_type="plugin.pkg.a.fetch")
        assert [one["label"] for one in field_options(None, "plugin_instances", context)] == ["B站"]
        #: 通用的 plugin_tool 节点按它选中的那个包过滤(那是字段的值,走 parent)。
        by_field = OptionContext(workspace_id="w", user_id=None, parent="pkg.b", locale="zh")
        assert [one["label"] for one in field_options(None, "plugin_instances", by_field)] == ["抖音"]


def test_对话模型只列这条连接上会对话的_而且得是我的连接() -> None:
    """LLM / 翻译节点的「模型」下拉。

    此前列的是这条连接下**所有**启用的模型:同一个端点上的生图、生视频模型一起出现,选中
    之后发出去的是一次对话请求,供应商回一句看不懂的 400。而且不核对连接归谁 —— 拿别人的
    连接 id 当 parent 就能看到他那条连接上配了哪些模型。
    """
    from app.db.models import User
    from app.domain import provider_models
    from app.domain.workflows.field_options import field_options
    from tests.util import add_provider, second_client

    fresh_client()
    second_client("other")
    with SessionLocal() as db:
        me = db.query(User).filter(User.username == "tester").one().id
        mine = add_provider(db, name="我的", vendor="openai-compatible", base_url="https://api.test",
                            api_key="sk", model="chat-m", capability_ids=["chat"])
        provider_models.upsert(db, mine, "image-m", capability_ids=["image"])
        theirs = add_provider(db, name="他的", vendor="openai-compatible", base_url="https://api.test",
                              api_key="sk", model="their-m", capability_ids=["chat"], owner_username="other")
        db.commit()

        def options(parent: str) -> set[str]:
            ctx = OptionContext(workspace_id="w", user_id=me, parent=parent, locale="zh")
            return {one["value"] for one in field_options(db, "chat_models", ctx)}

        assert options(mine.id) == {"chat-m"}
        assert options(theirs.id) == set()


def test_对话连接的订阅计划按自己那把钥匙判断() -> None:
    """oauth 连接的「可用」读的是当前用户自己那把凭据,不是档案行 —— 档案行上根本没有
    oauth_linked(那是 API schema 按用户算出来的展示字段),领域层直接读它曾让整个
    字段选项接口 500(AttributeError)。"""
    from app.db.models import ProviderCredential, ProviderProfile, User
    from app.domain.workflows.field_options import field_options

    fresh_client()
    with SessionLocal() as db:
        user_id = db.query(User).filter(User.username == "tester").one().id
        linked = ProviderProfile(owner_user_id=user_id, vendor="openai", name="订阅已登录", auth_type="oauth", enabled=True)
        unlinked = ProviderProfile(owner_user_id=user_id, vendor="openai", name="订阅未登录", auth_type="oauth", enabled=True)
        keyed = ProviderProfile(owner_user_id=user_id, vendor="openai-compatible", name="自填 Key", base_url="http://127.0.0.1:9", enabled=True)
        keyless = ProviderProfile(owner_user_id=user_id, vendor="openai-compatible", name="没填地址", enabled=True)
        db.add_all([linked, unlinked, keyed, keyless])
        db.flush()
        db.add(ProviderCredential(profile_id=linked.id, owner_user_id=user_id, oauth_credential={"access_token": "x"}))
        db.commit()

        options = field_options(db, "chat_connections", OptionContext(workspace_id="w", user_id=user_id, parent="", locale="zh"))

        assert {one["value"] for one in options} == {linked.id, keyed.id}


class Test指向工作区里某样东西的字段:
    """场景、镜头、项目、时间线、轨道此前都是文本框(「有些应该是下拉选择而非输入吧」)。
    清单只列**这个工作区**的;依赖另一个字段的(镜头跟场景、轨道跟时间线)按 parent 列,
    parent 说不出是哪一个(没挑、是一段 `{{…}}` 引用、在别的工作区)时是空清单。
    """

    @staticmethod
    def _two_workspaces() -> tuple[str, str]:
        from tests.util import second_client

        mine = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
        other = second_client("other").post("/api/workspaces", json={"name": "别人的"}).json()["id"]
        return mine, other

    def test_场景和它的镜头(self) -> None:
        from app.db.models import Scene3D
        from app.domain.workflows.field_options import field_options

        mine, other = self._two_workspaces()
        with SessionLocal() as db:
            shots = [
                {"id": "shot-1", "name": "开场", "camera_id": "camera-1"},
                {"id": "shot-2", "name": "近景", "camera_id": "camera-1"},
                {"id": "shot-3", "name": "近景", "camera_id": "camera-1"},
            ]
            scene = Scene3D(workspace_id=mine, name="客厅", content={"shots": shots})
            foreign = Scene3D(workspace_id=other, name="别人的场景", content={"shots": shots[:1]})
            db.add_all([scene, foreign])
            db.commit()

            assert field_options(db, "scenes", _ctx(mine)) == [{"value": scene.id, "label": "客厅"}]
            #: 按场景里的顺序,显示镜头名;重名的带上 id,下拉里才分得开。
            assert field_options(db, "scene_shots", _ctx(mine, parent=scene.id)) == [
                {"value": "shot-1", "label": "开场"},
                {"value": "shot-2", "label": "近景 · shot-2"},
                {"value": "shot-3", "label": "近景 · shot-3"},
            ]
            for parent in ("", "{{搭建白模.scene_id}}", foreign.id):
                assert field_options(db, "scene_shots", _ctx(mine, parent=parent)) == [], parent

    def test_项目_时间线_轨道(self) -> None:
        from app.db.models import Project
        from app.domain.sequences.creation import create_sequence_scaffold
        from app.domain.workflows.field_options import field_options

        mine, other = self._two_workspaces()
        with SessionLocal() as db:
            project = Project(workspace_id=mine, name="新品发布")
            foreign = Project(workspace_id=other, name="别人的项目")
            db.add_all([project, foreign])
            db.flush()
            scaffold = create_sequence_scaffold(db, project, name="主时间线", width=1920, height=1080, fps=30)
            create_sequence_scaffold(db, foreign, name="主时间线", width=1920, height=1080, fps=30)
            db.commit()
            sequence_id = scaffold.sequence.id

            assert field_options(db, "projects", _ctx(mine)) == [{"value": project.id, "label": "新品发布"}]
            #: 每个项目的时间线默认同名 —— 带上项目名才分得出是谁的。
            assert field_options(db, "sequences", _ctx(mine)) == [{"value": sequence_id, "label": "新品发布 / 主时间线"}]
            assert field_options(db, "sequence_tracks", _ctx(mine, parent=sequence_id)) == [
                {"value": scaffold.video_track.id, "label": "V1 · 视频"},
                {"value": scaffold.audio_track.id, "label": "A1 · 音频"},
            ]
            assert field_options(db, "sequence_tracks", _ctx(other, parent=sequence_id)) == []
            assert field_options(db, "sequence_tracks", _ctx(mine, parent="{{新建时间线.sequence_id}}")) == []

    def test_节点声明把来源和依赖发下去(self) -> None:
        client = fresh_client()
        types = {item["type"]: item for item in client.get("/api/workflows/node-types").json()}
        render = types["scene_render"]["config"]
        assert render["scene_id"]["options_from"] == "scenes" and render["scene_id"]["data_type"] == "scene"
        assert render["shot_id"]["options_from"] == "scene_shots" and render["shot_id"]["depends_on"] == "scene_id"
        assert render["shot_id"]["sole_option_default"] is True and not render["shot_id"].get("required")
        assert render["project_id"]["options_from"] == "projects"
        append = types["timeline_append"]["config"]
        assert append["sequence_id"]["options_from"] == "sequences"
        assert (append["track_id"]["options_from"], append["track_id"]["depends_on"]) == ("sequence_tracks", "sequence_id")
        plugin = types["plugin_tool"]["config"]["instance_id"]
        assert (plugin["options_from"], plugin["depends_on"]) == ("plugin_instances", "plugin_id")


def test_同名的几项带上一截_id_所有来源一处做() -> None:
    """几个场景都叫「未命名场景」时,下拉里是几行一模一样的字,高亮和选中都会认错。"""
    from app.domain.workflows.field_options import distinct_labels

    long_a, long_b = "a" * 28 + "3f9a", "b" * 28 + "77c1"
    out = distinct_labels([
        {"value": long_a, "label": "未命名场景"},
        {"value": long_b, "label": "未命名场景"},
        {"value": "c" * 32, "label": "客厅"},
        {"value": "shot-2", "label": "近景"},
        {"value": "shot-3", "label": "近景"},
    ])
    assert [one["label"] for one in out] == ["未命名场景 · #3f9a", "未命名场景 · #77c1", "客厅", "近景 · shot-2", "近景 · shot-3"]
    assert len({one["label"] for one in out}) == len(out)
