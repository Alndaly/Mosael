"""改 ComfyUI 工作台画布上开着的那一张 —— 这张卡(ADR 0042 拍板 3:先摆出改动清单,点「应用」才改到画布上)。

开卡之前(validate)插件就对着画布上这张算过一遍:每一条都查过、改完不多出错误,卡上的改动清单、子图用了几处、改前改后的
诊断都写进了 payload(见 workbench_agent.propose_edit)。**开卡时画布一点没动。** 批准之后对着现在的画布再算一遍,对得上才
交给桥,整批只占一步撤销(Ctrl+Z 就退回去)。

档位是 `edit`:最坏也撤得回 —— 一次 Ctrl+Z。没有自动放行的口子要它自己开:手动模式下每一张都要人点「应用」,用户自己把对话
设成自动 / 跳过时,和别的 edit 档一样按他的设定走。

另外三张是 ADR 0042 第三步(由智能体起头,都要点头):

- **下载模型**(`comfy_model_download`)—— 下到那台 ComfyUI 的磁盘上,几十 GB 也常有。开卡之前先问插件这个链接是哪个文件、
  多大、那边是不是已经有了;认不出、文件名对不上、已经有的都不开卡。卡上写文件名、目录、大小、哪台机器。
- **装节点包**(`comfy_node_pack_install`)—— 装的是**别人写的、之后在那台机器上跑的代码**,还要重启 ComfyUI(正在跑的任务
  会中断),所以是 `external`。开卡之前现查注册表:git 地址、`Flagged` / `Banned`、没有正常版本、装着同一版的不开卡;
  发行者、版本、要不要动 PyTorch、和这台机器合不合都写上。
- **试跑画布上这张**(`comfy_canvas_run`)—— 用的是那台机器的显卡(远程那台是别人的),和 `render_sequence` 同一档。
  画布上这张**从没存过**的不开卡(运行要一张这个连接下的生成模型)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import fragment
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError


def _user(db: Session, actor: str | None):
    from app.db.models import User

    user = db.get(User, actor) if actor else None
    if user is None:
        raise ConfirmationError("confirmErr_approverNotFound")
    return user


def _validate(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    from app.domain import workbench_agent

    workbench_agent.propose_edit(db, _user(db, actor), workspace_id, payload)


def _summarize(db: Session, payload: dict[str, Any]) -> Summary:
    workflow = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else {}
    #: 改的子图在这张图里用了不止一处:改的是定义,每一处都会变 —— 这半句单独成一条提示(卡上的 warning)
    shared = sorted((one for one in payload.get("subgraphs") or [] if isinstance(one, dict) and int(one.get("uses") or 0) > 1),
                    key=lambda one: -int(one.get("uses") or 0))
    warning = fragment("confirm_comfySubgraphUses", name=str(shared[0].get("name") or ""), uses=int(shared[0].get("uses") or 0)) \
        if shared else ""
    return "confirm_comfyCanvasEdit", {
        "name": str(workflow.get("name") or workflow.get("key") or ""),
        "count": len(payload.get("changes") or []),
        "warning": warning,
    }


def _execute(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    from app.domain import workbench_agent

    # 连接归人:用批准这张卡的那个人的连接、在他的桌面端上改(和读画布同一条路)
    return workbench_agent.apply_edit(db, _user(db, actor), confirmation.workspace_id, dict(confirmation.payload or {}))


confirmable_tool(ConfirmableTool(
    name="comfy_canvas_edit",
    permission="edit",
    cost="none",
    #: 改的是 ComfyUI 画布上开着的那一张,不在 Mosael 的库里
    writes=(),
    summarize=_summarize,
    execute=_execute,
    validate=_validate,
))


# --- 第三步:下载模型、装节点包、试跑(ADR 0042 拍板 4、5) --------------------------------------


def _download_validate(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    from app.domain import workbench_agent

    workbench_agent.propose_download(db, _user(db, actor), workspace_id, payload)


def _download_summarize(db: Session, payload: dict[str, Any]) -> Summary:
    from app.domain import workbench_agent

    size = workbench_agent.bytes_text(payload.get("size"))
    return "confirm_comfyModelDownload", {
        "name": str(payload.get("filename") or ""),
        "folder": str(payload.get("folder") or ""),
        #: 说不清多大就写「大小不明」—— 卡上不编一个数字,也不留一个空括号。
        "size": fragment("confirm_comfyModelSize", size=size) if size else fragment("confirm_comfyModelSizeUnknown"),
        "instance": str(payload.get("instance") or ""),
        "source": fragment("confirm_comfyModelSource", source=str(payload.get("source") or ""))
        if payload.get("source") else "",
    }


def _download_execute(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    from app.domain import workbench_agent

    return workbench_agent.start_model_download(db, _user(db, actor), confirmation.workspace_id,
                                                dict(confirmation.payload or {}))


confirmable_tool(ConfirmableTool(
    name="comfy_model_download",
    permission="external",
    cost="none",
    #: 只在那台机器上排一个下载任务;下完由任务那一侧刷新目录
    writes=(),
    summarize=_download_summarize,
    execute=_download_execute,
    validate=_download_validate,
))


def _install_validate(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    from app.domain import workbench_agent

    workbench_agent.propose_node_install(db, _user(db, actor), workspace_id, payload)


def _install_summarize(db: Session, payload: dict[str, Any]) -> Summary:
    #: 卡上要说清:装的是哪个包的哪一版、谁发布的、会不会动 PyTorch、和这台机器合不合、装完要重启。
    #: 每一句都是 `fragment`(落库时留 key,读的时候按读的人的语言翻),按语言的习惯连起来(见 core.i18n.read_param)。
    warnings = []
    if payload.get("newest_note") == "flagged":
        warnings.append(fragment("confirm_comfyPackFlagged", version=str(payload.get("newest_version") or "")))
    elif payload.get("newest_note") == "deprecated":
        warnings.append(fragment("confirm_comfyPackDeprecated", version=str(payload.get("newest_version") or "")))
    if payload.get("torch_touching"):
        warnings.append(fragment("confirm_comfyPackTorch",
                                 deps=", ".join(str(one) for one in payload["torch_touching"][:4])))
    elif str(payload.get("dependency_risk") or "") in ("medium", "high"):
        #: 会装额外的 Python 包(不是 PyTorch 那一种):也说一声它是哪一档风险。
        warnings.append(fragment("confirm_comfyPackRisk", risk=str(payload.get("dependency_risk"))))
    if payload.get("mismatched"):
        warnings.append(fragment("confirm_comfyPackMismatch", parts=", ".join(str(one) for one in payload["mismatched"])))
    if payload.get("installed_version"):
        warnings.append(fragment("confirm_comfyPackUpgrade", current=str(payload["installed_version"]),
                                 version=str(payload.get("version") or "")))
    publisher = fragment("confirm_comfyPackPublisher", publisher=str(payload.get("publisher") or "")) \
        if payload.get("publisher") else ""
    return "confirm_comfyNodePackInstall", {
        "instance": str(payload.get("instance") or ""),
        "name": str(payload.get("name") or payload.get("pack") or ""),
        "version": str(payload.get("version") or ""),
        "publisher": publisher,
        #: 合成**一个**片段:卡上的标题与后果提示只认得一个 `warning`(见 confirmations.card_parts)。
        "warning": fragment("confirm_comfyPackRisks", notes=warnings) if warnings else "",
    }


def _install_execute(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    from app.domain import workbench_agent

    return workbench_agent.install_node_pack(db, _user(db, actor), confirmation.workspace_id,
                                             dict(confirmation.payload or {}))


confirmable_tool(ConfirmableTool(
    name="comfy_node_pack_install",
    permission="external",
    cost="none",
    #: 装的是那台机器上的代码、还要重启它;Mosael 这边只起了一个任务
    writes=(),
    summarize=_install_summarize,
    execute=_install_execute,
    validate=_install_validate,
))


def _run_validate(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    from app.domain import workbench_agent

    workbench_agent.propose_canvas_run(db, _user(db, actor), workspace_id, payload)


def _run_summarize(db: Session, payload: dict[str, Any]) -> Summary:
    workflow = payload.get("workflow") if isinstance(payload.get("workflow"), dict) else {}
    node_id = str(payload.get("node_id") or "")
    return "confirm_comfyCanvasRun", {
        "instance": str(payload.get("instance") or ""),
        "name": str(workflow.get("name") or ""),
        "path": str(workflow.get("path") or ""),
        "target": fragment("confirm_comfyCanvasRunNode", node=node_id) if node_id else "",
    }


def _run_execute(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    from app.domain import workbench_agent

    return workbench_agent.run_canvas(db, _user(db, actor), confirmation.workspace_id,
                                      dict(confirmation.payload or {}))


confirmable_tool(ConfirmableTool(
    name="comfy_canvas_run",
    permission="render-cost",
    cost="render",
    #: 起的是一个普通的生成任务;产出由任务那一侧入库
    writes=(),
    summarize=_run_summarize,
    execute=_run_execute,
    validate=_run_validate,
))
