"""Resolve one generation model to one effective parameter contract.

This is the seam shared by settings, generation jobs, boards, workflows and agents.  Callers do
not join provider models, declarations and templates themselves: doing so previously gave the UI
and job validation different answers for the same model.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import get_generation_adapter
from app.core.i18n import LocalizedError, get_current_locale, pick_text
from app.db.models import (
    GenerationCapabilityDeclaration,
    GenerationCapabilityProfile,
    ProviderModel,
)
from app.domain import provider_models
from app.domain.generation.catalog import (
    GENERATION_KINDS,
    capabilities_are_known,
    capabilities_for,
    resolve_capability_ref,
)
from app.domain.generation.custom_profiles import custom_capabilities_map

#: 生成种类的那一份在 catalog(叶模块);这里保留旧名,画板产出者等调用方从这里读。
KINDS = GENERATION_KINDS


class GenerationResolutionError(LocalizedError, ValueError):
    """解析不出要用的生成模型 / 参数契约。带文案 key(`genErr_*`),按请求方的语言翻。"""


@dataclass(frozen=True)
class ResolvedGenerationModel:
    row: ProviderModel
    profile_id: str
    profile_name: str
    provider: str
    model: str
    kind: str
    capabilities: dict[str, Any]
    capabilities_known: bool
    declaration_ref: str | None


def declarations_for_model(db: Session, model_id: str) -> dict[str, GenerationCapabilityDeclaration]:
    rows = db.scalars(
        select(GenerationCapabilityDeclaration).where(
            GenerationCapabilityDeclaration.provider_model_id == model_id
        )
    ).all()
    return {row.kind: row for row in rows}


def declaration_refs_for_model(db: Session, model: ProviderModel) -> dict[str, str]:
    """Opaque refs for the settings form; the browser never parses storage details."""
    refs: dict[str, str] = {}
    for kind, declaration in declarations_for_model(db, model.id).items():
        if declaration.template_id:
            refs[kind] = f"profile:{declaration.template_id}"
        elif declaration.catalog_ref:
            refs[kind] = declaration.catalog_ref
    # Compatibility for rows written before declarations were split by kind.  New writes clear it.
    if model.generation_capability_ref:
        for kind in KINDS:
            if kind in provider_models.effective_capabilities(model):
                refs.setdefault(kind, model.generation_capability_ref)
    return refs


def set_declaration_refs(db: Session, model: ProviderModel, refs: dict[str, str | None]) -> None:
    """Replace only the kinds present in ``refs`` after validating ownership and kind."""
    existing = declarations_for_model(db, model.id)
    for kind, raw_ref in refs.items():
        if kind not in KINDS:
            raise GenerationResolutionError("genErr_unknownKind", kind=kind)
        current = existing.get(kind)
        ref = (raw_ref or "").strip()
        if not ref:
            if current is not None:
                db.delete(current)
            continue

        catalog_ref: str | None = None
        template_id: str | None = None
        if ref.startswith("profile:"):
            candidate = ref.removeprefix("profile:").strip()
            template = db.get(GenerationCapabilityProfile, candidate)
            if template is not None:
                if template.provider_profile_id != model.provider_profile_id or template.kind != kind:
                    raise GenerationResolutionError("genErr_templateMismatch")
                template_id = template.id
            elif resolve_capability_ref(ref, kind) is not None:
                catalog_ref = ref
            else:
                raise GenerationResolutionError("genErr_contractMissing")
        elif resolve_capability_ref(ref, kind) is not None:
            catalog_ref = ref
        else:
            raise GenerationResolutionError("genErr_contractMissing")

        declaration = current or GenerationCapabilityDeclaration(
            provider_model_id=model.id, kind=kind
        )
        declaration.catalog_ref = catalog_ref
        declaration.template_id = template_id
        db.add(declaration)
    #: legacy 列按 kind 兜底:只写了部分 kind 时,没写到的那几个还靠它 —— 无条件下架会让
    #: 双能力模型的另一半静默落回目录。这次写入把这个模型的生成 kind 全覆盖了,才安全下架。
    if refs:
        covered = {kind for kind in provider_models.effective_capabilities(model) if kind in KINDS}
        if covered and covered <= set(refs):
            model.generation_capability_ref = None


def _resolved_ref(db: Session, model: ProviderModel, kind: str) -> tuple[str | None, dict[str, dict[str, Any]]]:
    declaration = declarations_for_model(db, model.id).get(kind)
    custom = custom_capabilities_map(db, model.provider_profile_id, kind)
    if declaration is not None:
        if declaration.template_id:
            return f"profile:{declaration.template_id}", custom
        return declaration.catalog_ref, custom
    return model.generation_capability_ref, custom


def resolve_row(db: Session, model: ProviderModel, kind: str) -> ResolvedGenerationModel:
    profile = model.profile
    if profile is None:
        raise GenerationResolutionError("genErr_connectionMissing")
    ref, custom = _resolved_ref(db, model, kind)
    # 连接自己声明的那一份(插件目录刷新时写进模型行,见 ADR 0020)。
    declared = (model.declared_capabilities or {}).get(kind)
    return ResolvedGenerationModel(
        row=model,
        profile_id=profile.id,
        profile_name=profile.name,
        provider=profile.vendor,
        model=model.model_id,
        kind=kind,
        capabilities=capabilities_for(
            profile.vendor, model.model_id, kind, ref=ref, custom=custom, declared=declared
        ),
        capabilities_known=capabilities_are_known(
            profile.vendor, model.model_id, kind, ref=ref, custom=custom, declared=declared
        ),
        declaration_ref=ref,
    )


def resolve_generation_model(
    db: Session,
    *,
    user_id: str | None,
    provider: str,
    model: str,
    kind: str,
    provider_profile_id: str | None = None,
) -> ResolvedGenerationModel:
    """Resolve an enabled, owned model; legacy calls without profile id must be unambiguous."""
    candidates = provider_models.models_for_capability(db, kind, user_id=user_id)
    matches = [
        row
        for row in candidates
        if row.model_id == model
        and row.profile is not None
        and (provider_profile_id is not None or row.profile.vendor == provider)
        and (provider_profile_id is None or row.provider_profile_id == provider_profile_id)
    ]
    if not matches:
        # 分开两种「选不到」:行在、启用着,只是**没被认成能做这件事** —— 那是能力标签的事,
        # 说「未启用或不存在」会把人支去一个根本没问题的开关那里。常见来源:以前被预设兜底
        # 认成生图模型的对话模型,存在画板格、工作流节点或定时任务里(见 evidenced_capabilities)。
        if kind in KINDS and _owned_row_lacks_kind(
            db, user_id=user_id, provider=provider, model=model, provider_profile_id=provider_profile_id
        ):
            raise GenerationResolutionError(f"genErr_modelLacksKind_{kind}", model=model)
        raise GenerationResolutionError("genErr_modelNotEnabled")
    if len(matches) > 1:
        raise GenerationResolutionError("genErr_modelAmbiguous")
    return resolve_row(db, matches[0], kind)


def _owned_row_lacks_kind(
    db: Session, *, user_id: str | None, provider: str, model: str, provider_profile_id: str | None
) -> bool:
    """他自己的、启用着的连接下有这一行模型,只是它的能力里没有所问的那种生成。"""
    return any(
        row.model_id == model
        and row.enabled
        and row.profile is not None
        and row.profile.enabled
        and (user_id is None or row.profile.owner_user_id == user_id)
        and (provider_profile_id is not None or row.profile.vendor == provider)
        and (provider_profile_id is None or row.provider_profile_id == provider_profile_id)
        for row in db.scalars(select(ProviderModel).where(ProviderModel.model_id == model))
    )


def generation_options(db: Session, kind: str, *, user_id: str | None) -> list[dict[str, Any]]:
    """能用来生成的 (连接 × 模型) 列表 —— **唯一**的那份。

    以前这份列表是前端现拼的:拿 generation_models 的目录、enabled 的档案、provider_defaults
    三张表在浏览器里做交叉连接。三份数据任何一份的口径变一点,拼出来的东西就和设置页看到的
    对不上 —— 有的模型只在目录里(ComfyUI 当年还是个叫 `workflow` 的假模型 id)、设置页里加的
    模型进不了生成页,都是这么来的。

    现在只有一条线:**有哪些模型 = provider_models**(设置页管的就是它),参数描述符按
    (vendor, model, kind) 经 resolve_row 解析(声明 → 目录 → 兜底),适配器可用性问
    get_generation_adapter。适配器不可用的照样列出但标出来 —— 藏起来的话,用户配好了
    却找不到,只会以为是自己配错了。

    `is_default` 标出**这个人**在这种生成上设的默认(provider_models.resolve_default,和「没点名
    模型时用哪个」是同一个答案)。选择器据此预选;没有默认就一项都不标 —— 选择器让人选,
    而不是拿排在第一的那个顶上(第一个只是按连接名排序的结果,不是谁的选择)。
    """
    default = provider_models.resolve_default(db, kind, user_id)
    options: list[dict[str, Any]] = []
    for row in provider_models.models_for_capability(db, kind, user_id=user_id):
        resolved = resolve_row(db, row, kind)
        options.append(
            {
                "id": f"{resolved.profile_id}:{kind}:{resolved.model}",
                "provider_profile_id": resolved.profile_id,
                "profile_name": resolved.profile_name,
                "provider": resolved.provider,
                "kind": kind,
                "model": resolved.model,
                "label": f"{resolved.profile_name} · {row.display_name or resolved.model}",
                "capabilities": _for_reader(resolved.capabilities),
                "capabilities_known": resolved.capabilities_known,
                "adapter_available": get_generation_adapter(resolved.provider, kind) is not None,
                "is_default": default is not None and default.id == row.id,
            }
        )
    options.sort(key=lambda item: (item["profile_name"], item["model"]))
    return options


def _for_reader(capabilities: dict[str, Any]) -> dict[str, Any]:
    """描述符里**给人看的字**按看的人的语言挑好:`parameter_schema` 里的 title / description 可以是
    `{"zh": …, "en": …}`(插件声明的模型参数,见 ADR 0020)。

    在这里挑而不是存的时候挑:目录是在后台刷新的,刷新那一刻的语言不是看的人的语言。
    """
    schema = capabilities.get("parameter_schema")
    if not isinstance(schema, dict):
        return capabilities
    locale = get_current_locale()
    readable: dict[str, Any] = {}
    for key, spec in schema.items():
        if isinstance(spec, dict):
            spec = {
                **spec,
                **{field: pick_text(spec[field], locale) for field in ("title", "description") if isinstance(spec.get(field), dict)},
            }
        readable[key] = spec
    return {**capabilities, "parameter_schema": readable}


def template_reference_count(db: Session, template_id: str) -> int:
    return len(
        db.scalars(
            select(GenerationCapabilityDeclaration.id).where(
                GenerationCapabilityDeclaration.template_id == template_id
            )
        ).all()
    )
