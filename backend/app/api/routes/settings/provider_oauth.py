from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.ai.sidecar.adapters import AdapterError, refresh_oauth_credential
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import OAuthAnswerIn, OAuthLoginOut, OAuthPromptOut, ProviderModelOut, ProviderProfileOut, ProviderQuotaOut
from app.core.config import settings as settings_config
from app.db.models import ProviderProfile, new_id
from app.domain import provider_credentials, provider_models
from app.domain.agent.host import mint_tool_token
from app.domain.agent.login import (
    LoginError,
    answer as answer_login,
    cancel as cancel_login,
    get_session as get_login_session,
    start_login,
)
from app.domain.provider_auth import acquire_lease, commit_credential, read_credential
from app.domain.provider_quota import QuotaUnavailable, fetch_quota, is_expired, supports_quota
from app.domain.providers import pi_provider_id

from .provider_profiles import _profile_out, _require_profile

router = APIRouter(tags=["settings"])

def _oauth_profile(db: DbSession, profile_id: str, user: CurrentUser) -> ProviderProfile:
    profile = _require_profile(db, profile_id, user)
    if profile.auth_type != "oauth" or not pi_provider_id(profile.vendor):
        raise HTTPException(status_code=400, detail="该供应商不是订阅计划,不需要授权登录")
    return profile


def _login_out(session, db: DbSession | None = None) -> OAuthLoginOut:
    return OAuthLoginOut(
        login_id=session.login_id,
        status=session.status,
        events=list(session.events),
        prompt=OAuthPromptOut(**session.prompt) if session.prompt else None,
        error=session.error,
        models=[
            ProviderModelOut(
                id=str(item.get("id", "")),
                context_window=item.get("contextWindow"),
                max_output_tokens=item.get("maxTokens"),
            )
            for item in session.models
            if item.get("id")
        ],
    )


def _store_login_catalog(db: DbSession, profile: ProviderProfile, session, user: CurrentUser) -> None:
    """登录成功后把该账号的模型目录落库,并在没有默认模型时先挑一个。

    不挑的话用户回到设置页只会看到一个空的模型选择器,而「登录成功但用不了」比登录失败更费解。
    """
    if session.status != "done" or not session.models:
        return
    # 目录是**这次登录**的结果 —— 两个人的订阅档位可以不一样,所以它跟着钥匙走。
    provider_credentials.upsert(db, profile.id, user.id).model_catalog = session.models
    # 登录带回目录后,若这条连接一个模型行都没有,先把第一个建上 ——
    # 否则「登录成功但用不了」,比登录失败更费解。
    if not provider_models.list_models(db, profile.id):
        first = str(session.models[0].get("id", "")).strip()
        if first:
            provider_models.upsert(db, profile, first, source="catalog")
    db.commit()


@router.post("/settings/providers/{profile_id}/oauth/login", response_model=OAuthLoginOut)
def start_oauth_login(profile_id: str, db: DbSession, user: CurrentUser) -> OAuthLoginOut:
    """发起订阅计划的授权登录 —— 登的是**自己**的账号。

    这里不再要求部署管理员:订阅计划(Claude Pro/Max、Kimi Code)是按人计费的,一个部署里
    每个人都该能挂自己的。连接怎么配仍然是管理员的事,那是另一回事。
    """
    profile = _oauth_profile(db, profile_id, user)
    from app.domain.agent.host import mint_tool_token

    try:
        session = start_login(
            login_id=new_id(),
            profile_id=profile.id,
            pi_provider=pi_provider_id(profile.vendor),
            api_base=f"http://{settings_config.backend_host}:{settings_config.backend_port}",
            token=mint_tool_token(db, user),
            credential=read_credential(provider_credentials.get(db, profile.id, user.id)),
        )
    except LoginError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _login_out(session)


@router.get("/settings/providers/{profile_id}/oauth/login/{login_id}", response_model=OAuthLoginOut)
def poll_oauth_login(profile_id: str, login_id: str, db: DbSession, user: CurrentUser) -> OAuthLoginOut:
    profile = _oauth_profile(db, profile_id, user)
    session = get_login_session(login_id)
    if session is None or session.profile_id != profile_id:
        raise HTTPException(status_code=404, detail="登录会话已结束")
    _store_login_catalog(db, profile, session, user)
    return _login_out(session)


@router.post("/settings/providers/{profile_id}/oauth/login/{login_id}/answer", response_model=OAuthLoginOut)
def answer_oauth_login(
    profile_id: str, login_id: str, body: OAuthAnswerIn, db: DbSession, user: CurrentUser
) -> OAuthLoginOut:
    _oauth_profile(db, profile_id, user)
    session = get_login_session(login_id)
    if session is None or session.profile_id != profile_id:
        raise HTTPException(status_code=404, detail="登录会话已结束")
    if not answer_login(login_id, body.prompt_id, body.answer):
        raise HTTPException(status_code=409, detail="这一步已经不在等待作答了")
    return _login_out(session)


@router.delete("/settings/providers/{profile_id}/oauth/login/{login_id}", status_code=204)
def cancel_oauth_login(profile_id: str, login_id: str, db: DbSession, user: CurrentUser) -> None:
    _oauth_profile(db, profile_id, user)
    cancel_login(login_id)



@router.post("/settings/providers/{profile_id}/quota", response_model=ProviderQuotaOut)
def fetch_provider_quota(profile_id: str, db: DbSession, user: CurrentUser) -> ProviderQuotaOut:
    """查一次订阅额度。

    **只在用户点击时执行**,不做后台轮询:这些端点都不是官方承诺的公开接口(Anthropic 的
    oauth/usage、Codex 的 codex/usage 都是各自 CLI 内部在用),定时轮询既容易撞限流,也会
    在对方改接口后变成后台里一直失败的任务。

    查不到不抛 5xx:"这家不支持"和"这次没查成"都是正常结果,前端要据此显示不同的话,
    500 会被统一的错误提示吞成一句"请求失败"。
    """
    profile = _oauth_profile(db, profile_id, user)
    pi_provider = pi_provider_id(profile.vendor)
    if not supports_quota(pi_provider):
        return ProviderQuotaOut(supported=False)
    mine = provider_credentials.get(db, profile.id, user.id)
    credential = read_credential(mine)
    # 令牌过期就先刷新再查。自动刷新原本只发生在对话路径上(pi 解析模型鉴权时按 expires 判),
    # 于是"很久没聊天"之后这条旁路一律撞 401,而档案上明明写着已授权。刷新协议仍在 pi 那边,
    # 这里只是让它跑一次。
    if credential is not None and is_expired(credential):
        try:
            refresh_oauth_credential(
                api_base=f"http://{settings_config.backend_host}:{settings_config.backend_port}",
                token=mint_tool_token(db, user),
                pi_provider=pi_provider or "",
                profile_id=profile.id,
                credential=credential,
            )
            db.refresh(mine) if mine is not None else None
            credential = read_credential(provider_credentials.get(db, profile.id, user.id))
        except AdapterError as exc:
            return ProviderQuotaOut(supported=True, error=f"令牌刷新失败:{exc}")
    try:
        snapshot = fetch_quota(pi_provider, credential)
    except QuotaUnavailable as exc:
        return ProviderQuotaOut(supported=True, error=str(exc))
    return ProviderQuotaOut(supported=True, **snapshot)


@router.delete("/settings/providers/{profile_id}/oauth", response_model=ProviderProfileOut)
def logout_oauth_provider(profile_id: str, db: DbSession, user: CurrentUser) -> ProviderProfileOut:
    """解除**我自己**在这条连接上的订阅登录。登出是应用侧动作,跑对话的 sidecar 无权做。"""
    profile = _oauth_profile(db, profile_id, user)
    lease = acquire_lease(profile.id, user.id)
    commit_credential(db, profile.id, user.id, lease, None)
    mine = provider_credentials.get(db, profile.id, user.id)
    if mine is not None:
        mine.model_catalog = None
    db.commit()
    db.refresh(profile)
    return _profile_out(db, profile, user)

