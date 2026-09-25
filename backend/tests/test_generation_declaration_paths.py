"""生成能力声明的全链路契约:设置页写下一份声明,每一次提交都被**同一份**规则拦下。

`test_generation_custom_profiles.py` 钉的是保存时的形状校验与连接级归属;这里钉的是声明
**生效**的那一圈:创建 → 绑上模型 → 选项列表 → 画板/智能体提交 —— 每个入口看到的必须是
同一份描述符,否则就是"界面上让我选,提交时按另一套拦"那种分裂。

画板走 HTTP 全程;智能体、工作流、定时任务三条路在 confirmations.py / subjobs.py /
scheduler.py 里都只是把载荷原样喂给 `create_generation_job` —— 收口在那一个函数
(见 validate_against_capabilities 的说明),所以对那条缝直接断言,四条路同时被钉住。
"""

from __future__ import annotations

import pytest

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import ProviderProfile, User
from app.domain import provider_models
from app.domain.generation.operations import GenerationDomainError, create_generation_job
from tests.util import fresh_client, run_on_board, second_client


@pytest.fixture(autouse=True)
def _generation_jobs_不外发(monkeypatch: pytest.MonkeyPatch):
    """本文件只关心「建没建、拦没拦」,不关心真跑。真跑会让适配器对着假端点重试几分钟,
    而它的尾巴(失败记账落库)会撞进后面用例重建的库,炸在无辜的测试头上 —— conftest 那条
    autouse fixture 的注释说的就是这种事故。标成 external:job 照常建好、留在队列,线程不起。"""
    from app.domain import jobs as jobs_bus

    monkeypatch.setattr(
        jobs_bus, "_EXECUTION_MODES", {**jobs_bus._EXECUTION_MODES, "ai_generation": "external"}
    )

#: 中转端点上那种"目录装不下"的组合:目录不知道 `gpt-image-2-client`,用户知道它收什么。
IMAGE_CAPS = {
    "parameter_keys": ["size", "num_images", "quality", "reference_image"],
    "sizes": ["1024x1024", "1024x1536"],
    "default_size": "1024x1024",
    "max_num_images": 4,
    "parameter_choices": {"quality": ["low", "high"]},
    "source_limits": {"reference_image": 2},
}

VIDEO_CAPS = {
    "parameter_keys": ["duration_seconds", "resolution", "first_frame", "reference_video"],
    "duration_seconds": [4, 8, 12],
    "default_duration_seconds": 4,
    "resolutions": ["720p", "1080p"],
    "default_resolution": "720p",
    "max_duration_seconds": 12,
    "conditional_max_duration_seconds": {"reference_video": 8},
    "exclusive_source_groups": [["first_frame"], ["reference_video"]],
    "source_limits": {"reference_video": 1},
}


def _connection(client, vendor: str, name: str = "演示") -> str:
    profile_id = client.post(
        "/api/settings/providers",
        json={"vendor": vendor, "name": name, "api_key": "sk-test", "base_url": "http://127.0.0.1:1"},
    ).json()["id"]
    #: 密钥按人另存 —— 建连接那个请求不落钥匙(见 provider_credentials)。
    client.put(f"/api/settings/providers/{profile_id}/credential", json={"api_key": "sk-test"})
    return profile_id


def _add_model(profile_id: str, model_id: str, capability_ids: list[str]) -> None:
    with SessionLocal() as db:
        provider_models.upsert(
            db, db.get(ProviderProfile, profile_id), model_id,
            source="manual", capability_ids=capability_ids,
        )
        db.commit()


def _user_id(username: str = "tester") -> str:
    with SessionLocal() as db:
        user = db.scalars(select(User).where(User.username == username)).first()
        assert user is not None
        return user.id


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _create_profile(client, profile_id: str, name: str, kind: str, capabilities: dict) -> str:
    created = client.post(
        f"/api/settings/providers/{profile_id}/generation-profiles",
        json={"name": name, "kind": kind, "capabilities": capabilities},
    )
    assert created.status_code == 200, created.text
    return created.json()["ref"]


def _bind(client, profile_id: str, model_id: str, refs: dict):
    return client.patch(
        f"/api/settings/providers/{profile_id}/models/{model_id}",
        json={"generation_capability_refs": refs},
    )


class Test跨用户的那堵墙:
    def test_选项列表不给别人看(self) -> None:
        admin = fresh_client()
        pid = _connection(admin, "openai")
        _add_model(pid, "gpt-image-2-client", ["image"])

        mate = second_client("mate")

        assert mate.get("/api/generation/options?kind=image").json() == []

    def test_别人连接下的参数组看不了也建不了(self) -> None:
        admin = fresh_client()
        pid = _connection(admin, "openai")
        _create_profile(admin, pid, "甲的组", "image", IMAGE_CAPS)
        mate = second_client("mate")

        assert mate.get(f"/api/settings/providers/{pid}/generation-profiles?kind=image").status_code == 404
        created = mate.post(
            f"/api/settings/providers/{pid}/generation-profiles",
            json={"name": "伸手", "kind": "image", "capabilities": IMAGE_CAPS},
        )
        assert created.status_code == 404
        #: 选择器那条路同理 —— 拿别人的连接 id 来列候选,和列别人的连接是同一回事。
        assert mate.get(f"/api/generation/capability-refs?kind=image&profile_id={pid}").status_code == 404

    def test_别人连接下的参数组绑不到我的模型上(self) -> None:
        """ref 是个字符串,所以这道墙必须在绑定这一刻砌 —— 存进去再发现就晚了。"""
        admin = fresh_client()
        theirs = _connection(admin, "openai")
        foreign_ref = _create_profile(admin, theirs, "甲的组", "image", IMAGE_CAPS)

        mate = second_client("mate")
        mine = _connection(mate, "openai", "我的")
        _add_model(mine, "gpt-image-2-client", ["image"])

        rejected = _bind(mate, mine, "gpt-image-2-client", {"image": foreign_ref})
        assert rejected.status_code == 422, rejected.text


class Test从声明到提交只有一份规则:
    def test_创建_绑定_选项_画板提交_是同一份(self) -> None:
        client = fresh_client()
        pid = _connection(client, "openai")
        _add_model(pid, "gpt-image-2-client", ["image"])
        ref = _create_profile(client, pid, "中转那份", "image", IMAGE_CAPS)

        bound = _bind(client, pid, "gpt-image-2-client", {"image": ref})
        assert bound.status_code == 200, bound.text
        body = bound.json()
        assert body["generation_capability_refs"]["image"] == ref
        assert body["generation_capabilities_known_by_kind"]["image"] is True

        #: 选项列表那张嘴和设置页说的是同一份 —— 它此前是自己拼的第三份数据。
        options = client.get("/api/generation/options?kind=image").json()
        option = next(one for one in options if one["model"] == "gpt-image-2-client")
        assert option["capabilities"]["sizes"] == IMAGE_CAPS["sizes"]
        assert option["capabilities_known"] is True

        #: 画板提交:枚举外的值当场 400,报错点名是哪个参数 —— 而不是供应商那边一句英文。
        ws = _workspace(client)
        board_id = client.post(
            "/api/boards", json={"workspace_id": ws, "name": "B"}
        ).json()["id"]
        rejected = run_on_board(
            client, board_id, ws, producer="generate", item_id="n1", kind="image",
            form={
                "prompt": "一只猫",
                "provider": "openai", "provider_profile_id": pid, "model": "gpt-image-2-client",
                "parameters": {"quality": "ultra"},
            },
        )
        assert rejected.status_code == 400, rejected.text
        assert "quality" in rejected.json()["detail"]

        #: 声明内的值放行 —— 拦错了方向同样是这条链坏掉的样子。
        accepted = run_on_board(
            client, board_id, ws, producer="generate", item_id="n1", kind="image",
            form={
                "prompt": "一只猫",
                "provider": "openai", "provider_profile_id": pid, "model": "gpt-image-2-client",
                "parameters": {"quality": "high", "size": "1024x1536"},
            },
        )
        assert accepted.status_code == 200, accepted.text

    def test_提交校验那条缝认自定义声明(self) -> None:
        """智能体/工作流/定时任务都汇到 create_generation_job —— 直接对缝断言。

        模型在目录里查不到(…-client 是中转别名),没绑声明时校验放行(不猜);绑了之后
        同一份声明必须在提交这一刻生效 —— 否则"设置页说认出来了,提交按另一套拦"。
        """
        client = fresh_client()
        pid = _connection(client, "openai")
        _add_model(pid, "gpt-image-2-client", ["image"])
        ws = _workspace(client)
        user_id = _user_id()

        with SessionLocal() as db:
            #: 没绑声明:目录不认识它,放行(见 validate_against_capabilities 的说明)。
            create_generation_job(
                db, workspace_id=ws, session_id=None, project_id=None, created_by=user_id,
                provider="openai", provider_profile_id=pid, model="gpt-image-2-client",
                kind="image", prompt="一只猫", negative_prompt="",
                parameters={"quality": "ultra"}, source_assets=[],
            )

        ref = _create_profile(client, pid, "中转那份", "image", IMAGE_CAPS)
        assert _bind(client, pid, "gpt-image-2-client", {"image": ref}).status_code == 200

        with SessionLocal() as db:
            with pytest.raises(GenerationDomainError, match="quality"):
                create_generation_job(
                    db, workspace_id=ws, session_id=None, project_id=None, created_by=user_id,
                    provider="openai", provider_profile_id=pid, model="gpt-image-2-client",
                    kind="image", prompt="一只猫", negative_prompt="",
                    parameters={"quality": "ultra"}, source_assets=[],
                )


class Test提交前拦得住用户写下的约束:
    """用户声明的枚举、份数、互斥和条件时长,要在提交前拦 —— 供应商那句英文帮不上忙。"""

    def _video_setup(self, client):
        pid = _connection(client, "minimax")
        _add_model(pid, "MiniMax-H3-client", ["video"])
        ref = _create_profile(client, pid, "中转视频那份", "video", VIDEO_CAPS)
        assert _bind(client, pid, "MiniMax-H3-client", {"video": ref}).status_code == 200
        return pid

    def _submit_video(self, user_id: str, ws: str, pid: str, parameters: dict, sources: list[dict]):
        with SessionLocal() as db:
            return create_generation_job(
                db, workspace_id=ws, session_id=None, project_id=None, created_by=user_id,
                provider="minimax", provider_profile_id=pid, model="MiniMax-H3-client",
                kind="video", prompt="一只猫在窗台", negative_prompt="",
                parameters=parameters, source_assets=sources,
            )

    def test_素材份数超上限(self) -> None:
        client = fresh_client()
        pid = _connection(client, "openai")
        _add_model(pid, "gpt-image-2-client", ["image"])
        ref = _create_profile(client, pid, "中转那份", "image", IMAGE_CAPS)
        assert _bind(client, pid, "gpt-image-2-client", {"image": ref}).status_code == 200

        with SessionLocal() as db:
            with pytest.raises(GenerationDomainError, match="最多收 2 份"):
                create_generation_job(
                    db, workspace_id=_workspace(client), session_id=None, project_id=None,
                    created_by=_user_id(), provider="openai", provider_profile_id=pid,
                    model="gpt-image-2-client", kind="image", prompt="一只猫", negative_prompt="",
                    parameters={"size": "1024x1024"},
                    source_assets=[{"asset_id": f"a{i}", "role": "reference_image"} for i in range(3)],
                )

    def test_互斥的两组素材不能混挂(self) -> None:
        client = fresh_client()
        pid = self._video_setup(client)

        with pytest.raises(GenerationDomainError, match="不能一起用"):
            self._submit_video(
                _user_id(), _workspace(client), pid,
                {"duration_seconds": 4},
                [
                    {"asset_id": "a1", "role": "first_frame"},
                    {"asset_id": "a2", "role": "reference_video"},
                ],
            )

    def test_条件时长跟着素材收紧(self) -> None:
        """挂着参考视频最多 8 秒,不挂能到 12 —— 写死 8 会冤枉不挂的那条路。"""
        client = fresh_client()
        pid = self._video_setup(client)
        user_id, ws = _user_id(), _workspace(client)

        with pytest.raises(GenerationDomainError, match="最多 8 秒"):
            self._submit_video(
                user_id, ws, pid, {"duration_seconds": 12},
                [{"asset_id": "a1", "role": "reference_video"}],
            )
        #: 不挂参考视频,12 秒本来就该过得去。
        self._submit_video(user_id, ws, pid, {"duration_seconds": 12}, [])


class Test双能力模型各声明各的:
    def test_图片和视频各指各的(self) -> None:
        """一行模型可以同时会生图和生视频,两种能力的参数没有可复用的默认关系。"""
        client = fresh_client()
        pid = _connection(client, "openai")
        _add_model(pid, "gpt-dual-client", ["image", "video"])
        image_ref = _create_profile(client, pid, "图片那份", "image", IMAGE_CAPS)
        video_ref = _create_profile(client, pid, "视频那份", "video", VIDEO_CAPS)

        bound = _bind(client, pid, "gpt-dual-client", {"image": image_ref, "video": video_ref})
        assert bound.status_code == 200, bound.text
        refs = bound.json()["generation_capability_refs"]
        assert refs == {"image": image_ref, "video": video_ref}
        assert bound.json()["generation_capabilities_known_by_kind"] == {"image": True, "video": True}

        image_options = client.get("/api/generation/options?kind=image").json()
        assert next(one for one in image_options if one["model"] == "gpt-dual-client")[
            "capabilities"
        ]["sizes"] == IMAGE_CAPS["sizes"]
        video_options = client.get("/api/generation/options?kind=video").json()
        assert next(one for one in video_options if one["model"] == "gpt-dual-client")[
            "capabilities"
        ]["duration_seconds"] == VIDEO_CAPS["duration_seconds"]


class Test同一个模型在多条连接下:
    def test_不点名连接就拒掉而不是随便挑一条(self) -> None:
        """(provider, model) 不再是身份:两家中转都代理同一个模型时,悄悄挑一条就是用错了
        别人的端点和别人的声明。点名 provider_profile_id 的那条路不受影响。"""
        client = fresh_client()
        first = _connection(client, "openai", "甲中转")
        second = _connection(client, "openai", "乙中转")
        _add_model(first, "gpt-image-2-client", ["image"])
        _add_model(second, "gpt-image-2-client", ["image"])
        ws = _workspace(client)

        with SessionLocal() as db:
            with pytest.raises(GenerationDomainError, match="明确选择连接"):
                create_generation_job(
                    db, workspace_id=ws, session_id=None, project_id=None, created_by=_user_id(),
                    provider="openai", model="gpt-image-2-client", kind="image",
                    prompt="一只猫", negative_prompt="", parameters={}, source_assets=[],
                )
            #: 点名了就分得开。
            create_generation_job(
                db, workspace_id=ws, session_id=None, project_id=None, created_by=_user_id(),
                provider="openai", provider_profile_id=first, model="gpt-image-2-client",
                kind="image", prompt="一只猫", negative_prompt="", parameters={}, source_assets=[],
            )


class Test旧列的下架节奏:
    def test_只写部分kind时旧列不动_全覆盖才下架(self) -> None:
        """legacy ref 按 kind 兜底:只绑了 image 就把旧列清掉的话,video 那半边会静默落回
        目录 —— 用户没碰过视频,视频的声明却没了。两种 kind 都写到了,旧列才安全下架。"""
        from app.db.models import ProviderModel

        client = fresh_client()
        pid = _connection(client, "openai")
        _add_model(pid, "gpt-dual-client", ["image", "video"])
        image_ref = _create_profile(client, pid, "图片那份", "image", IMAGE_CAPS)
        video_ref = _create_profile(client, pid, "视频那份", "video", VIDEO_CAPS)
        with SessionLocal() as db:
            row = db.scalars(
                select(ProviderModel).where(ProviderModel.provider_profile_id == pid)
            ).one()
            row.generation_capability_ref = "profile:openai-image"
            db.commit()

        assert _bind(client, pid, "gpt-dual-client", {"image": image_ref}).status_code == 200
        with SessionLocal() as db:
            row = db.scalars(
                select(ProviderModel).where(ProviderModel.provider_profile_id == pid)
            ).one()
            assert row.generation_capability_ref == "profile:openai-image", "video 那半边还指着它"

        assert _bind(client, pid, "gpt-dual-client", {"image": image_ref, "video": video_ref}).status_code == 200
        with SessionLocal() as db:
            row = db.scalars(
                select(ProviderModel).where(ProviderModel.provider_profile_id == pid)
            ).one()
            assert row.generation_capability_ref is None, "两种 kind 都有了声明,旧列该下架了"


class Test删除正在使用的参数组:
    def test_有人用着时不给删_解绑后才能删(self) -> None:
        """删了的话指着它的模型会静默落回兜底 —— 用户以为还在生效的配置其实没了(ADR-0013)。"""
        client = fresh_client()
        pid = _connection(client, "openai")
        _add_model(pid, "gpt-image-2-client", ["image"])
        ref = _create_profile(client, pid, "中转那份", "image", IMAGE_CAPS)
        profile_row_id = ref.removeprefix("profile:")
        assert _bind(client, pid, "gpt-image-2-client", {"image": ref}).status_code == 200

        blocked = client.delete(f"/api/settings/providers/{pid}/generation-profiles/{profile_row_id}")
        assert blocked.status_code == 409, blocked.text
        assert "1" in blocked.json()["detail"]

        #: 改回"跟随目录"(前端给该 kind 发 null)之后,才删得掉。
        assert _bind(client, pid, "gpt-image-2-client", {"image": None}).status_code == 200
        assert client.delete(
            f"/api/settings/providers/{pid}/generation-profiles/{profile_row_id}"
        ).status_code == 204


class Test兜底面走得出接口:
    """目录认不出的模型,界面靠这个面区分两种处境:「键知道了但取值没人验证过」和「真的只剩
    提示词」。合成一句会在其中一边说假话(见 ADR 0015)。

    这里带着 `profile_id` 真发一次请求 —— 这条路上的返回类型标注比实际返回窄过一次,
    FastAPI 校验响应时 500,而浏览器只看得到"Internal Server Error"。标注和返回是两份东西,
    只有真调一次才对得上。
    """

    def test_纯转发的通道给得出键(self) -> None:
        admin = fresh_client()
        pid = _connection(admin, "openai")
        body = admin.get(f"/api/generation/capability-refs?kind=image&profile_id={pid}")
        assert body.status_code == 200, body.text
        keys = body.json()["fallback_keys"]
        assert "size" in keys and "num_images" in keys
        #: 素材角色不在其中 —— 它决定这个模型做哪种任务,不是一个标量旋钮。
        assert "reference_image" not in keys

    def test_按模型分支的通道保持空(self) -> None:
        """seedance 那几个真的按模型分支(t2v 和 i2v 是两件事),这里给键就是在猜。"""
        admin = fresh_client()
        pid = _connection(admin, "bytedance")
        body = admin.get(f"/api/generation/capability-refs?kind=video&profile_id={pid}")
        assert body.status_code == 200, body.text
        assert body.json()["fallback_keys"] == []
