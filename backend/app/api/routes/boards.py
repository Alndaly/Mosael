"""创意画板的路由。薄的一层:鉴权 + 把领域错误翻成 400,画布的规矩全在 domain/boards。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import BoardCreate, BoardGenerate, BoardOut, BoardSpeak, BoardTrim, BoardUpdate, BoardWrite
from app.db.models import Board
from app.domain.boards import (
    BoardDomainError,
    create_board,
    delete_board,
    get_board,
    list_boards,
    place_pending,
    receipt_to_item,
    update_board,
    write_text,
)
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm

router = APIRouter(tags=["boards"])


@router.get("/boards", response_model=list[BoardOut])
def list_all(workspace_id: str, db: DbSession, user: CurrentUser) -> list[Board]:
    ensure_workspace_access(db, user, workspace_id)
    return list_boards(db, workspace_id)


@router.get("/boards/{board_id}", response_model=BoardOut)
def read(board_id: str, workspace_id: str, db: DbSession, user: CurrentUser) -> Board:
    ensure_workspace_access(db, user, workspace_id)
    try:
        return get_board(db, workspace_id, board_id)
    except BoardDomainError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/boards", response_model=BoardOut)
def create(body: BoardCreate, db: DbSession, user: CurrentUser) -> Board:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    try:
        return create_board(db, workspace_id=body.workspace_id, name=body.name, canvas=body.canvas)
    except BoardDomainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/boards/{board_id}", response_model=BoardOut)
def update(board_id: str, body: BoardUpdate, db: DbSession, user: CurrentUser) -> Board:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    try:
        return update_board(
            db, workspace_id=body.workspace_id, board_id=board_id, name=body.name, canvas=body.canvas
        )
    except BoardDomainError as exc:
        # 「画板不存在」是 404,「画布不合法」是 400 —— 两者对调用方意味着完全不同的下一步。
        status = 404 if "不存在" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.delete("/boards/{board_id}")
def remove(board_id: str, workspace_id: str, db: DbSession, user: CurrentUser) -> dict[str, bool]:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    try:
        delete_board(db, workspace_id, board_id)
    except BoardDomainError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/boards/{board_id}/generate", response_model=BoardOut)
def generate(board_id: str, body: BoardGenerate, db: DbSession, user: CurrentUser) -> Board:
    """在画板上生成一份素材,产出就地落回画布。

    **不自己实现生成** —— 汇进 create_generation_job 那条漏斗(AI 工作台、定时任务、
    工作流节点、智能体走的是同一条),于是描述符校验、能力探测、计量记账、任务中心全都白拿。
    这里只多做一件画板自己的事:先摆一个「正在生成」的占位,并把回执指向它。
    """
    from app.domain import provider_models
    from app.domain.generation import create_generation_job
    from app.domain.generation.operations import parse_source_assets
    from app.domain.generation.operations import GenerationDomainError
    from app.domain.generation.runner import start_generation_thread

    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    try:
        board = get_board(db, body.workspace_id, board_id)
    except BoardDomainError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    provider, model = body.provider.strip(), body.model.strip()
    if not provider or not model:
        # 没点名就用这个人在这种能力上的默认 —— 和定时任务那条路同一个解析。
        default = provider_models.resolve_default(db, body.kind, user.id)
        if default is not None and default.profile is not None:
            provider, model = default.profile.vendor, default.model_id
    if not provider or not model:
        raise HTTPException(status_code=400, detail="还没有可用的生成模型,先去设置里配一个")

    try:
        generation, job = create_generation_job(
            db,
            workspace_id=body.workspace_id,
            session_id=None,
            project_id=None,
            created_by=user.id,
            provider=provider,
            model=model,
            kind=body.kind,
            prompt=body.prompt,
            negative_prompt="",
            parameters=dict(body.parameters or {}),
            #: **归一成字典再交出去** —— `create_generation_job` 收的是 `[{asset_id, role}]`,
            #: 而这里的 body.source_assets 是一串 pydantic 对象。直接传的话校验器上
            #: `entry.get("role")` 当场 AttributeError,整个请求 500:也就是说画板上只要挂了
            #: 素材(槽位或正文里 @ 的),生成就没成过。别处四个调用方都走这个函数。
            source_assets=parse_source_assets(
                [one.model_dump() for one in (body.source_assets or [])], kind=body.kind
            ),
        )
    except GenerationDomainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 回执指向这一项:任务落终态时由 domain/boards.deliver_generated 把 asset_id 填回来。
    job.payload = {**(job.payload or {}), "receipt": receipt_to_item(board.id, body.item_id)}
    db.commit()

    try:
        board = place_pending(
            db,
            workspace_id=body.workspace_id,
            board_id=board.id,
            item={
                "id": body.item_id,
                "kind": body.kind,
                "x": body.x,
                "y": body.y,
                "job_id": job.id,
                "text": body.prompt[:120],
            },
        )
    except BoardDomainError as exc:
        # 画布放不下这一项是**请求的问题**,不是服务器崩了 —— 漏出去的话调用方收到 500
        # 和一整页 traceback,而真正的原因(比如坐标不合法)一个字都看不到。
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    start_generation_thread(generation.id)
    return board


@router.post("/boards/{board_id}/write", response_model=BoardOut)
def write(board_id: str, body: BoardWrite, db: DbSession, user: CurrentUser) -> Board:
    """让 AI 往画板上的一张便签里写字。

    **不走生成任务那条路。** 出图出片要几十秒,所以那边先摆占位、起任务、回执填回来;写字几秒
    就回,同步返回反而更直接 —— 为它铺一套任务/回执,用户看到的只是一个多余的转圈。

    **也不自己实现一遍「调 LLM」**:供应商解析走 require_profile、调用走 ai_chat.chat、计量走
    billable —— 和工作流的 LLM 节点、智能体是同三样东西。另写一份的话,重试次数、超时、
    记账口径迟早各走各的,而分岔了没有任何地方会报错。
    """
    from app.domain.ai_chat import AiChatError, chat, target_for
    from app.domain.providers import require_profile
    from app.domain.usage import billable

    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="先写点要求,再让它写")

    #: 这张便签上已经有的字。**从画布上读,不让前端拼进提示词** —— 服务端本来就拿着这份画布,
    #: 而拼在前端意味着「现在写的是什么」和「要求是什么」揉成了一段,模型分不清哪句是要改的
    #: 对象、哪句是改法。有字就是**改写**,没字才是从头写。
    try:
        board = get_board(db, body.workspace_id, board_id)
    except BoardDomainError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    existing = next(
        (str(one.get("text") or "") for one in (board.canvas or {}).get("items", []) if one.get("id") == body.item_id),
        "",
    ).strip()

    #: 上游连过来的图 + 正文里 @ 到的图。**只收图片** —— 视频和音频这条路吃不下
    #: (要抽帧、要转写,那是 analyze_asset 的事),悄悄发过去只会换回一句看不懂的报错。
    #: 上游连过来的 + 正文里 @ 到的。图片和视频给画面,音频给转写 —— 见 _look_at。
    pictures, from_assets = _look_at(db, body.workspace_id, body.source_assets)
    materials = [one.strip() for one in body.context if one and one.strip()] + from_assets

    try:
        profile = require_profile(db, body.provider_profile_id or None, user_id=user.id, error=AiChatError)
        target = target_for(db, profile, model=body.model)
        with billable(
            db,
            capability="chat",
            operation="board_write",
            workspace_id=body.workspace_id,
            provider=target.vendor,
            model=target.model,
            provider_profile_id=profile.id,
            source_type="board",
            source_id=board_id,
        ) as call:
            text = chat(
                target,
                [
                    #: 说清楚产物要直接摆在画板上 —— 不交代的话模型爱写「好的,这是您要的文案:」,
                    #: 而那句话会原样贴进便签里。
                    {
                        "role": "system",
                        "content": (
                            "你在帮用户往一张创意画板的便签上写字。直接给正文,不要开场白、不要解释、"
                            "不要用 Markdown 代码块包起来。"
                            + (
                                "这张便签上已经有内容,用户给的是**改法**:照他说的改,没提到的地方保持原样,"
                                "整篇重写一遍不是他要的。"
                                if existing
                                else ""
                            )
                        ),
                    },
                    *(
                        #: 上游便签给的材料,自成一轮。**和「要求」分开** —— 揉成一段的话,
                        #: 模型分不清哪句是素材、哪句是指令,常见的结果是把材料原样抄一遍。
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
                        [{"role": "user", "content": f"这张便签现在的内容:\n{existing}"}]
                        if existing
                        else []
                    ),
                    #: 有图就让模型**看着写**。图片和要求放在同一轮里 —— 分开发的话模型
                    #: 不知道这句话说的是哪张图。
                    {"role": "user", "content": [{"type": "text", "text": prompt}, *pictures] if pictures else prompt},
                ],
                temperature=0.7,
                call=call,
                label="画板写文案",
            ).strip()
    except AiChatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        return write_text(db, workspace_id=body.workspace_id, board_id=board_id, item_id=body.item_id, text=text)
    except BoardDomainError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/boards/{board_id}/speak", response_model=BoardOut)
def speak(board_id: str, body: BoardSpeak, db: DbSession, user: CurrentUser) -> Board:
    """把一段文字念成音频,产出落回画板上那一格。

    **和出图出片同一套**:先摆占位、起任务、回执把 asset_id 填回来 —— 合成可能几十秒,还可能
    在另一台机器上跑。回执用 set_receipt 打在上下文里,之后 start_synthesis 建的任务自动带上
    (不用把 board 的概念塞进 voices 领域)。
    """
    from app.domain.jobs import reset_receipt, set_receipt
    from app.domain.voices.voices import VoiceError, start_synthesis

    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="没有可念的文字")

    token = set_receipt(receipt_to_item(board_id, body.item_id))
    try:
        job = start_synthesis(
            db,
            text=text,
            project_id=None,
            created_by=user.id,
            voice_id=body.voice_id or None,
            workspace_id=body.workspace_id,
        )
    except VoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        reset_receipt(token)

    try:
        return place_pending(
            db,
            workspace_id=body.workspace_id,
            board_id=board_id,
            item={"id": body.item_id, "kind": "audio", "x": body.x, "y": body.y, "job_id": job.id, "text": text[:120]},
        )
    except BoardDomainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/boards/{board_id}/trim", response_model=BoardOut)
def trim(board_id: str, body: BoardTrim, db: DbSession, user: CurrentUser) -> Board:
    """截出一段,产出落回画板上那一格。

    **原素材不动** —— 画板上的每一步都该是可回头的,就地改会让上一版消失。产出是一份新素材。
    """
    from app.db.models import Asset
    from app.domain.boards_trim import TrimError, start_trim
    from app.domain.jobs import reset_receipt, set_receipt

    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    asset = db.get(Asset, body.asset_id)
    if asset is None or asset.workspace_id != body.workspace_id:
        raise HTTPException(status_code=404, detail="这个工作区里没有这份素材")

    token = set_receipt(receipt_to_item(board_id, body.item_id))
    try:
        job = start_trim(
            db, asset=asset, start=body.start, end=body.end, mute=body.mute, created_by=user.id
        )
    except TrimError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        reset_receipt(token)

    try:
        return place_pending(
            db,
            workspace_id=body.workspace_id,
            board_id=board_id,
            item={
                "id": body.item_id,
                "kind": asset.kind,
                "x": body.x,
                "y": body.y,
                "job_id": job.id,
                "text": f"截取 {body.start:.1f}-{body.end:.1f}s",
            },
        )
    except BoardDomainError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _look_at(db: DbSession, workspace_id: str, asset_ids: list[str]) -> tuple[list[dict], list[str]]:
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
    from app.domain.analysis.service import AnalysisError, extract_video_frames, image_part
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
            mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            parts.append(image_part(path.read_bytes(), mime))
        elif asset.kind == "video":
            try:
                parts.extend(image_part(frame) for frame in extract_video_frames(path))
            except AnalysisError:
                # 抽不出帧不该让整次「写文案」失败 —— 少一段素材,总比一句都写不出来好。
                continue
        elif asset.kind == "audio":
            from app.domain.analysis.service import _asset_transcript_text

            spoken = _asset_transcript_text(db, asset.id)
            if spoken:
                materials.append(f"【{asset.name} 的语音转写】\n{spoken}")
    return parts, materials
