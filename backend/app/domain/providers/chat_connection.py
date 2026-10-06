"""没点名连接时拿哪一条去**对话**,以及「要一条能对话的连接」这件事本身。

LLM 节点、工作流 AI 改图、发布文案、画板、提示词优化、翻译都要对话;它们各自只给出「点名的连接(可以空)」和
自己要抛的错误类型。挑法只有这一份。

单独一个模块而不是住在 selection:要按对话能力挑就得读模型行(providers.models),而 models 经生成域一路
回头依赖 selection(配音引擎要查连接)—— 放在 selection 里就是一个环。
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, tr
from app.db.models import ProviderProfile
from app.domain.providers import credentials as provider_credentials
from app.domain.providers import models as provider_models
from app.domain.providers.credentials import ResolvedConnection
from app.domain.providers.presets import served_by_pi

#: 调用方在哪条通道上发对话请求(和 ai_chat.target_for 的 `surface` 同一个意思)。
ChatSurface = Literal["direct", "automation"]


def reachable_on(profile: ProviderProfile, surface: ChatSurface) -> bool:
    """这条连接在这个调用通道上调不调得通 —— 和 ai_chat.target_for 的判据是同一个。

    由 pi 承载的连接(订阅授权,Kimi Code 这类;以及 Google Gemini 这类预设点名了 pi Provider 的 API Key 连接)只能经
    网关(automation:工作流节点、画板)调;直连(direct:界面上的翻译、发布文案、提示词优化)只会说 OpenAI 兼容协议,
    发不出去,target_for 报「只能给智能体用」。
    """
    return surface == "automation" or not served_by_pi(profile.vendor)


def default_chat_connection(db: Session, *, owner_user_id: str | None, surface: ChatSurface) -> ProviderProfile | None:
    """没点名连接时拿哪一条去**对话**:他设的默认对话模型所在的那条;没设(或它已停用)就是他最早接上的、
    挂着启用对话模型的那一条 —— 和模板预填对话模型同一个先后(workflows.templates_models._pick)。

    此前是「最早建的那条启用连接」,不管它会不会对话:先接了一条生图连接的人,翻译、LLM 节点都拿它去发对话请求。
    没设默认时仍然给一条会对话的,而不是像智能体那样直接拒:建连接不会顺手设默认,这些节点一直在「没设默认也能跑」
    上被用着。

    `surface`:调用方在哪条通道上调(见 reachable_on)。他设的默认、或最早那条是订阅授权的连接,而调用方是直连时,
    挑它就是必然失败(「只能给智能体用」)—— 跳过它,挑下一条直连调得通的。
    """
    chosen = provider_models.resolve_default(db, "chat", owner_user_id)
    if chosen is not None and reachable_on(chosen.profile, surface):
        return chosen.profile
    if owner_user_id is None:
        return None
    usable = [model.profile for model in provider_models.models_for_capability(db, "chat", user_id=owner_user_id)
              if model.profile is not None and reachable_on(model.profile, surface)]
    return min(usable, key=lambda profile: profile.created_at, default=None)


def runner_choice(db: Session, profile_id: str | None, model: str, *, user_id: str | None) -> tuple[str | None, str, bool]:
    """节点上钉着的「连接 + 模型」,换成**跑的人**用得上的那一对:`(连接 id 或 None, 模型, 是否换过)`。

    工作流图是整个工作区共用的,而建图时按建图的人挑好的连接钉在了节点上(官方模板就是这样建的)。别的成员
    跑这张图,那条连接不是他的 —— 用不了(连接按人隔离),也不该用(花的是建图人的钱)。此前直接报「没有可用的
    AI 供应商」,他根本看不出是哪里不对。

    连接属于别人:换成他自己的默认对话连接(返回 None = 不点名,按他的默认挑),模型跟着清空 —— 那个模型名是
    那条连接上的。连接是他自己的、已经不在了、或者说不清跑的人是谁,原样交回,由后面报它该报的错。
    """
    if not profile_id or user_id is None:
        return profile_id or None, model, False
    profile = db.get(ProviderProfile, str(profile_id))
    if profile is None or profile.owner_user_id == user_id:
        return str(profile_id), model, False
    return None, "", True


def _connection_error(error: type[Exception], key: str, **params: object) -> Exception:
    """用调用方给的错误类型说「连接不可用」。

    带文案 key 的错误(LocalizedError)收 key,到展示的时候才按读的人的语言翻;别的错误类型只收
    一句话,就按**现在**的语言翻好了给它。"""
    if issubclass(error, LocalizedError):
        return error(key, **params)
    return error(tr(key, **params))


def require_connection(
    db: Session,
    profile_id: str | None = None,
    *,
    user_id: str | None,
    error: type[Exception] = RuntimeError,
    surface: ChatSurface,
    pinned_by_other: bool = False,
) -> ResolvedConnection:
    """指定 id 时要求该 profile 存在且启用;缺省用他的默认对话连接(见 default_chat_connection)。

    调用方(LLM 节点、工作流 AI 改图、发布文案、画板、提示词优化)要的都是**对话**,所以缺省按对话能力挑,
    不是「最早建的那条」(见 default_chat_connection)。

    `surface`:调用方之后在哪条通道上调这条连接(见 reachable_on),没点名时只挑这条通道上调得通的。

    `pinned_by_other`:节点上原本钉着别人的连接、已经换成按他的默认挑(见 runner_choice)。他自己也没有
    能对话的连接时,说清楚是「那条连接是别人的」,而不是一句笼统的「没有可用的连接」。

    供应商选取是 providers 领域的事——workflows / publish / agent 各自的调用方只提供
    要抛的领域错误类型,不再各自复制这段查询(此前同一逻辑存在三份)。
    """
    if profile_id:
        profile = db.get(ProviderProfile, str(profile_id))
        if profile is None or not profile.enabled or (user_id is not None and profile.owner_user_id != user_id):
            raise _connection_error(error, "providerErr_connectionMissing")
    else:
        profile = default_chat_connection(db, owner_user_id=user_id, surface=surface)
        if profile is None:
            raise _connection_error(error, "providerErr_pinnedNotYours" if pinned_by_other else "providerErr_noConnection")
    resolved = provider_credentials.resolve_connection(db, profile, user_id)
    if resolved is None:
        # 没有可用的钥匙时报出来,而不是找一把能用的顶上 —— 「我以为花的是自己的额度,
        # 其实花的是别人的钱」是这里最坏的失败方式。
        raise _connection_error(error, "providerErr_noKey", name=profile.name)
    return resolved
