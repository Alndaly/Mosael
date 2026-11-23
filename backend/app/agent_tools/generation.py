"""生成:图像、视频、声音、念白、播客;能用的模型和每个模型收哪些参数。

从仓库根的 mcp_server.py 按工具族拆出来(架构体检第 8 条)。登记、调用身份、领域用例的调用方式见 ./registry。
"""

from __future__ import annotations

from typing import Any

from app.agent_tools.registry import confirmation_reply, default_workspace_id, open_card, REQUESTED_BY, tool, use_case
from app.api.schemas import GenerationOptionOut
from app.domain.generation_catalog import GENERATION_KINDS
from app.domain.entities.shot_angles import SHOT_ANGLES
from app.domain.generation.resolution import generation_options
from app.domain.generation_catalog.descriptors.shared import SOURCE_ROLE_HELP, SOURCE_ROLE_LABELS
from app.domain.providers import choices
from app.domain.voices import use_cases as voices_use_cases

@tool(effect="confirms")
def generate_image(
    prompt: str = "",
    model: str = "",
    provider: str = "",
    provider_profile_id: str = "",
    workspace_id: str = "",
    source_asset_ids: list[str] | None = None,
    parameters: dict[str, Any] | None = None,
    entity_ids: list[str] | None = None,
    shot_angle: str = "",
    pose_as_reference: bool = False,
) -> dict[str, Any]:
    """Confirmation required: generate or edit an image asset.

    entity_ids @-mentions assets from the asset library (list_entities) — characters,
    locations, props, poses, outfits: each one's prompt descriptor is appended to the
    prompt and its reference images are attached, as many as the model accepts
    (turnaround first, then front, full body, the rest). Write the character's NAME in
    the prompt where it appears ("张三站在老街口") and pass its id here — do not pick
    reference images by hand. The result says which images were attached and which
    did not fit.

    A mentioned pose is sent as a pose reference (posture and composition only), and
    only its image for this shot's angle: pass shot_angle (front, three_quarter, side,
    back, high_angle, low_angle) or no pose image is sent. If the model does not take
    pose references, pose_as_reference=true sends it as an ordinary reference image
    instead — only when the user agrees, since the line-art style can leak into the
    result.

    Use without source_asset_ids for text-to-image. Use source_asset_ids with
    existing image asset ids when the user asks to edit/transform/continue from
    a specific image, for example "把这张图里的女孩变成男孩" or "按上一张图继续改"。

    Whether a prompt is needed depends on the model — list_generation_models
    gives each model a "prompt" of "required", "optional" or "none". A model
    with "none" (an upscale / background-removal workflow) takes no prompt:
    leave prompt empty and pass the image in source_asset_ids; a prompt sent to
    it is rejected. "optional" runs with or without one.

    parameters carries the model's own settings — size, num_images, seed,
    negative_prompt and so on. Which keys a model accepts, and the allowed
    values, come from list_generation_models; call it first whenever the user
    asks for a specific size or count. Passing a key the model does not accept
    is rejected, so do not guess.
    Requires the user's approval because it may spend AI
    budget; once approved the finished image appears in the media pool. Leave provider/model empty only when the user wants the
    configured image-generation default. When the user names an engine (e.g.
    "用 ComfyUI 画"), call list_generation_models to see valid provider/model
    pairs; each saved ComfyUI workflow is its own model there and needs no
    API key. Do NOT use to analyze an existing asset (analyze_asset), tag an
    asset (update_asset_tags), or edit a
    workflow/timeline.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "generate_image",
            "requested_by": REQUESTED_BY.get(),
            "payload": {
                "prompt": prompt,
                "provider": provider,
                "provider_profile_id": provider_profile_id,
                "model": model,
                "parameters": parameters or {},
                "source_assets": [
                    {"asset_id": str(one), "role": "reference_image"} for one in (source_asset_ids or [])
                ],
                "entity_ids": [str(one) for one in (entity_ids or [])],
                **_pose_payload(shot_angle, pose_as_reference),
            },
        },
    )
    return confirmation_reply(confirmation)


def _pose_payload(shot_angle: str, as_reference: bool) -> dict[str, Any]:
    """`@` 到的姿势怎么发(entities.mentions.PoseUse 的形状)。机位填错当场拒、说出合法值 —— 等到漏斗里才 422,
    模型只会换个词再试。"""
    if shot_angle and shot_angle not in SHOT_ANGLES:
        raise ValueError(f"unknown shot_angle {shot_angle!r}; valid values are {list(SHOT_ANGLES)}")
    pose = {**({"shot_angle": shot_angle} if shot_angle else {}), **({"as_reference": True} if as_reference else {})}
    return {"pose": pose} if pose else {}


#: 执行面的合法取值。后端那一侧是 Literal,填错只会换回一个 422 —— 而模型看到 422 不会说
#: "我填错了参数",它会换个词再试一次。在这里当场拒绝,并且把合法值说出来。
_SURFACES = ("all", "agent", "direct", "gateway", "automation")


@tool(effect="reads")
def list_provider_models(capability: str = "", surface: str = "") -> dict[str, Any]:
    """List the AI connections and models this user has actually configured, by capability.

    Read-only, no confirmation. Mosael has no built-in or fallback model — every AI call
    names a connection the user created. So read this before writing a model into a workflow
    `llm` node or a board node, and before telling the user what their setup can do. Do not
    guess a model string from a vendor's name: an unconfigured one is not usable, and a
    plausible-looking guess fails only later, at run time.

    Each entry carries both halves a config needs: `profile_id` (the connection) and `model`.
    A workflow `llm` node requires BOTH — the id cannot be derived from the provider's name,
    and two connections can carry the same model.

    `surface` is the execution channel, and it changes the answer. The AI Studio conversation
    runs on "agent"; workflow `llm` nodes and board writing run on "automation", which is
    "direct" (an API-key connection that has a base_url) plus "gateway" (a signed-in OAuth
    subscription) — the run time picks between those two by how the connection authenticates.
    So both kinds of connection do work inside a workflow. What does not is an API-key
    connection with no base_url: it answers on "agent" and has no automation channel at all.
    Pass the surface the config will actually run on; leave it empty to see everything. An
    empty `models` list means different things per surface, so read the echoed `surface`
    before telling the user they have nothing configured.

    `capability` filters to one of chat / image / video / audio / podcast; empty returns all
    of them. **The LLM one is called "chat"** — there is no "text" or "llm" capability, and asking
    for one costs a failed call. `audio` is music / sound-effect generation (generate_sound),
    `podcast` is multi-speaker dialogue. Voice synthesis is not here: its model belongs to the
    chosen voice (pick an engine and a voice with the speech tools), not to a per-capability default.

    This answers "which models exist". For what an image, video or audio model ACCEPTS — sizes,
    durations, lyrics, which source roles it takes — call list_generation_models instead.
    """
    if surface and surface not in _SURFACES:
        raise ValueError(f"unknown surface {surface!r}; valid values are {list(_SURFACES)}")
    # 能力清单从 provider-defaults 的回包推导 —— 它每种能力回一行。在这里另抄一份
    # DEFAULTABLE_CAPABILITIES 就成了第二份名单,而后端加一种能力时没有任何东西会提醒它。

    defaults = use_case(choices.defaults_of)
    known = [row["capability"] for row in defaults]
    if capability and capability not in known:
        raise ValueError(f"unknown capability {capability!r}; this backend has {known}")
    #: 只收他**自己设过**的那一格:没设过就是没设过,不替他推断一个。
    chosen = {
        row["capability"]: (row.get("provider_profile_id"), row.get("model"))
        for row in defaults
        if row.get("provider_profile_id")
    }
    models: list[dict[str, Any]] = []
    for one in [capability] if capability else known:
        for item in use_case(choices.capability_models, one, surface or "all"):
            models.append(
                {
                    "capability": one,
                    "profile_id": item["provider_profile_id"],
                    "provider": item["provider_name"],
                    "model": item["model"],
                    "display_name": item.get("display_name") or "",
                    "is_default": chosen.get(one) == (item["provider_profile_id"], item["model"]),
                    # 思考能力挂在**模型**上,不挂在供应商上。None = 还没探明,按"可能会"处理。
                    "reasoning": item.get("reasoning"),
                    "reasoning_effort": item.get("reasoning_effort"),
                }
            )
    return {"surface": surface or "all", "capabilities": known, "models": models}


@tool(effect="reads")
def list_generation_models(kind: str = "") -> list[dict[str, Any]]:
    """List the AI generation engines available to generate_image / generate_video / generate_sound.

    Read-only, no confirmation. Returns what the user has actually configured — each entry
    is one connection plus one model on it (a ComfyUI entry's "model" is a saved workflow).
    Call this before generate_image/generate_video/generate_sound when the user names a specific
    engine or asks what is available. kind filters to "image", "video" or "audio" (music, songs,
    background music, sound effects, soundtrack for a video); empty returns all of them.
    Each entry's "prompt" says whether the model needs a prompt: "required", "optional", or
    "none" (it takes none — an upscale workflow; send it no prompt).
    """

    kinds = [kind] if kind in GENERATION_KINDS else list(GENERATION_KINDS)
    out: list[dict[str, Any]] = []
    for one in kinds:
        for item in use_case(lambda db, user, kind=one: generation_options(db, kind, user_id=user.id), out=GenerationOptionOut):
            capabilities = item.get("capabilities") or {}
            out.append(
                {
                    "provider": item["provider"],
                    "provider_profile_id": item["provider_profile_id"],
                    "model": item["model"],
                    "kind": item["kind"],
                    "profile": item["profile_name"],
                    "available": item["adapter_available"],
                    # 这个模型认哪些 parameters,以及各自的取值 —— 界面按同一份描述符渲染控件。
                    # 此前这里被整个剥掉:于是智能体连"这个模型支不支持首帧""时长能选几档"
                    # 都问不出来,只能盲发一个没有参数的请求。
                    "parameters": _parameter_help(capabilities),
                    "modes": capabilities.get("modes") or [],
                    # 提示词要不要写:required / optional / none(放大这类工作流不收)。智能体据此决定
                    # 写不写 —— 不说的话它只能照「生成都要提示词」的老习惯硬编一句,而那句会被拒。
                    "prompt": capabilities.get("prompt") or "required",
                    "source_rules": _source_rules(capabilities),
                }
            )
    return out


#: 描述符里,某个参数键对应的**取值清单**放在哪一栏。参数名和取值清单不同名是历史形状
#: (`size` 的清单叫 `sizes`),在这里对上一次,别让每个消费者各猜一遍。
_PARAMETER_CHOICES = {
    "size": "sizes",
    "resolution": "resolutions",
    "aspect_ratio": "aspect_ratios",
    "duration_seconds": "duration_seconds",
}

#: 素材类参数的说明**住在描述符那一层**(catalog.SOURCE_ROLE_HELP),这里只是读它。
#:
#: 此前这里另存了一份四条的名单,而角色加到八种了 —— 参考音频、待编辑的视频、待续写的片段、
#: 驱动音频四种智能体根本不知道存在,于是永远不会用。上面那句「不在这里维护第二份名单」
#: 说的就是这件事,而这张表自己就是那第二份。


def _source_rules(capabilities: dict[str, Any]) -> list[str]:
    """**素材之间的规矩**,一条一句人话。

    上限、互斥、必填、搭伴 —— 这四类此前一条都没告诉过智能体。它拿到的只有"支持哪些角色",
    于是完全可能同时给首帧和参考图(接口硬约束,必然 400),或者拿视频编辑模型不给视频。
    每一条都会被提交前的校验拦下,但那意味着一次可见的失败,而这些规矩本来就是可以先说的。
    """
    rules: list[str] = []
    label = lambda role: SOURCE_ROLE_LABELS.get(role, role)

    groups = [g for g in (capabilities.get("exclusive_source_groups") or []) if g]
    if len(groups) > 1:
        rules.append(
            "这几组只能用一组:" + " | ".join("、".join(label(r) for r in group) for group in groups)
        )
    for options in capabilities.get("requires_source") or []:
        rules.append("必须给" + "或".join(label(one) for one in options))
    for role, companions in (capabilities.get("requires_companion") or {}).items():
        rules.append(f"{label(role)}要搭配" + "或".join(label(one) for one in companions))
    floor = capabilities.get("min_reference_images")
    if floor:
        rules.append(f"给参考图就至少给 {floor} 张(第一张是正面图)")
    for role, cap in (capabilities.get("conditional_max_duration_seconds") or {}).items():
        rules.append(f"挂了{label(role)}时时长最多 {cap} 秒")
    return rules


def _parameter_help(capabilities: dict[str, Any]) -> dict[str, Any]:
    """把一个模型的描述符翻成「这些参数能给,各自能给什么」。

    **不在这里维护第二份名单** —— 键从描述符自己的 parameter_keys 来。新增一个参数只要
    改目录(domain/generation_catalog),界面和智能体同时拿到;在这里再列一遍的话,漏掉的
    那一个不会报错,只会让智能体以为它不存在。
    """
    help_: dict[str, Any] = {}
    limits = capabilities.get("source_limits") or {}
    for key in capabilities.get("parameter_keys") or []:
        if key in SOURCE_ROLE_HELP:
            cap = limits.get(key)
            # 张数写进说明里。不写的话智能体只能猜 —— 挂十张参考图、被提交前的校验拦下、
            # 再重试一次,而那一次失败对用户是可见的。
            suffix = f";最多 {cap} 份" if cap and int(cap) > 1 else ""
            help_[key] = f"{SOURCE_ROLE_LABELS.get(key, key)}({key})的 asset_id —— {SOURCE_ROLE_HELP[key]}{suffix}"
            continue
        if key in (capabilities.get("boolean_parameters") or []):
            default = capabilities.get(f"default_{key}")
            help_[key] = {"choices": [True, False], "default": default} if default is not None else {"choices": [True, False]}
            continue
        choices = (capabilities.get("parameter_choices") or {}).get(key)
        if choices is None:
            choices = capabilities.get(_PARAMETER_CHOICES.get(key, ""))
        default = capabilities.get(f"default_{key}")
        if choices:
            help_[key] = {"choices": choices, "default": default} if default is not None else {"choices": choices}
        else:
            help_[key] = "自由取值"
    return help_


@tool(effect="confirms")
def generate_video(
    prompt: str = "",
    model: str = "",
    provider: str = "",
    provider_profile_id: str = "",
    workspace_id: str = "",
    parameters: dict[str, Any] | None = None,
    source_assets: list[dict[str, str]] | None = None,
    entity_ids: list[str] | None = None,
    digital_human_consent: bool = False,
    shot_angle: str = "",
    pose_as_reference: bool = False,
) -> dict[str, Any]:
    """Confirmation required: generate a NEW video asset from a text prompt.

    entity_ids @-mentions assets from the asset library (list_entities) — characters,
    locations, props, poses, outfits — exactly like generate_image: prompt descriptors
    appended, reference images attached up to what the model accepts. Models that build
    a reusable subject first (Kling Omni) get one subject per mentioned character. A
    mentioned pose needs shot_angle (and optionally pose_as_reference), exactly as in
    generate_image.

    Use when the user asks to create new footage/animation/B-roll as a media
    asset. The prompt describes the shot; models whose "prompt" in
    list_generation_models is "none" (frame interpolation, video upscaling
    workflows) take none — leave it empty — and "optional" ones run without it.
    This does not place the video onto a timeline; after approval the
    generated asset lands in the media pool and can later be inserted with
    edit_timeline. Leave provider/model empty only when the configured
    video-generation default should be used.

    parameters carries the model's own settings — duration_seconds, resolution,
    size, aspect_ratio, seed, generate_audio and so on. Which keys a model
    accepts, and the allowed values, come from list_generation_models; call it
    first whenever the user asks for a specific length, aspect or quality.
    Passing a key the model does not accept is rejected, so do not guess.

    source_assets attaches input footage/images, each with the role it plays:
    [{"asset_id": "...", "role": "first_frame"}]. Which roles a model takes, and what each one
    does, is in that model's `parameters` from list_generation_models (a role is a key there).
    Giving first_frame and last_frame together is "keyframes to video" — the
    model animates from one image to the other. Only models whose parameters
    list the role support it.

    Digital humans (a face that speaks a given audio) are two combinations,
    offered only by models whose capabilities.modes in list_generation_models
    include them: "speech-to-video" = first_frame (a portrait) + driving_audio
    (the speech); "video-lipsync" = source_video + driving_audio (re-sync the
    mouth). The result is as long as the audio, so do not pass
    duration_seconds. To make a character from the asset library say a line,
    first generate_audio with that character's voice, then generate_video with
    its front reference image as first_frame and that audio as driving_audio.
    Only animate a real person's face or voice when the user has said they are
    that person or have the person's consent (get_entity shows
    usable_for_digital_human); never for anyone else. Any request with a
    driving_audio is rejected unless digital_human_consent is true: set it only
    after the user has confirmed, in this conversation, that they have the
    pictured person's consent (or the face is fictional / their own).

    Do NOT use for exporting an existing sequence (render_sequence), running a
    workflow (run_workflow), or editing workflow nodes (edit_workflow).
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "generate_video",
            "requested_by": REQUESTED_BY.get(),
            "payload": {
                "prompt": prompt,
                "provider": provider,
                "provider_profile_id": provider_profile_id,
                "model": model,
                "parameters": parameters or {},
                "source_assets": source_assets or [],
                "entity_ids": [str(one) for one in (entity_ids or [])],
                "digital_human_consent": bool(digital_human_consent),
                **_pose_payload(shot_angle, pose_as_reference),
            },
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def generate_sound(
    prompt: str = "",
    lyrics: str = "",
    model: str = "",
    provider: str = "",
    provider_profile_id: str = "",
    workspace_id: str = "",
    parameters: dict[str, Any] | None = None,
    source_assets: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Confirmation required: generate a NEW music / sound asset — a song (with vocals), background
    music, an instrumental, a sound effect, or a soundtrack/foley for an existing video.

    prompt describes the sound: genre, mood, instruments, tempo, "cinematic whoosh", "rain on a tin
    roof". lyrics are the words to sing, with [Verse] / [Chorus] tags; give lyrics only for songs.
    For an instrumental track pass parameters={"instrumental": true} and no lyrics. Some models need
    only lyrics, and video-to-audio models may need no text at all — the model's own rules come from
    list_generation_models(kind="audio"); call it first, pick provider/model from it, and read its
    parameters (duration_seconds, instrumental, vocal_gender, title …) and source rules. Passing a
    key the model does not accept is rejected, so do not guess.

    source_assets attaches inputs with the role each plays: {"asset_id": "...", "role":
    "source_video"} is the video to score (video-to-audio); "reference_audio" is a track to follow
    or cover; "reference_image" an image to turn into music. Leave provider/model empty only when
    the configured audio-generation default should be used. The result lands in the media pool.

    Do NOT use for spoken narration / voiceover / reading text aloud — use generate_audio for that;
    do NOT use for two-host podcasts — use generate_podcast. Do NOT use to separate or denoise an
    existing recording (separate_audio / denoise_audio).
    """
    merged = dict(parameters or {})
    if lyrics.strip():
        merged["lyrics"] = lyrics
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "generate_sound",
            "requested_by": REQUESTED_BY.get(),
            "payload": {
                "prompt": prompt,
                "provider": provider,
                "provider_profile_id": provider_profile_id,
                "model": model,
                "parameters": merged,
                "source_assets": source_assets or [],
            },
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def generate_audio(
    text: str,
    engine: str = "",
    voice: str = "",
    model: str = "",
    workspace_id: str = "",
) -> dict[str, Any]:
    """Confirmation required: generate a NEW spoken-audio asset from text.

    Use when the user asks for narration, voiceover, TTS, or other single-speaker
    generated audio. Requires the user's approval because it may spend AI
    budget; once approved the generated audio appears in the media pool.

    engine and voice go together — there is no default speech engine. engine is an id from
    list_speech_engines such as "builtin:edge" (free, built in, nothing to configure — NOT
    "edge-tts"), "builtin:clone" (a cloned voice from the workspace's voice library), or a cloud
    engine the user has connected; voice is one of that engine's voices (e.g. "zh-CN-XiaoxiaoNeural"
    for Edge, a voice id from the library for clone). builtin:alibaba-cosyvoice can also speak a
    library voice (its voices marked cloned) through a copy on the user's Bailian account; the
    first time, the user has to agree to upload the reference audio — if the card is refused for
    that, ask them to click "Clone on Bailian" in the voice library. Giving only voice works when the
    voice belongs to exactly one engine (a library voice alone means builtin:clone). If the user
    named no engine, prefer builtin:edge. model is only for cloud engines with several models. Call
    list_speech_engines when unsure which engines are ready — never tell the user to "configure" Edge.

    Do NOT use for two-host podcast/dialogue audio — use generate_podcast for that. Do NOT use
    for music, songs, background music or sound effects — use generate_sound. Do NOT use for
    analyzing existing audio/video assets — use analyze_asset.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "generate_audio",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"text": text, "engine": engine, "voice": voice, "model": model},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="reads")
def list_speech_engines(workspace_id: str = "") -> list[dict[str, Any]]:
    """Read-only: the speech engines generate_audio / dub_subtitles can speak with, and their voices.

    Each entry: id (what to pass as `engine`, e.g. "builtin:edge"), name, ready (usable right
    now for this user), free (no key, costs nothing — Edge is always ready and free), note, and
    voices [{id, name}] (pass an id as `voice`). builtin:clone lists the cloned voices in this
    workspace's voice library; builtin:alibaba-cosyvoice lists them too, marked cloned (spoken
    through a copy on the user's Bailian account). Call before generate_audio when the user did not
    name an engine and voice, or when a card was refused over the engine.
    """

    return use_case(voices_use_cases.speaking_engines, workspace_id or default_workspace_id())


@tool(effect="confirms")
def generate_podcast(
    text: str = "",
    topic: str = "",
    mode: str = "summarize",
    speakers: list[str] | None = None,
    workspace_id: str = "",
) -> dict[str, Any]:
    """Confirmation required: generate a NEW two-speaker podcast/dialogue audio asset.

    Use when the user wants a podcast-style two-person discussion, reading, or
    research audio. mode is summarize/read/research: summarize/read use text,
    research uses topic. This is not the same adapter as ordinary TTS and uses
    its own provider configuration. Do NOT use for one-speaker narration —
    use generate_audio for that.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "generate_podcast",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"text": text, "topic": topic, "mode": mode, "speakers": speakers or []},
        },
    )
    return confirmation_reply(confirmation)
