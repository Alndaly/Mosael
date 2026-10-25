"""飞书客户端的出网那一层:非 2xx 时把飞书自己的 code/msg 留下来、重发只对安全的那些开、分页不跟同一个 token 转圈。

这几条 bug 的共性是**丢了原文**:限流(HTTP 429 + code 230020)此前先 `raise_for_status()` 再 `json()`,
飞书写的 code/msg 一个都没读 —— 抛出去的是 httpx.HTTPStatusError,执行器那层的
`except LocalizedError`(见 domain/workflows/executors/feishu._Translated)也接不住,
任务失败原因里只剩一句英文的 `Client error '429 Too Many Requests' for url …`。

**打桩打在传输层**(httpx.MockTransport):真的 `RetryingClient` 还在,而"会不会重发"正是这里要测的东西之一。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx
import pytest

from app.core import http_retry
from app.core.http_retry import status_resend_is_safe
from app.core.i18n import MESSAGES, LocalizedError, t
from app.integrations.feishu import client

#: 一条用例里允许的请求上限(取令牌也算)。分页那条要是没停住,这里当场炸,而不是把测试挂死。
_REQUEST_GUARD = 12

Answer = Callable[[], httpx.Response]


@dataclass(frozen=True)
class _Bot:
    """`client` 只读这三格;令牌缓存按 id 分,所以每条用例给一个新的 id。"""

    id: str
    app_id: str = "cli_test"
    app_secret: str = "s"


def _json(status: int, payload: dict) -> Answer:
    return lambda: httpx.Response(status, json=payload)


def _token_ok() -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "tenant_access_token": "t-1", "expire": 7200})


def _is_token(request: httpx.Request) -> bool:
    return request.url.path.endswith("/tenant_access_token/internal")


def _paths(seen: list[httpx.Request], needle: str) -> list[httpx.Request]:
    return [one for one in seen if needle in one.url.path]


@pytest.fixture(autouse=True)
def _retries_on():
    """这几条测的正是「会不会重发」,而重试次数是**进程级**的(别的用例可能把它写成 0,见 core.http_retry.set_max_retries)。"""
    before = http_retry.current_max_retries()
    http_retry.set_max_retries(3)
    yield
    http_retry.set_max_retries(before)


@pytest.fixture
def wire(monkeypatch):
    """把传输换成按脚本回答的那一份。**不换 RetryingClient** —— 重试那一层要真的跑。"""

    def install(*answers: Answer, token: Answer | None = None) -> list[httpx.Request]:
        seen: list[httpx.Request] = []
        others = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal others
            seen.append(request)
            if len(seen) > _REQUEST_GUARD:
                raise AssertionError(f"出网请求超过 {_REQUEST_GUARD} 次,是不是没停下来?{request.url}")
            if _is_token(request):
                return (token or _token_ok)()
            at = min(others, len(answers) - 1) if answers else 0
            others += 1
            return answers[at]()

        class _Scripted(client.RetryingClient):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = httpx.MockTransport(handler)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(client, "RetryingClient", _Scripted)
        return seen

    return install


# ---------------- ① 非 2xx:飞书的 code/msg 一个都不许丢 ----------------


def test_非2xx时飞书的code与msg都留在错误里(wire) -> None:
    """限流:HTTP 429 + body 里是飞书自己的 `code: 230020`。

    此前这条路抛 httpx.HTTPStatusError:code/msg 全丢、不是 LocalizedError、执行器翻不动,
    失败原因里只剩 `Client error '429 Too Many Requests' for url '…'`。
    """
    wire(_json(429, {"code": 230020, "msg": "too many request"}))

    with pytest.raises(client.FeishuError) as raised:
        client.send_text(_Bot("b-429"), "oc_1", "你好")

    exc = raised.value
    assert isinstance(exc, LocalizedError), "执行器那层只认 LocalizedError(见 executors/feishu._Translated)"
    assert exc.key == "feishuErr_sendText"
    assert "230020" in str(exc), str(exc)
    assert "too many request" in str(exc), str(exc)
    assert str(exc.params.get("code")) == "230020", exc.params
    assert exc.params.get("status") == 429, exc.params
    assert "Client error" not in str(exc), f"不该再把 httpx 那句英文裸奔出来:{exc}"
    assert "429" in str(exc), str(exc)


def test_HTTP200但code非0时msg与code照样在错误里(wire) -> None:
    """业务错误的大宗是 **HTTP 200 + code≠0**(这条路一直是好的)。改了非 2xx 那条路之后它必须还是原样:
    code 与 msg 都在错误里,而不是被新逻辑吞掉 —— 这一串 bug 的共性就是"丢了原文"。"""
    wire(_json(200, {"code": 230002, "msg": "bot is not in the chat"}))

    with pytest.raises(client.FeishuError) as raised:
        client.send_text(_Bot("b-biz"), "oc_1", "你好")

    exc = raised.value
    assert exc.key == "feishuErr_sendText"
    assert str(exc.params.get("code")) == "230002", exc.params
    assert "bot is not in the chat" in str(exc), str(exc)
    assert "status" not in exc.params, "HTTP 200 就别编一个状态码出来"


def test_非2xx时网关回的不是JSON_也带上原文(wire) -> None:
    """502 的 HTML(不是飞书答的):原文截一段带出来,别只说"失败了"。"""
    wire(lambda: httpx.Response(502, text="<html>bad gateway</html>"))

    with pytest.raises(client.FeishuError) as raised:
        client.send_text(_Bot("b-html"), "oc_1", "你好")

    exc = raised.value
    assert exc.key == "feishuErr_sendText"
    assert "bad gateway" in str(exc), str(exc)
    assert exc.params.get("status") == 502, exc.params


# ---------------- ② 重发:GET 会重发,POST 发消息绝不重发 ----------------


def test_列群遇到限流会重发_确实发了两次(wire) -> None:
    """列群是 GET:第一次 429、第二次成功。此前 `max_retries=0`,一次限流直接判这个节点失败。"""
    seen = wire(
        _json(429, {"code": 230020, "msg": "too many request"}),
        _json(200, {"code": 0, "data": {"items": [{"chat_id": "oc_a", "name": "甲群"}], "has_more": False}}),
    )

    assert client.list_chats(_Bot("b-get"), limit=10) == [{"id": "oc_a", "name": "甲群"}]
    assert len(_paths(seen, "/chats")) == 2, "429 之后要再来一次(GET 是幂等的)"


def test_列群遇到网关5xx也会重发(wire) -> None:
    """5xx 是瞬时的,而 GET 重发一遍不会多做一件事 —— 只有非幂等的那些才要收紧到 0(见 `_resend_budget`)。"""
    seen = wire(
        _json(500, {"code": 99991400, "msg": "internal error"}),
        _json(200, {"code": 0, "data": {"items": [{"chat_id": "oc_a", "name": "甲群"}], "has_more": False}}),
    )

    assert client.list_chats(_Bot("b-500"), limit=10) == [{"id": "oc_a", "name": "甲群"}]
    assert len(_paths(seen, "/chats")) == 2, "500 之后要再来一次"


def test_发消息遇到限流不重发_不会出现两条(wire) -> None:
    """**发消息不自动重发。**

    飞书消息 API 最常见的限流回法就是 429 + code 230020,而仓库那条判据对它是**放行**的 ——
    `status_resend_is_safe` 判的是"供应商会不会多做一次并多收一次钱",不是"群里会不会多一条"。
    所以飞书这一层自己收紧:发消息(会留下可见副本的那些)一律 0 次重试。
    """
    #: 判据本身确实会放行 —— 这正是必须在飞书这一层再收紧一层的原因。
    assert status_resend_is_safe(httpx.Request("POST", client.SEND_URL), 429) is True

    seen = wire(_json(429, {"code": 230020, "msg": "too many request"}))

    with pytest.raises(client.FeishuError) as raised:
        client.send_text(_Bot("b-post"), "oc_1", "只该发一次")

    assert raised.value.key == "feishuErr_sendText"
    assert len(_paths(seen, "/messages")) == 1, "重发一次就是群里多一条消息"


def test_发卡片遇到限流也不重发(wire) -> None:
    """卡片同一条规矩(也是往群里发东西)。"""
    seen = wire(_json(429, {"code": 230020, "msg": "too many request"}))

    with pytest.raises(client.FeishuError):
        client.send_card(_Bot("b-card"), "oc_1", {"header": {}})

    assert len(_paths(seen, "/messages")) == 1, "重发一次就是群里多一张卡片"


# ---------------- ③ 取令牌:非 JSON 也是我们的错;令牌失效的两个码都换一次 ----------------


def test_取令牌遇到网关的HTML不再是JSONDecodeError(wire) -> None:
    """网关 / 门户页回 HTML 时,此前 `response.json()` 抛 JSONDecodeError —— 同样不是 LocalizedError,
    执行器接不住,失败原因里连状态码都没有。"""
    wire(token=lambda: httpx.Response(502, text="<html>bad gateway</html>"))

    with pytest.raises(client.FeishuError) as raised:
        client.send_text(_Bot("b-tokenhtml"), "oc_1", "你好")

    exc = raised.value
    assert exc.key == "feishuErr_token"
    assert "502" in str(exc), str(exc)
    assert "bad gateway" in str(exc), str(exc)


def test_取令牌遇到限流会重发_取令牌没有可见副本(wire) -> None:
    """取令牌是 POST,但重发只是再拿一个令牌 —— 没有"群里多一条"这回事,所以按仓库那套:
    非幂等请求只在对方明说没处理这一次(429 / 503 / 529)时重发。

    **次数是飞书自己的**(`FEISHU_MAX_RESENDS`),不是设置页那个数:这里把设置页写成 0,
    取令牌照样重发到飞书自己的上限(见下一条)。
    """
    http_retry.set_max_retries(0)  # 设置页那一栏 —— 和"要不要再取一次令牌"没有关系
    seen = wire(token=_json(429, {"code": 99991400, "msg": "too many request"}))

    with pytest.raises(client.FeishuError) as raised:
        client.send_text(_Bot("b-token429"), "oc_1", "你好")

    assert raised.value.key == "feishuErr_token"
    assert len(_paths(seen, "tenant_access_token")) == 1 + client.FEISHU_MAX_RESENDS, (
        "429 明说没处理,取令牌可以再来一次 —— 而次数是飞书自己的上限"
    )


@pytest.mark.parametrize("setting", [0, 9])
def test_取令牌的次数不跟设置页那个数走(setting) -> None:
    """**取令牌那条 POST 此前直接读 `current_max_retries()`** —— 那是 `AiRuntimeConfig.max_retries`,
    也就是设置页「AI 连接」那一栏:调成 0 就一次都不再取令牌,调成 9 就在取令牌上退避九轮。

    飞书这一侧现在整个独立:会留下可见副本的那些是 0,GET 与取令牌都读 `FEISHU_MAX_RESENDS`,
    设置页写 0 还是 9 都一个样。
    """
    http_retry.set_max_retries(setting)

    assert client._resend_budget("POST", client.TOKEN_URL) == client.FEISHU_MAX_RESENDS, (
        f"设置页写成 {setting},取令牌的重发次数就跟着变了 —— 那一栏管的是 AI 连接"
    )
    assert client._resend_budget("GET", f"{client.CHATS_URL}?page_size=100") == client.FEISHU_MAX_RESENDS, (
        "GET 那一条本来就是飞书自己的上限,改这一处时别把它带回去"
    )
    assert client._resend_budget("POST", client.SEND_URL) == 0, "会留下可见副本的那些照旧一次都不重发"


@pytest.mark.parametrize("code", [99991663, 99991664])
def test_令牌失效的两个码都会换一个令牌再来一次(wire, code) -> None:
    """`99991663`(租户访问令牌无效)与 `99991664`(应用访问令牌无效,官方 SDK 错误码表里是它的兄弟)。

    非 2xx 的 401 也走这条路 —— 此前 `raise_for_status()` 先抛,这条路根本走不到。
    """
    seen = wire(
        _json(401, {"code": code, "msg": "token invalid"}),
        _json(200, {"code": 0, "data": {"message_id": "om_2"}}),
    )

    assert client.send_text(_Bot(f"b-refresh-{code}"), "oc_1", "你好") == "om_2"
    assert len(_paths(seen, "tenant_access_token")) == 2, "被拒之后要重新取一次令牌"
    assert len(_paths(seen, "/messages")) == 2, "拿着新令牌再发一次(第一次根本没发出去)"


# ---------------- ④ 下载:二次 401 之后 body 里的 code/msg 也要带出来 ----------------


def test_下载二次401后body里的code与msg都带出来(wire) -> None:
    """401 → 换令牌 → 还是 401。此前只留一个状态码,而 body 里飞书写着 code/msg。

    文案有**两个**槽:`{status}` 是 `HTTP 401`(不再把原文拼进去),`{detail}` 是飞书自己那句
    `code 99991664: app access token invalid`。原文一个字不丢,而"状态码"那一格说的一直是状态码。
    """
    seen = wire(
        _json(401, {"code": 99991663, "msg": "token expired"}),
        _json(401, {"code": 99991664, "msg": "app access token invalid"}),
    )

    with pytest.raises(client.FeishuError) as raised:
        client.download_message_resource_named(_Bot("b-dl"), "om_9", "file_v2_deadbeef", "image")

    exc = raised.value
    assert exc.key == "feishuErr_download"
    assert exc.params.get("status") == "HTTP 401", exc.params
    assert exc.params.get("detail") == "code 99991664: app access token invalid", exc.params
    assert t(exc.key, "zh", **exc.params) == "下载飞书资源失败(HTTP 401 · code 99991664: app access token invalid)"
    assert "99991664" in str(exc), str(exc)
    assert "app access token invalid" in str(exc), str(exc)
    assert len(_paths(seen, "/resources/")) == 2, "401 之后换一次令牌再取"


def test_下载失败的文案真的有一个放原文的槽() -> None:
    """`feishuErr_download` 此前只有一个 `{status}` 槽:文案里根本没有放飞书原文的地方,于是 client
    把 code/msg 拼进了状态码那一格(`HTTP 401 · code 99991664: …`)。

    **先红就是这一条**:没有 `{detail}` 槽时 `t()` 对多出来的参数视而不见 —— 这句模板渲染出来
    只剩状态码,飞书写的原文一个字都不在。
    """
    for locale in ("zh", "en"):
        assert "{detail}" in MESSAGES["feishuErr_download"][locale], MESSAGES["feishuErr_download"]

    assert t(
        "feishuErr_download", "zh", status="HTTP 401", detail="code 99991664: app access token invalid"
    ) == "下载飞书资源失败(HTTP 401 · code 99991664: app access token invalid)"


def test_飞书5xx最多重发两次(wire) -> None:
    """飞书这一侧的重发上限是 **2**(不含首次):设置页那个数是**AI 连接**的、缺省 3,跟着它走的话
    5xx 风暴下 `list_chats` 要多等一轮退避 —— 而用户在那几十秒里只看到"群列表转圈"。
    """
    seen = wire(_json(500, {"code": 99991400, "msg": "internal error"}))

    with pytest.raises(client.FeishuError):
        client.list_chats(_Bot("b-cap-default"), limit=10)

    assert len(_paths(seen, "/chats")) == 3, "首次 + 最多 2 次重发(此前跟着设置页的 3,是 4 次)"


def test_飞书5xx的上限不跟设置页那个数走(wire) -> None:
    """**独立上限**:设置页把 `max_retries` 调到 0,飞书这一层照样有自己的 2 次 —— 那一栏管的是
    AI 连接,和"列群要不要再问一次"没有关系。"""
    http_retry.set_max_retries(0)
    seen = wire(_json(500, {"code": 99991400, "msg": "internal error"}))

    with pytest.raises(client.FeishuError):
        client.list_chats(_Bot("b-cap-zero"), limit=10)

    assert len(_paths(seen, "/chats")) == 3, "首次 + 最多 2 次重发"


# ---------------- ⑤ 文件名:缺 Content-Disposition 时按 content-type 给扩展名 ----------------


@pytest.mark.parametrize(
    ("content_type", "kind", "expected"),
    [
        ("video/mp4", "file", "feishu-deadbeef.mp4"),
        ("application/pdf", "file", "feishu-deadbeef.pdf"),
        ("audio/mpeg", "file", "feishu-deadbeef.mp3"),
        ("application/x-thing", "file", "feishu-deadbeef"),
        ("", "image", "feishu-deadbeef.jpg"),
    ],
)
def test_缺Content_Disposition时按content_type给扩展名(wire, content_type, kind, expected) -> None:
    """素材库按名字/类型认种类(见 media/probe.guess_kind):没有扩展名的 `feishu-xxxxxxxx`
    会先被当成视频去探测,然后被拒收。**推不出就保持原样** —— 不编。"""
    headers = {"content-type": content_type} if content_type else {}
    wire(lambda: httpx.Response(200, content=b"\x00\x01", headers=headers))

    got = client.download_message_resource_named(_Bot(f"b-name-{content_type or 'none'}"), "om_5", "file_v2_deadbeef", kind)

    assert got.filename == expected, got.filename


def test_有Content_Disposition时还是用飞书给的名字(wire) -> None:
    """老路不动:飞书给了原名就用原名(不因为我们认出了 content-type 就去改它)。

    头里只能放 ASCII(HTTP 头就是这个规矩),所以这里给一个英文名。
    """
    wire(
        lambda: httpx.Response(
            200,
            content=b"\x00\x01",
            headers={"content-type": "video/mp4", "content-disposition": 'attachment; filename="clip.mp4"'},
        )
    )

    got = client.download_message_resource_named(_Bot("b-name-given"), "om_5", "file_v2_deadbeef", "file")

    assert got.filename == "clip.mp4"
    assert got.content_type == "video/mp4"


# ---------------- ⑥ 分页:同一个 page_token 不跟第二次 ----------------


def test_分页遇到重复的page_token就停(wire) -> None:
    """服务端 `has_more=true` 却一直回同一个 token 时,此前会一直拉下去(每次都是同一页)。"""
    same = "t-same"

    def page(name: str) -> Answer:
        """一页:has_more 一直为真,page_token 一直是同一个。"""
        return _json(
            200,
            {
                "code": 0,
                "data": {"items": [{"chat_id": f"oc_{name}", "name": name}], "has_more": True, "page_token": same},
            },
        )

    seen = wire(page("a"), page("b"))

    assert client.list_chats(_Bot("b-page"), limit=100) == [
        {"id": "oc_a", "name": "a"},
        {"id": "oc_b", "name": "b"},
    ]
    assert len(_paths(seen, "/chats")) == 2, "见过这个 token 就该停,不再要第三页"


def test_网络错误统一变成飞书错误(monkeypatch) -> None:
    """httpx 的 ConnectError/ReadTimeout 不能穿过所有 `except FeishuError` 的降级层。"""
    from app.integrations.feishu import client as feishu_client

    def handler(request: httpx.Request) -> httpx.Response:
        if _is_token(request):
            return _token_ok()
        raise httpx.ConnectError("network down", request=request)

    class _Scripted(feishu_client.RetryingClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(feishu_client, "RetryingClient", _Scripted)
    with pytest.raises(feishu_client.FeishuError) as caught:
        feishu_client.send_text(_Bot("b-network"), "oc_x", "hello")

    assert caught.value.key == "feishuErr_network"
    assert "network down" in str(caught.value)


def test_凭据轮换后旧_token_立即失效() -> None:
    bot = _Bot("b-token-rotate")
    client._token_cache[bot.id] = ("old-token", 10**12)
    client.invalidate_token(bot.id)
    assert bot.id not in client._token_cache


def test_文本和卡片请求体超限在出网前就失败() -> None:
    with pytest.raises(client.FeishuError) as text_error:
        client.send_text(_Bot("b-too-long-text"), "oc_x", "字" * 200_000)
    assert text_error.value.key == "feishuErr_sendText"

    huge_card = {"elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "字" * 40_000}}]}
    with pytest.raises(client.FeishuError) as card_error:
        client.send_card(_Bot("b-too-long-card"), "oc_x", huge_card)
    assert card_error.value.key == "feishuErr_sendCard"


def test_下载声明超过上限直接拒绝(wire) -> None:
    wire(lambda: httpx.Response(
        200,
        content=b"tiny",
        headers={"content-type": "video/mp4", "content-length": str(client.RESOURCE_MAX_BYTES + 1)},
    ))
    with pytest.raises(client.FeishuError) as caught:
        client.download_message_resource_named(_Bot("b-big-download"), "om", "fk", "file")
    assert caught.value.key == "feishuErr_download"
