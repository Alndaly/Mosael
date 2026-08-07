"""连接归建它的那个人,不是这台部署的公共财产。

**这是「钥匙归人」那把尺子没量到底的最后一段。** 当时把密钥搬去了 ProviderCredential,连接
(ProviderProfile)留在部署级,理由是"怎么连到这家供应商是部署的配置"。那个理由在单人机器上
成立,在多租户产品里不成立 —— 而这个应用是后者。

代价是新账号一进设置页就看到八条别人建的连接,每条底下一行红字「未配置你的密钥」:看得见、
用不了、也建不了自己的(建连接要部署管理员)。它同时是那次端点泄露的根 —— 我上次遮住了地址,
那是打补丁;真正的问题是**它本来就不该出现在别人的列表里**。

现在:谁建的归谁,列表只给自己的,谁都能建自己的。部署管理员也不例外 —— 他的连接是他的,
不是所有人的。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import ProviderProfile
from tests.util import fresh_client, second_client


def _create(client, name: str) -> str:
    created = client.post(
        "/api/settings/providers",
        json={
            "name": name,
            "vendor": "openai-compatible",
            "config": {"base_url": "https://x.example/v1", "default_model": "m", "api_key": "k"},
        },
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def test_a_new_account_sees_nothing() -> None:
    """一进来是空的 —— 那正是"你还没配过任何东西"的诚实样子。"""
    admin = fresh_client()
    _create(admin, "管理员的")

    mate = second_client("mate")

    assert mate.get("/api/settings/providers").json() == []


def test_anyone_can_add_their_own() -> None:
    """建连接不再要部署管理员:那是他自己的连接、他自己的钥匙、他自己的账单。"""
    fresh_client()
    mate = second_client("mate")

    mine = _create(mate, "我的")

    assert [row["id"] for row in mate.get("/api/settings/providers").json()] == [mine]


def test_i_cannot_touch_someone_elses() -> None:
    admin = fresh_client()
    theirs = _create(admin, "管理员的")
    mate = second_client("mate")

    assert mate.patch(f"/api/settings/providers/{theirs}", json={"name": "改个名"}).status_code == 404
    assert mate.delete(f"/api/settings/providers/{theirs}").status_code == 404
    with SessionLocal() as db:
        assert db.get(ProviderProfile, theirs) is not None, "被别人删掉了"


def test_a_deployment_admin_is_not_special_here() -> None:
    """管理员管的是这台部署,不是别人的账号 —— 他也看不到别人的连接。"""
    admin = fresh_client()
    mate = second_client("mate")
    _create(mate, "他的")

    assert admin.get("/api/settings/providers").json() == []


def test_models_follow_the_connection() -> None:
    """模型行挂在连接上,别人既看不到也加不了。"""
    admin = fresh_client()
    theirs = _create(admin, "管理员的")
    admin.post(f"/api/settings/providers/{theirs}/models", json={"model_id": "m"})
    mate = second_client("mate")

    assert mate.post(f"/api/settings/providers/{theirs}/models", json={"model_id": "偷偷加"}).status_code == 404
    assert mate.get("/api/settings/capability-models/chat").json() == []


def test_my_key_and_my_connection_are_the_same_thing_now() -> None:
    """连接归了人之后,「未配置你的密钥」这行红字不该再出现在别人的连接上 —— 因为看不到别人的。"""
    admin = fresh_client()
    _create(admin, "管理员的")
    mate = second_client("mate")

    assert "未配置" not in mate.get("/api/settings/providers").text


def test_i_can_see_my_own_endpoint() -> None:
    """自己那条连接的地址当然看得见 —— 上一轮为了挡住"别人的地址印在他列表里"加过一层按角色
    遮蔽,那是打补丁:它同时让普通成员看不到自己填的端点。归属修好之后那层就该撤掉。
    """
    fresh_client()
    mate = second_client("mate")
    _create(mate, "我的")

    assert "https://x.example/v1" in mate.get("/api/settings/providers").text
