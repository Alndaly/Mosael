"""画板上的四个动作:生成、写字、念出来、截一段。产出都落回画布上的那一格。

它们是四个内置产出者(Producer)的本体;入口只有一个 —— boards.producers.run(ADR 0021)。
表单上写明是哪个产出者(`form.producer`),界面据此挂面板,不再按种类猜。

此前它们整个写在路由里 —— 拼提示词、调模型、摊平素材、查版本冲突,路由成了第二个领域层,
而画板的第二个入口(智能体、工作流)想做同样的事就得再抄一遍。现在路由只认人、翻错误。

**都不自己实现能力**:生成走 create_generation_job,念字走 voices.start_synthesis,截取走
boards.trim,写字走 ai_chat —— 描述符校验、计量记账、任务中心全都白拿。画板只多做自己那件事:
先在画布上摆一个「正在做」的占位,再让回执把产出填回那一格。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Board
from app.domain.boards.canvas import (
    BoardDomainError,
    ensure_revision,
    get_board,
    item_not_found,
    live_job,
    place_pending,
    receipt_to_item,
)
from app.domain.jobs import create_job, reset_receipt, run_job_inline, set_receipt


class BoardInputError(BoardDomainError):
    """请求本身说不通(没写要求、素材不在这个工作区)。"""


@dataclass(frozen=True)
class Slot:
    """产出落在画布上的哪一格。已经在画布上的那一格会就地更新(位置归用户)。"""

    board_id: str
    item_id: str
    x: float
    y: float
    base_revision: int | None = None


def _ensure_slot_ready(db: Session, workspace_id: str, slot: Slot) -> None:
    """起任务之前问两件事:调用方看到的是不是最新的这张板;这一格是不是已经有一个任务在跑。

    两件都要在**建任务之前**问 —— 之后才发现的话,钱已经花了。一格同一时刻只有一个任务:
    第二次点生成时第一轮还在跑,放过去就是第二份钱,而第一轮的回执回来时照样填进这一格。
    """
    board = get_board(db, workspace_id, slot.board_id)
    ensure_revision(board, slot.base_revision)
    item = next((one for one in (board.canvas or {}).get("items", []) if one.get("id") == slot.item_id), None)
    if live_job(item):
        raise BoardInputError("boardErr_itemBusy")


def _pending(db: Session, workspace_id: str, slot: Slot, *, actor_id: str, kind: str, producer: str,
             form: dict[str, Any], job_id: str, ability: bool = False) -> Board:
    """摆「正在做」的占位。表单末尾写上**是哪个产出者做的** —— 跑挂了回来,面板照它挂、照它重试。

    `ability`:这一轮跑的是宿主的一项**能力**(转写、翻译……,见 boards.transforms 的 `ability`)。宿主自己的
    产出者不换 —— `form` 是那一项的设置,存进宿主的 `form.abilities[producer]`;这一轮是哪一项记在
    `run.ability` 上(回执照它把产出新建在右边,界面照它说「转写中」)。
    """
    if ability:
        return place_pending(
            db,
            workspace_id=workspace_id,
            board_id=slot.board_id,
            item={"id": slot.item_id, "kind": kind, "x": slot.x, "y": slot.y,
                  "run": {"status": "running", "job_id": job_id, "ability": producer}},
            actor_id=actor_id,
            ability=(producer, {key: value for key, value in form.items() if key != "producer"}),
        )
    return place_pending(
        db,
        workspace_id=workspace_id,
        board_id=slot.board_id,
        item={
            "id": slot.item_id,
            "kind": kind,
            "x": slot.x,
            "y": slot.y,
            #: 排在最后、覆盖调用方带来的那个 —— 这一轮是谁做的由这里说了算;位置固定,前端按
            #: JSON 比对表单时不会因为键的先后误以为「表单变了」。
            "form": {**{key: value for key, value in form.items() if key != "producer"}, "producer": producer},
            "run": {"status": "running", "job_id": job_id},
        },
        actor_id=actor_id,
    )


def upstream_entities(board: Board, item_id: str) -> list[str]:
    """连进这一格的资产格引用的资产(ADR 0027),按连线的先后。

    **连进来就等于 `@` 了它**:生成时和正文里 `@` 的资产走同一条路(domain/entities/mentions)——
    拼进它的提示词描述、按模型收得下的张数挂它的参考图。还没挑资产的资产格(没有 entity_id)跳过。
    """
    canvas = board.canvas or {}
    items = {str(one.get("id")): one for one in canvas.get("items") or [] if isinstance(one, dict)}
    out: list[str] = []
    for edge in canvas.get("edges") or []:
        if not isinstance(edge, dict) or edge.get("target") != item_id:
            continue
        source = items.get(str(edge.get("source")))
        entity_id = str((source or {}).get("entity_id") or "") if (source or {}).get("kind") == "entity" else ""
        if entity_id and entity_id not in out:
            out.append(entity_id)
    return out


def upstream_scene(board: Board, item_id: str) -> str | None:
    """连进这一格的 3D 场景格给的场景(ADR 0029 §2),按连线的先后取第一个。还没搭出场景的空场景格跳过。

    **连进来的是场景,不是一张图**:生成时现渲它的一个镜头当参考(见 generation.create_generation_job)。
    """
    canvas = board.canvas or {}
    items = {str(one.get("id")): one for one in canvas.get("items") or [] if isinstance(one, dict)}
    for edge in canvas.get("edges") or []:
        if not isinstance(edge, dict) or edge.get("target") != item_id:
            continue
        source = items.get(str(edge.get("source"))) or {}
        if source.get("kind") == "scene" and source.get("scene_id"):
            return str(source["scene_id"])
    return None


def generate_on_board(
    db: Session,
    *,
    workspace_id: str,
    slot: Slot,
    actor_id: str,
    kind: str,
    prompt: str,
    provider: str,
    provider_profile_id: str,
    model: str,
    parameters: dict[str, Any],
    source_assets: list[dict[str, Any]],
    form: dict[str, Any],
    entity_ids: list[str] | None = None,
    scene_reference: dict[str, str] | None = None,
) -> Board:
    """在画板上出图出片。没点名模型时由漏斗用这个人的默认。

    `entity_ids` 是正文里 `@` 到的资产;连进这一格的资产格在这里并进去(upstream_entities),
    之后两者是同一样东西。连进这一格的 3D 场景格(upstream_scene)按 `scene_reference`(镜头、用法)现渲成参考。

    **顺序**:建任务 → 摆占位 → 起任务。起在占位之前的话,一个当场失败的生成会把回执送到一格
    还不存在的地方。生成的错误(GenerationDomainError)原样抛出。
    """
    from app.domain.generation import create_generation_job
    from app.domain.generation.operations import parse_source_assets
    from app.domain.generation.runner import start_generation_thread

    _ensure_slot_ready(db, workspace_id, slot)
    board = get_board(db, workspace_id, slot.board_id)
    mentioned = list(dict.fromkeys([*(entity_ids or []), *upstream_entities(board, slot.item_id)]))
    scene_id = upstream_scene(board, slot.item_id)
    reference = {**(scene_reference or {}), "scene_id": scene_id} if scene_id else None
    token = set_receipt(receipt_to_item(slot.board_id, slot.item_id))
    try:
        generation, job = create_generation_job(
            db,
            workspace_id=workspace_id,
            session_id=None,
            project_id=None,
            created_by=actor_id,
            provider=provider,
            provider_profile_id=provider_profile_id.strip() or None,
            model=model,
            kind=kind,
            prompt=prompt,
            negative_prompt="",
            parameters=dict(parameters),
            source_assets=parse_source_assets(source_assets, kind=kind),
            entity_ids=mentioned,
            scene_reference=reference,
        )
    finally:
        reset_receipt(token)
    board = _pending(
        db, workspace_id, slot, actor_id=actor_id, kind=kind, producer="generate", job_id=job.id,
        form={
            **form,
            # 只存用户写的那句提示词;运行时追加的图例不该覆盖它。
            "prompt": str(form.get("prompt") or prompt),
            "provider": generation.provider,
            "provider_profile_id": generation.provider_profile_id,
            "model": generation.model,
            "parameters": dict(parameters),
            #: 表单里的是**槽位**那一半;正文里 @ 到的那几份记在 mentioned_asset_ids 上,运行时才
            #: 并进发出去的清单。把合并后的清单写回来,重试时 @ 过的素材就挂进了槽位 —— 正文里删掉
            #: 那个 @ 它照样被发出去。只有调用方没给表单(智能体、脚本)时,才拿发出去的那份当槽位。
            "source_assets": list(form["source_assets"] if "source_assets" in form else source_assets),
            #: 正文里 @ 到的资产(不含连进来的资产格 —— 那由连线说,线在它就在)。
            **({"mentioned_entity_ids": list(form.get("mentioned_entity_ids") or entity_ids or [])}
               if form.get("mentioned_entity_ids") or entity_ids else {}),
        },
    )
    start_generation_thread(generation.id)
    return board


def speak_on_board(
    db: Session,
    *,
    workspace_id: str,
    slot: Slot,
    actor_id: str,
    text: str,
    synthesis: dict[str, Any],
    voice_id: str | None,
    engine: str = "",
    engine_voice: str = "",
) -> Board:
    """把一段文字念成音频。合成的错误(VoiceError)原样抛出。

    回执打在上下文里,start_synthesis 建的任务自动带上 —— 不用把画板的概念塞进 voices 领域。

    节点表单记下**这一次用哪把嗓子**:克隆音色是 voice_id,引擎音色是 engine + engine_voice
    (和面板存的是同一个形状)。只记 voice_id 的话,引擎那条路跑挂了回来重试,面板落回第一个
    引擎,用户挑好的发音人没了。
    """
    from app.domain.voices.voices import start_synthesis

    _ensure_slot_ready(db, workspace_id, slot)
    text = text.strip()
    if not text:
        raise BoardInputError("boardErr_nothingToSpeak")
    token = set_receipt(receipt_to_item(slot.board_id, slot.item_id))
    try:
        job = start_synthesis(db, text=text, project_id=None, created_by=actor_id, **synthesis)
    finally:
        reset_receipt(token)
    return _pending(db, workspace_id, slot, actor_id=actor_id, kind="audio", producer="speak", job_id=job.id,
                    form={"prompt": text, "voice_id": voice_id or "", "engine": engine, "engine_voice": engine_voice})


def trim_on_board(
    db: Session,
    *,
    workspace_id: str,
    slot: Slot,
    actor_id: str,
    asset_id: str,
    start: float,
    end: float,
    mute: bool,
) -> Board:
    """截出一段,产出一份新素材(原素材不动)。截取的错误(TrimError)原样抛出。

    `slot` 可以是新的一格(从一段片子上截),也可以是一格截挂了的(照它表单上记的再截一次)。
    """
    from app.db.models import Asset
    from app.domain.boards.trim import start_trim

    _ensure_slot_ready(db, workspace_id, slot)
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != workspace_id:
        raise BoardInputError("boardErr_assetNotInWorkspace")
    token = set_receipt(receipt_to_item(slot.board_id, slot.item_id))
    try:
        job = start_trim(db, asset=asset, start=start, end=end, mute=mute, created_by=actor_id)
    finally:
        reset_receipt(token)
    #: 表单记下**截的是哪一份、哪一段**(见 canvas._normalize_trim):截挂了回来,这一格挂的是
    #: 截取面板、范围原样还在,重试就地再截一次 —— 而不是一块对着空提示词的生成面板。
    return _pending(db, workspace_id, slot, actor_id=actor_id, kind=asset.kind, producer="trim", job_id=job.id,
                    form={"trim": {"asset_id": asset.id, "start": start, "end": end, "mute": mute}})


#: 写字等模型多久。缺省的 60 秒(ai_chat.DEFAULT_TIMEOUT_SECONDS)写一段便签还行;看着几张图写一整篇文档,
#: 推理型模型、走 OAuth 网关的常常要两三分钟 —— 60 秒一到就断,用户看到的是「Gateway 调用超过 60 秒未返回」,
#: 而模型那边其实还在写。工作流的 LLM 节点同一个道理放宽到了 120 秒。
WRITE_TIMEOUT_SECONDS = {"note": 120.0, "document": 240.0}

#: 一次写字最多带上几个资产、每个资产挑几张参考图给模型看。图多了模型抓不住重点,也贵。
WRITE_MAX_ENTITIES = 8
WRITE_IMAGES_PER_ENTITY = 2


def _entity_materials(db: Session, workspace_id: str, entity_ids: list[str]) -> tuple[list[str], list[str]]:
    """点名的资产 → (给模型读的材料, 给模型看的图)。和生成里的 `@资产` 同一份画像(entities.generation_profile):
    名字(变体带母体)、提示词描述、按挑图先后排的图片参考图,这里只取前几张。"""
    from app.core.i18n import get_current_locale, t
    from app.domain.entities import generation_profile
    from app.domain.entities.mentions import resolve_mentions

    materials: list[str] = []
    pictures: list[str] = []
    for entity in resolve_mentions(db, workspace_id, entity_ids[:WRITE_MAX_ENTITIES]):
        name, descriptor, images = generation_profile(db, entity)
        kind = t(f"entityKind_{entity.kind}", get_current_locale())
        about = "\n".join(part for part in (entity.description.strip(), descriptor) if part)
        materials.append(f"资产「{name}」({kind})" + (f":\n{about}" if about else ""))
        pictures.extend(one for one in images[:WRITE_IMAGES_PER_ENTITY] if one not in pictures)
    return materials, pictures


def write_on_board(
    db: Session,
    *,
    workspace_id: str,
    board_id: str,
    item_id: str,
    actor_id: str,
    prompt: str,
    provider_profile_id: str,
    model: str,
    source_asset_ids: list[str],
    context: list[str],
    entity_ids: list[str] | None = None,
    base_revision: int | None = None,
) -> Board:
    """让 AI 往一张便签里写字,或者在文档格上写一篇笔记。模型的错误(AiChatError)在把失败落进那一格之后原样抛出。

    **同步返回,但照样是一个任务。** 写字几秒就回,调用方等着结果;可「这一格在写」这件事
    得由任务总线收尾 —— 此前运行态是这里手写的两笔(开始写 running、AiChatError 时写 failed),
    别的异常(读素材炸了、记账出错、写回撞了什么)一概漏过去,便签在服务端一直停在「写作中」,
    只等下一次客户端自动保存碰巧把它盖掉。现在和生成/念/截同一套:建任务 → 摆占位 → 跑 →
    回执把正文(或失败原因)落回这一格。任务在调用方线程里跑完(见 jobs.run_job_inline),
    任何异常都先落成失败再抛出;进程中途没了,重启时 reconcile 收掉。

    **看着什么写**:上游连过来的和正文里 `@` 到的素材(图片、视频给画面,音频给转写,见 look_at)、上游便签的字、
    以及连进来的和 `@` 到的**资产**(ADR 0027)—— 它的描述当材料,前几张参考图给模型看。

    **文档格**:写出来的是一篇笔记。空的文档格新建一篇、引用它;已经引用着一篇的,那一篇就是「现有内容」,
    写成它的**新一版**(笔记的每一版都留着,改坏了能退回),文档格改钉到新的那一版。

    **也不自己实现「调 LLM」**:供应商解析、调用、计量和工作流的 LLM 节点、智能体是同三样东西。
    """
    from app.domain.ai_chat import AiChatError, chat, target_for
    from app.domain.providers import require_connection
    from app.domain.usage import billable, once

    prompt = prompt.strip()
    if not prompt:
        raise BoardInputError("boardErr_writeNeedsPrompt")

    #: 这一格上已经有的字。**从画布上读,不让前端拼进提示词** —— 拼在前端意味着「现在写的是
    #: 什么」和「要求是什么」揉成了一段。有字就是**改写**,没字才是从头写。文档格的「字」是它引用的那篇笔记。
    slot_item = _slot_item(db, workspace_id, board_id, item_id)
    kind = "document" if slot_item.get("kind") == "document" else "note"
    note_id = str(slot_item.get("note_id") or "") if kind == "document" else ""
    if note_id:
        from app.domain.notes import get_note

        existing = get_note(db, workspace_id, note_id).markdown.strip()
    else:
        existing = str(slot_item.get("text") or "").strip() if kind == "note" else ""
    _ensure_slot_ready(db, workspace_id, Slot(board_id, item_id, 0, 0, base_revision))
    #: 连进来的资产格 + 正文里 @ 到的,和生成同一条路(upstream_entities)。在建任务之前取:点名的资产不在
    #: 这个工作区就当场说,不起任务。
    board = get_board(db, workspace_id, board_id)
    named = list(dict.fromkeys([*upstream_entities(board, item_id), *(entity_ids or [])]))
    entity_texts, entity_pictures = _entity_materials(db, workspace_id, named)

    token = set_receipt(receipt_to_item(board_id, item_id))
    try:
        job = create_job(
            db,
            workspace_id=workspace_id,
            kind="board_write",
            created_by=actor_id,
            payload={"board_id": board_id, "item_id": item_id, "subject": prompt[:80]},
            message="jobMsg_boardWriteQueued",
        )
    finally:
        reset_receipt(token)
    db.commit()
    _pending(
        db, workspace_id, Slot(board_id, item_id, 0, 0), actor_id=actor_id, kind=kind, producer="write", job_id=job.id,
        #: 表单记下**这一轮**用的要求和模型 —— 写挂了回来,面板上原样还在,改一个字就能重来。
        form={**(slot_item.get("form") or {}), "prompt": prompt,
              "provider_profile_id": provider_profile_id, "model": model},
    )
    target_name = "这篇文档" if kind == "document" else "这张便签"

    def write() -> dict[str, Any]:
        #: 上游连过来的 + 正文里 @ 到的 + 资产的参考图。图片和视频给画面,音频给转写 —— 见 look_at。
        seen = list(dict.fromkeys([*source_asset_ids, *entity_pictures]))
        pictures, from_assets = look_at(db, workspace_id, seen)
        materials = [one.strip() for one in context if one and one.strip()] + entity_texts + from_assets
        profile = require_connection(db, provider_profile_id or None, user_id=actor_id, error=AiChatError)
        target = target_for(db, profile, model=model, surface="automation")
        #: 说清楚产物要直接摆出来 —— 不交代的话模型爱写「好的,这是您要的文案:」,而那句话会原样贴进去。
        system = (
            "你在帮用户写一篇文档,它会存成一篇笔记:可以用 Markdown 的标题、列表、表格组织内容。"
            "直接给正文,不要开场白、不要解释、不要用代码块把整篇包起来。"
            if kind == "document"
            else "你在帮用户往一张创意画板的便签上写字。直接给正文,不要开场白、不要解释、不要用 Markdown 代码块包起来。"
        )
        if existing:
            system += f"{target_name}上已经有内容,用户给的是**改法**:照他说的改,没提到的地方保持原样,整篇重写一遍不是他要的。"
        with billable(
            db,
            capability="chat",
            operation="board_write",
            idempotency_key=once("board_write"),
            workspace_id=workspace_id,
            provider=target.vendor,
            model=target.model,
            provider_profile_id=profile.id,
            source_type="board",
            source_id=board_id,
        ) as call:
            text = chat(
                target,
                [
                    {"role": "system", "content": system},
                    *(
                        #: 上游给的材料(便签的字、资产的描述、素材的转写),自成一轮。**和「要求」分开** ——
                        #: 揉成一段的话,模型分不清哪句是素材、哪句是指令,常见的结果是把材料原样抄一遍。
                        [
                            {
                                "role": "user",
                                "content": "上游给的材料:\n\n" + "\n\n---\n\n".join(materials),
                            }
                        ]
                        if materials
                        else []
                    ),
                    *(
                        #: 现有内容单独一轮,和要求分开 —— 揉成一段的话,模型会把「改短一点」
                        #: 当成正文的一部分写进去。
                        [{"role": "user", "content": f"{target_name}现在的内容:\n{existing}"}]
                        if existing
                        else []
                    ),
                    #: 有图就让模型**看着写**。图片和要求放在同一轮里 —— 分开发的话模型
                    #: 不知道这句话说的是哪张图。
                    {"role": "user", "content": [{"type": "text", "text": prompt}, *pictures] if pictures else prompt},
                ],
                temperature=0.7,
                call=call,
                label="画板写文档" if kind == "document" else "画板写文案",
                timeout=WRITE_TIMEOUT_SECONDS[kind],
            ).strip()
        if kind == "document":
            return {"outputs": [_write_note(db, workspace_id, board, note_id, text)]}
        return {"text": text}

    run_job_inline(db, job, write, running="jobMsg_boardWriteRunning", done="jobMsg_boardWriteDone")
    db.expire_all()
    return get_board(db, workspace_id, board_id)


def _note_title(markdown: str) -> str:
    """新笔记的标题:正文第一个标题;没有就是第一行,截短。"""
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    heading = next((line.lstrip("#").strip() for line in lines if line.startswith("#")), "")
    title = heading or (lines[0] if lines else "")
    return title[:60]


def _write_note(db: Session, workspace_id: str, board: Board, note_id: str, markdown: str) -> dict[str, Any]:
    """文档格写出来的正文落成笔记:引用着一篇的写成它的新一版,空的新建一篇(来源记上这张画板)。
    交回一份 `note` 产出,回执据此把文档格钉到这一版(canvas.outputs_of)。"""
    from app.domain.note_types import NoteContent
    from app.domain.notes import create_note, get_note, save_note, snapshot

    if note_id:
        note = get_note(db, workspace_id, note_id)
        note = save_note(db, workspace_id, note_id, note.revision,
                         NoteContent.model_validate({**snapshot(note), "markdown": markdown}))
    else:
        note = create_note(db, workspace_id, NoteContent.model_validate({
            "title": _note_title(markdown),
            "markdown": markdown,
            "sources": [{"kind": "board", "id": board.id, "label": board.name, "quote": ""}],
        }))
    return {"type": "note", "note_id": note.id, "revision": note.revision, "title": note.title}


def _slot_item(db: Session, workspace_id: str, board_id: str, item_id: str) -> dict[str, Any]:
    """画布上的那一格;不在就说清楚。"""
    board = get_board(db, workspace_id, board_id)
    item = next((one for one in (board.canvas or {}).get("items", []) if one.get("id") == item_id), None)
    if item is None:
        raise item_not_found(item_id)
    return item


def look_at(db: Session, workspace_id: str, asset_ids: list[str]) -> tuple[list[dict], list[str]]:
    """把上游素材摊成模型看得懂的东西:**画面**和**能读的文字**。

    三种素材三条路,而它们本来就不一样:

     · 图片 —— 直接就是一帧画面。
     · 视频 —— 抽帧。**在这一次调用里抽**,不是先跑一遍 analyze_asset 再把结论喂进来:
       那样要多花一次模型调用和几秒钟,而模型本来就能直接看这几帧。抽帧用
       analysis.service 那份(自适应帧数、单次 ffmpeg),不自己再写一遍。
     · 音频 —— 没有画面可看,能给的是**转写**。没转写过就跳过 —— 在这里顺手起一个 ASR
       任务的话,一次「写句文案」会变成一次要等的后台作业,而用户并没有要求那件事。

    返回 (画面段, 文字材料)。
    """
    from app.db.models import Asset
    from app.domain.analysis import service as analysis
    from app.domain.analysis.service import AnalysisError, image_part
    from app.media.image_preview import browser_compatible_image
    from app.media.paths import resolve_key

    parts: list[dict] = []
    materials: list[str] = []
    for asset_id in asset_ids[:8]:  # 一次带太多既贵又容易超上下文
        asset = db.get(Asset, str(asset_id))
        if asset is None or asset.workspace_id != workspace_id or not asset.file_key:
            continue
        path = resolve_key(asset.file_key)
        if not path.is_file():
            continue

        if asset.kind == "image":
            # 与素材分析、聊天附件共用同一条格式 Seam：HEIC 等容器先转成派生 JPEG，
            # WebP/AVIF 等浏览器原生格式则保留原字节和真实 MIME。不能只改 data URI 标签，
            # 否则会把 HEIC 原字节伪装成 JPEG 交给模型。
            compatible = browser_compatible_image(path, path.parent)
            if compatible is None:
                # 一份坏图不该让整次写作失败；与视频抽帧失败保持相同的尽力而为语义。
                continue
            image_path, image_mime = compatible
            parts.append(image_part(image_path.read_bytes(), image_mime))
        elif asset.kind == "video":
            try:
                parts.extend(image_part(frame) for frame in analysis.extract_video_frames(path))
            except AnalysisError:
                # 抽不出帧不该让整次「写文案」失败 —— 少一段素材,总比一句都写不出来好。
                continue
        elif asset.kind == "audio":
            spoken = analysis.asset_transcript_text(db, asset.id)
            if spoken:
                materials.append(f"【{asset.name} 的语音转写】\n{spoken}")
    return parts, materials
