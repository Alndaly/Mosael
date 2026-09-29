from __future__ import annotations

from typing import Any

#: 描述符的数据住在 descriptors/ 下(按介质 / 厂商分文件);这里重新导出每一个名字 ——
#: 调用方照旧从 catalog 取。**导入而不是复制**:下面的档案名册按对象身份(id())反查。
from app.domain.generation.descriptors.shared import (
    SOURCE_ROLE_LABELS,  # noqa: F401
    SOURCE_ROLE_HELP,  # noqa: F401
    KEYFRAME_GROUP,  # noqa: F401
    REFERENCE_GROUP,  # noqa: F401
    SOURCE_GROUPS,  # noqa: F401
    SOURCE_GROUP_DROPS,  # noqa: F401
    REFERENCE_SCENE_LIMITS,  # noqa: F401
)
from app.domain.generation.descriptors.image import (
    OPENAI_IMAGE_CAPABILITIES,
    QWEN_TEXT_IMAGE_CAPABILITIES,
    QWEN_PRO_IMAGE_CAPABILITIES,
    QWEN_EDIT_IMAGE_CAPABILITIES,
    SEEDREAM_4_IMAGE_CAPABILITIES,
    SEEDREAM_3_IMAGE_CAPABILITIES,
    EVOLINK_IMAGE_SIZES,  # noqa: F401
    EVOLINK_IMAGE_CAPABILITIES,
    EVOLINK_IMAGE_EDIT_CAPABILITIES,
)
from app.domain.generation.descriptors.avatar import (
    WAN_22_S2V_CAPABILITIES,
    VOLCANO_OMNIHUMAN_15_CAPABILITIES,
    HEYGEN_AVATAR_CAPABILITIES,
    HEYGEN_LIPSYNC_CAPABILITIES,
    HEDRA_CHARACTER_3_CAPABILITIES,
    VIDEORETALK_CAPABILITIES,
    KLING_AVATAR_CAPABILITIES,
    KLING_LIPSYNC_CAPABILITIES,
)
from app.domain.generation.descriptors.video import (
    WAN_VIDEO_CAPABILITIES,
    WAN_27_T2V_CAPABILITIES,
    WAN_27_I2V_CAPABILITIES,
    WAN_27_R2V_CAPABILITIES,
    KLING_LEGACY_VIDEO_CAPABILITIES,
    KLING_V3_VIDEO_CAPABILITIES,
    KLING_V3_OMNI_VIDEO_CAPABILITIES,
    WAN_VIDEO_EDIT_CAPABILITIES,
    ARK_VIDEO_RATIOS,  # noqa: F401
    SEEDANCE_2_VIDEO_CAPABILITIES,
    SEEDANCE_2_SMALL_VIDEO_CAPABILITIES,
    SEEDANCE_1_VIDEO_CAPABILITIES,
    SEEDANCE_15_VIDEO_CAPABILITIES,
    MINIMAX_VIDEO_CAPABILITIES,
    GOOGLE_VEO_VIDEO_CAPABILITIES,
)
from app.domain.generation.descriptors.evolink_video import (
    EVOLINK_VIDEO_T2V_CAPABILITIES,
    EVOLINK_VIDEO_I2V_CAPABILITIES,
    EVOLINK_SEEDANCE_15_CAPABILITIES,
    EVOLINK_SEEDANCE_20_BASE,  # noqa: F401
    EVOLINK_SEEDANCE_20_T2V_CAPABILITIES,
    EVOLINK_SEEDANCE_20_I2V_CAPABILITIES,
    EVOLINK_SEEDANCE_20_R2V_CAPABILITIES,
    EVOLINK_SEEDANCE_20_FAST_T2V_CAPABILITIES,
    EVOLINK_SEEDANCE_20_FAST_I2V_CAPABILITIES,
    EVOLINK_SEEDANCE_20_FAST_R2V_CAPABILITIES,
    EVOLINK_SEEDANCE_25_BASE,  # noqa: F401
    EVOLINK_SEEDANCE_25_DURATION,  # noqa: F401
    EVOLINK_SEEDANCE_25_RATIOS,  # noqa: F401
    EVOLINK_SEEDANCE_25_T2V_CAPABILITIES,
    EVOLINK_SEEDANCE_25_I2V_CAPABILITIES,
    EVOLINK_SEEDANCE_25_R2V_CAPABILITIES,
    EVOLINK_SEEDANCE_25_VIDEO_EDIT_CAPABILITIES,
    EVOLINK_SEEDANCE_25_VIDEO_EXTEND_CAPABILITIES,
    EVOLINK_VEO_31_PRO_CAPABILITIES,
)
from app.domain.generation.descriptors.audio import (
    VOCAL_GENDER_SCHEMA,  # noqa: F401
    EVOLINK_SUNO_CAPABILITIES,
    EVOLINK_SUNO_V4_CAPABILITIES,
    EVOLINK_SUNO_V55_CAPABILITIES,
    KLING_TEXT_TO_AUDIO_CAPABILITIES,
    KLING_VIDEO_TO_AUDIO_CAPABILITIES,
    VOLCANO_SONG_CAPABILITIES,
    VOLCANO_BGM_CAPABILITIES,
    GOOGLE_LYRIA_CAPABILITIES,
    ALIBABA_FUN_MUSIC_CAPABILITIES,
    ALIBABA_FUN_MUSIC_PREVIEW_CAPABILITIES,
    ALIBABA_AUDIOGEN_CAPABILITIES,
)
from app.domain.generation.descriptors.builtin import (
    AUDIO_BUILTIN_MODELS,  # noqa: F401
    EVOLINK_BUILTIN_MODELS,  # noqa: F401
    BUILTIN_MODELS,
)

#: **生成的种类**:图像、视频、音频。全仓只有这一份 —— 解析、设置页、参数组表单、插件目录、
#: 画板的「生成」产出者都从这里读。此前 `("image", "video")` 在七个文件里各抄一份,于是
#: 加一种介质要记得改七处,漏掉的那一处不会报错,只会让那一种在某个入口上悄悄不见。
#:
#: 音频(音乐、BGM、歌曲、音效、给视频配声)是**生成**的一种,和语音合成(念一段字,
#: voices/speak 那条路)不是一回事 —— 见 ADR 0022。
GENERATION_KINDS = ("image", "video", "audio")

#: 一个模型对**提示词**的要求 —— 描述符的 `prompt` 格子,三种取值,没写就是 `required`:
#:
#: - `required`:要写一段描述。会唱歌词的模型(参数里有 `lyrics`)只给歌词也行 —— 歌词本身就是
#:   「写一首什么样的歌」;
#: - `optional`:可以不写。给视频配声、按素材出结果的模型,写了是锦上添花;
#: - `none`:这个模型**不收**提示词(ComfyUI 里的放大、抠图这类工作流)。写了也不会生效,所以
#:   提交时带着提示词是错 —— 当场说,而不是让人以为那句话起了作用。
#:
#: **一个格子、一套规矩**(operations.validate_text_inputs),不按种类分支:此前图像 / 视频「必须有
#: 提示词」写死在契约层,音频另有「必须写描述」「可以不写描述」两个布尔,于是插件里一张
#: 不需要提示词的放大工作流,也逼着人先敲一句没用的话。三个界面(AI 工作台、画板、工作流节点)
#: 和智能体都照这一格摆提示词框、判能不能提交。
PROMPT_MODES = ("required", "optional", "none")


def prompt_mode(capabilities: dict[str, Any] | None) -> str:
    """这个描述符对提示词的要求。没写(或写了认不出的值)就是 `required` —— 保守的那一边。"""
    value = (capabilities or {}).get("prompt")
    return value if value in PROMPT_MODES else "required"


#: **能力档案的名册。** descriptors/ 下那几十个常量本来就是"档案" —— 9 份被 28 行共用,只是没有名字,
#: 于是"另一条通道也有这个模型"每出现一次就只能再抄一行(openai / openai-compatible 下的
#: gpt-image-2 就是抄出来的一对)。给它们一个稳定的 id 之后,这件事有了第二种说法:
#: 用户在自己那行模型上指一份档案,而不是等我们补一行。
#:
#: id 由常量名推出来(`OPENAI_IMAGE_CAPABILITIES` → `openai-image`),但**写成显式的一行**:
#: 它会被存进用户的数据里,不能因为有人重命名了常量就悄悄变。改名要在这里同步改,并且
#: 想清楚存量数据怎么办。
CAPABILITY_PROFILES: dict[str, dict[str, Any]] = {
    "openai-image": OPENAI_IMAGE_CAPABILITIES,
    "qwen-text-image": QWEN_TEXT_IMAGE_CAPABILITIES,
    "qwen-pro-image": QWEN_PRO_IMAGE_CAPABILITIES,
    "qwen-edit-image": QWEN_EDIT_IMAGE_CAPABILITIES,
    "seedream-4-image": SEEDREAM_4_IMAGE_CAPABILITIES,
    "seedream-3-image": SEEDREAM_3_IMAGE_CAPABILITIES,
    "wan-video": WAN_VIDEO_CAPABILITIES,
    "wan-27-t2v": WAN_27_T2V_CAPABILITIES,
    "wan-27-i2v": WAN_27_I2V_CAPABILITIES,
    "wan-22-s2v": WAN_22_S2V_CAPABILITIES,
    "videoretalk": VIDEORETALK_CAPABILITIES,
    "volcano-omnihuman-15": VOLCANO_OMNIHUMAN_15_CAPABILITIES,
    "heygen-avatar-iv": HEYGEN_AVATAR_CAPABILITIES,
    "heygen-lipsync": HEYGEN_LIPSYNC_CAPABILITIES,
    "hedra-character-3": HEDRA_CHARACTER_3_CAPABILITIES,
    "kling-avatar": KLING_AVATAR_CAPABILITIES,
    "kling-lipsync": KLING_LIPSYNC_CAPABILITIES,
    "wan-27-r2v": WAN_27_R2V_CAPABILITIES,
    "kling-legacy-video": KLING_LEGACY_VIDEO_CAPABILITIES,
    "kling-v3-video": KLING_V3_VIDEO_CAPABILITIES,
    "kling-v3-omni-video": KLING_V3_OMNI_VIDEO_CAPABILITIES,
    "wan-video-edit": WAN_VIDEO_EDIT_CAPABILITIES,
    "seedance-2-video": SEEDANCE_2_VIDEO_CAPABILITIES,
    "seedance-2-small-video": SEEDANCE_2_SMALL_VIDEO_CAPABILITIES,
    "seedance-1-video": SEEDANCE_1_VIDEO_CAPABILITIES,
    "seedance-15-video": SEEDANCE_15_VIDEO_CAPABILITIES,
    "minimax-video": MINIMAX_VIDEO_CAPABILITIES,
    "evolink-video-t2v": EVOLINK_VIDEO_T2V_CAPABILITIES,
    "evolink-video-i2v": EVOLINK_VIDEO_I2V_CAPABILITIES,
    "evolink-seedance-15": EVOLINK_SEEDANCE_15_CAPABILITIES,
    "evolink-seedance-20-t2v": EVOLINK_SEEDANCE_20_T2V_CAPABILITIES,
    "evolink-seedance-20-i2v": EVOLINK_SEEDANCE_20_I2V_CAPABILITIES,
    "evolink-seedance-20-r2v": EVOLINK_SEEDANCE_20_R2V_CAPABILITIES,
    "evolink-seedance-20-fast-t2v": EVOLINK_SEEDANCE_20_FAST_T2V_CAPABILITIES,
    "evolink-seedance-20-fast-i2v": EVOLINK_SEEDANCE_20_FAST_I2V_CAPABILITIES,
    "evolink-seedance-20-fast-r2v": EVOLINK_SEEDANCE_20_FAST_R2V_CAPABILITIES,
    "evolink-seedance-25-t2v": EVOLINK_SEEDANCE_25_T2V_CAPABILITIES,
    "evolink-seedance-25-i2v": EVOLINK_SEEDANCE_25_I2V_CAPABILITIES,
    "evolink-seedance-25-r2v": EVOLINK_SEEDANCE_25_R2V_CAPABILITIES,
    "evolink-seedance-25-video-edit": EVOLINK_SEEDANCE_25_VIDEO_EDIT_CAPABILITIES,
    "evolink-seedance-25-video-extend": EVOLINK_SEEDANCE_25_VIDEO_EXTEND_CAPABILITIES,
    "evolink-image": EVOLINK_IMAGE_CAPABILITIES,
    "evolink-image-edit": EVOLINK_IMAGE_EDIT_CAPABILITIES,
    "evolink-veo-31-pro": EVOLINK_VEO_31_PRO_CAPABILITIES,
    "google-veo-video": GOOGLE_VEO_VIDEO_CAPABILITIES,
    "evolink-suno": EVOLINK_SUNO_CAPABILITIES,
    "evolink-suno-v4": EVOLINK_SUNO_V4_CAPABILITIES,
    "evolink-suno-v55": EVOLINK_SUNO_V55_CAPABILITIES,
    "kling-text-to-audio": KLING_TEXT_TO_AUDIO_CAPABILITIES,
    "kling-video-to-audio": KLING_VIDEO_TO_AUDIO_CAPABILITIES,
    "volcano-song": VOLCANO_SONG_CAPABILITIES,
    "volcano-bgm": VOLCANO_BGM_CAPABILITIES,
    "google-lyria": GOOGLE_LYRIA_CAPABILITIES,
    "alibaba-fun-music": ALIBABA_FUN_MUSIC_CAPABILITIES,
    "alibaba-fun-music-preview": ALIBABA_FUN_MUSIC_PREVIEW_CAPABILITIES,
    "alibaba-audiogen": ALIBABA_AUDIOGEN_CAPABILITIES,
}

#: 按对象身份反查档案 id。**不比较内容** —— 两份内容恰好相同的档案仍是两份(它们会各自演化)。
_PROFILE_ID_BY_IDENTITY: dict[int, str] = {id(caps): name for name, caps in CAPABILITY_PROFILES.items()}


def profile_id_for(vendor: str, model: str, kind: str) -> str | None:
    """这条内置记录用的是哪份档案。查不到这个模型时回 None。"""
    for item in BUILTIN_MODELS:
        if item["provider"] == vendor and item["model"] == model and item["kind"] == kind:
            return _PROFILE_ID_BY_IDENTITY.get(id(item["capabilities"]))
    return None


#: 某个 vendor 在某种生成能力下的**兜底**描述符。目录里没登记的模型(私有部署、别名、
#: 用户手填的)照样要能出现在选择器里并给出一组可用参数 —— 缺描述符不该等于"不能用"。
_FALLBACK_BY_KIND: dict[str, dict[str, Any]] = {
    "image": {
        "modes": ["text-to-image"],
        "parameter_keys": [],
    },
    "video": {
        "modes": ["text-to-video"],
        "parameter_keys": [],
    },
    "audio": {
        "modes": ["text-to-audio"],
        "parameter_keys": [],
    },
}


def resolve_capability_ref(
    ref: str | None, kind: str, *, custom: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any] | None:
    """用户在自己那行模型上写下的「生成参数按什么来」。认不出就回 None(**不猜**)。

    两种写法:

      `model:<provider>/<model>`  「它和 X 一样」。存的是指针不是快照 —— 以后我们把 X 的描述符
                                  改宽了,指着它的那些行**跟着变**。用户写 `gpt-image-2-client`
                                  时想说的正是这个:它就是 gpt-image-2,别的我不管。
      `profile:<id>`              目录里没有对应模型时,直接指一份能力档案(见 CAPABILITY_PROFILES)。

    指向的东西不存在时回 None 而不是抛:一个指向已被删掉的模型的旧值,不该让整个模型列表 500。
    界面那边会因此显示成"还没认出来",用户重新指一次即可。
    """
    text = (ref or "").strip()
    if not text:
        return None
    prefix, _, rest = text.partition(":")
    if prefix == "profile":
        name = rest.strip()
        #: 自定义的排在前面:同名时用户的那份说了算 —— 内置 id 是 `openai-image` 这种词,
        #: 自定义的是 32 位十六进制,实际撞不上,但顺序仍要写明白。
        found = (custom or {}).get(name) or CAPABILITY_PROFILES.get(name)
        return dict(found) if found is not None else None
    if prefix == "model":
        target_vendor, _, target_model = rest.partition("/")
        #: 跨 kind 不认:同一个 id 的图片档案套到视频上,参数是另一套。
        return known_capabilities_for(target_vendor.strip(), target_model.strip(), kind)
    return None


def capabilities_for(
    vendor: str,
    model: str,
    kind: str,
    *,
    ref: str | None = None,
    custom: dict[str, dict[str, Any]] | None = None,
    declared: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """某个模型在某种生成能力下的参数描述符(尺寸/时长/支持哪些参数)。

    **这是关于供应商 API 的静态知识,不是用户配置** —— 所以它是一张查表,不再是数据库里的行。
    以前每条描述符都在 `generation_models` 里占一行,于是"有哪些模型可选"这件事有了第二个
    答案:设置页看 provider_models,生成页看 generation_models,两边永远对不齐(有的模型只在
    后者里,设置页加的进不了前者)。

    只精确匹配 (provider, model, kind)。查不到时**不猜这个模型** —— 同一个供应商下,同系列
    不同型号的时长、素材角色和枚举值经常不同,继承目录第一项会让界面主动发送用户没有选择、
    目标模型也未必支持的参数。

    但"不猜模型"不等于"什么都不知道"。请求是**我们自己构造的**,所以 Adapter 说得出它能发
    哪几项标量参数。那个面与模型名无关时(`surface_depends_on_model = False`),兜底就用它 ——
    只给**键**,不声称任何取值范围。这不是推测:代码就在那儿,发哪几项一目了然。
    此前这里返回的是空集,于是一个中转上的模型看起来像"它就是没有参数",而那段代码早就知道
    自己准备发哪七项(见 ADR 0015)。
    """
    chosen = resolve_capability_ref(ref, kind, custom=custom)
    if chosen is not None:
        return chosen
    # **连接自己说的**(插件生成供应商在目录里声明的,见 ADR 0020)排在内置目录前面:
    # 那是 Adapter —— 这里就是插件 —— 对它自己要发的请求的描述,正是 ADR 0015 的「参数面由
    # Adapter 说」。内置目录里本来也没有它们。
    if declared:
        return dict(declared)
    exact = known_capabilities_for(vendor, model, kind)
    if exact is not None:
        return exact
    return fallback_capabilities(vendor, kind)


def adapter_parameter_surface(vendor: str, kind: str) -> tuple[str, ...]:
    """这条通道能发出去的标量参数;依赖模型名的一律回空(保守)。"""
    from app.ai.providers import get_generation_adapter

    adapter = get_generation_adapter(vendor, kind)
    if adapter is None or adapter.surface_depends_on_model:
        return ()
    return tuple(adapter.parameter_surface)


def fallback_capabilities(vendor: str, kind: str) -> dict[str, Any]:
    """目录不认识这个模型时给什么。

    **键来自 Adapter,取值范围一个都不声称。** 请求是我们自己构造的,发哪几项是知道的;
    这个模型收哪些**取值**才是未知的。界面据此渲染成自由输入 —— 摆出来,但在用户填之前
    不带任何值(见 ADR 0015 与 lib/generationCapabilities 的 UNDECLARED / DURATION_UNSET)。

    **这一步曾经放不出来。** 界面那一层原本有自己的造值逻辑:一个参数键只要出现、清单缺席,
    就凭空造出 size→["1024x1024"]、resolution→["720p"]、aspect_ratio→["16:9"]、duration→5
    并取第一项提交。于是"知道能发哪几项"会变成"声称这个模型是 720p / 16:9 / 5 秒",而用户
    一项都没选过 —— 那时这里的空是**承重**的,是唯一拦住它的闸。
    `tests/test_generation_capability_contract.py` 的 `不伪造第一款型号的参数` 抓的正是这个。
    界面改成"不知道就空着"之后,这道闸才拆得掉。
    """
    base = dict(_FALLBACK_BY_KIND.get(kind, {}))
    surface = adapter_parameter_surface(vendor, kind)
    if surface:
        base["parameter_keys"] = list(surface)
    return base


def capabilities_are_known(
    vendor: str,
    model: str,
    kind: str,
    *,
    ref: str | None = None,
    custom: dict[str, dict[str, Any]] | None = None,
    declared: dict[str, Any] | None = None,
) -> bool:
    """这个模型的参数是**认出来的**,还是落到了兜底。

    界面要分得开这两种零:「这个模型确实没有可调参数」和「我们不认识这个模型」。合成一个的
    后果今天见过 —— 生成节点的「参数」按钮对着一堆其实有参数的模型悄悄消失了。
    """
    return (
        resolve_capability_ref(ref, kind, custom=custom) is not None
        or bool(declared)
        or known_capabilities_for(vendor, model, kind) is not None
    )


def known_capabilities_for(vendor: str, model: str, kind: str) -> dict[str, Any] | None:
    """同上,但**查不到就是 None**,不给兜底。

    兜底那份是给界面用的 —— 总得渲染出点什么。校验不能用它:落到兜底的意思是「我们不认识
    这个模型」(用户自建的、中转上的别名),拿那份窄名单去拦,会挡住本来能用的参数。
    两种需求共用一个返回值时,分不出「它只支持这些」和「我们不知道它支持什么」。
    """
    for item in BUILTIN_MODELS:
        if item["provider"] == vendor and item["model"] == model and item["kind"] == kind:
            return dict(item["capabilities"])
    return None


def builtin_models_for(vendor: str, kind: str) -> list[str]:
    """该 vendor 在该能力下的内置模型名 —— 用户没在设置里加过任何模型时的候选。"""
    return [item["model"] for item in BUILTIN_MODELS if item["provider"] == vendor and item["kind"] == kind]

#: 「能用来生成的 (连接 × 模型) 列表」是 db 感知的,住在 resolution.py 那个集成缝上。
#: 这里保持纯静态目录 —— 叶模块向上伸手会成环(import 分层测试钉着)。
