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

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from app.domain.generation.operations import ReferenceDocument

logger = logging.getLogger(__name__)


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
             form: dict[str, Any], job_id: str, ability: bool = False, outputs: int = 1) -> Board:
    """摆「正在做」的占位。表单末尾写上**是哪个产出者做的** —— 跑挂了回来,面板照它挂、照它重试。

    `ability`:这一轮跑的是宿主的一项**能力**(转写、翻译……,见 boards.transforms 的 `ability`)。宿主自己的
    产出者不换 —— `form` 是那一项的设置,存进宿主的 `form.abilities[producer]`;这一轮是哪一项记在
    `run.ability` 上(回执照它把产出新建在右边,界面照它说「转写中」)。

    `outputs`:这一轮会交回几份 —— 就地落的那一格之外,其余几份的占位一起摆在右边(见 receipts.place_pending)。
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
        outputs=outputs,
    )


def upstream_cells(board: Board, item_id: str) -> list[dict[str, Any]]:
    """连进这一格的各格,按连线的先后;同一格连了两根线也只算一次。

    画板上「按连线取上游」都从这里走 —— 生成、写字、一项能力的绑定读的是同一份先后。「谁先连进来」是用户
    看得见、改得动的顺序,各处自己再遍历一遍连线的话,迟早有一处的先后、去重和别处不一样。
    """
    canvas = board.canvas or {}
    items = {str(one.get("id")): one for one in canvas.get("items") or [] if isinstance(one, dict)}
    out: dict[str, dict[str, Any]] = {}
    for edge in canvas.get("edges") or []:
        if not isinstance(edge, dict) or edge.get("target") != item_id:
            continue
        source_id = str(edge.get("source"))
        if source_id in items and source_id not in out:
            out[source_id] = items[source_id]
    return list(out.values())


def upstream_entities(board: Board, item_id: str) -> list[str]:
    """连进这一格的资产格引用的资产(ADR 0027),按连线的先后。

    **连进来就等于 `@` 了它**:生成时和正文里 `@` 的资产走同一条路(domain/entities/mentions)——
    拼进它的提示词描述、按模型收得下的张数挂它的参考图。还没挑资产的资产格(没有 entity_id)跳过。
    """
    return list(dict.fromkeys(
        str(cell["entity_id"]) for cell in upstream_cells(board, item_id)
        if cell.get("kind") == "entity" and cell.get("entity_id")
    ))


def upstream_scene(board: Board, item_id: str) -> str | None:
    """连进这一格的 3D 场景格给的场景(ADR 0029 §2),按连线的先后取第一个。还没搭出场景的空场景格跳过。

    **连进来的是场景,不是一张图**:生成时现渲它的一个镜头当参考(见 generation.create_generation_job)。
    """
    return next((str(cell["scene_id"]) for cell in upstream_cells(board, item_id)
                 if cell.get("kind") == "scene" and cell.get("scene_id")), None)


def document_cell(db: Session, workspace_id: str, item: dict[str, Any]) -> ReferenceDocument | None:
    """一格文档格给出的那一篇(ADR 0031):引用笔记的给**钉住的那一版**(和画布上看到的一致,不是最新版),
    引用文档素材的给解析出的全文,标题是素材名去掉扩展名(和文档格上显示的一致)。

    还没挑文档、素材还没解析好(或解析没成)回 None;引用的笔记进了回收站、那一版没了,notes 的错误原样抛出。
    """
    from app.domain.generation.operations import ReferenceDocument

    if item.get("note_id"):
        from app.domain.notes import read_reference

        ref = read_reference(db, workspace_id, str(item["note_id"]), item.get("note_revision"))
        return ReferenceDocument(title=str(ref["title"]), markdown=str(ref["markdown"]))
    if item.get("asset_id"):
        from app.db.models import Asset
        from app.domain.documents.reading import document_text

        markdown = document_text(db, workspace_id, str(item["asset_id"]))
        asset = db.get(Asset, str(item["asset_id"]))
        if markdown is None or asset is None:
            return None
        return ReferenceDocument(title=asset.name.rsplit(".", 1)[0], markdown=markdown)
    return None


def _upstream_document(db: Session, workspace_id: str, cell: dict[str, Any]) -> ReferenceDocument:
    """连进来的一格文档格给的那一篇;**读不到就拒绝**(BoardInputError)。

    一篇连着却读不到的文档悄悄跳过,产出少一块素材,用户无从知道 —— 面板上同样拦着(documentBlocked)。
    """
    from app.domain.notes import NoteDomainError

    try:
        document = document_cell(db, workspace_id, cell)
    except NoteDomainError as exc:
        raise BoardInputError.relay(exc) from exc
    if document is None:
        raise BoardInputError("boardErr_upstreamDocumentUnreadable", name=str(cell.get("text") or cell.get("id")))
    return document


def upstream_documents(db: Session, workspace_id: str, board: Board, item_id: str) -> list[ReferenceDocument]:
    """连进这一格的文档格给的文档,按连线的先后 —— 生成时整篇交给模型当素材(见 generation.documents_note)。

    **由服务端按连线取,不由前端拼进提示词**:拼在前端的话,生成记录上存的就是拼过的字,AI 工作台的用户气泡
    把文档正文当成他说的话画出来;给模型什么也成了前端说了算。读不到就不生成(_upstream_document)。
    """
    return [_upstream_document(db, workspace_id, cell)
            for cell in upstream_cells(board, item_id) if cell.get("kind") == "document"]


def upstream_texts(db: Session, workspace_id: str, board: Board, item_id: str) -> list[str]:
    """连进这一格的便签的字、文档格的正文,按连线的先后,去掉首尾空白、空的不要 —— 写字时当「上游给的材料」。

    **由服务端按连线取**,理由和生成的 upstream_documents 一样:给模型什么不该由前端说了算。文档的读法也是
    同一份(钉住的那一版、解析出的全文,读不到就不写)。只给正文不给标题:便签本来就没有标题,两种材料摆在一起
    是同一个样子。
    """
    texts: list[str] = []
    for cell in upstream_cells(board, item_id):
        if cell.get("kind") == "note":
            text = str(cell.get("text") or "")
        elif cell.get("kind") == "document":
            text = _upstream_document(db, workspace_id, cell).markdown
        else:
            continue
        if text.strip():
            texts.append(text.strip())
    return texts


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
    digital_human_consent: bool = False,
) -> Board:
    """在画板上出图出片。没点名模型时由漏斗用这个人的默认。

    `entity_ids` 是正文里 `@` 到的资产;连进这一格的资产格在这里并进去(upstream_entities),
    之后两者是同一样东西。连进这一格的 3D 场景格(upstream_scene)按 `scene_reference`(镜头、用法)现渲成参考。
    连进这一格的文档格(upstream_documents)整篇交给模型当素材。`prompt` 只是用户写的那句。

    **顺序**:建任务 → 摆占位 → 起任务。起在占位之前的话,一个当场失败的生成会把回执送到一格
    还不存在的地方。生成的错误(GenerationDomainError)原样抛出。

    **一次交回几份就摆几格**(generation.planned_outputs:模型说的一次几份 × 张数):第 2 份起的占位摆在右边,
    回执按先后填进去(见 outputs._canvas_with_delivered_result)。
    """
    from app.domain.generation import create_generation_job
    from app.core.unit_of_work import after_commit
    from app.domain.generation.operations import parse_source_assets, planned_outputs
    from app.domain.generation.runner import start_generation_thread

    _ensure_slot_ready(db, workspace_id, slot)
    board = get_board(db, workspace_id, slot.board_id)
    mentioned = list(dict.fromkeys([*(entity_ids or []), *upstream_entities(board, slot.item_id)]))
    scene_id = upstream_scene(board, slot.item_id)
    reference = {**(scene_reference or {}), "scene_id": scene_id} if scene_id else None
    documents = upstream_documents(db, workspace_id, board, slot.item_id)
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
            #: 画板上的正文会按名字 `@` 素材,而模型收到的素材没有名字 —— 让漏斗在提示词后面补一段对照。
            name_sources=True,
            documents=documents,
            digital_human_consent=digital_human_consent,
        )
    finally:
        reset_receipt(token)
    board = _pending(
        db, workspace_id, slot, actor_id=actor_id, kind=kind, producer="generate", job_id=job.id,
        #: 一次交回几份就一次摆几格(ComfyUI 一张工作流几个保存节点 × 张数):不再等回执到了往右冒出来。
        outputs=planned_outputs(db, user_id=actor_id, provider=generation.provider, model=generation.model, kind=kind,
                                provider_profile_id=generation.provider_profile_id, parameters=parameters),
        form={
            **form,
            #: 编辑器里的原样:换成不收提示词的模型时发出去的是空串,框里写过的字照样留着,换回来还在。
            #: 调用方没给表单(智能体、脚本)时才用发出去的那句。
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
    # 生成线程重开会话去读刚建的行(和这一格的占位):等入口提交之后再起。
    generation_id = generation.id
    after_commit(db, lambda: start_generation_thread(generation_id))
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
    entity_ids: list[str] | None = None,
    base_revision: int | None = None,
) -> Board:
    """让 AI 往一张便签里写字,或者在文档格上写一篇笔记。摆好「写作中」的占位、起好任务就回;写出来的正文(或失败原因)
    由回执落回那一格 —— 和生成、念、截同一套。

    **异步,不在请求里等模型。** 看着几张图写一整篇文档要两三分钟(见 WRITE_TIMEOUT_SECONDS):此前请求就在这里等,
    前端的写请求队列被它占着(那几分钟里拖一下、改个字都存不上),格子上的运行态没有任务号,也就没有停止按钮。
    现在它是一个普通的后台任务:格子上照常转圈、能停(停下时模型那边的回答作废,调用照样计费 —— 和别的
    停不下远端的产出者一样),回执落终态。进程中途没了,重启时 reconcile 收掉。

    **起任务之前**就把说得清的错说掉(没写要求、没配连接、点名的资产不在这个工作区、连着的文档读不到):
    当场回错,不起一个注定失败的任务。

    **看着什么写**:上游连过来的和正文里 `@` 到的素材(图片、视频给画面,音频给转写,见 look_at)、连进来的便签的字和
    文档的正文(upstream_texts,服务端按连线取,和生成读文档同一份)、以及连进来的和 `@` 到的**资产**(ADR 0027)——
    它的描述当材料,前几张参考图给模型看。`prompt` 只是用户写的那句。

    **文档格**:写出来的是一篇笔记。空的文档格新建一篇、引用它;已经引用着一篇的,那一篇就是「现有内容」,
    写成它的**新一版**(笔记的每一版都留着,改坏了能退回),文档格改钉到新的那一版。

    **也不自己实现「调 LLM」**:供应商解析、调用、计量和工作流的 LLM 节点、智能体是同三样东西。
    """
    from app.domain.ai_chat import AiChatError
    from app.domain.jobs import dispatch_job
    from app.domain.providers.chat_connection import require_connection

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
    #: 没配连接当场说(「先去设置里配一个」),不起任务 —— 任务线程里再解析一次(会话是它自己的)。
    require_connection(db, provider_profile_id or None, user_id=actor_id, error=AiChatError, surface="automation")
    #: 连进来的资产格 + 正文里 @ 到的,和生成同一条路(upstream_entities);连进来的便签和文档给的字(upstream_texts)。
    #: 都在建任务之前取:点名的资产不在这个工作区、连着的文档读不到,就当场说,不起任务。
    board = get_board(db, workspace_id, board_id)
    named = list(dict.fromkeys([*upstream_entities(board, item_id), *(entity_ids or [])]))
    entity_texts, entity_pictures = _entity_materials(db, workspace_id, named)
    upstream = upstream_texts(db, workspace_id, board, item_id)

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
    # 有意的提交:占位的合并撞上并发写入时会回滚重来(update_board),不能把刚建的任务一起卷走。
    db.commit()
    placed = _pending(
        db, workspace_id, Slot(board_id, item_id, 0, 0), actor_id=actor_id, kind=kind, producer="write", job_id=job.id,
        #: 表单记下**这一轮**用的要求和模型 —— 写挂了回来,面板上原样还在,改一个字就能重来。
        form={**(slot_item.get("form") or {}), "prompt": prompt,
              "provider_profile_id": provider_profile_id, "model": model},
    )
    order = _WriteOrder(
        workspace_id=workspace_id, board_id=board_id, kind=kind, note_id=note_id, existing=existing, prompt=prompt,
        provider_profile_id=provider_profile_id, model=model, actor_id=actor_id,
        #: 上游连过来的 + 正文里 @ 到的 + 资产的参考图。图片和视频给画面,音频给转写 —— 见 look_at。
        seen=list(dict.fromkeys([*source_asset_ids, *entity_pictures])),
        materials=[*upstream, *entity_texts],
    )
    job_id = job.id
    dispatch_job(db, job, lambda: _write_in_job(job_id, order))
    return placed


@dataclass(frozen=True)
class _WriteOrder:
    """一次写字要的全部东西,在请求里定好、交给任务线程。只有值,不带会话里的对象。"""

    workspace_id: str
    board_id: str
    kind: str
    note_id: str
    existing: str
    prompt: str
    provider_profile_id: str
    model: str
    actor_id: str
    seen: list[str]
    materials: list[str]


def _write_in_job(job_id: str, order: _WriteOrder) -> None:
    """任务线程里写。失败(模型报错、读素材炸了、落笔记出错)由 run_job_inline 落到任务上,回执随之送到那一格。"""
    from app.core.db import SessionLocal
    from app.db.models import Job

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        try:
            run_job_inline(db, job, lambda: _write(db, job_id, order),
                           running="jobMsg_boardWriteRunning", done="jobMsg_boardWriteDone")
        except Exception:  # noqa: BLE001 — 失败已经落到任务上(见 run_job_inline)
            logger.info("board_write %s failed", job_id, exc_info=True)


def _write(db: Session, job_id: str, order: _WriteOrder) -> dict[str, Any]:
    """调一次模型把字写出来,交回任务的 result:便签是一段正文,文档格是写成的那篇笔记(那一版)。"""
    from app.domain.ai_chat import AiChatError, chat, target_for
    from app.domain.billing.usage import billable
    from app.domain.providers.chat_connection import require_connection

    kind, existing = order.kind, order.existing
    target_name = "这篇文档" if kind == "document" else "这张便签"
    pictures, from_assets = look_at(db, order.workspace_id, order.seen)
    materials = order.materials + from_assets
    profile = require_connection(db, order.provider_profile_id or None, user_id=order.actor_id, error=AiChatError,
                                 surface="automation")
    target = target_for(db, profile, model=order.model, surface="automation")
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
        #: 一个任务记一次账:任务是这次调用稳定的工作单元。
        idempotency_key=f"board_write:{job_id}",
        workspace_id=order.workspace_id,
        provider=target.vendor,
        model=target.model,
        provider_profile_id=profile.id,
        source_type="board",
        source_id=order.board_id,
    ) as call:
        text = chat(
            target,
            [
                {"role": "system", "content": system},
                *(
                    #: 上游给的材料(便签的字、资产的描述、素材的转写),自成一轮。**和「要求」分开** ——
                    #: 揉成一段的话,模型分不清哪句是素材、哪句是指令,常见的结果是把材料原样抄一遍。
                    [{"role": "user", "content": "上游给的材料:\n\n" + "\n\n---\n\n".join(materials)}]
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
                {"role": "user", "content": [{"type": "text", "text": order.prompt}, *pictures] if pictures else order.prompt},
            ],
            temperature=0.7,
            call=call,
            label="画板写文档" if kind == "document" else "画板写文案",
            timeout=WRITE_TIMEOUT_SECONDS[kind],
        ).strip()
    if kind == "document":
        from app.db.models import Job
        from app.domain.jobs import lock_active_job

        #: 模型写的那一会儿人可能点了停止:那一格已经落成「已取消」,笔记就不能再新建、再改成新一版 —— 停下的活儿
        #: 不留副作用。拿到写锁再看(lock_active_job),看完到落笔记之间取消插不进来;停了就交回空结果(作废)。
        job = db.get(Job, job_id)
        if job is None or not lock_active_job(db, job):
            return {}
        board = get_board(db, order.workspace_id, order.board_id)
        return {"outputs": [_write_note(db, order.workspace_id, board, order.note_id, text, actor_id=order.actor_id)]}
    return {"text": text}


def _note_title(markdown: str) -> str:
    """新笔记的标题:正文第一个标题;没有就是第一行,截短。"""
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    heading = next((line.lstrip("#").strip() for line in lines if line.startswith("#")), "")
    title = heading or (lines[0] if lines else "")
    return title[:60]


def _write_note(db: Session, workspace_id: str, board: Board, note_id: str, markdown: str, *,
                actor_id: str) -> dict[str, Any]:
    """文档格写出来的正文落成笔记:引用着一篇的写成它的新一版,空的新建一篇(来源记上这张画板)。
    交回一份 `note` 产出,回执据此把文档格钉到这一版(canvas.outputs_of)。替点「写」的那个人写 ——
    笔记上原有的来源照留,新加的只有这张画板。"""
    from app.domain.note_types import NoteContent
    from app.domain.notes import create_note, get_note, save_note, snapshot

    if note_id:
        note = get_note(db, workspace_id, note_id)
        note = save_note(db, workspace_id, note_id, note.save_seq,
                         NoteContent.model_validate({**snapshot(note), "markdown": markdown}), actor=actor_id,
                         origin="board")
    else:
        note = create_note(db, workspace_id, NoteContent.model_validate({
            "title": _note_title(markdown),
            "markdown": markdown,
            "sources": [{"kind": "board", "id": board.id, "label": board.name, "quote": ""}],
        }), actor=actor_id, origin="board")
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
