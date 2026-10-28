"""清除元数据(ADR 0062)的对外入口:点一下排任务、读上一次的对账文本。

领域逻辑全在 `domain/media/scrub`(重封装、原地改码流、门禁、对账)—— 这里只做三件事:鉴权、
把领域错误翻成 HTTP、把接口形状收窄。**「导出时勾选」那条路以后走的是同一个 `POST`**:
前端把 `provenance` 开关的值放进请求体,拿回来的还是这条 `JobOut`。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas import JobOut, ScrubAssetRequest, ScrubReportOut
from app.db.models import Job
from app.domain.assets import use_cases
from app.domain.assets.scrub.engine import ScrubError

router = APIRouter(tags=["scrub"])


@router.post("/assets/{asset_id}/scrub", response_model=JobOut)
def start_scrub(asset_id: str, body: ScrubAssetRequest, db: Tx, user: CurrentUser) -> Job:
    """排一条「清除元数据」后台任务,返回这条任务(照 `/convert-gif`、`/shots` 那条既有形状)。

    产出是一份**新的**派生素材:画面和声音逐字节等于原片,去掉的是容器标签、GPS、设备/软件、
    账号/ID、封面、数据轨(遥测 / 时间码),以及 `ffprobe` 看不见的三层(H.264/H.265 的
    user-data SEI、AAC 帧里的 `DSE` / 填充元素、`compressorname`)。原素材一个字节不动。

    `provenance=true` 时连 AI 生成标记(C2PA)一起清 —— 那是另一个开关,**默认关**,理由见
    `domain/media/scrub/policy.PROVENANCE`。做完在任务中心看得到,结果里有对账文本和十道门;
    素材详情读 `GET /assets/{id}/scrub-report`。
    """
    try:
        return use_cases.start_scrub(db, user, asset_id, provenance=body.provenance)
    except ScrubError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/assets/{asset_id}/scrub-report", response_model=ScrubReportOut)
def read_scrub_report(asset_id: str, db: DbSession, user: CurrentUser) -> dict:
    """这份素材上一次清除元数据的对账文本。**没清过是 200 + `status="none"`**,不是 404 ——
    「还没清过」和「看不到这份素材」是两件事(和镜头表同一个态度)。"""
    return use_cases.scrub_report(db, user, asset_id)
