"""对象存储插件的「接入点」必须是一个主机名 —— 填成地域时当场说清楚,而不是报一句 SSL 错误。

真机上撞到的:阿里云 OSS 的「端点」填了 `cn-shanghai`(那是地域)。插件照原样拼出
`mosael.cn-shanghai` 去连,本该是 DNS 解析失败 —— 而机器上开着代理,代理接下了这个不存在的
域名再断开,用户看到的是:

    连不上对象存储:[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol

一句看不出「地址填错了」的话。修在两处:接入点不像主机名就当场拒并说怎么填;网络失败时
报出连的是哪个主机。几家共用同一份 storage.py,所以用阿里云那一格测一份。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "object-storage" / "tools"


def _run(env: dict[str, str], tool: str = "storage_list", payload: dict | None = None) -> dict:
    done = subprocess.run(
        [sys.executable, str(TOOLS / "main.py")],
        input=json.dumps({"tool": tool, "input": payload or {}, "locale": "zh"}),
        capture_output=True, text=True, cwd=TOOLS, timeout=30,
        env={"PATH": "/usr/bin:/bin", "STORAGE_PROVIDER": "aliyun-oss", "STORAGE_BUCKET": "mosael",
             "STORAGE_REGION": "cn-shanghai", "STORAGE_ACCESS_KEY_ID": "ak", "STORAGE_ACCESS_KEY_SECRET": "sk", **env},
    )
    return json.loads(done.stdout)


def test_把地域填进接入点_当场说清楚() -> None:
    """就是真机上那份配置。"""
    result = _run({"STORAGE_ENDPOINT": "cn-shanghai"})

    assert result["ok"] is False
    assert "cn-shanghai" in result["error"] and "不是一个域名" in result["error"], result
    assert "SSL" not in result["error"]


@pytest.mark.parametrize("endpoint", [
    "https://oss-cn-shanghai.aliyuncs.com/",
    "oss-cn-shanghai.aliyuncs.com/some/path",
])
def test_贴进来的整条URL_只取主机名(endpoint: str) -> None:
    result = _run({"STORAGE_ENDPOINT": endpoint}, tool="storage_presign", payload={"key": "a.mp4"})

    assert result["ok"] is True, result
    assert result["output"]["url"].startswith("https://mosael.oss-cn-shanghai.aliyuncs.com/a.mp4?")


@pytest.mark.parametrize("endpoint", ["localhost:9000", "minio:9000", "localhost"])
def test_自建服务的地址不被当成地域(endpoint: str) -> None:
    """S3 兼容服务(MinIO)的地址没有点号,但带端口或就是 localhost。"""
    result = _run({"STORAGE_PROVIDER": "s3-compatible", "STORAGE_ENDPOINT": endpoint},
                  tool="storage_presign", payload={"key": "a.mp4"})

    assert result["ok"] is True, result


def test_连不上时报出连的是哪个主机(monkeypatch: pytest.MonkeyPatch) -> None:
    sys.path.insert(0, str(TOOLS))
    try:
        import providers
        import storage
    finally:
        sys.path.pop(0)

    monkeypatch.setattr(storage, "_sleep", lambda _seconds: None)  # 连不上会按退避重试几次,不必真等
    bucket = storage.Bucket(provider=providers.PROVIDERS["s3-compatible"], bucket="b", region="us-east-1",
                            endpoint="http://127.0.0.1:9", access_key="ak", secret="sk")
    with pytest.raises(storage.StorageError) as caught:
        bucket.listing()
    assert "127.0.0.1" in str(caught.value)
