"""飞书开放平台的 REST 调用:租户令牌(按机器人缓存、提前两分钟刷新)、发文字 / 卡片、
表情反应(飞书的「对方正在输入」)、取回消息里的图片与文件、列出机器人所在的群。只懂飞书,不懂 Mosael 的业务。

## 失败时要说得出飞书自己那句话

飞书的业务错误大多是 **HTTP 200 + code≠0**,但限流 / 网关 / 令牌失效是**真非 2xx** ——
消息 API 限流是 `code 230020` + HTTP 429(历史版本 400),消息流 `99991400`。所以这里**先把 body 解出来**:
非 2xx 也当成一次回答来读,`code` / `msg` / HTTP 状态码一起进 `FeishuError`(它是 `LocalizedError`,
执行器那层翻得动)。此前是先 `raise_for_status()` 再 `json()` —— 非 2xx 一律变成 httpx 的
`HTTPStatusError`:飞书写的 code/msg 一个都没读,`except LocalizedError` 也接不住,任务失败原因里
只剩一句英文的 `Client error '429 Too Many Requests' for url …`。

## 重发只对不会留下可见副本的调用开

见 `_resend_budget`:幂等的(GET 列群 / 下载)和"重发只是再拿一个令牌"的交给
`core.http_retry` 那套判据;**发消息 / 改卡片 / 加表情一律 0 次** —— 重发一遍就是群里多一条,
而 429 恰好是飞书消息 API 最常见的限流回法,仓库那条判据对它是放行的。
**次数不跟设置页那个 `max_retries` 走**:会留下可见副本的那些是 0,GET 与取令牌都用飞书自己的上限
(`FEISHU_MAX_RESENDS`)—— 设置页那一栏是 **AI 连接**的,和飞书没有关系。
"""

from __future__ import annotations

import json
import logging
import mimetypes
import threading
import time
from dataclasses import dataclass
from typing import Any, NoReturn
from urllib.parse import quote

import httpx

from app.core.http_retry import RetryingClient
from app.core.i18n import LocalizedError
from app.db.models import FeishuBot

logger = logging.getLogger(__name__)

API_BASE = "https://open.feishu.cn/open-apis"
TOKEN_URL = f"{API_BASE}/auth/v3/tenant_access_token/internal"
SEND_URL = f"{API_BASE}/im/v1/messages"
#: 机器人所在的那个群列表(`im/v1/chats`):节点上「发到某个群」和「列出机器人所在的群」都读它。
CHATS_URL = f"{API_BASE}/im/v1/chats"
#: 一页最多要几个群(飞书自己的上限)。
CHATS_PAGE_SIZE = 100


class FeishuError(LocalizedError, RuntimeError):
    """飞书这一侧没做成。带文案 key(`feishuErr_*`);飞书自己回的 msg / code 放进 `detail`。"""


#: 飞书说「你手上那个令牌不认」的两个码。`99991663` 是**租户访问令牌无效**(官方 FAQ 专门有一篇:
#: how-to-fix-99991663-error),`99991664` 是**应用访问令牌无效** —— 官方 SDK 的错误码表里它们是兄弟,
#: 而第三方客户端(openclaw 那几笔修复)两个都重试:有些接口回的是后一个。我们只持有租户令牌,
#: 所以 99991664 在这里多半用不上;真遇上了,多花的也只是"再取一次令牌",**不会多发一条消息**。
_TOKEN_INVALID = frozenset({99991663, 99991664})

#: 非 2xx 时飞书的 `code` 可能与 HTTP 状态码不是一回事(429 + code 230020)。两个都要看得见,
#: 所以解析时把状态码另记一处(见 `_fail`)。
_HTTP_STATUS = "http_status"

#: 飞书这一侧的重发上限(不含首次)。**GET 与取令牌都用它。**
#:
#: **不跟 `core.http_retry` 那个进程级次数走。** 那个数由**设置页的 AI 连接**写
#: (`AiRuntimeConfig.max_retries`,缺省 3),和飞书没有关系 —— 跟着它在这里是有代价的:列群 / 下载
#: 都是 GET,5xx 风暴下每多一次重发就多等一轮退避,`list_chats` 最长可以多花几十秒,而那几十秒里
#: 用户看到的只是"群列表转圈"。2 够用:一次瞬时抖动等得到,持续 5xx 也不会把一次列群拖成半分钟。
#:
#: **取令牌那条 POST 也读这一个。** 它此前读 `current_max_retries()` —— 那同样是设置页那一栏
#: (AI 连接的重试次数),于是"飞书要不要再取一次令牌"取决于用户把 AI 连接调成了几次:
#: 调成 0 就一次都不再取,调成 9 就在取令牌上退避九轮。取令牌没有可见副本、也不产生费用,
#: 所以它归飞书自己管:给同一个上限,飞书这一侧就没有一处再读设置页那个数了。
FEISHU_MAX_RESENDS = 2


def _json_of(response: httpx.Response) -> Any:
    """body 是 JSON 就解出来,不是就 None —— **不抛**。

    网关 / 门户页回的是 HTML,`response.json()` 会抛 JSONDecodeError;那不是 `LocalizedError`,
    执行器那层接不住(和 `HTTPStatusError` 同一个毛病,见模块说明)。
    """
    try:
        return response.json()
    except ValueError:
        return None


def _body_head(response: httpx.Response) -> str:
    """响应体开头一小段(空白压平)。说不清是不是飞书答的时候,原文比一句"失败了"有用。"""
    try:
        raw = response.text
    except Exception:  # noqa: BLE001 —— 解不出文本(二进制、编码坏)不影响给出状态码
        raw = ""
    return " ".join(raw.split())[:200]


def _detail_of(data: dict[str, Any]) -> str:
    """飞书那条回答里的 code 与 msg —— **两个都留着**。

    只说 msg 的话排查时没有错误码(限流 230020 与令牌失效 99991663 的修法完全不同);
    只说 code 的话飞书偶尔不回 msg,人看不懂。
    """
    code, msg = data.get("code"), str(data.get("msg") or "").strip()
    has_code = code is not None and str(code) != ""
    if has_code and msg:
        return f"code {code}: {msg}"
    return f"code {code}" if has_code else msg


def _payload(response: httpx.Response) -> dict[str, Any]:
    """把响应的 body 读成飞书那种 `{code, msg, data}` —— **非 2xx 也读**(见模块说明)。

    非 2xx 且 body 里带着飞书自己的 `code` 时原样交回去:让调用方按 code 说清是哪一件事,
    `msg` 一个字都不丢。说不清是不是飞书答的(网关的 HTML、门户页,或者 2xx 却不是 JSON)时
    给一份**说真话的替身**:`code` 留空(它不是飞书的业务码,别混进那个语义里),`msg` 是 body 开头一小段。
    """
    body = _json_of(response)
    if isinstance(body, dict) and "code" in body and (response.is_success or body.get("code") not in (None, 0)):
        data = body
    else:
        data = {"code": None, "msg": _body_head(response)}
    if not response.is_success:
        data[_HTTP_STATUS] = response.status_code
    return data


def _fail(key: str, data: dict[str, Any]) -> NoReturn:
    """飞书拒了这一趟:把 code / msg / HTTP 状态一起放进错误里,并换成我们的文案 key。

    这是这一串 bug 的收敛点 —— 此前非 2xx 抛的是 httpx.HTTPStatusError,`code` 与 `msg` 从来没被读过,
    执行器那层的 `except LocalizedError`(见 domain/workflows/executors/feishu._Translated)也接不住。
    """
    detail = _detail_of(data)
    status = data.get(_HTTP_STATUS)
    if status is not None and f"HTTP {status}" not in detail:
        detail = f"{detail} (HTTP {status})" if detail else f"HTTP {status}"
    said = {"detail": detail, "code": data.get("code"), "msg": data.get("msg"), "status": status}
    #: 空的那几栏不传:它们要么翻不出东西,要么会在落库时变成字符串 "None"(见 core/i18n.stored_param)。
    raise FeishuError(key, **{name: value for name, value in said.items() if value not in (None, "")})


def _resend_budget(method: str, url: str) -> int:
    """这次调用允许自动重发几次(不含首次)。

    **会留下可见副本的那几条(发消息 / 改卡片 / 加表情)一律 0。** 重发一遍就是群里多一条消息、
    多一个表情,而飞书消息 API 最常见的限流回法恰好是 **HTTP 429 + code 230020** —— 仓库那条判据
    (`core.http_retry.status_resend_is_safe`)对 429 是**放行**的:它判的是"供应商会不会多做一次并
    多收一次钱",不是"用户会不会看到两条"。全仓此前一次都不自动重发,这条性质得保住。

    **不会留下可见副本的那几条**交给仓库那套:列群 / 下载是 GET(幂等,遇 429 / 5xx 都重发),
    取令牌是"重发只是再拿一个令牌"的 POST(非幂等,只在对方**明说没处理这一次**,也就是
    429 / 503 / 529 时重发)。

    **两种的次数都是飞书自己的上限,不是设置页那个数**(见 `FEISHU_MAX_RESENDS`):设置页那一栏是
    AI 连接的,而它落在飞书这里表现为"群列表多转几十秒",或者"取令牌要不要再试一次由 AI 配置决定"。
    """
    if url.startswith(TOKEN_URL):
        #: 取令牌没有可见副本、也不产生费用:它归飞书自己管,不读设置页那个数(见 FEISHU_MAX_RESENDS)。
        return FEISHU_MAX_RESENDS
    if method.upper() == "GET":
        return FEISHU_MAX_RESENDS
    return 0


# --- tenant token cache (per bot, refreshed with safety margin) -------------

_token_lock = threading.Lock()
_token_cache: dict[str, tuple[str, float]] = {}


def get_tenant_access_token(bot: FeishuBot, force: bool = False) -> str:
    with _token_lock:
        cached = _token_cache.get(bot.id)
        if cached and not force and cached[1] > time.time() + 120:
            return cached[0]
    #: 取令牌是 POST,但重发只是**再拿一个令牌**(没有可见副本),所以交给仓库那套重试策略:
    #: 非幂等请求只在对方明说没处理这一次(429 / 503 / 529)时重发。**次数是飞书自己的**
    #: (`FEISHU_MAX_RESENDS`),不是设置页那个 AI 连接的重试次数(见 _resend_budget)。
    with RetryingClient(timeout=15.0, max_retries=_resend_budget("POST", TOKEN_URL)) as client:
        response = client.post(TOKEN_URL, json={"app_id": bot.app_id, "app_secret": bot.app_secret})
        data = _payload(response)
    if data.get("code") != 0:
        _fail("feishuErr_token", data)
    token = str(data.get("tenant_access_token") or "")
    if not token:
        #: 说成功却没给令牌(网关改写、上游异常)。这一条**也必须是我们自己的错误**:KeyError 冲出去,
        #: 和 HTTPStatusError / JSONDecodeError 是同一类 —— 执行器接不住,失败原因里没有原文。
        raise FeishuError("feishuErr_token", detail=_body_head(response), status=response.status_code)
    with _token_lock:
        _token_cache[bot.id] = (token, time.time() + float(data.get("expire") or 7200))
    return token


def call_api(bot: FeishuBot, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    def _call(token: str) -> dict[str, Any]:
        with RetryingClient(timeout=15.0, max_retries=_resend_budget(method, url)) as client:
            response = client.request(method, url, headers={"Authorization": f"Bearer {token}"}, json=body)
            return _payload(response)

    data = _call(get_tenant_access_token(bot))
    if data.get("code") in _TOKEN_INVALID:  # 令牌半路过期:换一个新的再来一次(见 _TOKEN_INVALID)
        data = _call(get_tenant_access_token(bot, force=True))
    return data


def _message_id(data: dict[str, Any]) -> str:
    """发出去那条消息的 id(`om_…`)。飞书没给就是空串 —— 调用方照旧按"发出去了"算。"""
    return str((data.get("data") or {}).get("message_id") or "")


def send_text(bot: FeishuBot, chat_id: str, text: str, *, receive_id_type: str = "chat_id") -> str:
    """发一条文字,返回它的 message_id。`receive_id_type` 是 `chat_id`(会话)或 `open_id`(私聊某个人)。"""
    data = call_api(
        bot,
        "POST",
        f"{SEND_URL}?receive_id_type={receive_id_type}",
        {"receive_id": chat_id, "msg_type": "text", "content": json.dumps({"text": text})},
    )
    if data.get("code") != 0:
        _fail("feishuErr_sendText", data)
    return _message_id(data)


def send_card(bot: FeishuBot, chat_id: str, card: dict[str, Any], *, receive_id_type: str = "chat_id") -> str:
    """发一张交互卡片,返回它的 message_id。`receive_id_type` 是 `chat_id`(会话,默认)或 `open_id`(私聊某个人)——
    工作流的确认卡两条路都要:这一轮**来自飞书会话**就发回那个群,不是的话发给负责人本人。"""
    data = call_api(
        bot,
        "POST",
        f"{SEND_URL}?receive_id_type={receive_id_type}",
        {"receive_id": chat_id, "msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False)},
    )
    if data.get("code") != 0:
        _fail("feishuErr_sendCard", data)
    return _message_id(data)


#: 飞书「发送消息」的上限:卡片 / 富文本**请求体最大 30 KB**,文本 150 KB
#: (官方文档「发送消息 → 请求体 → content」,错误码 230025)。
#: 这里量的是**真正要发出去的请求体**(照 httpx 的序列化方式),不是正文字节 —— 引号 / 换行
#: 在 JSON 里要转义,一段代码块能让同样的正文大出两成,只量正文就会在那一刻撞上限。
#: 29_000 留 1 KB 余量给真实收件 id(`_RECEIVE_ID_PLACEHOLDER` 已按更长的算)。
CARD_PAYLOAD_MAX_BYTES = 29_000

#: 量请求体时用的收件 id 占位。真实 chat_id / open_id 一般 30~60 字符,这里给 67 —— 偏大即安全。
_RECEIVE_ID_PLACEHOLDER = "oc_" + "0" * 64


def markdown_card(content: str, *, index: int = 1, total: int = 1) -> dict[str, Any]:
    """一张只放正文的交互卡片:一个 `div`、一个 `lark_md`,正文原样。

    `lark_md` 是飞书卡片(JSON 1.0)普通文本组件支持的 Markdown 文本类型 —— 加粗、斜体、
    删除线、链接、列表、代码块这些会按排版渲染,而不是显示成源码(标题 / 表格 / 引用是
    JSON 2.0 的 `markdown` 组件才有的语法,这里不换卡片结构)。

    `total > 1` 时加一格标题栏写 `（i/n）`:超长正文拆成几张卡时,先看哪张、后看哪张
    才说得清。**正文一个字都不动** —— 编号在标题栏,不在正文里。
    """
    card: dict[str, Any] = {
        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": content}}],
    }
    if total > 1:
        card["header"] = {
            "template": "grey",
            "title": {"tag": "plain_text", "content": f"（{index}/{total}）"},
        }
    return card


def _card_text_bytes(content: str) -> int:
    """这张卡发出去时**请求体**有多少字节。按最宽的编号头算,给实际编号留余量。

    照 `httpx` 的 JSON 序列化方式量(`ensure_ascii=False`、紧凑分隔符):这样正文里的
    引号 / 换行 / 反斜杠在 JSON 里的那层转义也真的算进去。
    """
    card = markdown_card(content, index=999, total=999)
    body = {
        "receive_id": _RECEIVE_ID_PLACEHOLDER,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }
    return len(json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _fits_one_card(content: str) -> bool:
    return _card_text_bytes(content) <= CARD_PAYLOAD_MAX_BYTES


def _hard_split_one_line(text: str) -> list[str]:
    """一整行就超过上限(压缩过的 JSON、没有句读的长段):按字符二分,切到装得下为止。"""
    pieces: list[str] = []
    rest = text
    while rest:
        if _fits_one_card(rest):
            pieces.append(rest)
            break
        low, high = 1, len(rest)
        while low < high:
            middle = (low + high + 1) // 2
            if _fits_one_card(rest[:middle]):
                low = middle
            else:
                high = middle - 1
        pieces.append(rest[:low])
        rest = rest[low:]
    return pieces


def markdown_chunks(text: str) -> list[str]:
    """把正文切成**每张卡都装得下**的几段。拼起来与原文逐字相等 —— 不截断、不重排。

    优先在行边界切(代码块 / 列表不会被从中间断开);某一整行本身就超限时才按字符切开。
    空正文给一段空串,让调用方照旧发一张(能不能渲染由飞书说,失败还有下面那道降级)。
    """
    if not text:
        return [""]
    if _fits_one_card(text):
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        candidate = current + line
        if current and not _fits_one_card(candidate):
            chunks.append(current)
            current = line
        else:
            current = candidate
        #: 一整行自己就超限时在这里切开 —— 不能等下一行才发现。
        if not _fits_one_card(current):
            pieces = _hard_split_one_line(current)
            chunks.extend(pieces[:-1])
            current = pieces[-1]
    if current:
        chunks.append(current)
    return chunks


def send_markdown(bot: FeishuBot, chat_id: str, text: str, *, receive_id_type: str = "chat_id") -> list[str]:
    """**长正文**发成交互卡片,返回每条消息的 message_id(单张卡就是一个元素)。

    这是"长正文"唯一的一处实现 —— 智能体的回复与工作流运行结果都走它;短通知继续用
    `send_text`(任务回执、绑定提示、"看不了这种消息"),少一次卡片失败面。

    两道保险:

    - **卡片发不出去**(飞书拒了、网络抖动、卡片构造失败)→ 同一段内容改用 `send_text`
      重发,并把原因写进日志。消息不许凭空消失;逐段降级,已发出去的卡不会重发一遍。
    - **超长** → 按飞书 30 KB 的卡片请求体上限分多张卡(`markdown_chunks`),每张带
      `（i/n）` 编号,按原顺序发出,拼起来等于原文。**不静默截断。**

    这一轮不做流式 / 分段更新:调用方原来一次发多少还是多少,只是每一段的消息类型变了。
    """
    try:
        chunks = markdown_chunks(text)
    except Exception as exc:  # noqa: BLE001 —— 构造失败也只降级,不许把消息弄丢
        logger.warning("feishu markdown card build failed (%s: %s); sending as text", type(exc).__name__, exc)
        return [send_text(bot, chat_id, text, receive_id_type=receive_id_type)]

    total = len(chunks)
    sent: list[str] = []
    for index, chunk in enumerate(chunks, 1):
        try:
            card = markdown_card(chunk, index=index, total=total)
            sent.append(send_card(bot, chat_id, card, receive_id_type=receive_id_type))
        except Exception as exc:  # noqa: BLE001 —— 见 docstring:降级成文字,而不是丢掉
            logger.warning(
                "feishu markdown card %d/%d failed (%s: %s); resending that part as text",
                index, total, type(exc).__name__, exc,
            )
            label = f"（{index}/{total}）\n" if total > 1 else ""
            sent.append(send_text(bot, chat_id, label + chunk, receive_id_type=receive_id_type))
    return sent


def update_card(bot: FeishuBot, message_id: str, card: dict[str, Any]) -> None:
    """**就地换掉**一张已经发出去的交互卡片(`PATCH im/v1/messages/:message_id`)。

    飞书只让改"这张应用自己发的、而且那条消息是交互卡片"的消息 —— 降级发出去的那种纯文字消息
    改不了,调用方据此再补一条(见 integrations/feishu/approvals.settle_run_approval)。
    """
    data = call_api(bot, "PATCH", f"{SEND_URL}/{message_id}", {"content": json.dumps(card, ensure_ascii=False)})
    if data.get("code") != 0:
        _fail("feishuErr_updateCard", data)


def list_chats(bot: FeishuBot, *, limit: int = 200) -> list[dict[str, str]]:
    """这个机器人所在的群:`[{"id": "oc_…", "name": "…"}]`,按飞书给的顺序。

    飞书按 `page_token` 分页(`has_more` / `page_token`),这里跟到底 —— 但当心"跟到底"也可能是
    几千个群:调用方给 `limit` 划上界,到这里就停(不再要下一页)。服务端要是 `has_more=true`
    却一直回**同一个 token**,再拉就是原地转圈:见过的 token 直接停(见下面那一处)。
    """
    found: list[dict[str, str]] = []
    cap = max(1, int(limit))
    page_token = ""
    seen_tokens: set[str] = set()
    while True:
        query = f"?page_size={CHATS_PAGE_SIZE}" + (f"&page_token={quote(page_token)}" if page_token else "")
        data = call_api(bot, "GET", f"{CHATS_URL}{query}")
        if data.get("code") != 0:
            _fail("feishuErr_listChats", data)
        page = data.get("data") or {}
        for item in page.get("items") or []:
            if not isinstance(item, dict):
                continue
            chat_id = str(item.get("chat_id") or "").strip()
            if chat_id:
                found.append({"id": chat_id, "name": str(item.get("name") or "").strip() or chat_id})
        page_token = str(page.get("page_token") or "").strip()
        if len(found) >= cap or not page.get("has_more") or not page_token:
            return found[:cap]
        if page_token in seen_tokens:
            #: 这个 token 我们已经拿它要过一页了 —— 再要就是同一页,而 `has_more` 永远为真,拉不完。
            #: 把已经拿到的交出去(不给空清单,也不假装拉完了)。
            logger.warning(
                "feishu list_chats: page_token %r came back twice, stopping after %d groups", page_token, len(found)
            )
            return found[:cap]
        seen_tokens.add(page_token)


# --- 反应(reaction)= 飞书的「对方正在输入」(前身项目同款) ----------------
#
# 飞书没有 Slack/iMessage 那种原生输入指示器;给用户发来的那条消息加 emoji_type="Typing"
# 的反应,客户端会渲染成动画输入指示 —— 处理完删掉,失败换 "CrossMark"。全程 best-effort:
# 缺个小徽章纯属装饰问题,绝不能反过来弄坏回复链路。

REACTION_TYPING = "Typing"
REACTION_FAILURE = "CrossMark"


def add_reaction(bot: FeishuBot, message_id: str, emoji_type: str) -> str | None:
    """Best-effort; returns the reaction_id needed to remove it later, or None."""
    try:
        return add_reaction_strict(bot, message_id, emoji_type) or None
    except Exception:  # noqa: BLE001
        logger.warning("feishu add_reaction %s on %s failed", emoji_type, message_id, exc_info=True)
        return None


def add_reaction_strict(bot: FeishuBot, message_id: str, emoji_type: str) -> str:
    """加一个表情,**加不上就抛**。返回 reaction_id。

    「回个表情」那个节点要的是这一份:`add_reaction` 的"尽力而为"服务的是输入指示器那种点缀
    (坏了也不能反过来弄坏回复链路),而一个专门用来加表情的节点加不上时**必须说**。
    """
    data = call_api(
        bot, "POST", f"{SEND_URL}/{message_id}/reactions", {"reaction_type": {"emoji_type": emoji_type}}
    )
    if data.get("code") != 0:
        _fail("feishuErr_reaction", data)
    return str((data.get("data") or {}).get("reaction_id") or "")


def remove_reaction(bot: FeishuBot, message_id: str, reaction_id: str) -> bool:
    """Best-effort; never raises."""
    try:
        data = call_api(bot, "DELETE", f"{SEND_URL}/{message_id}/reactions/{reaction_id}")
        return data.get("code") == 0
    except Exception:  # noqa: BLE001
        logger.warning("feishu remove_reaction %s on %s failed", reaction_id, message_id, exc_info=True)
        return False


@dataclass(frozen=True)
class DownloadedResource:
    """从消息里取回来的一份资源:字节、它叫什么、飞书说它是什么类型。

    名字来自响应的 `Content-Disposition`(飞书会把原始文件名放在那儿)。取不回来时按 `file_key`
    与类型兜一个 —— **素材库按名字/类型认种类**(见 media/probe.guess_kind):没有名字也没有类型
    的字节会被当成视频去探测,然后被拒收。
    """

    data: bytes
    filename: str
    content_type: str


def _suffix_for(content_type: str) -> str:
    """`content-type` → 扩展名。用标准库那张表,不自己编;认不出就没有。

    `application/octet-stream` 除外:它的意思是"我不知道这是什么字节",给它按一个 `.bin`
    等于编一个类型出来。标准库对它有映射,这里挡掉。
    """
    mime = (content_type or "").split(";")[0].strip().lower()
    if not mime or mime == "application/octet-stream":
        return ""
    return mimetypes.guess_extension(mime) or ""


def _resource_name(disposition: str, file_key: str, kind: str, content_type: str = "") -> str:
    """`Content-Disposition` 里的文件名;没有就按 file_key 与类型兜一个**认得出**的名字。

    `content-type` 也参与:飞书对 file 类消息**不一定**给 `Content-Disposition`,而素材库按
    名字 / 类型认种类(见 media/probe.guess_kind)—— 一个没有扩展名的 `feishu-xxxxxxxx` 会先被
    当成视频去探测,素材库里可能直接进不去。推不出扩展名就保持原样(不编)。
    """
    for marker in ("filename*=UTF-8''", 'filename="', "filename="):
        at = disposition.find(marker)
        if at < 0:
            continue
        tail = disposition[at + len(marker):]
        name = tail.split(";")[0].strip().strip('"').strip()
        if name:
            return name
    suffix = _suffix_for(content_type) or (".jpg" if kind == "image" else "")
    return f"feishu-{file_key[-8:]}{suffix}"


def download_message_resource_named(bot: FeishuBot, message_id: str, file_key: str, kind: str) -> DownloadedResource:
    """把消息里的图片/文件取回来,**连它的名字和类型一起**。走 tenant token,和其它 API 调用同一条路。"""

    url = f"{API_BASE}/im/v1/messages/{message_id}/resources/{file_key}"

    def _fetch(token: str) -> httpx.Response:
        #: 下载是 GET:限流(429)/ 网关(5xx)重发一遍不会多取一份东西(见 _resend_budget)。
        with RetryingClient(timeout=60.0, max_retries=_resend_budget("GET", url)) as client:
            return client.get(url, params={"type": kind}, headers={"Authorization": f"Bearer {token}"})

    response = _fetch(get_tenant_access_token(bot))
    if response.status_code == 401:  # token 半路过期
        response = _fetch(get_tenant_access_token(bot, force=True))
    if response.status_code != 200:
        #: body 里飞书的 code/msg 也要带出来(限流 230020、权限 99991613…)。文案有两个槽:
        #: `{status}` 只放状态码、`{detail}` 放飞书那句原文 —— 此前只有一个槽,原文被拼进了状态码
        #: 那一格,于是"状态码"那一格说的不是状态码。
        #: **两栏都给**:模板里两个槽都在,少给一个会让 `t()` 把整句的占位符一起抹掉。
        body = _json_of(response)
        said = _detail_of(body) if isinstance(body, dict) else ""
        #: 网关连一个字节都没回时正文是空的(那时括号里会留下一个孤零零的分隔符)——
        #: 退到 HTTP 自己那句状态文本。
        detail = said or _body_head(response) or response.reason_phrase
        params: dict[str, Any] = {"status": f"HTTP {response.status_code}", "detail": detail}
        if isinstance(body, dict):
            params["code"], params["msg"] = body.get("code"), body.get("msg")
        raise FeishuError("feishuErr_download", **params)
    content_type = (response.headers.get("content-type") or "").split(";")[0].strip()
    return DownloadedResource(
        data=response.content,
        filename=_resource_name(response.headers.get("content-disposition", ""), file_key, kind, content_type),
        content_type=content_type,
    )


def download_message_resource(bot: FeishuBot, message_id: str, file_key: str, kind: str) -> bytes:
    """只要字节的那条老路(入站那条链路在用):它就是上面那一份 `.data`。"""
    return download_message_resource_named(bot, message_id, file_key, kind).data
