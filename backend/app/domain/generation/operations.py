from __future__ import annotations

from collections import Counter

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
    # 时长有两种形状:**枚举**(只收这几个档)或**区间**(min..max 内的任意整数)。
    # 只校验枚举的话,区间型的模型这里全放行,越界的值要等供应商拒了才知道 —— 而那时
    # 任务已经建好、扣了一次配额,报的还是一句英文的 InvalidParameter。
    durations = capabilities.get("duration_seconds")
    duration = parameters.get("duration_seconds")
    if duration is not None:
        if durations:
            if int(duration) not in [int(one) for one in durations]:
                raise GenerationDomainError(
                    f"{provider}/{model} 的时长只能是:{'、'.join(str(one) for one in durations)} 秒"
                )
        else:
            low = capabilities.get("min_duration_seconds")
            high = capabilities.get("max_duration_seconds")
            if (low is not None and int(duration) < int(low)) or (high is not None and int(duration) > int(high)):
                raise GenerationDomainError(
                    f"{provider}/{model} 的时长要在 {low or 1}–{high} 秒之间"
                )
    counts: Counter[str] = Counter()
    for entry in source_assets:
        role = entry.get("role") or ""
        if role not in allowed:
            raise GenerationDomainError(
                f"{provider}/{model} 不支持「{role}」这种素材;它支持的是:"
                f"{'、'.join(one for one in keys if one in SOURCE_ROLES) or '无'}"
            )
        counts[role] += 1
    _check_source_counts(provider, model, capabilities, counts)
    _check_conditional_duration(provider, model, capabilities, counts, parameters)


def _check_conditional_duration(
    provider: str,
    model: str,
    capabilities: dict[str, Any],
    counts: Counter[str],
    parameters: dict[str, Any],
) -> None:
    """有些上限**跟着素材变**:万相参考生视频不带参考视频能到 15 秒,带上就只剩 10 秒。

    不拦的话,用户挂了参考视频再选 12 秒 —— 提交过得去,要等任务失败才知道,而那时候
    报的是一句英文。写死 10 也不行:不带参考视频的那条路本来就能跑到 15 秒。
    """
    duration = parameters.get("duration_seconds")
    if duration is None:
        return
    for role, cap in (capabilities.get("conditional_max_duration_seconds") or {}).items():
        if counts.get(role) and int(duration) > int(cap):
            raise GenerationDomainError(
                f"{provider}/{model} 挂了{_label(role)}时,时长最多 {cap} 秒(不挂能到 "
                f"{capabilities.get('max_duration_seconds')} 秒)"
            )


#: 角色的中文名。报错要说人话:用户在界面上看到的是「参考图」,不是 reference_image。
_ROLE_LABELS = {
    "first_frame": "首帧",
    "last_frame": "尾帧",
    "reference_image": "参考图",
    "reference_video": "参考视频",
    "reference_audio": "参考音频",
    "source_video": "待编辑的视频",
    "first_clip": "待续写的片段",
    "driving_audio": "驱动音频",
}


#: 为什么互斥 —— 说清楚每一组各自是干什么的,比一句「不兼容」有用:用户下一步要做的是
#: 挑一条路,而不是猜哪个参数写错了。
_WHY_EXCLUSIVE = (
    "首尾帧决定成片的第一格和最后一格;"
    "参考素材一帧都不出现在成片里,只影响风格与主体;"
    "待续写的片段则是成片的开头、后面接着往下拍。"
)


def _label(role: str) -> str:
    return _ROLE_LABELS.get(role, role)


def _check_source_counts(
    provider: str,
    model: str,
    capabilities: dict[str, Any],
    counts: Counter[str],
) -> None:
    """按描述符查三件事:**每种给了几份、两组有没有混着用、有没有该搭伴的落了单**。

    拦在提交之前,是因为供应商那边的回话帮不上忙:火山说的是
    `expected at most 9 reference images but got 10 instead` —— 英文、说的是数组下标,
    而用户看到的是自己挂了十张图。更要紧的是**混用那一条**:首帧配参考图必然 400,
    而界面此前完全允许这么挂,用户只会觉得「这模型怎么老是失败」。
    """
    limits = capabilities.get("source_limits") or {}
    for role, count in counts.items():
        cap = limits.get(role)
        if cap is not None and count > int(cap):
            raise GenerationDomainError(
                f"{provider}/{model} 最多收 {cap} 份{_label(role)},这次给了 {count} 份"
            )

    used = {role for role, count in counts.items() if count}
    groups = [set(group) for group in capabilities.get("exclusive_source_groups") or []]
    touched = [group for group in groups if group & used]
    if len(touched) > 1:
        names = ["、".join(_label(r) for r in sorted(group & used)) for group in touched]
        raise GenerationDomainError(
            f"{provider}/{model} 的{' 和 '.join(names)}不能一起用:"
            f"{_WHY_EXCLUSIVE}它们是不同的路子,一次只能走一条。"
        )

    # 每一条是「这几种里至少给一份」。写成嵌套而不是平铺的一串,是因为两种要求都真实存在:
    # 视频编辑必须给那一段视频(只有一个选项),参考生视频则是参考图或参考视频给一个就行。
    for options in capabilities.get("requires_source") or []:
        if not (set(options) & used):
            raise GenerationDomainError(
                f"{provider}/{model} 必须给一份{'或'.join(_label(one) for one in options)}"
            )

    for role, companions in (capabilities.get("requires_companion") or {}).items():
        if role in used and not (set(companions) & used):
            raise GenerationDomainError(
                f"{provider}/{model} 的{_label(role)}不能单独使用,"
                f"要搭配{'或'.join(_label(one) for one in companions)}一起给"
            )
