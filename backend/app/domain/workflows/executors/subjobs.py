"""子任务型节点:复用既有 job 执行器(转写/导出/生成/配音/发布),轮询其终态。

领域模块在这里以「适配器调用」出现:每个执行器只调对应领域的启动函数 + wait_for_job,
不掺杂领域内部逻辑——这是工作流引擎与各领域之间的接缝。
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from app.db.models import Asset, Clip, Sequence, Transcript
from app.domain.sequences.errors import SequenceDomainError
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors.registry import PreflightNode, RunScope, register, register_preflight
from app.domain.jobs import current_actor
from app.domain.workflows.executors.common import id_list, provided, text_lines, truthy, wait_for_job, whole_number

logger = logging.getLogger(__name__)

T = TypeVar("T")


#: 段内两个词之间空了这么久才算「停顿」,值得把两边的词和它们的时间交给模型(整理模板的长停顿阈值默认 1 秒,
#: 这里放宽一些:阈值是模型按节点参数自己判的,这里只决定给不给它看)。
PAUSE_SECONDS = 0.6
#: 每个停顿前后各带几个词 —— 口头禅、错误起句多半就贴在停顿两边。
WORDS_AROUND_PAUSE = 2


def _compact_timed_text(segments: list[dict[str, Any]]) -> str:
    """把逐字稿编码成交给 LLM 的紧凑 JSON:**段落级**的起止和正文,词级时间只在停顿附近给。

    此前每个词都带着起止时间整份嵌进提示词:20 分钟的口播约 11 万字,超出多数模型的上下文,整理模板在长素材上
    直接失败。模型要精确落刀的地方只有停顿(和贴在停顿两边的口头禅、错误起句):段与段之间的停顿从相邻两段的
    起止就读得出;段内的停顿在 `pauses` 里给出起止,并附上两边各几个词的时间(`tokens`,列顺序见顶层
    `token_columns`)。别处的重复、跑题按段落定位就够。

    段落正文不能省:ASR token 常省略标点,偶尔还会缺少段尾。每段都写空 speaker 是冗余,省掉。
    """
    compact: list[dict[str, Any]] = []
    for segment in segments:
        row: dict[str, Any] = {
            "start": segment["start"],
            "end": segment["end"],
            "text": segment["text"],
        }
        if segment.get("speaker"):
            row["speaker"] = segment["speaker"]
        tokens = segment.get("tokens") if isinstance(segment.get("tokens"), list) else []
        pauses: list[list[float]] = []
        near: set[int] = set()
        for index in range(1, len(tokens)):
            gap_start, gap_end = float(tokens[index - 1]["end"]), float(tokens[index]["start"])
            if gap_end - gap_start >= PAUSE_SECONDS:
                pauses.append([gap_start, gap_end])
                near.update(range(max(0, index - WORDS_AROUND_PAUSE), min(len(tokens), index + WORDS_AROUND_PAUSE)))
        if pauses:
            row["pauses"] = pauses
            row["tokens"] = [[tokens[index]["start"], tokens[index]["end"], tokens[index]["text"]] for index in sorted(near)]
        compact.append(row)
    return json.dumps(
        {"token_columns": ["start", "end", "text"], "segments": compact},
        ensure_ascii=False,
        separators=(",", ":"),
    )


@register("transcribe_asset")
def transcribe_asset(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.voices.transcription import start_transcription

    # 收进工作区:转写结果会**返回到工作流输出里**,不挡等于让别的工作区的内容流出来。
    asset_id = _asset_in(db, scope, str(config.get("asset_id", "")).strip()).id
    child = start_transcription(
        db,
        asset_id,
        created_by=current_actor(db),
        engine=str(config.get("engine") or ""),
    )
    final = wait_for_job(child.id, release=db)
    # **取这一单转出来的那份**,不是这份素材最新的那份:同一份素材同时被两处转写(并行分支、另一条
    # 工作流、剪辑页里点了一下)时,「最新」是谁先写完谁算 —— 拿到的可能是别的引擎、别的语言的那份。
    transcript_id = str((final.result or {}).get("transcript_id") or "")
    transcript = db.get(Transcript, transcript_id) if transcript_id else None
    if transcript is None:
        raise WorkflowDomainError("wfErr_transcriptMissing")
    segments = [
        {
            "start": segment.start_time,
            "end": segment.end_time,
            "text": segment.text,
            "speaker": segment.speaker or "",
            "tokens": [
                {"start": token.start_time, "end": token.end_time, "text": token.text}
                for token in segment.tokens
            ],
        }
        for segment in transcript.segments
    ]
    text = "\n".join(segment["text"] for segment in segments)
    # JSON 而不是 Python repr:模板把它嵌进 LLM 提示词时仍是一份机器可读、时间精确的逐字稿。
    timed_text = _compact_timed_text(segments)
    duration = max((float(segment["end"]) for segment in segments), default=0.0)
    return {
        "text": text,
        "timed_text": timed_text,
        "segments": segments,
        #: 一句一行 —— 和剪辑台逐字稿同一套断句(voices/sentences,契约 transcript-sentence-cases)。
        #: 要做字幕、逐句翻译的接这个:引擎的段落一段动辄二三十秒。
        "sentences": transcript_sentences(segments),
        "language": transcript.language,
        "transcript_id": transcript.id,
        "duration": duration,
    }


def export_params(config: dict[str, Any]) -> dict[str, Any] | None:
    """节点配置 → 导出参数(和剪辑页的导出对话框同形)。一样都没填就是 None:按默认档导出。"""
    from app.domain.export_presets import EXPORT_QUALITIES, EXPORT_RESOLUTIONS

    params: dict[str, Any] = {}
    resolution = str(config.get("resolution") or "").strip()
    if resolution:
        if resolution not in EXPORT_RESOLUTIONS:
            raise WorkflowDomainError("wfErr_exportOptionUnknown", params={"field": "resolution", "value": resolution})
        params["resolution"] = resolution
    quality = str(config.get("quality") or "").strip()
    if quality:
        if quality not in EXPORT_QUALITIES:
            raise WorkflowDomainError("wfErr_exportOptionUnknown", params={"field": "quality", "value": quality})
        params["quality"] = quality
    label = str(config.get("ai_label") or "").strip().lower()
    if label:
        if label not in ("yes", "no"):
            raise WorkflowDomainError("wfErr_exportOptionUnknown", params={"field": "ai_label", "value": label})
        params["ai_label"] = label == "yes"
    return params or None


@register("document_to_markdown")
def document_to_markdown(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """一份文档素材 → 解析出的 Markdown(ADR 0031)。`parser` 点名用哪一家(本地 / MinerU 这类插件连接):
    有这一家成功的解析就用它,没有就让它解析一遍、等它做完。不点名:用最新成功的那份,还没解析过(或上次
    失败了)就先用本地解析解一遍。`first` / `last` 只取那几段(页 / 幻灯片 / 表 / 章,1 起)。"""
    from app.domain.capabilities import CapabilityUnavailable
    from app.domain.documents import LOCAL_PARSER
    from app.domain.documents.extraction import latest_extraction, read_sections, start_parse
    from app.domain.documents.local import DocumentParseError

    asset = _asset_in(db, scope, str(config.get("asset_id") or "").strip())
    if asset.kind != "document":
        raise WorkflowDomainError("wfErr_notDocument", params={"name": asset.name})
    parser = str(config.get("parser") or "").strip() or None
    extraction = latest_extraction(db, asset.id, parser=parser)
    if extraction is None:
        running = latest_extraction(db, asset.id, succeeded=False, parser=parser)
        if running is None or running.status not in ("queued", "running"):
            actor = current_actor(db)
            try:
                running = start_parse(db, asset, owner_user_id=actor, provider_id=parser or LOCAL_PARSER, created_by=actor)
            except (CapabilityUnavailable, DocumentParseError) as exc:
                raise WorkflowDomainError.from_error(exc) from exc
        asset_id, job_id = asset.id, running.job_id
        wait_for_job(job_id or "", release=db)
        extraction = latest_extraction(db, asset_id, parser=parser)
        if extraction is None:
            raise WorkflowDomainError("wfErr_documentNotParsed", params={"name": asset.name})
    total = extraction.sections
    first = max(1, whole_number(config, "first", node_type="document_to_markdown", default=1))
    last = min(total, whole_number(config, "last", node_type="document_to_markdown", default=total))
    sections = read_sections(extraction, first, last)
    separator = "\n\n---\n\n" if extraction.unit in ("page", "slide") else "\n\n"
    return {
        "markdown": separator.join(one["markdown"].strip() for one in sections if one["markdown"].strip()),
        "title": asset.name.rsplit(".", 1)[0],
        "sections": [{"index": one["index"], "title": one.get("title") or "", "markdown": one["markdown"]} for one in sections],
        "total": total,
        "unit": extraction.unit,
    }


def _digital_human_needs_consent(config: dict[str, Any], place: PreflightNode) -> None:
    """挂了驱动音频(说话照片、对口型,即数字人)就要勾「已取得授权」—— 在任何节点花钱之前说,判据和生成漏斗同一个
    (is_digital_human_request)。素材常是引用(`{{配音.asset_id}}:driving_audio`),角色写在模板里,所以按原始配置认。"""
    from app.domain.generation.operations import is_digital_human_request, parse_source_assets

    raw = place.node.get("config") or {}
    kind = str(raw.get("kind") or "image").strip() or "image"
    parameters = raw.get("parameters") if isinstance(raw.get("parameters"), dict) else {}
    if not is_digital_human_request(parse_source_assets(raw.get("source_assets"), kind=kind), parameters):
        return
    if not place.deferred("consent") and str(config.get("consent") or "").strip() != "yes":
        raise WorkflowDomainError("wfErr_talkingNeedsConsent")


@register("export_sequence")
def export_sequence(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.render import start_export

    # start_export 会把渲染任务建在**序列所属的那个工作区**(workspace_id=sequence.workspace_id),
    # 所以不挡的话,A 工作区的工作流能在 B 工作区里起一个渲染任务并拿到产出的 asset_id。
    sequence = _sequence_in(db, scope, str(config.get("sequence_id", "")).strip())
    child = start_export(db, sequence.id, export_params(config), created_by=current_actor(db))
    final = wait_for_job(child.id, release=db)
    asset_id = str((final.result or {}).get("asset_id", ""))
    return {"asset_id": asset_id}


@register("ai_generate")
def ai_generate(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.generation import create_generation_job
    from app.domain.generation.operations import GenerationDomainError, keep_source_group, parse_source_assets
    from app.domain.generation.runner import start_generation_thread
    from app.domain.entities import parse_entity_ids

    kind = str(config.get("kind", "image")).strip() or "image"
    # 声明里模型是必填的;错误(包括"没有可用模型")按工作流错误报出来。
    try:
        generation, child = create_generation_job(
            db,
            workspace_id=scope.workspace_id,
            session_id=None,
            project_id=None,
            created_by=current_actor(db),
            provider=str(config.get("provider", "")),
            provider_profile_id=str(config.get("provider_profile_id") or "").strip() or None,
            model=str(config.get("model", "")),
            kind=kind,
            prompt=str(config.get("prompt", "")),
            negative_prompt=str(config.get("negative_prompt", "")),
            parameters=provided(dict(config.get("parameters") or {})),
            source_assets=keep_source_group(
                parse_source_assets(config.get("source_assets"), kind=kind),
                str(config.get("source_group") or "all").strip(),
            ),
            #: 点名的资产按本工作流的工作区取(scope.workspace_id);别处的 id 由生成漏斗当场拒。
            entity_ids=parse_entity_ids(config.get("entity_ids")),
            digital_human_consent=str(config.get("consent") or "").strip() == "yes",
        )
    except GenerationDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    db.commit()
    generation_id, child_id = generation.id, child.id
    start_generation_thread(generation_id)
    wait_for_job(child_id, release=db)
    # 等待时交还了会话(release 会 close 它,里面的对象全部脱管)—— 按 id 重新取,不能 refresh 脱管的那两个:
    # 此前这里 refresh,生成跑完之后节点必然炸在「not persistent within this Session」。
    from app.db.models import GenerationJob, Job

    generation = db.get(GenerationJob, generation_id)
    child = db.get(Job, child_id)
    #: asset_id 是**封面**(下游多数节点只接一份),asset_ids 是全部 —— 生成一次可能出多张
    #: (图像接口的 n),只往下游传第一张的话,其余的在工作流里就没人看得见了。
    asset_ids = [str(one) for one in ((child.result or {}).get("asset_ids") or []) if one]
    return {
        "asset_id": generation.result_asset_id or "",
        "asset_ids": asset_ids,
        "generation_id": generation.id,
    }


@register_preflight("ai_generate")
def ai_generate_preflight(db: Session, config: dict[str, Any], actor: str | None, place: PreflightNode) -> None:
    """生成节点的运行前检查,两样:挂了驱动音频要勾授权(_digital_human_needs_consent);跑之前就知道的参数合不合模型
    (_parameters_fit_the_model)。同一种节点只能登记一个 preflight,所以在这里合起来。"""
    _digital_human_needs_consent(config, place)
    _parameters_fit_the_model(db, config, actor)


def _parameters_fit_the_model(db: Session, config: dict[str, Any], actor: str | None) -> None:
    """跑之前就知道的参数(字面量、开始参数插好的画幅 / 尺寸 / 时长)先按选中的模型问一遍,不建任务、不看素材。

    此前整片改成 1:1 交给 Veo(只收 16:9 / 9:16),要等前面五次对话、几张三视图和关键帧都付完钱,生成视频那一步
    才被拒。模型选择本身是引用的、或者参数全是运行时才知道的,不在这里判;模型解析不出来也不在这里说(漏斗会说)。
    """
    from app.domain.generation.operations import GenerationDomainError, check_parameters

    choice = ("provider", "provider_profile_id", "model", "kind")
    parameters = config.get("parameters")
    if any(key not in config for key in choice) or not isinstance(parameters, dict):
        return
    known = provided(dict(parameters))
    if not known:
        return
    try:
        check_parameters(
            db,
            user_id=actor,
            kind=str(config.get("kind") or "image").strip() or "image",
            provider=str(config.get("provider") or ""),
            model=str(config.get("model") or ""),
            parameters=known,
            provider_profile_id=str(config.get("provider_profile_id") or "").strip() or None,
        )
    except GenerationDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc


@register("video_to_gif")
def video_to_gif(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.assets.video_gif import VideoGifError, start_video_to_gif

    asset = db.get(Asset, str(config.get("asset_id") or ""))
    if asset is None or asset.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_gifAssetNotInWorkspace")
    try:
        child = start_video_to_gif(
            db,
            asset=asset,
            created_by=current_actor(db),
            fps=whole_number(config, "fps", node_type="video_to_gif", default=12),
            width=whole_number(config, "width", node_type="video_to_gif", default=720),
            start=float(config.get("start") or 0),
            duration=float(config["duration"]) if config.get("duration") not in (None, "") else None,
        )
    except VideoGifError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    final = wait_for_job(child.id, release=db)
    return {
        "asset_id": str((final.result or {}).get("asset_id") or ""),
        "source_asset_id": asset.id,
    }


@register("import_url")
def import_url(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """从链接下载一条进素材库:排一次「从链接导入」任务(和素材库那个按钮同一个任务),等它落定。

    `fail_on_error = no` 时下载失败不算这一步失败,交出空的 asset_id 和原因 —— 分析类模板里视频只是材料之一,
    下不到(要登录、被限流)时数据和评论照样分析,报告里说明少了口播这一块;而不是把前面已经付过钱的取数一起作废。
    取消照样往上抛:那不是下载失败。
    """
    from app.domain import browser, sharing
    from app.domain.assets.from_url import UrlImportError, start_url_import
    from app.domain.workflows import as_text
    from app.domain.workflows.authority import current_authority

    url = as_text(config.get("url")).strip()
    if not url:
        raise WorkflowDomainError("wfErr_importUrlEmpty")
    kind = str(config.get("kind") or "video")
    profile_id = str(config.get("profile_id") or "").strip()
    must_succeed = truthy(config.get("fail_on_error") if config.get("fail_on_error") not in (None, "") else "yes")
    try:
        if profile_id:
            #: 借的是档案主人的登录态:跑的人和被执行那一版图的担保人都要过得了闸(见 workflows.authority)。
            #: 任务自己跑的时候还会按发起人再查一次。
            browser.usable_profile(db, scope.workspace_id, profile_id, actor=current_authority(db))
        child = start_url_import(
            db,
            workspace_id=scope.workspace_id,
            project_id=None,
            items=[{"url": url, "title": ""}],
            kind=kind,
            created_by=current_actor(db),
            profile_id=profile_id or None,
            max_height=whole_number(config, "max_height", node_type="import_url", default=1080),
        )
        final = wait_for_job(child.id, release=db)
    except (UrlImportError, sharing.NotUsableError, browser.BrowserDomainError) as exc:
        if must_succeed:
            raise WorkflowDomainError.from_error(exc) from exc
        return {"asset_id": "", "name": "", "error": str(exc)}
    except WorkflowDomainError as exc:
        if must_succeed or exc.key != "wfErr_childFailed":
            raise
        return {"asset_id": "", "name": "", "error": str(exc.params.get("reason") or exc)}
    asset_ids = [str(one) for one in (final.result or {}).get("asset_ids") or []]
    asset = db.get(Asset, asset_ids[0]) if asset_ids else None
    return {"asset_id": asset.id if asset else "", "name": asset.name if asset else "", "error": ""}


def _speech_params(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """「引擎 + 音色」两格 → 合成要的那组参数(见 voices.engine_catalog.synthesis_params)。

    音色的报错原样转述(带着它的 key):此前在前面拼一截「语音合成」/「字幕配音」,那截是
    写死的中文,而原因在落库那一刻就被翻成了字 —— 英文界面里读到的是两段中文。"""
    from app.domain.voices.engine_catalog import synthesis_params
    from app.domain.voices.voices import VoiceError

    try:
        return synthesis_params(
            db,
            engine=str(config.get("engine") or ""),
            voice=str(config.get("voice") or ""),
            speed=float(config.get("speed") or 1.0),
            user_id=current_actor(db),
            workspace_id=scope.workspace_id,
        )
    except VoiceError as exc:
        raise WorkflowDomainError.from_error(exc) from exc


@register("synthesize_speech")
def synthesize_speech(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """把文本念出来。音色是一格,引擎决定它指什么(见 `_speech_params`)。"""
    from app.domain.voices.voices import start_synthesis

    child = start_synthesis(
        db,
        text=str(config.get("text", "")),
        project_id=None,
        created_by=current_actor(db),
        **_speech_params(db, scope, config),
    )
    final = wait_for_job(child.id, release=db)
    return {"asset_id": str((final.result or {}).get("asset_id", ""))}


def clone_engine_problem() -> WorkflowDomainError | None:
    """本机克隆引擎(配音库的音色走它)**已知**跑不起来时的那句原因;跑得起来或还没测过就是 None。

    模板预填音色、前置检查和下面的运行前检查用的是这一个判据(见 templates._cloned_voice_status)。只读已经
    测过的结果,不在请求里起探测(起子进程 import torch,要十几秒)—— 没测过的交给合成那一步再判。
    """
    from app.ai.runtime import config as tts_config
    from app.ai.runtime import tts_models
    from app.domain.voices.voices import VoiceError

    engine = tts_config.get().engine
    label = next((item.label for item in tts_models.CATALOG if item.id == engine), engine)
    ready, known = tts_models.runtime_status(engine)
    if known and not ready:
        return WorkflowDomainError.from_error(VoiceError("voiceErr_noRuntime", label=label))
    if ready and not tts_models.is_installed(engine):
        return WorkflowDomainError.from_error(VoiceError("voiceErr_noWeights", label=label))
    return None


def clone_engine_must_run(config: dict[str, Any]) -> None:
    """用配音库的音色念(引擎是本机克隆、音色这一格跑之前就知道且不空)时,克隆引擎得跑得起来。

    此前要等前面的对话、出图、出视频都付完钱,念第一句时才说「F5-TTS 还没有运行环境」。音色是引用别的节点的、
    或者空着(整片 / 混剪不配音时就是空的,那一步整段跳过)都不在这里判。
    """
    from app.domain.voices.speech import CLONE_ENGINE

    if "engine" not in config or "voice" not in config:
        return
    engine = str(config.get("engine") or "").strip() or CLONE_ENGINE
    if engine != CLONE_ENGINE or not str(config.get("voice") or "").strip():
        return
    problem = clone_engine_problem()
    if problem is not None:
        raise problem


@register_preflight("synthesize_speech")
def synthesize_speech_preflight(db: Session, config: dict[str, Any], actor: str | None, place: PreflightNode) -> None:
    clone_engine_must_run(config)


@register("publish")
def publish(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    from app.db.models import Asset, PublishAccount
    from app.domain.publish import start_publish

    account = db.get(PublishAccount, str(config.get("account_id", "")))
    if account is None or account.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_publishAccountMissing")
    asset = db.get(Asset, str(config.get("asset_id", "")))
    if asset is None or asset.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_publishAssetMissing")
    # 用的是**这次运行**的授权:操作人(手动运行是点运行的人,定时任务 / webhook 是任务主人,
    # 见 scheduler.operations._open_run),加上被执行那一版图的担保人(见 workflows.authority)。
    # 别人的私有账号、同事改过而主人没认可的那一版,都在 start_publish 里被拒。
    from app.domain.workflows.authority import current_authority

    task = start_publish(
        db,
        workspace_id=scope.workspace_id,
        account=account,
        asset=asset,
        title=str(config.get("title", "")),
        description=str(config.get("description", "")),
        actor=current_authority(db),
        tags=[],
    )
    final = wait_for_job(task.job_id or "", release=db)
    result = final.result or {}
    post = result.get("post") if isinstance(result.get("post"), dict) else {}
    return {"post_id": str(post.get("post_id") or ""), "post_url": str(post.get("url") or ""), "result": result}



@register("edit_timeline")
def edit_timeline(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """把一组操作应用到时间线上。

    智能体早就能做这件事(edit_timeline 工具),而工作流只能「导出序列」—— 于是「生成素材
    → 编排 → 导出」这条最常见的链路,中间那步在画布上做不了,必须切去对话里或者手动摆。

    操作的种类和智能体那边**是同一份**(domain/sequences/operations.EDIT_OP_KINDS)——
    不是抄一遍,是同一个清单。
    """
    from app.domain.sequences.operations import apply_edit_operations

    # **过 _sequence_in,和这一族的其它节点一样。** 此前这里只判了非空就把 id 交下去,而
    # apply_edit_operations 没有工作区的概念 —— 于是 A 工作区的工作流能改 B 工作区的时间线。
    # sequence_id 常常来自上游节点,而上游拿得到任何地方的 id。
    #
    # 智能体走同一个算子却不受影响:它在确认卡**建立时**就查过归属(见 agent/confirmations
    # 的 _validate_payload)。漏的只有这一条路。
    sequence = _sequence_in(db, scope, str(config.get("sequence_id", "")).strip())
    sequence_id = sequence.id
    operations = config.get("operations")
    if isinstance(operations, str):
        # 上游节点常常给一段 JSON 文本(比如 code 节点算出来的),接住它省得再加一个解析节点。
        try:
            operations = json.loads(operations)
        except json.JSONDecodeError as exc:
            raise WorkflowDomainError("wfErr_operationsNotJson", params={"reason": exc}) from exc
    if not isinstance(operations, list) or not operations:
        raise WorkflowDomainError("wfErr_operationsEmpty")

    def edit(sequence: Sequence) -> tuple[int, int]:
        # 改动记在跑这条工作流的人头上 —— 和剪辑页、智能体一样,不记成「没有人」(撤销「只撤我自己的」、
        # 冲突时「是谁改的」都靠它)。
        applied = apply_edit_operations(db, sequence.id, operations, actor_id=current_actor(db))
        db.flush()
        db.refresh(sequence)
        return applied, sequence.revision

    applied, revision = _write_timeline(db, scope, sequence_id, edit)
    return {"applied": applied, "sequence_id": sequence_id, "revision": revision}


@register("inspect_sequence")
def inspect_sequence(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """看一眼时间线现在长什么样 —— 编排之前得先知道有哪些轨道、片段排到了第几秒。

    和智能体的 inspect_sequence 读的是**同一份**(domain/sequences/overview):片段用 clip_id、轨道用
    track_id,正好是 edit_timeline 的操作要的名字。
    """
    from app.domain.sequences.overview import describe_sequence

    sequence_id = str(config.get("sequence_id", "")).strip()
    if not sequence_id:
        raise WorkflowDomainError("wfErr_inspectNeedsSequence")
    sequence = db.get(Sequence, sequence_id)
    if sequence is None or sequence.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_sequenceNotInWorkspace")
    view = describe_sequence(sequence)
    # 只交出声明过的那几个输出(见 node_types 的 outputs):画幅、名字这类工作流里接不出去的就不带。
    return {
        "sequence_id": view["sequence_id"],
        "revision": view["revision"],
        "tracks": view["tracks"],
        "duration": view["duration"],
        "video_track_id": view["video_track_id"],
        "audio_track_id": view["audio_track_id"],
    }


def _asset_in(db: Session, scope: RunScope, asset_id: str) -> Asset:
    """取这份素材,并确认它属于这次运行所在的工作区。和 _sequence_in 成对。

    asset_id 同样常常来自上游节点。少了这一条,A 工作区的工作流能转写 B 工作区的素材
    ——而转写结果是**要返回到工作流输出里**的,那是把别人的内容读出来。
    """
    if not asset_id:
        raise WorkflowDomainError("wfErr_assetIdMissing")
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_assetNotInWorkspace")
    return asset


def _sequence_in(db: Session, scope: RunScope, sequence_id: str) -> Sequence:
    """取这条序列,并确认它属于这次运行所在的工作区。

    sequence_id 常常来自上游节点,而上游可能拿到任何地方的 id —— 这一条挡的是
    「用 A 工作区的工作流去改 B 工作区的时间线」。
    """
    if not sequence_id:
        raise WorkflowDomainError("wfErr_sequenceIdMissing")
    sequence = db.get(Sequence, sequence_id)
    if sequence is None or sequence.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_sequenceNotInWorkspace")
    return sequence


#: 同一条时间线被别的写入方抢先改了一版时,重读重试几次。每一次冲突都意味着别人**已经写成**了一次,
#: 所以同时往一条时间线上写的有 N 个,最多冲突 N-1 次;并发的循环(4 路)套上并行分支,留足余量。
_TIMELINE_ATTEMPTS = 10


def _write_timeline(db: Session, scope: RunScope, sequence_id: str, write: Callable[[Sequence], T]) -> T:
    """工作流往一条时间线上写的**唯一形状**:读最新的一版 → 写;版本冲突就回滚、重读、再写。

    时间线的每一次写入按版本号 CAS(见 sequences._timeline._record_operation):读到同一版的两个写入方,
    后写的那个改 0 行、当场报「版本冲突」。并行的分支(或并发的循环项)同时往同一条时间线上接素材
    正是这样 —— 各自在自己的会话里读到第 5 版,整条工作流因为一个版本号失败。

    冲突时回滚**这个节点**的改动(它在这一步之前没写过别的)、按库里最新的一版重算再写:「接到末尾」
    的末尾、新轨道之前有哪些轨,都按别人刚写成的那一版算。提交仍归引擎(节点跑完就是它的事务边界);
    SQLite 一次只有一个写入方,后来者在写的那一刻等前一个节点提交,然后撞上新版本号、重试。

    时间线域的拒绝转成工作流错误,带着 key 按读的人的语言说 —— 此前接素材、加轨道、清空都没转,
    用户看到的是 `src_in must be non-negative` 这样的原文。
    """
    for attempt in range(_TIMELINE_ATTEMPTS):
        db.expire_all()  # 读库里最新的那一版,不用会话里攒着的旧快照
        sequence = _sequence_in(db, scope, sequence_id)
        try:
            return write(sequence)
        except SequenceDomainError as exc:
            if getattr(exc, "key", "") == "seqErr_revisionConflict" and attempt + 1 < _TIMELINE_ATTEMPTS:
                db.rollback()
                continue
            raise WorkflowDomainError.from_error(exc) from exc
    raise AssertionError("unreachable")  # pragma: no cover — 最后一次要么返回,要么抛


def _seconds(config: dict[str, Any], key: str, node_type: str) -> float | None:
    """一格秒数:留空是 None;填了就得是有限的数(数字格式已由 check_number_fields 核过,这里挡 inf / nan)。"""
    from app.domain.workflows import NODE_TYPES, field_name

    raw = config.get(key)
    if raw in (None, ""):
        return None
    value = float(raw)
    if not math.isfinite(value):
        spec = NODE_TYPES[node_type]["config"][key]
        raise WorkflowDomainError("wfErr_mustBeNumber", params={"field": field_name(key, spec)})
    return value


@register("timeline_append")
def timeline_append(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """把一份素材接到轨道上 —— 默认接在末尾,也可以放在指定的那一秒。

    **这是编排里占九成的动作**,所以它是一个有真表单的节点,而不是让人手写一条
    `{"kind": "insert_clip", "timeline_start": …}` —— 那个 timeline_start 还得自己算,
    而"接到末尾"本来就该由机器算。
    """
    from app.domain.sequences.append import asset_span, track_end, track_for_asset
    from app.domain.sequences.fitting import TRACK_FOR_ASSET, fit_asset_on_track
    from app.domain.sequences.operations import InsertClip, insert_clip

    sequence_id = _sequence_in(db, scope, str(config.get("sequence_id", "")).strip()).id
    asset = _asset_in(db, scope, str(config.get("asset_id", "")).strip())
    want = TRACK_FOR_ASSET.get(asset.kind, "video")

    # 截取范围:留空就是整段素材。出点夹到素材末尾、素材进不进得了这条轨,由放片段的那一套规矩
    # 说了算(sequences.fitting.fit_asset_on_track)—— 剪辑页的插入过的也是它,两边不再各写一份。
    src_in = _seconds(config, "start", "timeline_append") or 0.0
    src_out = _seconds(config, "end", "timeline_append")
    if src_out is None:
        src_out = asset_span(asset)
    if src_in < 0:
        raise WorkflowDomainError("wfErr_trimStartNegative")
    if src_out <= src_in:
        raise WorkflowDomainError("wfErr_trimRange")
    at = _seconds(config, "at", "timeline_append")
    if at is not None and at < 0:
        raise WorkflowDomainError("wfErr_startNegative")
    limit = _seconds(config, "max_duration", "timeline_append")
    trim_overflow = _yes_no(config, "trim_overflow", default=False)
    track_id = str(config.get("track_id", "")).strip()
    actor = current_actor(db)

    def append(sequence: Sequence) -> tuple[str, float, float, float]:
        tracks = list(sequence.tracks or [])
        if track_id:
            track = next((one for one in tracks if one.id == track_id), None)
            if track is None:
                raise WorkflowDomainError("wfErr_trackNotOnSequence")
        else:
            # 留空就挑第一条同类轨道 —— 绝大多数时间线只有一条视频轨和一条音频轨,
            # 逼用户先跑一个「看一眼时间线」把 id 取出来是纯仪式。
            track = track_for_asset(sequence, asset.kind)
            if track is None:
                raise WorkflowDomainError("wfErr_noSuchTrackKind", params={"kind": want})
        clip_out = fit_asset_on_track(asset, track, src_in, src_out)
        speed = _fit_speed(clip_out - src_in, config.get("max_duration"))
        #: 加速到上限仍放不下、又要求不许超出去(口播不能压到下一段、成片尾不能留黑):把尾巴裁到正好放下。
        trimmed = 0.0
        if trim_overflow and limit is not None and limit > 0:
            overflow = (clip_out - src_in) / (speed or 1.0) - limit
            if overflow > 1e-6:
                trimmed = overflow
                clip_out = src_in + limit * (speed or 1.0)
        # 落点:给了 `at` 就放在那一秒(口播要对齐它那一镜的画面,而不是接在上一段口播后面);
        # 没给就接到末尾 —— 这条轨道上最后一个片段的终点,空轨道就是 0。在锁里算:并行分支刚接上去的
        # 那一段也算在"末尾"里。
        start = at if at is not None else track_end(track)
        # 倍速随插入一起给:先按 1 倍放下再改速的话,放下那一刻多出来的那截已经按覆盖把后面的片段裁掉了。
        clip = insert_clip(
            db,
            sequence.id,
            InsertClip(track_id=track.id, asset_id=asset.id, timeline_start=start, src_in=src_in, src_out=clip_out,
                       speed=speed or 1.0, actor_id=actor),
        )
        return clip.id, start, (clip_out - src_in) / (speed or 1.0), trimmed

    clip_id, timeline_start, span, trimmed = _write_timeline(db, scope, sequence_id, append)
    return {
        "clip_id": clip_id,
        "timeline_start": timeline_start,
        "timeline_end": timeline_start + span,
        #: **实际**占了几秒。出点被夹到素材末尾时比计划的短 —— 下游(旁白最长多久、字幕裁到哪)按它,不按计划。
        "duration": span,
        "trimmed": round(trimmed, 3),
        "sequence_id": sequence_id,
    }


#: 为了塞进 max_duration 最多加速到多少。再快就听不清了 —— 宁可让它超出去,也不交一段
#: 听不懂的口播(超出多少,调用方从 timeline_end 看得到)。
MAX_FIT_SPEEDUP = 1.5


def _fit_speed(span: float, max_duration: Any) -> float | None:
    """片段比 max_duration 长时该用的倍速;不需要变就是 None。**只加速,不减速** ——
    一段话比它的位置短是正常的,拉慢了反而拖沓。"""
    if max_duration in (None, ""):
        return None
    limit = float(max_duration)
    if limit <= 0 or span <= limit:
        return None
    return round(min(MAX_FIT_SPEEDUP, span / limit), 3)


@register("timeline_add_track")
def timeline_add_track(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.sequences.operations import AddTrack, add_track

    sequence_id = _sequence_in(db, scope, str(config.get("sequence_id", "")).strip()).id
    kind = str(config.get("kind", "video")).strip() or "video"

    def add(sequence: Sequence) -> str:
        before = {one.id for one in (sequence.tracks or [])}
        add_track(db, sequence.id, AddTrack(kind=kind))
        db.flush()
        db.refresh(sequence)
        return next((one.id for one in (sequence.tracks or []) if one.id not in before), "")

    return {"track_id": _write_timeline(db, scope, sequence_id, add), "sequence_id": sequence_id}


@register("timeline_clear")
def timeline_clear(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """删掉所有片段,轨道留着。

    留着轨道是有意的:重跑一条工作流时,下游的「接素材」还指望那几条轨道在。

    **一次删完,记一条操作**(placement.delete_clips_batch):此前逐条 delete_clip,清掉 40 段就是 40 条
    撤销记录 —— 想在剪辑页里撤回这一次清空,得按 40 次 ⌘Z。
    """
    from app.domain.sequences.operations import DeleteClipsBatch, delete_clips_batch

    sequence_id = _sequence_in(db, scope, str(config.get("sequence_id", "")).strip()).id

    def clear(sequence: Sequence) -> int:
        clip_ids = [clip.id for track in (sequence.tracks or []) for clip in (track.clips or [])]
        if clip_ids:
            delete_clips_batch(db, sequence.id, DeleteClipsBatch(clip_ids=tuple(clip_ids)))
        return len(clip_ids)

    return {"removed": _write_timeline(db, scope, sequence_id, clear), "sequence_id": sequence_id}


@register("timeline_cut_ranges")
def timeline_cut_ranges(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """一次删除同一片段的多个源时间范围 —— 和剪辑台按文字剪同一个波纹删除(cutting._ripple_cut):
    保留段首尾相接,同轨后面的左移,分离出的音频同步剪,字幕跟着删 / 左移,整批一步撤销。

    不循环调用 cut_clip_range:范围都是**原片段**的源时间,一次交给批量算子,它先归并、再从后往前拿,
    正好承接逐字稿分析节点产出的多个停顿、口头禅和重录区间。
    """
    from app.domain.sequences.operations import CutClipRanges, cut_clip_ranges

    sequence = _sequence_in(db, scope, str(config.get("sequence_id") or "").strip())
    clip_id = str(config.get("clip_id") or "").strip()
    if not clip_id:
        raise WorkflowDomainError("wfErr_cutNeedsClip")
    clip = db.get(Clip, clip_id)
    if clip is None or clip.sequence_id != sequence.id:
        raise WorkflowDomainError("wfErr_clipNotOnSequence")
    try:
        confidence_raw = config.get("min_confidence")
        ratio_raw = config.get("max_removal_ratio")
        min_confidence = float(0 if confidence_raw in (None, "") else confidence_raw)
        max_removal_ratio = float(1 if ratio_raw in (None, "") else ratio_raw)
    except (TypeError, ValueError) as exc:
        raise WorkflowDomainError("wfErr_ratioNumbers") from exc
    if not 0 <= min_confidence <= 1 or not 0 <= max_removal_ratio <= 1:
        raise WorkflowDomainError("wfErr_ratioRange")
    raw_ranges = config.get("ranges")
    if isinstance(raw_ranges, str):
        try:
            raw_ranges = json.loads(raw_ranges)
        except json.JSONDecodeError as exc:
            raise WorkflowDomainError("wfErr_rangesNotJson", params={"reason": exc}) from exc
    if not isinstance(raw_ranges, list):
        raise WorkflowDomainError("wfErr_rangesArray")

    ranges: list[tuple[float, float]] = []
    normalized: list[dict[str, Any]] = []
    confidences: list[float] = []
    for item in raw_ranges:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("src_start"))
            end = float(item.get("src_end"))
        except (TypeError, ValueError):
            continue
        try:
            confidence = float(item.get("confidence", 1))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(start) or not math.isfinite(end) or not math.isfinite(confidence):
            continue
        if confidence < min_confidence:
            continue
        start = max(start, clip.src_in)
        end = min(end, clip.src_out)
        if end <= start:
            continue
        ranges.append((start, end))
        normalized.append({**item, "src_start": start, "src_end": end})
        confidences.append(confidence)
    segments = _segments_in(config.get("segments")) if config.get("segments") else []
    if not ranges:
        return {
            "removed": 0,
            "removed_seconds": 0.0,
            "ranges": [],
            "skipped_ranges": [],
            "skipped_note": "",
            "kept_text": _kept_text(segments, []),
            "sequence_id": sequence.id,
            "revision": sequence.revision,
        }

    source_seconds = max(clip.src_out - clip.src_in, 0.001)
    kept, skipped = _within_cap(ranges, confidences, source_seconds * max_removal_ratio)
    ranges = [ranges[index] for index in kept]
    skipped_ranges = [normalized[index] for index in skipped]
    normalized = [normalized[index] for index in kept]
    merged = _merged_ranges(ranges)
    removed_seconds = sum(end - start for start, end in merged)
    if not ranges:
        return {
            "removed": 0,
            "removed_seconds": 0.0,
            "ranges": [],
            "skipped_ranges": skipped_ranges,
            "skipped_note": _skipped_note(skipped_ranges, max_removal_ratio),
            "kept_text": _kept_text(segments, []),
            "sequence_id": sequence.id,
            "revision": sequence.revision,
        }

    def cut(sequence: Sequence) -> int:
        cut_clip_ranges(db, sequence.id, CutClipRanges(clip_id=clip_id, ranges=tuple(ranges)))
        db.refresh(sequence)
        return sequence.revision

    revision = _write_timeline(db, scope, sequence.id, cut)
    return {
        "removed": len(ranges),
        "removed_seconds": round(removed_seconds, 3),
        "ranges": normalized,
        "skipped_ranges": skipped_ranges,
        "skipped_note": _skipped_note(skipped_ranges, max_removal_ratio),
        "kept_text": _kept_text(segments, merged),
        "sequence_id": sequence.id,
        "revision": revision,
    }


def _within_cap(ranges: list[tuple[float, float]], confidences: list[float], budget: float) -> tuple[list[int], list[int]]:
    """删除总时长超过上限时,**按置信度从高到低**收进范围,收到上限为止;放不下的交回去给人复核。

    此前超了上限就整步失败 —— 模型多标了几处低置信度的停顿,一处都不删、连带后面的导出一起没了。
    重叠的范围按合并之后的长度算,不重复计。返回(保留的下标, 放不下的下标),各按原顺序。
    """
    order = sorted(range(len(ranges)), key=lambda index: (-confidences[index], ranges[index][0]))
    kept: list[int] = []
    for index in order:
        trial = _merged_ranges([ranges[one] for one in (*kept, index)])
        if sum(end - start for start, end in trial) <= budget + 1e-9:
            kept.append(index)
    skipped = [index for index in range(len(ranges)) if index not in kept]
    return sorted(kept), skipped


def _skipped_note(skipped: list[dict[str, Any]], ratio: float) -> str:
    """超出删除上限、没有删的那几处:一句给人看的话(通知里用),没有就是空串。"""
    from app.core.i18n import get_current_locale, t

    if not skipped:
        return ""
    return t("wfNote_cleanupCapped", get_current_locale(), count=len(skipped), ratio=f"{ratio:.0%}")


def _kept_text(segments: list[dict[str, Any]], removed: list[tuple[float, float]]) -> str:
    """删掉这些范围之后,逐字稿还剩下什么 —— 按保留的原话拼出来,一个字不改。

    此前这份「整理后的逐字稿」由模型在方案里全文复述(cleaned_verbatim):长素材上输出一长就被截断,而且复述
    不保证一字不差。有词级时间的段按词判(词的中点落在删除范围里就去掉),没有的整段判(整段在删除范围里才去掉)。
    """
    def gone(start: float, end: float) -> bool:
        middle = (start + end) / 2
        return any(cut_start <= middle <= cut_end for cut_start, cut_end in removed)

    lines: list[str] = []
    for segment in segments:
        try:
            start, end = float(segment.get("start") or 0), float(segment.get("end") or 0)
        except (TypeError, ValueError):
            continue
        tokens = [one for one in segment.get("tokens") or [] if isinstance(one, dict)]
        touched = any(cut_start < end and cut_end > start for cut_start, cut_end in removed)
        if not touched:
            text = str(segment.get("text") or "").strip()
        elif tokens:
            words = [str(one.get("text") or "") for one in tokens
                     if not gone(float(one.get("start") or 0), float(one.get("end") or 0))]
            text = _join_words([word.strip() for word in words if word.strip()])
        else:
            text = "" if gone(start, end) else str(segment.get("text") or "").strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _join_words(words: list[str]) -> str:
    """词级 token 拼回一句:**按相邻两个 token 判**要不要空格 —— 前一个以西文字母、数字或西文标点收尾,后一个以
    西文字母或数字开头,中间才空一格(`hello world`、`AI, right`);中文逐字的 token 之间、中英交界处都不空。

    此前按整段判:中文段里只要夹着一个英文词,整段每个字之间都插了空格(「今 天 我 们 用 AI」)。

    **数字挨着数字不空**:SenseVoice 把「92」逐位给成「9」「2」两个 token,空一格就成了「9 2度」。
    """
    out = ""
    for word in words:
        if out and out[-1].isascii() and not out[-1].isspace() and out[-1] not in "([{'\"" \
                and word[0].isascii() and word[0].isalnum() and not (out[-1].isdigit() and word[0].isdigit()):
            out += " "
        out += word
    return out


def _merged_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _yes_no(config: dict[str, Any], key: str, *, default: bool) -> bool:
    """是/否型配置。**留空不是"否"** —— 它是"没设过",该落到节点自己的默认值上。

    节点声明里的 `default` 是给表单预选用的,不会写进 config(见 WorkflowsView 的 OptionPicker),
    所以执行体得自己兜住那一档;否则"默认开"的选项对每一条没动过它的工作流都是关的。
    """
    raw = str(config.get(key, "")).strip()
    return truthy(raw) if raw else default


def transcript_sentences(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """逐字稿段落(`{start, end, text, speaker, tokens}`)按剪辑台那一套切成一句一行,形状不变。"""
    from app.domain.voices.sentences import Segment, Token, sentences_for_editing

    parsed = [
        Segment(
            id=str(index),
            start_time=float(segment["start"]),
            end_time=float(segment["end"]),
            text=str(segment.get("text") or ""),
            speaker=str(segment.get("speaker") or "") or None,
            tokens=tuple(
                Token(start_time=float(token["start"]), end_time=float(token["end"]), text=str(token.get("text") or ""))
                for token in segment.get("tokens") or []
                if isinstance(token, dict)
            ),
        )
        for index, segment in enumerate(segments)
    ]
    return [
        {
            "start": row.start_time,
            "end": row.end_time,
            "text": row.text,
            "speaker": row.speaker or "",
            "tokens": [{"start": token.start_time, "end": token.end_time, "text": token.text} for token in row.tokens],
        }
        for row in sentences_for_editing(parsed)
    ]


def _segments_in(value: Any) -> list[dict[str, Any]]:
    """上游给的逐字稿段落。接列表,也接一串 JSON —— 手填时它只能是文本。"""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise WorkflowDomainError("wfErr_segmentsNotJson", params={"reason": exc}) from exc
    if not isinstance(value, list):
        raise WorkflowDomainError("wfErr_segmentsArray")
    return [item for item in value if isinstance(item, dict)]


def _field(item: dict[str, Any], path: str) -> Any:
    """按点号路径取嵌套字段(`append.timeline_start`),取不到就是空串 —— 与模板插值同一个约定。"""
    current: Any = item
    for part in path.split("."):
        if not isinstance(current, dict):
            return ""
        current = current.get(part, "")
    return current


def _clip_window(db: Session, sequence: Sequence, clip_id: str):
    """`clip_id` 给了就返回「素材时间 (起, 止) → 时间线 (起, 止)」的映射,落在片段用到的那一截之外的返回 None。"""
    if not clip_id:
        return None
    clip = db.get(Clip, clip_id)
    if clip is None or clip.sequence_id != sequence.id:
        raise WorkflowDomainError("wfErr_clipNotOnSequence")
    timeline_start, src_in, src_out, speed = clip.timeline_start, clip.src_in, clip.src_out, clip.speed or 1.0

    def mapped(start: float, end: float) -> tuple[float, float] | None:
        low, high = max(start, src_in), min(end, src_out)
        if high <= low:
            return None
        return timeline_start + (low - src_in) / speed, timeline_start + (high - src_in) / speed

    return mapped


def _subtitle_track(db: Session, sequence: Sequence, track_id: str) -> str:
    """字幕落到哪条轨:指定了就用它,没指定就用第一条字幕轨,一条都没有就新建。

    「没有就新建」不是省事,是这个节点在工作流里的常态 —— 上游 project_sequence_create 建出来的
    新时间线只有视频轨和音频轨,而逼用户先接一个「加轨道」节点,只是把机器能算的事推给人。
    """
    from app.domain.sequences.operations import AddTrack, add_track

    tracks = list(sequence.tracks or [])
    if track_id:
        track = next((one for one in tracks if one.id == track_id), None)
        if track is None:
            raise WorkflowDomainError("wfErr_trackNotOnSequence")
        if track.kind != "subtitle":
            raise WorkflowDomainError("wfErr_subtitlesOnSubtitleTrack")
        return track.id
    existing = [one for one in tracks if one.kind == "subtitle"]
    if existing:
        return min(existing, key=lambda one: one.position).id
    before = {one.id for one in tracks}
    add_track(db, sequence.id, AddTrack(kind="subtitle"))
    db.flush()
    db.refresh(sequence)
    created = next((one.id for one in (sequence.tracks or []) if one.id not in before), "")
    if not created:
        raise WorkflowDomainError("wfErr_subtitleTrackFailed")
    return created


@register("generate_subtitles")
def generate_subtitles(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """把逐字稿段落批量插成时间线上的字幕条。

    **时间码来自 segments,文本可以来自别处**:这正是"翻译后配字幕"需要的形状 —— 译文是逐条
    重写的,而每一条该出现在第几秒完全由原始段落决定。两者分成两个入参而不是让上游拼出一份
    新段落数组,是因为模板插值产出的是字符串:把译文塞回 JSON 里,遇到带引号的台词就散架。

    条数对不上直接报错,不截断。少一条就意味着从那一条起**每一句字幕都配错了时间**,而截断后
    的成片看起来是完整的 —— 那种错要等到有人从头看一遍才发现。
    """
    from app.domain.sequences.operations import GenerateSubtitles
    from app.domain.sequences.operations import generate_subtitles as generate

    sequence = _sequence_in(db, scope, str(config.get("sequence_id", "")).strip())
    segments = _segments_in(config.get("segments"))
    allow_empty = _yes_no(config, "allow_empty", default=False)
    nothing = {"track_id": "", "clip_ids": [], "count": 0, "sequence_id": sequence.id}
    if not segments:
        if allow_empty:
            return nothing
        raise WorkflowDomainError("wfErr_noSegments")
    lines = text_lines(config.get("texts"))
    start_field = str(config.get("start_field") or "start").strip()
    end_field = str(config.get("end_field") or "end").strip()
    text_field = str(config.get("text_field") or "text").strip()
    #: 交来的是转写引擎的原始段落(带词级时间戳)、又没有逐条译文时:按剪辑台那一套切成一句一行再铺。
    #: 此前直接拿引擎的段落当字幕,一条二三十秒、上百个字,和剪辑台上同一份逐字稿铺出来的不一样。
    #: 给了译文时不切 —— 译文是一段对一条的,切了就对不上;要逐句翻译就接转写节点的 sentences。
    if not lines and (start_field, end_field, text_field) == ("start", "end", "text") and segments and all(
        isinstance(segment.get("tokens"), list) for segment in segments
    ):
        segments = transcript_sentences(segments)
    if lines and len(lines) != len(segments):
        raise WorkflowDomainError("wfErr_linesSegmentsMismatch", params={"lines": len(lines), "segments": len(segments)})
    keep_original = _yes_no(config, "keep_original", default=False)
    try:
        offset = float(config.get("offset") or 0.0)
    except (TypeError, ValueError):
        raise WorkflowDomainError("wfErr_offsetSeconds") from None
    #: 字幕最晚到哪一秒(一般是这一段在时间线上的终点):素材比计划短、模型写的时间码超出这一段时,
    #: 不让字幕盖到下一段上。
    until = _seconds(config, "until", "generate_subtitles")
    #: 给了片段:段落的时间是**这段素材里**的时间,按片段的入点和倍速映射到时间线上,只留片段用到的那一截
    #: (和剪辑台的逐字稿投影同一个算法)。此前只能给一个平移量 —— 片段从素材中间开始、或者调过速,字幕就对不上嘴。
    clip_window = _clip_window(db, sequence, str(config.get("clip_id") or "").strip())
    cues: list[tuple[str, float, float]] = []
    for index, segment in enumerate(segments):
        # 起止**都**没有:这一段不上屏(整片生成里「这一镜没有口播」就是这样交过来的),跳过。
        # **只缺一头不是第 0 秒。** 此前空的 start 按 0 算:起点字段写错一个字,每一条字幕都从片头开始、
        # 一直挂到它的终点,叠成一摞,而节点照样成功。
        raw_start, raw_end = _field(segment, start_field), _field(segment, end_field)
        if raw_start in ("", None) and raw_end in ("", None):
            continue
        try:
            if raw_start in ("", None) or raw_end in ("", None):
                raise ValueError
            start, end = float(raw_start), float(raw_end)
        except (TypeError, ValueError):
            raise WorkflowDomainError("wfErr_segmentTimecode", params={"index": index + 1}) from None
        original = str(_field(segment, text_field) or "").strip()
        text = lines[index].strip() if lines else original
        if keep_original and lines and original and original != text:
            # 原文在上、译文在下 —— 和「字幕配音」的 line=last 正好配套:看两行,只念译文。
            text = f"{original}\n{text}"
        if clip_window is not None:
            mapped = clip_window(start, end)
            if mapped is None:
                continue
            begin, finish = mapped
        else:
            begin, finish = start + offset, end + offset
        if until is not None:
            finish = min(finish, until)
        if text and finish > begin:
            cues.append((text, begin, finish - begin))
    if not cues:
        if allow_empty:
            # 提前返回:连字幕轨都不建 —— 一条空轨挂在时间线上只会让人以为字幕丢了。
            return nothing
        raise WorkflowDomainError("wfErr_noUsableSegments")

    wanted_track = str(config.get("track_id", "")).strip()

    def write(sequence: Sequence) -> tuple[str, list[str]]:
        track_id = _subtitle_track(db, sequence, wanted_track)
        before = {clip.id for track in (sequence.tracks or []) for clip in (track.clips or [])}
        generate(db, sequence.id, GenerateSubtitles(track_id=track_id, cues=tuple(cues)))
        db.refresh(sequence)
        # 新插进去的那些。按落点排序 —— 下游要按时间顺序配音,而库里的返回顺序没有这个保证。
        created = sorted(
            (clip for track in (sequence.tracks or []) for clip in (track.clips or []) if clip.id not in before),
            key=lambda clip: clip.timeline_start,
        )
        return track_id, [clip.id for clip in created]

    sequence_id = sequence.id
    track_id, clip_ids = _write_timeline(db, scope, sequence_id, write)
    return {"track_id": track_id, "clip_ids": clip_ids, "count": len(clip_ids), "sequence_id": sequence_id}


@register("dub_subtitles")
def dub_subtitles(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """给这些字幕条配音,落到一条专门的配音轨。

    和「语音合成」的分工:那个念一段文本、交出一份音频素材,由谁摆到哪一秒是下游的事;这个念
    的是**已经在时间线上、各自带着时间码**的一批字幕,所以它自己知道每一条该落在第几秒,也
    因此才谈得上「把配音压进原段落的长度」—— match_duration 改的是片段的 speed,渲染时由
    atempo 变速(见 media/render_executor),无损、可撤销、事后还能在检查器里手动微调。
    """
    from app.core.i18n import get_current_locale, t
    from app.domain.voices.original_audio import DEFAULT_ORIGINAL_AUDIO
    from app.domain.voices.subtitle_dub import DEFAULT_MATCH_DURATION, DubError, start_subtitle_dub

    sequence = _sequence_in(db, scope, str(config.get("sequence_id", "")).strip())
    clip_ids = id_list(config.get("clip_ids"))
    if not clip_ids:
        # **空进空出。**「该不该为空」是上游说了算的:「生成字幕」默认 0 条就报错,选了
        # allow_empty(整片可能没有口播)才交出 0 条。此前这里再报一次「没有要配音的字幕条」,
        # 于是上游明说可以为空的那条流程,在下一步照样失败。什么都没配,原声就原样留着。
        return {
            "track_id": "",
            "done": 0,
            "failed": 0,
            "original_audio": "keep",
            "original_audio_note": t("dubOriginalAudio_keep", get_current_locale()),
            "overlaps": 0,
            "overlap_seconds": 0.0,
            "overlap_note": "",
        }

    synthesis = _speech_params(db, scope, config)
    try:
        job = start_subtitle_dub(
            db,
            sequence_id=sequence.id,
            clip_ids=clip_ids,
            match_duration=_yes_no(config, "match_duration", default=DEFAULT_MATCH_DURATION),
            line=str(config.get("line") or "all"),
            created_by=current_actor(db),
            synthesis=synthesis,
            original_audio=str(config.get("original_audio") or DEFAULT_ORIGINAL_AUDIO).strip().lower(),
        )
    except DubError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    final = wait_for_job(job.id, release=db)
    result = final.result or {}
    #: **实际**对原声做了什么(配音任务收尾时处理,见 voices/original_audio)。历史任务可能留有
    #: mute_fallback；新任务对用户明确选择的 separate 不再静默降级。
    applied = str(result.get("original_audio") or "keep")
    #: 1.5 倍速也念不完、压到下一句上的那几句(见 voices/subtitle_dub):完成通知里如实说,不让人在成片里自己听出来。
    overlaps = int(result.get("overlaps") or 0)
    overlap_seconds = float(result.get("overlap_seconds") or 0.0)
    return {
        "track_id": str(result.get("track_id") or ""),
        "done": int(result.get("done") or 0),
        "failed": int(result.get("failed") or 0),
        "original_audio": applied,
        "original_audio_note": t(f"dubOriginalAudio_{applied}", get_current_locale()),
        "overlaps": overlaps,
        "overlap_seconds": overlap_seconds,
        "overlap_note": t("dubOverlapNote", get_current_locale(), overlaps=overlaps, seconds=f"{overlap_seconds:.1f}")
        if overlaps else "",
    }


@register_preflight("dub_subtitles")
def dub_subtitles_preflight(db: Session, config: dict[str, Any], actor: str | None, _node: PreflightNode) -> None:
    """选了「只去掉人声」就先问有没有分离能力 —— 在转写、付费翻译、逐句配音之前。

    此前这句只在配音节点开始时问(start_subtitle_dub):译配模板里它排在翻译之后,翻译的钱花完才说做不了。
    判据和配音那一步同一个(ensure_original_audio_mode,按跑的人挑提供方)。
    """
    from app.domain.voices.original_audio import DEFAULT_ORIGINAL_AUDIO, OriginalAudioError, ensure_original_audio_mode

    mode = str(config.get("original_audio") or DEFAULT_ORIGINAL_AUDIO).strip().lower()
    try:
        ensure_original_audio_mode(mode, owner_user_id=actor)
    except OriginalAudioError as exc:
        raise WorkflowDomainError.from_error(exc) from exc


@register("separate_audio")
def separate_audio_node(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """把一份素材拆成人声 + 背景音两份新素材。

    **节点不认识任何引擎** —— 它只跟 domain.separation 说话,由注册表决定这次用哪个
    Adapter(ADR-0016)。所以加一个引擎不用改这里。

    **排成子任务再等它**,和转写、导出同一条路:此前在节点线程里直接跑模型,绕开了界面那条
    路占的 RENDER_SLOTS(循环里并行几个就一起把模型拉进内存),等待期间也一直攥着引擎的
    连接预算(见 wait_for_job)。
    """
    from app.ai.providers.contracts.separation import SeparationError
    from app.domain.assets.separation import start_separation_job

    #: **收进工作区**,不是直接 db.get —— asset_id 常常来自上游节点,少了这一条,
    #: A 工作区的工作流能拆 B 工作区的素材,而产出的两份 stem 是要返回到工作流输出里的。
    asset = _asset_in(db, scope, str(config.get("asset_id") or "").strip())
    try:
        child = start_separation_job(
            db, asset=asset, created_by=current_actor(db), engine=str(config.get("engine") or "")
        )
    except SeparationError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    result = wait_for_job(child.id, release=db).result or {}
    return {
        "vocals_asset_id": str(result.get("vocals_asset_id") or ""),
        "background_asset_id": str(result.get("background_asset_id") or ""),
        "engine": str(result.get("engine") or ""),
    }


@register("denoise_audio")
def denoise_audio_node(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """降噪,产出一份新素材。节点不认识任何引擎,只跟 domain.denoise 说话(ADR-0017)。

    排成子任务再等它,理由同分离节点。
    """
    from app.ai.providers.contracts.denoise import DenoiseError
    from app.domain.assets.denoise import start_denoise_job

    # 收进工作区(同分离节点):asset_id 常常来自上游,不能让一个工作区的流程动另一个工作区的素材。
    asset = _asset_in(db, scope, str(config.get("asset_id") or "").strip())
    try:
        child = start_denoise_job(
            db,
            asset=asset,
            created_by=current_actor(db),
            engine=str(config.get("engine") or ""),
            strength=str(config.get("strength") or ""),
        )
    except DenoiseError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    result = wait_for_job(child.id, release=db).result or {}
    return {"asset_id": str(result.get("asset_id") or ""), "engine": str(result.get("engine") or "")}


@register("asset")
def asset_node(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """指向一份素材,把它的 id 交给下游。

    **它不做任何事**,存在的意义是让「这条流程从这份素材开始」在画布上有一个说法 ——
    否则下游节点的 asset_id 只能手填一个 32 位十六进制,而那个 id 从哪来、指的是哪个文件,
    图上完全看不出来。

    拖一个文件到画布上就会得到它(文件先进素材库,再落成这个节点)。
    """
    asset_id = str(config.get("asset_id", "")).strip()
    if not asset_id:
        raise WorkflowDomainError("wfErr_assetNodeEmpty")
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != scope.workspace_id:
        raise WorkflowDomainError("wfErr_assetNotInWorkspace")
    media_info = asset.media_info or {}

    def number(name: str) -> float | None:
        """素材自己的那个数;**不知道就是 None**。

        此前缺了就交 1920×1080、30fps、0 秒 —— 音频本来就没有画面尺寸,探测失败的视频什么都
        没有,而下游拿着编出来的数建项目、放时间线(0 秒的结尾点直接把片段放没了)。缺省是
        下游各自的事:建项目有它的画布缺省,放上时间线会去读素材真实的时长。
        """
        value = media_info.get(name)
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    width, height = number("width"), number("height")
    return {
        "asset_id": asset.id,
        "name": asset.name,
        "kind": asset.kind,
        "duration": number("duration"),
        "width": int(width) if width is not None else None,
        "height": int(height) if height is not None else None,
        "fps": number("fps"),
    }
