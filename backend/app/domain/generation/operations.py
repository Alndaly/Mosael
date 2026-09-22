from __future__ import annotations

import re

from collections import Counter

from typing import Any

from sqlalchemy.orm import Session

from app.ai.providers import (
    FIRST_FRAME,
    REFERENCE_IMAGE,
    SOURCE_ROLES,
    allowed_source_url_parameters,
    direct_media_url,
    get_generation_adapter,
    roles_supplied_via_url,
)
from app.domain.generation.catalog import (
    SOURCE_GROUP_DROPS,
    SOURCE_GROUPS,
    SOURCE_ROLE_LABELS,
    known_capabilities_for,
)
from app.domain.generation.resolution import GenerationResolutionError, resolve_generation_model
from app.db.models import Asset, GenerationJob, GenerationSession, ProviderProfile, now
from app.domain.jobs import create_job


class GenerationDomainError(ValueError):
    pass


def requested_negative_prompt(negative_prompt: str, parameters: dict[str, Any]) -> str:
    """兼容统一参数入口，同时保持领域请求只有一个负向提示字段。

    UI 有独立输入框，智能体/工作流则会按能力描述符把它放进 parameters。装配时提升一次，
    Adapter 永远只读 ``GenerationRequest.negative_prompt``，避免每家实现两套优先级。
    """
    explicit = str(negative_prompt or "").strip()
    return explicit or str(parameters.get("negative_prompt") or "").strip()


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
    if not provider or not model:
        provider, model, provider_profile_id = _default_model(db, kind, created_by)
    try:
        resolved = resolve_generation_model(
            db,
            user_id=created_by,
            provider=provider,
            model=model,
            kind=kind,
            provider_profile_id=provider_profile_id,
        )
    except GenerationResolutionError as exc:
        raise GenerationDomainError(str(exc)) from exc
    provider_profile = resolved.row.profile
    provider = resolved.provider
    if get_generation_adapter(provider, kind) is None:
        raise GenerationDomainError(f"Generation adapter is not available for {provider}/{kind}")

    validate_against_capabilities(
        provider,
        model,
        kind,
        parameters,
        source_assets,
        capabilities=resolved.capabilities if resolved.capabilities_known else None,
    )
    _validate_source_assets(
        db, workspace_id, source_assets,
        capabilities=resolved.capabilities if resolved.capabilities_known else None,
    )
    negative_prompt = requested_negative_prompt(negative_prompt, parameters)

    session = _resolve_session(
        db, workspace_id=workspace_id, session_id=session_id, prompt=prompt, created_by=created_by
    )
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


def _default_model(db: Session, kind: str, user_id: str | None) -> tuple[str, str, str | None]:
    """没点名模型时用**这个人**在这种能力上的默认 —— 画板、定时任务、智能体都可能不点名。

    此前这段在三个入口里各抄一份,工作流节点则干脆不认;放在漏斗里,四个入口就是同一个答案。
    没有默认就直说,不替他挑一个(见 provider_models.resolve_default 的说明)。
    """
    from app.domain import provider_models

    default = provider_models.resolve_default(db, kind, user_id)
    if default is None or default.profile is None:
        raise GenerationDomainError("还没有可用的生成模型,先去设置里配一个")
    return default.profile.vendor, default.model_id, default.provider_profile_id


def _validate_source_assets(
    db: Session,
    workspace_id: str,
    source_assets: list[dict[str, str]],
    capabilities: dict[str, Any] | None = None,
) -> None:
    """在创建任务前确认引用仍有效,**并且它能按这家要的形式交付**。

    以前到 worker 真正下载/读取素材时才发现引用已删除或来自别的工作区。此时界面已经进入
    loading，用户只得到一句没有素材名称的异步失败。同步拦截既不制造一个注定失败的任务，
    也能明确告诉他该重新连接哪一个槽位。runner 仍会复查，以覆盖提交后被删除的竞态。

    **交付形式**:一份素材有两种发法 —— 内联字节(base64 data URL)或者一条链接。哪一种
    可用是供应商按角色定的:方舟的参考图两种都收,参考视频**只收链接**(官方文档明写不收
    Base64)。素材是从一条公网直链导入的就有链接可用,照常放行;是本地文件就只有内联那一种,
    这家用不了 —— 而那个 400 是**花钱之后**才来的(一段最大 200MB 的视频得先整个传上去),
    回话还是一长串英文,中间夹着一个 Request id。
    """
    url_only = set((capabilities or {}).get("url_only_roles") or [])
    for entry in source_assets:
        asset_id = str(entry.get("asset_id") or "").strip()
        role = str(entry.get("role") or FIRST_FRAME)
        asset = db.get(Asset, asset_id)
        label = SOURCE_ROLE_LABELS.get(role, role)
        if asset is None or asset.workspace_id != workspace_id:
            short = f"（{asset_id[:12]}…）" if asset_id else ""
            raise GenerationDomainError(f"{label}素材{short}已删除或不在当前工作区，请重新连接或选择")
        if role in url_only and not direct_media_url((asset.media_info or {}).get("source_url")):
            raise GenerationDomainError(
                f"这个模型的{label}只能按链接给,不能上传本地文件 —— "
                f"「{asset.name}」是本地素材,没有可公开访问的地址。"
                f"请改用一条公网直链(界面上直接粘链接即可),或先把它传到一个能公开访问的地方"
            )


def _resolve_provider_profile(
    db: Session,
    provider_profile_id: str | None,
    *,
    owner_user_id: str | None,
) -> ProviderProfile | None:
    if not provider_profile_id:
        return None
    profile = db.get(ProviderProfile, provider_profile_id)
    if profile is None or not profile.enabled or (owner_user_id is not None and profile.owner_user_id != owner_user_id):
        raise GenerationDomainError("Generation provider profile is not available")
    return profile


def _resolve_session(
    db: Session, *, workspace_id: str, session_id: str | None, prompt: str, created_by: str | None
) -> GenerationSession:
    """这一次生成收在哪条会话线程里。没点名就现开一条。

    **现开的那条必须有主。** 生成会话和对话一样是某人的私人线程,列表按
    `owner_user_id == 我 或 被共享` 过滤 —— 不设主人的话它是 NULL,谁都匹配不上,
    于是这条记录**连创建它的人自己都看不见**:图进了素材库,而带着提示词、参数和花费的
    那条记录成了孤儿,既回不到历史里,也不进成本核算。

    界面那条路一直是传 session_id 的,所以这件事只在**另外四个入口**上发生:从画板生成、
    工作流的 ai_generate、智能体生成、定时任务 —— 它们都传 session_id=None。
    """
    if session_id:
        session = db.get(GenerationSession, session_id)
        if session is None or session.workspace_id != workspace_id:
            raise GenerationDomainError("Generation session not found in this workspace")
        if session.title == "新生成":
            session.title = _title_from_prompt(prompt)
        return session
    session = GenerationSession(
        workspace_id=workspace_id, title=_title_from_prompt(prompt), owner_user_id=created_by
    )
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


def keep_source_group(sources: list[dict[str, str]], group: str) -> list[dict[str, str]]:
    """只留这一组(以及两组之外的角色,例如待编辑的视频);`all` 原样返回。分组见 catalog.SOURCE_GROUPS。"""
    if group not in SOURCE_GROUPS:
        raise GenerationDomainError(f"素材分组只能是 {' / '.join(SOURCE_GROUPS)}")
    dropped = set(SOURCE_GROUP_DROPS.get(group, ()))
    return [source for source in sources if source["role"] not in dropped]


#: 模板串的样子。只有它里面的冒号可以不是角色分隔符 —— 别处的冒号一律当成在写角色。
_TEMPLATE = re.compile(r"\{\{.*\}\}")


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
        #: **某一项本身就是一组** —— 工作流里写 `{{角色三视图.results}}` 这种整串引用时,插值保留
        #: 列表原样(见 workflows.interpolate)。摊平成同一层,和一条一条写出来是一回事。
        items = []
        for item in value:
            items.extend(item if isinstance(item, (list, tuple)) else [item])
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
            # 从**右边**切,因为模板串自己也可能带冒号(`{{node.a:b}}`)。从左边切的话那种
            # 写法会被腰斩成 `{{node.a` + 角色 `b}}`,报一句「未知的素材角色」,而用户看着
            # 自己那行写得好好的。前端序列化用的就是右起规则,两边得是同一条。
            head, sep, tail = text.rpartition(":")
            if not sep:
                asset_id, role = text, default_role
            elif _TEMPLATE.search(text) and tail.strip() not in SOURCE_ROLES:
                # 模板串里那个冒号是它自己的一部分 —— 整条都是值。**只对模板串放行**:
                # 不是模板的话,写了冒号就是在写角色,拼错了要当场说,不能默默走默认
                # (那样任务照样成功,只是那张图当成了别的用途,界面上什么都没说)。
                asset_id, role = text, default_role
            else:
                asset_id, role = head.strip(), (tail.strip() or default_role)
        if not asset_id:
            continue
        if role not in SOURCE_ROLES:
            raise GenerationDomainError(f"未知的素材角色:{role}")
        out.append({"asset_id": asset_id, "role": role})
    return out


def allowed_parameter_keys(capabilities: dict[str, Any], kind: str | None = None) -> set[str]:
    """这个模型**认哪些参数键**。

    抽出来是因为有两个人要问同一个问题:校验器(拦下不认的)和棘轮
    (tests/test_adapters_read_only_declared_parameters,检查适配器读的键够不够得着)。
    各算一遍的话两边会分头演进 —— 而那正是这条规则要防的事:棘轮以为某个键不被允许、
    校验器其实放行,于是它报一个不存在的问题;反过来则是漏报。
    """
    declared = set(capabilities.get("parameter_keys") or ())
    roles = declared & set(SOURCE_ROLES)
    # kind 只影响无类型别名 image_url。棘轮只关心 Adapter 是否读到“某个允许键”，没有 kind
    # 时取两个领域含义的并集；真正的提交校验总会传 kind，因此不会多放行。
    url_keys = (
        allowed_source_url_parameters(roles, kind)
        if kind is not None
        else allowed_source_url_parameters(roles, "image") | allowed_source_url_parameters(roles, "video")
    )
    # seed / negative_prompt 不是跨引擎通用能力。只有描述符显式声明、Adapter 确实会发送时
    # 才能放行；否则任务可能成功，但用户要求被静默丢弃。
    allowed = declared | url_keys
    # “输出可能带声音”与“API 有 generate_audio 开关”不是一回事。万相能携带驱动音频，
    # 但没有这个布尔参数；把 supports_audio 当开关会让 UI 发一个 Adapter 完全不读的键。
    if capabilities.get("supports_generate_audio"):
        allowed.add("generate_audio")
    return allowed


_UNSET_CAPABILITIES = object()


def _integer_parameter(provider: str, model: str, name: str, value: Any) -> int:
    """Canonical integer parameters fail at submission instead of crashing in an Adapter.

    Workflow fields may legitimately arrive as numeric strings, but booleans and fractional
    numbers must not be truncated by ``int()`` (``5.9`` silently becoming five seconds).
    """
    if isinstance(value, bool):
        raise GenerationDomainError(f"{provider}/{model} 的 {name} 必须是整数")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise GenerationDomainError(f"{provider}/{model} 的 {name} 必须是整数")
    text = str(value).strip()
    if not re.fullmatch(r"-?\d+", text):
        raise GenerationDomainError(f"{provider}/{model} 的 {name} 必须是整数")
    return int(text)


def validate_against_capabilities(
    provider: str,
    model: str,
    kind: str,
    parameters: dict[str, Any],
    source_assets: list[dict[str, str]],
    *,
    capabilities: dict[str, Any] | None | object = _UNSET_CAPABILITIES,
) -> None:
    """按描述符拦下这个模型不认的参数和素材角色。

    **拦在这里而不是各个入口**:界面、智能体、工作流、定时任务四条路都汇到这个函数,
    在别处拦就得拦四遍,而漏掉的那一遍不会报错 —— 它会把参数原样发给供应商,拿回一个
    「invalid parameter」,或者更糟:那家默默忽略了它,于是用户要的 10 秒变成了默认的 5 秒,
    而界面上一切正常。

    描述符查不到的模型(用户自己加的、ComfyUI 的工作流)放行:我们不知道它认什么,
    猜着拦只会挡住本来能用的东西。
    """
    if capabilities is _UNSET_CAPABILITIES:
        capabilities = known_capabilities_for(provider, model, kind)
    if capabilities is None:
        return
    keys = capabilities.get("parameter_keys")
    if not keys:
        return
    allowed = allowed_parameter_keys(capabilities, kind)
    unknown = sorted(set(parameters) - allowed)
    if unknown:
        raise GenerationDomainError(
            f"{provider}/{model} 不支持这些参数:{'、'.join(unknown)};可用的是:{'、'.join(sorted(keys))}"
        )
    for name in capabilities.get("boolean_parameters") or ():
        if name in parameters and not isinstance(parameters[name], bool):
            raise GenerationDomainError(f"{provider}/{model} 的 {name} 必须是布尔值 true/false")
    for name, choices_key in (("size", "sizes"), ("resolution", "resolutions"), ("aspect_ratio", "aspect_ratios")):
        choices = capabilities.get(choices_key)
        value = parameters.get(name)
        if choices and value and str(value) not in [str(one) for one in choices]:
            raise GenerationDomainError(f"{provider}/{model} 的 {name} 只能是:{'、'.join(str(c) for c in choices)}")
    for name, choices in (capabilities.get("parameter_choices") or {}).items():
        value = parameters.get(name)
        if choices and value is not None and str(value) not in [str(one) for one in choices]:
            raise GenerationDomainError(f"{provider}/{model} 的 {name} 只能是:{'、'.join(str(c) for c in choices)}")
    # 时长有两种形状:**枚举**(只收这几个档)或**区间**(min..max 内的任意整数)。
    # 只校验枚举的话,区间型的模型这里全放行,越界的值要等供应商拒了才知道 —— 而那时
    # 任务已经建好、扣了一次配额,报的还是一句英文的 InvalidParameter。
    durations = capabilities.get("duration_seconds")
    special_durations = [int(one) for one in capabilities.get("duration_special_values") or ()]
    duration = parameters.get("duration_seconds")
    if duration is not None:
        numeric_duration = _integer_parameter(provider, model, "duration_seconds", duration)
        if numeric_duration in special_durations:
            pass
        elif durations:
            if numeric_duration not in [int(one) for one in durations]:
                raise GenerationDomainError(
                    f"{provider}/{model} 的时长只能是:{'、'.join(str(one) for one in durations)} 秒"
                )
        else:
            low = capabilities.get("min_duration_seconds")
            high = capabilities.get("max_duration_seconds")
            outside_range = low is None and high is None
            outside_range = outside_range or (low is not None and numeric_duration < int(low))
            outside_range = outside_range or (high is not None and numeric_duration > int(high))
            if outside_range:
                special = f"，或 {'、'.join(str(one) for one in special_durations)}（自动）" if special_durations else ""
                raise GenerationDomainError(
                    f"{provider}/{model} 的时长要在 {low or 1}–{high} 秒之间{special}"
                )
        resolution = str(parameters.get("resolution") or "")
        duration_by_resolution = capabilities.get("duration_by_resolution") or {}
        resolution_durations = duration_by_resolution.get(resolution)
        if resolution_durations and numeric_duration not in [int(one) for one in resolution_durations]:
            raise GenerationDomainError(
                f"{provider}/{model} 的 {resolution} 分辨率只支持 "
                f"{'、'.join(str(one) for one in resolution_durations)} 秒"
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
    # 外链与素材库同权:`<role>_url` 供的角色也计入 —— 只数 source_assets 的话,
    # 粘链接(不选素材)的用户会被 requires_source 误拦在「必须给一份首帧」上。
    counts.update(roles_supplied_via_url(parameters, kind))
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


#: 角色的中文名住在描述符那一层(catalog.SOURCE_ROLE_LABELS),这里只是读它 —— 报错要说人话:
#: 用户在界面上看到的是「参考图」,不是 reference_image。此前这张表在这里另存了一份,
#: 而三份表里漏掉哪一份都不会报错。


def _label(role: str) -> str:
    return SOURCE_ROLE_LABELS.get(role, role)


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

    # 参考图还有个**下限**,而且只有可灵有:它的多图参考是先拿几张图建一个主体,
    # 而建主体要 1 张正面图 + 至少 1 张其他角度。只给一张的话,那一步会在提交之后才失败,
    # 报的还是可灵那边关于 refer_images 的话 —— 用户根本不知道自己少挂了一张。
    floor = capabilities.get("min_reference_images")
    given = counts.get("reference_image", 0)
    if floor and given and given < int(floor):
        raise GenerationDomainError(
            f"{provider}/{model} 的多图参考至少要 {floor} 张参考图"
            f"(第一张是正面图,其余是其他角度),这次只给了 {given} 张"
        )

    used = {role for role, count in counts.items() if count}
    groups = [set(group) for group in capabilities.get("exclusive_source_groups") or []]
    touched = [group for group in groups if group & used]
    if len(touched) > 1:
        names = ["、".join(_label(r) for r in sorted(group & used)) for group in touched]
        raise GenerationDomainError(
            f"{provider}/{model} 的{' 和 '.join(names)}不能一起用:"
            "它们对应不同的生成模式,一次只能选择一组。"
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
