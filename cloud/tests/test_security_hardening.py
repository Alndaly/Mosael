"""本轮安全修复的回归：Cookie 前缀、上传类型、路径约束、登录限速与任务取消。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cloud.config import CloudConfig
from cloud.errors import CloudError
from cloud.gateway.jobs_api import UploadTicketIn
from cloud.generation.adapters import AdapterArtifact
from cloud.generation.storage import LocalArtifactStorage
from cloud.generation.validation import estimated_units, normalize_job_input
from cloud import login_limits


def test_secure_cloud_cookie_gets_host_prefix_but_local_http_does_not(tmp_path):
    secure = CloudConfig(data_dir=tmp_path, cookie_secure=True)
    local = CloudConfig(data_dir=tmp_path, cookie_secure=False)
    assert secure.cookie_name == "__Host-mosael_cloud_session"
    assert local.cookie_name == "mosael_cloud_session"


@pytest.mark.parametrize("mime", ["text/html", "image/svg+xml", "application/javascript"])
def test_upload_ticket_rejects_non_media(mime):
    with pytest.raises(ValidationError):
        UploadTicketIn(filename="x", mime=mime, size=1)


def test_upload_ticket_accepts_media():
    assert UploadTicketIn(filename="x.png", mime="image/png", size=1).mime == "image/png"


def test_local_storage_never_writes_outside_its_root(tmp_path):
    storage = LocalArtifactStorage(tmp_path)
    stored = storage.save(
        user_id="u", job_id="j",
        artifact=AdapterArtifact(filename="../../escape.txt", mime="text/plain", data=b"x"),
    )
    target = tmp_path / stored.storage_key
    assert target.resolve().is_relative_to(tmp_path.resolve())
    assert target.read_bytes() == b"x"


def test_job_input_is_allowlisted_and_bounded():
    with pytest.raises(CloudError):
        normalize_job_input({"prompt": "x", "n": 999})
    with pytest.raises(CloudError):
        normalize_job_input({"prompt": "x", "unknown": 1})
    assert normalize_job_input({"prompt": "x", "n": 4}) == {"prompt": "x", "n": 4}
    assert estimated_units({"image": 1}, {"n": 4}) == {"image": 4}
    assert estimated_units({"second": 5}, {"duration_seconds": 30}) == {"second": 30}


def test_login_limiter_locks_after_repeated_failures():
    login_limits.reset()
    for _ in range(login_limits.MAX_FAILURES):
        login_limits.failed("a@example.com", "1.2.3.4")
    with pytest.raises(CloudError):
        login_limits.check("a@example.com", "1.2.3.4")
    login_limits.succeeded("a@example.com", "1.2.3.4")
    login_limits.check("a@example.com", "1.2.3.4")
    login_limits.reset()
