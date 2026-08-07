"""默认模型:**我自己设的 → 报错**。就这两档。

先后删掉了两层兜底,理由是同一条。

第一层是「该能力下第一个可用模型」。它的失败方式跑出来过:界面显示 DeepSeek,回答却是
「我是 Kimi」—— 那个"第一个"碰巧是一条 oauth 订阅连接,而订阅计划走它自己的 provider 定义
(自带身份、自带思考)。用户看不出发生了什么,只会怀疑自己。

第二层是「部署默认」,曾经被当成必要的一层:让管理员替**还没设过的人**回答这个问题,新人于是
不会一上来就撞一句报错。它温和得多,但造成的是同一种误解 —— 你没选过任何模型,回答却来自某个
你不知道的模型,花的是你的额度、用的是你的钥匙。

**任何"替他挑一个"都在没有答案时编一个,而编出来的那个看起来像答案。** 没有默认就说没有:
「请先选一个模型」是能看懂的,而且知道下一步做什么。
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


def test_my_own_default_decides_it() -> None:
    """两条连接都在,选的是我设过的那一条 —— 而不是碰巧排在前面的那一条。"""
    from app.ai.agent.host import resolve_chat_provider

    _client, _other, mine, me = _deployment_with_two_connections()
    with SessionLocal() as db:
        provider_defaults.set_default(db, "chat", provider_models.get_model(db, mine, "the-one"), owner_user_id=me)
        db.commit()
    with SessionLocal() as db:
        _dict, model, _p = resolve_chat_provider(db, None, "", user_id=me)
        assert model == "the-one"


def test_someone_elses_default_does_not_answer_for_me() -> None:
    """别人设过不等于我设过。删掉部署那一档之后,这是唯一还可能"替我回答"的东西。"""
    from app.ai.agent.host import AdapterError, resolve_chat_provider

    _client, _other, mine, me = _deployment_with_two_connections()
    with SessionLocal() as db:
        provider_defaults.set_default(db, "chat", provider_models.get_model(db, mine, "the-one"), owner_user_id=me)
        db.commit()

    mate = second_client("mate")
    with SessionLocal() as db:
        mate_id = db.query(User).filter(User.username == "mate").one().id
        with pytest.raises(AdapterError):
            resolve_chat_provider(db, None, "", user_id=mate_id)
    assert mate.get("/api/auth/me").status_code == 200
