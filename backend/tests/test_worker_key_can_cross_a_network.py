"""执行器和后端不在同一台机器上时,这条通道要还能认证。

原来的证明方式是「worker 读得到本地文件」—— 后端启动时把密钥写进自己的数据目录,本机执行器
读它。这句话在同一台机器上成立,而且是**对的**:网页读不到文件,所以伪造不了那个请求头。

后端搬到服务器之后前提就没了:本机执行器读到的是自己那份(过期的,或者根本没有),远程要的
是它自己那份 —— 发布、浏览器自动化、external 模式的任务全都 401,而这三样看起来像各自坏了。

**为什么不是「用用户会话换一张 worker 令牌」。** worker 通道是全部署范围的:
`publish/worker.claim_next_pending` 认领的是任何人的待发布任务,它的注释还写着原子性依赖
"只有一个 worker"。把它挂到用户会话上,等于共享服务器上任何登录用户的执行器都能认领所有人的
任务 —— 那是提权。持有这个密钥的就是"这个部署的那一个执行器",而那正是它一直以来的语义。
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def worker_key(monkeypatch):
    """按需重新 issue —— 密钥是进程级模块状态。"""

    def issue(configured: str | None):
        module = importlib.import_module("app.core.worker_key")
        if configured is None:
            monkeypatch.delenv("MOSAEL_WORKER_KEY", raising=False)
        else:
            monkeypatch.setenv("MOSAEL_WORKER_KEY", configured)
        return module, module.issue_worker_key()

    return issue


def test_没配就还是每次随机(worker_key) -> None:
    """本机那条路不变:每进程一份新的,重启就换 —— 过期的密钥会 401 而不是静默继续能用。"""
    module, first = worker_key(None)
    _, second = worker_key(None)
    assert first != second
    assert len(first) == 64


def test_配了就用配的那一个(worker_key) -> None:
    module, key = worker_key("shared-across-the-network")
    assert key == "shared-across-the-network"
    assert module.verify_worker_key("shared-across-the-network") is True
    assert module.verify_worker_key("something-else") is False


def test_两次启动用同一个配置值就还是同一个(worker_key) -> None:
    """远程拓扑的全部意义在这儿:后端重启之后,本机那个执行器不必重新拿一次密钥。"""
    _, first = worker_key("stable-secret")
    _, second = worker_key("stable-secret")
    assert first == second == "stable-secret"


def test_配了也照样写文件(worker_key) -> None:
    """本机执行器读的还是文件 —— 两种拓扑走同一条路,不是两套实现。"""
    module, key = worker_key("also-on-disk")
    assert module.key_path().read_text(encoding="utf-8").strip() == key


def test_空白配置当作没配(worker_key) -> None:
    """`MOSAEL_WORKER_KEY=` 或者一串空格 —— 那是"没配",不是"密钥是空串"。
    当成空串的话,verify 会对任何空请求头放行。"""
    module, key = worker_key("   ")
    assert key != "   " and len(key) == 64
    assert module.verify_worker_key("") is False
    assert module.verify_worker_key(None) is False
