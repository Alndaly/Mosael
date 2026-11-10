"""内置模板**挑模型**的那几步:按用户的默认设置、按描述符能不能带参考图 / 首帧,选出每一步用哪个模型,
并把它的能力摊成出图 / 出片计划(ImagePlan / VideoPlan)。

模板入口(templates.py)和整片生成那张大图都要用,所以单独一份,放在两者下面。

调用方直接从这个模块取(一个名字只有一个来源,见 tests/test_imports_come_from_where_names_live)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import DRIVING_AUDIO, FIRST_CLIP, FIRST_FRAME, LAST_FRAME, REFERENCE_IMAGE, REFERENCE_VIDEO
from app.db.models import ProviderModel
from app.domain.generation_catalog import known_capabilities_for
from app.domain.generation.aspect import size_for_aspect
from app.domain.generation.resolution import resolve_row
from app.domain.providers.defaults import get_row
from app.domain.providers.models import effective_capabilities
from app.domain.providers import models as provider_models


@dataclass(frozen=True)
class ModelChoice:
    profile_id: str = ""
    provider: str = ""
    model: str = ""


#: 续写的尾巴留多长。H3 按 17k+5 帧取片段,22 帧正好是 24fps 下的 0.92 秒:写成 1 秒的话多出来的两帧被裁掉。
CONTINUATION_TAIL_SECONDS = 0.92
#: 工作流按段号存取潜空间时的两个参数(节点 50 读上一段,节点 52 存这一段):有它们的就是潜空间续写。
#: 存的是第二遍的高清潜空间,两遍都接它,重叠帧和上一段成片一模一样;这两个数是工作流里写死的 243 帧和 39 帧上文。
#: 第 0–38 帧是上文,时间线从第 39 帧接。
LATENT_LOAD_SCENE = "50.scene_number"
LATENT_SAVE_SCENE = "52.scene_number"
LATENT_SEGMENT_SECONDS = 10.125
LATENT_CONTEXT_SECONDS = 39 / 24
#: 这一段生成多少帧(节点 7 的 length):工作流里写死的是一整段 243 帧,最后一段按它真要的长度改小(见 chain_plan 的 `fps`)。
#: H3 按 17k+5 帧取,填进去的帧数由节点自己向上对齐;最短不少于它训练过的 124 帧(约 5.2 秒)。
LATENT_FPS = 24
LATENT_LENGTH = "7.length"
LATENT_SHORTEST_SECONDS = 124 / 24
#: 模型要尾巴至少几秒时多留这一点:按帧截,截出来总比要的短一丝,卡在下限上供应商未必认。
TAIL_MARGIN_SECONDS = 0.1


@dataclass(frozen=True)
class VideoPlan:
    clip_seconds: int = 5
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    width: int = 1920
    height: int = 1080
    parameters: dict[str, Any] | None = None
    #: 按像素尺寸定画幅的模型(万相 2.2 / 2.5 / 2.6 收 `size`、不收 `aspect_ratio`):每种画幅用尺寸表里哪一档。
    #: 有它时参数里的 size 是 `{{input.video_size}}`,跟着画幅走 —— 此前写死默认的 832*480,改成竖屏照样出横屏。
    sizes: dict[str, str] | None = None
    #: 这个视频模型收哪几种参考(见 _video_plan)。决定分镜里每一镜**能选**哪条路:
    #: 首帧(+尾帧)锁构图,或者参考图/参考视频锁人物与运镜。
    keyframes: bool = True
    last_frame: bool = False
    #: 收待续写的片段(`first_clip`):接着一段视频往下拍,而不只是从一帧动起来。
    extends: bool = False
    #: 按段号接潜空间(见 LATENT_LOAD_SCENE),不走 `first_clip`。
    latent_chain: bool = False
    #: 交给下一段的尾巴至少几秒(描述符的 `source_duration_seconds`)。没声明就是 0,由模板定。
    shortest_tail: float = 0
    #: 一段最长几秒。续写时每段都有一截是重叠,段越长重叠占的比例越小。没声明就是 0。
    longest_clip: int = 0
    shortest_clip: int = 0
    #: 只有几档固定时长的模型:这几档。
    allowed_clips: tuple[int, ...] = ()
    references: bool = False
    reference_video: bool = False

    @property
    def chains(self) -> bool:
        """一镜比一次能出的长时,这个模型接得下去:知道一次最长多少,又收待续写片段或首帧。"""
        return self.longest_clip > 0 and (self.extends or self.keyframes) and not self.latent_chain

    @property
    def tail_seconds(self) -> float:
        """续写时交给下一段的尾巴多长。只交一帧时没有重叠。"""
        if not self.extends:
            return 0.0
        return self.shortest_tail + TAIL_MARGIN_SECONDS if self.shortest_tail else CONTINUATION_TAIL_SECONDS

    @property
    def modes(self) -> list[str]:
        return [mode for mode, ok in (("keyframes", self.keyframes), ("references", self.references)) if ok]


@dataclass(frozen=True)
class ImagePlan:
    """图像模型的两种尺寸:关键帧(和成片同画幅)、角色三视图(横向,三个视角并排)。认不出的模型不传尺寸。"""

    frame_sizes: dict[str, str]
    sheet_size: str = ""


def _default_model(db: Session, capability: str, user_id: str) -> ModelChoice:
    row = get_row(db, capability, user_id)
    model = db.get(ProviderModel, row.provider_model_id) if row and row.provider_model_id else None
    if model is None or not model.enabled or model.profile is None or not model.profile.enabled:
        return ModelChoice()
    return ModelChoice(
        profile_id=model.provider_profile_id,
        provider=model.profile.vendor,
        model=model.model_id,
    )


def model_capabilities(db: Session | None, choice: ModelChoice, kind: str) -> dict[str, Any] | None:
    """这个模型在这种生成能力下的描述符;认不出返回 None(**不猜**)。

    点了名连接且有库可查时走逐模型解析 —— 用户自定义的声明(见 generation/resolution.py)
    在这条路上生效。纯静态上下文(官网模板导出、不建库的单元测试)传 ``db=None``,
    退回内置目录;连模型名都没有时是空选择,不是"不认识",同样 None。
    """
    if not choice.model:
        return None
    if db is not None and choice.profile_id:
        model = db.scalar(
            select(ProviderModel).where(
                ProviderModel.provider_profile_id == choice.profile_id,
                ProviderModel.model_id == choice.model,
            )
        )
        if model is not None:
            resolved = resolve_row(db, model, kind)
            return resolved.capabilities if resolved.capabilities_known else None
    return known_capabilities_for(choice.provider, choice.model, kind)


#: 整片生成的关键帧图要同时参考:白模帧 1 张 + 角色三视图最多 4 张 + 场景设定图最多 3 张 + (尾帧时)首帧 1 张。
REFERENCE_IMAGES_NEEDED = 9
#: 商品图、面料图那几条模板:每次出图只带那一张商品 / 面料图。
SINGLE_REFERENCE = 1


def _can_take_references(db: Session | None, choice: ModelChoice, *, needed: int) -> bool:
    """图像模型能不能带着 `needed` 张参考图出图。认不出的算能(用户自建的、查不到能力表的)。

    `needed` 由模板自己说:此前门槛写死 9 张(整片生成的关键帧),商品图 / 面料图模板复用了它 —— 每次只带一张图,
    却把只收 3 张的百炼 qwen-image-edit 判成缺。"""
    capabilities = model_capabilities(db, choice, "image")
    if capabilities is None:
        return bool(choice.model)
    limit = int((capabilities.get("source_limits") or {}).get(REFERENCE_IMAGE) or 0)
    return "image-to-image" in (capabilities.get("modes") or ()) and limit >= needed


def _can_shoot_from_references(db: Session | None, choice: ModelChoice, *, references: int | None = None) -> bool:
    """视频模型能不能从首帧或参考素材出片 —— 这条流程每一镜都给其中之一,从不只给一段文字。

    `references` 是参考那条路一次交几张图,由模板自己说:整片一镜交一整组(SHOT_REFERENCE_IMAGES),上身图动起来
    只交那一张上身图。此前门槛写死整片那一组 —— 只收 5 张、又必须给参考的万相 wan2.7-r2v 永远挑不中。"""
    plan = video_plan_for(db, choice, references=references)
    return bool(choice.model) and (plan.keyframes or plan.references)


def _pick(db: Session, user_id: str, kind: str, usable) -> ModelChoice:
    """默认模型合用就用它(用户自己的选择优先);不合用就在他**已经配好的**模型里挑一个合用的。
    一个都没有时留空 —— 节点上的模型格空着,界面会让他去选,那比塞一个必然失败的进去诚实。"""
    chosen = _default_model(db, kind, user_id)
    if usable(db, chosen):
        return chosen

    for model in provider_models.models_for_capability(db, kind, user_id=user_id):
        if model.profile is None or not model.profile.enabled or kind not in effective_capabilities(model):
            continue
        candidate = ModelChoice(profile_id=model.provider_profile_id, provider=model.profile.vendor, model=model.model_id)
        if usable(db, candidate):
            return candidate
    return ModelChoice()


def _chat_model(db: Session, user_id: str) -> ModelChoice:
    """模板里要对话的那几步用哪个模型。**建图写在节点上的和前置检查问的是同一个**:此前建图用 `_default_model`
    (没设默认就留空),检查用 `_pick`(没默认也挑一个配好的)—— 检查说齐了,建出来的节点却是空的。"""
    return _pick(db, user_id, "chat", lambda _db, choice: bool(choice.model))


def _shot_video_model(db: Session, user_id: str, *, references: int | None = None) -> ModelChoice:
    return _pick(db, user_id, "video", lambda db_, choice: _can_shoot_from_references(db_, choice, references=references))


def _continuation_video_model(db: Session, user_id: str) -> ModelChoice:
    """逐段往下拍用哪个模型:接潜空间的优先,其次收待续写片段的,再次收首帧的。"""
    latent = _pick(db, user_id, "video", lambda db_, choice: LATENT_LOAD_SCENE in _parameter_keys(db_, choice)
                   and DRIVING_AUDIO not in _parameter_keys(db_, choice))
    if latent.model:
        return latent
    extends = _pick(db, user_id, "video", lambda db_, choice: FIRST_CLIP in _parameter_keys(db_, choice))
    return extends if extends.model else _pick(db, user_id, "video", lambda db_, choice: FIRST_FRAME in _parameter_keys(db_, choice))


def _opening_video_model(db: Session, user_id: str, *, continuing: ModelChoice) -> ModelChoice:
    """第一段用哪个模型:从一段文字就能出片的,和续写同一家的优先 —— 同一家的画风接得更顺。"""

    if LATENT_LOAD_SCENE in _parameter_keys(db, continuing):
        #: 第一段要把潜空间存下来给续写用。
        return _pick(db, user_id, "video", lambda db_, choice: {LATENT_SAVE_SCENE} <= set(_parameter_keys(db_, choice))
                     and LATENT_LOAD_SCENE not in _parameter_keys(db_, choice) and DRIVING_AUDIO not in _parameter_keys(db_, choice))

    def from_text(db_: Session | None, choice: ModelChoice) -> bool:
        return "text-to-video" in ((model_capabilities(db_, choice, "video") or {}).get("modes") or ())

    same_vendor = _pick(db, user_id, "video", lambda db_, choice: choice.provider == continuing.provider and from_text(db_, choice))
    return same_vendor if same_vendor.model else _pick(db, user_id, "video", from_text)


def _talking_video_model(db: Session, user_id: str, *, continuing: bool) -> ModelChoice:
    """数字人长片用哪个模型:都收驱动音频、都存潜空间,续写的那条还读上一段的。"""

    def usable(db_: Session | None, choice: ModelChoice) -> bool:
        keys = _parameter_keys(db_, choice)
        return DRIVING_AUDIO in keys and LATENT_SAVE_SCENE in keys and (LATENT_LOAD_SCENE in keys) == continuing

    return _pick(db, user_id, "video", usable)


#: 明说自己出音乐的模式(内置的音乐服务)。
_MUSIC_MODES = frozenset({"text-to-music", "text-to-bgm"})


#: 歌词那一格写什么表示「纯器乐」(MiniMax Music / ACE-Step 的段落标记写法)。
INSTRUMENTAL_LYRICS = "[Instrumental]"


def _music_key(capabilities: dict[str, Any] | None, name: str) -> str:
    """音乐工作流里名字就叫 `name` 的那一格(`1.caption`、`44.lyrics`、`44.max_duration`)—— 和画幅按 `aspect_ratio`
    认是同一个约定:按节点输入的名字认,不猜。没有返回空串。"""
    caps = capabilities or {}
    keys = list((caps.get("parameter_schema") or {}).keys()) + list(caps.get("parameter_keys") or ())
    return next((key for key in keys if isinstance(key, str) and key.split(".")[-1] == name), "")


def music_caption_key(capabilities: dict[str, Any] | None) -> str:
    """写「这首曲子什么样」的那一格(`caption`)。"""
    return _music_key(capabilities, "caption")


def music_may_sing(capabilities: dict[str, Any] | None) -> bool:
    """这个音乐模型交回来的可能带人声:曲子写在 `caption` 里的那类工作流(MiniMax Music / ACE-Step)。真跑时
    MiniMax Music 3 的歌词写成空、`[Inst]`、`[Instrumental]`、`[Intro][Inst][Outro]` 五种,拆出来人声那一轨都不小 ——
    写法管不住它,配乐要先拆掉人声再铺(见 templates_music)。有「纯器乐」开关的服务不算。"""
    caps = capabilities or {}
    return bool(music_caption_key(caps)) and "instrumental" not in set(caps.get("parameter_keys") or ())


def music_request(capabilities: dict[str, Any] | None, description: str, *, seconds: int) -> tuple[str, dict[str, Any]]:
    """要一首 `seconds` 秒左右、纯器乐、照 `description` 写的配乐:交回(提示词, 参数)。

    ComfyUI 的音乐工作流(MiniMax Music / ACE-Step)把曲子写在 `caption`、歌词写在 `lyrics`,而表单版的「提示词」
    常常接的是**歌词** —— 真跑时配乐描述写进提示词,会被当歌词唱出来,caption 还是默认的「女声抒情歌」;完整工作流
    的歌词默认是一段示例说唱、时长默认 240 秒。所以有 caption 的:描述写 caption、提示词留空、`lyrics` 写纯器乐、
    `max_duration` 写成要的秒数。没有 caption 的(内置音乐服务)走提示词,有「纯器乐」开关就打开。"""
    caption = music_caption_key(capabilities)
    parameters: dict[str, Any] = {}
    if caption:
        parameters[caption] = description
        if lyrics := _music_key(capabilities, "lyrics"):
            parameters[lyrics] = INSTRUMENTAL_LYRICS
        if duration := _music_key(capabilities, "max_duration"):
            parameters[duration] = seconds
    if "instrumental" in set((capabilities or {}).get("parameter_keys") or ()):
        parameters["instrumental"] = True
    return ("" if caption else description), parameters


def _music_model(db: Session, user_id: str) -> ModelChoice:
    """成片配乐用哪个模型(见 sequences.background_music):明说出音乐的优先;没有时退一步,挑「从文字出音频」且
    写得进曲子描述的 —— ComfyUI 的音乐工作流都报成 text-to-audio(插件的缺省模式),描述写进它的 `caption` 输入
    (见 music_caption_key),没有 caption 的才走提示词。一个都没有就留空,模板不加配乐那两步。"""

    def modes(db_: Session | None, choice: ModelChoice) -> tuple[set[str], dict[str, Any]]:
        caps = model_capabilities(db_, choice, "audio") or {}
        return set(caps.get("modes") or ()), caps

    def says_music(db_: Session | None, choice: ModelChoice) -> bool:
        return bool(modes(db_, choice)[0] & _MUSIC_MODES)

    def takes_a_prompt(db_: Session | None, choice: ModelChoice) -> bool:
        found, caps = modes(db_, choice)
        return "text-to-audio" in found and (bool(music_caption_key(caps)) or caps.get("prompt") not in (None, "none"))

    music = _pick(db, user_id, "audio", says_music)
    return music if music.model else _pick(db, user_id, "audio", takes_a_prompt)


def _parameter_keys(db: Session | None, choice: ModelChoice) -> list[str]:
    return list((model_capabilities(db, choice, "video") or {}).get("parameter_keys") or ())


def _reference_image_model(db: Session, user_id: str, *, needed: int) -> ModelChoice:
    """能带 `needed` 张参考图出图的图像模型(整片生成传 REFERENCE_IMAGES_NEEDED,商品 / 面料图传 SINGLE_REFERENCE)。"""
    return _pick(db, user_id, "image", lambda db_, choice: _can_take_references(db_, choice, needed=needed))


#: 白模 / 时间线认得的三种画幅,以及每一种的成片画布。
FRAME_ASPECTS: dict[str, tuple[int, int]] = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}

def image_plan_for(db: Session | None, choice: ModelChoice) -> ImagePlan:
    """从图像模型的尺寸表里挑:关键帧和成片同画幅,三视图取最宽的横幅。认不出、或不收 `size` 的不传尺寸。"""
    capabilities = model_capabilities(db, choice, "image") or {}
    keys = capabilities.get("parameter_keys")
    #: 声明了参数却不收 size 的(百炼 qwen-image-edit 只收参考图,出图跟着参考图的比例):尺寸表再全也不传。
    sizes = capabilities.get("sizes") if not keys or "size" in keys else ()
    minimum = int(capabilities.get("min_size_pixels") or 0)
    frames = {aspect: size_for_aspect(sizes, aspect, minimum=minimum) for aspect in FRAME_ASPECTS}
    return ImagePlan(
        frame_sizes={aspect: size for aspect, size in frames.items() if size},
        sheet_size=size_for_aspect(sizes, "16:9", pick="largest", minimum=minimum),
    )


#: 整片生成「参考」那条路一镜交几张参考图:角色三视图最多 4 张 + 场景设定图最多 3 张 + 白模帧 1 张。
SHOT_REFERENCE_IMAGES = 8
#: 能从零拍出一镜的模式。说话照片、改口型、改视频、续写视频也收首帧或参考素材,但它们拍不了一镜:
#: 要的是一段现成的音频 / 视频。此前只看参数键,挑中过说话照片模型当镜头模型。
_SHOT_MODES = frozenset({"text-to-video", "image-to-video", "keyframes-to-video", "reference-to-video"})
#: 首尾帧那条路、参考那条路各交哪几种素材。
_KEYFRAME_SOURCES = frozenset({FIRST_FRAME, LAST_FRAME})
_REFERENCE_SOURCES = frozenset({REFERENCE_IMAGE, REFERENCE_VIDEO})


def _route_allowed(capabilities: dict[str, Any], sources: frozenset[str]) -> bool:
    """这条路交的素材满不满足模型的 `requires_source`(每一组里至少给一种)。万相 wan2.7-r2v 要求参考图或参考视频
    至少一种:走首尾帧那条路注定被漏斗拒 —— 此前照样把它算成能走首帧。"""
    return all(set(group) & sources for group in capabilities.get("requires_source") or () if group)


def video_plan_for(db: Session | None, choice: ModelChoice, *, references: int | None = None) -> VideoPlan:
    """从模型能力目录挑一组肯定合法的默认值；未知模型只给生成契约的通用时长。

    `references`:参考那条路一次交几张图(缺省是整片一镜的 SHOT_REFERENCE_IMAGES),收不下的不走这条路。"""
    needed = SHOT_REFERENCE_IMAGES if references is None else references
    capabilities = model_capabilities(db, choice, "video")
    if capabilities is None:
        #: 认不出的模型只按最通用的那条走:首帧生视频。不猜它收参考素材。
        parameters: dict[str, Any] = {"duration_seconds": 5}
        if not choice.model:
            #: 还没挑模型(官网副本、这台机器上还没配视频模型):把画幅、分辨率接到开始参数上。挑模型时编辑器
            #: 留下新模型仍收的那几个绑定(见前端 carriedParameters)—— 此前这里只有时长,挑了模型之后改开始
            #: 节点的画幅不起作用,片子按模型的默认画幅出。
            parameters.update({"aspect_ratio": "{{input.aspect_ratio}}", "resolution": "{{input.resolution}}"})
        return VideoPlan(parameters=parameters)

    keys = set(capabilities.get("parameter_keys") or ())
    durations = [int(value) for value in capabilities.get("duration_seconds") or ()]
    if durations:
        #: 只给几档固定时长的,取**最接近默认**的那一档(平手取短的,便宜);此前默认那档不在里面就取第一档。
        preferred = int(capabilities.get("default_duration_seconds") or 5)
        clip_seconds = min(durations, key=lambda one: (abs(one - preferred), one))
    else:
        low = int(capabilities.get("min_duration_seconds") or 1)
        high = int(capabilities.get("max_duration_seconds") or max(5, low))
        clip_seconds = max(low, min(int(capabilities.get("default_duration_seconds") or 5), high))

    aspect_ratio = str(capabilities.get("default_aspect_ratio") or "16:9")
    resolution = str(capabilities.get("default_resolution") or "720p")
    parameters: dict[str, Any] = {}
    if "duration_seconds" in keys:
        parameters["duration_seconds"] = clip_seconds
    if "aspect_ratio" in keys:
        parameters["aspect_ratio"] = "{{input.aspect_ratio}}"
    if "resolution" in keys:
        parameters["resolution"] = "{{input.resolution}}"
    size_text = str(capabilities.get("default_size") or "").lower().replace("*", "x")
    try:
        size_width, size_height = (int(value) for value in size_text.split("x", 1))
    except (TypeError, ValueError):
        ratio_dimensions = {
            **FRAME_ASPECTS,
            "4:3": (1440, 1080),
            "3:4": (1080, 1440),
        }
        size_width, size_height = ratio_dimensions.get(aspect_ratio, (1920, 1080))
    sizes: dict[str, str] = {}
    if "size" in keys:
        #: 每种画幅挑和默认那一档清晰度最接近的(832*480 → 480*832 / 624*624),不顺手升到 1080p 多花钱。
        default_area = size_width * size_height
        for aspect in FRAME_ASPECTS:
            found = size_for_aspect(capabilities.get("sizes"), aspect, pick="near", near_area=default_area)
            if found:
                sizes[aspect] = found
        if sizes:
            parameters["size"] = "{{input.video_size}}"
        elif capabilities.get("default_size"):
            parameters["size"] = str(capabilities["default_size"])
    modes = set(capabilities.get("modes") or ())
    #: 声明了模式、却一种能拍一镜的都没有(说话照片、改口型、改视频……):哪条路都不走。没声明模式的(用户自建、
    #: 查不全的)只看参数键。
    shoots = not modes or bool(modes & _SHOT_MODES)
    reference_limit = int((capabilities.get("source_limits") or {}).get(REFERENCE_IMAGE) or 0)
    return VideoPlan(
        clip_seconds=clip_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        width=size_width,
        height=size_height,
        parameters=parameters,
        sizes=sizes or None,
        keyframes=shoots and FIRST_FRAME in keys and _route_allowed(capabilities, _KEYFRAME_SOURCES),
        last_frame=shoots and LAST_FRAME in keys,
        extends=FIRST_CLIP in keys,
        latent_chain=LATENT_LOAD_SCENE in keys,
        longest_clip=max(durations) if durations else int(capabilities.get("max_duration_seconds") or 0),
        shortest_clip=int(capabilities.get("min_duration_seconds") or 0),
        allowed_clips=tuple(durations),
        shortest_tail=float(((capabilities.get("source_duration_seconds") or {}).get(FIRST_CLIP) or (0,))[0]),
        #: 参考那条路一次交 `needed` 张:收不下的(整片一镜 8 张,可灵 kling-v3-omni 只收 4 张)不走这条路。
        #: 没写上限的按收得下算(和图像模型那边「认不出的算能」同一条)。
        references=shoots and REFERENCE_IMAGE in keys and _route_allowed(capabilities, _REFERENCE_SOURCES)
        and (reference_limit == 0 or reference_limit >= needed),
        reference_video=REFERENCE_VIDEO in keys,
    )
