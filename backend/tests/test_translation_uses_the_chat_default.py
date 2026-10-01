"""翻译(和其它没点名连接的对话调用)用的是**这个人的对话模型**,不是「最早建的那条连接」。

此前两条译配模板的翻译节点只写了 `engine: builtin:chat`,没写连接和模型;运行时回退到按创建时间最早的那条启用连接
—— 不管它会不会对话。先接了一条生图连接的人,译配一跑到翻译就把对话请求发给了生图端点。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import User, Workspace
from app.domain.providers.chat_connection import require_connection
from app.domain.translate import resolve_ai_chat_target
from app.domain.workflows.templates import built_in_template_graph
from tests.util import add_provider, fresh_client


def _deployment(*, chat_default: bool) -> tuple[str, str, str]:
    """先接一条只会出图的连接,再接一条会对话的。返回 (人, 出图连接, 对话连接)。"""
    fresh_client().post("/api/workspaces", json={"name": "W"})
    with SessionLocal() as db:
        image = add_provider(db, name="先接的出图", vendor="openai-compatible", base_url="http://img/v1", api_key="k1",
                             model="painter", capability_ids=["image"])
        chat = add_provider(db, name="后接的对话", vendor="deepseek", base_url="http://chat/v1", api_key="k2",
                            model="deepseek-chat", capability_ids=["chat"], make_default=chat_default)
        db.commit()
        me = db.query(User).order_by(User.created_at).first().id
        return me, image.id, chat.id


def test_没点名连接_翻译用他的默认对话模型_不是最早那条连接() -> None:
    me, _image, chat = _deployment(chat_default=True)
    with SessionLocal() as db:
        target = resolve_ai_chat_target(db, None, me)
        assert (target.profile_id, target.model) == (chat, "deepseek-chat")
        assert require_connection(db, None, user_id=me, surface="direct").id == chat, "LLM 节点等没点名连接的对话调用同一个挑法"


def test_没设默认对话模型_也挑一条会对话的_不挑出图那条() -> None:
    me, _image, chat = _deployment(chat_default=False)
    with SessionLocal() as db:
        assert resolve_ai_chat_target(db, None, me).profile_id == chat
        assert require_connection(db, None, user_id=me, surface="direct").id == chat


def test_两条译配模板把对话连接和模型写在翻译节点上() -> None:
    me, _image, chat = _deployment(chat_default=True)
    with SessionLocal() as db:
        workspace = db.query(Workspace).first().id
        for template_id in ("translated_dub", "translated_dub_lipsync"):
            graph = built_in_template_graph(db, template_id, user_id=me, workspace_id=workspace, locale="zh")
            node = next(one for one in graph["nodes"] if one["id"] == "translate_lines")
            assert (node["config"]["profile_id"], node["config"]["model"]) == (chat, "deepseek-chat"), template_id


def test_没设默认对话模型时_建图和前置检查说的是同一个() -> None:
    """此前建图用「默认模型」(没设就空着),检查用「没默认也挑一个配好的」:检查说齐了,节点上却是空的。"""
    from app.domain.workflows.templates import requirement_statuses

    me, _image, chat = _deployment(chat_default=False)
    with SessionLocal() as db:
        workspace = db.query(Workspace).first().id
        assert requirement_statuses(db, user_id=me, workspace_id=workspace)["chat_model"] == "met"
        graph = built_in_template_graph(db, "transcript_video_cleanup", user_id=me, workspace_id=workspace, locale="zh")
        plan = next(one for one in graph["nodes"] if one["id"] == "cleanup_plan")
        assert (plan["config"]["profile_id"], plan["config"]["model"]) == (chat, "deepseek-chat")


def test_默认对话连接是订阅授权的_直连的调用方挑下一条调得通的() -> None:
    """订阅授权(OAuth)的连接没有服务地址,只有经网关(工作流、画板)调得通。此前没点名连接时不看调用通道:最早的
    (或设成默认的)是订阅授权时,界面上的翻译、发布文案这些直连调用方当场报「只能给智能体用」。"""
    fresh_client().post("/api/workspaces", json={"name": "W"})
    with SessionLocal() as db:
        oauth = add_provider(db, name="Kimi Code", vendor="kimi-coding", base_url="", auth_type="oauth",
                             oauth_credential={"access_token": "x"}, model="k3", capability_ids=["chat"])
        keyed = add_provider(db, name="后接的对话", vendor="deepseek", base_url="http://chat/v1", api_key="k2",
                             model="deepseek-chat", capability_ids=["chat"], make_default=False)
        db.commit()
        me = db.query(User).order_by(User.created_at).first().id
        assert resolve_ai_chat_target(db, None, me, surface="direct").profile_id == keyed.id
        assert require_connection(db, None, user_id=me, surface="direct").id == keyed.id
        assert require_connection(db, None, user_id=me, surface="automation").id == oauth.id, "经网关调的照旧用他的默认"
