"""要发很久的响应(文件、事件流):**先把这次请求的数据库会话还掉,再开始发。**

请求的会话(`DbSession`,鉴权的 `CurrentUser` 用的也是同一个)是 yield 依赖,默认在**响应发完之后**才关;
路由里查过一次库,它就一直攥着连接池里的一条连接。普通的 JSON 响应几毫秒就发完,看不出来;而
文件和事件流要发很久 —— 浏览器的 `<video>` 播放时一条 `bytes=0-` 按播放速度慢慢读,智能体这一轮的
SSE 开到这一轮结束。实测 15 条这样的响应就把池子(5 + 10)占满,之后**所有**请求等满 30 秒报 500;
工作流引擎按「池子容量减 POOL_RESERVE」派节点,而那份预算里没有这些。

所以这类响应只从这里出:鉴权、查找都做完了,关掉会话(连接还回池子),再把响应交出去。
`tests/test_long_responses_release_the_session.py` 看着:路由里不许直接构造 `FileResponse` / `StreamingResponse`。
"""

from __future__ import annotations

from collections.abc import AsyncIterable, Iterable
from os import PathLike
from typing import Any

from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session


def file_response(db: Session, path: str | PathLike[str], **kwargs: Any) -> FileResponse:
    """发一个文件。`db` 是这次请求的会话:发之前关掉(之后再用它会重新取一条连接,所以别在这之后再查库)。"""
    db.close()
    return FileResponse(path, **kwargs)


def event_stream(db: Session, content: AsyncIterable[Any] | Iterable[Any], **kwargs: Any) -> StreamingResponse:
    """发一条事件流(SSE)。理由同上:流开多久,连接就被攥多久。"""
    db.close()
    return StreamingResponse(content, **kwargs)


__all__ = ["event_stream", "file_response"]
