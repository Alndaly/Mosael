"""按秒轮询的那些请求不该刷屏。

用户的终端里是这样的,一屏全是它:

    INFO: 127.0.0.1:60926 - "POST /api/browser/worker/claim HTTP/1.1" 200 OK
    INFO: 127.0.0.1:60891 - "POST /api/publish/worker/heartbeat HTTP/1.1" 200 OK
    INFO: 127.0.0.1:60926 - "POST /api/publish/worker/claim-check HTTP/1.1" 200 OK
    …

这些是 sidecar 按定时器发的:claim(有活吗)、heartbeat(我还活着)、claim-check。它们**成功**
的时候一个字都不值得说 —— 说了反而把真正要看的那几行(任务失败、子进程 stderr)冲走。
刚补完一批业务日志,却被这个淹掉,等于没补。

判据不是"列一张噪声路径名单"(新加一个 worker 端点就又漏了),而是结构上的:
**路径里带 `/worker/` 的就是定时轮询**,这是这个仓库里 sidecar 端点的命名约定。

只压**成功**的那些。heartbeat 返 500 恰恰是最该看见的一行。
"""

from __future__ import annotations

import logging

from app.core.logging import AccessLogFilter


def _record(path: str, status: int) -> logging.LogRecord:
    """uvicorn.access 的形状:args = (client, method, path, http_version, status)。"""
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:60926", "POST", path, "1.1", status),
        exc_info=None,
    )


def test_successful_worker_polls_are_dropped() -> None:
    quiet = AccessLogFilter(quiet=True)

    for path in (
        "/api/browser/worker/claim",
        "/api/publish/worker/heartbeat",
        "/api/publish/worker/claim-check",
        "/api/jobs/worker/claim",
    ):
        assert not quiet.filter(_record(path, 200)), f"还在刷屏:{path}"


def test_a_failing_poll_still_shows() -> None:
    """heartbeat 返 500 是最该看见的一行 —— 压的是"没事发生",不是"这个端点"。"""
    quiet = AccessLogFilter(quiet=True)

    assert quiet.filter(_record("/api/publish/worker/heartbeat", 500))
    assert quiet.filter(_record("/api/browser/worker/claim", 401))


def test_ordinary_requests_are_untouched() -> None:
    quiet = AccessLogFilter(quiet=True)

    for path in ("/api/projects", "/api/assets/import", "/api/voices/upload"):
        assert quiet.filter(_record(path, 200)), f"误伤了:{path}"


def test_it_can_be_turned_off() -> None:
    """想看全量时得有路可走 —— 排查 sidecar 本身的时候就要看它们。"""
    loud = AccessLogFilter(quiet=False)

    assert loud.filter(_record("/api/browser/worker/claim", 200))


def test_a_record_of_an_unexpected_shape_is_kept() -> None:
    """看不懂的记录一律放行 —— 过滤器宁可少压一条,也不能吃掉一条不认识的日志。"""
    quiet = AccessLogFilter(quiet=True)
    weird = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "启动完成", None, None)

    assert quiet.filter(weird)


def test_configure_logging_actually_attaches_it() -> None:
    """判据要挂在**启动**上:只测 filter 类本身的话,忘了挂上去照样全绿,而终端照样刷屏。"""
    from app.core import logging as app_logging

    app_logging._configured = False
    app_logging.configure_logging()

    access = logging.getLogger("uvicorn.access")
    attached = [f for f in access.filters if isinstance(f, AccessLogFilter)]
    assert len(attached) == 1, f"没挂上,或挂了多份:{access.filters}"
    assert not attached[0].filter(_record("/api/browser/worker/claim", 200))


def test_configuring_twice_does_not_stack_filters() -> None:
    from app.core import logging as app_logging

    for _ in range(3):
        app_logging._configured = False
        app_logging.configure_logging()

    access = logging.getLogger("uvicorn.access")
    assert len([f for f in access.filters if isinstance(f, AccessLogFilter)]) == 1
