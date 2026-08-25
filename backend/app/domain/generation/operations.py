from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import FIRST_FRAME, REFERENCE_IMAGE, SOURCE_ROLES, get_provider
from app.domain.generation.catalog import known_capabilities_for
from app.db.models import GenerationJob, GenerationSession, ProviderProfile, now
from app.domain.jobs import create_job


class GenerationDomainError(ValueError):
    pass


def create_generation_job(
    db: Session,
    *,
    workspace_id: str,
    session_id: str | None,
    project_id: str | None,
    created_by: str | None,
    provider: str,
    model: str,
    kind: str,
    prompt: str,
    negative_prompt: str,
    parameters: dict[str, Any],
    source_assets: list[dict[str, str]],
    provider_profile_id: str | None = None,
) -> tuple[GenerationJob, Any]:
    provider = provider.strip()
    model = model.strip()
    provider_profile = _resolve_provider_profile(db, provider_profile_id)
    if provider_profile is not None:
        provider = provider_profile.vendor
    elif not _vendor_can_generate(db, provider, kind):
        # 没点名连接时,至少要有一条**启用的**连接声明了这个 vendor 能做这种生成 ——
        # 以前查的是 generation_models 那张目录表,而目录说"这个 vendor 有这个模型"和
        # "用户配了这条连接"是两回事,于是删掉档案之后照样能提交任务、跑到一半才失败。
        raise GenerationDomainError("Generation model is not enabled or does not exist")
    if get_provider(provider, kind) is None:
        raise GenerationDomainError(f"Generation adapter is not available for {provider}/{kind}")

    validate_against_capabilities(provider, model, kind, parameters, source_assets)

    session = _resolve_session(db, workspace_id=workspace_id, session_id=session_id, prompt=prompt)
    request = {
        "project_id": project_id,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "parameters": parameters,
        "source_assets": source_assets,
    }
    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="ai_generation",
        created_by=created_by,
        payload={
            "subject": prompt[:80],
            "provider_profile_id": provider_profile.id if provider_profile else None,
            "provider": provider,
            "model": model,
            "kind": kind,
            "request": request,
        },
        message="jobMsg_generationQueued",
    )
    generation = GenerationJob(
        workspace_id=workspace_id,
        session_id=session.id,
        job_id=job.id,
        provider_profile_id=provider_profile.id if provider_profile else None,
        provider=provider,
        model=model,
        kind=kind,
        request=request,
    )
    session.updated_at = now()
    db.add(generation)
    db.commit()
    db.refresh(generation)
    db.refresh(job)
    return generation, job


def _resolve_provider_profile(db: Session, provider_profile_id: str | None) -> ProviderProfile | None:
    if not provider_profile_id:
        return None
    profile = db.get(ProviderProfile, provider_profile_id)
    if profile is None or not profile.enabled:
        raise GenerationDomainError("Generation provider profile is not available")
    return profile


def _resolve_session(db: Session, *, workspace_id: str, session_id: str | None, prompt: str) -> GenerationSession:
    if session_id:
        session = db.get(GenerationSession, session_id)
        if session is None or session.workspace_id != workspace_id:
            raise GenerationDomainError("Generation session not found in this workspace")
        if session.title == "新生成":
            session.title = _title_from_prompt(prompt)
        return session
    session = GenerationSession(workspace_id=workspace_id, title=_title_from_prompt(prompt))
    db.add(session)
    db.flush()
    return session


def _title_from_prompt(prompt: str) -> str:
    title = " ".join(prompt.strip().split())
    return title[:40] or "新生成"


def _vendor_can_generate(db: Session, vendor: str, kind: str) -> bool:
    """有没有一条启用的连接,其下有启用的模型声明了这种生成能力。"""
    from app.domain import provider_models

    return any(
        model.profile is not None and model.profile.vendor == vendor
        for model in provider_models.models_for_capability(db, kind)
    )


#: 没写角色时按生成类型兜底:图生视频的那张图是首帧,图生图的那张图是参考。
#: 这是**两种介质里最常见的那个意思**,不是随便挑的默认值。
DEFAULT_ROLE_BY_KIND = {"video": FIRST_FRAME, "image": REFERENCE_IMAGE}


def parse_source_assets(value: Any, *, kind: str) -> list[dict[str, str]]:
    """把各种形态的「输入素材」归一成 [{asset_id, role}]。

    接受三种写法,因为它们来自三个地方:
      · `[{"asset_id": …, "role": …}]` —— 接口和界面发的;
      · `["id", "id:last_frame"]` 或换行/逗号分隔的字符串 —— 工作流的模板字段。模板是把
        上游节点输出({{gen-1.asset_id}})接进来的唯一方式,只认结构化列表的话这个字段在
        编辑器里就没法用;
      · 裸 id —— 不写角色,按 kind 兜底。
    """
    default_role = DEFAULT_ROLE_BY_KIND.get(kind, FIRST_FRAME)
    items: list[Any]
    if isinstance(value, str):
        items = [part.strip() for part in value.replace(",", "\n").replace("，", "\n").split("\n")]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return []
    out: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, dict):
            asset_id = str(item.get("asset_id") or "").strip()
            role = str(item.get("role") or default_role).strip()
        else:
            text = str(item).strip()
            if not text:
                continue
            asset_id, _, role = text.partition(":")
            asset_id, role = asset_id.strip(), (role.strip() or default_role)
        if not asset_id:
            continue
        if role not in SOURCE_ROLES:
            raise GenerationDomainError(f"未知的素材角色:{role}")
        out.append({"asset_id": asset_id, "role": role})
    return out


#: 每种能力都认的通用参数 —— 它们不进描述符的 parameter_keys(那一栏说的是「这个模型有什么
#: 可调的」),但每条路径都可能带上。
_ALWAYS_ALLOWED = {"negative_prompt", "seed"}

#: 素材角色也可以用 `<role>_url` 直接给外链,见 ai/providers/base.ROLE_URL_PARAMETERS。
_ROLE_URL_KEYS = {f"{role}_url" for role in SOURCE_ROLES} | {"image_url"}


def validate_against_capabilities(
    provider: str,
    model: str,
    kind: str,
    parameters: dict[str, Any],
    source_assets: list[dict[str, str]],
) -> None:
    """按描述符拦下这个模型不认的参数和素材角色。

    **拦在这里而不是各个入口**:界面、智能体、工作流、定时任务四条路都汇到这个函数,
    在别处拦就得拦四遍,而漏掉的那一遍不会报错 —— 它会把参数原样发给供应商,拿回一个
    「invalid parameter」,或者更糟:那家默默忽略了它,于是用户要的 10 秒变成了默认的 5 秒,
    而界面上一切正常。

    描述符查不到的模型(用户自己加的、ComfyUI 的工作流)放行:我们不知道它认什么,
    猜着拦只会挡住本来能用的东西。
    """
    capabilities = known_capabilities_for(provider, model, kind)
    if capabilities is None:
        return
    keys = capabilities.get("parameter_keys")
    if not keys:
        return
    allowed = set(keys) | _ALWAYS_ALLOWED | _ROLE_URL_KEYS
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        raise GenerationDomainError(
            f"{provider}/{model} 不支持这些参数:{'、'.join(unknown)};可用的是:{'、'.join(sorted(keys))}"
        )
    for name, choices_key in (("size", "sizes"), ("resolution", "resolutions"), ("aspect_ratio", "aspect_ratios")):
        choices = capabilities.get(choices_key)
        value = parameters.get(name)
        if choices and value and str(value) not in [str(one) for one in choices]:
            raise GenerationDomainError(f"{provider}/{model} 的 {name} 只能是:{'、'.join(str(c) for c in choices)}")
    durations = capabilities.get("duration_seconds")
    duration = parameters.get("duration_seconds")
    if durations and duration is not None and int(duration) not in [int(one) for one in durations]:
        raise GenerationDomainError(
            f"{provider}/{model} 的时长只能是:{'、'.join(str(one) for one in durations)} 秒"
        )
    for entry in source_assets:
        role = entry.get("role") or ""
        if role not in allowed:
            raise GenerationDomainError(
                f"{provider}/{model} 不支持「{role}」这种素材;它支持的是:"
                f"{'、'.join(one for one in keys if one in SOURCE_ROLES) or '无'}"
            )
