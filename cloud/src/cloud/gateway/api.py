"""网关的 HTTP 入口。第 1 步只有「这枚令牌是谁」(桌面端「测试连接」用);目录、对话、任务随后续步骤加。"""

from __future__ import annotations

from fastapi import APIRouter

from cloud.domain.device_tokens import device_token_view
from cloud.domain.identity import account_user
from cloud.gateway.deps import CurrentDevice

router = APIRouter(prefix="/gateway", tags=["gateway"])


@router.get("/me")
def whoami(device: CurrentDevice) -> dict[str, object]:
    return {"user": account_user(device.user), "device": device_token_view(device.token)}

