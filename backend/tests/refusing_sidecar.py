"""假的 pi sidecar 刷新:照真的那样先 acquire,刷新失败时带着那句错误去 release(见 agent-sidecar/src/credentials.ts),
再把错误抛回来。对方明确拒绝的,后端在 release 那一下把凭据记成要重新授权。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.ai.sidecar.pi_client import SidecarError
from app.main import app

KIMI_REJECTED = (
    "ModelsError: OAuth refresh failed for kimi-coding: Kimi Code token refresh unauthorized (status 400): "
    "The provided authorization grant is invalid"
)
NETWORK_DOWN = "ModelsError: OAuth refresh failed for anthropic: fetch failed: ECONNRESET"


def refusing(message: str):
    def refresh(**kwargs):
        api = TestClient(app)
        headers = {"Authorization": f"Bearer {kwargs['token']}"}
        base = f"/api/agent/provider-credentials/{kwargs['profile_id']}"
        lease = api.post(f"{base}/acquire", headers=headers)
        assert lease.status_code == 200, lease.text
        released = api.post(f"{base}/release", json={"lease": lease.json()["lease"], "refresh_error": message}, headers=headers)
        assert released.status_code == 204, released.text
        raise SidecarError(message)

    return refresh
