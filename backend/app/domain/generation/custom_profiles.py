"""用户自己写下的参数组:校验、读取、解析。

**这是"手填错了不当场报错"那个风险的唯一缓解处。** 内置目录里的每一份都是我们查证过的;
用户填的那份是他的断言,填错的代价是生成请求被供应商拒掉 —— 那已经是很远的地方了,所以
能在保存这一刻拦下来的都要拦。

拦的是**形状**,不是**事实**:我们判得出 `sizes` 必须是一串字符串、`max_num_images` 必须是
正整数、`parameter_keys` 里的名字得是界面认得的那几个;判不出的是"这个端点真的支持 4 张吗"。
后者只有端点自己知道 —— 所以界面上要说清这份是用户声明的,不是我们核过的。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GenerationCapabilityProfile


class CapabilityProfileError(ValueError):
    """保存被拒。message 已经是可以直接给用户看的话。"""


#: 描述符里认得的键。**白名单而不是黑名单**:写错一个键名(`sizes` 写成 `size`)不会报错,
#: 只会安静地什么都不生效 —— 那正是这个仓库一直在消灭的那种沉默。
_KNOWN_KEYS: dict[str, str] = {
    "modes": "str_list",
    "parameter_keys": "str_list",
    "sizes": "str_list",
    "resolutions": "str_list",
    "aspect_ratios": "str_list",
    "duration_seconds": "int_list",
    "duration_special_values": "int_list",
    "boolean_parameters": "str_list",
    "default_size": "str",
    "default_resolution": "str",
    "default_aspect_ratio": "str",
    "default_quality": "str",
    "default_background": "str",
    "default_output_format": "str",
    "default_moderation": "str",
    "default_duration_seconds": "int",
    "default_generate_audio": "bool",
    "default_prompt_extend": "bool",
    "max_num_images": "positive_int",
    "max_prompt_chars": "positive_int",
    "max_duration_seconds": "positive_int",
    "min_duration_seconds": "positive_int",
    "min_reference_images": "positive_int",
    "min_size_pixels": "positive_int",
    "size_multiple_of": "positive_int",
    "supports_audio": "bool",
    "supports_generate_audio": "bool",
    "source_limits": "str_to_int",
    "parameter_choices": "str_to_str_list",
    "duration_by_resolution": "str_to_int_list",
    "conditional_max_duration_seconds": "str_to_int",
    "exclusive_source_groups": "str_list_list",
    "requires_source": "str_list_list",
    "requires_companion": "str_to_str_list",
    "url_only_roles": "str_list",
}

_KINDS = ("image", "video")

#: 每个键在可视表单里归哪一组。**后端给语义分组,前端只翻译组名和键名** —— 分组知识要是也
#: 抄一份到前端,加一个键时漏掉不会有任何东西报错(见 routes/generation.py 的 schema 端点)。
_FIELD_GROUPS: dict[str, str] = {
    "parameter_keys": "params",
    "sizes": "choices",
    "resolutions": "choices",
    "aspect_ratios": "choices",
    "duration_seconds": "choices",
    "parameter_choices": "choices",
    "default_size": "defaults",
    "default_resolution": "defaults",
    "default_aspect_ratio": "defaults",
    "default_duration_seconds": "defaults",
    "default_quality": "defaults",
    "default_background": "defaults",
    "default_output_format": "defaults",
    "default_moderation": "defaults",
    "default_generate_audio": "defaults",
    "default_prompt_extend": "defaults",
    "max_num_images": "limits",
    "max_prompt_chars": "limits",
    "max_duration_seconds": "limits",
    "min_duration_seconds": "limits",
    "min_reference_images": "limits",
    "min_size_pixels": "limits",
    "size_multiple_of": "limits",
    "source_limits": "limits",
    "duration_special_values": "advanced",
    "duration_by_resolution": "advanced",
    "conditional_max_duration_seconds": "advanced",
    "exclusive_source_groups": "advanced",
    "requires_source": "advanced",
    "requires_companion": "advanced",
    "url_only_roles": "advanced",
    "boolean_parameters": "advanced",
    "supports_audio": "advanced",
    "supports_generate_audio": "advanced",
    "modes": "advanced",
}


#: 参数 → 装它可选值的那个描述符键。没有条目的参数,取值装在 `parameter_choices` 里按参数名
#: 分槽(quality / background / output_format / moderation 这几个枚举参数)。
#:
#: **这一份也归后端。** 界面此前在 TypeScript 里抄了一份 `{size: "sizes", ...}`,而"默认值"
#: 那一组还额外抄了一份"哪几个参数有默认值可设" —— 抄漏的后果真机上看得见:声明了
#: quality 的可选值之后,没有任何地方可以设 default_quality,而后端一直收这个键。
_CHOICES_KEY: dict[str, str] = {
    "size": "sizes",
    "resolution": "resolutions",
    "aspect_ratio": "aspect_ratios",
    "duration_seconds": "duration_seconds",
}

_DEFAULT_PREFIX = "default_"


def _defaults_for(key: str) -> str | None:
    """`default_quality` 是 `quality` 的默认值。名字本身就是这层关系,不另立一张表 ——
    另立一张表就有第二处要跟着改,而漏改不会有任何东西报错。

    这里不再额外判一次"它是不是 defaults 组":`default_` 开头**就是**归在那一组,而这条
    由测试直接钉住(test_别的组不冒充默认值),多一道判断只是给同一条规则加第二个说法。
    """
    return key[len(_DEFAULT_PREFIX) :] if key.startswith(_DEFAULT_PREFIX) else None


def _builtin_capabilities(kind: str) -> list[dict[str, Any]]:
    from app.domain.generation.catalog import BUILTIN_MODELS

    return [item.get("capabilities", {}) for item in BUILTIN_MODELS if item.get("kind") == kind]


def canonical_parameters(kind: str) -> list[str]:
    """这种生成能力下,目前真有适配器会发送的参数名 —— parameter_keys 的可选范围。

    **按 kind 分**:image 的可选里不该有 duration_seconds,声明一个这个 kind 没人会发的
    参数,只会让用户以为界面会多一个旋钮(见 validate_capabilities)。
    """
    return sorted(
        {parameter for capabilities in _builtin_capabilities(kind) for parameter in (capabilities.get("parameter_keys") or [])}
    )


def profile_form_schema(kind: str) -> dict[str, Any]:
    """可视表单的结构描述:有哪些字段、什么形状、归哪组、这个 kind 的参数与素材角色叫什么。

    **这是表单唯一的事实源。** 前端的语义化表单由它驱动,而不是把 34 个键的知识在
    TypeScript 里再抄一遍 —— 加字段时后端加一行,表单自动长出对应的控件。
    """
    from app.domain.generation.catalog import SOURCE_ROLE_LABELS

    capabilities = _builtin_capabilities(kind)
    enum_parameters = sorted(
        {name for caps in capabilities for name in (caps.get("parameter_choices") or {})}
    )
    roles = [
        role
        for role in SOURCE_ROLE_LABELS
        if any(role in (caps.get("parameter_keys") or []) for caps in capabilities)
    ]
    return {
        "parameters": canonical_parameters(kind),
        "enum_parameters": enum_parameters,
        "source_roles": roles,
        "choices_key": dict(_CHOICES_KEY),
        "fields": [
            {
                "key": key,
                "shape": shape,
                "group": _FIELD_GROUPS[key],
                "defaults_for": _defaults_for(key),
            }
            for key, shape in _KNOWN_KEYS.items()
        ],
    }


def _fail(message: str) -> None:
    raise CapabilityProfileError(message)


def _check(key: str, shape: str, value: Any) -> Any:
    def strs(v: Any, where: str) -> list[str]:
        if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
            _fail(f"{where} 要是一串非空文字")
        return [x.strip() for x in v]

    def positive(v: Any, where: str) -> int:
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            _fail(f"{where} 要是一个正整数")
        return v

    if shape == "str_list":
        return strs(value, key)
    if shape == "int_list":
        if not isinstance(value, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in value):
            _fail(f"{key} 要是一串整数")
        return list(value)
    if shape == "str":
        if not isinstance(value, str) or not value.strip():
            _fail(f"{key} 要是一段非空文字")
        return value.strip()
    if shape == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            _fail(f"{key} 要是一个整数")
        return value
    if shape == "positive_int":
        return positive(value, key)
    if shape == "bool":
        if not isinstance(value, bool):
            _fail(f"{key} 要是 true 或 false")
        return value
    if shape == "str_to_int":
        if not isinstance(value, dict):
            _fail(f"{key} 要是一组「名字 → 正整数」")
        return {str(k): positive(v, f"{key}.{k}") for k, v in value.items()}
    if shape == "str_to_str_list":
        if not isinstance(value, dict):
            _fail(f"{key} 要是一组「名字 → 可选值」")
        return {str(k): strs(v, f"{key}.{k}") for k, v in value.items()}
    if shape == "str_to_int_list":
        if not isinstance(value, dict):
            _fail(f"{key} 要是一组「名字 → 一串整数」")
        for k, v in value.items():
            if not isinstance(v, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in v):
                _fail(f"{key}.{k} 要是一串整数")
        return {str(k): list(v) for k, v in value.items()}
    if shape == "str_list_list":
        if not isinstance(value, list):
            _fail(f"{key} 要是若干组名字")
        return [strs(group, key) for group in value]
    _fail(f"{key} 的形状没人认得")
    return None


def validate_capabilities(raw: Any, kind: str) -> dict[str, Any]:
    """把用户填的东西校成一份描述符。拦不住的只有"这个端点真的支持吗"。"""
    if kind not in _KINDS:
        _fail(f"参数组只能是 {' 或 '.join(_KINDS)}")
    if not isinstance(raw, dict):
        _fail("参数组的内容要是一组键值")
    unknown = [k for k in raw if k not in _KNOWN_KEYS]
    if unknown:
        #: 点名说是哪个键。"格式不对"这种话对着三十几个键的表单毫无用处。
        _fail("这几个字段我们不认得:" + "、".join(sorted(unknown)))
    clean = {key: _check(key, _KNOWN_KEYS[key], value) for key, value in raw.items() if value is not None}
    unknown_parameters = sorted(set(clean.get("parameter_keys") or []) - set(canonical_parameters(kind)))
    if unknown_parameters:
        _fail(
            "这些参数当前没有生成适配器会发送，不能只在界面里声明:"
            + "、".join(unknown_parameters)
        )
    #: 一份什么参数都不声明的档案 = 兜底,指它和不指是一回事 —— 让人以为设过了,其实没有。
    if not clean.get("parameter_keys"):
        _fail("至少要声明一个参数(parameter_keys),否则指向它和不指是一样的")
    #: 默认值必须在自己那份清单里 —— 界面会拿它当初值,不在清单里就是一个选不回来的值。
    for default_key, list_key in (
        ("default_size", "sizes"),
        ("default_resolution", "resolutions"),
        ("default_aspect_ratio", "aspect_ratios"),
    ):
        default = clean.get(default_key)
        if default is not None and default not in (clean.get(list_key) or []):
            _fail(f"{default_key} 的值不在 {list_key} 里面")
    return clean


def custom_profiles_for(db: Session, profile_id: str, kind: str) -> list[GenerationCapabilityProfile]:
    rows = db.scalars(
        select(GenerationCapabilityProfile)
        .where(GenerationCapabilityProfile.provider_profile_id == profile_id)
        .where(GenerationCapabilityProfile.kind == kind)
    ).all()
    return sorted(rows, key=lambda row: row.name)


def custom_capabilities_map(db: Session, profile_id: str, kind: str) -> dict[str, dict[str, Any]]:
    """`profile:<id>` 能解析到的那些 —— 交给 resolve_capability_ref 当"额外名册"。

    **按连接取**:一份自定义参数组只在它所属的那条连接里有意义。别的连接指过来的 id 解析不到,
    于是落回兜底并在界面上显示"还没认出来" —— 比悄悄套用另一条连接的断言要好。
    """
    return {row.id: dict(row.capabilities or {}) for row in custom_profiles_for(db, profile_id, kind)}
