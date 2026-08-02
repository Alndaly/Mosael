"""分平台图像提示词优化。

不同图像平台的提示词范式差异很大,同一句原始想法在不同平台该写成不同样子:

- GPT-Image / DALL-E(openai):自然语言整句描述,像向人描述一幅画;不吃标签堆砌与权重,也不用 negative。
- Qwen-Image / 通义(alibaba):自然语言描述,中文表现好;支持 negative prompt。
- 豆包 Seedream(bytedance,image):自然语言 + 电影感描述,中文友好。
- ComfyUI / Stable Diffusion(comfyui):逗号分隔的英文标签 + 质量词 + 权重 (tag:1.2),且强依赖 negative prompt。

本模块给每个平台一套「风格指南」,连同用户原文一起交给聊天 LLM 重写,返回
{prompt, negative_prompt, notes}。前端「优化」按钮与智能助手技能共用这同一入口
(POST /api/generation/optimize-prompt),所以两处产出的优化口径完全一致。
"""

from __future__ import annotations

import json
from dataclasses import dataclass


from app.domain.ai_chat import AiChatError, ChatTarget, chat, target_for
from sqlalchemy.orm import Session

from app.domain import provider_models
from app.domain.providers import require_profile

_LLM_TIMEOUT_SECONDS = 60.0


class PromptOptimizeError(RuntimeError):
    """提示词优化失败(供应商缺失、LLM 调用失败、返回非法 JSON 等)。"""


@dataclass(frozen=True)
class PlatformGuide:
    """一个图像平台的提示词习惯,喂进优化 LLM 的系统提示。"""

    label: str  # 人类可读平台名
    style: str  # 该平台提示词写法要点
    prompt_lang: str  # 主提示词语言倾向:"en"(拉丁标签/英文更稳)或 "zh-ok"(中文友好)
    wants_negative: bool  # 该平台是否吃 negative prompt
    is_edit: bool = False  # 编辑类模型:提示词是「对已有图的改动指令」,而非从零描述


_SD_STYLE = (
    "逗号分隔的英文标签/短语,不要整句自然语言。开头放质量词(masterpiece, best quality, "
    "highly detailed, 8k),再依次给:主体标签、外观/服饰、动作、场景、光照(如 cinematic lighting, "
    "rim light)、镜头(如 close-up, wide shot)、风格/媒介(如 photorealistic, oil painting)。"
    "重要元素可加权重,语法 (tag:1.2),权重克制在 0.8–1.4。"
)
_SD_NEGATIVE_HINT = (
    "negative_prompt 给该平台惯用的排除词:lowres, worst quality, low quality, blurry, jpeg artifacts, "
    "bad anatomy, extra digits, deformed, watermark, text, signature —— 再结合本图该避免的内容。"
)

_NATURAL_STYLE = (
    "自然语言整句描述,像向人描述一幅画。有序涵盖:主体与其动作/神态、场景与背景、光线、"
    "构图/视角、风格/媒介、色调与氛围。不要用逗号堆砌标签、不要权重语法。1–3 句、信息密度高即可。"
)

_GUIDES: dict[str, PlatformGuide] = {
    "openai": PlatformGuide(
        label="GPT-Image / DALL·E",
        style=_NATURAL_STYLE + " GPT-Image 不接受 negative,把「要避免的」融进正向描述或直接省略。",
        prompt_lang="en",
        wants_negative=False,
    ),
    "openai-compatible": PlatformGuide(
        label="GPT-Image(兼容)",
        style=_NATURAL_STYLE + " 不接受 negative,把「要避免的」融进正向描述或省略。",
        prompt_lang="en",
        wants_negative=False,
    ),
    "alibaba": PlatformGuide(
        label="通义 Qwen-Image",
        style=_NATURAL_STYLE + " 中文表现好,可直接用中文;细节越具体越稳。",
        prompt_lang="zh-ok",
        wants_negative=True,
    ),
    "bytedance": PlatformGuide(
        label="豆包 Seedream",
        style=_NATURAL_STYLE + " 偏电影感,中文友好;强调质感、光影、镜头语言。",
        prompt_lang="zh-ok",
        wants_negative=False,
    ),
    "comfyui": PlatformGuide(
        label="ComfyUI / Stable Diffusion",
        style=_SD_STYLE + " " + _SD_NEGATIVE_HINT,
        prompt_lang="en",
        wants_negative=True,
    ),
}

_DEFAULT_GUIDE = PlatformGuide(
    label="通用",
    style=_NATURAL_STYLE,
    prompt_lang="zh-ok",
    wants_negative=False,
)


def guide_for(provider: str, model: str) -> PlatformGuide:
    """按 provider(必要时 model)选平台指南。编辑类模型(qwen-image-edit)走「编辑指令」范式。"""
    if "edit" in model.lower():
        base = _GUIDES.get(provider, _DEFAULT_GUIDE)
        return PlatformGuide(
            label=base.label + "(编辑)",
            style=(
                "这是图像「编辑」模型:提示词是对已有图片的改动指令,而非从零描述整幅画。"
                "只写要改什么(增/删/替换/调整某元素、改风格/光线/背景),保留未提及的部分,"
                "指令清晰、单一意图优先。"
            ),
            prompt_lang=base.prompt_lang,
            wants_negative=False,
            is_edit=True,
        )
    return _GUIDES.get(provider, _DEFAULT_GUIDE)


def _build_system_prompt(guide: PlatformGuide, ui_language: str) -> str:
    lang_rule = (
        "主提示词用英文(该平台英文更稳)。"
        if guide.prompt_lang == "en"
        else "主提示词可用中文(该平台中文友好),保持与用户原文一致的语言。"
    )
    neg_rule = (
        "同时给出 negative_prompt(不希望出现的内容),遵循该平台习惯。"
        if guide.wants_negative
        else "该平台不使用 negative_prompt,negative_prompt 返回空字符串。"
    )
    notes_lang = "英文" if ui_language.startswith("en") else "中文"
    return (
        f"你是资深的 AI 图像生成提示词专家。目标平台:{guide.label}。\n"
        f"该平台的提示词习惯:{guide.style}\n"
        f"{lang_rule}\n{neg_rule}\n"
        "把用户给的原始想法/提示词改写成一条贴合该平台习惯的高质量提示词:"
        "保留其核心意图与关键要素,补足有益细节(光线/构图/风格/画质),"
        "不要臆造与原意冲突的元素,不要输出解释性套话。\n"
        f'只返回 JSON,不要任何多余文字:{{"prompt": "优化后的主提示词", '
        f'"negative_prompt": "负向提示词(无则空串)", "notes": "一句{notes_lang}说明你做了什么优化"}}。'
    )


def _chat_json(target: ChatTarget, system: str, user: str) -> dict:
    """一次对话调用,强制 JSON 输出,解析为 dict。"""
    try:
        text = chat(
            target,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.7,
            timeout=_LLM_TIMEOUT_SECONDS,
            json_object=True,
            label="提示词优化",
        ).strip()
    except AiChatError as exc:
        raise PromptOptimizeError(str(exc)) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PromptOptimizeError("提示词优化返回的不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise PromptOptimizeError("提示词优化返回的 JSON 不是对象")
    return data


def optimize_image_prompt(
    db: Session,
    *,
    raw_prompt: str,
    provider: str,
    model: str,
    profile_id: str | None = None,
    ui_language: str = "zh",
) -> dict:
    """把 raw_prompt 按 provider/model 平台习惯优化,返回 {prompt, negative_prompt, notes, platform}。

    重写用的是「聊天 LLM」(供应商配置里默认启用的那个,与助手/工作流同一个),而不是图像模型本身;
    provider/model 只用来选平台指南。profile_id 可指定 LLM 供应商配置,缺省用默认启用的。
    """
    if not raw_prompt.strip():
        raise PromptOptimizeError("提示词为空,无法优化")
    guide = guide_for(provider, model)
    # 用「对话」默认 LLM 重写(与助手同一个),不是图像模型本身:图像 provider 的 default_model 是
    # 图像模型、且可能没有 chat 端点 / 密钥(空密钥会拼出非法的 'Bearer ' 头)。缺省时回退到显式
    # 传入的 profile / 首个启用的供应商。
    default = provider_models.resolve_default(db, "chat")
    chat_profile = default.profile if default is not None else None
    chat_model = default.model_id if default is not None else ""
    if chat_profile is None:
        chat_profile = require_profile(db, profile_id, error=PromptOptimizeError)
    if not chat_model:
        chat_model = provider_models.model_id_for(db, chat_profile, "chat")
    if not chat_model:
        raise PromptOptimizeError("未配置对话模型,请在设置里为「对话」选择供应商与模型")
    try:
        target = target_for(db, chat_profile, model=chat_model)
    except AiChatError as exc:
        raise PromptOptimizeError(str(exc)) from exc
    data = _chat_json(target, _build_system_prompt(guide, ui_language), raw_prompt.strip())
    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        raise PromptOptimizeError("优化结果为空")
    negative = str(data.get("negative_prompt") or "").strip() if guide.wants_negative else ""
    return {
        "prompt": prompt,
        "negative_prompt": negative,
        "notes": str(data.get("notes") or "").strip(),
        "platform": guide.label,
    }


__all__ = ["PromptOptimizeError", "PlatformGuide", "guide_for", "optimize_image_prompt"]
