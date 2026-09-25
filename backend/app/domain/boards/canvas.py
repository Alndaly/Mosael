"""创意画板:一张无限画布,用来攒想法。

除了和智能体对话之外的另一条路 —— 对话是线性的,而想法不是。画板让人把碎片摊开、挪动、
连起来,先看见结构再决定做什么。

## 这一层负责什么

**画布的形状**。数据库那边只有一列 JSON(见 db/models.Board),什么算合法的画布由这里说了算。
校验放在领域层而不是路由:画板将来会有第二个入口(智能体往板上贴东西、工作流产出落到板上),
放在路由里就意味着那些入口各自再写一遍,而漏掉的那一遍不会报错 —— 只会存进一张打不开的板。

## 为什么校验得这么紧

存进去的东西下一次是**要渲染**的。一个坐标是字符串、一个 kind 拼错了,前端拿到的是一张
渲染到一半崩掉的画布,而错误发生在几天前的某一次保存里。所以宁可在写入时就拒绝:
拒绝的那一刻用户还知道自己刚做了什么。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import Board, now


logger = logging.getLogger(__name__)


class BoardDomainError(LocalizedError, ValueError):
    pass


class BoardNotFound(BoardDomainError):
    """这个工作区里没有这张板(或这一项)。"""


class BoardRevisionConflict(BoardDomainError):
    """The caller edited a projection older than the server's current board."""

    def __init__(self, base_revision: int, current_revision: int):
        self.base_revision = base_revision
        self.current_revision = current_revision
        super().__init__("boardErr_revisionConflict", base=base_revision, current=current_revision)


def item_not_found(item_id: str) -> BoardNotFound:
    """「画板项不存在」。没给 id 是另一句话 —— 把「(空)」当成 id 填进去就翻不动了。"""
    return BoardNotFound("boardErr_itemNotFound", item_id=item_id) if item_id else BoardNotFound("boardErr_itemIdMissing")


def _field_error(item_key: str, bare_key: str, field: str, item_id: str, **params: object) -> BoardDomainError:
    """坐标 / 尺寸不合法。带不带「画板项 xx 的」是两句话,不是往前面拼一截。"""
    if item_id:
        return BoardDomainError(item_key, item_id=item_id, field=field, **params)
    return BoardDomainError(bare_key, field=field, **params)


#: 画板上能放什么。
#:
#: `note` 便签(文字)、`image` 图片、`video` 视频、`audio` 音频、`frame` 分组框(圈起来命名)。
#:
#: 图片和视频**分开两种而不是合成一个 media**:它们在画板上的样子和操作都不同 ——
#: 图片是一张静止的参考,视频要能就地播;而"从这张图生成视频"是图片才有的动作,
#: 反过来"抽一帧"是视频才有的。合成一种的话每处都要先分辨一次它到底是哪个。
ITEM_KINDS = ("note", "image", "video", "audio", "frame", "scene", "document")

#: 必须指向素材库一份的那几种。空着的话存得下、打开却是个空白框。
_NEEDS_ASSET = ("image", "video", "audio")

#: 一个 item 至少要有的东西。坐标必须是数,否则画布渲染不出来。
_REQUIRED = ("id", "kind", "x", "y")

#: 便签的颜色。给一组预设而不是任意色值:随手挑的颜色凑在一起会很难看,而且**颜色要能表达
#: 分类** —— 一组固定的色板才让"黄色是待办、蓝色是参考"这种约定成立。
NOTE_COLORS = ("yellow", "blue", "green", "pink", "purple", "gray")

MAX_ITEMS = 2000
MAX_TEXT_CHARS = 20_000
RUN_STATUSES = ("idle", "queued", "running", "succeeded", "failed", "cancelled")


def finite_number(value: Any, field: str, item_id: str = "") -> float:
    """画布上的一个坐标或尺寸。**算子那一侧共用这一个** —— 两份各写各的必然漂,而漂的那
    一半就是没挡住的那条路。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _field_error("boardErr_itemFieldNotNumber", "boardErr_fieldNotNumber", field, item_id, value=repr(value))
    # NaN / Infinity 是合法的 Python float,`json.dumps` 也照写不误 —— 而写出来的
    # `{"x": NaN}` **不是合法 JSON**,浏览器 `JSON.parse` 直接抛。一张画板只要混进一个,
    # 它就再也打不开了:用户看到的是"画板坏了",而库里那份数据其实完好。
    #
    # 不是只有恶意客户端造得出:前端算坐标时一次除以零(缩放为 0、宽度为 0)就是 NaN,
    # 而它会一路存进去、不报错。一个瞬时的计算失误换一张永久打不开的画板,不成比例。
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise _field_error("boardErr_itemFieldNotFinite", "boardErr_fieldNotFinite", field, item_id, value=repr(value))
    return number


def _normalize_form(value: Any, item_id: str) -> dict[str, Any] | None:
    """校验并保留**属于节点自己的表单**。

    表单是用户可继续编辑的事实；生成器为了调用供应商临时补上的文件名图例、签名参数等都
    不属于它。这里有意允许不同节点放不同字段，但把 JSON 的基本形状钉住，避免下一次打开
    节点时拿到一个无法渲染的值。
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BoardDomainError("boardErr_itemFieldNotObject", item_id=item_id, field="form")
    form = dict(value)
    prompt = form.get("prompt")
    if prompt is not None:
        if not isinstance(prompt, str):
            raise BoardDomainError("boardErr_itemFieldNotString", item_id=item_id, field="form.prompt")
        if len(prompt) > MAX_TEXT_CHARS:
            raise BoardDomainError("boardErr_promptTooLong", item_id=item_id, limit=MAX_TEXT_CHARS)
    for field in ("provider", "provider_profile_id", "model", "mode", "voice_id"):
        if form.get(field) is not None and not isinstance(form[field], str):
            raise BoardDomainError("boardErr_itemFieldNotString", item_id=item_id, field=f"form.{field}")
    if form.get("parameters") is not None and not isinstance(form["parameters"], dict):
        raise BoardDomainError("boardErr_itemFieldNotObject", item_id=item_id, field="form.parameters")
    sources = form.get("source_assets")
    if sources is not None:
        if not isinstance(sources, list) or any(not isinstance(one, dict) for one in sources):
            raise BoardDomainError("boardErr_sourceAssetsNotObjects", item_id=item_id)
        form["source_assets"] = [
            {"asset_id": str(one.get("asset_id") or "").strip(), "role": str(one.get("role") or "").strip()}
            for one in sources
            if str(one.get("asset_id") or "").strip() and str(one.get("role") or "").strip()
        ]
    mentioned = form.get("mentioned_asset_ids")
    if mentioned is not None:
        if not isinstance(mentioned, list):
            raise BoardDomainError("boardErr_itemFieldNotArray", item_id=item_id, field="form.mentioned_asset_ids")
        form["mentioned_asset_ids"] = [str(one).strip() for one in mentioned if str(one).strip()]
    prompt_document = form.get("prompt_document")
    if prompt_document is not None:
        if not isinstance(prompt_document, dict) or prompt_document.get("type") != "doc":
            raise BoardDomainError("boardErr_promptDocumentNotDoc", item_id=item_id)
        if len(json.dumps(prompt_document, ensure_ascii=False)) > MAX_TEXT_CHARS * 8:
            raise BoardDomainError("boardErr_promptDocumentTooLarge", item_id=item_id)
    return form


def _normalize_run(value: Any, item_id: str) -> dict[str, Any] | None:
    """校验节点自己的运行态。终态不允许再携带 job_id，避免 UI 永久转圈。"""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BoardDomainError("boardErr_itemFieldNotObject", item_id=item_id, field="run")
    status = str(value.get("status") or "idle").strip()
    if status not in RUN_STATUSES:
        raise BoardDomainError("boardErr_runStatusInvalid", item_id=item_id, status=status)
    run: dict[str, Any] = {"status": status}
    job_id = value.get("job_id")
    if job_id is not None:
        if status not in ("queued", "running"):
            raise BoardDomainError("boardErr_finishedRunHasJob", item_id=item_id)
        if not isinstance(job_id, str) or not job_id.strip():
            raise BoardDomainError("boardErr_itemFieldInvalid", item_id=item_id, field="run.job_id")
        run["job_id"] = job_id.strip()
    error = value.get("error")
    if error is not None:
        if not isinstance(error, str):
            raise BoardDomainError("boardErr_itemFieldNotString", item_id=item_id, field="run.error")
        if error.strip():
            run["error"] = error.strip()[:300]
    return run


def normalize_canvas(raw: Any) -> dict[str, Any]:
    """把外面传进来的画布校验并归一成存得下、读得回的形状。

    宽进严出:少写的字段补默认(新画板、旧版本存的都能读),而**写错的字段一律拒绝** ——
    补一个默认值等于替用户猜,而猜错的表现是他的东西挪了位置或者变了颜色。
    """
    if raw is None:
        return {"items": [], "edges": [], "markers": []}
    if not isinstance(raw, dict):
        raise BoardDomainError("boardErr_canvasNotObject")

    raw_items = raw.get("items") or []
    if not isinstance(raw_items, list):
        raise BoardDomainError("boardErr_canvasFieldNotArray", field="items")
    if len(raw_items) > MAX_ITEMS:
        raise BoardDomainError("boardErr_tooManyItems", limit=MAX_ITEMS, count=len(raw_items))

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw_items:
        if not isinstance(entry, dict):
            raise BoardDomainError("boardErr_itemNotObject")
        for field in _REQUIRED:
            if field not in entry:
                raise BoardDomainError("boardErr_itemMissingField", field=field)
        item_id = str(entry["id"]).strip()
        if not item_id:
            raise BoardDomainError("boardErr_itemIdEmpty")
        # id 重了的话前端按 id 索引会**默默丢掉一个** —— 用户看到的是"我刚加的东西没了"。
        if item_id in seen:
            raise BoardDomainError("boardErr_duplicateItemId", item_id=item_id)
        seen.add(item_id)

        kind = str(entry["kind"]).strip()
        if kind not in ITEM_KINDS:
            raise BoardDomainError("boardErr_unknownItemKind", kind=kind, kinds=", ".join(ITEM_KINDS))
        if "job_id" in entry or "error" in entry:
            raise BoardDomainError("boardErr_legacyRunFields", item_id=item_id)

        item: dict[str, Any] = {
            "id": item_id,
            "kind": kind,
            "x": finite_number(entry["x"], "x", item_id),
            "y": finite_number(entry["y"], "y", item_id),
        }
        for field in ("width", "height"):
            if entry.get(field) is not None:
                size = finite_number(entry[field], field, item_id)
                if size <= 0:
                    raise BoardDomainError("boardErr_itemSizeNotPositive", item_id=item_id, field=field)
                item[field] = size

        text = entry.get("text")
        if text is not None:
            if not isinstance(text, str):
                raise BoardDomainError("boardErr_itemFieldNotString", item_id=item_id, field="text")
            if len(text) > MAX_TEXT_CHARS:
                raise BoardDomainError("boardErr_textTooLong", item_id=item_id, limit=MAX_TEXT_CHARS)
            item["text"] = text

        form = _normalize_form(entry.get("form"), item_id)
        if form is not None:
            item["form"] = form

        color = entry.get("color")
        if color is not None:
            if color not in NOTE_COLORS:
                raise BoardDomainError("boardErr_unknownColor", color=color, colors=", ".join(NOTE_COLORS))
            item["color"] = color

        if kind == "document":
            note_id, revision = entry.get("note_id"), entry.get("note_revision")
            if note_id is not None or revision is not None:
                if not isinstance(note_id, str) or not note_id.strip() or len(note_id) > 64:
                    raise BoardDomainError("boardErr_documentNeedsNote")
                if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                    raise BoardDomainError("boardErr_documentNeedsRevision")
                item["note_id"], item["note_revision"] = note_id.strip(), revision

        if kind == "scene":
            scene_id = entry.get("scene_id")
            if not isinstance(scene_id, str) or not scene_id.strip():
                raise BoardDomainError("boardErr_sceneNeedsId")
            item["scene_id"] = scene_id.strip()

        asset_id = entry.get("asset_id")
        if asset_id is not None:
            if not isinstance(asset_id, str) or not asset_id.strip():
                raise BoardDomainError("boardErr_itemFieldInvalid", item_id=item_id, field="asset_id")
            item["asset_id"] = asset_id.strip()

        # 分组框「联动拖动」:开着的时候,拖动这个框会把框里的东西一起带走。
        #
        # **存下来而不是每次现开** —— 它是这个框的性质(「这一组是一个整体」),而不是一次
        # 操作的临时状态;重进画板时该还是那样。只有分组框有意义,别的类型给了就是写错了。
        move_children = entry.get("move_children")
        if move_children is not None:
            if not isinstance(move_children, bool):
                raise BoardDomainError("boardErr_itemFieldNotBool", item_id=item_id, field="move_children")
            if kind != "frame":
                raise BoardDomainError("boardErr_moveChildrenFrameOnly", kind=kind)
            item["move_children"] = move_children

        # 正在生成的那一项:还没有素材,但有一个任务在跑。任务落终态时由回执把 asset_id
        # 填回来(见 deliver_generated)。**这是"还没有"和"不该有"的区别** —— 前者要占着位置
        # 让用户看见"这儿在生成",后者才是错误。
        run = _normalize_run(entry.get("run"), item_id)
        if run is not None:
            item["run"] = run

        # **空槽是合法的。** 一个图片/视频项有四种状态,缺一不可:
        #   · 空槽(都没有)   —— 刚放下,底下挂着提示词面板等你写;
        #   · 生成中(run.running) —— 提交了,等回执把 asset_id 填回来;
        #   · 跑挂了(run.failed)  —— 提示词还在,可以改一改再来一次;
        #   · 有产出(有 asset_id)。
        # 前两种此前都被当成错误拒掉了 —— 而"节点本身就是生成单元"这件事,正要从空槽开始。

        items.append(item)

    raw_edges = raw.get("edges") or []
    if not isinstance(raw_edges, list):
        raise BoardDomainError("boardErr_canvasFieldNotArray", field="edges")
    edges: list[dict[str, Any]] = []
    for entry in raw_edges:
        if not isinstance(entry, dict):
            raise BoardDomainError("boardErr_edgeNotObject")
        source = str(entry.get("source") or "").strip()
        target = str(entry.get("target") or "").strip()
        # 连到不存在的项上,渲染时是一根悬空的线。存之前就把它挡住。
        if source not in seen or target not in seen:
            raise BoardDomainError("boardErr_edgeDangling", source=source, target=target)
        edge: dict[str, Any] = {"id": str(entry.get("id") or f"{source}->{target}"), "source": source, "target": target}
        label = entry.get("label")
        if label is not None:
            if not isinstance(label, str):
                raise BoardDomainError("boardErr_edgeLabelNotString")
            edge["label"] = label[:200]
        edges.append(edge)

    # 标记和 items 平级,不混进去 —— 它不是画板项(没有素材、不生成、连不了线),
    # 混进去的话每一处遍历 items 的地方都要先分辨一次"这个是不是标记"。规则见 domain/markers。
    from app.domain.markers import MarkerError, normalize_markers

    try:
        markers = normalize_markers(raw.get("markers"))
    except MarkerError as exc:
        # 带着 key/params 转手,不 str(exc):那会把句子冻成转手这一刻的语言。
        raise BoardDomainError(exc.key, **exc.params) from exc

    return {"items": items, "edges": edges, "markers": markers}


def list_boards(db: Session, workspace_id: str) -> list[Board]:
    return list(
        db.scalars(
            select(Board).where(Board.workspace_id == workspace_id).order_by(Board.updated_at.desc())
        )
    )


def get_board(db: Session, workspace_id: str, board_id: str) -> Board:
    board = db.get(Board, board_id)
    # 按工作区再验一次:拿到别的工作区的 id 也不该读得出来。
    if board is None or board.workspace_id != workspace_id:
        raise BoardNotFound("boardErr_notFound")
    return board


def ensure_revision(board: Board, base_revision: int | None) -> None:
    """调用方看到的是不是最新的这张板。**起任务之前**就要问 —— 等占位落地时才发现冲突,
    任务已经起了、钱已经花了,而产出没有地方放。"""
    if base_revision is not None and base_revision != board.revision:
        raise BoardRevisionConflict(base_revision, board.revision)


def _validate_scene_references(db: Session, workspace_id: str, canvas: dict, existing: dict | None = None) -> None:
    from app.db.models import Scene3D
    ids = {item['scene_id'] for item in canvas['items'] if item.get('scene_id')}
    if ids:
        owned = set(db.scalars(select(Scene3D.id).where(Scene3D.workspace_id == workspace_id, Scene3D.id.in_(ids))))
        if owned != ids:
            raise BoardDomainError("boardErr_sceneNotInWorkspace")

    from app.domain.notes import NoteDomainError, read_reference
    # Existing broken references remain movable/removable after a source is deleted.
    retained = {(item["id"], item.get("note_id"), item.get("note_revision"))
                for item in (existing or {}).get("items", []) if item["kind"] == "document"}
    for item in canvas["items"]:
        if item["kind"] != "document" or not item.get("note_id"):
            continue
        if (item["id"], item["note_id"], item["note_revision"]) in retained:
            continue
        try:
            ref = read_reference(db, workspace_id, item["note_id"], item["note_revision"])
            item["text"] = ref["title"]
        except NoteDomainError as exc:
            # 领域到领域的翻译:引用的文档有问题,对调用方来说是"这块画板存不下"。
            raise BoardDomainError(str(exc)) from exc

def create_board(
    db: Session, *, workspace_id: str, name: str, canvas: Any = None, actor_id: str | None = None
) -> Board:
    board = Board(
        workspace_id=workspace_id,
        name=(name or "").strip() or "新画板",
        canvas=normalize_canvas(canvas),
    )
    _validate_scene_references(db, workspace_id, board.canvas)
    db.add(board)
    db.flush()
    from app.domain.collaboration import record_activity

    record_activity(
        db,
        workspace_id=workspace_id,
        actor_id=actor_id,
        action="board.created",
        subject_type="board",
        subject_id=board.id,
        summary="创建了无限画布",
        payload={"revision": board.revision},
    )
    db.commit()
    db.refresh(board)
    return board


def duplicate_board(
    db: Session, *, workspace_id: str, board_id: str, name: str = "", actor_id: str | None = None
) -> Board:
    """复制一张画板:同样的项、连线和标记,落成新的一张。

    **在跑的那几格不带过去。** 生成任务的回执认的是原板(见 receipt_to_item,board_id 写死在
    任务的 payload 里),副本里留着 job_id 的话,那一格永远等不到回执 —— 框里一直转圈,底下的
    提交键一直按不动。它们在副本里退回空槽:提示词和参数都还在,想要的话再点一次。

    评论不跟着走:它们是对**那一张**的讨论,挂在原板的 subject_id 上。名字由调用方给(「× 副本」
    是界面语言里的一句话,这一层不替它挑语言);没给就沿用原名。
    """
    source = get_board(db, workspace_id, board_id)
    canvas = json.loads(json.dumps(source.canvas or {}))
    for item in canvas.get("items") or []:
        run = item.get("run")
        if isinstance(run, dict) and run.get("job_id"):
            item.pop("run")
    return create_board(
        db,
        workspace_id=workspace_id,
        name=(name or "").strip() or source.name,
        canvas=canvas,
        actor_id=actor_id,
    )


def update_board(
    db: Session,
    *,
    workspace_id: str,
    board_id: str,
    name: str | None = None,
    canvas: Any = None,
    base_revision: int | None = None,
    actor_id: str | None = None,
    starts_run: bool = False,
) -> Board:
    """改名和改画布是同一个入口,因为它们都是"这张板变了"。

    **两者都可以单独传**:自动保存只发 canvas,重命名只发 name —— 各发各的那一半,
    另一半不该被 None 覆盖掉。

    `starts_run`:这一次写入是服务端**自己开启新一轮运行**(摆生成占位、便签开始写),
    不是客户端存回来的快照。那种写入不过 `_keep_arrived_results` —— 那道闸防的是「任务结束后
    客户端拿着提交前的旧快照存回来」,而重新生成时库里正好是上一轮的终态,新一轮的 running
    会被它当成旧快照打回去:后端新任务照常跑(照常扣钱),画布上却还挂着上次的失败。
    """
    board = get_board(db, workspace_id, board_id)
    expected = board.revision if base_revision is None else base_revision
    if expected != board.revision:
        raise BoardRevisionConflict(expected, board.revision)
    next_name = board.name
    next_canvas = board.canvas
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise BoardDomainError("boardErr_nameEmpty")
        next_name = cleaned
    if canvas is not None:
        normalized = normalize_canvas(canvas)
        next_canvas = normalized if starts_run else _keep_arrived_results(board.canvas, normalized)
        _validate_scene_references(db, workspace_id, next_canvas, board.canvas)
    if next_name == board.name and next_canvas == board.canvas:
        return board
    result = db.execute(
        update(Board)
        .where(
            Board.id == board_id,
            Board.workspace_id == workspace_id,
            Board.revision == expected,
        )
        .values(name=next_name, canvas=next_canvas, revision=Board.revision + 1, updated_at=now())
        .execution_options(synchronize_session=False)
    )
    if int(result.rowcount or 0) != 1:
        db.rollback()
        current = get_board(db, workspace_id, board_id)
        raise BoardRevisionConflict(expected, current.revision)
    from app.domain.collaboration import record_activity

    action = "board.renamed" if name is not None and canvas is None else "board.updated"
    record_activity(
        db,
        workspace_id=workspace_id,
        actor_id=actor_id,
        action=action,
        subject_type="board",
        subject_id=board_id,
        summary="重命名了无限画布" if action == "board.renamed" else "编辑了无限画布",
        payload={"base_revision": expected, "revision": expected + 1},
    )
    db.commit()
    db.expire_all()
    return get_board(db, workspace_id, board_id)


def _keep_arrived_results(stored: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    """**客户端不该覆盖它还不知道的产出。**

    这是一个必然的竞态,不是偶发:画板自动保存,而生成是异步的 ——
      t1 客户端存了一份带占位(run 里有 job_id、没 asset_id)的画布;
      t2 任务跑完,回执把 asset_id 填进那一项;
      t3 用户又拖了一下,客户端把**它手上那份**存回来 —— 那份里还是占位。
    产出就这么没了,而且不报错:那一项看着还在转圈,可任务早就结束了。

    所以服务端在这一处做主:一项如果库里已经有 asset_id,而传来的那份还是占位,
    保留库里那个。客户端下一次拉到的就是填好的。
    """
    have = {
        str(item.get("id")): item
        for item in ((stored or {}).get("items") or [])
        if item.get("asset_id") or (item.get("run") or {}).get("status") in ("succeeded", "failed", "cancelled")
    }
    if not have:
        return incoming
    items = []
    for item in incoming["items"]:
        settled = have.get(str(item.get("id")))
        incoming_running = (item.get("run") or {}).get("status") in ("queued", "running")
        if settled and not item.get("asset_id") and settled.get("asset_id"):
            items.append({**item, "asset_id": settled["asset_id"], "run": settled.get("run", {"status": "succeeded"})})
        elif settled and incoming_running and (settled.get("run") or {}).get("status") in (
            "succeeded",
            "failed",
            "cancelled",
        ):
            # 任务结束后的下一次自动保存，客户端手里往往还是提交前的 running 快照。终态必须
            # 赢，否则它会把节点重新写活，界面就永远 loading。
            kept = {**item, "run": settled["run"]}
            # 同步便签写作没有 asset_id 可以充当「结果已到」的证据。服务端已经落下正文和
            # 清空后的表单时，晚到的 running 自动保存不能把三者一起覆盖回旧快照。
            if (settled.get("run") or {}).get("status") == "succeeded" and settled.get("kind") == "note":
                kept["text"] = settled.get("text", "")
                kept["form"] = settled.get("form", {})
            items.append(kept)
        else:
            items.append(item)
    return {**incoming, "items": items}


def delete_board(db: Session, workspace_id: str, board_id: str, *, actor_id: str | None = None) -> None:
    board = get_board(db, workspace_id, board_id)
    from app.domain.collaboration import record_activity

    record_activity(
        db,
        workspace_id=workspace_id,
        actor_id=actor_id,
        action="board.deleted",
        subject_type="board",
        subject_id=board_id,
        summary="删除了无限画布",
        payload={"name": board.name, "revision": board.revision},
    )
    db.delete(board)
    db.commit()


# ── 在画板上生成 ────────────────────────────────────────────────────────────
#
# 画板是生成能力的**第五个入口**(前四个:AI 工作台、定时任务、工作流节点、智能体)。
# 它不自己实现一遍生成 —— 照样汇进 create_generation_job 那条漏斗,于是描述符校验、
# 能力探测、计量记账、任务中心全都白拿。这一层只回答画板自己的那个问题:
# **产出该落回哪儿**。

#: 回执的种类名。任务落终态时,jobs 那边按这个名字找到下面的 deliver_generated。
RECEIPT_KIND = "board_item"


def receipt_to_item(board_id: str, item_id: str) -> dict[str, Any]:
    """建任务时写进 payload 的那一小块:这次的产出属于哪张板的哪一项。"""
    return {"kind": RECEIPT_KIND, "board_id": board_id, "item_id": item_id}


#: 服务端对**某一格**的合并(摆占位、写字、回执)在撞上并发写入时重试几次。
_MERGE_ATTEMPTS = 4


def _merge_into_latest(
    db: Session,
    *,
    workspace_id: str,
    board_id: str,
    merge: Callable[[dict[str, Any]], dict[str, Any]],
    actor_id: str | None = None,
    starts_run: bool = False,
) -> Board:
    """把服务端的一次单格改动**合到最新的画布上**,冲突就重读再合。

    客户端存回来的是整份快照,它不知道别人刚改了什么,所以按 base_revision 挡回去是对的。
    服务端这几种写入不一样:它们只改自己那一格,从最新画布出发重做一遍 `merge` 就不会覆盖
    任何人。此前它们各自带着调用方的 base_revision 去 CAS —— 于是任务已经建好(钱已经在路上)
    之后,同一个人的一次自动保存恰好先落库,占位就撞 409:任务永远排着队,画布上什么都没有。
    版本该在**花钱之前**问(见 ensure_revision),花了之后只剩「把结果放对地方」。
    """
    for attempt in range(_MERGE_ATTEMPTS):
        board = get_board(db, workspace_id, board_id)
        db.refresh(board)
        canvas = merge(dict(board.canvas or {"items": [], "edges": []}))
        try:
            return update_board(
                db,
                workspace_id=workspace_id,
                board_id=board_id,
                canvas=canvas,
                base_revision=board.revision,
                actor_id=actor_id,
                starts_run=starts_run,
            )
        except BoardRevisionConflict:
            if attempt == _MERGE_ATTEMPTS - 1:
                raise
    raise AssertionError("unreachable")


def _with_item(canvas: dict[str, Any], item_id: str, change: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    """把画布上某一格换成 `change` 之后的样子;找不到那一格就说清楚。"""
    items = [dict(one) for one in (canvas.get("items") or [])]
    index = next((i for i, one in enumerate(items) if one.get("id") == item_id), None)
    if index is None:
        raise item_not_found(item_id)
    items[index] = change(items[index])
    return {**canvas, "items": items}


def place_pending(
    db: Session,
    *,
    workspace_id: str,
    board_id: str,
    item: dict[str, Any],
    actor_id: str | None = None,
) -> Board:
    """把某一项的「正在生成」状态放到画布上,再去起任务。

    **顺序是这样的原因**:生成要几十秒,而用户点完就在看画布。先放一个占位,他立刻看得见
    "这儿在生成";等回执把 asset_id 填回来,占位就地变成图片/视频。反过来(先起任务、
    等成功再放)的话,这几十秒里画布上什么都没有,用户会以为自己没点中。

    **按 id 就地更新,不存在才追加。** 画板上的生成有两个入口:工具条上「放一个空槽去
    生成」是新建一项,而在已有的空槽里写完提示词点生成,那一项**早就在画布上**了 ——
    无脑追加会撞上同 id 的自己,用户只是点了生成,却收到一句「画板项 id 重复」。

    就地更新时**保留它已有的位置和大小**:调用方只知道「它开始生成了」,不知道用户把它
    拖到哪儿、拉多大 —— 拿请求里的默认坐标覆盖,会让节点自己跳回左上角。

    **不收 base_revision。** 调用方在建任务之前已经问过版本(ensure_revision);到这里任务
    已经建好,只剩把占位合到最新画布上(见 _merge_into_latest)。
    """

    def merge(canvas: dict[str, Any]) -> dict[str, Any]:
        items = [dict(one) for one in (canvas.get("items") or [])]
        index = next((i for i, one in enumerate(items) if one.get("id") == item.get("id")), None)
        if index is None:
            items.append(item)
        else:
            #: 位置和大小、表单归画布(用户编辑出来的),状态归这里(任务起来了)。
            keep = {k: v for k, v in item.items() if k not in ("x", "y", "width", "height")}
            merged = {**items[index], **keep}
            #: 四个状态两两互斥 —— 重新生成时旧产出、上一次的失败都让位给这次的占位。
            #: 不清的话,一个项会同时带着 run.running 和 asset_id(画布不知道该画哪个),
            #: 或者一边转圈一边挂着上次的报错(用户以为这次也挂了)。
            merged.pop("asset_id", None)
            items[index] = merged
        return {**canvas, "items": items}

    return _merge_into_latest(
        db, workspace_id=workspace_id, board_id=board_id, merge=merge, actor_id=actor_id, starts_run=True
    )


def set_text_write_run(
    db: Session,
    *,
    workspace_id: str,
    board_id: str,
    item_id: str,
    status: str,
    error: str = "",
    base_revision: int | None = None,
    actor_id: str | None = None,
) -> Board:
    """同步便签写作的运行态也落在节点内；失败时不碰表单，用户可以原样重试。

    `base_revision` 在**调模型之前**问(没花钱时拒);写入本身是单格合并。
    """
    if status not in ("running", "failed"):
        raise BoardDomainError("boardErr_textRunStatusInvalid", status=status)
    ensure_revision(get_board(db, workspace_id, board_id), base_revision)
    run = {"status": status}
    if error.strip():
        run["error"] = error.strip()[:300]
    return _merge_into_latest(
        db,
        workspace_id=workspace_id,
        board_id=board_id,
        merge=lambda canvas: _with_item(canvas, item_id, lambda item: {**item, "run": run}),
        actor_id=actor_id,
        # 上一次写挂了、这次重写:库里是 failed,不能让它把这一轮的 running 打回去。
        starts_run=status == "running",
    )


def write_text(
    db: Session,
    *,
    workspace_id: str,
    board_id: str,
    item_id: str,
    text: str,
    reset_form: bool = False,
    completed_form: dict[str, Any] | None = None,
    actor_id: str | None = None,
) -> Board:
    """把一段写好的文字放进某一项。

    **就地改,不新建** —— 调用方要写的那张便签是用户在画布上摆好的,位置、颜色、大小都归他。
    模型已经写完了(钱已经花了),所以这里是单格合并,不拿调用方的旧版本去挡。
    """

    def change(item: dict[str, Any]) -> dict[str, Any]:
        updated = {**item, "text": text}
        if reset_form:
            form = dict(completed_form if completed_form is not None else updated.get("form") or {})
            form["prompt"] = ""
            form["mentioned_asset_ids"] = []
            form.pop("prompt_document", None)
            updated["form"] = form
            updated["run"] = {"status": "succeeded"}
        return updated

    return _merge_into_latest(
        db,
        workspace_id=workspace_id,
        board_id=board_id,
        merge=lambda canvas: _with_item(canvas, item_id, change),
        actor_id=actor_id,
    )


def _canvas_with_delivered_result(
    canvas: dict[str, Any],
    *,
    item_id: str,
    asset_ids: list[str],
    job_status: str,
    job_error: str,
) -> dict[str, Any]:
    """Merge one asynchronous receipt into the newest board projection.

    The merge is deliberately pure so a compare-and-swap conflict can reload the latest canvas
    and retry without replaying any task side effects.
    """
    items = list(canvas.get("items") or [])
    kept: list[dict[str, Any]] = []
    for item in items:
        if item.get("id") != item_id:
            kept.append(item)
            continue
        if not asset_ids:
            # 失败/被取消:结束 run.running,留下这一项和它的提示词,并把原因写在上面。
            #
            # 此前是整项删掉。那让画布上的框凭空消失,连同用户刚写的提示词 —— 而他要做的
            # 下一件事十有八九是"改一个字再来一次"。留着才能重来;原因写在上面,他也不必
            # 去任务中心翻一遍才知道为什么。
            kept.append(
                {
                    **item,
                    "run": {
                        "status": "cancelled" if job_status == "cancelled" else "failed",
                        #: 「生成失败」这句话由界面说；这里只存真正原因。
                        "error": job_error[:300] or job_status,
                    },
                }
            )
            continue
        settled = dict(item)
        # 成功结束一次编辑周期：提示词和引用素材已经被消费，保留模型/参数方便继续同风格创作。
        # 失败/取消不走这里，因此原输入仍完整保留给重试。
        if isinstance(settled.get("form"), dict):
            form = dict(settled["form"])
            form["prompt"] = ""
            form["source_assets"] = []
            form["mentioned_asset_ids"] = []
            form.pop("prompt_document", None)
            settled["form"] = form
        settled["run"] = {"status": "succeeded"}
        kept.append({**settled, "asset_id": asset_ids[0]})
        #: 多出来的那几张挨着它往右排。宽度按这一项自己的宽 —— 用户可能已经把它拉大了,
        #: 用一个写死的间距会让它们叠在一起。
        step = float(settled.get("width") or 260) + 24
        #: 新格子的 id 要避开**整张板上已有的**:同一格再出一次多张时,上一轮的 `-2` 还在板上,
        #: 照序号直接拼会撞上它 —— 整次回执被 normalize 拒掉,产出一张都落不回来,这一格永远在转圈。
        #: 位置跟着序号走(第 n 格在第 n-1 列),于是也不会正好叠在上一轮那一格上。
        taken = {str(one.get("id")) for one in items}
        suffix = 1
        for extra in asset_ids[1:]:
            suffix += 1
            while f"{item_id}-{suffix}" in taken:
                suffix += 1
            extra_id = f"{item_id}-{suffix}"
            taken.add(extra_id)
            kept.append(
                {
                    **settled,
                    "id": extra_id,
                    "x": float(settled.get("x") or 0) + step * (suffix - 1),
                    "asset_id": extra,
                }
            )

    # 连线可能指着刚被摘掉的那一项 —— normalize 会拒绝悬空的线,所以先把它们去掉。
    alive = {item["id"] for item in kept}
    edges = [edge for edge in (canvas.get("edges") or []) if edge.get("source") in alive and edge.get("target") in alive]
    #: 只换 items 和 edges,**画布上别的层原样带着**(标记)。此前这里从零拼一个新字典,
    #: 于是每落回一次产出,用户放的标记就被 normalize 当成「没给」清空。
    return {**canvas, "items": kept, "edges": edges}


def deliver_generated(db: Session, job: Any, receipt: dict[str, Any]) -> None:
    """任务落终态 → 把产出填进画板上那一项。

    **成功和失败都要处理。** 失败时保留可重试的节点并结束转圈状态。

    **一次可能出多张。** 第一张落进占位，其余产出挨着它向右排列。

    **回执也遵守乐观并发。** 用户可能在任务完成的同一刻移动节点；冲突时重新读取最新画布，
    只把任务终态合并进去再 CAS，既不覆盖用户编辑，也不让已完成的结果丢失。
    """
    board_id = str(receipt.get("board_id") or "")
    item_id = str(receipt.get("item_id") or "")
    if not board_id or not item_id:
        return

    job_status = str(job.status)
    job_error = str(getattr(job, "error", "") or "")
    actor_id = getattr(job, "created_by", None)
    #: **两种形状都要读。** 生成任务一次可能出多张,给的是 asset_ids;语音合成一次只出一段,
    #: 给的是 asset_id —— 这不是新旧兼容,是两种任务本来就不同。
    result = (job.result or {}) if job_status == "succeeded" else {}
    asset_ids = [str(one) for one in (result.get("asset_ids") or []) if one]
    if not asset_ids and result.get("asset_id"):
        asset_ids = [str(result["asset_id"])]

    board = db.get(Board, board_id)
    if board is None:
        return
    _merge_into_latest(
        db,
        workspace_id=board.workspace_id,
        board_id=board.id,
        merge=lambda canvas: _canvas_with_delivered_result(
            canvas, item_id=item_id, asset_ids=asset_ids, job_status=job_status, job_error=job_error
        ),
        actor_id=actor_id,
    )
    logger.info("board %s item %s -> %s", board_id, item_id, ", ".join(asset_ids) or "(failed)")


def install() -> None:
    """把画板的回执登记进任务总线。

    **方向是反的**:任务不认识画板,是画板认识任务 —— 和智能体那条回执同一个做法
    (见 domain/agent/receipts 开头那段)。登记在组合层(app/main._wire_seams)的**导入期**,
    不在 lifespan 里:不跑 lifespan 的入口(TestClient、脚本)照样要能把产出填回画布。
    """
    from app.domain.jobs import register_receipt_deliverer

    register_receipt_deliverer(RECEIPT_KIND, deliver_generated)
