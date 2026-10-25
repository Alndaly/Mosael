"""`GET /api/workflows/field-options` 的**响应形状**:领域层多带的几格必须真的穿过 HTTP 那一层。

这个接口的 `response_model` 是 `list[WorkflowFieldOptionOut]`,`ApiModel` 是 pydantic 默认的
`extra="ignore"` —— 于是"领域层给了、响应模型没声明"的键在**序列化那一刻被静默丢掉**,而路由的
返回类型注解是 `list[dict]`、领域层的 `Option` 是 `dict[str, Any]`:两边都不认识这几格,没有任何
东西会喊停。

这里钉住的正是那一层(不是领域层算得对不对):

1. 飞书「收件人」那一格:open_id / chat_id 按飞书应用隔离,所以清单里每一项**必须**说得出它属于
   哪台机器人(`bot_id`)—— 前端选中时据此把「机器人」那一格一并写上,它拿不到
   "选项属于谁"这件事,不许从标签里的机器人名反推;
2. ADR 0045 的两层名字(`model` / `profile_name` / `entry_group`):生成类下拉一直带着它们,
   而 `entryNames.entryNamedOptions` 一直在读它们 —— 从没到过 Web 的话,第二行永远是空的。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from tests.util import fresh_client


def test_收件人选项带着是哪台机器人的openid() -> None:
    """两台机器人、各绑一个人:每一项各自等于**它那一台**,不是"有值就行"。

    两台才会暴露"按 label 里的机器人名反推"那种猜法 —— 并且选项清单是按机器人分组列的
    (见 `field_options._feishu_bound_users`),顺序由库里的 created_at 决定,所以断言按 value 索引。
    """
    from app.db.models import FeishuBinding, FeishuBot, User, WorkspaceMember
    from tests.util import second_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    second_client("other")

    with SessionLocal() as db:
        tester = db.query(User).filter(User.username == "tester").one()
        mate = db.query(User).filter(User.username == "other").one()
        bots = [
            FeishuBot(workspace_id=workspace, name="一号", app_id="cli_one", app_secret="s1"),
            FeishuBot(workspace_id=workspace, name="二号", app_id="cli_two", app_secret="s2"),
        ]
        db.add_all(bots)
        db.flush()
        db.add_all([
            FeishuBinding(workspace_id=workspace, bot_id=bots[0].id, open_id="ou_in_one", user_id=tester.id),
            FeishuBinding(workspace_id=workspace, bot_id=bots[1].id, open_id="ou_in_two", user_id=mate.id),
            WorkspaceMember(workspace_id=workspace, user_id=mate.id, role="editor"),
        ])
        db.commit()
        expected = {"ou_in_one": (bots[0].id, "一号"), "ou_in_two": (bots[1].id, "二号")}

    got = client.get("/api/workflows/field-options",
                     params={"source": "feishu_targets", "workspace_id": workspace, "parent": "user"})
    assert got.status_code == 200, got.text
    options = {one["value"]: one for one in got.json()}
    assert set(options) == set(expected), got.text
    for value, (bot_id, bot_name) in expected.items():
        assert options[value]["bot_id"] == bot_id, got.text
        #: 工作区里不止一台时,标签里本来就有机器人名 —— 那是给人看的字,不是给程序反推的依据。
        assert options[value]["label"].endswith(bot_name), got.text


def test_入口的两层名字穿过接口那一层(monkeypatch) -> None:
    """ADR 0045 的 `model` / `profile_name` / `entry_group`:**既存** bug。

    `generation_option_names` 三个键一直都在给(见 `field_options.generation_option_names`),
    前端 `lib/entryNames.ts` 的 `entryNamedOptions` 也一直在读(它读不到就整段跳过 —— 静默无效),
    丢的就是响应模型这一层。

    这里只把**数据的来源**换成一份假的生成选项(和 tests/test_talking.py 同一手法):路由、权限、
    `generation_option_names` 的整理、以及 pydantic 的响应序列化全是真的。假的这一份按
    `generation_options` 的真实形状给(`id` / `model_label` / `model` / `profile_name` / `group`)。
    """
    from app.domain.generation import resolution

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    group = {"id": "krea2-text-2-image.json", "label": "krea2-text-2-image", "entry": "form", "order": 1}
    monkeypatch.setattr(resolution, "generation_options", lambda db, kind, user_id=None: [{
        "id": "p:video:krea2-text-2-image.json",
        "provider": "comfyui",
        "provider_profile_id": "p",
        "model": "krea2-text-2-image.json",
        "model_label": "krea2-text-2-image",
        "profile_name": "ComfyUI 本机",
        "group": group,
        "adapter_available": True,
        "capabilities": {"modes": ["speech-to-video"]},
    }])

    got = client.get("/api/workflows/field-options",
                     params={"source": "speech_video_models", "workspace_id": workspace})
    assert got.status_code == 200, got.text
    options = got.json()
    assert len(options) == 1, got.text
    assert options[0]["value"] == "p:video:krea2-text-2-image.json"
    assert options[0]["model"] == "krea2-text-2-image.json", got.text
    assert options[0]["profile_name"] == "ComfyUI 本机", got.text
    assert options[0]["entry_group"] == group, got.text


def test_别的来源不填的那几格是空的而不是缺的() -> None:
    """**别的来源不填 `bot_id` / `model` / `profile_name` / `entry_group`。**

    这是"加默认值、别 required"的判据:不能因为一个来源不带这几格,就让整个接口 500,或者让
    `entry_group` 变成一个必须给出、给出还得像样的东西。形状固定(键都在),值是该来源如实不填。
    """
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    got = client.get("/api/workflows/field-options",
                     params={"source": "speech_engines", "workspace_id": workspace})
    assert got.status_code == 200, got.text
    engines = got.json()
    assert engines, got.text
    for one in engines:
        assert one["bot_id"] == ""
        assert one["model"] == "" and one["profile_name"] == ""
        assert one["entry_group"] is None
