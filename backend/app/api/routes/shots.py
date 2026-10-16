"""拆镜头(ADR 0061 §5)的对外入口:点一下排任务、读这份视频的镜头表、取逐镜的帧图。

领域逻辑全在 `domain/shots`(量、取帧、判、存取)和 `domain/analysis/shots_task`(排任务、挑视觉模型)——
这里只做三件事:鉴权、把领域错误翻成 HTTP、把接口形状收窄。**别处没有同义的入口**:工作流的三个节点
(`detect_shots` / `describe_shots` / `shot_report`)是工作流里的路,人点的那条走这里,两条都落在
同一张 `shot_breakdowns` 上(素材详情页和分析读的也是它)。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.responses import file_response
from app.api.schemas import JobOut, ShotBreakdownResponse
from app.core.i18n import tr
from app.db.models import Job
from app.domain.assets import use_cases
from app.domain.shots import breakdowns

router = APIRouter(tags=["shots"])


@router.post("/assets/{asset_id}/shots", response_model=JobOut)
def start_shot_breakdown(asset_id: str, db: Tx, user: CurrentUser) -> Job:
    """排一条「拆镜头」后台任务,返回这条任务(照 `/transcribe`、`/convert-gif` 那条既有形状)。

    量刀口取帧不花钱;有视觉模型就接着逐镜判画面(一批一次调用)。做完在任务中心看得到,素材详情页那一块
    读 `GET /assets/{id}/shots`。**重拆覆盖**同一张表(ADR 0061 待拍板 2),没有历史版本。
    """
    try:
        return use_cases.start_shots(db, user, asset_id)
    except breakdowns.ShotBreakdownError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/assets/{asset_id}/shots", response_model=ShotBreakdownResponse)
def read_shot_breakdown(asset_id: str, db: DbSession, user: CurrentUser) -> dict:
    """这份视频的镜头表。**没拆过是 200 + `status="none"`**,不是 404 —— 「还没拆」和「看不到这份素材」
    是两件事,界面据此决定显示「拆镜头」按钮还是那一列镜头。"""
    return use_cases.shot_breakdown(db, user, asset_id)


@router.get("/assets/{asset_id}/shots/frames/{name}")
def read_shot_frame(asset_id: str, name: str, db: DbSession, user: CurrentUser) -> FileResponse:
    """这一镜的帧图(详情页列表里的缩略图),名字是 `S03a.jpg`(15%)/ `S03b.jpg`(85%)。

    帧是镜头表的插图,不进素材库;素材删了目录一起走。名字不在这个形状里 —— 或者那一镜没取到帧 ——
    都是 404。
    """
    asset = use_cases.readable(db, user, asset_id)
    path = breakdowns.frame_file(asset, name)
    if path is None:
        raise HTTPException(status_code=404, detail=tr("routeErr_shotFrameNotFound"))
    return file_response(db, path, media_type="image/jpeg")
