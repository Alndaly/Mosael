"""素材、项目、时间线:列、看、剪、转、导入、转写、配音、翻译、改名、删。

从仓库根的 mcp_server.py 按工具族拆出来(架构体检第 8 条)。登记、调用身份、领域用例的调用方式见 ./registry。
"""

from __future__ import annotations

from pydantic import Field
from typing import Annotated
from typing import Any

from app.agent_tools.registry import (
    confirmation_reply,
    default_workspace_id,
    ImageContent,
    open_card,
    REQUESTED_BY,
    SESSION_ID,
    TextContent,
    tool,
    ToolInputError,
    use_case,
    with_images,
)
from app.agent_tools.workflows import looks_like_workflow_graph_ops
from app.api.schemas import AssetOut, JobOut, ProjectCreate, ProjectOut, SequenceCreate, TranscriptOut, UrlImportRequest
from app.core.i18n import get_current_locale, t
from app.domain.agent.analysis_target import agent_session_target
from app.domain.analysis import use_cases as analysis_use_cases
from app.domain.analysis.listening import listen_to_assets
from app.domain.assets import use_cases as assets_use_cases
from app.domain.assets.from_url import probe_url
from app.domain.assets.listing import AssetScope, MAX_PAGE_SIZE
from app.domain.projects import use_cases as projects_use_cases
from app.domain.sequences import use_cases as sequences
from app.domain.sequences.op_args import LINKED_MARK
from app.domain.sequences.operations import edit_operation_usage
from app.domain.sequences.overview import describe_sequence
from app.domain.translate import translate_for_member
from app.domain.voices import use_cases as voice_use_cases
from app.domain.voices.subtitle_dub import DEFAULT_MATCH_DURATION
from app.media.ytdlp import YtdlpError

@tool(effect="reads")
def list_assets(
    workspace_id: str = "",
    kind: str = "",
    name_contains: str = "",
    limit: int = 50,
    cursor: str = "",
    intermediate: str = "",
) -> dict[str, Any]:
    """Read-only: list media assets in a workspace, newest first, one page at a time.

    Returns {assets: [{id, name, kind, source, duration_seconds}], count, total, next_cursor}.
    Use when you need asset_id values for timeline clips, visual analysis, tagging,
    or choosing generated/imported media. Filter with kind ("video"/"image"/"audio"/
    "document") and/or name_contains (matches name, original file name or a tag) to
    batch-select. kind "document" is an uploaded file — PDF, Word, PowerPoint, Excel, CSV,
    Markdown, text, web page, EPUB; it has no picture or sound, so it never goes on a
    timeline or into generation as a reference. limit is 1–200 (default 50); when
    next_cursor is not null there are more — call again with cursor=next_cursor and the
    same filters. Per-line pieces a process made on its way to its result (each line of a
    subtitle dub, each chunk of a lip-sync) are left out; pass intermediate="dub_line" or
    "lipsync_chunk" to list those. Do NOT use for knowledge-base notes or workflow nodes
    (read_note / list_workflows). Leave workspace_id empty to use this conversation's workspace.
    """
    workspace_id = workspace_id or default_workspace_id()

    scope = AssetScope(workspace_id=workspace_id, kinds=(kind,) if kind and kind != "all" else (), query=name_contains,
                       intermediate=intermediate)

    def one_page(db, user) -> dict[str, Any]:
        # 在事务里摊平:出了会话,ORM 对象的属性就读不到了(见 use_case)。
        found = assets_use_cases.list_assets(db, user, scope, cursor=cursor or None,
                                      limit=max(1, min(int(limit), MAX_PAGE_SIZE)))
        assets = [
            {
                "id": asset.id,
                "name": asset.name,
                "kind": asset.kind,
                "source": asset.source,
                "duration_seconds": (asset.media_info or {}).get("duration"),
            }
            for asset in found.items
        ]
        return {"assets": assets, "count": len(assets), "total": found.total, "next_cursor": found.next_cursor}

    return use_case(one_page)


@tool(effect="reads")
def inspect_sequence(sequence_id: str = "", project_id: str = "") -> dict[str, Any]:
    """Read-only: a VIDEO TIMELINE's tracks and clips — the ids, times and revision edit_timeline needs.

    Give sequence_id, or project_id for its latest sequence. Clip duration is on the timeline
    (after speed); src_in/src_out are source-media time. Not for workflows — use get_workflow.
    """
    if not sequence_id and not project_id:
        raise ValueError("Provide sequence_id or project_id")

    def load(db, user) -> dict[str, Any]:
        row = sequences.readable(db, user, sequence_id) if sequence_id else sequences.latest_of_project(db, user, project_id)
        if row is None:
            raise ValueError("This project has no timeline yet. Create one: create_project(project_id=..., name=...).")
        return describe_sequence(row)

    return use_case(load)


@tool(effect="reads")
def list_projects(workspace_id: str = "") -> list[dict[str, Any]]:
    """Read-only: list video projects in a workspace (id, name, active_sequence_id).

    Use this to find a project's active_sequence_id before inspecting, editing,
    or rendering a video timeline. Do NOT use for visual workflow IDs — use
    list_workflows for workflows.
    """
    workspace_id = workspace_id or default_workspace_id()

    projects = use_case(projects_use_cases.list_with_stats, workspace_id)
    return [
        {"id": project["id"], "name": project["name"], "active_sequence_id": project.get("active_sequence_id")}
        for project in projects
    ]


def _edit_timeline_description() -> str:
    """edit_timeline 的说明:算子清单从入参模型生成(domain/sequences/op_args)—— 校验的和写给模型看的是同一份,
    参数名不会再对不上(审查实测:说明写 split_clip 的 `at`、改画幅的 `fit`,真实参数是 src_time、fill_mode)。

    写得很紧:工具定义每轮请求都重发,本机模型的兜底窗口里它是最大的一块。"""

    return "\n".join([
        "Confirmation required: propose edits to a VIDEO TIMELINE (ids from inspect_sequence).",
        "Do NOT use for workflow nodes/edges — use edit_workflow. Times in seconds; src_* = source-media time.",
        "operations: [{kind, ...args}], in order, all or nothing; arg? = optional;",
        f"kind{LINKED_MARK} = also its link_group (linked:false = only this clip):",
        *edit_operation_usage(),
    ])


@tool(effect="confirms", description=_edit_timeline_description(), kit="canvas")
def edit_timeline(sequence_id: str, operations: list[dict[str, Any]], workspace_id: str = "") -> dict[str, Any]:
    if looks_like_workflow_graph_ops(operations):
        raise ValueError(
            "Workflow graph operations were sent to edit_timeline. "
            "Use edit_workflow(workflow_id, operations) for workflow canvas nodes/edges; "
            "remove_node deletes workflow nodes there. edit_timeline only edits clips/tracks on a sequence_id."
        )
    if not str(sequence_id or "").strip():
        raise ValueError(
            "edit_timeline requires sequence_id and only edits video timelines. "
            "For workflow canvas nodes/edges, use edit_workflow(workflow_id, operations)."
        )
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "edit_timeline",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"sequence_id": sequence_id, "operations": operations},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def render_sequence(sequence_id: str, workspace_id: str = "") -> dict[str, Any]:
    """Confirmation required: export an existing VIDEO TIMELINE sequence to mp4.

    Use after inspect_sequence/edit_timeline when the user wants a rendered video
    file from a sequence_id. Requires the user's approval because rendering
    may spend time/resources; the render job starts only if they approve. Do NOT use for running visual workflows — use run_workflow.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "render_sequence",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"sequence_id": sequence_id},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def separate_audio(asset_id: str, engine: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Confirmation required: split an audio or video asset into a voice stem and a
    background stem (music, ambience, effects), as two NEW assets.

    The source asset is never changed. Use it when someone wants the music without the voice,
    the voice without the music, or — most often — to dub over a video while keeping its
    background music: drop the voice stem, keep the background, lay the new speech on top.

    Runs a model on this machine: it needs a separation engine installed, and a long asset takes
    many minutes. Leave `engine` empty to use whichever engine is currently runnable.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "separate_audio",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"asset_id": asset_id, "engine": engine},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def denoise_audio(asset_id: str, strength: str = "medium", engine: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Confirmation required: reduce background noise in an audio or video asset, producing a
    NEW asset (a video keeps its picture; only the sound is replaced). The source is never changed.

    `strength` is light / medium / strong — medium suits most recordings; strong can dull the voice.

    Engines (leave `engine` empty for the built-in one):
    - built-in (default): steady noise only — hiss, hum, fans, air conditioning. Music is untouched.
    - `deepfilternet`: the best choice for speech with any kind of noise, including keyboards,
      clatter and chatter. Must be downloaded once in Settings; removes music as well.
    - `rnnoise`: lighter speech denoiser, nothing to install; removes music as well.
    Pick a speech engine only when the asset is mainly speech AND losing background music is
    acceptable — say so to the user. To keep ONLY the voice, use separate_audio and take the
    voice stem instead. The card is refused up front if the engine is not ready.
    Returns a job id once approved; the cleaned asset appears when the job finishes.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "denoise_audio",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"asset_id": asset_id, "engine": engine, "strength": strength},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def grab_video_frame(asset_id: str, at: float | None = None, workspace_id: str = "") -> dict[str, Any]:
    """Confirmation required: save one frame of an EXISTING video asset as a NEW image asset.

    The video is never changed. at is the time in seconds; leave it empty for the last frame.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "grab_video_frame",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"asset_id": asset_id, "at": at},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def clip_media(
    asset_id: str,
    last_seconds: float = 0,
    start: float = 0,
    end: float | None = None,
    workspace_id: str = "",
) -> dict[str, Any]:
    """Confirmation required: cut a stretch of an EXISTING video or audio asset into a NEW asset.

    The source is never changed. last_seconds takes the final few seconds and ignores start and
    end; otherwise start and end are in seconds, and leaving end empty runs to the end of the file.
    This starts a background job and the clip lands in the media library with lineage to the source.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "clip_media",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"asset_id": asset_id, "last_seconds": last_seconds, "start": start, "end": end},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def convert_video_to_gif(
    asset_id: str,
    fps: int = 12,
    width: int = 720,
    start: float = 0,
    duration: float | None = None,
    workspace_id: str = "",
) -> dict[str, Any]:
    """Confirmation required: convert an EXISTING video asset into a NEW GIF asset.

    The source video is never changed or overwritten. fps must be 1-30, width
    64-1920 pixels, start cannot be negative, and duration is optional; leave it
    empty to convert from start to the end. This starts a background job and the
    final GIF lands in the media library with lineage back to the source video.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "convert_video_to_gif",
            "requested_by": REQUESTED_BY.get(),
            "payload": {
                "asset_id": asset_id,
                "fps": fps,
                "width": width,
                "start": start,
                "duration": duration,
            },
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def scrub_video_metadata(
    asset_id: str,
    provenance: bool = False,
    workspace_id: str = "",
) -> dict[str, Any]:
    """Confirmation required: strip metadata from an EXISTING video asset into a NEW asset.

    Picture and sound stay byte-for-byte identical (stream copy, never re-encoded). Container
    tags, capture location (GPS), device/software strings, account/ID, cover art and data
    tracks (GoPro telemetry, timecode) are dropped, along with the three layers ffprobe cannot
    see: user-data SEI in H.264/H.265, DSE/fill elements inside AAC frames, and compressorname.
    Returns a reconciliation report: found, cleared, and what could not be cleared and why.

    provenance stays False unless the user asks for it. True ALSO erases the AI-generation
    marking (C2PA), which can break platforms that require that disclosure. Say so first.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "scrub_video_metadata",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"asset_id": asset_id, "provenance": bool(provenance)},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def import_from_url(
    url: str,
    kind: str = "video",
    profile_id: str = "",
    workspace_id: str = "",
) -> dict[str, Any]:
    """Confirmation required: download a video (kind=audio: its audio) from a web link into the media library.
    profile_id: signed-in browser-pool profile whose cookies to borrow (Douyin needs one)."""
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "import_from_url",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"url": url, "kind": kind, "profile_id": profile_id},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def extract_audio(
    asset_id: Annotated[str, Field(description="A video asset in the workspace.")],
    workspace_id: Annotated[str, Field(description="Workspace id; omit for the conversation's workspace.")] = "",
) -> dict[str, Any]:
    """Confirmation required: extract the audio track from an EXISTING video into a NEW .m4a asset.

    The source video is never changed. Use this after importing a video when the user wants only
    the sound; do not tell them to run ffmpeg. It copies an AAC track without re-encoding and
    falls back to AAC transcoding when the container cannot hold it directly.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "extract_audio",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"asset_id": asset_id},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def split_image_grid(
    asset_id: str,
    grid: str = "3x3",
    trim_gutter: bool = False,
    workspace_id: str = "",
) -> dict[str, Any]:
    """Confirmation required: split an EXISTING grid image (a 3x3 sticker sheet, a 2x2 storyboard) into NEW images.

    grid is `rows x columns`: 2x2, 3x3, 1x2, 2x1, 1x3, 3x1, 2x3, 3x2, 3x4 or 4x3. The image is cut into equal
    tiles in reading order; each tile becomes a new asset with lineage back to the source, which is never changed.
    trim_gutter removes a same-coloured border (the white or black lines between tiles), at most 6% per side.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "split_image_grid",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"asset_id": asset_id, "grid": grid, "trim_gutter": trim_gutter},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def create_mask(
    asset_id: str,
    source: str = "luminance",
    threshold: float = 0.5,
    invert: bool = False,
    grow: int = 0,
    feather: float = 0.0,
    workspace_id: str = "",
) -> dict[str, Any]:
    """Confirmation required: turn an EXISTING image asset into a NEW greyscale mask asset (inpainting).

    A mask says WHICH PART of the image to change: white = the area to redraw, black = keep. The result is a
    greyscale PNG with no alpha channel, registered as a new asset named "Mask · <source>"; the source image is
    never changed. Use it to hand the same region to many generations, or when the user asks for a mask by
    description ("mask out the bright sky", "cut the subject out by its transparency").

    source is "luminance" (brighter than `threshold` becomes white) or "alpha" (opaque pixels become white;
    an image with no transparency comes back all white). threshold is 0..1. invert swaps white and black.
    grow is a pixel radius: positive dilates the white area, negative shrinks it. feather softens the edge by
    that many pixels. The order is fixed: threshold, invert, grow, feather.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "create_mask",
            "requested_by": REQUESTED_BY.get(),
            "payload": {
                "asset_id": asset_id, "source": source, "threshold": threshold,
                "invert": invert, "grow": grow, "feather": feather,
            },
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="reads")
def analyze_asset(asset_id: str, question: str = "", mode: str = "auto") -> dict[str, Any]:
    """Analyze an EXISTING image/video media asset with a multimodal model.

    Use after list_assets when you need to understand visual content,
    scenes, on-screen text, mood, or best moments for cutting. Do NOT use for
    documents, web pages, workflow graphs, or to generate new media — use
    fetch_url/get_workflow/generate_*. To check how something SOUNDS (music, voice-over,
    narration, sound effects — or a video's soundtrack), use listen_to_audio.

    When called from an AI Studio turn, the backend derives the provider/model from the
    authenticated agent session. Do not try to choose or describe another provider in the
    question. OAuth vision models use the tool-free Gateway; no base URL is required.

    mode: how to feed video (the session's analysis mode is authoritative for AI Studio turns):
      - "auto" (default): native video for a capable API-backed Adapter, otherwise sampled
        frames + transcript. OAuth session models always use frames through the Gateway.
      - "native": force native video understanding (errors for OAuth Gateway or when no
        capable API-backed Adapter exists).
      - "frames": force sampled frames + transcript.
      - "shots": don't answer — queue a shot breakdown for a video and return that job (poll
        with get_job); one table per video, re-running overwrites it. Use for 拆镜头/拉片.
        The session's analysis mode does not apply here.
    Pass "native" only when the user explicitly asks for native/whole-video analysis.
    """

    if mode == "shots":
        return use_case(_queue_shot_breakdown, asset_id, out=JobOut)

    def analyze(db, user, asset_id: str) -> dict[str, Any]:
        # 这次对话定下的连接、模型和视频分析方式由会话说了算(见 agent/analysis_target):工具参数里的
        # mode 覆盖不了用户在会话里的选择(「shots」除外 —— 它不是喂视频的方式,见 _queue_shot_breakdown)。

        session_id = SESSION_ID.get()
        target = None
        if session_id:
            workspace_id = assets_use_cases.readable(db, user, asset_id).workspace_id
            target = agent_session_target(db, session_id, workspace_id=workspace_id, user_id=user.id)
        return analysis_use_cases.analyze(db, user, asset_id, question, session_target=target, mode=mode)

    return use_case(analyze, asset_id)


@tool(effect="reads")
def listen_to_audio(
    asset_ids: list[str], start: float = 0.0, end: float = 0.0, expect: str = "any"
) -> list[TextContent | ImageContent]:
    """Read-only: LISTEN to 1–4 audio or video assets (a video's soundtrack) — free, local, a few seconds.

    You cannot hear audio yourself; this measures it so you can judge it. Use it after you
    generate or pick music / voice-over / sound effects, before you tell the user it is done,
    and whenever the user says something "sounds wrong". Returns, per clip:
      - loudness: integrated LUFS (short-video norm ≈ −14), loudness range, true peak (dBTP);
      - findings: concrete problems with timestamps, worst first — clipping, true peak above −1,
        dropouts, choppy stutter, clicks, hard-cut ending, too quiet / too loud, phase, noise.
        Each has a ready-made message; quote the times when you report them;
      - rhythm: bpm (None = no steady beat) and steadiness 0–1 — check it against the edit's pace;
      - timbre: brightness_hz (higher = brighter), noisiness 0–1, energy share in low/mid/high,
        pitch_hz with its 10–90% range (a single voice or solo instrument; ignore when
        voiced_ratio < 0.3) — e.g. male voices ≈ 85–180 Hz, female ≈ 165–300 Hz;
      - sections: level and brightness every ~2 s (intro, build, drop, outro);
      - a spectrogram image (if your model can see images): dark vertical bands = dropouts,
        bright full-height lines = clicks, even vertical stripes = beats, horizontal lines = notes.
    With 2+ clips, `comparison` gives per pair: brightness ratio, pitch difference in semitones,
    band-share shift, loudness difference and a timbre distance (0 = same) — use it to explain
    how two voices or two music takes differ. start/end (seconds, end=0 = to the end) listen to
    one window only. expect: "music", "speech" or "any" — say what the clip is: pauses are normal
    in speech but a defect in music. It measures; it does not judge taste — whether the music
    fits the video is still your call, and the user's.
    """

    mode = expect if expect in ("music", "speech", "any") else "any"
    data = use_case(listen_to_assets, asset_ids, start=max(0.0, start), end=end if end > 0 else None, expect=mode)
    return with_images(data)


def _queue_shot_breakdown(db, user, asset_id: str):
    """工具那一路的「拆镜头」:按**这次对话**的连接和模型排任务,和素材详情页那个按钮同一条路
    (`analysis.use_cases.start_shots` → `analysis.shots_task`,任务种类 `shot_breakdown`)。

    `mode="shots"` 不是喂视频的方式,所以不受会话里选定的分析方式覆盖 —— 那个选择管的是「整段直读还是抽帧」。
    """

    target = None
    session_id = SESSION_ID.get()
    if session_id:
        workspace_id = assets_use_cases.readable(db, user, asset_id).workspace_id
        target = agent_session_target(db, session_id, workspace_id=workspace_id, user_id=user.id)
    return analysis_use_cases.start_shots(db, user, asset_id, session_target=target)


@tool(effect="writes")
def update_asset_tags(asset_id: str, tags: list[str]) -> dict[str, Any]:
    """Runs directly: replace an EXISTING media asset's tag list.

    Use for metadata organisation of assets returned by list_assets. This
    replaces the entire tag array; read current tags first if you want to merge
    instead of overwrite. Do NOT use for workflow node labels or project names —
    use the workflow/project-specific tools instead.
    """

    asset = use_case(assets_use_cases.update_asset, asset_id, tags=tags, out=AssetOut)
    return {"asset_id": asset["id"], "name": asset["name"], "tags": asset.get("tags", [])}


@tool(effect="reads")
def translate_text(text: str, target: str, engine: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Runs directly: translate text into a target language.

    target is a language code ("zh", "en", "ja"); the source language is auto-detected.
    engine is a capability-table id ("builtin:google", "builtin:chat", or a plugin id); leave it
    empty for the user's default. Old ids ("google", "ai") still work; an unknown one reports
    what is available rather than silently becoming Google.
    Do NOT use for transcribing audio — that is transcribe_asset.
    """

    workspace_id = workspace_id or default_workspace_id()
    # engine 原样交出去:旧 id 由能力表一处归一(capabilities.canonical_id),认不出的由它报错。
    translations = use_case(translate_for_member, workspace_id, [text], target, engine=engine)
    return {"text": (translations or [""])[0]}


@tool(effect="writes")
def transcribe_asset(asset_id: str) -> dict[str, Any]:
    """Runs directly: run speech-to-text on an audio/video asset; returns the job.

    Use when the user wants a transcript, subtitles, or the spoken content of a clip.
    Returns a job — poll it with get_job. Do NOT use for images or to describe what a
    video looks like; that is analyze_asset.
    """

    return use_case(voice_use_cases.start_transcription, asset_id, out=JobOut)


@tool(effect="confirms")
def dub_subtitles(
    sequence_id: str,
    clip_ids: list[str] | None = None,
    track_id: str = "",
    match_duration: bool = DEFAULT_MATCH_DURATION,
    line: str = "all",
    voice_id: str = "",
    engine: str = "",
    engine_voice: str = "",
    original_audio: str = "duck",
    workspace_id: str = "",
) -> dict[str, Any]:
    """Confirmation required: speak subtitle cues aloud onto a new dub track.

    Use when the user wants an existing timeline's subtitles voiced — dubbing a video
    into another language, or narrating captions. Run inspect_sequence first to see the
    subtitle track and its cues. Leave clip_ids empty to dub every cue on `track_id`
    (or on the only subtitle track); one track per call. Requires approval because it spends AI budget.

    match_duration speeds each spoken line up or down so it fills the original cue's
    slot and stays in sync with the picture. `line` picks which line of a bilingual
    cue to speak: all / first / last. Voice: either voice_id (a cloned voice from the
    user's voice library; add engine "builtin:alibaba-cosyvoice" to speak it through Bailian instead
    of the local clone engine) or engine + engine_voice (a stock voice; list_speech_engines gives the
    engine ids, e.g. "builtin:edge", and their voices). The dub is one undo step; re-dubbing
    a cue replaces its old dub. original_audio once the dub is in: duck (lowered while the dub
    speaks), mute (translated dubbing: original footage silent under the dub, music stays), keep,
    or separate (drop only the original voice; fails without a separation engine).
    Do NOT use to create the subtitles themselves — use edit_timeline's insert_text_clip.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "dub_subtitles",
            "requested_by": REQUESTED_BY.get(),
            "payload": {
                "sequence_id": sequence_id,
                "clip_ids": list(clip_ids or []),
                "track_id": track_id,
                "match_duration": bool(match_duration),
                "line": line,
                "voice_id": voice_id,
                "engine": engine,
                "engine_voice": engine_voice,
                "original_audio": original_audio,
            },
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="writes")
def create_project(
    name: str, workspace_id: str = "", project_id: str = "", timeline: bool = False,
    width: int = 0, height: int = 0, fps: float = 0,
) -> dict[str, Any]:
    """Runs directly: create a project; returns its id. timeline=true also gives it an empty VIDEO TIMELINE.

    project_id: add a new empty timeline named `name` to that EXISTING project instead — the way to
    create a timeline. Returns sequence_id for edit_timeline. width/height/fps default to the project's
    current timeline, else 1920x1080@30 (1080x1920 = vertical). Move assets in with update_asset.
    """

    request = ProjectCreate(workspace_id=workspace_id or default_workspace_id(), name=name)
    if not project_id and not timeline:
        return use_case(projects_use_cases.create, request.workspace_id, request.name, out=ProjectOut)
    # 时间线的名字照建时间线那个接口的规矩校验(长度);画幅 / 帧率越界由领域层报。
    timeline_name = SequenceCreate(workspace_id=request.workspace_id, project_id=project_id or "-", name=name).name

    def build(db, user) -> dict[str, Any]:
        # 新项目和它的第一条时间线在**同一个事务**里:不留一个建了一半的项目。
        target = project_id or projects_use_cases.create(db, user, request.workspace_id, request.name).id
        sequence = sequences.create_in_project(
            db, user, request.workspace_id, target, name=timeline_name, width=width, height=height, fps=fps
        )
        return {
            **ProjectOut.model_validate(sequence.project).model_dump(mode="json"),
            "sequence_id": sequence.id,
            "timeline": {"name": sequence.name, "width": sequence.width, "height": sequence.height, "fps": sequence.fps},
        }

    return use_case(build)


@tool(effect="writes")
def update_asset(asset_id: str, name: str = "", project_id: str = "") -> dict[str, Any]:
    """Runs directly: rename an asset and/or move it into a project.

    Leave a field empty to keep it. project_id="-" moves the asset OUT of its project.
    Do NOT use for tags — that is update_asset_tags.
    """

    if not name and not project_id:
        return {"error": "nothing to update: pass name and/or project_id"}
    return use_case(
        assets_use_cases.update_asset,
        asset_id,
        name=name or None,
        project_id=("" if project_id == "-" else project_id) if project_id else None,
        out=AssetOut,
    )


@tool(effect="confirms")
def delete_assets(asset_ids: list[str], workspace_id: str = "") -> dict[str, Any]:
    """Confirmation required: PERMANENTLY delete media assets. This cannot be undone.

    The files are removed from disk. Timeline clips that use them are NOT
    deleted: they keep their position and duration and are marked "media
    offline", and the sequence will refuse to export until they are removed or
    replaced. The confirmation card tells the user how many clips that is.

    Pass every asset the user wants gone in ONE call (max 20) so they approve
    one card instead of twenty. Call list_assets first and show the user the
    list if there is any ambiguity about WHICH assets they mean — you cannot
    take this back. Do NOT use this to tidy up on your own initiative.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "delete_assets",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"asset_ids": asset_ids},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="confirms")
def delete_projects(project_ids: list[str], workspace_id: str = "") -> dict[str, Any]:
    """Confirmation required: PERMANENTLY delete projects and their timelines.

    Assets inside a project are NOT deleted — they go back to the workspace
    level. The sequences (timelines) in the project ARE deleted with it, and
    that cannot be undone.

    Pass every project in ONE call (max 20). Call list_projects first and show
    the user which ones you mean if there is any ambiguity.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "delete_projects",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"project_ids": project_ids},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="writes")
def import_media_from_url(
    url: str,
    kind: str = "video",
    max_height: int = 0,
    workspace_id: str = "",
    project_id: str = "",
) -> dict[str, Any]:
    """Runs directly: download a video or audio from a link into the asset library.

    Use when the user gives a link to media they want as material ("把这个视频下下来"). The
    site is probed first, so a playlist link brings in its entries; `kind` is "video" or
    "audio" (audio-only skips downloading the video stream entirely); `max_height` caps the
    resolution (0 = best available). Returns a job — poll it with get_job.

    Sites needing a login are not handled here: that borrows a browser-pool profile and is
    the media library's 「从链接导入」 dialog. Say so rather than retrying.
    """
    if kind not in ("video", "audio"):
        raise ValueError('kind must be "video" or "audio"')

    workspace = workspace_id or default_workspace_id()

    def probe(db, user):
        # 先过闸再出网:能看的人不等于能往这个工作区里塞东西。
        assets_use_cases.ensure_can_import(db, user, workspace)
        try:
            return probe_url(url, workspace_id=workspace, profile_id="", start=0, actor=user.id)
        except YtdlpError as exc:
            raise ValueError(t(exc.key, get_current_locale(), **exc.params)) from exc

    listing = use_case(probe)
    entries = list(listing.entries)
    if not entries:
        # 探不出条目就**不要**硬下:那多半是链接不对或站点不支持,而"下了个空"比报错更难查。
        raise ToolInputError("agentToolErr_urlNothingToDownload", what=listing.title or url)
    # 同一份请求校验(条目上限、清晰度范围)—— 直接调用例不经过 HTTP,校验不能跟着丢。
    request = UrlImportRequest(
        workspace_id=workspace,
        project_id=project_id or None,
        kind=kind,
        max_height=max_height,
        items=[{"url": entry.url, "title": entry.title or ""} for entry in entries],
    )
    job = use_case(
        assets_use_cases.import_from_url,
        workspace,
        project_id=request.project_id,
        kind=request.kind,
        max_height=request.max_height,
        items=[item.model_dump() for item in request.items],
        profile_id=request.profile_id,
        out=JobOut,
    )
    return {"job": job, "queued": len(entries), "playlist": bool(listing.is_playlist),
            "truncated": bool(listing.truncated)}


#: 一次最多回多少条转写片段。一小时的视频有几千段,连同逐词 token 全塞回去会把上下文吃干,
#: 而模型真正要的往往是某一段。截断了**一定要说**(返回 total 和 truncated),
#: 不然"就这些了"和"还有很多"在模型眼里是一样的。
TRANSCRIPT_SEGMENT_CAP = 200


@tool(effect="reads")
def get_transcript(
    asset_id: str,
    start_seconds: float = 0.0,
    end_seconds: float = 0.0,
    max_segments: int = TRANSCRIPT_SEGMENT_CAP,
) -> dict[str, Any]:
    """Read-only: read the transcript/subtitles of an asset — timed segments with speakers.

    **This is how you find out what was actually said.** Use it before cutting by content
    ("剪掉口误/删掉这段废话"), summarising a video, locating a quote, or writing captions:
    every segment carries start_time/end_time, so a segment maps straight to a cut you can
    hand to edit_timeline. transcribe_asset only *starts* the work; this reads the result.

    Narrow with start_seconds/end_seconds (both in seconds; end 0 means "to the end") rather
    than pulling a long video whole. Per-word tokens are dropped — segment timing is what
    cutting needs. If the asset has no transcript yet, returns ``status: "missing"`` and an
    empty segment list instead of failing: run transcribe_asset first, then read it again.
    """

    data = use_case(assets_use_cases.transcript_of, asset_id, out=TranscriptOut)
    if data is None:
        #: 素材存在、只是还没转写。这不是工具坏了:回一个说得清的状态,模型才知道下一步该转写,
        #: 界面上也不会把一次正常的「还没做」画成红色失败。
        return {
            "asset_id": asset_id,
            "status": "missing",
            "message": "No transcript yet. Run transcribe_asset first.",
            "total_segments": 0,
            "truncated": False,
            "segments": [],
            "text": "",
        }
    segments = data.get("segments") or []
    if start_seconds or end_seconds:
        end = float(end_seconds) if end_seconds else float("inf")
        segments = [
            seg for seg in segments
            if float(seg.get("end_time") or 0) > float(start_seconds) and float(seg.get("start_time") or 0) < end
        ]
    total = len(segments)
    cap = max(1, min(int(max_segments), 1000))
    kept = segments[:cap]
    return {
        "asset_id": asset_id,
        "language": data.get("language"),
        "status": data.get("status"),
        "total_segments": total,
        "truncated": total > cap,
        "segments": [
            {
                "start_time": seg.get("start_time"),
                "end_time": seg.get("end_time"),
                "text": seg.get("text"),
                **({"speaker": seg["speaker"]} if seg.get("speaker") else {}),
            }
            for seg in kept
        ],
        "text": " ".join((seg.get("text") or "").strip() for seg in kept).strip(),
    }
