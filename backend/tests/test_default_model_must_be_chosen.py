"""默认模型:我的 → 部署的 → **报错**,不再"随便挑一个"。

第三层曾经是「该能力下第一个可用模型」。它的失败方式跑出来过:界面显示 DeepSeek,回答却是
「我是 Kimi」—— 因为那个"第一个"碰巧是一条 oauth 订阅连接,而订阅计划走的是它自己的 provider
定义(自带身份、自带思考)。用户看不出发生了什么,只会怀疑自己。

**任何"随便挑一个"都在制造这种失败**:它在没有答案的时候编一个,而编出来的那个看起来像答案。
现在没有默认就说没有 —— 「请先选一个模型」是能看懂的,悄悄换一个不是。

部署默认因此变成必要的一层(而不是可有可无):它让管理员替**还没设过的人**回答这个问题,
于是新人不会一上来就撞一句报错。这一层现在有界面(管理员页),不再是只有 API 能置位的隐藏状态。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import User
from app.domain import provider_defaults, provider_models
from tests.util import add_provider, fresh_client, second_client


def _deployment_with_two_connections():
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    with SessionLocal() as db:
        oauth_ish = add_provider(
            db, name="别人家的订阅", vendor="openai-compatible", base_url="http://a/v1",
            api_key="k1", model="not-mine", capability_ids=["chat"], make_default=False,
        )
        mine = add_provider(
            db, name="我要的", vendor="deepseek", base_url="http://b/v1",
            api_key="k2", model="the-one", capability_ids=["chat"], make_default=False,
        )
        db.commit()
        me = db.query(User).order_by(User.created_at).first().id
        return client, oauth_ish.id, mine.id, me


def test_no_default_means_no_model_not_a_random_one() -> None:
    """一个都没设时回 None —— 而不是把"碰巧第一个"当成他的选择。"""
    _client, _other, _mine, me = _deployment_with_two_connections()
    with SessionLocal() as db:
        assert provider_models.resolve_default(db, "chat", me) is None


def test_the_agent_says_so_instead_of_picking_someone_elses_model() -> None:
    """报出来的话要能看懂,而且要指向下一步。"""
    from app.ai.agent.host import AdapterError, resolve_chat_provider

    _client, _other, _mine, me = _deployment_with_two_connections()
    with SessionLocal() as db:
        with pytest.raises(AdapterError) as caught:
            resolve_chat_provider(db, None, "", user_id=me)
        assert "模型" in str(caught.value)


def test_the_deployment_default_catches_the_newcomer() -> None:
    """管理员替还没设过的人回答 —— 新人不会一上来就撞报错。"""
    from app.ai.agent.host import resolve_chat_provider

    _client, _other, mine, me = _deployment_with_two_connections()
    with SessionLocal() as db:
        chosen = provider_models.get_model(db, mine, "the-one")
        provider_defaults.set_default(db, "chat", chosen, owner_user_id="")  # 部署默认
        db.commit()

    newcomer = second_client("newcomer")
    # 他仍然要配自己的钥匙 —— 部署默认省的是「选哪个模型」,不是「用谁的钥匙」(没有共享钥匙)。
    newcomer.put(f"/api/settings/providers/{mine}/credential", json={"api_key": "his-own"})
    with SessionLocal() as db:
        who = db.query(User).filter(User.username == "newcomer").one().id
        _dict, model, profile = resolve_chat_provider(db, None, "", user_id=who)
        assert model == "the-one" and profile is not None and profile.id == mine


def test_my_own_default_still_wins_over_the_deployments() -> None:
    from app.ai.agent.host import resolve_chat_provider

    _client, other, mine, me = _deployment_with_two_connections()
    with SessionLocal() as db:
        provider_defaults.set_default(db, "chat", provider_models.get_model(db, other, "not-mine"), owner_user_id="")
        provider_defaults.set_default(db, "chat", provider_models.get_model(db, mine, "the-one"), owner_user_id=me)
        db.commit()
    with SessionLocal() as db:
        _dict, model, _p = resolve_chat_provider(db, None, "", user_id=me)
        assert model == "the-one"


# ---------------- 部署默认不再是隐藏状态 ----------------


def test_the_deployment_default_is_readable_by_an_admin() -> None:
    """管理页要显示它 —— 一个没有界面的能力不是功能,是隐藏状态。"""
    client, _other, mine, me = _deployment_with_two_connections()
    with SessionLocal() as db:
        provider_defaults.set_default(db, "chat", provider_models.get_model(db, mine, "the-one"), owner_user_id="")
        db.commit()

    rows = {row["capability"]: row for row in client.get("/api/admin/provider-defaults").json()}
    assert rows["chat"]["model"] == "the-one"
    assert rows["chat"]["provider_profile_id"] == mine


def test_an_ordinary_member_cannot_read_or_set_it() -> None:
    client, _other, _mine, _me = _deployment_with_two_connections()
    mate = second_client("mate")
    assert mate.get("/api/admin/provider-defaults").status_code == 403
