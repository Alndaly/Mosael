"""我选的模型,就是实际跑的那个。

跑出来的现象:界面显示「DeepSeek · deepseek-v4-flash」,回答却是「我是 Kimi,由月之暗面开发」,
而且思考开关明明关着却出现了思考块。

原因不是模型在编身份 —— Kimi 那条连接是**订阅计划**(auth_type=oauth),走 pi 自己的 provider
定义:它注入自己的身份,而且是个 reasoning 模型,思考开关管不到它。所以问题是**解析真的选中了
Kimi**,而不是显示错了。

再往上一层:`resolve_default(db, capability)` 少传了 `user_id`。默认模型在第 4 步之后是**按人**存的
(自己的 → 部署的),不传人就只看部署那一行 —— 而那一行往往不存在,于是掉进最后的兜底
「该能力下第一个可用模型」,撞上谁算谁。

界面按一条链算(我的默认),后端按另一条链算(部署默认→随便第一个)。**两条链给出不同答案,
而用户只看得见其中一条。**
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import ProviderModel, User
from app.domain import provider_defaults, provider_models
from tests.util import add_provider, fresh_client


def _two_connections():
    """两条连接,各一个 chat 模型。第一条先建 —— 它就是"第一个可用"的那个兜底。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    with SessionLocal() as db:
        first = add_provider(
            db, name="别人家", vendor="openai-compatible", base_url="http://a/v1",
            api_key="k1", model="wrong-model", capability_ids=["chat"],
        )
        mine = add_provider(
            db, name="我选的", vendor="deepseek", base_url="http://b/v1",
            api_key="k2", model="right-model", capability_ids=["chat"],
        )
        db.commit()
        me = db.query(User).order_by(User.created_at).first().id
        return client, first.id, mine.id, me


def test_my_own_default_beats_the_first_available_model() -> None:
    """我设过默认,就该用我设的 —— 而不是"该能力下碰巧第一个"。"""
    _client, _first_id, mine_id, me = _two_connections()
    with SessionLocal() as db:
        chosen = provider_models.get_model(db, mine_id, "right-model")
        provider_defaults.set_default(db, "chat", chosen, owner_user_id=me)
        db.commit()

    with SessionLocal() as db:
        got = provider_models.resolve_default(db, "chat", me)
        assert got is not None and got.model_id == "right-model", "用的不是我设的默认"


def test_the_agent_uses_the_model_i_picked() -> None:
    """这条是端到端的那一句:界面显示什么,发给模型的就该是什么。"""
    from app.domain.agent.host import resolve_chat_provider

    _client, _first_id, mine_id, me = _two_connections()
    with SessionLocal() as db:
        chosen = provider_models.get_model(db, mine_id, "right-model")
        provider_defaults.set_default(db, "chat", chosen, owner_user_id=me)
        db.commit()

    with SessionLocal() as db:
        provider_dict, model, profile = resolve_chat_provider(db, None, "", user_id=me)
        assert model == "right-model", f"智能体用的是 {model},不是我设的默认"
        assert profile is not None and profile.id == mine_id


def test_a_session_that_names_its_model_always_wins() -> None:
    """会话上明确选过的,任何默认都不该盖过它。"""
    from app.domain.agent.host import resolve_chat_provider

    _client, first_id, mine_id, me = _two_connections()
    with SessionLocal() as db:
        chosen = provider_models.get_model(db, mine_id, "right-model")
        provider_defaults.set_default(db, "chat", chosen, owner_user_id=me)
        db.commit()

    with SessionLocal() as db:
        _dict, model, profile = resolve_chat_provider(db, first_id, "wrong-model", user_id=me)
        assert profile is not None and profile.id == first_id
        assert model == "wrong-model"


def test_every_default_lookup_names_the_person() -> None:
    """棘轮:`resolve_default` 不传人就只看部署默认 —— 而那一行往往不存在,于是静默兜底到别人家。

    七个调用点当初全漏了同一个参数,而漏掉不会报错、只会换一个模型回答你。
    """
    import ast
    import pathlib

    offenders: list[str] = []
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "resolve_default":
                continue
            # 位置参数 (db, capability, user_id) 或关键字 user_id=
            named = any(k.arg == "user_id" for k in node.keywords)
            if len(node.args) < 3 and not named:
                offenders.append(f"{path}:{node.lineno}")
    assert not offenders, "这些地方取默认模型时没说清「谁的默认」:\n  " + "\n  ".join(offenders)
