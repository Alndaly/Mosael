from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import AsrModelOut
from app.domain.permissions import ensure_deployment_admin
from app.domain.voices import transcription
from app.ai.runtime import asr_models
from app.core.i18n import normalize_locale, translate_fields

router = APIRouter(tags=["asr"])


@router.get("/asr/models", response_model=list[AsrModelOut])
def list_asr_models(request: Request, user: CurrentUser) -> list[dict]:
    """Downloadable transcription models with install/download status."""
    # 目录里存的是 key,**在出口翻译**(见 core/i18n):领域数据不必知道语言。
    locale = normalize_locale(request.headers.get("accept-language"))
    return [translate_fields(row, ("label", "detail", "message"), locale) for row in asr_models.list_status()]


@router.post("/asr/models/{model_id}/download", response_model=AsrModelOut)
def download_asr_model(model_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Deliberately (pre-)download a model in the external ASR interpreter."""
    # 下载模型是往**后端主机**上装东西 —— 部署级动作,不属于任何工作区。
    ensure_deployment_admin(db, user)
    try:
        return asr_models.start_download(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="未知模型") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


#: 一次听写最多收多少字节。**上限要在读之前就有** —— 先收进内存再判等于把这道闸交给上传方。
#: 120 秒的 opus 大约 1 MB,给到 12 MB 已经把各种码率都罩住了。
DICTATION_MAX_BYTES = 12 * 1024 * 1024


@router.post("/asr/dictate")
async def dictate(
    user: CurrentUser,
    clip: UploadFile = File(...),
    language: str = Form(default=""),
    engine: str = Form(default=""),
) -> dict[str, str]:
    """把一小段录音转成文字,**用完即弃**。

    输入框里的语音输入走这条:它不建任务、不入素材库 —— 用户要的是"把我说的话填进去",
    而不是在素材库里留下几十个几秒钟的 wav。识别本身仍是同一份实现(常驻 worker)。

    没有 workspace 参数:这段音频不属于任何工作区,它连库都不进。鉴权到"是个登录用户"为止。
    """
    with tempfile.TemporaryDirectory(prefix="mosael-dictate-in-") as tmp:
        raw = Path(tmp) / (Path(clip.filename or "clip").name or "clip")
        size = 0
        with raw.open("wb") as out:
            while chunk := await clip.read(1024 * 256):
                size += len(chunk)
                if size > DICTATION_MAX_BYTES:
                    # 边读边判:读完再判的话,上限拦住的只是"用不用",不是"收不收"。
                    raise HTTPException(status_code=413, detail="录音太大了,听写请说短一点。")
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=422, detail="没有收到音频")
        try:
            return {"text": transcription.transcribe_clip(raw, language=language, engine=engine)}
        except transcription.DictationTooLong as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except transcription.ASRError as exc:
            # 识别失败是**结果**,不是服务端故障 —— 说清楚原因,让界面能原样显示。
            raise HTTPException(status_code=422, detail=str(exc)) from exc
